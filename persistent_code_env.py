import multiprocessing
import dill
from multiprocessing.managers import BaseManager
from IPython.core.interactiveshell import InteractiveShell
import sys
from io import StringIO
import concurrent.futures
import re
import os
import concurrent.futures
from typing import List, Union
import traceback
import subprocess
import tempfile
import warnings
warnings.filterwarnings("ignore")
import sys
import threading
from io import StringIO
import time
from threading import Thread


# Define a custom pickler using dill
class CustomDillPickler(dill.Pickler):
    def __init__(self, file, protocol=dill.HIGHEST_PROTOCOL):
        super().__init__(file, protocol=protocol)


def custom_dill_reducer(obj):
    from io import BytesIO
    bio = BytesIO()
    pickler = CustomDillPickler(bio)
    pickler.dump(obj)
    data = bio.getvalue()
    return dill.loads, (data,)


# Apply the custom reducer to all picklable types
for t in [multiprocessing.Process, multiprocessing.Queue, InteractiveShell]:
    multiprocessing.reduction.register(t, custom_dill_reducer)

# Register the custom reducer for the multiprocessing context
context = multiprocessing.get_context()
context.reducer.register(type(multiprocessing.Queue()), custom_dill_reducer)


class QueueManager(BaseManager):
    pass


QueueManager.register('get_queue', multiprocessing.Queue)
context.reducer.register(type(QueueManager()), custom_dill_reducer)

class PersistentPythonEnvironment:
    def __init__(self):
        self.manager = QueueManager()
        context.reducer.register(type(self.manager), custom_dill_reducer)
        self.manager.start()
        queue = self.manager.get_queue()
        context.reducer.register(type(queue), custom_dill_reducer)
        self.queue = queue
        self.queue = self.manager.get_queue()
        # self.process = multiprocessing.Process(target=self.run_ipython_shell)
        self.process = Thread(target=self.run_ipython_shell)
        self.process.start()

    def run_ipython_shell(self):
        shell = InteractiveShell.instance()
        while True:
            # check if queue is empty
            if self.queue.empty():
                time.sleep(1)
                continue
            task = self.queue.get()
            if task is None:
                break
            code, result_queue, time_limit = task
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(shell.run_cell, code)
                    output = future.result(timeout=time_limit)
                stdout = sys.stdout.getvalue()
                stderr = sys.stderr.getvalue()
                stdout = self.strip_formatting(stdout)
                stderr = self.strip_formatting(stderr)
                if output.success:
                    result_queue.put((True, None, stdout, stderr))
                else:
                    error_message = output.error_in_exec if output.error_in_exec else "Unknown error"
                    result_queue.put((False, str(error_message), stdout, stderr))
            except concurrent.futures.TimeoutError:
                result_queue.put((False, "Code execution timed out", '', ''))
            except Exception as e:
                result_queue.put((False, str(e), '', ''))
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
            time.sleep(1)

    def run_code(self, code_string, time_limit=10):
        result_queue = self.manager.get_queue()
        self.queue.put((code_string, result_queue, time_limit))
        return result_queue.get()

    def close(self):
        self.queue.put(None)
        self.process.join()

    def strip_formatting(self, text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        text = text.replace('\r', '').replace('\b', '').replace('\a', '')
        return text

    # Example usage



