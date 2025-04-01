import random
from typing import Union, List
import uuid
from prompts import tts_friendly_format_instructions

import os
import tempfile
import shutil
import concurrent.futures
import logging
from openai import OpenAI
from pydub import AudioSegment  # For merging audio files


# Local imports  
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from prompts import tts_friendly_format_instructions
    from base import CallLLm, CallMultipleLLM, simple_web_search_with_llm
    from common import (
        CHEAP_LLM, USE_OPENAI_API, convert_markdown_to_pdf,
        get_async_future, sleep_and_get_future_result, convert_stream_to_iterable
    )
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

import logging
import re
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)
import time
agents = []
adl = []
adllib = []
agent_language_parser = []


class Agent:
    def __init__(self, keys):
        self.keys = keys

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        pass


class AgentWorkflow(Agent):
    def __init__(self, agents):
        self.agents = agents
        self.workflows = dict()

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        pass

    @classmethod
    def create_workflow(cls, agents):
        pass

    @classmethod
    def get_workflow(cls, workflow_name):
        pass

    def stop(self):
        pass

    def done(self):
        pass

    def status(self):
        pass

    def exception(self):
        pass

    def result(self, timeout=10):
        pass

    def __str__(self):
        return f"AgentWorkflow(agents={self.agents})"

    def __repr__(self):
        return self.__str__()
    
    
    
    

