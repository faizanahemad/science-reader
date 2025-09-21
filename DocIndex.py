import os.path
import shutil

import semanticscholar.Paper
from filelock import FileLock, Timeout
from pathlib import Path
from web_scraping import fetch_html

try:
    import ujson as json
except ImportError:
    import json


from langchain_community.vectorstores.faiss import FAISS
from langchain_core.vectorstores import VectorStore
from common import *
from base import *

pd.options.display.float_format = '{:,.2f}'.format
pd.set_option('max_colwidth', 800)
pd.set_option('display.max_columns', 100)

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)
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
        from langchain.docstore.base import AddableMixin
        from langchain.schema import Document
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
    db = DocFAISS.from_documents(chunks, embed_model)
    return db


class DocIndex:
    def __init__(self, doc_source, doc_filetype, doc_type, doc_text, chunk_size, full_summary, openai_embed, storage, keys):
        init_start = time.time()
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))
        raw_data = dict(chunks=full_summary["chunks"])
        raw_index_future = get_async_future(create_index_faiss, raw_data['chunks'], openai_embed, doc_id=self.doc_id, )
        raw_data_small = dict(chunks=full_summary["chunks_small"])
        raw_index_small_future = get_async_future(create_index_faiss, raw_data_small['chunks'], openai_embed, doc_id=self.doc_id, )



        self._visible = False
        self._chunk_size = chunk_size
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        # if parent folder of doc_source is not same as storage, then copy the doc_source to storage
        if self.is_local and os.path.dirname(os.path.expanduser(doc_source)) != os.path.expanduser(storage):
            # shutil.copy(doc_source, storage) # move not copy
            try:
                shutil.move(doc_source, storage)
                # Handle shutil.Error where file already exists
            except shutil.Error as e:
                # Replace the file in storage with the new one
                shutil.copy(doc_source, storage)
                doc_source = os.path.join(storage, os.path.basename(doc_source))

            doc_source = os.path.join(storage, os.path.basename(doc_source))
            self.doc_source = doc_source
        self.doc_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type
        self._title = ''
        self._short_summary = ''
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = ["indices", "raw_data", "review_data", "static_data", "_paper_details"]
        print(doc_filetype)
        assert doc_filetype in ["pdf", "html", "word", "jpeg", "md", "jpg", "png", "csv", "xls", "xlsx", "jpeg", "bmp", "svg", "parquet"] and ("http" in doc_source or os.path.exists(doc_source))

        if hasattr(self, "is_local") and self.is_local or "arxiv.org" not in self.doc_source:
            def set_title_summary():
                chunks = "\n\n".join(raw_data['chunks'][0:4])
                short_summary = CallLLm(keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False)(f"""Provide a summary for the below text: \n'''{chunks}''' \nSummary: \n""", )
                title = CallLLm(keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False, use_16k=True)(f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n""")
                setattr(self, "_title", title)
                setattr(self, "_short_summary", short_summary)
            set_title_summary_future = get_async_future(set_title_summary)
        else:
            set_title_summary_future = wrap_in_future(None)
        static_data = dict(doc_source=doc_source, doc_filetype=doc_filetype, doc_type=doc_type, doc_text=doc_text)
        del full_summary["chunks"]
        _paper_details = None
        # self.set_doc_data("static_data", None, static_data)
        # self.set_doc_data("raw_data", None, raw_data)


        futures = [get_async_future(self.set_doc_data, "static_data", None, static_data), get_async_future(self.set_doc_data, "raw_data", None, raw_data)]
        indices = dict(summary_index=create_index_faiss(['EMPTY'], openai_embed, ))
        futures.append(get_async_future(self.set_doc_data, "indices", None, indices))
        for f in futures:
            sleep_and_get_future_result(f, 0.1)
        time_logger.info(f"DocIndex init time without raw index: {(time.time() - init_start):.2f}")
        self.set_api_keys(keys)
        self.long_summary_waiting = time.time()
        def set_raw_index_small():
            _ = sleep_and_get_future_result(set_title_summary_future)
            brief_summary = self.title + "\n" + self.short_summary
            brief_summary = ("Summary:\n" + brief_summary + "\n\n") if len(brief_summary.strip()) > 0 else ""
            self._brief_summary = brief_summary
            # _ = get_async_future(self.get_doc_long_summary)
            text = self.brief_summary + doc_text
            self._text_len = get_gpt4_word_count(text)
            self._brief_summary_len = get_gpt3_word_count(brief_summary)
            self._raw_index = sleep_and_get_future_result(raw_index_future)
            self._raw_index_small = sleep_and_get_future_result(raw_index_small_future)
            time_logger.info(f"DocIndex init time with raw index and title, summary: {(time.time() - init_start):.2f}")
        set_raw_index_small()


    @property
    def brief_summary_len(self):
        if hasattr(self, "_brief_summary_len"):
            return self._brief_summary_len
        else:
            return get_gpt3_word_count(self.brief_summary)

    @property
    def raw_index(self):
        if hasattr(self, "_raw_index"):
            return self._raw_index
        else:
            return None

    @property
    def raw_index_small(self):
        if hasattr(self, "_raw_index_small"):
            return self._raw_index_small
        else:
            return None

    @property
    def text_len(self):
        return self._text_len

    @property
    def brief_summary(self):
        return self._brief_summary

    @property
    def chunk_size(self):
        if hasattr(self, "_chunk_size"):
            return self._chunk_size
        else:
            return LARGE_CHUNK_LEN

    @property
    def visible(self):
        return self._visible if hasattr(self, "_visible") else True

    def get_doc_data(self, top_key, inner_key=None,):
        import dill
        doc_id = self.doc_id

        folder = self._storage
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")
        
        try:
            assert top_key in self.store_separate
        except Exception as e:
            raise ValueError(f"Invalid top_key {top_key} provided")
        logger.debug(f"Get doc data for top_key = {top_key}, inner_key = {inner_key}, folder = {folder}, filepath = {filepath} exists = {os.path.exists(filepath)}, json filepath = {json_filepath} exists = {os.path.exists(json_filepath)}, already loaded = {getattr(self, top_key, None) is not None}")
        if getattr(self, top_key, None) is not None:
            if inner_key is not None:
                return getattr(self, top_key, None).get(inner_key, None)
            else:
                return getattr(self, top_key, None)
        else:
            if os.path.exists(json_filepath):
                with open(json_filepath, "r") as f:
                    obj = json.load(f)
                setattr(self, top_key, obj)
                if inner_key is not None:
                    return obj.get(inner_key, None)
                else:
                    return obj
            elif os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    obj = dill.load(f)
                if top_key not in ["indices", "_paper_details"]:
                    with open(json_filepath, "w") as f:
                        json.dump(obj, f)
                setattr(self, top_key, obj)
                if inner_key is not None:
                    return obj.get(inner_key, None)
                else:
                    return obj
            else:
                return None
        
    
    def set_doc_data(self, top_key, inner_key, value, overwrite=False):
        import dill
        doc_id = self.doc_id
        folder = self._storage
        print(folder)
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")
        path = Path(folder)
        lock_location = os.path.join(os.path.join(path.parent.parent, "locks"), f"{doc_id}-{top_key}")
        lock = FileLock(f"{lock_location}.lock")
        with lock.acquire(timeout=600):
            if inner_key is not None:
                tk = self.get_doc_data(top_key)
                if tk is None:
                    setattr(self, top_key, dict())
                
                inner = self.get_doc_data(top_key, inner_key)
                assert type(inner) == type(value) or inner is None or (isinstance(inner, (tuple, list)) and isinstance(value, (tuple, list)))
                if isinstance(inner, dict) and not overwrite:
                    inner.update(value)
                elif isinstance(inner, list) and not overwrite:
                    inner.extend(value)
                elif isinstance(inner, str) and not overwrite:
                    inner = inner + value
                elif isinstance(inner, tuple) and not overwrite:
                    inner = inner + value
                else:
                    inner = value
                getattr(self, top_key, None)[inner_key] = inner
            else:
                tk = self.get_doc_data(top_key, None)
                if top_key == "review_data" and isinstance(tk, dict):
                    tk = list(tk.values())
                assert (type(tk) == type(value) or tk is None or value is None) or (isinstance(tk, (tuple, list)) and isinstance(value, (tuple, list)))
                if tk is not None and type(tk) == type(value):
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
                elif tk is None and value is not None:
                    setattr(self, top_key, value)
                else:
                    setattr(self, top_key, None)
            if top_key not in ["indices", "_paper_details"]:
                with open(json_filepath, "w") as f:
                    json.dump(getattr(self, top_key, None), f)
            else:
                with open(os.path.join(filepath), "wb") as f:
                    dill.dump(getattr(self, top_key, None), f)
            
    
    def get_short_answer(self, query, mode=defaultdict(lambda:False), save_answer=True):
        answer = ''
        for ans in self.streaming_get_short_answer(query, mode, save_answer):
            answer += ans
        return answer
    
    def get_raw_doc_text(self):
        return self.brief_summary + "\n\n" + self.get_doc_data("static_data", "doc_text")
    
    def get_doc_long_summary(self):
        # while hasattr(self, "long_summary_waiting") and time.time() - self.long_summary_waiting < 90 and not hasattr(self, "_long_summary"):
        #     time.sleep(0.1)
        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        long_summary = ""
        if hasattr(self, "_long_summary"):
            yield self._long_summary
            return

        elif "arxiv" in self.doc_source or "aclanthology" in self.doc_source or "aclweb" in self.doc_source:
            paper_summary = prompts.paper_summary_prompt
            llm_context = paper_summary + "\n\n<context>\n" + text + "\n</context>\nWrite a detailed and comprehensive summary of the paper below.\n\n"
            llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LLM[0])
            document_type = "scientific paper"
            
        else:
            llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LLM[0])
            
            # Step 1: Identify document type and key aspects
            identify_prompt = """
Analyze the following document and:
1. Identify the type of document (e.g., research paper, technical report, business proposal, etc.) from the list of allowed document types.
2. List the key aspects that should be included in a highly detailed and comprehensive summary for this type of document.
3. Outline a plan for creating an in-depth summary. We need to ensure all Key Aspects are addressed. Any key takeaways and important points are included.

Allowed document types:
```
["scientific paper", "business report", "business proposal", "business plan", "technical documentation", "api documentation", "user manual", "other"]
```

Scientific Papers can include research papers, technical papers, arxiv papers, aclanthology papers, aclweb papers as well.
For scientific paper document type, just leave detailed_summary_prompt blank. We already have a detailed summary prompt for scientific papers.

Document text:
{text}

Respond in the following xml like format:

```xml
<response>

<document_type>
[Your identified document type]
</document_type>

<key_aspects>
[List of key aspects for understanding the document]
</key_aspects>

<key_takeaways>
[Detailed list of key takeaways in bullet points]
</key_takeaways>


<detailed_summary_prompt>
[
    For Scientific Papers just leave this blank. We already have a detailed summary prompt for scientific papers.
    Detailed summary prompt for an LLM to generate a comprehensive, detailed, and in-depth summary for the document type. 
    The prompt should elicit the LLM to generate a detailed overview, documentation and multi-page technical report based on the document type and key aspects. 
    The summary prompt should prompt the LLM to cover all the key aspects and important points and details of the document.
]
</detailed_summary_prompt>

</response>
```


Your response should be in the xml format given above. Write the response below.
""".lstrip()
            
            
            identification = llm(identify_prompt.format(text=text[:3000]), temperature=0.7, stream=False)
            document_type = identification.split("<document_type>")[1].split("</document_type>")[0].lower().strip()
            key_aspects = identification.split("<key_aspects>")[1].split("</key_aspects>")[0].lower().strip()
            key_takeaways = identification.split("<key_takeaways>")[1].split("</key_takeaways>")[0].lower().strip()
            
            long_summary += f"\n\n<b> Document Type: {document_type} </b> \n </br>"
            yield f"\n\n<b> Document Type: {document_type} </b> \n </br>"
            
            
            
            long_summary += f"\n\n<b> Key Takeaways:</b> \n{key_takeaways} \n \n </br>"
            yield f"\n\n<b> Key Takeaways:</b> \n{key_takeaways} \n \n </br>"
            
            if document_type == "scientific paper":
                detailed_summary_prompt = prompts.paper_summary_prompt
            else:
                detailed_summary_prompt = identification.split("<detailed_summary_prompt>")[1].split("</detailed_summary_prompt>")[0].lower().strip()
            logger.info(f"Document Type: {document_type}, ")
            if document_type not in ["scientific paper", "research paper", "technical paper", "business report", "business proposal", "business plan", "technical documentation", "api documentation", "user manual", "other"]:
                raise ValueError(f"Invalid document type {document_type} identified. Please try again.")
            
            # Step 2: Generate the comprehensive summary
            summary_prompt = """We have read the document and following is the analysis of the document:

Document Type: {document_type}

Key Aspects: 
{key_aspects}

Key Takeaways: 
{key_takeaways}

Use the below guidelines to generate the summary:

{detailed_summary_prompt}

Now, create a comprehensive, detailed, and in-depth summary of the entire document. 
Follow the Summary Plan and ensure all Key Aspects are addressed. 
The summary should provide a thorough understanding of the document's contents, main ideas, results, future work, and all other significant details.
Use the Detailed Summary Prompt to guide the LLM to generate the summary. Cover the key aspects in depth in your long and comprehensive report.
All sections must be detailed, comprehensive and in-depth. All sections must be rigorous, informative, easy to understand and follow.

- Formatting Mathematical Equations:
  - Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment. If you use `\\[ ... \\]` then use `\\\\` instead of `\\` for making the double backslash. We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]`.
  - For inline maths and notations use "\\\\( ... \\\\)" instead of '$$'. That means for inline maths and notations use double backslash and a parenthesis opening and closing (so for opening you will use a double backslash and a opening parenthesis and for closing you will use a double backslash and a closing parenthesis) instead of dollar sign.
  - We need to use double backslash so it should be `\\\\[ ... \\\\]` instead of `\\[ ... \\]` and and `\\\\( ... \\\\)` instead of `\\( ... \\)` for inline maths.


Full document text:
{text}

Comprehensive and In-depth Summary:
""".lstrip()
            llm_context = summary_prompt.format(document_type=document_type, key_aspects=key_aspects, key_takeaways=key_takeaways, detailed_summary_prompt=detailed_summary_prompt, text=text)
            
            
        ans_generator = llm(llm_context, temperature=0.7, stream=True)
        if "arxiv" in self.doc_source or document_type in ["scientific paper", "research paper", "technical paper"]:
        
            llm2 = CallLLm(self.get_api_keys(), model_name=EXPENSIVE_LLM[1])
            llm3 = CallLLm(self.get_api_keys(), model_name=EXPENSIVE_LLM[0])
            method_prompt = prompts.paper_details_map["methodology"]
            method_prompt += "\n\n<context>\n" + text + "\n</context>\nWrite a detailed and comprehensive explanation of the methodology used in the paper."
            method_ans_generator = llm2(method_prompt, temperature=0.7, stream=True)
            literature_prompt = prompts.paper_details_map["previous_literature_and_differentiation"]
            literature_prompt += "\n\n<context>\n" + text + "\n</context>\nWrite a detailed and comprehensive explanation of the previous literature and why their work is different from previous literature."
            literature_ans_generator = llm3(literature_prompt, temperature=0.7, stream=True)
            
            
        
        for ans in ans_generator:
            long_summary += ans
            yield ans
            
        if "arxiv" in self.doc_source or document_type in ["scientific paper", "research paper", "technical paper"]:
            long_summary += "\n\n ## More Details on their methodology \n"
            yield "\n\n ## More Details on their methodology \n"
            for ans in method_ans_generator:
                long_summary += ans
                yield ans
            long_summary += "\n\n ## Previous Literature and Differentiation \n"
            yield "\n\n ## Previous Literature and Differentiation \n"
            for ans in literature_ans_generator:
                long_summary += ans
                yield ans
            
        setattr(self, "_long_summary", long_summary)
        self.save_local()

        
    
    def get_chain_of_density_summary(self):
        """Generate a high-density summary using chain-of-density technique adapted to document type."""
        
        if hasattr(self, "_dense_summary"):
            return self._dense_summary
        
        # Get base summary and document analysis
        if hasattr(self, "_long_summary"):
            base_summary = self._long_summary
        else:
            base_summary = make_stream(self.get_doc_long_summary(), False)
        
        
        llm = CallLLm(self.get_api_keys(), model_name=EXPENSIVE_LLM[0])
        if "arxiv" in self.doc_source:
            doc_analysis = json.loads("""
                                      {
                                            "doc_type": "scientific paper",
                                            "key_elements": [],
                                            "technical_level": "high",
                                            "summary_focus": [],
                                            "improvements": [],
                                            "missing_elements": []
                                        }
                                      """)
        else:
            # First determine document type and structure using the identification from long summary
            identify_prompt = """
Analyze this summary and determine:
1. The type of document (e.g., scientific paper, business report, technical documentation, news article, etc.)
2. List the key aspects that should be included in a highly detailed and comprehensive summary for this type of document.
3. The key structural elements that should be emphasized in a dense summary
4. The appropriate level of technical detail needed
5. List of improvements to be made to the summary
6. List of missing elements from the summary

Allowed document types:
```
["scientific paper", "research paper", "technical paper", "business report", "business proposal", "business plan", "technical documentation", "api documentation", "user manual", "other"]
```

Summary text:
{text}

Only give JSON in your response in the format given below.

Respond in JSON format:
{{
    "doc_type": "type of document",
    "key_elements": ["list of important structural elements and key aspects for a detailed and comprehensive summary"],
    "technical_level": "high/medium/low",
    "summary_focus": ["specific aspects to focus on"],
    "improvements": ["list of improvements to be made to the summary"],
    "missing_elements": ["list of missing elements from the summary which could be added if present in the document"]
}}
""".lstrip()
        
            json_response = llm(
                identify_prompt.format(text=base_summary),
                temperature=0.1,
                stream=False
            )
            logger.info(f"Chain of density identify response: \n{json_response}")
            doc_analysis = json.loads(json_response)
        
        # Select appropriate density prompt based on document type
        if doc_analysis["doc_type"] in ["scientific paper", "research paper", "technical paper"]:
            density_prompt = prompts.scientific_chain_of_density_prompt
        elif doc_analysis["doc_type"] in ["business report", "business proposal", "business plan"]:
            density_prompt = prompts.business_chain_of_density_prompt
        elif doc_analysis["doc_type"] in ["technical documentation", "api documentation", "user manual"]:
            density_prompt = prompts.technical_chain_of_density_prompt
        else:
            density_prompt = prompts.general_chain_of_density_prompt
        
        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        # Initialize with first dense summary
        random_identifier = str(uuid.uuid4())
        answer = f"\n\n**Summary {0 + 1} :** <div data-toggle='collapse' href='#summary-{random_identifier}-{0}' role='button'></div> <div class='collapse' id='summary-{random_identifier}-{0}'>\n" + base_summary + f"\n</div>\n\n"
        yield answer
        preamble = f"\n\n**Final Summary :** <div data-toggle='collapse' href='#final-summary-{random_identifier}' role='button' aria-expanded='true'></div> <div class='collapse show' id='final-summary-{random_identifier}'>\n"
        answer += preamble
        yield preamble
        
        llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LLM[0])
        
        generator = llm(
            density_prompt.format(
                text=text,
                previous_summaries=base_summary,
                iteration=1,
                doc_type=doc_analysis["doc_type"],
                key_elements=", ".join(doc_analysis["key_elements"]),
                technical_level=doc_analysis["technical_level"],
                improvements=", ".join(doc_analysis["improvements"]),
                missing_elements=", ".join(doc_analysis["missing_elements"]),
                PaperSummary=prompts.paper_summary_prompt
            ),
            temperature=0.7,
            stream=True,
            system=prompts.chain_of_density_system_prompt
        )
        for ans in generator:
            yield ans
            answer += ans
        answer += "\n</div>\n\n"
        yield f"\n</div>\n\n"
        
        all_summaries = [base_summary, answer]
            
        setattr(self, "_dense_summary", all_summaries[-1])
        self.save_local()
        random_identifier = str(uuid.uuid4())
        yield ""


    @property
    def short_streaming_answer_prompt(self):
        return prompts.short_streaming_answer_prompt



    def semantic_search_document_small(self, query, token_limit=4096):
        st_time = time.time()
        tex_len = self.text_len
        if tex_len < token_limit:
            text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
            return text
        rem_word_len = token_limit - self.brief_summary_len
        rem_tokens = rem_word_len // self.chunk_size
        if self.raw_index_small is None:
            logger.warn(
                f"[semantic_search_document_small]:: Raw index small is None, returning using semantic_search_document fn.")
            return self.semantic_search_document(query, token_limit)
        raw_nodes = self.raw_index_small.similarity_search(query, k=max(self.result_cutoff, rem_tokens))

        raw_text = "\n".join([f"Small Doc fragment {ix + 1}:\n{n.page_content}\n" for ix, n in enumerate(raw_nodes)])
        logger.info(f"[semantic_search_document_small]:: Answered by {(time.time()-st_time):4f}s for additional info with additional_info_len = {len(raw_text.split())}")
        return self.brief_summary + raw_text

    def semantic_search_document(self, query, token_limit=4096):
        st_time = time.time()
        tex_len = self.text_len
        if tex_len < token_limit:
            text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
            return text
        rem_word_len = token_limit - self.brief_summary_len
        rem_tokens = rem_word_len // self.chunk_size
        if self.raw_index is None:
            text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
            logger.warn(f"[semantic_search_document]:: Raw index is None, returning brief summary and first chunk of text.")
            return chunk_text_words(text, chunk_size=token_limit, chunk_overlap=0)[0]
        raw_nodes = self.raw_index.similarity_search(query, k=max(self.result_cutoff, rem_tokens))

        raw_text = "\n".join([f"Doc fragment {ix + 1}:\n{n.page_content}\n" for ix, n in enumerate(raw_nodes)])
        logger.info(f"[semantic_search_document]:: Answered by {(time.time()-st_time):4f}s for additional info with additional_info_len = {len(raw_text.split())}")
        return self.brief_summary + raw_text

    
    @streaming_timer
    def streaming_get_short_answer(self, query, mode=defaultdict(lambda:False), save_answer=True):
        ent_time = time.time()
        detail_level = 1
        if mode["provide_detailed_answers"]:
            detail_level = max(1, int(mode["provide_detailed_answers"]))
            mode = "detailed"
        elif mode["review"]:
            mode = "detailed"
            detail_level = 2
        else:
            mode = None
            detail_level = 1

        # Sequential + RAG approach -> then combine.
        # For level 1, 2 both approaches use gpt3.5-16k -> gpt4-16k
        # For level 3, 4 both approaches use gpt3.5-16k + gpt4-16k

        additional_info = None
        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        prompt = f"""Answer the question or query in detail given below using the given context as reference. 
Question or Query is given below.
{query}
Write {'detailed and comprehensive ' if detail_level >= 3 else ''}answer.
"""
        cr = ContextualReader(self.get_api_keys(), provide_short_responses=detail_level < 2)
        answer = get_async_future(cr, prompt, text, self.semantic_search_document, "openai/gpt-4o")
        tex_len = self.text_len
        if (detail_level >= 3 or tex_len > 48000) and self.raw_index is not None:
            raw_nodes = self.raw_index.similarity_search(query, k=max(self.result_cutoff, 32_000//self.chunk_size))[1:]
            raw_text = "\n\n".join([n.page_content for n in raw_nodes])
            if (detail_level >= 4 or len(raw_nodes) == 0) and self.raw_index_small is not None:
                small_raw_nodes = self.raw_index_small.similarity_search(query, k=max(self.result_cutoff,
                                                                          12_000 // self.chunk_size))
                small_raw_text = "\n\n".join([n.page_content for n in small_raw_nodes])
                raw_text += "\n\n" + small_raw_text

            prompt = self.short_streaming_answer_prompt.format(query=query, fragment=self.brief_summary + raw_text, full_summary='')
            llm = CallLLm(self.get_api_keys(), model_name=EXPENSIVE_LLM[0] if detail_level >= 3 else CHEAP_LLM[0],
                          use_gpt4=True,
                          use_16k=True)
            additional_info = get_async_future(llm, prompt, temperature=0.8)

        answer = sleep_and_get_future_result(answer) if sleep_and_get_future_exception(answer) is None else ""
        answer, _ = answer
        if additional_info is not None:
            additional_info = sleep_and_get_future_result(additional_info) if additional_info.exception() is None else ""
            additional_info = remove_bad_whitespaces(additional_info)
            logger.info(f"streaming_get_short_answer:: Answered by {(time.time()-ent_time):4f}s for additional info with additional_info_len = {len(additional_info.split())}")
            for t in additional_info:
                yield t
                answer += t


        

    
    def get_short_info(self):
        source = self.doc_source
        if self.is_local:
            # only give filename in source
            # source = os.path.basename(source)
            source = source.replace(os.path.dirname(__file__)+"/", "")
        return dict(visible=self.visible, doc_id=self.doc_id, source=source, title=self.title, short_summary=self.short_summary, summary=self.short_summary)
    
    @property
    def title(self):
        if hasattr(self, "_title") and len(self._title.strip()) > 0:
            return self._title
        elif self.doc_type == "image":
            return "image"
        else:
            title = CallLLm(self.get_api_keys(),model_name=VERY_CHEAP_LLM[0])(f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n""")
            setattr(self, "_title", title)
            self.save_local()
            return title

        


    @property
    def short_summary(self):
        if hasattr(self, "_short_summary") and len(self._short_summary.strip()) > 0:
            return self._short_summary
        elif self.doc_type == "image":
            return "image"
        else:
            short_summary = CallLLm(self.get_api_keys(), model_name=VERY_CHEAP_LLM[0], use_gpt4=False)(f"""Provide a summary for the below text: \n'''{self.get_doc_data("raw_data", "chunks")[0]}''' \nSummary: \n""",)
            setattr(self, "_short_summary", short_summary)
            self.save_local()
            return short_summary

        
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
            logger.error(f"Error loading from local storage {folder} with error {e}")
            try:
                pass
                # shutil.rmtree(original_folder)
            except Exception as e:
                logger.error(
                    f"Error deleting local storage {folder} with error {e}")
            return None
    
    def save_local(self):
        import dill
        doc_id = self.doc_id
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
    


    def get_api_keys(self):
        logger.debug(f"get api keys for self hash = {hash(self)} and doc_id = {self.doc_id}")
        if hasattr(self, "api_keys"):
            api_keys = deepcopy(self.api_keys)
        else:
            raise AttributeError("No attribute named `api_keys`.")
        return api_keys
    
    
    def set_api_keys(self, api_keys:dict):
        assert isinstance(api_keys, dict)
        logger.debug(f"set api keys for self hash = {hash(self)} and doc_id = {self.doc_id}")
        indices = self.get_doc_data("indices")
        if indices is not None:
            for k, j in indices.items():
                if isinstance(j, (FAISS, VectorStore)):
                    j.embedding_function = get_embedding_model(api_keys).embed_query
                    if USE_OPENAI_API:
                        j.embedding_function.__self__.openai_api_key = api_keys["openAIKey"]
                        setattr(j.embedding_function.__self__, "openai_api_key", api_keys["openAIKey"])
                    else:
                        
                        j.embedding_function.__self__.openai_api_key = api_keys["jinaAIKey"]
                        setattr(j.embedding_function.__self__, "openai_api_key", api_keys["jinaAIKey"])
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



class ImmediateDocIndex(DocIndex):
    pass



class ImageDocIndex(DocIndex):
    def __init__(self, doc_source, doc_filetype, doc_type, doc_text, chunk_size, full_summary, openai_embed, storage,
                 keys):
        init_start = time.time()
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))

        self._visible = False
        self._chunk_size = chunk_size
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        # if parent folder of doc_source is not same as storage, then copy the doc_source to storage
        if self.is_local and os.path.dirname(os.path.expanduser(doc_source)) != os.path.expanduser(storage):
            # shutil.copy(doc_source, storage) # move not copy
            shutil.move(doc_source, storage)
            doc_source = os.path.join(storage, os.path.basename(doc_source))
            self.doc_source = doc_source
        self.doc_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type
        self._title = ''
        self.init_complete = False
        self._short_summary = ''
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = ["indices", "raw_data", "static_data",
                               "_paper_details"]
        assert doc_filetype in ["pdf", "word", "jpeg", "jpg", "png", "csv", "xls", "xlsx", "jpeg", "bmp", "svg",
                                "parquet"] and ("http" in doc_source or os.path.exists(doc_source))

        def complete_init_image_doc_index():
            llm = CallLLm(keys, use_gpt4=True, use_16k=True, model_name=CHEAP_LLM[0])
            llm2 = CallLLm(keys, use_gpt4=True, use_16k=True, model_name=CHEAP_LONG_CONTEXT_LLM[0])
            doc_text_f1 = get_async_future(llm, prompts.deep_caption_prompt, images=[self.doc_source], stream=False)
            doc_text_f2 = get_async_future(llm2, prompts.deep_caption_prompt, images=[self.doc_source], stream=False)

            while not doc_text_f1.done() or not doc_text_f2.done():
                time.sleep(1)
            ocr_1 = sleep_and_get_future_result(doc_text_f1) if sleep_and_get_future_exception(doc_text_f1) is None else ""
            ocr_2 = sleep_and_get_future_result(doc_text_f2) if sleep_and_get_future_exception(doc_text_f2) is None else ""
            if len(ocr_1) > 0 and len(ocr_2) > 0:
                doc_text = "OCR and analysis from strong model:\n" + ocr_1 + "\nOCR and analysis from weak model:\n" + ocr_2
            elif len(ocr_1) > 0:
                doc_text = "OCR and analysis from strong model:\n" + ocr_1
            elif len(ocr_2) > 0:
                doc_text = "OCR and analysis from weak model:\n" + ocr_2
            else:
                doc_text = "OCR failed."


            if hasattr(self, "is_local") and self.is_local or "arxiv.org" not in self.doc_source:
                def set_title_summary():
                    title = doc_text.split("</detailed_caption>")[0].split("<detailed_caption>")[-1].strip()
                    short_summary = doc_text.split("</detailed_insights>")[0].split("<detailed_insights>")[-1].strip()
                    setattr(self, "_title", title)
                    setattr(self, "_short_summary", short_summary)

                set_title_summary_future = get_async_future(set_title_summary)
            else:
                set_title_summary_future = wrap_in_future(None)
            static_data = dict(doc_source=doc_source, doc_filetype=doc_filetype, doc_type=doc_type, doc_text=doc_text)
            del full_summary["chunks"]

            self.set_doc_data( "static_data", None, static_data)
            time_logger.info(f"DocIndex init time without raw index: {(time.time() - init_start):.2f}")
            self.set_api_keys(keys)

            def set_raw_index_small():
                _ = sleep_and_get_future_result(set_title_summary_future)
                brief_summary = self.title + "\n" + self.short_summary
                brief_summary = ("Summary:\n" + brief_summary + "\n\n") if len(brief_summary.strip()) > 0 else ""
                self._brief_summary = brief_summary
                text = self.brief_summary + doc_text
                self._text_len = get_gpt4_word_count(text)
                self._brief_summary_len = get_gpt3_word_count(brief_summary)
                time_logger.info(f"DocIndex init time with raw index and title, summary: {(time.time() - init_start):.2f}")

            set_raw_index_small()
            self.init_complete = True
            self.save_local()
            return True

        self.init_future = get_async_future(complete_init_image_doc_index)

    def is_init_complete(self):
        # setattr that init_complete
        if hasattr(self, "init_complete"):
            return True

        return self.init_future.done()

    def wait_till_init_complete(self):
        while not self.init_complete:
            time.sleep(1)
        logger.info(f"Waited for init complete for Image doc id = {self.doc_id} with source = {self.doc_source}")
        setattr(self, "init_complete", True)
        return True

    def semantic_search_document_small(self, query, token_limit=4096):

        return self.semantic_search_document(query, token_limit)

    def semantic_search_document(self, query, token_limit=4096):
        self.wait_till_init_complete()
        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        return text

    @streaming_timer
    def streaming_get_short_answer(self, query, mode=defaultdict(lambda: False), save_answer=False):
        self.wait_till_init_complete()
        doc_text = self.get_doc_data("static_data", "doc_text")
        text = self.brief_summary + doc_text
        if mode["provide_detailed_answers"] >= 3:
            llm = CallLLm(self.get_api_keys(), use_gpt4=True, model_name=EXPENSIVE_LLM[0])
            prompt = """Please answer the user's query with the given image and the following text details of the image as context: \n\n'{}'\n\nConversation Details and User's Query: \n'{}'\n\nAnswer: \n""".format(text, query)
            answer = llm(prompt, images=[self.doc_source], temperature=0.7, stream=False)
            yield answer
        else:
            yield text


class YouTubeDocIndex(DocIndex):
    def __init__(self, doc_source, doc_filetype, doc_type, doc_text, chunk_size, full_summary, openai_embed, storage,
                 keys):
        pass

def create_immediate_document_index(pdf_url, folder, keys)->DocIndex:
    from langchain_community.document_loaders import UnstructuredMarkdownLoader
    from langchain_community.document_loaders import JSONLoader
    from langchain_community.document_loaders import UnstructuredHTMLLoader
    from langchain_community.document_loaders.csv_loader import CSVLoader
    from langchain_community.document_loaders.tsv import UnstructuredTSVLoader
    from langchain_community.document_loaders import UnstructuredWordDocumentLoader
    from langchain_community.document_loaders import TextLoader
    from langchain_community.document_loaders import YoutubeLoader
    import pandas as pd
    is_image = False
    image_futures = None
    chunk_overlap = 128
    pdf_url = pdf_url.strip()
    # check if the link is local or remote
    is_remote = pdf_url.startswith("http") or pdf_url.startswith("ftp") or pdf_url.startswith("s3") or pdf_url.startswith("gs") or pdf_url.startswith("azure") or pdf_url.startswith("https") or pdf_url.startswith("www.")
    assert is_remote or os.path.exists(pdf_url), f"File {pdf_url} does not exist"
    if is_remote:
        pdf_url = convert_to_pdf_link_if_needed(pdf_url)
        is_pdf = is_pdf_link(pdf_url)
    else:
        is_pdf = pdf_url.endswith(".pdf")
    # based on extension of the pdf_url decide on the loader to use, in case no extension is present then try pdf, word, html, markdown in that order.
    logger.info(f"Creating immediate doc index for {pdf_url}, is_remote = {is_remote}, is_pdf = {is_pdf}")
    filetype = "pdf" if is_pdf else "word" if pdf_url.endswith(".docx") else "html" if pdf_url.endswith(".html") else "md" if pdf_url.endswith(".md") else "json" if pdf_url.endswith(".json") else "csv" if pdf_url.endswith(".csv") else "txt" if pdf_url.endswith(".txt") else "jpg" if pdf_url.endswith(".jpg") else "png" if pdf_url.endswith(".png") else "jpeg" if pdf_url.endswith(".jpeg") else "bmp" if pdf_url.endswith(".bmp") else "svg" if pdf_url.endswith(".svg") else "pdf"
    if is_pdf:
        doc_text = PDFReaderTool(keys)(pdf_url)
    elif pdf_url.endswith(".docx"):
        doc_text = UnstructuredWordDocumentLoader(pdf_url).load()[0].page_content
        from converters import convert_doc_to_pdf
        convert_doc_to_pdf(pdf_url, pdf_url.replace(".docx", ".pdf"))
        pdf_url = pdf_url.replace(".docx", ".pdf")
    elif is_remote and ("https://www.youtube.com/watch?v" in pdf_url or "https://www.youtube.com/shorts/" in pdf_url or is_youtube_link(pdf_url)) and False:
        doc_text = YoutubeLoader.from_youtube_url(
            pdf_url, add_video_info=False
        ).load()
        doc_text = "\n".join([d.page_content for d in doc_text])

    elif is_remote and is_youtube_link(pdf_url):
        temp_folder = os.path.join(os.getcwd(), "temp")
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
        from YouTubeDocIndex import answer_youtube_question
        result = answer_youtube_question("", pdf_url, keys["ASSEMBLYAI_API_KEY"], keys["OPENROUTER_API_KEY"], temp_folder)
        doc_text = result["transcript"] + "\n" + result["summary"] + "\n" + result["subtitles"]
        
    
    elif is_remote and not (pdf_url.endswith(".md") or pdf_url.endswith(".json") or pdf_url.endswith(".csv") or pdf_url.endswith(".txt")):
        html = fetch_html(pdf_url, keys["zenrows"], keys["brightdataUrl"])
        # save this html to a file and then use the html loader.
        html_file = os.path.join(folder, "temp.html")
        with open(html_file, "w") as f:
            f.write(html)
        from converters import convert_html_to_pdf
        convert_html_to_pdf(html_file, html_file.replace(".html", ".pdf"))
        pdf_url = html_file.replace(".html", ".pdf")
        # delete html file
        os.remove(html_file)
        doc_text = UnstructuredHTMLLoader(html_file).load()[0].page_content
    elif pdf_url.endswith(".html"):
        from converters import convert_html_to_pdf
        doc_text = UnstructuredHTMLLoader(pdf_url).load()[0].page_content
        convert_html_to_pdf(pdf_url, pdf_url.replace(".html", ".pdf"))
        pdf_url = pdf_url.replace(".html", ".pdf")
        
    elif pdf_url.endswith(".md"):
        doc_text = UnstructuredMarkdownLoader(pdf_url).load()[0].page_content
        from converters import convert_markdown_to_pdf
        convert_markdown_to_pdf(pdf_url, pdf_url.replace(".md", ".pdf"))
        pdf_url = pdf_url.replace(".md", ".pdf")
        
    elif pdf_url.endswith(".json"):
        doc_text = JSONLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".csv"):
        df = pd.read_csv(pdf_url, engine="python")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".tsv"):
        df = pd.read_csv(pdf_url, sep="\t")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".parquet"):
        df = pd.read_parquet(pdf_url)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".xlsx") or pdf_url.endswith(".xls"):
        df = pd.read_excel(pdf_url, engine='openpyxl')
        doc_text = df.to_markdown()
    elif pdf_url.endswith(".jsonlines") or pdf_url.endswith(".jsonl"):
        df = pd.read_json(pdf_url, lines=True)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".json"):
        df = pd.read_json(pdf_url)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".txt"):
        doc_text = TextLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".jpg") or pdf_url.endswith(".jpeg") or pdf_url.endswith(".png") or pdf_url.endswith(".bmp") or pdf_url.endswith(".svg"):

        doc_text = ""
        is_image = True
        chunk_overlap = 0
    else:
        raise Exception(f"Could not find a suitable loader for the given url {pdf_url}")
    
        
    doc_text = doc_text.replace('<|endoftext|>', '\n').replace('endoftext', 'end_of_text').replace('<|endoftext|>', '')
    doc_text_len = len(doc_text.split())
    if doc_text_len < 8000:
        chunk_size = LARGE_CHUNK_LEN // 8
    elif doc_text_len < 16000:
        chunk_size = LARGE_CHUNK_LEN // 4
    elif doc_text_len < 32000:
        chunk_size = LARGE_CHUNK_LEN // 2
    else:
        chunk_size = LARGE_CHUNK_LEN
    chunk_overlap = min(chunk_size//2, 128)
    chunk_size = max(chunk_size, chunk_overlap*2)
    if not is_image:
        chunks = get_async_future(chunk_text_words, doc_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks_small = get_async_future(chunk_text_words, doc_text, chunk_size=chunk_size//2, chunk_overlap=chunk_overlap)
        # chunks = get_async_future(ChunkText, doc_text, chunk_size, 64)
        # chunks_small = get_async_future(ChunkText, doc_text, chunk_size//2, 64)
        chunks = sleep_and_get_future_result(chunks)
        chunks_small = sleep_and_get_future_result(chunks_small)
    else:
        chunks = []
        chunks_small = []
    nested_dict = {
        'chunks': chunks,
        'chunks_small': chunks_small,
        'image_futures': image_futures,
    }
    openai_embed = get_embedding_model(keys)
    cls = ImmediateDocIndex if not is_image else ImageDocIndex
    try:
        doc_index: DocIndex = cls(pdf_url,
                    filetype,
                    "scientific_article" if not is_image else "image", doc_text, chunk_size, nested_dict, openai_embed, folder, keys)
        # for k in doc_index.store_separate:
        #     doc_index.set_doc_data(k, None, doc_index.get_doc_data(k), overwrite=True)
        doc_index.set_api_keys(keys)
        def get_doc_ready():
            return doc_index.get_short_info()
        _ = get_async_future(get_doc_ready)
        doc_index._visible = True
    except Exception as e:
        doc_id = str(mmh3.hash(pdf_url + "pdf" + "scientific_article", signed=False))
        try:
            folder = os.path.join(folder, f"{doc_id}")
            if os.path.exists(folder):
                shutil.rmtree(folder)
        except Exception as e:
            pass
        logger.error(f"Error creating immediate doc index for {pdf_url}")
        raise e
    
    return doc_index

