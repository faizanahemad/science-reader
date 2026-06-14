#!/usr/bin/env python3
"""
Individual Agent Test Harness for Performance Analysis.

This module tests each search agent independently to identify
specific bottlenecks within each agent's implementation.

Usage:
    conda activate science-reader
    python tests/test_individual_agents.py "your search query" --agent all
    python tests/test_individual_agents.py "your search query" --agent websearch
    python tests/test_individual_agents.py "your search query" --agent perplexity
    python tests/test_individual_agents.py "your search query" --agent jina

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
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def clear_cache(verbose: bool = True) -> bool:
    """Clear the diskcache cache to ensure fresh results."""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "cache")
    
    if os.path.exists(cache_dir):
        try:
            import diskcache as dc
            cache = dc.Cache(cache_dir)
            cache_size = len(cache)
            cache.clear()
            cache.close()
            if verbose:
                print(f"[Cache] Cleared {cache_size} cached entries from {cache_dir}")
            return True
        except Exception as e:
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


class TimingContext:
    """Context manager for timing code blocks."""
    def __init__(self, name: str, results: Dict):
        self.name = name
        self.results = results
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        self.results[self.name] = elapsed
        return False


def get_api_keys() -> Dict:
    """Get API keys from environment variables."""
    # Convenience for local debugging: if env vars are missing, try to load them from
    # `.vscode/launch.json` (many users already keep a local, non-committed copy there).
    # This avoids needing to re-export keys for every terminal session.
    def _maybe_inject_from_launch_json() -> None:
        required = ["openAIKey", "OPENROUTER_API_KEY", "jinaAIKey", "googleSearchApiKey", "googleSearchCxId"]
        if any(not os.environ.get(k) for k in required):
            launch_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".vscode", "launch.json")
            if not os.path.exists(launch_path):
                return
            try:
                import json
                with open(launch_path, "r", encoding="utf-8") as f:
                    # VSCode launch.json often contains `//` comment lines (JSONC).
                    # Strip full-line comments to make it parseable as JSON.
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
                # Silent by design: don't spam output or accidentally print secrets.
                return

    _maybe_inject_from_launch_json()
    return {
        "openAIKey": os.environ.get("openAIKey", ""),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
        "jinaAIKey": os.environ.get("jinaAIKey", ""),
        "googleSearchApiKey": os.environ.get("googleSearchApiKey", ""),
        "googleSearchCxId": os.environ.get("googleSearchCxId", ""),
        "scrapingant": os.environ.get("scrapingant", ""),
        "zenrows": os.environ.get("zenrows", ""),
        "brightdataProxy": os.environ.get("brightdataProxy", ""),
        "brightdataUrl": os.environ.get("brightdataUrl", ""),
        "BRIGHTDATA_SERP_API_PROXY": os.environ.get("BRIGHTDATA_SERP_API_PROXY", ""),
    }


def test_websearch_agent(query: str, keys: Dict, detail_level: int = 1) -> Dict:
    """Test WebSearchWithAgent with detailed timing breakdown."""
    from agents.search_and_information_agents import WebSearchWithAgent
    from common import CHEAP_LONG_CONTEXT_LLM
    
    results = {
        "agent": "WebSearchWithAgent",
        "query": query,
        "detail_level": detail_level,
        "timings": {},
        "sub_timings": {},
        "success": False,
        "error": None,
        "output_length": 0
    }
    
    print(f"\n{'='*60}")
    print(f"Testing WebSearchWithAgent")
    print(f"{'='*60}")
    
    total_start = time.time()
    
    try:
        # Initialize agent
        init_start = time.time()
        agent = WebSearchWithAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], detail_level, timeout=60)
        results["timings"]["initialization"] = time.time() - init_start
        print(f"  Initialization: {results['timings']['initialization']:.2f}s")
        
        # Run agent
        call_start = time.time()
        full_output = ""
        phase_timings = {
            "query_generation": 0,
            "web_search_execution": 0,
            "combiner_llm": 0
        }
        
        phase = "query_generation"
        phase_start = time.time()
        
        for chunk in agent(query):
            text = chunk.get("text", "")
            status = chunk.get("status", "")
            full_output += text
            
            # Detect phase changes based on status
            if "search queries" in status.lower() and phase == "query_generation":
                phase_timings["query_generation"] = time.time() - phase_start
                print(f"  Query Generation: {phase_timings['query_generation']:.2f}s")
                phase = "web_search_execution"
                phase_start = time.time()
            elif "web search results" in status.lower() and phase == "web_search_execution":
                phase_timings["web_search_execution"] = time.time() - phase_start
                print(f"  Web Search Execution: {phase_timings['web_search_execution']:.2f}s")
                phase = "combiner_llm"
                phase_start = time.time()
        
        # Final phase
        if phase == "combiner_llm":
            phase_timings["combiner_llm"] = time.time() - phase_start
            print(f"  Combiner LLM: {phase_timings['combiner_llm']:.2f}s")
        
        results["timings"]["agent_call"] = time.time() - call_start
        results["sub_timings"] = phase_timings
        results["output_length"] = len(full_output)
        results["success"] = True
        
    except Exception as e:
        results["error"] = str(e)
        print(f"  ERROR: {e}")
        traceback.print_exc()
    
    results["timings"]["total"] = time.time() - total_start
    print(f"\n  TOTAL: {results['timings']['total']:.2f}s")
    print(f"  Output: {results['output_length']} chars")
    
    return results


def test_perplexity_agent(query: str, keys: Dict, detail_level: int = 1, num_queries: int = 3) -> Dict:
    """Test PerplexitySearchAgent with detailed timing breakdown."""
    from agents.search_and_information_agents import PerplexitySearchAgent
    from common import CHEAP_LONG_CONTEXT_LLM
    
    results = {
        "agent": "PerplexitySearchAgent",
        "query": query,
        "detail_level": detail_level,
        "num_queries": num_queries,
        "timings": {},
        "sub_timings": {},
        "success": False,
        "error": None,
        "output_length": 0
    }
    
    print(f"\n{'='*60}")
    print(f"Testing PerplexitySearchAgent")
    print(f"{'='*60}")
    
    total_start = time.time()
    
    try:
        # Initialize agent
        init_start = time.time()
        agent = PerplexitySearchAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], detail_level, timeout=60, num_queries=num_queries)
        results["timings"]["initialization"] = time.time() - init_start
        results["perplexity_models"] = agent.perplexity_models
        print(f"  Initialization: {results['timings']['initialization']:.2f}s")
        print(f"  Models: {agent.perplexity_models}")
        
        # Run agent
        call_start = time.time()
        full_output = ""
        phase_timings = {
            "query_generation": 0,
            "perplexity_api_calls": 0,
            "combiner_llm": 0
        }
        
        phase = "query_generation"
        phase_start = time.time()
        
        for chunk in agent(query):
            text = chunk.get("text", "")
            status = chunk.get("status", "")
            full_output += text
            
            # Detect phase changes based on status
            if "search queries" in status.lower() and phase == "query_generation":
                phase_timings["query_generation"] = time.time() - phase_start
                print(f"  Query Generation: {phase_timings['query_generation']:.2f}s")
                phase = "perplexity_api_calls"
                phase_start = time.time()
            elif "web search results" in status.lower() and phase == "perplexity_api_calls":
                phase_timings["perplexity_api_calls"] = time.time() - phase_start
                print(f"  Perplexity API Calls: {phase_timings['perplexity_api_calls']:.2f}s")
                phase = "combiner_llm"
                phase_start = time.time()
        
        # Final phase
        if phase == "combiner_llm":
            phase_timings["combiner_llm"] = time.time() - phase_start
            print(f"  Combiner LLM: {phase_timings['combiner_llm']:.2f}s")
        
        results["timings"]["agent_call"] = time.time() - call_start
        results["sub_timings"] = phase_timings
        results["output_length"] = len(full_output)
        results["success"] = True
        
    except Exception as e:
        results["error"] = str(e)
        print(f"  ERROR: {e}")
        traceback.print_exc()
    
    results["timings"]["total"] = time.time() - total_start
    print(f"\n  TOTAL: {results['timings']['total']:.2f}s")
    print(f"  Output: {results['output_length']} chars")
    
    return results


def test_jina_agent(query: str, keys: Dict, detail_level: int = 1, num_queries: int = 3) -> Dict:
    """Test JinaSearchAgent with detailed timing breakdown."""
    from agents.search_and_information_agents import JinaSearchAgent
    from common import CHEAP_LONG_CONTEXT_LLM
    
    results = {
        "agent": "JinaSearchAgent",
        "query": query,
        "detail_level": detail_level,
        "num_queries": num_queries,
        "timings": {},
        "sub_timings": {},
        "success": False,
        "error": None,
        "output_length": 0
    }
    
    print(f"\n{'='*60}")
    print(f"Testing JinaSearchAgent")
    print(f"{'='*60}")
    
    total_start = time.time()
    
    try:
        # Initialize agent
        init_start = time.time()
        agent = JinaSearchAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], detail_level, timeout=60, num_queries=num_queries)
        results["timings"]["initialization"] = time.time() - init_start
        print(f"  Initialization: {results['timings']['initialization']:.2f}s")
        print(f"  Num results per query: {agent.num_results}")
        
        # Run agent
        call_start = time.time()
        full_output = ""
        phase_timings = {
            "query_generation": 0,
            "jina_api_calls": 0,
            "combiner_llm": 0
        }
        
        phase = "query_generation"
        phase_start = time.time()
        
        for chunk in agent(query):
            text = chunk.get("text", "")
            status = chunk.get("status", "")
            full_output += text
            
            # Detect phase changes based on status
            if "search queries" in status.lower() and phase == "query_generation":
                phase_timings["query_generation"] = time.time() - phase_start
                print(f"  Query Generation: {phase_timings['query_generation']:.2f}s")
                phase = "jina_api_calls"
                phase_start = time.time()
            elif "web search results" in status.lower() and phase == "jina_api_calls":
                phase_timings["jina_api_calls"] = time.time() - phase_start
                print(f"  Jina API Calls: {phase_timings['jina_api_calls']:.2f}s")
                phase = "combiner_llm"
                phase_start = time.time()
        
        # Final phase
        if phase == "combiner_llm":
            phase_timings["combiner_llm"] = time.time() - phase_start
            print(f"  Combiner LLM: {phase_timings['combiner_llm']:.2f}s")
        
        results["timings"]["agent_call"] = time.time() - call_start
        results["sub_timings"] = phase_timings
        results["output_length"] = len(full_output)
        results["success"] = True
        
    except Exception as e:
        results["error"] = str(e)
        print(f"  ERROR: {e}")
        traceback.print_exc()
    
    results["timings"]["total"] = time.time() - total_start
    print(f"\n  TOTAL: {results['timings']['total']:.2f}s")
    print(f"  Output: {results['output_length']} chars")
    
    return results


def test_multisource_parallel_fix(query: str, keys: Dict, detail_level: int = 1) -> Dict:
    """Test if the parallel fix in MultiSourceSearchAgent works correctly."""
    from agents.search_and_information_agents import MultiSourceSearchAgent
    from common import CHEAP_LONG_CONTEXT_LLM
    
    results = {
        "agent": "MultiSourceSearchAgent (Parallel Fix Test)",
        "query": query,
        "detail_level": detail_level,
        "timings": {},
        "sub_timings": {},
        "success": False,
        "error": None,
        "output_length": 0
    }
    
    print(f"\n{'='*60}")
    print(f"Testing MultiSourceSearchAgent (Parallel Fix)")
    print(f"{'='*60}")
    
    total_start = time.time()
    
    try:
        # Initialize agent
        init_start = time.time()
        agent = MultiSourceSearchAgent(keys, CHEAP_LONG_CONTEXT_LLM[0], detail_level, timeout=60, num_queries=3)
        results["timings"]["initialization"] = time.time() - init_start
        print(f"  Initialization: {results['timings']['initialization']:.2f}s")
        
        # Run agent and track when each source completes
        call_start = time.time()
        full_output = ""
        source_completion_times = {}
        
        for chunk in agent(query):
            text = chunk.get("text", "")
            status = chunk.get("status", "")
            full_output += text
            
            # Track when each source's results appear
            current_time = time.time() - call_start
            if "Web Search Results" in text and "web_search" not in source_completion_times:
                source_completion_times["web_search"] = current_time
                print(f"  WebSearch results received at: {current_time:.2f}s")
            elif "Perplexity Search Results" in text and "perplexity" not in source_completion_times:
                source_completion_times["perplexity"] = current_time
                print(f"  Perplexity results received at: {current_time:.2f}s")
            elif "Jina Search Results" in text and "jina" not in source_completion_times:
                source_completion_times["jina"] = current_time
                print(f"  Jina results received at: {current_time:.2f}s")
        
        results["timings"]["agent_call"] = time.time() - call_start
        results["sub_timings"] = source_completion_times
        results["output_length"] = len(full_output)
        results["success"] = True
        
        # Analyze if streaming/parallel is working:
        # - If we stream as sources complete, we should see meaningful variance (fast sources appear earlier)
        # - If we wait for all before yielding, times will be near-identical (low variance)
        if len(source_completion_times) >= 2:
            times = list(source_completion_times.values())
            time_variance = max(times) - min(times) if times else 0
            results["parallel_working"] = time_variance > 5
            print(f"\n  Parallel Analysis:")
            print(f"    Earliest completion: {min(times):.2f}s")
            print(f"    Latest completion: {max(times):.2f}s")
            print(f"    Time variance: {time_variance:.2f}s")
            if time_variance > 5:
                print(f"    ✓ Streaming appears to work (sources arrive at different times)")
            else:
                print(f"    ⚠ Low variance suggests results were only yielded after all sources finished")
        
    except Exception as e:
        results["error"] = str(e)
        print(f"  ERROR: {e}")
        traceback.print_exc()
    
    results["timings"]["total"] = time.time() - total_start
    print(f"\n  TOTAL: {results['timings']['total']:.2f}s")
    print(f"  Output: {results['output_length']} chars")
    
    return results


def test_llm_combiner_speed(query: str, keys: Dict) -> Dict:
    """Test LLM combiner speed with different models."""
    from base import CallLLm
    from common import CHEAP_LLM, CHEAP_LONG_CONTEXT_LLM, VERY_CHEAP_LLM
    
    results = {
        "test": "LLM Combiner Speed Comparison",
        "query": query,
        "model_timings": {},
        "success": True
    }
    
    print(f"\n{'='*60}")
    print(f"Testing LLM Combiner Speed with Different Models")
    print(f"{'='*60}")
    
    test_prompt = f"""
Summarize the following query and provide a brief response:
Query: {query}

Provide a 2-3 sentence summary.
"""
    
    models_to_test = [
        ("VERY_CHEAP_LLM", VERY_CHEAP_LLM[0] if VERY_CHEAP_LLM else None),
        ("CHEAP_LLM", CHEAP_LLM[0] if CHEAP_LLM else None),
        ("CHEAP_LONG_CONTEXT_LLM", CHEAP_LONG_CONTEXT_LLM[0] if CHEAP_LONG_CONTEXT_LLM else None),
    ]
    
    for model_name, model in models_to_test:
        if model is None:
            continue
            
        print(f"\n  Testing {model_name} ({model})...")
        try:
            llm = CallLLm(keys, model_name=model)
            
            start_time = time.time()
            response = llm(test_prompt, temperature=0.7, stream=False, max_tokens=200)
            elapsed = time.time() - start_time
            
            results["model_timings"][model_name] = {
                "model": model,
                "time": elapsed,
                "response_length": len(response) if response else 0
            }
            print(f"    Time: {elapsed:.2f}s, Response: {len(response) if response else 0} chars")
            
        except Exception as e:
            results["model_timings"][model_name] = {
                "model": model,
                "error": str(e)
            }
            print(f"    ERROR: {e}")
    
    # Find fastest model
    valid_timings = {k: v for k, v in results["model_timings"].items() if "time" in v}
    if valid_timings:
        fastest = min(valid_timings.items(), key=lambda x: x[1]["time"])
        results["fastest_model"] = fastest[0]
        print(f"\n  Fastest model: {fastest[0]} ({fastest[1]['time']:.2f}s)")
    
    return results


def run_all_tests(query: str, detail_level: int = 1, clear_cache_first: bool = True) -> Dict:
    """Run all individual agent tests."""
    
    if clear_cache_first:
        print("\n" + "="*80)
        print("CLEARING CACHE FOR FRESH TEST RUN")
        print("="*80)
        clear_cache(verbose=True)
    
    keys = get_api_keys()
    all_results = {
        "query": query,
        "detail_level": detail_level,
        "timestamp": datetime.now().isoformat(),
        "tests": []
    }
    
    # Test individual agents
    print("\n" + "="*80)
    print("INDIVIDUAL AGENT TESTS")
    print("="*80)
    
    # WebSearchWithAgent
    websearch_results = test_websearch_agent(query, keys, detail_level)
    all_results["tests"].append(websearch_results)
    
    # PerplexitySearchAgent  
    perplexity_results = test_perplexity_agent(query, keys, detail_level, num_queries=3)
    all_results["tests"].append(perplexity_results)
    
    # JinaSearchAgent
    jina_results = test_jina_agent(query, keys, detail_level, num_queries=3)
    all_results["tests"].append(jina_results)
    
    # Test LLM combiner speeds
    llm_results = test_llm_combiner_speed(query, keys)
    all_results["tests"].append(llm_results)
    
    # Test MultiSourceSearchAgent parallel fix
    multisource_results = test_multisource_parallel_fix(query, keys, detail_level)
    all_results["tests"].append(multisource_results)
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    total_times = {}
    for test in all_results["tests"]:
        if "agent" in test and "timings" in test and "total" in test["timings"]:
            agent = test["agent"]
            total_times[agent] = test["timings"]["total"]
            status = "✓" if test.get("success", False) else "✗"
            print(f"  {status} {agent}: {total_times[agent]:.2f}s")
    
    # Identify slowest components
    print("\n  Slowest Components:")
    for test in all_results["tests"]:
        if "sub_timings" in test and test["sub_timings"]:
            agent = test.get("agent", test.get("test", "Unknown"))
            slowest = max(test["sub_timings"].items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0)
            if isinstance(slowest[1], (int, float)):
                print(f"    {agent}: {slowest[0]} ({slowest[1]:.2f}s)")
    
    # Save results
    output_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "individual_agent_timing_report.json"
    )
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved to: {output_file}")
    
    return all_results


def main():
    parser = argparse.ArgumentParser(description="Test individual search agents for performance analysis")
    parser.add_argument("query", type=str, help="Search query to test")
    parser.add_argument("--agent", type=str, default="all", 
                       choices=["all", "websearch", "perplexity", "jina", "multisource", "llm"],
                       help="Which agent to test")
    parser.add_argument("--detail-level", type=int, default=1, help="Detail level (1-4)")
    parser.add_argument("--num-queries", type=int, default=3, help="Number of queries for multi-query agents")
    parser.add_argument("--no-clear-cache", action="store_true", help="Skip clearing cache")
    
    args = parser.parse_args()
    
    if not args.no_clear_cache:
        print("\n" + "="*80)
        print("CLEARING CACHE FOR FRESH TEST RUN")
        print("="*80)
        clear_cache(verbose=True)
    
    keys = get_api_keys()
    
    if args.agent == "all":
        run_all_tests(args.query, args.detail_level, clear_cache_first=False)
    elif args.agent == "websearch":
        test_websearch_agent(args.query, keys, args.detail_level)
    elif args.agent == "perplexity":
        test_perplexity_agent(args.query, keys, args.detail_level, args.num_queries)
    elif args.agent == "jina":
        test_jina_agent(args.query, keys, args.detail_level, args.num_queries)
    elif args.agent == "multisource":
        test_multisource_parallel_fix(args.query, keys, args.detail_level)
    elif args.agent == "llm":
        test_llm_combiner_speed(args.query, keys)


if __name__ == "__main__":
    main()

