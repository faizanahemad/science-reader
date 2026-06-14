import inspect
from typing import get_type_hints
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, FunctionMessage
from langgraph.graph import END, MessageGraph

from agents_common import generate_exhaustive_doc, get_prompt_from_langchain_hub
from langchain_core.tools import tool

# Optional: add tracing to visualize the agent trajectories


from typing import List, Optional, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from playwright.async_api import Page

import asyncio
import platform

import asyncio
import base64

from langchain_core.runnables import chain

from langchain import hub
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough


from base import CallLLm


