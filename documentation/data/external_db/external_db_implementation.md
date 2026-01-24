## Database layer — implementation notes (developer-facing)

This file describes how persistence is implemented, where DB files live, and
how `database/*` modules are intended to be used.

### Key design goals

- Keep **SQL and persistence** out of `server.py` and out of route handlers.
- Provide a small, domain-oriented surface area for endpoints to call.
- Avoid circular imports by keeping DB modules independent of Flask.

### Where data lives

#### `users.db` (core server DB)

- **File**: `users.db`
- **Directory**: `users_dir` (provided by `AppState.users_dir` in `endpoints/state.py`)
- **Schema creation/upgrade**: `database.connection.create_tables(users_dir=...)`

#### `pkb.sqlite` (PKB DB)

- PKB uses `pkb.sqlite` under the same `users_dir`.
- That DB is managed by the PKB layer (`endpoints/pkb.py` / optional dependencies),
  not by `database/connection.py`.

### Connection pattern

The DB helpers use the simplest possible SQLite pattern:

- open a connection using `database.connection.create_connection(path)`
- do work using `cursor.execute(...)`
- `commit()` when needed
- close connection in `finally`

There is no global connection pool; each helper call opens/closes a connection.
This keeps the code simple and reduces cross-request coupling.

### Schema ownership and tables

`database.connection.create_tables(...)` is the canonical place where schema is
defined and ensured.

It creates (if missing):
- `UserToConversationId`
- `UserDetails`
- `ConversationIdToWorkspaceId`
- `WorkspaceMetadata`
- `DoubtsClearing`
- `SectionHiddenDetails`

It also:
- creates indexes for common query paths
- performs a small “migration” step:
  - attempts `ALTER TABLE DoubtsClearing ADD COLUMN child_doubt_id text`
  - ignores failure if the column already exists

### Default `users_dir` mechanism (incremental refactor support)

Some modules support both:
- explicit `users_dir=...` passed into every call (preferred), and
- a configured default users_dir (temporary convenience).

Implementation details:

- Modules like `database/conversations.py`, `database/users.py`, `database/doubts.py`, `database/sections.py`
  define:
  - `_default_users_dir: Optional[str]`
  - `configure_users_dir(users_dir: str) -> None`
  - `_resolve_users_dir(users_dir: Optional[str]) -> str` to enforce it exists

- `database/__init__.py` exposes `database.configure_users_dir(users_dir)` which
  sets defaults for all participating modules in one call.

Note: `database/workspaces.py` is stricter and generally expects `users_dir` to be passed.

### Datetime storage

Most tables store timestamps as text (either `datetime.now()` objects inserted
directly or `.isoformat()` strings depending on the module).

If you later want consistent ordering and portability, a good follow-up would be
to normalize timestamps to ISO-8601 strings everywhere.

### Concurrency considerations

- SQLite is safe for low/moderate concurrency but can lock on writes.
- Because the code opens/closes connections per call, long transactions are rare.
- If you see `database is locked` errors:
  - consider setting `timeout=` on `sqlite3.connect(...)`
  - consider using WAL mode (`PRAGMA journal_mode=WAL`)
  - reduce write frequency or batch writes

### How endpoints should use the DB layer

Pattern used across endpoint modules:

- obtain `users_dir` from app state:
  - `state = endpoints.state.get_state()`
  - `users_dir = state.users_dir`
- call DB helpers with explicit `users_dir=users_dir` where possible
- or rely on the one-time `database.configure_users_dir(state.users_dir)` called during app startup

### Adding a new table or query

1. Add the CREATE TABLE (and indexes) to `database/connection.py:create_tables`.
2. Create a new module `database/<domain>.py` or extend an existing domain module.
3. Keep helpers small and explicit; accept `users_dir` and (optionally) `logger`.
4. Avoid importing Flask or endpoint modules from `database/*`.
5. Add stable re-exports in `database/__init__.py` if the function is part of the public surface.


