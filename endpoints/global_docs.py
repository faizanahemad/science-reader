"""
Global document endpoints.

Provides CRUD operations for user-scoped global documents that can be
referenced from any conversation via #gdoc_N / #global_doc_N syntax.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import traceback

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session
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
    update_global_doc_metadata,
)
from database.doc_tags import set_tags as _set_tags, list_all_tags as _list_all_tags


global_docs_bp = Blueprint("global_docs", __name__)
logger = logging.getLogger(__name__)


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

        doc_index._storage = target_storage
        doc_index.save_local()

        short_info = doc_index.get_short_info()

        add_global_doc(
            users_dir=state.users_dir,
            user_email=email,
            doc_id=doc_id,
            doc_source=pdf_url,
            doc_storage=target_storage,
            title=short_info.get("title", ""),
            short_summary=short_info.get("short_summary", ""),
            folder_id=folder_id,
        )

        new_doc_list = [e for e in doc_list if e[0] != doc_id]
        conversation.set_field("uploaded_documents_list", new_doc_list, overwrite=True)

        remaining_docs = conversation.get_uploaded_documents()
        doc_infos = "\n".join(
            [
                f"#doc_{i + 1}: ({d.title})[{d.doc_source}]"
                for i, d in enumerate(remaining_docs)
            ]
        )
        conversation.doc_infos = doc_infos

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
