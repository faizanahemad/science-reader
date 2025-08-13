"""
Slide generation agents using Reveal.js for creating interactive presentations.

This module contains agents that convert content into slide-based presentations
using Reveal.js framework. Includes both generic slide generation and 
specialized coding interview slide generation.
"""

import json
import re
import random
from typing import Dict, List, Union, Optional

from common import CHEAP_LONG_CONTEXT_LLM
from .base_agent import Agent

# Import LLM calling infrastructure
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from base import CallLLm
    from very_common import get_async_future
    import markdown
    from markdown.extensions import codehilite
except ImportError as e:
    print(f"Import error in slide_agent: {e}")
    # Try to import markdown without extensions as fallback
    try:
        import markdown
    except ImportError:
        print("Warning: markdown library not available. Code formatting may be limited.")
        markdown = None
    raise

# Configuration: choose how content is authored and post-processed.
# 'html'  -> LLM is prompted to produce HTML; light HTML post-processing
# 'markdown' -> LLM is prompted to produce Markdown; we convert to HTML
DEFAULT_CONTENT_MODE = 'html'  # can be 'html' or 'markdown'
ENABLE_SERVER_SIDE_MATH = True  # try KaTeX server-side; keep client fallback
# IMPORTANT: by default do NOT touch indentation produced by the LLM.
# Only flip this to True if you want the heuristic re-indenter to run.
REPAIR_CODE_INDENTATION = False


class SlideAgent(Agent):
    """
    Base class for slide generation agents using Reveal.js.
    
    This agent converts content into interactive slide presentations,
    with support for both standalone HTML generation (demo mode) and 
    embedded HTML for integration into existing interfaces.
    """
    
    def __init__(self, keys, writer_model: Union[List[str], str], demo_mode: bool = True,
                 content_mode: Optional[str] = None):
        """
        Initialize the SlideAgent.
        
        Args:
            keys: API keys for LLM access
            writer_model: Model(s) to use for content generation
            demo_mode: If True, generates complete standalone HTML with Reveal.js imports.
                      If False, generates only slide content for embedding.
        """
        super().__init__(keys)
        self.writer_model = writer_model
        self.demo_mode = demo_mode
        self.content_mode = (content_mode or DEFAULT_CONTENT_MODE).lower()
        if self.content_mode not in { 'html', 'markdown' }:
            self.content_mode = 'html'
        
        # Reveal.js configuration
        self.reveal_config = {
            "hash": True,
            "controls": True,
            "progress": True,
            "center": True,
            "transition": "slide",
            "backgroundTransition": "fade",
            "theme": "white"
        }
        
        
        
        # Base slide generation prompt (mode-dependent). We'll format per-call.
        self.base_slide_prompt = None

    

    def _convert_markdown_to_html(self, content: str) -> str:
        """
        Convert markdown content to HTML, especially handling code blocks.
        
        Args:
            content: Markdown content to convert
            
        Returns:
            HTML content with proper code block formatting
        """
        if markdown is None:
            # Fallback: basic conversion without markdown library
            return self._basic_markdown_conversion(content)
        
        try:
            # Configure markdown with code highlighting
            md = markdown.Markdown(extensions=[
                'codehilite',
                'fenced_code',
                'tables',
                'nl2br'
            ])
            html_content = md.convert(content)
            
            # Post-process to ensure Reveal.js compatible code blocks
            html_content = self._fix_code_blocks(html_content)
            
            return html_content
            
        except Exception as e:
            print(f"Error converting markdown: {e}")
            return self._basic_markdown_conversion(content)
    
    def _basic_markdown_conversion(self, content: str) -> str:
        """
        Basic markdown to HTML conversion without external libraries.
        
        Args:
            content: Markdown content
            
        Returns:
            Basic HTML conversion
        """
        # Convert code blocks (```language to <pre><code class="language">)
        content = re.sub(
            r'```(\w+)?\n(.*?)\n```',
            lambda m: f'<pre><code class="{m.group(1) or "plaintext"}">{m.group(2)}</code></pre>',
            content,
            flags=re.DOTALL
        )
        
        # Convert inline code
        content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
        
        # Convert headers
        content = re.sub(r'^### (.*$)', r'<h3>\1</h3>', content, flags=re.MULTILINE)
        content = re.sub(r'^## (.*$)', r'<h2>\1</h2>', content, flags=re.MULTILINE)
        content = re.sub(r'^# (.*$)', r'<h1>\1</h1>', content, flags=re.MULTILINE)
        
        # Convert bold and italic
        content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.*?)\*', r'<em>\1</em>', content)
        
        # Convert line breaks to <br> or <p>
        content = re.sub(r'\n\n', '</p><p>', content)
        content = re.sub(r'\n', '<br>', content)
        content = f'<p>{content}</p>'
        
        return content
    
    def _fix_code_blocks(self, html_content: str) -> str:
        """
        Fix code blocks to be compatible with Reveal.js highlighting.
        
        Args:
            html_content: HTML content with code blocks
            
        Returns:
            Fixed HTML content
        """
        # Fix codehilite classes to be compatible with Reveal.js
        html_content = re.sub(
            r'<div class="codehilite"><pre><code class="language-(\w+)"',
            r'<pre><code class="\1"',
            html_content
        )
        
        # Remove closing div tags from codehilite
        html_content = re.sub(r'</code></pre></div>', r'</code></pre>', html_content)
        
        # Ensure Python code blocks have proper class
        html_content = re.sub(
            r'<code class="language-python"',
            r'<code class="python"',
            html_content
        )
        
        return html_content

    def _generate_slide_content_two_stage(self, content: str, slide_count: Union[int, str]) -> Dict:
        """
        Generate slide content using a two-stage approach:
        Stage 1: Generate structured storyboard 
        Stage 2: Parallel generation of individual slides
        
        Args:
            content: Content to convert to slides
            slide_count: Number of slides to generate
            
        Returns:
            Dictionary containing slide data
        """
        print(f"[SlideAgent] Starting two-stage slide generation...")
        
        # Stage 1: Generate storyboard
        storyboard = self._generate_storyboard(content, slide_count)
        print(f"[SlideAgent] Stage 1 complete: {len(storyboard)} slides planned")
        
        # Stage 2: Generate slides in parallel
        slides = self._generate_slides_parallel(content, storyboard)
        print(f"[SlideAgent] Stage 2 complete: {len(slides)} slides generated")
        
        return {
            "slides": slides,
            "metadata": {
                "total_slides": len(slides),
                "theme": "white",
                "estimated_duration": len(slides) * 2,
                "generation_method": "two_stage_parallel"
            }
        }
    
    def _generate_storyboard(self, content: str, slide_count: Union[int, str]) -> List[tuple]:
        """
        Stage 1: Generate structured storyboard as parseable Python array of tuples.
        
        Args:
            content: Content to analyze
            slide_count: Number of slides to generate
            
        Returns:
            List of tuples: (slide_title, slide_brief_description)
        """
        prompt = f"""
You are an expert presentation designer creating a storyboard for slides.

Analyze the following content and create a structured storyboard for approximately {slide_count} slides.

Content to analyze:
{content}

Your task:
1. Break down the content into logical, engaging slide topics
2. Create MORE slides with LESS content per slide for better readability
3. Each slide should focus on ONE specific concept or idea
4. Aim for 12-20 slides total to ensure content is well-distributed
5. Cover the content within <main-content> tags if present
6. Ignore conversation history, focus only on the main content

Respond with ONLY a Python list of tuples in this EXACT format:
[
    ("Slide Title 1", "Brief description of what this slide should cover"),
    ("Slide Title 2", "Brief description of what this slide should cover"),
    ("Slide Title 3", "Brief description of what this slide should cover")
]

CRITICAL: 
- Output must be valid Python syntax that can be parsed with eval()
- Use double quotes for strings
- Each tuple has exactly 2 elements: (title, description)
- Keep titles concise (1-4 words)
- Keep descriptions brief but informative (1-2 sentences)
- PRIORITIZE creating more slides with focused, bite-sized content
"""
        
        response = self.get_model_response(prompt, temperature=0.3)
        
        try:
            # Parse the Python list of tuples
            # Clean up the response to ensure it's valid Python
            response_clean = response.strip()
            if response_clean.startswith('```python'):
                response_clean = response_clean.split('```python')[1].split('```')[0].strip()
            elif response_clean.startswith('```'):
                response_clean = response_clean.split('```')[1].split('```')[0].strip()
            
            # Safely evaluate the Python list
            storyboard = eval(response_clean)
            
            # Validate structure
            if not isinstance(storyboard, list):
                raise ValueError("Storyboard must be a list")
            
            for item in storyboard:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise ValueError("Each storyboard item must be a tuple of 2 elements")
            
            return storyboard
            
        except Exception as e:
            print(f"[SlideAgent] Error parsing storyboard: {e}")
            print(f"[SlideAgent] Raw response: {response}")
            
            # Fallback: create basic storyboard
            return self._create_fallback_storyboard(content, slide_count)
    
    def _create_fallback_storyboard(self, content: str, slide_count: Union[int, str]) -> List[tuple]:
        """
        Create a fallback storyboard when parsing fails.
        
        Args:
            content: Content to analyze
            slide_count: Number of slides
            
        Returns:
            List of tuples for storyboard
        """
        numeric_count = slide_count if isinstance(slide_count, int) else 6
        
        # Simple content-based storyboard
        lines = content.strip().split('\n')
        sections = []
        current_section = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('#') and current_section:
                sections.append('\n'.join(current_section))
                current_section = [line]
            else:
                current_section.append(line)
        
        if current_section:
            sections.append('\n'.join(current_section))
        
        # Create storyboard from sections
        storyboard = []
        for i, section in enumerate(sections[:numeric_count]):
            title = f"Slide {i+1}"
            # Try to extract title from content
            section_lines = section.split('\n')
            for line in section_lines:
                if line.startswith('#'):
                    title = line.lstrip('#').strip()
                    break
            
            description = f"Cover content from section {i+1}"
            storyboard.append((title, description))
        
        # Fill remaining slides if needed
        while len(storyboard) < numeric_count:
            storyboard.append((f"Additional Content {len(storyboard)+1}", "Additional information and details"))
        
        return storyboard
    
    def _generate_slides_parallel(self, content: str, storyboard: List[tuple]) -> List[Dict]:
        """
        Stage 2: Generate individual slides in parallel using async futures.
        
        Args:
            content: Original content
            storyboard: List of (title, description) tuples
            
        Returns:
            List of slide dictionaries
        """
        # Create futures for parallel slide generation
        futures = []
        
        for i, (slide_title, slide_description) in enumerate(storyboard):
            future = get_async_future(
                self._generate_single_slide,
                content, slide_title, slide_description, i+1, len(storyboard), storyboard
            )
            futures.append((i, future))
        
        # Collect results
        slides = [None] * len(storyboard)
        
        for i, future in futures:
            try:
                slide_data = future.result(timeout=30)  # 30 second timeout per slide
                slides[i] = slide_data
            except Exception as e:
                print(f"[SlideAgent] Error generating slide {i+1}: {e}")
                # Create fallback slide
                slides[i] = {
                    "title": storyboard[i][0],
                    "content": f"<p>Error generating slide content: {str(e)}</p>",
                    "background": None,
                    "transition": None,
                    "notes": ""
                }
        
        return slides
    
    def _generate_single_slide(self, content: str, slide_title: str, slide_description: str, 
                             slide_number: int, total_slides: int, full_storyboard: List[tuple]) -> Dict:
        """
        Generate content for a single slide.
        
        Args:
            content: Original content
            slide_title: Title for this slide
            slide_description: Description of what this slide should cover
            slide_number: Current slide number (1-indexed)
            total_slides: Total number of slides
            full_storyboard: Complete storyboard for context
            
        Returns:
            Dictionary with slide data
        """
        # Create storyboard context
        storyboard_context = "\n".join([
            f"{i+1}. {title}: {desc}" 
            for i, (title, desc) in enumerate(full_storyboard)
        ])
        
        if self.content_mode == 'markdown':
            prompt = f"""
You are an expert presentation designer. Create content for slide {slide_number} of {total_slides}.

SLIDE ASSIGNMENT:
Title: {slide_title}
Description: {slide_description}

FULL PRESENTATION PLAN:
{storyboard_context}

ORIGINAL CONTENT:
{content}

Your task:
1. Create content specifically for slide {slide_number}: "{slide_title}"
2. Use STRICT Markdown format (no HTML)
3. Use fenced code blocks: ```python, ```javascript, etc.
4. Use LaTeX math: $inline$ or $$block$$ including AMS environments like \\begin{{cases}}
5. Focus only on the assigned slide topic
6. Keep content MINIMAL and focused - maximum 4-6 lines of text
7. Use bullet points for clarity
8. Include only the most essential information

Format your response with the slide content between <slide> tags:

<slide>
### {slide_title}

[Your markdown content here]
</slide>
"""
        else:
            prompt = f"""
You are an expert presentation designer. Create content for slide {slide_number} of {total_slides}.

SLIDE ASSIGNMENT:
Title: {slide_title}
Description: {slide_description}

FULL PRESENTATION PLAN:
{storyboard_context}

ORIGINAL CONTENT:
{content}

Your task:
1. Create content specifically for slide {slide_number}: "{slide_title}"
2. Use clean HTML: <h3>, <p>, <ul>, <li>, <pre><code class="python">
3. Use <div class="fragment"> for progressive disclosure
4. Focus only on the assigned slide topic
5. Keep content MINIMAL and focused - maximum 4-6 lines of text
6. Use bullet points for clarity
7. Include only the most essential information
8. Use LaTeX math in \\( \\) or \\[ \\] including AMS environments like \\begin{{cases}}

Format your response with the slide content between <slide> tags:

<slide>
<h3>{slide_title}</h3>

[Your HTML content here]
</slide>
"""
        
        response = self.get_model_response(prompt, temperature=0.7)
        
        # Extract content from <slide> tags
        slide_content = self._extract_slide_content(response)
        
        # Post-process based on content mode
        if self.content_mode == 'markdown':
            # Convert markdown to HTML
            processed_content = self._convert_markdown_to_html_comprehensive(slide_content)
        else:
            processed_content = self._post_process_slide_data_single(slide_content)
        
        return {
            "title": slide_title,
            "content": processed_content,
            "background": None,
            "transition": "slide",
            "notes": f"Slide {slide_number}: {slide_description}"
        }
    
    def _extract_slide_content(self, response: str) -> str:
        """
        Extract content from <slide> tags in LLM response.
        
        Args:
            response: Raw LLM response
            
        Returns:
            Extracted slide content
        """
        import re
        
        # Look for content between <slide> tags
        match = re.search(r'<slide>(.*?)</slide>', response, re.DOTALL | re.IGNORECASE)
        
        if match:
            return match.group(1).strip()
        
        # Fallback: return the entire response if no tags found
        return response.strip()
    
    def _post_process_slide_data_single(self, content: str) -> str:
        """
        Post-process content for a single slide (HTML mode).
        
        Args:
            content: Raw slide content
            
        Returns:
            Processed HTML content
        """
        # Apply comprehensive markdown-to-HTML conversion as safety net
        processed = self._convert_markdown_to_html_comprehensive(content)
        
        # Additional HTML-specific cleanup
        processed = self._clean_remaining_markdown_artifacts(processed)
        
        # Process math notation for MathJax
        processed = self._process_math_notation(processed)
        
        # Additional pass to fix math in HTML contexts (lists, paragraphs, etc.)
        processed = self._fix_math_in_html_contexts(processed)
        
        return processed

    def _process_math_notation(self, content: str) -> str:
        """
        Process LaTeX math notation for MathJax rendering, including AMS math environments.
        Handles math in lists, paragraphs, and other HTML contexts.
        
        Args:
            content: Content that may contain LaTeX math
            
        Returns:
            Content with properly formatted math for MathJax
        """
        # Simplified and robust approach using string replacement
        
        # Handle the most common problematic patterns first
        # Fix \\( and \\) patterns (most common in lists)
        content = content.replace('\\\\(', '\\(')
        content = content.replace('\\\\)', '\\)')
        
        # Fix \\[ and \\] patterns  
        content = content.replace('\\\\[', '\\[')
        content = content.replace('\\\\]', '\\]')
        
        # Handle triple backslash patterns that might occur
        content = content.replace('\\\\\\(', '\\(')
        content = content.replace('\\\\\\)', '\\)')
        content = content.replace('\\\\\\[', '\\[')
        content = content.replace('\\\\\\]', '\\]')
        
        # Handle quadruple backslash patterns
        content = content.replace('\\\\\\\\(', '\\(')
        content = content.replace('\\\\\\\\)', '\\)')
        content = content.replace('\\\\\\\\[', '\\[')
        content = content.replace('\\\\\\\\]', '\\]')
        
        # Handle AMS math environments with regex for better coverage
        # Fix \begin{cases} and \end{cases}
        content = re.sub(r'\\\\begin\{cases\}', r'\\begin{cases}', content)
        content = re.sub(r'\\\\end\{cases\}', r'\\end{cases}', content)
        
        # Handle other common AMS environments
        ams_environments = ['align', 'align*', 'equation', 'equation*', 'gather', 'gather*', 
                           'multline', 'multline*', 'split', 'array', 'matrix', 'pmatrix', 
                           'bmatrix', 'vmatrix', 'Vmatrix']
        
        for env in ams_environments:
            content = re.sub(f'\\\\\\\\begin\\{{{env}\\}}', f'\\\\begin{{{env}}}', content)
            content = re.sub(f'\\\\\\\\end\\{{{env}\\}}', f'\\\\end{{{env}}}', content)
        
        # Handle common LaTeX commands with more comprehensive patterns
        latex_commands = ['text', 'mathrm', 'mathbf', 'mathit', 'frac', 'sqrt', 'sum', 'int', 
                         'prod', 'lim', 'sin', 'cos', 'tan', 'log', 'ln', 'exp', 'alpha', 
                         'beta', 'gamma', 'delta', 'epsilon', 'theta', 'lambda', 'mu', 'pi', 
                         'sigma', 'phi', 'omega', 'infty', 'partial', 'nabla', 'cdot', 'ldots',
                         'dots', 'times', 'div', 'pm', 'mp', 'leq', 'geq', 'neq', 'approx']
        
        for cmd in latex_commands:
            # Handle various double backslash patterns
            content = re.sub(f'\\\\\\\\{cmd}', f'\\\\{cmd}', content)
            content = content.replace(f'\\\\{cmd}', f'\\{cmd}')
        
        # Clean up any remaining excessive backslashes
        # Fix any remaining quadruple backslashes
        content = content.replace('\\\\\\\\', '\\\\')
        
        # Fix subscripts and superscripts that might have double backslashes
        content = content.replace('\\\\_', '\\_')
        content = content.replace('\\\\^', '\\^')
        
        return content

    def _fix_math_in_html_contexts(self, content: str) -> str:
        """
        Specifically handle math notation that appears within HTML elements like lists.
        
        Args:
            content: HTML content that may contain math notation
            
        Returns:
            Content with math notation fixed in HTML contexts
        """
        # Apply the same simple string replacements as the main function
        # but this catches any patterns that might have been missed
        
        # Handle any remaining double backslashes that might appear in HTML contexts
        content = content.replace('\\\\(', '\\(')
        content = content.replace('\\\\)', '\\)')
        content = content.replace('\\\\[', '\\[')
        content = content.replace('\\\\]', '\\]')
        
        # Handle triple backslashes that might appear
        content = content.replace('\\\\\\(', '\\(')
        content = content.replace('\\\\\\)', '\\)')
        content = content.replace('\\\\\\[', '\\[')
        content = content.replace('\\\\\\]', '\\]')
        
        # Final safety check for any remaining problematic patterns
        content = content.replace('\\\\\\\\(', '\\(')
        content = content.replace('\\\\\\\\)', '\\)')
        content = content.replace('\\\\\\\\[', '\\[')
        content = content.replace('\\\\\\\\]', '\\]')
        
        return content

    def _post_process_slide_data(self, slide_data: Dict) -> Dict:
        """
        Post-process slide data with comprehensive markdown-to-HTML conversion.
        
        Args:
            slide_data: Raw slide data from LLM
            
        Returns:
            Processed slide data with proper HTML formatting (no markdown)
        """
        try:
            for slide in slide_data.get("slides", []):
                if "content" in slide:
                    content = slide["content"]
                    
                    # Apply comprehensive markdown to HTML conversion
                    content = self._convert_markdown_to_html_comprehensive(content)
                    
                    slide["content"] = content
                    
        except Exception as e:
            print(f"Error post-processing slide data: {e}")
        
        return slide_data

    def _post_process_via_markdown(self, slide_data: Dict) -> Dict:
        """
        Convert markdown slide contents to HTML using markdown-it-py with plugins
        (code fences, tables, task lists, math via texmath/katex) and then run
        minimal safety passes. Falls back to the comprehensive regex converter
        if markdown-it-py is not available.
        """
        try:
            from markdown_it import MarkdownIt
            from mdit_py_plugins.tasklists import tasklists_plugin
            from mdit_py_plugins.deflist import deflist_plugin
            from mdit_py_plugins.footnote import footnote_plugin
            # Math support (two-stage): render via texmath (KaTeX) if enabled
            math_plugin = None
            if ENABLE_SERVER_SIDE_MATH:
                try:
                    from mdit_py_plugins.texmath import texmath_plugin
                    # texmath_plugin doesn't take engine parameter directly
                    math_plugin = texmath_plugin
                except Exception as e:
                    print(f"[SlideAgent] Math plugin not available: {e}")
                    math_plugin = None

            md = MarkdownIt('commonmark', {'html': False, 'linkify': True}) \
                .use(tasklists_plugin) \
                .use(deflist_plugin) \
                .use(footnote_plugin)
            if math_plugin:
                md = md.use(math_plugin)

            for slide in slide_data.get('slides', []):
                content = slide.get('content', '')
                if not isinstance(content, str):
                    continue
                html = md.render(content)
                # If server-side math not enabled or plugin missing, leave $...$ for client
                # Normalize code language classes for highlight.js
                html = re.sub(r'<code class="language-([^"]+)"', r'<code class="\1"', html)
                slide['content'] = html
        except Exception as e:
            print(f"markdown-it processing unavailable or failed, falling back. Error: {e}")
            # Fallback to the regex-based comprehensive converter
            slide_data = self._post_process_slide_data(slide_data)

        return slide_data
    
    def _convert_markdown_to_html_comprehensive(self, content: str) -> str:
        """
        Comprehensive markdown to HTML conversion with extensible pattern system.
        
        Args:
            content: Content that may contain markdown syntax
            
        Returns:
            Content with all markdown converted to HTML
        """
        # Define conversion patterns - easily extensible
        conversion_patterns = [
            # Code blocks (triple backticks) - must be first to avoid conflicts
            {
                'pattern': r'```(\w+)?\s*\n(.*?)\n```',
                'replacement': lambda m: f'<pre><code class="{m.group(1) or "python"}">{m.group(2).strip()}</code></pre>',
                'flags': re.DOTALL,
                'description': 'Code blocks'
            },
            
            # Inline code (single backticks)
            {
                'pattern': r'`([^`\n]+)`',
                'replacement': r'<code>\1</code>',
                'flags': 0,
                'description': 'Inline code'
            },
            
            # Headers (must be before bold/italic to avoid conflicts)
            {
                'pattern': r'^### (.*$)',
                'replacement': r'<h3>\1</h3>',
                'flags': re.MULTILINE,
                'description': 'H3 headers'
            },
            {
                'pattern': r'^## (.*$)',
                'replacement': r'<h2>\1</h2>',
                'flags': re.MULTILINE,
                'description': 'H2 headers'
            },
            {
                'pattern': r'^# (.*$)',
                'replacement': r'<h1>\1</h1>',
                'flags': re.MULTILINE,
                'description': 'H1 headers'
            },
            
            # Bold text (double asterisks)
            {
                'pattern': r'\*\*(.*?)\*\*',
                'replacement': r'<strong>\1</strong>',
                'flags': 0,
                'description': 'Bold text'
            },
            
            # Italic text (single asterisks) - after bold to avoid conflicts
            {
                'pattern': r'(?<!\*)\*([^*\n]+)\*(?!\*)',
                'replacement': r'<em>\1</em>',
                'flags': 0,
                'description': 'Italic text'
            },
            
            # Unordered lists
            {
                'pattern': r'^- (.*$)',
                'replacement': r'<li>\1</li>',
                'flags': re.MULTILINE,
                'description': 'List items'
            },
            
            # Numbered lists
            {
                'pattern': r'^\d+\. (.*$)',
                'replacement': r'<li>\1</li>',
                'flags': re.MULTILINE,
                'description': 'Numbered list items'
            }
        ]
        
        # Apply each conversion pattern
        for pattern_info in conversion_patterns:
            try:
                if callable(pattern_info['replacement']):
                    content = re.sub(
                        pattern_info['pattern'],
                        pattern_info['replacement'],
                        content,
                        flags=pattern_info['flags']
                    )
                else:
                    content = re.sub(
                        pattern_info['pattern'],
                        pattern_info['replacement'],
                        content,
                        flags=pattern_info['flags']
                    )
            except Exception as e:
                print(f"Error applying {pattern_info['description']} conversion: {e}")
        
        # Post-processing: wrap consecutive list items
        content = re.sub(r'(<li>.*?</li>(?:\s*<li>.*?</li>)*)', r'<ul>\1</ul>', content, flags=re.DOTALL)
        
        # Clean up language class names for syntax highlighting
        language_cleanups = [
            (r'<code class="language-python"', r'<code class="python"'),
            (r'<code class="language-javascript"', r'<code class="javascript"'),
            (r'<code class="language-java"', r'<code class="java"'),
            (r'<code class="language-cpp"', r'<code class="cpp"'),
            (r'<code class="language-c"', r'<code class="c"'),
            (r'<code class="language-html"', r'<code class="html"'),
            (r'<code class="language-css"', r'<code class="css"'),
        ]
        
        for old_pattern, new_pattern in language_cleanups:
            content = re.sub(old_pattern, new_pattern, content)
        
        # Convert remaining line breaks to paragraphs (for non-HTML content)
        paragraphs = content.split('\n\n')
        processed_paragraphs = []
        
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                # Only wrap in <p> if it's not already HTML
                p = f'<p>{p}</p>'
            if p:
                processed_paragraphs.append(p)
        
        content = '\n'.join(processed_paragraphs)
        
        # Remove any remaining standalone markdown artifacts
        content = self._clean_remaining_markdown_artifacts(content)
        
        return content
    
    def _clean_remaining_markdown_artifacts(self, content: str) -> str:
        """
        Clean up any remaining markdown artifacts that weren't caught by main patterns.
        
        Args:
            content: Content to clean
            
        Returns:
            Cleaned content
        """
        # Remove standalone backticks
        content = re.sub(r'<p>```.*?</p>', '', content)
        content = re.sub(r'<p>`</p>', '', content)
        
        # Remove empty paragraphs
        content = re.sub(r'<p>\s*</p>', '', content)
        
        # Clean up multiple consecutive line breaks
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        return content.strip()
    
    def _convert_text_with_indentation_preserved(self, text: str) -> str:
        """
        Convert text to HTML with comprehensive markdown conversion and proper code indentation.
        
        Args:
            text: Text content that may contain markdown and code
            
        Returns:
            Clean HTML with proper code indentation and all markdown converted
        """
        if not text.strip():
            return "<p>Content here...</p>"
        
        # First apply comprehensive markdown to HTML conversion
        html_content = self._convert_markdown_to_html_comprehensive(text)
        
        # Optionally repair indentation if enabled
        if REPAIR_CODE_INDENTATION:
            html_content = self._fix_code_indentation_in_html(html_content)
        
        return html_content
    
    def _fix_code_indentation_in_html(self, html_content: str) -> str:
        """
        Fix code indentation in HTML content that contains <pre><code> blocks.
        
        Args:
            html_content: HTML content with code blocks
            
        Returns:
            HTML content with properly indented code blocks
        """
        def fix_code_block(match):
            language_class = match.group(1)
            code_content = match.group(2)

            # Token helpers
            def is_block_starter(s: str) -> bool:
                return (
                    s.startswith('for ') or s.startswith('if ') or s.startswith('else if ') or s.startswith('while ') or
                    s.startswith('with ') or s.startswith('try:') or s.startswith('except') or
                    s.startswith('elif ') or s == 'else:'
                ) and s.endswith(':')

            def block_type(s: str) -> str:
                if s.startswith('for '):
                    return 'for'
                if s.startswith('if '):
                    return 'if'
                if s.startswith('else if '):
                    return 'elif'
                if s.startswith('while '):
                    return 'while'
                if s.startswith('with '):
                    return 'with'
                if s.startswith('try:'):
                    return 'try'
                if s.startswith('except'):
                    return 'except'
                if s.startswith('elif '):
                    return 'elif'
                if s == 'else:':
                    return 'else'
                return 'block'

            # Build fixed code with a simple stack-based indentation model
            raw_lines = code_content.split('\n')
            # Remove leading/trailing empty lines but keep internal blanks
            while raw_lines and not raw_lines[0].strip():
                raw_lines.pop(0)
            while raw_lines and not raw_lines[-1].strip():
                raw_lines.pop()

            fixed_lines: list[str] = []
            stack: list[str] = []  # tracks opened blocks; 'def' is level 0 when present
            pending_dedent = 0     # how many levels to dedent before next line

            # Pre-scan to find last non-empty index for fallback-return heuristic
            non_empty_indexes = [i for i, l in enumerate(raw_lines) if l.strip()]
            last_non_empty = non_empty_indexes[-1] if non_empty_indexes else -1

            for idx, line in enumerate(raw_lines):
                # Preserve original indentation if the LLM already provided it
                if not REPAIR_CODE_INDENTATION:
                    fixed_lines.append(line)
                    continue

                stripped = line.strip()
                if not stripped:
                    fixed_lines.append('')
                    continue

                # Apply any pending dedent from previous control-flow terminators
                while pending_dedent > 0 and stack:
                    stack.pop()
                    pending_dedent -= 1

                # Determine indentation level for this line
                if stripped.startswith('def ') or stripped.startswith('class '):
                    indent_level = 0
                elif stripped.startswith('elif ') or stripped.startswith('else if ') or stripped == 'else:' or stripped.startswith('except') or stripped == 'finally:':
                    # same level as the corresponding block
                    indent_level = max(len(stack) - 1, 0)
                elif stripped.startswith('return ') and idx == last_non_empty:
                    # Heuristic: final return at function scope
                    indent_level = 1 if ('def' in stack or (fixed_lines and fixed_lines[0].startswith('def '))) else max(len(stack), 0)
                else:
                    indent_level = len(stack)

                # Emit line with computed indentation
                fixed_lines.append(('    ' * indent_level) + stripped)

                # Update stack transitions for next line
                if stripped.startswith('def ') or stripped.startswith('class '):
                    stack.append('def')
                if is_block_starter(stripped):
                    # New block increases indent for subsequent lines
                    stack.append(block_type(stripped))

                # If we just emitted a control-flow terminator inside an if/loop,
                # schedule a dedent for the next statement (closing the block)
                if (stripped.startswith('return ') or stripped.startswith('break') or stripped.startswith('continue') or stripped.startswith('pass')):
                    if stack and stack[-1] in {'if', 'for', 'while', 'with'}:
                        pending_dedent = max(pending_dedent, 1)

            fixed_code = '\n'.join(fixed_lines)
            return f'<pre><code class="{language_class}">{fixed_code}</code></pre>'
        
        # Fix indentation in all code blocks (called only when REPAIR_CODE_INDENTATION=True)
        html_content = re.sub(
            r'<pre><code class="([^"]*)">([\s\S]*?)</code></pre>',
            fix_code_block,
            html_content,
            flags=re.DOTALL
        )
        
        return html_content

    def _create_fallback_slides(self, content: str, slide_count: int) -> Dict:
        """
        Create basic slides if JSON parsing fails using simple text-to-HTML conversion.
        
        Args:
            content: Original content (markdown or plain text)
            slide_count: Number of slides to create
            
        Returns:
            Basic slide structure with simple HTML formatting like mock demo
        """
        # Split content into sections by lines, not by complex HTML processing
        lines = content.strip().split('\n')
        sections = []
        current_section = []
        
        # Smart splitting that respects code blocks and logical boundaries
        in_code_block = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Track code block boundaries
            if line.startswith('```'):
                in_code_block = not in_code_block
                current_section.append(line)
                continue
            
            # Don't split in the middle of code blocks
            if in_code_block:
                current_section.append(line)
                continue
            
            # Start new section if we hit a header or have enough content
            should_break = (
                (line.startswith('#') and current_section and len(current_section) > 3) or
                len(current_section) >= 12  # Allow more content per slide with increased viewport
            )
            
            if should_break:
                if current_section:
                    sections.append('\n'.join(current_section))
                    current_section = []
            
            current_section.append(line)
        
        # Add last section
        if current_section:
            sections.append('\n'.join(current_section))
        
        # Ensure we have enough sections
        while len(sections) < slide_count:
            if sections:
                # Split the longest section
                longest_idx = max(range(len(sections)), key=lambda i: len(sections[i]))
                longest = sections[longest_idx]
                lines = longest.split('\n')
                if len(lines) > 2:
                    mid = len(lines) // 2
                    sections[longest_idx] = '\n'.join(lines[:mid])
                    sections.insert(longest_idx + 1, '\n'.join(lines[mid:]))
                else:
                    sections.append("## Additional Content\n\nMore information...")
            else:
                sections.append("## Slide Content\n\nContent here...")
        
        # Convert sections to slides with basic HTML formatting
        slides = []
        for i, section in enumerate(sections[:slide_count]):
            lines = section.split('\n')
            
            # Extract title (look for markdown headers)
            title = f"Slide {i + 1}"
            content_lines = []
            
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                elif line.startswith('## '):
                    title = line[3:].strip()
                elif line.startswith('### '):
                    title = line[4:].strip()
                else:
                    content_lines.append(line)
            
            # Convert content to HTML using comprehensive conversion with proper indentation
            html_content = self._convert_text_with_indentation_preserved('\n'.join(content_lines))
            
            slides.append({
                "title": title,
                "content": html_content,
                "background": None,
                "transition": None,
                "notes": ""
            })
        
        return {
            "slides": slides,
            "metadata": {
                "total_slides": slide_count,
                "theme": "white",
                "estimated_duration": slide_count * 2
            }
        }
    
    def _convert_text_to_simple_html(self, text: str) -> str:
        """
        Convert plain text/markdown to clean HTML like the mock demo.
        
        Args:
            text: Text content to convert
            
        Returns:
            Clean HTML content with proper code blocks
        """
        if not text.strip():
            return "<p>Content here...</p>"
        
        # Clean up the text first - remove stray backticks and markdown artifacts
        text = text.strip()
        
        # Remove standalone triple backticks and language markers
        text = re.sub(r'^```\w*\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
        
        # Handle proper code blocks first (```language...```) - preserve exact indentation
        def preserve_code_block(match):
            language = match.group(1) or "python"
            code_content = match.group(2)
            
            # Keep exact indentation - just trim leading/trailing empty lines
            lines = code_content.split('\n')
            
            # Remove empty lines at start and end only
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            
            # Join back without any indentation changes
            code_content = '\n'.join(lines)
            
            return f'<pre><code class="{language}">{code_content}</code></pre>'
        
        text = re.sub(
            r'```(\w+)?\s*\n(.*?)\n```',
            preserve_code_block,
            text,
            flags=re.DOTALL
        )
        
        # Remove any remaining backticks that aren't part of inline code
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Don't strip indentation here - preserve it for code blocks
            if not line.strip():  # Skip empty lines
                continue
            
            # Skip lines that are just backticks
            if line.strip() in ['```', '```python', '```javascript', '```java']:
                continue
            
            cleaned_lines.append(line)  # Keep original line with indentation
        
        # Process lines into HTML
        html_parts = []
        current_code_block = []
        in_pre_tag = False
        
        for line in cleaned_lines:
            # Check if we're in an existing <pre> block
            if '<pre><code' in line:
                in_pre_tag = True
                html_parts.append(line)
                continue
            elif '</code></pre>' in line:
                in_pre_tag = False
                html_parts.append(line)
                continue
            elif in_pre_tag:
                html_parts.append(line)
                continue
            
            # Detect if this line looks like code (preserve original indentation)
            stripped_line = line.strip()
            is_code_line = (
                stripped_line.startswith('def ') or
                stripped_line.startswith('for ') or 
                stripped_line.startswith('if ') or
                stripped_line.startswith('elif ') or stripped_line.startswith('else if ') or stripped_line == 'else:' or
                stripped_line.startswith('return ') or
                stripped_line.startswith('class ') or
                stripped_line.startswith('import ') or
                stripped_line.startswith('from ') or
                line.startswith('    ') or  # Indented lines (use original line)
                line.startswith('\t') or   # Tab indented lines (use original line)
                ('=' in stripped_line and not stripped_line.startswith('**') and not stripped_line.startswith('*')) or
                stripped_line.endswith(':') and ('def ' in stripped_line or 'for ' in stripped_line or 'if ' in stripped_line or 'class ' in stripped_line)
            )
            
            # For Python code, ensure proper indentation based on context
            if is_code_line:
                # Track indentation context
                if stripped_line.startswith('def ') or stripped_line.startswith('class '):
                    # Function/class definition - no indentation needed
                    pass
                elif stripped_line.startswith('for ') or stripped_line.startswith('if ') or stripped_line.startswith('while ') or stripped_line.startswith('with ') or stripped_line.startswith('try:') or stripped_line.startswith('except'):
                    # Control structures inside functions need base indentation
                    if not (line.startswith('    ') or line.startswith('\t')):
                        line = '    ' + stripped_line
                elif stripped_line.startswith('return ') or stripped_line.startswith('break') or stripped_line.startswith('continue') or stripped_line.startswith('pass') or ('=' in stripped_line and not stripped_line.startswith('**')):
                    # Statements inside control structures need double indentation
                    if not (line.startswith('        ') or line.startswith('    ')):
                        # Check if this is likely inside a nested block (for/if)
                        if any(cb_line.strip().endswith(':') for cb_line in current_code_block[-3:] if cb_line.strip()):
                            line = '        ' + stripped_line  # Double indent for nested
                        else:
                            line = '    ' + stripped_line      # Single indent for function body
                elif not (line.startswith('    ') or line.startswith('\t')) and not (stripped_line.startswith('import ') or stripped_line.startswith('from ')):
                    # Other code statements should be indented
                    line = '    ' + stripped_line
            
            if is_code_line:
                # Add to current code block (preserve exact indentation)
                current_code_block.append(line)
            else:
                # Not code - flush any accumulated code first
                if current_code_block:
                    html_parts.append('<pre><code class="python">')
                    
                    # Add code lines with exact indentation preserved
                    for code_line in current_code_block:
                        html_parts.append(code_line)
                    
                    html_parts.append('</code></pre>')
                    current_code_block = []
                
                # Process non-code content (use stripped version for pattern matching)
                if stripped_line.startswith('- '):
                    # Keep empty lines between items as slight spacing
                    html_parts.append(f'<li>{stripped_line[2:].strip()}</li>')
                elif re.match(r'^\d+\.', stripped_line):
                    # Ordered lists like "1. Item"
                    html_parts.append('<li>' + re.sub(r'^\d+\.\s*', '', stripped_line) + '</li>')
                elif stripped_line.startswith('**') and stripped_line.endswith('**') and len(stripped_line) > 4:
                    html_parts.append(f'<p><strong>{stripped_line[2:-2]}</strong></p>')
                elif stripped_line.startswith('*') and stripped_line.endswith('*') and len(stripped_line) > 2 and not stripped_line.startswith('**'):
                    html_parts.append(f'<p><em>{stripped_line[1:-1]}</em></p>')
                else:
                    # Handle inline code within regular text
                    processed_line = self._process_inline_code(stripped_line)
                    html_parts.append(f'<p>{processed_line}</p>')
        
        # Flush any remaining code
        if current_code_block:
            html_parts.append('<pre><code class="python">')
            
            # Add remaining code lines with exact indentation preserved
            for code_line in current_code_block:
                html_parts.append(code_line)
            
            html_parts.append('</code></pre>')
        
        # Join and clean up
        html_text = '\n'.join(html_parts)
        
        # Wrap consecutive <li> elements in <ul>
        html_text = re.sub(r'(<li>.*?</li>(?:\s*<li>.*?</li>)*)', r'<ul>\1</ul>', html_text, flags=re.DOTALL)
        
        # Remove any remaining stray backticks
        html_text = re.sub(r'<p>```.*?</p>', '', html_text)
        html_text = re.sub(r'<p>`</p>', '', html_text)
        
        return html_text.strip() if html_text.strip() else "<p>Content here...</p>"
    
    def _process_inline_code(self, text: str) -> str:
        """
        Process inline code (single backticks) within text.
        
        Args:
            text: Text that may contain inline code
            
        Returns:
            Text with inline code converted to <code> tags
        """
        # Handle inline code with single backticks
        # Match `code` but not at start/end of line (those are handled elsewhere)
        processed = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
        return processed
    

    
    def _split_content_into_sections(self, html_content: str, slide_count: int) -> List[str]:
        """
        Split HTML content into sections for slides.
        
        Args:
            html_content: HTML content to split
            slide_count: Number of sections to create
            
        Returns:
            List of HTML sections
        """
        # Try to split by headers first
        header_sections = re.split(r'(<h[1-3][^>]*>.*?</h[1-3]>)', html_content)
        
        if len(header_sections) >= slide_count:
            # We have enough header sections
            sections = []
            current_section = ""
            
            for part in header_sections:
                if re.match(r'<h[1-3]', part):
                    if current_section:
                        sections.append(current_section)
                    current_section = part
                else:
                    current_section += part
                    
                if len(sections) >= slide_count - 1:
                    break
            
            if current_section:
                sections.append(current_section)
                
            return sections[:slide_count]
        
        else:
            # Split by paragraphs or length
            paragraphs = re.split(r'(</p>)', html_content)
            content_blocks = []
            current_block = ""
            
            for i in range(0, len(paragraphs), 2):
                if i + 1 < len(paragraphs):
                    paragraph = paragraphs[i] + paragraphs[i + 1]
                else:
                    paragraph = paragraphs[i]
                    
                if len(current_block) + len(paragraph) > len(html_content) // slide_count:
                    if current_block:
                        content_blocks.append(current_block)
                        current_block = paragraph
                    else:
                        content_blocks.append(paragraph)
                else:
                    current_block += paragraph
                    
                if len(content_blocks) >= slide_count - 1:
                    break
            
            if current_block:
                content_blocks.append(current_block)
                
            # Ensure we have exactly slide_count sections
            while len(content_blocks) < slide_count:
                content_blocks.append("<p>Additional content</p>")
                
            return content_blocks[:slide_count]

    def _create_markdown_slides(self, content: str, slide_count: int) -> Dict:
        """
        Create slides using Reveal.js native markdown support.
        
        Args:
            content: Original markdown content
            slide_count: Number of slides to create
            
        Returns:
            Slide structure with markdown content for Reveal.js
        """
        # Split content by headers or logical sections
        sections = self._split_markdown_content(content, slide_count)
        
        slides = []
        for i, section in enumerate(sections):
            # Extract title from markdown section
            lines = section.strip().split('\n')
            title = "Slide " + str(i + 1)
            
            # Look for markdown headers
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
                elif line.startswith('## '):
                    title = line[3:].strip()
                    break
                elif line.startswith('### '):
                    title = line[4:].strip()
                    break
            
            slides.append({
                "title": title,
                "content": section.strip(),
                "markdown": True,  # Flag to indicate this should use markdown rendering
                "background": None,
                "transition": None,
                "notes": ""
            })
        
        return {
            "slides": slides,
            "metadata": {
                "total_slides": slide_count,
                "theme": "white",
                "estimated_duration": slide_count * 2,
                "uses_markdown": True
            }
        }
    
    def _split_markdown_content(self, content: str, slide_count: int) -> List[str]:
        """
        Split markdown content into sections for slides with better size management.
        
        Args:
            content: Markdown content to split
            slide_count: Number of sections to create
            
        Returns:
            List of markdown sections optimized for slide display
        """
        # Split by headers and manage content size
        lines = content.strip().split('\n')
        sections = []
        current_section = []
        current_line_count = 0
        
        # Maximum lines per slide (to prevent overflow) - very restrictive
        MAX_LINES_PER_SLIDE = 6
        MAX_CHARS_PER_SLIDE = 400
        
        for line in lines:
            line = line.strip()
            if not line:
                current_section.append('')
                continue
                
            # Check if this is a header
            is_header = re.match(r'^#{1,3}\s+', line)
            
            # Start new section if:
            # 1. We hit a header and have content
            # 2. We exceed line or character limits
            current_content = '\n'.join(current_section)
            should_break = (
                (is_header and current_section and current_line_count > 3) or
                current_line_count >= MAX_LINES_PER_SLIDE or
                len(current_content) >= MAX_CHARS_PER_SLIDE
            )
            
            if should_break and current_section:
                sections.append('\n'.join(current_section))
                current_section = [line] if line else []
                current_line_count = 1 if line else 0
            else:
                current_section.append(line)
                current_line_count += 1
        
        # Add the last section
        if current_section:
            sections.append('\n'.join(current_section))
        
        # Clean up sections - remove empty ones and ensure proper formatting
        cleaned_sections = []
        for section in sections:
            section = section.strip()
            if section:
                # Ensure each section has a title
                lines = section.split('\n')
                has_header = any(re.match(r'^#{1,3}\s+', line) for line in lines[:3])
                
                if not has_header and cleaned_sections:
                    # Add a generic header if none exists
                    section = f"## Slide {len(cleaned_sections) + 1}\n\n{section}"
                
                cleaned_sections.append(section)
        
        # If we have too few sections, split longer ones more aggressively
        while len(cleaned_sections) < slide_count and len(cleaned_sections) > 0:
            # Find the longest section
            longest_idx = max(range(len(cleaned_sections)), 
                            key=lambda i: len(cleaned_sections[i].split('\n')))
            longest = cleaned_sections[longest_idx]
            lines = longest.split('\n')
            
            if len(lines) <= 4:  # Don't split very short sections
                break
                
            # Split at a logical point
            split_point = len(lines) // 2
            
            # Try to split at a paragraph break or after a code block
            for i in range(split_point - 2, split_point + 3):
                if i < len(lines) and (lines[i] == '' or lines[i].startswith('```')):
                    split_point = i + 1
                    break
            
            first_part = '\n'.join(lines[:split_point])
            second_part = '\n'.join(lines[split_point:])
            
            # Add header to second part if it doesn't have one
            if not re.match(r'^#{1,3}\s+', second_part):
                second_part = f"## Continued\n\n{second_part}"
            
            cleaned_sections[longest_idx] = first_part
            cleaned_sections.insert(longest_idx + 1, second_part)
        
        # Ensure we have exactly slide_count sections
        while len(cleaned_sections) < slide_count:
            cleaned_sections.append("## Additional Information\n\nContent continues...")
        
        return cleaned_sections[:slide_count]

    def _generate_reveal_html(self, slide_data: Dict) -> str:
        """
        Generate Reveal.js HTML from slide data.
        
        Args:
            slide_data: Dictionary containing slide information
            
        Returns:
            HTML string for Reveal.js presentation
        """
        slides_html = ""
        uses_markdown = slide_data.get("metadata", {}).get("uses_markdown", False)
        
        for slide in slide_data.get("slides", []):
            # Build slide attributes
            slide_attrs = []
            
            if slide.get("background"):
                slide_attrs.append(f'data-background="{slide["background"]}"')
            
            if slide.get("transition"):
                slide_attrs.append(f'data-transition="{slide["transition"]}"')
            
            # Check if this slide should use markdown
            if slide.get("markdown", False) or uses_markdown:
                slide_attrs.append('data-markdown')
            
            attrs_str = " " + " ".join(slide_attrs) if slide_attrs else ""
            
            # Use HTML format with scrollable content wrapper
            slide_html = f"""
            <section{attrs_str}>
                <div class="slide-content">
                    {slide.get("content", "")}
                </div>
                {f'<aside class="notes">{slide["notes"]}</aside>' if slide.get("notes") else ""}
            </section>
            """
            slides_html += slide_html
        
        if self.demo_mode:
            return self._generate_standalone_html(slides_html, slide_data)
        else:
            return self._generate_embedded_html(slides_html, slide_data)

    def _generate_standalone_html(self, slides_html: str, slide_data: Dict) -> str:
        """
        Generate complete standalone HTML with Reveal.js imports.
        
        Args:
            slides_html: HTML content for slides
            slide_data: Slide metadata
            
        Returns:
            Complete HTML document
        """
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Slide Presentation</title>
    
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/reveal.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/dist/theme/{slide_data.get('metadata', {}).get('theme', 'white')}.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@4.3.1/plugin/highlight/monokai.css">
    
    <style>
        .slide-content {{
            text-align: left;
            font-size: 0.85em;
            line-height: 1.3;
        }}
        
        /* Better code block styling */
        .reveal pre {{
            width: 100%;
            margin: 5px 0;
            box-shadow: 0px 3px 10px rgba(0, 0, 0, 0.15);
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
        
        /* Allow Reveal.js to handle slide positioning - DO NOT override */
        .reveal .slides section {{
            /* Only set non-positioning styles */
            padding: 0;
            font-size: 0.8em;
            /* DO NOT set position, top, left, transform, display, or height */
            /* Reveal.js will handle these internally */
        }}
        
        /* Create scrollable content wrapper inside slides */
        .reveal .slides section .slide-content {{
            width: 100%;
            height: calc(85vh - 40px); /* Slightly reduced to ensure last line visibility */
            max-height: calc(85vh - 40px);
            overflow-y: auto;
            overflow-x: hidden;
            padding: 20px;
            padding-bottom: 25px; /* Extra bottom padding to ensure last line is visible */
            margin: 0;
            /* Smooth scrolling */
            scroll-behavior: smooth;
            /* Custom scrollbar styling */
            scrollbar-width: thin;
            scrollbar-color: #3498db #f1f1f1;
            /* Content styling */
            text-align: left;
            font-size: 0.8em;
            /* Ensure proper positioning */
            position: relative;
            box-sizing: border-box;
            /* Scroll indicator variables */
            --scroll-indicator-opacity: 1;
        }}
        
        /* Webkit scrollbar styling for slide content */
        .reveal .slides section .slide-content::-webkit-scrollbar {{
            width: 8px;
        }}
        
        .reveal .slides section .slide-content::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 4px;
        }}
        
        .reveal .slides section .slide-content::-webkit-scrollbar-thumb {{
            background: #3498db;
            border-radius: 4px;
        }}
        
        .reveal .slides section .slide-content::-webkit-scrollbar-thumb:hover {{
            background: #2980b9;
        }}
        
        /* Add scroll indicator variables to existing slide-content rule above */
        
        .reveal .slides section .slide-content::after {{
            content: "";
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 25px;
            background: linear-gradient(transparent, rgba(255,255,255,0.9));
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s ease;
            z-index: 10;
        }}
        
        .reveal .slides section .slide-content.scrollable::after {{
            opacity: var(--scroll-indicator-opacity, 1);
        }}
        
        /* Scroll hint text */
        .reveal .slides section .slide-content.scrollable::before {{
            content: "↓ Scroll for more content ↓";
            position: absolute;
            bottom: 2px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 0.6em;
            color: #666;
            z-index: 11;
            opacity: var(--scroll-indicator-opacity, 1);
            transition: opacity 0.3s ease;
            background: rgba(255,255,255,0.8);
            padding: 2px 8px;
            border-radius: 10px;
            font-weight: normal;
        }}
        
        /* Smaller headers */
        .reveal .slides section h1,
        .reveal .slides section h2,
        .reveal .slides section h3 {{
            margin-top: 0;
            margin-bottom: 0.2em;
            font-size: 1.1em;
        }}
        
        .reveal .slides section h3 {{
            font-size: 1.1em;
        }}
        
        .reveal .slides section h4 {{
            font-size: 1.1em;
            margin-bottom: 0.2em;
        }}
        
        /* Compact list styling */
        .reveal ul, .reveal ol {{
            margin: 0.3em 0;
        }}
        
        .reveal li {{
            margin: 0.1em 0;
            font-size: 0.9em;
        }}
        
        /* Compact paragraph spacing */
        .reveal p {{
            margin: 0.3em 0;
            line-height: 1.3;
            font-size: 0.9em;
        }}
        
        /* Fragment animations */
        .reveal .slides section .fragment {{
            opacity: 0.3;
        }}
        .reveal .slides section .fragment.visible {{
            opacity: 1;
        }}
        
        /* Responsive design for different viewport sizes */
        @media (max-width: 768px) {{
            .reveal .slides section {{
                font-size: 0.75em;
                max-height: 80vh;
                padding: 8px !important;
            }}
            .reveal pre code {{
                font-size: 0.55em;
                max-height: 40vh;
            }}
        }}
        
        @media (max-height: 600px) {{
            /* Handle short viewport heights */
            .reveal .slides section {{
                max-height: 90vh;
                font-size: 0.7em;
            }}
            .reveal pre code {{
                max-height: 35vh;
                font-size: 0.5em;
            }}
        }}
        
        @media (max-height: 500px) {{
            /* Very short viewports */
            .reveal .slides section {{
                max-height: 95vh;
                font-size: 0.65em;
                padding: 6px !important;
            }}
            .reveal pre code {{
                max-height: 30vh;
                font-size: 0.45em;
            }}
        }}
        
        /* Ensure content doesn't overflow slide boundaries */
        .reveal .slides section > * {{
            max-width: 100%;
            box-sizing: border-box;
        }}
        
        /* Compact special styling */
        .complexity-analysis {{
            background: #ecf0f1;
            padding: 8px;
            border-radius: 4px;
            margin: 5px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.8em;
        }}
        
        /* Compact algorithm step styling */
        .algorithm-step {{
            background: #e8f6f3;
            padding: 6px;
            border-left: 3px solid #1abc9c;
            margin: 3px 0;
            font-size: 0.8em;
        }}
        
        /* Force text wrapping */
        .reveal .slides section * {{
            word-wrap: break-word;
            overflow-wrap: break-word;
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
    
    <!-- MathJax for LaTeX math rendering -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/MathJax.js?config=TeX-AMS_HTML"></script>
    
    <script>
        // Configure MathJax with AMS math support
        window.MathJax = {{
            tex2jax: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true,
                skipTags: ["code", "pre"],
                processEnvironments: true,
                processRefs: true
            }},
            TeX: {{
                extensions: ["AMSmath.js", "AMSsymbols.js", "autoload-all.js"],
                equationNumbers: {{
                    autoNumber: "AMS"
                }},
                Macros: {{
                    cases: ["\\\\begin{{cases}}#1\\\\end{{cases}}", 1],
                    text: ["\\\\mathrm{{#1}}", 1]
                }}
            }},
            displayAlign: "center",
            displayIndent: "0em"
        }};
        
        // Ensure all plugins are loaded before initialization
        document.addEventListener('DOMContentLoaded', function() {{
            Reveal.initialize({{
                hash: {str(self.reveal_config['hash']).lower()},
                controls: {str(self.reveal_config['controls']).lower()},
                progress: {str(self.reveal_config['progress']).lower()},
                center: {str(self.reveal_config['center']).lower()},
                transition: '{self.reveal_config['transition']}',
                backgroundTransition: '{self.reveal_config['backgroundTransition']}',
                plugins: [ RevealHighlight, RevealNotes, RevealMath.MathJax2 ]
            }}).then(() => {{
                console.log('Reveal.js initialized successfully');
                // Process math after initialization
                if (window.MathJax && window.MathJax.Hub) {{
                    MathJax.Hub.Queue(["Typeset", MathJax.Hub]);
                }}
                
                // Add scroll detection for visual indicators
                setTimeout(addScrollIndicators, 500);
            }});
        }});
        
        // Function to detect scrollable slide content and add visual indicators
        function addScrollIndicators() {{
            const slideContents = document.querySelectorAll('.reveal .slides section .slide-content');
            slideContents.forEach(slideContent => {{
                // Check if slide content overflows
                if (slideContent.scrollHeight > slideContent.clientHeight) {{
                    slideContent.classList.add('scrollable');
                    
                    // Add scroll event listener for fade effect
                    slideContent.addEventListener('scroll', function() {{
                        const isScrolledToBottom = slideContent.scrollHeight - slideContent.scrollTop <= slideContent.clientHeight + 10;
                        if (isScrolledToBottom) {{
                            slideContent.style.setProperty('--scroll-indicator-opacity', '0');
                        }} else {{
                            slideContent.style.setProperty('--scroll-indicator-opacity', '1');
                        }}
                    }});
                }}
            }});
        }}
        
        // Re-check scroll indicators when slides change
        Reveal.on('slidechanged', function() {{
            setTimeout(addScrollIndicators, 100);
        }});
    </script>
</body>
</html>
        """

    def _generate_embedded_html(self, slides_html: str, slide_data: Dict) -> str:
        """
        Generate HTML for embedding in existing page.
        
        Args:
            slides_html: HTML content for slides
            slide_data: Slide metadata
            
        Returns:
            HTML for embedding
        """
        return f"""
<div class="reveal-container" id="reveal-{id(self)}">
    <div class="reveal">
        <div class="slides">
            {slides_html}
        </div>
    </div>
    
    <div class="slide-controls mt-3">
        <button class="btn btn-sm btn-outline-primary" onclick="Reveal.prev()">
            <i class="fas fa-chevron-left"></i> Previous
        </button>
        <span class="mx-3">
            <span id="slide-counter">1</span> / {slide_data.get('metadata', {}).get('total_slides', 1)}
        </span>
        <button class="btn btn-sm btn-outline-primary" onclick="Reveal.next()">
            Next <i class="fas fa-chevron-right"></i>
        </button>
    </div>
    
    <script>
        // Initialize Reveal.js for this specific container (no markdown plugin)
        if (typeof Reveal !== 'undefined') {{
            Reveal.initialize({{
                embedded: true,
                hash: false,
                controls: false,
                progress: true,
                center: false,
                transition: '{self.reveal_config['transition']}',
                plugins: [ RevealHighlight, RevealMath.MathJax2 ]
            }}).then(() => {{
                console.log('Embedded Reveal.js initialized successfully');
            }});
            
            // Update slide counter
            Reveal.on('slidechanged', event => {{
                const counter = document.getElementById('slide-counter');
                if (counter) {{
                    counter.textContent = event.indexh + 1;
                }}
            }});
        }} else {{
            console.error('Reveal.js not loaded properly');
        }}
    </script>
</div>
        """

    def get_model_response(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Get response from the LLM model.
        
        Args:
            prompt: The prompt to send to the model
            temperature: Temperature for response generation
            
        Returns:
            Model response as string
        """
        try:
            # Use existing CallLLm infrastructure
            model = self.writer_model if isinstance(self.writer_model, str) else self.writer_model[0]
            llm = CallLLm(self.keys, model)
            # llm = CallLLm(self.keys, CHEAP_LONG_CONTEXT_LLM[0])
            response = llm(prompt, images=[], temperature=temperature, stream=False)
            
            # If response is a generator, collect all chunks
            if hasattr(response, '__iter__') and not isinstance(response, str):
                return ''.join(response)
            
            return str(response)
            
        except Exception as e:
            print(f"Error calling model: {e}")
            return f"Error: Unable to generate response - {str(e)}"

    def __call__(self, text: str, images: List = None, temperature: float = 0.7, 
                 stream: bool = True, max_tokens: Optional[int] = None, 
                 system: Optional[str] = None, web_search: bool = False) -> str:
        """
        Generate slides from the given text content.
        
        Args:
            text: Content to convert to slides
            images: Optional images (not used in base implementation)
            temperature: Temperature for LLM generation
            stream: Whether to stream response (not applicable for slides)
            max_tokens: Maximum tokens for generation
            system: Optional system message
            web_search: Whether to use web search (not applicable for slides)
            
        Returns:
            HTML content for the slides
        """
        import traceback
        
        try:
            # Two-stage approach: structured storyboard + parallel generation
            slide_count_hint = "12-20"
            print(f"[SlideAgent] Content mode: {self.content_mode}")
            print(f"[SlideAgent] Demo mode: {self.demo_mode}")
            
            # Generate slide content using two-stage approach
            slide_data = self._generate_slide_content_two_stage(text, slide_count_hint)
            print(f"[SlideAgent] Generated slide data with {len(slide_data.get('slides', []))} slides")
            
            # Generate final HTML
            html_output = self._generate_reveal_html(slide_data)
            print(f"[SlideAgent] Generated HTML output (length: {len(html_output)})")
            
            return html_output
            
        except Exception as e:
            error_msg = f"Error generating slides: {str(e)}"
            stack_trace = traceback.format_exc()
            print(f"[SlideAgent ERROR] {error_msg}")
            print(f"[SlideAgent STACK TRACE]:\n{stack_trace}")
            
            # Return basic error slide with detailed debugging info
            if self.demo_mode:
                return f"""
<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body>
    <h1>Error Generating Slides</h1>
    <p>{error_msg}</p>
    <details>
        <summary>Stack Trace</summary>
        <pre>{stack_trace}</pre>
    </details>
    <details>
        <summary>Input Text (first 1000 chars)</summary>
        <pre>{text[:1000]}...</pre>
    </details>
    <details>
        <summary>Configuration</summary>
        <pre>
Content Mode: {self.content_mode}
Demo Mode: {self.demo_mode}
Writer Model: {self.writer_model}
        </pre>
    </details>
</body>
</html>
                """
            else:
                return f"""
<div class="alert alert-danger">
    <h4>Error Generating Slides</h4>
    <p>{error_msg}</p>
    <details>
        <summary>Stack Trace</summary>
        <pre>{stack_trace}</pre>
    </details>
</div>
                """


class GenericSlideAgent(SlideAgent):
    """
    Generic slide agent for converting any content into slides.
    
    This agent can handle various types of content and create engaging
    slide presentations with appropriate structure and formatting.
    """
    
    def __init__(self, keys, writer_model: Union[List[str], str], demo_mode: bool = False):
        """
        Initialize the GenericSlideAgent.
        
        Args:
            keys: API keys for LLM access
            writer_model: Model(s) to use for content generation
            demo_mode: If True, generates standalone HTML; if False, embedded HTML
        """
        super().__init__(keys, writer_model, demo_mode)
        
        # Enhanced prompt for generic content - HTML format with more content per slide
        self.base_slide_prompt = """
You are an expert presentation designer creating engaging slides using Reveal.js HTML format.

Create approximately {slide_count} slides from the following content. Each slide should:
- Have a clear, focused topic with an engaging title
- Use clean HTML structure exactly like this example:
  <h3>Informational Section Title</h3>
  <p>Description text here with more detailed explanations.</p>
  <ul>
    <li>Key point 1 with explanation</li>
    <li>Key point 2 with explanation</li>
    <li>Key point 3 with explanation</li>
  </ul>
  <div class="fragment">
      <pre><code class="python">
def example():
    # More comprehensive code examples
    result = process_data()
    return result
      </code></pre>
  </div>

CRITICAL FORMATTING REQUIREMENTS:
- Use <pre><code class="python">code here</code></pre> for Python code blocks
- Use <pre><code class="javascript">code here</code></pre> for JavaScript code
- Use <pre><code class="java">code here</code></pre> for Java code
- Do NOT use markdown triple backticks (```) - only HTML tags
- Use <div class="fragment">content</div> for progressive disclosure
- Use proper HTML: <strong>, <em>, <ul>, <li>, <p>, <h3>, <h4>
- With mildy increased viewport height, you can include more content per slide (up to 8 lines)
- Include detailed explanations, multiple code examples, and comprehensive lists.
- Address the immediate question or problem statement asked by the user.
- Give informative slide titles.
- Cover the content in the slides within the <main-content> tag.
- Ignore conversation history and only focus on the content within the <main-content> tag.

Content to convert:
{content}

Generate the slides in the following JSON format:
{{
    "slides": [
        {{
            "title": "Clear Slide Title (1-4 words)",
            "content": "<h3>Subtitle</h3><p>Detailed description with explanations.</p><ul><li>Point 1</li><li>Point 2</li></ul><div class='fragment'><pre><code class='python'>comprehensive_code_example()</code></pre></div>",
            "background": "optional background color",
            "transition": "slide",
            "notes": "optional speaker notes"
        }}
    ],
    "metadata": {{
        "total_slides": {slide_count},
        "theme": "white",
        "estimated_duration": "estimated time in minutes"
    }}
}}

Maximize the use of available space with comprehensive content while maintaining readability.
"""


class CodingQuestionSlideAgent(SlideAgent):
    """
    Specialized slide agent for coding interview questions and solutions.
    
    This agent creates slides optimized for learning coding concepts,
    with proper code formatting, step-by-step explanations, and
    interview-focused content structure.
    """
    
    def __init__(self, keys, writer_model: Union[List[str], str], demo_mode: bool = False):
        """
        Initialize the CodingQuestionSlideAgent.
        
        Args:
            keys: API keys for LLM access
            writer_model: Model(s) to use for content generation
            demo_mode: If True, generates standalone HTML; if False, embedded HTML
        """
        super().__init__(keys, writer_model, demo_mode)
        
        # Specialized prompt for coding content - HTML format with comprehensive coverage
        self.base_slide_prompt = """
You are an expert coding instructor creating educational slides for coding interview preparation using Reveal.js HTML format.

Create approximately {slide_count} slides from the following coding content. Use the EXACT HTML structure like this example:

An example:


<h3>Problem Title</h3>
<p>Problem Description</p>
<p><strong>Constraints:</strong> Constraints</p>
<div class="fragment">
    <pre><code class="python">
# Example with detailed explanation
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
Explanation: nums[0] + nums[1] = 2 + 7 = 9
    </code></pre>
</div>
<div class="fragment">
    <ul>
        <li>Brute force approach: O(n²) time complexity</li>
        <li>Hash map approach: O(n) time, O(n) space</li>
        <li>Two pointer (sorted): O(n log n) time</li>
    </ul>
</div>

CRITICAL FORMATTING REQUIREMENTS:
- Use <pre><code class="python">code here</code></pre> for ALL Python code blocks
- Use <pre><code class="javascript">code here</code></pre> for JavaScript code  
- Do NOT use markdown triple backticks (```) - only HTML tags
- Use <div class="fragment">content</div> for progressive disclosure
- Use <div class="complexity-analysis">Time: O(n) | Space: O(1)</div> for complexity
- Use <div class="algorithm-step">Step 1: Description</div> for step-by-step explanations
- With mildy increased viewport height, include comprehensive content (up to 8 lines per slide)
- Include multiple approaches, detailed explanations, and complete code examples
- Address the immediate question or problem statement asked by the user.
- Give informative slide titles.
- Cover the content in the slides within the <main-content> tag.
- Ignore conversation history and only focus on the content within the <main-content> tag.
- We are preparing for a coding interview so focus on that aspect and algorithms, code solutions and approaches etc.

Structure slides for interview preparation:
1. Problem Overview - statement, examples, constraints, edge cases
2. Approach Analysis - multiple approaches with complexity analysis
3. Approach Deep Dive - detailed explanation of the each approach.
    - Pseudocode, analysis and explanation for approach 1
    - Pseudocode, analysis and explanation for approach 2
    - ...
4. Implementation - complete code solutions with comments
    - Code for approach 1
    - Code for approach 2
    - ...
5. Algorithm Walkthrough - detailed step-by-step execution of the best approach
7. Edge Cases - comprehensive edge cases scenarios

Content to convert:
{content}

Generate the slides in the following JSON format:
{{
    "slides": [
        {{
            "title": "Informational Section/Slide Title", 
            "content": "<h3>Two Sum Problem</h3><p>Comprehensive description with constraints.</p><div class='fragment'><pre><code class='python'>detailed_example_with_explanation()</code></pre></div><ul><li>Approach 1</li><li>Approach 2</li></ul>",
            "background": "optional background color",
            "transition": "slide",
            "notes": "Key teaching points and interview tips"
        }}
    ],
    "metadata": {{
        "total_slides": {slide_count},
        "theme": "white",
        "estimated_duration": "estimated time in minutes"
    }}
}}

Maximize content density while maintaining clarity for comprehensive interview preparation.
"""
        
        # Override reveal config for better code presentation
        self.reveal_config.update({
            "theme": "white",  # Better for code readability
            "transition": "slide",
            "center": False  # Left-align for better code display
        })

    def _generate_embedded_html(self, slides_html: str, slide_data: Dict) -> str:
        """
        Generate HTML for embedding with coding-specific styling.
        
        Args:
            slides_html: HTML content for slides
            slide_data: Slide metadata
            
        Returns:
            HTML for embedding with coding enhancements
        """
        base_html = super()._generate_embedded_html(slides_html, slide_data)
        
        # Add coding-specific styling
        coding_styles = """
        <style>
            .reveal pre {
                width: 100%;
                box-shadow: 0px 5px 15px rgba(0, 0, 0, 0.15);
                border-radius: 5px;
            }
            .reveal pre code {
                max-height: 400px;
                font-size: 0.8em;
                line-height: 1.4;
                padding: 20px;
            }
            .reveal .slides section {
                text-align: left;
            }
            .reveal h2 {
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }
            .complexity-analysis {
                background: #ecf0f1;
                padding: 15px;
                border-radius: 5px;
                margin: 10px 0;
            }
            .algorithm-step {
                background: #e8f6f3;
                padding: 10px;
                border-left: 4px solid #1abc9c;
                margin: 8px 0;
            }
        </style>
        """
        
        return coding_styles + base_html

    def _generate_standalone_html(self, slides_html: str, slide_data: Dict) -> str:
        """
        Generate standalone HTML with coding-specific enhancements.
        
        Args:
            slides_html: HTML content for slides  
            slide_data: Slide metadata
            
        Returns:
            Complete HTML document with coding optimizations
        """
        base_html = super()._generate_standalone_html(slides_html, slide_data)
        
        # Replace the entire style section with clean, non-conflicting CSS
        try:
            enhanced_html = re.sub(
                r'<style>.*?</style>',
                """<style>
        /* Clean coding-specific slide styling */
        .slide-content {
            text-align: left;
            font-size: 0.8em;
            line-height: 1.2;
        }
        
        /* Optimized code blocks for coding slides */
        .reveal pre {
            width: 100%;
            margin: 4px 0;
            box-shadow: 0px 3px 10px rgba(0, 0, 0, 0.1);
            border-radius: 4px;
        }
        
        .reveal pre code {
            max-height: 52vh;
            font-size: 0.5em;
            line-height: 1.1;
            padding: 6px;
            overflow-y: auto;
            display: block;
            white-space: pre;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            tab-size: 4;
            background: #f8f8f8;
            border: 1px solid #e1e1e8;
        }
        
        /* Auto-indent Python code visually */
        .reveal pre code.python {
            text-indent: 0;
        }
        
        /* Allow Reveal.js to handle slide positioning for coding slides - DO NOT override */
        .reveal .slides section {
            /* Only set non-positioning styles */
            text-align: left;
            padding: 0;
            font-size: 0.7em;
            /* DO NOT set position, top, left, transform, display, or height */
            /* Reveal.js will handle these internally */
        }
        
        /* Scrollable content wrapper for coding slides */
        .reveal .slides section .slide-content {
            width: 100%;
            height: calc(88vh - 40px); /* Slightly reduced to ensure last line visibility */
            max-height: calc(88vh - 40px);
            overflow-y: auto;
            overflow-x: hidden;
            padding: 15px;
            padding-bottom: 20px; /* Extra bottom padding to ensure last line is visible */
            margin: 0;
            /* Smooth scrolling */
            scroll-behavior: smooth;
            /* Custom scrollbar for coding slides */
            scrollbar-width: thin;
            scrollbar-color: #2c3e50 #ecf0f1;
            /* Content styling */
            text-align: left;
            font-size: 0.8em;
            /* Ensure proper positioning */
            position: relative;
            box-sizing: border-box;
            /* Scroll indicator variables */
            --scroll-indicator-opacity: 1;
        }
        
        /* Webkit scrollbar styling for coding slide content */
        .reveal .slides section .slide-content::-webkit-scrollbar {
            width: 10px;
        }
        
        .reveal .slides section .slide-content::-webkit-scrollbar-track {
            background: #ecf0f1;
            border-radius: 5px;
        }
        
        .reveal .slides section .slide-content::-webkit-scrollbar-thumb {
            background: #2c3e50;
            border-radius: 5px;
        }
        
        .reveal .slides section .slide-content::-webkit-scrollbar-thumb:hover {
            background: #34495e;
        }
        
        /* Compact headers */
        .reveal .slides section h1,
        .reveal .slides section h2 {
            margin-top: 0;
            margin-bottom: 0.2em;
            font-size: 1.0em;
            line-height: 1.0;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 4px;
        }
        
        .reveal .slides section h3 {
            font-size: 0.9em;
            margin-bottom: 0.1em;
        }
        
        /* Tight spacing */
        .reveal ul, .reveal ol {
            margin: 0.2em 0;
        }
        
        .reveal li {
            margin: 0.03em 0;
            font-size: 0.75em;
            line-height: 1.05;
        }
        .reveal ul ul, .reveal ol ol {
            margin-top: 0.05em;
            margin-bottom: 0.05em;
        }
        .reveal ul li + li, .reveal ol li + li {
            margin-top: 0.05em;
        }
        
        .reveal p {
            margin: 0.08em 0;
            line-height: 1.05;
            font-size: 0.75em;
        }
        
        /* Special coding elements */
        .complexity-analysis {
            background: #ecf0f1;
            padding: 6px;
            border-radius: 3px;
            margin: 4px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.7em;
            line-height: 1.1;
        }
        
        .algorithm-step {
            background: #e8f6f3;
            padding: 5px;
            border-left: 3px solid #1abc9c;
            margin: 3px 0;
            font-size: 0.75em;
            line-height: 1.1;
        }
        
        .test-case {
            background: #fdf2e9;
            padding: 5px;
            border-left: 3px solid #e67e22;
            margin: 3px 0;
            font-size: 0.75em;
        }
        
        /* Ensure content fits */
        .reveal .slides section > * {
            max-width: 100%;
            box-sizing: border-box;
        }
        
        /* Better inline code styling */
        .reveal code {
            font-size: 0.85em;
            padding: 2px 6px;
            background: #f4f4f4;
            border-radius: 3px;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            color: #c7254e;
            border: 1px solid #e1e1e8;
        }
        
        /* Mobile responsive with better scrolling */
        @media (max-width: 768px) {
            .reveal .slides section {
                font-size: 0.65em;
                max-height: 85vh;
                padding: 6px !important;
            }
            .reveal pre code {
                font-size: 0.4em;
                max-height: 45vh;
            }
        }
        
        @media (max-height: 600px) {
            /* Handle short viewport heights for coding slides */
            .reveal .slides section {
                max-height: 92vh;
                font-size: 0.6em;
                padding: 4px !important;
            }
            .reveal pre code {
                max-height: 30vh;
                font-size: 0.35em;
            }
        }
        
        @media (max-height: 500px) {
            /* Very short viewports for coding slides */
            .reveal .slides section {
                max-height: 95vh;
                font-size: 0.55em;
                padding: 2px !important;
            }
            .reveal pre code {
                max-height: 25vh;
                font-size: 0.3em;
            }
        }
    </style>""",
                base_html,
                flags=re.DOTALL
            )
        except Exception as e:
            print(f"Error replacing CSS: {e}")
            enhanced_html = base_html
        
        return enhanced_html
