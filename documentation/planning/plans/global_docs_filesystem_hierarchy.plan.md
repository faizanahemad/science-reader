# Global Docs Filesystem Hierarchy Plan

## Goal

Currently global doc "folders" exist only in the DB (`GlobalDocFolders` table) — they have no
filesystem representation. Documents are stored flat under
`storage/global_docs/{md5(email)}/{doc_id}/` regardless of which folder they belong to.

This plan makes folders **real OS directories** so:

1. A folder named "Research" becomes `storage/global_docs/{md5(email)}/Research/`
2. A doc in "Research" lives at `storage/global_docs/{md5(email)}/Research/{doc_id}/`
3. Moving a doc between folders physically moves its directory on disk AND updates `GlobalDocuments.doc_storage`
4. The **Folder view** file browser opens rooted at `storage/global_docs/{md5(email)}/` (the user's own dir, not the server root)
5. Drag-drop in the file browser moves files on disk AND syncs to DB
6. Deleting a doc from the file browser removes the DB row too
7. The **List view** stays as a flat view of ALL docs regardless of folder — no change to its behavior

---

## What Is NOT Changing

- Base directory name: `storage/global_docs/` stays as-is
- List view: remains flat, shows all docs, filter bar/tag chips unaffected
- Tags system: DB-only, unaffected
- `#folder:Name` and `#tag:name` chat resolution: unaffected (still DB-based via `folder_id`)
- All existing file browser endpoints (`/file-browser/*`): no changes
- `GlobalDocFolders` table schema: unchanged
- `GlobalDocTags` table schema: unchanged

---

## Current State (Exact)

### Storage layout today
```
storage/
  global_docs/
    {md5(email)}/
      {doc_id}/           ← flat; no folder subdirs
        index.json
        chunks.pkl
        ...
```

### GlobalDocuments today
```
doc_id     | doc_storage                                         | folder_id
doc_abc123 | storage/global_docs/b15e624.../doc_abc123/         | <uuid>   ← folder not reflected in path
doc_def456 | storage/global_docs/b15e624.../doc_def456/         | NULL
```

### GlobalDocFolders today
```
folder_id | name      | parent_id
<uuid>    | Research  | NULL
<uuid2>   | Papers    | <uuid>
```
No OS directories exist for these folders.

### FileBrowserManager today (global-docs-manager.js line 380-382)
```javascript
var startPath = GlobalDocsManager._userHash
    ? 'storage/global_docs/' + GlobalDocsManager._userHash
    : 'storage/global_docs';
FileBrowserManager.open(startPath);
```
`_userHash` extraction regex (line 235):
```javascript
var match = storage.match(/storage\/global_docs\/([^\/]+)\//);
```
Both are already correct — no change needed.

### `onMove` callback today (lines 350-378)
Extracts `docId` from last path component, looks up folder by **name** in `_folderCache`,
calls `/doc_folders/{folderId}/assign` → DB only, no filesystem move.

---

## Target State

### Storage layout after
```
storage/
  global_docs/
    {md5(email)}/
      {doc_id}/           ← unassigned (root-level) docs
        index.json
        ...
      Research/           ← real OS directory for folder
        {doc_id}/         ← doc assigned to Research
          index.json
          ...
        Papers/           ← nested subfolder
          {doc_id}/
            index.json
            ...
```

### GlobalDocuments after
```
doc_id     | doc_storage                                                      | folder_id
doc_abc123 | storage/global_docs/b15e624.../Research/doc_abc123/             | <uuid>
doc_def456 | storage/global_docs/b15e624.../Research/Papers/doc_def456/      | <uuid2>
doc_ghi789 | storage/global_docs/b15e624.../doc_ghi789/                      | NULL
```

---

## Files to Modify

| File | Change |
|------|--------|
| `database/global_docs.py` | Add `update_doc_storage()` and `get_docs_in_fs_path()` helpers |
| `database/doc_folders.py` | Add `get_folder_fs_path()` helper |
| `endpoints/global_docs.py` | Upload/promote: place doc inside folder dir when `folder_id` given |
| `endpoints/doc_folders.py` | Create/rename/move/delete folder: mirror to OS dir; assign doc: physically move dir + update `doc_storage` |
| `interface/global-docs-manager.js` | `onMove` callback: let `/doc_folders/assign` handle physical move; add `onDelete` callback |
| `scripts/migrate_global_docs_to_fs_hierarchy.py` | New one-time migration script |

---

## Phase 0 — Helper Functions (Pure Additions, No Behavior Change)

These are pure additions that no existing code calls yet. Safe to add first.

### Task 0.1 — `get_folder_fs_path()` in `database/doc_folders.py`

Reconstructs the OS path of a folder by walking up the `parent_id` chain.

```python
def get_folder_fs_path(
    *, users_dir: str, user_email: str, folder_id: str, user_root: str
) -> Optional[str]:
    """
    Reconstruct the filesystem path of a folder by walking its parent_id chain.

    Parameters
    ----------
    users_dir : str
        Path to the users directory (for DB lookup).
    user_email : str
        User email for scoping.
    folder_id : str
        Target folder UUID.
    user_root : str
        Absolute path to the user's global docs root,
        e.g. /abs/path/to/storage/global_docs/{md5(email)}/

    Returns
    -------
    str or None
        Absolute OS path to the folder directory, e.g.
        /abs/path/to/storage/global_docs/{md5(email)}/Research/Papers/
        Returns None on cycle or missing folder.
    """
    path_parts = []
    current_id = folder_id
    visited = set()
    while current_id:
        if current_id in visited:
            logger.error(f"Cycle detected in folder hierarchy for {folder_id}")
            return None
        visited.add(current_id)
        folder = get_folder(users_dir=users_dir, user_email=user_email, folder_id=current_id)
        if folder is None:
            return None
        path_parts.append(folder["name"])
        current_id = folder.get("parent_id")
    path_parts.reverse()
    return os.path.join(user_root, *path_parts)
```

### Task 0.2 — `update_doc_storage()` in `database/global_docs.py`

Updates the `doc_storage` column after a physical filesystem move.

```python
def update_doc_storage(
    *, users_dir: str, user_email: str, doc_id: str, new_storage: str
) -> bool:
    """
    Update the doc_storage path for a global doc after a filesystem move.

    Returns True if a row was updated.
    """
    now = datetime.now().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE GlobalDocuments SET doc_storage=?, updated_at=? WHERE doc_id=? AND user_email=?",
            (new_storage, now, doc_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating doc_storage for {doc_id}: {e}")
        return False
    finally:
        conn.close()
```

### Task 0.3 — `get_docs_in_fs_path()` in `database/global_docs.py`

Used when a folder is renamed or moved to bulk-update all contained `doc_storage` paths.

```python
def get_docs_in_fs_path(
    *, users_dir: str, user_email: str, path_prefix: str
) -> list[dict]:
    """
    Return all docs whose doc_storage starts with path_prefix.
    Used after a folder rename/move to bulk-update doc_storage paths.

    Returns list of {doc_id, doc_storage} dicts.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, doc_storage FROM GlobalDocuments WHERE user_email=? AND doc_storage LIKE ?",
            (user_email, path_prefix.rstrip(os.sep) + os.sep + '%'),
        )
        return [{"doc_id": row[0], "doc_storage": row[1]} for row in cur.fetchall()]
    finally:
        conn.close()
```

---

## Phase 1 — Upload/Promote: Place Doc Inside Folder Dir

**Goal**: When a doc is uploaded or promoted with a `folder_id`, its indexed directory is created
inside the folder's OS path, not at the flat user root.

### Task 1.1 — Update `_ensure_user_global_dir()` in `endpoints/global_docs.py`

Current signature:
```python
def _ensure_user_global_dir(state, email: str) -> str:
```

New signature and body:

```python
def _ensure_user_global_dir(
    state, email: str, folder_id: Optional[str] = None
) -> str:
    """
    Return (and create if needed) the target storage directory for a new doc.

    If folder_id is provided and the folder's OS directory exists, returns that
    directory so the doc is indexed directly inside it.
    Falls back to the flat user root if folder_id is absent or dir is missing.

    Returns absolute path to the parent directory where doc_id subdir will be created.
    """
    user_root = os.path.join(state.global_docs_dir, _user_hash(email))
    os.makedirs(user_root, exist_ok=True)

    if folder_id:
        from database.doc_folders import get_folder_fs_path
        folder_path = get_folder_fs_path(
            users_dir=state.users_dir,
            user_email=email,
            folder_id=folder_id,
            user_root=user_root,
        )
        if folder_path:
            os.makedirs(folder_path, exist_ok=True)
            return folder_path

    return user_root
```

### Task 1.2 — Pass `folder_id` to `_ensure_user_global_dir()` in upload endpoint

In `upload_global_doc()`, extract `folder_id` from form/JSON **before** calling
`_ensure_user_global_dir`, and pass it:

```python
# File upload branch (around line 55):
folder_id = request.form.get('folder_id') or None
user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)

# URL upload branch (around line 102):
folder_id = (request.json.get('folder_id') if request.is_json and request.json else None) or \
            request.form.get('folder_id') or None
user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)
```

The `doc_index._storage` will then be `storage/global_docs/{hash}/{FolderName}/{doc_id}/`
when a folder is specified, matching the DB `doc_storage` value written by `add_global_doc()`.

### Task 1.3 — Pass `folder_id` to `_ensure_user_global_dir()` in promote endpoint

In `promote_doc_to_global()` (around line 300-301):
```python
# Replace:
user_storage = _ensure_user_global_dir(state, email)
# With:
folder_id = payload.get('folder_id') or None
user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)
```

The `target_storage = os.path.join(user_storage, doc_id)` line that follows remains unchanged —
it will now produce the correct path inside the folder dir.

---

## Phase 2 — Folder CRUD: Mirror to Filesystem

**Goal**: Every folder create/rename/move/delete operation also operates on the OS directory.

All changes are in `endpoints/doc_folders.py`. Each route needs access to `state.global_docs_dir`
and `_user_hash(email)` to build `user_root`. Add a helper at the top of the file:

```python
# Add near top of endpoints/doc_folders.py after imports:
import os
import shutil

def _user_root(state, email: str) -> str:
    """Absolute path to the user's global docs root directory."""
    from endpoints.global_docs import _user_hash
    return os.path.join(state.global_docs_dir, _user_hash(email))
```

### Task 2.1 — `create_folder_route()`: create OS directory

After the existing `create_folder()` DB call succeeds, create the directory:

```python
# After: folder_id = create_folder(users_dir=users_dir, user_email=email, name=name, parent_id=parent_id)
# Add:
if folder_id:
    state, _ = get_state_and_keys()
    from database.doc_folders import get_folder_fs_path
    user_root = _user_root(state, email)
    folder_path = get_folder_fs_path(
        users_dir=users_dir, user_email=email,
        folder_id=folder_id, user_root=user_root,
    )
    if folder_path:
        os.makedirs(folder_path, exist_ok=True)
```

**Folder name validation** — add before `create_folder()` call to prevent path-breaking chars:
```python
if '/' in name or '\\' in name or name in ('.', '..'):
    return json_error("Folder name may not contain path separators", 400)
```

### Task 2.2 — `update_folder_route()` (rename / reparent): rename OS directory

This is the most complex operation. Sequence:

1. Capture the **old** OS path before the DB update
2. Apply DB updates (existing `rename_folder` / `move_folder` calls)
3. Compute the **new** OS path after DB update
4. Rename the directory on disk
5. Bulk-update `doc_storage` for all docs that were inside it

```python
# At start of update_folder_route(), before existing DB calls:
state, _ = get_state_and_keys()
from database.doc_folders import get_folder_fs_path
from database.global_docs import get_docs_in_fs_path, update_doc_storage
user_root = _user_root(state, email)

old_folder_path = get_folder_fs_path(
    users_dir=users_dir, user_email=email,
    folder_id=folder_id, user_root=user_root,
)

# ... existing rename_folder / move_folder DB calls ...

# After DB calls:
new_folder_path = get_folder_fs_path(
    users_dir=users_dir, user_email=email,
    folder_id=folder_id, user_root=user_root,
)

if old_folder_path and new_folder_path and old_folder_path != new_folder_path:
    if os.path.isdir(old_folder_path):
        os.makedirs(os.path.dirname(new_folder_path), exist_ok=True)
        os.rename(old_folder_path, new_folder_path)

    # Bulk-update doc_storage paths for all docs that were in the old folder
    affected = get_docs_in_fs_path(
        users_dir=users_dir, user_email=email, path_prefix=old_folder_path
    )
    for doc in affected:
        new_doc_storage = doc["doc_storage"].replace(old_folder_path, new_folder_path, 1)
        update_doc_storage(
            users_dir=users_dir, user_email=email,
            doc_id=doc["doc_id"], new_storage=new_doc_storage,
        )
```

### Task 2.3 — `assign_doc_route()`: physically move doc dir + update `doc_storage`

The assign route must move the doc's OS directory to the target folder and update `doc_storage`.
Do this **before** the existing `assign_doc_to_folder()` DB call.

```python
# Add before existing assign_doc_to_folder() call in assign_doc_route():
import os
from database.global_docs import get_global_doc, update_doc_storage
from database.doc_folders import get_folder_fs_path

state, _ = get_state_and_keys()
user_root = _user_root(state, email)

doc_row = get_global_doc(users_dir=users_dir, user_email=email, doc_id=doc_id)
if doc_row is None:
    return json_error("Document not found", 404)

old_storage = doc_row.get("doc_storage", "")

if target_folder_id is None:
    # Moving to root (unfile)
    new_storage = os.path.join(user_root, doc_id)
else:
    folder_path = get_folder_fs_path(
        users_dir=users_dir, user_email=email,
        folder_id=target_folder_id, user_root=user_root,
    )
    if not folder_path:
        return json_error("Could not resolve folder filesystem path", 500)
    os.makedirs(folder_path, exist_ok=True)
    new_storage = os.path.join(folder_path, doc_id)

if old_storage and new_storage and old_storage != new_storage and os.path.isdir(old_storage):
    os.makedirs(os.path.dirname(new_storage), exist_ok=True)
    os.rename(old_storage, new_storage)
    update_doc_storage(
        users_dir=users_dir, user_email=email,
        doc_id=doc_id, new_storage=new_storage,
    )

# Existing DB call follows unchanged:
assign_doc_to_folder(
    users_dir=users_dir, user_email=email, doc_id=doc_id, folder_id=target_folder_id
)
```

### Task 2.4 — `delete_folder_route()`, `move_to_parent` action: physically move doc dirs

Currently the `move_to_parent` action only updates `folder_id` in DB. We must also
move each doc's OS directory to the parent folder path.

```python
# In the move_to_parent branch, replace the doc loop with:
parent_path = (
    get_folder_fs_path(
        users_dir=users_dir, user_email=email,
        folder_id=parent_id, user_root=user_root,
    )
    if parent_id else user_root
)

direct_doc_ids = get_docs_in_folder(
    users_dir=users_dir, user_email=email, folder_id=folder_id, recursive=False
)
for doc_id in direct_doc_ids:
    doc_row = get_global_doc(users_dir=users_dir, user_email=email, doc_id=doc_id)
    if doc_row:
        old_storage = doc_row.get("doc_storage", "")
        new_storage = os.path.join(parent_path, doc_id)
        if old_storage and old_storage != new_storage and os.path.isdir(old_storage):
            os.makedirs(parent_path, exist_ok=True)
            os.rename(old_storage, new_storage)
            update_doc_storage(
                users_dir=users_dir, user_email=email,
                doc_id=doc_id, new_storage=new_storage,
            )
    assign_doc_to_folder(
        users_dir=users_dir, user_email=email,
        doc_id=doc_id, folder_id=parent_id,
    )
```

### Task 2.5 — `delete_folder_route()`: remove OS directory after DB delete

After `delete_folder()` DB call at the end of the route:

```python
# After delete_folder() call, add:
folder_path = get_folder_fs_path(
    users_dir=users_dir, user_email=email,
    folder_id=folder_id, user_root=user_root,
)
# By this point all docs have been moved/deleted, so the dir should be empty
if folder_path and os.path.isdir(folder_path):
    try:
        os.rmdir(folder_path)  # Non-recursive: safe, will fail if non-empty
    except OSError:
        logger.warning("Could not rmdir folder %s — may not be empty", folder_path)
```

**Note for `delete_docs` action**: when `action=delete_docs`, the existing loop calls
`delete_global_doc()` (DB only). The delete endpoint (`delete_global_doc_route`) calls
`shutil.rmtree(doc_storage)` on the already-correct path — so doc dirs ARE removed.
No change needed there. After all docs are deleted the folder dir will be empty and
`os.rmdir` above will succeed.

---

## Phase 3 — File Browser: Correct Root + DB Sync on Move/Delete

### Task 3.1 — `onMove` callback: no change needed to calling code

After Phase 2 Task 2.3, `assign_doc_route()` handles both the physical OS move AND the
DB update atomically. The existing `onMove` callback already calls `/doc_folders/{folderId}/assign`.
**No change required** to the callback JS logic — it already does the right thing.

The only subtle point: the file browser will show the actual filesystem tree, and after a
drag-drop it calls `onMove(srcPath, destPath, done)`. The `srcPath` will be something like
`storage/global_docs/{hash}/Research/doc_abc123` and `destPath` like
`storage/global_docs/{hash}/Papers/doc_abc123`. The callback correctly extracts `docId`
(last segment) and `parentName` (second-to-last segment), looks up `folder_id` from
`_folderCache`, and calls `/doc_folders/{folderId}/assign` — which now does the physical move.

**One gap to fix**: if a user drags a doc to the user root (no parent folder), `parentName` will
be `{hash}` (the hash segment), which won't match any folder in `_folderCache`, so `folderId`
falls back to `'root'`. That is already correct behavior (unfile the doc). ✓

### Task 3.2 — Add `onDelete` callback in `global-docs-manager.js`

When a doc directory is deleted from the file browser, we must also remove the DB row.
Add `onDelete` to the `FileBrowserManager.configure({...})` call (alongside the existing `onMove`):

```javascript
FileBrowserManager.configure({
    onMove: function(srcPath, destPath, done) {
        // ... existing onMove code unchanged ...
    },
    onDelete: function(path, done) {
        // path: e.g. "storage/global_docs/{hash}/Research/doc_abc123"
        // or a folder: "storage/global_docs/{hash}/Research"
        var parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
        var last = parts[parts.length - 1];

        // Heuristic: if last segment looks like a doc_id (≥8 chars, no spaces),
        // try to delete it via the global docs API (handles DB + FS together).
        // If it's a folder or unknown, fall back to /file-browser/delete.
        if (last && last.length >= 8 && last.indexOf(' ') === -1) {
            $.ajax({
                url: '/global_docs/' + last,
                method: 'DELETE',
                success: function(r) {
                    GlobalDocsManager.refresh();
                    done(r.status === 'ok' ? null : (r.error || 'Delete failed'));
                },
                error: function(xhr) {
                    if (xhr.status === 404) {
                        // Not a known doc — fall back to plain filesystem delete
                        _fallbackFsDelete(path, done);
                    } else {
                        var msg = 'Delete failed';
                        try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                        done(msg);
                    }
                }
            });
        } else {
            // It's a folder or unrecognized path — plain filesystem delete
            _fallbackFsDelete(path, done);
        }

        function _fallbackFsDelete(p, cb) {
            $.ajax({
                url: '/file-browser/delete',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ path: p, recursive: true }),
                success: function() { cb(null); },
                error: function() { cb('Delete failed'); }
            });
        }
    }
});
```

**Why this is safe**: The `onDelete` override replaces the file browser's default delete behavior
entirely. For docs it calls `/global_docs/<doc_id>` DELETE which runs `shutil.rmtree(doc_storage)`
AND deletes the DB row — no double-delete. For folders it calls `/file-browser/delete` directly.

---

## Phase 4 — One-Time Migration Script

Moves existing flat docs into their correct folder subdirectories and updates `doc_storage` in DB.

**File**: `scripts/migrate_global_docs_to_fs_hierarchy.py` (new)

```
Usage:
  conda activate science-reader
  python scripts/migrate_global_docs_to_fs_hierarchy.py --dry-run   # preview
  python scripts/migrate_global_docs_to_fs_hierarchy.py             # execute
```

### Script outline

```python
#!/usr/bin/env python3
"""
One-time migration: gives each GlobalDocFolders entry a real OS directory,
then moves existing docs from flat storage into their folder subdirectories.
Updates GlobalDocuments.doc_storage for every moved doc.

Run dry-run first to verify, then run live.
"""
import argparse, hashlib, os, shutil, sqlite3, json, sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLOBAL_DOCS_DIR = os.path.join(PROJECT_ROOT, "storage", "global_docs")
USERS_DB = os.path.join(PROJECT_ROOT, "storage", "users", "users.db")


def md5(s): return hashlib.md5(s.encode()).hexdigest()


def folder_path_parts(conn, user_email, folder_id):
    """Walk parent_id chain bottom-up; return ordered name list root→leaf."""
    parts, current, visited = [], folder_id, set()
    while current:
        if current in visited:
            print(f"  WARN: cycle at {current}")
            break
        visited.add(current)
        row = conn.execute(
            "SELECT name, parent_id FROM GlobalDocFolders WHERE folder_id=? AND user_email=?",
            (current, user_email)
        ).fetchone()
        if not row: break
        parts.append(row[0]); current = row[1]
    parts.reverse()
    return parts


def migrate(dry_run):
    print(f"=== Migration {'DRY RUN' if dry_run else 'LIVE'} ===\n")
    conn = sqlite3.connect(USERS_DB)

    # --- Step 1: create folder OS directories ---
    print("Step 1: Creating folder OS directories...")
    for folder_id, user_email in conn.execute(
        "SELECT folder_id, user_email FROM GlobalDocFolders"
    ).fetchall():
        user_root = os.path.join(GLOBAL_DOCS_DIR, md5(user_email))
        parts = folder_path_parts(conn, user_email, folder_id)
        fdir = os.path.join(user_root, *parts)
        if not os.path.exists(fdir):
            print(f"  mkdir: {fdir}")
            if not dry_run: os.makedirs(fdir, exist_ok=True)
        else:
            print(f"  exists: {fdir}")
    print()

    # --- Step 2: move docs into their folder dirs ---
    print("Step 2: Moving docs into folder directories...")
    docs = conn.execute(
        "SELECT doc_id, user_email, doc_storage, folder_id FROM GlobalDocuments"
    ).fetchall()
    print(f"  {len(docs)} docs total\n")

    updates, errors = [], 0
    for doc_id, user_email, old_storage, folder_id in docs:
        user_root = os.path.join(GLOBAL_DOCS_DIR, md5(user_email))
        if folder_id:
            parts = folder_path_parts(conn, user_email, folder_id)
            new_storage = os.path.join(user_root, *parts, doc_id)
        else:
            new_storage = os.path.join(user_root, doc_id)

        if old_storage == new_storage:
            print(f"  [SKIP] {doc_id[:8]}  already in correct location")
            continue

        if not os.path.isdir(old_storage):
            print(f"  [MISS] {doc_id[:8]}  old_storage not found: {old_storage}")
            continue

        if os.path.exists(new_storage):
            print(f"  [SKIP] {doc_id[:8]}  new_storage already exists: {new_storage}")
            continue

        print(f"  [MOVE] {doc_id[:8]}")
        print(f"         {old_storage}")
        print(f"      -> {new_storage}")

        if not dry_run:
            try:
                os.makedirs(os.path.dirname(new_storage), exist_ok=True)
                shutil.copytree(old_storage, new_storage)
                # Patch _storage in index.json if present
                idx = os.path.join(new_storage, "index.json")
                if os.path.exists(idx):
                    with open(idx) as f: data = json.load(f)
                    if "_storage" in data:
                        data["_storage"] = new_storage
                        with open(idx, "w") as f: json.dump(data, f, indent=2)
                updates.append((doc_id, user_email, new_storage))
            except Exception as e:
                print(f"  [ERR]  {e}"); errors += 1
        else:
            updates.append((doc_id, user_email, new_storage))
    print()

    # --- Step 3: update DB ---
    if updates:
        print(f"Step 3: Updating {len(updates)} doc_storage paths in DB...")
        if not dry_run:
            now = datetime.now().isoformat()
            for doc_id, user_email, new_storage in updates:
                conn.execute(
                    "UPDATE GlobalDocuments SET doc_storage=?, updated_at=? "
                    "WHERE doc_id=? AND user_email=?",
                    (new_storage, now, doc_id, user_email),
                )
            conn.commit()
            print("  DB updated.")
        else:
            print("  DRY RUN: would update DB.")
    else:
        print("Step 3: No DB updates needed.")

    conn.close()
    print(f"\nDone. {len(updates)} moved, {errors} errors.")
    if not dry_run and updates:
        print("Old flat dirs remain — delete manually after verifying new paths work.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    migrate(p.parse_args().dry_run)
```

---

## Implementation Order

Run phases in this sequence to minimize risk and allow rollback at each step:

1. **Phase 0** — Add helper functions. Pure additions, zero behavior change.
2. **Phase 4** — Run migration script dry-run, then live. Existing flat docs moved into folder
   dirs. All new behavior depends on this being done first.
3. **Phase 1** — Upload/promote places new docs in folder dirs from now on.
4. **Phase 2** — Folder CRUD mirrors to filesystem.
5. **Phase 3** — File browser wired up (onDelete). `onMove` already works via Phase 2.

---

## Risk Analysis

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Folder name with `/`, `\`, or `..` breaks path construction | Medium | Validate in `create_folder_route()` before DB insert |
| Duplicate folder names at same level (allowed by DB, disallowed by FS) | Low | Filesystem `os.makedirs` will fail silently with `exist_ok=True`; add a DB unique constraint on `(user_email, parent_id, name)` as a follow-up |
| `os.rename()` fails across filesystems (e.g. different mounts) | Very Low | All storage is under one `storage/` dir on same volume; use `shutil.move()` as fallback |
| `get_docs_in_fs_path()` LIKE query too broad if path_prefix has SQL wildcards | Low | Escape `%` and `_` in path_prefix before passing to LIKE |
| Migration copies (not moves) — old dirs remain and waste disk | Intentional | Manual cleanup after verification; add `--delete-old` flag to script as follow-up |
| `onDelete` heuristic misidentifies a folder named with 8+ chars as a doc | Low | `/global_docs/<id>` DELETE returns 404 if not in DB → falls back to fs delete |
| Cycle in folder parent_id chain | Very Low | `get_folder_fs_path()` detects and returns None; callers check for None |
| Race: two requests assign same doc simultaneously | Very Low | SQLite serializes writes; `os.rename` is atomic on same fs |

---

## Summary of All Code Changes

### `database/global_docs.py` — add 2 functions
- `update_doc_storage(users_dir, user_email, doc_id, new_storage) -> bool`
- `get_docs_in_fs_path(users_dir, user_email, path_prefix) -> list[dict]`

### `database/doc_folders.py` — add 1 function
- `get_folder_fs_path(users_dir, user_email, folder_id, user_root) -> Optional[str]`

### `endpoints/global_docs.py` — modify 1 function
- `_ensure_user_global_dir(state, email, folder_id=None)` — accepts optional `folder_id`, returns folder dir path

### `endpoints/doc_folders.py` — modify 4 routes + add 1 helper
- Add `_user_root(state, email) -> str` helper at top
- `create_folder_route()` — after DB insert, `os.makedirs(folder_path)`
- `update_folder_route()` — capture old path, rename dir, bulk-update `doc_storage`
- `assign_doc_route()` — `os.rename(old, new)` + `update_doc_storage()` before existing `assign_doc_to_folder()` call
- `delete_folder_route()` — move doc dirs in `move_to_parent` action; `os.rmdir` after DB delete

### `interface/global-docs-manager.js` — modify 1 section
- Add `onDelete` handler in the `FileBrowserManager.configure({...})` call

### `scripts/migrate_global_docs_to_fs_hierarchy.py` — new file
- Step 1: create OS dirs for all GlobalDocFolders rows
- Step 2: copy docs into folder subdirs
- Step 3: update `doc_storage` in DB
