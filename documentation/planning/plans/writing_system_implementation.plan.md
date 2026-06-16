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

### How Writing Studio Opens

```
Sidebar interaction:
├── Normal click on writing-project conversation:
│   → If current tab, replace with writing studio (full page navigation to /write/<id>)
│   → Or: load writing studio SPA into the chat pane (iframe or dynamic import)
│
├── Ctrl+click on writing-project conversation:
│   → Open new tab with type: "write"
│   → TabManager.tabs.push({conversationId, title, type: "write"})
│
└── Context menu → "Open in New Tab":
    → Same as Ctrl+click

Tab rendering:
├── type: undefined/null → render chat view (existing behavior)
└── type: "write" → render writing studio (iframe to /write/<artefact_id> or SPA mount)
```

### Iframe vs. SPA Mount

| Approach | Pros | Cons |
|----------|------|------|
| **iframe** to `/write/<id>` | Complete isolation, own JS context, can't conflict with main app | Cross-frame communication awkward, no shared auth state without postMessage, heavier |
| **Dynamic import** of Svelte bundle | Lighter, shares auth token, can communicate with TabManager directly | Must avoid global CSS conflicts (use scoped styles or shadow DOM), bundle loaded into main page context |
| **Full page navigation** | Simplest. Back button returns to chat. No integration complexity | Loses multi-tab context, can't see chat + writing side by side |

**Recommendation**: Start with **full page navigation** (`window.location = /write/<id>`). The writing studio is a full-screen experience anyway. If multi-tab coexistence proves important, migrate to iframe later. The Svelte app is already self-contained — either serving model works without code changes.

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

- [ ] `type: "write"` support in TabManager
- [ ] Full page navigation to `/write/<id>` from sidebar
- [ ] Back-to-chat navigation from writing studio
- [ ] Tab title sync with artefact name

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
