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
from .tts_and_podcast_agent import TTSAgent, StreamingPodcastAgent, PodcastAgent
from .search_and_information_agents import (
    WebSearchWithAgent,
    LiteratureReviewAgent,
    BroadSearchAgent,
    ReflectionAgent,
    NResponseAgent,
    WhatIfAgent,
    PerplexitySearchAgent, JinaSearchAgent
)


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
from .base_agent import Agent
from prompts import tts_friendly_format_instructions

# All agents as workflows


# at depth 4 use ToCGenerationAgent to generate a table of contents

# Take conversation history and summary into account


