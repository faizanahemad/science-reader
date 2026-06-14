#!/usr/bin/env python3
"""
Test harness for timing analysis of /search command via Conversation.reply().

This module tests the web search flow as triggered from the chat interface
when a user uses the /search command or enables web search checkbox.

Usage:
    conda activate science-reader
    python tests/test_reply_search_timing.py "your search query here"
    
    Or with VSCode debugger using the "Debug: Reply Search Timing" configuration.

Components Tested:
    1. Conversation initialization
    2. Web search flag detection and setup
    3. web_search_queue call timing
    4. Perplexity search timing (if enabled)
    5. Search result processing
    6. Link reading and summarization
    7. Final LLM response generation

Author: Auto-generated for performance debugging
"""

import os
import sys
import time
import json
import argparse
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Generator
from dataclasses import dataclass, field, asdict

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
class TimingMilestone:
    """Represents a timing milestone during search execution."""
    name: str
    timestamp: float
    elapsed_from_start: float
    notes: str = ""


@dataclass
class TimingResult:
    """Stores timing result for a single operation."""
    name: str
    duration_seconds: float
    success: bool
    result_summary: str = ""
    error: Optional[str] = None
    milestones: List[TimingMilestone] = field(default_factory=list)


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
        print(f"TIMING REPORT - /search Command via reply()")
        print(f"Query: {self.query}")
        print(f"Timestamp: {self.timestamp}")
        print(f"Total Duration: {self.total_duration_seconds:.2f}s")
        print("="*80)
        
        for r in self.results:
            status = "✓ OK" if r.success else "✗ FAIL"
            print(f"\n{'─'*80}")
            print(f"TEST: {r.name}")
            print(f"Duration: {r.duration_seconds:.2f}s | Status: {status}")
            print(f"Summary: {r.result_summary}")
            if r.error:
                print(f"Error: {r.error}")
            
            if r.milestones:
                print(f"\n{'Milestone':<40} {'Time':<10} {'Elapsed':<10} {'Notes'}")
                print("-"*80)
                for m in r.milestones:
                    elapsed_str = f"+{m.elapsed_from_start:.2f}s"
                    print(f"{m.name:<40} {elapsed_str:<10} {m.notes}")
        
        print("\n" + "="*80)
        print("BOTTLENECK ANALYSIS:")
        print("-"*80)
        
        # Analyze milestone gaps
        for r in self.results:
            if r.milestones and len(r.milestones) > 1:
                print(f"\n{r.name} - Phase Durations:")
                for i in range(1, len(r.milestones)):
                    prev = r.milestones[i-1]
                    curr = r.milestones[i]
                    phase_duration = curr.elapsed_from_start - prev.elapsed_from_start
                    phase_name = f"{prev.name} → {curr.name}"
                    pct = (phase_duration / r.duration_seconds * 100) if r.duration_seconds > 0 else 0
                    print(f"  {phase_name}: {phase_duration:.2f}s ({pct:.1f}%)")
        
        print("="*80 + "\n")
    
    def to_json(self) -> str:
        """Export report as JSON for further analysis."""
        return json.dumps(asdict(self), indent=2)


def create_test_conversation(keys: Dict, conversation_id: str = None):
    """Create a test conversation instance."""
    from Conversation import Conversation
    from base import get_embedding_model
    import tempfile
    
    if conversation_id is None:
        conversation_id = f"test_timing_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    storage = tempfile.mkdtemp()
    
    conversation = Conversation(
        email="test@example.com",
        openai_embed=get_embedding_model(keys),
        storage=storage,
        conversation_id=conversation_id,
        domain="general"
    )
    
    conversation.api_keys = keys
    
    return conversation


def create_search_query(message_text: str, detail_level: int = 1, use_perplexity: bool = False) -> Dict:
    """Create a query dict that simulates the /search command."""
    query = {
        "messageText": message_text,
        "checkboxes": {
            "provide_detailed_answers": str(detail_level),
            "main_model": "anthropic/claude-sonnet-4-20250514",
            "persist_or_not": False,
            "enable_planner": False,
            "perform_web_search": True,  # This enables web search
            "googleScholar": False,
            "use_memory_pad": False,
            "tell_me_more": False,
            "enable_previous_messages": "-1",
            "preamble_options": [],
            "need_diagram": False,
            "agentic_search": False,
            "ppt_answer": False,
        },
        "links": [],
        "search": [],  # Can add specific searches here
        "images": [],
    }
    
    if use_perplexity:
        query["checkboxes"]["field"] = "PerplexitySearch"
    
    return query


def test_web_search_queue_direct(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test web_search_queue directly (bypassing Conversation)."""
    from base import web_search_queue, create_tmp_marker_file, remove_tmp_marker_file
    import uuid
    
    print("\n[1/5] Testing web_search_queue Direct Call...")
    
    marker_name = f"_test_direct_{uuid.uuid4()}"
    create_tmp_marker_file(marker_name)
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    milestones = []
    
    try:
        milestones.append(TimingMilestone("Start", time.time(), 0, "Initiating search"))
        
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
            provide_detailed_answers=detail_level,
            web_search_tmp_marker_name=marker_name
        )
        
        milestones.append(TimingMilestone("Queue Created", time.time(), time.time() - start, "web_search_queue returned"))
        
        part1_future, read_queue = result
        
        # Get first search results
        search_results = None
        for item in part1_future.result():
            if isinstance(item, dict) and "queries" in item:
                search_results = item
                milestones.append(TimingMilestone("Queries Generated", time.time(), time.time() - start, 
                                                  f"{len(item.get('queries', []))} queries"))
                break
        
        # Get next item (actual results)
        try:
            end_result = next(part1_future.result())
            if end_result and end_result.get("type") == "end":
                milestones.append(TimingMilestone("SERP Complete", time.time(), time.time() - start,
                                                  f"{len(end_result.get('full_results', []))} results"))
        except StopIteration:
            pass
        
        # Get some read results
        read_count = 0
        read_timeout = time.time() + 30
        while time.time() < read_timeout and read_count < 3:
            if not read_queue.empty():
                item = read_queue.get()
                if item == "STOP":
                    break
                read_count += 1
                if read_count == 1:
                    milestones.append(TimingMilestone("First Link Read", time.time(), time.time() - start, ""))
            else:
                time.sleep(0.2)
        
        milestones.append(TimingMilestone(f"Links Read ({read_count})", time.time(), time.time() - start, ""))
        
        success = True
        result_summary = f"Queries: {len(search_results.get('queries', []) if search_results else [])}, Read: {read_count} links"
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
        milestones.append(TimingMilestone("Error", time.time(), time.time() - start, str(e)[:50]))
    finally:
        remove_tmp_marker_file(marker_name)
    
    duration = time.time() - start
    print(f"   Duration: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="web_search_queue Direct",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        milestones=milestones
    )


def test_conversation_reply_search(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test search via Conversation.reply() method."""
    
    print("\n[2/5] Testing Conversation.reply() with Web Search...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    milestones = []
    
    try:
        milestones.append(TimingMilestone("Start", time.time(), 0, "Creating conversation"))
        
        conversation = create_test_conversation(keys)
        
        milestones.append(TimingMilestone("Conversation Created", time.time(), time.time() - start, ""))
        
        # Create search query
        search_query = create_search_query(query, detail_level)
        
        milestones.append(TimingMilestone("Query Prepared", time.time(), time.time() - start, ""))
        
        # Execute reply with streaming
        answer = ""
        status_log = []
        
        for chunk in conversation.reply(search_query):
            status = chunk.get("status", "")
            text = chunk.get("text", "")
            answer += text
            
            # Track key milestones
            if "performing web search" in status.lower() and not any("Web Search Start" in m.name for m in milestones):
                milestones.append(TimingMilestone("Web Search Start", time.time(), time.time() - start, ""))
            
            if "displaying web search queries" in status.lower() and not any("Queries Displayed" in m.name for m in milestones):
                milestones.append(TimingMilestone("Queries Displayed", time.time(), time.time() - start, ""))
            
            if "reading" in status.lower() and "link" in status.lower() and not any("Link Reading" in m.name for m in milestones):
                milestones.append(TimingMilestone("Link Reading Start", time.time(), time.time() - start, ""))
            
            if "web search finally done" in status.lower():
                milestones.append(TimingMilestone("Web Search Done", time.time(), time.time() - start, ""))
            
            if "answering in progress" in status.lower() and not any("LLM Response" in m.name for m in milestones):
                milestones.append(TimingMilestone("LLM Response Start", time.time(), time.time() - start, ""))
            
            if len(status_log) < 50:  # Limit status logging
                status_log.append(status)
        
        milestones.append(TimingMilestone("Complete", time.time(), time.time() - start, f"{len(answer)} chars"))
        
        success = True
        result_summary = f"{len(answer)} chars, {len(milestones)} milestones"
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
        milestones.append(TimingMilestone("Error", time.time(), time.time() - start, str(e)[:50]))
    
    duration = time.time() - start
    print(f"   Duration: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="Conversation.reply() with Web Search",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        milestones=milestones
    )


def test_perplexity_via_reply(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test Perplexity search via Conversation.reply() with field="PerplexitySearch"."""
    
    print("\n[3/5] Testing Conversation.reply() with PerplexitySearch Agent...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    milestones = []
    
    try:
        milestones.append(TimingMilestone("Start", time.time(), 0, "Creating conversation"))
        
        conversation = create_test_conversation(keys)
        
        # Create query with PerplexitySearch field
        search_query = create_search_query(query, detail_level, use_perplexity=True)
        search_query["checkboxes"]["field"] = "PerplexitySearch"
        search_query["checkboxes"]["perform_web_search"] = False  # Use agent instead
        
        milestones.append(TimingMilestone("Query Prepared", time.time(), time.time() - start, "PerplexitySearch"))
        
        # Execute reply with streaming
        answer = ""
        
        for chunk in conversation.reply(search_query):
            status = chunk.get("status", "")
            text = chunk.get("text", "")
            answer += text
            
            if "perplexity" in status.lower() and not any("Perplexity" in m.name for m in milestones):
                milestones.append(TimingMilestone("Perplexity Start", time.time(), time.time() - start, ""))
            
            if "completed" in status.lower() and not any("Complete" in m.name for m in milestones):
                milestones.append(TimingMilestone("Agent Complete", time.time(), time.time() - start, ""))
        
        milestones.append(TimingMilestone("Full Complete", time.time(), time.time() - start, f"{len(answer)} chars"))
        
        success = True
        result_summary = f"{len(answer)} chars"
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
        milestones.append(TimingMilestone("Error", time.time(), time.time() - start, str(e)[:50]))
    
    duration = time.time() - start
    print(f"   Duration: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="Conversation.reply() with PerplexitySearch",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        milestones=milestones
    )


def test_multi_source_via_reply(keys: Dict, query: str, detail_level: int = 1) -> TimingResult:
    """Test MultiSourceSearch via Conversation.reply()."""
    
    print("\n[4/5] Testing Conversation.reply() with MultiSourceSearch Agent...")
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    milestones = []
    
    try:
        milestones.append(TimingMilestone("Start", time.time(), 0, "Creating conversation"))
        
        conversation = create_test_conversation(keys)
        
        # Create query with MultiSourceSearch field
        search_query = create_search_query(query, detail_level)
        search_query["checkboxes"]["field"] = "MultiSourceSearch"
        search_query["checkboxes"]["perform_web_search"] = False  # Use agent instead
        
        milestones.append(TimingMilestone("Query Prepared", time.time(), time.time() - start, "MultiSourceSearch"))
        
        # Execute reply with streaming
        answer = ""
        
        for chunk in conversation.reply(search_query):
            status = chunk.get("status", "")
            text = chunk.get("text", "")
            answer += text
            
            if "multisource" in status.lower() and not any("MultiSource" in m.name for m in milestones):
                milestones.append(TimingMilestone("MultiSource Start", time.time(), time.time() - start, ""))
            
            if "web search results" in text.lower() and not any("WebSearch Done" in m.name for m in milestones):
                milestones.append(TimingMilestone("WebSearch Done", time.time(), time.time() - start, ""))
            
            if "perplexity search results" in text.lower() and not any("Perplexity Done" in m.name for m in milestones):
                milestones.append(TimingMilestone("Perplexity Done", time.time(), time.time() - start, ""))
            
            if "jina search results" in text.lower() and not any("Jina Done" in m.name for m in milestones):
                milestones.append(TimingMilestone("Jina Done", time.time(), time.time() - start, ""))
        
        milestones.append(TimingMilestone("Complete", time.time(), time.time() - start, f"{len(answer)} chars"))
        
        success = True
        result_summary = f"{len(answer)} chars"
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
        milestones.append(TimingMilestone("Error", time.time(), time.time() - start, str(e)[:50]))
    
    duration = time.time() - start
    print(f"   Duration: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="Conversation.reply() with MultiSourceSearch",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        milestones=milestones
    )


def test_search_without_link_reading(keys: Dict, query: str) -> TimingResult:
    """Test SERP-only search without link reading to isolate SERP timing."""
    from base import web_search_part1_real, create_tmp_marker_file, remove_tmp_marker_file
    import uuid
    
    print("\n[5/5] Testing SERP-Only (No Link Reading)...")
    
    marker_name = f"_test_serp_{uuid.uuid4()}"
    create_tmp_marker_file(marker_name)
    
    start = time.time()
    success = False
    error = None
    result_summary = ""
    milestones = []
    
    try:
        milestones.append(TimingMilestone("Start", time.time(), 0, ""))
        
        # Call web_search_part1_real directly
        results = []
        queries = []
        
        for item in web_search_part1_real(
            context=query,
            doc_source="test",
            doc_context="",
            api_keys=keys,
            year_month=datetime.now().strftime("%Y-%m"),
            previous_answer=None,
            previous_search_results=None,
            extra_queries=None,
            gscholar=False,
            provide_detailed_answers=1,
            start_time=time.time(),
            web_search_tmp_marker_name=marker_name
        ):
            if item.get("type") == "query":
                queries = item.get("query", [])
                milestones.append(TimingMilestone("Queries Generated", time.time(), time.time() - start, 
                                                  f"{len(queries)} queries"))
            elif item.get("type") == "result":
                results.append(item)
                if len(results) == 1:
                    milestones.append(TimingMilestone("First Result", time.time(), time.time() - start, ""))
            elif item.get("type") == "end":
                milestones.append(TimingMilestone("SERP Complete", time.time(), time.time() - start,
                                                  f"{len(results)} results"))
                break
        
        success = True
        result_summary = f"{len(queries)} queries, {len(results)} results"
        
    except Exception as e:
        error = str(e)
        traceback.print_exc()
    finally:
        remove_tmp_marker_file(marker_name)
    
    duration = time.time() - start
    print(f"   Duration: {duration:.2f}s - {result_summary}")
    
    return TimingResult(
        name="SERP-Only (No Link Reading)",
        duration_seconds=duration,
        success=success,
        result_summary=result_summary,
        error=error,
        milestones=milestones
    )


def run_timing_analysis(query: str, detail_level: int = 1, skip_agents: bool = False):
    """Run complete timing analysis for /search command."""
    print("\n" + "="*80)
    print("/SEARCH COMMAND TIMING ANALYSIS")
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
        # Test web_search_queue directly
        result = test_web_search_queue_direct(keys, query, detail_level)
        report.add_result(result)
        
        # Test SERP-only (no link reading)
        result = test_search_without_link_reading(keys, query)
        report.add_result(result)
        
        if not skip_agents:
            # Test via Conversation.reply()
            result = test_conversation_reply_search(keys, query, detail_level)
            report.add_result(result)
            
            # Test Perplexity via reply
            result = test_perplexity_via_reply(keys, query, detail_level)
            report.add_result(result)
            
            # Test MultiSource via reply
            result = test_multi_source_via_reply(keys, query, detail_level)
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
    report_path = os.path.join(os.path.dirname(__file__), "timing_report_reply_search.json")
    with open(report_path, "w") as f:
        f.write(report.to_json())
    print(f"JSON report saved to: {report_path}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for timing analysis of /search command via Conversation.reply()"
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
        "--skip-agents",
        action="store_true",
        help="Skip agent-based tests (PerplexitySearch, MultiSourceSearch)"
    )
    
    args = parser.parse_args()
    run_timing_analysis(args.query, args.detail_level, args.skip_agents)


if __name__ == "__main__":
    main()

