import secrets
import inspect
import types
import collections.abc  
import shutil

import yaml
from agents.search_and_information_agents import JinaSearchAgent
from call_llm import MockCallLLm
from prompts import tts_friendly_format_instructions, improve_code_prompt, improve_code_prompt_interviews, short_coding_interview_prompt, more_related_questions_prompt, relationship_prompt, dating_maverick_prompt
from filelock import FileLock

from agents import LiteratureReviewAgent, NResponseAgent, ReflectionAgent, StreamingTTSAgent, TTSAgent, WebSearchWithAgent, BroadSearchAgent, PerplexitySearchAgent, WhatIfAgent, InterviewSimulatorAgent, InterviewSimulatorAgentV2
from agents import PodcastAgent, StreamingPodcastAgent, BookCreatorAgent, ToCGenerationAgent, NStepCodeAgent, MLSystemDesignAgent, MultiSourceSearchAgent, CodeSolveAgent
from code_runner import code_runner_with_retry, extract_all_mermaid, extract_code, extract_drawio, extract_last_mermaid, extract_mermaid, \
    PersistentPythonEnvironment, PersistentPythonEnvironment_v2

from prompts import *


from pathlib import Path
from base import *


pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.ERROR, logging.INFO, logging.ERROR, logging.INFO)
import time
import traceback
from DocIndex import DocIndex, DocFAISS, create_immediate_document_index, create_index_faiss, ImageDocIndex



import string
import tiktoken
import json
alphabet = string.ascii_letters + string.digits


class Conversation:
    def __init__(self, user_id, openai_embed, storage, conversation_id, domain=None) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        self._next_question_suggestions = list()
        folder = os.path.join(storage, f"{self.conversation_id}")
        self._storage = folder
        os.makedirs(folder, exist_ok=True)
        self._stateless = False
        memory = {  "title": 'Start the Conversation',
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "running_summary":[], # List of strings, each string is a running summary of chat till now.
                    "title_force_set": False,
                }
        messages = list() # list of message objects of structure like `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"},`
        self.set_field("memory", memory)
        self.set_messages_field(messages)
        self.set_field("uploaded_documents_list", list()) # just a List[str] of doc index ids
        self._domain = domain
        
        # Initialize persistent context data for reward system
        self._context_data = {
            "current_score": 0,
            "recent_achievements": [],
            "problem_difficulty": "medium",
            "total_rewards": 0,
            "total_penalties": 0,
            "session_start_time": time.time(),
            "last_reward_timestamp": None,
            "reward_history": []
        }
        
        self.save_local()


    def set_memory_if_None(self):
        if self.get_field("memory") is None:
            self.set_field("memory", {"title": 'Start the Conversation',
                                      "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      "running_summary": []})

    @property
    def next_question_suggestions(self):
        if hasattr(self, "_next_question_suggestions"):
            return self._next_question_suggestions
        return []

    @next_question_suggestions.setter
    def next_question_suggestions(self, value):
        if hasattr(self, "_next_question_suggestions"):
            self._next_question_suggestions = value
        else:
            setattr(self, "_next_question_suggestions", value)
        self.save_local()
    
    @property
    def memory_pad(self):
        if hasattr(self, "_memory_pad"):
            return self._memory_pad
        return ''

    @memory_pad.setter
    def memory_pad(self, value):
        if hasattr(self, "_memory_pad"):
            self._memory_pad = value
        else:
            setattr(self, "_memory_pad", value)
        self.save_local()

    def set_memory_pad(self, value):
        self.memory_pad = value

    def add_to_memory_pad_from_response(self, queryText, responseText, previous_messages, conversation_summary):
        # We will only add facts from the query and response text, nothing else. To determine facts we use an LLM.
        prompt = f"""You are given a user query and a system response from a conversation. You will extract important facts, numbers, metrics from the user query and system response. You will write in a compact manner using bullet points.

Previous messages: '''{previous_messages}'''

Conversation Summary: '''{conversation_summary}'''

Older memory: '''{self.memory_pad}'''

User query: '''{queryText}'''

Response: '''{responseText}'''

Only add new details, facts, numbers, metrics, short summarised code, from the user query and system response that the older memory does not have in a compact and brief manner while capturing all information.
Also extract user preference and behavior and goals, and any other information that will be useful to the user later.
Refrain from adding any information that is already present in the older memory.
Extract only new important details, facts, numbers, metrics from the user query and system response that older memory does not possess. Only write the extracted information in simple bullet points.
Write the new extracted information below in bullet points.

## New Information:

"""
        llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=False) # google/gemini-flash-1.5 # cohere/command-r-plus openai/gpt-3.5-turbo-0125 mistralai/mixtral-8x22b-instruct
        new_memory = llm(prompt, temperature=0.2, stream=False)
        new_memory = re.sub(r'\n+', '\n', new_memory)
        self.memory_pad += ("\n" + new_memory)
        # remove double \n
        memory_parts = self.memory_pad.split("\n")

        if len(self.memory_pad.split()) > 12000 and len(memory_parts) > 128:
            # split menmory pad into 8 equal parts using \n separator and then merging them back

            part_size = len(memory_parts)//8
            memory_parts = [memory_parts[i: part_size * (i//part_size + 1)] for i in range(0, len(memory_parts), part_size)]
            memory_parts = ["\n".join(mp) for mp in memory_parts]
            shorten_prompt = """You are given important factual information from two sources in the form of bullet points. You will now merge the two sources of information into a single compact list of bullet points.
The information is as follows:
First source of information:
{}

Second source of information:
{}

Now merge the two sources of information into a single compact list of bullet points. Merge any similar information and also remove any redundant information. Write compactly and in a brief manner while capturing all information.
Compact list of bullet points:
"""

            memory_parts_futures = []
            for i in range(0, len(memory_parts), 2):
                llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=False)
                if i + 1 < len(memory_parts):
                    memory_parts_futures.append(get_async_future(llm, shorten_prompt.format(memory_parts[i], memory_parts[i+1]), temperature=0.2, stream=False))
                else:
                    memory_parts_futures.append(get_async_future(llm, shorten_prompt.format(memory_parts[i], ""), temperature=0.2, stream=False))

            memory_parts = [sleep_and_get_future_result(mp) for mp in memory_parts_futures]
            memory_pad = "\n".join(memory_parts)
            memory_pad = re.sub(r'\n+', '\n', memory_pad)
            self.memory_pad = memory_pad
        time_logger.info(f"Memory pad updated with new memory , with length = {len(self.memory_pad.split())}")
        return self.memory_pad

    @property
    def domain(self):
        if hasattr(self, "_domain") and self._domain is not None:
            return self._domain
        return "assistant"

    @domain.setter
    def domain(self, value):
        if hasattr(self, "_domain"):
            self._domain = value
        else:
            setattr(self, "_domain", value)
        self.save_local()

    @property
    def context_data(self):
        """Get the persistent context data for reward system"""
        if hasattr(self, "_context_data"):
            return self._context_data
        # Initialize if not present (for backward compatibility)
        self._context_data = {
            "current_score": 0,
            "recent_achievements": [],
            "problem_difficulty": "medium",
            "total_rewards": 0,
            "total_penalties": 0,
            "session_start_time": time.time(),
            "last_reward_timestamp": None,
            "reward_history": []
        }
        return self._context_data

    @context_data.setter
    def context_data(self, value):
        """Set the persistent context data for reward system"""
        if isinstance(value, dict):
            self._context_data = value
        else:
            raise ValueError("context_data must be a dictionary")

    def update_context_data(self, updates):
        """Update specific fields in context_data"""
        if isinstance(updates, dict):
            self.context_data.update(updates)
        else:
            raise ValueError("updates must be a dictionary")

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

    @property
    def running_summary(self):
        if hasattr(self, "_running_summary"):
            return self._running_summary
        self.set_memory_if_None()
        if len(self.get_field("memory")["running_summary"]) == 0:
            return ""
        running_summary = "".join(self.get_field("memory")["running_summary"][-1:])
        setattr(self, "_running_summary", running_summary)
        return running_summary

    @running_summary.setter
    def running_summary(self, value):
        if hasattr(self, "_running_summary"):
            self._running_summary = value
        else:
            setattr(self, "_running_summary", value)
        self.save_local()

    @property
    def documents_path(self):
        storage = os.path.join(self._storage, "uploaded_documents")
        os.makedirs(storage, exist_ok=True)
        return storage

    @property
    def doc_infos(self) -> str:
        if hasattr(self, "_doc_infos"):
            return self._doc_infos
        return ""

    @doc_infos.setter
    def doc_infos(self, value: str):
        if hasattr(self, "_doc_infos"):
            self._doc_infos = value
        else:
            setattr(self, "_doc_infos", value)
        self.save_local()

    def add_uploaded_document(self, pdf_url):
        # TODO: check file md5 hash to see if it is already uploaded
        storage = self.documents_path
        keys = self.get_api_keys()
        keys["mathpixKey"] = None
        keys["mathpixId"] = None
        previous_docs = self.get_field("uploaded_documents_list")
        previous_docs = previous_docs if previous_docs is not None else []
        # deduplicate on basis of doc_id
        previous_docs = [d for i, d in enumerate(previous_docs) if d[0] not in [d[0] for d in previous_docs[:i]]]
        pdf_urls = [d[2] for d in previous_docs]
        if pdf_url in pdf_urls:
            return None
        current_documents: List[DocIndex] = self.get_uploaded_documents()
        current_sources = [d.doc_source for d in current_documents]
        if pdf_url in current_sources:
            return None
        doc_index: DocIndex = create_immediate_document_index(pdf_url, storage, keys)
        doc_index._visible = False
        doc_index.save_local()
        doc_id = doc_index.doc_id
        doc_storage = doc_index._storage
        all_docs = previous_docs + [(doc_id, doc_storage, pdf_url)]

        attached_docs: List[int] = list(range(1, len(current_documents) + 1))
        attached_docs: List[DocIndex] = [current_documents[d - 1] for d in attached_docs]
        attached_docs.append(doc_index)
        doc_infos = "\n".join([f"#doc_{i+1}: ({d.title})[{d.doc_source}]" for i, d in enumerate(attached_docs)])
        self.doc_infos = doc_infos
        self.set_field("uploaded_documents_list", all_docs, overwrite=True)

    def get_uploaded_documents(self, doc_id=None, readonly=False)->List[DocIndex]:
        try:
            doc_list = self.get_field("uploaded_documents_list")
        except ValueError as e:
            doc_list = None
            self.set_field("uploaded_documents_list", [])
        if doc_list is not None:
            docs = [DocIndex.load_local(doc_storage) for doc_id, doc_storage, pdf_url in doc_list]
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
        all_docs = [d for d in self.get_field("uploaded_documents_list") if d[0] != doc_id]
        self.set_field("uploaded_documents_list", all_docs, overwrite=True)
        current_documents: List[DocIndex] = self.get_uploaded_documents()
        attached_docs: List[int] = list(range(1, len(current_documents) + 1))
        attached_docs: List[DocIndex] = [current_documents[d - 1] for d in attached_docs]
        doc_infos = "\n".join([f"#doc_{i + 1}: ({d.title})[{d.doc_source}]" for i, d in enumerate(attached_docs)])
        self.doc_infos = doc_infos


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
            traceback.print_exc()
            try:
                shutil.rmtree(original_folder)
            except Exception as e:
                logger.error(
                    f"Error deleting local storage {folder} with error {e}")
            return None
    
    def clone_conversation(self):
        # Create new storage path for clone
        uuid = ''.join(secrets.choice(alphabet) for i in range(6))
        new_conversation_id = f"{self.conversation_id}_clone_{uuid}"
        # get parent directory of self._storage
        parent_dir = os.path.dirname(self._storage)
        new_storage = os.path.join(parent_dir, new_conversation_id)
        os.makedirs(new_storage, exist_ok=True)
        
        # Create new conversation with correct parameters
        new_conversation = Conversation(
            user_id=self.user_id,
            openai_embed=None,  # Will be set via set_api_keys
            storage=parent_dir,
            conversation_id=new_conversation_id,
            domain=self.domain
        )
        
        # Set API keys
        new_conversation.set_api_keys(self.get_api_keys())
        
        # Properties with getters/setters
        new_conversation.domain = self.domain
        new_conversation.stateless = self.stateless
        new_conversation.doc_infos = self.doc_infos
        new_conversation.running_summary = self.running_summary
        new_conversation.memory_pad = self.memory_pad if hasattr(self, '_memory_pad') else ''
        
        # Clone uploaded documents
        uploaded_docs = self.get_field("uploaded_documents_list") or []
        new_docs_path = os.path.join(new_storage, "uploaded_documents")
        os.makedirs(new_docs_path, exist_ok=True)
        if uploaded_docs:
            # Copy document files to new storage
            for doc_id, doc_storage, pdf_url in uploaded_docs:
                if os.path.exists(doc_storage):
                    new_doc_storage = os.path.join(new_docs_path, os.path.basename(doc_storage))
                    shutil.copytree(doc_storage, new_doc_storage, dirs_exist_ok=True)
        new_conversation.set_field("uploaded_documents_list", uploaded_docs)
        
        # Clone other fields
        fields_to_clone = [
            "memory",
            "messages",
        ]
        
        for field in fields_to_clone:
            value = self.get_field(field)
            if value is not None:
                new_conversation.set_field(field, value)
                    
        new_conversation.save_local()
        logger.info(f"Cloned conversation {self.conversation_id} to {new_conversation.conversation_id}, Parent directory = {parent_dir}, new location = {new_storage} from old location {self._storage}")
        # list contents of new_storage
        def print_tree(path, prefix=""):
            contents = []
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    contents.append(f"{prefix}├── {item}/")
                    contents.extend(print_tree(item_path, prefix + "│   "))
                else:
                    contents.append(f"{prefix}├── {item}")
            return contents
            
        tree = print_tree(new_storage)
        logger.info(f"Contents of {new_storage}:\n" + "\n".join(tree))
        logger.info(f"Contents of Old Storage {self._storage}:\n" + "\n".join(print_tree(self._storage)))

        return new_conversation
    
    
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
            raise GenericShortException(f"Invalid top_key {top_key} provided")
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

    def set_messages_field(self, messages, overwrite=False):
        self.set_field("messages", messages, overwrite=overwrite)


    @timer
    def retrieve_prior_context(self, query, past_message_ids=[], required_message_lookback=12):
        # Lets get the previous 2 messages, upto 1000 tokens
        st = time.time()
        token_limit_very_short = 8000
        token_limit_short = 12_000
        token_limit_long = 25_000
        token_limit_very_long = 55_000
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages")]
        memory, messages = [sleep_and_get_future_result(f) for f in futures]
        message_lookback = 2
        previous_messages_text = ""
        if len(past_message_ids) > 0:
            messages = [m for m in messages if m["message_id"] in past_message_ids]
            required_message_lookback = 12
        word_count = 0
        previous_messages_very_short = previous_messages_short = previous_messages_long = previous_messages_very_long = ''
        while word_count < token_limit_very_long and message_lookback <= required_message_lookback and required_message_lookback > 0:
            previous_messages = messages[-message_lookback:]
            previous_messages = [{"sender": m["sender"], "text": extract_user_answer(m["text"])} for m in previous_messages]
            previous_messages_text = '\n\n'.join([f"<{m['sender']}>\n{m['text']}\n</{m['sender']}>" for m in previous_messages])
            word_count = get_gpt4_word_count(previous_messages_text)
            if word_count < token_limit_very_short:
                previous_messages_very_short = previous_messages_text
            if word_count < token_limit_short:
                previous_messages_short = previous_messages_text
            if word_count < token_limit_long:
                previous_messages_long = previous_messages_text
            if word_count < token_limit_very_long:
                previous_messages_very_long = previous_messages_text
            message_lookback += 2

        running_summary = self.running_summary
        # older_extensive_summary = find_nearest_divisible_by_three(memory["running_summary"])
        # if len(running_summary) > 0 and running_summary[0] != older_extensive_summary:
        #     running_summary = [older_extensive_summary] + running_summary

        # We return a dict
        previous_messages_short = "<messages>\n" + previous_messages_short + "\n</messages>"
        previous_messages_long = "<messages>\n" + previous_messages_long + "\n</messages>"
        previous_messages_very_long = "<messages>\n" + previous_messages_very_long + "\n</messages>"
        previous_messages_very_short = "<messages>\n" + previous_messages_very_short + "\n</messages>"
        results = dict(previous_messages=previous_messages_short,
                       previous_messages_long=previous_messages_long,
                       previous_messages_very_long=previous_messages_very_long,
                       previous_messages_very_short=previous_messages_very_short,
                       summary=running_summary)
        # lets log the length of each of the above in a single log statement
        time_spend = time.time() - st
        logger.info(f"Length of previous_messages_short = {get_gpt4_word_count(previous_messages_short)}, previous_messages_long = {get_gpt4_word_count(previous_messages_long)}, previous_messages_very_long = {get_gpt4_word_count(previous_messages_very_long)}")
        time_logger.info(f"Time taken to retrieve prior context = {time_spend} seconds")
        return results

    def get_conversation_history(self, query=""):
        """Generate a comprehensive conversation history combining summary and recent messages"""
        try:
            # Get prior context and running summary
            context_data = self.retrieve_prior_context(query, required_message_lookback=20)
            running_summary = self.running_summary
            
            # Build comprehensive conversation history
            history_text = ""
            
            # Add conversation summary if available
            if running_summary and len(running_summary) > 0:
                if isinstance(running_summary, list):
                    summary_text = "\n".join(running_summary)
                else:
                    summary_text = str(running_summary)
                
                history_text += "# Conversation Summary\n\n"
                history_text += summary_text + "\n\n"
            
            # Add recent messages
            previous_messages_long = context_data.get("previous_messages_long", "")
            if previous_messages_long and previous_messages_long.strip() != "<messages>\n\n</messages>":
                history_text += "# Recent Messages\n\n"
                # Clean up the messages format for better readability
                clean_messages = previous_messages_long.replace("<messages>\n", "").replace("\n</messages>", "")
                if clean_messages.strip():
                    history_text += clean_messages + "\n\n"
            
            # Add metadata
            messages = self.get_field("messages")
            if messages:
                history_text += f"# Conversation Metadata\n\n"
                history_text += f"- **Total Messages:** {len(messages)}\n"
                history_text += f"- **Conversation ID:** {self.conversation_id}\n"
                history_text += f"- **Domain:** {self.domain}\n"
                
                # Add last message timestamp if available
                if messages:
                    last_message = messages[-1]
                    if "timestamp" in last_message:
                        history_text += f"- **Last Updated:** {last_message['timestamp']}\n"
            
            # If no content, provide a default message
            if not history_text.strip():
                history_text = "# Conversation History\n\nThis conversation is just getting started. No previous messages or summary available yet."
            
            return history_text
            
        except Exception as e:
            logger.error(f"Error generating conversation history: {str(e)}")
            return f"# Conversation History\n\nUnable to retrieve conversation history due to an error: {str(e)}"


    def get_message_ids(self, query, response):
        user_message_id = str(mmh3.hash(self.conversation_id + self.user_id + query["messageText"] if isinstance(query, dict) else query, signed=False))
        response_message_id = str(mmh3.hash(self.conversation_id + self.user_id + response["messageText"] if isinstance(response, dict) else response, signed=False))
        return dict(user_message_id=user_message_id, response_message_id=response_message_id)

    def show_hide_message(self, message_id, index, show_hide):
        # Add lock acquisition at the beginning
        lock_location = self._get_lock_location("message_operations")
        lock = FileLock(f"{lock_location}.lock")
        
        with lock.acquire(timeout=600):
            messages = self.get_field("messages")
            for i, m in enumerate(messages):
                if m["message_id"] == message_id:
                    messages[i]["show_hide"] = show_hide
                    break
            self.set_messages_field(messages, overwrite=True)
            self.save_local()
    
    
    def create_next_question_suggestions(self, query, response, previous_messages_text, previous_summary):
        system = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
You will write a list of next question/response suggestions that the human can ask to the AI after the current user query and system response to continue the conversation.
The next question/response suggestions should be in the form of a list of questions and the questions should be short and concise.

The next question/response suggestions can either be a question or a response that the user can tap on in the chat interface to continue the conversation.

Your response will be in below xml style format:
<next_question_suggestions>
    <suggestion>question/response suggestion 1</suggestion>
    <suggestion>question/response suggestion 2</suggestion>
    <suggestion>question/response suggestion 3</suggestion>
    ...
</next_question_suggestions>

Give 4 suggestions.
"""

        next_question_suggestions_prompt = prompts.next_question_suggestions_prompt.format(query=query, response=extract_user_answer(response), previous_messages_text=previous_messages_text, summary=previous_summary)
        llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=True)
        next_question_suggestions = llm(next_question_suggestions_prompt, system=system, temperature=0.2, stream=False)
        # Parse the next_question_suggestions to extract individual suggestions
        import re
        suggestions = []
        suggestion_pattern = r'<suggestion>(.*?)</suggestion>'
        matches = re.findall(suggestion_pattern, next_question_suggestions)
        if matches:
            suggestions = matches
        else:
            # Fallback in case the XML format wasn't followed
            suggestions = ["Tell me more", "Can you explain further?", "What's next?"]
        return suggestions
    
    @timer
    def persist_current_turn(self, query, response, config, previous_messages_text, previous_summary, new_docs, persist_or_not=True, past_message_ids=None):
        self.clear_cancellation()
        if not persist_or_not:
            return
        # message format = `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"}`
        # set the two messages in the message list as per above format.

        # Add lock acquisition at the beginning
        lock_location = self._get_lock_location("message_operations")
        lock = FileLock(f"{lock_location}.lock")

        prompt = prompts.persist_current_turn_prompt.format(query=query, response=extract_user_answer(response), previous_messages_text=previous_messages_text, previous_summary=previous_summary)
        llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=True)
        prompt = get_first_last_parts(prompt, 18000, 10_000)
        system = f"""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
You will write a new summary for this conversation which takes the last 2 recent messages into account. 
You will also write a very short title for this conversation.

Your response will be in below xml style format:
<summary> {{Detailed Conversation Summary with salient, important and noteworthy aspects and details.}} </summary>
<title> {{Very short title for the conversation}} </title>
"""
        summary = get_async_future(llm, prompt, system=system, temperature=0.2, stream=False)
        next_question_suggestions = get_async_future(self.create_next_question_suggestions, query, response, previous_messages_text, previous_summary)

        
        with lock.acquire(timeout=600):
            memory = get_async_future(self.get_field, "memory")
            memory_pad = get_async_future(self.add_to_memory_pad_from_response, query, response, previous_messages_text, previous_summary)
            message_ids = self.get_message_ids(query, response)
            preserved_messages = [
                {"message_id": message_ids["user_message_id"], "text": query, "show_hide": "show",
                "sender": "user", "user_id": self.user_id, "conversation_id": self.conversation_id},
                {"message_id": message_ids["response_message_id"], "text": response, "show_hide": "show", "sender": "model", "user_id": self.user_id, "conversation_id": self.conversation_id, "config": config}]
            
            if past_message_ids and len(past_message_ids) > 0 and config["render_close_to_source"]:
                messages = get_async_future(self.get_field, "messages")
            else:
                msg_set = get_async_future(self.set_messages_field, preserved_messages)

            
            memory = memory.result()
            if memory is None:
                memory = dict(running_summary=[])

            if past_message_ids and len(past_message_ids) > 0 and config["render_close_to_source"]:
                messages = messages.result()
                # Find index of last message in past_message_ids
                last_msg_idx = -1
                for i, msg in enumerate(messages):
                    if msg["message_id"] == past_message_ids[-1]:
                        last_msg_idx = i
                        break
                        
                # Split messages into before and after groups
                messages_before = messages[:last_msg_idx+1] 
                messages_after = messages[last_msg_idx+1:]
                
                # Insert new messages between the groups
                messages = messages_before + preserved_messages + messages_after
                
                # Update messages in storage
                msg_set = get_async_future(self.set_messages_field, messages, overwrite=True)
                

            memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            summary = sleep_and_get_future_result(summary)
            next_question_suggestions = sleep_and_get_future_result(next_question_suggestions)
            
            self.set_next_question_suggestions(next_question_suggestions)

            actual_summary = summary.split('</summary>')[0].split('<summary>')[-1]
            title = summary.split('</title>')[0].split('<title>')[-1]
            
            memory["title_force_set"] = False or memory.get("title_force_set", False)
            if not memory["title_force_set"] and (past_message_ids is None or len(past_message_ids) == 0):
                memory["title"] = title

            if past_message_ids and len(past_message_ids) > 0 and config["render_close_to_source"]:
                summary_index = (last_msg_idx+1)//2
                # list.insert() increases the length of the list by 1
                # If index > len(list), insert() will append the item at the end (equivalent to index=len(list))
                # So we should ensure summary_index is within bounds
                summary_index = min(summary_index, len(memory["running_summary"]))
                memory["running_summary"].insert(summary_index, actual_summary)
            else:
                self.running_summary = actual_summary
                memory["running_summary"].append(actual_summary)
            self.set_field("memory", memory)
            # self.set_field("memory", memory)
            self.save_local()
            msg_set.result()
            memory_pad.result()

    def set_title(self, title):
        memory = self.get_field("memory")
        memory["title"] = title
        self.set_field("memory", memory)
        memory["title_force_set"] = True
        self.save_local()
        
    def convert_to_tts(self, text, message_id, message_index, recompute=False, shortTTS=False):
        """
        Convert text to speech using TTSAgent, with support for both short and normal TTS versions.
        
        This method:
        1. Creates an audio messages directory if it doesn't exist.
        2. Resolves the message_id if it is missing or invalid by falling back to the last message in the conversation.
        3. Determines the correct filename based on whether shortTTS is True or False:
            - If shortTTS=True, uses "{message_id}_short.mp3"
            - Otherwise, uses "{message_id}.mp3"
        4. Checks if the mp3 file already exists (and recompute=False). If so, returns its path (cached). 
        5. Otherwise, initializes the TTSAgent (passing shortTTS as a named parameter) and generates the audio file.
        6. Returns the path to the generated audio file.

        Args:
            text (str): Text to convert to speech.
            message_id (str|None): Message ID for the text.
            message_index (int): Index of the message.
            recompute (bool, optional): If True, forces regeneration of the audio even if it exists. Defaults to False.
            shortTTS (bool, optional): Whether to generate a shorter TTS variant. 
                                    Affects naming and agent configuration. Defaults to False.
        
        Returns:
            str: Path to the generated (or cached) audio file, or None if an error occurred.
        """
        # Create audio messages directory
        audio_dir = os.path.join(self._storage, "audio_messages")
        os.makedirs(audio_dir, exist_ok=True)
        
        # If message_id is None or invalid, attempt fallback
        if not message_id or str(message_id) in ["None", "", "nan", "undefined"]:
            messages = self.get_field("messages")
            if messages:
                message_id = messages[-1].get("message_id")
                text = messages[-1].get("text")
        
        # If still no message_id, log and return
        if not message_id:
            logger.error(f"Could not determine message_id for index {message_index}")
            return None
        
        # Attempt to retrieve matching message text
        messages = self.get_field("messages")
        if messages:
            message = next((m for m in messages if m["message_id"] == message_id), None)
            if message:
                text = message.get("text", text)
        
        # Use distinct filename depending on shortTTS
        if shortTTS:
            filename = f"{message_id}_short.mp3"
        else:
            filename = f"{message_id}.mp3"
        
        audio_path = os.path.join(audio_dir, filename)
        
        # If audio file already exists and recompute=False, return its path
        if os.path.exists(audio_path) and not recompute:
            if audio_path.endswith(".mp3"):
                logger.info(f"Found existing audio file for message_id={message_id}, shortTTS={shortTTS}")
                return audio_path
            else:
                logger.info(f"Found existing audio file for message_id={message_id} but it is not an mp3 file")
                raise Exception(f"Found existing audio file for message_id={message_id} but it is not an mp3 file")
        
        # Attempt to generate TTS
        try:
            # Initialize TTSAgent with the specific output path and shortTTS flag
            tts_agent = TTSAgent(
                keys=self.get_api_keys(),
                storage_path=audio_path,
                convert_to_tts_friendly_format=True,
                shortTTS=shortTTS
            )
            
            # Convert text to audio and get the output path
            output_path = tts_agent(text)
            return output_path
        except Exception as e:
            logger.error(f"Error converting text to speech for message_id={message_id}, shortTTS={shortTTS}: {e}")
            return None


    def convert_to_audio_streaming(self, text, message_id, message_index, recompute=False, shortTTS=False, podcastTTS=False):
        if podcastTTS:
            return self.convert_to_podcast_streaming(text, message_id, message_index, recompute, shortTTS)
        else:
            return self.convert_to_tts_streaming(text, message_id, message_index, recompute, shortTTS)
    
    def convert_to_audio(self, text, message_id, message_index, recompute=False, shortTTS=False, podcastTTS=False):
        if podcastTTS:
            raise Exception("Podcast TTS is not supported yet")
        else:
            return self.convert_to_tts(text, message_id, message_index, recompute, shortTTS)
    
    def convert_to_tts_streaming(self, text, message_id, message_index, recompute=False, shortTTS=False):
        """
        Convert text to speech using StreamingTTSAgent with both streaming and file storage capabilities, 
        supporting distinct short/normal TTS versions.

        This method:
        1. Creates an audio messages directory if it doesn't exist (same as convert_to_tts).
        2. Resolves the message_id if it is missing or invalid by falling back to the last message.
        3. Determines the correct filename based on whether shortTTS is True or False:
            - If shortTTS=True, uses "{message_id}_short.mp3"
            - Otherwise, uses "{message_id}.mp3"
        4. If the file exists and recompute=False, streams it from the local file instead of regenerating audio.
        5. Otherwise, initializes the StreamingTTSAgent (passing shortTTS as a named parameter) to:
            - Stream audio chunks to the client.
            - Save the entire file as it streams for subsequent caching.
        6. Returns a generator that yields mp3 data chunks (bytes).

        Args:
            text (str): Text to convert to speech.
            message_id (str|None): Message ID for the text.
            message_index (int): Index of the message.
            recompute (bool, optional): If True, forces regeneration of the audio even if it exists. Defaults to False.
            shortTTS (bool, optional): Whether to generate a shorter TTS variant. 
                                    Affects naming and agent configuration. Defaults to False.

        Returns:
            generator: A generator that yields mp3 data chunks (bytes). An empty generator is returned if an error occurs.

        Note:
            - File caching logic is similar to convert_to_tts(), but audio is streamed in chunks.
        """
        # Create audio messages directory
        audio_dir = os.path.join(self._storage, "audio_messages")
        os.makedirs(audio_dir, exist_ok=True)

        # Resolve message_id if missing
        if not message_id or str(message_id) in ["None", "", "nan", "undefined"]:
            messages = self.get_field("messages")
            if messages:
                message_id = messages[-1].get("message_id")
                text = messages[-1].get("text")

        # If still no message_id, log and return empty generator
        if not message_id:
            logger.error(f"Could not determine message_id for index {message_index}")
            return (b"" for _ in range(0))  # empty generator

        # Retrieve relevant message text if available
        messages = self.get_field("messages")
        if messages:
            message = next((m for m in messages if m["message_id"] == message_id), None)
            if message:
                text = message.get("text", text)

        # Use distinct filename depending on shortTTS
        if shortTTS:
            filename = f"{message_id}_short.mp3"
        else:
            filename = f"{message_id}.mp3"

        audio_path = os.path.join(audio_dir, filename)

        try:
            # If file exists and recompute=False, stream it from local file
            if os.path.exists(audio_path) and not recompute:
                if audio_path.endswith(".mp3"):
                    logger.info(f"Streaming existing audio file for message_id={message_id}, shortTTS={shortTTS}")
                    with open(audio_path, 'rb') as f:
                        while chunk := f.read(8192):  # Stream in 8KB chunks
                            yield chunk
                    return
                else:
                    logger.info(f"Found existing audio file for message_id={message_id} but it is not an mp3 file")
                    raise Exception(f"Found existing audio file for message_id={message_id} but it is not an mp3 file")
            
            # Initialize StreamingTTSAgent with path and shortTTS
            tts_agent = StreamingTTSAgent(
                keys=self.get_api_keys(),
                storage_path=audio_path,
                convert_to_tts_friendly_format=True,
                shortTTS=shortTTS
            )
            
            # Stream the chunks to the client while saving to file
            audio_generator = tts_agent(text)
            for chunk in audio_generator:
                yield chunk

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error in streaming TTS conversion for message_id={message_id}, shortTTS={shortTTS}: {e}")
            # Return empty generator on failure
            def empty_gen():
                yield
            return empty_gen()
        
    
    def convert_to_podcast_streaming(self, text, message_id, message_index, recompute=False, shortTTS=False,
                                previous_message=None, conversation_summary=None):
        """
        Convert text to podcast-style audio using StreamingPodcastAgent with streaming capabilities.
        
        This method:
        1. Creates an audio messages directory if it doesn't exist
        2. Resolves the message_id if missing or invalid
        3. Formats the input to include brief context from previous message and conversation summary
        4. Uses a distinct filename format: "{message_id}_podcast.mp3"
        5. If the file exists and recompute=False, streams it from the local file
        6. Otherwise, initializes the StreamingPodcastAgent to:
        - Stream audio chunks to the client
        - Save the entire file as it streams for subsequent caching
        
        Args:
            text (str): Current message text to convert to podcast audio
            message_id (str|None): Message ID for the text
            message_index (int): Index of the message
            recompute (bool, optional): If True, forces regeneration of the audio even if it exists. Defaults to False.
            previous_message (str|None, optional): Text of the previous message for context. Defaults to None.
            conversation_summary (str|None, optional): Summary of the conversation for context. Defaults to None.
        
        Returns:
            generator: A generator that yields mp3 data chunks (bytes). An empty generator is returned if an error occurs.
        """
        # Create audio messages directory
        audio_dir = os.path.join(self._storage, "audio_messages")
        os.makedirs(audio_dir, exist_ok=True)
        
        # Resolve message_id if missing
        if not message_id or str(message_id) in ["None", "", "nan", "undefined"]:
            messages = self.get_field("messages")
            if messages:
                message_id = messages[-1].get("message_id")
                text = messages[-1].get("text")
        
        # If still no message_id, log and return empty generator
        if not message_id:
            logger.error(f"Could not determine message_id for index {message_index}")
            return (b"" for _ in range(0))  # empty generator
        
        # Retrieve relevant message text if available
        messages = self.get_field("messages")
        if messages:
            message = next((m for m in messages if m["message_id"] == message_id), None)
            if message:
                text = message.get("text", text)
        
        # If previous_message is not provided, try to get it from messages
        if previous_message is None and len(messages) > 1:
            prev_msg = messages[-2] if message_id == messages[-1].get("message_id") else None
            if prev_msg:
                previous_message = prev_msg.get("text", "")
        
        # If conversation_summary is not provided, use running_summary
        if conversation_summary is None:
            conversation_summary = self.running_summary
        
        # Format the input text to include context
        formatted_text = text # self._format_podcast_input(text, previous_message, conversation_summary)
        
        # Use distinct filename for podcast
        if shortTTS:
            filename = f"{message_id}_podcast_short.mp3"
        else:
            filename = f"{message_id}_podcast.mp3"
        audio_path = os.path.join(audio_dir, filename)
        
        try:
            # If file exists and recompute=False, stream it from local file
            if os.path.exists(audio_path) and not recompute:
                if audio_path.endswith(".mp3"):
                    logger.info(f"Streaming existing podcast audio file for message_id={message_id}")
                    with open(audio_path, 'rb') as f:
                        while chunk := f.read(8192):  # Stream in 8KB chunks
                            yield chunk
                    return
                else:
                    logger.info(f"Found existing podcast audio file for message_id={message_id} but it is not an mp3 file")
                    raise Exception(f"Found existing podcast audio file for message_id={message_id} but it is not an mp3 file")
            
            # Initialize StreamingPodcastAgent
            podcast_agent = StreamingPodcastAgent(
                keys=self.get_api_keys(),
                storage_path=audio_path,
                convert_to_tts_friendly_format=True,
                shortTTS=shortTTS
            )
            
            # Stream the chunks to the client while saving to file
            audio_generator = podcast_agent(formatted_text, stream=True)
            for chunk in audio_generator:
                yield chunk
                
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error in streaming podcast conversion for message_id={message_id}: {e}")
            # Return empty generator on failure
            def empty_gen():
                yield
            return empty_gen()

    

    def move_messages_up_or_down(self, message_ids, direction="up"):
        messages = self.get_field("messages")
        message_ids: List[str] = [str(m) for m in message_ids]
        messages:List[Dict] = [m for m in messages if m["message_id"] in message_ids]
        # Get indices of selected messages
        selected_indices = []
        for i, msg in enumerate(self.get_field("messages")):
            if msg["message_id"] in message_ids:
                selected_indices.append(i)
        
        # Sort indices to maintain relative order
        selected_indices.sort()
        
        # Get all messages
        all_messages = self.get_field("messages")
        
        # Check boundaries
        if direction == "up" and min(selected_indices) > 0:
            # Move messages up
            for idx in selected_indices:
                msg = all_messages[idx]
                all_messages[idx] = all_messages[idx-1]
                all_messages[idx-1] = msg
                
        elif direction == "down" and max(selected_indices) < len(all_messages) - 1:
            # Move messages down (process in reverse to avoid conflicts)
            for idx in reversed(selected_indices):
                msg = all_messages[idx]
                all_messages[idx] = all_messages[idx+1] 
                all_messages[idx+1] = msg
                
        # Save changes
        self.set_messages_field(all_messages, overwrite=True)
        self.save_local()
        # we want to move them all up or down, relative to their current position.
        # we want to move them all up or down, relative to their current position.

    
    def delete_message(self, message_id, index):
        index = int(index)
        get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        messages = self.get_field("messages")
        messages = [m for i, m in enumerate(messages) if m["message_id"] != message_id and i != index]
        self.set_messages_field(messages, overwrite=True)
        self.save_local()

    def edit_message(self, message_id, index, text):
        get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        messages = self.get_field("messages")
        index = int(index)
        for i, m in enumerate(messages):
            if m["message_id"] == message_id or i == index:
                messages[i]["text"] = text

        self.set_messages_field(messages, overwrite=True)
        self.save_local()

    def __call__(self, query, userData=None):
        logger.info(f"Called conversation reply for chat Assistant with Query: {query}")
        for txt in self.reply(query, userData):
            yield json.dumps(txt)+"\n"

    # Add this method to the Conversation class
    def is_cancelled(self):
        """Check if this conversation has been cancelled"""
        from base import cancellation_requests  # Import here to avoid circular imports
        
        if self.conversation_id in cancellation_requests:
            return cancellation_requests[self.conversation_id].get('cancelled', False)
        return False

    def clear_cancellation(self):
        """Clear cancellation flag for this conversation"""
        from base import cancellation_requests
        
        if self.conversation_id in cancellation_requests:
            del cancellation_requests[self.conversation_id]

    def get_uploaded_documents_for_query(self, query, replace_reference=True):
        messageText = query["messageText"]
        messageText, code_blocks = extract_code_blocks(messageText)
        attached_docs = re.findall(r'#doc_\d+', messageText)
        attached_docs = list(set(attached_docs))
        attached_docs_names = attached_docs
        attached_docs = [int(d.split("_")[-1]) for d in attached_docs]
        attached_docs_readable = []
        attached_docs_readable_names = []
        attached_docs_data = []
        attached_docs_data_names = []
        doc_names_and_docs = list(zip(attached_docs_names, attached_docs))
        if len(attached_docs) > 0:
            # assert that all elements of attached docs are greater than equal to 1.
            uploaded_documents = self.get_uploaded_documents()
            filtered_docs_by_actual = [(n, d) for n, d in doc_names_and_docs if len(uploaded_documents) >= d >= 1]
            if len(filtered_docs_by_actual) > 0:
                attached_docs_names, attached_docs = zip(*filtered_docs_by_actual)
            else:
                attached_docs_names, attached_docs = [], []
            attached_docs: List[DocIndex] = [uploaded_documents[d - 1] for d in attached_docs]
            attached_docs_readable = []
            attached_docs_readable_names = []
            attached_docs_data = []
            attached_docs_data_names = []
            for n, d in zip(attached_docs_names, attached_docs):
                if (d.is_local and os.path.getsize(d.doc_source) < 100 * 1024) or (d.doc_source.endswith(".pdf") or d.doc_source.endswith(".jpeg") or d.doc_source.endswith(".jpg") or d.doc_source.endswith(".png") or d.doc_source.endswith(".bmp") or d.doc_source.endswith(".svg")) or (d.doc_source.endswith(
                    ".html")):
                    attached_docs_readable.append(d)
                    attached_docs_readable_names.append(n)
                elif d.is_local and (d.doc_source.endswith(".csv") or d.doc_source.endswith(".parquet") or d.doc_source.endswith(
                    ".tsv") or d.doc_source.endswith(".xlsx") or d.doc_source.endswith(".xls") or d.doc_source.endswith(".jsonl") or d.doc_source.endswith(".jsonlines") or d.doc_source.endswith(".json")):
                    attached_docs_data.append(d)
                    attached_docs_data_names.append(n)
                else:
                    attached_docs_readable.append(d)
                    attached_docs_readable_names.append(n)
            attached_docs = attached_docs_readable + attached_docs_data
            doc_infos = [d.title for d in attached_docs_data + attached_docs_readable]
            doc_infos_data = [d.title for d in attached_docs_data]
            doc_infos_readable = [d.title for d in attached_docs_readable]
            # replace each of the #doc_1, #doc_2 etc with the doc_infos
            if replace_reference:
                for i, d in enumerate(attached_docs_names):
                    doc = attached_docs[i]
                    doc_title = doc_infos[i]
                    messageText = messageText.replace(d, f"{d} (Title of {d} '{doc_title}')\n" + (f"data file: {doc.doc_source}\n" if doc_title in doc_infos_data else ""))
        query["messageText"] = restore_code_blocks(messageText, code_blocks)
        return query, attached_docs, attached_docs_names, (attached_docs_readable, attached_docs_readable_names), (attached_docs_data, attached_docs_data_names)

    def get_prior_messages_summary(self, query:str)->str:
        summary_lookback = 12
        futures = [get_async_future(self.get_field, "memory"), get_async_future(self.get_field, "messages")]
        memory, messages = [f.result() for f in futures]
        previous_messages = messages[-16:]
        previous_messages = [{"sender": m["sender"],"text": extract_user_answer(m["text"])} for m in previous_messages]
        if len(previous_messages) < 2:
            return ""
        prev_msg_text = []
        for m in reversed(previous_messages):
            prev_msg_text.append(f"{m['sender']}:\n'''{m['text']}'''")
            if get_gpt3_word_count("\n\n".join(prev_msg_text)) > 96000:
                break
        previous_messages = "\n\n".join(reversed(prev_msg_text))
        running_summary = self.running_summary

        if memory is not None and len(memory["running_summary"]) > 4:
            summary_nodes = memory["running_summary"][-4:-3]
        else:
            summary_nodes = []

        summary_nodes = summary_nodes + [running_summary]
        summary_text = []
        for s in reversed(summary_nodes):
            summary_text.append(s)
            if get_gpt3_word_count("\n\n".join(summary_text)) > 12_000:
                break
        summary_nodes = "\n".join(reversed(summary_text))
        system = f"""You are given conversation details between a user and assistant. 
You will perform useful information retrieval only based on user query.
Extract revelant information from past messages and summary which are relevant to the current user query. 
For code, tables and other information which involves formatting extract them verbatim and just copy paste from the previous conversation messages.
Only extract relevant information, instruction, code and facts which are relevant to the current user query. 
Don't provide answer to the user query, just remember to extract information from the conversation.
"""
        prompt = f"""You are given conversation details between a user and assistant. 
You will perform useful information retrieval only based on user query.
Extract revelant information from past messages and summary which are relevant to the current user query. 
For code and other information which involves formatting extract them verbatim and just copy paste from the previous conversation messages.
Only extract relevant information, instruction, code and facts which are relevant to the current user query. Don't answer the user query, only extract information from previous messages.

The current user query is as follows:
'''{query}'''

Extract relevant information that might be useful in answering the above user query from the following conversation messages:
'''{previous_messages}'''

The summary of the conversation is as follows:
'''{summary_nodes}'''

Now lets extract relevant information for answering the current user query from the above conversation messages and summary. 
For certain type of information, like code, tables, equations, etc, extract them verbatim and paste it below if they are relevant to the user query.
Extract information in a concise and short manner suitable for a recap.
Write the useful information extracted from the above conversation messages and summary below in a brief, concise and short manner:
"""
        final_information = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False,
                                use_16k=False)(prompt, system=system, temperature=0.2, stream=False)
        # We return a string
        final_information = " ".join(final_information.split()[:4000])
        return final_information
    @property
    def max_time_to_wait_for_web_results(self):
        return MAX_TIME_TO_WAIT_FOR_WEB_RESULTS

    @property
    def retrieval_based_preambles(self):
        preamble_names = [
            "no format",
                          "Paper Summary",
                          # "no ai",
                          # "md format",
                          # "better formatting",
                          # "Easy Copy",
                          "Short",
                          # "No Code Exec",
                          # "Code Exec",
                          "Is Coding Request",
                          "Long",
                          # "CoT",
                          # "Short references",
                          "Latex Eqn",
                          "Explore",
            "Comparison",
        ]
        return preamble_names

    def get_preamble(self, preamble_options, field, web_search_or_document_read=False, prefix=None, **kwargs):
        preamble = ""
        plot_prefix = f"plot-{prefix}-"
        from flask import request as flask_request
        render_prefix=f"{flask_request.url_root.rstrip('/')}/get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}"
        agent = None
        if "no format" in preamble_options:
            # remove "md format" and "better formatting" from preamble options
            preamble_options = [p for p in preamble_options if p not in ["md format", "better formatting", "Latex Eqn", "Short references"]]
            preamble += "\n Write plaintext with separation between paragraphs by newlines. Don't use any formatting, avoid formatting. Write the answer in plain text.\n"
        if "Diagram" in preamble_options:
            preamble += diagram_instructions.format(output_directory=self.documents_path, plot_prefix=plot_prefix)
        
        if "TTS" in preamble_options:
            preamble += f"""We are using a TTS engine to read out to blind users. 
{tts_friendly_format_instructions}

Make it easy to understand and follow along. Provide pauses and repetitions to help understanding while listening. Your answer will be read out loud by a TTS engine.
"""
        if "Engineering Excellence" in preamble_options:
            preamble += prompts.engineering_excellence_prompt
            
        if "Coding Interview" in preamble_options:
            preamble += prompts.coding_interview_prompt
            

        if "Paper Summary" in preamble_options:
            preamble += prompts.paper_summary_prompt
        if "ML Design Roleplay" in preamble_options:
            preamble += prompts.ml_system_design_role
            
        if "ML Design Answer" in preamble_options:
            preamble += prompts.ml_system_design_answer
            
        if "ML Design Answer Short" in preamble_options:
            preamble += prompts.ml_system_design_answer_short
            
        if "no ai" in preamble_options:
            preamble += preamble_no_ai

        if "Easy Copy" in preamble_options:
            preamble += preamble_easy_copy
        if "Short" in preamble_options:
            preamble += preamble_short
        if "No Code Exec" in preamble_options:
            preamble += preamble_no_code_exec
        if "Code Exec" in preamble_options:
            preamble += preamble_code_exec
        if "CoT" in preamble_options:
            preamble += preamble_cot
        if "Short Coding Interview" in preamble_options:
            preamble += short_coding_interview_prompt
        if "Relationship" in preamble_options:
            preamble += relationship_prompt
        if "Dating Maverick" in preamble_options:
            preamble += dating_maverick_prompt
        if "More Related Coding Questions" in preamble_options:
            preamble += more_related_questions_prompt
        if "Explore" in preamble_options:
            preamble += preamble_explore
        if "Creative" in preamble_options:
            preamble += preamble_creative
        if "Argumentative" in preamble_options:
            preamble += preamble_argumentative
        if "Blackmail" in preamble_options:
            preamble += preamble_blackmail
        if "Web Search" in preamble_options or web_search_or_document_read:
            preamble += preamble_web_search
        if "Wife Prompt" in preamble_options:
            preamble += wife_prompt
        
        if "Improve Code" in preamble_options:
            preamble += improve_code_prompt
        if "Improve Code Interviews" in preamble_options:
            preamble += improve_code_prompt_interviews

        if field == "None":
            pass
        if field == "Prompt_IdeaNovelty":
            pass
        
        model_name = kwargs.get("model_name", EXPENSIVE_LLM[0])
        if field == "Agent_IdeaNovelty":
            pass
        if field == "JinaSearchAgent":
            agent = JinaSearchAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=120)
        if field == "PerplexitySearch":
            agent = PerplexitySearchAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=90)
        if field == "WebSearch":
            agent = WebSearchWithAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=90, gscholar=False)
        if field == "MultiSourceSearch":
            agent = MultiSourceSearchAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=90)
        if field == "LiteratureReview":
            agent = LiteratureReviewAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=90, gscholar=False)
        if field == "BroadSearch":
            agent = BroadSearchAgent(self.get_api_keys(), model_name=model_name if isinstance(model_name, str) else model_name[0], detail_level=kwargs.get("detail_level", 1), timeout=90, gscholar=False)
        if field == "InterviewSimulator":
            keys = self.get_api_keys()
            detail_level = kwargs.get("detail_level", 1)
            conversation_id = self.conversation_id
            model_name = model_name if isinstance(model_name, str) else model_name[0]
            agent = InterviewSimulatorAgent(keys, writer_model=model_name, conversation_id=conversation_id, detail_level=detail_level, timeout=90)
        if field == "InterviewSimulatorV2":
            keys = self.get_api_keys()
            detail_level = kwargs.get("detail_level", 1)
            conversation_id = self.conversation_id
            model_name = model_name if isinstance(model_name, str) else model_name[0]
            agent = InterviewSimulatorAgentV2(keys, writer_model=model_name, conversation_id=conversation_id, detail_level=detail_level, timeout=90)

        if field == "NResponseAgent":
            agent = NResponseAgent(self.get_api_keys(), writer_model=model_name, n_responses=kwargs.get("n_responses", 3))
        if field == "NStepCodeAgent":
            agent = NStepCodeAgent(self.get_api_keys(), writer_model=model_name, n_steps=kwargs.get("detail_level", 4))
        if field == "CodeSolveAgent":
            agent = CodeSolveAgent(self.get_api_keys(), writer_model=model_name, n_steps=kwargs.get("detail_level", 2))
        if field == "MLSystemDesignAgent":
            agent = MLSystemDesignAgent(self.get_api_keys(), writer_model=model_name, n_steps=kwargs.get("detail_level", 4))
        if field == "ToCGenerationAgent":
            agent = ToCGenerationAgent(llm_name=model_name if isinstance(model_name, str) else model_name[0], keys=self.get_api_keys(), run_phase_2=kwargs.get("detail_level", 1)>2, run_phase_3=kwargs.get("detail_level", 1)>3, storage_path=os.path.join(self.documents_path, f""), render_prefix=render_prefix)
            
        if field == "BookCreatorAgent":
            agent = BookCreatorAgent(llm_name=model_name if isinstance(model_name, str) else model_name[0], keys=self.get_api_keys(), depth=kwargs.get("detail_level", 1), storage_path=os.path.join(self.documents_path, f""), render_prefix=render_prefix)
        
        if field == "WhatIf":
            agent = WhatIfAgent(self.get_api_keys(), writer_models=model_name, n_scenarios=kwargs.get("n_scenarios", 3))
        if field == "CodeExecution":
            pass
        if field == "VerifyAndImprove":
            pass
        if field == "ElaborateDiveDeepExpand":
            pass
        if field == "Finance":
            pass
        if field == "DocQnA":
            pass
        if field == "SlideAgent":
            from agents.slide_agent import GenericSlideAgent
            agent = GenericSlideAgent(self.get_api_keys(), writer_model=model_name if isinstance(model_name, str) else model_name[0], demo_mode=True)
        if field == "CodingSlideAgent":
            from agents.slide_agent import CodingQuestionSlideAgent
            agent = CodingQuestionSlideAgent(self.get_api_keys(), writer_model=model_name if isinstance(model_name, str) else model_name[0], demo_mode=True)
        # Handle PPT answer mode - override agent selection if ppt_answer is enabled
        ppt_answer = kwargs.get("ppt_answer", False)
        if ppt_answer:
            # Select appropriate slide agent based on preamble options
            if "Short Coding Interview" in preamble_options:
                from agents.slide_agent import CodingQuestionSlideAgent
                agent = CodingQuestionSlideAgent(self.get_api_keys(), writer_model=model_name if isinstance(model_name, str) else model_name[0], demo_mode=True)
            else:
                from agents.slide_agent import GenericSlideAgent
                agent = GenericSlideAgent(self.get_api_keys(), writer_model=model_name if isinstance(model_name, str) else model_name[0], demo_mode=True)
        
        final_preamble = preamble
        if final_preamble.strip() == "":
            final_preamble = None
        else:
            final_preamble = final_preamble.strip()
        return final_preamble, agent

    def agent_level_one_websearch_helper(self, messageText, queries=list(), checkboxes=dict()):
        query = dict()
        query["search"] = queries
        query["messageText"] = messageText
        query["checkboxes"] = {"provide_detailed_answers": "1",
                               "main_model": "anthropic/claude-3-sonnet:beta",
                               "persist_or_not": False,
                               "enable_planner": False,
                               "perform_web_search": True,
                               "googleScholar": False,
                               "use_memory_pad": False,
                               "tell_me_more": False,
                               "enable_previous_messages": "-1"}
        query['links'] = []

        query["checkboxes"].update(checkboxes)
        answer = ''
        for r in self.reply(query):
            answer += r["text"]
        return answer

    def get_coding_rules(self, query, attached_docs_data, attached_docs_data_names, need_diagram=True, code_execution=True):
        message_ids = self.get_message_ids(query, "")
        prefix = message_ids["user_message_id"]
        plot_prefix = f"plot-{prefix}-"
        file_prefix = f"file-{prefix}-"
        # if input files are csv, tsv, xlsx, parquet then we need to read them and provide the data head to give idea of columns and content to the LLM. using zip(attached_docs_data, attached_docs_data_names)
        data_explore = ""
        # list data files like csv, tsv, xlsx, parquet in the working directory in data_explore
        for fname in os.listdir(self.documents_path):
            if fname.endswith(".csv") or fname.endswith(".tsv") or fname.endswith(".xlsx") or fname.endswith(".parquet"):
                data_explore += f"Data file: {fname}\n"


        def get_data_head(doc_source):
            if doc_source.endswith(".csv"):
                df = pd.read_csv(doc_source)
            elif doc_source.endswith(".tsv"):
                df = pd.read_csv(doc_source, sep="\t")
            elif doc_source.endswith(".xlsx"):
                df = pd.read_excel(doc_source)
            elif doc_source.endswith(".parquet"):
                df = pd.read_parquet(doc_source)
            return df.dtypes.to_string(), df.head(5).to_string()
        for d, n in zip(attached_docs_data, attached_docs_data_names):
            if d.doc_source.endswith(".csv") or d.doc_source.endswith(".tsv") or d.doc_source.endswith(".xlsx") or d.doc_source.endswith(".parquet"):
                data_explore += f"Data from 'name:{n}, file: {d.doc_source}':\n"
                dt = get_data_head(d.doc_source)
                data_explore += "-" * 50 + "\n"
                data_explore += f"{dt[0]}\n{dt[1]}\n\n"
                data_explore += "-" * 50 + "\n"

        # List other files in the working directory as well.
        for fname in os.listdir(self.documents_path):
            if fname.endswith(".csv") or fname.endswith(".tsv") or fname.endswith(".xlsx") or fname.endswith(".parquet"):
                data_explore += f"Data from 'name:{fname}, file: {os.path.join(self.documents_path, fname)}':\n"
                dt = get_data_head(os.path.join(self.documents_path, fname))
                data_explore += "-" * 50 + "\n"
                data_explore += f"{dt[0]}\n{dt[1]}\n\n"
                data_explore += "-" * 50 + "\n"

        coding_rules = prompts.coding_prompt.format(input_directory=self.documents_path,
                                                    output_directory=self.documents_path,
                                                    input_files_preview=data_explore,
                                                    input_files=str([f"name:{n}, file: `{d.doc_source}`;" for d, n in
                                                                     zip(attached_docs_data, attached_docs_data_names)]),
                                                    plot_prefix=plot_prefix, file_prefix=file_prefix, )
        return coding_rules if code_execution else "", prefix # if need_diagram or code_execution else ""

    
    def set_next_question_suggestions(self, suggestions):
        self.next_question_suggestions = suggestions
    
    def get_next_question_suggestions(self):
        if self.next_question_suggestions is None or len(self.next_question_suggestions) == 0:
            messages = self.get_field("messages")
            
            running_summary = self.running_summary
            if len(messages) >= 4:
                nqs = self.create_next_question_suggestions(messages[-2]["text"], messages[-1]["text"], messages[-4]["text"] + "\n\n" + messages[-3]["text"], running_summary)
            elif len(messages) >= 2:
                nqs = self.create_next_question_suggestions(messages[-2]["text"], messages[-1]["text"], "", running_summary)
            else:
                nqs = []
            self.set_next_question_suggestions(nqs)
        return self.next_question_suggestions
    
    def reply(self, query, userData=None):
        time_logger.info(f"[Conversation] reply called for chat Assistant.")
        self.next_question_suggestions = list()
        self.clear_cancellation()
        # get_async_future(self.set_field, "memory", {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        pattern = r'\[.*?\]\(.*?\)'
        st = time.time()
        time_dict = dict()
        user_memory = userData.get("user_memory", None) if userData is not None else None
        user_preferences = userData.get("user_preferences", None) if userData is not None else None
        
        answer = ''
        summary = self.running_summary
        summary_text_init = summary
        summary_text = summary
        checkboxes = query["checkboxes"]
        if "delete_last_turn" in checkboxes and checkboxes["delete_last_turn"]:
            self.delete_last_turn()
        persist_or_not = checkboxes["persist_or_not"] if "persist_or_not" in checkboxes else True
        enable_planner = checkboxes["enable_planner"] if "enable_planner" in checkboxes else False
        provide_detailed_answers = int(checkboxes["provide_detailed_answers"])
        past_message_ids = checkboxes["history_message_ids"] if "history_message_ids" in checkboxes else []
        enablePreviousMessages = str(checkboxes.get('enable_previous_messages', "infinite")).strip()
        
        # Extract reward level from checkboxes (0 = disabled, -3 to +3 = enabled with sensitivity)
        reward_level = int(checkboxes.get("reward_level", 0))
        if enablePreviousMessages == "infinite":
            message_lookback = provide_detailed_answers * 4
        else:
            message_lookback = int(enablePreviousMessages) * 2
        checkboxes["ppt_answer"] = checkboxes["ppt_answer"] if "ppt_answer" in checkboxes and bool(checkboxes["ppt_answer"]) else False
        only_slides = checkboxes["only_slides"] if "only_slides" in checkboxes and bool(checkboxes["only_slides"]) else False
        render_close_to_source = checkboxes["render_close_to_source"] if "render_close_to_source" in checkboxes and bool(checkboxes["render_close_to_source"]) else False
        checkboxes["render_close_to_source"] = render_close_to_source
        if checkboxes["ppt_answer"]:
            # permanent_instructions += "User has requested to receive the answer in PowerPoint slide format.\n"
            # reduce message lookback to 2
            message_lookback = 2

        prior_context_future = get_async_future(self.retrieve_prior_context,
                                                query["messageText"], past_message_ids=past_message_ids,
                                                required_message_lookback=message_lookback)
        prior_context = prior_context_future.result()
        time_dict["prior_context_time"] = time.time() - st
        previous_messages = prior_context["previous_messages"]
        previous_messages_very_short = prior_context["previous_messages_very_short"]
        previous_messages_short = previous_messages
        previous_messages_long = prior_context["previous_messages_long"]
        previous_messages_very_long = prior_context["previous_messages_very_long"]
        
        # Start reward evaluation async if reward level is non-zero
        reward_future = self._initiate_reward_evaluation(
            reward_level, query["messageText"], checkboxes, previous_messages_long, summary
        )
        permanent_instructions = ("Follow the below instructions given by the user.\n" + checkboxes[
            "permanentText"] + "\n") if "permanentText" in checkboxes and len(
            checkboxes["permanentText"].strip()) > 0 else ""

        yield {"text": '', "status": "Getting planner response ..."}
        planner_prompt = prompts.planner_checker_prompt.format(permanent_instructions=permanent_instructions, doc_details=self.doc_infos,
                                              summary_text=summary, previous_messages=remove_code_blocks(previous_messages_very_short), context=remove_code_blocks(query["messageText"]))

        st_planner = time.time()
        time_dict["before_planner_time"] = time.time() - st
        checkboxes["need_diagram"] = checkboxes["draw"] if "draw" in checkboxes and bool(checkboxes["draw"]) else False
        checkboxes["code_execution"] = checkboxes["execute"] if "execute" in checkboxes and bool(checkboxes["execute"]) else False
        

        if checkboxes["code_execution"]:
            permanent_instructions += "User has requested to execute the code and write executable code which we can run.\n"
        if checkboxes["need_diagram"]:
            permanent_instructions += "User has requested to draw diagrams in our available drawing/charting/plotting methods.\n"
        if enable_planner:
            # TODO: use gpt4o with planner. Don't execute code unless user has asked to explicitly execute code.
            planner_text_gen = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=True, use_16k=True)(planner_prompt,
                                                                                          temperature=0.2, stream=True)
        elif checkboxes["googleScholar"] or checkboxes["perform_web_search"] or checkboxes["code_execution"] or checkboxes["need_diagram"]:
            planner_text_gen = ""
        else:
            planner_text_gen = ""
            # planner_text_gen = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=True)(planner_prompt, temperature=0.2, stream=True)


        google_scholar = checkboxes["googleScholar"]
        searches = [s.strip() for s in query["search"] if s is not None and len(s.strip()) > 0]
        perform_web_search = checkboxes["perform_web_search"] or len(searches) > 0
        preambles = checkboxes["preamble_options"] if "preamble_options" in checkboxes else []
        if provide_detailed_answers >= 3 and "Short reply" not in preambles:
            preambles.append("Long")
        science_sites_count = count_science_urls(query["messageText"])
        if science_sites_count > 0:
            preambles.append("Paper Summary")
            preambles.append("Long")
            preambles.append("Latex Eqn")
            preambles.append("Explain Maths")
        if "code_execution" in checkboxes and checkboxes["code_execution"]:
            preambles.append("Long")
            preambles.append("Is Coding Request")

        retrieval_preambles = [p for p in preambles if p in self.retrieval_based_preambles]
        
        if science_sites_count > 1:
            preambles.append("Comparison")

        tell_me_more = False
        tell_me_more_msg_resp = None
        previous_message_config = None
        prev_attached_docs, prev_attached_docs_names = None, None
        prev_attached_docs_data, prev_attached_docs_names_data = None, None
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
                    mtext = " ".join(previous_message_config["attached_docs_names"]) if "attached_docs_names" in previous_message_config else ""
                    mtext += " ".join(previous_message_config["attached_docs_names_data"]) if "attached_docs_names_data" in previous_message_config else ""
                    prev_attached_docs_future = get_async_future(self.get_uploaded_documents_for_query, {"messageText": mtext}, False)
                    _, _, _, (prev_attached_docs, prev_attached_docs_names), (prev_attached_docs_data, prev_attached_docs_names_data) = prev_attached_docs_future.result()
                else:
                    prev_attached_docs_future = get_async_future(self.get_uploaded_documents_for_query,
                                                                 {"messageText": last_user_message["text"]}, False)
                    _, _, _, (prev_attached_docs, prev_attached_docs_names), (prev_attached_docs_data, prev_attached_docs_names_data) = prev_attached_docs_future.result()
                if "link_context" in previous_message_config:
                    previous_message_config["link_context"] = "\n" + previous_message_config["link_context"]
                if "perform_web_search" in previous_message_config and previous_message_config["perform_web_search"]:
                    checkboxes["perform_web_search"] = True
                    previous_message_config["web_search_user_query"] = "\n" + previous_message_config["web_search_user_query"]
                if "googleScholar" in previous_message_config and previous_message_config["googleScholar"]:
                    checkboxes["googleScholar"] = True
                    previous_message_config["web_search_user_query"] = "\n" + previous_message_config["web_search_user_query"]


        links_in_text = enhanced_robust_url_extractor(query['messageText'])
        query['links'].extend(links_in_text)
        if len(links_in_text) > 1 and "\n" not in query['messageText']:
            yield {"text": "We don't support multiple links on single line.\n", "status": "Reading your provided links."}
        links = list(set([l.strip() for l in query["links"] if
                          l is not None and len(l.strip()) > 0]))  # and l.strip() not in raw_documents_index
        # check if a pattern like #doc_<number> is present in query['messageText']
        attached_docs = re.findall(r'#doc_\d+', query['messageText'])
        
        # if any of the patterns are present in query['messageText'], then set links to [], don't process links
        if "<no_links_processing>" in query['messageText'] or "no_links_processing" in query['messageText'] or "no_link_processing" in query['messageText'] or "no_link_parsing" in query['messageText']  or "no_links_parsing" in query['messageText'] or "parse_no_links" in query['messageText'] or "parse_no_link" in query['messageText'] or "avoid_links_processing" in query['messageText'] or "avoid_link_parsing" in query['messageText'] or "avoid_link_processing" in query['messageText']:
            links = []

        qmt_no_space = query['messageText'].replace(" ", "_")
        if "<no_links_processing>" in qmt_no_space or "no_links_processing" in qmt_no_space or "no_link_processing" in qmt_no_space or "no_link_parsing" in qmt_no_space  or "no_links_parsing" in qmt_no_space or "parse_no_links" in qmt_no_space or "parse_no_link" in qmt_no_space or "avoid_links_processing" in qmt_no_space or "avoid_link_parsing" in qmt_no_space or "avoid_link_processing" in qmt_no_space:
            links = []
            
        if "No Links" in preambles:
            links = []
        
        pattern = r'(#dense_summary_doc_\d+|#summary_doc_\d+|#summarise_doc_\d+|#summarize_doc_\d+|#dense_summarise_doc_\d+|#dense_summarize_doc_\d+)'
        attached_docs_for_summary = re.findall(pattern, query['messageText'])
        attached_docs_for_summary = " ".join(attached_docs_for_summary) if len(attached_docs_for_summary) > 0 else ""
        if len(attached_docs_for_summary) > 0:
            
            assert attached_docs_for_summary == query['messageText'].strip(), f"Attached docs for summary should be the only docs in the message text. Our message text is:\n{query['messageText']}\n\nAttached docs are:\n{attached_docs_for_summary}"
            
        is_dense = "dense_summary" in attached_docs_for_summary

        if "/title " in query['messageText'] or "/set_title " in query['messageText']:
            title = None
            
            # Try to match /title pattern first
            title_match = re.search(r'/title (.*)', query['messageText'], re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
            else:
                # Try to match /set_title pattern
                set_title_match = re.search(r'/set_title (.*)', query['messageText'], re.DOTALL)
                if set_title_match:
                    title = set_title_match.group(1).strip()
            
            if title:
                self.set_title(title)
                yield {"text": f"Title set to {title}", "status": "Title set to {title}"}
            model_name = FILLER_MODEL
            checkboxes["main_model"] = model_name

        
        if "/temp " in query['messageText'] or "/temporary " in query['messageText']:
            
            query['messageText'] = query['messageText'].replace("/temp ", "").replace("/temporary ", "").strip()
            persist_or_not = False
            
        attached_docs_for_summary = attached_docs_for_summary.replace("dense_summary_", "").replace("summary_", "").replace("summarise_", "").replace("summarize_", "").replace("dense_summarise_", "").replace("dense_summarize_", "")
        attached_docs_for_summary_future = get_async_future(self.get_uploaded_documents_for_query, {"messageText":attached_docs_for_summary})
        _, attached_docs, doc_names, (_, _), (
            _, _) = attached_docs_for_summary_future.result()
        if len(attached_docs) > 0:
            assert len(attached_docs) == 1, "Only one doc is allowed for summary."
            yield {"text": '', "status": "Reading your attached documents for summary."}
            yield {"text":  "<answer>\n", "status": "Generating summary of the document."}
            
            answer += "<answer>\n"
            if is_dense:
                summary = make_stream(attached_docs[0].get_chain_of_density_summary(), True)
            else:
                summary = make_stream(attached_docs[0].get_doc_long_summary(), True)
            for ans in summary:
                answer += ans
                yield {"text": ans, "status": "Generating summary of the document."}
            
            answer += "</answer>\n"
            yield {"text": "</answer>\n", "status": "answering ended ..."}
            
            time_dict["total_time_to_reply"] = time.time() - st
            
            
            yield {"text": '', "status": "saving answer ..."}
            yield {"text": '', "status": "saving message ..."}
            get_async_future(self.persist_current_turn, query['messageText'], answer, dict(**checkboxes), previous_messages_long, summary, {}, persist_or_not, past_message_ids)
            # Process reward evaluation before saving message
            if reward_future is not None:
                yield {"text": "\n", "status": "reward evaluation complete"}
                yield from self._process_reward_evaluation(reward_future)
                yield {"text": "\n", "status": "reward evaluation complete"}
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}
            stats = collapsible_wrapper(yaml.dump(time_dict, default_flow_style=False), header="Time taken to reply for chatbot", show_initially=False, add_close_button=False)
            for chunk in stats:
                yield {"text": chunk, "status": "saving answer ...", "message_ids": message_ids}
            yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}
            return
        
        
        # Handle full document text request
        attached_docs_for_full = re.findall(r'#full_doc_\d+', query['messageText'])
        attached_docs_for_full = " ".join(attached_docs_for_full) if len(attached_docs_for_full) > 0 else ""
        
        if len(attached_docs_for_full) > 0:
            
            assert attached_docs_for_full == query['messageText'].strip(), "Attached docs for full text should be the only docs in the message text."
            
            attached_docs_for_full = attached_docs_for_full.replace("full_", "")
            attached_docs_for_full_future = get_async_future(self.get_uploaded_documents_for_query, {"messageText": attached_docs_for_full})
            _, attached_docs, doc_names, (_, _), (
                _, _) = attached_docs_for_full_future.result()
                
            if len(attached_docs) > 0:
                assert len(attached_docs) == 1, "Only one doc is allowed for summary."
                yield {"text": '', "status": "Reading your attached document for full text view."}
                yield {"text":  "<answer>\n", "status": "Getting full text of the document."}
                yield {"text": attached_docs[0].get_raw_doc_text(), "status": "Getting full text of the document."}
                answer += "<answer>\n"
                answer += attached_docs[0].get_raw_doc_text()
                answer += "</answer>\n"
                yield {"text": "</answer>\n", "status": "answering ended ..."}
                
                time_dict["total_time_to_reply"] = time.time() - st
                
                
                yield {"text": '', "status": "saving answer ..."}
                yield {"text": '', "status": "saving message ..."}
                get_async_future(self.persist_current_turn, query['messageText'], answer, dict(**checkboxes), previous_messages_long, summary, {}, persist_or_not, past_message_ids)
                message_ids = self.get_message_ids(query["messageText"], answer)
                # Process reward evaluation before saving message
                if reward_future is not None:
                    yield {"text": "\n", "status": "reward evaluation complete"}
                    yield from self._process_reward_evaluation(reward_future)
                    yield {"text": "\n", "status": "reward evaluation complete"}
                yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}
                stats = collapsible_wrapper(yaml.dump(time_dict, default_flow_style=False), header="Time taken to reply for chatbot", show_initially=False, add_close_button=False)
                for chunk in stats:
                    yield {"text": chunk, "status": "saving answer ...", "message_ids": message_ids}
                yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}
                return

        
            
        
        
        field = checkboxes["field"] if "field" in checkboxes else None
        model_name = checkboxes["main_model"] if "main_model" in checkboxes else None
        if isinstance(model_name, (tuple, list)):
            model_name = list(map(model_name_to_canonical_name, model_name))
            assert FILLER_MODEL not in model_name or len(model_name) == 1, "Filler model name is not allowed if multiple models are provided."
        else:
            model_name = model_name_to_canonical_name(model_name)
        if isinstance(model_name, (tuple, list)) and len(model_name) == 1:
            model_name = model_name[0].strip()

        if model_name == FILLER_MODEL:
            links = []
            
        if field is not None and field.startswith("Prompt_"):
            field_prompt = field.replace("Prompt_", "")
            query["messageText"] = self.replace_message_text_with_prompt(query["messageText"], field_prompt)
        
        message_ids = self.get_message_ids(query, "")
        prefix = message_ids["user_message_id"]
        plot_prefix = f"plot-{prefix}-"
        
        preamble, agent = self.get_preamble(preambles,
                                     checkboxes["field"] if "field" in checkboxes else None,
                                     perform_web_search or google_scholar or len(links) > 0 or len(
                                         attached_docs) > 0, detail_level=provide_detailed_answers, model_name=model_name, prefix=prefix, ppt_answer=checkboxes["ppt_answer"])
        previous_context = summary if len(summary.strip()) > 0 and message_lookback >= 0 else ''
        previous_context_and_preamble = "<|instruction|>" + str(retrieval_preambles) + "<|/instruction|>" + "\n\n" + "<|previous_context|>\n" + str(previous_context) + "<|/previous_context|>\n"
        link_context = previous_context_and_preamble + query['messageText'] + (
            previous_message_config["link_context"] if tell_me_more else '')
        if len(links) > 0:
            yield {"text": '', "status": "Reading your provided links."}
            link_future = get_async_future(read_over_multiple_links, links, [""] * len(links),
                                           [link_context] * (len(links)), self.get_api_keys(),
                                           provide_detailed_answers=max(0, int(provide_detailed_answers) - 1) or len(
                                               links) <= 2)


        prior_chat_summary_future = None
        if enable_planner:
            prior_chat_summary_future = get_async_future(self.get_prior_messages_summary, previous_context + "\n\n Current User Query or message:\n" + query["messageText"])
            
        
        
        planner_text = ''
        for t in planner_text_gen:
            if len(planner_text.strip()) == 0:
                time_dict["planner_first_word"] = time.time() - st
                time_logger.info(f"Time to get first word of planner text = {time.time() - st_planner:.2f} seconds with full text as \n{t}")
            planner_text += t
            if "<planner>" in planner_text and "</planner>" in planner_text:
                # use regex to get planner plan
                # get planner text along with planner tags included in the result text.
                time_dict["planner_full"] = time.time() - st
                planner_text_full = planner_text
                time_logger.info(f"Time to get planner text = {time.time() - st_planner:.2f} seconds with full text as \n{planner_text_full}")
                planner_text = re.search(r'<planner>(.*?)</planner>', planner_text, re.DOTALL).group(1)
                planner_text = "<planner>" + planner_text + "</planner>"
                planner_dict = xml_to_dict(planner_text)

                if "is_diagram_asked_explicitly" in planner_dict and string_indicates_true(planner_dict["is_diagram_asked_explicitly"]):
                    checkboxes["need_diagram"] = True
                    if "diagram_type_asked" in planner_dict and (planner_dict["diagram_type_asked"].strip().lower() == "drawio" or planner_dict["diagram_type_asked"].strip().lower() == "mermaid"):
                        preamble += diagram_instructions.format(output_directory=self.documents_path, plot_prefix=plot_prefix)
                if "python_code_execution_or_data_analysis_or_matplotlib_asked_explicitly" in planner_dict and string_indicates_true(planner_dict["python_code_execution_or_data_analysis_or_matplotlib_asked_explicitly"]):
                    checkboxes["code_execution"] = True
                    
                    
                if "web_search_asked_explicitly" in planner_dict and string_indicates_true(planner_dict["web_search_asked_explicitly"]) and len(links) == 0:
                    checkboxes["perform_web_search"] = True
                    if "web_search_queries" in planner_dict and len(planner_dict["web_search_queries"]) > 0:
                        if "search" in query and isinstance(query["search"], list):
                            query["search"].extend(planner_dict["web_search_queries"])
                        else:
                            query["search"] = planner_dict["web_search_queries"]
                    if 'web_search_type' in planner_dict and planner_dict['web_search_type'].strip().lower() != "none" and planner_dict[
                        'web_search_type'].strip().lower() != "" and planner_dict['web_search_type'] is not None and planner_dict[
                        'web_search_type'].strip().lower() != "na":
                        if planner_dict['web_search_type'].strip().lower() == "academic":
                            checkboxes["googleScholar"] = True

                if "read_uploaded_document" in planner_dict and string_indicates_true(planner_dict["read_uploaded_document"]):
                    document_ids = planner_dict["documents_to_read"]
                    query["messageText"] = query["messageText"] + "\n" + (" ".join(document_ids))
                    time_logger.info(f"Documents to read: {document_ids} and message text is \n\n{query['messageText']}\n\n")
                    print(f"Documents to read: {document_ids} and message text is \n\n{query['messageText']}\n\n")

                break
        et_planner = time.time()
        time_logger.info(
            f"Planner Module Time to exec: {et_planner - st_planner: .2f} seconds, Planner text: \n{planner_text}\n and message text is \n\n{query['messageText']}\n\n")
        attached_docs_future = get_async_future(self.get_uploaded_documents_for_query, query)
        user_query = query['messageText']
        use_memory_pad = False
        if "memory pad" in user_query or "memory_pad" in user_query or ("use_memory_pad" in checkboxes and checkboxes["use_memory_pad"]):
            use_memory_pad = True
            checkboxes["use_memory_pad"] = True
        message_config = dict(**checkboxes)

        message_config["link_context"] = link_context

        yield {"text": '', "status": "Getting prior chat context ..."}



        agentic_search = checkboxes["agentic_search"] if "agentic_search" in checkboxes else False
        message_config["googleScholar"] = google_scholar
        message_config["searches"] = searches
        original_user_query = user_query


        message_config["perform_web_search"] = perform_web_search
        message_config["links"] = query['links']
        
        unchanged_message_lookback = message_lookback

        web_search_tmp_marker_name = None
        perplexity_results_future = None
        if google_scholar or perform_web_search:
            web_search_tmp_marker_name = self.conversation_id + "_web_search" + str(time.time())
            create_tmp_marker_file(web_search_tmp_marker_name)
            time_dict["web_search_start"] = time.time() - st
            yield {"text": '', "status": "performing google scholar search" if google_scholar else "performing web search"}
            message_config["web_search_user_query"] = user_query + (previous_message_config["web_search_user_query"] if tell_me_more else '')
            previous_turn_results = dict(queries=previous_message_config["web_search_queries"], links=previous_message_config["web_search_links_unread"]) if tell_me_more else None
            time_logger.info(f"Time to Start Performing web search with chat query with elapsed time as {(time.time() - st):.2f}")
            web_results = get_async_future(web_search_queue, user_query + (previous_message_config["web_search_user_query"] if tell_me_more else ''), 'helpful ai assistant',
                                           previous_context,
                                           self.get_api_keys(), datetime.now().strftime("%Y-%m"), extra_queries=searches, previous_turn_search_results=previous_turn_results,
                                           gscholar=google_scholar, provide_detailed_answers=provide_detailed_answers, web_search_tmp_marker_name=web_search_tmp_marker_name)
            
            
            perplexity_agent = PerplexitySearchAgent(self.get_api_keys(), model_name="gpt-4o" if provide_detailed_answers >= 3 else "gpt-4o-mini", detail_level=provide_detailed_answers, timeout=90, num_queries=(10 if provide_detailed_answers >= 3 else 5) if provide_detailed_answers >= 2 else 3)
            perplexity_results_future = get_async_future(perplexity_agent.get_answer, "User Query:\n" + user_query + (previous_message_config["web_search_user_query"] if tell_me_more else '') + "\n\nPrevious Context:\n" + previous_context, system="You are a helpful assistant that can answer questions and provide detailed information.")
            
        if userData is not None:
            user_info_text = f"""Few details about the user and how they want us to respond to them:
**User Memory:** 
```
{user_memory}
```

**User Preferences:** 
```
{user_preferences}
```

Also given is the conversation summary:
```
{summary}
```

Previous conversation history:
```
{prior_context['previous_messages_very_short']}
```

The current query is:
```
{user_query}
```

Now based on the above information, please extract the user's preferences and user memory relevant to the current query and conversation history. Only focus on extracting the user preferences and user memory and only write the extracted user preferences and user memory.
If there is no user preferences or user memory relevant to the current query and conversation history, then just write "No user preferences or user memory found".
Write the extracted user preferences and user memory below in bullet points. Write in concise manner.
"""
            llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=True, use_16k=True)
            llm2 = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[1], use_gpt4=True, use_16k=True)
            user_info_text1 = get_async_future(llm, user_info_text, temperature=0.2, stream=False)
            user_info_text2 = get_async_future(llm2, user_info_text, temperature=0.2, stream=False)

        # raw_documents_index = self.get_field("raw_documents_index")
        link_result_text = ''
        full_doc_texts = {}

        query, attached_docs, attached_docs_names, (attached_docs_readable, attached_docs_readable_names), (
            attached_docs_data, attached_docs_data_names) = attached_docs_future.result()
        attached_docs, attached_docs_names = attached_docs_readable, attached_docs_readable_names

        coding_rules, prefix = self.get_coding_rules(query, attached_docs_data, attached_docs_data_names, need_diagram=checkboxes["need_diagram"] or "Code Exec" in preambles, code_execution=checkboxes["code_execution"] or "Code Exec" in preambles)
        plot_prefix = f"plot-{prefix}-"
        file_prefix = f"file-{prefix}-"
        if prev_attached_docs is not None:
            attached_docs.extend(prev_attached_docs)
            attached_docs_names.extend(prev_attached_docs_names)
            query["messageText"] = query["messageText"] + "\n" + " ".join(attached_docs_names) + "\n"

        if prev_attached_docs_data is not None:
            attached_docs_data.extend(prev_attached_docs_data)
            attached_docs_data_names.extend(prev_attached_docs_names_data)
            query["messageText"] = query["messageText"] + "\n" + " ".join(attached_docs_names) + "\n"
        if (google_scholar or perform_web_search or len(links) > 0 or len(attached_docs) > 0 or provide_detailed_answers >=3) and message_lookback >= 1 and provide_detailed_answers >=3 and len(past_message_ids) == 0:
            prior_chat_summary_future = get_async_future(self.get_prior_messages_summary, query["messageText"]) if prior_chat_summary_future is None else prior_chat_summary_future
            message_lookback = min(4, message_lookback)
        if (provide_detailed_answers == 0) and (len(links) + len(attached_docs) == 1 and len(
            searches) == 0):
            provide_detailed_answers = 2
        provide_raw_text = (len(links) + len(attached_docs)) <= 3 and provide_detailed_answers <= 3 and not (
                    google_scholar or perform_web_search) and unchanged_message_lookback <= 10
        if len(attached_docs) > 0:
            message_config["use_attached_docs"] = True
            message_config["attached_docs_names"] = attached_docs_names
        if len(attached_docs_data) > 0:
            message_config["attached_docs_data_names"] = attached_docs_data_names
            message_config["use_attached_docs"] = True

        if len(attached_docs) > 0:
            for ad in attached_docs:
                if ad.doc_type == "image" and ad.is_local:
                    source_file = ad.doc_source
                    filename = os.path.basename(source_file)
                    f = f"{plot_prefix}-{filename}"
                    image_path = f"get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}/{f}"
                    # TODO: url_encode_image_path with urllib
                    image_path = image_path.replace(" ", "%20")
                    save_path_for_render = os.path.join(self.documents_path, f)
                    shutil.copyfile(source_file, save_path_for_render)
                    image_md = f'\n[<img src="{image_path}" width="500"/>]({image_path})\n'
                    # image_md = f"\n![{f}]({image_path}) \n"
                    yield {"text": image_md, "status": "Reading your attached documents."}
                elif ad.doc_type == "image":
                    image_md = f'\n[<img src="{ad.doc_source}" width="500"/>]({ad.doc_source})\n'
                    # image_md = f"\n![{ad.title}]({ad.doc_source}) \n"
                    yield {"text": image_md, "status": "Reading your attached documents."}
            yield {"text": '', "status": "Reading your attached documents."}
            conversation_docs_future = get_async_future(get_multiple_answers,
                                                        previous_context_and_preamble + query["messageText"] + (f"\nPreviously we talked about: \n'''{tell_me_more_msg_resp}'''\n" if tell_me_more and tell_me_more_msg_resp is not None else ''),
                                                        attached_docs,
                                                        summary if message_lookback >= 0 else '',
                                                        max(0, int(provide_detailed_answers)),
                                                        provide_raw_text=provide_raw_text,
                                                        dont_join_answers=True)
        doc_answer = ''

        web_text = ''



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

            read_links = parse_mardown_link_text(link_result_text)
            read_links = list([[link.strip(), link_len] for link, title, link_len in read_links if
                               len(link.strip()) > 0 and len(title.strip()) > 0 and extract_url_from_mardown(
                                   link) in links])
            # if any link is an image then we display it.
            for link, link_len in read_links:
                if is_image_link(link):
                    image_md = f'\n[<img src="{link}" width="500"/>]({link})\n'
                    # image_md = f"\n![{link}]({link}) \n"
                    yield {"text": image_md, "status": "Reading your provided links."}

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

            cut_off = 0
            if len(search_results['search_results']) > 0:
                if provide_detailed_answers == 1:
                    cut_off = 6
                elif provide_detailed_answers == 2:
                    cut_off = 12
                elif provide_detailed_answers == 3:
                    cut_off = 16
                elif provide_detailed_answers == 4:
                    cut_off = 20
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
            qu_st = time.time()
            qu_mt = time.time()
            time_logger.info(f"Time to reach web search links accumulation code: {(qu_st - st):.2f}")
            time_dict["get_web_search_links"] = qu_st - st

            re_search = None

            def get_first_few_result_summary(start = 0, end=4):
                st = time.time()
                while len(web_text_accumulator) < end:
                    time.sleep(0.5)
                if not exists_tmp_marker_file(web_search_tmp_marker_name):
                    return ""
                full_web_string = ""
                for i, (wta, link, llm_future_dict) in enumerate(web_text_accumulator[start:]):
                    llm_text = sleep_and_get_future_result(llm_future_dict) if llm_future_dict.done() and \
                                                                   sleep_and_get_future_exception(llm_future_dict) is None else ""
                    web_string = f"{i + 1}.\n{link}\n{wta}\n{llm_text}"
                    full_web_string = full_web_string + web_string + "\n\n"
                    if get_gpt4_word_count(full_web_string) > 24000:
                        break
                prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                               summary_text=summary_text,
                                                               previous_messages=previous_messages_short,
                                                               permanent_instructions='Include references inline in wikipedia markdown format. Answer shortly, concisely and briefly while covering all given references.',
                                                               doc_answer='', web_text="\n"+full_web_string,
                                                               link_result_text='',
                                                               conversation_docs_answer='')
                answer_summary = CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_16k=True,
                                         use_gpt4=True)(prompt, temperature=0.3, stream=False)
                # web_text_accumulator.append((answer_summary, f"[Generated Answer from {start + 1} to {end + 1}](No Link)", answer_summary))
                et = time.time()
                time_logger.info(
                    f"Time taken to get web result four summary = {et - st:.2f} , with summary len = {len(answer_summary.split())}")
                return answer_summary

            first_four_summary = wrap_in_future("")
            second_four_summary = wrap_in_future("")
            if provide_detailed_answers >= 1:
                first_four_summary = get_async_future(get_first_few_result_summary, 0, 4)
            if provide_detailed_answers >= 2:
                second_four_summary = get_async_future(get_first_few_result_summary, 4, 8)
            third_four_summary = wrap_in_future("")
            if provide_detailed_answers >= 3:
                third_four_summary = get_async_future(get_first_few_result_summary, 8, 12)
            while True:
                qu_wait = time.time()
                break_condition = len(web_text_accumulator) >= cut_off or ((qu_wait - qu_st) > max(self.max_time_to_wait_for_web_results * 2, self.max_time_to_wait_for_web_results * provide_detailed_answers))
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
                    web_text_accumulator.append((one_web_result["text"], f'[{one_web_result["title"]}]({one_web_result["link"]})', one_web_result["llm_result_future"]))
                    yield {"text": '', "status": f"Reading <a href='{one_web_result['link']}'>{one_web_result['link']}</a> ... "}
                    time_logger.info(f"Time taken to get n-th {len(web_text_accumulator)}-th web result with len = {len(one_web_result['text'].split())}, time = {(time.time() - st):.2f}, wait time = {(qu_et - qu_st):.2f}, link = {one_web_result['link']}")
                time.sleep(0.5)

            time_logger.info(f"Time to get web search results without sorting: {(time.time() - st):.2f} with result count = {len(web_text_accumulator)} and only web reading time: {(time.time() - qu_st):.2f}")
            # Sort the array in reverse order based on the word count
            try:
                if re_search is not None:
                    for re_search_yield in sleep_and_get_future_result(re_search):
                        if re_search_yield and isinstance(re_search_yield, dict):
                            yield re_search_yield
                            answer += re_search_yield["text"]
            except Exception as e:
                error_logger.error(f"Error in re_search_if_needed: {e}, stack: {traceback.format_exc()}")

            web_text_accumulator = sorted(web_text_accumulator, key=lambda x: len(x[0].split()), reverse=True)
            web_text_accumulator = list(filter(lambda x: len(x[0].split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found." not in x[0].lower(), web_text_accumulator))

            remove_tmp_marker_file(web_search_tmp_marker_name)
            logger.info(
                f"Time taken to get web search results with sorting: {(time.time() - qu_st):.2f} with result len = {len(web_text_accumulator)}")
            full_web_string = ""
            web_text_accumulator = sorted(web_text_accumulator, key=lambda x: len(x[0].split()), reverse=True)
            web_text_accumulator = list(filter(
                lambda x: len(x[0].split()) > LEN_CUTOFF_WEB_TEXT and "No relevant information found." not in x[
                    0].lower(), web_text_accumulator))
            tt = time.time()
            while time.time() - tt < 5 and any([not wta.done() for wta in [first_four_summary, second_four_summary]]):
                time.sleep(0.5)
            if first_four_summary.done() and first_four_summary.exception() is None and first_four_summary.result().strip()!="":
                web_text_accumulator.append((first_four_summary.result(), f"[Generated Answer from {1} to {4}](No Link)", first_four_summary))

            if second_four_summary.done() and second_four_summary.exception() is None and second_four_summary.result().strip()!="":
                web_text_accumulator.append((second_four_summary.result(), f"[Generated Answer from {5} to {8}](No Link)", second_four_summary))
            if third_four_summary.done() and third_four_summary.exception() is None and third_four_summary.result().strip()!="":
                web_text_accumulator.append(
                    (third_four_summary.result(), f"[Generated Answer from {9} to {12}](No Link)", third_four_summary))

            for i, (wta, link, llm_future_dict) in enumerate(web_text_accumulator):
                llm_text = sleep_and_get_future_result(llm_future_dict) if llm_future_dict.done() and sleep_and_get_future_exception(llm_future_dict) is None else ""
                web_string = f"{i + 1}.\n{link}\n{wta}\n{llm_text}"
                full_web_string = full_web_string + web_string + "\n\n"
                if get_gpt4_word_count(full_web_string) > 36000:
                    break
            web_text = full_web_string
            # web_text = "\n\n".join(web_text_accumulator)
            # read_links = re.findall(pattern, web_text)

            # Make an array of links that are read with lengths.
            read_links = [[link.strip(), len(text.strip().split()), llm_future_dict.result() if llm_future_dict.done() and llm_future_dict.exception() is None else text] for text, link, llm_future_dict in web_text_accumulator]

            # read_links = parse_mardown_link_text(web_text)
            # read_links = list([[link.strip(), link_len] for link, title, link_len in read_links if len(link.strip())>0 and len(title.strip())>0 and any(extract_url_from_mardown(link) in seen_link for seen_link in web_results_seen_links)])

            if "web_search_links_read" in message_config:
                message_config["web_search_links_read"].extend(read_links)
            else:
                message_config["web_search_links_read"] = read_links
            if len(read_links) > 0:
                atext = "\n**We read the below links:** <div data-toggle='collapse' href='#readLinksStage2' role='button'></div> <div class='collapse' id='readLinksStage2'>" + "\n"
                read_links = atext + "\n\n".join([f"{i + 1}. {wta} : <{link_len} words>\n\t- {' '.join(text.split()[:(128 if 'No Link' not in wta else 1024)])}" for i, (wta, link_len, text) in enumerate(read_links)]) + "</div>\n\n"
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
            if (len(read_links) <= 1 and len(web_text.split()) < 200) and len(links)==0 and len(attached_docs) == 0:
                yield {"text": '', "status": "saving answer ..."}
                remove_tmp_marker_file(web_search_tmp_marker_name)
                message_ids = self.get_message_ids(query["messageText"], answer)
                yield {"text": 'WEB_SEARCH_FAILED', "status": "saving answer ...", "message_ids": message_ids}
                answer += 'WEB_SEARCH_FAILED'
                # Process reward evaluation before saving message
                if reward_future is not None:
                    yield {"text": "\n", "status": "reward evaluation complete"}
                    yield from self._process_reward_evaluation(reward_future)
                    yield {"text": "\n", "status": "reward evaluation complete"}
                get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, previous_messages_long, summary, full_doc_texts, persist_or_not, past_message_ids)
                return

        # TODO: if number of docs to read is <= 1 then just retrieve and read here, else use DocIndex itself to read and retrieve.
        remove_tmp_marker_file(web_search_tmp_marker_name)
        if (len(links)==1 and len(attached_docs) == 0 and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback<=-1):
            text = link_result_text.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            # Process reward evaluation before saving message
            if reward_future is not None:
                yield {"text": "\n", "status": "reward evaluation complete"}
                yield from self._process_reward_evaluation(reward_future)
                yield {"text": "\n", "status": "reward evaluation complete"}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, previous_messages_long, summary, full_doc_texts, persist_or_not, past_message_ids)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return



        if (len(links)==0 and (len(attached_docs) == 1 and not any([isinstance(d, ImageDocIndex) for d in attached_docs])) and not (google_scholar or perform_web_search) and provide_detailed_answers <= 2 and unchanged_message_lookback<=-1):
            text = conversation_docs_answer.split("Raw article text:")[0].replace("Relevant additional information from other documents with url links, titles and useful context are mentioned below:", "").replace("'''", "").replace('"""','').strip()
            text = "\n".join(text.replace("The documents that were read are as follows:", "").split("\n")[2:])
            yield {"text": text, "status": "answering in progress"}
            answer += text
            yield {"text": '', "status": "saving answer ..."}
            # Process reward evaluation before saving message
            if reward_future is not None:
                yield {"text": "\n", "status": "reward evaluation complete"}
                yield from self._process_reward_evaluation(reward_future)
                yield {"text": "\n", "status": "reward evaluation complete"}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, previous_messages_long, summary, full_doc_texts, persist_or_not, past_message_ids)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '', "status": "saving answer ...", "message_ids": message_ids}
            return

        if (len(web_text.split()) < 200 and (google_scholar or perform_web_search)) and len(links) == 0 and len(attached_docs) == 0:
            yield {"text": '', "status": "saving answer ..."}
            answer += '!ERROR WEB SEARCH FAILED\n'
            # Process reward evaluation before saving message
            if reward_future is not None:
                yield {"text": "\n", "status": "reward evaluation complete"}
                yield from self._process_reward_evaluation(reward_future)
                yield {"text": "\n", "status": "reward evaluation complete"}
            get_async_future(self.persist_current_turn, query["messageText"], answer, message_config, previous_messages_long, summary, full_doc_texts, persist_or_not, past_message_ids)
            message_ids = self.get_message_ids(query["messageText"], answer)
            yield {"text": '!ERROR WEB SEARCH FAILED\n', "status": "saving answer ...", "message_ids": message_ids}
            return
        yield {"text": '', "status": "getting previous context"}
        prior_chat_summary = ""
        wt_prior_ctx = time.time()
        summary_text = summary_text_init
        while time.time() - wt_prior_ctx < 10 and prior_chat_summary_future is not None:
            if prior_chat_summary_future.done() and not prior_chat_summary_future.exception():
                prior_chat_summary = prior_chat_summary_future.result()
                summary_text = prior_chat_summary + "\n" + summary_text
                break
            if prior_chat_summary_future.exception() is not None:
                break
            time.sleep(0.5)
        time_logger.info(f"Time to wait for prior context with 16K LLM: {(time.time() - wt_prior_ctx):.2f} and from start time to wait = {(time.time() - st):.2f}")



        yield {"text": '', "status": "Preparing prompt context ..."}
        yield {"text": '', "status": "Preparing partial answer / expert answer context ..."}

        

        

        if google_scholar or perform_web_search:
            web_text = web_text + (("\n\n" + first_four_summary.result()) if first_four_summary.done() and first_four_summary.exception() is None else '')
            web_text = web_text + (("\n\n" + second_four_summary.result()) if second_four_summary.done() and second_four_summary.exception() is None else '')
            web_text = web_text + (("\n\n" + third_four_summary.result()) if third_four_summary.done() and third_four_summary.exception() is None else '')
            if perplexity_results_future is not None:
                random_identifier = str(uuid.uuid4())
                try:
                    perplexity_results = perplexity_results_future.result()
                except Exception as e:
                    traceback.print_exc()
                    perplexity_results = {"text": f"We had an exception in perplexity search. Please try again later. {traceback.format_exc()}"}
                perplexity_text = "\n" + perplexity_results + "\n"
                perplexity_text = f"**Perplexity Search Results :** <div data-toggle='collapse' href='#singleQueryWebSearch-{random_identifier}' role='button'></div> <div class='collapse' id='singleQueryWebSearch-{random_identifier}'>" + perplexity_text + "</div>\n\n"
                yield {"text": perplexity_text, "status": "Perplexity search completed"}
                web_text = web_text + perplexity_text
        probable_prompt_length = get_probable_prompt_length(query["messageText"], web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer, '')
        logger.info(f"previous_messages long: {(len(previous_messages_long.split()))}, previous_messages_very_long: {(len(previous_messages_very_long.split()))}, previous_messages: {len(previous_messages.split())}, previous_messages short: {len(previous_messages_short.split())}")
        yield {"text": f"", "status": "starting answer generation"}
        time_dict["previous_messages_long"] = len(previous_messages_long.split())
        time_dict["previous_messages_very_long"] = len(previous_messages_very_long.split())
        time_dict["previous_messages"] = len(previous_messages.split())
        time_dict["previous_messages_short"] = len(previous_messages_short.split())
        if probable_prompt_length < 90000 and (model_name is None  or "gpt-4o" in model_name or "gpt-4-turbo" in model_name or "sonnet" in model_name or "opus" in model_name or "claude" in model_name or "o1" in model_name or "gemini" in model_name):
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_96k
        elif probable_prompt_length < 48000 and (model_name is None or "gpt-4o" in model_name or "gpt-4-turbo" in model_name or "sonnet" in model_name or "opus" in model_name or "claude" in model_name or "o1" in model_name or "gemini" in model_name):
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_96k
        elif probable_prompt_length < 28000 and (model_name is None or "gpt-4o" in model_name or "gpt-4-turbo" in model_name or "sonnet" in model_name or "opus" in model_name or "claude" in model_name or "o1" in model_name or "gemini" in model_name):
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_96k
        else:
            previous_messages = previous_messages_very_long
            truncate_text = truncate_text_for_gpt4_96k

        user_info_text = ""
        if userData is not None:
            while user_info_text1.done() is False and user_info_text2.done() is False:
                time.sleep(0.5)
            user_info_text = user_info_text1.result() if user_info_text1.done() else user_info_text2.result()
            user_info_text = f"\nUser Preferences and What we know about the user:\n{user_info_text}\n\n"

        memory_pad = f"\nPrevious factual data and details from this conversation:\n{self.memory_pad}\n" if use_memory_pad else ""

        link_result_text, web_text, doc_answer, summary_text, previous_messages, conversation_docs_answer = truncate_text(
            link_result_text, web_text, doc_answer, summary_text, previous_messages,
            query["messageText"], conversation_docs_answer)
        web_text, doc_answer, link_result_text, summary_text, previous_messages, conversation_docs_answer = format_llm_inputs(
            web_text, doc_answer, link_result_text, summary_text, previous_messages,
            conversation_docs_answer)
        time_logger.info(
            f"Time to wait before preparing prompt: {(time.time() - wt_prior_ctx):.2f} and from start time to wait = {(time.time() - st):.2f}")
        yield {"text": '', "status": "Preparing prompt ..."}
        prompt = prompts.chat_slow_reply_prompt.format(query=query["messageText"],
                                                       summary_text=summary_text,
                                                       previous_messages=previous_messages if agent is None else previous_messages_short,
                                                       permanent_instructions=permanent_instructions + memory_pad + coding_rules + user_info_text,
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
        answer += "<answer>\n"
        yield {"text": "<answer>\n", "status": "stage 2 answering in progress"}
        if self.is_cancelled():
            logger.info(f"Response cancelled for conversation {self.conversation_id}")
            answer += "\n\n**Response was cancelled by user**"
            yield {"text": "\n\n**Response was cancelled by user**", "status": "Response cancelled"}
        images = [d.doc_source for d in attached_docs if isinstance(d, ImageDocIndex)]
        ensemble = ((checkboxes["ensemble"] if "ensemble" in checkboxes else False) or isinstance(model_name, (list, tuple))) and agent is None
        from agents.slide_agent import SlideAgent, CodingQuestionSlideAgent
        is_slide_agent = agent is not None and (isinstance(agent, SlideAgent) or isinstance(agent, CodingQuestionSlideAgent))
        storyboard_context = None
        if is_slide_agent:
            # For slide agents, get the complete HTML response at once
            context_llm = CallLLm(self.get_api_keys(), model_name=LONG_CONTEXT_LLM[0], use_gpt4=True, use_16k=True)
            context_prompt = f"""
The conversation history is:
{previous_messages}

Conversation summary is:
{summary}

The user's question is:
{query["messageText"]}

Now please re-contextualize the user's question based on the conversation history and summary. Please make it more detailed, with more context and specific details.

This will be used to generate slides using an LLM. Please write what the user is asking without writing much about the history or like saying "user asked this, conversation was about that and blah blah".
The slides made will help us learn and grasp the topic better.

User's question:
{query["messageText"]}

Please write the question (and only the necessary context) in a way that is easy to understand and grasp the topic better and gives enough context to the LLM to generate slides.

At the end write what we must make slides about as well.
"""
            context_response_future = get_async_future(context_llm, context_prompt, images=images, system=preamble, temperature=0.3, stream=False)
            

            yield {"text": '', "status": "Preparing Slides ..."}
            # slide_html_future = get_async_future(agent, prompt, images=images, system=preamble, temperature=0.3, stream=False)

            storyboard = agent._generate_storyboard("<main-content>\n" + prompt + "\n</main-content>", "8-20")
            storyboard_context = agent._storyboard_to_context(storyboard)
            
        if self.is_cancelled():
            main_ans_gen = iter([])  # empty generator of string
        elif model_name == FILLER_MODEL:
            # main_ans_gen = a generator that yields Acked.
            main_ans_gen = make_stream(["Acked"], do_stream=True)
        elif agent is not None and not is_slide_agent:
            
            if isinstance(agent, (NResponseAgent, ReflectionAgent)):
                if hasattr(agent, "n_responses"):
                    agent.n_responses = 5 if provide_detailed_answers >= 3 else 3
                if hasattr(agent, "model_name"):
                    agent.model_name = model_name
            else:
                agent.model_name = model_name[0].strip() if isinstance(model_name, (list, tuple)) else model_name.strip()
                
                    
            if hasattr(agent, "detail_level"):
                agent.detail_level = provide_detailed_answers
            if hasattr(agent, "timeout"):
                agent.timeout = self.max_time_to_wait_for_web_results * max(provide_detailed_answers, 1)
            
            
            else:
                main_ans_gen = agent(prompt, images=images, system=preamble, temperature=0.3, stream=True)
                if isinstance(main_ans_gen, dict):
                    main_ans_gen = make_stream([main_ans_gen["answer"]], do_stream=True)
                elif inspect.isgenerator(main_ans_gen) or isinstance(main_ans_gen, (types.GeneratorType, collections.abc.Iterator)):
                    pass
                elif not isinstance(main_ans_gen, str):
                    main_ans_gen = make_stream([str(main_ans_gen)], do_stream=True)
                main_ans_gen = buffer_generator_async(main_ans_gen)
            
        else:
            if is_slide_agent and storyboard_context is not None:
                prompt = prompt + "\n\nUse the below outline to write your answer. \n\n" + storyboard_context + "\n"

                context_response = context_response_future.result()

                slide_html_future = get_async_future(agent, "\n\nUser ask is: \n\n<main-content>\n" + context_response + "\n</main-content>", images=images, system=preamble, temperature=0.3, stream=False, storyboard=storyboard)
            if not only_slides:
            
                if ensemble:
                    if isinstance(model_name, (list, tuple)):
                        model_names = model_name
                        improve_model = model_hierarchies(model_names)
                    else:
                        model_names = (EXPENSIVE_LLM[:3] + LONG_CONTEXT_LLM[:1] + [model_name])
                        improve_model = model_name
                    
                    llm = ReflectionAgent(self.get_api_keys(), writer_model=model_names, improve_model=improve_model, outline_model="openai/o1-mini")
                    # llm = CallMultipleLLM(self.get_api_keys(), model_names=model_names, merge=True, merge_model=model_name)
                    main_ans_gen = llm(prompt, images=images, system=preamble, temperature=0.9, stream=True)
                    main_ans_gen = make_stream([main_ans_gen] if isinstance(main_ans_gen, str) else main_ans_gen, do_stream=True)
                else:
                    if "Debug LLM" in preambles:
                        llm = MockCallLLm(self.get_api_keys(), model_name=model_name, use_gpt4=True, use_16k=True)
                    else:
                        llm = CallLLm(self.get_api_keys(), model_name=model_name, use_gpt4=True, use_16k=True)
                    main_ans_gen = llm(prompt, images=images, system=preamble, temperature=0.3, stream=True)
            else:
                main_ans_gen =  iter([])  # empty generator of string

                

                

        main_ans_gen = buffer_generator_async(main_ans_gen)
        
            


        # Process reward evaluation before saving message
        if reward_future is not None:
            yield {"text": "\n", "status": "reward evaluation complete"}
            yield from self._process_reward_evaluation(reward_future)
            yield {"text": "\n", "status": "reward evaluation complete"}
        time_dict["first_word_generated"] = time.time() - st
        logger.info(
            f"""Starting to reply for chatbot, prompt length: {len(enc.encode(prompt))}, llm extracted prior chat info len: {len(enc.encode(prior_chat_summary))}, summary text length: {len(enc.encode(summary_text))}, 
        last few messages length: {len(enc.encode(previous_messages))}, doc answer length: {len(enc.encode(doc_answer))}, 
        conversation_docs_answer length: {len(enc.encode(conversation_docs_answer))},  
        web text length: {len(enc.encode(web_text))}, 
        link result text length: {len(enc.encode(link_result_text))}, 
        final prompt len: {len(enc.encode(prompt))}""")
        time_dict["prompt_length"] = len(enc.encode(prompt))
        time_dict["web_text_length"] = len(enc.encode(web_text))
        time_dict["doc_answer_length"] = len(enc.encode(doc_answer + conversation_docs_answer))
        time_dict["link_result_text_length"] = len(enc.encode(link_result_text))
        time_dict["summary_text_length"] = len(enc.encode(summary_text))
        time_dict["previous_messages_length"] = len(enc.encode(previous_messages))
        et = time.time()
        time_logger.info(f"Time taken to start replying for chatbot: {(et - st):.2f}")
        time_dict["start_reply_final"] = time.time() - st
        if len(doc_answer) > 0:
            logger.debug(f"Doc Answer: {doc_answer}")
        if len(web_text) > 0:
            logger.debug(f"Web text: {web_text}")

        already_executed_code = []
        already_executed_drawio = []
        already_executed_mermaid = []
        # TODO: create coding env if coding is needed.
        code_session = None
        for dcit in main_ans_gen:
            if self.is_cancelled():
                logger.info(f"Response cancelled for conversation {self.conversation_id}")
                answer += "\n\n**Response was cancelled by user**"
                yield {"text": "\n\n**Response was cancelled by user**", "status": "Response cancelled"}
                break
            if isinstance(dcit, dict):
                txt = dcit["text"]
                status = dcit["status"]
            else:
                txt = dcit
                status = "answering in progress"
            yield {"text": txt, "status": status}
            answer += str(txt)
            # extract code between <code action="execute"> and </code> tags if present using regex from within answer string
            drawio_code = extract_drawio(answer)
            if len(drawio_code.strip()) > 0 and drawio_code not in already_executed_drawio:
                already_executed_drawio.append(drawio_code)
                save_path = os.path.join(self.documents_path, f"drawio-{prefix}-{str(mmh3.hash(drawio_code, signed=False))}.xml")
                with open(save_path, "w") as f:
                    f.write(drawio_code)
                file_path = f"/get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}/drawio-{prefix}-{str(mmh3.hash(drawio_code, signed=False))}.xml"
                # diagram_text = f'\n<div class="drawio-diagram" data-diagram-url="{file_path}"></div>\n'
                if "</mxfile>" in drawio_code:
                    drawio_code = re.findall(r'<mxfile.*?>(.*?)</mxfile>', drawio_code, re.DOTALL)[0]
                if "</diagram>" in drawio_code:
                    drawio_code = re.findall(r'<diagram.*?>(.*?)</diagram>', drawio_code, re.DOTALL)[0]
                save_path_for_render = os.path.join(self.documents_path, f"drawio-{prefix}-{str(mmh3.hash(drawio_code, signed=False))}-render.xml")
                file_path_for_render = f"/get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}/drawio-{prefix}-{str(mmh3.hash(drawio_code, signed=False))}-render.xml"
                with open(save_path_for_render, "w") as f:
                    f.write(drawio_code)
                # base64 encoded drawio_code
                # drawio_code = "data:image/svg+xml;base64," + base64.b64encode(drawio_code.encode()).decode()
                diagram_text = f'\n<div id="drawio-diagram-{str(mmh3.hash(drawio_code, signed=False))}" class="drawio-diagram" data-diagram-url="{file_path_for_render}"></div>\n'
                # diagram_text = f'\n<div class="drawio-diagram" data-diagram-data="{compress_and_encode_drawio_xml(drawio_code)}"></div>\n'
                yield {"text": diagram_text, "status": "answering in progress"}
                answer += diagram_text
                
                editable_links = f"\n[Edit Link 1](https://www.draw.io/?url=https://assist-chat.site{file_path}) | [Edit Link 2](https://app.diagrams.net/?url=https://assist-chat.site{file_path}) | [Edit Link 3](https://laingsimon.github.io/render-diagram/relay?chrome=0#https://assist-chat.site{file_path})\n"
                yield {"text": editable_links, "status": "answering in progress"}
                answer += editable_links
                
                download_link = f"\n[Download XML File]({file_path})\n"
                yield {"text": download_link, "status": "answering in progress"}
                answer += download_link
            mermaid_to_execute = extract_last_mermaid(answer)
            if len(mermaid_to_execute.strip()) > 0 and mermaid_to_execute not in already_executed_mermaid and ("\n" in txt and txt.endswith("\n")):
                already_executed_mermaid.append(mermaid_to_execute)
                yield {"text": "\n\n", "status": "answering in progress"}
                yield {"text": mermaid_to_execute, "status": "answering in progress"}
                yield {"text": "\n\n", "status": "answering in progress"}
                answer += ("\n\n" + mermaid_to_execute + "\n\n")
            code_to_execute = extract_code(answer)
            if len(code_to_execute.strip()) > 0 and code_to_execute not in already_executed_code:
                if code_session is None:
                    code_session = PersistentPythonEnvironment()
                already_executed_code.append(code_to_execute)

                success, failure_reason, stdout, stderr, code_string = code_runner_with_retry(query["messageText"],
                                                                                              coding_rules,
                                                                                              CallLLm(self.get_api_keys(), model_name=EXPENSIVE_LLM[0], use_gpt4=True, use_16k=True), CallLLm(self.get_api_keys(), model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=True, use_16k=True),
                                                                                              code_to_execute, session=code_session)
                if success:
                    successfull_code = code_string
                    if successfull_code != code_to_execute:
                        answer = answer.replace(code_to_execute, successfull_code)
                        yield {"text": f"\n```python\n{successfull_code}\n```\n", "status": "answering in progress"}
                        already_executed_code.append(successfull_code)
                    if stdout.strip() != "":
                        stdout = "\n" + f"```shell\n{stdout}\n```\n"
                        yield {"text": stdout, "status": "answering in progress"}
                        answer += stdout
                    # look in self.documents_path directory if any file with start as plot_prefix exists, if yes, then send that file as image in markdown format.

                    files = list(set([f for f in os.listdir(self.documents_path) if f.startswith(plot_prefix)]))
                    for f in files:
                        image_path = f"get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}/{f}"
                        # TODO: url_encode_image_path with urllib
                        image_path = image_path.replace(" ", "%20")
                        image_md = f"![{f}]({image_path})"
                        yield {"text": image_md, "status": "answering in progress"}
                        answer += image_md

                        yield {"text": "\n", "status": "answering in progress"}
                        answer += "\n"

                    files = list(set([f for f in os.listdir(self.documents_path) if f.startswith(file_prefix)]))
                    for f in files:
                        file_path = f"get_conversation_output_docs/{COMMON_SALT_STRING}/{self.conversation_id}/{f}"
                        download_link = f"[Download {f}]({file_path})"
                        yield {"text": download_link, "status": "answering in progress"}
                        answer += download_link
                        yield {"text": "\n", "status": "answering in progress"}
                        answer += "\n"
                else:
                    stderr = "\n" + f"```shell\n{stderr}\n{failure_reason}\n```\n"
                    yield {"text": stderr, "status": "answering in progress"}
                    answer += stderr


        answer_temp = answer
        while True:
            mermaid_to_execute = extract_last_mermaid(answer_temp)
            if len(mermaid_to_execute.strip()) > 0 and mermaid_to_execute not in already_executed_mermaid:
                already_executed_mermaid.append(mermaid_to_execute)
                yield {"text": "\n\n", "status": "answering in progress"}
                yield {"text": mermaid_to_execute, "status": "answering in progress"}
                yield {"text": "\n\n", "status": "answering in progress"}
                answer += ("\n\n" + mermaid_to_execute + "\n\n")
                answer_temp = answer_temp.replace(mermaid_to_execute, "")
            else:
                break
        
        self.clear_cancellation()

        if is_slide_agent:
            # "User's question:\n" + context_response_future.result() + 
            
            slide_html = slide_html_future.result()
            # Wrap the slide HTML with a special marker for UI detection
            slide_response = f"\n\n<slide-presentation>\n{slide_html}\n</slide-presentation>\n\n"
            yield {"text": slide_response, "status": "answering in progress"}
            answer += slide_response

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
        get_async_future(self.persist_current_turn, original_user_query, answer, message_config, previous_messages_long, summary, full_doc_texts, persist_or_not, past_message_ids)
        message_ids = self.get_message_ids(query["messageText"], answer)
        yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}
        stats = collapsible_wrapper(yaml.dump(time_dict, default_flow_style=False), header="Time taken to reply for chatbot", show_initially=False, add_close_button=False)
        for chunk in stats:
            yield {"text": chunk, "status": "saving answer ...", "message_ids": message_ids}
        yield {"text": "\n\n", "status": "saving answer ...", "message_ids": message_ids}

    
    def detect_previous_message_type(self):
        pass

    def get_last_ten_messages(self):
        return self.get_field("messages")[-10:]
    
    def get_message_list(self):
        msg_list = self.get_field("messages")
        return msg_list
    
    def get_metadata(self):
        self.set_memory_if_None()
        memory = self.get_field("memory")

        summary_till_now = self.running_summary
        if "title" not in memory:
            memory["title"] = ""
        title = memory["title"]
        return dict(conversation_id=self.conversation_id, user_id=self.user_id, title=title,
                    summary_till_now=summary_till_now, domain=self.domain,
                    last_updated=memory["last_updated"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(memory["last_updated"], datetime) else memory["last_updated"])

    def _initiate_reward_evaluation(self, reward_level, query_text, checkboxes, previous_messages_long, summary):
        """
        Initiates async reward evaluation if reward level is non-zero.
        Returns future object or None if reward evaluation is not needed.
        """
        if reward_level == 0:
            return None
        
        def sync_reward_evaluation_with_update():
            """
            Inner sync function that calls reward LLM and updates persistent context_data
            """
            try:
                # Prepare user info from available data
                user_info = f"User ID: {self.user_id}, Domain: {self.domain}"
                if checkboxes.get("permanentText"):
                    user_info += f", Instructions: {checkboxes['permanentText'][:200]}..."
                
                # Get conversation history length
                messages = self.get_field("messages") or []
                conversation_length = len(messages)
                
                # Call reward decision LLM synchronously with persistent context_data
                reward_decision = get_reward_decision(
                    conversation_history=previous_messages_long,
                    current_user_text=query_text,
                    reward_level_dialer=reward_level,
                    conversation_summary=summary,
                    conversation_length=conversation_length,
                    user_info=user_info,
                    keys=self.get_api_keys(),
                    context_data=self.context_data  # Use persistent context_data
                )
                
                # Update persistent context_data based on reward decision
                self._update_context_from_reward(reward_decision)
                
                return reward_decision
                
            except Exception as e:
                error_logger.error(f"[Reward System] Error in sync reward evaluation: {str(e)}")
                return {
                    "reward_type": "none",
                    "reward_level": "FAIR",
                    "reward_message": "Evaluation error occurred.",
                    "overall_assessment": "Error in assessment system",
                    "reasoning": f"System error: {str(e)}",
                    "dialer_setting": reward_level,
                    "judge_personality": "ERROR_STATE",
                    "evaluation_timestamp": time.time(),
                    "confidence_level": "low"
                }
        
        # Start async reward evaluation using the inner sync function
        reward_future = get_async_future(sync_reward_evaluation_with_update)
        
        return reward_future
    
    def _update_context_from_reward(self, reward_decision):
        """
        Updates persistent context_data based on reward decision
        """
        try:
            reward_type = reward_decision.get("reward_type", "none")
            reward_level = reward_decision.get("reward_level", "FAIR")
            
            # Map reward levels to point values
            reward_points = {
                "EXCELLENT": 10, "VERY_GOOD": 7, "GOOD": 5, "FAIR": 3, "BASIC": 1
            }
            penalty_points = {
                "MINOR": -1, "MODERATE": -3, "SIGNIFICANT": -5, "MAJOR": -7, "CRITICAL": -10
            }
            
            # Update score based on reward/penalty
            points = 0
            if reward_type == "reward":
                points = reward_points.get(reward_level, 1)
                self.context_data["total_rewards"] += 1
            elif reward_type == "penalty":
                points = penalty_points.get(reward_level, -1)
                self.context_data["total_penalties"] += 1
            
            # Update context data
            updates = {
                "current_score": self.context_data["current_score"] + points,
                "last_reward_timestamp": time.time(),
            }
            
            # Add to reward history (keep last 10)
            reward_history_entry = {
                "timestamp": time.time(),
                "reward_type": reward_type,
                "reward_level": reward_level,
                "points": points,
                "message": reward_decision.get("reward_message", "")
            }
            
            self.context_data["reward_history"].append(reward_history_entry)
            if len(self.context_data["reward_history"]) > 10:
                self.context_data["reward_history"] = self.context_data["reward_history"][-10:]
            
            # Add recent achievements (if reward)
            if reward_type == "reward" and reward_level in ["EXCELLENT", "VERY_GOOD"]:
                achievement = f"{reward_level}: {reward_decision.get('reward_message', '')}"
                self.context_data["recent_achievements"].append(achievement)
                # Keep only last 5 achievements
                if len(self.context_data["recent_achievements"]) > 5:
                    self.context_data["recent_achievements"] = self.context_data["recent_achievements"][-5:]
            
            # Update context data
            self.update_context_data(updates)
            
            time_logger.info(f"[Reward System] Context updated - Score: {self.context_data['current_score']}, "
                           f"Total Rewards: {self.context_data['total_rewards']}, "
                           f"Total Penalties: {self.context_data['total_penalties']}")
            
        except Exception as e:
            error_logger.error(f"[Reward System] Error updating context from reward: {str(e)}")

    def _initiate_doubt_reward_evaluation(self, reward_level, doubt_text, message_id):
        """
        Initiates async reward evaluation for doubt questions if reward level is non-zero.
        Returns future object or None if reward evaluation is not needed.
        """
        if reward_level == 0:
            return None
        
        def sync_doubt_reward_evaluation_with_update():
            """
            Inner sync function that calls reward LLM for doubt evaluation and updates persistent context_data
            """
            try:
                # Get the target message for context
                target_message, context_messages = self.get_context_around_message(message_id, 
                                                                                  context_messages_before=2, 
                                                                                  context_messages_after=1)
                
                # Build context for doubt evaluation
                doubt_context = ""
                if target_message:
                    doubt_context += f"**Target Message Being Asked About:**\n{target_message['text']}\n\n"
                
                if context_messages:
                    doubt_context += "**Surrounding Context:**\n"
                    for msg in context_messages:
                        sender_label = "User" if msg["sender"] == "user" else "Assistant"
                        is_target = msg["message_id"] == message_id
                        marker = " ← [TARGET]" if is_target else ""
                        doubt_context += f"{sender_label}{marker}: {msg['text'][:200]}...\n"
                
                # Prepare user info from available data
                user_info = f"User ID: {self.user_id}, Domain: {self.domain}"
                user_info += f"\nDoubt Context: User is asking about message {message_id}"
                
                # Get conversation history length
                messages = self.get_field("messages") or []
                conversation_length = len(messages)
                
                # Get conversation summary
                summary = self.running_summary if self.running_summary else "No summary available"
                if isinstance(summary, list):
                    summary = "\n".join(summary)
                
                # Build conversation history for context (last 1000 chars)
                conversation_history = doubt_context
                if len(conversation_history) > 1000:
                    conversation_history = conversation_history[-1000:]
                
                # Call reward decision LLM synchronously with persistent context_data
                from base import get_reward_decision
                reward_decision = get_reward_decision(
                    conversation_history=conversation_history,
                    current_user_text=doubt_text,
                    reward_level_dialer=reward_level,
                    conversation_summary=summary,
                    conversation_length=conversation_length,
                    user_info=user_info,
                    keys=self.get_api_keys(),
                    context_data=self.context_data  # Use persistent context_data
                )
                
                # Update persistent context_data based on reward decision
                self._update_context_from_reward(reward_decision)
                
                return reward_decision
                
            except Exception as e:
                error_logger.error(f"[Doubt Reward System] Error in sync doubt reward evaluation: {str(e)}")
                return {
                    "reward_type": "none",
                    "reward_level": "FAIR",
                    "reward_message": "Doubt evaluation error occurred.",
                    "overall_assessment": "Error in doubt assessment system",
                    "reasoning": f"System error: {str(e)}",
                    "dialer_setting": reward_level,
                    "judge_personality": "ERROR_STATE",
                    "evaluation_timestamp": time.time(),
                    "confidence_level": "low"
                }
        
        # Start async reward evaluation using the inner sync function
        from base import get_async_future
        reward_future = get_async_future(sync_doubt_reward_evaluation_with_update)
        
        return reward_future

    def _process_reward_evaluation(self, reward_future):
        """
        Processes completed reward evaluation and yields gamified output.
        Context data has already been updated by the inner sync function.
        """
        if reward_future is None:
            return
            
        try:
            # Get reward decision result (context_data already updated by inner function)
            reward_decision = reward_future.result()
            
            # Convert to gamified output with context info
            gamified_reward = apply_reward_gamification(reward_decision)
            
            # Add current score info to the gamified output
            current_score = self.context_data["current_score"]
            total_rewards = self.context_data["total_rewards"]
            total_penalties = self.context_data["total_penalties"]
            
            score_info = f"\n**Session Progress:** Score: {current_score} | Rewards: {total_rewards} | Penalties: {total_penalties}\n"
            gamified_reward += score_info
            
            # Yield the reward feedback
            yield {"text": gamified_reward, "status": "reward evaluation complete"}
            
            # Log reward decision with context for debugging
            time_logger.info(f"[Reward System] Applied {reward_decision.get('reward_type', 'none')} "
                           f"{reward_decision.get('reward_level', 'N/A')} - "
                           f"{reward_decision.get('judge_personality', 'N/A')} | "
                           f"Score: {current_score} | Session: R{total_rewards}/P{total_penalties}")
            
        except Exception as e:
            error_logger.error(f"[Reward System] Error processing reward evaluation: {str(e)}")
            # Yield a neutral message on error
            yield {"text": "⚙️ **Evaluation Processing** Assessment completed.\n\n", 
                   "status": "reward evaluation error"}

    def delete_last_turn(self):
        messages = self.get_field("messages")
        messages = messages[:-2]
        self.set_messages_field(messages, overwrite=True)
        memory = self.get_field("memory")
        memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        memory["running_summary"] = memory["running_summary"][:-1]
        self.running_summary = "".join(memory["running_summary"][-1:])
        if len(messages) > 3:
            previous_messages_text = messages[-4]["text"] + "\n\n" + messages[-3]["text"]
        else:
            previous_messages_text = ""
        if len(messages) >= 2:
            nqs = self.create_next_question_suggestions(messages[-2]["text"], messages[-1]["text"], previous_messages_text, "".join(memory["running_summary"][-1:]))
        else:
            nqs = []
        self.set_next_question_suggestions(nqs)

        self.set_field("memory", memory, overwrite=True)


    
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

    def replace_message_text_with_prompt(self, message, field_prompt):
        if field_prompt == "IdeaNovelty":
            return prompts.idea_novelty_prompt.format(research_idea=message)
        elif field_prompt == "IdeaComparison":
            return prompts.idea_comparison_prompt.format(research_idea=message)
        elif field_prompt == "IdeaFleshOut":
            return prompts.idea_flesh_out_prompt.format(research_idea=message)
        elif field_prompt == "IdeaDatasetsAndExperiments":
            return prompts.idea_datasets_and_experiments_prompt.format(research_idea=message)
        elif field_prompt == "IdeaAblationsAndResearchQuestions":
            return prompts.idea_ablations_and_research_questions_prompt.format(research_idea=message)
        elif field_prompt == "ResearchPreventRejections":
            return prompts.research_prevent_rejections_prompt.format(research_idea=message)
        elif field_prompt == "PaperMethod":
            return prompts.paper_details_map["methodology"]
        else:
            return message

    def get_message_by_id(self, message_id):
        """Retrieve a specific message by its message_id"""
        messages = self.get_field("messages")
        for i, message in enumerate(messages):
            if message["message_id"] == message_id:
                return message, i
        return None, -1

    def get_context_around_message(self, message_id, context_messages_before=3, context_messages_after=1):
        """Get context around a specific message including the message itself"""
        messages = self.get_field("messages")
        target_message = None
        target_index = -1
        
        # Find the target message
        for i, message in enumerate(messages):
            if message["message_id"] == message_id:
                target_message = message
                target_index = i
                break
        
        if target_message is None:
            return None, []
        
        # Get context messages
        start_index = max(0, target_index - context_messages_before)
        end_index = min(len(messages), target_index + context_messages_after + 1)
        context_messages = messages[start_index:end_index]
        
        return target_message, context_messages

    def is_doubt_clearing_cancelled(self):
        """Check if doubt clearing has been cancelled"""
        from base import doubt_cancellation_requests
        if self.conversation_id in doubt_cancellation_requests:
            return doubt_cancellation_requests[self.conversation_id].get('cancelled', False)
        return False

    def clear_doubt_clearing_cancellation(self):
        """Clear doubt clearing cancellation flag"""
        from base import doubt_cancellation_requests
        if self.conversation_id in doubt_cancellation_requests:
            del doubt_cancellation_requests[self.conversation_id]

    def clear_doubt(self, message_id, doubt_text="", doubt_history=None, reward_level=0):
        """Clear a doubt about a specific message - streaming response"""
        from call_llm import CallLLm
        
        import traceback
        import time
        
        try:
            # Clear any existing cancellation at the start
            self.clear_doubt_clearing_cancellation()
            
            # Initialize reward evaluation if reward level is non-zero
            reward_future = None
            if reward_level != 0:
                reward_future = self._initiate_doubt_reward_evaluation(reward_level, doubt_text, message_id)
            
            # Get the target message and surrounding context
            target_message, context_messages = self.get_context_around_message(message_id, 
                                                                              context_messages_before=4, 
                                                                              context_messages_after=2)
            
            if target_message is None:
                yield "Error: Message not found. Please check the message ID and try again."
                return
            
            # Get conversation summary and history
            conversation_summary = self.running_summary
            # conversation_history = self.get_conversation_history()
            
            # Build the context for doubt clearing
            context_text = ""
            
            # Add conversation summary
            if conversation_summary and len(conversation_summary) > 0:
                if isinstance(conversation_summary, list):
                    summary_text = "\n".join(conversation_summary)
                else:
                    summary_text = str(conversation_summary)
                context_text += f"# Conversation Summary\n\n{summary_text}\n\n"
            
            # Add doubt history if this is a follow-up
            if doubt_history and len(doubt_history) > 0:
                context_text += "# Previous Doubt History\n\n"
                context_text += "This is a follow-up question. Here's the previous doubt conversation:\n\n"
                for i, doubt_record in enumerate(doubt_history):
                    context_text += f"**Previous Doubt {i+1}:**\n"
                    context_text += f"User asked: {doubt_record['doubt_text']}\n"
                    context_text += f"Assistant answered: {doubt_record['doubt_answer']}\n\n"
                context_text += f"**Current Follow-up Question:** {doubt_text}\n\n"
            
            # Add context messages
            if context_messages:
                context_text += "# Relevant Context Messages\n\n"
                for i, msg in enumerate(context_messages):
                    sender_label = "**User**" if msg["sender"] == "user" else "**Assistant**"
                    is_target = msg["message_id"] == message_id
                    marker = " ← **[TARGET MESSAGE]**" if is_target else ""
                    context_text += f"{sender_label}{marker}:\n{msg['text']}\n\n"
            
            # Build the doubt clearing prompt
            doubt_prompt = f"""You are an AI assistant helping to clear doubts about a specific message in a conversation. 

{context_text}

# User's Doubt/Question
The user has a specific doubt or question about the message marked as **[TARGET MESSAGE]** above:

**User's Doubt:** {doubt_text if doubt_text.strip() else "Please explain this message in more detail."}

# Your Task
Please provide a clear, comprehensive explanation that addresses the user's doubt. Consider:

1. **Context**: Use the conversation history and surrounding messages to provide relevant context
2. **Clarity**: Explain any complex concepts, terminology, or reasoning mentioned in the target message
3. **Completeness**: Address all aspects of the user's doubt thoroughly
4. **Examples**: Provide examples or analogies where helpful
5. **Brieffly**: Answer the question in a few sentences.
6. Don't use latex or math notation. We can't render latex and math notation. Use single backticks for single line code blocks and triple backticks for multi-line code blocks.

Please provide your explanation in a clear, structured format that directly addresses the user's doubt."""

            # Initialize the LLM with appropriate model
            api_keys = self.get_api_keys()
            llm = CallLLm(api_keys, model_name=CHEAP_LONG_CONTEXT_LLM[0], use_gpt4=False, use_16k=False)
            
            # Generate streaming response
            response_stream = llm(
                doubt_prompt, 
                images=[], 
                temperature=0.3, 
                stream=True, 
                max_tokens=2000,
                system="You are a helpful AI assistant specializing in clarifying doubts and explaining complex concepts clearly and thoroughly."
            )
            
            # Stream the response
            for chunk in response_stream:
                # Check for cancellation before processing each chunk
                if self.is_doubt_clearing_cancelled():
                    logger.info(f"Doubt clearing cancelled for conversation {self.conversation_id}")
                    yield "\n\n**Doubt clearing was cancelled by user**"
                    break
                if chunk:
                    yield chunk
            
            # Process reward evaluation if it was initiated
            if reward_future is not None:
                yield "\n\n"
                for reward_chunk in self._process_reward_evaluation(reward_future):
                    yield reward_chunk.get("text", "")
            
            # Clear cancellation flag after completion
            self.clear_doubt_clearing_cancellation()
                    
        except Exception as e:
            error_msg = f"Error clearing doubt: {str(e)}"
            logger.error(f"Error in clear_doubt for message {message_id}: {error_msg}")
            logger.error(traceback.format_exc())
            yield f"I apologize, but I encountered an error while trying to clear your doubt: {error_msg}"


class TemporaryConversation(Conversation):
    def __init__(self) -> None:
        self.conversation_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        memory = {  "title": 'Start the Conversation',
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "running_summary":[], # List of strings, each string is a running summary of chat till now.
                }
        messages = list() # list of message objects of structure like `{"message_id": "one", "text": "Hello", "sender": "user/model", "user_id": "user_1", "conversation_id": "conversation_id"},`
        self.set_field("memory", memory)
        self.set_messages_field(messages)
        self.set_field("uploaded_documents_list", list()) # just a List[str] of doc index ids

    def add_uploaded_document(self, pdf_url):
        pass

    def documents_path(self):
        pass

    def save_local(self):
        pass

    def get_field(self, top_key):
        if getattr(self, top_key, None) is not None:
            return getattr(self, top_key, None)
        else:
            return None

    def set_field(self, top_key, value, overwrite=False):
        tk = self.get_field(top_key)
        assert (type(tk) == type(value) or tk is None) or (
                    isinstance(tk, (tuple, list)) and isinstance(value, (tuple, list)))
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
            
    def add_to_memory_pad_from_response(self, *args, **kwargs):
        pass



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








def truncate_text_for_gpt4_96k(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer):
    return truncate_text(link_result_text, web_text, doc_answer, summary_text, previous_messages, user_message, conversation_docs_answer, model="gpt-4-96k")


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
        l1 = 75000
        l2 = 30000
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



def model_name_to_canonical_name(model_name):
    model_name = model_name.strip()
    if model_name == "perplexity/sonar-deep-research":
        model_name = "perplexity/sonar-deep-research"
    elif model_name == "openai/gpt-4.1":
        model_name = "openai/gpt-4.1"
    elif model_name == "gpt-4.1":
        model_name = "gpt-4.1"
    elif model_name == "anthropic/claude-opus-4" or model_name == "anthropic/claude-opus-4.1" or model_name == "Opus 4.1":
        model_name = "anthropic/claude-opus-4.1"
    elif model_name == "anthropic/claude-sonnet-4" or model_name == "Claude Sonnet 4" or model_name == "Sonnet 4":
        model_name = "anthropic/claude-sonnet-4"
    elif model_name == "anthropic/claude-4-opus-20250522":
        model_name = "anthropic/claude-4-opus-20250522"
    elif model_name == "anthropic/claude-4-sonnet-20250522":
        model_name = "anthropic/claude-4-sonnet-20250522"
    elif model_name == "x-ai/grok-3-beta":
        model_name = "x-ai/grok-3-beta"
    elif model_name == "x-ai/grok-4":
        model_name = "x-ai/grok-4"
    elif model_name == "mistralai/devstral-medium":
        model_name = "mistralai/devstral-medium"
    elif model_name == "perplexity/sonar-pro":
        model_name = "perplexity/sonar-pro"
    elif model_name == "perplexity/sonar-reasoning-pro":
        model_name = "perplexity/sonar-reasoning-pro"
    elif model_name == "openai/gpt-4o-search-preview":
        model_name = "openai/gpt-4o-search-preview"
    elif model_name == "openai/gpt-4o-mini-search-preview":
        model_name = "openai/gpt-4o-mini-search-preview"
    elif model_name == "Gemini-2.5-pro-preview":
        model_name = "google/gemini-2.5-pro-preview"
    elif model_name == "Gemini-2.5-pro":
        model_name = "google/gemini-2.5-pro"
    elif model_name == "o1":
        model_name = "o1"
    elif model_name == "o3":
        model_name = "o3"
    elif model_name == "o3-mini":
        model_name = "o3-mini"
    elif model_name == "o3-pro":
        model_name = "o3-pro"
    elif model_name == "o4-mini-high":
        model_name = "openai/o4-mini-high"
    elif model_name == "o4-mini-deep-research":
        model_name = "o4-mini-deep-research"
    elif model_name == "o3-deep-research":
        model_name = "o3-deep-research"
    elif model_name == "openai/o3":
        model_name = "openai/o3"
    
    elif model_name == "o1-pro":
        model_name = "o1-pro"
    elif model_name == "openai/o1-pro":
        model_name = "openai/o1-pro"
    elif model_name == "cohere/command-a":
        model_name = "cohere/command-a"
    elif model_name == "gpt-4.5-preview":
        model_name = "gpt-4.5-preview"
    elif model_name == "Claude Sonnet 3.7 Thinking":
        model_name = "anthropic/claude-3.7-sonnet:thinking"
    elif model_name == "o1-hard":
        model_name = "o1-hard"
    elif model_name == "o1-easy":
        model_name = "o1-easy"
    elif model_name == "openai/o1":
        model_name = "openai/o1"
    elif model_name == "gpt-4-turbo":
        model_name = "gpt-4-turbo"
    elif model_name == "gpt-4o":
        model_name = "gpt-4o"
    elif model_name == "openai/gpt-4.5-preview":
        model_name = "openai/gpt-4.5-preview"
    elif model_name == "Command-r+":
        model_name = "cohere/command-r-plus-08-2024"
    elif model_name == "gpt-4-32k":
        model_name = "openai/gpt-4-32k"
    elif model_name == "gpt-4-32k-0314":
        model_name = "gpt-4-32k-0314"
    elif model_name == "gpt-4-0314":
        model_name = "gpt-4-0314"
    elif model_name == "Claude Opus":
        model_name = "anthropic/claude-3-opus:beta"
    elif model_name == "Claude Sonnet 3.5":
        model_name = "anthropic/claude-3.5-sonnet:beta"
    elif model_name == "Claude Sonnet 3.7":
        model_name = "anthropic/claude-3.7-sonnet"
    elif model_name == "Mistral Large":
        model_name = "mistralai/mistral-large"
    elif model_name == "Pixtral Large":
        model_name = "mistralai/pixtral-large-2411"
    elif model_name == "DeepSeek-V2.5 Chat":
        model_name = "deepseek/deepseek-chat"
    elif model_name == "deepseek/deepseek-coder":
        model_name = "deepseek/deepseek-coder"
    elif model_name == "Qwen 2":
        model_name = "qwen/qwen-2.5-72b-instruct"
    elif model_name == "Jamba":
        model_name = "ai21/jamba-1-5-large"
    elif model_name == "llama-3.1-70b":
        model_name = "meta-llama/llama-3.1-70b-instruct"
    elif model_name == "llama-3.1-405b":
        model_name = "meta-llama/llama-3.1-405b-instruct"
    elif model_name == "Hermes llama-3.1-405b":
        model_name = "nousresearch/hermes-3-llama-3.1-405b"
    elif model_name == "Yi Large":
        model_name = "01-ai/yi-large"

    elif model_name == "PPX 405B Online":
        model_name = "perplexity/llama-3.1-sonar-huge-128k-online"

    elif model_name == "Gemini 1.5":
        model_name = "google/gemini-pro-1.5"
    elif model_name == "openai/o1-preview":
        model_name = "openai/o1-preview"
    elif model_name == "openai/o1-mini":
        model_name = "openai/o1-mini"

    elif model_name == "o1-preview":
        model_name = "o1-preview"
    elif model_name == "o1-mini":
        model_name = "o1-mini"
    elif model_name == "minimax/minimax-01":
        model_name = "minimax/minimax-01"
    elif model_name == "qwen/qvq-72b-preview":
        model_name = "qwen/qvq-72b-preview"
    elif model_name == "meta-llama/llama-3.2-90b-vision-instruct":
        model_name = "meta-llama/llama-3.2-90b-vision-instruct"
    elif model_name == "openai/chatgpt-4o-latest":
        model_name = "openai/chatgpt-4o-latest"
    elif model_name == "sao10k/l3.3-euryale-70b":
        model_name = "sao10k/l3.3-euryale-70b"
    elif model_name == "latitudegames/wayfarer-large-70b-llama-3.3":
        model_name = "latitudegames/wayfarer-large-70b-llama-3.3"
    elif model_name == "thedrummer/anubis-pro-105b-v1":
        model_name = "thedrummer/anubis-pro-105b-v1"
    elif model_name == "thedrummer/anubis-70b-v1.1":
        model_name = "thedrummer/anubis-70b-v1.1"
    elif model_name == "moonshotai/kimi-k2":
        model_name = "moonshotai/kimi-k2"
    elif model_name == "steelskull/l3.3-electra-r1-70b":
        model_name = "steelskull/l3.3-electra-r1-70b"
    elif model_name == "openai/gpt-4o-mini":
        model_name = "openai/gpt-4o-mini"

    elif model_name == "eva-unit-01/eva-qwen-2.5-72b":
        model_name = "eva-unit-01/eva-qwen-2.5-72b"
    elif model_name == "google/gemini-2.5-flash-preview":
        model_name = "google/gemini-2.5-flash-preview"
    elif model_name == "qwen/qwen3-coder" or model_name == "Qwen3-Coder":
        model_name = "qwen/qwen3-coder"
    elif model_name == "google/gemini-2.5-flash":
        model_name = "google/gemini-2.5-flash"
    elif model_name == "google/gemini-2.5-flash-lite-preview-06-17":
        model_name = "google/gemini-2.5-flash-lite-preview-06-17"
    elif model_name == "google/gemini-2.5-flash-lite":
        model_name = "google/gemini-2.5-flash-lite"
    elif model_name == "google/gemini-2.0-flash-lite-001":
        model_name = "google/gemini-2.0-flash-lite-001"
    elif model_name == "x-ai/grok-3-mini":
        model_name = "x-ai/grok-3-mini"
    elif model_name == "minimax/minimax-m1":
        model_name = "minimax/minimax-m1"
    elif model_name == "eva-unit-01/eva-llama-3.33-70b":
        model_name = "eva-unit-01/eva-llama-3.33-70b"
    elif model_name == "nousresearch/hermes-3-llama-3.1-405b":
        model_name = "nousresearch/hermes-3-llama-3.1-405b"
    elif model_name == "neversleep/llama-3.1-lumimaid-70b":
        model_name = "neversleep/llama-3.1-lumimaid-70b"
    elif model_name == "raifle/sorcererlm-8x22b":
        model_name = "raifle/sorcererlm-8x22b"
    elif model_name == "qwen/qwen3-235b-a22b":
        model_name = "qwen/qwen3-235b-a22b"
    elif model_name == "deepseek/deepseek-prover-v2":
        model_name = "deepseek/deepseek-prover-v2"
    elif model_name == "deepseek/deepseek-chat-v3-0324":
        model_name = "deepseek/deepseek-chat-v3-0324"
    elif model_name == "openai/gpt-4.1-mini":
        model_name = "openai/gpt-4.1-mini"
    elif model_name == "gpt-5":
        model_name = "gpt-5"
    elif model_name == "openai/gpt-5-chat":
        model_name = "openai/gpt-5-chat"
    
    elif model_name in CHEAP_LONG_CONTEXT_LLM or model_name in CHEAP_LLM or model_name in LONG_CONTEXT_LLM or model_name in EXPENSIVE_LLM or model_name in VERY_CHEAP_LLM:
        pass
    
        
    elif model_name == FILLER_MODEL:
        model_name = FILLER_MODEL
    else:
        raise ValueError(f"Model name {model_name} not found in the list")
    return model_name
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
    
    
def model_hierarchies(model_names: List[str]):
    if "gpt-5" in model_names:
        improve_model = "gpt-5"
    elif "openai/gpt-5-chat" in model_names:
        improve_model = "openai/gpt-5-chat"
    
    if "x-ai/grok-3-beta" in model_names:
        improve_model = "x-ai/grok-3-beta"
    elif "x-ai/grok-3" in model_names:
        improve_model = "x-ai/grok-3"
    elif "x-ai/grok-4" in model_names:
        improve_model = "x-ai/grok-4"
    elif "mistralai/devstral-medium" in model_names:
        improve_model = "mistralai/devstral-medium"
    
    elif "openai/chatgpt-4o-latest" in model_names:
        improve_model = "openai/chatgpt-4o-latest"
    
    elif "anthropic/claude-3.7-sonnet" in model_names:
        improve_model = "anthropic/claude-3.7-sonnet"
    elif "anthropic/claude-opus-4" in model_names or "Opus 4" in model_names or "Claude Opus 4" in model_names:
        improve_model = "anthropic/claude-sonnet-4"
    elif "anthropic/claude-sonnet-4" in model_names or "Claude Sonnet 4" in model_names or "Sonnet 4" in model_names:
        improve_model = "anthropic/claude-sonnet-4"
    elif "anthropic/claude-3.5-sonnet:beta" in model_names:
        improve_model = "anthropic/claude-3.5-sonnet:beta"
    elif "gpt-4o" in model_names:
        improve_model = "gpt-4o"
    elif "anthropic/claude-3.7-sonnet:thinking" in model_names:
        improve_model = "anthropic/claude-3.7-sonnet"
    elif "openai/gpt-4.1" in model_names:
        improve_model = "openai/gpt-4.1"

    elif any(c.startswith("openai") for c in model_names):
        improve_model = "openai/chatgpt-4o-latest"
    
    else:
        improve_model = EXPENSIVE_LLM[0]
    return improve_model
