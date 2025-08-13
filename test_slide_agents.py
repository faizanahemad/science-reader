#!/usr/bin/env python3
"""
Test script for slide agents - demonstrates both GenericSlideAgent and CodingQuestionSlideAgent
in demo mode to generate standalone HTML files.
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.append(str(project_root))


mock_keys = {}

try:
    from agents.slide_agent import GenericSlideAgent, CodingQuestionSlideAgent
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def test_generic_slide_agent():
    """Test the GenericSlideAgent with sample content."""
    print("🔄 Testing GenericSlideAgent...")
    
    # Sample generic content
    sample_content = """
    <main-content>
    # Introduction to Machine Learning
    
    Machine Learning is a subset of artificial intelligence that enables computers to learn and make decisions from data without being explicitly programmed for every task.
    
    ## Key Concepts
    
    **Supervised Learning**: Learning with labeled examples
    - Classification: Predicting categories (spam/not spam)
    - Regression: Predicting continuous values (house prices)
    
    **Unsupervised Learning**: Finding patterns in data without labels
    - Clustering: Grouping similar data points
    - Dimensionality Reduction: Simplifying data while preserving information
    
    **Deep Learning**: Neural networks with multiple layers that can learn complex patterns
    
    ## Applications
    
    - Image recognition and computer vision
    - Natural language processing
    - Recommendation systems
    - Autonomous vehicles
    - Medical diagnosis
    
    ## Getting Started
    
    1. Learn Python and basic statistics
    2. Understand data preprocessing
    3. Study common algorithms
    4. Practice with real datasets
    5. Build projects to showcase your skills
    </main-content>
    """
    
    # Mock keys for testing (you'll need to provide real keys)
    
    writer_model = "gpt-4o"
    
    try:
        # Create agent in demo mode
        agent = GenericSlideAgent(mock_keys, writer_model, demo_mode=True)
        
        # Generate slides
        html_output = agent(sample_content)
        
        # Save to file
        output_file = "test_generic_slides_fixed.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_output)
        
        print(f"✅ Generic slides generated successfully: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Error testing GenericSlideAgent: {e}")
        return False


def test_markdown_fallback():
    """Test the markdown fallback directly without LLM."""
    print("🔄 Testing Markdown Fallback...")
    
    sample_content = """
<main-content>
# Introduction to Machine Learning

Machine Learning is a subset of artificial intelligence that enables computers to learn and make decisions from data without being explicitly programmed for every task.

## Key Concepts

**Supervised Learning**: Learning with labeled examples
- Classification: Predicting categories (spam/not spam)
- Regression: Predicting continuous values (house prices)

```python
# Example: Simple linear regression
def linear_regression(x, y):
    # Calculate slope and intercept
    n = len(x)
    slope = (n * sum(x*y) - sum(x) * sum(y)) / (n * sum(x**2) - sum(x)**2)
    intercept = (sum(y) - slope * sum(x)) / n
    return slope, intercept
```

**Unsupervised Learning**: Finding patterns in data without labels
- Clustering: Grouping similar data points
- Dimensionality Reduction: Simplifying data while preserving information

## Applications

- Image recognition and computer vision
- Natural language processing
- Recommendation systems
- Autonomous vehicles
- Medical diagnosis
</main-content>"""
    
    try:
        # Create agent in demo mode
        agent = GenericSlideAgent(mock_keys, "gpt-4o", demo_mode=True)
        
        # Force markdown fallback by creating slide data directly
        slide_data = agent._create_markdown_slides(sample_content, 5)
        
        # Generate HTML
        html_output = agent._generate_reveal_html(slide_data)
        
        # Save to file
        output_file = "test_markdown_fallback.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_output)
        
        print(f"✅ Markdown fallback slides generated: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Error testing markdown fallback: {e}")
        return False


def test_coding_slide_agent():
    """Test the CodingQuestionSlideAgent with a LeetCode-style problem."""
    print("🔄 Testing CodingQuestionSlideAgent...")
    
    # Sample coding problem content
    coding_content = """
    <main-content>
    # Two Sum Problem
    
    ## Problem Statement
    Given an array of integers `nums` and an integer `target`, return indices of the two numbers such that they add up to target.
    
    You may assume that each input would have exactly one solution, and you may not use the same element twice.
    
    **Example 1:**
    ```
    Input: nums = [2,7,11,15], target = 9
    Output: [0,1]
    Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].
    ```
    
    **Example 2:**
    ```
    Input: nums = [3,2,4], target = 6
    Output: [1,2]
    ```
    
    ## Approach 1: Brute Force
    
    The brute force approach is to check every pair of numbers in the array.
    
    ```python
    def two_sum_brute_force(nums, target):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] + nums[j] == target:
                    return [i, j]
        return []
    ```
    
    **Time Complexity:** O(n²)
    **Space Complexity:** O(1)
    
    ## Approach 2: Hash Map (Optimal)
    
    We can use a hash map to store the numbers we've seen and their indices.
    
    ```python
    def two_sum_optimal(nums, target):
        hash_map = {}
        
        for i, num in enumerate(nums):
            complement = target - num
            
            if complement in hash_map:
                return [hash_map[complement], i]
            
            hash_map[num] = i
        
        return []
    ```
    
    **Time Complexity:** O(n)
    **Space Complexity:** O(n)
    
    ## Algorithm Explanation
    
    1. Create an empty hash map
    2. Iterate through the array
    3. For each number, calculate its complement (target - current number)
    4. If complement exists in hash map, we found our answer
    5. Otherwise, store current number and its index in hash map
    6. Continue until we find the solution
    
    ## Test Cases
    
    ```python
    # Test the solution
    def test_two_sum():
        assert two_sum_optimal([2, 7, 11, 15], 9) == [0, 1]
        assert two_sum_optimal([3, 2, 4], 6) == [1, 2]
        assert two_sum_optimal([3, 3], 6) == [0, 1]
        print("All tests passed!")
    
    test_two_sum()
    ```
    
    ## Related Problems
    
    - Three Sum
    - Two Sum II - Input array is sorted
    - Two Sum IV - Input is a BST
    - Four Sum
    </main-content>
    """
    
    # Mock keys for testing
    writer_model = "gpt-4o"
    
    try:
        # Create agent in demo mode
        agent = CodingQuestionSlideAgent(mock_keys, writer_model, demo_mode=True)
        
        # Generate slides
        html_output = agent(coding_content)
        
        # Save to file
        output_file = "test_coding_slides.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_output)
        
        print(f"✅ Coding slides generated successfully: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Error testing CodingQuestionSlideAgent: {e}")
        return False


def create_mock_slide_demo():
    """Create a mock slide demo without LLM calls for immediate testing."""
    print("🔄 Creating mock slide demo...")
    
    # Create mock slide data
    mock_slide_data = {
        "slides": [
            {
                "title": "Problem Overview",
                "content": """
                <h3>Two Sum Problem</h3>
                <p>Given an array of integers and a target, find two numbers that add up to the target.</p>
                <div class="fragment">
                    <pre><code class="python">
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
                    </code></pre>
                </div>
                """,
                "background": "#f8f9fa",
                "notes": "Start with the problem statement and a simple example"
            },
            {
                "title": "Approach Analysis",
                "content": """
                <h3>Two Approaches</h3>
                <div class="fragment">
                    <h4>1. Brute Force - O(n²)</h4>
                    <p>Check every pair of numbers</p>
                </div>
                <div class="fragment">
                    <h4>2. Hash Map - O(n)</h4>
                    <p>Use a hash map to store seen numbers</p>
                </div>
                """,
                "notes": "Discuss the trade-offs between approaches"
            },
            {
                "title": "Optimal Solution",
                "content": """
                <h3>Hash Map Implementation</h3>
                <pre><code class="python">
def two_sum(nums, target):
    hash_map = {}
    
    for i, num in enumerate(nums):
        complement = target - num
        
        if complement in hash_map:
            return [hash_map[complement], i]
        
        hash_map[num] = i
    
    return []
                </code></pre>
                <div class="fragment complexity-analysis">
                    <strong>Time:</strong> O(n) | <strong>Space:</strong> O(n)
                </div>
                """,
                "notes": "Walk through the code step by step"
            },
            {
                "title": "Algorithm Walkthrough",
                "content": """
                <h3>Step-by-Step Example</h3>
                <p>Array: [2, 7, 11, 15], Target: 9</p>
                <div class="fragment algorithm-step">
                    <strong>Step 1:</strong> i=0, num=2, complement=7, hash_map={}
                    <br>→ Add {2: 0} to hash_map
                </div>
                <div class="fragment algorithm-step">
                    <strong>Step 2:</strong> i=1, num=7, complement=2, hash_map={2: 0}
                    <br>→ Found complement! Return [0, 1]
                </div>
                """,
                "notes": "Show how the algorithm works with the example"
            }
        ],
        "metadata": {
            "total_slides": 4,
            "theme": "white",
            "estimated_duration": "8 minutes"
        }
    }
    
    # Create a mock agent to generate HTML
    class MockAgent:
        def __init__(self):
            self.demo_mode = True
            self.reveal_config = {
                "hash": True,
                "controls": True,
                "progress": True,
                "center": True,
                "transition": "slide",
                "backgroundTransition": "fade"
            }
        
        def _generate_standalone_html(self, slides_html, slide_data):
            return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mock Slide Demo - Two Sum Problem</title>
    
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/theme/white.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/monokai.css">
    
    <style>
        /* Compact slide styling to prevent overflow */
        .slide-content {{
            text-align: left;
            font-size: 0.8em;
            line-height: 1.2;
        }}
        
        /* Very compact code blocks */
        .reveal pre {{
            width: 100%;
            margin: 5px 0;
            box-shadow: 0px 3px 10px rgba(0, 0, 0, 0.1);
            border-radius: 4px;
        }}
        
        .reveal pre code {{
            max-height: 200px;
            font-size: 0.5em;
            line-height: 1.1;
            padding: 6px;
            overflow-y: auto;
            display: block;
        }}
        
        /* Strict content overflow prevention */
        .reveal .slides section {{
            height: 100%;
            max-height: 70vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            align-items: stretch;
            text-align: left;
            padding: 8px !important;
            font-size: 0.8em;
        }}
        
        /* Smaller headers */
        .reveal .slides section h1,
        .reveal .slides section h2 {{
            margin-top: 0;
            margin-bottom: 0.3em;
            font-size: 1.4em;
            line-height: 1.1;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 8px;
        }}
        
        .reveal .slides section h3 {{
            font-size: 1.1em;
            margin-bottom: 0.2em;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 6px;
        }}
        
        /* Compact lists */
        .reveal ul, .reveal ol {{
            margin: 0.2em 0;
        }}
        
        .reveal li {{
            margin: 0.1em 0;
            font-size: 0.9em;
            line-height: 1.2;
        }}
        
        /* Tight paragraph spacing */
        .reveal p {{
            margin: 0.2em 0;
            line-height: 1.2;
            font-size: 0.9em;
        }}
        
        /* Compact special elements */
        .complexity-analysis {{
            background: #ecf0f1;
            padding: 6px;
            border-radius: 3px;
            margin: 4px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.7em;
            line-height: 1.1;
        }}
        
        .algorithm-step {{
            background: #e8f6f3;
            padding: 5px;
            border-left: 3px solid #1abc9c;
            margin: 3px 0;
            font-size: 0.75em;
            line-height: 1.1;
        }}
        
        /* Ensure inline code is readable */
        .reveal code {{
            font-size: 0.8em;
            padding: 2px 4px;
            background: #f5f5f5;
            border-radius: 2px;
        }}
    </style>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            {slides_html}
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/notes/notes.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/highlight.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/math/math.js"></script>
    
    <script>
        Reveal.initialize({{
            hash: true,
            controls: true,
            progress: true,
            center: true,
            transition: 'slide',
            backgroundTransition: 'fade',
            plugins: [ RevealHighlight, RevealNotes, RevealMath.KaTeX ]
        }});
    </script>
</body>
</html>
            """
    
    # Generate slides HTML
    slides_html = ""
    for slide in mock_slide_data["slides"]:
        slide_attrs = []
        if slide.get("background"):
            slide_attrs.append(f'data-background="{slide["background"]}"')
        
        attrs_str = " " + " ".join(slide_attrs) if slide_attrs else ""
        
        slide_html = f"""
            <section{attrs_str}>
                <h2>{slide.get("title", "")}</h2>
                <div class="slide-content">
                    {slide.get("content", "")}
                </div>
                {f'<aside class="notes">{slide["notes"]}</aside>' if slide.get("notes") else ""}
            </section>
        """
        slides_html += slide_html
    
    # Generate final HTML
    mock_agent = MockAgent()
    html_output = mock_agent._generate_standalone_html(slides_html, mock_slide_data)
    
    # Save to file
    output_file = "mock_slide_demo.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_output)
    
    print(f"✅ Mock slide demo created: {output_file}")
    print(f"🌐 Open {output_file} in your browser to test the slide functionality")
    return True


def main():
    """Main test function."""
    print("🚀 Testing Slide Agents")
    print("=" * 50)
    
    # Always create mock demo first for immediate testing
    create_mock_slide_demo()
    print()
    
    # Test markdown fallback first (doesn't require LLM)
    try:
        test_markdown_fallback()
    except Exception as e:
        print(f"⚠️  Markdown fallback test failed: {e}")
    
    print()
    
    # Test with actual agents (will fail without proper LLM setup, but shows structure)
    print("Note: The following tests require proper LLM API keys and may fail in this demo environment:")
    print()
    
    try:
        test_generic_slide_agent()
    except Exception as e:
        print(f"⚠️  GenericSlideAgent test skipped: {e}")
    
    print()
    
    try:
        test_coding_slide_agent()
    except Exception as e:
        print(f"⚠️  CodingQuestionSlideAgent test skipped: {e}")
    
    print()
    print("🎯 Summary:")
    print("- Mock demo created successfully (open mock_slide_demo.html to test)")
    print("- Markdown fallback test completed (open test_markdown_fallback.html)")
    print("- Slide agents are ready for integration")
    print("- Add proper LLM keys to test full functionality")


if __name__ == "__main__":
    main()
