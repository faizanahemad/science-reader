# Slash Command System

## Overview

The chat application supports `/` slash commands as per-turn overrides and actions. Commands are typed in the message input and parsed before sending. An autocomplete dropdown appears when the user types `/`, providing fuzzy-matched suggestions.

**Design principle**: `@` for information elements (PKB claims, docs, cross-conversation refs), `/` for functionality (actions, toggles, model/agent selection).

## Architecture

### Data Flow

1. **Page load**: Frontend fetches `GET /api/slash_commands` → caches the full command catalog in `window._slashCommandCatalog`
2. **Typing**: User types `/` → autocomplete filters cached catalog using fuzzy matching → shows 5 items max with scroll
3. **Send**: `parseMessageForCheckBoxes()` extracts slash commands from the first line → sets flags on the result object
4. **Merge**: `mergeOptions()` merges slash flags with modal settings (slash takes precedence) → resolves `/model_*`, `/agent_*`, `/preamble_*` short names to canonical names using the cached catalog
5. **Backend**: `Conversation.reply()` reads flags from `checkboxes` dict — same keys as the settings modal

### Key Files

| File | Role |
|---|---|
| `endpoints/slash_commands.py` | Backend catalog endpoint (`GET /api/slash_commands`) |
| `endpoints/__init__.py` | Blueprint registration |
| `interface/parseMessageForCheckBoxes.js` | Slash command parsing + `mergeOptions()` + name resolution via `_resolveSlashCatalogName()` |
| `interface/common-chat.js` | Slash autocomplete IIFE (fuzzy match, dropdown UI, catalog fetch/cache) |

## Command Categories

### Action Commands (existing)

These were the original slash commands. They set boolean flags or capture numeric arguments.

| Command | Flag | Type |
|---|---|---|
| `/search` | `perform_web_search` | toggle |
| `/scholar` | `googleScholar` | toggle |
| `/search_exact` | `search_exact` | toggle |
| `/image` | `generate_image` | toggle |
| `/draw` | `draw` | toggle |
| `/ensemble` | `ensemble` | toggle |
| `/execute` | `execute` | toggle |
| `/more` | `tell_me_more` | toggle |
| `/delete` | `delete_last_turn` | toggle |
| `/clarify` | `clarify_request` | toggle (works on any line) |
| `/history N` | `enable_previous_messages` | value |
| `/detailed N` | `provide_detailed_answers` | value |
| `/title <text>` | N/A (backend-only) | Sets conversation title manually. Alias: `/set_title`. Handled in `Conversation.reply()`, not parsed by frontend. |
| `/temp <text>` | N/A (backend-only) | Sends message as temporary (not persisted). Alias: `/temporary`. Handled in `Conversation.reply()`. |

### Enable/Disable Commands

Per-turn overrides for Basic Options checkboxes. `/enable_X` sets the flag to `true`, `/disable_X` sets it to `false`.

| Command | Flag | Settings Modal Element |
|---|---|---|
| `/enable_search` / `/disable_search` | `perform_web_search` | `settings-perform-web-search-checkbox` |
| `/enable_search_exact` / `/disable_search_exact` | `search_exact` | `settings-search-exact` |
| `/enable_auto_clarify` / `/disable_auto_clarify` | `auto_clarify` | `settings-auto_clarify` |
| `/enable_persist` / `/disable_persist` | `persist_or_not` | `settings-persist_or_not` |
| `/enable_ppt_answer` / `/disable_ppt_answer` | `ppt_answer` | `settings-ppt-answer` |
| `/enable_memory_pad` / `/disable_memory_pad` | `use_memory_pad` | `settings-use_memory_pad` |
| `/enable_context_menu` / `/disable_context_menu` | `enable_custom_context_menu` | `settings-enable_custom_context_menu` |
| `/enable_slides_inline` / `/disable_slides_inline` | `render_slides_inline` | `settings-render-slides-inline` |
| `/enable_only_slides` / `/disable_only_slides` | `only_slides` | `settings-only-slides` |
| `/enable_render_close` / `/disable_render_close` | `render_close_to_source` | `settings-render-close-to-source` |
| `/enable_pkb` / `/disable_pkb` | `use_pkb` | `settings-use_pkb` |
| `/enable_opencode` / `/disable_opencode` | `enable_opencode` | `settings-enable_opencode` |
| `/enable_planner` / `/disable_planner` | `enable_planner` | `settings-enable_planner` |
| `/enable_tools` / `/disable_tools` | `enable_tool_use` | `settings-enable_tool_use` |

### Model Commands

`/model_<short_name>` selects a model for this turn only. **Replaces** the modal selection (not additive).

The short name is resolved to a canonical model name via the cached catalog. Examples:
- `/model_gpt-5.4` → `openai/gpt-5.4`
- `/model_opus_4.6` → `Opus 4.6`
- `/model_sonnet_4.6` → `Sonnet 4.6`

Sets `checkboxes.main_model = [canonical_name]` (array for multi-select compatibility).

### Agent Commands

`/agent_<short_name>` selects an agent for this turn only. **Replaces** the modal selection.

Examples:
- `/agent_perplexity_search` → `PerplexitySearch`
- `/agent_web_search` → `WebSearch`
- `/agent_none` → `None` (no agent)

Sets `checkboxes.field = canonical_name`.

### Preamble Commands

`/preamble_<short_name>` adds a preamble for this turn. **Additive** — stacks with existing preamble selection from the modal.

Examples:
- `/preamble_short` → `Short`
- `/preamble_diagram` → `Diagram`
- `/preamble_creative` → `Creative`

Appends to `checkboxes.preamble_options` array.

### PKB Commands

Client-side intercepted before sending to server (except `/pkb` and `/memory` which route through `Conversation.reply` to the `PKBNLConversationAgent`).

| Command | Action |
|---|---|
| `/create-memory <text>` | Open memory creation modal (with AI auto-fill from text) |
| `/create-simple-memory <text>` | Silently create memory via AI (no modal) |
| `/create-entity <name>` | Open entity creation modal |
| `/create-context <name>` | Open context creation modal |
| `/pkb <text>` | Route to PKB NL agent for natural language memory operations (add, search, delete, edit claims). Bypasses normal conversation LLM — uses short history + summary for context. Alias: `/memory`. |
| `/memory <text>` | Alias for `/pkb <text>` |

### OpenCode Commands

Only available when OpenCode is enabled. Forwarded to OpenCode session.

| Command | Action |
|---|---|
| `/compact` | Compress session context |
| `/abort` | Stop current generation |
| `/new` | Create new session |
| `/sessions` | List sessions |
| `/fork` | Branch conversation |
| `/summarize` | Summarize session |
| `/status` | Show session status |
| `/diff` | Show file changes |
| `/revert` | Undo last message |
| `/mcp` | Show MCP server status |
| `/models` | Show available models |
| `/help` | Show available commands |

## Autocomplete

### Behavior

- **Trigger**: Typing `/` (0-character minimum — shows all commands immediately)
- **Fuzzy matching**: Sequential character matching with scoring (ported from file-browser-manager.js `_fuzzyMatch`)
- **Display**: 5 items max visible with scroll, grouped by category with thin separator headers
- **Selection**: First item pre-selected. Arrow keys navigate, Enter/Tab to apply, Escape to dismiss
- **Match highlighting**: Matched characters shown in bold blue in the command name
- **Data source**: Cached from `GET /api/slash_commands` on page load — no network calls during typing

### Fuzzy Matching Scoring

1. **Exact substring match** (best): `score = nLen * bonus + (1 / (subIdx + 1))`
   - Start of string: bonus = 2.0
   - After word boundary (`/\-_. `): bonus = 1.8
   - Mid-string: bonus = 1.5
2. **Sequential character match**: consecutive +1.0, word boundary +0.8, mid-word +0.3, gap penalty -0.005/char
3. **Length penalty**: `-(hLen - nLen) * 0.01`

### Category Order

1. Actions
2. Enable / Disable
3. Models
4. Agents
5. Preambles
6. PKB
7. OpenCode (only when enabled)

## Backend Endpoint

### `GET /api/slash_commands`

Returns the full command catalog as JSON. Called once on page load.

**Rate limit**: 10 per minute

**Response format**:
```json
{
  "categories": [
    {
      "name": "Actions",
      "icon": "bi-lightning",
      "commands": [
        {
          "command": "search",
          "description": "Enable web search for this turn",
          "flag": "perform_web_search",
          "type": "toggle"
        }
      ]
    },
    {
      "name": "Models",
      "icon": "bi-cpu",
      "commands": [
        {
          "command": "model_gpt-5.4",
          "description": "openai/gpt-5.4",
          "canonical": "openai/gpt-5.4",
          "type": "model"
        }
      ]
    }
  ]
}
```

Category fields:
- `name`: Category display name
- `icon`: Bootstrap icon class
- `badge` (optional): `"pkb"` or `"opencode"` — shown as colored badge in autocomplete
- `requires` (optional): Setting that must be enabled (e.g., `"enable_opencode"`)
- `commands`: Array of command objects

Command fields:
- `command`: The slash command text (without leading `/`)
- `description`: Human-readable description
- `type`: `"toggle"`, `"value"`, `"enable"`, `"disable"`, `"model"`, `"agent"`, `"preamble"`, `"client_action"`, `"opencode"`
- `canonical` (model/agent/preamble only): The canonical name used by the backend
- `flag` (toggle/enable/disable only): The checkbox flag name
- `value` (enable/disable only): `true` or `false`

## @ Reference Prefixes

The `@` references support these prefixes for PKB claim lookup:
- `@memory:claim_id` — standard prefix
- `@mem:claim_id` — short prefix
- `@pkb:claim_id` — legacy alias (added alongside memory/mem)
- `@friendly_id` — friendly ID lookup (3+ chars, no prefix needed)

## Adding New Commands

### Adding a new toggle command

1. Add `processCommand()` call in `parseMessageForCheckBoxes.js` (after existing commands)
2. Add entry to `ACTION_COMMANDS` in `endpoints/slash_commands.py`
3. Verify backend reads the flag from `checkboxes` in `Conversation.reply()`

### Adding a new enable/disable pair

1. Add to `ENABLE_DISABLE_SETTINGS` list in `endpoints/slash_commands.py`
2. Add `processCommand()` calls (enable + disable) in `parseMessageForCheckBoxes.js`
3. Verify backend reads the flag

### Adding a new model/agent/preamble

1. Add to `VISIBLE_MODELS` / `VISIBLE_AGENTS` / `VISIBLE_PREAMBLES` in `endpoints/slash_commands.py`
2. Corresponding `<option>` should exist in `interface.html` settings modal
3. No parsing changes needed — the `/model_*`, `/agent_*`, `/preamble_*` patterns are generic

### Updating after modal changes

When adding/removing options in the settings modal (`interface.html`):
1. Update the corresponding list in `endpoints/slash_commands.py` (`VISIBLE_MODELS`, `VISIBLE_AGENTS`, `VISIBLE_PREAMBLES`, or `ENABLE_DISABLE_SETTINGS`)
2. The frontend autocomplete will pick up changes on next page reload (catalog is fetched fresh)

## Autocomplete Implementation Details

### Frontend Architecture (IIFE v2)

The autocomplete is implemented as a 414-line IIFE in `interface/common-chat.js` (approximately lines 4090-4504). It replaces the original 302-line IIFE that only supported PKB and OpenCode commands with a 3-character minimum trigger.

**Initialization (page load)**:
1. `GET /api/slash_commands` fetched via AJAX
2. Response cached in `window._slashCommandCatalog`
3. Commands flattened into a searchable array with category metadata
4. OpenCode commands filtered by `requires: "enable_opencode"` setting

**Input handling**:
1. `keyup` event on `#user-message` textarea checks if cursor is preceded by `/` with optional characters
2. If `/` found at start of line (or after whitespace), extracts the query string after `/`
3. Query is passed to `_fuzzyMatch()` against all cached commands
4. Top 5 results shown in dropdown (with scroll for overflow)

### Fuzzy Matching Algorithm

Ported from `file-browser-manager.js` `_fuzzyMatch()` (lines 827-884). Two-pass algorithm:

**Pass 1 — Exact substring match** (preferred):
```
score = needleLength * bonus + (1 / (substringIndex + 1))
```
- `bonus = 2.0` if match starts at index 0 (start of string)
- `bonus = 1.8` if match starts after a word boundary (`/`, `-`, `_`, `.`, ` `)
- `bonus = 1.5` for mid-string matches
- Earlier matches score higher via the `1 / (idx + 1)` term

**Pass 2 — Sequential character match** (fallback):
- Characters matched greedily left-to-right through the haystack
- Scoring per matched character:
  - `+1.0` if consecutive with previous match
  - `+0.8` if at a word boundary
  - `+0.3` otherwise (mid-word)
- Gap penalty: `-0.005` per skipped character
- Length penalty: `-(haystackLength - needleLength) * 0.01`

**Match positions** are tracked and returned for UI highlighting.

### Dropdown Rendering

- Positioned absolutely below the textarea cursor position
- Category headers shown as thin grey separator lines (not selectable)
- Each command item shows:
  - Command name with matched characters in `<b>` bold blue
  - Description text in grey
  - Optional badge ("pkb" in teal `#20c997`, "opencode" in purple) for non-standard categories
- First item pre-selected with `.active` class
- Arrow Up/Down cycles through items (wraps at boundaries)
- Enter/Tab inserts the selected command (replacing the typed `/...` prefix)
- Escape or blur dismisses the dropdown
- Mouse click on an item also selects it

### Catalog Cache Lifecycle

1. **Fetch**: On page load, `$.get('/api/slash_commands')` stores result in `window._slashCommandCatalog`
2. **Filter**: OpenCode commands are excluded at render time if `enable_opencode` setting is off
3. **Invalidation**: Cache lasts for the page session. A page reload fetches fresh data (models/agents/preambles may have changed)
4. **No expiry timer**: Since the catalog is small (<5KB) and only fetched once, no TTL or background refresh is used

### Backend Catalog Generation (`endpoints/slash_commands.py`)

The endpoint builds the catalog from 5 source lists:

1. `ACTION_COMMANDS` — hardcoded list of action toggle/value commands
2. `ENABLE_DISABLE_SETTINGS` — list of `(suffix, flag_key, dom_id)` tuples defining all enable/disable pairs
3. `VISIBLE_MODELS` — list of `(short_name, canonical_name)` for model selection commands
4. `VISIBLE_AGENTS` — list of `(short_name, canonical_name)` for agent selection commands
5. `VISIBLE_PREAMBLES` — list of `(short_name, canonical_name)` for preamble selection commands

Each list maps to a category in the response JSON. The endpoint is rate-limited at 10/min and requires `@login_required`.

### Name Resolution Flow

When `parseMessageForCheckBoxes()` encounters `/model_X`, `/agent_X`, or `/preamble_X`:

1. Extracts the short name (everything after `model_`, `agent_`, or `preamble_`)
2. Calls `_resolveSlashCatalogName(shortName, commandType)` which:
   a. Reads `window._slashCommandCatalog`
   b. Finds the matching category (`Models`, `Agents`, or `Preambles`)
   c. Searches for a command where `command.command` ends with `_shortName`
   d. Returns `command.canonical` if found, or the raw short name as fallback
3. The resolved canonical name is set on the appropriate flag (`main_model`, `field`, or `preamble_options`)

### Merge Precedence (`mergeOptions()`)

Called in `sendMessageCallback()` to combine slash command flags with modal settings:

```
result = parseMessageForCheckBoxes(messageText)
options = getOptions('chat-options', 'assistant')  // from modal
merged = mergeOptions(result, options)              // slash wins
```

Rules:
- **Boolean flags** (`perform_web_search`, `use_pkb`, etc.): slash value overrides modal value
- **Model** (`main_model`): slash replaces entirely (array with single canonical name)
- **Agent** (`field`): slash replaces entirely
- **Preamble** (`preamble_options`): slash appends to modal selection (additive merge)
- **Unset flags**: modal value preserved (slash only overrides what it explicitly sets)
