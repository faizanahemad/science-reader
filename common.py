import asyncio
import threading
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

from multiprocessing import Process, Queue
from functools import partial

from tenacity import RetryError
FINISHED_TASK = TERMINATION_SIGNAL = "TERMINATION_SIGNAL"
SMALL_CHUNK_LEN = 160
LARGE_CHUNK_LEN = 512
TOKEN_LIMIT_FOR_DETAILED = 12000

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

executor = ThreadPoolExecutor(max_workers=32)

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

def execute_in_thread(function, *args, **kwargs):
    logger.debug(f"type args = {type(args)}, type kwargs = {type(kwargs)}, Pickle able:: function = {is_picklable(function)}, {is_picklable(args)}, {is_picklable(kwargs)}, Is Dill able:: function = {is_dillable(function)}, {is_dillable(args)}, {is_dillable(kwargs)}")
    submit_st = time.time()
    with ProcessPoolExecutor(max_workers=2) as executor:
        future = executor.submit(function, *args, **kwargs)
    
    submit_et = time.time()
    logger.info(f"Stuck on ProcessPoolExecutor for {(submit_et - submit_st):.2f} sec , done future state = {future.done()}")
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

def round_robin(arr):
    while True:
        for item in arr:
            yield item
            

def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds, result type: {type(result)}, result length: {len(result) if hasattr(result, '__len__') else None}")
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
        logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds")
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
    is_generator = inspect.isgenerator(res)
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
    else:
        # If it's not a string or a generator, raise an exception.
        raise ValueError("Unexpected input type.")
        
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
def get_first_last_parts(my_string, first_n=250, last_n=750):
    import tiktoken
    enc = tiktoken.encoding_for_model('gpt-4')
    str_encoded = enc.encode(my_string)
    if len(str_encoded) < first_n + last_n:
        return my_string
    str_len = len(str_encoded)
    first_part = enc.decode(str_encoded[:first_n])
    last_part = enc.decode(str_encoded[str_len-last_n:])
    return first_part + "\n" + last_part


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
    return re.sub(r'\s+', ' ', s).strip()

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
            if result is None:
                result = f(*args, **kwargs)
                cache.set(key, result, expire=cache_timeout)

            return result

        return wrapper
    return decorator

import requests

def is_pdf_link(link):
    response = requests.head(link)
    content_type = response.headers.get('Content-Type')
    return ("arxiv.org" in link and "pdf" in link) or ("openreview.net" in link and "pdf" in link) or (content_type is not None and (content_type == 'application/pdf' or 'pdf' in content_type))


import threading
from queue import Queue

class ProcessFnWithTimeout:
    def __init__(self, result_queue: Queue):
        self.result_queue = result_queue

    def __call__(self, fn, timeout, *args, **kwargs):
        result = None
        exception_event = threading.Event()

        def worker():
            nonlocal result
            try:
                result = fn(*args, **kwargs)  # Call the original function with its args and kwargs
            except Exception as e:
                traceback.print_exc()
                # Handle exceptions if needed
                print(f"Exception processing function {fn.__name__}: {e}")
            finally:
                exception_event.set()

        thread = threading.Thread(target=worker)
        thread.start()
        # Wait for either the result to be ready or the timeout to occur
        exception_event.wait(timeout)
        if not exception_event.is_set():
            print(f"Timeout processing function {fn.__name__}")
            result = None  # Use None to indicate timeout

        # Put the result (or None if there was a timeout) in the queue
        self.result_queue.put(result)
        return result


from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue


def orchestrator(fn, args_list, callback=None, max_workers=32, timeout=60):
    if not isinstance(args_list, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in args_list):
        raise ValueError("args_list must be a list of tuples containing (*args, **kwargs)")

    if timeout < 0:
        raise ValueError("Timeout must be non-negative")

    task_queue = Queue()

    def task_worker(args, kwargs):
        try:
            result = process_fn_with_timeout(fn, timeout, *args, **kwargs)
            if callback and result is not None:
                result = callback(result, args, kwargs)
            task_queue.put(result)
        except Exception as e:
            traceback.print_exc()
            print(f"Exception in task_worker: {e}")
            task_queue.put(None)  # Put None to indicate an error

    process_fn_with_timeout = ProcessFnWithTimeout(Queue())

    def run_tasks():
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = []
                for task in args_list:
                    if task is None:
                        continue
                    args, kwargs = task
                    futures.append(pool.submit(task_worker, args, kwargs))
                for future in futures:
                    future.result()
        except Exception as e:
            print(f"Exception in run_tasks: {e}")
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
            if result is not TERMINATION_SIGNAL:
                new_result = process_fn_with_timeout(fn, timeout, *args, **kwargs)
                if callback and new_result is not None:
                    new_result = callback(new_result, args, kwargs)
                task_queue.put(new_result)
        except Exception as e:
            traceback.print_exc()
            print(f"Exception in task_worker: {e}")
            task_queue.put(None)  # Put None to indicate an error

    process_fn_with_timeout = ProcessFnWithTimeout(Queue())

    def run_tasks():
        try:
            args_list = []
            futures = []
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                while True:
                    result = input_queue.get()
                    if result is TERMINATION_SIGNAL or result is FINISHED_TASK or result == FINISHED_TASK:  # End of results
                        break
                    if result is None:
                        continue
                    args, kwargs = result
                    future = pool.submit(task_worker, result, [args], kwargs)
                    futures.append(future)
                for future in futures:
                    future.result()
        except Exception as e:
            print(f"Exception in run_tasks: {e}")
        finally:
            # Signal the end of the task results
            task_queue.put(TERMINATION_SIGNAL)
            task_queue.put(FINISHED_TASK)

    # Start a separate thread to run the tasks
    orchestrator_thread = threading.Thread(target=run_tasks)
    orchestrator_thread.start()

    # Return the task queue immediately
    return task_queue


def dual_orchestrator(fn1, fn2, args_list, callback=None, max_workers=32, timeout=60):
    if not isinstance(args_list, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in args_list):
        raise ValueError("args_list must be a list of tuples containing (*args, **kwargs)")

    task_queue1 = orchestrator(fn1, args_list, max_workers=max_workers, timeout=timeout)
    task_queue2 = orchestrator_with_queue(task_queue1, fn2, callback, max_workers=max_workers, timeout=timeout)

    return task_queue2















