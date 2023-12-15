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
from typing import Optional, Type, List
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
    level=logging.ERROR,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)
logger.setLevel(logging.ERROR)
time_logger = logging.getLogger(__name__ + " | TIMING")
time_logger.setLevel(logging.INFO)  # Set log level for this logger

LEN_CUTOFF_WEB_TEXT = 50

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
# try:
#     import ujson as json
# except ImportError:
#     import json
import json
alphabet = string.ascii_letters + string.digits

class Conversation:
    def __init__(self, user_id, openai_embed, storage, conversation_id) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        folder = os.path.join(storage, f"{self.conversation_id}")
        self._storage = folder
        os.makedirs(folder, exist_ok=True)
        memory = {  "title": 'Start the Conversation',
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "running_summary":[], # List of strings, each string is a running summary of chat till now.
                }
        messages = list() # list of message objects of structure like `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"},`
        indices = dict(summary_index=create_index_faiss([''], openai_embed, doc_id=self.conversation_id,))
        self.set_field("memory", memory)
        self.set_field("messages", messages)
        self.set_field("indices", indices)
        self.set_field("uploaded_documents_list", list()) # just a List[str] of doc index ids
        self.save_local()

    
    # Make a method to get useful prior context and encapsulate all logic for getting prior context
    # Make a method to persist important details and encapsulate all logic for persisting important details in a function

    @property
    def store_separate(self):
        return ["indices", "raw_documents", "raw_documents_index", "memory", "messages", "uploaded_documents_list"]
    def add_uploaded_document(self, pdf_url):
        storage = os.path.join(self._storage, "uploaded_documents")
        os.makedirs(storage, exist_ok=True)
        keys = self.get_api_keys()
        keys["mathpixKey"] = None
        keys["mathpixId"] = None
        current_documents: List[DocIndex] = self.get_uploaded_documents()
        current_sources = [d.doc_source for d in current_documents]
        if pdf_url in current_sources:
            return None
        doc_index: DocIndex = create_immediate_document_index(pdf_url, storage, keys)
        doc_index._visible = False
        doc_index.save_local()
        doc_id = doc_index.doc_id
        doc_storage = doc_index._storage
        previous_docs = self.get_field("uploaded_documents_list")
        previous_docs = previous_docs if previous_docs is not None else []
        # deduplicate on basis of doc_id
        previous_docs = [d for i, d in enumerate(previous_docs) if d[0] not in [d[0] for d in previous_docs[:i]]]
        self.set_field("uploaded_documents_list", previous_docs + [(doc_id, doc_storage)], overwrite=True)

    def get_uploaded_documents(self, doc_id=None, readonly=False)->List[DocIndex]:
        try:
            doc_list = self.get_field("uploaded_documents_list")
        except ValueError as e:
            doc_list = None
            self.set_field("uploaded_documents_list", [])
        if doc_list is not None:
            docs = [DocIndex.load_local(doc_storage) for doc_id, doc_storage in doc_list]
        else:
            docs = []
        if doc_id is not None:
            docs = [d for d in docs if d.doc_id == doc_id]
        if not readonly:
            keys = self.get_api_keys()
            for d in docs:
                d.set_api_keys(keys)
        return docs

    def delete_uploaded_document(self, doc_id):
        self.set_field("uploaded_documents_list", [d for d in self.get_field("uploaded_documents_list") if d[0] != doc_id], overwrite=True)

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
        logger.debug(f"Get doc data for top_key = {top_key}, folder = {folder}, filepath = {filepath} exists = {os.path.exists(filepath)}, json filepath = {json_filepath} exists = {os.path.exists(json_filepath)}, already loaded = {getattr(self, top_key, None) is not None}")
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
    
    def _get_lock_location(self, key="all"):
        doc_id = self.conversation_id
        folder = self._storage
        path = Path(folder)
        lock_location = os.path.join(os.path.join(path.parent.parent, "locks"), f"{doc_id}_{key}")
        return lock_location

    def set_field(self, top_key, value, overwrite=False):
        import dill
        doc_id = self.conversation_id
        folder = self._storage
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")
        lock_location = self._get_lock_location(top_key)
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
    def retrieve_prior_context(self, query, links=None, required_message_lookback=6):
        # Lets get the previous 2 messages, upto 1000 tokens
        summary_lookback = 4
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages"), get_async_future(self.get_field, "indices")]
        memory, messages, indices = [f.result() for f in futures]
        previous_messages = messages[-required_message_lookback:] if required_message_lookback != 0 else []
        message_lookback = 2
        previous_messages_text = ""
        while get_gpt4_word_count(previous_messages_text) < 2500 and message_lookback <= required_message_lookback and required_message_lookback != 0:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        previous_messages = previous_messages_text
        running_summary = memory["running_summary"][-1:]
        older_extensive_summary = find_nearest_divisible_by_three(memory["running_summary"])
        if len(memory["running_summary"]) > 4:
            summary_nodes = indices["summary_index"].similarity_search(query, k=6)
            summary_nodes = [n.page_content for n in summary_nodes]
            not_taken_summaries = running_summary + memory["running_summary"][-summary_lookback:]
            summary_nodes = [n for n in summary_nodes if n not in not_taken_summaries]
            summary_nodes = [n for n in summary_nodes if len(n.strip()) > 0][-2:]
            # summary_text = get_first_last_parts("\n".join(summary_nodes + running_summary), 0, 1000)
        else:
            summary_nodes = []

        if len(running_summary) > 0 and running_summary[0] != older_extensive_summary:
            running_summary = [older_extensive_summary] + running_summary

        # We return a dict
        return dict(previous_messages=previous_messages, 
                    summary_nodes=summary_nodes + running_summary)

    def create_title(self, query, response):
        llm = CallLLm(self.get_api_keys(), use_gpt4=False)
        memory = self.get_field("memory")
        if (memory["title"] == 'Start the Conversation' and len(memory["running_summary"]) >= 0) or (len(memory["running_summary"]) >= 5 and len(memory["running_summary"]) % 10 == 1):
            llm = CallLLm(self.get_api_keys(), use_gpt4=False)
            running_summary = memory["running_summary"][-1:]
            running_summary = "".join(running_summary)
            running_summary = f"The summary of the conversation is as follows:\n'''{running_summary}'''" if len(running_summary) > 0 else ''
            prompt = f"""You are given conversation details between a human and an AI. You will write a title for this conversation. 
{running_summary}
The last 2 messages of the conversation are as follows:
User query: '''{query}'''
System response: '''{response}'''

Now lets write a title of the conversation.
Title of the conversation:
"""
            title = get_async_future(llm, prompt, temperature=0.2, stream=False)
        else:
            title = wrap_in_future(self.get_field("memory")["title"])
        return title

    @timer
    def persist_current_turn(self, query, response, new_docs):
        # message format = `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"}`
        # set the two messages in the message list as per above format.
        messages = get_async_future(self.get_field, "messages")
        memory = get_async_future(self.get_field, "memory")
        indices = get_async_future(self.get_field, "indices")
        llm = CallLLm(self.get_api_keys(), use_gpt4=False)
        memory = memory.result()
        messages = messages.result()
        message_lookback = 2
        previous_messages_text = ""

        while get_gpt3_word_count(previous_messages_text) < 1250 and message_lookback < 6:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        msg_set = get_async_future(self.set_field, "messages", [
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + query, signed=False)), "text": query,
             "sender": "user", "user_id": self.user_id, "conversation_id": self.conversation_id},
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + response, signed=False)),
             "text": response, "sender": "model", "user_id": self.user_id, "conversation_id": self.conversation_id}])

        prompt = prompts.persist_current_turn_prompt.format(query=query, response=extract_user_answer(response), previous_messages_text=previous_messages_text, previous_summary=get_first_last_parts("".join(memory["running_summary"][-4:-3] + memory["running_summary"][-1:]), 0, 1000))
        prompt = get_first_last_parts(prompt, 1000, 2500)
        if get_gpt3_word_count(prompt) > 3700:
            prompt = prompts.persist_current_turn_prompt.format(query=query, response=response, previous_messages_text="",
                                                                previous_summary=get_first_last_parts("".join(
                                                                    memory["running_summary"][-4:-3] + memory[
                                                                                                           "running_summary"][
                                                                                                       -1:]), 0, 1000))
        summary = get_async_future(llm, prompt, temperature=0.2, stream=False)
        title = self.create_title(query, extract_user_answer(response))
        memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = title.result()
        summary = summary.result()
        summary_index_new = get_async_future(FAISS.from_texts, [summary], get_embedding_model(self.get_api_keys()))
        memory["title"] = title
        memory["running_summary"].append(summary)
        mem_set = get_async_future(self.set_field, "memory", memory)
        # self.set_field("memory", memory)
        indices = indices.result()
        _ = indices["summary_index"].merge_from(summary_index_new.result())
        self.set_field("indices", indices)
        msg_set.result()
        mem_set.result()
        self.create_deep_summary()

    def create_deep_summary(self):
        indices = get_async_future(self.get_field, "indices")
        memory = get_async_future(self.get_field, "memory")
        messages = self.get_field("messages")
        if len(messages) % 6 != 0:
            return
        memory = memory.result()
        recent_summary = "".join(memory["running_summary"][-1:])
        old_summary = "\n\n".join(memory["running_summary"][-4:-3] + memory["running_summary"][-7:-6])
        message_lookback = 2
        previous_messages_text = ""

        while get_gpt4_word_count(previous_messages_text) < 5000 and message_lookback < 6:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"],"text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        assert get_gpt4_word_count(previous_messages_text) > 0
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        prompt = prompts.long_persist_current_turn_prompt.format(previous_messages=previous_messages_text, previous_summary=recent_summary, older_summary=old_summary)
        summary = llm(prompt, temperature=0.2, stream=False)
        memory["running_summary"][-1] = summary

        summary_index_new = get_async_future(FAISS.from_texts, [summary], get_embedding_model(self.get_api_keys()))
        indices = indices.result()
        _ = indices["summary_index"].merge_from(summary_index_new.result())
        mem_set = get_async_future(self.set_field, "memory", memory)
        self.set_field("indices", indices)
        mem_set.result()

    def delete_message(self, message_id, index):
        get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        messages = self.get_field("messages")
        messages = [m for i, m in enumerate(messages) if m["message_id"] != message_id and i != index]
        self.set_field("messages", messages, overwrite=True)
    def __call__(self, query):
        logger.info(f"Called conversation reply for chat Assistant with Query: {query}")
        for txt in self.reply(query):
            yield json.dumps(txt)+"\n"

    def get_uploaded_documents_for_query(self, query):
        attached_docs = re.findall(r'#doc_\d+', query["messageText"])
        attached_docs = list(set(attached_docs))
        attached_docs_names = attached_docs
        attached_docs = [int(d.split("_")[-1]) for d in attached_docs]
        if len(attached_docs) > 0:
            # assert that all elements of attached docs are greater than equal to 1.
            uploaded_documents = self.get_uploaded_documents()
            attached_docs: List[int] = [d for d in attached_docs if len(uploaded_documents) >= d >= 1]
            attached_docs: List[DocIndex] = [uploaded_documents[d - 1] for d in attached_docs]
            doc_infos = [d.title for d in attached_docs]
            # replace each of the #doc_1, #doc_2 etc with the doc_infos
            for i, d in enumerate(attached_docs_names):
                query["messageText"] = query["messageText"].replace(d, f"{d} (Title of {d} '{doc_infos[i]}')\n")
        return query, attached_docs, attached_docs_names

    def get_prior_messages_summary(self, query:str)->str:
        summary_lookback = 8
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages"),
                   get_async_future(self.get_field, "indices")]
        memory, messages, indices = [f.result() for f in futures]
        previous_messages = messages[-10:]
        previous_messages = [{"sender": m["sender"],"text": extract_user_answer(m["text"])} for m in previous_messages]
        prev_msg_text = []
        for m in reversed(previous_messages):
            prev_msg_text.append(f"{m['sender']}:\n'''{m['text']}'''")
            if get_gpt3_word_count("\n\n".join(prev_msg_text)) > 9000:
                break
        previous_messages = "\n\n".join(reversed(prev_msg_text))
        running_summary = memory["running_summary"][-1:]
        older_extensive_summary = find_nearest_divisible_by_three(memory["running_summary"])
        if len(memory["running_summary"]) > 4:
            summary_nodes = indices["summary_index"].similarity_search(query, k=8)
            summary_nodes = [n.page_content for n in summary_nodes]
            not_taken_summaries = running_summary + memory["running_summary"][-summary_lookback:]
            summary_nodes = [n for n in summary_nodes if n not in not_taken_summaries]
            summary_nodes = [n for n in summary_nodes if len(n.strip()) > 0][-2:]
        else:
            summary_nodes = []

        if len(running_summary) > 0 and running_summary[0] != older_extensive_summary:
            running_summary = [older_extensive_summary] + running_summary
        summary_nodes = summary_nodes + running_summary
        summary_text = []
        for s in reversed(summary_nodes):
            summary_text.append(s)
            if get_gpt3_word_count("\n\n".join(summary_text)) > 3_000:
                break
        summary_nodes = "\n".join(reversed(summary_text))
        prompt = f"""You are information extraction agent who will extract information for answering a query given the previous conversation details between a human and an AI. 
The user query is as follows:
'''{query}'''

Extract relevant information that might be useful in answering the above user query from the following conversation messages:
'''{previous_messages}'''

The summary of the conversation is as follows:
'''{summary_nodes}'''

Now lets extract relevant information for answering the query from the above conversation messages and summary.
Only provide answer from the conversation messages and summary given above. If no relevant information is found in given context, then output "No relevant information found." only.
Write the extracted information concisely below:
"""
        final_information = CallLLm(self.get_api_keys(), use_gpt4=False, use_16k=True)(prompt, temperature=0.2, stream=False)
        # We return a string
        return final_information
    @property
    def max_time_to_wait_for_web_results(self):
        return 15
    def reply(self, query):
        # Get prior context
        # Get document context
        # TODO: plan and pre-critique
        # TODO: post-critique and improve
        # TODO: Use gpt-3.5-16K for longer contexts as needed.
        # TODO: get prior messages and use gpt-3.5 16K for getting a good prior long context for current message. Do this asynchronously.
        # query payload below, actual query is the messageText
        get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        pattern = r'\[.*?\]\(.*?\)'
        st = time.time()
        query["messageText"] = query["messageText"].strip()
        attached_docs_future = get_async_future(self.get_uploaded_documents_for_query, query)
        query, attached_docs, attached_docs_names = attached_docs_future.result()
        answer = ''
        summary = "".join(self.get_field("memory")["running_summary"][-1:])

        checkboxes = query["checkboxes"]
        enablePreviousMessages = str(checkboxes.get('enable_previous_messages', "infinite")).strip()
        if enablePreviousMessages == "infinite":
            message_lookback = 6
        else:
            message_lookback = int(enablePreviousMessages) * 2

        previous_context = summary if len(summary.strip()) > 0 and message_lookback >= 0 else ''
        user_query = query['messageText']
        link_context = previous_context + user_query
        yield {"text": '', "status": "Getting prior chat context ..."}
        additional_docs_to_read = query["additional_docs_to_read"]
        searches = [s.strip() for s in query["search"] if s is not None and len(s.strip()) > 0]
        google_scholar = checkboxes["googleScholar"]
        provide_detailed_answers = int(checkboxes["provide_detailed_answers"])
        perform_web_search = checkboxes["perform_web_search"] or len(searches) > 0
        links = [l.strip() for l in query["links"] if
                 l is not None and len(l.strip()) > 0]  # and l.strip() not in raw_documents_index

        prior_chat_summary_future = None
        unchanged_message_lookback = message_lookback
        if (google_scholar or perform_web_search or len(links) > 0 or len(attached_docs) > 0 or len(
                additional_docs_to_read) > 0) and message_lookback >= 1 and provide_detailed_answers >=2:
            prior_chat_summary_future = get_async_future(self.get_prior_messages_summary, query["messageText"])
            message_lookback = min(4, message_lookback)
        web_search_tmp_marker_name = None
        if google_scholar or perform_web_search:
            web_search_tmp_marker_name = self.conversation_id + "_web_search" + str(time.time())
            create_tmp_marker_file(web_search_tmp_marker_name)
            logger.info(f"Time to Start Performing web search with chat query with elapsed time as {(time.time() - st):.2f}")
            yield {"text": '', "status": "performing google scholar search" if google_scholar else "performing web search"}
            web_results = get_async_future(web_search_queue, user_query, 'helpful ai assistant',
                                           previous_context,
                                           self.get_api_keys(), datetime.now().strftime("%Y-%m"), extra_queries=searches,
                                           gscholar=google_scholar, provide_detailed_answers=provide_detailed_answers, web_search_tmp_marker_name=web_search_tmp_marker_name)

        if (provide_detailed_answers == 0 or provide_detailed_answers == 1) and (len(links) + len(attached_docs) + len(additional_docs_to_read) == 1 and len(
            searches) == 0):
            provide_detailed_answers = 2
        # raw_documents_index = self.get_field("raw_documents_index")
        link_result_text = ''
        full_doc_texts = {}
        if len(links) > 0:
            yield {"text": '', "status": "Reading your provided links."}
            link_future = get_async_future(read_over_multiple_links, links, [""] * len(links), [link_context] * (len(links)), self.get_api_keys(), provide_detailed_answers=max(0, int(provide_detailed_answers) - 1) or len(links) <= 2)

        if len(attached_docs) > 0:
            yield {"text": '', "status": "Reading your attached documents."}
            conversation_docs_future = get_async_future(get_multiple_answers,
                                                        query["messageText"],
                                                        attached_docs,
                                                        summary if message_lookback >= 1 else '',
                                                        max(0, int(provide_detailed_answers) - 1),
                                                        False,
                                                        True)
        doc_answer = ''
        if len(additional_docs_to_read) > 0:
            yield {"text": '', "status": "reading your documents"}
            doc_future = get_async_future(get_multiple_answers,
                                          query["messageText"],
                                          additional_docs_to_read,
                                          summary if message_lookback >= 1 else '',
                                          max(0, int(provide_detailed_answers) - 1),
                                          False)
        web_text = ''
        prior_context_future = get_async_future(self.retrieve_prior_context,
            query["messageText"], links=links if len(links) > 0 else None, required_message_lookback=message_lookback)
        if len(links) > 0:
            link_read_st = time.time()
            link_result_text = "We could not read the links you provided. Please try again later."
            all_docs_info = []
            while True and ((time.time() - link_read_st) < self.max_time_to_wait_for_web_results * 6):
                if (time.time() - link_read_st) > (self.max_time_to_wait_for_web_results * 2):
                    yield {"text": '', "status": "Link reading taking long time ... "}
                if link_future.done():
                    link_result_text, all_docs_info = link_future.result()
                    break
                time.sleep(0.2)

            read_links = re.findall(pattern, link_result_text)
            read_links = list(set([link.strip() for link in read_links if len(link.strip())>0]))
            if len(all_docs_info) > 0:
                read_links = "\nWe read the below links:\n" + "\n".join([f"{i+1}. {wta}" for i, wta in enumerate(read_links)]) + "\n"
                yield {"text": read_links, "status": "Finished reading your provided links."}
            else:
                read_links = "\nWe could not read any of the links you provided. Please try again later. Timeout at 30s.\n"
                yield {"text": read_links, "status": "Finished reading your provided links."}
            yield {"text": "\n", "status": "Finished reading your provided links."}

            logger.info(f"Time taken to read links: {time.time() - st}")
            logger.debug(f"Link result text:\n```\n{link_result_text}\n```")
        qu_dst = time.time()
        if len(additional_docs_to_read) > 0:
            doc_answer = ''
            while True and (time.time() - qu_dst < (self.max_time_to_wait_for_web_results * ((provide_detailed_answers)*5))):
                if doc_future.done():
                    doc_answers = doc_future.result()
                    doc_answer = doc_answers[1].result()["text"]
                    break
                time.sleep(0.2)
            if len(doc_answer) > 0:
                yield {"text": '', "status": "document reading completed"}
            else:
                yield {"text": '', "status": "document reading failed"}
        conversation_docs_answer = ''
        if len(attached_docs) > 0:
            while True and (time.time() - qu_dst < (self.max_time_to_wait_for_web_results * ((provide_detailed_answers)*5))):
                if conversation_docs_future.done():
                    conversation_docs_answer = conversation_docs_future.result()[1].result()["text"]
                    conversation_docs_answer = "\n\n".join([f"For '{ad}' information is given below.\n{cd}" for cd, ad in zip(conversation_docs_answer, attached_docs_names)])
                    break
                time.sleep(0.2)
            if len(conversation_docs_answer) > 0:
                yield {"text": '', "status": "document reading completed"}
            else:
                yield {"text": '', "status": "document reading failed"}

        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        truncate_method = truncate_text_for_gpt4
        if llm.self_hosted_model_url is not None:
            truncate_method = truncate_text_for_others
        elif not llm.use_gpt4:
            truncate_method = truncate_text_for_gpt3
        prior_context = prior_context_future.result()
        previous_messages = prior_context["previous_messages"]
        new_line = "\n"
        summary_text = "\n".join(prior_context["summary_nodes"][-2:] if enablePreviousMessages == "infinite" else (
            prior_context["summary_nodes"][-1:]) if enablePreviousMessages in ["1", "2"] else [])
        executed_partial_two_stage_answering = False
        if perform_web_search or google_scholar:
            search_results = next(web_results.result()[0].result())
            if len(search_results['queries']) > 0:
                yield {"text": "#### Web searched with Queries: \n", "status": "displaying web search queries ... "}
                answer += "#### Web searched with Queries: \n"
                queries = two_column_list(search_results['queries'])
                answer += (queries + "\n")
                yield {"text": queries + "\n", "status": "displaying web search queries ... "}

            if len(search_results['search_results']) > 0:
                if provide_detailed_answers == 1:
                    cut_off = 6
                elif provide_detailed_answers == 2:
                    cut_off = 12
                elif provide_detailed_answers == 3:
                    cut_off = 18
                elif provide_detailed_answers == 4:
                    cut_off = 24
                else:
                    cut_off = 6
                query_results_part1 = search_results['search_results']
                seen_query_results = query_results_part1[:max(10, cut_off)]
                unseen_query_results = query_results_part1[max(10, cut_off):]
                answer += "\n#### Search Results: \n"
                yield {"text": "\n#### Search Results: \n", "status": "displaying web search results ... "}
                query_results = [f"<a href='{qr['link']}'>{qr['title']}</a>" for qr in seen_query_results]
                query_results = two_column_list(query_results)
                answer += (query_results + "\n")
                yield {"text": query_results + "\n", "status": "Reading web search results ... "}

                # if len(unseen_query_results) > 0:
                #     answer += "\n###### Other Search Results: \n"
                #     yield {"text": "\n###### Other Search Results: \n", "status": "displaying web search results ... "}
                #     query_results = [f"<a href='{qr['link']}'>{qr['title']}</a>" for qr in unseen_query_results]
                #     query_results = two_column_list(query_results)
                #     answer += (query_results + "\n")
                #     yield {"text": query_results + "\n", "status": "Reading web search results ... "}
            result_queue = web_results.result()[1]
            web_text_accumulator = []
            full_info = []
            qu_st = time.time()
            logger.info(f"Time to get web search links: {(qu_st - st):.2f}")
            while True:
                qu_wait = time.time()
                break_condition = (len(web_text_accumulator) >= (cut_off//1) and provide_detailed_answers <= 2) or (len(web_text_accumulator) >= (cut_off//2) and provide_detailed_answers >= 3) or ((qu_wait - qu_st) > max(self.max_time_to_wait_for_web_results * 2, self.max_time_to_wait_for_web_results * ((provide_detailed_answers) * (2 if google_scholar else 1))))
                if break_condition and result_queue.empty():
                    break
                one_web_result = None
                if not result_queue.empty():
                    one_web_result = result_queue.get()
                qu_et = time.time()
                if one_web_result is None:
                    time.sleep(0.2)
                    continue
                if one_web_result == TERMINATION_SIGNAL:
                    break

                if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                    web_text_accumulator.append(one_web_result["text"])
                    logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                if one_web_result["full_info"] is not None and isinstance(one_web_result["full_info"], dict):
                    full_info.append(one_web_result["full_info"])
                time.sleep(0.2)

            time_logger.info(f"Time to get web search results without sorting: {(time.time() - st):.2f} and only web reading time: {(time.time() - qu_st):.2f}")
            word_count = lambda s: len(s.split())
            # Sort the array in reverse order based on the word count
            web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            web_text_accumulator = [ws for ws in web_text_accumulator if len(ws.strip().split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found.".lower() not in ws.lower()]
            # Join the elements along with serial numbers.
            if len(web_text_accumulator) >= 4 and provide_detailed_answers > 2:

                first_stage_cut_off = 8 if provide_detailed_answers == 3 else 12
                used_web_text_accumulator_len = len(web_text_accumulator[:first_stage_cut_off])
                full_web_string = ""
                for i, wta in enumerate(web_text_accumulator[:first_stage_cut_off]):
                    web_string = f"{i + 1}.\n{wta}"
                    full_web_string = full_web_string + web_string + "\n\n"
                    if get_gpt4_word_count(full_web_string) > 8000:
                        break
                web_text = full_web_string
                read_links = re.findall(pattern, web_text)
                read_links = list(set([link.strip() for link in read_links if len(link.strip())>0]))
                if len(read_links) > 0:
                    read_links = "\nWe read the below links:\n" + "\n".join(
                        [f"{i + 1}. {wta}" for i, wta in enumerate(read_links)]) + "\n"
                    yield {"text": read_links, "status": "web search completed"}
                else:
                    read_links = "\nWe could not read any of the links you provided. Please try again later. Timeout at 30s.\n"
                    yield {"text": read_links, "status": "web search completed"}
                yield {"text": "\n", "status": "Finished reading few links."}
                web_text = read_links + "\n" + web_text

                link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_text_for_gpt4_16k(
                    link_result_text, web_text, doc_answer, summary_text, previous_messages,
                    query["messageText"],
                    conversation_docs_answer)
                web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer = format_llm_inputs(
                    web_text, doc_answer, link_result_text, summary_text, previous_messages,
                    conversation_docs_answer)

                prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                               summary_text=summary_text,
                                                               previous_messages=previous_messages if provide_detailed_answers > 3 else '',
                                                               permanent_instructions='Include references inline in wikipedia format. Answer concisely and briefly while covering all given references. Keep your answer short, concise and succinct. We will expand the answer later',
                                                               doc_answer=doc_answer, web_text=web_text,
                                                               link_result_text=link_result_text,
                                                               conversation_docs_answer=conversation_docs_answer)
                llm = CallLLm(self.get_api_keys(), use_gpt4=provide_detailed_answers > 3, use_16k=True)
                qu_mt = time.time()
                if len(read_links) > 0:
                    time_logger.info(f"Time taken to start replying (stage 1) for chatbot: {(time.time() - st):.2f}")
                    main_ans_gen = llm(prompt, temperature=0.3, stream=True)
                    answer += "<answer>\n"
                    yield {"text": "<answer>\n", "status": "stage 1 answering in progress"}
                    for txt in main_ans_gen:
                        yield {"text": txt, "status": "stage 1 answering in progress"}
                        answer += txt
                        one_web_result = None
                        if not result_queue.empty():
                            one_web_result = result_queue.get()
                        if one_web_result is not None and one_web_result != TERMINATION_SIGNAL:
                            if one_web_result["text"] is not None and one_web_result["text"].strip() != "" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                                web_text_accumulator.append(one_web_result["text"])
                                logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                            if one_web_result["full_info"] is not None and isinstance(one_web_result["full_info"], dict):
                                full_info.append(one_web_result["full_info"])
                    answer += "</answer>\n"
                    yield {"text": "</answer>\n", "status": "stage 1 answering in progress"}

                    executed_partial_two_stage_answering = True
                    time_logger.info(f"Time taken to end replying (stage 1) for chatbot: {(time.time() - st):.2f}")

                while True:
                    qu_wait = time.time()
                    break_condition = (len(web_text_accumulator) >= (cut_off//2)) or ((qu_wait - qu_mt) > (self.max_time_to_wait_for_web_results * ((provide_detailed_answers - 1) * (2 if google_scholar else 1))))
                    if break_condition and result_queue.empty():
                        break
                    one_web_result = None
                    if not result_queue.empty():
                        one_web_result = result_queue.get()
                    qu_et = time.time()
                    if one_web_result is None:
                        time.sleep(0.2)
                        continue
                    if one_web_result == TERMINATION_SIGNAL:
                        break

                    if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                        web_text_accumulator.append(one_web_result["text"])
                        logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                    if one_web_result["full_info"] is not None and isinstance(one_web_result["full_info"], dict):
                        full_info.append(one_web_result["full_info"])
                    time.sleep(0.2)
                web_text_accumulator = web_text_accumulator[used_web_text_accumulator_len:]
                web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            elif provide_detailed_answers > 2:
                qu_mt = time.time()
                while True:
                    qu_wait = time.time()
                    break_condition = (len(web_text_accumulator) >= cut_off) or ((qu_wait - qu_mt) > (self.max_time_to_wait_for_web_results * ((provide_detailed_answers - 1) * (2 if google_scholar else 1))))
                    if break_condition and result_queue.empty():
                        break
                    one_web_result = None
                    if not result_queue.empty():
                        one_web_result = result_queue.get()
                    qu_et = time.time()
                    if one_web_result is None:
                        time.sleep(0.2)
                        continue
                    if one_web_result == TERMINATION_SIGNAL:
                        break

                    if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                        web_text_accumulator.append(one_web_result["text"])
                        logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                    if one_web_result["full_info"] is not None and isinstance(one_web_result["full_info"], dict):
                        full_info.append(one_web_result["full_info"])
                    time.sleep(0.2)

                web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            full_web_string = ""
            web_text_accumulator = [ws for ws in web_text_accumulator if len(ws.strip().split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found.".lower() not in ws.lower()]
            for i, wta in enumerate(web_text_accumulator):
                web_string = f"{i + 1}.\n{wta}"
                full_web_string = full_web_string + web_string + "\n\n"
                if get_gpt4_word_count(full_web_string) > 12000:
                    break
            web_text = full_web_string
            # web_text = "\n\n".join(web_text_accumulator)
            # full_doc_texts.update({dinfo["link"].strip(): dinfo["full_text"] for dinfo in full_info})
            read_links = re.findall(pattern, web_text)
            read_links = list(set([link.strip() for link in read_links if len(link.strip())>0]))
            if len(read_links) > 0:
                read_links = "\nWe read the below links:\n" + "\n".join([f"{i+1}. {wta}" for i, wta in enumerate(read_links)]) + "\n"
                yield {"text": read_links, "status": "web search completed"}
            else:
                read_links = "\nWe could not read any of the links you provided. Please try again later. Timeout at 30s.\n"
                yield {"text": read_links, "status": "web search completed"}
            yield {"text": "\n", "status": "Finished reading your provided links."}
            web_text = read_links + "\n" + web_text
            time_logger.info(f"Time to get web search results with sorting: {(time.time() - st):.2f}")
            if (len(read_links) <= 2 or len(web_text.split()) < 200) and len(links)==0 and len(attached_docs) == 0 and len(additional_docs_to_read)==0:
                yield {"text": '', "status": "saving answer ..."}
                get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
                return

        # TODO: if number of docs to read is <= 1 then just retrieve and read here, else use DocIndex itself to read and retrieve.
        remove_tmp_marker_file(web_search_tmp_marker_name)
        if (len(links)==1 and len(attached_docs) == 0 and len(additional_docs_to_read)==0 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback==0):
            text = link_result_text.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
            return

        if (len(links)==0 and len(attached_docs) == 0 and len(additional_docs_to_read)==1 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback==0):
            text = doc_answer.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
            return

        if (len(links)==0 and len(attached_docs) == 1 and len(additional_docs_to_read)==0 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback==0):
            text = conversation_docs_answer.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            text = "\n".join(text.replace("The documents that were read are as follows:", "").split("\n")[2:])
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
            return

        if (len(web_text.split()) < 200 and (google_scholar or perform_web_search)) and len(links) == 0 and len(attached_docs) == 0 and len(additional_docs_to_read) == 0 and provide_detailed_answers >= 3:
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
            return
        yield {"text": '', "status": "getting previous context"}
        prior_chat_summary = ""
        wt_prior_ctx = time.time()
        while time.time() - wt_prior_ctx < 15 and prior_chat_summary_future is not None:
            if prior_chat_summary_future.done() and not prior_chat_summary_future.exception():
                prior_chat_summary = prior_chat_summary_future.result()
                break
            time.sleep(0.2)
        time_logger.info(f"Time to wait for prior context with 16K LLM: {(time.time() - wt_prior_ctx):.2f}")

        summary_text = prior_chat_summary + "\n" + summary_text
        link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_text_for_gpt4_32k(
            link_result_text, web_text, doc_answer, summary_text, previous_messages,
            query["messageText"], conversation_docs_answer)
        web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer = format_llm_inputs(
            web_text, doc_answer, link_result_text, summary_text, previous_messages,
            conversation_docs_answer)
        doc_answer = f"Answers from user's stored documents:\n'''{doc_answer}'''\n" if len(
            doc_answer.strip()) > 0 else ''
        web_text = f"Answers from web search:\n'''{web_text}'''\n" if len(web_text.strip()) > 0 else ''
        link_result_text = f"Answers from web links provided by the user:\n'''{link_result_text}'''\n" if len(
            link_result_text.strip()) > 0 else ''
        partial_answer_text = f"We have written a partial answer for the query as below:\n'''\n{answer}\n'''\nTake the partial answer into consideration and continue from there using the new resources provided and your own knowledge. Don't repeat the partial answer.\n" if executed_partial_two_stage_answering else ""
        prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text,
                                                       previous_messages=previous_messages,
                                                       permanent_instructions=partial_answer_text,
                                                       doc_answer=doc_answer, web_text=web_text,
                                                       link_result_text=link_result_text,
                                                       conversation_docs_answer=conversation_docs_answer)
        yield {"text": '', "status": "starting answer generation"}


        llm = CallLLm(self.get_api_keys(), use_gpt4=True, use_16k=True)
        main_ans_gen = llm(prompt, temperature=0.3, stream=True)
        logger.info(
            f"""Starting to reply for chatbot, prompt length: {len(enc.encode(prompt))}, llm extracted prior chat info len: {len(enc.encode(prior_chat_summary))}, summary text length: {len(enc.encode(summary_text))}, 
        last few messages length: {len(enc.encode(previous_messages))}, doc answer length: {len(enc.encode(doc_answer))}, conversation_docs_answer length: {len(enc.encode(conversation_docs_answer))},  web text length: {len(enc.encode(web_text))}, link result text length: {len(enc.encode(link_result_text))}""")
        et = time.time()
        time_logger.info(f"Time taken to start replying for chatbot: {(et - st):.2f}")
        if len(doc_answer) > 0:
            logger.debug(f"Doc Answer: {doc_answer}")
        if len(web_text) > 0:
            logger.debug(f"Web text: {web_text}")
        answer += "<answer>\n"
        yield {"text": "<answer>\n", "status": "stage 1 answering in progress"}
        for txt in main_ans_gen:
            yield {"text": txt, "status": "answering in progress"}
            answer += txt
        answer += "</answer>\n"
        yield {"text": "</answer>\n", "status": "stage 1 answering in progress"}
        time_logger.info(f"Time taken to reply for chatbot: {(time.time() - et):.2f}, total time: {(time.time() - st):.2f}")
        answer = answer.replace(prompt, "")
        yield {"text": '', "status": "saving answer ..."}
        get_async_future(self.persist_current_turn, query["messageText"], answer, full_doc_texts)
        if perform_web_search or google_scholar:
            search_results = next(web_results.result()[0].result())
            if search_results["type"] == "end":
                full_results = search_results["full_results"]
                answer += "\n#### All Search Results: \n"
                yield {"text": "\n#### All Search Results: \n", "status": "displaying web search results ... "}
                query_results = [f"<a href='{qr['link']}'>{qr['title']} [{qr['count']}]</a>" for qr in full_results]
                query_results = two_column_list(query_results)
                answer += (query_results + "\n")
                yield {"text": query_results + "\n", "status": "Showing all results ... "}

    
    def get_last_ten_messages(self):
        return self.get_field("messages")[-10:]
    
    def get_message_list(self):
        return self.get_field("messages")
    
    def get_metadata(self):
        memory = self.get_field("memory")
        return dict(conversation_id=self.conversation_id, user_id=self.user_id, title=memory["title"],
                    summary_till_now="".join(memory["running_summary"][-1:]),
                    last_updated=memory["last_updated"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(memory["last_updated"], datetime) else memory["last_updated"])
    
    def delete_last_turn(self):
        messages = self.get_field("messages")
        messages = messages[:-2]
        self.set_field("messages", messages, overwrite=True)
        memory = self.get_field("memory")
        memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        memory["running_summary"] = memory["running_summary"][:-1]
        self.set_field("memory", memory, overwrite=True)
        
        indices = self.get_field("indices")
        # TODO: delete from index as well

    
    def get_api_keys(self):
        logger.debug(
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
                j.embedding_function = get_embedding_model(api_keys).embed_query
                j.embedding_function.__self__.openai_api_key = api_keys["openAIKey"]
                setattr(j.embedding_function.__self__,
                        "openai_api_key", api_keys["openAIKey"])
        setattr(self, "api_keys", api_keys)
    
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


def format_llm_inputs(web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer):
    web_text = f"""Relevant information from other documents with url links, titles and useful document context are mentioned below:\n\n'''{web_text}'''
    Remember to refer to all the documents provided above in markdown format (like `[title](link) information from document`).""" if len(
        web_text) > 0 else ""
    doc_answer = f"""Results from user provided documents are given below. Questions user has asked usually pertain to these documents. Relevant information from user given documents with url links, titles and useful context are mentioned below:\n\n'''{doc_answer}'''""" if len(
        doc_answer) > 0 else ""
    link_result_text = f"""Results from user provided links are given below. Questions user has asked usually pertain to these links. Relevant information from user given links with url links, titles and useful context are mentioned below:\n\n'''{link_result_text}'''""" if len(
        link_result_text) > 0 else ""
    summary_text = f"""The summary of the conversation is as follows:
    '''{summary_text}'''""" if len(summary_text) > 0 else ''
    previous_messages = f"""Previous chat history between user and assistant:\n'''{previous_messages}'''""" if len(previous_messages) > 0 else ''
    conversation_docs_answer = f"""The documents that were read are as follows:
    '''{conversation_docs_answer}'''""" if len(conversation_docs_answer) > 0 else ''
    return web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer



def truncate_text_for_gpt3(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-3.5-turbo")

def truncate_text_for_gpt4(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4")

def truncate_text_for_gpt4_16k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-16k")

def truncate_text_for_gpt4_32k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-32k")

def truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4"):
    enc = tiktoken.encoding_for_model(model)
    if model == "gpt-4":
        l1 = 7000
        l2 = 1000
        l4 = 1250
    elif model == "gpt-4-16k":
        l1 = 14000
        l2 = 2000
        l4 = 2500
    elif model == "gpt-4-32k":
        l1 = 28000
        l2 = 4000
        l4 = 5000
    else:
        l1 = 2000
        l2 = 500
        l4 = 500
    previous_messages = get_first_last_parts(previous_messages, 0, l2)
    summary_text = get_first_last_parts(summary_text, 0, l4)
    ctx_len_allowed = l1 - len(enc.encode(user_message + previous_messages + summary_text))
    conversation_docs_answer = get_first_last_parts(conversation_docs_answer, 0, ctx_len_allowed)
    link_result_text = get_first_last_parts(link_result_text, 0, ctx_len_allowed - len(enc.encode(conversation_docs_answer)))
    doc_answer = get_first_last_parts(doc_answer, 0, ctx_len_allowed - len(enc.encode(link_result_text + conversation_docs_answer)))
    web_text = get_first_last_parts(web_text, 0, ctx_len_allowed - len(enc.encode(link_result_text + doc_answer + conversation_docs_answer)))
    return link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer

truncate_text_for_others = truncate_text_for_gpt4

import re

def extract_user_answer(text):
    # Pattern to find <answer>...</answer> segments
    pattern = r'<answer>(.*?)</answer>'

    # Find all occurrences of the pattern
    answers = re.findall(pattern, text, re.DOTALL)

    # Check if any answers were found within tags
    if answers:
        # Joining all extracted answers (in case there are multiple <answer> segments)
        return ' '.join(answers).strip()
    else:
        # If no <answer> tags are found, return the entire text
        return text.strip()
