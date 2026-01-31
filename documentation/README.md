# Documentation

This folder is the primary index for repo documentation. Use it to quickly find
implementation context, API docs, runbooks, and planning artifacts.

If you are new to the codebase, start with:
- `product/behavior/chat_app_capabilities.md` for a system overview
- `features/conversation_flow/` for the chat message pipeline (UI -> server -> UI)
- `api/internal/` for internal endpoints and payloads

## Planning
- `planning/plans/`: latest Cursor plan docs (older versions removed from `.cursor/plans`)
- `planning/roadmaps/`: roadmap / long-term planning notes

## Product
- `product/ops/`: deployment + ops runbooks
- `product/behavior/`: product behavior notes and context

## Features
- `features/extension/`: Chrome extension design + implementation docs
- `features/pwa/`: PWA/service-worker notes
- `features/conversation_artefacts/`: conversation-scoped artefacts (files + LLM edit flow)
- `features/conversation_flow/`: chat message send + streaming render pipeline
- `features/truth_management_system/`: TMS requirements + API + implementation
- `features/web_search/`: web search implementation notes
- `features/audio_slide_agent/`: audio/slide agent docs
- `features/stocks/`: stocks module notes

## APIs
- `api/internal/`: internal API docs and route summaries
- `api/internal/artefacts.md`: artefacts CRUD + LLM edit endpoints
- `api/external/`: external API docs

## Data
- `data/external_db/`: external DB docs

## Analysis
- `analysis/`: performance + timing analyses
- `analysis/route_parity/`: route parity checklist and report

## Dev
- `dev/`: developer documentation
- `dev/cursor/`: Cursor-internal context docs (optional reference)

## Scratch
- `scratch/`: non-product notes and experiments

---

Notes:
- This is a **copy-based** organization pass to avoid breaking existing links.
- Large generated outputs (e.g., `output/*`) and imported content in `storage/` were intentionally not duplicated here.
