"""
Tests for Workstream W1 — two-axis claim provenance.

Channel (manual|chat|ingest|import) + derivation (stated|extracted|inferred),
stored under meta_json.source. Covers:
  - constants (ProvenanceChannel.normalize, Derivation)
  - utils.set_provenance / get_provenance / infer_legacy_provenance
  - add_claim wiring + defaults + inferred confidence cap
  - backfill_provenance (idempotent)
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.constants import ProvenanceChannel, Derivation
from truth_management_system.utils import (
    set_provenance,
    get_provenance,
    infer_legacy_provenance,
)


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _src(api, claim_id):
    return json.loads(api.claims.get(claim_id).meta_json)["source"]


# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
def test_channel_normalize():
    assert ProvenanceChannel.normalize("chat_distillation") == "chat"
    assert ProvenanceChannel.normalize("text_ingestion") == "ingest"
    assert ProvenanceChannel.normalize("migration") == "import"
    assert ProvenanceChannel.normalize("manual") == "manual"
    assert ProvenanceChannel.normalize(None) == "manual"
    assert ProvenanceChannel.normalize("weird") == "weird"  # passthrough


def test_derivation_helpers():
    assert Derivation.default() == "stated"
    assert Derivation.is_valid("inferred")
    assert not Derivation.is_valid("bogus")


# --------------------------------------------------------------------------- #
# utils helpers
# --------------------------------------------------------------------------- #
def test_set_provenance_defaults_and_legacy_type():
    meta = {}
    set_provenance(meta, channel="chat_distillation", legacy_type="chat_distillation")
    src = meta["source"]
    assert src["channel"] == "chat"            # normalized
    assert src["type"] == "chat_distillation"  # legacy preserved
    assert src["derivation"] == "stated"       # default


def test_set_provenance_promotes_string_source():
    meta = {"source": "manual"}
    set_provenance(meta, derivation="inferred")
    assert meta["source"]["channel"] == "manual"
    assert meta["source"]["derivation"] == "inferred"
    assert meta["source"]["type"] == "manual"


def test_get_provenance_legacy_and_dict():
    assert get_provenance(json.dumps({"source": "chat_distillation"})) == {
        "channel": "chat",
        "derivation": "stated",
    }
    assert get_provenance(None) == {"channel": "manual", "derivation": "stated"}


def test_infer_legacy_provenance():
    assert infer_legacy_provenance(json.dumps({"source": "manual"})) == {
        "channel": "manual",
        "derivation": "stated",
    }
    assert infer_legacy_provenance(json.dumps({"source": {"type": "import"}})) == {
        "channel": "import",
        "derivation": "extracted",
    }


# --------------------------------------------------------------------------- #
# add_claim wiring
# --------------------------------------------------------------------------- #
def test_manual_add_is_manual_stated(api):
    r = api.add_claim("I like tea", "preference", "personal", auto_extract=False)
    src = _src(api, r.data.claim_id)
    assert src["channel"] == "manual"
    assert src["derivation"] == "stated"


def test_distilled_defaults_chat_extracted(api):
    r = api.add_claim(
        "user mentioned a trip", "memory", "personal", auto_extract=False,
        source_conversation_id="c1",
    )
    src = _src(api, r.data.claim_id)
    assert src["channel"] == "chat"
    assert src["derivation"] == "extracted"
    assert src["type"] == "chat_distillation"  # legacy preserved


def test_explicit_channel_and_derivation(api):
    r = api.add_claim(
        "health-conscious", "observation", "health", auto_extract=False,
        channel="migration", derivation="inferred",
    )
    src = _src(api, r.data.claim_id)
    assert src["channel"] == "import"      # migration normalized
    assert src["derivation"] == "inferred"


def test_inferred_caps_confidence(api):
    r = api.add_claim(
        "user is a runner", "observation", "health", auto_extract=False,
        derivation="inferred", confidence=0.95,
    )
    claim = api.claims.get(r.data.claim_id)
    assert claim.confidence <= api.config.inferred_confidence_cap


def test_stated_confidence_not_capped(api):
    r = api.add_claim(
        "explicit fact", "fact", "personal", auto_extract=False,
        derivation="stated", confidence=0.95,
    )
    assert api.claims.get(r.data.claim_id).confidence == 0.95


# --------------------------------------------------------------------------- #
# backfill
# --------------------------------------------------------------------------- #
def test_backfill_provenance_idempotent(api):
    # Simulate a legacy claim: write a string-form source directly.
    r = api.add_claim("legacy", "fact", "personal", auto_extract=False)
    cid = r.data.claim_id
    with api.db.transaction() as conn:
        conn.execute(
            "UPDATE claims SET meta_json = ? WHERE claim_id = ?",
            (json.dumps({"source": "chat_distillation"}), cid),
        )
    out = api.backfill_provenance()
    assert out["updated"] >= 1
    src = _src(api, cid)
    assert src["channel"] == "chat"
    assert src["derivation"] == "extracted"  # non-manual legacy -> extracted
    # Second run is a no-op (already has derivation).
    assert api.backfill_provenance()["updated"] == 0
