"""
Eager startup migration: move per-conversation docs into the canonical store.

Run once on first startup after deploying the canonical doc store feature.
Uses a sentinel file (``storage/documents/.local_migration_done``) to skip
on subsequent boots.

Conversations are migrated in parallel via ``ThreadPoolExecutor``.  Progress
is logged every N conversations so the admin can monitor long migrations.

Usage (from ``server.py``)::

    from migrate_docs import run_local_docs_migration
    run_local_docs_migration(
        conversation_folder=conversation_folder,
        docs_folder=docs_folder,
        logger=logger,
        max_workers=4,
    )
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import canonical_docs as _cd

logger = logging.getLogger(__name__)

# Sentinel file written after a successful full migration.
_SENTINEL_FILENAME = ".local_migration_done"


def _sentinel_path(docs_folder: str) -> str:
    return os.path.join(docs_folder, _SENTINEL_FILENAME)


def _discover_conversations(conversation_folder: str) -> list[str]:
    """Return a list of absolute paths to conversation directories.

    Each conversation lives in ``conversation_folder/{email}_{conv_id}/``
    and contains a dill-pickled ``.index`` file.
    """
    if not os.path.isdir(conversation_folder):
        return []
    result = []
    for name in os.listdir(conversation_folder):
        full = os.path.join(conversation_folder, name)
        if os.path.isdir(full):
            result.append(full)
    return result


def _migrate_one_conversation(conv_path: str, docs_folder: str) -> dict:
    """Migrate all docs in a single conversation to the canonical store.

    Returns a stats dict: {migrated: int, skipped: int, failed: int, error: str|None}
    """
    stats = {"migrated": 0, "skipped": 0, "failed": 0, "error": None, "path": conv_path}
    try:
        from Conversation import Conversation
        conv = Conversation.load_local(conv_path)
        if conv is None:
            stats["error"] = "Failed to load conversation"
            return stats

        u_hash = _cd.user_hash(conv.user_id)
        changed = False

        # --- Migrate uploaded_documents_list ---
        uploaded_docs = conv.get_field("uploaded_documents_list") or []
        new_uploaded = []
        for entry in uploaded_docs:
            doc_id = entry[0]
            doc_storage = entry[1]
            source_path = entry[2] if len(entry) > 2 else ""

            if _cd.is_canonical_path(docs_folder, doc_storage):
                # Already canonical
                new_uploaded.append(entry)
                stats["skipped"] += 1
                continue

            try:
                new_storage = _cd.migrate_doc_to_canonical(
                    docs_folder=docs_folder,
                    u_hash=u_hash,
                    doc_id=str(doc_id),
                    old_storage=doc_storage,
                    source_path=source_path,
                )
                if new_storage != doc_storage:
                    entry = (entry[0], new_storage) + entry[2:]
                    changed = True
                    stats["migrated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                logger.debug(
                    "migrate_docs: failed doc %s in %s: %s",
                    doc_id, conv_path, exc,
                )
                stats["failed"] += 1
            new_uploaded.append(entry)

        # --- Migrate message_attached_documents_list ---
        msg_docs = conv.get_field("message_attached_documents_list") or []
        new_msg_docs = []
        for entry in msg_docs:
            doc_id = entry[0]
            doc_storage = entry[1]
            source_path = entry[2] if len(entry) > 2 else ""

            if _cd.is_canonical_path(docs_folder, doc_storage):
                new_msg_docs.append(entry)
                stats["skipped"] += 1
                continue

            try:
                new_storage = _cd.migrate_doc_to_canonical(
                    docs_folder=docs_folder,
                    u_hash=u_hash,
                    doc_id=str(doc_id),
                    old_storage=doc_storage,
                    source_path=source_path,
                )
                if new_storage != doc_storage:
                    entry = (entry[0], new_storage) + entry[2:]
                    changed = True
                    stats["migrated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                logger.debug(
                    "migrate_docs: failed msg doc %s in %s: %s",
                    doc_id, conv_path, exc,
                )
                stats["failed"] += 1
            new_msg_docs.append(entry)

        # --- Persist changes ---
        if changed:
            conv.set_field("uploaded_documents_list", new_uploaded, overwrite=True)
            if msg_docs:
                conv.set_field("message_attached_documents_list", new_msg_docs, overwrite=True)
            conv.save_local()

    except Exception as exc:
        stats["error"] = str(exc)
        logger.error("migrate_docs: error processing %s: %s", conv_path, exc)

    return stats


def run_local_docs_migration(
    *,
    conversation_folder: str,
    docs_folder: str,
    max_workers: int = 4,
    log: Optional[logging.Logger] = None,
) -> None:
    """Migrate all per-conversation docs into the canonical store.

    Idempotent: writes a sentinel file on completion and skips on subsequent
    calls.  Conversations are processed in parallel.

    Parameters
    ----------
    conversation_folder:
        Absolute path to ``storage/conversations/``.
    docs_folder:
        Absolute path to ``storage/documents/`` (the canonical root).
    max_workers:
        Thread pool size for parallel migration.  4 is a safe default.
    log:
        Logger instance.  Falls back to module-level logger.
    """
    _log = log or logger

    sentinel = _sentinel_path(docs_folder)
    if os.path.isfile(sentinel):
        _log.info("Local docs migration: already done (sentinel exists). Skipping.")
        return

    conversations = _discover_conversations(conversation_folder)
    total = len(conversations)
    if total == 0:
        _log.info("Local docs migration: no conversations found. Skipping.")
        _write_sentinel(sentinel)
        return

    _log.info(
        "Local docs migration: starting migration of %d conversation(s) with %d workers.",
        total, max_workers,
    )
    start = time.time()

    total_migrated = 0
    total_skipped = 0
    total_failed = 0
    completed = 0
    progress_interval = max(1, total // 10)  # log every ~10%

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_migrate_one_conversation, conv_path, docs_folder): conv_path
            for conv_path in conversations
        }

        for future in as_completed(futures):
            conv_path = futures[future]
            completed += 1
            try:
                stats = future.result()
                total_migrated += stats["migrated"]
                total_skipped += stats["skipped"]
                total_failed += stats["failed"]
                if stats["error"]:
                    _log.warning(
                        "Local docs migration: error in %s: %s",
                        os.path.basename(conv_path), stats["error"],
                    )
            except Exception as exc:
                _log.error(
                    "Local docs migration: exception processing %s: %s",
                    os.path.basename(conv_path), exc,
                )
                total_failed += 1

            if completed % progress_interval == 0 or completed == total:
                elapsed = time.time() - start
                _log.info(
                    "Local docs migration progress: %d/%d conversations (%.0f%%) "
                    "| migrated=%d skipped=%d failed=%d | %.1fs elapsed",
                    completed, total, 100 * completed / total,
                    total_migrated, total_skipped, total_failed, elapsed,
                )

    elapsed = time.time() - start
    _log.info(
        "Local docs migration complete: %d conversation(s) processed in %.1fs. "
        "migrated=%d, skipped=%d, failed=%d.",
        total, elapsed, total_migrated, total_skipped, total_failed,
    )

    if total_failed == 0:
        _write_sentinel(sentinel)
    else:
        _log.warning(
            "Local docs migration: %d failure(s) — sentinel NOT written. "
            "Migration will re-run on next startup.",
            total_failed,
        )


def _write_sentinel(path: str) -> None:
    """Write the sentinel file indicating migration is complete."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        import datetime
        f.write(f"Migration completed at {datetime.datetime.now().isoformat()}\n")