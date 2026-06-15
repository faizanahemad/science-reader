# Writing System: UX Design & User Flows

## Design Philosophy

1. **Writing is thinking** — the UI must never rush the user. No aggressive autocomplete, no flashing suggestions. Quiet until asked.
2. **Progressive disclosure** — beginners see a simple editor with a chat panel. Power users discover structural tools, constraints, pipelines.
3. **Context without clutter** — information about the document (constraints, sources, version history) is available on demand but never competes with the writing surface.
4. **Trust through transparency** — every AI change shows what changed and why. The user never wonders "what did it do to my document?"
5. **The document is the source of truth** — chat is ephemeral, the document persists. All decisions materialize as document state, not chat history.

## Entry Points

### How Users Arrive at the Writing System

| Entry | Context | Initial state |
|-------|---------|---------------|
| "New writing project" button | Fresh start | Brief wizard → empty editor with config |
| Open existing artefact + enable writing mode | Existing content | Editor with content, no config yet → prompt to configure |
| Chat command: `/write <brief>` | From conversation | Creates artefact, opens writing studio, pre-fills brief |
| "Edit as Artefact" on long assistant answer | Existing AI output | Editor with content seeded from answer, suggest config |
| Template gallery | Browsing | Pick genre → pre-configured structure + constraints |

## Screen Layout

### Default (Compact) — Mobile & Small Screens

```
┌─────────────────────────────────┐
│  [≡ Structure] [Editor] [◉ AI]  │  ← tab bar (only one panel visible)
├─────────────────────────────────┤
│                                 │
│        Active panel content     │
│                                 │
├─────────────────────────────────┤
│  Constraint bar (always visible)│  ← single row: "1,423 words | Grade 9 | ✓ 5/5 sections"
└─────────────────────────────────┘
```

### Desktop (Full) — Three Panels

```
┌────────────────┬──────────────────────────┬──────────────────┐
│  Structure     │  Editor                  │  AI Panel        │
│  (collapsible) │  (always present)        │  (collapsible)   │
│  ~250px        │  flex                    │  ~350px          │
├────────────────┴──────────────────────────┴──────────────────┤
│  Status bar: constraints + version indicator + save status    │
└──────────────────────────────────────────────────────────────┘
```

## Panel Details

### Left Panel: Structure

**Tabs at top:** Outline | Sources | Versions

#### Outline Tab (default)

```
📄 Q3 Strategy One-Pager
├── § Summary ────────── 142w ✓
├── § Problem ────────── 287w ✓
├── § Proposal ───────── 456w ⚠️ (over budget)
│   ├── § Technical Approach ── 234w
│   └── § Timeline ──────────── 222w
├── § Risks ──────────── 198w ✓
└── § Ask ────────────── 89w ✓
    
Total: 1,172w / 1,500 max

[+ Add section]  [⚙ Edit structure]
```

**Interactions:**
- Click section → editor scrolls to it
- Drag section → reorder (agent auto-fixes transitions on drop)
- Right-click → section operations: expand, compress, rewrite, split, merge, freeze
- Word count badges change color: green (on budget), yellow (±20%), red (over)
- Section status icons: draft (pencil), reviewed (eye), approved (check), frozen (lock)

#### Sources Tab

```
📚 Sources (4)

[1] Q2 Revenue Report (internal)
    3 claims linked | Added Jun 12
    
[2] arxiv:2401.12345 — "Scaling Laws for..."
    1 claim linked | Added Jun 13

[3] PKB: revenue_growth_claim_23
    Used in § Problem | Auto-linked

[4] Competitor Analysis (manual)
    0 claims linked

─────────────────────────────
⚠️ 2 unsourced claims in document
    → Line 34: "reduces cost by 40%"
    → Line 89: "industry standard"
    
[+ Add source]  [🔍 Find sources for unsourced claims]
```

**Interactions:**
- Click source → highlights where it's used in editor
- Click unsourced claim → jumps to it in editor
- "Find sources" → agent searches PKB + web for supporting evidence

#### Versions Tab

```
📋 Version Timeline

v4 ── now ─────────────────────────
    "Style alignment pass" (Stylist)
    1,489w | Grade 9.4
    
v3 ── 12 min ago ──────────────────
    "User: rewrote section 3"
    1,502w | Grade 9.5

v2 ── 18 min ago ──────────────────
    "Reduced word count" (Reducer)
    1,456w | Grade 9.8

v1 ── 25 min ago ──────────────────
    "Initial draft from brief"
    1,823w | Grade 12.3

[Compare v1 ↔ v4]  [Branch from here]
```

**Interactions:**
- Click any version → side-by-side diff with current
- "Compare" → pick any two versions
- "Branch" → create alternative version (for trying different approaches)
- Hover → shows constraint snapshot at that point

### Center Panel: Editor

#### Editor Chrome

```
┌──────────────────────────────────────────────────────┐
│ [📝 Edit] [👁 Preview] [⚡ Diff]   [Genre: One-pager ▾] [Audience: VP ▾]  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  # Summary                                           │
│                                                      │
│  We propose investing $2M in a new event-driven      │
│  platform that will reduce operational costs by 40%  │  ← ⚠️ unsourced (subtle underline)
│  and improve team velocity by 3x over 6 months.     │
│                                                      │
│  # Problem                                           │
│                                                      │
│  Current infrastructure handles 10K req/s but our    │
│  projected Q4 load is 45K req/s. Without action...   │
│                                                      │
│  ┌─── 🔒 FROZEN ZONE ──────────────────────────┐    │
│  │ "Per legal review dated May 15, the existing │    │
│  │ SLA guarantees must be maintained..."        │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  📌 [annotation] Need data point for Q4 projection   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

#### Editor Interactions

**Selection → Action Menu (floating toolbar):**
```
┌─────────────────────────────────────────────────┐
│ [✨ Rewrite] [✂️ Shorten] [📝 Expand] [🎨 Restyle] [🔍 Fact-check] [📌 Annotate] [❄️ Freeze] │
└─────────────────────────────────────────────────┘
```

**Cmd+K Inline Edit:**
```
┌────────────────────────────────────────┐
│ 💡 Editing lines 12-18                 │
│ ┌────────────────────────────────────┐ │
│ │ Make this more concise and add the │ │
│ │ Q2 data point_                     │ │
│ └────────────────────────────────────┘ │
│ [☐ Deep context]  [Submit ⌘↩]  [Esc]  │
└────────────────────────────────────────┘
```

**Inline Annotations (gutter):**
```
  23 │  ...reduces costs by 40%...        📌 "Need source" (user)
  24 │                                     🤖 "Unsupported claim" (Fact-Checker)
  67 │  ...so we should totally go for...  🎨 "Tone drift: informal" (Stylist)
```

**Diff View (after propose_edits or pipeline run):**
```
┌──────────────────────────────────────────────┐
│  Proposed changes (3):                       │
│                                              │
│  [☑] Line 12: "leverage" → "use"            │  ← accept individually
│      Reason: forbidden term                  │
│                                              │
│  [☑] Lines 34-38: Rewrote for clarity        │
│      ┌─ Before ──────────────────────────┐   │
│      │ The system which we are proposing │   │
│      │ would theoretically reduce...     │   │
│      ├─ After ───────────────────────────┤   │
│      │ The proposed system reduces...    │   │
│      └───────────────────────────────────┘   │
│                                              │
│  [☐] Lines 89-92: Added citation             │
│      "According to Gartner (2024)..."        │
│                                              │
│  [Accept selected (2)] [Accept all] [Reject all] │
└──────────────────────────────────────────────┘
```

### Right Panel: AI Panel

**Tabs at top:** Chat | Brief | Config

#### Chat Tab (default)

Context-aware conversational interface. Always knows what document you're editing, what's selected, what version you're on.

```
┌──────────────────────────────────┐
│  💬 Writing Assistant            │
│                                  │
│  ┌──────────────────────────┐    │
│  │ 🤖 I notice section 3 is │    │
│  │ over its word budget by   │    │
│  │ 120 words. Want me to     │    │
│  │ tighten it?               │    │
│  │                           │    │
│  │ [Yes, reduce] [Show me    │    │
│  │  what you'd cut first]    │    │
│  └──────────────────────────┘    │
│                                  │
│  ┌──────────────────────────┐    │
│  │ 👤 Can you also check if │    │
│  │ the tone matches my       │    │
│  │ exemplars? The intro      │    │
│  │ feels too casual.         │    │
│  └──────────────────────────┘    │
│                                  │
│  ┌──────────────────────────┐    │
│  │ 🤖 Running Stylist on    │    │
│  │ the intro...              │    │
│  │                           │    │
│  │ Found 3 tone issues:      │    │
│  │ • L5: "pretty much" →    │    │
│  │   "substantially"         │    │
│  │ • L8: "gonna" → "will"   │    │
│  │ • L12: casual metaphor   │    │
│  │                           │    │
│  │ [Apply all] [Review in    │    │
│  │  diff view]               │    │
│  └──────────────────────────┘    │
│                                  │
│  ┌────────────────────────────┐  │
│  │ Type a writing instruction │  │
│  │ or ask for feedback...     │  │
│  └────────────────────────────┘  │
│  [📋 Run full edit pass]         │
│  [👁 Simulate reader]            │
│  [✅ Check constraints]          │
└──────────────────────────────────┘
```

**Quick actions (bottom of chat):**
- "Run full edit pass" → triggers orchestrator loop, streams progress
- "Simulate reader" → opens audience selector, then runs simulation
- "Check constraints" → instant deterministic check, shows dashboard

#### Brief Tab

The persistent "north star" for this document. Visible to all agents on every pass.

```
┌──────────────────────────────────┐
│  📋 Brief                        │
│                                  │
│  Goal:                           │
│  Convince leadership to invest   │
│  $2M in event-driven platform.   │
│                                  │
│  Key messages (must appear):     │
│  ✓ 40% cost reduction            │
│  ✓ 3x team velocity              │
│  ✗ Risk mitigation strategy      │  ← not yet in doc
│                                  │
│  Audience: VP (2 min read)       │
│  Genre: Business one-pager       │
│  Tone: Confident, data-driven    │
│                                  │
│  ─── Standing directives ───     │
│  1. Keep ≤ 1500 words            │
│  2. Section 3: include Q2 data   │
│  3. Intro tone is intentionally  │
│     informal — don't "fix" it    │
│                                  │
│  [Edit brief] [+ Add directive]  │
└──────────────────────────────────┘
```

**Key messages** auto-check: system scans document to confirm each key message appears. Shows ✓/✗ in real-time.

#### Config Tab

Settings that persist with the document.

```
┌──────────────────────────────────┐
│  ⚙️ Writing Config               │
│                                  │
│  Genre: [Business one-pager ▾]   │
│  Template: [Amazon 6-pager  ▾]   │
│                                  │
│  ─── Constraints ───             │
│  Max words: [1500]               │
│  Min words: [800]                │
│  Reading level: [≤ 10]           │
│  Required sections:              │
│    [Summary, Problem, Proposal,  │
│     Risks, Ask]                  │
│  Forbidden terms:                │
│    [synergy, leverage, paradigm] │
│                                  │
│  ─── Style Exemplars ───         │
│  [exemplar_1.md] [×]            │
│  [exemplar_2.md] [×]            │
│  [+ Add exemplar]               │
│                                  │
│  ─── Guidelines ───              │
│  [brand_voice.md] [×]           │
│  [writing_standards.md] [×]     │
│  [+ Add guideline]              │
│                                  │
│  ─── Audience Profiles ───       │
│  [VP (primary)] [Edit]          │
│  [Eng Lead (secondary)] [Edit]  │
│  [+ Add audience]               │
│                                  │
└──────────────────────────────────┘
```

### Status Bar (Always Visible)

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1,423w / 1,500 │ Grade 9.2 │ ✓ Sections 5/5 │ ⚠️ 1 forbidden term │ v4 │ Saved ✓ │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Clicking any constraint → scrolls to the violation in the editor.

## User Flows

### Flow 1: New Document from Brief

```
User clicks "New writing project"
    │
    ▼
┌─────────────────────────────────┐
│  Brief Wizard (modal)           │
│                                 │
│  What are you writing?          │
│  [                            ] │
│  [Convince my VP to fund the  ] │
│  [new platform project        ] │
│                                 │
│  Genre: [Auto-detect ▾]        │
│  (detected: Business one-pager) │
│                                 │
│  Audience: [               ]    │
│  [VP, 2-minute reader, cares  ] │
│  [about ROI and timeline      ] │
│                                 │
│  Word budget: [1500]            │
│                                 │
│  Style reference (optional):    │
│  [Drop a sample paragraph]      │
│                                 │
│  [Create document →]            │
└─────────────────────────────────┘
    │
    ▼
System creates artefact with writing_config populated
    │
    ▼
Planner agent generates outline:
    "Here's a proposed structure based on your brief and the
     one-pager template. Review and adjust before I draft."
    │
    ▼
User reviews outline in Structure panel
    - Drags "Risks" before "Proposal" 
    - Adds a section: "Cost of Inaction"
    - Adjusts word budgets
    │
    ▼
User clicks "Draft this" or tells chat "Go ahead and write it"
    │
    ▼
Drafter agent fills sections one by one (streaming)
    - Each section appears in editor as it's written
    - Structure panel updates word counts live
    - Constraint bar updates in real-time
    │
    ▼
Draft complete → constraint check auto-runs
    - Status bar shows: 1,823w / 1,500 (❌ over)
    - Agent proactively suggests: "Over budget by 323 words. Run Reducer?"
    │
    ▼
User: "Yes, but don't touch the Summary"
    │
    ▼
Standing directive added: "Summary is frozen for reduction"
Reducer runs on all sections except Summary
    - Diff view shows proposed cuts
    - User accepts 4/5 suggestions, rejects 1
    │
    ▼
Constraint check: 1,478w ✓ | Grade 9.8 ✓ | All sections ✓
Agent: "Looking good. Want me to run a style check against your exemplars?"
```

### Flow 2: Iterative Editing (Existing Document)

```
User opens existing artefact, enables writing mode
    │
    ▼
System: "No writing config detected. Want to set up a brief?"
User: "Yes" → Brief wizard (lighter version, pre-fills from content analysis)
    │
    ▼
User selects lines 34-52 in editor
    │
    ▼
Floating toolbar appears: [✨ Rewrite] [✂️ Shorten] [📝 Expand] ...
    │
    ▼
User clicks "Rewrite"
    │
    ▼
Chat panel activates:
    "What should change about this section? (Or I can suggest improvements.)"
    │
    ▼
User: "Make it more persuasive, add a concrete example"
    │
    ▼
Drafter rewrites selection → Diff view shows before/after
    │
    ▼
User reviews:
    - Accepts the persuasive restructuring
    - Rejects the added example ("wrong example, I'll add my own")
    │
    ▼
Standing directive auto-added: "User will provide example for section 2"
Annotation added at line 38: "TODO: add user's own example here"
    │
    ▼
Version created: v3 — "Rewrote lines 34-52 for persuasiveness (Drafter)"
```

### Flow 3: Full Edit Pass (Pipeline Mode)

```
User clicks "Run full edit pass" in chat panel
    │
    ▼
┌─────────────────────────────────────────┐
│  Pipeline Configuration (inline modal)  │
│                                         │
│  Passes to include:                     │
│  [✓] Critique (find issues)            │
│  [✓] Style check (match exemplars)     │
│  [✓] Fact check (verify claims)        │
│  [ ] Reduce (cut word count)           │
│  [✓] Reader simulation                 │
│                                         │
│  Max passes: [3]                        │
│  Audience for simulation: [VP ▾]       │
│                                         │
│  [Run pipeline →]                       │
└─────────────────────────────────────────┘
    │
    ▼
Pipeline streams progress in chat panel:

    🔄 Pass 1/3: Running Critic...
    
    Critic found 4 issues:
    • ⚠️ Section 3: claim without evidence (line 67)
    • ⚠️ Section 2: redundant paragraph (lines 28-35)  
    • 💡 Missing "cost of inaction" framing
    • 💡 Conclusion doesn't reference the ask amount
    
    🔄 Pass 1/3: Running Stylist...
    
    Stylist found 2 tone issues:
    • Line 12: register too informal for VP audience
    • Line 45: passive construction weakens the argument
    
    🔄 Pass 1/3: Running Fact-Checker...
    
    Fact-Checker results:
    • ✓ "10K req/s current" — sourced (Q2 Report)
    • ✗ "40% cost reduction" — NO SOURCE
    • ✓ "6 month timeline" — sourced (project plan)
    
    ────────────────────────────
    
    📊 Pass 1 complete. 6 issues found.
    [View all in diff] [Fix automatically] [I'll fix manually]
    │
    ▼
User: "Fix automatically, but show me what you'd do first"
    │
    ▼
    🔄 Pass 2/3: Applying fixes...
    
    Diff view opens with 6 proposed changes (priority-ranked):
    
    Priority 1 (high impact):
    [☑] Add "cost of inaction" paragraph to section 2
    [☑] Add evidence request annotation for "40% claim"
    
    Priority 2 (style):
    [☑] Line 12: "pretty solid bet" → "strong investment"
    [☑] Line 45: passive → active voice
    
    Priority 3 (cleanup):
    [☐] Remove redundant paragraph (lines 28-35)
    [☐] Strengthen conclusion with $ figure
    
    [Apply selected (4)] [Apply all (6)]
    │
    ▼
User applies 4, skips 2 ("I want that redundant paragraph, it provides context")
    │
    ▼
Standing directive added: "Keep context paragraph at lines 28-35"
    │
    ▼
    🔄 Pass 3/3: Reader Simulation...
    
    👤 Reading as: VP (2 minutes)
    
    "I get it — you want $2M for infrastructure. The 'cost of
     inaction' framing is compelling. But I'm not sold on the
     timeline. 6 months feels optimistic for a team of 4."
    
    Questions I'd ask:
    • What's the team plan? Hire or redirect?
    • What's Plan B if it takes 9 months?
    • Who's the exec sponsor?
    
    ────────────────────────────
    ✅ Pipeline complete (3 passes).
    Constraint status: all green.
    
    [Save as final] [One more pass] [Done]
```

### Flow 4: Audience Simulation (On Demand)

```
User clicks "Simulate reader" in chat panel
    │
    ▼
┌─────────────────────────────────┐
│  Select audience:               │
│                                 │
│  [● VP (primary)]              │
│  [○ Engineering Lead]          │
│  [○ Custom...]                 │
│                                 │
│  Reading mode:                  │
│  [● Quick skim (2 min)]       │
│  [○ Careful read (10 min)]    │
│  [○ Hostile reviewer]         │
│                                 │
│  [Simulate →]                   │
└─────────────────────────────────┘
    │
    ▼
Reader Simulator output in chat:

    👤 VP — Quick Skim (2 minutes)
    
    ═══ What I read ═══
    Summary (fully), Problem (skimmed), Proposal heading +
    first sentence, jumped to Ask.
    
    ═══ My takeaway ═══
    "Team wants $2M for a new platform. 6 months. Seems
    reasonable but I want to know who else tried this."
    
    ═══ What I missed (because skimming) ═══
    • The risk mitigation strategy (buried in paragraph 3 of Risks)
    • The Q2 data point (mid-paragraph, not highlighted)
    
    ═══ Suggestions for this audience ═══
    • Bold or bullet the risk mitigation — it's a strength
    • Pull Q2 data into a callout box or the Summary
    • Add a one-liner: "Similar approach at [Company X] saved Y%"
    
    [Apply suggestions] [Try different audience]
```

### Flow 5: Cmd+K Inline Quick Edit

```
User selects a paragraph, hits Cmd+K
    │
    ▼
Overlay appears anchored below selection:
┌──────────────────────────────────────┐
│ 💡 Editing lines 45-52              │
│ ┌──────────────────────────────────┐ │
│ │ rewrite as bullet points, keep   │ │
│ │ the data but cut the narrative_  │ │
│ └──────────────────────────────────┘ │
│ [☐ Deep context] [☐ Use guidelines]  │
│ [Submit ⌘↩]  [Cancel: Esc]          │
└──────────────────────────────────────┘
    │
    ▼ (Cmd+Enter)
    
Loading... (1-3s)
    │
    ▼
Inline diff appears in editor (ghost overlay):

    ┌─ Original ──────────────────────────────────┐
    │ The current platform, which was built in     │
    │ 2019, handles approximately 10,000 requests  │
    │ per second. However, our projections for Q4  │
    │ indicate that we will need to handle roughly │
    │ 45,000 requests per second, which represents │
    │ a 4.5x increase over our current capacity.  │
    └─────────────────────────────────────────────┘
    
    ┌─ Proposed ──────────────────────────────────┐
    │ • Current capacity: 10K req/s (built 2019)  │
    │ • Q4 projected load: 45K req/s              │
    │ • Gap: 4.5x beyond current capacity         │
    └─────────────────────────────────────────────┘
    
    [✓ Accept] [✗ Reject] [↻ Regenerate]
    │
    ▼
User hits ✓ → change applied, version created
```

### Flow 6: Source-Driven Writing (Research → Draft)

```
User starts a new technical document
    │
    ▼
Before writing, user adds sources:
    - Pastes 3 paper URLs
    - Drags a PDF into the Sources panel
    - Tags 2 PKB claims as relevant
    │
    ▼
System ingests sources (background):
    - Extracts key claims from each
    - Builds a source library with searchable claims
    │
    ▼
Sources panel shows:
    📚 Sources (5) — 23 extractable claims
    │
    ▼
User writes brief: "Literature review covering approaches to X"
Planner generates outline with section headings
    │
    ▼
User: "Draft with citations from my sources"
    │
    ▼
Drafter writes each section:
    - Pulls relevant claims from source library
    - Attributes: "According to Smith et al. (2024) [1]..."
    - Marks claims without source backing: "[citation needed]"
    │
    ▼
Fact-Checker auto-runs post-draft:
    - 18/20 claims sourced ✓
    - 2 claims flagged: "no source in library supports this"
    │
    ▼
Editor shows:
    - Sourced claims: subtle green underline
    - Unsourced claims: orange underline + gutter annotation
    │
    ▼
User can:
    [Add source for this claim] → opens source search
    [Mark as author's opinion] → removes flag, adds "(in our view)" prefix
    [Remove claim] → deletes the sentence
```

### Flow 7: Collaborative Annotations Workflow

```
User is reviewing their own draft and spots issues:
    │
    ▼
Selects text at line 23, clicks 📌 Annotate:
    "This needs a real example — ask marketing for the case study"
    │
    ▼
Annotation appears in gutter: 📌 (user, unresolved)
    │
    ▼
Later, user runs Critic pass:
    │
    ▼
Critic adds its own annotations:
    🤖 Line 45: "This claim contradicts section 2 line 12"
    🤖 Line 67: "Unclear antecedent — what does 'it' refer to?"
    │
    ▼
User can view all annotations:

┌─────────────────────────────────────────┐
│  📌 Annotations (5)                     │
│                                         │
│  Unresolved:                            │
│  L23 📌 "Need case study from mktg"     │
│  L45 🤖 "Contradicts section 2"         │
│  L67 🤖 "Unclear antecedent"            │
│                                         │
│  Resolved:                              │
│  L12 📌 "Add data" → resolved v3        │
│  L34 🤖 "Too informal" → fixed v4       │
│                                         │
│  [Resolve selected] [Ask AI to fix all] │
└─────────────────────────────────────────┘
    │
    ▼
User: "Fix the two AI annotations, I'll handle mine"
    │
    ▼
Agent fixes L45 (adds clarifying connector) and L67 (replaces pronoun)
Annotations marked resolved with link to the version that fixed them
```

### Flow 8: Branch-and-Compare (Alternative Phrasings)

```
User is unhappy with the intro but not sure what direction to go
    │
    ▼
Right-clicks § Summary in outline → "Try alternatives"
    │
    ▼
┌─────────────────────────────────────────┐
│  Generate alternatives for: Summary     │
│                                         │
│  Approaches:                            │
│  [✓] Data-first (lead with numbers)    │
│  [✓] Story-first (lead with problem)   │
│  [ ] Question-first (rhetorical hook)   │
│  [ ] Custom: [                        ] │
│                                         │
│  [Generate alternatives →]              │
└─────────────────────────────────────────┘
    │
    ▼
System generates 2 alternatives in parallel
    │
    ▼
Editor enters split view:

┌────────────────┬────────────────┬────────────────┐
│  Current       │  Alt A:        │  Alt B:        │
│                │  Data-first    │  Story-first   │
│                │                │                │
│  We propose    │  $2.3M in Q2   │  Last Tuesday, │
│  investing...  │  was lost to   │  our platform  │
│                │  downtime...   │  crashed for   │
│                │                │  47 minutes... │
│                │                │                │
│ [Keep current] │ [Use this ✓]  │ [Use this]     │
└────────────────┴────────────────┴────────────────┘
    │
    ▼
User picks Alt A → becomes new Summary
Standing directive: "Intro uses data-first hook — maintain this in future passes"
Version: v5 — "Replaced Summary with data-first alternative (user choice)"
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd+K | Inline edit (selection or whole doc) |
| Cmd+Shift+K | Run constraint check |
| Cmd+/ | Toggle annotation on selection |
| Cmd+D | Quick duplicate section |
| Cmd+Shift+R | Run full edit pipeline |
| Cmd+1/2/3 | Switch panels (Structure/Editor/AI) |
| Cmd+B | Toggle brief panel |
| Cmd+Shift+S | Simulate reader |
| Esc | Dismiss overlays, cancel in-progress actions |
| Cmd+Z | Undo (within version) |
| Cmd+Shift+Z | Undo entire version (revert to previous) |

## Visual Design Principles

### Color System for Annotations

| Color | Meaning |
|-------|---------|
| Subtle green underline | Sourced claim (has citation) |
| Orange underline | Unsourced claim (needs citation) |
| Red underline | Forbidden term or hard constraint violation |
| Purple gutter dot | Agent annotation |
| Blue gutter dot | User annotation |
| Grey background | Frozen zone |
| Yellow highlight (fading) | Recently changed text (fades after 5s) |

### Information Density Levels

**Minimal** (focused writing): Editor only, thin status bar. No panels.
**Standard** (editing): Editor + AI panel. Structure available via toggle.
**Full** (review/pipeline): All three panels + diff view.

User controls density via panel toggles. System suggests escalation:
- "Your document has 5 constraint violations. Open Structure panel to see details?"

### Motion & Feedback

- Proposed changes slide in from the right (diff overlay)
- Accepted changes flash green briefly, then settle
- Rejected changes flash red, slide out
- Constraint violations pulse once when newly triggered
- Pipeline progress uses a subtle progress ring on the "Run pipeline" button (not a modal)

## Mobile UX

On mobile, the system collapses to:
- Swipeable tabs: Editor | AI | Structure
- Editor is primary (full screen by default)
- Swipe right → Structure (outline, constraints)
- Swipe left → AI chat
- Floating action button: Cmd+K equivalent (tap to open instruction input)
- Status bar always visible at bottom
- No split views — alternatives shown sequentially in a card carousel

## Accessibility

- All annotations readable by screen readers (aria-labels with full text)
- Keyboard navigation for all panel operations (Tab + arrow keys)
- High contrast mode: constraint colors use patterns in addition to color
- Screen reader announces constraint status changes and pipeline progress
- Focus management: after accepting a change, focus returns to next proposal (not top of page)

## What This Differs From

| System | How writing studio differs |
|--------|--------------------------|
| Google Docs + Gemini | Multi-agent roles (not one AI), persistent brief, deterministic constraints, version intent |
| Notion AI | Structural editing (drag sections), audience simulation, source management |
| Grammarly | Beyond grammar — structural critique, persuasion analysis, audience modeling |
| Cursor/VSCode Copilot | No aggressive autocomplete, spatial structure panel, reader simulation, brief-driven |
| ChatGPT canvas | Multi-pass pipeline with orchestrator, constraint engine, exemplar-driven style, revision memory |
| Jasper/Copy.ai | Not template-fill — genuine editing collaboration with critique and fact-checking |

The key differentiator: **this system has opinions about what makes your document good** (via brief, constraints, audience, exemplars) and **actively verifies against them** — rather than just executing instructions blindly.
