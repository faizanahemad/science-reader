import time
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

import threading
import signal
import os
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import pickle
import tempfile
import subprocess
import signal
import os


import random

import concurrent.futures
from typing import List, Union

import pandas as pd
import tiktoken
from copy import deepcopy, copy
import requests
import re
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
import urllib3
import multiprocessing

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

    def run_code(self, code_string, time_limit):
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
                # logger.info(f"Code that we ran is: \n{code_string}\n, success = {output.success}, \nstdout is: \n{stdout}\n, stderr is: \n{stderr}")
                # logger.info("Code executed successfully.")
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


class PersistentPythonEnvironmentWithForceKill_old:
    def __init__(self):
        self.shell = InteractiveShell.instance()
        self.thread_local_io = ThreadLocalStringIO()
        self.execution_thread = None
        self.current_process_id = None
        from IPython import get_ipython
        ipython = get_ipython()
        ipython.run_line_magic('config', 'TerminalInteractiveShell.color_info = False')
        ipython.run_line_magic('config', 'TerminalInteractiveShell.highlight_matching_brackets = False')

    def run_code(self, code_string, time_limit):
        """
        Execute the code and capture the output with force termination capability.
        """
        self.thread_local_io = ThreadLocalStringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = self.thread_local_io.stdout_buffer
        sys.stderr = self.thread_local_io.stderr_buffer
        stdout = stderr = ""
        
        # Store the main process ID
        self.current_process_id = os.getpid()
        
        try:
            with ThreadPoolExecutor() as executor:
                # Start the execution in a separate thread
                future = executor.submit(self._execute_with_monitoring, code_string)
                
                try:
                    output = future.result(timeout=time_limit)
                    stdout = self.thread_local_io.stdout_buffer.getvalue()
                    stderr = self.thread_local_io.stderr_buffer.getvalue()
                    stdout = strip_formatting(stdout)
                    stderr = strip_formatting(stderr)
                    
                    if output.success:
                        return True, None, stdout, stderr
                    else:
                        if output.error_before_exec:
                            failure_reason = f"Error before execution: {output.error_before_exec}"
                            return False, failure_reason, stdout, stderr
                        exception = output.error_in_exec
                        if isinstance(exception, UsageError):
                            exception_trace = exception.etype.__name__ + ": " + str(exception.evalue)
                        else:
                            exception_trace = str(exception)
                        sys.stdout = original_stdout
                        sys.stderr = original_stderr
                        return False, exception_trace, stdout, stderr
                        
                except concurrent.futures.TimeoutError:
                    logger.info("The script exceeded the time limit. Force terminating...")
                    stdout = self.thread_local_io.stdout_buffer.getvalue()
                    stderr = self.thread_local_io.stderr_buffer.getvalue()
                    
                    # Force kill any child processes created by the execution
                    self._force_kill_execution_processes()
                    
                    # Cancel the future
                    future.cancel()
                    
                    
                    stdout = strip_formatting(stdout)
                    stderr = strip_formatting(stderr)
                    
                    logger.info("Process forcefully terminated due to timeout.")
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
                    return False, f"Code execution forcefully terminated after {time_limit} seconds", stdout, stderr
                    
        except Exception as e:
            logger.info(f"Unexpected error occurred: {e}")
            return False, str(e), stdout, stderr
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def _execute_with_monitoring(self, code_string):
        """Execute code while monitoring for child processes."""
        # Record child processes before execution
        try:
            parent = psutil.Process(self.current_process_id)
            initial_children = set(child.pid for child in parent.children(recursive=True))
        except psutil.NoSuchProcess:
            initial_children = set()
        
        # Execute the code
        result = self.shell.run_cell(code_string)
        
        return result
    
    def _force_kill_execution_processes(self):
        """Force kill any processes created during code execution."""
        try:
            parent = psutil.Process(self.current_process_id)
            current_children = parent.children(recursive=True)
            
            for child in current_children:
                try:
                    logger.info(f"Terminating child process: {child.pid}")
                    child.terminate()
                    # Wait a bit for graceful termination
                    child.wait(timeout=2)
                except psutil.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    logger.info(f"Force killing child process: {child.pid}")
                    child.kill()
                except psutil.NoSuchProcess:
                    # Process already terminated
                    pass
                except Exception as e:
                    logger.error(f"Error terminating child process {child.pid}: {e}")
                    
        except psutil.NoSuchProcess:
            logger.warning("Parent process not found for cleanup")
        except Exception as e:
            logger.error(f"Error during process cleanup: {e}")





class PythonEnvironmentWithForceKill:
    def __init__(self):
        self.state_file = tempfile.NamedTemporaryFile(mode='wb', delete=False)
        self.state_file.close()
        self.globals_dict = {}
        
    def run_code(self, code_string, time_limit):
        """
        Execute code in a separate process with state persistence and force termination.
        """
        # Create execution script that loads previous state
        memory_limit = 1000
        write_limit = 10
        cpu_time_limit = 60
        execution_script = f'''
import pickle
import sys
import warnings
import traceback
import signal
from io import StringIO
warnings.filterwarnings("ignore")

import pickle
import sys
import warnings
import traceback
import signal
import resource
from io import StringIO
warnings.filterwarnings("ignore")

# Set resource limits first
def set_resource_limits():
    try:
        # Memory limit
        memory_bytes = {memory_limit} * 1024 * 1024
        current_mem_limits = resource.getrlimit(resource.RLIMIT_AS)
        new_mem_limit = min(memory_bytes, current_mem_limits[1] if current_mem_limits[1] != -1 else memory_bytes)
        resource.setrlimit(resource.RLIMIT_AS, (new_mem_limit, current_mem_limits[1]))
        
        # CPU time limit  
        current_cpu_limits = resource.getrlimit(resource.RLIMIT_CPU)
        new_cpu_limit = min({cpu_time_limit}, current_cpu_limits[1] if current_cpu_limits[1] != -1 else {cpu_time_limit})
        resource.setrlimit(resource.RLIMIT_CPU, (new_cpu_limit, current_cpu_limits[1]))
        
        # File size limit
        write_bytes = {write_limit} * 1024 * 1024
        current_write_limits = resource.getrlimit(resource.RLIMIT_FSIZE)
        new_write_limit = min(write_bytes, current_write_limits[1] if current_write_limits[1] != -1 else write_bytes)
        resource.setrlimit(resource.RLIMIT_FSIZE, (new_write_limit, current_write_limits[1]))
        
    except (OSError, ValueError) as e:
        # Log but don't fail if resource limits can't be set
        print(f"Warning: Could not set resource limits: {{e}}", file=sys.stderr)

# Apply resource limits
set_resource_limits()


# Capture stdout
old_stdout = sys.stdout
old_stderr = sys.stderr
stdout_buffer = StringIO()
stderr_buffer = StringIO()
sys.stdout = stdout_buffer
sys.stderr = stderr_buffer

execution_success = True
error_message = ""

def handle_timeout_signal(signum, frame):
    """Handle timeout signal by generating stack trace"""
    import traceback
    global execution_success, error_message
    execution_success = False
    error_message = f"Execution timed out\\n" + "".join(traceback.format_stack(frame))
    
    # Print partial results immediately
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    sys.exit(1)

# Set up signal handler for graceful termination
signal.signal(signal.SIGTERM, handle_timeout_signal)

# Custom print function that flushes output
original_print = print
def flushing_print(*args, **kwargs):
    result = original_print(*args, **kwargs)
    sys.stdout.flush()
    return result

# Override print in the execution environment
globals()['print'] = flushing_print

try:
    # Execute user code
{self._indent_code(code_string)}

        
except Exception as e:
    execution_success = False
    error_message = str(e) + "\\n" + traceback.format_exc()
    
    
finally:
    # Restore stdout/stderr
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    
    # Print results in a structured way
    print("===EXECUTION_RESULT===", flush=True)
    print(f"SUCCESS: {{execution_success}}", flush=True)
    print(f"ERROR: {{error_message}}", flush=True)
    print("===STDOUT_START===", flush=True)
    print(stdout_buffer.getvalue(), flush=True)
    print("===STDOUT_END===", flush=True)
    print("===STDERR_START===", flush=True)
    print(stderr_buffer.getvalue(), flush=True)
    print("===STDERR_END===", flush=True)
'''

        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as tmp_file:
            tmp_file.write(execution_script)
            tmp_file_path = tmp_file.name

        try:
            # Start process
            proc = subprocess.Popen(
                [sys.executable, tmp_file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            try:
                # Wait for completion with timeout
                stdout, stderr = proc.communicate(timeout=time_limit)
                success = proc.returncode == 0
                
                # Parse structured output
                if success:
                    result = self._parse_execution_result(stdout)
                    return result['success'], result['error'], result['stdout'], result['stderr']
                else:
                    return False, f"Process failed with return code {proc.returncode}", stdout, stderr
                    
            except subprocess.TimeoutExpired:
                # Try graceful termination first
                logger.info("Timeout reached, attempting graceful termination...")
                proc.terminate()  # Send SIGTERM instead of SIGKILL
                
                # Wait a bit for graceful termination and partial output
                try:
                    stdout, stderr = proc.communicate(timeout=2)
                    success = False
                    
                    # Try to parse structured output first
                    try:
                        result = self._parse_execution_result(stdout)
                        partial_stdout = result['stdout']
                        partial_stderr = result['stderr']
                        error_msg = result['error'] if result['error'] else f"Execution terminated after {time_limit} seconds"
                    except:
                        # Fallback to raw output if parsing fails
                        partial_stdout = stdout
                        partial_stderr = stderr
                        error_msg = f"Execution terminated after {time_limit} seconds"
                        
                    return False, error_msg, partial_stdout, partial_stderr
                    
                except subprocess.TimeoutExpired:
                    # Force kill if graceful termination fails
                    logger.info("Graceful termination failed, force killing...")
                    self._force_kill_process_tree(proc.pid)
                    
                    # Get whatever output we can
                    try:
                        stdout, stderr = proc.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        stdout, stderr = "", ""
                    
                    # Return raw output since structured parsing likely failed
                    return False, f"Execution forcefully terminated after {time_limit} seconds", stdout, stderr
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_file_path)
            except:
                pass
    
    def _indent_code(self, code_string):
        """Indent code for inclusion in the script."""
        return '\n'.join('    ' + line for line in code_string.split('\n'))
    
    def _parse_execution_result(self, output):
        """Parse structured output from the execution script."""
        lines = output.split('\n')
        result = {'success': False, 'error': '', 'stdout': '', 'stderr': ''}
        
        current_section = None
        for line in lines:
            if line == "===EXECUTION_RESULT===":
                current_section = 'result'
            elif line.startswith("SUCCESS: "):
                result['success'] = line.split("SUCCESS: ")[1].strip() == 'True'
            elif line.startswith("ERROR: "):
                result['error'] = line.split("ERROR: ", 1)[1] if len(line.split("ERROR: ", 1)) > 1 else ''
            elif line == "===STDOUT_START===":
                current_section = 'stdout'
            elif line == "===STDOUT_END===":
                current_section = None
            elif line == "===STDERR_START===":
                current_section = 'stderr'
            elif line == "===STDERR_END===":
                current_section = None
            elif current_section == 'stdout':
                result['stdout'] += line + '\n'
            elif current_section == 'stderr':
                result['stderr'] += line + '\n'
        
        # Clean up trailing newlines
        result['stdout'] = result['stdout'].rstrip('\n')
        result['stderr'] = result['stderr'].rstrip('\n')
        
        return result
    
    def _force_kill_process_tree(self, pid):
        """Force kill a process and all its children."""
        try:
            import psutil
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # Kill children first
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            
            # Kill parent
            parent.kill()
            
            # Wait for processes to die
            gone, still_alive = psutil.wait_procs(children + [parent], timeout=3)
            
            # Force kill any remaining processes
            for p in still_alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                    
        except ImportError:
            # Fallback to os.kill if psutil is not available
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


from persistent_code_env import PersistentPythonEnvironment as PersistentPythonEnvironment_v2



def code_runner_with_retry(instructions: str, rules: List[str], llm_hard: CallLLm, llm_easy: CallLLm, code_string: str = "",
                           session: Union[PersistentPythonEnvironment, PersistentPythonEnvironment_v2]=None, retry=3, stdout_limit=50):
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
    for i in range(retry + 1):
        success, failure_reason, stdout, stderr = run_code_with_constraints_v2(code_string, session=session)
        # logger.info(f"[code_runner_with_retry] Code execution attempt {i+1} with success: {success}, failure_reason: {failure_reason}, stdout: {stdout}, stderr: {stderr}")
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
            if len(stdout.split("\n")) > stdout_limit:
                stdout = extract_relevant_from_stdout(instructions, llm_easy, code_string, stdout)
            return success, failure_reason, stdout, stderr, code_string
        elif i < retry:
            code_string = write_code_with_llm(instructions, rules, llm_hard, previous_code=code_string, previous_stdout=stdout, previous_failure=failure_reason)
    return success, failure_reason, stdout, stderr, code_string


def run_code_once(code_string: str, session: Union[PersistentPythonEnvironment, PersistentPythonEnvironment_v2]=None):
    success, failure_reason, stdout, stderr = run_code_with_constraints_v2(code_string, session=PythonEnvironmentWithForceKill() if session is None else session, timeout=5, pad_code_string=False)
    final_output = format_execution_output_for_ui(success, failure_reason, stdout, stderr)
    return final_output


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
        new_stdout = (previous_stdout if previous_stdout else "") + (("\n" + stdout.strip()) if stdout else "")
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

        # if code_to_execute is empty, then we need to extract the code from the code_string using regex.
        if code_to_execute.strip() == "":
            regex = r"```.*?(.*?)```"
            code_to_execute = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
            code_to_execute = [c.strip() for c in code_to_execute]
            code_to_execute = "\n".join(code_to_execute)

        if "# execute_code" in code_to_execute.lower() or relax:
            code_string = code_to_execute
        else:
            code_string = ""

    return code_string




def extract_drawio(code_string):
    regex = r"```<pre class=\"drawio\">(.*?)</pre>```"
    drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    drawio = [c.strip() for c in drawio]
    drawio = "\n".join(drawio)
    if drawio.strip() != "" and "<mxfile>" in drawio.lower() or "<mxfile " in drawio.lower():
        return drawio
    else:
        regex = r"```xml(.*?)```"
        drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        drawio = [c.strip() for c in drawio]
        drawio = "\n".join(drawio)
        if drawio.strip() != "" and "<mxfile>" in drawio.lower() or "<mxfile " in drawio.lower():
            return drawio
        else:
            regex = r"```(.*?)```"
            drawio = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
            drawio = [c.strip() for c in drawio]
            drawio = "\n".join(drawio)
            # separate lines and if any line just has xml as text and nothing else then discard that line then join them again.
            drawio = "\n".join([line for line in drawio.split("\n") if line.strip().lower() != "xml"])
            if drawio.strip() != "" and "<mxfile>" in drawio.lower() or "<mxfile " in drawio.lower():
                return drawio
    return ''


mermaid_diagram_wrapping_str = '<pre class="mermaid">\n{cleaned_content}\n</pre>'
def extract_mermaid(code_string):
    """
    Extract Mermaid diagrams from markdown code blocks and wrap in HTML pre tags.
    
    Args:
        code_string (str): String that may contain ```mermaid code blocks
        
    Returns:
        str: Extracted Mermaid diagrams, each wrapped in <pre class="mermaid"> tags
        
    Purpose:
        Extracts Mermaid diagrams from markdown-style code blocks and formats them
        as HTML pre elements for consistent rendering with other Mermaid sources.
    """
    regex = r"```mermaid(.*?)```"
    mermaid_matches = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    # Process and wrap each match in pre tags
    mermaid_blocks = []
    for match in mermaid_matches:
        # Strip whitespace from content
        cleaned_content = match.strip()
        if cleaned_content:
            # Check if it contains valid Mermaid content (expanded detection)
            if ("graph" in cleaned_content.lower() or 
                "flowchart" in cleaned_content.lower() or
                "sequencediagram" in cleaned_content.lower() or
                "gitgraph" in cleaned_content.lower() or
                "classDiagram" in cleaned_content.lower() or
                "stateDiagram" in cleaned_content.lower() or
                "pie" in cleaned_content.lower() or
                "journey" in cleaned_content.lower() or
                "erDiagram" in cleaned_content.lower()):
                
                # Wrap each diagram in its own pre tags
                wrapped_diagram = mermaid_diagram_wrapping_str.format(cleaned_content=cleaned_content)
                mermaid_blocks.append(wrapped_diagram)
    
    # Join all mermaid blocks with double newlines for separation
    return "\n\n".join(mermaid_blocks)


def extract_last_mermaid(code_string):
    """
    Extract the last mermaid diagram from the code string.
    
    Args:
        code_string (str): String that may contain ```mermaid code blocks or <pre class="mermaid"> tags
        
    Returns:
        str: Extracted Mermaid diagram content (without wrapper tags)
        
    Purpose:
        Extracts the most recent/last Mermaid diagram from a string that may contain
        multiple diagrams in either markdown code blocks or HTML pre tags. This is
        useful for getting the latest diagram when content is being streamed or updated.
    """
    # First try to extract from markdown code blocks
    markdown_regex = r"```mermaid(.*?)```"
    markdown_matches = re.findall(markdown_regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    # Then try to extract from HTML pre tags
    pre_tag_regex = r'<pre\s+class=["\']\s*mermaid\s*["\']\s*>(.*?)</pre>'
    pre_tag_matches = re.findall(pre_tag_regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    # Combine all matches and get positions to find the last one
    all_matches = []
    
    # Find positions of markdown matches
    for match in re.finditer(markdown_regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE):
        all_matches.append((match.start(), match.group(1).strip()))
    
    # Find positions of pre tag matches
    for match in re.finditer(pre_tag_regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE):
        all_matches.append((match.start(), match.group(1).strip()))
    
    # Sort by position and get the last match
    if all_matches:
        all_matches.sort(key=lambda x: x[0])
        last_match_content = all_matches[-1][1]
        
        # Validate that it contains Mermaid content
        if (last_match_content and 
            ("graph" in last_match_content.lower() or 
             "flowchart" in last_match_content.lower() or
             "sequencediagram" in last_match_content.lower() or
             "gitgraph" in last_match_content.lower() or
             "classDiagram" in last_match_content.lower() or
             "stateDiagram" in last_match_content.lower() or
             "pie" in last_match_content.lower() or
             "journey" in last_match_content.lower() or
             "erDiagram" in last_match_content.lower())):
            
            return mermaid_diagram_wrapping_str.format(cleaned_content=last_match_content)
    
    return ""

def extract_mermaid_from_pre_tags(html_string):
    """
    Extract Mermaid diagram content from HTML <pre class="mermaid"> tags.
    
    Args:
        html_string (str): HTML string that may contain <pre class="mermaid"> tags
        
    Returns:
        str: Extracted Mermaid diagrams, each wrapped in <pre class="mermaid"> tags
        
    Purpose:
        This function complements extract_mermaid() by handling Mermaid diagrams
        embedded in HTML pre tags instead of markdown code blocks. It preserves
        the HTML structure by keeping each diagram wrapped in pre tags.
    """
    # Regex to match complete <pre class="mermaid"> tags and their content
    # Handles both single and double quotes, flexible whitespace
    regex = r'<pre\s+class=["\']\s*mermaid\s*["\']\s*>(.*?)</pre>'
    
    mermaid_matches = re.findall(regex, html_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    # Process and wrap each match in pre tags
    mermaid_blocks = []
    for match in mermaid_matches:
        # Strip whitespace from content
        cleaned_content = match.strip()
        if cleaned_content:
            # Check if it contains valid Mermaid content
            if ("graph" in cleaned_content.lower() or 
                "flowchart" in cleaned_content.lower() or
                "sequencediagram" in cleaned_content.lower() or
                "gitgraph" in cleaned_content.lower() or
                "classDiagram" in cleaned_content.lower() or
                "stateDiagram" in cleaned_content.lower() or
                "pie" in cleaned_content.lower() or
                "journey" in cleaned_content.lower() or
                "erDiagram" in cleaned_content.lower()):
                
                # Wrap each diagram in its own pre tags
                wrapped_diagram = mermaid_diagram_wrapping_str.format(cleaned_content=cleaned_content)
                mermaid_blocks.append(wrapped_diagram)
    
    # Join all mermaid blocks with double newlines for separation
    return "\n\n".join(mermaid_blocks)


def extract_all_mermaid(content_string):
    """
    Extract Mermaid diagrams from both markdown code blocks and HTML pre tags.
    
    Args:
        content_string (str): Content that may contain Mermaid in various formats
        
    Returns:
        str: Combined Mermaid diagram content, pre-tag diagrams wrapped in HTML,
             markdown diagrams as raw content
        
    Purpose:
        Unified function to extract Mermaid content regardless of format,
        preserving appropriate formatting for each source type.
    """
    # Extract from markdown code blocks (returns raw content)
    mermaid_from_code = extract_mermaid(content_string)
    
    # Extract from HTML pre tags (returns wrapped in pre tags)
    mermaid_from_pre = extract_mermaid_from_pre_tags(content_string)
    
    # Combine results
    all_mermaid = []
    if mermaid_from_code.strip():
        all_mermaid.append(mermaid_from_code.strip())
    if mermaid_from_pre.strip():
        all_mermaid.append(mermaid_from_pre.strip())
    
    return "\n\n".join(all_mermaid)


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

    def __call__(self, *args, **kwargs):
        prnt(*args, file=self.stdout_buffer, **kwargs)

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
def run_code_with_constraints_v2_old(code_string, constraints={}, session: PersistentPythonEnvironment=None):
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
        session = PersistentPythonEnvironment_v2()
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
        success, failure_reason, stdout, stderr = session.run_code(code_string, time)
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
            # logger.info(f"Code that we ran is: \n{code_string}\n, success = {success}, \nstdout is: \n{stdout}\n, stderr is: \n{stderr}")
            logger.info("Code executed successfully.")
        failure_reason = f"{failure_reason}\n{stderr}".strip()

    except Exception as e:
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False
    finally:
        pass

    if failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None":
        failure_reason = f"Raised Exception Message and stack trace:\n{failure_reason}\n"
    if stderr:
        stderr = stderr.strip()

    return success, failure_reason, stdout, stderr

def run_code_with_constraints_v2(code_string, constraints={}, session: Union[PersistentPythonEnvironment, PersistentPythonEnvironment_v2, PythonEnvironmentWithForceKill]=None, 
                                 timeout=120, pad_code_string=True):
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
        session = PersistentPythonEnvironment_v2()
    memory = constraints.get("memory", 1500)
    time = constraints.get("time", timeout)
    if pad_code_string:
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
        success, failure_reason, stdout, stderr = session.run_code(code_string, time)
        if stdout:
            stdout = stdout.strip()
            split_string = "-x-=" * 40
            if split_string in stdout:
                stdout = stdout.split(split_string)[1]
                if stdout:
                    stdout = stdout.strip()
        
        # Add error handling around logging statements
        try:
            if not success or stderr.strip() != "":
                # Limit log size to prevent "file too large" errors
                log_stderr = stderr[:1000] + "..." if len(stderr) > 1000 else stderr
                logger.info(f"Code execution failed with error as below:\n{log_stderr}")
            else:
                logger.info("Code executed successfully.")
        except Exception as log_error:
            # Silently handle logging errors to prevent function from failing
            pass
        stderr = "" if stderr is None else stderr
        failure_reason = "" if failure_reason is None else failure_reason
        failure_reason = f"{failure_reason}\n{stderr}".strip()

    except Exception as e:
        failure_reason = str(e) + "\n" + traceback.format_exc()
        success = False
        # Add error handling for logging here too
        try:
            logger.info(f"Exception in code execution: {str(e)[:1000]}")
        except Exception:
            pass
    finally:
        pass

    if failure_reason is not None and failure_reason.strip() != "" and failure_reason.strip()!="None":
        failure_reason = f"Raised Exception Message and stack trace:\n{failure_reason}\n"
    if stderr:
        stderr = stderr.strip()

    return success, failure_reason, stdout, stderr


def format_execution_output_for_ui(success, failure_reason, stdout, stderr, code_string=None):
    """
    Formats code execution output in a pretty markdown format for UI display.
    
    Parameters:
    - success (bool): Whether the code executed successfully
    - failure_reason (str): Error details if execution failed
    - stdout (str): Standard output from code execution
    - stderr (str): Standard error from code execution
    - code_string (str, optional): The original code that was executed
    
    Returns:
    - str: Formatted markdown string for UI display
    """
    
    # Initialize the markdown output
    markdown_output = []
    
    # Add execution status header
    if success:
        markdown_output.append("## ✅ Code Execution Successful")
    else:
        markdown_output.append("## ❌ Code Execution Failed")
    
    markdown_output.append("")  # Empty line for spacing
    
    # Add original code if provided
    if code_string and code_string.strip():
        markdown_output.append("### 📝 Executed Code")
        markdown_output.append("```python")
        markdown_output.append(code_string.strip())
        markdown_output.append("```")
        markdown_output.append("")
    
    # Add stdout if present
    if stdout and stdout.strip():
        markdown_output.append("### 📤 Output")
        markdown_output.append("```")
        markdown_output.append(stdout.strip())
        markdown_output.append("```")
        markdown_output.append("")
    
    # Add stderr if present and different from failure_reason
    if stderr and stderr.strip() and stderr.strip() != failure_reason.strip():
        markdown_output.append("### ⚠️ Warnings/Errors")
        markdown_output.append("```")
        markdown_output.append(stderr.strip())
        markdown_output.append("```")
        markdown_output.append("")
    
    # Add failure reason if execution failed
    if not success and failure_reason and failure_reason.strip():
        markdown_output.append("### 🐛 Error Details")
        markdown_output.append("```")
        markdown_output.append(failure_reason.strip())
        markdown_output.append("```")
        markdown_output.append("")
    
    # Add summary section
    if success:
        if stdout and stdout.strip():
            markdown_output.append("### 📊 Summary")
            markdown_output.append("✅ **Status**: Execution completed successfully")
            markdown_output.append(f"📏 **Output Length**: {len(stdout)} characters")
        else:
            markdown_output.append("### 📊 Summary")
            markdown_output.append("✅ **Status**: Execution completed successfully (no output)")
    else:
        markdown_output.append("### 📊 Summary")
        markdown_output.append("❌ **Status**: Execution failed")
        if failure_reason:
            # Try to extract the main error type
            error_lines = failure_reason.split('\n')
            main_error = next((line for line in error_lines if 'Error:' in line or 'Exception:' in line), "Unknown error")
            markdown_output.append(f"🔍 **Error Type**: {main_error}")
    
    # Join all parts with newlines
    return "\n".join(markdown_output)



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
import pandas as pd  
import numpy as np  
from stocks_lib.equity_data_fetcher import get_equity_history  
  
# Fetching the last 2 months of Reliance stock data  
history_df = get_equity_history('RELIANCE', "2 months")  
  
# Calculating the standard deviation of closing prices  
std_deviation = history_df['CH_CLOSING_PRICE'].std()  
print("Standard Deviation of Closing Prices: ", std_deviation)  

# Placeholder for market returns  
market_returns = pd.Series([...])  # This should be the actual market returns  
  
# Calculating covariance between Reliance returns and market returns  
covariance = np.cov(history_df['daily_returns'].dropna(), market_returns.dropna())[0][1]  
  
# Calculating variance of the market returns  
variance = market_returns.var()  
  
# Calculating beta  
beta = covariance / variance  
print("Beta of Reliance: ", beta)  


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