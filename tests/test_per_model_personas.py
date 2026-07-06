"""Tests for per-model persona plumbing (Phase 1: system-as-list).

Covers:
  1. ``stream_multiple_models`` accepts ``system`` as a list and routes each
     per-index system prompt to the matching model instance (and still accepts a
     single str broadcast + validates length).
  2. ``code_common.personas`` resolution helpers (suffix/label/compose/headers).
  3. ``CallMultipleLLM`` forwards per-model ``systems`` + ``header_template``.

These tests mock ``call_llm.CallLLm`` so no live API keys are needed. Run with:
    python -m pytest tests/test_per_model_personas.py -v -s
    python tests/test_per_model_personas.py
"""

import os
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RecordingCallLLm:
    """Mock CallLLm that records the ``system`` it was called with, keyed by model."""

    # Class-level registry so the test can inspect calls across instances.
    calls = {}  # model_name -> list of system prompts seen
    _lock = threading.Lock()

    def __init__(self, keys, model_name, *args, **kwargs):
        self.keys = keys
        self.model_name = model_name

    def __call__(
        self,
        prompt,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        with RecordingCallLLm._lock:
            RecordingCallLLm.calls.setdefault(self.model_name, []).append(system)
        # Minimal streaming response.
        def _gen():
            yield f"[{self.model_name}] ok. "
        return _gen()

    @classmethod
    def reset(cls):
        with cls._lock:
            cls.calls = {}


# ---------------------------------------------------------------------------
# 1. stream_multiple_models: system as list
# ---------------------------------------------------------------------------

def test_system_list_routes_per_model():
    from common import stream_multiple_models

    RecordingCallLLm.reset()
    keys = {"openAIKey": "test"}
    model_names = ["model-a", "model-b", "model-c"]
    prompts = ["p", "p", "p"]  # identical prompt (personas live in system)
    systems = ["SYS-A", "SYS-B", "SYS-C"]

    with patch("call_llm.CallLLm", RecordingCallLLm):
        list(stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            system=systems,
            collapsible_headers=True,
        ))

    assert RecordingCallLLm.calls.get("model-a") == ["SYS-A"], RecordingCallLLm.calls
    assert RecordingCallLLm.calls.get("model-b") == ["SYS-B"], RecordingCallLLm.calls
    assert RecordingCallLLm.calls.get("model-c") == ["SYS-C"], RecordingCallLLm.calls
    print("PASSED: test_system_list_routes_per_model")


def test_system_str_broadcasts():
    from common import stream_multiple_models

    RecordingCallLLm.reset()
    keys = {"openAIKey": "test"}
    model_names = ["m1", "m2"]
    prompts = ["p", "p"]

    with patch("call_llm.CallLLm", RecordingCallLLm):
        list(stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            system="SHARED",
            collapsible_headers=True,
        ))

    assert RecordingCallLLm.calls.get("m1") == ["SHARED"]
    assert RecordingCallLLm.calls.get("m2") == ["SHARED"]
    print("PASSED: test_system_str_broadcasts")


def test_system_none_default():
    from common import stream_multiple_models

    RecordingCallLLm.reset()
    with patch("call_llm.CallLLm", RecordingCallLLm):
        list(stream_multiple_models(
            keys={"openAIKey": "test"},
            model_names=["m1", "m2"],
            prompts=["p", "p"],
            collapsible_headers=True,
        ))
    assert RecordingCallLLm.calls.get("m1") == [None]
    assert RecordingCallLLm.calls.get("m2") == [None]
    print("PASSED: test_system_none_default")


def test_system_list_length_mismatch_raises():
    from common import stream_multiple_models

    with patch("call_llm.CallLLm", RecordingCallLLm):
        try:
            list(stream_multiple_models(
                keys={"openAIKey": "test"},
                model_names=["m1", "m2"],
                prompts=["p", "p"],
                system=["only-one"],
            ))
        except ValueError as e:
            assert "system prompts must match" in str(e)
            print("PASSED: test_system_list_length_mismatch_raises")
            return
    raise AssertionError("Expected ValueError for mismatched system list length")


def test_duplicate_models_get_distinct_systems():
    """Same model in two rows must still receive its own per-row system."""
    from common import stream_multiple_models

    RecordingCallLLm.reset()
    with patch("call_llm.CallLLm", RecordingCallLLm):
        list(stream_multiple_models(
            keys={"openAIKey": "test"},
            model_names=["dup", "dup"],
            prompts=["p", "p"],
            system=["SYS-1", "SYS-2"],
            collapsible_headers=True,
        ))
    seen = sorted(RecordingCallLLm.calls.get("dup", []))
    assert seen == ["SYS-1", "SYS-2"], seen
    print("PASSED: test_duplicate_models_get_distinct_systems")


# ---------------------------------------------------------------------------
# 2. persona helpers
# ---------------------------------------------------------------------------

def test_persona_helpers():
    from code_common.personas import (
        persona_suffix,
        persona_label,
        compose_system,
        header_for_row,
        build_systems_and_headers,
        PERSONA_LIBRARY,
        CUSTOM_PERSONA_MAX_CHARS,
    )

    # None / empty
    assert persona_suffix(None) == ""
    assert persona_suffix({"persona": "none"}) == ""
    assert persona_suffix({"persona": ""}) == ""
    assert persona_label({"persona": "none"}) == ""

    # Curated
    sk = {"persona": "skeptic"}
    assert persona_suffix(sk) == PERSONA_LIBRARY["skeptic"]["text"]
    assert persona_label(sk) == "Skeptic"
    assert header_for_row(sk) == "Response from {model} · Skeptic"
    assert header_for_row({"persona": "none"}) == "Response from {model}"

    # Unknown id -> treated as none (defensive)
    assert persona_suffix({"persona": "does-not-exist"}) == ""
    assert persona_label({"persona": "does-not-exist"}) == ""

    # Custom + cap
    long_text = "x" * (CUSTOM_PERSONA_MAX_CHARS + 200)
    row = {"persona": "custom", "custom_text": long_text}
    assert len(persona_suffix(row)) == CUSTOM_PERSONA_MAX_CHARS
    assert persona_label(row) == "Custom"
    # Custom with empty text -> no persona
    assert persona_suffix({"persona": "custom", "custom_text": "  "}) == ""
    assert persona_label({"persona": "custom", "custom_text": ""}) == ""

    # compose_system
    assert compose_system("BASE", None) == "BASE"
    assert compose_system("BASE", sk) == f"BASE\n\n{PERSONA_LIBRARY['skeptic']['text']}"
    assert compose_system(None, sk) == PERSONA_LIBRARY["skeptic"]["text"]

    # build_systems_and_headers
    rows = [
        {"model": "m1", "persona": "skeptic"},
        {"model": "m2", "persona": "none"},
    ]
    systems, headers = build_systems_and_headers(rows, base_system="BASE")
    assert systems[0] == f"BASE\n\n{PERSONA_LIBRARY['skeptic']['text']}"
    assert systems[1] == "BASE"
    assert headers == ["Response from {model} · Skeptic", "Response from {model}"]
    print("PASSED: test_persona_helpers")


# ---------------------------------------------------------------------------
# 3. CallMultipleLLM forwards systems + header_template
# ---------------------------------------------------------------------------

def test_call_multiple_llm_forwards_systems():
    from call_llm import CallMultipleLLM

    RecordingCallLLm.reset()
    keys = {"openAIKey": "test"}
    systems = ["PERSONA-A", "PERSONA-B"]

    with patch("call_llm.CallLLm", RecordingCallLLm):
        llm = CallMultipleLLM(
            keys,
            ["m1", "m2"],
            systems=systems,
            header_template=["Response from {model} · Skeptic", "Response from {model} · ELI5"],
        )
        out = "".join(llm("the question", [], 0.9, True, None, "IGNORED_SHARED"))

    # Per-model systems must win over the shared `system` arg.
    assert RecordingCallLLm.calls.get("m1") == ["PERSONA-A"], RecordingCallLLm.calls
    assert RecordingCallLLm.calls.get("m2") == ["PERSONA-B"], RecordingCallLLm.calls
    # Persona-aware headers should appear in the streamed output.
    assert "Response from m1 · Skeptic" in out or "Skeptic" in out, out[:400]
    print("PASSED: test_call_multiple_llm_forwards_systems")


def test_call_multiple_llm_backward_compat():
    """When systems is None, the shared `system` broadcasts as before."""
    from call_llm import CallMultipleLLM

    RecordingCallLLm.reset()
    with patch("call_llm.CallLLm", RecordingCallLLm):
        llm = CallMultipleLLM({"openAIKey": "test"}, ["m1", "m2"])
        list(llm("q", [], 0.7, True, None, "SHARED"))
    assert RecordingCallLLm.calls.get("m1") == ["SHARED"]
    assert RecordingCallLLm.calls.get("m2") == ["SHARED"]
    print("PASSED: test_call_multiple_llm_backward_compat")


def run_all_tests():
    tests = [
        test_system_list_routes_per_model,
        test_system_str_broadcasts,
        test_system_none_default,
        test_system_list_length_mismatch_raises,
        test_duplicate_models_get_distinct_systems,
        test_persona_helpers,
        test_call_multiple_llm_forwards_systems,
        test_call_multiple_llm_backward_compat,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"FAILED: {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed == 0


if __name__ == "__main__":
    ok = run_all_tests()
    sys.exit(0 if ok else 1)
