# Web Search Performance Bottleneck Analysis

## Executive Summary

This document identifies potential performance bottlenecks in the web search implementation and provides recommendations for improvement. The analysis covers the full search pipeline from query generation to final response.

---

## Identified Bottlenecks

### 1. **Query Generation LLM Call (Estimated: 2-5s)**

**Location:** `base.py:1549-1561` and agent `__call__` methods

**Issue:** Every search starts with an LLM call to generate queries.

```python
# base.py:1551
query_strings = CallLLm(api_keys, use_gpt4=False, model_name=CHEAP_LLM[0])(prompt, temperature=0.5, max_tokens=100)
```

**Problem:**
- Sequential LLM call blocks before any search starts
- If parsing fails, another LLM call is made (`base.py:1558`)
- Each agent (WebSearchWithAgent, PerplexitySearchAgent, JinaSearchAgent) makes its own query generation call

**Impact on MultiSourceSearchAgent:**
- 3 parallel agents × 1 query gen call = effectively 1 call (parallel) but adds latency before search begins

**Optimization Suggestions:**
- Pre-cache common query patterns
- Use faster/smaller models for query generation
- Share query generation across agents in MultiSourceSearchAgent

---

### 2. **SERP API Calls (Estimated: 3-10s)**

**Location:** `base.py:1597-1714`

**Issue:** Multiple SERP providers called in parallel, but waiting for slowest one.

```python
# base.py:1731
for ix, s in enumerate(as_completed(serps)):
    # Processes results as they complete
```

**Problem:**
- BrightData Google SERP can be slow (3-8s)
- All SERP calls are made even if earlier ones return sufficient results
- Embedding computation for each result adds overhead (`base.py:1760-1772`)

**Bottleneck Measurements:**
| Provider | Typical Latency |
|----------|-----------------|
| Bing API | 1-3s |
| BrightData Google | 3-8s |
| SerpAPI | 2-4s |
| Google Custom Search | 2-5s |

**Optimization Suggestions:**
- Implement early termination once enough quality results gathered
- Reduce embedding computations (only compute for top N results)
- Add caching for repeated queries

---

### 3. **Link Scraping - MAJOR BOTTLENECK (Estimated: 10-60s)**

**Location:** `base.py:2681-2764` (`queued_read_over_multiple_links`)

**Issue:** Each link must be downloaded and parsed before summarization.

```python
# base.py:2763
task_queue = orchestrator_with_queue(..., timeout=MAX_TIME_TO_WAIT_FOR_WEB_RESULTS * (3 if provide_detailed_answers else 2))
```

**Problem:**
- 64 parallel threads, but each link can take 5-30s
- PDF processing is particularly slow (`read_pdf` function, `base.py:2541-2643`)
- Multiple scraping backends tried sequentially within each link (Jina, ScrapingAnt, BrightData)
- ArXiv HTML conversion adds overhead (`base.py:2459-2538`)

**Per-Link Breakdown:**
| Step | Time |
|------|------|
| Initial request | 1-5s |
| PDF detection/download | 2-10s |
| HTML parsing | 0.5-2s |
| Content extraction | 1-3s |
| **Total per link** | **5-20s** |

**Optimization Suggestions:**
- Reduce number of links read (currently reads too many)
- Parallelize scraping backends instead of sequential fallback
- Cache PDF conversions
- Skip slow-loading sites earlier

---

### 4. **LLM Summarization Per Link (Estimated: 2-8s per link)**

**Location:** `base.py:2645-2661` (`get_downloaded_data_summary`)

**Issue:** Each scraped link requires an LLM summarization call.

```python
# base.py:2655
result = ContextualReader(api_keys, provide_short_responses=not use_large_context, scan=use_large_context)(context, txt, retriever=None)
```

**Problem:**
- With 10+ links, this adds 20-80s cumulative time
- ContextualReader makes additional LLM calls
- No batching of summarization requests

**Optimization Suggestions:**
- Batch summarization requests
- Use smaller/faster models for initial summaries
- Reduce number of links that need full summarization

---

### 5. **MultiSourceSearchAgent Sequential Waits (Estimated: 45-120s)**

**Location:** `agents/search_and_information_agents.py:1433-1451`

**Issue:** Waits for each sub-agent with fixed timeouts.

```python
# lines 1435, 1441, 1447
perplexity_results_short, perplexity_full_answer = sleep_and_get_future_result(perplexity_results, timeout=120 if self.detail_level >= 3 else 90)
jina_results_short, jina_full_answer = sleep_and_get_future_result(jina_results, timeout=90 if self.detail_level >= 3 else 45)
web_search_results_short, web_search_full_answer = sleep_and_get_future_result(web_search_results, timeout=90 if self.detail_level >= 3 else 45)
```

**Problem:**
- Even though futures are parallel, waits are SEQUENTIAL
- Perplexity timeout (90-120s) blocks before checking Jina (45-90s)
- Total wait = Perplexity + Jina + WebSearch timeouts = **225-300s worst case**

**This is the PRIMARY BOTTLENECK in MultiSourceSearchAgent!**

**Optimization:**
```python
# Current (Sequential waits):
result1 = sleep_and_get_future_result(future1, timeout=120)  # waits up to 120s
result2 = sleep_and_get_future_result(future2, timeout=90)   # then waits up to 90s

# Should be (Parallel waits with combined timeout):
from concurrent.futures import wait, FIRST_COMPLETED
done, not_done = wait([future1, future2, future3], timeout=120, return_when=ALL_COMPLETED)
```

---

### 6. **Final Combiner LLM (Estimated: 5-15s)**

**Location:** `agents/search_and_information_agents.py:1529`

**Issue:** Large prompt with all combined results.

```python
response = llm(self.combiner_prompt.format(user_query=text, 
    web_search_results=web_search_full_answer+"\n\n"+web_search_results_short, 
    perplexity_search_results=perplexity_full_answer+"\n\n"+perplexity_results_short, 
    jina_search_results=jina_full_answer+"\n\n"+jina_results_short), ...)
```

**Problem:**
- Large input context (all 3 search results concatenated)
- Streaming but not parallelized
- Model selection not optimized for speed

---

### 7. **PerplexitySearchAgent - Multiple Parallel LLM Calls (Estimated: 10-30s)**

**Location:** `agents/search_and_information_agents.py:1097-1109`

**Issue:** For each query, calls multiple Perplexity models.

```python
for query, context in text_queries_contexts:
    for model in self.perplexity_models:  # 2-4 models
        llm = CallLLm(self.keys, model_name=model)
        future = get_async_future(llm, ...)
        futures.append((query, context, model, future))
```

**With 5 queries × 2-4 models = 10-20 parallel LLM calls**

**Problem:**
- All must complete before combining
- Perplexity API rate limits may cause delays
- Error handling doesn't short-circuit on failures

---

### 8. **JinaSearchAgent - Content Fetching per Result (Estimated: 10-40s)**

**Location:** `agents/search_and_information_agents.py:1165-1182`, `1209-1212`

**Issue:** Fetches content for each search result.

```python
# For each result:
content_response = self.fetch_jina_content(pdf_url)  # HTTP call

# If content too long, additional LLM call:
if len(content) > 5000:
    content = llm(f"...summarize...: {content}", ...)  # LLM call per result!
```

**Problem:**
- N search results × (1 HTTP + potentially 1 LLM) = significant overhead
- No limit on how many results to fully process

---

## Default Parameters from Chat Interface

From `Conversation.py:2759-2766`:

```python
# Web Search Queue defaults:
web_results = get_async_future(web_search_queue, 
    user_query,                    # Query text
    'helpful ai assistant',        # doc_source
    previous_context,              # doc_context  
    self.get_api_keys(),          # API keys
    datetime.now().strftime("%Y-%m"), # year_month
    extra_queries=searches,        # Extra search queries from UI
    previous_turn_search_results='',
    gscholar=google_scholar,       # False by default
    provide_detailed_answers=provide_detailed_answers,  # Usually 1-2
    web_search_tmp_marker_name=web_search_tmp_marker_name
)

# PerplexitySearchAgent defaults:
perplexity_agent = PerplexitySearchAgent(
    self.get_api_keys(), 
    model_name="gpt-4o" if provide_detailed_answers >= 3 else "gpt-4o-mini",
    detail_level=provide_detailed_answers,
    timeout=90,
    num_queries=(10 if provide_detailed_answers >= 3 else 5) if provide_detailed_answers >= 2 else 3
)
```

---

## Timing Breakdown Estimate (MultiSourceSearchAgent)

| Phase | Component | Min | Max | Notes |
|-------|-----------|-----|-----|-------|
| 1 | Query Generation | 2s | 5s | LLM call to generate queries |
| 2 | WebSearchWithAgent | 15s | 60s | SERP + Link reading + LLM summaries |
| 3 | PerplexitySearchAgent | 10s | 45s | Multi-model API calls |
| 4 | JinaSearchAgent | 10s | 40s | Search API + Content fetch + Summaries |
| 5 | Wait overhead | 0s | 120s | Sequential timeouts bug |
| 6 | Combiner LLM | 5s | 15s | Final synthesis |
| **Total** | | **42s** | **285s** | Wide range due to bottlenecks |

---

## Priority Recommendations

### HIGH PRIORITY (Impact: 50%+ time reduction)

1. **Fix Sequential Waits in MultiSourceSearchAgent**
   - Change from sequential `sleep_and_get_future_result` to parallel `wait()`
   - Expected improvement: 60-120s

2. **Reduce Link Scraping Count**
   - Limit to top 5 most relevant links instead of 10-15
   - Expected improvement: 20-40s

3. **Early Termination for SERP**
   - Stop SERP calls once 10 good results obtained
   - Expected improvement: 5-10s

### MEDIUM PRIORITY (Impact: 20-40% reduction)

4. **Batch LLM Summarizations**
   - Combine multiple link summaries into single LLM call
   - Expected improvement: 10-30s

5. **Cache Common Queries**
   - Cache SERP results for repeated queries
   - Expected improvement: Variable

### LOW PRIORITY (Impact: <20% reduction)

6. **Faster Query Generation Model**
   - Use smaller model for query generation
   - Expected improvement: 1-2s

---

## Test Harness Files

The following test files are available for granular timing analysis:

| File | Purpose | Command |
|------|---------|---------|
| `tests/test_search_timing_base.py` | Test base.py components (SERP, scraping, embeddings) | `python tests/test_search_timing_base.py "query"` |
| `tests/test_multi_source_search_timing.py` | Test MultiSourceSearchAgent and sub-agents | `python tests/test_multi_source_search_timing.py "query"` |
| `tests/test_reply_search_timing.py` | Test /search command via Conversation.reply() | `python tests/test_reply_search_timing.py "query"` |

### VSCode Debug Configurations

Available in `.vscode/launch.json`:
- **Debug: Search Timing Base** - Debug base.py components
- **Debug: MultiSource Search Timing** - Debug MultiSourceSearchAgent
- **Debug: Reply Search Timing** - Debug /search command flow

---

## How to Run Tests

```bash
# Activate conda environment
conda activate science-reader

# Run base component timing
python tests/test_search_timing_base.py "What are the latest AI advances?"

# Run MultiSourceSearchAgent timing
python tests/test_multi_source_search_timing.py "Machine learning trends 2024" --detail-level 1

# Run /search command timing
python tests/test_reply_search_timing.py "Transformer architecture" --detail-level 1

# Skip slow tests
python tests/test_search_timing_base.py "query" --skip-full
python tests/test_reply_search_timing.py "query" --skip-agents
python tests/test_multi_source_search_timing.py "query" --skip-individual
```

---

*Generated for performance debugging. Last updated: 2024*

