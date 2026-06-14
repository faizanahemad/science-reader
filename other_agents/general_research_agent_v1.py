# Write to markdown file.
# Search and Scatter Gather
# Comprehensive
# Create multiple dimensions, domains and questions.
# Ask further questions.
# Create new questions and use google search mostly.
# Use critic and create further questions from critic.


import inspect
import os
import random
from typing import get_type_hints
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, FunctionMessage
from langgraph.graph import END, MessageGraph
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate, \
    MessagesPlaceholder

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
from langchain_openai import ChatOpenAI

from base import CallLLm, PDFReaderTool


def date_string():
    import datetime
    import calendar
    date = datetime.datetime.now().strftime("%d %B %Y")
    year = datetime.datetime.now().strftime("%Y")
    month = datetime.datetime.now().strftime("%B")
    day = datetime.datetime.now().strftime("%d")
    weekday = datetime.datetime.now().weekday()
    weekday_name = calendar.day_name[weekday]
    time = datetime.datetime.now().strftime("%H:%M:%S")
    return f"The current date is '{date}', year is {year}, month is {month}, day is {day}. It is a {weekday_name}. The current time is {time}."


class BBox(TypedDict):
    x: float
    y: float
    text: str
    type: str
    ariaLabel: str


class Prediction(TypedDict):
    action: str
    args: Optional[List[str]]


# This represents the state of the agent
# as it proceeds through execution
class AgentState(TypedDict):
    page: Page  # The Playwright web page lets us interact with the web environment
    input: str  # User request

    current_task: str  # The current task the agent is working on
    task_breakdown: List[str] # The steps the agent has taken to complete the task
    completed_tasks: List[str]  # The tasks the agent has completed

    memory: str # A scratchpad for the agent to store information
    action_history: List[str]  # The actions the agent has taken

    img: str  # b64 encoded screenshot
    bboxes: List[BBox]  # The bounding boxes from the browser annotation function
    prediction: Prediction  # The Agent's output
    # A system message (or messages) containing the intermediate steps
    scratchpad: str
    observation: str  # The most recent response from a tool


import asyncio
import platform


async def click(state: AgentState):
    # - Click [Numerical_Label]
    page = state["page"]
    click_args = state["prediction"]["args"]
    if click_args is None or len(click_args) != 1:
        return f"Failed to click bounding box labeled as number {click_args}"
    bbox_id = click_args[0]
    try:
        bbox_id = int(bbox_id)
        bbox = state["bboxes"][bbox_id]
    except:
        return f"Error: no bbox for : {bbox_id}, please go back, or click on something else or try another action."
    x, y = bbox["x"], bbox["y"]
    await page.evaluate('''() => {  
            document.querySelector('a').addEventListener('click', function(event) {  
                event.preventDefault();  
                window.location.href = this.href;  
            });  
    }''')
    res = await page.mouse.click(x, y)
    # Wait for sometime
    await asyncio.sleep(3)
    # TODO: In the paper, they automatically parse any downloaded PDFs
    # We could add something similar here as well and generally
    # improve response format.
    return f"Clicked {bbox_id}"


async def type_text(state: AgentState):
    page = state["page"]
    type_args = state["prediction"]["args"]
    if type_args is None or len(type_args) != 2:
        return (
            f"Failed to type in element from bounding box labeled as number {type_args}"
        )
    bbox_id = type_args[0]
    bbox_id = int(bbox_id)
    bbox = state["bboxes"][bbox_id]
    x, y = bbox["x"], bbox["y"]
    text_content = type_args[1]
    await page.mouse.click(x, y)
    # Check if MacOS
    select_all = "Meta+A" if platform.system() == "Darwin" else "Control+A"
    await page.keyboard.press(select_all)
    await page.keyboard.press("Backspace")
    await page.keyboard.type(text_content)
    await page.keyboard.press("Enter")
    return f"Typed {text_content} and submitted"


async def scroll(state: AgentState):
    page = state["page"]
    scroll_args = state["prediction"]["args"]
    if scroll_args is None or len(scroll_args) != 2:
        return "Failed to scroll due to incorrect arguments."

    target, direction = scroll_args

    if target.upper() == "WINDOW":
        # Not sure the best value for this:
        scroll_amount = 500
        scroll_direction = (
            -scroll_amount if direction.lower() == "up" else scroll_amount
        )
        await page.evaluate(f"window.scrollBy(0, {scroll_direction})")
    else:
        # Scrolling within a specific element
        scroll_amount = 200
        target_id = int(target)
        bbox = state["bboxes"][target_id]
        x, y = bbox["x"], bbox["y"]
        scroll_direction = (
            -scroll_amount if direction.lower() == "up" else scroll_amount
        )
        await page.mouse.move(x, y)
        await page.mouse.wheel(0, scroll_direction)

    return f"Scrolled {direction} in {'window' if target.upper() == 'WINDOW' else 'element'}"

async def task_breakdown(state: AgentState):
    tasks = state["prediction"]["args"]
    if tasks is None or len(tasks) == 0:
        return "Failed to break down task due to incorrect arguments."
    current_task = state['task_breakdown'].pop()
    assert current_task == state['current_task']
    # state['completed_tasks'].append(current_task)
    state['task_breakdown'].append(tasks)
    state['current_task'] = tasks[-1]
    return f"Breaking down task `{current_task}` into sub-tasks: `{tasks}`."


async def task_complete(state: AgentState):
    task_result = state["prediction"]["args"]
    if task_result is None or len(task_result) == 0:
        return "Failed to complete task due to incorrect arguments."
    task_result = "".join(task_result)
    completed_task = state['task_breakdown'].pop()
    state['completed_tasks'].append(completed_task)
    if len(state['task_breakdown']) > 0:
        state['current_task'] = state['task_breakdown'][-1]
    else:
        state['current_task'] = "Lets give a final answer for our overall goal or task using the ANSWER action."
    return f"Completed task: {completed_task}. Task Result: {task_result}"


async def task_create(state: AgentState):
    tasks = state["prediction"]["args"]
    if tasks is None or len(tasks) == 0:
        return "Failed to create task due to incorrect arguments."
    state['task_breakdown'].append(tasks)
    state['current_task'] = tasks[-1]
    return f"Creating new task: {tasks}."


async def wait(state: AgentState):
    sleep_time = 5
    await asyncio.sleep(sleep_time)
    return f"Waited for {sleep_time}s."


async def go_back(state: AgentState):
    page = state["page"]
    await page.go_back()
    await asyncio.sleep(1)
    return f"Navigated back a page to {page.url}."


async def to_google(state: AgentState):
    page = state["page"]
    await page.goto("https://www.google.com/")
    await asyncio.sleep(1)
    return "Navigated to google.com."


# Create a scratchpad file to store information for later use.
import time

scratch_file = f"memory-{time.time()}.txt"
with open(scratch_file, "w") as f:
    f.write("")


async def add_info_to_memory(state: AgentState):
    info = " ".join(state["prediction"]["args"])
    info_len = len(info.split())
    state["memory"] += f"\n{info}"
    return "COLLECT_INFO: " + f"Added information (of {info_len} words) to memory file which can be read later."


async def read_from_memory(state: AgentState):
    info = state["memory"]
    return "USE_COLLECTED_INFO: " + info


async def read_pdf(state: AgentState):
    # This is a placeholder for a more complex function
    pdf_args = state["prediction"]["args"]
    if pdf_args is None or len(pdf_args) != 1:
        return f"Failed to read PDF due to incorrect arguments as {pdf_args}."
    pdf_link = pdf_args[0]
    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    pdf_text = pdfReader(pdf_link)
    pdf_text = " ".join(pdf_text.split()[:10000])
    model_prompt = f"Provide answer to the user query: {state['input']} from the text below. Text: {pdf_text}"
    return "READ_PDF: " + CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True,
                                  model_name="gpt-4o")(model_prompt)


async def get_page_text(state: AgentState):
    page = state["page"]
    text = await page.evaluate("document.body.innerText")
    return text


import asyncio
import base64

from langchain_core.runnables import chain

# Some javascript we will run on each step
# to take a screenshot of the page, select the
# elements to annotate, and add bounding boxes
with open("mark_page.js") as f:
    mark_page_script = f.read()

from web_scraping import remove_bad_tags, soup_html_parser_fast_v3


@chain
async def mark_page(page):
    await page.evaluate(mark_page_script)
    for _ in range(10):
        try:
            bboxes = await page.evaluate("markPage()")
            break
        except:
            # May be loading...
            await asyncio.sleep(3)
    screenshot = await page.screenshot()
    # Ensure the bboxes don't follow us around
    await page.evaluate("unmarkPage()")
    # text = await page.evaluate("document.body.innerText")
    html = await page.content()
    html = remove_bad_tags(html)
    text = soup_html_parser_fast_v3(html)['text']
    return {
        "img": base64.b64encode(screenshot).decode(),
        "bboxes": bboxes,
        "text": text,
    }


from langchain import hub
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

@chain
async def annotate(state):
    marked_page = await mark_page.with_retry().ainvoke(state["page"])
    return {**state, **marked_page}

@chain
async def break_tasks_down_with_llm(state):
    system = f"""Imagine you are an expert at delegating tasks, management, and breaking down complex tasks into smaller sub-tasks. You are managing a team of robots that are browsing the web. 
To help them complete a task, you need to break down the task into smaller sub-tasks if necessary. If a task is very complex or has multiple parts, you should break it down into smaller sub-tasks to make it easier to complete. 
Your goal is to help the robots complete the task as efficiently and accurately as possible and for this you need to decide if we need to break this task down or not. 
If you break the task down to simpler sub-tasks, then also write the sub-tasks that you think will help the robots complete the task. Inside <subtasks> </subtasks> tag write the sub-tasks separated by semi-colon.
{date_string()}

Your reply should strictly follow the below xml style format:
<thoughts> {{Your brief thoughts on whether this tasks need to be broken down or not and why}} </thoughts>
<subtasks> {{List of sub-tasks that you think will help the robots complete the task separated by semi-colon (';')}} </subtasks> 
"""
    model_prompt = f"{system}\n\nBreak down the task: {state['current_task']} into smaller sub-tasks. Your reply in xml style format:"
    result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(
        model_prompt, system=system)
    subtasks = result.split("<subtasks>")[1].split("</subtasks>")[0].strip()
    subtasks = subtasks.split(";")
    current_task = state['current_task']
    assert current_task == state['task_breakdown'][-1]
    _ = state['task_breakdown'].pop()
    # state['completed_tasks'].append(current_task)
    state['task_breakdown'].extend(subtasks)
    state['current_task'] = subtasks[-1]
    return {**state}


def format_descriptions(state):
    labels = []
    for i, bbox in enumerate(state["bboxes"]):
        text = bbox.get("ariaLabel") or ""
        if not text.strip():
            text = bbox["text"]
        el_type = bbox.get("type")
        labels.append(f'{i} (<{el_type}/>): "{text}"')
    bbox_descriptions = "\nValid Bounding Boxes:\n" + "\n".join(labels)
    return {**state, "bbox_descriptions": bbox_descriptions}


def parse(text: str) -> dict:
    action_prefix = "<action>"
    if action_prefix not in text.strip():
        return {"action": "retry", "args": f"Could not parse LLM Output: {text}"}
    # action block is in between <action> and </action> tags
    action_block = text.split(action_prefix)[1].replace("</action>", '').strip()

    action_str = action_block
    # action_str = action_block[len(action_prefix) :]
    split_output = action_str.split(" ", 1)
    if len(split_output) == 1:
        action, action_input = split_output[0], None
    else:
        action, action_input = split_output
    action = action.strip().replace(";", "").replace(":", "")
    if action_input is not None:
        action_input = [
            inp.strip().strip("[]") for inp in action_input.strip().split(";")
        ]
    return {"action": action, "args": action_input}


@chain
def create_input(state):
    system = f"""Imagine you are a robot browsing the web, just like humans. 
Now you need to complete a task. {date_string()}

In each iteration, you will receive an Observation that includes a url and screenshot of a webpage, its url and its page text and your previous actions, and user query or goal and the current task to solve the overall user query. This screenshot will feature Numerical Labels placed in the TOP LEFT corner of each Web Element. 

Carefully analyze the visual information to identify the Numerical Label corresponding to the Web Element that requires interaction, then follow the guidelines and choose one of the following actions:

1. Click a Web Element.

2. Delete existing content in a textbox and then type content.

3. Scroll up or down.

4. Wait 

5. Go back

7. Return to google to start over.

8. Collect information from this page to write in your scratch pad or memory that you can refer later for answering. Write in a very compact, brief format. Collect information when there is too much information to remember.

9. Read Previously collected information if we have collected sufficient information to answer the query.

10. Break down complex or multiple part tasks. If the task is too complex or has multiple parts, or we have been trying to solve it since multiple steps and still not successful, then we should break the task down to sub-tasks and follow that to solve sub-tasks individually.

11. Create a new task on the basis of the overall ask and goal if all the sub-tasks are completed and we still don't have enough information to answer the overall ask and goal.

12. If we can complete the current task fully and have all information to finish current task then we should emit the action TASK_COMPLETE and then the result of the current task.

13. Read the pdf link if the page is a pdf and you think it will help us by reading the link. The pdf link will be read and relevant information will be added to the scratchpad.

14. Respond with the final answer when all tasks are done using action ANSWER and we have all information to complete the overall ask and overall task goal.

Correspondingly, Action should STRICTLY follow the format:

- Click [Numerical_Label] 

- Type [Numerical_Label]; [Content] 

- Scroll [Numerical_Label or WINDOW]; [up or down] 

- Wait 

- GoBack

- Google

- COLLECT_INFO [content or information for scratchpad]

- USE_COLLECTED_INFO

- READ_PDF [link to pdf page]

- TASK_CREATE [task]

- TASK_BREAKDOWN [sub-task 1];[sub-task 2];[sub-task 3]...

- TASK_COMPLETE [content]

- ANSWER [content]

Key Guidelines You MUST follow:

* Action guidelines *

1) Execute only one action per iteration.

2) When clicking or typing, ensure to select the correct bounding box.

3) Numeric labels lie in the top-left corner of their corresponding bounding boxes and are colored the same.

4) Sub tasks when created are written using the TASK_BREAKDOWN action and sub-tasks are separated by semi-colon. Breakdown complex tasks or multiple questions into sub-tasks and simple tasks using the TASK_BREAKDOWN action so that they can be solved easily. If we are stuck at a task, then also break it down.

* Web Browsing Guidelines *

1) Don't interact with useless web elements like Login, Sign-in, donation that appear in Webpages

2) Select strategically to minimize time wasted and complete the overall goal in least number of steps.

3) If you can't find the required information, you can go back to the previous page or you can go back to google search and search again.

4) Don't repeat the same action too many times especially if it seems the action is not helping.

5) Don't stay on same page for too long if it is not helping us solve the current task or goal.


Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<reflection> {{Are we stuck on same page or just going back and forth on same set of pages, are we making any progress and have we collected any useful information? Are we stuck in a cycle of same pages and actions? Should we go back to google and search with a different term. or visit a different site?}} </reflection>
<action> {{One Action format you choose}} </action>

Then the User will provide:

Observation: {{A labeled image screenshot Given by User}}
Previous Actions and Observations: {{Previous actions and observations}}
Current Observation and Bounding Boxes: {{Current observation and bounding boxes}}
url: {{url of the page}}
Page Text: {{Web page Page Text of the page on which we are.}}
Information Collected till now: {{Information collected till now}}
User overall ask and goal: {{User query or goal}}
Current task we are trying to solve: {{Current task we are trying to solve}}

Then you will provide the next action based on the given information.
Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<reflection> {{Are we stuck on same page or just going back and forth on same set of pages, are we making any progress and have we collected any useful information? Are we stuck in a cycle of same pages and actions? Should we go back to google and search with a different term. or visit a different site?}} </reflection>
<action> {{One Action format you choose}} </action>
"""
    images = [state["img"]]
    text = f"""{system}

Previous Actions and Observations:\n'''\n{state['scratchpad']}\n'''

Current Observation and Bounding Boxes: {state['bbox_descriptions']}
url:{state['page'].url}
Page Text: ```plaintext\n{state['text']}\n```
Information Collected till now: ```\n{state['memory']}\n```
User overall ask and our overall task goal: `{state['input']}`

Current task we are trying to solve (Focus explicitly on this current task for now and take actions to help solve this current task): `{state['current_task']}`
"""
    return {"text": text, "system": system, "images": images}


@chain
def call_llm(state):
    return CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(
        **state)


agent = annotate | RunnablePassthrough.assign(prediction=format_descriptions | create_input | call_llm | parse)

import re

# str(mmh3.hash(str(args[0]), signed=False))

import mmh3


def get_six_digit_hash(text: str) -> str:
    return str(mmh3.hash(str(text), signed=False))[:6]


def update_scratchpad(state: AgentState):
    """After a tool is invoked, we want to update
    the scratchpad so the agent is aware of its previous steps"""
    old = state.get("scratchpad")
    if old:
        txt = old
        last_line = txt.rsplit("\n", 1)[-1]
        step = int(re.match(r"\d+", last_line).group()) + 1
    else:
        txt = "Previous action observations:\n"
        step = 1
    next_step = f"\n{step}. {state['observation']}; url: {state['page'].url}; 6 digit image hash of page screenshot: {get_six_digit_hash(state['img'])}"
    txt += next_step

    return {**state, "scratchpad": txt}


from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

graph_builder = StateGraph(AgentState)

graph_builder.add_node("breakdown", break_tasks_down_with_llm)
graph_builder.add_node("agent", agent)
graph_builder.add_edge("breakdown", "agent")
graph_builder.set_entry_point("breakdown")

graph_builder.add_node("update_scratchpad", update_scratchpad)
graph_builder.add_edge("update_scratchpad", "agent")

tools = {
    "Click": click,
    "Type": type_text,
    "Scroll": scroll,
    "Wait": wait,
    "GoBack": go_back,
    "Google": to_google,
    "COLLECT_INFO": add_info_to_memory,
    "USE_COLLECTED_INFO": read_from_memory,
    "READ_PDF": read_pdf,
    "TASK_BREAKDOWN": task_breakdown,
    "TASK_COMPLETE": task_complete,
    "TASK_CREATE": task_create,
}

for node_name, tool in tools.items():
    graph_builder.add_node(
        node_name,
        # The lambda ensures the function's string output is mapped to the "observation"
        # key in the AgentState
        RunnableLambda(tool) | (lambda observation: {"observation": observation}),
    )
    # Always return to the agent (by means of the update-scratchpad node)
    graph_builder.add_edge(node_name, "update_scratchpad")


def select_tool(state: AgentState):
    # Any time the agent completes, this function
    # is called to route the output to a tool or
    # to the end user.
    action = state["prediction"]["action"]
    action_args = state["prediction"]["args"]
    full_action = f"{action}; {action_args}; url:{state['page'].url}" if action_args else action
    state["action_history"].append(full_action)

    if len(state["action_history"]) > 4:
        if len(set(state["action_history"][-5:])) == 1:
            return random.choice(["GoBack", "Scroll"])
    if len(state["action_history"]) > 7:
        if len(set(state["action_history"][-6:])) == 2:
            return random.choice(["GoBack", "Scroll", "Google"])

    if action == "ANSWER":
        return END
    if action == "retry":
        return "agent"
    elif action in tools:
        return action
    else:
        return "agent"

    return action


graph_builder.add_conditional_edges("agent", select_tool)

graph = graph_builder.compile()

import playwright
from IPython import display
from playwright.async_api import async_playwright
import asyncio


async def init_browser(start_page):
    # Start Playwright
    playwright = await async_playwright().start()

    # Path to the uBlock Origin extension
    ublock_path = os.path.join(os.getcwd(), 'uBlock0_1.58.0.chromium')

    # Launch the browser with the uBlock Origin extension
    ublock_Args = [
        f"--load-extension={ublock_path}"
    ]
    browser = await playwright.chromium.launch(
        headless=False,
        args=ublock_Args,
    )

    # Create a new browser context
    context = await browser.new_context()

    # Create a new page in the browser context
    page = await context.new_page()

    # Navigate to the start page
    await page.goto(start_page)

    return page


async def call_agent(question: str, max_steps: int = 150):
    page = await init_browser("https://www.google.com")
    event_stream = graph.astream(
        {
            "page": page,
            "input": question,
            "scratchpad": "",
            "current_task": question,
            "task_breakdown": [question],
            "completed_tasks": [],
            "action_history": [],
            "memory": "",
        },
        {
            "recursion_limit": max_steps,
        },
    )
    final_answer = None
    steps = []
    async for event in event_stream:
        # We'll display an event stream here
        if "agent" not in event:
            continue
        pred = event["agent"].get("prediction") or {}
        action = pred.get("action")
        action_input = pred.get("args")
        display.clear_output(wait=False)
        steps.append(f"{len(steps) + 1}. {action}: {action_input}")
        # print("\n".join(steps))
        print(steps[-1])
        # display.display(display.Image(base64.b64decode(event["agent"]["img"])))
        print(action, action_input)

        if "ANSWER" in action:
            final_answer = action_input[0]
            break
    return final_answer


if __name__ == "__main__":
    res = asyncio.run(call_agent("Should I invest in Ashok leyland?"))
    print(f"Final response: {res}")