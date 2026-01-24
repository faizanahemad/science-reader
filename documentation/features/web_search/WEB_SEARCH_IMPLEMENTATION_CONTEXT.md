# Web Search & Perplexity Search Implementation Context

## Overview

This document describes how web search, perplexity search, and other search functionalities are implemented in the `server.py` based chat application. The search system is a multi-layered architecture that uses various search providers (SERP APIs, Perplexity, Jina, etc.) and combines them with LLM-based summarization.

---

## Architecture Summary

- `server.py` contains Flask endpoints (such as `/send_message`, `/temporary_llm_action`) that handle user queries and trigger search routines.
- `Conversation.py` handles the main logic for responding to user queries:
    - `reply()` method detects when to run a search.
    - Calls `web_search_queue()` for traditional multi-site searches.
    - Uses `PerplexitySearchAgent` for Perplexity-driven searches.
    - Uses an agent factory to instantiate specialized agents (e.g., Jina, custom).
- Supporting backend modules:
    - `base.py`:
        - Implements core search queue (`web_search_queue()`), search query generation (`web_search_part1*`), and wrappers for Bing, Google, and SERP APIs (`bingapi()`, `brightdata_google_serp()`).
    - `search_and_information_agents.py`:
        - Defines `PerplexitySearchAgent`, `JinaSearchAgent`, `WebSearchWithAgent`, `MultiSourceSearch`—each providing specialized aggregation and LLM-based answer synthesis from web data.
    - `web_scraping.py`:
        - Responsible for page fetching (`web_scrape_page()`), site parsing, and using backends like Jina, Ant, etc., for reading and extracting content from URL links discovered in the search phase.

---

## Key Files and Their Roles

### 1. **Conversation.py** (Lines 2751-3116)
**Purpose:** Main entry point for search in chat flow

**Key Functions:**
- `reply()` method (Line ~2374): Main chat response method that triggers web search
- Agent Factory (Line ~2206-2220): Creates search agents based on configuration

**Search Trigger Logic (Lines 2751-2766):**
```python
if google_scholar or perform_web_search:
    web_results = get_async_future(web_search_queue, user_query, ...)
    perplexity_agent = PerplexitySearchAgent(self.get_api_keys(), ...)
    perplexity_results_future = get_async_future(perplexity_agent.get_answer, ...)
```

**Variables to Track:**
- `perform_web_search` - Boolean flag if user wants web search
- `google_scholar` - Boolean flag for academic search
- `provide_detailed_answers` - Detail level (1-4)
- `web_results` - Future for traditional web search
- `perplexity_results_future` - Future for Perplexity search

---

### 2. **base.py** (Lines 509-2768)
**Purpose:** Core search and LLM utilities

**Key SERP Functions:**

| Function | Lines | Purpose |
|----------|-------|---------|
| `bingapi()` | 551-596 | Bing Search API wrapper |
| `brightdata_google_serp()` | 598-661 | Google SERP via BrightData proxy |
| `serpapi()` | (imported) | SerpAPI wrapper |
| `googleapi_v2()` | (imported) | Google Custom Search API |

**Core Search Pipeline:**

| Function | Lines | Purpose |
|----------|-------|---------|
| `web_search_part1_real()` | 1524-1878 | Generates queries & fetches SERP results |
| `web_search_queue()` | 1883-1904 | Orchestrates search + link reading |
| `queued_read_over_multiple_links()` | 2681-2764 | Parallel link scraping |
| `simple_web_search_with_llm()` | 2088-2118 | Search + LLM summarization |

**Search Query Generation (Lines 1544):**
Uses `prompts.web_search_prompt` to generate search queries via LLM.

**SERP Provider Selection (Lines 1597-1714):**
```python
if os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None:
    serps.extend([get_async_future(brightdata_google_serp, query, ...)])
if bing_available:
    serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], ...)])
```

---

### 3. **agents/search_and_information_agents.py** (Lines 1-1789)
**Purpose:** Search agent implementations

**Agent Classes:**

| Class | Lines | Description |
|-------|-------|-------------|
| `WebSearchWithAgent` | 42-243 | Base search agent using SERP + scraping |
| `LiteratureReviewAgent` | 245-318 | Academic literature search |
| `BroadSearchAgent` | 321-340 | Wide coverage search |
| `PerplexitySearchAgent` | 998-1131 | Perplexity API search |
| `JinaSearchAgent` | 1134-1339 | Jina AI search + reader API |
| `JinaDeepResearchAgent` | 1539-1786 | Jina deep research API |
| `MultiSourceSearchAgent` | 1356-1536 | Combines web + perplexity + jina |
| `OpenaiDeepResearchAgent` | 1342-1350 | OpenAI deep research (placeholder) |

**PerplexitySearchAgent Details (Lines 998-1131):**
- Uses Perplexity models: `perplexity/sonar-pro`, `perplexity/sonar`, `perplexity/sonar-reasoning`
- Generates multiple queries via LLM
- Calls Perplexity API in parallel for each query
- Combines results with combiner LLM

**JinaSearchAgent Details (Lines 1134-1339):**
- Uses Jina Search API (`s.jina.ai`) for results
- Uses Jina Reader API (`r.jina.ai`) for content extraction
- Summarizes results with LLM

---

### 4. **web_scraping.py** (Lines 1-1221)
**Purpose:** Web page scraping utilities

**Scraping Backends:**

| Function | Lines | Provider |
|----------|-------|----------|
| `send_request_jina_html()` | 312-406 | Jina Reader API |
| `send_request_ant_html()` | 244-274 | ScrapingAnt API |
| `send_request_zenrows_html()` | 704-740 | ZenRows API |
| `fetch_content_brightdata_html()` | 554-589 | BrightData Proxy |
| `browse_to_page_playwright()` | 450-491 | Playwright browser |
| `browse_to_page_selenium()` | 493-539 | Selenium browser |

**Main Scraping Function (Lines 980-1057):**
```python
def web_scrape_page(link, context, apikeys, web_search_tmp_marker_name=None, detailed=False):
    # Tries multiple backends in parallel:
    # - ScrapingAnt
    # - BrightData  
    # - Jina Reader
    # Returns first successful result
```

---

### 5. **prompts.py** (Lines 1118-1188)
**Purpose:** Prompt templates for search

**Key Property:** `web_search_prompt` (Line 1118)
- Generates web search queries from user question
- Includes date context and query formatting instructions

---

### 6. **common.py** (Lines 1-2500+)
**Purpose:** Shared utilities

**Key Async Functions (from very_common.py):**
- `get_async_future()` - Run function in thread pool
- `sleep_and_get_future_result()` - Wait for future with timeout
- `wrap_in_future()` - Wrap value in completed future

---

## Data Flow: Web Search in Chat

1. **User sends message** → `server.py:/send_message`
2. **Load conversation** → `Conversation.load_conversation()`
3. **Check search flags** → `reply()` checks `perform_web_search`, `google_scholar`
4. **Parallel search dispatch:**
   - `web_search_queue()` → SERP + link scraping
   - `PerplexitySearchAgent.get_answer()` → Perplexity API
5. **SERP results** → `web_search_part1_real()`:
   - Generate queries via LLM (`prompts.web_search_prompt`)
   - Call SERP APIs (Bing, Google via BrightData)
   - Return links + snippets
6. **Link scraping** → `queued_read_over_multiple_links()`:
   - Fetch page content via `web_scrape_page()`
   - Summarize with LLM
7. **Collect results** → Combine in chat response
8. **Stream to client** → Generator yields chunks

---

## API Keys Required

| Key Name | Environment Variable | Used For |
|----------|---------------------|----------|
| `bingKey` | `BING_SUBSCRIPTION_KEY` | Bing SERP API |
| `brightdataUrl` | `BRIGHTDATA_PROXY` | BrightData proxy |
| `BRIGHTDATA_SERP_API_PROXY` | env var | Google SERP via BrightData |
| `zenrows` | config | ZenRows scraping |
| `scrapingant` | config | ScrapingAnt scraping |
| `jinaAIKey` | `jinaAIKey` | Jina Search/Reader API |
| `openaiKey` | config | LLM calls (incl. Perplexity via OpenRouter) |

---

## Agent Factory Pattern (Conversation.py Lines 2206-2220)

```python
if field == "PerplexitySearch":
    agent = PerplexitySearchAgent(self.get_api_keys(), model_name=..., detail_level=...)
if field == "WebSearch":
    agent = WebSearchWithAgent(self.get_api_keys(), model_name=..., timeout=90)
if field == "MultiSourceSearch":
    agent = MultiSourceSearchAgent(self.get_api_keys(), ...)
if field == "JinaDeepResearchAgent":
    agent = JinaDeepResearchAgent(self.get_api_keys(), ...)
```

---

## Key Integration Points for Modifications

### To Add a New Search Provider:

1. **Create scraping function** in `web_scraping.py`:
   ```python
   def send_request_new_provider(url, apikey):
       # Fetch and return {"title": ..., "text": ...}
   ```

2. **Add to web_scrape_page()** in `web_scraping.py`:
   ```python
   if "newProviderKey" in apikeys:
       new_provider_result = get_async_future(send_request_for_webpage, link, 
                                              apikeys['newProviderKey'], 
                                              zenrows_or_ant='new_provider')
   ```

3. **Register in send_request_for_webpage()** (web_scraping.py):
   ```python
   elif zenrows_or_ant == 'new_provider':
       html = send_request_new_provider(url, apikey)
   ```

### To Add a New Search Agent:

1. **Create agent class** in `agents/search_and_information_agents.py`:
   ```python
   class NewSearchAgent(WebSearchWithAgent):
       def __init__(self, keys, model_name, ...):
           super().__init__(keys, model_name, ...)
       
       def get_results_from_web_search(self, text, text_queries_contexts):
           # Custom search logic
           ...
   ```

2. **Register in Agent Factory** (Conversation.py ~Line 2210):
   ```python
   if field == "NewSearch":
       agent = NewSearchAgent(self.get_api_keys(), model_name=...)
   ```

3. **Export from agents/__init__.py**

---

## Files to Look At for Implementation

| Purpose | Files |
|---------|-------|
| Search orchestration | `Conversation.py` (lines 2751-3150) |
| SERP APIs | `base.py` (lines 509-700, 1521-1900) |
| Search agents | `agents/search_and_information_agents.py` |
| Web scraping | `web_scraping.py` |
| Async utilities | `common.py`, `very_common.py` |
| Prompts | `prompts.py` (line 1118) |
| API key handling | `server.py` (keyParser function) |

---

## Possible Challenges

1. **Rate Limiting:** Multiple SERP calls may hit rate limits
2. **Timeout Management:** Search has configurable timeouts via `max_time_to_wait_for_web_results`
3. **API Key Dependencies:** Many features require multiple API keys
4. **Result Deduplication:** SERP results are deduplicated by URL and title
5. **Scraping Fallbacks:** Multiple scraping backends tried in parallel

---

## Test File

`test_serp.py` - Tests SERP API functions:
```python
from base import serpapi, brightdata_google_serp, googleapi_v2
```

---

*Generated for implementation reference. Review actual code for latest changes.*

