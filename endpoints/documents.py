"""
Document-related endpoints.

This module extracts the conversation document management API surface from
`server.py` into a Flask Blueprint.
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import List

from flask import Blueprint, jsonify, redirect, request, send_from_directory, session

from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
from endpoints.responses import json_error
from extensions import limiter


documents_bp = Blueprint("documents", __name__)
logger = logging.getLogger(__name__)


@documents_bp.route("/upload_doc_to_conversation/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def upload_doc_to_conversation_route(conversation_id: str):
    state, keys = get_state_and_keys()

    pdf_file = request.files.get("pdf_file")
    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    if pdf_file and conversation_id:
        try:
            pdf_file.save(os.path.join(state.pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
            conversation.add_uploaded_document(full_pdf_path)
            conversation.save_local()
            return jsonify({"status": "Indexing started"})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    pdf_url = None
    if request.is_json and request.json:
        pdf_url = request.json.get("pdf_url")

    if pdf_url:
        from common import convert_to_pdf_link_if_needed

        pdf_url = convert_to_pdf_link_if_needed(pdf_url)

    if pdf_url:
        try:
            conversation.add_uploaded_document(pdf_url)
            conversation.save_local()
            return jsonify({"status": "Indexing started"})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    return json_error("No pdf_url or pdf_file provided", status=400, code="bad_request")


@documents_bp.route("/delete_document_from_conversation/<conversation_id>/<document_id>", methods=["DELETE"])
@limiter.limit("100 per minute")
@login_required
def delete_document_from_conversation_route(conversation_id: str, document_id: str):
    state, keys = get_state_and_keys()

    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    doc_id = document_id
    if doc_id:
        try:
            conversation.delete_uploaded_document(doc_id)
            return jsonify({"status": "Document deleted"})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    return json_error("No doc_id provided", status=400, code="bad_request")


@documents_bp.route("/list_documents_by_conversation/<conversation_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_documents_by_conversation_route(conversation_id: str):
    state, keys = get_state_and_keys()

    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    if conversation:
        docs: List = conversation.get_uploaded_documents(readonly=True)
        docs = [d for d in docs if d is not None]
        docs = attach_keys(docs, keys)
        docs = [d.get_short_info() for d in docs]
        return jsonify(docs)

    return json_error("Conversation not found", status=404, code="conversation_not_found")


@documents_bp.route("/download_doc_from_conversation/<conversation_id>/<doc_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def download_doc_from_conversation_route(conversation_id: str, doc_id: str):
    state, keys = get_state_and_keys()

    conversation = state.conversation_cache[conversation_id]
    if conversation:
        conversation = attach_keys(conversation, keys)
        doc = conversation.get_uploaded_documents(doc_id, readonly=True)[0]
        if doc and os.path.exists(doc.doc_source):
            file_dir, file_name = os.path.split(doc.doc_source)
            if os.path.dirname(__file__).strip() != "":
                root_dir = os.path.dirname(__file__) + "/"
                file_dir = file_dir.replace(root_dir, "")
            return send_from_directory(file_dir, file_name)
        if doc:
            return redirect(doc.doc_source)
        return json_error("Document not found", status=404, code="document_not_found")

    return json_error("Conversation not found", status=404, code="conversation_not_found")


