"""
Workstream G3 — data portability and audit log.

Two related capabilities, both scoped per user:

- **Export / import** (``export_user_data`` / ``import_user_data``): a JSON
  snapshot of a user's claims, claim-to-claim links, entities, tags, contexts,
  and the join rows that connect them. Embeddings are intentionally excluded —
  they are derived data and can be rebuilt with ``backfill_embeddings()``.

- **Audit log** (``record_audit`` / ``get_audit_log``): an append-only history
  of add/edit/delete (and import) operations. Rows are only ever INSERTed and
  SELECTed, never mutated, so the log is tamper-evident.

All writes go through ``db.transaction()`` (commit-on-success, rollback-on-error)
and audit writes are best-effort — a logging failure must never break the user
operation it records.
"""

import json
import logging
import uuid
from typing import Dict, List, Optional

from .schema import SCHEMA_VERSION
from .utils import now_iso

logger = logging.getLogger(__name__)

# Bump if the export envelope shape changes in a backward-incompatible way.
EXPORT_FORMAT_VERSION = 1

# Tables owned directly by a user (they carry a ``user_email`` column).
# Order matters for import so that referenced rows are present (foreign keys are
# also deferred during import as a belt-and-suspenders measure).
_USER_TABLES = ["entities", "tags", "contexts", "claims", "claim_links"]

# Join / child tables keyed by ``claim_id`` (no ``user_email`` of their own);
# exported by membership in the set of the user's exported claims.
_CLAIM_CHILD_TABLES = ["claim_entities", "claim_tags", "context_claims"]


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
def record_audit(
    db,
    user_email: Optional[str],
    action: str,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    detail: Optional[Dict] = None,
) -> None:
    """
    Append one row to the audit log. Best-effort: never raises.

    Args:
        db: PKBDatabase.
        user_email: Owner (None for global/system rows).
        action: ``add`` | ``edit`` | ``delete`` | ``import`` | ...
        object_type: ``claim`` | ``entity`` | ``tag`` | ...
        object_id: ID of the affected object.
        detail: Optional JSON-serializable specifics (e.g. changed fields).
    """
    try:
        detail_json = json.dumps(detail) if detail is not None else None
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_log "
                "(audit_id, user_email, action, object_type, object_id, "
                "detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()), user_email, action, object_type,
                    object_id, detail_json, now_iso(),
                ),
            )
    except Exception as e:  # pragma: no cover - logging only
        logger.warning(f"Failed to record audit entry ({action} {object_type}): {e}")


def get_audit_log(
    db,
    user_email: Optional[str],
    limit: int = 100,
    offset: int = 0,
    action: Optional[str] = None,
) -> List[Dict]:
    """
    Return audit entries for a user, newest first.

    Args:
        db: PKBDatabase.
        user_email: Owner scope (None matches global rows).
        limit / offset: pagination.
        action: optional action filter.

    Returns:
        List of audit-row dicts.
    """
    sql = "SELECT audit_id, user_email, action, object_type, object_id, " \
          "detail_json, created_at FROM audit_log WHERE "
    params: List = []
    if user_email:
        sql += "user_email = ?"
        params.append(user_email)
    else:
        sql += "user_email IS NULL"
    if action:
        sql += " AND action = ?"
        params.append(action)
    sql += " ORDER BY created_at DESC, audit_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.fetchall(sql, tuple(params))
    out = []
    for r in rows:
        detail = None
        if r["detail_json"]:
            try:
                detail = json.loads(r["detail_json"])
            except (ValueError, TypeError):
                detail = r["detail_json"]
        out.append({
            "audit_id": r["audit_id"],
            "action": r["action"],
            "object_type": r["object_type"],
            "object_id": r["object_id"],
            "detail": detail,
            "created_at": r["created_at"],
        })
    return out


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def _scope_clause(user_email: Optional[str]) -> str:
    return "user_email = ?" if user_email else "user_email IS NULL"


def export_user_data(db, user_email: Optional[str]) -> Dict:
    """
    Build a JSON-serializable snapshot of a user's PKB.

    Includes claims, claim_links, entities, tags, contexts and the claim_*
    join rows. Excludes embeddings (derived) and the audit log (history, not
    portable state).

    Args:
        db: PKBDatabase.
        user_email: Owner whose data to export (None = global rows).

    Returns:
        Export envelope dict.
    """
    data: Dict[str, List[Dict]] = {}

    # Owned tables: filter by user_email.
    for table in _USER_TABLES:
        rows = db.fetchall(
            f"SELECT * FROM {table} WHERE {_scope_clause(user_email)}",
            (user_email,) if user_email else (),
        )
        data[table] = [dict(r) for r in rows]

    # Child/join tables: filter by membership in the exported claim set.
    claim_ids = [c["claim_id"] for c in data.get("claims", [])]
    for table in _CLAIM_CHILD_TABLES:
        if not claim_ids:
            data[table] = []
            continue
        placeholders = ",".join("?" for _ in claim_ids)
        rows = db.fetchall(
            f"SELECT * FROM {table} WHERE claim_id IN ({placeholders})",
            tuple(claim_ids),
        )
        data[table] = [dict(r) for r in rows]

    counts = {t: len(rows) for t, rows in data.items()}
    return {
        "pkb_export_version": EXPORT_FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exported_at": now_iso(),
        "user_email": user_email,
        "counts": counts,
        "data": data,
    }


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def import_user_data(
    db, user_email: Optional[str], payload: Dict, mode: str = "merge"
) -> Dict:
    """
    Load an export envelope into the database under ``user_email``.

    Owned rows (claims, links, entities, tags, contexts) are re-stamped with the
    importing user's email so an export can be moved between users. ``mode``:

    - ``merge`` (default): ``INSERT OR IGNORE`` — rows whose primary key already
      exists are skipped, so re-importing is a safe no-op and partial overlaps
      merge cleanly.

    Foreign keys are deferred for the duration of the import transaction so that
    self-referential (parent tag/context) and cross-table references resolve
    regardless of insertion order, then are verified atomically at commit.

    Args:
        db: PKBDatabase.
        user_email: Importing user (rows are re-owned to this email).
        payload: An envelope produced by :func:`export_user_data`.
        mode: ``merge`` (only supported mode today).

    Returns:
        Dict of per-table inserted-row counts plus ``mode``.
    """
    if mode != "merge":
        raise ValueError(f"Unsupported import mode: {mode!r} (only 'merge')")

    data = payload.get("data") or {}
    inserted: Dict[str, int] = {}
    all_tables = _USER_TABLES + _CLAIM_CHILD_TABLES

    with db.transaction() as conn:
        conn.execute("PRAGMA defer_foreign_keys=ON")
        for table in all_tables:
            rows = data.get(table) or []
            n = 0
            for row in rows:
                row = dict(row)
                # Re-own owned-table rows to the importing user.
                if table in _USER_TABLES and "user_email" in row:
                    row["user_email"] = user_email
                cols = list(row.keys())
                placeholders = ",".join("?" for _ in cols)
                col_list = ",".join(cols)
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) "
                    f"VALUES ({placeholders})",
                    tuple(row[c] for c in cols),
                )
                n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            inserted[table] = n

    inserted["mode"] = mode
    return inserted
