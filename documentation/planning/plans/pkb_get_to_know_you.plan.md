---
name: "PKB Get to Know You — Adaptive Interview for Memory Cold-Start"
overview: "An opt-in, conversational interview feature in the PKB that asks the user adaptive questions to populate their personal knowledge base. Solves the cold-start problem (new users have empty PKB for weeks) while avoiding survey fatigue through gap-aware question generation, free-text answers, standard proposal cards for confirmation, and low-priority claims that naturally yield to richer organic extraction over time."
todos:
  - id: backend-interview-endpoint
    content: "POST /pkb/interview/next_question — generate adaptive question from gap analysis"
    status: pending
  - id: backend-extract-endpoint
    content: "POST /pkb/interview/extract — extract claims from answer using distiller"
    status: pending
  - id: interview-channel-constant
    content: "Add 'interview' to ClaimChannel enum in constants.py"
    status: pending
  - id: ui-interview-section
    content: "Interview UI in PKB modal — question display, answer textarea, inline proposals, progress"
    status: pending
  - id: adaptive-stopping
    content: "Stop logic: 5/session cap, DONE signal, 2 consecutive skips, user Done button"
    status: pending
  - id: gap-detection
    content: "Build domain/topic gap analysis from existing claims for question prompt"
    status: pending
  - id: session-memory
    content: "Track questions asked this session + previously asked across sessions"
    status: pending
  - id: nudge-on-empty
    content: "Show suggestion when PKB has < 10 active claims"
    status: pending
---

# PKB Get to Know You — Adaptive Interview for Memory Cold-Start

## 1. Problem Statement

New users have an empty PKB. The system can't personalize responses until enough claims accumulate through organic chat extraction — which takes days or weeks of active use. Meanwhile, every conversation lacks context that the user would happily provide if asked.

Existing solutions (manual "Add claim" button, text ingestion) require the user to know what to add and how to phrase it. Most users don't.

## 2. Goals

| # | Goal | Success criteria |
|---|------|-----------------|
| G1 | Solve cold-start | User can go from 0 to 15+ useful claims in one 5-minute session |
| G2 | No survey fatigue | Session caps at 5 questions; user can stop anytime; questions feel conversational |
| G3 | Adaptive, not generic | Questions target gaps in what's already known; never re-asks covered topics |
| G4 | Low-friction integration | Reuses existing extraction pipeline and proposal UI; no new claim storage schema |
| G5 | Graceful degradation | Interview claims yield to richer organic extraction over time (lower confidence, supersession) |

### Non-goals

- Replacing organic extraction (this supplements, not replaces)
- Mandatory onboarding (always opt-in)
- Personality quiz / gamification
- Multi-user profiles (stays per-user like all PKB)

## 3. Design

### 3.1 Entry points

1. **Button in PKB Maintenance tab**: "Get to know you" — always available
2. **Cold-start nudge**: When PKB has < 10 active claims AND user opens PKB modal, show a dismissible banner: "Your memory is mostly empty — want me to ask a few questions to get started?"
3. **Slash command**: `/pkb interview` in chat (optional, lower priority)

### 3.2 Session flow

```
User clicks "Get to Know You"
  → System calls POST /pkb/interview/next_question
  → Backend:
      1. Gathers existing claims (grouped by domain)
      2. Gathers previously asked questions (from meta)
      3. Prompts LLM to generate ONE adaptive question
      4. Returns question text (or "DONE" if saturated)
  → UI displays question + answer textarea
  → User types free-text answer (or clicks Skip)
  → System calls POST /pkb/interview/extract {question, answer}
  → Backend:
      1. Runs extraction (reuses ConversationDistiller prompt, adapted)
      2. Returns candidate claims as proposals
  → UI shows inline proposal cards (checkbox per claim, edit button)
  → User confirms/rejects/edits
  → Confirmed claims saved with channel="interview", confidence=0.6
  → Loop: next question (until stopping condition)
```

### 3.3 Question generation

LLM prompt template:

```
You are helping build a personal knowledge base about a user by asking them questions.

WHAT WE ALREADY KNOW (by domain):
{claims_by_domain}

DOMAINS WITH NO COVERAGE: {empty_domains}

QUESTIONS ALREADY ASKED (this session + previous sessions):
{asked_questions}

YOUR TASK: Generate ONE question to learn something new about this user.

Rules:
- Target uncovered or shallow domains first
- Make it conversational (not survey-like, not multiple choice)
- Ask about things that help personalize future interactions:
  preferences, workflows, constraints, background, tools, communication style
- Don't ask about things already well-covered
- One question only. No preamble.
- If nothing useful remains to ask, return exactly: DONE
```

**Domain taxonomy** (used for gap detection, not shown to user):
- `work` — role, team, industry, responsibilities
- `technical` — languages, frameworks, tools, infrastructure
- `preferences` — communication style, detail level, formality
- `workflows` — how they work, processes, routines
- `learning` — what they're studying, interests, goals
- `context` — timezone, location, constraints, availability

These map loosely to PKB `context_domain` values. The LLM doesn't need to classify perfectly — it just needs to see which areas are sparse.

### 3.4 Claim extraction from answers

Uses existing `ConversationDistiller` with adapted prompt:

```
The user was asked: "{question}"
They answered: "{answer}"

Extract factual claims about this user from their answer.
Each claim should be:
- A standalone, self-contained statement about the user
- Specific enough to be useful in future conversations
- Marked as derivation "stated" (user said this directly)

Return claims as a list. If the answer doesn't contain extractable facts, return empty list.
```

Claims get:
- `channel: "interview"` in `meta_json.source`
- `derivation: "stated"`
- `confidence: 0.6` (below the 0.8+ that organic/manual claims get)
- Normal `claim_type` inference (fact/preference/etc.)
- Normal entity/tag enrichment

### 3.5 Adaptive stopping conditions

The session ends when ANY of:
1. User clicks "Done for now"
2. 5 questions answered this session (fatigue cap, configurable)
3. LLM returns "DONE" (coverage saturation)
4. User skips 2 consecutive questions (disengagement)
5. User rejects all proposals from 2 consecutive answers (not getting value)

### 3.6 Cross-session memory

Store in `meta_json` of a lightweight record (or a simple JSON file per user):
```json
{
  "questions_asked": [
    {"question": "...", "answered": true, "session_date": "2026-06-13", "claims_created": 3},
    {"question": "...", "answered": false, "session_date": "2026-06-13", "claims_created": 0}
  ],
  "total_sessions": 2,
  "last_session_date": "2026-06-13"
}
```

On re-entry, the system:
- Passes all previously asked questions to the LLM (avoid repeats)
- Checks which domains now have organic coverage (may skip domains that filled naturally)
- Generates fresh questions for remaining gaps

### 3.7 Long-term claim lifecycle

| Scenario | What happens |
|----------|-------------|
| User says same thing in chat later | Organic extraction creates higher-confidence claim → interview claim gets superseded |
| User's answer was vague ("I do coding") | Low confidence (0.6) → ranks below richer claims; eventually goes dormant if never reinforced |
| User's situation changes | Organic extraction captures new reality; old interview claim decays/gets superseded |
| User never chats about a topic | Interview claim stays at 0.6, still surfaces when relevant (better than nothing) |

No special lifecycle logic needed — existing confidence ranking + supersession + dormancy decay handle everything.

## 4. Implementation

### 4.1 Backend

**Constants** (`truth_management_system/constants.py`):
- Add `INTERVIEW = "interview"` to `ClaimChannel` enum

**New endpoint** (`endpoints/pkb.py`):

```python
@pkb_bp.route("/pkb/interview/next_question", methods=["POST"])
```
- Input: `{session_id?: string}` (optional, for tracking)
- Builds gap analysis from `api.claims.list()` grouped by domain
- Loads interview history from user meta
- Calls LLM with question-generation prompt
- Returns: `{question: string, domain_hint: string}` or `{done: true, reason: string}`

```python
@pkb_bp.route("/pkb/interview/extract", methods=["POST"])
```
- Input: `{question: string, answer: string}`
- Runs extraction via adapted distiller prompt
- Returns proposals (same format as `propose_updates`)
- On confirm: saves with `channel="interview"`, `confidence=0.6`

**Interview history** (`truth_management_system/interface/structured_api.py`):
- `get_interview_history()` — reads from user-level meta (stored in `pkb_user_meta` table or a JSON sidecar)
- `record_interview_question(question, answered, claims_created)` — appends to history

### 4.2 Frontend (`interface/pkb-manager.js`)

New section triggered from Maintenance tab button:

```javascript
function startInterview() { ... }    // Opens interview UI, calls next_question
function submitAnswer() { ... }      // Calls extract, shows proposals inline
function skipQuestion() { ... }      // Records skip, gets next question
function endInterview() { ... }      // Closes UI, shows summary
```

UI structure:
- Question display (styled as a chat bubble from the system)
- Answer textarea (auto-resize)
- Skip / Answer buttons
- Inline proposal cards (reuse existing `.proposal-checkbox` pattern)
- Progress footer: "3/5 questions · 7 facts learned"
- "Done for now" always visible

### 4.3 Cold-start nudge (`interface/pkb-manager.js`)

In `openPKBModal()`:
```javascript
$.get('/pkb/health', function(resp) {
    if (resp.total_claims < 10 && !localStorage.getItem('pkb-interview-dismissed')) {
        $('#pkb-interview-nudge').show();
    }
});
```

Dismissible banner with "Get to know you" CTA + "Don't show again" link.

## 5. Files touched

| File | Change |
|------|--------|
| `truth_management_system/constants.py` | Add `INTERVIEW` to `ClaimChannel` |
| `truth_management_system/interface/structured_api.py` | `get_interview_history()`, `record_interview_question()`, `generate_interview_question()`, `extract_interview_answer()` |
| `truth_management_system/llm_helpers.py` | `generate_interview_question()` prompt (or inline in structured_api) |
| `endpoints/pkb.py` | 2 new routes: `/pkb/interview/next_question`, `/pkb/interview/extract` |
| `interface/pkb-manager.js` | Interview UI section, startInterview/submitAnswer/skipQuestion/endInterview |
| `interface/interface.html` | Button in Maintenance tab, nudge banner, interview section container |

## 6. API surface (3-surface parity)

| Surface | Endpoint/Tool |
|---------|--------------|
| REST | `POST /pkb/interview/next_question`, `POST /pkb/interview/extract` |
| MCP | `pkb_interview_question` (full tier), `pkb_interview_extract` (full tier) |
| LLM tool | `pkb_interview_question` — allows the in-chat LLM to proactively ask if context seems thin |

The MCP/LLM tool exposure enables external editors (Claude Code, OpenCode) to run the interview flow in their own UI — they call `next_question`, present it to the user, call `extract` with the answer.

## 7. Configuration

| Config key | Default | Description |
|------------|---------|-------------|
| `interview_max_questions_per_session` | 5 | Fatigue cap |
| `interview_claim_confidence` | 0.6 | Confidence for interview-sourced claims |
| `interview_skip_threshold` | 2 | Consecutive skips before auto-stop |
| `interview_nudge_threshold` | 10 | Show nudge when active claims < this |
| `interview_cooldown_days` | 7 | Don't show nudge again for N days after dismissal |

## 8. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Generic/useless questions | Gap analysis + "questions already asked" context prevents repeats; domain taxonomy guides toward actionable info |
| User gives minimal answers | Extraction handles gracefully (0 claims from "idk") → counts as skip toward threshold |
| LLM hallucinates claims from answer | Standard proposal UI — user must confirm each claim before save |
| Interview claims pollute retrieval | Lower confidence (0.6) + `channel: "interview"` filter + natural supersession |
| Feature unused | Opt-in only, zero cost when ignored; nudge is dismissible |
| Question feels intrusive | User can skip any question; conversational tone in prompt; no mandatory fields |

## 9. Implementation order

1. **Add `interview` channel constant** — trivial, no dependencies
2. **Interview history storage** — lightweight (JSON in user meta or dedicated table row)
3. **Question generation endpoint** — LLM prompt + gap analysis
4. **Answer extraction endpoint** — reuse distiller with adapted prompt
5. **UI: interview section** — question display, textarea, proposal cards
6. **UI: cold-start nudge** — conditional banner
7. **MCP/LLM tool registration** — mechanical, same pattern as other tools

Steps 1–4 are backend (~2h). Step 5 is the main UI work (~2h). Steps 6–7 are quick (~30min each).

## 10. Future extensions (not in v1)

- **Periodic check-in**: "It's been 3 months since you said X — still accurate?" (ties into fading memories)
- **Topic-triggered questions**: When user enters a new domain (first conversation about finance), proactively ask one question about their finance background
- **Shared question sets**: Curated question packs for specific roles ("Developer onboarding", "Manager context")
- **Import from other sources**: "I see you connected GitHub — want me to infer your tech stack from your repos?"
