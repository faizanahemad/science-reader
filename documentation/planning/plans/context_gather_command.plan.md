# Agentic Context Gathering: /context, /fast_context, /deep_context

**Status: PLANNING**

## Goal

Add three slash commands (`/fast_context`, `/context`, `/deep_context`) that perform intelligent, multi-source document and knowledge search before the LLM generates its response. Also expose this as a **tool** (`context_gather`) and **MCP handler** so LLMs can autonomously invoke it mid-response.

The core problem: today users must manually reference specific docs (`#doc_1`, `#gdoc_all`, `#folder:Research`). This is brittle (user must know which doc has the answer), shallow (single query, no refinement), and siloed (can't cross-search local docs + global docs + PKB + conversation history in one sweep).

`/context` is a **"gather before you answer"** system — an intelligent pre-pass that searches widely, filters by relevance, and assembles a rich context block using the tool-result message format.

---

## Design Decisions

### Three Tiers

| Command | Strategy | Speed | Cost | Use Case |
|---------|----------|-------|------|----------|
| `/fast_context <query>` | BM25 + FAISS across all sources, parallelized. No LLM calls. | ~1-3s | Free | Quick lookup, known-answer queries |
| `/context <query>` | Fast sweep → LLM judge evaluates + generates follow-up queries if sparse | ~5-15s | 1-2 LLM calls | Default. Balanced. |
| `/deep_context <query>` | Full agentic: LLM plans strategy → parallel searches → judge evaluates gaps → iterates → final assembly. Auto web search if internal sources thin. | ~15-45s | 3-6 LLM calls | Complex research, cross-domain synthesis |

### Dual Mode

- **With query**: `/context <query>` gathers context AND answers the query in the same turn.
- **Without query**: `/context` (no query) gathers context based on conversation topic, makes it available for the next message ("Context ready. Ask your question."). One-shot — context is used for the immediately following message only, then cleared.

### Scope Modifiers (Exclusive When Present)

When **no modifier** is present → search everything (local docs + global docs + PKB + history).
When **any modifier** is present → search ONLY the specified scopes.

**Source scope modifiers:**

| Modifier | Scope |
|----------|-------|
| `--local` or `--conv` | This conversation's local docs only |
| `--global` or `--gdoc` | Global docs only |
| `--pkb` | PKB claims only |
| `--history` | Conversation message history only |
| `--docs` | Both local + global docs (but not PKB/history) |
| `#folder:<name>` | Global docs in this folder (implies --global scope) |
| `#tag:<name>` | Global docs with this tag (implies --global scope) |
| `--web` | Include web search (Jina + Perplexity). Explicit opt-in for /fast_context and /context. |

**Combinable**: `/context --local --pkb What about X?` → searches local docs + PKB only.
**Multiple folder/tag**: `/context #folder:Research #tag:arxiv attention` → union of folder + tag matches within global docs.

**Result modifiers:**

| Modifier | Effect |
|----------|--------|
| `--top N` | Limit to top N results (default: 10) |
| `--tokens N` | Override context budget (default: 8192-12288 tokens) |
| `--brief` | Return summaries instead of full passages |
| `--deep` | Alias for `/deep_context` |
| `--fast` | Alias for `/fast_context` |

**Web search behavior:**
- `/fast_context`: web search only via explicit `--web` modifier
- `/context`: web search only via explicit `--web` modifier
- `/deep_context`: auto web search if internal sources are thin (Jina + Perplexity). Also supports explicit `--web`.

### Context Injection

- Gathered context injected as **tool result messages** (reuses existing tool calling infrastructure).
- `/context` is also exposed as a **tool** (`context_gather`) in the tool calling framework and as an **MCP handler** — LLMs can autonomously invoke it.
- Single tool with a `strategy` parameter (`"fast"`, `"hybrid"`, `"deep"`).

### Ranking

**Weighted blend**: `0.6 * relevance_score + 0.25 * priority_weight + 0.15 * recency_weight`
- `relevance_score`: BM25/FAISS similarity score (normalized 0-1 per source)
- `priority_weight`: From doc metadata `_priority` (1-5, normalized to 0-1, where 5=1.0)
- `recency_weight`: From `_date_written` (normalized, most recent = 1.0, oldest = 0.0)
- Deprecated docs excluded entirely (same as `#doc_all` behavior)

### UI Behavior

- **Progressive disclosure**: Stream status lines as context is gathered → show collapsible `<details>` summary at top of answer message → then stream the answer.
- **Same collapsible UI for tool version**: When LLM autonomously calls `context_gather` as a tool, show same collapsible summary.
- **Empty results**: Warn but DON'T answer. Show what was searched and what was not found. Template warning message.

### Context Budget

- Default: 8192-12288 tokens (configurable).
- User override: `--tokens N`.
- When context exceeds budget: use LLM (via `model_overrides.context_model`) to shorten/summarize passages. Leverage existing `ContextualReader` class from `base.py` and `DocIndex` answer/summary methods.

### Persistence

- **One-shot**: Context lives in message history (as tool_result messages). Used for the immediately following answer, then cleared. No auto-save to memory pad.
- Memory pad auto-extraction works as normal on the answer message (existing system decides what's important).

### Model Configuration

- Judge/planning/shortening LLM: `model_overrides.context_model` (new key). Falls back to `CHEAP_LONG_CONTEXT_LLM[0]`.
- Accessed via `self.get_model_override("context_model")`.

### Interaction with Existing Systems

- **Additive always**: `/context` results add to whatever docs the user manually references (`#doc_1`, `#gdoc_all`, etc.). Never replaces.
- **Tool calling framework**: `context_gather` registered as a new tool in the `documents` category.
- **MCP**: Exposed as `context_gather` tool on the Documents MCP server (port 8102).

---

## What Is NOT Changing

- Existing `#doc_N` / `#gdoc_N` reference system — unchanged
- Existing tool calling framework architecture — we reuse it
- Existing slash command parsing infrastructure — we extend it
- DocIndex class hierarchy — no new subclasses
- PKB search API — we call it, don't modify it
- Web search agents — we call them, don't modify them

---

## Current State

### Existing Search Capabilities

**DocIndex methods** (`DocIndex.py`):
- `semantic_search_document(query, token_limit=16384)` — FAISS-based semantic search, returns relevant passages up to token_limit
- `semantic_search_document_small(query, token_limit=4096)` — Same, smaller budget
- `bm25_search(query, top_k=10)` — BM25 keyword search (FastDocIndex and full DocIndex)
- `get_doc_data(query, ...)` — Combined retrieval used by RAG pipeline

**ContextualReader** (`base.py`, line 160):
- Given context text + query, generates an answer. Used for doc Q&A.
- `__call__(context, query)` → answer string

**MessageSearchIndex** (`code_common/conversation_search.py`, line 166):
- BM25 + text search over conversation messages
- `search_bm25(query, top_k)` → list of `{message_id, score, ...}` results
- `search_text(pattern, ...)` → text/regex match results

**PKB Search** (`truth_management_system/`):
- `StructuredAPI.search_claims(query, ...)` — semantic search over PKB claims
- Tool handler: `handle_pkb_search_claims` in `code_common/tools.py`

**Web Search Agents** (`agents/`):
- Jina: `JinaSearchAgent` — web content retrieval with full page reading
- Perplexity: `PerplexityAgent` — AI-powered search with context parameter
- Tool handlers: `handle_jina_search`, `handle_perplexity_search` in `code_common/tools.py`

### Existing Slash Command Pattern (`Conversation.py`)

Commands are parsed in `reply()` around line 7495-7565:
```python
# /title and /set_title handled via regex (line 7495)
if "/title " in query["messageText"] or "/set_title " in query["messageText"]:
    ...

# /temp handled via string replace (line 7521)
if "/temp " in query["messageText"] or "/temporary " in query["messageText"]:
    ...

# OpenCode commands via dict dispatch (line 7540-7568)
opencode_commands = {
    "/compact": ..., "/abort": ..., "/new": ..., ...
}
cmd_word = msg_text.split()[0] if msg_text.startswith("/") else None
if cmd_word and cmd_word in opencode_commands:
    yield from opencode_commands[cmd_word]()
elif cmd_word and cmd_word.startswith("/") and cmd_word not in ("/title", "/set_title", "/temp", "/temporary"):
    yield from self._opencode_passthrough_command(msg_text)
```

### Tool Registration Pattern (`code_common/tools.py`)

```python
@register_tool(
    name="web_search",
    description="Search the web for current information",
    parameters={"type": "object", "properties": {...}, "required": [...]},
    category="search",
)
def handle_web_search(args: dict, context: ToolContext) -> ToolCallResult:
    ...
    return ToolCallResult(output="...", is_error=False)
```

### MCP Tool Pattern (`mcp_server/docs.py`)

Uses FastMCP server with `@mcp.tool()` decorator:
```python
@mcp.tool()
async def docs_query(query: str, doc_storage_path: str, ...) -> str:
    """..."""
    ...
    return json.dumps(result)
```

### model_overrides Pattern (`Conversation.py`, line 1213)

```python
def get_model_override(self, key: str, default: str | None = None) -> str | None:
```
Existing keys: `tldr_model`. Accessed in conversation_settings as `model_overrides` dict.

---

## Target State

### New File: `context_gather.py` (top-level)

New `ContextGatherer` class that orchestrates parallel multi-source search.

### New Slash Commands in `Conversation.py`

- `/fast_context [modifiers] [query]` → fast BM25/FAISS search
- `/context [modifiers] [query]` → hybrid search
- `/deep_context [modifiers] [query]` → full agentic search

### New Tool: `context_gather` in `code_common/tools.py`

Single tool with `strategy` parameter (`"fast"`, `"hybrid"`, `"deep"`).

### New MCP Handler: `context_gather` in `mcp_server/docs.py`

Mirrors the tool calling handler.

---

## Files to Modify

| File | Change |
|------|--------|
| `context_gather.py` | **NEW** — ContextGatherer class with parallel search, ranking, budget management |
| `Conversation.py` | Add `/context`, `/fast_context`, `/deep_context` slash command handling; add `_handle_context_command()` method |
| `code_common/tools.py` | Register `context_gather` tool with handler |
| `mcp_server/docs.py` | Add `context_gather` MCP tool handler |
| `interface/common-chat.js` | Parse `/context` commands client-side (autocomplete for modifiers) |
| `interface/interface.html` | Add `context_gather` to tool settings dropdown (documents category) |
| `interface/service-worker.js` | Bump CACHE_VERSION |

---

## Phase 0 — ContextGatherer Class (Foundation)

The core reusable class. No UI, no slash commands yet. Pure search + ranking logic.

### Task 0.1 — Create `context_gather.py` with ContextGatherer class

**File:** `context_gather.py` (new, top-level)

```python
"""Agentic context gathering across multiple knowledge sources.

Provides three search strategies:
- fast: BM25 + FAISS only, parallelized, no LLM calls
- hybrid: fast sweep + LLM judge for evaluation and refinement
- deep: full agentic with gap analysis, iteration, and optional web search
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from loggers import getLoggers
logger, time_logger = getLoggers("context_gather")


@dataclass
class ContextResult:
    """A single search result from any source."""
    source_type: str        # "local_doc", "global_doc", "pkb", "history", "web"
    doc_id: str             # doc_id, claim_id, message_id, or URL
    title: str              # Display title
    passage: str            # The actual text content
    relevance_score: float  # 0.0-1.0 normalized relevance
    priority: int           # 1-5 (from doc metadata, default 3)
    date_written: str       # ISO date or ""
    metadata: dict          # Additional source-specific metadata
    
    @property
    def blended_score(self) -> float:
        """Weighted blend: 0.6 relevance + 0.25 priority + 0.15 recency."""
        priority_norm = (self.priority - 1) / 4.0  # 1→0.0, 5→1.0
        # Recency: simple heuristic, more recent = higher
        recency_norm = 0.5  # TODO: compute from date_written relative to today
        return (0.6 * self.relevance_score 
                + 0.25 * priority_norm 
                + 0.15 * recency_norm)


@dataclass
class GatherResult:
    """Complete result from a context gathering operation."""
    query: str
    strategy: str           # "fast", "hybrid", "deep"
    scopes_searched: List[str]
    local_docs: List[ContextResult] = field(default_factory=list)
    global_docs: List[ContextResult] = field(default_factory=list)
    pkb: List[ContextResult] = field(default_factory=list)
    history: List[ContextResult] = field(default_factory=list)
    web: List[ContextResult] = field(default_factory=list)
    total_tokens: int = 0
    was_truncated: bool = False
    warnings: List[str] = field(default_factory=list)

    def ranked_results(self) -> List[ContextResult]:
        """All results sorted by blended_score descending."""
        all_results = (self.local_docs + self.global_docs 
                       + self.pkb + self.history + self.web)
        return sorted(all_results, key=lambda r: r.blended_score, reverse=True)
    
    def is_empty(self) -> bool:
        return not any([self.local_docs, self.global_docs, 
                        self.pkb, self.history, self.web])
    
    def source_counts(self) -> Dict[str, int]:
        return {
            "local_docs": len(self.local_docs),
            "global_docs": len(self.global_docs),
            "pkb": len(self.pkb),
            "history": len(self.history),
            "web": len(self.web),
        }


class ContextGatherer:
    """Orchestrates parallel multi-source context gathering.
    
    Parameters
    ----------
    conversation : Conversation
        The conversation instance (for accessing local docs, history, settings).
    user_email : str
        User email for global docs and PKB access.
    users_dir : str
        Path to users storage directory.
    token_budget : int
        Maximum tokens for gathered context (default 8192).
    """

    DEFAULT_TOKEN_BUDGET = 8192
    MAX_TOKEN_BUDGET = 16384
    DEFAULT_TOP_K = 10

    def __init__(self, conversation, user_email: str, users_dir: str, 
                 token_budget: int = DEFAULT_TOKEN_BUDGET):
        self.conversation = conversation
        self.user_email = user_email
        self.users_dir = users_dir
        self.token_budget = min(token_budget, self.MAX_TOKEN_BUDGET)

    def gather(
        self,
        query: str,
        strategy: str = "hybrid",      # "fast", "hybrid", "deep"
        scopes: Optional[List[str]] = None,  # None = all
        folders: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        top_k: int = DEFAULT_TOP_K,
        include_web: bool = False,
        token_budget: Optional[int] = None,
        brief: bool = False,
        status_callback=None,           # callable(status_dict) for streaming progress
    ) -> GatherResult:
        """Main entry point. Searches sources in parallel, ranks, truncates to budget.
        
        Parameters
        ----------
        query : str
            The search query.
        strategy : str
            "fast" (BM25/FAISS only), "hybrid" (fast + LLM judge), "deep" (agentic).
        scopes : list or None
            Active scopes. None = all. Options: "local_docs", "global_docs", "pkb", "history".
        folders : list or None
            Global doc folder names to filter by.
        tags : list or None
            Global doc tag names to filter by.
        top_k : int
            Max results per source.
        include_web : bool
            Whether to include web search.
        token_budget : int or None
            Override instance token budget.
        brief : bool
            Return summaries instead of full passages.
        status_callback : callable or None
            Called with {"text": "", "status": "..."} dicts for progress streaming.
            
        Returns
        -------
        GatherResult
            Grouped results with ranking and metadata.
        """
        budget = token_budget or self.token_budget
        active_scopes = scopes or ["local_docs", "global_docs", "pkb", "history"]
        
        # If folder/tag modifiers present, scope is implicitly global_docs only
        if (folders or tags) and scopes is None:
            active_scopes = ["global_docs"]

        result = GatherResult(
            query=query,
            strategy=strategy,
            scopes_searched=active_scopes[:],
        )

        # --- Phase 1: Parallel fast sweep ---
        if status_callback:
            status_callback({"text": "", "status": f"Searching {len(active_scopes)} sources..."})

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {}
            
            if "local_docs" in active_scopes:
                futures[executor.submit(
                    self._search_local_docs, query, top_k, brief
                )] = "local_docs"
            
            if "global_docs" in active_scopes:
                futures[executor.submit(
                    self._search_global_docs, query, top_k, brief, folders, tags
                )] = "global_docs"
            
            if "pkb" in active_scopes:
                futures[executor.submit(
                    self._search_pkb, query, top_k
                )] = "pkb"
            
            if "history" in active_scopes:
                futures[executor.submit(
                    self._search_history, query, top_k
                )] = "history"
            
            if include_web or (strategy == "deep"):
                futures[executor.submit(
                    self._search_web, query
                )] = "web"
                result.scopes_searched.append("web")

            for future in as_completed(futures):
                source = futures[future]
                try:
                    results = future.result(timeout=30)
                    setattr(result, source, results)
                    if status_callback:
                        status_callback({
                            "text": "", 
                            "status": f"Found {len(results)} results from {source}"
                        })
                except Exception as e:
                    logger.warning(f"Context gather: {source} search failed: {e}")
                    result.warnings.append(f"{source} search failed: {str(e)}")

        # --- Phase 2: Rank + merge ---
        # Results are already grouped by source. Ranking is done via ranked_results().

        # --- Phase 3: LLM judge (hybrid only) ---
        if strategy in ("hybrid", "deep") and not result.is_empty():
            if status_callback:
                status_callback({"text": "", "status": "Evaluating relevance..."})
            self._llm_judge_evaluate(result, query, strategy)

        # --- Phase 4: Deep agentic iteration (deep only) ---
        if strategy == "deep" and not result.is_empty():
            if status_callback:
                status_callback({"text": "", "status": "Deep analysis: checking for gaps..."})
            self._deep_iterate(result, query, active_scopes, include_web, top_k, brief)

        # --- Phase 5: Auto web search for deep if results thin ---
        if strategy == "deep" and result.is_empty() and not include_web:
            if status_callback:
                status_callback({"text": "", "status": "Internal sources thin, searching web..."})
            try:
                result.web = self._search_web(query)
                if result.web:
                    result.scopes_searched.append("web")
            except Exception as e:
                result.warnings.append(f"Web search fallback failed: {str(e)}")

        # --- Phase 6: Budget enforcement ---
        self._enforce_token_budget(result, budget, brief)

        return result

    # ------------------------------------------------------------------
    # Source-specific search methods
    # ------------------------------------------------------------------

    def _search_local_docs(self, query: str, top_k: int, brief: bool) -> List[ContextResult]:
        """Search this conversation's uploaded documents."""
        results = []
        # Get uploaded docs from conversation
        docs_list = self.conversation.get_field("uploaded_documents_list") or []
        
        for entry in docs_list:
            doc_id = entry[0]
            doc_storage = entry[1]
            try:
                from DocIndex import DocIndex as DocIndexClass
                doc_index = DocIndexClass.load_local(doc_storage)
                if doc_index is None:
                    continue
                
                # Skip deprecated
                if getattr(doc_index, "_deprecated", False):
                    continue
                
                # Search: use bm25_search for fast, semantic for full
                if hasattr(doc_index, 'bm25_search'):
                    bm25_results = doc_index.bm25_search(query, top_k=top_k)
                    # bm25_results format depends on implementation
                    # TODO: normalize to ContextResult
                
                if hasattr(doc_index, 'semantic_search_document_small'):
                    passage = doc_index.semantic_search_document_small(query, token_limit=2048)
                    if passage and passage.strip():
                        results.append(ContextResult(
                            source_type="local_doc",
                            doc_id=doc_id,
                            title=getattr(doc_index, 'title', '') or getattr(doc_index, '_display_name', '') or doc_id,
                            passage=passage if not brief else passage[:500],
                            relevance_score=0.5,  # TODO: extract actual score
                            priority=getattr(doc_index, "_priority", 3),
                            date_written=getattr(doc_index, "_date_written", "") or "",
                            metadata={"doc_storage": doc_storage},
                        ))
            except Exception as e:
                logger.warning(f"Context gather: local doc {doc_id} search failed: {e}")
        
        return results

    def _search_global_docs(self, query: str, top_k: int, brief: bool,
                            folders: Optional[List[str]] = None,
                            tags: Optional[List[str]] = None) -> List[ContextResult]:
        """Search global documents, optionally filtered by folder/tag."""
        results = []
        from database.global_docs import list_global_docs
        
        all_docs = list_global_docs(users_dir=self.users_dir, user_email=self.user_email)
        
        # Filter by folder/tag if specified
        if folders or tags:
            from database.doc_tags import get_doc_tags
            filtered = []
            for doc in all_docs:
                if folders and doc.get("folder_id"):
                    # TODO: resolve folder_id to folder name and match
                    pass
                if tags:
                    doc_tags = get_doc_tags(
                        users_dir=self.users_dir, 
                        user_email=self.user_email, 
                        doc_id=doc["doc_id"]
                    )
                    if any(t.lower() in [dt.lower() for dt in doc_tags] for t in tags):
                        filtered.append(doc)
                elif folders:
                    pass  # TODO: folder matching
                else:
                    filtered.append(doc)
            all_docs = filtered if (folders or tags) else all_docs
        
        # Filter out deprecated
        all_docs = [d for d in all_docs if not d.get("deprecated", False)]
        
        # Search each doc in parallel
        def search_one_global(doc):
            try:
                from DocIndex import DocIndex as DocIndexClass
                doc_index = DocIndexClass.load_local(doc["doc_storage"])
                if doc_index is None:
                    return None
                
                if hasattr(doc_index, 'semantic_search_document_small'):
                    passage = doc_index.semantic_search_document_small(query, token_limit=2048)
                    if passage and passage.strip():
                        return ContextResult(
                            source_type="global_doc",
                            doc_id=doc["doc_id"],
                            title=doc.get("display_name") or doc.get("title") or doc["doc_id"],
                            passage=passage if not brief else passage[:500],
                            relevance_score=0.5,  # TODO: extract actual score
                            priority=doc.get("priority", 3),
                            date_written=doc.get("date_written", "") or "",
                            metadata={
                                "doc_storage": doc["doc_storage"],
                                "folder_id": doc.get("folder_id"),
                                "tags": doc.get("tags", []),
                            },
                        )
            except Exception as e:
                logger.warning(f"Context gather: global doc {doc.get('doc_id')} search failed: {e}")
            return None
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            for cr in executor.map(search_one_global, all_docs):
                if cr is not None:
                    results.append(cr)
        
        return sorted(results, key=lambda r: r.blended_score, reverse=True)[:top_k]

    def _search_pkb(self, query: str, top_k: int) -> List[ContextResult]:
        """Search PKB claims via StructuredAPI."""
        results = []
        try:
            from truth_management_system.api import StructuredAPI
            api = StructuredAPI(users_dir=self.users_dir, user_email=self.user_email)
            claims = api.search_claims(query=query, top_k=top_k)
            
            for claim in (claims or []):
                results.append(ContextResult(
                    source_type="pkb",
                    doc_id=claim.get("claim_id", ""),
                    title=claim.get("friendly_id", "") or claim.get("claim_id", ""),
                    passage=claim.get("statement", ""),
                    relevance_score=claim.get("score", 0.5),
                    priority=3,  # PKB claims don't have priority
                    date_written="",
                    metadata={
                        "claim_type": claim.get("claim_type"),
                        "context_domain": claim.get("context_domain"),
                        "friendly_id": claim.get("friendly_id"),
                    },
                ))
        except Exception as e:
            logger.warning(f"Context gather: PKB search failed: {e}")
        
        return results

    def _search_history(self, query: str, top_k: int) -> List[ContextResult]:
        """Search conversation message history via BM25."""
        results = []
        try:
            # Use the conversation's message search index
            search_index = self.conversation.get_field("message_search_index")
            if search_index is None:
                return results
            
            from code_common.conversation_search import MessageSearchIndex
            if isinstance(search_index, dict):
                idx = MessageSearchIndex.from_dict(search_index)
            else:
                idx = search_index
            
            hits = idx.search_bm25(query, top_k=top_k)
            
            for hit in (hits or []):
                results.append(ContextResult(
                    source_type="history",
                    doc_id=hit.get("message_id", ""),
                    title=f"Message ({hit.get('sender', 'unknown')})",
                    passage=hit.get("text", "")[:1000],  # Truncate long messages
                    relevance_score=min(1.0, hit.get("score", 0) / 10.0),  # Normalize BM25 scores
                    priority=3,
                    date_written="",
                    metadata={
                        "sender": hit.get("sender"),
                        "message_id": hit.get("message_id"),
                    },
                ))
        except Exception as e:
            logger.warning(f"Context gather: history search failed: {e}")
        
        return results

    def _search_web(self, query: str) -> List[ContextResult]:
        """Search web via Jina and Perplexity agents."""
        results = []
        try:
            from common import get_keys
            keys = get_keys()
            
            # Try Perplexity first (faster, AI-summarized)
            try:
                from agents.search_and_information_agents import PerplexityAgent
                agent = PerplexityAgent(keys)
                response = agent(query, context="")
                if response and isinstance(response, str) and response.strip():
                    results.append(ContextResult(
                        source_type="web",
                        doc_id="perplexity_search",
                        title="Web Search (Perplexity)",
                        passage=response[:3000],
                        relevance_score=0.7,
                        priority=3,
                        date_written="",
                        metadata={"search_engine": "perplexity"},
                    ))
            except Exception as e:
                logger.warning(f"Context gather: Perplexity search failed: {e}")
            
            # Try Jina for additional results
            try:
                from agents.search_and_information_agents import JinaSearchAgent
                agent = JinaSearchAgent(keys)
                response = agent(query, context="")
                if response and isinstance(response, str) and response.strip():
                    results.append(ContextResult(
                        source_type="web",
                        doc_id="jina_search",
                        title="Web Search (Jina)",
                        passage=response[:3000],
                        relevance_score=0.6,
                        priority=3,
                        date_written="",
                        metadata={"search_engine": "jina"},
                    ))
            except Exception as e:
                logger.warning(f"Context gather: Jina search failed: {e}")
        except Exception as e:
            logger.warning(f"Context gather: web search setup failed: {e}")
        
        return results

    # ------------------------------------------------------------------
    # LLM judge and deep iteration
    # ------------------------------------------------------------------

    def _llm_judge_evaluate(self, result: GatherResult, query: str, strategy: str):
        """LLM evaluates results for relevance and suggests follow-up queries."""
        # TODO: Implementation
        # 1. Build a summary of what was found (titles + first 200 chars of each passage)
        # 2. Ask LLM: "Given query X, are these results sufficient? Rate each 1-5."
        # 3. Filter out low-relevance results
        # 4. If strategy == "hybrid" and results sparse, generate 2-3 refined queries
        # 5. Re-search with refined queries, merge new results
        pass

    def _deep_iterate(self, result: GatherResult, query: str,
                      scopes: List[str], include_web: bool,
                      top_k: int, brief: bool):
        """Agentic iteration: identify gaps, plan follow-up searches, iterate."""
        # TODO: Implementation
        # 1. LLM analyzes: "What aspects of the query are NOT covered by current results?"
        # 2. Generates specific follow-up queries targeting gaps
        # 3. Searches with new queries (possibly different scopes)
        # 4. Merges new results
        # 5. Repeats 1-2 more times if still gaps
        pass

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------

    def _enforce_token_budget(self, result: GatherResult, budget: int, brief: bool):
        """Truncate results to fit within token budget."""
        # TODO: Implementation
        # 1. Count tokens in all results (rough: len(text) / 4)
        # 2. If over budget, use LLM to shorten passages (via ContextualReader pattern)
        # 3. Or truncate lowest-ranked results first
        # 4. Set result.total_tokens and result.was_truncated
        pass

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_context_block(self, result: GatherResult) -> str:
        """Format gathered context as a text block for LLM injection."""
        if result.is_empty():
            return ""
        
        lines = ["## Gathered Context\n"]
        ranked = result.ranked_results()
        
        for i, cr in enumerate(ranked, 1):
            source_label = {
                "local_doc": "#doc",
                "global_doc": "#gdoc",
                "pkb": "@pkb",
                "history": "📝 history",
                "web": "🌐 web",
            }.get(cr.source_type, cr.source_type)
            
            priority_label = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(cr.priority, "medium")
            
            header = f"### Source {i}: {source_label} — {cr.title}"
            meta = f"[reliability: {priority_label}"
            if cr.date_written:
                meta += f", date: {cr.date_written}"
            meta += f", relevance: {cr.blended_score:.2f}]"
            
            lines.append(f"{header}\n{meta}\n\n{cr.passage}\n")
        
        return "\n".join(lines)

    def format_summary_html(self, result: GatherResult) -> str:
        """Format collapsible HTML summary for the UI."""
        if result.is_empty():
            return ""
        
        counts = result.source_counts()
        total = sum(counts.values())
        sources_str = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items() if v > 0)
        
        summary = f"<details><summary>📚 Context gathered: {total} sources ({sources_str})"
        if result.was_truncated:
            summary += " [truncated to budget]"
        summary += "</summary>\n\n"
        
        ranked = result.ranked_results()
        for cr in ranked:
            priority_label = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}.get(cr.priority, "medium")
            summary += f"- **{cr.title}** ({cr.source_type}) [reliability: {priority_label}, score: {cr.blended_score:.2f}]\n"
        
        summary += "\n</details>\n\n"
        
        if result.warnings:
            for w in result.warnings:
                summary += f"⚠️ {w}\n"
        
        return summary
    
    def format_empty_warning(self, result: GatherResult, query: str) -> str:
        """Format warning when no results found."""
        scopes_str = ", ".join(result.scopes_searched)
        msg = f"⚠️ **No relevant context found** for: *{query}*\n\n"
        msg += f"**Searched:** {scopes_str}\n"
        msg += f"**Strategy:** {result.strategy}\n\n"
        if result.warnings:
            msg += "**Issues:**\n"
            for w in result.warnings:
                msg += f"- {w}\n"
        msg += "\nTry broadening your search (remove scope modifiers), using a different query, or switching to `/deep_context`."
        return msg
```

### Task 0.2 — Add modifier parsing helper

Add a `parse_context_modifiers()` function to `context_gather.py`:

```python
def parse_context_modifiers(text: str) -> dict:
    """Parse /context command text into query + modifiers.
    
    Examples:
        "/context attention mechanisms" 
            → {"query": "attention mechanisms", "strategy": "hybrid", "scopes": None, ...}
        "/fast_context --local --top 5 attention"
            → {"query": "attention", "strategy": "fast", "scopes": ["local_docs"], "top_k": 5, ...}
        "/deep_context #folder:Research #tag:arxiv transformer scaling"
            → {"query": "transformer scaling", "strategy": "deep", "folders": ["Research"], "tags": ["arxiv"], ...}
    
    Returns dict with keys:
        query, strategy, scopes, folders, tags, top_k, token_budget, brief, include_web
    """
    import re
    
    # Determine strategy from command prefix
    strategy = "hybrid"
    text = text.strip()
    if text.startswith("/fast_context"):
        strategy = "fast"
        text = text[len("/fast_context"):].strip()
    elif text.startswith("/deep_context"):
        strategy = "deep"
        text = text[len("/deep_context"):].strip()
    elif text.startswith("/context"):
        strategy = "hybrid"
        text = text[len("/context"):].strip()
    
    # Check for --fast / --deep aliases
    if "--fast" in text:
        strategy = "fast"
        text = text.replace("--fast", "").strip()
    elif "--deep" in text:
        strategy = "deep"
        text = text.replace("--deep", "").strip()
    
    scopes = []
    folders = []
    tags = []
    top_k = 10
    token_budget = None
    brief = False
    include_web = False
    
    # Parse scope modifiers
    scope_map = {
        "--local": "local_docs", "--conv": "local_docs",
        "--global": "global_docs", "--gdoc": "global_docs",
        "--pkb": "pkb",
        "--history": "history",
        "--docs": None,  # special: both local + global
    }
    
    for flag, scope in scope_map.items():
        if flag in text:
            if flag == "--docs":
                scopes.extend(["local_docs", "global_docs"])
            else:
                scopes.append(scope)
            text = text.replace(flag, "").strip()
    
    # Parse #folder: and #tag:
    for match in re.finditer(r'#folder:(\S+)', text):
        folders.append(match.group(1))
    text = re.sub(r'#folder:\S+', '', text).strip()
    
    for match in re.finditer(r'#tag:(\S+)', text):
        tags.append(match.group(1))
    text = re.sub(r'#tag:\S+', '', text).strip()
    
    # Parse result modifiers
    top_match = re.search(r'--top\s+(\d+)', text)
    if top_match:
        top_k = int(top_match.group(1))
        text = text[:top_match.start()] + text[top_match.end():]
    
    tokens_match = re.search(r'--tokens\s+(\d+)', text)
    if tokens_match:
        token_budget = int(tokens_match.group(1))
        text = text[:tokens_match.start()] + text[tokens_match.end():]
    
    if "--brief" in text:
        brief = True
        text = text.replace("--brief", "").strip()
    
    if "--web" in text:
        include_web = True
        text = text.replace("--web", "").strip()
    
    query = text.strip()
    
    return {
        "query": query,
        "strategy": strategy,
        "scopes": scopes if scopes else None,  # None = all
        "folders": folders if folders else None,
        "tags": tags if tags else None,
        "top_k": top_k,
        "token_budget": token_budget,
        "brief": brief,
        "include_web": include_web,
    }
```

---

## Phase 1 — Slash Command Integration

Wire ContextGatherer into the existing slash command pipeline in `Conversation.py`.

### Task 1.1 — Add /context command handling to reply()

**File:** `Conversation.py`

Add `/context`, `/fast_context`, `/deep_context` detection BEFORE the `/title` check (around line 7493). These commands should be intercepted early and routed to a new `_handle_context_command()` method.

```python
# --- /context, /fast_context, /deep_context commands ---
context_commands = ("/context", "/fast_context", "/deep_context")
if any(query["messageText"].strip().startswith(cmd) for cmd in context_commands):
    yield from self._handle_context_command(query, userData, checkboxes)
    return
```

### Task 1.2 — Implement _handle_context_command()

**File:** `Conversation.py`

New method that:
1. Parses modifiers from the message text
2. Instantiates ContextGatherer
3. Calls `.gather()` with status streaming
4. If results found + query present: injects context as tool_result messages, then calls the normal reply flow
5. If results found + no query: yields context summary and "Context ready" message
6. If empty results: yields warning message, does NOT answer

```python
def _handle_context_command(self, query, userData, checkboxes):
    """Handle /context, /fast_context, /deep_context commands."""
    from context_gather import ContextGatherer, parse_context_modifiers
    
    msg_text = query["messageText"].strip()
    mods = parse_context_modifiers(msg_text)
    
    yield {"text": "", "status": f"Context gathering ({mods['strategy']})..."}
    
    gatherer = ContextGatherer(
        conversation=self,
        user_email=self._user_email,  
        users_dir=self._users_dir,
        token_budget=mods["token_budget"] or ContextGatherer.DEFAULT_TOKEN_BUDGET,
    )
    
    def status_cb(s):
        # Will be yielded as streaming status
        pass  # TODO: wire into generator
    
    result = gatherer.gather(
        query=mods["query"],
        strategy=mods["strategy"],
        scopes=mods["scopes"],
        folders=mods["folders"],
        tags=mods["tags"],
        top_k=mods["top_k"],
        include_web=mods["include_web"],
        token_budget=mods["token_budget"],
        brief=mods["brief"],
    )
    
    if result.is_empty():
        # Warn and don't answer
        warning = gatherer.format_empty_warning(result, mods["query"])
        yield {"text": warning, "status": "No relevant context found"}
        return
    
    # Format summary + context
    summary_html = gatherer.format_summary_html(result)
    context_block = gatherer.format_context_block(result)
    
    if mods["query"]:
        # Mode 1: Gather + answer
        # Inject context as tool result, then proceed with normal reply
        yield {"text": summary_html, "status": "Context gathered, generating answer..."}
        
        # Store context for injection into the next LLM call
        # This uses the tool_result message format
        self._pending_context = context_block
        
        # Modify query to be just the user's question (without /context prefix and modifiers)
        query["messageText"] = mods["query"]
        
        # Continue with normal reply flow (the pending context will be injected)
        # TODO: wire into reply() to inject self._pending_context into messages
        yield from self._reply_with_gathered_context(query, userData, checkboxes, context_block)
    else:
        # Mode 2: Gather for next message
        yield {"text": summary_html, "status": "Context ready"}
        yield {"text": "\n\n✅ **Context gathered.** Ask your question — I'll use these sources.\n", "status": ""}
        
        # Store for next message (one-shot)
        self._pending_context = context_block
```

### Task 1.3 — Implement _reply_with_gathered_context()

**File:** `Conversation.py`

Method that calls the normal reply pipeline but injects the gathered context as tool_result messages in the conversation history. The context appears as if a `context_gather` tool was called and returned results.

This should follow the existing `_run_tool_loop()` message format:
```python
# Tool result message format:
{"role": "tool", "content": context_block, "tool_call_id": "context_gather_..."}
```

### Task 1.4 — Add /context to the local command whitelist

**File:** `Conversation.py`

Update the OpenCode passthrough check (line 7565) to exclude `/context`, `/fast_context`, `/deep_context` from being passed through to OpenCode:

```python
elif cmd_word and cmd_word.startswith("/") and cmd_word not in (
    "/title", "/set_title", "/temp", "/temporary",
    "/context", "/fast_context", "/deep_context",
):
```

---

## Phase 2 — Tool Calling Integration

Register `context_gather` as a tool so LLMs can invoke it autonomously.

### Task 2.1 — Register context_gather tool

**File:** `code_common/tools.py`

```python
@register_tool(
    name="context_gather",
    description=(
        "Intelligent multi-source context gathering. Searches across conversation documents, "
        "global documents, PKB claims, and conversation history to find relevant information. "
        "Use when you need to find information across multiple documents or knowledge sources "
        "before answering a complex question. "
        "Strategy options: 'fast' (BM25/FAISS, instant), 'hybrid' (fast + LLM evaluation), "
        "'deep' (agentic multi-step with gap analysis). "
        "Returns grouped results with source attribution and relevance scores."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant context for",
            },
            "strategy": {
                "type": "string",
                "enum": ["fast", "hybrid", "deep"],
                "description": "Search strategy: 'fast' (instant BM25/FAISS), 'hybrid' (fast + LLM judge), 'deep' (agentic iteration)",
                "default": "hybrid",
            },
            "scopes": {
                "type": "array",
                "items": {"type": "string", "enum": ["local_docs", "global_docs", "pkb", "history"]},
                "description": "Which sources to search. Empty = all sources.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum results per source (default 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    },
    category="documents",
)
def handle_context_gather(args: dict, context: ToolContext) -> ToolCallResult:
    """Handle context_gather tool call."""
    from context_gather import ContextGatherer
    
    query = args.get("query", "")
    strategy = args.get("strategy", "hybrid")
    scopes = args.get("scopes") or None
    top_k = args.get("top_k", 10)
    
    conversation = context.conversation
    gatherer = ContextGatherer(
        conversation=conversation,
        user_email=context.user_email,
        users_dir=context.users_dir,
    )
    
    result = gatherer.gather(
        query=query,
        strategy=strategy,
        scopes=scopes,
        top_k=top_k,
    )
    
    if result.is_empty():
        return ToolCallResult(
            output=gatherer.format_empty_warning(result, query),
            is_error=False,
        )
    
    output = gatherer.format_context_block(result)
    return ToolCallResult(output=output, is_error=False)
```

### Task 2.2 — Add context_gather to tool settings UI

**File:** `interface/interface.html`

Add `context_gather` option to the documents optgroup in the tool settings `<select multiple>`:

```html
<option value="context_gather">Context Gather (multi-source search)</option>
```

---

## Phase 3 — MCP Integration

### Task 3.1 — Add context_gather MCP handler

**File:** `mcp_server/docs.py`

```python
@mcp.tool()
async def context_gather(
    query: str,
    conversation_id: str = "",
    strategy: str = "hybrid",
    scopes: str = "",
    top_k: int = 10,
) -> str:
    """Intelligent multi-source context gathering across documents, PKB, and history.
    
    Searches conversation documents, global documents, PKB claims, and conversation history.
    Returns relevant passages with source attribution and relevance scores.
    
    Args:
        query: Search query
        conversation_id: Conversation ID for local docs and history (optional)
        strategy: Search strategy - 'fast', 'hybrid', or 'deep'
        scopes: Comma-separated scopes to search (local_docs,global_docs,pkb,history). Empty = all.
        top_k: Max results per source (default 10)
    """
    from context_gather import ContextGatherer
    
    # Parse scopes
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()] or None
    
    # Load conversation if provided
    conversation = None
    if conversation_id:
        conversation = _load_conversation(conversation_id)
    
    gatherer = ContextGatherer(
        conversation=conversation,
        user_email=email,
        users_dir=users_dir,
    )
    
    result = gatherer.gather(
        query=query,
        strategy=strategy,
        scopes=scope_list,
        top_k=top_k,
    )
    
    if result.is_empty():
        return gatherer.format_empty_warning(result, query)
    
    return gatherer.format_context_block(result)
```

---

## Phase 4 — Frontend UI

### Task 4.1 — Parse /context commands client-side

**File:** `interface/common-chat.js`

Add detection for `/context` commands so the UI can show appropriate loading state. No special parsing needed — the command flows through the normal `send_message` pipeline. But add autocomplete hints for modifiers.

### Task 4.2 — Render collapsible context summary

The backend already yields the `<details>` HTML block via the streaming protocol. The existing markdown renderer handles `<details>` tags. Verify it renders correctly — may need minor CSS adjustments.

### Task 4.3 — Bump service worker cache version

**File:** `interface/service-worker.js`

Bump `CACHE_VERSION`.

---

## Phase 5 — LLM Judge and Deep Iteration (Hybrid/Deep)

### Task 5.1 — Implement _llm_judge_evaluate()

**File:** `context_gather.py`

The LLM judge receives a summary of found results and the original query, then:
1. Rates each result's relevance (1-5)
2. Filters out low-relevance results (< 2)
3. For hybrid strategy: generates 2-3 refined queries if results are sparse
4. Re-searches with refined queries, merges

Uses `model_overrides.context_model` via `conversation.get_model_override("context_model")`.

### Task 5.2 — Implement _deep_iterate()

**File:** `context_gather.py`

Full agentic iteration:
1. LLM analyzes gaps: "What aspects of the query are NOT covered?"
2. Generates specific follow-up queries targeting gaps
3. May suggest different scopes ("try PKB for personal notes on this")
4. Searches with new queries
5. Merges results
6. Iterates 1-2 more times if still gaps

### Task 5.3 — Implement _enforce_token_budget()

**File:** `context_gather.py`

1. Count tokens in all results (rough estimate: `len(text) / 4`)
2. If over budget, rank all passages and drop lowest-ranked first
3. If still over budget after dropping, use LLM to shorten top passages (via ContextualReader pattern from `base.py`)
4. Set `result.total_tokens` and `result.was_truncated`

---

## Phase 6 — Documentation

### Task 6.1 — Create feature documentation

**File:** `documentation/features/context_gather/README.md` (new)

Document: slash command syntax, all modifiers, scope behavior, three tiers, tool/MCP exposure, examples.

### Task 6.2 — Update capabilities doc

**File:** `documentation/product/behavior/chat_app_capabilities.md`

Add new section for Context Gathering feature.

### Task 6.3 — Update tool calling docs

**File:** `documentation/features/tool_calling/README.md`

Add `context_gather` to the documents tool category table.

---

## Implementation Order

1. **Phase 0** — ContextGatherer class + modifier parser. Pure library, no integration.
2. **Phase 1** — Slash command integration in Conversation.py. Users can use /fast_context.
3. **Phase 2** — Tool calling registration. LLMs can invoke context_gather.
4. **Phase 3** — MCP handler. External tools can use context_gather.
5. **Phase 4** — Frontend polish (autocomplete, CSS).
6. **Phase 5** — LLM judge + deep iteration. Upgrades /context and /deep_context from stubs to full implementation.
7. **Phase 6** — Documentation.

Build incrementally: Phase 0+1 gives `/fast_context` working end-to-end. Phase 5 unlocks the hybrid and deep tiers. Each phase is independently deployable.

---

## Risk Analysis

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| DocIndex.load_local() is slow for many global docs | High (10+ docs) | Parallel ThreadPoolExecutor, max 4 concurrent loads |
| BM25/FAISS scores not comparable across sources | Certain | Normalize per-source before blending |
| Token budget exceeded by rich context | Medium | Aggressive truncation + LLM shortening |
| LLM judge adds latency for /context | Expected (5-10s) | /fast_context as no-LLM alternative |
| PKB search API changes | Low | Isolate in _search_pkb(), easy to update |
| Web search costs for /deep_context | Low | Auto-web only for deep; explicit --web for others |
| Memory leak from loading many DocIndex objects | Medium | Load, search, discard — don't cache in ContextGatherer |
| Deprecated docs leaking into results | Low | Explicit filter in both _search_local_docs and _search_global_docs |
| /context conflicts with OpenCode /context command | Low | /context is not an OpenCode command today |
| Modifier parsing edge cases | Medium | Comprehensive test cases in parse_context_modifiers |

---

## Summary of All Code Changes

### `context_gather.py` (NEW)
- `ContextResult` dataclass — single search result with blended_score property
- `GatherResult` dataclass — grouped results with ranked_results(), source_counts()
- `ContextGatherer` class — orchestrates parallel search, ranking, budget enforcement
- `parse_context_modifiers()` — parse command text into query + modifiers
- Source search methods: `_search_local_docs`, `_search_global_docs`, `_search_pkb`, `_search_history`, `_search_web`
- LLM methods: `_llm_judge_evaluate`, `_deep_iterate`, `_enforce_token_budget`
- Formatting: `format_context_block`, `format_summary_html`, `format_empty_warning`

### `Conversation.py`
- Add `/context`, `/fast_context`, `/deep_context` to command detection (before /title check)
- Add to OpenCode passthrough exclusion list
- New: `_handle_context_command()` — parse, gather, route
- New: `_reply_with_gathered_context()` — inject context as tool_result, then reply normally

### `code_common/tools.py`
- New: `@register_tool(name="context_gather", ...)` + `handle_context_gather()`

### `mcp_server/docs.py`
- New: `@mcp.tool() async def context_gather(...)` handler

### `interface/interface.html`
- Add `context_gather` to documents optgroup in tool settings

### `interface/common-chat.js`
- Optional: autocomplete for /context modifiers

### `interface/service-worker.js`
- Bump CACHE_VERSION

### Documentation (3 files)
- `documentation/features/context_gather/README.md` (new)
- `documentation/product/behavior/chat_app_capabilities.md` (update)
- `documentation/features/tool_calling/README.md` (update)
