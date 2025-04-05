import logging
import os.path
import uuid
from datetime import datetime
from uuid import uuid4

import pandas as pd
from copy import deepcopy, copy
try:
    import ujson as json
except ImportError:
    import json


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

def process_math_formatting(text):
    """
    Replaces single-backslash math tokens with double-backslash versions.
    For example:
      - \\\[   -> \\\\\\\\[
      - \\\]   -> \\\\\\\\]
      - \\\(   -> \\\\\\\\(
      - \\\)   -> \\\\\\\\)
    If you have additional rules (e.g. checking newlines), put them here.
    """
    # Simple replacements:
    text = text.replace('\\[', '\\\\[')
    text = text.replace('\\]', '\\\\]')
    text = text.replace('\\(', '\\\\(')
    text = text.replace('\\)', '\\\\)')
    return text


def stream_with_math_formatting(response):
    """
    A generator that wraps the streaming response from the LLM, buffering
    partial tokens so we don't break them across chunk boundaries.
    """
    buffer = ""
    # How many characters to keep at the end of each iteration
    TAIL_LENGTH = 4
    
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
        
        # 2. If we have enough data in the buffer, process everything
        #    except for the last TAIL_LENGTH characters to reduce risk
        #    of chopping partial tokens.
        if len(buffer) > TAIL_LENGTH:
            to_process = buffer[:-TAIL_LENGTH]
            remainder = buffer[-TAIL_LENGTH:]
            
            # Process and yield the "safe" portion
            processed_text = process_math_formatting(to_process)
            yield processed_text
            
            # Keep only the remainder in the buffer
            buffer = remainder
    
    # Once the stream is done, process and yield the final leftover
    if buffer:
        yield process_math_formatting(buffer)


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
        self.base_system = """You are an expert in science, machine learning, critical reasoning, stimulating discussions, mathematics, problem solving, brainstorming, reading comprehension, information retrieval, question answering and others. 
Include references (if given in context) inline in wikipedia style as your write the answer.   

- Formatting Mathematical Equations:
  - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
  - For inline maths and notations use "\\\\( ... \\\\)" instead of '$$'. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.
  - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)` for inline maths.

Explain the maths and mathematical concepts in detail with their mathematical formulation and their notation comprehensively.
I am a student and need your help to improve my learning and knowledge. Write in an engaging and informative tone.
"""
        self.light_system = """
Always provide comprehensive, detailed and informative response.
Include references inline in wikipedia style as your write the answer.

- Formatting Mathematical Equations:
  - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
  - For inline maths and notations use "\\\\( ... \\\\)" instead of '$$'. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.
  - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)` for inline maths.

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
                                                                                                                                                 "mistralai/pixtral-large-2411",
                                                                                                                                                 "google/gemini-pro-1.5",
                                                                                                                                                 "google/gemini-flash-1.5",
                                                                                                                                                 "liuhaotian/llava-yi-34b", "openai/chatgpt-4o-latest", "anthropic/claude-3.7-sonnet", "anthropic/claude-3.7-sonnet:beta"], f"{self.model_name} is not supported for image input."
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
        system = f"{sys_init}\n{system.strip()}" if system is not None and len(system.strip()) > 0 else (sys_init + "\n" + self.light_system)
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
        system = f"{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
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
        responses_futures = []
        for model in self.models:
            response = get_async_future(model, text, images=images, temperature=temperature, stream=False, max_tokens=max_tokens,
                             system=system, *args, **kwargs)
            responses_futures.append((model.model_name, response))  # Assuming model_name is accessible
        logger.warning(f"[CallMultipleLLM] invoked all models")

        while len(responses_futures) > 0:
            while not any([resp[1].done() for resp in responses_futures]):
                time.sleep(0.1)
                # sleep more
            # Get the one that is done
            resp = [resp for resp in responses_futures if resp[1].done()][0]
            responses_futures.remove(resp)
            logger.warning(f"[CallMultipleLLM] got response from model {resp[0]} with success/failure as ```{resp[1].exception()}``` with elapsed time as {(time.time() - start_time):.2f} seconds")
            try:
                result = resp[1].result()
                
                random_identifier = str(uuid.uuid4())
                result = f"\n**Response from {resp[0]} :** <div data-toggle='collapse' href='#responseFrom-{random_identifier}' role='button'></div> <div class='collapse' id='responseFrom-{random_identifier}'>\n" + result + f"\n</div>\n\n"
                
                responses.append((resp[0], result))
                logger.warning(
                    f"[CallMultipleLLM] added response from model: {resp[0]} to `responses` with elapsed time as {(time.time() - start_time):.2f} seconds")

            except Exception as e:
                result = self.backup_model(text, images=images, temperature=0.9, stream=False, max_tokens=max_tokens,
                                           system=system, *args, **kwargs)
                random_identifier = str(uuid.uuid4())
                result = f"\n**Response from {self.backup_model.model_name} :** <div data-toggle='collapse' href='#responseFrom-{random_identifier}' role='button'></div> <div class='collapse' id='responseFrom-{random_identifier}'>\n" + result + f"\n</div>\n\n"
                responses.append((self.backup_model.model_name, result))
                logger.error(
                    f"[CallMultipleLLM] got response from backup model {self.backup_model.model_name} due to error from model {resp[0]}")


        if self.merge:
            merged_prompt = f"""We had originally asked large language model experts the below information/question:
<|original_context|>
{text}
<|/original_context|>
Given below are the responses we obtained by asking multiple models with the above context.
Consider each response and pick the best parts from each response to create a single comprehensive response.
Merge the following responses, ensuring to include all details from each of the expert model answers and following instructions given in the originalcontext:\n
"""
            for model_name, response in responses:
                merged_prompt += f"<model_response>\n<model_name>{model_name}</model_name>\n{response}\n</model_response>\n\n"

                # Add a system prompt for the merge model
            system_prompt = "You are a language model tasked with merging responses from multiple other models without losing any information and including all details from each of the expert model answers. Please ensure clarity, coverage and completeness. Provide a comprehensive and detailed answer."
            logger.warning(f"[CallMultipleLLM] merging responses from all models with prompt length {len(merged_prompt.split())} with elapsed time as {(time.time() - start_time):.2f} seconds")
            merged_response = self.merge_model(merged_prompt, system=system_prompt, stream=True)
            logger.warning(f"[CallMultipleLLM] merged response from all models with merged response length {len(merged_response.split()) if isinstance(merged_response, str) else -1} with elapsed time as {(time.time() - start_time):.2f} seconds")
            return make_stream(merged_response, stream)
        else:
            # Format responses in XML style
            formatted_responses = ""
            for model_name, response in responses:
                formatted_responses += f"<model_response>\n<model_name>{model_name}</model_name>\n{response}\n</model_response>\n\n"
            logger.warning(f"[CallMultipleLLM] returning responses from all models with elapsed time as {(time.time() - start_time):.2f} seconds")
            return make_stream(formatted_responses.strip(), stream) # formatted_responses.strip()  # Remove trailing newlines
