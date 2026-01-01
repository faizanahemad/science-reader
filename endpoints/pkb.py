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
        "claim_type": claim.claim_type,
        "statement": claim.statement,
        "context_domain": claim.context_domain,
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
        if request.args.get("claim_type"):
            filters["claim_type"] = request.args.get("claim_type")
        if request.args.get("context_domain"):
            filters["context_domain"] = request.args.get("context_domain")
        if request.args.get("status"):
            filters["status"] = request.args.get("status")
        else:
            filters["status"] = "active"

        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))

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
        api = get_pkb_api_for_user(email)

        if api is None:
            return json_error("Failed to initialize PKB", status=500, code="pkb_init_failed")

        # Preserve legacy behavior: accept partial updates via patch dict.
        patch = {}
        for field in ["statement", "claim_type", "context_domain", "status", "confidence", "meta_json", "valid_from", "valid_to"]:
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
                    "existing_claim_id": proposal.match.claim.claim_id if proposal.match and proposal.match.claim else None,
                    "existing_statement": proposal.match.claim.statement if proposal.match and proposal.match.claim else None,
                    "similarity_score": proposal.match.score if proposal.match else None,
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


