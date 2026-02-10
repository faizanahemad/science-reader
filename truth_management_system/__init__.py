"""
Truth Management System (PKB v0)

A personal knowledge base for storing, searching, and managing
personal facts, preferences, decisions, and memories.

Quick Start:
    from truth_management_system import PKBConfig, get_database, StructuredAPI

    # Initialize
    config = PKBConfig(db_path="./my_kb.sqlite")
    db = get_database(config)
    keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}
    api = StructuredAPI(db, keys, config)

    # Add a claim
    result = api.add_claim(
        statement="I prefer morning workouts",
        claim_type="preference",
        context_domain="health",
        auto_extract=True
    )

    # Search
    results = api.search("what are my workout preferences?")

    # Natural language commands
    from truth_management_system.interface import TextOrchestrator
    orchestrator = TextOrchestrator(api, keys)
    result = orchestrator.process("remember that I like coffee")

Features:
- SQLite-backed storage with FTS5 full-text search
- Multiple search strategies (FTS, embedding, LLM rewrite, hybrid)
- Tag and entity extraction/linking
- Conflict detection and resolution
- Conversation distillation for chat integration
- Text ingestion for bulk memory import with AI analysis
"""

__version__ = "0.1.0"

# Core configuration and database
from .config import PKBConfig, load_config, save_config
from .database import PKBDatabase, get_database, get_memory_database

# Data models
from .models import (
    Claim,
    Note,
    Entity,
    Tag,
    ConflictSet,
    Context,
    ContextClaim,
    ClaimTag,
    ClaimEntity,
    CLAIM_COLUMNS,
    NOTE_COLUMNS,
    ENTITY_COLUMNS,
    TAG_COLUMNS,
    CONTEXT_COLUMNS,
)

# Constants/enums
from .constants import (
    ClaimType,
    ClaimStatus,
    EntityType,
    EntityRole,
    ConflictStatus,
    ContextDomain,
    MetaJsonKeys,
    ALL_CLAIM_TYPES,
    ALL_CLAIM_STATUSES,
    ALL_ENTITY_TYPES,
    ALL_ENTITY_ROLES,
    ALL_CONFLICT_STATUSES,
    ALL_CONTEXT_DOMAINS,
    FRIENDLY_ID_REGEX,
)

# CRUD operations
from .crud import (
    ClaimCRUD,
    NoteCRUD,
    EntityCRUD,
    TagCRUD,
    ConflictCRUD,
    ContextCRUD,
)

# Search strategies
from .search import (
    SearchStrategy,
    SearchFilters,
    SearchResult,
    FTSSearchStrategy,
    EmbeddingSearchStrategy,
    RewriteSearchStrategy,
    MapReduceSearchStrategy,
    HybridSearchStrategy,
    NotesSearchStrategy,
)

# Interface layer
from .interface import (
    StructuredAPI,
    ActionResult,
    TextOrchestrator,
    OrchestrationResult,
    ConversationDistiller,
    MemoryUpdatePlan,
    DistillationResult,
    CandidateClaim,
    TextIngestionDistiller,
    TextIngestionPlan,
    IngestCandidate,
    IngestProposal,
    IngestExecutionResult,
)

# LLM helpers
from .llm_helpers import LLMHelpers, ExtractionResult, ClaimAnalysisResult

# Utility functions
from .utils import (
    generate_uuid,
    generate_friendly_id,
    validate_friendly_id,
    now_iso,
    epoch_iso,
    is_valid_iso_timestamp,
    parse_meta_json,
    update_meta_json,
    get_parallel_executor,
    ParallelExecutor,
)

__all__ = [
    # Version
    "__version__",
    # Config and database
    "PKBConfig",
    "load_config",
    "save_config",
    "PKBDatabase",
    "get_database",
    "get_memory_database",
    # Models
    "Claim",
    "Note",
    "Entity",
    "Tag",
    "ConflictSet",
    "Context",
    "ContextClaim",
    "ClaimTag",
    "ClaimEntity",
    "CLAIM_COLUMNS",
    "NOTE_COLUMNS",
    "ENTITY_COLUMNS",
    "TAG_COLUMNS",
    "CONTEXT_COLUMNS",
    # Constants
    "ClaimType",
    "ClaimStatus",
    "EntityType",
    "EntityRole",
    "ConflictStatus",
    "ContextDomain",
    "MetaJsonKeys",
    "ALL_CLAIM_TYPES",
    "ALL_CLAIM_STATUSES",
    "ALL_ENTITY_TYPES",
    "ALL_ENTITY_ROLES",
    "ALL_CONFLICT_STATUSES",
    "ALL_CONTEXT_DOMAINS",
    "FRIENDLY_ID_REGEX",
    # CRUD
    "ClaimCRUD",
    "NoteCRUD",
    "EntityCRUD",
    "TagCRUD",
    "ConflictCRUD",
    "ContextCRUD",
    # Search
    "SearchStrategy",
    "SearchFilters",
    "SearchResult",
    "FTSSearchStrategy",
    "EmbeddingSearchStrategy",
    "RewriteSearchStrategy",
    "MapReduceSearchStrategy",
    "HybridSearchStrategy",
    "NotesSearchStrategy",
    # Interface
    "StructuredAPI",
    "ActionResult",
    "TextOrchestrator",
    "OrchestrationResult",
    "ConversationDistiller",
    "MemoryUpdatePlan",
    "DistillationResult",
    "CandidateClaim",
    "TextIngestionDistiller",
    "TextIngestionPlan",
    "IngestCandidate",
    "IngestProposal",
    "IngestExecutionResult",
    # LLM
    "LLMHelpers",
    "ExtractionResult",
    "ClaimAnalysisResult",
    # Utils
    "generate_uuid",
    "generate_friendly_id",
    "validate_friendly_id",
    "now_iso",
    "epoch_iso",
    "is_valid_iso_timestamp",
    "parse_meta_json",
    "update_meta_json",
    "get_parallel_executor",
    "ParallelExecutor",
]


def create_pkb(
    db_path: str = "~/.pkb/kb.sqlite", api_key: str = None, **config_kwargs
) -> tuple:
    """
    Convenience function to create a fully initialized PKB.

    Args:
        db_path: Path to SQLite database.
        api_key: OpenRouter API key for LLM features.
        **config_kwargs: Additional PKBConfig options.

    Returns:
        Tuple of (api, db, config) for the initialized PKB.

    Example:
        api, db, config = create_pkb("./my_kb.sqlite", api_key="sk-or-v1-...")
        api.add_claim(statement="Test", claim_type="fact", context_domain="personal")
    """
    config = PKBConfig(db_path=db_path, **config_kwargs)
    db = get_database(config)
    keys = {"OPENROUTER_API_KEY": api_key} if api_key else {}
    api = StructuredAPI(db, keys, config)

    return api, db, config
