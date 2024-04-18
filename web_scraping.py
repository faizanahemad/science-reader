import atexit
import copy
import os
import random
import requests
import time
import json
import base64
import http.client
import urllib.parse

import logging
from common import *
import threading
from queue import Queue

from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed, FIRST_COMPLETED, wait
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor

import urllib3
urllib3.disable_warnings()
import requests
import re
import traceback
import sys
sys.tracebacklimit = 5

script_pattern = re.compile(r'<script.*?>.*?</script>', re.IGNORECASE | re.DOTALL)
noscript_pattern = re.compile(r'<noscript.*?>.*?</noscript>', re.IGNORECASE | re.DOTALL)
script_pattern_inside_header = re.compile(r'<header.*?>.*?<script.*?>.*?</script>.*?</header>', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v1 = re.compile(r'enable(?:(?!\n).){0,100}?javascript', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v2 = re.compile(r'enable(?:(?!\n).){0,100}?js', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v3 = re.compile(r'javascript(?:(?!\n).){0,100}?required', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v4 = re.compile(r'javascript(?:(?!\n).){0,100}?disabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v5 = re.compile(r'javascript(?:(?!\n).){0,100}?not enabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v6 = re.compile(r'js(?:(?!\n).){0,100}?not enabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v7 = re.compile(r'js(?:(?!\n).){0,100}?disabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v8 = re.compile(r'js(?:(?!\n).){0,100}?required', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v9 = re.compile(r'something went wrong', re.IGNORECASE | re.DOTALL)
def check_js_needed(html):
    js_warn_1 = bool(js_warning_pattern_v1.search(html))
    js_warn_2 = bool(js_warning_pattern_v2.search(html))
    js_warn_3 = bool(js_warning_pattern_v3.search(html))
    js_warn_4 = bool(js_warning_pattern_v4.search(html))
    js_warn_5 = bool(js_warning_pattern_v5.search(html))
    js_warn_6 = bool(js_warning_pattern_v6.search(html))
    js_warn_7 = bool(js_warning_pattern_v7.search(html))
    js_warn_8 = bool(js_warning_pattern_v8.search(html))

    js_warn = js_warn_1 or js_warn_2 or js_warn_3 or js_warn_4 or js_warn_5 or js_warn_6 or js_warn_7 or js_warn_8
    no_script_text = noscript_pattern.search(html)
    no_script_warn = bool(no_script_text)
    if js_warn:
        logger.warning(f"check_js_needed js_warn = {js_warn}, no_script_warn = {no_script_warn}, {no_script_text}, js patterns flagged = 1: {js_warn_1}, 2: {js_warn_2}, 3: {js_warn_3}, 4: {js_warn_4}, 5: {js_warn_5}, 6: {js_warn_6}, 7: {js_warn_7}, 8: {js_warn_8}")
    # js_warning_pattern_v4 = re.compile(r'javascript.{0,100}?disabled', re.IGNORECASE | re.DOTALL) # js_warning_pattern_v4 = re.compile(r'javascript(?:.|\n){0,100}?disabled', re.IGNORECASE)
    return js_warn






from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO)
from tenacity import (
    retry,
    RetryError,
    stop_after_attempt,
    wait_random_exponential,
)

# Check response code and then fall back to another api or playwright based call.
# On success parse the content and return it.


def soup_parser(html):
    from bs4 import BeautifulSoup, SoupStrainer

    # Assume that `html` is the HTML string of the page
    only_custom_content = SoupStrainer('div', id='custom_content')
    soup = BeautifulSoup(html, 'lxml', parse_only=only_custom_content)

    # Find the `custom_content` div element
    custom_content_div = soup.find('div', {'id': 'custom_content'})

    # Extract the `title` and `textContent` elements from the `custom_content` div
    title_div = custom_content_div.select('#title')[0]
    text_content_div = custom_content_div.select('#textContent')[0]

    # Create a dictionary with the `title` and `textContent` values
    my_dict = {
        'title': title_div.text,
        'text': text_content_div.text
    }

    return my_dict

remove_script_tags = """
const iframeElements = document.querySelectorAll('body iframe');iframeElements.forEach(iframeElement => iframeElement.remove());
""".strip() + "var script=document.createElement('script');async function myFunc(){await new Promise((e=>setTimeout(e,1e2))),function e(){if('interactive'===document.readyState||'complete'===document.readyState){var t=document.createElement('script');t.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(t)}else setTimeout(e,5e2)}(),function e(){if('undefined'!=typeof Readability){var t=new Readability(document).parse();const e=document.getElementsByTagName('body')[0];e.innerHTML='';const n=document.createElement('div');n.id='custom_content';const i=document.createElement('div');i.id='title',i.textContent=t.title;const a=document.createElement('div');return a.id='textContent',a.textContent=t.textContent,n.appendChild(i),n.appendChild(a),e.appendChild(n),t}setTimeout(e,1e3)}()}script.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(script),myFunc();"

def send_request_bee(url, apikey):
    js = '{"instructions":[{"wait_for":"body"},{"evaluate":"' + \
         remove_script_tags + '"}]}'
    st = time.time()
    response = requests.get(
        url='https://app.scrapingbee.com/api/v1/',
        params={
            'api_key': apikey,
            'url': url,
            'wait_for': 'body',
            'block_ads': 'true',
            'js_scenario': js,
        },

    )
    if response.status_code != 200:
        raise GenericShortException(
            f"Error in scrapingbee with status code {response.status_code}")
    et = time.time() - st
    logger.info(" ".join(['send_request_bee ', str(et), "\n", response.content.decode('utf-8')[-100:]]))
    return soup_parser(response.content.decode('utf-8'))




def send_request_scrapeit(url, apikey):

    scrape_api = "https://api.scrape-it.cloud/scrape"
    payload = {
        "url": url,
        "js_rendering": True,
        "screenshot": False,
        "block_resources": True,
        "extract_emails": False,
        "block_ads": True,
        "wait_for": "body",
        "wait": 0,
        "js_scenario": [
            {
                "evaluate": remove_script_tags
            }
        ],
        "proxy_type": "datacenter",
        "proxy_country": "US"
    }
    headers = {
        "x-api-key": apikey,
        "Content-Type": "application/json"
    }

    st = time.time()
    response = requests.post(
        scrape_api, data=json.dumps(payload), headers=headers)
    if response.status_code != 200:
        raise GenericShortException(
            f"Error in scrapeit with status code {response.status_code}")
    et = time.time() - st
    data = response.json()['scrapingResult']['content']
    logger.info(" ".join(['send_request_scrapeit ', str(et), "\n", data[-100:]]))
    return soup_parser(data)


def send_request_zenrows_shim(url, apikey):
    return {
        'title': "",
        'text': ""
    }


    
def send_request_ant_html(url, apikey, readability=True):
    add_readability_for_ant = '''
    const body = document.getElementsByTagName('body')[0];
    const helloDiv = document.createElement('div');
    var script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
    document.head.appendChild(script);
    await new Promise(r => setTimeout(r, 200));


    function myFunction() {
        if (document.readyState === 'interactive' || document.readyState === 'complete') {
            var script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
            document.head.appendChild(script);
        } else {
            setTimeout(myFunction, 500);
        }
    }
    myFunction();

    function myReadable() {
        if (typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')) {
            var myDict = new Readability(document).parse();
            const body = document.getElementsByTagName('body')[0];
            body.innerHTML = '';

            const customContentDiv = document.createElement('div');
            customContentDiv.id = 'custom_content';

            const titleDiv = document.createElement('div');
            titleDiv.id = 'title';
            titleDiv.textContent = myDict.title;

            const textContentDiv = document.createElement('div');
            textContentDiv.id = 'textContent';
            textContentDiv.textContent = myDict.textContent;

            customContentDiv.appendChild(titleDiv);
            customContentDiv.appendChild(textContentDiv);

            body.appendChild(customContentDiv);
            return myDict;
        } else {
            setTimeout(myReadable, 1000);
        }
    }
    myReadable();
    '''

    ant_remove_script_tags = """
    // Select all script elements inside the body
    const scriptElements = document.querySelectorAll('body script');

    // Remove each script element
    scriptElements.forEach(scriptElement => {
      scriptElement.remove();
    });
    const iframeElements = document.querySelectorAll('body iframe');

    // Remove each iframe element
    iframeElements.forEach(iframeElement => {
      iframeElement.remove();
    });

    """ + (add_readability_for_ant if readability else "")
    rst = base64.b64encode(ant_remove_script_tags.encode()).decode()
    ant_url = "https://api.scrapingant.com/v2/general"
    params = {
        'url': url,
        'x-api-key': apikey,
        'proxy_country': 'US',
        'wait_for_selector': 'body',
        'return_page_source': 'true',
        'js_snippet': rst
    }
    response = requests.get(ant_url, params=params)
    if response.status_code != 200:
        error_decode = json.loads(response.text)
        detected = error_decode["detail"].startswith("Our browser was detected by target site.")
        if detected:
            params['proxy_type'] = 'residential'
            response = requests.get(url, params=params)
        if response.status_code != 200:
            error_details = response.text
            raise GenericShortException(
                f"Error in ant with status code {response.status_code} and error details {error_details}")
    html = remove_script_tags_from_html(response.text)
    time_logger.info(" ".join(
        ['[send_request_ant_html] ', f"Time = {et:.2f}, ", f"Response length = {len(html.split())}",
         f"link = {url}"]))
    return html


user_agents = [
    # Chrome
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36',

    # Firefox
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:54.0) Gecko/20100101 Firefox/54.0',
    'Mozilla/5.0 (X11; Linux x86_64; rv:78.0) Gecko/20100101 Firefox/78.0',

    # Edge
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.102 Safari/537.36 Edge/18.19582',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36 Edge/18.17720',

    # Safari
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
]

            
        
readability_script_content_response = requests.get("https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
assert readability_script_content_response.status_code == 200
readability_script_content = readability_script_content_response.text

# https://github.com/alan-turing-institute/ReadabiliPy
# https://trafilatura.readthedocs.io/en/latest/
# https://github.com/goose3/goose3

def browse_to_page_playwright(url, playwright_cdp_link=None, timeout=5, get_html=False):
    if playwright_cdp_link is None:
        playwright_cdp_link = os.environ.get("BRIGHTDATA_PLAYWRIGHT_CDP_LINK", None)
    text = ''
    title = ''
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(playwright_cdp_link)
            page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            page.goto(url, timeout=timeout*1_000)
            if get_html:
                page.wait_for_function(
                    "() => document.readyState === 'complete' || document.readyState === 'interactive'",
                    timeout=8_000)
                result = page.content()
                page.close()
                browser.close()
                return result
            else:
                page.add_script_tag(content=readability_script_content)
                page.wait_for_function(
                    "() => typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')",
                    timeout=8_000)
                result = page.evaluate(
                    """(function execute(){var article = new Readability(document).parse();return article})()""")
            if result is not None and "title" in result and "textContent" in result and result["textContent"] is not None and result["textContent"] != "":
                title = normalize_whitespace(result['title'])
                text = normalize_whitespace(result['textContent'])
                page.close()
                browser.close()
                return {"text": text, "title": title}
            else:
                html = page.content()
                page.close()
                browser.close()
                return soup_html_parser(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.warning(
            f"Error in browse_to_page_brightdata_playwright with exception = {str(e)}")
        return {"text": text, "title": title}

def browse_to_page_selenium(url, brightdata_selenium_url=None, timeout=10):
    if brightdata_selenium_url is None:
        brightdata_selenium_url = os.environ.get("BRIGHTDATA_SELENIUM_URL", None)
    from selenium.webdriver import Remote, ChromeOptions
    from selenium.webdriver.chromium.remote_connection import ChromiumRemoteConnection
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.wait import WebDriverWait
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support import expected_conditions as EC
    sbr_connection = ChromiumRemoteConnection(brightdata_selenium_url, 'goog', 'chrome')
    with Remote(sbr_connection, options=ChromeOptions()) as driver:
        driver.get(url)
        add_readability_to_selenium = '''
                            function myFunction() {
                                var script = document.createElement('script');
                                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
                                document.head.appendChild(script);
                            }

                            myFunction();
                        '''
        try:
            driver.execute_script(add_readability_to_selenium)
            while driver.execute_script('return document.readyState;') != 'interactive':
                time.sleep(0.2)

            def document_initialised(driver):
                return driver.execute_script(
                    """return typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive');""")

            WebDriverWait(driver, timeout=timeout).until(document_initialised)
            result = driver.execute_script("""var article = new Readability(document).parse();return article""")
            if result is not None and "title" in result and "textContent" in result and result["textContent"] is not None and result["textContent"] != "":
                title = normalize_whitespace(result['title'])
                text = normalize_whitespace(result['textContent'])
                driver.close()
                return {"text": text, "title": title}
            else:
                init_html = driver.execute_script("""return document.body.innerHTML;""")
                driver.close()
                return soup_html_parser(init_html)
        except Exception as e:
            exc = traceback.format_exc()
            logger.warning(
                f"Error in browse_to_page_selenium with exception = {str(e)}")
            return {"text": "", "title": ""}

# pip install readabilipy from this git repo https://github.com/alan-turing-institute/ReadabiliPy below.
# pip install

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def fetch_content_brightdata_shim(url, brightdata_proxy):
    return {
        'title': "",
        'text': ""
    }

def fetch_content_brightdata_html(url, brightdata_proxy=None):
    """
    Fetch the content of the webpage at the specified URL using a proxy.

    Parameters:
    url (str): The URL of the webpage to fetch.

    Returns:
    str: The content of the webpage.
    """
    if brightdata_proxy is None:
        brightdata_proxy = os.environ.get("BRIGHTDATA_PROXY", None)

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    # Define the proxies
    proxies = {"http": brightdata_proxy, "https": brightdata_proxy}

    # Create a session
    session = requests.Session()

    # Set up retries
    retries = Retry(total=0, backoff_factor=2, status_forcelist=[400, 401, 402, 403, 422, 420, 404, 500, 501, 502, 503, 504, 505])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))

    # Make the request
    response = session.get(url, proxies=proxies, verify=False)
    html = response.text
    js_need = check_js_needed(html)

    if js_need:
        logger.warning(f"[fetch_content_brightdata_html] Js needed for link {url}")
        return None
    return html

import re

def remove_script_tags_from_html(html):
    # This regex looks for <script> tags and their content and removes them
    cleaned_html = re.sub(r'<script[^>]*?>.*?</script>', '', html, flags=re.DOTALL)
    soup = BeautifulSoup(cleaned_html, 'html.parser')
    for header in soup.find_all(['header', 'footer', 'script', 'style', 'nav', 'aside', 'form', 'iframe', 'img', 'button', 'input', 'select', 'textarea', 'video', 'audio', 'canvas', 'map', 'object', 'svg', 'figure', 'figcaption']):
        header.decompose()
    element = soup.find(id='bib')
    # Remove the element
    if element is not None:
        element.decompose()
    # get html back from soup
    cleaned_html = str(soup)
    return cleaned_html



def fetch_content_brightdata(url, brightdata_proxy):
    st = time.time()
    html = fetch_content_brightdata_html(url, brightdata_proxy)
    html = remove_script_tags_from_html(html)
    result = None
    soup_html_parser_result = get_async_future(soup_html_parser, html)
    try:
        soup_html_parser_result = soup_html_parser_result.result()
    except Exception as e:
        soup_html_parser_result = None
        exc = traceback.format_exc()
        logger.error(f"[fetch_content_brightdata] link = {url}, Error in soup_html_parser with exception = {str(e)}\n{exc}")

    if soup_html_parser_result is not None and (result is None or len(result['text']) < len(soup_html_parser_result['text']) // 4):
        result = soup_html_parser_result

    # Return the response content
    if result is not None and "text" in result and len(result["text"]) > 0:
        result["text"] = remove_bad_whitespaces(result["text"])
    # do the same for title
    if result is not None and "title" in result and len(result["title"]) > 0:
        result["title"] = remove_bad_whitespaces(result["title"])
    et = time.time() - st
    time_logger.info(" ".join(
        ['[fetch_content_brightdata] ', f"Time = {et:.2f}, ", f"Response length = {len(result['text'].split())}",
         f"link = {url}"]))
    return result

import threading
import time
ZENROW_PARALLELISM = 10
zenrows_semaphore = threading.Semaphore(ZENROW_PARALLELISM)

def send_request_zenrows_html(url, apikey, readability=True):
    st = time.time()
    if readability:
        js = '''[{"wait":500},{"wait_for":"body"},{"evaluate":"''' + remove_script_tags + '''"}]'''
    else:
        js = '''[{"wait":500},{"wait_for":"body"}]'''

    params = {
        'url': url,
        'apikey': apikey,
        'js_render': 'true',
        'wait_for': 'body',
        'block_resources': 'image,media,stylesheet,font',
        'js_instructions': js,
    }
    with zenrows_semaphore:
        response = requests.get('https://api.zenrows.com/v1/', params=params)
    if response.status_code != 200:
        raise GenericShortException(
            f"Error in zenrows with status code {response.status_code} for url {url} with response {response.text}")
    if response is None or response.text is None:
        return {
            'title': "",
            'text': ""
        }
    et = time.time() - st
    html = response.text
    html = remove_script_tags_from_html(html)
    time_logger.info(" ".join(
        ['[send_request_zenrows_html] ', f"Time = {et:.2f}, ", f"Response length = {len(html.split())}",
         f"link = {url}"]))
    return html

def fetch_html(url, apikey=None, brightdata_proxy=None):
    # TODO: add brightdata selenium and playwright backup as well.
    html = ''
    js_need = True
    soup_html_parser_result = ''
    zenrows_html = get_async_future(send_request_zenrows_html, url, apikey, readability=False)
    browse_to_page_playwright_result = get_async_future(browse_to_page_playwright, url, timeout=10, get_html=True)
    brightdata_scrape = get_async_future(fetch_content_brightdata, url, brightdata_proxy)
    st = time.time()
    while not zenrows_html.done() or not browse_to_page_playwright_result.done() or not brightdata_scrape.done():
        time.sleep(0.5)
    while True and time.time() - st < 60:
        if zenrows_html.done() and zenrows_html.exception() is None:
            html = zenrows_html.result() if zenrows_html.exception() is None else ''
            html = remove_script_tags_from_html(html)
            soup_html_parser_result = get_async_future(soup_html_parser, html)
            soup_html_parser_result = soup_html_parser_result.result() if soup_html_parser_result.exception() is None else ''
            if soup_html_parser_result != '':
                break
        if brightdata_scrape.done() and brightdata_scrape.exception() is None:
            html = brightdata_scrape.result() if brightdata_scrape.exception() is None else ''
            js_need = check_js_needed(html)
            html = remove_script_tags_from_html(html)
            soup_html_parser_result = get_async_future(soup_html_parser, html)
            soup_html_parser_result = soup_html_parser_result.result() if soup_html_parser_result.exception() is None else ''
            if not js_need and soup_html_parser_result != '':
                break

        if browse_to_page_playwright_result.done() and browse_to_page_playwright_result.exception() is None:
            html = browse_to_page_playwright_result.result() if browse_to_page_playwright_result.exception() is None else ''
            html = remove_script_tags_from_html(html)
            soup_html_parser_result = get_async_future(soup_html_parser, html)
            soup_html_parser_result = soup_html_parser_result.result() if soup_html_parser_result.exception() is None else ''
            if soup_html_parser_result != '':
                break

    # if brightdata_proxy is not None and brightdata_scrape is not None:
    #     html = brightdata_scrape.result() if brightdata_scrape.exception() is None else ''
    #     js_need = check_js_needed(html)
    #     html = remove_script_tags_from_html(html)
    #     soup_html_parser_result = get_async_future(soup_html_parser, html)
    #     soup_html_parser_result = soup_html_parser_result.result() if soup_html_parser_result.exception() is None else ''
    #
    # if (js_need or brightdata_proxy is None or brightdata_proxy == '' or html == '' or soup_html_parser_result == '') and apikey is not None:
    #     html = zenrows_html.result() if zenrows_html.exception() is None else ''
    #     html = remove_script_tags_from_html(html)
    #     soup_html_parser_result = get_async_future(soup_html_parser, html)
    #     soup_html_parser_result = soup_html_parser_result.result() if soup_html_parser_result.exception() is None else ''
    #
    # if html == '' or soup_html_parser_result == '':
    #     html = browse_to_page_playwright_result.result() if browse_to_page_playwright_result.exception() is None else ''
    #     html = remove_script_tags_from_html(html)
    return html

def send_request_for_webpage(url, apikey, zenrows_or_ant='zenrows', readability=True):
    page_fetching_start = time.time()
    if zenrows_or_ant == 'zenrows':
        html = send_request_zenrows_html(url, apikey, readability)
    elif zenrows_or_ant == 'ant':
        html = send_request_ant_html(url, apikey, readability)
    elif zenrows_or_ant == 'brightdata':
        html = fetch_content_brightdata_html(url, apikey)
    html_processing_start = time.time()
    result = get_async_future(soup_parser, html)
    soup_html_parser_result = get_async_future(soup_html_parser_fast, html) # soup_html_parser_fast_v2
    soup_html_parser_result_v2 = get_async_future(soup_html_parser_fast_v2, html)

    # wait till any of these future is done.
    done, _ = wait([result, soup_html_parser_result, soup_html_parser_result_v2], return_when=FIRST_COMPLETED)
    if done:
        for future in [result, soup_html_parser_result, soup_html_parser_result_v2]:
            if future.done() and future.exception() is None:
                result = future.result()
                break
    if result is not None and "text" in result and len(result["text"]) > 0:
        result["text"] = remove_bad_whitespaces(result["text"])
    if result is None:
        result = {
            'title': "",
            'text': ""
        }
    html_processing_end = time.time()
    time_logger.info(
        f"[send_request_for_webpage] Page fetching time = {html_processing_start - page_fetching_start:.2f}, html processing time = {html_processing_end - html_processing_start:.2f}, result len = {len(result['text'].split())}, link = {url}")

    return result


from bs4 import BeautifulSoup, NavigableString

def soup_html_parser(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string if soup.title else ''
    for link in soup.find_all('a'):
        link.decompose()
    for header in soup.find_all(['header', 'footer', 'script', 'style', 'nav', 'aside', 'form', 'iframe', 'img', 'button', 'input', 'select', 'textarea', 'video', 'audio', 'canvas', 'map', 'object', 'svg', 'figure', 'figcaption']):
        header.decompose()
    element = soup.find(id='bib')
    # Remove the element
    if element is not None:
        element.decompose()
    elements = soup.find_all('div', {'class': 'arxiv-vanity-wrapper'})
    for element in elements:
        element.decompose()

    def extract_text(element):
        # If the element is a string, return it as is
        if isinstance(element, NavigableString):
            return element.strip()
        # If the element is a tag you're interested in and doesn't contain any child tags of interest, extract its text
        elif element.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and not any(child.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] for child in element.children):
            return element.get_text().strip()
        # Otherwise, return an empty string
        return ""

    content_text = ''
    for child in soup.recursiveChildGenerator():
        text = extract_text(child)
        if text:
            content_text += text.strip() + '\n'

    return {"text": normalize_whitespace(content_text.strip()), "title": normalize_whitespace(title)}

def soup_html_parser_fast_v2(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string if soup.title else ''
    for link in soup.find_all('a'):
        link.decompose()
    for header in soup.find_all(['header', 'footer', 'script', 'style', 'nav', 'aside', 'form', 'iframe', 'img', 'button', 'input', 'select', 'textarea', 'video', 'audio', 'canvas', 'map', 'object', 'svg', 'figure', 'figcaption']):
        header.decompose()
    element = soup.find(id='bib')
    # Remove the element
    if element is not None:
        element.decompose()
    elements = soup.find_all('div', {'class': 'arxiv-vanity-wrapper'})
    for element in elements:
        element.decompose()

    # content_text = " ".join(soup.findAll(text=True))
    content_text = soup.text
    return {"text": normalize_whitespace(content_text.strip()), "title": normalize_whitespace(title)}

def soup_html_parser_fast(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string if soup.title else ''

    def extract_text(element):
        # If the element is a string, return it as is
        if isinstance(element, NavigableString):
            return element.strip()
        # If the element is a tag you're interested in and doesn't contain any child tags of interest, extract its text
        elif element.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and not any(child.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] for child in element.children):
            return element.get_text().strip()
        # Otherwise, return an empty string
        return ""

    content_text = ''
    for child in soup.recursiveChildGenerator():
        text = extract_text(child)
        if text:
            content_text += text.strip() + '\n'

    return {"text": normalize_whitespace(content_text.strip()), "title": normalize_whitespace(title)}

class ScrapingValidityException(Exception):
    def __init__(self, message=""):
        super().__init__(message)

    def __str__(self):
        return self.args[0]


def validate_web_page_scrape(result):
    return result is not None and isinstance(result, dict) and "text" in result and len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR

good_page_size = 100

def post_process_web_page_scrape(link, result_from, result, st):

    et = time.time()
    if result is None or "text" not in result:
        raise ScrapingValidityException(f"[ALL_FAILED] None succeeded in time. No result for {link} from {result_from}")
    result["text"] = remove_bad_whitespaces_easy(normalize_whitespace(result["text"]))
    result["title"] = normalize_whitespace(result["title"])
    if result["text"].strip() == DDOS_PROTECTION_STR:
        error_logger.error(
            f"[DDOS_PROTECTION] DDOS Protection for {link} from {result_from},  result len = {len(result['text'])} and result sample = {result['text'][:10]}")
        raise ScrapingValidityException(
            f"{DDOS_PROTECTION_STR} DDOS Protection for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")

    elif len(result["text"].strip().split()) < good_page_size:
        error_logger.error(
            f"[TOO_SHORT] Text too short for {link} from {result_from}, result len = {len(result['text'])}, and result sample = {result['text'][:50]}")
        raise ScrapingValidityException(
            f"Text too short for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")

    time_logger.info(
        f"[web_scrape_page]:: time = {(et - st):.2f}, result len = {len(result['text'].split())}, whitespace_removal_time = {(time.time() - et):.2f}, Got result for link {link} from {result_from}")
    success_logger.info(
        f"[web_scrape_page]:: Got result for link {link} from {result_from}, result len = {len(result['text'].split())}, time = {et:.2f}")

    return result

from scipy import spatial
@log_memory_usage
def web_scrape_page(link, context, apikeys, web_search_tmp_marker_name=None):
    # TODO: implement pre-emptive site blocking here. Also in PDF reading function.
    result = dict(text="", title="", link=link, error="")
    st = time.time()
    # bright_data_result = get_async_future(fetch_content_brightdata, link, apikeys['brightdataUrl'])
    bright_data_playwright_result = None
    bright_data_selenium_result = None
    logger.debug(f"[web_scrape_page] Invoke for {link}.")

    # if random.random() <= 0.5:
    #     bright_data_playwright_result = get_async_future(browse_to_page_playwright, link)
    # else:
    #     bright_data_selenium_result = get_async_future(browse_to_page_selenium, link)
    # bright_data_playwright_result = get_async_future(browse_to_page_playwright, link)
    # bright_data_selenium_result = get_async_future(browse_to_page_selenium, link)
    if "zenrows" in apikeys:
        zenrows_service_result = get_async_future(send_request_for_webpage, link, apikeys['zenrows'], zenrows_or_ant='zenrows')
    else:
        zenrows_service_result = None

    if "scrapingant" in apikeys:
        ant_service_result = get_async_future(send_request_for_webpage, link, apikeys['scrapingant'], zenrows_or_ant='ant', readability=False)
    else:
        ant_service_result = None

    if "brightdataUrl" in apikeys:
        bright_data_result = get_async_future(send_request_for_webpage, link, apikeys['brightdataUrl'], zenrows_or_ant='brightdata', readability=False)
    else:
        bright_data_result = None

        # embedding_model = get_embedding_model(apikeys)
    # query_embeddings_future = get_async_future(embedding_model.embed_query, context)

    # Also add bright data cdp fetch as a backup.
    result_from = "None"
    brightdata_exception = False
    zenrows_exception = False
    ant_exception = False
    bright_data_playwright_exception = False
    bright_data_selenium_exception = False
    # TODO: Change timeout based on whether it is a single page link read or multiple pages.
    # TODO: use the cache module with a lock based on url to ensure error is noted and attempts + success rates are noted.
    break_loop = False
    while time.time() - st < 45 and exists_tmp_marker_file(web_search_tmp_marker_name) and not break_loop:
        if zenrows_exception and brightdata_exception and bright_data_playwright_exception and bright_data_selenium_exception and ant_exception:
            break_loop = True
            error_logger.error(f"[web_scrape_page] for {link} zenrows exception \n{zenrows_service_result.exception()} \n brightdata exception \n{bright_data_result.exception()} \n ant exception \n{ant_service_result.exception()} \n bright_data_playwright_exception \n{bright_data_playwright_result.exception()} \n bright_data_selenium_exception \n{bright_data_selenium_result.exception()}")
            break
        # if zenrows_exception and brightdata_exception:
        #     if random.random() <= 0.5:
        #         bright_data_playwright_result = get_async_future(browse_to_page_playwright, link)
        #     else:
        #         bright_data_selenium_result = get_async_future(browse_to_page_selenium, link)
        if zenrows_service_result is not None and zenrows_service_result.done() and zenrows_service_result.exception() is None and not zenrows_exception:
            result = zenrows_service_result.result()
            result_from = "zenrows_tentative"
            validity_of_result = validate_web_page_scrape(result)
            logger.info(f"[web_scrape_page] [ZENROWS] Got tentative result with validity = {validity_of_result} for link {link}")
            if validity_of_result:
                result_from = "zenrows"
                break_loop = True
                break
            else:
                zenrows_exception = True
                error_logger.error(
                    f"[ZENROWS] Error in zenrows for link {link} with result {result} and exception {zenrows_service_result.exception()}")

        if ant_service_result is not None and ant_service_result.done() and ant_service_result.exception() is None and not ant_exception and time.time() - st >= 4:
            result = ant_service_result.result()
            result_from = "ant_tentative"
            validity_of_result = validate_web_page_scrape(result)
            logger.info(f"[web_scrape_page] [ANT] Got tentative result with validity = {validity_of_result} for link {link}")
            if validity_of_result:
                result_from = "ant"
                break_loop = True
                break
            else:
                ant_exception = True
                error_logger.error(f"[ANT] Error in ant for link {link} with result {result} and exception {ant_service_result.exception()}")

        # if bright_data_playwright_result is not None and bright_data_playwright_result.done() and bright_data_playwright_result.exception() is None and not bright_data_playwright_exception:
        #     result = bright_data_playwright_result.result()
        #     result_from = "bright_data_playwright_tentative"
        #     validity_of_result = validate_web_page_scrape(result)
        #     if validity_of_result:
        #         result_from = "bright_data_playwright"
        #         break_loop = True
        #         break
        #     else:
        #         bright_data_playwright_exception = True
        #         error_logger.error(
        #             f"[BRIGHTDATA_PLAYWRIGHT] Error in bright_data_playwright for link {link} with result {result} and exception {bright_data_playwright_result.exception()}")
        #
        # if bright_data_selenium_result is not None and bright_data_selenium_result.done() and bright_data_selenium_result.exception() is None and not bright_data_selenium_exception:
        #     result = bright_data_selenium_result.result()
        #     result_from = "bright_data_selenium_tentative"
        #     validity_of_result = validate_web_page_scrape(result)
        #     if validity_of_result:
        #         result_from = "bright_data_selenium"
        #         break_loop = True
        #         break
        #     else:
        #         bright_data_selenium_exception = True
        #         error_logger.error(
        #             f"[BRIGHTDATA_SELENIUM] Error in bright_data_selenium for link {link} with result {result} and exception {bright_data_selenium_result.exception()}")

        if bright_data_result is not None and bright_data_result.done() and bright_data_result.exception() is None and not brightdata_exception and (time.time() - st >= 18 or zenrows_exception or ant_exception):
            result = bright_data_result.result()
            result_from = "brightdata_tentative"
            validity_of_result = validate_web_page_scrape(result)
            logger.info(f"[web_scrape_page] [BRIGHTDATA] Got tentative result with validity = {validity_of_result} for link {link}")
            if validity_of_result:
                result_from = "brightdata"
                break_loop = True
                break
            else:
                brightdata_exception = True
                error_logger.error(
                    f"[BRIGHTDATA] Error in brightdata for link {link} with result {result} and exception {bright_data_result.exception()}")

        time.sleep(0.5)

    return post_process_web_page_scrape(link, result_from, result, st)



if __name__=="__main__":
    # result = send_request_zenrows("https://platform.openai.com/docs/guides/images/usage", "0e1c6def95eadc85bf9eff4798f311231caca6b3")
    # print(result)
    # result = fetch_content_brightdata("https://platform.openai.com/docs/guides/images/usage", "http://brd-customer-hl_f6ac9ba2-zone-unblocker:39vo949l2tfh@brd.superproxy.io:22225")
    # print(result)
    # result = web_scrape_page("https://docs.scrapingant.com/captcha-and-cloudflare", '',
    #                          {"brightdataUrl": "http://brd-customer-hl_f6ac9ba2-zone-unblocker:39vo949l2tfh@brd.superproxy.io:22225",
    #                           # "zenrows": "XXX"
    #                           })
    # print(result)
    st = time.time()
    res = send_request_for_webpage("https://docs.scrapingant.com/captcha-and-cloudflare", "XXX", zenrows_or_ant='ant')
    print(len(res['text'].strip().split()))
    et = time.time() - st
    print(f"Ant Time = {et:.2f}")

    st = time.time()
    res = send_request_for_webpage("https://docs.scrapingant.com/captcha-and-cloudflare",
                                   "XXX", zenrows_or_ant='ant', readability=False)
    print(len(res['text'].strip().split()))
    et = time.time() - st
    print(f"Ant Time = {et:.2f}")


    st = time.time()
    res = send_request_for_webpage("https://docs.scrapingant.com/captcha-and-cloudflare", "XXX", zenrows_or_ant='zenrows')
    print(len(res['text'].strip().split()))
    et = time.time() - st
    print(f"Zenrows Time = {et:.2f}")

    st = time.time()
    res = send_request_for_webpage("https://docs.scrapingant.com/captcha-and-cloudflare",
                                   "XXX", zenrows_or_ant='zenrows', readability=False)
    print(len(res['text'].strip().split()))
    et = time.time() - st
    print(f"Zenrows Time = {et:.2f}")
