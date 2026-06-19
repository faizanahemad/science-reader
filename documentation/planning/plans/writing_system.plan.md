# Writing System Spec

## Motivation & Background

LLMs can generate fluent text but struggle with:
- Maintaining consistent voice across long documents
- Structural coherence beyond ~2000 words
- Originality (defaulting to generic patterns and clichés)
- Self-evaluation (the writer judging its own writing always says "looks good")
- Respecting hard constraints (word count, required sections, forbidden terms) without constant reminding
- Preserving author intent across multiple editing passes

Current system has the pieces (artefacts for storage/diff, DocumentEditingAgent for multi-stage editing, PKB for source management, chat for interaction) but they're disconnected. This spec defines the unified system.

## Target Writing Domains

| Domain | Key requirements |
|--------|-----------------|
| **Business** (emails, memos, PRDs, one-pagers) | BLUF, audience-awareness, action-orientation, brevity |
| **Technical/Science** (papers, docs, RFCs) | Precision, citation-backed claims, internal consistency, peer-review readiness |
| **AI/ML** (experiment reports, model cards, lit reviews) | Data-grounded claims, reproducibility language, evidence-linked |
| **Management** (perf reviews, strategy docs, escalations) | Political awareness, diplomatic honesty, action-oriented |
| **Creative** (fiction, essays, scripts, blog posts) | Voice-driven, surprising, emotionally resonant, structurally inventive |

## Design Principles

1. **Separation of concerns**: The agent that writes prose never judges its own prose. Critic and drafter are distinct roles.
2. **Persistent intent**: The brief/goal survives across all passes. Every edit is verified against original intent.
3. **Deterministic where possible**: Word count, readability, forbidden terms, required sections — checked by rules, not LLM.
4. **Progressive refinement**: Each pass has a narrow focus. Never "make this better" — always "fix this specific dimension."
5. **User retains agency**: The system proposes, the user disposes. No auto-apply without review. Priority-ranked suggestions.
6. **Style by example, not description**: 2-3 paragraphs of target voice > abstract adjectives like "professional" or "warm."
7. **Structure before prose**: Generate skeleton → review → fill. Never go straight from brief to final text.

## Architecture: Multi-Agent Writing Studio

### Agent Roles

```
Orchestrator (Editor-in-Chief)
│   Decides next action, maintains intent, verifies constraints
│   Temperature: 0.2 | Model: cheap/fast
│
├── Planner
│   Generates outlines, proposes structure, assigns word budgets per section
│   Temperature: 0.5 | Model: standard
│
├── Drafter
│   Writes prose to fill structure. Creative, generative.
│   Temperature: 0.7–0.9 | Model: expensive/creative
│
├── Critic
│   Reviews draft. Finds weak arguments, redundancy, unclear passages, logical gaps.
│   Asks "so what?" and "says who?" for every claim.
│   Temperature: 0.3 | Model: standard
│
├── Stylist
│   Enforces voice/tone/guidelines. Applies exemplar style. Fixes register drift.
│   Temperature: 0.3 | Model: standard
│
├── Fact-Checker
│   Verifies claims against ingested sources. Flags unsupported assertions.
│   Temperature: 0.0 | Model: standard
│
├── Reducer
│   Cuts word count. Eliminates redundancy, filler, hedge words. Tightens.
│   Temperature: 0.3 | Model: standard
│
└── Reader Simulator
    Simulates target audience reaction. Reports what they'd take away,
    what confuses them, what questions they'd ask.
    Temperature: 0.5 | Model: standard
```

### Orchestrator Decision Loop

```
1. Run deterministic constraint check → constraint dashboard
2. If hard constraints violated → dispatch appropriate specialist
3. If constraints pass → run Critic
4. If Critic finds substantive issues → route to Drafter/Reducer/Stylist
5. If Critic satisfied → run Reader Simulator for target audience
6. If Reader Sim satisfied → mark "done" (offer to user)
7. If not → one targeted pass with specific feedback
8. Cap at N passes (configurable, default 5). Never infinite polish.
```

The orchestrator never writes prose. It only decides and verifies.

### When to Use Which Agent

| Trigger | Agent(s) dispatched |
|---------|-------------------|
| New document from brief | Planner → Drafter |
| "Make this shorter" | Reducer |
| "Check the tone" | Stylist |
| "Is this convincing?" | Critic → Reader Simulator |
| "Verify my claims" | Fact-Checker |
| "Full editing pass" | Orchestrator loop (all agents as needed) |
| "Rewrite section 3" | Drafter (scoped to section) |
| Constraint violated | Specialist based on which constraint |

## UX: Three-Panel Writing Studio

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  LEFT: Structure         │  CENTER: Editor            │  RIGHT: Agent     │
│                          │                            │                   │
│  Outline (draggable)     │  Rich markdown editor      │  Chat (contextual)│
│  Section word counts     │  Inline annotations        │  Active brief     │
│  Constraint dashboard    │  Frozen zones (greyed)     │  Style exemplars  │
│  Version timeline        │  Ghost suggestions         │  Guidelines list  │
│  Sources/references      │  Selection → action menu   │  Constraint status│
│  Section status          │  Cmd+K inline edits        │  Revision log     │
│  (draft/reviewed/final)  │  Split view (draft + diff) │  Audience config  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Interaction Modes

**1. Chat mode** (right panel)
- Natural language instructions scoped to current selection or whole document
- Agent responses include proposed changes (diff preview)
- Persistent context: brief, guidelines, revision history available to agent

**2. Inline mode** (Cmd+K in editor)
- Selection → instruction → proposed edit inline
- Quick accept/reject per suggestion
- Ghost text for small completions (sentence-level only, not paragraph)

**3. Pipeline mode** (explicit multi-pass)
- User triggers "full edit pass" or "prepare for review"
- Orchestrator runs autonomously through agent loop
- Results presented as prioritized suggestion list
- User accepts/rejects in batches

**4. Structural mode** (left panel)
- Drag-and-drop reordering of sections in outline
- Agent automatically adjusts transitions when sections move
- Section-level operations: "expand," "compress," "rewrite," "delete," "split"

### Ghost Text vs. Suggestions

| Feature | Behavior |
|---------|----------|
| Ghost text | Sentence-level inline prediction. Low-key, greyed, Tab to accept. For continuation only. |
| Suggestions | Section-level proposed edits. Highlighted, reviewable, accept/reject. For improvement. |
| Annotations | Agent or user notes attached to passages. Not edits — context for future passes. |

Ghost text should be rare and unobtrusive in writing (unlike code). Writing needs thinking space, not constant completion pressure.

## Data Model

### Document (extends Artefact)

```json
{
  "id": "uuid",
  "name": "Q3 Strategy One-Pager",
  "file_type": "md",
  "content": "...",

  "writing_config": {
    "brief": "Convince leadership to invest in X. Key messages: cost savings, team velocity, risk reduction.",
    "audience": "VP-level, 2 minutes reading time, expects BLUF",
    "genre": "business_one_pager",
    "tone_exemplars": ["<paragraph 1 in target style>", "<paragraph 2>"],
    "guidelines": ["artefact_id_of_style_guide", "path/to/brand_voice.md"],
    "constraints": {
      "max_words": 1500,
      "min_words": 800,
      "max_reading_level": 10,
      "required_sections": ["Summary", "Problem", "Proposal", "Risks", "Ask"],
      "forbidden_terms": ["synergy", "leverage", "paradigm"],
      "custom_rules": ["Every claim must have a data point or citation"]
    },
    "frozen_zones": [
      {"start_line": 45, "end_line": 52, "reason": "Approved legal language"}
    ]
  },

  "revision_history": [
    {
      "version": 1,
      "timestamp": "...",
      "intent": "Initial draft from brief",
      "agent": "Drafter",
      "constraint_snapshot": {"words": 1823, "reading_level": 12.3}
    },
    {
      "version": 2,
      "timestamp": "...",
      "intent": "Reduce word count, simplify language per Critic feedback",
      "agent": "Reducer",
      "constraint_snapshot": {"words": 1456, "reading_level": 9.8}
    }
  ],

  "annotations": [
    {"line": 23, "text": "Need data for this claim", "author": "user", "resolved": false},
    {"line": 67, "text": "Tone shifts to informal here", "author": "Stylist", "resolved": false}
  ],

  "sources": [
    {"id": "src_1", "type": "url", "url": "...", "title": "...", "extracted_claims": [...]},
    {"id": "src_2", "type": "pkb_claim", "claim_id": "...", "text": "..."}
  ]
}
```

### Writing Session State

```json
{
  "document_id": "...",
  "active_brief": "...",
  "pass_count": 3,
  "max_passes": 5,
  "standing_directives": [
    "Keep it under 1500 words",
    "Section 2 needs more data, everything else is approved"
  ],
  "completed_passes": [
    {"pass": 1, "type": "full_draft", "agents_used": ["Planner", "Drafter"]},
    {"pass": 2, "type": "critique", "agents_used": ["Critic"]},
    {"pass": 3, "type": "targeted", "agents_used": ["Reducer", "Stylist"]}
  ]
}
```

## Constraint Engine (Deterministic, No LLM)

Runs after every edit. Returns pass/fail per constraint.

### Built-in Checks

| Check | Implementation |
|-------|---------------|
| Word count (min/max) | `len(text.split())` |
| Reading level | Flesch-Kincaid grade level formula |
| Required sections | Heading regex match |
| Forbidden terms | Case-insensitive substring/regex search |
| Sentence length variance | Std dev of sentence lengths (flags monotony) |
| Paragraph length | Flag paragraphs > N words (wall of text) |
| Passive voice ratio | SpaCy or regex-based detection |
| Hedge word density | Dictionary lookup ("might", "perhaps", "arguably", etc.) |
| Citation coverage | Claims flagged by Fact-Checker that still lack sources |
| Frozen zone integrity | Diff check — frozen lines unchanged |

### Custom Rules (LLM-evaluated, marked as "soft")
- "Every claim must have a data point" → LLM pass, flagged as soft constraint
- "Tone must match exemplar" → LLM pass via Stylist

### Constraint Dashboard (Left Panel)

```
✅ Words: 1,423 / 1,500 max
✅ Reading level: 9.2 (target: ≤ 10)
✅ Required sections: 5/5 present
❌ Forbidden terms: "leverage" found on line 34
⚠️ Hedge words: 4.2% (threshold: 3%)
✅ Frozen zones: intact
⚠️ Passive voice: 18% (threshold: 15%)
```

## Source & Research Integration

### Source Ingestion

- Paste URL → fetch + extract key claims with attributions
- Upload PDF → extract text + structured claims
- Reference PKB claims → pulled into document source library
- Manual source entry (title + key finding)

### Citation Flow

1. Drafter or user makes a claim in the document
2. Fact-Checker scans: does this claim have a backing source in the source library?
3. If yes → auto-link (available for footnote/inline citation rendering)
4. If no → flag as annotation: "Unsupported claim — add source or mark as opinion"

### Reference Panel (Left Panel, tab)

```
Sources for this document:
├── [1] "Q2 Revenue Report" (internal) — 3 claims linked
├── [2] arxiv:2401.12345 — 1 claim linked
├── [3] PKB claim #revenue_growth_23 — used in section 2
└── [+] Add source...

Unlinked claims (need sources):
├── Line 34: "reduces cost by 40%" — NO SOURCE
└── Line 89: "industry standard practice" — NO SOURCE
```

## Version Timeline (Not Git — Intent-Aware)

### What a Version Captures

Each version is not just a snapshot — it's a snapshot + the *editorial decision* that produced it:

```
v1 ──── "Initial draft from brief (Planner + Drafter)"
  │       words: 1823, reading_level: 12.3
  │
v2 ──── "Reduced word count, simplified per Critic" (Reducer)
  │       words: 1456, reading_level: 9.8
  │
v3 ──── "User: rewrote section 3 manually"
  │       words: 1502, reading_level: 9.5
  │
v4 ──── "Style pass: aligned tone with exemplar" (Stylist)
          words: 1489, reading_level: 9.4
```

### Operations

- **Compare any two versions** — side-by-side with highlighted changes
- **Show evolution of a section** — "how did section 3 change across versions?"
- **Revert a section** — roll back one section to a prior version without affecting others
- **Branch** — "try two approaches for the intro" → pick winner, discard other

## Genre Templates

### Built-in Templates

Each template provides: required structure, section descriptions, word budget guidance, and common pitfalls.

| Genre | Template structure |
|-------|-------------------|
| Amazon 6-pager | Context → Tenets → Approach → Results/Projections → Key Decisions → Appendix |
| Academic paper | Abstract → Introduction → Related Work → Method → Experiments → Discussion → Conclusion |
| Blog post | Hook → Problem statement → Solution → Examples/Evidence → Call to action |
| Business email | Subject line → BLUF → Context → Ask → Timeline |
| PRD/One-pager | Summary → Problem → Goals/Non-goals → Proposal → Risks → Milestones |
| Technical RFC | Status → Context → Decision → Consequences → Alternatives considered |
| Performance review | Summary → Strengths → Growth areas → Impact examples → Goals |
| Creative short story | Opening hook → Rising action → Conflict peak → Resolution → Resonance |

### Template Behavior

- User selects genre (or system detects from brief)
- Planner agent uses template as scaffold
- Constraint engine enforces required sections
- Template is guidance, not prison — user can deviate with explicit override

## Audience Simulation

### Configuration

```json
{
  "audience_profiles": [
    {
      "name": "VP (primary reader)",
      "reading_time": "2 minutes",
      "expertise": "business strategy, not technical",
      "priorities": "ROI, timeline, risk",
      "style_preference": "BLUF, bullet points, data-driven"
    },
    {
      "name": "Engineering lead (secondary)",
      "reading_time": "10 minutes",
      "expertise": "deep technical",
      "priorities": "feasibility, architecture, dependencies",
      "style_preference": "detailed, precise, show your work"
    }
  ]
}
```

### Reader Simulator Output

```
Reading as: VP (2 minutes)

What I'd take away:
- You want $2M for a new platform. Timeline is 6 months.
- Main risk is team capacity.

What confused me:
- "Event-driven architecture" — what does this mean for my team?
- Section 3 buries the ask. I almost missed it.

Questions I'd ask:
- What happens if we don't do this? (Missing "cost of inaction")
- Who else has tried this approach?

Verdict: I'd ask for a revision before forwarding to my VP.
```

## Revision Memory & Standing Directives

### Problem

Without structured memory, pass 3 undoes pass 1's edits because the agent doesn't remember the earlier intent.

### Solution: Standing Directives

A persistent, ordered list of editorial decisions that the orchestrator re-injects on every pass:

```
Standing directives (in priority order):
1. Total word count ≤ 1500 [HARD - from constraint]
2. Section 3 must include the Q2 revenue data [from pass 2 user feedback]
3. Keep informal tone in the intro — deliberate choice [user override of Stylist]
4. Do NOT merge sections 4 and 5 — they serve different audiences [user rejection of Critic suggestion]
```

Directives are:
- Added when user accepts/rejects a suggestion (captures the *why*)
- Added manually by user ("remember: never use passive voice in this doc")
- Consumed by orchestrator on every pass as constraints
- Editable/deletable by user

## Integration with Existing System

### What Connects Where

| Existing component | Role in writing system |
|-------------------|----------------------|
| **Artefacts** | Document storage, diffing, propose/apply, Cmd+K |
| **DocumentEditingAgent** | Becomes the Stylist agent (guideline-based editing) |
| **PromptWorkflowAgent** | Basis for the multi-pass pipeline orchestration |
| **PKB** | Source library for Fact-Checker; claims = citable sources |
| **Chat** | Right panel agent interaction; context-aware writing instructions |
| **BookCreatorAgent** | Special case of Planner + Drafter for long-form content |
| **Running summary** | Revision memory / standing directives persistence |
| **Message pinning** | Pin key editorial decisions so they survive context truncation |

### New Components Needed

| Component | Purpose |
|-----------|---------|
| `WritingOrchestrator` | Meta-agent: decides next action, loops through agent roles |
| `ConstraintEngine` | Deterministic rule checker (no LLM) |
| `ReaderSimulator` agent | Audience-specific feedback generation |
| `FactChecker` agent | Claim verification against source library |
| `writing_config` on artefacts | Persistent brief, audience, exemplars, constraints |
| `revision_history` with intent | Version timeline beyond raw file saves |
| `standing_directives` store | Ordered editorial decisions that persist across passes |
| Genre template library | Structural scaffolds per writing type |
| Source panel UI | Left panel tab for research/citation management |
| Constraint dashboard UI | Left panel real-time constraint status |

## API Surface (New Endpoints)

```
# Writing config (extends artefacts)
GET    /artefacts/<conv_id>/<art_id>/writing_config
PUT    /artefacts/<conv_id>/<art_id>/writing_config

# Constraint checking (deterministic)
POST   /artefacts/<conv_id>/<art_id>/check_constraints
  → returns constraint dashboard JSON

# Full editing pipeline
POST   /artefacts/<conv_id>/<art_id>/run_pipeline
  body: { mode: "full" | "critique_only" | "style_only" | "reduce" }
  → streams agent actions + proposed changes

# Audience simulation
POST   /artefacts/<conv_id>/<art_id>/simulate_reader
  body: { audience_profile: {...} }
  → returns reader simulation response

# Fact checking
POST   /artefacts/<conv_id>/<art_id>/fact_check
  → returns list of claims with source/no-source status

# Sources
GET    /artefacts/<conv_id>/<art_id>/sources
POST   /artefacts/<conv_id>/<art_id>/sources
  body: { type: "url" | "pdf" | "pkb_claim" | "manual", ... }
DELETE /artefacts/<conv_id>/<art_id>/sources/<source_id>

# Standing directives
GET    /artefacts/<conv_id>/<art_id>/directives
POST   /artefacts/<conv_id>/<art_id>/directives
PUT    /artefacts/<conv_id>/<art_id>/directives/<id>
DELETE /artefacts/<conv_id>/<art_id>/directives/<id>

# Version timeline
GET    /artefacts/<conv_id>/<art_id>/versions
GET    /artefacts/<conv_id>/<art_id>/versions/<v1>/compare/<v2>
POST   /artefacts/<conv_id>/<art_id>/versions/<v>/revert_section
  body: { section_heading: "..." }
```

## Implementation Phases

### Phase 1: Foundation (connect existing pieces)
- Add `writing_config` to artefact metadata
- Implement `ConstraintEngine` (pure Python, no LLM)
- Wire `DocumentEditingAgent` output into artefact propose/apply flow
- Add constraint dashboard to artefact modal UI

### Phase 2: Multi-Agent Pipeline
- Implement `WritingOrchestrator` with role dispatch
- Add Critic agent (separate from Drafter)
- Add Reducer agent
- Implement standing directives (store + inject into orchestrator context)
- Version timeline with intent tracking

### Phase 3: Research & Verification
- Source ingestion (URL → claims extraction)
- PKB integration as source library
- Fact-Checker agent
- Citation panel UI
- Unlinked claims flagging

### Phase 4: Reader Simulation & Polish
- Reader Simulator agent with audience profiles
- Genre template library
- Audience config on writing_config
- Structural mode (outline drag-and-drop + auto-transition adjustment)

### Phase 5: Advanced UX
- Branch-and-merge for alternative phrasings
- Section-level version revert
- Ghost text (conservative, sentence-level only)
- Export to multiple formats (email, slides, docs)
- Annotation system (user + agent notes on passages)

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Over-editing: agent polishes away author's voice | Frozen zones, exemplar-based style, standing directives ("keep X as-is") |
| Infinite loop: orchestrator never satisfied | Hard cap on passes (default 5), "good enough" threshold |
| Context loss in long documents | Section-scoped passes; orchestrator maintains global summary |
| Cost: many LLM calls per document | Model tiering (cheap for checks, expensive for final only); cache repeated constraint checks |
| User overwhelm: too many suggestions | Progressive disclosure — top 5 by impact first, expand on request |
| Hallucinated "improvements" | Fact-Checker; Critic explicitly asks "source?"; deterministic constraint layer catches objective errors |
| Latency: multi-agent = slow | Parallelism where possible (Critic + Fact-Checker concurrent); streaming per stage |

## Success Criteria

A document passes through the system and the user:
1. Never has to re-state a previously accepted/rejected decision
2. Can see at a glance which constraints are met/violated
3. Can trace any sentence back to which pass introduced it and why
4. Gets audience-specific feedback without leaving the editor
5. Finds every claim is either sourced or explicitly flagged
6. Produces output in their target voice, verified against exemplars
7. Completes a full editing cycle in ≤ 5 minutes of active user time (for a 1500-word doc)
