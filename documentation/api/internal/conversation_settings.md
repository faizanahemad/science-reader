# Conversation Settings API (Internal)

Conversation-level settings are persisted on the conversation object and allow per-conversation overrides (currently focused on model selection for non-reply tasks).

Base path: `/`

## Endpoints

- `GET /get_conversation_settings/<conversation_id>`
  - Returns the stored settings object.
  - Response:

```json
{
  "conversation_id": "...",
  "settings": {
    "model_overrides": {
      "summary_model": "...",
      "tldr_model": "...",
      "artefact_propose_edits_model": "...",
      "doubt_clearing_model": "...",
      "context_action_model": "...",
      "doc_long_summary_model": "...",
      "doc_long_summary_v2_model": "...",
      "doc_short_answer_model": "..."
    }
  }
}
```

- `PUT /set_conversation_settings/<conversation_id>`
  - Persists `model_overrides` after validating model names.
  - Payload:

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
    "doc_short_answer_model": "..."
  }
}
```

## Validation Rules

- `model_overrides` must be an object.
- Keys outside the allowlist are ignored.
- Model names are validated with `model_name_to_canonical_name`.
- Empty values are dropped and fall back to defaults.

## Notes

- All routes are protected by `login_required` and rate-limited.
- Settings are persisted per conversation and do not affect other chats.
