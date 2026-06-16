# Writing System: Implementation Plan (Proposal B)

## Decision: Isolated SPA + Existing Backend

The writing studio will be a new standalone page served at `/write/<artefact_id>` (or `/write/new`) with its own frontend bundle (Svelte + ProseMirror). It communicates with existing Flask endpoints and new writing-specific ones. Fully isolated from the jQuery/Bootstrap main app.

## Organizational Model: Where Do Writing Projects Live?

### Key Question

Each writing artefact currently belongs to a conversation. Should the writing studio:
1. Continue to be conversation-scoped?
2. Be its own top-level entity (like conversations)?
3. Be workspace-scoped but conversation-linked?

### Recommendation: Conversation-scoped, but with cross-conversation source access

**Why conversation-scoped:**
- A writing project needs context: uploaded docs/PDFs, chat history with the AI about the document's purpose, PKB claims, referenced materials. Conversations already provide this context container.
- The existing doc upload flow (`POST /upload_doc_to_conversation/<conversation_id>`) + FastDocIndex + `#doc_N` references give the writing system free source management.
- Global docs (`#gdoc_all`, `#folder:`, `#tag:`) are already accessible from any conversation — so source PDFs uploaded elsewhere are available.
- The conversation chat (AI panel in writing studio) IS the conversation — same history, same context, same PKB.
- Workspaces already organize conversations hierarchically. A "Writing Projects" workspace is natural.

**Why not top-level:**
- Would duplicate the organizational machinery (workspaces, archiving, search, metadata).
- Would need its own document attachment system (already solved by conversations).
- Would isolate the writing project from the chat history that informed it.

**What we add:**
- A conversation can be marked as a "writing project" (metadata flag) — shows differently in sidebar (document icon instead of chat icon).
- Opening a writing project conversation routes to `/write/<artefact_id>` instead of the chat view.
- The AI panel in the writing studio IS the conversation's chat (same endpoint, same history).
- Source docs = conversation docs (already uploaded/indexed). Plus global docs accessible via `#gdoc_all`.

### How This Connects to Multi-Conversation Tabs

From the `feat/multi-conversation-tabs` branch:
- `TabManager` supports max 5 tabs, each holding a `{conversationId, title}`
- Tabs can be different "types" — a writing project tab opens the writing studio route instead of chat view
- Tab state already persists to localStorage per user
- Ctrl+click or "Open in New Tab" from sidebar → new tab. Works identically for writing projects.

**Integration plan:**
- `TabManager.tabs` entries gain an optional `type: "write"` field
- When `type === "write"`, focusing that tab loads `/write/<artefact_id>` in an iframe or navigates the pane
- Since the writing studio is a full SPA page, the cleanest approach is: clicking a writing-project conversation in sidebar opens it in a new browser tab (or the SPA replaces the chat pane if within multi-tab system)

### Data Flow: Source Documents → Writing

```
User has source PDFs/docs:
├── Option A: Upload to the writing project conversation directly
│   → Available as #doc_1, #doc_2 in chat and in writing studio source panel
│
├── Option B: Already uploaded in another conversation → Promote to Global
│   → Available as #gdoc_all in any conversation including writing project
│
└── Option C: Reference existing global docs by tag/folder
    → #tag:research or #folder:Q3_docs available in writing project
    
Writing studio Source Panel:
├── Shows conversation docs (via GET /get_docs_list/<conversation_id>)
├── Shows global docs (via GET /global_docs/list)
├── Can upload new docs (via POST /upload_doc_to_conversation/<conversation_id>)
└── Can search across all docs (via existing doc search endpoints)
```

### Writing Project Lifecycle

```
1. User creates writing project:
   - From sidebar: right-click workspace → "New Writing Project"
   - From chat: /write command → creates artefact + marks conversation as writing project
   - From artefact: "Open in Writing Studio" → marks conversation as writing project

2. Organization:
   - Lives in workspace hierarchy (same as conversations)
   - Sidebar shows with document icon + distinct styling
   - Appears in recent section, pinned section, time view (same as conversations)
   - Searchable via cross-conversation search

3. Opening:
   - Click in sidebar → opens /write/<artefact_id> (full page or new tab)
   - Tab bar shows it as a writing tab (document icon)

4. Context available in writing studio:
   - All conversation docs (uploaded PDFs, URLs)
   - All global docs (promoted or uploaded to global library)
   - PKB claims (conversation-scoped + global)
   - Chat history (prior discussions about this document)
   - Other artefacts in same conversation

5. Closing/archiving:
   - Same as conversations: archive, delete, move workspace
```

## Technical Architecture

### Frontend (New, Isolated)

```
interface/writing-studio/
├── index.html          ← served at /write/<artefact_id>
├── src/
│   ├── main.ts         ← Svelte app entry
│   ├── App.svelte      ← root component (three-panel layout)
│   ├── stores/
│   │   ├── document.ts     ← artefact content, writing_config, versions
│   │   ├── constraints.ts  ← live constraint state
│   │   ├── session.ts      ← standing directives, agent state, pass count
│   │   └── sources.ts      ← conversation docs + global docs
│   ├── components/
│   │   ├── editor/
│   │   │   ├── Editor.svelte        ← ProseMirror wrapper
│   │   │   ├── annotations.ts       ← decoration plugin for annotations
│   │   │   ├── frozen-zones.ts      ← read-only ranges
│   │   │   ├── inline-edit.svelte   ← Cmd+K overlay
│   │   │   └── diff-overlay.svelte  ← proposed changes inline
│   │   ├── structure/
│   │   │   ├── StructurePanel.svelte
│   │   │   ├── Outline.svelte       ← draggable section tree
│   │   │   ├── Sources.svelte       ← source list + unsourced claims
│   │   │   ├── Versions.svelte      ← version timeline
│   │   │   └── Constraints.svelte   ← constraint dashboard
│   │   ├── ai-panel/
│   │   │   ├── AIPanel.svelte       ← chat + quick actions
│   │   │   ├── BriefTab.svelte      ← persistent brief display
│   │   │   ├── ConfigTab.svelte     ← writing config editor
│   │   │   └── ChatMessage.svelte   ← message rendering
│   │   └── shared/
│   │       ├── StatusBar.svelte     ← bottom constraint summary
│   │       ├── DiffView.svelte      ← accept/reject proposed changes
│   │       └── PanelResizer.svelte  ← draggable panel borders
│   ├── api/
│   │   ├── artefacts.ts     ← CRUD, propose_edits, apply_edits
│   │   ├── documents.ts     ← conversation docs, global docs
│   │   ├── writing.ts       ← pipeline, constraints, reader sim, directives
│   │   └── chat.ts          ← send message, stream response (for AI panel)
│   └── lib/
│       ├── prosemirror/     ← ProseMirror schema, plugins, keymaps
│       └── constraints.ts   ← client-side constraint engine (subset)
├── vite.config.ts
├── package.json
└── tsconfig.json
```

### Build & Serving

- Vite builds to `interface/writing-studio/dist/`
- Flask serves: `@app.route('/write/<artefact_id>')` → returns `dist/index.html`
- Static assets served from `dist/assets/`
- Completely isolated from main jQuery app — no shared bundles, no conflicts
- Development: `vite dev` with proxy to Flask backend (hot reload)

### Chat Tab: LLM Tools for Artefact Editing

The chat LLM (in the chat tab) edits artefacts via tool calls. Two editing paths:

#### Path 1 (Primary): `propose_artefact_edit` Tool

Reuses the existing `propose_edits` logic. Single tool call → structured ops + diff.

```
Tool: propose_artefact_edit
Parameters:
  - artefact_id: string (required)
  - instruction: string (required) — what to change
  - selection: { start_line, end_line } (optional) — scope the edit
  - include_context: bool (default true) — inject summary + recent messages

Returns to chat:
  - diff_text (unified diff)
  - proposed_ops (JSON ops array)
  - base_hash (for stale check)

UI rendering:
  - Diff card in chat message with syntax-highlighted unified diff
  - [Accept] button → calls apply_edits → change appears in writing tab immediately
  - [Reject] button → discards, optionally adds standing directive
  - [Edit instruction] → re-run with modified instruction
```

#### Path 2 (Secondary): Sandboxed Terminal on Shadow Copy

For complex multi-step edits where structured ops are insufficient. LLM gets terminal access but sandboxed to a shadow copy.

```
Tool: artefact_terminal
Parameters:
  - artefact_id: string (required)
  - command: string (required) — shell command to execute

Sandbox rules:
  - Working directory: storage/conversations/<conv_id>/artefacts/
  - Shadow file: <filename>.proposed (auto-created as copy on first command)
  - All commands execute against .proposed only (paths rewritten)
  - LLM can issue multiple sequential commands in one session
  - Session ends when LLM calls `artefact_terminal_done` tool

Validation (pre-execution, every command):
  1. Artefact filename (or .proposed variant) MUST appear in command → else REJECT
  2. No blocked commands: rm, mv, chmod, chown, curl, wget, nc, ssh, scp, rsync,
     any network/socket operation
  3. No path traversal: resolve realpath, must stay within artefacts dir
  4. No ".." in any path argument
  5. Command string cannot contain pipe to network tools or redirection outside dir

Allowed commands:
  cat, head, tail, grep, sed, awk, wc, echo, printf, sort, uniq, tr, cut,
  paste, diff, patch, tee, cp (within dir), python -c (one-liners for text processing)

Lifecycle:
  1. First command in session → auto: cp <filename> <filename>.proposed
  2. Execute commands against .proposed (rewrite <filename> → <filename>.proposed in command)
  3. LLM calls artefact_terminal_done when finished
  4. System generates: diff <filename> <filename>.proposed (unified diff)
  5. Diff card shown in chat: [Accept] / [Reject]
  6. Accept → mv .proposed to original, update artefact metadata, update writing tab
  7. Reject → rm .proposed

Tool: artefact_terminal_done
Parameters:
  - artefact_id: string (required)
  - summary: string (optional) — what was changed (for version intent)
Returns: unified diff for display
```

#### Other Chat Tools (Read-Only / Agents)

```
Tool: read_artefact
Parameters:
  - artefact_id: string (required)
  - section: string (optional) — heading text to scope read
  - lines: { start, end } (optional)
Returns: file content (or section content)

Tool: check_constraints
Parameters:
  - artefact_id: string (required)
Returns: constraint dashboard results (pass/fail per rule)

Tool: run_writing_agent
Parameters:
  - artefact_id: string (required)
  - agent: "critic" | "stylist" | "reducer" | "fact_checker" | "reader_sim"
  - scope: { start_line, end_line } (optional)
  - audience_profile: {...} (optional, for reader_sim)
Returns: agent results (suggestions list, or simulation text)
  - If agent produces edit suggestions → rendered as diff card with Accept/Reject

Tool: list_artefact_sources
Parameters:
  - artefact_id: string (required)
Returns: conversation docs + global docs + linked claims + unsourced claims
```

#### Diff Card Rendering in Chat

When any tool produces a proposed edit, it renders as:

```
┌─────────────────────────────────────────────┐
│ 📝 Proposed Edit: "Make intro more concise" │
│                                             │
│ Summary: Replaced 5 lines with 2 lines      │
│ Lines affected: 4-8                         │
│                                             │
│ [View Diff]  [Accept ✓]  [Reject ✗]       │
└─────────────────────────────────────────────┘
```

Clicking "View Diff" opens a modal with syntax-highlighted unified diff:
```
┌─────────────────────────────────────────────┐
│ Diff: One-Pager.md (lines 4-8)             │
│                                             │
│ - The current infrastructure, which was     │
│ - built in 2019, handles approximately      │
│ - 10,000 requests per second. However,      │
│ - our projections for Q4 indicate that      │
│ - we will need roughly 45,000 req/s.        │
│ + Current: 10K req/s (2019).                │
│ + Q4 projected: 45K req/s (4.5x gap).      │
│                                             │
│ [Accept ✓]  [Reject ✗]  [Edit & Retry ↻]  │
└─────────────────────────────────────────────┘
```

Accepting: change applies immediately to the artefact file. If the writing tab is open, it refreshes to show the new content.

### References in Cmd+K and Chat

Both the Cmd+K instruction input (writing tab) and chat messages support references:

```
Reference formats:
  @section:Summary         → injects that section's content as context
  @section:Problem         → heading match (case-insensitive, partial match ok)
  "the intro"             → LLM interprets naturally (resolves to first section)
  #doc_1, #doc_2          → conversation docs (uploaded PDFs/files)
  #gdoc_all               → all global docs
  #folder:research        → global docs in folder
  #tag:Q3                 → global docs with tag
  @artefact_2             → another artefact in the same conversation

Resolution:
  - @section: references resolved by scanning markdown headings (h1-h4)
  - #doc_N / #gdoc references resolved via existing doc resolution in Conversation.py
  - Content injected into the LLM prompt as additional context
  - For Cmd+K: resolved server-side by the propose_edits endpoint
  - For chat: resolved as part of the normal reference resolution in reply()
```

### Backend (New Endpoints)

```python
# endpoints/writing.py (new file)

# Writing config management
GET    /writing/<conversation_id>/<artefact_id>/config
PUT    /writing/<conversation_id>/<artefact_id>/config
  body: { brief, audience, genre, constraints, exemplars, guidelines, frozen_zones }

# Constraint engine (deterministic)
POST   /writing/<conversation_id>/<artefact_id>/check_constraints
  → { results: [{name, status, value, target, line?}] }

# Multi-agent pipeline
POST   /writing/<conversation_id>/<artefact_id>/run_pipeline
  body: { passes: ["critique", "style", "fact_check", "reduce", "reader_sim"], max_passes: 3, audience_profile?: {...} }
  → SSE stream of agent actions + proposed changes

# Individual agent invocations
POST   /writing/<conversation_id>/<artefact_id>/run_agent
  body: { agent: "critic"|"stylist"|"reducer"|"fact_checker"|"reader_sim"|"drafter", scope?: {start_line, end_line}, instruction?: "..." }
  → SSE stream

# Reader simulation
POST   /writing/<conversation_id>/<artefact_id>/simulate_reader
  body: { audience_profile: {...}, mode: "skim"|"careful"|"hostile" }
  → { takeaway, missed, questions, suggestions }

# Standing directives
GET    /writing/<conversation_id>/<artefact_id>/directives
POST   /writing/<conversation_id>/<artefact_id>/directives
  body: { text, priority?, source: "user"|"agent" }
PUT    /writing/<conversation_id>/<artefact_id>/directives/<id>
DELETE /writing/<conversation_id>/<artefact_id>/directives/<id>

# Version timeline (intent-aware)
GET    /writing/<conversation_id>/<artefact_id>/versions
  → [{ version, timestamp, intent, agent, constraint_snapshot, diff_stats }]
GET    /writing/<conversation_id>/<artefact_id>/versions/<v1>/compare/<v2>
  → { diff_text, change_explanations[] }
POST   /writing/<conversation_id>/<artefact_id>/versions/branch
  body: { from_version, label }
POST   /writing/<conversation_id>/<artefact_id>/versions/<v>/revert_section
  body: { section_heading }

# Annotations
GET    /writing/<conversation_id>/<artefact_id>/annotations
POST   /writing/<conversation_id>/<artefact_id>/annotations
  body: { line, text, author: "user"|agent_name }
PUT    /writing/<conversation_id>/<artefact_id>/annotations/<id>
  body: { resolved?: bool, text? }
DELETE /writing/<conversation_id>/<artefact_id>/annotations/<id>

# Source management (extends existing doc endpoints)
GET    /writing/<conversation_id>/<artefact_id>/sources
  → { conversation_docs: [...], global_docs: [...], linked_claims: [...], unsourced_claims: [...] }
POST   /writing/<conversation_id>/<artefact_id>/sources/link_claim
  body: { line, source_id, claim_text }
POST   /writing/<conversation_id>/<artefact_id>/sources/fact_check
  → { claims: [{ line, text, status: "sourced"|"unsourced"|"contradicted", source_id? }] }
```

### Backend (New Python Modules)

```
code_common/
├── writing_orchestrator.py    ← WritingOrchestrator class (dispatches agents, loops)
├── constraint_engine.py       ← ConstraintEngine class (pure Python, no LLM)
└── writing_agents.py          ← Critic, Reducer, Stylist, FactChecker, ReaderSim (thin wrappers)

database/
└── writing_metadata.py        ← writing_config, directives, annotations, versions (SQLite)
```

### ConstraintEngine (Pure Python, No LLM)

```python
class ConstraintEngine:
    """Deterministic constraint checking. No LLM calls."""
    
    def check(self, content: str, config: WritingConfig) -> list[ConstraintResult]:
        results = []
        results.append(self._check_word_count(content, config.constraints))
        results.append(self._check_reading_level(content, config.constraints))
        results.append(self._check_required_sections(content, config.constraints))
        results.append(self._check_forbidden_terms(content, config.constraints))
        results.append(self._check_sentence_variance(content))
        results.append(self._check_paragraph_length(content))
        results.append(self._check_passive_voice(content))
        results.append(self._check_hedge_words(content))
        results.append(self._check_frozen_zones(content, config.frozen_zones, original))
        return [r for r in results if r is not None]
```

### WritingOrchestrator

```python
class WritingOrchestrator:
    """Dispatches writing agents based on document state and user intent."""
    
    def run_pipeline(self, artefact, config, passes, max_passes=3):
        """Generator that yields SSE events as agents run."""
        for pass_num in range(1, max_passes + 1):
            for agent_name in passes:
                agent = self._get_agent(agent_name)
                yield from self._run_agent_pass(agent, artefact, config, pass_num)
            
            # Check if constraints now pass
            results = self.constraint_engine.check(artefact.content, config)
            if all(r.passed for r in results):
                yield {"event": "pipeline_complete", "pass": pass_num, "status": "constraints_satisfied"}
                return
        
        yield {"event": "pipeline_complete", "pass": max_passes, "status": "max_passes_reached"}
```

## Storage Model

### Artefact Metadata Extension

```json
{
  "id": "uuid",
  "name": "Q3 Strategy One-Pager",
  "file_type": "md",
  "is_writing_project": true,
  
  "writing_config": {
    "brief": "...",
    "audience_profiles": [...],
    "genre": "business_one_pager",
    "tone_exemplars": ["...", "..."],
    "guideline_artefact_ids": ["uuid1", "uuid2"],
    "constraints": { "max_words": 1500, ... },
    "frozen_zones": [...]
  }
}
```

### New SQLite Tables

```sql
-- Standing directives per artefact
CREATE TABLE writing_directives (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    text TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    source TEXT DEFAULT 'user',  -- 'user' or agent name
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT 1
);

-- Annotations per artefact
CREATE TABLE writing_annotations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    line INTEGER NOT NULL,
    text TEXT NOT NULL,
    author TEXT NOT NULL,  -- 'user' or agent name
    resolved BOOLEAN DEFAULT 0,
    resolved_at_version INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Version timeline with intent
CREATE TABLE writing_versions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    intent TEXT NOT NULL,  -- what triggered this version
    agent TEXT,            -- which agent made the change (null = user)
    constraint_snapshot TEXT,  -- JSON of constraint results at this point
    content_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Source-claim linking
CREATE TABLE writing_source_links (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    line INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- 'conversation_doc', 'global_doc', 'pkb_claim', 'manual'
    source_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Multi-Tab Integration

### Decision: Writing Studio as a Tab Pane (iframe)

The writing studio opens as a **tab beside the chat** in the existing `feat/multi-conversation-tabs` tab bar — not as a full-page navigation. This lets users flip between chat (for discussing the document, uploading PDFs, asking questions) and the writing studio (for editing), sharing the same conversation context.

```
┌──────────────────────────────────────────────────────────────┐
│ [💬 Chat: Q3 Strategy] [✍️ Write: One-Pager]  [+]           │  ← tab bar
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   Active pane content (chat or writing studio)               │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Why Tab Pane Over Full-Page Navigation

| Concern | Full-page nav | Tab pane (iframe) |
|---------|---------------|-------------------|
| Chat + writing side-by-side switching | ❌ Must navigate between pages | ✅ Instant tab flip |
| Upload PDF mid-writing | ❌ Leave writing studio, upload, come back | ✅ Switch to chat tab, upload, switch back |
| Chat context while editing | ❌ Lost | ✅ One click away, same conversation |
| Stream response in background | ❌ Not possible | ✅ Chat tab streams while you write |
| Isolation from jQuery app | ✅ Total | ✅ iframe = total isolation |
| Implementation complexity | Simple route | iframe in pane div (trivial) |

### How It Works (TabManager Extension)

The `feat/multi-conversation-tabs` branch already has:
- `TabManager.tabs = [{conversationId, title}]` — max 5 tabs
- `_createPane(conversationId)` creates a `<div id="chatView-{conversationId}">` inside `#chatView-container`
- Focus toggles `.active` class on panes (CSS show/hide, no re-render)
- Persistence to localStorage

Extension needed:

```js
// Tab entry gains optional type + artefactId
// tabs: [{conversationId, title, type?, artefactId?}]

TabManager.openWritingTab = function(conversationId, artefactId, title) {
    var tabId = conversationId + '-write';
    if (this.hasTab(tabId)) { this.focusTab(tabId); return; }
    if (this.tabs.length >= MAX_TABS) { showToast('Max tabs reached', 'warning'); return; }
    this.tabs.push({ conversationId: tabId, title: '✍️ ' + (title || 'Writing'), type: 'write', artefactId: artefactId, parentConvId: conversationId });
    this.focusTab(tabId);
    this.persist();
};

// In _createPane, check type:
_createPane: function(conversationId) {
    var tab = this.getTab(conversationId);
    var $container = $('#chatView-container');
    var $pane = $('<div>').attr('id', 'chatView-' + conversationId)
        .addClass('chatView-pane row flex-grow-1 overflow-hidden');
    
    if (tab && tab.type === 'write') {
        // Load Svelte writing studio in iframe (complete isolation)
        var $iframe = $('<iframe>')
            .attr('src', '/write/' + tab.artefactId + '?embedded=true&conversation_id=' + tab.parentConvId)
            .css({ width: '100%', height: '100%', border: 'none' });
        $pane.append($iframe);
    }
    
    $container.append($pane);
    return $pane;
}
```

### Writing Studio `?embedded=true` Mode

The Svelte SPA at `/write/<artefact_id>` accepts query params:
- `?embedded=true` — hides any top-level navigation chrome (no header, no back button) since the tab bar handles navigation
- `&conversation_id=<id>` — tells the AI panel which conversation to send messages to

The SPA is identical whether accessed standalone (`/write/<id>`) or embedded in a tab. The `embedded` flag only removes redundant chrome.

### User Flows with Tabs

```
Flow A: Open writing studio from chat
─────────────────────────────────────
1. User is chatting about a document
2. Opens artefact modal → clicks "Open in Writing Studio"
3. New tab appears: [✍️ Write: <name>] next to [💬 Chat: <conv>]
4. Writing studio loads in the new tab pane (iframe)
5. User can flip between tabs instantly

Flow B: Open writing project from sidebar  
───────────────────────────────────────────
1. Conversation marked is_writing_project in sidebar (document icon)
2. Normal click → opens chat tab as usual
3. "Open Writing Studio" button in chat header → opens writing tab
4. Or: Ctrl+click → opens writing tab directly

Flow C: Working across both tabs
────────────────────────────────
1. User is in writing tab, needs to upload a source PDF
2. Clicks chat tab → uploads PDF via paperclip/docs modal
3. Clicks writing tab → source panel now shows the new doc
4. (Source panel calls GET /get_docs_list/<conversation_id> which includes the just-uploaded doc)

Flow D: Chat streams while writing
───────────────────────────────────
1. User sends a research question in chat tab
2. Switches to writing tab while LLM streams response
3. TabManager.streamControllers keeps the stream alive in background
4. When user switches back to chat tab, full response is rendered
```

### Communication Between Tabs and Writing Studio

Since the writing studio is in an iframe:
- **Auth**: shares session cookie (same domain) — no extra auth needed
- **Conversation ID**: passed via URL param
- **Events from main app → iframe**: `postMessage` for tab-focus/blur notifications (optional, for pausing animations)
- **Events from iframe → main app**: `postMessage` for "open chat tab" requests (e.g., "Upload a doc" button in source panel)

Minimal postMessage API:
```js
// From main app to iframe:
{ type: 'tab-focused' }   // writing tab gained focus
{ type: 'tab-blurred' }   // writing tab lost focus

// From iframe to main app:
{ type: 'switch-to-chat' }        // user wants chat tab
{ type: 'update-title', title }   // artefact renamed
```

## Implementation Phases

### Phase 1: Skeleton + Constraint Engine (2 weeks)

- [ ] Svelte project scaffold with Vite
- [ ] Three-panel layout (static, no content yet)
- [ ] ProseMirror editor with markdown support
- [ ] Flask route `/write/<artefact_id>` serving the SPA
- [ ] `ConstraintEngine` (pure Python) with word count, reading level, required sections, forbidden terms
- [ ] `POST /writing/.../check_constraints` endpoint
- [ ] Status bar showing live constraint results
- [ ] API client connecting to existing artefact CRUD endpoints

### Phase 2: Writing Config + Agent Roles (2 weeks)

- [ ] `writing_config` schema + SQLite storage
- [ ] Config tab in AI panel (brief, audience, constraints, exemplars)
- [ ] Brief tab display
- [ ] Critic agent (thin wrapper: prompt template + CallLLm)
- [ ] Stylist agent (guideline-based, reuses DocumentEditingAgent patterns)
- [ ] Reducer agent (word count focused)
- [ ] `POST /writing/.../run_agent` endpoint with SSE streaming
- [ ] AI panel chat (reuse existing `/reply` endpoint with conversation context)

### Phase 3: Pipeline + Diff (2 weeks)

- [ ] `WritingOrchestrator` with agent dispatch loop
- [ ] `POST /writing/.../run_pipeline` endpoint
- [ ] Pipeline progress UI in AI panel
- [ ] Diff overlay in editor (accept/reject per change)
- [ ] Standing directives (CRUD endpoints + UI)
- [ ] Version timeline with intent tracking
- [ ] Versions tab in structure panel

### Phase 4: Structure + Sources (2 weeks)

- [ ] Outline extraction from headings (auto-generated from document)
- [ ] Draggable outline in structure panel
- [ ] Section word budgets
- [ ] Sources tab (shows conversation docs + global docs)
- [ ] Source ingestion (upload triggers existing doc upload endpoint)
- [ ] Fact-checker agent
- [ ] Unsourced claims highlighting in editor
- [ ] Annotation system (gutter marks + CRUD)

### Phase 5: Reader Sim + Polish (2 weeks)

- [ ] Reader Simulator agent
- [ ] Audience profile config
- [ ] Simulation output UI
- [ ] Branch-and-compare (alternative phrasings)
- [ ] Frozen zones in editor (read-only decorations)
- [ ] Inline Cmd+K edit overlay
- [ ] Keyboard shortcuts
- [ ] Mobile responsive layout (tab-based panel switching)
- [ ] Sidebar integration (writing-project icon, right-click "New Writing Project")

### Phase 6: Multi-Tab Integration (1 week)

- [ ] Extend `TabManager` with `openWritingTab()` and `type: "write"` pane creation (iframe)
- [ ] `?embedded=true` mode in Svelte SPA (hide redundant chrome)
- [ ] "Open in Writing Studio" button in chat header / artefact modal → opens writing tab
- [ ] `postMessage` bridge: `switch-to-chat`, `update-title`, `tab-focused`/`tab-blurred`
- [ ] Tab title sync with artefact name (via postMessage from iframe)
- [ ] Source panel refresh on tab focus (picks up docs uploaded in chat tab)

**Total: ~11 weeks (~3 months)**

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Frontend framework | **Svelte 5** | Minimal boilerplate, fast, compiles away. No virtual DOM overhead for an editor-heavy app. |
| Editor | **ProseMirror** | Best for rich text with custom decorations, annotations, frozen zones. Better than CodeMirror for prose (not code). |
| Bundler | **Vite** | Fast dev server, Svelte plugin mature, outputs optimized bundle. |
| Language | **TypeScript** | Type safety for complex state management (versions, annotations, constraint results). |
| Styling | **Tailwind CSS** (scoped) | Rapid UI development, no global CSS conflicts with main app. |
| State management | **Svelte stores** | Built-in, reactive, no extra library needed. |
| SSE client | Native **EventSource** | For pipeline streaming. Simple, browser-native. |
| Diff rendering | **diff-match-patch** (client) | For inline diff overlay in editor. |
| Markdown parsing | **markdown-it** | For preview mode. Fast, extensible. |
| Drag-and-drop | **SortableJS** | For outline reordering. Framework-agnostic. |

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| ProseMirror learning curve | Start with basic markdown schema (prosemirror-markdown). Add decorations/annotations incrementally. |
| Svelte + ProseMirror integration | Use `onMount`/`onDestroy` lifecycle for editor init. ProseMirror manages its own DOM — Svelte just hosts it. |
| Auth between main app and SPA | Share session cookie (same domain, same Flask server). No extra auth needed. |
| Writing config schema evolving | Store as JSON blob in SQLite. Validate on read with Pydantic. Backwards-compatible by design. |
| Pipeline timeouts for long docs | SSE with heartbeat. Client reconnects. Server-side timeout per agent (60s). |
| Large documents in ProseMirror | ProseMirror handles docs up to ~100K chars well. For longer: paginate by section. |

## Build vs. Don't Build: Evaluation Framework

### Option 0: Zero-Build (Two-Prompt Workflow)

Use existing tools (Cursor/Zed, or our own chat with `PromptWorkflowAgent`) with two well-crafted prompts. No new code.

#### Prompt 1: Style-Aware Writer

```markdown
You are writing a document for me. Follow these rules strictly:

## My Writing Style
- [2-3 paragraphs of exemplar text in target voice]
- Tone: [e.g., confident, data-driven, concise, no hedge words]
- Audience: [e.g., VP-level, 2-minute reader, expects BLUF]
- Format: [e.g., Amazon 6-pager structure: Summary → Problem → Proposal → Risks → Ask]

## Constraints
- Maximum words: 1500
- Reading level: Grade 10 or below
- Required sections: [Summary, Problem, Proposal, Risks, Ask]
- Forbidden terms: [synergy, leverage, paradigm, "it's worth noting"]
- Every quantitative claim must cite a source

## Data/Content to Include
- [Key messages, data points, arguments to make]
- [Reference material: paste or @file relevant sources]

## Frozen Sections (do not modify)
- [Any text marked <!-- FROZEN --> must be preserved exactly]

## Task
[Write/rewrite/edit instruction here]
```

#### Prompt 2: Verifier

```markdown
Review the following document against these criteria. For each violation, state the line, the issue, and a suggested fix.

## Checks
1. Word count ≤ 1500
2. Reading level ≤ Grade 10 (estimate Flesch-Kincaid)
3. All required sections present: [Summary, Problem, Proposal, Risks, Ask]
4. No forbidden terms: [synergy, leverage, paradigm, "it's worth noting"]
5. No hedge words (might, perhaps, arguably, somewhat) — flag if > 3% of words
6. No passive voice in key claims
7. Every quantitative claim has a cited source
8. Tone matches exemplars (confident, not tentative)
9. BLUF present in first 2 sentences
10. Frozen sections unmodified

## Document
[paste document]

## Output Format
For each violation:
- Line N: [issue] → Suggested fix: [fix]

If all checks pass, state "✓ All constraints satisfied."
```

#### How to Use

**In Cursor/Zed**: Save Prompt 1 as `.cursorrules` or a project-level system prompt. Use Cmd+K with writing instructions. Run Prompt 2 manually after each draft pass.

**In our chat app**: Use `PromptWorkflowAgent` with `workflow_prompts=[prompt_1, prompt_2]` and `user_query=<brief + data>`. Two-step automatic pipeline.

**Limitation**: Must re-paste guidelines every session (Cursor) or per-conversation (our chat). No persistence across sessions, no standing directives, no deterministic constraint checking.

---

### Option 1: Minimum Viable Enhancement (2-3 weeks)

Build only what Cursor/Zed cannot provide. No new UI — just backend + chat tools.

#### What to Build

| Component | Effort | Value |
|-----------|--------|-------|
| `writing_config` field on artefacts (JSON blob: brief, constraints, audience, exemplars, directives) | 2 days | Config persists per document. Auto-injected into propose_edits. |
| `ConstraintEngine` class (pure Python: word count, readability, forbidden terms, required sections, passive voice, hedge words) | 3 days | Deterministic, instant, free (no LLM tokens). Exposed as chat tool. |
| Standing directives CRUD (simple JSON list on artefact, injected into every LLM call) | 1 day | "Don't touch the intro" survives across sessions. |
| Writing presets for `PromptWorkflowAgent` (style-first-draft, edit-pass, fact-check) | 2 days | One-command full pipeline from chat. |
| `propose_artefact_edit` as a chat tool (wraps existing endpoint) | 1 day | LLM can edit artefacts from chat with diff/accept/reject. |
| `check_constraints` as a chat tool | 0.5 day | "Check my doc" → instant structured results in chat. |

**Total: ~2 weeks**

#### What This Gives You Over Zero-Build

- Constraints checked deterministically (not LLM-guessed)
- Writing config persists per artefact (no re-pasting)
- Standing directives remembered across sessions
- Pipeline runnable from chat as one command
- Diff-based accept/reject for AI edits (already exists, just exposed as tool)

#### What's Still Missing vs. Full Spec

- No dedicated writing tab/editor (use artefact modal or Cursor)
- No Cmd+K in our editor (use Cursor for that)
- No structure panel, outline, source linking
- No audience simulation (but can approximate with a prompt)
- No version timeline with intent (just git/file saves)
- No ghost text

---

### Option 2: Full Writing Studio (3+ months)

The complete spec as documented above. Dedicated Svelte SPA, ProseMirror editor, tab integration, multi-agent pipeline, constraint dashboard, source management, etc.

---

## When to Escalate from Option 0 → 1 → 2

### Escalate from Zero-Build to Option 1 when:

You notice ANY of these friction patterns repeatedly (3+ times):

- [ ] **Re-pasting context**: You keep pasting the same style guidelines, exemplars, or brief into prompts. You wish the system just "knew" your style for this doc.
- [ ] **Constraint misses**: The LLM says "looks good" but you find it's 200 words over limit, or has a forbidden term. You want deterministic checking.
- [ ] **Forgotten directives**: You told the AI "don't touch section X" last session, but this session it rewrites it again. You need persistent memory.
- [ ] **Manual verification fatigue**: You're running Prompt 2 manually every time and it's tedious. You want it automated/instant.
- [ ] **Tool switching cost**: Copy-pasting between Cursor and your chat app (for PKB, source docs, discussion context) is slowing you down.

### Escalate from Option 1 to Full Studio when:

You notice ANY of these patterns repeatedly:

- [ ] **Spatial frustration**: You want to see the outline + document + constraints simultaneously. The artefact modal is too cramped. You're constantly scrolling.
- [ ] **Inline edit desire**: You want Cmd+K in your own editor (not switching to Cursor) because the context (writing_config, directives, conversation docs) isn't available there.
- [ ] **Source tracking need**: You're writing docs with 5+ source PDFs and losing track of which claims are supported. You need a source panel.
- [ ] **Iteration depth**: You do 5+ editing passes on a single doc and wish you could see the evolution, revert sections, branch alternatives.
- [ ] **Audience-specific feedback**: You're manually writing "read this as a VP" prompts and want it to be one button.
- [ ] **Team/process need**: Others will use this system and need a polished, self-explanatory UI (not chat commands).
- [ ] **Volume**: You're producing 3+ serious documents per week and the workflow overhead of Option 1 is noticeable.

### Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-16 | Start with Option 0 (two-prompt workflow) | Test hypothesis with zero investment. Evaluate after 2 weeks of actual usage. |
| | | |
| | | |

---

## Quick Start: Using Option 0 Today

### In Our Chat App (with existing PromptWorkflowAgent)

```
/write

Brief: Convince VP to fund $2M platform investment
Audience: VP, 2-minute reader
Genre: Business one-pager

Data:
- Current capacity: 10K req/s
- Q4 projected: 45K req/s
- Estimated savings: 40% operational cost reduction
- Timeline: 6 months

Style: Confident, data-first, no hedging. See attached exemplar.

Constraints: ≤1500 words, Grade 10 reading level, must include Summary/Problem/Proposal/Risks/Ask sections.
```

The `PromptWorkflowAgent` runs with preset prompts (writer → verifier) and streams results.

### In Cursor

1. Create `.cursorrules` with Prompt 1 content (your style + constraints)
2. Create the document as a `.md` file
3. Use Cmd+K for edits: "make this section shorter" / "add data from the Q2 report"
4. Periodically open a new Cursor chat, paste Prompt 2 + document for verification
5. Apply fixes via Cmd+K

### Evaluating

After 2 weeks of using Option 0, fill out:

```
Friction log:
- How many times did I re-paste guidelines? ___
- How many times did the verifier miss something deterministic? ___
- How many times did I forget/re-state a directive? ___
- How many times did I switch between apps for context? ___
- Am I writing enough docs to justify building? (docs/week) ___
- What's my biggest single pain point? ___
```

If total friction events > 10 in 2 weeks → build Option 1.
If total friction events < 5 → Option 0 is enough. Revisit in a month.

---

## Design Decisions: Q&A Log

All UX and architecture questions discussed during planning, with final decisions.

### Organizational Model

**Q: Should writing artefacts belong to a conversation or be top-level entities?**

A: **Conversation-scoped.** Each writing artefact belongs to a conversation. The conversation is marked `is_writing_project: true` and shows with a document icon in the sidebar. This gives free source/doc management (upload PDFs to the conversation), chat history as context, PKB claims as sources, workspace hierarchy for organization. Global docs accessible via `#gdoc_all`, `#tag:`, `#folder:`.

### Multi-Tab Integration

**Q: How should the writing studio open relative to chat?**

A: **As a tab pane beside chat.** Uses the `feat/multi-conversation-tabs` TabManager. Writing studio loads in an iframe (`/write/<artefact_id>?embedded=true`) within a tab pane. User can flip between chat (upload docs, discuss, research) and writing (edit) instantly. Same conversation, two views.

**Q: Why not full-page navigation?**

A: Loses multi-tab context. Can't see chat + writing side by side. Can't upload a PDF mid-writing without leaving the editor. Can't stream chat responses while in writing tab.

### AI Panel

**Q: Does the writing studio need an AI panel (right sidebar for chat with the LLM)?**

A: **No.** Since we have two tabs (chat + writing), an AI panel would be redundant and confusing (two places to send messages). The chat tab IS the AI interface. The writing tab has only Structure panel + Editor.

**Q: How do AI-initiated edits work without an AI panel?**

A: The LLM in chat has tools (`propose_artefact_edit`, `artefact_terminal`, `run_writing_agent`, etc.). When it proposes an edit, a diff card appears in chat with Accept/Reject. Accepting applies the change immediately to the artefact — writing tab refreshes to show new content.

### Edit Suggestions Display

**Q: How should edit suggestions appear in the editor?**

A: **Cursor-style inline diff.** Old text dimmed/struck, new text in green. Accept (⌘Y) / Reject (⌘N) without leaving the editor. Follow-up prompts allowed to modify the suggestion.

### Context for Instructions

**Q: When the user types a Cmd+K instruction, what context should it use?**

A: **Document + writing config + conversation docs + global docs + recent chat context.** Full reference system available: `#doc_1`, `#gdoc_all`, `#folder:`, `#tag:`, `@section:`, `@artefact_N`. Also supports natural language references ("the intro"). System auto-retrieves relevant chat context when instruction seems to reference a discussion.

### @ References

**Q: Should the writing system support @section references?**

A: **Yes.** `@section:Summary` (or `@section:Problem`) resolves by scanning markdown headings h1-h4. Injects that section's content as additional context. Can also scope edits: `@section:Problem` after selection means "edit my selection with section Problem as context." Natural language ("the intro") also works — LLM resolves it.

### AI Panel Persistence

**Q: Should AI results persist across sessions?**

A: **N/A** — no AI panel. Chat history persists naturally (it's a conversation). Standing directives persist on the artefact. Version timeline tracks what was done.

### Editor Inline Edit Initiation

**Q: How should the user initiate an edit from within the editor?**

A: **Both floating toolbar + Cmd+K.** Floating toolbar for common one-click actions (Rewrite, Shorten, Expand, Restyle, Annotate, Freeze). Cmd+K for custom typed instructions. Cursor-style.

### Brief Location

**Q: Where should the Brief live in the UI?**

A: **In the Structure panel as a tab** (alongside Outline, Sources, Versions, Config). Always accessible but not competing with the editor. The LLM always has access to it via writing_config.

### Constraint Violations

**Q: What happens when a constraint is violated?**

A: **Status bar turns red + editor highlights the offending region** (red underline on forbidden term, colored section for over-budget). Clicking the status bar constraint scrolls to the violation. No proactive AI suggestions (that would require an AI panel). User can ask in chat: "fix constraint violations."

### Version Snapshots

**Q: When should version snapshots be created?**

A: **Both auto + agent-triggered.** Auto-save for user manual edits (debounced, after 30s of no typing). Agent-triggered version when an Accept applies a tool-proposed change. Different version types (`user_edit` vs `agent_edit`) in timeline. Each version records intent.

### Opening Writing Studio

**Q: How should "Open Writing Studio" work?**

A: **Button in chat header/toolbar** when a writing-project artefact exists (✍️ icon). Also available in artefact modal ("Open in Studio"). Creates a new tab with `type: "write"`.

### Structure Panel Control

**Q: How much control should the outline give the user?**

A: **Full structural editing (Phase 5 feature)** — drag to reorder, right-click for operations (split, merge, expand, compress, delete), agent auto-adjusts transitions. Start with read-only outline (auto-generated from headings, click to jump) in Phase 1.

### Source Document Integration

**Q: How should sources integrate with the editor?**

A: **Sources listed in panel + hover-to-verify for inline claims.** Sources listed in Structure panel Sources tab. Hover over a sourced claim → tooltip shows source excerpt. Unsourced claims flagged with orange underline. No auto-suggestions while typing (too noisy).

### Accept/Reject Model (Cmd+K)

**Q: For Cmd+K inline edits, which accept/reject model?**

A: **Cursor style (A).** Diff shown inline (green/red lines), ⌘Y accept / ⌘N reject / ⌘R regenerate. Also allows follow-up prompts to modify the edit. Not Zed-style direct replacement.

### Chat "Apply" Behavior

**Q: Should chat tool Apply button show diff for review or directly apply?**

A: **Show diff in a modal (B).** Never apply directly. User clicks "View Diff" on the diff card in chat → modal shows syntax-highlighted unified diff → Accept/Reject/Edit & Retry in the modal.

### Ghost Text

**Q: Should there be ghost text in the writing editor?**

A: **Yes, conservative sentence-completion only (B).** After 3+ seconds pause, at end of paragraph only. Easy to dismiss (keep typing). Aware of writing config (brief + style exemplars) for better alignment — uses surrounding text + brief + exemplars as prompt context.

### Chat Results Styling

**Q: How should agent/tool results appear in chat?**

A: **N/A** — no separate AI panel. Results appear as normal chat messages from the LLM, with diff cards embedded (structured cards with View Diff / Accept / Reject buttons). Feels like a natural conversation where the AI shows its work.

### LLM Editing Autonomy

**Q: Should the LLM autonomously suggest edits or only when asked?**

A: **Only when asked.** The LLM does not proactively propose edits. It uses tools to edit only when the user explicitly requests it. No unsolicited suggestions.

### Editing Tools

**Q: What tools should the chat LLM have for editing artefacts?**

A: **Two paths:**
- **Primary**: `propose_artefact_edit` — wraps existing `propose_edits` endpoint. Structured ops + diff. Single tool call.
- **Secondary**: `artefact_terminal` — sandboxed shell on a shadow copy. For complex multi-step edits where structured ops are insufficient.

**Terminal sandbox rules:**
- Commands must contain the artefact filename, else rejected
- Blocked: rm, mv, chmod, chown, curl, wget, nc, ssh, scp, rsync, any network command
- No path traversal (no `..`, realpath must stay within artefacts dir)
- Edits go to `<filename>.proposed` (shadow copy)
- After session: diff shown as card in chat → Accept (swap files) / Reject (delete .proposed)

### Cursor/Zed vs. Building

**Q: Should we even build this given Cursor/Zed exist?**

A: **Start with zero-build (two-prompt workflow).** Evaluate after 2 weeks of real usage. Build only if friction signals exceed threshold (>10 events in 2 weeks). If building, start with Option 1 (constraint engine + writing_config + standing directives + chat tools, 2-3 weeks). Full studio (Option 2) only when spatial/inline/source/iteration needs emerge from actual usage.

**What Cursor can't do** (justification for eventual build):
- Persistent per-document writing config
- Deterministic constraint checking (no LLM tokens)
- Standing directives (remembered across sessions)
- Source/citation tracking and fact-checking
- Integrated with our chat/PKB/conversation docs ecosystem
- Version timeline with editorial intent

---

## Requirement: Preview Mode + Edit-in-Preview

### Need

The writing editor must support:
1. **Live preview** — rendered markdown alongside or instead of raw source (like our file browser's Raw/Preview/WYSIWYG toggle)
2. **Edit in preview mode** — click on rendered text to edit it inline (WYSIWYG), not just in raw markdown

### How Our System Already Does This

- File Browser: `.md` files have a **Raw / Preview / WYSIWYG** selector. WYSIWYG uses EasyMDE. CodeMirror is source of truth.
- Artefact modal: Code tab (raw) + Preview tab (rendered markdown)
- Message edit modal: edit raw text, preview rendered below

### Is Edit-in-Preview Possible with ProseMirror?

**Yes — ProseMirror is designed for this.** Unlike CodeMirror (code editor), ProseMirror is a rich-text/structured-content editor. It can render markdown as formatted rich text (headings, bold, lists, links) while still being editable. This is its primary use case.

Options:
- **ProseMirror with prosemirror-markdown** — parse markdown → ProseMirror doc → edit rich text → serialize back to markdown. Users edit in what looks like rendered markdown. This is how Notion, Outline, and many markdown editors work.
- **Split view** — raw markdown on left, live preview on right (synced). Edit in either.
- **Toggle** — switch between raw (CodeMirror) and WYSIWYG (ProseMirror). Source of truth is the markdown string.

**Recommendation**: ProseMirror in WYSIWYG mode as default (edit rendered markdown directly). Toggle to raw mode for users who want source control. This is superior to our current EasyMDE approach (EasyMDE is limited; ProseMirror is production-grade).

---

## Alternative: Folder-Based Workflow with External Agentic Tools

### The Idea

Instead of building a custom writing studio, create a **folder convention** that any agentic tool (Claude Code, Cursor, Kiro, Aider) can understand:

```
writing-projects/
└── q3-strategy-one-pager/
    ├── agents.md           ← instructions for the AI agent (workflow, orchestration)
    ├── guidelines.md       ← style guide, tone, checks, constraints, exemplars
    ├── brief.md            ← document objective, audience, key messages
    ├── output.md           ← the actual document being written
    ├── supporting_docs/
    │   ├── q2_revenue.pdf
    │   ├── competitor_analysis.md
    │   └── vp_feedback.txt
    └── .writing_config.json  ← machine-readable constraints (word count, required sections)
```

### `agents.md` Content

```markdown
# Writing Agent Instructions

## Your Role
You are a writing assistant helping produce `output.md` based on the brief, 
guidelines, and supporting documents in this folder.

## Workflow (Multi-Pass)

### Pass 0: Setup (only if guidelines.md is incomplete)
1. Read brief.md to understand the document objective
2. If guidelines.md is missing or has TODO markers:
   - Ask the user about their writing style preferences
   - Ask about tone, audience expectations, formatting conventions
   - Ask about do's and don'ts
   - Update guidelines.md with their answers
3. If guidelines.md exists and is complete, proceed to Pass 1

### Pass 1: Structure
1. Read brief.md (objective, audience, key messages)
2. Read guidelines.md (style, tone, constraints)
3. Read supporting_docs/ for data and evidence
4. Generate an outline in output.md with section headings + bullet points per section
5. Ask user to review/approve structure before proceeding

### Pass 2: Draft
1. Fill each section with prose following guidelines.md
2. Cite supporting_docs where relevant
3. Respect constraints in .writing_config.json (word limits, required sections)

### Pass 3: Verify
1. Check output.md against every rule in guidelines.md
2. Check against .writing_config.json constraints:
   - Word count within limits?
   - All required sections present?
   - No forbidden terms?
   - Reading level appropriate?
3. List all violations with line numbers
4. Propose fixes for each violation

### Pass 4: Revise
1. Apply fixes from Pass 3 (show diff, get approval)
2. Re-run Pass 3 to confirm all violations resolved
3. If clean, declare done

## Standing Directives
- Read this section before every edit. These are user decisions that must be respected.
- [Directives added here during the writing process]

## Rules
- Never edit guidelines.md without user permission
- Never delete content from supporting_docs/
- Always show diffs before applying changes to output.md
- Ask clarifying questions rather than guessing intent
- Maximum 5 passes. If not converging, ask user for guidance.
```

### `guidelines.md` Template

```markdown
# Writing Guidelines

## Style & Tone
- [Voice description or "TODO: ask user"]
- [Exemplar paragraphs or "TODO: ask user for 2-3 sample paragraphs"]

## Audience
- Primary: [e.g., VP-level, 2-minute reader]
- Secondary: [e.g., Engineering lead, 10-minute reader]

## Format
- Genre: [e.g., Business one-pager, Technical RFC, Blog post]
- Structure: [e.g., Summary → Problem → Proposal → Risks → Ask]

## Constraints
- Max words: [e.g., 1500]
- Reading level: [e.g., Grade 10]
- Required sections: [list]
- Forbidden terms: [list]

## Do's
- [e.g., Lead with data, use active voice, cite sources]

## Don'ts
- [e.g., No hedge words, no passive voice in claims, no jargon without definition]

## Checks (run after every draft)
- [ ] Word count within limit
- [ ] All required sections present
- [ ] No forbidden terms
- [ ] Every claim has a source or is marked as opinion
- [ ] Tone matches exemplars
- [ ] BLUF in first 2 sentences
```

### Will This Work with External Agentic Tools?

| Tool | Can it do this? | Limitations |
|------|----------------|-------------|
| **Claude Code (Kiro CLI)** | ✅ Yes. Reads all files, follows agents.md, multi-pass with user confirmation, shows diffs. | No live preview/WYSIWYG. Terminal-only. No constraint dashboard. Must trust agent to self-check. |
| **Cursor (Composer mode)** | ✅ Yes. Reads project files, @file references, multi-file edits with diffs. Can follow agents.md. | No autonomous multi-pass (user must prompt each pass). No deterministic constraint engine. No preview in-editor for .md. |
| **Cursor (Cmd+K)** | ⚠️ Partial. Per-edit only. Can reference guidelines.md via @file. | No multi-pass orchestration. Single edit at a time. |
| **Aider** | ✅ Yes. Reads repo, follows instructions, shows diffs, multi-file edits. | CLI-only. No preview. No interactive approval per-hunk. |
| **Windsurf** | ✅ Yes. Similar to Cursor Composer. | Same limitations as Cursor. |

### Honest Assessment: Are External Tools Fully At Par?

**What they DO give you (for free):**
- ✅ Multi-file awareness (agents.md + guidelines.md + output.md + supporting_docs)
- ✅ Diff-based editing with accept/reject
- ✅ Cmd+K inline edits
- ✅ Agent can read guidelines and follow them
- ✅ Terminal access for verification scripts
- ✅ Git versioning

**What they DON'T give you:**

| Gap | Impact |
|-----|--------|
| **No deterministic constraint engine** | Agent "checks" constraints by asking the LLM. LLM can miss word count by 50 or overlook a forbidden term. Not reliable for hard rules. |
| **No persistent standing directives that survive context loss** | Claude Code/Cursor context windows fill up. After 50+ messages, earlier "don't touch section X" is lost. agents.md helps but isn't actively enforced. |
| **No live constraint dashboard** | You don't know you're over word count until you ask. No real-time status bar. |
| **No structured version timeline with intent** | Git gives you what changed but not why. No "this was a style pass" vs "this was a reduction pass" metadata. |
| **No audience simulation** | Must manually prompt "read as a VP." No saved audience profiles. |
| **No source-claim linking** | Agent can read supporting_docs but doesn't track which claims are sourced. No "unsourced claims" flagging. |
| **No rendered preview with inline editing** | All tools show raw markdown. No WYSIWYG. For business users who think in formatted text, this is a friction point. |
| **No integration with our PKB/chat/conversation docs** | Supporting docs must be manually placed in the folder. No access to globally uploaded docs, PKB claims, or prior chat context about this project. |

### Verdict

**The folder-based approach with external tools is 70-80% as good as the full custom solution.** The missing 20-30% is:
- Deterministic constraints (reliable, instant, free)
- Persistent memory that doesn't degrade with context length
- Live preview/WYSIWYG editing
- Integration with our existing ecosystem (PKB, conversation docs, chat history)

**For a solo writer who's comfortable in terminal/Cursor**: the folder approach is probably sufficient. The `agents.md` file is the orchestrator.

**For a system that must be reliable** (constraints always enforced, no LLM hallucination on word count) **or integrated** (needs PKB claims, conversation docs, chat context): build Option 1 minimum.

### Recommendation

1. **Start today**: Create the folder structure + `agents.md` + `guidelines.md` template. Use with Claude Code or Cursor.
2. **Track friction**: Use the friction log from the evaluation framework above.
3. **Build Option 1 when**: Constraint checking fails you (LLM misses violations) or context loss causes repeated "I told you not to change X" frustration.
4. **Build full studio when**: You need preview/WYSIWYG, or non-technical users need to use the system, or you're producing high volume (3+ docs/week).

---

## Final Decision: Folder-Based Convention (No Custom Build)

### Conclusion

After analyzing all gaps, every limitation of the folder-based approach has a solution within existing agentic tooling:

| Original gap | Solution |
|---|---|
| Context window exhaustion | `worklog.md` + `learnings.md` as running files. Agent re-reads on each pass. |
| Persistent directives | `directives.md` (re-read before every edit). Cursor slash commands for enforcement. |
| No PKB/chat history integration | PKB exposed as MCP server. Agent queries it directly. |
| Manual orchestration | agents.md instructs "complete all passes." One prompt triggers full workflow. |
| No audience simulation | Slash command: `/simulate-reader` → expands to structured prompt. |
| Folder management overhead | Template folder copied per project. Keeps flexibility, prevents rigidity. |
| No deterministic constraints | `check.py` script in folder. Agent runs via terminal. Reliable, instant. |
| WYSIWYG / preview | Cursor/VS Code split preview pane. |
| Per-hunk diff accept/reject | Cursor has this natively. |
| Live constraint status bar | File watcher script or VS Code extension updating `constraints_status.md`. Nice-to-have. |

### Why Not Build

The custom tool's only advantage is **integrated UX polish for non-technical users**. For a technical user comfortable with agentic tools:

1. **Flexibility** — folder convention grows with every LLM improvement. Custom tool stays static until you update code.
2. **Zero maintenance** — no bugs, no dependency upgrades, no frontend framework churn.
3. **Tool-agnostic** — works with Claude Code today, whatever tool is best next year.
4. **Customizable per project** — edit any `.md` file. No UI limitations.
5. **Evolvable** — as agentic orchestration improves (better multi-pass, better tool use), the folder approach automatically benefits.

### When to Reconsider Building

Only build the custom writing studio if:
- [ ] Non-technical users need to use the system (need polished UI)
- [ ] You need real-time collaborative writing (multiple authors, live sync)
- [ ] PKB MCP integration proves insufficient (structured source-claim linking needed beyond what MCP queries provide)
- [ ] Volume exceeds what folder management can handle (10+ concurrent writing projects)

### The Complete Folder Convention

```
writing-projects/
└── <project-name>/
    ├── agents.md              ← orchestration (multi-pass workflow, rules, automation)
    ├── guidelines.md          ← style, tone, audience, do's/don'ts, exemplars
    ├── brief.md               ← objective, key messages, data to include
    ├── directives.md          ← standing editorial decisions (re-read before every edit)
    ├── output.md              ← the document being written
    ├── worklog.md             ← running log of actions taken, decisions made
    ├── learnings.md           ← accumulated insights about this doc/style
    ├── check.py               ← deterministic constraint checker (run via terminal)
    ├── constraints_status.md  ← auto-updated by check.py or file watcher
    └── supporting_docs/
        ├── *.pdf, *.md, *.txt
        └── (source materials)
```

### `check.py` (Deterministic Constraints)

```python
#!/usr/bin/env python3
"""Run: python check.py output.md — prints constraint status."""
import sys, re, json

def check(filepath):
    with open(filepath) as f:
        content = f.read()
    
    words = content.split()
    word_count = len(words)
    
    # Load config
    config = {}
    try:
        with open('.writing_config.json') as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {"max_words": 1500, "forbidden_terms": [], "required_sections": []}
    
    results = []
    
    # Word count
    max_w = config.get("max_words", 1500)
    status = "✅" if word_count <= max_w else "❌"
    results.append(f"{status} Words: {word_count} / {max_w}")
    
    # Forbidden terms
    forbidden = config.get("forbidden_terms", [])
    for term in forbidden:
        matches = [(i+1, line) for i, line in enumerate(content.splitlines()) if term.lower() in line.lower()]
        if matches:
            results.append(f"❌ Forbidden term '{term}' at line(s): {[m[0] for m in matches]}")
    if not any("Forbidden" in r for r in results):
        results.append("✅ No forbidden terms")
    
    # Required sections
    headings = re.findall(r'^#{1,4}\s+(.+)', content, re.MULTILINE)
    required = config.get("required_sections", [])
    for section in required:
        found = any(section.lower() in h.lower() for h in headings)
        status = "✅" if found else "❌"
        results.append(f"{status} Section '{section}': {'present' if found else 'MISSING'}")
    
    # Hedge words
    hedge_words = ["might", "perhaps", "arguably", "somewhat", "possibly", "maybe"]
    hedge_count = sum(content.lower().count(w) for w in hedge_words)
    hedge_pct = (hedge_count / max(word_count, 1)) * 100
    status = "✅" if hedge_pct <= 3 else "⚠️"
    results.append(f"{status} Hedge words: {hedge_pct:.1f}% ({hedge_count} occurrences)")
    
    print("\n".join(results))
    
    # Write to status file
    with open("constraints_status.md", "w") as f:
        f.write("# Constraint Status\n\n" + "\n".join(results) + "\n")

if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "output.md")
```

### Slash Commands (for Cursor/Agentic Tools)

```
/verify        → "Run python check.py output.md and report results. If violations found, propose fixes."
/simulate-reader → "Read output.md as the audience described in guidelines.md. Report: key takeaway, what confused you, questions you'd ask, verdict."
/style-check   → "Compare output.md tone against the exemplars in guidelines.md. Flag any paragraphs that drift from the target voice."
/full-pass     → "Execute the complete workflow from agents.md (Pass 1-4). Stop only if you need clarification."
```

### Migration Path

If this approach proves insufficient later:
1. The folder structure maps directly to `writing_config` (brief.md → brief field, guidelines.md → guidelines + exemplars, directives.md → standing directives)
2. `check.py` logic maps directly to `ConstraintEngine`
3. `agents.md` workflow maps to `WritingOrchestrator`
4. Supporting docs map to conversation docs

Nothing is wasted. The folder convention is the spec for a custom tool, expressed as text files instead of code.
