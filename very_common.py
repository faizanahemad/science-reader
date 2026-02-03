import random
import tempfile
import asyncio
import traceback
import more_itertools
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, ProcessPoolExecutor

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

import requests
import os

FINISHED_TASK = TERMINATION_SIGNAL = "TERMINATION_SIGNAL"

def string_indicates_true(s):
    return str(s).strip().lower() == "yes" or str(s).strip().lower() == "true" or str(s).strip().lower() == "1" or str(s).strip().lower() == "y" or str(s).strip().lower() == "t" or int(s) >= 1

def round_robin(arr, randomize=True):
    if randomize:
        random.shuffle(arr)
    while True:
        for item in arr:
            yield item

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


executor = ThreadPoolExecutor(max_workers=256)

def make_async(fn, execution_trace="", executor=executor):
    def async_fn(*args, **kwargs):
        func_part = partial(fn, *args, **kwargs)
        future = executor.submit(func_part)
        setattr(future, "execution_trace", execution_trace)
        return future
    return async_fn

def get_async_future(fn, *args, **kwargs):
    import traceback
    execution_trace = traceback.format_exc()
    # Make your function async
    if "executor" in kwargs:
        executor = kwargs.pop("executor")
    
        afn = make_async(fn, execution_trace, executor)
    else:
        afn = make_async(fn, execution_trace)
    # This will return a Future object, you can call .result() on it to get the result
    future = afn(*args, **kwargs)
    return future


def wrap_in_future(s):
    future = Future()
    future.set_result(s)
    return future

def sleep_and_get_future_result(future, sleep_time=0.2, timeout=1000):
    start_time = time.time()
    while not future.done():
        time.sleep(sleep_time)
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Timeout waiting for future for {timeout} sec")
    return future.result()

def sleep_and_get_future_exception(future, sleep_time=0.2, timeout=1000):
    start_time = time.time()
    while not future.done():
        time.sleep(sleep_time)
        if time.time() - start_time > timeout:
            return TimeoutError(f"Timeout waiting for future for {timeout} sec")
    return future.exception()

def checkNoneOrEmpty(x):
    if x is None:
        return True
    elif isinstance(x, str):
        return len(x.strip())==0
    elif isinstance(x, str) and x.strip().lower() in ['null', 'none']:
        return x.strip().lower() in ['null', 'none']
    else:
        return len(x) == 0