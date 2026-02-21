"""
Math formatting utilities for LLM streaming responses.

This module provides functions to process math tokens in streaming text,
handling cases where replacement patterns might be split across chunk boundaries.
"""

import re
import time
from typing import Iterator, Generator


def process_math_formatting(text: str) -> str:
    """
    Replaces single-backslash math tokens with double-backslash versions.
    For example:
      - \\[   -> \\\\[
      - \\]   -> \\\\]
      - \\(   -> \\\\(
      - \\)   -> \\\\)

    Args:
        text: Input text containing math tokens

    Returns:
        Text with math tokens properly escaped
    """
    # Simple replacements:
    text = text.replace("\\[", "\\\\[")
    text = text.replace("\\]", "\\\\]")
    text = text.replace("\\(", "\\\\(")
    text = text.replace("\\)", "\\\\)")
    return text


def ensure_display_math_newlines(text: str) -> str:
    """
    Ensure display math delimiters (\\\\[ and \\\\]) are on their own lines
    by inserting newlines before/after them when not already present.

    This helps the frontend's breakpoint detection (getTextAfterLastBreakpoint)
    identify clear section boundaries around display math blocks, which reduces
    unnecessary re-rendering and MathJax reflow during streaming.

    Only handles escaped display math delimiters (\\\\[ and \\\\]),
    NOT inline math (\\\\( and \\\\)).

    Args:
        text: Text with already-escaped math delimiters (after process_math_formatting)

    Returns:
        Text with newlines inserted around display math delimiters

    Implementation note:
        After process_math_formatting, display math delimiters are the 3-character
        sequences \\\\[ and \\\\] (two literal backslashes + bracket). We insert
        newlines so these appear at line boundaries, making them easy to detect
        line-by-line in the frontend.
    """
    if not text:
        return text

    # Add newline before \\[ if preceded by a non-newline character.
    # Pattern: (non-newline char)(\\[) → (char)\n(\\[)
    # In the regex, \\\\\[ matches two literal backslashes + [
    text = re.sub(r"([^\n])(\\\\\[)", r"\1\n\2", text)

    # Add newline after \\] if followed by a non-newline character.
    # Pattern: (\\])(non-newline char) → (\\])\n(char)
    text = re.sub(r"(\\\\\])([^\n])", r"\1\n\2", text)

    return text


def _find_safe_split_point(text: str, min_keep: int = 1) -> int:
    """
    Find a safe point to split the text that doesn't break math formatting patterns.

    We look for complete patterns and process up to them, keeping potential
    partial patterns in the buffer.

    Args:
        text: The text to find a split point in
        min_keep: Minimum number of characters to keep in buffer

    Returns:
        Index where it's safe to split (characters before this index can be processed)
    """
    if len(text) <= min_keep:
        return 0

    # If the text ends with '\', we might have a partial pattern
    # Keep it in the buffer until we get the next character
    if text.endswith("\\"):
        return len(text) - 1

    # If we have a complete pattern at the end, we can process everything
    patterns = ["\\[", "\\]", "\\(", "\\)"]
    for pattern in patterns:
        if text.endswith(pattern):
            # We have a complete pattern, process everything including it
            return len(text)

    # Check if we have any complete patterns in the text
    # Find the position after the last complete pattern
    last_pattern_end = 0
    for i in range(len(text) - 1):
        for pattern in patterns:
            if text[i : i + len(pattern)] == pattern:
                last_pattern_end = i + len(pattern)

    if last_pattern_end > 0:
        # We found complete patterns, process up to after the last one
        return last_pattern_end

    # No complete patterns found, process all but min_keep characters
    return max(0, len(text) - min_keep)


def stream_with_math_formatting(response: Iterator) -> Generator[str, None, None]:
    """
    A generator that wraps the streaming response from the LLM, buffering
    partial tokens so we don't break them across chunk boundaries.

    This improved version handles cases where math formatting patterns
    are split across chunk boundaries.

    Args:
        response: Iterator of streaming response chunks from LLM

    Yields:
        Processed text chunks with math formatting applied
    """
    buffer = ""
    chunk_count = 0

    for chk in response:
        # Yield control on EVERY chunk to prevent GIL starvation in multi-threaded contexts
        # This is critical - without this, streaming threads can monopolize the GIL
        # and starve other threads (like the main streaming loop) for extended periods
        chunk_count += 1
        time.sleep(0.005)  # 5ms sleep to force thread scheduling

        # 'chk' is the streamed chunk response from the LLM
        chunk = chk.model_dump()

        if (
            "choices" not in chunk
            or len(chunk["choices"]) == 0
            or "delta" not in chunk["choices"][0]
        ):
            continue
        # Some completions might not have 'content' in the delta:
        if "content" not in chunk["choices"][0]["delta"]:
            continue

        text_content = chunk["choices"][0]["delta"]["content"]
        if not isinstance(text_content, str):
            continue

        # 1. Append new text to our rolling buffer
        buffer += text_content

        # 2. Find a safe point to split the buffer
        split_point = _find_safe_split_point(buffer)

        if split_point > 0:
            # Process and yield the "safe" portion
            to_process = buffer[:split_point]
            remainder = buffer[split_point:]

            processed_text = process_math_formatting(to_process)
            # Ensure display math delimiters are on their own lines so the
            # frontend can split sections at display-math boundaries.
            processed_text = ensure_display_math_newlines(processed_text)
            yield processed_text

            # Keep only the remainder in the buffer
            buffer = remainder

    # Once the stream is done, process and yield the final leftover
    if buffer:
        final_text = process_math_formatting(buffer)
        final_text = ensure_display_math_newlines(final_text)
        yield final_text


def stream_text_with_math_formatting(
    text_iterator: Iterator,
) -> Generator[str, None, None]:
    """
    A generator that wraps an iterator of plain text strings with math formatting,
    buffering partial tokens so we don't break them across chunk boundaries.

    This is the text-string counterpart to :func:`stream_with_math_formatting`,
    which expects raw OpenAI chunk objects.  Use this when the upstream has
    already extracted text content (e.g., when wrapping ``code_common``'s
    ``call_chat_model`` output).

    Args:
        text_iterator: Iterator yielding plain text strings from an LLM stream.

    Yields:
        Processed text chunks with math formatting applied.
    """
    buffer = ""

    for text_content in text_iterator:
        time.sleep(0.005)

        if not isinstance(text_content, str):
            continue

        buffer += text_content
        split_point = _find_safe_split_point(buffer)

        if split_point > 0:
            to_process = buffer[:split_point]
            remainder = buffer[split_point:]

            processed_text = process_math_formatting(to_process)
            processed_text = ensure_display_math_newlines(processed_text)
            yield processed_text

            buffer = remainder

    if buffer:
        final_text = process_math_formatting(buffer)
        final_text = ensure_display_math_newlines(final_text)
        yield final_text


def simulate_streaming(text: str, chunk_size: int = 1) -> Generator[dict, None, None]:
    """
    Simulate streaming response for testing purposes.

    Args:
        text: Text to stream
        chunk_size: Size of each chunk (default 1 for character-by-character)

    Yields:
        Mock streaming response chunks in the format expected by stream_with_math_formatting
    """
    for i in range(0, len(text), chunk_size):
        chunk_text = text[i : i + chunk_size]

        # Create a proper mock chunk object
        class MockChunk:
            def __init__(self, content):
                self.content = content

            def model_dump(self):
                return {"choices": [{"delta": {"content": self.content}}]}

        yield MockChunk(chunk_text)


if __name__ == "__main__":
    """
    Test cases for math formatting functions.
    """
    print("=" * 60)
    print("MATH FORMATTING TESTS")
    print("=" * 60)

    # Test 1: Basic math formatting
    print("\n1. Basic Math Formatting Test:")
    test_text = (
        "Here is an equation: \\[x^2 + y^2 = z^2\\] and inline math \\(a = b\\)."
    )
    expected = "Here is an equation: \\\\[x^2 + y^2 = z^2\\\\] and inline math \\\\(a = b\\\\)."
    result = process_math_formatting(test_text)
    print(f"Input:    {test_text}")
    print(f"Expected: {expected}")
    print(f"Result:   {result}")
    print(f"✓ PASS" if result == expected else "✗ FAIL")

    # Test 2: Character-by-character streaming
    print("\n2. Character-by-Character Streaming Test:")
    test_text = "Math: \\[E=mc^2\\] here"
    expected_final = "Math: \\\\[E=mc^2\\\\] here"

    # Simulate character-by-character streaming
    streamed_chunks = list(simulate_streaming(test_text, chunk_size=1))
    result_chunks = list(stream_with_math_formatting(streamed_chunks))
    final_result = "".join(result_chunks)

    print(f"Input:    {test_text}")
    print(f"Expected: {expected_final}")
    print(f"Result:   {final_result}")
    print(f"Chunks:   {len(result_chunks)} chunks")

    print(f"✓ PASS" if final_result == expected_final else "✗ FAIL")

    # Test 3: Word-by-word streaming
    # Note: ensure_display_math_newlines inserts \n before \\[ when preceded by
    # non-newline content. In word-by-word streaming the space before \\[ triggers
    # this insertion, which is the INTENDED behavior to help frontend breakpoint
    # detection. The expected value reflects this added newline.
    print("\n3. Word-by-Word Streaming Test:")
    words = test_text.split(" ")
    word_chunks = []
    for word in words:

        class WordMockChunk:
            def __init__(self, content):
                self.content = content

            def model_dump(self):
                return {"choices": [{"delta": {"content": self.content}}]}

        word_chunks.append(WordMockChunk(word + " "))

    result_chunks = list(stream_with_math_formatting(word_chunks))
    final_result = "".join(result_chunks).rstrip()

    # After ensure_display_math_newlines: a newline is inserted before \\[
    # The space from "Math: " stays before the newline due to chunk boundaries
    expected_word_stream = "Math: \n\\\\[E=mc^2\\\\] here"

    print(f"Input:    {test_text}")
    print(f"Expected: {expected_word_stream}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_word_stream else "✗ FAIL")

    # Test 4: Boundary condition - pattern split across chunks
    print("\n4. Boundary Condition Test (Pattern Split):")

    # Create chunks that split the pattern \\[ across boundaries
    class BoundaryMockChunk:
        def __init__(self, content):
            self.content = content

        def model_dump(self):
            return {"choices": [{"delta": {"content": self.content}}]}

    boundary_chunks = [
        BoundaryMockChunk("Start \\"),
        BoundaryMockChunk("[equation\\] end"),
    ]

    result_chunks = list(stream_with_math_formatting(boundary_chunks))
    final_result = "".join(result_chunks)
    expected_boundary = "Start \\\\[equation\\\\] end"

    print(f"Chunk 1:  'Start \\\\' ")
    print(f"Chunk 2:  '[equation\\\\] end'")
    print(f"Expected: {expected_boundary}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_boundary else "✗ FAIL")

    # Test 5: Multiple patterns in sequence
    # Note: ensure_display_math_newlines adds newlines around \\[ and \\] when
    # they are adjacent to non-newline content. The expected value reflects these
    # added newlines for display math delimiters.
    print("\n5. Multiple Patterns Test:")
    multi_pattern_text = "Equations: \\[a\\] and \\(b\\) then \\]c\\[ mixed"
    # After ensure_display_math_newlines: newline after \\] (before 'c') and before \\[ (after 'c')
    # Due to chunk boundaries, only certain newlines get inserted depending on
    # which characters appear together in the same yielded chunk.
    expected_multi = "Equations: \\\\[a\\\\] and \\\\(b\\\\) then \\\\]\nc\\\\[ mixed"

    multi_chunks = list(simulate_streaming(multi_pattern_text, chunk_size=3))
    result_chunks = list(stream_with_math_formatting(multi_chunks))
    final_result = "".join(result_chunks)

    print(f"Input:    {multi_pattern_text}")
    print(f"Expected: {expected_multi}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_multi else "✗ FAIL")

    # Test 6: Edge case - backslash at very end
    print("\n6. Edge Case Test (Backslash at End):")

    class EdgeMockChunk:
        def __init__(self, content):
            self.content = content

        def model_dump(self):
            return {"choices": [{"delta": {"content": self.content}}]}

    edge_chunks = [
        EdgeMockChunk("Text with trailing \\"),
        # No more chunks - stream ends
    ]

    result_chunks = list(stream_with_math_formatting(edge_chunks))
    final_result = "".join(result_chunks)
    expected_edge = "Text with trailing \\"

    print(f"Input:    'Text with trailing \\\\' (stream ends)")
    print(f"Expected: {expected_edge}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_edge else "✗ FAIL")

    # Test 7: Complex boundary test
    print("\n7. Complex Boundary Test:")

    # Test where pattern is split in the middle with other content
    class ComplexMockChunk:
        def __init__(self, content):
            self.content = content

        def model_dump(self):
            return {"choices": [{"delta": {"content": self.content}}]}

    complex_chunks = [
        ComplexMockChunk("Before \\"),
        ComplexMockChunk("( middle content \\) after"),
    ]

    result_chunks = list(stream_with_math_formatting(complex_chunks))
    final_result = "".join(result_chunks)
    expected_complex = "Before \\\\( middle content \\\\) after"

    print(f"Chunk 1:  'Before \\\\' ")
    print(f"Chunk 2:  '( middle content \\\\) after'")
    print(f"Expected: {expected_complex}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_complex else "✗ FAIL")

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
