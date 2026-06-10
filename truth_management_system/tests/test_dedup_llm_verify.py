"""
Tests for Workstream W7 — LLM-assisted overlap judging.

LLMHelpers.judge_duplicates verifies a candidate cluster; the three find_*
dedup methods optionally filter clusters through it (use_llm / dedup_llm_verify).
LLM is mocked — no network.
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def test_judge_duplicates_needs_two(api):
    out = api.llm.judge_duplicates(["solo"])
    assert out["duplicate"] is False


def test_judge_duplicates_parses_llm(api, monkeypatch):
    monkeypatch.setattr(
        api.llm, "_call_llm",
        lambda *a, **k: '{"duplicate": true, "canonical": "John Smith", "reason": "variant"}',
    )
    out = api.llm.judge_duplicates(["john", "John Smith"], kind="entity")
    assert out["duplicate"] is True
    assert out["canonical"] == "John Smith"


def test_find_tag_duplicates_llm_filters(api, monkeypatch):
    api.add_tag("john")
    api.add_tag("john smith")
    api.add_tag("jon")  # similar but the LLM will reject this cluster

    calls = {"n": 0}

    def fake_judge(items, kind="claim"):
        calls["n"] += 1
        # accept only the cluster that contains "john smith"
        dup = any("smith" in s.lower() for s in items)
        return {"duplicate": dup, "canonical": "john smith", "reason": "x"}

    monkeypatch.setattr(api.llm, "judge_duplicates", fake_judge)
    res = api.find_tag_duplicates(use_llm=True)
    assert res.success
    # every surviving cluster is LLM-verified
    assert all(c.get("llm_verified") for c in res.data)
    assert calls["n"] >= 1


def test_find_tag_duplicates_no_llm_passthrough(api, monkeypatch):
    api.add_tag("john")
    api.add_tag("john smith")
    # use_llm defaults to config.dedup_llm_verify (False) -> no LLM call
    monkeypatch.setattr(
        api.llm, "judge_duplicates",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )
    res = api.find_tag_duplicates()
    assert res.success
    assert all("llm_verified" not in c for c in res.data)
