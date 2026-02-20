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
- `features/extension/`: Chrome extension docs — `extension_design_overview.md` (architecture, features, conversation flow), `extension_implementation.md` (file-by-file code reference), `extension_api.md` (endpoint reference), `README.md` (quick start), `multi_tab_scroll_capture.md` (4-mode capture with deferred OCR, tab restoration, 16 URL patterns). Backend unified with `server.py` (M1-M7 complete).
- `features/file_attachments/`: File attachment preview and persistence system — drag-and-drop images/PDFs in both extension and main UI, preview thumbnails above message input, persistent attachment rendering in messages, context menu (Preview/Download/Add to Conversation/Attach for current turn), FastDocIndex architecture (BM25 keyword search, 1-3s upload vs 15-45s), promotion to full ImmediateDocIndex, two document lists (message-attached vs uploaded), combined `#doc_N` numbering, LLM reads attached docs in reply, extension PDF text extraction via pdfplumber with system message merging into LLM prompt
- `features/pwa/`: PWA/service-worker notes
- `features/conversation_artefacts/`: conversation-scoped artefacts (files + LLM edit flow)
- `features/conversation_flow/`: chat message send + streaming render pipeline (includes notes on conversation-level + Doc Index model overrides, chat settings management and persistence, PKB `@` autocomplete UX, and suffix-based reference resolution for all PKB object types)
- `features/conversation_model_overrides/`: per-conversation model override system and UI
- `features/truth_management_system/`: Personal Knowledge Base (PKB/TMS) — requirements, API reference, implementation guide, deep dive. **Current: v0.7** — includes claims CRUD, contexts/groups, friendly IDs, claim numbers, QnA possible questions (self-sufficient), dynamic types/domains, FTS5 + embedding search, LLM extraction, conversation integration (with `use_pkb` toggle), `@` autocomplete (across claims, contexts, entities, tags, domains), referenced claim preservation, expandable entity/tag/context views, universal `@` references with type-suffixed friendly IDs (`_context`, `_entity`, `_tag`, `_domain`), suffix-based routing in `resolve_reference()`, recursive tag resolution, domain references
- `features/web_search/`: web search implementation notes
- `features/audio_slide_agent/`: audio/slide agent docs
- `features/cross_conversation_references/`: cross-conversation message references -- `@conversation_<fid>_message_<hash>` syntax for referencing messages from other conversations, conversation friendly IDs, message short hashes, sidebar context menu copy, message card ref badges, backend resolution via `_resolve_conversation_message_refs()`, DB schema (`conversation_friendly_id` column on `UserToConversationId`)
- `features/workspaces/`: hierarchical workspace system — jsTree-based sidebar, unlimited nesting, workspace color indicators, context menus (right-click + triple-dot), move workspace/conversation, cascade delete, `parent_workspace_id` schema, API endpoints, Bootstrap 4.6 modals, vakata styling fixes
- `features/stocks/`: stocks module notes
- `features/multi_model_response_tabs/`: tabbed UI for multi-model responses and TLDR summaries (start: `features/multi_model_response_tabs/TAB_BASED_RENDERING_IMPLEMENTATION.md`)
- `features/toc_streaming_fix/`: Table of Contents streaming fix — collapsed inline ToC, floating ToC panel, toggle button styling
- `features/scroll_preservation/`: scroll position preservation during DOM changes — CSS scroll anchoring, JavaScript anchor-based restore, card spacing
- `features/rendering_performance/`: rendering speed optimizations — MathJax priority for last card, deferred MathJax, immediate callbacks for showMore/buttons
- `features/math_streaming_reflow_fix/`: math equation reflow prevention during streaming — display math breakpoint detection (`\\[...\\]` and `$$`), math-aware render gating, min-height stabilization, over-indented list normalization; includes backend `ensure_display_math_newlines()` and frontend `isInsideDisplayMath()`, `normalizeOverIndentedLists()`
- `features/global_docs/`: Global Documents — index once, use everywhere. `#gdoc_N` / `#global_doc_N` / `"display name"` reference syntax, user-scoped global doc library, CRUD via UI modal with drag-and-drop upload and XHR progress, promote conversation docs to global, 7 REST endpoints (`/global_docs/*` including `/serve` for PDF viewer), DB table `GlobalDocuments`, storage at `storage/global_docs/{user_hash}/`, reply flow integration in Conversation.py with quoted display-name matching, full-height PDF viewing via `showPDF()` reuse, DocIndex fallback in download for stale source paths

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
