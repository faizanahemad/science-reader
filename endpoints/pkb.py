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

from flask import Blueprint, jsonify, request, session

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
    )
    from truth_management_system.interface.text_ingestion import (  # type: ignore
        TextIngestionDistiller,
    )

    PKB_AVAILABLE = True
except ImportError:
    PKB_AVAILABLE = False
    warnings.warn("PKB (truth_management_system) not available. PKB endpoints will be disabled.")


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


def serialize_claim(claim):
    """Convert a Claim object to a JSON-serializable dict."""

    return {
        "claim_id": claim.claim_id,
        "user_email": claim.user_email,
        "claim_number": getattr(claim, 'claim_number', None),
        "friendly_id": getattr(claim, 'friendly_id', None),
        "claim_type": claim.claim_type,
        "claim_types": getattr(claim, 'claim_types', None),
        "statement": claim.statement,
        "context_domain": claim.context_domain,
        "context_domains": getattr(claim, 'context_domains', None),
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
        "possible_questions": getattr(claim, 'possible_questions', None),
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
                return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

            result = api.search(query, strategy=strategy, k=limit, filters=filters)
            if result.success:
                claims = [r.claim for r in result.data]
                return jsonify({"claims": [serialize_claim(c) for c in claims], "count": len(claims)})
            return json_error("; ".join(result.errors), status=400, code="bad_request")
        else:
            # --- List mode: simple DB query with filters ---
            api = get_pkb_api_for_user(email)
            if api is None:
                return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

            claims = api.claims.list(filters=filters, limit=limit, offset=offset, order_by="-updated_at")
            return jsonify({"claims": [serialize_claim(c) for c in claims], "count": len(claims)})
    except Exception as e:
        logger.error(f"Error in pkb_list_claims: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
        claim_types = data.get("claim_types")              # JSON string or None
        context_domains = data.get("context_domains")      # JSON string or None
        possible_questions = data.get("possible_questions") # JSON string or None

        keys = keyParser(session) if auto_extract else {}
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.add_claim(
            statement=statement,
            claim_type=claim_type,
            context_domain=context_domain,
            tags=tags,
            entities=entities,
            auto_extract=auto_extract,
            confidence=confidence,
            meta_json=meta_json,
            claim_types=claim_types,
            context_domains=context_domains,
            possible_questions=possible_questions,
        )

        if result.success:
            return jsonify({"success": True, "claim": serialize_claim(result.data), "warnings": result.warnings})

        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_add_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Too many claims. Maximum is 100 per request.", status=400, code="bad_request")

        auto_extract = data.get("auto_extract", False)
        stop_on_error = data.get("stop_on_error", False)

        keys = keyParser(session) if auto_extract else {}
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.add_claims_bulk(claims=claims, auto_extract=auto_extract, stop_on_error=stop_on_error)
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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.get_claim(claim_id)
        if result.success:
            return jsonify({"claim": serialize_claim(result.data)})

        return json_error("Claim not found", status=404, code="claim_not_found")
    except Exception as e:
        logger.error(f"Error in pkb_get_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        # Preserve legacy behavior: accept partial updates via patch dict.
        patch = {}
        for field in ["statement", "claim_type", "context_domain", "status", "confidence",
                       "meta_json", "valid_from", "valid_to", "claim_types", "context_domains",
                       "possible_questions", "friendly_id"]:
            if field in data:
                patch[field] = data[field]

        if not patch:
            return json_error("No fields to update", status=400, code="bad_request")

        result = api.edit_claim(claim_id, **patch)

        if result.success:
            return jsonify({"success": True, "claim": serialize_claim(result.data)})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_update_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.delete_claim(claim_id)
        if result.success:
            return jsonify({"success": True, "message": "Claim retracted successfully"})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_delete_claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
            return jsonify({"success": True, "pinned_claims": claims, "count": len(claims)})

        return json_error("; ".join(result.errors), status=500, code="internal_error")
    except Exception as e:
        logger.error(f"Error in pkb_get_pinned: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
        return jsonify({"success": True, "conversation_id": conv_id, "message": "All conversation-pinned claims cleared"})
    except Exception as e:
        logger.error(f"Error in pkb_conversation_clear_pinned: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: query", status=400, code="bad_request")

        strategy = data.get("strategy", "hybrid")
        k = data.get("k", 20)
        filters = data.get("filters", {})

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.search(query, strategy=strategy, k=k, filters=filters)
        if result.success:
            return jsonify({"results": [serialize_search_result(r) for r in result.data], "count": len(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_search: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        filters = {}
        if request.args.get("entity_type"):
            filters["entity_type"] = request.args.get("entity_type")

        limit = int(request.args.get("limit", 100))
        entities = api.entities.list(filters=filters, limit=limit, order_by="name")
        return jsonify({"entities": [serialize_entity(e) for e in entities], "count": len(entities)})
    except Exception as e:
        logger.error(f"Error in pkb_list_entities: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        limit = int(request.args.get("limit", 200))
        claims = api.claims.get_by_entity(entity_id)
        claims = claims[:limit]
        return jsonify({"claims": [serialize_claim(c) for c in claims], "count": len(claims)})
    except Exception as e:
        logger.error(f"Error in pkb_entity_claims: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        limit = int(request.args.get("limit", 100))
        tags = api.tags.list(limit=limit, order_by="name")
        return jsonify({"tags": [serialize_tag(t) for t in tags], "count": len(tags)})
    except Exception as e:
        logger.error(f"Error in pkb_list_tags: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        limit = int(request.args.get("limit", 200))
        include_children = request.args.get("include_children", "false").lower() == "true"
        claims = api.claims.get_by_tag(tag_id, include_children=include_children)
        claims = claims[:limit]
        return jsonify({"claims": [serialize_claim(c) for c in claims], "count": len(claims)})
    except Exception as e:
        logger.error(f"Error in pkb_tag_claims: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.get_open_conflicts()
        if result.success:
            return jsonify({"conflicts": [serialize_conflict_set(c) for c in result.data], "count": len(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error in pkb_list_conflicts: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: resolution_notes", status=400, code="bad_request")

        winning_claim_id = data.get("winning_claim_id")
        api = get_pkb_api_for_user(email)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.resolve_conflict_set(conflict_id, resolution_notes, winning_claim_id)
        if result.success:
            return jsonify({"success": True, "conflict": serialize_conflict_set(result.data)})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error in pkb_resolve_conflict: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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

        if not user_message:
            return json_error("Missing required field: user_message", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        distiller = ConversationDistiller(api, keys)
        plan = distiller.extract_and_propose(
            conversation_summary=conversation_summary,
            user_message=user_message,
            assistant_message=assistant_message or "",
        )

        if not plan or len(plan.candidates) == 0:
            return jsonify({"has_updates": False, "proposed_actions": [], "user_prompt": None})

        plan_id = str(uuid.uuid4())
        _memory_update_plans[plan_id] = plan

        proposed_actions = []
        for i, candidate in enumerate(plan.candidates):
            action = {
                "index": i,
                "statement": candidate.statement,
                "claim_type": candidate.claim_type,
                "context_domain": candidate.context_domain,
                "action": "add",
            }
            if plan.matches and i < len(plan.matches) and plan.matches[i]:
                match = plan.matches[i]
                action["existing_claim_id"] = match.claim.claim_id
                action["existing_statement"] = match.claim.statement
                action["similarity_score"] = match.score
                action["action"] = plan.proposed_actions[i] if plan.proposed_actions and i < len(plan.proposed_actions) else "edit"
            proposed_actions.append(action)

        return jsonify(
            {
                "has_updates": True,
                "plan_id": plan_id,
                "proposed_actions": proposed_actions,
                "user_prompt": plan.user_prompt,
            }
        )
    except Exception as e:
        logger.error(f"Error in pkb_propose_updates: {e}")
        traceback.print_exc()
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: text", status=400, code="bad_request")

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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        distiller = TextIngestionDistiller(api, keys)
        plan = distiller.ingest_and_propose(
            text=text,
            default_claim_type=default_claim_type,
            default_domain=default_domain,
            use_llm_parsing=use_llm,
        )

        if not plan.proposals:
            return jsonify({"has_proposals": False, "proposals": [], "summary": plan.summary, "total_parsed": plan.total_lines_parsed})

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
                    "existing_claim_id": proposal.existing_claim.claim_id if proposal.existing_claim else None,
                    "existing_statement": proposal.existing_claim.statement if proposal.existing_claim else None,
                    "similarity_score": proposal.similarity_score,
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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: plan_id", status=400, code="bad_request")

        plan = _text_ingestion_plans.get(plan_id)
        if not plan:
            return json_error("Plan not found or expired", status=404, code="not_found")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        distiller = TextIngestionDistiller(api, keys)
        result = distiller.execute_plan(plan, approved)

        results = []
        for exec_result in result.execution_results:
            results.append({"action": exec_result.action, "success": exec_result.success, "claim_id": exec_result.object_id, "errors": exec_result.errors})

        del _text_ingestion_plans[plan_id]

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: plan_id", status=400, code="bad_request")

        plan = _memory_update_plans.get(plan_id)
        if not plan:
            return json_error("Plan not found or expired", status=404, code="not_found")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
                            "context_domain": item.get("context_domain", candidate.context_domain),
                        }
                    )
        else:
            for idx in approved_indices:
                if 0 <= idx < len(plan.candidates):
                    candidate = plan.candidates[idx]
                    items_to_process.append(
                        {"index": idx, "statement": candidate.statement, "claim_type": candidate.claim_type, "context_domain": candidate.context_domain}
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
            if plan.proposed_actions and idx < len(plan.proposed_actions):
                action = plan.proposed_actions[idx]

            if action == "edit" and plan.matches and idx < len(plan.matches) and plan.matches[idx]:
                existing_claim_id = plan.matches[idx].claim.claim_id
                result = api.edit_claim(existing_claim_id, statement=statement, claim_type=claim_type, context_domain=context_domain)
                results.append({"action": "edit", "claim_id": existing_claim_id, "success": result.success, "errors": result.errors})
                if result.success:
                    edited_count += 1
            else:
                candidate = plan.candidates[idx]
                result = api.add_claim(
                    statement=statement,
                    claim_type=claim_type,
                    context_domain=context_domain,
                    tags=candidate.tags if hasattr(candidate, "tags") else [],
                    auto_extract=False,
                )
                results.append({"action": "add", "claim_id": result.object_id if result.success else None, "success": result.success, "errors": result.errors})
                if result.success:
                    added_count += 1

        del _memory_update_plans[plan_id]

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: query", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return jsonify({"claims": [serialize_claim(sr.claim) for sr in claims[:k]], "formatted_context": formatted_context})
    except Exception as e:
        logger.error(f"Error in pkb_get_relevant_context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        # Use the universal resolver that handles all formats
        claim = api.resolve_claim_identifier(friendly_id)
        if claim:
            return jsonify({"success": True, "claim": serialize_claim(claim)})
        return json_error(f"No claim found with identifier: {friendly_id}", status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error getting claim by friendly_id: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


# =============================================================================
# === Autocomplete Endpoint (v0.5) ===
# =============================================================================

@pkb_bp.route("/pkb/autocomplete", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def pkb_autocomplete():
    """Search memories and contexts by friendly_id prefix for autocomplete.
    
    Query params:
        q: prefix string to search for
        limit: max results per category (default 10)
    """
    if not PKB_AVAILABLE:
        return json_error("PKB not available", status=503, code="pkb_unavailable")

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        q = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 10)), 20)

        if not q or len(q) < 1:
            return jsonify({"memories": [], "contexts": []})

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.autocomplete(q, limit=limit)
        if result.success:
            return jsonify(result.data)
        return jsonify({"memories": [], "contexts": []})
    except Exception as e:
        logger.error(f"Error in autocomplete: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.resolve_reference(reference_id)
        if result.success:
            data = result.data
            return jsonify({
                "success": True,
                "type": data["type"],
                "claims": [serialize_claim(c) for c in data["claims"]],
                "source_id": data["source_id"],
                "source_name": data["source_name"],
            })
        return json_error(result.errors[0] if result.errors else "Not found", status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error resolving reference: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        contexts_with_counts = api.contexts.get_with_claim_count(limit=200)
        result = []
        for ctx, count in contexts_with_counts:
            ctx_dict = serialize_context(ctx)
            ctx_dict["claim_count"] = count
            result.append(ctx_dict)

        return jsonify({"success": True, "contexts": result})
    except Exception as e:
        logger.error(f"Error listing contexts: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: name", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.edit_context(context_id, **data)
        if result.success:
            return jsonify({"success": True, "context": serialize_context(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error updating context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.delete_context(context_id)
        if result.success:
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error deleting context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: claim_id", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        # Resolve any identifier format to a real claim
        claim = api.resolve_claim_identifier(claim_identifier)
        if not claim:
            return json_error(f"No claim found matching: {claim_identifier}", status=404, code="not_found")

        result = api.add_claim_to_context(context_id, claim.claim_id)
        if result.success:
            return jsonify({"success": True, "claim_id": claim.claim_id})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error adding claim to context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.remove_claim_from_context(context_id, claim_id)
        if result.success:
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error removing claim from context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.resolve_context(context_id)
        if result.success:
            return jsonify({
                "success": True,
                "claims": [serialize_claim(c) for c in result.data],
                "count": len(result.data),
            })
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error resolving context: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: name", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.add_entity(name=name, entity_type=entity_type, meta_json=data.get("meta_json"))
        if result.success:
            return jsonify({"success": True, "entity": serialize_entity(result.data)})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error creating entity: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Missing required field: entity_id", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.link_entity_to_claim(claim_id, entity_id, role)
        if result.success:
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=400, code="bad_request")
    except Exception as e:
        logger.error(f"Error linking entity to claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        role = request.args.get("role")
        result = api.unlink_entity_from_claim(claim_id, entity_id, role)
        if result.success:
            return jsonify({"success": True})
        return json_error("; ".join(result.errors), status=404, code="not_found")
    except Exception as e:
        logger.error(f"Error unlinking entity from claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        contexts = api.contexts.get_contexts_for_claim(claim_id)
        return jsonify({"contexts": [serialize_context(c) for c in contexts], "count": len(contexts)})
    except Exception as e:
        logger.error(f"Error getting contexts for claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

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

        return jsonify({"success": True, "added": len(desired_ids - current_ids), "removed": len(current_ids - desired_ids)})
    except Exception as e:
        logger.error(f"Error setting contexts for claim: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        types = api.type_catalog.list()
        return jsonify({"types": types, "count": len(types)})
    except Exception as e:
        logger.error(f"Error listing types: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
        type_name = data.get("type_name", "").strip().lower().replace(' ', '_')
        if not type_name:
            return json_error("Missing required field: type_name", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.type_catalog.add(
            type_name=type_name,
            display_name=data.get("display_name"),
            description=data.get("description"),
        )
        return jsonify({"success": True, "type": result})
    except Exception as e:
        logger.error(f"Error adding type: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        domains = api.domain_catalog.list()
        return jsonify({"domains": domains, "count": len(domains)})
    except Exception as e:
        logger.error(f"Error listing domains: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


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
        domain_name = data.get("domain_name", "").strip().lower().replace(' ', '_')
        if not domain_name:
            return json_error("Missing required field: domain_name", status=400, code="bad_request")

        keys = keyParser(session)
        api = get_pkb_api_for_user(email, keys)
        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        result = api.domain_catalog.add(
            domain_name=domain_name,
            display_name=data.get("display_name"),
            description=data.get("description"),
        )
        return jsonify({"success": True, "domain": result})
    except Exception as e:
        logger.error(f"Error adding domain: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")
