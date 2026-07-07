# Conversation Sync (Push) — Plan

Status: DONE (implemented + verified 2026-07-07; feature doc at
documentation/features/conversation_sync/README.md). Verified end-to-end by
scripts/test_conversation_sync.py (19/19 checks pass).
Scope: pure, self-contained feature. No dependency on any other planned work.

## 0. Decisions Locked (2026-07-07, confirmed with user before build)

These resolve the open points in §6 and the optional/ambiguous items below:

1. **Scope**: implement all of tasks 1–6 (backend + UI + verification + docs) in one pass.
2. **Message/settings replacement on re-sync**: use plain `set_field(field, value, overwrite=True)`.
   Verified in code — `_set_field_sqlite` (Conversation.py:2959) REPLACES (not appends)
   for `messages` (`overwrite_messages`), `memory`, `artefacts`,
   `artefact_message_links`, and `conversation_settings` when `overwrite=True`.
   No manual delete-then-import_all needed.
3. **Deterministic target cid keying**: key on `source_user_id + '|' + source_cid`
   (plan default) — safest against cross-user collisions. Re-owning (changing
   `SYNC_UPLOAD_USER_EMAIL`) intentionally creates a distinct target copy.
4. **Target user existence**: assume ops guarantees `SYNC_UPLOAD_USER_EMAIL` exists
   on the target. If registration (`addConversation`) fails, do NOT auto-create the
   user — surface the error back to the source browser and show it in the sync
   toast/alert on the source UI.
5. **Config source of truth**: read all four env vars into `app.config` in
   `create_app`; endpoints reference `app.config[...]` (not bare `os.environ`).
6. **host_label**: comes from an optional `SYNC_HOST_LABEL` env var on the sender.
   When unset, `host_label` is empty and the receiver badge renders date-only.
   (Do NOT auto-derive from hostname — hostnames are sensitive on the user's setup.)
7. **Receiver display badge (§4.6)**: INCLUDED this pass — muted
   "synced from <host_label> · <exported_at>" (date-only when host_label empty).
8. **Verification (task 5)**: a standalone runnable script
   `scripts/test_conversation_sync.py` that boots two real servers on two ports
   (distinct `--folder` storage roots) and curls through the whole flow with
   assertions. Not a pytest; not an in-process app harness.

## 1. Motivation & Background

The user runs two (or more) instances of this chat service on different hosts
(e.g. a laptop and a cloud VM). Conversations answered on one host should be
readable on another — primarily for offline/remote reading of already-answered
questions. Earlier designs considered a long-polling worker so a cloud instance
could *execute* work on the laptop; that is heavyweight and solves a different
problem. This feature is the simple alternative:

- **One-way push**: the user right-clicks a conversation → "Sync to remote".
  The *source* server serializes the conversation and POSTs it to an upload
  endpoint on the *target* server over HTTPS with a bearer token.
- Synced conversations land on the target under a workspace named **`sync`**
  (auto-created), owned by a target-side user configured at server start.
- Symmetric: any instance can be sender, receiver, or both — it is purely a
  matter of which env vars are set on each instance. No polling, no daemon,
  no always-on requirement on either side beyond the moment of sync.

Non-goals (explicitly out of scope):
- Two-way sync / conflict resolution. This is push-only, last-write-wins upsert.
- Live continuation guarantees on the target. Synced conversations are for
  reading; replying to one on the target is allowed but the two copies then
  diverge permanently (acceptable; re-sync overwrites target with source).
- Syncing uploaded source documents' binary content (see §4.3) or embedding
  indices (rebuilt lazily, same as `clone_conversation`).
- Any content-based blocking/inspection of what is synced. The user manages
  what is appropriate to sync by habit/policy; the endpoint is a dumb
  authenticated upsert.

## 2. Requirements

Functional:
1. Per-conversation "Sync to remote" action in the sidebar context menu.
2. Source server serializes conversation (metadata, messages, memory,
   settings, artefacts) and pushes it server-side to the target URL.
   The browser never talks to the target and never sees the token.
3. Target server exposes `POST /sync/upload`, authenticated by a static
   bearer token from env. Endpoint is **disabled entirely** (404) when the
   env var is unset.
4. Upsert semantics keyed on the source conversation id: re-syncing the same
   conversation updates the existing target copy in place (no duplicates).
5. Target copy appears under a workspace named `sync` (created on demand) for
   the configured target user, in the same `domain` as the source conversation.
6. UI feedback via `showToast` on success/failure; the action is fire-and-forget
   (no page reload needed on the source).

Configuration (all plain `os.environ.get` in `create_app`, values supplied via
`run_server.sh` / launch config — never committed):
- Receiver: `SYNC_UPLOAD_TOKEN` (shared secret; endpoint disabled if unset),
  `SYNC_UPLOAD_USER_EMAIL` (target-side owner of all synced conversations).
- Sender: `SYNC_REMOTE_URL` (base URL of target, e.g. `https://host.example`),
  `SYNC_REMOTE_TOKEN` (must equal target's `SYNC_UPLOAD_TOKEN`), and optional
  `SYNC_HOST_LABEL` (free-text source label, e.g. `laptop`; empty when unset →
  receiver badge is date-only). The sidebar action is hidden/disabled when
  `SYNC_REMOTE_URL` is unset (source exposes a tiny "is sync configured" boolean
  via `GET /sync/config`).
- A single instance may set all of them and both send and receive.
- All read into `app.config` in `create_app`; endpoints reference `app.config`.

Security:
- HTTPS assumed (target is internet-facing); token compared with
  `hmac.compare_digest`. 401 on mismatch, 404 when feature unset.
- Request size cap (reject > ~25 MB with 413) and rate limit
  (`@limiter.limit("30 per minute")`) consistent with neighboring endpoints.
- The upload endpoint does NOT use `@login_required` (it is the first
  token-authenticated route in the codebase — see fact sheet note; keep it
  minimal and isolated in its own blueprint `endpoints/sync.py`).
- Never log payload bodies; log source cid, target cid, sizes, and outcome.

## 3. Existing Code Anchors (surveyed 2026-07-07)

- `Conversation.__init__(user_id, openai_embed, storage, conversation_id, domain)`
  — Conversation.py:236; folder `<storage>/<cid>`; `save_local()` at :2863
  (atomic dill `.index`, FileLock, api_keys stripped before dump).
- Per-field storage via `get_field`/`set_field` (Conversation.py:3036/:3184),
  SQLite-backed for messages/memory/settings/artefacts etc.
  (`database/conversation_store.py`, schema :23-99, bulk `import_all` :629).
- **`clone_conversation()` (Conversation.py:2712-2793) is the import template**:
  new Conversation object, copy domain/memory/messages/settings via
  get_field/set_field, `shutil.copytree` artefacts, skip embedding indices,
  `save_local()`. Sync-import mimics this with payload data instead of a
  sibling object.
- Registration of a conversation to a user+workspace:
  `addConversation(user_email, conversation_id, workspace_id, domain, users_dir)`
  (database/conversations.py:52); workspace helpers in `database/workspaces.py`
  (`load_workspaces_for_user` :27, `createWorkspace`,
  `getWorkspaceForConversation` :200). No get-workspace-by-name helper exists —
  resolve `sync` by scanning `load_workspaces_for_user(email, domain)` and
  create it if absent (name match, case-sensitive `"sync"`).
- Clone endpoint pattern to mirror for the sender endpoint:
  `POST /clone_conversation/<cid>` (endpoints/conversations.py:941) —
  limiter + `@login_required` + `get_session_identity()` +
  `state.conversation_cache` fetch.
- Server cache: `state.conversation_cache` (server.py:491) — after import the
  receiver must insert/refresh the cache entry for the target cid (or evict it)
  so a stale cached object is not served.
- Metadata shape: `get_metadata()` (Conversation.py:13599); message dict shape
  Conversation.py:4591-4598; `get_message_list()` :13576.
- UI: context menu items in `buildConversationContextMenu(node)`
  (interface/workspace-manager.js:1683-1790); ajax methods on
  `ConversationManager` (interface/common-chat.js, e.g. `cloneConversation`
  :371 returning a `$.ajax` promise); `showToast` (interface/common.js:6691).
- Env pattern: `os.environ.get(...)` inside `create_app` (server.py:324-327),
  stored in `app.config`.

## 4. Design

### 4.1 Payload format (versioned JSON)

```json
{
  "sync_version": 1,
  "source": {
    "conversation_id": "<source cid>",
    "user_id": "<source user email>",
    "host_label": "<optional free-text, e.g. 'laptop'>",
    "exported_at": "2026-07-07T18:00:00Z"
  },
  "domain": "<domain>",
  "metadata": { ...get_metadata() subset: title, summary_till_now, flag, ... },
  "memory": { ...get_field("memory") },
  "messages": [ ...get_field("messages") — full list, all fields as-is ],
  "conversation_settings": { ...get_field("conversation_settings") },
  "uploaded_documents": [ {"title": "...", "source": "..."} ],
  "artefact_metadata": [ ...get_field("artefacts") — list of artefact meta dicts ],
  "artefact_message_links": { ... },
  "artefacts": [ {"path": "relative/name.ext", "b64": "..."} ],
  "content_hash": "<sha256 of canonical-JSON of everything above>"
}
```

Note: `artefact_metadata` holds the artefact metadata dicts (id/name/filename/
filetype), while `artefacts` holds the inlined file bytes keyed by `path`
(== filename). Receiver sets `artefacts` field from `artefact_metadata` and
writes the decoded bytes from `artefacts` into the target `artefacts/` dir.

Notes:
- `messages` are copied verbatim (sender: `get_field("messages")`; they are
  plain dicts). No slimming in v1 — full fidelity reads best and the size cap
  guards the pathological case. A `?slim=1` variant can come later if needed.
- `content_hash` enables sender-side no-op detection (see §4.4) and receiver
  integrity check.
- `sync_version` gates future format changes; receiver rejects unknown major
  versions with 400.

### 4.2 Receiver: `POST /sync/upload` (new blueprint `endpoints/sync.py`)

1. Feature gate: if `app.config["SYNC_UPLOAD_TOKEN"]` unset → 404.
2. Auth: `Authorization: Bearer <token>`; `hmac.compare_digest` → else 401.
3. Validate early (400 on failure): JSON body, `sync_version == 1`,
   non-empty `source.conversation_id`, `domain`, `messages` is a list.
   Enforce size cap (413).
4. **Deterministic target cid**: `f"{SYNC_UPLOAD_USER_EMAIL}_sync_{sha256(source_user_id + '|' + source_cid).hexdigest()[:24]}"`.
   Deterministic ⇒ idempotent upsert; prefix keeps it recognisably synced and
   collision-safe across multiple source hosts/users.
5. Upsert:
   - If target folder exists: load via cache/`load_local`, overwrite fields
     (`set_field(..., overwrite=True)` semantics — memory, messages,
     conversation_settings, artefact_message_links), replace `artefacts/` dir
     contents from payload, update title/summary in memory, `save_local()`.
   - Else: create `Conversation(SYNC_UPLOAD_USER_EMAIL, None, state.conversation_folder,
     target_cid, domain)` (embedder None — mirrors clone which passes
     openai_embed=None; indices rebuild lazily if ever needed), set fields as
     above, `save_local()`, then register: resolve-or-create `sync` workspace
     for (user, domain) and `addConversation(user, target_cid, sync_ws_id, domain, users_dir)`.
   - Either way: refresh/evict `state.conversation_cache[target_cid]`; update
     cross-conversation search index metadata (same call sites as
     create/clone use — `update_metadata` / `update_conversation_workspace`).
6. Store provenance in `conversation_settings["sync_source"] = payload["source"] + {"content_hash": ...}` —
   used for the upsert no-op check and for display ("synced from <host_label>").
7. Respond `{"status": "ok", "target_conversation_id": ..., "updated": bool}`.

Receiver-side conversation is a normal conversation afterward — readable,
even continuable (diverges; by design re-sync overwrites it).

### 4.3 Uploaded documents & artefacts

- `uploaded_documents_list` tuples reference the *source host's* canonical
  document store — paths will not resolve on the target. v1 syncs only
  `{title, source}` display info into `uploaded_documents` (payload) and the
  receiver stores it under `conversation_settings["sync_source_documents"]`
  for display; it does NOT populate `uploaded_documents_list` (avoids broken
  doc references). Document binary sync is a possible v2 (upload doc files by
  hash to the shared doc store) — out of scope now.
- `artefacts/` are real per-conversation files and are included base64-inline
  (bounded by the payload size cap). Individually skipped with a warning list
  in the response if any single file exceeds ~5 MB.
- Embedding indices / raw_documents_index: never synced (clone doesn't copy
  them either).

### 4.4 Sender: `POST /sync_conversation/<conversation_id>` (same blueprint)

Session-authenticated (normal stack: limiter 25/min + `@login_required` +
`checkConversationExists` guard, mirroring `/clone_conversation`):
1. Feature gate: `SYNC_REMOTE_URL`/`SYNC_REMOTE_TOKEN` unset → 400 with clear
   message ("sync not configured on this server").
2. Build payload (§4.1) from the cached conversation object.
3. No-op optimisation: keep `conversation_settings["last_sync"] = {url, content_hash, at}`
   on the *source*; if unchanged hash for same URL → return
   `{"status": "ok", "skipped": true}` without an HTTP call. `?force=1` bypasses.
4. `requests.post(f"{SYNC_REMOTE_URL}/sync/upload", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=60)`.
5. Map outcomes: 2xx → update `last_sync`, return target cid; 401/404/413/5xx →
   4xx/502 to the browser with the target's error message surfaced.

`GET /sync/config` (login_required): `{"sync_send_enabled": bool}` — lets the
UI decide whether to show the menu item.

### 4.5 UI (interface/)

- `ConversationManager.syncConversation(conversationId)` in
  interface/common-chat.js — `$.ajax POST /sync_conversation/<cid>`, returns
  promise (pattern of `cloneConversation` :371).
- Menu item `syncToRemote` in `buildConversationContextMenu`
  (workspace-manager.js:1683-1790): label "Sync to remote", icon e.g.
  `fa-cloud-upload`; action calls `syncConversation(...)` →
  `.done(r => showToast(r.skipped ? 'Already in sync' : 'Synced to remote', 'success'))`
  `.fail(x => showToast('Sync failed: ' + (x.responseJSON?.message || x.statusText), 'error'))`.
  Item included only when the cached `/sync/config` says sending is enabled
  (fetch once at startup alongside other init config; default hidden).
- No list refresh needed on the source; nothing changes locally except
  `conversation_settings.last_sync`.

### 4.6 Receiver display niceties (small, optional in v1)

- The `sync` workspace is a normal workspace; nothing special needed to list it.
- Optional: in the conversation header on the target, if
  `conversation_settings.sync_source` exists, render a muted badge
  "synced from <host_label> · <exported_at>". `host_label` comes from the
  sender's optional `SYNC_HOST_LABEL`; when empty the badge shows the date only.
  INCLUDED this pass (see §0.7). Pure display.

## 5. Alternatives Considered

- **Long-polling worker on the source host** (cloud pulls work): solves remote
  *execution*, not remote *reading*; requires an always-on daemon and job
  tables. Rejected as overkill for this need.
- **rsync/scp of the conversation folder**: no workspace registration, no
  SQLite upsert safety, dill `.index` embeds absolute-ish state and user ids;
  bypasses the app's locking. Rejected.
- **Browser-side POST to the target**: leaks token to the client, CORS pain.
  Rejected in favour of server-side push.
- **Random target cid + mapping table**: deterministic hash cid achieves upsert
  without new tables. Chosen.
- **Reusing the dill blob as the wire format**: dill is code-version- and
  host-coupled and unsafe to unpickle across trust boundaries. Versioned JSON
  chosen.

## 6. Risks / Open Points for the Implementer

- First token-auth route in the codebase: keep it in its own blueprint, no
  session access, and make the 404-when-unconfigured behaviour explicit in
  tests, so it cannot become an accidental unauthenticated surface.
- `set_field` overwrite semantics for list fields (messages) must replace, not
  append — verify against Conversation.set_field(:3184)/SQLite `import_all`
  and use whichever guarantees replacement (a `delete-then-import_all`
  transaction on `conversation.db` is the clean path for the update case).
- Target user must exist / be login-able on the target instance
  (`SYNC_UPLOAD_USER_EMAIL` should be the email the user logs in with there);
  document this in the ops notes.
- Cache coherence on receiver: evict target cid from `state.conversation_cache`
  before import if present, insert fresh after `save_local()`.
- Message field drift between instances running different code versions:
  receiver must tolerate unknown message keys (store verbatim) and missing
  optional keys — messages are opaque dicts to the sync layer.
- Rate/size limits are the only DoS guard on a public endpoint; keep the 413
  check *before* JSON parsing (use `request.content_length`).

## 7. Task Breakdown (implementation order)

1. **Receiver core** — `endpoints/sync.py` blueprint: config gating, bearer
   auth, validation, deterministic cid, create-path import (new conversation +
   `sync` workspace resolve/create + registration + cache insert). Register
   blueprint + CORS rule in server.py; read the two env vars in `create_app`.
2. **Receiver upsert path** — existing-target overwrite (fields + artefacts +
   provenance + cache refresh + search-index update).
3. **Sender** — payload builder on `Conversation` (small method, e.g.
   `export_sync_payload()` near `get_metadata`), `/sync_conversation/<cid>` +
   `/sync/config` endpoints, `last_sync` no-op logic.
4. **UI** — `ConversationManager.syncConversation`, context-menu item gated on
   `/sync/config`, toasts.
5. **Verification** — two-instance local test: run two servers on different
   ports with distinct `--folder` storage roots; instance A gets
   `SYNC_REMOTE_URL=http://localhost:<portB>` + token, instance B gets
   `SYNC_UPLOAD_TOKEN` + `SYNC_UPLOAD_USER_EMAIL`. Script: create conv on A
   with a few messages → sync → assert target folder, workspace `sync`
   registration row, message count/text equality, idempotent re-sync
   (`updated: true`, no duplicate), hash-skip second call, 401 bad token,
   404 unconfigured, 413 oversized.
6. **Docs** — feature doc under `documentation/features/` (motivation, env
   vars, API contract, UI, files modified) + entry in documentation/README.md.

Each of 1-4 is independently committable; 1+3 alone give a curl-testable
end-to-end path before any UI work.
