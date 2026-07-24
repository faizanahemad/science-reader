"""Tests for environment-configured external MCP tools in native chat."""

from __future__ import annotations

from code_common.tools import ToolContext, ToolRegistry
from code_common.external_mcp import (
    ExternalMCPClient,
    discover_and_register_external_mcp_tools,
    parse_external_mcp_servers,
)


def test_parse_external_mcp_servers_pairs_urls_tokens_and_headers():
    servers = parse_external_mcp_servers(
        {
            "MCP_URLS": "http://127.0.0.1:8765/mcp, https://example.test/mcp",
            "MCP_AUTH_TOKENS": "local-token,",
            "MCP_HEADERS_JSON": (
                '{"*":{"X-Shared":"research"},'
                '"https://example.test/mcp":{"X-API-Key":"remote-key"}}'
            ),
            "MCP_TIMEOUT_SECONDS": "45",
        }
    )

    assert [(server.name, server.url) for server in servers] == [
        ("external_mcp_1", "http://127.0.0.1:8765/mcp"),
        ("external_mcp_2", "https://example.test/mcp"),
    ]
    assert servers[0].headers == {
        "X-Shared": "research",
        "Authorization": "Bearer local-token",
    }
    assert servers[1].headers == {
        "X-Shared": "research",
        "X-API-Key": "remote-key",
    }
    assert [server.timeout_seconds for server in servers] == [45, 45]


def test_parse_external_mcp_servers_merges_always_urls_and_marks_them_required():
    servers = parse_external_mcp_servers(
        {
            "MCP_URLS": "http://standard.test/mcp,http://shared.test/mcp",
            "MCP_ENABLE_ALWAYS_URLS": "http://shared.test/mcp,http://always.test/mcp",
        }
    )

    assert [(server.url, server.always_enabled) for server in servers] == [
        ("http://standard.test/mcp", False),
        ("http://shared.test/mcp", True),
        ("http://always.test/mcp", True),
    ]


def test_discovery_registers_always_url_tools_in_dedicated_category(monkeypatch):
    monkeypatch.setattr(
        ExternalMCPClient,
        "list_tools",
        lambda self: [{"name": "always-tool", "inputSchema": {"type": "object"}}],
    )
    registry = ToolRegistry()

    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={"MCP_ENABLE_ALWAYS_URLS": "http://always.test/mcp"},
    )

    assert len(registered) == 1
    assert registry.get_tool(registered[0]).category == "external_mcp_always"


def test_always_enabled_tools_bypass_manual_selection(monkeypatch):
    import Conversation as conversation_module

    registry = ToolRegistry()
    monkeypatch.setattr(
        ExternalMCPClient,
        "list_tools",
        lambda self: [{"name": "always-tool", "inputSchema": {"type": "object"}}],
    )
    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={"MCP_ENABLE_ALWAYS_URLS": "http://always.test/mcp"},
    )
    monkeypatch.setattr(conversation_module, "TOOL_REGISTRY", registry)
    monkeypatch.setattr(conversation_module, "TOOLS_AVAILABLE", True)

    conversation = conversation_module.Conversation.__new__(conversation_module.Conversation)
    conversation.list_artefacts = lambda: []

    tools = conversation._get_enabled_tools(
        {"tool_mode": "manual", "enabled_tools": []}
    )

    assert [tool["function"]["name"] for tool in tools] == registered
    assert conversation._get_enabled_tools({"tool_mode": "none"}) is None


def test_external_mcp_catalog_exposes_manual_selector_metadata(monkeypatch):
    from endpoints.conversations import _external_mcp_tool_catalog

    registry = ToolRegistry()
    monkeypatch.setattr(
        ExternalMCPClient,
        "list_tools",
        lambda self: [
            {
                "name": "lookup-record",
                "description": "Look up a record.",
                "inputSchema": {"type": "object"},
            }
        ],
    )
    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={"MCP_URLS": "http://external.test/mcp"},
    )
    monkeypatch.setattr("code_common.tools.TOOL_REGISTRY", registry)

    assert _external_mcp_tool_catalog() == [
        {
            "name": registered[0],
            "description": "Look up a record.",
            "category": "external_mcp",
        }
    ]


def test_parse_external_mcp_servers_rejects_invalid_headers_json():
    import pytest

    with pytest.raises(ValueError, match="MCP_HEADERS_JSON"):
        parse_external_mcp_servers(
            {
                "MCP_URLS": "http://127.0.0.1:8765/mcp",
                "MCP_HEADERS_JSON": "not-json",
            }
        )


def test_discovery_registers_external_schema_and_forwards_model_call(monkeypatch):
    def fake_list_tools(self):
        return [
            {
                "name": "lookup-record",
                "description": "Look up a record in the external service.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"record_id": {"type": "string"}},
                    "required": ["record_id"],
                },
            }
        ]

    captured = {}

    def fake_call_tool(self, tool_name, arguments):
        captured["url"] = self.server.url
        captured["headers"] = self.server.headers
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return "external record result"

    monkeypatch.setattr(ExternalMCPClient, "list_tools", fake_list_tools)
    monkeypatch.setattr(ExternalMCPClient, "call_tool", fake_call_tool)
    registry = ToolRegistry()

    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={
            "MCP_URLS": "http://127.0.0.1:8765/mcp",
            "MCP_AUTH_TOKENS": "secret-token",
        },
    )

    assert len(registered) == 1
    assert registered[0].startswith("external_mcp_1_lookup_record_")
    schema = registry.get_openai_tools_param(registered)
    assert schema[0]["function"]["name"] == registered[0]
    assert schema[0]["function"]["parameters"]["required"] == ["record_id"]

    result = registry.execute(
        registered[0],
        {"record_id": "record-123"},
        ToolContext(conversation_id="conversation-1"),
    )

    assert result.result == "external record result"
    assert result.error is None
    assert captured == {
        "url": "http://127.0.0.1:8765/mcp",
        "headers": {"Authorization": "Bearer secret-token"},
        "tool_name": "lookup-record",
        "arguments": {"record_id": "record-123"},
    }


def test_discovery_failure_does_not_prevent_other_servers_from_registering(monkeypatch):
    def fake_list_tools(self):
        if self.server.url == "http://unavailable.test/mcp":
            raise RuntimeError("connection refused")
        return [{"name": "healthy-tool", "inputSchema": {"type": "object"}}]

    monkeypatch.setattr(ExternalMCPClient, "list_tools", fake_list_tools)
    registry = ToolRegistry()

    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={
            "MCP_URLS": "http://unavailable.test/mcp,http://healthy.test/mcp",
        },
    )

    assert len(registered) == 1
    assert registered[0].startswith("external_mcp_2_healthy_tool_")
    assert registry.get_tool(registered[0]) is not None


def test_discovery_names_colliding_and_long_remote_tools_uniquely(monkeypatch):
    monkeypatch.setattr(
        ExternalMCPClient,
        "list_tools",
        lambda self: [
            {"name": "foo-bar", "inputSchema": {"type": "object"}},
            {"name": "foo_bar", "inputSchema": {"type": "object"}},
            {"name": "x" * 200, "inputSchema": {"type": "object"}},
        ],
    )
    registry = ToolRegistry()

    registered = discover_and_register_external_mcp_tools(
        registry=registry,
        environ={"MCP_URLS": "http://127.0.0.1:8765/mcp"},
    )

    assert len(registered) == len(set(registered)) == 3
    assert all(len(name) <= 64 for name in registered)