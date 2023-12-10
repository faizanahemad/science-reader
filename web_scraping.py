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
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor

import urllib3
urllib3.disable_warnings()
import requests
import re
import traceback

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

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.ERROR,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)
logger.setLevel(logging.ERROR)
time_logger = logging.getLogger(__name__ + " | TIMING")
time_logger.setLevel(logging.INFO)  # Set log level for this logger

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
const scriptElements = document.querySelectorAll('body script');scriptElements.forEach(scriptElement => scriptElement.remove());const iframeElements = document.querySelectorAll('body iframe');iframeElements.forEach(iframeElement => iframeElement.remove());
""".strip() + """var script=document.createElement("script");async function myFunc(){await new Promise((e=>setTimeout(e,1e3))),function e(){if("interactive"===document.readyState||"complete"===document.readyState){var t=document.createElement("script");t.src="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js",document.head.appendChild(t)}else setTimeout(e,200)}(),function e(){if("undefined"!=typeof Readability){const n=document.getElementsByTagName("body")[0];inner_html=n.innerHTML;try{var t=new Readability(document).parse();n.innerHTML="";const e=document.createElement("div");e.id="custom_content";const i=document.createElement("div");i.id="title",i.textContent=t.title;const c=document.createElement("div");return c.id="textContent",c.textContent=t.textContent,e.appendChild(i),e.appendChild(c),n.appendChild(e),t}catch(e){return console.log(e),e.innerHTML=inner_html,inner_html}}setTimeout(e,1e3)}()}script.src="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js",document.head.appendChild(script),myFunc();"""
js = '{"instructions":[{"wait_for":"body"},{"evaluate":"' + \
    remove_script_tags + '"}]}'


def send_request_bee(url, apikey):
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
        raise Exception(
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
        raise Exception(
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


    


def send_request_ant(url, apikey):
    
    add_readability_to_selenium = '''
const body = document.getElementsByTagName('body')[0];
const helloDiv = document.createElement('div');
var script = document.createElement('script');
script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
document.head.appendChild(script);
await new Promise(r => setTimeout(r, 2000));


function myFunction() {
    if (document.readyState === 'interactive' || document.readyState === 'complete') {
        var script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
        document.head.appendChild(script);
    } else {
        setTimeout(myFunction, 1000);
    }
}
myFunction();

function myReadable() {
    if (typeof(Readability) !== 'undefined') {
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
        setTimeout(myReadable, 2000);
    }
}
myReadable();
'''


    remove_script_tags = """
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

""" + add_readability_to_selenium
    
    url = urllib.parse.quote(url)
    rst = base64.b64encode(remove_script_tags.encode()).decode()
    st = time.time()
    conn = http.client.HTTPSConnection("api.scrapingant.com")
    conn.request("GET", f"/v2/general?url={url}&x-api-key={apikey}&proxy_country=US&wait_for_selector=body&js_snippet="+rst)

    res = conn.getresponse()
    if res.status != 200:
        raise Exception(
            f"Error in ant with status code {res.status}")
    data = res.read()
    html_content = data.decode("utf-8")
    et = time.time() - st
    logger.info(" ".join(['send_request_ant ', str(et), "\n", html_content[-100:]]))
    return soup_parser(html_content)



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

def browse_to_page_playwright(url, playwright_cdp_link=None, timeout=10):
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
            page.add_script_tag(content=readability_script_content)
            page.wait_for_function(
                "() => typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')",
                timeout=12_000)
            result = page.evaluate(
                """(function execute(){var article = new Readability(document).parse();return article})()""")
            if result is not None and "title" in result and "textContent" in result and result["textContent"] is not None and result["textContent"] != "":
                title = normalize_whitespace(result['title'])
                text = normalize_whitespace(result['textContent'])
                return {"text": text, "title": title}
            else:
                html = page.content()
                return soup_html_parser(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.warning(
            f"Error in browse_to_page_brightdata_playwright with exception = {str(e)}")
        return {"text": text, "title": title}

def browse_to_page_selenium(url, brightdata_selenium_url=None, timeout=15):
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
                time.sleep(0.1)

            def document_initialised(driver):
                return driver.execute_script(
                    """return typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive');""")

            WebDriverWait(driver, timeout=timeout).until(document_initialised)
            result = driver.execute_script("""var article = new Readability(document).parse();return article""")
            if result is not None and "title" in result and "textContent" in result and result["textContent"] is not None and result["textContent"] != "":
                title = normalize_whitespace(result['title'])
                text = normalize_whitespace(result['textContent'])
                return {"text": text, "title": title}
            else:
                init_html = driver.execute_script("""return document.body.innerHTML;""")
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
    return html

import re

def remove_script_tags_from_html(html):
    # This regex looks for <script> tags and their content and removes them
    cleaned_html = re.sub(r'<script[^>]*?>.*?</script>', '', html, flags=re.DOTALL)
    return cleaned_html



def fetch_content_brightdata(url, brightdata_proxy):
    html = fetch_content_brightdata_html(url, brightdata_proxy)
    js_need = check_js_needed(html)

    if js_need:
        logger.warning(f"[fetch_content_brightdata] Js needed for link {url}")
        return None
    html = remove_script_tags_from_html(html)
    result = None
    soup_html_parser_result = None
    # result = get_async_future(local_browser_reader, html)
    soup_html_parser_result = get_async_future(soup_html_parser, html)
    try:
        result = result.result()
    except Exception as e:
        result = None
        exc = traceback.format_exc()
        logger.warning(f"[fetch_content_brightdata] link = {url}, Error in fetch_content_brightdata with exception = {str(e)}")
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
        raise Exception(
            f"Error in zenrows with status code {response.status_code}")
    if response is None or response.text is None:
        return {
            'title': "",
            'text': ""
        }
    et = time.time() - st
    logger.info(" ".join(['send_request_zenrows ', f"Time = {et:.2f}, ", f"Response length = {len(response.text)}"]))
    html = response.text
    html = remove_script_tags_from_html(html)
    return html

def fetch_html(url, apikey=None, brightdata_proxy=None):
    html = ''
    if brightdata_proxy is not None:
        html = fetch_content_brightdata_html(url, brightdata_proxy)
    js_need = check_js_needed(html)
    if (js_need or brightdata_proxy is None or brightdata_proxy == '' or html == '') and apikey is not None:
        html = send_request_zenrows_html(url, apikey, readability=False)
    return html

def send_request_zenrows(url, apikey):
    html = send_request_zenrows_html(url, apikey)
    result = get_async_future(soup_parser, html)
    # local_result = get_async_future(local_browser_reader, html)
    soup_html_parser_result = get_async_future(soup_html_parser, html)
    try:
        result = result.result()
    except Exception as e:
        result = None
        exc = traceback.format_exc()
        logger.error(
            f"[fetch_content_zenrows] link = {url}, Error in soup_parser with exception = {str(e)}\n{exc}")
    if result is not None and "title" in result and "text" in result and result["text"] is not None and result["text"] != "":
        return result
    # try:
    #     local_result = local_result.result()
    # except Exception as e:
    #     local_result = None
    #     exc = traceback.format_exc()
    #     logger.error(
    #         f"[fetch_content_brightdata] link = {url}, Error in local_browser_reader with exception = {str(e)}\n{exc}")
    try:
        soup_html_parser_result = soup_html_parser_result.result()
    except Exception as e:
        soup_html_parser_result = None
        exc = traceback.format_exc()
        logger.error(
            f"[fetch_content_brightdata] link = {url}, Error in soup_html_parser with exception = {str(e)}\n{exc}")

    # if local_result is not None and (result is None or len(result['text']) < len(local_result['text']) // 2):
    #     result = local_result
    if soup_html_parser_result is not None and (
            result is None or len(result['text']) < len(soup_html_parser_result['text']) // 4):
        result = soup_html_parser_result
    if result is not None and "text" in result and len(result["text"]) > 0:
        result["text"] = remove_bad_whitespaces(result["text"])
    # do the same for title
    if result is not None and "title" in result and len(result["title"]) > 0:
        result["title"] = remove_bad_whitespaces(result["title"])
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

def web_scrape_page(link, apikeys, web_search_tmp_marker_name=None):
    good_page_size = 300
    result = dict(text="", title="", link=link, error="")
    st = time.time()
    try:
        bright_data_result = get_async_future(fetch_content_brightdata, link, apikeys['brightdataUrl'])
        zenrows_service_result = None
        bright_data_playwright_result = None
        bright_data_selenium_result = None


        if random.random() <= 0.5:
            bright_data_playwright_result = get_async_future(browse_to_page_playwright, link)
        else:
            bright_data_selenium_result = get_async_future(browse_to_page_selenium, link)
        if random.random() <= 0.4:
            zenrows_service_result = get_async_future(send_request_zenrows, link, apikeys['zenrows'])
        # Also add bright data cdp fetch as a backup.
        result_from = "None"
        brightdata_exception = False
        zenrows_exception = False
        bright_data_playwright_exception = False
        bright_data_selenium_exception = False
        while time.time() - st < 20 and exists_tmp_marker_file(web_search_tmp_marker_name):

            if zenrows_service_result is not None and zenrows_service_result.done() and not zenrows_exception:
                try:
                    result = zenrows_service_result.result()
                    if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "zenrows"
                        break
                    elif result is None or len(result["text"].strip()) <= good_page_size or result["text"].strip() == DDOS_PROTECTION_STR:
                        zenrows_exception = True
                except Exception as e:
                    zenrows_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} zenrows_service_result failed with exception = {str(e)}, \n {exc}")
                if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "zenrows"
                    break
            if bright_data_playwright_result is not None and bright_data_playwright_result.done() and not bright_data_playwright_exception:
                try:
                    result = bright_data_playwright_result.result()
                    if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "bright_data_playwright"
                        break
                    elif result is None or len(result["text"].strip()) <= good_page_size or result["text"].strip() == DDOS_PROTECTION_STR:
                        bright_data_playwright_exception = True
                except Exception as e:
                    bright_data_playwright_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} bright_data_playwright_result failed with exception = {str(e)}, \n {exc}")
                if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "bright_data_playwright"
                    break
            if bright_data_selenium_result is not None and bright_data_selenium_result.done() and not bright_data_selenium_exception:
                try:
                    result = bright_data_selenium_result.result()
                    if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "bright_data_selenium"
                        break
                    elif result is None or len(result["text"].strip()) <= good_page_size or result["text"].strip() == DDOS_PROTECTION_STR:
                        bright_data_selenium_exception = True
                except Exception as e:
                    bright_data_selenium_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} bright_data_selenium_result failed with exception = {str(e)}, \n {exc}")
                if len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "bright_data_selenium"
                    break
            if bright_data_result is not None and bright_data_result.done() and not brightdata_exception and time.time() - st >= 19:
                try:
                    result = bright_data_result.result()
                    if result is not None and len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "brightdata"
                        break
                    elif result is None or len(result["text"].strip()) <= good_page_size or result["text"].strip() == DDOS_PROTECTION_STR:
                        brightdata_exception = True
                except Exception as e:
                    brightdata_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} bright_data_result failed with exception = {str(e)}, \n {exc}")
                if result is not None and len(result["text"].strip()) > good_page_size and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "brightdata"
                    break
            time.sleep(0.2)
        et = time.time() - st
        if result is None:
            result = {"text": "", "title": "", "link": link, "error": "No result"}
        time_logger.info(
            f"web_scrape_page:: Got result from local browser for link {link}, result len = {len(result['text'])}, time = {et:.2f}, result sample = {result['text'][:100]}")
        if len(result["text"].strip()) < good_page_size:
            result = {"text": "", "title": "", "link": link, "error": "Text too short"}
            logger.error(f"Text too short for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")
            raise Exception(f"Text too short for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")
        if result["text"].strip() == DDOS_PROTECTION_STR:
            result = {"text": "", "title": "", "link": link, "error": DDOS_PROTECTION_STR}
            logger.error(f"{DDOS_PROTECTION_STR} DDOS Protection for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")
            raise Exception(f"{DDOS_PROTECTION_STR} DDOS Protection for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")

    except Exception as e:
        exc = traceback.format_exc()
        logger.info(f"web_scrape_page:: failed with exception = {str(e)}, \n {exc}")
        # traceback.print_exc()
        result = {"text": "", "title": "", "link": link, "error": str(e)}
        # result = send_request_zenrows(link, apikeys['zenrows'])

    return result



if __name__=="__main__":
    # result = send_request_zenrows("https://platform.openai.com/docs/guides/images/usage", "0e1c6def95eadc85bf9eff4798f311231caca6b3")
    # print(result)
    # result = fetch_content_brightdata("https://platform.openai.com/docs/guides/images/usage", "http://brd-customer-hl_f6ac9ba2-zone-unblocker:39vo949l2tfh@brd.superproxy.io:22225")
    # print(result)
    result = web_scrape_page("https://towardsdatascience.com/clothes-classification-with-the-deepfashion-dataset-and-fast-ai-1e174cbf0cdc",
                             {"brightdataUrl": "http://brd-customer-hl_f6ac9ba2-zone-unblocker:39vo949l2tfh@brd.superproxy.io:22225",
                              "zenrows": "0e1c6def95eadc85bf9eff4798f311231caca6b3"})
    print(result)
