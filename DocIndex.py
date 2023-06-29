import sys
import random
from functools import partial
import glob
from filelock import FileLock, Timeout
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import re
from semanticscholar import SemanticScholar
from semanticscholar.SemanticScholar import Paper
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
from prompts import prompts
from langchain.document_loaders import MathpixPDFLoader
from datetime import datetime, timedelta

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
from langchain.vectorstores.base import VectorStore
from langchain.schema import Document
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import TextLoader
from llama_index.data_structs.node import Node, DocumentRelationship
from llama_index import LangchainEmbedding, ServiceContext, Document
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
        self.options = {"conversion_formats": {self.processed_file_format: True}, "rm_fonts": True, 
                   "enable_tables_fallback":True}
        if "page_ranges" in kwargs and kwargs["page_ranges"] is not None:
            self.options["page_ranges"] = kwargs["page_ranges"]
        
    @property
    def data(self) -> dict:
        
        return {"options_json": json.dumps(self.options)}
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



def create_index_faiss(chunks, embed_model, doc_id=None):
    from langchain.schema import Document
    if doc_id is None:
        doc_id = [""] * len(chunks)
    elif isinstance(doc_id, (str, int)):
        doc_id = [doc_id] * len(chunks)
    else:
        assert len(doc_id) == len(chunks) and isinstance(doc_id, (list, tuple))
        doc_id = [int(d) for d in doc_id]
    chunks = [Document(page_content=str(c), metadata={"order": i}) for i, c in enumerate(chunks)]
    for ix, chunk in enumerate(chunks):
        chunk.metadata["next"] = None if ix == len(chunks)-1 else chunks[ix + 1]
        chunk.metadata["previous"] = None if ix == 0 else chunks[ix - 1]
        chunk.metadata["doc_id"] = doc_id[ix]
        chunk.metadata["index"] = ix
    db = FAISS.from_documents(chunks, embed_model)
    return db


class DocIndex:
    def __init__(self, doc_source, doc_filetype, doc_type, doc_text, full_summary, openai_embed):
        
        self.result_cutoff = 2
        self.version = 0
        self.last_access_time = time.time()
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))
        self.doc_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type
        self._title = ''
        self._short_summary = ''
        self._paper_details = None
        assert  doc_filetype == "pdf" and "http" in doc_source
        lsum = full_summary
        self.doc_data = lsum
        self.doc_data["small_chunks"] = ChunkText(doc_text, 256, 50)
        dqna = [(qa[1]+"\n"+ qa[2]) if len(qa) > 0 else '' for qa in lsum["detailed_qna"]]
        ddr = [k + "\n" + v["text"] for k, v in lsum["deep_reader_details"].items()]
        dqna = dqna + ddr
        self.dqna_index = create_index_faiss(dqna, openai_embed, doc_id=self.doc_id, )
        
        self.raw_index = create_index_faiss(self.doc_data['chunks'], openai_embed,  )
        self.summary_index = create_index_faiss(self.doc_data['chunked_summary'], openai_embed, )
        self.small_chunk_index = create_index_faiss(self.doc_data["small_chunks"], openai_embed,  )
        
        
        self.streaming_followup = prompts["DocIndex"]["streaming_followup"]
        self.streaming_more_details = prompts["DocIndex"]["streaming_more_details"]
        self.short_streaming_answer_prompt = prompts["DocIndex"]["short_streaming_answer_prompt"]
        self.running_summary_prompt = prompts["DocIndex"]["running_summary_prompt"]
    
    
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
            
        
    @streaming_timer
    def streaming_get_short_answer(self, query, mode="web_search", save_answer=True):
        ent_time = time.time()
        dqna_nodes = self.dqna_index.similarity_search(query, k=self.result_cutoff)
        summary_nodes = self.summary_index.similarity_search(query, k=self.result_cutoff*2)
        summary_text = "\n".join([n.page_content for n in summary_nodes]) # + "\n" + additional_text_qna
        qna_text = "\n".join([n.page_content for n in list(dqna_nodes)])
        raw_nodes = self.raw_index.similarity_search(query, k=self.result_cutoff)
        raw_text = "\n".join([n.page_content for n in raw_nodes])
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        if llm.use_gpt4:
            raw_nodes = self.raw_index.similarity_search(query, k=self.result_cutoff+1)
            raw_text = "\n".join([n.page_content for n in raw_nodes])
            small_chunk_nodes = self.small_chunk_index.similarity_search(query, k=self.result_cutoff)
            small_chunk_text = "\n".join([n.page_content for n in small_chunk_nodes])
            raw_text = raw_text + " \n\n " + small_chunk_text
            prompt = self.short_streaming_answer_prompt.format(query=query, fragment=raw_text, summary=summary_text, 
                                            questions_answers=qna_text, full_summary=self.doc_data["running_summary"])
        else:
            prompt = self.short_streaming_answer_prompt.format(query=query, fragment=raw_text, summary="", 
                                            questions_answers="", full_summary=self.doc_data["running_summary"])
        logger.info(f"Started streaming answering")
        if mode=="detailed":
            main_post_prompt_instruction = " \n\n After answering the question, append #### (four hashes) in a new line to your output and then mention whether elaborating the answer by reading the full document will help our user (write True for this) or whether our current answer is good enough and elaborating is just time wasted (write False for this). Write only True/False after the #### (four hashes)."
            prompt = prompt + main_post_prompt_instruction
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            st = time.time()
            additional_info = get_async_future(call_contextual_reader, query, " ".join(self.doc_data['chunks']), self.get_api_keys())
            et = time.time()
            logger.info(f"Blocking on ContextualReader for {(et-st):4f}s")
            post_prompt_instruction = " \n\n After answering the question, append #### (four hashes) in a new line to your output and then mention one follow-up question in the next line similar to the initial question which can help in further understanding."
        elif mode=="web_search":
            web_results = get_async_future(web_search, query, "\n ".join(self.doc_data['chunks'][:2]), self.get_api_keys(), self.get_date())
            prompt = "Provide a short and concise answer. " + prompt
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            logger.info(f"Web search Results for query = {query}, Results = {web_results}")
            additional_info = web_results
            post_prompt_instruction = ''
        else:
            main_ans_gen = llm(prompt, temperature=0.7, stream=True)
            small_chunk_nodes = self.small_chunk_index.similarity_search(query, k=self.result_cutoff*2)
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
            if mode == "web_search":
                if web_results.done():
                    web_res_1 = web_results.result()
                    web_generator_1 = self.streaming_web_search_answering(query, answer, web_res_1["text"])
                    
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
        
        if (decision_var and (mode == "detailed" or mode == "detailed_with_followup")) or mode == "web_search":
            follow_breaker = ''
            follow_q = ''
            txc = ''
            additional_info = additional_info.result()
            if mode == "web_search":
                txc = additional_info['text']
            else:
                for t in additional_info:
                    txc += t
                
            stage1_answer = answer + " \n "
            if mode == "web_search":
                if web_generator_1 is None:
                    web_generator_1 = self.streaming_web_search_answering(query, answer, txc)
                generator = web_generator_1
                
                web_results = get_async_future(web_search, query, "\n ".join(self.doc_data['chunks'][:1]), self.get_api_keys(), datetime.now().strftime("%Y-%m"), answer, additional_info['search_results'])
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
            else:
                generator = self.streaming_get_more_details(query, answer, 1, txc, post_prompt_instruction, save_answer)
            web_generator_2 = None
            for txt in generator:
                if mode == "web_search":
                    if web_results.done():
                        additional_info = web_results.result()
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
                    
            if mode == "web_search":
                
                if web_generator_2 is None:
                    additional_info = web_results.result()
                    logger.info(f"1st Stage Answer \n```\n{stage1_answer}\n```\n")
                    web_generator_2 = self.streaming_get_more_details(query, stage1_answer, 1, additional_info['text'], post_prompt_instruction, save_answer)
                yield "</br> \n"
                answer += " \n "
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
                
                
                for txt in web_generator_2:
                    yield txt
                    answer += txt
            
            logger.info(f"Mode = {mode}, Follow Up Question: {follow_q}")
            follow_q = follow_q.strip().replace('\n','')
            if len(follow_q) > 0 and mode == "detailed_with_followup":
                yield f"\n ** <b>{follow_q}</b> ** \n"
                for txt in self.streaming_ask_follow_up(follow_q, {"query": query, "answer": answer}, ):
                    answer += txt
                    yield txt
        if save_answer:
            self.save_answer(query, answer)
        
    def get_fixed_details(self, key):
        if "deep_reader_details" in self.doc_data and key in self.doc_data["deep_reader_details"] and len(self.doc_data["deep_reader_details"][key]["text"].strip())>0:
            logger.info(f'Found fixed details for key = {key} with content = {self.doc_data["deep_reader_details"][key].strip()}')
            return self.doc_data["deep_reader_details"][key]
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
        for txt in self.streaming_get_short_answer(key_to_query_map[key], save_answer=False):
            full_text += txt
            yield txt
        self.set_deep_reader_detail(key, full_text)
        
    
    def get_short_info(self):
        return dict(doc_id=self.doc_id, source=self.doc_source, title=self.title, short_summary=self.short_summary, summary=self.doc_data["running_summary"])
    
    @property
    def title(self):
        if hasattr(self, "_title") and len(self._title.strip()) > 0:
            return self._title
        else:
            title = CallLLm(self.get_api_keys(), use_gpt4=False)(f"Provide a title for the below text: \n'{self.doc_data['chunks'][0]}' \nTitle: \n")
            setattr(self, "_title", title)
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
        if hasattr(self, "_paper_details") and self._paper_details is not None:
            return DocIndex.process_one_paper(self._paper_details)
        else:
            arxiv_url = self.doc_source
            paper = get_paper_details_from_semantic_scholar(arxiv_url)
            self.set_doc_attribute({"_paper_details": paper})
            return self.paper_details
    
    def refetch_paper_details(self)->dict:
        url = self.doc_source
        paper = get_paper_details_from_semantic_scholar(url)
        old_details = getattr(self, "_paper_details", None)
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
        if hasattr(self, "_short_summary") and len(self._short_summary.strip()) > 0:
            return self._short_summary
        else:
            try:
                short_summary = self.paper_details["abstract"]
            except Exception as e:
                short_summary = CallLLm(self.get_api_keys(), use_gpt4=False)(f"Provide a very short summary for the below scientific text: \n'{self.doc_data['chunks'][0] + ' ' + self.doc_data['chunks'][1]}' \nSummary: \n",)
            setattr(self, "_short_summary", short_summary)
            return short_summary
        
    
    def get_all_details(self):
        return dict(doc_id=self.doc_id, source=self.doc_source, title=self.title, short_summary=self.short_summary, summary=self.doc_data["running_summary"], details=self.doc_data)
    
    
    def streaming_ask_follow_up(self, query, previous_answer, more_background_details=''):
        raw_nodes = self.raw_index.similarity_search(query, k=self.result_cutoff)
        small_chunk_nodes = self.small_chunk_index.similarity_search(query, k=self.result_cutoff*2)
        dqna_nodes = self.dqna_index.similarity_search(query, k=self.result_cutoff)[:1]
        
        # Get those nodes that don't come up in last query.
        small_chunk_nodes_ids = [n.metadata["order"] for n in small_chunk_nodes]
        small_chunk_nodes_old = self.small_chunk_index.similarity_search(previous_answer["query"], k=self.result_cutoff*8)
        small_chunk_nodes_ids = small_chunk_nodes_ids + [n.metadata["order"] for n in small_chunk_nodes_old]
        
        additional_small_chunk_nodes = self.small_chunk_index.similarity_search(query, k=self.result_cutoff*8)
        additional_small_chunk_nodes = [n for n in additional_small_chunk_nodes if n.metadata["order"] not in small_chunk_nodes_ids]
        
        small_chunk_nodes = small_chunk_nodes + additional_small_chunk_nodes[:4]
        
        summary_nodes = self.summary_index.similarity_search(query, k=self.result_cutoff)
        summary_text = "\n".join([n.page_content for n in summary_nodes])
        qna_text = "\n".join([n.page_content for n in list(dqna_nodes)])
        raw_text = "\n".join([n.page_content for n in raw_nodes] + [n.page_content for n in small_chunk_nodes])
        answer=previous_answer["answer"] + "\n" + (previous_answer["parent"]["answer"] if "parent" in previous_answer else "")
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        if llm.use_gpt4:
            prompt = self.streaming_followup.format(followup=query, query=previous_answer["query"], 
                                          answer=answer, summary=summary_text, 
                                          fragment=raw_text,
                                          full_summary=self.doc_data["running_summary"], questions_answers=qna_text)
        else:
            prompt = self.streaming_followup.format(followup=query, query=previous_answer["query"], 
                                          answer=answer, summary="", 
                                          fragment=get_first_n_words(raw_text, 750),
                                          full_summary=self.doc_data["running_summary"], questions_answers="")
        answer = ''
        
        for txt in llm(prompt, temperature=0.7, stream=True):
            yield txt
            answer += txt
        self.save_answer(previous_answer["query"], answer, query)

    def streaming_web_search_answering(self, query, answer, additional_info):
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        prompt = f"""Continue writing answer to a question which is partially answered. Provide new details from the additional information provided, don't repeat information from the partial answer already given.

Question is given below:

"{query}"

Relevant additional information from other documents with url links and titles are mentioned below:

"{additional_info}"


Continue the answer ('Answer till now') by incorporating additional information from other documents. 
Answer by thinking of Multiple different angles that 'the original question or request' can be thought from. Focus mainly on additional information from other documents. Provide their link and title before using their information in markdown format (like `[title](link) information from document`).

Use all of the documents given under 'additional information' and provide relevant information from them for our question "{query}".

Provide detailed and elaborate answer using all the 'additional information' provided.
Use markdown formatting to typeset/format your answer better.
Output any relevant equations in latex/markdown format. Remember to put each equation or math in their own environment of '$$', our screen is not wide hence we need to show math equations in less width.

Question: {query}
Answer till now (partial answer): {answer}
Continued Answer: 

        """
        answer=answer + "\n"
        for txt in llm(prompt, temperature=0.7, stream=True):
            yield txt
            answer += txt
        
        
    
    def streaming_get_more_details(self, query, previous_answer, counter, additional_info='', additional_instructions='', save_answer=True):
        raw_nodes = self.raw_index.similarity_search(query, k=self.result_cutoff*(counter+1))[self.result_cutoff*counter:]
        small_chunk_nodes = self.small_chunk_index.similarity_search(query, k=self.result_cutoff*2*(counter+1))[self.result_cutoff*2*counter:]
        dqna_nodes = self.dqna_index.similarity_search(query, k=self.result_cutoff*(counter+1))[self.result_cutoff*counter:]
        summary_nodes = self.summary_index.similarity_search(query, k=self.result_cutoff*2*(counter+1))[self.result_cutoff*2*counter:]
        
        raw_nodes_ans = self.raw_index.similarity_search(previous_answer, k=counter)[counter-1:]
        small_chunk_nodes_ans = self.small_chunk_index.similarity_search(previous_answer, k=2*counter)[2*(counter-1):]
        
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
                                          full_summary=self.doc_data["running_summary"], questions_answers=qna_text)
        else:
            prompt = self.streaming_more_details.format(query=query, 
                                          answer=answer, summary="", 
                                          fragment=get_first_n_words(raw_text, 750),
                                          full_summary=self.doc_data["running_summary"], questions_answers="")
        prompt = prompt + additional_instructions
        for txt in llm(prompt, temperature=0.7, stream=True):
            yield txt
            answer += txt
        if save_answer:
            self.save_answer(query, answer)
            
    def streaming_build_summary(self):
        summary_prompt = "Summarize the below text from a scientific research paper:\n '{}' \nSummary: \n"
        if len(self.doc_data['chunked_summary']) > 0 and len(self.doc_data['chunked_summary'][0].strip())>0:
            # We already have the summary
            for txt in self.doc_data['chunked_summary']:
                yield txt
        running_summaries = []
        self.doc_data['chunked_summary'] = []
        running_summary = ''
        this_chunk = ''
        llm = CallLLm(self.get_api_keys(), use_gpt4=True)
        two_chunks = combine_array_two_at_a_time(self.doc_data['chunks'])
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
        
        self.doc_data["chunked_summary"] = chunk_summaries
        assert len(rsum.strip()) > 0
        self.doc_data['running_summary'] = rsum
        self.summary_index = create_index_faiss(self.doc_data['chunked_summary'], get_embedding_model(self.get_api_keys()), )
    
    def load_fresh_self(self):
        if self.last_access_time < time.time() - 3600:
            slf = self.load_self()
            slf.last_access_time = time.time()
            slf.merge_doc(self)
            return slf
        return self
    
    def load_self(self):
        folder = self._storage
        return self.load_local(folder, f"{self.doc_id}.index")
        
    @staticmethod
    def load_local(folder, filename):
        import dill
        with open(os.path.join(folder, filename), "rb") as f:
            obj = dill.load(f)
            setattr(obj, "_storage", folder)
            return obj
    
    def save_local(self, folder):
        import dill
        doc_id = self.doc_id

        if folder is None:
            folder = self._storage
        else:
            setattr(self, "_storage", folder)
        os.makedirs(folder, exist_ok=True)
        os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
        lock_location = os.path.join(os.path.join(folder, "locks"), f"{doc_id}")
        filepath = os.path.join(folder, f"{doc_id}.index")
        lock = FileLock(f"{lock_location}.lock")
        if hasattr(self, "api_keys"):
            presave_api_keys = self.api_keys
            self.api_keys = {k: None for k, v in self.api_keys.items()}
        with lock.acquire(timeout=600):
            merge_needed = False
            if os.path.exists(os.path.join(folder,  f"{doc_id}.index")):
                old_doc = self.load_local(folder, f"{doc_id}.index")
                old_version = old_doc.version
                merge_needed = self.version < old_version
            if merge_needed:
                self.merge_doc(old_doc)
                self.version = old_version + 1
            else:
                self.version += 1
                self.last_access_time = time.time()
            
            with open(filepath, "wb") as f:
                dill.dump(self, f)
        if hasattr(self, "api_keys"):
            self.api_keys = presave_api_keys
    
    def merge_doc(self, old_doc):
        # TODO: if attribute is list then we dedup and recreate list
        # save answers custom
        # TODO: deep merge
        current_qid = [d[0] for d in self.doc_data["detailed_qna"]]
        for _, (qid, q, a) in enumerate(old_doc.doc_data["detailed_qna"]):
            if len(q.strip()) > 0 and qid not in current_qid:
                self.put_answer(q, a)
        if "deep_reader_details" in old_doc.doc_data:
            if "deep_reader_details" in self.doc_data:
                for k, v in old_doc.doc_data["deep_reader_details"].items():
                    if v is not None and isinstance(v["text"], str)  and len(v["text"].strip()) > 0 and checkNoneOrEmpty(self.doc_data["deep_reader_details"].get(k, dict()).get("text", None)):
                        self.doc_data["deep_reader_details"][k] = v     
            else:
                self.doc_data["deep_reader_details"] = old_doc.doc_data["deep_reader_details"]
        for k, v in vars(old_doc).items():
            if k in ["detailed_qna", "deep_reader_details"]:
                continue
            if not hasattr(self, k):
                setattr(self, k, v)
            if isinstance(v, (list, str, tuple)):
                w = getattr(self, k)
                if len(w) < len(v):
                    setattr(self, k, v)
            if isinstance(v, dict):
                w = getattr(self, k)
                assert isinstance(w, dict)
                w.update({m:n for m, n in v.items() if m not in w})
                
    def set_deep_reader_detail(self, key, full_text):
        logger.info(f"Set deep reader detail for key = {key} with value = {''.join(full_text.split()[:10])}")
        if "deep_reader_details" in self.doc_data:
            self.doc_data["deep_reader_details"][key] = {"id": str(mmh3.hash(self.doc_source + key, signed=False)), "text": full_text}
            logger.info(f"Set deep reader detail when deep_reader_details in doc_data for key = {key}")
        else:
            self.doc_data["deep_reader_details"] = dict()
            self.doc_data["deep_reader_details"][key] = {"id": str(mmh3.hash(self.doc_source + key, signed=False)), "text": full_text}
            logger.info(f"Set deep reader detail when deep_reader_details not in doc_data for key = {key}")
        self.save_local(None)

    def put_answer(self, query, answer, followup_query=''):
        query = query.strip()
        followup_query = followup_query.strip()
        final_query = query + (f". followup:{followup_query}" if len(followup_query.strip()) > 0 else "")
        question_id = str(mmh3.hash(self.doc_source + final_query, signed=False))
        found_index = None
        for ix, qna_pair in enumerate(self.doc_data["detailed_qna"]):
            if qna_pair[0] == question_id and found_index is None:
                found_index = ix
        logger.info(f"Put answer in doc with question_id = {question_id}, query = {query}, found_index = {found_index}")
        if found_index is None:
            self.doc_data["detailed_qna"] = [[question_id, final_query, answer]] + self.doc_data["detailed_qna"]
        else:
            self.doc_data["detailed_qna"][found_index] = [question_id, final_query, answer]
        
    def save_answer(self, query, answer, followup_query=''):
        
        self.put_answer(query, answer, followup_query)
        final_query = query + f"{followup_query}"
        db2 = FAISS.from_texts([final_query +"\n"+answer], get_embedding_model(self.get_api_keys()))
        logger.info(f"Save Answer called for query = {query}, followup_query = {followup_query}")
        self.save_local(None)
        self.dqna_index.merge_from(db2)

            
    def set_doc_attribute(self, dict_attr_to_value):
        logger.info(f"setting doc attribute = {dict_attr_to_value.keys()}")
        assert isinstance(dict_attr_to_value, dict)
        for k, v in dict_attr_to_value.items():
            setattr(self, k, v)
        if hasattr(self, "_storage"):
            logger.info(f"Saving doc after setting attribute = {dict_attr_to_value.keys()}, value = {dict_attr_to_value.values()}")
            self.save_local(None)
        
    
        
    def save_extended_abstract(self, paperId, answer):
        for ref in NoneToDefault(getattr(self._paper_details, "references", [])) + NoneToDefault(getattr(self._paper_details, "citations", [])):
            if ref["paperId"] == paperId:
                setattr(ref, "extended_abstract", answer)
                break
        self.save_local(None)
    
    def get_api_keys(self):
        logger.info(f"get api keys for self hash = {hash(self)}")
        if hasattr(self, "api_keys"):
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

def create_immediate_document_index(pdf_url, keys)->DocIndex:
    doc_text = PDFReaderTool(keys)(pdf_url)
    chunks = ChunkText(doc_text, 1024, 96)
    nested_dict = {
        'full_length_summary': '',
        'title': [''],
        'chunked_summary': [''],
        'chunks': chunks,
        'running_summary': '',
        'detailed_qna': [],
        'deep_reader_details': {
            "methodology": {"id":"", "text":""},
            "previous_literature_and_differentiation": {"id":"", "text":""},
            "experiments_and_evaluation": {"id":"", "text":""},
            "results_and_comparison": {"id":"", "text":""},
            "limitations_and_future_work" : {"id":"", "text":""},
        }
    }
    openai_embed = get_embedding_model(keys)
    doc_index = ImmediateDocIndex(pdf_url, 
                "pdf", 
                "scientific_article", doc_text, nested_dict, openai_embed)
    
    return doc_index


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




def web_search(context, doc_context, api_keys, year_month=None, previous_answer=None, previous_search_results=None):
    # generate query
    # get links
    # rerank using gpt3.5 with snippet, year, link, current doc and query
    # read over top 10 pdf
#     from langchain.utilities import BingSearchAPIWrapper
#     search = BingSearchAPIWrapper()
#     search.results("apples", 50)

    n_query = "three" if previous_search_results else "two"
    pqs = []
    if previous_search_results:
        for r in previous_search_results:
            pqs.append(r["query"])
    prompt = f"""Given the scientific query/context \n'{context}' for the research document \n'{doc_context}'. 
    The provided query may not have all details that it needs to ask or may not be web search friendly. 
    {f"We also have the answer we have given till now for this question as '{previous_answer}' this answer may not be addressing all the information needed to answer the question, use this to determine how to write new web search queries." if previous_answer else ''}
    {f"We had generated the following web search queries in our previous search: '{pqs}', generate different queries compared to these." if len(pqs)>0 else ''}
    Then Generate {n_query} proper and well specified web search queries as a valid python list. Your output should be only a python list of strings (a valid python syntax code which is a list of strings) with {n_query} search query strings which are diverse and cover various topics about the query ('{context}') and help us understand it better. 

Your output will look like:

["web_query_1", "web_query_2"]
    
Output only a valid python list of query strings: 
"""
    query_strings = CallLLm(api_keys, use_gpt4=False)(prompt)
    
    logger.info(f"Query string for {context} = {query_strings}") # prompt = \n```\n{prompt}\n```\n
    query_strings = eval(query_strings.strip())
    if not previous_search_results:
        query_strings = [context] + query_strings
    qres = []
    if year_month:
        year_month = datetime.strptime(year_month, "%Y-%m").strftime("%Y-%m-%d")
    for query in query_strings:
        serp = serpapi(query, api_keys["bingKey"], num=5, our_datetime=year_month)
        for r in serp:
            r["query"] = query
        qres.extend(serp)
    dedup_results = []
    seen_titles = set()
    seen_links = set()
    if previous_search_results:
        for r in previous_search_results:
            seen_links.add(r['link'])
    for r in qres:
        title = r.get("title", "").lower()
        link = r.get("link", "").lower().replace(".pdf", '').replace("v1", '').replace("v2", '').replace("v3", '').replace("v4", '').replace("v5", '').replace("v6", '').replace("v7", '').replace("v8", '').replace("v9", '')
        if title in seen_titles or len(title) == 0 or link in seen_links:
            continue
        dedup_results.append(r)
        seen_titles.add(title)
        seen_links.add(link)
    for r in dedup_results:
        r["title"] = r["title"] + f" ({r['year']})" + f" (Cited by {r['citations']})"
        logger.info(f"Link: {r['link']} title: {r['title']}")
    logger.info(f"SERP results for {context}, count = {len(dedup_results)}")
    links = [r["link"] for r in dedup_results]
    titles = [r["title"] for r in dedup_results]
    contexts = [r["query"] for r in dedup_results]
    read_text, per_pdf_texts = read_over_multiple_pdf(links, titles, contexts, api_keys)
    for r, t in zip(dedup_results, per_pdf_texts):
        r['text'] = t['text']
    return {"text":read_text, "search_results": dedup_results, "queries": query_strings}

def multi_doc_reader(context, docs):
    pass

def ref_and_cite_reader(context, doc_index, ss_obj):
    pass


import multiprocessing
from multiprocessing import Pool

from concurrent.futures import ThreadPoolExecutor

def process_pdf(link_title_context_apikeys):
    link, title, context, api_keys = link_title_context_apikeys
    st = time.time()
    # Reading PDF
    extracted_info = ''
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    try:
        txt = pdfReader(link)
    
        # Chunking text
        chunked_text = ChunkText(txt, 2048, 0)[0]

        # Extracting info
        extracted_info = call_contextual_reader(context, chunked_text, api_keys, provide_short_responses=True)
        tt = time.time() - st
        logger.info(f"Called contextual reader for link: {link} with total time = {tt:.2f}")
    except Exception as e:
        logger.info(f"Exception `{str(e)}` raised on `process_pdf` with link: {link}")
    return {"link": link, "title": title, "text": extracted_info}

def read_over_multiple_pdf(links, titles, contexts, api_keys):
    # Combine links, titles, contexts and api_keys into tuples for processing
    link_title_context_apikeys = list(zip(links, titles, contexts, [api_keys]*len(links)))
    with ThreadPoolExecutor(max_workers=len(links)) as executor:
        logger.info(f"Start reading over multiple pdf docs...")
        # Use the executor to apply process_pdf to each tuple
        futures = [executor.submit(process_pdf, l_t_c_a) for l_t_c_a in link_title_context_apikeys]
        # Collect the results as they become available
        processed_texts = [future.result() for future in futures]
    # Concatenate all the texts
    result = "\n\n".join([json.dumps(p, indent=2) for p in processed_texts])
    import tiktoken
    enc = tiktoken.encoding_for_model("gpt-4")
    logger.info(f"Web search Result string len = {len(result.split())}, token len = {len(enc.encode(result))}")
    return result, processed_texts




    





    

        
        
    

