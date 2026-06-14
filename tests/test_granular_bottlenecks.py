#!/usr/bin/env python3
"""
Granular bottleneck testing for web search components.

This module provides fine-grained timing measurements to isolate specific
bottlenecks identified in the performance analysis.

Usage:
    conda activate science-reader
    python tests/test_granular_bottlenecks.py "your search query"

Specific Bottlenecks Tested:
    1. Query Generation LLM latency
    2. Individual SERP provider latency comparison
    3. Embedding computation overhead
    4. Link scraping per-backend timing
    5. Per-link LLM summarization time
    6. MultiSourceSearchAgent sequential wait bug
    7. Perplexity multi-model overhead
    8. Jina content fetching overhead

Author: Auto-generated for performance debugging
"""

import os
import sys
import time
import json
import argparse
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED, ALL_COMPLETED

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_test_keys() -> Dict[str, str]:
    """Load API keys from environment variables."""
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
class GranularTimingResult:
    """Stores detailed timing for a granular test."""
    test_name: str
    total_duration: float
    sub_timings: Dict[str, float]
    success: bool
    error: Optional[str] = None
    notes: str = ""


class GranularBottleneckTester:
    """Tests specific bottlenecks in the search pipeline."""
    
    def __init__(self, keys: Dict, query: str):
        self.keys = keys
        self.query = query
        self.results: List[GranularTimingResult] = []
    
    def test_query_generation_variants(self) -> GranularTimingResult:
        """Test query generation with different models."""
        from call_llm import CallLLm
        from prompts import web_search_prompt
        from base import CHEAP_LLM, CHEAP_LONG_CONTEXT_LLM
        
        print("\n[1] Testing Query Generation Model Variants...")
        
        sub_timings = {}
        start = time.time()
        
        prompt = web_search_prompt.format(
            context=self.query,
            doc_context="",
            pqs="",
            n_query="four"
        )
        
        # Test with CHEAP_LLM
        try:
            t0 = time.time()
            llm = CallLLm(self.keys, use_gpt4=False, model_name=CHEAP_LLM[0])
            result = llm(prompt, temperature=0.5, max_tokens=100)
            sub_timings[f"CHEAP_LLM ({CHEAP_LLM[0]})"] = time.time() - t0
            print(f"   CHEAP_LLM: {sub_timings[f'CHEAP_LLM ({CHEAP_LLM[0]})']: .2f}s")
        except Exception as e:
            sub_timings[f"CHEAP_LLM ({CHEAP_LLM[0]})"] = -1
            print(f"   CHEAP_LLM: FAILED - {e}")
        
        # Test with CHEAP_LONG_CONTEXT_LLM
        try:
            t0 = time.time()
            llm = CallLLm(self.keys, model_name=CHEAP_LONG_CONTEXT_LLM[0])
            result = llm(prompt, temperature=0.5, max_tokens=100)
            sub_timings[f"CHEAP_LONG_CONTEXT ({CHEAP_LONG_CONTEXT_LLM[0]})"] = time.time() - t0
            print(f"   CHEAP_LONG_CONTEXT: {sub_timings[f'CHEAP_LONG_CONTEXT ({CHEAP_LONG_CONTEXT_LLM[0]})']: .2f}s")
        except Exception as e:
            sub_timings[f"CHEAP_LONG_CONTEXT ({CHEAP_LONG_CONTEXT_LLM[0]})"] = -1
            print(f"   CHEAP_LONG_CONTEXT: FAILED - {e}")
        
        return GranularTimingResult(
            test_name="Query Generation Model Comparison",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def test_serp_provider_comparison(self) -> GranularTimingResult:
        """Compare SERP provider latencies side-by-side."""
        from very_common import get_async_future, sleep_and_get_future_result
        
        print("\n[2] Testing SERP Provider Comparison (Parallel)...")
        
        sub_timings = {}
        start = time.time()
        futures = {}
        
        num_results = 10
        year_month = datetime.now().strftime("%Y-%m")
        
        # Launch all SERP calls in parallel
        if self.keys.get("bingKey"):
            from base import bingapi
            futures["Bing"] = get_async_future(bingapi, self.query, self.keys["bingKey"], num_results, our_datetime=year_month)
        
        brightdata_key = os.getenv("BRIGHTDATA_SERP_API_PROXY")
        if brightdata_key:
            from base import brightdata_google_serp
            futures["BrightData Google"] = get_async_future(brightdata_google_serp, self.query, brightdata_key, num_results, our_datetime=year_month)
        
        if self.keys.get("serpApiKey"):
            from base import serpapi
            futures["SerpAPI"] = get_async_future(serpapi, self.query, self.keys["serpApiKey"], num_results, our_datetime=year_month)
        
        if self.keys.get("googleSearchApiKey") and self.keys.get("googleSearchCxId"):
            from base import googleapi_v2
            futures["Google Custom"] = get_async_future(
                googleapi_v2, self.query,
                {"cx": self.keys["googleSearchCxId"], "api_key": self.keys["googleSearchApiKey"]},
                num_results, our_datetime=year_month
            )
        
        # Wait for each and record times
        for name, future in futures.items():
            try:
                result = sleep_and_get_future_result(future, timeout=30)
                sub_timings[name] = time.time() - start
                print(f"   {name}: {sub_timings[name]:.2f}s ({len(result) if result else 0} results)")
            except Exception as e:
                sub_timings[name] = -1
                print(f"   {name}: FAILED - {e}")
        
        return GranularTimingResult(
            test_name="SERP Provider Comparison",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True,
            notes="All providers launched in parallel"
        )
    
    def test_embedding_overhead(self) -> GranularTimingResult:
        """Test embedding computation overhead at scale."""
        from base import get_text_embedding
        
        print("\n[3] Testing Embedding Computation Overhead...")
        
        sub_timings = {}
        start = time.time()
        
        # Simulate real scenario: query + 20 search results
        test_texts = [
            self.query,
            *[f"Search result {i}: Title about {self.query} - Description with more details about the topic" for i in range(20)]
        ]
        
        # Sequential embeddings
        t0 = time.time()
        for text in test_texts[:5]:
            get_text_embedding(text, self.keys)
        sub_timings["Sequential (5 texts)"] = time.time() - t0
        print(f"   Sequential (5): {sub_timings['Sequential (5 texts)']:.2f}s ({sub_timings['Sequential (5 texts)']/5:.2f}s per text)")
        
        # Parallel embeddings
        from very_common import get_async_future, sleep_and_get_future_result
        t0 = time.time()
        futures = [get_async_future(get_text_embedding, text, self.keys) for text in test_texts[:10]]
        for f in futures:
            sleep_and_get_future_result(f, timeout=30)
        sub_timings["Parallel (10 texts)"] = time.time() - t0
        print(f"   Parallel (10): {sub_timings['Parallel (10 texts)']:.2f}s ({sub_timings['Parallel (10 texts)']/10:.2f}s per text)")
        
        return GranularTimingResult(
            test_name="Embedding Computation Overhead",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def test_scraping_backend_comparison(self) -> GranularTimingResult:
        """Compare scraping backend latencies."""
        from very_common import get_async_future, sleep_and_get_future_result
        from web_scraping import send_request_jina_html, send_request_ant_html, fetch_content_brightdata_html
        
        print("\n[4] Testing Scraping Backend Comparison...")
        
        sub_timings = {}
        start = time.time()
        
        test_url = "https://en.wikipedia.org/wiki/Machine_learning"
        
        # Test Jina Reader
        if self.keys.get("jinaAIKey"):
            try:
                t0 = time.time()
                result = send_request_jina_html(test_url, self.keys["jinaAIKey"], readability=True)
                sub_timings["Jina Reader"] = time.time() - t0
                print(f"   Jina Reader: {sub_timings['Jina Reader']:.2f}s ({len(result) if result else 0} chars)")
            except Exception as e:
                sub_timings["Jina Reader"] = -1
                print(f"   Jina Reader: FAILED - {e}")
        
        # Test ScrapingAnt
        if self.keys.get("scrapingant"):
            try:
                t0 = time.time()
                result = send_request_ant_html(test_url, self.keys["scrapingant"], readability=True)
                sub_timings["ScrapingAnt"] = time.time() - t0
                print(f"   ScrapingAnt: {sub_timings['ScrapingAnt']:.2f}s ({len(result) if result else 0} chars)")
            except Exception as e:
                sub_timings["ScrapingAnt"] = -1
                print(f"   ScrapingAnt: FAILED - {e}")
        
        # Test BrightData
        if self.keys.get("brightdataUrl"):
            try:
                t0 = time.time()
                result = fetch_content_brightdata_html(test_url, self.keys["brightdataUrl"], clean_parse=True)
                sub_timings["BrightData"] = time.time() - t0
                print(f"   BrightData: {sub_timings['BrightData']:.2f}s ({len(result) if result else 0} chars)")
            except Exception as e:
                sub_timings["BrightData"] = -1
                print(f"   BrightData: FAILED - {e}")
        
        return GranularTimingResult(
            test_name="Scraping Backend Comparison",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def test_sequential_vs_parallel_waits(self) -> GranularTimingResult:
        """
        Demonstrate the sequential wait bug in MultiSourceSearchAgent.
        Simulates three async operations and compares sequential vs parallel waiting.
        """
        from very_common import get_async_future, sleep_and_get_future_result
        
        print("\n[5] Testing Sequential vs Parallel Wait Bug...")
        
        sub_timings = {}
        start = time.time()
        
        # Simulate three async operations with different durations
        def slow_op(name: str, duration: float):
            time.sleep(duration)
            return f"{name} completed in {duration}s"
        
        # Launch all in parallel
        future1 = get_async_future(slow_op, "Op1", 2.0)  # 2 seconds
        future2 = get_async_future(slow_op, "Op2", 3.0)  # 3 seconds
        future3 = get_async_future(slow_op, "Op3", 1.5)  # 1.5 seconds
        
        # Method 1: Sequential waits (current implementation)
        t0 = time.time()
        try:
            r1 = sleep_and_get_future_result(future1, timeout=10)
        except:
            r1 = None
        try:
            r2 = sleep_and_get_future_result(future2, timeout=10)
        except:
            r2 = None
        try:
            r3 = sleep_and_get_future_result(future3, timeout=10)
        except:
            r3 = None
        sub_timings["Sequential Waits"] = time.time() - t0
        
        # Reset futures
        future1 = get_async_future(slow_op, "Op1", 2.0)
        future2 = get_async_future(slow_op, "Op2", 3.0)
        future3 = get_async_future(slow_op, "Op3", 1.5)
        
        # Method 2: Parallel wait with concurrent.futures.wait
        t0 = time.time()
        done, not_done = wait([future1, future2, future3], timeout=10, return_when=ALL_COMPLETED)
        results = [f.result() for f in done]
        sub_timings["Parallel Wait (Fixed)"] = time.time() - t0
        
        print(f"   Sequential Waits: {sub_timings['Sequential Waits']:.2f}s")
        print(f"   Parallel Wait: {sub_timings['Parallel Wait (Fixed)']:.2f}s")
        print(f"   Improvement: {sub_timings['Sequential Waits'] - sub_timings['Parallel Wait (Fixed)']:.2f}s")
        
        return GranularTimingResult(
            test_name="Sequential vs Parallel Wait Bug",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True,
            notes="Demonstrates ~3s overhead from sequential waits"
        )
    
    def test_perplexity_multi_model_overhead(self) -> GranularTimingResult:
        """Test overhead of calling multiple Perplexity models."""
        from call_llm import CallLLm
        from very_common import get_async_future, sleep_and_get_future_result
        
        print("\n[6] Testing Perplexity Multi-Model Overhead...")
        
        sub_timings = {}
        start = time.time()
        
        perplexity_models = [
            "perplexity/sonar-pro",
            "perplexity/sonar",
        ]
        
        test_prompt = f"What are the latest developments in: {self.query}"
        
        # Test each model individually
        for model in perplexity_models:
            try:
                t0 = time.time()
                llm = CallLLm(self.keys, model_name=model)
                result = llm(test_prompt, temperature=0.7, stream=False, max_tokens=500)
                sub_timings[model] = time.time() - t0
                print(f"   {model}: {sub_timings[model]:.2f}s ({len(result)} chars)")
            except Exception as e:
                sub_timings[model] = -1
                print(f"   {model}: FAILED - {e}")
        
        # Test parallel execution
        t0 = time.time()
        futures = []
        for model in perplexity_models:
            llm = CallLLm(self.keys, model_name=model)
            futures.append(get_async_future(llm, test_prompt, temperature=0.7, stream=False, max_tokens=500))
        
        for f in futures:
            try:
                sleep_and_get_future_result(f, timeout=60)
            except:
                pass
        sub_timings["All Models Parallel"] = time.time() - t0
        print(f"   All Parallel: {sub_timings['All Models Parallel']:.2f}s")
        
        return GranularTimingResult(
            test_name="Perplexity Multi-Model Overhead",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def test_llm_summarization_overhead(self) -> GranularTimingResult:
        """Test LLM summarization overhead for link content."""
        from base import ContextualReader
        
        print("\n[7] Testing LLM Summarization Overhead...")
        
        sub_timings = {}
        start = time.time()
        
        # Sample content of varying lengths
        short_content = "AI advances include GPT-4 improvements and multimodal capabilities." * 10
        medium_content = short_content * 10  # ~1000 words
        long_content = short_content * 50   # ~5000 words
        
        context = self.query
        
        # Test short content
        try:
            t0 = time.time()
            reader = ContextualReader(self.keys, provide_short_responses=True, scan=False)
            result, _ = reader(context, short_content, retriever=None)
            sub_timings["Short (~200 words)"] = time.time() - t0
            print(f"   Short: {sub_timings['Short (~200 words)']:.2f}s")
        except Exception as e:
            sub_timings["Short (~200 words)"] = -1
            print(f"   Short: FAILED - {e}")
        
        # Test medium content
        try:
            t0 = time.time()
            reader = ContextualReader(self.keys, provide_short_responses=True, scan=False)
            result, _ = reader(context, medium_content, retriever=None)
            sub_timings["Medium (~1000 words)"] = time.time() - t0
            print(f"   Medium: {sub_timings['Medium (~1000 words)']:.2f}s")
        except Exception as e:
            sub_timings["Medium (~1000 words)"] = -1
            print(f"   Medium: FAILED - {e}")
        
        # Test long content
        try:
            t0 = time.time()
            reader = ContextualReader(self.keys, provide_short_responses=True, scan=False)
            result, _ = reader(context, long_content, retriever=None)
            sub_timings["Long (~5000 words)"] = time.time() - t0
            print(f"   Long: {sub_timings['Long (~5000 words)']:.2f}s")
        except Exception as e:
            sub_timings["Long (~5000 words)"] = -1
            print(f"   Long: FAILED - {e}")
        
        return GranularTimingResult(
            test_name="LLM Summarization Overhead",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def test_jina_search_and_fetch(self) -> GranularTimingResult:
        """Test Jina search and content fetch separately."""
        
        print("\n[8] Testing Jina Search + Fetch Breakdown...")
        
        sub_timings = {}
        start = time.time()
        
        if not self.keys.get("jinaAIKey"):
            print("   SKIPPED: No jinaAIKey")
            return GranularTimingResult(
                test_name="Jina Search + Fetch Breakdown",
                total_duration=0,
                sub_timings={},
                success=False,
                error="No jinaAIKey"
            )
        
        import requests
        import urllib.parse
        
        # Test Jina Search API
        try:
            t0 = time.time()
            encoded_query = urllib.parse.quote(self.query)
            url = f"https://s.jina.ai/?q={encoded_query}&num=5"
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.keys['jinaAIKey']}",
                "X-Engine": "cf-browser-rendering"
            }
            response = requests.get(url, headers=headers, timeout=30)
            search_data = response.json()
            sub_timings["Jina Search API"] = time.time() - t0
            results = search_data.get("data", [])
            print(f"   Search API: {sub_timings['Jina Search API']:.2f}s ({len(results)} results)")
        except Exception as e:
            sub_timings["Jina Search API"] = -1
            results = []
            print(f"   Search API: FAILED - {e}")
        
        # Test Jina Reader API for first result
        if results:
            try:
                test_url = results[0].get("url", "")
                if test_url:
                    t0 = time.time()
                    reader_url = f"https://r.jina.ai/{test_url}"
                    headers = {
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.keys['jinaAIKey']}"
                    }
                    response = requests.get(reader_url, headers=headers, timeout=30)
                    content_data = response.json()
                    sub_timings["Jina Reader API (1 link)"] = time.time() - t0
                    print(f"   Reader API: {sub_timings['Jina Reader API (1 link)']:.2f}s")
            except Exception as e:
                sub_timings["Jina Reader API (1 link)"] = -1
                print(f"   Reader API: FAILED - {e}")
        
        return GranularTimingResult(
            test_name="Jina Search + Fetch Breakdown",
            total_duration=time.time() - start,
            sub_timings=sub_timings,
            success=True
        )
    
    def run_all_tests(self) -> List[GranularTimingResult]:
        """Run all granular bottleneck tests."""
        print("\n" + "="*80)
        print("GRANULAR BOTTLENECK ANALYSIS")
        print("="*80)
        print(f"Query: {self.query}")
        print(f"Time: {datetime.now().isoformat()}")
        print("="*80)
        
        tests = [
            self.test_query_generation_variants,
            self.test_serp_provider_comparison,
            self.test_embedding_overhead,
            self.test_scraping_backend_comparison,
            self.test_sequential_vs_parallel_waits,
            self.test_perplexity_multi_model_overhead,
            self.test_llm_summarization_overhead,
            self.test_jina_search_and_fetch,
        ]
        
        results = []
        for test in tests:
            try:
                result = test()
                results.append(result)
            except Exception as e:
                print(f"   TEST FAILED: {e}")
                traceback.print_exc()
                results.append(GranularTimingResult(
                    test_name=test.__name__,
                    total_duration=0,
                    sub_timings={},
                    success=False,
                    error=str(e)
                ))
        
        self.results = results
        return results
    
    def print_summary(self):
        """Print a summary of all test results."""
        print("\n" + "="*80)
        print("SUMMARY - GRANULAR BOTTLENECK ANALYSIS")
        print("="*80)
        
        for result in self.results:
            status = "✓" if result.success else "✗"
            print(f"\n{status} {result.test_name}: {result.total_duration:.2f}s")
            for name, timing in result.sub_timings.items():
                if timing >= 0:
                    print(f"    └─ {name}: {timing:.2f}s")
                else:
                    print(f"    └─ {name}: FAILED")
            if result.notes:
                print(f"    Notes: {result.notes}")
        
        print("\n" + "="*80)
        
        # Identify top bottlenecks
        all_sub_timings = []
        for result in self.results:
            for name, timing in result.sub_timings.items():
                if timing > 0:
                    all_sub_timings.append((name, timing))
        
        all_sub_timings.sort(key=lambda x: x[1], reverse=True)
        
        print("\nTOP BOTTLENECKS:")
        for i, (name, timing) in enumerate(all_sub_timings[:5], 1):
            print(f"  {i}. {name}: {timing:.2f}s")
        
        print("="*80)
    
    def save_report(self, filepath: str):
        """Save results as JSON report."""
        report = {
            "query": self.query,
            "timestamp": datetime.now().isoformat(),
            "results": [asdict(r) for r in self.results]
        }
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Granular bottleneck testing for web search components"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="What are the latest advances in large language models in 2024?",
        help="Search query to test with"
    )
    
    args = parser.parse_args()
    
    keys = load_test_keys()
    if not keys.get("OPENROUTER_API_KEY"):
        print("ERROR: Missing OPENROUTER_API_KEY")
        sys.exit(1)
    
    tester = GranularBottleneckTester(keys, args.query)
    tester.run_all_tests()
    tester.print_summary()
    
    report_path = os.path.join(os.path.dirname(__file__), "timing_report_granular.json")
    tester.save_report(report_path)


if __name__ == "__main__":
    main()

