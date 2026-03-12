"""
Slash command catalog endpoint.

Serves the full slash command catalog as JSON. Frontend caches this on page load
and uses it for autocomplete filtering — no network calls during typing.

The catalog includes:
- Action commands (existing /search, /scholar, etc.)
- Enable/Disable commands (per-turn toggles for Basic Options)
- Model commands (/model_<name>)
- Agent commands (/agent_<name>)
- Preamble commands (/preamble_<name>)
- PKB commands (/create-memory, etc.)
- OpenCode commands (when enabled)
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify

from endpoints.auth import login_required
from extensions import limiter

logger = logging.getLogger(__name__)
slash_commands_bp = Blueprint("slash_commands", __name__)


def _make_short_name(canonical: str) -> str:
    """
    Generate a URL-friendly short name from a canonical model/agent/preamble name.

    Examples:
        "openai/gpt-5.4"           -> "gpt-5.4"
        "Opus 4.6"                 -> "opus_4.6"
        "PerplexitySearch"         -> "perplexity_search"
        "Gemini 3.1 Pro"           -> "gemini_3.1_pro"
        "NStepCodeAgent"           -> "nstep_code_agent"
        "Wife Prompt"              -> "wife_prompt"
        "Manager Assist Short"     -> "manager_assist_short"
    """
    name = canonical.strip()
    # Strip provider prefix (e.g., "openai/gpt-5.4" -> "gpt-5.4")
    if "/" in name:
        name = name.rsplit("/", 1)[-1]

    # Insert underscores before uppercase letters in camelCase/PascalCase
    # e.g., "PerplexitySearch" -> "Perplexity_Search"
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)

    # Replace spaces, hyphens with underscores
    name = re.sub(r"[\s\-]+", "_", name)

    return name.lower()


# ---------------------------------------------------------------------------
# Static catalog of action commands (these match existing slash commands in
# parseMessageForCheckBoxes.js)
# ---------------------------------------------------------------------------
ACTION_COMMANDS = [
    {
        "command": "search",
        "description": "Enable web search for this turn",
        "flag": "perform_web_search",
        "type": "toggle",
    },
    {
        "command": "scholar",
        "description": "Use Google Scholar",
        "flag": "googleScholar",
        "type": "toggle",
    },
    {
        "command": "search_exact",
        "description": "Search exact terms",
        "flag": "search_exact",
        "type": "toggle",
    },
    {
        "command": "image",
        "description": "Generate an image",
        "flag": "generate_image",
        "type": "toggle",
    },
    {
        "command": "draw",
        "description": "Draw/render visual",
        "flag": "draw",
        "type": "toggle",
    },
    {
        "command": "ensemble",
        "description": "Use model ensemble",
        "flag": "ensemble",
        "type": "toggle",
    },
    {
        "command": "execute",
        "description": "Execute code",
        "flag": "execute",
        "type": "toggle",
    },
    {
        "command": "more",
        "description": "Tell me more / continue",
        "flag": "tell_me_more",
        "type": "toggle",
    },
    {
        "command": "delete",
        "description": "Delete last turn",
        "flag": "delete_last_turn",
        "type": "toggle",
    },
    {
        "command": "history N",
        "description": "Set history depth (e.g. /history 5)",
        "flag": "enable_previous_messages",
        "type": "value",
    },
    {
        "command": "detailed N",
        "description": "Set detail level (e.g. /detailed 3)",
        "flag": "provide_detailed_answers",
        "type": "value",
    },
    {
        "command": "clarify",
        "description": "Request clarifications before answering",
        "flag": "clarify_request",
        "type": "toggle",
    },
    {
        "command": "title <text>",
        "description": "Set conversation title manually",
        "type": "client_action",
    },
    {
        "command": "temp <text>",
        "description": "Send message as temporary (not persisted)",
        "type": "client_action",
    },
]

# ---------------------------------------------------------------------------
# Enable/Disable commands — map to Basic Options checkboxes in the settings
# modal.  /enable_X sets flag=true, /disable_X sets flag=false for this turn.
# ---------------------------------------------------------------------------
ENABLE_DISABLE_SETTINGS = [
    # (short_name, description, checkbox_flag, setting_id)
    (
        "search",
        "web search",
        "perform_web_search",
        "settings-perform-web-search-checkbox",
    ),
    ("search_exact", "exact search", "search_exact", "settings-search-exact"),
    ("auto_clarify", "auto clarify", "auto_clarify", "settings-auto_clarify"),
    ("persist", "persist this message", "persist_or_not", "settings-persist_or_not"),
    ("ppt_answer", "PPT answer mode", "ppt_answer", "settings-ppt-answer"),
    ("memory_pad", "memory pad", "use_memory_pad", "settings-use_memory_pad"),
    (
        "context_menu",
        "LLM right-click menu",
        "enable_custom_context_menu",
        "settings-enable_custom_context_menu",
    ),
    (
        "slides_inline",
        "render slides inline",
        "render_slides_inline",
        "settings-render-slides-inline",
    ),
    ("only_slides", "only slides mode", "only_slides", "settings-only-slides"),
    (
        "render_close",
        "render close to source",
        "render_close_to_source",
        "settings-render-close-to-source",
    ),
    ("pkb", "PKB memory", "use_pkb", "settings-use_pkb"),
    ("opencode", "OpenCode", "enable_opencode", "settings-enable_opencode"),
    ("planner", "planner", "enable_planner", "settings-enable_planner"),
    ("tools", "tool use", "enable_tool_use", "settings-enable_tool_use"),
]


def _build_enable_disable_commands() -> list[dict]:
    """Build the /enable_* and /disable_* command entries."""
    commands = []
    for short, desc, flag, setting_id in ENABLE_DISABLE_SETTINGS:
        commands.append(
            {
                "command": f"enable_{short}",
                "description": f"Enable {desc}",
                "flag": flag,
                "value": True,
                "setting_id": setting_id,
                "type": "enable",
            }
        )
        commands.append(
            {
                "command": f"disable_{short}",
                "description": f"Disable {desc}",
                "flag": flag,
                "value": False,
                "setting_id": setting_id,
                "type": "disable",
            }
        )
    return commands


# ---------------------------------------------------------------------------
# Models — visible options from #settings-main-model-selector.
# Only non-hidden models are included in autocomplete.
# ---------------------------------------------------------------------------
VISIBLE_MODELS = [
    "openai/gpt-5.4",
    "Opus 4.6",
    "Sonnet 4.6",
    "Gemini 3.1 Pro",
    "Kimi K2.5",
    "Filler",
    "inception/mercury-2",
    "openai/gpt-5.2",
    "Sonnet 4.5",
    "mistralai/mistral-large-2512",
    "Haiku 4.5",
    "google/gemini-3-flash-preview",
    "deepseek-v3.1",
    "google/gemini-2.5-flash",
    "x-ai/grok-3",
    "sao10k/l3.3-euryale-70b",
    "thedrummer/anubis-pro-105b-v1",
    "nousresearch/hermes-3-llama-3.1-405b",
    "raifle/sorcererlm-8x22b",
    "perplexity/sonar-pro",
]


def _build_model_commands() -> list[dict]:
    """Build /model_<short_name> commands from the visible model list."""
    commands = []
    for canonical in VISIBLE_MODELS:
        short = _make_short_name(canonical)
        commands.append(
            {
                "command": f"model_{short}",
                "description": canonical,
                "canonical": canonical,
                "type": "model",
            }
        )
    return commands


# ---------------------------------------------------------------------------
# Agents — visible (non-hidden) options from #settings-field-selector.
# ---------------------------------------------------------------------------
VISIBLE_AGENTS = [
    "None",
    "NStepCodeAgent",
    "InstructionFollowingAgent",
    "NResponseAgent",
    "PromptWorkflowAgent",
    "ManagerAssistAgent",
    "PerplexitySearch",
    "JinaSearchAgent",
    "JinaDeepResearchAgent",
    "InterleavedWebSearchAgent",
    "WebSearch",
    "MultiSourceSearch",
    "WhatIf",
]


def _build_agent_commands() -> list[dict]:
    """Build /agent_<short_name> commands from the visible agent list."""
    commands = []
    for canonical in VISIBLE_AGENTS:
        if canonical == "None":
            commands.append(
                {
                    "command": "agent_none",
                    "description": "No agent (default)",
                    "canonical": "None",
                    "type": "agent",
                }
            )
            continue
        short = _make_short_name(canonical)
        commands.append(
            {
                "command": f"agent_{short}",
                "description": canonical,
                "canonical": canonical,
                "type": "agent",
            }
        )
    return commands


# ---------------------------------------------------------------------------
# Preambles — visible default prompts from #settings-preamble-selector.
# Custom prompts are per-user and excluded from the static catalog.
# ---------------------------------------------------------------------------
VISIBLE_PREAMBLES = [
    "No Links",
    "Wife Prompt",
    "Debug LLM",
    "Short",
    "Manager Assist",
    "Manager Assist Short",
    "Manager to Manager Framework",
    "No Code",
    "Argumentative",
    "Blackmail",
    "Diagram",
    "Easy Copy",
    "Creative",
    "Relationship",
    "Dating Maverick",
]


def _build_preamble_commands() -> list[dict]:
    """Build /preamble_<short_name> commands from the visible preamble list."""
    commands = []
    for canonical in VISIBLE_PREAMBLES:
        short = _make_short_name(canonical)
        commands.append(
            {
                "command": f"preamble_{short}",
                "description": canonical,
                "canonical": canonical,
                "type": "preamble",
            }
        )
    return commands


# ---------------------------------------------------------------------------
# PKB commands — always available.
# ---------------------------------------------------------------------------
PKB_COMMANDS = [
    {
        "command": "create-memory",
        "description": "Open modal to add a memory (with AI auto-fill)",
        "type": "client_action",
    },
    {
        "command": "create-simple-memory",
        "description": "Silently add a memory via AI (no modal)",
        "type": "client_action",
    },
    {
        "command": "create-entity",
        "description": "Open modal to create an entity",
        "type": "client_action",
    },
    {
        "command": "create-context",
        "description": "Open modal to create a context",
        "type": "client_action",
    },
    {
        "command": "pkb",
        "description": "Ask or command your personal knowledge base (NL agent)",
        "type": "client_action",
    },
    {
        "command": "memory",
        "description": "Alias for /pkb — natural language memory operations",
        "type": "client_action",
    },
]

# ---------------------------------------------------------------------------
# OpenCode commands — only available when OpenCode is enabled.
# ---------------------------------------------------------------------------
OPENCODE_COMMANDS = [
    {
        "command": "compact",
        "description": "Compress session context to save tokens",
        "type": "opencode",
    },
    {"command": "abort", "description": "Stop current generation", "type": "opencode"},
    {
        "command": "new",
        "description": "Create new OpenCode session",
        "type": "opencode",
    },
    {
        "command": "sessions",
        "description": "List all sessions for this conversation",
        "type": "opencode",
    },
    {
        "command": "fork",
        "description": "Branch conversation from current point",
        "type": "opencode",
    },
    {
        "command": "summarize",
        "description": "Summarize session to reduce context",
        "type": "opencode",
    },
    {
        "command": "status",
        "description": "Show OpenCode session status",
        "type": "opencode",
    },
    {
        "command": "diff",
        "description": "Show file changes in this session",
        "type": "opencode",
    },
    {"command": "revert", "description": "Undo last message", "type": "opencode"},
    {"command": "mcp", "description": "Show MCP server status", "type": "opencode"},
    {"command": "models", "description": "Show available models", "type": "opencode"},
    {"command": "help", "description": "Show available commands", "type": "opencode"},
]


def _build_catalog() -> dict:
    """Assemble the full slash command catalog."""
    return {
        "categories": [
            {
                "name": "Actions",
                "icon": "bi-lightning",
                "commands": ACTION_COMMANDS,
            },
            {
                "name": "Enable / Disable",
                "icon": "bi-toggles",
                "commands": _build_enable_disable_commands(),
            },
            {
                "name": "Models",
                "icon": "bi-cpu",
                "commands": _build_model_commands(),
            },
            {
                "name": "Agents",
                "icon": "bi-robot",
                "commands": _build_agent_commands(),
            },
            {
                "name": "Preambles",
                "icon": "bi-file-text",
                "commands": _build_preamble_commands(),
            },
            {
                "name": "PKB",
                "icon": "bi-brain",
                "badge": "pkb",
                "commands": PKB_COMMANDS,
            },
            {
                "name": "OpenCode",
                "icon": "bi-terminal",
                "badge": "opencode",
                "requires": "enable_opencode",
                "commands": OPENCODE_COMMANDS,
            },
        ]
    }


@slash_commands_bp.route("/api/slash_commands", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def get_slash_commands():
    """
    Return the full slash command catalog.

    Called once on page load by the frontend. The result is cached client-side
    and used for autocomplete filtering with no further network calls.

    Returns
    -------
    flask.Response
        JSON with ``categories`` list, each containing ``name``, ``icon``,
        optional ``badge``/``requires``, and a ``commands`` list.
    """
    try:
        catalog = _build_catalog()
        return jsonify(catalog)
    except Exception:
        logger.exception("Failed to build slash command catalog")
        return jsonify({"categories": []}), 500
