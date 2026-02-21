# Multi-Model Streaming Delay Fix

## Executive Summary

This document describes the investigation and fix for a critical performance issue where multi-model LLM streaming responses experienced 20-140+ second delays before the first token appeared to users, even though model responses were being generated much earlier.

**Root Cause**: GIL (Global Interpreter Lock) starvation in Python's threading model caused the main streaming thread to be completely starved by model worker threads.

**Fix**: Changed `time.sleep(0)` to `time.sleep(0.001)` (1ms) in all stream consumption loops to force actual OS thread scheduling.

**Result**: First token now appears within 1-5 seconds (actual LLM response time) instead of 130+ seconds.

---

## Problem Statement

### Symptoms

When using `CallMultipleLLM` or `NResponseAgent` (which uses multiple models):
- User sends a message
- 20-140+ seconds pass with no visible output
- Suddenly, all content appears at once
- Single-model responses worked fine

### Timeline from Logs (Before Fix)

```
00:02:33.768 - stream_multiple_models loop iteration 1 | t=0.001s
00:02:35     - first chunk enqueued (Gemini) | t=1.231s
00:02:36     - first chunk enqueued (Claude) | t=3.000s
... (no more loop iterations for 130+ seconds) ...
00:13:15     - loop iteration 2 | queue_size=2254 | t=132.456s  <- FINALLY!
00:13:15     - first item dequeued | first chunk to user
```

The main loop was supposed to run every 100ms (queue.get timeout), but it didn't run for 132 seconds!

---

## Root Cause Analysis

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Main Thread (Flask)                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  buffer_generator_async (Thread)                         │   │
│  │    └── stream_multiple_models (Generator)                │   │
│  │          └── Main Loop (queue.get timeout=0.1s)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Model Thread 1: Gemini                                  │   │
│  │    └── Iterates LLM stream, puts chunks in queue         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Model Thread 2: Claude                                  │   │
│  │    └── Iterates LLM stream, puts chunks in queue         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Context Extraction Threads (4x)                         │   │
│  │    └── LLM calls with stream=False                       │   │
│  │    └── convert_stream_to_iterable() - tight loop!        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### The GIL Problem

Python's Global Interpreter Lock (GIL) means only one thread can execute Python bytecode at a time. Threads must acquire the GIL to run.

**The Issue**: `time.sleep(0)` releases the GIL but doesn't guarantee a context switch. When multiple threads call `sleep(0)`, they can keep passing the GIL back and forth between themselves, never giving other threads a chance.

### What Happened

1. **Model threads** started iterating their LLM streams
2. Each chunk iteration involved:
   - Receiving network data (releases GIL - good)
   - Processing chunk (holds GIL)
   - Calling `time.sleep(0)` (releases GIL, but...)
3. **Two model threads** kept alternating, passing GIL between themselves
4. **Main loop thread** never got scheduled because `sleep(0)` doesn't force rescheduling
5. **Context extraction threads** also had tight loops consuming streams

### Evidence from Logs

```
# Model threads making progress (putting chunks in queue):
00:11:09 - thread progress | model_id=gemini | chunks=18 | t=6.479s
00:11:10 - thread progress | model_id=claude | chunks=85 | t=7.502s
00:11:14 - thread progress | model_id=gemini | chunks=30 | t=11.656s
...
00:11:34 - thread finished | model_id=gemini | chunks=77 | t=31.139s
00:13:15 - thread finished | model_id=claude | chunks=2173 | t=132.456s

# Main loop only resumed AFTER both threads finished:
00:13:15 - loop iteration 2 | queue_size=2254 | t=132.456s
```

---

## The Fix

### Solution

Replace `time.sleep(0)` with `time.sleep(0.001)` (1 millisecond).

A non-zero sleep duration forces the OS scheduler to actually deschedule the thread, giving other threads a guaranteed opportunity to run.

### Files Modified

| File | Function | Change |
|------|----------|--------|
| `common.py` | `run_llm()` (lines ~520) | `time.sleep(0.001)` every 10 chunks |
| `common.py` | `convert_stream_to_iterable()` (lines ~1465) | `time.sleep(0.001)` every 5 chunks |
| `code_common/call_llm.py` | `convert_stream_to_iterable()` (lines ~227) | `time.sleep(0.001)` every 5 chunks |
| `Conversation.py` | `_coerce_llm_response_to_text()` (lines ~1835) | `time.sleep(0.001)` every 5 chunks |
| `base.py` | `buffer_generator_async()` (lines ~5430) | `time.sleep(0.001)` every 5 items |

### Code Changes

#### common.py - run_llm() in stream_multiple_models

```python
# Before:
for chunk in collapsible_wrapper(response, ...):
    model_response += chunk
    response_queue.put(("model", model_id, chunk))
    if chunk_count % 10 == 0:
        time.sleep(0)  # Didn't work!

# After:
for chunk in collapsible_wrapper(response, ...):
    model_response_chunks.append(chunk)  # List append instead of string concat
    response_queue.put(("model", model_id, chunk))
    if chunk_count % 10 == 0:
        time.sleep(0.001)  # Forces actual thread scheduling
```

#### common.py - convert_stream_to_iterable()

```python
def convert_stream_to_iterable(stream, join_strings=True):
    """Convert a stream/generator to a list or concatenated string.
    
    This function periodically yields control (via time.sleep(0.001)) to allow
    other threads to run, preventing GIL starvation during long-running
    stream consumption.
    """
    ans = []
    chunk_count = 0
    for t in stream:
        ans.append(t)
        chunk_count += 1
        # Every 5 chunks, yield control to other threads
        # Using 0.001s (1ms) instead of 0 to force actual thread scheduling
        if chunk_count % 5 == 0:
            time.sleep(0.001)
    if ans and isinstance(ans[0], str) and join_strings:
        ans = "".join(ans)
    return ans
```

### Performance Impact

- **Additional latency per response**: ~200-400ms total (2000 chunks × sleep every 5 = 400 sleeps × 1ms = 400ms max)
- **Benefit**: Reduces time-to-first-token from 130+ seconds to 1-5 seconds
- **Net improvement**: ~99% reduction in perceived latency

---

## Diagnostic Logging Added

The investigation added extensive logging that remains useful for future debugging:

### stream_multiple_models (common.py)

```python
# Thread lifecycle:
[stream_multiple_models] thread start | model_id=... | model=... | t=...
[stream_multiple_models] calling LLM | model_id=... | t=...
[stream_multiple_models] LLM returned generator | model_id=... | t=...
[stream_multiple_models] starting to iterate response | model_id=... | t=...
[stream_multiple_models] first chunk enqueued | model_id=... | t=...
[stream_multiple_models] thread progress | model_id=... | chunks=X | t=...  (every 5s)
[stream_multiple_models] thread finished iterating | model_id=... | chunks=X | t=...

# Main loop:
[stream_multiple_models] main loop started | t=...
[stream_multiple_models] loop iteration X | queue_size=Y | completed=Z/N | t=...
[stream_multiple_models] first item dequeued from queue | t=...
[stream_multiple_models] YIELDING first chunk | model_id=... | t=...
[stream_multiple_models] queue.get took Xs (expected <0.1s) | ...  (if slow)
```

### buffer_generator_async (base.py)

```python
[STREAM] buffer_generator_async start | t=...
[STREAM] buffer_generator_async accumulate_items thread started | dt=...
[STREAM] buffer_generator_async about to iterate generator | dt=...
[STREAM] buffer_generator_async progress | items=X | dt=...  (every 5s)
[STREAM] buffer_generator_async first item enqueued | dt=...
[STREAM] buffer_generator_async first item dequeued | dt=...
[STREAM] buffer_generator_async accumulate done | items=X | dt=...
```

### CallLLm (call_llm.py)

`CallLLm.__call__()` now delegates directly to `code_common/call_llm.py`'s `call_llm()`. The `__call_openrouter_models` and `__call_openai_models` methods no longer exist. Timing is logged inside `code_common/call_llm.py`:

```python
[code_common] call_with_stream start | fn=call_chat_model | model=... | do_stream=... | t=...
[code_common] call_with_stream fn returned | is_generator=True | dt=...
[code_common] call_with_stream returning | dt=...
```

---

## Testing

### Test Files Created

| File | Purpose |
|------|---------|
| `tests/test_stream_multiple_models.py` | Unit tests for stream_multiple_models function |
| `tests/test_buffer_generator_async.py` | Unit tests for buffer_generator_async function |

### How to Verify the Fix

1. Send a message with multiple models selected (e.g., Claude + Gemini)
2. Watch for first token appearance time in logs:
   ```
   [STREAM] first item from main_ans_gen | t=X.XXs
   ```
3. **Expected**: `t` should be 1-5 seconds (actual LLM response time)
4. **Before fix**: `t` was 20-140+ seconds

### Log Analysis

Look for the gap between:
```
[stream_multiple_models] first chunk enqueued | ... | t=1.2s
[stream_multiple_models] loop iteration 2 | ... | t=???
```

- **Good**: `t` values are close (within 0.5s)
- **Bad**: Large gap indicates GIL starvation still occurring

---

## Related Issues

### Why Single-Model Streaming Worked

With a single model, there's only one model thread competing for the GIL. The main loop thread gets scheduled naturally because there's less contention.

### Why Context Extraction Made It Worse

Context extraction calls LLMs with `stream=False`, which internally uses `convert_stream_to_iterable()` to consume the stream. These tight loops added more GIL contention, making the problem worse.

### Duplicate peek() Operations (Also Fixed)

During investigation, we also found and removed a duplicate `check_if_stream_and_raise_exception()` call in `call_with_stream()` that was causing unnecessary blocking peek operations.

---

## Future Considerations

### Alternative Solutions (Not Implemented)

1. **Use multiprocessing instead of threading**: Avoids GIL entirely but adds IPC overhead
2. **Use asyncio**: Would require significant refactoring
3. **Reduce number of concurrent threads**: Would slow down parallel model execution

### Monitoring

Consider adding metrics for:
- Time between chunk enqueue and dequeue
- Main loop iteration frequency
- Thread scheduling latency

---

## Summary

| Metric | Before | After |
|--------|--------|-------|
| Time to first token (2 models) | 20-140+ seconds | 1-5 seconds |
| Cause | GIL starvation | Fixed with 1ms sleeps |
| User experience | Perceived as broken | Smooth streaming |

---

## Files Reference

### Modified Files

- `common.py` - `stream_multiple_models()`, `convert_stream_to_iterable()`, `run_llm()`
- `code_common/call_llm.py` - `convert_stream_to_iterable()`
- `Conversation.py` - `_coerce_llm_response_to_text()`
- `base.py` - `buffer_generator_async()`
- `call_llm.py` - `CallMultipleLLM.call_models()` (logging)
- `agents/search_and_information_agents.py` - `NResponseAgent.__call__()` (logging)

### Test Files

- `tests/test_stream_multiple_models.py`
- `tests/test_buffer_generator_async.py`

---

*Last updated: February 2026*
*Fix implemented and verified*
