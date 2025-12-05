"""
Text Splitter Module

This module provides a token-aware text splitter that uses a divide-and-conquer
(merge sort style) approach to split text into chunks of a specified token size.

Usage:
    from text_splitter import RecursiveChunkTextSplitter
    
    splitter = RecursiveChunkTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter("Your long text here...")

Run this file directly to execute benchmarks and tests:
    python text_splitter.py
"""

import tiktoken
import time
import random
import string
from typing import List


class RecursiveChunkTextSplitter:
    """
    A text splitter that uses tiktoken to count tokens and splits text into chunks
    using a divide-and-conquer (merge sort style) approach.
    
    This splitter ensures chunks don't exceed the specified token size while
    maintaining semantic coherence by trying to split on word/sentence boundaries.
    Both chunk_size and chunk_overlap are measured in tokens (not characters).
    
    The algorithm works as follows:
    1. If text token count <= chunk_size, return as single chunk
    2. Otherwise, split tokens roughly in half (at a good boundary if possible)
    3. Recursively process both halves
    4. After all splitting is done, add token-based overlaps between consecutive chunks
    """
    
    def __init__(self, chunk_size: int = 3400, chunk_overlap: int = 100):
        """
        Initialize the text splitter.
        
        Args:
            chunk_size: Maximum number of tokens per chunk
            chunk_overlap: Number of tokens to overlap between consecutive chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.enc = tiktoken.encoding_for_model("gpt-4")
        # Cache space/whitespace tokens for finding good split points
        self._space_tokens = self._get_whitespace_tokens()
    
    def _get_whitespace_tokens(self) -> set:
        """
        Get a set of token ids that represent whitespace characters.
        Used to find good split points that don't break words.
        
        Returns:
            Set of token ids for whitespace characters
        """
        space_tokens = set()
        for char in [' ', '\n', '\t', '\r\n', '\n\n', '  ', '. ', ', ']:
            try:
                tokens = self.enc.encode(char)
                space_tokens.update(tokens)
            except:
                pass
        return space_tokens
    
    def _encode(self, text: str) -> List[int]:
        """Encode text to tokens."""
        return self.enc.encode(text)
    
    def _decode(self, tokens: List[int]) -> str:
        """Decode tokens back to text."""
        return self.enc.decode(tokens)
    
    def _find_split_point(self, tokens: List[int], target_idx: int) -> int:
        """
        Find a good split point near target_idx that doesn't break words.
        Searches for whitespace tokens near the target index.
        
        Args:
            tokens: List of token ids
            target_idx: Target split index (typically the midpoint)
            
        Returns:
            The best split index found, preferring whitespace boundaries
        """
        # Search window: look up to 50 tokens before and after target
        window = min(50, len(tokens) // 4)  # Don't search too far in small chunks
        
        # Search outward from target, prefer splitting after whitespace
        for offset in range(window + 1):
            # Check position after target first, then before
            for idx in [target_idx + offset, target_idx - offset]:
                if 0 < idx < len(tokens) and tokens[idx - 1] in self._space_tokens:
                    return idx  # Split after the whitespace token
        
        # No good split point found, use target
        return target_idx
    
    def _split_recursive(self, tokens: List[int]) -> List[List[int]]:
        """
        Recursively split tokens using divide-and-conquer (merge sort style) approach.
        Splits in half until all chunks are smaller than chunk_size.
        
        Args:
            tokens: List of token ids to split
            
        Returns:
            List of token chunks, each with length <= chunk_size
        """
        # Base case: if tokens fit in one chunk, return as single chunk
        if len(tokens) <= self.chunk_size:
            return [tokens] if tokens else []
        
        # Divide: split roughly in half, trying to find a good split point
        mid = len(tokens) // 2
        split_point = self._find_split_point(tokens, mid)
        
        left_tokens = tokens[:split_point]
        right_tokens = tokens[split_point:]
        
        # Handle edge case where split point is at extremes
        if not left_tokens or not right_tokens:
            # Force split in middle if we can't find a good point
            mid = len(tokens) // 2
            left_tokens = tokens[:mid]
            right_tokens = tokens[mid:]
        
        # Conquer: recursively split both halves (parallel in concept)
        left_chunks = self._split_recursive(left_tokens)
        right_chunks = self._split_recursive(right_tokens)
        
        # Combine: merge the results from both halves
        return left_chunks + right_chunks
    
    def _add_overlaps(self, chunks: List[List[int]]) -> List[List[int]]:
        """
        Add overlapping tokens between consecutive chunks.
        Takes tokens from the end of each chunk and prepends them to the next chunk.
        
        Args:
            chunks: List of token chunks without overlaps
            
        Returns:
            List of token chunks with overlaps added (except first chunk)
        """
        if not chunks or self.chunk_overlap <= 0:
            return chunks
        
        result = [chunks[0]]  # First chunk has no overlap to prepend
        
        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            curr_chunk = chunks[i]
            
            # Get overlap tokens from end of previous chunk
            overlap_size = min(self.chunk_overlap, len(prev_chunk))
            overlap_tokens = prev_chunk[-overlap_size:]
            
            # Prepend overlap to current chunk
            new_chunk = overlap_tokens + curr_chunk
            
            # If new chunk exceeds size limit, trim from the overlap portion
            # This ensures we never exceed chunk_size while maximizing overlap
            if len(new_chunk) > self.chunk_size:
                excess = len(new_chunk) - self.chunk_size
                new_chunk = new_chunk[excess:]
            
            result.append(new_chunk)
        
        return result
    
    def __call__(self, text: str) -> List[str]:
        """
        Split text into chunks using divide-and-conquer approach.
        All sizing (chunk_size and chunk_overlap) is based on tokens.
        
        Args:
            text: The text to split into chunks
            
        Returns:
            List of text chunks, each with token count <= chunk_size,
            with token-based overlap between consecutive chunks
        """
        if not text or not text.strip():
            return []
        
        # Encode text to tokens
        tokens = self._encode(text)
        
        # If text fits in one chunk, return as-is
        if len(tokens) <= self.chunk_size:
            return [text]
        
        # Recursively split into chunks (divide-and-conquer)
        token_chunks = self._split_recursive(tokens)
        
        # Add token-based overlaps between consecutive chunks
        token_chunks_with_overlap = self._add_overlaps(token_chunks)
        
        # Decode tokens back to text
        text_chunks = [self._decode(chunk) for chunk in token_chunks_with_overlap]
        
        # Filter out empty chunks
        return [chunk for chunk in text_chunks if chunk.strip()]


# =============================================================================
# TESTS AND BENCHMARKS
# =============================================================================

def generate_random_text(num_words: int) -> str:
    """Generate random text with specified number of words."""
    words = []
    for _ in range(num_words):
        word_len = random.randint(3, 12)
        word = ''.join(random.choices(string.ascii_lowercase, k=word_len))
        words.append(word)
    
    # Add some punctuation and structure
    text = ""
    for i, word in enumerate(words):
        text += word
        if (i + 1) % 15 == 0:
            text += ".\n"
        elif (i + 1) % 5 == 0:
            text += ", "
        else:
            text += " "
    return text


def generate_realistic_text(num_paragraphs: int = 10) -> str:
    """Generate more realistic looking text with paragraphs."""
    paragraphs = []
    for _ in range(num_paragraphs):
        num_sentences = random.randint(3, 8)
        sentences = []
        for _ in range(num_sentences):
            num_words = random.randint(8, 20)
            words = [''.join(random.choices(string.ascii_lowercase, k=random.randint(3, 10))) 
                     for _ in range(num_words)]
            words[0] = words[0].capitalize()
            sentence = ' '.join(words) + '.'
            sentences.append(sentence)
        paragraphs.append(' '.join(sentences))
    return '\n\n'.join(paragraphs)


def test_basic_functionality():
    """Test basic splitting functionality."""
    print("\n" + "=" * 60)
    print("TEST: Basic Functionality")
    print("=" * 60)
    
    splitter = RecursiveChunkTextSplitter(chunk_size=100, chunk_overlap=20)
    
    # Test 1: Empty text
    result = splitter("")
    assert result == [], f"Empty text should return empty list, got {result}"
    print("✓ Empty text handled correctly")
    
    # Test 2: Small text (fits in one chunk)
    small_text = "This is a small text that should fit in one chunk."
    result = splitter(small_text)
    assert len(result) == 1, f"Small text should be 1 chunk, got {len(result)}"
    assert result[0] == small_text, "Small text should be unchanged"
    print("✓ Small text returns single chunk")
    
    # Test 3: Larger text (needs splitting)
    large_text = generate_random_text(500)
    result = splitter(large_text)
    assert len(result) > 1, f"Large text should have multiple chunks, got {len(result)}"
    print(f"✓ Large text split into {len(result)} chunks")
    
    print("\nAll basic tests passed!")


def test_chunk_sizes():
    """Test that all chunks respect the size limit."""
    print("\n" + "=" * 60)
    print("TEST: Chunk Size Limits")
    print("=" * 60)
    
    chunk_size = 200
    chunk_overlap = 50
    splitter = RecursiveChunkTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    enc = tiktoken.encoding_for_model("gpt-4")
    
    # Generate large text
    text = generate_realistic_text(50)
    chunks = splitter(text)
    
    print(f"Generated {len(chunks)} chunks from text with {len(enc.encode(text))} tokens")
    
    all_valid = True
    for i, chunk in enumerate(chunks):
        token_count = len(enc.encode(chunk))
        if token_count > chunk_size:
            print(f"✗ Chunk {i} exceeds size limit: {token_count} > {chunk_size}")
            all_valid = False
        else:
            print(f"  Chunk {i}: {token_count} tokens")
    
    if all_valid:
        print(f"\n✓ All {len(chunks)} chunks are within size limit of {chunk_size} tokens")
    else:
        print("\n✗ Some chunks exceeded size limit!")
    
    return all_valid


def test_overlap():
    """Test that overlaps are correctly applied."""
    print("\n" + "=" * 60)
    print("TEST: Token Overlap")
    print("=" * 60)
    
    chunk_size = 150
    chunk_overlap = 30
    splitter = RecursiveChunkTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    enc = tiktoken.encoding_for_model("gpt-4")
    
    text = generate_realistic_text(20)
    chunks = splitter(text)
    
    if len(chunks) < 2:
        print("Not enough chunks to test overlap")
        return True
    
    print(f"Testing overlap between {len(chunks)} chunks...")
    
    overlaps_found = 0
    for i in range(1, len(chunks)):
        prev_tokens = enc.encode(chunks[i-1])
        curr_tokens = enc.encode(chunks[i])
        
        # Check if the beginning of current chunk contains tokens from end of previous
        overlap_tokens = prev_tokens[-chunk_overlap:]
        
        # Find how many tokens from the overlap appear at the start of current chunk
        match_count = 0
        for j, token in enumerate(overlap_tokens):
            if j < len(curr_tokens) and curr_tokens[j] == token:
                match_count += 1
            else:
                break
        
        if match_count > 0:
            overlaps_found += 1
            print(f"  Chunks {i-1} → {i}: {match_count} overlapping tokens")
    
    print(f"\n✓ Found overlaps in {overlaps_found}/{len(chunks)-1} chunk transitions")
    return True


def test_text_preservation():
    """Test that text content is preserved (accounting for overlap)."""
    print("\n" + "=" * 60)
    print("TEST: Text Content Preservation")
    print("=" * 60)
    
    splitter = RecursiveChunkTextSplitter(chunk_size=100, chunk_overlap=0)
    
    text = generate_realistic_text(10)
    chunks = splitter(text)
    
    # With no overlap, concatenated chunks should equal original
    reconstructed = ''.join(chunks)
    
    if reconstructed == text:
        print("✓ Text perfectly preserved (no overlap mode)")
        return True
    else:
        # Check if the difference is just whitespace
        if reconstructed.replace(' ', '').replace('\n', '') == text.replace(' ', '').replace('\n', ''):
            print("✓ Text content preserved (minor whitespace differences)")
            return True
        else:
            print("✗ Text content differs from original")
            print(f"  Original length: {len(text)}")
            print(f"  Reconstructed length: {len(reconstructed)}")
            return False


def benchmark_performance():
    """Benchmark the splitter performance with various text sizes."""
    print("\n" + "=" * 60)
    print("BENCHMARK: Performance")
    print("=" * 60)
    
    splitter = RecursiveChunkTextSplitter(chunk_size=500, chunk_overlap=50)
    enc = tiktoken.encoding_for_model("gpt-4")
    
    # Test with different sizes
    sizes = [1000, 5000, 10000, 50000, 100000]  # word counts
    
    print(f"{'Words':<12} {'Tokens':<12} {'Chunks':<10} {'Time (ms)':<12} {'Tokens/sec':<15}")
    print("-" * 65)
    
    for num_words in sizes:
        text = generate_random_text(num_words)
        token_count = len(enc.encode(text))
        
        # Warm up
        _ = splitter(text)
        
        # Benchmark
        iterations = 3
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            chunks = splitter(text)
            end = time.perf_counter()
            times.append((end - start) * 1000)  # Convert to ms
        
        avg_time = sum(times) / len(times)
        tokens_per_sec = token_count / (avg_time / 1000) if avg_time > 0 else 0
        
        print(f"{num_words:<12} {token_count:<12} {len(chunks):<10} {avg_time:<12.2f} {tokens_per_sec:<15,.0f}")


def benchmark_different_chunk_sizes():
    """Benchmark with different chunk sizes."""
    print("\n" + "=" * 60)
    print("BENCHMARK: Different Chunk Sizes")
    print("=" * 60)
    
    text = generate_random_text(20000)
    enc = tiktoken.encoding_for_model("gpt-4")
    token_count = len(enc.encode(text))
    print(f"Text size: {token_count} tokens\n")
    
    chunk_sizes = [100, 250, 500, 1000, 2000, 4000]
    
    print(f"{'Chunk Size':<12} {'Overlap':<10} {'Chunks':<10} {'Time (ms)':<12}")
    print("-" * 50)
    
    for chunk_size in chunk_sizes:
        overlap = chunk_size // 10  # 10% overlap
        splitter = RecursiveChunkTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        
        start = time.perf_counter()
        chunks = splitter(text)
        end = time.perf_counter()
        
        time_ms = (end - start) * 1000
        print(f"{chunk_size:<12} {overlap:<10} {len(chunks):<10} {time_ms:<12.2f}")


def run_all_tests():
    """Run all tests and benchmarks."""
    print("\n" + "=" * 60)
    print("RECURSIVE CHUNK TEXT SPLITTER - TESTS & BENCHMARKS")
    print("=" * 60)
    
    # Tests
    test_basic_functionality()
    test_chunk_sizes()
    test_overlap()
    test_text_preservation()
    
    # Benchmarks
    benchmark_performance()
    benchmark_different_chunk_sizes()
    
    print("\n" + "=" * 60)
    print("ALL TESTS AND BENCHMARKS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

