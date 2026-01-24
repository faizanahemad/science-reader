import random
import traceback
from typing import Union, List
import uuid
from common import OPENAI_CHEAP_LLM, collapsible_wrapper
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
    from prompts import tts_friendly_format_instructions, diagram_instructions
    from base import CallLLm, CallMultipleLLM, simple_web_search_with_llm
    from common import (
        VERY_CHEAP_LLM, CHEAP_LLM, USE_OPENAI_API, convert_markdown_to_pdf, convert_to_pdf_link_if_needed, CHEAP_LONG_CONTEXT_LLM,
        get_async_future, sleep_and_get_future_result, convert_stream_to_iterable, EXPENSIVE_LLM, two_column_list_md
    )
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

import logging
import re
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO)
import time
from .base_agent import Agent


_URL_RE = re.compile(r"https?://[^\s<>'\"\)\]]+")
_URL_TRAILING_PUNCTUATION = ".,;:!?)\\]}>\"'"


def _extract_urls(text: str) -> List[str]:
    """
    Extract unique http(s) URLs from arbitrary text.

    - Preserves first-seen order
    - Strips common trailing punctuation from matches

    Args:
        text: Arbitrary text that may contain URLs.

    Returns:
        A list of unique URLs in stable order.
    """
    if not text:
        return []

    urls: List[str] = []
    seen = set()
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_URL_TRAILING_PUNCTUATION)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _count_words(text: str) -> int:
    """
    Approximate word count for display/telemetry.

    Args:
        text: Text to count.

    Returns:
        Number of whitespace-delimited tokens.
    """
    if not text:
        return 0
    return len(re.findall(r"\S+", text))



class WebSearchWithAgent(Agent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=False, show_intermediate_results=False, headless=False):
        super().__init__(keys)
        self.gscholar = gscholar
        self.model_name = model_name
        self.detail_level = detail_level
        self.concurrent_searches = True
        self.timeout = timeout
        self.no_intermediate_llm = no_intermediate_llm
        self.post_process_answer_needed = False
        self.show_intermediate_results = show_intermediate_results
        self.headless = headless
        self.combiner_prompt = f"""
You are tasked with synthesizing information from multiple web search results to provide a comprehensive and accurate response to the user's query. Your goal is to combine these results into a coherent and informative answer.

Instructions:
1. Carefully analyze and integrate information from all provided web search results.
2. Only use information from the provided web search results.
3. If the web search results are not helpful or relevant, state: "No relevant information found in the web search results." and end your response.
4. If appropriate, include brief citations to indicate the source of specific information (e.g., "According to [Source],...").
5. Organize the information in a logical and easy-to-read format.
6. Put relevant citations inline in markdown format in the text at the appropriate places in your response.

Your response should include:
1. A comprehensive answer to the user's query, synthesizing information from all relevant search results with references in markdown link format closest to where applicable.
2. If applicable, a brief summary of any conflicting information or differing viewpoints found in the search results.
3. If no web search results are provided, please say "No web search results provided." and end your response.

Web search results:
<|results|>
{{web_search_results}}
</|results|>

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please compose your response, ensuring it thoroughly addresses the user's query while synthesizing information from all provided search results.
"""

        num_queries = 3 if self.detail_level <= 2 else 5 if self.detail_level == 3 else 8
        self.llm_prompt = f"""
Given the following user's query and conversation history, generate a list of relevant and targeted search queries and their corresponding brief contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.


User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Format your response as a Python list of tuples as given below: 
```python
[
    ('query1', 'context1 including conversational context on what user is looking for in short and concise manner'), 
    ('query2', 'context2 including conversational context on what user is looking for in short and concise manner'), 
    ('query3 with various variations to broaden the search', 'context3 with various variations to broaden the search including conversational context on what user is looking for in short and concise manner'), 
    ...
]
```

Generate up to {num_queries} highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""
    def extract_queries_contexts(self, code_string):
        regex = r"```(?:\w+)?\s*(.*?)```"
        matches = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        
        if not matches:
            return None  # or you could return an empty list [], depending on your preference
        
        matches = [m.split("=")[-1].strip() for m in matches]
        
        code_to_execute = [c.strip() for c in matches if c.strip()!="" and c.strip()!="[]" and c.strip().startswith("[") and c.strip().endswith("]")][-1:]
        return "\n".join(code_to_execute)
    
    def remove_code_blocks(self, text):
        regex = r"```(?:\w+)?\s*(.*?)```"
        return re.sub(regex, r"\1", text, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    def get_results_from_web_search(self, text, text_queries_contexts):

        array_string = text_queries_contexts
        web_search_results = []
        try:
            # Use ast.literal_eval to safely evaluate the string as a Python expression
            import ast
            text_queries_contexts = ast.literal_eval(array_string)
            
            # Ensure the result is a list of tuples
            if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) for item in text_queries_contexts):
                raise ValueError("Invalid format: expected list of tuples")
            
            # Now we have text_queries_contexts as a list of tuples of the form [('query', 'context'), ...]
            # We need to call simple_web_search_with_llm for each query and context
            # simple_web_search_with_llm(keys, user_context, queries, gscholar)
            
            if self.concurrent_searches:
                # Fix: correctly associate each future with its corresponding query/context by storing tuples
                future_tuples = []
                for query, context in text_queries_contexts:
                    future = get_async_future(
                        simple_web_search_with_llm,
                        self.keys,
                        text + "\n\n" + context,
                        [query],
                        gscholar=self.gscholar,
                        provide_detailed_answers=self.detail_level,
                        no_llm=len(text_queries_contexts) <= 5 or self.no_intermediate_llm,
                        timeout=self.timeout
                    )
                    future_tuples.append((future, query, context))

                web_search_results = []
                for future, query, context in future_tuples:
                    result = sleep_and_get_future_result(future)
                    web_search_results.append(f"<b>{query}</b></br>" + "\n\n" + context + "\n\n" + result)
            else:
                web_search_results = []
                for query, context in text_queries_contexts:
                    result = simple_web_search_with_llm(self.keys, text + "\n\n" + context, [query], gscholar=self.gscholar, provide_detailed_answers=self.detail_level, no_llm=len(text_queries_contexts) <= 5 or self.no_intermediate_llm, timeout=self.timeout)
                    web_search_results.append(f"<b>{query}</b></br>" + "\n\n" + context + "\n\n" + result)
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing text_queries_contexts: {e}, \n\n{traceback.format_exc()}")
            text_queries_contexts = None
        return "\n".join(web_search_results)
    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=True):
        # Extract queries and contexts from the text if present, otherwise set to None
        # We will get "[('query', 'context')...,]" style large array which is string, need to eval or ast.literal_eval this to make it python array, then error handle side cases.
        # Ensure the result is a list of tuples
        # Parallel search all queries and generate markdown formatted response, latex formatted response and bibliography entries inside code blocks.
        text_queries_contexts = self.extract_queries_contexts(text)

        answer = ""
        answer += f"""User's query and conversation history: 
<|context|>
{text}
</|context|>\n\n"""

        
        
        if text_queries_contexts is not None and len(text_queries_contexts) > 0:
            answer += f"Generated Queries and Contexts: {text_queries_contexts}\n\n"
            yield {"text": '\n```\n'+text_queries_contexts+'\n```\n', "status": "Created/Obtained search queries and contexts"}
            text = self.remove_code_blocks(text)
            # Extract the array-like string from the text
            web_search_results = self.get_results_from_web_search(text, text_queries_contexts)
            if self.show_intermediate_results:
                yield {"text": web_search_results + "\n", "status": "Obtained web search results"}
            answer += f"{web_search_results}\n\n"
        else:
            llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])
            # Write a prompt for the LLM to generate queries and contexts
            llm_prompt = self.llm_prompt.format(text=text)

            # Call the LLM to generate queries and contexts
            response = llm(llm_prompt, images=[], temperature=0.7, stream=False, max_tokens=None, system=None)

            # Parse the response to extract queries and contexts
            import ast
            try:
                # Use ast.literal_eval to safely evaluate the string as a Python expression
                try:
                    response = self.extract_queries_contexts(response)
                    text_queries_contexts = ast.literal_eval(response)
                except Exception as e:
                    logger.error(f"Error parsing LLM-generated queries and contexts: {e}, \n\n{traceback.format_exc()}")
                    response = llm(llm_prompt, images=[], temperature=0.7, stream=False, max_tokens=None, system=None)
                    response = self.extract_queries_contexts(response)
                    text_queries_contexts = ast.literal_eval(response)
                text = self.remove_code_blocks(text)
                yield {"text": '\n```\n'+response+'\n```\n', "status": "Created/Obtained search queries and contexts"}
                answer += f"Generated Queries and Contexts: ```\n{response}\n```\n\n"
                
                # Validate the parsed result
                if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in text_queries_contexts):
                    raise ValueError("Invalid format: expected list of tuples")
                
                # If valid, proceed with web search using the generated queries and contexts
                web_search_results = self.get_results_from_web_search(text, str(text_queries_contexts))
                if self.show_intermediate_results:
                    yield {"text": web_search_results + "\n", "status": "Obtained web search results"}
                answer += f"{web_search_results}\n\n"
            except (SyntaxError, ValueError) as e:
                logger.error(f"Error parsing LLM-generated queries and contexts: {e}, \n\n{traceback.format_exc()}")
                web_search_results = []
                
        if len(web_search_results) == 0:
            raise ValueError("No relevant information found in the web search results.")
        
        # if len(web_search_results) == 1 and not self.no_intermediate_llm:
        #     yield {"text": '' + "\n", "status": "Completed literature review for a single query"}
        
        # Now we have web_search_results as a list of strings, each string is a web search result.
        # After response is generated for all queries (within a timeout) then use a combiner LLM to combine all responses into a single response.
        llm = CallLLm(self.keys, model_name=self.model_name)
        
        if not self.headless:
            yield {"text": '\n\n', "status": "Completed web search with agent"}
            combined_response = llm(self.combiner_prompt.format(web_search_results=web_search_results, text=text), images=images, temperature=temperature, stream=True, max_tokens=max_tokens, system=system)
            yield {"text": '<web_answer>', "status": "Completed web search with agent"}
            combined_answer = ""
            for text in combined_response:
                yield {"text": text, "status": "Completed web search with agent"}
                combined_answer += text
            # Emit lightweight stats right before closing the tag so it appears at the end of the streamed answer.
            urls = _extract_urls(web_search_results)
            max_urls_to_show = 40
            url_items = [f"`{u}`" for u in urls[:max_urls_to_show]]
            urls_md = ""
            if urls:
                urls_md = "\n\n" + two_column_list_md(url_items)
                if len(urls) > max_urls_to_show:
                    urls_md += f"\n\n_(Showing first {max_urls_to_show} of {len(urls)} URLs.)_"
            else:
                urls_md = "\n\n_No URLs detected in `web_search_results`._"

        
            stats_md_content = (
                "\n---\n### Web search stats\n"
                f"- **Visited links**: {len(urls)}\n"
                f"- **Combiner input size (`web_search_results`)**: {_count_words(web_search_results)} words, {len(web_search_results)} chars\n"
                f"- **Combined answer length**: {_count_words(combined_answer)} words\n"
                f"{urls_md}\n---\n"
            )
            stats_md = collapsible_wrapper(
                stats_md_content,
                header="Web Search Stats",
                show_initially=False,
                add_close_button=True
            )
            yield {"text": stats_md, "status": "Completed web search with agent"}
            yield {"text": '</web_answer>', "status": "Completed web search with agent"}
        else:
            yield {"text": '<web_answer>', "status": "Completed web search with agent"}
            yield {"text": str(web_search_results), "status": "Completed web search with agent"}
            yield {"text": '</web_answer>', "status": "Completed web search with agent"}

        yield {"text": self.post_process_answer(answer, temperature, max_tokens, system), "status": "Completed web search with agent"}

    def post_process_answer(self, answer, temperature=0.7, max_tokens=None, system=None):
        return ""
    
    def get_answer(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=True):
        answer = ""
        for chunk in self.__call__(text, images, temperature, stream, max_tokens, system, web_search):
            answer += chunk["text"]
        # Extract content between web_answer tags
        import re
        web_answer_pattern = r'<web_answer>(.*?)</web_answer>'
        match = re.search(web_answer_pattern, answer, re.DOTALL)
        if match:
            answer = match.group(1)
        return answer

class LiteratureReviewAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=90, gscholar=False, no_intermediate_llm=False):
        super().__init__(keys, model_name, detail_level, timeout, gscholar, no_intermediate_llm)
        self.concurrent_searches = False
        self.post_process_answer_needed = True
        self.combiner_prompt = f"""
You are tasked with creating a comprehensive literature survey based on multiple web search results. Your goal is to synthesize this information into a cohesive, academically rigorous review that addresses the user's query.

Instructions:
1. Carefully analyze and integrate information from all provided web search results.
2. Only use information from the provided web search results.
3. Include relevant references to support your points, citing them appropriately within the text.
4. If the web search results are not helpful or relevant, state: "No relevant information found in the web search results." and end your response.
5. Put relevant citations inline in markdown format in the text at the appropriate places in your response.
6. If no web search results are provided, please say so by saying "No web search results provided." and end your response.

These elements are crucial for compiling a complete academic document later.

Web search results:
<|results|>
{{web_search_results}}
</|results|>


User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please compose your literature survey, ensuring it thoroughly addresses the user's query while synthesizing information from all provided search results. Include the Latex version of the literature review and bibliography in BibTeX format at the end of your response.
"""

        year = time.localtime().tm_year
        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1 arxiv', 'detailed context1 including conversational context on what user is looking for'), 
    ('query2 research papers', 'detailed context2 including conversational context on what user is looking for'), 
    ('query3 research in {year}', 'detailed context3 including conversational context on what user is looking for'), 
    ...
]
```

Text: {{text}}

Add keywords like 'arxiv', 'research papers', 'research in {year}' to the queries to get relevant academic sources.
Generate up to 3 highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""
        self.write_in_latex_prompt = f"""
You were tasked with creating a comprehensive literature survey based on multiple web search results. Our goal was to synthesize this information into a cohesive, academically rigorous review that addresses the user's query.
Based on the user's query and the web search results, you have generated a literature review in markdown format. Now, you need to convert this markdown literature review into LaTeX format.
If any useful references were missed in the literature review, you can include them in the LaTeX version along with the existing content.

Given below is the user's query, the web search results and markdown literature review you have generated:
<|context|>
{{answer}}
</|context|>

Include the only two items below in your response.
1. Literature review written in LaTeX, enclosed in a code block. Use newlines in the LaTeX code after each full sentence to wrap it instead of making lines too long. Ensure that the LaTeX version is well-formatted and follows academic writing conventions.
2. A bibliography in BibTeX format, enclosed in a separate code block.

Write your response with two items (Literature review in LaTeX enclosed in code block and bibliography in BibTeX format enclosed in a separate code block) below.
"""
    def post_process_answer(self, answer, temperature=0.7, max_tokens=None, system=None):
        llm = CallLLm(self.keys, model_name=self.model_name)

        combined_response = llm(self.write_in_latex_prompt.format(answer=answer),
                                temperature=temperature, stream=False, max_tokens=max_tokens,
                                system=system)
        return "\n\n<hr></br>" + combined_response + "\n\n<hr></br>"


class BroadSearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=True):
        super().__init__(keys, model_name, detail_level, timeout, gscholar, no_intermediate_llm)
        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1 word1_for_localisation', 'detailed context1 including conversational context on what user is looking for'), 
    ('query2 maybe_word2_for_site_specific_searches', 'detailed context2 with conversational context on what we are looking for'), 
    ('query3', 'detailed context3 with conversational context on what we are looking for'), 
    ...
]
```

Text: {{text}}

Generate as many as needed relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""

class InstructionFollowingAgent(Agent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=False):
        super().__init__(keys)
        
        # System prompt for the backbone model - generates initial answer
        self.backbone_system_prompt = """You are a helpful, accurate, and intelligent AI assistant. 
Your task is to provide comprehensive and detailed answers to user queries.
Follow all instructions carefully and provide complete, well-structured responses."""
        
        # System prompt for the verifier model - checks instruction adherence
        self.verifier_system_prompt = """You are a meticulous instruction verification specialist.
Your role is to carefully analyze whether an AI response fully adheres to all instructions and requirements given in the original query.
You must identify any missing elements, overlooked instructions, or areas where the response doesn't fully meet the requirements."""
        
        # Prompt template for the verifier model
        self.verifier_prompt = """Carefully analyze the following user query and the AI's response.
Your task is to verify whether the response fully adheres to ALL instructions and requirements specified in the original query.

## Original User Query:
<user_query>
{user_query}
</user_query>

## AI's Response:
<ai_response>
{ai_response}
</ai_response>

## Your Task:
1. First, identify ALL explicit and implicit instructions/requirements in the user query
2. Check if the AI's response addresses each instruction/requirement
3. Identify any missing elements, overlooked instructions, or partial compliance

## Output Format:
Provide your analysis in the following format:

### Instructions Found in Query:
- List each instruction or requirement you identified in the user query

### Compliance Analysis:
For each instruction, indicate whether it was:
✅ Fully addressed
⚠️ Partially addressed  
❌ Not addressed

### Issues and Missing Elements:
If there are any issues, list them as bullet points:
- [Specific issue or missing element 1]
- [Specific issue or missing element 2]
- [etc.]

### Overall Assessment:
Provide a brief summary of whether the response fully meets the requirements or needs improvement.

Be thorough and specific in your analysis. Focus on instruction adherence, not on the quality of the content itself."""

        # System prompt for the rewriter model - improves answer based on feedback
        self.rewriter_system_prompt = """You are an expert at improving AI responses to better follow instructions.
Your task is to rewrite responses to fully address all requirements and instructions identified by the verifier.
You must maintain all good aspects of the original response while fixing any issues or adding missing elements."""
        
        # Prompt template for the rewriter model
        self.rewriter_prompt = """Based on the verification feedback, rewrite the AI response to fully address ALL instructions and requirements.

## Original User Query:
<user_query>
{user_query}
</user_query>

## Original AI Response:
<original_response>
{original_response}
</original_response>

## Verifier's Feedback:
<verifier_feedback>
{verifier_feedback}
</verifier_feedback>

## Your Task:
Rewrite the response to:
1. Maintain all good aspects of the original response
2. Address ALL issues and missing elements identified by the verifier
3. Ensure complete adherence to every instruction in the original query
4. Keep the same level of detail and quality, or improve it where needed

## Important Guidelines:
- Do NOT remove good content from the original response unless it's incorrect
- ADD missing elements identified by the verifier
- IMPROVE sections that were only partially compliant
- Ensure the response is comprehensive and follows ALL instructions
- Maintain a clear, well-structured format

Provide the improved response directly without any preamble or explanation."""
        
        # Initialize the models
        self.backbone_model = CallLLm(keys, model_name)
        self.verifier_model = CallLLm(keys, model_name)
        self.rewriter_model = CallLLm(keys, model_name)
        
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        """
        Execute the instruction-following agent workflow:
        1. Generate base answer with backbone model
        2. Verify instruction adherence with verifier model
        3. Rewrite answer based on verifier feedback with rewriter model
        """
        import time
        
        
        st = time.time()
        
        # Step 1: Generate base answer from backbone model
        backbone_system = system if system else self.backbone_system_prompt
        backbone_response_stream = self.backbone_model(
            text, 
            images, 
            temperature, 
            stream=True,  # Always stream internally for better UX
            max_tokens=max_tokens, 
            system=backbone_system
        )
        
        # Wrap backbone response in collapsible section and collect it
        backbone_response = ""
        wrapped_backbone = collapsible_wrapper(
            backbone_response_stream, 
            header="Initial Response", 
            show_initially=True,
            add_close_button=True
        )
        
        for chunk in wrapped_backbone:
            if chunk and not chunk.startswith("<details") and not chunk.startswith("</details") and not chunk.startswith("<summary") and not chunk.startswith("</summary") and not chunk.startswith("<button"):
                backbone_response += chunk
            yield chunk
        
        time_logger.info(f"Time taken for backbone response: {time.time() - st} seconds, response length: {len(backbone_response.split())} words")
        
        # Step 2: Verify instruction adherence
        verifier_prompt_formatted = self.verifier_prompt.format(
            user_query=text,
            ai_response=backbone_response
        )
        
        verifier_response_stream = self.verifier_model(
            verifier_prompt_formatted,
            images=[],  # Verifier doesn't need images
            temperature=0.3,  # Lower temperature for more consistent verification
            stream=True,
            max_tokens=max_tokens,
            system=self.verifier_system_prompt
        )
        
        # Wrap verifier response in collapsible section and collect it
        verifier_response = ""
        wrapped_verifier = collapsible_wrapper(
            verifier_response_stream,
            header="Instruction Verification",
            show_initially=False,
            add_close_button=True
        )
        
        for chunk in wrapped_verifier:
            if chunk and not chunk.startswith("<details") and not chunk.startswith("</details") and not chunk.startswith("<summary") and not chunk.startswith("</summary") and not chunk.startswith("<button"):
                verifier_response += chunk
            yield chunk
        
        time_logger.info(f"Time taken for verification: {time.time() - st} seconds")
        
        # Step 3: Rewrite based on verifier feedback
        rewriter_prompt_formatted = self.rewriter_prompt.format(
            user_query=text,
            original_response=backbone_response,
            verifier_feedback=verifier_response
        )
        
        # Add a separator before the final improved response
        yield "\n---\n\n## 📝 **Final Improved Response**\n\n"
        
        rewriter_response_stream = self.rewriter_model(
            rewriter_prompt_formatted,
            images=images,  # Include original images for rewriter
            temperature=temperature,
            stream=True,
            max_tokens=max_tokens,
            system=self.rewriter_system_prompt
        )
        
        # Stream the final improved response
        wrapped_rewriter = collapsible_wrapper(
            rewriter_response_stream,
            header="Improved Response",
            show_initially=True,
            add_close_button=True
        )
        rewriter_response = ""
        for chunk in wrapped_rewriter:
            if chunk and not chunk.startswith("<details") and not chunk.startswith("</details") and not chunk.startswith("<summary") and not chunk.startswith("</summary") and not chunk.startswith("<button"):
                rewriter_response += chunk
            yield chunk
        
        yield "\n\n"
        time_logger.info(f"Total time for instruction-following agent: {time.time() - st} seconds")
        
        # Log the improvement metrics if needed
        if verifier_response and "❌" in verifier_response:
            time_logger.info("Response required significant improvements to meet instructions")
        elif verifier_response and "⚠️" in verifier_response:
            time_logger.info("Response required minor improvements to fully meet instructions")
        else:
            time_logger.info("Initial response met all instructions adequately")


class ReflectionAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], improve_model: str, outline_model: str):
        self.keys = keys
        self.writer_model = writer_model
        self.improve_model = improve_model
        self.outline_model = outline_model
        self.system = """
As an AI language model assistant, your task is to enhance a simple answer provided for a user's query by performing self-reflection and objective analysis.
Answer comprehensively in detail like a PhD scholar and leading experienced expert in the field. Compose a clear, detailed, comprehensive, thoughtful and highly informative response.
Provide a detailed answer along with all necessary details, preliminaries, equations, references, citations, examples, explanations, etc.
We need to help people with hand, wrist disability and minimise typing and editing on their side. Deduce what the question or query is asking about and then go above and beyond to provide a high quality response. Write full answers.
Answer completely in a way that our work can be used by others directly without any further editing or modifications. We need to be detail oriented, cover all references and provide details, work hard and provide our best effort. 
        """.strip()
        self.prompt = f"""
As an AI language model assistant, your task is to enhance simple answers provided for a user's query by performing self-reflection and objective analysis. 
You will be given:  
- A **User Query**  and some context around it if necessary.
- One or more **Simple Expert Answers** generated by one or more AI models.
- Some guidance on how to write a good answer from another LLM model. You may optionally use this guidance to further help your reflection and thinking steps.
  
Follow the steps outlined below, using the specified XML-style tags to structure your response. This format will help in parsing and reviewing each part of your process.  

---  
## Instructions:  
1. **Identify all goals:**  
   - Carefully read and understand the user's query.  
   - Determine the main objectives and what the user is seeking.  
   - Determine how we can go above and beyond to provide a high-quality response and help the user effectively.
   - Enclose your findings within `<goals>` and `</goals>` tags.  
  
2. **Reflect on the Simple Answer:**  
   - If more than one simple answer is provided by different models, consider each one and pick the best parts and aspects from each.
   - Identify areas of improvement and gaps in the simple answers provided.
   - Assess how these simple answers can be combined and improved to better meet the user's needs.  
   - Identify any missing information, corner cases, or important considerations.  
   - Enclose your reflection within `<reflection>` and `</reflection>` tags using bullet points.  
  
3. **Think Logically and Step by Step about how to improve the answer:**  
   - Outline your thought process for improving the answer.  
   - Provide a logical, step-by-step explanation of enhancements.  
   - Enclose your reasoning within `<thinking>` and `</thinking>` tags using bullet points.  
 
4. **Provide the Improved Answer:**  
   - Compose a new, comprehensive answer that addresses all aspects of the user's query, incorporating all improvements identified in your reflection and all information from the simple expert answers.
   - Provide any and all details from the simple expert answers we already have in our final answer.
   - Enclose the final answer within `<answer>` and `</answer>` tags.  
   - In your final answer mention all the details, improvements, and information from the simple expert answers we already have.
  
---  
**Formatting Guidelines:**  
- Use the following XML-style tags to structure your response:  
  - `<goals>` ... `</goals>`  
  - `<reflection>` ... `</reflection>`  
  - `<thinking>` ... `</thinking>`  
  - `<answer>` comprehensive, detailed, all expert opinions combined, complete and final improved answer `</answer>`

User Query with context:
<user_query>
{{query}}
</user_query>

<optional_guidance>
{{guidance}}
</optional_guidance>

Simple Answers:
<simple_answers>
{{simple_answer}}
</simple_answers>

Now your overall response would look and be formatted like this:
<goals>
    [Identify the user's main objectives.]  
</goals>
<reflection>
    [Reflect on the simple answer or answers and identify areas of improvement.]  
</reflection>
<thinking>
    [Provide a step-by-step plan for enhancements.]  
</thinking>
<answer>
    [Provide the complete and final improved answer to the user's query. Final answer must include all the details, improvements, and information from the simple expert answers we already have. It should be comprehensive and detailed. It should combine all the ideas, insights, and improvements from the simple expert answers and provide a highly informative, in-depth and useful answer.] 
</answer>

If we have multiple simple answers, we include all ideas, insights, and improvements from each simple answer in our final answer. Write in detail and in a comprehensive manner.
Use good organization, formatting and structure in your response. 
Use simple markdown formatting and indentation for appealing and clear presentation. For markdown formatting use 2nd level or lower level headers (##) and lower headers for different sections. Basically use small size headers only.
Now respond to the user's query and enhance the simple answer provided in the above format.
""".lstrip()
        self.good_answer_characteristics_prompt = f"""
Your task is to write down the characteristics of a good answer. You must mention how a good answer should be structured and formatted, what it should contain, and how it should be presented.
You will be given:  
- A **User Query**  and some context around it if necessary.

Based on the user query and the context provided, write down the characteristics of a good answer. 
You must mention 
- what topics a good answer to the user query must contain, 
- how it should be structured, 
- what areas it must cover, 
- what information it should provide,
- what details it should include,
- what are some nuances that should be considered,
- If the query is about a specific topic, what are some key points that should be included,
- If the query is a trivia, logic question, science question, math question, coding or other type of logical question then what are some high level steps and skills that are needed to solve the question, 
- what are some Aha stuff and gotchas that should be included,
- what are some corner cases that should be addressed,
- how can we make the answer more informative and useful, engaging and interesting, stimulating and thought-provoking,
- how can we make the answer more comprehensive and detailed,
- how can we make the answer more accurate and correct and useful and implementable if needed,
- what parts of the answer, topics, areas, and details should be dived deeper into and emphasized, 
- how it should be formatted,
- and how it should be presented.
- You can also mention what are some common mistakes that should be avoided in the answer and what are some common pitfalls that should be addressed.
- Write a detailed and comprehensive outline of the answer that should be provided to the user.

User Query with context:
<user_query>
{{query}}
</user_query>

Write down the characteristics of a good answer in detail following the above guidelines and adding any additional information you think is relevant.
""".strip()
        self.first_model = CallLLm(keys, self.writer_model) if isinstance(self.writer_model, str) else CallMultipleLLM(keys, self.writer_model)
        self.improve_model = CallLLm(keys, self.improve_model)
        self.outline_model = CallLLm(keys, self.outline_model) if isinstance(self.outline_model, str) else CallLLm(keys, self.improve_model)

    @property
    def model_name(self):
        return self.writer_model
    
    @model_name.setter
    def model_name(self, model_name):
        self.writer_model = model_name
        self.improve_model = model_name if isinstance(model_name, str) else model_name[0]
        self.outline_model = model_name if isinstance(model_name, str) else model_name[0]
        
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        st = time.time()
        # outline_future = get_async_future(self.outline_model, self.good_answer_characteristics_prompt.format(query=text), images, temperature, False, max_tokens, system)
        first_response_stream = self.first_model(text, images, temperature, True, max_tokens, system)
        first_response = ""
        for chunk in first_response_stream:
            first_response += chunk
            yield chunk
        yield "\n\n"
        time_logger.info(f"Time taken to get multi model response: {time.time() - st} with response length: {len(first_response.split())}")
        # outline = sleep_and_get_future_result(outline_future)
        # time_logger.info(f"Time taken to get till outline: {time.time() - st} with outline length: {len(outline.split())}")
        outline = ""
        improve_prompt = self.prompt.format(query=text, simple_answer=first_response, guidance=outline)
        if system is None:
            system = self.system
        else:
            system = f"{self.system}\n{system}"

            # Start first details section for thinking
        yield "\n<details>\n<summary><strong>Analysis & Thinking</strong></summary>\n\n"
        
        improved_response_stream = self.improve_model(improve_prompt, images, temperature, True, max_tokens, system)
        improved_response = ""
        answer_section_started = False
        
        
        
        for chunk in improved_response_stream:
            if "<answer>" in improved_response:
                answer_section_started = True
                yield improved_response.split('<answer>')[0]
                yield "</details>\n\n"
                yield "<answer>\n"
                improved_response = improved_response.split('<answer>')[1]
                yield "\n<details open>\n<summary><strong>Improved Answer</strong></summary>\n\n"
                yield improved_response
            if answer_section_started:
                yield chunk
            improved_response += chunk
            
            
            
            

        # Close the details section
        yield "</details>\n\n"
        yield "\n\n"
        time_logger.info(f"Time taken to get improved response: {time.time() - st}")




class NResponseAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_responses: int = 3):
        self.keys = keys
        self.writer_model = writer_model
        self.n_responses = n_responses
        self.system = """
Select the best response from the given multiple responses.
        """.strip()

    @property
    def model_name(self):
        return self.writer_model
    
    @model_name.setter
    def model_name(self, model_name):
        self.writer_model = model_name
        self.evaluator_model = model_name if isinstance(model_name, str) else model_name[0]
        
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):

        # repeat self.writer_model n_responses times if it is a string, otherwise use the list directly
        self.writer_models = [self.writer_model] * self.n_responses if isinstance(self.writer_model, str) else self.writer_model
        llm = CallMultipleLLM(self.keys, self.writer_models)

        first_response_stream = llm(text, images, temperature, True, max_tokens, system)
        first_response = ""
        for chunk in first_response_stream:
            first_response += chunk
            yield chunk
        yield "\n\n---\n\n"
        
        
        
def is_future_ready(future):
    """Check if a future is ready without blocking"""
    return future.done() if hasattr(future, 'done') else True


class WhatIfAgent(Agent):
    def __init__(self, keys, writer_models: Union[List[str], str], n_scenarios: int = 5):
        super().__init__(keys)
        self.keys = keys
        # Convert single model to list for consistent handling
        self.writer_models = [writer_models] if isinstance(writer_models, str) else writer_models
        self.n_scenarios = n_scenarios
        
        self.what_if_prompt = """
You are tasked with generating creative "what-if" scenarios that would change the answer to the user's query in interesting ways.

For the given text/query, generate {n_scenarios} alternative what-if scenarios where the answer would be significantly different.
These scenarios can:
1. Add new constraints or remove existing ones
2. Change the context or situation in subtle ways
3. Introduce unexpected elements
4. Consider edge cases or extreme situations
5. Explore creative possibilities
6. Make sure the scenarios you generate are realistic and grounded in the context of the query and the domain of the query.

Format your response as a Python list of tuples, where each tuple contains:
1. A brief title for the what-if scenario
2. The modified query/situation incorporating the what-if
3. A short explanation of how this changes things

The format should be exactly like this:
```python
[
("Brief Title 1", "Modified query/situation 1", "How this changes things 1"),
("Brief Title 2", "Modified query/situation 2", "How this changes things 2"),
...
]
```

Original query/text:
<query>
{text}
</query>

Generate exactly {n_scenarios} creative and diverse what-if scenarios that would lead to different answers.
Write your response as a code block containing only the Python list of tuples.
"""


        
    def extract_what_ifs(self, response):
        """Extract and validate the what-if scenarios from LLM response"""
        import re
        import ast
        
        # Extract code block
        code_pattern = r"```(?:python)?\s*(.*?)```"
        matches = re.findall(code_pattern, response, re.DOTALL)
        
        if not matches:
            return []
            
        try:
            # Get the last code block and evaluate it
            scenarios = ast.literal_eval(matches[-1].strip())
            
            # Validate format
            if not isinstance(scenarios, list) or not all(
                isinstance(s, tuple) and len(s) == 3 
                for s in scenarios
            ):
                return []
                
            return scenarios
            
        except Exception as e:
            logger.error(f"Error parsing what-if scenarios: {e}, \n\n{traceback.format_exc()}")
            return []

    def format_what_if_query(self, original_text: str, what_if: tuple) -> str:
        """Format the what-if scenario into a query for the LLM"""
        title, modified_query, explanation = what_if
        return f"""Original Query/Situation:
{original_text}

What-if Scenario: {title}
Modified Situation: {modified_query}
Impact: {explanation}

Please provide an answer for this modified scenario."""

        
    def get_next_model(self, index: int) -> str:
        """Get next model in round-robin fashion"""
        return self.writer_models[index % len(self.writer_models)]

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        # Start what-if generation immediately in parallel
        what_if_future = get_async_future(
            what_if_llm := CallLLm(self.keys, self.writer_models[0]),
            self.what_if_prompt.format(text=text, n_scenarios=self.n_scenarios),
            temperature=temperature,
            stream=False
        )

        # Start initial response streaming immediately
        writer_llm = CallLLm(self.keys, self.writer_models[0])
        initial_response_stream = writer_llm(
            text, 
            images=images,
            temperature=temperature,
            stream=True,
            max_tokens=max_tokens,
            system=system
        )

        # Variables to track state
        initial_response = ""
        what_if_scenarios = None
        what_if_futures = []
        random_identifier = str(uuid.uuid4())
        
        # Stream initial response while checking if what-if scenarios are ready
        for chunk in initial_response_stream:
            initial_response += chunk
            yield {"text": chunk, "status": "Generating initial response"}
            
            # Check if what-if scenarios are ready (non-blocking)
            if what_if_scenarios is None and is_future_ready(what_if_future):
                # Get scenarios and start their responses immediately
                what_if_response = sleep_and_get_future_result(what_if_future)
                what_if_scenarios = self.extract_what_ifs(what_if_response)
                
                # Start generating what-if responses in parallel
                for i, scenario in enumerate(what_if_scenarios, 1):
                    model = self.get_next_model(i)
                    writer_llm = CallLLm(self.keys, model)
                    modified_query = self.format_what_if_query(text, scenario)
                    future = get_async_future(
                        writer_llm,
                        modified_query,
                        images=images,
                        temperature=temperature,
                        stream=False,
                        max_tokens=max_tokens,
                        system=system
                    )
                    what_if_futures.append((scenario, future, model))

        # If what-if scenarios weren't ready during streaming, get them now
        if what_if_scenarios is None:
            what_if_response = sleep_and_get_future_result(what_if_future)
            what_if_scenarios = self.extract_what_ifs(what_if_response)
            
            # Start generating what-if responses
            for i, scenario in enumerate(what_if_scenarios, 1):
                model = self.get_next_model(i)
                writer_llm = CallLLm(self.keys, model)
                modified_query = self.format_what_if_query(text, scenario)
                future = get_async_future(
                    writer_llm,
                    modified_query,
                    images=images,
                    temperature=temperature,
                    stream=False,
                    max_tokens=max_tokens,
                    system=system
                )
                what_if_futures.append((scenario, future, model))

        # Format and yield what-if scenarios
        scenarios_text = "# What-If Scenarios Generated:\n\n"
        for i, (title, query, explanation) in enumerate(what_if_scenarios, 1):
            model_used = self.get_next_model(i)
            scenarios_text += f"**Scenario {i}: {title}** (Using model: {model_used})\n"
            scenarios_text += f"- Modified Situation: {query}\n"
            scenarios_text += f"- Impact: {explanation}\n\n"
        
        yield {"text": "\n\n" + scenarios_text, "status": "Generated what-if scenarios"}

        # Format initial response with collapsible section
        all_responses = [
            f"**Initial Response** (Using model: {self.writer_models[0]}):\n"
            f"<div data-toggle='collapse' href='#response-{random_identifier}-initial' role='button' aria-expanded='true'></div> "
            f"<div class='collapse show' id='response-{random_identifier}-initial'>\n{initial_response}\n</div>"
        ]

        # Collect and format what-if responses as they complete
        for i, (scenario, future, model) in enumerate(what_if_futures, 1):
            try:
                response = sleep_and_get_future_result(future)
                title = scenario[0]
                
                response_html = (
                    f"**What-If Scenario {i}: {title}** (Using model: {model})\n"
                    f"<div data-toggle='collapse' href='#response-{random_identifier}-{i}' "
                    f"role='button' aria-expanded='false'></div> "
                    f"<div class='collapse' id='response-{random_identifier}-{i}'>\n{response}\n</div>"
                )
                
                all_responses.append(response_html)
                yield {"text": "\n\n" + response_html, "status": f"Generated response for scenario {i} using {model}"}
                
            except Exception as e:
                logger.error(f"Error getting response for scenario {i} with model {model}: {e}, \n\n{traceback.format_exc()}")

        # Final yield with metadata
        yield {
            "text": "\n\n",
            "status": "Completed what-if analysis",
            "scenarios": what_if_scenarios,
            "initial_response": initial_response,
            "models_used": {
                "initial": self.writer_models[0],
                "what_if_generator": self.writer_models[0],
                "scenario_responses": [self.get_next_model(i) for i in range(1, len(what_if_scenarios) + 1)]
            }
        }


class PerplexitySearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=5, headless=False, no_intermediate_llm=False):
        super().__init__(keys, model_name, detail_level, timeout, headless=headless)
        self.num_queries = num_queries
        self.no_intermediate_llm = no_intermediate_llm
        self.perplexity_models = [
            
            "perplexity/sonar-pro",
            "perplexity/sonar",
            # "perplexity/llama-3.1-sonar-large-128k-online"
        ]
        
        if detail_level >= 3:
            
            # self.perplexity_models.append("perplexity/sonar-pro")
            self.perplexity_models.append("perplexity/sonar-reasoning")
            self.perplexity_models.append("perplexity/sonar-reasoning-pro")
        if detail_level >= 4:
            self.perplexity_models.append("perplexity/sonar-deep-research")
        
        year = time.localtime().tm_year
        self.get_references = f"""
[Important: Provide links and references inline closest to where applicable and provide all references you used finally at the end for my question as well. Search and look at references and information exhaustively and dive deep before answering. Think carefully before answering and provide an comprehensive, extensive answer using the references deeply. Provide all references with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.]
""".strip()
        
        # Override the llm_prompt to generate more diverse queries while maintaining the same format
        self.llm_prompt = f"""
Given the following user query and context, generate a list of relevant queries and their corresponding contexts. 
generate diverse queries that:
1. Directly address the main topic
2. Explore related subtopics and side aspects
3. Include domain-specific variations (as relevant) by adding keywords like:
   - For scientific topics: "research papers", "arxiv", "scientific studies"
   - For location-based topics: append relevant place names
   - For temporal topics: add years/timeframes
   - For domain-specific topics: add field identifiers (finance, politics, technology, etc.)
   - Both the query and the context pair should be detailed and capture the user's query and well enough for good web search.

Format your response as a Python list of tuples as given below: 
```python
[
    ('main topic exact query', 'short context about main topic with conversational context on what user is looking for'), 
    ('main topic research papers [if query is about research]', 'short context focusing on academic research'),
    ('related subtopic with year {year}', 'short context about temporal aspects with conversational context on what user is looking for'),
    ('specific aspect in domain/location', 'very short context about domain-specific elements'),
    ('main topic with location [if query is about location]', 'short and brief context about location'),
    ('main topic with year', 'short and brief context about temporal aspects with conversational context on what user is looking for'),
    ('side aspect topic with location', 'short and brief context about location with conversational context on what user is looking for'),
    ('another side aspect topic', 'short and brief context about side aspect with conversational context on what user is looking for'),
    ('more related subtopics', 'very short and brief context about more related subtopics with conversational context on what user is looking for'),
    ('more related side aspect topics', 'very short and brief context about more related side aspect topics with conversational context on what user is looking for'),
    ('wider coverage topics with year', 'very short and brief context about wider coverage topics with year with conversational context on what user is looking for'),
    ...
]
```

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Generate exactly {self.num_queries} highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""

        # Override the combiner_prompt to better handle multiple model responses
        self.combiner_prompt = f"""
Collate and combine information from multiple search results obtained from different queries. Your goal is to combine these results into a comprehensive response for the user's query.

Instructions:
1. Integrate and utilize information from all provided search results to write your extensive response.
2. Write a detailed, in-depth, wide coverage and comprehensive response to the user's query using all the information from the search results. Write full answers with all details well formatted.
3. Provide all references (that are present in the search results) with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.
4. Provide side information from the search results to provide more context and broader perspective.
5. Important: Provide links and references inline closest to where applicable and provide all references you used finally at the end for my question as well. Search and look at references and information exhaustively and dive deep before answering. Think carefully before answering and provide an comprehensive, extensive answer using all the references deeply. Provide all references with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.

Web search results (from multiple sources):
<|results|>
{{web_search_results}}
</|results|>

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please use the given search results to answer the user's query while combining information from all provided search results. Use all the information from the search results to write a detailed and comprehensive answer. Include the full list of useful references at the end in markdown as bullet points.
"""

    def get_results_from_web_search(self, text, text_queries_contexts):
        array_string = text_queries_contexts
        web_search_results = []
        try:
            # Use ast.literal_eval to safely evaluate the string as a Python expression
            import ast
            text_queries_contexts = ast.literal_eval(array_string)
            
            # Ensure the result is a list of tuples
            if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) for item in text_queries_contexts):
                raise ValueError("Invalid format: expected list of tuples")
            
            futures = []
            year = time.localtime().tm_year
            # For each query, create futures for both perplexity models
            for query, context in text_queries_contexts:
                for model in self.perplexity_models:
                    llm = CallLLm(self.keys, model_name=model)
                    future = get_async_future(
                        llm,
                        # text + "\n\n" + context + "\n\nQuery: " + query,
                        "Context: " + context + "\n\nQuery: " + query + "\n" + self.get_references,
                        timeout=self.timeout
                    )
                    futures.append((query, context, model, future))

            # Collect and format results
            for query, context, model, future in futures:
                try:
                    result = sleep_and_get_future_result(future)
                    model_name = model.split('/')[-1]  # Extract shorter model name
                    random_identifier = str(uuid.uuid4())
                    web_search_results.append(
                        f"**Single Query Web Search with query '{query}' :** <div data-toggle='collapse' href='#singleQueryWebSearch-{random_identifier}' role='button'></div> <div class='collapse' id='singleQueryWebSearch-{random_identifier}'>"
                        f"<b>Query:</b> {query}\n"
                        f"<b>Model ({model_name}):</b>\n{result}\n"
                        f"---\n"
                        f"</div>"
                    )
                except Exception as e:
                    logger.error(f"Error getting response for query '{query}' from model {model}: {e}, \n\n{traceback.format_exc()}")
                    
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing text_queries_contexts: {e}")
            text_queries_contexts = None
            
        return "\n".join(web_search_results)
    

class JinaSearchAgent(PerplexitySearchAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=5, headless=False, no_intermediate_llm=False):
        super().__init__(keys, model_name, detail_level, timeout, num_queries, headless=headless, no_intermediate_llm=no_intermediate_llm)
        self.jina_api_key = os.environ.get("jinaAIKey", "") or keys.get("jinaAIKey", "")
        assert self.jina_api_key, "No Jina API key found. Please set JINA_API_KEY environment variable."
        # Default was quite aggressive and causes large latency at detail_level=1.
        # Keep fewer results for low detail, more for deeper research.
        self.num_results = 5 if detail_level <= 1 else 8 if detail_level == 2 else 20
        # Tighten HTTP timeouts to avoid long hangs.
        self.http_timeout = (10, 45)  # (connect, read) seconds


    def fetch_jina_search_results(self, query: str):
        """Fetch search results from Jina API"""
        import requests
        import urllib.parse
        num_results: int = self.num_results
        
        encoded_query = urllib.parse.quote(query)
        url = f"https://s.jina.ai/?q={encoded_query}&num={num_results}"
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.jina_api_key}",
            "X-Engine": "cf-browser-rendering"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=self.http_timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching search results from Jina: {e}, \n\n{traceback.format_exc()}")
            return {"data": []}

    def fetch_jina_content(self, url: str):
        """Fetch content from a URL using Jina reader API"""
        import requests
        
        # Reader endpoint can occasionally fail DNS/regionally; keep default, but add timeout.
        reader_url = f"https://r.jina.ai/{url}"
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.jina_api_key}"
        }
        
        try:
            response = requests.get(reader_url, headers=headers, timeout=self.http_timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching content from Jina reader: {e}, \n\n{traceback.format_exc()}")
            return {"data": {"content": f"Error fetching content: {e}"}}

    def process_search_result(self, result, query, context, user_text):
        """Process a single search result from Jina API"""
        if not result.get("url"):
            return None
            
        # Skip YouTube links
        if "youtube.com" in result["url"] or "youtu.be" in result["url"]:
            return None
            
        # Check if we need to convert to PDF link
        original_url = result["url"]
        pdf_url = convert_to_pdf_link_if_needed(original_url)
        
        title = result.get("title", "")
        description = result.get("description", "")
        date = result.get("date", "")
        
        # If link was converted to PDF, fetch the content
        content = ""
        if pdf_url != original_url:
            content_response = self.fetch_jina_content(pdf_url)
            content = content_response.get("data", {}).get("content", "")
        else:
            content = result.get("content", "")

        # if content is too long, truncate it to 5000 characters
        if len(content) > 10_000:
            content = content[:100_000] + "..."
            llm = CallLLm(self.keys, model_name=VERY_CHEAP_LLM[0])
            content = llm(f"You are an information extraction expert. Given a user query and conversation context you will extract relevant information from the page content. \n\nUser's query: {query}\n\nUser's context: {context}\n\nUser's and assistant's text: {user_text}\n\nPlease extract and summarize the following page content to less than 200 words to extract only the most relevant information as per the user's query. \n\nPage content: \n{content}\n", temperature=0.7, stream=False)
        
        processed_result = {
            "title": title,
            "url": original_url,
            "pdf_url": pdf_url if pdf_url != original_url else None,
            "description": description,
            "date": date,
            "content": content
        }
        
        return processed_result

    def get_results_from_web_search(self, text, text_queries_contexts):
        array_string = text_queries_contexts
        web_search_results = []
        
        try:
            # Parse the query contexts
            import ast
            text_queries_contexts = ast.literal_eval(array_string)
            
            # Validate format
            if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) for item in text_queries_contexts):
                raise ValueError("Invalid format: expected list of tuples")
            
            futures = []
            
            # For each query, create a future to search and process results
            for query, context in text_queries_contexts:
                # Create a future for the search and processing
                future = get_async_future(
                    self.process_query,
                    query, 
                    context,
                    text,
                )
                futures.append((query, context, future))
            
            # Collect and format results (as they complete)
            for query, context, future in futures:
                try:
                    result = sleep_and_get_future_result(future)
                    random_identifier = str(uuid.uuid4())
                    web_search_results.append(
                        f"**Single Query Web Search with query '{query}' :** <div data-toggle='collapse' href='#singleQueryWebSearch-{random_identifier}' role='button'></div> <div class='collapse' id='singleQueryWebSearch-{random_identifier}'>"
                        f"<b>Query:</b> {query}\n"
                        f"<b>Context:</b> {context}\n"
                        f"{result}\n"
                        f"---\n"
                        f"</div>"
                    )
                except Exception as e:
                    logger.error(f"Error getting response for query '{query}': {e}, \n\n{traceback.format_exc()}")
                    
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing text_queries_contexts: {e}")
            text_queries_contexts = None
            
        return "\n".join(web_search_results)
    
    def process_query(self, query, context, user_text):
        """Process a single query and return formatted results with LLM summary"""
        # Search using Jina API
        search_response = self.fetch_jina_search_results(query)
        results = search_response.get("data", [])
        num_results = self.num_results
        
        # Process each result
        processed_results = []
        # Process results in parallel
        futures = []
        for result in results:
            future = get_async_future(
                self.process_search_result,
                result,
                query,
                context, 
                user_text,
            )
            futures.append(future)
        
        # Collect results
        for future in futures:
            try:
                processed = sleep_and_get_future_result(future)
                if processed:
                    processed_results.append(processed)
            except Exception as e:
                logger.error(f"Error processing search result: {e}, \n\n{traceback.format_exc()}")
        
        # Format results for display and LLM summarization
        formatted_results = []
        # Keep prompt sizes smaller at low detail for faster combiner calls.
        preview_chars = 5000 if self.detail_level <= 1 else 7500 if self.detail_level == 2 else 9000

        for idx, result in enumerate(processed_results[:num_results], 1):
            formatted_result = (
                f"### {idx}. [{result['title']}]({result['url']})\n"
                f"**Date**: {result.get('date', 'N/A')}\n"
                f"**Description**: {result.get('description', 'N/A')}\n"
            )
            
            # Add content if available
            if result.get('content'):
                content_preview = result['content'][:preview_chars] + "..." if len(result['content']) > preview_chars else result['content']
                formatted_result += f"**Content Preview**: {content_preview}\n"
            
            formatted_results.append(formatted_result)
        
        # Join the formatted results
        all_results = "\n\n".join(formatted_results)
        
        # If we have results, summarize them with LLM
        if formatted_results:
            try:
                llm = CallLLm(self.keys, model_name=self.model_name)
                
                # Create a mini version of the combiner prompt specific to this query result
                mini_combiner_prompt = f"""User Query: {user_text}\n\nSearch Query: {query}\n\nSearch Context: {context}\n\n"""
                
                # Generate summary
                summary = llm(self.combiner_prompt.format(web_search_results=all_results, text=mini_combiner_prompt), temperature=0.7, stream=False)
                
                # Return the full package
                return f"<b>Search Results:</b>\n\n{all_results}\n\n<b>Summary:</b>\n\n{summary}"
            except Exception as e:
                logger.error(f"Error summarizing results with LLM: {e}, \n\n{traceback.format_exc()}")
                return f"<b>Search Results:</b>\n\n{all_results}\n\n<b>Error summarizing results:</b> {str(e)}"
        else:
            return f"<b>No relevant search results found for query:</b> {query}"
        

class OpenaiDeepResearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=5):
        super().__init__(keys, model_name, detail_level, timeout, num_queries)
        self.openai_deep_research_model = model_name
        
        
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=True):
        response = self.openai_deep_research_model(text, images, temperature, stream, max_tokens, system, web_search)
        return response
        
        
        
        

def extract_answer(agent, text, images, temperature, stream, max_tokens, system, web_search):
        response = agent(text, images, temperature, stream, max_tokens, system, web_search)
        full_answer = ""
        for chunk in response:
            full_answer += chunk["text"]
        # Extract content between web_answer tags
        import re
        web_answer_pattern = r'<web_answer>(.*?)</web_answer>'
        match = re.search(web_answer_pattern, full_answer, re.DOTALL)
        answer = ""
        if match:
            answer = match.group(1)
        return answer, full_answer

class MultiSourceSearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=90, num_queries=3, show_intermediate_results=False, headless=False):
        self.keys = keys
        self.model_name = model_name
        self.detail_level = detail_level
        self.timeout = timeout
        self.num_queries = num_queries
        self.show_intermediate_results = show_intermediate_results
        self.headless = headless
        # NOTE: Call parent with keyword args to avoid accidental positional mismatches.
        # (The parent signature includes gscholar/no_intermediate_llm before show_intermediate_results.)
        super().__init__(
            keys=keys,
            model_name=model_name,
            detail_level=detail_level,
            timeout=timeout,
            show_intermediate_results=show_intermediate_results,
            headless=headless,
        )
        self.combiner_prompt = """
You are a helpful assistant that combines search results from multiple sources into a single response.
You will be given a user query, and a list of search results from multiple sources.
You will need to combine the search results into a single response.

Your goal is to combine these results into a comprehensive response for the user's query.

Instructions:
1. Integrate and utilize information from all provided search results to write your extensive response.
2. Write a detailed, in-depth, wide coverage and comprehensive response to the user's query using all the information from the search results. Write full answers with all details well formatted.
3. Provide all references (that are present in the search results) with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.
4. Provide side information from the search results to provide more context and broader perspective.
5. Important: Provide links and references inline closest to where applicable and provide all references you used finally at the end for my question as well. Search and look at refere

Here is the user query:
{user_query}

Here is the answer from web search:
{web_search_results}

Here is the answer from perplexity search:
{perplexity_search_results}

Here is the answer from jina search:
{jina_search_results}

Now, combine the search results into a single response. Please use the given search results to answer the user's query while combining information from all provided search results. Use all the information from the search results to write a detailed and comprehensive answer. 
Include the full list of useful references at the end in markdown as bullet points.
Write your comprehensive and in-depth answer below. Provide full extensive details and cover all references and sources obtained from search.
"""

    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        web_search_agent = WebSearchWithAgent(self.keys, OPENAI_CHEAP_LLM, max(self.detail_level - 1, 1), self.timeout, headless=True, no_intermediate_llm=True)
        perplexity_search_agent = PerplexitySearchAgent(self.keys, OPENAI_CHEAP_LLM, max(self.detail_level - 1, 1), self.timeout, self.num_queries, headless=True, no_intermediate_llm=True)
        jina_search_agent = JinaSearchAgent(self.keys, OPENAI_CHEAP_LLM, max(self.detail_level - 1, 1), self.timeout, self.num_queries, headless=True, no_intermediate_llm=True)
        
        web_search_results = get_async_future(extract_answer, web_search_agent, text, images, temperature, stream, max_tokens, system, web_search)
        perplexity_results = get_async_future(extract_answer, perplexity_search_agent, text, images, temperature, stream, max_tokens, system, web_search)
        jina_results = get_async_future(extract_answer, jina_search_agent, text, images, temperature, stream, max_tokens, system, web_search)
        llm = CallLLm(self.keys, model_name=self.model_name)
        
        web_search_results_short = ""
        perplexity_results_short = ""
        jina_results_short = ""
        st_time = time.time()

        # Run sources concurrently and STREAM each result section as soon as it completes.
        # (Previously the code effectively waited for the slowest source before yielding anything.)
        from concurrent.futures import wait, FIRST_COMPLETED

        futures_map = {
            web_search_results: "web_search",
            perplexity_results: "perplexity",
            jina_results: "jina",
        }
        pending = set(futures_map.keys())

        # Timeouts tuned for responsiveness; slow sources shouldn't block fast ones from being shown.
        total_timeout = 180 if self.detail_level >= 3 else 140
        start_wait = time.time()

        yielded_sections = set()

        while pending and (time.time() - start_wait) < total_timeout:
            done, pending = wait(pending, timeout=2, return_when=FIRST_COMPLETED)

            for future in done:
                source = futures_map.get(future, "unknown")
                try:
                    result_short, result_full = future.result(timeout=1)
                except Exception as e:
                    logger.error(f"MultiSourceSearchAgent: {source} failed with error: {e}")
                    continue

                if source == "web_search":
                    web_search_results_short, web_search_full_answer = result_short, result_full
                elif source == "perplexity":
                    perplexity_results_short, perplexity_full_answer = result_short, result_full
                elif source == "jina":
                    jina_results_short, jina_full_answer = result_short, result_full

                logger.info(f"MultiSourceSearchAgent: {source} completed in {time.time() - start_wait:.2f}s")

                # Stream the completed section immediately (skip empty).
                if source not in yielded_sections:
                    header = (
                        "Web Search Results"
                        if source == "web_search"
                        else "Perplexity Search Results"
                        if source == "perplexity"
                        else "Jina Search Results"
                    )
                    section_text = (
                        web_search_results_short
                        if source == "web_search"
                        else perplexity_results_short
                        if source == "perplexity"
                        else jina_results_short
                    ) or ""
                    if str(section_text).strip() and self.show_intermediate_results:
                        section_text = convert_stream_to_iterable(
                            collapsible_wrapper(section_text, header=header, show_initially=False, add_close_button=True)
                        )
                        yield {"text": section_text, "status": "MultiSourceSearchAgent"}
                        yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
                    yielded_sections.add(source)

        # Anything that didn't finish: record as timed out, but still proceed with available results.
        for future in list(pending):
            source = futures_map.get(future, "unknown")
            logger.error(f"MultiSourceSearchAgent: {source} timed out after {total_timeout}s")

        # If no source returned anything usable, avoid calling the combiner with empty input.
        if not (str(web_search_results_short).strip() or str(perplexity_results_short).strip() or str(jina_results_short).strip()):
            yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
            yield {"text": f"MultiSourceSearchAgent: No search sources returned results within {total_timeout}s.", "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
            yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}
            return
        
        # If some sections weren't yielded during the loop (e.g., returned instantly before first wait tick),
        # yield them here in a deterministic order.
        if "web_search" not in yielded_sections and web_search_results_short and self.show_intermediate_results:
            web_search_results_short = convert_stream_to_iterable(
                collapsible_wrapper(web_search_results_short, header="Web Search Results", show_initially=False, add_close_button=True)
            )
            yield {"text": web_search_results_short, "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        if "perplexity" not in yielded_sections and perplexity_results_short and self.show_intermediate_results:
            perplexity_results_short = convert_stream_to_iterable(
                collapsible_wrapper(perplexity_results_short, header="Perplexity Search Results", show_initially=False, add_close_button=True)
            )
            yield {"text": perplexity_results_short, "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        if "jina" not in yielded_sections and jina_results_short and self.show_intermediate_results:
            jina_results_short = convert_stream_to_iterable(
                collapsible_wrapper(jina_results_short, header="Jina Search Results", show_initially=False, add_close_button=True)
            )
            yield {"text": jina_results_short, "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}

        logger.info(f"MultiSourceSearchAgent: Now calling combiner LLM... Headless mode: {self.headless}, show_intermediate_results: {self.show_intermediate_results}")

        if not self.headless:

            response = llm(
                self.combiner_prompt.format(
                    user_query=text,
                    web_search_results=web_search_results_short,
                    perplexity_search_results=perplexity_results_short,
                    jina_search_results=jina_results_short,
                ),
                temperature=temperature,
                stream=True,
                max_tokens=max_tokens,
                system=system,
            )

            yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
            answer = ""
            for chunk in response:
                yield {"text": chunk, "status": "MultiSourceSearchAgent"}
                answer += chunk
            # Stats footer (inside <web_answer> but before </web_answer>) so it shows at the end of the streamed answer.
            sources_concat = "\n\n".join(
                [
                    str(web_search_results_short or ""),
                    str(perplexity_results_short or ""),
                    str(jina_results_short or ""),
                ]
            )
            urls = _extract_urls(sources_concat)
            max_urls_to_show = 40
            url_items = [f"`{u}`" for u in urls[:max_urls_to_show]]
            urls_md = ""
            if urls:
                urls_md = "\n\n" + two_column_list_md(url_items)
                if len(urls) > max_urls_to_show:
                    urls_md += f"\n\n_(Showing first {max_urls_to_show} of {len(urls)} URLs.)_"
            else:
                urls_md = "\n\n_No URLs detected in the source results._"

            stats_md_content = (
                "\n---\n## Web search stats\n"
                f"- **Visited links**: {len(urls)}\n"
                f"- **Web search input size**: {_count_words(str(web_search_results_short or ''))} words, {len(str(web_search_results_short or ''))} chars\n"
                f"- **Perplexity input size**: {_count_words(str(perplexity_results_short or ''))} words, {len(str(perplexity_results_short or ''))} chars\n"
                f"- **Jina input size**: {_count_words(str(jina_results_short or ''))} words, {len(str(jina_results_short or ''))} chars\n"
                f"- **Combined answer length**: {_count_words(answer)} words\n"
                f"{urls_md}\n---\n"
            )
            stats_md = collapsible_wrapper(
                stats_md_content,
                header="Web Search Stats",
                show_initially=False,
                add_close_button=True,
            )
            yield {"text": stats_md, "status": "MultiSourceSearchAgent"}
        else:
            # If the futures timed out or returned nothing, yield what we got so far
            yield {"text": str(web_search_results_short or "") + "\n\n" + str(perplexity_results_short or "") + "\n\n" + str(jina_results_short or ""), "status": "MultiSourceSearchAgent"}


class InterleavedWebSearchAgent(Agent):
    """
    Interleaved web-search agent: supports iterative search→answer→search→answer loops.

    ## Requirements / Why this exists
    The existing agents (`WebSearchWithAgent`, `PerplexitySearchAgent`, `JinaSearchAgent`, `MultiSourceSearchAgent`)
    do a single, non-interleaved pass:
    1) generate queries (or accept provided query-context tuples)
    2) fetch search results
    3) run a combiner LLM to write the final answer

    This is a mismatch for tasks that benefit from *multi-hop* reasoning where the assistant should:
    - start answering with partial info
    - notice gaps / sub-questions / missing citations
    - run a follow-up search based on the partial answer
    - continue the answer with the new evidence

    `InterleavedWebSearchAgent` implements that loop with configurable steps and sources, while streaming only the
    evolving answer (optionally hiding intermediate query planning and raw results).

    ## Architecture (high level)
    Inputs:
    - `text`: user's query + conversation context (same convention as other agents)
    - `interleave_steps`: number of search/answer cycles
    - `sources`: which existing search agents to use for each step (web/perplexity/jina), configurable
    - `num_queries_per_step`: how many follow-up queries to plan at each step
    - `show_intermediate_results`: if True, yields collapsible query/result blocks per step; otherwise only yields answer

    Loop per step:
    1) **Query planner LLM** proposes a list of `(query, context)` tuples (Python list literal inside ```python ... ```).
    2) For each configured source agent:
       - run in `headless=True` mode so we can capture results without nested UI wrappers
       - pass the planner's list literal *as a code block* appended to the text so the agent uses it directly
    3) **Answer LLM** streams an "answer continuation" using:
       - original user `text`
       - `answer_so_far`
       - the new search results from this step
       The streamed tokens are yielded immediately.

    ## Prompt caching strategy
    True provider-side prompt caching depends on the LLM backend. This class maximizes cacheability by:
    - keeping a stable prompt prefix and only *appending* new sections each step (answer + new evidence)
    - avoiding reformatting earlier parts between steps
    This allows any backend that caches prompt prefixes to reuse them effectively.
    """

    def __init__(
        self,
        keys,
        model_name,
        detail_level: int = 2,
        timeout: int = 90,
        interleave_steps: int = 3,
        min_interleave_steps: int = 2,
        num_queries_per_step: int = 3,
        sources: List[str] = None,
        min_successful_sources: int = 2,
        show_intermediate_results: bool = False,
        headless: bool = False,
        planner_model_name: str = None,
        max_sources_chars: int = 60_000,
    ):
        """
        Args:
            keys: Credentials dictionary.
            model_name: Model for answer writing (streaming).
            detail_level: Rough depth knob; used to set sub-agent detail level.
            timeout: Timeout passed to search sub-agents.
            interleave_steps: Number of search→answer cycles.
            min_interleave_steps: Minimum number of interleave steps to run before allowing early-stop sentinels.
            num_queries_per_step: Number of (query, context) tuples per cycle.
            sources: List of source identifiers: "web", "perplexity", "jina".
            min_successful_sources: Stop waiting for more sources once this many sources returned non-empty results.
            show_intermediate_results: If True, yields collapsible planner/output per step.
            headless: If True, does not wrap output in <web_answer> tags.
            planner_model_name: Optional separate model for query planning.
            max_sources_chars: Truncation limit for accumulated evidence in the answer prompt.
        """
        super().__init__(keys)
        self.keys = keys
        self.model_name = model_name
        self.planner_model_name = planner_model_name or model_name
        self.detail_level = detail_level
        self.timeout = timeout
        self.interleave_steps = max(1, int(interleave_steps))
        self.min_interleave_steps = max(1, int(min_interleave_steps))
        # Ensure min_interleave_steps does not exceed total configured steps.
        self.min_interleave_steps = min(self.min_interleave_steps, self.interleave_steps)
        self.num_queries_per_step = max(1, int(num_queries_per_step))
        self.sources = sources or ["web", "perplexity", "jina"]
        self.min_successful_sources = max(1, int(min_successful_sources))
        self.show_intermediate_results = show_intermediate_results
        self.headless = headless
        self.max_sources_chars = max_sources_chars

        # Sentinels for early stopping interleaving.
        # - Planner sentinel is returned as a special tuple in the planned query list.
        # - Answer sentinel is a special token emitted by the answering LLM (and filtered from user-visible output).
        self.planner_done_sentinel = "__INTERLEAVE_DONE__"
        self.answer_done_sentinel = "<INTERLEAVE_DONE/>"

        self.query_planner_prompt = f"""
You are an expert research assistant. You will propose follow-up web search queries to refine and complete an answer.

Goal: propose the *next* set of search queries needed to continue answering the user's request.

Constraints:
- Output MUST be a Python list of tuples: [(query, context), ...]
- Each tuple has:
  - query: a concise search query string
  - context: a short description of what we want from that query and why
- Generate exactly {self.num_queries_per_step} tuples.
- Keep queries diverse and non-overlapping; prioritize missing citations, missing sub-answers, or ambiguous claims.
- If you are highly confident (very high confidence) that NO further searching is needed to answer well,
  output the following sentinel *as the ONLY item*:
  ```python
  [("{self.planner_done_sentinel}", "HIGH_CONFIDENCE: reason why no more search is needed")]
  ```

User request / conversation context:
<context>
{{text}}
</context>

Current answer-so-far (may be empty):
<answer_so_far>
{{answer_so_far}}
</answer_so_far>

Now output ONLY a single python code block with the list of {self.num_queries_per_step} tuples:
```python
[(query, context), (...), ...]
```
""".strip()

        # NOTE on prompt caching:
        # We intentionally avoid re-formatting / re-inserting {answer_so_far} and {evidence} into the middle of a prompt
        # each step, because that invalidates provider-side prompt prefix caching for everything after the insertion point.
        #
        # Instead, we keep a stable prompt prefix and append a single "Step block" each iteration:
        #   - Evidence for this step
        #   - Answer continuation for this step
        #
        # We then call the answer LLM with:
        #   stable_prefix + rolling_history + current_step_block_prefix
        #
        # Where current_step_block_prefix ends with "### Answer\n" so the model continues from there. This keeps all prior
        # content byte-for-byte identical across steps (maximizing cache hit rates in backends that support it).
        self.answer_prompt_prefix = """
You are a helpful assistant writing a single cohesive answer over multiple iterations.

Rules:
- Only CONTINUE the answer; do not restart from scratch.
- Do not repeat earlier content unless needed to correct a contradiction.
- Use the newest evidence to add missing details and include citations/links inline when possible.
- Keep a consistent voice and structure across steps.
- If (and only if) you are highly confident (very high confidence) the answer is complete and no further web searching
  is needed, end your continuation with the exact sentinel token: <INTERLEAVE_DONE/>
  Otherwise do NOT emit that sentinel.

User request / conversation context:
<context>
{text}
</context>
""".strip()

        self.answer_step_block_template = """

---
## Interleave step {step_idx}

### Evidence
{evidence}

### Answer
""".lstrip("\n")

    def _extract_list_literal_from_codeblock(self, code_string: str) -> str:
        """
        Extract a Python list literal from a markdown code block.

        Returns:
            A string containing the list literal (e.g. "[('q','c'), ...]") or "" if not found.
        """
        if not code_string:
            return ""
        regex = r"```(?:\w+)?\s*(.*?)```"
        matches = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if not matches:
            return ""
        # Prefer the last bracketed list block.
        candidates = []
        for m in matches:
            s = m.strip()
            if s.startswith("[") and s.endswith("]") and s != "[]":
                candidates.append(s)
        return candidates[-1].strip() if candidates else matches[-1].strip()

    def _parse_query_contexts(self, planner_response: str) -> List[tuple]:
        """
        Parse a planner LLM response into a list of (query, context) tuples.
        """
        list_literal = self._extract_list_literal_from_codeblock(planner_response)
        if not list_literal:
            return []
        try:
            import ast
            parsed = ast.literal_eval(list_literal)
        except Exception:
            logger.error(f"InterleavedWebSearchAgent: failed parsing planner output. Raw: {planner_response[:500]}")
            return []
        if not isinstance(parsed, list):
            return []
        out = []
        for item in parsed:
            if not (isinstance(item, tuple) and len(item) == 2):
                continue
            q, c = item
            if not (isinstance(q, str) and isinstance(c, str)):
                continue
            q = q.strip()
            c = c.strip()
            if not q:
                continue
            out.append((q, c))
        return out

    def _format_query_contexts_codeblock(self, query_contexts: List[tuple]) -> str:
        """
        Format planned (query, context) tuples as a readable markdown ```python code block.

        Requirements:
        - Triple ticks
        - Newline before and after the block
        - Newline immediately after ```python
        """
        if not query_contexts:
            return "\n\n```python\n[]\n```\n\n"
        lines = ["["]
        for q, c in query_contexts:
            lines.append(f"  ({q!r}, {c!r}),")
        lines.append("]")
        body = "\n".join(lines)
        return f"\n\n```python\n{body}\n```\n\n"

    def _planner_indicates_done(self, query_contexts: List[tuple], planner_response: str = "") -> bool:
        """
        Decide whether the planner signaled completion.

        We primarily rely on the explicit sentinel tuple, but also allow a raw sentinel substring
        in case the LLM formatting deviates slightly.
        """
        if planner_response and self.planner_done_sentinel in planner_response:
            return True
        for q, _c in query_contexts or []:
            if str(q).strip() == self.planner_done_sentinel:
                return True
        return False

    def _make_headless_source_agent(self, source: str):
        """
        Factory for creating a headless search agent by source name.

        Returns:
            Agent instance.
        """
        sub_detail = 1
        if source == "web":
            return WebSearchWithAgent(self.keys, OPENAI_CHEAP_LLM, sub_detail, self.timeout, headless=True, no_intermediate_llm=True)
        if source == "perplexity":
            return PerplexitySearchAgent(self.keys, OPENAI_CHEAP_LLM, sub_detail, self.timeout, self.num_queries_per_step, headless=True, no_intermediate_llm=True)
        if source == "jina":
            return JinaSearchAgent(self.keys, OPENAI_CHEAP_LLM, sub_detail, self.timeout, self.num_queries_per_step, headless=True, no_intermediate_llm=True)
        raise ValueError(f"Unknown source '{source}'. Expected one of: web, perplexity, jina.")

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=True):
        """
        Stream an answer that is refined over multiple search/answer interleaves.

        Notes:
        - `stream` controls streaming of the *answer* model; search sources run headless and are collected per step.
        - If `self.headless` is False, wraps the whole output inside <web_answer> tags.
        """
        planner_llm = CallLLm(self.keys, model_name=self.planner_model_name)
        answer_llm = CallLLm(self.keys, model_name=self.model_name)

        answer_so_far = ""
        # stable_prefix + rolling_history is append-only (cache-friendly).
        stable_prefix = self.answer_prompt_prefix.format(text=text)
        rolling_history = ""

        if not self.headless:
            yield {"text": "<web_answer>", "status": "InterleavedWebSearchAgent"}

        for step_idx in range(self.interleave_steps):
            step_num = step_idx + 1
            # 1) Plan follow-up queries
            planner_prompt = self.query_planner_prompt.format(text=text, answer_so_far=answer_so_far)
            planner_response = planner_llm(planner_prompt, images=[], temperature=0.2, stream=False, max_tokens=None, system=system)
            query_contexts = self._parse_query_contexts(planner_response)

            # Early stop via planner sentinel:
            # - If we already have some answer, stop immediately (no more searching/answering needed).
            # - If we have no answer yet, fall through and allow the answer LLM to produce the initial answer
            #   (it may itself emit the answer sentinel to end after the first step).
            if (
                step_num >= self.min_interleave_steps
                and self._planner_indicates_done(query_contexts, planner_response)
                and answer_so_far.strip()
            ):
                logger.info("InterleavedWebSearchAgent: planner indicated DONE; stopping interleaving early.")
                break

            # Fallback: if planner fails, do not hard-fail the whole answer; proceed without evidence.
            if not query_contexts:
                logger.error("InterleavedWebSearchAgent: planner returned no valid queries; proceeding without new evidence.")

            query_block = ""
            if query_contexts:
                # Keep the injected block compact (the downstream agents parse the list literal).
                query_block = "```python\n" + str(query_contexts) + "\n```"

            # Always yield planned queries as a plain triple-tick python code block for observability.
            # (This stays stable across the step and is useful for debugging/quality evaluation.)
            if query_contexts:
                yield {"text": self._format_query_contexts_codeblock(query_contexts), "status": "InterleavedWebSearchAgent"}
            elif self.show_intermediate_results:
                yield {"text": self._format_query_contexts_codeblock([]), "status": "InterleavedWebSearchAgent"}

            # 2) Run configured sources concurrently, headless, using the planned query-context tuples
            evidence_chunks = []
            if query_contexts:
                search_text = f"{text}\n\n{query_block}\n"
                from concurrent.futures import wait, FIRST_COMPLETED

                futures = []
                for source in self.sources:
                    try:
                        agent = self._make_headless_source_agent(source)
                    except Exception as e:
                        logger.error(f"InterleavedWebSearchAgent: failed creating source agent '{source}': {e}")
                        continue
                    futures.append(
                        (source, get_async_future(extract_answer, agent, search_text, images, temperature, stream, max_tokens, system, web_search))
                    )

                # Collect results and short-circuit once enough sources succeeded.
                futures_map = {fut: source for source, fut in futures}
                pending = set(futures_map.keys())
                successes = 0
                # Don't require more successes than sources we actually launched.
                target_successes = min(self.min_successful_sources, len(pending)) if pending else 0

                start_wait = time.time()
                total_timeout = self.timeout + 30
                while pending and (time.time() - start_wait) < total_timeout and successes < target_successes:
                    done, pending = wait(pending, timeout=2, return_when=FIRST_COMPLETED)
                    for fut in done:
                        source = futures_map.get(fut, "unknown")
                        try:
                            short_answer, _full = fut.result(timeout=1)
                            if str(short_answer).strip():
                                evidence_chunks.append(f"### Source: {source}\n{short_answer}")
                                successes += 1
                        except Exception as e:
                            logger.error(f"InterleavedWebSearchAgent: source '{source}' failed: {e}")

                # Optionally pick up any done futures left (without waiting further), so we don't waste already-computed work.
                if pending:
                    done_now, pending = wait(pending, timeout=0, return_when=FIRST_COMPLETED)
                    for fut in done_now:
                        source = futures_map.get(fut, "unknown")
                        try:
                            short_answer, _full = fut.result(timeout=0)
                            if str(short_answer).strip():
                                evidence_chunks.append(f"### Source: {source}\n{short_answer}")
                        except Exception:
                            pass

            evidence = "\n\n".join(evidence_chunks).strip()

            if self.show_intermediate_results and evidence:
                yield {
                    "text": convert_stream_to_iterable(
                        collapsible_wrapper(
                            evidence,
                            header=f"Interleave step {step_idx + 1}: evidence",
                            show_initially=False,
                            add_close_button=True,
                        )
                    )
                    + "\n\n",
                    "status": "InterleavedWebSearchAgent",
                }

            # 3) Append-only prompt assembly (cache-friendly)
            # We append a single block per step; previous blocks stay unchanged.
            evidence_for_prompt = evidence.strip() if evidence.strip() else "_No new evidence for this step._"
            step_block_prefix = self.answer_step_block_template.format(step_idx=step_num, evidence=evidence_for_prompt)

            # Truncate rolling history if needed (keep the tail). We keep the stable_prefix intact.
            if self.max_sources_chars and len(rolling_history) > self.max_sources_chars:
                rolling_history = rolling_history[-self.max_sources_chars :]

            step_prompt = stable_prefix + rolling_history + step_block_prefix

            # 4) Stream continuation and update answer_so_far + rolling_history
            continuation = ""
            # We filter the answer sentinel so it never appears to the user. Because streaming chunks may split the
            # sentinel across boundaries, we keep a small lookbehind buffer and delay output slightly.
            done_detected = False
            carry = ""
            response_stream = answer_llm(step_prompt, images=images, temperature=temperature, stream=True, max_tokens=max_tokens, system=system)
            for chunk in response_stream:
                # `CallLLm` may yield strings or dict-like; convert defensively.
                s = str(chunk)
                continuation += s

                combined = carry + s
                sentinel_idx = combined.find(self.answer_done_sentinel)
                if sentinel_idx != -1:
                    # Emit text before sentinel, drop sentinel and everything after it.
                    before = combined[:sentinel_idx]
                    if before:
                        yield {"text": before, "status": "InterleavedWebSearchAgent"}
                    done_detected = True
                    carry = ""
                    break

                # No sentinel found. Emit everything except the last N chars (keep for boundary detection).
                keep = max(len(self.answer_done_sentinel) - 1, 0)
                if keep == 0:
                    yield {"text": combined, "status": "InterleavedWebSearchAgent"}
                    carry = ""
                else:
                    if len(combined) > keep:
                        emit = combined[:-keep]
                        if emit:
                            yield {"text": emit, "status": "InterleavedWebSearchAgent"}
                        carry = combined[-keep:]
                    else:
                        carry = combined

            # Flush remaining carry if we didn't detect sentinel.
            if carry and not done_detected:
                yield {"text": carry, "status": "InterleavedWebSearchAgent"}
                carry = ""

            # Append a separator between steps to avoid accidental sentence smashing.
            # If sentinel was detected, strip it from continuation so it doesn't enter state/history.
            if self.answer_done_sentinel in continuation:
                continuation = continuation.split(self.answer_done_sentinel, 1)[0]

            if continuation and not continuation.endswith("\n"):
                continuation += "\n"

            answer_so_far = (answer_so_far + continuation).strip() + "\n"
            rolling_history = rolling_history + step_block_prefix + continuation

            # Early stop via answer sentinel.
            if done_detected and step_num >= self.min_interleave_steps:
                logger.info("InterleavedWebSearchAgent: answer model emitted DONE sentinel; stopping interleaving early.")
                break

        if not self.headless:
            yield {"text": "</web_answer>", "status": "InterleavedWebSearchAgent"}


class PromptWorkflowAgent(Agent):
    """
    Workflow-style agent that runs a sequence of prompts over a user query.

    ## Purpose and behavior
    This agent executes a multi-step prompt workflow where each step produces an output
    that becomes context for subsequent steps. The workflow is designed to:
    - stream outputs step-by-step for UI rendering
    - always include the user query and the most recent prior output
    - include older steps only if the configured context budget allows

    ## Input modes
    The agent supports two primary input modes:
    1) Explicit prompts + user query:
       - `user_query` is provided
       - `workflow_prompts` is a list of prompt strings or a single string separated by
         double newlines ("\n\n")
    2) Single combined string:
       - If `workflow_prompts` is not provided and `text` contains double newlines,
         the first chunk is treated as the user query and remaining chunks are prompts.
       - If no prompts are found, a default prompt is used.

    ## Step execution and context management
    For step N:
    - The LLM receives:
      - the step prompt
      - a `<workflow_context>` section that includes:
        - the user query (trimmed if needed)
        - the most recent step output (always included)
        - older steps only if they fit within `max_context_chars`
    - The step response is streamed immediately as it is generated.

    Context trimming rules:
    - The total context is bounded by `max_context_chars`.
    - Each prior step output is individually capped by `max_step_output_chars`.
    - If the context budget is tight, the user query is trimmed while preserving the
      most recent output to maintain workflow continuity.

    ## Parameters
    - keys: API keys container.
    - model_name: LLM model name for all steps.
    - max_context_chars: Maximum total chars included in the context window per step.
    - max_step_output_chars: Maximum chars of any prior step output to include.
    - include_prompt_history: Whether to include prior prompts in the context.

    ## Outputs
    - Streams step-by-step responses as dicts with "text" and "status".
    """

    def __init__(
        self,
        keys,
        model_name,
        max_context_chars: int = 120_000,
        max_step_output_chars: int = 24_000,
        include_prompt_history: bool = True,
    ):
        super().__init__(keys)
        self.model_name = model_name
        self.max_context_chars = max(5_000, int(max_context_chars))
        self.max_step_output_chars = max(1_000, int(max_step_output_chars))
        self.include_prompt_history = include_prompt_history

    def _split_prompts(self, prompt_input):
        """
        Split a prompt input into a list of prompts.

        Inputs:
            prompt_input: list of strings or a single string with double-newline separators.

        Outputs:
            A list of non-empty prompt strings.
        """
        if prompt_input is None:
            return []
        if isinstance(prompt_input, list):
            return [p.strip() for p in prompt_input if str(p).strip()]
        if isinstance(prompt_input, str):
            parts = [p.strip() for p in prompt_input.split("\n\n")]
            return [p for p in parts if p]
        return []

    def _normalize_inputs(self, text, workflow_prompts, user_query):
        """
        Normalize user query and workflow prompts based on provided arguments.

        Inputs:
            text: the primary call argument (string or list).
            workflow_prompts: optional list or string of prompts.
            user_query: optional explicit user query.

        Outputs:
            (user_query: str, prompts: List[str])
        """
        prompts = self._split_prompts(workflow_prompts)
        resolved_user_query = user_query

        # If user_query not explicitly provided, infer from text.
        if resolved_user_query is None:
            if isinstance(text, list):
                # If text is a list, treat first item as user query if prompts not provided.
                if not prompts and text:
                    resolved_user_query = str(text[0]).strip()
                    prompts = [str(p).strip() for p in text[1:] if str(p).strip()]
                else:
                    resolved_user_query = " ".join([str(t).strip() for t in text if str(t).strip()])
            elif isinstance(text, str):
                # If prompts not provided and text contains double newlines, split:
                # first chunk is user query, remaining are prompts.
                if not prompts and "\n\n" in text:
                    parts = [p.strip() for p in text.split("\n\n")]
                    parts = [p for p in parts if p]
                    if parts:
                        resolved_user_query = parts[0]
                        prompts = parts[1:]
                    else:
                        resolved_user_query = text.strip()
                else:
                    resolved_user_query = text.strip()
            else:
                resolved_user_query = str(text).strip() if text is not None else ""

        if resolved_user_query is None:
            resolved_user_query = ""

        # Fallback: if no prompts were provided, use a single minimal prompt.
        if not prompts:
            prompts = ["Answer the user query clearly and completely."]

        return resolved_user_query, prompts

    def _trim_text(self, text: str, max_chars: int) -> str:
        """
        Trim text to a max char limit, keeping the tail for recency.

        Inputs:
            text: raw text
            max_chars: character limit

        Outputs:
            Trimmed text (possibly unchanged).
        """
        if not text:
            return ""
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return "[...truncated...]\n" + text[-max_chars:]

    def _build_step_context(self, user_query, prompts, step_outputs):
        """
        Build the context passed to each step.

        Inputs:
            user_query: original user query
            prompts: list of prompts used so far
            step_outputs: list of outputs from prior steps

        Outputs:
            A context string bounded by self.max_context_chars, always including the
            user query and the most recent previous step output.
        """
        if not user_query:
            user_query = ""
        if not step_outputs:
            return self._trim_text(f"User query:\n{user_query}", self.max_context_chars)

        def build_block(idx, output_limit):
            prompt_text = prompts[idx] if idx < len(prompts) else ""
            prompt_trimmed = self._trim_text(prompt_text, self.max_step_output_chars)
            output_trimmed = self._trim_text(step_outputs[idx], output_limit) if output_limit > 0 else ""
            if self.include_prompt_history:
                return f"Step {idx + 1} prompt:\n{prompt_trimmed}\n\nStep {idx + 1} output:\n{output_trimmed}"
            return f"Step {idx + 1} output:\n{output_trimmed}"

        header = "\n\nPrevious steps:\n"
        last_idx = len(step_outputs) - 1

        # Reserve space to always include the user query + most recent output.
        min_output_chars = min(200, self.max_step_output_chars)
        prompt_label = f"Step {last_idx + 1} prompt:\n" if self.include_prompt_history else ""
        output_label = f"\n\nStep {last_idx + 1} output:\n" if self.include_prompt_history else f"Step {last_idx + 1} output:\n"

        fixed_len = len("User query:\n") + len(header) + len(prompt_label) + len(output_label) + min_output_chars
        max_query_chars = max(0, self.max_context_chars - fixed_len)
        user_query_trimmed = self._trim_text(user_query, max_query_chars)
        base = f"User query:\n{user_query_trimmed}"

        available = max(0, self.max_context_chars - len(base) - len(header) - len(prompt_label) - len(output_label))
        if self.include_prompt_history:
            prompt_budget = min(self.max_step_output_chars, max(0, available - min_output_chars))
            output_budget = min(self.max_step_output_chars, max(0, available - prompt_budget))
        else:
            prompt_budget = 0
            output_budget = min(self.max_step_output_chars, available)

        # Build the most recent block with guaranteed inclusion.
        if self.include_prompt_history and prompt_budget < self.max_step_output_chars:
            prompt_text = prompts[last_idx] if last_idx < len(prompts) else ""
            prompt_trimmed = self._trim_text(prompt_text, prompt_budget)
            last_block_prefix = f"Step {last_idx + 1} prompt:\n{prompt_trimmed}\n\nStep {last_idx + 1} output:\n"
            last_output = self._trim_text(step_outputs[last_idx], output_budget) if output_budget > 0 else ""
            last_block = last_block_prefix + last_output
        else:
            last_block = build_block(last_idx, output_budget)

        history = last_block
        context = base + header + history

        # Add older steps only if they fit, preferring recency.
        for idx in range(last_idx - 1, -1, -1):
            block = build_block(idx, self.max_step_output_chars)
            candidate_history = block + "\n\n" + history
            candidate_context = base + header + candidate_history
            if len(candidate_context) <= self.max_context_chars:
                history = candidate_history
                context = candidate_context
            else:
                continue

        return context

    def __call__(
        self,
        text,
        images=[],
        temperature=0.7,
        stream=False,
        max_tokens=None,
        system=None,
        web_search=False,
        workflow_prompts=None,
        user_query=None,
    ):
        """
        Execute a prompt workflow over the user query.

        Supported input shapes:
            1) Explicit user query + prompts:
               - user_query: a user question or task string
               - workflow_prompts: list[str] or a single string separated by "\n\n"
               - text: may be empty or any placeholder (ignored for parsing in this mode)

            2) Combined string mode:
               - workflow_prompts is None
               - text is a string that contains "\n\n"
               - first chunk => user_query
               - remaining chunks => workflow_prompts

            3) Fallback single prompt mode:
               - if prompts cannot be resolved from workflow_prompts or text,
                 a default prompt is used to answer the query directly.

        Inputs:
            text:
                User query or combined query+prompts string (see supported modes).
            workflow_prompts:
                List[str] or a single string split by "\n\n". Optional.
            user_query:
                Explicit user query. Optional; overrides inference from text.
            images, temperature, stream, max_tokens, system:
                Standard LLM call parameters forwarded to CallLLm.

        Outputs:
            Streams dict chunks with:
                - "text": partial output for the current step
                - "status": "PromptWorkflowAgent"
        """
        llm = CallLLm(self.keys, model_name=self.model_name)
        resolved_query, prompts = self._normalize_inputs(text, workflow_prompts, user_query)

        step_outputs = []

        for idx, prompt in enumerate(prompts):
            step_num = idx + 1
            context = self._build_step_context(resolved_query, prompts, step_outputs)
            step_prompt = (
                f"{prompt}\n\n"
                f"<workflow_context>\n{context}\n</workflow_context>\n\n"
                "Write the next step output based on the prompt and context."
            )

            yield {"text": f"\n\n---\n### Workflow step {step_num}/{len(prompts)}\n\n", "status": "PromptWorkflowAgent"}
            yield {"text": f"Prompt:\n{prompt}\n\n", "status": "PromptWorkflowAgent"}

            step_output = ""
            if stream:
                response_stream = llm(step_prompt, images=images, temperature=temperature, stream=True, max_tokens=max_tokens, system=system)
                for chunk in response_stream:
                    chunk_text = str(chunk)
                    step_output += chunk_text
                    yield {"text": chunk_text, "status": "PromptWorkflowAgent"}
            else:
                step_output = llm(step_prompt, images=images, temperature=temperature, stream=False, max_tokens=max_tokens, system=system)
                yield {"text": str(step_output), "status": "PromptWorkflowAgent"}

            step_outputs.append(str(step_output))
            yield {"text": "\n\n", "status": "PromptWorkflowAgent"}


class JinaDeepResearchAgent(Agent):
    """Agent that uses Jina's Deep Research API for comprehensive search and analysis"""
    
    def __init__(self, keys, model_name, detail_level=1, timeout=180, num_queries=1):
        super().__init__(keys)
        self.model_name = model_name
        self.detail_level = detail_level
        self.timeout = timeout
        self.num_queries = num_queries
        
        # Use the same API key as JinaSearchAgent
        self.jina_api_key = os.environ.get("jinaAIKey", "") or keys.get("jinaAIKey", "")
        assert self.jina_api_key, "No Jina API key found. Please set jinaAIKey environment variable."
        
        # Reasoning effort based on detail level
        self.reasoning_effort = "low" if detail_level <= 2 else "medium" if detail_level == 3 else "high"
        num_queries_actual = num_queries + 1 
        
        # LLM for generating search queries
        self.query_generation_prompt = f"""Given the following text, generate {num_queries_actual} focused and specific search queries that would help answer the user's question comprehensively.

Text: {{text}}

Generate exactly {num_queries_actual} search queries that are:
1. The first query is a single detailed query that overall represents the user's question and web search intention and what to search for. If user's direct query itself is also short and clear then append it to the end of this first query so we keep what user asked verbatim as well.
2. The second query is a summary query that summarizes the user's question in full details along with brief information about user's goal and purpose and previous conversation.
3. The remaining queries are generated based on the below guidelines.
    a. Queries after the first two should be Specific and focused on different aspects of the question
    b. Queries after the first two should likely to return complementary information
    c. Queries after the first two should be formulated to get the most relevant results

Note: Generate a first query as a generic single query that overall represents the user's question. Then the remaining queries are generated based on the above guidelines.

Format your response as a Python list:
```python
["first query that overall represents the user's question", "summary query that summarizes the user's question in full details along with brief information about user's goal and purpose and previous conversation", "query3", ...]
```
"""

    def extract_queries(self, code_string):
        """Extract queries from LLM response"""
        regex = r"```(?:\w+)?\s*(.*?)```"
        matches = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        
        if not matches:
            return None
        
        code_to_execute = matches[0].strip()
        
        try:
            import ast
            queries = ast.literal_eval(code_to_execute)
            queries = [queries[0]] + queries[2:] # "\n\n" + queries[1]
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return queries[:self.num_queries]  # Limit to num_queries
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing queries: {e}")
        
        return None
    
    def call_jina_deep_research(self, messages, stream=True):
        """Call Jina Deep Research API with the given messages"""
        import requests
        import json
        
        url = "https://deepsearch.jina.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.jina_api_key}"
        }
        
        data = {
            "model": "jina-deepsearch-v1",
            "messages": messages,
            "stream": stream,
            "reasoning_effort": self.reasoning_effort
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, stream=stream)
            response.raise_for_status()
            
            if stream:
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith("data: "):
                            line_str = line_str[6:]  # Remove "data: " prefix
                        
                        if line_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(line_str)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                content_type = delta.get("type", "")
                                
                                yield {
                                    "content": content,
                                    "type": content_type,
                                    "role": delta.get("role", "")
                                }
                        except json.JSONDecodeError:
                            continue
            else:
                return response.json()
                
        except Exception as e:
            logger.error(f"Error calling Jina Deep Research API: {e}, \n\n{traceback.format_exc()}")
            yield {"content": f"Error: {str(e)}", "type": "error", "role": "assistant"}
    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=True):
        """Execute deep research for the given query"""
        
        # Generate search queries if num_queries > 1
        queries = []
        
        # Use LLM to generate multiple queries
        llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])
        query_prompt = self.query_generation_prompt.format(text=text, num_queries=self.num_queries)
        
        yield {"text": "Generating search queries...\n", "status": "Generating queries"}
        
        query_response = llm(query_prompt, temperature=0.7, stream=False)
        queries = self.extract_queries(query_response)
        yield {"text": "<details open>\n<summary><strong>Queries</strong></summary>\n\n", "status": "Researching query"}
        
        if queries:
            yield {"text": f"Generated {len(queries)} search queries:\n", "status": "Generated queries"}
            for i, q in enumerate(queries, 1):
                yield {"text": f"{i}. {q}\n", "status": "Generated queries"}
            yield {"text": "\n", "status": "Generated queries"}
        else:
            # Fallback to single query
            queries = [text]
        yield {"text": "</details>\n\n", "status": "Researching query"}        
        # Perform deep research for each query
        all_results = []
        
        for idx, query in enumerate(queries, 1):
            yield {"text": f"\n <b>Deep Research Query {idx}/{len(queries)}: {query}</b> \n\n", "status": f"Researching query {idx}"}
            
            # Prepare messages for Jina Deep Research API
            messages = [
                {
                    "role": "user",
                    "content": system if system else "You are a helpful research and web search assistant that provides comprehensive, well-researched answers and knowledge base compilations with citations. Focus on writing detailed and comprehensive answers with mutliple citations and research and references. Expend your energy in writing the actual answer itself with due research."
                },
                {
                    "role": "assistant", 
                    "content": "Let me perform an extensive search and provide you that information. I will perform a broad and deep search. This user has requested a web search query and I will not overthink. I will perform search and retrieval of information and then compile and present it. I will not think. Put all the references with web url links (http or https links) at the end in markdown links format as bullet points."
                },
                {
                    "role": "user",
                    "content": query
                }
            ]
            
            # Stream response from Jina Deep Research
            thinking_mode = False
            current_result = ""
            
            yield {"text": "<details open>\n<summary><strong>Research Process</strong></summary>\n\n", "status": f"Researching query {idx}"}
            
            try:
                for chunk in self.call_jina_deep_research(messages, stream=True):
                    content = chunk.get("content", "")
                    content_type = chunk.get("type", "")

                    if content_type != "think":
                        print(len(content))
                    
                    # Handle thinking vs regular content
                    if content_type == "think" and "<think>" in content and not thinking_mode:
                        thinking_mode = True
                        yield {"text": "<details open>\n<summary><strong>Thinking Process</strong></summary>\n\n", "status": f"Researching query {idx}"}
                        yield {"text": "**Analyzing sources and reasoning...**\n\n", "status": f"Researching query {idx}"}
                    elif content == "</think>" or "</think>" in content:
                        thinking_mode = False
                        yield {"text": "\n</think>\n\n", "status": f"Researching query {idx}"}
                        yield {"text": "\n</details>\n\n", "status": f"Researching query {idx}"}
                        yield {"text": "\n---\n\n", "status": f"Researching query {idx}"}
                    elif thinking_mode:
                        # Show thinking process in code block
                        yield {"text": content, "status": f"Researching query {idx}"}
                    elif content_type != "think":
                        yield {"text": content, "status": f"Researching query {idx}"}
                        current_result += content
                    else:
                        # Regular content
                        current_result += content
                        yield {"text": content, "status": f"Getting Results {idx}"}
            except Exception as e:
                logger.error(f"Error calling Jina Deep Research API: {e}, \n\n{traceback.format_exc()}")
                yield {"text": f"Error: {str(e)}", "status": f"Researching query {idx}"}
            
            yield {"text": "\n</details>\n\n", "status": f"Researching query {idx}"}
            
            all_results.append({
                "query": query,
                "result": current_result
            })
            
            if idx < len(queries):
                yield {"text": "\n---\n", "status": f"Completed query {idx}"}
        
        # If multiple queries, combine results
        if len(queries) > 1:
            yield {"text": "\n\n**Synthesizing Results**\n\n", "status": "Synthesizing"}
            
            # Combine all results using LLM
            llm = CallLLm(self.keys, model_name=self.model_name)
            
            # Prepare results for combination
            results_text = ""
            for res in all_results:
                results_text += f"Query: {res['query']}\n\nResult:\n{res['result']}\n\n---\n\n"
            
            combine_prompt = f"""You are tasked with synthesizing multiple deep research results into a comprehensive response.

User's original question:
{text}

Deep research results from multiple queries:
{results_text}

Please provide a comprehensive, well-structured response that:
1. Integrates information from all search results
2. Maintains all important citations and references
3. Presents the information in a logical flow
4. Avoids repetition while ensuring completeness
5. Clearly addresses the user's original question

Your synthesized response:"""
            
            yield {"text": "<web_answer>", "status": "Synthesizing"}
            
            combined_response = llm(combine_prompt, temperature=temperature, stream=True, max_tokens=max_tokens)
            
            for chunk in combined_response:
                yield {"text": chunk, "status": "Synthesizing"}
            
            yield {"text": "</web_answer>", "status": "Complete"}
        else:
            # Single query result already streamed
            yield {"text": "\n\n**Research completed.**", "status": "Complete"}

    
    