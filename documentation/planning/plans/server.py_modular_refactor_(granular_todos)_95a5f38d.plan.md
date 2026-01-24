---
name: server.py modular refactor (granular todos)
overview: Same blueprint + create_app refactor plan, but with a significantly more granular, trackable todo list covering scaffolding, state, DB extraction, per-blueprint extraction, server slimming, and verification.
todos:
  - id: m0-route-contract
    content: Create a route-parity checklist (path + methods + login_required + limiter annotations) based on `endpoints_brief_details.md` for use during verification.
    status: pending
  - id: m0-decide-prefixes
    content: "Confirm blueprint URL prefixes (default: no prefixes, preserve exact paths; `/pkb/*` stays in pkb blueprint via its route definitions)."
    status: pending
    dependencies:
      - m0-route-contract
  - id: m1-create-endpoints-pkg
    content: Create `endpoints/` package with `__init__.py` placeholder and module docstrings.
    status: pending
    dependencies:
      - m0-decide-prefixes
  - id: m1-create-database-pkg
    content: Create `database/` package with `__init__.py` placeholder and module docstrings.
    status: pending
    dependencies:
      - m0-decide-prefixes
  - id: m1-add-state-container
    content: "Implement `endpoints/state.py`: define `AppState`, `init_state()`, `get_state()`, and decide exact fields (dirs, caches, PKB state, etc.)."
    status: pending
    dependencies:
      - m1-create-endpoints-pkg
  - id: m1-add-blueprint-registry
    content: Implement `endpoints/__init__.py` with `register_blueprints(app)` that imports/registers all blueprint objects.
    status: pending
    dependencies:
      - m1-create-endpoints-pkg
  - id: m1-add-server-skeleton
    content: In `server.py`, add `create_app(argv=None)` + `main(argv=None)` skeletons while keeping existing behavior unchanged initially.
    status: completed
    dependencies:
      - m1-add-blueprint-registry
      - m1-add-state-container
  - id: m2-db-connection-module
    content: "Create `database/connection.py`: move `create_connection` and DB path logic; add docstrings."
    status: pending
    dependencies:
      - m1-create-database-pkg
  - id: m2-db-schema-create_tables
    content: Move `create_tables()` (and any helper DDL functions) into `database/connection.py`, parameterized by `users_dir`.
    status: pending
    dependencies:
      - m2-db-connection-module
  - id: m2-db-workspaces-module
    content: Create `database/workspaces.py` and move workspace DB helpers (load/create/update/delete/move/collapse workspace operations).
    status: pending
    dependencies:
      - m2-db-connection-module
  - id: m2-db-conversations-module
    content: Create `database/conversations.py` and move conversation DB helpers (add/check/list/get/delete/remove user etc.).
    status: completed
    dependencies:
      - m2-db-connection-module
  - id: m2-db-doubts-module
    content: Create `database/doubts.py` and move doubt DB helpers (add/get/delete/history/children/tree).
    status: completed
    dependencies:
      - m2-db-connection-module
  - id: m2-db-users-module
    content: Create `database/users.py` and move user details DB helpers (add/get/update user detail).
    status: completed
    dependencies:
      - m2-db-connection-module
  - id: m2-db-sections-module
    content: Create `database/sections.py` and move section hidden details DB helpers.
    status: completed
    dependencies:
      - m2-db-connection-module
  - id: m2-db-export-surface
    content: Update `database/__init__.py` to re-export public DB functions (stable API for endpoints).
    status: completed
    dependencies:
      - m2-db-workspaces-module
      - m2-db-conversations-module
      - m2-db-doubts-module
      - m2-db-users-module
      - m2-db-sections-module
      - m2-db-schema-create_tables
  - id: m3-endpoints-utils
    content: Create `endpoints/utils.py` and move shared helpers used by multiple endpoints (e.g., key parsing, cached file access, pinned-claims helpers).
    status: completed
    dependencies:
      - m1-create-endpoints-pkg
      - m1-add-state-container
  - id: m4-auth-blueprint-create
    content: Create `endpoints/auth.py` with `auth_bp = Blueprint('auth', __name__)` and module docstring.
    status: pending
    dependencies:
      - m3-endpoints-utils
  - id: m4-auth-move-decorator
    content: Move `login_required` and any auth helpers (credential checking, etc.) into `endpoints/auth.py`.
    status: pending
    dependencies:
      - m4-auth-blueprint-create
  - id: m4-auth-move-token-storage
    content: Move remember-token helpers (generate/verify/store/cleanup) into `endpoints/auth.py` (or `endpoints/auth_tokens.py` if it gets too large).
    status: pending
    dependencies:
      - m4-auth-blueprint-create
  - id: m4-auth-request-hook
    content: Convert `@app.before_request` remember-token logic to blueprint-safe `@auth_bp.before_app_request` (preserve behavior).
    status: pending
    dependencies:
      - m4-auth-blueprint-create
  - id: m4-auth-routes
    content: "Move auth routes into auth blueprint: `/login`, `/logout`, `/get_user_info` (preserve methods and response semantics)."
    status: pending
    dependencies:
      - m4-auth-move-decorator
      - m4-auth-request-hook
  - id: m5-static-blueprint-create
    content: Create `endpoints/static_routes.py` blueprint for infra/static/interface/proxy routes.
    status: pending
    dependencies:
      - m3-endpoints-utils
  - id: m5-static-routes-move
    content: "Move static + interface routes: favicon/loader/static, `/interface`, share view, `/proxy`, session/locks endpoints as appropriate."
    status: pending
    dependencies:
      - m5-static-blueprint-create
      - m4-auth-move-decorator
  - id: m6-workspaces-blueprint
    content: Create `endpoints/workspaces.py` blueprint and move workspace routes (create/list/update/collapse/delete/move conversation).
    status: pending
    dependencies:
      - m2-db-workspaces-module
      - m4-auth-move-decorator
  - id: m7-conversations-blueprint
    content: Create `endpoints/conversations.py` blueprint and move conversation/message routes (list/create/send/edit/move/delete/clone/history/details/state/memory-pad/flags).
    status: completed
    dependencies:
      - m2-db-conversations-module
      - m4-auth-move-decorator
      - m1-add-state-container
  - id: m7-cancellations
    content: Move cancellation routes (`/cancel_*`, `/cleanup_cancellations`) into `endpoints/conversations.py` (or a new `endpoints/cancellations.py` if needed) and store registries in `AppState`.
    status: completed
    dependencies:
      - m7-conversations-blueprint
      - m1-add-state-container
  - id: m8-documents-blueprint
    content: Create `endpoints/documents.py` blueprint and move document routes (upload/list/download/delete).
    status: completed
    dependencies:
      - m4-auth-move-decorator
      - m1-add-state-container
  - id: m9-doubts-blueprint
    content: Create `endpoints/doubts.py` blueprint and move doubt routes + temporary LLM action route.
    status: completed
    dependencies:
      - m2-db-doubts-module
      - m4-auth-move-decorator
  - id: m10-users-blueprint
    content: Create `endpoints/users.py` blueprint and move user detail/preference routes.
    status: completed
    dependencies:
      - m2-db-users-module
      - m4-auth-move-decorator
  - id: m11-audio-blueprint
    content: Create `endpoints/audio.py` blueprint and move `/tts`, `/is_tts_done`, `/transcribe`.
    status: completed
    dependencies:
      - m4-auth-move-decorator
      - m3-endpoints-utils
  - id: m12-pkb-blueprint
    content: Create `endpoints/pkb.py` blueprint; move PKB state/helpers and all `/pkb/*` routes; ensure PKB DB paths use `users_dir` consistently.
    status: completed
    dependencies:
      - m1-add-state-container
      - m4-auth-move-decorator
  - id: m13-prompts-blueprint
    content: Create `endpoints/prompts.py` blueprint and move prompt management routes.
    status: completed
    dependencies:
      - m4-auth-move-decorator
  - id: m14-sections-blueprint
    content: Create `endpoints/sections.py` (or merge into conversations) and move section hidden details routes.
    status: completed
    dependencies:
      - m2-db-sections-module
      - m4-auth-move-decorator
  - id: m15-code-runner-blueprint
    content: Create `endpoints/code_runner.py` and move `/run_code_once` route.
    status: completed
    dependencies:
      - m3-endpoints-utils
      - m4-auth-move-decorator
  - id: m16-register-all-blueprints
    content: Wire all blueprint modules into `endpoints/register_blueprints(app)` and ensure import order supports auth hooks/decorators.
    status: completed
    dependencies:
      - m4-auth-routes
      - m5-static-routes-move
      - m6-workspaces-blueprint
      - m7-conversations-blueprint
      - m8-documents-blueprint
      - m9-doubts-blueprint
      - m10-users-blueprint
      - m11-audio-blueprint
      - m12-pkb-blueprint
      - m13-prompts-blueprint
      - m14-sections-blueprint
      - m15-code-runner-blueprint
  - id: m17-thin-serverpy-orchestration
    content: "Refactor `server.py` to be thin: parse args, init extensions, init state, call `create_tables`, call `register_blueprints`, then `app.run` (preserve CLI semantics)."
    status: completed
    dependencies:
      - m16-register-all-blueprints
      - m2-db-schema-create_tables
      - m1-add-server-skeleton
  - id: m18-verify-cli-entrypoints
    content: Verify `python server.py` default and `python server.py --login_not_needed` both start cleanly (matches VSCode launch behavior).
    status: completed
    dependencies:
      - m17-thin-serverpy-orchestration
  - id: m18-verify-route-parity
    content: Verify every route in `endpoints_brief_details.md` exists with same methods + limiter/login_required decorators (spot-check plus automated listing if feasible).
    status: completed
    dependencies:
      - m17-thin-serverpy-orchestration
      - m0-route-contract
  - id: m18-smoke-test-core-paths
    content: "Smoke test key flows: login (or bypass), interface load, send_message path, one doubts route, one PKB route, one documents route."
    status: completed
    dependencies:
      - m18-verify-cli-entrypoints
      - m18-verify-route-parity
---

# Modularize `server.py` into `endpoints/` + `database/` (Blueprint + create_app)

## Requirements (what we are achieving)

- Keep **root** [`server.py`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/server.py) as the **runtime/debug entrypoint** (per [`.vscode/launch.json`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/.vscode/launch.json) which launches `program: "server.py"` and sometimes passes `--login_not_needed`).
- Split all Flask route handlers into an `endpoints/` folder, grouped by domain.
- Move all SQLite/persistence helpers out of `server.py` into `database/`.
- Preserve:
- **All URLs**, **HTTP methods**, and behavioral semantics.
- **Rate limits** and `login_required` behavior.
- CLI flags (`--folder`, `--login_not_needed`) and config resolution.
- Introduce **`create_app()` + Blueprints** so importing modules does not depend on `if __name__ == "__main__"` side-effects.
- Store shared state in a **dedicated module state container** (e.g., `endpoints/state.py`).

Primary refactor reference checklist: [`endpoints_brief_details.md`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/endpoints_brief_details.md).

Previous plan: [`.cursor/plans/server.py_modular_refactor_e2513202.plan.md`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/.cursor/plans/server.py_modular_refactor_e2513202.plan.md).

## Key design decisions

### 1) App factory + blueprint registration

- Create:
- `create_app(argv: list[str] | None = None) -> OurFlask`
- `main(argv: list[str] | None = None) -> None`
- `server.py` becomes the orchestrator:
- parse args
- resolve folders/paths
- initialize app + extensions (Session, CORS, Cache, Limiter)
- initialize shared state container
- register blueprints
- initialize DB schema
- run the server

### 2) Shared state container (`endpoints/state.py`)

Centralize shared globals that multiple endpoints currently touch (per brief):

- `users_dir`, `pdfs_dir`, `locks_dir`, `cache_dir`, `conversation_folder`
- `conversation_cache`, pinned-claims storage (`_conversation_pinned_claims`)
- cancellation registries/locks (if currently global)
- PKB state + DB path builder

Proposed API surface:

```python
from dataclasses import dataclass

@dataclass
class AppState:
    ...

def init_state(...) -> AppState:
    ...

def get_state() -> AppState:
    ...
```



## File structure (target)

- Root:
- [`server.py`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/server.py)
- New:
- `endpoints/` (blueprints + shared state/helpers)
- `database/` (SQLite/persistence layer)

## Data/control-flow (after refactor)

```mermaid
flowchart TD
    ServerPy[server.py] --> CreateApp[create_app]
    CreateApp --> InitExtensions[init_extensions]
    CreateApp --> InitState[init_state]
    CreateApp --> RegisterBPs[register_blueprints]
    CreateApp --> InitDB[database.create_tables]
    RegisterBPs --> AuthBP[endpoints/auth.py]
    RegisterBPs --> ConvBP[endpoints/conversations.py]
    RegisterBPs --> PKBBP[endpoints/pkb.py]
    AuthBP --> State[endpoints/state.py]
    ConvBP --> State
    PKBBP --> State
    ConvBP --> DB[database/*]
    AuthBP --> DB
```



## Risks / challenges + mitigations

- **Import-time side effects** in current `server.py`.
- Mitigation: move to `create_app()` + blueprints; avoid relying on `__main__`.
- **Circular imports**.
- Mitigation: enforce one-way dependencies (endpoints -> state/database; database never imports endpoints).
- **Shared mutable globals** (cache, PKB state, cancellation registries).
- Mitigation: `AppState` + `get_state()`.
- **Decorator dependencies** (`login_required`, `@limiter.limit`, request hooks).
- Mitigation: auth blueprint provides decorator + uses `before_app_request`.

## Milestones (implementation sequence)

1. Scaffolding: create folders, registration, state container, and minimal `create_app()` skeleton.
2. Extract DB functions into `database/` modules with explicit `users_dir` plumbing.
3. Extract shared endpoint utilities into `endpoints/utils.py`.
4. Extract endpoints into domain blueprints.
5. Slim `server.py` to orchestrator only.
6. Route parity + startup verification.

## Optional hardening milestone (post-refactor)