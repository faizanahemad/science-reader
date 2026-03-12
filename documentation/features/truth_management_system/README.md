# Truth Management System (PKB v0) - Documentation

**Personal Knowledge Base for LLM Chatbot Integration**

This directory contains comprehensive documentation for the Truth Management System (PKB), a SQLite-backed personal knowledge base designed for LLM chatbot applications.

---

## Documentation Files

### 📋 [truth_management_system_requirements.md](./truth_management_system_requirements.md)
**Product Requirements & Design Specification**

Complete product specification including:
- System objectives and success criteria
- Data model design (claims, notes, entities, tags, conflicts)
- Search strategies (FTS/BM25, embeddings, LLM rewrite, map-reduce)
- Schema definitions with detailed data dictionary
- Interface contracts
- Configuration options
- Known risks and limitations

**When to use:** Understanding the product vision, data model design decisions, and original requirements.

---

### 🔗 [pkb_reference_resolution_flow.md](./pkb_reference_resolution_flow.md)
**PKB Reference Resolution: Complete Technical Guide**

End-to-end documentation of how @references work:
- Database structure (claims, contexts, IDs)
- ID types and formats (UUID, claim_number, friendly_id, context name)
- UI parsing (`parseMemoryReferences()` in JavaScript)
- Backend resolution (`resolve_reference()` in Python)
- Context resolution (recursive SQL queries)
- LLM context formatting and priority system
- Post-distillation re-injection to preserve explicitly referenced claims
- Complete data flow diagrams

**When to use:** Understanding how `@ssdva` or `@claim_42` gets resolved, debugging reference issues, implementing new reference features.

---

### 🏗️ [implementation.md](./implementation.md)
**Implementation Guide & Module Overview**

High-level technical documentation covering:
- File tree structure and organization
- Module responsibilities and dependencies
- CRUD layer abstractions
- Search strategies overview
- Interface layer components
- External integrations (Flask, Conversation.py, Frontend)
- Multi-user implementation approach
- Schema migration
- Logging and debugging

**When to use:** Quick reference for file locations, module structure, and understanding what each component does.

---

### 🔍 [implementation_deep_dive.md](./implementation_deep_dive.md)
**Comprehensive Technical Deep Dive**

In-depth technical documentation including:
- **Architecture Overview**: System layers, component interactions
- **Auto-Fill / Statement Analysis (v0.7+)**: Shared LLM-powered single-call extraction for the Add Memory modal "Auto-fill" button and text ingestion enrichment
- **Module Structure**: Detailed file-by-file responsibilities
- **Data Flow Patterns**: Complete flows for add, search, memory update, attachment
- **Integration Patterns**: Flask server, Conversation.py, frontend integration
- **API Surface**: All REST endpoints with examples
- **Frontend Architecture**: JavaScript module structure, UI patterns
- **Multi-User Implementation**: Schema design, CRUD integration, API layer
- **Memory Attachment System**: All attachment mechanisms explained
- **Search Architecture**: Strategy comparison, RRF algorithm, FTS patterns
- **Common Development Patterns**: How to add endpoints, CRUD operations, search strategies
- **Testing Strategy**: Unit test patterns, integration tests, manual testing checklist
- **Troubleshooting Guide**: Common issues with diagnosis and solutions

**When to use:** Development work, debugging, understanding data flows, implementing new features, troubleshooting issues.

---

### 📚 [api.md](./api.md)
**Public API Reference**

Complete API documentation including:
- Quick start guide
- Configuration options
- StructuredAPI methods with examples
- Claims, Notes, Entities, Tags, Conflicts APIs
- Search API with filters and strategies
- Bulk operations (add_claims_bulk, text ingestion)
- Statement analysis / auto-fill (`POST /pkb/analyze_statement`)
- Conversation distillation
- Natural language orchestration
- Data type reference (claim types, domains, statuses)
- LLM helpers
- REST endpoints reference
- Frontend JavaScript API
- Deliberate memory attachment APIs
- Error handling and troubleshooting
- Chatbot integration patterns

**When to use:** Implementing features that use the PKB API, integrating with other systems, understanding function signatures and parameters.

---

### 🚀 [PKB_V07_UNIVERSAL_REFERENCES_PLAN.md](./PKB_V07_UNIVERSAL_REFERENCES_PLAN.md)
**v0.7 Plan: Universal @References for Entities, Tags, and Domains**

Design plan for extending @references to all PKB object types:
- Type-suffixed friendly IDs (`_context`, `_entity`, `_tag`, `_domain`) to eliminate namespace clashes
- Suffix-based routing for fast backend resolution
- DB schema changes (v7): friendly_id on entities and tags
- CRUD additions: `get_by_friendly_id()`, `search_friendly_ids()`, `resolve_claims()` for entities and tags
- Recursive tag resolution (like contexts)
- Domain references by query-time filtering
- Migration strategy for existing contexts (append `_context` suffix)
- Backwards compatibility with existing claim/context references
- Complete implementation plan with milestones and testing

**When to use:** Planning or implementing v0.7 universal references. Understanding the namespace disambiguation design.

---

## Quick Navigation

### By Use Case

**I want to understand the product:**
→ Start with [truth_management_system_requirements.md](./truth_management_system_requirements.md)

**I want to see the file structure:**
→ Check [implementation.md - File Tree Structure](./implementation.md#file-tree-structure)

**I want to add a new endpoint:**
→ See [implementation_deep_dive.md - Pattern 1: Adding a New Endpoint](./implementation_deep_dive.md#pattern-1-adding-a-new-endpoint)

**I want to understand the search system:**
→ Read [implementation_deep_dive.md - Search Architecture](./implementation_deep_dive.md#search-architecture)

**I want to use the API in my code:**
→ Refer to [api.md](./api.md)

**I want to debug an issue:**
→ Check [implementation_deep_dive.md - Troubleshooting Guide](./implementation_deep_dive.md#troubleshooting-guide)

**I want to understand data flows:**
→ See [implementation_deep_dive.md - Data Flow Patterns](./implementation_deep_dive.md#data-flow-patterns)

**I want to integrate with the chat system:**
→ Read [implementation_deep_dive.md - Pattern B: Conversation.py Integration](./implementation_deep_dive.md#pattern-b-conversationpy-integration)

---

## Key Concepts

### Claims
Atomic memory units representing facts, preferences, decisions, tasks, etc. Each claim has:
- Statement (the actual text)
- Friendly ID: user-facing alphanumeric ID (e.g. `@morning_workouts_a3f2`) for easy referencing
- Type (fact, preference, decision, etc.) — can have multiple types, dynamically extensible
- Domain (personal, health, work, etc.) — can have multiple domains, dynamically extensible
- Status (active, contested, historical, expired, etc.)
- Temporal validity (valid_from, valid_to) — **mandatory for task and reminder types**
- Metadata (tags, entities, confidence)

### Contexts (Groups)
Hierarchical grouping of claims for organization:
- Contexts can contain claims (many-to-many) and sub-contexts (tree hierarchy)
- Referenced in chat via `@context_friendly_id` which resolves to all contained claims
- Managed through UI: create, expand to see claims, attach/detach claims
- Assignable from the Create/Edit Memory modal

### Multi-User Support
All data is scoped by `user_email`. The system provides:
- Per-user data isolation in shared database
- User-scoped CRUD operations
- User-filtered search results
- Per-user unique constraints

### Search Strategies
Multiple search approaches available:
- **FTS** (Full-Text Search): Fast, deterministic, BM25 ranking
- **Embedding**: Semantic similarity via cosine distance
- **Rewrite**: LLM rewrites query into keywords
- **MapReduce**: LLM scores candidates
- **Hybrid**: Combines strategies with RRF merging

### Memory Attachment
Ways to force specific memories into LLM context:
1. **@friendly_id** references — resolved as claim or context (highest priority)
2. **@memory:uuid** references — legacy syntax (highest priority)
3. Global pinning (medium-high priority)
4. Conversation pinning (medium priority)
5. Auto-retrieval via search (normal priority)

### PKB Slash Commands
Create memories and PKB objects directly from the chat input without leaving the conversation:
- **`/create-memory <text>`** — opens Add Memory modal pre-filled with text and auto-fires LLM analysis (auto-fill) to classify type, domain, tags, possible questions. User reviews and saves.
- **`/create-simple-memory <text>`** — silently classifies text via `POST /pkb/analyze_statement`, then saves via `POST /pkb/claims`. No modal. Tag `create-simple` is always appended. Toast confirms success or failure. Falls back to `fact`/`personal` if analysis fails.
- **`/create-entity <name>`** — opens PKB modal on Entities tab with name pre-filled.
- **`/create-context <name>`** — opens PKB modal on Contexts tab with name pre-filled.

All four commands abort the normal send flow (message never sent to AI). They appear in the autocomplete dropdown with a green **pkb** badge, available regardless of OpenCode mode.

### NL Commands (`/pkb` and `/memory`)
Natural language PKB operations routed through a dedicated conversation agent:
- **`/pkb <text>`** — routes to `PKBNLConversationAgent` for natural language memory operations (add, search, delete, edit claims). Bypasses normal conversation LLM — uses short conversation history + summary for context. The NL agent has its own LLM tool calling (add_claim, search, delete, edit, ask_clarification) and can invoke the interactive `pkb_propose_memory` tool when uncertain.
- **`/memory <text>`** — alias for `/pkb <text>`.

These commands are NOT client-side intercepted — they are routed through `Conversation.reply()` to a conversation-compatible agent (`PKBNLConversationAgent`) that preserves conversation history, message IDs, and auto-takeaways. The agent streams its response like any other agent.

**Streaming support:** `/pkb` commands now stream intermediate action progress to the UI in real-time. As the NL agent processes each action (search, add, edit, delete), the user sees formatted status updates ("🔍 Searching memories...", "✅ Added (ID: ...)", etc.) before the final response arrives. This uses `PKBNLAgent.process_streaming()` under the hood.

### Auto-Expiry
Claims with `valid_to` dates in the past are automatically marked as `expired`:
- `expire_stale_claims()` runs at DB initialization and lazily during search operations
- Expired claims are excluded from search results by default (same as `retracted`)
- The `expired` status is distinct from `retracted` — it indicates temporal expiry, not user deletion

### Interactive Memory Proposals (`pkb_propose_memory`)
When the PKB NL agent or main LLM is uncertain about a user's memory request, it can invoke the `pkb_propose_memory` interactive tool:
- Shows a modal with editable memory cards (statement, type, dates, tags, entities, context, remove button)
- User reviews, edits, and confirms the proposed memories
- Works via both paths: `/pkb` slash command (SSE `tool_input_request` event) and main LLM tool calling (`ToolCallResult.needs_user_input=True`)

### Default-Enabled Tools
`DEFAULT_ENABLED_TOOLS` in `code_common/tools.py` defines tools that are always enabled when tool use is on: `["ask_clarification", "pkb_nl_command"]`. The `pkb_nl_command` tool allows the main LLM to invoke the PKB NL agent directly during conversation.

---

## File Locations

### Core Implementation
```
truth_management_system/
├── __init__.py              # Package exports
├── constants.py             # Enums and constants
├── config.py                # Configuration management
├── utils.py                 # Utilities and ParallelExecutor
├── models.py                # Data classes
├── schema.py                # SQLite DDL
├── database.py              # Connection management
├── llm_helpers.py           # LLM extraction utilities
├── crud/                    # Data access layer
│   ├── base.py
│   ├── claims.py
│   ├── notes.py
│   ├── entities.py
│   ├── tags.py
│   ├── conflicts.py
│   └── links.py
├── search/                  # Search strategies
│   ├── base.py
│   ├── fts_search.py
│   ├── embedding_search.py
│   ├── rewrite_search.py
│   ├── mapreduce_search.py
│   ├── hybrid_search.py
│   └── notes_search.py
├── interface/               # High-level APIs
│   ├── structured_api.py
│   ├── text_orchestration.py
│   ├── conversation_distillation.py
│   ├── text_ingestion.py
│   └── nl_agent.py          # NL agent with LLM tool calling for PKB operations (v0.9)
└── tests/                   # Unit tests
```

### Integration Points
```
endpoints/pkb.py                        # Flask REST API (includes /pkb/delete_claim, /pkb/nl_command)
Conversation.py                         # Chat integration + PKBNLConversationAgent dispatch
agents/pkb_nl_conversation_agent.py     # Conversation-compatible NL agent for /pkb and /memory commands
agents/pkb_nl_conversation_agent.impl.md # Agent implementation docs
code_common/tools.py                    # LLM tool definitions (pkb_nl_command, pkb_delete_claim, pkb_propose_memory)
mcp_server/pkb.py                       # MCP tools (pkb_nl_command, pkb_delete_claim)
interface/pkb-manager.js                # Frontend API
interface/tool-call-manager.js          # pkb_propose_memory modal UI
interface/interface.html                # UI components (tool selector with 3 new PKB tools)
```

---

## Version Information

**Current Version:** v0.9 (Schema v7)

**Recent Changes (v0.9):**
- **NL Agent for PKB operations**: `truth_management_system/interface/nl_agent.py` — agentic NL processor with LLM tool calling (add_claim, search_claims, delete_claim, edit_claim, ask_clarification actions). Supports conversation context, temporal extraction, and type-filtered search. `process_streaming()` generator variant yields event dicts for real-time progress.
- **`/pkb` and `/memory` slash commands**: Route to `PKBNLConversationAgent` inside `Conversation.reply()` using the existing agent dispatch pattern. Preserves conversation history, message IDs, streaming, and auto-takeaways. Agent skips heavy context modules (web search, PKB retrieval, doc retrieval) but uses conversation infrastructure. Now streams intermediate action progress via `process_streaming()`.
- **Mandatory `valid_to` for task/reminder**: `StructuredAPI.add_claim()` and REST `endpoints/pkb.py` now require `valid_to` for task and reminder claim types.
- **Auto-expiry**: Claims with `valid_to` in the past are automatically marked `expired`. `expire_stale_claims()` runs at DB init and lazily during search. Search excludes expired claims by default.
- **`expired` claim status**: New status in `constants.py` for temporally expired claims (distinct from `retracted`).
- **MCP/LLM-tools/REST API parity**: `pkb_delete_claim` and `pkb_nl_command` added to all three surfaces (MCP `mcp_server/pkb.py`, LLM tools `code_common/tools.py`, REST `endpoints/pkb.py`).
- **`pkb_propose_memory` interactive tool**: Like `ask_clarification`, this tool shows a modal with editable memory cards when the NL agent or main LLM is uncertain. Registered as `is_interactive=True` in `tools.py`. Full modal UI in `tool-call-manager.js`.
- **Two-path interactive pipeline**: (1) Main LLM path: `pkb_nl_command` → NL agent → `needs_user_input=True` → `ToolCallResult` → existing tool loop → modal. (2) `/pkb` path: `PKBNLConversationAgent` → NL agent → `tool_input_request` SSE event → `tool_response_waiter` → agent adds confirmed claims.
- **`DEFAULT_ENABLED_TOOLS`**: `["ask_clarification", "pkb_nl_command"]` in `code_common/tools.py` — tools always enabled when tool use is on.
- **Tool selector updates**: 3 new tools in PKB optgroup (`pkb_nl_command`, `pkb_delete_claim`, `pkb_propose_memory`). `pkb_nl_command` selected by default. Category defaults updated in `chat.js`.
- **`checkMemoryUpdates` skipped for `/pkb`**: When `/pkb` or `/memory` is used, the automatic post-message `PKBManager.checkMemoryUpdates()` call is skipped (no duplicate memory proposals).
- **Bug fixes**: Moved `/pkb` override before `use_pkb` read in `Conversation.py` (PKB retrieval now correctly skipped for `/pkb` commands). Fixed `enable_tools` → `enable_tool_use` key mismatch.

**Previous Changes (v0.8):**
- **PKB slash commands**: Four new slash commands for creating memories and PKB objects from the chat input — `/create-memory`, `/create-simple-memory`, `/create-entity`, `/create-context`
- **`createSimpleMemory()`**: New `PKBManager.createSimpleMemory(text)` function: calls `POST /pkb/analyze_statement` then `POST /pkb/claims`, appends `create-simple` tag, shows toast, falls back to defaults if analysis fails
- **Autocomplete extended**: `PKB_COMMANDS` array added to autocomplete IIFE in `common-chat.js`; PKB commands shown with green **pkb** badge and always visible (not gated by OpenCode setting)
- **`autofillClaimFields` exported**: `PKBManager.autofillClaimFields` now part of public API so external callers (slash command interception) can trigger modal auto-fill

**Previous Changes (v0.7):**
- **Universal @references** (schema v7): Entities, tags, and domains can now be referenced in chat using `@` syntax with type suffixes (`_entity`, `_tag`, `_domain`, `_context`)
- **Type-suffixed friendly IDs**: All non-claim objects get a type suffix to eliminate namespace clashes (e.g., `@john_smith_person_entity`, `@fitness_tag`, `@health_domain`, `@health_goals_context`)
- **Entity friendly_id** (new): `friendly_id TEXT` column added to entities table, auto-generated as `{name}_{type}_entity`
- **Tag friendly_id** (new): `friendly_id TEXT` column added to tags table, auto-generated as `{name}_tag`
- **Context suffix migration**: Existing context friendly_ids get `_context` suffix appended; old unsuffixed references still work via backwards-compatible fallback
- **Suffix-based routing**: `resolve_reference()` parses the suffix for direct routing — no sequential fallback needed for suffixed references
- **Entity references**: `@entity_fid` resolves to all claims linked to that entity via `claim_entities` join table
- **Tag references (recursive)**: `@tag_fid` resolves to all claims tagged with that tag and all descendant tags via recursive CTE
- **Domain references**: `@domain_name_domain` resolves to all claims in that context domain
- **Expanded autocomplete**: Autocomplete dropdown now shows entities, tags, and domains alongside memories and contexts
- **Reserved suffix guard**: Claim friendly_id generation checks for reserved suffixes to prevent ambiguity
- See [PKB_V07_UNIVERSAL_REFERENCES_PLAN.md](../../planning/plans/PKB_V07_UNIVERSAL_REFERENCES.plan.md) for full design document

**Previous Changes (v0.6):**
- **QnA-style memories** (schema v6): New `possible_questions` column — each claim can have auto-generated or user-provided self-sufficient questions it answers, indexed in FTS for improved search relevance. Each question must include specific subjects/entities from the claim to be understandable without reading the claim itself.
- **Numeric claim IDs** (schema v5): New `claim_number` column — per-user auto-incremented ID, referenceable as `@claim_42` in chat
- **Unified search endpoint**: `GET /pkb/claims` now accepts `query` param for hybrid search with filters in a single call (replaces separate `POST /pkb/search` in UI)
- **Universal claim resolver**: `resolve_claim_identifier()` accepts any format: UUID, `#42`, `claim_42`, `@friendly_id`
- **Context name fallback**: `resolve_reference()` now falls back to matching context names when friendly_id lookup fails
- **Search filter fixes**: Backend `api.search()` now accepts both singular (`claim_type`) and plural (`claim_types`) filter keys; frontend `performSearch()` passes all active filters to search
- **LLM-powered question generation**: `generate_possible_questions()` in LLMHelpers auto-creates 2-4 self-sufficient questions per claim (each must contain specific entities/subjects from the claim)
- **Improved friendly ID generation**: Better stopword filtering (80+ words), 1-3 meaningful words + 4-char suffix
- **Auto-generation on edit**: Missing `friendly_id` and `possible_questions` are auto-generated when editing claims
- **Referenced claims preserved verbatim**: `_extract_referenced_claims()` ensures claims the user explicitly referenced via `@friendly_id` or `@memory:uuid` bypass the cheap LLM distillation and reach the main LLM word-for-word

**v0.5.1 Changes:**
- Schema v4: Dynamic types and domains stored in DB catalog tables (`claim_types_catalog`, `context_domains_catalog`)
- Expandable entities/tags/contexts tabs: click to see linked claims with full action controls
- Context-claim linking in Create/Edit Memory modal: multi-select dropdown
- Multi-select Type/Domain dropdowns populated from DB with inline "Add New"
- New endpoints: entity claims, tag claims, claim contexts, types catalog, domains catalog
- New CRUD: `TypeCatalogCRUD`, `DomainCatalogCRUD` in `crud/catalog.py`

**v0.5.0 Changes:**
- Friendly IDs, Context/Group System, @reference in chat, Autocomplete, Entity management UI, Enhanced filtering
- Schema v3: `friendly_id`, `claim_types`, `context_domains`, `contexts` and `context_claims` tables
- Bug fixes: schema migration robustness, IngestProposal attribute fix, text ingestion performance

**Version History:**
- v0.9: NL agent, `/pkb` & `/memory` slash commands, **streaming action progress**, mandatory `valid_to` for task/reminder, auto-expiry, `expired` status, MCP/LLM/REST parity (`pkb_delete_claim`, `pkb_nl_command`), `pkb_propose_memory` interactive tool, `DEFAULT_ENABLED_TOOLS`, two-path interactive pipeline
- v0.8: PKB slash commands (`/create-memory`, `/create-simple-memory`, `/create-entity`, `/create-context`); autocomplete `PKB_COMMANDS`; `createSimpleMemory()` public API; `autofillClaimFields` export
- v0.7: Universal @references for entities, tags, domains; type-suffixed friendly IDs; suffix-based routing (schema v7)
- v0.6: QnA possible_questions, numeric claim_number, unified search endpoint, universal resolver (schema v5-v6)
- v0.5.1: Expandable views, context linking in modals, dynamic types/domains catalog (schema v4)
- v0.5.0: Friendly IDs, contexts, autocomplete, @references, entity linking (schema v3)
- v0.4.1: Bug fixes (DB path, numpy, logging)
- v0.4.0: Deliberate memory attachment
- v0.3.0: Bulk operations and text ingestion
- v0.2.0: Multi-user support
- v0.1.0: Initial release
- v0.4.1: Bug fixes (DB path, numpy, logging)
- v0.4.0: Deliberate memory attachment
- v0.3.0: Bulk operations and text ingestion
- v0.2.0: Multi-user support
- v0.1.0: Initial release

See [api.md - Version History](./api.md#version-history) for complete details.
See [PKB_V05_ENHANCEMENT_PLAN.md](./PKB_V05_ENHANCEMENT_PLAN.md) for v0.5+ design decisions.

---

## Getting Started

### For Developers

1. **Understand the architecture:**
   - Read [implementation.md - Overview](./implementation.md#overview)
   - Review [implementation_deep_dive.md - Architecture Overview](./implementation_deep_dive.md#architecture-overview)

2. **Set up development environment:**
   - Install: `pip install -r requirements.txt`
   - Configure: Set `OPENROUTER_API_KEY` for LLM features
   - Database: Auto-created at `storage/users/pkb.sqlite`

3. **Run tests:**
   ```bash
   cd truth_management_system
   pytest tests/ -v
   ```

4. **Review common patterns:**
   - [Adding endpoints](./implementation_deep_dive.md#pattern-1-adding-a-new-endpoint)
   - [CRUD operations](./implementation_deep_dive.md#pattern-2-adding-a-new-crud-operation)
   - [Search strategies](./implementation_deep_dive.md#pattern-3-adding-a-new-search-strategy)

### For Integrators

1. **Review API documentation:**
   - Start with [api.md - Quick Start](./api.md#quick-start)
   - Understand [StructuredAPI](./api.md#core-api-structuredapi)

2. **Choose integration approach:**
   - **Programmatic:** Use `StructuredAPI` directly in Python
   - **REST API:** Call `/pkb/*` endpoints from any language
   - **Frontend:** Use `PKBManager` JavaScript module

3. **Implement common use cases:**
   - [Chatbot integration](./api.md#chatbot-integration-pattern)
   - [Conversation distillation](./api.md#conversation-distillation)
   - [Search and retrieval](./api.md#search-api)

---

## Related Documentation

- **Cross-Conversation Message References:** `../cross_conversation_references/README.md` - Reference specific messages from other conversations using `@conversation_<fid>_message_<hash>`. Uses the same `[REFERENCED ...]` label system and post-distillation re-injection as PKB references, but resolves from conversation storage instead of PKB.
- **Code Common Utilities:** `code_common/call_llm.md` - LLM calling patterns
- **Server Documentation:** `endpoints_brief_details.md` - All API endpoints
- **Testing:** `AGENTS.md` - Testing commands and strategies

---

## Support & Troubleshooting

### Common Issues

1. **No search results:** Check user_email filtering, FTS index, claim status
2. **Database path mismatch:** Ensure consistent path usage
3. **Numpy errors:** Use `is not None` instead of truthiness checks
4. **Missing logs:** Use `time_logger` in search modules
5. **"no such column: friendly_id":** Run schema migration — `db.initialize_schema()` handles v2->v3->v4 automatically
6. **Text ingestion timeout:** Ensure `auto_extract=False` in `_execute_proposal()` (fixed in v0.5.0)

See [implementation_deep_dive.md - Troubleshooting Guide](./implementation_deep_dive.md#troubleshooting-guide) for detailed solutions.

### Debug Logging

```python
import logging
logging.getLogger("truth_management_system").setLevel(logging.DEBUG)
```

### Log Prefixes
- `[PKB]` - Context retrieval
- `[FTS]` - Full-text search
- `[EMBEDDING]` - Embedding search
- `[HYBRID]` - Hybrid orchestration

---

**Last Updated:** 2026-03-11
