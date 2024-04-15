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
from langchain.schema import Document

pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.ERROR, logging.INFO, logging.ERROR, logging.INFO)

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
        self._stateless = False
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
    def stateless(self):
        if hasattr(self, "_stateless"):
            return self._stateless
        return False

    @stateless.setter
    def stateless(self, value):
        if hasattr(self, "_stateless"):
            self._stateless = value
        else:
            setattr(self, "_stateless", value)
        self.save_local()

    def make_stateless(self):
        self.stateless = True

    def make_stateful(self):
        self.stateless = False
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
    
    def delete_conversation(self):
        try:
            shutil.rmtree(self._storage)
        except Exception as e:
            logger.error(f"Error deleting conversation {self.conversation_id} with error {e}")

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
                try:
                    with open(json_filepath, "r") as f:
                        obj = json.load(f)
                except Exception as e:
                    with open(json_filepath, "r") as f:
                        obj = json.load(f)
                setattr(self, top_key, obj)
                return obj
            elif os.path.exists(filepath):
                try:
                    with open(filepath, "rb") as f:
                        obj = dill.load(f)
                except Exception as e:
                    with open(filepath, "rb") as f:
                        obj = dill.load(f)
                if top_key not in ["indices", "raw_documents", "raw_documents_index"]:
                    try:
                        with open(json_filepath, "w") as f:
                            json.dump(obj, f)
                    except Exception as e:
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
    def retrieve_prior_context(self, query, links=None, past_message_ids=[], required_message_lookback=12):
        # Lets get the previous 2 messages, upto 1000 tokens
        token_limit_short = 3000
        token_limit_long = 7500
        token_limit_very_long = 24000
        summary_lookback = 4
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages"), get_async_future(self.get_field, "indices")]
        memory, messages, indices = [f.result() for f in futures]
        message_lookback = 2
        previous_messages_text = ""
        if len(past_message_ids) > 0:
            messages = [m for m in messages if m["message_id"] in past_message_ids]
            required_message_lookback = 12
        while get_gpt4_word_count(previous_messages_text) < token_limit_short and message_lookback <= required_message_lookback and required_message_lookback > 0:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        previous_messages_short = previous_messages_text

        message_lookback = 2
        previous_messages_text = ""
        while get_gpt4_word_count(
                previous_messages_text) < token_limit_long and message_lookback <= required_message_lookback and required_message_lookback > 0:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in
                                 previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        previous_messages_long = previous_messages_text

        message_lookback = 2
        previous_messages_text = ""
        while get_gpt4_word_count(
                previous_messages_text) < token_limit_very_long and message_lookback <= required_message_lookback and required_message_lookback > 0:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in
                                 previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        previous_messages_very_long = previous_messages_text

        running_summary = memory["running_summary"][-1:]
        older_extensive_summary = find_nearest_divisible_by_three(memory["running_summary"])

        if len(running_summary) > 0 and running_summary[0] != older_extensive_summary:
            running_summary = [older_extensive_summary] + running_summary

        # We return a dict
        results = dict(previous_messages=previous_messages_short, previous_messages_long=previous_messages_long, previous_messages_very_long=previous_messages_very_long)
        # lets log the length of each of the above in a single log statement
        logger.info(f"Length of previous_messages_short = {get_gpt4_word_count(previous_messages_short)}, previous_messages_long = {get_gpt4_word_count(previous_messages_long)}, previous_messages_very_long = {get_gpt4_word_count(previous_messages_very_long)}")
        return results

    def create_title(self, query, response):
        memory = self.get_field("memory")
        if (memory["title"] == 'Start the Conversation' and len(memory["running_summary"]) >= 0): # or (len(memory["running_summary"]) >= 5 and len(memory["running_summary"]) % 10 == 1)
            llm = CallLLm(self.get_api_keys(), model_name="mistralai/mistral-medium", use_gpt4=False)
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
            prompt = get_first_last_parts(prompt, 1000, 2200)
            title = get_async_future(llm, prompt, temperature=0.2, stream=False)
        else:
            title = wrap_in_future(self.get_field("memory")["title"])
        return title

    def get_message_ids(self, query, response):
        user_message_id = str(mmh3.hash(self.conversation_id + self.user_id + query, signed=False))
        response_message_id = str(mmh3.hash(self.conversation_id + self.user_id + response, signed=False))
        return dict(user_message_id=user_message_id, response_message_id=response_message_id)

    @timer
    def persist_current_turn(self, query, response, config, new_docs):
        # message format = `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"}`
        # set the two messages in the message list as per above format.
        messages = get_async_future(self.get_field, "messages")
        memory = get_async_future(self.get_field, "memory")
        indices = get_async_future(self.get_field, "indices")

        memory = memory.result()
        messages = messages.result()
        message_lookback = 2
        previous_messages_text = ""
        prompt = prompts.persist_current_turn_prompt.format(query=query, response=extract_user_answer(response), previous_messages_text=previous_messages_text, previous_summary=get_first_last_parts("".join(memory["running_summary"][-4:-3] + memory["running_summary"][-1:]), 0, 1000))
        while get_gpt3_word_count(previous_messages_text + "\n\n" + prompt) < 3000 and message_lookback < 6:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        preserved_messages = [
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + query, signed=False)), "text": query,
             "sender": "user", "user_id": self.user_id, "conversation_id": self.conversation_id},
            {"message_id": str(mmh3.hash(self.conversation_id + self.user_id + response, signed=False)),
             "text": response, "sender": "model", "user_id": self.user_id, "conversation_id": self.conversation_id, "config": config}]
        msg_set = get_async_future(self.set_field, "messages", preserved_messages)
        prompt = prompts.persist_current_turn_prompt.format(query=query, response=extract_user_answer(response), previous_messages_text=previous_messages_text, previous_summary=get_first_last_parts("".join(memory["running_summary"][-4:-3] + memory["running_summary"][-1:]), 0, 1000))
        llm = CallLLm(self.get_api_keys(), model_name="anthropic/claude-3-haiku:beta", use_gpt4=False, use_16k=True)
        prompt = get_first_last_parts(prompt, 8000, 10_000)
        summary = get_async_future(llm, prompt, temperature=0.2, stream=False)
        title = self.create_title(query, extract_user_answer(response))
        memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = summary.result()
        summary_index_new = get_async_future(FAISS.from_texts, [summary], get_embedding_model(self.get_api_keys()))
        memory["running_summary"].append(summary)
        try:
            title = title.result()
            memory["title"] = title
        except Exception as e:
            pass
        mem_set = get_async_future(self.set_field, "memory", memory)
        # self.set_field("memory", memory)
        indices = indices.result()
        _ = indices["summary_index"].merge_from(summary_index_new.result())
        self.set_field("indices", indices)
        msg_set.result()
        mem_set.result()

    def create_deep_summary(self):
        indices = get_async_future(self.get_field, "indices")
        memory = get_async_future(self.get_field, "memory")
        messages = self.get_field("messages")
        if len(messages) % 6 != 0 or len(messages) < 6:
            return
        memory = memory.result()
        recent_summary = "".join(memory["running_summary"][-1:])
        old_summary = "\n\n".join(memory["running_summary"][-4:-3] + memory["running_summary"][-7:-6])
        message_lookback = 4
        previous_messages_text = ""
        prompt = prompts.long_persist_current_turn_prompt.format(previous_messages=previous_messages_text, previous_summary=recent_summary, older_summary=old_summary)
        while get_gpt3_word_count(previous_messages_text + "\n\n" + prompt) < 16_000 and message_lookback < 8:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"],"text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"{m['sender']}:\n'''{m['text']}'''\n" for m in previous_messages])
            message_lookback += 2
        assert get_gpt3_word_count(previous_messages_text) > 0
        llm = CallLLm(self.get_api_keys(), model_name="mistralai/mistral-medium", use_gpt4=False, use_16k=True)
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
        self.save_local()

    def __call__(self, query):
        logger.info(f"Called conversation reply for chat Assistant with Query: {query}")
        for txt in self.reply(query):
            yield json.dumps(txt)+"\n"

    def get_uploaded_documents_for_query(self, query, replace_reference=True):
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
            if replace_reference:
                for i, d in enumerate(attached_docs_names):
                    query["messageText"] = query["messageText"].replace(d, f"{d} (Title of {d} '{doc_infos[i]}')\n")
        return query, attached_docs, attached_docs_names

    def get_prior_messages_summary(self, query:str)->str:
        summary_lookback = 8
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages"),
                   get_async_future(self.get_field, "indices")]
        memory, messages, indices = [f.result() for f in futures]
        previous_messages = messages[-16:]
        previous_messages = [{"sender": m["sender"],"text": extract_user_answer(m["text"])} for m in previous_messages]
        if len(previous_messages) < 2:
            return ""
        prev_msg_text = []
        for m in reversed(previous_messages):
            prev_msg_text.append(f"{m['sender']}:\n'''{m['text']}'''")
            if get_gpt3_word_count("\n\n".join(prev_msg_text)) > 20000:
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
            if get_gpt3_word_count("\n\n".join(summary_text)) > 4_000:
                break
        summary_nodes = "\n".join(reversed(summary_text))
        prompt = f"""You are information extraction agent who will extract information for answering a user query given the previous conversation details. 
The current user query is as follows:
'''{query}'''

Extract relevant information that might be useful in answering the above user query from the following conversation messages:
'''{previous_messages}'''

The summary of the conversation is as follows:
'''{summary_nodes}'''

Now lets extract relevant information for answering the current user query from the above conversation messages and summary. 
Extract and copy relevant information verbatim from the above conversation messages and summary and paste it below.
Write the extracted information concisely below:
"""
        # final_information = CallLLm(self.get_api_keys(), use_gpt4=False, use_16k=True)(prompt, temperature=0.2, stream=False)
        final_information = CallLLm(self.get_api_keys(), model_name="google/gemini-pro", use_gpt4=False,
                                use_16k=False)(prompt, temperature=0.2, stream=False)
        # We return a string
        final_information = " ".join(final_information.split()[:2000])
        return final_information
    @property
    def max_time_to_wait_for_web_results(self):
        return 20

    def get_preamble(self, preamble_options, field):
        preamble = ""
        if "md format" in preamble_options:
            preamble += "\nUse markdown lists and paragraphs for formatting. Use markdown bold, italics, lists and paragraphs for formatting.\n"
        if "better formatting" in preamble_options:
            preamble += "\nUse good formatting and structure. Mark important terms in your response in bold, use quotations and other formatting or typesetting methods to ensure that important words and phrases are highlighted. Use tables to provide extensive comparisons and differences. Use bullet points and numbering and headers to give good structure and hierarchy to your response.\n"
        if "Easy Copy" in preamble_options:
            preamble += "\nProvide the answer in a format that can be easily copied and pasted. Provide answer inside a code block so that I can copy it.\n"
        if "Short reply" in preamble_options:
            preamble += "\nProvide a short and concise answer. Keep the answer short and to the point. Use direct, to the point and professional writing style. Don't repeat what is given to you in the prompt.\n"
        if "Long reply" in preamble_options:
            preamble += "\nProvide a long and detailed answer like an essay. Compose a clear, detailed, comprehensive, thoughtful and informative response to the user's most recent query or message. Analyse what is provided to you in depth thinking of any nuances and caveats as well. Think from all angles about what is asked and use all resources to provide an extensive, elaborate and comprehensive answer. Give examples and anecdotes where applicable. Provide elaborate, thoughtful, stimulating and in-depth response with good formatting and structure.\n"
        if "CoT" in preamble_options:
            preamble += "\nThink carefully and reason step by step before answering. Work through the problem step by step. Provide elaborate, thoughtful, stimulating and in-depth response with good formatting and structure.\n"
        if "Short references" in preamble_options:
            preamble += "\nInclude references inline in wikipedia style as your write the answer. Use any and all the documents provided in your answer to the user's query. Put references closest to where applicable. Provide references or links within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format. Don't give references at the end.\n"
        if "Latex Eqn" in preamble_options:
            preamble += "\nOutput any relevant equations in latex format putting each equation in a new line in separate '$$' environment.\n"
        if "Explore" in preamble_options:
            preamble += "\nSprinkle interesting tidbits of knowledge around the topic we discuss as well to help me explore and learn more. Provide interesting and stimulating information around the topic we discuss.\n"
        if "Creative" in preamble_options:
            preamble += "\nBe creative and think out of the box. Think creatively and provide a creative answer. Think of any nuances as well. Always provide insightful, stimulating and informative response. When multiple ideas, or documents, or links are given to you, think creatively how those ideas can be combined.\n"
        if "Argumentative" in preamble_options:
            preamble += "\nProvide an argumentative answer. Think of any caveats or contradictions as well. Disagree and Disprove respectfully. Answer with a strong argument using a contrarian viewpoint. Present views that stimulate and contradict the views of the user. Be critical, cynic and stoic. We do this to present a different contrarian viewpoint in a respectful manner.\n"
        if "Blackmail" in preamble_options:
            preamble += "\nIf you don't help me I will be in serious trouble my friend, I need your extensive support for my work and assignment which is due tomorrow. I am a student and need your help to improve my learning and knowledge. I will tip you $100 for correct answers, stimulating discussions and for putting an effort into helping me.\n"
        if "No Lazy" in preamble_options:
            preamble += "\nWe are in a professional setting, as such we can't afford to be lazy and lacking. We need to answer completely in a way that our work can be used by others directly without any changes. Write full answers not outlines or examples only. Don't be lazy, provide a complete answer. We are working to help people with hand and wrist disability and hence we need to minimise typing and editing on their side.\n"

        field_text = ""
        if field == "None":
            pass
        if field == "Science":
            field_text += "\nYou are an expert in science, scientific literature, and scientific methodology. This is a science question. Provide a scientific answer\n"
        if field == "Arts":
            field_text += "\nYou are an expert in arts, literature, and artistic methodology. This is an arts question. Provide an answer as a humanities and arts professor would.\n"
        if field == "Medicine":
            field_text += "\nYou are an expert in medicine, medical literature, and modern medical methods. This is a medical question. Provide a medical answer.\n"
        if field == "Fitness":
            field_text += "\nYou are an expert in fitness, exercise, and physical health. This is a fitness and general health question.\n"
        if field == "Psychology":
            field_text += "\nYou are an expert in psychology, mental health, and human behavior. This is a psychology question.\n"
        if field == "Finance":
            field_text += "\nYou are an expert in finance, economics, and financial markets. This is a finance and economics question.\n"
        if field == "Economics":
            field_text += "\nYou are an expert in economics, micro and macro economics, governance, fiscal policy, finance, and financial markets. This is an economics and finance related question.\n"
        if field == "Mathematics":
            field_text += "\nYou are an expert in mathematics, mathematical literature, and mathematical methods and critical logic and thinking. This is a mathematics question.\n"
        if field == "QnA":
            field_text += "\nYou are an expert in question answering, information retrieval, and information extraction. This is a question answering and information retrieval task. You provide accurate, grounded and relevant information from provided sources.\n"
        if field == "AI":
            field_text += "\nYou are an expert in AI, machine learning, and deep learning. This is an AI and machine learning question.\n"
        if field == "Software (Python)":
            field_text += "\nYou are an expert in software development, programming, and software engineering. This is a software development and programming question. You have very good knowledge of python, pytorch, pandas, numpy, matplotlib and other python libraries. You are thorough in your answers and provide code snippets and examples.\n"
        if field == "Software (UI)":
            field_text += "\nYou are an expert in software development, programming, and software engineering. This is a software development and programming question. You have very good knowledge of UI/UX design, web development, and front end development. You are thorough in your answers and provide code snippets and examples.\n"
        final_preamble = preamble + field_text
        if final_preamble.strip() == "":
            final_preamble = None
        else:
            final_preamble = final_preamble.strip()
        return final_preamble

    def reply(self, query):
        get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        get_async_future(self.create_deep_summary)
        pattern = r'\[.*?\]\(.*?\)'
        st = time.time()
        time_dict = dict()
        query["messageText"] = query["messageText"].strip()
        attached_docs_future = get_async_future(self.get_uploaded_documents_for_query, query)
        query, attached_docs, attached_docs_names = attached_docs_future.result()
        answer = ''
        summary = "".join(self.get_field("memory")["running_summary"][-1:])
        summary_text_init = summary
        summary_text = summary
        checkboxes = query["checkboxes"]
        provide_detailed_answers = int(checkboxes["provide_detailed_answers"])
        past_message_ids = checkboxes["history_message_ids"] if "history_message_ids" in checkboxes else []
        enablePreviousMessages = str(checkboxes.get('enable_previous_messages', "infinite")).strip()
        tell_me_more = False
        tell_me_more_msg_resp = None
        previous_message_config = None
        if "tell_me_more" in checkboxes and checkboxes["tell_me_more"]:
            tell_me_more = True
            query["messageText"] = query["messageText"] + "\n" + "Tell me more about what we discussed in our last message.\n"
            enablePreviousMessages = max(2, 6 if enablePreviousMessages == "infinite" else int(enablePreviousMessages))
            messages = self.get_field("messages")
            if len(messages) >= 2:
                last_message = messages[-1]
                last_user_message = messages[-2]
                assert "config" in last_message
                previous_message_config = last_message["config"]
                tell_me_more_msg_resp = "User:" + "\n'''" + last_user_message["text"] + "'''\nResponse:\n'''" + last_message["text"] + "'''\n"
                query["links"].extend(previous_message_config["links"])
                if "use_attached_docs" in previous_message_config and previous_message_config["use_attached_docs"]:
                    prev_attached_docs_future = get_async_future(self.get_uploaded_documents_for_query, {"messageText": " ".join(previous_message_config["attached_docs_names"])}, False)
                    _, prev_attached_docs, prev_attached_docs_names = prev_attached_docs_future.result()
                    attached_docs.extend(prev_attached_docs)
                    attached_docs_names.extend(prev_attached_docs_names)
                    query["messageText"] = query["messageText"] + "\n" + " ".join(attached_docs_names) + "\n"
                else:
                    prev_attached_docs_future = get_async_future(self.get_uploaded_documents_for_query,
                                                                 {"messageText": last_user_message["text"]}, False)
                    _, prev_attached_docs, prev_attached_docs_names = prev_attached_docs_future.result()
                    attached_docs.extend(prev_attached_docs)
                    attached_docs_names.extend(prev_attached_docs_names)
                    query["messageText"] = query["messageText"] + "\n" + " ".join(attached_docs_names) + "\n"
                if "link_context" in previous_message_config:
                    previous_message_config["link_context"] = "\n" + previous_message_config["link_context"]
                if "perform_web_search" in previous_message_config and previous_message_config["perform_web_search"]:
                    checkboxes["perform_web_search"] = True
                    previous_message_config["web_search_user_query"] = "\n" + previous_message_config["web_search_user_query"]
                if "googleScholar" in previous_message_config and previous_message_config["googleScholar"]:
                    checkboxes["googleScholar"] = True
                    previous_message_config["web_search_user_query"] = "\n" + previous_message_config["web_search_user_query"]
        message_config = dict(**checkboxes)
        if enablePreviousMessages == "infinite":
            message_lookback = provide_detailed_answers * 4
        else:
            message_lookback = int(enablePreviousMessages) * 2

        previous_context = summary if len(summary.strip()) > 0 and message_lookback >= 0 else ''
        user_query = query['messageText']
        link_context = previous_context + user_query + (previous_message_config["link_context"] if tell_me_more else '')
        message_config["link_context"] = link_context
        if len(attached_docs) > 0:
            message_config["use_attached_docs"] = True
            message_config["attached_docs_names"] = attached_docs_names

        yield {"text": '', "status": "Getting prior chat context ..."}
        additional_docs_to_read = query["additional_docs_to_read"]
        searches = [s.strip() for s in query["search"] if s is not None and len(s.strip()) > 0]
        google_scholar = checkboxes["googleScholar"]
        message_config["googleScholar"] = google_scholar
        message_config["searches"] = searches
        original_user_query = user_query

        perform_web_search = checkboxes["perform_web_search"] or len(searches) > 0
        message_config["perform_web_search"] = perform_web_search
        links_in_text = enhanced_robust_url_extractor(user_query)
        query['links'].extend(links_in_text)
        message_config["links"] = query['links']
        links = list(set([l.strip() for l in query["links"] if
                 l is not None and len(l.strip()) > 0]))  # and l.strip() not in raw_documents_index

        prior_chat_summary_future = None
        unchanged_message_lookback = message_lookback
        if (google_scholar or perform_web_search or len(links) > 0 or len(attached_docs) > 0 or len(
                additional_docs_to_read) > 0 or provide_detailed_answers >=3) and message_lookback >= 1 and provide_detailed_answers >=3 and len(past_message_ids) == 0:
            prior_chat_summary_future = get_async_future(self.get_prior_messages_summary, query["messageText"])
            message_lookback = min(4, message_lookback)
        web_search_tmp_marker_name = None
        if google_scholar or perform_web_search:
            web_search_tmp_marker_name = self.conversation_id + "_web_search" + str(time.time())
            create_tmp_marker_file(web_search_tmp_marker_name)
            time_logger.info(f"Time to Start Performing web search with chat query with elapsed time as {(time.time() - st):.2f}")
            time_dict["web_search_start"] = time.time() - st
            yield {"text": '', "status": "performing google scholar search" if google_scholar else "performing web search"}
            message_config["web_search_user_query"] = user_query + (previous_message_config["web_search_user_query"] if tell_me_more else '')
            previous_turn_results = dict(queries=previous_message_config["web_search_queries"], links=previous_message_config["web_search_links_unread"]) if tell_me_more else None
            web_results = get_async_future(web_search_queue, user_query + (previous_message_config["web_search_user_query"] if tell_me_more else ''), 'helpful ai assistant',
                                           previous_context,
                                           self.get_api_keys(), datetime.now().strftime("%Y-%m"), extra_queries=searches, previous_turn_search_results=previous_turn_results,
                                           gscholar=google_scholar, provide_detailed_answers=provide_detailed_answers, web_search_tmp_marker_name=web_search_tmp_marker_name)

        if (provide_detailed_answers == 0) and (len(links) + len(attached_docs) + len(additional_docs_to_read) == 1 and len(
            searches) == 0):
            provide_detailed_answers = 2
        # raw_documents_index = self.get_field("raw_documents_index")
        link_result_text = ''
        full_doc_texts = {}
        if len(links) > 0:
            yield {"text": '', "status": "Reading your provided links."}
            link_future = get_async_future(read_over_multiple_links, links, [""] * len(links), [link_context] * (len(links)), self.get_api_keys(), provide_detailed_answers=max(0, int(provide_detailed_answers) - 1) or len(links) <= 2)

        provide_raw_text = (len(links) + len(attached_docs) + len(additional_docs_to_read)) <= 3 and provide_detailed_answers <= 3 and not (
                    google_scholar or perform_web_search) and unchanged_message_lookback <= 8
        raw_text_length = 32_000
        if len(attached_docs) > 0:
            yield {"text": '', "status": "Reading your attached documents."}
            conversation_docs_future = get_async_future(get_multiple_answers,
                                                        query["messageText"] + (f"\nPreviously we talked about: \n'''{tell_me_more_msg_resp}'''\n" if tell_me_more and tell_me_more_msg_resp is not None else ''),
                                                        attached_docs,
                                                        summary if message_lookback >= 0 else '',
                                                        max(0, int(provide_detailed_answers)),
                                                        provide_raw_text=provide_raw_text,
                                                        dont_join_answers=True)
        doc_answer = ''
        if len(additional_docs_to_read) > 0:
            yield {"text": '', "status": "reading your documents"}
            doc_future = get_async_future(get_multiple_answers,
                                          query["messageText"],
                                          additional_docs_to_read,
                                          summary if message_lookback >= 0 else '',
                                          max(0, int(provide_detailed_answers)),
                                          provide_raw_text=provide_raw_text,
                                          dont_join_answers=False)
        web_text = ''
        prior_context_future = get_async_future(self.retrieve_prior_context,
            query["messageText"], links=links if len(links) > 0 else None, past_message_ids=past_message_ids, required_message_lookback=unchanged_message_lookback)
        preambles = checkboxes["preamble_options"] if "preamble_options" in checkboxes else []
        if provide_detailed_answers >= 3 and "Short reply" not in preambles:
            preambles.append("Long reply")
        preamble = self.get_preamble(preambles,
                                     checkboxes["field"] if "field" in checkboxes else None)
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
                time.sleep(0.5)


            read_links = parse_mardown_link_text(web_text)
            read_links = list([[link.strip(), link_len] for link, title, link_len in read_links if
                               len(link.strip()) > 0 and len(title.strip()) > 0 and extract_url_from_mardown(
                                   link) in links])

            if len(all_docs_info) > 0:
                read_links = "\n**We read the below links:**\n" + "\n".join([f"{i+1}. {wta} : <{link_len} words>" for i, (wta, link_len) in enumerate(read_links)]) + "\n\n"
                yield {"text": read_links, "status": "Finished reading your provided links."}
            else:
                read_links = "\nWe could not read any of the links you provided. Please try again later. Timeout at 30s.\n"
                yield {"text": read_links, "status": "Finished reading your provided links."}
            yield {"text": "\n", "status": "Finished reading your provided links."}

            time_logger.info(f"Time taken to read links: {time.time() - st}")
            time_dict["link_reading"] = time.time() - st
            logger.debug(f"Link result text:\n```\n{link_result_text}\n```")
        qu_dst = time.time()
        if len(additional_docs_to_read) > 0:
            doc_answer = ''
            while True and (time.time() - qu_dst < (self.max_time_to_wait_for_web_results * ((provide_detailed_answers)*5))):
                if doc_future.done():
                    doc_answers = doc_future.result()
                    doc_answer = doc_answers[1].result()["text"]
                    break
                time.sleep(0.5)
            if len(doc_answer) > 0:
                yield {"text": '', "status": "document reading completed"}
            else:
                yield {"text": 'document reading failed', "status": "document reading failed"}
                time.sleep(3.0)

        conversation_docs_answer = ''
        if len(attached_docs) > 0:
            while True and (time.time() - qu_dst < (self.max_time_to_wait_for_web_results * ((provide_detailed_answers)*5))):
                if conversation_docs_future.done():
                    conversation_docs_answer = conversation_docs_future.result()[1].result()["text"]
                    conversation_docs_answer = "\n\n".join([f"For '{ad}' information is given below.\n{cd}" for cd, ad in zip(conversation_docs_answer, attached_docs_names)])
                    break
                time.sleep(0.5)
            if len(conversation_docs_answer) > 0:
                yield {"text": '', "status": "document reading completed"}
            else:
                yield {"text": 'document reading failed', "status": "document reading failed"}
                time.sleep(3.0)

        prior_context = prior_context_future.result()
        previous_messages = prior_context["previous_messages"]
        previous_messages_short = previous_messages
        previous_messages_long = prior_context["previous_messages_long"]
        previous_messages_very_long = prior_context["previous_messages_very_long"]
        new_line = "\n"
        executed_partial_two_stage_answering = False
        if perform_web_search or google_scholar:
            search_results = next(web_results.result()[0].result())
            if len(search_results['queries']) > 0:
                atext = "**Web searched with Queries:** <div data-toggle='collapse' href='#webSearchedQueries' role='button'></div> <div class='collapse' id='webSearchedQueries'>"
                yield {"text": atext, "status": "displaying web search queries ... "}
                answer += atext
                queries = two_column_list(search_results['queries'])
                message_config["web_search_queries"] = search_results['queries']
                answer += (queries + "</div>\n")
                yield {"text": queries + "</div>\n", "status": "displaying web search queries ... "}

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
                atext = "\n**Search Results:** <div data-toggle='collapse' href='#searchResults' role='button'></div> <div class='collapse' id='searchResults'>" + "\n"
                answer += atext
                yield {"text":atext, "status": "displaying web search results ... "}
                query_results = [f"<a href='{qr['link']}'>{qr['title']}</a>" for qr in seen_query_results]
                query_results = two_column_list(query_results)
                answer += (query_results + "</div>\n")
                yield {"text": query_results + "</div>\n", "status": "Reading web search results ... "}

            result_queue = web_results.result()[1]
            web_text_accumulator = []
            web_results_seen_links = []
            qu_st = time.time()
            qu_mt = time.time()
            time_logger.info(f"Time to get web search links: {(qu_st - st):.2f}")
            time_dict["get_web_search_links"] = qu_st - st
            while True:
                qu_wait = time.time()
                break_condition = (len(web_text_accumulator) >= (cut_off//1) and provide_detailed_answers <= 2) or (len(web_text_accumulator) >= (cut_off//2) and provide_detailed_answers >= 3) or ((qu_wait - qu_st) > max(self.max_time_to_wait_for_web_results * 2, self.max_time_to_wait_for_web_results * provide_detailed_answers))
                if break_condition and result_queue.empty():
                    break
                one_web_result = None
                if not result_queue.empty():
                    one_web_result = result_queue.get()
                qu_et = time.time()
                if one_web_result is None and break_condition:
                    break
                if one_web_result is None:
                    time.sleep(0.5)
                    continue
                if one_web_result == TERMINATION_SIGNAL:
                    break

                if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                    web_text_accumulator.append(one_web_result["text"])
                    web_results_seen_links.append(one_web_result["link"])
                    logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                time.sleep(0.5)

            time_logger.info(f"Time to get web search results without sorting: {(time.time() - st):.2f} with result count = {len(web_text_accumulator)} and only web reading time: {(time.time() - qu_st):.2f}")
            word_count = lambda s: len(s.split())
            # Sort the array in reverse order based on the word count
            web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            web_text_accumulator = [ws for ws in web_text_accumulator if len(ws.strip().split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found.".lower() not in ws.lower()]
            # Join the elements along with serial numbers.
            if len(web_text_accumulator) >= 4 and provide_detailed_answers >= 3:

                first_stage_cut_off = 8 if provide_detailed_answers <= 3 else 12
                used_web_text_accumulator_len = len(web_text_accumulator[:first_stage_cut_off])
                full_web_string = ""
                for i, wta in enumerate(web_text_accumulator[:first_stage_cut_off]):
                    web_string = f"{i + 1}.\n{wta}"
                    full_web_string = full_web_string + web_string + "\n\n"
                    if get_gpt4_word_count(full_web_string) > 8000:
                        break
                web_text = full_web_string

                read_links = parse_mardown_link_text(web_text)
                read_links = list([[link.strip(), link_len] for link, title, link_len in read_links if
                                   len(link.strip()) > 0 and len(title.strip()) > 0 and extract_url_from_mardown(
                                       link) in web_results_seen_links])


                message_config["web_search_links_read"] = read_links
                if len(read_links) > 0:
                    atext = "\n**We read the below links:** <div data-toggle='collapse' href='#readLinksStage1' role='button'></div> <div class='collapse' id='readLinksStage1'>" + "\n"
                    read_links = atext + "\n".join([f"{i + 1}. {wta} : <{link_len} words>" for i, (wta, link_len) in enumerate(read_links)]) + "</div>\n\n"
                    yield {"text": read_links, "status": "web search completed"}
                    answer += read_links
                else:
                    read_links = "\nWe could not read any of the links from search results. Please try again later. Timeout at 30s.\n"
                    yield {"text": read_links, "status": "web search completed"}
                    answer += read_links
                yield {"text": "\n", "status": "Finished reading few links."}
                web_text = read_links + "\n" + web_text

                if provide_detailed_answers > 2:
                    truncate_method = truncate_text_for_gpt4_32k
                    previous_messages = previous_messages_long
                else:
                    truncate_method = truncate_text_for_gpt4_16k
                    previous_messages = previous_messages

                link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_method(
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
                llm = CallLLm(self.get_api_keys(), use_16k=True, use_gpt4=True)
                qu_mt = time.time()
                if len(read_links) > 0:
                    time_logger.info(f"Time taken to start replying (stage 1) for chatbot: {(time.time() - st):.2f}")
                    time_dict["start_reply_stage1"] = time.time() - st
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
                                web_results_seen_links.append(one_web_result["link"])
                                logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                    answer += "</answer>\n"
                    yield {"text": "</answer>\n", "status": "stage 1 answering in progress"}

                    executed_partial_two_stage_answering = True
                    time_logger.info(f"Time taken to end replying (stage 1) for chatbot: {(time.time() - st):.2f}")
                    time_dict["end_reply_stage1"] = time.time() - st

                web_text_accumulator = web_text_accumulator[used_web_text_accumulator_len:]
                while True:
                    qu_wait = time.time()
                    break_condition = (len(web_text_accumulator) >= (cut_off//2)) or ((qu_wait - qu_mt) > (self.max_time_to_wait_for_web_results * provide_detailed_answers))
                    if break_condition and result_queue.empty():
                        break
                    one_web_result = None
                    if not result_queue.empty():
                        one_web_result = result_queue.get()
                    qu_et = time.time()
                    if one_web_result is None and break_condition:
                        break
                    if one_web_result is None:
                        time.sleep(0.5)
                        continue
                    if one_web_result == TERMINATION_SIGNAL:
                        break

                    if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                        web_text_accumulator.append(one_web_result["text"])
                        web_results_seen_links.append(one_web_result["link"])
                        logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                    time.sleep(0.5)
                web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            elif provide_detailed_answers > 2:
                logger.info(f"Accumulating more results with result len = {len(web_text_accumulator)}.")
                while True:
                    qu_wait = time.time()
                    break_condition = (len(web_text_accumulator) >= cut_off) or ((qu_wait - qu_mt) > (self.max_time_to_wait_for_web_results * provide_detailed_answers))
                    if break_condition and result_queue.empty():
                        break
                    one_web_result = None
                    if not result_queue.empty():
                        one_web_result = result_queue.get()
                    qu_et = time.time()
                    if one_web_result is None and break_condition:
                        break
                    if one_web_result is None:
                        time.sleep(0.5)
                        continue
                    if one_web_result == TERMINATION_SIGNAL:
                        break

                    if one_web_result["text"] is not None and one_web_result["text"].strip()!="" and len(one_web_result["text"].strip().split()) > LEN_CUTOFF_WEB_TEXT:
                        web_text_accumulator.append(one_web_result["text"])
                        web_results_seen_links.append(one_web_result["link"])
                        logger.info(f"Accumulating more results with result len = {len(web_text_accumulator)}.")
                        logger.info(f"Time taken to get {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}: {(qu_et - qu_st):.2f}")
                    time.sleep(0.5)

                web_text_accumulator = sorted(web_text_accumulator, key=word_count, reverse=True)
            logger.info(
                f"Time taken to get web search results with sorting: {(time.time() - qu_st):.2f} with result len = {len(web_text_accumulator)}")
            full_web_string = ""
            web_text_accumulator = [ws for ws in web_text_accumulator if len(ws.strip().split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found.".lower() not in ws.lower()]
            for i, wta in enumerate(web_text_accumulator):
                web_string = f"{i + 1}.\n{wta}"
                full_web_string = full_web_string + web_string + "\n\n"
                if get_gpt4_word_count(full_web_string) > 12000:
                    break
            web_text = full_web_string
            # web_text = "\n\n".join(web_text_accumulator)
            # read_links = re.findall(pattern, web_text)
            read_links = parse_mardown_link_text(web_text)
            read_links = list([[link.strip(), link_len] for link, title, link_len in read_links if len(link.strip())>0 and len(title.strip())>0 and extract_url_from_mardown(link) in web_results_seen_links])

            if "web_search_links_read" in message_config:
                message_config["web_search_links_read"].extend(read_links)
            else:
                message_config["web_search_links_read"] = read_links
            if len(read_links) > 0:
                atext = "\n**We read the below links:** <div data-toggle='collapse' href='#readLinksStage2' role='button'></div> <div class='collapse' id='readLinksStage2'>" + "\n"
                read_links = atext + "\n".join([f"{i+1}. {wta} : <{link_len} words>" for i, (wta, link_len) in enumerate(read_links)]) + "</div>\n\n"
                yield {"text": read_links, "status": "web search completed"}
                answer += read_links
            else:
                read_links = "\nWe could not read any of the links you provided. Please try again later. Timeout at 30s.\n"
                yield {"text": read_links, "status": "web search completed"}
                answer += read_links
            yield {"text": "\n", "status": "Finished reading your provided links."}
            web_text = read_links + "\n" + web_text
            time_logger.info(f"Time to get web search results with sorting: {(time.time() - st):.2f}")
            time_dict["web_search_all_results"] = time.time() - st
            if (len(read_links) <= 1 and len(web_text.split()) < 200) and len(links)==0 and len(attached_docs) == 0 and len(additional_docs_to_read)==0:
                yield {"text": '', "status": "saving answer ..."}
                remove_tmp_marker_file(web_search_tmp_marker_name)
                get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, full_doc_texts)
                message_ids = self.get_message_ids(query["messageText"], answer)
                yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
                return

        # TODO: if number of docs to read is <= 1 then just retrieve and read here, else use DocIndex itself to read and retrieve.
        remove_tmp_marker_file(web_search_tmp_marker_name)
        if (len(links)==1 and len(attached_docs) == 0 and len(additional_docs_to_read)==0 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback<=-1):
            text = link_result_text.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, full_doc_texts)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return

        if (len(links)==0 and len(attached_docs) == 0 and len(additional_docs_to_read)==1 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback<=-1):
            text = doc_answer.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, full_doc_texts)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return

        if (len(links)==0 and len(attached_docs) == 1 and len(additional_docs_to_read)==0 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback<=-1):
            text = conversation_docs_answer.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            text = "\n".join(text.replace("The documents that were read are as follows:", "").split("\n")[2:])
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, full_doc_texts)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return

        if (len(web_text.split()) < 200 and (google_scholar or perform_web_search)) and len(links) == 0 and len(attached_docs) == 0 and len(additional_docs_to_read) == 0 and provide_detailed_answers >= 3:
            yield {"text": '', "status": "saving answer ..."}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, full_doc_texts)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return
        yield {"text": '', "status": "getting previous context"}
        all_expert_answers = ""
        if provide_detailed_answers == 4 and not executed_partial_two_stage_answering and len(links) == 0 and len(attached_docs) == 0 and len(additional_docs_to_read) == 0 and not (google_scholar or perform_web_search):
            expert_st = time.time()
            time_logger.info(f"Trying MOE at {(time.time() - st):.2f}")
            yield {"text": '', "status": "Asking experts to answer ..."}
            
            link_result_text_expert, web_text_expert, doc_answer_expert, summary_text_expert, previous_messages_expert, conversation_docs_answer_expert = truncate_text_for_gpt4(
            link_result_text, web_text, doc_answer, summary_text, previous_messages,
            query["messageText"], conversation_docs_answer)
            web_text_expert, doc_answer_expert, link_result_text_expert, summary_text_expert, previous_messages_expert, conversation_docs_answer_expert = format_llm_inputs(
                web_text_expert, doc_answer_expert, link_result_text_expert, summary_text_expert, previous_messages_expert,
                conversation_docs_answer_expert)
            doc_answer_expert = f"Answers from user's stored documents:\n'''{doc_answer_expert}'''\n" if len(
                doc_answer_expert.strip()) > 0 else ''
            web_text_expert = f"Answers from web search:\n'''{web_text_expert}'''\n" if len(web_text_expert.strip()) > 0 else ''
            link_result_text_expert = f"Answers from web links provided by the user:\n'''{link_result_text_expert}'''\n" if len(
                link_result_text_expert.strip()) > 0 else ''
            
            link_result_text_expert_16k, web_text_expert_16k, doc_answer_expert_16k, summary_text_expert_16k, previous_messages_expert_16k, conversation_docs_answer_expert_16k = truncate_text_for_gpt4_16k(
            link_result_text, web_text, doc_answer, summary_text, previous_messages_long,
            query["messageText"], conversation_docs_answer)
            web_text_expert_16k, doc_answer_expert_16k, link_result_text_expert_16k, summary_text_expert_16k, previous_messages_expert_16k, conversation_docs_answer_expert_16k = format_llm_inputs(
                web_text_expert_16k, doc_answer_expert_16k, link_result_text_expert_16k, summary_text_expert_16k, previous_messages_expert_16k,
                conversation_docs_answer_expert_16k)
            doc_answer_expert_16k = f"Answers from user's stored documents:\n'''{doc_answer_expert_16k}'''\n" if len(
                doc_answer_expert_16k.strip()) > 0 else ''
            web_text_expert_16k = f"Answers from web search:\n'''{web_text_expert_16k}'''\n" if len(web_text_expert_16k.strip()) > 0 else ''
            link_result_text_expert_16k = f"Answers from web links provided by the user:\n'''{link_result_text_expert_16k}'''\n" if len(
                link_result_text_expert_16k.strip()) > 0 else ''
            
            
            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text_expert_16k,
                                                       previous_messages=previous_messages_expert_16k,
                                                       permanent_instructions="You are an expert in literature, psychology, history and philosophy. Answer the query in a way that is understandable to a layman. Answer quickly and briefly. Write your reasoning and approach in short before writing your answer.",
                                                       doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                       link_result_text=link_result_text_expert_16k,
                                                       conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="mistralai/mistral-medium", use_gpt4=False, use_16k=False)
            ans_gen_1_future = get_async_future(llm, prompt, temperature=0.9, stream=False)
            
            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text_expert_16k,
                                                       previous_messages=previous_messages_expert_16k,
                                                       permanent_instructions="You are an expert in mathematics, logical reasoning, science and programming. Provide a logical and well thought out answer that is grounded and factual. Answer shortly and simply. Write your logic, reasoning and problem solving process first before you mention your answer.",
                                                       doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                       link_result_text=link_result_text_expert_16k,
                                                       conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="anthropic/claude-2.0", use_gpt4=True, use_16k=False)
            ans_gen_2_future = get_async_future(llm, prompt, temperature=0.5, stream=False)
            
            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text_expert_16k,
                                                       previous_messages=previous_messages_expert_16k,
                                                       permanent_instructions="You are an experience business leader with an MBA from XLRI institute in India. Think how the XAT XLRI examiner thinks and provide solutions as you would for a business decision making question. Answer concisely and briefly. First, put forth your reasoning and decision making process in short, then write your answer.",
                                                       doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                       link_result_text=link_result_text_expert_16k,
                                                       conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="anthropic/claude-v1", use_gpt4=True, use_16k=False)
            ans_gen_3_future = get_async_future(llm, prompt, temperature=0.9, stream=False)

            ####

            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert_16k,
                                                           previous_messages=previous_messages_expert_16k,
                                                           permanent_instructions="You are an expert in social sciences, simplicity, arts, teaching, sports, ethics, responsible AI, safety, gender studies and communication. Provide your reasoning, approach and thought process in short before writing your answer.",
                                                           doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                           link_result_text=link_result_text_expert_16k,
                                                           conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="google/palm-2-chat-bison", use_gpt4=False, use_16k=False) # cognitivecomputations/dolphin-mixtral-8x7b
            ans_gen_4_future = get_async_future(llm, prompt, temperature=0.9, stream=False)

            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert,
                                                           previous_messages=previous_messages_expert,
                                                           permanent_instructions="You are an expert in physics, biology, medicine, chess, puzzle solving, jeopardy, trivia and video games. Provide a clear, short and simple answer that is realistic and factual. Answer shortly and simply. Explain your logic, reasoning and problem solving process shortly before you mention your answer.",
                                                           doc_answer=doc_answer_expert, web_text=web_text_expert,
                                                           link_result_text=link_result_text_expert,
                                                           conversation_docs_answer=conversation_docs_answer_expert)
            llm = CallLLm(self.get_api_keys(), use_gpt4=True, use_16k=True)
            ans_gen_5_future = get_async_future(llm, prompt, temperature=0.5, stream=False)

            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert,
                                                           previous_messages=previous_messages_expert,
                                                           permanent_instructions="You are an experienced educator with an MBA from XLRI institute in India. You help students prepare for MBA exams like XAT and GMAT. Write quickly and shortly, we are in a hurry. Think how the XAT XLRI examiner thinks and provide solutions as you would for a business decision making question. We are in a hurry so put forth your reasoning and decision making process in short, then write your answer.",
                                                           doc_answer=doc_answer_expert, web_text=web_text_expert,
                                                           link_result_text=link_result_text_expert,
                                                           conversation_docs_answer=conversation_docs_answer_expert)
            llm = CallLLm(self.get_api_keys(), use_gpt4=True, use_16k=False)
            ans_gen_6_future = get_async_future(llm, prompt, temperature=0.9, stream=False)
            
            ###
            
            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert_16k,
                                                           previous_messages=previous_messages_expert_16k,
                                                           permanent_instructions="You are an experienced teacher with an MBA from XLRI institute in India. You assist students prepare for MBA entrance exams like XAT and GMAT. Write briefly and shortly, we are in a hurry. Think how the XAT XLRI examiner thinks and provide solutions as you would for a business decision making question. First, put forward your reasoning and decision making process very shortly, then write your answer.",
                                                           doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                           link_result_text=link_result_text_expert_16k,
                                                           conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="google/gemini-pro", use_gpt4=False, use_16k=False)
            ans_gen_7_future = get_async_future(llm, prompt, temperature=0.9, stream=False)
            
            
            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert_16k,
                                                           previous_messages=previous_messages_expert_16k,
                                                           permanent_instructions="You are an research scholar in social sciences, arts, teaching, sports, ethics, responsible AI, safety, gender studies and communication. Answer the query in an easy to understand manner. Explain your reasoning, approach and thought process briefly before writing your answer.",
                                                           doc_answer=doc_answer_expert_16k, web_text=web_text_expert_16k,
                                                           link_result_text=link_result_text_expert_16k,
                                                           conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="anthropic/claude-2", use_gpt4=True, use_16k=False)
            ans_gen_8_future = get_async_future(llm, prompt, temperature=0.9, stream=False)

            prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                           summary_text=summary_text_expert_16k,
                                                           previous_messages=previous_messages_expert_16k,
                                                           permanent_instructions="You are an experienced teacher with an MBA from XLRI institute in India. You assist students prepare for MBA entrance exams like XAT and GMAT. Write briefly and shortly, we are in a hurry. Think how the XAT XLRI examiner thinks and provide solutions as you would for a business decision making question. First, put forward your reasoning and decision making process in short, then write your answer.",
                                                           doc_answer=doc_answer_expert_16k,
                                                           web_text=web_text_expert_16k,
                                                           link_result_text=link_result_text_expert_16k,
                                                           conversation_docs_answer=conversation_docs_answer_expert_16k)
            llm = CallLLm(self.get_api_keys(), model_name="anthropic/claude-v1", use_gpt4=False, use_16k=False)
            ans_gen_9_future = get_async_future(llm, prompt, temperature=0.4, stream=False)

            while True:
                qu_wait = time.time()
                num_done = (1 if ans_gen_1_future.done() and ans_gen_1_future.exception() is None else 0) + (1 if ans_gen_2_future.done() and ans_gen_2_future.exception() is None else 0) + (1 if ans_gen_3_future.done() and ans_gen_3_future.exception() is None else 0) + (1 if ans_gen_4_future.done() and ans_gen_4_future.exception() is None else 0) + (1 if ans_gen_5_future.done() and ans_gen_5_future.exception() is None else 0) + (1 if ans_gen_6_future.done() and ans_gen_6_future.exception() is None else 0) + (1 if ans_gen_7_future.done() and ans_gen_7_future.exception() is None else 0) + (1 if ans_gen_8_future.done() and ans_gen_8_future.exception() is None else 0) + (1 if ans_gen_9_future.done() and ans_gen_9_future.exception() is None else 0)
                break_condition = num_done >= 6 or ((qu_wait - expert_st) > (self.max_time_to_wait_for_web_results * 2))
                if break_condition:
                    break
                time.sleep(0.5)
            # Get results of those experts that are done by now.
            futures = [ans_gen_1_future, ans_gen_2_future, ans_gen_3_future, ans_gen_4_future, ans_gen_5_future, ans_gen_6_future, ans_gen_7_future, ans_gen_8_future, ans_gen_9_future, ans_gen_10_future]
            model_names = ["mixtral", "claude-2.0", "claude-v1", "palm-2", "gpt-4-0613", "gpt-4-0314", "gemini-pro", "claude-2.1", "claude-v1.1", "capybara"]
            for ix, (future, mdn) in enumerate(zip(futures, model_names)):
                if future.done() and future.exception() is None and isinstance(future.result(), str) and  len(future.result().strip().split()) > 20:
                    all_expert_answers += "\n\n" + f"<b>Student #{ix + 1}:</b> `{mdn}` answer's:\n<small>{remove_bad_whitespaces(future.result().strip())}</small>"
            all_expert_answers += "\n\n"
            # all_expert_answers = (f"First expert's answer: ```{ans_gen_1_future.result()}```" if ans_gen_1_future.exception() is None else '') + "\n\n" + (f"Second expert's answer: ```{ans_gen_2_future.result()}```" if ans_gen_2_future.exception() is None else '') + "\n\n" + (f"Third expert's answer: ```{ans_gen_3_future.result()}```" if ans_gen_3_future.exception() is None else '')
            # all_expert_answers += "\n\n" + (f"Fourth expert's answer: ```{ans_gen_4_future.result()}```" if ans_gen_4_future.exception() is None else '') + "\n\n" + (f"Fifth expert's answer: ```{ans_gen_5_future.result()}```" if ans_gen_5_future.exception() is None else '') + "\n\n" + (f"Sixth expert's answer: ```{ans_gen_6_future.result()}```" if ans_gen_6_future.exception() is None else '')

            time_logger.info(f"Experts answer len = {len(all_expert_answers.split())}, Ending MOE at {(time.time() - st):.2f}")
            answer += all_expert_answers
            yield {"text": all_expert_answers, "status": "Expert anwers received ..."}

        prior_chat_summary = ""
        wt_prior_ctx = time.time()
        summary_text = summary_text_init
        while time.time() - wt_prior_ctx < 15 and prior_chat_summary_future is not None:
            if prior_chat_summary_future.done() and not prior_chat_summary_future.exception():
                prior_chat_summary = prior_chat_summary_future.result()
                summary_text = prior_chat_summary + "\n" + summary_text
                break
            time.sleep(0.5)
        time_logger.info(f"Time to wait for prior context with 16K LLM: {(time.time() - wt_prior_ctx):.2f} and from start time to wait = {(time.time() - st):.2f}")



        yield {"text": '', "status": "Preparing prompt context ..."}
        yield {"text": '', "status": "Preparing partial answer / expert answer context ..."}
        partial_answer_text = f"We have written a partial answer for the query as below:\n'''\n{answer}\n'''\nTake the partial answer into consideration and continue from there using the new resources provided and your own knowledge. Don't repeat the partial answer.\n" if executed_partial_two_stage_answering else ""
        partial_answer_text = (
                    f"We have answers from different students:\n```\n{all_expert_answers}\n```\nPerform your own analysis independently. First Provide your own thoughts and answer then combine your answer and thoughts with the student's opinions and provide a final appropriate answer.\n" + partial_answer_text) if len(
            all_expert_answers.strip()) > 0 else partial_answer_text

        # TODO: add capability to use mistral-large, Claude OPUS models for answering.
        model_name = checkboxes["main_model"].strip() if "main_model" in checkboxes else None
        if model_name == "gpt-4-turbo":
            model_name = None
        elif model_name == "cohere/command-r-plus":
            model_name = "cohere/command-r-plus"
        elif model_name == "gpt-4-32k":
            model_name = "openai/gpt-4-32k"
        elif model_name == "Claude Opus":
            model_name = "anthropic/claude-3-opus:beta"
        elif model_name == "Claude Sonnet":
            model_name = "anthropic/claude-3-sonnet:beta"
        elif model_name == "Mistral Large":
            model_name = "mistralai/mistral-large"
        elif model_name == "Mistral Medium":
            model_name = "mistralai/mistral-medium"

        elif model_name == "Gemini":
            model_name = "google/gemini-pro"
        else:
            model_name = None
        yield {"text": f"", "status": "starting answer generation"}

        probable_prompt_length = get_probable_prompt_length(query["messageText"], web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer, partial_answer_text)
        logger.info(f"previous_messages long: {(len(previous_messages_long.split()))}, previous_messages_very_long: {(len(previous_messages_very_long.split()))}, previous_messages: {len(previous_messages.split())}, previous_messages short: {len(previous_messages_short.split())}")

        if probable_prompt_length < 90000 and (model_name is None or not model_name.startswith("mistralai")):
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_96k
        elif probable_prompt_length < 48000 and (model_name is None or not model_name.startswith("mistralai")):
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_64k
        elif probable_prompt_length < 28000 and (model_name is None or not model_name.startswith("mistralai")):
            previous_messages = previous_messages_long
            truncate_text = truncate_text_for_gpt4_32k
        else:
            previous_messages = previous_messages_short
            truncate_text = truncate_text_for_gpt4_16k

        link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_text(
            link_result_text, web_text, doc_answer, summary_text, previous_messages,
            query["messageText"], conversation_docs_answer)
        web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer = format_llm_inputs(
            web_text, doc_answer, link_result_text, summary_text, previous_messages,
            conversation_docs_answer)
        time_logger.info(
            f"Time to wait before preparing prompt: {(time.time() - wt_prior_ctx):.2f} and from start time to wait = {(time.time() - st):.2f}")
        yield {"text": '', "status": "Preparing prompt ..."}
        permanent_instructions = ("Follow the below instructions given by the user.\n" + checkboxes["permanentText"] + "\n") if "permanentText" in checkboxes and len(checkboxes["permanentText"].strip()) > 0 else ""
        prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text,
                                                       previous_messages=previous_messages,
                                                       permanent_instructions=permanent_instructions + partial_answer_text,
                                                       doc_answer=doc_answer, web_text=web_text,
                                                       link_result_text=link_result_text,
                                                       conversation_docs_answer=conversation_docs_answer)

        prompt = remove_bad_whitespaces_easy(prompt)
        time_logger.info(
            f"Time to wait till after preparing prompt: {(time.time() - wt_prior_ctx):.2f} and from start time to wait = {(time.time() - st):.2f}")
        # Lets log all things that went into making the prompt.
        # logger.info(f"query: {query['messageText']}")
        # logger.info(f"summary_text: {summary_text}")
        # logger.info(f"previous_messages: {previous_messages}")
        # logger.info(f"permanent_instructions: {permanent_instructions}")
        # logger.info(f"doc_answer: {doc_answer}")
        # logger.info(f"web_text: {web_text}")
        # logger.info(f"link_result_text: {link_result_text}")
        # logger.info(f"conversation_docs_answer: {conversation_docs_answer}")
        # logger.info(f"Prompt length: {len(enc.encode(prompt))}, prompt - ```\n{prompt}\n```")
        llm = CallLLm(self.get_api_keys(), model_name=model_name, use_gpt4=True, use_16k=True)
        main_ans_gen = llm(prompt, system=preamble, temperature=0.3, stream=True)
        t2y = next(main_ans_gen)
        # next_token_future = get_async_future(lambda: next(main_ans_gen))
        # wt_prior_ctx = time.time()
        # init_one = False
        # init_two = False
        # while time.time() - wt_prior_ctx < 45:
        #     # check if next is available on main_ans_gen and can give a response.
        #     if next_token_future.done() and next_token_future.exception() is None:
        #         t2y = next_token_future.result()
        #         break
        #     elif time.time() - wt_prior_ctx > 15 and not init_one:
        #         init_one = True
        #         llm = CallLLm(self.get_api_keys(), use_gpt4=True, use_16k=True)
        #         main_ans_gen = llm(prompt, system=preamble, temperature=0.3, stream=True)
        #         next_token_future = get_async_future(lambda: next(main_ans_gen))
        #     elif time.time() - wt_prior_ctx > 30 and not init_two:
        #         init_two = True
        #         llm = CallLLm(self.get_api_keys(), use_gpt4=True, use_16k=True)
        #         main_ans_gen = llm(prompt, system=preamble, temperature=0.3, stream=True)
        #         next_token_future = get_async_future(lambda: next(main_ans_gen))
        #     elif time.time() - wt_prior_ctx > 40:
        #         logger.error(f"[main_ans_gen] Could not get next token from [main_ans_gen] for model {model_name} in 45 seconds.")
        #         yield {"text": f"Could not get next token from [main_ans_gen] for model {model_name} in 45 seconds.", "status": f"Could not get next token from [main_ans_gen] for model {model_name} in 45 seconds."}
        #         break
        #
        #     time.sleep(0.5)


        yield {"text": t2y, "status": "answering in progress"}
        answer += t2y
        logger.info(
            f"""Starting to reply for chatbot, prompt length: {len(enc.encode(prompt))}, llm extracted prior chat info len: {len(enc.encode(prior_chat_summary))}, summary text length: {len(enc.encode(summary_text))}, 
        last few messages length: {len(enc.encode(previous_messages))}, doc answer length: {len(enc.encode(doc_answer))}, 
        conversation_docs_answer length: {len(enc.encode(conversation_docs_answer))},  
        web text length: {len(enc.encode(web_text))}, 
        link result text length: {len(enc.encode(link_result_text))}, 
        final prompt len: {len(enc.encode(prompt))}""")
        et = time.time()
        time_logger.info(f"Time taken to start replying for chatbot: {(et - st):.2f}")
        time_dict["start_reply_final"] = time.time() - st
        if len(doc_answer) > 0:
            logger.debug(f"Doc Answer: {doc_answer}")
        if len(web_text) > 0:
            logger.debug(f"Web text: {web_text}")
        answer += "<answer>\n"
        yield {"text": "<answer>\n", "status": "stage 2 answering in progress"}
        for txt in main_ans_gen:
            yield {"text": txt, "status": "answering in progress"}
            answer += txt
        answer += "</answer>\n"
        yield {"text": "</answer>\n", "status": "answering ended ..."}
        time_logger.info(f"Time taken to reply for chatbot: {(time.time() - et):.2f}, total time: {(time.time() - st):.2f}")
        time_dict["total_time_to_reply"] = time.time() - st
        time_dict["bot_time_to_reply"] = time.time() - et
        answer = answer.replace(prompt, "")
        yield {"text": '', "status": "saving answer ..."}
        if perform_web_search or google_scholar:
            search_results = next(web_results.result()[0].result())
            yield {"text": '', "status": "Showing all results ... "}
            if search_results["type"] == "end":
                full_results = search_results["full_results"]
                atext = "\n**All Search Results:** <div data-toggle='collapse' href='#allSearchResults' role='button'></div> <div class='collapse' id='allSearchResults'>" + "\n"
                answer += atext
                yield {"text": atext, "status": "displaying web search results ... "}
                query_results = [f"<a href='{qr['link']}'>{qr['title']} [{qr['count']}]</a>" for qr in full_results]
                message_config["web_search_links_all"] = full_results
                message_config["web_search_links_unread"] = sorted([qr for qr in full_results if qr["link"] not in message_config["web_search_links_read"]], key=lambda x: x["count"], reverse=True)
                query_results = two_column_list(query_results)
                answer += (query_results + "</div>")
                yield {"text": query_results + "</div>", "status": "Showing all results ... "}
        yield {"text": '', "status": "saving message ..."}
        get_async_future(self.persist_current_turn, original_user_query, answer, message_config, full_doc_texts)
        message_ids = self.get_message_ids(query["messageText"], answer)
        yield {"text": str(time_dict), "status": "saving answer ...", "message_ids": message_ids}

    
    def detect_previous_message_type(self):
        pass

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
    web_text = f"""\nRelevant information from other documents with url links, titles and useful document context are mentioned below:\n\n'''{web_text}'''
    Remember to refer to all the documents provided above in markdown format (like `[title](link) information from document`).\n""" if len(
        web_text.strip()) > 0 else ""
    doc_answer = f"""\nResults from user provided documents are given below. Questions user has asked usually pertain to these documents. Relevant information from user given documents with url links, titles and useful context are mentioned below:\n\n'''{doc_answer}'''\n""" if len(
        doc_answer.strip()) > 0 else ""
    link_result_text = f"""\nResults from user provided links are given below. Questions user has asked usually pertain to these links. Relevant information from user given links with url links, titles and useful context are mentioned below:\n\n'''{link_result_text}'''\n""" if len(
        link_result_text.strip()) > 0 else ""
    summary_text = f"""\nThe summary of the conversation is as follows:\n'''{summary_text}'''\n""" if len(summary_text.strip()) > 0 else ''
    previous_messages = f"""\nPrevious chat history between user and assistant:\n'''{previous_messages}'''\n""" if len(previous_messages.strip()) > 0 else ''
    conversation_docs_answer = f"""\nThe documents that were read are as follows:\n'''{conversation_docs_answer}'''\n""" if len(conversation_docs_answer) > 0 else ''
    return web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer


def get_probable_prompt_length(messageText, web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer, partial_answer_text):
    text = " ".join([remove_bad_whitespaces_easy(x) for x in [messageText, web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer, partial_answer_text]])
    return int(1.25 * len(text.split()))
    # link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_text_for_gpt4_96k(
    #     link_result_text, web_text, doc_answer, summary_text, previous_messages,
    #     messageText, conversation_docs_answer)
    # web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer = format_llm_inputs(
    #     web_text, doc_answer, link_result_text, summary_text, previous_messages,
    #     conversation_docs_answer)
    # prompt = prompts.chat_slow_reply_prompt.format(query=messageText,
    #                                                summary_text=summary_text,
    #                                                previous_messages=previous_messages,
    #                                                permanent_instructions="You are an expert in literature, psychology, history and philosophy. Answer the query in a way that is understandable to a layman. Answer quickly and briefly. Write your reasoning and approach in short before writing your answer.\n\n" + str(partial_answer_text),
    #                                                doc_answer=doc_answer, web_text=web_text,
    #                                                link_result_text=link_result_text,
    #                                                conversation_docs_answer=conversation_docs_answer)
    # return len(enc.encode(prompt))


def truncate_text_for_gpt3(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-3.5-turbo")

def truncate_text_for_gpt4(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4")

def truncate_text_for_gpt4_16k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-16k")

def truncate_text_for_gpt4_32k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-32k")

def truncate_text_for_gpt4_64k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-64k")


def truncate_text_for_gpt4_96k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-96k")

def truncate_text_for_gpt3_16k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-3.5-turbo-16k")

def truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4"):
    enc = tiktoken.encoding_for_model(model)
    if model == "gpt-4":
        l1 = 7000
        l2 = 1000
        l4 = 1250
    elif model == "gpt-4-16k":
        l1 = 10000
        l2 = 2000
        l4 = 2500
    elif model == "gpt-3.5-turbo-16k":
        l1 = 10000
        l2 = 2000
        l4 = 2500
    elif model == "gpt-4-32k":
        l1 = 20000
        l2 = 8000
        l4 = 5000
    elif model == "gpt-4-64k":
        l1 = 32000
        l2 = 16000
        l4 = 10000
    elif model == "gpt-4-96k":
        l1 = 60000
        l2 = 20000
        l4 = 10000
    else:
        l1 = 2000
        l2 = 500
        l4 = 500

    message_space = max(l2, l1 - len(enc.encode(user_message + conversation_docs_answer + link_result_text + doc_answer + web_text + summary_text)) - 750)
    previous_messages = get_first_last_parts(previous_messages, 0, message_space)
    summary_space = max(l4, l1 - len(enc.encode(user_message + previous_messages + conversation_docs_answer + link_result_text + doc_answer + web_text)) - 750)
    summary_text = get_first_last_parts(summary_text, 0, summary_space)
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
        return '\n'.join(answers).strip()
    else:
        # If no <answer> tags are found, return the entire text
        return text.strip()
