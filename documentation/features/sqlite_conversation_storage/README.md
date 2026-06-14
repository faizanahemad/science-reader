# SQLite Conversation Storage

Per-conversation SQLite storage layer replacing the old JSON flat-file system.

Plan: [`documentation/planning/plans/sqlite_storage_migration.plan.md`](../../planning/plans/sqlite_storage_migration.plan.md)

---

## Overview

Each conversation folder now contains a `conversation.db` SQLite file that replaces 8+ JSON files previously used for messages, artefacts, memory, settings, documents, todos, and search index. Migration is lazy — a conversation upgrades on first access if `conversation.db` is not yet present. Non-migrated conversations continue on the JSON path unchanged.

At 500 messages, mutations (edit/delete/hide) are **200–2000× faster** than the JSON path because SQLite updates a single row instead of deserializing, modifying, and reserializing the entire JSON blob.

---

## Architecture

**Core class:** `database/conversation_store.py` → `ConversationStore`

### Tables

| Table | Contents |
|-------|----------|
| `messages` | All chat messages with extracted `model`, `temperature`, `hidden` columns |
| `artefacts` | Artefact metadata |
| `artefact_links` | Message ↔ artefact relationships |
| `memory` | Key-value store for dill-only attrs and other metadata |
| `settings` | Key-value store for conversation settings |
| `documents` | Document records |
| `todos` | Todo items |
| `messages_fts` | FTS5 virtual table for full-text message search |

FTS5 is kept in sync automatically via INSERT/UPDATE/DELETE triggers on `messages`. `message_search_index` no longer exists.

**SQLite settings:** WAL journal mode, NORMAL synchronous, 5-second busy timeout.

---

## How It Works

- `Conversation._use_sqlite` — returns `True` if `conversation.db` exists in the conversation folder.
- `get_field` / `set_field` — dispatch to `_get_field_sqlite` / `_set_field_sqlite` when migrated.
- `edit_message`, `delete_message`, `show_hide_message`, `move_messages`, and batch operations all have direct SQLite fast paths that bypass JSON entirely.
- `save_local` — persists metadata attrs to the `memory` table and nulls non-serializable attrs before the dill dump.
- `load_local` — has a SQLite recovery path invoked when the dill blob is corrupt.

---

## Migration

```bash
# Migrate all conversations
python -m database.migration migrate_all <conversations_dir>

# Roll back a single conversation
python -m database.migration rollback <conversation_folder>

# Check migration status
python -m database.migration status <conversations_dir>
```

JSON files are renamed to `.json.migrated` and kept as backups. Rollback restores them and deletes `conversation.db`.

### Schema Transforms Applied During Migration

- `msg.user_id` and `msg.conversation_id` dropped (redundant with folder structure).
- `show_hide` + `user_hidden` unified into a single `hidden INTEGER` column.
- `config.main_model` extracted to a `model` column (multiple models joined with comma).
- `config.temperature` extracted to a `temperature` column.
- `running_summary` trimmed to the last 3 entries.
- Dill-only attrs (`_memory_pad`, `_domain`, `_flag`, `_archived`, etc.) moved to the `memory` table.
- `message_search_index` eliminated; FTS5 triggers maintain search automatically.

---

## Also Migrated

**`remember_tokens.json` → `users.db` `RememberTokens` table** — auto-migrated on first auth call (`endpoints/auth.py`).

**`pinned_claims` in-memory dict → `users.db` `PinnedClaims` table** — write-through cache (`endpoints/pkb.py`).

**`users.db` indexes** — 4 redundant indexes dropped; 2 new indexes added (conversation_id lookup, friendly_id UNIQUE).

---

## Key Files

| File | Purpose |
|------|---------|
| `database/conversation_store.py` | `ConversationStore` class — all CRUD operations |
| `database/migration.py` | `migrate` / `rollback` / `status` CLI |
| `database/connection.py` | `RememberTokens` + `PinnedClaims` DDL |
| `Conversation.py` | `conversation_store` property, `_use_sqlite` gate, routing |
| `endpoints/auth.py` | `remember_tokens` SQLite migration |
| `endpoints/pkb.py` | `pinned_claims` SQLite persistence |

---

## Performance (500 messages)

| Operation | JSON | SQLite | Speedup |
|-----------|------|--------|---------|
| Edit 1 message | 8.3 ms | 0.004 ms | 2000× |
| Delete 1 message | 14.1 ms | 0.07 ms | 200× |
| Show/hide | 9.8 ms | 0.005 ms | 1900× |
| Append 2 messages | 8.9 ms | 0.4 ms | 22× |
| Load all | 1.9 ms | 0.8 ms | 2.5× |

---

## What Stays as Files (Not Migrated)

| Path | Reason |
|------|--------|
| `{conv_id}-indices.partial` | FAISS binary embeddings — not relational |
| `{conv_id}-raw_documents_index.partial` | `DocIndex` structures — binary |
| `artefacts/` content files | Markdown/code blobs — filesystem is appropriate |
| `images/`, `audio_messages/` | Binary media |

---

## Backward Compatibility

- Conversations without `conversation.db` continue using the JSON path unchanged.
- Both paths coexist in `Conversation.py`; `_use_sqlite` acts as the gate.
- Full rollback is possible at any time via the migration CLI.
