import os
import json
import random
import traceback
from typing import Union, List, Dict, Optional
from pathlib import Path
import re

# Local imports
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from base import CallLLm, CallMultipleLLM
    from common import (
        CHEAP_LLM, EXPENSIVE_LLM, LONG_CONTEXT_LLM, CHEAP_LONG_CONTEXT_LLM,
        sleep_and_get_future_result, collapsible_wrapper
    )
    from very_common import get_async_future
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

import logging
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)

from .base_agent import Agent

# ============================================================================
# LLM PROMPTS - Defined at the top level
# ============================================================================

DOCUMENT_ANALYSIS_PROMPT = """
You are analyzing a large document to provide a comprehensive overview before editing begins.

## Document to Analyze:
<document>
{document}
</document>

Please provide a thorough analysis covering the following aspects:

## 1. Document Structure and Table of Contents
Create a detailed, hierarchical table of contents showing:
- Main sections and subsections
- Key topics covered in each section
- Approximate length/importance of each section
- Overall document organization and flow

## 2. Executive Summary
Write a comprehensive summary (300-500 words) that captures:
- The document's main purpose and audience
- Core arguments or messages
- Key themes throughout the document
- Overall tone and style
- Document type and genre

## 3. Key Takeaways and Facts
List the most important:
- Key takeaways (5-10 main points)
- Important facts and data points
- Critical insights or findings
- Notable quotes or statements
- Technical details or specifications mentioned

## 4. Action Items and Decision Points
Identify and list:
- **Action Items**: Any tasks, to-dos, or actions mentioned that need to be taken
- **Asks/Requests**: Any specific requests made in the document
- **Decision Points**: Areas requiring decision-making or choices to be made
- **Open Questions**: Unresolved questions or areas needing clarification
- **Conflicts/Contradictions**: Any conflicting information or viewpoints presented
- **Dependencies**: Items that depend on other actions or decisions

## 5. Document Metrics
Provide:
- Word count: {word_count}
- Estimated reading time
- Complexity level (technical/general audience)
- Completeness assessment

Format your response with clear markdown headers and bullet points for easy scanning.
"""

SUGGESTION_EXTRACTION_PROMPT = """
You are a professional editor reviewing a document against specific writing guidelines.

Given the following writing guideline document and a user's document, provide an exhaustive list of suggestions for improvements based on the guidelines.

## Writing Guideline:
<guideline>
{guideline_content}
</guideline>

{document_analysis_section}

## User's Document:
<document>
{document}
</document>

## Instructions:
1. Carefully analyze the document against the provided guideline
2. If document analysis is provided, use it to understand the document's structure, purpose, and key areas
3. Generate specific, actionable suggestions for improvement
4. Each suggestion should reference the specific guideline it relates to
5. Consider the document's identified action items, decision points, and conflicts when making suggestions
6. Score each suggestion from 1-10 based on importance:
   - 10-9: Critical issues that must be fixed
   - 8-7: Important improvements for clarity/correctness
   - 6-5: Moderate improvements for style/flow
   - 4-3: Minor improvements for polish
   - 2-1: Nitpicks or optional enhancements

## Output Format:
Provide your response as a JSON array with the following structure:
```json
[
    {
        "suggestion": "Specific suggestion text",
        "guideline_reference": "Which guideline this relates to",
        "location": "Where in the document this applies (quote a snippet)",
        "priority_score": 8,
        "category": "grammar/style/structure/clarity/etc",
        "rationale": "Why this change is important"
    },
    ...
]
```

Generate comprehensive suggestions covering all aspects of the guidelines.
"""

DEDUPLICATION_PROMPT_STAGE1 = """
You are tasked with consolidating and deduplicating suggestions from multiple sources.

Given the following groups of suggestions, identify duplicates and merge similar suggestions while preserving unique insights.

## Suggestions to Consolidate:
<suggestions>
{suggestions_json}
</suggestions>

## Instructions:
1. Identify suggestions that are essentially the same or very similar
2. Merge similar suggestions into single, comprehensive suggestions
3. Preserve the highest priority score when merging
4. Keep unique suggestions intact
5. Maintain all important details from merged suggestions

## Output Format:
Return a JSON array with consolidated suggestions in the same format as the input, reducing the total number by approximately 4x while preserving all unique insights.

```json
[
    {
        "suggestion": "Consolidated suggestion text",
        "guideline_reference": "Combined guideline references",
        "location": "Where in the document this applies",
        "priority_score": 8,
        "category": "category",
        "rationale": "Combined rationale",
        "merged_from": ["original suggestion 1", "original suggestion 2"]
    },
    ...
]
```
"""

DEDUPLICATION_PROMPT_STAGE2 = """
You are performing the final consolidation of editing suggestions.

Given these partially consolidated suggestions, create a final, deduplicated list with clear priority ordering.

## Suggestions to Finalize:
<suggestions>
{suggestions_json}
</suggestions>

## Instructions:
1. Perform final deduplication, removing any remaining similar suggestions
2. Order suggestions by priority (highest to lowest)
3. Ensure each suggestion is unique and actionable
4. Group related suggestions if helpful
5. Add an execution_order field for applying changes

## Output Format:
Return a JSON array with the final consolidated suggestions:

```json
[
    {
        "suggestion": "Final suggestion text",
        "guideline_reference": "Guideline references",
        "location": "Where in the document this applies",
        "priority_score": 8,
        "category": "category",
        "rationale": "Why this matters",
        "execution_order": 1
    },
    ...
]
```

Order by priority_score descending, then by logical application order.
"""

DELTA_GENERATION_PROMPT = """
You are applying specific editing suggestions to a document.

Given the document and the finalized suggestions, show the specific changes in a before/after format.

## Original Document:
<document>
{document}
</document>

## Suggestions to Apply:
<suggestions>
{suggestions_json}
</suggestions>

## Instructions:
1. For each suggestion, show the exact change to be made
2. Use clear before/after formatting
3. Show enough context to understand the change
4. Apply suggestions in the provided execution_order

## Output Format:
For each change, format as follows:

### Change {number}: {brief description}
**Suggestion**: {the suggestion being applied}
**Priority**: {priority_score}/10

**Before:**
```
{original text snippet with context}
```

**After:**
```
{modified text snippet with context}
```

**Rationale**: {why this change improves the document}

---

Show all changes that should be applied based on the suggestions.
"""

FINAL_DOCUMENT_GENERATION_PROMPT = """
You are creating the final edited version of a document based on approved suggestions.

## Original Document:
<document>
{document}
</document>

## Approved Suggestions:
<suggestions>
{suggestions_json}
</suggestions>

## Instructions:
1. Apply all the suggestions to create the final document
2. Ensure all changes are incorporated smoothly
3. Maintain document flow and coherence
4. Preserve any content not affected by suggestions
5. Apply changes in logical order to avoid conflicts

## Output:
Provide the complete, edited document with all suggestions applied. Do not include any commentary or explanation - just the final document text.

{document_format_instruction}
"""

# ============================================================================
# Main Agent Class
# ============================================================================

class DocumentEditingAgent(Agent):
    """
    An agent that helps modify and edit documents based on specific writing guidelines.
    Can work with a folder of guideline files or a list of specific guideline files.
    """
    
    def __init__(
        self, 
        keys,
        guideline_folder: Optional[str] = None,
        guideline_files: Optional[List[str]] = None,
        model_name: Union[str, List[str]] = None,
        cheap_model: str = None,
        expensive_model: str = None,
        enable_analysis: bool = True,
        analysis_word_threshold: int = 2000,
        enable_dedup: bool = True,
        enable_delta: bool = True,
        enable_final_doc: bool = True,
        dedup_batch_size: int = 4
    ):
        """
        Initialize the DocumentEditingAgent.
        
        Args:
            keys: API keys for LLM access
            guideline_folder: Path to folder containing guideline markdown files
            guideline_files: List of specific guideline file paths
            model_name: Model(s) to use for main operations
            cheap_model: Model for less critical operations (dedup)
            expensive_model: Model for critical operations (final doc)
            enable_analysis: Whether to perform initial document analysis
            analysis_word_threshold: Word count threshold to trigger analysis (default 2000)
            enable_dedup: Whether to perform deduplication
            enable_delta: Whether to generate delta/changes view
            enable_final_doc: Whether to generate final document
            dedup_batch_size: Batch size for first stage deduplication
        """
        super().__init__(keys)
        
        # Model configuration
        self.model_name = model_name or LONG_CONTEXT_LLM[0]
        self.cheap_model = cheap_model or CHEAP_LLM[0]
        self.expensive_model = expensive_model or EXPENSIVE_LLM[0]
        
        # Feature flags for modularity
        self.enable_analysis = enable_analysis
        self.analysis_word_threshold = analysis_word_threshold
        self.enable_dedup = enable_dedup
        self.enable_delta = enable_delta
        self.enable_final_doc = enable_final_doc
        self.dedup_batch_size = dedup_batch_size
        
        # Load guideline files
        self.guideline_contents = self._load_guidelines(guideline_folder, guideline_files)
        
        if not self.guideline_contents:
            raise ValueError("No guideline files found or loaded. Please provide either a guideline_folder or guideline_files.")
        
        logger.info(f"Loaded {len(self.guideline_contents)} guideline files")
    
    def _load_guidelines(
        self, 
        guideline_folder: Optional[str] = None,
        guideline_files: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Load guideline files from folder or specific file list.
        
        Returns:
            Dictionary mapping file path to content
        """
        guidelines = {}
        
        # Load from folder if provided
        if guideline_folder and os.path.exists(guideline_folder):
            folder_path = Path(guideline_folder)
            for file_path in folder_path.glob("*.md"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        guidelines[str(file_path)] = f.read()
                    logger.info(f"Loaded guideline: {file_path}")
                except Exception as e:
                    logger.error(f"Error loading {file_path}: {e}")
        
        # Load specific files if provided
        if guideline_files:
            for file_path in guideline_files:
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            guidelines[file_path] = f.read()
                        logger.info(f"Loaded guideline: {file_path}")
                    except Exception as e:
                        logger.error(f"Error loading {file_path}: {e}")
                else:
                    logger.warning(f"Guideline file not found: {file_path}")
        
        return guidelines
    
    def _count_words(self, text: str) -> int:
        """
        Count the number of words in the text.
        """
        return len(text.split())
    
    def _analyze_document(
        self,
        document: str,
        word_count: int,
        temperature: float = 0.7,
        stream: bool = True
    ):
        """
        Perform initial analysis of the document.
        """
        llm = CallLLm(self.keys, self.model_name if isinstance(self.model_name, str) else self.model_name[0])
        
        prompt = DOCUMENT_ANALYSIS_PROMPT.format(
            document=document,
            word_count=word_count
        )
        
        response = llm(prompt, temperature=temperature, stream=stream)
        
        if stream:
            for chunk in response:
                yield chunk
        else:
            yield response
    
    def _extract_json_from_response(self, response: str) -> List[Dict]:
        """
        Extract JSON array from LLM response, handling markdown code blocks.
        """
        # Try to find JSON in code blocks first
        json_pattern = r'```(?:json)?\s*(.*?)```'
        matches = re.findall(json_pattern, response, re.DOTALL)
        
        if matches:
            json_str = matches[-1].strip()
        else:
            # Try to find raw JSON array
            json_str = response.strip()
            # Find the JSON array boundaries
            start_idx = json_str.find('[')
            end_idx = json_str.rfind(']')
            if start_idx != -1 and end_idx != -1:
                json_str = json_str[start_idx:end_idx+1]
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response was: {response[:500]}...")
            return []
    
    def _generate_suggestions_for_guideline(
        self, 
        document: str, 
        guideline_path: str, 
        guideline_content: str,
        document_analysis: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> List[Dict]:
        """
        Generate suggestions for a single guideline file.
        """
        llm = CallLLm(self.keys, self.model_name if isinstance(self.model_name, str) else self.model_name[0])
        
        # Include document analysis if available
        document_analysis_section = ""
        if document_analysis:
            document_analysis_section = f"""## Document Analysis Context:
<analysis>
{document_analysis}
</analysis>
"""
        
        prompt = SUGGESTION_EXTRACTION_PROMPT.format(
            guideline_content=guideline_content,
            document=document,
            document_analysis_section=document_analysis_section
        )
        
        response = llm(prompt, temperature=temperature, stream=False, max_tokens=max_tokens)
        suggestions = self._extract_json_from_response(response)
        
        # Add source guideline to each suggestion
        for suggestion in suggestions:
            suggestion['source_guideline'] = os.path.basename(guideline_path)
        
        return suggestions
    
    def _deduplicate_stage1(
        self, 
        suggestions: List[Dict],
        temperature: float = 0.7
    ) -> List[Dict]:
        """
        First stage deduplication - reduce by batch_size factor (parallelized).
        """
        if len(suggestions) <= self.dedup_batch_size:
            return suggestions
        
        # Create futures for parallel batch processing
        batch_futures = []
        for i in range(0, len(suggestions), self.dedup_batch_size):
            batch = suggestions[i:i+self.dedup_batch_size]
            
            # Create a function to process this batch
            def process_batch(batch_data):
                llm = CallLLm(self.keys, self.cheap_model)
                prompt = DEDUPLICATION_PROMPT_STAGE1.format(
                    suggestions_json=json.dumps(batch_data, indent=2)
                )
                response = llm(prompt, temperature=temperature, stream=False)
                return self._extract_json_from_response(response)
            
            future = get_async_future(process_batch, batch)
            batch_futures.append(future)
        
        # Collect results from all batches
        consolidated = []
        for future in batch_futures:
            try:
                batch_consolidated = sleep_and_get_future_result(future, timeout=30)
                consolidated.extend(batch_consolidated)
            except Exception as e:
                logger.error(f"Error in batch deduplication: {e}")
                # On error, just skip this batch's deduplication
        
        return consolidated
    
    def _deduplicate_stage2(
        self, 
        suggestions: List[Dict],
        temperature: float = 0.7
    ) -> List[Dict]:
        """
        Final stage deduplication - create final consolidated list.
        """
        llm = CallLLm(self.keys, self.model_name if isinstance(self.model_name, str) else self.model_name[0])
        
        prompt = DEDUPLICATION_PROMPT_STAGE2.format(
            suggestions_json=json.dumps(suggestions, indent=2)
        )
        
        response = llm(prompt, temperature=temperature, stream=False)
        return self._extract_json_from_response(response)
    
    def _generate_delta(
        self, 
        document: str,
        suggestions: List[Dict],
        temperature: float = 0.7,
        stream: bool = True
    ):
        """
        Generate before/after changes for the suggestions.
        """
        llm = CallLLm(self.keys, self.model_name if isinstance(self.model_name, str) else self.model_name[0])
        
        prompt = DELTA_GENERATION_PROMPT.format(
            document=document,
            suggestions_json=json.dumps(suggestions, indent=2)
        )
        
        response = llm(prompt, temperature=temperature, stream=stream)
        
        if stream:
            for chunk in response:
                yield chunk
        else:
            yield response
    
    def _generate_delta_non_streaming(
        self,
        document: str,
        suggestions: List[Dict],
        temperature: float = 0.7
    ) -> str:
        """
        Non-streaming version for parallel execution.
        """
        llm = CallLLm(self.keys, self.model_name if isinstance(self.model_name, str) else self.model_name[0])
        
        prompt = DELTA_GENERATION_PROMPT.format(
            document=document,
            suggestions_json=json.dumps(suggestions, indent=2)
        )
        
        return llm(prompt, temperature=temperature, stream=False)
    
    def _generate_final_document(
        self, 
        document: str,
        suggestions: List[Dict],
        document_format: str = "",
        temperature: float = 0.7,
        stream: bool = True
    ):
        """
        Generate the final edited document with all suggestions applied.
        """
        llm = CallLLm(self.keys, self.expensive_model)
        
        format_instruction = f"The document should maintain its original format: {document_format}" if document_format else ""
        
        prompt = FINAL_DOCUMENT_GENERATION_PROMPT.format(
            document=document,
            suggestions_json=json.dumps(suggestions, indent=2),
            document_format_instruction=format_instruction
        )
        
        response = llm(prompt, temperature=temperature, stream=stream)
        
        if stream:
            for chunk in response:
                yield chunk
        else:
            yield response
    
    def _generate_final_document_non_streaming(
        self,
        document: str,
        suggestions: List[Dict],
        document_format: str = "",
        temperature: float = 0.7
    ) -> str:
        """
        Non-streaming version for parallel execution.
        """
        llm = CallLLm(self.keys, self.expensive_model)
        
        format_instruction = f"The document should maintain its original format: {document_format}" if document_format else ""
        
        prompt = FINAL_DOCUMENT_GENERATION_PROMPT.format(
            document=document,
            suggestions_json=json.dumps(suggestions, indent=2),
            document_format_instruction=format_instruction
        )
        
        return llm(prompt, temperature=temperature, stream=False)
    
    def __call__(
        self, 
        text: str,
        images: List = [],
        temperature: float = 0.7,
        stream: bool = True,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
        web_search: bool = False,
        document_format: str = "markdown"
    ):
        """
        Process a document through the editing pipeline.
        
        Args:
            text: The document to edit
            images: Not used in this agent
            temperature: LLM temperature
            stream: Whether to stream responses
            max_tokens: Maximum tokens for responses
            system: System prompt (not used)
            web_search: Not used in this agent
            document_format: Format of the document (for final generation)
        """
        
        # Step 0: Document Analysis (if enabled and document is large enough)
        word_count = self._count_words(text)
        document_analysis = None
        
        if self.enable_analysis and word_count >= self.analysis_word_threshold:
            yield f"## Initial Document Analysis\n\n"
            yield f"*Document contains {word_count:,} words, performing comprehensive analysis...*\n\n"
            
            # Capture the analysis for later use
            analysis_chunks = []
            for chunk in self._analyze_document(text, word_count, temperature, stream=False):
                analysis_chunks.append(chunk)
            document_analysis = ''.join(analysis_chunks)
            
            # Display the analysis with collapsible wrapper
            yield from collapsible_wrapper(
                iter([document_analysis]),
                header="Document Overview and Analysis",
                show_initially=True
            )
            
            yield "\n\n---\n\n"
        elif word_count < self.analysis_word_threshold:
            yield f"*Document contains {word_count:,} words (below {self.analysis_word_threshold:,} word threshold), skipping initial analysis.*\n\n"
        
        # Step 1: Generate suggestions from each guideline (in parallel)
        yield "## Analyzing Document Against Guidelines\n\n"
        
        # Start all guideline suggestion generation in parallel
        guideline_futures = []
        for guideline_path, guideline_content in self.guideline_contents.items():
            future = get_async_future(
                self._generate_suggestions_for_guideline,
                text, guideline_path, guideline_content,
                document_analysis, temperature, max_tokens
            )
            guideline_futures.append((guideline_path, future))
        
        # Collect results and display as they complete
        all_suggestions = []
        for i, (guideline_path, future) in enumerate(guideline_futures, 1):
            guideline_name = os.path.basename(guideline_path)
            
            # Get suggestions from future
            try:
                suggestions = sleep_and_get_future_result(future, timeout=60)
            except Exception as e:
                logger.error(f"Error getting suggestions for {guideline_name}: {e}")
                suggestions = []
            
            # Format and display suggestions in collapsible section
            def format_guideline_suggestions():
                if suggestions:
                    yield f"Found **{len(suggestions)}** suggestions from {guideline_name}:\n\n"
                    yield from self._format_suggestions_display(suggestions)
                else:
                    yield f"No suggestions from {guideline_name}.\n"
            
            yield from collapsible_wrapper(
                format_guideline_suggestions(),
                header=f"Guideline {i}: {guideline_name}",
                show_initially=(i == 1)
            )
            
            # Add to all suggestions
            all_suggestions.extend(suggestions)
        
        yield f"\n**Total suggestions generated: {len(all_suggestions)}**\n\n"
        
        # Step 2: Deduplication (if enabled)
        if self.enable_dedup and len(all_suggestions) > 1:
            yield "## Consolidating Suggestions\n\n"
            
            # Stage 1 deduplication
            yield "### Stage 1: Initial Consolidation\n"
            stage1_suggestions = self._deduplicate_stage1(all_suggestions, temperature)
            yield f"Reduced from {len(all_suggestions)} to {len(stage1_suggestions)} suggestions.\n\n"
            
            # Stage 2 deduplication
            yield "### Stage 2: Final Consolidation\n"
            final_suggestions = self._deduplicate_stage2(stage1_suggestions, temperature)
            yield f"Final suggestion count: {len(final_suggestions)}\n\n"
            
            # Display final suggestions
            yield from collapsible_wrapper(
                self._format_suggestions_display(final_suggestions),
                header="Final Consolidated Suggestions",
                show_initially=True
            )
        else:
            final_suggestions = all_suggestions
            yield from collapsible_wrapper(
                self._format_suggestions_display(final_suggestions),
                header="All Suggestions",
                show_initially=True
            )
        
        # Step 3 & 4: Start delta and final document generation in parallel (if enabled)
        delta_future = None
        final_doc_future = None
        
        if final_suggestions:
            # Start both operations in parallel if enabled
            if self.enable_delta:
                delta_future = get_async_future(
                    self._generate_delta_non_streaming,
                    text, final_suggestions, temperature
                )
            
            if self.enable_final_doc:
                final_doc_future = get_async_future(
                    self._generate_final_document_non_streaming,
                    text, final_suggestions, document_format, temperature
                )
        
        # Display delta results if enabled
        if delta_future:
            yield "\n## Suggested Changes (Before/After)\n\n"
            try:
                delta_result = sleep_and_get_future_result(delta_future, timeout=60)
                yield from collapsible_wrapper(
                    iter([delta_result]),
                    header="Document Changes Preview",
                    show_initially=True
                )
            except Exception as e:
                logger.error(f"Error generating delta: {e}")
                yield f"*Error generating change preview: {e}*\n"
            yield "\n\n"
        
        # Display final document if enabled
        if final_doc_future:
            yield "\n## Final Edited Document\n\n"
            try:
                final_doc = sleep_and_get_future_result(final_doc_future, timeout=60)
                yield from collapsible_wrapper(
                    iter([final_doc]),
                    header="Complete Edited Document",
                    show_initially=False
                )
            except Exception as e:
                logger.error(f"Error generating final document: {e}")
                yield f"*Error generating final document: {e}*\n"
            yield "\n\n"
        
        yield "\n---\n*Document editing complete.*\n"
    
    def _format_suggestions_display(self, suggestions: List[Dict]):
        """
        Format suggestions for display.
        """
        # Sort by priority
        sorted_suggestions = sorted(suggestions, key=lambda x: x.get('priority_score', 0), reverse=True)
        
        for i, suggestion in enumerate(sorted_suggestions, 1):
            priority = suggestion.get('priority_score', 0)
            category = suggestion.get('category', 'general')
            
            # Priority indicator
            if priority >= 9:
                priority_indicator = "🔴 **CRITICAL**"
            elif priority >= 7:
                priority_indicator = "🟠 **Important**"
            elif priority >= 5:
                priority_indicator = "🟡 **Moderate**"
            else:
                priority_indicator = "🟢 **Minor**"
            
            yield f"**{i}. {priority_indicator} (Score: {priority}/10)** - {category}\n"
            yield f"   - **Suggestion**: {suggestion.get('suggestion', '')}\n"
            
            if suggestion.get('location'):
                yield f"   - **Location**: `{suggestion.get('location', '')[:100]}...`\n"
            
            if suggestion.get('rationale'):
                yield f"   - **Rationale**: {suggestion.get('rationale', '')}\n"
            
            if suggestion.get('guideline_reference'):
                yield f"   - **Guideline**: {suggestion.get('guideline_reference', '')}\n"
            
            if suggestion.get('source_guideline'):
                yield f"   - **Source**: {suggestion.get('source_guideline', '')}\n"
            
            yield "\n"


# ============================================================================
# Convenience Functions
# ============================================================================

def create_document_editor(
    keys,
    guideline_folder: Optional[str] = None,
    guideline_files: Optional[List[str]] = None,
    **kwargs
) -> DocumentEditingAgent:
    """
    Convenience function to create a DocumentEditingAgent.
    
    Args:
        keys: API keys for LLM access
        guideline_folder: Path to folder containing guideline markdown files
        guideline_files: List of specific guideline file paths
        **kwargs: Additional arguments for DocumentEditingAgent including:
            - enable_analysis: Whether to perform initial analysis (default True)
            - analysis_word_threshold: Word count threshold (default 2000)
            - enable_dedup: Whether to deduplicate suggestions
            - enable_delta: Whether to show before/after changes
            - enable_final_doc: Whether to generate final document
            - model_name: Model(s) to use
            - cheap_model: Model for less critical operations
            - expensive_model: Model for critical operations
    
    Returns:
        Configured DocumentEditingAgent instance
    """
    return DocumentEditingAgent(
        keys=keys,
        guideline_folder=guideline_folder,
        guideline_files=guideline_files,
        **kwargs
    )
