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


global_docs_bp = Blueprint("global_docs", __name__)
logger = logging.getLogger(__name__)


def _user_hash(email: str) -> str:
    return hashlib.md5(email.encode()).hexdigest()


def _ensure_user_global_dir(state, email: str) -> str:
    """Return (and create if needed) the per-user global docs storage directory."""
    user_dir = os.path.join(state.global_docs_dir, _user_hash(email))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


@global_docs_bp.route("/global_docs/upload", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def upload_global_doc():
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    user_storage = _ensure_user_global_dir(state, email)

    pdf_file = request.files.get("pdf_file")
    display_name = ""

    if pdf_file:
        try:
            pdf_file.save(os.path.join(state.pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)

            if request.form:
                display_name = request.form.get("display_name", "")

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

    user_storage = _ensure_user_global_dir(state, email)
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
