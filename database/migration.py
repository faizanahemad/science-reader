"""
JSON → SQLite migration helpers for per-conversation storage.

Usage:
    python -m database.migration migrate_all <conversations_dir>
    python -m database.migration rollback <conversation_folder>
    python -m database.migration status <conversations_dir>
"""

import glob
import json
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

# Fields stored as separate JSON files per conversation
_JSON_FIELDS = [
    "messages",
    "memory",
    "artefacts",
    "artefact_message_links",
    "uploaded_documents_list",
    "message_attached_documents_list",
    "conversation_settings",
    "message_search_index",
]

_MIGRATED_SUFFIX = ".json.migrated"


def _load_json_file(path: str):
    """Load a JSON file, returning None if missing or corrupt."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read {path}: {e}")
        return None


def _load_dill_attrs(conv_folder: str, conv_id: str) -> dict:
    """Load dill .index and extract attributes to migrate to SQLite."""
    index_path = os.path.join(conv_folder, f"{conv_id}.index")
    if not os.path.exists(index_path):
        return {}
    try:
        import dill
        with open(index_path, "rb") as f:
            obj = dill.load(f)
        attrs = {}
        for attr in ("_memory_pad", "_domain", "_flag", "_archived",
                     "_auto_archive_exempt", "_archive_source",
                     "_last_opened_at", "_access_log"):
            if hasattr(obj, attr):
                attrs[attr] = getattr(obj, attr)
        return attrs
    except Exception as e:
        logger.warning(f"Could not load dill index {index_path}: {e}")
        return {}


def migrate_conversation(conv_folder: str, conv_id: str = None, force: bool = False) -> bool:
    """
    Migrate one conversation from JSON files to SQLite.

    Returns True if migration occurred, False if already migrated or no data.
    """
    from database.conversation_store import ConversationStore

    if conv_id is None:
        conv_id = os.path.basename(conv_folder)

    db_path = os.path.join(conv_folder, "conversation.db")
    messages_json = os.path.join(conv_folder, f"{conv_id}-messages.json")

    # Skip if no messages JSON (nothing to migrate)
    if not os.path.exists(messages_json):
        return False

    # Skip if already migrated (DB exists and has data), unless forced
    if os.path.exists(db_path) and not force:
        store = ConversationStore(db_path)
        if not store.is_empty():
            store.close()
            return False
        store.close()

    # Load all JSON fields
    messages = _load_json_file(messages_json) or []
    memory = _load_json_file(os.path.join(conv_folder, f"{conv_id}-memory.json"))
    artefacts = _load_json_file(os.path.join(conv_folder, f"{conv_id}-artefacts.json"))
    artefact_links = _load_json_file(os.path.join(conv_folder, f"{conv_id}-artefact_message_links.json"))
    settings = _load_json_file(os.path.join(conv_folder, f"{conv_id}-conversation_settings.json"))
    uploaded_docs = _load_json_file(os.path.join(conv_folder, f"{conv_id}-uploaded_documents_list.json"))
    attached_docs = _load_json_file(os.path.join(conv_folder, f"{conv_id}-message_attached_documents_list.json"))
    dill_attrs = _load_dill_attrs(conv_folder, conv_id)

    # Import into SQLite
    store = ConversationStore(db_path)
    store.import_all(
        messages=messages,
        artefacts=artefacts,
        artefact_links=artefact_links,
        memory=memory,
        settings=settings,
        uploaded_docs=uploaded_docs,
        attached_docs=attached_docs,
        dill_attrs=dill_attrs,
    )
    store.close()

    # Rename JSON files to .migrated (keep as backup)
    for field in _JSON_FIELDS:
        json_path = os.path.join(conv_folder, f"{conv_id}-{field}.json")
        if os.path.exists(json_path):
            migrated_path = json_path + ".migrated"
            os.rename(json_path, migrated_path)
            # Also rename .bak if present
            bak_path = json_path + ".bak"
            if os.path.exists(bak_path):
                os.rename(bak_path, bak_path + ".migrated")

    logger.info(f"Migrated conversation {conv_id} ({len(messages)} messages)")
    return True


def rollback_conversation(conv_folder: str, conv_id: str = None) -> bool:
    """
    Rollback a conversation from SQLite back to JSON files.
    Restores .migrated files and removes conversation.db.
    """
    if conv_id is None:
        conv_id = os.path.basename(conv_folder)

    restored = 0
    for field in _JSON_FIELDS:
        migrated_path = os.path.join(conv_folder, f"{conv_id}-{field}.json.migrated")
        json_path = os.path.join(conv_folder, f"{conv_id}-{field}.json")
        if os.path.exists(migrated_path):
            os.rename(migrated_path, json_path)
            restored += 1
            # Restore .bak too
            bak_migrated = migrated_path.replace(".json.migrated", ".json.bak.migrated")
            if os.path.exists(bak_migrated):
                os.rename(bak_migrated, json_path + ".bak")

    db_path = os.path.join(conv_folder, "conversation.db")
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    for p in (db_path, wal_path, shm_path):
        if os.path.exists(p):
            os.remove(p)

    if restored:
        logger.info(f"Rolled back conversation {conv_id} ({restored} files restored)")
        return True
    return False


def migrate_all(conversations_dir: str, force: bool = False) -> dict:
    """
    Migrate all conversations in a directory.
    Returns {migrated: int, skipped: int, failed: int, errors: list}.
    """
    stats = {"migrated": 0, "skipped": 0, "failed": 0, "errors": []}

    if not os.path.isdir(conversations_dir):
        print(f"Error: {conversations_dir} is not a directory")
        return stats

    for entry in os.listdir(conversations_dir):
        conv_folder = os.path.join(conversations_dir, entry)
        if not os.path.isdir(conv_folder):
            continue
        conv_id = entry
        try:
            if migrate_conversation(conv_folder, conv_id, force=force):
                stats["migrated"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"{conv_id}: {e}")
            logger.error(f"Failed to migrate {conv_id}: {e}", exc_info=True)

    return stats


def status(conversations_dir: str) -> dict:
    """Report migration status across all conversations."""
    result = {"total": 0, "migrated": 0, "pending": 0, "empty": 0}

    for entry in os.listdir(conversations_dir):
        conv_folder = os.path.join(conversations_dir, entry)
        if not os.path.isdir(conv_folder):
            continue
        result["total"] += 1
        conv_id = entry
        db_path = os.path.join(conv_folder, "conversation.db")
        messages_json = os.path.join(conv_folder, f"{conv_id}-messages.json")
        messages_migrated = messages_json + ".migrated"

        if os.path.exists(db_path):
            result["migrated"] += 1
        elif os.path.exists(messages_json):
            result["pending"] += 1
        elif os.path.exists(messages_migrated):
            result["migrated"] += 1
        else:
            result["empty"] += 1

    return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if cmd == "migrate_all":
        if len(sys.argv) < 3:
            print("Usage: python -m database.migration migrate_all <conversations_dir> [--force]")
            sys.exit(1)
        conv_dir = sys.argv[2]
        force = "--force" in sys.argv
        t0 = time.time()
        stats = migrate_all(conv_dir, force=force)
        elapsed = time.time() - t0
        print(f"Done in {elapsed:.1f}s: {stats['migrated']} migrated, "
              f"{stats['skipped']} skipped, {stats['failed']} failed")
        if stats["errors"]:
            print("Errors:")
            for e in stats["errors"]:
                print(f"  {e}")

    elif cmd == "rollback":
        if len(sys.argv) < 3:
            print("Usage: python -m database.migration rollback <conversation_folder>")
            sys.exit(1)
        conv_folder = sys.argv[2]
        if rollback_conversation(conv_folder):
            print(f"Rolled back: {conv_folder}")
        else:
            print(f"Nothing to roll back in: {conv_folder}")

    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: python -m database.migration status <conversations_dir>")
            sys.exit(1)
        s = status(sys.argv[2])
        print(f"Total: {s['total']} | Migrated: {s['migrated']} | "
              f"Pending: {s['pending']} | Empty: {s['empty']}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
