"""Host-local CLI-backed synthetic Main Models.

Two options in the chat UI:

1. ``local/gemini-rag``  → ``gemini-rag-query --detailed --reformulate --duckie``
   optional query rewrite + concurrent duckie + moma discovery → parallel URL
   reads → Gemini synthesis (+ FAQ/next expand). Broad internal-doc RAG; slower;
   citations.

2. ``local/gemini-agent`` → ``gemini-agent-query ask`` with a **fast depth-2**
   profile: ``--max-depth 2 --personas 0 --max-loops 2 --max-tool-iterations 4
   --loop-mode direct-retry --budget 20 --history-window 2``.
   ReAct-style agent over internal tools; lighter/faster than full GAQ defaults.

Both keep lean context: **user question + running summary only** (no full
history dump, no tools from the chat agent loop, no OpenRouter fallback).

Env kill-switches / paths:
  GEMINI_RAG_SCRIPT_PATH / GEMINI_RAG_DISABLED / GEMINI_RAG_TIMEOUT /
  GEMINI_RAG_MAX_URLS (passed as --max-urls, clamped 1–20 by the CLI)
  GEMINI_AGENT_SCRIPT_PATH / GEMINI_AGENT_DISABLED / GEMINI_AGENT_TIMEOUT
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared synthetic ids
# ---------------------------------------------------------------------------

GEMINI_RAG_MODEL = "local/gemini-rag"
GEMINI_AGENT_MODEL = "local/gemini-agent"

GEMINI_RAG_MODEL_ALIASES = (
    GEMINI_RAG_MODEL,
    "gemini-rag-query",
    "Gemini RAG",
    "Gemini RAG (detailed)",
    "Gemini-RAG",
)

GEMINI_AGENT_MODEL_ALIASES = (
    GEMINI_AGENT_MODEL,
    "gemini-agent-query",
    "Gemini Agent",
    "Gemini Agent (fast)",
    "Gemini-Agent",
    "local/gemini-agent-query",
)

# ---------------------------------------------------------------------------
# Host gating
# ---------------------------------------------------------------------------

GEMINI_RAG_SCRIPT_PATH = os.environ.get(
    "GEMINI_RAG_SCRIPT_PATH",
    os.path.expanduser("~/.local/bin/gemini-rag-query"),
)
GEMINI_AGENT_SCRIPT_PATH = os.environ.get(
    "GEMINI_AGENT_SCRIPT_PATH",
    os.path.expanduser("~/.local/bin/gemini-agent-query"),
)

GEMINI_RAG_AVAILABLE = (
    os.environ.get("GEMINI_RAG_DISABLED", "").strip().lower() not in ("1", "true", "yes")
    and os.path.isfile(GEMINI_RAG_SCRIPT_PATH)
    and os.access(GEMINI_RAG_SCRIPT_PATH, os.X_OK)
)
GEMINI_AGENT_AVAILABLE = (
    os.environ.get("GEMINI_AGENT_DISABLED", "").strip().lower()
    not in ("1", "true", "yes")
    and os.path.isfile(GEMINI_AGENT_SCRIPT_PATH)
    and os.access(GEMINI_AGENT_SCRIPT_PATH, os.X_OK)
)

_RAG_DEFAULT_TIMEOUT = int(os.environ.get("GEMINI_RAG_TIMEOUT", "600"))
_AGENT_DEFAULT_TIMEOUT = int(os.environ.get("GEMINI_AGENT_TIMEOUT", "420"))
# Primary moma fan-out for chat-model path (CLI clamps 1..20).
_RAG_DEFAULT_MAX_URLS = int(os.environ.get("GEMINI_RAG_MAX_URLS", "20"))


# ---------------------------------------------------------------------------
# Model name helpers
# ---------------------------------------------------------------------------

def is_gemini_rag_model(model_name: Optional[str]) -> bool:
    if not model_name or not isinstance(model_name, str):
        return False
    name = model_name.strip()
    if name in GEMINI_RAG_MODEL_ALIASES:
        return True
    lower = name.lower()
    return lower in {a.lower() for a in GEMINI_RAG_MODEL_ALIASES} or lower.endswith(
        "/gemini-rag"
    )


def is_gemini_agent_model(model_name: Optional[str]) -> bool:
    if not model_name or not isinstance(model_name, str):
        return False
    name = model_name.strip()
    if name in GEMINI_AGENT_MODEL_ALIASES:
        return True
    lower = name.lower()
    return lower in {a.lower() for a in GEMINI_AGENT_MODEL_ALIASES} or lower.endswith(
        "/gemini-agent"
    ) or lower.endswith("/gemini-agent-query")


def is_local_cli_model(model_name: Optional[str]) -> bool:
    """True for any host-CLI synthetic model that must not OpenRouter-fallback."""
    return is_gemini_rag_model(model_name) or is_gemini_agent_model(model_name)


def canonicalize_local_cli_model(model_name: str) -> str:
    if is_gemini_rag_model(model_name):
        return GEMINI_RAG_MODEL
    if is_gemini_agent_model(model_name):
        return GEMINI_AGENT_MODEL
    return model_name


# Back-compat exports used by earlier gemini_rag_llm.py wiring
canonicalize_gemini_rag_model = lambda m: (  # noqa: E731
    GEMINI_RAG_MODEL if is_gemini_rag_model(m) else m
)


# ---------------------------------------------------------------------------
# Lean context assembly (query + summary only)
# ---------------------------------------------------------------------------

def _messages_to_text_parts(
    messages: Optional[List[Dict[str, Any]]],
) -> Tuple[str, str]:
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
    return "\n\n".join(user_chunks).strip(), "\n\n".join(system_chunks).strip()


_SUMMARY_MARKERS = (
    "running summary",
    "conversation summary",
    "previous summary",
    "summary of the conversation",
    "summarized history",
)


def _extract_summary_from_system(system: Optional[str]) -> str:
    if not system or not isinstance(system, str):
        return ""
    text = system.strip()
    if not text:
        return ""
    lower = text.lower()
    for marker in _SUMMARY_MARKERS:
        idx = lower.find(marker)
        if idx >= 0:
            snippet = text[idx : idx + 2500]
            cut = re.search(r"\n\s*\n[A-Z#<\[]", snippet[80:])
            if cut:
                snippet = snippet[: 80 + cut.start()]
            return snippet.strip()
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
    """Single string for host CLIs: question + optional compressed summary."""
    msg_user, msg_system = _messages_to_text_parts(messages)
    question = (msg_user or text or "").strip()
    if "\n\n" in question and len(question) > 800:
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
        question = _trim(summary or "(empty query)", max_query_chars)
        summary = ""

    if summary:
        return (
            f"{question}\n\n"
            f"Conversation context (compressed summary — use only if relevant "
            f"to the question above):\n{summary}"
        )
    return question


def _chunk_text(text: str, chunk_size: int = 480) -> Iterable[str]:
    if not text:
        return
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


def _strip_debug_noise(stdout: str) -> str:
    lines = []
    for ln in (stdout or "").replace("\r", "").splitlines():
        if ln.startswith("main_prompt_bytes="):
            continue
        if ln.startswith('{"n_faq"') or ln.startswith('{"n_questions"'):
            continue
        lines.append(ln)
    return "\n".join(lines).strip() or (stdout or "").strip()


# ---------------------------------------------------------------------------
# CLI invokers
# ---------------------------------------------------------------------------

def run_gemini_rag_query(
    query: str,
    *,
    detailed: bool = True,
    reformulate: bool = True,
    duckie: bool = True,
    timeout: Optional[int] = None,
    no_cache: bool = False,
    max_urls: Optional[int] = None,
    script_path: Optional[str] = None,
) -> str:
    """Run host ``gemini-rag-query``.

    Chat UI path defaults ``reformulate=True`` and ``duckie=True`` so discovery
    uses a short rewritten search query and adds duckie_cli as a second source.
    Both are still bare CLI flags; only this wrapper opts them on by default.
    """
    binary = script_path or GEMINI_RAG_SCRIPT_PATH
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise RuntimeError(
            f"gemini-rag-query is not available on this host "
            f"(looked for executable at {binary}). "
            f"Install the CLI or set GEMINI_RAG_SCRIPT_PATH."
        )
    timeout_s = int(timeout if timeout is not None else _RAG_DEFAULT_TIMEOUT)
    n_urls = int(max_urls if max_urls is not None else _RAG_DEFAULT_MAX_URLS)
    if n_urls < 1:
        n_urls = 1
    if n_urls > 20:
        n_urls = 20
    cmd: List[str] = [binary]
    if detailed:
        cmd.append("--detailed")
    if reformulate:
        cmd.append("--reformulate")
    if duckie:
        cmd.append("--duckie")
    if no_cache:
        cmd.append("-n")
    cmd.extend(["--max-urls", str(n_urls)])
    cmd.append(query)

    logger.info(
        "gemini-rag-query invoke | detailed=%s reformulate=%s duckie=%s "
        "max_urls=%s timeout=%ss query_chars=%d",
        detailed,
        reformulate,
        duckie,
        n_urls,
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
        raise RuntimeError(f"gemini-rag-query timed out after {timeout_s}s") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"gemini-rag-query binary not found: {binary}") from e

    stdout = (proc.stdout or "").replace("\r", "")
    stderr = (proc.stderr or "").replace("\r", "")
    if proc.returncode != 0:
        if stdout.strip():
            logger.warning(
                "gemini-rag-query rc=%s but stdout present (%dB); returning it. stderr=%s",
                proc.returncode,
                len(stdout),
                stderr[-500:],
            )
            return _strip_debug_noise(stdout)
        raise RuntimeError(
            f"gemini-rag-query failed (rc={proc.returncode}): "
            f"{(stderr or stdout)[-1500:]}"
        )
    return _strip_debug_noise(stdout)


def run_gemini_agent_query(
    query: str,
    *,
    timeout: Optional[int] = None,
    max_depth: int = 2,
    personas: int = 0,
    max_loops: int = 2,
    max_tool_iterations: int = 4,
    loop_mode: str = "direct-retry",
    budget: int = 20,
    history_window: int = 2,
    script_path: Optional[str] = None,
) -> str:
    """Fast gemini-agent-query profile: depth-2, no personas, small budget."""
    binary = script_path or GEMINI_AGENT_SCRIPT_PATH
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise RuntimeError(
            f"gemini-agent-query is not available on this host "
            f"(looked for executable at {binary}). "
            f"Install the CLI or set GEMINI_AGENT_SCRIPT_PATH."
        )
    timeout_s = int(timeout if timeout is not None else _AGENT_DEFAULT_TIMEOUT)
    # "ask" subcommand; fast profile flags first so positional query is last.
    cmd: List[str] = [
        binary,
        "ask",
        "--new-session",
        "--max-depth",
        str(int(max_depth)),
        "--personas",
        str(int(personas)),
        "--max-loops",
        str(int(max_loops)),
        "--max-tool-iterations",
        str(int(max_tool_iterations)),
        "--loop-mode",
        str(loop_mode),
        "--budget",
        str(int(budget)),
        "--history-window",
        str(int(history_window)),
        "--synth-backend",
        "gemini",
        query,
    ]
    logger.info(
        "gemini-agent-query invoke | depth=%s personas=%s loops=%s tools=%s "
        "budget=%s timeout=%ss query_chars=%d",
        max_depth,
        personas,
        max_loops,
        max_tool_iterations,
        budget,
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
        raise RuntimeError(f"gemini-agent-query timed out after {timeout_s}s") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"gemini-agent-query binary not found: {binary}") from e

    stdout = (proc.stdout or "").replace("\r", "")
    stderr = (proc.stderr or "").replace("\r", "")
    if proc.returncode != 0:
        if stdout.strip():
            logger.warning(
                "gemini-agent-query rc=%s but stdout present (%dB); returning it. stderr=%s",
                proc.returncode,
                len(stdout),
                stderr[-500:],
            )
            return _strip_debug_noise(stdout)
        raise RuntimeError(
            f"gemini-agent-query failed (rc={proc.returncode}): "
            f"{(stderr or stdout)[-1500:]}"
        )
    return _strip_debug_noise(stdout)


# ---------------------------------------------------------------------------
# call_llm-compatible entry points
# ---------------------------------------------------------------------------

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
    del keys, images, temperature, tools, tool_choice
    if not is_gemini_rag_model(model_name):
        raise ValueError(f"not a gemini-rag model: {model_name}")
    if not GEMINI_RAG_AVAILABLE:
        msg = (
            "Gemini RAG model is selected but the gemini-rag-query CLI is not "
            f"available on this host (expected at {GEMINI_RAG_SCRIPT_PATH}). "
            "Install it under ~/.local/bin or set GEMINI_RAG_SCRIPT_PATH, "
            "or pick a different main model."
        )
        return (c for c in [msg]) if stream else msg

    query = build_lean_query(text=text, system=system, messages=messages)
    answer = run_gemini_rag_query(query, detailed=True, max_urls=_RAG_DEFAULT_MAX_URLS)
    if not stream:
        return answer

    def _gen() -> Generator[str, None, None]:
        for chunk in _chunk_text(answer):
            yield chunk

    return _gen()


def call_gemini_agent_llm(
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
    del keys, images, temperature, tools, tool_choice
    if not is_gemini_agent_model(model_name):
        raise ValueError(f"not a gemini-agent model: {model_name}")
    if not GEMINI_AGENT_AVAILABLE:
        msg = (
            "Gemini Agent model is selected but the gemini-agent-query CLI is not "
            f"available on this host (expected at {GEMINI_AGENT_SCRIPT_PATH}). "
            "Install it under ~/.local/bin or set GEMINI_AGENT_SCRIPT_PATH, "
            "or pick a different main model."
        )
        return (c for c in [msg]) if stream else msg

    query = build_lean_query(text=text, system=system, messages=messages)
    # Fast profile: depth 2, no persona fan-out, small call budget.
    answer = run_gemini_agent_query(
        query,
        max_depth=2,
        personas=0,
        max_loops=2,
        max_tool_iterations=4,
        loop_mode="direct-retry",
        budget=20,
        history_window=2,
    )
    if not stream:
        return answer

    def _gen() -> Generator[str, None, None]:
        for chunk in _chunk_text(answer):
            yield chunk

    return _gen()


def call_local_cli_llm(
    keys: Dict[str, str],
    model_name: str,
    **kwargs: Any,
) -> Union[str, Generator[str, None, None]]:
    """Dispatch helper for code_common.call_llm short-circuit."""
    if is_gemini_rag_model(model_name):
        return call_gemini_rag_llm(keys, model_name, **kwargs)
    if is_gemini_agent_model(model_name):
        return call_gemini_agent_llm(keys, model_name, **kwargs)
    raise ValueError(f"not a local CLI model: {model_name}")
