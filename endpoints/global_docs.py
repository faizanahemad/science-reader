"""
Global document endpoints.

Provides CRUD operations for user-scoped global documents that can be
referenced from any conversation via #gdoc_N / #global_doc_N syntax.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from flask import Blueprint, Response, jsonify, redirect, request, send_from_directory, session, stream_with_context
from typing import Optional

from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
from endpoints.responses import json_error
from extensions import limiter

from database.global_docs import (
    add_global_doc,
    delete_global_doc,
    get_global_doc,
    list_global_docs,
    replace_global_doc,
    update_global_doc_metadata,
)
from database.doc_tags import set_tags as _set_tags, list_all_tags as _list_all_tags


global_docs_bp = Blueprint("global_docs", __name__)
logger = logging.getLogger(__name__)

# In-memory task tracker for background doc replacements.  Keyed by task_id.
_REPLACE_TASKS: dict = {}

def _user_hash(email: str) -> str:
    return hashlib.md5(email.encode()).hexdigest()


def _ensure_user_global_dir(state, email: str, folder_id: Optional[str] = None) -> str:
    """
    Return (and create if needed) the target storage directory for a new doc.

    If folder_id is provided and the folder exists in DB, returns that folder's
    OS directory path so the doc is indexed directly inside it.
    Falls back to the flat user root if folder_id is absent or cannot be resolved.

    Parameters
    ----------
    state : AppState
        Application state with global_docs_dir and users_dir attributes.
    email : str
        User email address.
    folder_id : str, optional
        UUID of the target folder. If provided, doc will be stored inside
        the folder's OS directory.

    Returns
    -------
    str
        Absolute path to the parent directory where doc_id subdir will be created.
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


@global_docs_bp.route("/global_docs/upload", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def upload_global_doc():
    state, keys = get_state_and_keys()
    email = session.get("email", "")



    pdf_file = request.files.get("pdf_file")
    display_name = ""

    if pdf_file:
        try:
            pdf_file.save(os.path.join(state.pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)

            if request.form:
                display_name = request.form.get("display_name", "")

            # Read metadata fields from form
            priority = int(request.form.get('priority', 3) or 3)
            date_written = request.form.get('date_written') or None
            deprecated = request.form.get('deprecated', '').lower() in ('true', '1', 'yes')

            folder_id = request.form.get('folder_id') or None
            user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)

            from DocIndex import create_immediate_document_index

            doc_index = create_immediate_document_index(
                full_pdf_path, user_storage, keys
            )
            doc_index.save_local()

            short_info = doc_index.get_short_info()
            add_global_doc(
                users_dir=state.users_dir,
                user_email=email,
                doc_id=doc_index.doc_id,
                doc_source=full_pdf_path,
                doc_storage=doc_index._storage,
                title=short_info.get("title", ""),
                short_summary=short_info.get("short_summary", ""),
                display_name=display_name,
                folder_id=request.form.get('folder_id') or None,
                priority=priority,
                date_written=date_written,
                deprecated=deprecated,
            )
            # Set metadata on DocIndex as well
            doc_index._priority = priority
            doc_index._date_written = date_written or datetime.now().strftime('%Y-%m-%d')
            doc_index._deprecated = deprecated
            doc_index.save_local()
            # Set tags if provided (comma-separated string from form)
            tags_raw = request.form.get('tags', '').strip()
            if tags_raw:
                tag_list = [t.strip().lower() for t in tags_raw.split(',') if t.strip()]
                if tag_list:
                    _set_tags(
                        users_dir=state.users_dir,
                        user_email=email,
                        doc_id=doc_index.doc_id,
                        tags=tag_list,
                    )
            return jsonify({"status": "ok", "doc_id": doc_index.doc_id})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    pdf_url = None
    if request.is_json and request.json:
        pdf_url = request.json.get("pdf_url")
        display_name = request.json.get("display_name", "")

    if pdf_url:
        from common import convert_to_pdf_link_if_needed

        pdf_url = convert_to_pdf_link_if_needed(pdf_url)

    if pdf_url:
        try:
            from DocIndex import create_immediate_document_index

            folder_id = request.form.get('folder_id') or (request.json.get('folder_id') if request.is_json and request.json else None)
            user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)

            doc_index = create_immediate_document_index(pdf_url, user_storage, keys)
            doc_index.save_local()

            short_info = doc_index.get_short_info()
            # Read metadata from form or JSON
            priority = int((request.form.get('priority') or (request.json.get('priority') if request.is_json and request.json else None)) or 3)
            date_written = (request.form.get('date_written') or (request.json.get('date_written') if request.is_json and request.json else None)) or None
            deprecated = str(request.form.get('deprecated') or (request.json.get('deprecated') if request.is_json and request.json else '')).lower() in ('true', '1', 'yes')
            add_global_doc(
                users_dir=state.users_dir,
                user_email=email,
                doc_id=doc_index.doc_id,
                doc_source=pdf_url,
                doc_storage=doc_index._storage,
                title=short_info.get("title", ""),
                short_summary=short_info.get("short_summary", ""),
                display_name=display_name,
                folder_id=request.form.get('folder_id') or (request.json.get('folder_id') if request.is_json and request.json else None),
                priority=priority,
                date_written=date_written,
                deprecated=deprecated,
            )
            # Set metadata on DocIndex
            doc_index._priority = priority
            doc_index._date_written = date_written or datetime.now().strftime('%Y-%m-%d')
            doc_index._deprecated = deprecated
            doc_index.save_local()
            # Set tags if provided (comma-separated form field or JSON array)
            tags_raw = request.form.get('tags', '').strip()
            if not tags_raw and request.is_json and request.json:
                tags_raw = ','.join(request.json.get('tags', []))
            if tags_raw:
                tag_list = [t.strip().lower() for t in tags_raw.split(',') if t.strip()]
                if tag_list:
                    _set_tags(
                        users_dir=state.users_dir,
                        user_email=email,
                        doc_id=doc_index.doc_id,
                        tags=tag_list,
                    )
            return jsonify({"status": "ok", "doc_id": doc_index.doc_id})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    return json_error("No pdf_url or pdf_file provided", status=400, code="bad_request")


@global_docs_bp.route("/global_docs/list", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_global_docs_route():
    state, _keys = get_state_and_keys()
    email = session.get("email", "")

    docs = list_global_docs(users_dir=state.users_dir, user_email=email)
    result = []
    for idx, doc in enumerate(docs, start=1):
        result.append(
            {
                "index": idx,
                "doc_id": doc["doc_id"],
                "display_name": doc["display_name"] or "",
                "title": doc["title"] or "",
                "short_summary": doc["short_summary"] or "",
                "source": doc["doc_source"],
                "doc_source": doc["doc_source"],
                "created_at": doc["created_at"] or "",
                "tags": doc.get("tags") or [],
                "folder_id": doc.get("folder_id"),
                "priority": doc.get("priority", 3),
                "priority_label": doc.get("priority_label", "medium"),
                "date_written": doc.get("date_written"),
                "deprecated": doc.get("deprecated", False),
            }
        )
    return jsonify(result)


@global_docs_bp.route("/global_docs/info/<doc_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_global_doc_info(doc_id: str):
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row is None:
        return json_error("Global doc not found", status=404, code="not_found")

    result = {
        "doc_id": doc_row["doc_id"],
        "display_name": doc_row["display_name"] or "",
        "title": doc_row["title"] or "",
        "short_summary": doc_row["short_summary"] or "",
        "source": doc_row["doc_source"],
        "created_at": doc_row["created_at"] or "",
        "priority": doc_row.get("priority", 3),
        "priority_label": doc_row.get("priority_label", "medium"),
        "date_written": doc_row.get("date_written"),
        "deprecated": doc_row.get("deprecated", False),
    }

    try:
        from DocIndex import DocIndex

        doc_index = DocIndex.load_local(doc_row["doc_storage"])
        if doc_index is not None:
            short_info = doc_index.get_short_info()
            result["doc_type"] = getattr(doc_index, "doc_type", "")
            result["doc_filetype"] = getattr(doc_index, "doc_filetype", "")
            result["visible"] = short_info.get("visible", False)
    except Exception:
        pass

    return jsonify(result)



@global_docs_bp.route("/global_docs/<doc_id>/metadata", methods=["PATCH"])
@limiter.limit("60 per minute")
@login_required
def update_global_doc_metadata_route(doc_id: str):
    """Update priority, date_written, deprecated (and existing fields) for a global doc."""
    state, _keys = get_state_and_keys()
    email = session.get("email", "")
    data = request.json or {}

    priority = data.get("priority")
    display_name = data.get("display_name")
    date_written = data.get("date_written")
    deprecated = data.get("deprecated")

    if priority is not None:
        priority = max(1, min(5, int(priority)))
    if deprecated is not None:
        deprecated = bool(deprecated)

    update_global_doc_metadata(
        users_dir=state.users_dir, user_email=email, doc_id=doc_id,
        priority=priority, date_written=date_written, deprecated=deprecated,
        title=data.get("title"), short_summary=data.get("short_summary"),
        display_name=data.get("display_name"),
    )

    # Also update the DocIndex on disk
    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row and doc_row.get("doc_storage"):
        try:
            from DocIndex import DocIndex
            doc_index = DocIndex.load_local(doc_row["doc_storage"])
            if doc_index:
                if priority is not None:
                    doc_index._priority = priority
                if date_written is not None:
                    doc_index._date_written = date_written
                if deprecated is not None:
                    doc_index._deprecated = deprecated
                if display_name is not None:
                    doc_index._display_name = display_name if display_name else None
                doc_index.save_local()
        except Exception:
            pass

    return jsonify({"status": "ok"})
@global_docs_bp.route("/global_docs/download/<doc_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def download_global_doc(doc_id: str):
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row is None:
        return json_error("Global doc not found", status=404, code="not_found")

    doc_source = doc_row["doc_source"]

    # Try the DB-stored source path first
    if doc_source and os.path.exists(doc_source):
        file_dir, file_name = os.path.split(doc_source)
        if os.path.dirname(__file__).strip() != "":
            root_dir = os.path.dirname(__file__) + "/"
            file_dir = file_dir.replace(root_dir, "")
        return send_from_directory(file_dir, file_name)

    # Fallback: load the DocIndex to get the actual doc_source (may differ
    # from the DB value after promote/copy operations)
    doc_storage = doc_row.get("doc_storage", "")
    if doc_storage:
        try:
            from DocIndex import DocIndex

            doc_index = DocIndex.load_local(doc_storage)
            if doc_index is not None:
                actual_source = getattr(doc_index, "doc_source", "")
                if actual_source and os.path.exists(actual_source):
                    file_dir, file_name = os.path.split(actual_source)
                    if os.path.dirname(__file__).strip() != "":
                        root_dir = os.path.dirname(__file__) + "/"
                        file_dir = file_dir.replace(root_dir, "")
                    return send_from_directory(file_dir, file_name)
        except Exception:
            pass

    if doc_source:
        return redirect(doc_source)

    return json_error("Document source not found", status=404, code="not_found")


@global_docs_bp.route("/global_docs/serve", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def serve_global_doc():
    """Query-param wrapper around download_global_doc so that showPDF() in the
    UI can use ``/global_docs/serve`` as the *url* argument and pass the doc_id
    as the ``file`` query parameter:  ``showPDF(docId, ..., '/global_docs/serve')``.
    """
    doc_id = request.args.get("file", "")
    if not doc_id:
        return json_error("Missing file parameter", status=400, code="bad_request")
    return download_global_doc(doc_id)


@global_docs_bp.route("/global_docs/<doc_id>", methods=["DELETE"])
@limiter.limit("100 per minute")
@login_required
def delete_global_doc_route(doc_id: str):
    state, _keys = get_state_and_keys()
    email = session.get("email", "")

    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row is None:
        return json_error("Global doc not found", status=404, code="not_found")

    delete_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)

    doc_storage = doc_row.get("doc_storage", "")
    if doc_storage and os.path.isdir(doc_storage):
        shutil.rmtree(doc_storage, ignore_errors=True)

    return jsonify({"status": "ok"})


@global_docs_bp.route(
    "/global_docs/promote/<conversation_id>/<doc_id>", methods=["POST"]
)
@limiter.limit("100 per minute")
@login_required
def promote_doc_to_global(conversation_id: str, doc_id: str):
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    conversation = attach_keys(state.conversation_cache[conversation_id], keys)
    if conversation is None:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    doc_list = conversation.get_field("uploaded_documents_list") or []
    source_entry = None
    for entry in doc_list:
        if entry[0] == doc_id:
            source_entry = entry
            break

    if source_entry is None:
        return json_error(
            "Document not found in conversation", status=404, code="not_found"
        )

    _entry_doc_id, source_storage, pdf_url = source_entry

    payload = request.get_json(silent=True) or {}
    folder_id = payload.get('folder_id') or None
    user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)
    target_storage = os.path.join(user_storage, doc_id)

    try:
        import canonical_docs as _canonical_docs

        # Determine if source is in the canonical store (shared across conversations).
        # If it is, we must NOT delete the source after promoting — other conversations
        # may still reference it.
        source_is_canonical = (
            hasattr(state, 'docs_folder') and
            _canonical_docs.is_canonical_path(state.docs_folder, source_storage)
        )

        if os.path.exists(target_storage):
            shutil.rmtree(target_storage)
        shutil.copytree(source_storage, target_storage)

        from DocIndex import DocIndex

        doc_index = DocIndex.load_local(target_storage)
        if doc_index is None:
            shutil.rmtree(target_storage, ignore_errors=True)
            return json_error(
                "Failed to verify copied document", status=500, code="verify_failed"
            )

        # If it was a fast index, upgrade to full index now for global quality
        is_fast = getattr(doc_index, '_is_fast_index', False)
        if is_fast:
            from DocIndex import create_immediate_document_index
            keys = get_state_and_keys()[1]
            upgraded = create_immediate_document_index(pdf_url, _ensure_user_global_dir(state, email, folder_id=folder_id), keys)
            if upgraded is not None:
                shutil.rmtree(target_storage, ignore_errors=True)
                shutil.copytree(upgraded._storage, target_storage)
                doc_index = DocIndex.load_local(target_storage)
                if doc_index is None:
                    return json_error("Failed to upgrade index", status=500, code="upgrade_failed")

        doc_index._storage = target_storage
        doc_index.save_local()

        short_info = doc_index.get_short_info()
        index_type = 'fast' if getattr(doc_index, '_is_fast_index', False) else 'full'

        priority = getattr(doc_index, "_priority", 3)
        date_written = getattr(doc_index, "_date_written", None)
        deprecated = getattr(doc_index, "_deprecated", False)
        add_global_doc(
            users_dir=state.users_dir,
            user_email=email,
            doc_id=doc_id,
            doc_source=pdf_url,
            doc_storage=target_storage,
            title=short_info.get("title", ""),
            short_summary=short_info.get("short_summary", ""),
            folder_id=folder_id,
            index_type=index_type,
            priority=priority,
            date_written=date_written,
            deprecated=deprecated,
        )

        new_doc_list = [e for e in doc_list if e[0] != doc_id]
        conversation.set_field("uploaded_documents_list", new_doc_list, overwrite=True)

        remaining_docs = conversation.get_uploaded_documents()
        doc_infos = "\n".join(
            [
                conversation._format_doc_info_line(i, d)
                for i, d in enumerate(remaining_docs)
            ]
        )
        conversation.doc_infos = doc_infos

        # Only delete source if it is NOT in the canonical store
        # (canonical paths are shared across conversations and must not be removed).
        if not source_is_canonical:
            shutil.rmtree(source_storage, ignore_errors=True)
        conversation.save_local()

        return jsonify({"status": "ok", "doc_id": doc_id})
    except Exception as e:
        traceback.print_exc()
        if os.path.exists(target_storage) and not os.path.exists(source_storage):
            pass
        return json_error(str(e), status=500, code="promote_failed")


@global_docs_bp.route("/global_docs/<doc_id>/tags", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def set_doc_tags(doc_id: str):
    """Set tags for a global doc. Body: {tags: ["ai", "ml"]}. Replaces all existing tags."""
    state, keys = get_state_and_keys()
    email = session.get("email", "")
    users_dir = state.users_dir if state else None
    if not email or not users_dir:
        return json_error("Not authenticated", 401)
    data = request.get_json(force=True) or {}
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return json_error("tags must be a list", 400)
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]
    _set_tags(users_dir=users_dir, user_email=email, doc_id=doc_id, tags=tags)
    return jsonify({"status": "ok", "tags": tags})


@global_docs_bp.route("/global_docs/tags", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_all_doc_tags():
    """List all distinct tags for the user. ?prefix= for filtering."""
    state, keys = get_state_and_keys()
    email = session.get("email", "")
    users_dir = state.users_dir if state else None
    if not email or not users_dir:
        return json_error("Not authenticated", 401)
    prefix = request.args.get("prefix", "").lower()
    tags = _list_all_tags(users_dir=users_dir, user_email=email)
    if prefix:
        tags = [t for t in tags if t.lower().startswith(prefix)]
    return jsonify({"status": "ok", "tags": tags})


@global_docs_bp.route("/global_docs/autocomplete", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def global_docs_autocomplete():
    """Combined autocomplete for #folder:Name and #tag:name in chat input.
    ?type=folder&prefix=Re or ?type=tag&prefix=ml"""
    state, keys = get_state_and_keys()
    email = session.get("email", "")
    users_dir = state.users_dir if state else None
    if not email or not users_dir:
        return json_error("Not authenticated", 401)
    ref_type = request.args.get("type", "tag")
    prefix = request.args.get("prefix", "").lower()
    if ref_type == "folder":
        from database.doc_folders import list_folders as _list_folders
        folders = _list_folders(users_dir=users_dir, user_email=email)
        results = [f["name"] for f in folders if not prefix or f["name"].lower().startswith(prefix)]
        return jsonify({"status": "ok", "folders": results})
    else:
        tags = _list_all_tags(users_dir=users_dir, user_email=email)
        if prefix:
            tags = [t for t in tags if t.lower().startswith(prefix)]
        return jsonify({"status": "ok", "tags": tags})


# ---------------------------------------------------------------------------
# Document replacement endpoints
# ---------------------------------------------------------------------------


@global_docs_bp.route("/global_docs/<doc_id>/replace", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def replace_global_doc_route(doc_id: str):
    """Replace a global document's source file and re-index."""
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row is None:
        return json_error("Global doc not found", status=404, code="not_found")

    pdf_file = request.files.get("pdf_file")
    if not pdf_file:
        return json_error("No file provided", status=400, code="bad_request")

    full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
    pdf_file.save(full_pdf_path)

    display_name = (request.form.get("display_name") or "").strip() or None

    task_id = str(uuid.uuid4())
    _REPLACE_TASKS[task_id] = {
        "status": "running",
        "phase": "queued",
        "message": "Starting replacement\u2026",
        "doc_id": doc_id,
    }

    t = threading.Thread(
        target=_run_replace_global,
        args=(task_id, doc_id, doc_row, full_pdf_path,
              display_name, email, keys, state),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started", "task_id": task_id}), 202


def _run_replace_global(
    task_id, old_doc_id, doc_row, new_source_path,
    display_name, email, keys, state,
):
    """Background thread: create new index, update DB, clean up old."""
    task = _REPLACE_TASKS[task_id]

    def _progress(phase, message):
        task["phase"] = phase
        task["message"] = message

    try:
        from code_common.documents import create_immediate_document_index
        import shutil as _shutil

        _progress("reading", "Extracting text from new document\u2026")

        old_doc_storage = doc_row.get("doc_storage", "")
        folder_id = doc_row.get("folder_id")
        user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)

        new_doc_index = create_immediate_document_index(
            new_source_path, user_storage, keys, progress_callback=_progress
        )

        if new_doc_index is None:
            raise RuntimeError("Failed to create document index from new file")

        # Preserve user-set metadata from old doc
        new_doc_index._priority = doc_row.get("priority", 3)
        new_doc_index._date_written = doc_row.get("date_written")
        new_doc_index._deprecated = bool(doc_row.get("deprecated", 0))
        new_doc_index._display_name = display_name or doc_row.get("display_name")
        new_doc_index.save_local()

        _progress("saving", "Updating database\u2026")

        new_doc_id = new_doc_index.doc_id
        short_info = new_doc_index.get_short_info()

        replace_global_doc(
            users_dir=state.users_dir,
            user_email=email,
            old_doc_id=old_doc_id,
            new_doc_id=new_doc_id,
            new_doc_source=new_source_path,
            new_doc_storage=new_doc_index._storage,
            new_title=short_info.get("title", ""),
            new_short_summary=short_info.get("short_summary", ""),
        )

        # Clean up old storage (if different path)
        if old_doc_storage and old_doc_storage != new_doc_index._storage:
            if os.path.isdir(old_doc_storage):
                _shutil.rmtree(old_doc_storage, ignore_errors=True)

        task.update({
            "status": "completed",
            "phase": "done",
            "message": "Document replaced successfully.",
            "new_doc_id": new_doc_id,
            "title": short_info.get("title", ""),
            "short_summary": short_info.get("short_summary", ""),
        })
    except Exception as exc:
        traceback.print_exc()
        task.update({"status": "error", "phase": "error", "message": str(exc)})
    finally:
        def _cleanup():
            time.sleep(120)
            _REPLACE_TASKS.pop(task_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


@global_docs_bp.route("/global_docs/replace_progress/<task_id>")
@login_required
def replace_global_doc_progress(task_id: str):
    """SSE stream of replacement progress."""
    def generate():
        while True:
            task = _REPLACE_TASKS.get(task_id)
            if task is None:
                yield f"data: {json.dumps({'phase': 'error', 'message': 'Unknown task'})}\n\n"
                break
            yield f"data: {json.dumps(task)}\n\n"
            if task.get("status") in ("completed", "error"):
                break
            time.sleep(1.5)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")
