from datetime import datetime
import sys
import os
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
from typing import List

import pandas as pd
import tiktoken
from copy import deepcopy, copy
import requests

import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
import urllib3

from base import CallLLm

urllib3.disable_warnings()
import requests
import re
import traceback
import subprocess
import tempfile

import logging
from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)

def code_runner_with_retry(instructions: str, rules: List[str], llm: CallLLm, code_string: str = "", retry=3):
    """
    Executes the given code_string with specified resource constraints and captures the output.

    Parameters:
    - code_string (str): The Python code to execute.
    - constraints (dict): A dictionary of constraints.
    - retry (int): The number of times to retry the code execution in case of failure.

    Returns:
    - success (bool): True if the code executed successfully, False otherwise.
    - failure_reason (Exception): The exception that caused the code to fail, if any.
    - stdout (str): The standard output of the code.
    - stderr (str): The standard error of the code.
    """

    if code_string.strip() == "":
        code_string = write_code_with_llm(instructions, rules, llm)

    for i in range(retry):
        success, failure_reason, stdout, stderr = run_code_with_constraints(code_string)
        if success:
            return success, failure_reason, stdout, stderr
        else:
            code_string = write_code_with_llm(instructions, rules, llm, previous_code=code_string, previous_failure=failure_reason)
    return success, failure_reason, stdout, stderr



def write_code_with_llm(instructions: str, rules: List[str], llm: CallLLm, previous_code: str = "", previous_failure: str = '') -> str:
    assert llm is not None, "LLM object is None"
    previous_code = previous_code.strip()
    if previous_code:
        previous_code = f"\n\n## Previous code\n```{previous_code}```"
    previous_failure = previous_failure.strip()
    if previous_failure:
        previous_failure = f"\n\n## Previous failure\n```{previous_failure}```"

    prompt = f"""
You are an expert python programmer and an expert in data analysis, python plotting and graphing. 
You know python machine learning, data science and analytics libraries like scikit, pandas, numpy, scipy, matplotlib, seaborn, etc.
You may need to perform data analysis, data visualization, and output to either stdout or to a file or make a plot or a combination of these.
# Instructions for the task is given below. Please write full python code to help solve this problem with executable code. Please read the instructions carefully before writing the code.
{instructions}

# Rules
{rules}

{previous_code}

{previous_failure}

# Write your code below this line inside triple ticks ( ```python ). 
"""
    code_string = llm(prompt, stream=False)
    return extract_code(code_string)

def extract_code(code_string):
    regex = r"<code action=\"execute\">(.*?)</code>"
    code_to_execute = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    code_to_execute = [c.strip() for c in code_to_execute]
    code_to_execute = "\n".join(code_to_execute)
    if code_to_execute:
        code_string = code_to_execute
    else:
        # separate on triple ticks using regex.
        regex = r"```python(.*?)```"
        code_to_execute = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        code_to_execute = [c.strip() for c in code_to_execute]
        code_to_execute = "\n".join(code_to_execute)
        if "# execute" in code_to_execute.lower():
            code_string = code_to_execute
        else:
            code_string = ""

    return code_string




def extract_drawio(code_string):
    regex = r"```<pre class=\"drawio\">(.*?)</pre>```"
    drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    drawio = [c.strip() for c in drawio]
    drawio = "\n".join(drawio)
    if drawio.strip() != "" and "<mxfile>" in drawio.lower():
        return drawio
    else:
        regex = r"```xml(.*?)```"
        drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        drawio = [c.strip() for c in drawio]
        drawio = "\n".join(drawio)
        if drawio.strip() != "" and "<mxfile>" in drawio.lower():
            return drawio
        else:
            regex = r"```(.*?)```"
            drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
            drawio = [c.strip() for c in drawio]
            drawio = "\n".join(drawio)
            if drawio.strip() != "" and "<mxfile>" in drawio.lower():
                return drawio
    return ''

def extract_mermaid(code_string):
    regex = r"```mermaid(.*?)```"
    mermaid = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    mermaid = [c.strip() for c in mermaid]
    mermaid = "\n".join(mermaid)
    if mermaid.strip() != "" and "graph" in mermaid.lower():
        return mermaid
    return ''





mem_and_cpu_limit_str = """  
import resource  
current_limits = [v / (1024 * 1024) for v in resource.getrlimit(resource.RLIMIT_AS)  ]
# print("Current memory limit: ", current_limits)

MEMORY_LIMIT = int(500 * 1024 * 1024)  # 500MB  
CPU_TIME_LIMIT = 60  # 60 seconds  
WRITE_LIMIT = 10 * 1024 * 1024  # 10MB  

# print("Setting memory limit to: ", MEMORY_LIMIT)

def set_mem_limit():  
    # Check current limits  
    current_mem_limits = resource.getrlimit(resource.RLIMIT_AS)  
    current_cpu_limits = resource.getrlimit(resource.RLIMIT_CPU)  
    current_write_limits = resource.getrlimit(resource.RLIMIT_FSIZE)  
    assert MEMORY_LIMIT <= current_mem_limits[1]
      
    # Set new limits within allowable range  
    new_mem_limit = min(500 * 1024 * 1024, current_mem_limits[1])  
    new_cpu_limit = min(60, current_cpu_limits[1])  
    new_write_limit = min(10 * 1024 * 1024, current_write_limits[1])
      
    # resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, current_mem_limits[1]))  
    resource.setrlimit(resource.RLIMIT_CPU, (new_cpu_limit, new_cpu_limit))  
    resource.setrlimit(resource.RLIMIT_FSIZE, (new_write_limit, new_write_limit))  


# Call the function to apply the limits  
set_mem_limit()  
"""


def run_code_with_constraints(code_string, constraints={}):
    """
    Executes the given code_string with specified resource constraints and captures the output.

    Parameters:
    - code_string (str): The Python code to execute.
    - constraints (dict): A dictionary of constraints.

    Returns:
    - success (bool): True if the code executed successfully, False otherwise.
    - failure_reason (Exception): The exception that caused the code to fail, if any.
    - stdout (str): The standard output of the code.
    - stderr (str): The standard error of the code.
    """
    memory = constraints.get("memory", 1500)
    time = constraints.get("time", 30)
    code_string = mem_and_cpu_limit_str.format(memory=memory, time=time) + "\n" + code_string
    # Remove any line with plt.show() from the code
    code_string = "\n".join([line for line in code_string.split("\n") if "plt.show()" not in line])
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.py') as tmp_file:
        tmp_file.write(code_string)
        tmp_file_path = tmp_file.name
    stdout, stderr = None, None
    try:
        proc = subprocess.Popen([sys.executable, tmp_file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(timeout=60)
        success = True
        failure_reason = None
        logger.info("Code executed successfully.")
    except subprocess.CalledProcessError as e:
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False
    except subprocess.TimeoutExpired as e:
        logger.info("The script exceeded the time limit. Terminating process.")
        proc.kill()
        stdout, stderr = proc.communicate()
        logger.info("Process terminated.")
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False
    except Exception as e:
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False
    finally:
        os.remove(tmp_file_path)

    if stderr:
        stderr = stderr.decode()
    else:
        stderr = ""
    if stdout:
        stdout = stdout.decode()
    else:
        stdout = ""
    failure_reason = f"Raised Exception Message and stack trace:\n```{failure_reason}```" + f"\n\nStd Err Output:\n```{stderr}```"
    return success, failure_reason, stdout, stderr

if __name__ == "__main__":
    code = """
import time
print("Starting...")
time.sleep(10)
print("Finished.")
"""
    stdout, stderr = run_code_with_constraints(code)
    print("STDOUT:", stdout)
    print("STDERR:", stderr)