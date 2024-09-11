import os.path
from datetime import datetime
from uuid import uuid4

import pandas as pd
from copy import deepcopy, copy
try:
    import ujson as json
except ImportError:
    import json
from prompts import prompts
from collections import defaultdict, Counter

import openai
from typing import Callable, Any, List, Dict, Tuple, Optional, Union
from langchain_community.document_loaders import MathpixPDFLoader
from langchain_text_splitters import TokenTextSplitter



pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

from common import *

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.ERROR, logging.INFO, logging.ERROR, logging.INFO)
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


openai_rate_limits = defaultdict(lambda: (1000000, 10000), {
    "gpt-3.5-turbo": (1000000, 10000),
    "gpt-3.5-turbo-0301": (1000000, 10000),
    "gpt-3.5-turbo-0613": (1000000, 10000),
    "gpt-3.5-turbo-1106": (1000000, 10000),
    "gpt-3.5-turbo-16k": (1000000, 10000),
    "gpt-3.5-turbo-16k-0613": (1000000, 10000),
    "gpt-3.5-turbo-instruct": (250000, 3000),
    "gpt-3.5-turbo-instruct-0914": (250000, 3000),
    "gpt-4": (300000, 10000),
    "gpt-4-0314": (300000, 10000),
    "gpt-4-0613": (300000, 10000),
    "gpt-4-turbo": (800000, 10000),
    "gpt-4-32k": (150000, 100),
    "gpt-4-32k-0314": (150000, 100),
    "gpt-4-vision-preview": (150000, 100),
    "gpt-4o": (2000000 , 10000),
    "gpt-4o-mini": (10000000, 10000),
})

openai_model_family = {
    "gpt-3.5-turbo": ["gpt-3.5-turbo", "gpt-3.5-turbo-0301", "gpt-3.5-turbo-0613", "gpt-3.5-turbo-1106"],
    "gpt-3.5-16k": ["gpt-3.5-turbo-16k", "gpt-3.5-turbo-16k-0613"],
    "gpt-3.5-turbo-16k": ["gpt-3.5-turbo-16k", "gpt-3.5-turbo-16k-0613"],
    "gpt-3.5-turbo-instruct": ["gpt-3.5-turbo-instruct", "gpt-3.5-turbo-instruct-0914"],
    "gpt-4": ["gpt-4", "gpt-4-0314", "gpt-4-0613", "gpt-4-32k-0314"],
    "gpt-4-turbo": ["gpt-4-turbo", "gpt-4-vision-preview"],
    "gpt-4-0314": ["gpt-4-0314"],
    "gpt-4-0613": ["gpt-4-0613"],
    "gpt-4-32k": ["gpt-4-32k"],
    "gpt-4-vision-preview": ["gpt-4-vision-preview", "gpt-4-1106-vision-preview"],
    "gpt-4o": ["gpt-4o"],
    "gpt-4o-mini": ["gpt-4o-mini"]
}

import time
from collections import deque
from threading import Lock

# create a new tokenlimit exception class
class TokenLimitException(Exception):
    def __init__(self, message=""):
        super().__init__(message)

    def __str__(self):
        return self.args[0]

class OpenAIRateLimitRollingTokenTracker:
    def __init__(self):
        self.token_counts = {model: 0 for model in openai_rate_limits.keys()}
        self.token_time_queues = {model: deque() for model in openai_rate_limits.keys()}
        self.locks = {model: Lock() for model in openai_rate_limits.keys()}  # Lock for each model

    def add_tokens(self, model, token_count):
        with self.locks[model]:  # Ensure only one thread modifies data for a model at a time
            current_time = time.time()
            self.token_counts[model] += token_count
            self.token_time_queues[model].append((current_time, token_count))
            self.cleanup_old_tokens(model)

    def cleanup_old_tokens(self, model):
        current_time = time.time()
        while self.token_time_queues[model] and current_time - self.token_time_queues[model][0][0] > 60:
            old_time, old_count = self.token_time_queues[model].popleft()
            self.token_counts[model] -= old_count

    def get_token_count(self, model):
        with self.locks[model]:
            self.cleanup_old_tokens(model)
            return self.token_counts[model]

    def select_model(self, family: str):
        chosen_models = openai_model_family[family]
        with Lock():  # Global lock for selecting model
            model = min(chosen_models, key=self.get_token_count)
            if self.get_token_count(model) >= openai_rate_limits[model][0] - 32000:
                raise TokenLimitException("All models are rate limited")
            logger.debug(f"Selected model {model} with {self.get_token_count(model)} tokens for family {family}")
            return model

rate_limit_model_choice = OpenAIRateLimitRollingTokenTracker()

easy_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
davinci_enc = tiktoken.encoding_for_model("text-davinci-003")
gpt4_enc = tiktoken.encoding_for_model("gpt-4")

encoders_map = defaultdict(lambda: easy_enc, {
    "gpt-3.5-turbo": easy_enc,
    "gpt-3.5-turbo-0301": easy_enc,
    "gpt-3.5-turbo-0613": easy_enc,
    "gpt-3.5-turbo-1106": easy_enc,
    "gpt-3.5-turbo-16k": easy_enc,
    "gpt-3.5-turbo-16k-0613": easy_enc,
    "gpt-4": gpt4_enc,
    "gpt-4-0314": gpt4_enc,
    "gpt-4-0613": gpt4_enc,
    "gpt-4-32k-0314": gpt4_enc,
    "gpt-4-turbo": gpt4_enc,
    "gpt-4o-mini": gpt4_enc,
    "gpt-4o": gpt4_enc,
    "text-davinci-003": davinci_enc,
    "text-davinci-002": davinci_enc,
})

def call_chat_model(model, text, images, temperature, system, keys):
    api_key = keys["openAIKey"] if (("gpt" in model or "davinci" in model) and not model=='openai/gpt-4-32k') else keys["OPENROUTER_API_KEY"]
    if model.startswith("gpt") or "davinci" in model:
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text)))
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(system)))
    extras = dict(base_url="https://openrouter.ai/api/v1",) if not ("gpt" in model or "davinci" in model) or model=='openai/gpt-4-32k' else dict()
    openrouter_used = not ("gpt" in model or "davinci" in model) or model=='openai/gpt-4-32k'
    if not openrouter_used and model.startswith("openai/"):
        model = model.replace("openai/", "")
    extras_2 = dict(stop=["</s>", "Human:", "User:", "<|eot_id|>"]) if "claude" in model or openrouter_used else dict()
    from openai import OpenAI
    client = OpenAI(api_key=api_key, **extras)
    if len(images) > 0:
        messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": text},
                    *[{
                        "type": "image_url",
                        "image_url": {
                            "url": base64_image
                        }
                    } for base64_image in images]
                ]},
            ]
    else:
        messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            timeout=60,
            # max_tokens=300,
            **extras_2,
        )
        # yield response.choices[0].message.content
        # return

        chunk = None
        for chk in response:
            chunk = chk.model_dump()
            if "content" in chunk["choices"][0]["delta"]:
                text_content = chunk["choices"][0]["delta"]["content"]
                if isinstance(text_content, str):
                    yield text_content
                    if ("gpt" in model or "davinci" in model) and model != 'openai/gpt-4-32k':
                        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text_content)))

        if chunk is not None and "finish_reason" in chunk["choices"][0] and chunk["choices"][0]["finish_reason"] and chunk["choices"][0]["finish_reason"].lower().strip() not in ["stop", "end_turn", "stop_sequence", "recitation"]:
            yield "\n Output truncated due to lack of context Length."
    except Exception as e:
        logger.error(f"[call_chat_model]: Error in calling chat model {model} with error {str(e)}")
        traceback.print_exc(limit=4)
        raise e

def call_chat_model_old(model, text, temperature, system, keys):
    api_key = keys["openAIKey"] if (("gpt" in model or "davinci" in model) and not model=='openai/gpt-4-32k') else keys["OPENROUTER_API_KEY"]
    if model.startswith("gpt") or "davinci" in model:
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text)))
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(system)))
    extras = dict(api_base="https://openrouter.ai/api/v1", base_url="https://openrouter.ai/api/v1",) if not ("gpt" in model or "davinci" in model) or model=='openai/gpt-4-32k' else dict()
    response = openai.ChatCompletion.create(
        model=model,
        api_key=api_key,
        stop=["</s>", "Human:", "USER:", "[EOS]", "HUMAN:", "HUMAN :", "Human:", "User:", "USER :", "USER :", "Human :", "###", "<|eot_id|>"] if "claude" in model else [],
        messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        temperature=temperature,
        stream=True,
        **extras
    )
    chunk = None
    for chunk in response:
        if "content" in chunk["choices"][0]["delta"]:
            text_content = chunk["choices"][0]["delta"]["content"]
            yield text_content
            if ("gpt" in model or "davinci" in model) and model != 'openai/gpt-4-32k':
                rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text_content)))

    if chunk is not None and "finish_reason" in chunk["choices"][0] and chunk["choices"][0]["finish_reason"].lower().strip() not in ["stop", "end_turn", "stop_sequence", "recitation"]:
        yield "\n Output truncated due to lack of context Length."




class CallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):

        self.keys = keys
        self.light_system = "You are an expert in science, machine learning, critical reasoning, stimulating discussions, mathematics, problem solving, brainstorming, reading comprehension, information retrieval, question answering and others. \nAlways provide comprehensive, detailed and informative response.\nInclude references inline in wikipedia style as your write the answer.\nUse direct, to the point and professional writing style.\nI am a student and need your help to improve my learning and knowledge. Write the full response to the user's query now.\n"
        self.self_hosted_model_url = self.keys["vllmUrl"] if "vllmUrl" in self.keys  and not checkNoneOrEmpty(self.keys["vllmUrl"]) else None
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.gpt4_enc = encoders_map.get("gpt-4")
        self.turbo_enc = encoders_map.get("gpt-3.5-turbo")
        self.model_name = model_name
        self.model_type = "openai" if model_name is None or model_name.startswith("gpt") else "openrouter"


    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        if len(images) > 0:
            assert (self.model_type == "openai" and self.model_name in ["gpt-4-turbo", "gpt-4o", "gpt-4-vision-preview"]) or self.model_name in ["anthropic/claude-3-haiku:beta",
                                                                                                                                                 "anthropic/claude-3-opus:beta",
                                                                                                                                                 "anthropic/claude-3-sonnet:beta",
                                                                                                                                                 "anthropic/claude-3.5-sonnet:beta",
                                                                                                                                                 "fireworks/firellava-13b",
                                                                                                                                                 "gpt-4-turbo",
                                                                                                                                                 "google/gemini-pro-1.5",
                                                                                                                                                 "google/gemini-flash-1.5",
                                                                                                                                                 "liuhaotian/llava-yi-34b"]
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
        sys_init = self.light_system
        system = f"{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text) if self.use_gpt4 else self.turbo_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")

        if "google/gemini-flash-1.5" in self.model_name:
            assert get_gpt3_word_count(system + text) < 400_000
        elif "gemini" in self.model_name or "cohere/command-r-plus" in self.model_name or "llama-3.1" in self.model_name or "deepseek" in self.model_name or "jamba-1-5" in self.model_name:
            assert get_gpt3_word_count(system + text) < 100_000
        elif "mistralai" in self.model_name:
            assert get_gpt3_word_count(system + text) < 26000
        elif "claude-3" in self.model_name:
            assert get_gpt3_word_count(system + text) < 140_000
        elif "anthropic" in self.model_name:
            assert get_gpt3_word_count(system + text) < 100_000
        elif "openai" in self.model_name:
            assert get_gpt3_word_count(system + text) < 120_000
        else:
            assert get_gpt3_word_count(system + text) < 32000
        streaming_solution = call_with_stream(call_chat_model, stream, self.model_name, text, images, temperature,
                                              system, self.keys)
        return streaming_solution

    @retry(wait=wait_random_exponential(min=10, max=30), stop=stop_after_attempt(0))
    def __call_openai_models(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.light_system
        system = f"{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text) if self.use_gpt4 else self.turbo_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        if self.self_hosted_model_url is not None:
            raise ValueError("Self hosted models not supported")
        else:
            assert self.keys["openAIKey"] is not None

        model_name = "gpt-4o" if (self.use_gpt4 and self.use_16k and self.model_name not in ["gpt-4-turbo", "gpt-4", "gpt-4-32k", "gpt-4o-mini"]) else "gpt-4o-mini"
        if (model_name != "gpt-4-turbo" and model_name != "gpt-4o") and (text_len > 3000 and model_name == "gpt-3.5-turbo"):
            model_name = "gpt-4o-mini"
        if (model_name != "gpt-4-turbo" and model_name != "gpt-4o") and (text_len < 3000 and model_name == "gpt-3.5-turbo-16k"):
            model_name = "gpt-4o-mini"
        if (model_name != "gpt-4-turbo" and model_name != "gpt-4o") and text_len > 12000:
            model_name = "gpt-4o"
        if len(images) > 0 and model_name != "gpt-4-turbo":
            model_name = "gpt-4o"
        if self.model_name == "gpt-4o":
            model_name = "gpt-4o"

        try:
            assert text_len < 98000
        except AssertionError as e:
            text = get_first_last_parts(text, 40000, 50000, self.gpt4_enc)
        try:
            model = rate_limit_model_choice.select_model(model_name)
            return call_with_stream(call_chat_model, stream, model, text, images, temperature, system, self.keys)
        except TokenLimitException as e:
            time.sleep(5)
            try:
                model = rate_limit_model_choice.select_model(model_name)
            except:
                try:
                    model = rate_limit_model_choice.select_model("gpt-4o")
                except:
                    raise e
            return call_with_stream(call_chat_model, stream, model, text, images, temperature, system, self.keys)




        
def split_text(text):
    # Split the text by spaces, newlines, and HTML tags
    chunks = re.split(r'( |\n|<[^>]+>)', text)
    
    # Find the middle index
    middle = len(chunks) // 2

    # Split the chunks into two halves
    first_half = ''.join(chunks[:min(middle+100, len(chunks)-1)])
    second_half = ''.join(chunks[max(0, middle-100):])
    
    yield first_half
    yield second_half





enc = tiktoken.encoding_for_model("gpt-4")

@AddAttribute('name', "TextLengthCheck")
@AddAttribute('description', """
TextLengthCheck:
    Checks if the token count of the given `text_document` is smaller or lesser than the `threshold`.

    Input params/args: 
        text_document (str): document to verify if its length or word count or token count is less than threshold.
        threshold (int): Token count, text_document token count is below this then returns True

    Returns: 
        bool: whether length or token count is less than given threshold.

    Usage:
        `length_valid = TextLengthCheck(text_document="document to check length") # This tool needs no initialization`
        `less_than_ten = TextLengthCheck(text_document="document to check length", threshold=10)`

    """)
def TextLengthCheck(text_document: str, threshold: int=3400):
    assert isinstance(text_document, str)
    return len(enc.encode(text_document)) < threshold

@AddAttribute('name', "Search")
@AddAttribute('description', """
Search:
    This tool takes a search phrase, performs search over a web search engine and returns a list of urls for the search.

    Input params/args: 
        search_phrase (str): phrase or keywords to search over the web/internet.
        top_n (int): Number of webpages or results to return from search. Default is 5.

    Returns: 
        List[str]: List of webpage urls for given search_phrase, List length same as top_n input parameter.

    Usage:
        `web_url_list = Search(search_phrase="phrase to search") # This tool needs no initialization`
        
    Alternative Usage:
        `web_url_list = Search(search_phrase="phrase to search", top_n=20) # Get a custom number of results

    """)
def Search(search_phrase: str, top_n: int=5):
    return [r["link"] for r in  BingSearchAPIWrapper().results(search_phrase, top_n)]

@AddAttribute('name', "ChunkText")
@AddAttribute('description', """
ChunkText:
    This tool takes a text document and chunks it into given chunk size lengths, then returns a list of strings as chunked sub-documents.

    Input params/args: 
        text_document (str): document to create chunks from.
        chunk_size (int): Size of each chunk. Default is 3400, smaller chunk sizes are needed if downstream systems throw length error or token limit exceeded errors.

    Returns: 
        List[str]: text_chunks

    Usage:
        `text_chunks = ChunkText(text_document="document to chunk") # This tool needs no initialization`
        
    Alternative Usage:
        `text_chunks = ChunkText(text_document="document to chunk", chunk_size=1800) # Smaller chunk size, more chunks, but avoid token limit exceeded or length errors.

    """)
def ChunkText(text_document: str, chunk_size: int=3400, chunk_overlap:int=100):
    text_splitter = TokenTextSplitter(chunk_size=max(chunk_overlap, max(128, chunk_size)), chunk_overlap=chunk_overlap)
    return text_splitter.split_text(text_document)

@log_memory_usage
@AddAttribute('name', "ChunkTextSentences")
@AddAttribute('description', """
ChunkTextSentences:
    This tool takes a text document and chunks it into given chunk size lengths, then returns a list of strings as chunked sub-documents.

    Input params/args: 
        text_document (str): document to create chunks from.
        chunk_size (int): Size of each chunk. Default is 3400, smaller chunk sizes are needed if downstream systems throw length error or token limit exceeded errors.

    Returns: 
        List[str]: text_chunks

    Usage:
        `text_chunks = ChunkText(text_document="document to chunk") # This tool needs no initialization`

    Alternative Usage:
        `text_chunks = ChunkText(text_document="document to chunk", chunk_size=1800) # Smaller chunk size, more chunks, but avoid token limit exceeded or length errors.

    """)
def ChunkTextSentences(text_document: str, chunk_size: int = 3400, chunk_overlap: int = 100):
    text_splitter = SentenceSplitter(chunk_size=max(chunk_overlap, max(128, chunk_size)), chunk_overlap=chunk_overlap, backup_separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", "</br>", "<br>", "<br/>", "<br />", "<p>", "</p>", ])
    return text_splitter.split_text(text_document)


async def get_url_content(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url)
        title = await page.title()
        page_content = await page.content()
        # TODO: get rendered body
        page_content = await page.evaluate("""
        (() => document.body.innerText)()
        """)
        await browser.close()
        return {"title": title, "page_content": page_content}


class ContextualReader:
    def __init__(self, keys, provide_short_responses=False, scan=False):
        self.keys = keys
        self.name = "ContextualReader"
        self.provide_short_responses = provide_short_responses
        self.scan = scan
        # Use markdown formatting to typeset or format your answer better.
        long_or_short = "Provide a short, brief, concise and informative response in 3-4 sentences. \n" if provide_short_responses else "Provide concise, comprehensive and informative response. Output any relevant equations if found in latex format.\n"
        response_prompt = "Write short, compact, concise and informative" if provide_short_responses else "Write concise, comprehensive and informative"
        self.prompt = f"""You are an information retrieval agent. {long_or_short}
Provide relevant and helpful information from the given document for the given user question and conversation context given below.
<|context_or_query|>
'''{{context}}'''
<|/context_or_query|>

Document to read and extract information from is given below.
<|document|>
'''
{{document}}
'''
<|/document|>

Only provide answer from the document given above.
{response_prompt} response below.
"""
        # If no relevant information is found in given context, then output "No relevant information found." only.
        
    def get_one(self, context, document, model_name="google/gemini-pro", limit=64_000):
        document = " ".join(document.split()[:limit])
        prompt = self.prompt.format(context=context, document=document)
        try:
            llm = CallLLm(self.keys, model_name=model_name, use_gpt4=False, use_16k=False)
            result = llm(prompt, temperature=0.4, stream=False)
        except Exception as e:
            traceback.print_exc()
            llm = CallLLm(self.keys, model_name="anthropic/claude-3-haiku:beta", use_gpt4=False, use_16k=False)
            result = llm(prompt, temperature=0.4, stream=False)
        assert isinstance(result, str)
        return result

    def get_one_chunked(self, context, document, model_name="google/gemini-flash-1.5", limit=256_000, chunk_size=16_000, chunk_overlap=2_000):
        try:
            short_reading = get_async_future(self.get_one, "Provide a short summary", document,
                                             model_name, 16_000)
            document = " ".join(document.split()[:limit])
            context = context + "\n\nShort summary of the document to help your reading is below." + sleep_and_get_future_result(short_reading)
            chunks = chunk_text_words(document, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            results = [get_async_future(self.get_one, context, c, model_name=model_name, limit=chunk_size*2) for c in chunks]
            results = [sleep_and_get_future_result(r) for r in results]
            results = "\n".join(results)
            # concat all strings
            return f"Short general summary of the document:\n{sleep_and_get_future_result(short_reading)}. Relevant information from the document is below:\n{results}"
        except Exception as e:
            traceback.print_exc()
            return f"Unable to read due to exception: {str(e)}."

    def get_one_with_rag(self, context, document, retriever:Optional[Callable[[str, Optional[int]], str]]=None):
        fragments_text = self.get_relevant_text(context, document, retriever)
        prompt = self.prompt.format(context=context, document=fragments_text)
        join_method = lambda x, y: "Details from one LLM that read the document:\n<|LLM_1|>\n" + str(
            x) + "\n<|/LLM_1|>\n\nDetails from second LLM which read the document:\n<|LLM_2|>\n" + str(
            y) + "\n<|/LLM_2|>"
        result = join_two_futures(get_async_future(CallLLm(self.keys, model_name="google/gemini-flash-1.5"), prompt, temperature=0.4, stream=False),
                                  get_async_future(CallLLm(self.keys, model_name="openai/gpt-4o-mini"), prompt, temperature=0.4, stream=False), join_method
                                  )

        result = sleep_and_get_future_result(result)
        assert isinstance(result, str)
        return result

    def get_relevant_text(self, context, document, retriever: Optional[Callable[[str, Optional[int]], str]]=None):
        if retriever is None:
            document = document.strip()
            len_doc = len(document.split())
            if len_doc < 1536:
                return document
            openai_embed = get_embedding_model(self.keys)
            def get_doc_embeds(document, len_doc):
                chunk_size = 768 if len_doc < 8000 else 1280 if len_doc < 16000 else 1536 if len_doc < 32000 else 2048
                ds = document.split()
                document = " ".join(ds[:156_000])
                st_chnk = time.time()
                chunks = chunk_text_words(document, chunk_size=chunk_size, chunk_overlap=64) # ChunkTextSentences
                if len(chunks) > 128:
                    chunks = chunks[:128]
                et_chnk = time.time()
                # time_logger.info(f"[ContextualReader] Chunking time = {(et_chnk - st_chnk):.2f} seconds and doc len = {len_doc} and num chunks = {len(chunks)}")
                doc_embeds = openai_embed.embed_documents(chunks)
                et_emb = time.time()
                time_logger.info(f"[ContextualReader] Actual Embedding time = {(et_emb - et_chnk):.2f} seconds, Chunking time = {(et_chnk - st_chnk):.2f} seconds, and doc len = {len_doc} and num chunks = {len(chunks)}")
                return chunks, chunk_size, np.array(doc_embeds)

            st = time.time()
            doc_em_future = get_async_future(get_doc_embeds, document, len_doc)
            # query_em_future = get_async_future(openai_embed.embed_query, context)
            query_em_future = get_async_future(get_text_embedding, context, self.keys)
            chunks, chunk_size, doc_embedding = sleep_and_get_future_result(doc_em_future)
            doc_em_time = time.time()-st
            # query_embedding = np.array(query_em_future.result())
            query_embedding = sleep_and_get_future_result(query_em_future)
            time_logger.info(f"[ContextualReader] Embedding time = {time.time()-st:.2f}, doc em time = {doc_em_time:.2f} .")
            scores = np.dot(doc_embedding, query_embedding)
            sorted_chunks = sorted(list(zip(chunks, scores)), key=lambda x: x[1], reverse=True)
            top_chunks = sorted_chunks[:6]
        else:
            top_chunks = retriever(document, 16_000)
        top_chunks_text = ""
        for idx, tc in enumerate(top_chunks):
            top_chunks_text += f"Retrieved relevant text chunk {idx + 1}:\n{tc[0]}\n\n"
        top_chunks = top_chunks_text
        return top_chunks

    def scan(self, context, document, retriever: Optional[Callable[[str, Optional[int]], str]]=None):
        pass

    def __call__(self, context_user_query, text_document, retriever:Optional[Callable[[str, Optional[int]], str]]=None):
        assert isinstance(text_document, str)
        st = time.time()
        doc_word_count = len(text_document.split())
        join_method = lambda x, y: "Details from one expert who read the document:\n<|expert1|>\n" + str(x) + "\n<|/expert1|>\n\nDetails from second expert who read the document:\n<|expert2|>\n" + str(y) + "\n<|/expert2|>"
        initial_reading = join_two_futures(get_async_future(self.get_one, context_user_query, text_document, "google/gemini-flash-1.5", 200_000),
                                                   get_async_future(self.get_one, context_user_query, text_document, "openai/gpt-4o-mini"), join_method)
        if self.provide_short_responses:
            result = sleep_and_get_future_result(initial_reading)
            return result, initial_reading

        global_reading = None
        join_method = lambda x, y: "Details from both experts:\n<|experts|>\n" + str(
            x) + "\n<|/experts|>\n\n\nDetails from using an LLM to summarise and get information:\n<|LLM based summary|>\n" + str(
            y) + "\n<|/LLM based summary|>"

        if doc_word_count < 2048:
            return sleep_and_get_future_result(initial_reading) + "\n\nFull Text:\n" + text_document, global_reading
        elif doc_word_count < 6144:
            return sleep_and_get_future_result(initial_reading), initial_reading

        elif doc_word_count > 32_000:
            chunked_reading = get_async_future(self.get_one_chunked, context_user_query, text_document, "openai/gpt-4o-mini", 200_000, 32_000, 2_000)
            global_reading = join_two_futures(initial_reading, chunked_reading, join_method)
        main_future = get_async_future(self.get_one_with_rag, context_user_query, text_document, retriever)
        if global_reading is None:
            global_reading = initial_reading
        join_method = lambda x, y: "Details from both experts and LLMs:\n<|experts_and_LLM|>\n" + str(
            x) + "\n<|/experts_and_LLM|>\n\n\nDetails from using an Retrieval Augmented Generation with LLM:\n<|RAG LLM|>\n" + str(
            y) + "\n<|/RAG LLM|>"
        final_future = join_two_futures(main_future, global_reading, join_method)
        final_result = sleep_and_get_future_result(final_future)
        return final_result, final_future




import json
import re

def get_citation_count(dres):
    # Convert the dictionary to a JSON string and lowercase it
    json_string = json.dumps(dres).lower()
    
    # Use regex to search for the citation count
    match = re.search(r'cited by (\d+)', json_string)
    
    # If a match is found, return the citation count as an integer
    if match:
        return int(match.group(1))
    
    # If no match is found, return zero
    return ""

def get_year(dres):
    # Check if 'rich_snippet' and 'top' exist in the dictionary
    if 'rich_snippet' in dres and 'top' in dres['rich_snippet']:
        # Iterate through the extensions
        for extension in dres['rich_snippet']['top'].get('extensions', []):
            # Use regex to search for the year
            match = re.search(r'(\d{4})', extension)

            # If a match is found, return the year as an integer
            if match:
                return int(match.group(1))

    # If no match is found, return None
    return None


def list_to_gscholar_query(conferences_and_journals):
    # Prefix to be added before each conference or journal name
    prefix = 'source:'
    # Using a list comprehension to format each item with the prefix and enclosing quotes
    formatted_items = [f'{prefix}"{item}"' for item in conferences_and_journals]
    # Joining all formatted items with ' OR ' to match the query format
    query_string = ' OR '.join(formatted_items)
    return query_string


# List of conferences and journals
conferences_and_journals = [
    "Neural Information Processing Systems",
    "International Conference on Learning Representations",
    "International Conference on Machine Learning",
    "AAAI Conference on Artificial Intelligence",
    "Expert Systems with Applications",
    "IEEE Transactions on Neural Networks and Learning Systems",
    "IEEE Transactions On Systems, Man And Cybernetics Part B, Cybernetics",
    "Neurocomputing",
    "International Joint Conference on Artificial Intelligence (IJCAI)",
    "Applied Soft Computing",
    "Knowledge-Based Systems",
    "Neural Computing and Applications",
    "IEEE Transactions on Fuzzy Systems",
    "The Journal of Machine Learning Research",
    "Artificial Intelligence Review",
    "International Conference on Artificial Intelligence and Statistics",
    "Neural Networks",
    "Engineering Applications of Artificial Intelligence",
    "Applied Intelligence",
    "Conference on Robot Learning",
    "NAACL-HLT",
    "IJCAI",
    "ACL",
    "EMNLP",
    "EACL",
    "COLING",
    "CoNLL",
    "TACL",
    "Transactions of the Association for Computational Linguistics",
    "Journal of Machine Learning Research",
    "Journal of Artificial Intelligence Research",
    "IEEE Transactions on Pattern Analysis and Machine Intelligence",
    "IEEE Transactions on Knowledge and Data Engineering",
    "IEEE Transactions on Evolutionary Computation",
    "IEEE Transactions on Cybernetics",
    "IEEE Transactions on Computational Intelligence and AI in Games",
    "IEEE Transactions on Autonomous Mental Development",
    "IEEE Transactions on Affective Computing",
    "IEEE Intelligent Systems",
    "IEEE Computational Intelligence Magazine",
    "IEEE Transactions on Cognitive and Developmental Systems",
    "IEEE Transactions on Big Data",
    "IEEE Transactions on Artificial Intelligence",
    "IEEE Transactions on Emerging Topics in Computational Intelligence",
    "IEEE Transactions on Games",
    "IEEE Transactions on Human-Machine Systems",
    "IEEE Transactions on Technology and Society",
    "IEEE Transactions on Computational Social Systems",
    "IEEE Transactions on Intelligent Transportation Systems",
    "IEEE Transactions on Network Science and Engineering",
    "The NVIDIA GTC AI Conference",
]

# Using the function to convert the list to a query string
gscholar_query_string = list_to_gscholar_query(conferences_and_journals)

science_sites = [
    "arxiv.org",
    "openreview.net",
    "arxiv-vanity.com",
    "arxiv-sanity.com",
    "biorxiv.org",
    "medrxiv.org",
    "aclweb.org",
    "aclanthology.org",
    "paperswithcode.com",
    "semanticscholar.org",
    "pubmed.gov",
    "sciencedirect.com",
    "link.springer.com",
    "ieeexplore.ieee.org",
    "ams.org/mathscinet",
    "chemrxiv.org",
    "psyarxiv.com",
    "socarxiv.org",
    "osf.io/preprints/socarxiv"
    "engrxiv.org",
    "ssrn.com",
    "philpapers.org"
    "nature.com"
    "jstor.org"
    "sciencemag.org"
    "researchgate.net"
    "frontiersin.org"
    "springer.com"
    "wiley.com"
    "tandfonline.com",
    "rsc.org",
    "projecteuclid.org",
    "zbmath.org",
    "journals.sagepub.com",
    "journals.aps.org",
    "journals.plos.org",
    "journals.elsevier.com",
    "journals.cambridge.org",
    "journals.uchicago.edu",


]



def is_science_site(url):
    return any(site in url for site in science_sites)


import re


def count_science_urls(text):
    # Regular expression to find URLs
    url_pattern = r'(https?://(?:www\.)?[^\s]+)'

    # Find all URLs in the text
    urls = re.findall(url_pattern, text)

    urls = [url.strip() for url in urls]

    urls = list(set(urls))

    # Count science site URLs
    count = sum(1 for url in urls if is_science_site(url))

    return count

def generate_science_site_query(search_terms):
    site_query = " OR ".join([f"site:{site}" for site in science_sites])
    return f"{site_query} {search_terms}"


def search_post_processing(query, results, source, only_science_sites=False, only_pdf=False):
    seen_titles = set()
    seen_links = set()
    dedup_results = []
    for r in results:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3",
                                                                                                         '').replace(
            "v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        if only_science_sites is not None and only_science_sites and not is_science_site(link):
            continue
        if only_science_sites is not None and not only_science_sites and is_science_site(link):
            continue
        if only_pdf is not None and not only_pdf and "pdf" in link:
            continue

        try:
            r["citations"] = get_citation_count(r)
        except:
            try:
                r["citations"] = int(r.get("inline_links", {}).get("cited_by", {}).get("total", "-1"))
            except:
                r["citations"] = None
        try:
            r["year"] = get_year(r)
        except:
            try:
                r["year"] = re.search(r'(\d{4})', r.get("publication_info", {}).get("summary", ""))
            except:
                r["year"] = None
        r['query'] = query
        _ = r.pop("rich_snippet", None)
        r['source'] = source
        description = r.get("description", r.get("snippet", ""))
        r["description"] = description
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    return dedup_results
@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def bingapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    from datetime import datetime, timedelta
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365*3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None
        date_string = ''

    from langchain_community.utilities.bing_search import BingSearchAPIWrapper
    search = BingSearchAPIWrapper(bing_subscription_key=key, bing_search_url="https://api.bing.microsoft.com/v7.0/search")
    
    pre_query = query
    after_string = f"after:{date_string}" if now and not only_pdf and not only_science_sites else ""
    search_pdf = " filetype:pdf" if only_pdf else ""
    if only_science_sites is None:
        site_string = " "
    elif only_science_sites:
        site_string = " (site:arxiv.org OR site:openreview.net) "
    elif not only_science_sites:
        site_string = " -site:arxiv.org AND -site:openreview.net "
    else:
        site_string = " "
    og_query = query
    no_after_query = f"{query}{site_string}{search_pdf}"
    query = f"{query}{site_string}{after_string}{search_pdf}"
    if use_original_query:
        query = str(og_query)
    more_res = None
    if num > 10:
        more_res = get_async_future(search.results, query, 30)
    results = search.results(query, num)
    expected_res_length = max(num, 10)
    if num > 10:
        results.extend(more_res.result() if more_res is not None and more_res.exception() is None else [])
    if len(results) < expected_res_length:
        results.extend(search.results(no_after_query, num))
    if len(results) < expected_res_length:
        results.extend(search.results(og_query, num))
    if len(results) < expected_res_length:
        results.extend(search.results(og_query, num * 2))
    dedup_results = search_post_processing(pre_query, results, "bing", only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(f"Called BING API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results
@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def brightdata_google_serp(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    import requests

    from datetime import datetime, timedelta
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365 * 3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None

    pre_query = query
    after_string = f"after:{date_string}" if now else ""
    search_pdf = " filetype:pdf" if only_pdf else ""
    if only_science_sites is None:
        site_string = " "
    elif only_science_sites:
        # site:arxiv.org OR site:openreview.net OR site:arxiv-vanity.com OR site:arxiv-sanity.com OR site:bioRxiv.org OR site:medrxiv.org OR site:aclweb.org
        site_string = " (site:arxiv.org OR site:openreview.net OR site:arxiv-vanity.com OR site:arxiv-sanity.com OR site:bioRxiv.org OR site:medrxiv.org OR site:aclweb.org) "
    elif not only_science_sites:
        site_string = " -site:arxiv.org AND -site:openreview.net "
    og_query = query
    no_after_query = f"{query}{site_string}{search_pdf}"
    query = f"{query}{site_string}{after_string}{search_pdf}"
    if use_original_query:
        query = str(og_query)
    expected_res_length = max(num, 10)
    def search_google(query, num=expected_res_length, start=0, gl="us"):
        # URL encode the query
        encoded_query = requests.utils.quote(query)
        # Set up the URL
        url = f"https://www.google.com/search?q={encoded_query}&gl={gl}&num={num}&start={start}&brd_json=1"
        # Set up the proxy
        proxy = {
            'https': os.getenv("BRIGHTDATA_SERP_API_PROXY", key)
        }
        # Make the request
        response = requests.get(url, proxies=proxy, verify=False)
        try:
            return json.loads(response.text)["organic"]
        except Exception as e:
            logger.error(f"Error in brightdata_google_serp with query = {query} and response = {response.text} and error = {str(e)}\n{traceback.format_exc()}")
            return []

    more_results_future = None
    if expected_res_length > 10:
        more_results_future = get_async_future(search_google, query, 20, start=20, gl="uk")
        # more_results_future = get_async_future(search_google, og_query, 20, start=20, gl="fr")
    results = search_google(query)
    # title , description
    if len(results) < expected_res_length:
        results.extend(more_results_future.result() if more_results_future is not None and more_results_future.exception() is None else [])
    if len(results) < expected_res_length:
        results.extend(search_google(og_query, 20, start=20, gl="fr"))
    if len(results) < expected_res_length:
        results.extend(search_google(f"{query}{site_string}{after_string}{search_pdf}", 20, start=20, gl="fr"))
    for r in results:
        _ = r.pop("image", None)
        _ = r.pop("image_alt", None)
        _ = r.pop("image_url", None)
        _ = r.pop("global_rank", None)
        _ = r.pop("image_base64", None)
    dedup_results = search_post_processing(pre_query, results, "brightdata_google", only_science_sites=only_science_sites, only_pdf=only_pdf)
    return dedup_results

@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def googleapi_v2(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    from datetime import datetime, timedelta
    num = max(num, 10)

    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365 * 3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None

    cse_id = key["cx"]
    google_api_key = key["api_key"]

    pre_query = query
    after_string = f"after:{date_string}" if now else ""
    search_pdf = " filetype:pdf" if only_pdf else ""

    if only_science_sites is None:
        site_string = " "
    elif only_science_sites:
        site_string = " (site:arxiv.org OR site:openreview.net OR site:arxiv-vanity.com OR site:arxiv-sanity.com OR site:bioRxiv.org OR site:medrxiv.org OR site:aclweb.org) "
    elif not only_science_sites:
        site_string = " -site:arxiv.org AND -site:openreview.net "

    og_query = query
    no_after_query = f"{query}{site_string}{search_pdf}"
    query = f"{query}{site_string}{after_string}{search_pdf}"
    if use_original_query:
        query = str(og_query)

    expected_res_length = max(num, 10)
    results = []

    if expected_res_length > 10:
        more_results_future = get_async_future(google_search, query, cse_id, google_api_key, num=20, filter=1, start=20)
    # Perform initial search
    initial_results = google_search(query, cse_id, google_api_key, num=min(num, 10), filter=1, start=0)
    # title snippet
    if initial_results:
        results.extend(initial_results)

        # Perform additional searches if needed
    if len(results) < expected_res_length:
        additional_results = more_results_future.result() if more_results_future is not None and more_results_future.exception() is None else []
        if additional_results:
            results.extend(additional_results)

    if len(results) < expected_res_length:
        additional_results = google_search(query, cse_id, google_api_key, num=min(num, 10), filter=1,
                                           start=len(results))
        if additional_results:
            results.extend(additional_results)

    if len(results) < expected_res_length:
        no_after_results = google_search(no_after_query, cse_id, google_api_key, num=min(num, 10), filter=1, start=0)
        if no_after_results:
            results.extend(no_after_results)

    if len(results) < expected_res_length:
        no_after_additional_results = google_search(no_after_query, cse_id, google_api_key, num=min(num, 10), filter=1,
                                                    start=len(results))
        if no_after_additional_results:
            results.extend(no_after_additional_results)

    if len(results) < expected_res_length:
        og_query_results = google_search(og_query, cse_id, google_api_key, num=min(num, 10), filter=1,
                                         start=len(results))
        if og_query_results:
            results.extend(og_query_results)

    dedup_results = search_post_processing(pre_query, results, "google", only_science_sites=only_science_sites,
                                           only_pdf=only_pdf)
    logger.debug(
        f"Called GOOGLE API with args = {query}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")

    return dedup_results


@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def serpapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    from datetime import datetime, timedelta
    import requests
    
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365*3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None

    
    location = random.sample(["New Delhi", "New York", "London", "Berlin", "Sydney", "Tokyo", "Seattle", "Amsterdam", "Paris"], 1)[0]
    gl = random.sample(["us", "uk", "fr", "ar", "ci", "dk", "ec", "gf", "hk", "is", "in", "id", "pe", "ph", "pt", "pl"], 1)[0]
    location_2 = random.sample(["New Delhi", "New York", "London", "Berlin", "Sydney", "Tokyo", "Seattle", "Amsterdam", "Paris"], 1)[0]
    gl_2 = random.sample(["us", "uk", "fr", "ar", "ci", "dk", "ec", "gf", "hk", "is", "in", "id", "pe", "ph", "pt", "pl"], 1)[0]
    location_3 = random.sample(["New Delhi", "New York", "London", "Berlin", "Sydney", "Tokyo", "Seattle", "Amsterdam", "Paris"], 1)[
        0]
    gl_3 = random.sample(["us", "uk", "fr", "ar", "ci", "dk", "ec", "gf", "hk", "is", "in", "id", "pe", "ph", "pt", "pl"], 1)[
        0]
    # format the date as YYYY-MM-DD
    
    url = "https://serpapi.com/search"
    pre_query = query
    after_string = f"after:{date_string}" if now else ""
    search_pdf = " filetype:pdf" if only_pdf else ""
    if only_science_sites is None:
        site_string = " "
    elif only_science_sites:
        site_string = " (site:arxiv.org OR site:openreview.net) "
    elif not only_science_sites:
        site_string = " -site:arxiv.org AND -site:openreview.net "
    og_query = query
    no_after_query = f"{query}{site_string}{search_pdf}"
    query = f"{query}{site_string}{after_string}{search_pdf}"
    if use_original_query:
        query = str(og_query)
    params = {
       "q": query,
       "api_key": key,
       "num": num,
       "no_cache": False,
        "location": location,
        "gl": gl,
       }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        logger.error(f"Error in SERP API with query = {query} and response = {response.text}")
        raise Exception(f"Error in SERP API with query = {query} and response = {response.text}")
    assert response.status_code == 200
    rjs = response.json()
    if "organic_results" in rjs:
        results = rjs["organic_results"]
    else:
        return []
    expected_res_length = max(num, 10)
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": no_after_query, "api_key": key, "num": min(num, 10), "no_cache": False, "location": location, "gl": gl}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num, 10), "no_cache": False, "location": location_2, "gl": gl_2}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num, 10), "no_cache": False, "location": location_3, "gl": gl_3}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    dedup_results = search_post_processing(pre_query, results, "serpapi", only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(f"Called SERP API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results


@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def gscholarapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    from datetime import datetime, timedelta
    import requests

    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365 * 3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None
    # format the date as YYYY-MM-DD

    url = "https://serpapi.com/search"
    pre_query = query
    search_pdf = " filetype:pdf" if only_pdf else ""
    site_string = ""
    og_query = query
    query = f"{query}{search_pdf}"
    if use_original_query:
        query = str(og_query)
    params = {
        "q": query,
        "api_key": key,
        "num": num,
        "engine": "google_scholar",
        "no_cache": False,
    }
    response = requests.get(url, params=params)
    rjs = response.json()
    if "organic_results" in rjs:
        results = rjs["organic_results"]
    else:
        return []
    expected_res_length = max(num, 10)
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num - 10, 10), "no_cache": False, "engine": "google_scholar"}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num, 10), "no_cache": True, "engine": "google_scholar"}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    dedup_results = search_post_processing(pre_query, results, "gscholar", only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(
        f"Called SERP Google Scholar API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    return dedup_results


@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def gscholarapi_published(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True, use_original_query=False):
    from datetime import datetime, timedelta
    import requests

    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365 * 3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None
    # format the date as YYYY-MM-DD

    url = "https://serpapi.com/search"
    pre_query = query
    search_pdf = " filetype:pdf" if only_pdf else ""
    site_string = ""
    og_query = query
    query = f"{query}{search_pdf} {gscholar_query_string}"
    params = {
        "q": query,
        "api_key": key,
        "num": num,
        "engine": "google_scholar",
        "no_cache": False,
    }
    response = requests.get(url, params=params)
    rjs = response.json()
    if "organic_results" in rjs:
        results = rjs["organic_results"]
    else:
        return []
    expected_res_length = max(num, 10)
    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num - 10, 10), "no_cache": False, "engine": "google_scholar"}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])

    if len(results) < expected_res_length:
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": max(num , 10), "no_cache": True, "engine": "google_scholar"}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    dedup_results = search_post_processing(pre_query, results, "gscholar_published", only_science_sites=None, only_pdf=only_pdf)
    logger.debug(
        f"Called SERP Google Scholar API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    return dedup_results

# TODO: Add caching
from web_scraping import web_scrape_page, soup_html_parser, soup_html_parser_fast_v3, fetch_content_brightdata_html, \
    send_request_zenrows_html


def get_page_content(link, playwright_cdp_link=None, timeout=10):
    text = ''
    title = ''
    try:
        from playwright.sync_api import sync_playwright
        playwright_enabled = True
        with sync_playwright() as p:
            if playwright_cdp_link is not None and isinstance(playwright_cdp_link, str):
                try:
                    browser = p.chromium.connect_over_cdp(playwright_cdp_link)
                except Exception as e:
                    logger.error(f"Error connecting to cdp link {playwright_cdp_link} with error {e}")
                    browser = p.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials"])
            else:
                browser = p.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials"])
            page = browser.new_page(ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            url = link
            page.goto(url)
            # example_page = browser.new_page(ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            # example_page.goto("https://www.example.com/")
            
            try:
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
                # page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
                page.wait_for_selector('body', timeout=timeout * 1000)
                page.wait_for_function("() => typeof(Readability) !== 'undefined' && document.readyState === 'complete'", timeout=10000)
                while page.evaluate('document.readyState') != 'complete':
                    time.sleep(0.5)
                result = page.evaluate("""(function execute(){var article = new Readability(document).parse();return article})()""")
            except Exception as e:
                # TODO: use playwright response modify https://playwright.dev/python/docs/network#modify-responses instead of example.com
                logger.warning(f"Trying playwright for link {link} after playwright failed with exception = {str(e)}")
                # traceback.print_exc()
                # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
                page.wait_for_selector('body', timeout=timeout * 1000)
                while page.evaluate('document.readyState') != 'complete':
                    time.sleep(0.5)
                init_html = page.evaluate("""(function e(){return document.body.innerHTML})()""")
                init_title = page.evaluate("""(function e(){return document.title})()""")
                # page = example_page
                page.goto("https://www.example.com/")
                page.evaluate(f"""text=>document.body.innerHTML=text""", init_html)
                page.evaluate(f"""text=>document.title=text""", init_title)
                logger.debug(f"Loaded html and title into page with example.com as url")
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
                page.wait_for_function("() => typeof(Readability) !== 'undefined' && document.readyState === 'complete'", timeout=10000)
                # page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
                page.wait_for_selector('body', timeout=timeout*1000)
                while page.evaluate('document.readyState') != 'complete':
                    time.sleep(0.5)
                result = page.evaluate("""(function execute(){var article = new Readability(document).parse();return article})()""")
            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])
                
            try:
                browser.close()
            except:
                pass
    except Exception as e:
        # traceback.print_exc()
        try:
            logger.debug(f"Trying selenium for link {link} after playwright failed with exception = {str(e)})")
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.wait import WebDriverWait
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.support import expected_conditions as EC
            options = webdriver.ChromeOptions()
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--headless')
            driver = webdriver.Chrome(options=options)
            driver.get(link)
            add_readability_to_selenium = '''
                    function myFunction() {
                        if (document.readyState === 'complete') {
                            var script = document.createElement('script');
                            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
                            document.head.appendChild(script);

                            // var script = document.createElement('script');
                            // script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js';
                            // document.head.appendChild(script);
                        } else {
                            setTimeout(myFunction, 1000);
                        }
                    }

                    myFunction();
                '''
            try:
                driver.execute_script(add_readability_to_selenium)
                while driver.execute_script('return document.readyState;') != 'complete':
                    time.sleep(0.5)
                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined' && document.readyState === 'complete';""")
                WebDriverWait(driver, timeout=timeout).until(document_initialised)
                result = driver.execute_script("""var article = new Readability(document).parse();return article""")
            except Exception as e:
                traceback.print_exc()
                # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
                init_title = driver.execute_script("""return document.title;""")
                init_html = driver.execute_script("""return document.body.innerHTML;""")
                driver.get("https://www.example.com/")
                logger.debug(f"Loaded html and title into page with example.com as url")
                driver.execute_script("""document.body.innerHTML=arguments[0]""", init_html)
                driver.execute_script("""document.title=arguments[0]""", init_title)
                driver.execute_script(add_readability_to_selenium)
                while driver.execute_script('return document.readyState;') != 'complete':
                    time.sleep(0.5)
                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined' && document.readyState === 'complete';""")
                WebDriverWait(driver, timeout=timeout).until(document_initialised)
                result = driver.execute_script("""var article = new Readability(document).parse();return article""")
                
            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])
            try:
                driver.close()
            except:
                pass
        except Exception as e:
            if 'driver' in locals():
                try:
                    driver.close()
                except:
                    pass
        finally:
            if 'driver' in locals():
                try:
                    driver.close()
                except:
                    pass
    finally:
        if "browser" in locals():
            try:
                browser.close()
            except:
                pass
    return {"text": text, "title": title}
# @typed_memoize(cache, str, int, tuple, bool)
def freePDFReader(url, page_ranges=None):
    from langchain_community.document_loaders import PyPDFLoader, PyMuPDFLoader
    from pathlib import Path
    if not os.path.isfile(url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        r = requests.get(url, verify=False, headers=headers)

        if r.status_code != 200:
            raise ValueError(
                "Check the url of your file; returned status code %s"
                % r.status_code
            )

        temp_dir = tempfile.TemporaryDirectory()
        temp_pdf = Path(temp_dir.name) / "tmp.pdf"
        with open(temp_pdf, mode="wb") as f:
            f.write(r.content)
        url = str(temp_pdf)
    loader = PyMuPDFLoader(url)
    pages = loader.load_and_split()
    if page_ranges:
        start, end = page_ranges.split("-")
        start = int(start) - 1
        end = int(end) - 1
        " ".join([pages[i].page_content for i in range(start, end+1)])
    return " ".join([p.page_content for p in pages])


class PDFtoMarkdown:
    def __init__(self, keys, file_path, **kwargs):
        self.file_path = file_path
        from pathlib import Path
        self.file_path = file_path
        self.keys = keys

        if "~" in self.file_path:
            self.file_path = os.path.expanduser(self.file_path)

        # If the file is a web path, download it to a temporary file, and use that
        if not os.path.isfile(self.file_path) and self._is_valid_url(self.file_path):
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
            r = requests.get(self.file_path, verify=False, headers=headers)

            if r.status_code != 200:
                raise ValueError(
                    "Check the url of your file; returned status code %s"
                    % r.status_code
                )

            self.temp_dir = tempfile.TemporaryDirectory()
            temp_pdf = Path(self.temp_dir.name) / "tmp.pdf"
            with open(temp_pdf, mode="wb") as f:
                f.write(r.content)
            self.file_path = str(temp_pdf)



        self.page_ranges = None
        if "page_ranges" in kwargs and kwargs["page_ranges"] is not None:
            self.page_ranges = []
            page_ranges = kwargs["page_ranges"]
            # page_ranges = page_ranges.split(",") # We need to split on comma and semi-colon both so use regex
            page_ranges = re.split(r"[,;]", page_ranges)

            for pr in page_ranges:
                pr = pr.split("-")
                pr = [int(i.strip()) for i in pr]
                if len(pr) == 2:
                    # self.page_ranges = (int(page_ranges[0]), int(page_ranges[1]))
                    self.page_ranges.extend(list((range(int(pr[0]), int(pr[1]) + 1))))
                else:
                    self.page_ranges.append(int(pr[0]))



    def _is_valid_url(self, url):
        import re
        regex = re.compile(
            r'^(?:http|ftp)s?://'  # http:// or https://
            # domain...
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}|'
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )
        return re.match(regex, url)

    def _is_valid_pdf(self, file_path):
        return file_path.endswith(".pdf")

    def _is_valid_web_pdf(self, url):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        r = requests.get(url, verify=False, headers=headers)
        return r.headers.get("content-type") == "application/pdf"


    def ocr_efficient_prompt(self, text):
        system = f"""
You are given a pdf file text and the corresponding image of the pdf page. Please look at the image given carefully and convert the text in the image to markdown. 
You can use the text given in the pdf to help you with the text in the image. 
Remember to give all details, everything in the image and the pdf file text by reading the image carefully and translate to markdown format. Use markdown formatting to make the text more readable.

Guidelines:
- Give all details by reading the image carefully and translate to markdown format. Use markdown formatting to make the text more readable. 
- Output tables in markdown as well.
- If there are any diagrams / images / photos within the page then output their detailed description, any data, numbers the images say, their usage within the page and any insights the images convey in place of the image in your output.
- For tables, check if all the columns, headers, headings, text values are correct. Check tables, rows, table headers and their formatting as well. Format tables correctly. 
- In tables take care to create empty cells as well so that columns are correctly aligned with the headers.
- After converting the page fully to markdown you will finally you will write a summary of the page.
- Certain images may have graphs, charts, data plots etc. You need to describe the important data, numbers, and mainly the insights the images convey in place of the image in your output.
- The page text and page image can be noisy and may not be accurate. Please use your best judgement to output correct markdown.


Your output should follow the below xml like format.
<pdf_page_content_in_markdown> {{Content of the page using page image and page text following above guidelines.}} </pdf_page_content_in_markdown>
<pdf_page_summary> {{Summary of the page}} </pdf_page_summary>
""".strip()
        prompt = f"""{system}
You are given a pdf file text and the corresponding image of the pdf page. Please look at the image given carefully and convert the text in the image to markdown.
Page text (pdf file text) from the pdf: 
'''
{text}
'''

Your output should follow the below xml like format.
<pdf_page_content_in_markdown> {{Content of the page using page image and page text with every single detail following above guidelines.}} </pdf_page_content_in_markdown>
<pdf_page_summary> {{Summary of the page}} </pdf_page_summary>

Write your markdown content and page summary below in the above xml like format:
"""
        return system, prompt


    def ocr_checker_corrector_prompt(self, page_text, past_content_1, past_summary_1, past_content_2, past_summary_2):
        system = f"""
You were given a pdf file text and the corresponding image of the pdf page. You were asked to convert the text in the image to markdown. 
We performed two iterations and got two set of results. You need to check the results and correct them if needed. And then give a final corrected markdown output result.
The page text and page image can be noisy and may not be accurate. So you need to correct the output from previous iterations if needed.
Check if all the columns, headers, headings, text values are correct. Check tables, rows, table headers and their formatting as well.
In tables take care to create empty cells as well so that columns are correctly aligned with the headers.
The guidelines given for pdf text and image to markdown conversion is listed below.

'''
Guidelines:
- Give all details by reading the image carefully and translate to markdown format. Use markdown formatting to make the text more readable. 
- Output tables in markdown as well.
- If there are any diagrams / images / photos within the page then output their detailed description, any data, numbers the images say, their usage within the page and any insights the images convey in place of the image in your output.
- For tables, check if all the columns, headers, headings, text values are correct. Check tables, rows, table headers and their formatting as well. Format tables correctly. 
- In tables take care to create empty cells as well so that columns are correctly aligned with the headers.
- After converting the page fully to markdown you will finally you will write a summary of the page.
- Certain images may have graphs, charts, data plots etc. You need to describe the important data, numbers, and mainly the insights the images convey in place of the image in your output.
- The page text and page image can be noisy and may not be accurate. Please use your best judgement to output correct markdown.
'''

Your output should follow the below xml like format.
<corrections>
    <correction> {{Correction of the output from previous iterations of the page}} </correction>
    <correction> {{Another Correction of the output from previous iterations of the page}} </correction>
    <correction> {{Correction of the page}} </correction>
</corrections>
<pdf_page_content_in_markdown> {{Content of the page using page image and page text with every single detail following above guidelines.}} </pdf_page_content_in_markdown>
<pdf_page_summary> {{Detailed summary and insights  of the page combining and correcting the previous summaries and taking the page image and text into account}} </pdf_page_summary>

Remember to give all details, everything in the image and the pdf file text by reading the image carefully and translate to markdown format. Use markdown formatting to make the text more readable.
Remember the <corrections> tag can be empty if no corrections need to be made.
""".strip()

        prompt = f"""{system}
        
Page Text (pdf file text) from the pdf:
'''
{page_text}
'''

Past Iteration 1 Content:
'''
{past_content_1}
'''

Past Iteration 1 Summary:
'''
{past_summary_1}
'''

Past Iteration 2 Content:
'''
{past_content_2}
'''

Past Iteration 2 Summary:
'''
{past_summary_2}
'''

Your output should follow the below xml like format.
<corrections>
    <correction> {{Correction of the output from previous iterations of the page}} </correction>
    <correction> {{Another Correction of the output from previous iterations of the page}} </correction>
    <correction> {{Correction of the page}} </correction>
</corrections>
<pdf_page_content_in_markdown> {{Content of the page using page image and page text with every single detail following above guidelines.}} </pdf_page_content_in_markdown>
<pdf_page_summary> {{Detailed summary and insights  of the page combining and correcting the previous summaries and taking the page image and text into account}} </pdf_page_summary>

Remember to give all details, everything in the image and the pdf file text by reading the image carefully and correcting any mistakes of past iterations.
Write your corrected markdown content (using the image and pdf file text) and page summary below in the above xml like format:
"""
        return system, prompt

    def get_one_page(self, doc, page_number):
        page = doc.load_page(page_number)
        text = page.get_text()
        pix = page.get_pixmap(dpi=400)
        return text, pix

    def process_one_page(self, doc, page_number) -> Tuple[str, str]:
        page_text, page_image = self.get_one_page(doc, page_number)
        # Make call to flash
        # Make call to flash and haiku with double outputs for correction
        temp_dir = tempfile.TemporaryDirectory()
        from pathlib import Path
        from PIL import Image
        uuid = str(uuid4())
        temp_path = Path(temp_dir.name) / f"tmp-{uuid}.png"
        image_file_path = str(temp_path)

        page_image.save(image_file_path)
        # Get file size of image_file_path
        import os
        mb_size_1 = os.path.getsize(image_file_path) / 1_000

        im = Image.open(image_file_path)
        im = im.convert('RGB')
        image_file_path = str(Path(temp_dir.name) / f"tmp-{uuid}.jpg")
        im.save(image_file_path, quality=90)
        mb_size_2 = os.path.getsize(image_file_path) / 1_000
        print(mb_size_1, mb_size_2)
        llm1 = CallLLm(self.keys, model_name="google/gemini-pro-1.5")
        llm2 = CallLLm(self.keys, model_name="gpt-4o")
        system, prompt = self.ocr_efficient_prompt(page_text)
        llm1_res = get_async_future(llm1, prompt, images=[image_file_path], system=system)
        llm2_res = get_async_future(llm2, prompt, images=[image_file_path], system=system)
        llm1_res = sleep_and_get_future_result(llm1_res)
        llm2_res = sleep_and_get_future_result(llm2_res)

        page_content_1 = llm1_res.split("</pdf_page_content_in_markdown>")[0].split("<pdf_page_content_in_markdown>")[-1]
        page_summary_1 = llm1_res.split("</pdf_page_summary>")[0].split("<pdf_page_summary>")[-1]
        page_content_2 = llm2_res.split("</pdf_page_content_in_markdown>")[0].split("<pdf_page_content_in_markdown>")[-1]
        page_summary_2 = llm2_res.split("</pdf_page_summary>")[0].split("<pdf_page_summary>")[-1]

        system, prompt = self.ocr_checker_corrector_prompt(page_text, page_content_1, page_summary_1, page_content_2, page_summary_2)
        final_res = llm2(prompt, images=[image_file_path], system=system)
        final_content = final_res.split("</pdf_page_content_in_markdown>")[0].split("<pdf_page_content_in_markdown>")[-1]
        final_summary = final_res.split("</pdf_page_summary>")[0].split("<pdf_page_summary>")[-1]

        return final_summary, final_content


    def convert_to_md(self) -> Tuple[List[str], List[str], str, str]:
        import fitz
        from fitz.fitz import Document
        doc: Document = fitz.open(self.file_path)
        num_pages = len(doc)
        full_md_text = ""
        if self.page_ranges:
            pages = self.page_ranges
        else:
            pages = range(num_pages)
        # for page_number in pages:
        #     md_text = self.process_one_page(doc, page_number)
        #     full_md_text += ("\n<page_break>\n" + md_text)

        # convert above code to parallel version using threadpool. Also add exception handling and one time retry which retries after sleep.
        with ThreadPoolExecutor(max_workers=4) as executor:
            # results = list(executor.map(self.process_one_page, [doc]*len(pages), pages))
            # use executor.submit instead of executor.map to get exceptions
            futures = [executor.submit(self.process_one_page, doc, page_number) for page_number in pages]
            # Check for exception and retry
            results = []
            for page_number, future in zip(pages, futures):
                try:
                    r = sleep_and_get_future_result(future)
                    results.append(r)
                except Exception as e:
                    # Retry after sleep
                    time.sleep(1)
                    r = self.process_one_page(doc, page_number)
                    results.append(r)
        summaries, texts = zip(*results)
        full_md_text = "\n<page_break>\n".join(texts)
        full_md_summary = "\n<page_break>\n".join(summaries)
        return summaries, texts, full_md_text, full_md_summary


    def __call__(self, *args, **kwargs):
        return self.convert_to_md()


class CustomPDFLoader(MathpixPDFLoader):
    def __init__(self, file_path, processed_file_format: str = "mmd",
        max_wait_time_seconds: int = 500,
        should_clean_pdf: bool = False,
        **kwargs):
        from pathlib import Path
        self.file_path = file_path
        self.web_path = None
        if "~" in self.file_path:
            self.file_path = os.path.expanduser(self.file_path)

        # If the file is a web path, download it to a temporary file, and use that
        if not os.path.isfile(self.file_path) and self._is_valid_url(self.file_path):
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
            r = requests.get(self.file_path, verify=False, headers=headers)

            if r.status_code != 200:
                raise ValueError(
                    "Check the url of your file; returned status code %s"
                    % r.status_code
                )

            self.web_path = self.file_path
            self.temp_dir = tempfile.TemporaryDirectory()
            temp_pdf = Path(self.temp_dir.name) / "tmp.pdf"
            with open(temp_pdf, mode="wb") as f:
                f.write(r.content)
            self.file_path = str(temp_pdf)
        self.mathpix_api_key = get_from_dict_or_env(
            kwargs, "mathpix_api_key", "MATHPIX_API_KEY"
        )
        self.mathpix_api_id = get_from_dict_or_env(
            kwargs, "mathpix_api_id", "MATHPIX_API_ID"
        )
        self.processed_file_format = processed_file_format
        self.max_wait_time_seconds = max_wait_time_seconds
        self.should_clean_pdf = should_clean_pdf
        
        self.options = {"rm_fonts": True, 
                   "enable_tables_fallback":True}
        if self.processed_file_format != "mmd":
            self.options["conversion_formats"] = {self.processed_file_format: True},
        if "page_ranges" in kwargs and kwargs["page_ranges"] is not None:
            self.options["page_ranges"] = kwargs["page_ranges"]
        
    @property
    def data(self) -> dict:
        if os.path.exists(self.file_path):
            options = dict(**self.options)
        else:
            options = dict(url=self.file_path, **self.options)
        return {"options_json": json.dumps(options)}
    def clean_pdf(self, contents: str) -> str:
        contents = "\n".join(
            [line for line in contents.split("\n") if not line.startswith("![]")]
        )
        # replace the "\" slash that Mathpix adds to escape $, %, (, etc.
        contents = (
            contents.replace(r"\$", "$")
            .replace(r"\%", "%")
            .replace(r"\(", "(")
            .replace(r"\)", ")")
        )
        return contents
    

class PDFReaderTool:
    def __init__(self, keys):
        self.mathpix_api_id=keys['mathpixId']
        self.mathpix_api_key=keys['mathpixKey']
    # @typed_memoize(cache, str, int, tuple, bool)
    def __call__(self, url, page_ranges=None):
        if self.mathpix_api_id is not None and self.mathpix_api_key is not None:
            
            loader = CustomPDFLoader(url, should_clean_pdf=True,
                              mathpix_api_id=self.mathpix_api_id, 
                              mathpix_api_key=self.mathpix_api_key, 
                              processed_file_format="mmd", page_ranges=page_ranges)
            data = loader.load()
            return data[0].page_content
        else:
            return freePDFReader(url, page_ranges)

@CacheResults(cache=FixedSizeFIFODict(100), dtype_filters=[str, int, tuple, bool], enabled=False)
def get_semantic_scholar_url_from_arxiv_url(arxiv_url):
    import requests
    arxiv_id = arxiv_url.split("/")[-1].split(".")[0]
    semantic_scholar_api_url = f"https://api.semanticscholar.org/v1/paper/arXiv:{arxiv_id}"
    response = requests.get(semantic_scholar_api_url)
    if response.status_code == 200:
        semantic_scholar_id = response.json()["paperId"]
        semantic_url = f"https://www.semanticscholar.org/paper/{semantic_scholar_id}"
        return semantic_url
    raise ValueError(f"Couldn't parse arxiv url {arxiv_url}")

@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def get_paper_details_from_semantic_scholar(arxiv_url):
    print(f"get_paper_details_from_semantic_scholar with {arxiv_url}")
    arxiv_id = arxiv_url.split("/")[-1].replace(".pdf", '').strip()
    from semanticscholar import SemanticScholar
    from semanticscholar.Paper import Paper

    sch = SemanticScholar()
    paper = sch.get_paper(f"ARXIV:{arxiv_id}", fields=list(set(Paper.FIELDS) - {'authors.aliases'}))
    time_logger.info(f"get_paper_details_from_semantic_scholar with {arxiv_url} and got details")
    return paper

def web_search_part1_mock(context, doc_source, doc_context, api_keys, year_month=None,
                     previous_answer=None, previous_search_results=None, extra_queries=None,
                     gscholar=False, provide_detailed_answers=False, start_time=None, web_search_tmp_marker_name=None,):
    query_strings = ["Tell me about this."]
    result_context = context
    links = [
        "https://towardsdatascience.com/top-5-deep-learning-frameworks-to-watch-in-2021-and-why-tensorflow-98d8d6667351",
        "https://www.projectpro.io/article/pytorch-vs-tensorflow-2021-a-head-to-head-comparison/416",
        "https://www.knowledgehut.com/blog/data-science/pytorch-vs-tensorflow",
        "https://ulimum.net/2023/05/08/mxnet-vs-tensorflow-vs-pytorch-which-is-best-for-deep/",
        "https://medium.com/@splitwireml/pytorch-vs-tensorflow-a-hands-on-comparison-febc845c0a00",
        "https://www.nvidia.com/en-us/glossary/mxnet/",
        "https://365datascience.com/trending/deep-learning-frameworks/",
        "https://www.scaler.com/topics/tensorflow/mxnet-vs-tensorflow/",
        "https://www.tutorialsfreak.com/ai-tutorial/deep-learning-frameworks",
        "https://www.freecodecamp.org/news/deep-learning-frameworks-compared-mxnet-vs-tensorflow-vs-dl4j-vs-pytorch/",
        "https://www.educba.com/mxnet-vs-tensorflow/",
        "https://julsimon.medium.com/keras-shoot-out-tensorflow-vs-mxnet-51ae2b30a9c0",
        "https://medium.com/syncedreview/tensorflow-pytorch-or-mxnet-a-comprehensive-evaluation-on-nlp-cv-tasks-with-titan-rtx-cdf816fc3935",
        "https://www.reddit.com/r/MachineLearning/comments/gvqoh8/use_of_mxnet_gluoncv_vs_tensorflow_for_computer/",
        "https://github.com/sreenivasanramesh/sreenivasanramesh.github.io/blob/master/_posts/2019-12-28-tensorflow-vs-mxnet.markdown",
        "https://developer.ibm.com/articles/compare-deep-learning-frameworks/",
        "https://www.projectpro.io/article/machine-learning-frameworks/509",
        "https://developer.nvidia.com/deep-learning-frameworks",
        "https://in.indeed.com/career-advice/career-development/what-is-tensorflow",
        "https://www.knowledgehut.com/blog/data-science/pytorch-vs-tensorflow",
        "https://mxnet.apache.org/versions/1.6/api/python/docs/tutorials/getting-started/to-mxnet/pytorch.html",
        "https://stackoverflow.com/questions/61116190/what-are-all-the-formats-to-save-machine-learning-model-in-scikit-learn-keras",
        "https://www.tensorflow.org/tutorials/images",
        "https://mxnet.apache.org/",
        "https://cv.gluon.ai/contents.html",
        "https://hackernoon.com/object-detection-frameworks-that-will-dominate-2023-and-beyond",
        "https://iamitcohen.medium.com/a-comparative-analysis-of-tensorflow-pytorch-mxnet-and-scikit-learn-2072fe566df7",
        "https://towardsdatascience.com/not-just-pytorch-and-tensorflow-4-other-deep-learning-libraries-you-should-lnow-a72cf8be0814",
        "https://analyticsindiamag.com/can-mxnet-stand-up-to-tensorflow-pytorch/",


    ]
    query = query_strings[0]
    title = "Deep Learning Frameworks"

    yield {"type": "query", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month,
           "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers}
    full_queue = []
    for iqx, link in enumerate(links):
        full_queue.append(
            {"query": query, "title": title, "link": link, "context": result_context, "type": "result", "rank": iqx})
        yield {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
               "rank": iqx, "start_time": start_time}
    yield {"type": "end", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month,
           "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers, "full_results": full_queue}

forbidden_links = ["youtube.com", "twitter.com", "facebook.com", "instagram.com",
                   "pinterest.com", "tiktok.com", "snapchat.com",
                   "whatsapp.com", "telegram.com", "discord.com",
                   # paid science sites
                "https://ieeexplore.ieee.org", "https://www.sciencedirect.com", "https://www.springer.com", "https://www.jstor.org",
                   # "t.me", "wa.me", "m.me", "fb.com",
                   # "bit.ly", "tinyurl.com", "goo.gl",
                   # "ow.ly", "buff.ly", "dlvr.it", "ift.tt", "t.co", "lnkd.in", "rebrand.ly",
                   # "trib.al", "mtr.cool", "mcaf.ee", "bit.do", "qr.ae", "adf.ly", "goo.gl", "bit.do",
                   # "bitly.com", "tinyurl.com", "bit.ly", "ow.ly", "t.co", "lnkd.in", "rebrand.ly", "trib.al",
                   # "mtr.cool", "mcaf.ee", "bit.do", "qr.ae", "adf.ly", "goo.gl", "bit.do", "bitly.com",
                   # "tinyurl.com", "bit.ly", "ow.ly", "t.co", "lnkd.in", "rebrand.ly", "trib.al", "mtr.cool",
                   # "mcaf.ee", "bit.do", "qr.ae", "adf.ly", "goo.gl", "bit.do", "bitly.com", "tinyurl.com",
                   # "bit.ly", "ow.ly", "t.co", "lnkd.in", "rebrand.ly", "trib.al", "mtr.cool", "mcaf.ee", "bit.do",
                   # "qr.ae", "adf.ly", "goo.gl", "bit.do", "bitly.com", "tinyurl.com", "bit.ly", "ow.ly", "t.co",
                   # "lnkd.in", "rebrand.ly", "trib.al", "mtr.cool", "mcaf.ee", "bit.do", "qr.ae", "adf.ly", "goo.gl",
                   # "bit.do", "bitly.com", "tinyurl.com", "bit.ly", "ow.ly", "t.co", "lnkd.in", "rebrand.ly", "trib.al",
                   # "mtr.cool", "mcaf.ee", "bit.do", "qr.ae", "adf.ly", "goo.gl", "bit.do",
                   ]

# TODO: Add caching
def web_search_part1_real(context, doc_source, doc_context, api_keys, year_month=None,
                     previous_answer=None, previous_search_results=None, extra_queries=None,
                     gscholar=False, provide_detailed_answers=False, start_time=None, web_search_tmp_marker_name=None,):

    # TODO: if it is scientific or knowledge based question, then use google scholar api, use filetype:pdf and site:arxiv.org OR site:openreview.net OR site:arxiv-vanity.com OR site:arxiv-sanity.com OR site:bioRxiv.org OR site:medrxiv.org OR site:aclweb.org
    st = time.time()
    start_time = start_time if start_time is not None else st
    provide_detailed_answers = int(provide_detailed_answers)
    if extra_queries is None:
        extra_queries = []
    n_query = "two" if previous_search_results or len(extra_queries) > 0 else "four"
    n_query = n_query if provide_detailed_answers >= 3 else "four"
    n_query_num = 4
    pqs = []
    if previous_search_results:
        for r in previous_search_results:
            pqs.append(r["query"])
    doc_context = f"You are also given the research document: '''{doc_context}'''" if len(doc_context) > 0 else ""
    if provide_detailed_answers >= 2 and len(extra_queries) > 0:
        pqs.extend(extra_queries)
    pqs = f"We had previously generated the following web search queries in our previous search: '''{pqs}''', don't generate these queries or similar queries - '''{pqs}'''" if len(pqs)>0 else ''
    prompt = prompts.web_search_prompt.format(context=context, doc_context=doc_context, pqs=pqs, n_query=n_query)
    year = int(datetime.now().strftime("%Y"))
    month = datetime.now().strftime("%B")
    num_res = 10
    use_original_query = False
    if (len(extra_queries) == 0) or (len(extra_queries) <= 1 and provide_detailed_answers >= 2):
        # TODO: explore generating just one query for local LLM and doing that multiple times with high temperature.
        query_strings = CallLLm(api_keys, use_gpt4=False, model_name="gpt-4o")(prompt, temperature=0.5, max_tokens=100)
        query_strings.split("###END###")[0].strip()
        logger.debug(f"Query string for {context} = {query_strings}") # prompt = \n```\n{prompt}\n```\n
        query_strings = sorted(parse_array_string(query_strings.strip()), key=lambda x: len(x), reverse=True)
        query_strings = [q.strip().lower() for q in query_strings[:n_query_num]]

        if len(query_strings) == 0:
            query_strings = CallLLm(api_keys, use_gpt4=False)(prompt, temperature=0.2, max_tokens=100)
            query_strings.split("###END###")[0].strip()
            query_strings = sorted(parse_array_string(query_strings.strip()), key=lambda x: len(x), reverse=True)
            query_strings = [q.strip().lower() for q in query_strings[:n_query_num]]
        if len(query_strings) <= 1:
            query_strings = query_strings + [context]
        query_strings = (query_strings if len(extra_queries) == 0 else query_strings[:1]) + extra_queries
        if (len(extra_queries) == 0):
            for i, q in enumerate(query_strings):
                if f"in {year}" in q or f"in {month} {year}" in q or f"in {year} {month}" in q:
                    continue
                if "trend" in q or "trending" in q or "upcoming" in q or "pioneering" in q or "advancements" in q or "advances" in q or "emerging" in q:
                    q = q + f" in {year}"
                elif "latest" in q or "recent" in q or "new" in q or "newest" in q or "current" in q or "state-of-the-art" in q or "sota" in q or "state of the art" in q:
                    if i % 2 == 0:
                        q = q + f" in {year} {month}"
                    else:
                        q = q + f" in {year}"
                query_strings[i] = q
    else:
        query_strings = extra_queries
        use_original_query = True
    if len(query_strings) <= 2:
        num_res = 20
    if len(query_strings) == 1:
        num_res = 40

    yield {"type": "query", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month, "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers}
    serp_available = "serpApiKey" in api_keys and api_keys["serpApiKey"] is not None and len(api_keys["serpApiKey"].strip()) > 0
    bing_available = "bingKey" in api_keys and api_keys["bingKey"] is not None and len(api_keys["bingKey"].strip()) > 0
    google_available = ("googleSearchApiKey" in api_keys and api_keys["googleSearchApiKey"] is not None and len(api_keys["googleSearchApiKey"].strip()) > 0) and ("googleSearchCxId" in api_keys and api_keys["googleSearchCxId"] is not None and len(api_keys["googleSearchCxId"].strip()) > 0)


    if year_month:
        year_month = datetime.strptime(year_month, "%Y-%m").strftime("%Y-%m-%d")
    time_logger.info(f"[web_search_part1_real] Time taken for web search part 1 query preparation = {(time.time() - st):.2f} with query strings as {query_strings}")
    search_st = time.time()
    serps = []
    month = int(datetime.now().strftime("%m"))
    if os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None:
        if not gscholar:

            serps.extend([get_async_future(brightdata_google_serp, query, os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
        if gscholar and use_original_query:
            serps.extend([get_async_future(brightdata_google_serp, f" research paper for {query}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None,
                                           only_science_sites=None) for ix, query in
                          enumerate(query_strings)])
        if gscholar and not use_original_query:
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {str(year)}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            if month <= 3:
                serps.extend([get_async_future(brightdata_google_serp, generate_science_site_query(query + f" research paper in {str(year - 1)}"),
                                               os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                               our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                              query_strings])
            serps.extend([get_async_future(brightdata_google_serp,
                                           generate_science_site_query(query + f" research paper"),
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
    if serp_available:
        if not gscholar:
            serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar and use_original_query:
            serps.extend([get_async_future(serpapi, f" research paper for {query}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=None,
                                           only_science_sites=None) for ix, query in
                          enumerate(query_strings)])
        if gscholar and not use_original_query:
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            if month <= 3:
                serps.extend([get_async_future(serpapi, query + f" research paper in {str(year - 1)}",
                                               api_keys["serpApiKey"], num_res,
                                               our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                              query_strings])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(gscholarapi, generate_science_site_query(query), api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(gscholarapi_published, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(gscholarapi, query + f" in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])

    if google_available:
        if not gscholar:
            serps.extend([get_async_future(googleapi_v2, query,
                                           dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in query_strings])
        if gscholar and use_original_query:
            serps.extend([get_async_future(googleapi_v2, f" research paper for {query}",
                                           dict(cx=api_keys["googleSearchCxId"],
                                                api_key=api_keys["googleSearchApiKey"]), 10,
                                           our_datetime=year_month, only_pdf=None,
                                           only_science_sites=None) for ix, query in
                          enumerate(query_strings)])
        if gscholar and not use_original_query:
            serps.extend([get_async_future(googleapi_v2, query + f" research paper in {year}",
                                           dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 0 else None,
                                           only_science_sites=True if ix % 2 == 1 else None) for ix, query in
                          enumerate(query_strings)])
            if month <= 3:
                serps.extend([get_async_future(googleapi_v2, query + f" research paper in {str(year - 1)}",
                                               dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), 10,
                                               our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                               only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                              enumerate(query_strings)])
            serps.extend([get_async_future(googleapi_v2, generate_science_site_query(query + f" research paper in {year}"),
                                           dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])

    if bing_available:
        if not gscholar:
            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res + 10, our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar and use_original_query:
            serps.extend([get_async_future(bingapi, f"Research paper for {query}", api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
        if gscholar and not use_original_query:
            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper in {year}", api_keys["bingKey"], num_res,
                                           our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper", api_keys["bingKey"], num_res,
                                           our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])

    try:
        assert len(serps) > 0
    except AssertionError:
        logger.error(f"Neither GOOGLE, Bing nor SERP keys are given but Search option choosen.")
        yield {"type": "error", "error": "Neither GOOGLE, Bing nor SERP keys are given but Search option choosen."}


    query_vs_results_count = Counter()
    total_count = 0
    full_queue = []
    deduped_results = set()
    seen_titles = set()
    temp_queue = Queue()
    result_context_emb_map = dict()
    # logger.error(f"Total number of queries = {len(query_strings)} and total serps = {len(serps)}")
    for ix, s in enumerate(as_completed(serps)):
        time_logger.info(f"[web_search_part1_real] Time taken for {ix}-th serp result in web search part 1 = {(time.time() - search_st):.2f} and full time = {(time.time() - st):.2f} and validity = {s.done() and s.exception() is None and len(s.result())> 0}")
        if s.exception is not None:
            try:
                s.result()
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Exception in getting search results from serp = \n{s.exception()}")
        if s.done() and s.exception() is None and exists_tmp_marker_file(web_search_tmp_marker_name):
            for iqx, r in enumerate(s.result()):
                if iqx > max(5, num_res//2):
                    break
                query = remove_year_month_substring(r.get("query", "").lower()).replace("recent research papers", "").replace("research paper", "").replace("research papers", "").strip()
                title = r.get("title", "").lower()
                description = r.get("description", "").lower()
                cite_text = f"""{(f" Cited by {r['citations']}") if r['citations'] else ""}"""
                title = title + f" ({r['year'] if r['year'] else ''})" + f"{cite_text}"
                link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace(
                    "v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8",
                                                                                                              '').replace(
                    "v9", '')
                link = convert_to_pdf_link_if_needed(link)
                if title in seen_titles or len(
                        title) == 0 or link in deduped_results or any(fbdn in link for fbdn in forbidden_links):
                    deduped_results.add(link)
                    seen_titles.add(title)
                    continue
                result_context = context + ".\n" + query + "?\n"
                if result_context not in result_context_emb_map:
                    result_context_emb_future = get_async_future(get_text_embedding, result_context, api_keys)
                result_text = title + "\n" + description + "\nLink Url: " + link.replace("https://",'').replace("http://",'').replace(".com",'').replace("www.",'').replace("/",' ').replace("_", ' ').replace("-", ' ')
                assert len(description.split()) > 0, "Link Description is empty"
                result_text_emb_future = get_async_future(get_text_embedding, result_text, api_keys)
                try:
                    if result_context not in result_context_emb_map:
                        result_context_emb = sleep_and_get_future_result(result_context_emb_future)
                        result_context_emb_map[result_context] = result_context_emb
                    else:
                        result_context_emb = result_context_emb_map[result_context]
                    result_text_emb = sleep_and_get_future_result(result_text_emb_future)
                    # numpy cosine similarity
                    sim = np.dot(result_context_emb, result_text_emb) / (np.linalg.norm(result_context_emb) * np.linalg.norm(result_text_emb))
                    if sim < THRESHOLD_SIM_FOR_SEARCH_RESULT:
                        continue
                except Exception as e:
                    continue
                full_queue.append({"query": query, "title": title, "link": link, "context": result_context, "type": "result", "rank": iqx})


                if link not in deduped_results and title not in seen_titles and (
                        len(query_vs_results_count) == len(query_strings) or query not in query_vs_results_count or query_vs_results_count[query] <= (5 if provide_detailed_answers <= 2 else 6)):
                    yield {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                           "rank": iqx, "start_time": start_time}
                    query_vs_results_count[query] += 1
                    total_count += 1
                    time_logger.info(
                        f"[web_search_part1_real] [Main Loop] Time taken for getting search results from {r['source']} n= {total_count}-th, time {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}, link = {link}")
                elif link not in deduped_results and title not in seen_titles:
                    temp_queue.put(
                        {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                         "rank": iqx, "start_time": start_time})

                deduped_results.add(link)
                seen_titles.add(title)
    for ix, s in enumerate(as_completed(serps)):
        time_logger.info(
            f"[web_search_part1_real] Time taken for {ix}-th serp result in web search part 1 = {(time.time() - search_st):.2f} and full time = {(time.time() - st):.2f} and validity = {s.done() and s.exception() is None and len(s.result()) > 0}")
        if s.exception is not None:
            try:
                s.result()
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Exception in getting search results from serp = \n{s.exception()}")
        if s.done() and s.exception() is None and exists_tmp_marker_file(web_search_tmp_marker_name):
            for iqx, r in enumerate(s.result()):
                if iqx <= max(5, num_res//2):
                    continue
                query = remove_year_month_substring(r.get("query", "").lower()).replace("recent research papers",
                                                                                        "").replace("research paper",
                                                                                                    "").replace(
                    "research papers", "").strip()
                title = r.get("title", "").lower()
                description = r.get("description", "").lower()
                cite_text = f"""{(f" Cited by {r['citations']}") if r['citations'] else ""}"""
                title = title + f" ({r['year'] if r['year'] else ''})" + f"{cite_text}"
                link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace(
                    "v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8",
                                                                                                              '').replace(
                    "v9", '')
                link = convert_to_pdf_link_if_needed(link)
                if title in seen_titles or len(
                        title) == 0 or link in deduped_results or any(fbdn in link for fbdn in forbidden_links):
                    deduped_results.add(link)
                    seen_titles.add(title)
                    continue
                result_context = context + ".\n" + query + "?\n"
                if result_context not in result_context_emb_map:
                    result_context_emb_future = get_async_future(get_text_embedding, result_context, api_keys)
                result_text = title + "\n" + description + "\nLink Url: " + link.replace("https://", '').replace("http://", '').replace(".com",
                                                                                                        '').replace(
                    "www.", '').replace("/", ' ').replace("_", ' ').replace("-", ' ')
                assert len(description.split()) > 0, "Link Description is empty"
                result_text_emb_future = get_async_future(get_text_embedding, result_text, api_keys)
                try:
                    if result_context not in result_context_emb_map:
                        result_context_emb = sleep_and_get_future_result(result_context_emb_future)
                        result_context_emb_map[result_context] = result_context_emb
                    else:
                        result_context_emb = result_context_emb_map[result_context]
                    result_text_emb = sleep_and_get_future_result(result_text_emb_future)
                    # numpy cosine similarity
                    sim = np.dot(result_context_emb, result_text_emb) / (
                                np.linalg.norm(result_context_emb) * np.linalg.norm(result_text_emb))
                    if sim < THRESHOLD_SIM_FOR_SEARCH_RESULT:
                        continue
                except Exception as e:
                    continue
                full_queue.append(
                    {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                     "rank": iqx})


                if link not in deduped_results and title not in seen_titles and (
                        len(query_vs_results_count) == len(query_strings) or query not in query_vs_results_count or
                        query_vs_results_count[query] <= (5 if provide_detailed_answers <= 2 else 6)):
                    yield {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                           "rank": iqx, "start_time": start_time}
                    query_vs_results_count[query] += 1
                    total_count += 1
                    time_logger.info(
                        f"[web_search_part1_real] [Main Loop] Time taken for getting search results from {r['source']} n= {total_count}-th, time {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}, link = {link}")
                elif link not in deduped_results and title not in seen_titles:
                    temp_queue.put(
                        {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                         "rank": iqx, "start_time": start_time})

                deduped_results.add(link)
                seen_titles.add(title)

    while not temp_queue.empty() and total_count <= ((provide_detailed_answers + 2) * 10):
        r = temp_queue.get()
        yield r
        total_count += 1
        time_logger.debug(
            f"Time taken for getting search results n= {total_count}-th in web search part 1 [Post all serps] = {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}")
        query_vs_results_count[r.get("query", "")] += 1
    time_logger.info(f"[web_search_part1_real] Time taken for web search part 1 = {(time.time() - st):.2f} and yielded {total_count} results.")
    yield {"type": "end", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month, "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers, "full_results": full_queue}


web_search_part1 = web_search_part1_real # web_search_part1_real

def web_search_queue(context, doc_source, doc_context, api_keys, year_month=None, previous_answer=None, previous_search_results=None, extra_queries=None,
                     previous_turn_search_results=None,
                     gscholar=False, provide_detailed_answers=False,
                     web_search_tmp_marker_name=None):
    if previous_turn_search_results is None:
        part1_res = get_async_future(web_search_part1, context, doc_source, doc_context, api_keys, year_month, previous_answer, previous_search_results, extra_queries, gscholar, provide_detailed_answers, time.time(), web_search_tmp_marker_name)
    else:
        def get_pseudo_results():
            queries = previous_turn_search_results["queries"]
            yield {"type": "query", "query": queries, "query_type": "web_search_part1", "year_month": year_month,
                   "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers}
            for idx, r in enumerate(previous_turn_search_results["links"]):
                yield {"query": random.choice(queries), "title": r["title"], "link": r["link"], "context": context, "type": "result",
                       "rank": idx, "start_time": time.time()}
            yield {"type": "end", "query": queries, "query_type": "web_search_part1", "year_month": year_month,
                   "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers,
                   "full_results": previous_turn_search_results["links"]}
        part1_res = get_async_future(get_pseudo_results)
    gen1, gen2 = thread_safe_tee(part1_res.result(), 2)
    read_queue = queued_read_over_multiple_links(gen2, api_keys, provide_detailed_answers=max(0, int(provide_detailed_answers) - 1),
                                                 web_search_tmp_marker_name=web_search_tmp_marker_name)
    return [get_async_future(get_part_1_results, gen1), read_queue] # get_async_future(get_part_1_results, part1_res)

def get_part_1_results(part1_res):
    queries = next(part1_res)["query"]
    results = []
    end_result = None
    query_yield_done = False
    for r in part1_res:
        if isinstance(r, dict) and r["type"] == "result" and len(results) <= 10:
            results.append(r)
        if len(results) == 10:
            query_yield_done = True
            yield {"search_results": results, "queries": queries}
        if r["type"] == "end":
            if not query_yield_done:
                yield {"search_results": results, "queries": queries}
            end_result = r

            def deduplicate_and_sort(link_data):
                aggregated_data = {}

                # Parsing and Aggregating Data
                for entry in link_data:
                    link = entry["link"]
                    rank = entry["rank"]
                    title = entry["title"]
                    if link in aggregated_data:
                        aggregated_data[link]["ranks"].append(rank)
                        aggregated_data[link]["count"] += 1
                    else:
                        aggregated_data[link] = {"title": title, "ranks": [rank], "count": 1}

                # Calculating Average Rank
                for data in aggregated_data.values():
                    data["rank"] = sum(data["ranks"]) / len(data["ranks"])
                    del data["ranks"]  # Remove the ranks list as it's no longer needed

                # Creating the Final List
                final_list = [{"link": link, **data} for link, data in aggregated_data.items()]

                # Sorting the List
                final_list.sort(key=lambda x: (-x["count"], x["rank"]))

                return final_list

            end_result["full_results"] = deduplicate_and_sort(end_result["full_results"])
    yield end_result

import multiprocessing
from multiprocessing import Pool

@CacheResults(cache, key_function=lambda args, kwargs: str(mmh3.hash(str(args[0]), signed=False)), enabled=False,
              should_cache_predicate=lambda result: result is not None and "full_text" in result and len(result["full_text"].strip()) > 10)
def process_link(link_title_context_apikeys, use_large_context=False):
    # TODO: process links which are images as well.
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    st = time.time()
    link_data = download_link_data(link_title_context_apikeys)
    title = link_data["title"]
    text = link_data["full_text"]
    is_image = link_data["is_image"]
    query = f"First Lets write a comprehensive and detailed summary reuters essay with full details, nuances and caveats about [{title}]({link}) from the given document. \n\nThen lets write in detail about the document ([{title}]({link})) ( ```preview snippet of document - '{text[:1000]}'``` ) in the context of the the below question or writing instructions \n```{context}```\n"
    link_title_context_apikeys = (link, title, context, api_keys, text, detailed)
    try:
        if is_image:
            summary = link_data["full_text"]
        else:
            if detailed >= 2:
                more_summary = get_async_future(get_downloaded_data_summary, (link, title, query, api_keys, text, detailed), use_large_context=False)
            if is_science_site(link):
                keys = SCIENCE_KEYS
                if detailed < 2:
                    keys = ["methodology"]
                key_to_query_map = prompts.paper_details_map
                science_answers = [get_async_future(get_downloaded_data_summary, (link, title, key_to_query_map[key], api_keys, text, detailed), use_large_context=len(keys) == 1) for key in keys]
            summary = get_downloaded_data_summary(link_title_context_apikeys, use_large_context=use_large_context)["text"]
            if detailed >= 2:
                more_summary = sleep_and_get_future_result(more_summary)["text"] if sleep_and_get_future_exception(more_summary) is None else ""
                summary = f"{summary}\n\n{more_summary}"
            if is_science_site(link):
                science_answers = [f"<|{key}|>" + "\n" + sleep_and_get_future_result(sa)["text"] + f"\n<|/{key}|>" for key, sa in zip(keys, science_answers)]
                science_answers = "\n".join(science_answers)
                summary = f"{summary}\n\n{science_answers}"


    except AssertionError as e:
        return {"link": link, "title": title, "text": '', "exception": False, "full_text": text, "detailed": detailed}
    logger.debug(f"Time for processing PDF/Link {link} = {(time.time() - st):.2f}")
    assert len(link.strip()) > 0, f"[process_link] Link is empty for title {title}"
    # assert semantic_validation_web_page_scrape(context, {"link": link, "title": title, "text": summary}, api_keys)
    return {"link": link, "title": title, "text": summary, "exception": False, "full_text": text, "detailed": detailed, "is_image": is_image}

from concurrent.futures import ThreadPoolExecutor
@CacheResults(cache=cache, key_function=lambda args, kwargs: str(mmh3.hash(str(args[0][0]), signed=False)),
            enabled=False)
def download_link_data(link_title_context_apikeys, web_search_tmp_marker_name=None):
    st = time.time()
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    assert len(link.strip()) > 0, f"[download_link_data] Link is empty for title {title}"
    link = convert_to_pdf_link_if_needed(link)
    is_image_link_future = get_async_future(is_image_link, link)
    is_pdf = is_pdf_link(link)
    is_image = sleep_and_get_future_result(is_image_link_future)
    link_title_context_apikeys = (link, title, context, api_keys, text, detailed)
    if is_image:
        llm = CallLLm(api_keys, use_gpt4=True, use_16k=True, model_name="anthropic/claude-3-haiku:beta")
        doc_text_f1 = get_async_future(llm, prompts.deep_caption_prompt, images=[link], stream=False)
        llm = CallLLm(api_keys, use_gpt4=True, model_name="gpt-4o")
        new_context = context.replace(link, 'this given image')
        prompt = prompts.deep_caption_prompt_with_query(query=new_context)
        # prompt = f"You are an AI expert at reading images and performing OCR, image analysis, graph analysis, object detection, image recognition and text extraction from images. OCR the image, extract text, tables, data, charts or plot information or any other text and tell me what this image says. Then answer the query: {context}"
        answer = llm(prompt, images=[link], temperature=0.7, stream=False)
        answer += ("\n" + sleep_and_get_future_result(doc_text_f1))
        answer = f"OCR (low accuracy) and image extraction results and answers: {answer}\n\n"
        result = {"link": link, "title": title, "text": answer, "exception": False, "full_text": answer, "is_pdf": False, "is_image": True}
    elif is_pdf:
        result = read_pdf(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        result["is_pdf"] = True
        result["is_image"] = False
    else:
        result = get_page_text(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        result["is_pdf"] = False
        result["is_image"] = False
    assert len(result["full_text"].strip().split()) > 100, f"[download_link_data] Text too short for link {link}"
    et = time.time() - st
    time_logger.info(f"[download_link_data] Time taken to download link data for {link} = {et:.2f}")
    return result


import requests
import base64

import requests


def convert_doc_to_pdf(file_path, output_path, secret_key=None):
    """
    Converts a Word document (DOCX) to PDF using an online API.

    Args:
    file_path (str): Path to the DOCX file on disk.
    output_path (str): Path where the converted PDF should be saved.
    secret_key (str): API secret key.

    Returns:
    None
    """
    # Define the API endpoint with the secret key as a query parameter

    if secret_key is None:
        secret_key = os.getenv("CONVERT_API_SECRET_KEY")
    assert secret_key is not None, "Secret key is not provided and not found in environment variables."

    api_endpoint = f"https://v2.convertapi.com/convert/docx/to/pdf?Secret={secret_key}"
    data = {'StoreFile': 'true'}

    # Open the DOCX file in binary mode
    with open(file_path, 'rb') as file:
        files = {'File': file}

        # Make the POST request
        response = requests.post(api_endpoint, files=files, data=data)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the response JSON
            response_json = response.json()

            # ConvertAPI returns the PDF file in a URL if StoreFile was set to true
            pdf_url = response_json['Files'][0]['Url']

            # Download the PDF file
            pdf_response = requests.get(pdf_url)

            if pdf_response.status_code == 200:
                # Save the PDF file to the specified output path
                with open(output_path, 'wb') as pdf_file:
                    pdf_file.write(pdf_response.content)
            else:
                raise Exception(f"Failed to download the converted PDF: {pdf_response.status_code} {pdf_response.text}")
        else:
            raise Exception(f"Failed to convert DOCX to PDF: {response.status_code} {response.text}")


def convert_pdf_to_txt(file_url, secret_key):
    """
    Converts a PDF file to a text file using an online API.

    Args:
    file_url (str): URL of the PDF file to be converted.
    secret_key (str): API secret key.

    Returns:
    str: Content of the converted text file.
    """

    # Define the API endpoint with the secret key as a query parameter
    api_endpoint = f"https://v2.convertapi.com/convert/pdf/to/txt?Secret={secret_key}"

    # Data for non-file fields
    data = {
        'Timeout': 30,
        'PageRange': '1-50',
        'StoreFile': 'true'
    }

    # File payload
    files = {'File': (None, file_url)}

    # Make the POST request
    response = requests.post(api_endpoint, data=data, files=files)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the response JSON
        response_json = response.json()

        # Extract the FileData field
        file_data_base64 = response_json['Files'][0]['FileData']

        # Decode the base64 string to get the file content
        file_content = base64.b64decode(file_data_base64).decode('utf-8')

        return file_content
    else:
        raise Exception(f"Failed to convert PDF: {response.status_code} {response.text}")


def convert_arxiv_link_to_html(link):
    if "pdf" in link:
        arxiv_id = link.replace(".pdf", "").split("/")[-1]
        new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        new_link_2 = f"https://arxiv.org/html/{arxiv_id}"
    if "abs" in link:
        arxiv_id = link.split("/")[-1]
        new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        new_link_2 = f"https://arxiv.org/html/{arxiv_id}"
    if "html" in link:
        arxiv_id = link.split("/")[-1]
        new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        new_link_2 = f"https://arxiv.org/html/{arxiv_id}"

    return new_link, new_link_2

def get_arxiv_pdf_link(link):
    try:
        assert "arxiv.org" in link
        import re
        from bs4 import BeautifulSoup, SoupStrainer
        # convert to ar5iv link
        if "pdf" in link:
            arxiv_id = link.replace(".pdf", "").split("/")[-1]
            new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
            new_link_2 = f"https://arxiv.org/html/{arxiv_id}"
        if "abs" in link:
            arxiv_id = link.split("/")[-1]
            new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
            new_link_2 = f"https://arxiv.org/html/{arxiv_id}"
        if "html" in link:
            arxiv_id = link.split("/")[-1]
            new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
            new_link_2 = f"https://arxiv.org/html/{arxiv_id}"
        logger.debug(f"Converted arxiv link {link} to {new_link}")
        arxiv_request_v2 = get_async_future(requests.get, new_link_2, timeout=10)
        arxiv_request = requests.get(new_link, timeout=10)
        if arxiv_request.status_code == 200:
            arxiv_text = arxiv_request.text
        else:
            arxiv_request = sleep_and_get_future_result(arxiv_request_v2)
            arxiv_text = arxiv_request.text
        assert arxiv_request.status_code == 200 or arxiv_request_v2.status_code == 200, f"Error converting arxiv link {link} to ar5iv link with status code {arxiv_request.status_code}"
        arxiv_pdf_html_parse_start = time.time()
        soup = BeautifulSoup(arxiv_text, 'lxml', parse_only=SoupStrainer('article'))
        element = soup.find(id='bib')
        title = ''
        # Remove the element
        if element is not None:
            element.decompose()
        try:
            title = soup.select("h1")[0].text
        except:
            title = ''
        try:
            text = soup.select("article")[0].text
        except:
            soupy = soup_html_parser_fast_v3(arxiv_text)
            text = soupy["text"]
            title = soupy["title"]
        arxiv_pdf_html_parse_end = time.time()
        time_logger.info(f"Time taken to parse arxiv html {link} = {(arxiv_pdf_html_parse_end - arxiv_pdf_html_parse_start):.2f}")
        text = normalize_whitespace(text)
        text = re.sub('\n{3,}', '\n\n', text)
        assert len(text.strip().split()) > 500, f"Extracted arxiv info is too short for link: {link}"
        return title, text
    except AssertionError as e:
        logger.warning(f"Error converting arxiv link {link} to ar5iv link with error {str(e)}")
        raise e
    except Exception as e:
        logger.warning(f"Error reading arxiv / ar5iv pdf {link} with error = {str(e)}\n{traceback.format_exc()}")
        raise e

def read_pdf(link_title_context_apikeys, web_search_tmp_marker_name=None):
    link, title, context, api_keys, _, detailed = link_title_context_apikeys
    assert exists_tmp_marker_file(web_search_tmp_marker_name), f"Marker file not found for link: {link}"
    st = time.time()
    # Reading PDF
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    # convert_api_pdf_future = get_async_future(convert_pdf_to_txt, link, os.getenv("CONVERT_API_SECRET_KEY"))
    convert_api_pdf_future = None
    pdf_text_future = None
    if "arxiv.org" in link and ("html" in link or "pdf" not in link):
        pass
    else:
        pdf_text_future = get_async_future(pdfReader, link)
    get_arxiv_pdf_link_future = None
    arxiv_brightdata_future_1 = None
    arxiv_brightdata_future_2 = None
    arxiv_zenrows_future = None
    result_from = "TIMEOUT_PDF_READER"
    if "arxiv.org" in link:
        get_arxiv_pdf_link_future = get_async_future(get_arxiv_pdf_link, link)
        arxiv_html_link = convert_arxiv_link_to_html(link)
        arxiv_brightdata_future_1 = get_async_future(fetch_content_brightdata_html, arxiv_html_link[0], api_keys['brightdataUrl'], False, True)
        arxiv_brightdata_future_2 = get_async_future(fetch_content_brightdata_html, arxiv_html_link[1], api_keys['brightdataUrl'], False, True)
        arxiv_zenrows_future = get_async_future(send_request_zenrows_html, arxiv_html_link[0], api_keys['zenrows'], readability=False, js_render=False, clean_parse=True)
    text = ''
    while time.time() - st < (45 if detailed <= 1 else 75):
        if pdf_text_future is not None and pdf_text_future.done() and pdf_text_future.exception() is None:
            text = pdf_text_future.result()
            if isinstance(text, str):
                txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>',
                                                                                                      '')
                txt_len = len(txt.strip().split())
                if txt_len > 500:
                    result_from = "pdf_reader_tool"
                    break
        if convert_api_pdf_future is not None and convert_api_pdf_future.done() and convert_api_pdf_future.exception() is None:
            text = convert_api_pdf_future.result()
            if isinstance(text, str):
                txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>',
                                                                                                      '')
                txt_len = len(txt.strip().split())
                if txt_len > 500:
                    result_from = "convert_api"
                    break
        if get_arxiv_pdf_link_future is not None and get_arxiv_pdf_link_future.done() and get_arxiv_pdf_link_future.exception() is None and not (convert_api_pdf_future is not None and convert_api_pdf_future.done() and convert_api_pdf_future.exception() is None) and not (pdf_text_future is not None and pdf_text_future.done() and pdf_text_future.exception() is None):
            maybe_title, text = get_arxiv_pdf_link_future.result()
            if isinstance(maybe_title, str) and len(maybe_title.strip()) > 0:
                title = maybe_title
            if isinstance(text, str):
                txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>',
                                                                                                      '')
                txt_len = len(txt.strip().split())
                if txt_len > 500:
                    result_from = "arxiv"
                    break
        if arxiv_brightdata_future_1 is not None and arxiv_brightdata_future_1.done() and arxiv_brightdata_future_1.exception() is None:
            text = str(arxiv_brightdata_future_1.result())
            if isinstance(text, str):
                txt_len = len(text.strip().split())
                if txt_len > 500:
                    result_from = "arxiv_brightdata"
                    break

        if arxiv_brightdata_future_2 is not None and arxiv_brightdata_future_2.done() and arxiv_brightdata_future_2.exception() is None:
            text = str(arxiv_brightdata_future_2.result())
            if isinstance(text, str):
                txt_len = len(text.strip().split())
                if txt_len > 500:
                    result_from = "arxiv_brightdata"
                    break

        if arxiv_zenrows_future is not None and arxiv_zenrows_future.done() and arxiv_zenrows_future.exception() is None:
            text = str(arxiv_zenrows_future.result())
            if isinstance(text, str):
                txt_len = len(text.strip().split())
                if txt_len > 500:
                    result_from = "arxiv_brightdata"
                    break
        time.sleep(0.5)

    txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    txt = normalize_whitespace(txt)
    txt_len = len(txt.strip().split())
    time_logger.info(f"Time taken to read PDF {link} = {(time.time() - st):.2f} with text len = {txt_len}")

    assert txt_len > 500, f"Extracted pdf from {result_from} with len = {txt_len} is too short for pdf link: {link}"
    assert len(link.strip()) > 0, f"[read_pdf] Link is empty for link {link}"
    # assert semantic_validation_web_page_scrape(context, {"link": link, "title": title, "text": txt}, api_keys)
    return {"link": link, "title": title, "context": context, "detailed":detailed, "exception": False, "full_text": txt}

@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def read_pdf_simple(link: str) -> str:

    st = time.time()
    # Reading PDF
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    convert_api_pdf_future = get_async_future(convert_pdf_to_txt, link, os.getenv("CONVERT_API_SECRET_KEY"))
    # convert_api_pdf_future = None
    pdf_text_future = get_async_future(pdfReader, link)

    result_from = "TIMEOUT_PDF_READER"
    text = ''
    while time.time() - st < 75:
        if pdf_text_future is not None and pdf_text_future.done() and pdf_text_future.exception() is None:
            text = pdf_text_future.result()
            if isinstance(text, str):
                txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>',
                                                                                                      '')
                txt_len = len(txt.strip().split())
                if txt_len > 500:
                    result_from = "pdf_reader_tool"
                    break
        if convert_api_pdf_future is not None and convert_api_pdf_future.done() and convert_api_pdf_future.exception() is None:
            text = convert_api_pdf_future.result()
            if isinstance(text, str):
                txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>',
                                                                                                      '')
                txt_len = len(txt.strip().split())
                if txt_len > 500:
                    result_from = "convert_api"
                    break
        time.sleep(0.5)

    txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    time_logger.info(f"Time taken to read PDF {link} = {(time.time() - st):.2f}")
    txt = normalize_whitespace(txt)
    txt_len = len(txt.strip().split())
    assert txt_len > 500, f"Extracted pdf from {result_from} with len = {txt_len} is too short for pdf link: {link}"
    assert len(link.strip()) > 0, f"[read_pdf] Link is empty for link {link}"
    assert semantic_validation_web_page_scrape(context, {"link": link, "title": title, "text": txt}, api_keys)
    return txt


def get_downloaded_data_summary(link_title_context_apikeys, use_large_context=False):
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    st = time.time()
    input_len = len(txt.strip().split())
    assert input_len > 100, f"Input length is too short, input len = {input_len}, for link: {link}"
    # chunked_text = ChunkText(txt, TOKEN_LIMIT_FOR_DETAILED if detailed else TOKEN_LIMIT_FOR_SHORT, 0)[0]
    logger.debug(f"Time for content extraction for link: {link} = {(time.time() - st):.2f}")
    time_logger.info(f"Invoke contextual reader for link: {link}. Input length = {input_len}")

    result = ContextualReader(api_keys, provide_short_responses=not use_large_context, scan=use_large_context)(context, txt, retriever=None)
    extracted_info, llm_result_future = result

    tt = time.time() - st
    tex_len = len(extracted_info.split())
    time_logger.info(f"Called contextual reader for link: {link}, Input length = {input_len}, Result length = {tex_len} with total time = {tt:.2f}")
    return {"link": link, "title": title, "context": context, "text": extracted_info, "llm_result_future": llm_result_future, "detailed": detailed, "exception": False, "full_text": txt, "detailed": detailed}

def get_page_text(link_title_context_apikeys, web_search_tmp_marker_name=None):
    st = time.time()
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    assert exists_tmp_marker_file(web_search_tmp_marker_name), f"Marker file not found for link: {link}"
    pgc = web_scrape_page(link, context, api_keys, web_search_tmp_marker_name=web_search_tmp_marker_name)
    title = pgc["title"]
    text = pgc["text"]
    assert len(text.strip().split()) > 100, f"Extracted Web text is too short for link: {link}"
    assert len(link.strip()) > 0, f"[get_page_text] Link is empty for title {title}"
    assert not title.lower().strip().startswith("Page not found".lower())
    assert not title.lower().strip().startswith("Not found (404)".lower())
    # assert semantic_validation_web_page_scrape(context, dict(**pgc), api_keys)
    time_logger.info(f"[get_page_text] Time taken to download page data with len = {len(text.split())} for {link} = {(time.time() - st):.2f}")
    return {"link": link, "title": title, "context": context, "exception": False, "full_text": text, "detailed": detailed}


pdf_process_executor = ThreadPoolExecutor(max_workers=32)

def queued_read_over_multiple_links(results_generator, api_keys, provide_detailed_answers=False, web_search_tmp_marker_name=None):
    def yeild_one():
        for r in results_generator:
            if isinstance(r, dict) and r["type"] == "result":
                yield [r["link"], r["title"], r["context"], api_keys, '', provide_detailed_answers, r.get("start_time", time.time()), r["query"]]
            else:
                continue

    def call_back(result, *args, **kwargs):
        try:
            if result is not None and "link" in result and len(result["link"].strip()) > 0:
                link = result['link']
            else:
                link = args[0][0]['link']
            assert len(link.strip()) > 0, f"Empty input link in call_back"
        except:
            link = ''
        full_result = None
        text = ''
        llm_result_future = wrap_in_future("NO_LLM_RESULT")

        if result is not None:
            assert isinstance(result, dict)
            result.pop("exception", None)
            result.pop("detailed", None)
            llm_result_future = result.pop("llm_result_future", wrap_in_future("NO_LLM_RESULT"))
            full_result = deepcopy(result)
            result.pop("full_text", None)
            text = f"[{result['title']}]({result['link']})\n{result['text']}"
        return {"text": text, "llm_result_future": llm_result_future, "full_info": full_result, "link": link, "title": result['title']}

    threads = 64
    # task_queue = orchestrator(process_link, list(zip(link_title_context_apikeys, [{}]*len(link_title_context_apikeys))), call_back, threads, 120)
    def fn2(*args, **kwargs):
        link_title_context_apikeys = args[0]
        link = link_title_context_apikeys[0]
        st = time.time()
        time_logger.info(f"[fn2] Start Processing link: {link}")
        title = link_title_context_apikeys[1]
        context = link_title_context_apikeys[2]
        api_keys = link_title_context_apikeys[3]
        text = link_title_context_apikeys[4]
        detailed = link_title_context_apikeys[5]
        start_time = link_title_context_apikeys[6]
        assert len(link.strip()) > 0, f"Empty input link in fn2"
        query = link_title_context_apikeys[7]
        web_search_tmp_marker_name = kwargs.get("keep_going_marker", None)
        link_title_context_apikeys = (link, title, context, api_keys, text, detailed)
        if exists_tmp_marker_file(web_search_tmp_marker_name):
            web_res = download_link_data(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        else:
            web_res = {"exception": True, "error": "Marker file not found"}
            raise ForceStoppedException(f"fn2 Web search stopped for link: {link}, {web_res['error']}")
        error = web_res["error"] if "error" in web_res else None
        elapsed = time.time() - start_time
        if elapsed > MAX_TIME_TO_WAIT_FOR_WEB_RESULTS:
            raise ForceStoppedException(f"fn2 Web search stopped due to too long download time for link: {link}, {error}")
        time_logger.info(f"[fn2] Time taken for downloading link: = {elapsed:.2f}, fn2 time = {(time.time() - st):.2f} with len = {len(web_res['full_text'].split())}, link = {link}")
        if exists_tmp_marker_file(web_search_tmp_marker_name) and not web_res.get("exception",
                                                                                  False) and "full_text" in web_res and len(
                web_res["full_text"].split()) > 0:
            text = web_res["full_text"]
            link_title_context_apikeys = (link, title, context, api_keys, text, query, detailed)
            st = time.time()
            summary = get_downloaded_data_summary(link_title_context_apikeys)
            if "is_image" in web_res and web_res["is_image"]:
                summary["text"] += ("\n" + web_res["full_text"])
            assert "link" in summary and len(summary["link"].strip()) > 10, f"Empty output link in summary"
            time_logger.info(f"[fn2] Time taken for processing link and summary: = {(time.time() - start_time):.2f}, fn2 time = {(time.time() - st):.2f}, link = {link}")
            return summary
        elif error or web_res.get("exception", False):
            raise ForceStoppedException(f"fn2 Web search stopped for link: {link}, {error}")
        elif not exists_tmp_marker_file(web_search_tmp_marker_name):
            raise ForceStoppedException(f"fn2 Web search stopped for link: {link} due to marker file not found")
        else:
            raise GenericShortException(f"fn2 Web search stopped for link: {link}")
    # def compute_timeout(link):
    #     return {"timeout": 60 + (30 if provide_detailed_answers else 0)} if is_pdf_link(link) else {"timeout": 30 + (15 if provide_detailed_answers else 0)}
    # timeouts = list(pdf_process_executor.map(compute_timeout, links))
    def yield_timeout():
        while True:
            yield dict(keep_going_marker=web_search_tmp_marker_name)
    task_queue = orchestrator_with_queue(zip(yeild_one(), yield_timeout()), fn2, call_back, max_workers=threads, timeout=MAX_TIME_TO_WAIT_FOR_WEB_RESULTS * (3 if provide_detailed_answers else 2))
    return task_queue


def read_over_multiple_links(links, titles, contexts, api_keys, texts=None, provide_detailed_answers=False):
    if texts is None:
        texts = [''] * len(links)
    # Combine links, titles, contexts and api_keys into tuples for processing
    link_title_context_apikeys = list(zip(links, titles, contexts, [api_keys] * len(links), texts, [provide_detailed_answers] * len(links)))
    # Use the executor to apply process_pdf to each tuple
    futures = [pdf_process_executor.submit(process_link, l_t_c_a, provide_detailed_answers and len(links) <= 4) for l_t_c_a in link_title_context_apikeys]
    # Collect the results as they become available
    processed_texts = [sleep_and_get_future_result(future) for future in futures]
    processed_texts = [p for p in processed_texts if not p["exception"]]
    # processed_texts = [p for p in processed_texts if not "no relevant information" in p["text"].lower()]
    # assert len(processed_texts) > 0
    if len(processed_texts) == 0:
        logger.warning(f"Number of processed texts: {len(processed_texts)}, with links: {links} in read_over_multiple_links")
    full_processed_texts = deepcopy(processed_texts)
    for fp, p in zip(full_processed_texts, processed_texts):
        p.pop("exception", None)
        p.pop("detailed", None)
        if len(p["text"].strip()) == 0:
            p["text"] = p.pop("full_text", '')
            fp["text"] = fp.pop("full_text", '')
        p.pop("full_text", None)
    # Concatenate all the texts

    # Cohere rerank here
    # result = "\n\n".join([json.dumps(p, indent=2) for p in processed_texts])
    if len(links) == 1:
        raw_texts = [p.get("full_text", '') if not p.get('is_image', False) else '' for p in full_processed_texts]
        raw_texts = [ChunkText(p.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', ''),
                              TOKEN_LIMIT_FOR_SHORT*2 - get_gpt4_word_count(p), 0)[0] if len(p) > 0 else "" for p in raw_texts]
        result = "\n\n".join([f"[{p['title'] if len(p['title']) > 0 else p['link']}]({p['link']})\nSummary:\n{p['text']}\n{'Raw article text:' if len(r.strip()) > 0 else ''}\n{r}\n" for r, p in
                              zip(raw_texts, processed_texts)])
    elif len(links) == 2 and provide_detailed_answers:
        raw_texts = [p.get("full_text", '') if not p.get('is_image', False) else '' for p in full_processed_texts]
        raw_texts = [ChunkText(p.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', ''),
                               TOKEN_LIMIT_FOR_SHORT - get_gpt4_word_count(p),
                               0)[0] if len(p) > 0 else "" for p in raw_texts]
        result = "\n\n".join([f"[{p['title'] if len(p['title']) > 0 else p['link']}]({p['link']})\nSummary:\n{p['text']}\n{'Raw article text:' if len(r.strip()) > 0 else ''}\n{r}\n" for r, p in
                              zip(raw_texts, processed_texts)])
    else:
        result = "\n\n".join([f"[{p['title'] if len(p['title']) > 0 else p['link']}]({p['link']})\n{p['text']}" for p in processed_texts])
    return result, full_processed_texts


def get_multiple_answers(query, additional_docs:list, current_doc_summary:str, provide_detailed_answers=False, provide_raw_text=True, dont_join_answers=False):
    # prompt = prompts.document_search_prompt.format(context=query, doc_context=current_doc_summary)
    # api_keys = additional_docs[0].get_api_keys()
    # query_strings = CallLLm(api_keys, use_gpt4=False)(prompt, temperature=0.5, max_tokens=100)
    # query_strings.split("###END###")[0].strip()
    # logger.debug(f"Query string for {query} = {query_strings}")  # prompt = \n```\n{prompt}\n```\n
    # query_strings = [q.strip() for q in parse_array_string(query_strings.strip())[:4]]
    # # select the longest string from the above array
    #
    # if len(query_strings) == 0:
    #     query_strings = CallLLm(api_keys, use_gpt4=False)(prompt, temperature=0.2, max_tokens=100)
    #     query_strings.split("###END###")[0].strip()
    #     query_strings = [q.strip() for q in parse_array_string(query_strings.strip())[:4]]
    # query_strings = sorted(query_strings, key=lambda x: len(x), reverse=True)
    # query_strings = query_strings[:1]
    # if len(query_strings) <= 0:
    #     query_strings = query_strings + [query]
    # query_string = query_strings[0]

    start_time = time.time()
    query_string = (
                       f"Previous context: '''{current_doc_summary}'''\n" if len(
                           current_doc_summary.strip()) > 0 else '') + f"Focus on this Current query: '''{query}'''"
    if provide_raw_text:
        per_doc_text_len = (32_000 if provide_detailed_answers >= 2 else 16_000) // len(additional_docs)
        doc_search_results_futures = [pdf_process_executor.submit(doc.semantic_search_document, query_string, per_doc_text_len) for doc in additional_docs]
        if provide_detailed_answers >= 2:
            doc_search_results_small_futures = [pdf_process_executor.submit(doc.semantic_search_document_small, query_string, per_doc_text_len//2) for doc in
                additional_docs]
    query_string = (
                       f"Previous context: '''{current_doc_summary}'''\n" if len(
                           current_doc_summary.strip()) > 0 else '') + f"{'Write detailed, informative, comprehensive and in depth answer. Provide more details, information and in-depth response covering all aspects. We will use this response as an essay so write clearly and elaborately using excerts from the document.' if provide_detailed_answers else ''}. Provide {'detailed, comprehensive, thoughtful, insightful, informative and in depth' if provide_detailed_answers else ''} answer for this current query: '''{query}'''"
    if not provide_raw_text or provide_detailed_answers >= 2:
        futures = [pdf_process_executor.submit(doc.get_short_answer, query_string, defaultdict(lambda:provide_detailed_answers, {"provide_detailed_answers": 2 if provide_detailed_answers >= 4 else provide_detailed_answers}), False)  for doc in additional_docs]
        answers = [sleep_and_get_future_result(future) for future in futures]
        logger.info(f"[get_multiple_answers]: Getting answers only Time spent = {time.time() - start_time:.2f}, Query = ```{query}```")
        answers = [{"link": doc.doc_source, "title": doc.title, "text": answer} for answer, doc in zip(answers, additional_docs)]

        if provide_detailed_answers >= 4:
            stage_1_answers = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}" for p in answers]
            joined_answers = "\n\n".join(stage_1_answers)
            query_string = (
                               f"Previous context and conversation details between human and AI assistant: '''{current_doc_summary}'''\n" if len(
                                   current_doc_summary.strip()) > 0 else '') + f"Current query: '''{query}'''" + f"\n\nAnswers:\n{joined_answers}"
            futures = [pdf_process_executor.submit(doc.get_short_answer, query_string,
                                                   defaultdict(lambda: provide_detailed_answers, {
                                                       "provide_detailed_answers": 2}),
                                                   False) for doc in additional_docs]
            answers_stage_2 = [sleep_and_get_future_result(future) for future in futures]
            answers_stage_2 = [{"link": doc.doc_source, "title": doc.title, "text": answer} for answer, doc in
                       zip(answers_stage_2, additional_docs)]
            answers = [{"link": doc.doc_source, "title": doc.title, "text": a1["text"] + "\n" + a2["text"]} for a1, a2, doc in zip(answers, answers_stage_2, additional_docs)]
            logger.info(f"[get_multiple_answers]: Getting answers stage 2 Time spent = {time.time() - start_time:.2f}")



    if provide_raw_text:
        if provide_detailed_answers >= 2:
            doc_search_results = [sleep_and_get_future_result(f) + "\n\n" + sleep_and_get_future_result(q) for f, q in zip(doc_search_results_futures, doc_search_results_small_futures)]
        else:
            doc_search_results = [sleep_and_get_future_result(f) for f in doc_search_results_futures]
        logger.info(
            f"[get_multiple_answers]: Getting raw data Time spent = {time.time() - start_time:.2f}, Query = ```{query}```")

    if provide_detailed_answers >= 2 and provide_raw_text:
        read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}\n{'Raw article text:' if len(r.strip()) > 0 else ''}\n{r}\n" for r, p in
                     zip(doc_search_results, answers)]
    elif provide_detailed_answers >= 2:
        read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}" for p in answers]
    elif provide_raw_text:
        read_text = [d for d in doc_search_results]
    else:
        # read_text = [f"[{p['title']}]({p['link']})\n{p['text']}" for p in answers]
        read_text = ["Problem reading documents"] * len(additional_docs)

    new_line = '\n\n'

    if dont_join_answers:
        pass
    else:
        read_text = new_line.join(read_text)
    dedup_results = [{"link": doc.doc_source, "title": doc.title} for doc in additional_docs]
    time_spent = time.time() - start_time
    logger.info(f"[get_multiple_answers]: Time spent = {time_spent:.2f}, Query = ```{query}```\nAnswers len = {len((read_text if isinstance(read_text, str) else new_line.join(read_text)).split())}")
    return wrap_in_future({"search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]}), wrap_in_future({"text": read_text, "search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]})



