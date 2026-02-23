"""
SSE-to-Flask streaming bridge for OpenCode events.

Translates the OpenCode SSE event stream into the newline-delimited JSON
format expected by the existing Flask chat UI::

    {"text": "...", "status": "..."}

The bridge filters events by session, accumulates text deltas, maps tool
status updates, detects completion (``session.idle``), and auto-approves
permission requests when configured.

Typical usage (inside a Flask streaming endpoint)::

    bridge = SSEBridge(client, session_id)
    for chunk in bridge.stream_response():
        yield json.dumps(chunk) + "\\n"
"""

import logging
import time
from typing import Any, Callable, Dict, Generator, Optional

from opencode_client.client import OpencodeClient, _extract_session_id
from opencode_client.config import (
    OPENCODE_AUTO_APPROVE_PERMISSIONS,
    OPENCODE_SSE_MAX_RECONNECTS,
    OPENCODE_SSE_RECONNECT_DELAY,
)

logger = logging.getLogger(__name__)


class SSEBridge:
    """Translates OpenCode SSE events into Flask streaming chunks.

    Parameters
    ----------
    client : OpencodeClient
        Authenticated client instance used for streaming and permission
        responses.
    session_id : str
        The OpenCode session to filter events for.
    is_cancelled_fn : callable, optional
        A zero-argument callable that returns ``True`` when the user has
        requested cancellation.  Checked on every event.
    auto_approve : bool, optional
        Whether to automatically approve tool permission requests.
        Defaults to the ``OPENCODE_AUTO_APPROVE_PERMISSIONS`` config value.
    """

    def __init__(
        self,
        client: OpencodeClient,
        session_id: str,
        is_cancelled_fn: Optional[Callable[[], bool]] = None,
        auto_approve: Optional[bool] = None,
    ):
        self._client = client
        self._session_id = session_id
        self._is_cancelled_fn = is_cancelled_fn
        self._auto_approve = (
            auto_approve
            if auto_approve is not None
            else OPENCODE_AUTO_APPROVE_PERMISSIONS
        )

        # Delta accumulation: part_id -> accumulated text so far
        self._text_parts: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stream_response(self) -> Generator[Dict[str, str], None, None]:
        """Stream translated events until completion or cancellation.

        Connects to the global SSE endpoint, filters for ``self._session_id``,
        and yields ``{"text": ..., "status": ...}`` dicts.  Handles reconnection
        on connection drops (up to ``OPENCODE_SSE_MAX_RECONNECTS`` times).

        Yields
        ------
        dict
            Keys ``text`` (str) and ``status`` (str).  ``text`` contains
            incremental content deltas; ``status`` is a human-readable progress
            indicator.
        """
        reconnects = 0
        logger.info("[SSE Bridge] Starting stream for session %s", self._session_id)
        print(f"[SSE Bridge] Starting stream for session {self._session_id}")
        while reconnects <= OPENCODE_SSE_MAX_RECONNECTS:
            try:
                yield from self._consume_stream()
                # Normal exit (stream ended after session.idle or error)
                return
            except (ConnectionError, OSError, StopIteration) as exc:
                reconnects += 1
                if reconnects > OPENCODE_SSE_MAX_RECONNECTS:
                    logger.error(
                        "SSE reconnect limit (%d) exceeded for session %s: %s",
                        OPENCODE_SSE_MAX_RECONNECTS,
                        self._session_id,
                        exc,
                    )
                    yield {
                        "text": "",
                        "status": "Connection lost — max reconnect attempts exceeded",
                    }
                    return
                logger.warning(
                    "SSE connection dropped for session %s (attempt %d/%d): %s",
                    self._session_id,
                    reconnects,
                    OPENCODE_SSE_MAX_RECONNECTS,
                    exc,
                )
                yield {
                    "text": "",
                    "status": f"Reconnecting... (attempt {reconnects}/{OPENCODE_SSE_MAX_RECONNECTS})",
                }
                time.sleep(OPENCODE_SSE_RECONNECT_DELAY)
            except Exception as exc:
                logger.exception(
                    "Unexpected error in SSE bridge for session %s", self._session_id
                )
                yield {
                    "text": "",
                    "status": f"Stream error: {exc}",
                }
                return

    # ------------------------------------------------------------------
    # Internal stream consumer
    # ------------------------------------------------------------------

    def _consume_stream(self) -> Generator[Dict[str, str], None, None]:
        """Read from the SSE stream and translate events.
        :meth:`stream_response` catches for reconnection.
        """
        event_count = 0
        logger.info("[SSE Bridge] Connecting to SSE endpoint for session %s", self._session_id)
        print(f"[SSE Bridge] Connecting to SSE endpoint for session {self._session_id}")
        for sse_event in self._client.stream_events(session_id=self._session_id):
            event_count += 1
            # ---- Cancellation check ----
            if self._is_cancelled_fn and self._is_cancelled_fn():
                logger.info("Cancellation detected for session %s", self._session_id)
                self._abort_session()
                yield {
                    "text": "\n\n**Response was cancelled by user**",
                    "status": "Response cancelled",
                }
                return
            raw_event_type = sse_event.get("event", "")
            data = sse_event.get("data", {})
            # OpenCode wraps ALL events under SSE event type "message".
            # The real event type lives in data["type"].
            if raw_event_type == "message" and isinstance(data, dict) and "type" in data:
                event_type = data["type"]
            else:
                event_type = raw_event_type
            # ---- Debug logging for first 5 events + all non-delta events ----
            if event_count <= 5 or event_type not in ("message.part.delta", "message.part.updated"):
                import json as _json
                data_preview = _json.dumps(data, default=str)[:500] if isinstance(data, dict) else str(data)[:500]
                logger.info("[SSE Bridge] Event #%d type=%s (raw=%s) data_preview=%s", event_count, event_type, raw_event_type, data_preview)
                print(f"[SSE Bridge] Event #{event_count} type={event_type} (raw={raw_event_type}) data_preview={data_preview[:200]}")
            # ---- Dispatch by event type ----
            chunk = self._handle_event(event_type, data)
            if chunk is not None:
                if chunk.get("_done"):
                    # Internal signal: stream is finished
                    logger.info("[SSE Bridge] Stream done after %d events for session %s", event_count, self._session_id)
                    print(f"[SSE Bridge] Stream done after {event_count} events")
                    chunk.pop("_done", None)
                    if chunk.get("text") or chunk.get("status"):
                        yield chunk
                    return
                yield chunk
        # If we fall off the end of the for loop, the SSE stream closed without session.idle
        logger.warning("[SSE Bridge] SSE stream ended without session.idle after %d events for session %s", event_count, self._session_id)
        print(f"[SSE Bridge] SSE stream ended unexpectedly after {event_count} events")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_event(self, event_type: str, data: Any) -> Optional[Dict[str, Any]]:
        """Route a single SSE event to the appropriate handler.

        Parameters
        ----------
        event_type : str
            SSE event name (e.g. ``message.part.updated``).
        data : Any
            Parsed JSON payload.

        Returns
        -------
        dict or None
            A Flask chunk dict, possibly with internal ``_done`` flag.
            ``None`` if the event should be silently skipped.
        """
        if event_type == "message.part.delta":
            return self._handle_part_delta(data)
        elif event_type in ("message.part.updated",):
            return self._handle_part_updated(data)
        elif event_type == "session.idle":
            return self._handle_session_idle(data)
        elif event_type == "session.error":
            return self._handle_session_error(data)
        elif event_type == "session.status":
            return self._handle_session_status(data)
        elif event_type == "permission.updated":
            return self._handle_permission(data)
        elif event_type == "message.updated":
            # Full message update — may contain final text, route same as part update
            return self._handle_part_updated(data)
        elif event_type == "session.updated":
            # Session metadata update — skip silently
            return None
        elif event_type == "session.diff":
            # File diff update — skip silently
            return None
        else:
            # Unknown event types are logged for debugging
            logger.debug("Ignoring SSE event type: %s (data keys: %s)", event_type, list(data.keys()) if isinstance(data, dict) else type(data).__name__)
            return None

    def _handle_part_delta(self, data: Any) -> Optional[Dict[str, str]]:
        """Handle ``message.part.delta`` events.

        Delta events have a flat structure at the properties level:
        ``{"type": "message.part.delta", "properties": {"sessionID": ...,
        "partID": ..., "field": "text", "content": "delta text", ...}}``

        This is different from ``message.part.updated`` which nests a full
        ``part`` object inside properties.

        Parameters
        ----------
        data : Any
            Parsed event data with flat ``properties`` containing ``field``
            and ``content``.

        Returns
        -------
        dict or None
        """
        if not isinstance(data, dict):
            return None
        props = data.get("properties", {})
        if not isinstance(props, dict):
            return None

        field = props.get("field", "")
        part_id = props.get("partID", "") or props.get("id", "") or "_anon_delta"

        if field == "text":
            # Text delta — the actual streaming content
            # Try 'content' first (OpenCode standard), fall back to 'delta'
            delta = props.get("content", "") or props.get("delta", "")
            if delta:
                self._text_parts[part_id] = self._text_parts.get(part_id, "") + delta
                return {"text": delta, "status": "Generating response..."}
            return None
        elif field == "reasoning":
            # Reasoning deltas — skip (could optionally surface later)
            return None
        else:
            # Other field types (tool state, etc.) — log and skip
            logger.debug("Ignoring delta for field: %s (partID=%s)", field, part_id)
            return None

    def _handle_part_updated(self, data: Any) -> Optional[Dict[str, str]]:
        """Handle ``message.part.updated`` events.

        Dispatches to text delta accumulation or tool status reporting
        depending on ``part.type``.

        Parameters
        ----------
        data : Any
            Parsed event data with ``properties.part``.

        Returns
        -------
        dict or None
        """
        props = data.get("properties", {}) if isinstance(data, dict) else {}
        part = props.get("part", {})
        if not isinstance(part, dict):
            # Log the data structure so we can see what's actually there
            import json as _json
            logger.warning("[SSE Bridge] _handle_part_updated: no 'part' dict in data. props_keys=%s, data_type=%s, data_preview=%s",
                           list(props.keys()) if isinstance(props, dict) else type(props).__name__,
                           type(data).__name__,
                           _json.dumps(data, default=str)[:300] if isinstance(data, dict) else str(data)[:300])
            return None
        part_type = part.get("type", "")
        part_id = part.get("id") or f"_anon_{id(part)}"

        if part_type == "text":
            return self._handle_text_delta(part, part_id)
        elif part_type == "tool":
            return self._handle_tool_status(part)
        elif part_type == "reasoning":
            # Reasoning parts are optionally skipped
            return None
        else:
            logger.debug("Ignoring message part type: %s", part_type)
            return None

    def _handle_text_delta(self, part: dict, part_id: str) -> Optional[Dict[str, str]]:
        """Extract incremental text delta from a text part update.

        Uses the ``delta`` field when present.  Falls back to diffing
        against the previously accumulated ``text`` for this part ID.

        Parameters
        ----------
        part : dict
            The ``part`` object from the event.
        part_id : str
            Unique part identifier for delta tracking.

        Returns
        -------
        dict or None
            ``{"text": delta, "status": "Generating response..."}``
        """
        delta = part.get("delta", "")

        if delta:
            # Explicit delta — preferred path
            self._text_parts[part_id] = self._text_parts.get(part_id, "") + delta
            return {"text": delta, "status": "Generating response..."}

        # Fallback: diff full accumulated text
        full_text = part.get("text", "")
        if not full_text:
            return None

        prev = self._text_parts.get(part_id, "")
        if full_text == prev:
            return None  # No change

        new_content = full_text[len(prev) :]
        self._text_parts[part_id] = full_text
        if new_content:
            return {"text": new_content, "status": "Generating response..."}
        return None

    def _handle_tool_status(self, part: dict) -> Optional[Dict[str, str]]:
        """Translate tool part updates to status messages.

        Parameters
        ----------
        part : dict
            The tool part object (contains ``state.status``, tool name, etc.).

        Returns
        -------
        dict or None
        """
        state = part.get("state", {})
        if not isinstance(state, dict):
            return None

        status = state.get("status", "")
        # Try to get a human-readable tool name
        tool_name = part.get("name", "") or part.get("toolName", "") or "tool"

        if status == "running":
            return {"text": "", "status": f"Running {tool_name}..."}
        elif status == "completed":
            return {"text": "", "status": f"Tool {tool_name} completed"}
        elif status == "error":
            error_msg = state.get("error", "unknown error")
            return {"text": "", "status": f"Tool {tool_name} failed: {error_msg}"}
        else:
            return {"text": "", "status": f"{tool_name}: {status}"}

    def _handle_session_idle(self, data: Any) -> Dict[str, Any]:
        """Handle ``session.idle`` — signals response completion.

        Parameters
        ----------
        data : Any
            Event payload (unused).

        Returns
        -------
        dict
            Chunk with ``_done`` flag to signal stream end.
        """
        logger.debug("Session %s is now idle", self._session_id)
        return {"text": "", "status": "Complete", "_done": True}

    def _handle_session_error(self, data: Any) -> Dict[str, Any]:
        """Handle ``session.error`` events.

        Parameters
        ----------
        data : Any
            Event payload containing error details.

        Returns
        -------
        dict
            Error chunk with ``_done`` flag.
        """
        error_msg = ""
        if isinstance(data, dict):
            props = data.get("properties", {})
            if isinstance(props, dict):
                error_msg = props.get("error", "") or props.get("message", "")
        if not error_msg:
            error_msg = "Unknown OpenCode error"

        logger.error("Session %s error: %s", self._session_id, error_msg)
        return {
            "text": f"\n\nOpenCode error: {error_msg}",
            "status": f"Error: {error_msg}",
            "_done": True,
        }

    def _handle_session_status(self, data: Any) -> Optional[Dict[str, str]]:
        """Handle ``session.status`` events (busy/idle transitions).

        Parameters
        ----------
        data : Any
            Event payload with status type.

        Returns
        -------
        dict or None
        """
        if not isinstance(data, dict):
            return None
        props = data.get("properties", {})
        if not isinstance(props, dict):
            return None
        status_type = props.get("type", "")
        if status_type == "busy":
            return {"text": "", "status": "Processing..."}
        # Other status types (including idle handled separately) are skipped
        return None

    def _handle_permission(self, data: Any) -> Optional[Dict[str, str]]:
        """Handle ``permission.updated`` events.

        When auto-approve is enabled, immediately approves the permission
        request via the API.

        Parameters
        ----------
        data : Any
            Event payload containing permission details.

        Returns
        -------
        dict or None
            Status update if the permission was handled, else None.
        """
        if not self._auto_approve:
            logger.debug("Permission request received but auto-approve is disabled")
            return {"text": "", "status": "Waiting for permission approval..."}

        if not isinstance(data, dict):
            return None

        props = data.get("properties", {})
        if not isinstance(props, dict):
            return None

        permission_id = props.get("id", "") or props.get("permissionID", "")
        if not permission_id:
            logger.warning("Permission event without ID, cannot auto-approve")
            return None

        try:
            self._client.respond_permission(
                self._session_id, permission_id, response="allow", remember=True
            )
            logger.info(
                "Auto-approved permission %s for session %s",
                permission_id,
                self._session_id,
            )
            return {"text": "", "status": "Permission auto-approved"}
        except Exception as exc:
            logger.error("Failed to auto-approve permission %s: %s", permission_id, exc)
            return {"text": "", "status": f"Permission approval failed: {exc}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _abort_session(self) -> None:
        """Best-effort abort of the OpenCode session on cancellation."""
        try:
            self._client.abort_session(self._session_id)
            logger.info("Aborted OpenCode session %s", self._session_id)
        except Exception as exc:
            logger.warning("Failed to abort session %s: %s", self._session_id, exc)
