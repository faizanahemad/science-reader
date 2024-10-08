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
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO)
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
        assert doc_filetype in ["pdf", "word", "jpeg", "jpg", "png", "csv", "xls", "xlsx", "jpeg", "bmp", "svg", "parquet"] and ("http" in doc_source or os.path.exists(doc_source))

        if hasattr(self, "is_local") and self.is_local or "arxiv.org" not in self.doc_source:
            def set_title_summary():
                chunks = "\n\n".join(raw_data['chunks'][0:4])
                short_summary = CallLLm(keys, model_name="anthropic/claude-3-haiku:beta", use_gpt4=False)(f"""Provide a summary for the below text: \n'''{chunks}''' \nSummary: \n""", )
                title = CallLLm(keys, use_gpt4=False, use_16k=True)(f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n""")
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
        def set_raw_index_small():
            _ = sleep_and_get_future_result(set_title_summary_future)
            brief_summary = self.title + "\n" + self.short_summary
            brief_summary = ("Summary:\n" + brief_summary + "\n\n") if len(brief_summary.strip()) > 0 else ""
            self._brief_summary = brief_summary
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
            llm = CallLLm(self.get_api_keys(), model_name="gpt-4o" if detail_level >= 3 else "gpt-4o-mini",
                          use_gpt4=True,
                          use_16k=True)
            additional_info = get_async_future(llm, prompt, temperature=0.8)

        answer = sleep_and_get_future_result(answer) if sleep_and_get_future_exception(answer) is None else ""
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
            source = os.path.basename(source)
        return dict(visible=self.visible, doc_id=self.doc_id, source=source, title=self.title, short_summary=self.short_summary, summary=self.short_summary)
    
    @property
    def title(self):
        if hasattr(self, "_title") and len(self._title.strip()) > 0:
            return self._title
        elif self.doc_type == "image":
            return "image"
        else:
            title = CallLLm(self.get_api_keys(),model_name="gpt-4o-mini")(f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n""")
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
            short_summary = CallLLm(self.get_api_keys(), model_name="gpt-4o-mini", use_gpt4=False)(f"""Provide a summary for the below text: \n'''{self.get_doc_data("raw_data", "chunks")[0]}''' \nSummary: \n""",)
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
                    j.embedding_function.__self__.openai_api_key = api_keys["openAIKey"]
                    setattr(j.embedding_function.__self__, "openai_api_key", api_keys["openAIKey"])
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
            llm = CallLLm(keys, use_gpt4=True, use_16k=True, model_name="gpt-4o")
            llm2 = CallLLm(keys, use_gpt4=True, use_16k=True, model_name="google/gemini-flash-1.5")
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
            llm = CallLLm(self.get_api_keys(), use_gpt4=True, model_name="gpt-4o")
            prompt = """Please answer the user's query with the given image and the following text details of the image as context: \n\n'{}'\n\nConversation Details and User's Query: \n'{}'\n\nAnswer: \n""".format(text, query)
            answer = llm(prompt, images=[self.doc_source], temperature=0.7, stream=False)
            yield answer
        else:
            yield text


def create_immediate_document_index(pdf_url, folder, keys)->DocIndex:
    from langchain_community.document_loaders import UnstructuredMarkdownLoader
    from langchain_community.document_loaders import JSONLoader
    from langchain_community.document_loaders import UnstructuredHTMLLoader
    from langchain_community.document_loaders.csv_loader import CSVLoader
    from langchain_community.document_loaders.tsv import UnstructuredTSVLoader
    from langchain_community.document_loaders import UnstructuredWordDocumentLoader
    from langchain_community.document_loaders import TextLoader
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
        convert_doc_to_pdf(pdf_url, pdf_url.replace(".docx", ".pdf"))
        pdf_url = pdf_url.replace(".docx", ".pdf")
    elif is_remote and not (pdf_url.endswith(".md") or pdf_url.endswith(".json") or pdf_url.endswith(".csv") or pdf_url.endswith(".txt")):
        html = fetch_html(pdf_url, keys["zenrows"], keys["brightdataUrl"])
        # save this html to a file and then use the html loader.
        html_file = os.path.join(folder, "temp.html")
        with open(html_file, "w") as f:
            f.write(html)
        convert_html_to_pdf(html_file, html_file.replace(".html", ".pdf"))
        pdf_url = html_file.replace(".html", ".pdf")
        # delete html file
        os.remove(html_file)
        doc_text = UnstructuredHTMLLoader(html_file).load()[0].page_content
    elif pdf_url.endswith(".html"):
        doc_text = UnstructuredHTMLLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".md"):
        doc_text = UnstructuredMarkdownLoader(pdf_url).load()[0].page_content
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

