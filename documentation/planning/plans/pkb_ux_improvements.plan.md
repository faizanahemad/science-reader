---
name: PKB UX Improvements — Capture, Organization, Retrieval, Maintenance & Transparency
overview: "A comprehensive set of UX improvements to the PKB system covering all user-journey phases: smarter capture (extraction-based save, dedup at proposal, STM visibility, import button), bulk organization (multi-select, create-from-selection, auto-clustering), retrieval refinement (domain/context scoping, negative feedback, STM visibility in cards), richer interaction (summarize command, enhanced NL search results), proactive maintenance (background cleanup, fading memories, undo, dedup highlighting), and transparency (health dashboard, why-tooltips, promotion visibility). All new capabilities exposed on REST, LLM tool-calling, AND MCP surfaces for external AI editor compatibility."
todos:
  - id: stm-mcp-tools
    content: "Register existing STM endpoints (get, promote, dismiss) as MCP + LLM tools — currently REST-only"
    status: pending
  - id: save-to-memory-extraction
    content: "Make 'Save to Memory' button and text-selection context menu run the extraction pipeline (propose_updates style) instead of opening modal with raw text"
    status: pending
  - id: dedup-at-proposal
    content: "Show 'Similar existing memory' warning on proposal cards by running fuzzy match against existing claims during propose_updates"
    status: pending
  - id: import-button-pkb-modal
    content: "Add visible 'Import' button/tab in PKB modal for text/document bulk ingestion"
    status: pending
  - id: stm-capture-toast
    content: "Show subtle non-blocking toast when STM items are silently captured (e.g. '2 context items remembered')"
    status: pending
  - id: bulk-organization
    content: "Add multi-select checkboxes to claims list + bulk actions toolbar (Add to Context, Tag, Change Type, Delete)"
    status: pending
  - id: create-context-from-selection
    content: "Allow creating a new context from selected claims (multi-select → 'Create Context' action)"
    status: pending
  - id: auto-clustering-suggestions
    content: "Periodic/on-demand clustering: identify untagged/ungrouped claims that share entities/topics, suggest grouping"
    status: pending
  - id: negative-feedback-retrieval
    content: "Add thumbs-down on retrieved memories in PKB Retrieval Details; store as contextual negative signal for rerank tuning"
    status: pending
  - id: stm-in-audit-details
    content: "Make STM items visible in the PKB Retrieval Details collapsible section with distinct 'STM' badge"
    status: pending
  - id: retrieval-scoping
    content: "Add domain/context/entity/tag scoping filter in chat settings to restrict PKB retrieval to a subset"
    status: pending
  - id: nl-search-rich-results
    content: "Enhance NL agent search results to show confidence, provenance badge, last-accessed age, and friendly ID"
    status: pending
  - id: pkb-summarize-command
    content: "Add '/pkb summarize <topic>' NL command — collects related claims via search and generates a synthesis"
    status: pending
  - id: proactive-cleanup-nudge
    content: "Background job runs cleanup analysis after N new claims or X days since last cleanup; shows badge/notification when results available"
    status: pending
  - id: fading-memories-section
    content: "Show 'Fading Memories' in Maintenance tab — claims approaching staleness with Reinforce/Dismiss buttons; stale claims excluded from retrieval"
    status: pending
  - id: dedup-highlight-matching
    content: "In dedup suggestion UI, highlight the overlapping/matching text between candidate duplicates"
    status: pending
  - id: undo-cleanup-actions
    content: "Add 'Recently Archived' list in Maintenance with one-click restore (unarchive)"
    status: pending
  - id: pkb-health-dashboard
    content: "Stats section in PKB modal: claim counts by provenance/type/status, claims this month, top entities, STM active count, last cleanup date"
    status: pending
  - id: why-tooltip-proposals
    content: "Show 'Why?' tooltip on auto-extract proposal cards — displays the conversation snippet that triggered extraction"
    status: pending
  - id: stm-promotion-visibility
    content: "Toast on STM→LTM promotion with statement preview; 'Recently Promoted' section in STM UI; one-click revert (demote back to STM or delete)"
    status: pending
---

# PKB UX Improvements Plan

## Motivation & Background

The PKB system has grown from a simple claim store into a rich multi-layer memory system (short-term → long-term, provenance, cleanup, NL agent, overview). However the UX hasn't kept pace with the architecture — users face friction at every phase:

- **Capture:** Auto-extract works well but manual capture (Save to Memory button) dumps raw text; no dedup warning; STM capture is invisible
- **Organize:** One-at-a-time editing; no way to bulk-assign contexts/tags; no proactive grouping
- **Retrieve:** Scoping is all-or-nothing; no negative feedback to tune retrieval; STM injection invisible
- **Maintain:** Manual-only cleanup trigger; no visibility into "fading" claims; no undo
- **Trust:** No aggregate health view; no explanation of why something was extracted; promotions invisible

This plan addresses all phases with 19 discrete improvements.

---

## Design Principle: 3-Surface API Parity

**Every new PKB capability MUST be exposed on all three surfaces:**

1. **REST API** (`endpoints/pkb.py`) — for direct HTTP integration, frontend calls, and third-party automation
2. **LLM Tool Calling** (`code_common/tools.py`) — for the in-app LLM to invoke mid-conversation
3. **MCP** (`mcp_server/pkb.py`) — for external AI editors (Claude Code, OpenCode, ChatGPT, Cursor, etc.)

This ensures the PKB is a **standalone module** usable from any AI client, not just our chat UI. External editors connect via MCP and get full access to memory operations.

### New tools/endpoints this plan introduces:

| Capability | REST Endpoint | LLM Tool | MCP Tool | Tier |
|-----------|---------------|----------|----------|------|
| Retrieval feedback | `POST /pkb/claims/<id>/feedback` | `pkb_feedback` | `pkb_feedback` | baseline |
| Get STM | `GET /pkb/stm` | `pkb_get_stm` | `pkb_get_stm` | baseline |
| Promote STM | `POST /pkb/stm/<id>/promote` | `pkb_promote_stm` | `pkb_promote_stm` | baseline |
| Dismiss STM | `DELETE /pkb/stm/<id>` | `pkb_dismiss_stm` | `pkb_dismiss_stm` | baseline |
| Summarize topic | `POST /pkb/summarize` | `pkb_summarize` | `pkb_summarize` | baseline |
| Get stats/health | `GET /pkb/stats` | `pkb_stats` | `pkb_stats` | full |
| Get fading claims | `GET /pkb/claims/fading` | `pkb_get_fading` | `pkb_get_fading` | full |
| Reinforce claim | `POST /pkb/claims/<id>/reinforce` | `pkb_reinforce_claim` | `pkb_reinforce_claim` | baseline |
| Bulk update | `POST /pkb/claims/bulk_update` | — | — | full |
| Suggest clusters | `POST /pkb/suggest_clusters` | `pkb_suggest_clusters` | `pkb_suggest_clusters` | full |
| Recent promotions | `GET /pkb/stm/recent_promotions` | `pkb_recent_promotions` | `pkb_recent_promotions` | full |
| Demote claim | `POST /pkb/stm/<id>/demote` | `pkb_demote_claim` | `pkb_demote_claim` | full |
| Propose extraction | `POST /pkb/propose_updates` | `pkb_propose_extraction` | `pkb_propose_extraction` | baseline |

**Existing STM endpoints** (`GET /pkb/stm`, `POST /pkb/stm/<id>/promote`, `DELETE /pkb/stm/<id>`) need MCP + LLM tool registration (currently REST-only).

**Tier assignment rationale:**
- `baseline` = operations an external AI might need in normal conversation (feedback, STM, summarize, reinforce, extract)
- `full` = administrative/maintenance operations (stats, fading, clusters, bulk, demote)

### MCP Design for External AI Clients

When Claude Code, ChatGPT, or Cursor connects via MCP, they should be able to:
1. **Store memories** from their conversation → `pkb_add_claim`, `pkb_propose_extraction`
2. **Retrieve relevant context** for the current task → `pkb_search`, `pkb_get_stm`, `pkb_get_pinned_claims`
3. **Provide feedback** on retrieved context → `pkb_feedback`
4. **Manage STM** → `pkb_get_stm`, `pkb_promote_stm`, `pkb_dismiss_stm`
5. **Explore knowledge** → `pkb_summarize`, `pkb_stats`, `pkb_list_contexts`
6. **Maintain** → `pkb_reinforce_claim`, `pkb_get_fading`, `pkb_suggest_clusters`

This makes the PKB a **universal memory backend** for any AI assistant the user works with.

---

## Existing Infrastructure to Leverage

Cross-referencing with existing plans and code reveals significant backend support already in place. Many improvements are **UI-only** or need minimal backend wiring:

| Improvement | Existing Backend Support | Remaining Work |
|-------------|------------------------|----------------|
| `dedup-at-proposal` | `LLMHelpers.check_similarity(new_claim, existing_claims, cached_embeddings=...)` — embedding-based similarity with configurable threshold | Wire into `extract_and_propose` + annotate `CandidateClaim` + frontend warning badge |
| `fading-memories-section` | `ClaimStatus.DORMANT` + `decay_dormant_claims()` (marks inactive claims dormant) + `get_lifecycle_notifications()` returns `newly_dormant` bucket | UI section showing dormant/approaching-dormant claims with Reinforce/Dismiss buttons |
| `proactive-cleanup-nudge` | `GET /pkb/notifications` endpoint already returns `soon_to_expire` + `newly_dormant` + `counts` | Frontend polling + badge + auto-navigate; background trigger condition check |
| `retrieval-scoping` | `SearchFilters` dataclass supports `context_domains`, `claim_types`, `tag_ids`, `entity_ids` — full filtering already works in all search strategies | UI dropdowns in chat settings + pass filters through `_get_pkb_context` |
| `auto-clustering-suggestions` | `cluster_near_duplicate_claims(embeddings, threshold)` in `search/consolidation.py` + `cluster_entity_variants()` | Different threshold (topic clustering vs dedup) + LLM naming + suggestion UI |
| `pkb-health-dashboard` | `OverviewStats` (claims, contexts, entities, tags, last_updated) + `get_lifecycle_notifications()` counts + existing queries | Aggregate into single endpoint + render |
| `undo-cleanup-actions` | Claims use `status='archived'` — data preserved, query-filterable | UI section + `PATCH /pkb/claims/<id>` with `status=active` (edit_claim already supports this) |
| `pkb-summarize-command` | `PKBOverviewManager.get_key_areas_snippet()` + NL agent search action + existing LLM infrastructure | New NL agent action combining search results + LLM synthesis |
| `import-button-pkb-modal` | `POST /pkb/ingest_text` (TextIngestionDistiller) + `POST /pkb/ingest_document` endpoints exist | UI button + modal + file upload zone |
| `save-to-memory-extraction` | `POST /pkb/propose_updates` with extraction mode already works | Rewire frontend handler to call this endpoint instead of opening raw modal |
| `why-tooltip-proposals` | `GET /pkb/claims/<id>/provenance` exists; extraction prompt could include `reason` field | Add `reason` to extraction JSON schema + tooltip UI |

**Key patterns to reuse:**
- `_fire_overview_update()` fire-and-forget async pattern → for stm-capture-toast, proactive-nudge background checks
- `handleToolInputRequest()` in `tool-call-manager.js` → interactive modal patterns
- `apply_recency_confidence_rerank()` post-fusion hook in search → insertion point for negative-feedback penalty
- `IngestProposal.similarity_score` + `existing_claim` fields → dedup-at-proposal data model precedent
- `portability.record_audit()` audit trail → extend to STM CRUD if audit visibility needed

**Potential conflicts/ordering:**
1. `pkb-health-dashboard` should extend `OverviewStats` not duplicate it — add fields to existing dataclass
2. `dedup-at-proposal` must not block add-claim latency — use `cached_embeddings` path (precomputed via `EmbeddingStore.ensure_embeddings`)
3. `negative-feedback-retrieval` penalty goes into `apply_recency_confidence_rerank()` — same hook as `w_recency`/`w_confidence`
4. `pkb-summarize-command` and `nl-search-rich-results` both affect NL agent prompts — coordinate prompt budget (Key Areas snippet already capped at ~200 words)

---

## Phase 1: Capture Improvements

### 1.1 Save to Memory → Extraction Pipeline (`save-to-memory-extraction`)

**Current behavior:** "Save to Memory" button in message card header calls `PKBManager.openAddClaimModalWithText(fullMessageText)` — opens the Add Claim modal with the entire AI response as a single blob.

**New behavior:**
1. "Save to Memory" button → calls `POST /pkb/propose_updates` with the message text (same endpoint as auto-extract)
2. Backend runs `ConversationDistiller.extract_and_propose()` on the text
3. Returns proposed claims (multiple, structured)
4. Frontend shows the standard `#memory-proposal-modal` with editable cards
5. User reviews, edits, approves

**Text selection variant:**
- Add a floating "💾 Remember" button that appears when user selects text within an AI response (using `window.getSelection()`)
- Selected text is sent to the same extraction pipeline
- If selection is short enough (< 50 words), also offer "Save as-is" (direct single-claim creation without LLM)

**Files to modify:**
- `interface/common.js` — `saveToMemoryItem.click` handler + text selection listener
- `interface/pkb-manager.js` — new `extractAndPropose(text, sourceMessageId)` method
- `endpoints/pkb.py` — ensure `propose_updates` can accept raw text without full conversation context (already supports `extraction_mode`)

**Edge cases:**
- Empty selection → do nothing
- Very long message (>2000 words) → truncate with notice or split
- PKB disabled → hide the button

**3-Surface exposure (propose_extraction):**
- REST: `POST /pkb/propose_updates` already exists — ensure it accepts raw `text` param without requiring full conversation context
- LLM Tool: `pkb_propose_extraction(text)` — LLM can extract memories from any text block autonomously
- MCP: `pkb_propose_extraction` (baseline tier) — external editors can send code comments, README sections, or conversation snippets for memory extraction
- This enables a key use case: Claude Code reads a design doc → extracts key decisions as PKB claims automatically

---

### 1.2 Dedup Check at Proposal Time (`dedup-at-proposal`)

**Current behavior:** Proposal modal shows extracted claims without checking if semantically-equivalent claims already exist.

**New behavior:**
1. During `extract_and_propose()`, after generating candidates, run a quick similarity check against existing claims
2. For each candidate, search existing claims (embedding similarity or SequenceMatcher ≥ 0.80)
3. If match found, annotate the candidate with `similar_existing: [{claim_id, statement, similarity}]`
4. Frontend shows a yellow "⚠️ Similar existing" badge on the card with expandable comparison
5. User can still approve (creates new) or dismiss (skips)

**Implementation:**
- `conversation_distillation.py` — after `_extract_claims_from_turn()`, call `self.llm.check_similarity(candidate.statement, active_claims, cached_embeddings=precomputed)` for each candidate
- `EmbeddingStore.ensure_embeddings(active_claims)` provides the cached embeddings (one batch call, not per-candidate)
- Filter results by threshold ≥ 0.80; attach matches as `CandidateClaim.similar_existing: List[{claim_id, statement, similarity}]`
- `pkb-manager.js` — render yellow "⚠️ Similar existing" badge in proposal modal with expandable comparison

**Performance:** Each candidate gets one embedding search (fast, ~50ms). With 3-5 candidates typical, adds 150-250ms total — acceptable since proposal is non-blocking.

---

### 1.3 Import Button in PKB Modal (`import-button-pkb-modal`)

**Current behavior:** Text/document ingestion exists (`POST /pkb/ingest_text`, `POST /pkb/ingest_document`) but has no visible UI entry point.

**New behavior:**
- Add an "Import" button in the PKB modal header (next to "Add Memory")
- Opens a sub-modal with:
  - Textarea for paste-in text (with "Extract Memories" button)
  - File upload zone (accepts .txt, .md, .pdf, .docx)
  - Progress indicator during extraction
  - Shows proposal cards when done

**Files:** `interface/interface.html` (modal HTML), `interface/pkb-manager.js` (handlers), existing endpoints already support this.

---

### 1.4 STM Capture Toast (`stm-capture-toast`)

**Current behavior:** STM captures silently — user has no idea.

**New behavior:**
- After `POST /pkb/propose_updates` completes (in the response handler in `common-chat.js`), if the response includes `stm_stored_count > 0`:
  - Show a brief non-blocking toast: "💭 2 context items remembered" (auto-dismiss after 3s)
  - Toast is clickable → opens PKB modal on STM section
- Backend already stores STM and could return the count; add `stm_stored_count` to response JSON

**Files:** `endpoints/pkb.py` (add count to response), `interface/common-chat.js` (show toast)

---

## Phase 2: Organization Improvements

### 2.1 Bulk Organization Tools (`bulk-organization`)

**Current behavior:** Claims list is view-only with individual edit buttons.

**New behavior:**
- Checkbox column in claims list (first column, hidden until "Select" mode toggled)
- "Select" toggle button in claims tab header
- When ≥1 claim selected, show floating action bar:
  - "Add to Context" → dropdown of existing contexts + "New Context"
  - "Add Tag" → tag picker
  - "Change Type" → type dropdown
  - "Change Status" → status dropdown
  - "Delete" → confirmation dialog
- "Select All" / "Deselect All" in header
- Selection persists across pagination

**Implementation:**
- `interface/pkb-manager.js` — selection state management, bulk action bar HTML, batch API calls
- `endpoints/pkb.py` — `POST /pkb/claims/bulk_update` (accepts array of claim_ids + action)
- `truth_management_system/interface/structured_api.py` — `bulk_update_claims()` method

---

### 2.2 Create Context from Selection (`create-context-from-selection`)

**Current behavior:** Must create context first, then assign claims one by one.

**New behavior:**
- In bulk action bar (when claims selected): "Create Context" button
- Opens mini-modal: "Name this context" + optional parent context dropdown
- On submit: creates context, assigns all selected claims to it
- Deselects claims, refreshes view

**Implementation:** Reuses existing `api.add_context()` + `api.link_claims_to_context()` endpoints. Frontend only.

---

### 2.3 Auto-Clustering Suggestions (`auto-clustering-suggestions`)

**Current behavior:** No proactive grouping.

**Existing backend support:** `cluster_near_duplicate_claims(embeddings, threshold)` in `search/consolidation.py` already clusters claims by embedding similarity. `cluster_entity_variants()` groups entity name variations. `EmbeddingStore.ensure_embeddings()` batch-computes vectors. The clustering algorithm exists — we need to repurpose it with a lower threshold for topic grouping (vs dedup's high threshold).

**New behavior:**
- In Maintenance tab, new "Suggest Groupings" button
- Backend:
  1. Find claims with no context assignment (query `claims LEFT JOIN context_claims WHERE context_id IS NULL`)
  2. Compute embeddings via `EmbeddingStore.ensure_embeddings(orphan_claims)`
  3. Run `cluster_near_duplicate_claims(embeddings, threshold=0.65)` — lower threshold than dedup (0.85) for topic affinity
  4. For each cluster with ≥3 claims, extract a suggested group name via LLM (one-shot: "What topic connects these statements?")
  5. Return suggestions: `[{suggested_name, claim_ids, sample_statements}]`
- Frontend: Show suggestion cards with claim previews, "Create Context" button per suggestion
- Can also run as part of `run_memory_cleanup` if a config flag `compaction_suggest_clusters` is set

**Files:**
- `truth_management_system/interface/structured_api.py` — `suggest_claim_clusters()` (uses existing `cluster_near_duplicate_claims` with different threshold)
- `endpoints/pkb.py` — `POST /pkb/suggest_clusters`
- `code_common/tools.py` — `pkb_suggest_clusters` tool (full tier)
- `mcp_server/pkb.py` — `pkb_suggest_clusters` (full tier) — external editors can trigger organization suggestions
- `interface/pkb-manager.js` — render suggestion cards in Maintenance tab

---

## Phase 3: Retrieval Improvements

### 3.1 Negative Feedback on Retrieved Memories (`negative-feedback-retrieval`)

**Current behavior:** No feedback mechanism.

**New behavior:**
- In the "PKB Retrieval Details" collapsible section (already streamed per-response), add a small "👎" button per item
- Click → `POST /pkb/claims/<id>/feedback` with `{type: "irrelevant", query_context: <user_message_summary>, conversation_id}`
- **Storage:** New `pkb_retrieval_feedback` table: `(feedback_id, claim_id, user_email, query_context, feedback_type, conversation_id, created_at)`
- **Usage in rerank:** NOT a permanent confidence decrease (the memory isn't wrong). Instead:
  - Track per-claim negative feedback count and the query contexts it was irrelevant to
  - In `apply_recency_confidence_rerank()` (the existing post-fusion reranking hook in `search/base.py`), check if the current query is semantically similar to any past negative-feedback queries for this claim
  - If yes, apply a small penalty (e.g. `score *= 0.7`) — contextual demotion, not permanent
  - This reuses the same hook that already applies `w_recency` and `w_confidence` adjustments
  - Claims with 5+ negative feedbacks across diverse queries → flag for review in Maintenance tab ("Frequently irrelevant" section)

**This solves the contextual problem:** "not relevant HERE" vs "not relevant EVER" — we store the query context and only penalize when similar queries appear again.

**3-Surface exposure:**
- REST: `POST /pkb/claims/<id>/feedback` — body: `{type: "irrelevant"|"helpful", query_context: str, conversation_id: str}`
- LLM Tool: `pkb_feedback(claim_id, feedback_type, query_context)` — allows the in-app LLM to signal when it notices retrieved context wasn't used
- MCP: `pkb_feedback` (baseline tier) — external AI editors can report "this memory wasn't relevant to what I'm working on"
- The MCP exposure is particularly important: when Claude Code retrieves PKB context for coding tasks, it can autonomously report irrelevant memories without user action

---

### 3.2 STM in Audit Details (`stm-in-audit-details`)

**Current behavior:** `_format_pkb_audit_details` only parses `<pkb_item>` tags. STM block uses `<stm_context>` with `- [ago] statement` bullets — these either fall through the fallback bullet parser without STM badges or are missed entirely.

**New behavior:**
- In `_format_pkb_audit_details`, add parsing for `<stm_context>` block:
  - Extract lines matching `- [<time>] <statement>`
  - Render with a distinct purple "STM" badge (vs the existing source/type badges for claims)
  - Show the relative time
- This makes STM visible in the same "PKB Retrieval Details" section that already shows long-term claims

**Files:** `Conversation.py` — `_format_pkb_audit_details` function (~10 lines to add STM parsing)

---

### 3.3 Retrieval Scoping (`retrieval-scoping`)

**Current behavior:** `use_pkb` is a binary on/off toggle.

**Existing backend support:** `SearchFilters` dataclass already accepts `context_domains: List[str]`, `claim_types: List[str]`, `tag_ids: List[str]`, `entity_ids: List[str]`. All search strategies (FTS, embedding, hybrid, rewrite) respect these filters. This is purely a UI + plumbing task.

**New behavior:**
- In Chat Settings → Advanced Options, add "Memory Scope" multi-select (collapsed by default):
  - Domain filter: dropdown of user's domains (populated from `GET /pkb/domains`)
  - Context filter: dropdown of user's contexts (populated from `GET /pkb/contexts`)
  - Tag filter: dropdown of user's tags (populated from `GET /pkb/tags`)
  - Entity filter: dropdown of user's entities (populated from `GET /pkb/entities`)
- When any filter set, `_get_pkb_context()` constructs `SearchFilters` with those values
- Stored in `chatSettingsState.pkb_scope` → sent with each message payload
- "All" = no filter (default); clearing scope removes all restrictions

**Implementation:**
- `interface/chat.js` — scope dropdowns in settings modal (Bootstrap Select multi-select like tool selector)
- `Conversation.py` `_get_pkb_context()` — accept `pkb_scope` from message settings, construct `SearchFilters`
- NO backend changes needed — `SearchFilters` and all search strategies already work

**UX:** Useful for users who have work+personal claims and want to scope a conversation to just "work." Also useful for focused research sessions on a specific project context.

---

## Phase 4: Interaction Improvements

### 4.1 Enhanced NL Search Results (`nl-search-rich-results`)

**Current behavior:** NL agent returns search results as plain text statements.

**New behavior:** Format each result with metadata:
```
1. **@morning_workouts_a3f2** (fact, confidence: 0.9, stated)
   "User prefers morning workouts before 7am"
   _Last accessed 3 days ago_
```

**Implementation:** Modify `nl_agent.py` search action handler to include `friendly_id`, `confidence`, `derivation`, `last_accessed_at` in formatted output.

---

### 4.2 `/pkb summarize <topic>` Command (`pkb-summarize-command`)

**Current behavior:** No way to get a synthesis across claims about a topic.

**Existing backend support:** `PKBOverviewManager.get_key_areas_snippet()` provides a high-level KB map. NL agent already has `search_claims` action. The NL agent's prompt already receives the KB map for context.

**New behavior:**
- NL agent recognizes "summarize X" / "what do you know about X" / "tell me everything about X" patterns
- Implementation:
  1. Search claims with query=topic, k=20 (existing search action, maybe with expanded k)
  2. Also fetch the overview Key Areas snippet for topic orientation
  3. Pass all results to LLM: "Synthesize what is known about {topic} from these memories. Include confidence levels and note any contradictions."
  4. Stream the synthesis back (uses existing `process_streaming()` pattern)
- Register as explicit action in `nl_agent.py` — `summarize_topic` alongside existing `search_claims`, `add_claim`, etc.
- Could also be a standalone tool: `pkb_summarize` registered in `code_common/tools.py` for main LLM tool-calling access

**3-Surface exposure:**
- REST: `POST /pkb/summarize` — body: `{topic: str, max_claims: int}` → returns `{summary: str, claims_used: [...]}`
- LLM Tool: `pkb_summarize(topic)` — LLM can ask "what do I know about X?" autonomously
- MCP: `pkb_summarize` (baseline tier) — external editors can query "summarize everything known about React hooks" before starting a task
- NL Agent: also accessible via `/pkb summarize <topic>` or `/memory what do you know about <topic>`

---

## Phase 5: Maintenance Improvements

### 5.1 Proactive Cleanup — Background Job + Nudge (`proactive-cleanup-nudge`)

**Current behavior:** User must manually navigate to Maintenance tab and click Analyze.

**Existing backend support:** `GET /pkb/notifications` already returns `soon_to_expire`, `newly_dormant`, and `counts` dict. The infrastructure for detecting "things needing attention" is fully built.

**New behavior:**
- **Background trigger conditions** (checked on each `propose_updates` call or on a lightweight poll):
  - N ≥ 20 new claims since last cleanup, OR
  - ≥ 14 days since last cleanup for this user, OR
  - `GET /pkb/notifications` returns counts > 0 (dormant or expiring claims exist)
- **When triggered:**
  1. Run `run_memory_cleanup(apply=False)` in background (analysis only, fire-and-forget like `_fire_overview_update`)
  2. Cache results keyed by user (in-memory or lightweight DB table `pkb_cleanup_cache`)
  3. Set a flag `cleanup_available: true` in subsequent API responses
- **Frontend:**
  - On PKB modal open, check `GET /pkb/notifications` counts — if non-zero, show badge on Maintenance tab header
  - Badge on PKB sidebar button: small dot indicator when cleanup available
  - In PKB modal header: "⚠️ Memory health check available — Review" link → navigates to Maintenance tab
  - Click shows pre-computed results (no re-analysis wait)
- **Also supports manual re-run** if user wants fresh analysis

**Files:**
- `endpoints/pkb.py` — add `cleanup_available` flag to responses; background trigger in `propose_updates`
- `interface/pkb-manager.js` — badge display on modal open (poll `GET /pkb/notifications`), auto-navigate

---

### 5.2 Fading Memories Section (`fading-memories-section`)

**Current behavior:** Claims silently decay via `decay_dormant_claims()` which flips them to `ClaimStatus.DORMANT` — but users never see this happening. `get_lifecycle_notifications()` already returns `newly_dormant` claims but it's not surfaced in Maintenance UI.

**New behavior:**
- In Maintenance tab, new "Fading Memories" section (above dedup suggestions):
  - Uses `GET /pkb/notifications` (existing endpoint) to show `newly_dormant` claims
  - Additionally queries claims APPROACHING dormancy: `last_accessed_at > 60 days` AND `confidence < 0.6` AND `status = 'active'` AND NOT pinned
  - Each shows: statement, confidence badge, "last seen X days ago" text
  - Actions: "Reinforce" (calls `reinforce_claim()` — resets timestamps, bumps confidence), "Archive" (sets status=archived)
- **Retrieval behavior:** `DORMANT` claims are already excluded from `default_search_statuses()` — they don't appear in search results. The "Fading" section shows claims approaching that threshold so users can intervene.
- **Integration:** The proactive-cleanup-nudge (5.1) can include fading count in its badge: "3 fading, 2 expiring soon"

**3-Surface exposure:**
- REST: `GET /pkb/claims/fading` — returns claims approaching dormancy with `last_accessed_at`, confidence, days until dormancy
- REST: `POST /pkb/claims/<id>/reinforce` — resets timestamps + bumps confidence
- LLM Tool: `pkb_get_fading` (full tier) — LLM can proactively say "btw, these memories are fading, want to keep them?"
- LLM Tool: `pkb_reinforce_claim(claim_id)` (baseline) — LLM can reinforce a claim when it uses one successfully
- MCP: `pkb_get_fading`, `pkb_reinforce_claim` — external editors can maintain memory health
- Key MCP use case: external editor retrieves context → successfully uses a claim → calls `pkb_reinforce_claim` to prevent decay

---

### 5.3 Dedup Highlight Matching (`dedup-highlight-matching`)

**Current behavior:** Dedup pairs shown as two statements side-by-side.

**New behavior:** Highlight the overlapping words/phrases between the two statements using a simple diff. Use `<mark>` tags around matching subsequences.

**Implementation:** Frontend-only — compute LCS (longest common subsequence) of words between the two statements, wrap matching spans in `<mark>`.

---

### 5.4 Undo Cleanup — Recently Archived (`undo-cleanup-actions`)

**Current behavior:** No way to find or restore archived claims.

**New behavior:**
- In Maintenance tab, new "Recently Archived" section (collapsible, at bottom):
  - Shows claims with `status = 'archived'`, ordered by `updated_at DESC`, limit 20
  - Each shows: statement, archive date, provenance
  - Action: "Restore" → sets status back to `active`
- `GET /pkb/claims?status=archived&sort=updated_at&limit=20` (existing endpoint already supports status filter)

**Files:** `interface/pkb-manager.js` — new section in Maintenance tab. Backend already supports the query.

---

## Phase 6: Trust & Transparency

### 6.1 PKB Health Dashboard (`pkb-health-dashboard`)

**Current behavior:** No aggregate view of memory system health.

**Existing backend support:** `OverviewStats` dataclass already computes `claims`, `contexts`, `entities`, `tags`, `last_updated`. `get_lifecycle_notifications()` returns `counts` dict. Individual queries for status/type/provenance breakdowns are straightforward SQL aggregates.

**New behavior:**
- New "Stats" section at top of PKB modal (or as part of existing Overview tab):
  - **Counts by status:** Active | Dormant | Contested | Historical | Expired | Archived (horizontal colored bar/badges)
  - **Counts by provenance:** Stated | Extracted | Inferred (badges with percentages)
  - **Counts by type:** Fact | Preference | Decision | Task | etc. (top 5)
  - **Activity this month:** N claims added, N modified, N expired, N promoted from STM
  - **Top 5 entities** (by linked claim count)
  - **STM:** N active, N promoted this week, N expired this week
  - **Last cleanup:** date + summary (expired count, archived count, dedup count)
  - **Health signals:** dormant claims approaching threshold, expiring tasks
  - **Memory growth over time:** claims per month (last 6 months, simple text: "Jan: 12, Feb: 8, ...")
- Endpoint: `GET /pkb/stats` → single aggregated response (extends `OverviewStats` + additional queries)

**Files:**
- `truth_management_system/interface/structured_api.py` — `get_pkb_stats()` (SQL aggregates, reuse `OverviewStats` base)
- `endpoints/pkb.py` — `GET /pkb/stats`
- `code_common/tools.py` — `pkb_stats` tool (LLM can check memory health)
- `mcp_server/pkb.py` — `pkb_stats` MCP tool (full tier — external editors can audit memory state)
- `interface/pkb-manager.js` — render dashboard (simple HTML badges/bars, no chart library)

---

### 6.2 "Why?" Tooltip on Proposal Cards (`why-tooltip-proposals`)

**Current behavior:** Proposal cards show the extracted statement but not what triggered it.

**New behavior:**
- `ConversationDistiller.extract_and_propose()` already has the conversation text as input
- Extend the extraction prompt to also output a `reason` field per candidate: "Brief explanation of why this was extracted"
- Include in the response: `CandidateClaim.extraction_reason: str`
- Frontend: small "?" icon on each proposal card → hover shows the reason + the triggering conversation snippet (first 100 chars of the message that contained the fact)

**Implementation:**
- `conversation_distillation.py` — add `reason` field to extraction prompt JSON schema + `CandidateClaim`
- `endpoints/pkb.py` — pass through in response
- `interface/pkb-manager.js` — tooltip rendering

---

### 6.3 STM Promotion Visibility (`stm-promotion-visibility`)

**Current behavior:** Auto-promotion at 3 reinforcements happens silently.

**New behavior:**
1. **Toast on promotion:** When `reinforce_short_term_memory()` triggers auto-promote, record the event
2. **Frontend notification:** On next page load or PKB modal open, check `GET /pkb/stm/recent_promotions` (last 7 days)
3. **Show toast:** "💫 Memory promoted: '{statement}' (used in 3+ conversations)"
4. **"Recently Promoted" section** in STM UI area:
   - Shows claims that were promoted from STM in the last 7 days
   - Each shows: statement, promotion date, reinforcement count
   - Actions: "Keep" (no-op, dismiss from list), "Revert" (delete the promoted claim, optionally re-create as STM)
5. **Revert mechanism:** `POST /pkb/stm/<promoted_claim_id>/demote` — sets claim status to `retracted` + optionally recreates as STM with original TTL

**Files:**
- `truth_management_system/interface/structured_api.py` — `get_recent_promotions()`, `demote_promoted_claim()`
- `endpoints/pkb.py` — `GET /pkb/stm/recent_promotions`, `POST /pkb/stm/<id>/demote`
- `code_common/tools.py` — `pkb_recent_promotions` tool (LLM can check what was recently promoted)
- `mcp_server/pkb.py` — `pkb_recent_promotions`, `pkb_demote_claim` (full tier)
- `interface/pkb-manager.js` — Recently Promoted section + toast logic

---

## Implementation Order (suggested)

Group by effort and dependency. Effort estimates revised after discovering existing infrastructure:

**Batch 0 (API Parity Foundation — do first, unlocks external editor usage):**
- `stm-mcp-tools` — register `pkb_get_stm`, `pkb_promote_stm`, `pkb_dismiss_stm` in MCP + LLM tools (~2h)
- Register `pkb_propose_extraction` as MCP + LLM tool (wrap existing `POST /pkb/propose_updates`) (~1h)

**Batch 1 (Low effort — mostly frontend wiring to existing backends):**
- `stm-capture-toast` — add count to response JSON + show toast (~30 min)
- `stm-in-audit-details` — parse `<stm_context>` in existing formatter (~30 min)
- `stm-promotion-visibility` — toast + section + demote endpoint (~2h)
- `undo-cleanup-actions` — UI section + existing `edit_claim(status=active)` (~1h)
- `import-button-pkb-modal` — button + modal wiring to existing `ingest_text`/`ingest_document` (~2h)
- `save-to-memory-extraction` — rewire click handler to call `propose_updates` (~1h)

**Batch 2 (Medium effort — backend exists, needs UI + light wiring):**
- `dedup-at-proposal` — `check_similarity` + `cached_embeddings` + frontend warning (~3h)
- `why-tooltip-proposals` — extraction prompt `reason` field + tooltip (~2h)
- `retrieval-scoping` — UI dropdowns + pass `SearchFilters` through `_get_pkb_context` (~3h, no backend changes)
- `fading-memories-section` — extends `get_lifecycle_notifications` + reinforce button + UI section (~2h)
- `proactive-cleanup-nudge` — lightweight trigger check + badge (~3h)
- `nl-search-rich-results` — format change in NL agent response (~1h)

**Batch 3 (Medium-high effort — new backend logic + UI + API surface):**
- `pkb-summarize-command` — new NL agent action + LLM synthesis + register as MCP/LLM tool (~4h)
- `negative-feedback-retrieval` — new table + contextual penalty in `apply_recency_confidence_rerank` + REST/MCP/tool (~5h)
- `pkb-health-dashboard` — aggregate SQL endpoint + REST/MCP tool + dashboard render (~5h)
- `dedup-highlight-matching` — frontend LCS diff logic (~2h)

Note: Each new endpoint in Batch 2-4 gets simultaneously registered as REST + LLM tool + MCP tool. The pattern is mechanical: define handler in `structured_api.py`, expose via `endpoints/pkb.py`, register in `code_common/tools.py`, register in `mcp_server/pkb.py`.

**Batch 4 (Higher effort — significant UI state management + API surface):**
- `bulk-organization` — selection state + bulk endpoint + action bar (~6h)
- `create-context-from-selection` — builds on bulk-organization (~1h after bulk-org)
- `auto-clustering-suggestions` — repurpose `cluster_near_duplicate_claims` at lower threshold + LLM naming + REST/MCP tool + UI (~5h)
