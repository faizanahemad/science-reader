# Conversation Artefacts

Conversation artefacts are conversation-scoped files stored on disk and editable in a full-screen modal. Users can create, edit, download, and apply LLM-assisted edits with a diff preview. Artefacts can be referenced in chat using `#artefact_N` tokens.

## Access Points

- Message action menu: message triple-dot dropdown opens the artefacts modal.
- Chat settings: the Artefacts button opens the modal.
- Context menu: right-click selection and choose Artefacts.
- Vote menu: "Edit as Artefact" from the right-side triple-dot menu on assistant cards creates an artefact from the answer and links saves back to the message. The same triple-dot menu also includes "Save to Memory" which opens the PKB Add Memory modal with the message text pre-filled.

## Storage Model

- Each conversation stores artefact metadata in the `artefacts` field.
- Files are stored under `storage/conversations/<conversation_id>/artefacts/`.
- File names are sanitized and include a unique id suffix.

Metadata schema (stored on the conversation object):

```json
{
  "id": "<uuid>",
  "name": "<display name>",
  "file_type": "md|txt|py|js|json|html|css",
  "file_name": "<safe-name>-<id>.<ext>",
  "created_at": "YYYY-MM-DD HH:MM:SS",
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "size_bytes": 1234
}
```

## Backend Flow

- `Conversation.py` adds artefact helpers: create, list, read, update, delete, and `#artefact_N` resolution.
- `endpoints/artefacts.py` exposes CRUD endpoints and LLM edit workflows.
- LLM edit workflow uses a propose/apply flow with content hashing to avoid stale edits.
- Message links (edit-as-artefact) are stored on the conversation in `artefact_message_links` and served via the artefacts API.

### CRUD Endpoints

- `GET /artefacts/<conversation_id>`: list metadata.
- `POST /artefacts/<conversation_id>`: create a file with `{name, file_type, initial_content}`.
- `GET /artefacts/<conversation_id>/<artefact_id>`: fetch metadata + content.
- `PUT /artefacts/<conversation_id>/<artefact_id>`: update file content.
- `DELETE /artefacts/<conversation_id>/<artefact_id>`: delete file + metadata.
- `GET /artefacts/<conversation_id>/<artefact_id>/download`: download file.

### LLM Edit Proposals

- `POST /artefacts/<conversation_id>/<artefact_id>/propose_edits` accepts instructions, optional selection, and context toggles.
- The server generates operations (replace/insert/append/delete), applies them in memory, and returns a unified diff.

Payload shape:

```json
{
  "instruction": "Update the summary section.",
  "selection": { "start_line": 4, "end_line": 12 },
  "include_summary": true,
  "include_messages": true,
  "include_memory_pad": false,
  "history_count": 10
}
```

Response shape:

```json
{
  "proposed_ops": [
    { "op": "replace_range", "start_line": 4, "end_line": 8, "text": "..." }
  ],
  "diff_text": "--- before\n+++ after\n@@ ...",
  "base_hash": "...",
  "new_hash": "..."
}
```

- `POST /artefacts/<conversation_id>/<artefact_id>/apply_edits` applies the selected ops if the `base_hash` matches.

## Frontend Flow

- `interface/interface.html` defines the full-screen modal, tabs (Code/Preview/Diff), and controls.
- `interface/artefacts-manager.js` handles list/load/save/delete, diff preview, and proposed edit application.
  - `openModalForMessage()` creates or reuses a linked artefact from an assistant answer and links saves back to `ConversationManager.saveMessageEditText()`.
  - Linked artefacts are persisted on the server via `artefact_message_links` and fetched by the UI.
  - Opening a linked artefact later (any ingress) still syncs saves back to the original message.
  - Diff preview supports per-block selection (multiple checkboxes per diff) for incremental apply.

Entry points:

- `interface/common-chat.js`: action dropdown item `open-artefacts-button` inside `renderMessages()`.
- `interface/context-menu-manager.js`: `artefacts` action opens the modal.
- `interface/chat.js`: settings modal button `settings-artefacts-modal-open-button` opens the modal.
- `interface/common.js`: `initialiseVoteBank()` adds "Edit as Artefact" and "Save to Memory" to the vote dropdown on assistant cards.

## Recent Enhancements

- **Edit-as-Artefact persistence**: message -> artefact links are stored server-side (`artefact_message_links`) and reused across devices/sessions.
- **Linked save-through**: saving a linked artefact updates the original assistant answer via `ConversationManager.saveMessageEditText()`.
- **Reuse on re-open**: "Edit as Artefact" reopens the existing linked artefact instead of creating a duplicate.
- **Per-block diff selection**: diff rendering splits hunks into smaller selectable blocks so changes can be accepted incrementally.
- **Propose edits feedback**: the Propose Edits button shows a spinner and disables while proposals run.

## Implementation Notes

- **Message link APIs**:
  - `GET /artefacts/<conversation_id>/message_links` returns `{ message_id: { artefact_id, message_index } }`.
  - `POST /artefacts/<conversation_id>/message_links` accepts `{ message_id, artefact_id, message_index? }`.
  - `DELETE /artefacts/<conversation_id>/message_links/<message_id>` removes the mapping.
- **Link persistence**: the client loads links on modal open and stores updates through the API (no localStorage).
- **Edit-as-Artefact reuse**: `openModalForMessage()` checks for an existing link and reopens that artefact; if missing, it creates a new artefact seeded with the answer.
- **Linked save-through**: `saveArtefact()` reuses the link to update the original message text (falling back to `/edit_message_from_conversation/...` if no card element is available).
- **Diff blocks**: `parseUnifiedDiff()` splits hunks into smaller blocks around change clusters to enable per-block checkboxes.

## Cmd+K Inline Edit

Keyboard shortcut for quick AI-assisted editing:

 **Shortcut**: Cmd+K / Ctrl+K while the artefact textarea has focus opens an instruction overlay.
 **Selection**: If text is selected, shows the selected line range. Otherwise, edits the entire artefact.
 **Flow**: Overlay captures instruction -> feeds into existing `proposeEdits()` pipeline -> per-hunk diff in Diff tab.
 **Deep context**: Optional checkbox for `retrieve_prior_context_llm_based` extraction (adds 2-5s latency).
 Ctrl+Enter / Cmd+Enter submits the instruction.
 Escape closes the overlay.

### Backend Enhancement
 `propose_edits` endpoint now accepts optional `deep_context` boolean field.
 When true, calls `conversation.retrieve_prior_context_llm_based(instruction)` and includes extracted context in the LLM prompt.

---
## Chat References

- Use `#artefact_N` in a message to inject artefact content into the prompt.
- The system resolves `N` as a 1-based index into the artefact list and inserts line-numbered content.

## Key Files

- `Conversation.py`
- `endpoints/artefacts.py`
- `endpoints/__init__.py`
- `server.py`
- `interface/interface.html`
- `interface/artefacts-manager.js`
- `interface/common-chat.js`
- `interface/context-menu-manager.js`
- `interface/chat.js`
