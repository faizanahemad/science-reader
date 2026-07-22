"""
Tool registry framework for LLM tool calling.

Why this exists
---------------
Modern LLMs support tool/function calling — the model can request execution of
named tools during a conversation turn. This module provides:

- Dataclasses describing tool definitions, call results, and execution context.
- A ``ToolRegistry`` that stores definitions, converts them to OpenAI API
  ``tools`` parameter format, and dispatches tool execution.
- A ``@register_tool`` decorator for convenient registration.
- Three built-in tool stubs: ``ask_clarification``, ``web_search``,
  ``document_lookup``.

This module intentionally avoids importing from ``Conversation.py`` or endpoint
modules to prevent circular dependencies. It is designed to be imported by
``code_common/call_llm.py`` and ``Conversation.py``.

Plan references
~~~~~~~~~~~~~~~
- p1-tool-registry (framework)
- p1-builtin-tools-define (initial tool definitions)
"""

from __future__ import annotations

import functools
import json
import traceback
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "tools",
    logger_level=10,
    time_logger_level=10,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_RESULT_TRUNCATION_LIMIT = 50000
"""Hard cap (in characters) on the length of a tool result string sent back to the LLM."""

DEFAULT_ENABLED_TOOLS = ["ask_clarification", "pkb_nl_command"]
"""Tools that should be enabled by default in the UI tool selector.

These tools are automatically selected when the user resets settings to defaults.
Both the backend (this constant) and frontend (chat.js resetSettingsToDefaults) must agree.
"""



def _truncate_result(text: str, max_len: int = TOOL_RESULT_TRUNCATION_LIMIT) -> str:
    """Truncate *text* to *max_len* characters, appending an ellipsis marker.

    Parameters
    ----------
    text:
        The raw tool result string.
    max_len:
        Maximum allowed character length (default ``TOOL_RESULT_TRUNCATION_LIMIT``).

    Returns
    -------
    str
        The (possibly truncated) text.
    """
    if len(text) <= max_len:
        return text
    suffix = "\n... [truncated, result too long]"
    return text[: max_len - len(suffix)] + suffix


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Context passed to every tool handler so it can access conversation state.

    Attributes
    ----------
    conversation_id:
        Unique identifier of the current conversation.
    user_email:
        Email of the authenticated user (may be empty for anonymous).
    keys:
        API keys and credentials the tool may need (e.g. search API key).
    conversation_summary:
        A short summary of the conversation so far, useful for context.
    recent_messages:
        The last N messages (list of dicts) for tools that need chat history.
    """

    conversation_id: str
    user_email: str = ""
    keys: dict = field(default_factory=dict)
    conversation_summary: str = ""
    recent_messages: list = field(default_factory=list)
    model_overrides: dict = field(default_factory=dict)
    workspace_id: str = ""
    target_message_id: str = ""  # Set by doubt flow so propose_answer_edit knows which message to target


@dataclass
class ToolCallResult:
    """Result of executing a tool handler.

    Attributes
    ----------
    tool_id:
        The tool call ID from the API response (e.g. ``"call_abc123"``).
    tool_name:
        Name of the tool that was invoked.
    result:
        The result text to feed back to the LLM as a tool message.
    error:
        Error message if the tool failed; ``None`` on success.
    needs_user_input:
        ``True`` if the agentic loop should pause and wait for user input
        (used by interactive tools like ``ask_clarification``).
    ui_schema:
        Optional schema/payload for the UI to render (e.g. clarification
        questions with MCQ options).  ``None`` for non-interactive tools.
    """

    tool_id: str
    tool_name: str
    result: str
    error: Optional[str] = None
    needs_user_input: bool = False
    ui_schema: Optional[dict] = None


@dataclass
class ToolDefinition:
    """A registered tool that the LLM can invoke.

    Attributes
    ----------
    name:
        Machine-readable tool name (e.g. ``"web_search"``).
    description:
        Human-readable description included in the OpenAI API request.
    parameters:
        JSON Schema dict defining the tool's accepted parameters.
    handler:
        The callable invoked when the LLM calls this tool.
        Signature: ``(args: dict, context: ToolContext) -> ToolCallResult``.
    is_interactive:
        ``True`` for tools that require pausing for user input.
    category:
        Grouping category for UI settings (e.g. ``"search"``,
        ``"clarification"``).
    """

    name: str
    description: str
    parameters: dict
    handler: Callable
    is_interactive: bool = False
    category: str = "general"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Registry for LLM-callable tools.

    Manages tool definitions, converts them to OpenAI API format,
    and executes tool handlers when the LLM invokes them.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    # -- Registration -------------------------------------------------------

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a tool definition. Overwrites if name already exists."""
        if tool_def.name in self._tools:
            logger.warning("Overwriting existing tool registration: %s", tool_def.name)
        self._tools[tool_def.name] = tool_def
        logger.info(
            "Registered tool: %s (category=%s, interactive=%s)",
            tool_def.name,
            tool_def.category,
            tool_def.is_interactive,
        )

    # -- Lookup -------------------------------------------------------------

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name. Returns ``None`` if not found."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        """Get tools filtered by category."""
        return [t for t in self._tools.values() if t.category == category]

    # -- OpenAI API conversion ----------------------------------------------

    def get_openai_tools_param(
        self,
        enabled_names: Optional[List[str]] = None,
    ) -> List[dict]:
        """Convert registered tools to OpenAI API ``tools`` parameter format.

        Parameters
        ----------
        enabled_names:
            If provided, only include tools whose names are in this list.
            If ``None``, include **all** registered tools.

        Returns
        -------
        list[dict]
            List of dicts in the format expected by the OpenAI chat
            completions ``tools`` parameter::

                [{"type": "function",
                  "function": {"name": ..., "description": ...,
                               "parameters": ...}}]
        """
        tools_to_include = self._tools.values()
        if enabled_names is not None:
            tools_to_include = [t for t in tools_to_include if t.name in enabled_names]

        result = []
        for tool_def in tools_to_include:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "parameters": tool_def.parameters,
                    },
                }
            )
        return result

    # -- Execution ----------------------------------------------------------

    def execute(
        self,
        name: str,
        args: dict,
        context: ToolContext,
        tool_call_id: str = "",
    ) -> ToolCallResult:
        """Execute a tool handler by name.

        Fail-open: never raises. On any error, returns a ``ToolCallResult``
        with the ``error`` field populated so the LLM can gracefully handle it.

        Parameters
        ----------
        name:
            Registered tool name.
        args:
            Arguments dict parsed from the LLM's tool call.
        context:
            Execution context (conversation state, keys, etc.).
        tool_call_id:
            The ``tool_call.id`` from the API response, threaded through
            to the result so callers can match requests to responses.

        Returns
        -------
        ToolCallResult
        """
        tool_def = self._tools.get(name)
        if tool_def is None:
            error_msg = f"Unknown tool: {name}"
            logger.error(error_msg)
            return ToolCallResult(
                tool_id=tool_call_id,
                tool_name=name,
                result=error_msg,
                error=error_msg,
            )

        try:
            time_logger.info(
                "Executing tool: %s with args: %s", name, json.dumps(args)[:200]
            )
            result = tool_def.handler(args, context)

            # Ensure handler returned a ToolCallResult
            if not isinstance(result, ToolCallResult):
                result = ToolCallResult(
                    tool_id=tool_call_id,
                    tool_name=name,
                    result=str(result),
                )

            # Fill in IDs if handler didn't set them
            if not result.tool_id:
                result.tool_id = tool_call_id
            if not result.tool_name:
                result.tool_name = name

            # Truncate oversized results
            result.result = _truncate_result(result.result)

            time_logger.info(
                "Tool %s completed (len=%d, error=%s, needs_input=%s)",
                name,
                len(result.result),
                result.error,
                result.needs_user_input,
            )
            return result

        except Exception:
            tb = traceback.format_exc()
            error_msg = f"Tool '{name}' raised an exception:\n{tb}"
            logger.error(error_msg)
            return ToolCallResult(
                tool_id=tool_call_id,
                tool_name=name,
                result=f"Error executing tool '{name}'. The tool encountered an internal error.",
                error=error_msg,
            )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

TOOL_REGISTRY = ToolRegistry()


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def register_tool(
    name: str,
    description: str,
    parameters: dict,
    is_interactive: bool = False,
    category: str = "general",
):
    """Decorator to register a function as a tool handler.

    Usage::

        @register_tool(
            name="web_search",
            description="Search the web for current information",
            parameters={"type": "object", "properties": {...}, "required": [...]},
            category="search",
        )
        def handle_web_search(args: dict, context: ToolContext) -> ToolCallResult:
            ...

    Parameters
    ----------
    name:
        Unique tool name.
    description:
        Human-readable description for the OpenAI API.
    parameters:
        JSON Schema dict defining the tool's parameters.
    is_interactive:
        Whether the tool requires pausing for user input.
    category:
        Grouping category string.
    """

    def decorator(fn: Callable) -> Callable:
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            is_interactive=is_interactive,
            category=category,
        )
        TOOL_REGISTRY.register(tool_def)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Built-in tool definitions (stubs)
# ---------------------------------------------------------------------------


@register_tool(
    name="ask_clarification",
    description=(
        "Ask the user clarifying questions to better understand their request. "
        "Use when the user explicitly asks you to ask questions, or when you "
        "detect significant ambiguity that would affect the quality of your response."
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The clarifying question to ask",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Multiple choice options (2-5 options). "
                                "Include an 'Other' option if appropriate."
                            ),
                        },
                    },
                    "required": ["question", "options"],
                },
                "description": "List of clarifying questions with MCQ options",
                "minItems": 1,
                "maxItems": 5,
            },
        },
        "required": ["questions"],
    },
    is_interactive=True,
    category="clarification",
)
def handle_ask_clarification(args: dict, context: ToolContext) -> ToolCallResult:
    """Handle the ask_clarification tool call.

    This is an interactive tool — it does NOT execute any logic. Instead it
    returns ``needs_user_input=True`` so the agentic loop pauses and the UI
    renders the clarification questions for the user to answer.

    Parameters
    ----------
    args:
        Parsed arguments from the LLM containing ``questions`` list.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        With ``needs_user_input=True`` and ``ui_schema`` containing the
        questions payload.
    """
    questions = args.get("questions", [])
    logger.info("ask_clarification invoked with %d question(s)", len(questions))

    return ToolCallResult(
        tool_id="",
        tool_name="ask_clarification",
        result="Waiting for user to answer clarification questions.",
        needs_user_input=True,
        ui_schema=args,
    )


@register_tool(
    name="web_search",
    description=(
        "Search the web for current information not in training data or context. "
        "Provide focused query + context for better results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "context": {
                "type": "string",
                "description": (
                    "Additional context to help the search (background, intent, "
                    "what kind of information is needed). Provide as much relevant "
                    "context as possible for better results."
                ),
                "default": "",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    is_interactive=False,
    category="search",
)
def handle_web_search(args: dict, context: ToolContext) -> ToolCallResult:
    """Search the web using the Perplexity search agent infrastructure.

    Instantiates a ``PerplexitySearchAgent`` (falling back to ``JinaSearchAgent``)
    from ``agents/search_and_information_agents.py`` and collects the streamed
    output.  The query and context are pre-formatted as a code block so that
    ``extract_queries_contexts()`` picks them up directly, bypassing the internal
    LLM query-generation step.  The agent runs in headless mode (no combiner LLM,
    raw search results returned).

    Keys are taken from ``context.keys``; if those are empty the
    environment-variable-based ``keyParser`` is used as a fallback.

    Parameters
    ----------
    args:
        Parsed arguments containing ``query``, optionally ``context`` and
        ``num_results``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Search results or an error description.
    """
    query = args.get("query", "")
    search_context = args.get("context", "") or ""
    num_results = args.get("num_results", 5)
    logger.info("web_search invoked: query=%r, num_results=%d", query, num_results)

    if not query.strip():
        return ToolCallResult(
            tool_id="", tool_name="web_search",
            error="query is required and must not be empty.",
        )

    try:
        # Resolve API keys: prefer context.keys, fall back to env vars
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        # Resolve model name
        from common import CHEAP_LLM
        model_name = CHEAP_LLM[0]

        # Map num_results to detail_level (1-4)
        detail_level = 1 if num_results <= 3 else 2 if num_results <= 6 else 3

        # Try Perplexity first, fall back to Jina
        agent = None
        try:
            from agents.search_and_information_agents import PerplexitySearchAgent
            agent = PerplexitySearchAgent(
                keys,
                model_name=model_name,
                detail_level=detail_level,
                timeout=120,
                headless=True,
            )
        except Exception:
            logger.warning("PerplexitySearchAgent unavailable, trying JinaSearchAgent")
            try:
                from agents.search_and_information_agents import JinaSearchAgent
                agent = JinaSearchAgent(
                    keys,
                    model_name=model_name,
                    detail_level=detail_level,
                    timeout=240,
                    headless=True,
                )
            except Exception as inner_exc:
                return ToolCallResult(
                    tool_id="", tool_name="web_search",
                    error=f"No search agent available: {inner_exc}",
                )

        # Pre-format query+context as a code block so the agent's
        # extract_queries_contexts() picks it up directly, bypassing the
        # internal LLM query-generation step entirely.
        # Use repr() to safely escape quotes for ast.literal_eval.
        agent_input = (
            f"```python\n"
            f"[({repr(query)}, {repr(search_context)})]\n"
            f"```"
        )
        logger.info('web_search: bypassing LLM query gen, agent_input=%s', agent_input[:200])

        # Collect streamed output (agents yield dicts with 'text' key)
        result_parts: list[str] = []
        for chunk in agent(agent_input, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            if text:
                result_parts.append(text)

        result_text = "".join(result_parts)
        if not result_text.strip():
            result_text = "Search returned no results."

        return ToolCallResult(
            tool_id="",
            tool_name="web_search",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("web_search failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="web_search",
            error=f"Web search failed: {exc}",
        )


@register_tool(
    name="document_lookup",
    description=(
        "Search the user's uploaded documents or global documents for specific "
        "information. Use when the user's question relates to content in their "
        "documents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in the documents",
            },
            "doc_scope": {
                "type": "string",
                "enum": ["conversation", "global", "all"],
                "description": (
                    "Which documents to search: conversation-level, global, or all"
                ),
                "default": "all",
            },
        },
        "required": ["query"],
    },
    is_interactive=False,
    category="documents",
)
def handle_document_lookup(args: dict, context: ToolContext) -> ToolCallResult:
    """Search the user's uploaded or global documents for information.

    Loads conversation-scoped documents (via ``Conversation.uploaded_documents_list``)
    and/or global documents (via ``database.global_docs``) depending on ``doc_scope``.
    For each document found, calls ``DocIndex.semantic_search_document`` to retrieve
    relevant passages matching the query.

    Parameters
    ----------
    args:
        Parsed arguments containing ``query`` and optionally ``doc_scope``.
    context:
        Tool execution context (needs ``conversation_id`` and ``user_email``).

    Returns
    -------
    ToolCallResult
        Matching document passages or an error description.
    """
    query = args.get("query", "")
    doc_scope = args.get("doc_scope", "all")
    logger.info("document_lookup invoked: query=%r, scope=%s", query, doc_scope)

    if not query.strip():
        return ToolCallResult(
            tool_id="", tool_name="document_lookup",
            error="query is required and must not be empty.",
        )

    try:
        import os
        import json as _json

        # Resolve API keys for DocIndex embedding/LLM operations
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        storage_dir = os.getenv("STORAGE_DIR", "storage")
        conversation_folder = os.path.join(os.getcwd(), storage_dir, "conversations")
        users_dir = os.path.join(os.getcwd(), storage_dir, "users")

        result_sections: list[str] = []

        # --- Conversation-scoped documents ---
        if doc_scope in ("conversation", "all") and context.conversation_id:
            try:
                from Conversation import Conversation

                conv_path = os.path.join(conversation_folder, context.conversation_id)
                if os.path.isdir(conv_path):
                    conv = Conversation.load_local(conv_path)
                    if conv is not None:
                        doc_list = conv.get_field("uploaded_documents_list")
                        if doc_list:
                            for entry in doc_list:
                                doc_id, doc_storage, _src, _dn = conv._doc_entry_fields(entry)
                                display = _dn if _dn is not None else doc_id
                                try:
                                    from DocIndex import DocIndex
                                    doc = DocIndex.load_local(doc_storage)
                                    if doc is None:
                                        continue
                                    doc.set_api_keys(keys)
                                    passage = doc.semantic_search_document(
                                        query, token_limit=2048
                                    )
                                    if passage and passage.strip():
                                        result_sections.append(
                                            f"### Document: {display}\n{passage}"
                                        )
                                except Exception as doc_exc:
                                    logger.warning(
                                        "Failed to query conv doc %s: %s",
                                        doc_id, doc_exc,
                                    )
            except Exception as conv_exc:
                logger.warning("Failed to load conversation docs: %s", conv_exc)

        # --- Global documents ---
        if doc_scope in ("global", "all") and context.user_email:
            try:
                from database.global_docs import list_global_docs

                rows = list_global_docs(
                    users_dir=users_dir,
                    user_email=context.user_email,
                )
                for row in rows:
                    doc_storage = row.get("doc_storage", "")
                    display = row.get("display_name") or row.get("title") or row.get("doc_id", "")
                    if not doc_storage:
                        continue
                    try:
                        from DocIndex import DocIndex
                        doc = DocIndex.load_local(doc_storage)
                        if doc is None:
                            continue
                        doc.set_api_keys(keys)
                        passage = doc.semantic_search_document(
                            query, token_limit=2048
                        )
                        if passage and passage.strip():
                            result_sections.append(
                                f"### Global Doc: {display}\n{passage}"
                            )
                    except Exception as doc_exc:
                        logger.warning(
                            "Failed to query global doc %s: %s",
                            display, doc_exc,
                        )
            except Exception as glob_exc:
                logger.warning("Failed to load global docs: %s", glob_exc)

        if not result_sections:
            result_text = "No matching content found in documents."
        else:
            result_text = "\n\n".join(result_sections)

        return ToolCallResult(
            tool_id="",
            tool_name="document_lookup",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("document_lookup failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="document_lookup",
            error=f"Document lookup failed: {exc}",
        )


# ---------------------------------------------------------------------------
# MCP Search Tools (category: search)
# ---------------------------------------------------------------------------


@register_tool(
    name="perplexity_search",
    description=(
        "Search using Perplexity AI models for web information. "
        "Higher detail_level (1-4) progressively adds reasoning and "
        "deep-research models for more thorough results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query or question"},
            "context": {
                "type": "string",
                "description": "Additional context to help the search (background, intent, what kind of information is needed). Perplexity can use a good amount of context to provide better results, so provide as much relevant context as possible.",
                "default": "",
            },
            "detail_level": {
                "type": "integer",
                "description": "Search depth level 1-4 (1=quick, 4=deep)",
                "default": 1,
            },
        },
        "required": ["query"],
    },
    category="search",
)
def handle_perplexity_search(args: dict, context: ToolContext) -> ToolCallResult:
    """Search using Perplexity AI.

    Instantiates a ``PerplexitySearchAgent`` from
    ``agents/search_and_information_agents.py`` and collects streamed output.
    Keys are taken from ``context.keys``; if empty, ``keyParser`` is used as
    a fallback.

    Parameters
    ----------
    args:
        Parsed arguments containing ``query`` and optionally ``detail_level``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Search results or an error description.
    """
    query = args.get("query", "")
    detail_level = args.get("detail_level", 2)
    logger.info("perplexity_search invoked: query=%r, detail_level=%d", query, detail_level)

    if not query.strip():
        return ToolCallResult(
            tool_id="", tool_name="perplexity_search",
            error="query is required and must not be empty.",
        )

    try:
        # Resolve API keys: prefer context.keys, fall back to env vars
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        # Resolve model name
        from common import CHEAP_LLM
        model_name = CHEAP_LLM[0]

        from agents.search_and_information_agents import PerplexitySearchAgent
        agent = PerplexitySearchAgent(
            keys,
            model_name=model_name,
            detail_level=detail_level,
            timeout=120,
            num_queries=1,  # In tool-calling mode the main LLM already crafted the query, no need for LLM query expansion
            headless=True,
        )

        # In tool-calling mode, the main LLM already has context and crafted a
        # good query.  We pre-format it as a code block so the agent's
        # extract_queries_contexts() picks it up directly, bypassing the internal
        # LLM query-generation step entirely.
        search_context = args.get('context', '') or ''
        # Use repr() to safely escape quotes in query/context for ast.literal_eval
        agent_input = (
            f"```python\n"
            f"[({repr(query)}, {repr(search_context)})]\n"
            f"```"
        )
        logger.info('perplexity_search: bypassing LLM query gen, agent_input=%s', agent_input[:200])

        # Collect streamed output
        result_parts: list[str] = []
        for chunk in agent(agent_input, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            if text:
                result_parts.append(text)

        result_text = "".join(result_parts)
        if not result_text.strip():
            result_text = "Perplexity search returned no results."

        return ToolCallResult(
        tool_id="", tool_name="perplexity_search",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("perplexity_search failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="perplexity_search",
            error=f"Perplexity search failed: {exc}",
        )


@register_tool(
    name="jina_search",
    description=(
        "Search via Jina AI with full page content retrieval (not just snippets). "
        "Summarizes long pages, handles PDFs. Provide query + context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query or question"},
            "context": {
                "type": "string",
                "description": (
                    "Additional context to help the search (background, intent, "
                    "what kind of information is needed). Provide as much relevant "
                    "context as possible for better results."
                ),
                "default": "",
            },
            "detail_level": {
                "type": "integer",
                "description": "Search depth. 1=5 results, 2=8 results, 3+=20 results",
                "default": 1,
            },
        },
        "required": ["query"],
    },
    is_interactive=False,
    category="search",
)
def handle_jina_search(args: dict, context: ToolContext) -> ToolCallResult:
    """Search using Jina AI with full web content retrieval.

    Instantiates a ``JinaSearchAgent`` from
    ``agents/search_and_information_agents.py`` and collects streamed output.
    The query and context are pre-formatted as a code block so that
    ``extract_queries_contexts()`` picks them up directly, bypassing the internal
    LLM query-generation step.  The agent runs in headless mode (no combiner LLM,
    raw search results returned).

    Keys are taken from ``context.keys``; if empty, ``keyParser`` is used as
    a fallback.

    Parameters
    ----------
    args:
        Parsed arguments containing ``query``, optionally ``context`` and
        ``detail_level``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Search results or an error description.
    """
    query = args.get("query", "")
    search_context = args.get("context", "") or ""
    detail_level = args.get("detail_level", 1)
    logger.info("jina_search invoked: query=%r, detail_level=%d", query, detail_level)

    if not query.strip():
        return ToolCallResult(
            tool_id="", tool_name="jina_search",
            error="query is required and must not be empty.",
        )

    try:
        # Resolve API keys: prefer context.keys, fall back to env vars
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        # Resolve model name — use SUPERFAST_LLM for faster per-query summarization
        from common import SUPERFAST_LLM
        model_name = SUPERFAST_LLM[0]

        from agents.search_and_information_agents import JinaSearchAgent
        agent = JinaSearchAgent(
            keys,
            model_name=model_name,
            detail_level=detail_level,
            timeout=240,
            headless=True,
        )

        # Pre-format query+context as a code block so the agent's
        # extract_queries_contexts() picks it up directly, bypassing the
        # internal LLM query-generation step entirely.
        # Use repr() to safely escape quotes for ast.literal_eval.
        agent_input = (
            f"```python\n"
            f"[({repr(query)}, {repr(search_context)})]\n"
            f"```"
        )
        logger.info('jina_search: bypassing LLM query gen, agent_input=%s', agent_input[:200])

        # Collect streamed output
        result_parts: list[str] = []
        for chunk in agent(agent_input, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            if text:
                result_parts.append(text)

        result_text = "".join(result_parts)
        if not result_text.strip():
            result_text = "Jina search returned no results."

        return ToolCallResult(
            tool_id="", tool_name="jina_search",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("jina_search failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="jina_search",
            error=f"Jina search failed: {exc}",
        )


@register_tool(
    name="jina_read_page",
    description=(
        "Read a web page using the Jina Reader API. Returns clean markdown text. "
        "Lightweight and fast, suitable for standard web pages. "
        "For PDFs, images, or links needing heavier processing, use read_link instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full URL of the page to read"},
        },
        "required": ["url"],
    },
    is_interactive=False,
    category="search",
)
def handle_jina_read_page(args: dict, context: ToolContext) -> ToolCallResult:
    """Read a web page via the Jina Reader API.

    Sends a GET request to ``https://r.jina.ai/{url}`` which returns clean
    markdown text.  If a Jina API key is available (from ``context.keys`` or
    the ``JINA_API_KEY`` environment variable), it is sent as a Bearer token.

    Parameters
    ----------
    args:
        Parsed arguments containing ``url``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Page content in markdown or an error description.
    """
    url = args.get("url", "")
    logger.info("jina_read_page invoked: url=%r", url)

    if not url.strip():
        return ToolCallResult(
            tool_id="", tool_name="jina_read_page",
            error="url is required and must not be empty.",
        )

    try:
        import requests as _requests
        import os

        headers = {"Accept": "text/markdown"}

        # Check for Jina API key in context or environment
        keys = context.keys if context.keys else {}
        jina_key = keys.get("jinaKey") or os.environ.get("JINA_API_KEY", "")
        if jina_key:
            headers["Authorization"] = f"Bearer {jina_key}"

        resp = _requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=60)
        resp.raise_for_status()

        result_text = resp.text
        if not result_text.strip():
            result_text = f"No content returned for {url}"

        return ToolCallResult(
        tool_id="", tool_name="jina_read_page",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("jina_read_page failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="jina_read_page",
            error=f"Jina read page failed: {exc}",
        )


@register_tool(
    name="read_link",
    description=(
        "Read any link — web page, PDF, or image — and return its text content. "
        "Handles different content types automatically: web pages via multiple scrapers, "
        "PDFs via download+extraction, images via OCR+vision, YouTube via transcript."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full URL to read (web page, PDF, image, or YouTube link)"},
            "context": {
                "type": "string",
                "description": "What you are looking for on this page. Helps focus extraction",
                "default": "Read and extract all content from this page.",
            },
            "detailed": {
                "type": "boolean",
                "description": "If true, uses deeper extraction (more scrapers, longer timeouts)",
                "default": False,
            },
        },
        "required": ["url"],
    },
    is_interactive=False,
    category="search",
)
def handle_read_link(args: dict, context: ToolContext) -> ToolCallResult:
    """Read any link — web page, PDF, or image — and return its text content.

    Uses ``download_link_data`` from ``base.py`` which handles different content
    types automatically: web pages via multiple scrapers, PDFs via extraction,
    images via OCR+vision, YouTube via transcript.  Falls back to the Jina
    Reader API if ``download_link_data`` is unavailable.

    Parameters
    ----------
    args:
        Parsed arguments containing ``url``, optional ``context`` and ``detailed``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Extracted content or an error description.
    """
    url = args.get("url", "")
    read_context = args.get("context", "Read and extract all content from this page.")
    detailed = args.get("detailed", False)
    logger.info("read_link invoked: url=%r, detailed=%r", url, detailed)

    if not url.strip():
        return ToolCallResult(
            tool_id="", tool_name="read_link",
            error="url is required and must not be empty.",
        )

    try:
        # Resolve API keys: prefer context.keys, fall back to env vars
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        # Try using download_link_data from base.py
        try:
            from base import download_link_data

            link_tuple = (url, "", read_context, keys, "", detailed)
            result = download_link_data(link_tuple, web_search_tmp_marker_name=None)
        except (ImportError, AttributeError):
            logger.warning("download_link_data unavailable, falling back to jina_read_page")
            return handle_jina_read_page({"url": url}, context)

        if result.get("exception"):
            return ToolCallResult(
                tool_id="", tool_name="read_link",
                result="",
                error=f"Error reading link: {result.get('error', 'unknown error')}",
            )

        # Prefer full_text (raw content), fall back to text (processed)
        content = result.get("full_text", "") or result.get("text", "")
        if not content or not content.strip():
            return ToolCallResult(
                tool_id="", tool_name="read_link",
                result=f"No content extracted from {url}",
            )

        # Build formatted output with metadata
        parts: list[str] = []
        title = result.get("title", "")
        if title:
            parts.append(f"# {title}\n")
        is_pdf = result.get("is_pdf", False)
        is_image = result.get("is_image", False)
        type_label = "PDF" if is_pdf else "Image" if is_image else "Web page"
        meta = f"**Source**: {url} ({type_label})"
        partial = result.get("partial", False)
        if partial:
            meta += f" — ⚠ partial content ({result.get('error', 'unknown')})"
        parts.append(meta + "\n")
        parts.append(content)
        result_text = "\n".join(parts)

        return ToolCallResult(
        tool_id="", tool_name="read_link",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("read_link failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="read_link",
            result="",
            error=f"Read link failed: {exc}",
        )


# ---------------------------------------------------------------------------
# MCP Document Tools (category: documents)
# ---------------------------------------------------------------------------


# --- Document tool helpers (mirrors mcp_server/docs.py) ---

def _docs_get_keys():
    """Get API keys, cached."""
    from endpoints.utils import keyParser
    return keyParser({})

def _docs_storage_dir():
    return os.environ.get("STORAGE_DIR", "storage")

def _docs_users_dir():
    return os.path.join(os.getcwd(), _docs_storage_dir(), "users")

def _docs_conversation_folder():
    return os.path.join(os.getcwd(), _docs_storage_dir(), "conversations")

def _docs_load_doc_index(doc_storage_path):
    """Load a DocIndex from a storage path and set API keys."""
    from DocIndex import DocIndex
    doc = DocIndex.load_local(doc_storage_path)
    if doc is None:
        return None
    doc.set_api_keys(_docs_get_keys())
    return doc

def _docs_load_conversation(conversation_id):
    """Load a Conversation object from disk."""
    from Conversation import Conversation
    folder = os.path.join(_docs_conversation_folder(), conversation_id)
    if not os.path.isdir(folder):
        return None
    return Conversation.load_local(folder)

def _docs_resolve_global_doc(user_email, doc_id):
    """Look up a global document and return (metadata_dict, doc_storage_path)."""
    from database.global_docs import get_global_doc
    row = get_global_doc(users_dir=_docs_users_dir(), user_email=user_email, doc_id=doc_id)
    if row is None:
        return None, None
    return row, row.get("doc_storage", "")


@register_tool(
    name="docs_list_conversation_docs",
    description=(
        "List all documents attached to a conversation. Returns a JSON array of "
        "document metadata objects with doc_id, title, short_summary, "
        "doc_storage_path, source, and display_name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "The conversation identifier"},
        },
        "required": ["conversation_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_list_conversation_docs(args: dict, context: ToolContext) -> ToolCallResult:
    """List documents in a conversation."""
    conversation_id = args.get("conversation_id", "") or context.conversation_id or ""
    try:
        conv = _docs_load_conversation(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_list_conversation_docs",
                error=f"Conversation '{conversation_id}' not found.",
                result="",
            )
        doc_list = conv.get_field("uploaded_documents_list")
        if not doc_list:
            return ToolCallResult(
                tool_id="", tool_name="docs_list_conversation_docs",
                result=_truncate_result(json.dumps([])),
            )
        results = []
        for idx, entry in enumerate(doc_list):
            doc_id, doc_storage, pdf_url, _display_name = conv._doc_entry_fields(entry)
            doc = _docs_load_doc_index(doc_storage)
            if doc is None:
                results.append({
                    "index": idx + 1,
                    "doc_id": doc_id,
                    "title": "(failed to load)",
                    "short_summary": "",
                    "doc_storage_path": doc_storage,
                    "source": pdf_url,
                    "display_name": _display_name,
                })
                continue
            results.append({
                "index": idx + 1,
                "doc_id": doc_id,
                "title": doc.title,
                "short_summary": doc.short_summary,
                "doc_storage_path": doc_storage,
                "source": pdf_url,
                "display_name": _display_name,
                "priority": getattr(doc, "_priority", 3),
                "priority_label": {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(getattr(doc, "_priority", 3), "medium"),
                "date_written": getattr(doc, "_date_written", None),
                "deprecated": getattr(doc, "_deprecated", False),
            })
        return ToolCallResult(
            tool_id="", tool_name="docs_list_conversation_docs",
            result=_truncate_result(json.dumps(results)),
        )
    except Exception as exc:
        logger.exception("docs_list_conversation_docs error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_list_conversation_docs",
            error=f"Failed to list conversation docs: {exc}",
            result="",
        )


@register_tool(
    name="docs_list_global_docs",
    description=(
        "List all global documents for the current user. Global documents are "
        "indexed once and can be referenced from any conversation. Returns a JSON "
        "array with index, doc_id, display_name, title, short_summary, "
        "doc_storage_path, source, folder_id, and tags."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_list_global_docs(args: dict, context: ToolContext) -> ToolCallResult:
    """List global documents for the user."""
    try:
        from database.global_docs import list_global_docs
        rows = list_global_docs(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
        )
        results = []
        for idx, row in enumerate(rows):
            results.append({
                "index": idx + 1,
                "doc_id": row.get("doc_id", ""),
                "display_name": row.get("display_name", ""),
                "title": row.get("title", ""),
                "short_summary": row.get("short_summary", ""),
                "doc_storage_path": row.get("doc_storage", ""),
                "source": row.get("doc_source", ""),
                "folder_id": row.get("folder_id"),
                "tags": row.get("tags", []),
                "priority": row.get("priority", 3),
                "priority_label": {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(row.get("priority", 3), "medium"),
                "date_written": row.get("date_written"),
                "deprecated": row.get("deprecated", False),
            })
        return ToolCallResult(
            tool_id="", tool_name="docs_list_global_docs",
            result=_truncate_result(json.dumps(results)),
        )
    except Exception as exc:
        logger.exception("docs_list_global_docs error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_list_global_docs",
            error=f"Failed to list global docs: {exc}",
            result="",
        )


@register_tool(
    name="docs_query",
    description=(
        "Semantic search within a document. Finds and returns the most relevant "
        "passages matching the query. Use docs_list_conversation_docs or "
        "docs_list_global_docs first to obtain the doc_storage_path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_storage_path": {"type": "string", "description": "Storage path of the document to search"},
            "query": {"type": "string", "description": "What to search for in the document"},
            "token_limit": {
                "type": "integer",
                "description": "Maximum number of tokens in the returned passages",
                "default": 4096,
            },
        },
        "required": ["doc_storage_path", "query"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_query(args: dict, context: ToolContext) -> ToolCallResult:
    """Semantic search within a document."""
    doc_storage_path = args.get("doc_storage_path", "")
    query = args.get("query", "")
    token_limit = args.get("token_limit", 4096)
    try:
        doc = _docs_load_doc_index(doc_storage_path)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_query",
                error=f"Could not load document at '{doc_storage_path}'.",
                result="",
            )
        result = doc.semantic_search_document(query, token_limit=token_limit)
        return ToolCallResult(
            tool_id="", tool_name="docs_query",
            result=_truncate_result(result),
        )
    except Exception as exc:
        logger.exception("docs_query error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_query",
            error=f"Error querying document: {exc}",
            result="",
        )


@register_tool(
    name="docs_get_full_text",
    description=(
        "Retrieve the full text content of a document. For very large documents "
        "the output may be truncated to token_limit tokens. Use docs_query for "
        "targeted retrieval from large documents."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_storage_path": {"type": "string", "description": "Storage path of the document"},
            "token_limit": {
                "type": "integer",
                "description": "Maximum number of tokens to return",
                "default": 16000,
            },
        },
        "required": ["doc_storage_path"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_get_full_text(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full text of a document."""
    doc_storage_path = args.get("doc_storage_path", "")
    token_limit = args.get("token_limit", 16000)
    try:
        doc = _docs_load_doc_index(doc_storage_path)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_full_text",
                error=f"Could not load document at '{doc_storage_path}'.",
                result="",
            )
        text = doc.get_raw_doc_text()
        # Rough token truncation (1 token ~ 4 chars)
        char_limit = token_limit * 4
        if len(text) > char_limit:
            text = text[:char_limit] + "\n\n[... truncated ...]"
        return ToolCallResult(
            tool_id="", tool_name="docs_get_full_text",
            result=_truncate_result(text),
        )
    except Exception as exc:
        logger.exception("docs_get_full_text error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_get_full_text",
            error=f"Error retrieving document text: {exc}",
            result="",
        )


@register_tool(
    name="docs_get_info",
    description=(
        "Get metadata about a document without retrieving its full text. "
        "Returns title, brief_summary, short_summary, text_len, and visible status."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_storage_path": {"type": "string", "description": "Storage path of the document"},
        },
        "required": ["doc_storage_path"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_get_info(args: dict, context: ToolContext) -> ToolCallResult:
    """Get document metadata."""
    doc_storage_path = args.get("doc_storage_path", "")
    try:
        doc = _docs_load_doc_index(doc_storage_path)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_info",
                error=f"Could not load document at '{doc_storage_path}'.",
                result="",
            )
        return ToolCallResult(
            tool_id="", tool_name="docs_get_info",
            result=_truncate_result(json.dumps({
                "title": doc.title,
                "brief_summary": doc.brief_summary,
                "short_summary": doc.short_summary,
                "text_len": getattr(doc, "_text_len", 0),
                "visible": doc.visible,
                "priority": getattr(doc, "_priority", 3),
                "priority_label": {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(getattr(doc, "_priority", 3), "medium"),
                "date_written": getattr(doc, "_date_written", None),
                "deprecated": getattr(doc, "_deprecated", False),
            })),
        )
    except Exception as exc:
        logger.exception("docs_get_info error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_get_info",
            error=f"Failed to get document info: {exc}",
            result="",
        )


@register_tool(
    name="docs_answer_question",
    description=(
        "Ask a question about a document and get an LLM-generated answer. "
        "Uses RAG-style retrieval: relevant passages are extracted and fed to "
        "an LLM to produce a concise answer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_storage_path": {"type": "string", "description": "Storage path of the document"},
            "question": {"type": "string", "description": "The question to answer about the document"},
        },
        "required": ["doc_storage_path", "question"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_answer_question(args: dict, context: ToolContext) -> ToolCallResult:
    """Answer a question about a document."""
    doc_storage_path = args.get("doc_storage_path", "")
    question = args.get("question", "")
    try:
        from collections import defaultdict
        doc = _docs_load_doc_index(doc_storage_path)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_answer_question",
                error=f"Could not load document at '{doc_storage_path}'.",
                result="",
            )
        result = doc.get_short_answer(question, mode=defaultdict(lambda: False))
        return ToolCallResult(
            tool_id="", tool_name="docs_answer_question",
            result=_truncate_result(result),
        )
    except Exception as exc:
        logger.exception("docs_answer_question error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_answer_question",
            error=f"Error answering question: {exc}",
            result="",
        )


@register_tool(
    name="docs_get_global_doc_info",
    description=(
        "Get metadata about a global document. Returns doc_id, display_name, "
        "title, short_summary, doc_storage_path, source, created_at, updated_at."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
        },
        "required": ["doc_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_get_global_doc_info(args: dict, context: ToolContext) -> ToolCallResult:
    """Get global document metadata."""
    doc_id = args.get("doc_id", "")
    try:
        row, doc_storage = _docs_resolve_global_doc(context.user_email, doc_id)
        if row is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_global_doc_info",
                error=f"Global doc '{doc_id}' not found for user.",
                result="",
            )
        return ToolCallResult(
            tool_id="", tool_name="docs_get_global_doc_info",
            result=_truncate_result(json.dumps({
                "doc_id": row.get("doc_id", ""),
                "display_name": row.get("display_name", ""),
                "title": row.get("title", ""),
                "short_summary": row.get("short_summary", ""),
                "doc_storage_path": doc_storage,
                "source": row.get("doc_source", ""),
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
                "priority": row.get("priority", 3),
                "priority_label": {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(row.get("priority", 3), "medium"),
                "date_written": row.get("date_written"),
                "deprecated": row.get("deprecated", False),
            })),
        )
    except Exception as exc:
        logger.exception("docs_get_global_doc_info error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_get_global_doc_info",
            error=f"Failed to get global doc info: {exc}",
            result="",
        )


@register_tool(
    name="docs_query_global_doc",
    description=(
        "Semantic search within a global document. Resolves the document by "
        "doc_id, then performs semantic search to find relevant passages."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
            "query": {"type": "string", "description": "What to search for in the document"},
            "token_limit": {
                "type": "integer",
                "description": "Maximum number of tokens in the returned passages",
                "default": 4096,
            },
        },
        "required": ["doc_id", "query"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_query_global_doc(args: dict, context: ToolContext) -> ToolCallResult:
    """Semantic search within a global document."""
    doc_id = args.get("doc_id", "")
    query = args.get("query", "")
    token_limit = args.get("token_limit", 4096)
    try:
        row, doc_storage = _docs_resolve_global_doc(context.user_email, doc_id)
        if row is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_query_global_doc",
                error=f"Global doc '{doc_id}' not found for user.",
                result="",
            )
        if not doc_storage:
            return ToolCallResult(
                tool_id="", tool_name="docs_query_global_doc",
                error=f"Global doc '{doc_id}' has no storage path.",
                result="",
            )
        doc = _docs_load_doc_index(doc_storage)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_query_global_doc",
                error=f"Could not load global doc at '{doc_storage}'.",
                result="",
            )
        result = doc.semantic_search_document(query, token_limit=token_limit)
        return ToolCallResult(
            tool_id="", tool_name="docs_query_global_doc",
            result=_truncate_result(result),
        )
    except Exception as exc:
        logger.exception("docs_query_global_doc error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_query_global_doc",
            error=f"Error querying global document: {exc}",
            result="",
        )


@register_tool(
    name="docs_get_global_doc_full_text",
    description=(
        "Retrieve the full text content of a global document. Resolves by "
        "doc_id and returns the complete text, possibly truncated to token_limit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
            "token_limit": {
                "type": "integer",
                "description": "Maximum number of tokens to return",
                "default": 16000,
            },
        },
        "required": ["doc_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_get_global_doc_full_text(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full text of a global document."""
    doc_id = args.get("doc_id", "")
    token_limit = args.get("token_limit", 16000)
    try:
        row, doc_storage = _docs_resolve_global_doc(context.user_email, doc_id)
        if row is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_global_doc_full_text",
                error=f"Global doc '{doc_id}' not found for user.",
                result="",
            )
        if not doc_storage:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_global_doc_full_text",
                error=f"Global doc '{doc_id}' has no storage path.",
                result="",
            )
        doc = _docs_load_doc_index(doc_storage)
        if doc is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_get_global_doc_full_text",
                error=f"Could not load global doc at '{doc_storage}'.",
                result="",
            )
        text = doc.get_raw_doc_text()
        # Rough token truncation (1 token ~ 4 chars)
        char_limit = token_limit * 4
        if len(text) > char_limit:
            text = text[:char_limit] + "\n\n[... truncated ...]"
        return ToolCallResult(
            tool_id="", tool_name="docs_get_global_doc_full_text",
            result=_truncate_result(text),
        )
    except Exception as exc:
        logger.exception("docs_get_global_doc_full_text error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_get_global_doc_full_text",
            error=f"Error retrieving global document text: {exc}",
            result="",
        )


# ---------------------------------------------------------------------------
# MCP PKB Tools (category: pkb)
# ---------------------------------------------------------------------------


# --- PKB tool helpers (mirrors mcp_server/pkb.py) ---

_pkb_api_instance = None

def _get_pkb_api():
    """Get or create the shared StructuredAPI singleton."""
    global _pkb_api_instance
    if _pkb_api_instance is None:
        from endpoints.pkb import get_pkb_db
        from endpoints.utils import keyParser
        from truth_management_system.interface.structured_api import StructuredAPI
        keys = keyParser({})
        db, config = get_pkb_db()
        if db is None:
            raise RuntimeError("PKB database unavailable")
        _pkb_api_instance = StructuredAPI(db=db, keys=keys, config=config)
    return _pkb_api_instance

def _pkb_serialize_action_result(result):
    """Serialize ActionResult to JSON string. Mirrors mcp_server/pkb.py."""
    import json as _json
    from dataclasses import asdict
    try:
        d = asdict(result)
    except Exception:
        d = {
            "success": result.success,
            "action": result.action,
            "object_type": result.object_type,
            "object_id": result.object_id,
            "data": _pkb_serialize_data(result.data),
            "warnings": list(result.warnings) if result.warnings else [],
            "errors": list(result.errors) if result.errors else [],
        }
    else:
        d["data"] = _pkb_serialize_data(result.data)
    return _json.dumps(d, default=str)

def _pkb_serialize_data(data):
    """Recursively convert PKB model objects to JSON-safe dicts."""
    if data is None:
        return None
    if hasattr(data, "to_dict"):
        return data.to_dict()
    if hasattr(data, "claim") and hasattr(data, "score"):
        sr = {
            "score": data.score,
            "source": getattr(data, "source", None),
            "is_contested": getattr(data, "is_contested", False),
            "warnings": list(getattr(data, "warnings", [])),
        }
        if hasattr(data.claim, "to_dict"):
            sr["claim"] = data.claim.to_dict()
        else:
            sr["claim"] = data.claim
        return sr
    if isinstance(data, list):
        return [_pkb_serialize_data(item) for item in data]
    if isinstance(data, dict):
        return {k: _pkb_serialize_data(v) for k, v in data.items()}
    return data

@register_tool(
    name="pkb_search",
    description=(
        "Search the user's PKB for relevant claims using hybrid search (FTS5 + embedding). "
        "HIGH RECALL IS CRITICAL — search with multiple phrasings, synonyms, and alternative terms. "
        "Issue MULTIPLE searches with varied queries. Use broad terms first, then narrow. "
        "Request higher k (30-50) when comprehensive coverage matters."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query. Use broad terms, synonyms, and alternative phrasings to maximize recall. Issue multiple searches with different queries rather than relying on one."},
            "k": {
                "type": "integer",
                "description": "Maximum number of results to return. Use 30-50 when comprehensive recall matters. Default 20 may miss relevant items.",
                "default": 20,
            },
            "strategy": {
                "type": "string",
                "description": "Search strategy: hybrid (default), fts, or embedding",
                "default": "hybrid",
            },
        },
        "required": ["query"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_search(args: dict, context: ToolContext) -> ToolCallResult:
    """Search the PKB for relevant claims."""
    query = args.get("query", "")
    k = args.get("k", 20)
    strategy = args.get("strategy", "hybrid")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.search(query=query, strategy=strategy, k=k)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_search",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_search",
            error=f"pkb_search failed: {exc}",
        )


@register_tool(
    name="pkb_get_claim",
    description=(
        "Retrieve a single claim from the PKB by its claim ID. Use when you "
        "already have a specific claim_id (e.g. from search results or a reference) "
        "and need the full claim details."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string", "description": "The UUID of the claim to retrieve"},
        },
        "required": ["claim_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_get_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Get a single PKB claim by ID."""
    claim_id = args.get("claim_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.get_claim(claim_id=claim_id)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_claim",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_claim",
            error=f"pkb_get_claim failed: {exc}",
        )


@register_tool(
    name="pkb_resolve_reference",
    description=(
        "Resolve a PKB @-reference (friendly ID) to its full object(s). "
        "Friendly IDs look like @my_preference_42 or @work_context. "
        "Suffixed IDs (_context, _entity, _tag, _domain) route to the correct object type."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reference_id": {"type": "string", "description": "The friendly ID to resolve (with or without leading @)"},
        },
        "required": ["reference_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_resolve_reference(args: dict, context: ToolContext) -> ToolCallResult:
    """Resolve a PKB @-reference to its full object(s)."""
    reference_id = args.get("reference_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.resolve_reference(reference_id=reference_id.lstrip("@"))
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_resolve_reference",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_resolve_reference",
            error=f"pkb_resolve_reference failed: {exc}",
        )


@register_tool(
    name="pkb_get_pinned_claims",
    description=(
        "Retrieve the user's pinned (high-priority) PKB claims. "
        "Pinned claims are those marked as especially important or frequently referenced."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of pinned claims to return",
                "default": 50,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_get_pinned_claims(args: dict, context: ToolContext) -> ToolCallResult:
    """Get pinned PKB claims."""
    limit = args.get("limit", 50)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.get_pinned_claims(limit=limit)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_pinned_claims",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_pinned_claims",
            error=f"pkb_get_pinned_claims failed: {exc}",
        )


@register_tool(
    name="pkb_add_claim",
    description=(
        "Add a new claim (memory, fact, preference, etc.) to the PKB (write operation). "
        "Claims are the atomic units of the knowledge base. Each claim has a type "
        "(e.g. fact, preference, decision) and belongs to a context domain."
    ),
    parameters={
        "type": "object",
        "properties": {
            "statement": {"type": "string", "description": "The claim text — a single clear assertion"},
            "claim_type": {
                "type": "string",
                "description": "Claim type (e.g. fact, preference, decision, memory, goal)",
            },
            "context_domain": {
                "type": "string",
                "description": "Domain/topic area (e.g. work, health, finance, personal)",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of tag names to attach to the claim",
            },
            "valid_to": {
                "type": "string",
                "description": "End of validity period (ISO 8601 date, e.g. '2025-07-20'). Required for task and reminder claim types.",
            },
        },
        "required": ["statement", "claim_type", "context_domain"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_add_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Add a new claim to the PKB."""
    statement = args.get("statement", "")
    claim_type = args.get("claim_type", "")
    context_domain = args.get("context_domain", "")
    tags = args.get("tags", None)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        kwargs = dict(statement=statement, claim_type=claim_type, context_domain=context_domain)
        if tags is not None:
            kwargs["tags"] = tags
        valid_to = args.get("valid_to", None)
        if valid_to is not None:
            kwargs["valid_to"] = valid_to
        result = user_api.add_claim(**kwargs)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_add_claim",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_add_claim",
            error=f"pkb_add_claim failed: {exc}",
        )


@register_tool(
    name="pkb_edit_claim",
    description=(
        "Edit an existing claim in the PKB (write operation). "
        "Only the fields you provide will be updated; others remain unchanged. "
        "Use pkb_get_claim first to see the current state."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string", "description": "UUID of the claim to edit"},
            "statement": {"type": "string", "description": "New statement text (optional)"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New list of tag names (replaces existing tags; optional)",
            },
        },
        "required": ["claim_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_edit_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Edit an existing PKB claim."""
    claim_id = args.get("claim_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        patch = {}
        if args.get("statement") is not None:
            patch["statement"] = args["statement"]
        if args.get("tags") is not None:
            patch["tags"] = args["tags"]
        result = user_api.edit_claim(claim_id=claim_id, **patch)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_edit_claim",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_edit_claim",
            error=f"pkb_edit_claim failed: {exc}",
        )


@register_tool(
    name="pkb_get_claims_by_ids",
    description=(
        "Retrieve multiple claims by their IDs in a single call. "
        "More efficient than calling pkb_get_claim in a loop."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of claim UUIDs to retrieve",
            },
        },
        "required": ["claim_ids"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_get_claims_by_ids(args: dict, context: ToolContext) -> ToolCallResult:
    """Batch retrieve PKB claims by IDs."""
    claim_ids = args.get("claim_ids", [])
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.get_claims_by_ids(claim_ids=claim_ids)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_claims_by_ids",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_claims_by_ids",
            error=f"pkb_get_claims_by_ids failed: {exc}",
        )


@register_tool(
    name="pkb_autocomplete",
    description=(
        "Autocomplete PKB friendly IDs by prefix. Searches across claims, "
        "contexts, entities, tags, and domains. Useful for discovering available knowledge."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "The prefix string to match against friendly IDs"},
            "limit": {
                "type": "integer",
                "description": "Maximum matches per category",
                "default": 10,
            },
        },
        "required": ["prefix"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_autocomplete(args: dict, context: ToolContext) -> ToolCallResult:
    """Autocomplete PKB friendly IDs by prefix."""
    prefix = args.get("prefix", "")
    limit = args.get("limit", 10)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.autocomplete(prefix=prefix, limit=limit)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_autocomplete",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_autocomplete",
            error=f"pkb_autocomplete failed: {exc}",
        )


@register_tool(
    name="pkb_resolve_context",
    description=(
        "Resolve a context to its full claim tree. Returns all claims "
        "belonging to the given context (including sub-contexts, resolved recursively)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "context_id": {"type": "string", "description": "UUID or friendly_id of the context"},
        },
        "required": ["context_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_resolve_context(args: dict, context: ToolContext) -> ToolCallResult:
    """Resolve a PKB context to its full claim tree."""
    context_id = args.get("context_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.resolve_context(context_id=context_id)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_resolve_context",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_resolve_context",
            error=f"pkb_resolve_context failed: {exc}",
        )

@register_tool(
    name="pkb_delete_claim",
    description=(
        "Soft-delete (retract) a claim from the PKB. "
        "The claim is not permanently deleted but marked as retracted "
        "and excluded from default search results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string", "description": "UUID of the claim to delete"},
        },
        "required": ["claim_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_delete_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Soft-delete (retract) a PKB claim."""
    claim_id = args.get("claim_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.delete_claim(claim_id=claim_id)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_delete_claim",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_delete_claim",
            error=f"pkb_delete_claim failed: {exc}",
        )

@register_tool(
    name="pkb_pin_claim",
    description=(
        "Pin or unpin a claim for prominence (write operation). Pinned claims "
        "appear in pkb_get_pinned_claims results and are given higher priority "
        "in context injection."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string", "description": "UUID of the claim to pin/unpin"},
            "pin": {
                "type": "boolean",
                "description": "True to pin, False to unpin",
                "default": True,
            },
        },
        "required": ["claim_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_pin_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Pin or unpin a PKB claim."""
    claim_id = args.get("claim_id", "")
    pin = args.get("pin", True)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.pin_claim(claim_id=claim_id, pin=pin)
        serialized = _pkb_serialize_action_result(result)
        return ToolCallResult(
            tool_id="", tool_name="pkb_pin_claim",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_pin_claim",
            error=f"pkb_pin_claim failed: {exc}",
        )

@register_tool(
    name="pkb_nl_command",
    description=(
        "Process a natural language command against the PKB. Performs multi-step CRUD "
        "(search, add, edit, delete claims; manage entities/tags) via internal agent loop. "
        "Use for complex PKB operations. Agent optimizes for HIGH RECALL with synonyms and broad terms."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Natural language command. For search/retrieval, include synonyms and alternative phrasings to improve recall (e.g. 'find my dietary preferences, food habits, eating restrictions, nutrition notes').",
            },
            "model": {
                "type": "string",
                "description": "Optional LLM model override (default: openai/gpt-4o-mini)",
            },
        },
        "required": ["command"],
    },
    is_interactive=True,
    category="pkb",
)
def handle_pkb_nl_command(args: dict, context: ToolContext) -> ToolCallResult:
    """Process a natural language PKB command via the agentic NL processor.

    If the NL agent is uncertain and requests clarification, this returns
    an interactive result (needs_user_input=True) with tool_name='pkb_propose_memory'
    so the UI shows the memory proposal modal.
    """
    command = args.get("command", "")
    model = args.get("model", None)
    # Fall back to model override from conversation settings, then CHEAP_LLM[0]
    if not model:
        from common import CHEAP_LLM
        model = context.model_overrides.get("pkb_nl_model") or CHEAP_LLM[0]
    try:
        from truth_management_system.interface.nl_agent import PKBNLAgent

        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        keys = context.keys
        agent = PKBNLAgent(api=user_api, keys=keys, model=model)
        result = agent.process(command)

        # If the NL agent needs user input (ask_clarification with proposals),
        # bubble it up as an interactive tool result so the UI shows the modal.
        if result.needs_user_input and result.proposed_claims:
            return ToolCallResult(
                tool_id="",
                tool_name="pkb_propose_memory",
                result=result.message or "Review proposed memories.",
                needs_user_input=True,
                ui_schema={
                    "claims": result.proposed_claims,
                    "message": result.message or "Review proposed memories.",
                },
            )

        serialized = json.dumps(result.to_dict(), default=str)
        return ToolCallResult(
            tool_id="", tool_name="pkb_nl_command",
            result=_truncate_result(serialized),
        )
    except Exception as exc:
        logger.exception("pkb_nl_command error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="pkb_nl_command",
            error=f"pkb_nl_command failed: {exc}",
        )

@register_tool(
    name="pkb_propose_memory",
    description=(
        "Propose memory entries to user for review before saving to PKB. "
        "Shows modal with pre-filled fields user can edit and confirm. "
        "Use when uncertain about structure/type/dates/tags of a memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The claim/memory text",
                        },
                        "claim_type": {
                            "type": "string",
                            "enum": ["fact", "preference", "event", "task", "reminder", "goal", "note"],
                            "description": "Type of the memory entry",
                        },
                        "valid_from": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format (optional)",
                        },
                        "valid_to": {
                            "type": "string",
                            "description": "End/due date in YYYY-MM-DD format (required for task/reminder)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags to categorize the memory",
                        },
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Named entities mentioned (people, places, orgs)",
                        },
                        "context": {
                            "type": "string",
                            "description": "Context/source of the memory (e.g. conversation topic)",
                        },
                    },
                    "required": ["text", "claim_type"],
                },
                "description": "List of proposed memory entries for user review",
                "minItems": 1,
                "maxItems": 10,
            },
            "message": {
                "type": "string",
                "description": "Brief explanation of what is being proposed and why review is needed",
            },
        },
        "required": ["claims"],
    },
    is_interactive=True,
    category="pkb",
)
def handle_pkb_propose_memory(args: dict, context: ToolContext) -> ToolCallResult:
    """Handle the pkb_propose_memory interactive tool call.

    Like ask_clarification, this is an interactive tool — it does NOT execute
    any logic directly. Instead it returns ``needs_user_input=True`` so the
    agentic loop pauses and the UI renders the memory proposal modal for the
    user to review, edit, and confirm.

    Parameters
    ----------
    args:
        Parsed arguments containing ``claims`` list and optional ``message``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        With ``needs_user_input=True`` and ``ui_schema`` containing the
        proposed claims for user review.
    """
    claims = args.get("claims", [])
    message = args.get("message", "")
    logger.info("pkb_propose_memory invoked with %d claim(s): %s", len(claims), message[:100])

    return ToolCallResult(
        tool_id="",
        tool_name="pkb_propose_memory",
        result="Waiting for user to review proposed memory entries.",
        needs_user_input=True,
        ui_schema=args,
    )

# ---------------------------------------------------------------------------
# MCP Conversation Memory Tools (category: memory)
# ---------------------------------------------------------------------------

# --- Conversation/Memory tool helpers (mirrors mcp_server/conversation.py) ---

def _conv_load(conversation_id):
    """Load a Conversation from local storage."""
    from Conversation import Conversation
    import os as _os
    storage = _os.environ.get("STORAGE_DIR", "storage")
    folder = _os.path.join(storage, "conversations", conversation_id)
    if not _os.path.isdir(folder):
        return None
    return Conversation.load_local(folder)

def _conv_users_dir():
    """Return users directory path."""
    import os as _os
    storage = _os.environ.get("STORAGE_DIR", "storage")
    return _os.path.join(_os.getcwd(), storage, "users")


@register_tool(
    name="conv_get_memory_pad",
    description=(
        "Get the per-conversation memory pad (scratchpad). The memory pad "
        "stores factual data and details accumulated during the conversation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Unique identifier for the conversation"},
        },
        "required": ["conversation_id"],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_get_memory_pad(args: dict, context: ToolContext) -> ToolCallResult:
    """Get conversation memory pad."""
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="conv_get_memory_pad",
                error=f"Conversation not found: {conversation_id}",
            )
        text = conv.memory_pad or ""
        return ToolCallResult(
            tool_id="", tool_name="conv_get_memory_pad",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_get_memory_pad",
            error=f"Error getting memory pad: {e}",
        )


@register_tool(
    name="conv_set_memory_pad",
    description=(
        "Set (overwrite) the per-conversation memory pad (write operation). "
        "Stores text that persists for the duration of the conversation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Unique identifier for the conversation"},
            "text": {"type": "string", "description": "New memory pad content (plain text)"},
        },
        "required": ["conversation_id", "text"],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_set_memory_pad(args: dict, context: ToolContext) -> ToolCallResult:
    """Set conversation memory pad."""
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    text = args.get("text", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="conv_set_memory_pad",
                error=f"Conversation not found: {conversation_id}",
            )
        conv.set_memory_pad(text)
        return ToolCallResult(
            tool_id="", tool_name="conv_set_memory_pad",
            result=_truncate_result(json.dumps({"success": True})),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_set_memory_pad",
            error=f"Error setting memory pad: {e}",
        )


@register_tool(
    name="conv_get_history",
    description=(
        "Get formatted conversation history (summary + recent messages). "
        "Returns a human-readable markdown string with conversation summary, "
        "recent messages, and metadata."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Unique identifier for the conversation"},
            "query": {
                "type": "string",
                "description": "Optional query to focus history retrieval on a topic",
                "default": "",
            },
        },
        "required": ["conversation_id"],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_get_history(args: dict, context: ToolContext) -> ToolCallResult:
    """Get conversation history."""
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    query = args.get("query", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="conv_get_history",
                error=f"Conversation not found: {conversation_id}",
            )
        text = conv.get_conversation_history(query=query)
        return ToolCallResult(
            tool_id="", tool_name="conv_get_history",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_get_history",
            error=f"Error getting history: {e}",
        )


@register_tool(
    name="conv_get_user_detail",
    description=(
        "Get the user's persistent memory/bio. User details persist across "
        "all conversations and contain biographical info, preferences, and "
        "accumulated knowledge about the user."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_get_user_detail(args: dict, context: ToolContext) -> ToolCallResult:
    """Get user persistent memory."""
    try:
        from database.users import getUserFromUserDetailsTable
        user_details = getUserFromUserDetailsTable(
            context.user_email, users_dir=_conv_users_dir(), logger=logger
        )
        text = user_details.get("user_memory", "") or ""
        return ToolCallResult(
            tool_id="", tool_name="conv_get_user_detail",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_get_user_detail",
            error=f"Error getting user detail: {e}",
        )


@register_tool(
    name="conv_get_user_preference",
    description=(
        "Get the user's stored preferences. Preferences persist across all "
        "conversations and describe how the user likes responses formatted, "
        "their expertise level, and other customisation options."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_get_user_preference(args: dict, context: ToolContext) -> ToolCallResult:
    """Get user preferences."""
    try:
        from database.users import getUserFromUserDetailsTable
        user_details = getUserFromUserDetailsTable(
            context.user_email, users_dir=_conv_users_dir(), logger=logger
        )
        text = user_details.get("user_preferences", "") or ""
        return ToolCallResult(
            tool_id="", tool_name="conv_get_user_preference",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_get_user_preference",
            error=f"Error getting user preferences: {e}",
        )


@register_tool(
    name="conv_get_messages",
    description=(
        "Get the raw message list from a conversation. Returns a JSON-encoded "
        "list of message objects with fields like text, role, timestamp."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Unique identifier for the conversation"},
        },
        "required": ["conversation_id"],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_get_messages(args: dict, context: ToolContext) -> ToolCallResult:
    """Get raw conversation messages."""
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="conv_get_messages",
                error=f"Conversation not found: {conversation_id}",
            )
        messages = conv.get_message_list() or []
        text = json.dumps(messages, default=str)
        return ToolCallResult(
            tool_id="", tool_name="conv_get_messages",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_get_messages",
            error=f"Error getting messages: {e}",
        )


@register_tool(
    name="conv_set_user_detail",
    description=(
        "Update the user's persistent memory/bio (write operation). "
        "Overwrites the stored user memory with the provided text. "
        "This data persists across all conversations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "New user memory/bio content (plain text)"},
        },
        "required": ["text"],
    },
    is_interactive=False,
    category="memory",
)
def handle_conv_set_user_detail(args: dict, context: ToolContext) -> ToolCallResult:
    """Set user persistent memory."""
    text = args.get("text", "")
    try:
        from database.users import updateUserInfoInUserDetailsTable
        success = updateUserInfoInUserDetailsTable(
            context.user_email, user_memory=text,
            users_dir=_conv_users_dir(), logger=logger
        )
        return ToolCallResult(
            tool_id="", tool_name="conv_set_user_detail",
            result=_truncate_result(json.dumps({"success": success})),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="conv_set_user_detail",
            error=f"Error setting user detail: {e}",
        )


# MCP Conversation Message Tools (category: conversation)
# --- Conversation tool helpers (uses code_common/conversation_search.py) ---
from code_common.conversation_search import CONVERSATION_TOOLS

def _conv_tool_kwargs(tool_name: str) -> dict:
    """Return CONVERSATION_TOOLS[tool_name] kwargs suitable for register_tool (strips extra keys)."""
    return {k: v for k, v in CONVERSATION_TOOLS[tool_name].items() if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}


@register_tool(**_conv_tool_kwargs("search_messages"))
def handle_search_messages(args: dict, context: ToolContext) -> ToolCallResult:
    """Search conversation messages by keyword using BM25 or text/regex mode.

    Delegates to Conversation.search_messages() and returns ranked results.
    """
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="search_messages",
                error=f"Conversation not found: {conversation_id}",
            )
        query = args.get("query", "")
        mode = args.get("mode", "bm25")
        sender_filter = args.get("sender_filter", None)
        top_k = args.get("top_k", 10)
        case_sensitive = args.get("case_sensitive", False)
        min_length = args.get("min_length", None)
        max_length = args.get("max_length", None)
        result = conv.search_messages(
            query=query,
            mode=mode,
            sender_filter=sender_filter,
            top_k=top_k,
            case_sensitive=case_sensitive,
            min_length=min_length,
            max_length=max_length,
        )
        return ToolCallResult(
            tool_id="", tool_name="search_messages",
            result=_truncate_result(json.dumps(result, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="search_messages",
            error=f"Error searching messages: {e}",
        )


@register_tool(**_conv_tool_kwargs("list_messages"))
def handle_list_messages(args: dict, context: ToolContext) -> ToolCallResult:
    """List conversation messages with short previews and TLDR summaries.

    Delegates to Conversation.list_messages() and returns paginated results.
    """
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="list_messages",
                error=f"Conversation not found: {conversation_id}",
            )
        start = args.get("start", None)
        end = args.get("end", None)
        from_end = args.get("from_end", False)
        sender_filter = args.get("sender_filter", None)
        result = conv.list_messages(
            start=start,
            end=end,
            from_end=from_end,
            sender_filter=sender_filter,
        )
        return ToolCallResult(
            tool_id="", tool_name="list_messages",
            result=_truncate_result(json.dumps(result, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="list_messages",
            error=f"Error listing messages: {e}",
        )


@register_tool(**_conv_tool_kwargs("read_message"))
def handle_read_message(args: dict, context: ToolContext) -> ToolCallResult:
    """Read the full content of a specific message by ID or index.

    Delegates to Conversation.read_message() and returns full message data.
    """
    # Context conversation_id is authoritative — the doubt/chat flow sets it to
    # the real (email-prefixed) conversation id. The LLM frequently hallucinates
    # this value (e.g. passing the message_id), so prefer context over args.
    conversation_id = getattr(context, "conversation_id", "") or args.get("conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="read_message",
                result="",
                error=f"Conversation not found: {conversation_id}",
            )
        message_id = args.get("message_id", None)
        index = args.get("index", None)
        result = conv.read_message(message_id=message_id, index=index)
        return ToolCallResult(
            tool_id="", tool_name="read_message",
            result=_truncate_result(json.dumps(result, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="read_message",
            result="",
            error=f"Error reading message: {e}",
        )


@register_tool(**_conv_tool_kwargs("propose_answer_edit"))
def handle_propose_answer_edit(args: dict, context: ToolContext) -> ToolCallResult:
    """Propose text replacements for a conversation message.

    Validates each replacement (old_text must exist in current message), computes
    a unified diff, and returns a structured proposal JSON for the frontend to display.
    The edit is NOT applied — the user must accept the diff in the UI.
    """
    import difflib

    # Context ids are authoritative for the doubt flow: clear_doubt sets
    # conversation_id and target_message_id to the exact message under
    # discussion. The LLM cannot know the internal (email-prefixed)
    # conversation_id and routinely hallucinates it (e.g. reuses the
    # message_id), so prefer context over the model-supplied args.
    conversation_id = getattr(context, "conversation_id", "") or args.get("conversation_id", "")
    message_id = getattr(context, "target_message_id", "") or args.get("message_id", "")
    replacements = args.get("replacements", [])
    summary = args.get("summary", "")

    if not conversation_id:
        return ToolCallResult(
            tool_id="", tool_name="propose_answer_edit",
            result="",
            error="conversation_id is required",
        )
    if not message_id:
        return ToolCallResult(
            tool_id="", tool_name="propose_answer_edit",
            result="",
            error="message_id is required — provide it explicitly or check context",
        )
    if not replacements:
        return ToolCallResult(
            tool_id="", tool_name="propose_answer_edit",
            result="",
            error="replacements list is empty — at least one replacement is required",
        )

    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="propose_answer_edit",
                result="",
                error=f"Conversation not found: {conversation_id}",
            )
        msg = conv.read_message(message_id=message_id)
        if msg is None:
            return ToolCallResult(
                tool_id="", tool_name="propose_answer_edit",
                result="",
                error=f"Message not found: {message_id}",
            )
        original_text = msg.get("text", "")
        current_text = original_text

        # Apply replacements and track which ones were found
        validated = []
        for rep in replacements:
            old_t = rep.get("old_text", "")
            new_t = rep.get("new_text", "")
            if not old_t:
                continue
            # Use the same whitespace-tolerant matcher as apply_message_replacements
            # so the proposed diff matches what will actually be persisted.
            matched = conv._locate_old_text(current_text, old_t)
            found = matched is not None
            if found:
                current_text = current_text.replace(matched, new_t, 1)
            validated.append({
                "old_text": old_t,
                "new_text": new_t,
                "found": found,
            })

        # Compute unified diff for display.
        # Use splitlines() WITHOUT keepends + lineterm="" so the join with "\n"
        # does not produce doubled newlines (keepends would leave each line's own
        # trailing newline, then join adds another → blank lines between each row).
        orig_lines = original_text.splitlines()
        new_lines = current_text.splitlines()
        diff_lines = list(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile="original",
            tofile="updated",
            lineterm="",
        ))
        diff_text = "\n".join(diff_lines)

        found_count = sum(1 for v in validated if v["found"])
        if found_count == 0:
            return ToolCallResult(
                tool_id="", tool_name="propose_answer_edit",
                result="",
                error=(
                    "None of the old_text values were found in the message. "
                    "Use read_message to get the exact current text and try again."
                ),
            )

        result_payload = {
            "proposal_type": "answer_edit",
            "message_id": message_id,
            "conversation_id": conversation_id,
            "replacements": validated,
            "original_text": original_text,
            "new_text": current_text,
            "diff_text": diff_text,
            "summary": summary,
            "found_count": found_count,
            "total_count": len(validated),
        }
        return ToolCallResult(
            tool_id="", tool_name="propose_answer_edit",
            result=json.dumps(result_payload),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="propose_answer_edit",
            result="",
            error=f"Error proposing edit: {e}",
        )


@register_tool(**_conv_tool_kwargs("get_conversation_details"))
def handle_get_conversation_details(args: dict, context: ToolContext) -> ToolCallResult:
    """Get a comprehensive overview of the conversation including metadata.

    Delegates to Conversation.get_conversation_details() and returns full details.
    """
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="get_conversation_details",
                error=f"Conversation not found: {conversation_id}",
            )
        result = conv.get_conversation_details()
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_details",
            result=_truncate_result(json.dumps(result, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_details",
            error=f"Error getting conversation details: {e}",
        )


@register_tool(**_conv_tool_kwargs("get_conversation_memory_pad"))
def handle_get_conversation_memory_pad(args: dict, context: ToolContext) -> ToolCallResult:
    """Get the conversation's memory pad scratchpad of extracted facts.

    Returns conv.memory_pad text directly — lighter-weight than reading all messages.
    """
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="get_conversation_memory_pad",
                error=f"Conversation not found: {conversation_id}",
            )
        text = conv.memory_pad or ""
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_memory_pad",
            result=_truncate_result(text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_memory_pad",
            error=f"Error getting conversation memory pad: {e}",
        )


# ---------------------------------------------------------------------------
# Cross-Conversation Search Tools (category: conversation)
# --- Uses code_common/cross_conversation_search.py ---
# ---------------------------------------------------------------------------
from code_common.cross_conversation_search import CROSS_CONVERSATION_TOOLS

def _cross_conv_tool_kwargs(tool_name: str) -> dict:
    """Return CROSS_CONVERSATION_TOOLS[tool_name] kwargs suitable for register_tool."""
    return {k: v for k, v in CROSS_CONVERSATION_TOOLS[tool_name].items()
            if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}

def _cross_conv_users_dir():
    """Return users directory path for cross-conv search (same pattern as _conv_users_dir)."""
    import os as _os
    storage = _os.environ.get("STORAGE_DIR", "storage")
    return _os.path.join(_os.getcwd(), storage, "users")


@register_tool(**_cross_conv_tool_kwargs("search_conversations"))
def handle_search_conversations(args: dict, context: ToolContext) -> ToolCallResult:
    """Search across all user conversations by keyword, phrase, or regex.

    Creates a CrossConversationIndex per call and delegates to index.search().
    """
    try:
        from code_common.cross_conversation_search import CrossConversationIndex
        index = CrossConversationIndex(_cross_conv_users_dir())
        user_email = getattr(context, 'user_email', '') or ''
        results = index.search(
            user_email=user_email,
            query=args.get("query", ""),
            mode=args.get("mode", "keyword"),
            deep=bool(args.get("deep", False)),
            workspace_id=args.get("workspace_id") or None,
            domain=args.get("domain") or None,
            flag=args.get("flag") or None,
            date_from=args.get("date_from") or None,
            date_to=args.get("date_to") or None,
            sender_filter=args.get("sender_filter") or None,
            top_k=int(args.get("top_k", 20)),
        )
        return ToolCallResult(
            tool_id="", tool_name="search_conversations",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="search_conversations",
            error=f"Error searching conversations: {e}",
        )


@register_tool(**_cross_conv_tool_kwargs("list_user_conversations"))
def handle_list_user_conversations(args: dict, context: ToolContext) -> ToolCallResult:
    """Browse and filter conversations without a search query."""
    try:
        from code_common.cross_conversation_search import CrossConversationIndex
        index = CrossConversationIndex(_cross_conv_users_dir())
        user_email = getattr(context, 'user_email', '') or ''
        results = index.list_conversations(
            user_email=user_email,
            workspace_id=args.get("workspace_id") or None,
            domain=args.get("domain") or None,
            flag=args.get("flag") or None,
            date_from=args.get("date_from") or None,
            date_to=args.get("date_to") or None,
            sort_by=args.get("sort_by", "last_updated"),
            limit=int(args.get("limit", 50)),
            offset=int(args.get("offset", 0)),
        )
        return ToolCallResult(
            tool_id="", tool_name="list_user_conversations",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="list_user_conversations",
            error=f"Error listing conversations: {e}",
        )


@register_tool(**_cross_conv_tool_kwargs("get_conversation_summary"))
def handle_get_conversation_summary(args: dict, context: ToolContext) -> ToolCallResult:
    """Get detailed summary of a specific conversation by ID or friendly ID."""
    try:
        from code_common.cross_conversation_search import CrossConversationIndex
        index = CrossConversationIndex(_cross_conv_users_dir())
        user_email = getattr(context, 'user_email', '') or ''
        conversation_id = args.get("conversation_id", "")
        result = index.get_summary(conversation_id, user_email=user_email)
        if result is None:
            return ToolCallResult(
                tool_id="", tool_name="get_conversation_summary",
                error=f"Conversation not found: {conversation_id}",
            )
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_summary",
            result=_truncate_result(json.dumps(result, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="get_conversation_summary",
            error=f"Error getting conversation summary: {e}",
        )

# ---------------------------------------------------------------------------
# Tool Call History Tools (category: conversation)
# --- Uses code_common/tool_call_history.py ---
# ---------------------------------------------------------------------------
from code_common.tool_call_history import TOOL_HISTORY_TOOLS

def _history_tool_kwargs(tool_name: str) -> dict:
    """Return TOOL_HISTORY_TOOLS[tool_name] kwargs suitable for register_tool."""
    return {k: v for k, v in TOOL_HISTORY_TOOLS[tool_name].items()
            if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}


@register_tool(**_history_tool_kwargs("list_search_history"))
def handle_list_search_history(args: dict, context: ToolContext) -> ToolCallResult:
    """List previous web searches and page reads with metadata.

    Queries the tool call history DB for search-category tool calls.
    """
    try:
        from code_common.tool_call_history import get_tool_call_history_db, SEARCH_TOOL_NAMES
        db = get_tool_call_history_db()
        if not db:
            return ToolCallResult(
                tool_id="", tool_name="list_search_history",
                error="Tool call history unavailable.",
            )
        user_email = getattr(context, 'user_email', '') or ''
        conversation_id = getattr(context, 'conversation_id', '') or ''
        limit = min(int(args.get("limit", 20)), 100)
        since_hours = args.get("since_hours")
        since_ts = None
        if since_hours:
            import time as _time
            since_ts = _time.time() - float(since_hours) * 3600
        conv_id = conversation_id if args.get("conversation_only") else None
        rows = db.list_calls(
            user_email=user_email,
            tool_category="search",
            conversation_id=conv_id,
            since=since_ts,
            limit=limit,
        )
        query_contains = (args.get("query_contains") or "").lower()
        if query_contains:
            rows = [r for r in rows if query_contains in r.get("args_json", "").lower()]
        # Truncate args_json for readability
        for r in rows:
            r["args_summary"] = (r.pop("args_json", "") or "")[:200]
        return ToolCallResult(
            tool_id="", tool_name="list_search_history",
            result=_truncate_result(json.dumps(rows, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="list_search_history",
            error=f"Error listing search history: {e}",
        )


@register_tool(**_history_tool_kwargs("get_search_results"))
def handle_get_search_results(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full result text of previous search/page-read calls by ID.

    Returns the most recent execution for each requested ID.
    """
    try:
        from code_common.tool_call_history import get_tool_call_history_db
        db = get_tool_call_history_db()
        if not db:
            return ToolCallResult(
                tool_id="", tool_name="get_search_results",
                error="Tool call history unavailable.",
            )
        user_email = getattr(context, 'user_email', '') or ''
        ids = args.get("ids", [])
        if not ids:
            return ToolCallResult(
                tool_id="", tool_name="get_search_results",
                error="No IDs provided. Use list_search_history first to find IDs.",
            )
        rows = db.get_results(user_email=user_email, ids=ids, tool_category="search")
        return ToolCallResult(
            tool_id="", tool_name="get_search_results",
            result=_truncate_result(json.dumps(rows, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="get_search_results",
            error=f"Error getting search results: {e}",
        )


@register_tool(**_history_tool_kwargs("list_tool_call_history"))
def handle_list_tool_call_history(args: dict, context: ToolContext) -> ToolCallResult:
    """List previous tool calls across all categories with metadata.

    Queries the tool call history DB with optional filters.
    """
    try:
        from code_common.tool_call_history import get_tool_call_history_db
        db = get_tool_call_history_db()
        if not db:
            return ToolCallResult(
                tool_id="", tool_name="list_tool_call_history",
                error="Tool call history unavailable.",
            )
        user_email = getattr(context, 'user_email', '') or ''
        conversation_id = getattr(context, 'conversation_id', '') or ''
        limit = min(int(args.get("limit", 20)), 100)
        since_hours = args.get("since_hours")
        since_ts = None
        if since_hours:
            import time as _time
            since_ts = _time.time() - float(since_hours) * 3600
        conv_id = conversation_id if args.get("conversation_only") else None
        tool_category = args.get("tool_category_filter") or None
        tool_name = args.get("tool_name_filter") or None
        rows = db.list_calls(
            user_email=user_email,
            tool_category=tool_category,
            tool_name=tool_name,
            conversation_id=conv_id,
            since=since_ts,
            limit=limit,
        )
        # Truncate args_json for readability
        for r in rows:
            r["args_summary"] = (r.pop("args_json", "") or "")[:200]
        return ToolCallResult(
            tool_id="", tool_name="list_tool_call_history",
            result=_truncate_result(json.dumps(rows, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="list_tool_call_history",
            error=f"Error listing tool call history: {e}",
        )


@register_tool(**_history_tool_kwargs("get_tool_call_results"))
def handle_get_tool_call_results(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full result text of previous tool calls by ID (any category).

    Returns the most recent execution for each requested ID.
    """
    try:
        from code_common.tool_call_history import get_tool_call_history_db
        db = get_tool_call_history_db()
        if not db:
            return ToolCallResult(
                tool_id="", tool_name="get_tool_call_results",
                error="Tool call history unavailable.",
            )
        user_email = getattr(context, 'user_email', '') or ''
        ids = args.get("ids", [])
        if not ids:
            return ToolCallResult(
                tool_id="", tool_name="get_tool_call_results",
                error="No IDs provided. Use list_tool_call_history first to find IDs.",
            )
        rows = db.get_results(user_email=user_email, ids=ids)
        return ToolCallResult(
            tool_id="", tool_name="get_tool_call_results",
            result=_truncate_result(json.dumps(rows, default=str)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="get_tool_call_results",
            error=f"Error getting tool call results: {e}",
        )

# ---------------------------------------------------------------------------
# MCP Code Runner Tools (category: code_runner)
# ---------------------------------------------------------------------------


@register_tool(
    name="run_python_code",
    description=(
        "Run Python code in the project's IPython environment. "
        "Code runs in a sandboxed environment with 120s timeout. "
        "Has access to project-installed packages (pandas, numpy, scikit-learn, matplotlib, etc.)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code_string": {"type": "string", "description": "Python code to execute. Can be multi-line"},
        },
        "required": ["code_string"],
    },
    is_interactive=False,
    category="code_runner",
)
def handle_run_python_code(args: dict, context: ToolContext) -> ToolCallResult:
    """Execute Python code using the project's code runner infrastructure.

    Delegates to ``code_runner.run_code_once`` which runs the code inside a
    ``PythonEnvironmentWithForceKill`` subprocess with a 120-second timeout,
    memory limits, and structured output capture.  The conda ``science-reader``
    environment is used (inherited from the parent process).

    Parameters
    ----------
    args:
        Parsed arguments containing ``code_string``.
    context:
        Tool execution context.

    Returns
    -------
    ToolCallResult
        Formatted execution output (stdout, stderr, status) or an error.
    """
    code_string = args.get("code_string", "")
    logger.info(
        "run_python_code invoked: code_length=%d, user=%s",
        len(code_string), context.user_email,
    )

    if not code_string.strip():
        return ToolCallResult(
            tool_id="", tool_name="run_python_code",
            error="code_string is required and must not be empty.",
        )

    try:
        from code_runner import run_code_once

        result = run_code_once(code_string)
        result_text = result if isinstance(result, str) else str(result)

        return ToolCallResult(
            tool_id="", tool_name="run_python_code",
            result=_truncate_result(result_text),
        )

    except Exception as exc:
        logger.exception("run_python_code failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="run_python_code",
            error=f"Code execution failed: {exc}",
        )


# ---------------------------------------------------------------------------
# MCP Artefact Tools (category: artefacts)
# ---------------------------------------------------------------------------

# --- Artefact tool helpers (mirrors mcp_server/artefacts.py) ---

def _art_load_conversation(conversation_id):
    """Load a Conversation for artefact operations."""
    from Conversation import Conversation
    import os as _os
    storage = _os.environ.get("STORAGE_DIR", "storage")
    folder = _os.path.join(storage, "conversations", conversation_id)
    return Conversation.load_local(folder)


@register_tool(
    name="artefacts_list",
    description=(
        "List all artefacts in a conversation. Returns a JSON array of artefact "
        "metadata objects with id, name, file_type, file_name, created_at, "
        "updated_at, size_bytes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation to list artefacts from"},
        },
        "required": ["conversation_id"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_list(args: dict, context: ToolContext) -> ToolCallResult:
    """List artefacts in a conversation."""
    import json as _json
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _art_load_conversation(conversation_id)
        artefacts = conv.list_artefacts()
        result_text = _json.dumps(artefacts)
        return ToolCallResult(
            tool_id="", tool_name="artefacts_list",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_list",
            error=f"artefacts_list failed: {exc}",
        )


@register_tool(
    name="artefacts_create",
    description=(
        "Create a new artefact file in the conversation (write operation). "
        "Artefacts are the ONLY way to create persistent files. Returns file_path "
        "for direct editing. File types: md, txt, py, js, json, html, css."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation to create the artefact in"},
            "name": {"type": "string", "description": "Display name for the artefact"},
            "file_type": {"type": "string", "description": "File extension (e.g. md, py, json)"},
            "initial_content": {
                "type": "string",
                "description": "Initial file content",
                "default": "",
            },
        },
        "required": ["conversation_id", "name", "file_type"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_create(args: dict, context: ToolContext) -> ToolCallResult:
    """Create a new artefact in the conversation."""
    import json as _json
    import os as _os
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    name = args.get("name", "")
    file_type = args.get("file_type", "")
    initial_content = args.get("initial_content", "")
    try:
        conv = _art_load_conversation(conversation_id)
        result = conv.create_artefact(name, file_type, initial_content)
        result["file_path"] = _os.path.join(conv.artefacts_path, result["file_name"])
        result_text = _json.dumps(result)
        return ToolCallResult(
            tool_id="", tool_name="artefacts_create",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_create",
            error=f"artefacts_create failed: {exc}",
        )


@register_tool(
    name="artefacts_get",
    description=(
        "Get artefact metadata, content, and file_path. Returns the full "
        "artefact including its content read from disk and the absolute "
        "file_path for direct editing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
        },
        "required": ["conversation_id", "artefact_id"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_get(args: dict, context: ToolContext) -> ToolCallResult:
    """Get artefact content and metadata."""
    import json as _json
    import os as _os
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    try:
        conv = _art_load_conversation(conversation_id)
        result = conv.get_artefact(artefact_id)
        result["file_path"] = _os.path.join(conv.artefacts_path, result["file_name"])
        result_text = _json.dumps(result)
        return ToolCallResult(
            tool_id="", tool_name="artefacts_get",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_get",
            error=f"artefacts_get failed: {exc}",
        )


@register_tool(
    name="artefacts_get_file_path",
    description=(
        "Get the absolute file path for an artefact. Returns JUST the "
        "filesystem path so tools can edit the artefact directly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
        },
        "required": ["conversation_id", "artefact_id"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_get_file_path(args: dict, context: ToolContext) -> ToolCallResult:
    """Get the absolute file path for an artefact."""
    import json as _json
    import os as _os
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    try:
        conv = _art_load_conversation(conversation_id)
        _idx, entry = conv._get_artefact_entry(artefact_id)
        file_path = _os.path.join(conv.artefacts_path, entry["file_name"])
        result_text = _json.dumps({"file_path": file_path})
        return ToolCallResult(
            tool_id="", tool_name="artefacts_get_file_path",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_get_file_path",
            error=f"artefacts_get_file_path failed: {exc}",
        )


@register_tool(
    name="artefacts_update",
    description=(
        "Update the full content of an artefact (write operation). "
        "Overwrites the artefact file with the given content. For partial edits, "
        "prefer using artefacts_get_file_path and editing directly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
            "content": {"type": "string", "description": "New file content to write"},
        },
        "required": ["conversation_id", "artefact_id", "content"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_update(args: dict, context: ToolContext) -> ToolCallResult:
    """Update the full content of an artefact."""
    import json as _json
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    content = args.get("content", "")
    try:
        conv = _art_load_conversation(conversation_id)
        result = conv.update_artefact_content(artefact_id, content)
        result_text = _json.dumps(result)
        return ToolCallResult(
            tool_id="", tool_name="artefacts_update",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_update",
            error=f"artefacts_update failed: {exc}",
        )


@register_tool(
    name="artefacts_delete",
    description=(
        "Delete an artefact file and its metadata (write operation). "
        "Removes the artefact file from disk and clears its metadata entry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact to delete"},
        },
        "required": ["conversation_id", "artefact_id"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_delete(args: dict, context: ToolContext) -> ToolCallResult:
    """Delete an artefact file and its metadata."""
    import json as _json
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    try:
        conv = _art_load_conversation(conversation_id)
        conv.delete_artefact(artefact_id)
        result_text = _json.dumps({"success": True})
        return ToolCallResult(
            tool_id="", tool_name="artefacts_delete",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_delete",
            error=f"artefacts_delete failed: {exc}",
        )


@register_tool(
    name="artefacts_propose_edits",
    description=(
        "Propose LLM-generated edits to an artefact (advanced, requires prior artefacts_get). "
        "Sends an instruction to generate edit operations using an LLM. "
        "Returns proposed ops and a diff."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
            "instruction": {"type": "string", "description": "Natural language edit instruction for the LLM"},
            "selection_start_line": {
                "type": "integer",
                "description": "Optional start line of selection to edit",
            },
            "selection_end_line": {
                "type": "integer",
                "description": "Optional end line of selection to edit",
            },
        },
        "required": ["conversation_id", "artefact_id", "instruction"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_propose_edits(args: dict, context: ToolContext) -> ToolCallResult:
    """Propose LLM-generated edits to an artefact via Flask backend."""
    import json as _json
    import os as _os
    import requests as http_requests
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    instruction = args.get("instruction", "")
    selection_start_line = args.get("selection_start_line")
    selection_end_line = args.get("selection_end_line")
    try:
        FLASK_PORT = int(_os.environ.get("FLASK_PORT", "5000"))
        url = f"http://localhost:{FLASK_PORT}/artefacts/{conversation_id}/{artefact_id}/propose_edits"
        body = {"instruction": instruction}
        if selection_start_line:
            body["selection_start_line"] = selection_start_line
        if selection_end_line:
            body["selection_end_line"] = selection_end_line
        resp = http_requests.post(url, json=body, timeout=120)
        result_text = _json.dumps(resp.json())
        return ToolCallResult(
            tool_id="", tool_name="artefacts_propose_edits",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_propose_edits",
            error=f"artefacts_propose_edits failed: {exc}",
        )


@register_tool(
    name="artefacts_apply_edits",
    description=(
        "Apply proposed edit operations to an artefact (advanced, requires prior artefacts_get). "
        "Applies previously proposed ops if the base_hash matches "
        "(optimistic concurrency control)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
            "base_hash": {"type": "string", "description": "Hash of the content the ops were generated against"},
            "ops": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of edit operations to apply",
            },
        },
        "required": ["conversation_id", "artefact_id", "base_hash", "ops"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_artefacts_apply_edits(args: dict, context: ToolContext) -> ToolCallResult:
    """Apply edit operations to an artefact via Flask backend."""
    import json as _json
    import os as _os
    import requests as http_requests
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    artefact_id = args.get("artefact_id", "")
    base_hash = args.get("base_hash", "")
    ops = args.get("ops", [])
    try:
        FLASK_PORT = int(_os.environ.get("FLASK_PORT", "5000"))
        url = f"http://localhost:{FLASK_PORT}/artefacts/{conversation_id}/{artefact_id}/apply_edits"
        body = {"base_hash": base_hash, "ops": ops}
        resp = http_requests.post(url, json=body, timeout=60)
        result_text = _json.dumps(resp.json())
        return ToolCallResult(
            tool_id="", tool_name="artefacts_apply_edits",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="artefacts_apply_edits",
            error=f"artefacts_apply_edits failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Enhanced Artefact Chat Tools (propose_artefact_edit, read_artefact, create_or_delete_artefact)
# ---------------------------------------------------------------------------


@register_tool(
    name="propose_artefact_edit",
    description=(
        "Propose edits to an artefact using natural language instruction. "
        "The LLM generates edit operations and returns a unified diff. "
        "Use include_context=true to inject conversation summary and recent messages for better edits."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
            "instruction": {"type": "string", "description": "Natural language edit instruction"},
            "start_line": {"type": "integer", "description": "Optional: focus edit on lines starting here (1-indexed)"},
            "end_line": {"type": "integer", "description": "Optional: focus edit on lines ending here (1-indexed)"},
            "include_context": {"type": "boolean", "description": "If true, include conversation summary and recent messages for context-aware edits", "default": False},
        },
        "required": ["conversation_id", "artefact_id", "instruction"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_propose_artefact_edit(args: dict, context: ToolContext) -> ToolCallResult:
    """Propose LLM-generated edits to an artefact directly (no HTTP round-trip)."""
    import json as _json
    import hashlib
    from difflib import unified_diff

    conversation_id = args.get("conversation_id", "") or context.conversation_id
    artefact_id = args.get("artefact_id", "")
    instruction = args.get("instruction", "").strip()
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    include_context = args.get("include_context", False)

    if not instruction:
        return ToolCallResult(tool_id="", tool_name="propose_artefact_edit", error="instruction is required")

    try:
        conv = _art_load_conversation(conversation_id)
        artefact = conv.get_artefact(artefact_id)
        content = artefact.get("content", "")
        base_hash = hashlib.sha256(content.encode()).hexdigest()

        # Build selection text
        selection_text = ""
        if start_line and end_line:
            lines = content.splitlines()
            s = max(1, int(start_line)) - 1
            e = min(int(end_line), len(lines))
            selection_text = "\n".join(lines[s:e])

        # Context injection
        summary_text = ""
        message_text = ""
        if include_context:
            summary_text = getattr(conv, "running_summary", "") or ""
            msgs = conv.get_message_list() or []
            recent = msgs[-10:] if len(msgs) > 10 else msgs
            message_text = "\n".join(
                f"{m.get('role','')}: {(m.get('content','') or '')[:200]}" for m in recent
            )

        # Line-numbered content
        numbered = "\n".join(f"{i+1}: {l}" for i, l in enumerate(content.splitlines()))

        prompt = f"""You are editing a file. Produce ONLY a JSON array of edit operations.

Instruction: {instruction}

File: {artefact.get("name", "")} ({artefact.get("file_type", "")})

{f"Selection (lines {start_line}-{end_line}):{chr(10)}{selection_text}" if selection_text else ""}
{f"Conversation summary:{chr(10)}{summary_text}" if summary_text else ""}
{f"Recent messages:{chr(10)}{message_text}" if message_text else ""}

File content with line numbers:
{numbered}

Allowed operations:
[
  {{"op": "replace_range", "start_line": 1, "end_line": 3, "text": "new text"}},
  {{"op": "insert_at", "start_line": 2, "text": "inserted text"}},
  {{"op": "append", "text": "text to append"}},
  {{"op": "delete_range", "start_line": 4, "end_line": 6}}
]
Return ONLY the JSON array."""

        from code_common.call_llm import CallLLm
        from code_common.utils import EXPENSIVE_LLM
        model_name = conv.get_model_override("artefact_propose_edits_model", EXPENSIVE_LLM[2]) if hasattr(conv, "get_model_override") else EXPENSIVE_LLM[2]
        llm = CallLLm(context.keys, model_name=model_name, use_gpt4=False, use_16k=False)
        response = llm(prompt, stream=False, temperature=0.2, max_tokens=2000, system="Return ONLY JSON.")

        # Consume response
        response_text = response if isinstance(response, str) else "".join(response) if hasattr(response, "__iter__") else str(response)

        # Parse JSON ops
        import re
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        ops = _json.loads(json_match.group()) if json_match else []

        # Apply ops to generate diff
        from endpoints.artefacts import _apply_ops
        new_content = _apply_ops(content, ops)
        diff_text = "\n".join(unified_diff(
            content.splitlines(), new_content.splitlines(),
            fromfile="before", tofile="after", lineterm="",
        ))

        result = {
            "proposed_ops": ops,
            "diff_text": diff_text,
            "base_hash": base_hash,
            "new_hash": hashlib.sha256(new_content.encode()).hexdigest(),
        }
        return ToolCallResult(tool_id="", tool_name="propose_artefact_edit", result=_truncate_result(_json.dumps(result)))
    except Exception as exc:
        return ToolCallResult(tool_id="", tool_name="propose_artefact_edit", error=f"propose_artefact_edit failed: {exc}")


@register_tool(
    name="read_artefact",
    description=(
        "Read an artefact's content. Four modes (checked in order): "
        "(1) map_view=true: returns a structural map (headers, table columns, bold paragraph openers) with line numbers. "
        "(2) If 'query' is provided, the artefact content + query are sent to the LLM and the answer is returned. "
        "(3) If 'start_line'/'end_line' are provided, returns only that line range. "
        "(4) Otherwise returns full artefact content as string."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation containing the artefact"},
            "artefact_id": {"type": "string", "description": "Unique identifier of the artefact"},
            "map_view": {"type": "boolean", "description": "If true, return a bird's-eye structural map of the artefact (headers, table headers, bold openers)"},
            "query": {"type": "string", "description": "Optional: question about the artefact. LLM will read the artefact and answer."},
            "start_line": {"type": "integer", "description": "Optional: start line (1-indexed) for partial read"},
            "end_line": {"type": "integer", "description": "Optional: end line (1-indexed) for partial read"},
        },
        "required": ["conversation_id", "artefact_id"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_read_artefact(args: dict, context: ToolContext) -> ToolCallResult:
    """Read artefact content, optionally querying it with LLM or returning a line range."""
    import json as _json
    import re as _re

    conversation_id = args.get("conversation_id", "") or context.conversation_id
    artefact_id = args.get("artefact_id", "")
    map_view = args.get("map_view", False)
    query = (args.get("query") or "").strip()
    start_line = args.get("start_line")
    end_line = args.get("end_line")

    try:
        conv = _art_load_conversation(conversation_id)
        artefact = conv.get_artefact(artefact_id)
        content = artefact.get("content", "")
        name = artefact.get("name", "")
        file_type = artefact.get("file_type", "")

        if map_view:
            # Mode 0: Structural map — headers, table header rows, bold paragraph openers
            lines = content.splitlines()
            landmarks = []
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Markdown headers (# through ####)
                if _re.match(r'^#{1,4}\s+', stripped):
                    landmarks.append(f"L{i}: {stripped}")
                # Table header row (first row with | separators, followed by |---|)
                elif '|' in stripped and i < len(lines) and _re.match(r'^[\s|:-]+$', lines[i].strip() if i < len(lines) else ""):
                    landmarks.append(f"L{i}: [table] {stripped}")
                # Bold at paragraph start (**word** or __word__ at line beginning)
                elif _re.match(r'^(\*\*|__).+?(\*\*|__)', stripped):
                    landmarks.append(f"L{i}: {stripped[:80]}")
                # HTML-style headers
                elif _re.match(r'^<h[1-4]', stripped, _re.IGNORECASE):
                    landmarks.append(f"L{i}: {stripped[:80]}")
            result = {"artefact_id": artefact_id, "name": name, "total_lines": len(lines), "map": "\n".join(landmarks)}
            return ToolCallResult(tool_id="", tool_name="read_artefact", result=_truncate_result(_json.dumps(result)))

        elif query:
            # Mode 1: LLM answers a question about the artefact
            from code_common.call_llm import CallLLm
            from code_common.utils import EXPENSIVE_LLM
            model_name = EXPENSIVE_LLM[2]
            llm = CallLLm(context.keys, model_name=model_name, use_gpt4=False, use_16k=False)
            prompt = f"""Document: {name} ({file_type})

Content:
{content}

Question: {query}

Answer the question based on the document content above. Be concise and precise."""
            response = llm(prompt, stream=False, temperature=0.1, max_tokens=1500)
            answer = response if isinstance(response, str) else "".join(response) if hasattr(response, "__iter__") else str(response)
            result = {"artefact_id": artefact_id, "name": name, "query": query, "answer": answer.strip()}
            return ToolCallResult(tool_id="", tool_name="read_artefact", result=_truncate_result(_json.dumps(result)))

        elif start_line and end_line:
            # Mode 2: Return line range
            lines = content.splitlines()
            s = max(1, int(start_line)) - 1
            e = min(int(end_line), len(lines))
            excerpt = "\n".join(f"{i+s+1}: {lines[i+s]}" for i in range(e - s))
            result = {"artefact_id": artefact_id, "name": name, "total_lines": len(lines), "lines": f"{start_line}-{end_line}", "content": excerpt}
            return ToolCallResult(tool_id="", tool_name="read_artefact", result=_truncate_result(_json.dumps(result)))

        else:
            # Mode 3: Full content
            result = {"artefact_id": artefact_id, "name": name, "file_type": file_type, "total_lines": len(content.splitlines()), "content": content}
            return ToolCallResult(tool_id="", tool_name="read_artefact", result=_truncate_result(_json.dumps(result)))

    except Exception as exc:
        return ToolCallResult(tool_id="", tool_name="read_artefact", error=f"read_artefact failed: {exc}")


@register_tool(
    name="create_or_delete_artefact",
    description=(
        "Create or delete an artefact. "
        "action='create': creates a new artefact with name, file_type, and optional initial_content. "
        "action='delete': deletes the artefact by artefact_id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string", "description": "Conversation to operate on"},
            "action": {"type": "string", "enum": ["create", "delete"], "description": "Whether to create or delete"},
            "artefact_id": {"type": "string", "description": "Required for delete: artefact to remove"},
            "name": {"type": "string", "description": "Required for create: display name"},
            "file_type": {"type": "string", "description": "Required for create: file extension (md, txt, py, etc.)"},
            "initial_content": {"type": "string", "description": "Optional for create: starting content"},
        },
        "required": ["conversation_id", "action"],
    },
    is_interactive=False,
    category="artefacts",
)
def handle_create_or_delete_artefact(args: dict, context: ToolContext) -> ToolCallResult:
    """Create or delete an artefact in one tool."""
    import json as _json

    conversation_id = args.get("conversation_id", "") or context.conversation_id
    action = args.get("action", "")

    try:
        conv = _art_load_conversation(conversation_id)

        if action == "create":
            name = args.get("name", "")
            file_type = args.get("file_type", "txt")
            initial_content = args.get("initial_content", "")
            if not name:
                return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", error="'name' is required for create")
            result = conv.create_artefact(name, file_type, initial_content)
            return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", result=_truncate_result(_json.dumps(result)))

        elif action == "delete":
            artefact_id = args.get("artefact_id", "")
            if not artefact_id:
                return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", error="'artefact_id' is required for delete")
            conv.delete_artefact(artefact_id)
            return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", result=_json.dumps({"status": "deleted", "artefact_id": artefact_id}))

        else:
            return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", error=f"Unknown action: {action}. Use 'create' or 'delete'.")

    except Exception as exc:
        return ToolCallResult(tool_id="", tool_name="create_or_delete_artefact", error=f"create_or_delete_artefact failed: {exc}")


# ---------------------------------------------------------------------------
# MCP Prompts & Actions Tools (category: prompts)
# ---------------------------------------------------------------------------

# --- Prompt/Action tool helpers (mirrors mcp_server/prompts_actions.py) ---

def _get_prompt_manager():
    """Return the global WrappedManager from the prompts module."""
    from prompts import manager
    return manager

def _get_prompt_cache():
    """Return the global prompt cache dict."""
    from prompts import prompt_cache
    return prompt_cache


@register_tool(
    name="prompts_list",
    description=(
        "List all saved prompts with metadata. Returns a JSON array of objects, "
        "each with keys: name, description, category, tags."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    is_interactive=False,
    category="prompts",
)
def handle_prompts_list(args: dict, context: ToolContext) -> ToolCallResult:
    """List all saved prompts with metadata."""
    try:
        manager = _get_prompt_manager()
        prompt_names = manager.keys()
        results = []
        for name in prompt_names:
            raw = manager.get_raw(name, as_dict=True)
            results.append({
                "name": name,
                "description": raw.get("description", ""),
                "category": raw.get("category", ""),
                "tags": raw.get("tags", []),
            })
        return ToolCallResult(
            tool_id="", tool_name="prompts_list",
            result=_truncate_result(json.dumps(results)),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="prompts_list",
            error=f"Failed to list prompts: {e}",
        )


@register_tool(
    name="prompts_get",
    description=(
        "Get a specific prompt by name, including its content and metadata. "
        "Returns a JSON object with name, content, and metadata (description, "
        "category, tags, version)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The exact name of the prompt to retrieve"},
        },
        "required": ["name"],
    },
    is_interactive=False,
    category="prompts",
)
def handle_prompts_get(args: dict, context: ToolContext) -> ToolCallResult:
    """Get a specific prompt by name, including content and metadata."""
    try:
        name = args.get("name", "")
        manager = _get_prompt_manager()
        if name not in manager:
            return ToolCallResult(
                tool_id="", tool_name="prompts_get",
                error=f"Prompt '{name}' not found.",
            )
        content = manager[name]
        raw = manager.get_raw(name, as_dict=True)
        metadata = {
            "description": raw.get("description", ""),
            "category": raw.get("category", ""),
            "tags": raw.get("tags", []),
            "version": raw.get("version", ""),
            "created_at": raw.get("created_at", ""),
            "updated_at": raw.get("updated_at", ""),
        }
        result_text = json.dumps({"name": name, "content": content, "metadata": metadata})
        return ToolCallResult(
            tool_id="", tool_name="prompts_get",
            result=_truncate_result(result_text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="prompts_get",
            error=f"Failed to get prompt: {e}",
        )


@register_tool(
    name="temp_llm_action",
    description=(
        "Run an ephemeral LLM action on selected text. "
        "Supported action types: explain, critique, expand, eli5, ask_temp."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "description": "One of: explain, critique, expand, eli5, ask_temp",
                "enum": ["explain", "critique", "expand", "eli5", "ask_temp"],
            },
            "selected_text": {"type": "string", "description": "The text to operate on"},
            "conversation_id": {
                "type": "string",
                "description": "Optional conversation ID for context",
            },
            "user_message": {
                "type": "string",
                "description": "Optional user prompt (used with ask_temp)",
            },
        },
        "required": ["action_type", "selected_text"],
    },
    is_interactive=False,
    category="prompts",
)
def handle_temp_llm_action(args: dict, context: ToolContext) -> ToolCallResult:
    """Run an ephemeral LLM action on selected text via Flask backend."""
    try:
        import requests as http_requests
        import os
        action_type = args.get("action_type", "")
        selected_text = args.get("selected_text", "")
        conversation_id = args.get("conversation_id")
        user_message = args.get("user_message")
        FLASK_PORT = int(os.environ.get("FLASK_PORT", "5000"))
        valid_actions = {"explain", "critique", "expand", "eli5", "ask_temp"}
        if action_type not in valid_actions:
            return ToolCallResult(
                tool_id="", tool_name="temp_llm_action",
                error=f"Invalid action_type '{action_type}'. Must be one of: {', '.join(sorted(valid_actions))}",
            )
        payload = {"action_type": action_type, "selected_text": selected_text}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if user_message:
            payload["user_message"] = user_message
        resp = http_requests.post(
            f"http://localhost:{FLASK_PORT}/temporary_llm_action",
            json=payload, stream=True, timeout=120,
        )
        resp.raise_for_status()
        collected = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
                collected.append(chunk.get("text", ""))
            except json.JSONDecodeError:
                collected.append(line)
        result_text = "".join(collected)
        return ToolCallResult(
            tool_id="", tool_name="temp_llm_action",
            result=_truncate_result(result_text),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="temp_llm_action",
            error=f"Failed to run temp_llm_action: {e}",
        )


@register_tool(
    name="prompts_create",
    description=(
        "Create a new prompt (write operation). Stores a prompt with the given "
        "name and content. Returns an error if a prompt with the same name "
        "already exists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique name for the new prompt"},
            "content": {"type": "string", "description": "The prompt text / template"},
            "description": {"type": "string", "description": "Optional human-readable description"},
            "category": {"type": "string", "description": "Optional category string"},
            "tags": {"type": "string", "description": "Optional comma-separated tags (e.g. coding,research)"},
        },
        "required": ["name", "content"],
    },
    is_interactive=False,
    category="prompts",
)
def handle_prompts_create(args: dict, context: ToolContext) -> ToolCallResult:
    """Create a new prompt with content and optional metadata."""
    try:
        name = args.get("name", "")
        content = args.get("content", "")
        description = args.get("description")
        category = args.get("category")
        tags = args.get("tags")
        manager = _get_prompt_manager()
        prompt_cache = _get_prompt_cache()
        if name in manager:
            return ToolCallResult(
                tool_id="", tool_name="prompts_create",
                error=f"Prompt '{name}' already exists. Use prompts_update to modify it.",
            )
        manager[name] = content
        prompt_cache[name] = content
        edit_kwargs = {}
        if description:
            edit_kwargs["description"] = description
        if category:
            edit_kwargs["category"] = category
        if tags:
            edit_kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if edit_kwargs:
            manager.edit(name, **edit_kwargs)
        return ToolCallResult(
            tool_id="", tool_name="prompts_create",
            result=_truncate_result(json.dumps({"success": True, "name": name})),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="prompts_create",
            error=f"Failed to create prompt: {e}",
        )


@register_tool(
    name="prompts_update",
    description=(
        "Update an existing prompt's content and metadata (write operation). "
        "The prompt must already exist — use prompts_create for new prompts."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the prompt to update"},
            "content": {"type": "string", "description": "New prompt text / template"},
            "description": {"type": "string", "description": "Optional new description"},
            "category": {"type": "string", "description": "Optional new category string"},
            "tags": {"type": "string", "description": "Optional comma-separated tags (e.g. coding,research)"},
        },
        "required": ["name", "content"],
    },
    is_interactive=False,
    category="prompts",
)
def handle_prompts_update(args: dict, context: ToolContext) -> ToolCallResult:
    """Update an existing prompt's content and metadata."""
    try:
        name = args.get("name", "")
        content = args.get("content", "")
        description = args.get("description")
        category = args.get("category")
        tags = args.get("tags")
        manager = _get_prompt_manager()
        prompt_cache = _get_prompt_cache()
        if name not in manager:
            return ToolCallResult(
                tool_id="", tool_name="prompts_update",
                error=f"Prompt '{name}' not found. Use prompts_create for new prompts.",
            )
        manager[name] = content
        prompt_cache[name] = content
        edit_kwargs = {}
        if description:
            edit_kwargs["description"] = description
        if category:
            edit_kwargs["category"] = category
        if tags:
            edit_kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if edit_kwargs:
            manager.edit(name, **edit_kwargs)
        return ToolCallResult(
            tool_id="", tool_name="prompts_update",
            result=_truncate_result(json.dumps({"success": True, "name": name})),
        )
    except Exception as e:
        return ToolCallResult(
            tool_id="", tool_name="prompts_update",
            error=f"Failed to update prompt: {e}",
        )


# ---------------------------------------------------------------------------
# Global Document Management Tools (category: documents)
# ---------------------------------------------------------------------------


def _docs_user_hash(email: str) -> str:
    """Compute the user-hash used for per-user storage directories."""
    import hashlib
    return hashlib.md5(email.encode()).hexdigest()


@register_tool(
    name="upload_global_doc",
    description=(
        "Upload a local file as a global document. Reads the file from the "
        "server filesystem, indexes it, and registers it as a global document "
        "for the user. Optionally attach tags."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file on the server filesystem"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of tag strings to attach to the document",
                "default": [],
            },
        },
        "required": ["file_path"],
    },
    is_interactive=False,
    category="documents",
)
def handle_upload_global_doc(args: dict, context: ToolContext) -> ToolCallResult:
    """Upload a local file as a global document."""
    file_path = args.get("file_path", "")
    tags = args.get("tags") or []
    try:
        if not os.path.isfile(file_path):
            return ToolCallResult(
                tool_id="", tool_name="upload_global_doc",
                error=f"File not found: {file_path}",
                result="",
            )

        from DocIndex import create_immediate_document_index

        user_hash = _docs_user_hash(context.user_email)
        user_global_dir = os.path.join(_docs_users_dir(), user_hash, "global_docs")
        os.makedirs(user_global_dir, exist_ok=True)

        doc_index = create_immediate_document_index(
            file_path, user_global_dir, _docs_get_keys()
        )
        doc_index.save_local()

        short_info = doc_index.get_short_info()
        from database.global_docs import add_global_doc

        add_global_doc(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_index.doc_id,
            doc_source=file_path,
            doc_storage=doc_index._storage,
            title=short_info.get("title", ""),
            short_summary=short_info.get("short_summary", ""),
        )

        if tags:
            from database.doc_tags import set_tags

            tag_list = [t.strip().lower() for t in tags if t.strip()]
            if tag_list:
                set_tags(
                    users_dir=_docs_users_dir(),
                    user_email=context.user_email,
                    doc_id=doc_index.doc_id,
                    tags=tag_list,
                )

        return ToolCallResult(
            tool_id="", tool_name="upload_global_doc",
            result=_truncate_result(json.dumps({
                "doc_id": doc_index.doc_id,
                "title": short_info.get("title", ""),
                "doc_storage_path": doc_index._storage,
            })),
        )
    except Exception as exc:
        logger.exception("upload_global_doc error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="upload_global_doc",
            error=f"Failed to upload global doc: {exc}",
            result="",
        )


@register_tool(
    name="delete_global_doc",
    description=(
        "Delete a global document by ID. Removes the database record for the "
        "global document. Does not delete the underlying filesystem storage."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
        },
        "required": ["doc_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_delete_global_doc(args: dict, context: ToolContext) -> ToolCallResult:
    """Delete a global document by ID."""
    doc_id = args.get("doc_id", "")
    try:
        from database.global_docs import delete_global_doc

        deleted = delete_global_doc(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
        )
        if deleted:
            return ToolCallResult(
                tool_id="", tool_name="delete_global_doc",
                result=_truncate_result(json.dumps({"success": True, "message": f"Global doc '{doc_id}' deleted."})),
            )
        return ToolCallResult(
            tool_id="", tool_name="delete_global_doc",
            error=f"Global doc '{doc_id}' not found or already deleted.",
            result="",
        )
    except Exception as exc:
        logger.exception("delete_global_doc error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="delete_global_doc",
            error=f"Failed to delete global doc: {exc}",
            result="",
        )


@register_tool(
    name="set_global_doc_tags",
    description=(
        "Set tags on a global document (replaces existing tags). Atomically "
        "replaces all tags for the document with the provided list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tag strings to set on the document",
            },
        },
        "required": ["doc_id", "tags"],
    },
    is_interactive=False,
    category="documents",
)
def handle_set_global_doc_tags(args: dict, context: ToolContext) -> ToolCallResult:
    """Set tags on a global document."""
    doc_id = args.get("doc_id", "")
    tags = args.get("tags", [])
    try:
        from database.doc_tags import set_tags

        tag_list = [t.strip().lower() for t in tags if t.strip()]
        ok = set_tags(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
            tags=tag_list,
        )
        if ok:
            return ToolCallResult(
                tool_id="", tool_name="set_global_doc_tags",
                result=_truncate_result(json.dumps({"success": True, "doc_id": doc_id, "tags": tag_list})),
            )
        return ToolCallResult(
            tool_id="", tool_name="set_global_doc_tags",
            error=f"Failed to set tags on doc '{doc_id}'.",
            result="",
        )
    except Exception as exc:
        logger.exception("set_global_doc_tags error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="set_global_doc_tags",
            error=f"Failed to set tags: {exc}",
            result="",
        )


@register_tool(
    name="assign_doc_to_folder",
    description=(
        "Assign a global document to a folder. Moves the document into the "
        "specified folder. Pass an empty string for folder_id to move the "
        "document to Unfiled."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier (from docs_list_global_docs)"},
            "folder_id": {"type": "string", "description": "The target folder ID, or empty string to unfile"},
        },
        "required": ["doc_id", "folder_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_assign_doc_to_folder(args: dict, context: ToolContext) -> ToolCallResult:
    """Assign a global document to a folder."""
    doc_id = args.get("doc_id", "")
    folder_id = args.get("folder_id", "")
    try:
        from database.doc_folders import assign_doc_to_folder

        resolved_folder_id = folder_id if folder_id else None
        ok = assign_doc_to_folder(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
            folder_id=resolved_folder_id,
        )
        if ok:
            return ToolCallResult(
                tool_id="", tool_name="assign_doc_to_folder",
                result=_truncate_result(json.dumps({"success": True, "doc_id": doc_id, "folder_id": folder_id})),
            )
        return ToolCallResult(
            tool_id="", tool_name="assign_doc_to_folder",
            error=f"Failed to assign doc '{doc_id}' to folder '{folder_id}'.",
            result="",
        )
    except Exception as exc:
        logger.exception("assign_doc_to_folder error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="assign_doc_to_folder",
            error=f"Failed to assign to folder: {exc}",
            result="",
        )


# ---------------------------------------------------------------------------
# PKB Listing Tools (category: pkb)
# ---------------------------------------------------------------------------


@register_tool(
    name="pkb_list_contexts",
    description=(
        "List all PKB contexts for the user. Returns a JSON array of context "
        "objects with context_id, name, description, and claim_count."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_contexts(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB contexts."""
    try:
        api = _get_pkb_api()
        from endpoints.pkb import serialize_context

        contexts_with_counts = api.contexts.get_with_claim_count(limit=200)
        results = []
        for ctx, count in contexts_with_counts:
            ctx_dict = serialize_context(ctx)
            ctx_dict["claim_count"] = count
            results.append(ctx_dict)

        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as exc:
        logger.exception("pkb_list_contexts error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            error=f"Failed to list PKB contexts: {exc}",
            result="",
        )


@register_tool(
    name="pkb_list_entities",
    description=(
        "List all PKB entities for the user. Returns a JSON array of entity "
        "objects with entity_id, entity_type, name, and metadata."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "description": "Optional filter by entity type",
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entities to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_entities(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB entities."""
    entity_type = args.get("entity_type", "") or ""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        from endpoints.pkb import serialize_entity

        filters = {}
        if entity_type:
            filters["entity_type"] = entity_type

        entities = api.entities.list(filters=filters, limit=limit, order_by="name")
        results = [serialize_entity(e) for e in entities]

        return ToolCallResult(
            tool_id="", tool_name="pkb_list_entities",
            result=_truncate_result(json.dumps({"entities": results, "count": len(results)}, default=str)),
        )
    except Exception as exc:
        logger.exception("pkb_list_entities error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_entities",
            error=f"Failed to list PKB entities: {exc}",
            result="",
        )


@register_tool(
    name="pkb_list_tags",
    description=(
        "List all PKB tags for the user. Returns a JSON array of tag "
        "objects with tag_id, name, parent_tag_id, and metadata."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of tags to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_tags(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB tags."""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        from endpoints.pkb import serialize_tag

        tags = api.tags.list(limit=limit, order_by="name")
        results = [serialize_tag(t) for t in tags]

        return ToolCallResult(
            tool_id="", tool_name="pkb_list_tags",
            result=_truncate_result(json.dumps({"tags": results, "count": len(results)}, default=str)),
        )
    except Exception as exc:
        logger.exception("pkb_list_tags error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_tags",
            error=f"Failed to list PKB tags: {exc}",
            result="",
        )


# ---------------------------------------------------------------------------
# PKB STM Tools (category: pkb)
# ---------------------------------------------------------------------------


@register_tool(
    name="pkb_get_stm",
    description=(
        "Get the user's active short-term memories (STM). "
        "STM items are transient context captured during conversations that persist briefly "
        "and get promoted to long-term claims if reinforced across conversations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max memories to return", "default": 50},
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_get_stm(args: dict, context: ToolContext) -> ToolCallResult:
    """Get active short-term memories."""
    limit = args.get("limit", 50)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.get_active_short_term_memories(limit=limit)
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_stm",
            result=_truncate_result(_pkb_serialize_action_result(result)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_get_stm",
            error=f"pkb_get_stm failed: {exc}",
        )


@register_tool(
    name="pkb_promote_stm",
    description=(
        "Promote a short-term memory to a permanent long-term claim. "
        "Use when context has proven valuable and should be retained permanently."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "UUID of the short-term memory to promote"},
        },
        "required": ["memory_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_promote_stm(args: dict, context: ToolContext) -> ToolCallResult:
    """Promote an STM item to a long-term claim."""
    memory_id = args.get("memory_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.promote_short_term_memory(memory_id)
        return ToolCallResult(
            tool_id="", tool_name="pkb_promote_stm",
            result=_truncate_result(_pkb_serialize_action_result(result)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_promote_stm",
            error=f"pkb_promote_stm failed: {exc}",
        )


@register_tool(
    name="pkb_dismiss_stm",
    description=(
        "Dismiss (delete) a short-term memory that is no longer relevant."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "UUID of the short-term memory to dismiss"},
        },
        "required": ["memory_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_dismiss_stm(args: dict, context: ToolContext) -> ToolCallResult:
    """Dismiss a short-term memory."""
    memory_id = args.get("memory_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.delete_short_term_memory(memory_id)
        return ToolCallResult(
            tool_id="", tool_name="pkb_dismiss_stm",
            result=_truncate_result(_pkb_serialize_action_result(result)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_dismiss_stm",
            error=f"pkb_dismiss_stm failed: {exc}",
        )


@register_tool(
    name="pkb_propose_extraction",
    description=(
        "Extract knowledge claims from arbitrary text. Runs the extraction pipeline "
        "and returns proposed claims for review. Does NOT auto-commit — caller should "
        "present proposals to the user or call pkb_add_claim for accepted ones. "
        "Use to ingest info from documents, code comments, meeting notes, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to extract claims from"},
            "extraction_mode": {
                "type": "string",
                "description": "'relaxed' (default) or 'aggressive'",
                "default": "relaxed",
            },
        },
        "required": ["text"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_propose_extraction(args: dict, context: ToolContext) -> ToolCallResult:
    """Extract proposed claims from text."""
    text = args.get("text", "")
    extraction_mode = args.get("extraction_mode", "relaxed")
    if extraction_mode not in ("relaxed", "aggressive"):
        extraction_mode = "relaxed"
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        from truth_management_system.interface.conversation_distillation import ConversationDistiller
        distiller = ConversationDistiller(
            user_api, user_api.keys, user_api.config,
            extraction_mode=extraction_mode,
        )
        plan = distiller.extract_and_propose(
            conversation_summary="",
            user_message=text,
            assistant_message="",
        )
        if not plan.candidates:
            return ToolCallResult(
                tool_id="", tool_name="pkb_propose_extraction",
                result=json.dumps({"proposals": [], "count": 0}),
            )
        proposals = []
        for c in plan.candidates:
            proposals.append({
                "statement": c.statement,
                "claim_type": c.claim_type,
                "context_domain": c.context_domain,
                "confidence": c.confidence,
                "reason": getattr(c, "reason", None),
            })
        return ToolCallResult(
            tool_id="", tool_name="pkb_propose_extraction",
            result=_truncate_result(json.dumps({"proposals": proposals, "count": len(proposals)}, default=str)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_propose_extraction",
            error=f"pkb_propose_extraction failed: {exc}",
        )


@register_tool(
    name="pkb_summarize",
    parameters={"type": "object", "properties": {}, "required": []},
    category="pkb",
    description="Get a summary overview of the user's knowledge base — key areas, topics, and statistics.",
)
def handle_pkb_summarize(args: dict, context: ToolContext) -> ToolCallResult:
    try:
        api = _get_pkb_user_api(context.user_email)
        summary = ""
        try:
            from truth_management_system.interface.overview_manager import PKBOverviewManager
            om = PKBOverviewManager(api.db, api.keys, api.config)
            snippet = om.get_key_areas_snippet(context.user_email)
            if snippet:
                summary = snippet
        except Exception:
            pass
        if not summary:
            tags = api.tags.list(limit=50)
            tag_names = [t.name for t in tags] if tags else []
            summary = f"Tags ({len(tag_names)}): {', '.join(tag_names[:20])}"
        return ToolCallResult(
            tool_id="", tool_name="pkb_summarize",
            result=json.dumps({"summary": summary}),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_summarize",
            error=f"pkb_summarize failed: {exc}",
        )


@register_tool(
    name="pkb_negative_feedback",
    parameters={"type": "object", "properties": {"claim_id": {"type": "string", "description": "UUID of the claim"}, "context": {"type": "string", "description": "Why it wasn't helpful"}}, "required": ["claim_id"]},
    category="pkb",
    description="Record negative feedback on a claim that was not relevant or helpful in this context.",
)
def handle_pkb_negative_feedback(args: dict, context: ToolContext) -> ToolCallResult:
    try:
        api = _get_pkb_user_api(context.user_email)
        result = api.add_claim_feedback(args["claim_id"], context=args.get("context", ""))
        return ToolCallResult(
            tool_id="", tool_name="pkb_negative_feedback",
            result=json.dumps({"recorded": result.success}),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_negative_feedback",
            error=f"pkb_negative_feedback failed: {exc}",
        )


@register_tool(
    name="pkb_recent_promotions",
    description=(
        "List STM items recently promoted to long-term claims. "
        "Shows what context crossed the reinforcement threshold and became permanent."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results", "default": 10},
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_recent_promotions(args: dict, context: ToolContext) -> ToolCallResult:
    """Get recently promoted STM items."""
    limit = args.get("limit", 10)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.get_recent_promotions(limit=limit)
        return ToolCallResult(
            tool_id="", tool_name="pkb_recent_promotions",
            result=_truncate_result(_pkb_serialize_action_result(result)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_recent_promotions",
            error=f"pkb_recent_promotions failed: {exc}",
        )


@register_tool(
    name="pkb_demote_claim",
    description=(
        "Reverse a STM→claim promotion. Deletes the created claim "
        "and resets the STM item to unpromoted state."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "UUID of the STM memory whose promotion to reverse"},
        },
        "required": ["memory_id"],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_demote_claim(args: dict, context: ToolContext) -> ToolCallResult:
    """Demote a promoted STM item."""
    memory_id = args.get("memory_id", "")
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        result = user_api.demote_promoted_claim(memory_id)
        return ToolCallResult(
            tool_id="", tool_name="pkb_demote_claim",
            result=_truncate_result(_pkb_serialize_action_result(result)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_demote_claim",
            error=f"pkb_demote_claim failed: {exc}",
        )


@register_tool(
    name="pkb_fading_claims",
    parameters={"type": "object", "properties": {}, "required": []},
    category="pkb",
    description="List claims that have gone dormant (fading memories) and may need reinforcement or cleanup.",
)
def handle_pkb_fading_claims(args: dict, context: ToolContext) -> ToolCallResult:
    try:
        api = _get_pkb_user_api(context.user_email)
        result = api.get_lifecycle_notifications()
        fading = result.data.get("newly_dormant", []) if result.success else []
        return ToolCallResult(
            tool_id="", tool_name="pkb_fading_claims",
            result=json.dumps({"fading": fading}),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_fading_claims",
            error=f"pkb_fading_claims failed: {exc}",
        )


@register_tool(
    name="pkb_reinforce_claim",
    parameters={"type": "object", "properties": {"claim_id": {"type": "string", "description": "UUID of the claim to reinforce"}}, "required": ["claim_id"]},
    category="pkb",
    description="Reinforce a claim — resets its decay timer and revives it if dormant.",
)
def handle_pkb_reinforce_claim(args: dict, context: ToolContext) -> ToolCallResult:
    try:
        api = _get_pkb_user_api(context.user_email)
        result = api.reinforce_claim(args["claim_id"])
        return ToolCallResult(
            tool_id="", tool_name="pkb_reinforce_claim",
            result=json.dumps({"reinforced": result.success, "claim_id": args["claim_id"]}),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_reinforce_claim",
            error=f"pkb_reinforce_claim failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Image Generation Tool (category: general)
# ---------------------------------------------------------------------------


@register_tool(
    name="generate_image",
    description=(
        "Generate an image from a text prompt using an image generation model. "
        "Optionally provide a base64 input image for image editing/transformation. "
        "Returns generated image data URIs and any accompanying text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The image generation prompt describing what to create"},
            "base64_input": {
                "type": "string",
                "description": "Optional base64 data URI of an existing image to edit/transform",
                "default": "",
            },
        },
        "required": ["prompt"],
    },
    is_interactive=False,
    category="general",
)
def handle_generate_image(args: dict, context: ToolContext) -> ToolCallResult:
    """Generate an image from a text prompt."""
    prompt = args.get("prompt", "")
    base64_input = args.get("base64_input") or None
    try:
        keys = context.keys if context.keys else {}
        if not keys.get("OPENROUTER_API_KEY"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        from endpoints.image_gen import generate_image_from_prompt

        result = generate_image_from_prompt(
            prompt=prompt,
            keys=keys,
            input_image=base64_input,
        )

        if result.get("error"):
            return ToolCallResult(
                tool_id="", tool_name="generate_image",
                error=result["error"],
                result="",
            )

        return ToolCallResult(
            tool_id="", tool_name="generate_image",
            result=_truncate_result(json.dumps({
                "images": result.get("images", []),
                "text": result.get("text", ""),
            })),
        )
    except Exception as exc:
        logger.exception("generate_image error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="generate_image",
            error=f"Failed to generate image: {exc}",
            result="",
        )


# ---------------------------------------------------------------------------
# Audio Transcription Tool (category: general)
# ---------------------------------------------------------------------------


@register_tool(
    name="transcribe_audio",
    description=(
        "Transcribe an audio file to text. Reads the audio file from the server "
        "filesystem and returns the transcribed text using either OpenAI or "
        "AssemblyAI transcription services."
    ),
    parameters={
        "type": "object",
        "properties": {
            "audio_file_path": {"type": "string", "description": "Absolute path to the audio file on the server filesystem"},
        },
        "required": ["audio_file_path"],
    },
    is_interactive=False,
    category="general",
)
def handle_transcribe_audio(args: dict, context: ToolContext) -> ToolCallResult:
    """Transcribe an audio file to text."""
    audio_file_path = args.get("audio_file_path", "")
    try:
        if not os.path.isfile(audio_file_path):
            return ToolCallResult(
                tool_id="", tool_name="transcribe_audio",
                error=f"Audio file not found: {audio_file_path}",
                result="",
            )

        from transcribe_audio import transcribe_audio as run_transcribe_audio

        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        transcription = run_transcribe_audio(
            audio_file_path,
            openai_api_key=keys.get("openAIKey"),
            assemblyai_api_key=keys.get("assemblyAIKey"),
        )

        return ToolCallResult(
            tool_id="", tool_name="transcribe_audio",
            result=_truncate_result(json.dumps({"transcription": transcription})),
        )
    except Exception as exc:
        logger.exception("transcribe_audio error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="transcribe_audio",
            error=f"Failed to transcribe audio: {exc}",
            result="",
        )


# ===========================================================================
# Coding category tools — ported from mcp_server/coding_tools.py
# ===========================================================================

# Maximum characters returned by coding file tools to keep results LLM-friendly
_FS_MAX_READ_CHARS = 100_000
_FS_MAX_GREP_MATCHES = 200


def _coding_resolve_safe_path(rel_or_abs: str) -> str:
    """Resolve a path and verify it stays within the project root (cwd).

    Raises ValueError if the resolved path escapes the project root.
    """
    root = os.getcwd()
    resolved = os.path.normpath(os.path.join(root, rel_or_abs))
    if not resolved.startswith(root):
        raise ValueError(
            f"Path '{rel_or_abs}' escapes the project root '{root}'. "
            "Only paths within the project directory are allowed."
        )
    return resolved


def _coding_todo_path(scope: str, conversation_id: str) -> str:
    """Return the absolute path to the todo JSON file.

    scope='global' -> <STORAGE_DIR>/todo.json
    scope='conversation' -> <STORAGE_DIR>/conversations/<conversation_id>/todo.json
    """
    storage = os.environ.get("STORAGE_DIR", "storage")
    root = os.getcwd()
    if scope == "conversation":
        if not conversation_id:
            raise ValueError("conversation_id is required when scope='conversation'.")
        return os.path.join(root, storage, "conversations", conversation_id, "todo.json")
    return os.path.join(root, storage, "todo.json")


def _coding_get_keys(context: ToolContext) -> dict:
    """Get API keys from context, falling back to keyParser."""
    keys = context.keys if context.keys else {}
    if not keys.get("openAIKey"):
        from endpoints.utils import keyParser
        keys = keyParser({})
    return keys


# ---------------------------------------------------------------------------
# Tool: fs_read_file
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_read_file",
    description=(
        "Read file contents. Supports text (with line range), PDF (pdfplumber), "
        "and images (vision LLM). Use start_line/end_line for text sections."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative to project root or absolute). .pdf files are read as PDFs."},
            "start_line": {"type": "integer", "description": "First line to return (1-indexed, default 1). Text files only.", "default": 1},
            "end_line": {"type": "integer", "description": "Last line to return inclusive (0 = read to end). Text files only.", "default": 0},
        },
        "required": ["path"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_read_file(args: dict, context: ToolContext) -> ToolCallResult:
    """Read file contents — text with line numbers, PDF via pdfplumber, image via vision LLM."""
    path = args.get("path", "")
    start_line = int(args.get("start_line", 1))
    end_line = int(args.get("end_line", 0))
    logger.info("fs_read_file invoked: path=%s, user=%s", path, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_read_file", result="", error="path is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        if not os.path.isfile(abs_path):
            return ToolCallResult(tool_id="", tool_name="fs_read_file", result="", error=f"File not found: {path}")

        # PDF branch
        if abs_path.lower().endswith(".pdf"):
            try:
                import pdfplumber
                with pdfplumber.open(abs_path) as pdf:
                    pages_text = []
                    for i, page in enumerate(pdf.pages, 1):
                        text = page.extract_text()
                        if text and text.strip():
                            pages_text.append(f"--- Page {i} ---\n{text.strip()}")
                if not pages_text:
                    raise ValueError("pdfplumber found no extractable text in PDF")
                full_text = "\n\n".join(pages_text)
            except ImportError:
                from base import freePDFReader
                full_text = freePDFReader(abs_path)
                if not full_text or not full_text.strip():
                    raise ValueError("freePDFReader found no extractable text in PDF")
            if len(full_text) > _FS_MAX_READ_CHARS:
                full_text = full_text[:_FS_MAX_READ_CHARS] + "\n\n... [truncated — PDF too large]"
            return ToolCallResult(tool_id="", tool_name="fs_read_file", result=full_text)

        # Image branch
        _IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
        if os.path.splitext(abs_path)[1].lower() in _IMAGE_EXTS:
            try:
                from code_common.call_llm import call_llm
                from common import VERY_CHEAP_LLM
                _keys = _coding_get_keys(context)
                system = "You are an expert image analyst. Produce a comprehensive analysis."
                prompt = (
                    "Analyse this image and return exactly the following four sections:\n\n"
                    "**OCR**\nTranscribe all readable text, preserving structure.\n\n"
                    "**Scene Description**\nDescribe setting, layout, visual composition.\n\n"
                    "**Objects & Elements**\nBullet list of all key objects and visual elements.\n\n"
                    "**Summary**\n2-3 sentence summary of what this image communicates."
                )
                result = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                                  text=prompt, images=[abs_path],
                                  temperature=0.0, stream=False, system=system)
                return ToolCallResult(
                    tool_id="", tool_name="fs_read_file",
                    result=result if isinstance(result, str) else "(empty)",
                )
            except Exception as img_exc:
                logger.exception("fs_read_file image error: %s", img_exc)
                return ToolCallResult(tool_id="", tool_name="fs_read_file", result="", error=f"Image analysis failed: {img_exc}")

        # Text branch
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()

        total = len(lines)
        s = max(1, start_line) - 1  # 0-indexed
        e = total if end_line <= 0 else min(end_line, total)

        selected = lines[s:e]
        numbered = "".join(f"{s + i + 1}: {line}" for i, line in enumerate(selected))

        if len(numbered) > _FS_MAX_READ_CHARS:
            numbered = numbered[:_FS_MAX_READ_CHARS] + "\n... [truncated]"

        return ToolCallResult(tool_id="", tool_name="fs_read_file", result=numbered)

    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_read_file", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_read_file error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_read_file", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_read_pdf
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_read_pdf",
    description=(
        "Read a PDF file with optional page selection. "
        "Page selection via pages argument: empty=all, single='3', range='1-5', list='1,3,5'. "
        "Returns up to 100,000 characters of extracted text prefixed by a metadata header."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "PDF file path (relative to project root)."},
            "pages": {"type": "string", "description": "Page selection: empty=all, '3'=single, '1-5'=range, '1,3,5'=list.", "default": ""},
        },
        "required": ["path"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_read_pdf(args: dict, context: ToolContext) -> ToolCallResult:
    """Read a PDF with optional page selection; 100k char truncation with header metadata."""
    path = args.get("path", "")
    pages_spec = args.get("pages", "")
    logger.info("fs_read_pdf invoked: path=%s, pages=%s, user=%s", path, pages_spec, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error="path is required.")

    def _parse_pages(spec):
        if not spec or not spec.strip():
            return None
        spec = spec.strip()
        if "-" in spec and "," not in spec:
            parts = spec.split("-", 1)
            try:
                return list(range(int(parts[0]) - 1, int(parts[1])))
            except ValueError:
                pass
        if "," in spec:
            try:
                return sorted({int(p.strip()) - 1 for p in spec.split(",") if p.strip()})
            except ValueError:
                pass
        try:
            return [int(spec) - 1]
        except ValueError:
            return None

    try:
        abs_path = _coding_resolve_safe_path(path)
        if not os.path.isfile(abs_path):
            return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error=f"File not found: {path}")
        if not abs_path.lower().endswith(".pdf"):
            return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error=f"Not a PDF file: {path}")

        page_indices = _parse_pages(pages_spec)
        import pdfplumber
        with pdfplumber.open(abs_path) as _pdf:
            total = len(_pdf.pages)
            selected = list(range(total)) if page_indices is None else [i for i in page_indices if 0 <= i < total]
            pages_text = []
            for idx in selected:
                t = _pdf.pages[idx].extract_text()
                if t and t.strip():
                    pages_text.append(f"--- Page {idx + 1} ---\n{t.strip()}")
        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error="No extractable text in PDF")
        truncated = len(full_text) > _FS_MAX_READ_CHARS
        if truncated:
            full_text = full_text[:_FS_MAX_READ_CHARS]
        read_label = (
            ", ".join(str(i + 1) for i in sorted(page_indices))
            if page_indices is not None else "all pages"
        )
        header = (
            f"[PDF: {os.path.basename(path)} | Reading: {read_label} | "
            f"{total} total pages | Truncated: {'Yes' if truncated else 'No'}]\n\n"
        )
        return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result=header + full_text)

    except ImportError:
        try:
            from base import freePDFReader
            abs_path = _coding_resolve_safe_path(path)
            text = freePDFReader(abs_path)
            truncated = len(text) > _FS_MAX_READ_CHARS
            if truncated:
                text = text[:_FS_MAX_READ_CHARS]
            return ToolCallResult(
                tool_id="", tool_name="fs_read_pdf",
                result=f"[PDF: {os.path.basename(path)} | Truncated: {'Yes' if truncated else 'No'}]\n\n" + text,
            )
        except Exception as fe:
            return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error=f"PDF read failed: {fe}")
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_read_pdf error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_read_pdf", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_get_file_structure_and_summary
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_get_file_structure_and_summary",
    description=(
        "Get LLM-generated structure and summary of a file. "
        "Supports text, Markdown, PDF, and image files. An LLM orchestrates up to "
        "5 reading iterations to build full understanding, then returns a structured "
        "outline and a 2-3 paragraph summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative to project root)."},
        },
        "required": ["path"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_get_file_structure_and_summary(args: dict, context: ToolContext) -> ToolCallResult:
    """LLM agent loop (max 5 iterations) for file structure and summary."""
    import re as _re
    path = args.get("path", "")
    logger.info("fs_get_file_structure_and_summary invoked: path=%s, user=%s", path, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_get_file_structure_and_summary", result="", error="path is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        if not os.path.isfile(abs_path):
            return ToolCallResult(tool_id="", tool_name="fs_get_file_structure_and_summary", result="", error=f"File not found: {path}")

        from code_common.call_llm import call_llm
        from common import VERY_CHEAP_LLM
        _keys = _coding_get_keys(context)
        ext = os.path.splitext(abs_path)[1].lower()
        basename = os.path.basename(abs_path)
        file_size = os.path.getsize(abs_path)
        MAX_ITER = 5
        BUDGET = 12_000
        _IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})

        # Image: single-shot vision call
        if ext in _IMAGE_EXTS:
            system = "You are an expert image analyst."
            prompt = (
                "Analyse this image and return exactly the following four sections:\n\n"
                "**OCR**\nTranscribe all visible text.\n\n"
                "**Scene Description**\nDescribe setting and composition.\n\n"
                "**Objects & Elements**\nBullet list of key objects.\n\n"
                "**Summary**\n2-3 sentence summary."
            )
            desc = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                            text=prompt, images=[abs_path],
                            temperature=0.0, stream=False, system=system)
            return ToolCallResult(
                tool_id="", tool_name="fs_get_file_structure_and_summary",
                result=f"[File: {basename} | Type: image]\n\n{desc}",
            )

        # Text / PDF iterative reading with LLM JSON protocol
        SYSTEM = (
            "You are a file analysis assistant. You read files in parts and build structural understanding.\n"
            "Respond ONLY with valid JSON in one of two schemas:\n"
            'If you need more: {"action": "read_more", "reason": "...", '
            '"request": {"start_line": N, "end_line": N}} (for PDFs use "pages": "N-M")\n'
            'When ready: {"action": "done", "structure": [...], "summary": "..."}'
        )

        is_pdf = ext == ".pdf"
        is_md = ext in (".md", ".markdown")

        if is_pdf:
            try:
                import pdfplumber
                with pdfplumber.open(abs_path) as _p:
                    total_pages = len(_p.pages)
                    pages_text = []
                    for idx in range(min(5, total_pages)):
                        t = _p.pages[idx].extract_text()
                        if t and t.strip():
                            pages_text.append(f"--- Page {idx+1} ---\n{t.strip()}")
                accumulated = "\n\n".join(pages_text)[:BUDGET]
            except Exception:
                from base import freePDFReader
                accumulated = freePDFReader(abs_path)[:BUDGET]
                total_pages = -1
            file_meta = {"name": basename, "type": "pdf", "total_pages": total_pages}
        else:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
            headers = [l.strip() for l in raw.splitlines() if l.strip().startswith("#")] if is_md else []
            file_meta = {"name": basename, "type": "markdown" if is_md else "text",
                         "total_lines": raw.count("\n") + 1,
                         "headers": headers[:50]}
            accumulated = raw[:BUDGET]

        structure, summary = [], ""
        for iteration in range(1, MAX_ITER + 1):
            user_msg = (
                f"FILE METADATA: {json.dumps(file_meta)}\n\n"
                f"CONTENT (iteration {iteration}/{MAX_ITER}):\n{accumulated}\n\n"
                f"{'FINAL iteration — respond with action=done.' if iteration == MAX_ITER else ''}"
            )
            raw_resp = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                               text=user_msg, temperature=0.0, stream=False, system=SYSTEM)
            try:
                clean = raw_resp.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
                llm_json = json.loads(clean)
            except Exception:
                m = _re.search(r"\{.*\}", raw_resp, _re.DOTALL)
                llm_json = json.loads(m.group()) if m else None

            if llm_json is None or llm_json.get("action") == "done" or iteration == MAX_ITER:
                structure = (llm_json or {}).get("structure", [])
                summary = (llm_json or {}).get("summary", "")
                break

            req = llm_json.get("request", {})
            if is_pdf and "pages" in req:
                try:
                    import pdfplumber
                    spec = req["pages"]
                    parts = spec.split("-", 1)
                    pidx = list(range(int(parts[0]) - 1, int(parts[1])))
                    with pdfplumber.open(abs_path) as _p:
                        more = []
                        for idx in pidx:
                            if 0 <= idx < len(_p.pages):
                                t = _p.pages[idx].extract_text()
                                if t:
                                    more.append(f"--- Page {idx+1} ---\n{t.strip()}")
                    accumulated += "\n\n" + "\n\n".join(more)[:BUDGET // 2]
                except Exception:
                    break
            else:
                s_line = max(0, req.get("start_line", 1) - 1)
                e_line = req.get("end_line", s_line + 100)
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    all_lines = fh.readlines()
                accumulated += "\n\n" + "".join(all_lines[s_line:min(len(all_lines), e_line)])[:BUDGET // 2]

        structure_txt = "\n".join(structure) if structure else "(no structure extracted)"
        out = (
            f"[File: {basename} | Type: {file_meta.get('type', ext)} | Size: {file_size:,} bytes]\n\n"
            f"STRUCTURE:\n{structure_txt}\n\nSUMMARY:\n{summary}"
        )
        return ToolCallResult(tool_id="", tool_name="fs_get_file_structure_and_summary", result=out[:_FS_MAX_READ_CHARS])

    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_get_file_structure_and_summary", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_get_file_structure_and_summary error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_get_file_structure_and_summary", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_write_file
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_write_file",
    description=(
        "Write content to a file, creating it (and any parent directories) if needed. "
        "Overwrites the file if it already exists. Paths are relative to the project root. "
        "For targeted line-level edits, prefer fs_patch_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path (relative to project root or absolute)."},
            "content": {"type": "string", "description": "Full file content to write."},
        },
        "required": ["path", "content"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_write_file(args: dict, context: ToolContext) -> ToolCallResult:
    """Write (create or overwrite) a file."""
    path = args.get("path", "")
    content = args.get("content", "")
    logger.info("fs_write_file invoked: path=%s, user=%s", path, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_write_file", result="", error="path is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        encoded = content.encode("utf-8")
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return ToolCallResult(
            tool_id="", tool_name="fs_write_file",
            result=json.dumps({"status": "ok", "path": abs_path, "bytes": len(encoded)}),
        )
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_write_file", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_write_file error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_write_file", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_patch_file
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_patch_file",
    description=(
        "Replace a range of lines in a file with new content. "
        "Lines are 1-indexed and inclusive. For example, start_line=3, end_line=5 "
        "replaces lines 3, 4, and 5 with new_content. To insert without removing "
        "any lines use start_line=N+1, end_line=N. To delete lines pass new_content=''."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative to project root or absolute)."},
            "start_line": {"type": "integer", "description": "First line to replace (1-indexed, inclusive)."},
            "end_line": {"type": "integer", "description": "Last line to replace (1-indexed, inclusive)."},
            "new_content": {"type": "string", "description": "Replacement text. May be empty to delete lines."},
        },
        "required": ["path", "start_line", "end_line", "new_content"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_patch_file(args: dict, context: ToolContext) -> ToolCallResult:
    """Replace a range of lines in a file with new content."""
    path = args.get("path", "")
    start_line = int(args.get("start_line", 1))
    end_line = int(args.get("end_line", 1))
    new_content = args.get("new_content", "")
    logger.info("fs_patch_file invoked: path=%s, lines=%d-%d, user=%s", path, start_line, end_line, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_patch_file", result="", error="path is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        if not os.path.isfile(abs_path):
            return ToolCallResult(tool_id="", tool_name="fs_patch_file", result="", error=f"File not found: {path}")
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        total = len(lines)
        s = max(1, start_line) - 1   # 0-indexed
        e = min(end_line, total)      # 0-indexed exclusive end
        if s > total:
            return ToolCallResult(
                tool_id="", tool_name="fs_patch_file", result="",
                error=f"start_line {start_line} exceeds file length {total}.",
            )
        replacement: list = []
        if new_content:
            for chunk in new_content.split("\n"):
                replacement.append(chunk + "\n")
            # If new_content didn't end with \n, strip the spurious trailing newline
            if not new_content.endswith("\n") and replacement:
                replacement[-1] = replacement[-1].rstrip("\n")
        new_lines = lines[:s] + replacement + lines[e:]
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.writelines(new_lines)
        removed = e - s
        added = len(replacement)
        return ToolCallResult(
            tool_id="", tool_name="fs_patch_file",
            result=json.dumps({"status": "ok", "lines_removed": removed, "lines_added": added, "total_lines": len(new_lines)}),
        )
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_patch_file", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_patch_file error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_patch_file", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_list_dir
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_list_dir",
    description=(
        "List the entries in a directory. Returns file names, types (file/dir), sizes, "
        "and modification times. Hidden files and __pycache__ entries are included but labelled."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (relative to project root, default '.')." , "default": "."},
        },
        "required": [],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_list_dir(args: dict, context: ToolContext) -> ToolCallResult:
    """List directory entries with metadata."""
    path = args.get("path", ".")
    logger.info("fs_list_dir invoked: path=%s, user=%s", path, context.user_email)

    try:
        abs_path = _coding_resolve_safe_path(path)
        if not os.path.isdir(abs_path):
            return ToolCallResult(tool_id="", tool_name="fs_list_dir", result="", error=f"Not a directory: {path}")

        entries = []
        for name in sorted(os.listdir(abs_path)):
            full = os.path.join(abs_path, name)
            try:
                stat = os.stat(full)
                entries.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                entries.append({"name": name, "type": "unknown"})

        return ToolCallResult(tool_id="", tool_name="fs_list_dir", result=json.dumps(entries))
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_list_dir", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_list_dir error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_list_dir", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_find_files
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_find_files",
    description=(
        "Find files matching a glob pattern under a base directory. "
        "Common patterns: '*.py', '**/*.json', 'src/**/*.ts'. The search is always recursive."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern relative to base_path."},
            "base_path": {"type": "string", "description": "Directory to search in (relative to project root, default '.').", "default": "."},
            "max_results": {"type": "integer", "description": "Maximum number of paths to return (default 100).", "default": 100},
        },
        "required": ["pattern"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_find_files(args: dict, context: ToolContext) -> ToolCallResult:
    """Find files matching a glob pattern."""
    import glob as _glob
    pattern = args.get("pattern", "")
    base_path = args.get("base_path", ".")
    max_results = int(args.get("max_results", 100))
    logger.info("fs_find_files invoked: pattern=%s, base=%s, user=%s", pattern, base_path, context.user_email)

    if not pattern:
        return ToolCallResult(tool_id="", tool_name="fs_find_files", result="", error="pattern is required.")

    try:
        abs_base = _coding_resolve_safe_path(base_path)
        if not os.path.isdir(abs_base):
            return ToolCallResult(tool_id="", tool_name="fs_find_files", result="", error=f"Not a directory: {base_path}")

        root = os.getcwd()
        full_pattern = os.path.join(abs_base, pattern)
        matches = _glob.glob(full_pattern, recursive=True)

        rel_matches = []
        for m in sorted(matches)[:max_results]:
            try:
                rel_matches.append(os.path.relpath(m, root))
            except ValueError:
                rel_matches.append(m)

        return ToolCallResult(tool_id="", tool_name="fs_find_files", result=json.dumps(rel_matches))
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_find_files", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_find_files error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_find_files", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_grep
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_grep",
    description=(
        "Search file contents for lines matching a regular expression. "
        "Recursively searches all files under path that match include_glob. "
        "Returns matching lines with file path and line number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression to search for."},
            "path": {"type": "string", "description": "File or directory to search (relative to project root, default '.').", "default": "."},
            "include_glob": {"type": "string", "description": "Only search files whose names match this glob (e.g. '*.py').", "default": "*"},
            "case_sensitive": {"type": "boolean", "description": "Whether to match case-sensitively (default true).", "default": True},
            "max_results": {"type": "integer", "description": "Maximum number of matching lines to return (default 100).", "default": 100},
        },
        "required": ["pattern"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_grep(args: dict, context: ToolContext) -> ToolCallResult:
    """Search file contents by regex."""
    import re as _re
    import fnmatch as _fnmatch
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    include_glob = args.get("include_glob", "*")
    case_sensitive = args.get("case_sensitive", True)
    max_results = int(args.get("max_results", 100))
    logger.info("fs_grep invoked: pattern=%s, path=%s, user=%s", pattern, path, context.user_email)

    if not pattern:
        return ToolCallResult(tool_id="", tool_name="fs_grep", result="", error="pattern is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        flags = 0 if case_sensitive else _re.IGNORECASE
        compiled = _re.compile(pattern, flags)
    except _re.error as re_err:
        return ToolCallResult(tool_id="", tool_name="fs_grep", result="", error=f"Invalid regex: {re_err}")
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_grep", result="", error=str(ve))

    try:
        root = os.getcwd()
        results = []

        def _search_file(file_path: str) -> None:
            if len(results) >= max_results:
                return
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if compiled.search(line):
                            results.append({
                                "file": os.path.relpath(file_path, root),
                                "line_number": lineno,
                                "line": line.rstrip("\n"),
                            })
                            if len(results) >= max_results:
                                return
            except (OSError, UnicodeDecodeError):
                pass

        if os.path.isfile(abs_path):
            _search_file(abs_path)
        elif os.path.isdir(abs_path):
            for dirpath, _dirs, filenames in os.walk(abs_path):
                for fname in sorted(filenames):
                    if _fnmatch.fnmatch(fname, include_glob):
                        _search_file(os.path.join(dirpath, fname))
                    if len(results) >= max_results:
                        break
        else:
            return ToolCallResult(tool_id="", tool_name="fs_grep", result="", error=f"Path not found: {path}")

        return ToolCallResult(tool_id="", tool_name="fs_grep", result=json.dumps(results))
    except Exception as exc:
        logger.exception("fs_grep error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_grep", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_file_info
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_file_info",
    description=(
        "Get metadata about a file or directory path. "
        "Useful for checking existence, type, and size before reading or writing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to inspect (relative to project root or absolute)."},
        },
        "required": ["path"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_file_info(args: dict, context: ToolContext) -> ToolCallResult:
    """Get path metadata (exists, type, size, mtime)."""
    path = args.get("path", "")
    logger.info("fs_file_info invoked: path=%s, user=%s", path, context.user_email)

    if not path:
        return ToolCallResult(tool_id="", tool_name="fs_file_info", result="", error="path is required.")

    try:
        abs_path = _coding_resolve_safe_path(path)
        root = os.getcwd()

        if not os.path.exists(abs_path):
            return ToolCallResult(
                tool_id="", tool_name="fs_file_info",
                result=json.dumps({"exists": False, "abs_path": abs_path, "rel_path": os.path.relpath(abs_path, root)}),
            )

        stat = os.stat(abs_path)
        if os.path.isfile(abs_path):
            ftype = "file"
        elif os.path.isdir(abs_path):
            ftype = "dir"
        else:
            ftype = "other"

        return ToolCallResult(
            tool_id="", tool_name="fs_file_info",
            result=json.dumps({
                "exists": True, "type": ftype, "size_bytes": stat.st_size,
                "modified": stat.st_mtime, "abs_path": abs_path,
                "rel_path": os.path.relpath(abs_path, root),
            }),
        )
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_file_info", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_file_info error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_file_info", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: fs_bash
# ---------------------------------------------------------------------------

@register_tool(
    name="fs_bash",
    description=(
        "Execute a bash shell command in the project directory. "
        "Runs the command in a subprocess with a configurable timeout (max 300s). "
        "Use for: running tests, build commands, git operations, installing packages."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command string to execute (passed to bash -c)."},
            "workdir": {"type": "string", "description": "Working directory (relative to project root, default '.').", "default": "."},
            "timeout": {"type": "integer", "description": "Maximum seconds to wait (default 60, max 300).", "default": 60},
        },
        "required": ["command"],
    },
    is_interactive=False,
    category="coding",
)
def handle_fs_bash(args: dict, context: ToolContext) -> ToolCallResult:
    """Execute a bash shell command in the project directory."""
    import subprocess
    command = args.get("command", "")
    workdir = args.get("workdir", ".")
    timeout = int(args.get("timeout", 60))
    logger.info("fs_bash invoked: command=%s, workdir=%s, user=%s", command[:100], workdir, context.user_email)

    if not command:
        return ToolCallResult(tool_id="", tool_name="fs_bash", result="", error="command is required.")

    try:
        abs_workdir = _coding_resolve_safe_path(workdir)
        if not os.path.isdir(abs_workdir):
            return ToolCallResult(tool_id="", tool_name="fs_bash", result="", error=f"workdir not a directory: {workdir}")
        effective_timeout = min(max(1, timeout), 300)
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=abs_workdir,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        if len(stdout) > 50_000:
            stdout = stdout[:50_000] + "\n... [stdout truncated]"
        if len(stderr) > 10_000:
            stderr = stderr[:10_000] + "\n... [stderr truncated]"
        return ToolCallResult(
            tool_id="", tool_name="fs_bash",
            result=json.dumps({"exit_code": proc.returncode, "success": proc.returncode == 0, "stdout": stdout, "stderr": stderr}),
        )
    except subprocess.TimeoutExpired:
        return ToolCallResult(
            tool_id="", tool_name="fs_bash",
            result=json.dumps({"exit_code": -1, "success": False, "error": f"Command timed out after {timeout}s.", "stdout": "", "stderr": ""}),
        )
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="fs_bash", result="", error=str(ve))
    except Exception as exc:
        logger.exception("fs_bash error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="fs_bash", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: todo_write
# ---------------------------------------------------------------------------

@register_tool(
    name="todo_write",
    description=(
        "Write (replace) the todo list. Stores a structured task list as JSON. "
        "Each task should be an object with at least a 'content' field. "
        "Recommended fields: content, status (pending/in_progress/completed/cancelled), "
        "priority (high/medium/low), id (auto-assigned if missing)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "todos": {"type": "string", "description": "JSON string — an array of task objects."},
            "scope": {"type": "string", "description": "'global' (default) or 'conversation'.", "default": "global"},
            "conversation_id": {"type": "string", "description": "Required when scope='conversation'.", "default": ""},
        },
        "required": ["todos"],
    },
    is_interactive=False,
    category="coding",
)
def handle_todo_write(args: dict, context: ToolContext) -> ToolCallResult:
    """Write/replace the todo list (global or per-conversation)."""
    todos_str = args.get("todos", "")
    scope = args.get("scope", "global")
    conversation_id = args.get("conversation_id", "") or context.conversation_id
    logger.info("todo_write invoked: scope=%s, user=%s", scope, context.user_email)

    if not todos_str:
        return ToolCallResult(tool_id="", tool_name="todo_write", result="", error="todos is required.")

    try:
        parsed = json.loads(todos_str)
        if not isinstance(parsed, list):
            return ToolCallResult(tool_id="", tool_name="todo_write", result="", error="'todos' must be a JSON array.")

        # Auto-assign IDs if missing
        for i, task in enumerate(parsed):
            if isinstance(task, dict) and "id" not in task:
                task["id"] = str(i + 1)

        todo_file = _coding_todo_path(scope, conversation_id)
        os.makedirs(os.path.dirname(todo_file), exist_ok=True)

        with open(todo_file, "w", encoding="utf-8") as fh:
            json.dump(parsed, fh, indent=2)

        return ToolCallResult(
            tool_id="", tool_name="todo_write",
            result=json.dumps({"status": "ok", "count": len(parsed), "path": todo_file}),
        )
    except json.JSONDecodeError as je:
        return ToolCallResult(tool_id="", tool_name="todo_write", result="", error=f"Invalid JSON in todos: {je}")
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="todo_write", result="", error=str(ve))
    except Exception as exc:
        logger.exception("todo_write error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="todo_write", result="", error=str(exc))


# ---------------------------------------------------------------------------
# Tool: todo_read
# ---------------------------------------------------------------------------

@register_tool(
    name="todo_read",
    description=(
        "Read the current todo list. Returns the JSON array of task objects, "
        "or an empty list if no todo list has been created yet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "'global' (default) or 'conversation'.", "default": "global"},
            "conversation_id": {"type": "string", "description": "Required when scope='conversation'.", "default": ""},
        },
        "required": [],
    },
    is_interactive=False,
    category="coding",
)
def handle_todo_read(args: dict, context: ToolContext) -> ToolCallResult:
    """Read the current todo list."""
    scope = args.get("scope", "global")
    conversation_id = args.get("conversation_id", "") or context.conversation_id
    logger.info("todo_read invoked: scope=%s, user=%s", scope, context.user_email)

    try:
        todo_file = _coding_todo_path(scope, conversation_id)

        if not os.path.isfile(todo_file):
            return ToolCallResult(
                tool_id="", tool_name="todo_read",
                result=json.dumps({"todos": [], "message": "No todo list found."}),
            )

        with open(todo_file, "r", encoding="utf-8") as fh:
            todos = json.load(fh)

        return ToolCallResult(tool_id="", tool_name="todo_read", result=json.dumps(todos))
    except ValueError as ve:
        return ToolCallResult(tool_id="", tool_name="todo_read", result="", error=str(ve))
    except Exception as exc:
        logger.exception("todo_read error: %s", exc)
        return ToolCallResult(tool_id="", tool_name="todo_read", result="", error=str(exc))



# ===========================================================================
# Aggregator tools — delegate_task
# ===========================================================================

from code_common.agent_tool import (
    AGENT_TOOLS as _AGENT_TOOLS,
    _agent_tool_kwargs,
    run_agent_loop,
    start_background_agent,
    get_background_task_result,
    list_all_background_tasks,
)


@register_tool(**_agent_tool_kwargs("delegate_task"))
def handle_delegate_task(args: dict, context: ToolContext) -> ToolCallResult:
    """Delegate a sub-task to an autonomous agent with its own tool access."""
    prompt = args.get("prompt", "")
    profile = args.get("profile", "general")

    if not prompt:
        return ToolCallResult(
            tool_id="", tool_name="delegate_task",
            error="Missing required parameter: prompt",
            result="",
        )

    if profile not in ("research", "documents", "general"):
        return ToolCallResult(
            tool_id="", tool_name="delegate_task",
            error=f"Invalid profile: {profile}. Must be 'research', 'documents', or 'general'.",
            result="",
        )

    try:
        result_text = run_agent_loop(prompt, profile, context, depth=1)
        return ToolCallResult(
            tool_id="", tool_name="delegate_task",
            result=_truncate_result(result_text),
        )
    except Exception as exc:
        logger.exception("delegate_task error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="delegate_task",
            error=f"Agent execution failed: {exc}",
            result="",
        )


# ===========================================================================
# delegate_task_background — fire-and-forget sub-agent
# ===========================================================================


@register_tool(**_agent_tool_kwargs("delegate_task_background"))
def handle_delegate_task_background(args: dict, context: ToolContext) -> ToolCallResult:
    """Start a sub-agent in a background thread; return task_id immediately.

    The sub-agent receives full access to all tools in the chosen profile
    (fs_*, run_python_code, web search, document query, MCP tools, etc.).
    Use get_task_result(task_id=...) to poll and list_background_tasks() to
    enumerate all active/completed tasks in this server session.
    """
    prompt = args.get("prompt", "")
    profile = args.get("profile", "general")
    if not prompt:
        return ToolCallResult(
            tool_id="", tool_name="delegate_task_background",
            error="Missing required parameter: prompt", result="",
        )
    if profile not in ("research", "documents", "general"):
        return ToolCallResult(
            tool_id="", tool_name="delegate_task_background",
            error=f"Invalid profile '{profile}'. Must be 'research', 'documents', or 'general'.",
            result="",
        )
    try:
        task_id = start_background_agent(prompt, profile, context)
        return ToolCallResult(
            tool_id="", tool_name="delegate_task_background",
            result=json.dumps({
                "task_id": task_id,
                "status": "running",
                "message": (
                    "Sub-agent started in background. "
                    "Call get_task_result(task_id='{task_id}') to check progress. "
                    "Call list_background_tasks() to see all tasks."
                ).format(task_id=task_id),
            }),
        )
    except Exception as exc:
        logger.exception("delegate_task_background error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="delegate_task_background",
            error=f"Failed to start background agent: {exc}", result="",
        )


# ===========================================================================
# get_task_result — poll a background task by task_id
# ===========================================================================


@register_tool(**_agent_tool_kwargs("get_task_result"))
def handle_get_task_result(args: dict, context: ToolContext) -> ToolCallResult:
    """Poll a background task by task_id. Returns status + full result when done.

    Status values:
      'running'   — sub-agent still working
      'done'      — completed successfully; 'result' contains the full answer
      'error'     — sub-agent failed; 'result' contains the error message
      'not_found' — no task with this id (wrong id or never started)
      'expired'   — task older than 30 min; result purged from memory
    """
    task_id = args.get("task_id", "")
    if not task_id:
        return ToolCallResult(
            tool_id="", tool_name="get_task_result",
            error="Missing required parameter: task_id", result="",
        )
    task = get_background_task_result(task_id)
    return ToolCallResult(
        tool_id="", tool_name="get_task_result",
        result=json.dumps(task),
    )


# ===========================================================================
# list_background_tasks — enumerate all tasks in this server session
# ===========================================================================


@register_tool(**_agent_tool_kwargs("list_background_tasks"))
def handle_list_background_tasks(args: dict, context: ToolContext) -> ToolCallResult:
    """List all background tasks (running, done, error) with status and result preview.

    Expired tasks (>30 min) are pruned lazily during this call.
    Use status_filter to narrow results: 'running', 'done', 'error', or 'all' (default).
    """
    status_filter = args.get("status_filter", "all")
    tasks = list_all_background_tasks(status_filter=status_filter)
    if not tasks:
        suffix = f" with status='{status_filter}'" if status_filter != "all" else ""
        return ToolCallResult(
            tool_id="", tool_name="list_background_tasks",
            result=f"No background tasks found{suffix}.",
        )
    return ToolCallResult(
        tool_id="", tool_name="list_background_tasks",
        result=json.dumps(tasks, indent=2),
    )


# ---------------------------------------------------------------------------
# Internal search via a local user-provided script — host-gated tool
# ---------------------------------------------------------------------------
#
# This tool shells out to a local script (default ~/.local/bin/internal-search,
# override via INTERNAL_SEARCH_SCRIPT_PATH) that runs LLM queries against a
# company-internal knowledge system (typically over SSH from an authorized
# host). Registration is GATED on the script existing and being executable, so
# the tool is simply absent (all modes, menus, request_tools) on other hosts.
# Script contract: invoked as `script -t <timeout_seconds> <query>...`, runs
# the queries in parallel, prints labeled per-query answers to stdout.

INTERNAL_SEARCH_SCRIPT_PATH = os.environ.get(
    "INTERNAL_SEARCH_SCRIPT_PATH",
    os.path.expanduser("~/.local/bin/internal-search"),
)

_USE_CKT_INTERNAL_TOOLS = bool(os.environ.get("INTERNAL_TOOLS_PATH", "").strip())

INTERNAL_SEARCH_AVAILABLE = (
    not _USE_CKT_INTERNAL_TOOLS
    and os.environ.get("INTERNAL_SEARCH_DISABLED", "").strip().lower()
    not in ("1", "true", "yes")
    and os.path.isfile(INTERNAL_SEARCH_SCRIPT_PATH)
    and os.access(INTERNAL_SEARCH_SCRIPT_PATH, os.X_OK)
)

# Local internal knowledge base (L2 cache of previous internal search
# results). Separate script from internal-search, same host-gating pattern:
# the tool only exists where the script does. It rides in the same tool
# group as internal_search/read_internal_page everywhere they are wired.
INTERNAL_KB_SCRIPT_PATH = os.environ.get(
    "INTERNAL_KB_SCRIPT_PATH",
    os.path.expanduser("~/.local/bin/internal-kb"),
)

INTERNAL_KB_AVAILABLE = (
    not _USE_CKT_INTERNAL_TOOLS
    and os.environ.get("INTERNAL_KB_DISABLED", "").strip().lower()
    not in ("1", "true", "yes")
    and os.path.isfile(INTERNAL_KB_SCRIPT_PATH)
    and os.access(INTERNAL_KB_SCRIPT_PATH, os.X_OK)
)

_INTERNAL_SEARCH_DESCRIPTION = (
    "Search company-internal systems, docs, and knowledge via an "
    "internal AI assistant. This is the ONLY way to get information about "
    "internal/proprietary systems — external web search will not have it.\n\n"
    + (
        "SPEED TIP — CHECK THE LOCAL CACHE FIRST: call "
        "`search_local_internal_kb` before this tool. It is a local, "
        "sub-second BM25 cache of previously-fetched internal answers/pages "
        "— a hit saves the 30-90s+ this tool costs per query. Only reach "
        "for THIS tool (internal_search) when the local KB has nothing "
        "cached, or its results are empty, thin, off-topic, or too stale "
        "for the question at hand.\n\n"
        if INTERNAL_KB_AVAILABLE else ""
    )
    + "KNOWN LIMITATIONS (work around them actively):\n"
    "- Each query is a slow one-shot call (~30-90s, sometimes minutes) to an "
    "internal AI that often SKIMPS on detail and does little background work "
    "on its own.\n"
    "- Answers may be based on stale/outdated internal pages.\n\n"
    "HOW TO USE WELL:\n"
    "- Decompose the user's question into 2-5 focused, differently-angled "
    "queries and pass them ALL in one call via `queries` — they execute in "
    "parallel on the remote side, so 5 queries cost about the same wall time "
    "as 1.\n"
    "- You may ALSO issue several internal_search tool calls in the SAME "
    "response (they run in parallel too) and invoke the tool again across "
    "multiple rounds — there is no call budget; more coverage beats fewer "
    "calls.\n"
    "- Make each query self-contained and specific (the internal AI has no "
    "conversation context): include system names, acronyms expanded, and "
    "explicitly ask for details, links, caveats, and recency.\n"
    "MANDATORY MULTI-ROUND WORKFLOW (do this BEFORE answering the user):\n"
    "1. RECON ROUND: fire your first batch of queries to map the topic.\n"
    "2. SELF-CRITIQUE against this quality bar: 'Would this answer satisfy a "
    "STAFF-LEVEL senior engineer ramping up to contribute in this area — does "
    "it cover architecture and design rationale, key components and their "
    "interactions, configuration/APIs, operational concerns (failure modes, "
    "monitoring, capacity), team/doc/code pointers, and current best "
    "practice?' First-round answers almost NEVER meet this bar.\n"
    "3. DEEPENING ROUND(S): ask yourself 'what other queries would an expert "
    "fire to fill the gaps?' and fire them — drill into each thin area, "
    "verify surprising claims, chase named systems/docs that appeared in "
    "round 1.\n"
    "4. Only then synthesize: a complete, expert-depth answer with explicit "
    "notes on remaining gaps or possibly-stale information.\n"
    "Do NOT stop after one round unless the results already meet the bar "
    "(rare). The user should get the deep, multi-round-quality answer on the "
    "FIRST response, without having to ask you to dig further.\n"
    "- Prefer this tool over web_search/perplexity_search for anything about "
    "internal systems, infra, tooling, or processes."
)

# Compact one-paragraph version of the internal_search guidance, for the
# short quick-action surfaces (doubt clearing, temporary LLM actions) whose
# system prompts must stay small. It carries the same essentials: multi-round
# workflow, parallel decomposition, and the staff-level quality bar.
INTERNAL_SEARCH_WORKFLOW_HINT = (
    "\n\nYou have an `internal_search` tool for company-internal systems, docs, "
    "and knowledge — it is the ONLY source for internal/proprietary info "
    "(external web search will not have it). It is a slow one-shot internal AI "
    "that skimps on detail, so work around that: decompose the question into "
    "2-5 focused, differently-angled queries and pass them ALL in one call via "
    "`queries` (they run in parallel), make each query self-contained and "
    "specific (expand acronyms, name systems, ask for details/links/caveats/"
    "recency), and do a quick recon round then at least one deepening round to "
    "fill gaps before answering — a first-round internal answer rarely meets "
    "the bar a staff-level engineer would expect. Prefer it over web search for "
    "anything internal."
    + (
        " SPEED TIP: check `search_local_internal_kb` (instant local cache) "
        "FIRST — only fall back to internal_search when the cache is empty, "
        "thin, or stale for this question."
        if INTERNAL_KB_AVAILABLE else ""
    )
)


_READ_INTERNAL_PAGE_DESCRIPTION = (
    "Read a specific company-internal web page / doc by URL and return its "
    "content. Use this when you already have an internal URL (an internal "
    "docs/wiki/code/bug link) and want the actual page contents — NOT a "
    "search. It fetches the page through an internal AI acting as a RAG/source "
    "layer: it returns the bulk of the raw extracted information first, then a "
    "short tldr.\n\n"
    "WHEN TO USE:\n"
    "- You have one or more concrete internal URLs to read (e.g. surfaced by "
    "internal_search, or given by the user).\n"
    "- Prefer this over internal_search when the goal is 'read THIS page' "
    "rather than 'find information about a topic'. Use internal_search to "
    "discover pages, then read_internal_page to pull their full detail.\n\n"
    + (
        "SPEED TIP — CHECK THE LOCAL CACHE FIRST: call "
        "`search_local_internal_kb` with the URL (or its topic) before this "
        "tool — if that page was already fetched, the cache returns it "
        "instantly instead of paying another ~30-90s live fetch. Only use "
        "THIS tool when the cache has nothing for that URL, or what it has "
        "is thin/stale for your need.\n\n"
        if INTERNAL_KB_AVAILABLE else ""
    )
    + "NOTES:\n"
    "- Each URL is a slow one-shot fetch (~30-90s); pass MULTIPLE urls in one "
    "call — they are read in parallel remotely, so N urls cost about as much "
    "wall time as 1.\n"
    "- Only works for company-internal URLs reachable from the authorized "
    "host; external web pages should use the normal read_link/jina_read_page "
    "tools.\n"
    "- Content may reflect the current internal page but can still be stale; "
    "note recency caveats when it matters."
)

# Compact guidance for the short quick-action surfaces (doubt clearing,
# temporary LLM actions). Pairs with INTERNAL_SEARCH_WORKFLOW_HINT.
READ_INTERNAL_PAGE_WORKFLOW_HINT = (
    "\n\nYou also have a `read_internal_page` tool: give it one or more "
    "company-internal URLs (in the `urls` array) and it returns the actual "
    "page contents (raw detail first, then a tldr). Use it to READ specific "
    "internal pages you already have links to (including links surfaced by "
    "`internal_search`), rather than to search. Pass multiple URLs in one call "
    "— they are fetched in parallel."
    + (
        " SPEED TIP: check `search_local_internal_kb` for that URL/topic "
        "FIRST — a cache hit is instant; only fetch live if the cache is "
        "empty or stale."
        if INTERNAL_KB_AVAILABLE else ""
    )
)


def handle_read_internal_page(args: dict, context: ToolContext) -> ToolCallResult:
    """Read one or more company-internal pages by URL via the local
    internal-search script's ``--read`` mode.

    Multiple URLs run in parallel remotely (single SSH session), so passing
    several links is roughly as fast as one. Output is labeled per URL. Only
    available when the script exists locally (authorized host); never
    registered on other deployments.

    Parameters
    ----------
    args:
        ``urls`` (list[str] or str, required), ``timeout_seconds`` (int,
        per-URL remote timeout, default 180, clamped 30-600).
    context:
        Tool execution context (unused; the script needs no API keys).

    Returns
    -------
    ToolCallResult
        Labeled per-URL page contents, or an error description.
    """
    import subprocess

    urls = args.get("urls") or args.get("url") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    if not urls:
        return ToolCallResult(
            tool_id="", tool_name="read_internal_page", result="",
            error="urls is required: pass 1-8 non-empty internal URL strings.",
        )
    urls = urls[:8]

    try:
        timeout_s = int(args.get("timeout_seconds", 180) or 180)
    except (TypeError, ValueError):
        timeout_s = 180
    timeout_s = max(30, min(timeout_s, 600))

    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "-t", str(timeout_s), "--read"] + urls
    logger.info(
        "read_internal_page invoked: %d urls, timeout=%ds", len(urls), timeout_s
    )
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s + 120
        )
    except subprocess.TimeoutExpired:
        return ToolCallResult(
            tool_id="", tool_name="read_internal_page", result="",
            error=(
                f"internal page read timed out after {timeout_s + 120}s locally. "
                "The SSH connection may need a fresh auth touch, or the remote "
                "AI is overloaded. Retry with fewer URLs."
            ),
        )
    except FileNotFoundError:
        return ToolCallResult(
            tool_id="", tool_name="read_internal_page", result="",
            error=f"internal search script not found at {INTERNAL_SEARCH_SCRIPT_PATH}.",
        )
    except Exception as exc:  # noqa: BLE001 — handlers must never raise
        return ToolCallResult(
            tool_id="", tool_name="read_internal_page", result="",
            error=f"internal page read failed: {exc}",
        )

    out = (proc.stdout or "").replace("\r", "")
    _noise_prefixes = ("Shared connection to ", "Connection to ")
    text = "\n".join(
        ln for ln in out.splitlines()
        if not ln.strip().startswith(_noise_prefixes)
    ).strip()

    if proc.returncode != 0 and not text:
        stderr_tail = (proc.stderr or "").replace("\r", "").strip()[-2000:]
        return ToolCallResult(
            tool_id="", tool_name="read_internal_page", result="",
            error=(
                f"internal page read script exited with code {proc.returncode} "
                f"and no output. stderr tail: {stderr_tail or '(empty)'}"
            ),
        )
    if not text:
        text = "(internal page read returned no output)"
    if proc.returncode != 0:
        text += (
            f"\n\n[note: internal page read script exit code {proc.returncode} — "
            "one or more URLs may have failed or timed out; see per-URL exit "
            "codes in the headers above]"
        )
    return ToolCallResult(
        tool_id="", tool_name="read_internal_page",
        result=_truncate_result(text),
    )


if INTERNAL_SEARCH_AVAILABLE:
    handle_read_internal_page = register_tool(
        name="read_internal_page",
        description=_READ_INTERNAL_PAGE_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "1-8 company-internal page URLs to read. Pass MULTIPLE "
                        "to read pages in parallel remotely, so N urls take "
                        "about as long as 1."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Per-URL remote timeout in seconds (30-600). "
                        "Default 180."
                    ),
                    "default": 180,
                },
            },
            "required": ["urls"],
        },
        is_interactive=False,
        category="search",
    )(handle_read_internal_page)


def handle_internal_search(args: dict, context: ToolContext) -> ToolCallResult:
    """Run one or more company-internal search queries via the local
    internal-search script.

    Multiple queries run in parallel remotely (single SSH session), so
    passing several focused reformulations is roughly as fast as one.
    Output is labeled per query. Only available when the script exists
    locally (authorized host); never registered on other deployments.

    Parameters
    ----------
    args:
        ``queries`` (list[str] or str, required), ``timeout_seconds``
        (int, per-query remote timeout, default 180, clamped 30-600).
    context:
        Tool execution context (unused; the script needs no API keys).

    Returns
    -------
    ToolCallResult
        Labeled per-query answers, or an error description.
    """
    import subprocess

    queries = args.get("queries") or args.get("query") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    if not queries:
        return ToolCallResult(
            tool_id="", tool_name="internal_search", result="",
            error="queries is required: pass 1-8 non-empty query strings.",
        )
    queries = queries[:8]

    try:
        timeout_s = int(args.get("timeout_seconds", 180) or 180)
    except (TypeError, ValueError):
        timeout_s = 180
    timeout_s = max(30, min(timeout_s, 600))

    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "-t", str(timeout_s)] + queries
    logger.info(
        "internal_search invoked: %d queries, timeout=%ds", len(queries), timeout_s
    )
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s + 120
        )
    except subprocess.TimeoutExpired:
        return ToolCallResult(
            tool_id="", tool_name="internal_search", result="",
            error=(
                f"internal search timed out after {timeout_s + 120}s locally. "
                "The SSH connection may need a fresh auth touch, or the remote "
                "AI is overloaded. Retry with fewer/simpler queries."
            ),
        )
    except FileNotFoundError:
        return ToolCallResult(
            tool_id="", tool_name="internal_search", result="",
            error=f"internal search script not found at {INTERNAL_SEARCH_SCRIPT_PATH}.",
        )
    except Exception as exc:  # noqa: BLE001 — handlers must never raise
        return ToolCallResult(
            tool_id="", tool_name="internal_search", result="",
            error=f"internal search failed: {exc}",
        )

    out = (proc.stdout or "").replace("\r", "")
    # Strip SSH connection-noise lines from -tt sessions.
    _noise_prefixes = ("Shared connection to ", "Connection to ")
    text = "\n".join(
        ln for ln in out.splitlines()
        if not ln.strip().startswith(_noise_prefixes)
    ).strip()

    if proc.returncode != 0 and not text:
        stderr_tail = (proc.stderr or "").replace("\r", "").strip()[-2000:]
        return ToolCallResult(
            tool_id="", tool_name="internal_search", result="",
            error=(
                f"internal search script exited with code {proc.returncode} "
                f"and no output. stderr tail: {stderr_tail or '(empty)'}"
            ),
        )
    if not text:
        text = "(internal search returned no output)"
    if proc.returncode != 0:
        text += (
            f"\n\n[note: internal search script exit code {proc.returncode} — "
            "one or more queries may have failed or timed out; see per-query "
            "exit codes in the headers above]"
        )
    return ToolCallResult(
        tool_id="", tool_name="internal_search",
        result=_truncate_result(text),
    )


if INTERNAL_SEARCH_AVAILABLE:
    handle_internal_search = register_tool(
        name="internal_search",
        description=_INTERNAL_SEARCH_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "1-8 self-contained queries about internal systems. "
                        "Pass MULTIPLE focused reformulations — they run in "
                        "parallel remotely, so 5 queries take about as long "
                        "as 1."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Per-query remote timeout in seconds (30-600). "
                        "Default 180."
                    ),
                    "default": 180,
                },
            },
            "required": ["queries"],
        },
        is_interactive=False,
        category="search",
    )(handle_internal_search)


_SEARCH_LOCAL_INTERNAL_KB_DESCRIPTION = (
    "Search a LOCAL knowledge base of previously-fetched company-internal "
    "answers and pages (BM25 full-text over cached internal_search / "
    "read_internal_page results). It is nearly INSTANT (<1s, no network, no "
    "remote AI) — so it is the CHEAPEST first probe for any company-internal "
    "question.\n\n"
    "INTENTION:\n"
    "- Use this FIRST, before internal_search/read_internal_page, on any "
    "internal topic — if the KB already holds the answer you save 30-90s per "
    "query.\n"
    "- Also use it to recall internal facts looked up in past sessions.\n\n"
    "LIMITATIONS (judge results critically):\n"
    "- It only contains what was previously fetched on this machine — "
    "coverage is sparse and topic-dependent; absence of results means "
    "'not cached', NOT 'does not exist internally'.\n"
    "- Content can be up to ~30 days old (entries expire) and may be stale "
    "relative to the live internal page.\n"
    "- It is keyword (BM25) retrieval over text chunks, not an AI answer: "
    "results are raw excerpts that may only partially match your need.\n\n"
    "FALLBACK RULE (mandatory): after calling this tool, assess whether the "
    "returned chunks actually and sufficiently answer the question with "
    "adequate freshness. If results are empty, off-topic, too thin, or "
    "possibly stale for a recency-sensitive question, you MUST fall back to "
    "the live tools in the same turn: internal_search (find information on "
    "the topic) and/or read_internal_page (a KB hit often names the source "
    "URL — re-read it live for current full detail). Never present KB-only "
    "results as complete when they are marginal; say what came from cache "
    "and deepen with live search.\n\n"
    "USAGE:\n"
    "- Pass 1-8 short keyword-style queries in `queries` (distinct angles / "
    "synonyms / system names) — local and fast, so probing broadly is free.\n"
    "- Each result chunk is headed by "
    "'===== [score] (age d old) from: <source query or URL>' — lower "
    "(more negative) score = better match; use the age and source to judge "
    "staleness and to pick URLs for read_internal_page."
)

# Compact guidance for the short quick-action surfaces (doubt clearing,
# temporary LLM actions). Pairs with the other two internal hints.
SEARCH_LOCAL_INTERNAL_KB_WORKFLOW_HINT = (
    "\n\nYou also have a `search_local_internal_kb` tool: an instant (<1s) "
    "local cache of previously-fetched internal answers. On internal topics "
    "probe it FIRST with a few keyword queries; but it only holds what was "
    "fetched before (possibly up to 30 days stale), so if results are empty, "
    "thin, or off-topic you MUST fall back to `internal_search` / "
    "`read_internal_page` for live answers instead of stopping."
)


def handle_search_local_internal_kb(args: dict, context: ToolContext) -> ToolCallResult:
    """Search the local internal knowledge base (cached internal answers).

    Runs the local ``internal-kb search`` script once per query. Purely
    local SQLite FTS5/BM25 lookup — no network, sub-second. Only available
    when the script exists locally (authorized host); never registered on
    other deployments.

    Parameters
    ----------
    args:
        ``queries`` (list[str] or str, required), ``max_results_per_query``
        (int, default 5, clamped 1-10), ``full`` (bool, default False —
        return full chunks instead of 1200-char truncated ones).
    context:
        Tool execution context (unused; the script needs no API keys).

    Returns
    -------
    ToolCallResult
        Labeled per-query result chunks, or an error description.
    """
    import subprocess

    queries = args.get("queries") or args.get("query") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    if not queries:
        return ToolCallResult(
            tool_id="", tool_name="search_local_internal_kb", result="",
            error="queries is required: pass 1-8 non-empty query strings.",
        )
    queries = queries[:8]

    try:
        n = int(args.get("max_results_per_query", 5) or 5)
    except (TypeError, ValueError):
        n = 5
    n = max(1, min(n, 10))
    full = bool(args.get("full", False))

    logger.info(
        "search_local_internal_kb invoked: %d queries, n=%d, full=%s",
        len(queries), n, full,
    )

    sections = []
    any_hits = False
    for q in queries:
        cmd = [INTERNAL_KB_SCRIPT_PATH, "search", "-n", str(n)]
        if full:
            cmd.append("--full")
        cmd.append(q)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            sections.append(f"## KB query: {q}\n(local KB search timed out)")
            continue
        except FileNotFoundError:
            return ToolCallResult(
                tool_id="", tool_name="search_local_internal_kb", result="",
                error=f"internal KB script not found at {INTERNAL_KB_SCRIPT_PATH}.",
            )
        except Exception as exc:  # noqa: BLE001 — handlers must never raise
            sections.append(f"## KB query: {q}\n(local KB search failed: {exc})")
            continue
        out = (proc.stdout or "").strip()
        # internal-kb exits 1 with "no results" on stdout for a clean miss —
        # treat that as a miss, not an error.
        is_miss = not out or out.lower().splitlines()[0].startswith("no results")
        if proc.returncode != 0 and not is_miss:
            err_tail = (proc.stderr or "").strip()[-500:]
            sections.append(
                f"## KB query: {q}\n(local KB search exited with code "
                f"{proc.returncode}: {err_tail or '(no stderr)'})"
            )
            continue
        if is_miss:
            sections.append(f"## KB query: {q}\n(no cached results)")
            continue
        any_hits = True
        sections.append(f"## KB query: {q}\n{out}")

    text = "\n\n".join(sections)
    if not any_hits:
        text += (
            "\n\n[The local KB has NOTHING cached for these queries. This does "
            "NOT mean the information doesn't exist internally — fall back to "
            "internal_search (and read_internal_page for known URLs) NOW.]"
        )
    else:
        text += (
            "\n\n[Reminder: these are CACHED excerpts (possibly up to ~30 days "
            "old, possibly partial). If they don't fully and freshly answer "
            "the question, deepen with internal_search / read_internal_page "
            "before answering.]"
        )
    return ToolCallResult(
        tool_id="", tool_name="search_local_internal_kb",
        result=_truncate_result(text),
    )


if INTERNAL_KB_AVAILABLE:
    handle_search_local_internal_kb = register_tool(
        name="search_local_internal_kb",
        description=_SEARCH_LOCAL_INTERNAL_KB_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "1-8 short keyword-style queries (distinct angles, "
                        "synonyms, system names). Local and instant, so "
                        "probing broadly costs nothing."
                    ),
                },
                "max_results_per_query": {
                    "type": "integer",
                    "description": "Result chunks per query (1-10). Default 5.",
                    "default": 5,
                },
                "full": {
                    "type": "boolean",
                    "description": (
                        "Return full untruncated chunks instead of "
                        "1200-char previews. Default false."
                    ),
                    "default": False,
                },
            },
            "required": ["queries"],
        },
        is_interactive=False,
        category="search",
    )(handle_search_local_internal_kb)


# ---------------------------------------------------------------------------
# Typed fast-path internal tools (moma/yaqs/bug/code/code-search) + ask_internal_kb —
# host-gated the same way as internal_search (they all shell out to the SAME
# jetski-query script, just with its typed --moma/--who/--team/--yaqs/--bug/
# --code/--code-search flags instead of the general agentic query path).
# ask_internal_kb additionally needs INTERNAL_KB_AVAILABLE since it calls
# `internal-kb ask`.
#
# These are DIRECT, NON-AGENTIC binary calls on the remote host (~1-3s, no
# LLM round trip) except search_code (itself an LLM agent, comparable
# latency to internal_search) and ask_internal_kb (usually fast, sometimes
# escalates to one live agentic call). Unlike internal_search/
# read_internal_page, the fast-tier tools (search_moma/search_yaqs/get_bug/
# search_code_standard) have NO agentic fallback on failure inside the
# script — a miss/error means the calling model must itself fall back to
# internal_search, not that this tool will retry more broadly.
# ---------------------------------------------------------------------------

_FASTPATH_NO_FALLBACK_NOTE = (
    "\n\nNO AGENTIC FALLBACK ON FAILURE: this is a direct, deterministic "
    "lookup with no broader search behind it. If it returns nothing, an "
    "error, or an unhelpful result, you MUST fall back to `internal_search` "
    "yourself in the same turn — this tool will not retry or broaden the "
    "query on its own."
)

_SEARCH_MOMA_DESCRIPTION = (
    "Direct lookup in Moma (Google's internal docs/people/teams directory) "
    "— NOT an LLM call, ~1-3s, much faster than internal_search for this "
    "specific kind of lookup.\n\n"
    "MODES:\n"
    "- `who`: look up a specific person by username (team, role, manager).\n"
    "- `team`: find a team by name (members, description).\n"
    "- `search`: semantic doc/topic search over Moma (the general case — use "
    "this when you don't have a specific username or exact team name)."
    + _FASTPATH_NO_FALLBACK_NOTE
)

_SEARCH_YAQS_DESCRIPTION = (
    "Direct search of YAQS (Google's internal Stack-Overflow-equivalent Q&A "
    "site) — NOT an LLM call, ~1-3s. Good for known technical blockers, "
    "error messages, or 'has anyone hit this before' questions other "
    "engineers have already answered."
    + _FASTPATH_NO_FALLBACK_NOTE
)

_GET_BUG_DESCRIPTION = (
    "Fetch a SPECIFIC Buganizer bug by its numeric ID — NOT an LLM call, "
    "~1-3s. Use only when you already have a concrete bug ID (given by the "
    "user, or surfaced by another tool/search result) and want its current "
    "title/status/description/comments. This is NOT for searching bugs by "
    "topic or keyword — that still requires `internal_search`.\n\n"
    "FRESHNESS NOTE: bug status/comments change often; a cached "
    "`search_local_internal_kb` hit for a bug may be more stale than for "
    "other content (bugs use a shorter 3-day local-KB TTL) — prefer this "
    "live tool over a cached KB hit when currency actually matters (e.g. "
    "'is this still open')."
    + _FASTPATH_NO_FALLBACK_NOTE
)

_SEARCH_CODE_DESCRIPTION = (
    "Ask a codebase question via the internal CodeSearch agent — an LLM "
    "that reads real code and synthesizes an answer. Typically ~6-15s+, "
    "SLOWER than search_moma/search_yaqs/get_bug and comparable in latency "
    "to a single internal_search query — it is itself an agent, not a "
    "deterministic lookup. Use it for 'how does X work in the code' / "
    "'where is Y implemented' questions; narrower and more precise for code "
    "than internal_search, which has no direct code access. Pass `dir` to "
    "scope the search to a known subpackage/path.\n\n"
    "DIFFERENT FALLBACK BEHAVIOR THAN THE OTHER FAST-PATH TOOLS: an empty or "
    "thin result here does NOT necessarily mean escalate to internal_search "
    "— internal_search has no code access either. If you have a specific "
    "file or CS (code search) link, prefer `read_internal_page` on it "
    "instead; only use internal_search for non-code context around the "
    "question.\n\n"
    "PREFER `search_code_standard` FIRST when the question names a specific "
    "symbol/function/string you already know — it's a deterministic ~1-3s "
    "regex search (no LLM), faster and more precise than this agent for "
    "that case. Reach for this tool only when you need synthesis/reasoning "
    "across multiple files rather than a raw pattern match."
)

_SEARCH_CODE_STANDARD_DESCRIPTION = (
    "Standard, regex-indexed Code Search (the internal `cs`/CodeSearch CLI, "
    "see http://go/cs-reference) — NOT an LLM call, ~1-3s, deterministic. "
    "Use when you already know roughly what you're looking for (an exact "
    "symbol, function name, string literal, or regex pattern) and want fast, "
    "precise, non-paraphrased matches with file:line locations. Query syntax "
    "uses filters like `f:<path-regex>` (filename), `c:\"literal\"` (content), "
    "`func:name`/`class:name`/`symbol:name` (definitions), `lang:python`, "
    "`within:comment`, `-f:third_party` (exclude), combinable (implicit AND). "
    "Pass `dir` to additionally scope results to a known subpackage/path.\n\n"
    "PREFER `search_code` (the CodeSearch AGENT) INSTEAD when the question is "
    "conceptual/reasoning-shaped ('how does X work', 'explain the flow of Y') "
    "rather than 'find this specific thing' — that tool reads and synthesizes "
    "across files instead of returning raw regex matches."
    + _FASTPATH_NO_FALLBACK_NOTE
)

_ASK_INTERNAL_KB_DESCRIPTION = (
    "Ask ONE focused internal-knowledge question with automatic KB-first, "
    "live-fallback-if-needed behavior in a single call. Checks the local "
    "cache (like `search_local_internal_kb`); if the best cached match is "
    "good enough (by BM25 score) it returns instantly, otherwise it "
    "automatically fires ONE live internal_search-style query and caches "
    "the fresh answer for next time.\n\n"
    "RESULT IS TIER-LABELED — read the tier before trusting the answer:\n"
    "- `[TIER: cache-hit ...]` — answered from the local cache; still "
    "subject to the same staleness caveats as `search_local_internal_kb`.\n"
    "- `[TIER: live-single-shot ...]` — the cache was a poor match, so this "
    "tool escalated automatically. IMPORTANT: a single live query is NOT "
    "the same as internal_search's mandatory multi-round decompose + "
    "self-critique + deepen workflow. Treat a live-single-shot result as a "
    "first-round answer ONLY.\n\n"
    "MANDATORY FALLBACK RULE: use this tool for narrow, single-fact lookups "
    "where one focused query is plausibly sufficient (e.g. 'what does "
    "system X do', 'who owns team Y'). For genuinely broad, multi-faceted, "
    "or architecture-level questions that you already know need "
    "decomposition, call `internal_search` directly instead — don't waste a "
    "round trip through this tool first. And regardless of this tool's "
    "tier, if the returned answer is thin, hedged ('no information found', "
    "'unclear'), or the question is recency-sensitive and the tier is "
    "cache-hit with a stale timestamp, you MUST still follow up with "
    "`internal_search` before treating the answer as final."
)

# Compact one-line-per-tool guidance for the short quick-action surfaces
# (doubt clearing, temporary LLM actions), same pattern as
# INTERNAL_SEARCH_WORKFLOW_HINT / READ_INTERNAL_PAGE_WORKFLOW_HINT /
# SEARCH_LOCAL_INTERNAL_KB_WORKFLOW_HINT above.
FASTPATH_TOOLS_WORKFLOW_HINT = (
    "\n\nYou also have typed fast-path internal tools: `search_moma` (Moma "
    "docs/people/teams — pass mode search/who/team), `search_yaqs` "
    "(internal Q&A site), `get_bug` (a specific numeric Buganizer bug "
    "ID), and `search_code_standard` (a specific known symbol/string/pattern "
    "in code — regex-indexed CodeSearch, go/cs-reference filter syntax: "
    "f:/c:/func:/class:/symbol:/lang:/within:) — each ~1-3s, no LLM call, "
    "with NO fallback on failure (if one misses, fall back to "
    "`internal_search` yourself). `search_code` is "
    "different: it IS an LLM agent (CodeSearch), latency comparable to "
    "internal_search, for 'how does X work in the code' reasoning-shaped "
    "questions — an "
    "empty result there does not automatically mean escalate to "
    "internal_search (no code access there either); prefer "
    "`read_internal_page` on a known file/CS link instead, or "
    "`search_code_standard` first if you already know the specific "
    "symbol/string to find."
)

ASK_INTERNAL_KB_WORKFLOW_HINT = (
    "\n\nYou also have an `ask_internal_kb` tool: one call, KB-first then "
    "automatic live-fallback for a SINGLE focused internal question. Its "
    "result is TIER-labeled ('cache-hit' vs 'live-single-shot'); treat "
    "'live-single-shot' as a first-round answer only, NOT the same depth as "
    "internal_search's multi-round workflow — for broad/multi-faceted "
    "questions call `internal_search` directly instead."
)


def build_internal_tool_routing_hint(tool_names: list) -> str:
    """Build a consolidated internal-tool routing decision tree for the system
    prompt, including per-tool latency and a recommended ordering.

    Only includes tools that are actually present in *tool_names*. Returns an
    empty string when no internal tools are enabled (so callers can
    unconditionally append the result without polluting the prompt on hosts
    where the internal toolset is absent).

    Parameters
    ----------
    tool_names:
        List of enabled tool names (as used by ``get_openai_tools_param`` /
        ``_get_enabled_tools``).

    Returns
    -------
    str
        A markdown block describing the routing decision tree, or ``""`` when
        no internal tools are in *tool_names*.
    """
    # Map canonical tool name -> whether it's enabled.
    present = {name: name in tool_names for name in (
        "search_local_internal_kb",
        "ask_internal_kb",
        "search_moma",
        "search_yaqs",
        "get_bug",
        "search_code",
        "search_code_standard",
        "internal_search",
        "read_internal_page",
    )}
    if not any(present.values()):
        return ""

    lines = [
        "",
        "### Internal Tool Routing (follow this order for any company-internal question)",
        "",
        "Pick the FIRST entry whose shape matches the question. Do not skip "
        "ahead unless the earlier tools have nothing or returned thin/stale "
        "results — cheaper tiers are almost free and a hit saves 30-90s+.",
        "",
    ]

    # Sequential numbering — only present tools get a slot, no gaps.
    tier = [0]  # mutable counter for closure-free increment

    def _num() -> str:
        tier[0] += 1
        return str(tier[0])

    # Tier 1: local KB search (cheapest)
    if present["search_local_internal_kb"]:
        lines.append(
            f"{_num()}. **search_local_internal_kb** — <1s, local only, no network. "
            "ALWAYS the first probe for any internal question. Pass 1-8 "
            "keyword-style queries (broad probing is free). Returns raw "
            "cached excerpts; a miss means 'not cached', NOT 'doesn't exist'."
        )

    # Tier 2: ask_internal_kb (KB-first + critic + optional live fallback)
    if present["ask_internal_kb"]:
        lines.append(
            f"{_num()}. **ask_internal_kb** — <1s (cache-hit) or 30-90s "
            "(live-single-shot escalation). ONE narrow single-fact question "
            "only (e.g. 'what does system X do', 'who owns team Y'). An LLM "
            "critic judges the cached match; if insufficient it auto-fires "
            "one live query and caches the answer. Result is TIER-labeled: "
            "'cache-hit' = same staleness caveats as tier 1; 'live-single-"
            "shot' = a first-round answer ONLY. Do NOT use for broad/"
            "multi-faceted questions — skip to internal_search instead."
        )

    # Tier 3: typed fast-path lookups (specific, deterministic, ~1-3s)
    fastpath_lines = []
    if present["search_moma"]:
        fastpath_lines.append(
            "   - **search_moma** — ~1-3s. Moma docs/people/teams (mode: "
            "search/who/team)."
        )
    if present["search_yaqs"]:
        fastpath_lines.append(
            "   - **search_yaqs** — ~1-3s. Internal Q&A site (YAQS)."
        )
    if present["get_bug"]:
        fastpath_lines.append(
            "   - **get_bug** — ~1-3s. A specific numeric Buganizer bug ID."
        )
    if present["search_code_standard"]:
        fastpath_lines.append(
            "   - **search_code_standard** — ~1-3s. Regex-indexed CodeSearch "
            "for a known symbol/string/pattern (go/cs-reference filter "
            "syntax)."
        )
    if present["search_code"]:
        fastpath_lines.append(
            "   - **search_code** — ~6-15s. CodeSearch LLM agent for "
            "'how does X work in the code' reasoning-shaped questions (no "
            "live fallback; if it misses, try read_internal_page on a known "
            "file/CS link)."
        )
    if fastpath_lines:
        lines.append(
            f"{_num()}. **Typed fast paths** — ~1-3s each (search_code is "
            "slower). Use when you have a specific, concrete lookup target:"
        )
        lines.extend(fastpath_lines)
        lines.append(
            "   NO agentic fallback on failure (except search_code) — if one "
            "misses, fall back to internal_search yourself."
        )

    # Tier 4: internal_search (broad, multi-round, slow)
    if present["internal_search"]:
        lines.append(
            f"{_num()}. **internal_search** — 30-90s per round, expect 2+ rounds "
            "(typically 2-5 min total wall time). The ONLY tool for broad, "
            "multi-faceted, or architecture-level internal questions. "
            "Decompose into 2-5 self-contained queries per call (parallel "
            "remotely), self-critique against a staff-engineer quality bar, "
            "then fire deepening rounds. No call budget."
        )

    # Tier 5: read_internal_page (specific URL)
    if present["read_internal_page"]:
        lines.append(
            f"{_num()}. **read_internal_page** — 30-90s per URL (pass multiple URLs "
            "in one call, they fetch in parallel). Use when you ALREADY have "
            "a specific internal URL (surfaced by internal_search, a fast "
            "path, or given by the user) and want its full contents."
        )

    lines.append("")
    lines.append(
        "General rules: always start at the cheapest tier that could answer "
        "the question; escalate downward only when results are empty, thin, "
        "off-topic, or too stale. You MAY issue multiple tool calls in the "
        "same response (they execute in parallel) — e.g. probe "
        "search_local_internal_kb AND fire a search_moma lookup "
        "simultaneously."
    )
    lines.append("")
    return "\n".join(lines)


def _run_fastpath(
    tool_name: str, cmd: list, timeout_s: int = 45
) -> ToolCallResult:
    """Shared subprocess runner for the typed fast-path internal tools.

    All of them are thin wrappers around a single ``jetski-query``/
    ``internal-kb`` invocation with no query-list decomposition, so they
    share one small, consistent error-handling path (timeout / missing
    script / other exception / non-zero exit with no output).

    Parameters
    ----------
    tool_name:
        Name to stamp on the returned ``ToolCallResult`` and use in error
        messages (must match the tool's registered name).
    cmd:
        Full argv list to run via ``subprocess.run``.
    timeout_s:
        Local subprocess timeout in seconds.

    Returns
    -------
    ToolCallResult
        Cleaned stdout on success, or an error description.
    """
    import subprocess

    logger.info("%s invoked: cmd=%s", tool_name, cmd)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result="",
            error=(
                f"{tool_name} timed out after {timeout_s}s locally. Fall "
                "back to internal_search."
            ),
        )
    except FileNotFoundError as exc:
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result="",
            error=f"{tool_name} script not found: {exc}.",
        )
    except Exception as exc:  # noqa: BLE001 — handlers must never raise
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result="",
            error=f"{tool_name} failed: {exc}",
        )

    out = (proc.stdout or "").replace("\r", "")
    _noise_prefixes = ("Shared connection to ", "Connection to ")
    text = "\n".join(
        ln for ln in out.splitlines()
        if not ln.strip().startswith(_noise_prefixes)
    ).strip()

    if proc.returncode != 0 and not text:
        stderr_tail = (proc.stderr or "").replace("\r", "").strip()[-1000:]
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result="",
            error=(
                f"{tool_name} exited with code {proc.returncode} and no "
                f"output. stderr tail: {stderr_tail or '(empty)'}. Fall "
                "back to internal_search."
            ),
        )
    if not text:
        text = f"({tool_name} returned no output)"
    if proc.returncode != 0:
        text += (
            f"\n\n[note: {tool_name} exit code {proc.returncode} — treat as "
            "a miss and consider falling back to internal_search]"
        )
    return ToolCallResult(
        tool_id="", tool_name=tool_name, result=_truncate_result(text),
    )


def handle_search_moma(args: dict, context: ToolContext) -> ToolCallResult:
    """Direct Moma lookup via jetski-query's --moma/--who/--team fast paths.

    Parameters
    ----------
    args:
        ``mode`` ("search" | "who" | "team", required), ``query`` (string,
        required).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Raw Moma lookup output, or an error description.
    """
    mode = str(args.get("mode", "search") or "search").strip().lower()
    query = str(args.get("query", "") or "").strip()
    if not query:
        return ToolCallResult(
            tool_id="", tool_name="search_moma", result="",
            error="query is required.",
        )
    flag_by_mode = {"search": "--moma", "who": "--who", "team": "--team"}
    flag = flag_by_mode.get(mode)
    if not flag:
        return ToolCallResult(
            tool_id="", tool_name="search_moma", result="",
            error=f"invalid mode '{mode}': must be one of search/who/team.",
        )
    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, flag, query]
    return _run_fastpath("search_moma", cmd)


def handle_search_yaqs(args: dict, context: ToolContext) -> ToolCallResult:
    """Direct YAQS search via jetski-query's --yaqs fast path.

    Parameters
    ----------
    args:
        ``query`` (string, required).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Raw YAQS search output, or an error description.
    """
    query = str(args.get("query", "") or "").strip()
    if not query:
        return ToolCallResult(
            tool_id="", tool_name="search_yaqs", result="",
            error="query is required.",
        )
    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "--yaqs", query]
    return _run_fastpath("search_yaqs", cmd)


def handle_get_bug(args: dict, context: ToolContext) -> ToolCallResult:
    """Direct Buganizer bug fetch via jetski-query's --bug fast path.

    Parameters
    ----------
    args:
        ``bug_id`` (string or int, required — numeric bug ID).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Raw bug render output, or an error description.
    """
    import re

    bug_id = str(args.get("bug_id", "") or "").strip()
    if not bug_id:
        return ToolCallResult(
            tool_id="", tool_name="get_bug", result="",
            error="bug_id is required.",
        )
    if not re.match(r"^\d+$", bug_id):
        return ToolCallResult(
            tool_id="", tool_name="get_bug", result="",
            error=(
                f"bug_id must be numeric (got '{bug_id}'). To search bugs "
                "by topic/keyword, use internal_search instead."
            ),
        )
    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "--bug", bug_id]
    return _run_fastpath("get_bug", cmd)


def handle_search_code(args: dict, context: ToolContext) -> ToolCallResult:
    """Codebase question via jetski-query's --code fast path (CodeSearch
    agent — itself LLM-backed, so latency is comparable to internal_search
    rather than the other ~1-3s fast paths).

    Parameters
    ----------
    args:
        ``query`` (string, required), ``dir`` (string, optional — scope to
        a subpackage/path), ``timeout_seconds`` (int, default 60, clamped
        30-300).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Raw CodeSearch agent answer, or an error description.
    """
    query = str(args.get("query", "") or "").strip()
    if not query:
        return ToolCallResult(
            tool_id="", tool_name="search_code", result="",
            error="query is required.",
        )
    directory = str(args.get("dir", "") or "").strip()
    try:
        timeout_s = int(args.get("timeout_seconds", 60) or 60)
    except (TypeError, ValueError):
        timeout_s = 60
    timeout_s = max(30, min(timeout_s, 300))

    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "--code", query]
    if directory:
        cmd += ["--dir", directory]
    return _run_fastpath("search_code", cmd, timeout_s=timeout_s + 30)


def handle_search_code_standard(args: dict, context: ToolContext) -> ToolCallResult:
    """Codebase question via jetski-query's --code-search fast path (standard,
    regex-indexed Code Search — NOT an LLM call, deterministic, ~1-3s).

    Parameters
    ----------
    args:
        ``query`` (string, required — go/cs-reference filter syntax, e.g.
        ``func:calculateTotal`` or ``f:foo\\.py c:"deprecated = true"``),
        ``dir`` (string, optional — scope to a subpackage/path).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Raw Code Search matches (file:line + snippet), or an error
        description.
    """
    query = str(args.get("query", "") or "").strip()
    if not query:
        return ToolCallResult(
            tool_id="", tool_name="search_code_standard", result="",
            error="query is required.",
        )
    directory = str(args.get("dir", "") or "").strip()
    cmd = [INTERNAL_SEARCH_SCRIPT_PATH, "--code-search", query]
    if directory:
        cmd += ["--dir", directory]
    return _run_fastpath("search_code_standard", cmd)


def handle_ask_internal_kb(args: dict, context: ToolContext) -> ToolCallResult:
    """KB-first, live-fallback-if-needed single-question lookup via
    `internal-kb ask`.

    Auto-escalates to one live query when the cached best match is a poor
    fit (BM25 score above the skip-score threshold); the returned text is
    tier-labeled (cache-hit vs live-single-shot) so the calling model can
    judge whether the answer is sufficient or whether a full
    `internal_search` multi-round pass is still warranted.

    Parameters
    ----------
    args:
        ``query`` (string, required — single focused question, not a
        list), ``skip_score`` (float, default -3.0), ``no_live`` (bool,
        default False — KB-only, never escalate), ``full`` (bool, default
        False — untruncated chunk).
    context:
        Unused; the underlying script needs no API keys.

    Returns
    -------
    ToolCallResult
        Tier-labeled answer text, or an error description.
    """
    query = str(args.get("query", "") or "").strip()
    if not query:
        return ToolCallResult(
            tool_id="", tool_name="ask_internal_kb", result="",
            error="query is required (pass ONE focused question).",
        )
    try:
        skip_score = float(args.get("skip_score", -3.0) or -3.0)
    except (TypeError, ValueError):
        skip_score = -3.0
    no_live = bool(args.get("no_live", False))
    full = bool(args.get("full", False))

    cmd = [
        INTERNAL_KB_SCRIPT_PATH, "ask", query,
        "--skip-score", str(skip_score),
    ]
    if no_live:
        cmd.append("--no-live")
    if full:
        cmd.append("--full")

    # Live fallback (when it fires) costs as long as one internal_search
    # query; give it that much room locally on top of the KB-only case.
    result = _run_fastpath("ask_internal_kb", cmd, timeout_s=210)
    if result.error or not result.result:
        return result

    text = result.result
    first_line = text.splitlines()[0] if text else ""
    if first_line.startswith("[KB hit"):
        tier_note = (
            "[TIER: cache-hit — this is a CACHED excerpt, possibly stale. "
            "If it doesn't fully and freshly answer the question, fall "
            "back to internal_search.]\n\n"
        )
    elif first_line.startswith("[live answer]"):
        tier_note = (
            "[TIER: live-single-shot — ONE live query, escalated because "
            "the cache had no good match. This is a first-round answer "
            "ONLY, not internal_search's multi-round decompose+critique+"
            "deepen workflow. For broad/multi-faceted questions, still "
            "follow up with internal_search.]\n\n"
        )
    else:
        tier_note = ""

    body_len = len(text) - len(first_line)
    if tier_note and body_len < 200:
        tier_note += (
            "[warning: answer is short — may be thin/incomplete; consider "
            "internal_search to deepen.]\n\n"
        )
    return ToolCallResult(
        tool_id="", tool_name="ask_internal_kb",
        result=_truncate_result(tier_note + text),
    )


if INTERNAL_SEARCH_AVAILABLE:
    handle_search_moma = register_tool(
        name="search_moma",
        description=_SEARCH_MOMA_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["search", "who", "team"],
                    "description": (
                        "'search' for topic/doc search, 'who' for a "
                        "specific username, 'team' for a specific team "
                        "name."
                    ),
                    "default": "search",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Search term, username, or team name depending on "
                        "mode."
                    ),
                },
            },
            "required": ["mode", "query"],
        },
        is_interactive=False,
        category="search",
    )(handle_search_moma)

    handle_search_yaqs = register_tool(
        name="search_yaqs",
        description=_SEARCH_YAQS_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "YAQS search query.",
                },
            },
            "required": ["query"],
        },
        is_interactive=False,
        category="search",
    )(handle_search_yaqs)

    handle_get_bug = register_tool(
        name="get_bug",
        description=_GET_BUG_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "bug_id": {
                    "type": "string",
                    "description": "Numeric Buganizer bug ID.",
                },
            },
            "required": ["bug_id"],
        },
        is_interactive=False,
        category="search",
    )(handle_get_bug)

    handle_search_code = register_tool(
        name="search_code",
        description=_SEARCH_CODE_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Codebase question for the CodeSearch agent.",
                },
                "dir": {
                    "type": "string",
                    "description": (
                        "Optional path to scope the search to a known "
                        "subpackage/directory."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Remote timeout in seconds (30-300). Default 60."
                    ),
                    "default": 60,
                },
            },
            "required": ["query"],
        },
        is_interactive=False,
        category="search",
    )(handle_search_code)

    handle_search_code_standard = register_tool(
        name="search_code_standard",
        description=_SEARCH_CODE_STANDARD_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Code Search query using go/cs-reference filter "
                        "syntax (f:/c:/func:/class:/symbol:/lang:/within:/ "
                        "etc, implicitly AND-combined)."
                    ),
                },
                "dir": {
                    "type": "string",
                    "description": (
                        "Optional path to scope the search to a known "
                        "subpackage/directory."
                    ),
                },
            },
            "required": ["query"],
        },
        is_interactive=False,
        category="search",
    )(handle_search_code_standard)

if INTERNAL_SEARCH_AVAILABLE and INTERNAL_KB_AVAILABLE:
    handle_ask_internal_kb = register_tool(
        name="ask_internal_kb",
        description=_ASK_INTERNAL_KB_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "ONE focused internal-knowledge question (not a "
                        "list — use internal_search directly if you already "
                        "need multiple angles)."
                    ),
                },
                "skip_score": {
                    "type": "number",
                    "description": (
                        "BM25 threshold below which a cached hit is "
                        "considered good enough (lower = stricter). "
                        "Default -3.0."
                    ),
                    "default": -3.0,
                },
                "no_live": {
                    "type": "boolean",
                    "description": (
                        "KB-only: never escalate to a live query even on a "
                        "poor cache match. Default false."
                    ),
                    "default": False,
                },
                "full": {
                    "type": "boolean",
                    "description": (
                        "Return the full untruncated cached chunk instead "
                        "of a 2000-char preview. Default false."
                    ),
                    "default": False,
                },
            },
            "required": ["query"],
        },
        is_interactive=False,
        category="search",
    )(handle_ask_internal_kb)


# ---------------------------------------------------------------------------
# CKT direct internal tools — one root, subprocess-only, 120s hard deadline
# ---------------------------------------------------------------------------

from code_common.ckt_internal_tools import (
    CKT_INTERNAL_TOOL_NAMES,
    compact_json_result,
    is_ckt_internal_tools_available,
    run_ckt_command,
)

CKT_INTERNAL_TOOLS_AVAILABLE = is_ckt_internal_tools_available()

if CKT_INTERNAL_TOOLS_AVAILABLE:
    _CKT_TOOL_SPECS = {
        "read_url": ("Read one or more known company-internal URLs into Markdown (<10s average).", {"urls": {"type": "array", "items": {"type": "string"}}}, ["urls"]),
        "moma_search": ("Search Moma internal documents and teams (<10s average); use for cheap discovery.", {"query": {"type": "string"}}, ["query"]),
        "moma_bm25_read": ("Moma search, concurrent source reads, and BM25-ranked source evidence JSON (~15s average). Use for retrieval evidence, not final synthesis.", {"queries": {"type": "array", "items": {"type": "string"}}, "crawl": {"type": "boolean"}, "max_urls_per_query": {"type": "integer"}, "top_chunks_per_page": {"type": "integer"}}, ["queries"]),
        "yaqs_search": ("Search company-internal YAQS engineering Q&A (<10s average).", {"query": {"type": "string"}}, ["query"]),
        "code_search_standard": ("Fresh deterministic literal Code Search for a known symbol, string, or filter (<10s average).", {"query": {"type": "string"}, "directory": {"type": "string"}}, ["query"]),
        "kb_search": ("Search the local CKT internal knowledge base of cached evidence (<10s average); use as a cheap first probe.", {"query": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"]),
        "system_flow_research": ("Bounded Moma-first, source-grounded system-flow explanation (~20s average, 120s tail).", {"query": {"type": "string"}}, ["query"]),
        "code_trace": ("Parallel fresh literal Code Search for one to four explicit symbols (<10s average); returns grouped raw evidence without LLM synthesis.", {"question": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4}, "directory": {"type": "string"}}, ["question", "symbols"]),
        "duckie_search": ("Ask Duckie for a source-grounded internal answer (~45s average, 120s tail).", {"query": {"type": "string"}}, ["query"]),
        "ckt_duckie_retrieval": ("Plan diverse Duckie retrieval lenses and return raw structured JSON evidence (~60s average, 120s tail); no final synthesis.", {"query": {"type": "string"}, "query_count": {"type": "integer", "minimum": 1, "maximum": 6}}, ["query"]),
    }
    for _ckt_name, (_ckt_description, _ckt_properties, _ckt_required) in _CKT_TOOL_SPECS.items():
        def _make_ckt_handler(name):
            def _handler(args, context):
                del context
                return compact_json_result(run_ckt_command(name, args))
            return _handler
        register_tool(
            name=_ckt_name,
            description=_ckt_description + " Runs through the authorized local CKT façade with a hard 120-second deadline.",
            parameters={"type": "object", "properties": _ckt_properties, "required": _ckt_required},
            is_interactive=False,
            category="search",
        )(_make_ckt_handler(_ckt_name))

def build_ckt_tool_workflow_hint(tool_names: list) -> str:
    """Return model-facing CKT latency, parallelism, and multi-hop policy."""
    if not set(tool_names).intersection(CKT_INTERNAL_TOOL_NAMES):
        return ""
    return (
        "\n\n### CKT Company Retrieval Workflow\n"
        "All CKT calls are free in monetary terms: issue independent calls in PARALLEL; "
        "do not serialize calls that do not depend on each other.\n"
        "- Very Fast (<10s average): `kb_search`, `moma_search`, `read_url`, `yaqs_search`, "
        "`code_search_standard`, and `code_trace`.\n"
        "- Fast: `moma_bm25_read` — ~15s average, raw ranked source evidence.\n"
        "- Medium Speed (average 45s): `system_flow_research` — ~20s average; "
        "`duckie_search` — ~45s average; `ckt_duckie_retrieval` — ~60s average.\n"
        "ROUND 1: almost always make at least 3-4 parallel calls from the Very Fast and Fast applicable tools, "
        "unless you absolutely know fewer will answer the question. Search and indexes are imperfect, so "
        "you are responsible for heavy lifting in information discovery and navigation. ROUND 2+: inspect "
        "round-1 evidence, then use targeted reads, verification, deeper retrieval, and maybe multiple "
        "Medium Speed tools (or re-use Fast tools) for concrete gaps. Do not call `duckie_search` or "
        "`ckt_duckie_retrieval` in ROUND 1 unless the user explicitly asks for Duckie or the request clearly "
        "requires Duckie-specific evidence. First inspect the Fast/Very Fast discovery wave; use Duckie in "
        "ROUND 2+ for further investigation because Duckie is slower (~45-60s). For non-trivial research, perform "
        "at least two retrieval rounds. one round is acceptable only when a narrow question is directly "
        "and fully answered by an immediately found/read page. Raw evidence is for you to synthesize; do "
        "not claim completeness from thin or conflicting evidence. If the user mentions urgency or shorter "
        "answers, reduce the number of rounds or choose a faster tool mix.\n"
    )


# ---------------------------------------------------------------------------
# Tool Mode Selector — Tiered loading, Smart Select, request_tools meta-tool
# ---------------------------------------------------------------------------

TIER_1_TOOLS = [
    "ask_clarification",
    "perplexity_search",
    "jina_search",
    "jina_read_page",
    "read_link",
    "document_lookup",
    "docs_query",
    "docs_get_full_text",
    "pkb_search",
    "delegate_task",
    "search_messages",
    "request_tools",
]

# Always-on tools for the doubt-clearing flow, independent of the user's
# tools toggle. These let the doubt LLM read the target message and propose
# edits to it (user must approve the diff before anything is saved).
DOUBT_DEFAULT_TOOLS = [
    "read_message",
    "propose_answer_edit",
]

# Minimal always-included base for adaptive tier 1
_TIER_1_BASE = [
    "ask_clarification",
    "pkb_search",
    "delegate_task",
    "search_messages",
    "request_tools",
]

# internal_search (local script) is always-on when its script exists on this
# host: include in the static tier-1 list AND the adaptive base so it
# survives usage-history-based selection. Hybrid mode force-appends it in
# Conversation._get_enabled_tools (same pattern as request_tools).
# It is ALSO added to DOUBT_DEFAULT_TOOLS so the doubt-clearing (and, via the
# same list, temporary-LLM) quick actions can reach internal knowledge even
# when the user's general tools toggle is off — internal lookups should behave
# consistently everywhere the script exists.
if INTERNAL_SEARCH_AVAILABLE:
    TIER_1_TOOLS.append("internal_search")
    _TIER_1_BASE.append("internal_search")
    DOUBT_DEFAULT_TOOLS.append("internal_search")
    # read_internal_page rides alongside internal_search everywhere: same
    # host-gate, same always-on treatment (static tier-1, adaptive base, and
    # the doubt/temp default list). Selecting/enabling internal knowledge tools
    # should always expose BOTH search and page-read together.
    TIER_1_TOOLS.append("read_internal_page")
    _TIER_1_BASE.append("read_internal_page")
    DOUBT_DEFAULT_TOOLS.append("read_internal_page")

# search_local_internal_kb is in the same internal-knowledge group and gets
# the same always-on treatment wherever ITS script exists (own gate: it is a
# separate local script, so it can exist without internal-search and vice
# versa). It is the cheap first probe; the live tools remain the fallback.
if INTERNAL_KB_AVAILABLE:
    TIER_1_TOOLS.append("search_local_internal_kb")
    _TIER_1_BASE.append("search_local_internal_kb")
    DOUBT_DEFAULT_TOOLS.append("search_local_internal_kb")

# Typed fast-path internal tools (search_moma/search_yaqs/get_bug/
# search_code/search_code_standard) ride the same always-on treatment as
# internal_search — same host-gate (INTERNAL_SEARCH_AVAILABLE), since they
# all shell out to the same jetski-query script. ask_internal_kb additionally
# needs the local KB script (INTERNAL_KB_AVAILABLE).
if INTERNAL_SEARCH_AVAILABLE:
    for _fastpath_tool in ("search_moma", "search_yaqs", "get_bug", "search_code", "search_code_standard"):
        TIER_1_TOOLS.append(_fastpath_tool)
        _TIER_1_BASE.append(_fastpath_tool)
        DOUBT_DEFAULT_TOOLS.append(_fastpath_tool)

if INTERNAL_SEARCH_AVAILABLE and INTERNAL_KB_AVAILABLE:
    TIER_1_TOOLS.append("ask_internal_kb")
    _TIER_1_BASE.append("ask_internal_kb")
    DOUBT_DEFAULT_TOOLS.append("ask_internal_kb")

# CKT is the replacement internal-tool surface when INTERNAL_TOOLS_PATH is
# configured. Keep its expensive research tools discoverable on demand rather
# than always injecting them into every normal chat completion.
if CKT_INTERNAL_TOOLS_AVAILABLE:
    for _ckt_tool in sorted(CKT_INTERNAL_TOOL_NAMES):
        DOUBT_DEFAULT_TOOLS.append(_ckt_tool)


_adaptive_tier1_cache = {}  # {user_email: (timestamp, result)}
_ADAPTIVE_TIER1_TTL = 86400  # 1 day


def get_adaptive_tier1_tools(user_email="", target_size=12):
    """Get adaptive Tier 1 tools based on user's usage history.

    Falls back to static TIER_1_TOOLS if no history or on error.
    Uses most-frequently-used tools from last 30 days. Cached per user (1-day TTL).
    """
    import time
    if not user_email:
        return list(TIER_1_TOOLS)
    # Check cache
    cached = _adaptive_tier1_cache.get(user_email)
    if cached and (time.time() - cached[0]) < _ADAPTIVE_TIER1_TTL:
        return list(cached[1])
    try:
        from code_common.tool_call_history import get_tool_call_history_db
        import time
        from collections import Counter
        db = get_tool_call_history_db()
        if not db:
            return list(TIER_1_TOOLS)
        cutoff = time.time() - 30 * 86400
        rows = db.list_calls(user_email=user_email, since=cutoff, limit=200)
        if len(rows) < 10:
            _adaptive_tier1_cache[user_email] = (time.time(), TIER_1_TOOLS)
            return list(TIER_1_TOOLS)
        counts = Counter(r["tool_name"] for r in rows)
        frequent = [name for name, _ in counts.most_common(target_size * 2)]
        # Build adaptive: base + top frequent, capped at target_size
        all_names = {t.name for t in TOOL_REGISTRY.get_all_tools()}
        result = list(_TIER_1_BASE)
        for name in frequent:
            if name not in result and name in all_names:
                result.append(name)
            if len(result) >= target_size:
                break
        _adaptive_tier1_cache[user_email] = (time.time(), result)
        return result
    except Exception:
        return list(TIER_1_TOOLS)


def _build_compact_tool_menu():
    """Build a compact one-line-per-tool menu for the Smart Select LLM."""
    lines = []
    for t in TOOL_REGISTRY.get_all_tools():
        if t.name == "request_tools":
            continue
        lines.append(f"- {t.name} [{t.category}]: {t.description[:80]}")
    return "\n".join(lines)


# Pre-computed at import time after all tools are registered.
# Populated lazily on first access since tools register throughout module load.
_COMPACT_TOOL_MENU_CACHE = None


def get_compact_tool_menu():
    global _COMPACT_TOOL_MENU_CACHE
    if _COMPACT_TOOL_MENU_CACHE is None:
        _COMPACT_TOOL_MENU_CACHE = _build_compact_tool_menu()
    return _COMPACT_TOOL_MENU_CACHE


@register_tool(
    name="request_tools",
    description=(
        "Load additional tools not in your current set. Categories: "
        "search, documents, pkb, memory, conversation, cross_conversation, "
        "code_runner, artefacts, prompts, coding, aggregator, general. "
        "You can also request specific tool names."
    ),
    parameters={
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories to load (e.g. ['coding', 'artefacts'])",
            },
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific tool names to load",
            },
        },
    },
    is_interactive=False,
    category="meta",
)
def handle_request_tools(args: dict, context: ToolContext) -> ToolCallResult:
    """Handled specially in _run_tool_loop() as zero-cost expansion. This is a fallback."""
    categories = args.get("categories", [])
    tool_names = args.get("tool_names", [])
    loaded = []
    for t in TOOL_REGISTRY.get_all_tools():
        if t.category in categories or t.name in tool_names:
            loaded.append(t.name)
    return ToolCallResult(
        tool_id="", tool_name="request_tools",
        result=f"Loaded {len(loaded)} tools: {', '.join(loaded[:20])}",
    )


def _select_relevant_tools(user_message, summary, keys):
    """Use VERY_CHEAP_LLM to select relevant tools for this turn. HIGH RECALL."""
    from code_common.call_llm import call_llm
    from common import VERY_CHEAP_LLM, get_first_n_words

    menu = get_compact_tool_menu()
    prompt = (
        "Select which tools are relevant for this user message. "
        "HIGH RECALL — err heavily on inclusion. Missing a needed tool is much "
        "worse than including an unneeded one. Include follow-up tools (e.g. if "
        "search is needed, include read_link too). Include tools for plausible "
        "next steps the user might take within this turn. For CKT tools, prefer "
        "cheap <10s discovery tools in the first selection; include slower Duckie "
        "or system-flow tools only when their distinct task shape is clearly needed.\n"
        "Return ONLY a JSON array of tool names.\n\n"
        f"Message: {get_first_n_words(user_message, n=500)}\n"
        f"Context: {get_first_n_words(summary, n=500)}\n\n"
        f"Available tools:\n{menu}\n\n"
        "Output: [\"tool1\", \"tool2\", ...]"
    )
    try:
        result = call_llm(keys=keys, model_name=VERY_CHEAP_LLM[0], text=prompt, stream=False)
        # Extract JSON array from response
        import re
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if not match:
            return list(TIER_1_TOOLS)
        selected = json.loads(match.group())
        # Validate: only keep names that exist
        all_names = {t.name for t in TOOL_REGISTRY.get_all_tools()}
        selected = [n for n in selected if n in all_names]
        if len(selected) < 3:
            selected = list(set(selected + TIER_1_TOOLS))
        if len(selected) > 30:
            selected = selected[:30]
        return selected
    except Exception:
        return list(TIER_1_TOOLS)
