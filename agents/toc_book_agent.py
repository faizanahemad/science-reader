import random
from typing import Union, List
import uuid
from prompts import tts_friendly_format_instructions

import os
import tempfile
import shutil
import concurrent.futures
import logging
from openai import OpenAI
from pydub import AudioSegment  # For merging audio files


# Local imports  
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from prompts import tts_friendly_format_instructions
    from base import CallLLm, CallMultipleLLM, simple_web_search_with_llm
    from common import (
        CHEAP_LLM, USE_OPENAI_API, convert_markdown_to_pdf,
        get_async_future, sleep_and_get_future_result, convert_stream_to_iterable
    )
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

import logging
import re
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)
import time
from .base_agent import Agent
from .tts_and_podcast_agent import TTSAgent, StreamingPodcastAgent, PodcastAgent


  
import asyncio  
import logging  
import re  
import time  
import random  
from concurrent.futures import ThreadPoolExecutor  
from dataclasses import dataclass, field  
from typing import Dict, List, Optional, Union, Callable, Any  
from datetime import datetime  
  
def run_async_in_thread(async_func, *args, **kwargs):
    """Run an async function in a separate thread with its own event loop."""
    # print(f"Running async function in a separate thread: {async_func.__name__}")
    def run_in_new_loop():
        # print(f"Running in a new loop")
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(async_func(*args, **kwargs))
        finally:
            new_loop.close()
    
    with ThreadPoolExecutor() as executor:
        return executor.submit(run_in_new_loop).result()  

# Configure logging  
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')  
logger = logging.getLogger("ToC_Book_Agent")  
  
class RateLimiter:  
    """Manage API rate limiting."""  
    def __init__(self, calls_per_minute: int = 50):  
        self.calls_per_minute = calls_per_minute  
        self.calls = []  
        try:
            loop = asyncio.get_event_loop()
            self.lock = asyncio.Lock()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.lock = asyncio.Lock()
  
    async def acquire(self):  
        """Acquire permission to make an API call."""  
        async with self.lock:  
            now = time.time()  
            self.calls = [call for call in self.calls if now - call < 60]  
            if len(self.calls) >= self.calls_per_minute:  
                wait_time = 60 - (now - self.calls[0])  
                logger.debug(f"Rate limit reached, waiting for {wait_time:.2f} seconds")  
                await asyncio.sleep(wait_time)  
            self.calls.append(now)  
            return True  
  
@dataclass  
class ToCGenerationResult:  
    """Container for ToC generation results."""  
    initial_toc: str = ""  
    terminology: str = ""  
    advanced_concepts: str = ""  
    toc_critique: str = ""  
    enhanced_toc: str = ""  
    section_enhancements: Dict[str, str] = None  
    final_toc: str = ""  
    processing_time: float = 0  
      
    def __post_init__(self):  
        if self.section_enhancements is None:  
            self.section_enhancements = {}  
  
toc_creation_prompt = """  
# Table of Contents Generation and Enhancement System  
  
## CONTEXT  
{task}  
Topic: {query}  
{existing_toc}  
{terminology}  
{advanced_concepts}  
{critique}  
  
## OBJECTIVE  
Create a comprehensive, hierarchically structured Table of Contents that progresses from foundational to advanced concepts, incorporating provided feedback and enhancements where available.  
  
## REQUIRED STRUCTURE  
  
### 1. MAIN PARTS  
Structure the content into three progressive levels:  
  
#### PART I: FOUNDATIONS  
- Core concepts and terminology  
- Basic principles and methodologies  
- Fundamental theories  
- Introductory examples and applications  
  
#### PART II: INTERMEDIATE CONCEPTS  
- Advanced principles  
- Practical implementations  
- Industry applications  
- Real-world case studies  
  
#### PART III: ADVANCED TOPICS  (PhD or professional level)
- Cutting-edge research  
- Theoretical extensions  
- Complex applications  
- Future directions  
  
### 2. CHAPTER STRUCTURE  
Each chapter must include:  
- Chapter Overview  
- Learning Objectives  
- Core Concepts (Name of the concept)
- Practical Applications (Brief name and description of the application)
- Case Studies (Brief name and description of the case study) 
- Further Reading (What to read next to go deeper into the topic)
- Tables for any comparisons.
- Equations for any formulas.
- Examples for Concepts, Calculations and Applications
- Learning Objectives for each section and what the reader should be able to do after reading the section and chapter.
  
### 3. FORMATTING REQUIREMENTS  
- Use proper markdown headings (# for chapters, ## for sections)  
- Enclose each chapter in <chapter> tags and close the chapter with </chapter> tags.
- Maintain consistent indentation  
- Include brief descriptions for each section  
  
## OUTPUT GUIDELINES  
  
1. Hierarchical Organization:  
   - Clear progression of concepts  
   - Logical dependencies  
   - Sequential skill building  
   - Knowledge prerequisites  
  
2. Content Balance:  
   - Theory vs. Practice  
   - Basic vs. Advanced topics  
   - Concepts vs. Applications  
   - Examples vs. Explanations
  
3. Comprehensive Coverage:  
   - Core domain concepts  
   - Industry standards  
   - Best practices  
   - Modern approaches  
   - Future trends  
   - Applications
   - Side content for context and background.
   - Cross disciplinary applications and concepts.
   - Cross Domain applications and concepts.
  
4. Learning Support:  
   - Case studies  
   - Real-world examples 
   - Practical Guidance  
    
  
## SPECIAL INSTRUCTIONS  
- Ensure XML tags for chapters: <chapter>content</chapter>  
- Maintain consistent depth across sections  
- Include cross-references where relevant  
- Consider both academic and industry perspectives  
- Incorporate provided terminology and advanced concepts if available  
- Address critique points if provided.
- The content hierarchy should be as follows: Part I: Introduction, Part II: Intermediate Concepts, Part III: Advanced Topics and any other parts that are relevant. Then each part should have chapters, and each chapter should have sections. So part > chapter > section.
- Every individual atomic chapter should have a title, and start as "## Chapter X: Title" followed by the content. 
- Cover a wide range of topics, applications, recent developments, and concepts.
- Cover a wide range of complexity levels, from basic to advanced.
- Look at giving a comprehensive coverage of the topic, including all important concepts, applications, caveats, strategies, and usages.
- If an existing ToC is provided, enhance it based on the critique and the new information. Keep all content from the original ToC while enhancing it.
- Give newline characters between each section and chapter.
- There are 4 types of tasks of which you will be given one at a time:
    - Base ToC creation: Create a ToC for a given topic.
    - ToC Update: Update an existing ToC based on a critique and new information.
    - Terminology identification and classification: Generate a comprehensive, classified list of terminology for each chapter and section, categorizing terms by importance and complexity level.
    - Advanced Concepts: Identify advanced applications and concepts and write a comprehensive list of them in the form of an advanced applications, usage, cross disciplinary applications and concepts section, only focusing on the most advanced concepts and applications, cross disciplinary applications, less known trivia, hard to understand concepts, and other difficult material around the topic.
- When the task is Terminology classification, the output should be a list of terms with their classification as "Core", "Advanced", "Intermediate", "Basic", "Trivia", "Hard to understand", "Cross disciplinary", "Cross domain" in a bulleted list format.
- When the task is Advanced Concepts, the output should be a single chapter with the title "Advanced Applications and Concepts" and extensive ToC of only the advanced concepts, applications, cross disciplinary applications and concepts.
- Write your output or answer for the given task above in a code block in markdown format.

Generate a detailed Table of Contents following these guidelines, ensuring comprehensive coverage while maintaining a clear learning progression from basic to advanced concepts.  
"""  


toc_checker_prompt = """  
# Table of Contents Evaluation System  
  
## CONTEXT  
Topic: {query}  
Current ToC:  
{toc}  
  
## OBJECTIVE  
Perform a comprehensive analysis of the provided Table of Contents, identifying gaps, inconsistencies, and opportunities for enhancement.  
  
## EVALUATION DIMENSIONS  
  
### 1. STRUCTURAL ANALYSIS  
- Logical flow and progression  
- Hierarchical organization  
- Topic dependencies  
- Learning path coherence  
  
### 2. CONTENT COVERAGE  
- Core concept completeness  
- Practical application scope  
- Advanced topic representation  
- Industry relevance  
  
### 3. PEDAGOGICAL EFFECTIVENESS  
- Learning progression  
- Skill development path  
- Knowledge prerequisites  
- Assessment opportunities  
  
### 4. MODERN RELEVANCE  
- Current technologies  
- Industry trends  
- Research directions  
- Future applications  
  
## CRITIQUE FRAMEWORK  
  
### 1. Gap Analysis  
Identify:  
- Missing fundamental concepts  
- Overlooked applications  
- Incomplete topic coverage  
- Weak connections  
  
### 2. Balance Assessment  
Evaluate:  
- Theory vs. Practice ratio  
- Basic vs. Advanced content  
- Academic vs. Industry focus  
- Individual vs. Team learning  
  
### 3. Enhancement Opportunities  
Suggest:  
- Additional topics  
- Expanded sections  
- New applications  
- Modern contexts  
  
### 4. Structural Improvements  
Recommend:  
- Reorganization needs  
- Flow improvements  
- Connection strengthening  
- Prerequisite clarification  
  
## OUTPUT FORMAT  
Provide structured feedback including:  
  
1. Overall Assessment  
   - Major strengths  
   - Critical weaknesses  
   - Key opportunities  
   - Primary concerns  
  
2. Specific Recommendations  
   - Content additions  
   - Structural changes  
   - Enhancement priorities  
   - Implementation suggestions  
  
3. Prioritized Improvements  
   - Critical (Must implement)  
   - Important (Should implement)  
   - Optional (Nice to have)  
  
Generate a detailed critique that identifies both immediate improvement needs and strategic enhancement opportunities.  
"""  

section_enhancement_prompt = """  
# Section/Chapter Enhancement System  
  
## CONTEXT  
Topic: {query}  
Full ToC Context:  
{context}  
Current Section:  
{section}  
  
## OBJECTIVE  
Enhance the provided section/chapter to create a more comprehensive, detailed, and well-structured sub-Table of Contents while maintaining alignment with the overall document structure.  
  
## ENHANCEMENT FRAMEWORK  
  
### 1. SECTION STRUCTURE  
Expand the section to include:  
- Detailed Overview  
- Learning Objectives  
- Core Concepts  
- Theoretical Foundations  
- Practical Applications  
- Case Studies  
- Exercises and Problems  
- Assessment Methods  
- Further Reading  
  
### 2. CONTENT DEPTH  
For each subsection, include:  
- Key concepts  
- Theoretical background  
- Mathematical foundations  
- Implementation details  
- Best practices  
- Common pitfalls  
- Expert insights  
  
### 3. PRACTICAL ELEMENTS  
Incorporate:  
- Real-world examples  
- Industry applications  
- Code samples (if applicable)  
- Tool usage  
- Implementation strategies  
- Performance considerations  
  
### 4. LEARNING SUPPORT  
Add:  
- Practice exercises  
- Discussion topics  
- Review questions  
- Project ideas  
- Self-assessment tools  
- Additional resources  
  
## OUTPUT FORMAT  
Generate enhanced section content in this structure:  
  
<chapter>  
# [Chapter Title]  
  
## Overview  
- Chapter scope  
- Learning goals  
- Prerequisites  
- Key outcomes  (Learning Objectives for each section and what the reader should be able to do after reading the section and chapter.)
  
## Core Concepts  
- Theoretical foundations  
- Key principles  
- Mathematical framework  
- Fundamental algorithms  
  
## Implementation Details  
- Practical guidelines  
- Best practices  
- Common approaches  
- Performance considerations  
  
## Applications  
- Industry use cases  
- Real-world examples  
- Case studies  
- Implementation projects  
  
## Advanced Topics  
- Research directions  
- Current developments  
- Future trends  
- Advanced applications  
  
## Learning Exercises  
- Practice problems  
- Programming exercises  
- Discussion questions  
- Projects  
  
## Summary and Next Steps  
- Key takeaways  
- Learning Objectives for each section and what the reader should be able to do after reading the section and chapter.
- Review questions  
- Further reading  
- Connection to next topics  
</chapter>  
  
## SPECIAL INSTRUCTIONS  
- Maintain consistency with overall ToC  
- Ensure proper depth and breadth  
- Include cross-references  
- Balance theory and practice  
- Consider both academic and industry perspectives  
- Align with modern industry standards  
- Include emerging trends and technologies  
- The content hierarchy should be as follows: Part I: Introduction, Part II: Intermediate Concepts, Part III: Advanced Topics and any other parts that are relevant. Then each part should have chapters, and each chapter should have sections. So part > chapter > section.
- Every individual atomic chapter should have a title, and start as "## Chapter X: Title" followed by the content. 
- Cover a wide variety of applications, usage, cross disciplinary applications and concepts.
- Cover a wide range of complexity levels, from basic to advanced.
- Give newline characters between each section and chapter.
- Go further in breadth and depth both in the content.
- Talk about insights, aha moments and caveats.
- Add any missed terminology, concepts, applications, cross disciplinary applications and concepts.
- Write your output or answer about the full section level content for the given chapter above in a code block in markdown format.
  
Generate a detailed, enhanced section that provides comprehensive coverage while maintaining clear structure and progression.  
"""  


class ToCGenerationAgent:  
    """Main agent for ToC generation and management."""  
    def __init__(  
        self,   
        llm_name: Union[str, List[str]],  
        keys: dict,
        run_phase_1: bool = True,  
        run_phase_2: bool = True,  
        run_phase_3: bool = False,  
        max_retries: int = 3,  
        max_workers: int = 8,  
        calls_per_minute: int = 50,
        storage_path: str = ".",
        render_prefix: str = ""
    ):  
        """  
        Initialize the ToC Generation Agent.  
          
        Args:  
            llm_name: Name of the LLM to use.
            run_phase_1: Whether to run phase 1 (initial ToC, terminology, advanced concepts)  
            run_phase_2: Whether to run phase 2 (ToC critique and enhancement)  
            run_phase_3: Whether to run phase 3 (section-level enhancement)  
            max_retries: Maximum number of retries for API calls  
            max_workers: Maximum number of parallel workers  
            calls_per_minute: Rate limit for API calls  
        """  
        self.llm_caller = CallLLm(keys, llm_name)  if isinstance(llm_name, str) else CallLLm(keys, llm_name[0])
        self.run_phase_1 = run_phase_1  
        self.run_phase_2 = run_phase_2  
        self.run_phase_3 = run_phase_3  
        self.max_retries = max_retries  
        self.executor = ThreadPoolExecutor(max_workers=max_workers)  
        self.rate_limiter = RateLimiter(calls_per_minute=calls_per_minute)  
          
        # Prompt placeholders - these would be replaced with actual prompts  
        self.toc_creation_prompt = toc_creation_prompt
        self.toc_checker_prompt = toc_checker_prompt
        self.section_enhancement_prompt = section_enhancement_prompt
        
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)
        self.storage_path = storage_path
        self.render_prefix = render_prefix
        logger.info(f"ToCGenerationAgent initialized with phases: {run_phase_1=}, {run_phase_2=}, {run_phase_3=}")  
  
    @property
    def model_name(self):
        return self.llm_caller.model_name
    
    @model_name.setter
    def model_name(self, value):
        self.llm_caller.model_name = value
    
    async def retry_with_backoff(self, func, *args, **kwargs):  
        """Execute function with exponential backoff retry."""  
        for attempt in range(self.max_retries):  
            try:  
                await self.rate_limiter.acquire()  
                return await func(*args, **kwargs)  
            except Exception as e:  
                if attempt == self.max_retries - 1:  
                    logger.error(f"All {self.max_retries} attempts failed: {e}")  
                    raise  
                wait_time = (2 ** attempt) + random.uniform(0, 1)  
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time:.2f}s")  
                await asyncio.sleep(wait_time)  
  
    async def call_llm(self, prompt: str, **kwargs) -> str:  
        """Call LLM with retry logic."""  
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: self.llm_caller(prompt, **kwargs)  
            )  
        return await self.retry_with_backoff(_call)  
    
    def extract_code_block(self, text: str) -> str:
        """Extract the code block from the text, removing the backticks and language identifier.
        
        Args:
            text (str): Text containing code block(s)
            
        Returns:
            str: Extracted code without backticks and language identifier, or original text if no code block found
        """
        # Match any code block with or without language identifier
        pattern = r'```(?:\w+)?\n?(.*?)\n?```'
        match = re.search(pattern, text, re.DOTALL)
        
        if match:
            # Return just the code content (group 1) without the backticks and language
            return match.group(1).strip()
        return text
  
    async def generate_initial_toc(self, topic: str) -> str:  
        """Generate initial ToC."""  
        logger.debug(f"Generating initial ToC for topic: {topic}")  
        prompt = self.toc_creation_prompt.replace("{query}", topic).replace("{task}", "Base ToC creation:Create a ToC for the given topic")  
        response = await self.call_llm(prompt)  
        response = self.extract_code_block(response)
        logger.debug("Initial ToC generation completed")  
        return response  
  
    async def analyze_terminology(self, topic: str, toc: str) -> str:  
        """Analyze and classify terminology."""  
        logger.debug("Analyzing terminology")  
        prompt = self.toc_creation_prompt.replace("{query}", topic).replace("{toc}", toc).replace("{task}", "Terminology identification and classification: Generate a comprehensive, classified list of terminology for this user topic and ToC, categorizing terms by importance and complexity level. The generated list of terms should be a bullet list and cover all the terminology for the given topic in breadth and depth, including applications, usage, cross disciplinary applications and concepts. Some important terminology is already in the main ToC, so don't repeat them, write new and more important terms. Only write the list of terms as bullet list, no other text.")  
        response = await self.call_llm(prompt)  
        response = self.extract_code_block(response)
        logger.debug("Terminology analysis completed")  
        return response  
  
    async def identify_advanced_concepts(self, topic: str, toc: str) -> str:  
        """Identify advanced applications and concepts."""  
        logger.debug("Identifying advanced concepts")  
        prompt = self.toc_creation_prompt.replace("{query}", topic).replace("{toc}", toc).replace("{task}", "Advanced Concepts: Identify and generate a comprehensive list of advanced applications and concepts and write a comprehensive list of them in the form of an advanced applications, usage, cross disciplinary applications and concepts section. Only focus on the most advanced concepts and applications, cross disciplinary applications, less known trivia, hard to understand concepts, and other difficult material around the topic. Some advanced concepts are already in the main ToC, so don't repeat them, write new and more advanced concepts. Only write the advanced part as a ToC section, no other text.")  
        response = await self.call_llm(prompt)  
        response = self.extract_code_block(response)
        logger.debug("Advanced concepts identification completed")  
        return response  
  
    async def critique_toc(self, topic: str, toc: str) -> str:  
        """Critique the ToC."""  
        logger.debug("Critiquing ToC")  
        prompt = self.toc_checker_prompt.replace("{query}", topic).replace("{toc}", toc)  
        response = await self.call_llm(prompt)  
        logger.debug("ToC critique completed")  
        return response  
  
    async def enhance_toc(self, topic: str, toc: str, terminology: str, advanced_concepts: str, critique: str) -> str:  
        """Enhance the ToC based on critique, terminology, and advanced concepts."""  
        logger.debug("Enhancing ToC")  
        prompt = self.toc_creation_prompt.replace("{query}", topic).replace("{toc}", toc).replace("{task}", "ToC Update: Enhance the ToC based on critique, terminology, and advanced concepts.").replace("{terminology}", terminology).replace("{advanced_concepts}", advanced_concepts).replace("{critique}", critique)  
        response = await self.call_llm(prompt)  
        response = self.extract_code_block(response)
        logger.debug("ToC enhancement completed")  
        return response  
  
    def extract_chapters(self, toc: str) -> Dict[str, str]:  
        """Extract chapters from ToC using XML tags."""  
        logger.debug("Extracting chapters from ToC")  
        chapters = []
        pattern = r'<chapter>(.*?)</chapter>'  
        matches = re.finditer(pattern, toc, re.DOTALL)  
          
        for match in matches:  
            chapter_content = match.group(1).strip()  
            # Extract chapter title from the first line (assuming it's a markdown heading)  
            chapters.append(chapter_content)
          
        logger.debug(f"Extracted {len(chapters)} chapters")  
        return chapters  
  
    async def enhance_section(self, topic: str, full_toc: str, section_content: str) -> str:  
        """Enhance a specific section/chapter."""  
        logger.debug(f"Enhancing section: {section_content}")  
        prompt = self.section_enhancement_prompt.replace("{query}", topic)  
        prompt = prompt.replace("{context}", full_toc)  
        prompt = prompt.replace("{section}", section_content)  
          
        response = await self.call_llm(prompt)  
        response = self.extract_code_block(response)
        logger.debug(f"Section enhancement completed for: {section_content}")  
        return response  
  
    async def enhance_sections_parallel(self, topic: str, full_toc: str, chapters: List[str]) -> List[str]:  
        """Enhance multiple sections in parallel."""  
        logger.debug(f"Starting parallel enhancement of {len(chapters)} sections")  
        tasks = []  
        for content in chapters:  
            task = self.enhance_section(topic, full_toc, content)  
            tasks.append(task)  
          
        enhanced_sections = await asyncio.gather(*tasks)  
          
        result = []
        for content, enhanced_content in zip(chapters, enhanced_sections):  
            result.append(enhanced_content)  
          
        logger.debug("Parallel section enhancement completed")  
        return result  
  
    def merge_enhanced_sections(self, base_toc: str, enhanced_sections: List[str]) -> str:
        """Merge enhanced sections back into the main ToC.
        
        Args:
            base_toc (str): The original ToC content with chapter markers
            enhanced_sections (List[str]): List of enhanced chapter contents in same order as base_toc
        
        Returns:
            str: Merged ToC with enhanced sections
        """
        logger.debug("Merging enhanced sections into main ToC")
        result = base_toc
        
        pattern = r'<chapter>.*?</chapter>'  # Simple pattern to match chapter blocks
        
        # Create iterator of replacements
        replacements = (f"{content}" for content in enhanced_sections)
        
        # Replace each matched chapter with its corresponding enhanced content
        result = re.sub(pattern, lambda _: next(replacements), result, flags=re.DOTALL)
        
        logger.debug("Section merging completed")
        return result 
  
    async def generate_toc(self, topic: str) -> ToCGenerationResult:  
        """Main workflow for ToC generation."""  
        start_time = time.time()  
        result = ToCGenerationResult() 
        # print(f"Generating ToC for topic: {topic}")
          
        try:  
            # Phase 1: Generate initial ToC, terminology, and advanced concepts in parallel  
            if self.run_phase_1:  
                logger.info("Starting Phase 1: Initial generation")  
                initial_toc = await self.generate_initial_toc(topic)
                # print(f"Initial ToC generated with len as {len(initial_toc)}")
                initial_toc = initial_toc.replace("```markdown", "").replace("```xml", "").replace("```", "")
                initial_toc = initial_toc.replace("<chapter>", "<chapter>\n").replace("</chapter>", "\n</chapter>")
                result.initial_toc = initial_toc  
                  
                logger.info("Phase 1 completed")  
                  
                # If only Phase 1 is requested, combine results and return  
                if not self.run_phase_2 and not self.run_phase_3:  
                    result.final_toc = self.format_phase1_output(initial_toc, "", "")  
                    result.processing_time = time.time() - start_time  
                    return result  
              
            # Phase 2: Critique and enhance the ToC  
            if self.run_phase_2 and result.initial_toc:  
                logger.info("Starting Phase 2: ToC critique and enhancement")  
                  
                # Critique can start as soon as initial ToC is ready  
                phase2_tasks = [  
                    self.critique_toc(topic, result.initial_toc),  
                    self.analyze_terminology(topic, result.initial_toc),  
                    self.identify_advanced_concepts(topic, result.initial_toc)  
                ]  
                critique, terminology, advanced_concepts = await asyncio.gather(*phase2_tasks)  
                
                result.toc_critique = critique  
                result.terminology = terminology  
                result.advanced_concepts = advanced_concepts  
                  
                # Enhanced ToC requires all Phase 1 results and the critique  
                enhanced_toc = await self.enhance_toc(  
                    topic,   
                    result.initial_toc,   
                    result.terminology,   
                    result.advanced_concepts,   
                    critique  
                )  
                enhanced_toc = enhanced_toc.replace("```markdown", "").replace("```xml", "").replace("```", "")
                enhanced_toc = enhanced_toc.replace("<chapter>", "<chapter>\n").replace("</chapter>", "\n</chapter>")
                result.enhanced_toc = enhanced_toc  
                
                  
                logger.info("Phase 2 completed")  
                  
                # If only Phase 1 and 2 are requested, return enhanced ToC  
                if not self.run_phase_3:  
                    result.final_toc = self.format_phase2_output(enhanced_toc, terminology)    
                    result.processing_time = time.time() - start_time  
                    return result  
              
            # Phase 3: Enhance individual sections  
            if self.run_phase_3 and result.enhanced_toc:  
                logger.info("Starting Phase 3: Section-level enhancement")  
                  
                # Extract chapters from enhanced ToC  
                chapters = self.extract_chapters(result.enhanced_toc)  
                  
                # Enhance each chapter in parallel  
                enhanced_sections = await self.enhance_sections_parallel(  
                    topic,   
                    result.enhanced_toc,   
                    chapters  
                )  
                result.section_enhancements = enhanced_sections  
                  
                # Merge enhanced sections back into main ToC  
                final_toc = self.merge_enhanced_sections(result.enhanced_toc, enhanced_sections) 
                final_toc = final_toc.replace("```markdown", "").replace("```xml", "").replace("```", "")
                final_toc = final_toc.replace("<chapter>", "<chapter>\n").replace("</chapter>", "\n</chapter>")
                result.final_toc = final_toc  
                  
                logger.info("Phase 3 completed")  
              
            result.processing_time = time.time() - start_time  
            return result  
              
        except Exception as e:  
            logger.error(f"ToC generation process failed: {e}", exc_info=True)  
            result.processing_time = time.time() - start_time  
            return result  
  
    def format_phase1_output(self, initial_toc: str, terminology: str, advanced_concepts: str) -> str:  
        """Format Phase 1 output as a markdown string."""  
        return f"""{initial_toc}"""  

    def format_phase2_output(self, enhanced_toc: str, terminology: str) -> str:
        """Format Phase 2 output as a markdown string."""
        return f"""{enhanced_toc}

# Terminology

{terminology}
"""



  
    def __call__(self, topic: str, **kwargs) -> Dict[str, Any]:  
        """Synchronous interface for ToC generation."""  
        try:  
            # Get or create an event loop  
            try:  
                loop = asyncio.get_event_loop()  
            except RuntimeError:  
                loop = asyncio.new_event_loop()  
                asyncio.set_event_loop(loop)  
                
            # if the topic str is too long then we need an LLM call to shorten it
            if len(topic) > 140:
                prompt = f"Write in short. Shorten in one or two sentences, and extract the topic on which we will make a book from the following discussion or conversation: {topic}. Ensure that the topic you extract captures the full nuance and detail of the book we want from the discussion and last message. Return only the topic in one line as a single sentence, no other text."
                try:
                    topic = loop.run_until_complete(self.call_llm(prompt))
                except RuntimeError as e:
                    
                    topic = self.llm_caller(prompt)  # Direct synchronous call
              
            # Run the async generation process  
            try:
                # print("Running the async ToC generation process")
                result = loop.run_until_complete(self.generate_toc(topic))
            except RuntimeError as e:
                if "This event loop is already running" in str(e):
                    # print("Event loop already running, using a separate thread")
                    result = run_async_in_thread(self.generate_toc, topic)
                    # print(f"ToC generation process completed with toc len as {len(result.final_toc)}")
                else:
                    # Re-raise if it's a different RuntimeError
                    raise
            initial_topic = topic
            topic = topic.replace(" ", "_").replace(":", "_").replace("/", "_").replace("\\", "_").replace("*", "_").replace("?", "_").replace("'", "_").replace("\"", "_").replace("<", "_").replace(">", "_").replace("|", "_").replace("#", "")
            
            if self.storage_path.endswith('/'):
                link = f"{self.storage_path}{topic.replace(' ', '_')}_toc.pdf"
            else:
                link = f"{self.storage_path}/{topic.replace(' ', '_')}_toc.pdf"
            convert_markdown_to_pdf(result.final_toc, link)
            dl_link = self.render_prefix + "/" + f"{topic.replace(' ', '_')}_toc.pdf"
              
            # Format the result as a dictionary  
            return {  
                "initial_toc": result.initial_toc,  
                "topic": initial_topic,
                "terminology": result.terminology,  
                "advanced_concepts": result.advanced_concepts,  
                "toc_critique": result.toc_critique,  
                "enhanced_toc": result.enhanced_toc,  
                "section_enhancements": result.section_enhancements,  
                "final_toc": result.final_toc or result.enhanced_toc or result.initial_toc,  
                "processing_time": result.processing_time,
                "answer": f"<a href='{dl_link}' target='_blank'>{topic}</a>" + "\n\n" + result.final_toc
            }  
        except Exception as e:  
            logger.error(f"ToC generation failed: {e}", exc_info=True)  
            raise e
            
            
@dataclass  
class BookResult:  
    """Container for book generation results."""  
    toc: str = ""  
    chapters: List[str] = field(default_factory=list)  
    chapters_tts: List[str] = field(default_factory=list)  
    chapters_tts_audio: List[str] = field(default_factory=list)
    chapters_podcast: List[str] = field(default_factory=list)
    chapters_podcast_audio: List[str] = field(default_factory=list)
    processing_time: float = 0
    
    # New fields to store file paths
    chapter_pdf_paths: List[str] = field(default_factory=list)
    storage_path: str = "",
    render_prefix: str = "",
    full_book_pdf_path: str = ""
    full_audio_path: str = ""
    full_podcast_path: str = ""

    @property
    def full_text(self) -> str:
        """Concatenate chapters to form the full text."""
        return "\n\n".join(self.chapters)

    @property
    def full_text_tts(self) -> str:
        """Concatenate chapters_tts to form the full text for TTS."""
        return "\n\n".join(self.chapters_tts)
    
    def _format_path(self, path: str) -> str:
        """Convert storage path to render path for web display.
        
        Args:
            path: The original file path
            
        Returns:
            Formatted path with render_prefix for web display
        """
        if not path:
            return ""
            
        # Remove storage_path prefix if present
        if self.storage_path and path.startswith(self.storage_path):
            # Remove storage_path and any leading slashes
            rel_path = path[len(self.storage_path):].lstrip('/')
        else:
            rel_path = os.path.basename(path)
            
        # Add render_prefix
        if self.render_prefix:
            if self.render_prefix.endswith('/'):
                return f"{self.render_prefix}{rel_path}"
            else:
                return f"{self.render_prefix}/{rel_path}"
        else:
            return rel_path
    
    def __str__(self) -> str:
        """Format the result as a markdown string with links to all assets."""
        result = "# Book Generation Results\n\n"
        
        # Add full book PDF link
        if self.full_book_pdf_path:
            result += f"## Complete Book\n\n"
            result += f"- [Full Book PDF]({self._format_path(self.full_book_pdf_path)})\n"
        
        # Add full audio link
        if self.full_audio_path:
            result += f"- [Full Audio]({self._format_path(self.full_audio_path)})\n"
        
        # Add full podcast link
        if self.full_podcast_path:
            result += f"- [Full Podcast]({self._format_path(self.full_podcast_path)})\n\n"
        
        # Add chapter links
        if self.chapter_pdf_paths:
            result += f"## Chapters\n\n"
            for i, path in enumerate(self.chapter_pdf_paths):
                chapter_title = f"Chapter {i+1}"
                result += f"### {chapter_title}\n\n"
                result += f"- [PDF]({self._format_path(path)})\n"
                
                # Add chapter audio link if available
                if i < len(self.chapters_tts_audio) and self.chapters_tts_audio[i]:
                    result += f"- [Audio]({self._format_path(self.chapters_tts_audio[i])})\n"
                
                # Add chapter podcast link if available
                if i < len(self.chapters_podcast_audio) and self.chapters_podcast_audio[i]:
                    result += f"- [Podcast]({self._format_path(self.chapters_podcast_audio[i])})\n"
                
                result += "\n"
        
        # Add processing time
        result += f"## Processing Information\n\n"
        result += f"- Processing time: {self.processing_time:.2f} seconds\n"
        result += f"- Number of chapters: {len(self.chapters)}\n"
        
        return result 
    
import asyncio  
import logging  
import re  
import time  
from concurrent.futures import ThreadPoolExecutor  
from typing import List, Optional, Dict, Any  
from dataclasses import dataclass, field  
import os  
from datetime import datetime  
  
  
  
class BookCreatorAgent:  
    """Agent for creating book content from ToC."""  
      
    def __init__(  
        self,  
        llm_name: str,  
        keys: dict,  
        max_retries: int = 3,  
        max_workers: int = 8,  
        calls_per_minute: int = 50,  
        depth: int = 1, # 1, 2, 3, 4
        toc_agent: Optional[ToCGenerationAgent] = None, 
        storage_path: str = ".",
        create_audio: bool = False,
        create_podcast: bool = False,
        create_diagrams: bool = False,
        render_prefix: str = ""
    ):  
        """  
        Initialize the BookCreatorAgent.  
          
        Args:  
            llm_name: Name of the LLM to use  
            keys: API keys dictionary  
            max_retries: Maximum number of retries for API calls  
            max_workers: Maximum number of parallel workers  
            calls_per_minute: Rate limit for API calls  
            depth: Depth of content generation (1-4)
            toc_agent: Optional ToCGenerationAgent instance
            storage_path: Path to store generated files
            create_audio: Whether to create audio versions
            create_podcast: Whether to create podcast versions
            create_diagrams: Whether to create diagrams for chapters
        """  
        self.llm_caller = CallLLm(keys, llm_name)  
        self.max_retries = max_retries  
        self.executor = ThreadPoolExecutor(max_workers=max_workers)  
        self.rate_limiter = RateLimiter(calls_per_minute=calls_per_minute)  
        self.depth = depth 
        self.create_audio = create_audio
        self.create_podcast = create_podcast
        self.create_diagrams = create_diagrams
        self.render_prefix = render_prefix
        self.toc_agent = toc_agent or ToCGenerationAgent(  
            llm_name=llm_name,  
            keys=keys,  
            run_phase_1=True,  
            run_phase_2=depth > 2,  
            run_phase_3=depth > 3  
        )  
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)
        self.storage_path = storage_path
        self.keys = keys
        
          
        # Chapter content generation prompts  
        self.chapter_content_prompt = """  
# Chapter Content Generation  

## Context  
Topic: {topic}  
Chapter Outline:  
{chapter_outline}  

Full ToC Context:  
{toc_context}  

## Task  
Generate comprehensive content for this chapter following the outline provided.  

## Requirements  
1. Follow the chapter outline strictly  
2. Include detailed explanations for each concept  
3. Provide mathematical formulations where relevant  
4. Include code examples if applicable  
5. Maintain academic rigor while ensuring readability  
6. Use proper markdown formatting  
7. Include equations in LaTeX format  
8. Add tables where comparisons are needed  
9. Include diagram suggestions using <figure> tags at appropriate places

## Diagram Instructions
When a diagram would enhance understanding, include a <figure> tag with the following format:
<figure>
type: [python or mermaid]
title: Brief title for the diagram
description: Detailed description of what the diagram should show
content: [For python: describe the plot in detail | For mermaid: describe the diagram structure]
</figure>

Examples:
1. For a Python matplotlib/seaborn diagram:
<figure>
type: python
title: Normal Distribution Comparison
description: Comparison of normal distributions with different parameters
content: Create a plot showing three normal distributions: standard normal, μ=2 σ=1, and μ=0 σ=2
</figure>

2. For a MermaidJS diagram:
<figure>
type: mermaid
title: Option Pricing Process
description: Flowchart showing the Black-Scholes option pricing model process
content: Create a flowchart showing inputs (stock price, strike price, volatility, time to expiration, risk-free rate) flowing into the Black-Scholes model and outputting call and put option prices
</figure>

## Output Format  
- Use markdown headings (# for chapter title, ## for sections)  
- Include equations in LaTeX format using $$ delimiters  
- Use tables for comparisons  
- Include code blocks where needed  
- Maintain consistent formatting  
- Place <figure> tags at appropriate locations where diagrams would enhance understanding
  
Generate the chapter content now.  
"""
        self.practical_content_prompt = """  
# Practical Content Generation  
    
## Context  
Topic: {topic}  

Chapter Outline:  
{chapter_outline}
  
Chapter Content:  
{chapter_content}  
    
## Task  
Generate practical supplementary content for this chapter.  
    
## Required Sections  
1. Key Terms and Definitions  
2. Insightful Examples and Anecdotes  
3. Surprising Facts and Aha Moments  
4. Real-world Applications  
5. Case Studies  
    
## Output Format  
Use markdown with clear section headings:  
# Practical Applications and Insights  
## Key Terms and Definitions  
## Insightful Examples  
## Surprising Facts  
## Real-world Applications  
## Case Studies  
    
Generate the practical content now.  
"""  
        self.glossary_and_faq_prompt = """  
# Glossary and FAQ content generation task. 
    
## Context  
Topic: {topic} 

Chapter Outline:  
{chapter_outline}  

Chapter Content:  
{chapter_content}   

## Task  
Generate a glossary and FAQ for this chapter in markdown format.  

## Output Format  
- Use markdown headings (# for chapter title, ## for sections, ### for sub sections, ### for glossary and FAQ)  
- Use tables for comparisons  
- Include code blocks where needed  
- Maintain consistent formatting  

Write the glossary and FAQ now.  
"""  
          
    async def retry_with_backoff(self, func, *args, **kwargs):  
        """Execute function with exponential backoff retry."""  
        for attempt in range(self.max_retries):  
            try:  
                await self.rate_limiter.acquire()  
                return await func(*args, **kwargs)  
            except Exception as e:  
                if attempt == self.max_retries - 1:  
                    logger.error(f"All {self.max_retries} attempts failed: {e}")  
                    raise  
                wait_time = (2 ** attempt) + random.uniform(0, 1)  
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time:.2f}s")  
                await asyncio.sleep(wait_time)  
  
    async def call_llm(self, prompt: str, **kwargs) -> str:  
        """Call LLM with retry logic."""  
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: self.llm_caller(prompt, **kwargs)  
            )  
        return await self.retry_with_backoff(_call)  
  
    def extract_chapters_from_toc(self, toc: str) -> List[Dict[str, str]]:  
        """  
        Extract chapter information from ToC using XML chapter tags.  
        
        Args:  
            toc (str): Table of contents with chapters marked by XML tags  
            
        Returns:  
            List[Dict[str, str]]: List of dictionaries containing chapter title and content  
            
        Example:  
            Input ToC format:  
            <chapter>  
            # Chapter 1: Introduction  
            ## Section 1.1  
            ## Section 1.2  
            </chapter>  
            <chapter>  
            # Chapter 2: Advanced Topics  
            ## Section 2.1  
            ## Section 2.2  
            </chapter>  
        """  
        chapters = []  
        try:  
            # Find all chapter blocks using regex  
            chapter_pattern = r'<chapter>(.*?)</chapter>'  
            chapter_matches = re.finditer(chapter_pattern, toc, re.DOTALL)  
            
            for match in chapter_matches:  
                chapter_content = match.group(1).strip()  
                
                # Extract title from the first line (assuming it starts with # Chapter)  
                lines = chapter_content.split('\n')  
                title = next((line.strip() for line in lines if line.strip().startswith('# Chapter') or line.strip().startswith('Chapter ') or line.strip().startswith('## Chapter')), 'Untitled Chapter')  
                
                chapters.append({  
                    'title': title,  
                    'content': chapter_content  
                })  
                
            if not chapters:  
                logger.warning("No chapters found in ToC using XML tags")  
                
            return chapters  
            
        except Exception as e:  
            logger.error(f"Error extracting chapters from ToC: {e}")  
            # Return empty list in case of error  
            return []  

  
    async def process_figures(self, chapter_text: str, chapter_title: str) -> str:
        """
        Process <figure> tags in chapter text and replace with generated diagrams.
        
        Args:
            chapter_text: The chapter text containing <figure> tags
            chapter_title: The title of the chapter (for naming diagrams)
            
        Returns:
            Updated chapter text with <figure> tags replaced by markdown image references
        """
        if not self.create_diagrams:
            # If diagrams are disabled, remove the figure tags but keep the descriptions
            return re.sub(
                r'<figure>.*?type:\s*(\w+).*?title:\s*(.*?).*?description:\s*(.*?).*?content:\s*(.*?).*?</figure>',
                r'**Figure: \2**\n\n\3',
                chapter_text,
                flags=re.DOTALL
            )
        
        # Create diagrams directory if it doesn't exist
        diagrams_dir = os.path.join(self.storage_path, "diagrams")
        os.makedirs(diagrams_dir, exist_ok=True)
        
        # Find all figure tags
        figure_pattern = r'<figure>(.*?)</figure>'
        figures = re.findall(figure_pattern, chapter_text, re.DOTALL)
        
        # Process each figure
        for i, figure_content in enumerate(figures):
            try:
                # Extract figure details
                figure_type = re.search(r'type:\s*(\w+)', figure_content, re.DOTALL)
                figure_title = re.search(r'title:\s*(.*?)(?:\n|$)', figure_content, re.DOTALL)
                figure_desc = re.search(r'description:\s*(.*?)(?:\n|$|content:)', figure_content, re.DOTALL)
                figure_content_match = re.search(r'content:\s*(.*?)(?:\n|$)', figure_content, re.DOTALL)
                
                if not all([figure_type, figure_title, figure_desc, figure_content_match]):
                    logger.warning(f"Incomplete figure specification in chapter {chapter_title}")
                    continue
                    
                figure_type = figure_type.group(1).strip().lower()
                figure_title = figure_title.group(1).strip()
                figure_desc = figure_desc.group(1).strip()
                figure_content_text = figure_content_match.group(1).strip()
                
                # Generate a unique filename for the diagram
                safe_title = re.sub(r'[^\w\-_]', '_', chapter_title.lower())
                filename = f"{safe_title}_diagram_{i+1}"
                
                # Generate diagram code using LLM
                if figure_type == "python":
                    diagram_code = await self.generate_python_diagram_code(
                        figure_title, 
                        figure_desc, 
                        figure_content_text,
                        chapter_text,
                    )
                    diagram_path = await self.create_python_diagram(
                        diagram_code, 
                        os.path.join(diagrams_dir, f"{filename}.png")
                    )
                elif figure_type == "mermaid":
                    diagram_code = await self.generate_mermaid_diagram_code(
                        figure_title, 
                        figure_desc, 
                        figure_content_text,
                        chapter_text,
                    )
                    diagram_path = await self.create_mermaidjs_diagram(
                        diagram_code, 
                        os.path.join(diagrams_dir, f"{filename}.png")
                    )
                else:
                    logger.warning(f"Unknown diagram type: {figure_type}")
                    continue
                
                # Create markdown image reference
                relative_path = os.path.relpath(diagram_path, self.storage_path)
                image_markdown = f"\n\n![{figure_title}]({relative_path})\n*{figure_desc}*\n\n"
                
                # Replace the figure tag with the image markdown
                chapter_text = chapter_text.replace(f"<figure>{figure_content}</figure>", image_markdown)
                
            except Exception as e:
                logger.error(f"Error processing figure in chapter {chapter_title}: {e}")
                # Remove the figure tag if processing failed
                chapter_text = chapter_text.replace(f"<figure>{figure_content}</figure>", 
                                                f"\n\n**Figure: {figure_title if 'figure_title' in locals() else 'Diagram'}**\n\n{figure_desc if 'figure_desc' in locals() else ''}\n\n")
        
        return chapter_text
    
    async def generate_python_diagram_code(self, title: str, description: str, content: str, chapter_text: str) -> str:
        """Generate Python code for creating a matplotlib/seaborn diagram."""
        prompt = f"""
Create Python code using matplotlib or seaborn to generate the following diagram:

Chapter Text: {chapter_text}
Title: {title}
Description: {description}
Content: {content}

Requirements:
1. Use matplotlib or seaborn to create a high-quality visualization
2. Include appropriate labels, title, and legend
3. Use a professional color scheme
4. Set figure size appropriately (e.g., plt.figure(figsize=(10, 6)))
5. Include code to save the figure with plt.savefig('output.png', dpi=300, bbox_inches='tight')
6. Do not include code to display the plot (no plt.show())
7. Add helpful comments to explain the code

Return only the Python code without any additional text or explanations.
"""
        
        return await self.call_llm(prompt)

    async def generate_mermaid_diagram_code(self, title: str, description: str, content: str, chapter_text: str) -> str:
        """Generate MermaidJS code for creating a diagram."""
        prompt = f"""
Create MermaidJS code to generate the following diagram:

Chapter Text: {chapter_text}
Title: {title}
Description: {description}
Content: {content}

Requirements:
1. Use appropriate MermaidJS syntax (flowchart, sequence diagram, class diagram, etc.)
2. Include clear labels and descriptions
3. Use a professional and readable layout
4. Add appropriate styling for clarity

Return only the MermaidJS code without any additional text or explanations.
"""
        
        return await self.call_llm(prompt)
    
    async def create_python_diagram(self, code: str, save_path: str) -> str:
        """
        Execute Python code to create and save a diagram.
        
        Args:
            code: Python code that creates and saves a matplotlib/seaborn diagram
            save_path: Path where the diagram should be saved
            
        Returns:
            Path to the saved diagram
        """
        try:
            # Create a temporary directory for execution
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create a Python file with the code
                script_path = os.path.join(temp_dir, "diagram_script.py")
                
                # Modify the code to save to our specified path
                modified_code = code.replace("plt.savefig('output.png'", f"plt.savefig('{save_path}'")
                modified_code = modified_code.replace("plt.savefig(\"output.png\"", f"plt.savefig(\"{save_path}\"")
                
                # If no savefig is found, add it
                if "savefig" not in modified_code:
                    modified_code += f"\n\nimport matplotlib.pyplot as plt\nplt.savefig('{save_path}', dpi=300, bbox_inches='tight')\n"
                
                with open(script_path, "w") as f:
                    f.write(modified_code)
                
                # Execute the script in a separate process
                async def _call():
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        self.executor,
                        lambda: subprocess.run(
                            [sys.executable, script_path],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                    )
                
                await _call()
                
                # Check if the file was created
                if os.path.exists(save_path):
                    logger.info(f"Diagram created: {save_path}")
                    return save_path
                else:
                    logger.error(f"Diagram file not created at {save_path}")
                    return ""
        
        except Exception as e:
            logger.error(f"Error creating Python diagram: {e}")
            return ""

    async def create_mermaidjs_diagram(self, mermaid_code: str, save_path: str) -> str:
        """
        Create a diagram from MermaidJS code and save it.
        
        Args:
            mermaid_code: MermaidJS code for the diagram
            save_path: Path where the diagram should be saved
            
        Returns:
            Path to the saved diagram
        """
        try:
            # This is a placeholder - in a real implementation, you would use a MermaidJS
            # renderer like puppeteer-mermaid or a mermaid CLI tool
            
            # For now, we'll create a text file with the mermaid code
            # and return a message about the limitation
            mermaid_path = save_path.replace(".png", ".mermaid")
            with open(mermaid_path, "w") as f:
                f.write(mermaid_code)
            
            logger.info(f"MermaidJS code saved to: {mermaid_path}")
            logger.warning("Actual MermaidJS rendering not implemented - would require external tools")
            
            # In a real implementation, you would render the diagram here
            # For example, using a command like:
            # mmdc -i input.mermaid -o output.png
            
            # For now, return the path to the mermaid code file
            return mermaid_path
        
        except Exception as e:
            logger.error(f"Error creating MermaidJS diagram: {e}")
            return ""

    
    async def create_chapter_content(  
        self,  
        topic: str,  
        chapter_info: Dict[str, str],  
        toc_context: str  
    ) -> Dict[str, str]:  
        """Generate content for a single chapter."""  
        try:  
            # Generate main chapter content  
            prompt = self.chapter_content_prompt.format(  
                topic=topic,  
                chapter_outline=chapter_info['content'],  
                toc_context=toc_context  
            )  
            chapter_content = await self.call_llm(prompt)  
            # print(f"Chapter title: {chapter_info['title']},  created content.")
              
            result = {  
                'title': chapter_info['title'],  
                'main_content': chapter_content  
            }  
              
            # Generate practical content if enabled  
            if self.depth > 3:  
                practical_prompt = self.practical_content_prompt.format(  
                    topic=topic,  
                    chapter_outline=chapter_info['content'],  
                    chapter_content=chapter_content  
                )  
                glossary_and_faq_prompt = self.glossary_and_faq_prompt.format(  
                    topic=topic,  
                    chapter_outline=chapter_info['content'],  
                    chapter_content=chapter_content  
                )  
                practical_task = self.call_llm(practical_prompt)
                glossary_and_faq_task = self.call_llm(glossary_and_faq_prompt)

                practical_content, glossary_and_faq_content = await asyncio.gather(
                    practical_task, glossary_and_faq_task
                )

                result['practical_content'] = practical_content
                result['glossary_and_faq_content'] = glossary_and_faq_content
              
            return result  
              
        except Exception as e:  
            logger.error(f"Error generating chapter content: {e}")  
            return {  
                'title': chapter_info['title'],  
                'main_content': f"Error generating content: {str(e)}",  
                'practical_content': ""  
            }  
  
    async def create_book_content(  
    self,  
    topic: str,  
    toc: Optional[str] = None  
) -> BookResult:  
        """Create full book content from ToC."""  
        start_time = time.time()  
        result = BookResult(storage_path=self.storage_path, render_prefix=self.render_prefix) 
        # print(f"Creating book content for topic: {topic}") 
        
        try:  
            # Generate ToC if not provided  
            if not toc:  
                logger.info("Generating new ToC")  
                toc_result = self.toc_agent(topic)  
                toc = toc_result["final_toc"]  
                if len(topic) > 140:
                    topic = toc_result["topic"]
            result.toc = toc  
            
            # Extract chapters from ToC  
            chapters = self.extract_chapters_from_toc(toc)  
            
            # print(f"Creating {len(chapters)} chapters")
            
            # Generate chapter content in parallel  
            tasks = [  
                self.create_chapter_content(topic, chapter, toc)  
                for chapter in chapters  
            ]  
            
            chapter_contents = await asyncio.gather(*tasks)  
            
            # Create chapters directory if it doesn't exist
            chapters_dir = self.storage_path # os.path.join(self.storage_path, "chapters") 
            os.makedirs(chapters_dir, exist_ok=True)
            
            # Process chapter contents  
            for i, content in enumerate(chapter_contents):  
                chapter_text = content['main_content']  
                title = content['title']
                
                # Process figures if diagrams are enabled
                if self.create_diagrams:
                    chapter_text = await self.process_figures(chapter_text, title)
                if self.depth > 3 and 'practical_content' in content:  
                    practical_content = content['practical_content']
                    if self.create_diagrams:
                        practical_content = await self.process_figures(practical_content, f"{title}_practical")
                    chapter_text += "\n\n" + practical_content
                if self.depth > 3 and 'glossary_and_faq_content' in content:  
                    glossary_content = content['glossary_and_faq_content']
                    if self.create_diagrams:
                        glossary_content = await self.process_figures(glossary_content, f"{title}_glossary")
                    chapter_text += "\n\n" + glossary_content
                    
                chapter_text += "\n\n---\n\n\\newpage\n\n"
                
                result.chapters.append(chapter_text)  
                
                # Create chapter PDF
                title = title.replace(' ', '_').replace('\\', '_').replace('/', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace('`', '_').replace('~', '_').replace('!', '_').replace('@', '_').replace('#', '_').replace('$', '_').replace('%', '_').replace('^', '_').replace('&', '_').replace('(', '_').replace(')', '_').replace('-', '_').replace('_', '_')
                chapter_pdf_path = os.path.join(chapters_dir, f"{title}.pdf")
                await self.create_chapter_pdf(chapter_text, title, chapter_pdf_path)
                result.chapter_pdf_paths.append(chapter_pdf_path)
                
                # Create TTS-friendly version (remove markdown, latex, etc.)  
                
                if self.create_audio and self.create_podcast:
                    tts_text, podcast_text = await asyncio.gather(
                        self.prepare_for_tts(chapter_text),
                        self.prepare_for_podcast(chapter_text)
                    )
                    result.chapters_tts.append(tts_text)
                    result.chapters_podcast.append(podcast_text)
                    audio_file, podcast_file = await asyncio.gather(
                        self.convert_to_audio(tts_text, self.storage_path+f"/audio" + f"/{title.replace(' ', '_')}"),
                        self.convert_to_podcast(podcast_text, self.storage_path+f"/podcast" + f"/{title.replace(' ', '_')}")
                    )
                    result.chapters_tts_audio.append(audio_file)
                    result.chapters_podcast_audio.append(podcast_file)
                
                elif self.create_audio:
                    tts_text = await self.prepare_for_tts(chapter_text)  
                    result.chapters_tts.append(tts_text)  
                    audio_file = await self.convert_to_audio(tts_text, self.storage_path+f"/audio" + f"/{title.replace(' ', '_')}")
                    result.chapters_tts_audio.append(audio_file)
                    
                elif self.create_podcast:
                    podcast_text = await self.prepare_for_podcast(chapter_text)
                    result.chapters_podcast.append(podcast_text)
                    podcast_file = await self.convert_to_podcast(podcast_text, self.storage_path+f"/podcast" + f"/{title.replace(' ', '_')}")
                    result.chapters_podcast_audio.append(podcast_file)
            
            # Generate full PDF  
            full_book_pdf_path = await self.create_pdf(result, topic)
            result.full_book_pdf_path = full_book_pdf_path
            
            # Combine audio files if they exist
            if self.create_audio and result.chapters_tts_audio:
                full_audio_path = os.path.join(self.storage_path, "audio", f"{topic.replace(' ', '_')}_full_audio.mp3")
                await self.combine_audio_files(result.chapters_tts_audio, full_audio_path)
                result.full_audio_path = full_audio_path
                
            # Combine podcast files if they exist
            if self.create_podcast and result.chapters_podcast_audio:
                full_podcast_path = os.path.join(self.storage_path, "podcast", f"{topic.replace(' ', '_')}_full_podcast.mp3")
                await self.combine_audio_files(result.chapters_podcast_audio, full_podcast_path)
                result.full_podcast_path = full_podcast_path
            
            result.processing_time = time.time() - start_time  
            
            return result  
            
        except Exception as e:  
            logger.error(f"Error in book creation: {e}")  
            result.processing_time = time.time() - start_time  
            raise e
    
    async def prepare_for_podcast(self, text: str) -> str:
        """Prepare text for podcast by converting to conversational format."""
        podcast_agent = PodcastAgent(self.keys, storage_path=self.storage_path+f"/podcast", shortTTS=self.depth <= 2)
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: podcast_agent.make_tts_friendly(text)
            )  
        return await self.retry_with_backoff(_call)

    async def convert_to_podcast(self, text: str, storage_path: str):
        """Convert text to podcast audio format."""
        podcast_agent = PodcastAgent(self.keys, storage_path=storage_path, shortTTS=self.depth <= 2)
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: podcast_agent(text)
            )  
        return await self.retry_with_backoff(_call)
    
    async def prepare_for_tts(self, text: str) -> str:  
        """Prepare text for TTS by removing markdown and latex."""  
        # # Remove markdown headers  
        # text = re.sub(r'#+ ', '', text)  
        # # Remove latex equations  
        # text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)  
        # # Remove inline latex  
        # text = re.sub(r'\$.*?\$', '', text)  
        # # Remove code blocks  
        # text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  
        # # Remove tables
        # text = re.sub(r'\|\s*-\s*\|', '', text, flags=re.DOTALL)
        # return text.strip()  
        tts_agent = TTSAgent(self.keys, storage_path=self.storage_path+f"/audio", shortTTS=self.depth <= 2)
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: tts_agent.make_tts_friendly(text)
            )  
        return await self.retry_with_backoff(_call) 
    
    async def convert_to_audio(self, text: str, storage_path: str):
        tts_agent = TTSAgent(self.keys, storage_path=storage_path, shortTTS=self.depth <= 2)
        async def _call():  
            loop = asyncio.get_event_loop()  
            return await loop.run_in_executor(  
                self.executor,  
                lambda: tts_agent(text)
            )  
        return await self.retry_with_backoff(_call) 
     
    async def create_chapter_pdf(self, chapter_text: str, title: str, output_path: str):
        """Create PDF for a single chapter."""
        try:
            # Add title to the chapter text
            pdf_content = f"# {title}\n\n{chapter_text}"
            
            async def _call():
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    self.executor,
                    lambda: convert_markdown_to_pdf(pdf_content, output_path)
                )
            await _call()
            logger.info(f"Chapter PDF created: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error creating chapter PDF: {e}")
            return None
    
    async def combine_audio_files(self, audio_files: List[str], output_path: str):
        """Combine multiple audio files into one."""
        try:
            async def _call():
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    self.executor,
                    lambda: self._merge_audio_files(audio_files, output_path)
                )
            await _call()
            logger.info(f"Combined audio created: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error combining audio files: {e}")
            return None

    def _merge_audio_files(self, chunk_files: List[str], output_path: str, pause_duration: int = 500):
        """
        Merge multiple audio files into one.

        Args:
            chunk_files: List of audio file paths to merge
            output_path: Path to save the merged audio file
            pause_duration: Duration of pause between chunks in milliseconds
        """
        try:
            # Load the first file
            combined = AudioSegment.from_mp3(chunk_files[0])

            # Add pause between chunks
            pause = AudioSegment.silent(duration=pause_duration)

            # Append the rest
            for chunk_file in chunk_files[1:]:
                audio_chunk = AudioSegment.from_mp3(chunk_file)
                combined += pause + audio_chunk

            # Export the final file
            combined.export(output_path, format="mp3")
            return output_path
        except Exception as e:
            error_logger.error(f"Error merging audio files: {e}")
            # If merge fails, copy the first file as fallback
            if chunk_files:
                try:
                    shutil.copy2(chunk_files[0], output_path)
                    return output_path
                except Exception as copy_error:
                    error_logger.error(f"Error copying fallback audio file: {copy_error}")
                    return None

    async def create_pdf(self, result: BookResult, topic: str):
        """Create PDF version of the book."""
        try:
            pdf_content = f"# {topic}\n\n"
            pdf_content += result.toc + "\n\n"
            pdf_content += result.full_text
            
            filename = f"{self.storage_path}/{topic.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_book.pdf"
            async def _call():
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    self.executor,
                    lambda: convert_markdown_to_pdf(pdf_content, filename)
                )
            await _call()
            logger.info(f"PDF created: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Error creating PDF: {e}")
            return None
    def __call__(self, topic: str, toc: Optional[str] = None, **kwargs) -> BookResult:  
        """Synchronous interface for book creation."""  
        # if topic has a code block with markdown or plaintext and first of code block is toc then extract the toc and use it as the toc
        if re.search(r'```(markdown|plaintext|md|txt)\s*.*?```', topic, re.DOTALL):
            toc = re.search(r'```(markdown|plaintext|md|txt)\s*.*?```', topic, re.DOTALL).group(0)
            if toc:
                toc = toc.strip()
                # if first line of toc is toc then use it as the toc
                if toc.startswith("toc") and len(toc.split("\n")) > 1:
                    toc = toc.split("\n", 2)[1]
                    topic = re.sub(r'```(markdown|plaintext|md|txt)\s*.*?```', '', topic, re.DOTALL).strip()
        try:  
            loop = asyncio.get_event_loop()  
        except RuntimeError:  
            loop = asyncio.new_event_loop()  
            asyncio.set_event_loop(loop)  
              
        return loop.run_until_complete(self.create_book_content(topic, toc))  
  


    
if __name__ == "__main__":
    keys = {
        "openAIKey": "woop",
            }
    # put keys in os.environ
    import os
    for k, v in keys.items():
        os.environ[k] = v
        
    # Create the agent
    toc_agent = ToCGenerationAgent(    
        llm_name="gpt-4o-mini",    
        keys=keys,    
        run_phase_1=True,    
        run_phase_2=True,    
        run_phase_3=False,    
        max_retries=1,    
        max_workers=8,    
        calls_per_minute=30,
        storage_path="ToC_and_Book_Audio"
    )    
        
    # Generate ToC for a topic    
    topic = "Options in Finance"    
    result = toc_agent(topic)    
    toc = result["final_toc"]  
    print(toc)  
    
    # Create book content  
    book_agent = BookCreatorAgent(  
        llm_name="gpt-4o-mini",  
        keys=keys,  
        max_retries=3,  
        max_workers=8,  
        calls_per_minute=30,  
        depth=2,  
        toc_agent=toc_agent,
        storage_path="ToC_and_Book_Audio"
    )  
      
    # Generate book content using existing ToC  
    book_result = book_agent(topic, toc)  
    
