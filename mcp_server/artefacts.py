"""
MCP artefacts server application.

Creates a ``FastMCP`` instance that exposes 11 artefact management tools
over the streamable-HTTP transport on port 8103.

Artefacts are the ONLY file creation mechanism in the system. The model
MUST use these tools to produce any persistent output (documents, code,
reports, notes). OpenCode can also directly edit artefact files using its
built-in bash/edit tools once it has the absolute ``file_path``.

Authentication and rate limiting are handled by Starlette middleware
that wraps the ASGI app returned by ``FastMCP.streamable_http_app()``.
This follows the same pattern as ``mcp_server/mcp_app.py``.

Entry point: ``create_artefacts_mcp_app(jwt_secret, rate_limit)`` returns a
Starlette ``ASGIApp`` ready to be run with uvicorn.

Launcher: ``start_artefacts_mcp_server()`` runs it in a daemon thread.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware, _health_check

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))


# ---------------------------------------------------------------------------
# Conversation loader
# ---------------------------------------------------------------------------


def _load_conversation(conversation_id: str):
    """Load a conversation by its ID from the local storage directory.

    Parameters
    ----------
    conversation_id : str
        Unique conversation identifier.

    Returns
    -------
    Conversation
        Loaded conversation instance.
    """
    from Conversation import Conversation

    folder = os.path.join(STORAGE_DIR, "conversations", conversation_id)
    return Conversation.load_local(folder)




# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_artefacts_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create the MCP artefacts server as an ASGI application.

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

    mcp = FastMCP(
        "Artefacts Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: artefacts_list
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_list(user_email: str, conversation_id: str) -> str:
        """List all artefacts in a conversation.

        Returns a JSON array of artefact metadata objects, each containing:
        id, name, file_type, file_name, created_at, updated_at, size_bytes.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation to list artefacts from.
        """
        try:
            conv = _load_conversation(conversation_id)
            artefacts = conv.list_artefacts()
            return json.dumps(artefacts)
        except Exception as exc:
            logger.exception("artefacts_list error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 2: artefacts_create
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_create(
        user_email: str,
        conversation_id: str,
        name: str,
        file_type: str,
        initial_content: str = "",
    ) -> str:
        """Create a new artefact file in the conversation.

        Artefacts are the ONLY way to create persistent files. Returns
        file_path for direct editing with bash/edit tools.
        File types: md, txt, py, js, json, html, css.

        This is the primary file creation tool in the system. The returned
        file_path is an absolute path that OpenCode can use with native
        edit/bash tools for subsequent modifications.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation to create the artefact in.
            name: Display name for the artefact.
            file_type: File extension (e.g., 'md', 'py', 'json').
            initial_content: Initial file content (default empty).
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.create_artefact(name, file_type, initial_content)
            result["file_path"] = os.path.join(
                conv.artefacts_path, result["file_name"]
            )
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_create error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 3: artefacts_get
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_get(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Get artefact metadata, content, and file_path.

        Returns the full artefact including its content read from disk
        and the absolute file_path for direct editing.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.get_artefact(artefact_id)
            result["file_path"] = os.path.join(
                conv.artefacts_path, result["file_name"]
            )
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_get error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 4: artefacts_get_file_path
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_get_file_path(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Get the absolute file path for an artefact.

        Returns JUST the absolute filesystem path so OpenCode can edit
        the artefact directly with native bash/edit tools. This is the
        key tool for enabling direct file manipulation.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
        """
        try:
            conv = _load_conversation(conversation_id)
            _idx, entry = conv._get_artefact_entry(artefact_id)
            file_path = os.path.join(conv.artefacts_path, entry["file_name"])
            return json.dumps({"file_path": file_path})
        except Exception as exc:
            logger.exception("artefacts_get_file_path error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 5: artefacts_update
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_update(
        user_email: str, conversation_id: str, artefact_id: str, content: str
    ) -> str:
        """Update the full content of an artefact.

        Overwrites the artefact file with the given content. Use this
        when replacing the entire file via MCP. For partial edits,
        prefer using artefacts_get_file_path and editing directly.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            content: New file content to write.
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.update_artefact_content(artefact_id, content)
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_update error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 6: artefacts_delete
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_delete(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Delete an artefact file and its metadata.

        Removes the artefact file from disk and clears its metadata
        entry from the conversation.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact to delete.
        """
        try:
            conv = _load_conversation(conversation_id)
            conv.delete_artefact(artefact_id)
            return json.dumps({"success": True})
        except Exception as exc:
            logger.exception("artefacts_delete error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 7: artefacts_propose_edits (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_propose_edits(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        instruction: str,
        selection_start_line: Optional[int] = None,
        selection_end_line: Optional[int] = None,
    ) -> str:
        """Propose LLM-generated edits to an artefact.

        Sends the instruction to the Flask backend which generates
        edit operations using an LLM. Returns proposed ops and a diff.
        Only in full tier — OpenCode can use bash edit directly instead.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            instruction: Natural language edit instruction for the LLM.
            selection_start_line: Optional start line of selection to edit.
            selection_end_line: Optional end line of selection to edit.
        """
        import requests

        try:
            url = (
                f"http://localhost:{FLASK_PORT}"
                f"/artefacts/{conversation_id}/{artefact_id}/propose_edits"
            )
            body: dict[str, Any] = {"instruction": instruction}
            if selection_start_line is not None:
                body["selection_start_line"] = selection_start_line
            if selection_end_line is not None:
                body["selection_end_line"] = selection_end_line
            resp = requests.post(url, json=body, timeout=120)
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as exc:
            logger.exception("artefacts_propose_edits error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 8: artefacts_apply_edits (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_apply_edits(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        base_hash: str,
        ops: list,
    ) -> str:
        """Apply proposed edit operations to an artefact.

        Applies previously proposed ops if the base_hash matches
        (optimistic concurrency control). Only in full tier.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            base_hash: Hash of the content the ops were generated against.
            ops: List of edit operations to apply.
        """
        import requests

        try:
            url = (
                f"http://localhost:{FLASK_PORT}"
                f"/artefacts/{conversation_id}/{artefact_id}/apply_edits"
            )
            body = {"base_hash": base_hash, "ops": ops}
            resp = requests.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as exc:
            logger.exception("artefacts_apply_edits error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 9: read_artefact (with query, line range, and map view)
    # -----------------------------------------------------------------

    @mcp.tool()
    def read_artefact(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        map_view: bool = False,
        query: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Read an artefact with four modes (checked in order):

        1. map_view=true: structural map (headers, table columns, bold openers) with line numbers.
        2. query provided: artefact + query sent to LLM, answer returned.
        3. start_line/end_line: returns that line range with line numbers.
        4. Otherwise: full content.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            map_view: If true, return bird's-eye structural map.
            query: Question about the artefact (LLM answers).
            start_line: Start line (1-indexed) for partial read.
            end_line: End line (1-indexed) for partial read.
        """
        import re
        try:
            conv = _load_conversation(conversation_id)
            artefact = conv.get_artefact(artefact_id)
            content = artefact.get("content", "")
            name = artefact.get("name", "")
            file_type = artefact.get("file_type", "")

            if map_view:
                lines = content.splitlines()
                landmarks = []
                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if re.match(r'^#{1,4}\s+', stripped):
                        landmarks.append(f"L{i}: {stripped}")
                    elif '|' in stripped and i < len(lines) and re.match(r'^[\s|:-]+$', lines[i].strip() if i < len(lines) else ""):
                        landmarks.append(f"L{i}: [table] {stripped}")
                    elif re.match(r'^(\*\*|__).+?(\*\*|__)', stripped):
                        landmarks.append(f"L{i}: {stripped[:80]}")
                    elif re.match(r'^<h[1-4]', stripped, re.IGNORECASE):
                        landmarks.append(f"L{i}: {stripped[:80]}")
                return json.dumps({"artefact_id": artefact_id, "name": name, "total_lines": len(lines), "map": "\n".join(landmarks)})

            elif query:
                import requests
                url = f"http://localhost:{FLASK_PORT}/artefacts/{conversation_id}/{artefact_id}/propose_edits"
                # Use a lightweight LLM call via the propose_edits infra isn't right — call directly
                from code_common.call_llm import CallLLm
                from code_common.utils import EXPENSIVE_LLM
                from endpoints.utils import keyParser
                keys = keyParser()
                llm = CallLLm(keys, model_name=EXPENSIVE_LLM[2], use_gpt4=False, use_16k=False)
                prompt = f"Document: {name} ({file_type})\n\nContent:\n{content}\n\nQuestion: {query}\n\nAnswer concisely based on the document."
                response = llm(prompt, stream=False, temperature=0.1, max_tokens=1500)
                answer = response if isinstance(response, str) else "".join(response) if hasattr(response, "__iter__") else str(response)
                return json.dumps({"artefact_id": artefact_id, "name": name, "query": query, "answer": answer.strip()})

            elif start_line and end_line:
                lines = content.splitlines()
                s = max(1, int(start_line)) - 1
                e = min(int(end_line), len(lines))
                excerpt = "\n".join(f"{i+s+1}: {lines[i+s]}" for i in range(e - s))
                return json.dumps({"artefact_id": artefact_id, "name": name, "total_lines": len(lines), "lines": f"{start_line}-{end_line}", "content": excerpt})

            else:
                return json.dumps({"artefact_id": artefact_id, "name": name, "file_type": file_type, "total_lines": len(content.splitlines()), "content": content})

        except Exception as exc:
            logger.exception("read_artefact error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 10: propose_artefact_edit (direct LLM, with context)
    # -----------------------------------------------------------------

    @mcp.tool()
    def propose_artefact_edit(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        instruction: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        include_context: bool = False,
    ) -> str:
        """Propose edits to an artefact using natural language instruction.

        LLM generates edit operations and returns a unified diff.
        Use include_context=true to inject conversation summary and recent messages.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            instruction: Natural language edit instruction.
            start_line: Optional focus start line (1-indexed).
            end_line: Optional focus end line (1-indexed).
            include_context: Include conversation summary and recent messages.
        """
        import hashlib
        from difflib import unified_diff
        try:
            conv = _load_conversation(conversation_id)
            artefact = conv.get_artefact(artefact_id)
            content = artefact.get("content", "")
            base_hash = hashlib.sha256(content.encode()).hexdigest()

            selection_text = ""
            if start_line and end_line:
                lines = content.splitlines()
                s = max(1, int(start_line)) - 1
                e = min(int(end_line), len(lines))
                selection_text = "\n".join(lines[s:e])

            summary_text, message_text = "", ""
            if include_context:
                summary_text = getattr(conv, "running_summary", "") or ""
                msgs = conv.get_message_list() or []
                recent = msgs[-10:]
                message_text = "\n".join(f"{m.get('role','')}: {(m.get('content','') or '')[:200]}" for m in recent)

            numbered = "\n".join(f"{i+1}: {l}" for i, l in enumerate(content.splitlines()))
            selection_block = "Selection (lines {}-{}):\n{}".format(start_line, end_line, selection_text) if selection_text else ""
            summary_block = "Conversation summary:\n{}".format(summary_text) if summary_text else ""
            messages_block = "Recent messages:\n{}".format(message_text) if message_text else ""
            prompt = f"""You are editing a file. Produce ONLY a JSON array of edit operations.

Instruction: {instruction}

File: {artefact.get("name", "")} ({artefact.get("file_type", "")})

{selection_block}
{summary_block}
{messages_block}

File content with line numbers:
{numbered}

Allowed operations:
[
  {{"op": "replace_range", "start_line": 1, "end_line": 3, "text": "new text"}},
  {{"op": "insert_at", "start_line": 2, "text": "inserted text"}},
  {{"op": "append", "text": "text to append"}},
  {{"op": "delete_range", "start_line": 4, "end_line": 6}}
]
Return ONLY the JSON array."""

            from code_common.call_llm import CallLLm
            from code_common.utils import EXPENSIVE_LLM
            from endpoints.utils import keyParser
            import re
            keys = keyParser()
            model_name = conv.get_model_override("artefact_propose_edits_model", EXPENSIVE_LLM[2]) if hasattr(conv, "get_model_override") else EXPENSIVE_LLM[2]
            llm = CallLLm(keys, model_name=model_name, use_gpt4=False, use_16k=False)
            response = llm(prompt, stream=False, temperature=0.2, max_tokens=2000, system="Return ONLY JSON.")
            response_text = response if isinstance(response, str) else "".join(response) if hasattr(response, "__iter__") else str(response)

            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            ops = json.loads(json_match.group()) if json_match else []

            from endpoints.artefacts import _apply_ops
            new_content = _apply_ops(content, ops)
            diff_text = "\n".join(unified_diff(
                content.splitlines(), new_content.splitlines(),
                fromfile="before", tofile="after", lineterm="",
            ))
            return json.dumps({"proposed_ops": ops, "diff_text": diff_text, "base_hash": base_hash, "new_hash": hashlib.sha256(new_content.encode()).hexdigest()})

        except Exception as exc:
            logger.exception("propose_artefact_edit error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 11: create_or_delete_artefact (combined)
    # -----------------------------------------------------------------

    @mcp.tool()
    def create_or_delete_artefact(
        user_email: str,
        conversation_id: str,
        action: str,
        artefact_id: Optional[str] = None,
        name: Optional[str] = None,
        file_type: Optional[str] = None,
        initial_content: str = "",
    ) -> str:
        """Create or delete an artefact in one tool.

        action='create': creates a new artefact (name and file_type required).
        action='delete': deletes the artefact (artefact_id required).

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation to operate on.
            action: 'create' or 'delete'.
            artefact_id: Required for delete.
            name: Required for create: display name.
            file_type: Required for create: file extension (md, txt, py, etc.).
            initial_content: Optional for create: starting content.
        """
        try:
            conv = _load_conversation(conversation_id)
            if action == "create":
                if not name:
                    return json.dumps({"error": "'name' is required for create"})
                result = conv.create_artefact(name, file_type or "txt", initial_content)
                result["file_path"] = os.path.join(conv.artefacts_path, result["file_name"])
                return json.dumps(result)
            elif action == "delete":
                if not artefact_id:
                    return json.dumps({"error": "'artefact_id' is required for delete"})
                conv.delete_artefact(artefact_id)
                return json.dumps({"status": "deleted", "artefact_id": artefact_id})
            else:
                return json.dumps({"error": f"Unknown action: {action}. Use 'create' or 'delete'."})
        except Exception as exc:
            logger.exception("create_or_delete_artefact error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Build the Starlette ASGI app with middleware layers
    # -----------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
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

    app_with_auth: ASGIApp = JWTAuthMiddleware(
        app_with_rate_limit, jwt_secret=jwt_secret
    )

    return app_with_auth, mcp


# ---------------------------------------------------------------------------
# Launcher: start in daemon thread (called from server.py)
# ---------------------------------------------------------------------------


def start_artefacts_mcp_server() -> None:
    """Start the MCP artefacts server in a daemon thread.

    Reads configuration from environment variables:
    - ``ARTEFACTS_MCP_ENABLED``: set to ``"false"`` to skip (default ``"true"``).
    - ``ARTEFACTS_MCP_PORT``: port number (default ``8103``).
    - ``MCP_JWT_SECRET``: HS256 secret for bearer-token verification.
    - ``MCP_RATE_LIMIT``: max tool calls per token per minute (default ``10``).

    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("ARTEFACTS_MCP_ENABLED", "true").lower() == "false":
        logger.info("Artefacts MCP server disabled (ARTEFACTS_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Artefacts MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the artefacts MCP server."
        )
        return

    port = int(os.getenv("ARTEFACTS_MCP_PORT", "8103"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_artefacts_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Artefacts MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Artefacts MCP server failed to start")

    thread = threading.Thread(target=_run, name="mcp-artefacts-server", daemon=True)
    thread.start()
    logger.info(
        "Artefacts MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
