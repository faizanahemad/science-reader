"""Local ``gemini-rag-query`` model backend (host-gated CLI wrapper).

Selected in the chat UI as a Main Model option. Intentional lean context:
only the user question + optional running summary are sent to the CLI.
Full conversation history / system preambles / tools are ignored so the
CLI can run its own moma → parallel-read → Gemini RAG pipeline.

Public identifiers:
  * model id: ``local/gemini-rag`` (and display aliases)
  * binary: ``GEMINI_RAG_SCRIPT_PATH`` (default ``~/.local/bin/gemini-rag-query``)
  * kill-switch: ``GEMINI_RAG_DISABLED=1``
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Synthetic model id used in UI / CallLLm. Keep "local/" prefix so it cannot
# collide with OpenRouter provider IDs.
GEMINI_RAG_MODEL = "local/gemini-rag"

# Friendly UI labels that canonicalize to GEMINI_RAG_MODEL.
GEMINI_RAG_MODEL_ALIASES = (
    GEMINI_RAG_MODEL,
    "gemini-rag-query",
    "Gemini RAG",
    "Gemini RAG (detailed)",
    "Gemini-RAG",
)

GEMINI_RAG_SCRIPT_PATH = os.environ.get(
    "GEMINI_RAG_SCRIPT_PATH",
    os.path.expanduser("~/.local/bin/gemini-rag-query"),
)

# Host availability (binary present + executable, unless killed by env).
GEMINI_RAG_AVAILABLE = (
    os.environ.get("GEMINI_RAG_DISABLED", "").strip().lower() not in ("1", "true", "yes")
    and os.path.isfile(GEMINI_RAG_SCRIPT_PATH)
    and os.access(GEMINI_RAG_SCRIPT_PATH, os.X_OK)
)

# Default wall timeout for the whole CLI (moma + multi-read + expand + generate).
# Override with GEMINI_RAG_TIMEOUT seconds.
_DEFAULT_TIMEOUT = int(os.environ.get("GEMINI_RAG_TIMEOUT", "600"))


def is_gemini_rag_model(model_name: Optional[str]) -> bool:
    """True when ``model_name`` is the synthetic gemini-rag model (or alias)."""
    if not model_name or not isinstance(model_name, str):
        return False
    name = model_name.strip()
    if name in GEMINI_RAG_MODEL_ALIASES:
        return True
    # Tolerate accidental openrouter-style or trailing decorations.
    lower = name.lower()
    return lower in {a.lower() for a in GEMINI_RAG_MODEL_ALIASES} or lower.endswith(
        "/gemini-rag"
    )


def canonicalize_gemini_rag_model(model_name: str) -> str:
    """Map any accepted alias to the canonical synthetic id."""
    return GEMINI_RAG_MODEL if is_gemini_rag_model(model_name) else model_name


def _messages_to_text_parts(
    messages: Optional[List[Dict[str, Any]]],
) -> Tuple[str, str]:
    """Best-effort extract (user, summary) from an OpenAI-style messages list."""
    if not messages:
        return "", ""
    user_chunks: List[str] = []
    system_chunks: List[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or "").lower()
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal content: only keep text parts.
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    texts.append(part)
            content = "\n".join(t for t in texts if t)
        if not isinstance(content, str):
            content = str(content or "")
        content = content.strip()
        if not content:
            continue
        if role == "system":
            system_chunks.append(content)
        elif role == "user":
            user_chunks.append(content)
        # assistant turns intentionally ignored for this lean backend
    return "\n\n".join(user_chunks).strip(), "\n\n".join(system_chunks).strip()


_SUMMARY_MARKERS = (
    "running summary",
    "conversation summary",
    "previous summary",
    "summary of the conversation",
    "summarized history",
)


def _extract_summary_from_system(system: Optional[str]) -> str:
    """Pull a small summary snippet out of a large system/preamble if present."""
    if not system or not isinstance(system, str):
        return ""
    text = system.strip()
    if not text:
        return ""
    lower = text.lower()
    # Prefer explicitly marked section already labeled as summary.
    for marker in _SUMMARY_MARKERS:
        idx = lower.find(marker)
        if idx >= 0:
            # Take from marker to next double-newline section or 2500 chars.
            snippet = text[idx : idx + 2500]
            # cut at a subsequent clear section boundary if present
            cut = re.search(r"\n\s*\n[A-Z#<\[]", snippet[80:])
            if cut:
                snippet = snippet[: 80 + cut.start()]
            return snippet.strip()
    # Last resort: keep a short head+tail window of the system prompt as weak context.
    if len(text) <= 1500:
        return text
    return (text[:900] + "\n...\n" + text[-500:]).strip()


def _trim(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    head = max_chars * 2 // 3
    tail = max_chars - head - 20
    return s[:head] + "\n...\n" + s[-tail:]


def build_lean_query(
    text: str = "",
    system: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    max_query_chars: int = 4000,
    max_summary_chars: int = 2500,
) -> str:
    """Build the single string passed to ``gemini-rag-query``.

    Preference order for the question:
      1. last user content from ``messages``
      2. ``text``
    Preference order for optional summary context:
      1. system messages from ``messages`` (short)
      2. ``system`` argument (marker-extracted / truncated)

    Concats as:

        <question>

        Conversation context (compressed summary):
        <summary>
    """
    msg_user, msg_system = _messages_to_text_parts(messages)
    question = (msg_user or text or "").strip()
    # Prefer the last user paragraph if multi-turn junk snuck in.
    if "\n\n" in question and len(question) > 800:
        # Keep last ~2 non-empty paragraphs for multi-turn collapse.
        paras = [p.strip() for p in question.split("\n\n") if p.strip()]
        if len(paras) > 2:
            question = "\n\n".join(paras[-2:])
    question = _trim(question, max_query_chars)

    summary = ""
    if msg_system:
        summary = _trim(msg_system, max_summary_chars)
    if not summary:
        summary = _trim(_extract_summary_from_system(system), max_summary_chars)

    if not question:
        # Fall back: if only system arrived, still try something.
        question = _trim(summary or "(empty query)", max_query_chars)
        summary = ""

    if summary:
        return (
            f"{question}\n\n"
            f"Conversation context (compressed summary — use only if relevant "
            f"to the question above):\n{summary}"
        )
    return question


def run_gemini_rag_query(
    query: str,
    *,
    detailed: bool = True,
    timeout: Optional[int] = None,
    no_cache: bool = False,
    max_urls: Optional[int] = None,
    script_path: Optional[str] = None,
) -> str:
    """Invoke the ``gemini-rag-query`` CLI and return stdout (answer text)."""
    binary = script_path or GEMINI_RAG_SCRIPT_PATH
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise RuntimeError(
            f"gemini-rag-query is not available on this host "
            f"(looked for executable at {binary}). "
            f"Install the CLI or set GEMINI_RAG_SCRIPT_PATH."
        )
    timeout_s = int(timeout if timeout is not None else _DEFAULT_TIMEOUT)
    cmd: List[str] = [binary]
    if detailed:
        cmd.append("--detailed")
    if no_cache:
        cmd.append("-n")
    if max_urls is not None and int(max_urls) > 0:
        cmd.extend(["--max-urls", str(int(max_urls))])
    cmd.append(query)

    logger.info(
        "gemini-rag-query invoke | detailed=%s timeout=%ss query_chars=%d",
        detailed,
        timeout_s,
        len(query),
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 30,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"gemini-rag-query timed out after {timeout_s}s"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            f"gemini-rag-query binary not found: {binary}"
        ) from e

    stdout = (proc.stdout or "").replace("\r", "")
    stderr = (proc.stderr or "").replace("\r", "")
    if proc.returncode != 0:
        # Prefer stdout if it has content (partial answer); else raise with stderr.
        if stdout.strip():
            logger.warning(
                "gemini-rag-query rc=%s but stdout present (%dB); returning it. stderr=%s",
                proc.returncode,
                len(stdout),
                stderr[-500:],
            )
            return stdout
        raise RuntimeError(
            f"gemini-rag-query failed (rc={proc.returncode}): "
            f"{(stderr or stdout)[-1500:]}"
        )
    # Strip known debug noise that might leak.
    lines = []
    for ln in stdout.splitlines():
        if ln.startswith("main_prompt_bytes="):
            continue
        if ln.startswith('{"n_faq"') or ln.startswith('{"n_questions"'):
            continue
        lines.append(ln)
    return "\n".join(lines).strip() or stdout.strip()


def _chunk_text(text: str, chunk_size: int = 480) -> Iterable[str]:
    """Yield moderately sized chunks so chat UI streaming feels progressive."""
    if not text:
        return
    # Prefer paragraph boundaries when possible.
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            yield remaining
            return
        cut = remaining.rfind("\n\n", 0, chunk_size)
        if cut < chunk_size // 3:
            cut = remaining.rfind("\n", 0, chunk_size)
        if cut < chunk_size // 3:
            cut = chunk_size
        yield remaining[:cut]
        remaining = remaining[cut:]
        if remaining.startswith("\n"):
            # keep a single leading newline with the next chunk for spacing
            pass


def call_gemini_rag_llm(
    keys: Dict[str, str],
    model_name: str,
    text: str = "",
    images: Optional[List[str]] = None,
    temperature: float = 0.7,
    stream: bool = False,
    system: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Any = None,
    tool_choice: Any = None,
) -> Union[str, Generator[str, None, None]]:
    """``call_llm``-compatible entry point for the synthetic model.

    ``keys``, ``images``, ``temperature``, ``tools`` are accepted for signature
    parity with OpenRouter calls and intentionally unused (this backend is CLI
    RAG, not tool-loop OpenRouter).
    """
    del keys, images, temperature, tools, tool_choice  # signature parity only
    if not is_gemini_rag_model(model_name):
        raise ValueError(f"not a gemini-rag model: {model_name}")
    if not GEMINI_RAG_AVAILABLE:
        msg = (
            "Gemini RAG model is selected but the gemini-rag-query CLI is not "
            f"available on this host (expected at {GEMINI_RAG_SCRIPT_PATH}). "
            "Install it under ~/.local/bin or set GEMINI_RAG_SCRIPT_PATH, "
            "or pick a different main model."
        )
        if stream:
            return (c for c in [msg])
        return msg

    query = build_lean_query(text=text, system=system, messages=messages)
    # Always detailed per product request for the UI model option.
    answer = run_gemini_rag_query(query, detailed=True)

    if not stream:
        return answer

    def _gen() -> Generator[str, None, None]:
        for chunk in _chunk_text(answer):
            yield chunk

    return _gen()
