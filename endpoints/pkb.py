"""
Personal Knowledge Base (PKB) endpoints.

This module extracts the `/pkb/*` API surface from `server.py` into a Flask
Blueprint while preserving exact routes, methods, and behavior.

Notes
-----
- The PKB feature depends on the optional `truth_management_system` package. If
  it's not installed, endpoints return HTTP 503.
- PKB database path is derived from `AppState.users_dir` (not `server.py` globals).
- Conversation-level pinned-claim state is stored in `AppState.pinned_claims`.
"""

from __future__ import annotations

import logging
import os
import traceback
import uuid
import warnings
from typing import Any

from flask import Blueprint, jsonify, request, session, Response

from endpoints.auth import login_required
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from endpoints.utils import keyParser
from extensions import limiter


logger = logging.getLogger(__name__)
pkb_bp = Blueprint("pkb", __name__)


# =============================================================================
# PKB (truth_management_system) imports (optional)
# =============================================================================
try:
    from truth_management_system import (  # type: ignore
        PKBConfig,
        StructuredAPI,
        ConversationDistiller,
        get_database,
        PKBOverviewManager,
        OverviewUpdateEvent,
    )
    from truth_management_system.interface.text_ingestion import (  # type: ignore
        TextIngestionDistiller,
    )

    PKB_AVAILABLE = True
except ImportError:
    PKB_AVAILABLE = False
    warnings.warn(
        "PKB (truth_management_system) not available. PKB endpoints will be disabled."
    )


# =============================================================================
# PKB shared state (module-local; lazily initialized)
# =============================================================================
_pkb_db = None
_pkb_config = None

_memory_update_plans: dict[str, Any] = {}
_text_ingestion_plans: dict[str, Any] = {}


def _pinned_store() -> dict[str, set]:
    """
    Return the in-memory conversation-level pinned-claims store.

    The store maps: conversation_id -> set(claim_id).
    """

    st = get_state()
    if st.pinned_claims is None:
        st.pinned_claims = {}
    return st.pinned_claims


def get_conversation_pinned_claims(conversation_id: str) -> set:
    """Get pinned claim IDs for a conversation."""

    store = _pinned_store()
    return store.get(conversation_id, set())


def add_conversation_pinned_claim(conversation_id: str, claim_id: str) -> None:
    """Pin a claim ID to a conversation."""

    store = _pinned_store()
    if conversation_id not in store:
        store[conversation_id] = set()
    store[conversation_id].add(claim_id)


def remove_conversation_pinned_claim(conversation_id: str, claim_id: str) -> None:
    """Unpin a claim ID from a conversation."""

    store = _pinned_store()
    if conversation_id in store:
        store[conversation_id].discard(claim_id)


def clear_conversation_pinned_claims(conversation_id: str) -> None:
    """Clear all pinned claims for a conversation."""

    store = _pinned_store()
    if conversation_id in store:
        del store[conversation_id]


def get_pkb_db():
    """Get or initialize the shared PKB database instance."""

    global _pkb_db, _pkb_config

    if not PKB_AVAILABLE:
        return None, None

    if _pkb_db is None:
        st = get_state()
        pkb_db_path = os.path.join(st.users_dir, "pkb.sqlite")
        _pkb_config = PKBConfig(db_path=pkb_db_path)
        _pkb_db = get_database(_pkb_config)
        logger.info(f"Initialized PKB database at {pkb_db_path}")

        # Run initial expiry of stale claims on startup
        try:
            from truth_management_system.utils import expire_stale_claims
            expired_count = expire_stale_claims(_pkb_db)
            if expired_count > 0:
                logger.info(f"Expired {expired_count} stale claims on startup")
        except Exception as e:
            logger.warning(f"Failed to expire stale claims on startup: {e}")
    else:
        # Ensure schema is up-to-date even in long-running servers where the
        # code (and SCHEMA_VERSION) may have changed since `_pkb_db` was first
        # created. This is idempotent and cheap when already up-to-date.
        try:
            _pkb_db.initialize_schema()
        except Exception as e:
            logger.error(f"Failed to ensure PKB schema is initialized: {e}")
            return None, None

    return _pkb_db, _pkb_config


def get_pkb_api_for_user(user_email: str, keys: dict | None = None):
    """
    Get a StructuredAPI instance scoped to a specific user.

    Parameters
    ----------
    user_email:
        Email of the user to scope operations to.
    keys:
        API keys dict (for LLM operations).
    """

    db, config = get_pkb_db()
    if db is None:
        return None

    return StructuredAPI(db, keys or {}, config, user_email=user_email)


def start_pkb_background_jobs():
    """
    Start PKB background jobs at server startup (Workstream F1).

    Initializes the shared PKB database and starts the periodic lifecycle-sweep
    scheduler. The scheduler is config-gated (``sweep_interval_seconds <= 0``
    disables it), so this is a safe no-op by default. Best-effort: any failure
    is logged and swallowed so it never blocks server startup.

    Returns:
        The sweep Thread, or None when PKB is unavailable / scheduler disabled.
    """
    if not PKB_AVAILABLE:
        return None
    try:
        db, config = get_pkb_db()
        if db is None or config is None:
            return None
        from truth_management_system.scheduler import start_lifecycle_sweep_scheduler

        return start_lifecycle_sweep_scheduler(db, config)
    except Exception as e:
        logger.warning(f"Failed to start PKB background jobs: {e}")
        return None


def _safe_overview_update(manager, user_email: str, event) -> None:
    """Inner async task — marks stale on failure, never raises."""
    try:
        manager.update_from_event(user_email, event)
    except Exception as e:
        logger.warning(f"[PKB Overview] async update failed for {user_email}: {e}")
        try:
            manager.mark_stale(user_email)
        except Exception:
            pass


def _fire_overview_update(user_email: str, trigger: str, claims: list, link_metadata: dict = None) -> None:
    """
    Fire-and-forget async overview update after a successful write op.
    Never blocks the write endpoint response. Swallows all errors.
    """
    if not PKB_AVAILABLE:
        return
    try:
        from base import get_async_future
        db, config = get_pkb_db()
        keys = keyParser.get_api_keys()
        manager = PKBOverviewManager(db, keys, config)
        current = manager.get_raw_content(user_email) or ""
        event = OverviewUpdateEvent(
            trigger=trigger, claims=claims, current_content=current,
            link_metadata=link_metadata,
        )
        get_async_future(_safe_overview_update, manager, user_email, event)
    except Exception as e:
        logger.warning(f"[PKB Overview] failed to fire overview update: {e}")


def serialize_claim(claim):
    """Convert a Claim object to a JSON-serializable dict."""

    return {
        "claim_id": claim.claim_id,
        "user_email": claim.user_email,
        "claim_number": getattr(claim, "claim_number", None),
        "friendly_id": getattr(claim, "friendly_id", None),
        "claim_type": claim.claim_type,
        "claim_types": getattr(claim, "claim_types", None),
        "statement": claim.statement,
        "context_domain": claim.context_domain,
        "context_domains": getattr(claim, "context_domains", None),
        "status": claim.status,
        "confidence": claim.confidence,
        "subject_text": claim.subject_text,
        "predicate": claim.predicate,
        "object_text": claim.object_text,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        "valid_from": claim.valid_from,
        "valid_to": claim.valid_to,
        "meta_json": claim.meta_json,
        "possible_questions": getattr(claim, "possible_questions", None),
    }


def serialize_context(context):
    """Convert a Context object to a JSON-serializable dict."""

    return {
        "context_id": context.context_id,
        "user_email": context.user_email,
        "friendly_id": context.friendly_id,
        "name": context.name,
        "description": context.description,
        "parent_context_id": context.parent_context_id,
        "meta_json": context.meta_json,
        "created_at": context.created_at,
        "updated_at": context.updated_at,
    }


def serialize_entity(entity):
    """Convert an Entity object to a JSON-serializable dict."""

    return {
        "entity_id": entity.entity_id,
        "user_email": entity.user_email,
        "entity_type": entity.entity_type,
        "name": entity.name,
        "meta_json": entity.meta_json,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def serialize_tag(tag):
    """Convert a Tag object to a JSON-serializable dict."""

    return {
        "tag_id": tag.tag_id,
        "user_email": tag.user_email,
        "name": tag.name,
        "parent_tag_id": tag.parent_tag_id,
        "meta_json": tag.meta_json,
        "created_at": tag.created_at,
        "updated_at": tag.updated_at,
    }


def serialize_conflict_set(conflict_set):
    """Convert a ConflictSet object to a JSON-serializable dict."""

    return {
        "conflict_set_id": conflict_set.conflict_set_id,
        "user_email": conflict_set.user_email,
        "status": conflict_set.status,
        "resolution_notes": conflict_set.resolution_notes,
        "created_at": conflict_set.created_at,
        "updated_at": conflict_set.updated_at,
        "member_claim_ids": conflict_set.member_claim_ids,
    }


def serialize_search_result(result):
    """Convert a SearchResult object to a JSON-serializable dict."""

    return {
        "claim": serialize_claim(result.claim),
        "score": result.score,
        "source": result.source,
        "is_contested": result.is_contested,
        "warnings": result.warnings,
        "metadata": result.metadata,
    }


# =============================================================================
# === Claims CRUD Endpoints ===
# =============================================================================


@pkb_bp.route("/pkb/claims", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_claims_route():
    """List or search claims.

    When the ``query`` parameter is present the endpoint performs a hybrid
    (or specified strategy) search **with** the given filters.  When
    ``query`` is absent it falls back to a simple DB list with filters.

    This single endpoint replaces the need for the separate ``POST /pkb/search``
    endpoint in the UI.

    Query params (all optional):
        query         - Free-text search query.
        strategy      - Search strategy: hybrid (default), fts, embedding, rerank.
        claim_type    - Filter by claim type.
        context_domain- Filter by context domain.
        status        - Filter by status (default: active).
        limit         - Max results (default 100).
        offset        - Pagination offset (default 0, list-mode only).
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        query = request.args.get("query", "").strip()
        strategy = request.args.get("strategy", "hybrid")
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))

        filters = {}
        if request.args.get("claim_type"):
            filters["claim_type"] = request.args.get("claim_type")
        if request.args.get("context_domain"):
            filters["context_domain"] = request.args.get("context_domain")
        if request.args.get("status"):
            filters["status"] = request.args.get("status")
        else:
            filters["status"] = "active"

        if query:
            # --- Search mode: use hybrid/fts/embedding search with filters ---
            keys = keyParser(session)
            api = get_pkb_api_for_user(email, keys)
            if api is None:
                return json_error(
                    "Failed to initialize PKB", status=500, code="pkb_init_failed"
                )

            result = api.search(query, strategy=strategy, k=limit, filters=filters)
            if result.success:
                claims = [r.claim for r in result.data]
                return jsonify(
                    {
                        "claims": [serialize_claim(c) for c in claims],
                        "count": len(claims),
                    }
                )
            return json_error("; ".join(result.errors), status=400, code="bad_request")
        else:
            # --- List mode: simple DB query with filters ---
            api = get_pkb_api_for_user(email)
            if api is None:
                return json_error(
                    "Failed to initialize PKB", status=500, code="pkb_init_failed"
                )

            claims = api.claims.list(
                filters=filters, limit=limit, offset=offset, order_by="-updated_at"
            )
            return jsonify(
                {"claims": [serialize_claim(c) for c in claims], "count": len(claims)}
            )
    except Exception as e:
        logger.error(f"Error in pkb_list_claims: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def pkb_add_claim_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        statement = data.get("statement")
        claim_type = data.get("claim_type")
        context_domain = data.get("context_domain")

        if not all([statement, claim_type, context_domain]):
            return json_error(
                "Missing required fields: statement, claim_type, context_domain",
                status=400,
                code="bad_request",
            )

        tags = data.get("tags", [])
        entities = data.get("entities", [])
        auto_extract = data.get("auto_extract", False)
        confidence = data.get("confidence")
        meta_json = data.get("meta_json")
        valid_from = data.get("valid_from")
        valid_to = data.get("valid_to")
        claim_types = data.get("claim_types")  # JSON string or None
        context_domains = data.get("context_domains")  # JSON string or None
        possible_questions = data.get("possible_questions")  # JSON string or None

        # Enforce valid_to for time-bound claim types
        if claim_type in ("task", "reminder") and not valid_to:
            return json_error(
                "valid_to is required for task and reminder claims. "
                "Please provide a deadline date.",
                status=400,
                code="valid_to_required",
            )

        keys = keyParser(session) if auto_extract else {}
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.add_claim(
            statement=statement,
            claim_type=claim_type,
            context_domain=context_domain,
            tags=tags,
            entities=entities,
            auto_extract=auto_extract,
            confidence=confidence,
            valid_from=valid_from,
            valid_to=valid_to,
            meta_json=meta_json,
            claim_types=claim_types,
            context_domains=context_domains,
            possible_questions=possible_questions,
        )

        if result.success:
            _fire_overview_update(email, "add", [result.data])
            return jsonify(
                {
                    "success": True,
                    "claim": serialize_claim(result.data),
                    "warnings": result.warnings,
                    "lifecycle_changes": (result.metadata or {}).get(
                        "lifecycle_changes", []
                    ),
                }
            )

        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_add_claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/bulk", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_add_claims_bulk_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        claims = data.get("claims")
        if not claims or not isinstance(claims, list):
            return json_error(
                "Missing or invalid 'claims' field (must be an array)",
                status=400,
                code="bad_request",
            )
        if len(claims) == 0:
            return json_error("Claims array is empty", status=400, code="bad_request")
        if len(claims) > 100:
            return json_error(
                "Too many claims. Maximum is 100 per request.",
                status=400,
                code="bad_request",
            )

        auto_extract = data.get("auto_extract", False)
        stop_on_error = data.get("stop_on_error", False)

        keys = keyParser(session) if auto_extract else {}
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.add_claims_bulk(
            claims=claims, auto_extract=auto_extract, stop_on_error=stop_on_error
        )
        # Fire one consolidated overview update for all successfully added claims
        added_claims = [r["claim"] for r in result.data.get("results", []) if r.get("success") and r.get("claim")]
        if added_claims:
            _fire_overview_update(email, "bulk", added_claims)
        return jsonify(
            {
                "success": result.success,
                "results": result.data["results"],
                "added_count": result.data["added_count"],
                "failed_count": result.data["failed_count"],
                "total": result.data["total"],
                "warnings": result.warnings,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_add_claims_bulk: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/analyze_statement", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def pkb_analyze_statement_route():
    """Analyze a claim statement and return auto-populated fields.

    Uses a cheap/fast LLM to extract claim_type, context_domain, tags,
    entities, and possible_questions in a single call.  Shared backend
    logic with text-ingestion enrichment (which uses an expensive model).

    Request body:
        {"statement": "I prefer morning workouts"}

    Response:
        {"success": true, "analysis": {
            "claim_type": "preference",
            "context_domain": "health",
            "tags": ["morning_exercise", "fitness"],
            "entities": [{"type": "topic", "name": "morning workouts", "role": "object"}],
            "possible_questions": ["Do I prefer morning or evening workouts?", ...]
        }}
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        statement = (data.get("statement") or "").strip()
        if not statement:
            return json_error(
                "Missing or empty 'statement' field",
                status=400,
                code="bad_request",
            )

        keys = keyParser(session)
        if not keys.get("OPENROUTER_API_KEY"):
            return json_error(
                "API key required for statement analysis",
                status=400,
                code="api_key_required",
            )

        from truth_management_system.llm_helpers import LLMHelpers, ClaimAnalysisResult
        from truth_management_system.config import PKBConfig

        db, config = get_pkb_db()
        llm = LLMHelpers(keys, config)

        from common import CHEAP_LLM

        cheap_model = CHEAP_LLM[0] if CHEAP_LLM else config.llm_model

        analysis = llm.analyze_claim_statement(statement, model=cheap_model)

        from truth_management_system.utils import generate_friendly_id

        friendly_id = generate_friendly_id(statement)

        return jsonify(
            {
                "success": True,
                "analysis": {
                    "claim_type": analysis.claim_type,
                    "context_domain": analysis.context_domain,
                    "tags": analysis.tags,
                    "entities": analysis.entities,
                    "possible_questions": analysis.possible_questions,
                    "confidence": analysis.confidence,
                    "friendly_id": friendly_id,
                },
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_analyze_statement: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/backfill_entities", methods=["POST"])
@limiter.limit("2 per minute")
@login_required
def pkb_backfill_entities_route():
    """
    Backfill entity links for the current user's existing claims.

    Links entities for active claims that have no entity links yet (claims that
    predate entity extraction or were added with auto_extract=False) — corpus
    parity for the entity-linked retrieval strategy. Idempotent, user-scoped,
    off the retrieval hot path, and NOT required for correctness.

    Body (all optional):
        context_domain: restrict to one domain (e.g. "work").
        dry_run: preview without writing (default True for safety).
        limit: cap claims processed this call. Large corpora should pass a limit
            and call repeatedly (already-linked claims are skipped) or use the
            CLI (`python -m truth_management_system.backfill_entities`), since
            this runs synchronously and makes one LLM call per scanned claim.

    Requires OPENROUTER_API_KEY (entity extraction is LLM-backed).
    Returns {scanned, linked, links, skipped}.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json(silent=True) or {}
        context_domain = data.get("context_domain")
        dry_run = bool(data.get("dry_run", True))
        limit = data.get("limit")
        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                return json_error(
                    "limit must be an integer", status=400, code="bad_request"
                )

        keys = keyParser(session)
        if not keys.get("OPENROUTER_API_KEY"):
            return json_error(
                "API key required for entity backfill",
                status=400,
                code="api_key_required",
            )

        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.backfill_entities(
            context_domain=context_domain, dry_run=dry_run, limit=limit
        )
        return jsonify({"success": True, "dry_run": dry_run, **result})
    except Exception as e:
        logger.error(f"Error in pkb_backfill_entities: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_claim_route(claim_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_claim(claim_id)
        if result.success:
            return jsonify({"claim": serialize_claim(result.data)})

        return json_error("Claim not found", status=404, code="claim_not_found")
    except Exception as e:
        logger.error(f"Error in pkb_get_claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/provenance", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_claim_provenance_route(claim_id: str):
    """Provenance for a claim — "why do I know this?" (Workstream E1)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_claim_provenance(claim_id)
        if result.success:
            return jsonify({"provenance": result.data})

        return json_error("Claim not found", status=404, code="claim_not_found")
    except Exception as e:
        logger.error(f"Error in pkb_get_claim_provenance: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/consolidation/candidates", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def pkb_consolidation_candidates_route():
    """Clusters of near-duplicate claims proposed for merge (Workstream D2)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        threshold = request.args.get("threshold", type=float)
        limit = request.args.get("limit", default=50, type=int)
        result = api.find_consolidation_candidates(threshold=threshold, limit=limit)
        if result.success:
            return jsonify({"clusters": result.data})
        return json_error(
            "; ".join(result.errors) or "Consolidation unavailable",
            status=503, code="consolidation_unavailable",
        )
    except Exception as e:
        logger.error(f"Error in pkb_consolidation_candidates: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/consolidation/merge", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_consolidation_merge_route():
    """Merge a near-duplicate cluster into one canonical claim (Workstream D2)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json() or {}
        claim_ids = data.get("claim_ids")
        keep_id = data.get("keep_id")
        if not claim_ids or not isinstance(claim_ids, list) or len(claim_ids) < 2:
            return json_error(
                "claim_ids must be a list of at least two ids",
                status=400, code="bad_request",
            )

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.consolidate_claims(claim_ids, keep_id=keep_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Consolidation failed",
            status=400, code="consolidation_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_consolidation_merge: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/entities/duplicates", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def pkb_entity_duplicates_route():
    """Clusters of entity name variants proposed for merge (Workstream D3)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        entity_type = request.args.get("entity_type")
        threshold = request.args.get("threshold", type=float)
        result = api.find_entity_duplicates(entity_type=entity_type, threshold=threshold)
        if result.success:
            return jsonify({"clusters": result.data})
        return json_error(
            "; ".join(result.errors) or "Entity dedup failed",
            status=400, code="entity_dedup_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_entity_duplicates: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/entities/merge", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_entity_merge_route():
    """Merge a duplicate entity into a canonical one, keeping aliases (D3)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json() or {}
        source_id = data.get("source_id")
        target_id = data.get("target_id")
        if not source_id or not target_id:
            return json_error(
                "source_id and target_id are required",
                status=400, code="bad_request",
            )

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.merge_entities(source_id, target_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Entity merge failed",
            status=400, code="entity_merge_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_entity_merge: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/tags/duplicates", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def pkb_tag_duplicates_route():
    """Clusters of tag name variants proposed for merge (Workstream W6)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        threshold = request.args.get("threshold", type=float)
        result = api.find_tag_duplicates(threshold=threshold)
        if result.success:
            return jsonify({"clusters": result.data})
        return json_error(
            "; ".join(result.errors) or "Tag dedup failed",
            status=400, code="tag_dedup_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_tag_duplicates: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/tags/merge", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_tag_merge_route():
    """Merge a duplicate tag into a canonical one (Workstream W6)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json() or {}
        source_id = data.get("source_id")
        target_id = data.get("target_id")
        if not source_id or not target_id:
            return json_error(
                "source_id and target_id are required",
                status=400, code="bad_request",
            )

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.merge_tags(source_id, target_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Tag merge failed",
            status=400, code="tag_merge_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_tag_merge: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/cleanup", methods=["POST"])
@limiter.limit("4 per minute")
@login_required
def pkb_cleanup_route():
    """
    Memory Cleanup orchestrator (Workstream W9).

    Body (optional): {"apply": bool, "use_llm": bool}. With apply=false (default)
    runs safe maintenance (sweep + overview refresh) and returns dedup proposals
    for review. With apply=true also merges the suggested duplicate clusters.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json(silent=True) or {}
        apply_changes = bool(data.get("apply", False))
        use_llm = data.get("use_llm")

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.run_memory_cleanup(apply=apply_changes, use_llm=use_llm)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Memory cleanup failed",
            status=400, code="cleanup_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_cleanup: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/sweep", methods=["POST"])
@limiter.limit("6 per minute")
@login_required
def pkb_sweep_route():
    """Run the lifecycle sweep on demand (Workstream F1): expiry + dormancy."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.run_lifecycle_sweep()
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Sweep failed",
            status=500, code="sweep_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_sweep: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/notifications", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_notifications_route():
    """Soon-to-expire and newly-dormant claims for the user (Workstream F4)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        within_days = request.args.get("within_days", type=int)
        result = api.get_lifecycle_notifications(within_days=within_days)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Notifications failed",
            status=500, code="notifications_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_notifications: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/export", methods=["GET"])
@limiter.limit("6 per minute")
@login_required
def pkb_export_route():
    """Export the user's full PKB as a JSON envelope (Workstream G3)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )
        result = api.export_data()
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Export failed",
            status=500, code="export_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_export: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/import", methods=["POST"])
@limiter.limit("6 per minute")
@login_required
def pkb_import_route():
    """Import a PKB export envelope into the user's PKB (Workstream G3).

    Request body: the export envelope, optionally with `mode` (default merge).
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        body = request.get_json(silent=True) or {}
        if "data" not in body:
            return json_error(
                "Request body must be an export envelope with a 'data' key",
                status=400, code="invalid_payload",
            )
        mode = body.get("mode", "merge")

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )
        result = api.import_data(body, mode=mode)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Import failed",
            status=400, code="import_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_import: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/audit", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_audit_route():
    """Return the user's append-only audit log, newest first (Workstream G3).

    Query params: limit, offset, action (optional filter).
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )
        limit = request.args.get("limit", default=100, type=int)
        offset = request.args.get("offset", default=0, type=int)
        action = request.args.get("action", type=str)
        result = api.get_audit_log(limit=limit, offset=offset, action=action)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Audit read failed",
            status=500, code="audit_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_audit: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>", methods=["PUT"])
@limiter.limit("15 per minute")
@login_required
def pkb_update_claim_route(claim_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json() or {}
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)

        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        # Preserve legacy behavior: accept partial updates via patch dict.
        patch = {}
        for field in [
            "statement",
            "claim_type",
            "context_domain",
            "status",
            "confidence",
            "meta_json",
            "valid_from",
            "valid_to",
            "claim_types",
            "context_domains",
            "possible_questions",
            "friendly_id",
        ]:
            if field in data:
                patch[field] = data[field]

        if not patch:
            return json_error("No fields to update", status=400, code="bad_request")

        result = api.edit_claim(claim_id, **patch)

        if result.success:
            _fire_overview_update(email, "edit", [result.data])
            return jsonify({"success": True, "claim": serialize_claim(result.data)})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_update_claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>", methods=["DELETE"])
@limiter.limit("15 per minute")
@login_required
def pkb_delete_claim_route(claim_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.delete_claim(claim_id)
        if result.success:
            _fire_overview_update(email, "delete", [result.data] if result.data else [])
            return jsonify({"success": True, "message": "Claim retracted successfully"})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_delete_claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === NL Command Endpoint (Agentic PKB Operations) ===
# =============================================================================


@pkb_bp.route("/pkb/nl_command", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_nl_command_route():
    """Process a natural language command against the PKB.

    Request body:
        command (str): Natural language command text.
        model (str, optional): LLM model override.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return json_error(
            "command is required", status=400, code="missing_command"
        )

    model = data.get("model", None)

    try:
        from truth_management_system.interface.nl_agent import PKBNLAgent
        from endpoints.utils import keyParser

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        keys = keyParser({})
        db, config = get_pkb_db()
        overview_manager = PKBOverviewManager(db, keys, config)
        agent = PKBNLAgent(api=api, keys=keys, model=model, overview_manager=overview_manager)
        result = agent.process(command)
        return jsonify(result.to_dict())
    except Exception as e:
        logger.error(f"Error in pkb_nl_command: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )

# =============================================================================
# === Pinning Endpoints (Deliberate Memory Attachment) ===
# =============================================================================


@pkb_bp.route("/pkb/claims/<claim_id>/pin", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_pin_claim_route(claim_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        data = request.get_json() or {}
        pin = data.get("pin", True)
        result = api.pin_claim(claim_id, pin=pin)

        if result.success:
            claim = result.data
            return jsonify(
                {
                    "success": True,
                    "pinned": pin,
                    "claim": {
                        "claim_id": claim.claim_id,
                        "statement": claim.statement,
                        "claim_type": claim.claim_type,
                        "context_domain": claim.context_domain,
                        "status": claim.status,
                        "meta_json": claim.meta_json,
                        "updated_at": claim.updated_at,
                    },
                }
            )

        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_pin_claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/pinned", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_pinned_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        limit = request.args.get("limit", 50, type=int)
        result = api.get_pinned_claims(limit=limit)

        if result.success:
            claims = [
                {
                    "claim_id": c.claim_id,
                    "statement": c.statement,
                    "claim_type": c.claim_type,
                    "context_domain": c.context_domain,
                    "status": c.status,
                    "confidence": c.confidence,
                    "meta_json": c.meta_json,
                    "updated_at": c.updated_at,
                    "created_at": c.created_at,
                }
                for c in result.data
            ]
            return jsonify(
                {"success": True, "pinned_claims": claims, "count": len(claims)}
            )

        return json_error("; ".join(result.errors), status=500, code="internal_error")
    except Exception as e:
        logger.error(f"Error in pkb_get_pinned: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Conversation-Level Pinning Endpoints ===
# =============================================================================


@pkb_bp.route("/pkb/conversation/<conv_id>/pin", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_conversation_pin_route(conv_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json() or {}
        claim_id = data.get("claim_id")
        pin = data.get("pin", True)
        if not claim_id:
            return json_error("claim_id is required", status=400, code="bad_request")

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_claim(claim_id)
        if not result.success:
            return json_error("Claim not found", status=404, code="claim_not_found")

        if pin:
            add_conversation_pinned_claim(conv_id, claim_id)
        else:
            remove_conversation_pinned_claim(conv_id, claim_id)

        pinned_ids = list(get_conversation_pinned_claims(conv_id))
        return jsonify(
            {
                "success": True,
                "conversation_id": conv_id,
                "pinned": pin,
                "claim_id": claim_id,
                "pinned_claim_ids": pinned_ids,
                "count": len(pinned_ids),
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_conversation_pin: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/conversation/<conv_id>/pinned", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_conversation_get_pinned_route(conv_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        pinned_ids = list(get_conversation_pinned_claims(conv_id))

        claims = []
        if pinned_ids:
            result = api.get_claims_by_ids(pinned_ids)
            if result.success and result.data:
                for claim in result.data:
                    if claim:
                        claims.append(
                            {
                                "claim_id": claim.claim_id,
                                "statement": claim.statement,
                                "claim_type": claim.claim_type,
                                "context_domain": claim.context_domain,
                                "status": claim.status,
                            }
                        )

        return jsonify(
            {
                "success": True,
                "conversation_id": conv_id,
                "pinned_claim_ids": pinned_ids,
                "pinned_claims": claims,
                "count": len(pinned_ids),
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_conversation_get_pinned: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/conversation/<conv_id>/pinned", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def pkb_conversation_clear_pinned_route(conv_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    _email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        clear_conversation_pinned_claims(conv_id)
        return jsonify(
            {
                "success": True,
                "conversation_id": conv_id,
                "message": "All conversation-pinned claims cleared",
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_conversation_clear_pinned: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Search / Entities / Tags / Conflicts ===
# =============================================================================


@pkb_bp.route("/pkb/search", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def pkb_search_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        query = data.get("query")
        if not query:
            return json_error(
                "Missing required field: query", status=400, code="bad_request"
            )

        strategy = data.get("strategy", "hybrid")
        k = data.get("k", 20)
        filters = data.get("filters", {})

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.search(query, strategy=strategy, k=k, filters=filters)
        if result.success:
            return jsonify(
                {
                    "results": [serialize_search_result(r) for r in result.data],
                    "count": len(result.data),
                }
            )
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_search: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/entities", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_entities_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        filters = {}
        if request.args.get("entity_type"):
            filters["entity_type"] = request.args.get("entity_type")

        limit = int(request.args.get("limit", 100))
        entities = api.entities.list(filters=filters, limit=limit, order_by="name")
        return jsonify(
            {
                "entities": [serialize_entity(e) for e in entities],
                "count": len(entities),
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_list_entities: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/entities/<entity_id>/claims", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_entity_claims_route(entity_id):
    """Get all claims linked to a specific entity.

    Returns serialized claims with count so the frontend can render them
    under an expandable entity card.

    Path params:
        entity_id: UUID of the entity.
    Query params:
        limit (int, default 200): max claims to return.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        limit = int(request.args.get("limit", 200))
        claims = api.claims.get_by_entity(entity_id)
        claims = claims[:limit]
        return jsonify(
            {"claims": [serialize_claim(c) for c in claims], "count": len(claims)}
        )
    except Exception as e:
        logger.error(f"Error in pkb_entity_claims: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/tags", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_tags_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        limit = int(request.args.get("limit", 100))
        tags = api.tags.list(limit=limit, order_by="name")
        return jsonify({"tags": [serialize_tag(t) for t in tags], "count": len(tags)})
    except Exception as e:
        logger.error(f"Error in pkb_list_tags: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/tags/<tag_id>/claims", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_tag_claims_route(tag_id):
    """Get all claims linked to a specific tag.

    Returns serialized claims with count so the frontend can render them
    under an expandable tag card.

    Path params:
        tag_id: UUID of the tag.
    Query params:
        limit (int, default 200): max claims to return.
        include_children (bool, default false): include claims from child tags.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        limit = int(request.args.get("limit", 200))
        include_children = (
            request.args.get("include_children", "false").lower() == "true"
        )
        claims = api.claims.get_by_tag(tag_id, include_children=include_children)
        claims = claims[:limit]
        return jsonify(
            {"claims": [serialize_claim(c) for c in claims], "count": len(claims)}
        )
    except Exception as e:
        logger.error(f"Error in pkb_tag_claims: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/tags", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_create_tag_route():
    """Create a new tag.

    Body:
        name (str, required): Tag name.
        parent_tag_id (str, optional): Parent tag UUID for nesting.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        data = request.get_json()
        name = (data.get("name") or "").strip()
        if not name:
            return json_error(
                "Missing required field: name", status=400, code="bad_request"
            )

        parent_tag_id = data.get("parent_tag_id")
        result = api.add_tag(name, parent_tag_id=parent_tag_id)
        if result.success:
            return jsonify({"success": True, "tag": serialize_tag(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error creating tag: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Claim-Tag Linking Endpoints ===
# =============================================================================


@pkb_bp.route("/pkb/claims/<claim_id>/tags", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_claim_tags_route(claim_id):
    """Get all tags linked to a claim.

    Returns serialized tags so the frontend can show which tags a claim has
    and pre-check checkboxes in the tag linking panel.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_claim_tags_list(claim_id)
        if result.success:
            return jsonify(
                {
                    "success": True,
                    "tags": [serialize_tag(t) for t in result.data],
                    "count": len(result.data),
                }
            )
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error getting tags for claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/tags", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_link_tag_to_claim(claim_id):
    """Link a tag to a claim.

    Body:
        tag_id (str, required): UUID of the tag to link.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        tag_id = data.get("tag_id")
        if not tag_id:
            return json_error(
                "Missing required field: tag_id", status=400, code="bad_request"
            )

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.link_tag_to_claim(claim_id, tag_id)
        if result.success:
            tag = api.tags.get(tag_id)
            claim = api.claims.get(claim_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "tag",
                "object_name": tag.name if tag else tag_id,
                "claim_statement": claim.statement if claim else "",
            })
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error linking tag to claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/tags/<tag_id>", methods=["DELETE"])
@limiter.limit("15 per minute")
@login_required
def pkb_unlink_tag_from_claim(claim_id, tag_id):
    """Unlink a tag from a claim."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.unlink_tag_from_claim(claim_id, tag_id)
        if result.success:
            tag = api.tags.get(tag_id)
            claim = api.claims.get(claim_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "tag",
                "object_name": tag.name if tag else tag_id,
                "claim_statement": claim.statement if claim else "",
            })
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error unlinking tag from claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/conflicts", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def pkb_list_conflicts_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_open_conflicts()
        if result.success:
            return jsonify(
                {
                    "conflicts": [serialize_conflict_set(c) for c in result.data],
                    "count": len(result.data),
                }
            )
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_list_conflicts: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/conflicts/<conflict_id>/resolve", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_resolve_conflict_route(conflict_id: str):
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        resolution_notes = data.get("resolution_notes")
        if not resolution_notes:
            return json_error(
                "Missing required field: resolution_notes",
                status=400,
                code="bad_request",
            )

        winning_claim_id = data.get("winning_claim_id")
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.resolve_conflict_set(
            conflict_id, resolution_notes, winning_claim_id
        )
        if result.success:
            return jsonify(
                {"success": True, "conflict": serialize_conflict_set(result.data)}
            )
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_resolve_conflict: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Memory Update Proposal / Text Ingestion / Execute Plans ===
# =============================================================================


@pkb_bp.route("/pkb/propose_updates", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_propose_updates_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        conversation_summary = data.get("conversation_summary", "")
        user_message = data.get("user_message", "")
        assistant_message = data.get("assistant_message", "")
        extraction_mode = data.get("extraction_mode", "relaxed")
        if extraction_mode not in ("relaxed", "aggressive"):
            extraction_mode = "relaxed"
        recent_turns = data.get("recent_turns", [])  # [{"user": ..., "assistant": ...}, ...]
        conversation_id = data.get("conversation_id")  # Optional; provenance (E1) + future context linking
        message_id = data.get("message_id")  # Optional; provenance (E1) — the originating message

        if not user_message:
            return json_error(
                "Missing required field: user_message", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        distiller = ConversationDistiller(api, keys, api.config, extraction_mode=extraction_mode)
        plan = distiller.extract_and_propose(
            conversation_summary=conversation_summary,
            user_message=user_message,
            assistant_message=assistant_message or "",
            recent_turns=recent_turns,
            source_conversation_id=conversation_id,
            source_message_id=message_id,
        )

        # Silently store short-term memories (no user approval needed)
        stm_stored = 0
        stm_reinforced = 0
        if plan and plan.short_term_candidates:
            # Get existing STM for cross-conversation reinforcement detection
            existing_stm = []
            existing_result = api.get_active_short_term_memories(limit=api.config.stm_max_per_user)
            if existing_result.success and existing_result.data:
                existing_stm = existing_result.data

            for stc in plan.short_term_candidates:
                # Check for similar existing STM from a DIFFERENT conversation
                reinforced = False
                if existing_stm and conversation_id:
                    for mem in existing_stm:
                        if mem.get("conversation_id") == conversation_id:
                            continue  # Same conversation — skip
                        # Simple word-overlap similarity check
                        from difflib import SequenceMatcher
                        ratio = SequenceMatcher(None, stc.statement.lower(), mem["statement"].lower()).ratio()
                        if ratio >= api.config.stm_reinforcement_threshold:
                            api.reinforce_short_term_memory(mem["memory_id"])
                            stm_reinforced += 1
                            reinforced = True
                            break

                if not reinforced:
                    # Also skip if same conversation already has very similar STM
                    skip = False
                    if existing_stm and conversation_id:
                        for mem in existing_stm:
                            if mem.get("conversation_id") != conversation_id:
                                continue
                            from difflib import SequenceMatcher
                            ratio = SequenceMatcher(None, stc.statement.lower(), mem["statement"].lower()).ratio()
                            if ratio >= api.config.stm_reinforcement_threshold:
                                skip = True
                                break
                    if not skip:
                        result = api.add_short_term_memory(
                            statement=stc.statement,
                            conversation_id=conversation_id or "",
                            importance=stc.importance,
                            ttl_class=stc.ttl,
                            meta_json={"reasoning": stc.reasoning,
                                       "source_conversation_title": conversation_summary[:100] if conversation_summary else ""},
                        )
                        if result.success:
                            stm_stored += 1
            if stm_stored or stm_reinforced:
                logger.info(f"STM for {email}: stored={stm_stored}, reinforced={stm_reinforced}")

        if not plan or len(plan.candidates) == 0:
            return jsonify(
                {"has_updates": False, "proposed_actions": [], "user_prompt": None,
                 "stm_stored": stm_stored, "stm_reinforced": stm_reinforced}
            )

        plan_id = str(uuid.uuid4())
        _memory_update_plans[plan_id] = plan

        proposed_actions = []
        # Build a lookup from candidate statement -> ProposedAction for O(1) access
        pa_by_statement = {pa.candidate.statement: pa for pa in plan.proposed_actions}
        for i, candidate in enumerate(plan.candidates):
            pa = pa_by_statement.get(candidate.statement)
            action = {
                "index": i,
                "statement": candidate.statement,
                "claim_type": candidate.claim_type,
                "context_domain": candidate.context_domain,
                "action": pa.action if pa else "add",
                "valid_from": candidate.valid_from,
                "valid_to": candidate.valid_to,
                "tags": candidate.tags or [],
                "reason": getattr(candidate, 'reason', None) or (pa.reason if pa else ""),
            }
            if pa and pa.existing_claim:
                action["existing_claim_id"] = pa.existing_claim.claim_id
                action["existing_statement"] = pa.existing_claim.statement
            proposed_actions.append(action)

        # Tiered persistence: serialize auto-saved and skipped
        auto_saved_response = []
        for item in getattr(plan, 'auto_saved', []):
            pa = item.get("action")
            res = item.get("result")
            auto_saved_response.append({
                "statement": pa.candidate.statement if pa else "",
                "claim_type": pa.candidate.claim_type if pa else "",
                "claim_id": getattr(res, 'object_id', None),
                "reason": item.get("reason", ""),
            })
        skipped_response = []
        for item in getattr(plan, 'skipped', []):
            pa = item.get("action")
            skipped_response.append({
                "statement": pa.candidate.statement if pa else "",
                "reason": item.get("reason", ""),
            })

        return jsonify(
            {
                "has_updates": True,
                "plan_id": plan_id,
                "proposed_actions": proposed_actions,
                "user_prompt": plan.user_prompt,
                "stm_stored": stm_stored,
                "stm_reinforced": stm_reinforced,
                "auto_saved": auto_saved_response,
                "skipped": skipped_response,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_propose_updates: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/ingest_text", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def pkb_ingest_text_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        text = data.get("text", "").strip()
        if not text:
            return json_error(
                "Missing required field: text", status=400, code="bad_request"
            )

        max_size = 50 * 1024
        if len(text) > max_size:
            return json_error(
                f"Text too large. Maximum size is {max_size // 1024}KB.",
                status=400,
                code="bad_request",
            )

        default_claim_type = data.get("default_claim_type", "fact")
        default_domain = data.get("default_domain", "personal")
        use_llm = data.get("use_llm", True)

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        distiller = TextIngestionDistiller(api, keys)
        plan = distiller.ingest_and_propose(
            text=text,
            default_claim_type=default_claim_type,
            default_domain=default_domain,
            use_llm_parsing=use_llm,
        )

        if not plan.proposals:
            return jsonify(
                {
                    "has_proposals": False,
                    "proposals": [],
                    "summary": plan.summary,
                    "total_parsed": plan.total_lines_parsed,
                }
            )

        _text_ingestion_plans[plan.plan_id] = plan

        proposals = []
        for i, proposal in enumerate(plan.proposals):
            proposals.append(
                {
                    "index": i,
                    "statement": proposal.candidate.statement,
                    "claim_type": proposal.candidate.claim_type,
                    "context_domain": proposal.candidate.context_domain,
                    "action": proposal.action,
                    "reason": proposal.reason,
                    "confidence": proposal.candidate.confidence,
                    "editable": proposal.editable,
                    "existing_claim_id": proposal.existing_claim.claim_id
                    if proposal.existing_claim
                    else None,
                    "existing_statement": proposal.existing_claim.statement
                    if proposal.existing_claim
                    else None,
                    "similarity_score": proposal.similarity_score,
                    "tags": getattr(proposal.candidate, "tags", []) or [],
                    "possible_questions": getattr(
                        proposal.candidate, "possible_questions", []
                    )
                    or [],
                    "entities": getattr(proposal.candidate, "entities", []) or [],
                }
            )

        return jsonify(
            {
                "has_proposals": True,
                "plan_id": plan.plan_id,
                "proposals": proposals,
                "summary": plan.summary,
                "total_parsed": plan.total_lines_parsed,
                "add_count": plan.add_count,
                "edit_count": plan.edit_count,
                "skip_count": plan.skip_count,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_ingest_text: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/execute_ingest", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_execute_ingest_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        plan_id = data.get("plan_id")
        approved = data.get("approved", [])

        if not plan_id:
            return json_error(
                "Missing required field: plan_id", status=400, code="bad_request"
            )

        plan = _text_ingestion_plans.get(plan_id)
        if not plan:
            return json_error("Plan not found or expired", status=404, code="not_found")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        distiller = TextIngestionDistiller(api, keys)
        result = distiller.execute_plan(plan, approved)

        results = []
        for exec_result in result.execution_results:
            results.append(
                {
                    "action": exec_result.action,
                    "success": exec_result.success,
                    "claim_id": exec_result.object_id,
                    "errors": exec_result.errors,
                }
            )

        del _text_ingestion_plans[plan_id]

        # One consolidated overview update for all successfully ingested claims
        success_ids = [r["claim_id"] for r in results if r["success"] and r.get("claim_id")]
        if success_ids:
            ingested_claims = []
            try:
                res = api.get_claims_by_ids(success_ids)
                if res.success:
                    ingested_claims = [c for c in res.data if c]
            except Exception:
                pass
            _fire_overview_update(email, "bulk", ingested_claims)

        return jsonify(
            {
                "executed_count": result.added_count + result.edited_count,
                "added_count": result.added_count,
                "edited_count": result.edited_count,
                "failed_count": result.failed_count,
                "results": results,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_execute_ingest: {e}")
        traceback.print_exc()
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/execute_updates", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_execute_updates_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        plan_id = data.get("plan_id")
        if not plan_id:
            return json_error(
                "Missing required field: plan_id", status=400, code="bad_request"
            )

        plan = _memory_update_plans.get(plan_id)
        if not plan:
            return json_error("Plan not found or expired", status=404, code="not_found")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        approved_list = data.get("approved", None)
        approved_indices = data.get("approved_indices", [])

        items_to_process = []
        if approved_list is not None:
            for item in approved_list:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(plan.candidates):
                    candidate = plan.candidates[idx]
                    items_to_process.append(
                        {
                            "index": idx,
                            "statement": item.get("statement", candidate.statement),
                            "claim_type": item.get("claim_type", candidate.claim_type),
                            "context_domain": item.get(
                                "context_domain", candidate.context_domain
                            ),
                            "valid_from": item.get("valid_from") or getattr(candidate, "valid_from", None),
                            "valid_to": item.get("valid_to") or getattr(candidate, "valid_to", None),
                            "tags": item.get("tags") or getattr(candidate, "tags", []),
                        }
                    )
        else:
            for idx in approved_indices:
                if 0 <= idx < len(plan.candidates):
                    candidate = plan.candidates[idx]
                    items_to_process.append(
                        {
                            "index": idx,
                            "statement": candidate.statement,
                            "claim_type": candidate.claim_type,
                            "context_domain": candidate.context_domain,
                            "valid_from": getattr(candidate, "valid_from", None),
                            "valid_to": getattr(candidate, "valid_to", None),
                            "tags": getattr(candidate, "tags", []),
                        }
                    )

        results = []
        added_count = 0
        edited_count = 0

        for item in items_to_process:
            idx = item["index"]
            statement = item["statement"]
            claim_type = item["claim_type"]
            context_domain = item["context_domain"]

            action = "add"
            existing_claim_id = None
            if plan.proposed_actions and idx < len(plan.proposed_actions):
                pa = plan.proposed_actions[idx]
                action = pa.action  # ProposedAction.action is the string
                if pa.existing_claim:
                    existing_claim_id = pa.existing_claim.claim_id

            if action == "edit" and existing_claim_id:
                result = api.edit_claim(
                    existing_claim_id,
                    statement=statement,
                    claim_type=claim_type,
                    context_domain=context_domain,
                )
                results.append(
                    {
                        "action": "edit",
                        "claim_id": existing_claim_id,
                        "statement": statement,
                        "success": result.success,
                        "errors": result.errors,
                    }
                )
                if result.success:
                    edited_count += 1
            else:
                candidate = plan.candidates[idx]
                add_kwargs = {
                    "statement": statement,
                    "claim_type": claim_type,
                    "context_domain": context_domain,
                    "tags": item.get("tags") or (candidate.tags if hasattr(candidate, "tags") else []),
                    "auto_extract": False,
                }
                if item.get("valid_from"):
                    add_kwargs["valid_from"] = item["valid_from"]
                if item.get("valid_to"):
                    add_kwargs["valid_to"] = item["valid_to"]
                result = api.add_claim(**add_kwargs)
                results.append(
                    {
                        "action": "add",
                        "claim_id": result.object_id if result.success else None,
                        "statement": statement,
                        "success": result.success,
                        "errors": result.errors,
                    }
                )
                if result.success:
                    added_count += 1

        # Emit low-priority notifications for confirmed items
        for r in results:
            if r["success"] and r.get("claim_id"):
                try:
                    api.create_notification(
                        priority="low", category="claim_confirmed",
                        title=f"Confirmed: {r['statement'][:80]}",
                        body=r["statement"],
                        object_type="claim", object_id=r["claim_id"],
                        available_actions=["dismiss"],
                        source="system",
                    )
                    # Resolve any pending confirm_required notification for same statement
                    from truth_management_system.utils import now_iso as _now_iso
                    conn = api.db.connect()
                    conn.execute(
                        "UPDATE pkb_notifications SET action_taken = 'approved_via_modal', "
                        "resolved_at = ? WHERE user_email = ? AND category = 'confirm_required' "
                        "AND resolved_at IS NULL AND title LIKE ?",
                        (_now_iso(), email, f"Confirm: {r['statement'][:80]}%")
                    )
                    conn.commit()
                except Exception:
                    pass

        del _memory_update_plans[plan_id]

        # One consolidated overview update for all successfully modified claims
        successful_claim_ids = [r["claim_id"] for r in results if r["success"] and r.get("claim_id")]
        if successful_claim_ids:
            successful_claims = []
            try:
                res = api.get_claims_by_ids(successful_claim_ids)
                if res.success:
                    successful_claims = [c for c in res.data if c]
            except Exception:
                pass
            _fire_overview_update(email, "bulk", successful_claims)

        return jsonify(
            {
                "executed_count": len([r for r in results if r["success"]]),
                "added_count": added_count,
                "edited_count": edited_count,
                "failed_count": len([r for r in results if not r["success"]]),
                "results": results,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_execute_updates: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Relevant Context Endpoint (for Conversation.py integration) ===
# =============================================================================


@pkb_bp.route("/pkb/relevant_context", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def pkb_get_relevant_context_route():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        query = data.get("query", "")
        conversation_summary = data.get("conversation_summary", "")
        k = data.get("k", 10)

        if not query:
            return json_error(
                "Missing required field: query", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        enhanced_query = query
        if conversation_summary:
            enhanced_query = f"{conversation_summary}\n\nCurrent query: {query}"

        result = api.search(enhanced_query, strategy="hybrid", k=k)
        if not result.success or not result.data:
            return jsonify({"claims": [], "formatted_context": ""})

        claims = result.data
        context_lines = []
        for sr in claims[:k]:
            claim = sr.claim
            prefix = f"[{claim.claim_type}]" if claim.claim_type else ""
            context_lines.append(f"- {prefix} {claim.statement}")

        formatted_context = "\n".join(context_lines)
        return jsonify(
            {
                "claims": [serialize_claim(sr.claim) for sr in claims[:k]],
                "formatted_context": formatted_context,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_get_relevant_context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Friendly ID Lookup Endpoint (v0.5) ===
# =============================================================================


@pkb_bp.route("/pkb/claims/by-friendly-id/<friendly_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_claim_by_friendly_id(friendly_id):
    """Get a claim by its user-facing friendly_id.

    Also supports claim_number (e.g., 'claim_42', '42') and UUID as fallbacks.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        # Use the universal resolver that handles all formats
        claim = api.resolve_claim_identifier(friendly_id)
        if claim:
            return jsonify({"success": True, "claim": serialize_claim(claim)})
        return json_error(
            f"No claim found with identifier: {friendly_id}",
            status=404,
            code="not_found",
        )
    except Exception as e:
        logger.error(f"Error getting claim by friendly_id: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Autocomplete Endpoint (v0.5) ===
# =============================================================================


@pkb_bp.route("/pkb/autocomplete", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def pkb_autocomplete():
    """Search all PKB object types by friendly_id prefix for autocomplete.

    Returns memories, contexts, entities, tags, and domains matching the prefix.

    Query params:
        q: prefix string to search for
        limit: max results per category (default 10)
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    empty_result = {
        "memories": [],
        "contexts": [],
        "entities": [],
        "tags": [],
        "domains": [],
    }
    try:
        q = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 10)), 20)

        if not q or len(q) < 1:
            return jsonify(empty_result)

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.autocomplete(q, limit=limit)
        if result.success:
            return jsonify(result.data)
        return jsonify(empty_result)
    except Exception as e:
        logger.error(f"Error in autocomplete: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Reference Resolution Endpoint (v0.5) ===
# =============================================================================


@pkb_bp.route("/pkb/resolve/<reference_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_resolve_reference(reference_id):
    """Resolve a @reference_id to claims. Tries memory first, then context."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.resolve_reference(reference_id)
        if result.success:
            data = result.data
            return jsonify(
                {
                    "success": True,
                    "type": data["type"],
                    "claims": [serialize_claim(c) for c in data["claims"]],
                    "source_id": data["source_id"],
                    "source_name": data["source_name"],
                }
            )
        return json_error(
            result.errors[0] if result.errors else "Not found",
            status=404,
            code="not_found",
        )
    except Exception as e:
        logger.error(f"Error resolving reference: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Context CRUD Endpoints (v0.5) ===
# =============================================================================


@pkb_bp.route("/pkb/contexts", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_contexts():
    """List user's contexts."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        contexts_with_counts = api.contexts.get_with_claim_count(limit=200)
        result = []
        for ctx, count in contexts_with_counts:
            ctx_dict = serialize_context(ctx)
            ctx_dict["claim_count"] = count
            result.append(ctx_dict)

        return jsonify({"success": True, "contexts": result})
    except Exception as e:
        logger.error(f"Error listing contexts: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_create_context():
    """Create a new context."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        if not name:
            return json_error(
                "Missing required field: name", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.add_context(
            name=name,
            friendly_id=data.get("friendly_id"),
            description=data.get("description"),
            parent_context_id=data.get("parent_context_id"),
            claim_ids=data.get("claim_ids"),
        )

        if result.success:
            return jsonify({"success": True, "context": serialize_context(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error creating context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_context(context_id):
    """Get a context by ID with children and claim count."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_context(context_id)
        if result.success:
            ctx_dict = serialize_context(result.data)
            children = api.contexts.get_children(context_id)
            claims = api.contexts.get_claims(context_id)
            ctx_dict["children"] = [serialize_context(c) for c in children]
            ctx_dict["claim_count"] = len(claims)
            ctx_dict["claims"] = [serialize_claim(c) for c in claims]
            return jsonify({"success": True, "context": ctx_dict})
        return json_error("Context not found", status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error getting context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>", methods=["PUT"])
@limiter.limit("15 per minute")
@login_required
def pkb_update_context(context_id):
    """Update a context."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.edit_context(context_id, **data)
        if result.success:
            return jsonify({"success": True, "context": serialize_context(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error updating context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>", methods=["DELETE"])
@limiter.limit("15 per minute")
@login_required
def pkb_delete_context(context_id):
    """Delete a context (claims remain, just unlinked)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.delete_context(context_id)
        if result.success:
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error deleting context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>/claims", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_add_claim_to_context(context_id):
    """Link a claim to a context.

    The claim_id field accepts any identifier format:
    - UUID claim_id (e.g., "550e8400-...")
    - claim_number (e.g., "42" or "claim_42" or "@claim_42")
    - friendly_id (e.g., "prefer_morning_a3f2" or "@prefer_morning_a3f2")
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        claim_identifier = data.get("claim_id")
        if not claim_identifier:
            return json_error(
                "Missing required field: claim_id", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        # Resolve any identifier format to a real claim
        claim = api.resolve_claim_identifier(claim_identifier)
        if not claim:
            return json_error(
                f"No claim found matching: {claim_identifier}",
                status=404,
                code="not_found",
            )

        result = api.add_claim_to_context(context_id, claim.claim_id)
        if result.success:
            ctx = api.contexts.get(context_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "context",
                "object_name": ctx.name if ctx else context_id,
                "claim_statement": claim.statement,
            })
            return jsonify({"success": True, "claim_id": claim.claim_id})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error adding claim to context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>/claims/<claim_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def pkb_remove_claim_from_context(context_id, claim_id):
    """Remove a claim from a context."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.remove_claim_from_context(context_id, claim_id)
        if result.success:
            claim = api.claims.get(claim_id)
            ctx = api.contexts.get(context_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "context",
                "object_name": ctx.name if ctx else context_id,
                "claim_statement": claim.statement if claim else "",
            })
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error removing claim from context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/contexts/<context_id>/resolve", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def pkb_resolve_context(context_id):
    """Get all claims (recursive) under a context and its sub-contexts."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.resolve_context(context_id)
        if result.success:
            return jsonify(
                {
                    "success": True,
                    "claims": [serialize_claim(c) for c in result.data],
                    "count": len(result.data),
                }
            )
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error resolving context: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Entity Management Endpoints (v0.5) ===
# =============================================================================


@pkb_bp.route("/pkb/entities", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_create_entity():
    """Create a new entity."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        entity_type = data.get("entity_type", "other")
        if not name:
            return json_error(
                "Missing required field: name", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.add_entity(
            name=name, entity_type=entity_type, meta_json=data.get("meta_json")
        )
        if result.success:
            return jsonify({"success": True, "entity": serialize_entity(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error creating entity: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/entities", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_claim_entities(claim_id):
    """Get entities linked to a claim."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.get_claim_entities_list(claim_id)
        if result.success:
            entities = [
                {"entity": serialize_entity(entity), "role": role}
                for entity, role in result.data
            ]
            return jsonify({"success": True, "entities": entities})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error getting claim entities: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/entities", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_link_entity_to_claim(claim_id):
    """Link an entity to a claim with a role."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        entity_id = data.get("entity_id")
        role = data.get("role", "mentioned")
        if not entity_id:
            return json_error(
                "Missing required field: entity_id", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.link_entity_to_claim(claim_id, entity_id, role)
        if result.success:
            entity = api.entities.get(entity_id)
            claim = api.claims.get(claim_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "entity",
                "object_name": entity.name if entity else entity_id,
                "claim_statement": claim.statement if claim else "",
            })
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error linking entity to claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/entities/<entity_id>", methods=["DELETE"])
@limiter.limit("15 per minute")
@login_required
def pkb_unlink_entity_from_claim(claim_id, entity_id):
    """Unlink an entity from a claim."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        role = request.args.get("role")
        result = api.unlink_entity_from_claim(claim_id, entity_id, role)
        if result.success:
            entity = api.entities.get(entity_id)
            claim = api.claims.get(claim_id)
            _fire_overview_update(email, "link", [], link_metadata={
                "object_type": "entity",
                "object_name": entity.name if entity else entity_id,
                "claim_statement": claim.statement if claim else "",
            })
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error unlinking entity from claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Claim-Context Linking Endpoints (v0.5.1) ===
# =============================================================================


@pkb_bp.route("/pkb/claims/<claim_id>/contexts", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_claim_contexts_route(claim_id):
    """Get all contexts that a claim belongs to.

    Returns serialized contexts so the frontend can pre-select them in the
    claim edit modal.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        contexts = api.contexts.get_contexts_for_claim(claim_id)
        return jsonify(
            {
                "contexts": [serialize_context(c) for c in contexts],
                "count": len(contexts),
            }
        )
    except Exception as e:
        logger.error(f"Error getting contexts for claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/claims/<claim_id>/contexts", methods=["PUT"])
@limiter.limit("15 per minute")
@login_required
def pkb_set_claim_contexts_route(claim_id):
    """Set (replace) the contexts for a claim.

    Diffs the current vs desired context list and adds/removes links as needed.

    Body:
        context_ids (list[str]): Desired context IDs. Empty list = remove all.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        data = request.get_json()
        desired_ids = set(data.get("context_ids", []))

        # Get current contexts for this claim
        current_contexts = api.contexts.get_contexts_for_claim(claim_id)
        current_ids = {c.context_id for c in current_contexts}

        # Add new links
        for cid in desired_ids - current_ids:
            api.contexts.add_claim(cid, claim_id)

        # Remove old links
        for cid in current_ids - desired_ids:
            api.contexts.remove_claim(cid, claim_id)

        return jsonify(
            {
                "success": True,
                "added": len(desired_ids - current_ids),
                "removed": len(current_ids - desired_ids),
            }
        )
    except Exception as e:
        logger.error(f"Error setting contexts for claim: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# === Dynamic Type & Domain Catalog Endpoints (v0.5.1) ===
# =============================================================================


@pkb_bp.route("/pkb/types", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_types_route():
    """List all valid claim types (system + user-defined)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        types = api.type_catalog.list()
        return jsonify({"types": types, "count": len(types)})
    except Exception as e:
        logger.error(f"Error listing types: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/types", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_add_type_route():
    """Add a custom claim type.

    Body:
        type_name (str): Machine-readable key.
        display_name (str, optional): Human-friendly label.
        description (str, optional): Optional description.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        type_name = data.get("type_name", "").strip().lower().replace(" ", "_")
        if not type_name:
            return json_error(
                "Missing required field: type_name", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.type_catalog.add(
            type_name=type_name,
            display_name=data.get("display_name"),
            description=data.get("description"),
        )
        return jsonify({"success": True, "type": result})
    except Exception as e:
        logger.error(f"Error adding type: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/domains", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_list_domains_route():
    """List all valid context domains (system + user-defined)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        domains = api.domain_catalog.list()
        return jsonify({"domains": domains, "count": len(domains)})
    except Exception as e:
        logger.error(f"Error listing domains: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


@pkb_bp.route("/pkb/domains", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_add_domain_route():
    """Add a custom context domain.

    Body:
        domain_name (str): Machine-readable key.
        display_name (str, optional): Human-friendly label.
        description (str, optional): Optional description.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        domain_name = data.get("domain_name", "").strip().lower().replace(" ", "_")
        if not domain_name:
            return json_error(
                "Missing required field: domain_name", status=400, code="bad_request"
            )

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error(
                "Failed to initialize PKB", status=500, code="pkb_init_failed"
            )

        result = api.domain_catalog.add(
            domain_name=domain_name,
            display_name=data.get("display_name"),
            description=data.get("description"),
        )
        return jsonify({"success": True, "domain": result})
    except Exception as e:
        logger.error(f"Error adding domain: {e}")
        return json_error(
            f"An error occurred: {str(e)}", status=500, code="internal_error"
        )


# =============================================================================
# PKB Overview routes (PKB Memory Overview feature, schema v11)
# =============================================================================

@pkb_bp.route("/pkb/overview", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def pkb_get_overview_route():
    """Return the per-user PKB overview, generating it on first access."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        db, config = get_pkb_db()
        keys = keyParser.get_api_keys()
        manager = PKBOverviewManager(db, keys, config)
        result = manager.get_overview(email)
        return jsonify({
            "content": result.content,
            "stats": {
                "claims": result.stats.claims,
                "contexts": result.stats.contexts,
                "entities": result.stats.entities,
                "tags": result.stats.tags,
            },
            "is_stale": result.is_stale,
            "last_updated": result.last_updated,
            "topics": manager.get_topics(email),
        })
    except Exception as e:
        logger.error(f"Error getting PKB overview: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/overview", methods=["PUT"])
@limiter.limit("20 per minute")
@login_required
def pkb_put_overview_route():
    """Manual save of overview content from the UI editor."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json()
        content = data.get("content", "")
        db, config = get_pkb_db()
        keys = keyParser.get_api_keys()
        manager = PKBOverviewManager(db, keys, config)
        manager.save(email, content)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving PKB overview: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/overview/regenerate", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def pkb_regenerate_overview_route():
    """Trigger full overview regeneration with streaming progress."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    import queue, threading
    import json as _json
    q = queue.Queue()

    def worker():
        try:
            db, config = get_pkb_db()
            keys = keyParser.get_api_keys()
            manager = PKBOverviewManager(db, keys, config)

            def cb(msg):
                q.put(("progress", msg))

            result = manager.generate_full(email, progress_cb=cb)
            q.put(("result", result))
        except Exception as e:
            logger.error(f"Error regenerating PKB overview: {e}")
            q.put(("error", str(e)))
        finally:
            q.put(("done", None))

    def generate():
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            kind, val = q.get()
            if kind == "done":
                break
            elif kind == "progress":
                yield _json.dumps({"type": "progress", "message": val}) + "\n"
            elif kind == "result":
                yield _json.dumps({
                    "type": "result",
                    "content": val.content,
                    "stats": {
                        "claims": val.stats.claims,
                        "contexts": val.stats.contexts,
                        "entities": val.stats.entities,
                        "tags": val.stats.tags,
                    },
                    "is_stale": val.is_stale,
                    "last_updated": val.last_updated,
                }) + "\n"
            elif kind == "error":
                yield _json.dumps({"type": "error", "message": val}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@pkb_bp.route("/pkb/overview/scan", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def pkb_scan_overview_route():
    """Trigger gap-scan of overview with streaming progress."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    import queue, threading
    import json as _json
    q = queue.Queue()

    def worker():
        try:
            db, config = get_pkb_db()
            keys = keyParser.get_api_keys()
            manager = PKBOverviewManager(db, keys, config)

            def cb(msg):
                q.put(("progress", msg))

            result = manager.scan_for_gaps(email, progress_cb=cb)
            q.put(("result", result))
        except Exception as e:
            logger.error(f"Error scanning PKB overview: {e}")
            q.put(("error", str(e)))
        finally:
            q.put(("done", None))

    def generate():
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            kind, val = q.get()
            if kind == "done":
                break
            elif kind == "progress":
                yield _json.dumps({"type": "progress", "message": val}) + "\n"
            elif kind == "result":
                yield _json.dumps({
                    "type": "result",
                    "content": val.content,
                    "stats": {
                        "claims": val.stats.claims,
                        "contexts": val.stats.contexts,
                        "entities": val.stats.entities,
                        "tags": val.stats.tags,
                    },
                    "is_stale": val.is_stale,
                    "last_updated": val.last_updated,
                }) + "\n"
            elif kind == "error":
                yield _json.dumps({"type": "error", "message": val}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@pkb_bp.route("/pkb/overview/topics", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_get_overview_topics_route():
    """Return structured topics extracted from the overview Key Areas section."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        db, config = get_pkb_db()
        keys = keyParser.get_api_keys()
        manager = PKBOverviewManager(db, keys, config)
        topics = manager.get_topics(email)
        return jsonify({"topics": topics})
    except Exception as e:
        logger.error(f"Error getting PKB overview topics: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


# ──────────────────────────────────────────────────────────────────────────────
# Short-Term Memory (STM) Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@pkb_bp.route("/pkb/stm", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_stm_list():
    """List active (non-expired) short-term memories for the current user."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.get_active_short_term_memories(limit=api.config.stm_max_per_user)
        if result.success:
            return jsonify({"memories": result.data})
        return json_error("Failed to get STM", status=500, code="stm_list_failed")
    except Exception as e:
        logger.error(f"Error in pkb_stm_list: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/stm/<memory_id>/promote", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_stm_promote(memory_id):
    """Manually promote a short-term memory to a long-term claim."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.promote_short_term_memory(memory_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Promotion failed",
            status=404 if "not found" in str(result.errors).lower() else 400,
            code="stm_promote_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_stm_promote: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/stm/<memory_id>", methods=["DELETE"])
@limiter.limit("20 per minute")
@login_required
def pkb_stm_delete(memory_id):
    """Dismiss (delete) a short-term memory."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.delete_short_term_memory(memory_id)
        if result.success:
            return jsonify({"deleted": memory_id})
        return json_error("Delete failed", status=400, code="stm_delete_failed")
    except Exception as e:
        logger.error(f"Error in pkb_stm_delete: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/stm/recent_promotions", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_stm_recent_promotions():
    """List recently promoted STM items."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        limit = request.args.get("limit", 10, type=int)
        result = api.get_recent_promotions(limit=limit)
        if result.success:
            return jsonify({"promotions": result.data})
        return json_error("Failed to get recent promotions", status=500, code="stm_promotions_failed")
    except Exception as e:
        logger.error(f"Error in pkb_stm_recent_promotions: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/stm/<memory_id>/demote", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_stm_demote(memory_id):
    """Demote a promoted STM item — deletes the claim and clears the promotion link."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.demote_promoted_claim(memory_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Demotion failed",
            status=404 if "not found" in str(result.errors).lower() else 400,
            code="stm_demote_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_stm_demote: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/archived", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_recently_archived():
    """List recently archived claims for undo/restore."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        limit = request.args.get("limit", 20, type=int)
        result = api.get_recently_archived(limit=limit)
        if result.success:
            return jsonify({"archived": result.data})
        return json_error("Failed", status=500, code="archived_list_failed")
    except Exception as e:
        logger.error(f"Error in pkb_recently_archived: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/<claim_id>/restore", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def pkb_restore_claim(claim_id):
    """Restore an archived claim back to active status."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.restore_archived_claim(claim_id)
        if result.success:
            return jsonify(result.data)
        return json_error(
            "; ".join(result.errors) or "Restore failed",
            status=404 if "not found" in str(result.errors).lower() else 400,
            code="restore_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_restore_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/fading", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def pkb_fading_claims():
    """List dormant/fading claims that may need reinforcement or cleanup."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.get_lifecycle_notifications()
        if result.success:
            return jsonify({"fading": result.data.get("newly_dormant", [])})
        return json_error("Failed", status=500, code="fading_list_failed")
    except Exception as e:
        logger.error(f"Error in pkb_fading_claims: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/<claim_id>/reinforce", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_reinforce_claim(claim_id):
    """Reinforce a claim — resets decay timer, revives if dormant."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.reinforce_claim(claim_id)
        if result.success:
            return jsonify({"reinforced": True, "claim_id": claim_id})
        return json_error(
            "; ".join(result.errors) or "Reinforce failed",
            status=404 if "not found" in str(result.errors).lower() else 400,
            code="reinforce_failed",
        )
    except Exception as e:
        logger.error(f"Error in pkb_reinforce_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/<claim_id>/feedback", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_add_feedback(claim_id):
    """Record negative feedback on a claim."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        context = (request.json or {}).get("context", "")
        result = api.add_claim_feedback(claim_id, context=context)
        if result.success:
            return jsonify(result.data)
        return json_error("Failed", status=500, code="feedback_failed")
    except Exception as e:
        logger.error(f"Error in pkb_add_feedback: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/feedback", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def pkb_list_feedback():
    """List negative feedback entries."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        claim_id = request.args.get("claim_id")
        result = api.get_claim_feedback(claim_id=claim_id)
        if result.success:
            return jsonify({"feedback": result.data})
        return json_error("Failed", status=500, code="feedback_list_failed")
    except Exception as e:
        logger.error(f"Error in pkb_list_feedback: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/health", methods=["GET"])
@limiter.limit("20 per minute")
@login_required
def pkb_health_stats():
    """Aggregate health stats for the PKB dashboard."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.get_health_stats()
        if result.success:
            return jsonify(result.data)
        return json_error("Failed", status=500, code="health_failed")
    except Exception as e:
        logger.error(f"Error in pkb_health_stats: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/bulk_action", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def pkb_bulk_action():
    """Perform bulk actions on multiple claims (archive, tag)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        data = request.json or {}
        claim_ids = data.get("claim_ids", [])
        action = data.get("action", "")

        if not claim_ids or not action:
            return json_error("claim_ids and action required", status=400, code="bad_request")

        results = {"succeeded": 0, "failed": 0}
        for cid in claim_ids:
            try:
                if action == "archive":
                    api.edit_claim(cid, status="archived")
                elif action == "tag":
                    tag_name = data.get("tag", "")
                    if tag_name:
                        # Create tag if needed, then link
                        tag_result = api.add_tag(tag_name)
                        if tag_result.success and tag_result.data:
                            tag_id = tag_result.data.get("tag_id") or tag_result.data.get("id")
                            if tag_id:
                                api.link_tag_to_claim(cid, tag_id)
                results["succeeded"] += 1
            except Exception:
                results["failed"] += 1

        return jsonify(results)
    except Exception as e:
        logger.error(f"Error in pkb_bulk_action: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/claims/clusters", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def pkb_auto_clusters():
    """Suggest semantic clusters (related claims grouped at a lower similarity threshold)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        threshold = request.args.get("threshold", 0.75, type=float)
        limit = request.args.get("limit", 20, type=int)
        result = api.find_consolidation_candidates(threshold=threshold, limit=limit, use_llm=False)
        if result.success:
            return jsonify({"clusters": result.data or []})
        return json_error("; ".join(result.errors) or "Clustering failed", status=500, code="cluster_failed")
    except Exception as e:
        logger.error(f"Error in pkb_auto_clusters: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


# ─── Tiered Persistence REST Endpoints (B4) ───────────────────────────────────

@pkb_bp.route("/pkb/memory/policy", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_memory_policy_get():
    """Get current user's autonomy policy (dial level + effective policy)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        settings = api.get_user_settings(email)
        return jsonify({
            "autonomy": settings.get("autonomy", api.config.default_autonomy),
            "overrides": settings.get("overrides", {}),
            "policy": api.policy,
        })
    except Exception as e:
        logger.error(f"Error in pkb_memory_policy_get: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/policy", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def pkb_memory_policy_put():
    """Update user's autonomy level and/or per-facet overrides."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json(force=True)
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")

        settings = {}
        if "autonomy" in data:
            val = int(data["autonomy"])
            if not (0 <= val <= 100):
                return json_error("autonomy must be 0-100", status=400, code="invalid_param")
            settings["autonomy"] = val
        if "overrides" in data:
            settings["overrides"] = data["overrides"]

        result = api.set_user_settings(email, settings)
        if not result.success:
            return json_error("; ".join(result.errors), status=500, code="settings_failed")

        # Re-resolve policy after update
        api_fresh = get_pkb_api_for_user(email)
        return jsonify({
            "autonomy": settings.get("autonomy", api.config.default_autonomy),
            "overrides": settings.get("overrides", {}),
            "policy": api_fresh.policy if api_fresh else None,
        })
    except Exception as e:
        logger.error(f"Error in pkb_memory_policy_put: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/undo", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def pkb_memory_undo():
    """Undo auto-saved claims (retract within 24h tombstone window).

    Body: { "activity_ids": ["id1", ...] }
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        data = request.get_json(force=True)
        activity_ids = data.get("activity_ids", [])
        if not activity_ids:
            return json_error("activity_ids required", status=400, code="invalid_param")

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")

        results = []
        for aid in activity_ids:
            r = api.undo_activity(aid)
            results.append({"activity_id": aid, "success": r.success, "errors": r.errors})

        return jsonify({"results": results})
    except Exception as e:
        logger.error(f"Error in pkb_memory_undo: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/recent_auto", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def pkb_memory_recent_auto():
    """List recently auto-saved claims (activity log entries with action_type='auto_save').

    Query params: days (default 7), limit (default 50).
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        days = int(request.args.get("days", 7))
        limit = int(request.args.get("limit", 50))

        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")

        result = api.get_recent_activity(limit=limit, action_type="auto_save")
        return jsonify({"recent_auto": result or []})
    except Exception as e:
        logger.error(f"Error in pkb_memory_recent_auto: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/auto_save_rate", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def pkb_memory_auto_save_rate():
    """Get wrong-auto-save rate (eval gate metric).

    Query params: days (default 30).
    Returns: total_auto_saves, undone_count, wrong_auto_save_rate, days.
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        days = int(request.args.get("days", 30))
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        return jsonify(api.get_auto_save_rate(days=days))
    except Exception as e:
        logger.error(f"Error in pkb_memory_auto_save_rate: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


# ─── PKB Notification Endpoints (v14) ─────────────────────────────────────────

@pkb_bp.route("/pkb/memory/notifications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def pkb_notifications_list():
    """List notifications with optional filters."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        # Trigger reminder check on list request
        api.check_reminders_due()
        return jsonify(api.get_notifications(
            priority=request.args.get("priority"),
            category=request.args.get("category"),
            unresolved_only=request.args.get("unresolved", "true").lower() == "true",
            unseen_only=request.args.get("unseen", "false").lower() == "true",
            limit=int(request.args.get("limit", 50)),
            offset=int(request.args.get("offset", 0)),
        ))
    except Exception as e:
        logger.error(f"Error in pkb_notifications_list: {e}")
        return json_error(str(e), status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/notifications/count", methods=["GET"])
@limiter.limit("120 per minute")
@login_required
def pkb_notifications_count():
    """Get badge count (unseen high/medium action-required)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        return jsonify({"count": api.get_notification_count()})
    except Exception as e:
        logger.error(f"Error in pkb_notifications_count: {e}")
        return json_error(str(e), status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/notifications/<notification_id>/action", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def pkb_notifications_action(notification_id):
    """Take action on a notification (approve/reject/undo/dismiss/pick_new/pick_existing/keep_both)."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        data = request.get_json(force=True) or {}
        action = data.get("action")
        if not action:
            return json_error("Missing 'action' field", status=400, code="bad_request")
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        result = api.resolve_notification(notification_id, action)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in pkb_notifications_action: {e}")
        return json_error(str(e), status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/notifications/bulk_action", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def pkb_notifications_bulk_action():
    """Bulk resolve notifications with same action."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("ids", [])
        action = data.get("action")
        if not ids or not action:
            return json_error("Missing 'ids' or 'action'", status=400, code="bad_request")
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        result = api.bulk_resolve(ids, action)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in pkb_notifications_bulk_action: {e}")
        return json_error(str(e), status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/notifications/mark_seen", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def pkb_notifications_mark_seen():
    """Mark notifications as seen."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("ids", [])
        if not ids:
            return json_error("Missing 'ids'", status=400, code="bad_request")
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        count = api.mark_seen(ids)
        return jsonify({"marked": count})
    except Exception as e:
        logger.error(f"Error in pkb_notifications_mark_seen: {e}")
        return json_error(str(e), status=500, code="internal_error")


@pkb_bp.route("/pkb/memory/notifications/settings", methods=["GET", "PUT"])
@limiter.limit("30 per minute")
@login_required
def pkb_notifications_settings():
    """Get or update notification preferences."""
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")
    try:
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("PKB not available", status=503, code="pkb_unavailable")
        conn = api.db.connect()
        if request.method == "GET":
            row = conn.execute(
                "SELECT facet_overrides FROM pkb_user_settings WHERE email = ?",
                (email,)
            ).fetchone()
            import json as _json
            overrides = _json.loads(row[0]) if row and row[0] else {}
            return jsonify(overrides.get("notification_preferences", {
                "badge_min_priority": "medium",
                "reminder_threshold_hours": 24,
                "emit_low_priority": True,
                "categories_muted": [],
            }))
        else:
            import json as _json
            from truth_management_system.utils import now_iso
            data = request.get_json(force=True) or {}
            row = conn.execute(
                "SELECT facet_overrides FROM pkb_user_settings WHERE email = ?",
                (email,)
            ).fetchone()
            overrides = _json.loads(row[0]) if row and row[0] else {}
            overrides["notification_preferences"] = data
            if row:
                conn.execute(
                    "UPDATE pkb_user_settings SET facet_overrides = ?, updated_at = ? WHERE email = ?",
                    (_json.dumps(overrides), now_iso(), email)
                )
            else:
                conn.execute(
                    "INSERT INTO pkb_user_settings (email, memory_autonomy, facet_overrides, updated_at) "
                    "VALUES (?, 50, ?, ?)",
                    (email, _json.dumps(overrides), now_iso())
                )
            conn.commit()
            return jsonify({"status": "updated"})
    except Exception as e:
        logger.error(f"Error in pkb_notifications_settings: {e}")
        return json_error(str(e), status=500, code="internal_error")
