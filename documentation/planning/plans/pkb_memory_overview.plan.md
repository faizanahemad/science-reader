# PKB Memory Overview: Design & Implementation Plan

**Created:** 2026-06-10
**Status:** DONE (June 2026)
**Depends On:** PKB v0.9 (Schema v10, `truth_management_system/`), `MarkdownEditorManager` (`interface/markdown-editor.js`), REST API (`endpoints/pkb.py`)
**Schema Version:** This plan adds schema v11 (`pkb_overview` table). Schema v10 is `audit_log` (Workstream G3) — already shipped.
**Related Docs:**
- `documentation/features/truth_management_system/README.md` — PKB feature overview
- `documentation/features/truth_management_system/implementation_deep_dive.md` — PKB internals
- `documentation/features/truth_management_system/api.md` — PKB API reference

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Requirements & Clarifications](#requirements--clarifications)
3. [Goals](#goals)
4. [Non-Goals](#non-goals)
5. [Storage Design](#storage-design)
6. [Overview Content Structure](#overview-content-structure)
7. [PKBOverviewManager Module](#pkboverviewmanager-module)
8. [Update Hook Architecture](#update-hook-architecture)
9. [Bulk Debouncing](#bulk-debouncing)
10. [Incremental Update LLM Prompt Design](#incremental-update-llm-prompt-design)
11. [Consolidation](#consolidation)
12. [REST API](#rest-api)
13. [MarkdownEditorManager Refactor](#markdowneditormanager-refactor)
14. [UI: Overview Tab (Tab 8)](#ui-overview-tab-tab-8)
15. [Chat Retrieval Integration](#chat-retrieval-integration)
16. [NL Agent Integration](#nl-agent-integration)
17. [Implementation Order](#implementation-order)
18. [Files to Create / Modify](#files-to-create--modify)
19. [Testing Plan](#testing-plan)
20. [Risks and Mitigations](#risks-and-mitigations)

---

## Problem Statement

The PKB system stores potentially hundreds of claims, contexts, entities, and tags per user, but provides no synthesized view of what it collectively knows. A user has no way to quickly answer "what does my memory system know about me overall?" without manually browsing every tab.

Additionally, the existing `MarkdownEditorManager` is hardcoded to the `#message-edit-modal` element throughout its ~700-line implementation, making it impossible to reuse for other markdown editing surfaces (memory pad, overview, future callers) without copy-pasting.

---

## Requirements & Clarifications

The following requirements were gathered through a clarification session before design began.

### Content & Structure

- **Section guidance**: The overview uses a fixed set of default sections (Summary, Key Areas, Important Entities, Table of Contents, Recently Modified) but the LLM is free to add more sections as the knowledge base evolves. Sections are never forcibly removed by the system.
- **Update operations**: After the initial generation, updates are file-edit style operations — the LLM performs targeted add/edit/remove operations on specific sections of the existing markdown document, not full rewrites. This mirrors how coding agents operate on files.
- **"Recently Modified"**: Top 5 claims by `last_reinforced_at` (falling back to `updated_at`). Edits count — not creation-time only.
- **Key entities threshold**: Top 20 entities by claim-link count.
- **Prose tone**: Third person ("The user prefers..." not "I prefer...").

### Update Behavior

- **Bulk debouncing**: For bulk import (`execute_ingest`, `add_claims_bulk`) and distillation approval (`execute_updates`), one consolidated overview update fires at the end of the bulk operation — not per-claim.
- **Manual staleness handling**: The UI exposes two explicit buttons: "Regenerate" (full regeneration from scratch) and "Scan for gaps" (pass full claim list + current overview to LLM to identify what's missing/outdated). Both are user-triggered.
- **Failure tolerance**: If the overview LLM call fails (timeout, API error), the write operation still succeeds silently. The overview is marked `is_stale = 1` and a warning is shown in the Overview tab UI.
- **Auto-save gate**: Auto-save from chat (`auto_pkb_extract`) already has a user-approval gate (proposal modal). The overview update triggers on `execute_updates` — which is only called after user approval. No special handling needed.

### Consolidation

- **Threshold**: 8,000 words (same as memory pad).
- **Timing**: Triggered on the write path but executed asynchronously (fire-and-forget) so write endpoints are never blocked by a second LLM call.

### UI & Editor

- **Tab position**: Last tab (Tab 8), after the existing 7 tabs.
- **Edit access**: Full markdown editor with the `MarkdownEditorManager`. Freely hand-editable at any time.
- **Manual edits and auto-updates**: After a user manually edits the overview, subsequent auto-updates from write operations still run. The LLM prompt instructs it to make only minimal targeted edits — it only overwrites a section if the new claim actually warrants a change there. Manual prose additions in unrelated sections should survive incremental updates.
- **Editor reuse scope**: Full abstraction. `MarkdownEditorManager` should become a general-purpose reusable component usable from any surface (PKB overview, memory pad, future callers). Expect more callers soon.

### Storage

- **Per-user isolation**: Handled by `user_email PRIMARY KEY` in a new DB table. Same SQLite file as the rest of PKB.
- **Derived/disposable**: The overview is not included in PKB data export. It can always be regenerated.

  > **Portability exclusion:** `portability.export_user_data()` (Workstream G3) uses `SELECT *` on each owned table. Since `pkb_overview` is a new table not in that export list, it will naturally be excluded **as long as it is not added to `export_user_data`'s table list**. The implementer must not add `pkb_overview` to `portability.py`'s export queries.
- **Concurrent writes**: Last-write-wins. No versioning or optimistic locking needed.

---

## Goals

1. **Memory overview document** — a maintained markdown file per user summarizing the entire knowledge base: prose summary, key areas by domain, important entities, context TOC, and recently modified claims.
2. **Incremental LLM updates** — each write operation on the PKB triggers a cheap async LLM call that performs a targeted edit on the overview document. Overview stays current without full regeneration on every change.
3. **Consolidation** — when the overview exceeds 8,000 words, a background LLM call condenses it while preserving structure.
4. **Manual controls** — user can trigger full regeneration, gap-scan, or direct edit via the Overview tab.
5. **Stale warning** — if an LLM update fails, a visible warning appears in the UI until the next successful update or manual save.
6. **Reusable markdown editor** — `MarkdownEditorManager` refactored to accept a target modal context so any surface can use it without code duplication.
7. **Chat retrieval integration** — Overview accessible via `@pkb_overview` reference in chat (resolves like any other PKB object). A lightweight Key Areas snippet (~100 words) optionally prepended to the auto-retrieved PKB context on every turn (config-gated).
8. **NL agent integration** — Overview prepended to the NL agent's system context so it has a map of the KB before issuing search/add/edit commands.

---

## Non-Goals

- Injecting the full overview into the LLM chat context automatically (chat integration is done via explicit @reference and a lightweight Key Areas snippet — see [Chat Retrieval Integration](#chat-retrieval-integration)).
- Real-time/live updates within a session (updates fire async, may appear on next tab open).
- Exporting the overview as part of PKB data export.
- Per-claim or per-entity "mini-overviews".
- Scheduled background regeneration daemon.

---

## Storage Design

### New table: `pkb_overview`

Added via `_migrate_v10_to_v11()` in `database.py`. Also added to base DDL with `IF NOT EXISTS`.

> **Schema version conflict note:** `_migrate_v9_to_v10()` already exists and creates the `audit_log` table (Workstream G3, portability). The overview table is schema **v11**, not v10. `SCHEMA_VERSION` in `schema.py` must be bumped to `11`.

```sql
CREATE TABLE IF NOT EXISTS pkb_overview (
    user_email   TEXT PRIMARY KEY,
    content      TEXT,             -- raw markdown (stats line is a template slot)
    word_count   INTEGER,          -- cached to avoid re-splitting on every write check
    last_updated TEXT,             -- ISO timestamp of last successful update
    is_stale     INTEGER DEFAULT 0 -- 1 = last LLM update failed; show warning in UI
);
```

### Stats line as a template slot

The stored `content` contains a stats line placeholder:

```
*Claims: {claims} · Contexts: {contexts} · Entities: {entities} · Tags: {tags} · Last updated: {date}*
```

The `GET /pkb/overview` endpoint always replaces this line with live DB counts before returning content to the UI. The stored markdown never has accurate counts baked in — they're injected at read time. This prevents counts from drifting out of sync if an LLM update fails.

---

## Overview Content Structure

Generated in markdown. Sections are guided but not enforced — the LLM may add more sections as the knowledge base evolves. The LLM is instructed to operate on this as a file (targeted add/edit/remove per section) after initial generation.

```markdown
# Memory Overview
*Claims: {claims} · Contexts: {contexts} · Entities: {entities} · Tags: {tags} · Last updated: {date}*

## Summary
2–4 sentences in third person. What domains are covered, what's most prominent,
what kind of person this knowledge base describes overall.

## Key Areas
- **Health** (34 claims): morning workouts, peanut allergy, sleep schedule
- **Work** (41 claims): Project Alpha, Python/microservices stack, team dynamics
- **Personal** (28 claims): IST timezone, coffee with oat milk, family members
...one bullet per domain with claim count and top keywords...

## Important People & Entities
Top 20 entities by claim-link count, comma-separated:
Dr. Smith (person), Project Alpha (project), Python (system), ...

## Table of Contents
PKB contexts with claim counts, linked by @reference:
- @health_goals_context — 15 claims
- @work_projects_context — 22 claims
...

## Recently Modified
Top 5 claims by last_reinforced_at / updated_at:
- [preference] The user prefers morning workouts — *2026-06-09*
- [fact] Project Alpha is using a microservices architecture — *2026-06-08*
...
```

---

## PKBOverviewManager Module

**New file:** `truth_management_system/interface/overview_manager.py`

### Dataclasses

```python
@dataclass
class OverviewStats:
    claims: int
    contexts: int
    entities: int
    tags: int
    last_updated: str

@dataclass
class OverviewResult:
    content: str          # markdown with stats line injected
    stats: OverviewStats
    is_stale: bool
    last_updated: str     # ISO timestamp

@dataclass
class OverviewUpdateEvent:
    trigger: str          # "add" | "edit" | "delete" | "bulk" | "link"
    claims: List[Claim]   # changed claims for LLM context (empty for pure link events)
    current_content: str  # existing overview markdown (may be empty)
    link_metadata: Optional[dict] = None
    # For link events: {"object_type": "tag"|"entity"|"context",
    #                   "object_name": str, "claim_statement": str}
    # For claim events: None
```

### Class: `PKBOverviewManager`

```python
class PKBOverviewManager:
    def __init__(self, db: PKBDatabase, keys: dict, config: PKBConfig):
        ...

    def get_overview(self, user_email: str) -> OverviewResult:
        """
        Returns the overview for user. If no content exists (first time),
        triggers lazy full generation synchronously and returns result.
        Always injects live stats into the stats line before returning.
        """

    def generate_full(self, user_email: str) -> OverviewResult:
        """
        Full regeneration from scratch. Queries:
          - All active claims grouped by domain (counts + top keywords via FTS)
          - Top 20 entities by claim-link count
          - All contexts with claim counts
          - Top 5 claims by last_reinforced_at / updated_at
        One LLM call (CHEAP_LLM). Stores result. Clears is_stale.
        Returns OverviewResult.
        """

    def scan_for_gaps(self, user_email: str) -> OverviewResult:
        """
        Gap-scan variant. Passes current overview + FULL raw claim list (all active claims,
        no summarization or capping) to LLM with prompt: "Given this overview and the full
        current knowledge base, identify what important information is missing or outdated,
        then produce an updated overview using the edit operations format."
        More thorough than incremental update, cheaper than full regeneration.
        Trade-off: for very large KBs (500+ claims) this will be slow and expensive.
        This is intentional — user explicitly chose accuracy over speed by triggering this.
        """

    def update_from_event(self, user_email: str, event: OverviewUpdateEvent) -> OverviewResult:
        """
        Incremental update triggered by a write operation.
        - Builds a minimal prompt: current overview + changed claim(s) + trigger type.
        - LLM performs targeted add/edit/remove on relevant sections only.
        - If word_count > 8000 after update: calls _consolidate() async (fire-and-forget).
        - On any exception: calls mark_stale(user_email), re-raises for caller to log.
        Returns OverviewResult.
        """

    def _consolidate(self, user_email: str, content: str) -> str:
        """
        Condenses overview to ~600 words while preserving all section headers,
        key entities, domain counts, and the TOC.
        One cheap LLM call. Saves result and returns new content.
        """

    def mark_stale(self, user_email: str) -> None:
        """Sets is_stale=1 in DB. Called when an LLM update fails."""

    def save(self, user_email: str, content: str) -> None:
        """
        Direct save — used by manual edit from UI (PUT /pkb/overview).
        Does NOT trigger an LLM update. Clears is_stale. Updates word_count.
        """

    def _apply_edits(self, content: str, ops: list) -> str:
        """
        Apply a list of JSON edit operations to the markdown content.
        Splits content into sections by '\n## ' boundaries.
        For each op: finds target section by exact '## Header' match, applies the op.
        Preserves section order and all untouched sections verbatim.
        Skips (and logs) ops that match no section.
        Pure Python string manipulation — no LLM call.
        Supported ops: replace_section, append_to_section, insert_section,
                       delete_from_section, no_change.
        """

    def _get_live_stats(self, user_email: str) -> OverviewStats:
        """Queries DB for live counts. Used to inject into stats line at read time."""

    def _inject_stats(self, content: str, stats: OverviewStats) -> str:
        """Replaces the template stats line with live values."""

    def get_raw_content(self, user_email: str) -> Optional[str]:
        """
        Returns the raw stored markdown content WITHOUT stats injection.
        Used by _fire_overview_update to pass current_content to OverviewUpdateEvent.
        Returns None if no overview row exists yet.
        """
```

### generate_full / scan_for_gaps vs _apply_edits

`generate_full` and `scan_for_gaps` produce **complete markdown output** (not edit ops arrays). They call `save()` directly with the full generated content. `_apply_edits` is only used by `update_from_event` (incremental updates), which receives edit ops JSON from the LLM. The implementer must not apply `_apply_edits` to the output of `generate_full` or `scan_for_gaps`.

### Model selection

| Operation | Model |
|---|---|
| `update_from_event` (incremental) | `CHEAP_LLM[0]` (Gemini Flash Lite) |
| `generate_full` | `CHEAP_LLM[0]` |
| `scan_for_gaps` | `CHEAP_LLM[0]` or one tier up if available |
| `_consolidate` | `CHEAP_LLM[0]` |

All calls at `temperature=0.2` for slight creativity in prose while staying deterministic.

---

## Update Hook Architecture

Hooks live in **`endpoints/pkb.py`**, not inside `StructuredAPI`. This avoids coupling the core library to an LLM call on every write.

### Module-level helper

```python
def _fire_overview_update(user_email: str, trigger: str, claims: list, keys: dict):
    """
    Fire-and-forget async overview update after a successful write op.
    On exception inside the async task: mark_stale is called.
    Never blocks the write endpoint response.
    """
    db, config = get_pkb_db()
    manager = PKBOverviewManager(db, keys, config)
    current = manager.get_raw_content(user_email)  # raw stored content, no stats injection
    event = OverviewUpdateEvent(trigger=trigger, claims=claims, current_content=current or "")
    get_async_future(_safe_overview_update, manager, user_email, event)

def _safe_overview_update(manager, user_email, event):
    try:
        manager.update_from_event(user_email, event)
    except Exception as e:
        logger.warning(f"[PKB Overview] update failed for {user_email}: {e}")
        manager.mark_stale(user_email)
```

> **Audit log interaction:** `_record_audit` is called by `add_claim`, `edit_claim`, `delete_claim`, and `import_data` (Workstream G3). Overview updates go through `PKBOverviewManager`, not through those StructuredAPI methods — so they do **not** emit audit rows. This is correct: the overview is a derived document, not a user data operation. Do not add audit hooks to `PKBOverviewManager.save()` or `update_from_event()`.
```

### Write endpoints that trigger an update

| Endpoint | Trigger value | Event payload |
|---|---|---|
| `POST /pkb/claims` | `"add"` | single new claim |
| `PUT /pkb/claims/<id>` | `"edit"` | updated claim |
| `DELETE /pkb/claims/<id>` | `"delete"` | retracted claim |
| `POST /pkb/execute_updates` | `"bulk"` | all successfully added/edited claims (one call at end) |
| `POST /pkb/execute_ingest` | `"bulk"` | all successfully ingested claims (one call at end) |
| `POST /pkb/claims/bulk` | `"bulk"` | all successful results |
| NL agent (`pkb_nl_command`) | per action type | per claim modified |

> **Other write operations not in this table:** `supersede_claim()`, `consolidate_claims()`, `merge_entities()`, `resolve_conflict_set()`, `run_lifecycle_sweep()` (decay/expiry) all change claim state but do not fire `_fire_overview_update`. These are background/maintenance ops — they change `status`, not the claim statement. The overview's content is driven by statement changes and additions. The `Recently Modified` section will pick up any status changes indirectly on the next triggered update (it reads `last_reinforced_at` / `updated_at` live from DB). Exception: if `consolidate_claims()` is triggered by the user from a future UI surface, a `"bulk"` trigger could optionally be added at that point.
| `POST /pkb/contexts/<id>/claims` | `"link"` | context name + claim statement |
| `DELETE /pkb/contexts/<id>/claims/<cid>` | `"link"` | context name + claim statement |
| `POST /pkb/claims/<id>/tags` | `"link"` | tag name + claim statement |
| `DELETE /pkb/claims/<id>/tags/<tid>` | `"link"` | tag name + claim statement |
| `POST /pkb/claims/<id>/entities` | `"link"` | entity name + claim statement |
| `DELETE /pkb/claims/<id>/entities/<eid>` | `"link"` | entity name + claim statement |

Linking operations (context/tag/entity) use trigger `"link"` and pass a lightweight payload — the name of the object being linked and the claim statement. The LLM update prompt for `"link"` events focuses only on the Table of Contents (context structure) and Important Entities sections — not the full Key Areas prose.

### Write endpoints that do NOT trigger an update

Reads, search, pin/unpin (pinning is a retrieval priority signal, not a content change), entity/tag creation alone (creating an entity with no claims linked is not yet significant).

> **`reinforce_claim` note:** `StructuredAPI.reinforce_claim()` updates `last_reinforced_at`, `reinforcement_count`, and potentially `confidence` and `status` (reviving dormant). It is called from `pin_claim(pin=True)`, from `add_claim` near-duplicate branch, and from `ConversationDistiller`. However, reinforcement does not change the claim's *statement* or domain — it is a staleness/confidence signal, not a semantic change. The overview's `Recently Modified` section is sorted by `last_reinforced_at`, so reinforced claims will naturally bubble up on the next incremental write that does trigger an update. A dedicated hook on `reinforce_claim` is not needed.

---

## Bulk Debouncing

`execute_updates` and `execute_ingest` loop over N claims. The overview update fires **once at the end**, passing all changed claims in a single `OverviewUpdateEvent(trigger="bulk", claims=[all_changed])`. The loop itself never fires per-claim updates.

Single-item endpoints (`POST /pkb/claims`, `PUT`, `DELETE`) fire per-operation since they are always single-item by definition.

Auto-save (`execute_updates`): the user-approval gate (proposal modal) is already in place before this endpoint is called. Triggering on `execute_updates` naturally means "only if user accepted proposals."

---

## Incremental Update LLM Prompt Design

### Core principle: the LLM edits a file, it does not rewrite it

The overview is treated as a file on disk. The LLM is given a set of edit tools and must use them to make surgical changes — it cannot output a full replacement blurb. This prevents section drift, preserves manual edits in unrelated sections, and keeps token costs low (output is just a list of small edit operations, not the full document).

### Edit tools available to the LLM

The LLM outputs a JSON array of operations (same structured-JSON-output pattern as the NL agent, for model compatibility):

```json
[
  {"op": "replace_section", "section": "## Key Areas", "new_content": "...updated bullet list..."},
  {"op": "replace_section", "section": "## Recently Modified", "new_content": "...top 5..."},
  {"op": "append_to_section", "section": "## Important People & Entities", "content": "- Gym (place)"},
  {"op": "no_change", "reason": "Minor observation, already covered in Key Areas"}
]
```

Available operations:
- `replace_section` — replace the full content of a named section (identified by `## Header` exact match)
- `append_to_section` — append a line/item to an existing section
- `insert_section` — insert a new `## Section` after a named anchor section
- `delete_from_section` — remove a specific line from a section (matched by substring)
- `no_change` — explicit signal that no edit is needed (prevents silent empty output)

The backend applies these operations sequentially against the stored markdown using simple section-boundary parsing (split on `## ` headers). After applying, the result is stored. If any operation fails to find its target section, it is skipped and logged as a warning.

### Prompt structure

```
You are editing a markdown overview document about a person's knowledge base.
Treat this document as a file — make ONLY the minimal targeted edits required by the event below.
Do NOT rewrite sections unrelated to this event.
Do NOT output the full document — output ONLY a JSON array of edit operations.

Event: [add | edit | delete | bulk | link]
Changed item(s):
  [claim: Type=preference, Domain=health, Statement="The user prefers morning workouts"]
  [OR for link events: Tag "fitness" linked to claim "The user prefers morning workouts"]

Current overview:
<current_content>

Top 5 recently modified claims (always update Recently Modified section):
- [preference] The user prefers morning workouts — 2026-06-09
...

Available operations:
  replace_section, append_to_section, insert_section, delete_from_section, no_change
  (see schema above)

Rules:
- The stats line is managed by the system — never touch it.
- Write in third person.
- For link events: only update Table of Contents (context links) or Important Entities/Tags if the link adds new information.
- For add/edit: update Key Areas if the domain's keyword list needs updating, update Summary only if a new dominant theme emerges.
- For delete: update Key Areas count and keywords if the deleted claim was significant; no change if minor.
- Always update Recently Modified using the provided list.
- If nothing needs changing, output: [{"op": "no_change", "reason": "..."}]

Output ONLY the JSON array. No explanation outside the JSON.
```

### Backend application of edit operations

`PKBOverviewManager._apply_edits(content: str, ops: list) -> str`:
- Splits content into sections by `\n## ` boundaries
- For each operation: find target section by header match, apply the op
- Preserves section order, preserves all untouched sections verbatim
- Returns assembled markdown

This is pure Python string manipulation — no LLM involved in applying the edits.

### Fallback

If the LLM output is not valid JSON, or no ops match any sections: log a warning, mark `is_stale=True`, keep existing content unchanged. Never overwrite content with a failed/empty response.

---

## Consolidation

Mirrors the memory pad pattern in `Conversation.py` exactly.

**Trigger:** After `update_from_event` stores the updated content, if `word_count > 8000`, the endpoint has already returned — consolidation fires async (fire-and-forget, `get_async_future`).

**Consolidation prompt:**
```
The following PKB overview has grown too long. Condense it to under 600 words
while preserving ALL section headers, the Table of Contents in full, all named
entities in Important Entities, and domain names with claim counts in Key Areas.
Prose in Summary and Key Areas descriptions may be shortened.
Return ONLY the condensed markdown.

<current_content>
```

**Threshold:** 8,000 words. No line-count threshold (unlike memory pad's 128-line cap — the overview is structured markdown, not bullet lists).

---

## REST API

All endpoints require `@login_required`. Rate limits consistent with other PKB read/write endpoints.

```
GET  /pkb/overview
```
Returns `{content, stats, is_stale, last_updated}`.
- `content`: markdown with stats line injected from live DB counts.
- `stats`: `{claims, contexts, entities, tags}`.
- `is_stale`: boolean.
- If no overview exists yet: triggers `generate_full()` synchronously (first-time generation), then returns result.
- Rate limit: 60/min (read).

```
PUT  /pkb/overview
```
Body: `{content: "<markdown>"}`.
Manual save from UI editor. Clears `is_stale`. Updates `word_count`. Does NOT trigger LLM update.
Rate limit: 20/min.

```
POST /pkb/overview/regenerate
```
Triggers `generate_full()` synchronously (waits for result). Returns updated `{content, stats, is_stale: false, last_updated}`.
Rate limit: 5/min (expensive op).

```
POST /pkb/overview/scan
```
Triggers `scan_for_gaps()` synchronously. Returns updated result.
Rate limit: 5/min.

---

## MarkdownEditorManager Refactor

### Current state

`MarkdownEditorManager` in `interface/markdown-editor.js` hardcodes `'#message-edit-modal'` and element IDs (`#message-edit-editor-type`, `#message-edit-codemirror-container`, etc.) throughout ~700 lines. The `openEditor(text, onSave)` signature accepts no configuration.

### Approach: per-instance modal, zero breaking changes

The root problem with sharing a single `#message-edit-modal` is that `MarkdownEditorManager` holds module-level state (`currentText`, `editors.codemirror`, `editors.easymde`, `editors.wysiwyg`, `pendingSaveCallback`). If two surfaces open the editor concurrently (two browser tabs, or the PKB modal open while a message-edit is triggered), that state corrupts.

**Solution: each caller supplies its own modal element.** `openEditor` accepts an `options.modalId`. When `modalId` differs from `'message-edit-modal'`, the manager creates an **isolated state object** for that modal rather than using the module-level shared state. Concretely:

```javascript
// Internal: per-modal state registry
var _modalStates = {};  // modalId → { currentText, editors, pendingSaveCallback, ... }

function _getState(modalId) {
    if (!_modalStates[modalId]) {
        _modalStates[modalId] = {
            currentText: '',
            initialText: '',
            editors: { codemirror: null, easymde: null, wysiwyg: null },
            pendingSaveCallback: null,
            hasEditorBeenInitialized: false,
        };
    }
    return _modalStates[modalId];
}
```

The existing `#message-edit-modal` keeps using the old module-level variables (unchanged — zero breaking changes). Any new caller that passes a different `modalId` gets its own isolated state bucket. Cleanup on `modal('hidden')`: null out the `editors` instances in that state bucket (so CodeMirror instances are released and re-initialized fresh next open) but keep the state key itself in `_modalStates` — deleting the key would not release the editor instances and could leak DOM nodes.

**Change `openEditor` signature:**
```javascript
// Before:
MarkdownEditorManager.openEditor(text, onSave)

// After (fully backward compatible — all params optional with defaults):
MarkdownEditorManager.openEditor(text, onSave, options)
// options = {
//   modalId:   'message-edit-modal',  // default — existing callers use module-level state
//   title:     'Edit Message',         // default
//   saveLabel: 'Save',                 // default
// }
```

The PKB overview caller adds a **second modal** `#pkb-overview-edit-modal` to `interface.html` — a minimal copy of `#message-edit-modal` with all the same inner element IDs namespaced to the new modal ID (e.g. `pkb-overview-edit-modal-editor-type`, `pkb-overview-edit-modal-codemirror-container`). `openEditor` reads element IDs using the `modalId` prefix, so both modals work independently with isolated state and no shared-editor corruption risk.

The modal HTML template is **one block** — added as a parameterized HTML fragment or simply duplicated once for the overview modal (since there are only two known callers at this time).

**Add `openInline(containerId, text, options)` function:**
For surfaces that need the editor embedded inline (not in a modal). Creates an isolated CodeMirror instance inside the target container. Uses the container ID as the state key in `_modalStates`. Optional `options.height` for sizing.

**Public API after refactor:**
```javascript
MarkdownEditorManager.init()
MarkdownEditorManager.openEditor(text, onSave, options)      // modal-based
MarkdownEditorManager.openInline(containerId, text, options) // inline
MarkdownEditorManager.getValue(modalId)       // optional modalId, defaults to 'message-edit-modal'
MarkdownEditorManager.setValue(text, modalId)
MarkdownEditorManager.switchEditorType(type, modalId)
MarkdownEditorManager.refreshCurrentEditor(modalId)
MarkdownEditorManager.getCurrentEditorType(modalId)
```

**Files changed:** `interface/markdown-editor.js` (additive `_modalStates` registry, `options` param, `openInline`), `interface/interface.html` (add `#pkb-overview-edit-modal` HTML block, add `data-save-btn` attribute to save buttons in both modals).

---

## UI: Overview Tab (Tab 8)

### Tab entry in `#pkb-tabs`

> **Existing tab order (confirmed from `interface.html`):** Tab 1 = Claims (`#pkb-claims-pane`), Tab 2 = Entities (`#pkb-entities-pane`), Tab 3 = Tags (`#pkb-tags-pane`), Tab 4 = Conflicts (`#pkb-conflicts-pane`), Tab 5 = Bulk Add (`#pkb-bulk-pane`), Tab 6 = Import Text (`#pkb-import-pane`), Tab 7 = Contexts (`#pkb-contexts-pane`). Overview is appended as Tab 8.

### Tab entry in `#pkb-tabs`

```html
<li class="nav-item">
  <a class="nav-link" id="pkb-overview-tab" data-toggle="tab"
     href="#pkb-overview-pane" role="tab">
    <i class="bi bi-journal-text mr-1"></i>Overview
  </a>
</li>
```

### Tab pane `#pkb-overview-pane`

Layout:

```
┌──────────────────────────────────────────────────────────────┐
│  [⟳ Regenerate]  [🔍 Scan for gaps]         [✏️ Edit]        │
│                            ⚠️ Overview may be stale           │  ← shown when is_stale
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  # Memory Overview                                           │
│  *Claims: 142 · Contexts: 8 · Entities: 31 · Tags: 19*      │
│                                                              │
│  ## Summary                                                  │
│  ...rendered markdown via marked.js...                       │
│                                                              │
│  ## Key Areas                                                │
│  ...                                                         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Behaviour

- **Lazy load**: Content fetched via `GET /pkb/overview` on first tab open (same lazy pattern as other PKB tabs). Loading spinner while fetching.
- **Render**: Via `marked.js` (same pipeline used in chat message rendering). Applied to `#pkb-overview-content` div.
- **Edit button**: Calls `MarkdownEditorManager.openEditor(rawContent, onSave, {title: 'Edit Memory Overview', saveLabel: 'Save Overview'})`. On save callback: calls `PUT /pkb/overview`, refreshes rendered content, hides stale warning.
- **Regenerate button**: Calls `POST /pkb/overview/regenerate`. Shows spinner on button, disables both action buttons while running. On response: refreshes rendered content, clears stale warning.
- **Scan for gaps button**: Calls `POST /pkb/overview/scan`. Same spinner/disable pattern.
- **Stale warning** (`⚠️ Overview may be stale — last update failed`): `#pkb-overview-stale-warning`, shown when `is_stale === true` in the GET response. Hidden after any successful regenerate, scan, or manual save.
- **Raw markdown preserved**: `rawContent` variable in the tab's JS closure holds the unrendered markdown for passing to the editor. Separate from the rendered HTML in the div.

### JS in `pkb-manager.js`

New functions:
```javascript
function loadOverview()          // GET /pkb/overview, render, show/hide stale warning
function renderOverview(content) // marked.js render into #pkb-overview-content
function saveOverview(content)   // PUT /pkb/overview
function regenerateOverview()    // POST /pkb/overview/regenerate, re-render
function scanOverviewGaps()      // POST /pkb/overview/scan, re-render
```

Tab open event (same pattern as other tabs):
```javascript
$('#pkb-overview-tab').on('shown.bs.tab', function() {
    if (!overviewLoaded) { loadOverview(); overviewLoaded = true; }
});
```

**Note on `overviewLoaded` scope:** `pkb-manager.js` uses the IIFE module pattern (`var PKBManager = (function() { ... })()`). `overviewLoaded` must be declared in the private state section alongside `currentPage`, `pendingMemoryAttachments`, etc. — not as a bare variable. Initialize to `false`.

---

## Chat Retrieval Integration

### How the PKB retrieval pipeline works (summary)

`Conversation.reply()` fires `_get_pkb_context()` async at the start of every reply. It returns `<pkb_item>` XML items prioritised as: referenced → attached → global pinned → conv pinned → auto hybrid search. This entire block goes into a `user_info_text` prompt that two cheap LLMs distill into bullet-point user preferences. After distillation, explicitly `source="referenced"` items are re-injected verbatim. The final `user_info_text` lands in `permanent_instructions` in `chat_slow_reply_prompt`. The OpenCode path uses the same future but injects raw context as a `[USER'S PERSONAL KNOWLEDGE]` noReply message instead of distilling.

### Integration A: `@pkb_overview` reference (mandatory)

The overview is registered as a **pseudo-claim** with a well-known friendly_id `pkb_overview`. It is not stored as a real claim row — instead, `resolve_reference("pkb_overview")` in `StructuredAPI` has a special branch that calls `PKBOverviewManager.get_overview(user_email)` and returns the content wrapped as a mock claim-like object with `claim_type="overview"` and `source="referenced"`.

When the user types `@pkb_overview` in a message:
- `parseMemoryReferences()` captures it as a `friendlyId` (existing regex already matches it — 3+ chars, starts with letter).
- Backend resolves it via the special branch in `resolve_reference()`.
- The full overview content is injected with `source="referenced"` — it bypasses distillation and reaches the main LLM verbatim (same as any other referenced claim).
- This gives the LLM the complete map of what the KB knows, on-demand, without adding token cost to every turn.

**Implementation:** One `if reference_id == "pkb_overview":` branch added near the top of `resolve_reference()` in `structured_api.py`. No schema change.

> **Reserved friendly_id guard:** `generate_friendly_id()` in `utils.py` already checks for reserved suffixes (`_context`, `_entity`, etc.). Add `"pkb_overview"` to the reserved exact-match list so no real claim can accidentally be assigned that friendly_id.

### Integration B: Lightweight Key Areas snippet (config-gated)

A condensed snippet (~100 words) derived from the **Key Areas section only** of the overview is prepended to the auto-retrieved PKB context as a `source="overview_summary"` item at the end of `_get_pkb_context()` — after all other priority levels are collected.

Format injected into the `<pkb_item>` block:
```xml
<pkb_item source="overview_summary" type="overview">
Health (34 claims): morning workouts, peanut allergy. Work (41 claims): Project Alpha, Python stack.
Personal (28 claims): IST timezone, coffee preference. Relationships (12 claims): family, Dr. Smith.
</pkb_item>
```

This is ~50–100 words. The distillation LLM sees it as background context — it knows which domains exist and can weight retrieved specific claims accordingly. It does not bypass distillation (not `source="referenced"`).

**Config gate:** `PKBConfig.overview_snippet_in_context: bool = False` (default off). Enabled via environment variable or config file. The overview snippet is fetched from DB (single row read, no LLM call) and cached for the session.

> **PKBConfig addition:** Add `overview_snippet_in_context: bool = False` to `PKBConfig` in `truth_management_system/config.py`. Document in `api.md` config options table.

**Implementation:** In `_get_pkb_context()`, after collecting all priority levels, if `config.overview_snippet_in_context` and overview content exists: extract Key Areas section via regex, truncate to 150 words, append as a `<pkb_item source="overview_summary">` item.

**Why default off:** The Key Areas section may be stale if overview updates are lagging. Also adds a small token cost to every turn. Users/operators should opt in after verifying the overview stays current.

---

## NL Agent Integration

### What the NL agent currently does

`PKBNLAgent` in `truth_management_system/interface/nl_agent.py` is an iterative JSON-output loop (not native tool-calling, for model compatibility). On each iteration, the LLM outputs `{"thought": "...", "action": "...", "action_input": {...}}` and the agent executes the named action then feeds the observation back as a user message. Loop runs up to `MAX_ITERATIONS=5` with a 30-second timeout.

**Available actions:**
- `search_claims` — hybrid search with optional type/domain filters
- `add_claim` — create claim with full metadata including temporal fields
- `edit_claim` — patch claim fields by ID
- `delete_claim` — soft-delete by ID
- `get_claim` — fetch single claim by ID
- `pin_claim` — pin/unpin
- `resolve_reference` — resolve `@friendly_id`
- `add_entity`, `add_tag`, `list_tags`, `list_entities` — metadata management
- `final_response` — terminal: return message to user
- `ask_clarification` — terminal: pause and ask user for more info (triggers `pkb_propose_memory` modal if claims were already added)

The system prompt injects today's date/year and instructs the agent to use multiple synonym searches for high recall, extract dates from natural language, and require `valid_to` for task/reminder types.

**What it does NOT currently have:**
- Any awareness of the overall shape of the KB (how many claims, what domains, what contexts exist).
- No "map" to guide search strategy — it must blindly try synonyms hoping to find things.
- No context about what kinds of memories the user tends to store, making search queries less targeted.

### How the overview helps the NL agent

The overview's **Key Areas** section tells the agent:
- Which domains are populated and how many claims each has
- What the key topics/keywords are in each domain
- Which contexts exist and what they contain

This directly improves **search quality**: instead of generic synonym exploration, the agent can issue more targeted queries matching the actual terminology in the KB.

Example: Without overview, a user asks `/pkb what do I know about my doctor?` → agent searches "doctor", "physician", "medical", "healthcare"... With overview showing `Health (34 claims): Dr. Smith (cardiologist), peanut allergy, morning workouts`, the agent knows to search "Dr. Smith" directly.

### Implementation

**Where to inject:** In `PKBNLAgent.process()` and `process_streaming()`, when building the initial `messages` list, prepend a condensed overview to the **system prompt** (not as a separate message — it should be part of the agent's background knowledge, not a conversational turn).

> **NL agent routing note:** There are two NL agent classes: `PKBNLAgent` (`truth_management_system/interface/nl_agent.py`) is the core tool-calling loop; `PKBNLConversationAgent` (`agents/pkb_nl_conversation_agent.py`) is the conversation-compatible wrapper used for `/pkb` slash commands. The overview injection goes into `PKBNLAgent` (the core loop) — `PKBNLConversationAgent` delegates to `PKBNLAgent.process_streaming()` internally, so it gets the injection automatically.

**What to inject:** The Key Areas + Table of Contents sections only — not the full overview. ~150 words. This keeps the system prompt short.

**How to get it:** `PKBNLAgent.__init__` already receives `api` (user-scoped `StructuredAPI`). Add an optional `overview_manager: PKBOverviewManager = None` parameter. In `process()`, if `overview_manager` is set, call `overview_manager.get_key_areas_snippet(user_email)` — a new lightweight method that returns only the Key Areas + TOC text without stats injection or full content.

**In `endpoints/pkb.py` (`pkb_nl_command_route`):** When constructing `PKBNLAgent`, also construct a `PKBOverviewManager` and pass it in.

> **Route name note:** The REST route for the NL agent is `POST /pkb/nl_command` (confirmed in `endpoints/pkb.py`). The handler constructs `PKBNLAgent` directly. `PKBNLConversationAgent` (the `/pkb` slash command path in `Conversation.reply()`) also constructs `PKBNLAgent` internally — the `overview_manager` param must be threaded through `PKBNLConversationAgent.__init__` as well, or alternatively `PKBNLConversationAgent` can construct `PKBOverviewManager` itself and pass it to `PKBNLAgent` when it creates it.

**Fallback:** If overview content is `None` (never generated), the agent behaves exactly as today — no change.

**System prompt addition** (appended to `PKB_AGENT_SYSTEM_PROMPT` when overview is available):
```
## Knowledge Base Map
Here is a current map of what is stored in this knowledge base.
Use this to guide your search queries — prefer terms that match the actual content described below.

{key_areas_and_toc}
```

**New method on `PKBOverviewManager`:**
```python
def get_key_areas_snippet(self, user_email: str) -> Optional[str]:
    """
    Returns only the Key Areas + Table of Contents sections from the stored overview.
    Returns None if no overview exists yet.
    Truncated to 200 words to keep NL agent system prompt compact.
    """
```

---



1. **Schema migration** — `pkb_overview` table in `schema.py` + `_migrate_v10_to_v11()` in `database.py`. Bump `SCHEMA_VERSION` to `11`. Verify on a copy of the real DB (current v10 → v11, all claims/audit_log rows preserved, idempotent).
2. **`PKBOverviewManager`** — `overview_manager.py`. Implement and unit-test `generate_full`, `update_from_event`, `_consolidate`, `save`, `get_overview`, `mark_stale`, `get_key_areas_snippet`. Use in-memory DB for tests.
3. **REST endpoints** — 4 new routes in `endpoints/pkb.py` + `_fire_overview_update` helper.
4. **Write hooks** — Add `_fire_overview_update` calls to all 13 write/link endpoints (7 claim endpoints + 6 link endpoints). Verify bulk debouncing.
5. **`@pkb_overview` reference** — Special branch in `resolve_reference()` in `structured_api.py`.
6. **Lightweight snippet in `_get_pkb_context()`** — Config-gated Key Areas injection in `Conversation.py`.
7. **NL agent integration** — `overview_manager` param in `PKBNLAgent.__init__`, snippet injection in `process()` / `process_streaming()`. Wire up in `pkb_nl_command_route`.
8. **`MarkdownEditorManager` refactor** — `options` param, `openInline`, `data-save-btn` in `interface.html`.
9. **UI tab** — Tab 8 HTML + pane in `interface.html`. Overview functions in `pkb-manager.js`. Wire buttons and stale warning.
10. **Integration test** — Add claim → overview updates. `@pkb_overview` in chat → content injected. NL agent with overview → more targeted search queries. Bulk import → one update. Manual edit survives next incremental update.
11. **Documentation** — Update `README.md` version info and file locations. Add section to `implementation_deep_dive.md`.

---

## Files to Create / Modify

| File | Type | Change |
|---|---|---|
| `truth_management_system/schema.py` | Modify | Add `pkb_overview` DDL; `SCHEMA_VERSION = 11` (v10 = audit_log, already exists) |
| `truth_management_system/database.py` | Modify | Add `_migrate_v10_to_v11()` |
| `truth_management_system/interface/overview_manager.py` | **Create** | `PKBOverviewManager`, `OverviewResult`, `OverviewUpdateEvent`, `OverviewStats`; add `get_key_areas_snippet()` |
| `truth_management_system/__init__.py` | Modify | Export `PKBOverviewManager`, `OverviewResult`, `OverviewUpdateEvent` |
| `truth_management_system/interface/structured_api.py` | Modify | Special `@pkb_overview` branch in `resolve_reference()`; add `"pkb_overview"` to reserved friendly_id list in `utils.py` |
| `truth_management_system/config.py` | Modify | Add `overview_snippet_in_context: bool = False` to `PKBConfig` |
| `truth_management_system/interface/nl_agent.py` | Modify | `overview_manager` param in `__init__`; snippet injection in `process()` and `process_streaming()` |
| `agents/pkb_nl_conversation_agent.py` | Modify | Thread `overview_manager` through to `PKBNLAgent` construction (so `/pkb` slash commands also get the KB map) |
| `endpoints/pkb.py` | Modify | 4 new overview routes + `_fire_overview_update` + hooks in 6 write endpoints + pass `overview_manager` to `PKBNLAgent` in `pkb_nl_command_route` |
| `Conversation.py` | Modify | Config-gated Key Areas snippet injection in `_get_pkb_context()` |
| `interface/markdown-editor.js` | Modify | Add `options` param to `openEditor`; add `openInline` function |
| `interface/interface.html` | Modify | Add `data-save-btn` attr to save button; add Tab 8 HTML + pane |
| `interface/pkb-manager.js` | Modify | 5 new overview functions + tab open event binding |
| `truth_management_system/tests/test_overview.py` | **Create** | Unit tests for `PKBOverviewManager` (offline, in-memory DB) |
| `documentation/features/truth_management_system/README.md` | Modify | Update version info, file locations |
| `documentation/features/truth_management_system/implementation_deep_dive.md` | Modify | Add `PKBOverviewManager` section and retrieval/NL agent integration notes |

---

## Testing Plan

### Unit tests (`test_overview.py`, offline — no LLM needed)

- Schema: `pkb_overview` table created on fresh DB and migration from v9.
  > The migration is v10 → v11 (not v9 → v10). The unit test should verify: fresh DB gets `pkb_overview` table at v11; an existing v10 DB (with `audit_log` present) migrates to v11 correctly with `audit_log` intact and `pkb_overview` added; idempotent re-init does not corrupt either table.
- `save()` and `get_raw_content()` round-trip.
- `mark_stale()` sets `is_stale=1`; `save()` clears it.
- `_inject_stats()` correctly replaces the stats template line.
- `word_count` is computed and stored correctly.
- `generate_full()` with mocked LLM call — verify full markdown stored directly (not via `_apply_edits`), result is stored, `is_stale` cleared.
- `update_from_event()` with mocked LLM — verify prompt contains claim statement and current content; `_apply_edits` is called with parsed ops.
- `_apply_edits()` — section parsing, `replace_section` applies correctly, `append_to_section` appends, `insert_section` inserts after anchor, `delete_from_section` removes matched line, `no_change` leaves content unchanged, unmatched section is skipped (not error), all untouched sections preserved verbatim.
- `update_from_event()` with link event — `link_metadata` in event, LLM prompt scoped to TOC/Entities only.
- Consolidation triggers when `word_count > 8000` — verify `_consolidate` is called (mock).
- `get_key_areas_snippet()` returns None when overview content is None.
- `get_key_areas_snippet()` extracts only Key Areas + TOC sections and truncates to 200 words.
- `"pkb_overview"` reserved in `generate_friendly_id()` — verify a statement that would otherwise produce `pkb_overview` as friendly_id gets a different ID.
- Multi-user isolation: overview for user A not returned for user B.

### Integration tests (require LLM key)

- Add a claim → wait for async update → `GET /pkb/overview` shows updated content reflecting new claim's domain.
- Edit a claim → targeted edit op updates only the relevant section, other sections unchanged.
- Delete a claim → overview's Recently Modified updates.
- Link a tag to a claim → overview update fires with `trigger="link"`, TOC or Entities section updated.
- Bulk import 10 claims → one overview update fires (not 10).
- Manual edit via `PUT /pkb/overview` → content saved verbatim, `is_stale` cleared.
- Simulate LLM failure in `update_from_event` → `is_stale=1` set → GET returns `is_stale: true`.
- `POST /pkb/overview/regenerate` → full fresh overview generated → `is_stale` cleared.
- `@pkb_overview` typed in chat message → `resolve_reference("pkb_overview")` returns overview content → injected verbatim with `source="referenced"` into main LLM prompt.
- NL agent invoked via `/pkb what do I know about health?` → system prompt contains KB map from `get_key_areas_snippet()` → first search query more targeted than without map.
- No overview exists yet → NL agent still works (graceful fallback, no exception).

### Manual testing checklist

- [ ] Tab 8 appears in PKB modal, loads on first open
- [ ] Rendered markdown displays correctly (headers, bullets, bold)
- [ ] Stale warning shown/hidden based on `is_stale`
- [ ] Edit button opens `MarkdownEditorManager` modal with correct title/save label
- [ ] Edit modal is isolated — opening message-edit modal in another tab while PKB overview edit modal is open causes no state corruption
- [ ] Saving from editor updates displayed content and calls `PUT /pkb/overview`
- [ ] Regenerate button shows spinner, disables buttons during request
- [ ] Scan button shows spinner, disables buttons during request
- [ ] Existing message-edit callers (chat messages) unaffected by `MarkdownEditorManager` refactor
- [ ] Stats line (Claims: N · Contexts: N · ...) always reflects live DB counts
- [ ] `@pkb_overview` in a chat message injects overview content into the LLM's context
- [ ] No real claim can be given friendly_id `pkb_overview` (reserved guard works)

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM modifies stats line despite instructions | Medium | Strip and re-inject stats line from live DB on every save, both from LLM updates and on GET. Stats line is never trusted from stored content. |
| LLM outputs invalid JSON or ops that match no sections | Medium | `_apply_edits` skips unmatched ops and logs warnings. If output is not parseable JSON at all, mark `is_stale=True` and keep existing content unchanged. Never overwrite with a failed response. |
| LLM rewrites a full section when a targeted edit would suffice | Low | Tool-call format enforces surgical edits — the LLM cannot output the full document, only named operations. `replace_section` is the largest unit of change. |
| Shared editor state corruption (two simultaneous callers) | **Resolved** | Per-modal `_modalStates` registry isolates state per `modalId`. `#message-edit-modal` and `#pkb-overview-edit-modal` are separate DOM elements with separate state buckets. No shared mutable state between callers. |
| Async overview update fires after rapid sequence of edits, overwriting newer state | Low | Last-write-wins is acceptable. The overview is approximate and regeneratable. |
| `openEditor` options refactor breaks existing callers | Low | Existing `openEditor(text, onSave)` calls are unaffected — third param absent means `modalId` defaults to `'message-edit-modal'`, which uses the unchanged module-level state path. |
| First-time `generate_full()` is slow for large KBs | Medium | Show a loading spinner. Cap claims passed to the LLM at 200 — claims beyond 200 are represented only as domain-grouped counts and top keywords (not full statements). The full detail can be added via "Scan for gaps" which passes all raw claims (no cap). This cap applies only to `generate_full()`, not `scan_for_gaps()`. |
| `scan_for_gaps()` is expensive for very large KBs | Medium | Passes full raw claim list (no summarization — user explicitly chose accuracy). For very large KBs (500+ claims), consider paginating or warning the user about latency. Documented as a known trade-off. |
| Tab 8 shifts existing tab indices in JS | Low | Audit `pkb-manager.js` for any tab-index-based selectors before adding Tab 8. Use data attributes or IDs, not indices, for all tab references. |
| Schema version collision with `audit_log` (v10) | **Already addressed** | The `pkb_overview` table is schema v11. `_migrate_v10_to_v11()` must check `schema_version = 10` before running and must not touch the `audit_log` table. Verified on a copy of the real DB before merging. |
