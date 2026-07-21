"""Unit tests for the subprocess-isolated CKT internal-tool adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from code_common.ckt_internal_tools import (
    CKT_INTERNAL_TOOL_NAMES,
    INTERNAL_TOOL_TIMEOUT_SECONDS,
    build_ckt_command,
    is_ckt_internal_tools_available,
    run_ckt_command,
)


def test_ckt_workflow_hint_contains_latency_parallelism_and_depth_policy():
    from code_common.tools import build_ckt_tool_workflow_hint

    hint = build_ckt_tool_workflow_hint(CKT_INTERNAL_TOOL_NAMES)
    for required_text in (
        "Very Fast (<10s average)",
        "Fast: `moma_bm25_read` — ~15s average",
        "Medium Speed (average 45s)",
        "`system_flow_research` — ~20s average",
        "`duckie_search` — ~45s average",
        "`ckt_duckie_retrieval` — ~60s average",
        "independent calls in PARALLEL",
        "at least two retrieval rounds",
        "one round is acceptable only",
        "urgency or shorter answers",
    ):
        assert required_text in hint


def _write_executable(path: Path, body: str = "#!/bin/sh\nprintf '%s\\n' ok\n") -> None:
    path.write_text(body)
    path.chmod(0o755)


def _tool_root(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for binary in (
        "ckt-jetski-query",
        "ckt-internal-kb",
        "ckt-moma-bm25-read",
        "ckt-system-flow-research",
        "ckt-code-trace",
        "ckt-duckie-retrieval-query",
    ):
        _write_executable(bin_dir / binary)
    return tmp_path


def test_available_only_when_single_root_contains_all_required_executables(tmp_path):
    root = _tool_root(tmp_path)
    assert is_ckt_internal_tools_available(str(root))

    (root / "bin" / "ckt-code-trace").unlink()
    assert not is_ckt_internal_tools_available(str(root))


def test_builds_direct_cli_commands_with_bounded_inner_deadlines(tmp_path):
    root = _tool_root(tmp_path)

    assert build_ckt_command("moma_bm25_read", {"queries": ["one", "two"], "timeout_seconds": 999}, str(root)) == [
        str(root / "bin" / "ckt-moma-bm25-read"), "--timeout", "120", "one", "two",
    ]
    assert build_ckt_command("read_url", {"urls": ["http://go/one", "http://go/two"]}, str(root)) == [
        str(root / "bin" / "ckt-jetski-query"), "--json", "--read", "http://go/one", "--read", "http://go/two",
    ]
    assert build_ckt_command("code_search_standard", {"query": "ExampleSymbol"}, str(root)) == [
        str(root / "bin" / "ckt-jetski-query"), "--json", "--cs", "ExampleSymbol",
    ]
    assert build_ckt_command("code_trace", {"question": "trace packet", "symbols": ["A", "A", "B"], "directory": "search/next"}, str(root)) == [
        str(root / "bin" / "ckt-code-trace"), "--directory", "search/next", "trace packet", "A", "B",
    ]
    assert build_ckt_command("ckt_duckie_retrieval", {"query": "What is AIO?", "query_count": 99}, str(root)) == [
        str(root / "bin" / "ckt-duckie-retrieval-query"), "--query-count", "6", "--timeout", "120", "What is AIO?",
    ]


def test_runner_uses_exact_120_second_outer_timeout_and_returns_compact_json(tmp_path, monkeypatch):
    root = _tool_root(tmp_path)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, '{"tool":"duckie_retrieval","results":[]}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_ckt_command("ckt_duckie_retrieval", {"query": "q"}, str(root))

    assert captured["timeout"] == INTERNAL_TOOL_TIMEOUT_SECONDS == 120
    assert captured["env"] is not None
    assert json.loads(result.result) == {"tool": "duckie_retrieval", "results": []}
    assert result.error is None


def test_runner_reports_timeout_without_raising(tmp_path, monkeypatch):
    root = _tool_root(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_ckt_command("system_flow_research", {"query": "q"}, str(root))

    assert result.error == "system_flow_research timed out after 120s."
    assert result.result == ""


@pytest.mark.parametrize("tool_name", sorted(CKT_INTERNAL_TOOL_NAMES))
def test_all_requested_tools_have_a_direct_command_contract(tool_name, tmp_path):
    root = _tool_root(tmp_path)
    minimal_args = {
        "read_url": {"urls": ["http://go/example"]},
        "moma_search": {"query": "example"},
        "moma_bm25_read": {"queries": ["example"]},
        "yaqs_search": {"query": "example"},
        "code_search_standard": {"query": "ExampleSymbol"},
        "kb_search": {"query": "example"},
        "system_flow_research": {"query": "How does example work?"},
        "code_trace": {"question": "trace", "symbols": ["ExampleSymbol"]},
        "duckie_search": {"query": "example"},
        "ckt_duckie_retrieval": {"query": "example"},
    }
    assert build_ckt_command(tool_name, minimal_args[tool_name], str(root))[0].startswith(str(root / "bin"))
