"""
Shared utilities for LLM-assisted editing.

Provides helpers for prompt construction, content hashing, response parsing,
and conversation context gathering. Used by both the file browser AI edit
endpoint and the artefacts propose_edits endpoint.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from difflib import unified_diff
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language / extension mapping
# ---------------------------------------------------------------------------

LANGUAGE_MAP: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".markdown": "markdown",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sql": "sql",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".txt": "text",
    ".csv": "csv",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    ".php": "php",
    ".pl": "perl",
    ".dockerfile": "dockerfile",
}


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def hash_content(content: str) -> str:
    """Return a SHA-256 hex digest for the given content.

    Parameters
    ----------
    content : str
        Text to hash.

    Returns
    -------
    str
        Hex digest string.
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Line numbering and line extraction
# ---------------------------------------------------------------------------


def line_number_content(content: str) -> str:
    """Add 1-based line numbers to content for LLM context.

    Parameters
    ----------
    content : str
        File content.

    Returns
    -------
    str
        Line-numbered text.
    """
    if not content:
        return "(empty file)"
    lines = content.splitlines()
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))


def read_lines(content: str, start: int, end: int) -> str:
    """Read a 1-indexed inclusive line range from content.

    Parameters
    ----------
    content : str
        File content.
    start : int
        Start line (1-indexed, inclusive).
    end : int
        End line (1-indexed, inclusive).

    Returns
    -------
    str
        Selected lines joined by newline.
    """
    lines = content.splitlines()
    if not lines:
        return ""
    start_idx = max(1, int(start)) - 1
    end_idx = max(start_idx, int(end) - 1)
    end_idx = min(end_idx, len(lines) - 1)
    return "\n".join(lines[start_idx : end_idx + 1])


# ---------------------------------------------------------------------------
# LLM output processing
# ---------------------------------------------------------------------------


def consume_llm_output(result: Any) -> str:
    """Convert LLM output (string or iterable of chunks) to a string.

    Parameters
    ----------
    result : Any
        LLM return value — either a string or an iterable of string chunks.

    Returns
    -------
    str
        Full response text.
    """
    if isinstance(result, str):
        return result
    try:
        return "".join(chunk for chunk in result)
    except TypeError:
        return str(result)


def extract_code_from_response(llm_output: str) -> str:
    """Extract content from the first fenced code block in LLM output.

    Looks for content between the first opening ``` and the last closing ```.
    Falls back to the full stripped text if no code fences are found.

    Parameters
    ----------
    llm_output : str
        Raw LLM response text.

    Returns
    -------
    str
        Extracted code content.
    """
    if not llm_output:
        return ""
    text = llm_output.strip()
    # Find opening fence (``` optionally followed by a language identifier)
    open_match = re.search(r"```[a-zA-Z]*\s*\n?", text)
    if not open_match:
        # No code fence found — return full text as fallback
        return text
    # Find the last closing fence
    close_idx = text.rfind("```", open_match.end())
    if close_idx == -1:
        # Opening fence but no closing fence — take everything after the open
        return text[open_match.end():].strip()
    return text[open_match.end():close_idx].strip("\n")


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_recent_messages(messages: List[Dict[str, Any]], limit: int) -> str:
    """Format recent conversation messages for inclusion in a prompt.

    Parameters
    ----------
    messages : list
        Conversation message list.
    limit : int
        Number of most recent messages to include.

    Returns
    -------
    str
        Formatted conversation excerpt.
    """
    if not messages:
        return ""
    limit = max(0, int(limit))
    recent = messages[-limit:] if limit > 0 else []
    lines = []
    for msg in recent:
        role = msg.get("sender") or msg.get("role") or "user"
        text = msg.get("text") or msg.get("content") or ""
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_language(file_path: str) -> str:
    """Detect a language name from a file path extension.

    Parameters
    ----------
    file_path : str
        File path (only the extension is used).

    Returns
    -------
    str
        Language name (e.g. 'python', 'javascript') or 'text' as fallback.
    """
    if not file_path:
        return "text"
    _, ext = os.path.splitext(file_path)
    # Handle Dockerfile specially
    basename = os.path.basename(file_path).lower()
    if basename in ("dockerfile", "dockerfile.dev", "dockerfile.prod"):
        return "dockerfile"
    if basename in ("makefile", "gnumakefile"):
        return "makefile"
    return LANGUAGE_MAP.get(ext.lower(), "text")


# ---------------------------------------------------------------------------
# Conversation context gathering
# ---------------------------------------------------------------------------


def gather_conversation_context(
    conversation: Any,
    instruction: str,
    include_context: bool = False,
    deep_context: bool = False,
    include_summary: bool = True,
    include_messages: bool = True,
    include_memory_pad: bool = False,
    history_count: int = 2,
) -> Dict[str, str]:
    """Gather conversation context for an LLM edit prompt.
    Optionally performs expensive LLM-based context extraction if
    ``deep_context`` is True.
    ----------
    conversation : Conversation
        Loaded conversation instance with API keys set.
    instruction : str
        The edit instruction — used as the retrieval query for deep context.
    include_context : bool
        Whether to include basic context (summary + recent messages).
    deep_context : bool
        Whether to additionally run ``retrieve_prior_context_llm_based``.
    include_summary : bool
        Whether to include the running summary in the context.
    include_messages : bool
        Whether to include recent messages in the context.
    include_memory_pad : bool
        Whether to include the conversation memory pad.
    history_count : int
        Number of recent messages to include (default 2).
    Returns
    -------
    dict
        Keys: ``summary``, ``recent_messages``, ``extracted_context``,
        ``memory_pad``.  Values are empty strings when the corresponding
        flag is False.
    """
    result: Dict[str, str] = {
        "summary": "",
        "recent_messages": "",
        "extracted_context": "",
        "memory_pad": "",
    }
    if not include_context or conversation is None:
        return result

    if include_summary:
        try:
            result["summary"] = conversation.running_summary or ""
        except Exception:
            logger.warning("Failed to get running summary", exc_info=True)
    if include_messages:
        try:
            messages = conversation.get_message_list() or []
            result["recent_messages"] = format_recent_messages(messages, history_count)
        except Exception:
            logger.warning("Failed to get recent messages", exc_info=True)
    if include_memory_pad:
        try:
            result["memory_pad"] = getattr(conversation, "memory_pad", "") or ""
        except Exception:
            logger.warning("Failed to get memory pad", exc_info=True)
    if deep_context:
        try:
            ctx = conversation.retrieve_prior_context_llm_based(
                query=instruction,
                required_message_lookback=30,
            )
            result["extracted_context"] = ctx.get("extracted_context", "")
        except Exception:
            logger.warning("Failed to retrieve LLM-based context", exc_info=True)
    return result


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a precise code editor. Return ONLY the edited content inside a "
    "single fenced code block. Do not include explanations, commentary, or "
    "anything outside the code block. Do not include line numbers in the "
    "output. Preserve the original formatting, indentation, and style unless "
    "the instruction specifically asks to change them."
)


def build_edit_prompt(
    instruction: str,
    file_path: str,
    content: str,
    selection: Optional[Dict[str, Any]] = None,
    context_parts: Optional[Dict[str, str]] = None,
) -> str:
    """Construct the user prompt for an LLM edit request.

    Builds either a selection-edit prompt (with surrounding context lines)
    or a whole-file edit prompt depending on whether ``selection`` is provided.

    Parameters
    ----------
    instruction : str
        Natural language edit instruction.
    file_path : str
        File path (used for language detection and display).
    content : str
        Full file content.
    selection : dict, optional
        If provided, must contain ``start_line`` and ``end_line`` (1-indexed).
        Generates a selection-edit prompt with surrounding context.
    context_parts : dict, optional
        Conversation context with keys ``summary``, ``recent_messages``,
        ``extracted_context``.  Values are empty strings when not included.

    Returns
    -------
    str
        Complete user prompt ready to send to the LLM.
    """
    lang = detect_language(file_path)
    ctx = context_parts or {}
    summary = ctx.get("summary", "")
    recent = ctx.get("recent_messages", "")
    extracted = ctx.get("extracted_context", "")
    memory_pad = ctx.get("memory_pad", "")

    # Context section
    context_section = "## Conversation Context\n"
    context_section += f"### Summary\n{summary or '(not included)'}\n\n"
    context_section += f"### Recent Messages\n{recent or '(not included)'}\n\n"
    context_section += f"### Extracted Context\n{extracted or '(not included)'}\n"
    if memory_pad:
        context_section += f"### Memory Pad\n{memory_pad}\n"

    if selection and selection.get("start_line") and selection.get("end_line"):
        return _build_selection_prompt(
            instruction, file_path, lang, content, selection, context_section
        )
    else:
        return _build_whole_file_prompt(
            instruction, file_path, lang, content, context_section
        )


def _build_selection_prompt(
    instruction: str,
    file_path: str,
    lang: str,
    content: str,
    selection: Dict[str, Any],
    context_section: str,
) -> str:
    """Build a prompt for editing a selected region of a file.

    Includes the selected text plus up to 15 lines before and after as
    read-only surrounding context.
    """
    start = int(selection["start_line"])
    end = int(selection["end_line"])
    selected_text = read_lines(content, start, end)
    lines = content.splitlines()
    total = len(lines)

    # Surrounding context: up to 15 lines before and after
    before_start = max(1, start - 15)
    after_end = min(total, end + 15)

    before_text = read_lines(content, before_start, start - 1) if start > 1 else ""
    after_text = read_lines(content, end + 1, after_end) if end < total else ""

    parts = [
        f"## Instruction\n{instruction}\n",
        f"## File Info\n- Path: {file_path}\n- Language: {lang}\n",
        context_section,
        f"## Selected Region (lines {start}-{end})",
        "Edit ONLY this content and return the complete replacement:\n",
        f"```{lang}\n{selected_text}\n```\n",
    ]

    if before_text or after_text:
        parts.append(
            "## Surrounding Context (read-only, for reference only -- "
            "do NOT include in output)"
        )
        if before_text:
            parts.append(
                f"### Before selection (lines {before_start}-{start - 1}):\n"
                f"```\n{before_text}\n```\n"
            )
        if after_text:
            parts.append(
                f"### After selection (lines {end + 1}-{after_end}):\n"
                f"```\n{after_text}\n```\n"
            )

    return "\n".join(parts)


def _build_whole_file_prompt(
    instruction: str,
    file_path: str,
    lang: str,
    content: str,
    context_section: str,
) -> str:
    """Build a prompt for editing an entire file."""
    return "\n".join([
        f"## Instruction\n{instruction}\n",
        f"## File Info\n- Path: {file_path}\n- Language: {lang}\n",
        context_section,
        "## Full File Content",
        "Edit this file and return the complete updated content:\n",
        f"```{lang}\n{content}\n```",
    ])


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------


def generate_diff(original: str, proposed: str) -> str:
    """Generate a unified diff between original and proposed content.

    Parameters
    ----------
    original : str
        Original content.
    proposed : str
        Proposed (edited) content.

    Returns
    -------
    str
        Unified diff string.
    """
    return "\n".join(
        unified_diff(
            original.splitlines(),
            proposed.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )