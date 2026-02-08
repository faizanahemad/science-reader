# Hierarchical Workspaces

## Summary

Workspaces support unlimited nesting depth. Any workspace can contain sub-workspaces and conversations at the same level. The sidebar uses **jsTree 3.3.17** (jQuery plugin) to render a VS Code-style file explorer with right-click and triple-dot context menus, wholerow selection, folder/file icons, and workspace color indicators.

Previously workspaces were flat (one level only). This feature adds a `parent_workspace_id` column to `WorkspaceMetadata`, rewrites the sidebar rendering from custom jQuery DOM manipulation to jsTree, and adds backend APIs for moving workspaces, querying paths, and cascade-safe deletion.

## Data Model

### Database file

All workspace data lives in `storage/users/users.db` (SQLite). Path resolved via `_db_path(users_dir=users_dir)` which returns `{users_dir}/users.db`.

### Tables involved

**`WorkspaceMetadata`** — one row per workspace globally.

| Column | Type | Notes |
|--------|------|-------|
| `workspace_id` | text PRIMARY KEY | Format: `<user_email>_<16-char random>` or `default_<email>_<domain>` |
| `workspace_name` | text | Display name |
| `workspace_color` | text | Bootstrap color key: primary, success, danger, warning, info, purple, pink, orange |
| `domain` | text | Domain namespace (e.g. "assistant", "search") |
| `expanded` | boolean | Whether the tree node is expanded in the sidebar |
| `parent_workspace_id` | text (nullable) | Points to another `workspace_id`. NULL = root level. **NEW** |
| `created_at` | text | ISO datetime string |
| `updated_at` | text | ISO datetime string |

**`ConversationIdToWorkspaceId`** — maps conversations to workspaces. Also stores "workspace marker" rows.

| Column | Type | Notes |
|--------|------|-------|
| `conversation_id` | text PRIMARY KEY | The conversation ID, or `NULL` for workspace marker rows |
| `user_email` | text | User who owns this mapping |
| `workspace_id` | text | The workspace this conversation belongs to |
| `created_at` | text | ISO datetime string |
| `updated_at` | text | ISO datetime string |

Important: workspace marker rows have `conversation_id IS NULL`. Since SQLite allows multiple NULLs in a PRIMARY KEY column, each workspace gets one marker row per user. These rows are how the system knows a workspace "exists" for a user (used by `workspaceExistsForUser()`).

**`UserToConversationId`** — maps users to conversations (not modified by this feature, but used in the conversation listing JOIN).

### Indexes

Pre-existing:
- `idx_ConversationIdToWorkspaceId_conversation_id` UNIQUE on `(conversation_id)`
- `idx_ConversationIdToWorkspaceId_workspace_id` on `(workspace_id)`
- `idx_ConversationIdToWorkspaceId_user_email` on `(user_email)`
- `idx_WorkspaceMetadata_workspace_id` on `(workspace_id)`

New:
- `idx_WorkspaceMetadata_parent_workspace_id` on `(parent_workspace_id)` — speeds up child workspace lookups and cascade operations.

### Schema migration

In `database/connection.py`, function `create_tables()`, after creating all tables and existing indexes:

```python
# Line 170-176
try:
    cur.execute("ALTER TABLE WorkspaceMetadata ADD COLUMN parent_workspace_id text")
    log.info("Added parent_workspace_id column to WorkspaceMetadata table")
except Exception:
    # Column already exists or other error - this is fine
    pass

cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_WorkspaceMetadata_parent_workspace_id ON WorkspaceMetadata (parent_workspace_id)"
)
```

This runs on every server start. The `ALTER TABLE` is idempotent via try/except. The index uses `IF NOT EXISTS`. No foreign key constraint is added (SQLite limitation with ALTER TABLE), but cycle prevention is enforced in application code.

Existing workspaces get `parent_workspace_id = NULL` automatically (SQLite default for new columns). No data migration script is needed.

### Default workspace

The default workspace ID is `default_{user_email}_{domain}`. It is auto-created by `load_workspaces_for_user()` if missing. The default workspace:
- Gets `workspace_name = "default_{user_email}_{domain}"` (displayed as "General" in the UI via `getWorkspaceDisplayName()`).
- Gets `workspace_color = NULL` (rendered as "primary"/blue by the frontend fallback `ws.workspace_color || 'primary'`).
- Gets `parent_workspace_id = NULL` (root level).
- Gets `expanded = True`.
- Cannot be deleted or renamed from the UI (context menu items are disabled).

### Workspace ID generation

In `endpoints/workspaces.py`, new workspace IDs are generated as:
```python
workspace_id = email + "_" + "".join(secrets.choice(alphabet) for _ in range(16))
```
where `alphabet = string.ascii_letters + string.digits`. This produces IDs like `user@example.com_aB3cD4eF5gH6iJ7k`.

## Backend — Database Layer

### File: `database/workspaces.py`

Module docstring: "Workspace persistence helpers." All functions use keyword-only arguments (`*`) and open/close their own SQLite connections via `create_connection(_db_path(users_dir=users_dir))`. The caller (endpoint handler) is responsible for passing `users_dir` from the application state.

#### Complete function inventory

**`_db_path(*, users_dir: str) -> str`** (private)
- Returns `f"{users_dir}/users.db"`.

**`load_workspaces_for_user(*, users_dir, user_email, domain) -> list[dict]`** (modified)
- Returns all workspaces for a user in a domain.
- Query JOINs `ConversationIdToWorkspaceId` with `WorkspaceMetadata` on `workspace_id`.
- Filter: `WHERE c.user_email = ? AND c.workspace_id IS NOT NULL AND wm.domain = ?`.
- Returns list of dicts with keys: `workspace_id`, `workspace_name`, `workspace_color`, `domain`, `expanded`, `parent_workspace_id`.
- If the default workspace (`default_{email}_{domain}`) is not in results, creates it:
  - INSERTs into `WorkspaceMetadata` (with `parent_workspace_id = NULL`) using `INSERT OR IGNORE`.
  - INSERTs a workspace marker row into `ConversationIdToWorkspaceId` (with `conversation_id = NULL`) using `INSERT OR IGNORE`.
  - Appends the default workspace dict to the result list.

**`addConversationToWorkspace(*, users_dir, user_email, conversation_id, workspace_id)`** (unchanged)
- `INSERT OR IGNORE INTO ConversationIdToWorkspaceId`.

**`moveConversationToWorkspace(*, users_dir, user_email, conversation_id, workspace_id)`** (modified)
- Uses `WHERE conversation_id=?` only (PK-based) instead of the previous `WHERE user_email=? AND conversation_id=?`. This fixes a bug where the user_email stored in the row might not match the session email exactly (e.g. case sensitivity), causing the UPDATE to match 0 rows and silently do nothing.
- If `cur.rowcount == 0` after the UPDATE (no existing mapping row), falls back to `INSERT OR REPLACE INTO ConversationIdToWorkspaceId` to create the mapping.
- Uses try/finally to ensure connection is closed.

**`removeConversationFromWorkspace(*, users_dir, user_email, conversation_id)`** (unchanged)
- `DELETE FROM ConversationIdToWorkspaceId WHERE user_email=? AND conversation_id=?`.

**`getWorkspaceForConversation(*, users_dir, conversation_id) -> Optional[dict]`** (modified)
- Two-step lookup: first gets `workspace_id` from `ConversationIdToWorkspaceId`, then gets full metadata from `WorkspaceMetadata`.
- SELECT now includes `parent_workspace_id` column.
- Result dict now includes `parent_workspace_id`.
- If `WorkspaceMetadata` row is missing, returns minimal dict with just `workspace_id` and `user_email`.

**`getConversationsForWorkspace(*, users_dir, workspace_id, user_email)`** (unchanged)
- `SELECT * FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?`.

**`_is_ancestor(cursor, *, ancestor_id, workspace_id) -> bool`** (new, private)
- Walks up the `parent_workspace_id` chain from `workspace_id`.
- At each step: `SELECT parent_workspace_id FROM WorkspaceMetadata WHERE workspace_id=?`.
- Returns `True` if `ancestor_id` is encountered at any point.
- Uses a `visited` set to prevent infinite loops if the data is corrupted (circular reference).
- Takes an open cursor (not a connection) so it can be called within an existing transaction.

**`workspaceExistsForUser(*, users_dir, user_email, workspace_id) -> bool`** (new)
- Checks for a workspace marker row: `SELECT 1 FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=? AND conversation_id IS NULL`.
- Returns `cur.fetchone() is not None`.

**`moveWorkspaceToParent(*, users_dir, user_email, workspace_id, new_parent_workspace_id) -> None`** (new)
- Moves a workspace to a new parent. Pass `new_parent_workspace_id=None` to move to root.
- Validation (all raise `ValueError`):
  1. `workspace_id == new_parent_workspace_id` → "Workspace cannot be its own parent."
  2. Source workspace must exist for user (checked via workspace marker row query).
  3. If `new_parent_workspace_id` is not None, target parent must exist for user.
  4. `_is_ancestor(workspace_id, new_parent_workspace_id)` → "Cannot move workspace into its own descendant." (cycle prevention)
- Performs: `UPDATE WorkspaceMetadata SET parent_workspace_id=?, updated_at=? WHERE workspace_id=?`.

**`getWorkspacePath(*, users_dir, workspace_id) -> list[dict]`** (new)
- Returns breadcrumb path from root to the specified workspace.
- Walks up `parent_workspace_id` chain: at each step SELECTs `workspace_id, workspace_name, workspace_color, domain, expanded, parent_workspace_id` from `WorkspaceMetadata`.
- Collects dicts, reverses the list (so root is first, target is last).
- Uses `visited` set for cycle safety.

**`createWorkspace(*, users_dir, user_email, workspace_id, domain, workspace_name, workspace_color, parent_workspace_id=None)`** (modified)
- New optional parameter `parent_workspace_id` (default `None`).
- INSERTs into `WorkspaceMetadata` with 8 columns (including `parent_workspace_id`).
- INSERTs workspace marker row into `ConversationIdToWorkspaceId` (conversation_id=NULL).
- New workspaces start with `expanded=True`.

**`collapseWorkspaces(*, users_dir, workspace_ids: list[str])`** (unchanged)
- Bulk update: `UPDATE WorkspaceMetadata SET expanded=0 WHERE workspace_id IN (...)`.

**`updateWorkspace(*, users_dir, user_email, workspace_id, workspace_name=None, workspace_color=None, expanded=None)`** (unchanged)
- Dynamic UPDATE: builds SET clause from non-None parameters.
- Always sets `updated_at`.

**`deleteWorkspace(*, users_dir, workspace_id, user_email, domain)`** (modified)
- Cascade-safe deletion. Steps in order:
  1. Look up the workspace's `parent_workspace_id` from `WorkspaceMetadata`. If no row found, return early.
  2. Compute `target_workspace_id = parent_workspace_id or default_workspace_id`. Children go to parent if one exists, otherwise to the default workspace.
  3. Ensure default workspace metadata and marker row exist (INSERT OR IGNORE for both).
  4. Move child workspaces: `UPDATE WorkspaceMetadata SET parent_workspace_id=? WHERE parent_workspace_id=?` → points children at the target.
  5. Move conversations: `UPDATE ConversationIdToWorkspaceId SET workspace_id=? WHERE workspace_id=? AND user_email=? AND conversation_id IS NOT NULL` → points conversations at the target. The `IS NOT NULL` filter excludes the workspace marker row itself.
  6. Delete workspace mapping rows: `DELETE FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?`.
  7. Check if any other users still have mapping rows for this workspace_id: `SELECT 1 FROM ConversationIdToWorkspaceId WHERE workspace_id=? LIMIT 1`. If none, delete the `WorkspaceMetadata` row too.
  8. Commit.

## Backend — API Endpoints

### File: `endpoints/workspaces.py`

Blueprint: `workspaces_bp = Blueprint("workspaces", __name__)`. All endpoints require `@login_required`. Rate-limited via `@limiter.limit(...)`.

Imports from `database.workspaces`: `collapseWorkspaces`, `createWorkspace`, `deleteWorkspace`, `getWorkspacePath`, `load_workspaces_for_user`, `moveConversationToWorkspace`, `moveWorkspaceToParent`, `workspaceExistsForUser`. The `updateWorkspace` import is done inline (line 126) to avoid circular imports.

All endpoint handlers begin with `get_session_identity()` to get `(email, name, loggedin)`, check login, and cast `email = str(email)`.

#### Complete endpoint inventory

**`POST /create_workspace/<domain>/<workspace_name>`** (modified)
- Rate limit: 500/min
- Request: optional JSON body with `workspace_color` (string, default "primary") and `parent_workspace_id` (string or null, default null).
- Empty string `""` for `parent_workspace_id` is treated as null.
- If `parent_workspace_id` is provided, validates via `workspaceExistsForUser()`. Returns 400 if not found.
- Generates `workspace_id = email + "_" + <16 random chars>`.
- Calls `createWorkspace(...)`.
- Response: `{ "workspace_id": "...", "workspace_name": "...", "workspace_color": "...", "parent_workspace_id": "..." }`.

**`GET /list_workspaces/<domain>`** (unchanged)
- Rate limit: 200/min
- Returns JSON array from `load_workspaces_for_user()`.
- Each item: `{ workspace_id, workspace_name, workspace_color, domain, expanded, parent_workspace_id }`.

**`PUT /update_workspace/<workspace_id>`** (unchanged)
- Rate limit: 500/min
- JSON body: any of `workspace_name`, `workspace_color`, `expanded` (at least one required).
- Calls `updateWorkspace(...)`.

**`POST /collapse_workspaces`** (unchanged)
- Rate limit: 500/min
- JSON body: `{ "workspace_ids": [...] }`.
- Calls `collapseWorkspaces(...)`.

**`DELETE /delete_workspace/<domain>/<workspace_id>`** (unchanged API, changed backend logic)
- Rate limit: 500/min
- Calls `deleteWorkspace(...)` which now handles cascade.

**`PUT /move_conversation_to_workspace/<conversation_id>`** (unchanged)
- Rate limit: 500/min
- JSON body: `{ "workspace_id": "<target_workspace_id>" }`.
- Calls `moveConversationToWorkspace(...)`.

**`PUT /move_workspace/<workspace_id>`** (new)
- Rate limit: 500/min
- JSON body: `{ "parent_workspace_id": "<target_id>" }` or `{ "parent_workspace_id": null }` for root.
- Empty string `""` is normalized to null.
- Calls `moveWorkspaceToParent(...)`.
- Returns 400 with error message on `ValueError` (cycle, self-parent, not found).
- Returns 500 on unexpected exceptions.

**`GET /get_workspace_path/<workspace_id>`** (new)
- Rate limit: 500/min
- Calls `getWorkspacePath(...)`.
- Returns JSON array of workspace metadata dicts (root first, target last).
- Returns 404 if empty (workspace not found).

## Frontend — HTML

### File: `interface/interface.html`

#### CDN additions (in `<head>`)

```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.17/themes/default-dark/style.min.css" />
<script src="https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.17/jstree.min.js"></script>
```

jsTree 3.3.17 includes the vakata context menu library bundled.

#### Sidebar structure (replaces old Chats header + workspaces-container + context menu divs)

```html
<div class="sidebar-toolbar d-flex justify-content-between align-items-center mt-2">
    <h5 class="mb-0">Explorer</h5>
    <div class="sidebar-toolbar-actions">
        <button id="add-new-chat" type="button" class="btn btn-sm sidebar-tool-btn" title="New Conversation">
            <i class="fa fa-file-o"></i>
        </button>
        <button id="add-new-workspace" type="button" class="btn btn-sm sidebar-tool-btn" title="New Workspace">
            <i class="fa fa-folder-o"></i>
        </button>
    </div>
</div>
<div id="workspaces-container" style="margin-top: 4px;">
    <!-- jsTree initialised here by workspace-manager.js -->
</div>
```

Removed elements:
- `#workspace-context-menu` div with rename/delete/change-color/move-to submenu.
- `#conversation-context-menu` div with open-new-window/move-to submenu.
- Old `#workspaces-container` with custom workspace section structure.
- Old "Chats" header with button group and tip text.

## Frontend — JavaScript

### File: `interface/workspace-manager.js`

1078 lines. Single global object `WorkspaceManager` initialized on `$(document).ready()`.

#### State properties

| Property | Type | Description |
|----------|------|-------------|
| `workspaces` | Object | Map of `workspace_id -> workspace data object` |
| `conversations` | Array | All conversations for current domain, sorted by `last_updated` descending |
| `_mobileConversationInterceptorInstalled` | Boolean | Guard to prevent double-installation of mobile interceptor |
| `_jsTreeReady` | Boolean | Set to `true` after `ready.jstree` fires |
| `_pendingHighlight` | String/null | Conversation ID queued for highlighting before tree is ready |
| `defaultWorkspaceId` | String (getter) | Computed: `"default_" + userDetails.email + "_" + currentDomain.domain` |

#### Workspace data object shape (in `workspacesMap`)

```javascript
{
    workspace_id: "...",
    name: "...",               // from ws.workspace_name
    color: "primary",          // from ws.workspace_color || 'primary'
    is_default: true/false,    // ws.workspace_id === defaultWorkspaceId
    expanded: true/false,      // coerced from true/'true'/1
    parent_workspace_id: null  // from ws.parent_workspace_id || null
}
```

#### `init()`
Called on `$(document).ready()`. Does two things:
1. `installMobileConversationInterceptor()` — capture-phase event listener for mobile touch handling.
2. `setupToolbarHandlers()` — binds click handlers for `#add-new-workspace` and `#add-new-chat`.

#### `installMobileConversationInterceptor()`

Installs three capture-phase event listeners on `document`: `touchend`, `pointerup`, `click`. On mobile widths (≤768px), when a conversation node (`li.jstree-node` with ID starting with `cv_`) is tapped:
1. Extracts conversation ID from node ID (strips `cv_` prefix).
2. Hides sidebar: adds `d-none` to `#chat-assistant-sidebar`, switches `#chat-assistant` from `col-md-10` to `col-md-12`.
3. Calls `ConversationManager.setActiveConversation(conversationId)`.

Guard checks: skip if button element, skip if modifier keys held, skip if already handled (`e.__conversationItemHandled`), skip if same conversation already active. Debounce: 700ms after `touchend` before `click` is processed (prevents double-fire).

#### `setupToolbarHandlers()`

- `#add-new-workspace` → `showCreateWorkspaceModal(null)`. Always creates top-level workspace. Sub-workspace creation is only available via context menu.
- `#add-new-chat` → `createConversationInWorkspace(getSelectedWorkspaceId() || defaultWorkspaceId)`. Creates conversation in the currently selected workspace, or default if none selected.

#### `getSelectedWorkspaceId() -> string|null`

Returns the real `workspace_id` (without `ws_` prefix) of the currently selected node:
- If a workspace node is selected: returns the workspace_id.
- If a conversation node is selected: returns its parent workspace_id.
- If nothing is selected or tree not ready: returns null.

#### `loadConversationsWithWorkspaces(autoselect)`

Main data loading function. Called on init and after every CRUD operation.

1. Fires two parallel AJAX requests:
   - `GET /list_workspaces/{domain}` → workspace metadata array
   - `GET /list_conversation_by_user/{domain}` → conversation metadata array
2. Sorts conversations by `last_updated` descending.
3. Builds `workspacesMap` from workspace data, adding `parent_workspace_id` field.
4. Ensures default workspace exists in the map (client-side fallback).
5. Groups conversations by `workspace_id` (conversations without a workspace go to default).
6. Calls `renderTree(convByWs)`.
7. Auto-selection logic (when `autoselect=true`):
   - If URL contains a conversation ID (`getConversationIdFromUrl()`), selects that conversation.
   - Otherwise, tries to resume from `localStorage` key `lastActiveConversationId:{email}:{domain}`.
   - Falls back to first conversation in sorted list.
8. When `autoselect=false`: re-highlights the current active conversation if any.
9. Sets up `window.onpopstate` handler for browser back/forward.
10. For "search" domain: auto-stateless the selected conversation.

Returns the `$.when()` promise for chaining.

#### `getWorkspaceDisplayName(workspace) -> string`

Returns "General" for the default workspace, otherwise `workspace.name`.

#### `getWorkspaceDescendantIds(workspaceId) -> object`

Iterative BFS using a stack. Returns an object where keys are workspace IDs that are descendants of `workspaceId`. Used by `buildWorkspaceMoveSubmenu()` to disable invalid move targets.

#### `buildJsTreeData(convByWs) -> array`

Produces a flat array of node objects for jsTree's `core.data` option (jsTree builds the tree from parent pointers).

Workspace nodes:
```javascript
{
    id: 'ws_' + workspace_id,
    parent: ws.parent_workspace_id ? ('ws_' + ws.parent_workspace_id) : '#',
    text: displayName + ' (N)',   // N = conversation count, omitted if 0
    type: 'workspace',
    state: { opened: ws.expanded },
    li_attr: { 'data-workspace-id': workspace_id, 'data-color': ws.color },
    a_attr: { title: displayName }
}
```

Conversation nodes:
```javascript
{
    id: 'cv_' + conversation_id,
    parent: 'ws_' + wsId,
    text: title,                  // full title, trimmed, or '(untitled)'
    type: 'conversation',
    li_attr: {
        'data-conversation-id': conversation_id,
        'data-flag': flag || 'none',
        'class': ' jstree-flag-' + flag   // only if flag !== 'none'
    },
    a_attr: {
        title: conv.title || '',
        'data-conversation-id': conversation_id
    }
}
```

#### `renderTree(convByWs)`

1. Destroys previous jsTree instance if `_jsTreeReady` is true.
2. Builds tree data via `buildJsTreeData()`.
3. Initializes `$('#workspaces-container').jstree({...})` with:
   - `core.data`: flat node array
   - `core.check_callback: true` — allows programmatic modifications
   - `core.themes`: `default-dark`, no dots, icons enabled, responsive
   - `core.multiple: false` — single selection only
   - `types.workspace`: icon `fa fa-folder`, `li_attr: { class: 'ws-node' }`
   - `types.conversation`: icon `fa fa-comment-o`, `li_attr: { class: 'conv-node' }`, `max_depth: 0` (cannot have children)
   - `contextmenu`: plugin is loaded (so `$.vakata.context` is available) but with `items: function () { return {}; }` to prevent jsTree's built-in right-click from showing anything. We handle context menus ourselves.
   - `plugins: ['types', 'wholerow', 'contextmenu']`

4. Event bindings (all use `.off().on()` to prevent duplicate handlers):

   **`ready.jstree`**: Sets `_jsTreeReady = true`, calls `addTripleDotButtons()`, processes `_pendingHighlight` if queued.

   **`redraw.jstree`**, **`after_open.jstree`**: Re-adds triple-dot buttons (jsTree re-renders DOM on these events).

   **`select_node.jstree`**: When a conversation node is selected (ID starts with `cv_`), calls `ConversationManager.setActiveConversation(conversationId)`. Also closes the sidebar on mobile (≤768px). Does nothing if the same conversation is already active.

   **`open_node.jstree`**: For workspace nodes, sends `PUT /update_workspace/{id}` with `{ expanded: true }`.

   **`contextmenu.ws`** (custom namespace): Bound on the container div itself. On any right-click within the tree:
   - Finds closest `.jstree-node` `<li>` from `e.target`.
   - Calls `e.preventDefault()`, `e.stopPropagation()`, `e.stopImmediatePropagation()`.
   - Calls `showNodeContextMenu(nodeId, e.pageX, e.pageY)`.

   **`close_node.jstree`**: For workspace nodes, sends `PUT /update_workspace/{id}` with `{ expanded: false }`.

#### `addTripleDotButtons()`

Iterates all `.jstree-node` `<li>` elements in the tree. For each node that doesn't already have a `.jstree-node-menu-btn`:
1. Creates `<span class="jstree-node-menu-btn" title="Menu"><i class="fa fa-ellipsis-v"></i></span>`.
2. Finds the node's `> .jstree-anchor` element and inserts the button after it (before any child `<ul>`).
3. Binds `click` handler with `stopPropagation` + `stopImmediatePropagation` + `return false` → calls `showNodeContextMenu(nodeId, e.pageX, e.pageY)`.
4. Binds `mousedown` handler with `stopPropagation` + `stopImmediatePropagation` to prevent jsTree's selection handler from firing.

#### `showNodeContextMenu(nodeId, x, y)`

1. Gets jsTree instance and node object.
2. Calls `$.vakata.context.hide()` to close any existing menu.
3. Builds menu items via `buildContextMenuItems(node)`.
4. Converts to vakata format via `_convertToVakataItems(items, node)`.
5. Calculates menu X position: `Math.max(x, sidebarRightEdge + 2)` — prevents menu from appearing behind the narrow sidebar.
6. Creates a temporary 1x1px `<span>` at the adjusted coordinates and appends to `<body>`.
7. Calls `$.vakata.context.show(posEl, {x, y}, vakataItems)`.
8. Removes the positioning element after 200ms.

#### `_convertToVakataItems(items, node) -> object`

Converts our menu item format to vakata's expected format. Key logic:
- Items without a `label` and with `separator_before` or `separator_after` are treated as pure separators: they are skipped, and their separator flag is propagated to the next real item via `nextNeedsSepBefore`.
- `action` functions are wrapped so they're called with `self` context.
- `submenu` objects are recursively converted.
- Missing `icon` defaults to empty string (prevents vakata from showing undefined).

#### Context menu item builders

**`buildWorkspaceContextMenu(node)`** — items for workspace nodes:

| Key | Label | Icon | Behavior | Disabled when |
|-----|-------|------|----------|---------------|
| `addConversation` | New Conversation | `fa-file-o` | `createConversationInWorkspace(wsId)` | never |
| `addSubWorkspace` | New Sub-Workspace | `fa-folder-o` | `showCreateWorkspaceModal(wsId)` | never |
| `rename` | Rename | `fa-edit` | `showRenameWorkspaceModal(wsId)` | default workspace |
| `changeColor` | Change Color | `fa-palette` | `showWorkspaceColorModal(wsId)` | never |
| `moveTo` | Move to... | `fa-folder-open` | submenu via `buildWorkspaceMoveSubmenu(wsId)` | default workspace |
| `deleteWs` | Delete | `fa-trash` | `deleteWorkspace(wsId)` | default workspace |

Separators: before `rename` and before `deleteWs`.

**`buildConversationContextMenu(node)`** — items for conversation nodes:

| Key | Label | Icon | Behavior |
|-----|-------|------|----------|
| `openNewWindow` | Open in New Window | `fa-external-link` | `window.open('/interface/' + convId, '_blank')` |
| `clone` | Clone | `fa-clone` | `ConversationManager.cloneConversation(convId)` then reload + highlight |
| `toggleStateless` | Toggle Stateless | `fa-eye-slash` | `ConversationManager.statelessConversation(convId)` |
| `flag` | Set Flag | `fa-flag` | submenu via `buildFlagSubmenu(convId)` |
| `moveTo` | Move to... | `fa-folder-open` | submenu via `buildConversationMoveSubmenu(convId)` |
| `deleteConv` | Delete | `fa-trash` | `DELETE /delete_conversation/{convId}` then reload |

Separators: before `clone` and before `deleteConv`.

**`buildFlagSubmenu(convId)`** — flag color options:
- none (No Flag, `fa-flag-o`), red, blue, green, yellow, orange, purple (all `fa-flag`).
- Each calls `POST /set_flag/{convId}/{color}` then reloads.

**`buildConversationMoveSubmenu(convId)`** — hierarchical workspace list:
- Recursively builds items by walking workspace tree (starting from root workspaces where `parent_workspace_id` is null).
- Each workspace gets a folder icon. Display name is prefixed with spaces for visual indentation.
- Action: `moveConversationToWorkspace(convId, workspace_id)`.

**`buildWorkspaceMoveSubmenu(wsId)`** — hierarchical workspace list with cycle prevention:
- First item: "Top level" (`fa-arrow-up`). Disabled if workspace is already at root level.
- Then recursively lists all workspaces. Disabled if the target is:
  - The workspace itself or a descendant (from `getWorkspaceDescendantIds()`).
  - The workspace's current parent (already there).

#### CRUD methods

All make AJAX calls and call `loadConversationsWithWorkspaces(false)` on success to refresh the tree.

| Method | HTTP | URL | Body |
|--------|------|-----|------|
| `createWorkspace(name, color, parentWorkspaceId)` | POST | `/create_workspace/{domain}/{name}` | `{ workspace_color, parent_workspace_id }` |
| `renameWorkspace(workspaceId, newName)` | PUT | `/update_workspace/{id}` | `{ workspace_name }` |
| `updateWorkspaceColor(workspaceId, newColor)` | PUT | `/update_workspace/{id}` | `{ workspace_color }` |
| `deleteWorkspace(workspaceId)` | DELETE | `/delete_workspace/{domain}/{id}` | none |
| `moveConversationToWorkspace(convId, targetWsId)` | PUT | `/move_conversation_to_workspace/{convId}` | `{ workspace_id }` |
| `moveWorkspaceToParent(wsId, parentWsId)` | PUT | `/move_workspace/{wsId}` | `{ parent_workspace_id }` |
| `createConversationInWorkspace(wsId)` | POST | `/create_conversation/{domain}/{wsId}` | none |

Special behaviors:
- `deleteWorkspace`: shows `confirm()` dialog first. Blocked for default workspace with `alert()`.
- `createConversationInWorkspace`: on success, clears `#linkInput` and `#searchInput`, reloads with `autoselect=true`, then highlights the new conversation.
- `moveConversationToWorkspace`: on success, preserves current active conversation and re-highlights it after 100ms delay (to wait for tree rebuild).

#### `highlightActiveConversation(conversationId)`

1. If `_jsTreeReady` is false or tree instance not available, queues the ID in `_pendingHighlight` and returns.
2. Deselects all nodes: `tree.deselect_all(true)` (suppress event).
3. Gets the node `cv_{conversationId}`.
4. Collects all parent node IDs by walking up `node.parent` until reaching `#` (root).
5. Reverses the parent list (root first) and opens each: `tree.open_node(pid, false, false)`.
6. Selects the conversation node: `tree.select_node(nodeId, true)` (suppress event to prevent re-triggering `select_node.jstree`).

#### Modal dialogs

Three modal functions. All use Bootstrap 4.6 syntax:
- Close button: `<button type="button" class="close" data-dismiss="modal"><span>&times;</span></button>`
- Cancel button: `<button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>`
- Select elements: `class="custom-select"` (not `form-select`)
- Modal cleanup: `modal.on('hidden.bs.modal', function () { modal.remove(); })` removes the modal from DOM after hiding.

**`showCreateWorkspaceModal(parentWorkspaceId)`**
- Title: "Create Sub-Workspace" if `parentWorkspaceId` is set, otherwise "Create New Workspace".
- Fields: Workspace Name (text input), Color (select with 8 options: Blue/Green/Red/Yellow/Cyan/Purple/Pink/Orange).
- Create button calls `createWorkspace(name, color, parentWorkspaceId)`.

**`showRenameWorkspaceModal(workspaceId)`**
- Pre-fills input with current workspace name.
- Rename button calls `renameWorkspace(workspaceId, newName)`.

**`showWorkspaceColorModal(workspaceId)`**
- Select pre-selects current color.
- Change button calls `updateWorkspaceColor(workspaceId, newColor)`.

## Frontend — CSS

### File: `interface/workspace-styles.css`

296 lines. Complete rewrite for jsTree integration. All rules use high specificity and `!important` where needed to override jsTree's default-dark theme.

#### Width containment strategy

The core problem: jsTree's internal `<ul>` and `<li>` elements have no width constraint from the theme. They expand to content width, overflowing the narrow `col-md-2` sidebar (~238px). `overflow-x: hidden` on the container just clips rather than forces wrapping.

Solution — force `width: 100%` at every level:

1. `#workspaces-container` — `overflow-x: hidden !important; width: 100% !important; max-width: 100% !important`.
2. Every `<ul>` in the tree (`#workspaces-container ul`) — `width: 100% !important; max-width: 100% !important; overflow: hidden !important; padding-left: 0 !important`.
3. Root `<ul>` (`> .jstree > .jstree-container-ul`) — `padding: 0; margin: 0`.
4. Children `<ul>` (`.jstree-children`) — `padding-left: 6px !important` (the only indent source).
5. Every `<li>` (`.jstree-node`) — `width: 100% !important; margin-left: 0 !important; overflow: hidden !important; background-image: none !important` (kills theme indent guides).

#### Node styling

- `.jstree-node` — `min-height: 20px; line-height: 18px; position: relative` (for absolute triple-dot button).
- `.jstree-leaf > .jstree-ocl` — `display: none !important` (hides useless toggle arrow on leaf/conversation nodes).
- `.jstree-ocl` — `width: 14px; height: 18px; background-image: none` (compact toggle arrow).
- `.jstree-themeicon` — `width: 14px; margin-right: 2px` (compact type icon).

#### Anchor (text) styling

- `font-size: 0.76rem`
- `line-height: 17px`
- `padding: 1px 18px 1px 0` (18px right for triple-dot)
- `white-space: normal !important` (allows word wrap)
- `word-break: break-word !important`
- `overflow-wrap: break-word !important`
- `display: block !important` (instead of inline, forces block-level wrapping)
- `height: auto !important` (overrides theme fixed height)
- `text-overflow: unset !important` (overrides theme ellipsis)

#### Wholerow

- `.jstree-wholerow` — `width: 100%; height: 100%; position: absolute; top: 0; left: 0`.
- `.jstree-wholerow-clicked` — `background: rgba(0, 120, 212, 0.35)` (blue highlight).
- `.jstree-wholerow-hovered` — `background: rgba(255, 255, 255, 0.06)` (subtle hover).

#### Selection

- `.jstree-clicked` — `color: #fff; background: transparent; box-shadow: none` (text-only highlight, background handled by wholerow).
- `.jstree-hovered` — `background: transparent; box-shadow: none`.

#### Icon colors

- Folder icon (`.ws-node > .jstree-anchor > .jstree-themeicon`) — `color: #dcb67a` (gold).
- Conversation icon (`.conv-node > .jstree-anchor > .jstree-themeicon`) — `color: #75beff` (light blue).
- Icon font size: `0.75rem`.

#### Workspace color indicators

Each workspace node `<li>` has `data-color="..."` attribute set via `li_attr`. CSS rules:

| data-color | Border color | Bootstrap equivalent |
|-----------|-------------|---------------------|
| primary | `#007bff` | Blue |
| success | `#28a745` | Green |
| danger | `#dc3545` | Red |
| warning | `#ffc107` | Yellow |
| info | `#17a2b8` | Cyan |
| purple | `#6f42c1` | Purple |
| pink | `#e83e8c` | Pink |
| orange | `#fd7e14` | Orange |

Applied as `border-left: 3px solid {color}; padding-left: 2px` on the `.jstree-anchor`.

#### Conversation flag indicators

Conversation nodes with flags get a CSS class `jstree-flag-{color}` on the `<li>` (set via `li_attr.class`). CSS rules apply `border-left: 3px solid {color}` on the anchor. Supported: red, blue, green, yellow (`#ffc107`), orange, purple.

#### Triple-dot menu button

- `.jstree-node-menu-btn` — `display: none; position: absolute; right: 0; top: 0; z-index: 10; font-size: 0.7rem; line-height: 18px; color: #999`.
- Hover: `color: #fff; background: rgba(255,255,255,0.15); border-radius: 3px`.
- Show triggers (both use `display: inline-block !important`):
  - `.jstree-node:hover > .jstree-node-menu-btn` — show on row hover.
  - `.jstree-clicked ~ .jstree-node-menu-btn` — show when anchor is selected (sibling selector works because button is inserted after anchor).

#### Context menu (vakata) styling

Vakata is the context menu library bundled with jsTree. It renders a `<ul class="vakata-context">` appended to `<body>`.

Container:
- `background: #252526` (VS Code dark background)
- `border: 1px solid #454545`
- `border-radius: 4px`
- `min-width: 160px`
- `-webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; text-rendering: optimizeLegibility` (crisp text)
- `transform: none` (prevents sub-pixel blur)

Menu items (`li > a`):
- `font-size: 0.82rem; color: #e0e0e0; font-weight: 400; letter-spacing: 0.01em`
- `text-shadow: none !important` — **critical fix**. Vakata's default CSS has `text-shadow: 1px 1px 0 white` which causes a blurry "double vision" effect on dark backgrounds.
- `-webkit-font-smoothing: antialiased`

Hover: `background: #094771; color: #fff`.
Icons: `color: #888`, hover `color: #fff`.
Separators: `border-top: 1px solid #454545; margin: 2px 0`.
Disabled: `color: #666; cursor: default; no hover highlight`.

#### Legacy styles

Flag color picker popover styles are preserved for any remnant DOM (`.flag-color-picker-popover`, `.flag-color-option`). These use the same dark theme colors.

## Backward Compatibility

- All existing conversations and workspaces continue to work without any data migration.
- The `parent_workspace_id` column defaults to `NULL` (SQLite default for new columns), so all existing workspaces appear at root level.
- Deep links (`/interface/<conversation_id>`) are preserved. The `highlightActiveConversation` function opens all parent workspace nodes and selects the conversation node.
- Mobile sidebar close-on-select is preserved via capture-phase touch/click interceptor that detects `li.jstree-node` with `cv_` prefix IDs.
- The `moveConversationToWorkspace` fix (using PK-only WHERE clause and INSERT fallback) makes conversation moves more robust for all existing data regardless of user_email casing.
- Browser back/forward navigation via `window.onpopstate` is preserved.
- `localStorage` resume of last active conversation is preserved.

## Bug Fixes Included

1. **Move conversation silently failing**: The `moveConversationToWorkspace` UPDATE used `WHERE user_email=? AND conversation_id=?`. Since `conversation_id` is the PRIMARY KEY (one row per conversation), the `user_email` filter was unnecessary and could cause zero-row updates if the stored email casing didn't match. Fixed to use `WHERE conversation_id=?` only, with INSERT fallback.

2. **Hazy context menu text**: Vakata's default CSS applies `text-shadow: 1px 1px 0 white` to all menu items. On a dark background, this creates a blurry "double vision" effect. Fixed with `text-shadow: none !important`.

3. **Context menu appearing behind sidebar**: The vakata context menu was positioned at the mouse click coordinates, which could place it behind the narrow sidebar column. Fixed by computing the sidebar's right edge and using `Math.max(mouseX, sidebarRightEdge + 2)`.

4. **Highlight not working on page load / deep link**: jsTree initializes asynchronously — the `ready.jstree` event fires after DOM creation. `highlightActiveConversation()` called before this event would silently fail (node doesn't exist yet). Fixed with `_pendingHighlight` queue that's processed in the `ready.jstree` handler.

5. **Modal close/cancel buttons not working**: Modals used Bootstrap 5 syntax (`data-bs-dismiss="modal"`, `btn-close`, `form-select`) but the project uses Bootstrap 4.6. Fixed to `data-dismiss="modal"`, `close`, `custom-select`.

## Files Modified

| File | Lines | Change summary |
|------|-------|---------------|
| `database/connection.py` | ~10 lines added | ALTER TABLE migration for `parent_workspace_id`, new index |
| `database/workspaces.py` | ~613 total | `parent_workspace_id` in all queries/INSERTs, new functions: `_is_ancestor`, `workspaceExistsForUser`, `moveWorkspaceToParent`, `getWorkspacePath`. Modified: `moveConversationToWorkspace` (PK-based), `deleteWorkspace` (cascade), `createWorkspace` (parent param) |
| `endpoints/workspaces.py` | ~279 total | `parent_workspace_id` in create endpoint, new endpoints: `PUT /move_workspace/<id>`, `GET /get_workspace_path/<id>`. New imports |
| `interface/interface.html` | ~15 lines changed | jsTree CDN links, simplified sidebar HTML, removed old context menu divs |
| `interface/workspace-manager.js` | ~1078 total (full rewrite) | jsTree init, tree data builder, triple-dot buttons, vakata context menus, pending highlight queue, CRUD methods, modal dialogs, mobile interceptor |
| `interface/workspace-styles.css` | ~296 total (full rewrite) | jsTree width containment, anchor text wrapping, triple-dot visibility, workspace color borders, flag borders, vakata dark styling with text-shadow fix |
| `documentation/features/workspaces/README.md` | This file | Exhaustive documentation |
| `documentation/product/behavior/chat_app_capabilities.md` | ~30 lines changed | Updated Workspaces section |
| `documentation/README.md` | 1 line added | Added workspaces feature entry |

## Implementation Notes and Gotchas

1. **jsTree theme indent guides**: The `default-dark` theme uses `background-image` on `<li>` nodes for indent guide lines. These are invisible but take up space and affect layout. Override with `background-image: none !important`.

2. **jsTree `<ul>` width**: jsTree's `<ul>` elements have no width constraint. They expand to content width (can be 600px+ for long titles). The `overflow-x: hidden` on the container just clips rather than forces wrapping. Must set `width: 100% !important` on every `<ul>` and `<li>` in the tree.

3. **Vakata text-shadow**: The vakata context menu library has `text-shadow: 1px 1px 0 white` in its base CSS. This is designed for light themes but causes a "double vision" haze effect on dark backgrounds.

4. **jsTree async init**: jsTree initializes asynchronously. The `ready.jstree` event fires after all DOM nodes are created. Any `select_node` or `get_node` calls before this will fail silently.

5. **SQLite NULL in PRIMARY KEY**: `ConversationIdToWorkspaceId` has `conversation_id text PRIMARY KEY`. Workspace marker rows store `NULL` as the conversation_id. SQLite allows multiple NULL values in a PRIMARY KEY column (unlike most other databases). This is by design and relied upon.

6. **Context menu positioning**: On narrow sidebars (`col-md-2` ~238px), right-click menus would appear at the mouse position inside the sidebar and get clipped. The fix positions menus at `Math.max(mouseX, sidebarRightEdge + 2)` to push them outside.

7. **Special characters in node IDs**: Workspace and conversation IDs contain email addresses (with `@`, `.`). jQuery `#` selectors fail on these. The code uses attribute selectors `[id="..."]` instead.

8. **Bootstrap version mismatch**: The project uses Bootstrap 4.6 (jQuery-based). Bootstrap 5 syntax (`data-bs-dismiss`, `btn-close`, `form-select`) does not work. Must use Bootstrap 4 equivalents (`data-dismiss`, `close`, `custom-select`).

9. **Leaf node toggle arrow**: jsTree renders a toggle arrow (`.jstree-ocl`) on all nodes including leaves. For conversation nodes this is useless and takes horizontal space. Hidden via `display: none !important` on `.jstree-leaf > .jstree-ocl`.

10. **Triple-dot button placement**: The button must be inserted after the `.jstree-anchor` (not appended to the `<li>`) because jsTree `<li>` elements contain child `<ul>` elements. Appending to `<li>` would place the button after the entire subtree. Using `anchor.after(btn)` ensures it's a direct sibling of the anchor.
