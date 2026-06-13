# PKB / TMS as a Standalone System — Extraction, Standalone UI, MCP, REST API, Auth & Agent Integration

**Status:** In Progress — M1 done, T0.1 partial (provider protocol + config), T3.1 done (dual-auth decorator), T4.1 done (token endpoint)
**Created:** 2026-06-09
**Revised:** 2026-06-10; 2026-06-11 (sync with landed `backfill_entities` REST route + DB concurrency fix — see §1, §9, §12); 2026-06-12 (**major re-scope** — PKB is now to become a standalone, separately-hostable system; added Workstream 0 extraction + explicit independence goals — see §0, §2, §3.0, §8); 2026-06-12b (sync surface counts, keyParser bug fix, maintenance UX overhaul, LLM smart consolidation, schema v14 — see §1, §9, §12); 2026-06-13 (landed: LLMProvider protocol, CodeCommonProvider, PKBConfig model fields, dual-auth decorator, /pkb/token endpoint — all non-breaking/additive)
**Scope:** Turn the PKB/TMS into an **independent, separately-hostable system** that runs in three modes — (a) an importable Python **library**, (b) a self-contained **HTTP server with its own bundled UI**, and (c) a standalone **MCP server** — usable by *any* assistant or coding service (Claude Code, OpenCode, Cursor, scripts), **while preserving the existing in-chat-app integration unchanged**. This subsumes the original narrower scope (a `/memory/` page, external MCP, token REST API, dual-auth, agent recipes), which now becomes the set of *surfaces built inside the extracted package* rather than inside the chat app.

Internal memory-system improvements are covered separately in `pkb_memory_system_improvements.plan.md`, `pkb_ux_improvements.plan.md`, `pkb_retrieval_ranking.plan.md`, and `pkb_rewrite_entity_unification.plan.md` (the latter added the `backfill_entities` maintenance op now exposed over REST — see §1).

---

## 0. Primary Objective & Guiding Goals (user-stated)

> **The PKB should become a mostly-independent system that can be hosted separately and used with other assistants and coding services (e.g. Claude Code). It must be able to start as (1) an HTTP server — which also serves its own UI, (2) an MCP server, and (3) an import-enabled library. Building this MUST NOT break the current chat-app integration; the chat app continues to consume PKB as one of its hosts.**

Everything in this plan is in service of that objective. The litmus test for "done": a developer can `pip install` (or vendor) the PKB package into a fresh environment with **no chat-app code present**, point it at a storage dir + an LLM provider + a JWT secret, and run any of:

```bash
python -m truth_management_system serve-http   # REST API + bundled web UI
python -m truth_management_system serve-mcp    # MCP server for agents
python -c "from truth_management_system import StructuredAPI; ..."   # library
```

…and the existing chat app, unchanged from a user's perspective, still embeds the same PKB as a library + mounted blueprint.

---

## 1. Background & Motivation

Today the PKB is reachable only from inside the logged-in chat app:
- **UI:** the PKB lives as Bootstrap modals (`#pkb-modal` with 9 tabs: Claims/Entities/Tags/Conflicts/Bulk/Import/Contexts/Overview/Maintenance, plus `#pkb-claim-edit-modal`, `#memory-proposal-modal`) inside `interface/interface.html`, driven by the `PKBManager` IIFE in `interface/pkb-manager.js`. There is no dedicated URL — no `memory.html`, no `/memory` route, no `init()` on PKBManager.
- **REST:** `endpoints/pkb.py` exposes 83 routes under `/pkb/*` (incl. the new `POST /pkb/backfill_entities` maintenance route added by the rewrite/entity unification work — `dry_run` defaults True, gated on `OPENROUTER_API_KEY`), all guarded by `@login_required` (Flask session via Google OAuth) — unusable by external programmatic clients. No bearer token auth exists anywhere in the REST layer. `endpoints/auth.py` only has `generate_remember_token`/`verify_remember_token` for session "remember me" — not suitable for API access.
- **MCP:** `mcp_server/pkb.py` implements a JWT-authenticated streamable-HTTP MCP server (port 8101) with **27 tools** (19 baseline + 8 full tier). Auth handled by `mcp_server/auth.py` (HS256 JWT with `{email, scopes, iat, exp}`). **Security gap:** `user_email` is a client-supplied parameter in every tool — NOT derived from the JWT. The server trusts whatever email the client passes.
- **nginx:** `documentation/planning/nginx_mcp_blocks.conf` has ready-to-paste location blocks for `/mcp/pkb/` → `localhost:8101` (and 7 other servers), but these are NOT deployed yet.

Goal: a clean, authenticated "memory anywhere" surface — a bookmarkable UI at `https://assist-chat.site/memory/`, plus MCP and REST endpoints an external agent (Claude Code, OpenCode, scripts) can connect to with a per-user token.

### Current coupling — why "host it separately" needs an extraction step (verified 2026-06-12)

The dependency direction today is **favorable but not yet inverted**. Verified by import analysis:

- **The PKB *core* (`truth_management_system/`) is already nearly self-contained.** Its only "upward" dependency on the chat app is `code_common.call_llm` (LLM calls, embeddings, keyword extraction), imported *lazily* in ~22 call sites across `llm_helpers.py`, `search/*`, and `interface/*`. It already exposes a library entrypoint — `StructuredAPI` (`truth_management_system/interface/structured_api.py`) — plus its own `PKBConfig`, DB layer (`get_database`), scheduler, and `truth_management_system_requirements.md`.
- **`code_common/call_llm.py` itself** depends on chat-app top-level modules `loggers` (`getLoggers`) and `common` (lazy). This is the one hard seam to abstract.
- **The REST layer `endpoints/pkb.py` is NOT independent** — it is a Flask blueprint wired into chat-app infra: `endpoints.auth` (`login_required`), `endpoints.responses` (`json_error`), `endpoints.session_utils` (`get_session_identity`), `endpoints.state` (`get_state().users_dir` for the DB path), `endpoints.utils` (`keyParser`), `extensions.limiter`, `base.get_async_future`, `common.CHEAP_LLM`.
- **The MCP layer `mcp_server/pkb.py` rides on the REST layer** — it imports `from endpoints.pkb import get_pkb_db, serialize_context, serialize_entity, serialize_tag` and `endpoints.utils.keyParser`.
- **The UI (`interface/pkb-manager.js`)** lives in the chat-app interface and depends on `interface/common.js` helpers + the chat shell.

**Implication:** Today PKB is *embedded in* the chat app, not a system the chat app embeds. The original version of this plan added external surfaces but left every one of them inside `endpoints/` / `mcp_server/` / `interface/` — so "host PKB separately" was **not** achievable (you'd still need the whole chat app running). The re-scope (Workstream 0, §3.0) inverts this: move the surfaces *into the package*, abstract the LLM dependency behind an injected provider, and reduce the chat app to one host/adapter. Because the core only points "down" to `code_common`, this extraction can be done **without breaking chat integration**.

### Current surface area (post v1.0 UX improvements)

| Surface | Count | Auth |
|---------|-------|------|
| REST endpoints | 94 | Session only (`@login_required`) |
| MCP tools | 32 (22 baseline + 10 full) | JWT header, email from JWT (T2.1 landed) |
| LLM tools (in-chat) | 26 | Implicit (session user) |
| NL agent actions | 14 | Implicit (session user) |
| structured_api methods | 103 | Called server-side with known email |
| UI tabs | 9 | Session |

### Key code references
- `endpoints/static_routes.py` — `/interface` + `/interface/<path:path>` serve `interface/interface.html`; `/` redirects to `/interface`. Auth via `@login_required`.
- `endpoints/auth.py` — `login_required` decorator (checks `session["email"]`/`["name"]`); `generate_remember_token`/`verify_remember_token` for remember-me only.
- `endpoints/session_utils.py` — `get_session_identity()` → `(email, name, loggedin)`.
- `endpoints/pkb.py` — all 83 `/pkb/*` routes (`@login_required` + `get_session_identity()`).
- `mcp_server/pkb.py` — `create_pkb_mcp_app(jwt_secret, rate_limit)`; 27 tiered tools; `PKB_MCP_PORT=8101`.
- `mcp_server/auth.py` — `generate_token(secret, email, days=365, scopes=["search"])` → HS256 JWT; `verify_jwt(token, secret)` → payload or None. `JWTAuthMiddleware` extracts bearer token. Stateless — no revocation.
- `documentation/planning/nginx_mcp_blocks.conf` — ready location blocks for all 8 MCP servers.
- `documentation/product/ops/mcp_server_setup.md` — ports 8100-8108, shared `MCP_JWT_SECRET`.

---

## 2. Goals & Success Criteria

**Foundational goals (G0\*) — standalone independence.** These are the user-stated objective (§0) and are *prerequisites* for the surface goals (G1–G6) being deliverable as a separately-hostable system. G1–G6 are now interpreted as "…built inside the extracted package."

| # | Goal | Success criteria |
|---|------|------------------|
| **G0a** | **Library mode** | `import truth_management_system` / `from truth_management_system import StructuredAPI` works in an env with **no chat-app modules**, given only config + an LLM provider |
| **G0b** | **HTTP server mode + own UI** | `python -m truth_management_system serve-http` starts a self-contained REST API **and serves its own bundled web UI**, with no dependency on `endpoints/`, `extensions`, `base`, `common`, or `interface/` |
| **G0c** | **MCP server mode** | `python -m truth_management_system serve-mcp` starts the MCP server importing only the package's own API + auth (not `endpoints.pkb`) |
| **G0d** | **Chat integration preserved** | The existing chat app embeds PKB as a library + mounted blueprint; in-chat modal, `@references`, slash commands, STM capture, proposals all behave exactly as before |
| **G0e** | **LLM/embedding dependency injected** | PKB core depends on an `LLMProvider` interface, not directly on `code_common.call_llm` / `loggers` / `common`; the host supplies the implementation (chat app injects `code_common`, standalone supplies a default OpenAI/OpenRouter-backed provider) |
| **G0f** | **Installable + pinned deps** | The package has its own `pyproject.toml`/requirements and a `__main__` CLI; standalone install pulls only PKB's real dependencies |
| G1 | Standalone PKB UI | `https://assist-chat.site/memory/` renders the full PKB (all 9 tabs) as a first-class page, session-authenticated, no chat shell required |
| G1b | Single source of truth | The standalone page and the in-chat modal render from one `pkb-manager.js` with an `init(container)` entry point; no forked markup |
| G2 | Deep-linkable | `/memory/<friendly_id>` opens that claim/context directly |
| G3 | External MCP (secured) | PKB MCP reachable over HTTPS at `/mcp/pkb/` with bearer token; `user_email` **derived from JWT**, not client-supplied |
| G4 | External REST API | `/pkb/*` callable by external clients with `Authorization: Bearer <token>`, scoped per user |
| G5 | Unified auth | One token type works for both MCP and REST; mintable from the UI; scoped + revocable |
| G6 | Documented integration | Copy-paste setup for Claude Code / OpenCode + curl examples |

### Non-goals
- Public/unauthenticated access.
- A separate SPA framework — reuse existing jQuery/Bootstrap + `pkb-manager.js` (now vendored into the package's UI bundle).
- OAuth client-credentials / third-party app authorization flows (future).
- Mobile-specific responsive layout (future).
- **Rewriting PKB core logic.** Workstream 0 is a *structural* extraction (move modules, invert one dependency via an injected provider, add entrypoints/packaging) — **not** a rewrite of search, storage, or claim logic. Behavior must be identical before/after.
- **Splitting into a separate git repository (for now).** The package stays in this monorepo under `truth_management_system/`; "separately hostable" means *independently installable/runnable*, not necessarily a different repo. A repo split can follow once the import boundary is clean.

---

## 3.0 Workstream 0 — Extract PKB into a standalone, embeddable package (G0a–G0f)

**This is the foundational workstream. It must land first** — WS1–WS5 are then built *inside* the package, and the chat app is reduced to a thin host. The guiding principle: **invert the dependency** so the chat app depends on the PKB package, never the reverse. Do it incrementally so the chat app keeps working after every step.

### Design: layering after extraction

```
truth_management_system/                  (the standalone package)
├── core/ (existing)        claims, entities, tags, search, storage, scheduler, config
├── providers/              LLMProvider protocol + default impl  ◀── replaces direct code_common dep
├── interface/structured_api.py   StructuredAPI  (library entrypoint, G0a)
├── auth/                   JWT mint/verify + dual-auth + scopes  (moved from mcp_server/auth.py)
├── http/                   self-contained Flask/ASGI app + blueprint (G0b)
├── ui/                     vendored pkb-manager.js + memory.html + minimal utils (G0b)
├── mcp/                    MCP server importing the package API (G0c)
├── __main__.py             CLI: serve-http | serve-mcp  (G0b/G0c)
└── pyproject.toml          packaging + pinned deps (G0f)

chat app (host)             imports the package; mounts its blueprint; injects code_common LLM provider; keeps its own modal UI (G0d)
```

### T0.1 Define and inject an `LLMProvider` (G0e) — the critical seam

**Verified coupling inventory (2026-06-12) — this is the *entire* upward dependency of the TMS core.** Import analysis shows the core imports **nothing** from `loggers`, `base`, `server`, `prompts`, `endpoints`, or `extensions`, and from `code_common` it uses **only** `call_llm`. The complete surface to decouple:

| # | Coupling | Symbols | Sites | Current hardness | Removal |
|---|----------|---------|-------|------------------|---------|
| C1 | `code_common.call_llm` | `call_llm` (12), `get_query_embedding` (5), `get_document_embedding` (3), `getKeywordsFromText` (2) | ~22 | Lazy (inside functions) | Inject `LLMProvider` |
| C2 | `common` model lists | `CHEAP_LLM` (2), `SUPERFAST_LLM` (1) | 3 | Lazy | Promote to `PKBConfig` model fields |
| C3 | `common.time_logger` | `time_logger` | 5 | **Already guarded** (`try/except ImportError → time_logger = logger`) | Inject a logger object |

**Already clean — no work required (confirmed):**
- **API keys:** injected as a `keys` dict param — `StructuredAPI(db, keys, config)` → `self.keys` → `call_llm(self.keys, model, prompt, …)`; `call_llm` reads only `keys["OPENROUTER_API_KEY"]`. No chat-app global. Standalone builds the same dict from env. **Note (2026-06-12):** A bug was found where 14 REST endpoints in `endpoints/pkb.py` failed to call `keyParser(session)` before constructing the API — causing embedding store and LLM operations to fail silently. All 94 endpoints are now fixed. The extraction must ensure the standalone HTTP layer replicates this key-passing pattern (env-var fallback → per-request session override).
- **Prompts:** fully self-contained inside TMS modules — zero imports from a main-repo prompts module.
- **Other chat-app modules:** none imported by the core.

So **C1 (the `LLMProvider`) is ~90% of the decoupling; C2 and C3 are trivial.**

**Fix — four moves (all preserve behavior; chat app injects host objects, standalone supplies defaults):**

1. **LLMProvider protocol (C1).** Define in `truth_management_system/providers/base.py`:
   ```python
   class LLMProvider(Protocol):
       def call_llm(self, keys, model, prompt, **kw) -> str: ...   # mirror code_common.call_llm signature
       def get_query_embedding(self, text, **kw) -> list[float]: ...
       def get_document_embedding(self, text, **kw) -> list[float]: ...
       def get_keywords(self, text, **kw) -> list[str]: ...
   ```
   Mirror the existing `code_common.call_llm` call signatures so the swap is 1:1. Carry the provider on `PKBConfig`/`StructuredAPI`. Two impls:
   - `providers/codecommon_provider.py` — thin wrapper over `code_common.call_llm` (chat-app host; zero behavior change).
   - `providers/default_provider.py` — self-contained OpenRouter/OpenAI impl (standalone; no `loggers`/`common`). Must match models + embedding dimensions (pin `embedding_model`).
   Replace all ~22 `from code_common.call_llm import …` sites with calls through the injected provider. Exhaustive — add a source-guard test (like the M1 guard) asserting no `from code_common` import remains in core paths.

2. **Logger injection (C3) — allow passing a logger object.** Let `PKBConfig`/`StructuredAPI` accept an optional `logger` (and `time_logger`); default to `logging.getLogger("truth_management_system")` when not supplied. Replace the 5 guarded `from common import time_logger` sites with the injected `time_logger` (fall back to the module logger if `None`, preserving today's behavior). The chat app passes its `common.time_logger` (keeps timing visibility); standalone gets stdlib logging. This removes the last `common` import path and gives hosts full control of logging.

3. **Internalize model config (C2).** Add `PKBConfig` fields — e.g. `fast_llm_model: str` and `superfast_llm_model: str` (defaults mirroring today's first-choice models, e.g. `"anthropic/claude-haiku-4.5"` and `"inception/mercury-2"`) — and replace the 3 `CHEAP_LLM`/`SUPERFAST_LLM` borrow sites with config reads. The chat app may override these from its `common` lists at construction time if it wants identical selection; standalone uses the config defaults. (`PKBConfig` already has `llm_model`/`embedding_model`, so this just extends an existing pattern.)

4. **Keys + prompts: nothing to do** — already injected / self-contained (see above). Standalone `__main__` builds `keys = {"OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"]}`.

**Risk control:** land this whole step first and verify the **full TMS suite (302+) passes with the codecommon provider + host logger injected** — proves zero behavior change *before* any file is moved. Then add the source guards (no `code_common`, no `common` imports in core).

### ✅ Full-decouple checklist (definition of done for C1–C3)

The TMS core is fully decoupled when **all** of these hold:
- [ ] `grep -rE "from (code_common|common|loggers|base|server|prompts|endpoints|extensions) " truth_management_system/` (excluding `providers/codecommon_provider.py` and tests) returns **nothing**.
- [ ] All LLM/embedding/keyword calls route through the injected `LLMProvider`.
- [ ] All timing/log calls route through the injected `logger`/`time_logger` (with a stdlib fallback).
- [ ] All model names come from `PKBConfig` fields (no `CHEAP_LLM`/`SUPERFAST_LLM` imports).
- [ ] API keys arrive only via the injected `keys` dict / provider (already true).
- [ ] The package imports cleanly and the full suite passes in an environment where `code_common`, `common`, `loggers`, `base`, `server`, `endpoints`, `extensions`, and `interface` are **not importable** (standalone smoke test, T0.8).
- [ ] The chat app, injecting the codecommon provider + its `time_logger` + (optionally) its model lists, behaves identically (G0d).

### T0.2 Move auth into the package

Move `mcp_server/auth.py` (JWT `generate_token`/`verify_jwt`, `JWTAuthMiddleware`) → `truth_management_system/auth/`. Add the dual-auth decorator + scope logic here (was WS3 T3.1, see §5). `mcp_server/auth.py` becomes a re-export shim for back-compat. No secret/algorithm change.

### T0.3 Build a self-contained HTTP app inside the package (G0b)

Create `truth_management_system/http/app.py` exposing `create_pkb_http_app(config, provider, jwt_secret)` that builds a Flask (or ASGI) app + the `/pkb/*` blueprint **using only the package's own API and auth** — not `endpoints.*`, `extensions`, `base`, `common`.
- Port the route bodies from `endpoints/pkb.py` into a package blueprint. Replace: `get_state().users_dir` → `config.storage_dir`; `keyParser` → provider/config; `extensions.limiter` → an injectable limiter (default: a small in-package limiter); `base.get_async_future` → a package util or stdlib executor; `common.CHEAP_LLM` → provider.
- The chat app's `endpoints/pkb.py` becomes a **thin adapter**: it builds the package blueprint with the chat app's session-auth + injected provider and registers it (so all existing `/pkb/*` URLs and behavior are preserved — G0d).
- Bundle the UI here too (T0.4) so `serve-http` serves it.

### T0.4 Vendor the UI into the package (G0b)

Move/copy `interface/pkb-manager.js`, the new `memory.html` shell (WS1 T1.2), and the minimal helpers (`showToast`, `escapeHtml`, `debounce`) into `truth_management_system/ui/`. The package's HTTP app serves them at `/` (or `/ui/`). The chat app keeps its in-chat modal pointing at the same `pkb-manager.js` (now sourced from the package, or a build step copies it) so there is still **one canonical UI implementation** (G1b).

### T0.5 Build the MCP server inside the package (G0c)

Move `mcp_server/pkb.py` logic → `truth_management_system/mcp/server.py`, importing the package `StructuredAPI` + `auth` directly (drop `from endpoints.pkb import ...`; move `serialize_context/entity/tag` into the package). `mcp_server/pkb.py` becomes a thin shim that calls the package factory (preserves the existing 8-server MCP launcher + ports). The M1 `_effective_email` fix (already landed) moves with it.

### T0.6 CLI entrypoint + packaging (G0b/G0c/G0f)

Add `truth_management_system/__main__.py` with subcommands `serve-http`, `serve-mcp` (and `mint-token`), and a `pyproject.toml` declaring the package + **pinned** real dependencies (flask/starlette, mcp, openai, numpy, sqlite-backed deps, jwt, etc.). Standalone storage path + secret come from env/flags/`PKBConfig`.

### T0.7 Storage & config independence

`PKBConfig` already has `db_path`. Add a `storage_dir`/multi-user resolution that does not require `endpoints.state`. Decide single-user vs multi-user for standalone (see Open Questions §11) — default standalone to a configurable per-user dir keyed by the JWT email, mirroring chat-app behavior.

### T0.8 Verification gates

- TMS suite green after T0.1 (provider injection) — **before** any move.
- After each move (auth/http/mcp/ui), chat app boots, `/pkb/*` behaves identically, in-chat modal works, MCP tools work.
- New: a standalone smoke test that imports the package in an env with `endpoints`/`server`/`interface` *not importable* (e.g. `sys.modules` block or a venv) and runs library + `serve-http` + `serve-mcp` against a temp storage dir.

### Sequencing within WS0
T0.1 (provider) → T0.2 (auth) → T0.3 (http app) + T0.4 (ui) → T0.5 (mcp) → T0.6 (cli/packaging) → T0.7/T0.8. Each step keeps the chat app working.

---

## 3. Workstream 1 — Standalone `/memory/` UI (G1, G2)

> **Re-scope note (2026-06-12):** Build this *inside the package* (`truth_management_system/ui/` + the package HTTP app from T0.3/T0.4). The chat app's `/memory` route and in-chat modal both consume the package's `pkb-manager.js`. The tasks below are unchanged in substance; only their home moves into the package.

**Design principle:** one canonical PKB UI implementation, reused everywhere. The standalone `/memory/` page and the in-chat modal render from the **same** `pkb-manager.js`, so they stay in sync automatically.

### Approach: add `init(container)` to PKBManager + create a thin shell page

- **T1.1 Add `PKBManager.init(containerSelector)`.** Today PKBManager is an IIFE that assumes its DOM exists inside `#pkb-modal`. Refactor to accept a container: when `containerSelector` is given, render the 9-tab UI directly into that element (no `.modal()` calls). When no container is given (or `#pkb-modal` exists), preserve current modal behavior. This requires:
  - Moving the tab HTML into a template string (or a `<template>` tag in interface.html that both paths consume).
  - Guarding all `$('#pkb-modal').modal(...)` calls behind a `isModal` flag.
  - Ensuring all `/pkb/*` AJAX calls work identically in both contexts (they will — same session cookie).

- **T1.2 Create `interface/memory.html`** — a thin full-page shell:
  ```html
  <!DOCTYPE html>
  <html>
  <head>
    <title>Memory — PKB</title>
    <!-- Same CSS deps as interface.html: Bootstrap 4.6, bootstrap-icons, custom styles -->
  </head>
  <body>
    <nav><!-- minimal header: logo, user name, back-to-chat link --></nav>
    <div id="memory-root" style="max-width:1200px; margin:0 auto; padding:20px"></div>
    <div id="memory-deeplink" data-ref="" style="display:none"></div>
    <!-- JS deps: jQuery, Bootstrap, shared utils (showToast, escapeHtml), pkb-manager.js -->
    <script>
      $(function() {
        PKBManager.init('#memory-root');
        var ref = $('#memory-deeplink').data('ref');
        if (ref) PKBManager.openByReference(ref);
      });
    </script>
  </body>
  </html>
  ```
  Extract the minimal subset of `common.js` helpers needed (`showToast`, `escapeHtml`, `debounce`) into a `common-utils.js` or include `common.js` with a guard.

- **T1.3 Add Flask route** in `endpoints/static_routes.py`:
  ```python
  @static_bp.route("/memory", strict_slashes=False)
  @static_bp.route("/memory/<path:path>", strict_slashes=False)
  @login_required
  def memory_ui(path: str = ""):
      if path:
          html = open(os.path.join("interface", "memory.html")).read()
          div = f'<div id="memory-deeplink" data-ref="{path}" style="display:none"></div>'
          return Response(html.replace("</body>", div + "</body>"), mimetype="text/html")
      return send_from_directory("interface", "memory.html", max_age=0)
  ```

- **T1.4 Deep-link handling (G2).** `PKBManager.openByReference(ref)` calls `GET /pkb/claims/by-friendly-id/<ref>` or `GET /pkb/resolve/<ref>` and opens the edit modal or context view.

- **T1.5 No backend changes** — reuse existing session-authenticated `/pkb/*` endpoints.

- **T1.6 nginx:** none required — nginx already proxies `/` → `localhost:5000`.

### Chat-integrated touchpoints (stay in-page, NOT in the standalone UI)
These remain as direct `PKBManager` calls within `interface.html`:
- `@reference` autocomplete in chat input
- "Save to Memory" from message context menu
- `/pkb` and `/memory` slash commands
- "Use in next message" pending-attachments indicator
- Memory proposal modals (`#memory-proposal-modal`, tool-call modal)
- STM capture toasts

### Optional: iframe the management view in the main chat app
For CSS/JS isolation, the in-chat modal *may* iframe `/memory/` (same-origin, session cookie inherited). Only do this if the shared-template approach causes CSS/DOM conflicts. Adds complexity (postMessage bridge for `open-add-with-text`, `switch-tab`; double jQuery load; iframe sizing).

**Recommendation:** Ship `init(container)` + shared template first. Add iframe only if isolation proves necessary.

### Challenges
- The `pkb-manager.js` refactor (T1.1) must not regress the in-chat modal. Gate all modal calls with `if (isModal)`.
- Audit `common.js` dependencies used by PKBManager — may need to extract a standalone utility bundle.
- The 9-tab template is ~300 lines of HTML — embedding as a JS template string is feasible but consider a `<template id="pkb-template">` approach for maintainability.
- **(2026-06-12):** The Maintenance tab is now significantly more complex than originally scoped — it has per-item checkboxes, selective apply with multiple endpoint calls (consolidation/merge, bulk_action, entities/merge, tags/merge), health dashboard, fading memories with reinforce, recently archived with restore, and LLM-assisted smart consolidation. The full-page layout will benefit this tab the most. See `pkb_maintenance_ux_polish.plan.md` for remaining UX gaps.

---

## 4. Workstream 2 — Secure External MCP (G3)

> **Re-scope note (2026-06-12):** The MCP server moves into the package (`truth_management_system/mcp/`, WS0 T0.5). T2.1 (below) already landed and its `_effective_email` fix travels with the move. T2.2–T2.5 still apply, now against the package's MCP factory.

The MCP server exists and works. Two tasks: deploy externally via nginx, and fix the `user_email` security gap.

### T2.1 Fix `user_email` derivation (SECURITY — MUST DO FIRST) — ✅ DONE 2026-06-11

**Status:** Landed. `mcp_server/pkb.py` now derives the effective email from the
JWT, not the client argument.

**Was:** Every MCP tool took `user_email` as an explicit parameter and called
`api.for_user(user_email)` with the client-supplied value. The JWT middleware
validated the token but did NOT enforce that `user_email` matched
`token["email"]` — so a holder of any valid token could read/modify any user's
PKB (broken object-level authorization / IDOR).

**Fix (as implemented):** `JWTAuthMiddleware` already stashes the verified token
identity in the `_mcp_request_context.user_email` thread-local (it was used only
for history logging). Added `_effective_email(supplied)` in `mcp_server/pkb.py`
which returns that trusted identity, **ignores** the client-supplied
`user_email` (logging a warning on mismatch), and **fails closed**
(`PermissionError`, surfaced as a JSON error by each tool's `try/except`) when no
authenticated identity is present. All 27 `.for_user(user_email)` call sites now
route through it. The `user_email` argument is kept in the tool signatures for
schema/client hinting but is advisory only. Tests: `tests/test_mcp_pkb_auth.py`
(6, incl. a source guard so a new tool cannot reintroduce the raw pattern).

### T2.1b Verify thread-local identity propagation end-to-end (SECURITY — before external exposure)

**Why:** `_effective_email` (T2.1) trusts `_mcp_request_context.user_email`, a `threading.local` set by `JWTAuthMiddleware`. This is only correct if the **tool executes in the same thread/context** the middleware set it on. That was *assumed* (the web-search MCP server uses the same pattern) but never proven for the PKB server end-to-end. If FastMCP dispatches tools on a different thread/async task, the identity could be **missing** (fail-closed — safe) or, worst case if a worker thread is reused across requests, **stale/wrong** (cross-user data exposure).

**Task — a two-identity integration test (must pass before M3 deploys MCP externally):**
1. Spin up the PKB MCP ASGI app with a test `MCP_JWT_SECRET`.
2. Mint two tokens for `alice@` and `bob@`; seed one claim in each PKB.
3. Issue **concurrent/interleaved** tool calls (e.g. `pkb_search`, `pkb_add_claim`) with each token and assert each call only ever sees/writes its own user's data — never the other's — across many iterations to flush out thread reuse.
4. Assert a request with no/invalid token fails closed (no identity leaks from a prior request on the same worker).

If the test reveals propagation is unreliable, switch from `threading.local` to an explicit per-request context (e.g. `contextvars.ContextVar`, or thread the identity through the FastMCP request scope) and re-test.

**Original fix sketch (for reference):** In `JWTAuthMiddleware` or a wrapper,
after JWT validation:
1. Store `request.state.authenticated_email = payload["email"]` (or equivalent for the MCP framework).
2. In each tool function, **ignore** the `user_email` parameter and use the authenticated email from request state.
3. Alternatively, remove `user_email` from tool signatures entirely and inject it from middleware. But this breaks the MCP tool schema for clients that expect to pass it. **Recommended approach:** keep `user_email` in signatures for documentation/client hinting, but override it server-side with the JWT email. Log a warning if they differ.

### T2.2 Deploy via nginx

Apply the existing `/mcp/pkb/` block from `documentation/planning/nginx_mcp_blocks.conf`:
```nginx
location /mcp/pkb/ {
    proxy_pass http://127.0.0.1:8101/;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
Add to `/etc/nginx/sites-available/science-reader` inside the `listen 443 ssl` server block.

### T2.3 Verify server runs persistently

Confirm `PKB_MCP_ENABLED=1` and `MCP_JWT_SECRET` are set in the screen session. Add to the server restart guide if not already there. The MCP server should auto-start with the main app (check `mcp_server/pkb.py` `if __name__` or startup hook).

### T2.4 Tool tier for external use

Default to `full` (all 27 tools) for token holders — they are authenticated power users. The baseline/full split was designed to limit casual in-chat use, not external programmatic access.

### T2.5 Token issuance (shared with Workstream 4)

See §6 T4.1 — provide `/pkb/token` endpoint so users don't need CLI access.

---

## 5. Workstream 3 — Token-authenticated REST API (G4)

> **Re-scope note (2026-06-12):** The dual-auth decorator (T3.1) moves into the package auth module (WS0 T0.2) and the routes into the package HTTP blueprint (WS0 T0.3). The chat app's `endpoints/pkb.py` becomes a thin adapter that mounts that blueprint with session-auth enabled, so the 83 existing `/pkb/*` URLs and their behavior are preserved (G0d). "Replace 83 `@login_required` decorators" (T3.2) is realized by the adapter choosing the auth mode, not by editing 83 sites in the chat app.

**Problem:** All 83 `/pkb/*` routes require Flask session. External agents need bearer token access.

### T3.1 Dual-auth decorator `pkb_auth_required`

Create `endpoints/pkb_auth.py`:
```python
from functools import wraps
from flask import request, session
from mcp_server.auth import verify_jwt
import os

MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET", "")

def pkb_auth_required(f):
    """Accept either Flask session OR Bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Path 1: existing session auth
        if session.get("email"):
            request._pkb_email = session["email"]
            return f(*args, **kwargs)
        
        # Path 2: Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = verify_jwt(token, MCP_JWT_SECRET)
            if payload and "email" in payload:
                request._pkb_email = payload["email"]
                request._pkb_scopes = payload.get("scopes", [])
                return f(*args, **kwargs)
        
        # No auth
        return {"error": "Authentication required", "code": "unauthorized"}, 401
    return decorated
```

Helper to get the authenticated email:
```python
def get_pkb_email():
    return getattr(request, '_pkb_email', None)
```

### T3.2 Replace `@login_required` on `/pkb/*` routes

Replace all 83 `@login_required` decorators in `endpoints/pkb.py` with `@pkb_auth_required`. Replace `get_session_identity()` email extraction with `get_pkb_email()`. This is a mechanical find-replace — the email resolution is the only thing that changes.

### T3.3 Scope enforcement

Map JWT scopes to operations:
- `read` — GET endpoints (search, list, export, resolve, autocomplete)
- `write` — POST/PUT/DELETE endpoints (add, edit, delete, bulk, import)
- `admin` — destructive / maintenance operations (cleanup, sweep, bulk_action archive, `backfill_entities`)

Add a `require_scope(scope)` decorator or check inside `pkb_auth_required`. Session-authenticated users get all scopes implicitly.

### T3.4 Error contract

Already handled — all endpoints use `json_error(...)`. For token-authenticated requests, ensure no HTML redirect on 401 (the dual-auth decorator returns JSON 401, not a redirect).

### T3.5 Rate limiting

Keep existing `@limiter.limit("...")` decorators. Consider per-token stricter limits (e.g., 60/min for token auth vs 200/min for session). Use `request._pkb_email + token_jti` as rate limit key for token requests.

---

## 6. Workstream 4 — Unified Auth & Token Management (G5)

### T4.1 Token issuance endpoint

```python
@pkb_bp.route("/pkb/token", methods=["POST"])
@login_required  # Session-only — must be logged in to mint
def pkb_mint_token():
    email, _, _ = get_session_identity()
    data = request.json or {}
    scopes = data.get("scopes", ["read", "write"])
    days = min(data.get("days", 365), 365)
    token = generate_token(MCP_JWT_SECRET, email, days=days, scopes=scopes)
    return jsonify({"token": token, "expires_in_days": days, "scopes": scopes})
```

### T4.2 Token management UI

In the `/memory/` standalone page (or a Settings section within PKB), add a "Connect External Tools" panel:
- "Generate Token" button with scope checkboxes (read, write, admin) and lifetime dropdown
- Display token once (copy button), never stored server-side
- "Revoke All Tokens" button
- Active token info (when `jti` tracking is added)

### T4.3 Revocation

**Phase 1 (simple):** Per-user `token_version` integer stored in a lightweight JSON/SQLite table. JWT includes `ver` claim. Verifier checks `payload["ver"] >= user_current_version`. "Revoke All" bumps the version → all old tokens instantly invalid.

**Phase 2 (granular):** Add `jti` (JWT ID) claim to each token. Store issued `jti`s with metadata (created_at, label, last_used). Allow revoking individual tokens by `jti`. Check `jti` against a `revoked_jtis` set on each request.

### T4.4 Single secret, single verifier

Both MCP and REST validate against `MCP_JWT_SECRET`. One token works everywhere (G5). Document: rotating the secret invalidates all tokens — provide a "Revoke All + regenerate" workflow in the UI.

### Security considerations
- Tokens grant per-user PKB access — enforce HTTPS-only (already the case).
- Write scopes default to 90-day lifetime; read-only can be 365 days.
- Audit log: record token-authenticated calls (endpoint, email, timestamp) in a lightweight table for abuse detection.
- Never log token values, only `jti` or last-4-chars.

---

## 7. Workstream 5 — Agent Integration Recipes (G6)

### T5.1 Claude Code MCP configuration

```json
{
  "mcpServers": {
    "pkb": {
      "type": "url",
      "url": "https://assist-chat.site/mcp/pkb/",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

Document all 27 tools with one-line descriptions. Note: client should pass their email in `user_email` parameter (server overrides with JWT email for security, but clients should still provide it for tool schema compliance).

### T5.2 OpenCode / Cursor MCP configuration

Same pattern as Claude Code but with OpenCode's config format (`opencode.json` / `mcp` section).

### T5.3 REST quickstart (curl examples)

```bash
# Search memories
curl -H "Authorization: Bearer $TOKEN" \
  "https://assist-chat.site/pkb/search" \
  -d '{"query": "python async patterns", "limit": 5}'

# Add a claim
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://assist-chat.site/pkb/claims" \
  -d '{"statement": "FastAPI uses Starlette under the hood", "claim_type": "fact", "context_domain": "python"}'

# NL command
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://assist-chat.site/pkb/nl_command" \
  -d '{"command": "what do I know about kubernetes?"}'
```

### T5.4 Documentation

Create `documentation/features/truth_management_system/external_access.md`:
- Token generation (UI + CLI)
- MCP setup for Claude Code, OpenCode, Cursor
- REST API authentication
- Scope descriptions
- Revocation
- Troubleshooting

Cross-link from: `documentation/README.md`, `documentation/product/ops/mcp_server_setup.md`, project `readme.md`.

---

## 8. Implementation Milestones

| Milestone | Tasks | Dependency | Effort |
|-----------|-------|------------|--------|
| **M0 — Standalone extraction** ⭐ foundational | T0.1–T0.8 (provider injection, auth/http/mcp/ui move, CLI, packaging) | M1 (done) | Large — but incremental; each step keeps chat app green. **Unblocks true separate hosting (G0a–G0f).** |
| **M1 — MCP security fix** ✅ DONE | T2.1 (user_email override) | None | Small — critical security fix (landed 2026-06-11) |
| **M2 — Token issuance + dual auth** | T4.1 ✅, T3.1 ✅, T3.2, T3.3 | M0, M1 | Medium — enables all external access (built in package) |
| **M3 — MCP external deployment** | T2.2, T2.3, T2.4 | M0, M2 | Small — nginx config + verification |
| **M4 — Standalone UI** | T1.1, T1.2, T1.3, T1.4 | M0 | Medium — JS refactor + new page (vendored in package) |
| **M5 — Token management UI** | T4.2, T4.3 | M2, M4 | Medium |
| **M6 — Integration docs** | T5.1–T5.4 | M2, M3 | Small |

### Progress summary (2026-06-13)

| Task | Status | Commit |
|------|--------|--------|
| T2.1 (MCP user_email fix) | ✅ Done | Landed 2026-06-11 |
| T0.1 partial (LLMProvider protocol + CodeCommonProvider) | ✅ Done | `985ae8ef` — protocol defined, provider impl created, PKBConfig wired. Remaining: replace ~22 `from code_common` import sites. |
| T0.1 partial (C2: model tier config) | ✅ Done | `985ae8ef` — `fast_llm_model`/`superfast_llm_model` added to PKBConfig |
| T3.1 (dual-auth decorator) | ✅ Done | `985ae8ef` — `endpoints/pkb_auth.py` with `pkb_auth_required`, `require_scope()` |
| T4.1 (token mint endpoint) | ✅ Done | `985ae8ef` — `POST /pkb/token` (session-only, scoped, lifetime-capped) |
| T2.1b (thread-local verification) | Pending | Needs integration test before external deployment |
| T0.1 remainder (replace imports) | Next — highest impact | ~22 sites to route through provider |
| T3.2 (swap @login_required → @pkb_auth_required) | After T0.1 | Mechanical find-replace |

**Recommended order:** **M1 ✅ → M0 (extraction, the new critical path)** → M2 → M3 → M6 (external + standalone access working), then M4 → M5 (UI) in parallel or after. The biggest change from the original plan: **M0 is now the backbone** — without it the other milestones produce a chat-app-bound feature, not a hostable system. Within M0, T0.1 (provider injection, verified against the full suite) is the safest first move and the highest-leverage de-risk.

---

## 9. Risks & Cross-Cutting Concerns

- **Extraction regressions (WS0, highest risk):** Moving auth/http/mcp/ui and inverting the LLM dependency touches a lot of surface. Mitigation: do T0.1 (provider injection) first and prove the **full TMS suite (302+) is green with the codecommon provider injected before moving any file**; after each subsequent move, boot the chat app and confirm `/pkb/*`, the in-chat modal, and MCP tools are unchanged. Keep `mcp_server/auth.py`, `mcp_server/pkb.py`, and `endpoints/pkb.py` as thin back-compat shims so existing imports/URLs don't break (G0d). Note: schema is now v14; the `keyParser` pattern (function, not object) must be preserved or replaced with the provider's key-passing interface during extraction.
- **Incomplete dependency inversion (T0.1):** Missing even one `code_common.call_llm`, `common` model-list, or `common.time_logger` site leaves the core coupled and breaks standalone mode. Mitigation: the T0.1 source-guard test asserts that `grep -rE "from (code_common|common|loggers|base|server|prompts|endpoints|extensions) " truth_management_system/` (excluding the codecommon provider shim + tests) returns nothing — see the full-decouple checklist in §3.0 T0.1.
- **Two divergent UI copies:** Vendoring `pkb-manager.js` into the package risks the chat app and package drifting. Mitigation: single source of truth — the package owns `pkb-manager.js`; the chat app references the package copy (symlink/build-copy), per G1b.
- **Default LLM provider parity:** The standalone `default_provider` must match `code_common.call_llm` behavior (models, embedding dims, retry). Mitigation: keep the chat app on the codecommon provider; treat the default provider as best-effort and document supported models. Embedding-dimension mismatch would corrupt vector search — pin the embedding model in `PKBConfig`.
- **Packaging dependency surface (G0f):** `code_common.call_llm` pulls heavy deps (openai, numpy, tiktoken, tenacity, more_itertools). The default provider must declare exactly its real deps so standalone install stays lean.
- **`user_email` trust in MCP (critical) — ✅ RESOLVED 2026-06-11:** Tools now scope to the JWT identity via `_effective_email()` (T2.1), not the client-supplied argument, and fail closed without an authenticated identity. M1's hard prerequisite for external exposure (M3) is satisfied. (This logic moves with the MCP server into the package in T0.5.)
- **Auth redirect vs 401:** Browser paths (session) redirect to `/login`; token paths must return JSON 401. The `pkb_auth_required` decorator handles this by checking auth type before responding.
- **`pkb-manager.js` refactor risk (T1.1):** The IIFE pattern + 9 tabs + many event handlers make refactoring non-trivial. Gate all `.modal()` calls behind `isModal` flag. Test both surfaces.
- **Shared CSS/JS deps:** `memory.html` needs a subset of what `interface.html` loads. Audit and extract minimal deps to avoid loading the entire chat UI.
- **Secret rotation:** Single `MCP_JWT_SECRET` for everything — rotation invalidates all tokens. Document the procedure + provide "Revoke All + regenerate" in UI.
- **Rate limiting abuse:** External tokens widen attack surface. Per-token limits + audit log required.
- **CORS:** Not needed for server-side agents (Claude Code, OpenCode). Only add if browser-based external clients are intended (future).
- **Concurrent DB access (resolved):** Three external surfaces (standalone UI + MCP + REST) plus in-chat use mean the per-user SQLite connection is now hit from multiple threads at once. This was a latent `SQLITE_MISUSE` risk that external access would have amplified. **Resolved** — `PKBDatabase` now guards its shared connection with a re-entrant lock (`threading.RLock`, commit `0fdaa15`); reads/writes are serialized while network/LLM work stays outside the lock. No remaining action for this plan, but external load testing should confirm there is no lock-contention regression under concurrent token clients.

---

## 10. Files Likely Touched

**Workstream 0 — extraction (new package structure):**

| File | Changes |
|------|---------|
| `truth_management_system/providers/base.py` (new) | `LLMProvider` protocol |
| `truth_management_system/providers/codecommon_provider.py` (new) | Wraps `code_common.call_llm` (chat-app host injects this) |
| `truth_management_system/providers/default_provider.py` (new) | Self-contained OpenAI/OpenRouter provider (standalone) |
| `truth_management_system/llm_helpers.py`, `search/*.py`, `interface/*.py` | C1: replace ~22 `code_common.call_llm` imports with provider calls; C3: replace 5 guarded `common.time_logger` imports with injected logger; C2: replace 3 `common.CHEAP_LLM`/`SUPERFAST_LLM` borrows with config reads (T0.1) |
| `truth_management_system/config.py` | Add injected `logger`/`time_logger` + `fast_llm_model`/`superfast_llm_model` fields (T0.1 C2/C3) |
| `truth_management_system/interface/structured_api.py` | Carry/resolve the provider; remains the library entrypoint (G0a) |
| `truth_management_system/auth/` (new) | JWT + dual-auth + scopes (moved from `mcp_server/auth.py`) |
| `truth_management_system/http/app.py` (new) | `create_pkb_http_app()` + `/pkb/*` blueprint, package-only deps (G0b) |
| `truth_management_system/ui/` (new) | Vendored `pkb-manager.js`, `memory.html`, minimal utils (G0b/G1b) |
| `truth_management_system/mcp/server.py` (new) | MCP server importing package API + auth (moved from `mcp_server/pkb.py`) |
| `truth_management_system/__main__.py` (new) | CLI: `serve-http` / `serve-mcp` / `mint-token` (G0b/G0c) |
| `truth_management_system/pyproject.toml` (new) | Packaging + pinned deps (G0f) |
| `mcp_server/auth.py`, `mcp_server/pkb.py` | Reduced to back-compat shims re-exporting from the package |
| `endpoints/pkb.py` | Reduced to a thin adapter that mounts the package blueprint with session auth (preserves all 83 URLs, G0d) |
| `tests/` | Provider-inversion source guard; standalone smoke test (import with chat app absent); MCP/REST auth tests |

**Workstreams 1–6 (built inside the package per re-scope notes):**

| File | Changes |
|------|---------|
| `mcp_server/pkb.py` | Override `user_email` with JWT email in each tool |
| `mcp_server/auth.py` | Add `token_version` check to `verify_jwt`; expose authenticated email |
| `endpoints/pkb_auth.py` (new) | `pkb_auth_required` dual-auth decorator, `get_pkb_email()` |
| `endpoints/pkb.py` | Replace `@login_required` with `@pkb_auth_required`; add `/pkb/token` |
| `endpoints/static_routes.py` | `/memory` route |
| `interface/memory.html` (new) | Standalone PKB shell page |
| `interface/pkb-manager.js` | Add `init(container)`, `isModal` gate, `openByReference(ref)` |
| `interface/common-utils.js` (new, optional) | Extracted shared utilities (showToast, escapeHtml) |
| nginx config | Add `/mcp/pkb/` location block |
| `documentation/features/truth_management_system/external_access.md` (new) | Integration guide |
| `documentation/product/ops/mcp_server_setup.md` | Update tool counts (27), add external access section |
| `documentation/README.md` | Add external access entry |

---

## 11. Open Questions

1. ~~Subdomain vs path for MCP exposure?~~ **Resolved:** Use `/mcp/pkb/` path — config already prepared in `nginx_mcp_blocks.conf`.
2. Default token lifetime: 365 days for read, 90 days for write? Or uniform 365?
3. Should `/memory/` support PWA install (add to `manifest.json`)?
4. For revocation phase 1, use SQLite table (per-user `token_version`) or the existing user JSON config?
5. Should token-authenticated REST requests get the same rate limits as session requests, or stricter?
6. When overriding `user_email` in MCP tools — log a warning when client-supplied value differs from JWT email, or silently override? **Resolved in M1: log a warning.**
7. **(WS0) Resolved (2026-06-12):** Standalone HTTP framework = **Flask for the REST app, reuse existing Starlette for the MCP server** (least porting risk).
8. **(WS0) Resolved (2026-06-12):** Standalone is **multi-user** (per-JWT-email storage dirs, like the chat app); single-user is a config flag.
9. **(WS0)** Default LLM provider: which models/embedding model does `default_provider` target, and how are keys supplied (env `OPENAI_API_KEY`/`OPENROUTER_API_KEY`)? Embedding model must be pinned to avoid vector-dim drift.
10. **(WS0) Resolved (2026-06-12):** Stays in the **monorepo for now**; a separate repo split happens **later**, once the import boundary is clean.
11. **(WS0)** Does the chat app reference the vendored `pkb-manager.js` via symlink, a build-copy step, or a served path from the package? Pick one to keep a single UI source of truth.

---

## 12. Resolved Decisions (from original draft)

| Decision | Resolution |
|----------|-----------|
| 8 vs 15 MCP tools | Now 32 tools (22 baseline + 10 full) post v1.0 + notifications |
| 7-tab modal | Now 9 tabs (added Overview + Maintenance in v1.0) |
| JWT vs opaque API keys | JWT — reuses existing `mcp_server/auth.py` infrastructure |
| Iframe vs shared template for standalone UI | Shared template first; iframe only if CSS conflicts arise |
| Route conflict: `/pkb/claims/bulk` | Resolved — new bulk action uses `/pkb/claims/bulk_action` |
| REST surface count | Now 94 routes (added notifications, cleanup, fading, archived, health, consolidation, smart-consolidate, restore, reinforce, backfill_entities) — maintenance ops map to `admin` scope in T3.3 |
| Concurrent external access vs single SQLite connection | Resolved — `PKBDatabase` guards its shared connection with a `threading.RLock` (commit `0fdaa15`), so parallel MCP/REST/UI callers are thread-safe; removes a blocker for external exposure |
| keyParser pattern for API keys | Resolved — `keyParser` in `endpoints/utils.py` is a **function** taking `session` dict, returning API keys dict (falls back to env vars). All 94 REST endpoints now correctly call `keyParser(session)` (bug fix 2026-06-12: 14 endpoints were missing keys, causing embedding store / LLM failures) |
| Maintenance tab UX | Resolved — per-item checkboxes, selective apply, fading/archived always visible, LLM-assisted smart consolidation, status badges. Remaining polish tracked in `pkb_maintenance_ux_polish.plan.md` |
