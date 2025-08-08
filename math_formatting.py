"""
Math formatting utilities for LLM streaming responses.

This module provides functions to process math tokens in streaming text,
handling cases where replacement patterns might be split across chunk boundaries.
"""

import re
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
    text = text.replace('\\[', '\\\\[')
    text = text.replace('\\]', '\\\\]')
    text = text.replace('\\(', '\\\\(')
    text = text.replace('\\)', '\\\\)')
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
    if text.endswith('\\'):
        return len(text) - 1
    
    # If we have a complete pattern at the end, we can process everything
    patterns = ['\\[', '\\]', '\\(', '\\)']
    for pattern in patterns:
        if text.endswith(pattern):
            # We have a complete pattern, process everything including it
            return len(text)
    
    # Check if we have any complete patterns in the text
    # Find the position after the last complete pattern
    last_pattern_end = 0
    for i in range(len(text) - 1):
        for pattern in patterns:
            if text[i:i+len(pattern)] == pattern:
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
    
    for chk in response:
        # 'chk' is the streamed chunk response from the LLM
        chunk = chk.model_dump()
        
        if "choices" not in chunk or len(chunk["choices"]) == 0 or "delta" not in chunk["choices"][0]:
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
            yield processed_text
            
            # Keep only the remainder in the buffer
            buffer = remainder
    
    # Once the stream is done, process and yield the final leftover
    if buffer:
        yield process_math_formatting(buffer)


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
        chunk_text = text[i:i + chunk_size]
        # Create a proper mock chunk object
        class MockChunk:
            def __init__(self, content):
                self.content = content
            
            def model_dump(self):
                return {
                    "choices": [{
                        "delta": {
                            "content": self.content
                        }
                    }]
                }
        
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
    test_text = "Here is an equation: \\[x^2 + y^2 = z^2\\] and inline math \\(a = b\\)."
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
    final_result = ''.join(result_chunks)
    
    print(f"Input:    {test_text}")
    print(f"Expected: {expected_final}")
    print(f"Result:   {final_result}")
    print(f"Chunks:   {len(result_chunks)} chunks")

    print(f"✓ PASS" if final_result == expected_final else "✗ FAIL")
    
    # Test 3: Word-by-word streaming
    print("\n3. Word-by-Word Streaming Test:")
    words = test_text.split(' ')
    word_chunks = []
    for word in words:
        class WordMockChunk:
            def __init__(self, content):
                self.content = content
            
            def model_dump(self):
                return {
                    "choices": [{
                        "delta": {
                            "content": self.content
                        }
                    }]
                }
        word_chunks.append(WordMockChunk(word + " "))
    
    result_chunks = list(stream_with_math_formatting(word_chunks))
    final_result = ''.join(result_chunks).rstrip()
    
    print(f"Input:    {test_text}")
    print(f"Expected: {expected_final}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_final else "✗ FAIL")
    
    # Test 4: Boundary condition - pattern split across chunks
    print("\n4. Boundary Condition Test (Pattern Split):")
    # Create chunks that split the pattern \\[ across boundaries
    class BoundaryMockChunk:
        def __init__(self, content):
            self.content = content
        
        def model_dump(self):
            return {
                "choices": [{
                    "delta": {
                        "content": self.content
                    }
                }]
            }
    
    boundary_chunks = [
        BoundaryMockChunk("Start \\"),
        BoundaryMockChunk("[equation\\] end")
    ]
    
    result_chunks = list(stream_with_math_formatting(boundary_chunks))
    final_result = ''.join(result_chunks)
    expected_boundary = "Start \\\\[equation\\\\] end"
    
    print(f"Chunk 1:  'Start \\\\' ")
    print(f"Chunk 2:  '[equation\\\\] end'")
    print(f"Expected: {expected_boundary}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_boundary else "✗ FAIL")
    
    # Test 5: Multiple patterns in sequence
    print("\n5. Multiple Patterns Test:")
    multi_pattern_text = "Equations: \\[a\\] and \\(b\\) then \\]c\\[ mixed"
    expected_multi = "Equations: \\\\[a\\\\] and \\\\(b\\\\) then \\\\]c\\\\[ mixed"
    
    multi_chunks = list(simulate_streaming(multi_pattern_text, chunk_size=3))
    result_chunks = list(stream_with_math_formatting(multi_chunks))
    final_result = ''.join(result_chunks)
    
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
            return {
                "choices": [{
                    "delta": {
                        "content": self.content
                    }
                }]
            }
    
    edge_chunks = [
        EdgeMockChunk("Text with trailing \\"),
        # No more chunks - stream ends
    ]
    
    result_chunks = list(stream_with_math_formatting(edge_chunks))
    final_result = ''.join(result_chunks)
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
            return {
                "choices": [{
                    "delta": {
                        "content": self.content
                    }
                }]
            }
    
    complex_chunks = [
        ComplexMockChunk("Before \\"),
        ComplexMockChunk("( middle content \\) after")
    ]
    
    result_chunks = list(stream_with_math_formatting(complex_chunks))
    final_result = ''.join(result_chunks)
    expected_complex = "Before \\\\( middle content \\\\) after"
    
    print(f"Chunk 1:  'Before \\\\' ")
    print(f"Chunk 2:  '( middle content \\\\) after'")
    print(f"Expected: {expected_complex}")
    print(f"Result:   {final_result}")
    print(f"✓ PASS" if final_result == expected_complex else "✗ FAIL")
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60) 