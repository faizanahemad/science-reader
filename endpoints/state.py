"""
Shared application state for endpoint modules.

`server.py` currently relies on many module-level globals (folders, caches,
registries). As we extract endpoints into separate modules, those globals become
hard to manage and create circular-import risk.

This module centralizes that shared state in a single dataclass and provides
simple accessors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class AppState:
    """
    Shared state used across multiple endpoint modules.

    Parameters
    ----------
    folder:
        Root storage folder (e.g., "storage") resolved to an absolute path.
    users_dir:
        Directory where user DB/files are stored.
    pdfs_dir:
        Directory where uploaded PDFs are stored.
    locks_dir:
        Directory used for lock files.
    cache_dir:
        Directory used by Flask-Caching filesystem backend.
    conversation_folder:
        Directory where conversation artifacts are stored.
    login_not_needed:
        Whether auth is bypassed.
    conversation_cache:
        In-memory cache for conversations/docindexes (type is project-specific).
    pinned_claims:
        In-memory pinned claims store (type is project-specific).
    cache:
        Optional Flask-Caching extension instance (if endpoints need direct access).
    limiter:
        Optional Flask-Limiter extension instance (if endpoints need direct access).
    """

    folder: str
    users_dir: str
    pdfs_dir: str
    locks_dir: str
    cache_dir: str
    conversation_folder: str
    login_not_needed: bool

    conversation_cache: Any
    pinned_claims: Any

    cache: Optional[Any] = None
    limiter: Optional[Any] = None


_state: Optional[AppState] = None


def init_state(
    *,
    folder: str,
    users_dir: str,
    pdfs_dir: str,
    locks_dir: str,
    cache_dir: str,
    conversation_folder: str,
    login_not_needed: bool,
    conversation_cache: Any,
    pinned_claims: Any,
    cache: Any = None,
    limiter: Any = None,
) -> AppState:
    """
    Initialize the process-global AppState used by endpoint modules.

    This should be called exactly once during app startup (in `server.create_app`).
    """

    global _state
    _state = AppState(
        folder=folder,
        users_dir=users_dir,
        pdfs_dir=pdfs_dir,
        locks_dir=locks_dir,
        cache_dir=cache_dir,
        conversation_folder=conversation_folder,
        login_not_needed=login_not_needed,
        conversation_cache=conversation_cache,
        pinned_claims=pinned_claims,
        cache=cache,
        limiter=limiter,
    )
    return _state


def get_state() -> AppState:
    """
    Fetch the initialized AppState.

    Raises
    ------
    RuntimeError
        If called before `init_state`.
    """

    if _state is None:
        raise RuntimeError("AppState not initialized. Call init_state(...) during app startup.")
    return _state


