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
  - `product/ops/server_restart_guide.md`: **Server restart procedures** — all 3 screen sessions (science-reader, opencode_server, extension_server), JWT extraction from `/proc`, deferred restart via nohup+sleep, full stack restart sequence, troubleshooting
  - `product/ops/mcp_server_setup.md`: **MCP server setup** — all 8 MCP servers (7 remote on ports 8100-8106 + local pdf-reader), 37 tools, JWT auth, token generation, OpenCode/Claude Code client config, Jina timeout tuning, nginx reverse proxy, troubleshooting
  - `product/ops/llm_model_management.md`: **LLM model management** — model configuration, provider setup, model catalog
  - `product/ops/server_ops_and_runbook.md`: **Legacy server runbook** — original deployment notes (nginx, SSL, Docker/Gotenberg, vLLM). See `server_restart_guide.md` for current restart procedures
- `product/behavior/`: product behavior notes and context
  - `product/behavior/chat_app_capabilities.md`: full system overview — capability map, API surface, differentiators vs ChatGPT, Android parity checklist
  - `product/behavior/CLARIFICATIONS_AND_AUTO_DOUBT_CONTEXT.md`: `/clarify` slash command system — detection, `ClarificationsManager`, multi-round `[Clarifications]` format, `forceClarify` flag, `/clarify_intent` endpoint, PKB + conversation summary context, `clarify_intent_model` override. Also contains design notes for planned Auto Takeaways (not yet implemented).

## Features
- `features/extension/`: Chrome extension docs — `extension_design_overview.md` (architecture, features, conversation flow), `extension_implementation.md` (file-by-file code reference), `extension_api.md` (endpoint reference), `README.md` (quick start), `multi_tab_scroll_capture.md` (4-mode capture with deferred OCR, tab restoration, 16 URL patterns; **cross-origin iframe subframe probe** for SharePoint/Word Online via `findCaptureContextInFrames` + `webNavigation.getAllFrames`). Shared extension logic lives in `extension-shared/` (symlinked into both `extension/` and `extension-iframe/`). Backend unified with `server.py` (M1-M7 complete).
- **[File Browser](features/file_browser/README.md)** — Full-screen modal file browser & code editor (Settings → Actions → File Browser). VS Code-like lazy-loaded tree sidebar, CodeMirror 5 with syntax highlighting (Python/JS/TS/CSS/HTML/XML/Markdown/JSON), **Raw / Preview / WYSIWYG** view-mode selector for `.md` files (EasyMDE inline, CodeMirror as source of truth), **PDF viewer** (inline PDF.js with scoped progress bar) for `.pdf` files, fuzzy autocomplete address bar (substring + sequential-char matching, filename-priority scoring), right-click context menu CRUD (**New File**, **New Folder**, **Rename**, **Move to…**, **Delete**) + sidebar New File/Folder buttons, in-modal confirm/name/move dialogs, `Ctrl+S` save, `Escape` close with dirty guard, `Cmd+K` **AI Edit** (LLM diff with Accept/Reject/Edit Instruction, conversation context injection), Reload from Disk, Word Wrap toggle, Download, drag-and-drop Upload (XHR progress), Monokai/Light theme picker, binary detection, 2 MB size guard with Load Anyway override. **Drag-and-drop move** (tree item → folder or tree background to move to **root**; dashed-outline drop feedback; `.fb-drag-over-root` on background hover) and **context-menu Move modal** (lazy folder-only tree with pinned **/ (root)** item, z-index 100004). **Decoupled move backend**: `_config.onMove(src, dest, done)` callback overridable at `init({onMove})` or `.configure({onMove})`. 11 REST endpoints under `/file-browser/*` (tree, read, write, mkdir, rename, move, delete, download, upload, serve, ai-edit), all path-sandboxed to server root via `os.path.realpath()`. Modal uses raw DOM manipulation (no Bootstrap JS) to stack safely over the settings modal; view switching covers all 5 states (editor/preview/wysiwyg/pdf/empty) via `element.style.display`. Key files: `endpoints/file_browser.py`, `interface/file-browser-manager.js`. Note: bump both `CACHE_VERSION` in `service-worker.js` and `?v=N` in the script tag together on JS changes.
- `features/file_attachments/`: File attachment preview and persistence system — drag-and-drop images/PDFs in both extension and main UI, preview thumbnails above message input, persistent attachment rendering in messages, context menu (Preview/Download/Add to Conversation/Attach for current turn), FastDocIndex architecture (BM25 keyword search, 1-3s upload vs 15-45s), promotion to full ImmediateDocIndex, two document lists (message-attached vs uploaded), combined `#doc_N` numbering, LLM reads attached docs in reply, extension PDF text extraction via pdfplumber with system message merging into LLM prompt
- `features/pwa/`: PWA/service-worker notes
- `features/conversation_artefacts/`: conversation-scoped artefacts (files + LLM edit flow)
- `features/conversation_flow/`: chat message send + streaming render pipeline (includes notes on conversation-level + Doc Index model overrides, chat settings management and persistence, PKB `@` autocomplete UX, suffix-based reference resolution for all PKB object types, and the `/clarify` slash command intercept)
- `features/conversation_model_overrides/`: per-conversation model override system and UI — `summary_model`, `tldr_model`, `artefact_propose_edits_model`, `doubt_clearing_model`, `context_action_model`, `doc_*_model`, and `clarify_intent_model` (for `/clarify` slash command)
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
- `features/global_docs/`: Global Documents — index once, use everywhere. `#gdoc_N` / `#global_doc_N` / `"display name"` / `#folder:Name` / `#tag:name` reference syntax (with chat input autocomplete). User-scoped global doc library with hierarchical folder organization (`GlobalDocFolders` DB table, pure metadata) and free-form tag system (`GlobalDocTags` DB table, many-to-many). Dual-view modal: **List view** with tag chips + real-time filter bar, **Folder view** backed by pluggable `FileBrowserManager.configure({onMove: fn})` with **Manage Folders** button for drag-and-drop organization. Promote conversation docs to global (copy-verify-delete). 10 REST endpoints (`/global_docs/*`) + 7 folder endpoints (`/doc_folders/*`). DB tables: `GlobalDocuments` (with `folder_id` column), `GlobalDocFolders`, `GlobalDocTags`. Storage unchanged at `storage/global_docs/{user_hash}/`. Reply flow in `Conversation.py` integrates `#folder:`/`#tag:` detection, quoted display-name matching, `#gdoc_all` support. Key files: `database/doc_folders.py`, `database/doc_tags.py`, `endpoints/doc_folders.py`, `interface/global-docs-manager.js`, `interface/common-chat.js` (`#folder:`/`#tag:` autocomplete).
- `features/documents/doc_flow_reference.md`: **Document System Flow Reference** — comprehensive end-to-end reference for all three document types (message attachments, conversation/local docs, global docs). Covers UI entry points, API endpoints, backend Python methods (with line numbers), DocIndex class hierarchy (FastDocIndex vs ImmediateDocIndex), storage layouts, numbering schemes (`#doc_N`, `#gdoc_N`), search/query resolution flow, and quick-reference function call chains. Unified doc modal: `#conversation-docs-modal` / `LocalDocsManager` / `DocsManagerUtils` (shared with GlobalDocsManager).
- `features/mcp_web_search_server/`: MCP Web Search Server — exposes 3 search agents (Perplexity, Jina, Interleaved deep search) and 2 page-reader tools (`jina_read_page` via Jina Reader API, `read_link` via `download_link_data` for web pages/PDFs/images/YouTube) as MCP tools over streamable-HTTP transport for external coding assistants (OpenCode, Claude Code). JWT bearer-token auth via Starlette middleware, per-token rate limiting, daemon thread alongside Flask on port 8100, `python -m mcp_server.auth` CLI for token generation, nginx reverse proxy config. Key files: `mcp_server/__init__.py`, `mcp_server/auth.py`, `mcp_server/mcp_app.py`. Plan: `planning/plans/mcp_web_search_server.plan.md`
- `features/opencode_integration/`: OpenCode Integration — routes chat messages through `opencode serve` for agentic capabilities (tool use, MCP, multi-step planning), with multi-provider support (OpenRouter + AWS Bedrock). SSE bridge translates OpenCode events to Flask streaming format with delta accumulation, reconnection, and cancellation. Per-conversation OpenCode sessions via `SessionManager`, configurable injection levels (minimal/medium/full), `noReply` context injection, math formatting parity. Provider/model selection UI in settings modal. Model routing: `_resolve_opencode_model()` with `BEDROCK_MODEL_MAP` for Bedrock ID translation. Only Claude 4.5 and 4.6 models supported. Key files: `opencode_client/` (client, session_manager, sse_bridge, config), `Conversation.py` (routing + streaming), `opencode.json`, `interface/interface.html` (settings modal), `interface/chat.js` (settings persistence), `endpoints/conversations.py` (validation). Plan: `planning/plans/opencode_integration.plan.md`

 **Web Terminal** — browser-based terminal (Settings → Actions → Terminal, or standalone `/terminal` page). Spawns user's default shell (`$SHELL` or `/bin/bash`) in a PTY, bridges I/O to browser via WebSocket + xterm.js (Catppuccin Mocha theme). Per-user session registry with reattach support (second tab reconnects to same PTY), idle timeout (30 min default), max-sessions cap, process-group cleanup. Modal uses raw DOM manipulation (no Bootstrap JS) to stack safely over other modals. **nginx note:** If deployed behind nginx, add a `/ws/` location block with `proxy_http_version 1.1`, `Upgrade`, and `Connection "upgrade"` headers — without these, WebSocket connections to `/ws/terminal` will silently fail (see `server_ops_and_runbook.md` for the full config). Key files: `endpoints/terminal.py` (PTY + WebSocket handler), `interface/opencode-terminal.js` (xterm.js module), `interface/terminal.html` (standalone page). Config via env vars: `TERMINAL_SHELL`, `TERMINAL_IDLE_TIMEOUT`, `TERMINAL_MAX_SESSIONS`, `PROJECT_DIR`.
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
- `changelogs/IFRAME_EXTENSION_OCR_FIX.md`: cross-origin iframe subframe probe for SharePoint/Word Online full-page OCR; OCR model fix (`gemini-2.5-flash-lite` → `gemini-2.5-flash`); tab-picker auto-checkbox removal; modal backdrop fix; content-viewer-modal height fix; DOM/OCR/Full-OCR split button (Feb 2026)

## Scratch
- `scratch/`: non-product notes and experiments

---

Notes:
- This is a **copy-based** organization pass to avoid breaking existing links.
- Large generated outputs (e.g., `output/*`) and imported content in `storage/` were intentionally not duplicated here.
