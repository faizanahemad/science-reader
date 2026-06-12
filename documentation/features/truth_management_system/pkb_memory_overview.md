# PKB Memory Overview

**A per-user auto-maintained markdown summary of the entire knowledge base.**

## Motivation

As the PKB grows past a few dozen claims, it becomes difficult for the user (and for the LLM during retrieval) to know *what* is in there. The overview solves this by maintaining a concise, structured document that:
- Gives the user a bird's-eye view of their knowledge base topics
- Provides the LLM with a "map" of available knowledge domains for better retrieval weighting
- Updates itself automatically on every write so it never goes stale

## How it works

### Generation
- **First access** (lazy): opening the Overview tab or triggering `GET /pkb/overview` generates the overview from up to 200 claims via a single cheap LLM call.
- **Regenerate** (button): rewrites the overview from scratch using all claims (no cap after first generation).
- **Scan for gaps** (button): passes all claims + the existing overview to the LLM, asking it to fill missing topics without rewriting the whole document.

### Incremental updates
Every write operation (add, edit, delete, bulk import, link/unlink tags/entities/contexts) fires an async background update. The cheap LLM receives the event + current overview and returns targeted edit ops (`replace_section`, `append_to_section`, `insert_section`, `delete_from_section`, `no_change`). These are applied structurally — only the affected sections change.

### Consolidation
When the overview exceeds 8,000 words, an async consolidation pass condenses it back under 600 words while preserving all section headers and the Table of Contents.

### Stats line
A live stats line (`*Claims: N · Contexts: N · Entities: N · Tags: N · Last updated: DATE*`) is injected at read time from live DB counts — never stale.

## UI

**Tab 8** in the PKB modal (after Claims/Entities/Tags/Conflicts/Bulk Add/Import Text/Contexts):
- Rendered markdown view of the overview
- **Regenerate** button — full rewrite from scratch; shows live progress text on button via NDJSON stream
- **Scan for gaps** button — targeted gap-fill; same streaming progress UX
- **Edit** button — opens a full markdown editor modal (`#pkb-overview-edit-modal`) via `MarkdownEditorManager.openEditor` with isolated state
- Stale warning banner shown when last background update failed
- **Toast notification** surfaced on every tab open if `is_stale` is true: "Overview may need a regenerate — last auto-update failed."
- Tab reloads fresh data on every switch (not just first open) to detect stale state promptly

## Chat integration

### `@pkb_overview` reference
Type `@pkb_overview` in a message to inject the full overview verbatim into the conversation context. Resolved via `resolve_reference()` in `structured_api.py` with a special branch that bypasses the normal claim/context/entity routing.

### Key Areas snippet (config-gated)
When `config.overview_snippet_in_context = True`, a truncated Key Areas + Table of Contents snippet (≤200 words) is appended to the PKB context block sent to the distillation LLM. Default: OFF.

### NL agent KB map
Both `PKBNLAgent.process()` and `process_streaming()` inject the Key Areas snippet into their system prompt as a `## Knowledge Base Map` section, giving the agent awareness of what topics exist in the PKB.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/pkb/overview` | Returns overview content, stats, topics, is_stale, last_updated. Triggers lazy generation on first call. |
| PUT | `/pkb/overview` | Save manual edits. Body: `{"content": "..."}` |
| POST | `/pkb/overview/regenerate` | Full regeneration. Streams NDJSON progress events. |
| POST | `/pkb/overview/scan` | Gap-scan. Streams NDJSON progress events. |
| GET | `/pkb/overview/topics` | Returns structured topics JSON extracted from Key Areas. |

### Streaming protocol (Regenerate/Scan)

Both POST endpoints return `application/x-ndjson` (newline-delimited JSON). Events:
- `{"type": "progress", "message": "Processing 247 claims..."}` — real-time via background thread + queue
- `{"type": "progress", "message": "Generating overview with LLM..."}`
- `{"type": "result", "content": "...", "stats": {...}, "is_stale": false, "last_updated": "..."}` — final payload
- `{"type": "error", "message": "..."}` — on failure

The UI reads the stream with `fetch()` + `ReadableStream` reader and updates the button text live with each progress message.

## Structured topics sidecar

Every `save()` call parses the Key Areas section into a structured JSON array stored in `topics_json`:
```json
[{"name": "Health", "claim_count": 10, "description": "workouts, diet"}, ...]
```
Expected Key Areas format: `- **TopicName** (N claims): description text`

Access via `GET /pkb/overview` (includes `"topics": [...]`) or standalone `GET /pkb/overview/topics`.

Used by the `RewriteSearchStrategy` for overview-informed retrieval: the SUPERFAST_LLM sees these domains and expands queries with domain-relevant terms, boosting recall for the user's primary knowledge areas.

## Schema

**Table: `pkb_overview`** (v11, migration: `_migrate_v10_to_v11`)

| Column | Type | Notes |
|--------|------|-------|
| user_email | TEXT | PK |
| content | TEXT | Raw markdown |
| word_count | INTEGER | Computed on save |
| is_stale | INTEGER | 1 if last update failed |
| last_updated | TEXT | ISO timestamp |
| topics_json | TEXT | JSON array of `{name, claim_count, description}` parsed from Key Areas |

## Key design decisions

- **Derived, not authoritative**: the overview is disposable. It is NOT exported in `portability.py`. Delete and regenerate at any time.
- **No audit hooks**: `save()` and `update_from_event()` do not write to `audit_log` (would create noisy loops).
- **`pkb_overview` is a reserved friendly_id**: `generate_friendly_id()` rejects this exact string to avoid collision with the special `@pkb_overview` reference.
- **Manual edits survive**: user changes from the Edit button persist until the next write-triggered update modifies the same section. Full Regenerate overwrites everything.
- **Async, non-blocking**: all write hooks dispatch via `get_async_future`. The HTTP response is never delayed.
- **One consolidated update per bulk op**: `execute_ingest` and `execute_updates` fire a single overview update for all affected claims, not per-claim.
- **Streaming via queue+thread**: Regenerate/Scan use a background thread that puts progress messages into a `queue.Queue`; the generator yields from the queue. This gives true real-time progress to the client.
- **Regenerate cap logic**: first-time generation (no existing overview) is capped at 200 claims for speed. Subsequent regenerates are uncapped.
- **MarkdownEditorManager modal race**: event handlers (`shown.bs.modal`, save click) are bound BEFORE `modal('show')` is called, preventing the Bootstrap transition race.

## Overview-informed retrieval ranking

The overview's Key Areas section is injected into the search pipeline to improve claim retrieval quality. This works through the `RewriteSearchStrategy`:

### How it works

1. **Before search**, `_get_pkb_context()` in `Conversation.py` loads the Key Areas snippet and calls `search_strategy.set_overview_context(snippet)`.
2. **RewriteSearchStrategy** includes the Key Areas in its LLM prompt, so the fast rewrite LLM (`SUPERFAST_LLM` = `inception/mercury-2`) knows the user's domains and can expand queries with domain-relevant terms.
3. The strategy produces **two outputs** from one LLM call:
   - `fts_query`: optimized keywords for full-text search
   - `embedding_query`: natural-language sentence for vector similarity
4. Both are searched, then merged via RRF internally.

### Three-strategy default

The `HybridSearchStrategy` default is now `["fts", "embedding", "rewrite"]`:
- **fts**: original keyword search (unchanged, no LLM)
- **embedding**: original vector similarity (unchanged, no LLM)
- **rewrite**: LLM-expanded FTS + embedding with overview context

All three run in parallel, then outer RRF merge + recency/confidence re-ranking produces the final ranked list.

### Recency/confidence boost

Post-fusion re-ranking is now active by default:
- `w_recency = 0.15` — recent claims get a mild boost (half-life = 30 days)
- `w_confidence = 0.1` — high-confidence claims get a slight edge
- Formula: `final_score = rrf_score × (recency ^ 0.15) × (confidence ^ 0.1)`

Configurable via env vars `W_RECENCY` and `W_CONFIDENCE`, or in PKBConfig.

## Files modified

- `truth_management_system/schema.py` — DDL + version bump
- `truth_management_system/database.py` — migration dispatch
- `truth_management_system/interface/overview_manager.py` — core module (PKBOverviewManager)
- `truth_management_system/interface/__init__.py` — exports
- `truth_management_system/__init__.py` — exports
- `truth_management_system/config.py` — `overview_snippet_in_context`, `w_recency=0.15`, `w_confidence=0.1`
- `truth_management_system/utils.py` — reserved ID guard
- `truth_management_system/search/rewrite_search.py` — overview-informed FTS+embedding rewrite
- `truth_management_system/search/hybrid_search.py` — default includes rewrite, `set_overview_context` passthrough
- `endpoints/pkb.py` — 5 routes + 13 write hooks + NL wiring
- `truth_management_system/interface/structured_api.py` — `@pkb_overview` resolution
- `Conversation.py` — Key Areas snippet + NL agent wiring + overview context injection before search
- `truth_management_system/interface/nl_agent.py` — KB map injection
- `agents/pkb_nl_conversation_agent.py` — overview_manager pass-through
- `interface/markdown-editor.js` — `_modalStates`, `options` param, `openInline`
- `interface/interface.html` — Tab 8 pane + `#pkb-overview-edit-modal`
- `interface/pkb-manager.js` — overview tab functions
- `truth_management_system/tests/test_overview.py` — 30 unit tests
