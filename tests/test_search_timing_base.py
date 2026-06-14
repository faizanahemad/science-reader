#!/usr/bin/env python3
"""
Test harness for timing analysis of base.py web search functions.

This module provides granular timing measurements for individual components
of the web search pipeline in base.py to identify performance bottlenecks.

Usage:
    conda activate science-reader
    python tests/test_search_timing_base.py "your search query here"
    
    Or with VSCode debugger using the "Debug: Search Timing Base" configuration.

Components Tested:
    1. Query Generation via LLM (web_search_prompt)
    2. SERP API calls (bingapi, brightdata_google_serp, serpapi, googleapi_v2)
    3. Embedding computation for result relevance
    4. Link content scraping (web_scrape_page, download_link_data)
    5. LLM summarization of scraped content (get_downloaded_data_summary)
    6. Full web_search_queue orchestration

Author: Auto-generated for performance debugging
"""

import os
import sys
import time
import json
import argparse
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from concurrent.futures import as_completed

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from launch.json pattern
def load_test_keys() -> Dict[str, str]:
    """
    Load API keys from environment variables.
    These should be set via launch.json or exported before running.
    """
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
        print(f"TIMING REPORT - Web Search Base Components")
        print(f"Query: {self.query}")
        print(f"Timestamp: {self.timestamp}")
        print(f"Total Duration: {self.total_duration_seconds:.2f}s")
        print("="*80)
        
        # Sort by duration
        sorted_results = sorted(self.results, key=lambda x: x.duration_seconds, reverse=True)
        
        print(f"\n{'Component':<45} {'Duration':<12} {'Status':<10} {'Summary'}")
        print("-"*100)
        
        for r in sorted_results:
            status = "✓ OK" if r.success else "✗ FAIL"
            summary = r.result_summary[:40] + "..." if len(r.result_summary) > 40 else r.result_summary
            print(f"{r.name:<45} {r.duration_seconds:>8.2f}s   {status:<10} {summary}")
            if r.error:
                print(f"{'':>45} Error: {r.error[:60]}...")
        
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


def timed_execution(name: str, func, *args, **kwargs) -> TimingResult:
    """Execute a function and return timing result."""
    start = time.time()
    success = False
    result_summary = ""
    error = None
    
    try:
        result = func(*args, **kwargs)
        success = True
        
        # Generate summary based on result type
        if result is None:
            result_summary = "None returned"
        elif isinstance(result, (list, tuple)):
            result_summary = f"{len(result)} items"
        elif isinstance(result, dict):
            result_summary = f"{len(result)} keys"
        elif isinstance(result, str):
            result_summary = f"{len(result)} chars"
        elif hasattr(result, '__iter__'):
            # For generators, consume them
            items = list(result)
            result_summary = f"{len(items)} items (generator)"
        else:
            result_summary = str(type(result).__name__)
            
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    
    duration = time.time() - start
    return TimingResult(name=name, duration_seconds=duration, success=success, 
                       result_summary=result_summary, error=error)


def test_query_generation(keys: Dict, query: str, report: TimingReport):
    """Test LLM query generation timing."""
    from call_llm import CallLLm
    from prompts import web_search_prompt
    from base import CHEAP_LLM
    
    print("\n[1/6] Testing Query Generation via LLM...")
    
    doc_context = ""
    pqs = ""
    n_query = "four"
    prompt = web_search_prompt.format(context=query, doc_context=doc_context, pqs=pqs, n_query=n_query)
    
    def generate_queries():
        llm = CallLLm(keys, use_gpt4=False, model_name=CHEAP_LLM[0])
        return llm(prompt, temperature=0.5, max_tokens=100)
    
    result = timed_execution("Query Generation (LLM)", generate_queries)
    report.add_result(result)
    print(f"   Duration: {result.duration_seconds:.2f}s - {result.result_summary}")
    
    return result


def test_serp_apis(keys: Dict, query: str, report: TimingReport):
    """Test individual SERP API timings."""
    from base import bingapi, brightdata_google_serp, serpapi, googleapi_v2, gscholarapi
    from very_common import get_async_future, sleep_and_get_future_result
    
    print("\n[2/6] Testing SERP API Calls...")
    
    num_results = 10
    year_month = datetime.now().strftime("%Y-%m")
    
    # Test each SERP API individually
    serp_tests = []
    
    # Bing API
    if keys.get("bingKey"):
        def test_bing():
            return bingapi(query, keys["bingKey"], num_results, our_datetime=year_month)
        result = timed_execution("SERP: Bing API", test_bing)
        report.add_result(result)
        serp_tests.append(("Bing", result))
        print(f"   Bing API: {result.duration_seconds:.2f}s - {result.result_summary}")
    else:
        print("   Bing API: SKIPPED (no key)")
    
    # BrightData Google SERP
    brightdata_key = os.getenv("BRIGHTDATA_SERP_API_PROXY")
    if brightdata_key:
        def test_brightdata():
            return brightdata_google_serp(query, brightdata_key, num_results, our_datetime=year_month)
        result = timed_execution("SERP: BrightData Google", test_brightdata)
        report.add_result(result)
        serp_tests.append(("BrightData", result))
        print(f"   BrightData Google: {result.duration_seconds:.2f}s - {result.result_summary}")
    else:
        print("   BrightData Google: SKIPPED (no BRIGHTDATA_SERP_API_PROXY)")
    
    # SerpAPI
    if keys.get("serpApiKey"):
        def test_serpapi():
            return serpapi(query, keys["serpApiKey"], num_results, our_datetime=year_month)
        result = timed_execution("SERP: SerpAPI", test_serpapi)
        report.add_result(result)
        serp_tests.append(("SerpAPI", result))
        print(f"   SerpAPI: {result.duration_seconds:.2f}s - {result.result_summary}")
    else:
        print("   SerpAPI: SKIPPED (no key)")
    
    # Google Custom Search
    if keys.get("googleSearchApiKey") and keys.get("googleSearchCxId"):
        def test_google():
            return googleapi_v2(
                query, 
                {"cx": keys["googleSearchCxId"], "api_key": keys["googleSearchApiKey"]},
                num_results, 
                our_datetime=year_month
            )
        result = timed_execution("SERP: Google Custom Search", test_google)
        report.add_result(result)
        serp_tests.append(("Google", result))
        print(f"   Google Custom Search: {result.duration_seconds:.2f}s - {result.result_summary}")
    else:
        print("   Google Custom Search: SKIPPED (no key)")
    
    return serp_tests


def test_embedding_computation(keys: Dict, query: str, report: TimingReport):
    """Test embedding computation timing."""
    from base import get_text_embedding
    
    print("\n[3/6] Testing Embedding Computation...")
    
    test_texts = [
        query,
        "Sample search result title and description for relevance testing",
        "Another sample text to test embedding computation speed"
    ]
    
    def compute_embeddings():
        embeddings = []
        for text in test_texts:
            emb = get_text_embedding(text, keys)
            embeddings.append(emb)
        return embeddings
    
    result = timed_execution("Embedding Computation (3 texts)", compute_embeddings)
    report.add_result(result)
    print(f"   Duration: {result.duration_seconds:.2f}s for 3 texts")
    print(f"   Per-text average: {result.duration_seconds/3:.2f}s")
    
    return result


def test_link_scraping(keys: Dict, report: TimingReport):
    """Test link scraping timing with various backends."""
    from web_scraping import web_scrape_page, send_request_jina_html, send_request_ant_html
    from base import create_tmp_marker_file, remove_tmp_marker_file
    import uuid
    
    print("\n[4/6] Testing Link Scraping...")
    
    # Test URLs - mix of types
    test_urls = [
        ("Wikipedia (HTML)", "https://en.wikipedia.org/wiki/Artificial_intelligence"),
        ("ArXiv (HTML)", "https://arxiv.org/abs/2301.00234"),
    ]
    
    marker_name = f"_test_scrape_{uuid.uuid4()}"
    create_tmp_marker_file(marker_name)
    
    try:
        for url_name, url in test_urls:
            context = "Test context for scraping"
            
            def scrape_page():
                return web_scrape_page(url, context, keys, 
                                      web_search_tmp_marker_name=marker_name,
                                      detailed=False)
            
            result = timed_execution(f"Scrape: {url_name}", scrape_page)
            report.add_result(result)
            print(f"   {url_name}: {result.duration_seconds:.2f}s - {result.result_summary}")
    finally:
        remove_tmp_marker_file(marker_name)
    
    # Test Jina Reader specifically
    if keys.get("jinaAIKey"):
        def test_jina_reader():
            return send_request_jina_html(
                "https://en.wikipedia.org/wiki/Machine_learning",
                keys["jinaAIKey"],
                readability=True
            )
        result = timed_execution("Scrape: Jina Reader API", test_jina_reader)
        report.add_result(result)
        print(f"   Jina Reader: {result.duration_seconds:.2f}s - {result.result_summary}")


def test_llm_summarization(keys: Dict, report: TimingReport):
    """Test LLM summarization timing."""
    from base import ContextualReader
    
    print("\n[5/6] Testing LLM Summarization...")
    
    # Sample scraped content
    sample_content = """
    Artificial intelligence (AI) is intelligence demonstrated by machines, 
    as opposed to natural intelligence displayed by animals and humans. 
    AI research has been defined as the field of study of intelligent agents, 
    which refers to any system that perceives its environment and takes actions 
    that maximize its chance of achieving its goals.
    
    The field was founded on the assumption that human intelligence can be 
    so precisely described that a machine can be made to simulate it. This 
    raises philosophical arguments about the mind and the ethics of creating 
    artificial beings endowed with human-like intelligence.
    
    Major AI applications include advanced web search engines, recommendation 
    systems, understanding human speech, self-driving cars, automated 
    decision-making, and competing at the highest level in strategic game systems.
    """ * 10  # Make it longer to be more realistic
    
    context = "What is artificial intelligence and its applications?"
    
    def summarize_content():
        reader = ContextualReader(keys, provide_short_responses=True, scan=False)
        result, llm_future = reader(context, sample_content, retriever=None)
        return result
    
    result = timed_execution("LLM Summarization (ContextualReader)", summarize_content)
    report.add_result(result)
    print(f"   Duration: {result.duration_seconds:.2f}s - {result.result_summary}")
    
    return result


def test_full_web_search_queue(keys: Dict, query: str, report: TimingReport):
    """Test full web_search_queue orchestration timing."""
    from base import web_search_queue, create_tmp_marker_file, remove_tmp_marker_file
    from very_common import get_async_future, sleep_and_get_future_result
    import uuid
    
    print("\n[6/6] Testing Full web_search_queue Pipeline...")
    
    marker_name = f"_test_full_{uuid.uuid4()}"
    create_tmp_marker_file(marker_name)
    
    start_time = time.time()
    
    try:
        def run_full_search():
            result = web_search_queue(
                context=query,
                doc_source="test",
                doc_context="",
                api_keys=keys,
                year_month=datetime.now().strftime("%Y-%m"),
                previous_answer=None,
                previous_search_results=None,
                extra_queries=None,
                previous_turn_search_results=None,
                gscholar=False,
                provide_detailed_answers=1,
                web_search_tmp_marker_name=marker_name
            )
            
            # Get part 1 results
            part1_future, read_queue = result
            search_results = None
            
            # Wait for initial results
            timeout_counter = 0
            while timeout_counter < 60:  # 60 second max
                try:
                    search_results = next(part1_future.result())
                    break
                except StopIteration:
                    break
                except:
                    time.sleep(0.5)
                    timeout_counter += 0.5
            
            # Collect some read results
            read_results = []
            read_timeout = 0
            while read_timeout < 30:  # 30 second max for reading
                if not read_queue.empty():
                    item = read_queue.get()
                    if item == "STOP":
                        break
                    read_results.append(item)
                    if len(read_results) >= 3:  # Get first 3 results
                        break
                else:
                    time.sleep(0.5)
                    read_timeout += 0.5
            
            return {"search_results": search_results, "read_results_count": len(read_results)}
        
        result = timed_execution("Full web_search_queue Pipeline", run_full_search)
        report.add_result(result)
        print(f"   Duration: {result.duration_seconds:.2f}s - {result.result_summary}")
        
    finally:
        remove_tmp_marker_file(marker_name)
    
    return result


def run_timing_analysis(query: str, skip_full_pipeline: bool = False):
    """Run complete timing analysis."""
    print("\n" + "="*80)
    print("WEB SEARCH TIMING ANALYSIS - base.py Components")
    print("="*80)
    print(f"Query: {query}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*80)
    
    keys = load_test_keys()
    
    # Validate keys
    required_keys = ["OPENROUTER_API_KEY"]
    missing = [k for k in required_keys if not keys.get(k)]
    if missing:
        print(f"\nERROR: Missing required API keys: {missing}")
        print("Please set these via environment variables or launch.json")
        sys.exit(1)
    
    # Initialize report
    total_start = time.time()
    report = TimingReport(
        query=query,
        timestamp=datetime.now().isoformat(),
        total_duration_seconds=0
    )
    
    try:
        # Run individual tests
        test_query_generation(keys, query, report)
        test_serp_apis(keys, query, report)
        test_embedding_computation(keys, query, report)
        test_link_scraping(keys, report)
        test_llm_summarization(keys, report)
        
        if not skip_full_pipeline:
            test_full_web_search_queue(keys, query, report)
        else:
            print("\n[6/6] Full Pipeline: SKIPPED (--skip-full flag)")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\n\nError during testing: {e}")
        traceback.print_exc()
    
    # Finalize report
    report.total_duration_seconds = time.time() - total_start
    report.print_report()
    
    # Save JSON report
    report_path = os.path.join(os.path.dirname(__file__), "timing_report_base.json")
    with open(report_path, "w") as f:
        f.write(report.to_json())
    print(f"JSON report saved to: {report_path}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for timing analysis of base.py web search functions"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="What are the latest advances in large language models in 2024?",
        help="Search query to test with"
    )
    parser.add_argument(
        "--skip-full",
        action="store_true",
        help="Skip the full web_search_queue pipeline test"
    )
    
    args = parser.parse_args()
    run_timing_analysis(args.query, args.skip_full)


if __name__ == "__main__":
    main()

