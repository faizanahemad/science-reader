# Conversation Model Overrides

Conversation model overrides let users pick non-reply models on a per-conversation basis (summaries, artefact edits, context actions, and Doc Index operations). Overrides are stored on the conversation and sent to the server so they apply consistently across sessions and devices.

## What We Added

- **Conversation-level settings store**: new `conversation_settings` field in `Conversation.py` persisted with the conversation.
- **Model override UI**: chat settings now exposes a **Model Overrides** modal with dropdowns (defaults + full model list).
- **Dynamic model catalog**: dropdown options are fetched from `/model_catalog`, which dedupes models from the common model lists.
- **Server application points**: overrides are applied to summary/TLDR generation, artefact propose-edits, doubt clearing, context menu actions, and Doc Index summarization/answers.

## User Experience

- Open chat settings → **Model Overrides**.
- Each dropdown has:
  - **Default (recommended)** which means “use the current code default.”
  - A default entry showing the actual default model name.
  - All deduped models from the shared lists.
- Overrides are saved per conversation and do not affect other chats.

## Settings Schema

Stored on the conversation as:

```json
{
  "model_overrides": {
    "summary_model": "...",
    "tldr_model": "...",
    "artefact_propose_edits_model": "...",
    "doubt_clearing_model": "...",
    "context_action_model": "...",
    "doc_long_summary_model": "...",
    "doc_long_summary_v2_model": "...",
    "doc_short_answer_model": "...",
    "clarify_intent_model": "..."
  }
}
```

If a key is missing or empty, the server falls back to the existing default in code.

## API Endpoints

- `GET /get_conversation_settings/<conversation_id>`
  - Returns `{ conversation_id, settings }`.
- `PUT /set_conversation_settings/<conversation_id>`
  - Payload: `{ "model_overrides": { ... } }`
  - Validates model names using `model_name_to_canonical_name`.
- `GET /model_catalog`
  - Returns `{ models: [...], defaults: { ... } }`.
  - Models are deduped from: `VERY_CHEAP_LLM`, `CHEAP_LLM`, `EXPENSIVE_LLM`, `CHEAP_LONG_CONTEXT_LLM`, `LONG_CONTEXT_LLM`.

## Application Points (Server)

- **Summaries**: `Conversation.reply()` uses `summary_model` when updating running summary/title.
- **TLDR**: `Conversation.reply()` uses `tldr_model` for long-answer TLDR generation.
- **Artefact propose edits**: `endpoints/artefacts.py` uses `artefact_propose_edits_model`.
- **Doubt clearing**: `Conversation.reply()` uses `doubt_clearing_model`.
- **Context menu actions** (explain/critique/expand/ELI5): `Conversation.reply()` and the fallback path in `endpoints/doubts.py` use `context_action_model`.
- **Doc Index**:
  - `doc_long_summary_model` for `DocIndex.get_doc_long_summary()` and chain-of-density.
  - `doc_long_summary_v2_model` for `DocIndex.get_doc_long_summary_v2()`.
  - `doc_short_answer_model` for `DocIndex.streaming_get_short_answer()`.
- **Clarify Intent**: `endpoints/conversations.py` `clarify_intent` endpoint uses `clarify_intent_model` when calling the LLM to generate clarification questions. Defaults to `VERY_CHEAP_LLM[0]`. Applied via `conversation.get_model_override("clarify_intent_model", VERY_CHEAP_LLM[0])`. UI dropdown: `#settings-clarify-intent-model` in the "Clarify Models" section of the Model Overrides modal.

## UI Implementation Details

- **Modal**: `interface/interface.html` adds the Model Overrides modal with dropdowns.
- **Data loading**: `interface/chat.js` calls `/model_catalog` on startup and before opening the modal.
- **Saving**: `interface/chat.js` uses `/set_conversation_settings/<conversation_id>` and updates in-memory state.
- **Conversation switching**: `interface/common-chat.js` fetches settings on conversation load and updates `chatSettingsState`.

## Extending the Feature

To add a new override:

1) **Server allowlist**: add the key to `allowed_keys` in `endpoints/conversations.py`.
2) **Defaults**: include the default in `/model_catalog` response.
3) **Storage**: no change needed (same `model_overrides` map).
4) **Usage**: apply `conversation.get_model_override("new_key", DEFAULT)` at the callsite.
5) **UI**: add a dropdown in `interface/interface.html` and wire load/save in `interface/chat.js`.
6) **Docs**: update this file and any relevant API docs.

## Key Files

- `Conversation.py`
- `DocIndex.py`
- `endpoints/conversations.py`
- `endpoints/artefacts.py`
- `endpoints/doubts.py`
- `interface/interface.html`
- `interface/chat.js`
- `interface/common-chat.js`
