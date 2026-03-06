## Science Reader Desktop Companion — Product Requirements Document

**Status**: Draft v6
**Created**: 2026-03-01
**Last updated**: 2026-03-05
**Platform**: macOS (primary), Windows (future)
**Codename**: Desktop Companion

Based on:
- `documentation/product/behavior/chat_app_capabilities.md` (existing system capabilities)
- `documentation/product/ops/mcp_server_setup.md` (MCP server architecture)
- `documentation/features/extension/extension_design_overview.md` (Chrome extension as prior art)
- `documentation/planning/plans/workflow_engine_framework.plan.md` (workflow engine spec — authoritative source for sections 4.3 Tab 2, 4.13, 5.8, and Phase 10)
- `documentation/features/tool_calling/README.md` (LLM tool-calling framework — 48 tools, agentic mid-response loop, interactive modals)
- `documentation/features/image_generation/README.md` (image generation — `/image` command, standalone modal, editing, prompt refinement)
- `documentation/features/extension/multi_tab_scroll_capture.md` (multi-tab scroll capture with OCR comment extraction)
- Web research on Electron, nut.js, macOS Finder extensions, and accessibility APIs
- **Enconvo AI Companion** feature analysis (PopBar, SmartBar, Companion Orb, App Sidebar, Context Awareness, Workflows, Dictation, Knowledge Base, Skills)

Primary goals:
- Define the product vision, user experience, and feature set for a native desktop companion app
- Specify behavior for every interaction surface: PopBar, Results Dropdown, Sidebar, Dictation Pop, right-click ingestion, screen reading
- Serve as the single source of truth for implementation

---

## Table of Contents

1. [Vision & Problem Statement](#1-vision--problem-statement)
2. [User Persona](#2-user-persona)
3. [Four-Surface Architecture](#3-four-surface-architecture)
4. [Feature Specifications](#4-feature-specifications)
   - 4.1 PopBar (Context-Aware Quick Actions)
   - 4.2 Results Dropdown
   - 4.3 Sidebar (Full Chat + Workflows Panel)
   - 4.4 Finder / File System Integration
   - 4.5 Text Selection & Services Menu
   - 4.6 Screen Capture & OCR
   - 4.7 Tray Icon & Global Hotkeys
   - 4.8 File Drop Zone
   - 4.9 Focus Management
   - 4.10 Voice Dictation
   - 4.11 App Context Awareness
   - 4.12 Folder Sync
   - 4.13 Workflow Engine
   - 4.14 In-place Text Replacement
5. [UX Flows](#5-ux-flows)
6. [Technical Architecture](#6-technical-architecture)
7. [Platform Considerations](#7-platform-considerations)
8. [Backend API Surface](#8-backend-api-surface)
9. [Implementation Phases](#9-implementation-phases)
10. [Risks & Mitigations](#10-risks--mitigations)
11. [Out of Scope](#11-out-of-scope)
12. [Appendix A: Background Research & Competitive Analysis](#appendix-a-background-research--competitive-analysis)
13. [Appendix B: Technology Selection Rationale](#appendix-b-technology-selection-rationale)
14. [Appendix C: Design Decisions Log](#appendix-c-design-decisions-log)

---

## 1) Vision & Problem Statement

### The problem

The Science Reader web app is a powerful research and productivity system — chat, documents, PKB memory, agents, code execution, web search — but it lives in a browser tab. To use it, you must:
- Switch away from the app you're working in
- Navigate to the browser tab
- Lose the context of what you were looking at
- Manually copy-paste text, upload files, or re-describe what's on screen

This friction means the AI assistant is always one context-switch away. It should be zero.

### The vision

A lightweight desktop companion that **hovers above whatever app you're using**, so you can:
- Ask the AI about what's currently on your screen without leaving the app
- Right-click any file in Finder and instantly add it to your document library
- Select text anywhere and save it as PKB memory with one click
- Drop files onto the companion panel to index them
- Chat with the full Science Reader system from a floating sidebar
- Dictate text with your voice, transcribe it, and reformat it
- Run multi-step workflows (research, document generation) with visual progress
- Auto-sync watched folders to keep your document library current

The underlying app retains focus. The companion is an overlay — always present when summoned, invisible when not. Think of it as a hybrid between Spotlight (quick command entry), Grammarly (non-intrusive overlay), and the Chrome extension sidepanel (full chat).

### Key principle

**The Sidebar has two tabs** — **Tab 1** loads the full `interface.html` (web UI) in an Electron `BrowserView` for research, chat, and knowledge management. **Tab 2** loads `opencode web` for agentic coding — file editing, bash, grep, LSP, and full MCP tool access to your server's capabilities. Both tabs connect to the same remote backend (`assist-chat.site`); Tab 2 additionally operates on a user-selected local working directory.

**Tab 1 (Chat) preserves all existing features** — artefacts, workspace management, settings, model overrides, TTS, sharing, multi-model responses, cross-conversation references, next-question suggestions, file browser, terminal. The Sidebar adds **no custom chat UI** — it relies entirely on the web UI's responsive layout at various widths.

**Tab 2 (OpenCode) is a full coding agent** — it connects to your 7+ remote MCP servers (PKB, docs, search, artefacts, prompts, code runner, conversations) plus a local filesystem MCP (sandboxed to the working directory). OpenCode handles its own sessions, streaming, tool calling, undo/redo, and diff view.

**The desktop-native additions are**: PopBar (lightweight quick actions with configurable tool whitelist), Results Dropdown, Dictation Pop, Finder/Services right-click integration, folder sync, screen capture, app context awareness, and in-place text replacement. These are the surfaces that don't exist in the web UI and are built specifically for the desktop companion.

**PopBar is a lightweight subset** — ephemeral per-query (no conversation state), configurable tool whitelist (capped at 1-2 iterations), and no full agentic loop. For complex interactions, the user escalates to the Sidebar.

### Competitive reference: Enconvo

Enconvo is a native macOS AI Companion with five UI surfaces (SmartBar, PopBar, Companion Orb, App Sidebar, Agent Mode). Key features studied:
- **SmartBar**: Spotlight-like command bar with `@plugin` and `#context` modifiers
- **PopBar**: Text selection toolbar with writing tools (improve, fix spelling, translate, etc.) and in-place replacement
- **Companion Orb**: Persistent sidebar with quick actions (Screenshot OCR, Voice Chat, Summarize URL)
- **App Sidebar**: Per-app AI agent context (browser URL, code file, Finder selection)
- **Context Awareness**: Auto-detects active app, selected text, browser content, Finder files
- **Workflows**: Chain plugins into multi-step automations
- **Dictation**: System-wide voice input with multiple providers
- **Knowledge Base**: Document indexing with folder sync, collections, semantic search

Our approach differs: we connect to the existing Science Reader backend (Flask + 7 MCP servers) rather than building a standalone AI system. We use the existing PKB, Global Docs, chat, and prompt management. We add desktop-specific surfaces on top.

---

## 2) User Persona

**Single user, personal tool.** This is built for the developer/owner of the Science Reader system, running on their own machine. There is no distribution, no App Store, no multi-user auth flow.

Implications:
- No code signing or notarization needed (ad-hoc sign with `codesign --sign -`, bypass Gatekeeper with `xattr -cr`)
- No auto-update infrastructure in v1 (manual rebuild)
- Accessibility and screen recording permissions granted manually once
- The app connects to the existing Science Reader server (either `localhost:5000` for local dev, or `assist-chat.site` for production)

---

## 3) Four-Surface Architecture

The companion has **four distinct UI surfaces**, each with its own purpose, behavior, and hotkey. Inspired by Enconvo (PopBar + SmartBar + Companion Orb), Raycast (command bar + results), and Chrome extension sidepanels.

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Surface 1: PopBar                                          │
│  ─────────────────                                          │
│  Small floating bar near the cursor/selection.              │
│  Belongs to the context of the current app.                 │
│  Hotkey: Cmd+Shift+Space                                    │
│  Core: Quick Ask, Save to Memory, Explain, Summarize,       │
│        Screenshot, Search Memory, Context, Generate Image   │
│  Configurable: 2-3 slots (workflows, prompts, custom)       │
│                                                             │
│       ┌────────────────────────────────────┐                │
│       │ [Ask] [Mem] [Exp] [Sum] [📸] [🔍] │ ← PopBar      │
│       │ [What does this function do?     ] │                │
│       └────────────────────────────────────┘                │
│       ┌────────────────────────────────────┐                │
│       │ This function implements a binary  │                │
│       │ search algorithm that...           │ ← Dropdown     │
│       │          [Replace] [Copy] [Expand] │   (Surface 2)  │
│       └────────────────────────────────────┘                │
│                                                             │
│  Surface 2: Results Dropdown                                │
│  ───────────────────────────                                │
│  Appears below the PopBar. Shows AI responses, search       │
│  results, or action confirmations. Like Raycast results.    │
│  No separate hotkey — appears automatically when PopBar     │
│  produces output. Contains "Expand" link to escalate to     │
│  the Sidebar.                                               │
│                                                             │
│  Surface 3: Sidebar                                    ┌────┐│
│  ────────────────────                                  │Chat││
│  Dual-tab panel. Slides from edge.                     │────││
│  Tab 1: Full web UI (chat, PKB, docs, workspaces).     │Open││
│  Tab 2: OpenCode Web (coding agent, local files).      │Code││
│  Tab 3: Workflows panel (status, launch, debug).       │────││
│  App-agnostic: persists across Cmd+Tab.                │Work││
│  Hotkey: Cmd+Shift+J                                   │flow││
│  Draggable. Snaps to right/left/bottom edge.           │    ││
│                                                        └────┘│
│                                                             │
│  Surface 4: Dictation Pop                                   │
│  ────────────────────────                                   │
│  Small widget for voice dictation. Bottom-left default.     │
│  Hotkey: Cmd+J (toggle), hold Fn (push-to-talk)            │
│  Shows: waveform/indicator, transcribed text, reformat      │
│  dropdown, history. Draggable, remembers position.          │
│                                                             │
│  ┌──────────────────────────────────┐                       │
│  │ 🎙 Recording... [■ Stop]         │ ← Dictation Pop      │
│  │ "The transformer architecture..." │                       │
│  │ [Raw ▾] [History] [Copy] [Paste] │                       │
│  └──────────────────────────────────┘                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### How the surfaces relate

| From | To | Trigger |
|------|----|---------|
| Hidden | PopBar | `Cmd+Shift+Space` (PopBar hotkey) |
| Hidden | Sidebar | `Cmd+Shift+J` (Sidebar hotkey) |
| Hidden | Dictation Pop | `Cmd+J` (Dictation hotkey) or hold `Fn` |
| PopBar | Results Dropdown | Automatically, when PopBar produces output |
| PopBar / Dropdown | Sidebar | Click "Expand" → choose "New Conversation" or "Add to [active]" |
| PopBar / Dropdown | Sidebar | Finder/Services actions that need web UI modals (Review & Edit, Extract Multiple, Add to Global Docs) |
| Sidebar | Hidden | `Cmd+Shift+J` (toggle) |
| PopBar | Hidden | `Escape` |
| Dictation Pop | Hidden | `Escape` or `Cmd+J` (toggle) |
| Any surface | Deactivated (visible but unfocused) | `Escape` once |
| Deactivated | Hidden | `Escape` again |

> **Note**: PopBar queries are ephemeral — they do not accumulate conversation history. Each query is standalone. When escalating to Sidebar via "Expand", the user chooses whether to create a new conversation or inject into the active one.

### Key behavioral differences

| Property | PopBar | Sidebar | Dictation Pop |
|----------|--------|---------|---------------|
| **Position** | Near cursor / text selection | Snapped to screen edge or floating | Bottom-left (default), draggable, remembers position |
| **Scope** | Context of the current app | App-agnostic, persists across `Cmd+Tab` | App-agnostic, persists across `Cmd+Tab` |
| **Hotkey** | `Cmd+Shift+Space` | `Cmd+Shift+J` | `Cmd+J` (toggle) / hold `Fn` (push-to-talk) |
| **Focus behavior** | Non-activating by default; activates on text input | Same: non-activating hover, activates on input click | Non-activating; activates only when user clicks text area |
| **Content** | 8 action buttons + text input + configurable slots + tool whitelist | Tab 1: Full web UI (all features) in BrowserView. Tab 2: OpenCode Web (coding agent + MCP tools). Tab 3: Workflow panel. | Waveform, transcription, reformat dropdown, history |
| **Conversation model** | Ephemeral per-query (no persistent conversation) | Tab 1: Full conversations via web UI's workspace tree. Tab 2: OpenCode sessions (independent). | N/A |
| **Persistence** | Dismissed after use or on `Escape` | Stays visible until explicitly toggled off | Dismissed after use or on `Escape` |
| **Text selection trigger** | Optional auto-popup on text selection (off by default, toggle in Settings) | No auto-trigger | No auto-trigger |
| **Escalation** | Can escalate to Sidebar (user chooses: new conversation or add to active) | Cannot downgrade to PopBar | Transcribed text can be sent to PopBar or Sidebar |

---

## 4) Feature Specifications

### 4.1) PopBar (Context-Aware Quick Actions)

**What it does**
- A compact floating bar (~500x50px) that appears **near the cursor or text selection** when summoned.
- Designed for fast, in-context actions: ask a question, save text to memory, explain a selection, capture the screen.
- Belongs to the context of the current app — if you switch apps, the PopBar dismisses.
- Inspired by Enconvo's PopBar and SmartBar, Raycast's command bar.

**Appearance & positioning**
- Appears near the mouse cursor or the selected text (Enconvo-style), offset so it doesn't occlude the selection.
- If near a screen edge, repositions to stay fully visible.
- Has a small drag handle for manual repositioning within the current invocation.

**Text selection trigger (optional)**
- **Off by default.** When enabled in Settings, selecting text in any app auto-shows the PopBar nearby with relevant actions.
- Per-app toggle if feasible (e.g., enable for Safari and Notes, disable for VS Code). If per-app control is too complex for v1, a simple global on/off toggle.
- Always accessible via hotkey regardless of this setting.

**Actions — Core (always visible)**

| # | Action | Icon | Behavior |
|---|--------|------|----------|
| 1 | **Quick Ask** | `💬` | Type a question, press Enter. AI response appears in the Results Dropdown below. Optional model selector (dropdown, sane default set in Settings). **Tool calling**: Quick Ask uses a configurable tool whitelist (see "PopBar Tool Calling" below) with max 1-2 tool iterations. For the full 48-tool agentic loop, escalate to Sidebar Chat. |
| 2 | **Save to Memory** | `🧠` | Opens the Quick Review form (see 4.5) with the selected text pre-filled. If no text selected, uses typed text. Three sub-actions: Quick Save (equivalent to `/create-simple-memory`), Review & Edit (equivalent to `/create-memory`), Extract Multiple. |
| 3 | **Explain** | `📖` | Sends selected text to AI with "Explain this:" prefix. Response in Results Dropdown. |
| 4 | **Summarize** | `📝` | Sends selected text to AI with "Summarize this:" prefix. Response in Results Dropdown. |
| 5 | **Screenshot** | `📸` | Dropdown with capture modes: **App Window**, **Full Screen**, **Select Area** (crosshair), **Scrolling Screenshot**. Each mode has a plain capture variant and an **+OCR** toggle. +OCR modes include an additional **"Extract Comments"** checkbox for documents with annotations/comments (uses dual-LLM parallel extraction). Captured image or extracted text shown in Results Dropdown. |
| 6 | **Search Memory** | `🗂` | Type a query, searches PKB via `POST /pkb/search`. Results appear in dropdown with claim statements, types, domains. Click a result to view full claim or use in chat. |
| 7 | **Context** | `🔗` | Dropdown to manually attach app context at different levels: App Name + Window Title, + Selected Text, + Screenshot, + Full Scrolling OCR. Context is included as system context in the next query. |
| 8 | **Generate Image** | `🎨` | Type an image prompt, press Enter. Uses `POST /api/generate-image` with conversation context and prompt refinement. Generated image shown in Results Dropdown with download button. If text/image was selected, it can be used as an edit input. |

**Actions — Configurable slots (2-3)**

| Slot | Default | Configurable to |
|------|---------|-----------------|
| Slot A | (empty) | Any pinned prompt from the prompt store |
| Slot B | (empty) | Any workflow |
| Slot C | (empty) | Any pinned prompt or workflow |

User configures which prompts/workflows appear in these slots via Settings. A **Prompt button** opens a mini-list of pinned/favorited prompts when clicked — selecting one runs it on the selected text or current input.

**Model selection in Quick Ask**
- A small model dropdown next to the input field (collapsed by default, shows current model name).
- Click to expand and choose from available models.
- Default model configured in Settings. Persists across sessions.

**Keyboard shortcuts within PopBar**

| Shortcut | Action |
|----------|--------|
| `Enter` | Execute the selected action with current input |
| `Cmd+Enter` | Execute and escalate to Sidebar (response appears in Sidebar) |
| `Escape` | Dismiss PopBar, return focus to underlying app |
| `Tab` | Move focus to next action button |
| `1-8` | Quick-select core action by number (when input is empty) |
| `Up/Down` | Scroll through recent inputs (history) |

**PopBar conversation model: ephemeral per-query**

PopBar queries are **ephemeral** — they do not use a persistent conversation object. Each query is a standalone request (similar to `temp_llm_action`). There is no conversation history accumulating in the PopBar across queries.

- When the user clicks **"Expand"** in the Results Dropdown, they are given a choice:
  - **"New Conversation"** — creates a new conversation in the default workspace, injects the PopBar query + response as the first turn, opens it in the Sidebar.
  - **"Add to [current conversation name]"** — injects the PopBar exchange into the currently active Sidebar conversation.
- Input history (Up/Down arrow) is local to the PopBar process — it's a list of recent user inputs, not conversation turns.

**PopBar tool calling: configurable whitelist**

PopBar supports a **configurable subset** of the 48-tool tool-calling framework, capped at **1-2 tool iterations** max (vs the Sidebar's 5). This allows the LLM to call specific tools during Quick Ask without the full agentic loop overhead.

- **Configurable in Settings > PopBar > Allowed Tools**: a multi-select list of tools the PopBar's LLM can invoke. Default tools enabled: PKB search (`pkb_search`), PKB add claim (`pkb_add_claim`). All other tools disabled by default.
- **Max iterations**: 2 (configurable in Settings, range 1-3). On the final iteration, `tool_choice="none"` forces text output, same as the Sidebar.
- **No interactive tools**: `ask_clarification` is disabled in PopBar (the MCQ modal UX doesn't fit the compact dropdown). If the LLM needs clarification, the user should escalate to Sidebar.
- **Tool results display**: Tool execution shows a brief inline status indicator in the Results Dropdown (similar to Sidebar's status pills but simpler — just tool name + spinner/checkmark).
- **Settings persistence**: PopBar tool whitelist persists across sessions via electron-store.

This design gives the PopBar access to memory operations (search, add, edit claims) and potentially web search, while keeping response times fast (2-5 seconds typical).

---

### 4.2) Results Dropdown

**What it does**
- A panel that appears directly below the PopBar, showing output from PopBar actions.
- Styled like Raycast's results panel: same width as PopBar, scrollable, max height ~400px.
- Auto-appears when the PopBar produces output (AI response, search results, OCR text, action confirmation).
- Auto-dismisses when the PopBar is dismissed.

**Content types**

| PopBar action | What appears in dropdown |
|---------------|--------------------------|
| Quick Ask | Streaming AI response (markdown rendered). **Replace** and **Copy** buttons. "Expand to Sidebar" link at bottom. |
| Explain | Streaming AI response. **Replace** and **Copy** buttons. |
| Summarize | Streaming AI response. **Replace** and **Copy** buttons. |
| Screenshot (plain) | Captured image thumbnail + text input for question. Enter sends image+question to AI. |
| Screenshot (+OCR) | Extracted text with action buttons: **Replace**, **Copy**, "Ask AI", "Save to PKB". If "Extract Comments" was enabled, shows clean text section + separate comments section with `[anchor → body]` pairs. **"Ask AI"** sets the OCR text as a context chip in the PopBar input + attaches the screenshot image, then focuses the input for the user to type a question. |
| Scrolling Screenshot (plain) | Stitched image thumbnail + text input. |
| Scrolling Screenshot (+OCR) | Full extracted text with action buttons. If "Extract Comments" enabled, includes per-page comment annotations. |
| Search Memory | List of matching PKB claims with type badges and domain labels. Click to view full claim. |
| Save to Memory | Quick Review form (inline in dropdown): statement, claim_type, domain, tags, three action buttons. |
| Prompt (from configurable slot) | Streaming AI response from the selected prompt applied to the input/selection. **Replace** and **Copy** buttons. |
| Workflow (from configurable slot) | Workflow status + "Open in Sidebar Workflows tab" link. |
| Generate Image | Generated image displayed as a card with download button. If an input image was provided, shows before/after comparison. "Open in Sidebar" link to continue editing in full chat. |

**Replace and Copy buttons**
- Every AI response or text-transform result shows **both** a "Replace" button and a "Copy" button.
- **Replace**: simulates `Cmd+V` in the target app to replace the selected text with the AI result. Only available when text was selected before invoking PopBar.
- **Copy**: copies the result to clipboard.
- See section 4.14 for implementation details.

**Escalation to Sidebar**
- Every AI response in the dropdown includes an **"Expand"** link/button.
- Clicking it shows a small choice dropdown:
  - **"New Conversation"** — creates a new conversation in the default workspace, injects the PopBar query + response as the first turn, and opens it in the Sidebar.
  - **"Add to [current conversation name]"** — injects the PopBar exchange (query + response + any context) as a new turn into the currently active Sidebar conversation.
- The PopBar and dropdown dismiss. The Sidebar takes over.

**Result persistence**
- After adding a file or saving a claim, the dropdown **stays open** showing the result (doc ID, claim details, link to web UI).
- User manually dismisses with `Escape` or clicks away.

---

### 4.3) Sidebar (Chat + OpenCode + Workflows)

**What it does**
- A floating, draggable panel with **three tabs**: **Chat** (full web UI), **OpenCode** (agentic coding agent), and **Workflows** (execution monitoring).
- **App-agnostic**: persists across `Cmd+Tab` app switching. Switching from VS Code to Safari does not dismiss the Sidebar.
- Only the Sidebar hotkey (`Cmd+Shift+J`) toggles it away.
- **Tab system**: three tabs at the top — **Chat**, **OpenCode**, and **Workflows**.
- The Sidebar is **resizable** — the user can widen it beyond the default 400px for full-width viewing.

**Tab 1: Chat (= the full web UI)**

The Chat tab loads the existing `interface.html` **as-is** — no custom chat UI, no stripped-down version. The Electron `BrowserView` renders the complete web application, and the web UI's responsive layout handles different widths automatically. At narrow widths (~400px), the workspace sidebar auto-hides (mobile responsive mode) and the chat area fills the space. At wider widths, the full layout with workspace sidebar appears.

**All existing web UI features work automatically** in the Sidebar Chat, including but not limited to:
- Streaming chat with markdown, math (MathJax), code (highlight.js), diagrams (Mermaid)
- Workspace management (hamburger sidebar at narrow width, full tree at wider widths)
- Conversation CRUD, cloning, stateless mode, flags
- New Temporary Chat button
- Document references (`#doc_1`, `#gdoc_1`, `#gdoc_all`, `#folder:Name`, `#tag:name`, `#artefact_N`, `@memory`, `@friendly_id`, `@conversation_<fid>_message_<hash>`)
- LLM Tool Calling (48 tools, 8 categories, interactive modals, mid-response agentic loop)
- Image Generation (`/image <prompt>`, standalone modal, image editing, vision context)
- PKB Slash Commands (`/create-memory`, `/create-simple-memory`, `/create-entity`, `/create-context`)
- Artefacts (create, edit, diff preview, CodeMirror editor, `#artefact_N` references)
- Next-question suggestion chips after each response
- Per-conversation model overrides (settings modal)
- Multi-model ensemble responses (tabbed output)
- TLDR auto-summaries (tabbed output)
- TTS audio playback on messages
- `/clarify` slash command and auto-clarify checkbox
- Cross-conversation message references with ref badges and click-to-copy
- Shared conversation link generation
- Global Docs modal (upload, list, folders, tags)
- PKB management modal (claims CRUD, contexts, entities, tags)
- Chat settings (web search, PKB, persist, model selection, tool toggles)
- Code execution and artifact rendering
- Conversation docs (upload, list, promote to global)
- Screenshot capture button (`📸`) in the chat input toolbar — **with OCR toggle** (see section 4.6)
- File browser, terminal, and all other web UI features

**Caching optimization**: To reduce network load when opening the Sidebar, the Electron app should implement aggressive caching:
- Cache `interface.html` and static assets (JS, CSS, images) locally with a service worker or Electron's `protocol.registerFileProtocol`.
- Use `If-Modified-Since` / ETags for stale-while-revalidate freshness checks.
- Optionally bundle a local copy of static assets that updates on app rebuild.

**No custom chat UI code** is needed for the Sidebar. The desktop companion's value-add for chat is:
1. Desktop-native screenshot injection (capture → drag-drop simulation into the web UI)
2. Desktop-native file injection (Finder files → drag-drop simulation into the web UI)
3. Desktop-native context injection (app context → paste into chat input via `executeJavaScript`)

**Tab 2: OpenCode (= agentic coding agent)**

The OpenCode tab loads `opencode web` — a full agentic coding agent with its own session management, streaming, tool calling, undo/redo, and diff view. It connects to the remote server's MCP servers for PKB, documents, search, artefacts, prompts, and code execution, plus a **local filesystem MCP** for reading/editing files on the user's Mac.

**How it works**:
1. Electron spawns `opencode web --port <dynamic> --hostname 127.0.0.1` as a child process, with `cwd` set to the user's selected working directory.
2. The OpenCode tab loads `http://127.0.0.1:<port>` in a second `BrowserView`.
3. OpenCode reads its `opencode.json` config (in the working directory or global config) which lists the remote MCP servers and the local filesystem MCP.
4. The `MCP_JWT_TOKEN` environment variable is injected by Electron before spawning, so MCP authentication is automatic — no manual config needed.

**Working directory selector**:
- A directory picker in the OpenCode tab header: dropdown of recent directories + pinned favorites + OS file picker button (macOS `NSOpenPanel`).
- Last 10 directories remembered. User can pin/star frequently used dirs.
- Pinned directories persist across app restarts (electron-store).
- Changing directory: the user is warned that the current OpenCode session will end. On confirmation, Electron kills the `opencode web` child process and restarts it with the new `cwd`.

**MCP server connections (OpenCode tab)**:

OpenCode in Tab 2 connects to these MCP servers:

| MCP Server | Location | Transport | Tools |
|------------|----------|-----------|-------|
| Web Search | Remote (`https://assist-chat.site/mcp/search/`) | Streamable HTTP + JWT | perplexity_search, jina_search, jina_read_page, read_link |
| PKB | Remote (`https://assist-chat.site/mcp/pkb/`) | Streamable HTTP + JWT | pkb_search, pkb_get_claim, pkb_resolve_reference, pkb_get_pinned, pkb_add_claim, pkb_edit_claim, pkb_list_contexts, pkb_list_entities, pkb_list_tags |
| Documents | Remote (`https://assist-chat.site/mcp/docs/`) | Streamable HTTP + JWT | docs_list_*, docs_query, docs_get_full_text, docs_upload_global, docs_delete_global, docs_set_tags, docs_assign_folder |
| Artefacts | Remote (`https://assist-chat.site/mcp/artefacts/`) | Streamable HTTP + JWT | artefacts_list, create, get, update, delete, propose_edits, apply_edits |
| Conversations | Remote (`https://assist-chat.site/mcp/conversations/`) | Streamable HTTP + JWT | conv_get_memory_pad, conv_set_memory_pad, conv_get_history, conv_get_user_detail, conv_get_messages, search_messages, list_messages, read_message, get_conversation_details |
| Prompts & Actions | Remote (`https://assist-chat.site/mcp/prompts/`) | Streamable HTTP + JWT | prompts_list, prompts_get, prompts_create, prompts_update, temp_llm_action, transcribe_audio |
| Code Runner | Remote (`https://assist-chat.site/mcp/code/`) | Streamable HTTP + JWT | run_python_code |
| Image Generation | Remote (`https://assist-chat.site/mcp/image/`) | Streamable HTTP + JWT | generate_image |
| Local Filesystem | Local (Electron, `localhost:<port>`) | Streamable HTTP, no auth | fs_read_file, fs_write_file, fs_edit_file, fs_list_directory, fs_glob, fs_grep, fs_run_shell, fs_mkdir, fs_move, fs_delete |

The local filesystem MCP is sandboxed to the selected working directory. All path operations are validated: `path.resolve(workdir, userPath)` then `resolvedPath.startsWith(workdir)`.

**Tab 1 vs Tab 2 — when to use which**:

| Use case | Tab |
|----------|-----|
| Research chat, PKB management, document Q&A, image generation, multi-model ensemble, TTS | Tab 1 (Chat) |
| Edit code files, run shell commands, grep/search a codebase, agentic multi-step coding tasks | Tab 2 (OpenCode) |
| Both: "search my PKB for X, then edit the config file based on what you find" | Tab 2 (OpenCode has MCP access to PKB + local filesystem) |

**Cross-tab communication**: Deep integration is supported. Tab 1 (Chat) already has `opencode_enabled` mode that routes messages through OpenCode's agentic pipeline. Tab 2 (OpenCode) can reference chat conversations via the Conversations MCP server. However, the two tabs operate independently by default — no automatic synchronization. The user can copy/paste between tabs or use MCP tools to bridge.

**Chrome extension**: The Chrome extension sidepanel keeps its current single-tab architecture (web UI iframe only). OpenCode is desktop-only (Electron). The extension already provides its own capabilities (page extraction, screenshots, custom scripts) that serve the browser context.

**Web-hosted version**: OpenCode is already hosted separately at `opencode.assist-chat.site` (existing subdomain, password-protected). No changes needed — users access it directly in a browser tab when not using the desktop companion.

**Position & snapping**
- **Draggable** to any position on screen.
- **Snap buttons** in the title bar: snap to right edge, left edge, or bottom edge (like Chrome DevTools dock positions).
- Default: right edge, ~400px wide, full screen height minus padding.
- **Last position remembered** until app restart. On restart, resets to default (right edge).
- If snapped to an edge, the Sidebar takes the full height/width of that edge. If floating, it's freely resizable.

**Snap positions**

| Snap | Position | Size |
|------|----------|------|
| Right | Right edge of screen | 400px wide, full height |
| Left | Left edge of screen | 400px wide, full height |
| Bottom | Bottom edge of screen | Full width, 350px tall |
| Float | Wherever the user dragged it | Freely resizable |

**Conversation management**
- The Sidebar loads the full web UI, which includes the workspace sidebar (auto-hidden at narrow widths via mobile responsive mode, visible at wider widths). Users switch conversations via the standard workspace tree — no custom conversation picker needed.
- On first launch, the web UI opens to the last active conversation (standard behavior via `localStorage` persistence).
- When PopBar escalates to Sidebar via "Expand", the user chooses whether to create a new conversation or inject into the active one (see Results Dropdown section 4.2).

**Persistence across app switching**
- The Sidebar is implemented as a separate Electron `BrowserWindow` with `alwaysOnTop: true` at the `'floating'` level.
- It does NOT belong to any specific app — it floats above all windows.
- `Cmd+Tab` switches the app behind the Sidebar, but the Sidebar stays visible.
- Only `Cmd+Shift+J` (Sidebar hotkey) or the close button hides it.

---

### 4.4) Finder / File System Integration

**What it does**
- Adds a "Science Reader" submenu to the macOS Finder right-click context menu when a file is selected.
- Allows sending a file directly to Global Docs or PKB from Finder without opening the web browser.
- **Single file at a time** — multi-file selection is not supported for Finder integration. User right-clicks a single file.

**Right-click menu structure**

When the user right-clicks a file in Finder:

```
[Standard Finder menu items]
─────────────────────────────
Science Reader              ▸
   Add to Global Docs...
   Extract Text to PKB...
   Ask AI About This File
   Summarize Document
```

**"Add to Global Docs..." flow — reuses the existing Global Docs modal**

1. User right-clicks a file in Finder, chooses "Science Reader > Add to Global Docs..."
2. The Sidebar opens (or comes to front). The Electron main process uses `executeJavaScript()` to open the **existing Global Docs upload modal** (`#global-docs-modal`) in the web UI.
3. The file is pre-filled into the modal's file input via simulated drag-and-drop or programmatic file input assignment.
4. If available, the display name field is pre-filled with the filename (sans extension).
5. The user interacts with the standard Global Docs modal: folder picker, tags, display name — all existing UI elements.
6. On upload completion, the modal shows the standard success feedback. User closes the modal.

> **Design principle**: No custom Quick Add form. Reuse the web UI's Global Docs modal (`GlobalDocsManager` in `interface/global-docs-manager.js`). This reduces custom UI code and ensures the desktop experience matches the web experience.

**"Extract Text to PKB..." flow — reuses the existing PKB modal**

1. User right-clicks a file, chooses "Science Reader > Extract Text to PKB..."
2. The Electron main process extracts text from the file **client-side**:
   - PDF: via `pdf-parse` (Node.js library) in Electron's main process
   - DOCX/DOC: via `mammoth` (Node.js library) for DOCX-to-text conversion
   - Plain text / markdown / CSV: read directly from filesystem
   - Images (PNG/JPG/WEBP): OCR via the existing `POST /ext/ocr` endpoint
   - Other formats: show "Unsupported format" toast notification
3. The Sidebar opens. The Electron main process uses `executeJavaScript()` to open the **existing PKB Add Memory modal** (`#pkb-claim-edit-modal`) with the extracted text pre-filled in the statement field, and auto-triggers the auto-fill API (`POST /pkb/analyze_statement`) to classify type, domain, tags, entities, and questions.
4. The user interacts with the standard PKB modal: review auto-filled fields, edit as needed, save.
5. For longer texts where **Extract Multiple** is desired, the Electron main process instead calls `POST /pkb/ingest_text` with `use_llm: true` and opens the existing PKB text ingestion review flow in the web UI.

> **Design principle**: Reuse the web UI's PKB modal (`PKBManager` in `interface/pkb-manager.js`). Client-side text extraction in Electron avoids a server round-trip for common formats.

**"Ask AI About This File" flow**

1. User right-clicks a file, chooses "Science Reader > Ask AI About This File".
2. The Sidebar opens (or comes to front).
3. The Electron main process **simulates a drag-and-drop** of the file onto the web UI's chat area, triggering the existing attachment flow (`setupPaperclipAndPageDrop()` in `interface/common-chat.js`).
4. The web UI processes the drop: the attachment strip shows `[📎 filename.pdf]` above the chat input. Cursor is ready for the user to type a question.
5. User types a question and sends. The file is indexed as a `FastDocIndex` for the turn.

**"Summarize Document" flow**

1. User right-clicks a file, chooses "Science Reader > Summarize Document".
2. The Electron main process extracts text from the file **client-side** (same extraction pipeline as "Extract Text to PKB").
3. The PopBar appears with the Results Dropdown showing a streaming AI summary.
4. The extracted text is sent with a "Summarize this document:" prompt via the PopBar's ephemeral LLM call.
5. Result shows with **Copy** button and **"Expand"** link to continue in Sidebar.

**Supported file types**

| Type | Add to Global Docs | Extract Text to PKB | Ask AI / Summarize |
|------|-------------------|---------------------|--------------------|
| PDF | Yes (native) | Yes (text extraction) | Yes |
| DOCX/DOC | Yes (converted) | Yes (text extraction) | Yes |
| TXT / MD / CSV | Yes | Yes | Yes |
| Images (PNG/JPG/WEBP) | Yes | Yes (via OCR) | Yes (via vision or OCR) |
| XLSX / Parquet / JSON | Yes (data doc) | No | Yes |
| Other | No (show unsupported message) | No | No |

**Implementation: macOS Finder Sync Extension**
- A native Swift `FIFinderSync` subclass bundled inside the Electron `.app` as a `.appex` plugin.
- Communicates with the Electron main process via HTTP POST to `localhost:19876/finder-action`.
- Sends `{ action: "global_docs" | "pkb_extract" | "ask_ai" | "summarize", path: "/path/to/file.pdf" }` (single file).
- Ad-hoc signed (`codesign --sign -`). User enables in System Settings > Login Items & Extensions > Finder Extensions.

---

### 4.5) Text Selection & Services Menu

**What it does**
- Adds "Science Reader" items to the macOS Services menu, which appears in the right-click menu of any app when text is selected.
- Allows saving selected text as PKB memory, asking the AI, or running prompts from anywhere in the OS.

**Right-click menu appearance**

When text is selected in any app (Safari, Notes, VS Code, Terminal, etc.):

```
[Standard app menu items]
─────────────────────────────
Services                    ▸
   Science Reader: Save to Memory
   Science Reader: Ask About This
   Science Reader: Explain
   Science Reader: Summarize
   Science Reader: Send to Chat
   Science Reader: Run Prompt...
```

**"Save to Memory" flow**

1. User selects text in any app, right-clicks > Services > "Science Reader: Save to Memory".
2. macOS sends the selected text to the companion app via Apple Events / custom URL scheme.
3. The companion activates and shows the **Quick Review form** in the PopBar Results Dropdown:
   - Selected text displayed at top (editable, in case the user wants to trim)
   - Three action buttons below the text:
     - **Quick Save** — equivalent to the `/create-simple-memory` slash command: silently calls `POST /pkb/analyze_statement` to classify, then `POST /pkb/claims` to save immediately. Auto-tags with `create-simple`. Toast confirms with claim type and domain.
     - **Review & Edit** — opens the Sidebar and uses `executeJavaScript()` to open the **existing PKB Add Memory modal** (`#pkb-claim-edit-modal`) in the web UI with the selected text pre-filled and auto-fill API triggered. The user interacts with the standard PKB modal.
     - **Extract Multiple** — opens the Sidebar and triggers the existing PKB text ingestion flow in the web UI via `executeJavaScript()`, passing the selected text to `POST /pkb/ingest_text`.
   - The user always chooses which path. No automatic routing.
4. Quick Save: toast confirms in the PopBar area. Review & Edit / Extract Multiple: the Sidebar handles the interaction.

> **Note**: Quick Save is the only path that stays entirely in the PopBar. Review & Edit and Extract Multiple escalate to the Sidebar to reuse the web UI's PKB modals. This avoids building a duplicate PKB form for the desktop companion.

**"Ask About This" flow**

1. User selects text, right-clicks > Services > "Science Reader: Ask About This".
2. The companion captures the selected text and opens the PopBar with the text in Quick Ask mode: `Explain this: "<selected text>"`.
3. The user can edit the prompt before sending, or just press Enter.
4. Response appears in Results Dropdown.

**"Explain" flow**

1. User selects text, right-clicks > Services > "Science Reader: Explain".
2. Selected text is sent directly to AI with "Explain this:" prefix. No PopBar input step.
3. PopBar appears with Results Dropdown showing the streaming AI response.
4. **Replace** and **Copy** buttons available.

**"Summarize" flow**

1. Same as Explain but with "Summarize this:" prefix.

**"Send to Chat" flow**

1. User selects text, right-clicks > Services > "Science Reader: Send to Chat".
2. The Sidebar opens (or comes to front). Selected text is pre-filled in the chat input.
3. User types additional context and sends.

**"Run Prompt..." flow**

1. User selects text, right-clicks > Services > "Science Reader: Run Prompt...".
2. PopBar appears with pinned prompt selector open. User picks a prompt.
3. The selected prompt is applied to the selected text. Result appears in Results Dropdown.
4. **Replace** and **Copy** buttons available.

**Implementation: macOS Services**
- Registered via `NSServices` entry in the Electron app's `Info.plist`.
- Declares `NSSendTypes: [NSStringPboardType]` to receive text from the pasteboard.
- The `NSMessage` handler in the app receives the text and routes to the appropriate flow.

---

### 4.6) Screen Capture & OCR

**What it does**
- Captures screenshots with four modes (including scrolling) and optionally extracts text via OCR.
- Used from the PopBar (Screenshot action) or from the Sidebar (capture button in chat input).
- The AI can "see" what the user is looking at and answer questions about it.
- This is a **read-only** capability — the AI observes the screen but does not control other apps.

**Four capture modes**

| Mode | What it captures | How it's triggered |
|------|-----------------|-------------------|
| **App Window** | The specific frontmost window beneath the overlay | Default mode. Uses `CGWindowListCreateImage` with target window ID via nut.js. |
| **Full Screen** | The entire display (excluding companion surfaces) | Select from submenu. |
| **Select Area** | A user-drawn rectangle on screen | Crosshair cursor appears. User clicks and drags to define region. Screenshot taken of that region only. |
| **Scrolling Screenshot** | Full scrollable content of a window (beyond visible area) | For browsers: uses Chrome extension's existing full-page capture API. For native apps: auto-scroll + stitch (simulate scroll events, capture at each position, stitch images). |

**OCR toggle**
- Each of the four capture modes has an **+OCR** variant.
- In the Screenshot dropdown menu, modes are listed as:
  ```
  App Window
  App Window + OCR
  Full Screen
  Full Screen + OCR
  Select Area
  Select Area + OCR
  Scrolling
  Scrolling + OCR
  ```
- Plain capture → sends image to AI for vision.
- +OCR capture → extracts text first, shows in Results Dropdown. Cheaper and faster than vision for text-heavy content.

**OCR Comment Extraction** (see `documentation/features/extension/multi_tab_scroll_capture.md` and `documentation/changelogs/IFRAME_EXTENSION_OCR_FIX.md`)
- When +OCR mode is selected, an additional **"Extract Comments"** checkbox appears.
- When enabled, the `POST /ext/ocr` endpoint runs **two parallel LLM calls** per screenshot:
  1. Clean text extraction (main document content, ignoring comments/annotations)
  2. Comment extraction (JSON array of `{anchor, body}` objects — the anchor text and comment body)
- Results are displayed in the Results Dropdown with both the clean text and a separate "Comments" section listing each comment with its anchor.
- Useful for document review: captures Google Docs comments, Word track-changes, PDF annotations, and similar annotation formats.
- The `extract_comments` flag is passed through to the OCR endpoint.

**Screenshot flow (from PopBar)**

1. User clicks the Screenshot (`📸`) action button in the PopBar.
2. The dropdown menu shows all 8 options (4 modes x 2 variants).
3. User picks a mode. For "Select Area", the PopBar temporarily hides and a crosshair cursor appears.
4. Screenshot is captured.
5. **Plain capture**: image thumbnail in Results Dropdown + text input for question. Enter sends image+question to AI.
6. **+OCR capture**: extracted text in Results Dropdown with **Replace**, **Copy**, "Ask AI", "Save to PKB" buttons.

**Screenshot flow (from Sidebar)**

1. A capture button (`📸` icon) in the Sidebar's chat input toolbar (injected by the desktop companion via `executeJavaScript` into the web UI).
2. Clicking it shows the same mode submenu with all options including +OCR variants and "Extract Comments" checkbox.
3. **Plain capture**: captured image appears as an attachment thumbnail above the chat input (same UX as existing web UI file attachments). User types a question and sends. Image is included in the message.
4. **+OCR capture**: extracted text is inserted into the chat input field. The original screenshot is also attached as an image for visual context. User can edit the text and send.
5. **+OCR with Extract Comments**: both clean text and comment annotations are inserted into the chat input.

**Scrolling Screenshot implementation**

| App type | Method |
|----------|--------|
| Browsers (Safari, Chrome, Arc) | Use Chrome extension's existing full-page screenshot API. The extension now has 3 capture modes per tab (DOM, OCR, Full OCR) with cross-origin iframe support (probes subframes for scroll targets — important for SharePoint Word Online, Google Docs embeds). See `documentation/features/extension/multi_tab_scroll_capture.md`. |
| Native apps (Slack, Outlook, etc.) | Programmatically send scroll events via Accessibility API, capture visible area at each position, stitch images. May not work perfectly for all apps. |

**The AI does NOT**:
- Type into other apps
- Click buttons in other apps
- Control the mouse or keyboard
- Take actions outside the companion surfaces

Screen reading is passive context gathering only.

**Privacy note**: Screenshots are sent to the LLM provider (OpenRouter) for processing. They are not stored permanently — they exist only for the duration of the chat turn, same as message attachments.

**Permissions required**: Screen Recording permission in System Settings > Privacy & Security. The app prompts for this on first use.

---

### 4.7) Tray Icon & Global Hotkeys

**What it does**
- A persistent menu bar icon (macOS system tray) provides quick access to the companion.
- Global keyboard shortcuts work from any app, even when the overlay is hidden.

**Menu bar icon**

A small monochrome icon in the macOS menu bar (top-right area). Clicking it shows a dropdown menu:

| Menu item | Action |
|-----------|--------|
| Show / Hide PopBar | Toggle PopBar |
| Show / Hide Sidebar | Toggle Sidebar |
| Dictation | Toggle Dictation Pop |
| Capture Screen | Capture frontmost window, open PopBar with screenshot attached |
| Recent Dictations ▸ | Submenu with last 10 transcriptions (click to copy) |
| ─── | separator |
| Connected to: `assist-chat.site` | Status indicator (or `localhost:5000`) |
| Settings... | Open settings window (server URL, hotkey config, position reset, folder sync, PopBar slot config) |
| Quit | Exit the app |

**Global hotkeys**

| Shortcut | Action |
|----------|--------|
| `Cmd+Shift+Space` | Toggle PopBar (show near cursor / hide) |
| `Cmd+Shift+J` | Toggle Sidebar (show / hide) |
| `Cmd+J` | Toggle Dictation Pop (start/stop recording) |
| `Hold Fn` | Push-to-talk dictation (hold to record, release to transcribe) |
| `Cmd+Shift+S` | Capture screen (App Window mode) + open PopBar with screenshot |
| `Cmd+Shift+M` | Open PopBar in "Save to Memory" mode |

Hotkeys are configurable in the Settings window. They are registered via Electron's `globalShortcut` API and work regardless of which app is focused.

**Important**: Global hotkeys override any app-specific shortcuts using the same key combination. The desktop companion's hotkeys take priority.

**Additional hotkey: text selection PopBar trigger**
- When the optional text-selection trigger is enabled, selecting text in any app auto-shows the PopBar.
- This is controlled by a separate toggle in Settings.
- The hotkey (`Cmd+Shift+Space`) is the manual alternative — select text, then press the hotkey to show the PopBar near the selection.
- The auto-trigger and the manual hotkey coexist independently.

---

### 4.8) File Drop Zone

**What it does**
- The overlay (in either mode) accepts drag-and-drop files from Finder or any app.
- Dropping a file triggers the same flow as the Finder right-click "Add to Global Docs" — opening the Sidebar and the web UI's Global Docs modal with the file pre-filled.

**Behavior**

1. User drags a file from Finder toward the overlay.
2. The overlay shows a visual drop zone indicator (dashed border, blue tint, "Drop to add" label).
3. User drops the file.
4. The Sidebar opens (if not already visible) and the web UI's Global Docs modal is triggered via `executeJavaScript()` with the file pre-filled (same as section 4.4 "Add to Global Docs..." flow).
5. If the file is dropped onto the Sidebar's **chat input area** specifically, it behaves like a message attachment instead (same as existing web UI paperclip/drag-drop behavior — creates a `FastDocIndex` for the current turn).

**Drop targets**

| Drop location | Behavior |
|---------------|----------|
| PopBar (anywhere) | Opens the Sidebar and triggers the Global Docs modal with the file pre-filled |
| Sidebar — Chat tab — input area | Attaches to current message (standard web UI drag-drop behavior) |
| Sidebar — Chat tab — message history area | Opens the Global Docs modal with the file pre-filled |
| Sidebar — Workflows tab | Attaches file as workflow input (if workflow expects file input) |

---

### 4.9) Focus Management

**What it does**
- All companion surfaces (PopBar, Dropdown, Sidebar, Dictation Pop) float above other apps without stealing focus.
- The underlying app retains keyboard focus by default. The user explicitly activates a companion surface when they want to type into it.

**Three focus states**

| State | Behavior | Transition to |
|-------|----------|---------------|
| **Hidden** | Surface not visible. No interaction possible. | → Visible via hotkey or tray icon |
| **Hover** (visible, unfocused) | Surface visible but `focusable: false`. Underlying app has keyboard focus. Mouse clicks on buttons work. Text input does NOT accept keystrokes. | → Active (click input or hotkey) |
| **Active** (visible, focused) | Surface `focusable: true` and focused. Keyboard input goes to companion surface. Underlying app loses keyboard focus. | → Hover (Escape) → Hidden (Escape again or hotkey toggle) |

**Implementation**
- Electron `BrowserWindow` with `focusable: false` for hover state (creates macOS `NSPanel` with `NSNonactivatingPanelMask`).
- Toggle to `focusable: true` + `window.focus()` when the user clicks the text input.
- Toggle back on `Escape` or click outside.

**Visual indicators**
- **Hover state**: slightly reduced opacity (0.85), thinner border, input field appears grayed/placeholder.
- **Active state**: full opacity, highlighted border, input field has cursor/focus ring.

**Cross-app persistence (Sidebar + Dictation Pop)**
- The Sidebar and Dictation Pop stay visible when the user `Cmd+Tab`s to another app.
- The PopBar dismisses on app switch (it belongs to the current app's context).

---

### 4.10) Voice Dictation

**What it does**
- System-wide voice-to-text dictation accessible via hotkey from any app.
- Appears as a small **Dictation Pop** widget (Surface 4) distinct from the PopBar.
- Transcribed text is smart-routed: pasted into the focused text field if one exists, otherwise copied to clipboard.
- Maintains a history of the last 10 transcriptions for reuse.
- Supports reformatting transcribed text via prompts before pasting.

**Dictation Pop appearance**
- Small widget (~350x120px) at **bottom-left** of screen by default.
- **Draggable**, remembers last position until app restart (same persistence as Sidebar).
- Shows: recording indicator (waveform/pulsing dot), transcribed text, reformat dropdown, action buttons.

**Two trigger modes**

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Toggle** | `Cmd+J` | First press starts recording. Second press stops and transcribes. |
| **Push-to-talk** | Hold `Fn` | Hold to record. Release to stop and transcribe. |

Both modes can be used interchangeably. If the Dictation Pop is already showing a previous transcription, starting a new recording replaces it.

**Transcription provider**
- **v1**: OpenAI Whisper API (`POST https://api.openai.com/v1/audio/transcriptions`). Fast, accurate, $0.006/min.
- **Future**: configurable in Settings — switch to local Whisper (whisper.cpp), Deepgram, AssemblyAI, Groq.
- Audio is recorded via Electron's media APIs (MediaRecorder with `getUserMedia`). Sent as WAV/WebM to the provider.

**Output routing (smart paste)**

When transcription completes:
1. Check if a text input field is focused in the frontmost app (via Accessibility API: `AXFocusedUIElement` → check if role is `AXTextField` or `AXTextArea`).
2. **If text field focused**: paste transcription at cursor position (simulate `Cmd+V` after writing to clipboard).
3. **If no text field focused**: copy to clipboard + show toast "Copied to clipboard".
4. In both cases, transcribed text is also shown in the Dictation Pop for further action.

**Reformat dropdown**

A dropdown menu in the Dictation Pop, default selection is **"Raw"** (no reformatting):

| Option | What it does |
|--------|-------------|
| **Raw** (default) | Output transcription as-is |
| **As Bullets** | Send transcription through a prompt that reformats as bullet points |
| **As Markdown Paragraphs** | Send transcription through a prompt that reformats as clean paragraph-style markdown |
| **Custom Prompt...** | Opens the pinned prompt selector. User picks a prompt. Transcription is run through it before output. |

When a reformat option other than "Raw" is selected:
1. Transcription completes → text is sent to the LLM with the reformat prompt.
2. Reformatted result replaces the raw text in the Dictation Pop.
3. Smart paste uses the reformatted text.

The reformat selection persists across dictation sessions (remembered until changed).

**Dictation history**

- Last 10 transcriptions stored in memory (not persisted to disk across app restarts).
- Accessible from:
  1. **Dictation Pop**: expandable list at the bottom. Click an entry to copy it or re-paste it.
  2. **Tray menu**: "Recent Dictations" submenu. Click to copy.
- Each history entry shows: timestamp, first ~50 chars of text, reformat type used.

**Dictation Pop layout**

```
┌──────────────────────────────────────┐
│ 🎙  Recording...         [■ Stop]    │
│──────────────────────────────────────│
│ "The transformer architecture uses   │
│  self-attention mechanisms to..."     │
│──────────────────────────────────────│
│ Format: [Raw           ▾]            │
│ [Copy]  [Paste]  [History ▾]         │
└──────────────────────────────────────┘
```

**Permissions required**: Microphone permission in System Settings > Privacy & Security. The app prompts for this on first use.

---

### 4.11) App Context Awareness

**What it does**
- Detects the frontmost app, its window title, URL (for browsers), selected text, and file paths to provide rich context for AI queries.
- Context is **not auto-attached** to queries. Instead, the user explicitly requests context via the **Context button** in the PopBar.
- Inspired by Enconvo's context awareness but with manual control.

**Context levels**

The Context button in the PopBar shows a dropdown with four levels of increasing detail:

| Level | What's included | How it's gathered |
|-------|----------------|-------------------|
| **Basic** | App name + window title | `NSWorkspace.shared.frontmostApplication` + Accessibility API `AXTitle` |
| **+ Selected Text** | Basic + currently selected/focused text in the app | Accessibility API `AXSelectedText` or `AXFocusedUIElement` value |
| **+ Screenshot** | Basic + screenshot of the frontmost app window | `CGWindowListCreateImage` via nut.js |
| **+ Full Scrolling OCR** | Basic + OCR-extracted text from full scrollable content | Scrolling screenshot + OCR pipeline (see 4.6) |

**Per-app context enrichment**

| App type | Extra context available |
|----------|----------------------|
| **Safari / Chrome / Arc** | Current page URL (via AppleScript: `tell application "Safari" to get URL of current tab of front window`), page title |
| **VS Code / Xcode** | Current file path, programming language (via Accessibility API or AppleScript) |
| **Finder** | Selected file paths (via AppleScript: `tell application "Finder" to get selection`) |
| **Terminal / iTerm** | Current working directory, last command (via Accessibility API if available) |
| **Other apps** | Window title only (+ screenshot/OCR if requested) |

**How it works in practice**

1. User presses `Cmd+Shift+Space` (PopBar appears).
2. User clicks the **Context** button (`🔗`).
3. Dropdown shows four levels. User picks one (e.g., "+ Selected Text").
4. A **context chip** appears in the PopBar input area: `[Safari: "Attention Is All You Need" | selected: 247 chars]`.
5. User types their question in the input field.
6. When they press Enter, the context is included as system context in the AI request.
7. User can click the `×` on the context chip to remove it before sending.

**Context chip display**
- Format: `[AppName: WindowTitle | level_detail]`
- Examples:
  - `[Safari: arxiv.org/abs/1706.03762]`
  - `[VS Code: src/app.ts | selected: 42 lines]`
  - `[Finder: 3 files selected]`
  - `[Slack: #general | screenshot attached]`

**Permissions required**: Accessibility permission in System Settings > Privacy & Security > Accessibility. Required for reading selected text, window titles, and focused elements.

---

### 4.12) Folder Sync

**What it does**
- Watches designated folders on the filesystem and automatically uploads new or changed files to Global Docs.
- Eliminates the need to manually add files — drop a PDF into `~/Research/` and it appears in Global Docs within the configured interval.

**Configuration**

In Settings > Folder Sync:

| Setting | Description |
|---------|-------------|
| **Watched folders** | List of folder paths. "Add Folder" button opens a folder picker. |
| **Sync frequency** (per folder) | Real-time (fsevents), every 5 min, every 15 min, every hour, manual only |
| **Auto-assign folder** (per watched folder) | Which Global Docs folder to place files in. Default: "No folder". |
| **Auto-assign tags** (per watched folder) | Tags automatically applied to all files synced from this folder. |
| **File filter** (per watched folder) | Glob pattern to include/exclude files. Default: `*` (all supported types). Example: `*.pdf,*.md` |
| **Enabled/Disabled toggle** (per watched folder) | Pause syncing without removing the configuration. |

**Sync behavior**

1. On app startup, the Electron main process registers `fs.watch` (or `chokidar` for recursive watching) on each enabled watched folder.
2. When a new file is detected (or an existing file is modified):
   a. Check if file type is supported (see 4.4 supported types).
   b. Check if file was already synced (compare by path + modification time in a local SQLite cache).
   c. If new/changed: upload via `POST /global_docs/upload` with the configured folder/tags.
   d. Record the sync in the local cache.
3. A small badge on the tray icon shows sync activity (e.g., spinning icon during upload).
4. Toast notification on completion: "Synced report.pdf to Global Docs".

**Conflict handling**
- If a file was manually uploaded to Global Docs AND exists in a watched folder, the sync skips it (no duplicates).
- If a synced file is deleted from the watched folder, it is **not** deleted from Global Docs (one-way sync only).

**Implementation**
- Desktop-side watcher using `chokidar` (Node.js library, cross-platform file watching with macOS fsevents support).
- Local SQLite database (`~/.science-reader-desktop/sync_cache.db`) tracks: file path, last modified time, global doc ID, sync timestamp.
- Sync runs in the Electron main process, not the renderer.

---

### 4.13) Workflow Engine

> **Authoritative spec**: The workflow engine is fully specified in `documentation/planning/plans/workflow_engine_framework.plan.md` (2,005 lines). This section summarizes the aspects relevant to the desktop companion. The framework plan is the source of truth for all engine internals, API endpoints, models, and implementation phases.

> **Implementation**: The workflow engine is a separate, self-contained `workflow_engine/` module that runs standalone (own Flask server on port 5050 + CLI) or embedded in the main Flask app via blueprint under `/workflows`. It does **not** depend on the desktop companion — the desktop app is one of several clients (web UI, CLI, MCP tools). Desktop-specific workflow work is limited to the Sidebar Workflows tab UI and workflow triggering from PopBar/tray.

**What it does**
- Enables multi-step automated tasks: research pipelines, iterative document writing, Q&A compilation, and structured data extraction.
- Workflows are composable: chaining (state inheritance) and nesting (sub-workflow steps, depth limit 3).
- Supports parallel execution, looping with LLM judge stop conditions, user interaction at any step, and LLM-driven dynamic decision making.
- Automatic checkpointing after every step for crash recovery.
- Real-time UI updates via SSE (Server-Sent Events) with polling fallback.
- Exposed as MCP tools for external agent consumption (OpenCode, Claude Code).

**Architecture overview**

The engine uses an **adapter pattern** with 5 abstract interfaces to decouple from any specific LLM provider, tool system, storage backend, event transport, or user interaction mechanism:

```
workflow_engine/ (self-contained module, zero main app imports)
  ├── models.py          — StepDefinition, WorkflowDefinition, WorkflowRun, StepResult, etc.
  ├── engine.py          — Core WorkflowEngine class (step dispatch, loops, parallel groups)
  ├── executors.py       — Per-step-type executors (LLM, ToolOnly, UserInput, Judge, SubWorkflow)
  ├── state.py           — SharedState (JSON state + markdown scratchpad, thread-safe)
  ├── adapters.py        — Abstract interfaces + standalone/embedded adapter implementations
  ├── events.py          — SSE event types and InMemoryEventBus
  ├── checkpointing.py   — Checkpoint save/load, crash recovery, delta snapshots
  ├── storage.py         — SQLite for definitions + runs, JSON template loader
  ├── endpoints.py       — Flask blueprint (/workflows/* REST API + SSE)
  ├── config.py          — WorkflowEngineConfig dataclass
  ├── errors.py          — Exception hierarchy
  └── templates/         — Pre-built workflow JSON files

Deployment modes:
  STANDALONE: python -m workflow_engine serve  (port 5050, DirectOpenAIAdapter)
  EMBEDDED:   Registered as Flask blueprint in main app (port 5000, CallLLmAdapter + ToolRegistryAdapter)
  CLI:        python -m workflow_engine run <workflow> --prompt '...'
```

**7 step types**

| Step type | Description |
|-----------|-------------|
| **LLM** | Send a rendered prompt template to an LLM, optionally with tools enabled (mini agentic loop, max 5 tool rounds within step). Output written to `output_key`. |
| **TOOL_ONLY** | Execute a specific tool directly with templated arguments, without LLM intermediary. |
| **USER_INPUT** | Pause workflow, present a question/form to the user (text, choice, confirm, clarification), wait for response, resume with response in state. |
| **JUDGE** | Evaluate loop stop condition via natural language criteria. Reads state inputs, calls LLM, returns 'continue'/'stop' verdict. |
| **SUB_WORKFLOW** | Execute another workflow as a nested sub-step. Inherits parent state (deep copy), merges results back. Depth limit 3. |
| **LOOP** | Repeat child steps until JUDGE verdict is 'stop' or `max_iterations` reached, whichever comes first. Body can be single step or sequence of steps. |
| **PARALLEL_GROUP** | Execute child steps concurrently via ThreadPoolExecutor (max 5 workers). Each child writes its own `output_key`. Markdown scratchpad locked during parallel execution. |

**Shared mutable state (dual architecture)**

1. **JSON state object**: structured data passed between steps. Each step reads via `{{state.field_name}}` in prompt templates and writes to its `output_key`. Supports accumulators (append/merge/replace modes for keys that grow across loop iterations).
2. **Markdown scratch pad**: free-text document that accumulates content. Steps can append, prepend, or replace sections. Used by document-building workflows. The final scratch pad is the workflow's primary output artifact.
3. **Template rendering**: `{{state.field}}`, `{{config.key}}`, `{{scratchpad}}`, `{{scratchpad | last_n_lines(N)}}`, `{{state.field | default('fallback')}}`. Simple regex substitution, not Jinja2.

**Loop and stop conditions**

Loops terminate based on:
1. **LLM judge verdict**: a JUDGE step evaluates natural language criteria against the full scratchpad + latest output + original goal + current state. Returns 'continue' or 'stop'.
2. **Fixed iteration count** (`max_iterations`): hard cap.
3. **Both** (whichever triggers first): typical pattern is "repeat up to 5 times, stop early if judge says coverage is sufficient".

**User interaction model**

- **Pause/Resume**: User can pause execution at any point. Current step completes, then execution halts. Resume continues from where it stopped.
- **Guidance injection**: User injects free-text guidance → written to `state.user_guidance`, visible to the next step's prompt. Available while RUNNING or PAUSED.
- **User input steps** (USER_INPUT type): configurable checkpoint steps that pause and ask the user for input (text, choice, confirm, clarification). Configurable timeout (default 300s).
- **LLM-decided dynamic input**: Every LLM step has access to an `ask_clarification` tool via the ToolAdapter. If the LLM decides mid-step it needs user clarification, it calls this tool, which pauses the workflow and surfaces the question in the UI. Transparent to workflow definitions — any LLM step can trigger it.
- **Retry/Skip/Revert**: Per-step error recovery. Retry a failed step, skip it and continue, or revert state to a previous step's checkpoint.
- **State/scratchpad editing**: In debug mode while paused, user can directly edit JSON state or markdown pad.

**Per-step configuration**

Each step supports: `model_override`, `tools_enabled` (tool category whitelist), `output_key` (str or list), `debug_keys`, `accumulator_keys` (append/merge/replace modes), `write_to_scratchpad`, `scratchpad_instruction` (append/replace_section/prepend), `temperature`, `max_tokens`, `timeout_seconds`, `retry_config` (max 3 retries, 2/5/15s backoff).

**Pre-built templates (3 shipped with engine)**

| Template | Description | Steps |
|----------|-------------|-------|
| **Deep Research** | Iterative web research with LLM judge | Plan → Loop(Search + Synthesize + Evaluate + User Checkpoint + Judge, max 5 iterations) → Final Polish |
| **Document Writer** | Iterative document writing with user review | Outline → User Review → Refine → Loop(Select Section + Draft + Progress Check + User Review + Judge, max 10) → Final Edit |
| **Q&A Research** | Multi-question research with parallel execution | Parse Questions → User Confirm → Finalize → Parallel Research per Question → Compile → User Review → Refinement Loop(max 3) → Final Format |

Templates are JSON files, clone-and-customizable via `POST /workflows/definitions/<id>/clone`.

**Triggering workflows from the desktop companion**

| Trigger | How |
|---------|-----|
| **PopBar configurable slot** | Click workflow button → workflow panel opens in Sidebar Workflows tab → provide prompt → starts |
| **Tray menu** | Start Workflow → select from list → opens Sidebar Workflows tab |
| **Sidebar Workflows tab** | "Start Workflow" button, template browser, freeform prompt launch |
| **`/workflow` chat command** | Type `/workflow [template-name] [prompt]` in chat input → opens Workflows tab with template pre-selected |
| **MCP tools** (external agents) | `workflow_start(workflow_id, prompt)` → returns `run_id`, caller polls `workflow_status`/`workflow_result` |

**Run lifecycle and real-time updates**

- Run IDs: `wfr_YYYYMMDD_XXXX` format (timestamp + 4-char random hex).
- Status flow: PENDING → RUNNING → PAUSED / WAITING_FOR_USER → COMPLETED / FAILED / CANCELLED.
- Max 3 concurrent runs per user (configurable). HTTP 429 if exceeded.
- SSE event stream at `GET /workflows/runs/<run_id>/events` with 15s keepalive pings.
- 20+ event types: workflow_started, step_started, step_completed, step_failed, user_input_requested, loop_iteration_started, scratchpad_updated, checkpoint_saved, debug_info, etc.
- Automatic checkpointing after every step. Full snapshots every 10 steps, delta checkpoints between. Crash recovery resumes RUNNING workflows from latest checkpoint on server restart.

**Debug mode**

Per-run opt-in flag. When enabled, every step captures: resolved prompt (with all `{{state.*}}` substitutions applied), raw LLM output, tool calls and results, state before/after (JSON diff), scratchpad before/after (markdown diff), timing, token usage. Available in the Debug View of the workflow panel.

**Composability**

- **Chaining**: Workflow B inherits state from workflow A when invoked as a sub-workflow.
- **Nesting**: Steps can invoke sub-workflows (SUB_WORKFLOW type). Max depth 3, configurable. Each nesting level gets namespaced state.
- **State merging**: Sub-workflow results are merged back into parent state on completion.

---

### 4.14) In-place Text Replacement

**What it does**
- When the user selects text in any app and uses a PopBar action that produces transformed text (Explain, Summarize, prompt-based transforms), the result can be **pasted back** to replace the original selection.
- Both **Replace** and **Copy** buttons are always shown on AI text results.

**Replace mechanism**

1. When the user invokes PopBar with text selected, the app records:
   - The selected text (via clipboard or Accessibility API)
   - The fact that a selection exists
2. When the AI produces a result, the dropdown shows:
   - **Replace** button: writes result to clipboard, simulates `Cmd+V` in the frontmost app
   - **Copy** button: writes result to clipboard only
3. The Replace button is **only shown when text was originally selected**. If the user invoked PopBar without a selection (e.g., just typing a question), only Copy is shown.

**Implementation details**

- Before sending the AI request, the Electron main process reads the current clipboard contents and saves them as "original clipboard".
- On Replace: write AI result to clipboard → simulate `Cmd+V` keypress via nut.js → restore original clipboard contents after a short delay (200ms).
- On Copy: write AI result to clipboard (don't restore original).

**Risks**
- Simulating `Cmd+V` may not work in all apps (some apps intercept paste differently).
- Race condition between clipboard write and paste simulation — mitigated with a short delay.
- Some apps may not have the original text still selected when Replace is clicked (user may have clicked elsewhere) — Replace silently pastes at cursor position in that case.

---

## 5) UX Flows

### 5.1) Flow: "I'm reading something and want to ask the AI about it"

```
User is reading a PDF in Preview.app
  │
  ├─ Presses Cmd+Shift+Space (PopBar hotkey)
  │   └─ PopBar appears near the cursor (hover state, doesn't steal focus)
  │
  ├─ Clicks the Context button (🔗) → selects "+ Screenshot"
  │   └─ Context chip appears: [Preview: research_paper.pdf | screenshot attached]
  │
  ├─ Clicks the text input (PopBar activates, gains focus)
  │   └─ Quick Ask mode is default
  │
  ├─ Types: "What's the main conclusion of this paper?"
  │
  ├─ Presses Enter
  │   ├─ Results Dropdown appears below PopBar
  │   ├─ AI response streams in (markdown rendered), with screenshot as context
  │   └─ [Copy] and [Expand] at bottom of dropdown
  │
  ├─ Option A: User reads the short answer, satisfied
  │   └─ Presses Escape, PopBar + dropdown dismiss, Preview.app regains focus
  │
  └─ Option B: User wants to continue the conversation
      ├─ Clicks "Expand" in the dropdown
      ├─ Choice: "New Conversation" or "Add to [active conversation]"
      ├─ Sidebar slides in from the right edge
      ├─ Query + response + screenshot context injected into chosen conversation
      └─ PopBar + dropdown dismiss. User continues chatting in Sidebar.
```

### 5.2) Flow: "I found a useful PDF and want to save it to my library"

```
User is in Finder, looking at a PDF
  │
  ├─ Right-clicks the PDF
  │   └─ Context menu shows: Science Reader > Add to Global Docs...
  │
  ├─ Clicks "Add to Global Docs..."
  │   ├─ Sidebar opens (or comes to front)
  │   └─ Electron opens the existing Global Docs modal in the web UI
  │       with the PDF file pre-filled in the upload input:
  │       ┌─────────────────────────────────────────────┐
  │       │  Global Docs                                │
  │       │  ┌─ Upload ────────────────────────────────┐│
  │       │  │  File: research_paper.pdf  [ready]      ││
  │       │  │  Display name: [research_paper        ] ││
  │       │  │  Folder: [No folder              ▾]     ││
  │       │  │  Tags: [                              ] ││
  │       │  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ 70% uploading ││
  │       │  └─────────────────────────────────────────┘│
  │       │  ┌─ Your Documents ────────────────────────┐│
  │       │  │  #gdoc_1: old_paper.pdf                 ││
  │       │  │  #gdoc_2: dataset.csv                   ││
  │       │  └─────────────────────────────────────────┘│
  │       └─────────────────────────────────────────────┘
  │
  ├─ User types tags, selects folder — all standard Global Docs modal UX
  │
  ├─ Upload completes. Modal shows the new doc in the list.
  │
  └─ User closes the modal. Sidebar stays open for further use.
```

### 5.3) Flow: "I want to save this text I selected as a memory"

```
User is reading an article in Safari
  │
  ├─ Selects a paragraph of text
  │
  ├─ Option A: Right-clicks > Services > "Science Reader: Save to Memory"
  │   OR
  │   Option B: Presses Cmd+Shift+M (Save to Memory hotkey)
  │   OR
  │   Option C: PopBar auto-appears (if text-selection trigger is enabled)
  │
  │   └─ PopBar appears near selection. 🧠 (Save to Memory) is active.
  │       Results Dropdown shows Quick Review form:
  │       ┌──────────────────────────────────────────────┐
  │       │  Save to Memory                              │
  │       │                                              │
  │       │  "The transformer architecture uses self-    │
  │       │   attention mechanisms to process all        │
  │       │   positions in parallel, unlike RNNs which   │
  │       │   process sequentially."                     │
  │       │                                              │
  │       │  [Quick Save]  [Review & Edit]  [Extract ▾]  │
  │       └──────────────────────────────────────────────┘
  │
  ├─ Path 1: User clicks "Quick Save"
  │   ├─ Calls POST /pkb/analyze_statement → POST /pkb/claims (silent)
  │   └─ Toast: "Saved to PKB (fact, learning, #42)"
  │       PopBar stays open. User presses Escape to dismiss.
  │
  ├─ Path 2: User clicks "Review & Edit"
  │   ├─ Sidebar opens. Electron opens the existing PKB Add Memory modal
  │   │   in the web UI with text pre-filled and auto-fill triggered:
  │   │   ┌──────────────────────────────────────────────┐
  │   │   │  Add Memory (standard web UI modal)          │
  │   │   │                                              │
  │   │   │  Statement: [editable text field           ] │
  │   │   │  Type:      [fact              ▾]            │
  │   │   │  Domain:    [learning          ▾]            │
  │   │   │  Tags:      [transformers, attention       ] │
  │   │   │  Questions: "How do transformers differ..."  │
  │   │   │  Contexts:  [                         ▾]     │
  │   │   │                                              │
  │   │   │  [Cancel]                       [Save ▸]     │
  │   │   └──────────────────────────────────────────────┘
  │   ├─ PopBar dismisses. User interacts with the standard PKB modal.
  │   └─ User saves. Modal closes. Sidebar stays open.
  │
  └─ Path 3: User clicks "Extract Multiple"
      ├─ Sidebar opens. Electron triggers PKB text ingestion in web UI.
      ├─ PopBar dismisses. Web UI shows ingestion proposals for review.
      └─ User approves/edits/rejects proposed claims.
```

### 5.4) Flow: "I want to search my PKB memory from the PopBar"

```
User is working and wants to recall a stored fact
  │
  ├─ Presses Cmd+Shift+Space (PopBar hotkey)
  │   └─ PopBar appears near cursor
  │
  ├─ Clicks 🗂 (Search Memory) action
  │
  ├─ Types: "transformer attention mechanism"
  │
  ├─ Presses Enter
  │   ├─ POST /pkb/search with the query
  │   └─ Results Dropdown shows matching claims:
  │       ┌──────────────────────────────────────────────┐
  │       │  3 results for "transformer attention"       │
  │       │                                              │
  │       │  1. "Transformers use self-attention..."     │
  │       │     [fact] [learning] #42                    │
  │       │                                              │
  │       │  2. "Multi-head attention allows the..."     │
  │       │     [fact] [work] #67                        │
  │       │                                              │
  │       │  3. "Attention is O(n²) in sequence..."      │
  │       │     [fact] [learning] #89                    │
  │       │                                              │
  │       │  [Copy #42]  [Use in Chat]  [View All ▸]    │
  │       └──────────────────────────────────────────────┘
  │
  ├─ User clicks "Use in Chat" on claim #42
  │   └─ Sidebar opens with @transformer_self_attention_a3f2 pre-filled in input
  │
  └─ OR: User copies the claim text and presses Escape.
```

### 5.5) Flow: "Quick question while working"

```
User is writing code in VS Code
  │
  ├─ Presses Cmd+Shift+Space
  │   └─ PopBar appears near cursor (Quick Ask mode)
  │
  ├─ Types: "What's the difference between useEffect and useLayoutEffect?"
  │
  ├─ Presses Enter
  │   ├─ Results Dropdown appears below PopBar
  │   ├─ AI response streams in (4-6 lines, markdown rendered)
  │   └─ [Copy] and [Expand] at bottom
  │
  ├─ User reads the answer, satisfied
  │   └─ Presses Escape. PopBar + dropdown dismiss. VS Code regains focus.
  │
  └─ OR: User wants more detail → clicks "Expand"
      ├─ Choice: "New Conversation" or "Add to [active]"
      └─ Sidebar opens with the exchange injected. PopBar dismisses.
```

### 5.6) Flow: "Screenshot + OCR to extract text from an image"

```
User sees an interesting diagram in a presentation
  │
  ├─ Presses Cmd+Shift+Space (PopBar)
  │
  ├─ Clicks 📸 (Screenshot) → selects "Select Area + OCR"
  │   ├─ PopBar temporarily hides
  │   ├─ Crosshair cursor appears
  │   ├─ User draws a rectangle around the diagram
  │   └─ PopBar reappears
  │
  ├─ OCR runs on the captured region
  │   └─ Results Dropdown shows extracted text:
  │       ┌──────────────────────────────────────────────┐
  │       │  Extracted text:                             │
  │       │                                              │
  │       │  "Layer 1: Input Embedding (d=512)           │
  │       │   Layer 2: Multi-Head Attention (8 heads)    │
  │       │   Layer 3: Feed Forward (d_ff=2048)          │
  │       │   Output: Softmax over vocabulary"           │
  │       │                                              │
  │       │  [Replace]  [Copy]  [Ask AI ▸]  [Save 🧠]   │
  │       └──────────────────────────────────────────────┘
  │
  └─ User clicks "Save to PKB" → Quick Review form appears in dropdown.
```

### 5.7) Flow: "Voice dictation while writing an email"

```
User is composing an email in Gmail (Safari)
  │
  ├─ Cursor is in the email body text field
  │
  ├─ Presses Cmd+J (Dictation toggle)
  │   └─ Dictation Pop appears at bottom-left (or last remembered position)
  │       Recording indicator shows waveform
  │
  ├─ User speaks: "I wanted to follow up on our discussion about the
  │   project timeline. I think we should move the deadline to next Friday
  │   given the recent scope changes."
  │
  ├─ Presses Cmd+J again (stop recording)
  │   ├─ Audio sent to OpenAI Whisper API
  │   ├─ Transcription appears in Dictation Pop
  │   └─ Format dropdown shows "Raw" (default)
  │
  ├─ User changes format to "As Markdown Paragraphs"
  │   ├─ Transcription sent through reformat prompt
  │   └─ Reformatted text replaces raw in Dictation Pop
  │
  ├─ Smart paste detects Gmail text field is focused
  │   └─ Reformatted text is pasted into the email body
  │
  └─ User presses Escape. Dictation Pop dismisses.
      Dictation saved to history (accessible later from tray menu).
```

### 5.8) Flow: "Running a deep research workflow"

```
User wants to research a topic thoroughly
  │
  ├─ Option A: Presses Cmd+Shift+J (Sidebar hotkey) → Workflows tab
  │   OR
  │   Option B: Types in chat: /workflow deep-research Recent advances in protein folding
  │             → Sidebar opens, Workflows tab, Deep Research template pre-selected
  │
  ├─ Workflows tab shows List View → user clicks "Deep Research" template
  │   └─ Launch View appears:
  │       Template: Deep Research (iterative web research with LLM judge)
  │       Steps preview: Plan → Loop(Search → Synthesize → Evaluate → 
  │                      User Checkpoint → Judge, max 5) → Final Polish
  │       Prompt: [                                            ]
  │       [Cancel]  [Run ▸]  [Run in Debug Mode]
  │
  ├─ Types: "Recent advances in protein folding prediction"
  │   └─ Clicks "Run" (or "Run in Debug Mode" for full step inspection)
  │
  ├─ Run View appears. Run ID: wfr_20260303_a3b8. Status: RUNNING.
  │   SSE EventSource connected → real-time updates streaming.
  │   Step timeline (vertical list with status indicators):
  │   ✅ plan_research — completed (11s, 830 tokens)
  │   🔄 research_loop — iteration 2/5
  │      ├─ ✅ search_step (6s)
  │      ├─ 🔄 synthesize_step — running
  │      ├─ ⬜ evaluate_step
  │      ├─ ⬜ user_checkpoint
  │      └─ ⬜ decide_continue (JUDGE)
  │   ⬜ final_polish
  │   Scratchpad preview: "## Research: Protein Folding\n### Findings..."
  │
  ├─ User notices search is focusing on wrong sub-topic
  │   ├─ Clicks "Pause" → current step completes, execution halts
  │   ├─ Status: PAUSED. Clicks "Inject Guidance"
  │   ├─ Types: "Focus on AlphaFold 3 and diffusion-based approaches, not AlphaFold 2"
  │   ├─ Clicks "Resume" → guidance written to state.user_guidance
  │   └─ Next search_step sees guidance in its rendered prompt
  │
  ├─ Iteration 3: user_checkpoint step triggers WAITING_FOR_USER
  │   ├─ Inline form appears in Run View:
  │   │   "Here's a summary of the research so far: Coverage 75%, 
  │   │    Gaps: diffusion model details. Are you satisfied? (yes/no/guidance)"
  │   ├─ User types: "No, dig deeper into RFDiffusion specifically"
  │   └─ Clicks "Submit" → workflow resumes, loop continues
  │
  ├─ Iteration 4: evaluate_step shows 92% coverage.
  │   user_checkpoint → user says "yes"
  │   decide_continue (JUDGE) → verdict: "stop" (>90% coverage)
  │   Loop exits.
  │
  ├─ final_polish runs → Status: ✅ COMPLETED
  │   Scratchpad shows polished research document with citations.
  │   Run View footer: Total 4m 21s, 12.4K tokens.
  │   Export dropdown: [Copy to Clipboard] [Download as MD] [Save as Global Doc]
  │
  └─ Run stays in List View history (last 20 runs retained).
      If in debug mode: click any completed step → see resolved prompt,
      raw LLM output, tool calls, state diff, scratchpad diff.
```

---

## 6) Technical Architecture

### Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Desktop shell | Electron 33+ | BrowserWindow, tray, global shortcuts, IPC |
| Screen automation | nut.js (build from source) | Screenshot capture, window detection, keyboard simulation |
| Accessibility API | Native Node addon (N-API + Swift) | Read focused text, window titles, selected text, app detection |
| Finder extension | Swift / FIFinderSync | Right-click menu in Finder |
| macOS Services | Info.plist NSServices | Right-click on selected text in any app |
| Local IPC server | Express on localhost:19876 | Finder extension → Electron communication |
| File watching | chokidar (Node.js) | Folder sync file system monitoring |
| Audio recording | Electron MediaRecorder API | Voice dictation capture |
| Speech-to-text | OpenAI Whisper API (v1) | Dictation transcription |
| Text extraction | pdf-parse + mammoth (Node.js) | Client-side PDF and DOCX text extraction for Finder "Extract Text to PKB" and "Summarize Document" |
| Frontend (Tab 1) | Existing web UI (loaded as-is in BrowserView) | Full web UI in Sidebar — all features including tool-call-manager.js, image-gen-manager.js, PKB modals, Global Docs modal, artefacts, workspace tree, etc. |
| Frontend (Tab 2) | OpenCode Web (`opencode web` spawned by Electron) | Agentic coding agent with session management, tool calling, diff view, undo/redo. Connects to remote MCP servers + local filesystem MCP. |
| Local Filesystem MCP | Node.js MCP server (spawned by Electron, localhost) | 10 tools: fs_read_file, fs_write_file, fs_edit_file, fs_list_directory, fs_glob, fs_grep, fs_run_shell, fs_mkdir, fs_move, fs_delete. Sandboxed to user-selected working directory. Consumed by OpenCode Tab 2 only. |
| LLM Tool Calling | `code_common/tools.py` — 48 tools, 8 categories, `TOOL_REGISTRY` singleton | Mid-response agentic loop in Sidebar Chat. PopBar uses lightweight single-turn calls (no tools). See `documentation/features/tool_calling/README.md` |
| Image Generation | `endpoints/image_gen.py` — OpenRouter multimodal API | `/image` slash command + standalone modal. 5 models (Nano Banana 2 default). Prompt refinement via Claude Haiku. See `documentation/features/image_generation/README.md` |
| Backend | Existing Flask server + 9 MCP servers (7 existing + Image Gen + extended PKB/Docs/Prompts) | All AI, documents, PKB, search, image generation, OCR. MCP servers exposed via nginx reverse proxy with SSL. |
| Workflow engine | Self-contained `workflow_engine/` module — Flask blueprint under `/workflows` when embedded (see `workflow_engine_framework.plan.md`) | Multi-step execution, shared state (JSON + markdown scratchpad), loops with LLM judge, parallel groups, checkpointing, SSE real-time updates, MCP exposure. Adapter pattern: 5 abstract interfaces for LLM, tools, storage, events, user interaction. |

### Process architecture

```
Electron Main Process
  ├── Session cookie store (shared across all surfaces)
  │     └── Extracts Flask session cookie for main-process API calls
  ├── MCP_JWT_TOKEN env var (injected into OpenCode child process)
  ├── PopBar BrowserWindow (small, near-cursor, non-activating)
  │     ├── Custom HTML: action buttons + input + dropdown + context button
  │     └── Ephemeral queries: temp stateless conversations or temp_llm_action
  ├── Sidebar BrowserWindow (large, edge-snapped, resizable, non-activating)
  │     ├── Tab 1: BrowserView loading full interface.html (all web UI features)
  │     │     └── executeJavaScript() bridge for modal injection (Global Docs, PKB, file drops)
  │     ├── Tab 2: BrowserView loading OpenCode Web (http://localhost:<dynamic>)
  │     │     ├── opencode web child process (spawned with cwd = user's working directory)
  │     │     ├── Connects to remote MCP servers via https://assist-chat.site/mcp/*
  │     │     └── Connects to local filesystem MCP via localhost
  │     └── Tab 3: Loads workflow-panel.js (decoupled UI module) — Workflows panel
  │           ├── SSE EventSource → /workflows/runs/{run_id}/events
  │           └── REST calls → /workflows/* endpoints
  ├── Local Filesystem MCP Server (Node.js, localhost:<dynamic>)
  │     ├── 10 tools: read, write, edit, list, glob, grep, shell, mkdir, move, delete
  │     ├── Sandboxed to user-selected working directory
  │     └── Consumed by OpenCode Tab 2 only
  ├── Working Directory Manager
  │     ├── Directory picker: recent dirs + pinned favorites + OS file picker
  │     ├── On change: warn user → kill opencode web → restart with new cwd
  │     └── Persists recent/pinned dirs in electron-store
  ├── Dictation Pop BrowserWindow (small, bottom-left, non-activating)
  │     └── Custom HTML: recording indicator + transcription + reformat + history
  ├── Express server (port 19876)
  │     └── Receives POSTs from Finder Extension (single file path + action)
  ├── Tray icon + global shortcuts
  │     ├── PopBar: Cmd+Shift+Space
  │     ├── Sidebar: Cmd+Shift+J
  │     ├── Dictation: Cmd+J (toggle) + hold Fn (push-to-talk)
  │     ├── Screenshot: Cmd+Shift+S
  │     └── Save to Memory: Cmd+Shift+M
  ├── Client-side file extraction (pdf-parse, mammoth)
  │     └── Used by Finder "Extract Text to PKB" and "Summarize Document"
  ├── Folder sync watcher (chokidar, per configured folder)
  ├── nut.js — screen capture (4 modes), keyboard simulation, window queries
  ├── Audio recorder — MediaRecorder for dictation
  └── Native addon — macOS Accessibility (text reading, app detection, context)

macOS Finder Extension (.appex)
  └── FIFinderSync — adds context menu, POSTs to localhost:19876

macOS Services (via Info.plist)
  └── Receives selected text via Apple Events → routes to Electron

Remote Server (assist-chat.site)
  ├── Flask server (port 5000) — all AI, chat, documents, PKB, image gen
  ├── Nginx reverse proxy (port 443, SSL termination)
  │     ├── /           → localhost:5000  (Flask web app)
  │     ├── /ext/       → localhost:5001  (Extension server)
  │     ├── /mcp/search/     → localhost:8100  (Web Search MCP)
  │     ├── /mcp/pkb/        → localhost:8101  (PKB MCP)
  │     ├── /mcp/docs/       → localhost:8102  (Documents MCP)
  │     ├── /mcp/artefacts/  → localhost:8103  (Artefacts MCP)
  │     ├── /mcp/conversations/ → localhost:8104  (Conversations MCP)
  │     ├── /mcp/prompts/    → localhost:8105  (Prompts & Actions MCP)
  │     ├── /mcp/code/       → localhost:8106  (Code Runner MCP)
  │     └── /mcp/image/      → localhost:8107  (Image Generation MCP)
  └── All MCP servers bind to 127.0.0.1 (not 0.0.0.0) — reachable only via nginx
```

### Authentication: session cookie sharing

The desktop companion authenticates to the Flask backend via **session cookie sharing**:

1. On first launch (or when the session expires), the Sidebar's `BrowserView` loads the web UI's login page. The user logs in normally.
2. The Flask session cookie is set in Electron's cookie store (shared across all `BrowserView` and `BrowserWindow` instances via the same `session` partition).
3. All direct API calls from the Electron main process (PopBar queries, Finder extension uploads, folder sync) extract the session cookie from Electron's cookie store and include it in their HTTP requests.
4. If the session expires, the web UI in the Sidebar will show the login page. After re-login, the cookie is refreshed for all surfaces.
5. **Cookie extraction**: `session.defaultSession.cookies.get({ url: serverUrl })` retrieves the Flask session cookie. The main process includes it as a `Cookie` header in `fetch` / `net.request` calls.

This approach requires no backend changes (no new auth mechanism). The existing Flask session-based auth works as-is.

### MCP infrastructure: nginx reverse proxy with SSL

The desktop companion (running on the user's Mac) connects to MCP servers hosted on the remote server (`assist-chat.site`). All MCP traffic goes through nginx with SSL — no direct port access.

**Architecture**:
```
Desktop (Mac)                          Remote Server
┌─────────────┐                        ┌────────────────────────────┐
│ OpenCode    │ ──HTTPS (JWT bearer)──▶│ Nginx (port 443)           │
│ Tab 2       │                        │  SSL cert: assist-chat.site│
│             │                        │  ├─ /mcp/search/ → :8100   │
│ PopBar      │ ──HTTPS (session)────▶│  ├─ /mcp/pkb/    → :8101   │
│             │                        │  ├─ /mcp/docs/   → :8102   │
│ Chat Tab 1  │ ──HTTPS (session)────▶│  ├─ /mcp/artefacts/ → :8103│
│             │                        │  ├─ ...etc                  │
└─────────────┘                        │  └─ /            → :5000   │
                                       │                            │
                                       │ MCP servers (127.0.0.1)    │
                                       │  :8100-8107 (localhost only)│
                                       └────────────────────────────┘
```

**Key points**:
- **One SSL certificate**: The existing Let's Encrypt cert for `assist-chat.site` covers all paths. No new certs, no new domains. Path-based routing (`/mcp/search/`, `/mcp/pkb/`, etc.) is handled by nginx location blocks.
- **SSL termination at nginx**: MCP servers themselves speak plain HTTP on localhost. Nginx handles all TLS encryption/decryption. The JWT Bearer token is encrypted in transit.
- **MCP servers bind to `127.0.0.1`** (not `0.0.0.0`): They are only reachable through nginx. No direct port access from the internet.
- **JWT authentication**: Same HS256 JWT mechanism already in use. `MCP_JWT_TOKEN` environment variable is injected by Electron into the OpenCode child process. OpenCode's config uses `{env:MCP_JWT_TOKEN}` template syntax. Rate limited at 10 req/min per token.
- **nginx config**: Each MCP server gets a location block with `proxy_pass http://127.0.0.1:<port>/;` (trailing slash strips the location prefix), `proxy_buffering off`, `proxy_read_timeout 300s`, and standard proxy headers. Added to the existing HTTPS server block — no structural changes to nginx.

**Rejected alternative: local server with shared filesystem**

Running the Flask server locally in Electron (with sshfs/rsync to share the remote filesystem) was evaluated and rejected:
- **SQLite over network filesystems is broken**: `pkb.sqlite` and `users.db` use file-level locking (`fcntl`/`flock`) which does not work reliably over sshfs. Two concurrent writers (local + remote) would corrupt the databases.
- **Conversation JSON files**: `FileLock` has the same problem over network filesystems — partial reads, lost writes, lock contention failures.
- **sshfs latency**: Every file I/O operation adds 50-200ms of network latency. A single `send_message` call does 10-20 file operations, adding 1-4 seconds of pure I/O wait.
- **sshfs reliability**: Drops on network interruption. macOS is particularly bad at recovering from stale FUSE mounts.
- **rsync is not a solution for live data**: Periodic batch copy cannot handle concurrent modifications. SQLite WAL files copied mid-transaction cause corruption.
- **Conclusion**: Remote server is the single source of truth. The desktop companion is a client, not a server peer.

### How the overlay connects to the backend

The Sidebar loads the existing web UI in an Electron `BrowserView`, which communicates with the Flask server via HTTP exactly as it does in a browser. The desktop app adds a thin layer on top for PopBar and desktop-native actions:

| Desktop-specific action | How it reaches the backend |
|------------------------|---------------------------|
| File from Finder → Global Docs | Electron reads file, POSTs to `POST /global_docs/upload` |
| Text from Services → PKB | Electron sends text to `POST /pkb/claims` or `POST /pkb/ingest_text` |
| Screenshot → Chat | Electron captures image, encodes as base64, includes in `POST /send_message` payload |
| Chat messages | Handled by the web UI inside the BrowserWindow (unchanged) |
| Voice dictation → text | Electron records audio, sends to Whisper API, receives text |
| App context → AI query | Electron reads context via Accessibility API, includes as system message in AI request |
| Folder sync → Global Docs | Electron's chokidar detects new file, POSTs to `POST /global_docs/upload` |
| Workflow execution | `workflow-panel.js` in Sidebar sends `POST /workflows/runs` to start, opens `SSE /workflows/runs/{run_id}/events` for real-time updates, REST calls for control (pause/resume/cancel/guidance/input) |

---

## 7) Platform Considerations

### macOS (primary, v1)

| Requirement | macOS API / Approach |
|-------------|---------------------|
| Always-on-top window | `BrowserWindow({ alwaysOnTop: true })` with level `'floating'` |
| Non-activating panel | `focusable: false` creates NSPanel internally |
| Finder right-click | FIFinderSync extension (Swift, Xcode project) |
| Text selection right-click | NSServices in Info.plist |
| Screen capture | `CGWindowListCreateImage` via nut.js or native addon |
| Scrolling screenshot (browsers) | Chrome extension full-page capture API |
| Scrolling screenshot (native apps) | Auto-scroll via Accessibility API + stitch captures |
| Read focused text / selected text | `AXUIElement` Accessibility API via native addon |
| Browser URL detection | AppleScript (`tell application "Safari" to get URL...`) |
| File path detection (Finder) | AppleScript (`tell application "Finder" to get selection`) |
| Menu bar tray | Electron `Tray` API (native macOS support) |
| Global hotkeys | Electron `globalShortcut` API |
| File watching | chokidar with macOS fsevents backend |
| Audio recording | Electron MediaRecorder API |
| Push-to-talk (hold Fn) | Low-level key event monitoring via native addon or `IOKit` |
| Code signing | Ad-hoc: `codesign --force --deep --sign -` |
| Gatekeeper bypass | `xattr -cr /path/to/app` (one-time) |
| Permissions | Accessibility + Screen Recording + Microphone (manual grant in System Settings) |

### Windows (future, v2)

| Requirement | Windows API / Approach |
|-------------|----------------------|
| Always-on-top window | Same Electron API (works cross-platform) |
| Non-activating window | `WS_EX_NOACTIVATE` window style (may need native module) |
| Explorer right-click | Shell Extension (C++ COM DLL) or Windows 11 sparse package |
| Text selection right-click | No direct equivalent to macOS Services; use clipboard monitoring or custom hotkey |
| Screen capture | `BitBlt` / `PrintWindow` via nut.js (cross-platform) |
| Read focused text | UI Automation API via native addon |
| System tray | Electron `Tray` API (cross-platform) |
| Global hotkeys | Electron `globalShortcut` API (cross-platform) |
| File watching | chokidar with Windows fsevents backend |

---

## 8) Backend API Surface

All backend APIs already exist except the Workflow Engine endpoints. The desktop companion is a **new client** for existing endpoints — no backend changes required (except possibly a CORS rule for the Electron origin and the new Workflow API).

### Existing APIs used by the desktop companion

| Feature | Endpoint | Method | Notes |
|---------|----------|--------|-------|
| Chat | `POST /send_message/<conversation_id>` | Streaming | Same as web UI |
| Conversation list | `GET /list_conversations/<domain>` | GET | |
| New conversation | `POST /create_conversation/<domain>/<workspace>` | POST | |
| Upload to Global Docs | `POST /global_docs/upload` | POST (multipart) | File + display_name + folder_id + tags |
| List Global Doc folders | `GET /doc_folders` | GET | For folder picker dropdown |
| Tag autocomplete | `GET /global_docs/autocomplete?q=<prefix>` | GET | For tag input |
| Add PKB claim | `POST /pkb/claims` | POST | statement + claim_type + context_domain + tags + auto_extract |
| Analyze statement | `POST /pkb/analyze_statement` | POST | Returns claim_type, domain, tags, entities, questions |
| Ingest text | `POST /pkb/ingest_text` | POST | Returns proposals for review |
| Execute ingest | `POST /pkb/execute_ingest` | POST | Executes approved proposals |
| Search PKB | `POST /pkb/search` | POST | Semantic search across claims |
| Conversation history | `GET /list_messages_by_conversation/<id>` | GET | |
| Conversation details | `GET /get_conversation_details/<id>` | GET | |
| Prompts list | `GET /prompts/list` | GET | For prompt selector in PopBar |
| Get prompt | `GET /prompts/<name>` | GET | For running a prompt on selected text |
| Generate image | `POST /api/generate-image` | POST | Image generation with context and prompt refinement (see `documentation/features/image_generation/README.md`) |
| Serve conversation image | `GET /api/conversation-image/<conv_id>/<filename>` | GET | Serves stored PNG images from conversation storage |
| Tool response | `POST /tool_response/<conversation_id>/<tool_id>` | POST | Submit user response for interactive tool calls (e.g., `ask_clarification` MCQ modal) |
| OCR with comments | `POST /ext/ocr` | POST | Screenshot OCR with optional `extract_comments` flag for dual-LLM comment extraction |

### New APIs (to be built — see `workflow_engine_framework.plan.md` for full spec)

The workflow engine exposes a Flask blueprint under `/workflows` when embedded in the main app. Full API reference with request/response schemas, validations, error codes, and rate limits is in the framework plan. Summary of endpoints used by the desktop companion:

**Definition CRUD** (for Editor View)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /workflows/definitions` | GET | List all definitions + templates |
| `POST /workflows/definitions` | POST | Create new workflow definition |
| `GET /workflows/definitions/<id>` | GET | Get full definition with steps |
| `PUT /workflows/definitions/<id>` | PUT | Update definition (auto-increments version) |
| `DELETE /workflows/definitions/<id>` | DELETE | Delete definition + run history |
| `POST /workflows/definitions/<id>/clone` | POST | Clone a template as user-owned definition |

**Run Lifecycle** (for Launch/Run Views)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /workflows/runs` | POST | Start a new run (returns `run_id`) |
| `GET /workflows/runs` | GET | List runs (filter by status, workflow_id) |
| `GET /workflows/runs/<run_id>` | GET | Get full run details + step results |
| `GET /workflows/runs/<run_id>/state` | GET | Get current JSON state + scratchpad |
| `PUT /workflows/runs/<run_id>/state` | PUT | Manual state edit (paused only) |
| `DELETE /workflows/runs/<run_id>` | DELETE | Delete completed/failed/cancelled run |

**Run Control** (for Run View action buttons)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /workflows/runs/<run_id>/pause` | POST | Pause running workflow |
| `POST /workflows/runs/<run_id>/resume` | POST | Resume paused workflow |
| `POST /workflows/runs/<run_id>/cancel` | POST | Cancel running/paused workflow |
| `POST /workflows/runs/<run_id>/guidance` | POST | Inject user guidance (max 5000 chars) |
| `POST /workflows/runs/<run_id>/input` | POST | Submit user input for waiting step |
| `POST /workflows/runs/<run_id>/retry` | POST | Retry most recently failed step |
| `POST /workflows/runs/<run_id>/skip` | POST | Skip failed step, continue |
| `POST /workflows/runs/<run_id>/revert` | POST | Revert to previous checkpoint |

**SSE & Debug** (for real-time updates and Debug View)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /workflows/runs/<run_id>/events` | GET (SSE) | Real-time event stream (20+ event types, 15s keepalive) |
| `GET /workflows/runs/<run_id>/checkpoints` | GET | List all checkpoints for a run |
| `GET /workflows/runs/<run_id>/checkpoints/<step_index>` | GET | Get specific checkpoint state |

**Templates**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /workflows/templates` | GET | List pre-built templates with descriptions + input schemas |

**MCP Tools** (registered in `mcp_server/workflows.py`)

| MCP Tool | Maps To | Purpose |
|----------|---------|---------|
| `workflow_templates` | `GET /templates` | List available templates |
| `workflow_start` | `POST /runs` | Start workflow, returns `run_id` |
| `workflow_status` | `GET /runs/<run_id>` | Get current status + progress |
| `workflow_result` | `GET /runs/<run_id>/state` | Get final state + scratchpad |
| `workflow_list` | `GET /runs` | List active and recent runs |
| `workflow_cancel` | `POST /runs/<run_id>/cancel` | Cancel a running workflow |
| `workflow_guidance` | `POST /runs/<run_id>/guidance` | Inject guidance into running workflow |

### Client-side libraries (Electron main process)

The desktop companion uses these Node.js libraries in the Electron main process for local file processing:

| Library | Purpose | Used by |
|---------|---------|---------|
| `pdf-parse` | Extract text from PDF files | Finder "Extract Text to PKB", "Summarize Document" |
| `mammoth` | Convert DOCX to plain text | Finder "Extract Text to PKB", "Summarize Document" |
| `chokidar` | File system watching (macOS fsevents) | Folder sync |
| `electron-store` | Persistent settings storage | PopBar tool whitelist, dictation reformat, folder sync cache |

### PopBar LLM implementation

PopBar's ephemeral queries use a **direct LLM call** (not through `POST /send_message` which requires a conversation):

| Approach | Endpoint | Notes |
|----------|----------|-------|
| **With tools** | `POST /send_message/<temp_conversation_id>` | Creates a temporary conversation for the call, enables configured tool whitelist, max 1-2 iterations. Conversation is marked stateless and cleaned up. |
| **Without tools** | `POST /ext/llm_action` (or equivalent lightweight endpoint) | Direct single-turn LLM call without conversation overhead. Used for Explain, Summarize, prompt execution. |

The PopBar tool whitelist is sent as `checkboxes.enabled_tools` in the request payload, same format as the Sidebar. The max iteration count is enforced client-side by setting `tool_choice="none"` after the configured number of iterations.

### New MCP tools (to be built — see `mcp_expansion.plan.md` for full spec)

The following new MCP tools extend the existing 7 MCP servers and add 1 new server. These enable OpenCode Tab 2 to access the full range of server capabilities. Full implementation spec in `documentation/planning/plans/mcp_expansion.plan.md`.

**Extend Global Documents MCP (port 8102) — 4 new tools**

| MCP Tool | Endpoint | Purpose |
|----------|----------|---------|
| `docs_upload_global` | `POST /global_docs/upload` | Upload file/URL to Global Docs library |
| `docs_delete_global` | `DELETE /global_docs/<doc_id>` | Delete a global doc |
| `docs_set_global_doc_tags` | `POST /global_docs/<doc_id>/tags` | Set tags on a global doc |
| `docs_assign_to_folder` | `POST /doc_folders/<id>/assign` | Assign doc to a folder |

**Extend PKB MCP (port 8101) — 3 new tools**

| MCP Tool | Endpoint | Purpose |
|----------|----------|---------|
| `pkb_list_contexts` | `GET /pkb/contexts` | List all PKB contexts with claim counts |
| `pkb_list_entities` | `GET /pkb/entities` | List all PKB entities with types and linked claim counts |
| `pkb_list_tags` | `GET /pkb/tags` | List all PKB tags with hierarchy and claim counts |

**New Image Generation MCP (port 8107) — 1 tool**

| MCP Tool | Endpoint | Purpose |
|----------|----------|---------|
| `generate_image` | `POST /api/generate-image` | Text-to-image / image editing. Returns base64 image. The Electron client saves the returned image to `{workdir}/{slugified_prompt}.png`. |

**Extend Prompts & Actions MCP (port 8105) — 1 new tool**

| MCP Tool | Endpoint | Purpose |
|----------|----------|---------|
| `transcribe_audio` | `POST /transcribe` | Transcribe audio via Whisper API. Accepts base64 audio. |

**Local Filesystem MCP (runs in Electron, not on server) — 10 tools**

| MCP Tool | Purpose | Security |
|----------|---------|----------|
| `fs_read_file` | Read file content (with optional offset/limit) | Sandboxed to workdir |
| `fs_write_file` | Write/overwrite a file | Sandboxed to workdir |
| `fs_edit_file` | Find-and-replace edit (oldString → newString) | Sandboxed to workdir |
| `fs_list_directory` | List files/dirs with metadata | Sandboxed to workdir |
| `fs_glob` | Find files by glob pattern | Sandboxed to workdir |
| `fs_grep` | Search file contents by regex | Sandboxed to workdir |
| `fs_run_shell` | Run shell command (120s timeout) | cwd = workdir |
| `fs_mkdir` | Create directory (with parents) | Sandboxed to workdir |
| `fs_move` | Move/rename file or directory | Sandboxed to workdir |
| `fs_delete` | Delete file/directory (recursive flag) | Sandboxed to workdir |

**MCP tool inventory summary**:

| Server | Port | Existing tools | New tools | Total |
|--------|------|---------------|-----------|-------|
| Web Search | 8100 | 4 | 0 | 4 |
| PKB | 8101 | 6-10 | +3 | 9-13 |
| Documents | 8102 | 4-9 | +4 | 8-13 |
| Artefacts | 8103 | 8 | 0 | 8 |
| Conversations | 8104 | 12 | 0 | 12 |
| Prompts & Actions | 8105 | 5 | +1 | 6 |
| Code Runner | 8106 | 1 | 0 | 1 |
| Image Generation | 8107 | 0 (new) | +1 | 1 |
| Local Filesystem | Electron | 0 (new) | +10 | 10 |
| **Total** | | **~49** | **+19** | **~68** |

### Possible backend additions (optional, not blocking)

| Addition | Purpose |
|----------|---------|
| CORS for `file://` or `app://` origin | If loading web UI locally in Electron |
| `GET /desktop/status` | Health check for tray icon connection indicator |
| `POST /desktop/capture-ocr` | Dedicated endpoint for screenshot text extraction (could reuse `/ext/ocr`) |
| Stateless temp conversation auto-cleanup | Ensure PopBar's temporary conversations are cleaned up on next page load (existing behavior for stateless conversations) |

---

## 9) Implementation Phases

### Phase 0: MCP Expansion (weeks 1-2)

**Goal**: Extend existing MCP servers with new tools and add Image Generation MCP server. Set up nginx reverse proxy for remote MCP access. Build local filesystem MCP for OpenCode.

**Server-side (remote)**:
- [ ] Extend Documents MCP (port 8102): add `docs_upload_global`, `docs_delete_global`, `docs_set_global_doc_tags`, `docs_assign_to_folder`
- [ ] Extend PKB MCP (port 8101): add `pkb_list_contexts`, `pkb_list_entities`, `pkb_list_tags`
- [ ] New Image Generation MCP (port 8107): add `generate_image` tool wrapping `generate_image_from_prompt()`
- [ ] Extend Prompts & Actions MCP (port 8105): add `transcribe_audio` tool
- [ ] Change all MCP servers to bind to `127.0.0.1` (not `0.0.0.0`)
- [ ] Add nginx location blocks for `/mcp/search/`, `/mcp/pkb/`, `/mcp/docs/`, `/mcp/artefacts/`, `/mcp/conversations/`, `/mcp/prompts/`, `/mcp/code/`, `/mcp/image/` — all within existing HTTPS server block (same SSL cert)
- [ ] Test all MCP servers via `https://assist-chat.site/mcp/*/health`

**Client-side (Electron/Node.js)**:
- [ ] Local Filesystem MCP server (Node.js, spawned by Electron): 10 tools (fs_read_file, fs_write_file, fs_edit_file, fs_list_directory, fs_glob, fs_grep, fs_run_shell, fs_mkdir, fs_move, fs_delete)
- [ ] Sandbox validation: all paths resolved via `path.resolve(workdir, userPath)` then checked with `startsWith(workdir)`
- [ ] MCP server uses streamable-HTTP transport on `localhost:<dynamic-port>`, no auth (local only)

**Deliverable**: All MCP tools available for OpenCode consumption. Remote MCP servers accessible via HTTPS with JWT auth. Local filesystem MCP ready for integration.

### Phase 1: Core Shell (weeks 3-4)

**Goal**: Electron app with floating Sidebar (3 tabs: Chat, OpenCode, Workflows), tray icon, global hotkeys, session cookie sharing, OpenCode child process management.

- [ ] Electron project setup (`desktop/` directory, `package.json`, TypeScript config)
- [ ] Sidebar `BrowserWindow` as always-on-top overlay (floating level, resizable)
- [ ] Tab 1: `BrowserView` inside Sidebar loading full `interface.html` from server (remote URL)
- [ ] Tab 2: OpenCode child process management — spawn `opencode web --port <dynamic> --hostname 127.0.0.1` with `cwd` = selected working directory, inject `MCP_JWT_TOKEN` env var
- [ ] Tab 2: `BrowserView` loading OpenCode Web at `http://127.0.0.1:<dynamic-port>`
- [ ] Tab 2: Working directory selector — recent dirs dropdown + pinned favorites + OS file picker (NSOpenPanel)
- [ ] Tab 2: Directory change flow — warn user → kill opencode process → restart with new cwd
- [ ] Tab 2: `opencode.json` template with remote MCP server URLs (`https://assist-chat.site/mcp/*`) and local filesystem MCP
- [ ] Tab 3: Placeholder for Workflows panel
- [ ] Session cookie sharing: extract Flask session cookie from `BrowserView` cookie store for main process API calls
- [ ] Tray icon with show/hide/quit menu + connection status indicator
- [ ] Global hotkey (`Cmd+Shift+Space`) to toggle PopBar visibility
- [ ] Global hotkey (`Cmd+Shift+J`) to toggle Sidebar visibility
- [ ] Position, size, and snap-state persistence (electron-store)
- [ ] Sidebar snap buttons (right / left / bottom / float) in a minimal title bar
- [ ] Caching strategy: service worker or `protocol.registerFileProtocol` for static assets

**Deliverable**: A floating, resizable panel with 3 tabs. Tab 1 loads the full web UI. Tab 2 runs OpenCode with MCP access to all server capabilities + local filesystem. Session auth is shared. All web UI features work.

### Phase 2: Focus Management (week 3)

**Goal**: The overlay doesn't steal focus. Smooth activate/deactivate transitions.

- [ ] `focusable: false` default state (NSPanel behavior)
- [ ] Click-to-activate on text input → `focusable: true` + `overlay.focus()`
- [ ] Escape to deactivate → `focusable: false` + `overlay.blur()`
- [ ] Visual state changes (opacity, border) for hover vs active
- [ ] Off-screen position recovery

**Deliverable**: Overlay hovers above apps without disrupting focus. User explicitly activates it.

### Phase 3: PopBar UI (weeks 4-5)

**Goal**: PopBar with core actions, configurable tool whitelist, semi-customizable slots, and Results Dropdown. Ephemeral per-query model.

- [ ] Custom PopBar HTML/CSS/JS (separate from web UI — this is desktop-native UI)
- [ ] 8 core action buttons (Quick Ask, Save to Memory, Explain, Summarize, Screenshot, Search Memory, Context, Generate Image)
- [ ] 2-3 configurable slots (settings UI to assign prompts/workflows)
- [ ] Prompt button with pinned prompt selector
- [ ] Results Dropdown with streaming AI responses (markdown rendered)
- [ ] Replace and Copy buttons on all text results
- [ ] Expand escalation with "New Conversation" / "Add to [active]" choice dropdown
- [ ] Ephemeral query model: create temp stateless conversation per query (or use `temp_llm_action` endpoint)
- [ ] Configurable PopBar tool whitelist (Settings > PopBar > Allowed Tools, default: PKB search + add claim)
- [ ] Tool calling with max 1-2 iterations, `ask_clarification` always disabled
- [ ] Inline tool status indicators in Results Dropdown (tool name + spinner/checkmark)
- [ ] Tab cycling between actions
- [ ] Input history (Up/Down arrow)
- [ ] IPC bridge between PopBar (renderer) and main process
- [ ] Model selector dropdown in Quick Ask
- [ ] Session cookie extraction for PopBar API calls (from shared cookie store)

**Deliverable**: A Spotlight-like bar with actions that produce inline results. PKB tools enabled by default. Ephemeral queries with Expand escalation.

### Phase 4: File Ingestion — Drag-and-Drop + Modal Reuse (weeks 5-6)

**Goal**: Drop files onto the overlay to add them to Global Docs via the web UI's existing Global Docs modal. Simulate drag-and-drop for file injection into the web UI.

- [ ] Drag-and-drop handler on the overlay windows (PopBar and Sidebar)
- [ ] PopBar/Sidebar non-chat-input drops → open Sidebar + trigger Global Docs modal via `executeJavaScript()`
- [ ] Pre-fill file into the Global Docs modal's upload input (programmatic file input or simulated drag-drop)
- [ ] Sidebar chat-input drops → standard web UI attachment behavior (no desktop-specific code needed)
- [ ] File injection helper: `executeJavaScript()` function to programmatically open web UI modals and inject data
- [ ] Toast notifications for success/failure via Electron's native notification API

**Deliverable**: Can add files to Global Docs by dragging them onto the overlay. Uses the web UI's existing modal.

### Phase 5: Text Selection → PKB (macOS Services) (weeks 6-7)

**Goal**: Right-click selected text in any app → Save to Memory, Explain, Summarize, Send to Chat, Run Prompt. Reuse web UI modals for Review & Edit and Extract Multiple.

- [ ] NSServices registration in Info.plist (6 service entries)
- [ ] Apple Events handler in Electron main process
- [ ] Quick Review form in PopBar (Quick Save / Review & Edit / Extract Multiple buttons)
- [ ] Quick Save: direct API calls from main process (`POST /pkb/analyze_statement` → `POST /pkb/claims`), toast notification
- [ ] Review & Edit: opens Sidebar + opens existing PKB Add Memory modal via `executeJavaScript()` with text pre-filled and auto-fill triggered
- [ ] Extract Multiple: opens Sidebar + triggers existing PKB text ingestion flow via `executeJavaScript()`
- [ ] Explain and Summarize: direct PopBar actions with Replace/Copy in Results Dropdown
- [ ] Send to Chat: opens Sidebar, pastes text into chat input via `executeJavaScript()`
- [ ] Run Prompt: opens pinned prompt selector in PopBar, applies to text

**Deliverable**: Select text anywhere on macOS, right-click, multiple Science Reader actions available. PKB actions reuse web UI modals.

### Phase 6: Finder Extension (weeks 8-10)

**Goal**: Right-click a file in Finder → Add to Science Reader. Single file at a time. Reuse web UI modals.

- [ ] Xcode project for Finder Sync Extension (`desktop/finder-extension/`)
- [ ] FIFinderSync subclass with 4 menu items (Add to Global Docs, Extract Text to PKB, Ask AI, Summarize)
- [ ] Express server on localhost:19876 in Electron main process
- [ ] Finder extension POSTs single file path to Express server: `{ action, path }`
- [ ] "Add to Global Docs": opens Sidebar + Global Docs modal with file pre-filled via `executeJavaScript()`
- [ ] "Extract Text to PKB": client-side text extraction (pdf-parse for PDF, mammoth for DOCX, `/ext/ocr` for images) → opens Sidebar + PKB Add Memory modal with text pre-filled
- [ ] "Ask AI": opens Sidebar + simulates drag-drop of file onto chat input area
- [ ] "Summarize": client-side text extraction → PopBar Results Dropdown with streaming summary
- [ ] Ad-hoc code signing of the `.app` bundle
- [ ] User documentation for enabling the extension in System Settings

**Deliverable**: Right-click a file in Finder → 4 Science Reader actions. Global Docs and PKB actions reuse web UI modals.

### Phase 7: Screen Context & Capture (weeks 10-12)

**Goal**: Full app context awareness + screenshot capture with 4 modes + OCR.

- [ ] nut.js integration for window detection and screenshot capture
- [ ] Native addon for macOS Accessibility API (AXUIElement: read window title, focused text, selected text)
- [ ] AppleScript integration for browser URLs, Finder selections, VS Code file paths
- [ ] Context button in PopBar with 4-level dropdown
- [ ] Context chip display in PopBar input
- [ ] 4 capture modes: App Window, Full Screen, Select Area, Scrolling
- [ ] OCR toggle per capture mode (PopBar and Sidebar)
- [ ] "Extract Comments" checkbox for +OCR modes
- [ ] Scrolling screenshot: browser extension integration + native app auto-scroll+stitch
- [ ] Sidebar screenshot button injected via `executeJavaScript()` into web UI's chat input toolbar — with full OCR support
- [ ] In-place text replacement (Replace button): clipboard save → paste simulation → clipboard restore
- [ ] Screen Recording permission prompt on first use

**Deliverable**: Full app context awareness. Press hotkey, see what the AI knows about your current app. Screenshot any content with OCR. OCR available in both PopBar and Sidebar.

### Phase 8: Voice Dictation (weeks 12-14)

**Goal**: System-wide voice dictation with transcription, reformatting, and history.

- [ ] Dictation Pop BrowserWindow (small, bottom-left, draggable, position memory)
- [ ] Audio recording via Electron MediaRecorder API
- [ ] OpenAI Whisper API integration for transcription
- [ ] Toggle hotkey (`Cmd+J`) and push-to-talk (hold `Fn`) triggers
- [ ] Smart paste: detect focused text field → paste, else clipboard
- [ ] Reformat dropdown (Raw, As Bullets, As Markdown Paragraphs, Custom Prompt)
- [ ] Dictation history (last 10, accessible in Dictation Pop + tray menu)
- [ ] Microphone permission prompt on first use

**Deliverable**: Press `Cmd+J`, speak, text appears in the current app. Reformat before pasting. History for reuse.

### Phase 9: Folder Sync (weeks 14-15)

**Goal**: Watched folders auto-sync files to Global Docs.

- [ ] Settings UI for folder sync configuration
- [ ] chokidar file watcher integration
- [ ] Local SQLite cache for sync state
- [ ] Upload on file detection with configured folder/tags
- [ ] Configurable frequency per folder (real-time, 5 min, 15 min, hourly, manual)
- [ ] Tray icon badge for sync activity
- [ ] Duplicate detection (skip already-synced files)

**Deliverable**: Drop a file into a watched folder → it appears in Global Docs automatically.

### Phase 10: Workflow Engine Integration (weeks 16-20)

**Goal**: Integrate the workflow engine (built per `workflow_engine_framework.plan.md`) into the desktop companion.

> **Note**: The workflow engine backend (7 implementation phases in the framework plan) is built independently of the desktop companion. Phase 10 here covers the **desktop-side integration** — loading the workflow panel UI in the Sidebar and wiring up workflow triggers from PopBar/tray. The backend engine work is tracked in its own plan.

**Backend prerequisites** (from `workflow_engine_framework.plan.md`, must be done before or in parallel):
- [ ] Phase 1-3: Core engine + executors + REST API + SSE endpoints (the `/workflows/*` blueprint)
- [ ] Phase 4: Pre-built templates (Deep Research, Document Writer, Q&A Research)
- [ ] Phase 5: Main app integration (register blueprint in `server.py`, embedded adapters, `/workflow` chat command)
- [ ] Phase 5: MCP tool registration (`mcp_server/workflows.py`)
- [ ] Phase 5: Deprecate `ext_workflows` endpoints

**Backend UI** (from `workflow_engine_framework.plan.md` Phase 6, needed for Sidebar):
- [ ] `workflow-panel.js` — decoupled UI module with List/Launch/Run/Debug/Editor views
- [ ] `workflow-panel.css` — standalone CSS with `.wfp-*` prefix
- [ ] `workflow-standalone.html` — standalone page at `/workflows/ui`
- [ ] Drawer integration in main web app (right drawer overlay + `/workflow` chat command handler)

**Desktop-specific work**:
- [ ] Sidebar Workflows tab (Tab 3) loads `workflow-panel.js` with desktop-appropriate config (apiBase pointing to backend, container targeting the tab pane, auth headers from desktop session)
- [ ] SSE EventSource connection for real-time run updates in Sidebar
- [ ] Workflow trigger from PopBar configurable slot → opens Sidebar Workflows tab with template pre-selected
- [ ] Workflow trigger from tray menu → opens Sidebar Workflows tab
- [ ] `/workflow` command in PopBar text input → opens Sidebar Workflows tab with template + prompt
- [ ] Pop-out workflow panel in separate Electron BrowserWindow (loads `workflow-standalone.html`)
- [ ] Export callback wiring: "Save as Global Doc" / "Copy to Clipboard" / "Download" from workflow panel

**Deliverable**: Run multi-step research and document generation workflows from the desktop companion with visual progress, user interaction, debug inspection, and composable steps. The same workflow panel works in the web UI, standalone page, and desktop Sidebar.

### Phase 11: Polish & Packaging (weeks 20-22)

**Goal**: Production-ready for daily use.

- [ ] electron-builder config for macOS `.app` and `.dmg`
- [ ] Ad-hoc signing script
- [ ] Settings window (server URL, hotkey config, startup on login, PopBar slot config, folder sync, dictation provider)
- [ ] Launch on login (macOS Login Items)
- [ ] Error handling for server disconnection (tray icon shows status)
- [ ] Performance profiling (memory, CPU while idle)
- [ ] Keyboard accessibility throughout all forms

---

## 10) Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| macOS Accessibility/Screen Recording/Microphone permission denial | Low (personal use) | Blocks context/screen/dictation features | Prompt on first use; document manual grant steps |
| Finder extension fails to load without paid certificate | Medium | Blocks Finder integration | Test ad-hoc signing thoroughly; fallback to drag-and-drop |
| `focusable: false` breaks input in overlay | Medium | Core UX broken | Prototype focus toggle early (Phase 2); test on macOS Sequoia |
| nut.js build-from-source fails on Apple Silicon | Low | Blocks screen capture | Fallback to Electron's `desktopCapturer` API (built-in) |
| Electron's 150MB+ binary size | Certain | Disk usage | Acceptable for personal tool; not distributing |
| Web UI doesn't render well at 400px width | Medium | Chat panel looks broken | Test responsive behavior early; may need CSS overrides |
| macOS Services registration requires app restart | Low | Minor UX friction | Document the one-time setup; macOS caches Services |
| Server connection lost while using overlay | Medium | Actions fail silently | Tray icon shows connected/disconnected status; retry logic |
| In-place text replacement (Cmd+V simulation) fails in some apps | Medium | Replace button doesn't work | Always show Copy as fallback; document known incompatible apps |
| Scrolling screenshot for native apps (auto-scroll+stitch) unreliable | Medium | Incomplete captures | Best-effort; fall back to visible-area-only capture. Browser scrolling via extension is reliable. |
| Push-to-talk (hold Fn) conflicts with macOS system shortcuts | Medium | Dictation trigger doesn't work | Make push-to-talk key configurable; document conflicts |
| Workflow engine complexity — scope creep during implementation | Medium (reduced) | Delays other features | Workflow engine is now a **separate project** (`workflow_engine_framework.plan.md`) with its own 7-phase plan, built independently of the desktop companion. Desktop Phase 10 only covers UI integration. Risk is reduced because the engine is self-contained and testable in isolation. |
| Long-running workflows (up to 60 min) hit SSE connection timeouts | Medium | Desktop loses real-time updates | SSE endpoint uses 15s keepalive pings. If SSE disconnects, `workflow-panel.js` auto-reconnects and uses polling API for missed events. Nginx `proxy_read_timeout` already set to 3600s. |
| Concurrent workflows (up to 3 per user) strain server resources | Low | Slowdown or OOM | Each workflow run uses a single thread (sequential). Parallel steps bounded at 5 workers. Rate limiting per user via Flask-Limiter. |
| OpenAI Whisper API latency for dictation | Low | Slow transcription | Typical latency <2s for short clips. Future: switch to streaming providers (Deepgram) |
| Folder sync creates duplicates or misses files | Medium | Messy Global Docs library | SQLite cache tracks synced files; add manual "force re-sync" button |
| Session cookie expires while PopBar/folder sync is active | Medium | API calls fail silently | Detect 401/403 responses → show "Session expired" in tray icon → user re-logs in via Sidebar `BrowserView`. Queue folder sync uploads until re-authenticated. |
| `executeJavaScript()` modal injection breaks on web UI changes | Medium | Finder/Services actions fail to open modals | Version the injection scripts. Pin web UI version in desktop config. Test injection after web UI updates. |
| `pdf-parse` / `mammoth` fail on complex files | Low | "Extract Text to PKB" shows garbled text | Fall back to uploading file to server for extraction. Show "extraction failed" toast with option to open in web UI. |
| Simulated drag-and-drop for file injection fails | Medium | "Ask AI About This File" can't attach files | Fall back to `executeJavaScript()` calling the paperclip upload function directly with a programmatic File object. |

---

## 11) Out of Scope

The following are explicitly NOT part of this product:

- **Multi-user support** — single user, single machine
- **App Store distribution** — personal tool only
- **Auto-update mechanism** — manual rebuild in v1
- **Offline mode** — requires connection to the Flask server (and Whisper API for dictation)
- **AI controlling other apps** (typing, clicking into them beyond paste simulation) — read-only screen context in v1
- **Windows support** — macOS only in v1; Windows deferred to v2
- **Custom chat UI for Sidebar** — the Sidebar loads the full web UI as-is. No stripped-down or forked version. All web UI features (workspace management, settings, file browser, terminal, multi-model, TTS, artefacts, sharing) come free.
- **Custom conversation picker** — conversation switching uses the web UI's workspace sidebar (auto-hidden at narrow widths, visible when widened)
- **Custom PKB/Global Docs forms for desktop** — Finder and Services actions reuse the web UI's existing modals via `executeJavaScript()` injection. Only PopBar's Quick Save is a custom lightweight form.
- **Multi-file Finder actions** — Finder right-click operates on a single file at a time. Batch operations use the web UI.
- **`#context` typed modifiers** — context is button-based, not typed (decided against Enconvo's `#screen` / `#clipboard` approach)
- **Visual node/graph workflow editor** — workflows use pre-built templates + a nested/indented step tree editor, not a node-based visual graph editor (like n8n, Apple Shortcuts, or LangGraph Studio). The step editor is a structured tree, not a canvas with draggable nodes and connections.
- **Translate action** — not included as a standalone action; user can type "translate" in Quick Ask
- **~~Image generation~~** — ~~not included~~ **NOW INCLUDED**: Generate Image is core action #8 in PopBar, and the `/image` slash command + standalone modal are available in the Sidebar Chat tab. See `documentation/features/image_generation/README.md`.
- **Live closed captions** — not included; use macOS built-in or dedicated tools
- **Extension/plugin system** — not building a marketplace; prompts + workflows serve this role
- **PopBar conversation history** — PopBar queries are ephemeral (no persistent conversation). For conversation history, use the Sidebar.
- **PopBar interactive tools** — `ask_clarification` is disabled in PopBar. The MCQ modal UX doesn't fit the compact dropdown. Escalate to Sidebar for interactive tool use.

---

## Appendix A: Background Research & Competitive Analysis

### Research methodology

Between 2026-03-01 and 2026-03-03, we conducted web research on macOS AI desktop companion apps to inform our architecture and UX decisions. Tools used: Perplexity search, Jina search, direct website fetching, and Enconvo documentation deep-dive.

### Apps researched (prior session, 2026-03-01)

| App | Type | Key takeaway for our design |
|-----|------|----------------------------|
| **Enconvo** | Native macOS AI companion ($49-99 lifetime) | Primary inspiration. 5 UI surfaces (SmartBar, PopBar, Companion Orb, App Sidebar, Agent Mode). Deep context awareness. 100+ plugins. Open-source extensions. **Most feature-rich competitor.** Deep-dived in this session. |
| **FridayGPT** | macOS AI assistant | Lightweight, Spotlight-style interface. Showed that a simple command bar + floating panel is sufficient for most interactions. |
| **Raycast** | macOS productivity launcher with AI | Command bar + results panel pattern. Our Results Dropdown is directly inspired by Raycast's results UX. Quick, keyboard-driven. |
| **Alfred** | macOS productivity launcher | Workflow system (Alfred Workflows) demonstrated how power users chain actions. Informed our decision to add workflows. |
| **Sky** (by Shortcuts creators) | macOS AI assistant | Showed how Apple Shortcuts-style automation can be applied to AI tasks. Influenced our workflow thinking. |
| **OverAI** | macOS AI overlay | Floating overlay pattern. Confirmed the viability of always-on-top non-activating panels on macOS. |
| **One Chat** | Multi-model AI chat app | Demonstrated conversation management across multiple models. We already have this in our web UI. |

### Enconvo deep-dive (this session, 2026-03-03)

**Source**: Enconvo website (enconvo.com), documentation (docs.enconvo.ai), feature pages for SmartBar, PopBar, Companion Orb, App Sidebar, Context Awareness, Knowledge Base, Workflows, Dictation, Skills, Extensions.

**Enconvo's five UI surfaces**

| Surface | Hotkey | Purpose | Our equivalent |
|---------|--------|---------|---------------|
| **SmartBar** | `Cmd+Shift+D` | Spotlight-like command bar with `@plugin` and `#context` modifiers. Center of screen. Free-text input. | Our **PopBar** (merged SmartBar+PopBar into one surface near cursor) |
| **PopBar** | Auto on text selection | Text selection toolbar. Writing tools only (improve, fix spelling, translate, etc.). No free-text input. | Part of our **PopBar** (we added free-text input, Enconvo's PopBar is action-buttons-only) |
| **Companion Orb** | `Cmd+Shift+A` (voice) | Persistent sidebar with quick-action buttons (Screenshot OCR, Voice Chat, Summarize URL). Auto-hide. | Our **Sidebar** (but ours loads full web UI chat, not just quick actions) |
| **App Sidebar** | `Cmd+Shift+T` | Per-app AI agent sidebar. Attaches to each app window. Context differs per app (browser URL, code file, Finder selection). | **No direct equivalent.** We chose an app-agnostic Sidebar + manual Context button instead. |
| **Agent Mode** | In chat | Full AI agent with memory, KB access, tool use, long-running tasks. | Our **chat** (via existing Flask backend with PKB, docs, web search, code execution) |

**Key Enconvo features analyzed and our decisions**

| Enconvo feature | What it does | Our decision | Rationale |
|----------------|-------------|-------------|-----------|
| `@plugin` commands | Type `@translate`, `@ocr`, `@image` in SmartBar to invoke plugins | **Not adopted.** Use action buttons + prompt selector instead. | Simpler UX. We don't have 100+ plugins — our actions are finite and button-accessible. |
| `#context` modifiers | Type `#screen`, `#clipboard`, `#browser`, `#finder` to attach context | **Not adopted.** Manual Context button with dropdown instead. | Typing modifiers requires memorization. Button with visual dropdown is more discoverable. |
| Writing tools in PopBar | Improve Writing, Make Professional, Make Casual, Fix Spelling, Expand, Bullet Points | **Kept minimal.** Explain + Summarize as core actions. Other transforms via prompt selector (configurable slots). | Our prompt store already has these capabilities. Adding fixed writing tool buttons duplicates existing functionality. |
| In-place text replacement | PopBar result has "Replace" button that pastes back into original app | **Adopted.** Both Replace and Copy buttons on all text transform results. | High-value feature. Makes PopBar truly useful for text editing workflows. |
| App Sidebar (per-app agent) | Sidebar attached to each app with per-app context detection | **Not adopted as separate surface.** Instead: app-agnostic Sidebar + manual Context button with 4 levels. | Per-app sidebar is complex to implement and maintain. Manual context button gives same information with less magic. |
| Context Awareness (auto-detect) | Auto-detects active app, browser URL, code file, selected text. Always included. | **Adopted but manual.** Context button with dropdown (Basic, +Text, +Screenshot, +Full OCR). Not auto-attached. | Auto-attach adds cost to every query. Manual control lets user decide when context is needed. |
| Workflows | Chain plugins into automated multi-step processes. Triggers, actions, outputs. | **Adopted and expanded.** Full workflow engine with loops, parallel steps, LLM judge, user interaction, scratch pad, composable sub-workflows. | We need deep research and document generation pipelines. Enconvo's workflows are simpler (linear chains). Ours are more like a lightweight orchestration engine. |
| Dictation | System-wide voice input. Multiple providers (Microsoft, AssemblyAI, Deepgram, Groq, local Whisper). Toggle + push-to-talk. | **Adopted.** Separate Dictation Pop surface. OpenAI Whisper API v1, others later. Added: smart paste, reformat dropdown, history. | Voice input is genuinely useful for long-form dictation. Enconvo proved the UX pattern works. |
| Knowledge Base | Document indexing with folder sync, collections, semantic search, `@kb` queries. | **Partially adopted.** We already have PKB + Global Docs. Added: folder sync feature. Collections/`@kb` syntax not needed (we have `@friendly_id` and `#gdoc_N`). | Our existing PKB/Global Docs system is more sophisticated than Enconvo's KB. Folder sync fills the remaining gap. |
| Skills (SKILL.md) | Instruction files that teach the AI specific workflows. Auto-trigger based on description matching. | **Not adopted.** We already have a prompt store with prompt selection. | Our prompt management system serves the same purpose. Skills are Enconvo's version of prompts. |
| Extension system (100+ plugins) | Open-source plugin ecosystem. GitHub-based. Installable via `/skill-installer`. | **Not adopted.** Our prompts + workflows cover extensibility. | We're a single-user tool, not a platform. No need for a plugin marketplace. |
| Live Closed Captions | System-wide speech recognition with real-time translation. | **Not adopted.** | Too specialized. macOS has built-in Live Captions. Not related to our AI assistant use case. |
| Image Generation | Stability Diffusion, DALL-E, Flux via SmartBar/plugins. | **Now adopted.** PopBar Generate Image action (#8) + `/image` slash command + standalone modal in Sidebar. Uses OpenRouter multimodal API (Nano Banana 2 default). Includes image editing and conversation-aware prompt refinement. | Image generation was implemented in the backend (`endpoints/image_gen.py`) after the initial BRD. It's now a core feature. See `documentation/features/image_generation/README.md`. |
| Video Downloader | Download videos from YouTube, TikTok, etc. | **Not adopted.** | Unrelated to our use case. |
| Offline/Privacy Mode | Local LLMs via Ollama/LM Studio. | **Not adopted for v1.** Our backend already supports model selection including local models. | The desktop companion connects to our Flask backend which handles model routing. Local model support is a backend concern, not a desktop app concern. |

**Enconvo's technical architecture (for reference)**

- **Native macOS app** (Swift/AppKit, NOT Electron) — optimized for performance and system integration
- **Native Swift** context awareness — deep integration with Accessibility API, AppleScript
- **Open-source extensions** on GitHub (github.com/enconvo) — plugin-based architecture
- **Pricing**: Free (10 uses/day), Standard ($49, 1 year updates, 1 Mac), Premium ($99, lifetime, 3 Macs), Cloud ($10/mo)
- **macOS 13+** requirement (Ventura or later)
- **~200MB** storage requirement

Our approach differs fundamentally: we use Electron (cross-platform potential, web tech stack) connecting to our existing Flask backend. We trade native performance for development speed and code reuse with our web UI.

### Research sources

- Enconvo website: https://enconvo.com (main page, pricing, FAQ)
- Enconvo docs: https://docs.enconvo.ai (all feature pages: SmartBar, PopBar, Companion Orb, App Sidebar, Context Awareness, Knowledge Base, Workflows, Dictation, Skills, Extensions)
- Enconvo docs index: https://docs.enconvo.ai/llms.txt (complete page listing)
- YouTube demos: SmartBar (CZ9Oash0rMk), PopBar (Vky72-N0qQM), Companion Orb (qCFZd00hM9g), App Sidebar (uzfm32lKzKk), Context Awareness (VKhyKibToAw), Voice Input (SB-zzuQY9eU)
- Other apps: researched via web search in prior session (2026-03-01)

---

## Appendix B: Technology Selection Rationale

### Why Electron (not Tauri, not native Swift)

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Electron** | Web tech stack (JS/TS/HTML/CSS) — same as our existing web UI. Mature ecosystem. Rich BrowserWindow API (always-on-top, focusable toggle, tray). Can load our existing web UI directly in a BrowserWindow. Large community, well-documented. Cross-platform (Windows v2). | ~150MB binary size. Higher memory usage than native. Not as performant as native Swift. | **Chosen.** Development speed and web UI reuse outweigh performance concerns for a personal tool. |
| **Tauri** | Smaller binary (~10MB). Uses system WebView. Rust backend (fast, safe). | Smaller ecosystem. WebView has rendering inconsistencies across OS versions. Less mature BrowserWindow API (limited always-on-top control, no NSPanel-equivalent `focusable` toggle out of box). Rust is a different stack from our Python/JS backend. | **Rejected.** The `focusable: false` / NSPanel behavior is critical for our non-activating overlay UX. Tauri's WebView doesn't give us the same control. |
| **Native Swift (AppKit)** | Best macOS integration. Native NSPanel support. Smallest footprint. Best performance. This is what Enconvo uses. | Completely different tech stack from our web app (Swift vs JS/Python). Can't reuse existing web UI. macOS-only (no Windows path). Much longer development time for a single developer. | **Rejected.** Development time is the bottleneck. We'd have to rewrite the entire chat UI in Swift. Electron lets us load the existing web UI as-is. |

### Why nut.js (not native-only, not desktopCapturer-only)

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **nut.js** (build from source) | Cross-platform (macOS + Windows). Handles screenshots, window detection, mouse/keyboard simulation. Free when built from source. Node.js native addon — integrates with Electron. | Must build from source (pre-built binaries require paid license). Build may fail on some Apple Silicon configurations. | **Chosen.** Provides the most functionality in one library. Building from source is a one-time setup. |
| **Electron `desktopCapturer`** | Built-in, no dependencies. Works out of the box. | Limited: full-screen or window capture only (no select-area, no scrolling). No keyboard/mouse simulation. No window detection/listing. | **Fallback option.** Used if nut.js build fails. |
| **Native Swift addon** | Maximum control. Direct access to `CGWindowListCreateImage`, `IOKit`, `AXUIElement`. | Requires writing Swift/Obj-C N-API addon. More development effort. macOS-only. | **Used alongside nut.js** for Accessibility API features (text reading, app detection) that nut.js doesn't cover. |

### Why no Apple Developer Program ($99/yr)

- **Personal use only** — no App Store distribution, no notarization required.
- **Ad-hoc signing** (`codesign --force --deep --sign -`) is sufficient for running on your own machine.
- **Gatekeeper bypass** (`xattr -cr /path/to/app`) is a one-time manual step.
- The **Finder Sync Extension** (.appex) is the riskiest component — it *may* require a proper signing identity. If ad-hoc signing fails for the extension, the fallback is drag-and-drop file ingestion (Phase 4) which doesn't need a Finder extension at all.
- **Accessibility and Screen Recording permissions** are granted per-app in System Settings regardless of signing status.

### Why Express on localhost:19876 (Finder extension IPC)

- The Finder Sync Extension runs in a separate process (sandboxed by macOS).
- It cannot communicate with Electron via Electron IPC (different process, different sandbox).
- **XPC Services** would be the Apple-native approach, but require Xcode, Swift, and proper entitlements.
- A **local HTTP server** (Express on localhost:19876) is the simplest cross-process communication:
  - Finder extension POSTs `{ action, paths }` to the Electron Express server.
  - Electron receives the request and triggers the appropriate UI flow.
  - No sandbox issues — localhost HTTP is allowed from Finder extensions.
  - Port 19876 chosen to avoid conflicts with common development ports.

---

## Appendix C: Design Decisions Log

This appendix records every significant design decision made during the Q&A sessions (2026-03-01 through 2026-03-03), the alternatives considered, and the rationale for each choice.

### Decision 1: Three surfaces → Four surfaces

- **Question**: How many distinct UI surfaces should the companion have?
- **Original design**: Two surfaces (compact bar + full panel), evolved to three (PopBar + Results Dropdown + Sidebar).
- **Final decision**: **Four surfaces** — PopBar, Results Dropdown, Sidebar, Dictation Pop.
- **Rationale**: Dictation has a fundamentally different UX (recording indicator, reformat, history) that doesn't fit naturally into the PopBar. A separate small widget at bottom-left keeps it out of the way and gives it appropriate persistence (survives app switching like Sidebar, unlike PopBar).

### Decision 2: PopBar near cursor (not center screen)

- **Question**: Should the quick-action bar appear at the center of the screen (like Spotlight/Raycast) or near the cursor (like Enconvo's PopBar)?
- **Alternatives**: Center screen (Spotlight-style) vs. near cursor (Enconvo-style).
- **Decision**: **Near cursor / text selection.**
- **Rationale**: The PopBar is context-specific — it operates on what the user is currently looking at. Placing it near the cursor/selection reduces eye travel and reinforces the connection between the action and the content. Enconvo's PopBar validated this pattern.

### Decision 3: No `#context` typed modifiers

- **Question**: Should the input support Enconvo-style `#screen`, `#clipboard`, `#browser` modifiers?
- **Alternatives**: Typed modifiers (Enconvo-style) vs. button-based context attachment.
- **Decision**: **Button-based only.** A Context button with a 4-level dropdown.
- **Rationale**: Typed modifiers require memorization and are invisible to new users. A visual button with a dropdown is more discoverable. Since this is a personal tool (single user), simplicity wins over power-user shortcuts. The user explicitly said "No typed modifiers."

### Decision 4: In-place text replacement (both Replace and Copy)

- **Question**: Should AI results be pasteable back into the original app?
- **Alternatives**: Copy only vs. Replace only vs. both.
- **Decision**: **Both Replace and Copy buttons.** Replace simulates Cmd+V. Copy just copies to clipboard.
- **Rationale**: Replace is high-value for text editing workflows (explain → replace, summarize → replace). Copy is the safe fallback for apps where paste simulation might fail. Showing both gives maximum flexibility.

### Decision 5: Minimal writing tools + prompt selector

- **Question**: Should PopBar have dedicated writing tool buttons like Enconvo (Improve, Fix Spelling, Translate, etc.)?
- **Alternatives**: Full writing tools (8+ buttons) vs. a few key ones vs. minimal + prompt selector.
- **Decision**: **Keep only Explain and Summarize as core actions.** Other text transforms are accessible via the **prompt selector** in configurable slots.
- **Rationale**: The existing prompt store already contains reusable prompts for any text transformation. Adding fixed writing tool buttons duplicates this. The prompt selector (pinned/favorited prompts) provides the same capability with more flexibility and no action bar clutter.

### Decision 6: Voice input as a separate surface (Dictation Pop)

- **Question**: Should voice input be integrated into the PopBar, or be a separate widget?
- **Decision**: **Separate Dictation Pop** at bottom-left, with its own hotkey (`Cmd+J`), push-to-talk (`hold Fn`), draggable, position memory.
- **Rationale**: Dictation has a different lifecycle than PopBar actions — it involves recording, waiting for transcription, reformatting, and history. It also needs to be app-agnostic (persist across Cmd+Tab) unlike PopBar. A separate widget gives it the right behavior without overloading PopBar's UX. The Sidebar already has voice input capability in the web UI; the Dictation Pop is for quick system-wide dictation.

### Decision 7: Smart paste for dictation output

- **Question**: Where should transcribed text go?
- **Alternatives**: Always paste into current app vs. always clipboard vs. show in Dictation Pop for user to decide vs. smart detection.
- **Decision**: **Smart paste** — if a text field is focused, paste there; otherwise clipboard.
- **Rationale**: The most natural behavior. If you're dictating while writing an email, you want the text to appear in the email. If you're dictating while looking at a PDF (no text field), you want it on the clipboard. Smart detection via Accessibility API (`AXFocusedUIElement`) enables this.

### Decision 8: Dictation reformat via dropdown (not buttons)

- **Question**: How should reformatting work in the Dictation Pop?
- **Alternatives**: Buttons (As Bullets, As Markdown, etc.) vs. dropdown menu vs. two-step (raw then optional reformat).
- **Decision**: **Dropdown menu** with default "Raw". Options: Raw, As Bullets, As Markdown Paragraphs, Custom Prompt...
- **Rationale**: A dropdown is compact (Dictation Pop is small ~350x120px), persists the selection across sessions (no need to re-select every time), and the "Custom Prompt..." option opens the full prompt selector for advanced reformatting. Buttons would take too much space.

### Decision 9: Dictation history accessible in both Dictation Pop and tray menu

- **Question**: Where should the last 10 dictations be accessible?
- **Decision**: **Both** — expandable list in Dictation Pop + "Recent Dictations" submenu in tray icon.
- **Rationale**: Dictation Pop is the natural place to see history while dictating. Tray menu provides access even when Dictation Pop is hidden.

### Decision 10: Hotkey changes (Sidebar = Cmd+Shift+J, Dictation = Cmd+J)

- **Question**: What hotkeys for the new surfaces?
- **Original BRD**: Sidebar was `Cmd+Shift+\`.
- **Decision**: Sidebar → `Cmd+Shift+J`. Dictation toggle → `Cmd+J`. Dictation push-to-talk → hold `Fn`.
- **Rationale**: User preference. `Cmd+J` is easier to hit than `Cmd+Shift+\`. The `J` key is home row. `Cmd+Shift+J` for Sidebar and `Cmd+J` for Dictation creates a natural hierarchy (Shift = bigger surface).

### Decision 11: Workflows — pre-built templates + nested step editor (not visual node editor)

- **Question**: How should users define workflows?
- **Alternatives**: Visual node editor (like Shortcuts/n8n) vs. config files (YAML) vs. pre-built + simple list UI vs. pre-built only.
- **Original decision**: Pre-built + simple list UI only.
- **Updated decision**: **Pre-built templates (3: Deep Research, Document Writer, Q&A Research) + clone-and-customize + nested/indented step editor.** The step editor (Editor View in workflow-panel.js) shows a tree with indentation for loops and parallel groups, inline edit forms per step, drag-drop reorder, and add/indent/outdent controls. This is NOT a visual node/graph editor — it's a structured list/tree editor, keeping complexity manageable.
- **Rationale**: A full visual node editor (n8n/Shortcuts-style) is still out of scope, but a structured tree editor for steps is essential for creating and editing workflows with nested loops and parallel groups. JSON files alone are too error-prone for complex definitions. The tree editor is a good middle ground. See `workflow_engine_framework.plan.md` FR-17 Editor View.

### Decision 12: Workflows — self-contained engine module (not desktop-only or tightly coupled)

- **Question**: Where does the workflow engine live?
- **Alternatives**: Desktop-only (Electron orchestrates) vs. tightly coupled backend API vs. self-contained module with adapters.
- **Decision**: **Self-contained `workflow_engine/` module** at project root. Runs standalone (own Flask server on port 5050 + CLI) or embedded in the main Flask app via blueprint under `/workflows`. Uses adapter pattern with 5 abstract interfaces (LLMAdapter, ToolAdapter, StorageAdapter, EventBus, UserInteractionAdapter) — zero main app imports in the engine core.
- **Rationale**: Workflows involve long-running tasks that survive independently of the desktop app. The adapter pattern makes the engine portable and testable in isolation. Standalone mode enables CLI execution (`python -m workflow_engine run <workflow>`) and integration with external systems. Embedded mode gives full access to the 48-tool TOOL_REGISTRY and existing auth. See `workflow_engine_framework.plan.md` design_decisions for full rationale.

### Decision 13: Workflow scratch pad — both JSON state + markdown pad (dual architecture)

- **Question**: What internal state format for workflows?
- **Alternatives**: JSON state only vs. markdown pad only vs. both.
- **Decision**: **Both.** JSON state for structured inter-step data, markdown scratch pad for document accumulation. Thread-safe SharedState class with RLock.
- **Rationale**: Research workflows need structured state (search results, relevance scores, gap lists, loop counters, debug info) AND a living document (the research report being built). JSON handles the former, markdown handles the latter. Template rendering uses `{{state.field}}` and `{{scratchpad}}` syntax. Accumulator support (append/merge/replace modes) for keys that grow across loop iterations. Size limits enforced: 50KB JSON, 100KB scratchpad.

### Decision 14: Workflow user interaction — decoupled panel module in Sidebar

- **Question**: Where do workflow interactions appear?
- **Alternatives**: Inline in existing surfaces vs. dedicated panel in Sidebar vs. floating progress widget.
- **Decision**: **Decoupled workflow panel module** (`workflow-panel.js` + `workflow-panel.css`) loaded in the Sidebar's Workflows tab, the standalone `/workflows/ui` route, and a pop-out Electron window. `.wfp-*` CSS prefix, zero main app JS dependencies beyond jQuery + Bootstrap 4.6.
- **Rationale**: Workflows need their own UI space with 5 views (List, Launch, Run, Debug, Editor). Making the panel fully decoupled means it works identically in the web UI drawer, the desktop Sidebar tab, the standalone page, and a pop-out window — all from the same codebase. SSE EventSource for real-time updates. Polling fallback on disconnect. See `workflow_engine_framework.plan.md` FR-17.

### Decision 15: App context — manual button (not auto-attach)

- **Question**: Should app context be auto-attached to every query?
- **Alternatives**: Always auto-attach (hidden) vs. auto-attach with visible chip vs. manual button.
- **Decision**: **Manual Context button** with a dropdown to select context level. Visible context chip in input.
- **Rationale**: Auto-attach adds cost and latency to every query (screenshot capture, OCR, Accessibility API calls). Most quick questions don't need app context. Manual control lets the user decide when context is worth the overhead. The context chip makes the attached context visible and removable.

### Decision 16: App context — full depth (including scrolling OCR)

- **Question**: How deep should context detection go?
- **Alternatives**: Basic (app name + title) vs. medium (+ text) vs. full (+ URL, code file, screenshot, scrolling OCR).
- **Decision**: **Full context** with 4 levels in the dropdown: Basic, +Selected Text, +Screenshot, +Full Scrolling OCR.
- **Rationale**: When the user explicitly requests context, they want the richest possible information. Full context includes per-app enrichment (browser URL via AppleScript, VS Code file path, Finder selection). The 4-level dropdown lets the user choose the depth (and cost) appropriate to their question.

### Decision 17: Folder sync — desktop-side watcher, configurable per folder

- **Question**: Where should folder watching happen?
- **Alternatives**: Desktop-side (fsevents) vs. backend-side vs. hybrid vs. manual button.
- **Decision**: **Desktop-side watcher** using chokidar. Frequency configurable per folder (real-time, 5 min, 15 min, hourly, manual).
- **Rationale**: The desktop app has direct filesystem access. The backend runs on a remote server and can't watch local folders. chokidar with macOS fsevents is efficient and well-tested. Per-folder frequency lets the user balance between responsiveness and resource usage.

### Decision 18: PopBar — semi-customizable (core + configurable slots)

- **Question**: Should PopBar actions be fixed or customizable?
- **Alternatives**: Fully customizable vs. fixed with good defaults vs. semi-customizable.
- **Decision**: **Semi-customizable.** 8 core actions always visible (Quick Ask, Save to Memory, Explain, Summarize, Screenshot, Search Memory, Context, Generate Image) + 2-3 configurable slots for prompts/workflows.
- **Rationale**: Core actions are essential and should always be discoverable. Configurable slots give power users the ability to add their most-used prompts or workflows without cluttering the bar with rarely-used actions.

### Decision 19: Explain and Summarize are separate actions

- **Question**: Should Explain and Summarize be one combined action or two separate buttons?
- **Original BRD**: Combined as "Explain / Summarize".
- **Decision**: **Two separate core actions.**
- **Rationale**: They serve different purposes. Explain is for understanding (what does this mean?). Summarize is for compression (give me the key points). Having them as separate one-click actions saves a step versus having a combined action with a sub-menu.

### Decision 20: Add File to Docs — moved from PopBar to Finder right-click only

- **Question**: Should "Add File to Docs" be a PopBar action?
- **Original BRD**: It was PopBar action #7.
- **Decision**: **Removed from PopBar.** Only accessible via Finder right-click and drag-and-drop.
- **Rationale**: Adding files is a Finder-context action, not a cursor-context action. It makes more sense as a right-click in Finder or a drag-and-drop onto the overlay. PopBar space is better used for text-context actions (the configurable slots).

### Decision 21: Right-click menu scope (text in apps)

- **Question**: How many items in the macOS Services right-click menu for selected text?
- **Proposed full list**: Save to Memory, Ask About This, Explain, Summarize, Translate, Send to Chat, Run Prompt, Run Workflow.
- **Decision**: **6 items** — excluded Translate and Run Workflow.
- **Rationale**: Translate is not a standalone action in our system (user can type "translate" in Quick Ask). Run Workflow from a right-click menu is too complex (requires parameter input) and was excluded to keep the menu clean.

### Decision 22: Right-click menu scope (files in Finder)

- **Question**: How many items in the Finder right-click menu?
- **Proposed full list**: Add to Global Docs, Extract Text to PKB, Ask AI About This File, Summarize Document, Run Workflow.
- **Decision**: **4 items** — excluded Run Workflow.
- **Rationale**: Same as above — Run Workflow requires parameter input and is better triggered from the Sidebar Workflows tab or PopBar configurable slot.

### Decision 23: Prompt access in PopBar — dedicated button (not slash commands)

- **Question**: How should pinned prompts be accessed in PopBar?
- **Alternatives**: Dedicated button opening mini-list vs. slash commands in input (`/prompt-name`) vs. both.
- **Decision**: **Dedicated Prompt button** that opens a mini-list of pinned/favorited prompts.
- **Rationale**: A dedicated button is more discoverable than slash commands. The prompt list is visual and doesn't require remembering prompt names. The mini-list only shows pinned/favorited prompts, keeping it focused. Slash commands could be added later as a power-user feature.

### Decision 24: Sidebar tab system (Chat + Workflows)

- **Question**: Should workflows appear inline in chat, in a separate tab, or in a separate window?
- **Alternatives**: Inline in chat vs. tabs (Chat + Workflows) vs. separate floating window.
- **Decision**: **Tab system** — Chat tab and Workflows tab in the Sidebar.
- **Rationale**: Tabs keep everything in one panel without cluttering the chat. A separate window adds another floating element to manage. Inline in chat would make long workflow status updates dominate the conversation history.

### Decision 25: Scrolling screenshot — both browser extension + native auto-scroll

- **Question**: How to implement full-page scrolling screenshots?
- **Alternatives**: Browser-only (via extension) vs. auto-scroll+stitch for native apps vs. both.
- **Decision**: **Both approaches.** Browser content via Chrome extension's full-page capture API. Native apps via auto-scroll + stitch (Accessibility API scroll events).
- **Rationale**: Browser scrolling via extension is reliable and already implemented. Native app scrolling is best-effort (may not work for all apps) but valuable for apps like Slack, Outlook, and long documents in Preview. Having both maximizes coverage.

### Decision 26: Tool calling — PopBar has configurable whitelist (**UPDATED in v5 — see Decision 31**)

- **Original decision (v4)**: PopBar uses lightweight, single-turn LLM calls without tool calling.
- **Updated decision (v5)**: **PopBar has a configurable tool whitelist** with max 1-2 iterations. Default: PKB search + add claim. `ask_clarification` always disabled. Full 48-tool agentic loop remains Sidebar-only.
- **See Decision 31** for full rationale.

### Decision 27: Image generation — both PopBar action and Sidebar

- **Question**: Should image generation be available from the PopBar, or only from the Sidebar?
- **Alternatives**: Sidebar only (via `/image` command and modal) vs. PopBar action + Sidebar.
- **Decision**: **Both.** PopBar gets a Generate Image action (#8) for quick generation. Sidebar has the `/image` slash command and the full standalone modal (Settings > Image) for advanced features (model selection, granular context control, image editing via drag-drop).
- **Rationale**: Quick image generation (type a prompt, see result) is a natural PopBar action — same interaction pattern as Quick Ask. The Sidebar/modal handle advanced use cases: editing existing images, choosing specific models, controlling context. PopBar uses `POST /api/generate-image` directly with default settings.

### Decision 28: OCR comment extraction — opt-in toggle in Screenshot dropdown

- **Question**: How should the new OCR comment extraction feature (dual-LLM parallel extraction of document text + annotations) be exposed in the desktop companion?
- **Alternatives**: Always extract comments when OCR is used vs. separate toggle vs. only in Sidebar.
- **Decision**: **Opt-in "Extract Comments" checkbox** in the Screenshot dropdown, visible only when a +OCR mode is selected. Off by default.
- **Rationale**: Comment extraction doubles the OCR cost (two parallel LLM calls per screenshot instead of one). Most OCR use cases only need the document text. The checkbox gives users control. The checkbox state persists across sessions (like the dictation reformat dropdown).

### Decision 29: Sidebar is the full web UI (no custom chat implementation)

- **Question**: Should the Sidebar load a slimmed-down local version of the chat UI, or the full web UI?
- **Alternatives**: Full web UI (remote `interface.html`) vs. stripped-down local version vs. custom Electron chat UI.
- **Decision**: **Full web UI loaded as-is in an Electron `BrowserView`.** No custom chat UI code. No stripping of features. The web UI's responsive layout handles different widths automatically.
- **Rationale**: Building a custom chat UI duplicates massive effort (streaming, markdown, math, tools, artefacts, PKB, docs, settings, workspace tree — hundreds of JS files). Loading the web UI directly gives 100% feature parity for free. The Sidebar is resizable, so at wider widths the full desktop layout with workspace sidebar appears. At narrow widths (~400px), mobile responsive mode hides the workspace sidebar. Aggressive caching in Electron reduces network load.

### Decision 30: PopBar queries are ephemeral (no persistent conversation)

- **Question**: Should PopBar queries accumulate in a conversation?
- **Alternatives**: Persistent "PopBar conversation" vs. ephemeral per-query vs. per-session conversation.
- **Decision**: **Ephemeral per-query.** Each PopBar query is a standalone request. No conversation history.
- **Rationale**: PopBar is for fast, disposable queries. Accumulating history adds complexity and makes the PopBar feel like a chat client. The Sidebar already provides full conversation management. If the user wants to continue a PopBar query, they use "Expand" to escalate to the Sidebar.

### Decision 31: PopBar has a configurable tool whitelist (not no-tools)

- **Question**: Should PopBar's Quick Ask support any tool calling?
- **Original decision (v4, Decision 26)**: No tool calling in PopBar. Single-turn LLM only.
- **Updated decision**: **Configurable tool whitelist** with max 1-2 iterations. Default tools: PKB search, PKB add claim. User configures in Settings > PopBar > Allowed Tools.
- **Rationale**: PKB search and memory operations are high-value in the PopBar context (user wants to quickly search or save memories without escalating to Sidebar). The configurable whitelist keeps the default fast while allowing power users to enable additional tools (e.g., web search). Max 1-2 iterations keeps response times at 2-5 seconds. `ask_clarification` is always disabled in PopBar (modal UX doesn't fit).

### Decision 32: Expand escalation gives user a choice (new vs active conversation)

- **Question**: When expanding from PopBar to Sidebar, where does the exchange go?
- **Alternatives**: Always new conversation vs. always inject into active vs. user chooses.
- **Decision**: **User chooses** via a small dropdown: "New Conversation" or "Add to [current conversation name]".
- **Rationale**: Sometimes the PopBar query is a new topic (→ new conversation). Sometimes it's related to what the user is working on in the Sidebar (→ inject into active). Giving the choice takes one click and avoids polluting conversations with unrelated queries.

### Decision 33: Reuse web UI modals for Finder/Services actions (no custom forms)

- **Question**: Should the desktop companion build custom forms for "Add to Global Docs" and "Extract Text to PKB"?
- **Alternatives**: Custom PopBar-based forms (as specced in BRD v4) vs. reuse web UI modals.
- **Decision**: **Reuse the web UI's existing modals.** "Add to Global Docs" opens the Global Docs modal. "Extract Text to PKB" opens the PKB Add Memory modal. Both via `executeJavaScript()` injection into the Sidebar's BrowserView.
- **Rationale**: Building custom forms duplicates UI work and creates maintenance burden. The web UI's modals are already feature-complete (folder picker, tag autocomplete, auto-fill, validation). Reusing them ensures the desktop experience matches the web experience. The only exception is PopBar's "Quick Save" which is a lightweight toast-only operation.

### Decision 34: Authentication via session cookie sharing

- **Question**: How does the desktop app authenticate to the Flask backend?
- **Alternatives**: Session cookie sharing vs. API key / JWT vs. hardcoded local auth.
- **Decision**: **Session cookie sharing.** User logs in via the Sidebar's `BrowserView`. Electron extracts the session cookie from its cookie store and reuses it for all direct API calls from the main process (PopBar, Finder, folder sync).
- **Rationale**: No backend changes needed. The existing Flask session-based auth works as-is. Cookie extraction is straightforward via Electron's `session.defaultSession.cookies.get()` API. If the session expires, the web UI in the Sidebar shows the login page, and re-login refreshes the cookie for all surfaces.

### Decision 35: Single file for Finder actions (no multi-select)

- **Question**: Should Finder right-click support multiple selected files?
- **Decision**: **Single file at a time.** Multi-file Finder actions are not supported. User right-clicks one file.
- **Rationale**: Multi-file handling adds complexity (batch display names, batch progress, partial failures). The Global Docs modal is designed for single-file upload. For batch ingestion, the user can use folder sync or the web UI's Global Docs modal directly.

### Decision 36: Sidebar OCR — add OCR toggle to Sidebar screenshot too

- **Question**: Should the Sidebar's screenshot capture button offer +OCR modes, or only plain capture?
- **Original decision (BRD v4)**: Sidebar only offers plain capture (image attachment).
- **Updated decision**: **Add OCR toggle to Sidebar too.** The Sidebar's screenshot button offers all modes including +OCR and "Extract Comments".
- **Rationale**: OCR is useful in the Sidebar context too — extract text from a screenshot and paste it into the chat input as text. This avoids the roundtrip of using PopBar for OCR and then expanding to Sidebar. The screenshot button is injected by the desktop companion into the web UI via `executeJavaScript`.

### Decision 37: Dual-tab Sidebar (Chat + OpenCode + Workflows)

- **Question**: Should the Sidebar contain just the web UI, or also integrate a coding agent?
- **Alternatives**: Single tab (web UI only) vs. dual tab (web UI + OpenCode) vs. three tabs (+ Workflows).
- **Decision**: **Three tabs** — Tab 1: Chat (full web UI), Tab 2: OpenCode Web (agentic coding agent), Tab 3: Workflows.
- **Rationale**: The web UI excels at research, knowledge management, and conversational AI (PKB @-references, workspace hierarchy, document #-references, math rendering, multi-model ensemble, TTS). OpenCode excels at coding tasks (file editing, bash, grep, LSP, multi-step planning, undo/redo). Rather than replacing one with the other, having both tabs lets the user pick the right tool. The Chat tab preserves all 35K+ lines of product differentiation. The OpenCode tab adds agentic coding with MCP access to server capabilities. Workflows remain a separate tab for long-running executions.

### Decision 38: OpenCode spawned locally, MCP servers remote

- **Question**: Where does the OpenCode instance run?
- **Alternatives**: Remote (on assist-chat.site) vs. local (spawned by Electron on user's Mac) vs. hybrid.
- **Decision**: **Local.** Electron spawns `opencode web` as a child process on the user's Mac, with `cwd` set to the user's working directory.
- **Rationale**: OpenCode needs to operate on local files (the user's codebase on their Mac). The filesystem MCP is local. The remote MCP servers (PKB, docs, search) are accessed over HTTPS. This gives the best of both worlds: local file access + remote knowledge access.

### Decision 39: Remote-only architecture (no local server/database)

- **Question**: Should the Flask server and databases run locally in Electron alongside the remote server?
- **Alternatives**: Local server with sshfs/rsync to share remote filesystem vs. remote-only with HTTPS API calls.
- **Decision**: **Remote-only.** The desktop companion is a client. All data (conversations, PKB, documents) lives on the remote server.
- **Rationale**: SQLite does not work reliably over network filesystems (sshfs, NFS). File-level locking (`fcntl`/`flock`) fails when two processes on different machines both write to `pkb.sqlite` or conversation JSON files — resulting in database corruption, partial reads, and lost writes. rsync is periodic batch copy, not a live mount — guaranteed divergence. sshfs adds 50-200ms latency per file operation (10-20 ops per `send_message` = 1-4s pure I/O wait). macOS is bad at recovering from stale FUSE mounts. The remote server is the single source of truth; the desktop companion accesses it via HTTPS (50-150ms per MCP call — fast enough).

### Decision 40: Path-based nginx routing for MCP servers (not subdomains)

- **Question**: How should MCP servers be exposed for remote access?
- **Alternatives**: Subdomain per MCP (mcp-search.assist-chat.site, etc.) vs. path-based (assist-chat.site/mcp/search/) vs. direct port access.
- **Decision**: **Path-based routing** under the existing domain. `https://assist-chat.site/mcp/search/` → `localhost:8100`, `/mcp/pkb/` → `localhost:8101`, etc.
- **Rationale**: Uses the existing SSL certificate (no new certs, no new DNS records). One `nginx reload` adds all routes. The trailing slash in `proxy_pass` strips the location prefix, so `/mcp/search/mcp` → `localhost:8100/mcp` (what the MCP server expects). MCP servers bind to `127.0.0.1` only — not directly accessible from the internet. JWT Bearer token is encrypted in transit via TLS.

### Decision 41: Local filesystem MCP for OpenCode only (not Chat tab)

- **Question**: Should the Chat tab's tool-calling framework also use the local filesystem MCP?
- **Alternatives**: Both tabs use local filesystem MCP vs. OpenCode only vs. Chat uses server-side file browser.
- **Decision**: **OpenCode only.** The Chat tab's tool-calling runs server-side (`Conversation.py`), operating on server files via existing file browser endpoints. The local filesystem MCP is consumed exclusively by OpenCode Tab 2.
- **Rationale**: The Chat tab's tool-calling framework runs in `Conversation.py` on the remote server. Bridging it to a local MCP server in Electron would require a complex proxy (Electron intercepts tool calls from the streaming response, executes locally, returns results). This is unnecessary complexity since the Chat tab already has `code_runner` (Python execution) and file browser endpoints for server-side file operations. OpenCode natively consumes MCP tools, so the local filesystem MCP integrates seamlessly.

### Decision 42: Working directory selector with recent + pinned + picker

- **Question**: How does the user choose the OpenCode working directory?
- **Decision**: **Dropdown of recent directories + pinned favorites + OS file picker button.** Last 10 dirs remembered, user can pin/star frequently used dirs. Pinned dirs persist across app restarts.
- **Rationale**: Most of the time the user works in the same 2-3 directories. A recent list with pins avoids re-navigating each time. The OS file picker is the fallback for new directories.

### Decision 43: Session warning on directory change

- **Question**: What happens to the OpenCode session when the user changes working directory?
- **Alternatives**: Kill and restart silently vs. warn and confirm vs. support multiple instances.
- **Decision**: **Warn the user** that changing directory will end the current session, with option to cancel. On confirmation, kill the `opencode web` process and restart with new `cwd`.
- **Rationale**: OpenCode sessions accumulate context (conversation history, tool results, compaction state). Silently killing a session could lose unsaved work. The warning gives the user a chance to finish or save first. Multiple simultaneous instances add complexity (multiple ports, multiple filesystem MCPs) deferred to a later version.

### Decision 44: Chrome extension stays single-tab (no OpenCode)

- **Question**: Should the Chrome extension sidepanel also get the dual-tab treatment?
- **Decision**: **No.** Chrome extension keeps current behavior — single iframe loading the web UI. OpenCode is desktop-only (Electron).
- **Rationale**: The Chrome extension already provides browser-specific capabilities (page extraction with 16 site-specific extractors, full-page scrolling screenshots, custom scripts, multi-tab capture). These serve the browser context well. OpenCode is a coding agent that operates on local files — not useful inside a browser extension where there's no local filesystem access. Adding OpenCode to the extension would require spawning or connecting to an OpenCode server, which adds complexity with limited benefit.

### Decision 45: MCP auth via environment variable injection

- **Question**: How does OpenCode Tab 2 authenticate to the remote MCP servers?
- **Decision**: **Electron sets `MCP_JWT_TOKEN` as an environment variable** before spawning the `opencode web` child process. OpenCode's config uses `{env:MCP_JWT_TOKEN}` template syntax to inject the token into `Authorization: Bearer` headers.
- **Rationale**: Simplest approach. No manual config needed per working directory. The JWT token is a long-lived bearer token (already generated via `python -m mcp_server.auth`). Electron stores it in its own config and injects it into the child process environment. The `opencode.json` in each working directory (or global config) references `{env:MCP_JWT_TOKEN}` which OpenCode resolves at runtime.

---

*End of Product Requirements Document*
