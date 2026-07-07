# Conversation Sync (one-way push)

Push a single conversation from one running instance of this app to another over
HTTPS, so an answer produced on one host (e.g. a laptop) can be *read* on another
(e.g. a cloud VM). This is a deliberately small, self-contained feature: no
polling, no daemon, no two-way sync, no conflict resolution.

Plan of record: `documentation/planning/plans/conversation_sync.plan.md`.

## Motivation & Background

The user runs multiple instances of this chat service on different hosts. Rather
than a heavyweight long-polling worker (which solves remote *execution*), this
feature solves remote *reading*: the user right-clicks a conversation → **Sync to
remote**, and the *source* server serializes the conversation and POSTs it to an
upload endpoint on the *target* server with a bearer token. The browser never
talks to the target and never sees the token.

- Synced conversations land on the target under an auto-created workspace named
  **`sync`**, owned by a target-side user configured at server start, in the same
  `domain` as the source conversation.
- Symmetric: any instance can send, receive, or both — purely a function of which
  env vars are set on each instance.

### Non-goals

- Two-way sync / conflict resolution. Push-only, last-write-wins upsert.
- Live continuation on the target. Synced conversations are for reading; replying
  to one on the target is allowed but the copies then diverge (re-sync overwrites
  the target).
- Syncing uploaded documents' binary content (only display metadata is carried)
  or embedding indices (rebuilt lazily, same as `clone_conversation`).
- Any content-based inspection/blocking of what is synced. The endpoint is a dumb
  authenticated upsert; the user manages what is appropriate to sync by policy.

## Configuration (environment variables)

All five are read into `app.config` in `server.create_app` and referenced via
`current_app.config` in `endpoints/sync.py`. Supply them via `run_server.sh` /
launch config — never commit them.

Receiver (target instance):
- `SYNC_UPLOAD_TOKEN` — shared secret. **When unset, `POST /sync/upload` returns
  404 and the receiver feature is entirely off** (it can never become an
  accidental unauthenticated surface).
- `SYNC_UPLOAD_USER_EMAIL` — the target-side owner of all synced conversations.
  This must be an email that can log in on the target instance (ops guarantees it
  exists; the receiver does not auto-create users).

Sender (source instance):
- `SYNC_REMOTE_URL` — base URL of the target, e.g. `https://host.example`.
- `SYNC_REMOTE_TOKEN` — must equal the target's `SYNC_UPLOAD_TOKEN`.
- `SYNC_HOST_LABEL` — optional free-text label (e.g. `laptop`) stamped into
  provenance and shown in the receiver badge. **No hostname fallback** — when
  unset, the receiver badge shows the export date only.

A single instance may set all five and both send and receive. The sidebar action
is shown only when `GET /sync/config` reports `sync_send_enabled: true` (i.e.
`SYNC_REMOTE_URL` and `SYNC_REMOTE_TOKEN` are both set).

## API

### `POST /sync/upload` — receiver (token auth, no session)

The first and only token-authenticated route in the codebase; isolated in its own
blueprint (`endpoints/sync.py`), no session access. Rate limited `30/min`.

Order of checks (all early-exit):
1. **404** `sync_disabled` — `SYNC_UPLOAD_TOKEN`/`SYNC_UPLOAD_USER_EMAIL` unset.
2. **413** `sync_too_large` — `Content-Length` > 25 MB, checked *before* parsing.
3. **401** `sync_unauthorized` — missing/incorrect `Authorization: Bearer <token>`
   (compared with `hmac.compare_digest`).
4. **400** — bad JSON (`sync_bad_body`), wrong `sync_version` (`sync_bad_version`),
   or missing `source.conversation_id` / `domain` / `messages` (`sync_bad_payload`).

On success it computes a **deterministic target conversation id**
`f"{owner_email}_sync_{sha256(source_user_id + '|' + source_cid)[:24]}"` — this
makes re-syncing idempotent (upsert in place, no duplicates, no mapping table).

Upsert:
- **Create path** (target folder absent): new `Conversation(owner_email, None,
  conversation_folder, target_cid, domain)`, apply fields, write artefact files,
  `save_local()`, resolve-or-create the `sync` workspace and `addConversation(...)`.
- **Update path** (target folder present): `Conversation.load_local(target_dir)`,
  overwrite fields, replace artefacts, `save_local()`.
- Either way: evict the stale cache entry first, insert the fresh object into
  `state.conversation_cache[target_cid]`, and best-effort reindex into the
  cross-conversation search index.

Response: `{"status": "ok", "target_conversation_id": <cid>, "updated": <bool>}`.
`updated=false` on first import, `true` on re-sync.

### `POST /sync_conversation/<conversation_id>` — sender (session auth)

Normal stack: `@limiter.limit("25 per minute")` + `@login_required`. Returns
**400** `sync_not_configured` when `SYNC_REMOTE_URL`/`SYNC_REMOTE_TOKEN` are unset,
**404** when the conversation isn't in the cache.

1. Builds the payload via `Conversation.export_sync_payload(host_label=...)`.
2. **No-op optimisation**: compares the payload `content_hash` against
   `conversation_settings["last_sync"]` (same remote URL). If unchanged, returns
   `{"status": "ok", "skipped": true}` with no HTTP call. `?force=1` bypasses.
3. `requests.post(f"{SYNC_REMOTE_URL}/sync/upload", json=payload, headers={Bearer},
   timeout=60)`. Remote 401/404/413 are surfaced to the browser as-is; unreachable
   → **502** `sync_unreachable`; other non-2xx → **502** `sync_remote_error`.
4. On 2xx, records `last_sync` (url, content_hash, target cid, timestamp) into
   `conversation_settings` and `save_local()`.

Response: `{"status": "ok", "skipped": false, "updated": <bool>,
"target_conversation_id": <cid>}`.

### `GET /sync/config` — sender (session auth)

`{"sync_send_enabled": <bool>}`. Lets the UI decide whether to show the menu item.

## Payload format (versioned JSON, `sync_version: 1`)

Built by `Conversation.export_sync_payload(host_label="", max_artefact_bytes=5MB)`
(Conversation.py, near `get_metadata`). Keys:

- `sync_version`, `source` (`conversation_id`, `user_id`, `host_label`,
  `exported_at`), `domain`
- `metadata` (title, summary_till_now, flag, conversation_friendly_id)
- `memory`, `messages` (verbatim, full fidelity — opaque dicts), `conversation_settings`
- `uploaded_documents` (title/source **display only** — binaries not synced)
- `artefact_metadata` (the `artefacts` field's meta dicts)
- `artefact_message_links`
- `artefacts` (base64-inlined file bytes keyed by `path` = filename; files over
  `max_artefact_bytes` are skipped and listed in `skipped_artefacts`)
- `content_hash` — sha256 of canonical JSON of the above.

**Important:** the volatile local sync bookkeeping keys `last_sync`, `sync_source`,
and `sync_source_documents` are stripped from `conversation_settings` *before*
hashing and transmission. Otherwise the first sync (which writes `last_sync`) would
change the hash and permanently defeat the no-op skip. This also prevents a source's
sync bookkeeping from propagating to the target.

## Receiver-side behavior

- The target copy is a normal conversation afterward — readable and even
  continuable (it then diverges; re-sync overwrites it by design).
- Provenance is stored in `conversation_settings["sync_source"]`
  (`{conversation_id, user_id, host_label, exported_at, content_hash}`) and, if
  present, `conversation_settings["sync_source_documents"]` (display-only).
- `set_field(..., overwrite=True)` **replaces** (not appends) for messages, memory,
  artefacts, artefact_message_links, and conversation_settings (verified against
  `Conversation._set_field_sqlite`), so no delete-then-import is needed.
- Artefact files are written into the target `artefacts/` dir with path-traversal
  guarded to a bare `os.path.basename`.

## UI (interface/)

- `ConversationManager.syncConversation(conversationId, force)` in
  `interface/common-chat.js` — POSTs `/sync_conversation/<cid>` (`?force=1` when
  `force`), returns a `$.ajax` promise (mirrors `cloneConversation`).
- Context-menu item `syncToRemote` in `buildConversationContextMenu`
  (`interface/workspace-manager.js`), after the clone item. Success/skip/fail
  toasts via `showToast`. The item is deleted from the menu unless
  `WorkspaceManager._syncSendEnabled` is true, which is fetched once from
  `GET /sync/config` in `init()`.
- Receiver badge: `ConversationManager.renderSyncBadge(conversationId, settings)`
  in `common-chat.js` prepends a muted `.sync-source-badge`
  ("synced from `<host_label>` · `<exported_at>`", date-only when the label is
  empty) into the chat view, called after render in `setActiveConversation` via
  `GET /get_conversation_settings/<cid>` with a stale-guard.

## Verification

`scripts/test_conversation_sync.py` is a hybrid two-instance end-to-end test:
a real HTTP receiver in a subprocess (`scripts/_sync_test_server.py`, boots
`create_app()` on a chosen port, skipping MCP servers) plus an in-process sender
app with a seeded session (the sender route is `@login_required`, which always
needs a session and the conversation in the in-memory cache). It asserts: 404
unconfigured, 401 bad token, 413 oversized, 200 create with workspace
registration and message equality, provenance stamping, idempotent re-sync
(`updated: true`, same deterministic cid), the real sender endpoint, hash-skip
no-op on unchanged re-send, and `?force=1` bypass. All 19 checks pass.

Run: `PIP_INDEX_URL=https://pypi.org/simple/ .venv/bin/python scripts/test_conversation_sync.py`

## Files

- `Conversation.py` — `export_sync_payload()` (payload builder + stable hash).
- `endpoints/sync.py` — new blueprint: `/sync/upload`, `/sync_conversation/<cid>`,
  `/sync/config`, plus helpers (`_target_conversation_id`,
  `_resolve_or_create_sync_workspace`, `_apply_payload_fields`,
  `_write_artefact_files`, `_reindex`).
- `server.py` — reads the 5 `SYNC_*` env vars into `app.config` in `create_app`.
- `endpoints/__init__.py` — registers `sync_bp`.
- `interface/common-chat.js` — `syncConversation`, `renderSyncBadge`, badge call.
- `interface/workspace-manager.js` — `_syncSendEnabled` gate, `/sync/config` fetch,
  `syncToRemote` context-menu item.
- `scripts/_sync_test_server.py`, `scripts/test_conversation_sync.py` — verification.
