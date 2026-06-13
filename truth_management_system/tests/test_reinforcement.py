"""
Tests for Workstream H — reinforcement & decay.

Covers:
- Schema v8: claims has last_reinforced_at + reinforcement_count + index.
- Migration v7 -> v8: columns added, last_reinforced_at backfilled = updated_at.
- StructuredAPI.reinforce_claim: count++, last_reinforced_at/updated_at set,
  confidence asymptotic toward 1.0, dormant revive, TTL extension, and the
  contested/superseded safeguard.
- The recency re-rank (Workstream C) now reads last_reinforced_at in preference
  to updated_at.
"""

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.models import Claim
from truth_management_system.constants import ClaimStatus
from truth_management_system.crud import ClaimCRUD


def _iso(days_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    keys = {"OPENROUTER_API_KEY": "test-key"}
    return StructuredAPI(db, keys, config)


# --------------------------------------------------------------------------- #
# Schema / migration
# --------------------------------------------------------------------------- #
def test_schema_v8_has_reinforcement_columns(api):
    cols = {row[1] for row in api.db.execute("PRAGMA table_info(claims)").fetchall()}
    assert "last_reinforced_at" in cols
    assert "reinforcement_count" in cols

    idx = {
        row[1] for row in api.db.execute("PRAGMA index_list(claims)").fetchall()
    }
    assert "idx_claims_last_reinforced" in idx


def test_migration_v7_to_v8_backfills_last_reinforced(tmp_path):
    """The v7->v8 migration step adds the columns and backfills from updated_at."""
    db_path = str(tmp_path / "v7.sqlite")
    db = PKBDatabase(PKBConfig(db_path=db_path))
    conn = db.connect()
    # A v7-shaped claims table without the two v8 columns.
    conn.executescript(
        """
        CREATE TABLE claims (
            claim_id TEXT PRIMARY KEY,
            claim_type TEXT NOT NULL,
            statement TEXT NOT NULL,
            context_domain TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
        );
        INSERT INTO claims (claim_id, claim_type, statement, context_domain, status, created_at, updated_at)
            VALUES ('c1', 'fact', 'old claim', 'personal', 'active',
                    '2020-01-01T00:00:00Z', '2021-06-15T00:00:00Z');
        """
    )
    conn.commit()

    # Run the migration step directly (isolates it from full-DDL/FTS machinery).
    db._migrate_v7_to_v8(conn)
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()}
    assert "last_reinforced_at" in cols
    assert "reinforcement_count" in cols

    row = conn.execute(
        "SELECT last_reinforced_at, reinforcement_count FROM claims WHERE claim_id='c1'"
    ).fetchone()
    assert row[0] == "2021-06-15T00:00:00Z"  # backfilled from updated_at
    assert row[1] == 0  # NOT NULL DEFAULT 0

    # Index created.
    idx = {row[1] for row in conn.execute("PRAGMA index_list(claims)").fetchall()}
    assert "idx_claims_last_reinforced" in idx


def test_fresh_db_is_v8_with_columns_and_index(api):
    """A freshly initialized DB (no migration path) still has v8 columns + index."""
    assert api.db.get_schema_version() >= 8
    cols = {row[1] for row in api.db.execute("PRAGMA table_info(claims)").fetchall()}
    assert {"last_reinforced_at", "reinforcement_count"} <= cols


# --------------------------------------------------------------------------- #
# reinforce_claim
# --------------------------------------------------------------------------- #
def _add(api, statement="I prefer morning workouts", ctype="preference", **kw):
    claim = Claim.create(statement, ctype, "health", **kw)
    return ClaimCRUD(api.db).add(claim)


def test_reinforce_increments_count_and_sets_timestamps(api):
    claim = _add(api)
    assert claim.reinforcement_count == 0

    res = api.reinforce_claim(claim.claim_id)
    assert res.success
    c = res.data
    assert c.reinforcement_count == 1
    assert c.last_reinforced_at is not None
    # updated_at advanced (CRUD auto-stamps it)
    assert c.updated_at >= claim.updated_at

    res2 = api.reinforce_claim(claim.claim_id)
    assert res2.data.reinforcement_count == 2


def test_reinforce_confidence_is_asymptotic(api):
    claim = _add(api)
    # seed a known confidence
    ClaimCRUD(api.db).edit(claim.claim_id, {"confidence": 0.5})

    api.config.reinforce_alpha = 0.5
    c1 = api.reinforce_claim(claim.claim_id).data
    # 0.5 + (1-0.5)*0.5 = 0.75
    assert abs(c1.confidence - 0.75) < 1e-6
    c2 = api.reinforce_claim(claim.claim_id).data
    # 0.75 + (1-0.75)*0.5 = 0.875, strictly increasing but < 1.0
    assert 0.75 < c2.confidence < 1.0


def test_reinforce_strength_scales_alpha(api):
    claim = _add(api)
    ClaimCRUD(api.db).edit(claim.claim_id, {"confidence": 0.0})
    api.config.reinforce_alpha = 0.4
    c = api.reinforce_claim(claim.claim_id, strength=0.5).data
    # effective alpha = 0.4 * 0.5 = 0.2 -> 0 + (1-0)*0.2 = 0.2
    assert abs(c.confidence - 0.2) < 1e-6


def test_reinforce_revives_dormant(api):
    claim = _add(api)
    ClaimCRUD(api.db).edit(claim.claim_id, {"status": ClaimStatus.DORMANT.value})
    res = api.reinforce_claim(claim.claim_id)
    assert res.success
    assert res.data.status == ClaimStatus.ACTIVE.value
    assert any("dormant" in w.lower() for w in res.warnings)


def test_reinforce_refuses_contested_and_superseded(api):
    for status in (ClaimStatus.CONTESTED.value, ClaimStatus.SUPERSEDED.value):
        claim = _add(api, statement=f"claim {status}")
        ClaimCRUD(api.db).edit(claim.claim_id, {"status": status})
        res = api.reinforce_claim(claim.claim_id)
        assert not res.success
        assert res.errors
        # count unchanged
        after = api.claims.get(claim.claim_id)
        assert after.reinforcement_count == 0


def test_reinforce_extends_ttl_when_configured(api):
    claim = _add(api, ctype="task")
    near = _iso(2)
    ClaimCRUD(api.db).edit(claim.claim_id, {"valid_to": near})
    api.config.reinforce_ttl_days_by_type = {"task": 30.0}

    res = api.reinforce_claim(claim.claim_id)
    assert res.success
    # valid_to pushed out to ~now+30d (well beyond the original +2d)
    assert res.data.valid_to > _iso(20)


def test_reinforce_no_ttl_extension_by_default(api):
    claim = _add(api, ctype="task")
    near = _iso(2)
    ClaimCRUD(api.db).edit(claim.claim_id, {"valid_to": near})
    # default config: reinforce_ttl_days_by_type empty -> no change
    res = api.reinforce_claim(claim.claim_id)
    assert res.data.valid_to == near


def test_reinforce_missing_claim(api):
    res = api.reinforce_claim("does-not-exist")
    assert not res.success
    assert "not found" in res.errors[0].lower()


# --------------------------------------------------------------------------- #
# Recency re-rank now prefers last_reinforced_at (bridge C <-> H)
# --------------------------------------------------------------------------- #
def test_recency_rerank_prefers_last_reinforced_at():
    """A claim stale by updated_at but recently reinforced should rank as fresh."""
    from truth_management_system.search.base import apply_recency_confidence_rerank
    from truth_management_system.search.base import SearchResult

    cfg = PKBConfig(w_recency=2.0, recency_half_life_days=30.0)
    now = datetime.now(timezone.utc)

    # Both claims look old by updated_at; only A was recently reinforced.
    a = Claim.create("claim A", "fact", "personal")
    a.updated_at = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a.last_reinforced_at = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    b = Claim.create("claim B", "fact", "personal")
    b.updated_at = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    b.last_reinforced_at = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Give B the higher base RRF score so only recency can flip the order.
    ra = SearchResult.from_claim(a, 0.010, "fts", {"rrf_score": 0.010})
    rb = SearchResult.from_claim(b, 0.016, "fts", {"rrf_score": 0.016})

    ranked = apply_recency_confidence_rerank([rb, ra], cfg, now=now)
    # A (recently reinforced) should now outrank B despite lower base score.
    assert ranked[0].claim.claim_id == a.claim_id
    assert ranked[0].metadata["recency_factor"] > ranked[1].metadata["recency_factor"]


# --------------------------------------------------------------------------- #
# H3 reinforcement signal wire-ups
# --------------------------------------------------------------------------- #
def _claim_count(db):
    return db.execute("SELECT COUNT(*) FROM claims").fetchone()[0]


class _Extraction:
    """Minimal stand-in for LLMHelpers.extract_single output."""
    tags: list = []
    entities: list = []
    claim_type = "preference"


def test_pin_reinforces_but_unpin_does_not(api):
    claim = _add(api)
    assert claim.reinforcement_count == 0

    pinned = api.pin_claim(claim.claim_id, pin=True)
    assert pinned.success
    assert pinned.data.reinforcement_count == 1
    assert pinned.data.last_reinforced_at is not None

    # Unpinning must NOT reinforce again.
    unpinned = api.pin_claim(claim.claim_id, pin=False)
    assert unpinned.success
    assert unpinned.data.reinforcement_count == 1


def test_pin_does_not_reinforce_contested(api):
    claim = _add(api)
    ClaimCRUD(api.db).edit(claim.claim_id, {"status": ClaimStatus.CONTESTED.value})
    pinned = api.pin_claim(claim.claim_id, pin=True)
    assert pinned.success  # pin still toggles
    assert pinned.data.reinforcement_count == 0  # but reinforcement is skipped


def test_distiller_proposes_and_executes_reinforce_for_duplicate(api):
    from truth_management_system.interface.conversation_distillation import (
        ConversationDistiller,
        CandidateClaim,
    )

    existing = _add(api, statement="I am vegetarian", ctype="fact")
    d = ConversationDistiller(api, {"OPENROUTER_API_KEY": "x"}, api.config)
    cand = CandidateClaim(
        statement="I am vegetarian", claim_type="fact", context_domain="health"
    )

    # Duplicates (score > 0.9) are now silently reinforced — no proposal returned
    actions = d._propose_actions([cand], [(cand, existing, "duplicate")])
    assert len(actions) == 0  # silent reinforce, no proposal

    # Verify the reinforce actually happened
    refreshed = api.get_claim(existing.claim_id)
    assert refreshed.success
    assert refreshed.data.reinforcement_count == 1


def test_add_claim_duplicate_reinforces_when_configured(api, monkeypatch):
    existing = _add(api, statement="I love hiking", ctype="preference")
    api.config.reinforce_on_duplicate = "reinforce"

    monkeypatch.setattr(api.llm, "extract_single", lambda *a, **k: _Extraction())
    monkeypatch.setattr(api.llm, "generate_possible_questions", lambda *a, **k: [])
    monkeypatch.setattr(
        api.llm,
        "check_similarity",
        lambda statement, existing_claims, **k: [(existing, 0.97, "duplicate")],
    )

    before = _claim_count(api.db)
    res = api.add_claim(
        statement="I really love hiking",
        claim_type="preference",
        context_domain="health",
        auto_extract=True,
    )
    assert res.success
    assert res.action == "reinforce"
    assert res.object_id == existing.claim_id
    # No new (duplicate) claim was created.
    assert _claim_count(api.db) == before
    assert api.claims.get(existing.claim_id).reinforcement_count == 1


def test_add_claim_duplicate_off_creates_anyway(api, monkeypatch):
    existing = _add(api, statement="I drink coffee", ctype="preference")
    # Default config: reinforce_on_duplicate == "off" -> today's behavior.
    monkeypatch.setattr(api.llm, "extract_single", lambda *a, **k: _Extraction())
    monkeypatch.setattr(api.llm, "generate_possible_questions", lambda *a, **k: [])
    monkeypatch.setattr(
        api.llm,
        "check_similarity",
        lambda statement, existing_claims, **k: [(existing, 0.97, "duplicate")],
    )

    before = _claim_count(api.db)
    res = api.add_claim(
        statement="I drink coffee daily",
        claim_type="preference",
        context_domain="health",
        auto_extract=True,
    )
    assert res.success
    assert res.action == "add"
    assert _claim_count(api.db) == before + 1
    # Existing claim was NOT reinforced (just warned about).
    assert api.claims.get(existing.claim_id).reinforcement_count == 0
