"""
Audio-related endpoints (TTS + transcription).

This module extracts `/tts`, `/is_tts_done`, and `/transcribe` from `server.py`
into a Flask Blueprint.
"""

from __future__ import annotations

import traceback

from flask import Blueprint, Response, jsonify, request, send_file, session

from database.conversations import checkConversationExists
from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from transcribe_audio import transcribe_audio as run_transcribe_audio


audio_bp = Blueprint("audio", __name__)

@audio_bp.route("/tts/<conversation_id>/<message_id>", methods=["POST"])
@login_required
def tts_route(conversation_id: str, message_id: str):
    """
    Streaming (or non-streaming) TTS for a conversation message.

    Request JSON keys (legacy):
    - text: str
    - recompute: bool
    - message_index: int | None
    - streaming: bool
    - shortTTS: bool
    - podcastTTS: bool
    """

    email, _name, _loggedin = get_session_identity()
    state, keys = get_state_and_keys()

    text = request.json.get("text", "") if request.is_json and request.json else ""
    recompute = request.json.get("recompute", False) if request.is_json and request.json else False
    message_index = request.json.get("message_index", None) if request.is_json and request.json else None
    streaming = request.json.get("streaming", True) if request.is_json and request.json else True
    shortTTS = request.json.get("shortTTS", False) if request.is_json and request.json else False
    podcastTTS = request.json.get("podcastTTS", False) if request.is_json and request.json else False

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = state.conversation_cache[conversation_id]
    conversation = attach_keys(conversation, keys)

    if streaming:
        audio_generator = conversation.convert_to_audio_streaming(text, message_id, message_index, recompute, shortTTS, podcastTTS)

        def generate_audio():
            for chunk in audio_generator:
                yield chunk

        return Response(generate_audio(), mimetype="audio/mpeg")

    location = conversation.convert_to_audio(text, message_id, message_index, recompute, shortTTS, podcastTTS)
    return send_file(location, mimetype="audio/mpeg")


@audio_bp.route("/is_tts_done/<conversation_id>/<message_id>", methods=["POST"])
def is_tts_done_route(conversation_id: str, message_id: str):
    # Legacy endpoint always returns done=True.
    _ = conversation_id, message_id
    _text = request.json.get("text") if request.is_json and request.json else None
    return jsonify({"is_done": True}), 200


@audio_bp.route("/transcribe", methods=["POST"])
def transcribe_audio_route():
    if "audio" not in request.files:
        return json_error("No audio file provided", status=400, code="bad_request")

    audio_file = request.files["audio"]
    if audio_file.filename == "":
        return json_error("No selected file", status=400, code="bad_request")

    try:
        transcription = run_transcribe_audio(audio_file)
        return jsonify({"transcription": transcription})
    except Exception as e:
        traceback.print_exc()
        return json_error(str(e), status=500, code="internal_error")


