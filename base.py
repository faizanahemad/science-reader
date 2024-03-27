from datetime import datetime
import sys
import random
from functools import partial
import glob
import traceback
from operator import itemgetter
import itertools
from queue import Empty

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import re
import inspect
import random
import inspect
from semanticscholar import SemanticScholar
from semanticscholar.SemanticScholar import Paper
import mmh3
from pprint import pprint
import time
import concurrent.futures
import pandas as pd
import tiktoken
from copy import deepcopy, copy
import requests
import tempfile
from tqdm import tqdm
try:
    import ujson as json
except ImportError:
    import json
import requests
import dill
import os
from prompts import prompts
from langchain.document_loaders import MathpixPDFLoader
from functools import partial

from langchain.llms import OpenAI
from langchain.agents import load_tools
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain import OpenAI, ConversationChain
from langchain.embeddings import OpenAIEmbeddings
from collections import defaultdict, Counter

import openai
import tiktoken
from vllm_client import get_streaming_vllm_response


from langchain.agents import Tool
from langchain.tools import BaseTool
from langchain.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.llms import OpenAI
from langchain.text_splitter import SpacyTextSplitter
from langchain.text_splitter import TokenTextSplitter
from langchain.text_splitter import NLTKTextSplitter
from langchain.prompts import PromptTemplate
from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from langchain.llms import GPT4All
from llama_index.node_parser.simple import SimpleNodeParser
from llama_index.langchain_helpers.text_splitter import TokenTextSplitter
from llama_index import (
    GPTVectorStoreIndex, 
    LangchainEmbedding, 
    LLMPredictor, 
    ServiceContext, 
    StorageContext, 
    download_loader,
    PromptHelper
)
from llama_index import SimpleDirectoryReader, LangchainEmbedding, GPTListIndex, PromptHelper
from llama_index import LLMPredictor, ServiceContext

from langchain.vectorstores import FAISS
from langchain.schema import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.document_loaders import TextLoader
from llama_index.data_structs.node import Node, DocumentRelationship
from llama_index import LangchainEmbedding, ServiceContext, Document
from llama_index import GPTTreeIndex, SimpleDirectoryReader


from langchain.utilities import SerpAPIWrapper
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from typing import Optional, Type, List
from langchain.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain.tools import DuckDuckGoSearchRun
from langchain.utilities import BingSearchAPIWrapper, DuckDuckGoSearchAPIWrapper
from langchain.tools import DuckDuckGoSearchResults
from langchain.prompts import PromptTemplate

import tempfile
from flask_caching import Cache
temp_dir = tempfile.gettempdir()
import diskcache as dc
cache = dc.Cache(temp_dir)
cache_timeout = 7 * 24 * 60 * 60
# cache = Cache(None, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': temp_dir, 'CACHE_DEFAULT_TIMEOUT': 7 * 24 * 60 * 60})
try:
    from googleapiclient.discovery import build
except ImportError:
    raise ImportError(
        "google-api-python-client is not installed. "
        "Please install it with `pip install google-api-python-client`"
    )

pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

import logging
from common import *

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.ERROR,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)
logger.setLevel(logging.ERROR)
time_logger = logging.getLogger(__name__ + " | TIMING")
time_logger.setLevel(logging.INFO)  # Set log level for this logger

from tenacity import (
    retry,
    RetryError,
    stop_after_attempt,
    wait_random_exponential,
)

import asyncio
import threading
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "gpt-4-turbo-preview": (800000, 10000),
    "gpt-4-32k": (150000, 100),
    "gpt-4-32k-0314": (150000, 100),
    "gpt-4-vision-preview": (150000, 100),
})

openai_model_family = {
    "gpt-3.5-turbo": ["gpt-3.5-turbo", "gpt-3.5-turbo-0301", "gpt-3.5-turbo-0613", "gpt-3.5-turbo-1106"],
    "gpt-3.5-16k": ["gpt-3.5-turbo-16k", "gpt-3.5-turbo-16k-0613", "gpt-3.5-turbo-1106"],
    "gpt-3.5-turbo-instruct": ["gpt-3.5-turbo-instruct", "gpt-3.5-turbo-instruct-0914"],
    "gpt-4": ["gpt-4", "gpt-4-0314", "gpt-4-0613", "gpt-4-32k-0314"],
    "gpt-4-turbo": ["gpt-4-turbo-preview", "gpt-4-vision-preview"],
    "gpt-4-0314": ["gpt-4-0314"],
    "gpt-4-0613": ["gpt-4-0613"],
    "gpt-4-32k": ["gpt-4-32k"],
    "gpt-4-vision-preview": ["gpt-4-vision-preview"],
}

import time
from collections import deque
from threading import Lock

# create a new tokenlimit exception class
class TokenLimitException(Exception):
    pass

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
    "gpt-4-turbo-preview": gpt4_enc,
    "text-davinci-003": davinci_enc,
    "text-davinci-002": davinci_enc,
})
def call_chat_model(model, text, temperature, system, keys):
    api_key = keys["openAIKey"] if "gpt" in model or "davinci" in model else keys["OPENROUTER_API_KEY"]
    if model.startswith("gpt") or "davinci" in model:
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text)))
        rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(system)))
    extras = dict(api_base="https://openrouter.ai/api/v1", base_url="https://openrouter.ai/api/v1",) if not ("gpt" in model or "davinci" in model) else dict()
    response = openai.ChatCompletion.create(
        model=model,
        api_key=api_key,
        stop=["</s>", "Human:", "USER:", "[EOS]", "HUMAN:", "HUMAN :", "Human:", "User:", "USER :", "USER :", "Human :", "###"] if "claude" in model else [],
        messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        temperature=temperature,
        stream=True,
        **extras
    )
    for chunk in response:
        if "content" in chunk["choices"][0]["delta"]:
            text_content = chunk["choices"][0]["delta"]["content"]
            yield text_content
            if "gpt" in model or "davinci" in model:
                rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text_content)))

    if "finish_reason" in chunk["choices"][0] and chunk["choices"][0]["finish_reason"].lower().strip() not in ["stop", "end_turn", "stop_sequence"]:
        yield "\n Output truncated due to lack of context Length."


def call_non_chat_model(model, text, temperature, system, keys):
    api_key = keys["openAIKey"]
    text = f"{system}\n\n{text}\n"
    input_len = len(easy_enc.encode(text))
    assert 3600 - input_len > 0
    rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(text)))
    completions = openai.Completion.create(
        api_key=api_key,
        engine=model,
        prompt=text,
        temperature=temperature,
        max_tokens = 4000 - input_len,
    )
    message = completions.choices[0].text
    finish_reason = completions.choices[0].finish_reason
    if finish_reason.lower().strip() not in ["stop", "end_turn", "stop_sequence"]:
        message = message + "\n Output truncated due to lack of context Length."
    rate_limit_model_choice.add_tokens(model, len(encoders_map.get(model, easy_enc).encode(message)))
    return message

class CallLLm:
    def __init__(self, keys, model_name=None, use_gpt4=False, use_16k=False):

        self.keys = keys
        self.light_system = "You are an expert in science, machine learning, critical reasoning, stimulating discussions, mathematics, problem solving, brainstorming, reading comprehension, information retrieval, question answering and others. \nAlways provide comprehensive, detailed and informative response.\nInclude references inline in wikipedia style as your write the answer.\nUse direct, to the point and professional writing style.\nI am a student and need your help to improve my learning and knowledge,\n"
        self.self_hosted_model_url = self.keys["vllmUrl"] if not checkNoneOrEmpty(self.keys["vllmUrl"]) else None
        self.use_gpt4 = use_gpt4
        self.use_16k = use_16k
        self.gpt4_enc = encoders_map.get("gpt-4")
        self.turbo_enc = encoders_map.get("gpt-3.5-turbo")
        self.model_name = model_name
        self.model_type = "openai" if model_name is None or model_name.startswith("gpt") else "openrouter"


    def __call__(self, text, temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        if self.model_type == "openai":
            return self.__call_openai_models(text, temperature, stream, max_tokens, system, *args, **kwargs)
        else:
            return self.__call_openrouter_models(text, temperature, stream, max_tokens, system, *args, **kwargs)


    def __call_openrouter_models(self, text, temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.light_system
        system = f"{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text) if self.use_gpt4 else self.turbo_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        if "gemini" in self.model_name:
            assert get_gpt3_word_count(system + text) < 90_000
        elif "mistralai" in self.model_name:
            assert get_gpt3_word_count(system + text) < 26000
        elif "claude-3" in self.model_name:
            assert get_gpt3_word_count(system + text) < 90_000
        else:
            assert get_gpt3_word_count(system + text) < 14000
        return call_with_stream(call_chat_model, stream, self.model_name, text, temperature, system, self.keys)

    @retry(wait=wait_random_exponential(min=10, max=30), stop=stop_after_attempt(2))
    def __call_openai_models(self, text, temperature=0.7, stream=False, max_tokens=None, system=None, *args, **kwargs):
        sys_init = self.light_system
        system = f"{system.strip()}" if system is not None and len(system.strip()) > 0 else sys_init
        text_len = len(self.gpt4_enc.encode(text) if self.use_gpt4 else self.turbo_enc.encode(text))
        logger.debug(f"CallLLM with temperature = {temperature}, stream = {stream}, token len = {text_len}")
        if self.self_hosted_model_url is not None:
            raise ValueError("Self hosted models not supported")
        else:
            assert self.keys["openAIKey"] is not None


        if self.use_gpt4 and self.use_16k:
            try:
                assert text_len < 90000
            except AssertionError as e:
                text = get_first_last_parts(text, 40000, 50000, self.gpt4_enc)
            try:
                model = rate_limit_model_choice.select_model("gpt-4-turbo")
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)
            except TokenLimitException as e:
                time.sleep(5)
                try:
                    model = rate_limit_model_choice.select_model("gpt-4-turbo")
                except:
                    try:
                        text = get_first_last_parts(text, 7000, 6000, self.turbo_enc)
                        model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    except:
                        raise e
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                time.sleep(5)
                try:
                    model = rate_limit_model_choice.select_model("gpt-4-turbo")
                except:
                    try:
                        model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    except:
                        raise e
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)

        elif self.use_gpt4:
#             logger.info(f"Try GPT4 models with stream = {stream}, use_gpt4 = {self.use_gpt4}")
            try:
                assert text_len < 7600
            except AssertionError as e:
                text = get_first_last_parts(text, 4000, 3500, self.gpt4_enc)
            try:
                model = rate_limit_model_choice.select_model("gpt-4")
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)
            except TokenLimitException as e:
                time.sleep(5)
                try:
                    model = rate_limit_model_choice.select_model("gpt-4")
                except:
                    try:
                        model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    except:
                        raise e
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                time.sleep(5)
                try:
                    model = rate_limit_model_choice.select_model("gpt-4")
                except:
                    try:
                        model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    except:
                        raise e
                return call_with_stream(call_chat_model, stream, model, text, temperature, system, self.keys)
        elif not self.use_16k:
            assert text_len < 3800
            try:

                model = rate_limit_model_choice.select_model("gpt-3.5-turbo")
                return call_with_stream(call_chat_model if "instruct" not in model else call_non_chat_model, stream, model, text, temperature, system, self.keys)
            except TokenLimitException as e:
                time.sleep(5)
                model = rate_limit_model_choice.select_model("gpt-3.5-turbo")
                fn = call_chat_model if "instruct" not in model else call_non_chat_model

                return call_with_stream(fn, stream, model, text, temperature, system, self.keys)
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                model = rate_limit_model_choice.select_model("gpt-3.5-turbo")
                fn = call_chat_model if "instruct" not in model else call_non_chat_model

                return call_with_stream(fn, stream, model, text, temperature, system, self.keys)
        elif self.use_16k:
            try:
                if text_len > 3400:
                    model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    logger.debug(f"Try 16k model with stream = {stream} with text len = {text_len}")
                else:
                    model = rate_limit_model_choice.select_model("gpt-3.5-turbo")

                    logger.debug(f"Try Turbo model with stream = {stream} with text len = {text_len}")
                assert text_len < 15000
#                 logger.info(f"Try 16k model with stream = {stream}")
                return call_with_stream(call_chat_model if "instruct" not in model else call_non_chat_model, stream, model, text, temperature, system, self.keys)
            except TokenLimitException as e:
                time.sleep(5)
                if text_len > 3400:
                    model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    logger.debug(f"Try 16k model with stream = {stream} with text len = {text_len}")
                else:
                    model = rate_limit_model_choice.select_model("gpt-3.5-turbo")

                return call_with_stream(call_chat_model if "instruct" not in model else call_non_chat_model, stream,
                                        model, text, temperature, system, self.keys)
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                if text_len > 3400:
                    model = rate_limit_model_choice.select_model("gpt-3.5-16k")
                    logger.debug(f"Try 16k model with stream = {stream} with text len = {text_len}")
                else:
                    model = rate_limit_model_choice.select_model("gpt-3.5-turbo")
                return call_with_stream(call_chat_model if "instruct" not in model else call_non_chat_model, stream,
                                        model, text, temperature, system, self.keys)
        else:
            raise ValueError("No model use criteria met")



        
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


class Summarizer:
    def __init__(self, keys, is_detailed=False):
        self.keys = keys
        self.is_detail = is_detailed
        self.name = "Summariser"
        self.description = """
Summarizer:
    This tool takes a text document and summarizes it into a shorter version while preserving the main points and context. Useful when the document is too long and needs to be shortened before further processing.

    Input params/args: 
        text_document (str): document to summarize.

    Returns: 
        str: summarized_document.

    Usage:
        `summary = Summarizer()(text_document="document to summarize") # Note: this tool needs to be initialized first.`
    """
        template = f""" 
Write a {"detailed and informational " if is_detailed else ""}summary of the document below while preserving the main points and context, do not miss any important details, do not remove mathematical details and references.
Document to summarize is given below.
'''{{document}}'''

Write {"detailed and informational " if is_detailed else ""}Summary below.
"""
        self.prompt = PromptTemplate(
            input_variables=["document"],
            template=template,
        )
    @timer
    def __call__(self, text_document):
        prompt = self.prompt.format(document=text_document)
        return CallLLm(self.keys, model_name="mistralai/mistral-medium", use_gpt4=False)(prompt, temperature=0.5)
    

process_text_executor = ThreadPoolExecutor(max_workers=1)
def contrain_text_length_by_summary(text, keys, threshold=2000):
    summariser = Summarizer(keys)
    tlc = partial(TextLengthCheck, threshold=threshold)
    return text if tlc(text) else summariser(text)

def process_text(text, chunk_size, my_function, keys):
    # Split the text into chunks
    chunks = [c.strip() for c in list(ChunkText(text, chunk_size)) if len(c.strip()) > 0]
    if len(chunks) == 0:
        return 'No relevant information found.'
    if len(chunks) > 1:
        futures = [process_text_executor.submit(my_function, chunk) for chunk in chunks]
        # Get the results from the futures
        results = [future.result() for future in futures]
    else:
        results = [my_function(chunk) for chunk in chunks]

    threshold = 512*3
    
    while len(results) > 1:
        logger.warning(f"--- process_text --- Multiple chunks as result. Results len = {len(results)} and type of results =  {type(results[0])}")
        assert isinstance(results[0], str)
        results = [process_text_executor.submit(contrain_text_length_by_summary, r, keys, threshold) for r in results]
        results = [future.result() for future in results]
        results = combine_array_two_at_a_time(results, '\n\n')
    assert len(results) == 1
    results = results[0]
    # threshold = 384
    # tlc = partial(TextLengthCheck, threshold=threshold)
    # if not tlc(results):
    #     summariser = Summarizer(keys, is_detailed=True)
    #     logger.warning(f"--- process_text --- Calling Summarizer on single result with single result len = {len(results.split())}")
    #     results = summariser(results)
    #     logger.warning(
    #         f"--- process_text --- Called Summarizer and final result len = {len(results.split())}")
    
    # if not tlc(results):
    #     logger.warning("--- process_text --- Calling ReduceRepeatTool")
    #     results = ReduceRepeatTool(keys)(results)
    assert isinstance(results, str)
    return results

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
        self.description = """
ContextualReader:
    This tool takes a context/query/instruction, and a text document. It reads the document based on the context or query instruction and outputs only parts of document relevant to the query. Useful when the document is too long and you need to store a short contextual version of it for answering the user request. Sometimes rephrasing the query/question/user request before asking the ContextualReader helps ContextualReader provide better results. You can also specify directives to ContextualReader like "return numbers only", along with the query for better results.

    Input params/args: 
        context_user_query (str): instructions or query on how to read the document to provide contextually useful content from the document.
        text_document (str): document to read and provide information from using context_user_query.

    Returns: 
        str: contextual_content_from_document

    Usage:
        `contextual_content_from_document = ContextualReader()(context_user_query="instructions on how to read document", text_document="document to read") # Note: this tool needs to be initialized first.`

    """
        # Use markdown formatting to typeset or format your answer better.
        long_or_short = "Provide a short, brief, concise and informative response in 3-4 sentences. \n" if provide_short_responses else "Provide concise, comprehensive and informative response. Output any relevant equations if found in latex format.\n"
        response_prompt = "Write short, concise and informative" if provide_short_responses else "Write concise, comprehensive and informative"
        self.prompt = PromptTemplate(
            input_variables=["context", "document"],
            template=f"""You are an information retrieval agent. {long_or_short}
Provide relevant and helpful information from the given document for the given user question and conversation context given below.
'''{{context}}'''

Document to read and extract information from is given below.
'''
{{document}}
'''

Only provide answer from the document given above.
{response_prompt} response below.
""",
        )
        # If no relevant information is found in given context, then output "No relevant information found." only.
        
    def get_one(self, context, document,):
        import inspect
        prompt = self.prompt.format(context=context, document=document)
        wc = get_gpt3_word_count(prompt)
        try:
            llm = CallLLm(self.keys, model_name="anthropic/claude-3-haiku:beta", use_gpt4=False, use_16k=False)
            result = llm(prompt, temperature=0.4, stream=False)
        except:
            llm = CallLLm(self.keys, model_name="anthropic/claude-instant-1.2", use_gpt4=False, use_16k=False)
            result = llm(prompt, temperature=0.4, stream=False)
        assert isinstance(result, str)
        return result

    def get_one_with_rag(self, context, chunk_size, document):

        import inspect
        openai_embed = get_embedding_model(self.keys)
        def get_doc_embeds(document):
            document = document.strip()
            ds = document.split(" ")
            document = " ".join(ds[:128_000])
            wc = len(ds)
            if wc < 8000:
                chunk_size = 512
            elif wc < 16000:
                chunk_size = 1024
            elif wc < 32000:
                chunk_size = 1536
            else:
                chunk_size = 2048
            chunks = ChunkText(text_document=document, chunk_size=chunk_size)
            doc_embeds = openai_embed.embed_documents(chunks)
            return chunks, chunk_size, np.array(doc_embeds)
        doc_em_future = get_async_future(get_doc_embeds, document)
        query_em_future =  get_async_future(openai_embed.embed_query, context)
        chunks, chunk_size, doc_embedding = doc_em_future.result()
        query_embedding = np.array(query_em_future.result())
        # doc embeddins is 2D but query embedding is 1D, we want to find the closest chunk to query embedding by cosine similarity
        scores = np.dot(doc_embedding, query_embedding)
        sorted_chunks = sorted(list(zip(chunks, scores)), key=lambda x: x[1], reverse=True)
        top_chunks = sorted_chunks[:8]
        top_chunks_text = ""
        for idx, tc in enumerate(top_chunks):
            top_chunks_text += f"Retrieved relevant text chunk {idx+1}:\n{tc[0]}\n\n"
        top_chunks = top_chunks_text
        fragments_text = f"Fragments of document relevant to the query are given below.\n\n{top_chunks}\n\n"
        prompt = self.prompt.format(context=context, document=fragments_text)
        callLLm = CallLLm(self.keys, model_name="google/gemini-pro")
        result = callLLm(prompt, temperature=0.4, stream=False)
        assert isinstance(result, str)
        return result

    def __call__(self, context_user_query, text_document, chunk_size=TOKEN_LIMIT_FOR_SHORT):
        assert isinstance(text_document, str)
        import functools
        st = time.time()
        # part_fn = functools.partial(self.get_one_with_exception, context_user_query, chunk_size)
        # result = process_text(text_document, chunk_size, part_fn, self.keys)
        doc_word_count = get_gpt3_word_count(text_document)
        short = self.provide_short_responses and doc_word_count < int(TOKEN_LIMIT_FOR_SHORT * 1.0) and not self.scan
        if doc_word_count < TOKEN_LIMIT_FOR_DETAILED:
            rag_result = None
            if self.scan:
                rag_result = get_async_future(self.get_one_with_rag, context_user_query, None,
                                              text_document) if not short else None
            result = self.get_one(context_user_query, text_document)
            if self.scan:
                rag_result = rag_result.result() if rag_result is not None and rag_result.exception() is None else ""
                result = result + "\nMore Details:\n" + rag_result
        elif doc_word_count < TOKEN_LIMIT_FOR_EXTRA_DETAILED and doc_word_count> TOKEN_LIMIT_FOR_DETAILED:
            rag_result = get_async_future(self.get_one_with_rag, context_user_query, None, text_document) if not short else None
            result = self.get_one(context_user_query, text_document)
            rag_result = rag_result.result() if rag_result is not None and rag_result.exception() is None else ""
            result = result + "\nMore Details:\n" + rag_result
        elif self.scan and doc_word_count > TOKEN_LIMIT_FOR_EXTRA_DETAILED:
            chunks = ChunkText(text_document, chunk_size=TOKEN_LIMIT_FOR_EXTRA_DETAILED, chunk_overlap=0)
            first_chunk = chunks[0]
            second_result = None
            rag_result = None
            if len(chunks) > 1:
                first_chunk = first_chunk + "..."
                second_chunk = first_chunk[:1000] + "\n...\n" + chunks[1]
                second_result = get_async_future(self.get_one, context_user_query,
                                                 second_chunk)
            if len(chunks) > 2:
                rag_result = get_async_future(self.get_one_with_rag, context_user_query, None, "\n\n".join(chunks[2:]))
            else:
                rag_result = get_async_future(self.get_one_with_rag, context_user_query, None,
                                              text_document) if not short else None

            result = self.get_one(context_user_query, first_chunk)
            result = result + "\n" + (second_result.result() if len(chunks) > 1 and second_result is not None else "") + "\n" + (rag_result.result() if rag_result is not None and rag_result.exception() is None else "") + "\n"
        else:
            try:
                rag_result = get_async_future(self.get_one_with_rag, context_user_query, None,
                                              text_document) if not short else None
                result = self.get_one(context_user_query, text_document)
                rag_result = rag_result.result() if rag_result is not None and rag_result.exception() is None else ""
                result = result + "\nMore Details:\n" + rag_result
            except Exception as e:
                logger.warning(f"ContextualReader:: RAG failed with exception {str(e)}")
                chunks = ChunkText(text_document, chunk_size=TOKEN_LIMIT_FOR_DETAILED, chunk_overlap=0)
                result = self.get_one(context_user_query, chunks[0])

        result = get_first_last_parts(result, 512, 256) if short else get_first_last_parts(result, 1536 if self.scan else 512, 1024 if self.scan else 384)
        assert isinstance(result, str)
        et = time.time()
        time_logger.info(f"ContextualReader took {(et-st):.2f} seconds for chunk size {chunk_size}")
        return result

@typed_memoize(cache, str, int, tuple, bool)
def call_contextual_reader(query, document, keys, provide_short_responses=False, chunk_size=TOKEN_LIMIT_FOR_SHORT//2, scan=False)->str:
    assert isinstance(document, str)
    cr = ContextualReader(keys, provide_short_responses=provide_short_responses, scan=scan)
    return cr(query, document, chunk_size=chunk_size+512)


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

def search_post_processing(query, results, only_science_sites=False, only_pdf=False):
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
        if only_science_sites is not None and only_science_sites and "arxiv.org" not in link and "openreview.net" not in link:
            continue
        if only_science_sites is not None and not only_science_sites and ("arxiv.org" in link or "openreview.net" in link):
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
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    return dedup_results

@typed_memoize(cache, str, int, tuple, bool)
def bingapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
    from datetime import datetime, timedelta
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365*3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None
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
    og_query = query
    no_after_query = f"{query}{site_string}{search_pdf}"
    query = f"{query}{site_string}{after_string}{search_pdf}"
    more_res = None
    if num > 10:
        more_res = get_async_future(search.results, query, 10)
    results = search.results(query, num)
    expected_res_length = max(num, 10)
    if num > 10:
        results.extend(more_res.result() if more_res is not None and more_res.exception() is None else [])
    if len(results) < expected_res_length:
        results.extend(search.results(no_after_query, num))
    if len(results) < expected_res_length:
        results.extend(search.results(og_query, num))
    dedup_results = search_post_processing(pre_query, results, only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(f"Called BING API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results


def brightdata_google_serp(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
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
    expected_res_length = max(num, 10)
    def search_google(query):
        # URL encode the query
        encoded_query = requests.utils.quote(query)
        # Set up the URL
        url = f"https://www.google.com/search?q={encoded_query}&gl=us&num={num}&brd_json=1"
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
    results = search_google(query)
    if len(results) < expected_res_length:
        results.extend(search_google(no_after_query))
    if len(results) < expected_res_length:
        results.extend(search_google(og_query))
    for r in results:
        _ = r.pop("image", None)
        _ = r.pop("image_alt", None)
        _ = r.pop("image_url", None)
        _ = r.pop("global_rank", None)
        _ = r.pop("image_base64", None)
    dedup_results = search_post_processing(pre_query, results, only_science_sites=only_science_sites, only_pdf=only_pdf)
    return dedup_results

@typed_memoize(cache, str, int, tuple, bool)
def googleapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
    from langchain.utilities import GoogleSearchAPIWrapper
    from datetime import datetime, timedelta
    num=max(num, 10)
    
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365*3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None
    cse_id = key["cx"]
    google_api_key = key["api_key"]
    service = build("customsearch", "v1", developerKey=google_api_key)

    search = GoogleSearchAPIWrapper(google_api_key=google_api_key, google_cse_id=cse_id)
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

    expected_res_length = max(num, 10)
    more_res = None
    if num > 10:
        more_res = get_async_future(search.results, query, min(num, 10), search_params={"filter": "1", "start": "11"})
    results = search.results(query, min(num, 10), search_params={"filter":"1", "start": "1"})
    if num > 10:
        results.extend(more_res.results() if more_res is not None and more_res.exception() is None else [])
    if len(results) < expected_res_length:
        results.extend(search.results(no_after_query, min(num, 10), search_params={"filter":"1", "start": "1"}))
    if len(results) < expected_res_length:
        results.extend(search.results(no_after_query, min(num, 10), search_params={"filter":"1", "start": str(len(results)+1)}))
    if len(results) < expected_res_length:
        results.extend(search.results(og_query, min(num, 10), search_params={"filter":"1", "start": str(len(results)+1)}))
    dedup_results = search_post_processing(pre_query, results, only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(f"Called GOOGLE API with args = {query}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results

@typed_memoize(cache, str, int, tuple, bool)
def serpapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
    from datetime import datetime, timedelta
    import requests
    
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
        two_years_ago = now - timedelta(days=365*3)
        date_string = two_years_ago.strftime("%Y-%m-%d")
    else:
        now = None

    
    location = random.sample(["New Delhi", "New York", "London", "Berlin", "Sydney", "Tokyo", "Washington D.C.", "Seattle", "Amsterdam", "Paris"], 1)[0]
    gl = random.sample(["us", "uk", "fr", "ar", "ci", "dk", "ec", "gf", "hk", "is", "in", "id", "pe", "ph", "pt", "pl"], 1)[0]
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
    params = {
       "q": query,
       "api_key": key,
       "num": num,
       "no_cache": False,
        "location": location,
        "gl": gl,
       }
    response = requests.get(url, params=params)
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
        rjs = requests.get(url, params={"q": og_query, "api_key": key, "num": min(num, 10), "no_cache": False, "location": location, "gl": gl}).json()
        if "organic_results" in rjs:
            results.extend(["organic_results"])
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    dedup_results = search_post_processing(pre_query, results, only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(f"Called SERP API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results


@typed_memoize(cache, str, int, tuple, bool)
def gscholarapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
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
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    dedup_results = search_post_processing(pre_query, results, only_science_sites=only_science_sites, only_pdf=only_pdf)
    logger.debug(
        f"Called SERP Google Scholar API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    return dedup_results
    
# TODO: Add caching
from web_scraping import web_scrape_page, soup_html_parser


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
@typed_memoize(cache, str, int, tuple, bool)
def freePDFReader(url, page_ranges=None):
    from langchain.document_loaders import PyPDFLoader
    loader = PyPDFLoader(url)
    pages = loader.load_and_split()
    if page_ranges:
        start, end = page_ranges.split("-")
        start = int(start) - 1
        end = int(end) - 1
        " ".join([pages[i].page_content for i in range(start, end+1)])
    return " ".join([p.page_content for p in pages])

class CustomPDFLoader(MathpixPDFLoader):
    def __init__(self, file_path, processed_file_format: str = "mmd",
        max_wait_time_seconds: int = 500,
        should_clean_pdf: bool = False,
        **kwargs):
        from langchain.utils import get_from_dict_or_env
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
    @typed_memoize(cache, str, int, tuple, bool)
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

@typed_memoize(cache, str, int, tuple, bool)
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

@typed_memoize(cache, str, int, tuple, bool)
def get_paper_details_from_semantic_scholar(arxiv_url):
    print(f"get_paper_details_from_semantic_scholar with {arxiv_url}")
    arxiv_id = arxiv_url.split("/")[-1].replace(".pdf", '').strip()
    from semanticscholar import SemanticScholar
    sch = SemanticScholar()
    paper = sch.get_paper(f"ARXIV:{arxiv_id}")
    return paper



# TODO: Add caching
def web_search_part1(context, doc_source, doc_context, api_keys, year_month=None,
                     previous_answer=None, previous_search_results=None, extra_queries=None,
                     gscholar=False, provide_detailed_answers=False, start_time=None,):

    # TODO: if it is scientific or knowledge based question, then use google scholar api, use filetype:pdf and site:arxiv.org OR site:openreview.net OR site:arxiv-vanity.com OR site:arxiv-sanity.com OR site:bioRxiv.org OR site:medrxiv.org OR site:aclweb.org
    st = time.time()
    start_time = start_time if start_time is not None else st
    provide_detailed_answers = int(provide_detailed_answers)
    if extra_queries is None:
        extra_queries = []
    n_query = "two" if previous_search_results or len(extra_queries) > 0 else "four"
    n_query = n_query if provide_detailed_answers >= 3 else "two"
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
    if (len(extra_queries) < 1) or (len(extra_queries) < 2 and provide_detailed_answers >= 2):
        # TODO: explore generating just one query for local LLM and doing that multiple times with high temperature.
        query_strings = CallLLm(api_keys, use_gpt4=False)(prompt, temperature=0.5, max_tokens=100)
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
    else:
        query_strings = extra_queries
    year = int(datetime.now().strftime("%Y"))
    month = datetime.now().strftime("%B")
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

    yield {"type": "query", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month, "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers}
    time_logger.info(f"Time taken for web search part 1 query preparation = {(time.time() - st):.2f}")
    serp_available = "serpApiKey" in api_keys and api_keys["serpApiKey"] is not None and len(api_keys["serpApiKey"].strip()) > 0
    bing_available = "bingKey" in api_keys and api_keys["bingKey"] is not None and len(api_keys["bingKey"].strip()) > 0
    google_available = ("googleSearchApiKey" in api_keys and api_keys["googleSearchApiKey"] is not None and len(api_keys["googleSearchApiKey"].strip()) > 0) and ("googleSearchCxId" in api_keys and api_keys["googleSearchCxId"] is not None and len(api_keys["googleSearchCxId"].strip()) > 0)
    if len(extra_queries) > 0:
        num_res = 20
    else:
        num_res = 10
    
    if year_month:
        year_month = datetime.strptime(year_month, "%Y-%m").strftime("%Y-%m-%d")
    search_st = time.time()
    if os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None and serp_available and google_available and bing_available:
        serps = [get_async_future(brightdata_google_serp, query, os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                  our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                 query_strings]
        serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                       only_pdf=None, only_science_sites=None) for query in query_strings])
        serps.extend([get_async_future(googleapi, query,
                                       dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
                                       num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                      query in query_strings])
        serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res + 10, our_datetime=None,
                                       only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar:
            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper in {year}", api_keys["bingKey"], num_res,
                                           our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {str(year - 1)}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(googleapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(gscholarapi, query + f" in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])
    if os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None and serp_available and google_available:
        serps = [get_async_future(brightdata_google_serp, query, os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                  our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                 query_strings]
        serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings])
        serps.extend([get_async_future(googleapi, query,
                                       dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
                                       num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                      query in query_strings])
        if gscholar:

            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {str(year-1)}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper", os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                  our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                 query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(googleapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                      only_pdf=None, only_science_sites=None) for query in
                     query_strings])
            serps.extend([get_async_future(gscholarapi, query + f" in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])
    elif os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None and serp_available:

        serps = [get_async_future(brightdata_google_serp, query, os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                  our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                 query_strings]
        serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar:

            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {str(year-1)}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend(
                [get_async_future(gscholarapi, query + f" in {year}", api_keys["serpApiKey"],
                                  num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in
                 query_strings])
    elif os.getenv("BRIGHTDATA_SERP_API_PROXY", None) is not None:

        serps = [get_async_future(brightdata_google_serp, query, os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res + 10,
                          our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings]
        if gscholar:

            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {str(year-1)}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None, only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                 enumerate(query_strings)])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(brightdata_google_serp, query + f" research paper in {year}",
                                           os.getenv("BRIGHTDATA_SERP_API_PROXY"), num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
    elif google_available and serp_available:
        serps = [get_async_future(googleapi, query,
                                  dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
                                  num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in query_strings]
        serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar:
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend(
                [get_async_future(gscholarapi, query + f" recent research papers in {year}", api_keys["serpApiKey"],
                                  num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in
                 query_strings])
            serps.extend([get_async_future(googleapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(googleapi, query + f" research paper in {str(year - 1)}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])

    elif google_available and bing_available:
        serps = [get_async_future(googleapi, query,
                                  dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
                                  num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in query_strings]
        serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res + 10, our_datetime=None, only_pdf=None, only_science_sites=None) for query in query_strings])

        if gscholar:
            serps.extend([get_async_future(googleapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(googleapi, query + f" research paper in {str(year - 1)}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper in {year}", api_keys["bingKey"], num_res,
                                           our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])

        logger.debug(f"Using GOOGLE for web search, serps len = {len(serps)}")

    elif serp_available and bing_available:
        serps = [get_async_future(bingapi, query, api_keys["bingKey"], num_res + 10, our_datetime=None, only_pdf=None,
                          only_science_sites=None) for query in query_strings]
        serps.extend([get_async_future(serpapi, query, api_keys["serpApiKey"], num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings])
        if gscholar:
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend(
                [get_async_future(gscholarapi, query + f" recent research papers in {year}", api_keys["serpApiKey"],
                                  num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in
                 query_strings])
            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper in {year}", api_keys["bingKey"], num_res,
                                           our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
    elif serp_available:
        serps = [get_async_future(serpapi, query, api_keys["serpApiKey"], num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings]
        if gscholar:

            serps.extend([get_async_future(serpapi, query + f" research paper in {year}", api_keys["serpApiKey"],
                                           num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                          query in
                          query_strings])
            serps.extend([get_async_future(serpapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], num_res,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(gscholarapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
            serps.extend(
                [get_async_future(gscholarapi, query + f" recent research papers in {year}", api_keys["serpApiKey"],
                                  num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for
                 query in
                 query_strings])
        logger.debug(f"Using SERP for web search, serps len = {len(serps)}")
    elif google_available:

        # serps = [googleapi(query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), num_res, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings] + \
        #         [googleapi(query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
        #                    num_res, our_datetime=year_month, only_pdf=True, only_science_sites=None) for query in
        #          query_strings] + \
        #         [googleapi(query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]),
        #                    num_res, our_datetime=year_month, only_pdf=False, only_science_sites=True) for query in
        #          query_strings]
        serps = [get_async_future(googleapi, query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), num_res + 10, our_datetime=year_month, only_pdf=None, only_science_sites=None) for query in query_strings]

        if gscholar:

            serps.extend([get_async_future(googleapi, query + f" research paper in {year}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])
            serps.extend([get_async_future(googleapi, query + f" research paper in {str(year - 1)}",
                                           api_keys["serpApiKey"], 10,
                                           our_datetime=year_month, only_pdf=True if ix % 2 == 1 else None,
                                           only_science_sites=True if ix % 2 == 0 else None) for ix, query in
                          enumerate(query_strings)])

        logger.debug(f"Using GOOGLE for web search, serps len = {len(serps)}")

    elif bing_available:

        serps = [get_async_future(bingapi, query, api_keys["bingKey"], num_res + 10, our_datetime=None, only_pdf=None, only_science_sites=None) for query in query_strings]
        if gscholar:

            serps.extend([get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=True, only_science_sites=None) for query in
                          query_strings])
            serps.extend([get_async_future(bingapi, query + f" research paper in {year}", api_keys["bingKey"], num_res, our_datetime=None,
                                           only_pdf=None, only_science_sites=None) for query in
                          query_strings])
        logger.debug(f"Using BING for web search, serps len = {len(serps)}")
    else:
        serps = []
        logger.warning(f"Neither GOOGLE, Bing nor SERP keys are given but Search option choosen.")
        yield {"type": "error", "error": "Neither GOOGLE, Bing nor SERP keys are given but Search option choosen."}
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
    # logger.error(f"Total number of queries = {len(query_strings)} and total serps = {len(serps)}")
    for ix, s in enumerate(as_completed(serps)):
        time_logger.debug(f"Time taken for {ix}-th serp result in web search part 1 = {(time.time() - search_st):.2f}")
        if s.exception() is None and s.done():
            for iqx, r in enumerate(s.result()):
                query = remove_year_month_substring(r.get("query", "").lower()).replace("recent research papers", "").replace("research paper", "").replace("research papers", "").strip()
                title = r.get("title", "").lower()
                cite_text = f"""{(f" Cited by {r['citations']}") if r['citations'] else ""}"""
                title = title + f" ({r['year'] if r['year'] else ''})" + f"{cite_text}"
                link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace(
                    "v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8",
                                                                                                              '').replace(
                    "v9", '')
                link = convert_to_pdf_link_if_needed(link)
                result_context = context + "?\n" + query
                full_queue.append({"query": query, "title": title, "link": link, "context": result_context, "type": "result", "rank": iqx})
                if title in seen_titles or len(
                        title) == 0 or link in deduped_results or "youtube.com" in link or "twitter.com" in link or "https://ieeexplore.ieee.org" in link or "https://www.sciencedirect.com" in link:
                    deduped_results.add(link)
                    seen_titles.add(title)
                    continue

                if link not in deduped_results and title not in seen_titles and (
                        query not in query_vs_results_count or query_vs_results_count[query] <= (4 if provide_detailed_answers <= 2 else 5)):
                    yield {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                         "rank": iqx, "start_time": start_time}
                    query_vs_results_count[query] += 1
                    total_count += 1
                    time_logger.debug(
                        f"Time taken for getting search results n= {total_count}-th in web search part 1 [Main Loop] = {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}")
                elif link not in deduped_results and title not in seen_titles:
                    temp_queue.put(
                        {"query": query, "title": title, "link": link, "context": result_context, "type": "result",
                         "rank": iqx, "start_time": start_time})

                try:
                    min_key, min_count = min(query_vs_results_count.items(), key=itemgetter(1))
                except (ValueError, AssertionError):
                    min_key = query
                    min_count = 0
                if len(query_vs_results_count) >= 4 and not temp_queue.empty() and total_count <= ((provide_detailed_answers  + 2) * 10):
                    keys, _ = zip(*query_vs_results_count.most_common()[:-3:-1])
                    qs = temp_queue.qsize()
                    iter_times = 0
                    put_times = 0
                    while not temp_queue.empty() and iter_times < qs and put_times < 2:
                        iter_times += 1
                        r = temp_queue.get()
                        rq = r.get("query", "")
                        if rq == min_key or rq in keys:
                            put_times += 1
                            yield r
                            total_count += 1
                            query_vs_results_count[rq] += 1
                            time_logger.debug(
                                f"Time taken for getting search results n= {total_count}-th in web search part 1 [Sub Loop] = {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}")
                        else:
                            temp_queue.put(r)
                deduped_results.add(link)
                seen_titles.add(title)
    while not temp_queue.empty() and total_count <= ((provide_detailed_answers  + 2) * 10):
        r = temp_queue.get()
        yield r
        total_count += 1
        query_vs_results_count[r.get("query", "")] += 1
        time_logger.debug(
            f"Time taken for getting search results n= {total_count}-th in web search part 1 [Post all serps] = {(time.time() - search_st):.2f}, full time = {(time.time() - st):.2f}")
    yield {"type": "end", "query": query_strings, "query_type": "web_search_part1", "year_month": year_month, "gscholar": gscholar, "provide_detailed_answers": provide_detailed_answers, "full_results": full_queue}


def web_search_queue(context, doc_source, doc_context, api_keys, year_month=None, previous_answer=None, previous_search_results=None, extra_queries=None, gscholar=False, provide_detailed_answers=False, web_search_tmp_marker_name=None):
    part1_res = get_async_future(web_search_part1, context, doc_source, doc_context, api_keys, year_month, previous_answer, previous_search_results, extra_queries, gscholar, provide_detailed_answers)
    gen1, gen2 = thread_safe_tee(part1_res.result(), 2)
    read_queue = queued_read_over_multiple_links(gen2, api_keys, provide_detailed_answers=max(0, int(provide_detailed_answers) - 1),
                                                 web_search_tmp_marker_name=web_search_tmp_marker_name)
    return [get_async_future(get_part_1_results, gen1), read_queue] # get_async_future(get_part_1_results, part1_res)

def get_part_1_results(part1_res):
    queries = next(part1_res)["query"]
    results = []
    end_result = None
    for r in part1_res:
        if isinstance(r, dict) and r["type"] == "result" and len(results) <= 10:
            results.append(r)
        if len(results) == 10:
            yield {"search_results": results, "queries": queries}
        if r["type"] == "end":
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

def web_search_part2(part1_res, api_keys, provide_detailed_answers=False, web_search_tmp_marker_name=None):
    result_queue = queued_read_over_multiple_links(part1_res, api_keys,
                                                 provide_detailed_answers=max(0, int(provide_detailed_answers) - 1),
                                                 web_search_tmp_marker_name=web_search_tmp_marker_name)
    web_text_accumulator = []
    full_info = []
    qu_st = time.time()
    cut_off = (10 if provide_detailed_answers <= 1 else 16) if provide_detailed_answers else 6
    while True:
        qu_wait = time.time()
        break_condition = len(web_text_accumulator) >= cut_off or (qu_wait - qu_st) > 45
        if break_condition and result_queue.empty():
            break
        one_web_result = result_queue.get()
        qu_et = time.time()
        if one_web_result is None:
            continue
        if one_web_result == TERMINATION_SIGNAL:
            break

        if one_web_result["text"] is not None and one_web_result["text"].strip() != "":
            web_text_accumulator.append(one_web_result["text"])
            logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result: {(qu_et - qu_st):.2f}")
        if one_web_result["full_info"] is not None and isinstance(one_web_result["full_info"], dict):
            full_info.append(one_web_result["full_info"])
    web_text = "\n\n".join(web_text_accumulator)
    all_results_doc, links, titles, contexts, web_links, web_titles, web_contexts, texts, query_strings, rerank_query, rerank_available = part1_res.result()
    return {"text": web_text, "full_info": full_info, "search_results": all_results_doc, "queries": query_strings}


import multiprocessing
from multiprocessing import Pool

def process_link(link_title_context_apikeys, use_large_context=False):
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    key = f"process_link-{str([link, context, detailed, use_large_context])}"
    key = str(mmh3.hash(key, signed=False))
    result = cache.get(key)
    if result is not None and "full_text" in result and len(result["full_text"].strip()) > 0:
        return result
    st = time.time()
    link_data = download_link_data(link_title_context_apikeys)
    title = link_data["title"]
    text = link_data["full_text"]
    query = f"Lets write a comprehensive summary essay with full details, nuances and caveats about [{title}]({link}). Then lets analyse in detail about [{title}]({link}) ( ```preview - '{text[:1000]}'``` ) in the context of the the below question ```{context}```\n"
    link_title_context_apikeys = (link, title, context, api_keys, text, query, detailed)
    try:
        if detailed >= 1:
            more_summary = get_async_future(get_downloaded_data_summary, (link, title, context, api_keys, query, "", detailed), use_large_context=True)
        summary = get_downloaded_data_summary(link_title_context_apikeys, use_large_context=use_large_context)["text"]
        if detailed >= 2:
            more_summary = more_summary.result() if more_summary.exception() is None else ""
            summary = f"{summary}\n\n{more_summary}"

    except AssertionError as e:
        return {"link": link, "title": title, "text": '', "exception": False, "full_text": text, "detailed": detailed}
    logger.debug(f"Time for processing PDF/Link {link} = {(time.time() - st):.2f}")
    cache.set(key, {"link": link, "title": title, "text": summary, "exception": False, "full_text": text, "detailed": detailed},
              expire=cache_timeout)
    return {"link": link, "title": title, "text": summary, "exception": False, "full_text": text, "detailed": detailed}

from concurrent.futures import ThreadPoolExecutor
@timer
def download_link_data(link_title_context_apikeys, web_search_tmp_marker_name=None):
    st = time.time()
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    key = f"download_link_data-{str([link])}"
    key = str(mmh3.hash(key, signed=False))
    result = cache.get(key)
    if result is not None and "full_text" in result and len(result["full_text"].strip()) > 0:
        result["full_text"] = result["full_text"].replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
        return result
    link = convert_to_pdf_link_if_needed(link)
    is_pdf = is_pdf_link(link)
    link_title_context_apikeys = (link, title, context, api_keys, text, detailed)
    if is_pdf:
        result = read_pdf(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        result["is_pdf"] = True
    else:
        result = get_page_text(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        result["is_pdf"] = False
    if "full_text" in result and len(result["full_text"].strip()) > 0 and len(result["full_text"].strip().split()) > 100:
        result["full_text"] = result["full_text"].replace('<|endoftext|>', '\n').replace('endoftext',
                                                                                         'end_of_text').replace(
            '<|endoftext|>', '')
        cache.set(key, result, expire=cache_timeout)
    else:
        assert len(result["full_text"].strip().split()) > 100, f"[download_link_data] Text too short for link {link}"
    et = time.time() - st
    time_logger.info(f"Time taken to download link data for {link} = {et:.2f}")
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
        'PageRange': '1-50'
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


def get_arxiv_pdf_link(link):
    try:
        assert "arxiv.org" in link
        import re
        from bs4 import BeautifulSoup, SoupStrainer
        # convert to ar5iv link
        arxiv_id = link.replace(".pdf", "").split("/")[-1]
        new_link = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        logger.debug(f"Converted arxiv link {link} to {new_link}")
        status_future = get_async_future(requests.head, new_link, timeout=10)
        arxiv_text = requests.get(new_link, timeout=10).text
        status = status_future.result()
        assert status.status_code == 200, f"Error converting arxiv link {link} to ar5iv link with status code {status.status_code}"
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
            soupy = soup_html_parser(arxiv_text)
            text = soupy["text"]
            title = soupy["title"]
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
    key = f"read_pdf-{str([link])}"
    key = str(mmh3.hash(key, signed=False))
    result = cache.get(key)
    if result is not None:
        return result
    st = time.time()
    # Reading PDF
    extracted_info = ''

    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    convert_api_pdf_future = get_async_future(convert_pdf_to_txt, link, os.getenv("CONVERT_API_SECRET_KEY"))
    pdf_text_future = get_async_future(pdfReader, link)
    get_arxiv_pdf_link_future = None
    result_from = "TIMEOUT_PDF_READER"
    if "arxiv.org" in link:
        get_arxiv_pdf_link_future = get_async_future(get_arxiv_pdf_link, link)
    text = ''
    while time.time() - st < (45 if detailed <= 1 else 75) and exists_tmp_marker_file(web_search_tmp_marker_name):
        if pdf_text_future.done() and pdf_text_future.exception() is None:
            text = pdf_text_future.result()
            result_from = "pdf_reader_tool"
            break
        if convert_api_pdf_future.done() and convert_api_pdf_future.exception() is None:
            text = convert_api_pdf_future.result()
            result_from = "convert_api"
            break
        if get_arxiv_pdf_link_future is not None and get_arxiv_pdf_link_future.done() and get_arxiv_pdf_link_future.exception() is None and not (convert_api_pdf_future.done() and convert_api_pdf_future.exception() is None) and not (pdf_text_future.done() and pdf_text_future.exception() is None):
            title, text = get_arxiv_pdf_link_future.result()
            result_from = "arxiv"
            break
        time.sleep(0.5)

    txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    time_logger.info(f"Time taken to read PDF {link} = {(time.time() - st):.2f}")
    txt = normalize_whitespace(txt)
    txt_len = len(txt.strip().split())
    assert txt_len > 500, f"Extracted pdf from {result_from} with len = {txt_len} is too short for link: {link}"
    cache.set(key, {"link": link, "title": title, "context": context, "detailed": detailed, "exception": False, "full_text": txt},
              expire=cache_timeout)
    return {"link": link, "title": title, "context": context, "detailed":detailed, "exception": False, "full_text": txt}


def get_downloaded_data_summary(link_title_context_apikeys, use_large_context=False):
    link, title, context, api_keys, text, query, detailed = link_title_context_apikeys
    txt = text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    st = time.time()
    input_len = len(txt.split())
    assert len(txt.strip().split()) > 200, f"Input length is too short, input len = {input_len}, for link: {link}"
    # chunked_text = ChunkText(txt, TOKEN_LIMIT_FOR_DETAILED if detailed else TOKEN_LIMIT_FOR_SHORT, 0)[0]
    logger.debug(f"Time for content extraction for link: {link} = {(time.time() - st):.2f}")
    non_chunk_time = time.time()
    extracted_info = call_contextual_reader(context, txt,
                                            api_keys, provide_short_responses=not detailed and not use_large_context,
                                            chunk_size=((TOKEN_LIMIT_FOR_DETAILED + 500) if detailed or use_large_context else (TOKEN_LIMIT_FOR_SHORT + 200)), scan=use_large_context)
    tt = time.time() - st
    tex_len = len(extracted_info.split())
    time_logger.info(f"Called contextual reader for link: {link}, Result length = {tex_len} with total time = {tt:.2f}, non chunk time = {(time.time() - non_chunk_time):.2f}, chunk time = {(non_chunk_time - st):.2f}")
    assert len(extracted_info.strip().split()) > 40, f"Extracted info is too short, input len = {input_len}, ( Output len = {tex_len} ) for link: {link}"
    return {"link": link, "title": title, "context": context, "text": extracted_info, "detailed": detailed, "exception": False, "full_text": txt, "detailed": detailed}


def get_page_text(link_title_context_apikeys, web_search_tmp_marker_name=None):
    link, title, context, api_keys, text, detailed = link_title_context_apikeys
    key = f"get_page_text-{str([link])}"
    key = str(mmh3.hash(key, signed=False))
    result = cache.get(key)
    if result is not None and "full_text" in result and len(result["full_text"].strip()) > 0:
        return result
    st = time.time()
    pgc = web_scrape_page(link, context, api_keys, web_search_tmp_marker_name=web_search_tmp_marker_name)
    if len(pgc["text"].strip()) == 0:
        logger.error(f"[process_page_link] Empty text for link: {link}")
        return {"link": link, "title": title, "exception": True, "full_text": '', "detailed": detailed, "context": context, "error": pgc["error"] if "error" in pgc else "Empty text"}
    title = pgc["title"]
    text = pgc["text"]
    cache.set(key, {"link": link, "title": title, "detailed": detailed, "exception": False, "full_text": text},
              expire=cache_timeout)
    return {"link": link, "title": title, "context": context, "exception": False, "full_text": text, "detailed": detailed}


pdf_process_executor = ThreadPoolExecutor(max_workers=64)

def queued_read_over_multiple_links(results_generator, api_keys, provide_detailed_answers=False, web_search_tmp_marker_name=None):
    def yeild_one():
        for r in results_generator:
            if isinstance(r, dict) and r["type"] == "result":
                yield [[r["link"], r["title"], r["context"], api_keys, '', provide_detailed_answers, r.get("start_time", time.time()), r["query"]]]
            else:
                continue

    def call_back(result, *args, **kwargs):
        try:
            link = args[0][0][0]
        except:
            link = ''
        full_result = None
        text = ''

        if result is not None:
            assert isinstance(result, dict)
            result.pop("exception", None)
            result.pop("detailed", None)
            full_result = deepcopy(result)
            result.pop("full_text", None)
            text = f"[{result['title']}]({result['link']})\n{result['text']}"
        return {"text": text, "full_info": full_result, "link": link}

    threads = 64 if provide_detailed_answers else 16
    # task_queue = orchestrator(process_link, list(zip(link_title_context_apikeys, [{}]*len(link_title_context_apikeys))), call_back, threads, 120)
    def fn1(*args, **kwargs):
        link_title_context_apikeys = args[0]
        link = link_title_context_apikeys[0]
        title = link_title_context_apikeys[1]
        context = link_title_context_apikeys[2]
        api_keys = link_title_context_apikeys[3]
        text = link_title_context_apikeys[4]
        detailed = link_title_context_apikeys[5]
        start_time = link_title_context_apikeys[6]
        query = link_title_context_apikeys[7]
        link_title_context_apikeys = (link, title, context, api_keys, text, detailed)
        web_search_tmp_marker_name = kwargs.get("keep_going_marker", None)
        web_res = download_link_data(link_title_context_apikeys, web_search_tmp_marker_name=web_search_tmp_marker_name)
        web_res["start_time"] = start_time
        web_res["query"] = query
        if exists_tmp_marker_file(web_search_tmp_marker_name) and not web_res.get("exception", False) and "full_text" in web_res and len(web_res["full_text"].split()) > 0:
            return [web_res, kwargs]
        else:
            error = web_res["error"] if "error" in web_res else None
            raise Exception(f"fn1 Web search stopped for link: {link} due to {error}")
    def fn2(*args, **kwargs):
        link_data = args[0]
        link = link_data["link"]
        title = link_data["title"]
        text = link_data["full_text"]
        exception = link_data["exception"]
        elapsed = link_data["start_time"] - time.time()
        error = link_data["error"] if "error" in link_data else None
        context = link_data["context"]
        query = link_data["query"]
        detailed = link_data["detailed"] if "detailed" in link_data and elapsed <= 30 else False
        web_search_tmp_marker_name = kwargs.get("keep_going_marker", None)
        if exception:
            # link_data = {"link": link, "title": title, "text": '', "detailed": detailed, "context": context, "exception": True, "full_text": ''}
            raise Exception(f"Exception raised for link: {link}, {error}")
        if exists_tmp_marker_file(web_search_tmp_marker_name):
            link_title_context_apikeys = (link, title, context, api_keys, text, query, detailed)
            summary = get_downloaded_data_summary(link_title_context_apikeys)
            return summary
        else:
            raise Exception(f"fn2 Web search stopped for link: {link}")
    # def compute_timeout(link):
    #     return {"timeout": 60 + (30 if provide_detailed_answers else 0)} if is_pdf_link(link) else {"timeout": 30 + (15 if provide_detailed_answers else 0)}
    # timeouts = list(pdf_process_executor.map(compute_timeout, links))
    def yield_timeout():
        while True:
            yield dict(keep_going_marker=web_search_tmp_marker_name)
    task_queue = dual_orchestrator(fn1, fn2, zip(yeild_one(), yield_timeout()), call_back, threads, 90, 75)
    return task_queue


def read_over_multiple_links(links, titles, contexts, api_keys, texts=None, provide_detailed_answers=False):
    if texts is None:
        texts = [''] * len(links)
    # Combine links, titles, contexts and api_keys into tuples for processing
    link_title_context_apikeys = list(zip(links, titles, contexts, [api_keys] * len(links), texts, [provide_detailed_answers] * len(links)))
    # Use the executor to apply process_pdf to each tuple
    futures = [pdf_process_executor.submit(process_link, l_t_c_a, provide_detailed_answers and len(links) <= 4) for l_t_c_a in link_title_context_apikeys]
    # Collect the results as they become available
    processed_texts = [future.result() for future in futures]
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
        raw_texts = [p.get("full_text", '') for p in full_processed_texts]
        raw_texts = [ChunkText(p.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', ''),
                              TOKEN_LIMIT_FOR_SHORT*2 - get_gpt4_word_count(p), 0)[0] if len(p) > 0 else "" for p in raw_texts]
        result = "\n\n".join([f"[{p['title']}]({p['link']})\nSummary:\n{p['text']}\nRaw article text:\n{r}\n" for r, p in
                              zip(raw_texts, processed_texts)])
    elif len(links) == 2 and provide_detailed_answers:
        raw_texts = [p.get("full_text", '') for p in full_processed_texts]
        raw_texts = [ChunkText(p.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', ''),
                               TOKEN_LIMIT_FOR_SHORT - get_gpt4_word_count(p),
                               0)[0] if len(p) > 0 else "" for p in raw_texts]
        result = "\n\n".join([f"[{p['title']}]({p['link']})\nSummary:\n{p['text']}\nRaw article text:\n{r}\n" for r, p in
                              zip(raw_texts, processed_texts)])
    else:
        result = "\n\n".join([f"[{p['title']}]({p['link']})\n{p['text']}" for p in processed_texts])
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

    query_string = (f"Previous context and conversation details between human and AI assistant: '''{current_doc_summary}'''\n" if len(current_doc_summary.strip())>0 else '')+f"Provide {'detailed, comprehensive, thoughtful, insightful, informative and in depth' if provide_detailed_answers else ''} answer for this current query: '''{query}'''"

    futures = [pdf_process_executor.submit(doc.get_short_answer, query_string, defaultdict(lambda:provide_detailed_answers, {"provide_detailed_answers": provide_detailed_answers}), True)  for doc in additional_docs]
    answers = [future.result() for future in futures]
    answers = [{"link": doc.doc_source, "title": doc.title, "text": answer} for answer, doc in zip(answers, additional_docs)]
    new_line = '\n\n'
    if len(additional_docs) == 1:
        if provide_raw_text:
            doc_search_results = [ChunkText(d.semantic_search_document(query), TOKEN_LIMIT_FOR_SHORT - get_gpt4_word_count(p['text']) if provide_detailed_answers else TOKEN_LIMIT_FOR_SHORT//2 - get_gpt3_word_count(p['text']), 0)[0] for p, d in zip(answers, additional_docs)]

            read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}\nRaw article text:\n{r}\n" for r, p in
                                 zip(doc_search_results, answers)]
        else:
            read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}" for p in
                 answers]
    elif len(additional_docs) == 2 and provide_detailed_answers:
        if False:
            doc_search_results = [ChunkText(d.semantic_search_document(query), 1400 - get_gpt4_word_count(p['text']) if provide_detailed_answers else 700 - get_gpt3_word_count(p['text']), 0)[0] for p, d in zip(answers, additional_docs)]
            read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}\nRaw article text:\n{r}\n" for r, p in zip(doc_search_results, answers)]
        else:
            read_text = [f"[{p['title']}]({p['link']})\nAnswer:\n{p['text']}" for p in answers]
    else:
        read_text = [f"[{p['title']}]({p['link']})\n{p['text']}" for p in answers]
    if dont_join_answers:
        pass
    else:
        read_text = new_line.join(read_text)
    dedup_results = [{"link": doc.doc_source, "title": doc.title} for answer, doc in zip(answers, additional_docs)]
    logger.info(f"Query = ```{query}```\nAnswers = {answers}")
    return wrap_in_future({"search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]}), wrap_in_future({"text": read_text, "search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]})





