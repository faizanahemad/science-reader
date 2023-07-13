import asyncio
import threading
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, ProcessPoolExecutor
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

from multiprocessing import Process, Queue
from functools import partial

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

executor = ThreadPoolExecutor(max_workers=16)

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
    logger.info(f"type args = {type(args)}, type kwargs = {type(kwargs)}, Pickle able:: function = {is_picklable(function)}, {is_picklable(args)}, {is_picklable(kwargs)}, Is Dill able:: function = {is_dillable(function)}, {is_dillable(args)}, {is_dillable(kwargs)}")
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
        logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds, result: {result}")
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
        logger.info(f"Execution time of {func.__name__}: {end_time - start_time} seconds, result: {accum}")
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
    res = fn(*args, **kwargs)
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
        except StopIteration:
            # Here you could handle the empty generator case.
            raise
        except Exception as e:
            # Here you could handle other exceptions.
            raise
        else:
            # If no exception was raised, return the peekable generator.
            return peeked
    else:
        # If it's not a string or a generator, raise an exception.
        raise ValueError("Unexpected input type.")
        
def get_first_n_words(my_string, n=700):
    words = my_string.split()
    if len(words) < n:
        return my_string
    return ' '.join(words[:n])


def parse_array_string(s):
    import re
    s = re.sub(r"(?<=[a-zA-Z0-9])'(?!(, ?|]))", "@@", s)
    parsed_list = eval(s)
    parsed_list = [i.replace("@@", "'") for i in parsed_list]
    return parsed_list



def normalize_whitespace(s):
    return re.sub(r'\s+', ' ', s).strip()







