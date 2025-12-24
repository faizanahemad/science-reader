# Minimal Personal Knowledge Base (PKB) v0 — Product + Technical Design Doc (No Code)  
  
## 1) What we’re building (in one sentence)  
A **minimal, local-first “claim store”** backed by a single **SQLite** file that lets an AI chatbot **add / edit / delete / search** your “facts” (claims) with **manual contradiction handling** and **interchangeable retrieval strategies** (FTS/BM25, embeddings, LLM map-reduce, LLM query-rewrite → FTS), without building a full-blown Truth Maintenance System yet [SQLite], [Truth maintenance system], [Okapi BM25].  
  
---  
  
## 2) Why this exists (the problem we’re actually solving)  
Chatbots don’t “remember.” They:  
- forget important personal context,  
- repeat questions,  
- contradict earlier statements,  
- and mix sensitive context into unrelated tasks (even if you *think* reranking will prevent that—LLMs are probabilistic, not a privacy boundary).  
  
This v0 system provides a **durable memory layer** that your chatbot can query deterministically (FTS) and semantically (embeddings), while you keep **human control** over what becomes “truth.”  
  
**Non-goal (explicit):** building full propagation, dependency graphs, provenance pipelines, review queues, or automatic truth maintenance. Those come later only if the pilot proves value.  
  
---  
  
## 3) Objectives (v0 success criteria)  
### 3.1 Primary objectives  
1. **Fast capture of durable “claims”** (facts/memories/decisions/preferences/tasks/reminders/habits/observations) into one store.  
2. **Reliable retrieval** for chatbot augmentation:  
   - returns the most relevant claims quickly (FTS/embeddings),  
   - and optionally uses LLMs to rerank / interpret.  
3. **Manual contradiction tracking**:  
   - contradictions can exist,  
   - they are flagged and bucketed,  
   - resolution is manual (for now).  
4. **Minimal operational overhead**:  
   - one SQLite file,  
   - minimal schema,  
   - easy backup (copy one file).  
  
### 3.2 Secondary objectives  
- Provide a clean **upgrade path** to a stronger TMS-style system later (versioning, provenance, propagation) [Truth maintenance system].  
- Support both **structured UI calls** and a **text orchestration endpoint** (the chatbot can call it with natural language).  
  
---  
  
## 4) What it can do (capabilities)  
### 4.1 Core capabilities (must-have)  
- **Create a claim** (manual or LLM-assisted)  
- **Edit a claim**  
- **Soft-delete / retract a claim** (keep it for audit, don’t destroy history)  
- **Add notes** (free-form narrative)  
- **Tagging** (hierarchical tags)  
- **Entity linking** (people/topics/projects linked to claims)  
- **Search** using interchangeable strategies (detailed below)  
- **Contradiction buckets** (“these claims conflict”) tracked manually  
  
### 4.2 What it explicitly will *not* do in v0  
| Capability | Why we’re not doing it now | What replaces it in v0 |  
|---|---|---|  
| **Propagation / ripple updates** | Hard to get right; easy to corrupt memory | Manual edits + search |  
| **Justifications / provenance offsets** | Requires ingestion pipeline and artifact storage | Optional free-text notes + `meta_json` |  
| **Graph dependencies / KG traversal** | Expensive + UI-less management is painful | Tags + entity joins |  
| **Automated conflict resolution** | Risky; can self-gaslight | Manual conflict sets |  
| **Privacy policy enforcement** | You said “everything retrievable”; this is risky | Rely on domain/tags + downstream LLM discipline (weak) |  
  
**Provocative but true:** if you rely purely on “LLM reranking” to prevent leakage (e.g., relationship facts appearing in professional writing), you are building a system that will eventually embarrass you. Even v0 should *at least* support later policy gating cleanly (we’ll keep a hook via `meta_json` and optional `visibility`).  
  
---  
  
## 5) Data model overview (minimal kernel)  
We store **four primary objects** and a few join/utility structures:  
  
1. **Claims** — atomic items you want the chatbot to reuse  
2. **Notes** — longer narrative text  
3. **Entities** — people/topics/projects (canonical names)  
4. **Tags** — hierarchical labels used for filtering and “world/context” approximation  
5. **Join tables** — claim↔tags and claim↔entities  
6. **Conflict sets** — manual contradiction grouping  
7. **FTS indexes** — for fast keyword retrieval (BM25-style scoring) [Full-text search], [Okapi BM25]  
  
---  
  
## 6) Claim semantics (what a “claim” means here)  
A **claim** is a text statement plus metadata; it can optionally carry a lightweight SPO-ish structure.  
  
### 6.1 Required timestamps (your decisions)  
- **`created_at`**: defaults to “now”  
- **`valid_from`**: defaults to **1970-01-01** (or earliest system epoch)  
- **`valid_to`**: nullable (`NULL` means open-ended)  
  
### 6.2 Status rules (v0)  
- MVP search includes:  
  - **`active`**  
  - **`contested`** (but must be returned with warnings)  
  
Validity filtering:  
- **Show everything unless filtered** (so old claims don’t silently disappear).  
- Consumers can optionally filter by time when needed.  
  
---  
  
## 7) Retrieval approach — 4 interchangeable search strategies  
We expose retrieval as a **pluggable strategy interface** so you can A/B test what works.  
  
### 7.1 The four search modes (and how they behave)  
  
| Search mode | How it works | Strengths | Failure modes / risks | Best use |  
|---|---|---|---|---|  
| **S1: LLM map-reduce over claims** | Batch-send claims (+metadata) to an LLM, ask it to score relevance, return top N | Captures nuance, can use metadata creatively | Expensive, slow, nondeterministic, can miss items due to context limits; privacy risk if you send all facts | “Deep thinking” queries with high ambiguity |  
| **S2: FTS / BM25** | Use SQLite FTS to keyword-search claim text + selected fields [SQLite], [Okapi BM25] | Fast, cheap, deterministic-ish, debuggable | Misses fuzzy paraphrases; depends on good wording and tagging | Default retrieval backbone |  
| **S3: Embedding similarity** | Compute query embedding, retrieve nearest claims | Great for vague queries; paraphrase recall | False positives, semantic drift, hard to explain; requires embedding store management | “What did I say about…” type fuzzy recall |  
| **S4: LLM rewrite → FTS/BM25** | LLM rewrites query into keywords/tags; then run S2 | Often boosts recall dramatically | LLM can “invent intent” and add wrong constraints unless logged | Messy long queries; voice transcripts |  
  
### 7.2 Combining strategies (recommended)  
Even in v0, you’ll usually get the best results via:  
- **FTS top-K** + **Embeddings top-K** → merge → **LLM rerank top 30–80**  
- Or: **Rewrite → FTS** as a cheaper alternative to full map-reduce.  
  
**Key principle:** LLMs should **rank and explain** candidates, not be the only retrieval mechanism. Otherwise your “memory” becomes non-reproducible vibes.  
  
---  
  
## 8) Minimal schema (SQLite, single file)  
  
### 8.1 Tables and relationships (high level)  
| Table | Purpose | Key relationships |  
|---|---|---|  
| **`claims`** | Store atomic truths | Links to tags/entities; referenced by conflict members |  
| **`notes`** | Narrative memory | Optional: can be linked in `meta_json` (no FK needed in v0) |  
| **`entities`** | Canonical people/topics/projects | Many-to-many with claims via `claim_entities` |  
| **`tags`** | Hierarchical tags (and “world/context” tags) | Self-referential parent; many-to-many with claims |  
| **`claim_tags`** | Claim↔Tag join | FK to `claims` and `tags` |  
| **`claim_entities`** | Claim↔Entity join with role | FK to `claims` and `entities` |  
| **`conflict_sets`** | Manual contradiction buckets | Has many members |  
| **`conflict_set_members`** | Conflict↔Claim join | FK to `conflict_sets` and `claims` |  
| **`claims_fts`** | FTS index for claims | Mirrors `claims` text fields |  
| **`notes_fts`** | FTS index for notes | Mirrors `notes` text fields |  
  
### 8.2 Column-level schema (with keys & constraints)  
  
#### A) `claims`  
| Column | Type | Required? | Default | Notes |  
|---|---|---:|---|---|  
| **claim_id** | TEXT (UUID) | Yes | — | **Primary Key** |  
| **claim_type** | TEXT | Yes | — | e.g. fact/memory/decision/preference/task/reminder/habit/observation |  
| **statement** | TEXT | Yes | — | Canonical text |  
| subject_text | TEXT | No | NULL | Optional structure |  
| predicate | TEXT | No | NULL | Optional structure |  
| object_text | TEXT | No | NULL | Optional structure |  
| **context_domain** | TEXT | Yes | — | e.g. personal/health/relationships/learning |  
| **status** | TEXT | Yes | `active` | Include `contested` in search with warnings |  
| confidence | REAL | No | NULL | Optional scoring |  
| **created_at** | TEXT | Yes | “now” | ISO-8601 string recommended |  
| **valid_from** | TEXT | Yes | `1970-01-01T00:00:00Z` | Your chosen default |  
| valid_to | TEXT | No | NULL | NULL = open-ended |  
| meta_json | TEXT | No | NULL | Extensible metadata (keywords, extra fields) |  
| updated_at | TEXT | Yes | “now” | Maintain on edits |  
| retracted_at | TEXT | No | NULL | Soft delete marker (optional but useful) |  
  
**Indexes (recommended):**  
- `claims(status)`  
- `claims(context_domain)`  
- `claims(claim_type)`  
- `claims(valid_from, valid_to)`  
- `claims(predicate)` (optional)  
  
#### B) `notes`  
| Column | Type | Required? | Default | Notes |  
|---|---|---:|---|---|  
| **note_id** | TEXT (UUID) | Yes | — | **Primary Key** |  
| title | TEXT | No | NULL | |  
| **body** | TEXT | Yes | — | |  
| context_domain | TEXT | No | NULL | Optional |  
| meta_json | TEXT | No | NULL | |  
| **created_at** | TEXT | Yes | “now” | |  
| **updated_at** | TEXT | Yes | “now” | |  
  
Indexes:  
- `notes(created_at)`  
- `notes(context_domain)`  
  
#### C) `entities`  
| Column | Type | Required? | Default | Notes |  
|---|---|---:|---|---|  
| **entity_id** | TEXT (UUID) | Yes | — | **Primary Key** |  
| **entity_type** | TEXT | Yes | — | person/org/place/topic/project/system |  
| **name** | TEXT | Yes | — | Canonical label |  
| meta_json | TEXT | No | NULL | |  
| created_at | TEXT | Yes | “now” | |  
| updated_at | TEXT | Yes | “now” | |  
  
Constraint:  
- Unique `(entity_type, name)` to prevent duplicates (recommended).  
  
#### D) `tags`  
| Column | Type | Required? | Default | Notes |  
|---|---|---:|---|---|  
| **tag_id** | TEXT (UUID) | Yes | — | **Primary Key** |  
| **name** | TEXT | Yes | — | Tag label |  
| parent_tag_id | TEXT | No | NULL | **Foreign Key → tags(tag_id)** (hierarchy) |  
| meta_json | TEXT | No | NULL | Can store “tag_kind=world/policy/normal” later |  
| created_at | TEXT | Yes | “now” | |  
| updated_at | TEXT | Yes | “now” | |  
  
Constraint:  
- Unique `(name, parent_tag_id)` (recommended).  
  
#### E) Join tables  
**`claim_tags`**  
- Composite **Primary Key**: `(claim_id, tag_id)`  
- Foreign Keys:  
  - `claim_id → claims(claim_id)` (ON DELETE CASCADE)  
  - `tag_id → tags(tag_id)` (ON DELETE CASCADE)  
- Index: `(tag_id)` for reverse lookup  
  
**`claim_entities`**  
- Composite **Primary Key**: `(claim_id, entity_id, role)`  
- Foreign Keys:  
  - `claim_id → claims(claim_id)` (ON DELETE CASCADE)  
  - `entity_id → entities(entity_id)` (ON DELETE CASCADE)  
- `role`: subject/object/mentioned/about_person (TEXT)  
- Index: `(entity_id)`, `(role)` for filtering  
  
#### F) Manual contradiction tracking  
**`conflict_sets`**  
| Column | Type | Required? | Default |  
|---|---|---:|---|  
| **conflict_set_id** | TEXT (UUID) | Yes | — |  
| status | TEXT | Yes | `open` |  
| resolution_notes | TEXT | No | NULL |  
| created_at | TEXT | Yes | “now” |  
| updated_at | TEXT | Yes | “now” |  
  
**`conflict_set_members`**  
- Composite **Primary Key**: `(conflict_set_id, claim_id)`  
- Foreign Keys:  
  - `conflict_set_id → conflict_sets(conflict_set_id)` (ON DELETE CASCADE)  
  - `claim_id → claims(claim_id)` (ON DELETE CASCADE)  
  
### 8.3 FTS virtual tables (for S2 and S4)  
We maintain two FTS indexes [Full-text search]:  
- **`claims_fts`** indexes: `statement`, `predicate`, `object_text`, `context_domain`  
- **`notes_fts`** indexes: `title`, `body`, `context_domain`  
  
**Important limitation:** FTS virtual tables don’t behave like normal tables; you typically keep them in sync via application writes (or later via triggers once CRUD stabilizes).  
  
---  
  
## 9) “Interfaces” we will expose (function-level contract, no code)  
  
### 9.1 Core structured interface (for UI + agents)  
These are the stable “product primitives”:  
  
1. **Add**  
   - `add_claim(params)`    
   - `add_note(params)`    
   - `add_entity(params)`    
   - `add_tag(params)`    
  
2. **Edit**  
   - `edit_claim(claim_id, patch_params)`  
   - `edit_note(note_id, patch_params)`  
   - etc.  
  
3. **Delete (soft)**  
   - `delete_claim(claim_id, mode=retract)`    
     (sets `status='retracted'` and/or `retracted_at`, does not remove row)  
  
4. **Search**  
   - `search(query_text, strategy, filters, k, include_contested=true, validity_filtering=false)`  
   - `strategy ∈ {map_reduce_llm, fts_bm25, embedding, rewrite_then_fts, hybrid}`  
  
5. **Conflict handling**  
   - `create_conflict_set(claim_ids, notes)`  
   - `resolve_conflict_set(conflict_set_id, resolution_notes, actions_taken)`  
  
### 9.2 Text orchestration interface (for chatbot “one endpoint” usage)  
A higher-level entry point that:  
- accepts **plain text** user intent (“add this fact”, “find what I said about X”, “update my preference”),  
- routes to the structured functions above,  
- returns:  
  - action taken (or proposed),  
  - any clarifying questions,  
  - and the objects affected.  
  
**Why this matters:** your chatbot shouldn’t handcraft SQL-ish operations. It should call a single tool and get structured results.  
  
### 9.3 Conversation turn distillation interface (your “memory extraction” workflow)  
A function that takes:  
- `conversation_summary`  
- the latest `(user_message, assistant_message)` turn  
  
And outputs a **proposed memory update plan**:  
- extracted candidate claims  
- dedupe / exact-match checks (FTS + entity/tag filters)  
- “already exists / should update / should retract / conflicts with X”  
- a user confirmation prompt  
- and then (after user response) executes changes.  
  
**Critical safety stance:** in v0, this should default to *propose-first*, not silent writes. Otherwise you’ll create a self-amplifying hallucinated biography.  
  
---  
  
## 10) Configuration (minimal)  
We will support a small config object (file/env-based later) containing:  
  
| Config | Purpose | Example |  
|---|---|---|  
| **db_path** | Location of SQLite file | `~/.pkb/kb.sqlite` |  
| fts_enabled | Toggle FTS usage | true |  
| embedding_enabled | Toggle embedding search | false/true |  
| default_k | Default top-K results | 20 |  
| include_contested_by_default | Your chosen default | true |  
| validity_filter_default | Your chosen default | false (“show everything”) |  
| llm_provider_settings | model name, limits, batch sizes | (kept abstract) |  
  
---  
  
## 11) Build approach (phased, minimal, upgradeable)  
### Phase 0 — Storage kernel  
- SQLite file creation + schema migrations (even if minimal)  
- CRUD for claims/notes/entities/tags  
- Join management (claim_tags, claim_entities)  
- FTS index maintenance on claim/note writes  
  
### Phase 1 — Retrieval strategies  
- Implement S2 (FTS/BM25) first (fast, deterministic baseline)  
- Add S4 (rewrite → FTS) with logging of:  
  - original query  
  - rewritten query  
  - extracted tags/keywords  
- Add S3 (embeddings) if needed  
- Add S1 (LLM map-reduce) last (expensive fallback)  
  
### Phase 2 — Orchestration + distillation  
- Text-to-action router  
- Conversation-turn distillation (propose → user approve → apply)  
  
---  
  
## 12) Known risks / uncomfortable truths (read this before you ship)  
| Risk | Why it will happen | Mitigation in v0 |  
|---|---|---|  
| **LLM retrieval inconsistency** | Same query can yield different ranked outputs | Keep FTS as backbone; log rewrite prompts/outputs |  
| **Privacy leakage** | Rerankers are not policy enforcement | At minimum: encode “sensitive-ness” as tags/domains consistently; later add deterministic gating |  
| **Duplicate / near-duplicate claims** | Manual entry + LLM extraction will repeat | Use entity+tag normalization + FTS “similar matches” prompt |  
| **Contested claims pollute answers** | If included, they can confuse the chatbot | Always label contested results and prefer active unless user asks |  
| **Schema regret** | You’ll want provenance/versioning sooner than expected | Keep `meta_json`, keep soft delete, keep conflict sets |  
  
---  
  
## 13) Final decisions locked (from your latest message)  
- Storage: **single SQLite file** [SQLite]  
- Tasks/reminders: **stored as `claim_type` within `claims`** (Option 1)  
- Search defaults:  
  - include **`contested`** claims **with warnings**  
  - **no validity filtering by default** (show everything unless filtered)  
- Retrieval supports four strategies (S1–S4) and hybrids.  
  
---  
  
## 14) What I still recommend (even if you ignore it now)  
You previously chose “no sensitivity levels.” Fine for a pilot—but if you store relationship/health/finance notes, you’re gambling.  
  
A near-zero-cost future-proofing move is:  
- encode a simple `visibility` marker inside `meta_json` (e.g., `"visibility":"restricted"`),  
- and teach the chatbot to exclude it unless explicitly requested.  
  
That’s not “extra engineering.” That’s basic self-defense.  
  
---  
  
If you want, I can rewrite this doc into:  
1) a tighter **PRD-style** version (user stories + acceptance criteria), and    
2) a separate **Data Dictionary** (every column, allowed values, invariants),    
so a new engineer can implement it without interpretation drift.  
  
  
<details  id='details-4895e504'>  
<summary><strong>📝 TLDR Summary (Quick Read)</strong></summary>  
  
Here's a TLDR of the Minimal Personal Knowledge Base (PKB) v0 design:  
  
This project aims to build a **minimal, local-first "claim store"** using a single **SQLite** file to provide a durable memory layer for AI chatbots. The core problem it solves is chatbots' inability to remember personal context, leading to repetition, contradictions, and potential leakage of sensitive information. The v0 system focuses on fast capture of "claims" (facts, memories, tasks), reliable retrieval for chatbot augmentation, and manual contradiction tracking, all with minimal operational overhead. It explicitly avoids complex features like full propagation, dependency graphs, or automated conflict resolution in this initial phase.  
  
The system's capabilities include creating, editing, and soft-deleting claims, adding notes, tagging, entity linking, and using **four interchangeable search strategies**: LLM map-reduce, FTS/BM25, embedding similarity, and LLM query rewrite combined with FTS/BM25. The recommended approach for retrieval is a hybrid of FTS/BM25 and embeddings, followed by LLM reranking. Claims will have `created_at`, `valid_from` (defaulting to 1970-01-01), and nullable `valid_to` timestamps. Search will include `active` and `contested` claims (with warnings), and will show everything by default unless explicitly filtered by validity. Tasks and reminders will be stored as a `claim_type` within the `claims` table.  
  
The minimal SQLite schema includes tables for `claims`, `notes`, `entities`, `tags`, and join tables (`claim_tags`, `claim_entities`). It also incorporates `conflict_sets` for manual contradiction tracking and **FTS virtual tables** (`claims_fts`, `notes_fts`) for efficient keyword search. The system will expose structured interfaces for `add`, `edit`, `delete` (soft), `search`, and `conflict handling`, alongside a text orchestration interface for chatbots and a conversation turn distillation interface to propose memory updates for user approval.  
  
**Key Takeaways & Learnings:**  
  
The v0 PKB prioritizes a simple, single-file SQLite solution for durable chatbot memory. It emphasizes deterministic retrieval (FTS/BM25) over purely LLM-based methods, which are seen as inconsistent and risky for privacy. Manual contradiction resolution and user approval for memory updates are crucial safety measures. While not fully implemented in v0, encoding a `visibility` marker in `meta_json` for claims is a recommended, low-cost future-proofing step against privacy leakage, especially for sensitive data. Avoid relying solely on LLM reranking for privacy enforcement.  
  
<button class='details-close-btn' data-details-id='details-{hashString}'>Close</button>  
</details>  
  
  
  
  
---
---

# PKB v0 — **Data Dictionary** (Minimal SQLite “Claim Store”)  
  
This is the **implementation-grade** data dictionary for the minimal PKB v0 we agreed on: **Claims + Notes + Entities + Tags + joins + manual conflicts + FTS indexes** in a **single SQLite file** [SQLite]. It’s written to minimize “interpretation drift” for a new engineer.  
  
---  
  
## 0) Global conventions (apply everywhere)  
  
### 0.1 Identifiers  
- All primary keys are **TEXT** UUIDs (generated by app).  
- **Never reuse** IDs (even after soft delete).  
  
### 0.2 Timestamps and time validity  
- All timestamps are **ISO-8601 strings** in UTC recommended (e.g., `2025-12-23T04:07:37Z`).  
- `created_at`: defaults to “now” (app-side default).  
- `updated_at`: must update on *every* edit.  
- `valid_from`: defaults to **`1970-01-01T00:00:00Z`**.  
- `valid_to`: nullable; `NULL` means “open-ended”.  
  
**Invariant (validity interval):**  
- If `valid_to` is not NULL, then `valid_to >= valid_from`.  
  
### 0.3 Soft deletion / retraction  
- We do **not** hard-delete claims in normal operation.  
- Retraction is represented by:  
  - `status = 'retracted'` and/or  
  - `retracted_at` set (recommended to set both).  
  
### 0.4 JSON metadata  
- `meta_json` fields store **extensible metadata** as JSON serialized to TEXT.  
- **Invariant:** must be either NULL or valid JSON.  
- Recommended keys (non-enforced in v0 but strongly encouraged):  
  - `keywords: string[]` (LLM-generated)  
  - `source: string` (e.g., `"manual"`, `"chat_distillation"`)  
  - `visibility: "default" | "restricted" | "shareable"` (you said “no sensitivity system”, but keeping a hook is wise)  
  - `llm: { model, prompt_version, confidence_notes }`  
  
> Critical note: relying on LLM reranking for privacy is probabilistic and will fail eventually. Even if you won’t *enforce* privacy now, preserving `visibility` in metadata keeps the migration cheap later.  
  
---  
  
## 1) Table-by-table Data Dictionary  
  
## 1.1 `claims` — the atomic memory units  
  
**Purpose:** Store “truth atoms” (facts/memories/decisions/preferences/tasks/reminders/habits/observations), with optional SPO-ish structure and time validity.  
  
### Columns  
  
| Column | Type | Required | Default | Allowed values | Meaning / Notes |  
|---|---|---:|---|---|---|  
| **claim_id** | TEXT | Yes | — | UUID | Primary key |  
| **claim_type** | TEXT | Yes | — | default set: `fact, memory, decision, preference, task, reminder, habit, observation` (extensible) | Claim category; keep extensible (do not hard-enum in DB unless you want migrations) |  
| **statement** | TEXT | Yes | — | non-empty | Canonical human-readable claim |  
| subject_text | TEXT | No | NULL | — | Optional structure (free text) |  
| predicate | TEXT | No | NULL | — | Optional structure (free text). Useful for contradictions later. |  
| object_text | TEXT | No | NULL | — | Optional structure (free text) |  
| **context_domain** | TEXT | Yes | — | examples: `personal`, `health`, `relationships`, `learning`, `life_ops` | Primary domain bucket (used in filtering/boosting) |  
| **status** | TEXT | Yes | `active` | see §1.1.1 | Lifecycle state |  
| confidence | REAL | No | NULL | typically $0.0 \dots 1.0$ | Optional; treat as advisory only |  
| **created_at** | TEXT | Yes | now | ISO-8601 | Creation time |  
| **updated_at** | TEXT | Yes | now | ISO-8601 | Last modification time |  
| **valid_from** | TEXT | Yes | 1970 epoch | ISO-8601 | When claim begins being applicable |  
| valid_to | TEXT | No | NULL | ISO-8601 or NULL | When claim stops being applicable |  
| meta_json | TEXT | No | NULL | JSON or NULL | Extensible metadata |  
| retracted_at | TEXT | No | NULL | ISO-8601 or NULL | Optional explicit retraction timestamp |  
  
### 1.1.1 `claims.status` allowed values + invariants  
  
| Status | Included in MVP search by default? | Meaning | Invariants / expectations |  
|---|---:|---|---|  
| **active** | Yes | Believed true / usable | default state |  
| **contested** | Yes (**with warnings**) | Contradiction suspected or known | retrieval must label as contested |  
| historical | No (unless filtered) | Past truth, still useful | typically `valid_to` set (but not required in v0) |  
| superseded | No (unless filtered) | Replaced by a newer claim | ideally also has `valid_to` set |  
| retracted | No (unless filtered) | Withdrawn / incorrect | set `retracted_at` recommended |  
| draft | No (unless filtered) | Not ready for use | for incomplete capture |  
  
**Critical retrieval invariants:**  
- Default search returns `status IN ('active','contested')`.  
- Returned `contested` claims must include a **warning label** (UI/agent responsibility).  
- **Validity filtering is OFF by default**: do *not* hide old claims automatically unless filters specify time constraints.  
  
### 1.1.2 Indexing expectations (for engineer)  
Even in minimal v0, engineer should create conventional indexes:  
- `status`, `context_domain`, `claim_type`, `(valid_from, valid_to)`, optional `predicate`.  
  
---  
  
## 1.2 `notes` — narrative storage (optional but useful)  
  
**Purpose:** Store longer, unstructured text blobs that can be searched and optionally referenced in `meta_json` (we are not enforcing FK links from claims to notes in v0).  
  
| Column | Type | Required | Default | Allowed values | Meaning |  
|---|---|---:|---|---|---|  
| **note_id** | TEXT | Yes | — | UUID | Primary key |  
| title | TEXT | No | NULL | — | Optional |  
| **body** | TEXT | Yes | — | non-empty | Full note text |  
| context_domain | TEXT | No | NULL | same domain convention as claims | Optional |  
| meta_json | TEXT | No | NULL | JSON or NULL | Optional metadata |  
| **created_at** | TEXT | Yes | now | ISO-8601 | Creation time |  
| **updated_at** | TEXT | Yes | now | ISO-8601 | Last modification time |  
  
**Invariant:** `updated_at >= created_at` (lexicographically true only if consistent ISO format; enforce in app if needed).  
  
---  
  
## 1.3 `entities` — canonical people/topics/projects  
  
**Purpose:** Normalize references like “mom”, “John”, “project Atlas” to an `entity_id` for linking and filtering.  
  
| Column | Type | Required | Default | Allowed values | Meaning |  
|---|---|---:|---|---|---|  
| **entity_id** | TEXT | Yes | — | UUID | Primary key |  
| **entity_type** | TEXT | Yes | — | recommended: `person`, `org`, `place`, `topic`, `project`, `system`, `other` | Keep extensible |  
| **name** | TEXT | Yes | — | non-empty | Canonical display name |  
| meta_json | TEXT | No | NULL | JSON or NULL | Optional attributes |  
| **created_at** | TEXT | Yes | now | ISO-8601 | Creation time |  
| **updated_at** | TEXT | Yes | now | ISO-8601 | Last modification time |  
  
**Uniqueness recommendation (not philosophically perfect but practical):**  
- Unique `(entity_type, name)` to reduce duplicates.  
- If you expect many alias collisions, add aliases later; for v0 this is enough.  
  
---  
  
## 1.4 `tags` — hierarchical tags (also “worlds” later if desired)  
  
**Purpose:** Lightweight organization + filtering + soft context boundaries. Hierarchy is supported via `parent_tag_id`.  
  
| Column | Type | Required | Default | Allowed values | Meaning |  
|---|---|---:|---|---|---|  
| **tag_id** | TEXT | Yes | — | UUID | Primary key |  
| **name** | TEXT | Yes | — | non-empty | Tag label (e.g., `relationships`, `health/sleep`) |  
| parent_tag_id | TEXT | No | NULL | references `tags.tag_id` | Parent for hierarchy |  
| meta_json | TEXT | No | NULL | JSON or NULL | Optional metadata (e.g., tag kind: `world`, `policy`, etc.) |  
| **created_at** | TEXT | Yes | now | ISO-8601 | Creation time |  
| **updated_at** | TEXT | Yes | now | ISO-8601 | Last modification time |  
  
**Hierarchy invariants:**  
- `parent_tag_id` must exist or be NULL.  
- Prevent cycles (SQLite won’t enforce this; must be app logic). If you don’t, hierarchy becomes garbage quickly.  
  
**Uniqueness recommendation:**  
- Unique `(name, parent_tag_id)`.  
  
---  
  
## 1.5 `claim_tags` — many-to-many linking (claims ↔ tags)  
  
**Purpose:** A claim can have many tags; a tag can apply to many claims.  
  
| Column | Type | Required | Default | Meaning |  
|---|---|---:|---|---|  
| **claim_id** | TEXT | Yes | — | FK → `claims.claim_id` |  
| **tag_id** | TEXT | Yes | — | FK → `tags.tag_id` |  
  
**Keys / invariants**  
- Primary key: `(claim_id, tag_id)` (no duplicates).  
- On delete:  
  - If claim is deleted (rare), cascade delete rows.  
  - If tag is deleted, cascade delete rows.  
  
---  
  
## 1.6 `claim_entities` — many-to-many linking with **role**  
  
**Purpose:** Attach entities to claims with a semantic role (subject/object/mentioned/about_person), matching your earlier “roles” requirement.  
  
| Column | Type | Required | Default | Allowed values | Meaning |  
|---|---|---:|---|---|---|  
| **claim_id** | TEXT | Yes | — | — | FK → `claims.claim_id` |  
| **entity_id** | TEXT | Yes | — | — | FK → `entities.entity_id` |  
| **role** | TEXT | Yes | — | `subject`, `object`, `mentioned`, `about_person` | Link semantics |  
  
**Keys / invariants**  
- Primary key: `(claim_id, entity_id, role)` (avoid duplicates).  
- Recommended: enforce role allowed values in app (SQLite CHECK optional).  
  
---  
  
## 1.7 `conflict_sets` — manual contradiction buckets  
  
**Purpose:** Manual tracking of contradictions: “these claims conflict”, without building full automated truth maintenance [Truth maintenance system].  
  
| Column | Type | Required | Default | Allowed values | Meaning |  
|---|---|---:|---|---|---|  
| **conflict_set_id** | TEXT | Yes | — | UUID | Primary key |  
| **status** | TEXT | Yes | `open` | `open`, `resolved`, `ignored` | Resolution lifecycle |  
| resolution_notes | TEXT | No | NULL | — | What the user decided and why |  
| **created_at** | TEXT | Yes | now | ISO-8601 | Creation time |  
| **updated_at** | TEXT | Yes | now | ISO-8601 | Last modification time |  
  
**Invariant:** If `status='resolved'`, `resolution_notes` should usually be non-null (enforce in app; DB won’t).  
  
---  
  
## 1.8 `conflict_set_members` — link claims into a conflict set  
  
| Column | Type | Required | Default | Meaning |  
|---|---|---:|---|---|  
| **conflict_set_id** | TEXT | Yes | — | FK → `conflict_sets.conflict_set_id` |  
| **claim_id** | TEXT | Yes | — | FK → `claims.claim_id` |  
  
**Keys / invariants**  
- Primary key: `(conflict_set_id, claim_id)`  
- A conflict set should have **≥ 2 members** (enforce in app).  
  
---  
  
## 1.9 Full-text search (FTS) virtual tables  
  
These are **indexes**, not authoritative storage [Full-text search]. They enable S2 (FTS/BM25) and S4 (LLM rewrite → FTS/BM25). SQLite FTS5 scoring is commonly associated with BM25-style ranking [Okapi BM25], [SQLite].  
  
### 1.9.1 `claims_fts`  
**Purpose:** Full-text index for claims.  
  
**Indexed content (recommended):**  
- `statement`  
- `predicate`  
- `object_text`  
- `context_domain`  
  
**FTS invariants (critical operational rules):**  
- Every insert/update/delete to `claims` must be reflected in `claims_fts`.  
- If you don’t keep this in sync, search results will become “haunted” (missing new claims and returning deleted ones).  
  
### 1.9.2 `notes_fts`  
**Purpose:** Full-text index for notes.  
  
**Indexed content (recommended):**  
- `title`  
- `body`  
- `context_domain`  
  
**Same sync invariant** as `claims_fts`.  
  
> You asked for “no code”; fine. But a new engineer must implement *some* sync mechanism (application-managed updates or DB triggers). If they hand-wave this, retrieval quality collapses.  
  
---  
  
## 2) Cross-table invariants (system-level rules)  
  
These are “must obey” behavioral rules, even if SQLite doesn’t enforce them:  
  
### 2.1 Search default behavior (MVP)  
| Rule | Value (locked from your spec) |  
|---|---|  
| Default statuses included | `active` + `contested` |  
| Contested handling | Included **with warnings** |  
| Validity filtering by default | **Off** (show everything unless filtered) |  
  
### 2.2 Claim lifecycle consistency  
- If a claim becomes `retracted`, it should not be returned in default search.  
- If a claim becomes `historical` / `superseded`, it should not be returned in default search.  
- `updated_at` must change on any mutation.  
  
### 2.3 Domain + tags usage discipline  
- `context_domain` should be **present and meaningful**, not junk. Otherwise you lose your easiest filtering primitive.  
- Tags should not be used as freeform duplicates of domains; treat tags as *orthogonal facets*.  
  
---  
  
## 3) “Allowed values” reference tables (for engineer quick copy)  
  
### 3.1 Default `claim_type` set (extensible)  
| Value | Meaning |  
|---|---|  
| fact | stable-ish assertions (“My home city is Bengaluru”) |  
| memory | subjective / episodic (“I enjoyed that restaurant”) |  
| decision | commitments (“I decided to avoid X”) |  
| preference | likes/dislikes (“I prefer morning workouts”) |  
| task | actionable work item (“Buy medication”) |  
| reminder | future prompt (“Remind me to call mom Friday”) |  
| habit | recurring behavior target (“Sleep by 11pm”) |  
| observation | low-commitment notes (“Noticed knee pain after running”) |  
  
### 3.2 `role` values (`claim_entities.role`)  
| Role | Meaning |  
|---|---|  
| subject | primary subject |  
| object | object/target |  
| mentioned | referenced in text |  
| about_person | the “about_person_id” equivalent pattern |  
  
### 3.3 `status` values (`claims.status`)  
| Status | Default-search? | Notes |  
|---|---:|---|  
| active | Yes | normal |  
| contested | Yes | must warn |  
| draft | No | incomplete |  
| historical | No | past truth |  
| superseded | No | replaced |  
| retracted | No | withdrawn |  
  
### 3.4 `conflict_sets.status`  
| Value | Meaning |  
|---|---|  
| open | unresolved |  
| resolved | user decided outcome |  
| ignored | acknowledged but intentionally left |  
  
---  
  
## 4) What a new engineer is likely to screw up (so you can prevent it)  
  
| Likely mistake | Why it’s bad | What to enforce |  
|---|---|---|  
| Treating FTS as “eventually consistent” | Search becomes unreliable and you stop trusting memory | Make FTS sync part of CRUD invariants |  
| Allowing tag hierarchy cycles | Breaks hierarchical filtering forever | Enforce “no cycles” in app logic |  
| Using local-time / inconsistent timestamps | Validity filters and ordering get corrupted | Standardize ISO UTC strings |  
| Treating `contested` as normal | Assistant will confidently answer from disputed memory | Always attach warning + prefer `active` in ranking |  
| Stuffing everything into `meta_json` and ignoring typed columns | You lose filterability and performance | Keep core fields in columns; `meta_json` for extras |  
  
---  
  
## 5) Optional (but very low-cost) future-proofing fields  
  
You said “no sensitivity system”, but I’ll be blunt: **that’s self-deception if you store intimate facts**. If you refuse a first-class column, at least standardize a metadata key:  
  
- `meta_json.visibility`: `"default" | "restricted" | "shareable"`  
  
This does not change current behavior, but it prevents you from painting yourself into a corner later.  
  
---  
  
## 6) Quick checklist: “Done means implemented correctly”  
  
1. All tables exist with PK/FK relationships as described.  
2. CRUD updates always update `updated_at`.  
3. `valid_from` defaults to epoch; `created_at` defaults to now.  
4. Default search returns `active + contested`, and contested is visibly warned.  
5. No validity filtering unless filter explicitly applied.  
6. FTS indexes are always synced (claims + notes).  
  
---  
  
If you want, I can produce a **second document** right after this: **“API Contract Dictionary”** (structured parameters + expected outputs for `add/edit/delete/search`, plus the text-orchestration router and the conversation-turn distillation function). That’s usually where “interpretation drift” hurts even more than schema.  
  
  
<details  id='details-8dbc91ce'>  
<summary><strong>📝 TLDR Summary (Quick Read)</strong></summary>  
  
Here's a TLDR of the PKB v0 Data Dictionary:  
  
The PKB v0 Data Dictionary outlines a minimal SQLite schema for a "Claim Store" focusing on `claims`, `notes`, `entities`, `tags`, and manual conflict tracking, all within a single SQLite file.  
  
**Key Data Model & Conventions:**  
*   **Claims:** Core "truth atoms" with `claim_id`, `claim_type`, `statement`, `context_domain`, `status` (active, contested, historical, superseded, retracted, draft), `valid_from` (defaulting to 1970 epoch), and nullable `valid_to`. `meta_json` is for extensible metadata, including a recommended `visibility` field for future privacy.  
*   **Identifiers & Timestamps:** All primary keys are TEXT UUIDs. Timestamps are ISO-8601 UTC, with `created_at` and `updated_at` (must update on every edit).  
*   **Soft Deletion:** Retraction uses `status = 'retracted'` and `retracted_at`. Hard deletes are avoided.  
*   **Notes:** For unstructured text, linked via `meta_json` (no direct FK in v0).  
*   **Entities:** Canonical references (person, org, topic) with `entity_id`, `entity_type`, and `name`.  
*   **Tags:** Hierarchical organization (`tag_id`, `name`, `parent_tag_id`).  
*   **Linking Tables:** `claim_tags` (many-to-many claims ↔ tags) and `claim_entities` (claims ↔ entities with a `role` like `subject`, `object`).  
*   **Conflict Sets:** `conflict_sets` and `conflict_set_members` manually group conflicting claims, with a `status` (`open`, `resolved`, `ignored`).  
  
**Search & Invariants:**  
*   **FTS5:** `claims_fts` and `notes_fts` virtual tables provide full-text search (BM25-style ranking) for efficient retrieval. **Crucially, these FTS tables must be kept in sync with their source tables on every CRUD operation.**  
*   **Default Search:** Returns `active` and `contested` claims. `Contested` claims **must** be flagged with warnings. Validity filtering is OFF by default; all claims are shown unless explicitly filtered by time.  
*   **Cross-table Invariants:** Emphasizes consistent timestamp usage, `updated_at` on all mutations, and disciplined use of `context_domain` and tags for effective filtering.  
  
**Key Takeaways & Guardrails for Implementation:**  
A new engineer must prioritize **strict FTS sync** to prevent unreliable search results. Avoid tag hierarchy cycles. Standardize on **ISO-8601 UTC timestamps**. Always warn users about `contested` claims. While `meta_json` offers flexibility, use typed columns for core, filterable data. **Crucially, despite initial claims of "no sensitivity system," include a `meta_json.visibility` field (`default`, `restricted`, `shareable`) for future-proofing privacy, as relying solely on LLM reranking for sensitive data is a significant risk.**  
  
<button class='details-close-btn' data-details-id='details-{hashString}'>Close</button>  
</details>  
  
  
  
  
