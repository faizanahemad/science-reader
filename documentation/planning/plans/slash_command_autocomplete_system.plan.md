# Slash Command Autocomplete System — Implementation Plan

**Status:** DONE (June 2026)

**Status**: Ready for Implementation  
**Created**: 2026-03-08  
**Oracle Reviewed**: Yes (architecture approved)

## Overview

Overhaul the slash command system: add new command categories (`/enable_*`, `/disable_*`, `/model_*`, `/agent_*`, `/preamble_*`), build a backend catalog endpoint cached on page load, and replace the current 3-char-minimum prefix autocomplete with a 0-char fuzzy-matching dropdown showing 5 items at a time with scroll.

### Design Principles

- `@` for information elements, `/` for functionality
- Both `/enable_search` AND `/search` work (aliases, not conflicts)
- Backend catalog cached once on page load — no network calls during typing
- Fuzzy matching reuses existing `_fuzzyMatch()` from `file-browser-manager.js`
- New slash commands are **per-turn overrides** — they don't persist to the settings modal
- Reuse existing `checkboxes` keys (`main_model`, `field`, `preamble_options`) — no new backend plumbing

---

## Task Breakdown

### Task 1: Add `@pkb` as legacy prefix alias

**File**: `interface/parseMessageForCheckBoxes.js`  
**Line**: 413  
**Change**: `/@(?:memory|mem):` → `/@(?:memory|mem|pkb):`  
**Also**: Line 461, skip filter: `/^(?:memory|mem)$/i` → `/^(?:memory|mem|pkb)$/i`  
**Also**: Update test cases at lines 489+ to include `@pkb:claim_id` tests  
**Effort**: Trivial (3 line changes + tests)

---

### Task 2: Create backend slash command catalog endpoint

**New file**: `endpoints/slash_commands.py`  
**New endpoint**: `GET /api/slash_commands`  
**Register in**: `server.py` (import + blueprint registration)

Returns JSON with all commands organized by category. The endpoint reads dynamic values from the same sources the HTML selectors use (model list, agent list, preamble list).

```python
# Static catalog structure
SLASH_COMMAND_CATALOG = {
    "categories": [
        {
            "name": "Actions",
            "icon": "bi-lightning",
            "commands": [
                {"command": "search", "description": "Enable web search for this turn", "flag": "perform_web_search", "type": "toggle"},
                {"command": "scholar", "description": "Use Google Scholar", "flag": "googleScholar", "type": "toggle"},
                {"command": "search_exact", "description": "Search exact terms", "flag": "search_exact", "type": "toggle"},
                {"command": "image", "description": "Generate an image", "flag": "generate_image", "type": "toggle"},
                {"command": "draw", "description": "Draw/render visual", "flag": "draw", "type": "toggle"},
                {"command": "ensemble", "description": "Use model ensemble", "flag": "ensemble", "type": "toggle"},
                {"command": "execute", "description": "Execute code", "flag": "execute", "type": "toggle"},
                {"command": "more", "description": "Tell me more / continue", "flag": "tell_me_more", "type": "toggle"},
                {"command": "delete", "description": "Delete last turn", "flag": "delete_last_turn", "type": "toggle"},
                {"command": "history N", "description": "Set history depth (e.g. /history 5)", "flag": "enable_previous_messages", "type": "value"},
                {"command": "detailed N", "description": "Set detail level (e.g. /detailed 3)", "flag": "provide_detailed_answers", "type": "value"},
                {"command": "clarify", "description": "Request clarifications before answering", "flag": "clarify_request", "type": "toggle"},
            ]
        },
        {
            "name": "Enable/Disable",
            "icon": "bi-toggles",
            "commands": [
                # These map to the Basic Options checkboxes in settings modal.
                # /enable_X sets the flag to true for this turn. /disable_X sets it to false.
                # The "setting_id" is the HTML element ID for reference.
                {"command": "enable_search", "description": "Enable web search", "flag": "perform_web_search", "value": true, "setting_id": "settings-perform-web-search-checkbox"},
                {"command": "disable_search", "description": "Disable web search", "flag": "perform_web_search", "value": false, "setting_id": "settings-perform-web-search-checkbox"},
                {"command": "enable_pkb", "description": "Enable PKB memory", "flag": "use_pkb", "value": true, "setting_id": "settings-use_pkb"},
                {"command": "disable_pkb", "description": "Disable PKB memory", "flag": "use_pkb", "value": false, "setting_id": "settings-use_pkb"},
                {"command": "enable_memory_pad", "description": "Enable memory pad", "flag": "use_memory_pad", "value": true, "setting_id": "settings-use_memory_pad"},
                {"command": "disable_memory_pad", "description": "Disable memory pad", "flag": "use_memory_pad", "value": false, "setting_id": "settings-use_memory_pad"},
                {"command": "enable_tools", "description": "Enable tool use", "flag": "enable_tool_use", "value": true, "setting_id": "settings-enable_tool_use"},
                {"command": "disable_tools", "description": "Disable tool use", "flag": "enable_tool_use", "value": false, "setting_id": "settings-enable_tool_use"},
                {"command": "enable_opencode", "description": "Enable OpenCode", "flag": "enable_opencode", "value": true, "setting_id": "settings-enable_opencode"},
                {"command": "disable_opencode", "description": "Disable OpenCode", "flag": "enable_opencode", "value": false, "setting_id": "settings-enable_opencode"},
                {"command": "enable_planner", "description": "Enable planner", "flag": "enable_planner", "value": true, "setting_id": "settings-enable_planner"},
                {"command": "disable_planner", "description": "Disable planner", "flag": "enable_planner", "value": false, "setting_id": "settings-enable_planner"},
                {"command": "enable_persist", "description": "Persist this message", "flag": "persist_or_not", "value": true, "setting_id": "settings-persist_or_not"},
                {"command": "disable_persist", "description": "Don't persist this message", "flag": "persist_or_not", "value": false, "setting_id": "settings-persist_or_not"},
                {"command": "enable_auto_clarify", "description": "Enable auto clarify", "flag": "auto_clarify", "value": true, "setting_id": "settings-auto_clarify"},
                {"command": "disable_auto_clarify", "description": "Disable auto clarify", "flag": "auto_clarify", "value": false, "setting_id": "settings-auto_clarify"},
            ]
        },
        {
            "name": "Models",
            "icon": "bi-cpu",
            "commands": []  # Populated dynamically from model list
            # Each entry: {"command": "model_opus", "description": "Opus 4.6", "canonical": "Opus 4.6", "type": "model"}
            # Friendly short name → canonical model name as it appears in the <option> text
        },
        {
            "name": "Agents",
            "icon": "bi-robot",
            "commands": []  # Populated dynamically from agent list
            # Each: {"command": "agent_perplexity", "description": "PerplexitySearch agent", "canonical": "PerplexitySearch", "type": "agent"}
        },
        {
            "name": "Preambles",
            "icon": "bi-file-text",
            "commands": []  # Populated dynamically from preamble list
            # Each: {"command": "preamble_short", "description": "Short preamble", "canonical": "Short", "type": "preamble"}
        },
        {
            "name": "PKB",
            "icon": "bi-brain",
            "badge": "pkb",
            "commands": [
                {"command": "create-memory", "description": "Open modal to add a memory (with AI auto-fill)", "type": "client_action"},
                {"command": "create-simple-memory", "description": "Silently add a memory via AI (no modal)", "type": "client_action"},
                {"command": "create-entity", "description": "Open modal to create an entity", "type": "client_action"},
                {"command": "create-context", "description": "Open modal to create a context", "type": "client_action"},
            ]
        },
        {
            "name": "OpenCode",
            "icon": "bi-terminal",
            "badge": "opencode",
            "requires": "enable_opencode",
            "commands": [
                {"command": "compact", "description": "Compress session context", "type": "opencode"},
                {"command": "abort", "description": "Stop current generation", "type": "opencode"},
                {"command": "new", "description": "Create new OpenCode session", "type": "opencode"},
                {"command": "sessions", "description": "List all sessions", "type": "opencode"},
                {"command": "fork", "description": "Branch conversation", "type": "opencode"},
                {"command": "summarize", "description": "Summarize session", "type": "opencode"},
                {"command": "status", "description": "Show session status", "type": "opencode"},
                {"command": "diff", "description": "Show file changes", "type": "opencode"},
                {"command": "revert", "description": "Undo last message", "type": "opencode"},
                {"command": "mcp", "description": "Show MCP server status", "type": "opencode"},
                {"command": "models", "description": "Show available models", "type": "opencode"},
                {"command": "help", "description": "Show available commands", "type": "opencode"},
            ]
        }
    ]
}
```

**Dynamic population**: The endpoint reads models from the same config the HTML `<select>` uses. Agent list and preamble list are similarly sourced from the backend config (same data that populates the selectors). A helper function generates friendly short names from canonical names (e.g., "Opus 4.6" → "opus_4.6", "PerplexitySearch" → "perplexity_search").

**Implementation notes**:
- Model list source: Look at how `interface.html` model `<option>` values are generated or maintained. If hardcoded in HTML, mirror in Python. If dynamic, use the same source.
- Agent list: Same approach — mirror the `<option>` values from `#settings-field-selector`.
- Preamble list: Mirror from `#settings-preamble-selector` default prompts. Custom prompts are user-specific and can be excluded from autocomplete or fetched separately.
- Rate limit: Light rate limiting (e.g., 10/min) since it's called once per page load.

---

### Task 3: Frontend — Fetch and cache slash command catalog on page load

**File**: `interface/common-chat.js` (inside the slash autocomplete IIFE)

On `$(document).ready`, after the existing `setTimeout(initAutocomplete, 600)`:
1. Call `GET /api/slash_commands`
2. Store result in a module-level variable `cachedCatalog`
3. Build a flat array of all commands (merging categories) for filtering
4. If OpenCode is disabled, filter out `requires: "enable_opencode"` commands
5. Re-check OpenCode state on each autocomplete trigger (the checkbox may change)

```javascript
var cachedCatalog = null;
var flatCommands = [];

function fetchAndCacheCatalog() {
    $.get('/api/slash_commands', function(data) {
        cachedCatalog = data;
        rebuildFlatCommands();
    }).fail(function() {
        console.warn('Failed to fetch slash command catalog, using fallback');
        // Fallback to existing hardcoded PKB_COMMANDS + OPENCODE_COMMANDS
        cachedCatalog = null;
    });
}

function rebuildFlatCommands() {
    flatCommands = [];
    if (!cachedCatalog || !cachedCatalog.categories) return;
    cachedCatalog.categories.forEach(function(cat) {
        cat.commands.forEach(function(cmd) {
            flatCommands.push({
                ...cmd,
                category: cat.name,
                categoryIcon: cat.icon,
                badge: cat.badge || null,
                requires: cat.requires || null
            });
        });
    });
}
```

---

### Task 4: Frontend — Replace slash autocomplete with fuzzy matching

**File**: `interface/common-chat.js` (slash autocomplete IIFE, lines 4097-4392)

Major changes:
1. **Copy `_fuzzyMatch()`** from `file-browser-manager.js` (lines 827-884) into the IIFE (or extract to a shared utility — but keeping it in the IIFE is simpler and matches existing patterns)
2. **Drop 3-char minimum** to 0-char (show all commands when user types just `/`)
3. **Replace `indexOf` prefix matching** with fuzzy matching using `_fuzzyMatch()`
4. **Sort results by fuzzy score** (descending)
5. **Show max 5 items** with scroll for more (change `max-height` accordingly)
6. **Pre-select first item** (already done — `selectedIndex: 0`)
7. **Filter by OpenCode state** — skip `requires: "enable_opencode"` commands when OpenCode is off
8. **Render with category headers** — group by category, show thin category separator between groups
9. **Highlight matched characters** in the command name (use `match.indexes` from fuzzy match)

**handleSlashInput changes (line 4195+)**:

```javascript
function handleSlashInput(textarea) {
    // ... existing checks (slash position, whitespace, etc.) ...
    
    // CHANGE: Remove the 3-char minimum (lines 4231-4235)
    // if (prefix.length < 3) { ... }  ← DELETE THIS
    
    var lowerPrefix = prefix.toLowerCase();
    var opencodeEnabled = $('#settings-enable_opencode').is(':checked');
    var source = flatCommands.length > 0 ? flatCommands : buildFallbackCommands();
    var filtered = [];
    
    if (prefix.length === 0) {
        // Show all commands (grouped by category)
        source.forEach(function(cmd) {
            if (cmd.requires === 'enable_opencode' && !opencodeEnabled) return;
            filtered.push({ ...cmd, score: 0, matchIndexes: [] });
        });
    } else {
        // Fuzzy match
        source.forEach(function(cmd) {
            if (cmd.requires === 'enable_opencode' && !opencodeEnabled) return;
            var match = _fuzzyMatch(lowerPrefix, cmd.command);
            if (match) {
                filtered.push({ ...cmd, score: match.score, matchIndexes: match.indexes });
            }
        });
        // Sort by score descending
        filtered.sort(function(a, b) { return b.score - a.score; });
    }
    
    slashState.results = filtered;
    slashState.selectedIndex = 0;
    // ...
}
```

**Dropdown rendering changes (showSlashAutocomplete)**:
- Max 5 visible items. Set `max-height` to ~5 * item_height (approx 200px).
- Group items by category with thin separator headers.
- Highlight matched characters in command name using `matchIndexes`.
- Show category badge (pkb/opencode) where applicable.

**Highlight helper**:
```javascript
function highlightMatches(text, indexes) {
    if (!indexes || indexes.length === 0) return escapeHtml(text);
    var result = '';
    var indexSet = {};
    indexes.forEach(function(i) { indexSet[i] = true; });
    for (var i = 0; i < text.length; i++) {
        var ch = escapeHtml(text[i]);
        if (indexSet[i]) {
            result += '<strong style="color:#0d6efd;">' + ch + '</strong>';
        } else {
            result += ch;
        }
    }
    return result;
}
```

---

### Task 5: Frontend — Parse new slash commands in parseMessageForCheckBoxes.js

**File**: `interface/parseMessageForCheckBoxes.js`

Add `processCommand` calls for the new command categories. These run on the first line only, outside backticks (same as existing commands).

```javascript
// Enable/Disable commands
processCommand(/\/enable_search\b/i, "perform_web_search", true);
processCommand(/\/disable_search\b/i, null);  // Special: need to set flag to explicit false
processCommand(/\/enable_pkb\b/i, "use_pkb", true);
processCommand(/\/disable_pkb\b/i, null);
processCommand(/\/enable_memory_pad\b/i, "use_memory_pad", true);
processCommand(/\/disable_memory_pad\b/i, null);
processCommand(/\/enable_tools\b/i, "enable_tool_use", true);
processCommand(/\/disable_tools\b/i, null);
processCommand(/\/enable_opencode\b/i, "enable_opencode", true);
processCommand(/\/disable_opencode\b/i, null);
processCommand(/\/enable_planner\b/i, "enable_planner", true);
processCommand(/\/disable_planner\b/i, null);
processCommand(/\/enable_persist\b/i, "persist_or_not", true);
processCommand(/\/disable_persist\b/i, null);
processCommand(/\/enable_auto_clarify\b/i, "auto_clarify", true);
processCommand(/\/disable_auto_clarify\b/i, null);

// Model selection: /model_<name> — sets main_model
// Must capture the model name after the underscore
processCommand(/\/model_(\S+)/i, "main_model");

// Agent selection: /agent_<name>
processCommand(/\/agent_(\S+)/i, "field");

// Preamble selection: /preamble_<name>
processCommand(/\/preamble_(\S+)/i, "preamble_slash_override");

// Also add bare token cleanup for new commands
removeBareTokenFromFirstLine(/\/model_\b/i);
removeBareTokenFromFirstLine(/\/agent_\b/i);
removeBareTokenFromFirstLine(/\/preamble_\b/i);
```

**Handling `/disable_*`**: The current `processCommand` sets `result[key] = true` for flags. For `/disable_*`, we need to set the flag to `false` explicitly. Two approaches:

**Approach A** (preferred — minimal change): Extend `processCommand` to accept a value parameter:
```javascript
const processCommand = (regex, key, isFlag = false, flagValue = true) => {
    // ... existing logic ...
    if (key) {
        result[key] = isFlag ? flagValue : match[1];
    }
    // ...
};

// Then:
processCommand(/\/enable_search\b/i, "perform_web_search", true, true);
processCommand(/\/disable_search\b/i, "perform_web_search", true, false);
```

**Approach B**: Add a separate `processDisableCommand` function. Less clean.

**Handling `/model_*` and `/agent_*` name resolution**: 
The captured `match[1]` from `/model_(\S+)` will be a friendly short name like "opus" or "gpt5.4". This needs to be resolved to the canonical name. Two options:

1. **Frontend resolution** (preferred): Use the cached catalog's `value_map` to resolve at parse time. The `processCommand` would need access to the cached catalog. Since `parseMessageForCheckBoxes` is a standalone function, pass the catalog as an optional parameter or use a global.

2. **Backend resolution**: Send the friendly name as-is and let the backend resolve it. Requires backend changes.

**Decision**: Frontend resolution using cached catalog. Add a post-processing step after `processCommand` calls:

```javascript
// After all processCommand calls, resolve model/agent/preamble names
if (result.main_model && cachedSlashCatalog) {
    var resolved = resolveFromCatalog('Models', result.main_model);
    if (resolved) result.main_model = [resolved];  // Array format for multi-select compatibility
}
if (result.field && cachedSlashCatalog) {
    var resolved = resolveFromCatalog('Agents', result.field);
    if (resolved) result.field = resolved;
}
```

**Handling `/preamble_*` additive merge**:
`mergeOptions` currently does `{...options, ...parsedOptions}` which overwrites arrays. For preamble, we need additive behavior:

```javascript
// In mergeOptions (line 187):
function mergeOptions(parsed_message, options) {
    const { text, ...parsedOptions } = parsed_message;
    const mergedOptions = { ...options, ...parsedOptions };
    
    // Special handling: preamble slash override is ADDITIVE
    if (parsedOptions.preamble_slash_override) {
        var existing = options.preamble_options || [];
        var resolved = resolveFromCatalog('Preambles', parsedOptions.preamble_slash_override);
        if (resolved) {
            mergedOptions.preamble_options = [...existing, resolved];
        }
        delete mergedOptions.preamble_slash_override;
    }
    
    return mergedOptions;
}
```

---

### Task 6: Documentation updates

**Files to update**:
- `documentation/product/ops/server_ops_and_runbook.md` — Add new endpoint, document command catalog
- `documentation/features/` — Create `slash_command_system.md` documenting all commands, autocomplete behavior, and how to add new commands
- `documentation/product/behavior/chat_app_capabilities.md` — Update with new slash command categories

---

## Implementation Order

1. **Task 1**: `@pkb` alias (trivial, independent, ship immediately)
2. **Task 2**: Backend catalog endpoint (independent, enables Task 3+4)
3. **Task 3**: Frontend catalog fetch + cache (depends on Task 2)
4. **Task 5**: Parse new commands in `parseMessageForCheckBoxes.js` (can parallel with Task 4)
5. **Task 4**: Autocomplete overhaul with fuzzy matching (depends on Task 3, biggest task)
6. **Task 6**: Documentation (after implementation)

## Files Modified

| File | Change |
|---|---|
| `interface/parseMessageForCheckBoxes.js` | `@pkb` alias, new slash commands, `/disable_*` support, model/agent/preamble resolution |
| `interface/common-chat.js` | Slash autocomplete IIFE overhaul: fuzzy match, 0-char trigger, 5-item display, catalog cache |
| `endpoints/slash_commands.py` | **NEW** — Backend catalog endpoint |
| `server.py` | Register new blueprint |
| `documentation/product/ops/server_ops_and_runbook.md` | New endpoint docs |
| `documentation/features/slash_command_system.md` | **NEW** — Feature documentation |

## Edge Cases & Watch-outs

- **Multiple model/agent commands on same line**: `processCommand` only matches first occurrence. This is correct — document it.
- **`/model_` without a name**: `removeBareTokenFromFirstLine` strips it silently.
- **Model name ambiguity**: "gpt5" could match "openai/gpt-5.4" and "openai/gpt-5.2". Prefer the first match (most recent/default). Document the mapping.
- **Stale catalog cache**: Acceptable — models/agents change rarely. User refreshes to get updated list.
- **`/preamble_*` additive merge**: Must modify `mergeOptions` to concat instead of overwrite for preamble arrays.
- **Existing `/search` vs `/enable_search`**: Both work. `/search` is the existing short form. `/enable_search` is the explicit form. They set the same flag. No conflict.
- **Custom preambles**: User-created preambles may not be in the static catalog. Options: (a) exclude from autocomplete, (b) include if fetched per-user. Start with (a), add (b) later.

## Alternatives Considered

1. **Oracle recommended against `/enable_*`/`/disable_*`**: User wants both approaches — keep `/enable_*` AND simple aliases.
2. **Parse options from HTML**: Oracle recommended static Python catalog instead of HTML parsing. We follow this — backend is the source of truth.
3. **Separate `slash_override_*` keys**: Oracle recommended reusing existing `checkboxes` keys. We follow this.
