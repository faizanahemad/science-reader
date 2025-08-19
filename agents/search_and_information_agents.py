import random
import traceback
from typing import Union, List
import uuid
from common import collapsible_wrapper
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
        get_async_future, sleep_and_get_future_result, convert_stream_to_iterable, EXPENSIVE_LLM
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



class WebSearchWithAgent(Agent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=False):
        super().__init__(keys)
        self.gscholar = gscholar
        self.model_name = model_name
        self.detail_level = detail_level
        self.concurrent_searches = True
        self.timeout = timeout
        self.no_intermediate_llm = no_intermediate_llm
        self.post_process_answer_needed = False
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

        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1', 'detailed context1 including conversational context on what user is looking for'), 
    ('query2', 'detailed context2 including conversational context on what user is looking for'), 
    ('query3', 'detailed context3 including conversational context on what user is looking for'), 
    ...
]
```

Text: {{text}}

Generate up to 3 highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
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
                futures = []
                for query, context in text_queries_contexts:
                    future = get_async_future(simple_web_search_with_llm, self.keys, text + "\n\n" + context, [query], gscholar=self.gscholar, provide_detailed_answers=self.detail_level, no_llm=len(text_queries_contexts) <= 3 or self.no_intermediate_llm, timeout=self.timeout * len(text_queries_contexts))
                    futures.append(future)

                web_search_results = []
                for future in futures:
                    result = sleep_and_get_future_result(future)
                    web_search_results.append(f"<b>{query}</b></br>" + "\n\n" + context + "\n\n" + result)
            else:
                web_search_results = []
                for query, context in text_queries_contexts:
                    result = simple_web_search_with_llm(self.keys, text + "\n\n" + context, [query], gscholar=self.gscholar, provide_detailed_answers=self.detail_level, no_llm=len(text_queries_contexts) <= 3 or self.no_intermediate_llm, timeout=self.timeout)
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
        
        
        yield {"text": '\n\n', "status": "Completed web search with agent"}
        combined_response = llm(self.combiner_prompt.format(web_search_results=web_search_results, text=text), images=images, temperature=temperature, stream=True, max_tokens=max_tokens, system=system)
        yield {"text": '<web_answer>', "status": "Completed web search with agent"}
        for text in combined_response:
            yield {"text": text, "status": "Completed web search with agent"}
            answer += text
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
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=5):
        super().__init__(keys, model_name, detail_level, timeout)
        self.num_queries = num_queries
        self.perplexity_models = [
            "perplexity/llama-3.1-sonar-small-128k-online",
            "openai/gpt-4o-mini-search-preview",
            "perplexity/sonar-pro",
            "perplexity/sonar",
            # "perplexity/llama-3.1-sonar-large-128k-online"
        ]
        
        if detail_level >= 3:
            self.perplexity_models.append("perplexity/llama-3.1-sonar-large-128k-online")
            # self.perplexity_models.append("perplexity/sonar-pro")
            self.perplexity_models.append("perplexity/sonar-reasoning")
            self.perplexity_models.append("perplexity/sonar-reasoning-pro")
            self.perplexity_models.append("openai/gpt-4o-search-preview")
        
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
                        "Context: " + context + "\n\nQuery: " + query + "\n" + self.get_references + ("\n\n" + f"Get most recent information and data for the query for year = {year}. If this is a research or scientific query or news query then append current year = {year} and previous year = {year - 1} to your search queries alternatively." if "gpt-4o" in model else ""),
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
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=5, ):
        super().__init__(keys, model_name, detail_level, timeout, num_queries)
        self.jina_api_key = os.environ.get("jinaAIKey", "") or keys.get("jinaAIKey", "")
        assert self.jina_api_key, "No Jina API key found. Please set JINA_API_KEY environment variable."
        self.num_results = 20 if detail_level >= 3 else 10


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
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching search results from Jina: {e}, \n\n{traceback.format_exc()}")
            return {"data": []}

    def fetch_jina_content(self, url: str):
        """Fetch content from a URL using Jina reader API"""
        import requests
        
        reader_url = f"https://r.jina.ai/{url}"
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.jina_api_key}"
        }
        
        try:
            response = requests.get(reader_url, headers=headers)
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
        if len(content) > 5000:
            llm = CallLLm(self.keys, model_name=CHEAP_LONG_CONTEXT_LLM[0])
            content = llm(f"User's query: {query}\n\nUser's context: {context}\n\nUser's and assistant's text: {user_text}\n\nPlease summarize the following content to 5000 characters to extract only the most relevant information as per the user's query: {content}", temperature=0.7, stream=False)
        
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
            
            # Collect and format results
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
        for idx, result in enumerate(processed_results[:num_results], 1):  # Limit to top 10 for readability
            formatted_result = (
                f"### {idx}. [{result['title']}]({result['url']})\n"
                f"**Date**: {result.get('date', 'N/A')}\n"
                f"**Description**: {result.get('description', 'N/A')}\n"
            )
            
            # Add content if available
            if result.get('content'):
                content_preview = result['content'][:5000] + "..." if len(result['content']) > 5000 else result['content']
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
        

class MultiSourceSearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=3):
        self.keys = keys
        self.model_name = model_name
        self.detail_level = detail_level
        self.timeout = timeout
        self.num_queries = num_queries

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

    def extract_answer(self, agent, text, images, temperature, stream, max_tokens, system, web_search):
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
    

    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        web_search_agent = WebSearchWithAgent(self.keys, VERY_CHEAP_LLM[0], max(self.detail_level - 1, 1), self.timeout)
        perplexity_search_agent = PerplexitySearchAgent(self.keys, VERY_CHEAP_LLM[0], max(self.detail_level - 1, 1), self.timeout, self.num_queries)
        jina_search_agent = JinaSearchAgent(self.keys, VERY_CHEAP_LLM[0], max(self.detail_level - 1, 1), self.timeout, self.num_queries)
        
        web_search_results = get_async_future(self.extract_answer, web_search_agent.__call__, text, images, temperature, stream, max_tokens, system, web_search)
        perplexity_results = get_async_future(self.extract_answer, perplexity_search_agent.__call__, text, images, temperature, stream, max_tokens, system, web_search)
        jina_results = get_async_future(self.extract_answer, jina_search_agent.__call__, text, images, temperature, stream, max_tokens, system, web_search)
        llm = CallLLm(self.keys, model_name=self.model_name)
        
        web_search_results_not_yielded = True
        perplexity_results_not_yielded = True
        jina_results_not_yielded = True
        web_search_full_answer = ""
        perplexity_full_answer = ""
        jina_full_answer = ""
        web_search_results_short = ""
        perplexity_results_short = ""
        jina_results_short = ""
        st_time = time.time()
        done_count = 0

        
        try:
            perplexity_results_short, perplexity_full_answer = sleep_and_get_future_result(perplexity_results, timeout=120 if self.detail_level >= 3 else 90)
            done_count += 1
        except TimeoutError:
            logger.error("MultiSourceSearchAgent: Perplexity search timed out after 3 minutes")
            done_count += 1
        try:
            jina_results_short, jina_full_answer = sleep_and_get_future_result(jina_results, timeout=90 if self.detail_level >= 3 else 45)
            done_count += 1
        except TimeoutError:
            logger.error("MultiSourceSearchAgent: Jina search timed out after 3 minutes")
            done_count += 1
        try:
            web_search_results_short, web_search_full_answer = sleep_and_get_future_result(web_search_results, timeout=90 if self.detail_level >= 3 else 45)
            done_count += 1
        except TimeoutError:
            logger.error("MultiSourceSearchAgent: Web search timed out after 3 minutes")
            done_count += 1

        if done_count == 0:
            yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
            yield {"text": "MultiSourceSearchAgent: Time out after 4 minutes", "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
            yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}
            return
        elif done_count == 1:
            yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
            yield {"text": web_search_results_short + "\n\n" + perplexity_results_short + "\n\n" + jina_results_short, "status": "MultiSourceSearchAgent"}
            yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
            yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}
            return
        
        web_search_results_short = convert_stream_to_iterable(collapsible_wrapper(web_search_results_short, header="Web Search Results", show_initially=False, add_close_button=True))
        yield {"text": web_search_results_short, "status": "MultiSourceSearchAgent"}
        yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}

        perplexity_results_short = convert_stream_to_iterable(collapsible_wrapper(perplexity_results_short, header="Perplexity Search Results", show_initially=False, add_close_button=True))
        yield {"text": perplexity_results_short, "status": "MultiSourceSearchAgent"}
        yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}

        jina_results_short = convert_stream_to_iterable(collapsible_wrapper(jina_results_short, header="Jina Search Results", show_initially=False, add_close_button=True))
        yield {"text": jina_results_short, "status": "MultiSourceSearchAgent"}
        yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}

        # while any(not future.done() for future in [web_search_results, perplexity_results, jina_results]):
        #     if web_search_results.done() and web_search_results.exception() is None and web_search_results_not_yielded:
        #         web_search_results_short, web_search_full_answer = web_search_results.result()
        #         web_search_results_short = convert_stream_to_iterable(collapsible_wrapper(web_search_results_short, header="Web Search Results", show_initially=False, add_close_button=True))
        #         yield {"text": web_search_results_short, "status": "MultiSourceSearchAgent"}
        #         yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        #         web_search_results_not_yielded = False
        #         done_count += 1
        #     if perplexity_results.done() and perplexity_results.exception() is None and perplexity_results_not_yielded:
        #         perplexity_results_short, perplexity_full_answer = perplexity_results.result()
        #         perplexity_results_short = convert_stream_to_iterable(collapsible_wrapper(perplexity_results_short, header="Perplexity Search Results", show_initially=False, add_close_button=True))
        #         yield {"text": perplexity_results_short, "status": "MultiSourceSearchAgent"}
        #         yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        #         perplexity_results_not_yielded = False
        #         done_count += 1
        #     if jina_results.done() and jina_results.exception() is None and jina_results_not_yielded:
        #         jina_results_short, jina_full_answer = jina_results.result()
        #         jina_results_short = convert_stream_to_iterable(collapsible_wrapper(jina_results_short, header="Jina Search Results", show_initially=False, add_close_button=True))
        #         yield {"text": jina_results_short, "status": "MultiSourceSearchAgent"}
        #         yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        #         jina_results_not_yielded = False
        #         done_count += 1

        #     if web_search_results.exception() is not None:
        #         logger.error(f"Error in web search: {web_search_results.exception()}, \n\n{traceback.format_exc()}")
        #         done_count += 1
        #     if perplexity_results.exception() is not None:
        #         logger.error(f"Error in perplexity search: {perplexity_results.exception()}, \n\n{traceback.format_exc()}")
        #         done_count += 1
        #     if jina_results.exception() is not None:
        #         logger.error(f"Error in jina search: {jina_results.exception()}, \n\n{traceback.format_exc()}")
        #         done_count += 1
            
        #     if done_count >=2 and time.time() - st_time > 180:
        #         logger.error("MultiSourceSearchAgent: Time out after 3 minutes")
        #         break
        #     if time.time() - st_time > 240:
        #         logger.error("MultiSourceSearchAgent: Time out after 4 minutes")
        #         if done_count == 0:
        #             yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
        #             yield {"text": "MultiSourceSearchAgent: Time out after 4 minutes", "status": "MultiSourceSearchAgent"}
        #             yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        #             yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}
        #             return
        #         elif done_count == 1:
        #             yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
        #             yield {"text": web_search_results_short + "\n\n" + perplexity_results_short + "\n\n" + jina_results_short, "status": "MultiSourceSearchAgent"}
        #             yield {"text": "\n\n", "status": "MultiSourceSearchAgent"}
        #             yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}
        #             return
        #     time.sleep(0.5)
        response = llm(self.combiner_prompt.format(user_query=text, web_search_results=web_search_full_answer+"\n\n"+web_search_results_short, perplexity_search_results=perplexity_full_answer+"\n\n"+perplexity_results_short, jina_search_results=jina_full_answer+"\n\n"+jina_results_short), temperature=temperature, stream=True, max_tokens=max_tokens, system=system)

        yield {"text": "<web_answer>", "status": "MultiSourceSearchAgent"}
        answer = ""
        for chunk in response:
            yield {"text": chunk, "status": "MultiSourceSearchAgent"}
            answer += chunk
        yield {"text": "</web_answer>", "status": "MultiSourceSearchAgent"}

    
    