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
from typing import Dict, Optional, Any


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
    
    # Search defaults (from requirements)
    default_k: int = 20
    include_contested_by_default: bool = True
    validity_filter_default: bool = False  # Show everything unless filtered
    
    # LLM settings
    llm_model: str = "openai/gpt-4o-mini"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_temperature: float = 0.0  # Deterministic for extraction
    
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
        return os.path.abspath(os.path.expanduser(os.path.expandvars(self.db_path)))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'db_path': self.db_path,
            'fts_enabled': self.fts_enabled,
            'embedding_enabled': self.embedding_enabled,
            'default_k': self.default_k,
            'include_contested_by_default': self.include_contested_by_default,
            'validity_filter_default': self.validity_filter_default,
            'llm_model': self.llm_model,
            'embedding_model': self.embedding_model,
            'llm_temperature': self.llm_temperature,
            'max_parallel_llm_calls': self.max_parallel_llm_calls,
            'max_parallel_embedding_calls': self.max_parallel_embedding_calls,
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
            'db_path', 'fts_enabled', 'embedding_enabled', 'default_k',
            'include_contested_by_default', 'validity_filter_default',
            'llm_model', 'embedding_model', 'llm_temperature',
            'max_parallel_llm_calls', 'max_parallel_embedding_calls',
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
        'DEFAULT_K': ('default_k', int),
        'INCLUDE_CONTESTED_BY_DEFAULT': ('include_contested_by_default', lambda x: x.lower() in ('true', '1', 'yes')),
        'VALIDITY_FILTER_DEFAULT': ('validity_filter_default', lambda x: x.lower() in ('true', '1', 'yes')),
        'LLM_MODEL': ('llm_model', str),
        'EMBEDDING_MODEL': ('embedding_model', str),
        'LLM_TEMPERATURE': ('llm_temperature', float),
        'MAX_PARALLEL_LLM_CALLS': ('max_parallel_llm_calls', int),
        'MAX_PARALLEL_EMBEDDING_CALLS': ('max_parallel_embedding_calls', int),
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
