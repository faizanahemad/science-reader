#!/usr/bin/env python3
"""
Benchmark script for code_common/call_llm.py public functions.

Measures execution time for:
- call_llm (text only, with image, streaming, messages mode)
- get_query_embedding, get_document_embedding, get_document_embeddings
- getKeywordsFromText, getKeywordsFromImage, getKeywordsFromImageText
- getImageQueryEmbedding, getImageDocumentEmbedding
- getJointQueryEmbedding (separate + vlm modes)
- getJointDocumentEmbedding (separate + vlm modes)

Usage:
    python benchmark_call_llm.py

Environment:
    OPENROUTER_API_KEY must be set.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Ensure imports work
def _ensure_import_paths() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code_common_dir = os.path.join(root, "code_common")
    if root not in sys.path:
        sys.path.insert(0, root)
    if code_common_dir not in sys.path:
        sys.path.insert(0, code_common_dir)

_ensure_import_paths()

from code_common.call_llm import (
    call_llm,
    get_query_embedding,
    get_document_embedding,
    get_document_embeddings,
    getKeywordsFromText,
    getKeywordsFromImage,
    getKeywordsFromImageText,
    getImageQueryEmbedding,
    getImageDocumentEmbedding,
    getJointQueryEmbedding,
    getJointDocumentEmbedding,
)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    name: str
    duration_seconds: float
    success: bool
    error: Optional[str] = None
    notes: str = ""


def _collect_stream(stream, max_seconds: float = 60.0) -> str:
    """Collect a streaming response into a string."""
    start = time.time()
    parts = []
    for chunk in stream:
        if isinstance(chunk, str):
            parts.append(chunk)
        if time.time() - start > max_seconds:
            break
    return "".join(parts)


def benchmark_function(
    name: str,
    fn: Callable[[], Any],
    notes: str = "",
) -> BenchmarkResult:
    """Run a function and measure its execution time."""
    print(f"  Running: {name}...", end=" ", flush=True)
    start = time.time()
    try:
        result = fn()
        duration = time.time() - start
        # Handle streaming results
        if hasattr(result, "__iter__") and not isinstance(result, (str, list, dict)):
            # It's a generator/stream - collect it
            stream_start = time.time()
            collected = _collect_stream(result)
            duration = time.time() - start  # Total including collection
        print(f"✓ ({duration:.2f}s)")
        return BenchmarkResult(name=name, duration_seconds=duration, success=True, notes=notes)
    except Exception as e:
        duration = time.time() - start
        print(f"✗ ({duration:.2f}s) - {type(e).__name__}: {e}")
        return BenchmarkResult(name=name, duration_seconds=duration, success=False, error=str(e), notes=notes)


def run_benchmarks(keys: Dict[str, str], image_path: str) -> List[BenchmarkResult]:
    """Run all benchmarks and return results."""
    results: List[BenchmarkResult] = []
    
    model = "openai/gpt-4o-mini"
    vlm_model = "openai/gpt-4o-mini"
    
    print("\n" + "="*70)
    print("BENCHMARKING call_llm.py PUBLIC FUNCTIONS")
    print("="*70)
    print(f"Model: {model}")
    print(f"VLM Model: {vlm_model}")
    print(f"Image: {image_path}")
    print("="*70 + "\n")
    
    # -------------------------------------------------------------------------
    # 1. Text Embeddings
    # -------------------------------------------------------------------------
    print("[1/5] TEXT EMBEDDINGS")
    print("-" * 40)
    
    results.append(benchmark_function(
        "get_query_embedding",
        lambda: get_query_embedding("running shoes for marathon training", keys),
        notes="Single text → 1D vector"
    ))
    
    results.append(benchmark_function(
        "get_document_embedding",
        lambda: get_document_embedding("Nike Air Zoom Pegasus running shoes with responsive cushioning.", keys),
        notes="Single text → 1D vector"
    ))
    
    results.append(benchmark_function(
        "get_document_embeddings (3 docs)",
        lambda: get_document_embeddings([
            "Document about cats and dogs.",
            "Document about physics and math.",
            "Document about software testing.",
        ], keys),
        notes="Batch of 3 texts → 2D array"
    ))
    
    # -------------------------------------------------------------------------
    # 2. LLM Calls
    # -------------------------------------------------------------------------
    print("\n[2/5] LLM CALLS (call_llm)")
    print("-" * 40)
    
    results.append(benchmark_function(
        "call_llm (text only, non-stream)",
        lambda: call_llm(
            keys=keys,
            model_name=model,
            text="What is 2+2? Reply with just the number.",
            temperature=0.0,
            stream=False,
        ),
        notes="Simple text prompt"
    ))
    
    results.append(benchmark_function(
        "call_llm (text only, stream)",
        lambda: call_llm(
            keys=keys,
            model_name=model,
            text="Count from 1 to 5.",
            temperature=0.0,
            stream=True,
        ),
        notes="Streaming response"
    ))
    
    results.append(benchmark_function(
        "call_llm (with image, non-stream)",
        lambda: call_llm(
            keys=keys,
            model_name=vlm_model,
            text="Describe this image in one sentence.",
            images=[image_path],
            temperature=0.0,
            stream=False,
        ),
        notes="Image + text prompt"
    ))
    
    results.append(benchmark_function(
        "call_llm (messages mode, text)",
        lambda: call_llm(
            keys=keys,
            model_name=model,
            messages=[
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "And 3+3?"},
            ],
            temperature=0.0,
            stream=False,
        ),
        notes="Multi-turn conversation"
    ))
    
    results.append(benchmark_function(
        "call_llm (messages mode, with image)",
        lambda: call_llm(
            keys=keys,
            model_name=vlm_model,
            messages=[
                {"role": "system", "content": "Be brief."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": image_path}},
                    ],
                },
            ],
            temperature=0.0,
            stream=False,
        ),
        notes="Messages with image_url"
    ))
    
    # -------------------------------------------------------------------------
    # 3. Keyword Extraction
    # -------------------------------------------------------------------------
    print("\n[3/5] KEYWORD EXTRACTION")
    print("-" * 40)
    
    results.append(benchmark_function(
        "getKeywordsFromText",
        lambda: getKeywordsFromText(
            "Nike Air Zoom Pegasus running shoes for marathon training in New York City.",
            keys,
            llm_model=model,
            max_keywords=15,
        ),
        notes="Text → keyword list"
    ))
    
    results.append(benchmark_function(
        "getKeywordsFromImage",
        lambda: getKeywordsFromImage(
            image_path,
            keys,
            vlm_model=vlm_model,
            max_keywords=15,
        ),
        notes="Image → keyword list"
    ))
    
    results.append(benchmark_function(
        "getKeywordsFromImageText",
        lambda: getKeywordsFromImageText(
            "What brand is shown?",
            image_path,
            keys,
            vlm_model=vlm_model,
            max_keywords=15,
        ),
        notes="Image + text → keyword list"
    ))
    
    # -------------------------------------------------------------------------
    # 4. Image Embeddings
    # -------------------------------------------------------------------------
    print("\n[4/5] IMAGE EMBEDDINGS (VLM → text → embed)")
    print("-" * 40)
    
    results.append(benchmark_function(
        "getImageQueryEmbedding",
        lambda: getImageQueryEmbedding(
            image_path,
            keys,
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="Image → VLM description → query embedding"
    ))
    
    results.append(benchmark_function(
        "getImageDocumentEmbedding",
        lambda: getImageDocumentEmbedding(
            image_path,
            keys,
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="Image → VLM description → doc embedding"
    ))
    
    # -------------------------------------------------------------------------
    # 5. Joint Embeddings
    # -------------------------------------------------------------------------
    print("\n[5/5] JOINT EMBEDDINGS (text + image)")
    print("-" * 40)
    
    results.append(benchmark_function(
        "getJointQueryEmbedding (separate)",
        lambda: getJointQueryEmbedding(
            "running shoes",
            image_path,
            keys,
            mode="separate",
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="Embed text + embed image separately, combine"
    ))
    
    results.append(benchmark_function(
        "getJointQueryEmbedding (vlm)",
        lambda: getJointQueryEmbedding(
            "running shoes",
            image_path,
            keys,
            mode="vlm",
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="VLM combines text+image, then embed"
    ))
    
    results.append(benchmark_function(
        "getJointDocumentEmbedding (separate)",
        lambda: getJointDocumentEmbedding(
            "Product listing for athletic footwear.",
            image_path,
            keys,
            mode="separate",
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="Embed text + embed image separately, combine"
    ))
    
    results.append(benchmark_function(
        "getJointDocumentEmbedding (vlm)",
        lambda: getJointDocumentEmbedding(
            "Product listing for athletic footwear.",
            image_path,
            keys,
            mode="vlm",
            vlm_model=vlm_model,
            use_keywords=True,
            max_keywords=15,
        ),
        notes="VLM combines text+image, then embed"
    ))
    
    return results


def print_results_table(results: List[BenchmarkResult]) -> None:
    """Print results as a formatted table."""
    print("\n" + "="*100)
    print("BENCHMARK RESULTS")
    print("="*100)
    
    # Calculate column widths
    name_width = max(len(r.name) for r in results) + 2
    time_width = 12
    status_width = 8
    notes_width = 45
    
    # Header
    header = f"{'Function':<{name_width}} {'Time (s)':>{time_width}} {'Status':<{status_width}} {'Notes':<{notes_width}}"
    print(header)
    print("-" * len(header))
    
    # Rows
    total_time = 0.0
    successful = 0
    for r in results:
        status = "✓ OK" if r.success else "✗ FAIL"
        time_str = f"{r.duration_seconds:.2f}"
        notes = r.notes[:notes_width-3] + "..." if len(r.notes) > notes_width else r.notes
        print(f"{r.name:<{name_width}} {time_str:>{time_width}} {status:<{status_width}} {notes:<{notes_width}}")
        total_time += r.duration_seconds
        if r.success:
            successful += 1
    
    # Summary
    print("-" * len(header))
    print(f"{'TOTAL':<{name_width}} {total_time:>{time_width}.2f} {successful}/{len(results)} OK")
    print("="*100)
    
    # Markdown table for easy copy
    print("\n### Benchmark Results (Markdown Table)\n")
    print("| Function | Time (s) | Status | Notes |")
    print("|----------|----------|--------|-------|")
    for r in results:
        status = "✓" if r.success else "✗"
        print(f"| {r.name} | {r.duration_seconds:.2f} | {status} | {r.notes} |")
    print(f"| **TOTAL** | **{total_time:.2f}** | **{successful}/{len(results)}** | |")


def main() -> int:
    """Main entry point."""
    # Get API key from environment
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY environment variable not set.")
        print("Usage: export OPENROUTER_API_KEY='sk-or-...' && python benchmark_call_llm.py")
        return 1
    
    keys = {"OPENROUTER_API_KEY": api_key}
    
    # Find test image
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(script_dir, "test_image.jpg")
    if not os.path.exists(image_path):
        print(f"ERROR: Test image not found at {image_path}")
        print("Please place a test_image.jpg in the code_common/ directory.")
        return 1
    
    # Run benchmarks
    results = run_benchmarks(keys, image_path)
    
    # Print results table
    print_results_table(results)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

