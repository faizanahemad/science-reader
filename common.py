import random
import tempfile
import asyncio
import threading
import sys
sys.tracebacklimit = 5
import traceback

from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, ProcessPoolExecutor
from urllib.parse import urlparse, urlunparse
import time
import logging
import sys
import os
import re
import inspect
from more_itertools import peekable
import types

import pickle
import dill
import collections
import threading
import requests

from multiprocessing import Process, Queue
from functools import partial

from tenacity import RetryError
FINISHED_TASK = TERMINATION_SIGNAL = "TERMINATION_SIGNAL"
SMALL_CHUNK_LEN = 256
LARGE_CHUNK_LEN = 4096
TOKEN_LIMIT_FOR_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_DETAILED", 13000))
TOKEN_LIMIT_FOR_EXTRA_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_EXTRA_DETAILED", 25000))
TOKEN_LIMIT_FOR_SUPER_DETAILED = int(os.getenv("TOKEN_LIMIT_FOR_SUPER_DETAILED", 50000))
TOKEN_LIMIT_FOR_SHORT = int(os.getenv("TOKEN_LIMIT_FOR_SHORT", 3000))
MODEL_TOKENS_SMART = int(os.getenv("MODEL_TOKENS_SMART", 7500))
MODEL_TOKENS_DUMB = int(os.getenv("MODEL_TOKENS_DUMB", 3500))
DDOS_PROTECTION_STR = "Blocked by ddos protection"
PDF_CONVERT_URL = os.getenv("PDF_CONVERT_URL", "http://localhost:7777/forms/libreoffice/convert")
MAX_TIME_TO_WAIT_FOR_WEB_RESULTS = int(os.getenv("MAX_TIME_TO_WAIT_FOR_WEB_RESULTS", 20))

import requests
import os



def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

def is_picklable(obj):
    try:
        pickle.dumps(obj)
        return True
    except (pickle.PickleError, TypeError):
        return False
    return False


def is_dillable(obj):
    try:
        dill.dumps(obj)
        return True
    except (TypeError, AttributeError):
        return False
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

executor = ThreadPoolExecutor(max_workers=256)

def make_async(fn):
    def async_fn(*args, **kwargs):
        func_part = partial(fn, *args, **kwargs)
        future = executor.submit(func_part)
        return future
    return async_fn

def get_async_future(fn, *args, **kwargs):
    # Make your function async
    afn = make_async(fn)
    # This will return a Future object, you can call .result() on it to get the result
    future = afn(*args, **kwargs)
    return future


def wrap_in_future(s):
    future = Future()
    future.set_result(s)
    return future

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

def round_robin(arr, randomize=True):
    if randomize:
        random.shuffle(arr)
    while True:
        for item in arr:
            yield item
            

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

class CacheResults:
    def __init__(self, cache, key_function=lambda args, kwargs: str(mmh3.hash(str(args) + str(kwargs), signed=False)),
                                                  dtype_filters=None,
                                                  should_cache_predicate=lambda x: x is not None and (not isinstance(x, Exception)) and (not isinstance(x, (list, tuple, set)) or len(x) > 0) and (not isinstance(x, str) or len(x.strip()) > 0),
                                                  enabled=True):
        self.cache = cache
        self.key_function = key_function
        self.dtype_filters = tuple(dtype_filters) if dtype_filters is not None else None
        self.should_cache_predicate = should_cache_predicate
        self.enabled = enabled

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self.enabled:
                result_computed = False
                if self.dtype_filters is not None and len(self.dtype_filters) > 0:
                    sig = signature(func)

                    # Bind the arguments to the signature
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()

                    # Filter the arguments based on their type
                    filtered_args = {k: v for k, v in bound_args.arguments.items() if isinstance(v, self.dtype_filters)}
                    key = f"{func.__module__}:{func.__name__}:{str(mmh3.hash(str(filtered_args), signed=False))}"
                else:
                    key = f"{func.__module__}:{func.__name__}:{self.key_function(args, kwargs)}"
                result = cache.get(key)
                if result is None or isinstance(result, Exception) or (
                        isinstance(result, (list, tuple, set)) and len(result) == 0):
                    result = func(*args, **kwargs)
                    result_computed = True
                if result is not None and not isinstance(result, Exception) and not (
                        isinstance(result, (list, tuple, set)) and len(result) == 0) and self.should_cache_predicate(result) and result_computed:
                    cache.set(key, result, expire=cache_timeout)
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
    
def checkNoneOrEmpty(x):
    if x is None:
        return True
    elif isinstance(x, str):
        return len(x.strip())==0
    elif isinstance(x, str) and x.strip().lower() in ['null', 'none']:
        return x.strip().lower() in ['null', 'none']
    else:
        return len(x) == 0
    
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

def make_stream(res, do_stream):
    is_generator = inspect.isgenerator(res)
    if is_generator:
        res = check_if_stream_and_raise_exception(res)
    if do_stream and not is_generator:
        assert isinstance(res, (str, list, tuple))
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

def convert_stream_to_iterable(stream):
    ans = []
    for t in stream:
        ans.append(t)
    if isinstance(ans[0], str):
        ans = "".join(ans)
    return ans

def check_if_stream_and_raise_exception(iterable_or_str):
    if isinstance(iterable_or_str, str):
        # If it's a string, just return it as it is.
        return iterable_or_str
    elif isinstance(iterable_or_str, types.GeneratorType):
        # If it's a generator, we need to peek at it.
        try:
            peeked = peekable(iterable_or_str)
            peeked.peek()  # This will raise StopIteration if the generator is empty.
            return peeked
        except StopIteration:
            # Here you could handle the empty generator case.
            raise
        except Exception as e:
            # Here you could handle other exceptions.
            raise
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
    if "arxiv.org" in link and "pdf" not in link:
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
    # Try to find text inside square brackets
    match = re.search(r'\[.*?\]', s)
    if match:
        return match.group(0)

    # Check for queries separated by one or two newlines
    newline_separated = re.split(r'\n\n|\n', s.strip())
    if newline_separated and all(len(query.strip().split()) >= 3 for query in newline_separated) and len(newline_separated) >= 3:
        return newline_separated
    # Try to find markdown list
    markdown_list = re.findall(r'^[-*] (.+)$', s, flags=re.M)
    if markdown_list:
        return markdown_list



    # If a single string, return it in an array
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
        self.set = set()
        self.data = dict()
        self.lock = threading.RLock()
        self.default_factory = default_factory  # Save the default factory

    def __delitem__(self, key):
        with self.lock:
            if key in self.set:
                self.set.remove(key)
                self.queue.remove(key)
                del self.data[key]

    def remove_any(self, item):
        with self.lock:
            if item in self.set:
                self.set.remove(item)
                self.queue.remove(item)
                del self.data[item]

    def add(self, item, item_data=None):  # Modified to allow adding an item without data
        with self.lock:
            self.remove_any(item)
            if len(self.queue) >= self.maxsize - 1:
                removed = self.queue.popleft()
                self.set.remove(removed)
                del self.data[removed]
            self.queue.append(item)
            self.set.add(item)
            self.data[item] = item_data if item_data is not None else self.default_factory() if self.default_factory else None

    def __contains__(self, item):
        with self.lock:
            return item in self.set

    def __len__(self):
        with self.lock:
            return len(self.queue)

    def items(self):
        with self.lock:
            return list(self.queue)

    def get_data(self, item):
        with self.lock:
            if item not in self.set and self.default_factory:
                self.add(item, self.default_factory(item))
            return self.data.get(item, None)

    def __getitem__(self, item):
        return self.get_data(item)

    def __setitem__(self, item, data):
        with self.lock:
            if item in self.set:
                self.data[item] = data
            else:
                self.add(item, data)

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

from flask_caching import Cache
from inspect import signature
from functools import wraps
import mmh3
import diskcache as dc
cache_timeout = 7 * 24 * 60 * 60
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
                cache.set(key, result, expire=cache_timeout)

            return result

        return wrapper
    return decorator

import requests
os_temp_dir = tempfile.gettempdir()
temp_dir = os.path.join(os.getcwd(), "storage", "cache")
cache = dc.Cache(temp_dir)
cache_timeout = 7 * 24 * 60 * 60

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

@CacheResults(cache=dict(), dtype_filters=[str, int, tuple, bool], enabled=False)
def is_pdf_link(link):
    st = time.time()
    result = False
    science_doc = ("arxiv.org" in link and "pdf" in link) or ("openreview.net" in link and "pdf" in link) or ("aclanthology.org" in link and "pdf" in link) or ("aclweb.org" in link and "anthology" in link and "pdf" in link)
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
    return s.strip()

def remove_bad_whitespaces_easy(s):
    s = re.sub("\n{2,}", "\n", s)
    s = re.sub("\r+", "\n", s)
    lines = s.splitlines(keepends=False)
    lines = [line.rstrip() for line in lines]
    s = '\n'.join(lines)
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


from langchain.embeddings.openai import embed_with_retry, OpenAIEmbeddings
from typing import List, Optional
import numpy as np
import requests
from typing import List, Union


def get_openai_embedding(input_text: Union[str, List[str]], model_name: str, api_key: str) -> Union[
    List[float], List[List[float]]]:
    """
    Fetches the embedding(s) for the given input text using the specified model.
    Parameters:
    - input_text: The text (or texts) for which to generate the embedding(s).
    - model_name: The model to use for generating the embedding(s).
    - api_key: The OpenAI API key for authorization.
    Returns:
    - A list of floats representing the embedding, or a list of lists of floats if the input was a list of strings.
    """
    # Define the URL for the OpenAI API embeddings endpoint
    url = "https://api.openai.com/v1/embeddings"

    # Prepare the headers with the Content-Type and Authorization
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # Prepare the data payload with the input text and model name
    data = {
        "input": input_text,
        "model": model_name
    }

    # Send a POST request to the API
    response = requests.post(url, headers=headers, json=data)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON response
        response_json = response.json()
        # Extract the embedding(s) from the response
        embeddings = [item["embedding"] for item in response_json["data"]]
        return embeddings
    else:
        # Handle errors (e.g., invalid API key, rate limits, etc.)
        raise Exception(f"Failed to fetch embedding(s): {response.text}")


embed_executor = ThreadPoolExecutor(max_workers=256)
class OpenAIEmbeddingsParallel(OpenAIEmbeddings):
    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    def embed_documents(
            self, texts: List[str], chunk_size: Optional[int] = 0
    ) -> List[List[float]]:
        if len(texts) >= 2:
            futures = []
            for i in range(0, len(texts), 2):
                futures.append(embed_executor.submit(get_openai_embedding, texts[i:i+2], model_name=self.model, api_key=self.openai_api_key))
            results = [future.result() for future in futures]
            return [item for sublist in results for item in sublist]
        else:
            return get_openai_embedding(texts, model_name=self.model, api_key=self.openai_api_key)
    def _get_len_safe_embeddings(
        self, texts: List[str], *, engine: str, chunk_size: Optional[int] = None
    ) -> List[List[float]]:
        embeddings: List[List[float]] = [[] for _ in range(len(texts))]
        try:
            import tiktoken
        except ImportError:
            raise ImportError(
                "Could not import tiktoken python package. "
                "This is needed in order to for OpenAIEmbeddings. "
                "Please install it with `pip install tiktoken`."
            )

        tokens = []
        indices = []
        model_name = self.tiktoken_model_name or self.model
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            logger.warning("Warning: model not found. Using cl100k_base encoding.")
            model = "cl100k_base"
            encoding = tiktoken.get_encoding(model)
        for i, text in enumerate(texts):
            if self.model.endswith("001"):
                # See: https://github.com/openai/openai-python/issues/418#issuecomment-1525939500
                # replace newlines, which can negatively affect performance.
                text = text.replace("\n", " ")
            token = encoding.encode(
                text,
                allowed_special=self.allowed_special,
                disallowed_special=self.disallowed_special,
            )
            for j in range(0, len(token), self.embedding_ctx_length):
                tokens += [token[j : j + self.embedding_ctx_length]]
                indices += [i]

        batched_embeddings = []
        _chunk_size = chunk_size or self.chunk_size

        if self.show_progress_bar:
            try:
                import tqdm

                _iter = tqdm.tqdm(range(0, len(tokens), _chunk_size))
            except ImportError:
                _iter = range(0, len(tokens), _chunk_size)
        else:
            _iter = range(0, len(tokens), _chunk_size)
        _iter = list(_iter)
        if len(_iter) <= 4:
            for i in _iter:
                response = embed_with_retry(
                    self,
                    input=tokens[i : i + _chunk_size],
                    **self._invocation_params,
                )
                batched_embeddings += [r["embedding"] for r in response["data"]]
        else:
            # parallelize the above with a threadpool
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = []
                for i in _iter:
                    futures.append(executor.submit(embed_with_retry, self, input=tokens[i : i + _chunk_size], **self._invocation_params))
                for future in futures:
                    response = future.result()
                    batched_embeddings += [r["embedding"] for r in response["data"]]

        results: List[List[List[float]]] = [[] for _ in range(len(texts))]
        num_tokens_in_batch: List[List[int]] = [[] for _ in range(len(texts))]
        for i in range(len(indices)):
            results[indices[i]].append(batched_embeddings[i])
            num_tokens_in_batch[indices[i]].append(len(tokens[i]))
        avg_const = embed_with_retry(
                    self,
                    input="",
                    **self._invocation_params,
                )[
                    "data"
                ][0]["embedding"]
        for i in range(len(texts)):
            _result = results[i]
            if len(_result) == 0:
                average = avg_const
            else:
                average = np.average(_result, axis=0, weights=num_tokens_in_batch[i])
            embeddings[i] = (average / np.linalg.norm(average)).tolist()

        return embeddings

from langchain.embeddings.base import Embeddings
def get_embedding_model(keys) -> Embeddings:
    if "embeddingsUrl" in keys and not checkNoneOrEmpty(keys["embeddingsUrl"]):
        from embedding_client_server import EmbeddingClient
        return EmbeddingClient(keys["embeddingsUrl"])
    openai_key = keys["openAIKey"]
    assert openai_key
    # TODO: https://python.langchain.com/docs/modules/data_connection/caching_embeddings
    openai_embed = OpenAIEmbeddingsParallel(openai_api_key=openai_key, model='text-embedding-3-small', chunk_size=8000)
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


# Test the function
test_str = "This event happened in 2023 December and was repeated in 2021 January, but not in 2022 summer."
result = remove_year_month_substring(test_str)
print(result)  # The string with specified substrings removed

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
    code_block_pattern = re.compile(r'(?s)(```.*?```|`.*?`|<code>.*?</code>)')
    code_blocks = code_block_pattern.findall(text)
    modified_text = code_block_pattern.sub('CODE_BLOCK_{}', text)
    return modified_text, code_blocks


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
        # Split URLs separated by pipe (|), semicolon (;), or comma (,)
        split_urls = re.split(r'[|;,]', cleaned_url)
        for split_url in split_urls:
            # Avoid appending empty or duplicate URLs
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


from collections import OrderedDict
from threading import Lock


class FixedSizeFIFODict(OrderedDict):
    def __init__(self, size):
        super().__init__()
        self.size = size
        self.lock = Lock()  # Initialize a lock for thread-safe operations

    def __setitem__(self, key, value):
        with self.lock:  # Use the lock to ensure thread-safe access
            super().__setitem__(key, value)
            self.ensure_fixed_size()

    def ensure_fixed_size(self):
        while len(self) > self.size:
            self.popitem(last=False)


@CacheResults(cache=FixedSizeFIFODict(1000), dtype_filters=tuple([str, int, tuple, bool]), enabled=True)
def get_text_embedding(text, keys):
    openai_embed = get_embedding_model(keys)
    embedding = openai_embed.embed_query(text)
    embedding = np.array(embedding)
    return embedding


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




















