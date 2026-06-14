import inspect
import json
import os
from operator import itemgetter
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
from langchain_community.tools import HumanInputRun

from agents_common import generate_exhaustive_doc, get_prompt_from_langchain_hub, download_pdf_directly, \
    download_pdf_using_fetch, init_browser
from agents_common import generate_exhaustive_doc, get_prompt_from_langchain_hub, download_pdf_directly, get_input, async_download_pdf
from langchain_core.tools import tool

# import timeout error of playwright
from playwright._impl._api_types import TimeoutError

# Optional: add tracing to visualize the agent trajectories


from typing import List, Optional, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from playwright.async_api import Page

import asyncio
import platform

import asyncio
import base64

from langchain_core.runnables import chain, RunnableParallel

from langchain import hub
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from base import CallLLm, PDFReaderTool
from common import remove_bad_whitespaces_easy, is_pdf_link

FINAL_ANSWER_CONST = "Lets give a final answer for our overall goal or task using the ANSWER action."
NO_ANSWER_FOUND_IN_TEXT = "NO_ANSWER_FOUND_IN_TEXT_NOTHING_RELEVANT_FOUND_IN_TEXT"

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
    extra_information: str


# This represents the state of the agent
# as it proceeds through execution
class AgentState(TypedDict):
    start_with_task_breakdown: bool
    page: Page  # The Playwright web page lets us interact with the web environment
    input: str  # User request
    collected_information: str  # Information collected

    current_task: str  # The current task the agent is working on
    task_breakdown: List[str] # The steps the agent has taken to complete the task
    completed_tasks: List[str]  # The tasks the agent has completed

    action_history: List[str]  # The actions the agent has taken

    # Critic Elements
    critic: str  # The critic's output.
    next_steps: str
    need_to_break_tasks_down: bool
    answer: str

    img: str  # b64 encoded screenshot
    bboxes: List[BBox]  # The bounding boxes from the browser annotation function
    prediction: Prediction  # The Agent's output
    page_text_answer: str
    page_text_answer_urls: List[str]
    # A system message (or messages) containing the intermediate steps
    scratchpad: str
    observation: str  # The most recent response from a tool


import asyncio
import platform
from urllib.parse import urlparse, urlunparse

def get_page_url_without_query_params(page_url: str) -> str:
    # Get the current URL
    full_url = page_url

    # Parse the URL and remove query parameters
    parsed_url = urlparse(full_url)
    url_without_query = urlunparse(parsed_url._replace(query=""))
    return url_without_query

def get_domain_and_subdomain(page_url: str) -> str:
    # Parse the URL
    parsed_url = urlparse(page_url)
    # Extract the domain and subdomain
    domain_and_subdomain = parsed_url.netloc
    return domain_and_subdomain

get_short_page_url = get_domain_and_subdomain

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
    return f"Clicked {bbox_id} on {get_short_page_url(page.url)}"


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
    return f"Typed {text_content} and submitted on {get_short_page_url(page.url)}"


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

    return f"Scrolled {direction} in {'window' if target.upper() == 'WINDOW' else 'element'} on {get_short_page_url(page.url)}"



async def task_complete(state: AgentState):
    task_result = state["prediction"]["args"]
    if task_result is None or len(task_result) == 0:
        return "Failed to complete task due to incorrect arguments."
    task_result = "".join(task_result)
    completed_task = state['current_task']
    return f"TASK_COMPLETE: <task>{completed_task}</task>. Task Result: <result>{task_result}</result>"



async def wait(state: AgentState):
    sleep_time = 5
    await asyncio.sleep(sleep_time)
    return f"Waited for {sleep_time}s on {get_short_page_url(state['page'].url)}"


async def go_back(state: AgentState):
    page = state["page"]
    await page.go_back()
    if page.url == "about:blank":
        await page.goto("https://www.google.com/")
    await asyncio.sleep(1)
    return f"Navigated back a page to {page.url}."


async def to_google(state: AgentState):
    page = state["page"]
    await page.goto("https://www.google.com/")
    await asyncio.sleep(1)
    return "Navigated to google.com."


# Create a scratchpad file to store information for later use.
import time

def create_scratch_file(query: str):
    query_hash = str(mmh3.hash(str(query), signed=False))[:12]
    scratch_file = f"memory-{query_hash}.txt"
    if os.path.exists(scratch_file):
        return scratch_file
    with open(scratch_file, "w") as f:
        f.write("")
    return scratch_file


async def add_info_to_memory(state: AgentState):
    info = " ".join(state["prediction"]["args"])

    return "COLLECT_INFO: " + f"\n{info}"



async def read_pdf(state: AgentState):
    # This is a placeholder for a more complex function
    pdf_args = state["prediction"]["args"]
    if pdf_args is None or len(pdf_args) != 1:
        return f"Failed to read PDF due to incorrect arguments as {pdf_args}."
    pdf_link = pdf_args[0]
    from common import enhanced_robust_url_extractor
    pdf_link = enhanced_robust_url_extractor(pdf_link)[0]
    page = state["page"]
    current_page_url = page.url
    await page.goto(pdf_link)
    await asyncio.sleep(3)
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
        # await async_download_pdf(pdf_link, temp_file.name)
        await download_pdf_using_fetch(page, pdf_link, temp_file.name)
        pdf_link = temp_file.name

        # Download the pdf

    pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
    pdf_text = pdfReader(pdf_link)
    # pdf_text = read_pdf_simple(pdf_link)
    pdf_text = remove_bad_whitespaces_easy(pdf_text)
    pdf_text = pdf_text.split()
    pdf_text = [word for word in pdf_text if len(word.strip()) > 0]
    pdf_text = " ".join(pdf_text[:30000])
    system_prompt = """You are an expert at answering questions using provided context and in gathering helpful information. You are good at related information retrieval and answering questions based on the given text context."""
    model_prompt = f"""Provide answer to the user query: '''{state['current_task']}''' from the text below.
If some criticism has been given from model or human then provide the answer based on the criticism and refine your work.
Criticism: `{state['critic']}` 
Text: '''{pdf_text}'''"""
    pdf_result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True,
                                  model_name="gpt-4o")(model_prompt, system=system_prompt)
    return "READ_PDF: " + f"{pdf_link}\n'''{pdf_result}'''"


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
#             await page.evaluate("""
# var tags_to_remove = ['script', 'header', 'footer', 'style', 'nav', 'aside', 'iframe', 'video', 'audio', 'canvas', 'map', 'object', 'figcaption'];
# tags_to_remove.forEach(tag => {
#     const elements = document.querySelectorAll('body ' + tag);
#     elements.forEach(element => {
#         element.remove();
#     });
# });
# """)
            bboxes = await page.evaluate("markPage()")
            break
        except Exception as e:
            # May be loading...
            await asyncio.sleep(3)
    screenshot = await page.screenshot()
    # Ensure the bboxes don't follow us around
    await page.evaluate("unmarkPage()")
    # text = await page.evaluate("document.body.innerText")
    html = await page.content()
    html = remove_bad_tags(html)
    text = soup_html_parser_fast_v3(html)['text']
    text = remove_bad_whitespaces_easy(text)
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
async def annotate(state: AgentState):
    marked_page = await mark_page.with_retry().ainvoke(state["page"])
    return {**state, **marked_page}

@chain
async def break_tasks_down_with_llm(state):
    if not state["start_with_task_breakdown"]:
        return {**state}
    system = f"""Imagine you are an expert at delegating tasks, management, and breaking down complex tasks into smaller sub-tasks. You are managing a team of robots that are browsing the web. 
To help them complete a task, you need to break down the task into smaller sub-tasks if necessary. If a task is very complex or has multiple parts, you should break it down into smaller sub-tasks to make it easier to complete. 
Your goal is to help the robots complete the task as efficiently and accurately as possible and for this you need to decide if we need to break this task down or not. 
If you break the task down to simpler sub-tasks, then also write the sub-tasks that you think will help the robots complete the task. Inside <subtasks> </subtasks> tag write the sub-tasks separated by semi-colon.
{date_string()}

Each subtask should be a self contained and fully self explanatory task that can be understood independently. Subtasks could use the date and time information as well.

If we have some critic or verification of overall task then the critic will provide the criticism based on which you can refine your work and give a better breakdown based on what tasks are not complete yet.
Previous answer: {{Previous answer or empty if no verification has been done}}
Criticism: {{Critic's criticism or empty if no verification has been done}}

Your reply should strictly follow the below xml style format:
<thoughts> {{Your brief thoughts on whether this tasks need to be broken down or not and why}} </thoughts>
<subtasks> {{List of sub-tasks that you think will help the robots complete the task separated by semi-colon (';')}} </subtasks> 
"""
    model_prompt = f"""{system}
Break down the task: {state['current_task']} into smaller sub-tasks. 

If we have some critic of overall task or current task then the critic will provide the criticism based on which you can refine your work and give more extensive answer. 
Based on previous answer and criticism you can decide how to break the task down further or not and what the subtasks should be so that the remaining overall goal or work can be completed.
Previous answer: `{state['answer']}`
Criticism: `{state['critic']}`

Your reply in xml style format:
"""
    result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(
        model_prompt, system=system)
    subtasks = result.split("<subtasks>")[1].split("</subtasks>")[0].strip()
    subtasks = subtasks.split(";")
    subtasks = list(reversed(subtasks))
    subtasks = [subtask.strip() for subtask in subtasks]
    current_task = state['current_task']
    assert current_task == state['task_breakdown'][-1]
    _ = state['task_breakdown'].pop()
    # state['completed_tasks'].append(current_task)
    state['task_breakdown'].extend(subtasks)
    state['current_task'] = state['task_breakdown'].pop()
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
    if "<useful_information_from_this_page>" in text and "</useful_information_from_this_page>" in text:
        extra_information = text.split("<useful_information_from_this_page>")[-1].split("</useful_information_from_this_page>")[0].strip()
    else:
        extra_information = ""
    prediction: Prediction = {"action": action, "args": action_input, "extra_information": extra_information}
    return prediction


@chain
def create_input(state):
    # TODO: pass page text.
    state["text"] = NO_ANSWER_FOUND_IN_TEXT if NO_ANSWER_FOUND_IN_TEXT in state["page_text_answer"] else state["page_text_answer"]
    system = f"""Imagine you are a robot browsing the web, just like humans. 
Now you need to complete a task. {date_string()}

In each iteration, you will receive an Observation that includes a url and screenshot of a webpage, its url and its page text and your previous actions, and user query or goal and the current task to solve the overall user query. This screenshot will feature Numerical Labels placed in the TOP LEFT corner of each Web Element. 

Carefully analyze the visual information to identify the Numerical Label corresponding to the Web Element that requires interaction, then follow the guidelines and choose one of the following actions from the possible action list given below:

1. Click a Web Element.

2. Delete existing content in a textbox and then type content.

3. Scroll up or down.

4. Wait, if page is still loading. 

5. Go back to previous page.

6. Return to google to start over.

7. Collect information from this page text and image to write in your scratch pad or memory that you can refer later for answering.

8. Mark the current task as complete and provide the result of the task.

9. READ_PDF if we are on a pdf page as the desired action, we read the pdf and extract information from it.

10. Respond with the final answer for the overall goal when all tasks are done and we are ready to answer the overall ask or goal using action ANSWER and we have all information to complete the overall ask and overall task goal.

Correspondingly, Action should STRICTLY follow the format:

- Click [Numerical_Label] 

- Type [Numerical_Label]; [Content] 

- Scroll [Numerical_Label or WINDOW]; [up or down] 

- Wait 

- GoBack

- Google

- COLLECT_INFO [content or information for scratchpad from current page text and page screenshot image which is given as image input]

- READ_PDF [actual link to pdf page]

- TASK_COMPLETE [content]

- ANSWER [content]

Key Guidelines You MUST follow:

* Action guidelines *

1) Execute only one action per iteration.

2) When clicking or typing, ensure to select the correct bounding box.

3) Numeric labels lie in the top-left corner of their corresponding bounding boxes and are colored the same.

4) Sub tasks when created are written using the TASK_BREAKDOWN action and sub-tasks are separated by semi-colon. Breakdown complex tasks or multiple questions into sub-tasks and simple tasks using the TASK_BREAKDOWN action so that they can be solved easily. If we are stuck at a task, then also break it down.

5) You can complete the current task using TASK_COMPLETE action with the information from this page and previous collected information if we already have enough information for the current task.

6) READ_PDF if we are on a pdf page as the desired action.

7) Write the Action name first and then the arguments for the action without the square brackets.

* Web Browsing Guidelines *

1) Don't interact with useless web elements like Login, Sign-in, donation that appear in Webpages

2) Select strategically to minimize time wasted and complete the overall goal in least number of steps.

3) If you can't find the required information, you can go back to the previous page or you can go back to google search and search again.

4) Don't repeat the same action too many times especially if it seems the action is not helping. Try a variety of actions. DRY. Don't repeat yourself.

5) Write different google search query and visit different sites to collect information every time.

6) READ_PDF should be the action if we are on a pdf page as main desired action.

Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<are_we_repeating_a_google_search> {{Make sure we are not repeating previously done google searches. Observe previous actions and then reply yes/no with reasoning.}} </are_we_repeating_a_google_search>
<are_we_stuck> {{Are we stuck on same page or just going back and forth on same set of pages? Are we stuck in a cycle of same pages and actions? Should we go back to google and search with a different term. or visit a different site? Observe previous actions and then reply yes/no with reasoning.}} </are_we_stuck>
<are_we_repeating_same_actions> {{Are we repeating the same actions again and again? Observe previous actions and then reply yes/no with reasoning.}} </are_we_repeating_same_actions>
<useful_information_from_this_page> {{Extract information and put here, else leave blank. Gather information from this page that can help with the current task. Empty if no useful information found. Actual useful extracted information from page text and image only.}} </useful_information_from_this_page>
<possible_actions_to_take> {{Step by step thinking and coming up with List of possible actions (from the above possible action list) that can be taken to solve the current task with their pros and cons and payoff for each action. Should we call this task complete?}} </possible_actions_to_take>
<action_choice_reason> {{Step by step Reasoning behind the action you are goign to choose to take.}} </action_choice_reason>
<action> {{One Action format you choose from the list of possible actions written in the action format given above}} </action>

Then the User will provide:

Information Collected till now: {{Information collected till now}}
Observation: {{A labeled image screenshot Given by User}}
Previous Actions and Observations: {{Previous actions and observations}}
Current Observation and Bounding Boxes: {{Current observation and bounding boxes}}

url: {{url of the page}}

Page Text of the web page we are on (Use this page text to answer or collect information for the current task): {{Web page Page Text of the page on which we are.}}
User overall ask and goal: {{User query or goal}}
Current task we are trying to solve: {{Current task we are trying to solve}}

If we have some critic or verification of overall task then the critic will provide the criticism based on which you can refine your work and give more extensive answer.
Previous answer: {{Previous answer or empty if no verification has been done}}
Criticism: {{Critic's criticism or empty if no verification has been done}}


Then you will provide the next action based on the given information.
Your reply should strictly follow the format:

<thought> {{Your brief thoughts on what next steps to take or briefly summarize the info that will help ANSWER}} </thought>
<are_we_repeating_a_google_search> Reasoning first and then yes/no </are_we_repeating_a_google_search>
<are_we_stuck> Reasoning first and then yes/no </are_we_stuck>
<are_we_repeating_same_actions> Reasoning first and then yes/no </are_we_repeating_same_actions>
<useful_information_from_this_page> {{Extract information and put here, else leave blank. Actual useful extracted information from page text and image only.}} </useful_information_from_this_page>
<possible_actions_to_take> {{Step by step thinking and coming up with List of possible actions that can be taken to solve the current task with their pros and cons and payoff for each action. Should we call this task complete?}} </possible_actions_to_take>
<action_choice_reason> {{Step by step Reasoning behind the action you are goign to choose to take.}} </action_choice_reason>
<action> {{One Action format you choose}} </action>
"""
    images = [state["img"]]
    text = f"""Information Collected till now: '''\n{state['collected_information']}\n'''
Previous Actions you took:\n'''\n{state['scratchpad']}\n'''

Current Observation and Bounding Boxes: {state['bbox_descriptions']}

url: {state['page'].url}

Page Text of the web page we are on (Use this page text to answer or collect information or task complete for the current task): '''\n{state['page_text_answer']}\n'''
User overall ask and our overall task goal: '{state['input']}'
Current task we are trying to solve: '{state['current_task']}'

If we have any hint or specific instruction to follow from the user for this specific task then the hint will be provided here. If no hint is provided then this section will be empty.
Hint: '{state['human_hint']}'

If we have some critic of overall task then the critic will provide the criticism based on which you can refine your work and give more extensive answer.
Previous answer: '{state['answer']}'
Criticism: '{state['critic']}'

Current task we are trying to solve (Focus explicitly on this current task for now and take actions to help solve this current task): `{state['current_task']}`
"""
    return {"text": text, "system": system, "images": images}


@chain
async def call_page_text_llm(state: dict):
    # TODO: handle pdf reading.
    if state['page'].url.strip() == "https://www.google.com/":
        return NO_ANSWER_FOUND_IN_TEXT

    if is_pdf_link(state['page'].url):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            # await async_download_pdf(state['page'].url, temp_file.name)
            await download_pdf_using_fetch(state['page'], state['page'].url, temp_file.name)
            # pdf_text = read_pdf_simple(temp_file.name)
            pdfReader = PDFReaderTool({"mathpixKey": None, "mathpixId": None})
            pdf_text = pdfReader(temp_file.name)
            pdf_text = remove_bad_whitespaces_easy(pdf_text)
            pdf_text = pdf_text.split()
            pdf_text = [word for word in pdf_text if len(word.strip()) > 0]
            pdf_text = " ".join(pdf_text[:30000])
            state['text'] = pdf_text

    current_url_task_hash = get_page_url_without_query_params(state['page'].url) + "||" + state['current_task'] + "||" + state["critic"]
    if current_url_task_hash in state["page_text_answer_urls"] or state['text'].strip() == '':
        return NO_ANSWER_FOUND_IN_TEXT
    page_text_system = f"""You are an expert at answering questions using provided context and in gathering helpful information. You are good at related information retrieval and answering questions based on the given text context.
Answer the user query from given text context partially or completely if possible, if no useful information about the user query is present then just write '{NO_ANSWER_FOUND_IN_TEXT}'. 
Write only '{NO_ANSWER_FOUND_IN_TEXT}' if there is nothing useful in the text context for answering or getting information.
When you write '{NO_ANSWER_FOUND_IN_TEXT}' don't write anything else.
When you write an answer or gather useful information don't write '{NO_ANSWER_FOUND_IN_TEXT}'.
{date_string()}"""
    page_text_prompt = f"""Answer the user query from given text context partially or completely if possible, if answering from the text context is not possible then write {NO_ANSWER_FOUND_IN_TEXT}.
Write just '{NO_ANSWER_FOUND_IN_TEXT}' when no relevant information related to the user query is found in the text context.
When you write '{NO_ANSWER_FOUND_IN_TEXT}' don't write anything else.
When you write an answer or gather useful information don't write '{NO_ANSWER_FOUND_IN_TEXT}'.
Extract any relevant useful information (if present) that might help in answering later for the user query from the text context.

If some criticism has been given from model or human then provide the answer based on the criticism and refine your work.
Criticism: `{state['critic']}` 

Provide an answer partially or completely to the user query: {state['current_task']} from the text context below. 
Text context: '''\n{remove_bad_whitespaces_easy(state['text'])}\n'''
Write answer or relevant information if the answer (and any relevant information) is in the text context.
Write just '{NO_ANSWER_FOUND_IN_TEXT}' if no answer or no relevant is given in the text context.
"""
    page_result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True,
                          model_name="gpt-4-turbo")(page_text_prompt, system=page_text_system)
    if NO_ANSWER_FOUND_IN_TEXT not in page_result:
        return page_result
    return NO_ANSWER_FOUND_IN_TEXT

@chain
def call_llm(state):
    llm_result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4-turbo")(
        **state)
    return llm_result


agent = annotate | RunnablePassthrough.assign(human_hint=get_input) | RunnablePassthrough.assign(page_text_answer=call_page_text_llm) | RunnablePassthrough.assign(prediction=format_descriptions | create_input | call_llm | parse, page_text_answer=itemgetter('page_text_answer'), human_hint=itemgetter('human_hint'))

# agent = annotate | RunnableParallel(page_text_answer=RunnablePassthrough.assign(page_text_answer=call_page_text_llm), state=RunnablePassthrough.assign(prediction=format_descriptions | create_input | call_llm | parse))

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
        last_line = txt.rsplit("\n#", 1)[-1]
        match = re.match(r"\d+", last_line)
        if match:
            step = int(match.group()) + 1
        else:
            step = 1
    else:
        txt = "Previous action observations:\n"
        step = 1
    next_step = f"\n#{step}. {state['observation']}; url: {get_short_page_url(state['page'].url)}; 6 digit image hash of page screenshot: {get_six_digit_hash(state['img'])}"
    txt += next_step

    if "human_hint" in state and state["human_hint"]:
        txt += f"\nHuman Hint: {state['human_hint']}"

    if "page_text_answer" in state and state["page_text_answer"].strip() != NO_ANSWER_FOUND_IN_TEXT:
        # txt += f"\nInformation from page text for task '{state['current_task']}': '''{state['page_text_answer']}'''"
        state["collected_information"] += f"\nInformation from page text for task '{state['current_task']}': '''{state['page_text_answer']}'''"
        state["page_text_answer_urls"].append(get_page_url_without_query_params(state['page'].url) + "||" + state['current_task'] + "||" + state["critic"])

    if "COLLECT_INFO" in state['observation']:
        state["collected_information"] += f'\n{state["observation"].split("COLLECT_INFO")[1].strip()}'

    if "ANSWER" in state['observation']:
        # state["answer"] = state['observation'].split("ANSWER")[1].strip()
        state["collected_information"] += f'\n{state["observation"].split("ANSWER")[1].strip()}'

    if "TASK_COMPLETE" in state['observation']:
        completed_task = state['observation'].split("<task>")[1].split("</task>")[0]
        task_result = state['observation'].split("<result>")[1].split("</result>")[0]
        state["collected_information"] += f"\nTask Complete: {completed_task}. Result: {task_result}"
        # txt += f"\nTask Complete: {completed_task}. Result: {task_result}"
        if completed_task not in state['completed_tasks']:
            state['completed_tasks'].append(completed_task)
        if completed_task in state['task_breakdown']:
            state['task_breakdown'].remove(completed_task)
        if len(state['task_breakdown']) > 0:
            state['current_task'] = state['task_breakdown'].pop()
        else:
            state['current_task'] = FINAL_ANSWER_CONST

    return {**state, "scratchpad": txt}


def is_task_complete_or_all_info_for_task_present(state: AgentState):
    if "TASK_COMPLETE" in state['observation']:
        return {**state}
    if "ANSWER" in state['observation']: # Doesn't happen since on "ANSWER" we go to critic directly.
        return {**state}
    if "COLLECT_INFO" not in state['observation'] and state['page_text_answer'].strip() == NO_ANSWER_FOUND_IN_TEXT:
        return {**state}
    gathered_information = state['collected_information'] + (f'\n{state["answer"]}' if "answer" in state and state["answer"] else "")
    if len(gathered_information.strip()) == 0:
        return {**state}
    current_task = state["current_task"]
    llm_system_prompt = f"""You are an expert at reading and verification of work done. Verify if the current task can be answered from the information gathered till now. 
If the current task can be answered from the information gathered till now then write YES, otherwise write NO or PARTIAL if only partial answer is possible with collected information.
If the current task can be only partially answered (PARTIAL) then write the information that is still missing or incomplete and needs to be collected to answer the task completely. Then write a rephrase of the current task or query which only focuses on what is missing or incomplete or remains to be done.
Finally, also write a final answer if the current task is complete or partial answer if the current task is partially done in <answer> </answer> tag.
Your reply will be in below xml style format:

<thoughts_observations> {{Your brief thoughts on whether the current task can be answered from the information gathered till now or not and why}} </thoughts_observations>
<task_complete> YES/NO/PARTIAL </task_complete>
<missing_info> {{Missing information or incomplete information that is still needed to complete the current task}} </missing_info>
<rephrasing_task_needed>yes/no</rephrasing_task_needed>
<rephrased_task> {{Rephrased task or query which only focuses on what is missing or incomplete or remains to be done. Empty if current task is complete.}} </rephrased_task>
<answer> {{The final answer if the current task is complete or partial answer if the task is partially done. Empty if current task is completely pending and not done.}} </answer>
"""
    llm_message = f"""{llm_system_prompt}
Overall goal or overall task: '{state['input']}'
The current task is: '{current_task}'
Information gathered till now: '''\n{gathered_information}\n'''

Write your reply in xml style format:
"""
    # If task or part of task is complete then we change the current_question to reflect what is remaining and put current task in completed tasks.
    # We also add an entry to scratch pad with the answer or partial answer.

    result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(
        llm_message, system=llm_system_prompt)
    task_complete = result.split("<task_complete>")[1].split("</task_complete>")[0].strip()
    missing_info = result.split("<missing_info>")[1].split("</missing_info>")[0].strip()
    rephrasing_task_needed = result.split("<rephrasing_task_needed>")[1].split("</rephrasing_task_needed>")[0].strip()
    if rephrasing_task_needed == "yes":
        rephrased_task = result.split("<rephrased_task>")[1].split("</rephrased_task>")[0].strip()
    else:
        rephrased_task = current_task
    answer = result.split("<answer>")[1].split("</answer>")[0].strip()
    state['answer'] = ""
    if task_complete == "YES" and state['current_task'] == FINAL_ANSWER_CONST:
        state['answer'] = answer
    elif task_complete == "YES":
        state['completed_tasks'].append(state['current_task'])
        if state['current_task'] in state['task_breakdown']:
            state['task_breakdown'].remove(state['current_task'])
        if len(state['task_breakdown']) > 0:
            state['current_task'] = state['task_breakdown'].pop()
        else:
            state['current_task'] = FINAL_ANSWER_CONST
        state['collected_information'] += f"\n{answer}"

    elif task_complete == "PARTIAL" and rephrased_task != state['current_task']:
        # state['completed_tasks'].append(state['current_task'])
        # state['current_task'] = rephrased_task
        state['critic'] = missing_info + " " + rephrased_task
        state['collected_information'] += f"\n{answer}"

    else:

        return {**state}


    return {**state}


def is_task_complete_router(state: AgentState):
    if "answer" in state and state['answer']:
        return "critic"
    else:
        return "agent"

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

graph_builder = StateGraph(AgentState)

graph_builder.add_node("breakdown", break_tasks_down_with_llm)
graph_builder.add_node("agent", agent)
graph_builder.add_edge("breakdown", "agent")
graph_builder.set_entry_point("breakdown")

graph_builder.add_node("update_scratchpad", update_scratchpad)
graph_builder.add_node("task_complete_or_all_info_for_task_present", is_task_complete_or_all_info_for_task_present)
graph_builder.add_edge("update_scratchpad", "task_complete_or_all_info_for_task_present")
# graph_builder.add_edge("task_complete_or_all_info_for_task_present", "agent")
graph_builder.add_conditional_edges("task_complete_or_all_info_for_task_present", is_task_complete_router)

tools = {
    "Click": click,
    "Type": type_text,
    "Scroll": scroll,
    "Wait": wait,
    "GoBack": go_back,
    "Google": to_google,
    "COLLECT_INFO": add_info_to_memory,
    "READ_PDF": read_pdf,
    "TASK_COMPLETE": task_complete,
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
    extra_information = state["prediction"]["extra_information"] if "extra_information" in state["prediction"] else ""
    if extra_information and len(extra_information.strip().split()) > 10:
        state["collected_information"] += f"\n{extra_information}"
    full_action = f"{action}; {action_args}; url:{state['page'].url}" if action_args else f"{action}; url:{state['page'].url}"
    state["action_history"].append(full_action)
    only_past_actions = [a.split(";")[0] for a in state["action_history"]]

    if len(state["action_history"]) > 4 and action != "Type":
        if len(set(state["action_history"][-4:])) == 1 or len(set(only_past_actions[-5:])) == 1:
            return random.choice(["GoBack", "Scroll"])


    if len(state["action_history"]) > 6 and action != "Type":
        if len(set(state["action_history"][-6:])) == 2 or len(set(only_past_actions[-7:])) == 2:
            return random.choice(["GoBack", "Scroll", "Google"])

    if action == "ANSWER" and len(state["task_breakdown"]) == 0:
        state['answer'] = " ".join(action_args)
        if state["current_task"] not in state["completed_tasks"]:
            state["completed_tasks"].append(state["current_task"])
        return "critic_node"
    elif action == "ANSWER" and len(state["task_breakdown"]) > 0:
        state['current_task'] = state["task_breakdown"].pop()
        return "agent"
    if action == "retry":
        return "agent"
    elif action in tools:
        return action
    else:
        return "agent"

    return action

@chain
def critic(state: AgentState):
    # The critic node is responsible for evaluating the agent's
    # performance and providing feedback
    # This is where we can add a decision point to determine if the agent
    # should continue with the current task or go back to google
    system = f"""You are a critic evaluating a research robotic agent's answer. The agent had been tasked at completing a task by breaking it down into smaller sub-tasks.
{date_string()}
Your responsibility is to evaluate the agent's performance and provide feedback. You need to decide if the agent should continue with the current task or the task is done completely or if the task needs to be further broken down if the task is too complex for the agent.
Write in detail how the agent can improve its answer if you think the answer is not complete. If the task is complete, then write the final answer. 
If the task is not complete, then decide how we can proceed, should we break the task down further or should we ask the agent to continue on the task again.
In next_step tag you decide if the we should call the agent again on the same task or break the task down or the answer is complete and just give the answer to the user.



Your critic reply should strictly follow the below xml style format:
<critic> {{Your brief thoughts on the agent's performance and how it can improve its answer and what next steps should we take? What can the agent do differently?}} </critic>
<need_to_break_tasks_down> yes/no </need_to_break_tasks_down>
<next_step>CALL_AGENT_AGAIN/TASK_BREAKDOWN/ANSWER_COMPLETE </next_step>
<answer> {{The final elaborate and extensive answer covering all information from the agent if the task is complete otherwise empty.}} </answer> 
"""
    model_prompt = f"""{system}

Evaluate the agent's performance and provide feedback based on agent's given answer and the overall task. 

Previous Actions and Observations of the agent:\n'''\n{state['scratchpad']}\n'''
Completed Tasks: '{state['completed_tasks']}'
Information Collected till now: '''\n{state['collected_information']}\n'''
User overall ask and our overall task goal: '{state['input']}'
Answer provided by the agent: '{state['prediction'] if len(state['answer']) == 0 else state['answer']}'

Your critic reply in xml style format:
"""
    result = CallLLm({"openAIKey": os.environ["OPENAI_API_KEY"]}, use_gpt4=True, use_16k=True, model_name="gpt-4o")(
        model_prompt, system=system)
    criticism = result.split("<critic>")[1].split("</critic>")[0].strip()
    need_to_break_tasks_down = result.split("<need_to_break_tasks_down>")[1].split("</need_to_break_tasks_down>")[0].strip()
    next_steps = result.split("<next_step>")[1].split("</next_step>")[0].strip()
    if not next_steps in ["CALL_AGENT_AGAIN", "TASK_BREAKDOWN", "ANSWER_COMPLETE"]:
        next_steps = "CALL_AGENT_AGAIN"
    answer = result.split("<answer>")[1].split("</answer>")[0].strip()
    state['critic'] = criticism
    if need_to_break_tasks_down == "yes" or need_to_break_tasks_down == "true" or next_steps == "TASK_BREAKDOWN":
        state['current_task'] = state['input']
        need_to_break_tasks_down = True
    else:
        need_to_break_tasks_down = False
    critic_dict = dict(criticism=criticism, need_to_break_tasks_down=need_to_break_tasks_down, next_steps=next_steps, answer=answer)
    return {**state, **critic_dict}

graph_builder.add_node("critic_node", critic)

def critic_conditional_edge(state: AgentState):
    # Return either END or the agent node or task breakdown node
    # based on the critic's evaluation
    if state["need_to_break_tasks_down"]:
        return "breakdown"
    elif state["next_steps"] == "CALL_AGENT_AGAIN":
        return "agent"
    elif state["next_steps"] == "TASK_BREAKDOWN":
        return "breakdown"
    elif state["next_steps"] == "ANSWER_COMPLETE":
        return END

graph_builder.add_conditional_edges("agent", select_tool)
graph_builder.add_conditional_edges("critic_node", critic_conditional_edge)

graph = graph_builder.compile()

import playwright
from IPython import display
from playwright.async_api import async_playwright
import asyncio


async def call_agent(question: str, max_steps: int = 150):
    query_hash = str(mmh3.hash(str(question), signed=False))[:12]
    browser, context, page = await init_browser("https://www.google.com")
    # Read agent state if present.

    if os.path.exists(f"agent_state-{query_hash}.json"):
        with open(f"agent_state-{query_hash}.json", "r") as f:
            agent_state = json.load(f)
            agent_state["action_history"] = []
            agent_state["input"] = question
            agent_state["start_with_task_breakdown"] = False
            page_url = agent_state["page_url"]
            if page_url == "about:blank" or page_url.strip() == "":
                page_url = "https://www.google.com/"
            try:
                await page.goto(page_url)
                await asyncio.sleep(1)
            except TimeoutError:
                await page.goto("https://www.google.com/")
            agent_state["page"] = page
            del agent_state["page_url"]

            agent_state["page_text_answer_urls"] = [] if "page_text_answer_urls" not in agent_state else agent_state["page_text_answer_urls"]
    else:
        agent_state: AgentState = {
            "start_with_task_breakdown": True,
            "page": page,
            "input": question,
            "scratchpad": "",
            "current_task": question,
            "task_breakdown": [question],
            "completed_tasks": [],
            "action_history": [],
            "collected_information": "",
            "page_text_answer": NO_ANSWER_FOUND_IN_TEXT,
            "page_text_answer_urls": [],

            "critic": "",
            "next_steps": "",
            "need_to_break_tasks_down": False,
            "answer": "",
        }

    event_stream = graph.astream(agent_state,
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
        print(event["agent"]["current_task"])
        print(steps[-1])
        # display.display(display.Image(base64.b64decode(event["agent"]["img"])))
        print(action, action_input)
        # Save agent state to a file. # event["agent"]
        event["agent"]["start_with_task_breakdown"] = False
        with open(f"agent_state-{query_hash}.json", "w") as f:
            action_history = event["agent"]["action_history"]
            event["agent"]["action_history"] = []
            page = event["agent"]["page"]
            del event["agent"]["page"]
            img = event["agent"]["img"]
            del event["agent"]["img"]
            bboxes = event["agent"]["bboxes"]
            del event["agent"]["bboxes"]
            url = page.url
            event["agent"]["page_url"] = url
            json.dump(event["agent"], f, indent=4)
            event["agent"]["page"] = page
            event["agent"]["img"] = img
            event["agent"]["bboxes"] = bboxes
            del event["agent"]["page_url"]
            event["agent"]["action_history"] = action_history

        if "ANSWER" in action:
            final_answer = action_input[0] if len(event["agent"]['answer']) == 0 else event["agent"]['answer']

            break
    return final_answer


if __name__ == "__main__":
    res = asyncio.run(call_agent("Who are the current contenders in US election?"))
    print(f"Final response: {res}")

    # Emit info for task breakdown

    # Conditional edge for task breakdown initially as a single decision point.

    # Stuck at same node, go back or go back to google.

    # Just domain names

    # Collect info and then send to update_scratchpad function as a string which will then store it in state. Actions can't modify state.

    # Filter website text as a separate smaller LLM call.