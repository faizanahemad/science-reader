"""
Test harness package for timing analysis of web search components.

This package provides granular timing measurements for:
- base.py web search functions
- MultiSourceSearchAgent and component agents
- /search command via Conversation.reply()
- Granular bottleneck analysis for specific components

Usage:
    conda activate science-reader
    
    # Test base.py components
    python -m tests.test_search_timing_base "your query"
    
    # Test MultiSourceSearchAgent
    python -m tests.test_multi_source_search_timing "your query"
    
    # Test /search command via reply()
    python -m tests.test_reply_search_timing "your query"
    
    # Granular bottleneck analysis
    python -m tests.test_granular_bottlenecks "your query"

VSCode Debug Configurations:
    - Debug: Search Timing Base
    - Debug: MultiSource Search Timing  
    - Debug: Reply Search Timing
    - Debug: Granular Bottlenecks

See PERFORMANCE_BOTTLENECK_ANALYSIS.md for identified bottlenecks and recommendations.
"""

from .test_search_timing_base import run_timing_analysis as run_base_timing
from .test_multi_source_search_timing import run_timing_analysis as run_multi_source_timing
from .test_reply_search_timing import run_timing_analysis as run_reply_timing


def run_all_timing_tests(query: str = "What are the latest advances in large language models?"):
    """Run all timing tests with the given query."""
    print("\n" + "="*80)
    print("RUNNING ALL TIMING TESTS")
    print("="*80)
    
    results = {}
    
    print("\n--- BASE TIMING TESTS ---")
    results["base"] = run_base_timing(query, skip_full_pipeline=True)
    
    print("\n--- MULTI-SOURCE AGENT TIMING TESTS ---")
    results["multi_source"] = run_multi_source_timing(query, detail_level=1, test_individual=False)
    
    print("\n--- REPLY SEARCH TIMING TESTS ---")
    results["reply"] = run_reply_timing(query, detail_level=1, skip_agents=True)
    
    return results

