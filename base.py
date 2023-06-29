import sys
import random
from functools import partial
import glob
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import re
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
    logger.info(f"Getting embedding model with user provided keys")
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
    def __init__(self, keys):
        self.keys = keys
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
        self.prompt = PromptTemplate(
            input_variables=["document"],
            template=""" 
Summarize the document below into a shorter version (by eliminating repeatation, by paraphrasing etc.) while preserving the main points and context, do not miss any important details, do not remove mathematical details.
Document is given below:
{document}
""",
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


def process_text(text, chunk_size, my_function, keys):
    # Split the text into chunks
    chunks = list(chunk_text_langchain(text, chunk_size))
    if len(chunks) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # Use the executor to apply my_function to each chunk
            futures = [executor.submit(my_function, chunk) for chunk in chunks]
            # Get the results from the futures
            results = [future.result() for future in futures]
    else:
        results = [my_function(chunk) for chunk in chunks]

    
    tlc = partial(TextLengthCheck, threshold=1800)
    summariser = Summarizer(keys)
    while len(results) > 1:
        logger.info(f"Results len = {len(results)} and type of results =  {type(results[0])}")
        assert isinstance(results[0], str)
        results = [r if tlc(r) else summariser(r) for r in results]
        results = combine_array_two_at_a_time(results)
    results = [r if tlc(r) else summariser(r) for r in results]
    results = ' '.join(results)
    if not tlc(results):
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
            template=("Provide short and concise response ('Extracted Information') for the given question and using the given document. " if provide_short_responses else "") + """
Gather information and context from the given document for the below question:
"{context}"

Document:

"{document}"

Read the above document and extract useful information in a concise manner for the query/question. If nothing relevant is found then don't output anything.
You can use markdown formatting to typeset/format your answer better.
You can output any relevant equations in latex/markdown format as well. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math in less width.

Extracted Information:

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
            cleaned_text = self.get_one(context, document)
            
            return cleaned_text
        except Exception as e:
            exp_str = str(e)
            too_long = "maximum context length" in exp_str and "your messages resulted in" in exp_str
            if too_long:
                return " ".join([self.get_one_with_exception(context, st) for st in split_text(document)])
            raise e
            

    def __call__(self, context_user_query, text_document, chunk_size=3000):
        
        assert isinstance(text_document, str)
        import functools
        part_fn = functools.partial(self.get_one_with_exception, context_user_query)
        result = process_text(text_document, chunk_size, part_fn, self.keys)
        assert isinstance(result, str)
        return result
    
def call_contextual_reader(query, document, keys, provide_short_responses=False)->str:
    from base import ContextualReader
    assert isinstance(document, str)
    cr = ContextualReader(keys, provide_short_responses=provide_short_responses)
    return cr(query, document)





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
    return 0

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


def serpapi(query, key, num=20, our_datetime=None):
    from datetime import datetime, timedelta
    import requests
    # get the current date and time
    if our_datetime:
        now = datetime.strptime(our_datetime, "%Y-%m-%d")
    else:
        now = datetime.now()

    # subtract two years from the current date and time
    two_years_ago = now - timedelta(days=365*3)

    # format the date as YYYY-MM-DD
    date_string = two_years_ago.strftime("%Y-%m-%d")
    
    url = "https://serpapi.com/search"
    query = f"{query} (site:arxiv.org OR site:openreview.net) after:{date_string} filetype:pdf"
    params = {
       "q": query,
       "api_key": "cbf408275ae4040bf055042b0798efe4da4c8f1dd2034d69907239848991842b",
       "num": num,
       }
    response = requests.get(url, params=params)
    results = response.json()["organic_results"]
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
        r["citations"] = get_citation_count(r)
        r["year"] = get_year(r)
        _ = r.pop("rich_snippet", None)
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    
    return dedup_results
    
    
    
    

