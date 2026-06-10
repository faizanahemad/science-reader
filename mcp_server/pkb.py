"""
PKB (Personal Knowledge Base) MCP server.

Exposes PKB search, retrieval, and write tools over streamable-HTTP.
Port 8101. Wraps truth_management_system.interface.structured_api.StructuredAPI.

Environment variables:
    PKB_MCP_ENABLED: Set to "false" to skip startup (default "true").
    PKB_MCP_PORT: Port (default 8101).
    MCP_JWT_SECRET: Required. HS256 secret for bearer-token verification.
    MCP_RATE_LIMIT: Max tool calls per token per minute (default 10).
    MCP_TOOL_TIER: "baseline" (default, 8 tools) or "full" (15 tools).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from dataclasses import asdict
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared StructuredAPI singleton (lazy init)
# ---------------------------------------------------------------------------

_pkb_api: Any = None

STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")


def _get_pkb_api():
    """Load or return the shared StructuredAPI singleton.

    Uses ``get_pkb_db()`` from ``endpoints.pkb`` for the database and
    config, and ``keyParser({})`` from ``endpoints.utils`` for API keys.
    The instance is **not** user-scoped — call ``.for_user(email)`` on
    each tool invocation.

    Returns
    -------
    StructuredAPI
        The shared (unscoped) StructuredAPI instance.
    """
    global _pkb_api
    if _pkb_api is None:
        from endpoints.pkb import get_pkb_db
        from endpoints.utils import keyParser
        from truth_management_system.interface.structured_api import StructuredAPI

        keys = keyParser({})
        db, config = get_pkb_db()
        if db is None:
            raise RuntimeError(
                "PKB database unavailable — cannot initialise StructuredAPI"
            )
        _pkb_api = StructuredAPI(db=db, keys=keys, config=config)
    return _pkb_api


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_action_result(result: Any) -> str:
    """Serialize an ActionResult to a JSON string.

    ActionResult is a dataclass with a ``data`` field that may contain
    Claim objects, SearchResult objects, lists, dicts, or None.
    We use ``asdict`` for the ActionResult itself, then handle nested
    model objects that have ``to_dict()`` methods.

    Parameters
    ----------
    result:
        An ActionResult dataclass instance.

    Returns
    -------
    str
        JSON string representation.
    """
    try:
        d = asdict(result)
    except Exception:
        # Fallback: ActionResult may contain non-dataclass objects in
        # ``data``.  Build the dict manually.
        d = {
            "success": result.success,
            "action": result.action,
            "object_type": result.object_type,
            "object_id": result.object_id,
            "data": _serialize_data(result.data),
            "warnings": list(result.warnings) if result.warnings else [],
            "errors": list(result.errors) if result.errors else [],
        }
    else:
        # asdict may have converted nested objects; data might still
        # need special handling if it contains non-serializable types.
        d["data"] = _serialize_data(result.data)

    return json.dumps(d, default=str)


def _serialize_data(data: Any) -> Any:
    """Recursively convert model objects to JSON-safe dicts.

    Handles Claim, SearchResult (which contains a Claim), plain dicts,
    and lists thereof.
    """
    if data is None:
        return None

    # Single object with to_dict()
    if hasattr(data, "to_dict"):
        return data.to_dict()

    # SearchResult dataclass (has .claim attribute)
    if hasattr(data, "claim") and hasattr(data, "score"):
        sr: dict[str, Any] = {
            "score": data.score,
            "source": getattr(data, "source", None),
            "is_contested": getattr(data, "is_contested", False),
            "warnings": list(getattr(data, "warnings", [])),
        }
        if hasattr(data.claim, "to_dict"):
            sr["claim"] = data.claim.to_dict()
        else:
            sr["claim"] = data.claim
        return sr

    # List
    if isinstance(data, list):
        return [_serialize_data(item) for item in data]

    # Dict
    if isinstance(data, dict):
        return {k: _serialize_data(v) for k, v in data.items()}

    # Primitive
    return data


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_pkb_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[Any, Any]:
    """Create the PKB MCP server as an ASGI application.

    Returns a tuple of ``(asgi_app, fastmcp_instance)`` so the caller
    can manage the FastMCP session lifecycle if needed.

    Parameters
    ----------
    jwt_secret:
        HS256 secret for JWT verification.
    rate_limit:
        Maximum tool calls per token per minute.

    Returns
    -------
    tuple[ASGIApp, FastMCP]
        The wrapped Starlette ASGI app and the underlying FastMCP instance.
    """
    from mcp.server.fastmcp import FastMCP
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    from mcp_server.mcp_app import (
        JWTAuthMiddleware,
        RateLimitMiddleware,
        _health_check,
    )

    tier = os.getenv("MCP_TOOL_TIER", "baseline")
    is_full = tier == "full"

    mcp = FastMCP(
        "PKB Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: pkb_search — search the personal knowledge base
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_search(
        user_email: str,
        query: str,
        k: int = 20,
        strategy: str = "hybrid",
    ) -> str:
        """Search the user's Personal Knowledge Base (PKB) for relevant claims.

        Uses hybrid search (FTS5 + embedding similarity) by default.
        Returns a ranked list of matching claims with relevance scores.

        HIGH RECALL IS CRITICAL — the PKB uses semantic similarity so callers MUST search with
        multiple phrasings, synonyms, and alternative terms to avoid missing relevant memories.
        For example, if looking for dietary preferences, also search for 'food', 'eating', 'diet',
        'nutrition', 'meal'. Issue MULTIPLE searches with varied queries rather than relying on a
        single query. Use broad terms first, then narrow down. Cross-domain terms help:
        e.g. for 'exercise' also try 'fitness', 'gym', 'workout', 'health'.
        Request a higher k (30-50) when comprehensive coverage matters.

        Args:
            user_email: Email of the PKB owner.
            query: Natural-language search query. Use broad terms, synonyms, and alternative
                phrasings to maximize recall. Issue multiple searches with different queries
                rather than relying on one.
            k: Maximum number of results to return. Use 30-50 when comprehensive recall
                matters. Default 20 may miss relevant items.
            strategy: Search strategy — 'hybrid' (default), 'fts', or 'embedding'.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.search(query=query, strategy=strategy, k=k)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_search error: %s", exc)
            return json.dumps({"error": f"pkb_search failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 2: pkb_get_claim — retrieve a single claim by ID
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_get_claim(user_email: str, claim_id: str) -> str:
        """Retrieve a single claim from the PKB by its claim ID.

        Use this when you already have a specific claim_id (e.g. from
        search results or a reference) and need the full claim details.

        Args:
            user_email: Email of the PKB owner.
            claim_id: The UUID of the claim to retrieve.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.get_claim(claim_id=claim_id)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_get_claim error: %s", exc)
            return json.dumps({"error": f"pkb_get_claim failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 3: pkb_resolve_reference — resolve an @-reference
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_resolve_reference(user_email: str, reference_id: str) -> str:
        """Resolve a PKB @-reference (friendly ID) to its full object(s).

        Friendly IDs look like ``@my_preference_42`` or
        ``@work_context``.  Suffixed IDs (``_context``, ``_entity``,
        ``_tag``, ``_domain``) route to the correct object type.

        Args:
            user_email: Email of the PKB owner.
            reference_id: The friendly ID to resolve (with or without leading @).
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            # Strip leading @ if present
            ref = reference_id.lstrip("@")
            result = user_api.resolve_reference(reference_id=ref)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_resolve_reference error: %s", exc)
            return json.dumps({"error": f"pkb_resolve_reference failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 4: pkb_get_pinned_claims — get globally pinned claims
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_get_pinned_claims(user_email: str, limit: int = 50) -> str:
        """Retrieve the user's pinned (high-priority) PKB claims.

        Pinned claims are those the user has marked as especially
        important or frequently referenced.  Returns up to ``limit``
        pinned claims.

        Args:
            user_email: Email of the PKB owner.
            limit: Maximum number of pinned claims to return (default 50).
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.get_pinned_claims(limit=limit)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_get_pinned_claims error: %s", exc)
            return json.dumps({"error": f"pkb_get_pinned_claims failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 5: pkb_add_claim — add a new claim to the PKB
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_add_claim(
        user_email: str,
        statement: str,
        claim_type: str,
        context_domain: str,
        tags: Optional[List[str]] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> str:
        """Add a new claim (memory, fact, preference, etc.) to the PKB.

        Claims are the atomic units of the knowledge base.  Each claim
        has a type (e.g. "fact", "preference", "decision") and belongs
        to a context domain (e.g. "work", "health", "finance").

        Args:
            user_email: Email of the PKB owner.
            statement: The claim text — a single clear assertion.
            claim_type: Claim type (e.g. "fact", "preference", "decision", "memory", "goal").
            context_domain: Domain/topic area (e.g. "work", "health", "finance", "personal").
            tags: Optional list of tag names to attach to the claim.
            valid_from: Start of validity period (ISO 8601 date). Optional.
            valid_to: End of validity period (ISO 8601 date). Required for task and reminder claims.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            kwargs = dict(
                statement=statement,
                claim_type=claim_type,
                context_domain=context_domain,
                tags=tags,
            )
            if valid_from is not None:
                kwargs["valid_from"] = valid_from
            if valid_to is not None:
                kwargs["valid_to"] = valid_to
            result = user_api.add_claim(**kwargs)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_add_claim error: %s", exc)
            return json.dumps({"error": f"pkb_add_claim failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 6: pkb_edit_claim — edit an existing claim
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_edit_claim(
        user_email: str,
        claim_id: str,
        statement: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Edit an existing claim in the PKB.

        Only the fields you provide will be updated; others remain
        unchanged.  Use ``pkb_get_claim`` first to see the current
        state.

        Args:
            user_email: Email of the PKB owner.
            claim_id: UUID of the claim to edit.
            statement: New statement text (optional).
            tags: New list of tag names (replaces existing tags; optional).
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            patch: dict[str, Any] = {}
            if statement is not None:
                patch["statement"] = statement
            if tags is not None:
                patch["tags"] = tags
            result = user_api.edit_claim(claim_id=claim_id, **patch)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_edit_claim error: %s", exc)
            return json.dumps({"error": f"pkb_edit_claim failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 7: pkb_delete_claim — soft-delete a claim
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_delete_claim(user_email: str, claim_id: str) -> str:
        """Soft-delete (retract) a claim from the PKB. The claim is not permanently deleted but marked as retracted and excluded from default search results.

        Args:
            user_email: Email of the PKB owner.
            claim_id: UUID of the claim to delete.
        """
        try:
            result = _get_pkb_api().for_user(user_email).delete_claim(claim_id=claim_id)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_delete_claim error: %s", exc)
            return json.dumps({"error": f"pkb_delete_claim failed: {exc}"})

    # -----------------------------------------------------------------
    # Tool 8: pkb_nl_command — natural language PKB operations
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_nl_command(user_email: str, command: str, model: str = None) -> str:
        """Process a natural language command against the PKB.

        Accepts free-form text and performs multi-step CRUD operations
        (search, add, edit, delete, pin claims; manage entities and tags)
        using an internal agentic LLM loop. Returns a natural language
        summary of actions taken.

        When the command involves searching or retrieving memories, the internal agent
        optimizes for HIGH RECALL by using synonyms, alternative phrasings, and broad
        search terms to ensure no relevant memories are missed.

        Examples:
            - "Add a reminder to buy a gift for my friend on July 20th"
            - "What are my pending tasks?"
            - "Delete all claims about my old address"
            - "Update my preference about coffee to prefer espresso"
            - "Find everything about my health — diet, exercise, medical, fitness, nutrition"

        Args:
            user_email: Email of the PKB owner.
            command: Natural language command. For search/retrieval, include synonyms and
                alternative phrasings to improve recall (e.g. 'find my dietary preferences,
                food habits, eating restrictions, nutrition notes').
            model: Optional LLM model override (default: openai/gpt-4o-mini).
        """
        try:
            from truth_management_system.interface.nl_agent import PKBNLAgent
            from endpoints.utils import keyParser

            api = _get_pkb_api().for_user(user_email)
            keys = keyParser({})
            agent = PKBNLAgent(api=api, keys=keys, model=model)
            result = agent.process(command)
            return json.dumps(result.to_dict(), default=str)
        except Exception as exc:
            logger.exception("pkb_nl_command error: %s", exc)
            return json.dumps({"error": f"pkb_nl_command failed: {exc}"})

    # =================================================================
    # Full-tier tools (only registered when MCP_TOOL_TIER == "full")
    # =================================================================

    # -----------------------------------------------------------------
    # STM tools (baseline) — available to all external editors
    # -----------------------------------------------------------------

    @mcp.tool()
    def pkb_get_stm(user_email: str, limit: int = 50) -> str:
        """Get the user's active short-term memories (STM).

        STM items are transient context captured during conversations.
        They persist for a limited time and get promoted to long-term
        claims if reinforced across conversations.

        Args:
            user_email: Email of the PKB owner.
            limit: Maximum memories to return (default 50).
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.get_active_short_term_memories(limit=limit)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_get_stm error: %s", exc)
            return json.dumps({"error": f"pkb_get_stm failed: {exc}"})

    @mcp.tool()
    def pkb_promote_stm(user_email: str, memory_id: str) -> str:
        """Promote a short-term memory to a permanent long-term claim.

        Use when a piece of context has proven valuable and should be
        retained permanently in the knowledge base.

        Args:
            user_email: Email of the PKB owner.
            memory_id: UUID of the short-term memory to promote.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.promote_short_term_memory(memory_id)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_promote_stm error: %s", exc)
            return json.dumps({"error": f"pkb_promote_stm failed: {exc}"})

    @mcp.tool()
    def pkb_dismiss_stm(user_email: str, memory_id: str) -> str:
        """Dismiss (delete) a short-term memory.

        Use when a captured context item is no longer relevant or was
        captured in error.

        Args:
            user_email: Email of the PKB owner.
            memory_id: UUID of the short-term memory to dismiss.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.delete_short_term_memory(memory_id)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_dismiss_stm error: %s", exc)
            return json.dumps({"error": f"pkb_dismiss_stm failed: {exc}"})

    @mcp.tool()
    def pkb_propose_extraction(
        user_email: str,
        text: str,
        extraction_mode: str = "relaxed",
    ) -> str:
        """Extract knowledge claims from arbitrary text.

        Runs the extraction pipeline on the provided text and returns
        proposed claims for review. Does NOT auto-commit — the caller
        should present proposals to the user or call pkb_add_claim for
        each accepted proposal.

        Use this to ingest information from documents, code comments,
        README sections, meeting notes, or any text block.

        Args:
            user_email: Email of the PKB owner.
            text: The text to extract claims from.
            extraction_mode: 'relaxed' (default) or 'aggressive'.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            from truth_management_system.interface.conversation_distillation import ConversationDistiller
            distiller = ConversationDistiller(
                user_api, user_api.keys, user_api.config,
                extraction_mode=extraction_mode,
            )
            plan = distiller.extract_and_propose(
                conversation_summary="",
                user_message=text,
                assistant_message="",
            )
            if plan is None:
                return json.dumps({"proposals": [], "count": 0})
            proposals = []
            for c in (plan.new_claims or []):
                proposals.append({
                    "statement": c.statement,
                    "claim_type": c.claim_type,
                    "context_domain": c.context_domain,
                    "confidence": c.confidence,
                    "reason": getattr(c, "reason", None),
                })
            return json.dumps({"proposals": proposals, "count": len(proposals)}, default=str)
        except Exception as exc:
            logger.exception("pkb_propose_extraction error: %s", exc)
            return json.dumps({"error": f"pkb_propose_extraction failed: {exc}"})

    # Tool: pkb_summarize — get a summary/overview of the knowledge base
    @mcp.tool()
    def pkb_summarize(user_email: str) -> str:
        """Get a summary overview of the user's knowledge base.

        Returns key areas, topics, and basic statistics about what's stored.

        Args:
            user_email: Email of the PKB owner.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            # Try overview manager first
            summary = ""
            try:
                from truth_management_system.interface.overview_manager import PKBOverviewManager
                om = PKBOverviewManager(user_api.db, user_api.keys, user_api.config)
                snippet = om.get_key_areas_snippet(user_email)
                if snippet:
                    summary = snippet
            except Exception:
                pass
            if not summary:
                tags = user_api.tags.list(limit=50)
                tag_names = [t.name for t in tags] if tags else []
                summary = f"Tags ({len(tag_names)}): {', '.join(tag_names[:20])}"
            return json.dumps({"summary": summary})
        except Exception as exc:
            logger.exception("pkb_summarize error: %s", exc)
            return json.dumps({"error": f"pkb_summarize failed: {exc}"})

    # Tool: pkb_negative_feedback — record that a retrieved claim was not helpful
    @mcp.tool()
    def pkb_negative_feedback(user_email: str, claim_id: str, context: str = "") -> str:
        """Record negative feedback on a claim that was not relevant or helpful.

        This penalizes the claim in future retrievals for similar contexts.

        Args:
            user_email: Email of the PKB owner.
            claim_id: UUID of the claim to mark as unhelpful.
            context: Optional description of why it wasn't helpful.
        """
        try:
            api = _get_pkb_api()
            user_api = api.for_user(user_email)
            result = user_api.add_claim_feedback(claim_id, context=context)
            return _serialize_action_result(result)
        except Exception as exc:
            logger.exception("pkb_negative_feedback error: %s", exc)
            return json.dumps({"error": f"pkb_negative_feedback failed: {exc}"})

    if is_full:
        # -------------------------------------------------------------
        # Tool: pkb_recent_promotions — list recently promoted STM items
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_recent_promotions(user_email: str, limit: int = 10) -> str:
            """List STM items that were recently promoted to long-term claims.

            Shows what context items crossed the reinforcement threshold
            and became permanent memories. Useful for reviewing what the
            system has learned.

            Args:
                user_email: Email of the PKB owner.
                limit: Maximum results (default 10).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.get_recent_promotions(limit=limit)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_recent_promotions error: %s", exc)
                return json.dumps({"error": f"pkb_recent_promotions failed: {exc}"})

        # -------------------------------------------------------------
        # Tool: pkb_demote_claim — reverse a STM promotion
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_demote_claim(user_email: str, memory_id: str) -> str:
            """Reverse a STM→claim promotion. Deletes the created claim
            and resets the STM item to unpromoted state.

            Args:
                user_email: Email of the PKB owner.
                memory_id: UUID of the STM memory whose promotion to reverse.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.demote_promoted_claim(memory_id)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_demote_claim error: %s", exc)
                return json.dumps({"error": f"pkb_demote_claim failed: {exc}"})

        # Tool: pkb_fading_claims — list dormant claims needing attention
        @mcp.tool()
        def pkb_fading_claims(user_email: str) -> str:
            """List claims that have gone dormant (fading memories).

            These are claims that haven't been used recently and may need
            reinforcement or cleanup.

            Args:
                user_email: Email of the PKB owner.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.get_lifecycle_notifications()
                if result.success:
                    return json.dumps({"fading": result.data.get("newly_dormant", [])})
                return json.dumps({"error": "; ".join(result.errors)})
            except Exception as exc:
                logger.exception("pkb_fading_claims error: %s", exc)
                return json.dumps({"error": f"pkb_fading_claims failed: {exc}"})

        # Tool: pkb_reinforce_claim — reinforce/revive a claim
        @mcp.tool()
        def pkb_reinforce_claim(user_email: str, claim_id: str) -> str:
            """Reinforce a claim — resets its decay timer and revives it if dormant.

            Use this to keep important memories alive when they're fading.

            Args:
                user_email: Email of the PKB owner.
                claim_id: UUID of the claim to reinforce.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.reinforce_claim(claim_id)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_reinforce_claim error: %s", exc)
                return json.dumps({"error": f"pkb_reinforce_claim failed: {exc}"})

        # Tool: pkb_health_stats — aggregate health dashboard
        @mcp.tool()
        def pkb_health_stats(user_email: str) -> str:
            """Get aggregate health statistics for the knowledge base.

            Returns counts by status, claim type, and domain.

            Args:
                user_email: Email of the PKB owner.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.get_health_stats()
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_health_stats error: %s", exc)
                return json.dumps({"error": f"pkb_health_stats failed: {exc}"})

        # Tool: pkb_auto_clusters — find semantic clusters at lower threshold
        @mcp.tool()
        def pkb_auto_clusters(user_email: str, threshold: float = 0.75) -> str:
            """Find groups of semantically related claims (auto-clustering).

            Uses a lower similarity threshold than dedup to surface claims
            that could be organized into contexts or merged.

            Args:
                user_email: Email of the PKB owner.
                threshold: Similarity threshold (default 0.75, range 0.5-0.95).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.find_consolidation_candidates(threshold=threshold, use_llm=False)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_auto_clusters error: %s", exc)
                return json.dumps({"error": f"pkb_auto_clusters failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 8: pkb_get_claims_by_ids — batch retrieve claims
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_get_claims_by_ids(user_email: str, claim_ids: List[str]) -> str:
            """Retrieve multiple claims by their IDs in a single call.

            More efficient than calling ``pkb_get_claim`` in a loop
            when you need several claims at once.

            Args:
                user_email: Email of the PKB owner.
                claim_ids: List of claim UUIDs to retrieve.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.get_claims_by_ids(claim_ids=claim_ids)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_get_claims_by_ids error: %s", exc)
                return json.dumps({"error": f"pkb_get_claims_by_ids failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 9: pkb_autocomplete — prefix search for friendly IDs
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_autocomplete(user_email: str, prefix: str, limit: int = 10) -> str:
            """Autocomplete PKB friendly IDs by prefix.

            Searches across claims, contexts, entities, tags, and
            domains.  Useful for building @-reference suggestions in
            a UI or helping an LLM discover available knowledge.

            Args:
                user_email: Email of the PKB owner.
                prefix: The prefix string to match against friendly IDs.
                limit: Maximum matches per category (default 10).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.autocomplete(prefix=prefix, limit=limit)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_autocomplete error: %s", exc)
                return json.dumps({"error": f"pkb_autocomplete failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 10: pkb_resolve_context — get context + its claims
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_resolve_context(user_email: str, context_id: str) -> str:
            """Resolve a context to its full claim tree.

            Returns all claims belonging to the given context
            (including sub-contexts, resolved recursively).

            Args:
                user_email: Email of the PKB owner.
                context_id: UUID or friendly_id of the context.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.resolve_context(context_id=context_id)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_resolve_context error: %s", exc)
                return json.dumps({"error": f"pkb_resolve_context failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 11: pkb_pin_claim — pin or unpin a claim
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_pin_claim(user_email: str, claim_id: str, pin: bool = True) -> str:
            """Pin or unpin a claim for prominence.

            Pinned claims appear in ``pkb_get_pinned_claims`` results
            and are given higher priority in context injection.

            Args:
                user_email: Email of the PKB owner.
                claim_id: UUID of the claim to pin/unpin.
                pin: True to pin, False to unpin (default True).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                result = user_api.pin_claim(claim_id=claim_id, pin=pin)
                return _serialize_action_result(result)
            except Exception as exc:
                logger.exception("pkb_pin_claim error: %s", exc)
                return json.dumps({"error": f"pkb_pin_claim failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 12: pkb_list_contexts — list all PKB contexts
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_contexts(user_email: str) -> str:
            """List all PKB contexts for a user.

            Returns a JSON array of context objects, each containing:
            ``context_id``, ``friendly_id``, ``name``, ``description``,
            ``parent_context_id``, ``claim_count``, ``created_at``,
            ``updated_at``.

            Args:
                user_email: Email of the PKB owner.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                contexts_with_counts = user_api.contexts.get_with_claim_count(limit=200)
                from endpoints.pkb import serialize_context

                results = []
                for ctx, count in contexts_with_counts:
                    ctx_dict = serialize_context(ctx)
                    ctx_dict["claim_count"] = count
                    results.append(ctx_dict)
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_contexts error: %s", exc)
                return json.dumps({"error": f"pkb_list_contexts failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 13: pkb_list_entities — list all PKB entities
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_entities(user_email: str) -> str:
            """List all PKB entities for a user.

            Returns a JSON array of entity objects, each containing:
            ``entity_id``, ``entity_type``, ``name``, ``meta_json``,
            ``created_at``, ``updated_at``.

            Args:
                user_email: Email of the PKB owner.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                entities = user_api.entities.list(limit=200, order_by="name")
                from endpoints.pkb import serialize_entity

                results = [serialize_entity(e) for e in entities]
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_entities error: %s", exc)
                return json.dumps({"error": f"pkb_list_entities failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 14: pkb_list_tags — list all PKB tags
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_tags(user_email: str) -> str:
            """List all PKB tags for a user.

            Returns a JSON array of tag objects, each containing:
            ``tag_id``, ``name``, ``parent_tag_id``, ``meta_json``,
            ``created_at``, ``updated_at``.

            Args:
                user_email: Email of the PKB owner.
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                tags = user_api.tags.list(limit=200, order_by="name")
                from endpoints.pkb import serialize_tag

                results = [serialize_tag(t) for t in tags]
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_tags error: %s", exc)
                return json.dumps({"error": f"pkb_list_tags failed: {exc}"})
    # -----------------------------------------------------------------
    # Build the Starlette ASGI app with middleware layers
    # -----------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    mcp_starlette = mcp.streamable_http_app()

    outer_app = Starlette(
        routes=[
            Route("/health", _health_check, methods=["GET"]),
            Mount("/", app=mcp_starlette),
        ],
        lifespan=lifespan,
    )

    app_with_rate_limit = RateLimitMiddleware(outer_app, rate=rate_limit, window=60)

    app_with_auth = JWTAuthMiddleware(app_with_rate_limit, jwt_secret=jwt_secret)

    return app_with_auth, mcp


# ---------------------------------------------------------------------------
# Server startup (daemon thread)
# ---------------------------------------------------------------------------


def start_pkb_mcp_server() -> None:
    """Start the PKB MCP server in a daemon thread.

    Reads configuration from environment variables (see module docstring).
    Does nothing if ``PKB_MCP_ENABLED=false`` or ``MCP_JWT_SECRET`` is
    not set.  The thread is a daemon so it exits automatically when the
    main process (Flask) terminates.
    """
    if os.getenv("PKB_MCP_ENABLED", "true").lower() == "false":
        logger.info("PKB MCP server disabled (PKB_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — PKB MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the PKB MCP server."
        )
        return

    port = int(os.getenv("PKB_MCP_PORT", "8101"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_pkb_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
            logger.info("PKB MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("PKB MCP server failed to start")

    thread = threading.Thread(target=_run, name="pkb-mcp-server", daemon=True)
    thread.start()
    logger.info(
        "PKB MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
