import inspect
import os
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
    bbox_id = int(bbox_id)
    try:
        bbox = state["bboxes"][bbox_id]
    except:
        return f"Error: no bbox for : {bbox_id}"
    x, y = bbox["x"], bbox["y"]
    await page.evaluate('''() => {  
            document.querySelector('a').addEventListener('click', function(event) {  
                event.preventDefault();  
                window.location.href = this.href;  
            });  
    }''')
    res = await page.mouse.click(x, y)
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


async def wait(state: AgentState):
    sleep_time = 5
    await asyncio.sleep(sleep_time)
    return f"Waited for {sleep_time}s."


async def go_back(state: AgentState):
    page = state["page"]
    await page.go_back()
    return f"Navigated back a page to {page.url}."


async def to_google(state: AgentState):
    page = state["page"]
    await page.goto("https://www.google.com/")
    return "Navigated to google.com."

# Create a scratchpad file to store information for later use.
import time
scratch_file = f"memory-{time.time()}.txt"
with open(scratch_file, "w") as f:
    f.write("")
async def add_info_to_memory(state: AgentState):
    info = ";".join(state["prediction"]["args"])
    info_len = len(info.split())
    with open(scratch_file, "a") as f:
        f.write(info + "\n")
    return "COLLECT_INFO: " + f"Added information (of {info_len} words) to memory file which can be read later."


async def read_from_memory(state: AgentState):
    with open(scratch_file, "r") as f:
        info = f.read()
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
    return "READ_PDF: " + CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(model_prompt)


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


async def annotate(state):
    marked_page = await mark_page.with_retry().ainvoke(state["page"])
    return {**state, **marked_page}


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
    action = action.strip()
    if action_input is not None:
        action_input = [
            inp.strip().strip("[]") for inp in action_input.strip().split(";")
        ]
    return {"action": action, "args": action_input}


@chain
def create_input(state):
    system = """
Imagine you are a robot browsing the web, just like humans. 
Now you need to complete a task. 

In each iteration, you will receive an Observation that includes a url and screenshot of a webpage, its page text and your previous actions, and user query or goal. This screenshot will feature Numerical Labels placed in the TOP LEFT corner of each Web Element. 

Carefully analyze the visual information to identify the Numerical Label corresponding to the Web Element that requires interaction, then follow the guidelines and choose one of the following actions:

1. Click a Web Element.

2. Delete existing content in a textbox and then type content.

3. Scroll up or down.

4. Wait 

5. Go back

7. Return to google to start over.

8. Collect information from this page to write in your scratch pad or memory that you can refer later for answering.

9. Read Previously collected information if we have collected sufficient information to answer the query.

10. Read the pdf link if the page is a pdf and you think it will help us by reading the link. The pdf link will be read and relevant information will be added to the scratchpad.

11. Respond with the final answer.

Correspondingly, Action should STRICTLY follow the format:

- Click [Numerical_Label] 

- Type [Numerical_Label]; [Content] 

- Scroll [Numerical_Label or WINDOW]; [up or down] 

- Wait 

- GoBack

- Google

- COLLECT_INFO; [content or information for scratchpad]

- USE_COLLECTED_INFO

- READ_PDF [link to pdf page]

- ANSWER; [content]

Key Guidelines You MUST follow:

* Action guidelines *

1) Execute only one action per iteration.

2) When clicking or typing, ensure to select the correct bounding box.

3) Numeric labels lie in the top-left corner of their corresponding bounding boxes and are colored the same.

* Web Browsing Guidelines *

1) Don't interact with useless web elements like Login, Sign-in, donation that appear in Webpages

2) Select strategically to minimize time wasted.

3) If you can't find the required information, you can go back to the previous page.

4) Don't repeat the same action too many times especially if it seems the action is not helping.

Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<action> {{One Action format you choose}} </action>

Then the User will provide:

Observation: {{A labeled screenshot Given by User}}
url: {{url of the page}}
Page Text: {{Web page Page Text of the page on which we are.}}
User ask and goal: {{User query or goal}}

Then you will provide the next action based on the given information.
Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<action> {{One Action format you choose}} </action>
"""
    images = [state["img"]]
    text = f"{system}\n\nPrevious Actions and Observations:\n'''\n{state['scratchpad']}\n'''\n\nCurrent Observation and Bounding Boxes: {state['bbox_descriptions']}\nurl:{state['page'].url}\nPage Text: {state['text']}\n\nUser ask and goal: {state['input']}"
    return {"text": text, "system": system, "images": images}

@chain
def call_llm(state):
    return CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(**state)


agent = annotate | RunnablePassthrough.assign(prediction=format_descriptions | create_input | call_llm  | parse)


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
    txt += f"\n{step}. {state['observation']}; url: {state['page'].url}; 6 digit image hash of page screenshot: {get_six_digit_hash(state['img'])}"

    return {**state, "scratchpad": txt}


from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

graph_builder = StateGraph(AgentState)


graph_builder.add_node("agent", agent)
graph_builder.set_entry_point("agent")

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
    if action == "ANSWER":
        return END
    if action == "retry":
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
            f"--disable-extensions-except={ublock_path}",
            f"--load-extension={ublock_path}"
        ]
    browser = await playwright.chromium.launch(
        headless=False,
        args=None,
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
        if "ANSWER" in action:
            final_answer = action_input[0]
            break
    return final_answer

if __name__== "__main__":
    res = asyncio.run(call_agent("What is the PE ratio and market cap of Ashok leyland?"))
    print(f"Final response: {res}")

    # Causality and QoQ or YoY or time span related finanance questions.

    # Are you satisfied with this information? Node
    # COLLECT_INFORMATION to file
    # USE_COLLECTED_INFORMATION - from file
    # Break main task to a smaller component and follow that.