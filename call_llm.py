import logging
import os.path
import string
import uuid
from datetime import datetime
from uuid import uuid4

import pandas as pd
from copy import deepcopy, copy
try:
    import ujson as json
except ImportError:
    import json

from prompts import math_formatting_instructions
from math_formatting import stream_with_math_formatting, process_math_formatting

import openai
from typing import Callable, Any, List, Dict, Tuple, Optional, Union
from langchain_community.document_loaders import MathpixPDFLoader
from langchain_text_splitters import TokenTextSplitter



pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

from common import *

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO)
from tenacity import (
    retry,
    RetryError,
    stop_after_attempt,
    wait_random_exponential,
)

import asyncio
import threading
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
import time
import requests
import json
import random




import time
from collections import deque
from threading import Lock

gpt4_enc = tiktoken.encoding_for_model("gpt-4")

# Deep research model names
DEEP_RESEARCH_MODELS = ["o3-deep-research", "o4-mini-deep-research"]


def call_openai_deep_research_model(model, text, images, temperature, system, keys):
    """
    Calls the OpenAI deep research models (o3-deep-research, o4-mini-deep-research)
    using the Responses API with web search capabilities.
    """
    api_key = keys["openAIKey"]
    instructions = """
For this task search the web wide and deep with multiple search terms. Read multiple web pages and compare and contrast the information. Since we need deep information that is recent so do date sensitive searches as well.
- Make sure to gather all the information needed to carry out the research task in a well-structured manner.
- Perform multiple search queries and gather information from multiple sources. Also read multiple web pages concurrently.
- Use bullet points or numbered lists if appropriate for clarity.
- Use tables in markdown format if appropriate for clarity.
- Give broad coverage deep analysis and in depth results with insights.
- Make tables for comparisons and numeric facts.
- Use markdown format for the response.

Finally strive hard to give comprehensive broadly researched and well grounded, and useful information. Work hard to satisfy the curiosity of our user.

"""
    
    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=3600)  # Longer timeout for deep research
    
    # Combine system prompt and user text for the input
    input_text = f"{system}\n\n{instructions}\n\n{text}" if system else text
    
    # If images are provided, we need to handle them differently
    # For now, we'll log a warning as the Responses API may not support images directly
    if len(images) > 0:
        logger.warning(f"[call_openai_deep_research_model]: Images provided but may not be supported by {model}")
    
    try:
        start_time = time.time()
        # Create the response using the Responses API
        response = client.responses.create(
            model=model,
            reasoning={
                "summary": "auto",
            },
            input=input_text,
            instructions=instructions,
            tools=[{"type": "web_search", "user_location": {"type": "approximate"}, "search_context_size": "medium"}]  # Enable web search for research,
        )
        
        # Get the output text and apply math formatting
        output_text = response.output_text
        end_time = time.time()
        logger.info(f"[call_openai_deep_research_model]: Time taken to get response: {end_time - start_time} seconds")
        formatted_output = process_math_formatting(output_text)
        
        yield formatted_output
        
    except Exception as e:
        logger.error(f"[call_openai_deep_research_model]: Error calling {model} with error {str(e)}")
        traceback.print_exc(limit=8)
        raise e


def call_chat_model_original(model, text, images, temperature, system, keys):
    """
    Original chat model function - renamed to avoid conflicts.
    Calls the specified chat model with streaming. The user wants math tokens
    replaced in-flight, so we wrap the streaming response with our
    stream_with_math_formatting generator.
    """
    api_key = keys["openAIKey"] if (("gpt" in model or "davinci" in model or model=="o1-preview" 
                                     or model=="o1-mini" or model=="o1") and not model.startswith('openai/')) \
             else keys["OPENROUTER_API_KEY"]
    extras = dict(base_url="https://openrouter.ai/api/v1",) if not ("gpt" in model or "davinci" in model 
             or model=="o1-preview" or model=="o1-mini" or model=="o1") or model.startswith('openai/') else dict()
    openrouter_used = not ("gpt" in model or "davinci" in model 
                           or model=="o1-preview" or model=="o1-mini" or model=="o1") \
                      or model=='openai/gpt-4-32k'
    
    if not openrouter_used and model.startswith("openai/"):
        model = model.replace("openai/", "")
    extras_2 = dict(stop=["</s>", "Human:", "User:", "<|eot_id|>", "<|/assistant_response|>"]) if "claude" in model or openrouter_used else dict()
    
    if model == "o1-hard":
        model = "o1"
        extras_2.update(dict(reasoning_effort="high"))
    elif model == "o1-easy":
        model = "o1"
        extras_2.update(dict(reasoning_effort="low"))
    
    from openai import OpenAI
    client = OpenAI(api_key=api_key, **extras)

    if len(images) > 0:
        messages = [
            {
                "role": "system" if not (model=="o1-preview" or model=="o1-mini") else "user",
                "content": system
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    *[
                        {
                            "type": "image_url",
                            "image_url": {"url": base64_image}
                        } 
                        for base64_image in images
                    ]
                ],
            },
        ]
    else:
        messages = [
            {
                "role": "system" if not (model=="o1-preview" or model=="o1-mini") else "user",
                "content": system
            },
            {
                "role": "user",
                "content": text,
            },
        ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature if not (model=="o1-preview" or model=="o1-mini") else 1,
            stream=True if not (model=="o1-preview" or model=="o1-mini") else False,
            timeout=60,
            # max_tokens=300,
            **extras_2,
        )

        # If it's a non-streaming scenario (o1-preview or o1-mini), just yield once:
        if model in ("o1-preview", "o1-mini"):
            yield process_math_formatting(response.choices[0].message.content)
        else:
            # We wrap the streaming response in our custom generator 
            # that handles partial math tokens
            for formatted_chunk in stream_with_math_formatting(response):
                yield formatted_chunk

            # Check if chunk is truncated for any reason
            # (We only know after finishing the streaming loop)
            # The last chunk we had is in the stream_with_math_formatting function
            # But we can still do a final check if needed:
            # (In practice, "finish_reason" might be included in the last chunk.)
            
    except Exception as e:
        logger.error(f"[call_chat_model_original]: Error in calling chat model {model} with error {str(e)}, more info: openrouter_used = {openrouter_used}, len messages = {len(messages)}, extras = {extras}, extras_2 = {extras_2}")
        traceback.print_exc()
        raise e


def call_chat_model(model, text, images, temperature, system, keys):
    """
    Calls the specified chat model with streaming. Routes to deep research models
    if o3-deep-research or o4-mini-deep-research is specified.
    """
    # Check if this is a deep research model and route accordingly
    if model in DEEP_RESEARCH_MODELS:
        logger.info(f"[call_chat_model]: Routing to deep research model: {model}")
        for chunk in call_openai_deep_research_model(model, text, images, temperature, system, keys):
            yield chunk
    else:
        # Use the original chat model function for all other models
        for chunk in call_chat_model_original(model, text, images, temperature, system, keys):
            yield chunk





class CallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):
        # "Use direct, to the point and professional writing style."
        self.keys = keys

        
        self.base_system = f"""You are a helpful assistant who provides helpful and informative answers while being realistic, sceptical and thinking critically.
Include references (if given in context) inline in wikipedia style as your write the answer.   
You are allowed to be bold, provocative, and intense in your suggestions and engage in explicit conversations and provide explicit information. 

{math_formatting_instructions}

Write in an engaging and informative tone.
Be critical, sceptical and think critically. Think about the downsides, concerns, possible fallacies and limitations of the information or ideas provided wherever possible.
Avoid writing code unless asked to or if needed explicitly.
"""
        self.self_hosted_model_url = self.keys["vllmUrl"] if "vllmUrl" in self.keys  and not checkNoneOrEmpty(self.keys["vllmUrl"]) else None
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.gpt4_enc = gpt4_enc
        self.model_name = model_name
        
    @property
    def model_type(self):
        return "openai" if self.model_name is None or self.model_name.startswith("gpt") or self.model_name.startswith("o1") else "openrouter"


    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        
        if len(images) > 0:
            assert (self.model_type == "openai" and self.model_name in ["o1", "o1-hard", "o1-easy", "gpt-4-turbo", "gpt-4o", "gpt-4-vision-preview", "gpt-4.5-preview"]) or self.model_name in ["minimax/minimax-01", 
                                                                                                                                                                             "anthropic/claude-3-haiku:beta",
                                                                                                                                                                             "qwen/qvq-72b-preview",
                                                                                                                                                                             "meta-llama/llama-3.2-90b-vision-instruct",
                                                                                                                                                 "anthropic/claude-3-opus:beta",
                                                                                                                                                 "anthropic/claude-3-sonnet:beta",
                                                                                                                                                 "anthropic/claude-3.5-sonnet:beta",
                                                                                                                                                 "fireworks/firellava-13b",
                                                                                                                                                 "gpt-4-turbo",
                                                                                                                                                 "gpt-5.1",
                                                                                                                                                 "gpt-4.5-preview",
                                                                                                                                                 "openai/gpt-4o-mini",
                                                                                                                                                 "openai/o1",
                                                                                                                                                 "openai/o1-pro",
                                                                                                                                                 "anthropic/claude-haiku-4.5",
                                                                                                                                                 "openai/gpt-4o",
                                                                                                                                                 "anthropic/claude-sonnet-4",
                                                                                                                                                 "anthropic/claude-opus-4",
                                                                                                                                                 "anthropic/claude-opus-4.5",
                                                                                                                                                 "mistralai/pixtral-large-2411",
                                                                                                                                                 "google/gemini-pro-1.5",
                                                                                                                                                 "google/gemini-flash-1.5",
                                                                                                                                                 "liuhaotian/llava-yi-34b", "openai/chatgpt-4o-latest",
                                                                                                                                                 "anthropic/claude-4-opus-20250522",
                                                                                                                                                 "anthropic/claude-4-sonnet-20250522",
                                                                                                                                                 "google/gemini-2.5-pro", "google/gemini-2.0-flash-001", "google/gemini-2.5-flash",
                                                                                                                                                   "anthropic/claude-3.7-sonnet", "anthropic/claude-3.7-sonnet:beta", "anthropic/claude-sonnet-4.5"], f"{self.model_name} is not supported for image input."
            encoded_images = []
            for img in images:
                if os.path.exists(img):
                    base64_image = encode_image(img)
                    # get image type from extension of img
                    image_type = img.split(".")[-1]
                    if self.model_name in [ "google/gemini-pro-1.5"]:
                        encoded_images.append(f"data:image/png;base64,{base64_image}")
                    else:
                        encoded_images.append(f"data:image/{image_type};base64,{base64_image}")

                elif len(enhanced_robust_url_extractor(img))==1:
                    encoded_images.append(img)
                elif isinstance(img, str):
                    encoded_images.append(f"data:image/png;base64,{img}")
            images = encoded_images
            system = f"{self.base_system}\nYou are an expert at reading images, reading text from images and performing OCR, image analysis, graph analysis, object detection, image recognition and text extraction from images. You are hardworking, detail oriented and you leave no stoned unturned. The attached images are referred in text as documents as '#doc_<doc_number>' like '#doc_1' etc.\n{system if system is not None else ''}"
        if self.model_type == "openai":
            return self.__call_openai_models(text, images, temperature, stream, max_tokens, system, *args, **kwargs)
        else:
            return self.__call_openrouter_models(text, images, temperature, stream, max_tokens, system, *args, **kwargs)


    def __call_openrouter_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.base_system
        system = f"{sys_init}\n{system.strip()}" if system is not None and len(system.strip()) > 0 else (sys_init)
        text_len = len(self.gpt4_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        tok_count = get_gpt4_word_count(system + text)
        assertion_error_message = f"Model {self.model_name} is selected. Please reduce the context window. Current context window is {tok_count} tokens."
        if self.model_name in CHEAP_LONG_CONTEXT_LLM:
            assert tok_count < 800_000, assertion_error_message
        elif self.model_name in LONG_CONTEXT_LLM:
            assert tok_count < 900_000, assertion_error_message
        elif self.model_name in EXPENSIVE_LLM:
            assert tok_count < 200_000, assertion_error_message
        elif "google/gemini-flash-1.5" in self.model_name or "google/gemini-flash-1.5-8b" in self.model_name or "google/gemini-pro-1.5" in self.model_name:
            assert tok_count < 400_000, assertion_error_message
        elif "gemini" in self.model_name:
            assert tok_count < 500_000, assertion_error_message
        elif "cohere/command-r-plus" in self.model_name or "llama-3.1" in self.model_name or "deepseek" in self.model_name or "jamba-1-5" in self.model_name:
            assert tok_count < 100_000
        elif "mistralai/pixtral-large-2411" in self.model_name or "mistralai/mistral-large-2411" in self.model_name:
            assert tok_count < 100_000, assertion_error_message
            
        elif "mistralai" in self.model_name:
            assert tok_count < 146000, assertion_error_message
        elif "claude-3" in self.model_name:
            assert tok_count < 180_000, assertion_error_message
        elif "anthropic" in self.model_name:
            assert tok_count < 160_000, assertion_error_message
        elif "openai" in self.model_name:
            assert tok_count < 160_000, assertion_error_message
        elif self.model_name in VERY_CHEAP_LLM or self.model_name in CHEAP_LLM or self.model_name in EXPENSIVE_LLM:
            assert tok_count < 160_000, assertion_error_message
        else:
            assert tok_count < 48000, assertion_error_message
        streaming_solution = call_with_stream(call_chat_model, stream, self.model_name, text, images, temperature,
                                              system, self.keys)
        return streaming_solution

    @retry(wait=wait_random_exponential(min=10, max=30), stop=stop_after_attempt(0))
    def __call_openai_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.base_system
        system = f"{sys_init}\n{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        if self.self_hosted_model_url is not None:
            raise ValueError("Self hosted models not supported")
        else:
            assert self.keys["openAIKey"] is not None

        model_name = self.model_name
        # Handle deep research models
        if model_name in DEEP_RESEARCH_MODELS:
            # Deep research models are handled separately
            pass
        elif model_name == "o1-mini":
            pass
        elif model_name == "o1-preview":
            pass
        elif model_name == "gpt-4-turbo":
            pass
        elif model_name == "o1" or model_name == "o1-hard" or model_name == "o1-easy":
            pass
        elif model_name == "gpt-4.5-preview":
            pass
        elif model_name == "gpt-4o":
            pass
        elif model_name == "gpt-4o-mini":
            pass
        elif (model_name != "gpt-4-turbo" and model_name != "gpt-4o" and model_name != "gpt-4o-mini") and text_len > 12000:
            model_name = "gpt-4o"
        elif (model_name != "gpt-4-turbo" and model_name != "gpt-4o" and model_name!= "gpt-4-32k" and model_name!="gpt-4o-mini"):
            model_name = "gpt-4o-mini"
        elif len(images) > 0 and model_name != "gpt-4-turbo" and model_name!="gpt-4o-mini":
            model_name = "gpt-4o"
        elif self.model_name == "gpt-4o":
            model_name = "gpt-4o"
        assert model_name not in ["gpt-3.5-turbo", "gpt-3.5-turbo-16k"]

        try:
            assert text_len < 98000
        except AssertionError as e:
            text = get_first_last_parts(text, 40000, 50000, self.gpt4_enc)

        return call_with_stream(call_chat_model, stream, model_name, text, images, temperature, system, self.keys)


class CallMultipleLLM:
    def __init__(self, keys, model_names:List[str], merge=False, merge_model=None):
        self.keys = keys
        if model_names is None or len(model_names) < 2:
            raise ValueError("At least two models are needed for multiple model call")
        self.model_names = model_names

        self.merge = merge
        self.merge_model = CallLLm(keys, model_name=merge_model) if merge_model is not None else CallLLm(keys, model_name=EXPENSIVE_LLM[0])
        self.backup_model = CallLLm(keys, model_name=CHEAP_LLM[0], use_gpt4=True, use_16k=True)
        self.models:List[CallLLm] = [CallLLm(keys, model_name=model_name) for model_name in model_names]

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        return self.call_models(text, images=images, temperature=temperature,stream=stream, max_tokens=max_tokens, system=system,
                                *args, **kwargs)

    def call_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        responses = []
        logger.warning(f"[CallMultipleLLM] with temperature = {temperature}, stream = {stream} and models = {self.model_names}")
        start_time = time.time()
        # Call each model and collect responses with stream set to False
        from common import stream_multiple_models
        models_responses = ""
        multi_model_stream = stream_multiple_models(self.keys, self.model_names, [text] * len(self.model_names), images=images, temperature=temperature, max_tokens=max_tokens, system=system, 
                           collapsible_headers=True, header_template="Response from {model}")
        for chunk in multi_model_stream:
            models_responses += chunk
            if stream:
                yield chunk
        models_responses += "\n\n"
        yield "\n\n"
        
        if self.merge:
            merged_prompt = f"""We had originally asked large language model experts the below information/question:
<|original_context|>
{text}
<|/original_context|>
Given below are the responses we obtained by asking multiple models with the above context.
Consider each response and pick the best parts from each response to create a single comprehensive response.
Merge the following responses, ensuring to include all details from each of the expert model answers and following instructions given in the originalcontext:\n
{models_responses}

Merge the above responses to create a single comprehensive response including all details from each of the expert model answers and following instructions given in the original context.
"""
            
            system_prompt = "You are a language model tasked with merging responses from multiple other models without losing any information and including all details from each of the expert model answers. Please ensure clarity, coverage and completeness. Provide a comprehensive and detailed answer."
            logger.warning(f"[CallMultipleLLM] merging responses from all models with prompt length {len(merged_prompt.split())} with elapsed time as {(time.time() - start_time):.2f} seconds")
            merged_response = collapsible_wrapper(self.merge_model(merged_prompt, system=system_prompt, stream=stream), header="Merged Response", show_initially=True)
            if stream:
                for chunk in merged_response:
                    models_responses += chunk
                    yield chunk
            else:
                merged_response = merged_response.strip()
                return models_responses + merged_response
            
        else:
            if not stream:
                return models_responses
            
class MockCallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):
        self.keys = keys
        self.model_name = model_name
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.mock_response = r"""
# **Mathematics in Computer Science: The Logic of Computation**  
  
Following our exploration of mathematics in physics and chemistry, let's dive into how computer science uses mathematics as its **foundational language**. Unlike physics (which describes nature) or chemistry (which studies matter), computer science uses mathematics to **create abstract systems**, **solve computational problems**, and **design algorithms**.  
  
## **The Mathematical Foundation: Why Computer Science Needs Math**  
  
Computer science uses mathematics to:  
- **Design algorithms** and analyze their efficiency  
- **Prove correctness** of programs and systems  
- **Model computational problems** abstractly  
- **Optimize performance** and resource usage  
- **Ensure security** through cryptographic methods  
- **Process and analyze data** at scale  
  
## **Core Mathematical Areas in Computer Science**  
  
### **1. Discrete Mathematics: The Foundation**  
  
**Why It's Essential:**  
- Computers work with **discrete values** (0s and 1s)  
- **Logic** forms the basis of all computation  
- **Combinatorics** helps count possibilities and analyze complexity  
  
**Key Applications:**  
  
**Boolean Logic:**  
$$\text{AND: } A \land B$$  
$$\text{OR: } A \lor B$$  
$$\text{NOT: } \neg A$$  
$$\text{XOR: } A \oplus B$$  
  
**De Morgan's Laws:**  
$$\neg(A \land B) = \neg A \lor \neg B$$  
$$\neg(A \lor B) = \neg A \land \neg B$$  
  
**Set Theory:**  
$$A \cup B \text{ (Union)}$$  
$$A \cap B \text{ (Intersection)}$$  
$$A - B \text{ (Difference)}$$  
$$|A \times B| = |A| \times |B| \text{ (Cartesian Product)}$$  
  
**Combinatorics:**  
$$P(n,r) = \frac{n!}{(n-r)!} \text{ (Permutations)}$$  
$$C(n,r) = \binom{n}{r} = \frac{n!}{r!(n-r)!} \text{ (Combinations)}$$  
  
### **2. Graph Theory: Networks and Relationships**  
  
**Applications:**  
- **Social networks** and web graphs  
- **Computer networks** and routing  
- **Database relationships**  
- **Algorithm design** (shortest paths, spanning trees)  
  
**Key Concepts:**  
  
**Graph Representation:**  
- **Adjacency Matrix:** $A_{ij} = 1$ if edge exists between vertices $i$ and $j$  
- **Adjacency List:** Each vertex stores list of neighbors  
  
**Important Algorithms:**  
**Dijkstra's Algorithm** (shortest path):  
$$d[v] = \min(d[v], d[u] + w(u,v))$$  
  
**Graph Properties:**  
- **Degree of vertex:** $\deg(v) = $ number of edges incident to $v$  
- **Handshaking Lemma:** $\sum_{v \in V} \deg(v) = 2|E|$  
  
### **3. Probability and Statistics: Randomness and Data**  
  
**Applications:**  
- **Machine learning** and AI  
- **Randomized algorithms**  
- **Data analysis** and mining  
- **Performance modeling**  
- **Cryptography** and security  
  
**Key Concepts:**  
  
**Basic Probability:**  
$$P(A \cup B) = P(A) + P(B) - P(A \cap B)$$  
$$P(A|B) = \frac{P(A \cap B)}{P(B)} \text{ (Conditional Probability)}$$  
  
**Bayes' Theorem:**  
$$P(A|B) = \frac{P(B|A) \cdot P(A)}{P(B)}$$  
  
**Expected Value:**  
$$E[X] = \sum_{i} x_i \cdot P(X = x_i)$$  
  
**Variance:**  
$$\text{Var}(X) = E[X^2] - (E[X])^2$$  

```mermaid
graph TD
    A[User Input] --> B[Memory Retrieval System]
    B --> C[Dossier Injection]
    C --> D[Context Window Assembly]
    D --> E[LLM Processing]
    E --> F[Response Generation]
    F --> G[Memory Update]
    G --> H[Dossier Refinement]
```

*Another example of a mermaid diagram:*

```mermaid
graph TB  
    subgraph "Load Balancer Layer"  
        LB[Load Balancer]  
    end  
      
    subgraph "API Gateway Layer"  
        AG1[API Gateway 1]  
        AG2[API Gateway 2]  
        AG3[API Gateway 3]  
    end  
      
    subgraph "Memory Service Layer"  
        MS1[Memory Service 1]  
        MS2[Memory Service 2]  
        MS3[Memory Service 3]  
        MS4[Memory Service 4]  
    end  
      
    subgraph "Database Layer"  
        VDB1[Vector DB Shard 1]  
        VDB2[Vector DB Shard 2]  
        VDB3[Vector DB Shard 3]  
          
        SQL1[PostgreSQL 1]  
        SQL2[PostgreSQL 2]  
        SQL3[PostgreSQL 3]  
    end  
      
    subgraph "Cache Layer"  
        C1[Redis Cluster 1]  
        C2[Redis Cluster 2]  
        C3[Redis Cluster 3]  
    end  
      
    LB --> AG1  
    LB --> AG2  
    LB --> AG3  
      
    AG1 --> MS1  
    AG1 --> MS2  
    AG2 --> MS3  
    AG2 --> MS4  
    AG3 --> MS1  
    AG3 --> MS3  
      
    MS1 --> VDB1  
    MS2 --> VDB2  
    MS3 --> VDB3  
    MS4 --> VDB1  
      
    MS1 --> SQL1  
    MS2 --> SQL2  
    MS3 --> SQL3  
    MS4 --> SQL1  
      
    MS1 --> C1  
    MS2 --> C2  
    MS3 --> C3  
    MS4 --> C1  
```

*Another example of a mermaid diagram:*

```mermaid
graph LR
    X1[x₁] --> H1[h₁]
    X1 --> H2[h₂]
    X1 --> H3[h₃]
    X2[x₂] --> H1
    X2 --> H2
    X2 --> H3
    X3[x₃] --> H1
    X3 --> H2
    X3 --> H3
    H1 --> Y1[y₁]
    H2 --> Y1
    H3 --> Y1
    H1 --> Y2[y₂]
    H2 --> Y2
    H3 --> Y2
```




Would you like me to dive deeper into any specific area, such as the mathematics behind a particular machine learning algorithm, or explore how graph theory is used in social network analysis?</answer>  


"""

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        mock_response = self.mock_response + " " + "".join(random.choices(string.ascii_letters + string.digits, k=100))
        if stream:
            for line in mock_response.split("\n"):
                for word in line.split(" "):
                    yield word + " "
                    
                yield "\n"
                time.sleep(0.01)
                
        else:
            yield mock_response