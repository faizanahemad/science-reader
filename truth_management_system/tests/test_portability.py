"""
Tests for Workstream G3 — data portability (export/import) and the audit log.

All offline (auto_extract=False; no LLM).
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.schema import SCHEMA_VERSION


def _api(email="u1@example.com"):
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email=email)


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def test_schema_is_v10_with_audit_table():
    api = _api()
    assert SCHEMA_VERSION >= 10
    assert api.db.get_schema_version() == SCHEMA_VERSION
    # audit_log table exists and is queryable.
    assert api.db.fetchone("SELECT COUNT(*) c FROM audit_log")["c"] == 0


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
def test_audit_records_add_edit_delete():
    api = _api()
    r = api.add_claim("I live in Mumbai", "fact", "personal", auto_extract=False)
    cid = r.object_id
    api.edit_claim(cid, statement="I live in Bengaluru")
    api.delete_claim(cid)

    log = api.get_audit_log().data
    actions = sorted(e["action"] for e in log["entries"])
    assert actions == ["add", "delete", "edit"]
    # edit detail captures changed fields.
    edit = next(e for e in log["entries"] if e["action"] == "edit")
    assert "statement" in edit["detail"]["fields"]


def test_audit_action_filter_and_scoping():
    api = _api("owner@example.com")
    api.add_claim("a", "fact", "personal", auto_extract=False)
    api.add_claim("b", "fact", "personal", auto_extract=False)
    adds = api.get_audit_log(action="add").data
    assert adds["count"] == 2
    assert all(e["action"] == "add" for e in adds["entries"])

    # A different user sees none of the first user's audit entries.
    other = StructuredAPI(api.db, {}, api.config, user_email="other@example.com")
    assert other.get_audit_log().data["count"] == 0


# --------------------------------------------------------------------------- #
# Export / import
# --------------------------------------------------------------------------- #
def test_export_envelope_shape():
    api = _api()
    api.add_claim("I like tea", "preference", "personal", auto_extract=False)
    env = api.export_data().data
    assert env["pkb_export_version"] == 1
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["user_email"] == "u1@example.com"
    assert env["counts"]["claims"] == 1
    assert "claims" in env["data"] and "claim_tags" in env["data"]


def test_export_import_round_trip_across_users():
    src = _api("src@example.com")
    r = src.add_claim("I live in Mumbai", "fact", "personal", auto_extract=False)
    src.edit_claim(r.object_id, statement="I live in Bengaluru")
    src.add_claim("I like tea", "preference", "personal", auto_extract=False)
    env = src.export_data().data
    assert env["counts"]["claims"] == 2

    # Import into a fresh DB under a different user.
    dst = _api("dst@example.com")
    counts = dst.import_data(env).data
    assert counts["claims"] == 2

    rows = dst.db.fetchall(
        "SELECT statement, user_email FROM claims ORDER BY statement"
    )
    statements = [row["statement"] for row in rows]
    assert "I live in Bengaluru" in statements
    assert "I like tea" in statements
    # Rows are re-owned to the importing user.
    assert all(row["user_email"] == "dst@example.com" for row in rows)


def test_import_merge_is_idempotent():
    src = _api("src@example.com")
    src.add_claim("fact one", "fact", "personal", auto_extract=False)
    env = src.export_data().data

    dst = _api("dst@example.com")
    first = dst.import_data(env).data
    assert first["claims"] == 1
    second = dst.import_data(env).data
    assert second["claims"] == 0  # merge skips existing primary keys


def test_import_rejects_invalid_payload():
    api = _api()
    result = api.import_data({"not": "an envelope"})
    assert not result.success
    assert any("data" in e for e in result.errors)


def test_import_records_audit_entry():
    src = _api("src@example.com")
    src.add_claim("fact one", "fact", "personal", auto_extract=False)
    env = src.export_data().data

    dst = _api("dst@example.com")
    dst.import_data(env)
    imports = dst.get_audit_log(action="import").data
    assert imports["count"] == 1
    assert imports["entries"][0]["detail"]["claims"] == 1


def test_export_preserves_tags_and_links():
    api = _api("tagger@example.com")
    # Two claims where the newer supersedes the older (creates a claim_link).
    old = api.add_claim("I live in Mumbai", "fact", "personal", auto_extract=False)
    new = api.add_claim(
        "I live in Bengaluru", "fact", "personal",
        auto_extract=False, supersedes=old.object_id,
    )
    env = api.export_data().data
    assert env["counts"]["claim_links"] >= 1

    dst = _api("dst2@example.com")
    counts = dst.import_data(env).data
    assert counts["claim_links"] >= 1
    # Link survived with both endpoints present.
    link = dst.db.fetchone(
        "SELECT from_claim_id, to_claim_id, link_type FROM claim_links LIMIT 1"
    )
    assert link["link_type"] == "supersedes"
