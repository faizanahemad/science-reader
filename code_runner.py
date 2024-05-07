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
import re
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
import urllib3

from base import CallLLm
from prompts import prompts

urllib3.disable_warnings()
import requests
import re
import traceback
import subprocess
import tempfile
import warnings
warnings.filterwarnings("ignore")

import logging
from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)

from IPython.core.interactiveshell import InteractiveShell
from IPython.core.error import UsageError
# Assuming logging is already set up elsewhere in your code
import signal
import sys
import threading
from io import StringIO
class TimeoutException(Exception):
    pass
def timeout_handler(signum, frame):
    raise TimeoutException("Code execution timed out")


class ThreadLocalStringIO(threading.local):
    def __init__(self):
        self.stdout_buffer = StringIO()
        self.stderr_buffer = StringIO()


def strip_formatting(text):
    # Remove ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)

    # Remove terminal-specific formatting
    text = text.replace('\r', '')
    text = text.replace('\b', '')
    text = text.replace('\a', '')

    return text


class PersistentPythonEnvironment:
    def __init__(self):
        self.shell = InteractiveShell.instance()
        self.thread_local_io = ThreadLocalStringIO()
        from IPython import get_ipython
        ipython = get_ipython()
        ipython.run_line_magic('config', 'TerminalInteractiveShell.color_info = False')
        ipython.run_line_magic('config', 'TerminalInteractiveShell.highlight_matching_brackets = False')

    def run_code(self, code_string, session_id, time_limit):
        """
        Execute the code and capture the output.
        """
        # Store the original stdout and stderr
        self.thread_local_io = ThreadLocalStringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        # Redirect stdout and stderr to thread-local StringIO objects
        sys.stdout = self.thread_local_io.stdout_buffer
        sys.stderr = self.thread_local_io.stderr_buffer
        stdout = stderr = ""

        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self.shell.run_cell, code_string)
                output = future.result(timeout=time_limit)

            stdout = self.thread_local_io.stdout_buffer.getvalue()
            stderr = self.thread_local_io.stderr_buffer.getvalue()
            # Strip formatting from stdout and stderr
            stdout = strip_formatting(stdout)
            stderr = strip_formatting(stderr)

            if output.success:
                logger.info(f"Code that we ran is: \n{code_string}\n, success = {output.success}, \nstdout is: \n{stdout}\n, stderr is: \n{stderr}")
                logger.info("Code executed successfully.")
                return True, None, stdout, stderr
            else:
                if output.error_before_exec:
                    failure_reason = f"Error before execution: {output.error_before_exec}"
                    return False, failure_reason, stdout, stderr
                exception = output.error_in_exec
                logger.info(f"Code that we ran is: \n{code_string}\n, success = {output.success}, \nstdout is: \n{stdout}\n, stderr is: \n{stderr}")
                logger.info(f"Code execution failed with error: {exception}")
                # Extracting the exception trace from the error object
                if isinstance(exception, UsageError):
                    exception_trace = exception.etype.__name__ + ": " + str(exception.evalue)
                else:
                    exception_trace = str(exception)
                return False, exception_trace, stdout, stderr

        except concurrent.futures.TimeoutError:
            logger.info("The script exceeded the time limit. Terminating process.")
            stdout = self.thread_local_io.stdout_buffer.getvalue()
            stderr = self.thread_local_io.stderr_buffer.getvalue()
            # Strip formatting from stdout and stderr
            stdout = strip_formatting(stdout)
            stderr = strip_formatting(stderr)
            return False, "Code Timeout", stdout, stderr

        except Exception as e:
            logger.info(f"Unexpected error occurred: {e}")
            return False, str(e), stdout, stderr

        finally:
            # Restore stdout and stderr to their original values
            sys.stdout = original_stdout
            sys.stderr = original_stderr
def code_runner_with_retry(instructions: str, rules: List[str], llm_hard: CallLLm, llm_easy: CallLLm, code_string: str = "",
                           session: PersistentPythonEnvironment=None, retry=3):
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
        code_string = write_code_with_llm(instructions, rules, llm_hard)

    all_stdout = []
    for i in range(retry):
        success, failure_reason, stdout, stderr = run_code_with_constraints_v2(code_string, session=session)
        logger.info(f"[code_runner_with_retry] Code execution attempt {i+1} with success: {success}, failure_reason: {failure_reason}, stdout: {stdout}, stderr: {stderr}")
        if failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None":
            success, failure_reason, stdout, stderr, code_string_from_checker = code_checker_and_continuer(instructions, rules, llm_easy, session, code_string, stdout, failure_reason)
            if code_string_from_checker != code_string:
                code_string = code_string_from_checker
        else:
            if not code_checker(instructions, rules, llm_easy, session, code_string, stdout):
                success, failure_reason, stdout, stderr, code_string_from_checker = code_checker_and_continuer(
                    instructions, rules, llm_easy, session, code_string, stdout, str(failure_reason))
                if code_string_from_checker != code_string:
                    code_string = code_string_from_checker
        all_stdout.append(stdout)

        if success:
            if len(stdout.split("\n")) > 10:
                stdout = extract_relevant_from_stdout(instructions, llm_easy, code_string, stdout)
            return success, failure_reason, stdout, stderr, code_string
        else:
            code_string = write_code_with_llm(instructions, rules, llm_hard, previous_code=code_string, previous_stdout=stdout, previous_failure=failure_reason)
    return success, failure_reason, stdout, stderr, code_string


def extract_relevant_from_stdout(instructions: str, llm: CallLLm, code:str, stdout: str):
    # Remove exceptions, repeats from stdout based on code and instructions using LLM
    assert llm is not None, "LLM object is None"
    prompt = f"""
You are an expert python programmer, a seasoned code reviewer, a test and qa engineer, a sincere and earnest software engineer, and an avid reader.
Your goal is to read the provided coding task instructions we performed earlier, read the code written to complete the task, and then read the output generated by the code execution. Then you will write a cleaned version of the output.
To write the cleaned version of the output, you will remove any exceptions, errors, or warnings from the output. You will also remove any repeated or redundant information from the output. 
You will only keep the relevant information that is useful and important. Remove any print statements for debugging, debug information, or any other unnecessary information from the output.
Write the cleaned output inside <output> </output> tags like this: <output> cleaned output here </output>.

# Coding task instructions we performed earlier is given below. Please read the instructions carefully before writing the cleaned output.
{instructions}

Actual code written to complete the task is given below:
```python
{code}
```

The output generated by the code execution is given below:
```
{stdout}
```

# Just Write the cleaned version of the output inside <output> </output> tags by removing any exceptions, errors, warnings, repeated or redundant information, and keeping only the relevant information that is useful and important.
"""
    llm_answer = llm(prompt, stream=False)
    regex = r"<output>(.*?)</output>"
    cleaned_output = re.findall(regex, llm_answer, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    if len(cleaned_output) == 0:
        cleaned_output = llm_answer
    else:
        cleaned_output = [c.strip() for c in cleaned_output]
        cleaned_output = "\n".join(cleaned_output)
    return cleaned_output


def code_checker_and_continuer(instructions: str, rules: List[str], llm: CallLLm, session: PersistentPythonEnvironment, previous_code: str, previous_stdout: str, previous_failure: str):
    assert llm is not None, "LLM object is None"
    previous_code = previous_code.strip()
    code_string = previous_code
    if previous_code:
        previous_code = f"\n\n## Previous code\n```python\n{previous_code}\n```\n\nConvert any pseudo-code or incomplete code (or placeholder) from previous code while correcting code to actual complete executable code with proper and full implementation.\n"
    if previous_failure:
        previous_failure = previous_failure.strip()
    correction_prompt = ""
    if previous_failure:
        previous_failure = f"\n\n## Previous failure or errors from above code execution:\n```\n{previous_failure}\n```"
        correction_prompt = f"""Please correct the code by looking at the exception message and stack trace above and write code only after the point of failure. Make any other changes as needed to solve the task and get the code running.\nConvert any pseudo-code or incomplete code (or placeholder) from previous code while correcting code to actual complete executable code with proper and full implementation.\nAnalyse the previous code and describe what it was supposed to do and where it failed.\nAnalyse each line of code previously written and correct any line that is a placeholder or needs correction.\nFirst write your thoughts on why the previous code failed. Then write how you plan to correct the code and what steps you will take. Then write partial code from the point from which correction needs to be made.\n"""
    llm_input_stdout = ""
    if previous_stdout:
        llm_input_stdout = f"\n\n## Previous stdout from above code execution:\n```\n{previous_stdout}\n```\nThe output may not be complete or useful. Please write the code carefully and execute it to get the correct output if needed.\n"

    prompt = f"""
You are an expert python programmer, a seasoned code reviewer, a test and qa engineer, a sincere and earnest software engineer, and an expert in data analysis, python plotting and graphing. 
You are able to write code as well as fix errors and bugs in existing code. Please what parts of code are correct and what parts are incorrect and need correction and then write from the incorrect point onwards.
You know python machine learning, data science and analytics libraries like scikit, pandas, numpy, scipy, matplotlib, seaborn, networkx and many other standard python libraries in very deep details with great fluency.
You may need to perform data analysis, data visualization, and output to either stdout or to a file or make a plot or a combination of these.
We have persisted the results and session variables, globals and locals of the previous code execution till the point it ran successfully. You can use these variables and results and continue to write after from the point of failure.
If output is incomplete or we have errors then write actual runnable code (after the last good line of code that worked) and convert any pseudo-code or incomplete code (or placeholder) to actual complete executable code with proper and runnable implementation.
If output is correct and as expected then you can skip this task and just say that written code is correct and output looks as expected. Convert example and placeholders to actual code if output looks wrong or if code has given errors.

# Instructions for the task is given below. Please write partial python code to help solve this problem with executable code from the earlier failure point. If no new code needs to be written and output of previous code is as expected, you can skip this task and just say that written code is correct and output looks as expected. 
{instructions}

# Some Coding Rules we followed earlier are given below:
{rules}

The above rules are helpful to understand our coding system but here you need to write partial code from the point of failure in previous code. If no new code needs to be written and output of previous code is as expected, you can skip this task and just say that written code is correct and output looks as expected.

{previous_code}
{llm_input_stdout}
{previous_failure}
{correction_prompt}

# Write only corrected partial code (if needed, after the point of failure or error or mistake afterwards) in python. Think about the problem and write the partial code carefully from the point of failure.
"""
    llm_answer = llm(prompt, stream=False)
    new_code_string = extract_code(llm_answer, relax=True)
    if new_code_string.strip() != "":
        success, failure_reason, stdout, stderr = run_code_with_constraints_v2(new_code_string, session=session)
        code_string = "\n".join(["\t" + line for line in code_string.split("\n")])
        code_string = "\n".join([line for line in code_string.split("\n") if "plt.show()" not in line])
        new_code_string = "\n".join(["\t" + line for line in new_code_string.split("\n")])
        new_code_string = "\n".join([line for line in new_code_string.split("\n") if "plt.show()" not in line])
        code_string = f"""
try:
{code_string}
except Exception as e:
{new_code_string}
"""
        new_stdout = previous_stdout + "\n" + stdout.strip()
        logger.info(f"[code_checker_and_continuer] Code and output correctness decision is: {False}, from LLM answer: `\n{llm_answer}\n`")
        return False, failure_reason, new_stdout, stderr, code_string
    else:
        logger.info(f"[code_checker_and_continuer] Code and output correctness decision is: {True}, from LLM answer: `\n{llm_answer}\n`")
        return True, "None", previous_stdout, "", code_string

def code_checker(instructions: str, rules: List[str], llm: CallLLm, session: PersistentPythonEnvironment, previous_code: str, previous_stdout: str) -> bool:
    assert llm is not None, "LLM object is None"
    previous_code = previous_code.strip()
    if previous_code:
        previous_code = f"\n\n## Previous code\n```python\n{previous_code}\n```\n\nConvert any pseudo-code or incomplete code (or placeholder) from previous code while correcting code to actual complete executable code with proper and full implementation.\n"

    prompt = f"""
You are an expert python programmer, a seasoned code reviewer, a test and qa engineer, a sincere and earnest software engineer, and an expert in data analysis, python plotting and graphing.
Your goal is to read the provided coding task instructions we performed earlier, read the code written to complete the task, and then read the output generated by the code execution. Then you will decide if the code is correct and output is as expected or not.
If code is correct and complete, output is complete and correct and there are no errors then consider the execution as successful and write your decision on the code correctness and output correctness inside <is_code_and_output_correct> </is_code_and_output_correct> tags like this: <is_code_and_output_correct> yes </is_code_and_output_correct>.
If output is incomplete or we have errors or we have pseudo-code or incomplete code (or placeholder) then consider the execution as failed and write your decision on the code correctness and output correctness inside <is_code_and_output_correct> </is_code_and_output_correct> tags like this: <is_code_and_output_correct> no </is_code_and_output_correct>.
Write your decision on the code and output correctness inside <is_code_and_output_correct> </is_code_and_output_correct> tags like this: <is_code_and_output_correct> yes </is_code_and_output_correct> or <is_code_and_output_correct> no </is_code_and_output_correct>.

# Coding task instructions we performed earlier is given below. Please read the instructions carefully before writing the cleaned output.
{instructions}

Actual code written to complete the task is given below:
```python
{previous_code}
```

The output generated by the code execution is given below:
```
{previous_stdout}
```

Write your decision on the code and output correctness inside <is_code_and_output_correct> </is_code_and_output_correct> tags like this:<is_code_and_output_correct> no </is_code_and_output_correct>  or <is_code_and_output_correct> yes </is_code_and_output_correct>. 
"""

    llm_answer = llm(prompt, stream=False).lower()
    regex = r"<is_code_and_output_correct>(.*?)</is_code_and_output_correct>"
    decision = re.findall(regex, llm_answer, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    if len(decision) == 0:
        decision = "yes" in llm_answer
    else:
        decision = [c.strip() for c in decision]
        decision = "\n".join(decision)
        decision = decision.lower().strip()
        if "yes" in decision:
            decision = True
        else:
            decision = False
    logger.info(f"[code_checker] Code and output correctness decision is: {decision}, from LLM answer: `{llm_answer}`")
    return decision

def write_code_with_llm(instructions: str, rules: List[str], llm: CallLLm, previous_code: str = "", previous_stdout: str='', previous_failure: str = '') -> str:
    assert llm is not None, "LLM object is None"
    previous_code = previous_code.strip()
    if previous_code:
        previous_code = f"\n\n## Previous code\n```python\n{previous_code}\n```\n\nConvert any pseudo-code or incomplete code (or placeholder) from previous code while correcting code to actual complete executable code with proper and full implementation.\n"
    previous_failure = previous_failure.strip()
    correction_prompt = ""
    if previous_failure:
        previous_failure = f"\n\n## Previous failure from above code execution:\n```\n{previous_failure}\n```"
        correction_prompt = f"""Please correct the code by looking at the exception message and stack trace above. Make any other changes as needed to solve the task and get the code running.\nConvert any pseudo-code or incomplete code (or placeholder) from previous code while correcting code to actual complete executable code with proper and full implementation.\nAnalyse the previous code and describe what it was supposed to do and where it failed.\nAnalyse each line of code previously written and correct any line that is a placeholder or needs correction.\nFirst write your thoughts on why the previous code failed. Then write how you plan to correct the code and what steps you will take. Then write the full and complete corrected code.\n"""
    if previous_stdout:
        previous_stdout = f"\n\n## Previous stdout from above code execution:\n```\n{previous_stdout}\n```"

    prompt = f"""
You are an expert python programmer, a sincere and earnest software engineer, and an expert in data analysis, python plotting and graphing. You are able to write code as well as fix errors and bugs in existing code.
You know python machine learning, data science and analytics libraries like scikit, pandas, numpy, scipy, matplotlib, seaborn, networkx and many other standard python libraries in very deep details with great fluency.
You may need to perform data analysis, data visualization, and output to either stdout or to a file or make a plot or a combination of these.
Write actual runnable code and convert any pseudo-code or incomplete code (or placeholder) to actual complete executable code with proper and full implementation on each line with proper comments.

# Instructions for the task is given below. Please write full python code to help solve this problem with executable code. Please read the instructions carefully before writing the code.
{instructions}

# Coding Rules are given below:
{rules}

{previous_code}
{previous_stdout}
{previous_failure}
{correction_prompt}

# Write corrected code in python. Think about the problem and write the code carefully. 
"""
    llm_answer = llm(prompt, stream=False)
    code_string = extract_code(llm_answer, relax=True)
    return code_string

def extract_code(code_string, relax=False):
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
        if "# execute" in code_to_execute.lower() or relax:
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
import warnings
warnings.filterwarnings("ignore")
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
    # assert MEMORY_LIMIT <= current_mem_limits[1]
      
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

try_catch_block = """
import traceback  
import sys
from io import StringIO
try:  
{code}
except Exception as e:  
    print(f"An error {{str(e)}} occurred:", file=sys.stderr)  
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
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
    time = constraints.get("time", 120)
    code_string = "\n".join([line for line in code_string.split("\n") if "plt.show()" not in line])
    code_string = "\n".join(["\t" + line for line in code_string.split("\n")])
    code_string = mem_and_cpu_limit_str.format(memory=memory, time=time) + "\n" + try_catch_block.format(code=code_string)
    # Remove any line with plt.show() from the code
    logger.info("Actual Executed code is: \n" + code_string)
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.py') as tmp_file:
        tmp_file.write(code_string)
        tmp_file_path = tmp_file.name
    stdout, stderr = None, None
    try:
        proc = subprocess.Popen([sys.executable, tmp_file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(timeout=time)
        if proc.returncode != 0:
            logger.info("Code execution failed with error as below:\n" + stderr.decode())
        else:
            logger.info("Code executed successfully.")
        success = (proc.returncode == 0)
        failure_reason = None if success else stderr.decode()
    except subprocess.CalledProcessError as e:
        failure_reason = str(e) + "\n" + traceback.format_exc() + "\n" + (stderr.decode() if stderr else "")
        success = False
    except subprocess.TimeoutExpired as e:
        logger.info("The script exceeded the time limit. Terminating process.")
        proc.kill()
        stdout, stderr = proc.communicate()
        logger.info("Process terminated.")
        failure_reason = f"The script exceeded the time limit of {time} seconds."
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
    failure_reason = f"Raised Exception Message and stack trace:\n{failure_reason}\n"
    return success, failure_reason, stdout, stderr


try_catch_block_v2 = """
import traceback  
import sys
from io import StringIO
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings("ignore")

prnt = print
class MyPrint:
    def __init__(self):
        self.stdout_buffer = StringIO()

    def __call__(self, *args):
        prnt(*args, file=self.stdout_buffer)

    def __str__(self):
        return self.stdout_buffer.getvalue()

print = MyPrint()
did_we_print = False
try:  
{code}
except Exception as e:  
    if not did_we_print:
        prnt("-x-=" * 40)
        prnt(str(print))
        print = prnt
    print(f"An error {{str(e)}} occurred:", file=sys.stderr)  
    traceback.print_exc(file=sys.stderr)
    raise e
"""
def run_code_with_constraints_v2(code_string, constraints={}, session: PersistentPythonEnvironment=None):
    """
    Executes the given code_string with specified resource constraints and captures the output.

    Parameters:
    - code_string (str): The Python code to execute.
    - constraints (dict): A dictionary of constraints.
    - session (PersistentPythonEnvironment): The persistent python environment to use for code execution.

    Returns:
    - success (bool): True if the code executed successfully, False otherwise.
    - failure_reason (Exception): The exception that caused the code to fail, if any.
    - stdout (str): The standard output of the code.
    - stderr (str): The standard error of the code.
    """
    if session is None:
        session = PersistentPythonEnvironment()
    memory = constraints.get("memory", 1500)
    time = constraints.get("time", 120)
    code_string = "\n".join([line for line in code_string.split("\n") if "plt.show()" not in line])
    code_string += """
prnt("-x-=" * 40)
did_we_print = True
prnt(str(print))
print = prnt
"""
    code_string = "\n".join(["\t" + line for line in code_string.split("\n")])
    # logger.info("Actual Executed code is: \n" + code_string)
    code_string = mem_and_cpu_limit_str.format(memory=memory, time=time) + "\n" + try_catch_block_v2.format(code=code_string)
    # Remove any line with plt.show() from the code
    stdout, stderr = None, None
    try:
        success, failure_reason, stdout, stderr = session.run_code(code_string, "123", time)
        if stdout:
            stdout = stdout.strip()
            split_string = "-x-=" * 40
            if split_string in stdout:
                stdout = stdout.split(split_string)[1]
                if stdout:
                    stdout = stdout.strip()
        if not success or stderr.strip()!= "":
            logger.info("Code execution failed with error as below:\n" + stderr)
        else:
            logger.info(f"Code that we ran is: \n{code_string}\n, success = {success}, \nstdout is: \n{stdout}\n, stderr is: \n{stderr}")
            logger.info("Code executed successfully.")
        failure_reason = f"{failure_reason}\n{stderr}".strip()

    except Exception as e:
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False

    if failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None":
        failure_reason = f"Raised Exception Message and stack trace:\n{failure_reason}\n"
    if stderr:
        stderr = stderr.strip()

    return success, failure_reason, stdout, stderr



if __name__ == "__main__":
    code = """
import time
from stocks_lib.equity_data_fetcher import get_equity_history
print("Starting...")
# print(get_equity_history('RELIANCE', "2 months").head(5))
print(1 + 1)
print(1/1)
time.sleep(5)
print("Finished.")
"""

    code_2 = """
# execute  
import pandas as pd  
import numpy as np  
from stocks_lib.equity_data_fetcher import get_equity_history  
  
# Fetching the last 2 months of Reliance stock data  
history_df = get_equity_history('RELIANCE', "2 months")  
  
# Calculating the standard deviation of closing prices  
std_deviation = history_df['CH_CLOSING_PRICE'].std()  
print("Standard Deviation of Closing Prices: ", std_deviation)  

# execute  
# Placeholder for market returns  
market_returns = pd.Series([...])  # This should be the actual market returns  
  
# Calculating covariance between Reliance returns and market returns  
covariance = np.cov(history_df['daily_returns'].dropna(), market_returns.dropna())[0][1]  
  
# Calculating variance of the market returns  
variance = market_returns.var()  
  
# Calculating beta  
beta = covariance / variance  
print("Beta of Reliance: ", beta)  


# execute  
# Calculating moving average  
history_df['moving_average'] = history_df['CH_CLOSING_PRICE'].rolling(window=20).mean()  
  
# Calculating moving standard deviation  
history_df['moving_std_dev'] = history_df['CH_CLOSING_PRICE'].rolling(window=20).std()  
  
# Calculating upper and lower bands  
history_df['upper_band'] = history_df['moving_average'] + (history_df['moving_std_dev'] * 2)  
history_df['lower_band'] = history_df['moving_average'] - (history_df['moving_std_dev'] * 2)  
  
# Displaying the first few rows of the dataframe to verify the calculations  
print(history_df[['moving_average', 'upper_band', 'lower_band']].head())  

    """


    # success, falure_reason, stdout, stderr = run_code_with_constraints(code)
    # print("STDOUT:", stdout)
    # print("STDERR:", stderr)

    # success, failure_reason, stdout, stderr = PersistentPythonEnvironment().run_code(code, "123", 2)
    # print(f"Success: {success}, Failure Reason: {failure_reason}, STDOUT: {stdout}, STDERR: {stderr}")
    #
    # success, failure_reason, stdout, stderr = run_code_with_constraints_v2(code)
    # print(f"Success: {success}, Failure Reason: {failure_reason}, STDOUT: {stdout}, STDERR: {stderr}")
    keys = None
    llm_hard = CallLLm(use_gpt4=True, use_16k=True,
                       keys=keys)
    llm_easy = CallLLm(use_gpt4=True, use_16k=True,
                       keys=keys)
    success, failure_reason, stdout, stderr, codes_string = code_runner_with_retry(
        """
Write a python code to fetch the equity history for RELIANCE from the last 2 months and calculate the standard deviation of closing prices, beta of Reliance, and moving average, upper band, and lower band of the closing prices.",
"You should use the get_equity_history function from the stocks_lib.equity_data_fetcher module to fetch the equity history.
Output example is given below.

Example Code:
```python
from stocks_lib.equity_data_fetcher import get_equity_history  
history_df = get_equity_history('RELIANCE', "2 months") # dataframe  
print(history_df.head())
```

Output of example code:
```
                         _id CH_SYMBOL CH_SERIES CH_MARKET_TYPE CH_TIMESTAMP                 TIMESTAMP  CH_TRADE_HIGH_PRICE  CH_TRADE_LOW_PRICE  CH_OPENING_PRICE  CH_CLOSING_PRICE  CH_LAST_TRADED_PRICE  CH_PREVIOUS_CLS_PRICE  CH_TOT_TRADED_QTY  CH_TOT_TRADED_VAL  CH_52WEEK_HIGH_PRICE  CH_52WEEK_LOW_PRICE  CH_TOTAL_TRADES       CH_ISIN                 createdAt                 updatedAt  __v SLBMH_TOT_VAL     VWAP   mTIMESTAMP  
0   661d170667f74c7b05bb4577  RELIANCE        EQ              N   2024-04-15  2024-04-14T18:30:00.000Z              2964.25             2892.65           2922.00           2929.65               2931.00                2934.30            6451031       1.894981e+10                3024.9               2220.3           278625  INE002A01018  2024-04-15T12:01:10.178Z  2024-04-15T12:01:10.178Z    0          None  2937.49  15-Apr-2024  
1   661e687fc1cb1b138131ff3a  RELIANCE        EQ              N   2024-04-16  2024-04-15T18:30:00.000Z              2942.35             2901.85           2906.70           2931.50               2936.50                2929.65            4683092       1.368756e+10                3024.9               2220.3           202013  INE002A01018  2024-04-16T12:01:03.308Z  2024-04-16T12:01:03.308Z    0          None  2922.76  16-Apr-2024  
2   66210b92e76a74aef2218d18  RELIANCE        EQ              N   2024-04-18  2024-04-17T18:30:00.000Z              2972.00             2918.70           2927.00           2928.65               2925.00                2931.50            9502846       2.794153e+10                3024.9               2220.3           292105  INE002A01018  2024-04-18T12:01:22.787Z  2024-04-18T12:01:22.787Z    0          None  2940.33  18-Apr-2024  
3   66225cff337be0542c009b64  RELIANCE        EQ              N   2024-04-19  2024-04-18T18:30:00.000Z              2948.00             2886.05           2913.55           2940.25               2943.05                2928.65            7870889       2.300439e+10                3024.9               2220.3           257506  INE002A01018  2024-04-19T12:01:03.874Z  2024-04-19T12:01:03.874Z    0          None  2922.72  19-Apr-2024  
```
""",

        rules=prompts.coding_prompt, code_string=code_2,llm_hard=llm_hard, llm_easy=llm_easy,
        session=PersistentPythonEnvironment(), retry=3)
    print(f"Success: {success}, \nFailure Reason: {failure_reason}, \nSTDOUT: {stdout}, \nSTDERR: {stderr}")