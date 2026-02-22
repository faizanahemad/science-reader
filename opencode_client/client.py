"""
HTTP client for the OpenCode ``opencode serve`` REST API.

Wraps every documented endpoint (sessions, messages, commands, health, config,
MCP, agents, sharing, permissions) behind a single ``OpencodeClient`` class.
Uses the ``requests`` library (sync) with HTTP Basic Auth.

Typical usage::

    from opencode_client import OpencodeClient

    client = OpencodeClient()
    session = client.create_session(title="my chat")
    client.send_message_async(session["id"], parts=[{"type": "text", "text": "Hello"}])
    for event in client.stream_events():
        print(event)
"""

import json
import logging
from typing import Any, Dict, Generator, List, Optional

import requests

from opencode_client.config import (
    OPENCODE_ASYNC_TIMEOUT,
    OPENCODE_BASE_URL,
    OPENCODE_DEFAULT_TIMEOUT,
    OPENCODE_SERVER_PASSWORD,
    OPENCODE_SERVER_USERNAME,
    OPENCODE_SSE_CONNECT_TIMEOUT,
    OPENCODE_SYNC_TIMEOUT,
)

logger = logging.getLogger(__name__)


class OpencodeClient:
    """Synchronous HTTP client for the OpenCode server API.

    Parameters
    ----------
    base_url : str, optional
        Root URL of the ``opencode serve`` instance.
    username : str, optional
        HTTP Basic Auth user (env ``OPENCODE_SERVER_USERNAME``).
    password : str, optional
        HTTP Basic Auth password (env ``OPENCODE_SERVER_PASSWORD``).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = (base_url or OPENCODE_BASE_URL).rstrip("/")
        self._username = username or OPENCODE_SERVER_USERNAME
        self._password = password or OPENCODE_SERVER_PASSWORD
        self._session = requests.Session()
        if self._password:
            self._session.auth = (self._username, self._password)
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build full URL from a relative path."""
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Execute an HTTP request with logging and error handling.

        Parameters
        ----------
        method : str
            HTTP verb (GET, POST, PATCH, DELETE).
        path : str
            API path (e.g. ``/session``).
        timeout : int, optional
            Override default timeout.
        **kwargs
            Forwarded to ``requests.Session.request``.

        Returns
        -------
        requests.Response

        Raises
        ------
        requests.HTTPError
            On 4xx/5xx responses.
        """
        url = self._url(path)
        timeout = timeout or OPENCODE_DEFAULT_TIMEOUT
        try:
            resp = self._session.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError:
            logger.error(
                "OpenCode API error: %s %s -> %s %s",
                method,
                path,
                resp.status_code,
                resp.text[:500],
            )
            raise
        except requests.exceptions.RequestException as exc:
            logger.error("OpenCode request failed: %s %s -> %s", method, path, exc)
            raise

    def _get(
        self, path: str, params: Optional[dict] = None, **kw: Any
    ) -> requests.Response:
        return self._request("GET", path, params=params, **kw)

    def _post(
        self, path: str, body: Optional[dict] = None, **kw: Any
    ) -> requests.Response:
        return self._request("POST", path, json=body, **kw)

    def _patch(
        self, path: str, body: Optional[dict] = None, **kw: Any
    ) -> requests.Response:
        return self._request("PATCH", path, json=body, **kw)

    def _delete(self, path: str, **kw: Any) -> requests.Response:
        return self._request("DELETE", path, **kw)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> dict:
        """Check server health and version.

        Returns
        -------
        dict
            Server health payload (includes version info).
        """
        return self._get("/global/health").json()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Retrieve the current server configuration.

        Returns
        -------
        dict
            Full configuration object.
        """
        return self._get("/config").json()

    def update_config(self, patch: dict) -> dict:
        """Update server configuration at runtime.

        Parameters
        ----------
        patch : dict
            Partial config to merge.

        Returns
        -------
        dict
            Updated configuration.
        """
        return self._patch("/config", body=patch).json()

    def get_providers(self) -> dict:
        """List available providers and their default models.

        Returns
        -------
        dict
            Provider catalog.
        """
        return self._get("/config/providers").json()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(
        self, title: Optional[str] = None, parent_id: Optional[str] = None
    ) -> dict:
        """Create a new OpenCode session.

        Parameters
        ----------
        title : str, optional
            Human-readable title.
        parent_id : str, optional
            Parent session ID for branching.

        Returns
        -------
        dict
            Created session object (includes ``id``).
        """
        body: Dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if parent_id is not None:
            body["parentID"] = parent_id
        return self._post("/session", body=body).json()

    def get_session(self, session_id: str) -> dict:
        """Get details for a single session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        dict
            Session object.
        """
        return self._get(f"/session/{session_id}").json()

    def list_sessions(self) -> List[dict]:
        """List all sessions on the server.

        Returns
        -------
        list of dict
            Session objects.
        """
        return self._get("/session").json()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        bool
            True if deleted successfully.
        """
        self._delete(f"/session/{session_id}")
        return True

    def update_session(self, session_id: str, title: Optional[str] = None) -> dict:
        """Update session metadata (e.g. title).

        Parameters
        ----------
        session_id : str
            Session identifier.
        title : str, optional
            New title.

        Returns
        -------
        dict
            Updated session object.
        """
        body: Dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        return self._patch(f"/session/{session_id}", body=body).json()

    def abort_session(self, session_id: str) -> bool:
        """Immediately stop generation for a session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        bool
            True on success.
        """
        self._post(f"/session/{session_id}/abort")
        return True

    def fork_session(self, session_id: str, message_id: Optional[str] = None) -> dict:
        """Fork (branch) a session, optionally at a specific message.

        Parameters
        ----------
        session_id : str
            Session to fork.
        message_id : str, optional
            Message to fork at.  If omitted, forks at latest message.

        Returns
        -------
        dict
            New forked session object.
        """
        body: Dict[str, Any] = {}
        if message_id is not None:
            body["messageID"] = message_id
        return self._post(f"/session/{session_id}/fork", body=body).json()

    def summarize_session(
        self, session_id: str, provider_id: str, model_id: str
    ) -> bool:
        """Summarize a session for context compaction.

        Parameters
        ----------
        session_id : str
            Session identifier.
        provider_id : str
            Provider to use for summarization (e.g. ``"anthropic"``).
        model_id : str
            Model to use (e.g. ``"claude-sonnet-4-5"``).

        Returns
        -------
        bool
            True on success.
        """
        self._post(
            f"/session/{session_id}/summarize",
            body={"providerID": provider_id, "modelID": model_id},
        )
        return True

    def get_session_status(self) -> dict:
        """Get status for all sessions (busy/idle).

        Returns
        -------
        dict
            Status mapping.
        """
        return self._get("/session/status").json()

    def get_session_children(self, session_id: str) -> List[dict]:
        """List child sessions (forks) of a session.

        Parameters
        ----------
        session_id : str
            Parent session identifier.

        Returns
        -------
        list of dict
            Child session objects.
        """
        return self._get(f"/session/{session_id}/children").json()

    def get_session_diff(
        self, session_id: str, message_id: Optional[str] = None
    ) -> List[dict]:
        """Get file diffs for a session.

        Parameters
        ----------
        session_id : str
            Session identifier.
        message_id : str, optional
            If given, only diffs up to this message.

        Returns
        -------
        list of dict
            Diff entries.
        """
        params: Dict[str, str] = {}
        if message_id is not None:
            params["messageID"] = message_id
        return self._get(f"/session/{session_id}/diff", params=params).json()

    def get_session_todos(self, session_id: str) -> List[dict]:
        """Get the todo list for a session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        list of dict
            Todo items.
        """
        return self._get(f"/session/{session_id}/todo").json()

    def revert_message(
        self, session_id: str, message_id: str, part_id: Optional[str] = None
    ) -> bool:
        """Revert (undo) a message or specific part.

        Parameters
        ----------
        session_id : str
            Session identifier.
        message_id : str
            Message to revert.
        part_id : str, optional
            Specific part to revert within the message.

        Returns
        -------
        bool
            True on success.
        """
        body: Dict[str, Any] = {"messageID": message_id}
        if part_id is not None:
            body["partID"] = part_id
        self._post(f"/session/{session_id}/revert", body=body)
        return True

    def unrevert_session(self, session_id: str) -> bool:
        """Restore previously reverted messages.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        bool
            True on success.
        """
        self._post(f"/session/{session_id}/unrevert")
        return True

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def _build_message_body(
        self,
        parts: List[dict],
        model: Optional[dict] = None,
        agent: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[List[str]] = None,
        no_reply: bool = False,
        format: Optional[str] = None,
    ) -> dict:
        """Assemble the JSON body shared by sync/async message endpoints.

        Parameters
        ----------
        parts : list of dict
            Message parts, e.g. ``[{"type": "text", "text": "hi"}]``.
        model : dict, optional
            ``{"providerID": "...", "modelID": "..."}``.
        agent : str, optional
            Agent name override.
        system : str, optional
            System prompt addition for this message.
        tools : list of str, optional
            Allowed tools list.
        no_reply : bool
            If True, message is stored but does not trigger LLM.
        format : str, optional
            Response format constraint.

        Returns
        -------
        dict
            Request body ready for ``json=`` kwarg.
        """
        body: Dict[str, Any] = {"parts": parts}
        if model is not None:
            body["model"] = model
        if agent is not None:
            body["agent"] = agent
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = tools
        if no_reply:
            body["noReply"] = True
        if format is not None:
            body["format"] = format
        return body

    def send_message_sync(
        self,
        session_id: str,
        parts: List[dict],
        model: Optional[dict] = None,
        agent: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[List[str]] = None,
        no_reply: bool = False,
        format: Optional[str] = None,
    ) -> dict:
        """Send a message and wait for the full response (synchronous).

        Parameters
        ----------
        session_id : str
            Target session.
        parts : list of dict
            Message parts (``[{"type": "text", "text": "..."}]``).
        model : dict, optional
            ``{"providerID": "...", "modelID": "..."}``.
        agent : str, optional
            Agent name override.
        system : str, optional
            Additional system prompt for this message.
        tools : list of str, optional
            Allowed tools.
        no_reply : bool
            If True, inject context without triggering AI response.
        format : str, optional
            Response format constraint.

        Returns
        -------
        dict
            The assistant's response message object.
        """
        body = self._build_message_body(
            parts,
            model=model,
            agent=agent,
            system=system,
            tools=tools,
            no_reply=no_reply,
            format=format,
        )
        return self._post(
            f"/session/{session_id}/message",
            body=body,
            timeout=OPENCODE_SYNC_TIMEOUT,
        ).json()

    def send_message_async(
        self,
        session_id: str,
        parts: List[dict],
        model: Optional[dict] = None,
        agent: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[str] = None,
        no_reply: bool = False,
    ) -> None:
        """Send a message asynchronously (returns immediately with 204).

        The response streams via the SSE ``/event`` endpoint.

        Parameters
        ----------
        session_id : str
            Target session.
        parts : list of dict
            Message parts.
        model : dict, optional
            ``{"providerID": "...", "modelID": "..."}``.
        agent : str, optional
            Agent name override.
        system : str, optional
            Additional system prompt.
        tools : str, optional
            Allowed tools.
        no_reply : bool
            If True, inject context without triggering AI response.
        """
        body = self._build_message_body(
            parts,
            model=model,
            agent=agent,
            system=system,
            tools=tools,
            no_reply=no_reply,
        )
        self._post(
            f"/session/{session_id}/prompt_async",
            body=body,
            timeout=OPENCODE_ASYNC_TIMEOUT,
        )

    def send_context(
        self,
        session_id: str,
        text: str,
        system: Optional[str] = None,
    ) -> None:
        """Inject context into a session without triggering an AI response.

        Convenience wrapper around :meth:`send_message_async` with
        ``no_reply=True``.

        Parameters
        ----------
        session_id : str
            Target session.
        text : str
            Context text to inject (appears as a user message in history).
        system : str, optional
            System prompt addition (appended, does not replace base prompt).
        """
        parts = [{"type": "text", "text": text}]
        self.send_message_async(
            session_id,
            parts=parts,
            system=system,
            no_reply=True,
        )

    def get_messages(self, session_id: str, limit: Optional[int] = None) -> List[dict]:
        """List messages in a session.

        Parameters
        ----------
        session_id : str
            Session identifier.
        limit : int, optional
            Max messages to return.

        Returns
        -------
        list of dict
            Message objects.
        """
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        return self._get(f"/session/{session_id}/message", params=params).json()

    def get_message(self, session_id: str, message_id: str) -> dict:
        """Get a single message by ID.

        Parameters
        ----------
        session_id : str
            Session identifier.
        message_id : str
            Message identifier.

        Returns
        -------
        dict
            Message object.
        """
        return self._get(f"/session/{session_id}/message/{message_id}").json()

    # ------------------------------------------------------------------
    # Commands and Shell
    # ------------------------------------------------------------------

    def execute_command(
        self,
        session_id: str,
        command: str,
        arguments: str = "",
        agent: Optional[str] = None,
        model: Optional[dict] = None,
    ) -> dict:
        """Execute an OpenCode slash command (e.g. ``compact``, ``diff``).

        Parameters
        ----------
        session_id : str
            Session identifier.
        command : str
            Command name (without leading ``/``).
        arguments : str
            Arguments string.
        agent : str, optional
            Agent override.
        model : dict, optional
            ``{"providerID": "...", "modelID": "..."}``.

        Returns
        -------
        dict
            Command result.
        """
        body: Dict[str, Any] = {"command": command, "arguments": arguments}
        if agent is not None:
            body["agent"] = agent
        if model is not None:
            body["model"] = model
        return self._post(
            f"/session/{session_id}/command",
            body=body,
            timeout=OPENCODE_SYNC_TIMEOUT,
        ).json()

    def run_shell(
        self,
        session_id: str,
        command: str,
        agent: str,
        model: Optional[dict] = None,
    ) -> dict:
        """Run a shell command inside an OpenCode session.

        Parameters
        ----------
        session_id : str
            Session identifier.
        command : str
            Shell command string.
        agent : str
            Agent that executes the command.
        model : dict, optional
            ``{"providerID": "...", "modelID": "..."}``.

        Returns
        -------
        dict
            Shell execution result.
        """
        body: Dict[str, Any] = {"command": command, "agent": agent}
        if model is not None:
            body["model"] = model
        return self._post(
            f"/session/{session_id}/shell",
            body=body,
            timeout=OPENCODE_SYNC_TIMEOUT,
        ).json()

    # ------------------------------------------------------------------
    # SSE streaming
    # ------------------------------------------------------------------

    def stream_events(
        self, session_id: Optional[str] = None
    ) -> Generator[dict, None, None]:
        """Connect to the global SSE event stream and yield parsed events.

        Opens a long-lived ``GET /event`` connection and manually parses the
        ``text/event-stream`` format (no external SSE library needed).

        Parameters
        ----------
        session_id : str, optional
            If provided, only events matching this session are yielded.
            Filtering is done client-side.

        Yields
        ------
        dict
            Parsed SSE event with keys ``event`` (event type string) and
            ``data`` (parsed JSON payload).  Raw lines that fail JSON parsing
            yield ``data`` as the raw string.
        """
        url = self._url("/event")
        auth = (self._username, self._password) if self._password else None
        # Use a fresh request (not self._session) so we can stream without
        # holding the session lock.
        resp = requests.get(
            url,
            stream=True,
            auth=auth,
            headers={"Accept": "text/event-stream"},
            timeout=(OPENCODE_SSE_CONNECT_TIMEOUT, None),  # (connect, read=infinite)
        )
        resp.raise_for_status()

        current_event = ""
        current_data_lines: List[str] = []

        for raw_line in resp.iter_lines(decode_unicode=True):
            # iter_lines strips the trailing newline.  An empty string
            # signals the end of an SSE block (blank line separator).
            if raw_line is None or raw_line == "":
                # Dispatch accumulated event
                if current_data_lines:
                    data_str = "\n".join(current_data_lines)
                    try:
                        data = json.loads(data_str)
                    except (json.JSONDecodeError, ValueError):
                        data = data_str

                    event_dict = {"event": current_event or "message", "data": data}

                    # Client-side session filter
                    if session_id is not None:
                        event_session = _extract_session_id(data)
                        if not event_session or event_session != session_id:
                            current_event = ""
                            current_data_lines = []
                            continue

                    yield event_dict

                current_event = ""
                current_data_lines = []
                continue

            if raw_line.startswith("event:"):
                current_event = raw_line[len("event:") :].strip()
            elif raw_line.startswith("data:"):
                current_data_lines.append(raw_line[len("data:") :].strip())
            elif raw_line.startswith("id:"):
                pass  # SSE id field — ignored for now
            elif raw_line.startswith("retry:"):
                pass  # SSE retry field — ignored
            # Lines starting with ':' are SSE comments (heartbeats), skip.

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def respond_permission(
        self,
        session_id: str,
        permission_id: str,
        response: str,
        remember: bool = False,
    ) -> bool:
        """Respond to a tool permission request.

        Parameters
        ----------
        session_id : str
            Session identifier.
        permission_id : str
            Permission request ID.
        response : str
            ``"allow"`` or ``"deny"``.
        remember : bool
            If True, remember this decision for future identical requests.

        Returns
        -------
        bool
            True on success.
        """
        self._post(
            f"/session/{session_id}/permissions/{permission_id}",
            body={"response": response, "remember": remember},
        )
        return True

    # ------------------------------------------------------------------
    # MCP (dynamic registration)
    # ------------------------------------------------------------------

    def get_mcp_status(self) -> dict:
        """Get MCP server status.

        Returns
        -------
        dict
            MCP status payload.
        """
        return self._get("/mcp").json()

    def add_mcp_server(self, name: str, config: dict) -> dict:
        """Register a new MCP server dynamically at runtime.

        Parameters
        ----------
        name : str
            MCP server name.
        config : dict
            Server configuration (transport, url, etc.).

        Returns
        -------
        dict
            Registration result.
        """
        return self._post("/mcp", body={"name": name, "config": config}).json()

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def list_agents(self) -> List[dict]:
        """List available agents.

        Returns
        -------
        list of dict
            Agent definitions.
        """
        return self._get("/agent").json()

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def share_session(self, session_id: str) -> dict:
        """Share a session (creates a public link).

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        dict
            Share metadata (includes URL).
        """
        return self._post(f"/session/{session_id}/share").json()

    def unshare_session(self, session_id: str) -> dict:
        """Revoke sharing for a session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        dict
            Result payload.
        """
        return self._delete(f"/session/{session_id}/share").json()


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _extract_session_id(data: Any) -> Optional[str]:
    """Extract the session ID from an SSE event data payload.

    Checks ``properties.part.sessionID`` first, then ``properties.sessionID``.

    Parameters
    ----------
    data : Any
        Parsed JSON from an SSE data field.

    Returns
    -------
    str or None
        Session ID if found, else None.
    """
    if not isinstance(data, dict):
        return None
    props = data.get("properties", {})
    if not isinstance(props, dict):
        return None
    # Check nested part first
    part = props.get("part", {})
    if isinstance(part, dict):
        sid = part.get("sessionID")
        if sid:
            return sid
    # Fallback to top-level properties
    return props.get("sessionID")
