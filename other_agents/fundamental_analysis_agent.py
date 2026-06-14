from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, FunctionMessage
from langgraph.graph import END, MessageGraph
from langchain import hub
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.tools import tool
from langchain_experimental.tools import PythonREPLTool
from langchain_core.runnables import (
    RunnableLambda,
    RunnableParallel,
    RunnablePassthrough,
)

import inspect
from typing import get_type_hints
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, FunctionMessage
from langgraph.graph import END, MessageGraph

from agents_common import generate_exhaustive_doc, get_prompt_from_langchain_hub

# Optional: add tracing to visualize the agent trajectories
import os
from getpass import getpass

# Gather results in markdown format
# Coding agents
# Path: agents/fundamental_analysis_agent.py