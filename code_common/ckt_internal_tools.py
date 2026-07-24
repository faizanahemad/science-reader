"""Subprocess-isolated adapters for selected Corp Knowledge Tools façades.

All binaries resolve under one optional ``INTERNAL_TOOLS_PATH`` root. The chat
process never imports Corp Knowledge Tools runtime code: each call is an argv
subprocess and has a hard 120-second outer deadline.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "ckt_internal_tools",
    logger_level=10,
    time_logger_level=10,
)

INTERNAL_TOOLS_PATH_ENV = "INTERNAL_TOOLS_PATH"
INTERNAL_TOOL_TIMEOUT_SECONDS = 120

_BINARY_NAMES = frozenset({
    "ckt-jetski-query",
    "ckt-internal-kb",
    "ckt-moma-bm25-read",
    "ckt-system-flow-research",
    "ckt-code-trace",
    "ckt-duckie-retrieval-query",
    "ckt-gdocs-readonly",
})

CKT_INTERNAL_TOOL_NAMES = frozenset({
    "read_url",
    "moma_search",
    "moma_bm25_read",
    "yaqs_search",
    "code_search_standard",
    "kb_search",
    "system_flow_research",
    "code_trace",
    "duckie_search",
    "ckt_duckie_retrieval",
    "gdocs_readonly",
})


def internal_tools_root(configured_root: str | None = None) -> Path | None:
    """Return the configured Corp Knowledge Tools root, or ``None`` when unset."""
    value = configured_root if configured_root is not None else os.environ.get(INTERNAL_TOOLS_PATH_ENV, "")
    value = (value or "").strip()
    return Path(value).expanduser() if value else None


def internal_tool_binary(binary_name: str, configured_root: str | None = None) -> Path | None:
    """Resolve one approved CKT binary below the single configured root."""
    if binary_name not in _BINARY_NAMES:
        raise ValueError(f"unsupported CKT binary: {binary_name}")
    root = internal_tools_root(configured_root)
    return root / "bin" / binary_name if root else None


def is_ckt_internal_tools_available(configured_root: str | None = None) -> bool:
    """True only when the configured root contains every required executable."""
    root = internal_tools_root(configured_root)
    return bool(root and all(os.access(root / "bin" / name, os.X_OK) for name in _BINARY_NAMES))


def _nonempty_strings(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()][:limit]


def _required_string(args: dict, key: str, tool_name: str) -> str:
    value = str(args.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"{tool_name}: {key} is required.")
    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def build_ckt_command(tool_name: str, args: dict, configured_root: str | None = None) -> list[str]:
    """Build argv for one direct CKT façade without shell interpolation."""
    if tool_name not in CKT_INTERNAL_TOOL_NAMES:
        raise ValueError(f"unsupported CKT tool: {tool_name}")
    args = args if isinstance(args, dict) else {}

    def binary(name: str) -> str:
        path = internal_tool_binary(name, configured_root)
        if path is None or not os.access(path, os.X_OK):
            raise FileNotFoundError(f"required CKT executable unavailable: {path}")
        return str(path)

    if tool_name == "read_url":
        urls = _nonempty_strings(args.get("urls") or args.get("url"), limit=8)
        if not urls:
            raise ValueError("read_url: urls is required.")
        command = [binary("ckt-jetski-query"), "--json"]
        for url in urls:
            command.extend(["--read", url])
        return command
    if tool_name == "moma_search":
        return [binary("ckt-jetski-query"), "--json", "--moma", _required_string(args, "query", tool_name)]
    if tool_name == "yaqs_search":
        return [binary("ckt-jetski-query"), "--json", "--yaqs", _required_string(args, "query", tool_name)]
    if tool_name == "code_search_standard":
        command = [binary("ckt-jetski-query"), "--json", "--cs"]
        directory = str(args.get("directory", "") or "").strip()
        if directory:
            command.extend(["--dir", directory])
        command.append(_required_string(args, "query", tool_name))
        return command
    if tool_name == "kb_search":
        count = _bounded_int(args.get("max_results"), default=5, minimum=1, maximum=20)
        return [binary("ckt-internal-kb"), "search", _required_string(args, "query", tool_name), "-n", str(count)]
    if tool_name == "moma_bm25_read":
        queries = _nonempty_strings(args.get("queries") or args.get("query"), limit=6)
        if not queries:
            raise ValueError("moma_bm25_read: queries is required.")
        command = [binary("ckt-moma-bm25-read"), "--timeout", str(INTERNAL_TOOL_TIMEOUT_SECONDS)]
        if bool(args.get("crawl", False)):
            command.append("--crawl")
        for arg_name, flag, default, maximum in (
            ("max_urls_per_query", "--max-urls-per-query", 8, 20),
            ("top_chunks_per_page", "--top-chunks-per-page", 5, 20),
        ):
            if arg_name in args:
                command.extend([flag, str(_bounded_int(args.get(arg_name), default=default, minimum=1, maximum=maximum))])
        command.extend(queries)
        return command
    if tool_name == "system_flow_research":
        return [binary("ckt-system-flow-research"), _required_string(args, "query", tool_name)]
    if tool_name == "code_trace":
        question = _required_string(args, "question", tool_name)
        symbols = list(dict.fromkeys(_nonempty_strings(args.get("symbols"), limit=4)))
        if not symbols:
            raise ValueError("code_trace: symbols is required.")
        command = [binary("ckt-code-trace")]
        directory = str(args.get("directory", "") or "").strip()
        if directory:
            command.extend(["--directory", directory])
        return command + [question] + symbols
    if tool_name == "duckie_search":
        return [binary("ckt-jetski-query"), "--json", "--duckie", _required_string(args, "query", tool_name)]
    if tool_name == "gdocs_readonly":
        command = [binary("ckt-gdocs-readonly"), "read", _required_string(args, "document_id", tool_name)]
        tab_id = str(args.get("tab_id", "") or "").strip()
        if tab_id:
            command.extend(["--tab", tab_id])
        return command

    query_count = _bounded_int(args.get("query_count"), default=5, minimum=1, maximum=6)
    return [
        binary("ckt-duckie-retrieval-query"),
        "--query-count", str(query_count),
        "--timeout", str(INTERNAL_TOOL_TIMEOUT_SECONDS),
        _required_string(args, "query", tool_name),
    ]


def _clean_output(output: str) -> str:
    return "\n".join(
        line for line in (output or "").replace("\r", "").splitlines()
        if not line.strip().startswith(("Shared connection to ", "Connection to "))
    ).strip()


def run_ckt_command(tool_name: str, args: dict, configured_root: str | None = None):
    """Run one CKT tool with the uniform 120-second deadline and fail-open result."""
    from code_common.tools import ToolCallResult
    try:
        command = build_ckt_command(tool_name, args, configured_root)
    except (ValueError, FileNotFoundError) as exc:
        return ToolCallResult(tool_id="", tool_name=tool_name, result="", error=str(exc))

    logger.info("%s invoked via CKT subprocess; argv_count=%d timeout=%ds", tool_name, len(command), INTERNAL_TOOL_TIMEOUT_SECONDS)
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=INTERNAL_TOOL_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result="",
            error=f"{tool_name} timed out after {INTERNAL_TOOL_TIMEOUT_SECONDS}s.",
        )
    except OSError as exc:
        return ToolCallResult(tool_id="", tool_name=tool_name, result="", error=f"{tool_name} failed to start: {exc}")

    stdout = _clean_output(process.stdout)
    if process.returncode == 0 and stdout:
        return ToolCallResult(tool_id="", tool_name=tool_name, result=stdout)

    stderr_tail = _clean_output(process.stderr)[-1000:]
    if stdout:
        return ToolCallResult(
            tool_id="", tool_name=tool_name, result=stdout,
            error=f"{tool_name} exited with code {process.returncode}; inspect the returned partial result.",
        )
    return ToolCallResult(
        tool_id="", tool_name=tool_name, result="",
        error=f"{tool_name} exited with code {process.returncode}: {stderr_tail or '(no output)'}",
    )


def compact_json_result(result):
    """Canonicalize valid JSON output without changing non-JSON tool results."""
    if result.error or not result.result:
        return result
    try:
        result.result = json.dumps(
            json.loads(result.result), ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError):
        pass
    return result
