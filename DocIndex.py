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
import json
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
from DataModel import *
from sqlalchemy.orm.attributes import flag_modified

import openai
import tiktoken
from sqlalchemy.orm.session import object_session


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
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import TextLoader
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

class DocFAISS(FAISS):
    
    def merge_from(self, target: FAISS) -> None:
        """Merge another FAISS object with the current one.

        Add the target FAISS to the current one.

        Args:
            target: FAISS object you wish to merge into the current one

        Returns:
            None.
        """
        if not isinstance(self.docstore, AddableMixin):
            raise ValueError("Cannot merge with this type of docstore")
        # Numerical index for target docs are incremental on existing ones
        starting_len = len(self.index_to_docstore_id)

        # Merge two IndexFlatL2
        self.index.merge_from(target.index)

        # Get id and docs from target FAISS object
        full_info = []
        existing_id = set([target_id for i, target_id in self.index_to_docstore_id.items()])
        for i, target_id in target.index_to_docstore_id.items():
            if target_id in existing_id:
                continue
            doc = target.docstore.search(target_id)
            if not isinstance(doc, Document):
                raise ValueError("Document should be returned")
            full_info.append((starting_len + i, target_id, doc))

        # Add information to docstore and index_to_docstore_id.
        self.docstore.add({_id: doc for _, _id, doc in full_info})
        index_to_id = {index: _id for index, _id, _ in full_info}
        self.index_to_docstore_id.update(index_to_id)

def create_index_faiss(chunks, embed_model, doc_id=None):
    from langchain.schema import Document as LangchainDocument
    if doc_id is None:
        doc_id = [""] * len(chunks)
    elif isinstance(doc_id, (str, int)):
        doc_id = [doc_id] * len(chunks)
    else:
        assert len(doc_id) == len(chunks) and isinstance(doc_id, (list, tuple))
        doc_id = [int(d) for d in doc_id]
    chunks = [LangchainDocument(page_content=str(c), metadata={"order": i}) for i, c in enumerate(chunks)]
    for ix, chunk in enumerate(chunks):
        chunk.metadata["next"] = None if ix == len(chunks)-1 else chunks[ix + 1]
        chunk.metadata["previous"] = None if ix == 0 else chunks[ix - 1]
        chunk.metadata["doc_id"] = doc_id[ix]
        chunk.metadata["index"] = ix
    db = DocFAISS.from_documents(chunks, embed_model)
    return db

class DocIndex:
    def __init__(self):
        self.result_cutoff = 2
        self._indices = None
        self._openai_embed = None
        self._document = None
        
        
    @property
    def indices(self):
        assert self._indices is not None
        return self._indices
    
    @indices.setter
    def indices(self, args):
        if isinstance(args, dict):
            self._indices = args
        elif isinstance(args[0], dict) and len(args) == 1:
            self._indices = args[0]
        else:
            chunks, small_chunks, openai_embed = args
            self._indices = dict(dqna_index = create_index_faiss([''], openai_embed, 
                                                                 doc_id=self.doc_id, ), 
                                raw_index = create_index_faiss(chunks, openai_embed, doc_id=self.doc_id,), 
                                summary_index = create_index_faiss([''], openai_embed, doc_id=self.doc_id,), 
                                small_chunk_index = create_index_faiss(small_chunks, openai_embed, doc_id=self.doc_id,), 
                                chunks=chunks, small_chunks=small_chunks, chunked_summary=[''], running_summary='', )
        
    @property
    def doc_id(self):
        return self.document.id
    
    @property
    def document(self)->Document:
        return self._document
    
    @document.setter
    def document(self, document: Document):
        assert isinstance(document, Document)
        self._document = document
    
    @property
    def streaming_followup(self):
        return prompts["DocIndex"]["streaming_followup"]
    
    @property
    def streaming_more_details(self):
        return prompts["DocIndex"]["streaming_more_details"]
    
    @property
    def short_streaming_answer_prompt(self):
        return prompts["DocIndex"]["short_streaming_answer_prompt"]
    
    @property
    def running_summary_prompt(self):
        return prompts["DocIndex"]["running_summary_prompt"]
    
    @property
    def session(self):
        from sqlalchemy.orm.session import object_session
        return object_session(self.document)
    
    
    def get_date(self):
        paper_details = self.paper_details
        if "publicationDate" in paper_details:
            return paper_details["publicationDate"][:7]
        elif "year" in paper_details:
            return paper_details["year"] + "-01"
        if "arxiv.org" in self.doc_source:
            yr = self.doc_source.split("/")[-1].split(".")[0]
            if is_int(yr):
                return yr
            return None
        return None
            
    def get_short_answer(self, query, mode=defaultdict(lambda:False), save_answer=True):
        answer = ''
        for ans in self.streaming_get_short_answer(query, mode, save_answer):
            answer += ans
        return answer
        
    
    @streaming_timer
    def streaming_get_short_answer(self, query, mode=defaultdict(lambda:False), save_answer=True):
        ent_time = time.time()
        
        if mode["perform_web_search"]:
            mode = "web_search"
        elif mode["provide_detailed_answers"]:
            mode = "detailed"
        elif mode["detailed_with_followup"]:
            mode = "detailed_with_followup" # Broken # TODO: Fix
            depth = 1
        elif mode["use_references_and_citations"]:
            mode = "use_references_and_citations"
        elif mode["use_multiple_docs"]:
            additional_docs = mode["additional_docs_to_read"]
            mode = "use_multiple_docs"
        elif mode["review"]:
            mode = "review"
        else:
            mode = None
            
        
        
        depth = 1
        if mode=="web_search":
            web_results = get_async_future(web_search, query, self.doc_source, "\n ".join(self.indices['chunks'][:1]), self.get_api_keys(), self.get_date())
            depth = 1
            
        if mode == "use_multiple_docs":
            web_results = get_async_future(get_multiple_answers, query, additional_docs)
            mode = "web_search"
            depth = 1
            
        if mode == "review":
            web_results = get_async_future(web_search, query, self.doc_source, "\n ".join(self.indices['chunks'][:1]), self.get_api_keys(), self.get_date())
            
        
        summary_nodes = self.indices["summary_index"].similarity_search(query, k=self.result_cutoff*2)
        summary_text = "\n".join([n.page_content for n in summary_nodes]) # + "\n" + additional_text_qna
        dqna_nodes = self.indices["dqna_index"].similarity_search(query, k=self.result_cutoff)
        qna_text = "\n".join([n.page_content for n in list(dqna_nodes)])
        raw_nodes = self.indices["raw_index"].similarity_search(query, k=self.result_cutoff)
        raw_text = "\n".join([n.page_content for n in raw_nodes])
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        if llm.use_gpt4:
            raw_nodes = self.indices["raw_index"].similarity_search(query, k=self.result_cutoff+1)
            raw_text = "\n".join([n.page_content for n in raw_nodes])
            small_chunk_nodes = self.indices["small_chunk_index"].similarity_search(query, k=self.result_cutoff)
            small_chunk_text = "\n".join([n.page_content for n in small_chunk_nodes])
            raw_text = raw_text + " \n\n " + small_chunk_text
            prompt = self.short_streaming_answer_prompt.format(query=query, fragment=raw_text, summary=summary_text, 
                                            questions_answers=qna_text, full_summary=self.indices["running_summary"])
        else:
            prompt = self.short_streaming_answer_prompt.format(query=query, fragment=raw_text, summary="", 
                                            questions_answers="", full_summary=self.indices["running_summary"])
        logger.info(f"Started streaming answering")
        if mode=="detailed" or mode=="detailed_with_followup" or mode=="review":
            post_prompt_instruction = ''
            if mode=="detailed_with_followup":
                main_post_prompt_instruction = " \n\n After answering the question, append #### (four hashes) in a new line to your output and then mention whether elaborating the answer by reading the full document will help our user (write True for this) or whether our current answer is good enough and elaborating is just time wasted (write False for this). Write only True/False after the #### (four hashes)."
                prompt = prompt + main_post_prompt_instruction
                post_prompt_instruction = " \n\n After answering the question, append #### (four hashes) in a new line to your output and then mention one follow-up question in the next line similar to the initial question which can help in further understanding."
            elif mode == "review":
                post_prompt_instruction = ""
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            st = time.time()
            additional_info = get_async_future(call_contextual_reader, query, " ".join(self.indices['chunks']), self.get_api_keys(), chunk_size=2000 if mode=="review" else 3200)
            et = time.time()
            logger.info(f"Blocking on ContextualReader for {(et-st):4f}s")
            
            
        elif mode=="web_search":
            prompt = "Provide a short and concise answer. " + prompt
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            logger.info(f"Web search Results for query = {query}, Results = {web_results}")
            additional_info = web_results
            post_prompt_instruction = ''
        else:
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            small_chunk_nodes = self.indices["small_chunk_index"].similarity_search(query, k=self.result_cutoff*2)
            additional_info = "\n".join([n.page_content for n in small_chunk_nodes])
            additional_info = wrap_in_future(additional_info)
            post_prompt_instruction = ''
        answer = ''
        ans_begin_time = time.time()
        logger.info(f"Start to answer by {(ans_begin_time-ent_time):4f}s")
        
        breaker = ''
        decision_var = ''
        web_generator_1 = None
        for txt in main_ans_gen:
            if mode == "web_search" or mode == "review":
                if web_results.done():
                    web_res_1 = web_results.result()
                    web_generator_1 = self.streaming_web_search_answering(query, answer, web_res_1["text"])
                    if depth == 2:
                        web_results_l2 = get_async_future(web_search, query, self.doc_source, "\n ".join(self.indices['chunks'][:1]), self.get_api_keys(), datetime.now().strftime("%Y-%m"), answer, web_res_1['search_results'])
                    
            if breaker.strip() != '####':
                yield txt
                answer += txt
            else:
                decision_var += txt
            if txt == "#" or txt == "##" or txt == "###" or txt == "####":
                breaker = breaker + txt
            elif breaker.strip()!="####":
                breaker = ''
        yield "</br> \n"
        logger.info(f"Decision to continue the answer for short answer = {decision_var}")
        decision_var = True if re.sub(r"[^a-z]+", "", decision_var.lower().strip()) in ["true", "yes", "ok", "sure"] else False
        
        if (decision_var and (mode == "detailed" or mode == "detailed_with_followup")) or mode == "web_search" or mode == "review":
            follow_breaker = ''
            follow_q = ''
            txc = ''
            additional_info = additional_info.result()
            web_results = web_results.result()
            if mode == "review":
                txc1 = additional_info
                txc2 = web_results['text']
                txc = f"Contextual text based on query from rest of document: {txc1} \n\n Web search response based on query: {txc2} \n\n"
            elif mode == "web_search":
                txc = additional_info['text']
            else:
                for t in additional_info:
                    txc += t
                
            stage1_answer = answer + " \n "
            if mode == "web_search" or mode == "review":
                if web_generator_1 is None:
                    web_generator_1 = self.streaming_web_search_answering(query, answer, txc)
                    if mode == "web_search" and depth == 2:
                        web_results_l2 = get_async_future(web_search, query, self.doc_source, "\n ".join(self.indices['chunks'][:1]), self.get_api_keys(), datetime.now().strftime("%Y-%m"), answer, additional_info['search_results'])
                generator = web_generator_1
                
                
                if len(web_results['queries'])>0:
                    answer += "\nWeb searched with Queries: \n"
                    yield "\nWeb searched with Queries: \n"
                    yield '</br>'
                for ix, q in enumerate(web_results['queries']):
                    answer += (str(ix+1) + ". " + q + " \n")
                    yield str(ix+1) + ". " + q + " \n"
                    yield '</br>'
                
                
                answer += "\n\nSearch Results: \n"
                yield '</br>'
                for ix, r in enumerate(web_results['search_results']):
                    answer += (str(ix+1) + f". [{r['title']}]({r['link']})")
                    yield str(ix+1) + f". [{r['title']}]({r['link']})"
                    yield '</br>'
                answer += '\n'
                yield '</br> '
                
            else:
                generator = self.streaming_get_more_details(query, answer, 1, txc, post_prompt_instruction, save_answer)
            web_generator_2 = None
            for txt in generator:
                if mode == "web_search" and depth==2:
                    if web_results_l2.done():
                        additional_info = web_results_l2.result()
                        web_generator_2 = self.streaming_get_more_details(query, stage1_answer, 2, additional_info['text'], post_prompt_instruction, save_answer)
                if follow_breaker.strip() != '####':
                    yield txt
                    answer += txt
                    stage1_answer += txt
                else:
                    follow_q = follow_q + txt
                if txt == "#" or txt == "##" or txt == "###" or txt == "####":
                    follow_breaker = follow_breaker + txt
                elif follow_breaker.strip()!="####":
                    follow_breaker = ''
                    
            if mode == "web_search" and depth==2:
                
                if web_generator_2 is None:
                    additional_info = web_results_l2.result()
                    logger.info(f"1st Stage Answer \n```\n{stage1_answer}\n```\n")
                    web_generator_2 = self.streaming_get_more_details(query, stage1_answer, 1, additional_info['text'], post_prompt_instruction, save_answer)
                yield "</br> \n"
                answer += " \n "
                if len(additional_info['queries'])>0:
                    answer += "\nWeb searched with Queries: \n"
                    yield "\nWeb searched with Queries: \n"
                    yield '</br>'
                for ix, q in enumerate(additional_info['queries']):
                    answer += (str(ix+1) + ". " + q + " \n")
                    yield str(ix+1) + ". " + q + " \n"
                    yield '</br>'
                
                
                answer += "\n\nSearch Results: \n"
                yield '</br>'
                for ix, r in enumerate(additional_info['search_results']):
                    answer += (str(ix+1) + f". [{r['title']}]({r['link']})")
                    yield str(ix+1) + f". [{r['title']}]({r['link']})"
                    yield '</br>'
                answer += '\n'
                yield '</br> '
                
                
                for txt in web_generator_2:
                    yield txt
                    answer += txt
            
            logger.info(f"Mode = {mode}, Follow Up Question: {follow_q}")
            follow_q = follow_q.strip().replace('\n','')
            if len(follow_q) > 0 and mode == "detailed_with_followup" and depth==2:
                yield f"\n ** <b>{follow_q}</b> ** \n"
                for txt in self.streaming_ask_follow_up(follow_q, {"query": query, "answer": answer}, ):
                    answer += txt
                    yield txt
        if save_answer:
            self.save_answer(query, answer)
        
    def get_fixed_details(self, key):
        in_depth_readers = self.document.in_depth_readers
        id_dict = {idr.key: idr.text for idr in in_depth_readers}
        if key in id_dict and len(id_dict[key]["text"].strip())>0:
            logger.info(f'Found fixed details for key = {key} with content = {id_dict[key].strip()}')
            return id_dict[key]
        keys = [
                        "methodology",
                        "previous_literature_and_differentiation",
                        "experiments_and_evaluation",
                        "results_and_comparison",
                        "limitations_and_future_work"
                    ]
        assert key in keys
        key_to_query_map = {
            "methodology": """
- Motivation and Methodology
    - What do the authors do in this overall work (i.e. their methodology) with details.
    - Detailed methodology and approach described in this work.
    - what problem do they address ?
    - how do they solve the problem, provide details?
    - Why do they solve this particular problem?
    - what is their justification in using this method? Why do they use this method? 
    - Any insights from their methods
    - Any drawbacks in their method or process
            """,
            "previous_literature_and_differentiation": """
- Previous Literature and Background work
    - What is this work's unique contribution over previous works?
    - what previous literature or works are referred to?
    - How are the previous works relevant to the problem this method is solving?
    - how their work is different from previous literature?
    - What improvements does their work bring over previous methods.
            """,
            "experiments_and_evaluation":"""
- Experiments and Evaluation
    - How is the proposed method/idea evaluated?
    - What metrics are used to quantify their results?
    - what datasets do they evaluate on?
    - What experiments are performed?
    - Are there any experiments with surprising insights?
    - Any other surprising experiments or insights
    - Any drawbacks in their evaluation or experiments
    
            """,
            "results_and_comparison": """
- Results
    - What results do they get from their experiments 
    - how does this method perform compared to other methods?
    - Make markdown tables to highlight most important results.
    - Any Insights or surprising details from their results and their tables
            """,
            "limitations_and_future_work":"""
- Limitations and possible future research directions
    - What are the limitations of this method, 
    - Where and when can this method or approach fail? 
    - What are some further future research opportunities for this domain as a follow up to this method?
    - What are some tangential interesting research questions or problems that a reader may want to follow upon?
    - What are some overlooked experiments which could have provided more insights into this approach or work.
            """,
        }
        logger.info(f"Create fixed details for key = {key} ")
        full_text = ''
        for txt in self.streaming_get_short_answer(key_to_query_map[key], defaultdict(lambda: False, {"provide_detailed_answers": True}), save_answer=False):
            full_text += txt
            yield txt
        self.set_deep_reader_detail(key, full_text)
        
    
    def get_short_info(self):
        logger.info(f"Get short info for doc_id = {self.doc_id}")
        logger.info(f"get_short_info: {self.get_api_keys()}")
        return dict(doc_id=self.doc_id, source=self.doc_source, title=self.title, short_summary=self.short_summary, summary=self.indices["running_summary"])
    
    @property
    def doc_source(self):
        return self.document.doc_source
    
    @property
    def title(self):
        if isinstance(self.document._title, str) and len(self.document._title.strip()) > 0:
            return self.document._title
        else:
            try:
                logger.info(f"title: {self.get_api_keys()}")
                title = self.paper_details["title"]
            except Exception as e:
                logger.info(f"title: {self.get_api_keys()}")
                title = CallLLm(self.get_api_keys(), use_gpt4=False)(f"Provide a title for the below text: \n'{self.indices['chunks'][0]}' \nTitle: \n")
            self.document._title = title
            return title
    
    @staticmethod
    def process_one_paper(paper):
        string_keys = ["paperId", "venue", "url", "title", "abstract", "tldr", "year", "referenceCount", "citationCount", "journal"]
        keys = ["publicationDate", "citations", "references", "externalIds", ]
        paper_output = dict()
        for k in string_keys:
            paper_output[k] = str(getattr(paper, k))
        
#         print(paper.title, getattr(paper, "publicationDate"), paper.year)
        pubdate = getattr(paper, "publicationDate")
        if pubdate is None:
            paper_output["publicationDate"] = str(paper.year)+"-01-01"
        else:
            paper_output["publicationDate"] = pubdate.strftime("%Y-%m-%d")
        paper_output['ArXiv'] = NoneToDefault(getattr(paper, "externalIds", dict()), dict()).get('ArXiv')
        paper_output["citations"] = [DocIndex.process_one_paper(c) for c in NoneToDefault(getattr(paper, "citations", []))]
        paper_output["references"] = [DocIndex.process_one_paper(c) for c in NoneToDefault(getattr(paper, "references", []))]
        paper_output["citations"] = [c for c in paper_output["citations"] if c["paperId"] is not None and len(c["paperId"])>0 and c["paperId"].lower()!="none"]
        paper_output["references"] = [c for c in paper_output["references"] if c["paperId"] is not None and len(c["paperId"])>0 and c["paperId"].lower()!="none"]
        paper_output["extended_abstract"] = getattr(paper, "extended_abstract", None)
        return paper_output
        
    @property
    def paper_details(self)->dict:
        if hasattr(self.document, "is_local") and self.document.is_local:
            return dict()
        elif "_paper_details" in self.indices and self.indices["_paper_details"] is not None:
            return DocIndex.process_one_paper(self.indices["_paper_details"])
        else:
            arxiv_url = self.doc_source
            paper = get_paper_details_from_semantic_scholar(arxiv_url)
            logger.info(f"paper_details: {self.get_api_keys()}")
            self.set_doc_attribute({"_paper_details": paper})
            return self.paper_details
    
    def refetch_paper_details(self)->dict:
        url = self.doc_source
        paper = get_paper_details_from_semantic_scholar(url)
        old_details = self.indices.get("_paper_details", None)
        if old_details is not None:
            extended_ref = {ref["paperId"]:getattr(ref, "extended_abstract") for ref in (NoneToDefault(getattr(old_details, "references", [])) + NoneToDefault(getattr(old_details, "citations", []))) if hasattr(ref, "extended_abstract")}
            for ref in NoneToDefault(getattr(paper, "references", [])) + NoneToDefault(getattr(paper, "citations", [])):
                if ref["paperId"] in extended_ref:
                    setattr(ref, "extended_abstract", extended_ref.get(ref["paperId"]))
                    break
        
        self.set_doc_attribute({"_paper_details": paper})
        return self.paper_details
    
    def get_extended_abstract_for_ref_or_cite(self, paperId)->str:
        for ref in self.paper_details["references"] + self.paper_details["citations"]:
            if ref["paperId"] == paperId and hasattr(ref, "extended_abstract") and len(getattr(ref, "extended_abstract", '').strip())>0:
                yield getattr(ref, "extended_abstract", '').strip()
                return
        
        from semanticscholar import SemanticScholar
        sch = SemanticScholar()
        paper = sch.get_paper(paperId)
        if 'ArXiv' in paper.externalIds:
            arxiv = paper.externalIds['ArXiv']
            pdf_url = f"https://arxiv.org/pdf/{arxiv}.pdf"
            data = PDFReaderTool()(pdf_url, page_ranges="1-3")
            prompt = f"""Provide a detailed and comprehensive summary for the scientific text given. This scientific text is the beginning two pages of a larger research paper, as such some details maybe incomplete in this scientific text.
Abstract:
'{paper.abstract}'

Scientific Text:
'{data}'

Detailed and comprehensive summary:

            """
            answer = ''
            for txt in CallLLm(self.get_api_keys(), use_gpt4=False)(prompt, temperature=0.7, stream=True):
                yield txt
                answer += txt
            self.save_extended_abstract(paperId, answer)
            
        else:
            yield "Could not find ArXiv pdf for this document"
            
        
    @property
    def short_summary(self):
        if isinstance(self.document._short_summary, str) and len(self.document._short_summary.strip()) > 0:
            return self.document._short_summary
        else:
            try:
                short_summary = self.paper_details["abstract"]
            except Exception as e:
                short_summary = CallLLm(self.get_api_keys(), use_gpt4=False)(f"Provide a summary for the below scientific text: \n'''{self.indices['chunks'][0] + ' ' + self.indices['chunks'][1]}''' \nInclude relevant keywords, the provided abstract and any search/seo friendly terms in your summary. \nSummary: \n",)
            self.document._short_summary = short_summary
            return short_summary
        
    
    @property
    def doc_source(self):
        return self.document.doc_source
    
    
    
    def get_all_details(self):
        details=dict()
        document:Document = self.document
        details["deep_reader_details"] = {indr.key:{"id":indr.id, "text": indr.text} for indr in document.in_depth_readers}
        details["detailed_qna"] = [[qa.id, qa.question, qa.answer] for qa in document.questions]
        details["running_summary"] = self.indices["running_summary"]
        details["chunked_summary"] = self.indices["chunked_summary"]
        return dict(doc_id=self.doc_id, source=self.doc_source, title=self.title, short_summary=self.short_summary, summary=self.indices["running_summary"], details=details)
    
    
    def streaming_ask_follow_up(self, query, previous_answer, mode=defaultdict(lambda: False)):
    
        if mode["perform_web_search"]:
            mode = "web_search"
        elif mode["provide_detailed_answers"]:
            mode = "detailed"
        elif mode["detailed_with_followup"]:
            mode = "detailed_with_followup" # Broken # TODO: Fix
        elif mode["use_references_and_citations"]:
            mode = "use_references_and_citations"
        elif mode["use_multiple_docs"]:
            additional_docs = mode["additional_docs_to_read"]
            mode = "use_multiple_docs"
        elif mode["review"]:
            mode = "review"
        else:
            mode = None
        raw_nodes = self.indices["raw_index"].similarity_search(query, k=self.result_cutoff)
        small_chunk_nodes = self.indices["small_chunk_index"].similarity_search(query, k=self.result_cutoff*2)
        dqna_nodes = self.indices["dqna_index"].similarity_search(query, k=self.result_cutoff)[:1]
        
        # Get those nodes that don't come up in last query.
        small_chunk_nodes_ids = [n.metadata["order"] for n in small_chunk_nodes]
        small_chunk_nodes_old = self.indices["small_chunk_index"].similarity_search(previous_answer["query"], k=self.result_cutoff*8)
        small_chunk_nodes_ids = small_chunk_nodes_ids + [n.metadata["order"] for n in small_chunk_nodes_old]
        
        additional_small_chunk_nodes = self.indices["small_chunk_index"].similarity_search(query, k=self.result_cutoff*8)
        additional_small_chunk_nodes = [n for n in additional_small_chunk_nodes if n.metadata["order"] not in small_chunk_nodes_ids]
        
        small_chunk_nodes = small_chunk_nodes + additional_small_chunk_nodes[:4]
        
        summary_nodes = self.indices["summary_index"].similarity_search(query, k=self.result_cutoff)
        summary_text = "\n".join([n.page_content for n in summary_nodes])
        qna_text = "\n".join([n.page_content for n in list(dqna_nodes)])
        raw_text = "\n".join([n.page_content for n in raw_nodes] + [n.page_content for n in small_chunk_nodes])
        small_text = "\n".join([n.page_content for n in small_chunk_nodes])
        answer=previous_answer["answer"] + "\n" + (previous_answer["parent"]["answer"] if "parent" in previous_answer else "")
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        
            
        if llm.use_gpt4 and mode != "web_search":
            prompt = self.streaming_followup.format(followup=query, query=previous_answer["query"], 
                                          answer=answer, summary=summary_text, 
                                          fragment=raw_text,
                                          full_summary=self.indices["running_summary"], questions_answers=qna_text)
        else:
            prompt = self.streaming_followup.format(followup=query, query=previous_answer["query"], 
                                          answer=answer, summary="", 
                                          fragment=get_first_n_words(raw_text, 250) + " \n " + small_text,
                                          full_summary=self.indices["running_summary"], questions_answers="")
        if mode == "web_search":
            answer = CallLLm(self.get_api_keys(), use_gpt4=False)(f"Given the question: {previous_answer['query']}, Summarise this answer: '''{answer}''' \n ")
            web_results = get_async_future(web_search, query, self.doc_source, "\n ".join(self.indices['chunks'][:1]), self.get_api_keys(), datetime.now().strftime("%Y-%m"), answer)
            prev_answer = answer
            additional_info = web_results.result()
            answer = ''
            answer += "\nWeb searched with Queries: \n"
            yield "\nWeb searched with Queries: \n"
            yield '</br>'
            for ix, q in enumerate(additional_info['queries']):
                answer += (str(ix+1) + ". " + q + " \n")
                yield str(ix+1) + ". " + q + " \n"
                yield '</br>'
                
            answer += "\n\nSearch Results: \n"
            yield '</br>'
            for ix, r in enumerate(additional_info['search_results']):
                answer += (str(ix+1) + f". [{r['title']}]({r['link']})")
                yield str(ix+1) + f". [{r['title']}]({r['link']})"
                yield '</br>'
            answer += '\n'
            yield '</br>'
            
            generator = self.streaming_web_search_answering(query, prev_answer, web_results.result()['text'] + "\n\n " + f" Answer the followup question: {query} \n\n Additional Instructions: '''{prompt}'''")
            
        else:
            generator = llm(prompt, temperature=0.7, stream=True)
            answer = ''
        
        for txt in generator:
            yield txt
            answer += txt
        self.save_answer(previous_answer["query"], answer, query)

    def streaming_web_search_answering(self, query, answer, additional_info):
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        prompt = f"""Continue writing answer to a question or instruction which is partially answered. Provide new details from the additional information provided, don't repeat information from the partial answer already given.

Question is given below:

"{query}"

Relevant additional information from other documents with url links, titles and document context are mentioned below:

"{additional_info}"


Continue the answer ('Answer till now') by incorporating additional information from other documents. 
Answer by thinking of Multiple different angles that 'the original question or request' can be answered with. Focus mainly on additional information from other documents. Provide the link and title before using their information in markdown format (like `[title](link) information from document`) for the documents you use in your answer.

Use all of the documents given under 'additional information' and provide relevant information from them for our question. Remember to refer to all the documents in 'Relevant additional information' in markdown format (like `[title](link) information from document`).

Use markdown formatting to typeset/format your answer better.
Output any relevant equations in latex/markdown format. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math equations in less width.

Question: {query}
Answer till now (partial answer): {answer}
Continued Answer using additional information from other documents with url links, titles and document context: 

        """
        answer=answer + "\n"
        for txt in llm(prompt, temperature=0.7, stream=True):
            yield txt
            answer += txt
        
        
    
    def streaming_get_more_details(self, query, previous_answer, counter, additional_info='', additional_instructions='', save_answer=True):
        raw_nodes = self.indices["raw_index"].similarity_search(query, k=self.result_cutoff*(counter+1))[self.result_cutoff*counter:]
        small_chunk_nodes = self.indices["small_chunk_index"].similarity_search(query, k=self.result_cutoff*2*(counter+1))[self.result_cutoff*2*counter:]
        dqna_nodes = self.indices["dqna_index"].similarity_search(query, k=self.result_cutoff*(counter+1))[self.result_cutoff*counter:]
        summary_nodes = self.indices["summary_index"].similarity_search(query, k=self.result_cutoff*2*(counter+1))[self.result_cutoff*2*counter:]
        
        raw_nodes_ans = self.indices["raw_index"].similarity_search(previous_answer, k=counter)[counter-1:]
        small_chunk_nodes_ans = self.indices["small_chunk_index"].similarity_search(previous_answer, k=2*counter)[2*(counter-1):]
        
        raw_nodes = raw_nodes[:1]
        small_chunk_nodes = small_chunk_nodes[:1]
        dqna_nodes = dqna_nodes[:1]
        summary_nodes = summary_nodes[:1]
        raw_nodes_ans = raw_nodes_ans[:1]
        small_chunk_nodes_ans = small_chunk_nodes_ans[:1]
        
        summary_text = "\n".join([n.page_content for n in (summary_nodes)])
        qna_text = "\n".join([n.page_content for n in list(dqna_nodes)])
        sm_text = list(set([n.page_content.strip() for n in (small_chunk_nodes + small_chunk_nodes_ans)]))
        raw_text = "\n".join([n.page_content for n in (raw_nodes + raw_nodes_ans)] + sm_text)
        raw_text = raw_text + ' \n ' + additional_info
        answer=previous_answer + "\n"
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        if llm.use_gpt4:
            prompt = self.streaming_more_details.format(query=query, 
                                          answer=answer, summary=summary_text, 
                                          fragment=raw_text,
                                          full_summary=self.indices["running_summary"], questions_answers=qna_text)
        else:
            prompt = self.streaming_more_details.format(query=query, 
                                          answer=answer, summary="", 
                                          fragment=get_first_n_words(raw_text, 750),
                                          full_summary=self.indices["running_summary"], questions_answers="")
        prompt = prompt + additional_instructions
        for txt in llm(prompt, temperature=0.7, stream=True):
            yield txt
            answer += txt
        if save_answer:
            self.save_answer(query, answer)
            
    def streaming_build_summary(self):
        summary_prompt = "Summarize the below text from a scientific research paper:\n '{}' \nSummary: \n"
        if len(self.indices['chunked_summary']) > 0 and len(self.indices['chunked_summary'][0].strip())>0:
            # We already have the summary
            for txt in self.indices['chunked_summary']:
                yield txt
        running_summaries = []
        self.indices['chunked_summary'] = []
        running_summary = ''
        this_chunk = ''
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        two_chunks = combine_array_two_at_a_time(self.indices['chunks'])
        if llm.use_gpt4:
            two_chunks = [two_chunks[0] + ' ' + two_chunks[1]] + two_chunks[2:]
        
        chunk_summaries = []
        for ic, chunk in enumerate(two_chunks):
            if not TextLengthCheck(running_summary, 800):
                running_summaries.append(running_summary)
                running_summary = CallLLm(self.get_api_keys(), use_gpt4=False)(summary_prompt.format(running_summary), temperature=0.7, stream=False)
                
            prompt = self.running_summary_prompt.format(summary=running_summary, document=chunk, previous_chunk_summary=this_chunk)
            this_chunk = ''
            if ic == 0:
                for txt in llm(prompt, temperature=0.7, stream=True):
                    this_chunk = this_chunk + txt
                    yield txt
            else:
                for txt in CallLLm(self.get_api_keys(), use_gpt4=False)(prompt, temperature=0.7, stream=True):
                    this_chunk = this_chunk + txt
                    yield txt
            
            chunk_summaries.append(this_chunk)
            running_summary = running_summary + " " + this_chunk
        
        
        if llm.use_gpt4:
            running_summaries = [running_summaries[i] for i in range(0, len(running_summaries), 2)]
        else:
            mid = max(len(running_summaries)//2 - 1, 0)
            running_summaries = running_summaries[mid:mid+1]
        yield '\n\n</br></br>'
        new_summary_prompt = "Create an overall summary (elaborate and detailed summary) of a scientific paper from given sectional summary of parts of the paper.\n Sectional Summaries: \n '{}' \n Overall Summary: \n"
        rsum = ''
        for txt in llm(new_summary_prompt.format(" \n".join(running_summaries+[running_summary])), temperature=0.7, stream=True):
            rsum = rsum + txt
            yield txt
        
        self.indices["chunked_summary"] = chunk_summaries
        assert len(rsum.strip()) > 0
        self.indices['running_summary'] = rsum
        self.summary_index = create_index_faiss(self.indices['chunked_summary'], get_embedding_model(self.get_api_keys()), )
        self.save_local(None)
    
    def get_instruction_text_from_review_topic(self, review_topic):
        instruction_text = ''
        if isinstance(review_topic, str) and review_topic.strip() in review_params:
            instruction_text = review_topic + ": "+review_params[review_topic.strip()]
        elif isinstance(review_topic, str):
            instruction_text = review_topic.strip()
        elif isinstance(review_topic, (list, tuple)):
            try:
                assert len(review_topic) == 2
                assert isinstance(review_topic[0], str)
                assert isinstance(review_topic[1], int)
                
                instruction_text = ": ".join(review_params[review_topic[0].strip()][review_topic[1]])
            except Exception as e:
                raise Exception(f"Invalid review topic {review_topic}")
        else:
            raise Exception(f"Invalid review topic {review_topic}")
        return instruction_text
    
    def get_all_reviews(self):
        new_review_params = dict(**review_params)
        del new_review_params["meta_review"]
        del new_review_params["scores"]
        new_reviews = []
        for r in self.document.reviews:
            # dict(review_text=review_text, is_meta_review=is_meta_review, tone=tone, header=header, detailed_instructions=detailed_instructions, ) we use this structure.
            new_reviews.append(dict(review=r["review"] + ('\n\n' if len(r['score']) > 0 else '') + r['score'], 
                                    is_meta_review=r["is_meta_review"], 
                                    tone=r["tone"], 
                                    id=r["id"],
                                    review_topic=r["review_topic"],
                                    header=self.get_instruction_text_from_review_topic(r["review_topic"]).split(":")[0].strip(), 
                                    description=self.get_instruction_text_from_review_topic(r["review_topic"]).split(":")[-1].strip(),
                                    instructions=r["additional_instructions"],))    
        
        return {"reviews": new_reviews, "review_params": new_review_params}
        
    
    def get_review(self, tone, review_topic, additional_instructions, score_this_review, use_previous_reviews, is_meta_review):
        # Map -> collect details.
        # TODO: Support followup on a generated review.
        # TODO: use previous reviews.
        assert tone in ["positive", "negative", "neutral", "none"]
        tones = ["positive", "negative", "neutral", "none"]
        tone_synonyms = ["favorable and supportive.", "critical and unfavorable.", "not opinionated and middle grounded.", "unbiased to accept or reject."]
        instruction_text = self.get_instruction_text_from_review_topic(review_topic)
        if is_meta_review:
            use_previous_reviews = True
            assert use_previous_reviews and len(self.document.reviews) > 0, "Meta reviews require previous reviews to be present"
        
        for review in self.document.reviews:
            if str(review["review_topic"]) == str(review_topic) and review["tone"] == tone and review["additional_instructions"] == additional_instructions and review["is_meta_review"] == bool(is_meta_review):
                yield review["review"]
                yield review["score"]
                return
        previous_reviews_text = ''
        if use_previous_reviews and len(self.document.reviews) > 0:
            previous_reviews = [review for review in self.document.reviews if review["tone"] == tone]
            previous_reviews_text = "\n\n".join([review["review"]+review["score"] for review in previous_reviews])
        query_prompt = f"""You are an expert {'meta-' if is_meta_review else ''}reviewer assigned to review and evalaute a scientific research paper using certain reviewer instructions on a conference submission website like openreview.net or microsoft cmt. 
Write an opinionated review as a human reviewer who is thorough with this domain of research. 
Justify your review points and thoughts on the paper with examples from the paper. {(' '+review_params['meta_review'] + ' ') if is_meta_review else ''} Provide a {(tone + ' ') if tone!='none' and len(tone)>0 else ''}review for the given scientific text.{(' Make your review sound ' + tone_synonyms[tones.index(tone)]) if tone!='none' and len(tone)>0 else ''}
The topic and style of your review is described in the reviewer instructions given here: \n'''{instruction_text}'''  \n{'Further we have certain additional instructions to follow while writing this review: ' if len(additional_instructions.strip())>0 else ''}'''{additional_instructions}''' 
\n\n{'We also have previous reviews with same tone on this paper to assist in writing this review. Previous reviews: ' if len(previous_reviews_text) > 0 else ''}'''{previous_reviews_text}''' \n 
Don't give your final remarks or conclusion in this response. We will ask you to give your final remarks and conclusion later. 
\n{'Meta-' if is_meta_review else ''}Review: \n"""
        mode = defaultdict(lambda: False)
        mode["review"] = True
        review = ''
        for txt in self.streaming_get_short_answer(query_prompt, defaultdict(lambda: False, {"review": True}), save_answer=False):
            yield txt
            review += txt
        score = ''
        
        if score_this_review:
            score_prompt = f"Provide a score for the given research work using the given review on a scale of 1-5 ({review_params['scores']}). Provide your step by step elaborate reasoning for your score decision before writing your score. \nFirst page of the research work:  \n'''{ ' '.join(self.indices['chunks'][:2])}''' \nReview: \n'''{review}''' \nWrite Reasoning for score and then write score: \n"
            for txt in CallLLm(self.get_api_keys(), use_gpt4=False)(score_prompt, temperature=0.1, stream=True):
                yield txt
                score += txt
        self.save_review(review, score, tone, review_topic, additional_instructions, is_meta_review)
        self.session.commit()
        self.session.close()
    
    def save_review(self, review, score, tone, review_topic, additional_instructions, is_meta_review):
        review_topic = ",".join(map(str, review_topic)) if isinstance(review_topic, list) else review_topic
        id = str(mmh3.hash(self.doc_source + ",".join([tone, review_topic, additional_instructions, str(is_meta_review)]), signed=False))
        review = Review(id, review, score, tone, review_topic, additional_instructions, is_meta_review, self.doc_id, self.get_api_keys()["email"])
        self.document.reviews.append(review)
        
    
    @staticmethod
    def convert_document_to_docindex(document):
        if isinstance(document, DocIndex):
            return document
        elif isinstance(document, Document):
            d = DocIndex()
            d.indices = d.load_local(document._storage)
            d.document = document
            return d
        elif isinstance(document, (list, tuple, set)):
            return [DocIndex.convert_document_to_docindex(d) for d in document]
        else:
            return document
    
    @staticmethod
    def load_local(storage):
        import dill
        with open(storage, "rb") as f:
            obj = dill.load(f)
            return obj
    
    def save_local(self, folder):
        import dill
        doc_id = self.document.id
        
        filepath = self.document._storage
        if folder is None:
            folder = os.path.dirname(filepath)
        os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
        lock_location = os.path.join(os.path.join(folder, "locks"), f"{doc_id}")
        lock = FileLock(f"{lock_location}.lock")
        presave_api_keys = None
        if hasattr(self, "api_keys"):
            presave_api_keys = self.get_api_keys()
            logger.info(f"presave save_local {folder} \n {filepath} \n {lock}: {presave_api_keys}")
            self.api_keys = {k: None for k, v in self.api_keys.items()}
        with lock.acquire(timeout=600):
            if os.path.exists(filepath):
                logger.info(f"between p0 save_local: {presave_api_keys}")
                old_indices = self.load_local(filepath)
                for k, v in self.indices.items():
                    if isinstance(v,  (FAISS, VectorStore, DocFAISS)):
                        logger.info(f"between p1 save_local: {presave_api_keys}")
                        try:
                            v.merge_from(old_indices[k])
                        except Exception as e:
                            traceback.print_exc()
                        logger.info(f"between p1.5 save_local: {presave_api_keys}")
            logger.info(f"between p2 save_local: {presave_api_keys}")
            with open(filepath, "wb") as f:
                logger.info(f"between p3 save_local: {presave_api_keys}")
                dill.dump(self.indices, f)
                
        logger.info(f"set post save_local: {presave_api_keys}")
        self.set_api_keys(presave_api_keys)
    
                
    def set_deep_reader_detail(self, key, full_text):
        id = str(mmh3.hash(self.document.id + key, signed=False))
        depth_reader = InDepthReader(id, key, full_text, self.document.id)
        self.document.in_depth_readers.append(depth_reader)

    def put_answer(self, query, answer, followup_query=''):
        query = query.strip()
        followup_query = followup_query.strip()
        final_query = query + (f". followup:{followup_query}" if len(followup_query.strip()) > 0 else "")
        question_id = str(mmh3.hash(self.doc_source + final_query, signed=False))
        question = Question(question_id, final_query, answer, self.doc_id, self.get_api_keys()["email"])
        self.document.questions.append(question)
        
        
    def save_answer(self, query, answer, followup_query=''):
        
        self.put_answer(query, answer, followup_query)
        final_query = query + f"{followup_query}"
        db2 = FAISS.from_texts([final_query +"\n"+answer], get_embedding_model(self.get_api_keys()))
        logger.info(f"Save Answer called for query = {query}, followup_query = {followup_query}")
        self.indices["dqna_index"].merge_from(db2)
        self.save_local(None)
        

            
    def set_doc_attribute(self, dict_attr_to_value):
        logger.info(f"setting doc attribute = {dict_attr_to_value.keys()}")
        assert isinstance(dict_attr_to_value, dict)
        for k, v in dict_attr_to_value.items():
            self.indices[k] = v
        
        logger.info(f"Saving doc after setting attribute = {dict_attr_to_value.keys()}")
        self.save_local(None)
        
    
        
    def save_extended_abstract(self, paperId, answer):
        for ref in NoneToDefault(getattr(self._paper_details, "references", [])) + NoneToDefault(getattr(self._paper_details, "citations", [])):
            if ref["paperId"] == paperId:
                setattr(ref, "extended_abstract", answer)
                break
        self.save_local(None)
    
    def get_api_keys(self):
        logger.info(f"get api keys for self hash = {hash(self)}")
        if hasattr(self, "api_keys") and self.api_keys is not None:
            api_keys = deepcopy(self.api_keys)
        else:
            raise AttributeError("No attribute named `api_keys`.")
        return api_keys
    
    
    def set_api_keys(self, api_keys:dict):
        assert isinstance(api_keys, dict)
        setattr(self, "api_keys", api_keys)
    
    def __copy__(self):
        # Create a new instance of our class
        cls = self.__class__
        result = cls.__new__(cls)
        # Copy all attributes from self to result. This is a shallow copy.
        result.__dict__.update(self.__dict__)
        # Now we need to replace api_keys with a deepcopy
        for k, v in vars(result).items():
            if isinstance(v,  (FAISS, VectorStore)):
                v = deepcopy(v)
                setattr(result, k, v)
        if hasattr(result, "api_keys"):
            result.api_keys = deepcopy(self.api_keys)
        
        return result
    
    def copy(self):
        return self.__copy__()



class ImmediateDocIndex(DocIndex):
    pass

def create_immediate_document_index(pdf_url, keys, folder)->DocIndex:
    
    doc_text = PDFReaderTool(keys)(pdf_url)
    chunks = ChunkText(doc_text, 1024, 96)
    doc_filetype = "pdf"
    doc_type = "scientific_article"
    doc_id = str(mmh3.hash(pdf_url + doc_filetype + doc_type, signed=False))
    assert  doc_filetype == "pdf" and ("http" in pdf_url or os.path.exists(pdf_url))
    small_chunks = ChunkText(doc_text, 256, 32)
    openai_embed = keys["openai_embed"]
    document = Document(
            id=doc_id,
            doc_source=pdf_url,
            doc_filetype=doc_filetype,
            doc_type=doc_type,
            _title=None,
            _short_summary=None,
            _paper_details=None,
            is_local=os.path.exists(pdf_url),
            _storage=os.path.join(folder, doc_id+".index"),
        )
    doc_index = ImmediateDocIndex()
    doc_index.document = document
    doc_index.indices = (chunks, small_chunks, openai_embed) # Just invoking the setter
    return doc_index







    





    

        
        
    

