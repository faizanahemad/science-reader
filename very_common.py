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