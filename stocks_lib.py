from common import *
from datetime import datetime
import sys
import random
from functools import partial
import glob
import traceback
from operator import itemgetter
import itertools
from queue import Empty
import re
import inspect
import random

import concurrent.futures
import pandas as pd
import tiktoken
from copy import deepcopy, copy
import requests

import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
import urllib3
urllib3.disable_warnings()
import requests
import re
import traceback

from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)

def get_ticker_from_company_name(company_name):
    try:
        company_name = company_name.lower()
        company_name = re.sub(r'[^a-z0-9]', '', company_name)
        company_name = company_name[:4]
        return company_name
    except Exception as e:
        logger.error(f"Error in get_ticker_from_company_name: {e}")
        return None