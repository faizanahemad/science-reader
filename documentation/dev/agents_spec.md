## Cost effective agents
- Path Discovery and then action copying with playwright.
- Semantic Search in agent solutions database and execute actions there.
- Use a stronger planner or question breakdown agent to make easier tasks.
- Use Reflexion or a simple self critic or Are we Done LLM step with cheaper LLMs.
- Use stronger question or plan generation agents to make easier tasks.
- Use Bi-encoder models or LLM models with paragraph annotations to reduce number of paragraphs read from a document using a cheaper LLM and then pass the filtered paragraphs to a stronger LLM.

## Agents
- Supervisor Agents
- Task Breakdown agents (Break main task to a smaller component and follow that.)
- Create more questions and granular asks for this task Agent.
- Verify and Feedback Agents
- Agents can ask for user clarification as well.
- Infinite Length output
- Multi level agents - Agents calling other specialized agents.
- Reusable agents and agent plans based on what worked (Auto Agents).
  - Agent task description and agent policy stored if upvoted message.
  - Curate based on AI feedback or LLM feedback as well.
  - Math Problem Solver agent
- Agentic Search

## Graph
- Graph
- DAG
- Clarification nodes
- Any node as an output node.
- Graph nodes with each node's input nodes and output nodes specified.
- Final output node copies from the remaining nodes.
- Nodes can be simple functions or agents. They should be able to download files, run code, browse net etc.
- Graphs can be saved and reused.
- Output of each node should be possible to save and view separately.
- A node should be able to ask user for clarification and wait till user provides it. Our overall graph should support us to query it for clarification asking nodes.
- Are you satisfied with this information? Node
- COLLECT_INFORMATION to file
- USE_COLLECTED_INFORMATION - from file

## Management (could all be simple json text based.)
- View graph structure.
- View which nodes are done for a graph.
- View output of a node.
- View and provide clarification asks for a node.


## Functions
- Finance functions


## Frameworks (https://github.com/Jenqyang/Awesome-AI-Agents?tab=readme-ov-file#frameworks)
- https://github.com/microsoft/autogen
- https://python.langchain.com/v0.2/docs/langgraph/#define-the-agent-state
- https://github.com/langroid/langroid
- https://docs.crewai.com/
- https://github.com/TransformerOptimus/SuperAGI?tab=readme-ov-file#-architecture

## Libraries
- https://github.com/McGill-NLP/webllama

## Financial
- https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly
- https://pypi.org/project/yfinance/