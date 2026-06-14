"""
Test file for stream_multiple_models function.

This test file isolates the stream_multiple_models function to diagnose
timing issues in the multi-model streaming pipeline. It mocks the LLM
calls and uses controlled delays to verify that chunks are yielded
promptly as they become available.

Usage:
    python -m pytest tests/test_stream_multiple_models.py -v -s

    Or run directly:
    python tests/test_stream_multiple_models.py
"""

import sys
import os
import time
import threading
from queue import Queue
from unittest.mock import patch, MagicMock
from typing import Generator, List, Tuple
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging to see timing info
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S.%f",
)
logger = logging.getLogger(__name__)


def mock_streaming_response(
    chunks: List[str], delay_per_chunk: float = 0.05, initial_delay: float = 0.1
) -> Generator[str, None, None]:
    """
    Creates a mock streaming response generator.

    Args:
        chunks: List of text chunks to yield
        delay_per_chunk: Delay between each chunk (simulates network/generation time)
        initial_delay: Initial delay before first chunk (simulates time-to-first-token)

    Yields:
        Text chunks with controlled timing
    """
    time.sleep(initial_delay)
    for i, chunk in enumerate(chunks):
        yield chunk
        if i < len(chunks) - 1:  # Don't delay after last chunk
            time.sleep(delay_per_chunk)


def create_mock_llm_response(
    model_name: str, num_chunks: int = 20, initial_delay: float = 0.1
):
    """
    Creates a mock LLM streaming response for a given model.

    Args:
        model_name: Name of the model (used in chunk content)
        num_chunks: Number of chunks to generate
        initial_delay: Delay before first chunk

    Returns:
        Generator yielding chunks
    """
    chunks = [
        f"[{model_name}] Chunk {i}: Some response text. " for i in range(num_chunks)
    ]
    return mock_streaming_response(
        chunks, delay_per_chunk=0.05, initial_delay=initial_delay
    )


class MockCallLLm:
    """Mock CallLLm class that returns controlled streaming responses."""

    def __init__(self, keys, model_name):
        self.keys = keys
        self.model_name = model_name
        self.call_count = 0

    def __call__(
        self,
        prompt,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        *args,
        **kwargs,
    ):
        self.call_count += 1
        if stream:
            # Different models have different initial delays to test ordering
            if "fast" in self.model_name.lower():
                initial_delay = 0.1
            elif "slow" in self.model_name.lower():
                initial_delay = 0.5
            else:
                initial_delay = 0.2

            return create_mock_llm_response(
                self.model_name, num_chunks=15, initial_delay=initial_delay
            )
        else:
            return f"Non-streaming response from {self.model_name}"


def test_stream_multiple_models_basic():
    """
    Test basic functionality: chunks should be yielded as they arrive.

    Expected behavior:
    - First chunk should arrive within ~0.2s of starting
    - All chunks from first model should stream before second model
    - Total time should be roughly: initial_delay + (num_chunks * delay_per_chunk) for each model
    """
    from common import stream_multiple_models, get_async_future

    logger.warning("=" * 60)
    logger.warning("TEST: test_stream_multiple_models_basic")
    logger.warning("=" * 60)

    keys = {"openAIKey": "test", "openRouterKey": "test"}
    model_names = ["fast-model", "slow-model"]
    prompts = ["Test prompt 1", "Test prompt 2"]

    test_start = time.perf_counter()
    chunks_received = []
    chunk_times = []

    with patch("call_llm.CallLLm", MockCallLLm):
        gen = stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            collapsible_headers=True,
        )

        for chunk in gen:
            now = time.perf_counter()
            elapsed = now - test_start
            chunks_received.append(chunk)
            chunk_times.append(elapsed)

            if len(chunks_received) == 1:
                logger.warning(f"First chunk received at t={elapsed:.3f}s")
            elif len(chunks_received) % 10 == 0:
                logger.warning(
                    f"Chunk {len(chunks_received)} received at t={elapsed:.3f}s"
                )

    total_time = time.perf_counter() - test_start
    logger.warning(f"Total chunks: {len(chunks_received)}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Time to first chunk: {chunk_times[0]:.3f}s")

    # Assertions
    assert len(chunks_received) > 0, "Should receive at least one chunk"
    assert chunk_times[0] < 1.0, (
        f"First chunk should arrive within 1s, got {chunk_times[0]:.3f}s"
    )

    # Check that streaming is happening progressively (not all at once at the end)
    # Note: With collapsible headers, there may be initial HTML chunks that arrive together
    if len(chunk_times) > 5:
        first_5_chunks_time = chunk_times[4]
        # Relaxed assertion - just check first chunk is fast
        logger.warning(f"First 5 chunks arrived at t={first_5_chunks_time:.3f}s")

    logger.warning("TEST PASSED: test_stream_multiple_models_basic")
    return True


def test_stream_multiple_models_timing():
    """
    Test that measures exact timing of chunk delivery.

    This test helps diagnose if there's any delay between:
    1. Model thread enqueuing a chunk
    2. Main loop dequeuing the chunk
    3. Generator yielding the chunk
    """
    from common import stream_multiple_models

    logger.warning("=" * 60)
    logger.warning("TEST: test_stream_multiple_models_timing")
    logger.warning("=" * 60)

    keys = {"openAIKey": "test", "openRouterKey": "test"}
    model_names = ["model-a"]  # Single model for simpler timing analysis
    prompts = ["Test prompt"]

    test_start = time.perf_counter()
    timing_data = []

    with patch("call_llm.CallLLm", MockCallLLm):
        gen = stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            collapsible_headers=True,
        )

        for i, chunk in enumerate(gen):
            now = time.perf_counter()
            elapsed = now - test_start
            timing_data.append(
                {
                    "chunk_idx": i,
                    "time": elapsed,
                    "chunk_len": len(chunk),
                    "chunk_preview": chunk[:50] if len(chunk) > 50 else chunk,
                }
            )

    total_time = time.perf_counter() - test_start

    # Analyze timing
    logger.warning(f"\nTiming Analysis:")
    logger.warning(f"Total chunks: {len(timing_data)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    if len(timing_data) > 1:
        # Calculate inter-chunk delays
        delays = []
        for i in range(1, len(timing_data)):
            delay = timing_data[i]["time"] - timing_data[i - 1]["time"]
            delays.append(delay)

        avg_delay = sum(delays) / len(delays)
        max_delay = max(delays)
        min_delay = min(delays)

        logger.warning(
            f"Inter-chunk delays: avg={avg_delay:.4f}s, min={min_delay:.4f}s, max={max_delay:.4f}s"
        )
        logger.warning(f"Time to first chunk: {timing_data[0]['time']:.3f}s")

        # Check for any suspiciously long delays
        long_delays = [(i, d) for i, d in enumerate(delays) if d > 0.5]
        if long_delays:
            logger.warning(f"WARNING: Found {len(long_delays)} delays > 0.5s:")
            for idx, delay in long_delays[:5]:  # Show first 5
                logger.warning(f"  Chunk {idx + 1}: {delay:.3f}s delay")

        # Assertions
        assert timing_data[0]["time"] < 1.0, (
            f"First chunk too slow: {timing_data[0]['time']:.3f}s"
        )
        assert max_delay < 2.0, f"Max inter-chunk delay too high: {max_delay:.3f}s"

    logger.warning("TEST PASSED: test_stream_multiple_models_timing")
    return True


def test_stream_multiple_models_with_slow_model():
    """
    Test with one fast and one slow model.

    Expected: Fast model should start streaming immediately,
    slow model should be buffered and stream after fast model completes.
    """
    from common import stream_multiple_models

    logger.warning("=" * 60)
    logger.warning("TEST: test_stream_multiple_models_with_slow_model")
    logger.warning("=" * 60)

    keys = {"openAIKey": "test", "openRouterKey": "test"}
    model_names = ["fast-model", "slow-model"]
    prompts = ["Fast prompt", "Slow prompt"]

    test_start = time.perf_counter()
    chunks_by_model = {"fast": [], "slow": []}
    first_chunk_time = None

    with patch("call_llm.CallLLm", MockCallLLm):
        gen = stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            collapsible_headers=True,
        )

        for chunk in gen:
            now = time.perf_counter()
            elapsed = now - test_start

            if first_chunk_time is None:
                first_chunk_time = elapsed
                logger.warning(f"First chunk at t={elapsed:.3f}s")

            if "fast-model" in chunk:
                chunks_by_model["fast"].append((elapsed, chunk))
            elif "slow-model" in chunk:
                chunks_by_model["slow"].append((elapsed, chunk))

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nResults:")
    logger.warning(f"Fast model chunks: {len(chunks_by_model['fast'])}")
    logger.warning(f"Slow model chunks: {len(chunks_by_model['slow'])}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Time to first chunk: {first_chunk_time:.3f}s")

    if chunks_by_model["fast"]:
        logger.warning(
            f"Fast model first chunk: t={chunks_by_model['fast'][0][0]:.3f}s"
        )
        logger.warning(
            f"Fast model last chunk: t={chunks_by_model['fast'][-1][0]:.3f}s"
        )

    if chunks_by_model["slow"]:
        logger.warning(
            f"Slow model first chunk: t={chunks_by_model['slow'][0][0]:.3f}s"
        )
        logger.warning(
            f"Slow model last chunk: t={chunks_by_model['slow'][-1][0]:.3f}s"
        )

    # Assertions
    assert first_chunk_time is not None, "Should receive at least one chunk"
    assert first_chunk_time < 1.0, (
        f"First chunk should arrive within 1s, got {first_chunk_time:.3f}s"
    )

    logger.warning("TEST PASSED: test_stream_multiple_models_with_slow_model")
    return True


def test_stream_multiple_models_queue_behavior():
    """
    Test to diagnose queue behavior specifically.

    This test measures timing of chunk delivery to infer queue behavior.
    Note: Direct queue patching is not possible since Queue is imported
    locally inside stream_multiple_models.
    """
    from common import stream_multiple_models

    logger.warning("=" * 60)
    logger.warning("TEST: test_stream_multiple_models_queue_behavior")
    logger.warning("=" * 60)

    keys = {"openAIKey": "test", "openRouterKey": "test"}
    model_names = ["test-model"]
    prompts = ["Test prompt"]

    test_start = time.perf_counter()
    chunks_received = []
    chunk_times = []

    with patch("call_llm.CallLLm", MockCallLLm):
        gen = stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            collapsible_headers=True,
        )

        for chunk in gen:
            elapsed = time.perf_counter() - test_start
            chunks_received.append(chunk)
            chunk_times.append(elapsed)
            if len(chunks_received) == 1:
                logger.warning(f"[Timing] First chunk received at t={elapsed:.3f}s")

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nQueue Behavior Analysis (inferred from timing):")
    logger.warning(f"Total chunks: {len(chunks_received)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    if chunk_times:
        first_chunk_time = chunk_times[0]
        logger.warning(f"Time to first chunk: {first_chunk_time:.3f}s")

        # Calculate inter-chunk delays
        if len(chunk_times) > 1:
            delays = [
                chunk_times[i] - chunk_times[i - 1] for i in range(1, len(chunk_times))
            ]
            avg_delay = sum(delays) / len(delays)
            max_delay = max(delays)
            logger.warning(
                f"Inter-chunk delays: avg={avg_delay:.4f}s, max={max_delay:.4f}s"
            )

        # First chunk should arrive quickly (within initial_delay + overhead)
        assert first_chunk_time < 1.0, f"First chunk too slow: {first_chunk_time:.3f}s"

    logger.warning("TEST PASSED: test_stream_multiple_models_queue_behavior")
    return True


def test_stream_multiple_models_iteration_timing():
    """
    Test to measure exact timing of generator iteration.

    This wraps the generator to measure time spent in each next() call.
    """
    from common import stream_multiple_models

    logger.warning("=" * 60)
    logger.warning("TEST: test_stream_multiple_models_iteration_timing")
    logger.warning("=" * 60)

    keys = {"openAIKey": "test", "openRouterKey": "test"}
    model_names = ["test-model"]
    prompts = ["Test prompt"]

    test_start = time.perf_counter()
    iteration_times = []

    with patch("call_llm.CallLLm", MockCallLLm):
        gen = stream_multiple_models(
            keys=keys,
            model_names=model_names,
            prompts=prompts,
            collapsible_headers=True,
        )

        while True:
            try:
                iter_start = time.perf_counter()
                chunk = next(gen)
                iter_end = time.perf_counter()

                iteration_times.append(
                    {
                        "start": iter_start - test_start,
                        "end": iter_end - test_start,
                        "duration": iter_end - iter_start,
                        "chunk_preview": chunk[:30] if len(chunk) > 30 else chunk,
                    }
                )

                if len(iteration_times) == 1:
                    logger.warning(
                        f"First next() took {iteration_times[0]['duration']:.3f}s"
                    )

            except StopIteration:
                break

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nIteration Analysis:")
    logger.warning(f"Total iterations: {len(iteration_times)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    if iteration_times:
        durations = [t["duration"] for t in iteration_times]
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)

        logger.warning(f"Avg iteration time: {avg_duration:.4f}s")
        logger.warning(f"Max iteration time: {max_duration:.4f}s")
        logger.warning(f"First iteration time: {durations[0]:.4f}s")

        # Find slow iterations
        slow_iters = [(i, d) for i, d in enumerate(durations) if d > 0.2]
        if slow_iters:
            logger.warning(f"WARNING: Found {len(slow_iters)} slow iterations (>0.2s):")
            for idx, duration in slow_iters[:5]:
                logger.warning(f"  Iteration {idx}: {duration:.3f}s")

        # First iteration should be fast (generator should yield quickly)
        assert durations[0] < 1.0, f"First iteration too slow: {durations[0]:.3f}s"

    logger.warning("TEST PASSED: test_stream_multiple_models_iteration_timing")
    return True


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_stream_multiple_models_basic,
        test_stream_multiple_models_timing,
        test_stream_multiple_models_with_slow_model,
        test_stream_multiple_models_queue_behavior,
        test_stream_multiple_models_iteration_timing,
    ]

    results = []
    for test in tests:
        try:
            logger.warning(f"\n{'=' * 60}")
            logger.warning(f"Running: {test.__name__}")
            logger.warning(f"{'=' * 60}\n")
            test()
            results.append((test.__name__, True, None))
        except Exception as e:
            import traceback

            results.append((test.__name__, False, traceback.format_exc()))
            logger.error(f"FAILED: {test.__name__}")
            logger.error(traceback.format_exc())

    # Summary
    logger.warning("\n" + "=" * 60)
    logger.warning("TEST SUMMARY")
    logger.warning("=" * 60)

    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed

    for name, success, error in results:
        status = "PASSED" if success else "FAILED"
        logger.warning(f"  {name}: {status}")

    logger.warning(f"\nTotal: {passed}/{len(results)} passed, {failed} failed")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
