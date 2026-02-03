# Artefacts API (Internal)

Conversation artefacts are file-based attachments stored under each conversation. The API provides CRUD operations plus LLM-assisted edit proposals with diff previews.

Base path: `/artefacts/<conversation_id>`

## Endpoints

- `GET /artefacts/<conversation_id>`
  - List artefact metadata for the conversation.

- `POST /artefacts/<conversation_id>`
  - Create a new artefact.
  - Body: `{ "name": "...", "file_type": "md|txt|py|js|json|html|css", "initial_content": "" }`

- `GET /artefacts/<conversation_id>/<artefact_id>`
  - Fetch artefact metadata plus `content`.

- `PUT /artefacts/<conversation_id>/<artefact_id>`
  - Update content.
  - Body: `{ "content": "..." }`

- `DELETE /artefacts/<conversation_id>/<artefact_id>`
  - Delete file + metadata.

- `GET /artefacts/<conversation_id>/<artefact_id>/download`
  - Download artefact file.

- `GET /artefacts/<conversation_id>/message_links`
  - Return mapping `{ message_id: { artefact_id, message_index } }`.

- `POST /artefacts/<conversation_id>/message_links`
  - Create/update mapping.
  - Body: `{ "message_id": "...", "artefact_id": "...", "message_index": "..." }`

- `DELETE /artefacts/<conversation_id>/message_links/<message_id>`
  - Remove mapping for a message.

## LLM Edit Workflow

- `POST /artefacts/<conversation_id>/<artefact_id>/propose_edits`
  - Proposes file edits without persisting.
  - Uses the conversation-level `artefact_propose_edits_model` override when set.
  - See `documentation/api/internal/conversation_settings.md` and `documentation/api/internal/model_catalog.md` for how overrides are configured.
  - Body:

```json
{
  "instruction": "...",
  "selection": { "start_line": 4, "end_line": 12 },
  "include_summary": true,
  "include_messages": true,
  "include_memory_pad": false,
  "history_count": 10
}
```

  - Response: `{ "proposed_ops": [...], "diff_text": "...", "base_hash": "...", "new_hash": "..." }`

- `POST /artefacts/<conversation_id>/<artefact_id>/apply_edits`
  - Applies selected operations if `base_hash` matches current content.
  - Body: `{ "base_hash": "...", "proposed_ops": [...] }`
  - Response includes updated content and diff.

## Notes

- All routes are protected by `login_required` and rate-limited.
- Edit proposals use line-based operations: `replace_range`, `insert_at`, `append`, `delete_range`.
