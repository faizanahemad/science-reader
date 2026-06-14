"""
Per-conversation SQLite storage layer.

Each conversation gets one `conversation.db` file in its storage folder.
This replaces 8+ JSON files with a single WAL-mode database providing
O(1) mutations, FTS5 search, and crash-safe transactions.
"""

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Optional

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    temperature REAL,
    answer_tldr TEXT,
    answer_keywords TEXT,
    message_short_hash TEXT,
    metadata TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_msg_position ON messages(position);
CREATE INDEX IF NOT EXISTS idx_msg_hash ON messages(message_short_hash) WHERE message_short_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS artefacts (
    artefact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    filetype TEXT,
    size_bytes INTEGER,
    metadata TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS artefact_links (
    message_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    link_type TEXT DEFAULT 'created',
    PRIMARY KEY (message_id, artefact_id)
);
CREATE INDEX IF NOT EXISTS idx_artlink_artefact ON artefact_links(artefact_id);

CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,
    doc_storage TEXT,
    doc_source TEXT,
    display_name TEXT,
    metadata TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    position INTEGER,
    metadata TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content=messages,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


def _json_encode(v: Any) -> Optional[str]:
    """Encode a value as JSON string, or None if value is None."""
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _json_decode(s: Optional[str]) -> Any:
    """Decode a JSON string, or return None."""
    if s is None:
        return None
    return json.loads(s)


class ConversationStore:
    """Per-conversation SQLite database wrapper."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript(_SCHEMA_SQL)
        cur = self._conn.cursor()
        row = cur.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        if row[0] == 0:
            cur.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_empty(self) -> bool:
        """True if no data has been imported (neither messages nor memory keys exist)."""
        row = self._conn.execute(
            "SELECT (SELECT COUNT(*) FROM messages) + (SELECT COUNT(*) FROM memory)"
        ).fetchone()
        return row[0] == 0

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0

    # ===================== Messages =====================

    def _msg_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a messages row back to the legacy dict format."""
        d = {
            "message_id": row["message_id"],
            "text": row["text"],
            "sender": row["role"],
            "show_hide": "hide" if row["hidden"] else "show",
        }
        # Reconstruct config: merge column-extracted fields + metadata.config
        config = {}
        if row["model"]:
            config["main_model"] = row["model"]
        if row["temperature"] is not None:
            config["temperature"] = row["temperature"]
        if row["answer_tldr"]:
            d["answer_tldr"] = row["answer_tldr"]
        if row["answer_keywords"]:
            d["answer_keywords"] = _json_decode(row["answer_keywords"])
        if row["message_short_hash"]:
            d["message_short_hash"] = row["message_short_hash"]
        # Merge metadata blob
        meta = _json_decode(row["metadata"])
        if meta:
            # If metadata has a config sub-dict, merge it with column-extracted config
            meta_config = meta.pop("config", None)
            if meta_config and isinstance(meta_config, dict):
                config.update(meta_config)
            d.update(meta)
        if config:
            d["config"] = config
        return d

    def _msg_from_dict(self, msg: dict, position: int) -> tuple:
        """Extract columns from a legacy message dict. Returns tuple for INSERT."""
        message_id = str(msg.get("message_id", uuid.uuid4().hex))
        role = msg.get("sender", "user")
        text = msg.get("text")
        # Unified hidden: OR of both legacy flags
        hidden = 0
        if msg.get("show_hide") == "hide":
            hidden = 1
        if msg.get("user_hidden"):
            hidden = 1
        # Extract model/temperature from config
        config = msg.get("config") or {}
        model = config.get("main_model")
        temperature = config.get("temperature")
        # model can be a list (multi-model feature) — join for storage
        if isinstance(model, list):
            model = ", ".join(str(m) for m in model)
        # temperature can occasionally be a list — take first
        if isinstance(temperature, list):
            temperature = temperature[0] if temperature else None
        if temperature is not None:
            try:
                temperature = float(temperature)
            except (TypeError, ValueError):
                temperature = None
        answer_tldr = msg.get("answer_tldr")
        answer_keywords = _json_encode(msg.get("answer_keywords"))
        message_short_hash = msg.get("message_short_hash")
        # Metadata: everything else not in dedicated columns
        _skip = {"message_id", "text", "sender", "show_hide", "user_hidden", "config",
                 "answer_tldr", "answer_keywords", "message_short_hash",
                 "user_id", "conversation_id"}
        meta = {k: v for k, v in msg.items() if k not in _skip and v is not None}
        # Keep slim config (minus model/temperature which are columns)
        slim_config = {k: v for k, v in config.items() if k not in ("main_model", "temperature")}
        if slim_config:
            meta["config"] = slim_config
        metadata = _json_encode(meta) if meta else None
        created_at = msg.get("created_at", time.time())
        return (message_id, position, role, text, hidden, model, temperature,
                answer_tldr, answer_keywords, message_short_hash, metadata, created_at, None)

    def get_messages(self, include_hidden: bool = True) -> list[dict]:
        sql = "SELECT * FROM messages ORDER BY position"
        if not include_hidden:
            sql = "SELECT * FROM messages WHERE hidden=0 ORDER BY position"
        rows = self._conn.execute(sql).fetchall()
        return [self._msg_to_dict(r) for r in rows]

    def get_message(self, message_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
        return self._msg_to_dict(row) if row else None

    def append_messages(self, messages: list[dict]):
        if not messages:
            return
        cur = self._conn.cursor()
        row = cur.execute("SELECT COALESCE(MAX(position), -1) FROM messages").fetchone()
        pos = row[0] + 1
        for msg in messages:
            vals = self._msg_from_dict(msg, pos)
            cur.execute(
                "INSERT OR REPLACE INTO messages (message_id, position, role, text, hidden, "
                "model, temperature, answer_tldr, answer_keywords, message_short_hash, "
                "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
            pos += 1
        self._conn.commit()

    def edit_message(self, message_id: str, text: str):
        self._conn.execute(
            "UPDATE messages SET text=?, updated_at=? WHERE message_id=?",
            (text, time.time(), message_id))
        self._conn.commit()

    def delete_message(self, message_id: str):
        self._conn.execute("DELETE FROM messages WHERE message_id=?", (message_id,))
        self._conn.commit()

    def delete_messages_batch(self, message_ids: list[str]):
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        self._conn.execute(f"DELETE FROM messages WHERE message_id IN ({placeholders})", message_ids)
        self._conn.commit()

    def set_hidden(self, message_id: str, hidden: bool):
        self._conn.execute(
            "UPDATE messages SET hidden=?, updated_at=? WHERE message_id=?",
            (1 if hidden else 0, time.time(), message_id))
        self._conn.commit()

    def set_hidden_batch(self, message_ids: list[str], hidden: bool):
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        self._conn.execute(
            f"UPDATE messages SET hidden=?, updated_at=? WHERE message_id IN ({placeholders})",
            [1 if hidden else 0, time.time()] + message_ids)
        self._conn.commit()

    def move_messages(self, message_ids: list[str], direction: str = "up"):
        """Swap positions of selected messages with their neighbor."""
        rows = self._conn.execute("SELECT message_id, position FROM messages ORDER BY position").fetchall()
        positions = [(r["message_id"], r["position"]) for r in rows]
        id_to_pos = {mid: pos for mid, pos in positions}
        ids_set = set(message_ids)
        indices = sorted(i for i, (mid, _) in enumerate(positions) if mid in ids_set)

        if not indices:
            return
        if direction == "up" and indices[0] == 0:
            return
        if direction == "down" and indices[-1] == len(positions) - 1:
            return

        cur = self._conn.cursor()
        if direction == "up":
            for idx in indices:
                mid_a = positions[idx][0]
                mid_b = positions[idx - 1][0]
                pos_a = positions[idx][1]
                pos_b = positions[idx - 1][1]
                cur.execute("UPDATE messages SET position=? WHERE message_id=?", (pos_b, mid_a))
                cur.execute("UPDATE messages SET position=? WHERE message_id=?", (pos_a, mid_b))
                positions[idx], positions[idx - 1] = positions[idx - 1], positions[idx]
        else:
            for idx in reversed(indices):
                mid_a = positions[idx][0]
                mid_b = positions[idx + 1][0]
                pos_a = positions[idx][1]
                pos_b = positions[idx + 1][1]
                cur.execute("UPDATE messages SET position=? WHERE message_id=?", (pos_b, mid_a))
                cur.execute("UPDATE messages SET position=? WHERE message_id=?", (pos_a, mid_b))
                positions[idx], positions[idx + 1] = positions[idx + 1], positions[idx]
        self._conn.commit()

    def overwrite_messages(self, messages: list[dict]):
        """Full replace (fork, insert-between). Deletes all then re-inserts."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM messages")
        # Rebuild FTS
        cur.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        for i, msg in enumerate(messages):
            vals = self._msg_from_dict(msg, i)
            cur.execute(
                "INSERT INTO messages (message_id, position, role, text, hidden, "
                "model, temperature, answer_tldr, answer_keywords, message_short_hash, "
                "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
        self._conn.commit()

    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        """FTS5 search. Returns matching messages ranked by relevance."""
        rows = self._conn.execute(
            "SELECT m.* FROM messages_fts f JOIN messages m ON m.rowid = f.rowid "
            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)).fetchall()
        return [self._msg_to_dict(r) for r in rows]

    def message_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    # ===================== Artefacts =====================

    def get_artefacts(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM artefacts ORDER BY created_at").fetchall()
        result = []
        for r in rows:
            d = {"artefact_id": r["artefact_id"], "name": r["name"],
                 "filename": r["filename"], "filetype": r["filetype"]}
            if r["size_bytes"]:
                d["size_bytes"] = r["size_bytes"]
            meta = _json_decode(r["metadata"])
            if meta:
                d.update(meta)
            result.append(d)
        return result

    def add_artefact(self, artefact: dict):
        aid = artefact.get("artefact_id", uuid.uuid4().hex)
        meta = {k: v for k, v in artefact.items()
                if k not in ("artefact_id", "name", "filename", "filetype", "size_bytes") and v is not None}
        self._conn.execute(
            "INSERT OR REPLACE INTO artefacts (artefact_id, name, filename, filetype, size_bytes, metadata) "
            "VALUES (?,?,?,?,?,?)",
            (aid, artefact.get("name", ""), artefact.get("filename", ""),
             artefact.get("filetype"), artefact.get("size_bytes"), _json_encode(meta) if meta else None))
        self._conn.commit()

    def update_artefact(self, artefact_id: str, **updates):
        cols = []
        vals = []
        direct = {"name", "filename", "filetype", "size_bytes"}
        for k, v in updates.items():
            if k in direct:
                cols.append(f"{k}=?")
                vals.append(v)
        if cols:
            cols.append("updated_at=?")
            vals.append(time.time())
            vals.append(artefact_id)
            self._conn.execute(f"UPDATE artefacts SET {','.join(cols)} WHERE artefact_id=?", vals)
            self._conn.commit()

    def delete_artefact(self, artefact_id: str):
        self._conn.execute("DELETE FROM artefacts WHERE artefact_id=?", (artefact_id,))
        self._conn.execute("DELETE FROM artefact_links WHERE artefact_id=?", (artefact_id,))
        self._conn.commit()

    # ===================== Artefact Links =====================

    def get_artefact_links(self) -> dict:
        """Returns {message_id: {artefact_id: ..., link_type: ...}} matching legacy format."""
        rows = self._conn.execute("SELECT * FROM artefact_links").fetchall()
        result = {}
        for r in rows:
            # Legacy format: one link per message (last one wins if multiple)
            result[r["message_id"]] = {"artefact_id": r["artefact_id"]}
        return result

    def get_links_for_artefact(self, artefact_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT message_id FROM artefact_links WHERE artefact_id=?", (artefact_id,)).fetchall()
        return [r["message_id"] for r in rows]

    def add_link(self, message_id: str, artefact_id: str, link_type: str = "created"):
        self._conn.execute(
            "INSERT OR REPLACE INTO artefact_links VALUES (?,?,?)",
            (message_id, artefact_id, link_type))
        self._conn.commit()

    def remove_links_for_message(self, message_id: str):
        self._conn.execute("DELETE FROM artefact_links WHERE message_id=?", (message_id,))
        self._conn.commit()

    def remove_links_for_artefact(self, artefact_id: str):
        self._conn.execute("DELETE FROM artefact_links WHERE artefact_id=?", (artefact_id,))
        self._conn.commit()

    # ===================== Memory (key-value) =====================

    def get_memory(self) -> dict:
        rows = self._conn.execute("SELECT key, value FROM memory").fetchall()
        return {r["key"]: _json_decode(r["value"]) for r in rows}

    def get_memory_key(self, key: str) -> Any:
        row = self._conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
        return _json_decode(row["value"]) if row else None

    def set_memory(self, updates: dict):
        cur = self._conn.cursor()
        for k, v in updates.items():
            cur.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?,?)",
                        (k, _json_encode(v)))
        self._conn.commit()

    def set_memory_key(self, key: str, value: Any):
        self._conn.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?,?)",
                           (key, _json_encode(value)))
        self._conn.commit()

    def delete_memory_key(self, key: str):
        self._conn.execute("DELETE FROM memory WHERE key=?", (key,))
        self._conn.commit()

    # ===================== Settings (key-value) =====================

    def get_settings(self) -> dict:
        rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: _json_decode(r["value"]) for r in rows}

    def set_settings(self, updates: dict):
        cur = self._conn.cursor()
        for k, v in updates.items():
            cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                        (k, _json_encode(v)))
        self._conn.commit()

    def set_settings_key(self, key: str, value: Any):
        self._conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                           (key, _json_encode(value)))
        self._conn.commit()

    # ===================== Documents =====================

    def get_documents(self, doc_type: str = None) -> list[dict]:
        if doc_type:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE doc_type=? ORDER BY created_at", (doc_type,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM documents ORDER BY created_at").fetchall()
        return [{"doc_id": r["doc_id"], "doc_type": r["doc_type"], "doc_storage": r["doc_storage"],
                 "doc_source": r["doc_source"], "display_name": r["display_name"],
                 **(json.loads(r["metadata"]) if r["metadata"] else {})} for r in rows]

    def add_document(self, doc_id: str, doc_type: str, doc_storage: str = None,
                     doc_source: str = None, display_name: str = None, **extra):
        self._conn.execute(
            "INSERT OR REPLACE INTO documents (doc_id, doc_type, doc_storage, doc_source, display_name, metadata) "
            "VALUES (?,?,?,?,?,?)",
            (doc_id, doc_type, doc_storage, doc_source, display_name,
             _json_encode(extra) if extra else None))
        self._conn.commit()

    def delete_document(self, doc_id: str):
        self._conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
        self._conn.commit()

    # ===================== Todos =====================

    def get_todos(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM todos ORDER BY position, created_at").fetchall()
        return [{"id": r["id"], "text": r["text"], "status": r["status"],
                 "position": r["position"], **(_json_decode(r["metadata"]) or {})} for r in rows]

    def add_todo(self, todo: dict):
        tid = todo.get("id", uuid.uuid4().hex)
        pos = todo.get("position")
        if pos is None:
            row = self._conn.execute("SELECT COALESCE(MAX(position), -1) FROM todos").fetchone()
            pos = row[0] + 1
        meta = {k: v for k, v in todo.items() if k not in ("id", "text", "status", "position")}
        self._conn.execute(
            "INSERT OR REPLACE INTO todos (id, text, status, position, metadata) VALUES (?,?,?,?,?)",
            (tid, todo["text"], todo.get("status", "pending"), pos,
             _json_encode(meta) if meta else None))
        self._conn.commit()

    def update_todo(self, todo_id: str, **updates):
        sets = []
        vals = []
        for k in ("text", "status", "position"):
            if k in updates:
                sets.append(f"{k}=?")
                vals.append(updates[k])
        if sets:
            sets.append("updated_at=?")
            vals.append(time.time())
            vals.append(todo_id)
            self._conn.execute(f"UPDATE todos SET {','.join(sets)} WHERE id=?", vals)
            self._conn.commit()

    def delete_todo(self, todo_id: str):
        self._conn.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        self._conn.commit()

    # ===================== Bulk Migration Import =====================

    def import_all(self, *, messages=None, artefacts=None, artefact_links=None,
                   memory=None, settings=None, uploaded_docs=None,
                   attached_docs=None, dill_attrs: dict = None):
        """
        Bulk import from legacy JSON/dill format. Single transaction.
        Called once during lazy migration of a conversation.
        """
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            # Messages
            if messages:
                for i, msg in enumerate(messages):
                    vals = self._msg_from_dict(msg, i)
                    cur.execute(
                        "INSERT OR IGNORE INTO messages (message_id, position, role, text, hidden, "
                        "model, temperature, answer_tldr, answer_keywords, message_short_hash, "
                        "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)

            # Artefacts
            if artefacts:
                for art in artefacts:
                    aid = art.get("artefact_id", art.get("id", uuid.uuid4().hex))
                    meta = {k: v for k, v in art.items()
                            if k not in ("artefact_id", "id", "name", "filename", "filetype", "size_bytes")
                            and v is not None}
                    cur.execute(
                        "INSERT OR IGNORE INTO artefacts (artefact_id, name, filename, filetype, size_bytes, metadata) "
                        "VALUES (?,?,?,?,?,?)",
                        (aid, art.get("name", ""), art.get("filename", ""),
                         art.get("filetype"), art.get("size_bytes"), _json_encode(meta) if meta else None))

            # Artefact links (old format: {message_id: {artefact_id: ..., message_index: ...}})
            if artefact_links:
                if isinstance(artefact_links, dict):
                    for mid, link_data in artefact_links.items():
                        if isinstance(link_data, dict):
                            aid = link_data.get("artefact_id")
                            if aid:
                                cur.execute("INSERT OR IGNORE INTO artefact_links VALUES (?,?,?)",
                                            (str(mid), str(aid), "created"))
                        elif isinstance(link_data, list):
                            for ld in link_data:
                                aid = ld.get("artefact_id") if isinstance(ld, dict) else ld
                                if aid:
                                    cur.execute("INSERT OR IGNORE INTO artefact_links VALUES (?,?,?)",
                                                (str(mid), str(aid), "created"))

            # Memory
            if memory:
                for k, v in memory.items():
                    # Trim running_summary to last 3
                    if k == "running_summary" and isinstance(v, list):
                        v = v[-3:]
                    cur.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?,?)",
                                (k, _json_encode(v)))

            # Settings
            if settings:
                for k, v in settings.items():
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                                (k, _json_encode(v)))

            # Uploaded documents (old format: list of tuples or list of dicts)
            if uploaded_docs:
                for doc in uploaded_docs:
                    if isinstance(doc, (list, tuple)):
                        # (doc_id, storage, source, display_name) or shorter
                        doc_id = doc[0] if len(doc) > 0 else uuid.uuid4().hex
                        storage = doc[1] if len(doc) > 1 else None
                        source = doc[2] if len(doc) > 2 else None
                        name = doc[3] if len(doc) > 3 else None
                        cur.execute(
                            "INSERT OR IGNORE INTO documents (doc_id, doc_type, doc_storage, doc_source, display_name) "
                            "VALUES (?,?,?,?,?)", (str(doc_id), "uploaded", storage, source, name))
                    elif isinstance(doc, dict):
                        cur.execute(
                            "INSERT OR IGNORE INTO documents (doc_id, doc_type, doc_storage, doc_source, display_name) "
                            "VALUES (?,?,?,?,?)",
                            (str(doc.get("doc_id", uuid.uuid4().hex)), "uploaded",
                             doc.get("doc_storage"), doc.get("doc_source"), doc.get("display_name")))

            # Attached documents (same format as uploaded)
            if attached_docs:
                for doc in attached_docs:
                    if isinstance(doc, (list, tuple)):
                        doc_id = doc[0] if len(doc) > 0 else uuid.uuid4().hex
                        storage = doc[1] if len(doc) > 1 else None
                        source = doc[2] if len(doc) > 2 else None
                        name = doc[3] if len(doc) > 3 else None
                        cur.execute(
                            "INSERT OR IGNORE INTO documents (doc_id, doc_type, doc_storage, doc_source, display_name) "
                            "VALUES (?,?,?,?,?)", (str(doc_id), "attached", storage, source, name))
                    elif isinstance(doc, dict):
                        cur.execute(
                            "INSERT OR IGNORE INTO documents (doc_id, doc_type, doc_storage, doc_source, display_name) "
                            "VALUES (?,?,?,?,?)",
                            (str(doc.get("doc_id", uuid.uuid4().hex)), "attached",
                             doc.get("doc_storage"), doc.get("doc_source"), doc.get("display_name")))

            # Dill attributes → memory table
            if dill_attrs:
                dill_to_memory = {
                    "_memory_pad": "memory_pad",
                    "_domain": "domain",
                    "_flag": "flag",
                    "_archived": "archived",
                    "_auto_archive_exempt": "auto_archive_exempt",
                    "_archive_source": "archive_source",
                    "_last_opened_at": "last_opened_at",
                    "_access_log": "access_log",
                }
                for attr, key in dill_to_memory.items():
                    if attr in dill_attrs and dill_attrs[attr] is not None:
                        val = dill_attrs[attr]
                        # Convert datetime to isoformat
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        cur.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?,?)",
                                    (key, _json_encode(val)))

            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
