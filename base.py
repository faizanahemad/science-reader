from datetime import datetime
import sys
import random
from functools import partial
import glob
import traceback
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
from typing import Optional, Type
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


import ai21

pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

import logging
from common import *

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)

from tenacity import (
    retry,
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


def get_embedding_model(keys):
    openai_key = keys["openAIKey"]
    assert openai_key
    openai_embed = OpenAIEmbeddings(openai_api_key=openai_key, model='text-embedding-ada-002')
    return openai_embed

@retry(wait=wait_random_exponential(min=15, max=60), stop=stop_after_attempt(3))
def call_ai21(text, temperature=0.7, api_key=None):
    response_grande = ai21.Completion.execute(
          model="j2-jumbo-instruct",
          prompt=text,
          numResults=1,
          maxTokens=4000,
          temperature=temperature,
          topKReturn=0,
          topP=1,
          stopSequences=["##"],
          api_key=api_key,
    )
    result = response_grande["completions"][0]["data"]["text"]
    return result





# search = BingSearchAPIWrapper(k=1)



easy_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
davinci_enc = tiktoken.encoding_for_model("text-davinci-003")
def call_chat_model(model, text, temperature, system, api_key):
    response = openai.ChatCompletion.create(
        model=model,
        api_key=api_key,
        messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=temperature,
            stream=True
        )
    for chunk in response:
        if "content" in chunk["choices"][0]["delta"]:
            yield chunk["choices"][0]["delta"]["content"]

    if chunk["choices"][0]["finish_reason"]!="stop":
        yield "\n Output truncated due to lack of context Length."
    

def call_non_chat_model(model, text, temperature, system, api_key):
    input_len = len(davinci_enc.encode(text))
    assert 4000 - input_len > 0
    completions = openai.Completion.create(
        api_key=api_key,
        engine=model,
        prompt=text,
        temperature=temperature,
        max_tokens = 4000 - input_len,
    )
    message = completions.choices[0].text
    finish_reason = completions.choices[0].finish_reason
    if finish_reason != 'stop':
        message = message + "\n Output truncated due to lack of context Length."
    return message


class CallLLm:
    def __init__(self, keys, use_gpt4=False, self_hosted_model_url=None):
        
        
        self.keys = keys
        self.system = "You are a helpful assistant. Please follow the instructions and respond to the user request."
        available_openai_models = self.keys["openai_models_list"]
        self.self_hosted_model_url = self_hosted_model_url
        openai_gpt4_models = [] if available_openai_models is None else [m for m in available_openai_models if "gpt-4" in m]
        use_gpt4 = use_gpt4 and self.keys.get("use_gpt4", True)
        self.use_gpt4 = use_gpt4 and len(openai_gpt4_models) > 0
        openai_turbo_models = ["gpt-3.5-turbo"] if available_openai_models is None else [m for m in available_openai_models if "gpt-3.5-turbo" in m]
        openai_basic_models = [
            "text-davinci-003", "text-davinci-003", 
            "text-davinci-002",]
        
        self.openai_basic_models = random.sample(openai_basic_models, len(openai_basic_models))
        self.openai_turbo_models = random.sample(openai_turbo_models, len(openai_turbo_models))
        self.openai_gpt4_models = random.sample(openai_gpt4_models, len(openai_gpt4_models))
        self.gpt4_enc = tiktoken.encoding_for_model("gpt-4")
        self.turbo_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.davinci_enc = tiktoken.encoding_for_model("text-davinci-003")
        
    @retry(wait=wait_random_exponential(min=30, max=90), stop=stop_after_attempt(3))
    def __call__(self, text, temperature=0.7, stream=False,):
#         logger.info(f"CallLLM with temperature = {temperature}, stream = {stream} with text len = {len(text.split())}, token len = {len(self.gpt4_enc.encode(text) if self.use_gpt4 else self.turbo_enc.encode(text))}")
        if self.use_gpt4 and self.keys["openAIKey"] is not None and len(self.openai_gpt4_models) > 0:
#             logger.info(f"Try GPT4 models with stream = {stream}, use_gpt4 = {self.use_gpt4}")
            assert len(self.gpt4_enc.encode(text)) < 8000
            models = round_robin(self.openai_gpt4_models)
            try:
                model = next(models)
                return call_with_stream(call_chat_model, stream, model, text, temperature, self.system, self.keys["openAIKey"])
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                if len(self.openai_gpt4_models) > 1:
                    model = next(models)
                else:
                    raise e
                return call_with_stream(call_chat_model, stream, model, text, temperature, self.system, self.keys["openAIKey"])
        elif self.keys["openAIKey"] is not None:
            models = round_robin(self.openai_turbo_models)
            assert len(self.turbo_enc.encode(text)) < 4000
            try:
                model = next(models)
#                 logger.info(f"Try turbo model with stream = {stream}")
                return call_with_stream(call_chat_model, stream, model, text, temperature, self.system, self.keys["openAIKey"])
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                if len(self.openai_turbo_models) > 1:
                    model = next(models)
                    fn = call_chat_model
                else:
                    models = round_robin(self.openai_basic_models)
                    model = next(model)
                    fn = call_non_chat_model
                try:  
                    return call_with_stream(fn, stream, model, text, temperature, self.system, self.keys["openAIKey"])
                except Exception as e:
                    if type(e).__name__ == 'AssertionError':
                        raise e
                    elif self.keys["ai21Key"] is not None:
                        return call_with_stream(call_ai21, stream, text, temperature, self.keys["ai21Key"])
                    else:
                        raise e
                        
        elif self.keys["ai21Key"] is not None:
#             logger.info(f"Try Ai21 model with stream = {stream}, Ai21 key = {self.keys['ai21Key']}")
            return call_with_stream(call_ai21, stream, text, temperature, self.keys["ai21Key"])
        else:
            raise ValueError(str(self.keys))
            

def chunk_text_langchain(text, chunk_size=3400):
    text_splitter = TokenTextSplitter(chunk_size=chunk_size, chunk_overlap=100)
    texts = text_splitter.split_text(text)
    for t in texts:
        yield t
        
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
    
    




@AddAttribute('name', "MathTool")
@AddAttribute('description', """
MathTool:
    This tool takes a numeric expression as a string and provides the output for it.

    Input params/args: 
        num_expr (str): numeric expression to evaluate

    Returns: 
        str: evaluated expression answer

    Usage:
        `answer=MathTool(num_expr="2*3") # Expected answer = 6, # This tool needs no initialization`

    """)
def MathTool(num_expr: str):
    math_tool = load_tools(["llm-math"], llm=llm)[0]
    return math_tool._run(num_expr).replace("Answer: ", "")


@AddAttribute('name', "WikipediaTool")
@AddAttribute('description', """
WikipediaTool:
    This tool takes a phrase or key words and searches them over wikipedia, returns results from wikipedia as a str.

    Input params/args: 
        search_phrase (str): phrase to search over on wikipedia

    Returns: 
        str: searched paragraph on basis of search_phrase from wikipedia

    Usage:
        `answer=WikipediaTool(search_phrase="phrase to search") # This tool needs no initialization`

    """)
def WikipediaTool(search_phrase: str):
    tool = load_tools(["wikipedia"], llm=llm)[0]
    return tool._run(search_phrase)

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
    text_splitter = TokenTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
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
Summarize the document below into a {"detailed and informational " if is_detailed else ""}shorter version (by eliminating repeatation, by paraphrasing etc.) while preserving the main points and context, do not miss any important details, do not remove mathematical details.
Document:
{{document}}

{"Detailed and informational " if is_detailed else ""}Summary:

"""
        self.prompt = PromptTemplate(
            input_variables=["document"],
            template=template,
        )
    @timer
    def __call__(self, text_document):
        prompt = self.prompt.format(document=text_document)
        return CallLLm(self.keys, use_gpt4=False)(prompt, temperature=0.7)
    
class ReduceRepeatTool:
    def __init__(self, keys):
        self.keys = keys
        self.name = "ReduceRepeatTool"
        self.description = """       
ReduceRepeatTool:
    This tool takes a text document reduces repeated content in the document. Useful when document has a lot of repeated content or ideas which can be mentioned in a shorter version.

    Input params/args: 
        text_document (str): document to summarize.

    Returns: 
        str: non_repeat_document.

    Usage:
        `non_repeat_document = ReduceRepeatTool()(text_document="document to to reduce repeats") # Note: this tool needs to be initialized first.`
        
    """
        self.prompt = PromptTemplate(
            input_variables=["document"],
            template=""" 
Reduce repeated content in the document given. Some ideas or phrases or points are repeated with no variation, remove them, output non-repeated parts verbatim without any modification, do not miss any important details.
Document is given below:

{document}
""",
        )
    def __call__(self, text_document):
        prompt = self.prompt.format(document=text_document)
        result = CallLLm(self.keys, use_gpt4=False)(prompt, temperature=0.4)
        logger.info(f"ReduceRepeatTool with input as \n {text_document} and output as \n {result}")
        return result

process_text_executor = ThreadPoolExecutor(max_workers=32)
def contrain_text_length_by_summary(text, keys, threshold=2000):
    summariser = Summarizer(keys)
    tlc = partial(TextLengthCheck, threshold=threshold)
    return text if tlc(text) else summariser(text)

def process_text(text, chunk_size, my_function, keys):
    # Split the text into chunks
    chunks = list(chunk_text_langchain(text, chunk_size))
    if len(chunks) > 1:
        futures = [process_text_executor.submit(my_function, chunk) for chunk in chunks]
        # Get the results from the futures
        results = [future.result() for future in futures]
    else:
        results = [my_function(chunk) for chunk in chunks]

    threshold = 2000
    tlc = partial(TextLengthCheck, threshold=threshold)
    
    while len(results) > 1:
        logger.warning(f"--- process_text --- Multiple chunks as result. Results len = {len(results)} and type of results =  {type(results[0])}")
        assert isinstance(results[0], str)
        results = [process_text_executor.submit(contrain_text_length_by_summary, r, keys, threshold) for r in results]
        results = [future.result() for future in results]
        results = combine_array_two_at_a_time(results)
    assert len(results) == 1
    results = results[0]
    if not tlc(results):
        summariser = Summarizer(keys, is_detailed=True)
        logger.warning("--- process_text --- Calling Summarizer on single result")
        results = summariser(results)
    
    if not tlc(results):
        logger.warning("--- process_text --- Calling ReduceRepeatTool")
        results = ReduceRepeatTool(keys)(results)
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


class Cleaner:
    def __init__(self, keys, prompt=None, context=None):
        self.keys=keys
        self.instruction = """
You will be given unclean text fragments from web scraping a url.
Your goal is to return cleaned text without html tags and other irrelevant content (including code exception stack traces). 
If you are given a user request, instruction or query, then use that as well in filtering the information and return information relevant to the user query or instruction.
just extract relevant information if user query is given (Try to answer mostly in bullet points in this case.) else return cleaned text..
No creativity needed here.
Some context about the source document and user query is provided next, use the user query if provided and give very concise succint response.
        """ if prompt is None else prompt
        self.clean_now_follows = "\nActual text to be cleaned follows: \n"
        self.prompt = (self.instruction + " " + (context if context is not None else "") + " " + self.clean_now_follows) if prompt is None else prompt
        
    def clean_one(self, string, model=None):
        return CallLLm(self.keys, use_gpt4=False)(self.prompt + string, temperature=0.2)

    
    def clean_one_with_exception(self, string):
        try:
            cleaned_text = self.clean_one(string)
            return cleaned_text
        except Exception as e:
            exp_str = str(e)
            too_long = "maximum context length" in exp_str and "your messages resulted in" in exp_str
            if too_long:
                return " ".join([self.clean_one_with_exception(st) for st in split_text(string)])
            raise e
                
    def __call__(self, string, chunk_size=3400):
        return process_text(string, chunk_size, self.clean_one_with_exception, self.keys)

class GetWebPage:
    
    def __init__(self, keys):
        self.keys = keys
        self.name = "GetWebPage"
        self.description = """
GetWebPage:
    This tool takes a url link to a webpage and returns cleaned text content of that Page. Useful if you want to visit a page and get it's content. Optionally it can also take a user context or instruction and give only relevant parts of the page for the provided context.

    Input params/args: 
        url (str): url of page to visit
        context (str): user query/instructions/context about what to look for in this webpage

    Returns: 
        str: page_content

    Usage:
        `page_content = GetWebPage()(url="url to visit", context="user query or page reading instructions") # Note: this tool needs to be initialized first.`

    """
    def __call__(self, url, context=None):
        page_items = run_async(get_url_content, url)

        if not isinstance(page_items, dict):
            print(f"url: {url}, title: None, content: None")
            return f"url: {url}, title: None, content: None"
        page_content = page_items["page_content"]
        if not isinstance(page_content, str):
            print(f"url: {url}, title: {page_items['title']}, content: None")
            return f"url: {url}, title: {page_items['title']}, content: None"
        page_content = Cleaner(self.keys, context=f"\n\n url: {url}, title: {page_items['title']}" + (f"user query or context: {context}" if context is not None else ""))(page_content,
        chunk_size=768)
        return f"url: {url}, title: {page_items['title']}, content: {page_content}"
    def _run(self, url: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Use the tool."""
        return self.__call__(url)
    async def _arun(self, query: str, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        """Use the tool asynchronously."""
        raise NotImplementedError("custom_search does not support async")


class ContextualReader:
    def __init__(self, keys, provide_short_responses=False):
        self.keys = keys
        self.name = "ContextualReader"
        self.provide_short_responses = provide_short_responses
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
        
        self.prompt = PromptTemplate(
            input_variables=["context", "document"],
            template=("Provide short, concise and informative response in 5-6 sentences ( after 'Extracted Information') for the given question and using the given document. " if provide_short_responses else "Provide elaborate and in-depth information relevant to the provided context after 'Extracted Information'. ") + """
Provide relevant information from the given document for the given question:
"{context}"

Document from which you need to extract information:
'''
{document}
'''

If highly relevant content is not found for the given question then output details from the document which might be helpful relative to the given question. If you find nothing useful at all then say 'No relevant information found.'.
You can use markdown formatting to typeset/format your answer better.
You can output any relevant equations in latex/markdown format as well. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math in less width.

Relevant Information:

""",
        )
        
    def get_one(self, context, document):
        import inspect
        prompt = self.prompt.format(context=context, document=document)
        callLLm = CallLLm(self.keys, use_gpt4=False)
        result = callLLm(prompt, temperature=0.4, stream=False)
        assert isinstance(result,str)
        return result
        
        
    
    def get_one_with_exception(self, context, document):
        try:
            text = self.get_one(context, document)
            return text
        except Exception as e:
            exp_str = str(e)
            too_long = "maximum context length" in exp_str and "your messages resulted in" in exp_str
            if too_long:
                logger.warning(f"ContextualReader:: Too long context, raised exception {str(e)}")
                return " ".join([self.get_one_with_exception(context, st) for st in split_text(document)])
            raise e
            

    def __call__(self, context_user_query, text_document, chunk_size=3000):
        assert isinstance(text_document, str)
        import functools
        part_fn = functools.partial(self.get_one_with_exception, context_user_query)
        result = process_text(text_document, chunk_size, part_fn, self.keys)
        assert isinstance(result, str)
        return result

# TODO: Add caching
@typed_memoize(cache, str, int, tuple, bool)
def call_contextual_reader(query, document, keys, provide_short_responses=False, chunk_size=3000)->str:
    from base import ContextualReader
    assert isinstance(document, str)
    cr = ContextualReader(keys, provide_short_responses=provide_short_responses)
    return cr(query, document, chunk_size=chunk_size)





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

# TODO: Add caching
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
    site_string = " (site:arxiv.org OR site:openreview.net) " if only_science_sites and not only_pdf else " "
    query = f"{query}{site_string}{after_string}{search_pdf}"
    results = search.results(query, num)
    seen_titles = set()
    seen_links = set()
    dedup_results = []
    for r in results:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        if only_science_sites and "arxiv.org" not in link and "openreview.net" not in link:
            continue
        if not only_science_sites and ("arxiv.org" in link or "openreview.net" in link):
            continue
        if not only_pdf and "pdf" in link:
            continue
        r["citations"] = None
        r["year"] = None
        r['query'] = pre_query
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    logger.info(f"Called BING API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results

# TODO: Add caching
@typed_memoize(cache, str, int, tuple, bool)
def googleapi(query, key, num, our_datetime=None, only_pdf=True, only_science_sites=True):
    from langchain.utilities import GoogleSearchAPIWrapper
    from datetime import datetime, timedelta
    num=min(num, 20)
    
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
    site_string = " (site:arxiv.org OR site:openreview.net) " if only_science_sites else " -site:arxiv.org AND -site:openreview.net "
    query = f"{query}{site_string}{after_string}{search_pdf}"
    
    results = search.results(query, min(num, 10), search_params={"filter":"1", "start": "1"})
    if num > 10:
        results.extend(search.results(query, min(num, 10), search_params={"filter":"1", "start": "11"}))
    seen_titles = set()
    seen_links = set()
    dedup_results = []
    for r in results:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        if only_science_sites and "arxiv.org" not in link and "openreview.net" not in link:
            continue
        if not only_science_sites and ("arxiv.org" in link or "openreview.net" in link):
            continue
        if not only_pdf and "pdf" in link:
            continue
        r["citations"] = None
        r["year"] = None
        r['query'] = pre_query
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    logger.info(f"Called GOOGLE API with args = {query}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results

# TODO: Add caching
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
    site_string = " (site:arxiv.org OR site:openreview.net) " if only_science_sites else " -site:arxiv.org AND -site:openreview.net "
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
    keys = ['title', 'link', 'snippet', 'rich_snippet', 'source']
    results = [{k: r[k] for k in keys if k in r} for r in results]
    seen_titles = set()
    seen_links = set()
    dedup_results = []
    for r in results:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        if only_science_sites and "arxiv.org" not in link and "openreview.net" not in link:
            continue
        if not only_science_sites and ("arxiv.org" in link or "openreview.net" in link):
            continue
        if not only_pdf and "pdf" in link:
            continue
        r["citations"] = get_citation_count(r)
        r["year"] = get_year(r)
        _ = r.pop("rich_snippet", None)
        r['query'] = pre_query
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    logger.info(f"Called SERP API with args = {query}, {key}, {num}, {our_datetime}, {only_pdf}, {only_science_sites} and responses len = {len(dedup_results)}")
    
    return dedup_results
    
# TODO: Add caching
@typed_memoize(cache, str, int, tuple, bool)
def get_page_content(link, playwright_cdp_link=None):
    
    text = ''
    title = ''
    try:
        from playwright.sync_api import sync_playwright
        playwright_enabled = True
        with sync_playwright() as p:
            if playwright_cdp_link is not None and isinstance(playwright_cdp_link, str):
                browser = p.chromium.connect_over_cdp(playwright_cdp_link)
            else:
                browser = p.chromium.launch(args=['--disable-web-security', "--disable-site-isolation-trials"])
            page = browser.new_page()
            url = link
            page.goto(url)
            page.wait_for_selector('body', timeout=10000)
            while page.evaluate('document.readyState') != 'complete':
                pass
            
            try:
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
                result = page.evaluate("""(function execute(){var article = new Readability(document).parse();return article})()""")
            except Exception as e:
                logger.info(f"Trying playwright for link {link} after playwright failed with exception = {str(e)}")
                # traceback.print_exc()
                # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
                init_html = page.evaluate("""(function e(){return document.body.innerHTML})()""")
                init_title = page.evaluate("""(function e(){return document.title})()""")
                page.goto("https://www.example.com/")
                while page.evaluate('document.readyState') != 'complete':
                    pass
                page.evaluate(f"""text=>document.body.innerHTML=text""", init_html)
                page.evaluate(f"""text=>document.title=text""", init_title)
                logger.info(f"Loaded html and title into page with example.com as url")
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
                page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
                page.wait_for_selector('body', timeout=10000)
                while page.evaluate('document.readyState') != 'complete':
                    pass
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
            logger.info(f"Trying selenium for link {link} after playwright failed with exception = {str(e)})")
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
            try:
                driver.execute_script('''
                    function myFunction() {
                        if (document.readyState === 'complete') {
                            var script = document.createElement('script');
                            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
                            document.head.appendChild(script);

                            var script = document.createElement('script');
                            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js';
                            document.head.appendChild(script);
                        } else {
                            setTimeout(myFunction, 1000);
                        }
                    }

                    myFunction();
                ''')
                while driver.execute_script('return document.readyState;') != 'complete':
                    pass
                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined';""")
                WebDriverWait(driver, timeout=10).until(document_initialised)
                result = driver.execute_script("""var article = new Readability(document).parse();return article""")
            except Exception as e:
                traceback.print_exc()
                # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
                init_title = driver.execute_script("""return document.title;""")
                init_html = driver.execute_script("""return document.body.innerHTML;""")
                driver.get("https://www.example.com/")
                logger.info(f"Loaded html and title into page with example.com as url")
                while driver.execute_script('return document.readyState;') != 'complete':
                    pass
                driver.execute_script("""document.body.innerHTML=arguments[0]""", init_html)
                driver.execute_script("""document.title=arguments[0]""", init_title)
                driver.execute_script('''
                    function myFunction() {
                        if (document.readyState === 'complete') {
                            var script = document.createElement('script');
                            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
                            document.head.appendChild(script);

                            var script = document.createElement('script');
                            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js';
                            document.head.appendChild(script);
                        } else {
                            setTimeout(myFunction, 1000);
                        }
                    }

                    myFunction();
                ''')
                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined';""")
                WebDriverWait(driver, timeout=10).until(document_initialised)
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            options = dict(url=self.file_path,**self.options)
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


def get_paper_details_from_semantic_scholar(arxiv_url):
    print(f"get_paper_details_from_semantic_scholar with {arxiv_url}")
    arxiv_id = arxiv_url.split("/")[-1].replace(".pdf", '').strip()
    from semanticscholar import SemanticScholar
    sch = SemanticScholar()
    paper = sch.get_paper(f"ARXIV:{arxiv_id}")
    return paper



# TODO: Add caching
def web_search_part1(context, doc_source, doc_context, api_keys, year_month=None, previous_answer=None, previous_search_results=None, extra_queries=None):

    if extra_queries is None:
        extra_queries = []
    num_res = 10
    n_query = "two" if previous_search_results or len(extra_queries) > 0 else "four"

    pqs = []
    if previous_search_results:
        for r in previous_search_results:
            pqs.append(r["query"])
    prompt = f"""You are given a query/question as below:
'{context}' 
We want to answer it in context of the research document below: 
'''{doc_context}''' 

We want to generate web search queries to search the web for more information about the query/question.
{f"We also have the answer we have given till now for this question as '''{previous_answer}''', write new web search queries that can help expand this answer." if previous_answer and len(previous_answer.strip())>10 else ''}
{f"We had previously generated the following web search queries in our previous search: '''{pqs}''', don't generate these queries or similar queries - '''{pqs}'''" if len(pqs)>0 else ''}

Generate {n_query} well specified and diverse web search queries as a valid python list. 
Instructions for how to generate the queries are given below.
Generated web search queries can break down the actual question into smaller parts. 
Each generated query must be different from others and diverse from each other. 
Dearch query strings must be diverse and cover various topics about the original query ('{context}').
Output should be only a python list of strings (a valid python syntax code which is a list of strings) with {n_query} queries.
When generating a search query prepend the name of the study area to the query (like one final output query is "<area of research> <query>", example: "machine learning self attention vs cross attention" where 'machine learning' is domain and 'self attention vs cross attention' is the web search query without domain.). 
Determine the subject domain from the research document and the query and make sure to mention the domain in your queries.
Convert abbreviations to full forms and correct typos in the query using the research document as context.

Your output will look like:

["query_1", "different_web_query_2", "diverse_web_query_3", "part_of_query_web_query_4"]
    
Output only a valid python list of web search query strings: 
"""
    if len(extra_queries) < 1:
        query_strings = CallLLm(api_keys, use_gpt4=False)(prompt)
        logger.info(f"Query string for {context} = {query_strings}") # prompt = \n```\n{prompt}\n```\n
        query_strings = parse_array_string(query_strings.strip())
        query_strings = query_strings + extra_queries
    else:
        query_strings = extra_queries
    
    rerank_available = "cohereKey" in api_keys and api_keys["cohereKey"] is not None and len(api_keys["cohereKey"].strip()) > 0
    serp_available = "serpApiKey" in api_keys and api_keys["serpApiKey"] is not None and len(api_keys["serpApiKey"].strip()) > 0
    bing_available = "bingKey" in api_keys and api_keys["bingKey"] is not None and len(api_keys["bingKey"].strip()) > 0
    google_available = ("googleSearchApiKey" in api_keys and api_keys["googleSearchApiKey"] is not None and len(api_keys["googleSearchApiKey"].strip()) > 0) and ("googleSearchCxId" in api_keys and api_keys["googleSearchCxId"] is not None and len(api_keys["googleSearchCxId"].strip()) > 0)
    if rerank_available:
        import cohere
        co = cohere.Client(api_keys["cohereKey"])
        num_res = 10
        rerank_query = "\n".join(query_strings)
    if len(extra_queries) > 0:
        num_res = 5
    
    if year_month:
        year_month = datetime.strptime(year_month, "%Y-%m").strftime("%Y-%m-%d")
    
    if google_available:
        num_res = 10
        serps = [get_async_future(googleapi, query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), num_res, our_datetime=None) for query in query_strings]
        serps_web = [get_async_future(googleapi, query, dict(cx=api_keys["googleSearchCxId"], api_key=api_keys["googleSearchApiKey"]), num_res, our_datetime=year_month, only_pdf=False, only_science_sites=False) for query in query_strings]
        logger.debug(f"Using GOOGLE for web search, serps len = {len(serps)}, serps web len = {len(serps_web)}")
    elif serp_available:
        serps = [get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month) for query in query_strings]
        serps_web = [get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month, only_pdf=False, only_science_sites=False) for query in query_strings]
        logger.debug(f"Using SERP for web search, serps len = {len(serps)}, serps web len = {len(serps_web)}")
    elif bing_available:
        serps = [get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None) for query in query_strings]
        serps_web = [get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=year_month, only_pdf=False, only_science_sites=False) for query in query_strings]
        logger.debug(f"Using BING for web search, serps len = {len(serps)}, serps web len = {len(serps_web)}")
    else:
        logger.warning(f"Neither GOOGLE, Bing nor SERP keys are given but Search option choosen.")
        return {"text":'', "search_results": [], "queries": query_strings}
    try:
        serps = [s.result() for s in serps]
        serps_web = [s.result() for s in serps_web]
    except Exception as e:
        logger.error(f"Error in getting results from web search engines, error = {e}")
        
        if serp_available:
            serps = [get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month) for query in query_strings]
            serps_web = [get_async_future(serpapi, query, api_keys["serpApiKey"], num_res, our_datetime=year_month, only_pdf=False, only_science_sites=False) for query in query_strings]
            logger.debug(f"Using SERP for web search, serps len = {len(serps)}, serps web len = {len(serps_web)}")
        elif bing_available:
            serps = [get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=None) for query in query_strings]
            serps_web = [get_async_future(bingapi, query, api_keys["bingKey"], num_res, our_datetime=year_month, only_pdf=False, only_science_sites=False) for query in query_strings]
            logger.debug(f"Using BING for web search, serps len = {len(serps)}, serps web len = {len(serps_web)}")
        else:
            return {"text":'', "search_results": [], "queries": query_strings}
        serps = [s.result() for s in serps]
        serps_web = [s.result() for s in serps_web]
    
    qres = [r for serp in serps for r in serp if r["link"] not in doc_source and doc_source not in r["link"] and "pdf" in r["link"]]
    qres_web = [r for serp in serps_web for r in serp if r["link"] not in doc_source and doc_source not in r["link"] and "pdf" not in r["link"]]
    logger.info(f"Using Engine for web search, serps len = {len([r for s in serps for r in s])}, serps web len = {len([r for s in serps_web for r in s])}, Qres len = {len(qres)} and Qres web len = {len(qres_web)}")
    dedup_results = []
    seen_titles = set()
    seen_links = set()
    link_counter = Counter()
    title_counter = Counter()
    if previous_search_results:
        for r in previous_search_results:
            seen_links.add(r['link'])
    len_before_dedup = len(qres)
    for r in qres:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        link_counter.update([link])
        title_counter.update([link])
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
        
    dedup_results_web = []
    for r in qres_web:
        title = r.get("title", "").lower()
        link = r.get("link", "")
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        dedup_results_web.append(r)
        seen_titles.add(title)
        seen_links.add(link)

    len_after_dedup = len(dedup_results)
    logger.info(f"Web search:: Before Dedup = {len_before_dedup}, After = {len_after_dedup}")
#     logger.info(f"Before Dedup = {len_before_dedup}, After = {len_after_dedup}, Link Counter = \n{link_counter}, title counter = \n{title_counter}")
        
    # Rerank here first

    # if rerank_available:
    #     st_rerank = time.time()
    #     docs = [r["title"] + " " + r.get("snippet", '') for r in dedup_results]
    #     rerank_results = co.rerank(query=rerank_query, documents=docs, top_n=8, model='rerank-english-v2.0')
    #     pre_rerank = dedup_results
    #     dedup_results = [dedup_results[r.index] for r in rerank_results]
    #     tt_rerank = time.time() - st_rerank
    #     logger.info(f"--- Cohere Reranked in {tt_rerank:.2f} --- rerank len = {len(dedup_results)}")
        # logger.info(f"--- Cohere Reranked in {tt_rerank:.2f} ---\nBefore Dedup len = {len_before_dedup}, rerank len = {len(dedup_results)},\nBefore Rerank = ```\n{pre_rerank}\n```, After Rerank = ```\n{dedup_results}\n```")
        
    # if rerank_available:
    #     pdfs = [pdf_process_executor.submit(get_pdf_text, doc["link"]) for doc in dedup_results]
    #     pdfs = [p.result() for p in pdfs]
    #     docs = [r["snippet"] + " " + p["small_text"] for p, r in zip(pdfs, dedup_results)]
    #     rerank_results = co.rerank(query=rerank_query, documents=docs, top_n=8, model='rerank-english-v2.0')
    #     dedup_results = [dedup_results[r.index] for r in rerank_results]
    #     pdfs = [pdfs[r.index] for r in rerank_results]
    #     logger.info(f"--- Cohere PDF Reranked --- rerank len = {len(dedup_results)}")
    #     logger.info(f"--- Cohere PDF Reranked ---\nBefore Dedup len = {len_before_dedup} \n rerank len = {len(dedup_results)}, After Rerank = ```\n{dedup_results}\n```")
    texts = None
    # if rerank_available:
    #     texts = [p["text"] for p in pdfs]
        
    # if rerank_available:
    #     for r in dedup_results_web:
    #         if "snippet" not in r:
    #             logger.warning(r)
    #     docs = [r["title"] + " " + r.get("snippet", '') for r in dedup_results_web]
    #     rerank_results = co.rerank(query=rerank_query, documents=docs, top_n=4, model='rerank-english-v2.0')
    #     pre_rerank = dedup_results_web
    #     dedup_results_web = [dedup_results_web[r.index] for r in rerank_results]

    dedup_results = list(round_robin_by_group(dedup_results, "query"))[:(4 if len(extra_queries) > 0 else 8)]
    dedup_results_web = dedup_results_web[:4]
    web_links = [r["link"] for r in dedup_results_web]
    web_titles = [r["title"] for r in dedup_results_web]
    web_contexts = [context +"? \n" + r["query"] for r in dedup_results_web]
    for r in dedup_results:
        cite_text = f"""{(f" Cited by {r['citations']}" ) if r['citations'] else ""}"""
        r["title"] = r["title"] + f" ({r['year'] if r['year'] else ''})" + f"{cite_text}"
    
    dedup_results = dedup_results[:8]
    links = [r["link"] for r in dedup_results]
    titles = [r["title"] for r in dedup_results]
    contexts = [r["query"] for r in dedup_results]
    all_results_doc = dedup_results + dedup_results_web
    web_future = get_async_future(read_over_multiple_webpages, web_links, web_titles, web_contexts, api_keys)
    pdf_future = get_async_future(read_over_multiple_pdf, links, titles, contexts, api_keys, texts)
    return all_results_doc, links, titles, contexts, web_links, web_titles, web_contexts, texts, query_strings, rerank_query, rerank_available

def web_search(context, doc_source, doc_context, api_keys, year_month=None, previous_answer=None, previous_search_results=None, extra_queries=None):
    part1_res = get_async_future(web_search_part1, context, doc_source, doc_context, api_keys, year_month, previous_answer, previous_search_results, extra_queries)
    # all_results_doc, links, titles, contexts, web_links, web_titles, web_contexts, texts, query_strings, rerank_query, rerank_available = part1_res.result()
    part2_res = get_async_future(web_search_part2, part1_res, api_keys)
    return [get_async_future(get_part_1_results, part1_res), part2_res]

def get_part_1_results(part1_res):
    return {"search_results": part1_res.result()[0], "queries": part1_res.result()[8]}


def web_search_part2(part1_res, api_keys):
    all_results_doc, links, titles, contexts, web_links, web_titles, web_contexts, texts, query_strings, rerank_query, rerank_available = part1_res.result()
    web_future = get_async_future(read_over_multiple_webpages, web_links, web_titles, web_contexts, api_keys)
    pdf_future = get_async_future(read_over_multiple_pdf, links, titles, contexts, api_keys, texts)
    read_text_web, per_pdf_texts_web = web_future.result()
    read_text, per_pdf_texts = pdf_future.result()

    all_text = read_text + "\n\n" + read_text_web
    if rerank_available:
        import cohere
        co = cohere.Client(api_keys["cohereKey"])
        crawl_text = (per_pdf_texts + per_pdf_texts_web)
        docs = [r["text"] for r in crawl_text]
        rerank_results = co.rerank(query=rerank_query, documents=docs, top_n=max(1, len(docs) // 2),
                                   model='rerank-english-v2.0')
        crawl_text = [crawl_text[r.index] for r in rerank_results]
        pre_rerank = all_results_doc
        all_results_doc = [all_results_doc[r.index] for r in rerank_results]
        all_text = "\n\n".join([json.dumps(p, indent=2) for p in crawl_text])
        logger.info(
            f"--- Cohere Second Reranked (All) ---\nBefore Rerank = {len(pre_rerank)}, ```\n{pre_rerank}\n```, After Rerank = {len(all_results_doc)}, ```\n{all_results_doc}\n```")

    logger.debug(f"Queries = ```\n{query_strings}\n``` \n SERP All Text results = ```\n{all_text}\n```")
    return {"text": all_text, "search_results": all_results_doc, "queries": query_strings}



import multiprocessing
from multiprocessing import Pool

from concurrent.futures import ThreadPoolExecutor

# TODO: Add caching
@typed_memoize(cache, str, int, tuple, bool)
def get_pdf_text(link):
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    try:
        txt = pdfReader(link)
        chunked_text = ChunkText(txt, 1536, 0)[0]
        small_text = ChunkText(txt, 512, 0)[0]
    except Exception as e:
        return {"text": "No relevant text found in this document.", "small_text": "No relevant text found in this document."}
    return {"text": chunked_text, "small_text": small_text}

def process_pdf(link_title_context_apikeys):
    link, title, context, api_keys, text = link_title_context_apikeys
    st = time.time()
    # Reading PDF
    extracted_info = ''
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    try:
        if len(text.strip()) == 0:
            txt = pdfReader(link)

            # Chunking text
            chunked_text = ChunkText(txt, 1536, 0)[0]
        else:
            chunked_text = text

        # Extracting info
        extracted_info = call_contextual_reader(context, chunked_text, api_keys, provide_short_responses=True)
        tt = time.time() - st
        logger.info(f"Called contextual reader for link: {link} with total time = {tt:.2f}")
    except Exception as e:
        logger.error(f"Exception `{str(e)}` raised on `process_pdf` with link: {link}")
        return {"link": link, "title": title, "text": extracted_info, "exception": True}
    return {"link": link, "title": title, "text": extracted_info, "exception": False}


def process_page_link(link_title_context_apikeys):
    link, title, context, api_keys, text = link_title_context_apikeys
    st = time.time()
    pgc = get_page_content(link, api_keys["scrapingBrowserUrl"] if "scrapingBrowserUrl" in api_keys and api_keys["scrapingBrowserUrl"] is not None and len(api_keys["scrapingBrowserUrl"].strip()) > 0 else None)
    title = pgc["title"]
    text = pgc["text"]
    extracted_info = ''
    if len(text.strip()) > 0:
        chunked_text = ChunkText(text, 1536, 0)[0]
        extracted_info = call_contextual_reader(context, chunked_text, api_keys, provide_short_responses=True)
    else:
        return {"link": link, "title": title, "text": extracted_info, "exception": True}
    tt = time.time() - st
    logger.info(f"Web page read and contextual reader for link: {link} with total time = {tt:.2f}")
    return {"link": link, "title": normalize_whitespace(title), "text": extracted_info, "exception": False}


pdf_process_executor = ThreadPoolExecutor(max_workers=32)
def read_over_multiple_pdf(links, titles, contexts, api_keys, texts=None):
    if texts is None:
        texts = [''] * len(links)
    # Combine links, titles, contexts and api_keys into tuples for processing
    link_title_context_apikeys = list(zip(links, titles, contexts, [api_keys]*len(links), texts))
    # Use the executor to apply process_pdf to each tuple
    futures = [pdf_process_executor.submit(process_pdf, l_t_c_a) for l_t_c_a in link_title_context_apikeys]
    # Collect the results as they become available
    processed_texts = [future.result() for future in futures]
    processed_texts = [p for p in processed_texts if not p["exception"]]
    assert len(processed_texts) > 0
    for p in processed_texts:
        del p["exception"]
    # Concatenate all the texts
    
    # Cohere rerank here
    result = "\n\n".join([json.dumps(p, indent=2) for p in processed_texts])
    import tiktoken
    enc = tiktoken.encoding_for_model("gpt-4")
    logger.info(f"read_over_multiple_pdf:: Web search Result string len = {len(result.split())}, token len = {len(enc.encode(result))}")
    return result, processed_texts

def read_over_multiple_webpages(links, titles, contexts, api_keys, texts=None):
    if texts is None:
        texts = [''] * len(links)
    link_title_context_apikeys = list(zip(links, titles, contexts, [api_keys]*len(links), texts))
    futures = [pdf_process_executor.submit(process_page_link, l_t_c_a) for l_t_c_a in link_title_context_apikeys]
    processed_texts = [future.result() for future in futures]
    processed_texts = [p for p in processed_texts if not p["exception"]]
    assert len(processed_texts) > 0
    for p in processed_texts:
        del p["exception"]
    result = "\n\n".join([json.dumps(p, indent=2) for p in processed_texts])
    return result, processed_texts


def get_multiple_answers(query, additional_docs:list, current_doc_summary:str):
    prompt = f"""Given question: '{query}'. A summary of prior conversation or documents that maybe related to this query is given below.\n
'''{current_doc_summary}'''. 
Collect evidence and relevant information from the document we are reading now to answer the given question.
If it is possible to answer the question with the information in the document, please answer the question by carefully reading and analysing the information in the document.
Answer or information for the given question:
"""
    
    futures = [pdf_process_executor.submit(doc.get_short_answer, prompt, defaultdict(lambda:False), False)  for doc in additional_docs]
    answers = [future.result() for future in futures]
    answers = [{"link": doc.doc_source, "title": doc.title, "text": answer} for answer, doc in zip(answers, additional_docs)]
    dedup_results = [{"link": doc.doc_source, "title": doc.title} for answer, doc in zip(answers, additional_docs)]
    read_text = "\n\n".join([json.dumps(p, indent=2) for p in answers])
    return wrap_in_future({"search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]}), wrap_in_future({"text": read_text, "search_results": dedup_results, "queries": [f"[{r['title']}]({r['link']})" for r in dedup_results]})


