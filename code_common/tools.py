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

TOOL_RESULT_TRUNCATION_LIMIT = 12000
"""Hard cap (in characters) on the length of a tool result string sent back to the LLM."""


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
        "Search the web for current information. Use when you need up-to-date "
        "facts, news, or information not in your training data or the "
        "conversation context. Provide a focused search query and additional "
        "context describing what information is needed and why. The context "
        "helps the search agent produce more relevant results."
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
                                doc_id, doc_storage = entry[0], entry[1]
                                display = entry[3] if len(entry) > 3 else doc_id
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
        "Search using Jina AI with full web content retrieval. "
        "Fetches actual page content (not just snippets), summarises "
        "long pages, and handles PDFs. Provide a focused search query and "
        "additional context describing what information is needed. The context "
        "helps produce more relevant results by guiding extraction and summarization."
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

        # Resolve model name
        from common import CHEAP_LLM
        model_name = CHEAP_LLM[0]

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
            doc_id, doc_storage, pdf_url = entry[0], entry[1], entry[2]
            doc = _docs_load_doc_index(doc_storage)
            if doc is None:
                results.append({
                    "index": idx + 1,
                    "doc_id": doc_id,
                    "title": "(failed to load)",
                    "short_summary": "",
                    "doc_storage_path": doc_storage,
                    "source": pdf_url,
                    "display_name": entry[3] if len(entry) > 3 else None,
                })
                continue
            results.append({
                "index": idx + 1,
                "doc_id": doc_id,
                "title": doc.title,
                "short_summary": doc.short_summary,
                "doc_storage_path": doc_storage,
                "source": pdf_url,
                "display_name": entry[3] if len(entry) > 3 else None,
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
        "Search the user's Personal Knowledge Base (PKB) for relevant claims. "
        "Uses hybrid search (FTS5 + embedding similarity) by default. "
        "Returns a ranked list of matching claims with relevance scores."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query"},
            "k": {
                "type": "integer",
                "description": "Maximum number of results to return",
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
    conversation_id = args.get("conversation_id", "") or getattr(context, "conversation_id", "")
    try:
        conv = _conv_load(conversation_id)
        if conv is None:
            return ToolCallResult(
                tool_id="", tool_name="read_message",
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
            error=f"Error reading message: {e}",
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
