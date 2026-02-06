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
- `features/conversation_flow/`: chat message send + streaming render pipeline (includes notes on conversation-level + Doc Index model overrides)
- `features/conversation_model_overrides/`: per-conversation model override system and UI
- `features/truth_management_system/`: TMS requirements + API + implementation
- `features/web_search/`: web search implementation notes
- `features/audio_slide_agent/`: audio/slide agent docs
- `features/stocks/`: stocks module notes
- `features/multi_model_response_tabs/`: tabbed UI for multi-model responses and TLDR summaries (start: `features/multi_model_response_tabs/TAB_BASED_RENDERING_IMPLEMENTATION.md`)
- `features/toc_streaming_fix/`: Table of Contents streaming fix — collapsed inline ToC, floating ToC panel, toggle button styling
- `features/scroll_preservation/`: scroll position preservation during DOM changes — CSS scroll anchoring, JavaScript anchor-based restore, card spacing
- `features/rendering_performance/`: rendering speed optimizations — MathJax priority for last card, deferred MathJax, immediate callbacks for showMore/buttons
- `features/math_streaming_reflow_fix/`: math equation reflow prevention during streaming — display math breakpoint detection (`\\[...\\]` and `$$`), math-aware render gating, min-height stabilization, over-indented list normalization; includes backend `ensure_display_math_newlines()` and frontend `isInsideDisplayMath()`, `normalizeOverIndentedLists()`

## APIs
- `api/internal/`: internal API docs and route summaries
- `api/internal/artefacts.md`: artefacts CRUD + LLM edit endpoints
- `api/internal/conversation_settings.md`: conversation settings (model overrides)
- `api/internal/model_catalog.md`: model catalog for dropdowns
- `api/external/`: external API docs

## Data
- `data/external_db/`: external DB docs

## Analysis
- `analysis/`: performance + timing analyses
- `analysis/route_parity/`: route parity checklist and report

## Dev
- `dev/`: developer documentation
- `dev/cursor/`: Cursor-internal context docs (optional reference)

## Changelogs
- `changelogs/AUTOSCROLL_REMOVAL_CHANGELOG.md`: removal of unwanted auto-scroll behaviors
- `changelogs/MATH_STREAMING_REFLOW_FIX.md`: math streaming reflow fix + over-indented list normalization (Feb 2026)

## Scratch
- `scratch/`: non-product notes and experiments

---

Notes:
- This is a **copy-based** organization pass to avoid breaking existing links.
- Large generated outputs (e.g., `output/*`) and imported content in `storage/` were intentionally not duplicated here.
