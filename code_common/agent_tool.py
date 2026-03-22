"""
Agent / Delegate Task tool — meta-tool that runs a sub-agent LLM loop.

Why this exists
---------------
Complex user questions often require the main LLM to orchestrate multiple
tool calls in sequence, consuming iteration budget and context window.
This module provides a ``delegate_task`` meta-tool that encapsulates a
full LLM-with-tools sub-loop behind a single tool call.

The main LLM delegates a sub-task (e.g. "research X using web search and
documents") to a sub-LLM that has its own tool access, runs its own
agentic loop, and returns a synthesized answer.

Architecture
~~~~~~~~~~~~
- ``AGENT_PROFILES`` maps profile names to lists of tool names.
- ``run_agent_loop()`` is the core non-streaming mini tool loop.
- Both ``code_common/tools.py`` and ``mcp_server/mcp_app.py`` import
  ``AGENT_TOOLS`` (shared metadata) and ``run_agent_loop()`` from here.

Dependencies
~~~~~~~~~~~~
- ``code_common.call_llm`` — LLM calls (lazy import to avoid cycles).
- ``code_common.tools`` — ``TOOL_REGISTRY`` for tool execution (lazy).
- ``code_common.tool_call_history`` — recording sub-agent tool calls (lazy).
- ``loggers.py`` for logging.

Plan reference: documentation/planning/plans/agent_delegate_task.plan.md
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional
import time
import traceback
from typing import Any, Dict, List, Optional

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "agent_tool",
    logger_level=10,
    time_logger_level=10,
)


# ============================================================================
# Part 1: Constants
# ============================================================================

AGENT_DEFAULT_MODEL = "openai/gpt-4o-mini"
"""Default model for the sub-agent.  Cheap and fast."""

AGENT_MAX_ITERATIONS = 5
"""Maximum tool-loop iterations for the sub-agent."""

AGENT_TIMEOUT_SECONDS = 300
"""Wall-clock timeout (5 minutes) for the entire sub-agent execution."""

BACKGROUND_TASK_EXPIRY_SECONDS = 1800  # 30 minutes

# Background task store: keyed by UUID4 string
# Each entry: {"status": "running"|"done"|"error", "result": str, "started_at": float}
_BACKGROUND_TASKS: Dict[str, Dict] = {}
_BACKGROUND_TASKS_LOCK = threading.Lock()

# ============================================================================
# Part 2: Profile Configuration
# ============================================================================

AGENT_PROFILES: Dict[str, List[str]] = {
    "research": [
        # Search tools
        "web_search",
        "perplexity_search",
        "jina_search",
        "jina_read_page",
        "read_link",
        # Document query tools (read-only)
        "document_lookup",
        "docs_list_conversation_docs",
        "docs_list_global_docs",
        "docs_query",
        "docs_get_full_text",
        "docs_get_info",
        "docs_answer_question",
        "docs_get_global_doc_info",
        "docs_query_global_doc",
        "docs_get_global_doc_full_text",
        # Conversation search
        "search_messages",
        "list_messages",
        "read_message",
        "search_conversations",
        "list_user_conversations",
        "get_conversation_summary",
        # Tool call history (reuse previous results)
        "list_search_history",
        "get_search_results",
        "list_tool_call_history",
        "get_tool_call_results",
    ],
    "documents": [
        # Full document tools
        "document_lookup",
        "docs_list_conversation_docs",
        "docs_list_global_docs",
        "docs_query",
        "docs_get_full_text",
        "docs_get_info",
        "docs_answer_question",
        "docs_get_global_doc_info",
        "docs_query_global_doc",
        "docs_get_global_doc_full_text",
        # Conversation tools (for cross-referencing)
        "search_messages",
        "list_messages",
        "read_message",
        "get_conversation_details",
        "get_conversation_memory_pad",
        "search_conversations",
        "list_user_conversations",
        "get_conversation_summary",
        # Tool call history
        "list_search_history",
        "get_search_results",
        "list_tool_call_history",
        "get_tool_call_results",
    ],
    "general": [
        # Search
        "web_search",
        "perplexity_search",
        "jina_search",
        "jina_read_page",
        "read_link",
        # Documents
        "document_lookup",
        "docs_list_conversation_docs",
        "docs_list_global_docs",
        "docs_query",
        "docs_get_full_text",
        "docs_get_info",
        "docs_answer_question",
        "docs_get_global_doc_info",
        "docs_query_global_doc",
        "docs_get_global_doc_full_text",
        # Conversation & cross-conversation
        "search_messages",
        "list_messages",
        "read_message",
        "get_conversation_details",
        "get_conversation_memory_pad",
        "search_conversations",
        "list_user_conversations",
        "get_conversation_summary",
        # Memory
        "conv_get_memory_pad",
        "conv_get_history",
        "conv_get_user_detail",
        "conv_get_user_preference",
        "conv_get_messages",
        # Tool call history
        "list_search_history",
        "get_search_results",
        "list_tool_call_history",
        "get_tool_call_results",
        # Code runner
        "run_python_code",
        # Coding & file system tools
        "fs_read_file",
        "fs_read_pdf",
        "fs_get_file_structure_and_summary",
        "fs_write_file",
        "fs_patch_file",
        "fs_list_dir",
        "fs_find_files",
        "fs_grep",
        "fs_file_info",
        "fs_bash",
        "todo_write",
        "todo_read",
        # Delegate tools (for 1-level recursion — stripped at depth >= 2)
        "delegate_task",
        "delegate_task_background",
        "list_background_tasks",
        "get_task_result",
    ],
}


# ============================================================================
# Part 3: Shared Tool Metadata (imported by tools.py and mcp_app.py)
# ============================================================================

_AGENT_CATEGORY = "aggregator"

AGENT_TOOLS: Dict[str, dict] = {
    "delegate_task": {
        "name": "delegate_task",
        "description": (
            "Delegate a sub-task to an autonomous agent that has its own tool "
            "access. The agent runs a multi-step tool loop (up to 5 iterations) "
            "and returns a synthesized text answer. Use this to offload complex "
            "research, document analysis, or multi-tool workflows without "
            "consuming the main conversation's iteration budget.\n\n"
            "Profiles control which tools the agent can use:\n"
            "- 'research': Web search + document query + conversation search. "
            "Best for information gathering.\n"
            "- 'documents': Full document tools + conversation tools. "
            "Best for document analysis and lookup.\n"
            "- 'general': All non-interactive tools (broadest capability). "
            "Best for open-ended tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The task description or question for the sub-agent. "
                        "Be specific about what information you need and how "
                        "the results should be formatted."
                    ),
                },
                "profile": {
                    "type": "string",
                    "enum": ["research", "documents", "general"],
                    "description": (
                        "Tool profile controlling which tools the agent gets. "
                        "'research' for web search + docs, 'documents' for "
                        "document analysis, 'general' for all tools."
                    ),
                },
            },
            "required": ["prompt", "profile"],
        },
        "is_interactive": False,
        "category": _AGENT_CATEGORY,
    },
    "delegate_task_background": {
        "name": "delegate_task_background",
        "description": (
            "Fire-and-forget version of delegate_task. Starts the sub-agent in a "
            "background daemon thread and returns a task_id immediately so the "
            "main LLM can continue working in parallel.\n\n"
            "The sub-agent has full access to all tools in the chosen profile "
            "(including fs_*, run_python_code, web search, MCP tools, etc.).\n\n"
            "Use get_task_result(task_id=...) to poll for the result. "
            "Use list_background_tasks() to see all active/completed tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task description for the background sub-agent.",
                },
                "profile": {
                    "type": "string",
                    "enum": ["research", "documents", "general"],
                    "description": "Tool profile: 'research', 'documents', or 'general'.",
                },
            },
            "required": ["prompt", "profile"],
        },
        "is_interactive": False,
        "category": _AGENT_CATEGORY,
    },
    "get_task_result": {
        "name": "get_task_result",
        "description": (
            "Poll for the result of a background task started by delegate_task_background. "
            "Returns status ('running', 'done', 'error', 'not_found', 'expired') and the "
            "result text when complete. Tasks expire after 30 minutes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task_id returned by delegate_task_background.",
                },
            },
            "required": ["task_id"],
        },
        "is_interactive": False,
        "category": _AGENT_CATEGORY,
    },
    "list_background_tasks": {
        "name": "list_background_tasks",
        "description": (
            "List all background tasks (running and completed) in this server session. "
            "Returns task_id, status, age in seconds, and a result preview for each. "
            "Expired tasks (>30 min) are pruned during this call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "enum": ["all", "running", "done", "error"],
                    "description": "Filter by status. Default: 'all'.",
                    "default": "all",
                },
            },
            "required": [],
        },
        "is_interactive": False,
        "category": _AGENT_CATEGORY,
    },
}
def get_background_task_result(task_id: str) -> Dict:
    """Return status/result of a background task; lazily expire stale entries."""
    with _BACKGROUND_TASKS_LOCK:
        task = _BACKGROUND_TASKS.get(task_id)
        if task is None:
            return {"status": "not_found", "result": f"No task with id: {task_id}"}
        age = time.time() - task["started_at"]
        if age > BACKGROUND_TASK_EXPIRY_SECONDS:
            del _BACKGROUND_TASKS[task_id]
            return {"status": "expired", "result": "Task result expired (>30 min)."}
        return {"status": task["status"], "result": task.get("result", "")}


def list_all_background_tasks(status_filter: str = "all") -> list:
    """Return a list of background task summaries, optionally filtered by status."""
    now = time.time()
    results = []
    with _BACKGROUND_TASKS_LOCK:
        expired = [tid for tid, t in _BACKGROUND_TASKS.items()
                   if now - t["started_at"] > BACKGROUND_TASK_EXPIRY_SECONDS]
        for tid in expired:
            del _BACKGROUND_TASKS[tid]
        for tid, task in _BACKGROUND_TASKS.items():
            if status_filter != "all" and task["status"] != status_filter:
                continue
            results.append({
                "task_id": tid,
                "status": task["status"],
                "age_seconds": int(now - task["started_at"]),
                "result_preview": task["result"][:200] if task["result"] else "",
            })
    return results


def start_background_agent(prompt: str, profile: str, context: Any) -> str:
    """Start a background sub-agent daemon thread and return the task_id."""
    task_id = str(uuid.uuid4())
    with _BACKGROUND_TASKS_LOCK:
        _BACKGROUND_TASKS[task_id] = {
            "status": "running",
            "result": "",
            "started_at": time.time(),
        }
    t = threading.Thread(
        target=_run_background_task,
        args=(task_id, prompt, profile, context),
        daemon=True,
    )
    t.start()
    logger.info("Started background agent task_id=%s profile=%s", task_id, profile)
    return task_id


def _run_background_task(task_id: str, prompt: str, profile: str, context: Any) -> None:
    """Daemon thread target: call run_agent_loop and write result to _BACKGROUND_TASKS."""
    try:
        result = run_agent_loop(prompt, profile, context, depth=1)
        with _BACKGROUND_TASKS_LOCK:
            _BACKGROUND_TASKS[task_id]["status"] = "done"
            _BACKGROUND_TASKS[task_id]["result"] = result
    except Exception as exc:
        with _BACKGROUND_TASKS_LOCK:
            _BACKGROUND_TASKS[task_id]["status"] = "error"
            _BACKGROUND_TASKS[task_id]["result"] = f"Background task error: {exc}"
        error_logger.error("Background task %s failed: %s", task_id, exc)


def _agent_tool_kwargs(tool_name: str) -> dict:
    """Extract kwargs suitable for ``@register_tool`` from ``AGENT_TOOLS``.

    Mirrors the pattern used by ``_history_tool_kwargs`` and
    ``_cross_conv_tool_kwargs`` in ``tools.py``.
    """
    return {
        k: v
        for k, v in AGENT_TOOLS[tool_name].items()
        if k in ("name", "description", "parameters", "is_interactive", "category")
    }


# ============================================================================
# Part 4: Helper Functions
# ============================================================================


def _resolve_agent_tools(profile: str, depth: int) -> tuple[list[dict], list[str]]:
    """Resolve tool names for a profile and return OpenAI-format tool list.

    Parameters
    ----------
    profile:
        One of the keys in ``AGENT_PROFILES``.
    depth:
        Current recursion depth.  At depth >= 2, ``delegate_task`` is
        stripped from the tool list to prevent infinite recursion.

    Returns
    -------
    tuple[list[dict], list[str]]
        (openai_tools_param, valid_tool_names) — the tools in OpenAI API
        format and the corresponding list of validated tool names.
    """
    from code_common.tools import TOOL_REGISTRY

    raw_names = list(AGENT_PROFILES.get(profile, AGENT_PROFILES["general"]))

    # Strip delegate_task at depth >= 2 to prevent infinite recursion
    if depth >= 2 and "delegate_task" in raw_names:
        raw_names.remove("delegate_task")

    # Validate names against registry and filter interactive tools
    valid_names = []
    for name in raw_names:
        tool_def = TOOL_REGISTRY.get_tool(name)
        if tool_def is None:
            logger.warning(
                "Agent profile '%s' references unknown tool: %s", profile, name
            )
            continue
        if tool_def.is_interactive:
            logger.debug("Filtering interactive tool from agent: %s", name)
            continue
        valid_names.append(name)

    openai_tools = TOOL_REGISTRY.get_openai_tools_param(valid_names)
    return openai_tools, valid_names


def _build_agent_system_prompt(parent_context: str = "") -> str:
    """Build the system prompt for the sub-agent.

    Parameters
    ----------
    parent_context:
        Optional summary of the parent conversation for grounding.
    """
    parts = [
        "You are a focused research and task execution agent. You have access "
        "to tools and should use them to complete the given task thoroughly.",
        "",
        "Instructions:",
        "- Use the available tools to gather information and complete the task.",
        "- Be thorough but efficient — prefer reusing previous search results "
        "when available (check tool call history first).",
        "- Synthesize your findings into a clear, well-organized answer.",
        "- If a tool call fails, try an alternative approach.",
        "- When you have enough information, produce your final answer as text.",
        "- Do not ask clarifying questions — work with what you have.",
    ]

    if parent_context:
        parts.extend(
            [
                "",
                "Context from the parent conversation:",
                parent_context,
            ]
        )

    return "\n".join(parts)


def _record_agent_tool_call(
    tool_name: str,
    args_dict: dict,
    result_text: str,
    error_text: Optional[str],
    duration: float,
    user_email: str,
    conversation_id: Optional[str],
) -> None:
    """Record a sub-agent tool call to history.  Fail-open — never raises."""
    try:
        from code_common.tool_call_history import (
            get_tool_call_history_db,
            tool_call_hash,
        )

        db = get_tool_call_history_db()
        if db:
            from code_common.tool_call_history import get_tool_category

            db.record(
                id=tool_call_hash(tool_name, args_dict),
                tool_name=tool_name,
                tool_category=get_tool_category(tool_name),
                args_json=json.dumps(args_dict, ensure_ascii=False),
                result_text=result_text,
                error=error_text,
                user_email=user_email,
                conversation_id=conversation_id,
                timestamp=time.time(),
                duration_seconds=duration,
                result_chars=len(result_text) if result_text else 0,
                source="agent_delegate",
            )
    except Exception:
        logger.debug("Failed to record agent tool call", exc_info=True)


def _parse_llm_response(response: Any) -> tuple[str, list[dict]]:
    """Parse call_llm(stream=False, tools=...) response into text and tool calls.

    When tools are provided, call_llm may return:
    - A str (text-only response, no tool calls)
    - A list of mixed str and dict items (text chunks + tool call dicts)

    Tool call dicts have shape:
        {"type": "tool_call", "id": str, "function": {"name": str, "arguments": str}}

    Returns
    -------
    tuple[str, list[dict]]
        (text_content, tool_calls) where tool_calls is a list of tool call dicts.
    """
    if isinstance(response, str):
        return response, []

    if isinstance(response, list):
        text_parts = []
        tool_calls = []
        for item in response:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "tool_call":
                tool_calls.append(item)
        return "".join(text_parts), tool_calls

    # Unexpected type — treat as text
    return str(response), []


# ============================================================================
# Part 5: Core Agent Loop
# ============================================================================


def run_agent_loop(
    prompt: str,
    profile: str,
    context: Any,
    depth: int = 1,
) -> str:
    """Run a non-streaming sub-agent tool loop and return the final text.

    This is the core function called by both the tool-calling handler and
    the MCP handler.

    Parameters
    ----------
    prompt:
        The user's task description for the sub-agent.
    profile:
        Tool profile name (key in ``AGENT_PROFILES``).
    context:
        A ``ToolContext`` instance carrying conversation_id, user_email,
        keys, and model_overrides.
    depth:
        Current recursion depth (1 = first delegation, 2 = nested).

    Returns
    -------
    str
        The sub-agent's final text answer, or an error message on failure.
    """
    from code_common.call_llm import call_llm
    from code_common.tools import TOOL_REGISTRY

    start_time = time.time()

    # --- Resolve model ---
    model = AGENT_DEFAULT_MODEL
    if hasattr(context, "model_overrides") and context.model_overrides:
        model = context.model_overrides.get("agent_model", model)

    # --- Resolve tools ---
    try:
        openai_tools, valid_tool_names = _resolve_agent_tools(profile, depth)
    except Exception as exc:
        error_logger.error(
            "Failed to resolve agent tools for profile '%s': %s", profile, exc
        )
        return f"Agent error: failed to resolve tools for profile '{profile}': {exc}"

    if not openai_tools:
        return f"Agent error: no valid tools found for profile '{profile}'."

    # --- Build system prompt ---
    # Fetch parent context from conversation_summary if available
    parent_context = ""
    if hasattr(context, "conversation_summary") and context.conversation_summary:
        parent_context = context.conversation_summary

    system_prompt = _build_agent_system_prompt(parent_context)

    # --- Build initial messages ---
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    # --- Get context fields ---
    user_email = getattr(context, "user_email", "unknown")
    conversation_id = getattr(context, "conversation_id", None)
    keys = getattr(context, "keys", None)
    if not keys:
        try:
            from endpoints.utils import keyParser

            keys = keyParser({})
        except Exception:
            return "Agent error: no API keys available."

    logger.info(
        "Starting agent loop: profile=%s, model=%s, depth=%d, tools=%d",
        profile,
        model,
        depth,
        len(valid_tool_names),
    )

    # --- Main loop ---
    final_text = ""
    for iteration in range(AGENT_MAX_ITERATIONS):
        # Check wall-clock timeout
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT_SECONDS:
            logger.warning(
                "Agent loop timed out after %.1fs at iteration %d", elapsed, iteration
            )
            if final_text:
                return final_text
            return "Agent error: execution timed out."

        # On last iteration, force text output
        current_tool_choice: Any = "auto"
        current_tools = openai_tools
        if iteration == AGENT_MAX_ITERATIONS - 1:
            current_tool_choice = "none"
            current_tools = None  # Don't send tools when forcing no-tool response

        try:
            response = call_llm(
                keys=keys,
                model_name=model,
                messages=messages,
                tools=current_tools,
                tool_choice=current_tool_choice if current_tools else None,
                stream=False,
                temperature=0.3,
            )
        except Exception as exc:
            error_logger.error(
                "Agent call_llm error at iteration %d: %s", iteration, exc
            )
            if final_text:
                return final_text
            return f"Agent error: LLM call failed: {exc}"

        # --- Parse response ---
        text_content, tool_calls = _parse_llm_response(response)

        if text_content:
            final_text = text_content  # Keep updating with latest text

        # If no tool calls, we're done (model produced final text)
        if not tool_calls:
            logger.info(
                "Agent loop completed at iteration %d with text response", iteration
            )
            break

        # --- Execute tool calls ---
        # Add assistant message with tool calls to conversation
        assistant_msg: dict = {"role": "assistant", "content": text_content or None}
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls
        ]
        messages.append(assistant_msg)

        for tc in tool_calls:
            tc_id = tc["id"]
            tc_name = tc["function"]["name"]
            tc_args_str = tc["function"]["arguments"]

            # Parse arguments
            try:
                tc_args = json.loads(tc_args_str) if tc_args_str else {}
            except json.JSONDecodeError:
                tc_args = {}
                logger.warning(
                    "Agent: failed to parse tool args for %s: %s",
                    tc_name,
                    tc_args_str[:200],
                )

            # Handle recursive delegate_task
            if tc_name == "delegate_task" and depth < 2:
                logger.info("Agent: recursive delegate_task at depth %d", depth)
                tc_start = time.time()
                try:
                    inner_result = run_agent_loop(
                        prompt=tc_args.get("prompt", ""),
                        profile=tc_args.get("profile", "general"),
                        context=context,
                        depth=depth + 1,
                    )
                    tool_result_text = inner_result
                    tool_error = None
                except Exception as exc:
                    tool_result_text = f"Delegate error: {exc}"
                    tool_error = str(exc)
                tc_duration = time.time() - tc_start
            elif tc_name == "delegate_task":
                # Should not happen (stripped at depth >= 2), but safety check
                tool_result_text = "Error: maximum delegation depth reached."
                tool_error = "Max depth"
                tc_duration = 0.0
            elif tc_name not in valid_tool_names:
                tool_result_text = f"Error: tool '{tc_name}' is not available in the '{profile}' profile."
                tool_error = "Unavailable tool"
                tc_duration = 0.0
            else:
                # Execute via TOOL_REGISTRY
                tc_start = time.time()
                try:
                    result = TOOL_REGISTRY.execute(
                        name=tc_name,
                        args=tc_args,
                        context=context,
                        tool_call_id=tc_id,
                    )
                    tool_result_text = result.result if result else ""
                    tool_error = result.error if result else None
                except Exception as exc:
                    logger.exception(
                        "Agent: tool execution error for %s: %s", tc_name, exc
                    )
                    tool_result_text = f"Tool execution error: {exc}"
                    tool_error = str(exc)
                tc_duration = time.time() - tc_start

            # Record tool call in history
            _record_agent_tool_call(
                tool_name=tc_name,
                args_dict=tc_args,
                result_text=tool_result_text or "",
                error_text=tool_error,
                duration=tc_duration,
                user_email=user_email,
                conversation_id=conversation_id,
            )

            # Add tool result message
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result_text or "(empty result)",
                }
            )

            logger.info(
                "Agent: tool %s completed in %.1fs (error=%s, result_len=%d)",
                tc_name,
                tc_duration,
                bool(tool_error),
                len(tool_result_text) if tool_result_text else 0,
            )

    # If we exhausted iterations without a final text, do one last call
    if not final_text:
        try:
            response = call_llm(
                keys=keys,
                model_name=model,
                messages=messages,
                tools=None,
                stream=False,
                temperature=0.3,
            )
            final_text, _ = _parse_llm_response(response)
        except Exception as exc:
            error_logger.error("Agent final text extraction failed: %s", exc)
            final_text = "Agent completed but failed to produce a final summary."

    elapsed = time.time() - start_time
    logger.info(
        "Agent loop finished: %.1fs elapsed, profile=%s, depth=%d",
        elapsed,
        profile,
        depth,
    )
    return final_text or "Agent completed but produced no output."
