#!/usr/bin/env python3
"""
Test harness for timing analysis of MultiSourceSearchAgent.

This module provides granular timing measurements for the MultiSourceSearchAgent
which combines WebSearchWithAgent, PerplexitySearchAgent, and JinaSearchAgent.

Usage:
    conda activate science-reader
    python tests/test_multi_source_search_timing.py "your search query here"
    
    Or with VSCode debugger using the "Debug: MultiSource Search Timing" configuration.

Components Tested:
    1. WebSearchWithAgent individual timing
    2. PerplexitySearchAgent individual timing
    3. JinaSearchAgent individual timing
    4. MultiSourceSearchAgent combined (parallel) timing
    5. Final combiner LLM timing
    6. Query generation for each agent

Author: Auto-generated for performance debugging
"""

import os
import sys
import time
import json
import argparse
import traceback
import shutil
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _maybe_inject_from_launch_json() -> None:
    """
    Convenience for CLI runs: VSCode `launch.json` is JSONC (allows `//` comments).
    If expected env vars are missing, try to inject them from `.vscode/launch.json`.
    """
    required = ["OPENROUTER_API_KEY", "openAIKey", "jinaAIKey", "googleSearchApiKey", "googleSearchCxId"]
    if all(os.environ.get(k) for k in required):
        return

    launch_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".vscode", "launch.json")
    if not os.path.exists(launch_path):
        return

    try:
        with open(launch_path, "r", encoding="utf-8") as f:
            raw = f.read()
        filtered_lines = []
        for line in raw.splitlines():
            if line.lstrip().startswith("//"):
                continue
            filtered_lines.append(line)
        data = json.loads("\n".join(filtered_lines)) or {}
        configs = data.get("configurations", []) or []
        for cfg in configs:
            env = (cfg or {}).get("env") or {}
            if not isinstance(env, dict) or not env:
                continue
            for k, v in env.items():
                if v is None:
                    continue
                if not os.environ.get(k):
                    os.environ[k] = str(v)
    except Exception:
        # Silent by design; never print secrets
        return


def clear_cache(verbose: bool = True) -> bool:
    """Clear the diskcache cache to ensure fresh results.
    
    Returns True if cache was cleared, False otherwise.
    """
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "cache")
    
    if os.path.exists(cache_dir):
        try:
            # Try to use diskcache's clear method first
            import diskcache as dc
            cache = dc.Cache(cache_dir)
            cache_size = len(cache)
            cache.clear()
            cache.close()
            if verbose:
                print(f"[Cache] Cleared {cache_size} cached entries from {cache_dir}")
            return True
        except Exception as e:
            # Fallback: remove directory and recreate
            if verbose:
                print(f"[Cache] Warning: Could not clear cache cleanly: {e}")
            try:
                shutil.rmtree(cache_dir)
                os.makedirs(cache_dir, exist_ok=True)
                if verbose:
                    print(f"[Cache] Removed and recreated cache directory: {cache_dir}")
                return True
            except Exception as e2:
                if verbose:
                    print(f"[Cache] Error clearing cache: {e2}")
                return False
    else:
        if verbose:
            print(f"[Cache] No cache directory found at {cache_dir}")
        return False


def load_test_keys() -> Dict[str, str]:
    """Load API keys from environment variables."""
    _maybe_inject_from_launch_json()
    keys = {
        "openAIKey": os.getenv("openAIKey", ""),
        "jinaAIKey": os.getenv("jinaAIKey", ""),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
        "bingKey": os.getenv("bingKey", ""),
        "serpApiKey": os.getenv("serpApiKey", ""),
        "googleSearchApiKey": os.getenv("googleSearchApiKey", ""),
        "googleSearchCxId": os.getenv("googleSearchCxId", ""),
        "brightdataUrl": os.getenv("brightdataUrl", ""),
        "brightdataProxy": os.getenv("brightdataProxy", ""),
        "zenrows": os.getenv("zenrows", ""),
        "scrapingant": os.getenv("scrapingant", ""),
        "ASSEMBLYAI_API_KEY": os.getenv("ASSEMBLYAI_API_KEY", ""),
    }
    return keys


@dataclass
class TimingResult:
    """Stores timing result for a single operation."""
    name: str
    duration_seconds: float
    success: bool
    result_summary: str = ""
    error: Optional[str] = None
    sub_timings: Dict[str, float] = field(default_factory=dict)


@dataclass 
class TimingReport:
    """Aggregate timing report for all operations."""
    query: str
    timestamp: str
    total_duration_seconds: float
    results: List[TimingResult] = field(default_factory=list)
    
    def add_result(self, result: TimingResult):
        self.results.append(result)
    
    def print_report(self):
        """Print a formatted timing report."""
        print("\n" + "="*80)
        print(f"TIMING REPORT - MultiSourceSearchAgent Components")
        print(f"Query: {self.query}")
        print(f"Timestamp: {self.timestamp}")
        print(f"Total Duration: {self.total_duration_seconds:.2f}s")
        print("="*80)
        
        # Sort by duration
        sorted_results = sorted(self.results, key=lambda x: x.duration_seconds, reverse=True)
        
        print(f"\n{'Component':<50} {'Duration':<12} {'Status':<10} {'Summary'}")
        print("-"*100)
        
        for r in sorted_results:
            status = "✓ OK" if r.success else "✗ FAIL"
            summary = r.result_summary[:35] + "..." if len(r.result_summary) > 35 else r.result_summary
            print(f"{r.name:<50} {r.duration_seconds:>8.2f}s   {status:<10} {summary}")
            if r.error:
                print(f"{'':>50} Error: {r.error[:50]}...")
            if r.sub_timings:
                for sub_name, sub_dur in r.sub_timings.items():
                    print(f"  └─ {sub_name:<46} {sub_dur:>8.2f}s")
        
        print("\n" + "="*80)
        print("BOTTLENECK ANALYSIS:")
        print("-"*80)
        
        if sorted_results:
            top_bottleneck = sorted_results[0]
            print(f"  Slowest component: {top_bottleneck.name} ({top_bottleneck.duration_seconds:.2f}s)")
            
            # Calculate percentage of total time
            for r in sorted_results[:5]:
                pct = (r.duration_seconds / self.total_duration_seconds * 100) if self.total_duration_seconds > 0 else 0
                print(f"  - {r.name}: {pct:.1f}% of total time")
        
        print("="*80 + "\n")
    
    def to_json(self) -> str:
        """Export report as JSON for further analysis."""
        return json.dumps(asdict(self), indent=2)


def test_query_generation_timing(keys: Dict, query: str) -> TimingResult:
    """Test query generation timing for agents."""
    from call_llm import CallLLm
    from base import CHEAP_LLM
    
    print("\n[1/7] Testing Query Generation Timing...")
    
    # WebSearchWithAgent llm_prompt template
    llm_prompt = """
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1', 'detailed context1 including conversational context on what user is looking for'), 
    ('query2', 'detailed context2 including conversational context on what user is looking for'), 
    ('query3', 'detailed context3 including conversational context on what user is looking for'), 
    ...
]
```

Text: {text}

Generate up to 3 highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    
    try:
        llm = CallLLm(keys, use_gpt4=False, model_name=CHEAP_LLM[0])
        prompt = llm_prompt.format(text=query)
        result = llm(prompt, temperature=0.7, stream=False, max_tokens=None)
        success = True
        result_summary = f"{len(result)} chars generated"
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   Query Generation: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="Query Generation (LLM)",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error
    )


def test_web_search_agent_timing(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test WebSearchWithAgent timing."""
    from agents import WebSearchWithAgent
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[2/7] Testing WebSearchWithAgent Timing...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    sub_timings = {}
    
    try:
        agent = WebSearchWithAgent(
            keys=keys,
            model_name=CHEAP_LONG_CONTEXT_LLM[0],
            detail_level=max(detail_level - 1, 1),
            timeout=60,
            gscholar=False
        )
        
        # Time the full call
        full_answer = ""
        query_gen_end = None
        search_end = None
        
        for chunk in agent(query, images=[], temperature=0.7, stream=False):
            if "Created/Obtained search queries" in chunk.get("status", ""):
                query_gen_end = time.time()
            if "Obtained web search results" in chunk.get("status", ""):
                search_end = time.time()
            full_answer += chunk.get("text", "")
        
        success = True
        result_summary = f"{len(full_answer)} chars"
        
        # Calculate sub-timings
        if query_gen_end:
            sub_timings["Query Generation"] = query_gen_end - start
        if search_end and query_gen_end:
            sub_timings["Web Search Execution"] = search_end - query_gen_end
        if search_end:
            sub_timings["Combiner LLM"] = time.time() - search_end
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   WebSearchWithAgent: {duration:.2f}s - {result_summary}")
    for sub_name, sub_dur in sub_timings.items():
        print(f"     └─ {sub_name}: {sub_dur:.2f}s")
    
    return TimingResult(
        name="WebSearchWithAgent",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        sub_timings=sub_timings
    )


def test_perplexity_agent_timing(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test PerplexitySearchAgent timing."""
    from agents import PerplexitySearchAgent
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[3/7] Testing PerplexitySearchAgent Timing...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    sub_timings = {}
    
    try:
        agent = PerplexitySearchAgent(
            keys=keys,
            model_name=CHEAP_LONG_CONTEXT_LLM[0],
            detail_level=max(detail_level - 1, 1),
            timeout=60,
            num_queries=3
        )
        
        # Time the full call
        full_answer = ""
        query_gen_end = None
        search_end = None
        
        for chunk in agent(query, images=[], temperature=0.7, stream=False):
            if "Created/Obtained search queries" in chunk.get("status", ""):
                query_gen_end = time.time()
            if "Obtained web search results" in chunk.get("status", ""):
                search_end = time.time()
            full_answer += chunk.get("text", "")
        
        success = True
        result_summary = f"{len(full_answer)} chars"
        
        # Calculate sub-timings
        if query_gen_end:
            sub_timings["Query Generation"] = query_gen_end - start
        if search_end and query_gen_end:
            sub_timings["Perplexity API Calls"] = search_end - query_gen_end
        if search_end:
            sub_timings["Combiner LLM"] = time.time() - search_end
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   PerplexitySearchAgent: {duration:.2f}s - {result_summary}")
    for sub_name, sub_dur in sub_timings.items():
        print(f"     └─ {sub_name}: {sub_dur:.2f}s")
    
    return TimingResult(
        name="PerplexitySearchAgent",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        sub_timings=sub_timings
    )


def test_jina_agent_timing(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test JinaSearchAgent timing."""
    from agents import JinaSearchAgent
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[4/7] Testing JinaSearchAgent Timing...")
    
    if not keys.get("jinaAIKey"):
        print("   JinaSearchAgent: SKIPPED (no jinaAIKey)")
        return TimingResult(
            name="JinaSearchAgent",
            duration_seconds=0,
            success=False,
            result_summary="SKIPPED - no API key",
            error="Missing jinaAIKey"
        )
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    sub_timings = {}
    
    try:
        agent = JinaSearchAgent(
            keys=keys,
            model_name=CHEAP_LONG_CONTEXT_LLM[0],
            detail_level=max(detail_level - 1, 1),
            timeout=60,
            num_queries=3
        )
        
        # Time the full call
        full_answer = ""
        query_gen_end = None
        search_end = None
        
        for chunk in agent(query, images=[], temperature=0.7, stream=False):
            if "Created/Obtained search queries" in chunk.get("status", ""):
                query_gen_end = time.time()
            if "Obtained web search results" in chunk.get("status", ""):
                search_end = time.time()
            full_answer += chunk.get("text", "")
        
        success = True
        result_summary = f"{len(full_answer)} chars"
        
        # Calculate sub-timings
        if query_gen_end:
            sub_timings["Query Generation"] = query_gen_end - start
        if search_end and query_gen_end:
            sub_timings["Jina API Calls"] = search_end - query_gen_end
        if search_end:
            sub_timings["Combiner LLM"] = time.time() - search_end
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   JinaSearchAgent: {duration:.2f}s - {result_summary}")
    for sub_name, sub_dur in sub_timings.items():
        print(f"     └─ {sub_name}: {sub_dur:.2f}s")
    
    return TimingResult(
        name="JinaSearchAgent",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        sub_timings=sub_timings
    )


def test_multi_source_agent_timing(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test full MultiSourceSearchAgent timing."""
    from agents import MultiSourceSearchAgent
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[5/7] Testing MultiSourceSearchAgent (Full Pipeline) Timing...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    sub_timings = {}
    
    try:
        agent = MultiSourceSearchAgent(
            keys=keys,
            model_name=CHEAP_LONG_CONTEXT_LLM[0],
            detail_level=detail_level,
            timeout=60,
            num_queries=3
        )
        
        # Time the full call
        full_answer = ""
        web_search_done = None
        perplexity_done = None
        jina_done = None
        
        for chunk in agent(query, images=[], temperature=0.7, stream=False):
            status = chunk.get("status", "")
            text = chunk.get("text", "")
            
            if "Web Search Results" in text and web_search_done is None:
                web_search_done = time.time()
            if "Perplexity Search Results" in text and perplexity_done is None:
                perplexity_done = time.time()
            if "Jina Search Results" in text and jina_done is None:
                jina_done = time.time()
            
            full_answer += text
        
        success = True
        result_summary = f"{len(full_answer)} chars"
        
        # Calculate sub-timings
        if web_search_done:
            sub_timings["WebSearch Wait"] = web_search_done - start
        if perplexity_done:
            sub_timings["Perplexity Wait"] = perplexity_done - start
        if jina_done:
            sub_timings["Jina Wait"] = jina_done - start
        
        # The rest is combiner time
        last_component = max(filter(None, [web_search_done, perplexity_done, jina_done]), default=start)
        sub_timings["Final Combiner LLM"] = time.time() - last_component
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   MultiSourceSearchAgent: {duration:.2f}s - {result_summary}")
    for sub_name, sub_dur in sub_timings.items():
        print(f"     └─ {sub_name}: {sub_dur:.2f}s")
    
    return TimingResult(
        name="MultiSourceSearchAgent (Full)",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        sub_timings=sub_timings
    )


def test_combiner_llm_timing(keys: Dict, query: str) -> TimingResult:
    """Test combiner LLM timing separately."""
    from call_llm import CallLLm
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[6/7] Testing Combiner LLM Timing (isolated)...")
    
    # Simulate combined results
    sample_results = """
    **Web Search Results:**
    - Result 1: AI advances in 2024 include GPT-4 improvements...
    - Result 2: Language models have shown remarkable progress...
    
    **Perplexity Results:**
    - Large language models have evolved significantly...
    - Key advances include multimodal capabilities...
    
    **Jina Results:**
    - Recent papers discuss transformer architectures...
    - Applications in code generation have expanded...
    """
    
    combiner_prompt = f"""
Collate and combine information from multiple search results obtained from different queries. Your goal is to combine these results into a comprehensive response for the user's query.

Instructions:
1. Integrate and utilize information from all provided search results to write your extensive response.
2. Write a detailed, in-depth, wide coverage and comprehensive response to the user's query.

Web search results (from multiple sources):
<|results|>
{sample_results}
</|results|>

User's query: {query}

Please compose your comprehensive response.
"""
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    
    try:
        llm = CallLLm(keys, model_name=CHEAP_LONG_CONTEXT_LLM[0])
        result = llm(combiner_prompt, temperature=0.7, stream=False)
        success = True
        result_summary = f"{len(result)} chars"
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   Combiner LLM: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="Combiner LLM (isolated)",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error
    )


def test_parallel_vs_sequential(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Compare parallel vs sequential execution."""
    from very_common import get_async_future, sleep_and_get_future_result
    from agents import WebSearchWithAgent, PerplexitySearchAgent, JinaSearchAgent
    from base import CHEAP_LONG_CONTEXT_LLM
    
    print("\n[7/7] Testing Parallel Execution Efficiency...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    sub_timings = {}
    
    try:
        # Create agents
        web_agent = WebSearchWithAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], max(detail_level - 1, 1), 60)
        perplexity_agent = PerplexitySearchAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], max(detail_level - 1, 1), 60, 3)
        jina_agent = JinaSearchAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], max(detail_level - 1, 1), 60, 3) if keys.get("jinaAIKey") else None
        
        def extract_answer(agent, text):
            full_answer = ""
            for chunk in agent(text, images=[], temperature=0.7, stream=False):
                full_answer += chunk.get("text", "")
            return full_answer
        
        # Launch all in parallel
        parallel_start = time.time()
        
        web_future = get_async_future(extract_answer, web_agent, query)
        perplexity_future = get_async_future(extract_answer, perplexity_agent, query)
        jina_future = get_async_future(extract_answer, jina_agent, query) if jina_agent else None
        
        # Wait for all with timeouts
        try:
            web_result = sleep_and_get_future_result(web_future, timeout=90)
            sub_timings["WebSearch (parallel)"] = time.time() - parallel_start
        except:
            sub_timings["WebSearch (parallel)"] = 90  # timeout
        
        try:
            perplexity_result = sleep_and_get_future_result(perplexity_future, timeout=90)
            sub_timings["Perplexity (parallel)"] = time.time() - parallel_start
        except:
            sub_timings["Perplexity (parallel)"] = 90
        
        if jina_future:
            try:
                jina_result = sleep_and_get_future_result(jina_future, timeout=45)
                sub_timings["Jina (parallel)"] = time.time() - parallel_start
            except:
                sub_timings["Jina (parallel)"] = 45
        
        success = True
        parallel_duration = time.time() - parallel_start
        
        # Calculate theoretical sequential time
        sequential_estimate = sum(sub_timings.values())
        speedup = sequential_estimate / parallel_duration if parallel_duration > 0 else 0
        
        result_summary = f"Parallel: {parallel_duration:.1f}s, Est Sequential: {sequential_estimate:.1f}s, Speedup: {speedup:.1f}x"
        sub_timings["Theoretical Sequential Total"] = sequential_estimate
        sub_timings["Actual Parallel Total"] = parallel_duration
        sub_timings["Parallel Speedup Factor"] = speedup
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    print(f"   Parallel Execution: {duration:.2f}s")
    print(f"   {result_summary}")
    
    return TimingResult(
        name="Parallel vs Sequential Analysis",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        sub_timings=sub_timings
    )


def run_timing_analysis(query: str, detail_level: int = 1, test_individual: bool = True):
    """Run complete timing analysis for MultiSourceSearchAgent."""
    print("\n" + "="*80)
    print("MULTISOURCESEARCHAGENT TIMING ANALYSIS")
    print("="*80)
    print(f"Query: {query}")
    print(f"Detail Level: {detail_level}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*80)
    
    keys = load_test_keys()
    
    # Validate keys
    if not keys.get("OPENROUTER_API_KEY"):
        print("\nERROR: Missing OPENROUTER_API_KEY")
        sys.exit(1)
    
    # Initialize report
    total_start = time.time()
    report = TimingReport(
        query=query,
        timestamp=datetime.now().isoformat(),
        total_duration_seconds=0
    )
    
    try:
        # Query generation timing
        result = test_query_generation_timing(keys, query)
        report.add_result(result)
        
        if test_individual:
            # Individual agent timings
            result = test_web_search_agent_timing(keys, query, detail_level)
            report.add_result(result)
            
            result = test_perplexity_agent_timing(keys, query, detail_level)
            report.add_result(result)
            
            result = test_jina_agent_timing(keys, query, detail_level)
            report.add_result(result)
        
        # Full MultiSourceSearchAgent
        result = test_multi_source_agent_timing(keys, query, detail_level)
        report.add_result(result)
        
        # Combiner LLM isolated
        result = test_combiner_llm_timing(keys, query)
        report.add_result(result)
        
        # Parallel efficiency analysis
        if test_individual:
            result = test_parallel_vs_sequential(keys, query, detail_level)
            report.add_result(result)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\n\nError during testing: {e}")
        traceback.print_exc()
    
    # Finalize report
    report.total_duration_seconds = time.time() - total_start
    report.print_report()
    
    # Save JSON report
    report_path = os.path.join(os.path.dirname(__file__), "timing_report_multi_source.json")
    with open(report_path, "w") as f:
        f.write(report.to_json())
    print(f"JSON report saved to: {report_path}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for timing analysis of MultiSourceSearchAgent"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="What are the latest advances in large language models in 2024?",
        help="Search query to test with"
    )
    parser.add_argument(
        "--detail-level",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="Detail level (1-4, higher = more thorough but slower)"
    )
    parser.add_argument(
        "--skip-individual",
        action="store_true",
        help="Skip individual agent tests, only test MultiSourceSearchAgent"
    )
    parser.add_argument(
        "--no-clear-cache",
        action="store_true",
        help="Skip clearing cache before running tests (use cached results)"
    )
    
    args = parser.parse_args()
    
    # Clear cache by default (unless --no-clear-cache is specified)
    if not args.no_clear_cache:
        print("\n" + "="*80)
        print("CLEARING CACHE FOR FRESH TEST RUN")
        print("="*80)
        clear_cache(verbose=True)
    else:
        print("\n[Cache] Skipping cache clear (using --no-clear-cache)")
    
    run_timing_analysis(args.query, args.detail_level, not args.skip_individual)


if __name__ == "__main__":
    main()

