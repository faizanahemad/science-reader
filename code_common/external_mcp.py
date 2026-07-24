"""Expose environment-configured remote MCP tools to the native chat registry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping
from urllib.parse import urlparse

from code_common.tools import ToolCallResult, ToolContext, ToolDefinition, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalMCPServer:
    """Connection settings for one Streamable HTTP MCP server."""

    name: str
    url: str
    headers: dict[str, str]
    timeout_seconds: int
    discovery_timeout_seconds: int
    always_enabled: bool = False


def _comma_separated(value: str) -> list[str]:
    return [item.strip() for item in value.split(",")]


def _parse_headers(environ: Mapping[str, str]) -> dict[str, dict[str, str]]:
    raw_headers = environ.get("MCP_HEADERS_JSON", "").strip()
    if not raw_headers:
        return {}
    try:
        parsed = json.loads(raw_headers)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP_HEADERS_JSON must be a JSON object keyed by URL or '*'.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("MCP_HEADERS_JSON must be a JSON object keyed by URL or '*'.")

    headers_by_server: dict[str, dict[str, str]] = {}
    for server_key, headers in parsed.items():
        if not isinstance(server_key, str) or not isinstance(headers, dict):
            raise ValueError("MCP_HEADERS_JSON values must be objects of string header names and values.")
        normalized: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("MCP_HEADERS_JSON header names and values must be strings.")
            normalized[name] = value
        if server_key == "*" and "Authorization" in normalized:
            raise ValueError("MCP_HEADERS_JSON must not set Authorization under '*'.")
        headers_by_server[server_key] = normalized
    return headers_by_server


def parse_external_mcp_servers(
    environ: Mapping[str, str] | None = None,
) -> list[ExternalMCPServer]:
    """Parse ``MCP_URLS`` and optional auth settings into remote MCP configs.

    ``MCP_AUTH_TOKENS`` is a comma-aligned list of bearer tokens. Use
    ``MCP_HEADERS_JSON`` for additional non-bearer headers keyed by URL or ``*``.
    """
    environ = os.environ if environ is None else environ
    urls = [url for url in _comma_separated(environ.get("MCP_URLS", "")) if url]
    always_urls = [
        url
        for url in _comma_separated(environ.get("MCP_ENABLE_ALWAYS_URLS", ""))
        if url
    ]
    always_url_set = set(always_urls)
    urls = list(dict.fromkeys([*urls, *always_urls]))
    if not urls:
        return []

    tokens = _comma_separated(environ.get("MCP_AUTH_TOKENS", ""))
    headers_by_server = _parse_headers(environ)
    try:
        timeout_seconds = int(environ.get("MCP_TIMEOUT_SECONDS", "120"))
        discovery_timeout_seconds = int(
            environ.get("MCP_DISCOVERY_TIMEOUT_SECONDS", "15")
        )
    except ValueError as exc:
        raise ValueError("MCP timeouts must be positive integers.") from exc
    if timeout_seconds <= 0 or discovery_timeout_seconds <= 0:
        raise ValueError("MCP timeouts must be positive integers.")

    servers = []
    for index, url in enumerate(urls, start=1):
        parsed_url = urlparse(url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.fragment
        ):
            raise ValueError(
                "MCP_URLS entries must be http(s) URLs without credentials or fragments."
            )
        headers = dict(headers_by_server.get("*", {}))
        headers.update(headers_by_server.get(url, {}))
        token = tokens[index - 1] if index <= len(tokens) else ""
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        servers.append(
            ExternalMCPServer(
                name=f"external_mcp_{index}",
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
                discovery_timeout_seconds=discovery_timeout_seconds,
                always_enabled=url in always_url_set,
            )
        )
    return servers


def _run_async(coro: Any) -> Any:
    """Run an MCP SDK coroutine from synchronous Flask startup/tool handlers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    failure: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive thread bridge
            failure["exception"] = exc

    import threading

    thread = threading.Thread(target=runner, name="external-mcp-call")
    thread.start()
    thread.join()
    if "exception" in failure:
        raise failure["exception"]
    return result.get("value")


def _tool_attribute(tool: Any, name: str, default: Any = None) -> Any:
    if isinstance(tool, dict):
        return tool.get(name, default)
    return getattr(tool, name, default)


def _tool_result_text(result: Any) -> str:
    """Preserve text, resource, and structured MCP result content as JSON-safe text."""
    content = _tool_attribute(result, "content", result)
    structured_content = _tool_attribute(result, "structuredContent")
    if structured_content is None:
        structured_content = _tool_attribute(result, "structured_content")

    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            text = _tool_attribute(item, "text")
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(json.dumps(item, default=str, sort_keys=True))
    elif content is not None:
        parts.append(json.dumps(content, default=str, sort_keys=True))
    if structured_content is not None:
        parts.append(json.dumps({"structured_content": structured_content}, default=str, sort_keys=True))

    text = "\n".join(parts)
    if _tool_attribute(result, "isError", False) or _tool_attribute(result, "is_error", False):
        raise RuntimeError(text or "External MCP server reported a tool error.")
    return text


class ExternalMCPClient:
    """Synchronous wrapper around the MCP Python SDK Streamable HTTP client."""

    def __init__(self, server: ExternalMCPServer) -> None:
        self.server = server

    async def _with_session(self, operation: Any, timeout_seconds: int) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            raise RuntimeError("MCP client support requires the 'mcp' package.") from exc

        async with streamablehttp_client(
            self.server.url,
            headers=self.server.headers or None,
            timeout=timeout_seconds,
        ) as transport:
            read_stream, write_stream, *_ = transport
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await operation(session)

    def list_tools(self) -> list[Any]:
        async def operation(session: Any) -> list[Any]:
            result = await session.list_tools()
            return list(result.tools)

        return _run_async(
            self._with_session(operation, self.server.discovery_timeout_seconds)
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        async def operation(session: Any) -> str:
            result = await session.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=self.server.timeout_seconds),
            )
            return _tool_result_text(result)

        return _run_async(self._with_session(operation, self.server.timeout_seconds))


def _safe_tool_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_") or "tool"


def _registered_tool_name(server: ExternalMCPServer, remote_name: str) -> str:
    """Return a collision-safe OpenAI-compatible name bounded to 64 characters."""
    digest = hashlib.sha256(f"{server.url}\0{remote_name}".encode()).hexdigest()[:8]
    prefix = f"{server.name}_"
    max_slug_length = 64 - len(prefix) - len(digest) - 1
    return f"{prefix}{_safe_tool_name(remote_name)[:max_slug_length]}_{digest}"


def discover_and_register_external_mcp_tools(
    registry: ToolRegistry,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Discover configured MCP tools and register synchronous proxy handlers.

    One unavailable server is logged and skipped so it cannot prevent Flask from
    starting or hide tools exposed by other configured servers.
    """
    registered_names: list[str] = []
    for server in parse_external_mcp_servers(environ):
        client = ExternalMCPClient(server)
        try:
            tools = client.list_tools()
        except Exception as exc:
            logger.warning("External MCP discovery failed for %s: %s", server.url, exc)
            continue

        for tool in tools:
            original_name = _tool_attribute(tool, "name")
            if not isinstance(original_name, str) or not original_name:
                logger.warning("External MCP server %s returned a tool without a name", server.url)
                continue
            registered_name = _registered_tool_name(server, original_name)
            if registry.get_tool(registered_name) is not None:
                logger.warning("External MCP tool name collision skipped: %s", registered_name)
                continue
            description = _tool_attribute(tool, "description", "") or ""
            parameters = _tool_attribute(tool, "inputSchema")
            if parameters is None:
                parameters = _tool_attribute(tool, "input_schema", {"type": "object"})
            if not isinstance(parameters, dict):
                parameters = {"type": "object"}

            def handler(
                args: dict[str, Any],
                context: ToolContext,
                *,
                mcp_client: ExternalMCPClient = client,
                mcp_tool_name: str = original_name,
                public_tool_name: str = registered_name,
            ) -> ToolCallResult:
                try:
                    return ToolCallResult(
                        tool_id="",
                        tool_name=public_tool_name,
                        result=mcp_client.call_tool(mcp_tool_name, args),
                    )
                except Exception as exc:
                    logger.warning("External MCP tool %s failed: %s", public_tool_name, exc)
                    return ToolCallResult(
                        tool_id="",
                        tool_name=public_tool_name,
                        result=f"External MCP tool failed: {exc}",
                        error=str(exc),
                    )

            registry.register(
                ToolDefinition(
                    name=registered_name,
                    description=description,
                    parameters=parameters,
                    handler=handler,
                    category=(
                        "external_mcp_always"
                        if server.always_enabled
                        else "external_mcp"
                    ),
                )
            )
            registered_names.append(registered_name)
            logger.info("Registered external MCP tool %s from %s", registered_name, server.url)
    if registered_names:
        import code_common.tools as tools_module

        tools_module._COMPACT_TOOL_MENU_CACHE = None
    return registered_names
