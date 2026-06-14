# custom_decorator.py
import functools
from common import *
import asyncio
from playwright.async_api import async_playwright
from playwright.async_api import Page

import requests
import os
from getpass import getpass


def _getpass(env_var: str):
    if not os.environ.get(env_var):
        os.environ[env_var] = getpass(f"{env_var}=")


# Configuration to specify which framework to use
FRAMEWORK = 'dagster'  # Change this to 'airflow' or 'prefect' as needed


def custom_task(task_type='tool'):
    def decorator(func):
        if FRAMEWORK == 'airflow':
            from airflow.operators.python_operator import PythonOperator
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return PythonOperator(
                    task_id=func.__name__,
                    python_callable=func,
                    *args,
                    **kwargs
                )
        elif FRAMEWORK == 'prefect':
            from prefect import task
            wrapper = task(func)
        elif FRAMEWORK == 'dagster':
            if task_type == 'tool':
                from dagster import solid
                wrapper = solid(func)
            elif task_type == 'asset':
                from dagster import asset
                wrapper = asset(func)
            elif task_type == 'sensor':
                from dagster import sensor
                wrapper = sensor(func)
            elif task_type == 'job':
                from dagster import job
                wrapper = job(func)
            elif task_type == 'pipeline':
                from dagster import pipeline
                wrapper = pipeline(func)
            else:
                raise ValueError(f"Unsupported task type: {task_type}")
        else:
            raise ValueError(f"Unsupported framework: {FRAMEWORK}")

        return wrapper

    return decorator


# custom_doc_decorator.py
import inspect
from typing import get_type_hints




def generate_exhaustive_doc(func):
    """
    Custom decorator to generate an exhaustive docstring for a function.
    """
    # Retrieve the function's signature
    sig = inspect.signature(func)
    # Retrieve type hints
    type_hints = get_type_hints(func)
    # Retrieve the original docstring
    original_doc = func.__doc__ or ""

    # Generate the exhaustive docstring
    param_docs = []
    for param in sig.parameters.values():
        param_type = type_hints.get(param.name, 'Any')
        param_docs.append(f":param {param_type} {param.name}: Description of {param.name}")

    return_type = type_hints.get('return', 'Any')
    return_doc = f":return: {return_type} - Description of return value"

    exhaustive_doc = f"{original_doc}\n\n" + "\n".join(param_docs) + f"\n\n{return_doc}"

    # Attach the exhaustive docstring as an attribute named `doc`
    func.doc = exhaustive_doc

    return func

async def init_browser(start_page, ad_block=True):
    # Start Playwright
    playwright = await async_playwright().start()

    if ad_block:
        # Path to the uBlock Origin extension
        ublock_path = os.path.join(os.getcwd(), 'uBlock0_1.58.0.chromium')

        # Launch the browser with the uBlock Origin extension
        ublock_Args = [
            f"--load-extension={ublock_path}"
        ]
    else:
        ublock_Args = []
    browser = await playwright.chromium.launch(
        headless=False,
        args=ublock_Args,
    )

    # Create a new browser context
    context = await browser.new_context(accept_downloads=True)

    # Create a new page in the browser context
    page: Page = await context.new_page()
    if start_page == "about:blank":
        start_page = "https://www.google.com/"
    # Navigate to the start page
    try:
        await page.goto(start_page, timeout=60_000)
        await asyncio.sleep(3)
    except TimeoutError:
        await page.goto("https://www.google.com/")

    return browser, context, page


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


def web_search():
    pass

def download_link_html():
    pass

def download_link_data():
    pass

def read_link():
    pass

def scholar_search():
    pass

@CacheResults(cache=cache, expire="Monthly")
def get_prompt_from_langchain_hub(prompt):
    prompt = hub.pull(prompt)
    print(prompt)
    return prompt




def download_pdf_directly(pdf_url, download_path):
    # Send a GET request to the PDF URL
    response = requests.get(pdf_url)
    response.raise_for_status()  # Raise an exception for HTTP errors

    # Write the PDF content to a file
    with open(download_path, 'wb') as f:
        f.write(response.content)

async def async_download_pdf_v0(pdf_url, download_path):
    # Start Playwright asynchronously
    async with async_playwright() as p:
        # Launch a browser instance
        browser = await p.chromium.launch(headless=False)  # Set headless=False to see the browser interaction
        # Create a new browser context with download permission
        context = await browser.new_context(accept_downloads=True)

        # Create a new page in the browser context
        page = await context.new_page()

        # Navigate to the PDF URL
        await page.goto(pdf_url)

        # Handle the download within an asynchronous context manager
        async with page.expect_download() as download_info:
            # Trigger the download, adjust as needed; this is a placeholder action
            await page.evaluate("window.location.href")

        # Get the download object from the context manager
        download = await download_info.value

        # Save the download to the desired location
        await download.save_as(download_path)

        # Close the browser context
        await context.close()
        await browser.close()

async def download_pdf_using_fetch(page, url, download_path):
    # JavaScript to fetch and download a file
    download_script = f"""
    fetch('{url}').then(response => response.blob()).then(blob => {{
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = 'downloaded_file.pdf';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    }});
    """
    await page.evaluate(download_script)
    # Wait for the download event in Playwright
    download = await page.wait_for_event('download')
    await download.save_as(download_path)
    print(f"Downloaded file path: {await download.path()}")

import platform
async def async_download_pdf(url, download_path):
    async with async_playwright() as p:
        # Launch the browser in headless mode
        browser = await p.chromium.launch(headless=False)  # headless=False to see what happens
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # Navigate to the URL
        await page.goto(url)
        await asyncio.sleep(5)  # Wait for the page to load

        # Depending on the OS, use Cmd+S (Mac) or Ctrl+S (Windows/Linux)
        os_type = platform.system()
        shortcut = 'Meta+S' if os_type == 'Darwin' else 'Control+S'  # 'Darwin' indicates macOS


        # Perform the keyboard shortcut to initiate the download
        try:
            await page.keyboard.down(shortcut)
        except:
            shortcut = 'Cmd+S' if os_type == 'Darwin' else 'Control+S'  # 'Darwin' indicates macOS
            await page.keyboard.down(shortcut)

        # Set up to handle the download
        download = await page.wait_for_event('download')  # Wait for the download event

        # Get the path to the downloaded file
        path = await download.path()
        print(f"Downloaded file path: {path}")

        # Optionally, you can save it to another location
        await download.save_as(download_path)

        # Cleanup
        await page.close()
        await context.close()
        await browser.close()

def get_input(*args, **kwargs) -> str:
    print("Insert your text. Enter 'q' or press Ctrl-D (or Ctrl-Z on Windows) to end.")
    contents = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "q":
            break
        contents.append(line)
    return "\n".join(contents)
