"""
Constants and Enums for PKB v0.

This module centralizes all allowed values to avoid magic strings,
enable IDE autocomplete, and ensure consistency across the codebase.

Includes:
- ClaimType: Types of claims (fact, memory, decision, etc.)
- ClaimStatus: Lifecycle states of claims
- EntityType: Types of entities that can be linked to claims
- EntityRole: Roles entities play in claims
- ConflictStatus: States of conflict sets
- ContextDomain: Life domains for organizing claims
- MetaJsonKeys: Standard keys for the meta_json field
"""

from enum import Enum
from typing import List


class ClaimType(str, Enum):
    """
    Classification of claims by their nature and purpose.

    These types help determine how claims should be treated in search,
    expiration, and conflict detection.
    """

    FACT = "fact"  # Stable assertions ("My home city is Bengaluru")
    MEMORY = "memory"  # Episodic experiences ("I enjoyed that restaurant")
    DECISION = "decision"  # Commitments ("I decided to avoid X")
    PREFERENCE = "preference"  # Likes/dislikes ("I prefer morning workouts")
    TASK = "task"  # Actionable items ("Buy medication")
    REMINDER = "reminder"  # Future prompts ("Remind me to call mom Friday")
    HABIT = "habit"  # Recurring targets ("Sleep by 11pm")
    OBSERVATION = "observation"  # Low-commitment notes ("Noticed knee pain")


class ClaimStatus(str, Enum):
    """
    Lifecycle states of claims.

    Claims transition through these states based on user actions,
    conflict detection, and temporal validity.
    """

    ACTIVE = "active"  # Currently valid and trusted
    CONTESTED = "contested"  # In conflict with other claims (shown with warnings)
    HISTORICAL = "historical"  # No longer current but preserved
    SUPERSEDED = "superseded"  # Replaced by a newer claim
    RETRACTED = "retracted"  # Soft-deleted by user
    DRAFT = "draft"  # Not yet confirmed/finalized

    @classmethod
    def default_search_statuses(cls) -> List[str]:
        """
        Default statuses included in search results.

        Contested claims ARE included by default but with warnings.
        """
        return [cls.ACTIVE.value, cls.CONTESTED.value]

    @classmethod
    def all_visible_statuses(cls) -> List[str]:
        """All statuses that should be visible in UI (excludes retracted)."""
        return [
            cls.ACTIVE.value,
            cls.CONTESTED.value,
            cls.HISTORICAL.value,
            cls.SUPERSEDED.value,
            cls.DRAFT.value,
        ]


class EntityType(str, Enum):
    """
    Types of entities that can be extracted from and linked to claims.

    Entities are canonical references to people, places, topics, etc.
    that appear across multiple claims.
    """

    PERSON = "person"  # Individual people (Mom, Dr. Smith)
    ORG = "org"  # Organizations (Google, local gym)
    PLACE = "place"  # Locations (Bengaluru, favorite cafe)
    TOPIC = "topic"  # Abstract topics (machine learning, fitness)
    PROJECT = "project"  # Projects or initiatives (home renovation)
    SYSTEM = "system"  # Technical systems (this PKB, chatbot)
    OTHER = "other"  # Catch-all for unclassified entities


class EntityRole(str, Enum):
    """
    Roles that entities play within a claim.

    Used in the claim_entities join table to specify the relationship
    between an entity and a claim.
    """

    SUBJECT = "subject"  # The entity performing the action
    OBJECT = "object"  # The entity receiving the action
    MENTIONED = "mentioned"  # Entity is referenced but not central
    ABOUT_PERSON = "about_person"  # Claim is about this person


class ConflictStatus(str, Enum):
    """
    States of conflict sets (groups of contradicting claims).

    Conflict sets track contradictions for user resolution.
    """

    OPEN = "open"  # Conflict detected, needs resolution
    RESOLVED = "resolved"  # User has resolved the conflict
    IGNORED = "ignored"  # User chose to leave the conflict unresolved


class ContextDomain(str, Enum):
    """
    Life domains for organizing and filtering claims.

    These domains help segment personal knowledge for
    privacy and relevance filtering.
    """

    PERSONAL = "personal"  # General personal facts
    HEALTH = "health"  # Health, medical, fitness
    RELATIONSHIPS = "relationships"  # Family, friends, social
    LEARNING = "learning"  # Education, skills, knowledge
    LIFE_OPS = "life_ops"  # Daily operations, logistics
    WORK = "work"  # Professional, career
    FINANCE = "finance"  # Financial matters


class MetaJsonKeys:
    """
    Standard keys for the meta_json field.

    These are documented conventions, not enforced by schema.
    Using standardized keys enables future tooling and migrations.

    Example meta_json:
    {
        "keywords": ["workout", "morning", "exercise"],
        "source": "chat_distillation",
        "visibility": "default",
        "llm": {"model": "gpt-4o-mini", "prompt_version": "v1", "confidence_notes": "..."}
    }
    """

    KEYWORDS = "keywords"  # List[str] - extracted keywords for search
    SOURCE = "source"  # str - "manual"|"chat_distillation"|"import"
    VISIBILITY = "visibility"  # str - "default"|"restricted"|"shareable"
    LLM = "llm"  # Dict - {model, prompt_version, confidence_notes}

    # Source values
    SOURCE_MANUAL = "manual"
    SOURCE_CHAT_DISTILLATION = "chat_distillation"
    SOURCE_IMPORT = "import"

    # Visibility values
    VISIBILITY_DEFAULT = "default"
    VISIBILITY_RESTRICTED = "restricted"
    VISIBILITY_SHAREABLE = "shareable"


# Convenience lists for validation
ALL_CLAIM_TYPES = [e.value for e in ClaimType]
ALL_CLAIM_STATUSES = [e.value for e in ClaimStatus]
ALL_ENTITY_TYPES = [e.value for e in EntityType]
ALL_ENTITY_ROLES = [e.value for e in EntityRole]
ALL_CONFLICT_STATUSES = [e.value for e in ConflictStatus]
ALL_CONTEXT_DOMAINS = [e.value for e in ContextDomain]

# Friendly ID pattern: alphanumeric + underscores + hyphens, 2-128 chars
FRIENDLY_ID_REGEX = r"^[a-zA-Z0-9_-]{2,128}$"

# Reference patterns for parsing @references in chat messages
# New friendly_id syntax: @some_friendly_id (alphanumeric, underscores, hyphens)
# Old UUID syntax: @memory:uuid or @mem:uuid (backwards compatible)
REFERENCE_FRIENDLY_ID_REGEX = r"@([a-zA-Z0-9_-]{2,128})"
REFERENCE_LEGACY_UUID_REGEX = r"@(?:memory|mem):([a-zA-Z0-9-]+)"


# =============================================================================
# Universal Reference Suffixes (v0.7)
# =============================================================================
# Type suffixes appended to friendly_ids to disambiguate object types.
# Claims have NO suffix (most common, backwards compatible).
# All other types have a _<type> suffix for unambiguous routing.

RESERVED_FRIENDLY_ID_SUFFIXES = ["_context", "_entity", "_tag", "_domain"]
"""Suffixes reserved for non-claim object types.

Claim friendly_id generation must avoid ending with any of these so that
the suffix-based routing in resolve_reference() works unambiguously.
"""

REFERENCE_TYPE_SUFFIXES = {
    "_context": "context",
    "_entity": "entity",
    "_tag": "tag",
    "_domain": "domain",
}
"""Mapping from friendly_id suffix to object type name.

Used by resolve_reference() to route @references directly to the
correct lookup without sequential fallback.
"""
