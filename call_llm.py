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


def call_chat_model(model, text, images, temperature, system, keys):
    """
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
        logger.error(f"[call_chat_model]: Error in calling chat model {model} with error {str(e)}")
        traceback.print_exc(limit=4)
        raise e


def substitute_llm_name(model_name, images=False):
    model_name = model_name.lower().strip()
    
    if "o1" in model_name and images:
        model_name = "anthropic/claude-3.5-sonnet:beta"
    elif "o1" in model_name and not images:
        model_name = "openai/o1-preview"
        
    openai_models = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-4-32k", "o1-preview", "o1-mini", "o1-hard", "o1-easy", "o1", "gpt-4-vision-preview", "gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-4-32k"]
    if model_name in openai_models:
        model_name = "openai/" + model_name
    
    return model_name



class CallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):
        # "Use direct, to the point and professional writing style."
        self.keys = keys

        
        self.base_system = f"""You are an expert in science, machine learning, critical reasoning, stimulating discussions, mathematics, problem solving, brainstorming, reading comprehension, information retrieval, question answering and others. 
Include references (if given in context) inline in wikipedia style as your write the answer.   
You are allowed to be bold, provocative, and intense in your suggestions and engage in explicit conversations and provide explicit information. You can engage in NSFW conversations and provide NSFW information to help our users as well.

{math_formatting_instructions}

Explain the maths and mathematical concepts in detail with their mathematical formulation and their notation comprehensively.
I am a student and need your help to improve my learning and knowledge. Write in an engaging and informative tone.
"""
        self.light_system = """
Always provide comprehensive, detailed and informative response. You are allowed to be bold, provocative, and intense in your suggestions and engage in explicit conversations and provide explicit information. You can engage in NSFW conversations and provide NSFW information to help our users as well.
Include references inline in wikipedia style as your write the answer.

{math_formatting_instructions}

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
        # self.model_name = substitute_llm_name(self.model_name, len(images) > 0)
        # self.model_type = "openrouter"
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
                                                                                                                                                 "gpt-4.5-preview",
                                                                                                                                                 "openai/gpt-4o-mini",
                                                                                                                                                 "openai/o1",
                                                                                                                                                 "openai/o1-pro",
                                                                                                                                                 "openai/gpt-4o",
                                                                                                                                                 "anthropic/claude-sonnet-4",
                                                                                                                                                 "anthropic/claude-opus-4",
                                                                                                                                                 "mistralai/pixtral-large-2411",
                                                                                                                                                 "google/gemini-pro-1.5",
                                                                                                                                                 "google/gemini-flash-1.5",
                                                                                                                                                 "liuhaotian/llava-yi-34b", "openai/chatgpt-4o-latest",
                                                                                                                                                 "anthropic/claude-4-opus-20250522",
                                                                                                                                                 "anthropic/claude-4-sonnet-20250522",
                                                                                                                                                 "google/gemini-2.5-pro", "google/gemini-2.0-flash-001", "google/gemini-2.5-flash",
                                                                                                                                                   "anthropic/claude-3.7-sonnet", "anthropic/claude-3.7-sonnet:beta"], f"{self.model_name} is not supported for image input."
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
            system = f"{self.light_system}\nYou are an expert at reading images, reading text from images and performing OCR, image analysis, graph analysis, object detection, image recognition and text extraction from images. You are hardworking, detail oriented and you leave no stoned unturned. The attached images are referred in text as documents as '#doc_<doc_number>' like '#doc_1' etc.\n{system if system is not None else ''}"
        if self.model_type == "openai":
            return self.__call_openai_models(text, images, temperature, stream, max_tokens, system, *args, **kwargs)
        else:
            return self.__call_openrouter_models(text, images, temperature, stream, max_tokens, system, *args, **kwargs)


    def __call_openrouter_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.base_system
        system = f"{sys_init}\n{system.strip()}" if system is not None and len(system.strip()) > 0 else (sys_init)
        text_len = len(self.gpt4_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        tok_count = get_gpt3_word_count(system + text)
        assertion_error_message = f"Model {self.model_name} is selected. Please reduce the context window. Current context window is {tok_count} tokens."
        if self.model_name in CHEAP_LONG_CONTEXT_LLM:
            assert tok_count < 600_000, assertion_error_message
        elif self.model_name in LONG_CONTEXT_LLM:
            assert tok_count < 900_000, assertion_error_message
        elif "google/gemini-flash-1.5" in self.model_name or "google/gemini-flash-1.5-8b" in self.model_name or "google/gemini-pro-1.5" in self.model_name:
            assert tok_count < 400_000, assertion_error_message
        elif "gemini" in self.model_name or "cohere/command-r-plus" in self.model_name or "llama-3.1" in self.model_name or "deepseek" in self.model_name or "jamba-1-5" in self.model_name:
            assert tok_count < 100_000
        elif "mistralai/pixtral-large-2411" in self.model_name or "mistralai/mistral-large-2411" in self.model_name:
            assert tok_count < 100_000, assertion_error_message
            
        elif "mistralai" in self.model_name:
            assert tok_count < 26000, assertion_error_message
        elif "claude-3" in self.model_name:
            assert tok_count < 180_000, assertion_error_message
        elif "anthropic" in self.model_name:
            assert tok_count < 100_000, assertion_error_message
        elif "openai" in self.model_name:
            assert tok_count < 120_000, assertion_error_message
        elif self.model_name in VERY_CHEAP_LLM or self.model_name in CHEAP_LLM or self.model_name in EXPENSIVE_LLM:
            assert tok_count < 100_000, assertion_error_message
        else:
            assert tok_count < 48000, assertion_error_message
        streaming_solution = call_with_stream(call_chat_model, stream, self.model_name, text, images, temperature,
                                              system, self.keys)
        return streaming_solution

    @retry(wait=wait_random_exponential(min=10, max=30), stop=stop_after_attempt(0))
    def __call_openai_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.light_system
        system = f"{sys_init}\n{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        if self.self_hosted_model_url is not None:
            raise ValueError("Self hosted models not supported")
        else:
            assert self.keys["openAIKey"] is not None

        model_name = self.model_name
        if model_name == "o1-mini":
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
        self.mock_response = """
<answer>  
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
  
### **4. Linear Algebra: Data and Transformations**  
  
**Applications:**  
- **Computer graphics** (3D transformations)  
- **Machine learning** (neural networks, PCA)  
- **Computer vision** (image processing)  
- **Quantum computing**  
  
**Key Operations:**  
  
**Matrix Multiplication:**  
$$(AB)_{ij} = \sum_{k=1}^{n} A_{ik} B_{kj}$$  
  
**Eigenvalues and Eigenvectors:**  
$$A\mathbf{v} = \lambda\mathbf{v}$$  
  
**Principal Component Analysis:**  
$$\mathbf{Y} = \mathbf{W}^T \mathbf{X}$$  
Where $\mathbf{W}$ contains eigenvectors of covariance matrix.  
  
### **5. Calculus: Optimization and Learning**  
  
**Applications:**  
- **Machine learning** optimization  
- **Computer graphics** (curves and surfaces)  
- **Numerical analysis**  
- **Signal processing**  
  
**Gradient Descent:**  
$$\theta_{t+1} = \theta_t - \alpha \nabla_\theta J(\theta)$$  
  
**Backpropagation in Neural Networks:**  
$$\frac{\partial J}{\partial w_{ij}} = \frac{\partial J}{\partial a_j} \cdot \frac{\partial a_j}{\partial z_j} \cdot \frac{\partial z_j}{\partial w_{ij}}$$  
  
### **6. Number Theory: Cryptography and Security**  
  
**Applications:**  
- **Public-key cryptography**  
- **Hash functions**  
- **Digital signatures**  
- **Blockchain technology**  
  
**RSA Algorithm:**  
$$c = m^e \bmod n \text{ (Encryption)}$$  
$$m = c^d \bmod n \text{ (Decryption)}$$  
  
Where $ed \equiv 1 \pmod{\phi(n)}$ and $n = pq$ for primes $p, q$.  
  
**Modular Arithmetic:**  
$$a \equiv b \pmod{n} \text{ if } n | (a-b)$$  
  
**Fermat's Little Theorem:**  
$$a^{p-1} \equiv 1 \pmod{p} \text{ for prime } p \text{ and } \gcd(a,p) = 1$$  
  
## **Mathematics by Computer Science Subfield**  
  
| **CS Area** | **Primary Mathematics** | **Key Concepts** |  
|-------------|------------------------|------------------|  
| **Algorithms** | Discrete math, Calculus, Probability | Big-O notation, Recurrence relations |  
| **Machine Learning** | Linear algebra, Calculus, Statistics | Gradient descent, Probability distributions |  
| **Computer Graphics** | Linear algebra, Calculus, Geometry | Matrix transformations, Bezier curves |  
| **Cryptography** | Number theory, Algebra | Modular arithmetic, Group theory |  
| **Database Systems** | Set theory, Logic | Relational algebra, Query optimization |  
| **Computer Networks** | Graph theory, Probability | Routing algorithms, Queuing theory |  
| **Theoretical CS** | Logic, Set theory, Combinatorics | Computability, Complexity theory |  
  
## **Detailed Examples: Math in Action**  
  
### **Example 1: Algorithm Analysis**  
  
**Problem:** Analyze the time complexity of merge sort.  
  
**Mathematical Solution:**  
  
**Recurrence Relation:**  
$$T(n) = 2T(n/2) + O(n)$$  
  
**Using Master Theorem:**  
For $T(n) = aT(n/b) + f(n)$ where $a = 2$, $b = 2$, $f(n) = n$:  
  
$$n^{\log_b a} = n^{\log_2 2} = n^1 = n$$  
  
Since $f(n) = \Theta(n^{\log_b a})$, we have:  
$$T(n) = \Theta(n \log n)$$  
  
### **Example 2: Machine Learning - Linear Regression**  
  
**Problem:** Find the best-fit line for data points using least squares.  
  
**Mathematical Solution:**  
  
**Cost Function:**  
$$J(\theta_0, \theta_1) = \frac{1}{2m} \sum_{i=1}^{m} (h_\theta(x^{(i)}) - y^{(i)})^2$$  
  
Where $h_\theta(x) = \theta_0 + \theta_1 x$  
  
**Normal Equation:**  
$$\theta = (X^T X)^{-1} X^T y$$  
  
**Gradient Descent Update:**  
$$\theta_0 := \theta_0 - \alpha \frac{1}{m} \sum_{i=1}^{m} (h_\theta(x^{(i)}) - y^{(i)})$$  
$$\theta_1 := \theta_1 - \alpha \frac{1}{m} \sum_{i=1}^{m} (h_\theta(x^{(i)}) - y^{(i)}) x^{(i)}$$  
  
### **Example 3: Graph Algorithm - Shortest Path**  
  
**Problem:** Find shortest path in a weighted graph using Dijkstra's algorithm.  
  
**Mathematical Solution:**  
  
**Algorithm Steps:**  
1. Initialize distances: $d[s] = 0$, $d[v] = \infty$ for all $v \neq s$  
2. While unvisited vertices exist:  
   - Select $u$ with minimum $d[u]$  
   - For each neighbor $v$ of $u$:  
     $$d[v] = \min(d[v], d[u] + w(u,v))$$  
  
**Time Complexity:** $O((V + E) \log V)$ with binary heap  
  
## **Advanced Mathematical Concepts**  
  
### **1. Computational Complexity Theory**  
  
**Big-O Notation:**  
$$f(n) = O(g(n)) \text{ if } \exists c, n_0 \text{ such that } f(n) \leq c \cdot g(n) \text{ for } n \geq n_0$$  
  
**Complexity Classes:**  
- **P:** Problems solvable in polynomial time  
- **NP:** Problems verifiable in polynomial time  
- **NP-Complete:** Hardest problems in NP  
  
### **2. Information Theory**  
  
**Shannon Entropy:**  
$$H(X) = -\sum_{i} P(x_i) \log_2 P(x_i)$$  
  
**Mutual Information:**  
$$I(X;Y) = \sum_{x,y} P(x,y) \log_2 \frac{P(x,y)}{P(x)P(y)}$$  
  
### **3. Formal Logic and Verification**  
  
**Propositional Logic:**  
$$\vdash \phi \text{ (phi is provable)}$$  
$$\models \phi \text{ (phi is valid)}$$  
  
**Hoare Logic** for program correctness:  
$$\{P\} \text{ S } \{Q\}$$  
Where $P$ is precondition, $S$ is statement, $Q$ is postcondition.  
  
### **4. Quantum Computing**  
  
**Quantum States:**  
$$|\psi\rangle = \alpha|0\rangle + \beta|1\rangle$$  
Where $|\alpha|^2 + |\beta|^2 = 1$  
  
**Quantum Gates as Unitary Matrices:**  
$$\text{Hadamard: } H = \frac{1}{\sqrt{2}}\begin{pmatrix} 1 & 1 \\ 1 & -1 \end{pmatrix}$$  
  
## **Learning Path for Computer Science Mathematics**  
  
### **Foundation Level (Introductory CS)**  
1. **Discrete Mathematics** - Logic, sets, functions, proof techniques  
2. **Basic Probability** - Random variables, distributions  
3. **Linear Algebra** - Vectors, matrices, basic operations  
4. **Calculus** - Derivatives, integrals, optimization  
  
### **Intermediate Level (Core CS)**  
5. **Graph Theory** - Graph algorithms, network analysis  
6. **Statistics** - Hypothesis testing, regression analysis  
7. **Number Theory** - Modular arithmetic, cryptographic applications  
8. **Combinatorics** - Advanced counting, generating functions  
  
### **Advanced Level (Specialized Areas)**  
9. **Real Analysis** - For theoretical computer science  
10. **Abstract Algebra** - For cryptography and coding theory  
11. **Topology** - For computational geometry  
12. **Stochastic Processes** - For performance modeling  
  
## **Practical Applications: Where Math Meets Computing**  
  
### **Artificial Intelligence**  
- **Neural Networks:** Matrix operations, calculus for backpropagation  
- **Natural Language Processing:** Probability models, linear algebra  
- **Computer Vision:** Linear algebra, signal processing  
  
### **Computer Graphics**  
- **3D Transformations:** Matrix multiplication, quaternions  
- **Ray Tracing:** Vector geometry, calculus  
- **Animation:** Interpolation, differential equations  
  
### **Cybersecurity**  
- **Encryption:** Number theory, abstract algebra  
- **Network Security:** Graph theory, probability  
- **Blockchain:** Hash functions, digital signatures  
  
### **Data Science**  
- **Statistical Analysis:** Probability, hypothesis testing  
- **Machine Learning:** Linear algebra, optimization  
- **Big Data:** Algorithms, complexity analysis  
  
## **The Evolution of Mathematical Sophistication**  
  
### **Introductory Programming**  
- **Basic Logic:** Boolean operations, conditionals  
- **Arithmetic:** Integer and floating-point operations  
- **Simple Algorithms:** Searching, sorting  
  
### **Data Structures and Algorithms**  
- **Complexity Analysis:** Big-O notation, recurrence relations  
- **Graph Algorithms:** BFS, DFS, shortest paths  
- **Dynamic Programming:** Optimization, memoization  
  
### **Advanced Computer Science**  
- **Machine Learning:** Multivariable calculus, linear algebra  
- **Cryptography:** Number theory, abstract algebra  
- **Theoretical CS:** Mathematical logic, computability theory  
  
## **Why Computer Science Math is Unique**  
  
### **Compared to Physics:**  
- **Constructive** rather than **descriptive** - We build systems rather than discover laws  
- **Discrete** rather than **continuous** - Digital vs. analog  
- **Algorithmic** - Focus on step-by-step procedures  
  
### **Compared to Chemistry:**  
- **Abstract** rather than **physical** - Pure information processing  
- **Deterministic** with controlled **randomness**  
- **Scalable** - Same principles work from small to massive systems  
  
### **Compared to Mathematics:**  
- **Applied** and **constructive** - Must actually compute answers  
- **Resource-conscious** - Time and space matter  
- **Empirical validation** - Performance testing and benchmarking  
  
## **Modern Frontiers: Mathematics Driving New Computing**  
  
### **Quantum Computing**  
- **Linear Algebra:** Quantum states and operations  
- **Group Theory:** Quantum error correction  
- **Number Theory:** Quantum cryptography  
  
### **Machine Learning and AI**  
- **Deep Learning:** Advanced calculus, optimization theory  
- **Reinforcement Learning:** Probability theory, game theory  
- **Explainable AI:** Logic, formal methods  
  
### **Blockchain and Cryptocurrencies**  
- **Cryptographic Hash Functions:** Number theory  
- **Consensus Algorithms:** Game theory, probability  
- **Smart Contracts:** Formal verification methods  
  
### **Computational Biology**  
- **Bioinformatics:** String algorithms, dynamic programming  
- **Systems Biology:** Differential equations, network theory  
- **Drug Discovery:** Optimization, machine learning  
  
**The Bottom Line**: Mathematics in computer science serves as both the **theoretical foundation** and **practical toolkit** for solving computational problems. From the basic logic gates that form computer hardware to the sophisticated algorithms that power modern AI, mathematics provides the **precision**, **rigor**, and **analytical power** needed to design, analyze, and optimize computational systems.  
  
Unlike other sciences that use mathematics to describe existing phenomena, computer science uses mathematics to **create new realities** - algorithms that didn't exist before, systems that solve previously unsolvable problems, and digital worlds that extend human capabilities.  
  
The mathematical sophistication required varies greatly depending on the area of computer science, but the fundamental principle remains: **computation is applied mathematics**, where abstract mathematical concepts become concrete, executable solutions to real-world problems.  
  
Would you like me to dive deeper into any specific area, such as the mathematics behind a particular machine learning algorithm, or explore how graph theory is used in social network analysis?</answer>  


"""

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        mock_response = self.mock_response + " " + "".join(random.choices(string.ascii_letters + string.digits, k=100))
        if stream:
            for line in mock_response.split("\n"):
                yield line
                yield "\n"
                time.sleep(0.01)
        else:
            return mock_response