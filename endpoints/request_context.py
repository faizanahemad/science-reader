"""
Shared request context helpers for endpoint modules.

Minimal-risk utilities only: small wrappers around the most repeated boilerplate
in endpoint modules (state + keys + attaching keys to docs/conversations).
"""

from __future__ import annotations

from typing import Any, Tuple

from flask import session

from endpoints.state import get_state
from endpoints.utils import keyParser, set_keys_on_docs


def get_state_and_keys() -> Tuple[Any, Any]:
    """
    Return `(state, keys)` for the current request.

    - state: `endpoints.state.AppState`
    - keys: whatever `endpoints.utils.keyParser(session)` returns
    """

    return get_state(), keyParser(session)


def attach_keys(obj: Any, keys: Any) -> Any:
    """
    Attach parsed keys to a Conversation/DocIndex/list of docs, preserving legacy behavior.
    """

    return set_keys_on_docs(obj, keys)


def get_conversation_with_keys(state: Any, *, conversation_id: str, keys: Any) -> Any:
    """
    Fetch a conversation from the state's cache and attach request keys to it.

    This is a tiny helper to replace the very common 2-liner:
    `conversation = state.conversation_cache[conversation_id]`
    `conversation = set_keys_on_docs(conversation, keys)`
    """

    return attach_keys(state.conversation_cache[conversation_id], keys)


