"""
Test file for buffer_generator_async function.

This test file isolates the buffer_generator_async function to diagnose
timing issues in the async buffering pipeline. It uses controlled generators
to verify that items are buffered and yielded promptly.

Usage:
    python -m pytest tests/test_buffer_generator_async.py -v -s

    Or run directly:
    python tests/test_buffer_generator_async.py
"""

import sys
import os
import time
import threading
from queue import Queue
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


def slow_generator(
    num_items: int = 20, delay_per_item: float = 0.1, initial_delay: float = 0.2
) -> Generator[str, None, None]:
    """
    Creates a slow generator that yields items with controlled delays.

    Args:
        num_items: Number of items to yield
        delay_per_item: Delay between each item
        initial_delay: Initial delay before first item

    Yields:
        String items with controlled timing
    """
    logger.warning(f"[slow_generator] Starting with initial_delay={initial_delay}s")
    time.sleep(initial_delay)

    for i in range(num_items):
        item = f"Item {i}: Some data here"
        logger.warning(f"[slow_generator] Yielding item {i}")
        yield item
        if i < num_items - 1:
            time.sleep(delay_per_item)

    logger.warning(f"[slow_generator] Generator finished")


def fast_generator(num_items: int = 50) -> Generator[str, None, None]:
    """
    Creates a fast generator that yields items immediately.

    Args:
        num_items: Number of items to yield

    Yields:
        String items with no delay
    """
    for i in range(num_items):
        yield f"Fast item {i}"


def variable_delay_generator(delays: List[float]) -> Generator[str, None, None]:
    """
    Creates a generator with variable delays between items.

    Args:
        delays: List of delays before each item

    Yields:
        String items with variable timing
    """
    for i, delay in enumerate(delays):
        time.sleep(delay)
        yield f"Variable item {i} after {delay}s delay"


def test_buffer_generator_async_basic():
    """
    Test basic functionality: items should be buffered and yielded promptly.

    Expected behavior:
    - First item should arrive within initial_delay + small overhead
    - All items should be yielded
    - No significant additional delay from buffering
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_basic")
    logger.warning("=" * 60)

    num_items = 10
    initial_delay = 0.2
    delay_per_item = 0.05

    test_start = time.perf_counter()

    # Create the slow generator
    gen = slow_generator(
        num_items=num_items, delay_per_item=delay_per_item, initial_delay=initial_delay
    )

    # Wrap with buffer_generator_async
    buffered_gen = buffer_generator_async(gen)

    items_received = []
    item_times = []

    for item in buffered_gen:
        now = time.perf_counter()
        elapsed = now - test_start
        items_received.append(item)
        item_times.append(elapsed)

        if len(items_received) == 1:
            logger.warning(f"First item received at t={elapsed:.3f}s")

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nResults:")
    logger.warning(f"Total items: {len(items_received)}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Time to first item: {item_times[0]:.3f}s")

    # Expected time: initial_delay + (num_items - 1) * delay_per_item
    expected_time = initial_delay + (num_items - 1) * delay_per_item
    logger.warning(f"Expected minimum time: {expected_time:.3f}s")

    # Assertions
    assert len(items_received) == num_items, (
        f"Expected {num_items} items, got {len(items_received)}"
    )
    assert item_times[0] < initial_delay + 0.5, (
        f"First item too slow: {item_times[0]:.3f}s"
    )

    # Total time should be close to expected (with some overhead allowance)
    assert total_time < expected_time * 2, (
        f"Total time too high: {total_time:.3f}s vs expected {expected_time:.3f}s"
    )

    logger.warning("TEST PASSED: test_buffer_generator_async_basic")
    return True


def test_buffer_generator_async_timing():
    """
    Test exact timing of buffer delivery.

    This measures:
    1. Time for first item to be yielded
    2. Time between consecutive items
    3. Whether buffering adds overhead
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_timing")
    logger.warning("=" * 60)

    num_items = 15
    delay_per_item = 0.1
    initial_delay = 0.3

    test_start = time.perf_counter()

    gen = slow_generator(
        num_items=num_items, delay_per_item=delay_per_item, initial_delay=initial_delay
    )
    buffered_gen = buffer_generator_async(gen)

    timing_data = []

    for i, item in enumerate(buffered_gen):
        now = time.perf_counter()
        elapsed = now - test_start
        timing_data.append({"index": i, "time": elapsed, "item": item})

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nTiming Analysis:")
    logger.warning(f"Total items: {len(timing_data)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    if len(timing_data) > 1:
        # Calculate inter-item delays
        delays = []
        for i in range(1, len(timing_data)):
            delay = timing_data[i]["time"] - timing_data[i - 1]["time"]
            delays.append(delay)

        avg_delay = sum(delays) / len(delays)
        max_delay = max(delays)
        min_delay = min(delays)

        logger.warning(
            f"Inter-item delays: avg={avg_delay:.4f}s, min={min_delay:.4f}s, max={max_delay:.4f}s"
        )
        logger.warning(f"Expected inter-item delay: {delay_per_item:.4f}s")
        logger.warning(f"Time to first item: {timing_data[0]['time']:.3f}s")
        logger.warning(f"Expected time to first item: {initial_delay:.3f}s")

        # Check for suspicious delays
        # Due to queue timeout (0.1s), items might be delayed slightly
        long_delays = [(i, d) for i, d in enumerate(delays) if d > delay_per_item + 0.2]
        if long_delays:
            logger.warning(
                f"WARNING: Found {len(long_delays)} unexpectedly long delays:"
            )
            for idx, delay in long_delays[:5]:
                logger.warning(
                    f"  Item {idx + 1}: {delay:.3f}s delay (expected ~{delay_per_item:.3f}s)"
                )

        # Assertions
        assert timing_data[0]["time"] < initial_delay + 0.5, (
            f"First item too slow: {timing_data[0]['time']:.3f}s"
        )

        # Average delay should be close to the generator's delay
        assert avg_delay < delay_per_item + 0.15, (
            f"Average delay too high: {avg_delay:.3f}s vs expected {delay_per_item:.3f}s"
        )

    logger.warning("TEST PASSED: test_buffer_generator_async_timing")
    return True


def test_buffer_generator_async_fast_producer():
    """
    Test with a fast producer to verify buffering doesn't slow things down.
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_fast_producer")
    logger.warning("=" * 60)

    num_items = 100

    test_start = time.perf_counter()

    gen = fast_generator(num_items=num_items)
    buffered_gen = buffer_generator_async(gen)

    items_received = []

    for item in buffered_gen:
        items_received.append(item)

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nResults:")
    logger.warning(f"Total items: {len(items_received)}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Items per second: {len(items_received) / total_time:.1f}")

    # Assertions
    assert len(items_received) == num_items, (
        f"Expected {num_items} items, got {len(items_received)}"
    )

    # Fast generator should complete quickly (< 1 second for 100 items)
    assert total_time < 2.0, f"Fast generator took too long: {total_time:.3f}s"

    logger.warning("TEST PASSED: test_buffer_generator_async_fast_producer")
    return True


def test_buffer_generator_async_slow_consumer():
    """
    Test with a slow consumer to verify buffering works correctly.

    The producer is fast, but the consumer is slow. The buffer should
    accumulate items while the consumer processes them.
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_slow_consumer")
    logger.warning("=" * 60)

    num_items = 20
    consumer_delay = 0.05

    test_start = time.perf_counter()

    gen = fast_generator(num_items=num_items)
    buffered_gen = buffer_generator_async(gen)

    items_received = []

    for item in buffered_gen:
        items_received.append(item)
        time.sleep(consumer_delay)  # Slow consumer

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nResults:")
    logger.warning(f"Total items: {len(items_received)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    # Expected time: num_items * consumer_delay (producer is fast, consumer is slow)
    expected_time = num_items * consumer_delay
    logger.warning(f"Expected minimum time: {expected_time:.3f}s")

    # Assertions
    assert len(items_received) == num_items, (
        f"Expected {num_items} items, got {len(items_received)}"
    )

    # Total time should be dominated by consumer delay
    assert total_time < expected_time * 1.5, f"Total time too high: {total_time:.3f}s"

    logger.warning("TEST PASSED: test_buffer_generator_async_slow_consumer")
    return True


def test_buffer_generator_async_queue_timing():
    """
    Test to diagnose queue timing specifically.

    This simulates the scenario where items are enqueued quickly
    but may be dequeued slowly.
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_queue_timing")
    logger.warning("=" * 60)

    # Variable delays to simulate real-world streaming
    delays = [0.1, 0.05, 0.02, 0.05, 0.1, 0.02, 0.05, 0.05, 0.1, 0.02]

    test_start = time.perf_counter()

    gen = variable_delay_generator(delays)
    buffered_gen = buffer_generator_async(gen)

    timing_data = []

    for i, item in enumerate(buffered_gen):
        now = time.perf_counter()
        elapsed = now - test_start
        timing_data.append(
            {
                "index": i,
                "time": elapsed,
                "expected_cumulative_delay": sum(delays[: i + 1]),
            }
        )

    total_time = time.perf_counter() - test_start
    expected_total = sum(delays)

    logger.warning(f"\nQueue Timing Analysis:")
    logger.warning(f"Total items: {len(timing_data)}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Expected total time: {expected_total:.3f}s")

    # Check timing accuracy
    for data in timing_data:
        actual = data["time"]
        expected = data["expected_cumulative_delay"]
        diff = actual - expected
        if diff > 0.2:  # Allow 200ms overhead
            logger.warning(
                f"Item {data['index']}: actual={actual:.3f}s, expected={expected:.3f}s, diff={diff:.3f}s"
            )

    # Assertions
    assert len(timing_data) == len(delays), f"Expected {len(delays)} items"

    # First item should arrive close to first delay
    assert timing_data[0]["time"] < delays[0] + 0.2, (
        f"First item too slow: {timing_data[0]['time']:.3f}s vs expected {delays[0]:.3f}s"
    )

    logger.warning("TEST PASSED: test_buffer_generator_async_queue_timing")
    return True


def test_buffer_generator_async_iteration_timing():
    """
    Test exact timing of each next() call.

    This measures how long each iteration takes and identifies
    any blocking behavior.
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_iteration_timing")
    logger.warning("=" * 60)

    num_items = 15
    delay_per_item = 0.1
    initial_delay = 0.2

    test_start = time.perf_counter()

    gen = slow_generator(
        num_items=num_items, delay_per_item=delay_per_item, initial_delay=initial_delay
    )
    buffered_gen = buffer_generator_async(gen)

    iteration_times = []

    while True:
        try:
            iter_start = time.perf_counter()
            item = next(buffered_gen)
            iter_end = time.perf_counter()

            iteration_times.append(
                {
                    "start": iter_start - test_start,
                    "end": iter_end - test_start,
                    "duration": iter_end - iter_start,
                    "item": item,
                }
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
        min_duration = min(durations)

        logger.warning(
            f"Iteration durations: avg={avg_duration:.4f}s, min={min_duration:.4f}s, max={max_duration:.4f}s"
        )
        logger.warning(f"First iteration duration: {durations[0]:.4f}s")

        # Identify slow iterations
        # Note: queue.get(timeout=0.1) means max wait is 0.1s when queue is empty
        slow_iters = [(i, d) for i, d in enumerate(durations) if d > 0.15]
        if slow_iters:
            logger.warning(f"Slow iterations (>0.15s): {len(slow_iters)}")
            for idx, duration in slow_iters[:5]:
                logger.warning(f"  Iteration {idx}: {duration:.3f}s")

        # Assertions
        # First iteration will wait for initial_delay + first item
        assert durations[0] < initial_delay + 0.3, (
            f"First iteration too slow: {durations[0]:.3f}s vs expected ~{initial_delay:.3f}s"
        )

    logger.warning("TEST PASSED: test_buffer_generator_async_iteration_timing")
    return True


def test_buffer_generator_async_thread_timing():
    """
    Test to verify the background thread is running correctly.

    This test adds instrumentation to track when the background
    thread enqueues items vs when the main thread dequeues them.
    """
    from queue import Queue
    import threading

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_thread_timing")
    logger.warning("=" * 60)

    enqueue_times = []
    dequeue_times = []
    test_start = time.perf_counter()

    def instrumented_slow_generator(num_items=10, delay=0.1, initial_delay=0.2):
        """Generator that logs when items are produced."""
        time.sleep(initial_delay)
        for i in range(num_items):
            enqueue_times.append(time.perf_counter() - test_start)
            logger.warning(
                f"[Producer] Yielding item {i} at t={enqueue_times[-1]:.3f}s"
            )
            yield f"Item {i}"
            if i < num_items - 1:
                time.sleep(delay)

    from base import buffer_generator_async

    gen = instrumented_slow_generator(num_items=10, delay=0.1, initial_delay=0.2)
    buffered_gen = buffer_generator_async(gen)

    items = []
    for item in buffered_gen:
        dequeue_times.append(time.perf_counter() - test_start)
        items.append(item)
        logger.warning(f"[Consumer] Received item at t={dequeue_times[-1]:.3f}s")

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nThread Timing Analysis:")
    logger.warning(f"Total items: {len(items)}")
    logger.warning(f"Total time: {total_time:.3f}s")

    if enqueue_times and dequeue_times:
        # Calculate enqueue-to-dequeue delays
        delays = []
        for i in range(min(len(enqueue_times), len(dequeue_times))):
            delay = dequeue_times[i] - enqueue_times[i]
            delays.append(delay)
            if i < 5:
                logger.warning(
                    f"Item {i}: enqueue={enqueue_times[i]:.3f}s, dequeue={dequeue_times[i]:.3f}s, delay={delay:.3f}s"
                )

        avg_delay = sum(delays) / len(delays)
        max_delay = max(delays)

        logger.warning(
            f"\nEnqueue-to-dequeue delays: avg={avg_delay:.4f}s, max={max_delay:.4f}s"
        )

        # The delay should be small (just queue overhead)
        # Unless the consumer is slower than the producer
        assert avg_delay < 0.2, (
            f"Average enqueue-to-dequeue delay too high: {avg_delay:.3f}s"
        )

    logger.warning("TEST PASSED: test_buffer_generator_async_thread_timing")
    return True


def test_buffer_generator_async_with_nested_generator():
    """
    Test with a nested generator structure (similar to stream_multiple_models).

    This simulates the real scenario where stream_multiple_models yields
    chunks and buffer_generator_async wraps it.
    """
    from base import buffer_generator_async

    logger.warning("=" * 60)
    logger.warning("TEST: test_buffer_generator_async_with_nested_generator")
    logger.warning("=" * 60)

    def mock_stream_multiple_models():
        """
        Simulates stream_multiple_models behavior:
        - Has a queue internally
        - Yields chunks as they arrive
        - May have delays between chunks
        """
        from queue import Queue
        import threading

        internal_queue = Queue()
        num_models = 2
        chunks_per_model = 10

        def producer(model_id, delay):
            """Simulates a model thread."""
            time.sleep(delay)  # Initial delay
            for i in range(chunks_per_model):
                chunk = f"[Model {model_id}] Chunk {i}"
                internal_queue.put(("chunk", model_id, chunk))
                time.sleep(0.05)  # Delay between chunks
            internal_queue.put(("done", model_id, None))

        # Start producer threads
        threads = []
        for i in range(num_models):
            t = threading.Thread(target=producer, args=(i, 0.1 * (i + 1)))
            t.start()
            threads.append(t)

        # Yield chunks from queue
        completed = 0
        while completed < num_models:
            try:
                msg_type, model_id, chunk = internal_queue.get(timeout=0.1)
                if msg_type == "chunk":
                    yield chunk
                elif msg_type == "done":
                    completed += 1
            except:
                pass

        for t in threads:
            t.join()

    test_start = time.perf_counter()

    # This is the exact pattern used in Conversation.py
    gen = mock_stream_multiple_models()
    buffered_gen = buffer_generator_async(gen)

    items = []
    item_times = []

    for item in buffered_gen:
        elapsed = time.perf_counter() - test_start
        items.append(item)
        item_times.append(elapsed)
        if len(items) == 1:
            logger.warning(f"First chunk received at t={elapsed:.3f}s")

    total_time = time.perf_counter() - test_start

    logger.warning(f"\nNested Generator Results:")
    logger.warning(f"Total chunks: {len(items)}")
    logger.warning(f"Total time: {total_time:.3f}s")
    logger.warning(f"Time to first chunk: {item_times[0]:.3f}s")

    # Assertions
    assert len(items) > 0, "Should receive at least one chunk"
    assert item_times[0] < 1.0, f"First chunk too slow: {item_times[0]:.3f}s"

    logger.warning("TEST PASSED: test_buffer_generator_async_with_nested_generator")
    return True


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_buffer_generator_async_basic,
        test_buffer_generator_async_timing,
        test_buffer_generator_async_fast_producer,
        test_buffer_generator_async_slow_consumer,
        test_buffer_generator_async_queue_timing,
        test_buffer_generator_async_iteration_timing,
        test_buffer_generator_async_thread_timing,
        test_buffer_generator_async_with_nested_generator,
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
