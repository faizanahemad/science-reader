"""
Canonical document store — "store once, referenced from many".

All uploaded documents are stored at a single canonical location under
``storage/documents/{user_hash}/{doc_id}/``.  Content-based deduplication
uses SHA-256 hashing: an index file ``_sha256_index.json`` in each user’s
directory maps content hashes to ``doc_id`` values, catching the same file
uploaded under different names.

Conversations hold tuple references (doc_id, doc_storage, source_url,
display_name) that point at the canonical path; they never own a copy.

Benefits
--------
* Same file uploaded to N conversations → indexed once, referenced N times.
* Same file under different names → SHA-256 catches the duplicate.
* "Analyze" upgrade propagates to every conversation on next load.
* Cloning copies only the tuple list — no shutil.copytree.
* Promoting to global points at the existing canonical path.

Thread / process safety
-----------------------
``store_or_get`` uses ``filelock.FileLock`` to prevent concurrent uploads
of the same content from racing.  The SHA-256 index file is also locked
during reads and writes.

Key layout
----------
::

    storage/documents/{user_hash}/
      ├── _sha256_index.json        ← {sha256: doc_id} mapping for dedup
      ├── {doc_id_A}/
      │   ├── {doc_id_A}.index     ← dill-pickled DocIndex
      │   └── locks/
      └── {doc_id_B}/
          └── ...

Legacy per-conversation path (pre-migration)::

    storage/conversations/{conv_id}/uploaded_documents/{doc_id}/
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil

from filelock import FileLock

logger = logging.getLogger(__name__)

# How many bytes to read per chunk when computing SHA-256
_HASH_CHUNK = 1 << 20  # 1 MB

# Name of the per-user SHA-256 → doc_id mapping file
_SHA256_INDEX_FILENAME = "_sha256_index.json"


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def compute_file_hash(path: str) -> str:
    """Return the SHA-256 hex digest of the file at *path*.

    Parameters
    ----------
    path:
        Absolute or relative path to a local file.

    Returns
    -------
    str
        64-character lower-case hex string.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def user_hash(email: str) -> str:
    """Return the MD5 hex digest of *email* (matches global_docs convention).

    Parameters
    ----------
    email:
        User email address.

    Returns
    -------
    str
        32-character lower-case hex string.
    """
    return hashlib.md5(email.encode()).hexdigest()


# ---------------------------------------------------------------------------
# SHA-256 index management
# ---------------------------------------------------------------------------

def _sha256_index_path(docs_folder: str, u_hash: str) -> str:
    """Return path to the per-user SHA-256 index file."""
    return os.path.join(docs_folder, u_hash, _SHA256_INDEX_FILENAME)


def _sha256_lock_path(docs_folder: str, u_hash: str) -> str:
    """Return path to the lock file protecting the SHA-256 index."""
    return os.path.join(docs_folder, u_hash, _SHA256_INDEX_FILENAME + ".lock")


def _load_sha256_index(docs_folder: str, u_hash: str) -> dict:
    """Load the SHA-256 → doc_id mapping from disk.

    Returns an empty dict if the file does not exist or is corrupted.
    The caller must hold the index lock.
    """
    idx_path = _sha256_index_path(docs_folder, u_hash)
    if not os.path.isfile(idx_path):
        return {}
    try:
        with open(idx_path, "r") as f:
            return json.load(f)
    except Exception:
        logger.warning("canonical_docs: corrupt SHA-256 index at %s — resetting", idx_path)
        return {}


def _save_sha256_index(docs_folder: str, u_hash: str, index: dict) -> None:
    """Atomically write the SHA-256 index to disk.

    The caller must hold the index lock.
    """
    idx_path = _sha256_index_path(docs_folder, u_hash)
    tmp_path = idx_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(index, f, indent=2)
    os.replace(tmp_path, idx_path)  # atomic on POSIX


def register_sha256(docs_folder: str, u_hash: str, sha256: str, doc_id: str) -> None:
    """Record a SHA-256 → doc_id mapping.

    Thread-safe: acquires the index lock internally.
    """
    parent = get_canonical_parent(docs_folder, u_hash)
    os.makedirs(parent, exist_ok=True)
    lock = FileLock(_sha256_lock_path(docs_folder, u_hash), timeout=30)
    with lock:
        index = _load_sha256_index(docs_folder, u_hash)
        index[sha256] = str(doc_id)
        _save_sha256_index(docs_folder, u_hash, index)


def lookup_by_sha256(docs_folder: str, u_hash: str, sha256: str):
    """Look up a SHA-256 hash in the index.

    Returns
    -------
    str or None
        The ``doc_id`` if found and the canonical directory still exists,
        ``None`` otherwise.
    """
    parent = get_canonical_parent(docs_folder, u_hash)
    if not os.path.isdir(parent):
        return None
    lock = FileLock(_sha256_lock_path(docs_folder, u_hash), timeout=30)
    with lock:
        index = _load_sha256_index(docs_folder, u_hash)
    doc_id = index.get(sha256)
    if doc_id is None:
        return None
    # Verify the directory actually exists
    canonical = get_canonical_storage(docs_folder, u_hash, doc_id)
    if os.path.isdir(canonical):
        return doc_id
    return None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_canonical_parent(docs_folder: str, u_hash: str) -> str:
    """Return ``<docs_folder>/<user_hash>/`` — the per-user root directory.

    The directory is **not** created by this function.
    """
    return os.path.join(docs_folder, u_hash)


def get_canonical_storage(docs_folder: str, u_hash: str, doc_id: str) -> str:
    """Return the canonical storage directory for a specific document.

    The directory layout is ``<docs_folder>/<user_hash>/<doc_id>/``,
    which mirrors the path DocIndex creates when given the parent as storage.

    The directory is **not** created by this function.
    """
    return os.path.join(docs_folder, u_hash, str(doc_id))


# ---------------------------------------------------------------------------
# Core: store-or-get (SHA-256 aware)
# ---------------------------------------------------------------------------

def store_or_get(
    docs_folder: str,
    u_hash: str,
    source_path: str,
    build_fn,
) -> str:
    """Ensure a canonical index exists for the document at *source_path*.

    Deduplication strategy (layered):

    1. **SHA-256 check** — if *source_path* is a local file, compute its hash
       and look up the SHA-256 index.  If a matching doc_id is found whose
       canonical directory still exists, return it immediately.
    2. **Build** -- call *build_fn* to create the DocIndex.  DocIndex.__init__
       creates ``{doc_id}/`` inside the canonical parent.
    3. **Register** — record the SHA-256 → doc_id mapping for future lookups.

    A per-SHA ``FileLock`` is held during check-and-build to prevent concurrent
    uploads of identical content from racing.

    Parameters
    ----------
    docs_folder:
        Absolute path to ``storage/documents/``.
    u_hash:
        MD5 hex digest of the user's email.
    source_path:
        Local file path **or** URL.  SHA-256 dedup only works for local files;
        URLs are built without dedup (the doc_id-level check in DocIndex still
        prevents exact-source duplicates).
    build_fn:
        Callable ``(canonical_parent: str) -> DocIndex``.  Receives the parent
        directory; DocIndex creates ``{doc_id}/`` inside it.  Must call
        ``save_local()`` before returning.

    Returns
    -------
    str
        Absolute path to the canonical doc_id directory.  Always exists after
        return.
    """
    canonical_parent = get_canonical_parent(docs_folder, u_hash)
    os.makedirs(canonical_parent, exist_ok=True)

    # --- SHA-256 dedup for local files ---
    sha256 = None
    if os.path.isfile(source_path):
        sha256 = compute_file_hash(source_path)
        lock_path = os.path.join(canonical_parent, f".sha_{sha256[:16]}.lock")

        with FileLock(lock_path, timeout=600):
            # Check SHA-256 index
            existing_doc_id = lookup_by_sha256(docs_folder, u_hash, sha256)
            if existing_doc_id:
                existing_storage = get_canonical_storage(docs_folder, u_hash, existing_doc_id)
                if os.path.isdir(existing_storage):
                    logger.debug(
                        "canonical_docs: SHA-256 hit — reusing doc_id=%s for hash=%s",
                        existing_doc_id, sha256[:12],
                    )
                    return existing_storage

            # Build new index
            logger.info(
                "canonical_docs: building new index for sha256=%s",
                sha256[:12],
            )
            try:
                doc_index = build_fn(canonical_parent)
            except Exception:
                # Clean up partial build — doc_index._storage may have been created
                # We don't know doc_id here, so we can't clean precisely.
                raise

            # Register the SHA-256 → doc_id mapping
            register_sha256(docs_folder, u_hash, sha256, doc_index.doc_id)
            return doc_index._storage

    # --- URL or non-local source: build without SHA-256 dedup ---
    logger.info("canonical_docs: building index for non-local source %s", source_path[:80])
    doc_index = build_fn(canonical_parent)
    return doc_index._storage


# ---------------------------------------------------------------------------
# Path detection helper
# ---------------------------------------------------------------------------

def is_canonical_path(docs_folder: str, path: str) -> bool:
    """Return True if *path* lives under the canonical docs folder.

    Used by the lazy migration code in ``Conversation.get_uploaded_documents``
    to distinguish old per-conversation paths from already-migrated canonical
    paths.
    """
    docs_folder = os.path.normpath(docs_folder)
    path = os.path.normpath(path)
    return path.startswith(docs_folder + os.sep)


# ---------------------------------------------------------------------------
# Lazy migration helper
# ---------------------------------------------------------------------------

def migrate_doc_to_canonical(
    docs_folder: str,
    u_hash: str,
    doc_id: str,
    old_storage: str,
    source_path: str = "",
) -> str:
    """Move an existing per-conversation doc folder into the canonical store.

    Also computes the SHA-256 hash (from *source_path* or the ``.index`` file)
    and registers it in the SHA-256 index for future dedup lookups.

    The caller is responsible for updating the tuple in
    ``uploaded_documents_list`` and calling ``conversation.set_field(...)``.

    If a canonical directory already exists (another conversation already
    migrated this doc), the old directory is removed and the existing canonical
    path is returned.

    Parameters
    ----------
    docs_folder:
        Absolute path to ``storage/documents/``.
    u_hash:
        MD5 hex digest of the user's email.
    doc_id:
        Document ID used as the canonical subdirectory name.
    old_storage:
        Current ``doc_storage`` path (under ``uploaded_documents/``).
    source_path:
        Original file path for SHA-256 hashing.  Falls back to hashing the
        ``.index`` dill file inside *old_storage* if empty or non-existent.

    Returns
    -------
    str
        Canonical path the document now lives at.  Equals *old_storage* if
        migration failed for any reason (safe fallback).
    """
    canonical_storage = get_canonical_storage(docs_folder, u_hash, doc_id)
    lock_path = canonical_storage + ".lock"

    canonical_parent = get_canonical_parent(docs_folder, u_hash)
    os.makedirs(canonical_parent, exist_ok=True)

    with FileLock(lock_path, timeout=60):
        if os.path.isdir(canonical_storage):
            # Another conversation already migrated this doc — reuse it
            if old_storage != canonical_storage and os.path.isdir(old_storage):
                shutil.rmtree(old_storage, ignore_errors=True)
            _register_hash_for_doc(docs_folder, u_hash, doc_id, source_path, canonical_storage)
            return canonical_storage

        if not os.path.isdir(old_storage):
            logger.warning(
                "canonical_docs.migrate: old_storage %s does not exist — skipping",
                old_storage,
            )
            return old_storage

        try:
            shutil.copytree(old_storage, canonical_storage)
            shutil.rmtree(old_storage, ignore_errors=True)
            logger.info(
                "canonical_docs.migrate: moved doc_id=%s  %s -> %s",
                doc_id, old_storage, canonical_storage,
            )
            _register_hash_for_doc(docs_folder, u_hash, doc_id, source_path, canonical_storage)
        except Exception as exc:
            logger.error(
                "canonical_docs.migrate: failed to move %s -> %s: %s",
                old_storage, canonical_storage, exc,
            )
            return old_storage

    return canonical_storage


def _register_hash_for_doc(
    docs_folder: str, u_hash: str, doc_id: str,
    source_path: str, canonical_storage: str,
) -> None:
    """Best-effort SHA-256 registration during migration.

    Tries *source_path* first; falls back to hashing the ``.index`` file.
    """
    hash_target = None
    if source_path and os.path.isfile(source_path):
        hash_target = source_path
    else:
        # Fall back to .index file inside the canonical dir
        if os.path.isdir(canonical_storage):
            for fname in os.listdir(canonical_storage):
                if fname.endswith(".index"):
                    hash_target = os.path.join(canonical_storage, fname)
                    break
    if hash_target is None:
        return
    try:
        sha256 = compute_file_hash(hash_target)
        register_sha256(docs_folder, u_hash, sha256, doc_id)
    except Exception as exc:
        logger.debug("canonical_docs: SHA-256 registration failed for %s: %s", doc_id, exc)
