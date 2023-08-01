from langchain.memory import ConversationSummaryMemory, ChatMessageHistory
import shutil
import sys
import random
from functools import partial
import glob
from filelock import FileLock, Timeout
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from collections import defaultdict
import re
from semanticscholar import SemanticScholar
from semanticscholar.SemanticScholar import Paper
from langchain.utilities import BingSearchAPIWrapper
from collections import Counter
import mmh3
from pprint import pprint
import time
import concurrent.futures
import pandas as pd
import tiktoken
from copy import deepcopy, copy
from collections import defaultdict
import requests
import tempfile
from tqdm import tqdm
import requests
import dill
import os
import re
from prompts import prompts
from langchain.document_loaders import MathpixPDFLoader
from datetime import datetime, timedelta

from langchain.llms import OpenAI
from langchain.agents import load_tools
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain import OpenAI, ConversationChain
from langchain.embeddings import OpenAIEmbeddings
from review_criterias import review_params
from pathlib import Path
from more_itertools import peekable
from concurrent.futures import Future

import openai
import tiktoken
try:
    import ujson as json
except ImportError:
    import json


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
from langchain.vectorstores.base import VectorStore
from langchain.schema import Document as LangchainDocument
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import TextLoader
from llama_index.data_structs.node import Node, DocumentRelationship
from llama_index import LangchainEmbedding, ServiceContext
from llama_index import GPTTreeIndex, SimpleDirectoryReader
from langchain.document_loaders import PyPDFLoader


from langchain.utilities import SerpAPIWrapper
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from typing import Optional, Type
from langchain.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain.tools import DuckDuckGoSearchRun
from langchain.utilities import BingSearchAPIWrapper, DuckDuckGoSearchAPIWrapper
from langchain.tools import DuckDuckGoSearchResults
from langchain.prompts import PromptTemplate

from common import *
from base import *
import ai21
from langchain.schema import Document

pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

import logging
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

from DocIndex import DocIndex, DocFAISS, create_immediate_document_index, create_index_faiss
from langchain.memory import ConversationSummaryMemory, ChatMessageHistory
import secrets
import string
import tiktoken
alphabet = string.ascii_letters + string.digits

class Conversation:
    def __init__(self, user_id, openai_embed, storage, conversation_id) -> None:
        self.conversation_id = conversation_id
        self.title = 'Start the Conversation'
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.user_id = user_id
        folder = os.path.join(storage, f"{self.conversation_id}")
        self._storage = folder
        os.makedirs(folder, exist_ok=True)
        self.store_separate = ["indices", "raw_documents", "raw_documents_index", "memory", "messages"]
        
        self.running_summary_length_limit = 1000
        self.last_message_length_limit = 1000
        memory = {
                    "running_summary":[], # List of strings, each string is a running summary of chat till now.
                    "salient_points_and_unforgettables":[] # List of strings, each string comes from one turn of chat in which user asks a question and the agent/model answers it.
                }
        messages = list() # list of message objects of structure like `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"},`
        indices = dict(message_index=create_index_faiss([''], openai_embed, doc_id=self.conversation_id,), 
                            summary_index=create_index_faiss([''], openai_embed, doc_id=self.conversation_id,),
                            salient_index=create_index_faiss([''], openai_embed, doc_id=self.conversation_id,), 
                            document_index=create_index_faiss([''], openai_embed, doc_id=self.conversation_id,),
                            )
        raw_documents = dict() # Dict[src-link, Dict] of Dict of Document objects (title, source, document, chunks, summary,)
        raw_documents_index = dict() # Dict[src-link, Index]
        self.set_field("memory", memory)
        self.set_field("messages", messages)
        self.set_field("indices", indices)
        self.set_field("raw_documents", raw_documents)
        self.set_field("raw_documents_index", raw_documents_index)
        self.save_local()

    
    # Make a method to get useful prior context and encapsulate all logic for getting prior context
    # Make a method to persist important details and encapsulate all logic for persisting important details in a function
    
    @staticmethod
    def load_local(folder):
        original_folder = folder
        folder = os.path.join(folder, os.path.basename(folder)+".index")
        import dill
        try:
            with open(folder, "rb") as f:
                obj = dill.load(f)
                setattr(obj, "_storage", original_folder)
                return obj
        except Exception as e:
            logger.error(
                f"Error loading from local storage {folder} with error {e}")
            try:
                shutil.rmtree(original_folder)
            except Exception as e:
                logger.error(
                    f"Error deleting local storage {folder} with error {e}")
            return None
    
    def save_local(self):
        import dill
        doc_id = self.conversation_id
        folder = self._storage
        os.makedirs(folder, exist_ok=True)
        os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
        path = Path(folder)
        lock_location = os.path.join(os.path.join(path.parent.parent, "locks"), f"{doc_id}")
        filepath = os.path.join(folder, f"{doc_id}.index")
        lock = FileLock(f"{lock_location}.lock")
        if hasattr(self, "api_keys"):
            presave_api_keys = self.api_keys
            self.api_keys = {k: None for k, v in self.api_keys.items()}
        
        with lock.acquire(timeout=600):
            previous_attr = dict()
            for k in self.store_separate:
                if hasattr(self, k):
                    previous_attr[k] = getattr(self, k)
                    setattr(self, k, None)
            with open(filepath, "wb") as f:
                dill.dump(self, f)
            for k, v in previous_attr.items():
                setattr(self, k, v)
        if hasattr(self, "api_keys"):
            self.api_keys = presave_api_keys
    
    def get_field(self, top_key):
        import dill
        doc_id = self.conversation_id

        folder = self._storage
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")

        try:
            assert top_key in self.store_separate
        except Exception as e:
            raise ValueError(f"Invalid top_key {top_key} provided")
        logger.info(f"Get doc data for top_key = {top_key}, folder = {folder}, filepath = {filepath} exists = {os.path.exists(filepath)}, json filepath = {json_filepath} exists = {os.path.exists(json_filepath)}, already loaded = {getattr(self, top_key, None) is not None}")
        if getattr(self, top_key, None) is not None:
            return getattr(self, top_key, None)
        else:
            if os.path.exists(json_filepath):
                with open(json_filepath, "r") as f:
                    obj = json.load(f)
                setattr(self, top_key, obj)
                return obj
            elif os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    obj = dill.load(f)
                if top_key not in ["indices", "raw_documents", "raw_documents_index"]:
                    with open(json_filepath, "w") as f:
                        json.dump(obj, f)
                setattr(self, top_key, obj)
                return obj
            else:
                return None
    
    def set_field(self, top_key, value, overwrite=False):
        import dill
        doc_id = self.conversation_id
        folder = self._storage
        print(folder)
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")
        path = Path(folder)
        lock_location = os.path.join(os.path.join(path.parent.parent, "locks"), f"{doc_id}-{top_key}")
        lock = FileLock(f"{lock_location}.lock")
        with lock.acquire(timeout=600):
            tk = self.get_field(top_key)
            assert (type(tk) == type(value) or tk is None) or (isinstance(tk, (tuple, list)) and isinstance(value, (tuple, list)))
            if tk is not None:
                if isinstance(tk, dict) and not overwrite:
                    tk.update(value)
                elif isinstance(tk, list) and not overwrite:
                    tk.extend(value)
                elif isinstance(tk, str) and not overwrite:
                    tk = tk + value
                elif isinstance(tk, tuple) and not overwrite:
                    tk = tk + value
                else:
                    tk = value
                setattr(self, top_key, tk)
            else:
                setattr(self, top_key, value)
            if top_key not in ["indices", "raw_documents_index"]:
                with open(json_filepath, "w") as f:
                    json.dump(getattr(self, top_key, None), f)
            else:
                with open(os.path.join(filepath), "wb") as f:
                    dill.dump(getattr(self, top_key, None), f)
    
    @timer
    def retrieve_prior_context(self, query, requery=False):
        encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
        # Lets get the previous 2 messages, upto 1000 tokens
        previous_messages = self.get_field("messages")[-6:]
        previous_messages = '\n\n'.join([f"Sender: {m['sender']}\n'''{m['text']}'''\n" for m in previous_messages])
        
        running_summary = self.get_field("memory")["running_summary"][-1:]
        summary_nodes = self.get_field("indices")["summary_index"].similarity_search(query, k=3)
        summary_nodes = [n.page_content for n in summary_nodes]
        not_taken_summaries = running_summary + self.get_field("memory")["running_summary"][-3:]
        summary_nodes = [n for n in summary_nodes if n not in not_taken_summaries]
        summary_nodes = [n for n in summary_nodes if len(n.strip()) > 0]
        # summary_text = get_first_last_parts("\n".join(summary_nodes + running_summary), 0, 1000)

        message_nodes = self.get_field("indices")["message_index"].similarity_search(query, k=3)
        message_nodes = [n.page_content for n in message_nodes]
        not_taken_messages = self.get_field("messages")[-6:]
        message_nodes = [n for n in message_nodes if n not in not_taken_messages]
        message_nodes = [n for n in message_nodes if len(n.strip()) > 0]
        
        salient_points = self.get_field("memory")["salient_points_and_unforgettables"][-1:]
        salient_nodes = self.get_field("indices")["salient_index"].similarity_search(query, k=3)
        salient_nodes = [n.page_content for n in salient_nodes]
        not_taken_salient = salient_points + self.get_field("memory")["salient_points_and_unforgettables"][-3:]
        salient_nodes = [n for n in salient_nodes if n not in not_taken_salient]
        salient_nodes = [n for n in salient_nodes if len(n.strip())>0]
        # salient_text = get_first_last_parts("\n".join(salient_nodes + salient_points), 0, 1000)
        prior_context = dict()
        rephrase = ''
        if requery:
            requery_salient_text = get_first_last_parts("\n".join(salient_nodes + salient_points), 0, 1000)
            requery_summary_text = get_first_last_parts("\n".join(summary_nodes + running_summary), 0, 1000)
            llm = CallLLm(self.get_api_keys(), use_gpt4=False)
            prompt = f"""You are given conversation details between a human and an AI. 
Based on the given conversation details and human's last response or query we want to search our database of responses.
You will generate a contextualised query based on the given conversation details and human's last response or query.
The query should be a question or a statement that can be answered by the AI or by searching in our semantic database.
Ensure that the rephrased and contextualised version is different from the original query.
The summary of the conversation is as follows:
{requery_salient_text}

The salient points of the conversation are as follows:
{requery_summary_text}

The last 6 messages of the conversation are as follows:
{get_first_last_parts(previous_messages, 0, 1000)}

The last message of the conversation sent by the human is as follows:
{query}

Rephrase and contextualise the last message of the human as a question or a statement using the given conversation details.
Rephrased and contextualised human's last message:
"""
            rephrase = llm(prompt, temperature=0.7, stream=False)
            logger.info(f"Rephrased and contextualised human's last message: {rephrase}")
            prior_context = self.retrieve_prior_context(rephrase, requery=False)
            del prior_context["previous_messages"]
            summary_nodes = [s for s in prior_context["summary_nodes"] if s not in summary_nodes] + summary_nodes
            summary_nodes = [n for n in summary_nodes if len(n.strip()) > 0]
            salient_nodes = [s for s in prior_context["salient_nodes"] if s not in salient_nodes] + salient_nodes
            salient_nodes = [n for n in salient_nodes if len(n.strip()) > 0]
            message_nodes = [s for s in prior_context["message_nodes"] if s not in message_nodes] + message_nodes
            message_nodes = [n for n in message_nodes if len(n.strip()) > 0]

        # We return a dict
        return dict(previous_messages=previous_messages, 
                    summary_nodes=summary_nodes + running_summary,
                    message_nodes=message_nodes,
                    salient_nodes=salient_nodes + salient_points,
                    rephrase=rephrase)
    
    def get_document_context(self, query):
        # Lets get anything from document index even if a document is not  referred.
        # Lets do full scan on documents if a document is referred.
        
        pass
    
    @timer
    def persist_current_turn(self, query, response):
        # message format = `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"}`
        # set the two messages in the message list as per above format.
        self.set_field("messages", [
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + query, signed=False)), "text": query, "sender": "user", "user_id": self.user_id, "conversation_id": self.conversation_id}, 
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + response, signed=False)), "text": response, "sender": "model", "user_id": self.user_id, "conversation_id": self.conversation_id}])
        
        llm = CallLLm(self.get_api_keys(), use_gpt4=False)
        prompt = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
Using these you will write a new summary of the conversation. Your summary should capture everything that has happened in the conversation till now without a recency bias. Your summary must keep any important details that have been mentioned in the previous summary.
The summary of the conversation is as follows:
{"".join(self.get_field("memory")["running_summary"][-1:])}

The last 2 messages of the conversation are as follows:
User query: '''{query}'''
System response: '''{response}'''

Now lets write a new summary of the conversation.
Summary of the conversation till now:
"""
        summary = get_async_future(llm, prompt, temperature=0.2, stream=False)
        llm = CallLLm(self.get_api_keys(), use_gpt4=False)
        prompt = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. We also have a list of salient points of the conversation.
Using these you will write a new set of salient points that capture the salient, important and noteworthy aspects and details from the user query and system response. 
Your salient points should focus on the current query and response and should not be biased towards the previous salient points. Your salient points should be different from the previous salient points and from summary. 
Capture what might be useful in future and if user has provided any information or important details then capture that as well.
The summary of the conversation is as follows:
'''{"".join(self.get_field("memory")["running_summary"][-1:])}'''

The last 2 messages of the conversation are as follows:
User query: '''{query}'''
System response: '''{response}'''

The salient points of the conversation are as follows:
'''{"".join(self.get_field("memory")["salient_points_and_unforgettables"][-1:])}'''

Now lets write a new set of salient points of the conversation.
Salient points of the conversation till now:
"""
        salient_points = get_async_future(llm, prompt, temperature=0.2, stream=False)
        if self.title == 'Start the Conversation':
            llm = CallLLm(self.get_api_keys(), use_gpt4=False)
            prompt = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. We also have a list of salient points of the conversation.
        Using these you will write a new title for this conversation. 
        The summary of the conversation is as follows:
        '''{"".join(self.get_field("memory")["running_summary"][-1:])}'''

        The last 2 messages of the conversation are as follows:
        User query: '''{query}'''
        System response: '''{response}'''

        The salient points of the conversation are as follows:
        '''{"".join(self.get_field("memory")["salient_points_and_unforgettables"][-1:])}'''

        Now lets write a title of the conversation.
        Title of the conversation:
                """
            title = get_async_future(llm, prompt, temperature=0.2, stream=False)
        else:
            title = wrap_in_future(self.title)
        summary = summary.result()
        salient_points = salient_points.result()
        self.title = title.result()
        memory = self.get_field("memory")
        memory["running_summary"].append(summary)
        memory["salient_points_and_unforgettables"].append(salient_points)
        self.set_field("memory", memory)
        
        indices = self.get_field("indices")
        message_index_new = FAISS.from_texts([query, response], get_embedding_model(self.get_api_keys()))
        message_index = indices["message_index"].merge_from(message_index_new)
        
        salient_index_new = FAISS.from_texts([salient_points], get_embedding_model(self.get_api_keys()))
        salient_index = indices["salient_index"].merge_from(salient_index_new)
        
        summary_index_new = FAISS.from_texts([summary], get_embedding_model(self.get_api_keys()))
        summary_index = indices["summary_index"].merge_from(summary_index_new)
        
        self.set_field("indices", indices)
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_local()

    def __call__(self, query):
        for txt in self.reply(query):
            yield json.dumps(txt)+"\n"

    
    def reply(self, query):
        # Get prior context
        # Get document context
        # TODO: plan and pre-critique
        # TODO: post-critique and improve
        # TODO: Use gpt-3.5-16K for longer contexts as needed.
        # query payload below, actual query is the messageText
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        """
        {"messageText":"Hey there","permanentMessageText":"Some custom instructions","checkboxes":{"perform_web_search":false,"use_multiple_docs":false,"provide_detailed_answers":false,"googleScholar":false,"additional_docs_to_read":[]},"links":["www.example.com"],"search":["what is self attention?"]}
        """
        
        prior_context = self.retrieve_prior_context(query["messageText"], requery=False)
        previous_messages = prior_context["previous_messages"]
        summary_nodes = prior_context["summary_nodes"]
        message_nodes = prior_context["message_nodes"]
        salient_nodes = prior_context["salient_nodes"]
        
        llm = CallLLm(self.get_api_keys(), use_gpt4=True,)
        if llm.use_gpt4:
            
            salient_text = get_first_last_parts("\n".join(salient_nodes), 0, 1000)
            summary_text = get_first_last_parts("\n".join(summary_nodes), 0, 1000)
            used_len = len(enc.encode(summary_text + salient_text))
            previous_messages = get_first_last_parts(previous_messages, 0, 4000 - used_len)
            used_len = len(enc.encode(previous_messages)) + used_len
            message_text = get_first_last_parts("\n".join(message_nodes), 0, 4500 - used_len)
            permanent_instructions = get_first_last_parts(query["permanentMessageText"], 0, 500)
        else:
            salient_text = get_first_last_parts("\n".join(salient_nodes), 0, 500)
            summary_text = get_first_last_parts("\n".join(summary_nodes), 0, 500)
            used_len = len(enc.encode(summary_text + salient_text))
            previous_messages = get_first_last_parts(previous_messages, 0, 1500 - used_len)
            used_len = len(enc.encode(previous_messages)) + used_len
            message_text = get_first_last_parts("\n".join(message_nodes), 0, 2000 - used_len)
            permanent_instructions = get_first_last_parts(query["permanentMessageText"], 0, 250)
        
        prompt = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. We also have a list of salient points of the conversation.
You are also given the user's most recent query to which we need to respond.

The summary of the conversation is as follows:
{summary_text}

The salient points of the conversation are as follows:
{salient_text}

The last few messages of the conversation are as follows:
{previous_messages}

Few other relevant messages from the conversation are as follows:
{message_text}

The last message of the conversation sent by the human is as follows:
{query["messageText"]}

Now lets write a response to the user's query.
Response to the user's query:
"""
        answer = ''
        main_ans_gen = llm(prompt, temperature=0.7, stream=True)
        for txt in main_ans_gen:
            yield {"text": txt, "status": "in-progress"}
            answer += txt
        answer = answer.replace(prompt, "")
        self.persist_current_turn(query["messageText"], answer)

    
    def get_last_ten_messages(self):
        return self.get_field("messages")[-10:]
    
    def get_message_list(self):
        return self.get_field("messages")
    
    def get_metadata(self):
        return dict(conversation_id=self.conversation_id, user_id=self.user_id, title=self.title, summary_till_now="".join(self.get_field("memory")["running_summary"][-1:]), last_updated=self.last_updated.strftime("%Y-%m-%d %H:%M:%S") if isinstance(self.last_updated, datetime) else self.last_updated)
    
    def delete_last_turn(self):
        messages = self.get_field("messages")
        messages = messages[:-2]
        self.set_field("messages", messages, overwrite=True)
        memory = self.get_field("memory")
        memory["running_summary"] = memory["running_summary"][:-1]
        memory["salient_points_and_unforgettables"] = memory["salient_points_and_unforgettables"][:-1]
        self.set_field("memory", memory, overwrite=True)
        
        indices = self.get_field("indices")
        # TODO: delete from index as well
        
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_local()
    
    def get_api_keys(self):
        logger.info(
            f"get api keys for self hash = {hash(self)} and doc_id = {self.conversation_id}")
        if hasattr(self, "api_keys"):
            api_keys = deepcopy(self.api_keys)
        else:
            raise AttributeError("No attribute named `api_keys`.")
        return api_keys

    def set_api_keys(self, api_keys: dict):
        assert isinstance(api_keys, dict)
        indices = self.get_field("indices")
        for k, j in indices.items():
            if isinstance(j, (FAISS, VectorStore)):
                j.embedding_function.__self__.openai_api_key = api_keys["openAIKey"]
                setattr(j.embedding_function.__self__,
                        "openai_api_key", api_keys["openAIKey"])
        setattr(self, "api_keys", api_keys)
    
    def add_document(self, src_link):
        pass
    
    def __copy__(self):
            # Create a new instance of our class
        cls = self.__class__
        result = cls.__new__(cls)
        # Copy all attributes from self to result. This is a shallow copy.
        result.__dict__.update(self.__dict__)
        for k in self.store_separate:
            if hasattr(result, k):
                setattr(result, k, None)
        
        if hasattr(result, "api_keys"):
            result.api_keys = deepcopy(self.api_keys)

        return result

    def copy(self):
        return self.__copy__()
