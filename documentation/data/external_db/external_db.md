## Database layer — external reference

This file is a **consumer-facing** reference for the `database/` package:
what data we store and which DB helpers other modules should call.

### High-level storage layout

- **Primary SQLite DB**: `users.db`
  - **Location**: `os.path.join(users_dir, "users.db")`
  - **Created/updated by**: `database.connection.create_tables(users_dir=...)`
- **PKB SQLite DB**: `pkb.sqlite`
  - **Location**: `os.path.join(users_dir, "pkb.sqlite")`
  - **Owned by**: PKB implementation (see `endpoints/pkb.py`), not by `database/`.

### Public entry points

You can import from `database` directly (re-exported in `database/__init__.py`), or
from the specific module.

#### Global configuration

- `database.configure_users_dir(users_dir: str) -> None`
  - Sets a default `users_dir` for modules that accept `users_dir: Optional[str]`
  - Prefer passing `users_dir=...` explicitly where possible; this exists to keep older call sites working.

#### Connection/schema

- `database.create_connection(db_file: str) -> sqlite3.Connection`
- `database.create_tables(*, users_dir: str, logger: Optional[logging.Logger] = None) -> None`

### Core tables (in `users.db`)

#### Conversations <-> users

Tables:
- `UserToConversationId(user_email, conversation_id, created_at, updated_at)`
- `ConversationIdToWorkspaceId(conversation_id PRIMARY KEY, user_email, workspace_id, created_at, updated_at)`

Primary helpers (module: `database/conversations.py`):
- `addConversation(user_email, conversation_id, workspace_id=None, domain=None, *, users_dir=None, logger=None) -> bool`
- `checkConversationExists(user_email, conversation_id, *, users_dir=None) -> bool`
- `getCoversationsForUser(user_email, domain, *, users_dir=None) -> list[tuple]`
  - Returns joined rows including workspace metadata when present.
- `deleteConversationForUser(user_email, conversation_id, *, users_dir=None) -> None`
- `cleanup_deleted_conversations(conversation_ids, *, users_dir=None, logger=None) -> None`
  - Also deletes rows from `SectionHiddenDetails` and `DoubtsClearing` for the deleted conversation ids.
- `getAllCoversations(*, users_dir=None) -> list[tuple]` (legacy helper)
- `getConversationById(conversation_id, *, users_dir=None) -> list[tuple]`
- `removeUserFromConversation(user_email, conversation_id, *, users_dir=None) -> None`

#### Workspaces

Tables:
- `WorkspaceMetadata(workspace_id PRIMARY KEY, workspace_name, workspace_color, domain, expanded, created_at, updated_at)`
- `ConversationIdToWorkspaceId(...)` (mapping table shared with conversations)

Primary helpers (module: `database/workspaces.py`):
- `load_workspaces_for_user(*, users_dir, user_email, domain) -> list[dict]`
  - Ensures a default workspace exists.
- `createWorkspace(*, users_dir, user_email, workspace_id, domain, workspace_name, workspace_color) -> None`
- `updateWorkspace(*, users_dir, user_email, workspace_id, workspace_name=None, workspace_color=None, expanded=None) -> None`
- `deleteWorkspace(*, users_dir, workspace_id, user_email, domain) -> None`
  - Moves conversations back into the default workspace for the domain.
- `collapseWorkspaces(*, users_dir, workspace_ids: list[str]) -> None`
- `addConversationToWorkspace(*, users_dir, user_email, conversation_id, workspace_id) -> None`
- `moveConversationToWorkspace(*, users_dir, user_email, conversation_id, workspace_id) -> None`
- `removeConversationFromWorkspace(*, users_dir, user_email, conversation_id) -> None`
- `getWorkspaceForConversation(*, users_dir, conversation_id) -> Optional[dict]`
- `getConversationsForWorkspace(*, users_dir, workspace_id, user_email) -> list[tuple]`

#### User details/preferences

Table:
- `UserDetails(user_email PRIMARY KEY, user_preferences, user_memory, created_at, updated_at)`

Primary helpers (module: `database/users.py`):
- `addUserToUserDetailsTable(user_email, user_preferences=None, user_memory=None, *, users_dir=None, logger=None) -> bool`
- `getUserFromUserDetailsTable(user_email, *, users_dir=None, logger=None) -> Optional[dict]`
- `updateUserInfoInUserDetailsTable(user_email, user_preferences=None, user_memory=None, *, users_dir=None, logger=None) -> bool`

#### Doubt clearing

Table:
- `DoubtsClearing(doubt_id PRIMARY KEY, conversation_id, user_email, message_id, doubt_text, doubt_answer, parent_doubt_id, child_doubt_id, is_root_doubt, created_at, updated_at)`

Primary helpers (module: `database/doubts.py`):
- `add_doubt(*, conversation_id, user_email, message_id, doubt_text, doubt_answer, parent_doubt_id=None, users_dir=None, logger=None) -> str`
  - Returns the generated `doubt_id`.
- `delete_doubt(*, doubt_id, users_dir=None, logger=None) -> bool`
  - Performs tree restructuring (linked-list style) when deleting.
- `get_doubt(*, doubt_id, users_dir=None, logger=None) -> Optional[dict]`
- `get_doubt_children(*, doubt_id, users_dir=None, logger=None) -> list[dict]`
- `build_doubt_tree(doubt_record: dict, *, users_dir=None, logger=None) -> dict`
- `get_doubts_for_message(*, conversation_id, message_id, user_email=None, users_dir=None, logger=None) -> list[dict]`
- `get_doubt_history(*, doubt_id, users_dir=None, logger=None) -> list[dict]`

#### Section hidden details

Table:
- `SectionHiddenDetails(conversation_id, section_id, hidden, created_at, updated_at, PRIMARY KEY(conversation_id, section_id))`

Primary helpers (module: `database/sections.py`):
- `get_section_hidden_details(*, conversation_id, section_ids: list[str], users_dir=None, logger=None) -> dict[str, dict]`
- `bulk_update_section_hidden_detail(*, conversation_id, section_updates: dict[str, bool], users_dir=None, logger=None) -> None`


