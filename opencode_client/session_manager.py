"""
Session manager for mapping conversation IDs to OpenCode sessions.

Each conversation in the Flask app can be backed by one or more OpenCode
sessions.  ``SessionManager`` tracks this mapping via
``conversation_settings.opencode_config`` and delegates persistence to
caller-supplied callbacks so that this module never imports ``Conversation``
directly.

Storage schema inside ``conversation_settings``::

    {
        "opencode_config": {
            "active_session_id": "ses_abc123",
            "session_ids": ["ses_abc123", "ses_def456"],
            ...
        }
    }
"""

import logging
from typing import Any, Callable, Dict, List, Optional


import requests
from opencode_client.client import OpencodeClient

logger = logging.getLogger(__name__)

# Type alias for the settings read/write callbacks.
# get_settings(conversation_id) -> dict
# set_settings(conversation_id, settings_dict) -> None
GetSettingsFn = Callable[[str], Dict[str, Any]]
SetSettingsFn = Callable[[str, Dict[str, Any]], None]


class SessionManager:
    """Maps conversation IDs to OpenCode session IDs.

    Avoids importing ``Conversation.py`` by accepting callbacks for reading
    and writing ``conversation_settings``.

    Parameters
    ----------
    client : OpencodeClient
        Authenticated OpenCode client.
    get_settings_fn : callable
        ``fn(conversation_id) -> dict`` — reads the conversation settings.
    set_settings_fn : callable
        ``fn(conversation_id, settings_dict) -> None`` — persists settings.
    """

    def __init__(
        self,
        client: OpencodeClient,
        get_settings_fn: GetSettingsFn,
        set_settings_fn: SetSettingsFn,
    ):
        self._client = client
        self._get_settings = get_settings_fn
        self._set_settings = set_settings_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create_session(
        self,
        conversation_id: str,
        title: Optional[str] = None,
    ) -> str:
        """Return the active session ID, creating one if none exists.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.
        title : str, optional
            Title for a newly-created session.

        Returns
        -------
        str
            OpenCode session ID.
        """
        oc_config = self._read_opencode_config(conversation_id)
        active_id = oc_config.get("active_session_id")

        if active_id:
            # Verify the session still exists on the server
            try:
                self._client.get_session(active_id)
                return active_id
            except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError):
                logger.warning(
                    "Active session %s for conversation %s no longer exists; "
                    "creating a new one",
                    active_id,
                    conversation_id,
                )

        # No active session (or it was stale) — create a new one
        return self.create_new_session(conversation_id, title=title)

    def create_new_session(
        self,
        conversation_id: str,
        title: Optional[str] = None,
    ) -> str:
        """Force-create a new OpenCode session and make it active.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.
        title : str, optional
            Human-readable session title.

        Returns
        -------
        str
            The newly created session ID.
        """
        session_title = title or f"Conversation {conversation_id[:8]}"
        session = self._client.create_session(title=session_title)
        session_id = session["id"]

        oc_config = self._read_opencode_config(conversation_id)
        session_ids = oc_config.get("session_ids", [])
        if session_id not in session_ids:
            session_ids.append(session_id)
        oc_config["session_ids"] = session_ids
        oc_config["active_session_id"] = session_id
        self._write_opencode_config(conversation_id, oc_config)

        logger.info(
            "Created OpenCode session %s for conversation %s",
            session_id,
            conversation_id,
        )
        return session_id

    def list_sessions_for_conversation(self, conversation_id: str) -> List[dict]:
        """List all OpenCode sessions attached to a conversation.

        Returns enriched session objects from the server for each stored
        session ID.  Sessions that no longer exist on the server are
        silently removed from the stored list.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.

        Returns
        -------
        list of dict
            Session objects from the OpenCode API.  Each dict also includes
            an ``"is_active"`` boolean.
        """
        oc_config = self._read_opencode_config(conversation_id)
        session_ids = oc_config.get("session_ids", [])
        active_id = oc_config.get("active_session_id")

        results: List[dict] = []
        valid_ids: List[str] = []

        for sid in session_ids:
            try:
                info = self._client.get_session(sid)
                info["is_active"] = sid == active_id
                results.append(info)
                valid_ids.append(sid)
            except Exception:
                logger.warning(
                    "Session %s no longer exists on server; removing from conversation %s",
                    sid,
                    conversation_id,
                )

        # Prune stale IDs
        if len(valid_ids) != len(session_ids):
            oc_config["session_ids"] = valid_ids
            if active_id and active_id not in valid_ids:
                oc_config["active_session_id"] = valid_ids[0] if valid_ids else ""
            self._write_opencode_config(conversation_id, oc_config)

        return results

    def switch_session(self, conversation_id: str, session_id: str) -> bool:
        """Switch the active session for a conversation.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.
        session_id : str
            The OpenCode session ID to make active.  Must already be in the
            conversation's session list.

        Returns
        -------
        bool
            True if the switch was successful, False if the session_id is
            not associated with this conversation.
        """
        oc_config = self._read_opencode_config(conversation_id)
        session_ids = oc_config.get("session_ids", [])

        if session_id not in session_ids:
            logger.warning(
                "Cannot switch to session %s — not in conversation %s session list",
                session_id,
                conversation_id,
            )
            return False

        oc_config["active_session_id"] = session_id
        self._write_opencode_config(conversation_id, oc_config)
        logger.info(
            "Switched conversation %s to session %s",
            conversation_id,
            session_id,
        )
        return True

    def get_active_session_id(self, conversation_id: str) -> Optional[str]:
        """Return the active session ID without creating one.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.

        Returns
        -------
        str or None
            Active session ID, or None if no session is mapped.
        """
        oc_config = self._read_opencode_config(conversation_id)
        return oc_config.get("active_session_id") or None

    def remove_session(self, conversation_id: str, session_id: str) -> bool:
        """Remove a session from a conversation's tracking list.

        Does **not** delete the session on the OpenCode server — only removes
        the local mapping.  If the removed session was active, the first
        remaining session becomes active.

        Parameters
        ----------
        conversation_id : str
            The Flask-side conversation identifier.
        session_id : str
            Session ID to remove.

        Returns
        -------
        bool
            True if the session was found and removed.
        """
        oc_config = self._read_opencode_config(conversation_id)
        session_ids = oc_config.get("session_ids", [])

        if session_id not in session_ids:
            return False

        session_ids.remove(session_id)
        oc_config["session_ids"] = session_ids

        if oc_config.get("active_session_id") == session_id:
            oc_config["active_session_id"] = session_ids[0] if session_ids else ""

        self._write_opencode_config(conversation_id, oc_config)
        logger.info(
            "Removed session %s from conversation %s",
            session_id,
            conversation_id,
        )
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_opencode_config(self, conversation_id: str) -> Dict[str, Any]:
        """Read the ``opencode_config`` sub-dict from conversation settings.

        Parameters
        ----------
        conversation_id : str
            Conversation identifier.

        Returns
        -------
        dict
            The ``opencode_config`` dict (may be empty).
        """
        try:
            settings = self._get_settings(conversation_id)
        except Exception as exc:
            logger.error(
                "Failed to read settings for conversation %s: %s",
                conversation_id,
                exc,
            )
            settings = {}

        if not isinstance(settings, dict):
            settings = {}
        return settings.get("opencode_config", {})

    def _write_opencode_config(
        self, conversation_id: str, oc_config: Dict[str, Any]
    ) -> None:
        """Persist the ``opencode_config`` sub-dict back to conversation settings.

        Merges into existing settings rather than overwriting them.

        Parameters
        ----------
        conversation_id : str
            Conversation identifier.
        oc_config : dict
            Updated opencode config to persist.
        """
        try:
            settings = self._get_settings(conversation_id)
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}

        settings["opencode_config"] = oc_config

        try:
            self._set_settings(conversation_id, settings)
        except Exception as exc:
            logger.error(
                "Failed to write settings for conversation %s: %s",
                conversation_id,
                exc,
            )
