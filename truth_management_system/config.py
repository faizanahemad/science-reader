"""
Configuration management for PKB v0.

Provides PKBConfig dataclass with settings for:
- Database path and connection settings
- Feature toggles (FTS, embeddings)
- Search defaults (k, contested inclusion, validity filtering)
- LLM settings (model, temperature)
- Parallelization settings
- Logging settings

Configuration can be loaded from:
1. Direct dict (highest priority)
2. Config file (JSON/YAML)
3. Environment variables (PKB_ prefix)
4. Defaults (lowest priority)
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PKBConfig:
    """
    Configuration for PKB instance.
    
    Attributes:
        db_path: Path to SQLite database file. Supports ~ expansion.
        fts_enabled: Whether FTS5 search is enabled.
        embedding_enabled: Whether embedding-based search is enabled.
        default_k: Default number of results to return from searches.
        include_contested_by_default: Include contested claims in search results.
        validity_filter_default: Filter by temporal validity by default.
        llm_model: Default LLM model for extraction and rewriting.
        embedding_model: Model for text embeddings.
        llm_temperature: Temperature for LLM calls (0.0 for deterministic).
        max_parallel_llm_calls: Max concurrent LLM API calls.
        max_parallel_embedding_calls: Max concurrent embedding API calls.
        log_llm_calls: Log all LLM prompts and responses.
        log_search_queries: Log all search queries and results.
    """
    # Database
    db_path: str = "~/.pkb/kb.sqlite"
    
    # Feature toggles
    fts_enabled: bool = True
    embedding_enabled: bool = True
    # When True, claim embeddings are persisted at add/edit time and reused by
    # the add-path similarity/conflict check instead of being recomputed per add.
    embedding_cache_enabled: bool = True
    
    # Search defaults (from requirements)
    default_k: int = 20
    include_contested_by_default: bool = True
    validity_filter_default: bool = False  # Show everything unless filtered
    # Max number of existing active claims scanned for duplicate/conflict
    # detection on add_claim. <= 0 means no limit (scan all). Replaces the
    # former hardcoded cap of 100.
    conflict_scan_limit: int = 500

    # Ranking: post-fusion recency + confidence re-weight (Workstream C).
    # Applied ONCE after RRF merge as:
    #   final = rrf_score * (recency ** w_recency) * (confidence ** w_confidence)
    # where recency = 0.5 ** (age_days / half_life). Defaults reproduce the
    # current ranking EXACTLY: with w_recency = w_confidence = 0 both factors
    # are 1.0, so order is unchanged. Tune the weights (e.g. via the eval
    # harness) to enable recency/confidence-aware ranking.
    recency_rerank_enabled: bool = True
    w_recency: float = 0.15
    w_confidence: float = 0.1
    # Contested down-ranking (C2): multiplier applied to a contested claim's
    # score in the re-rank. 1.0 (default) = no-op; e.g. 0.5 halves it so
    # in-conflict claims sink below uncontested ones.
    contested_penalty: float = 1.0
    # D2 consolidation: cosine-similarity threshold above which two active
    # claims are clustered as near-duplicates and proposed for merge.
    consolidation_similarity_threshold: float = 0.95
    # D3 entity resolution: name-similarity threshold above which two entities
    # of the same type are proposed as variants of one canonical entity.
    entity_dedup_threshold: float = 0.85
    # W7: when True, an LLM verification pass confirms each cheap-similarity
    # dedup cluster (claims/entities/tags) is a true duplicate before it is
    # proposed for merge. Off by default (the cheap prefilter stands alone).
    dedup_llm_verify: bool = False
    # Confidence assumed when a claim has no explicit confidence value.
    default_confidence: float = 0.5
    # Default half-life (days) for recency decay; per-type overrides below.
    recency_half_life_days: float = 30.0
    # Optional per-claim-type half-life overrides (e.g. {"fact": 3650,
    # "observation": 7}). Falls back to recency_half_life_days when absent.
    half_life_by_type: Dict[str, float] = field(default_factory=dict)
    # Fresh claims keep recency floored at 1.0 for this many days (anti
    # rich-get-richer); 0 disables the grace floor.
    recency_grace_days: float = 0.0

    # --- Reinforcement & decay (Workstream H) -------------------------------
    # reinforce_claim() resets last_reinforced_at and nudges confidence toward
    # 1.0: confidence += (1 - confidence) * reinforce_alpha (diminishing returns).
    reinforce_alpha: float = 0.1
    # On reinforcement, extend a claim's hard TTL (valid_to) by this many days
    # per claim_type. Empty dict (default) = never extend TTL — inert.
    reinforce_ttl_days_by_type: Dict[str, float] = field(default_factory=dict)
    # How add_claim handles a near-duplicate (similarity > threshold):
    #   "off"            -> current behavior (warn only; H3 wiring disabled)
    #   "reinforce"      -> reinforce the existing claim, skip the duplicate
    #   "reinforce_warn" -> reinforce AND surface a warning
    # Default "off" keeps existing behavior until the H3 hook is enabled.
    reinforce_on_duplicate: str = "off"
    # Decay sweep (Workstream F2): freshness below this flips active->dormant.
    # 0.0 (default) disables dormancy decay — inert.
    dormancy_threshold: float = 0.0
    # Claim types that never decay to dormant even when dormancy is enabled
    # (e.g. ["fact", "identity"]). Empty (default) = every type is decayable.
    dormancy_exempt_types: List[str] = field(default_factory=list)
    # F1 scheduled sweep: interval (seconds) for the background lifecycle sweep
    # (hard-TTL expiry + soft-TTL dormancy). 0 (default) disables the scheduler
    # and leaves the existing lazy on-search sweep as the only trigger.
    sweep_interval_seconds: int = 0
    # F4 notifications: how many days ahead a task/reminder counts as
    # "soon to expire", and the window for "newly dormant" claims.
    notify_expiry_within_days: int = 7

    # G2 batch enrichment: when True (default), add_claim's auto-extract path
    # uses a single combined LLM call (analyze_claim_statement) to derive
    # type/domain/tags/entities/possible_questions, instead of ~5-6 separate
    # field-extraction calls + a separate question-generation call. Bulk adds
    # fan these combined calls out in parallel (batch_analyze). Set False to
    # restore the legacy multi-call extraction path.
    combined_enrichment: bool = True

    # D1 follow-up: when True (default), the conversation distiller checks
    # whether an extracted claim contradicts/replaces a closely-matched existing
    # claim and, if so, proposes a user-confirmed "supersede" action (link the
    # new claim as superseding the old, then retire the old) instead of adding a
    # parallel, conflicting claim. Set False to disable contradiction detection
    # in the distiller (saves an LLM call per close match).
    distiller_detect_contradictions: bool = True

    # Workstream B — vector index for embedding-search acceleration.
    #   ann_enabled    : use the cached vector index fast path (default True).
    #   ann_backend    : "flat" (numpy, exact, default) or "hnsw" (faiss,
    #                    approximate; falls back to flat if faiss is missing).
    #   ann_min_claims : only engage the index when the user has at least this
    #                    many cached embeddings; below it the exact linear scan
    #                    is already fast (keeps small corpora / eval identical).
    #   ann_overfetch  : retrieve k * ann_overfetch candidates from the index
    #                    before applying SQL filters, so post-filtering still
    #                    yields k results.
    ann_enabled: bool = True
    ann_backend: str = "flat"
    ann_min_claims: int = 200
    ann_overfetch: int = 5

    # Provenance (two-axis): inferred claims are trusted less.
    #   inferred_confidence_cap  : ceiling applied to a claim's confidence when
    #       its derivation is "inferred" (a conclusion the user never stated).
    #   inferred_rerank_penalty  : fraction by which an inferred claim's score
    #       is reduced in the recency/confidence re-rank (0.0 = no-op,
    #       0.1 = multiply score by 0.9). Active even when w_recency/w_confidence
    #       are 0, so inferred claims sink unless the penalty is set to 0.0.
    inferred_confidence_cap: float = 0.4
    inferred_rerank_penalty: float = 0.1

    # LLM settings
    llm_model: str = "google/gemini-3.1-flash-lite-preview"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_temperature: float = 0.0  # Deterministic for extraction

    # PKB Memory Overview — config-gated Key Areas snippet injection into
    # _get_pkb_context(). When True, a condensed ~100-word Key Areas section
    # from the overview is appended to the auto-retrieved PKB context on every
    # chat turn. Default off: the snippet may be stale and adds token cost.
    overview_snippet_in_context: bool = False

    # Short-term memory (cross-conversation)
    stm_enabled: bool = True
    stm_ttl_session_hours: float = 4.0
    stm_ttl_day_hours: float = 24.0
    stm_ttl_week_days: float = 7.0
    stm_max_per_user: int = 50
    stm_inject_limit: int = 10
    stm_inject_max_words: int = 200
    stm_reinforcement_threshold: float = 0.85
    stm_promotion_threshold: int = 3

    # Compaction
    compaction_stale_days: int = 90
    compaction_confidence_threshold: float = 0.5

    # Retrieval ranking — weighted RRF fusion (W-A).
    # Maps a strategy source name ('fts', 'embedding', 'rewrite', 'entity') to a
    # multiplier on its reciprocal-rank contribution. Empty dict => every weight
    # is 1.0 => identical to plain (unweighted) RRF. Tune via the eval harness.
    rrf_strategy_weights: Dict[str, float] = field(default_factory=dict)

    # Retrieval ranking — per-strategy query scoping (W-B).
    # When True, _get_pkb_context routes the focused current message to literal
    # FTS while semantic/embedding search keeps the contextual (summary-laden)
    # query, so past-topic summary text stops polluting literal matches.
    fts_use_focused_query: bool = True

    # Retrieval ranking — entity-linked retrieval strategy (W-C).
    # When enabled, an EntitySearchStrategy resolves named entities in the
    # query, pulls their linked claims (status-filtered) and contributes them
    # as another ranked list to RRF fusion. Returns nothing when no entity
    # resolves, so it is inert for entity-free queries.
    entity_strategy_enabled: bool = True
    entity_strategy_top_n: int = 5          # max entity-linked claims fed into RRF
    entity_strategy_max_entities: int = 5   # cap resolved entities per query (anti-flooding)
    entity_alias_match: bool = True         # also resolve via meta_json.aliases (W6)

    # Parallelization
    max_parallel_llm_calls: int = 8
    max_parallel_embedding_calls: int = 16
    
    # Logging
    log_llm_calls: bool = True
    log_search_queries: bool = True
    
    def expand_db_path(self) -> str:
        """
        Expand ~ and environment variables in db_path.
        
        Returns:
            Fully resolved absolute path to database file.
        """
        # Special-case SQLite in-memory DB identifiers.
        #
        # IMPORTANT:
        # - sqlite3 treats ':memory:' specially *only* if it is passed verbatim.
        # - Converting it to an absolute path (e.g. '/.../:memory:') turns it into a
        #   normal on-disk file, which can lead to confusing behavior (stale schema,
        #   cross-test contamination, etc.).
        if self.db_path == ":memory:":
            return ":memory:"
        # Keep SQLite URI paths as-is; PKBDatabase.connect will enable uri=True.
        if self.db_path.startswith("file:"):
            return self.db_path

        return os.path.abspath(os.path.expanduser(os.path.expandvars(self.db_path)))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'db_path': self.db_path,
            'fts_enabled': self.fts_enabled,
            'embedding_enabled': self.embedding_enabled,
            'embedding_cache_enabled': self.embedding_cache_enabled,
            'default_k': self.default_k,
            'include_contested_by_default': self.include_contested_by_default,
            'validity_filter_default': self.validity_filter_default,
            'conflict_scan_limit': self.conflict_scan_limit,
            'recency_rerank_enabled': self.recency_rerank_enabled,
            'w_recency': self.w_recency,
            'w_confidence': self.w_confidence,
            'contested_penalty': self.contested_penalty,
            'consolidation_similarity_threshold': self.consolidation_similarity_threshold,
            'entity_dedup_threshold': self.entity_dedup_threshold,
            'dedup_llm_verify': self.dedup_llm_verify,
            'default_confidence': self.default_confidence,
            'recency_half_life_days': self.recency_half_life_days,
            'half_life_by_type': dict(self.half_life_by_type),
            'recency_grace_days': self.recency_grace_days,
            'reinforce_alpha': self.reinforce_alpha,
            'reinforce_ttl_days_by_type': dict(self.reinforce_ttl_days_by_type),
            'reinforce_on_duplicate': self.reinforce_on_duplicate,
            'dormancy_threshold': self.dormancy_threshold,
            'dormancy_exempt_types': list(self.dormancy_exempt_types),
            'sweep_interval_seconds': self.sweep_interval_seconds,
            'notify_expiry_within_days': self.notify_expiry_within_days,
            'combined_enrichment': self.combined_enrichment,
            'distiller_detect_contradictions': self.distiller_detect_contradictions,
            'ann_enabled': self.ann_enabled,
            'ann_backend': self.ann_backend,
            'ann_min_claims': self.ann_min_claims,
            'ann_overfetch': self.ann_overfetch,
            'inferred_confidence_cap': self.inferred_confidence_cap,
            'inferred_rerank_penalty': self.inferred_rerank_penalty,
            'llm_model': self.llm_model,
            'embedding_model': self.embedding_model,
            'llm_temperature': self.llm_temperature,
            'max_parallel_llm_calls': self.max_parallel_llm_calls,
            'max_parallel_embedding_calls': self.max_parallel_embedding_calls,
            'rrf_strategy_weights': dict(self.rrf_strategy_weights),
            'fts_use_focused_query': self.fts_use_focused_query,
            'entity_strategy_enabled': self.entity_strategy_enabled,
            'entity_strategy_top_n': self.entity_strategy_top_n,
            'entity_strategy_max_entities': self.entity_strategy_max_entities,
            'entity_alias_match': self.entity_alias_match,
            'log_llm_calls': self.log_llm_calls,
            'log_search_queries': self.log_search_queries,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PKBConfig':
        """
        Create config from dictionary, ignoring unknown keys.
        
        Args:
            data: Dictionary with config values.
            
        Returns:
            PKBConfig instance with provided values.
        """
        valid_keys = {
            'db_path', 'fts_enabled', 'embedding_enabled', 'embedding_cache_enabled',
            'default_k', 'include_contested_by_default', 'validity_filter_default',
            'conflict_scan_limit',
            'recency_rerank_enabled', 'w_recency', 'w_confidence',
            'contested_penalty',
            'consolidation_similarity_threshold', 'entity_dedup_threshold',
            'dedup_llm_verify',
            'default_confidence', 'recency_half_life_days', 'half_life_by_type',
            'recency_grace_days',
            'reinforce_alpha', 'reinforce_ttl_days_by_type',
            'reinforce_on_duplicate', 'dormancy_threshold',
            'dormancy_exempt_types',
            'sweep_interval_seconds', 'notify_expiry_within_days',
            'combined_enrichment',
            'distiller_detect_contradictions',
            'ann_enabled', 'ann_backend', 'ann_min_claims', 'ann_overfetch',
            'inferred_confidence_cap', 'inferred_rerank_penalty',
            'llm_model', 'embedding_model', 'llm_temperature',
            'max_parallel_llm_calls', 'max_parallel_embedding_calls',
            'rrf_strategy_weights',
            'fts_use_focused_query',
            'entity_strategy_enabled', 'entity_strategy_top_n', 'entity_strategy_max_entities', 'entity_alias_match',
            'log_llm_calls', 'log_search_queries'
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def load_config(
    config_dict: Optional[Dict[str, Any]] = None,
    config_file: Optional[str] = None,
    env_prefix: str = "PKB_"
) -> PKBConfig:
    """
    Load configuration from multiple sources with priority:
    1. config_dict (highest priority)
    2. config_file (JSON)
    3. Environment variables (PKB_* prefix)
    4. Defaults (lowest priority)
    
    Args:
        config_dict: Dictionary with config values (highest priority).
        config_file: Path to JSON config file.
        env_prefix: Prefix for environment variables (default: PKB_).
        
    Returns:
        PKBConfig instance with merged configuration.
        
    Example:
        # Load from file
        config = load_config(config_file="~/.pkb/config.json")
        
        # Override with dict
        config = load_config(config_dict={"db_path": "./my_kb.sqlite"})
        
        # Use environment variables
        # PKB_DB_PATH=./test.sqlite PKB_DEFAULT_K=50 python app.py
        config = load_config()
    """
    merged: Dict[str, Any] = {}
    
    # 1. Start with defaults (from dataclass)
    defaults = PKBConfig()
    merged = defaults.to_dict()
    
    # 2. Load from environment variables
    env_mapping = {
        'DB_PATH': ('db_path', str),
        'FTS_ENABLED': ('fts_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'EMBEDDING_ENABLED': ('embedding_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'EMBEDDING_CACHE_ENABLED': ('embedding_cache_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'DEFAULT_K': ('default_k', int),
        'INCLUDE_CONTESTED_BY_DEFAULT': ('include_contested_by_default', lambda x: x.lower() in ('true', '1', 'yes')),
        'VALIDITY_FILTER_DEFAULT': ('validity_filter_default', lambda x: x.lower() in ('true', '1', 'yes')),
        'CONFLICT_SCAN_LIMIT': ('conflict_scan_limit', int),
        'RECENCY_RERANK_ENABLED': ('recency_rerank_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'W_RECENCY': ('w_recency', float),
        'W_CONFIDENCE': ('w_confidence', float),
        'CONTESTED_PENALTY': ('contested_penalty', float),
        'SWEEP_INTERVAL_SECONDS': ('sweep_interval_seconds', int),
        'NOTIFY_EXPIRY_WITHIN_DAYS': ('notify_expiry_within_days', int),
        'COMBINED_ENRICHMENT': ('combined_enrichment', lambda x: x.lower() in ('true', '1', 'yes')),
        'DISTILLER_DETECT_CONTRADICTIONS': ('distiller_detect_contradictions', lambda x: x.lower() in ('true', '1', 'yes')),
        'ANN_ENABLED': ('ann_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'ANN_BACKEND': ('ann_backend', str),
        'ANN_MIN_CLAIMS': ('ann_min_claims', int),
        'ANN_OVERFETCH': ('ann_overfetch', int),
        'INFERRED_CONFIDENCE_CAP': ('inferred_confidence_cap', float),
        'INFERRED_RERANK_PENALTY': ('inferred_rerank_penalty', float),
        'CONSOLIDATION_SIMILARITY_THRESHOLD': ('consolidation_similarity_threshold', float),
        'ENTITY_DEDUP_THRESHOLD': ('entity_dedup_threshold', float),
        'DEDUP_LLM_VERIFY': ('dedup_llm_verify', lambda x: x.lower() in ('true', '1', 'yes')),
        'DEFAULT_CONFIDENCE': ('default_confidence', float),
        'RECENCY_HALF_LIFE_DAYS': ('recency_half_life_days', float),
        'RECENCY_GRACE_DAYS': ('recency_grace_days', float),
        'REINFORCE_ALPHA': ('reinforce_alpha', float),
        'REINFORCE_ON_DUPLICATE': ('reinforce_on_duplicate', str),
        'DORMANCY_THRESHOLD': ('dormancy_threshold', float),
        'LLM_MODEL': ('llm_model', str),
        'EMBEDDING_MODEL': ('embedding_model', str),
        'LLM_TEMPERATURE': ('llm_temperature', float),
        'MAX_PARALLEL_LLM_CALLS': ('max_parallel_llm_calls', int),
        'MAX_PARALLEL_EMBEDDING_CALLS': ('max_parallel_embedding_calls', int),
        'RRF_STRATEGY_WEIGHTS': ('rrf_strategy_weights', lambda x: {str(k): float(v) for k, v in json.loads(x).items()}),
        'FTS_USE_FOCUSED_QUERY': ('fts_use_focused_query', lambda x: x.lower() in ('true', '1', 'yes')),
        'ENTITY_STRATEGY_ENABLED': ('entity_strategy_enabled', lambda x: x.lower() in ('true', '1', 'yes')),
        'ENTITY_STRATEGY_TOP_N': ('entity_strategy_top_n', int),
        'ENTITY_STRATEGY_MAX_ENTITIES': ('entity_strategy_max_entities', int),
        'ENTITY_ALIAS_MATCH': ('entity_alias_match', lambda x: x.lower() in ('true', '1', 'yes')),
        'LOG_LLM_CALLS': ('log_llm_calls', lambda x: x.lower() in ('true', '1', 'yes')),
        'LOG_SEARCH_QUERIES': ('log_search_queries', lambda x: x.lower() in ('true', '1', 'yes')),
    }
    
    for env_key, (config_key, converter) in env_mapping.items():
        env_var = f"{env_prefix}{env_key}"
        if env_var in os.environ:
            try:
                merged[config_key] = converter(os.environ[env_var])
            except (ValueError, TypeError):
                pass  # Skip invalid env values
    
    # 3. Load from config file
    if config_file:
        config_path = os.path.expanduser(os.path.expandvars(config_file))
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                file_config = json.load(f)
                merged.update({k: v for k, v in file_config.items() if k in merged})
    
    # 4. Apply config_dict overrides (highest priority)
    if config_dict:
        merged.update({k: v for k, v in config_dict.items() if k in merged})
    
    return PKBConfig.from_dict(merged)


def save_config(config: PKBConfig, config_file: str) -> None:
    """
    Save configuration to JSON file.
    
    Args:
        config: PKBConfig instance to save.
        config_file: Path to write JSON config.
    """
    config_path = os.path.expanduser(os.path.expandvars(config_file))
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)
