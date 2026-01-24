# Web Search Timing Analysis Results
## Test Date: 2025-12-31
## Query: "What are the latest advances in large language models?"

---

## Executive Summary

**Total Test Duration: 394.87 seconds (~6.5 minutes)**

The web search system has significant performance issues, primarily caused by:
1. **Sequential waiting in MultiSourceSearchAgent** (should be parallel)
2. **Slow LLM combiner calls** (25-38 seconds each)
3. **High Jina API latency** (44+ seconds)
4. **Web scraping failures** (many "Page not found" errors wasting time)

---

## Detailed Timing Breakdown

### Individual Component Times

| Component | Duration | % of Total |
|-----------|----------|------------|
| MultiSourceSearchAgent (Full) | 120.48s | 30.5% |
| Parallel vs Sequential Analysis | 86.21s | 21.8% |
| JinaSearchAgent | 73.52s | 18.6% |
| WebSearchWithAgent | 54.76s | 13.9% |
| PerplexitySearchAgent | 48.90s | 12.4% |
| Query Generation (LLM) | 4.76s | 1.2% |
| Combiner LLM (isolated) | 3.91s | 1.0% |

### Sub-Component Analysis

#### WebSearchWithAgent (54.76s total)
| Phase | Time | % |
|-------|------|---|
| Query Generation | 4.71s | 8.6% |
| **Web Search Execution** | **41.31s** | **75.4%** |
| Combiner LLM | 8.74s | 16% |

#### PerplexitySearchAgent (48.90s total)
| Phase | Time | % |
|-------|------|---|
| Query Generation | 3.41s | 7% |
| Perplexity API Calls | 17.30s | 35.4% |
| **Combiner LLM** | **28.19s** | **57.6%** |

#### JinaSearchAgent (73.52s total)
| Phase | Time | % |
|-------|------|---|
| Query Generation | 3.27s | 4.4% |
| **Jina API Calls** | **44.56s** | **60.6%** |
| Combiner LLM | 25.69s | 34.9% |

#### MultiSourceSearchAgent (120.48s total)
| Phase | Time | % |
|-------|------|---|
| WebSearch Wait | 82.41s | 68.4% |
| Perplexity Wait | 82.41s | 68.4% |
| Jina Wait | 82.41s | 68.4% |
| **Final Combiner LLM** | **38.07s** | **31.6%** |

---

## 🚨 CRITICAL FINDING: Sequential Wait Bug

### The Problem

In `MultiSourceSearchAgent.__call__()` (lines 1434-1451 of `agents/search_and_information_agents.py`):

```python
# Currently: SEQUENTIAL waiting (BAD!)
try:
    perplexity_results_short, perplexity_full_answer = sleep_and_get_future_result(perplexity_results, timeout=120)
    done_count += 1
except TimeoutError:
    ...
try:
    jina_results_short, jina_full_answer = sleep_and_get_future_result(jina_results, timeout=90)
    done_count += 1
except TimeoutError:
    ...
try:
    web_search_results_short, web_search_full_answer = sleep_and_get_future_result(web_search_results, timeout=90)
    done_count += 1
except TimeoutError:
    ...
```

**Why This Is Bad:**
- All three agents START in parallel (correct)
- But then we WAIT for each one SEQUENTIALLY
- Even if WebSearch completes in 60s, we don't check it until AFTER Perplexity and Jina are done
- This explains why all three show identical ~82.4s wait times

### Evidence from Parallel Test

When properly parallelized (in the test's parallel analysis):
| Agent | Actual Time |
|-------|-------------|
| WebSearch (parallel) | 60.75s |
| Perplexity (parallel) | 60.75s |
| Jina (parallel) | 86.21s |
| **Total (parallel)** | **86.21s** |
| Theoretical Sequential | 207.72s |
| **Speedup Factor** | **2.41x** |

**The proper parallel wait achieves 86s, but MultiSourceSearchAgent currently takes 120s due to sequential waits!**

---

## Other Performance Issues

### 1. Slow Combiner LLM Calls

| Location | Time |
|----------|------|
| Perplexity combiner | 28.19s |
| Jina combiner | 25.69s |
| MultiSource final combiner | 38.07s |

**Root Cause:** These likely use slow models (gpt-4 instead of gpt-4o-mini)

### 2. Web Scraping Failures

Many pages returned errors:
- `pmc.ncbi.nlm.nih.gov` - Page not found
- `www.mdpi.com` - Page not found
- `blogs.oracle.com` - Page not found
- `dl.acm.org` - Page not found
- `medium.com` - Page not found
- `www.tandfonline.com` - Page not found
- SSL certificate errors

**Impact:** Each failed scrape still consumes time before failing (retries, timeouts)

### 3. Jina API Latency

Jina API calls took 44.56s - the slowest API component.

Individual page scrape times via Jina:
- 0.67s - 5.40s per page
- But fetching multiple pages adds up

---

## Recommendations

### Priority 1: Fix MultiSourceSearchAgent Parallel Waiting

**Option A: Use `concurrent.futures.wait()` or `as_completed()`**

```python
from concurrent.futures import wait, as_completed, FIRST_COMPLETED

# Instead of sequential sleep_and_get_future_result calls:
futures = {
    web_search_results: 'web',
    perplexity_results: 'perplexity',
    jina_results: 'jina'
}

for future in as_completed(futures.keys(), timeout=120):
    source = futures[future]
    try:
        result = future.result()
        # Process result immediately
        ...
    except Exception as e:
        logger.error(f"Error in {source}: {e}")
```

**Option B: Uncomment and fix the polling loop (lines 1478-1528)**

The commented code already implements progressive result handling:
```python
while any(not future.done() for future in [web_search_results, perplexity_results, jina_results]):
    if web_search_results.done() and web_search_results_not_yielded:
        # yield immediately
        ...
```

**Expected Savings: 30-40 seconds** (120s → ~85s)

### Priority 2: Optimize Combiner LLM Calls

Current combiner calls take 25-38 seconds each.

**Recommendation:**
1. Use `gpt-4o-mini` or other fast models for combiners
2. Consider streaming responses earlier
3. Reduce the amount of text sent to combiner (summarize first)

**Expected Savings: 15-25 seconds per combiner**

### Priority 3: Reduce Web Scraping Failures

**Recommendations:**
1. Pre-filter URLs that are known to fail (academic paywalls, etc.)
2. Use HEAD request first to check availability (already happens but needs faster timeout)
3. Cache successful domain patterns
4. Lower retry count for failing domains
5. Add domain-specific scraping strategies

### Priority 4: Jina API Optimization

**Recommendations:**
1. Reduce number of URLs sent to Jina
2. Use priority scoring to pick best URLs only
3. Consider using `eu.r.jina.ai` instead of `r.jina.ai` if closer to server

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `agents/search_and_information_agents.py` | 1434-1451 | Fix sequential wait → parallel wait |
| `agents/search_and_information_agents.py` | 1412-1414 | Consider using faster model for sub-agents |
| `agents/search_and_information_agents.py` | 1529 | Consider using faster model for final combiner |
| `web_scraping.py` | 850-1000 | Add URL pre-filtering, faster fail |
| `base.py` | 2700-2800 | Reduce number of links to scrape |

---

## Test Commands

```bash
# Run full MultiSourceSearchAgent test
python tests/test_multi_source_search_timing.py "your query" --detail-level 2

# Run with cached results (skip cache clear)
python tests/test_multi_source_search_timing.py "your query" --detail-level 2 --no-clear-cache

# Run granular bottleneck tests
python tests/test_granular_bottlenecks.py "your query"

# Run reply search timing test
python tests/test_reply_search_timing.py "your query" --detail-level 1
```

---

## Summary of Expected Improvements

| Optimization | Current | Expected | Savings |
|--------------|---------|----------|---------|
| Fix parallel wait in MultiSource | 120s | 85s | 35s |
| Faster combiner models | ~30s each | ~8s each | 22s each |
| Reduce scraping failures | ~41s | ~30s | 11s |
| **Total MultiSource** | **120s** | **~65s** | **~55s** |

**Potential improvement: 45-50% reduction in MultiSourceSearchAgent time**

