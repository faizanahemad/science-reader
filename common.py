import random
import tempfile
import asyncio
import traceback
import uuid

import more_itertools
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, ProcessPoolExecutor
from urllib.parse import urlparse, urlunparse
import time
import logging
import os
import inspect
from more_itertools import peekable
import types

import pickle
import dill
import threading

from multiprocessing import Process, Queue
from functools import partial

from very_common import is_picklable, is_dillable, is_int, get_async_future, wrap_in_future, executor, make_async, FINISHED_TASK, TERMINATION_SIGNAL, string_indicates_true, round_robin, checkNoneOrEmpty
from very_common import sleep_and_get_future_result, sleep_and_get_future_exception

from tenacity import RetryError
from convert_markdown_to_pdf import convert_markdown_to_pdf

USE_OPENAI_API = True
SMALL_CHUNK_LEN = 386
LARGE_CHUNK_LEN = 6144
TOKEN_LIMIT_FOR_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_DETAILED", 13000))
TOKEN_LIMIT_FOR_EXTRA_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_EXTRA_DETAILED", 25000))
TOKEN_LIMIT_FOR_SUPER_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_SUPER_DETAILED", 50000))
TOKEN_LIMIT_FOR_SHORT = int(os.getenv("TOKEN_LIMIT_FOR_SHORT", 3000))
TOKEN_LIMIT_FOR_NORMAL = int(os.getenv("TOKEN_LIMIT_FOR_SHORT", 5500))
DDOS_PROTECTION_STR = "Blocked by ddos protection"
PDF_CONVERT_URL = os.getenv("PDF_CONVERT_URL", "http://localhost:7777/forms/libreoffice/convert")
MAX_TIME_TO_WAIT_FOR_WEB_RESULTS = int(os.getenv("MAX_TIME_TO_WAIT_FOR_WEB_RESULTS", 45))
THRESHOLD_SIM_FOR_SEARCH_RESULT = 0.5
FILLER_MODEL = "Filler"
LEN_CUTOFF_WEB_TEXT = 50
SCIENCE_KEYS = [
                        "methodology",
                        "previous_literature_and_differentiation",
                        "experiments_and_evaluation",
                        "results_and_comparison",
                        "limitations_and_future_work"
                    ]
# stick to VL models
# stick to 128K or above context window

OPENROUTER_LLM = ["google/gemini-pro-1.5", "openai/gpt-4o", "anthropic/claude-3.7-sonnet:beta",]
            
VERY_CHEAP_LLM = ["google/gemini-2.5-flash", "google/gemini-2.5-flash-preview","google/gemini-2.0-flash-001", "google/gemini-2.0-flash-001", "google/gemini-flash-1.5", "google/gemma-3-27b-it", "minimax/minimax-01", "google/gemini-pro-1.5", "gpt-4o-mini", "google/gemini-flash-1.5-8b", "cohere/command-r7b-12-2024"]
CHEAP_LLM = ["gpt-4o", "minimax/minimax-01", "anthropic/claude-3.5-haiku:beta", "cohere/command-r-08-2024", "openai/gpt-4o-mini", "openai/gpt-4o", "google/gemini-pro-1.5", "amazon/nova-pro-v1", "qwen/qwen-plus"]
EXPENSIVE_LLM = ["anthropic/claude-3.7-sonnet:beta", "openai/chatgpt-4o-latest", "anthropic/claude-3.5-sonnet:beta", 
                 "anthropic/claude-3.7-sonnet",  "o3-mini", "anthropic/claude-3-opus:beta", "mistralai/pixtral-large-2411", 
                 "cohere/command-r-plus-08-2024", "openai/o1-preview", "o1-preview", "o1", 
                 "cohere/command-a", "ai21/jamba-1.6-large"]


CHEAP_LONG_CONTEXT_LLM = ["google/gemini-2.5-flash", "google/gemini-2.5-flash-preview", "gpt-4.1-mini", "google/gemini-2.0-flash-001", "google/gemini-flash-1.5", "google/gemini-2.0-flash-lite-001", "qwen/qwen-turbo", "minimax/minimax-01", "google/gemini-flash-1.5-8b"]
LONG_CONTEXT_LLM = ["google/gemini-2.5-pro", "google/gemini-pro-1.5", "google/gemini-2.5-pro-preview", "minimax/minimax-m1"]

COMMON_SALT_STRING = "31256greagy89"


def collapsible_wrapper_old(response, header="Solution", show_initially=True):
    """
    Wraps the response in a collapsible div with a header.
    If the response is a generator, it will yield the chunks.
    @param response: The response to wrap.
    @param header: The header of the collapsible div.
    @param show_initially: Whether the collapsible div should be shown initially.
    @return: A generator of the wrapped response.
    """
    is_generator = inspect.isgenerator(response)
    random_identifier = str(uuid.uuid4())
    response_class = 'collapse show' if show_initially else 'collapse'
    aria_expanded = 'true' if show_initially else 'false'
    if isinstance(response, str):
        yield f"**{header}**: <div data-toggle='collapse' href='#response-solution-{random_identifier}' role='button' aria-expanded='{aria_expanded}'></div><div class='{response_class}' id='response-solution-{random_identifier}'>\n{response}\n</div>"
        return
    
    if not is_generator:
        if isinstance(response, (str, list, tuple)) or isinstance(response, more_itertools.more.peekable) or isinstance(response, peekable) or hasattr(response, '__iter__') or hasattr(res, '__next__'):
            response = convert_iterable_to_stream(response)
    
        else:
            raise ValueError(f"Invalid response type: {type(response)}")
    
    yield f"**{header}**: <div data-toggle='collapse' href='#response-solution-{random_identifier}' role='button' aria-expanded='{aria_expanded}'></div><div class='{response_class}' id='response-solution-{random_identifier}'>\n"
    for chunk in response:
        yield chunk
    yield "\n</div>"


def collapsible_wrapper(response, header="Solution", show_initially=True, add_close_button=True):
    """
    Wraps the response in a collapsible section using HTML <details> tag with a header.
    If the response is a generator, it will yield the chunks.
    
    Parameters:
    -----------
    response : str or generator
        The response content to wrap in a collapsible section
    header : str, optional
        The header text to display in the collapsible section (default: "Solution")
    show_initially : bool, optional
        Whether the collapsible section should be shown initially (default: True)
    add_close_button : bool, optional
        Whether to add a close button at the end of the collapsible section (default: True)
    
    Returns:
    --------
    generator
        A generator yielding the wrapped response chunks
    
    Examples:
    ---------
    # Using with a string
    result = collapsible_wrapper("This is my content", header="My Header")
    
    # Using with a generator
    def my_generator():
        yield "Chunk 1"
        yield "Chunk 2"
    result = collapsible_wrapper(my_generator(), header="Streaming Content")
    """
    import inspect
    import uuid
    import more_itertools
    from more_itertools import peekable
    
    is_generator = inspect.isgenerator(response)
    
    # Add the open attribute if the section should be shown initially
    open_attr = " open" if show_initially else ""
    
    # Add CSS for the close button if requested
    if add_close_button:
        style_string = """<style>
.details-close-btn {
    background-color: #f0f0f0;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 12px;
    cursor: pointer;
    margin-top: 10px;
    display: inline-block;
}
.details-close-btn:hover {
    background-color: #e0e0e0;
}
</style>
<script>
document.addEventListener('click', function(event) {
    if (event.target.classList.contains('details-close-btn')) {
        // Find the parent details element
        let details = event.target.closest('details');
        if (details) {
            // Close the details element
            details.removeAttribute('open');
            // Scroll to the summary
            details.querySelector('summary').scrollIntoView({behavior: 'smooth'});
        }
    }
});
</script>
"""
        # yield style_string
    
    # Handle string responses directly
    if isinstance(response, str):
        yield f"\n<details {open_attr}>\n<summary><strong>{header}</strong></summary>\n\n{response}\n"
        if add_close_button:
            yield "\n<button class='details-close-btn'>Close</button>\n"
        yield "</details>\n\n"
        return
    
    # Handle other types of iterables
    if not is_generator:
        if isinstance(response, (list, tuple)) or isinstance(response, more_itertools.more.peekable) or isinstance(response, peekable) or hasattr(response, '__iter__') or hasattr(response, '__next__'):
            response = convert_iterable_to_stream(response)
        else:
            raise ValueError(f"Invalid response type: {type(response)}")
    
    # Start the details section
    yield f"\n<details {open_attr}>\n<summary><strong>{header}</strong></summary>\n\n"
    
    # Stream the content
    for chunk in response:
        yield chunk
    
    # Add the close button if requested
    if add_close_button:
        yield "\n<button class='details-close-btn'>Close</button>\n"
    
    # Close the details section
    yield "</details>\n\n"


def stream_multiple_models(keys, model_names, prompts, images=[], temperature=0.7, max_tokens=None, system=None, 
                           collapsible_headers=True, header_template="Response from {model}"):
    """
    Streams responses from multiple LLM models sequentially in a coordinated fashion, ensuring one complete
    model response is shown at a time while running all models in parallel for efficiency.
    
    Core Functionality:
    -------------------
    1. Runs multiple language models in parallel using async execution
    2. Buffers responses from each model as they become available
    3. Presents responses to the user one full model at a time
    4. Prioritizes models in order of which started responding first
    5. Handles errors gracefully without affecting other models
    6. Returns a dictionary of complete responses for further processing
    
    How It Works:
    ------------
    - Parallel Execution: Creates a separate thread for each model to execute requests concurrently
    - Message Queue: Uses a queue to coordinate messages from all threads to the main thread
    - Buffering System: Maintains a buffer for each model to store chunks when not actively streaming
    - Streaming Order: Tracks models in order of first response for sequential presentation
    - Error Handling: Captures and presents errors without disrupting other models
    
    Execution Process:
    -----------------
    1. Initialization:
       - Normalizes model_names length to match prompts if needed
       - Creates a message queue for thread communication
       - Sets up empty buffers for each model
       - Initializes tracking variables (streaming_order, currently_streaming, completed_models)
    
    2. Thread Creation:
       - For each model+prompt pair, creates a thread that:
         a. Calls the model with the given prompt
         b. Sends chunks to the queue as they arrive
         c. Signals completion or errors through the queue
    
    3. Main Loop:
       - Runs until all models have completed
       - Processes queue messages in order received
       - For each message, handles one of three types:
         a. "model": A chunk from a model
         b. "complete": Signal that a model has finished
         c. "error": Signal that a model encountered an error
    
    4. Chunk Processing Rules:
       - If no model is currently streaming, start streaming the first model that responds
       - If a chunk belongs to the currently streaming model, yield it immediately
       - If a chunk belongs to another model, buffer it for later
    
    5. Model Completion Rules:
       - When a model completes, if it was the currently streaming model:
         a. Close its collapsible section (if enabled)
         b. Find the next model in streaming_order that hasn't completed yet
         c. Begin streaming that model, including any buffered chunks
    
    6. Error Handling:
       - If a model errors, treat it as completed but with an error message
       - Display the error message in its own collapsible section (if headers enabled)
       - Continue with the next model
    
    7. Cleanup:
       - Ensure any open collapsible section is properly closed
       - Return the dictionary of complete model responses
    
    Arguments:
    ----------
    keys : dict
        API keys for the language models
    model_names : list
        List of model identifiers to use for queries
    prompts : list
        List of prompts to send to corresponding models
    images : list, optional
        Images to include with the prompts
    temperature : float, optional
        Temperature setting for generation (default: 0.7)
    max_tokens : int, optional
        Maximum tokens to generate for each model
    system : str, optional
        System prompt to use with the models
    collapsible_headers : bool, optional
        Whether to wrap responses in collapsible sections (default: True)
    header_template : str, optional
        Template string for headers, must contain {model} placeholder
    
    Yields:
    -------
    str
        Chunks of text from models in sequential order
    
    Returns:
    --------
    dict
        Dictionary mapping model instance IDs to their complete responses, 
        where model instance IDs follow the format "model_name_index"
    
    Notes:
    ------
    - If len(prompts) > len(model_names), model_names will be extended by repeating elements
    - When model names are repeated, unique identifiers are created internally (model_name_index)
      to avoid conflicts, but the original model name is used for display purposes
    - If a model completes before others start, the next model to respond will begin streaming immediately
    - Models are presented in order of first response, not in the order they were provided
    - The function returns a dictionary containing the complete responses, useful for further processing
    """

    from call_llm import CallLLm
    import traceback
    
    # Handle mismatch between prompts and model_names
    if len(prompts) > len(model_names):
        model_names = model_names * (len(prompts) // len(model_names)) + model_names[:len(prompts) % len(model_names)]
    elif len(prompts) < len(model_names):
        model_names = model_names[:len(prompts)]    
    
    if len(model_names) != len(prompts):
        raise ValueError("Number of models must match number of prompts")
    
    # Create model instance data with unique identifiers
    model_instances = []
    model_id_to_name = {}  # Mapping from unique ID to display name
    
    for i, (model, prompt) in enumerate(zip(model_names, prompts)):
        model_id = f"{model}_{i}"  # Create unique identifier
        model_instances.append((model_id, model, prompt))
        model_id_to_name[model_id] = model  # Store mapping for display purposes
    
    # Create a queue for communication between threads
    from queue import Queue
    response_queue = Queue()
    
    # Keep track of model responses for potential further processing
    model_responses = {}
    
    # Function to run a single LLM and collect its response
    def run_llm(model_id, model_name, prompt):
        try:
            llm = CallLLm(keys, model_name)  # Use original model name for API call
            response = llm(prompt, images, temperature, stream=True, max_tokens=max_tokens, system=system)
            
            # Collect the response chunks without additional wrapping
            model_response = ""
            for chunk in collapsible_wrapper(response, header=header_template.format(model=model_name), show_initially=collapsible_headers):
                model_response += chunk
                response_queue.put(("model", model_id, chunk))
            response_queue.put(("model", model_id, "\n\n"))
            
            # Store complete response and signal completion
            model_responses[model_id] = model_response
            response_queue.put(("complete", model_id))
        except Exception as e:
            error_msg = f"Error with model {model_name}: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            error_msg = collapsible_wrapper(error_msg, header=f"Error with {model_name}", show_initially=False)
            response_queue.put(("error", model_id, error_msg))
            response_queue.put(("complete", model_id))
    
    # Start a thread for each model instance
    futures = []
    for model_id, model_name, prompt in model_instances:
        future = get_async_future(lambda id=model_id, name=model_name, p=prompt: run_llm(id, name, p))
        futures.append(future)
    
    # Track which models have completed using model_id
    completed_models = set()
    
    # Create buffers to store chunks from each model using model_id
    model_buffers = {model_id: [] for model_id, _, _ in model_instances}
    streaming_order = []  # List to track the order in which models started streaming
    currently_streaming = None  # Which model is currently being streamed
    started_models = set()
    
    # Process the queue until all models complete
    while len(completed_models) < len(model_instances) or not response_queue.empty():
        try:
            # Get next item from queue with timeout
            item = response_queue.get(timeout=0.1)
            
            if item[0] == "model":
                model_id, chunk = item[1], item[2]
                
                # Add model to streaming order if it's not there yet
                if model_id not in streaming_order:
                    streaming_order.append(model_id)
                
                # If no model is currently streaming, start streaming this one
                if currently_streaming is None:
                    currently_streaming = model_id
                    # Set up the collapsible section if needed
                    
                    yield chunk
                    started_models.add(model_id)
                # If this is the currently streaming model, stream it directly
                elif model_id == currently_streaming:
                    yield chunk
                    started_models.add(model_id)
                # Otherwise, buffer the chunks
                else:
                    model_buffers[model_id].append(chunk)
            
            elif item[0] == "complete" or item[0] == "error":
                model_id = item[1]
                completed_models.add(model_id)
                if item[0] == "error":
                    yield f'\nError with {model_id_to_name[model_id]}: \n\n```\n{item[2]}\n```\n\n'
                
                # If this was the currently streaming model, close it and start the next one
                if currently_streaming == model_id:
                    # Close the current model's collapsible section if needed
                    
                    currently_streaming = None
                    
                    # Find the next model to stream
                    next_model_found = False
                    for next_model_id in streaming_order:
                        if next_model_id not in completed_models and next_model_id != model_id:
                            currently_streaming = next_model_id
                            # Stream all buffered chunks for this model
                            for buffered_chunk in model_buffers[next_model_id]:
                                yield buffered_chunk
                            # Clear the buffer
                            model_buffers[next_model_id] = []
                            next_model_found = True
                            break
                    # If no model in streaming_order is available, check if any other model has content
                    if not next_model_found:
                        for next_model_id, buffer in model_buffers.items():
                            if next_model_id not in completed_models and len(buffer) > 0:
                                currently_streaming = next_model_id
                                for buffered_chunk in buffer:
                                    yield buffered_chunk
                                model_buffers[next_model_id] = []
                                # Add to streaming order if not already there
                                if next_model_id not in streaming_order:
                                    streaming_order.append(next_model_id)
                                break
            
            
            else:
                raise Exception(f"Unknown item type: {item[0]}")
        
        except Exception:
            # Check if all futures are done to prevent infinite loops
            if all(future.done() or future.exception() is not None for future in futures):
                break

    # Final pass: check for any models that have buffered content but never got to stream
    # This ensures all model outputs are presented, even if they completed out of order
    for model_id in streaming_order:
        if model_buffers[model_id] and model_id not in started_models:
            currently_streaming = model_id
            # Stream all buffered chunks for this model
            for buffered_chunk in model_buffers[model_id]:
                yield buffered_chunk
            model_buffers[model_id] = []
    
    
    
    # Return the complete model responses dictionary for potential further processing
    return model_responses


import requests
import os

import tempfile
from flask_caching import Cache
# temp_dir = tempfile.gettempdir()
temp_dir = os.path.join(os.getcwd(), "storage", "cache")
# Create temp dir if not present
os.makedirs(temp_dir, exist_ok=True)
import diskcache as dc
cache = dc.Cache(temp_dir)
# cache = Cache(None, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': temp_dir, 'CACHE_DEFAULT_TIMEOUT': cache_days * 24 * 60 * 60})

import requests

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

def check_page_status(url):
    """
    Checks if a webpage is available. Tries an HTTP HEAD request first, then optionally
    falls back to a GET request if HEAD might not be supported or indicates an error.

    Returns:
        bool: True if the page is reachable (status < 400), otherwise False.
    """

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1'
    }

    timeout_seconds = 8

    # 1. Attempt HEAD request
    try:
        response = requests.head(url, headers=headers, timeout=timeout_seconds)

        # HEAD is successful and status < 400
        if response.ok:
            return True

        # HEAD might be unsupported - codes like 405 (Method Not Allowed), 501 (Not Implemented)
        # or simply an unexpected 4xx/5xx. We will try a fallback GET below.
    except (Timeout, ConnectionError, RequestException):
        # If it fails outright, we proceed to fallback
        pass

    # 2. Fallback to GET
    try:
        response_get = requests.get(url, headers=headers, timeout=timeout_seconds)
        return response_get.ok  # True if status < 400
    except (Timeout, ConnectionError, RequestException):
        # If GET fails, we return False
        return False
    

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.ERROR, logging.INFO, logging.ERROR, logging.INFO)

def convert_html_to_pdf(file_path, output_path):
    api_url = PDF_CONVERT_URL
    try:
        logger.info(f"Converting doc at {file_path} to pdf, file exists = {os.path.exists(file_path)}")
        assert os.path.exists(file_path)
        with open(file_path, 'rb') as f:
            files = {'files': (os.path.basename(file_path), f)}
            payload = {'pdfFormat': 'PDF/A-1a'}
            r = requests.post(api_url, files=files, data=payload)
            if r.status_code == 200:
                with open(output_path, 'wb') as out_file:
                    out_file.write(r.content)
                return True
            else:
                print(f"Conversion failed with status code {r.status_code}")
                return False
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"Exception converting doc at {file_path} to pdf: {e}\n{exc}")
        return False

class RunThread(threading.Thread):
    def __init__(self, func, args, kwargs):
        """
        https://stackoverflow.com/questions/55409641/asyncio-run-cannot-be-called-from-a-running-event-loop-when-using-jupyter-no
        """
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result = None
        super().__init__()

    def run(self):
        self.result = asyncio.run(self.func(*self.args, **self.kwargs))

def run_async(func, *args, **kwargs):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        thread = RunThread(func, args, kwargs)
        thread.start()
        thread.join()
        return thread.result
    else:
        return asyncio.run(func(*args, **kwargs))
    


class RunProcess(Process):
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.queue = Queue()
        super().__init__()

    def run(self):
        result = asyncio.run(self.func(*self.args, **self.kwargs))
        self.queue.put(result)

def run_async_process(func, *args, **kwargs):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        process = RunProcess(func, args, kwargs)
        process.start()
        process.join()
        return process.queue.get()
    else:
        return asyncio.run(func(*args, **kwargs))



def join_two_futures(future1, future2, join_method=lambda x, y: str(x) + "\n\n" + str(y), dtype=str):
    def fn(future1, future2, join_method):
        while not future1.done() or not future2.done():
            time.sleep(0.1)
        while not future1.done():
            time.sleep(0.1)
        while not future2.done():
            time.sleep(0.1)

        f1_fail = future1.exception()
        f2_fail = future2.exception()
        try:
            f1 = future1.result()
        except Exception as e:
            traceback.print_exc()
            f1 = dtype()
        try:
            f2 = future2.result()
        except Exception as e:
            traceback.print_exc()
            f2 = dtype()

        if f1_fail is not None and f2_fail is not None:
            raise Exception(f"Both futures failed, future1: {f1_fail}, future2: {f2_fail}")

        return join_method(f1, f2)
    return get_async_future(fn, future1, future2, join_method)




def execute_in_new_process(function, *args, **kwargs):
    logger.debug(f"type args = {type(args)}, type kwargs = {type(kwargs)}, Pickle able:: function = {is_picklable(function)}, {is_picklable(args)}, {is_picklable(kwargs)}, Is Dill able:: function = {is_dillable(function)}, {is_dillable(args)}, {is_dillable(kwargs)}")
    submit_st = time.time()
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(function, *args, **kwargs)
    
    submit_et = time.time()
    logger.info(f"Stuck on ProcessPoolExecutor for {(submit_et - submit_st):.2f} sec , done future state = {future.done()}")
    return future


def execute_in_new_thread(function, *args, **kwargs):
    logger.debug(
        f"type args = {type(args)}, type kwargs = {type(kwargs)}, Pickle able:: function = {is_picklable(function)}, {is_picklable(args)}, {is_picklable(kwargs)}, Is Dill able:: function = {is_dillable(function)}, {is_dillable(args)}, {is_dillable(kwargs)}")
    submit_st = time.time()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(function, *args, **kwargs)

    submit_et = time.time()
    logger.info(
        f"Stuck on ProcessPoolExecutor for {(submit_et - submit_st):.2f} sec , done future state = {future.done()}")
    return future

def call_api_parallel(api_calls, fn, max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks and collect Future objects
        futures = [executor.submit(fn, **api_call) for api_call in api_calls]

        # Collect results in order of input tasks
        results = [future.result() for future in futures]
    return results

def call_api_parallel_multi_fn(api_calls, fns):
    assert len(api_calls) == len(fns)
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit tasks and collect Future objects
        futures = [executor.submit(fn, **api_call) for fn, api_call in zip(fns, api_calls)]

        # Collect results in order of input tasks
        results = [future.result() for future in futures]
    return results


            

def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        time_logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds, result type: {type(result)}, {('result length:' + str(len(result))) if hasattr(result, '__len__') and isinstance(result, str) else ''}")
        return result
    return wrapper

def streaming_timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        accum = ''
        for r in func(*args, **kwargs):
            yield r
            accum = accum + r
        end_time = time.time()
        time_logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds")
    return wrapper

def print_nested(val, nesting = -5): 
    if isinstance(val, dict): 
        print('') 
        nesting += 5 
        print(nesting * ' ', end='') 
        print(type(val)) 
        for k in val: 
            print(nesting * ' ', end='') 
            print(k, end=':') 
            print_nested(val[k],nesting) 
    elif isinstance(val, (tuple, list)) and len(val) > 0 and isinstance(val[0], (dict, tuple, list)):
        nesting += 5
        print('') 
        print(nesting * ' ', end='') 
        print(type(val), end=":")
        print_nested(val[0], nesting) 
    else:
        print(type(val))


class AddAttribute:
    def __init__(self, attribute, value):
        self.attribute = attribute
        self.value = value

    def __call__(self, func):
        setattr(func, self.attribute, self.value)
        return func


class SetDescription(AddAttribute):
    def __init__(self, description):
        super().__init__('description', description)

from collections import deque
from datetime import datetime, timedelta
import calendar
cache_days = 1
cache_timeout = cache_days * 24 * 60 * 60

class CacheKeyFn:
    @staticmethod
    def get_key_fn_args():
        def key_fn_args(args, kwargs):
            return str(mmh3.hash(str(args) + str(kwargs), signed=False))
        return key_fn_args

    @staticmethod
    def get_key_fn_typed(types):
        def key_fn_typed(args, kwargs):
            filtered_args = [arg for arg in args if isinstance(arg, types)]
            filtered_kwargs = {k: v for k, v in kwargs.items() if isinstance(v, types)}
            return str(mmh3.hash(str(filtered_args) + str(filtered_kwargs), signed=False))
        return key_fn_typed

    @staticmethod
    def get_combined_key_fn(*key_fns):
        def combined_key_fn(args, kwargs):
            return "-".join(key_fn(args, kwargs) for key_fn in key_fns)
        return combined_key_fn

class CacheResults:
    def __init__(self, cache, key_function=CacheKeyFn.get_key_fn_args(),
                                                  dtype_filters=None,
                                                  should_cache_predicate=lambda x: x is not None and (not isinstance(x, Exception)) and (not isinstance(x, (list, tuple, set)) or len(x) > 0) and (not isinstance(x, str) or len(x.strip()) > 0),
                                                  should_cache_key_condition=lambda x: x is not None and (not isinstance(x, Exception)),
                                                  enabled=True, expire=cache_timeout):
        """
        A caching decorator class that caches the results of function calls using the `diskcache` library or any other cache object that supports similar interface.

        This class supports various expiration formats for cached data, making it suitable for use cases such as
        stock market data where data validity varies (e.g., daily, weekly, monthly, yearly).

        Attributes:
        -----------
        cache : diskcache.Cache
            The cache object to store the results.
        key_function : callable
            A function to generate a unique key for the cache based on the function arguments. Default is a hash of the arguments.
        dtype_filters : tuple
            A tuple of data types to filter the function arguments for generating the cache key. If dtype_filters is not None, the cache key will be generated based on the arguments that match the specified data types and key_function will be ignored. Default is None.
        should_cache_predicate : callable
            A predicate function to determine if the result should be cached. Default is a function that checks if the result is not None and not an empty collection.
        enabled : bool
            A flag to enable or disable caching.
        expire : int or str
            The expiration time for the cache. It can be a number (in seconds) or a string representing various time intervals or specific times/dates. Possible inputs include "minutely", "hourly", "daily", "weekly", "fortnightly", "monthly", "quarterly", "yearly", specific times (e.g., "12:00"), days of the week (e.g., "Sunday"), days of the month (e.g., "1st"), and months (e.g., "January"). Default is 86400 seconds (1 day).
        part_key : str
            A partial key used for generating the cache key.
        cache_metrics : collections.deque
            A deque to store cache metrics for performance monitoring.

        Methods:
        --------
        get_agg_cache_metrics():
            Aggregates and logs cache metrics.
        calculate_expiry(expire):
            Calculates the expiry time in seconds based on the current time and the specified interval or specific time/date.
        __call__(func):
            Decorator method to wrap the target function for caching its results.

        Parameters:
        -----------
        cache : diskcache.Cache
            The cache object to store the results.
        key_function : callable, optional
            A function to generate a unique key for the cache based on the function arguments. Default is a hash of the arguments.
        dtype_filters : list or tuple, optional
            A list or tuple of data types to filter the function arguments for generating the cache key. Default is None. If dtype_filters is not None, the cache key will be generated based on the arguments that match the specified data types and key_function will be ignored.
        should_cache_predicate : callable, optional
            A predicate function to determine if the result should be cached. Default is a function that checks if the result is not None and not an empty collection.
        enabled : bool, optional
            A flag to enable or disable caching. Default is True.
        expire : int or str, optional
            The expiration time for the cache. It can be a number (in seconds) or a string representing various time intervals or specific times/dates. Default is 86400 seconds (1 day). Possible inputs include "minutely", "hourly", "daily", "weekly", "fortnightly", "monthly", "quarterly", "yearly", specific times (e.g., "12:00"), days of the week (e.g., "Sunday"), days of the month (e.g., "1st"), and months (e.g., "January").

        Examples:
        ---------
        Basic usage with default expiration (1 day):

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
        def get_data(param1, param2):
            # Function implementation
            return data
        ```

        ```python
        @CacheResults(cache, key_function=lambda args, kwargs: str(mmh3.hash(str(args[0]), signed=False)), enabled=False,
              should_cache_predicate=lambda result: result is not None and "full_text" in result and len(result["full_text"].strip()) > 10)
        def process_link(link_title_context_apikeys, use_large_context=False):
            # Function implementation
            return result
        ```

        Usage with yearly expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="yearly")
        def get_annual_report(company_name):
            # Function implementation
            return annual_report
        ```

        Usage with daily expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="daily")
        def get_open_price(company_name):
            # Function implementation
            return open_price
        ```

        Usage with specific time expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="12:00")
        def get_midday_data(company_name):
            # Function implementation
            return midday_data
        ```

        Usage with day of the week expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="Sunday")
        def get_weekly_summary(company_name):
            # Function implementation
            return weekly_summary
        ```

        Usage with day of the month expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="13th")
        def get_monthly_data(company_name):
            # Function implementation
            return monthly_data
        ```

        Usage with month expiration:

        ```python
        @CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True, expire="June")
        def get_annual_meeting_data(company_name):
            # Function implementation
            return annual_meeting_data
        ```

        Notes:
        ------
        - The `expire` parameter can be a number (in seconds) or a string representing various time intervals or specific times/dates.
        - Supported string formats for `expire` include:
            - Intervals: "minutely", "hourly", "daily", "weekly", "fortnightly", "monthly", "quarterly", "yearly".
            - Specific Times: "HH:MM" (e.g., "12:00", "00:00").
            - Days of the Week: "Sunday", "Monday", etc.
            - Days of the Month: "1st", "2nd", "3rd", ..., "31st".
            - Months: "January", "February", ..., "December".
        - The `calculate_expiry` method handles the parsing and calculation of the expiry time based on the different formats.
        """
        self.cache = cache
        self.key_function = key_function
        self.dtype_filters = tuple(dtype_filters) if dtype_filters is not None else None
        self.should_cache_predicate = should_cache_predicate
        self.should_cache_key_condition = should_cache_key_condition
        self.enabled = enabled
        self.expire = expire
        self.part_key = None
        self.cache_metrics = deque([], maxlen=100) # each element is a dict with keys as module, get, set where get and set are seconds to get and set the cache

    def get_agg_cache_metrics(self):
        get_time = 0
        set_time = 0
        total_items = len(self.cache_metrics)
        for cache_time_dict in self.cache_metrics:
            get_time += cache_time_dict.get('get', 0)
            set_time += cache_time_dict.get('set', 0)
        time_logger.info(f"[CacheResults] [get_agg_cache_metrics] [Metrics] Total items: {total_items}, get_time: {get_time/total_items}, set_time: {set_time/total_items}, module: {self.part_key}")
        return {'get': get_time/total_items , 'set': set_time/total_items, 'module': self.part_key}

    def calculate_expiry(self, expire):
        now = datetime.now()
        if isinstance(expire, str):
            expire = expire.lower().strip()
        if isinstance(expire, int):
            return expire
        elif expire == "minutely":
            return 60 - now.second
        elif expire == "hourly":
            return 3600 - (now.minute * 60 + now.second)
        elif expire == "daily":
            return 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire == "weekly":
            return (7 - now.weekday()) * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire == "fortnightly":
            days_until_next_fortnight = (14 - (now.day % 14)) % 14
            return days_until_next_fortnight * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire == "monthly":
            days_in_month = calendar.monthrange(now.year, now.month)[1]
            return (days_in_month - now.day) * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire == "quarterly":
            current_month = now.month
            months_until_next_quarter = (3 - (current_month % 3)) % 3
            days_in_next_months = sum(
                calendar.monthrange(now.year, now.month + i)[1] for i in range(1, months_until_next_quarter + 1))
            return days_in_next_months * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire == "yearly":
            days_in_year = 366 if calendar.isleap(now.year) else 365
            return (days_in_year - now.timetuple().tm_yday) * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif ":" in expire:
            target_time = datetime.strptime(expire, "%H:%M").time()
            target_datetime = datetime.combine(now.date(), target_time)
            if target_datetime < now:
                target_datetime += timedelta(days=1)
            return (target_datetime - now).total_seconds()
        elif expire.lower() in calendar.day_name:
            target_day = list(calendar.day_name).index(expire.capitalize())
            days_until_target = (target_day - now.weekday()) % 7
            return days_until_target * 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        elif expire.lower() in calendar.month_name:
            target_month = list(calendar.month_name).index(expire.capitalize())
            months_until_target = (target_month - now.month) % 12
            target_date = datetime(now.year + (1 if months_until_target == 0 and now.month > target_month else 0),
                                   target_month, 1)
            return (target_date - now).total_seconds()
        elif expire[:-2].isdigit() and expire[-2:].lower() in ["st", "nd", "rd", "th"]:
            target_day = int(expire[:-2])
            target_date = datetime(now.year, now.month, target_day)
            if target_date < now:
                target_date += timedelta(days=calendar.monthrange(now.year, now.month + 1)[1])
            return (target_date - now).total_seconds()
        else:
            raise ValueError(f"Unsupported expire format: {expire}")

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self.enabled:
                cache = self.cache
                if self.part_key is None:
                    self.part_key = f"{func.__module__}:{func.__name__}"
                result_computed = False
                if self.dtype_filters is not None and len(self.dtype_filters) > 0:
                    sig = signature(func)
                    # Bind the arguments to the signature
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()

                    # Filter the arguments based on their type
                    filtered_args = {k: v for k, v in bound_args.arguments.items() if isinstance(v, self.dtype_filters)}
                    key = f"{self.part_key}:{str(mmh3.hash(str(filtered_args), signed=False))}"
                else:
                    key = f"{self.part_key}:{self.key_function(args, kwargs)}"
                cache_time_dict = dict()
                st = time.time()
                result = cache.get(key)
                et_get = time.time() - st
                cache_time_dict["module"] = self.part_key
                cache_time_dict['get'] = et_get
                self.cache_metrics.append(cache_time_dict)
                if result is None or isinstance(result, (Exception, AssertionError, ValueError, RetryError)) or (
                        isinstance(result, (list, tuple, set)) and len(result) == 0):
                    result = func(*args, **kwargs)
                    result_computed = True
                if result is not None and not isinstance(result, (Exception, AssertionError, ValueError, RetryError)) and not (
                        isinstance(result, (list, tuple, set)) and len(result) == 0) and self.should_cache_predicate(result) and result_computed and self.should_cache_key_condition(key):
                    st_set = time.time()
                    expire_seconds = self.calculate_expiry(self.expire)
                    cache.set(key, result, expire=expire_seconds)
                    et_set = time.time() - st_set
                    cache_time_dict['set'] = et_set
                self.get_agg_cache_metrics()
                return result
            else:
                assert func is not None
                return func(*args, **kwargs)

        return wrapper

def NoneToDefault(x, default=[]):
    if x is None:
        return default
    else:
        return x
    

    
def combine_array_two_at_a_time(array, sep=' '):
    result = []
    if len(array) % 2 == 1:
        array.append('')
    for i in range(0, len(array), 2):
        result.append(array[i] + f'{sep}' + array[i+1])
    return result

def concat_array_two_at_a_time(array):
    result = []
    if len(array) % 2 == 1:
        array.append('')
    for i in range(0, len(array), 2):
        result.append([array[i],array[i+1]])
    return result

def make_stream(res, do_stream:bool):
    is_generator = inspect.isgenerator(res)
    if is_generator and do_stream:
        res = check_if_stream_and_raise_exception(res)
        return res
    if do_stream and not is_generator:
        assert isinstance(res, (str, list, tuple)) or isinstance(res, more_itertools.more.peekable) or isinstance(res, peekable) or hasattr(res, '__iter__') or hasattr(res, '__next__')
        return convert_iterable_to_stream(res)
    elif not do_stream and is_generator:
        return convert_stream_to_iterable(res)
    return res

def call_with_stream(fn, do_stream, *args, **kwargs):
    backup = kwargs.pop('backup_function', None)
    try:
        res = fn(*args, **kwargs)
    except RetryError as e:
        logger.error(f"RetryError: {e}")
        if backup is not None:
            res = backup(*args, **kwargs)
        else:
            raise e
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"Exception: {e}, \n{trace}")
        if backup is not None:
            res = backup(*args, **kwargs)
        else:
            raise e
    is_generator = inspect.isgenerator(res)
    if is_generator:
        try:
            res = check_if_stream_and_raise_exception(res)
        except Exception as e:
            # check if exception is not StopIteration
            try:
                from botocore.exceptions import EventStreamError
                if not isinstance(e, StopIteration) and backup is not None:
                    res = backup(*args, **kwargs)
                else:
                    raise e
            except Exception as j:
                raise e
    if is_generator:
        res = check_if_stream_and_raise_exception(res)
    if do_stream and not is_generator:
        assert isinstance(res, (str, list, tuple))
        return convert_iterable_to_stream(res)
    elif not do_stream and is_generator:
        return convert_stream_to_iterable(res)
    return res
        
def convert_iterable_to_stream(iterable):
    for t in iterable:
        yield t

def convert_stream_to_iterable(stream, join_strings=True):
    ans = []
    for t in stream:
        ans.append(t)
    if isinstance(ans[0], str) and join_strings:
        ans = "".join(ans)
    return ans

def check_if_stream_and_raise_exception(iterable_or_str):
    if isinstance(iterable_or_str, str):
        # If it's a string, just return it as it is.
        return iterable_or_str
    elif isinstance(iterable_or_str, more_itertools.more.peekable):
        return iterable_or_str
    elif isinstance(iterable_or_str, types.GeneratorType):
        # If it's a generator, we need to peek at it.
        try:
            peeked = peekable(iterable_or_str)
            peek_val = peeked.peek()  # This will raise StopIteration if the generator is empty.
            return peeked
        except StopIteration:
            # Here you could handle the empty generator case.
            raise
        except Exception as e:
            # Here you could handle other exceptions.
            raise e
    elif isinstance(iterable_or_str, peekable):
        return iterable_or_str
    else:
        # If it's not a string or a generator, raise an exception.
        raise ValueError("Unexpected input type.")


import tiktoken
gpt4_enc = tiktoken.encoding_for_model('gpt-4')
gpt3_enc = tiktoken.encoding_for_model('gpt-3.5-turbo')
def get_first_n_words(my_string, n=700):
    return get_first_last_parts(my_string, first_n=n, last_n=0)

def get_gpt4_word_count(my_string):
    import tiktoken
    enc = tiktoken.encoding_for_model('gpt-4')
    str_encoded = enc.encode(my_string)
    return len(str_encoded)

def get_gpt3_word_count(my_string):
    import tiktoken
    enc = tiktoken.encoding_for_model('gpt-3.5-turbo')
    str_encoded = enc.encode(my_string)
    return len(str_encoded)
def get_first_last_parts(my_string, first_n=250, last_n=750, enc=None):
    import tiktoken
    if enc is None:
        enc = tiktoken.encoding_for_model('gpt-4')
    str_encoded = enc.encode(my_string)
    if len(str_encoded) < first_n + last_n:
        return my_string
    str_len = len(str_encoded)
    first_part = enc.decode(str_encoded[:first_n])
    last_part = enc.decode(str_encoded[str_len-last_n:])
    return first_part + "\n" + last_part

def convert_to_pdf_link_if_needed(link):
    if "arxiv.org" in link and "pdf" not in link and "html" not in link:
        link = link.replace("abs", "pdf") + ".pdf"
        # convert arxiv link to pdf
    if "openreview.net" in link and "pdf" not in link:
        link = link.replace("forum", "pdf")
        # convert openreview link to pdf
    if "aclanthology.org" in link and "pdf" not in link:
        link = (link[:-1] + ".pdf") if link[-1] == "/" else (link + ".pdf")
    if "aclweb.org" in link and "anthology" in link and "pdf" not in link:
        # https://www.aclweb.org/anthology/P19-1028/
        link = (link[:-1] + ".pdf") if link[-1] == "/" else (link + ".pdf")
        # convert aclweb link to pdf
    return link

def extract_array_string(s):
    # Try to find content inside markdown code blocks
    code_block_match = re.search(r'```(?:\w+)?\s*([\s\S]*?)\s*```', s)
    if code_block_match:
        # Extract content from the code block and recursively process it
        code_content = code_block_match.group(1).strip()
        # If the code block content looks like an array, process it
        if code_content.startswith('[') and code_content.endswith(']'):
            return code_content
        # Otherwise, try other patterns on the code content
        inner_result = extract_array_string(code_content)
        if inner_result:
            return inner_result

    # Try to find text inside square brackets
    match = re.search(r'\[.*?\]', s)
    if match:
        return match.group(0)

    # Check for queries separated by one or two newlines
    # ... existing code ...
    newline_separated = re.split(r'\n\n|\n', s.strip())
    if newline_separated and all(len(query.strip().split()) >= 3 for query in newline_separated) and len(newline_separated) >= 3:
        return newline_separated
    
    # Try to find markdown list
    # ... existing code ...
    markdown_list = re.findall(r'^[-*] (.+)$', s, flags=re.M)
    if markdown_list:
        return markdown_list

    # If a single string, return it in an array
    # ... existing code ...
    if s.strip() and ' ' in s.strip() and len(s.strip().split()) <=10:
        return [s.strip()]

    # If all else fails, return an empty list
    return [s.strip().split('\n')[0]]

def parse_array_string(s):
    result = extract_array_string(s)
    if result and isinstance(result, str) and result.startswith('['):
        result = re.sub(r"(?<=[a-zA-Z0-9])'(?!(, ?|]))", "@@", result)
        parsed_list = eval(result)
        return [i.replace("@@", "'") for i in parsed_list]
    elif result and isinstance(result, list):
        return result
    else:
        return []


def normalize_whitespace(s):
    if s is None:
        return ""
    # Replace multiple spaces with a single space
    s = re.sub(r' {2,}', ' ', s)

    # Replace multiple tabs with a single tab
    s = re.sub(r'\t{2,}', '\t', s)

    # Replace multiple blank lines with a single blank line
    s = re.sub(r'\n\s*\n', '\n\n', s)

    return s.strip()


def verify_openai_key_and_fetch_models(api_key):
    logger.warning("Verifying OpenAI API key...")
    # Make a GET request to OpenAI API
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get("https://api.openai.com/v1/models", headers=headers)

    if response.status_code == 200:
        # Extract model ids and return as a list
        models = response.json()["data"]
        model_ids = [model["id"] for model in models]
        return model_ids
    else:
        # Handle error response
        print(f"Error fetching OpenAI models: {response.status_code} {response.reason}")
        return []

def two_column_list(items):
    half = (len(items) + 1) // 2   # adjust for odd lengths
    column1 = items[:half]
    column2 = items[half:]

    output = '<table><tr><td><ul>'
    for item in column1:
        output += f'<li>{item}</li>'
    output += '</ul></td><td><ul>'
    for item in column2:
        output += f'<li>{item}</li>'
    output += '</ul></td></tr></table>'

    return output

def two_column_list_md(items):
    half = (len(items) + 1) // 2   # adjust for odd lengths
    column1 = items[:half]
    column2 = items[half:]

    # Create a Markdown table with two columns
    output = '| Column 1 | Column 2 |\n| --- | --- |\n'
    for item1, item2 in zip(column1, column2 + [None]):
        # Check if item2 is None (in case of odd number of items)
        second_column_item = item2 if item2 is not None else ""
        output += f'| {item1} | {second_column_item} |\n'

    # If there are an odd number of items, we'll add the last item
    if len(items) % 2 != 0:
        output += f'| {items[-1]} | |\n'

    return output


class SetQueue:
    def __init__(self, maxsize):
        self.maxsize = maxsize
        self.queue = collections.deque(maxlen=maxsize)
        self.set = set()
        self.lock = threading.RLock()

    def remove_any(self, item):
        with self.lock:
            if item in self.set:
                self.set.remove(item)
                self.queue.remove(item)
    
    def add(self, item):
        with self.lock:
            self.remove_any(item)
            if len(self.queue) >= self.maxsize - 1:
                removed = self.queue.popleft()
                self.set.remove(removed)
            self.queue.append(item)
            self.set.add(item)

    def __contains__(self, item):
        with self.lock:
            return item in self.set

    def __len__(self):
        with self.lock:
            return len(self.queue)

    def items(self):
        with self.lock:
            return list(self.queue)


import collections
import threading


class DefaultDictQueue:
    def __init__(self, maxsize, default_factory=None):  # Added default_factory parameter
        self.maxsize = maxsize
        self.queue = collections.deque(maxlen=maxsize)
        self.set_of_items = set()
        self.data = dict()
        self.lock = threading.RLock()
        self.default_factory = default_factory  # Save the default factory

    def __delitem__(self, key):
        with self.lock:
            if key in self.set_of_items:
                self.set_of_items.remove(key)
                self.queue.remove(key)
                del self.data[key]

    def remove_any(self, item):
        with self.lock:
            if item in self.set_of_items:
                self.set_of_items.remove(item)
                self.queue.remove(item)
                del self.data[item]

    def add(self, item, item_data=None):  # Modified to allow adding an item without data
        with self.lock:
            self.remove_any(item)
            if len(self.queue) >= self.maxsize - 1:
                removed = self.queue.popleft()
                self.set_of_items.remove(removed)
                del self.data[removed]
            self.queue.append(item)
            self.set_of_items.add(item)
            self.data[item] = item_data if item_data is not None else self.default_factory(item) if self.default_factory else None

    def __contains__(self, item):
        with self.lock:
            return item in self.set_of_items

    def __len__(self):
        with self.lock:
            return len(self.queue)

    def items(self):
        with self.lock:
            return list(self.queue)

    def get_data(self, item):
        with self.lock:
            if item not in self.set_of_items and self.default_factory:
                self.add(item, self.default_factory(item))
            return self.data.get(item, None)

    def __getitem__(self, item):
        return self.get_data(item)

    def get(self, item):
        return self.get_data(item)

    def set(self, item, data, *args, **kwargs):
        self.__setitem__(item, data, *args, **kwargs)


    def __setitem__(self, item, data, *args, **kwargs):
        with self.lock:
            if item in self.set_of_items:
                self.data[item] = data
            else:
                self.add(item, data)
                
                
from collections import OrderedDict
import threading

class SetQueueWithCount:
    def __init__(self, maxsize):
        self.maxsize = maxsize
        self._data = OrderedDict()  # key: item, value: count
        self.lock = threading.RLock()

    def add(self, item):
        with self.lock:
            # If item already present, just move to end and increment count
            if item in self._data:
                self._data[item] += 1
                self._data.move_to_end(item, last=True)
            else:
                # Check capacity
                if len(self._data) >= self.maxsize:
                    # Pop oldest
                    self._data.popitem(last=False)
                # Insert new
                self._data[item] = 1

    def remove_any(self, item):
        with self.lock:
            if item in self._data:
                del self._data[item]

    def count(self, item):
        with self.lock:
            return self._data.get(item, 0)

    def __contains__(self, item):
        with self.lock:
            return item in self._data

    def __len__(self):
        with self.lock:
            return len(self._data)

    def items(self):
        with self.lock:
            return list(self._data.keys())

def convert_http_to_https(url):
    parsed_url = urlparse(url)
    https_url = parsed_url._replace(scheme='https')
    return urlunparse(https_url)

def get_peekable_iterator(iterable):
    from more_itertools import peekable
    p = peekable(iterable)
    try:
        _ = p.peek(10)
    except StopIteration:
        _ = p.peek()
        return p
    return p

def truncate_string(input_str, n):
    # This list will store the original separators for each word
    separators = []

    # Replace all separators with a space and remember the original separator
    for sep in [',', '\n', '\t', '\r', ';', '"', "'", '(', ')', '{', '}', '[', ']', '<', '>', '?', '/', '\\', '|', '`', '~', '!', '@', '#', '$', '%', '^', '&', '*', '-', '_', '+', '=', ':', '.']:
        input_str = input_str.replace(sep, ' ')
        separators.append(sep)

    # Split the string into words
    words = input_str.split(' ')

    # Remove the last n words
    truncated_words = words[:-n]

    # Join the words back together using the original separators
    truncated_str = ''
    for word in truncated_words:
        # Check if the word ends with a separator and add it back if it does
        for sep in separators:
            if word.endswith(sep):
                word = word.rstrip(sep) + sep
        truncated_str += word + ' '
    # Remove the trailing space
    truncated_str = truncated_str.rstrip(' ')
    return truncated_str


from collections import defaultdict, deque


def round_robin_by_group(dict_list, group_key='group'):
    # Group dictionaries by 'group' key
    groups = defaultdict(list)
    for d in dict_list:
        groups[d[group_key]].append(d)

    # Convert groups to a deque of deques for round-robin iteration
    groups = deque(deque(group) for group in groups.values())

    while groups:
        group = groups.popleft()  # Take the next group
        yield group.popleft()  # Yield the next dictionary from this group

        if group:  # If the group still has dictionaries, put it back at the end
            groups.append(group)

from collections import OrderedDict
from threading import Lock, RLock


class FixedSizeFIFODict(OrderedDict):
    def __init__(self, size):
        super().__init__()
        self.size = size
        self.lock = RLock()  # Initialize a lock for thread-safe operations

    def __setitem__(self, key, value, expiry=None):
        with self.lock:  # Use the lock to ensure thread-safe access
            # Calculate expiry time as current time + expiry seconds
            expiry_time = None if expiry is None else time.time() + expiry
            # Store the value along with its expiry time
            super().__setitem__(key, (value, expiry_time))
            self.move_to_end(key)  # Move the accessed/updated item to the end
            self.ensure_fixed_size()
            self.remove_expired_items()  # Remove expired items

    def __getitem__(self, key):
        with self.lock:
            value, expiry_time = super().__getitem__(key)
            # Check if the item has expired
            if expiry_time is not None and expiry_time < time.time():
                # If expired, remove the item and raise KeyError
                del self[key]
                raise KeyError(f"Key '{key}' is expired and has been removed.")
            self.move_to_end(key)  # Move the accessed item to the end
            return value  # Return the actual value

    def set(self, key, value, expiry=None, **kwargs):
        with self.lock:
            # Delegate to __setitem__ to handle insertion, order maintenance, and expiry
            self.__setitem__(key, value, expiry=expiry)

    def ensure_fixed_size(self):
        while len(self) > self.size:
            self.popitem(last=False)  # Remove the oldest item

    def get(self, key, default=None):
        with self.lock:
            try:
                return self[key]  # Attempt to get the item, which checks for expiry
            except KeyError:
                return default  # Return default if the key is not found or expired

    def remove_expired_items(self):
        # Remove items that have expired
        with self.lock:
            current_time = time.time()
            keys_to_delete = [key for key, (_, expiry_time) in self.items() if
                              expiry_time is not None and expiry_time < current_time]
            for key in keys_to_delete:
                del self[key]


from inspect import signature
from functools import wraps
import mmh3
def typed_memoize(cache, *types):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Get the function's signature
            sig = signature(f)

            # Bind the arguments to the signature
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Filter the arguments based on their type
            filtered_args = {k: v for k, v in bound_args.arguments.items() if isinstance(v, types)}

            # Define a key function that generates a cache key based on the filtered arguments
            key = f"{f.__module__}:{f.__name__}:{str(filtered_args)}"

            # Try to get the result from the cache
            key = str(mmh3.hash(key, signed=False))
            result = cache.get(key)
            # If the result is not in the cache, call the function and store the result in the cache
            if result is None or isinstance(result, Exception) or (isinstance(result, (list, tuple, set)) and len(result) == 0):
                result = f(*args, **kwargs)
            if result is not None and not isinstance(result, Exception) and not (isinstance(result, (list, tuple, set)) and len(result) == 0):
                cache.set_of_items(key, result, expire=cache_timeout)

            return result

        return wrapper
    return decorator

import requests
os_temp_dir = tempfile.gettempdir()

def create_tmp_marker_file(file_path):
    marker_file_path = os.path.join(os_temp_dir, file_path + ".tmp")
    with open(marker_file_path, 'w') as f:
        f.write(f"{file_path}")
    return marker_file_path

def remove_tmp_marker_file(file_path):
    if file_path is None:
        return None
    try:
        marker_file_path = os.path.join(os_temp_dir, file_path + ".tmp")
        if os.path.exists(marker_file_path):
            os.remove(marker_file_path)
        return marker_file_path
    except Exception as e:
        logger.error(f"Exception removing tmp marker file: {e}\n{traceback.format_exc()}")
        return None

def exists_tmp_marker_file(file_path):
    if file_path is None:
        return True
    marker_file_path = os.path.join(os_temp_dir, file_path + ".tmp")
    return os.path.exists(marker_file_path)

@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def is_pdf_link(link):
    st = time.time()
    result = False
    science_doc = ("arxiv.org" in link and ("pdf" in link or "html" in link or "abs" in link)) or ("openreview.net" in link and "pdf" in link) or ("aclanthology.org" in link and "pdf" in link) or ("aclweb.org" in link and "anthology" in link and "pdf" in link)
    ends_with_pdf = link.endswith(".pdf")
    if science_doc or ends_with_pdf:
        result = True
    else:
        response = ProcessFnWithTimeout(Queue())(requests.head, 8, link)
        content_type = response.headers.get('Content-Type') if response is not None else None
        result = (content_type is not None and (content_type == 'application/pdf' or 'pdf' in content_type))
    et = time.time() - st
    logger.debug(f"Time taken to check if link is pdf: {et:.2f} sec, is science doc: {science_doc}, ends with .pdf: {ends_with_pdf,} result: {result}")
    return result

@CacheResults(cache=cache, dtype_filters=[str, int, tuple, bool], enabled=True)
def is_image_link(link):
    st = time.time()
    result = False
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.ico']
    # Check if the link is an image based on the file extension
    # remove query params from link
    link = link.split('?')[0]
    is_image = any([link.endswith(ext) for ext in image_extensions])
    if is_image:
        result = True
    else:
        response = ProcessFnWithTimeout(Queue())(requests.head, 8, link)
        content_type = response.headers.get('Content-Type') if response is not None else None
        result = (content_type is not None and ('image' in content_type))
    et = time.time() - st
    logger.debug(f"Time taken to check if link is image: {et:.2f} sec, is image link: {link}, result: {result}")
    return result


import threading
from queue import Queue

class ProcessFnWithTimeout:
    def __init__(self, result_queue: Queue):
        self.result_queue = result_queue

    def __call__(self, fn, timeout, *args, **kwargs):
        timeout = kwargs.get('timeout', timeout)
        keep_going_marker = kwargs.get('keep_going_marker', None)
        result = None
        exception_event = threading.Event()

        def worker():
            nonlocal result
            try:
                result = fn(*args, **kwargs)  # Call the original function with its args and kwargs
            except Exception as e:
                exc = traceback.format_exc()
                # Handle exceptions if needed
                logger.error(f"Exception processing function {fn.__name__}: {e}\n{exc}")
            finally:
                exception_event.set()

        thread = threading.Thread(target=worker)
        thread.start()
        # Wait for either the result to be ready or the timeout to occur
        exception_event.wait(timeout)
        if not exception_event.is_set():
            print(f"Timeout processing function {fn.__name__} , timeout = {timeout}")
            result = None  # Use None to indicate timeout

        # Put the result (or None if there was a timeout) in the queue
        self.result_queue.put(result)
        return result


from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue


def orchestrator(fn, args_list, callback=None, max_workers=32, timeout=60):

    if timeout < 0:
        raise ValueError("Timeout must be non-negative")

    task_queue = Queue()

    def task_worker(args, kwargs):
        try:
            wait_time = kwargs.get('timeout', timeout)
            result = ProcessFnWithTimeout(Queue())(fn, wait_time, *args, **kwargs)
            if callback and result is not None:
                result = callback(result, args, kwargs)
            task_queue.put(result)
        except Exception as e:
            exc = traceback.format_exc()
            logger.error(f"[orchestrator] Exception in task_worker with timeout = {timeout} : {e}\n{exc}")
            task_queue.put(None)  # Put None to indicate an error

    def run_tasks():
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = []
                for task in args_list:
                    if task is None:
                        continue
                    args, kwargs = task
                    futures.append(pool.submit(task_worker, args, kwargs))
        except Exception as e:
            exc = traceback.format_exc()
            logger.error(f"[orchestrator] Exception in run_tasks with timeout = {timeout} : {e}\n{exc}")
        finally:
            # Signal the end of the task results
            task_queue.put(FINISHED_TASK)
            task_queue.put(FINISHED_TASK) # this line has to be repeated so that we can handle the second queue poll after staggered LLM response.

    # Start a separate thread to run the tasks
    orchestrator_thread = threading.Thread(target=run_tasks)
    orchestrator_thread.start()

    # Return the task queue immediately
    return task_queue


from concurrent.futures import Future



def orchestrator_with_queue(input_queue, fn, callback=None, max_workers=32, timeout=60):
    task_queue = Queue()

    def task_worker(result, args, kwargs):
        try:
            wait_time = kwargs.get('timeout', timeout)
            if result is not TERMINATION_SIGNAL:
                new_result = ProcessFnWithTimeout(Queue())(fn, wait_time, *args, **kwargs)
                if callback and new_result is not None:
                    new_result = callback(new_result, args, kwargs)
                task_queue.put(new_result)
        except Exception as e:
            exc = traceback.format_exc()
            logger.error(f"[orchestrator_with_queue] Exception in task_worker with timeout = {timeout} : {e}\n{exc}")
            task_queue.put(None)  # Put None to indicate an error

    def run_tasks():
        try:
            args_list = []
            futures = []
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                while True:
                    # handle if input_queue is a generator or a zip object
                    if isinstance(input_queue, types.GeneratorType) or isinstance(input_queue, zip):
                        try:
                            result = next(input_queue)
                        except StopIteration:
                            result = TERMINATION_SIGNAL
                    elif isinstance(input_queue, Queue):
                        result = input_queue.get()
                    elif isinstance(input_queue, (list, tuple)):
                        result = input_queue.pop(0) if len(input_queue) > 0 else None
                    else:
                        raise ValueError("Invalid input_queue type")
                    if result is TERMINATION_SIGNAL or result is FINISHED_TASK or result == FINISHED_TASK:  # End of results
                        break
                    if result is None:
                        continue
                    args, kwargs = result
                    future = pool.submit(task_worker, result, [args], kwargs)
                    futures.append(future)
        except Exception as e:
            exc = traceback.format_exc()
            logger.error(f"[orchestrator_with_queue] Exception in run_tasks with timeout = {timeout} : {e}\n{exc}")
        finally:
            # Signal the end of the task results
            task_queue.put(TERMINATION_SIGNAL)
            task_queue.put(FINISHED_TASK)

    # Start a separate thread to run the tasks
    orchestrator_thread = threading.Thread(target=run_tasks)
    orchestrator_thread.start()

    # Return the task queue immediately
    return task_queue


def dual_orchestrator(fn1, fn2, args_list, callback=None, max_workers=32, timeout1=60, timeout2=60):

    task_queue1 = orchestrator(fn1, args_list, max_workers=max_workers, timeout=timeout1)
    task_queue2 = orchestrator_with_queue(task_queue1, fn2, callback, max_workers=max_workers, timeout=timeout2)

    return task_queue2

def yield_with_condition(yield_value, condition_function, failure_call_back):
    if condition_function():
        return yield_value
    else:
        return failure_call_back()

def remove_leading_spaces(text):
    lines = text.splitlines()
    in_code_block = False
    for i, line in enumerate(lines):
        if re.match(r'^<code>|^```|^`', line):
            in_code_block = not in_code_block
        if not in_code_block:
            lines[i] = line.lstrip()
    return '\n'.join(lines)
def remove_bad_whitespaces(s):
    s = re.sub(' +', ' ', s)  # Remove extra whitespaces
    s = re.sub("\n{2,}", "\n", s)
    s = re.sub("\r+", "\n", s)
    lines = s.splitlines(keepends=False)
    lines = [line.rstrip().lstrip() for line in lines if line.strip()!='']
    s = '\n'.join(lines)
    s = remove_leading_spaces(s)
    # s = normalize_whitespace(s)
    return s.strip()

def remove_bad_whitespaces_easy(s):
    s = re.sub("\n{2,}", "\n", s)
    s = re.sub("\r+", "\n", s)
    lines = s.splitlines(keepends=False)
    lines = [line.rstrip() for line in lines]
    s = '\n'.join(lines)
    # s = normalize_whitespace(s)
    return s.strip()

def reformat_string(input_str):
    words = input_str.split("\n")
    corrected_words = []
    prev_word_ended_sentence = False

    for i, word in enumerate(words):
        # If the previous word ended with a sentence-ending punctuation, then
        # this newline is likely intentional.
        if prev_word_ended_sentence:
            corrected_words.append("\n")
            prev_word_ended_sentence = False

        # Check if this word ends with a sentence-ending punctuation.
        if word.endswith(('.', '!', '?')):
            prev_word_ended_sentence = True

        if word in {',', '.', '!', '?', ';'}:
            corrected_words[-1] += word
        else:
            corrected_words.append(word)

    return " ".join(corrected_words)


def find_nearest_divisible_by_three(arr):
    # Start from the last index
    for i in range(len(arr) - 1, -1, -1):
        # Check if the current index (i + 1 because index starts from 0) is divisible by 3
        if (i + 1) % 3 == 0:
            return arr[i]
    # Return a message if no such element is found
    return "No element found with index divisible by 3"

import queue
import threading

def thread_safe_tee(iterable, n=2):
    queues = [queue.Queue() for _ in range(n)]
    def generator(queues):
        for item in iterable:
            for ix, q in enumerate(queues):
                q.put(item)
                # logger.info(f"thread_safe_tee putting item for {ix}-th queue: {item}")
        for q in queues:
            q.put(StopIteration)
    threading.Thread(target=generator, args=(queues,)).start()

    def gen(ix, q):
        while True:
            item = q.get()
            if item is StopIteration:
                return
            # logger.info(f"thread_safe_tee yielding item for {ix}-th queue: {item}")
            yield item
            time.sleep(0.01)

    return tuple(gen(ix, q) for ix, q in enumerate(queues))


from langchain_openai import OpenAIEmbeddings
from typing import List, Optional, Dict, Any
import numpy as np
import requests
from typing import List, Union


def get_jina_embedding(input_text: Union[str, List[str]], model_name: str, api_key: str, ctx_length: int = 10_000, ctx_chunk_size: int = 4000) -> Union[
    List[float], List[List[float]]]:
    """
    Fetches the embedding(s) for the given input text using Jina's embedding service.
    
    Parameters:
    - input_text: The text (or texts) for which to generate the embedding(s)
    - model_name: The Jina model to use (e.g., 'jina-embeddings-v3')
    - api_key: The Jina API key for authorization
    
    Returns:
    - A list of floats representing the embedding, or a list of lists of floats if the input was a list of strings
    """
    # Define the URL for the Jina API embeddings endpoint
    url = "https://api.jina.ai/v1/embeddings"

    # Prepare the headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # Preprocess input text
    if isinstance(input_text, list):
        # Handle list of strings
        processed_texts = [
            " ".join(text[:ctx_length].strip().split()[:ctx_chunk_size]) if text else "<EMPTY STRING>"
            for text in input_text
        ]
        # Remove empty strings and replace with placeholder
        processed_texts = [
            text if len(text.strip()) > 0 else "<EMPTY STRING>" 
            for text in processed_texts
        ]
    else:
        # Handle single string
        processed_texts = [" ".join(input_text[:ctx_length].strip().split()[:ctx_chunk_size])]

    # Prepare the data payload
    data = {
        "model":  "jina-embeddings-v3",
        "input": processed_texts,
        "task": "text-matching",
        "dimensions": "512",
        "embedding_type": "float"
    }

    try:
        # Send POST request to the API
        response = requests.post(url, headers=headers, json=data)
        
        # Check if request was successful
        if response.status_code == 200:
            response_json = response.json()
            
            # Extract embeddings from response
            embeddings = [item["embedding"] for item in response_json["data"]]
            
            # Return single embedding list if input was a string
            if not isinstance(input_text, list):
                return embeddings[0]
            return embeddings
            
        else:
            # Handle API errors
            logger.error(f"Failed to fetch embedding(s) with model = {model_name} for input text with len: "
                        f"{(len(processed_texts), len(processed_texts[0].split()))}")
            raise Exception(f"Failed to fetch embedding(s): {response.text}")
            
    except Exception as e:
        # Handle request errors
        logger.error(f"Exception in get_jina_embedding: {str(e)}")
        if ctx_length > 2000:
            return get_jina_embedding(input_text, model_name, api_key, ctx_length=ctx_length//2, ctx_chunk_size=ctx_chunk_size//2)
        
        raise Exception(f"Failed to fetch embedding(s): {str(e)}")


def get_openai_embedding(
    input_text: Union[str, List[str]],
    model_name: str,
    api_key: str,
    ctx_length: int = 10_000,
    ctx_chunk_size: int = 4_000
) -> Union[List[float], List[List[float]]]:
    """
    Fetches the embedding(s) for the given input text using the specified model,
    similarly to the logic in `get_jina_embedding`. It accepts two parameters:
    `ctx_length` and `ctx_chunk_size`. 
    - We first reduce the text length to `ctx_length` 
    - Then limit the number of tokens/words to `ctx_chunk_size`.
    If the request fails and `ctx_length` is still above 2000, we retry with half 
    of both parameters, providing a fallback for extremely large inputs or partial failures.

    Parameters:
    -----------
    input_text : str or List[str]
        The text (or list of texts) for which to generate the embedding(s).
    model_name : str
        The OpenAI model name to use for generating the embeddings.
    api_key : str
        The OpenAI API key for authorization.
    ctx_length : int, optional
        Maximum length in characters to keep from the input text, defaults to 10,000.
    ctx_chunk_size : int, optional
        Maximum number of tokens/words to slice from the text, defaults to 4,000.

    Returns:
    --------
    List[float] or List[List[float]]
        If a single string is passed in, returns a single list of floats.
        If a list of strings is passed in, returns a list of lists of floats.

    Raises:
    -------
    Exception
        If the API request to OpenAI fails or returns a non-200 response, and 
        the fallback recursion fails once ctx_length <= 2000.
    """

    # Define the OpenAI embeddings endpoint
    url = "https://api.openai.com/v1/embeddings"

    # Prepare request headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # Preprocess input text with ctx_length & ctx_chunk_size
    if isinstance(input_text, list):
        processed_texts = [
            " ".join(text[:ctx_length].strip().split()[:ctx_chunk_size]) if text else "<EMPTY STRING>"
            for text in input_text
        ]
        # Make sure we replace empty strings with a placeholder
        processed_texts = [
            text if len(text.strip()) > 0 else "<EMPTY STRING>"
            for text in processed_texts
        ]
    else:
        processed_texts = [
            " ".join(input_text[:ctx_length].strip().split()[:ctx_chunk_size])
        ]

    # Construct the JSON payload
    data = {
        "input": processed_texts,
        "model": model_name
    }

    try:
        # Send request
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Will trigger exception if status is not 2xx

        response_json = response.json()
        # Extract embeddings
        embeddings = [item["embedding"] for item in response_json["data"]]

        # If the original input was a single string, return the first embedding as a list
        if not isinstance(input_text, list):
            return embeddings[0]
        return embeddings

    except Exception as e:
        logger.error(f"Exception in get_openai_embedding: {str(e)}")
        # If ctx_length > 2000, try again with smaller ctx_length & ctx_chunk_size
        if ctx_length > 2000:
            return get_openai_embedding(
                input_text=input_text,
                model_name=model_name,
                api_key=api_key,
                ctx_length=ctx_length // 2,
                ctx_chunk_size=ctx_chunk_size // 2
            )
        # Otherwise, raise after final fallback
        raise Exception(f"Failed to fetch embedding(s) from OpenAI: {str(e)}")


embed_executor = ThreadPoolExecutor(max_workers=256)
if USE_OPENAI_API:
    embed_fn = get_openai_embedding
else:
    embed_fn = get_jina_embedding

class OpenAIEmbeddingsParallel:
    def __init__(self, openai_api_key, model, chunk_size=8000):
        self.openai_api_key = openai_api_key
        self.model = model
        self.chunk_size = chunk_size

    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)

    def _embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts, chunk_size=self.chunk_size)


    def _embed_query(self, text: str) -> List[float]:
        return self.embed_query(text)

    def encode(self, text: str) -> List[float]:
        return self.embed_query(text)

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    def embed_documents(
            self, texts: List[str], chunk_size: Optional[int] = 0
    ) -> List[List[float]]:
        if len(texts) >= 8:
            futures = []
            for i in range(0, len(texts), 8):
                futures.append(embed_executor.submit(embed_fn, texts[i:i+8], model_name=self.model, api_key=self.openai_api_key))
            results = [sleep_and_get_future_result(future) for future in futures]
            return [item for sublist in results for item in sublist]
        else:
            return embed_fn(texts, model_name=self.model, api_key=self.openai_api_key)
    def _get_len_safe_embeddings(
        self, texts: List[str], *, engine: str, chunk_size: Optional[int] = None
    ) -> List[List[float]]:
        return self._embed_documents(texts)

def get_embedding_model(keys):
    if "embeddingsUrl" in keys and not checkNoneOrEmpty(keys["embeddingsUrl"]):
        from embedding_client_server import EmbeddingClient
        return EmbeddingClient(keys["embeddingsUrl"])
    openai_key = keys["openAIKey"] if USE_OPENAI_API else keys["jinaAIKey"]
    assert openai_key
    openai_embed = OpenAIEmbeddingsParallel(openai_api_key=openai_key, model='text-embedding-3-small', chunk_size=2000)
    return openai_embed





import re


def remove_year_month_substring(s):
    # Define the regex pattern
    # This pattern now includes explicit month names
    pattern = r'\bin \d{4}(?:\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))?'
    s = re.sub(pattern, '', s)
    pattern = r'\bin \d{4}(?:\s+(?:january|february|march|april|may|june|july|august|september|october|november|december))?'
    s = re.sub(pattern, '', s)
    # Substitute the pattern with an empty string
    return normalize_whitespace(s)

import re


def enhanced_robust_url_extractor_v0(text):
    # Regex pattern to capture URLs, allowing for punctuation and parentheses
    pattern = r'(?:\b(?:https?://|www\.)\S+\b|\((?:https?://|www\.)\S+\))'
    raw_urls = re.findall(pattern, text, re.IGNORECASE)

    # Post-processing to clean up URLs
    cleaned_urls = []
    for url in raw_urls:
        # Remove surrounding parentheses and trailing punctuation
        cleaned_url = re.sub(r'^[\(\'"]*|[\.,;:!?\)\'"]+$', '', url)

        # Split URLs separated by pipe (|), semicolon (;), or comma (,)
        split_urls = re.split(r'[|;,]', cleaned_url)

        for split_url in split_urls:
            # Avoid appending empty or duplicate URLs
            if split_url and split_url not in cleaned_urls:
                cleaned_urls.append(split_url)

    return cleaned_urls


import re


def extract_code_blocks(text):
    # Pattern to find code blocks
    code_block_pattern = re.compile(r'(?s)(```.*?```|`.*?`|<code>.*?</code>)')
    # Find all code blocks
    code_blocks = code_block_pattern.findall(text)

    # Function to replace each match with an incrementing number
    def replace_with_counter(match):
        replace_with_counter.counter += 1
        return f"CODE_BLOCK_{replace_with_counter.counter}"

        # Initialize the counter attribute

    replace_with_counter.counter = -1

    # Replace code blocks with unique identifiers
    modified_text = code_block_pattern.sub(replace_with_counter, text)

    return modified_text, code_blocks


# execute
import re


def extract_code_blocks_with_lang(text):
    # Pattern to find code blocks with optional language specifier
    code_block_pattern = re.compile(r'(?s)(```(\w+)?\s.*?```|`.*?`|<code>.*?</code>)')

    # Find all code blocks
    code_blocks = code_block_pattern.findall(text)

    # Function to replace each match with an incrementing number and include language
    def replace_with_counter(match):
        replace_with_counter.counter += 1
        # Extract language if present, default to 'no_lang'
        language = match.group(2) if match.group(2) else 'no_lang'
        return f"CODE_BLOCK_{language}_{replace_with_counter.counter}"

        # Initialize the counter attribute

    replace_with_counter.counter = -1

    # Replace code blocks with unique identifiers including language
    modified_text = code_block_pattern.sub(replace_with_counter, text)
    return modified_text, [block[0] for block in code_blocks]

def remove_code_blocks(text):
    modified_text, code_blocks = extract_code_blocks_with_lang(text)
    return modified_text


def restore_code_blocks(modified_text, code_blocks):
    restored_text = modified_text
    for i, code_block in enumerate(code_blocks):
        restored_text = restored_text.replace(f'CODE_BLOCK_{i}', code_block)
    return restored_text

def enhanced_robust_url_extractor(text):
    modified_text, code_blocks = extract_code_blocks(text)
    # Regex pattern to capture URLs, allowing for punctuation and parentheses
    pattern = r'(?:\b(?:https?://|www\.)\S+\b|\((?:https?://|www\.)\S+\))'
    raw_urls = re.findall(pattern, modified_text, re.IGNORECASE)
    # Post-processing to clean up URLs
    cleaned_urls = []
    for url in raw_urls:
        # Remove surrounding parentheses and trailing punctuation
        cleaned_url = re.sub(r'^[\(\'"]*|[\.,;:!?\)\'"]+$', '', url)

        # Check if the cleaned_url is a valid URL
        if re.match(r'^(https?://|www\.)\S+$', cleaned_url):
            if cleaned_url not in cleaned_urls:
                cleaned_urls.append(cleaned_url)
        else:
            # Split URLs separated by pipe (|) or semicolon (;), but not comma (,)
            split_urls = re.split(r'[|;]', cleaned_url)
            for split_url in split_urls:
                if split_url and split_url not in cleaned_urls:
                    cleaned_urls.append(split_url)
    restored_text = restore_code_blocks(modified_text, code_blocks)
    return cleaned_urls



def test_enhanced_robust_url_extraction():
    import pandas as pd
    # Execute the updated tests with the enhanced robust URL extractor
    # Define the test cases with expected URLs
    test_cases_with_expected_urls = [
        ("the url is (www.example.com)", ["www.example.com"]),
        ("the url is www.example.com/path", ["www.example.com/path"]),
        ("the url is www.example.au/path", ["www.example.au/path"]),
        ("the urls are http://example.com/path|http://example.com/alternate",
         ["http://example.com/path", "http://example.com/alternate"]),
        (
        "Check out this website: https://www.example.com, and this one: http://another-example.com. Sometimes you might encounter www.without-https.com.",
        ["https://www.example.com", "http://another-example.com", "www.without-https.com"]),
        ("Visit https://site.io for more info.", ["https://site.io"]),
        ("Here's a tricky one: https://example.com/path,https://another-example.com/path.",
         ["https://example.com/path", "https://another-example.com/path"]),
        ("A URL with a query: https://example.com/search?q=url.", ["https://example.com/search?q=url"]),
        ("A URL with a port number: http://example.com:8080/path.", ["http://example.com:8080/path"]),
        ("A URL in quotes: 'https://example.com'.", ["https://example.com"]),
        ("Text before URL:https://example.com.", ["https://example.com"]),
        ("Parenthesis URL (https://example.com).", ["https://example.com"]),
        ("Embedded URL in text, visit https://example.com today!", ["https://example.com"]),
        ("Multiple URLs: https://example.com;https://site.io.", ["https://example.com", "https://site.io"]),
        ("Special characters in URL: https://example.com/path?query=value&another=2.",
         ["https://example.com/path?query=value&another=2"]),
        ### Code blocks
        ("Code block with URL: ```https://example.com```", []),
        ("Code block with URL and text: ```This is a code block with https://example.com inside.```", []),
        ("Multiple code blocks: ```https://example.com``` and `https://another-example.com`", []),
        (
        "Code block with URL and other code: ```python\nprint('Hello, World!')\nvisit https://example.com for more info```",
        []),
        ("Code block with URL and text: <code>This is a code block with https://example.com inside.</code>", []),
        ("Multiple code blocks: <code>https://example.com</code> and <code>https://another-example.com</code>", []),
        (
        "Text with URL and code block: Visit https://example.com for more info. ```Code block with https://another-example.com```",
        ["https://example.com"]),
        (
        "Text with URL, code block, and URL: Check out https://example.com ```Code block with https://another-example.com``` and visit https://third-example.com",
        ["https://example.com", "https://third-example.com"]),
    ]

    results = []
    extractor = enhanced_robust_url_extractor
    pattern_results = {"Pattern Name": "Enhanced Robust URL Extractor"}
    for i, (test_case, expected_urls) in enumerate(test_cases_with_expected_urls, start=1):
        matches = extractor(test_case)
        print(matches)
        result = "Passed" if set(matches) == set(expected_urls) else "Failed"
        pattern_results[f"Case {i}"] = result

        # Print failed cases with detected and expected URLs
        if result == "Failed":
            print(f"Case {i} Failed:")
            print(f"  Text: {test_case}")
            print(f"  Detected URLs: {matches}")
            print(f"  Expected URLs: {expected_urls}")
            print()

    results.append(pattern_results)

    # Display the results in a tabular format
    df_enhanced_robust = pd.DataFrame(results)
    df_enhanced_robust.set_index("Pattern Name", inplace=True)
    print(df_enhanced_robust)

import re

def extract_url_from_mardown(text):
    """
    Extracts URLs from text where URLs are always enclosed within parentheses.

    Args:
        text (str): The input text.

    Returns:
        list: A list of extracted URLs.
    """

    if not text.startswith("(") or not text.endswith(")"):
        text = f"({text})"
    pattern = r'\((https?://\S+)\)'  # Regular expression pattern
    urls = re.findall(pattern, text)

    if len(urls) == 0:
        try:
            urls = enhanced_robust_url_extractor(text)
        except:
            urls = []

    if len(urls) == 0:
        print(f"No URLs found in the text = ```{text}```")
        return '<NO_URL_FOUND_IN_TEXT>'
    return urls[0]

import re

def parse_mardown_link_text(text):
    pattern = r'\[(.*?)\]\((.*?)\)(.*?)(?=\[|$)'
    matches = re.findall(pattern, text, re.DOTALL)

    results = []
    for match in matches:
        title, link, content = match
        # Cleaning and counting words in content
        word_count = len(content.strip().split())
        results.append((link, title, word_count))

    return results





@CacheResults(cache=cache, dtype_filters=tuple([str, int, tuple, bool]), enabled=True, expire=3600, should_cache_key_condition=lambda x: x is not None and len(x.split()) < 100)
def get_text_embedding(text, keys):
    openai_embed = get_embedding_model(keys)
    try:
        embedding = openai_embed.embed_query(text)
        embedding = np.array(embedding)
    except:
        time.sleep(1)
        embedding = openai_embed.embed_query(text)
        embedding = np.array(embedding)
    return embedding


def semantic_validation_web_page_scrape(context, result, apikeys, threshold=0.3):
    import sys
    text = result["text"].strip()
    title = result["title"]
    link = result["link"]
    if len(text.split()) < 2:
        return True
    context_emb_future = get_async_future(get_text_embedding, context, apikeys)
    chunk_size = len(text.split()) // 4
    chunks = chunk_text_words(text, chunk_size=chunk_size, chunk_overlap=min(64, chunk_size // 2))
    chunks = [" ".join(chunk.strip().split()[:2048]) for chunk in chunks if len(chunk.strip().split()) > 2][:2]
    chunk_embeddings_future = [get_async_future(get_text_embedding, chunk, apikeys) for chunk in chunks]
    try:
        chunk_embeddings = [sleep_and_get_future_result(future) for future in chunk_embeddings_future]
        context_emb = sleep_and_get_future_result(context_emb_future)
        # dot product of context and chunk embeddings using numpy
        dot_products = [np.dot(context_emb, chunk_emb) / (np.linalg.norm(context_emb) * np.linalg.norm(chunk_emb)) for chunk_emb in chunk_embeddings]
        max_dot_product = max(dot_products)

        if max_dot_product < threshold:
            print(f"[semantic_validation_web_page_scrape] [FAILED] \ntitle = {title}, text = {text[:100]} link = {link}, Max dot = {max_dot_product}, Dot products = {dot_products}")
            # Flush the print
            sys.stdout.flush()
            return False
        return True
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[semantic_validation_web_page_scrape] Error in getting embeddings with exception = {str(e)}")
        return False


class GenericShortException(Exception):
    def __init__(self, message=""):
        super().__init__(message)

    def __str__(self):
        # Fetch the current stack trace, limit it to the last 2 entries for brevity
        stack_trace = traceback.format_stack(limit=3)
        # Print the last one or two lines of the stack trace
        trace = self.args[0] + "\n" + "\n".join(stack_trace[-3:-1])
        return trace

class ForceStoppedException(GenericShortException):
    pass


import re


def chunk_text(text, chunk_size, separators=None):
    """
    Splits a given text into chunks of a specified size, retaining the original separators.

    This function takes a string and divides it into smaller chunks, each not exceeding the specified chunk size.
    It respects the natural breaks in the text, determined by a set of specified separators. If no separators are
    provided, it defaults to common whitespace characters and punctuation marks. The function ensures that the
    original structure and separator information of the text are preserved in the output chunks.

    Parameters:
    - text (str): The text to be chunked.
    - chunk_size (int): The maximum size of each chunk. The actual chunk size may be smaller to respect the separators.
    - separators (list of str, optional): A list of separator characters or strings to be used for splitting the text.
      Defaults to [' ', '\t', '\n', ',', ';', '. ', '!'].

    Returns:
    - list of str: A list containing the chunked parts of the original text.

    Example usage:
    >>> chunk_text("This is a sample text, to demonstrate how the chunking function works. It will split the text into chunks!", 20)
    ['This is a sample text,', ' to demonstrate how', ' the chunking function', ' works. It will split', ' the text into chunks!']
    """

    # Define default separators if none are provided
    if separators is None:
        separators = [' ', '\t', '\n', ',', ';', '. ', '!']

        # Adjust the regex pattern to capture and retain separators in the results
    pattern = '(%s)' % '|'.join(map(re.escape, separators))

    # Split the text while retaining separators, using the adjusted regex pattern
    parts = re.split(pattern, text)

    # Initialize variables for the current chunk and the list of chunks
    current_chunk = ''
    chunks = []

    for part in parts:
        # Check if adding the next part exceeds the chunk size and if the current chunk is not empty
        if len(current_chunk + part) > chunk_size and current_chunk:
            # Append the current chunk to the list and start a new chunk with the current part
            chunks.append(current_chunk)
            current_chunk = part
        else:
            # Add the current part to the chunk, including the separator if present
            current_chunk += part

            # Add the last chunk to the list if it's not empty
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


import re


def chunk_text_words(text, chunk_size, chunk_overlap=0, separators=None):
    """
    Splits a given text into chunks based on the number of words or elements, retaining the original separators,
    with an option to overlap chunks by a specified number of elements.

    This function divides the text into smaller chunks, each containing a number of elements (words or separators)
    that does not exceed the specified chunk size, while allowing for an overlap of elements between consecutive chunks.
    It respects the natural breaks in the text, determined by a set of specified separators. If no separators are provided,
    it defaults to common whitespace characters and punctuation marks. The function ensures that the original structure
    and separator information of the text are preserved in the output chunks.

    Parameters:
    - text (str): The text to be chunked.
    - chunk_size (int): The maximum number of elements (words and separators) in each chunk.
    - chunk_overlap (int): The number of elements to be overlapped between consecutive chunks. Must be less than chunk_size.
    - separators (list of str, optional): A list of separator characters or strings to be used for splitting the text.
      Defaults to [' ', '\t', '\n', ',', ';', '. ', '!'].

    Returns:
    - list of str: A list containing the chunked parts of the original text.

    Example usage:
    >>> chunk_text("This is a longer example text to demonstrate the overlapping functionality.", 5, 2)
    ['This is a longer', 'longer example text to', 'text to demonstrate the', 'demonstrate the overlapping functionality.']
    """
    if separators is None:
        separators = ['                ', '            ', '           ', '          ', '        ','       ','      ', '    ', '   ','  ', ' ', '  ',  '\t\t\t', '\t\t\n', '\n\n\n', '\n\n\t', '\n\t\t', '\n\n','\t\t', '\n\t','\t\n',  '\t', '\n', ',', ';', '. ', '!']
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be less than chunk_size")
    pattern = '(%s)' % '|'.join(map(re.escape, separators))
    parts = re.split(pattern, text)

    chunks = []
    current_chunk = []
    element_count = 0
    overlap_buffer = []

    for part in parts:
        if part in separators:
            element_count += 1
            overlap_buffer.append(part)
        else:
            words = re.split(r'\s+', part.strip())
            element_count += len(words)
            overlap_buffer.extend(words)

        while element_count > chunk_size:
            chunk_end = chunk_size - len(current_chunk) if current_chunk else chunk_size
            current_chunk.extend(overlap_buffer[:chunk_end])
            if len(current_chunk) == chunk_size:
                chunks.append(''.join(current_chunk))
                overlap_buffer = overlap_buffer[chunk_size - chunk_overlap:]
                current_chunk = overlap_buffer[:chunk_overlap]
                element_count = len(re.split(r'\s+', ''.join(current_chunk).strip()))
                overlap_buffer = overlap_buffer[chunk_overlap:]

    if overlap_buffer or current_chunk:
        chunks.append(''.join(overlap_buffer if overlap_buffer else current_chunk))

    return chunks


def sort_two_lists(list1, list2, key=None, reverse=False):
    """
    Sorts two lists based on the sorting of the first list using an optional sorting key.

    Parameters:
    - list1: The list to be sorted.
    - list2: The list to be sorted in the same order as list1.
    - sort_key: Optional. A function that would serve as a key for the sorting criteria.
                If None, the list1 elements themselves are used for sorting.
    - reverse: Optional. If True, the lists are sorted in reverse order.

    Returns:
    - list1_sorted: The sorted version of list1.
    - list2_sorted: The sorted version of list2, in the same order as list1_sorted.
    """
    # If no sort_key is provided, use the elements of list1 as they are
    if key is None:
        key = lambda x: x

    assert len(list1) == len(list2), "[sort_two_lists] The two lists must have the same length."
    if len(list1) == 0:
        return [], []

        # Pair each element of list1 with its corresponding element in list2
    paired = list(zip(list1, list2))
    # Sort the paired list by the provided sort_key applied to the elements of list1
    paired_sorted = sorted(paired, key=lambda x: key(x[0]), reverse=reverse)
    # Unzip the pairs back into two lists
    list1_sorted, list2_sorted = zip(*paired_sorted)

    # Convert the tuples back to lists
    return list(list1_sorted), list(list2_sorted)

def sort_three_lists(list1, list2, list3, key=None, reverse=False):
    """
    Sorts three lists based on the sorting of the first list using an optional sorting key.

    Parameters:
    - list1: The list to be sorted.
    - list2: The list to be sorted in the same order as list1.
    - list3: The list to be sorted in the same order as list1.
    - sort_key: Optional. A function that would serve as a key for the sorting criteria.
                If None, the list1 elements themselves are used for sorting.
    - reverse: Optional. If True, the lists are sorted in reverse order.

    Returns:
    - list1_sorted: The sorted version of list1.
    - list2_sorted: The sorted version of list2, in the same order as list1_sorted.
    - list3_sorted: The sorted version of list3, in the same order as list1_sorted.
    """
    # If no sort_key is provided, use the elements of list1 as they are
    if key is None:
        key = lambda x: x

    assert len(list1) == len(list2) == len(list3), "[sort_three_lists] The three lists must have the same length."
    if len(list1) == 0:
        return [], [], []

    # Pair each element of list1 with its corresponding elements in list2 and list3
    paired = list(zip(list1, list2, list3))
    # Sort the paired list by the provided sort_key applied to the elements of list1
    paired_sorted = sorted(paired, key=lambda x: key(x[0]), reverse=reverse)
    # Unzip the pairs back into three lists
    list1_sorted, list2_sorted, list3_sorted = zip(*paired_sorted)

    # Convert the tuples back to lists
    return list(list1_sorted), list(list2_sorted), list(list3_sorted)


def filter_two_lists(list1, list2, combined_filter_criterion = lambda x,y: True, filter_criterion_list1 = lambda x: True, filter_criterion_list2 = lambda x: True):
    """
    Filters two lists based on a filtering criterion applied to the first list.

    Parameters:
    - list1: The list whose elements are to be filtered based on the filter_criterion.
    - list2: The list to be filtered in parallel with list1.
    - filter_criterion: A function that takes an element of list1 and returns True if the element should be kept.

    Returns:
    - list1_filtered: The filtered version of list1 based on the filter_criterion.
    - list2_filtered: The filtered version of list2, corresponding to the filtering of list1.
    """
    # Use list comprehension to filter both lists simultaneously based on the filter_criterion applied to list1 elements

    assert len(list1) == len(list2), "[sort_two_lists] The two lists must have the same length."
    if len(list1) == 0:
        return [], []

    list1_filtered, list2_filtered = zip(
        *[(item1, item2) for item1, item2 in zip(list1, list2) if filter_criterion_list1(item1) and filter_criterion_list2(item2) and combined_filter_criterion(item1, item2)])

    # Convert the tuples back to lists
    return list(list1_filtered), list(list2_filtered)


def filter_three_lists(list1, list2, list3, combined_filter_criterion = lambda x,y,z: True, filter_criterion_list1 = lambda x: True, filter_criterion_list2 = lambda x: True, filter_criterion_list3 = lambda x: True):
    """
    Filters three lists based on a filtering criterion applied to the first list.

    Parameters:
    - list1: The list whose elements are to be filtered based on the filter_criterion.
    - list2: The list to be filtered in parallel with list1.
    - list3: The list to be filtered in parallel with list1.
    - filter_criterion: A function that takes an element of list1 and returns True if the element should be kept.

    Returns:
    - list1_filtered: The filtered version of list1 based on the filter_criterion.
    - list2_filtered: The filtered version of list2, corresponding to the filtering of list1.
    - list3_filtered: The filtered version of list3, corresponding to the filtering of list1.
    """
    # Use list comprehension to filter both lists simultaneously based on the filter_criterion applied to list1 elements

    assert len(list1) == len(list2) == len(list3), "[sort_three_lists] The three lists must have the same length."
    if len(list1) == 0:
        return [], [], []

    list1_filtered, list2_filtered, list3_filtered = zip(
        *[(item1, item2, item3) for item1, item2, item3 in zip(list1, list2, list3) if filter_criterion_list1(item1) and filter_criterion_list2(item2) and filter_criterion_list3(item3) and combined_filter_criterion(item1, item2, item3)])

    # Convert the tuples back to lists
    return list(list1_filtered), list(list2_filtered), list(list3_filtered)



import requests
def google_search(query, cx, api_key, num=10, filter=0, start=0):
    url = 'https://www.googleapis.com/customsearch/v1'
    params = {
        'key': api_key,
        'cx': cx,
        'q': query,
        'num': num,
        'filter': filter,
        'start': start
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
        data = response.json()

        search_results = []
        for result in data.get('items', []):
            search_result = {
                'title': result['title'],
                'url': result['link'],
                'snippet': result['snippet'],
                'query': query,
                'link': result['link'],
                'source': 'google',
            }
            search_results.append(search_result)

        return search_results

    except requests.exceptions.RequestException as e:
        print(f'An error occurred: {e}')
        return None


def get_from_dict_or_env(
    data: Dict[str, Any], key: str, env_key: str, default: Optional[str] = None
) -> str:
    """Get a value from a dictionary or an environment variable."""
    if key in data and data[key]:
        return data[key]
    else:
        return get_from_env(key, env_key, default=default)


def get_from_env(key: str, env_key: str, default: Optional[str] = None) -> str:
    """Get a value from a dictionary or an environment variable."""
    if env_key in os.environ and os.environ[env_key]:
        return os.environ[env_key]
    elif default is not None:
        return default
    else:
        raise ValueError(
            f"Did not find {key}, please add an environment variable"
            f" `{env_key}` which contains it, or pass"
            f"  `{key}` as a named parameter."
        )

import base64
import zlib
from urllib.parse import quote


def compress_and_encode_drawio_xml(input_string):
    # Step 1: Base64 Encode
    base64_encoded = base64.b64encode(input_string.encode('utf-8'))

    # Step 2: Deflate
    deflated = zlib.compress(base64_encoded)

    # Step 3: URL Encode
    url_encoded = quote(deflated)

    return url_encoded


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

from getpass import getpass
def _getpass(env_var: str):
    if not os.environ.get(env_var):
        os.environ[env_var] = getpass(f"{env_var}=")
    return os.environ.get(env_var)

    

    





















