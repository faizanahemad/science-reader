"""
Tests for Workstream G2 — batch / combined enrichment.

Verifies that auto-extract uses a single combined LLM call
(``analyze_claim_statement``) instead of the legacy multi-call path, that the
combined call's questions are reused (no extra question-generation call), that
bulk adds fan the analysis out via a single ``batch_analyze``, and that the
legacy path is still reachable via the config flag. All offline (fake LLM).
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.llm_helpers import ClaimAnalysisResult, ExtractionResult


class FakeLLM:
    """Records call counts for each enrichment entry point."""

    def __init__(self):
        self.analyze_calls = 0
        self.extract_calls = 0
        self.questions_calls = 0
        self.batch_calls = 0
        self.similarity_calls = 0

    def analyze_claim_statement(self, statement, model=None):
        self.analyze_calls += 1
        return ClaimAnalysisResult(
            claim_type="preference",
            context_domain="health",
            tags=["combined_tag_a", "combined_tag_b"],
            entities=[{"type": "topic", "name": "workouts", "role": "object"}],
            possible_questions=["Do I prefer mornings?", "What is my routine?"],
        )

    def extract_single(self, statement, context_domain="personal"):
        self.extract_calls += 1
        return ExtractionResult(
            tags=["legacy_tag"],
            entities=[],
            spo={},
            claim_type="fact",
            keywords=[],
        )

    def generate_possible_questions(self, statement, claim_type="fact"):
        self.questions_calls += 1
        return ["legacy question?"]

    def check_similarity(self, statement, existing, cached_embeddings=None):
        self.similarity_calls += 1
        return []

    def batch_analyze(self, statements, model=None):
        self.batch_calls += 1
        return [self.analyze_claim_statement(s) for s in statements]


def _api(combined=True, email="g2@example.com"):
    config = PKBConfig(db_path=":memory:", combined_enrichment=combined)
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    api = StructuredAPI(db, {}, config, user_email=email)
    api.llm = FakeLLM()
    return api


def _claim(api, claim_id):
    return api.claims.get(claim_id)


# --------------------------------------------------------------------------- #
# Combined path (default)
# --------------------------------------------------------------------------- #
def test_combined_add_uses_single_llm_call():
    api = _api(combined=True)
    r = api.add_claim("I work out", "observation", "personal", auto_extract=True)
    assert r.success
    llm = api.llm
    # Exactly one combined analysis call; no legacy extraction or question calls.
    assert llm.analyze_calls == 1
    assert llm.extract_calls == 0
    assert llm.questions_calls == 0


def test_combined_add_applies_analysis_fields():
    api = _api(combined=True)
    r = api.add_claim("I work out", "observation", "personal", auto_extract=True)
    claim = _claim(api, r.object_id)
    # Type overridden from "observation" -> analysis type.
    assert claim.claim_type == "preference"
    # Questions reused from the same combined call (no extra LLM round-trip).
    questions = json.loads(claim.possible_questions)
    assert questions == ["Do I prefer mornings?", "What is my routine?"]


def test_user_provided_fields_not_overridden():
    api = _api(combined=True)
    r = api.add_claim(
        "I work out", "fact", "personal", auto_extract=True,
        tags=["mine"], possible_questions=["my own?"],
    )
    claim = _claim(api, r.object_id)
    assert json.loads(claim.possible_questions) == ["my own?"]
    # claim_type was explicitly "fact" (not observation) -> not overridden.
    assert claim.claim_type == "fact"


# --------------------------------------------------------------------------- #
# Legacy path (flag off)
# --------------------------------------------------------------------------- #
def test_legacy_path_uses_extract_and_questions():
    api = _api(combined=False)
    r = api.add_claim("I work out", "observation", "personal", auto_extract=True)
    assert r.success
    llm = api.llm
    assert llm.analyze_calls == 0
    assert llm.extract_calls == 1
    assert llm.questions_calls == 1


# --------------------------------------------------------------------------- #
# Bulk batching
# --------------------------------------------------------------------------- #
def test_bulk_uses_single_batch_analyze():
    api = _api(combined=True)
    claims = [
        {"statement": "I like tea", "claim_type": "preference"},
        {"statement": "I run daily", "claim_type": "observation"},
        {"statement": "I sleep early", "claim_type": "habit"},
    ]
    res = api.add_claims_bulk(claims, auto_extract=True)
    assert res.data["added_count"] == 3
    llm = api.llm
    # One batch fan-out call; the 3 analyze calls all come from inside it
    # (add_claim did NOT make its own per-claim analyze call).
    assert llm.batch_calls == 1
    assert llm.analyze_calls == 3
    assert llm.extract_calls == 0


def test_bulk_without_autoextract_makes_no_llm_calls():
    api = _api(combined=True)
    claims = [{"statement": "plain claim", "claim_type": "fact"}]
    res = api.add_claims_bulk(claims, auto_extract=False)
    assert res.data["added_count"] == 1
    llm = api.llm
    assert llm.batch_calls == 0
    assert llm.analyze_calls == 0
