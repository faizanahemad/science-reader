import atexit
import copy
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
js_warning_pattern_v2 = re.compile(r'javascript(?:(?!\n).){0,100}?enable', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v3 = re.compile(r'javascript(?:(?!\n).){0,100}?required', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v4 = re.compile(r'javascript(?:(?!\n).){0,100}?disabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v5 = re.compile(r'javascript(?:(?!\n).){0,100}?not enabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v6 = re.compile(r'js(?:(?!\n).){0,100}?not enabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v7 = re.compile(r'js(?:(?!\n).){0,100}?disabled', re.IGNORECASE | re.DOTALL)
js_warning_pattern_v8 = re.compile(r'js(?:(?!\n).){0,100}?required', re.IGNORECASE | re.DOTALL)
def check_js_needed(html):
    js_warn = js_warning_pattern_v1.search(html) or js_warning_pattern_v2.search(html) or js_warning_pattern_v3.search(html) or js_warning_pattern_v4.search(html) or js_warning_pattern_v5.search(html) or js_warning_pattern_v6.search(html) or js_warning_pattern_v7.search(html) or js_warning_pattern_v8.search(html)
    # js_warning_pattern_v4 = re.compile(r'javascript.{0,100}?disabled', re.IGNORECASE | re.DOTALL) # js_warning_pattern_v4 = re.compile(r'javascript(?:.|\n){0,100}?disabled', re.IGNORECASE)
    return bool(noscript_pattern.search(html)) or bool(script_pattern_inside_header.search(html)) or js_warn

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)

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
""".strip() + "var script=document.createElement('script');async function myFunc(){await new Promise((e=>setTimeout(e,1e3))),function e(){if('interactive'===document.readyState||'complete'===document.readyState){var t=document.createElement('script');t.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(t)}else setTimeout(e,1e3)}(),function e(){if('undefined'!=typeof Readability){var t=new Readability(document).parse();const e=document.getElementsByTagName('body')[0];e.innerHTML='';const n=document.createElement('div');n.id='custom_content';const i=document.createElement('div');i.id='title',i.textContent=t.title;const a=document.createElement('div');return a.id='textContent',a.textContent=t.textContent,n.appendChild(i),n.appendChild(a),e.appendChild(n),t}setTimeout(e,1e3)}()}script.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(script),myFunc();"
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
page_pool = Queue()
playwright_obj = None

# Thread-local storage for Playwright resources
thread_local = threading.local()
def init_thread_local_playwright():
    global thread_local
    if not hasattr(thread_local, "playwright_obj"):
        thread_local.playwright_obj = create_page_pool_thread(pool_size=1)
        atexit.register(close_playwright_thread)
        
def close_playwright_thread():
    if hasattr(thread_local, "playwright_obj"):
        thread_local.playwright_obj.stop()
        
        

def close_playwright():
    global playwright_obj
    if playwright_obj:
        playwright_obj.stop()

atexit.register(close_playwright)

page_pool = None
playwright_obj = None
pool_size = 16
playwright_executor = ProcessPoolExecutor(max_workers=pool_size)

def init_playwright_resources():
    global page_pool, playwright_obj
    page_pool = Queue()
    if not playwright_obj:
        create_page_pool(pool_size=1)
        atexit.register(close_playwright)
        
def playwright_worker(link):
    # Initialize Playwright resources, if not already initialized
    init_playwright_resources()
    
    # Here, page_pool and playwright_obj are available and initialized
    result = get_page_content(link)
    
    return result

def playwright_thread_worker(link):
    init_thread_local_playwright()
    result = get_page_content(link)
    return result

def playwright_thread_reader(html):
    init_thread_local_playwright()
    result = parse_page_content(html)
    return result

playwright_thread_executor = ThreadPoolExecutor(max_workers=pool_size)
        

def create_page_pool(pool_size=16):
    from playwright.sync_api import sync_playwright
    global playwright_obj  # Declare it as global so we can modify it
    playwright_obj = sync_playwright().start()
    p = playwright_obj
    for _ in range(pool_size):
        browser = p.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials", ])
        page = browser.new_page(user_agent=random.choice(
            user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
        page_pool.put([browser, page, 0])  # Store the page in the pool
        
        
def create_page_pool_thread(pool_size=1):
    from playwright.sync_api import sync_playwright
    global thread_local  # Declare it as global so we can modify it

    if not hasattr(thread_local, 'page_pool'):
        thread_local.page_pool = Queue()

    if not hasattr(thread_local, 'playwright_obj'):
        thread_local.playwright_obj = sync_playwright().start()

    p = thread_local.playwright_obj
    for _ in range(pool_size):
        browser = p.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials"])
        page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
        page.set_content('<html><body></body></html>')
        thread_local.page_pool.put([browser, page, 0])  # Store the page in the thread-local pool
    return thread_local.playwright_obj

            
        
readability_script_content_response = requests.get("https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
assert readability_script_content_response.status_code == 200
readability_script_content = readability_script_content_response.text

# https://github.com/alan-turing-institute/ReadabiliPy
# https://trafilatura.readthedocs.io/en/latest/
# https://github.com/goose3/goose3


def parse_page_content(html):
    text = ''
    title = ''
    global thread_local
    if hasattr(thread_local, 'page_pool'):
        page_pool = thread_local.page_pool
    st = time.time()
    browser_resources = page_pool.get()
    browser = browser_resources[0]
    for context in browser.contexts:
        context.clear_cookies()
    try:
        _, page, _ = browser_resources
        page.set_content(html)
        page.add_script_tag(content=readability_script_content)
        page.wait_for_function(
            "() => typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')",
            timeout=10000)
        result = page.evaluate(
            """(function execute(){var article = new Readability(document).parse();return article})()""")
        title = normalize_whitespace(result['title'])
        text = normalize_whitespace(result['textContent'])
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(
            f"Error in parse_page_content with exception = {str(e)}\n{exc}")
    finally:
        # Set empty html context
        browser_resources[2] += 1
        if browser_resources[2] % 1000 == 0:
            browser.close()
            browser = playwright_obj.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials"])
            page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            browser_resources = [browser, page, 0]
        if browser_resources[2] % 100 == 0:
            page.close()
            page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            browser_resources = [browser, page, 0]
        page.goto('about:blank')
        page.set_content('<html><body></body></html>')
        page_pool.put(browser_resources)
    logger.info(" ".join(['parse_page_content ', str(time.time() - st), "\n", text[-100:]]))
    return {"text": text, "title": title}



def get_page_content(link, playwright_cdp_link=None, timeout=2):
    text = ''
    title = ''
    global thread_local
    if hasattr(thread_local, 'page_pool'):
        page_pool = thread_local.page_pool
    st = time.time()
    browser_resources = page_pool.get()
    browser = browser_resources[0]
    for context in browser.contexts:
        context.clear_cookies()
    try:
        _, page, _ = browser_resources
        url = link
        response = page.goto(url,  timeout = 60000)
        if response.status == 403 or response.status == 429 or response.status == 302 or response.status == 301:
            text = DDOS_PROTECTION_STR
            raise Exception(DDOS_PROTECTION_STR)
        initial_base_url = urlparse(link).netloc
        final_base_url = urlparse(response.url).netloc
        if initial_base_url != final_base_url:
            text = DDOS_PROTECTION_STR
            raise Exception(DDOS_PROTECTION_STR)

        try:
            page.add_script_tag(content=readability_script_content)
            page.wait_for_function(
                "() => typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')", timeout=10000)
            result = page.evaluate(
                """(function execute(){var article = new Readability(document).parse();return article})()""")
            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])
        except Exception as e:

            exc = traceback.format_exc()
            # TODO: use playwright response modify https://playwright.dev/python/docs/network#modify-responses instead of example.com
            logger.warning(
                f"Trying playwright for link {link} after playwright failed with exception = {str(e)}\n{exc}")
            # traceback.print_exc()
            # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
            init_html = page.evaluate(
                """(function e(){return document.body.innerHTML})()""")
            init_title = page.evaluate(
                """(function e(){return document.title})()""")
            page.goto('about:blank')
            page.set_content('<html><body></body></html>')
            page.evaluate(
                f"""text=>document.body.innerHTML=text""", init_html)
            page.evaluate(f"""text=>document.title=text""", init_title)
            page.add_script_tag(content=readability_script_content)
            logger.debug(
                f"Loaded html and title into page with example.com as url")
            page.add_script_tag(content=readability_script_content)
            page.wait_for_function(
                "() => typeof(Readability) !== 'undefined' && (document.readyState === 'complete' || document.readyState === 'interactive')", timeout=10000)
            # page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
            result = page.evaluate(
                """(function execute(){var article = new Readability(document).parse();return article})()""")
            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])

    except Exception as e:
        traceback.print_exc()
        exc = traceback.format_exc()
        logger.error(
            f"Error in get_page_content with exception = {str(e)}\n{exc}")
    finally:
        browser_resources[2] += 1
        if browser_resources[2] % 1000 == 0:
            browser.close()
            browser = playwright_obj.chromium.launch(headless=True, args=['--disable-web-security', "--disable-site-isolation-trials"])
            page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            browser_resources = [browser, page, 0]
        if browser_resources[2] % 100 == 0:
            page.close()
            page = browser.new_page(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
            browser_resources = [browser, page, 0]
        page.goto('about:blank')
        page.set_content('<html><body></body></html>')
        page_pool.put(browser_resources)
    logger.info(" ".join(['get_page_content ', str(time.time() - st), "\n", text[-100:]]))
    return {"text": text, "title": title}

# for i in range(pool_size):
#     _ = playwright_thread_executor.submit(playwright_thread_worker, "https://www.example.com/").result()

def send_local_browser(link):
    st = time.time()
    result = playwright_thread_executor.submit(playwright_thread_worker, link).result()
    et = time.time() - st
    logger.info(" ".join(['send_local_browser ', str(et), "\n", result['text'][-100:]]))
    return result

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

def fetch_content_brightdata_html(url, brightdata_proxy):
    """
    Fetch the content of the webpage at the specified URL using a proxy.

    Parameters:
    url (str): The URL of the webpage to fetch.

    Returns:
    str: The content of the webpage.
    """

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    # Define the proxies
    proxies = {"http": brightdata_proxy, "https": brightdata_proxy}

    # Create a session
    session = requests.Session()

    # Set up retries
    retries = Retry(total=1, backoff_factor=2, status_forcelist=[400, 404, 500, 501, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))

    # Make the request
    response = session.get(url, proxies=proxies, verify=False)
    try:
        html = response.content.decode('utf-8')
    except:
        html = response.text
    return html

def fetch_content_brightdata(url, brightdata_proxy):
    html = fetch_content_brightdata_html(url, brightdata_proxy)
    js_need = check_js_needed(html)
    result = None
    goose3_result = None
    trafilatura_result = None
    soup_html_parser_result = None
    try:
        result = local_browser_reader(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[fetch_content_brightdata] link = {url}, Error in local_browser_reader with exception = {str(e)}\n{exc}")
    try:
        goose3_result = send_request_goose3(link=url, html=html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[fetch_content_brightdata] link = {url}, Error in send_request_goose3 with exception = {str(e)}\n{exc}")
    try:
        trafilatura_result = send_request_trafilatura(link=url, html=html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[fetch_content_brightdata] link = {url}, Error in send_request_trafilatura with exception = {str(e)}\n{exc}")
    try:
        soup_html_parser_result = soup_html_parser(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[fetch_content_brightdata] link = {url}, Error in soup_html_parser with exception = {str(e)}\n{exc}")


    if goose3_result is not None and (result is None or len(result['text']) < len(goose3_result['text'])//2):
        result = goose3_result
    if trafilatura_result is not None and (result is None or len(result['text']) < len(trafilatura_result['text'])//2):
        result = trafilatura_result
    if soup_html_parser_result is not None and (result is None or len(result['text']) < len(soup_html_parser_result['text']) // 4):
        result = soup_html_parser_result

    # Return the response content
    return result

def send_request_zenrows_html(url, apikey):
    js = '''[{"wait":500},{"wait_for":"body"},{"evaluate":"''' + remove_script_tags + '''"}]'''

    params = {
        'url': url,
        'apikey': apikey,
        'js_render': 'true',
        'wait_for': 'body',
        'block_resources': 'image,media',
        'js_instructions': js,
    }
    import time
    st = time.time()
    response = requests.get('https://api.zenrows.com/v1/', params=params)
    if response.status_code != 200:
        raise Exception(
            f"Error in zenrows with status code {response.status_code}")
        return {
            'title': "",
            'text': ""
        }
    if response is None or response.text is None:
        return {
            'title': "",
            'text': ""
        }
    et = time.time() - st
    logger.info(" ".join(['send_request_zenrows ', str(et), "\n", response.text[-100:]]))
    html = response.text
    return html

def fetch_html(url, apikey=None, brightdata_proxy=None):
    html = ''
    if brightdata_proxy is not None:
        html = fetch_content_brightdata_html(url, brightdata_proxy)
    js_need = check_js_needed(html)
    if (js_need or brightdata_proxy is None or brightdata_proxy == '' or html == '') and apikey is not None:
        html = send_request_zenrows_html(url, apikey)
    return html

def send_request_zenrows(url, apikey):
    html = send_request_zenrows_html(url, apikey)
    result = None
    goose3_result = None
    trafilatura_result = None
    soup_html_parser_result = None
    try:
        result = soup_html_parser(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[send_request_zenrows] link = {url}, Error in soup_html_parser with exception = {str(e)}\n{exc}")
    if result is not None and "title" in result and "text" in result and result["text"] is not None and result["text"] != "":
        return result
    try:
        result = local_browser_reader(html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[send_request_zenrows] link = {url}, Error in local_browser_reader with exception = {str(e)}\n{exc}")
    try:
        goose3_result = send_request_goose3(link=url, html=html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[send_request_zenrows] link = {url}, Error in send_request_goose3 with exception = {str(e)}\n{exc}")
    try:
        trafilatura_result = send_request_trafilatura(link=url, html=html)
    except Exception as e:
        exc = traceback.format_exc()
        logger.error(f"[send_request_zenrows] link = {url}, Error in send_request_trafilatura with exception = {str(e)}\n{exc}")

    if goose3_result is not None and (result is None or len(result['text']) < len(goose3_result['text']) // 2):
        result = goose3_result
    if trafilatura_result is not None and (result is None or len(result['text']) < len(trafilatura_result['text']) // 2):
        result = trafilatura_result
    # Return the response content
    return result

def local_browser_reader(html):
    st = time.time()
    result = playwright_thread_executor.submit(playwright_thread_reader, html).result()
    et = time.time() - st
    logger.debug(" ".join(['local_browser_reader ', str(et), "\n", result['text'][-100:]]))
    return result

def soup_html_parser(html):
    from bs4 import BeautifulSoup, SoupStrainer
    soup = BeautifulSoup(html, 'html.parser')
    # Extract the title
    title = soup.title.string if soup.title else ''
    # Remove links and other unwanted elements
    for link in soup.find_all('a'):
        link.decompose()

    # Remove header and footer elements
    for header in soup.find_all(['header', 'footer']):
        header.decompose()
    content_elements = soup.find_all(['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    content_text = '\n '.join(element.get_text() for element in content_elements)
    return {"text": content_text, "title": title}

def send_request_readabilipy(link, html=None):
    from readabilipy import simple_json_from_html_string
    st = time.time()
    if html is None:
        response = requests.get(link, verify=False, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'})
        if response.status_code not in [200, 201, 202, 303, 302, 301]:
            logger.error(
                f"Error in readabilipy with status code {response.status_code}, link = {link}, response = {response.text}")
            return {"text": '', "title": ''}
        html = response.text

    et = time.time() - st
    logger.debug(" ".join(['send_request_readabilipy ', str(et), "\n", html[-100:]]))
    article = simple_json_from_html_string(html)
    return {"text": article['plain_text'], "title": article['title']}

def send_request_goose3(link, html=None):
    from goose3 import Goose
    st = time.time()
    g = Goose()
    article = g.extract(url=link, raw_html=html)
    et = time.time() - st
    logger.debug(" ".join(['send_request_goose3 ', str(et), "\n", article.cleaned_text[:100]]))
    return {"text": article.cleaned_text, "title": article.title}


def send_request_trafilatura(link, html=None):
    import trafilatura
    from trafilatura.settings import DEFAULT_CONFIG
    DEFAULT_CONFIG.set('DEFAULT', 'EXTRACTION_TIMEOUT', '0')
    st = time.time()
    if html is None:
        html = trafilatura.fetch_url(link)
    et = time.time() - st
    result = trafilatura.extract(html)
    title = result.split('\n')[0]
    logger.debug(" ".join(['send_request_trafilatura ', str(et), "\n", title[:100]]))
    return {"text": result, "title": title}


def web_scrape_page(link, apikeys):
    result = dict(text="", title="", link=link, error="")
    try:
        bright_data_result = None
        zenrows_service_result = None
        if random.random() < 0.7:
            bright_data_result = get_async_future(fetch_content_brightdata, link, apikeys['brightdataUrl'])
        else:
            zenrows_service_result = get_async_future(send_request_zenrows, link, apikeys['zenrows'])

        # Also add bright data cdp fetch as a backup.
        st = time.time()
        result_from = "None"
        brightdata_exception = False
        zenrows_exception = False
        while time.time() - st < 45:
            if zenrows_service_result is not None and zenrows_service_result.done() and not zenrows_exception:
                try:
                    result = zenrows_service_result.result()
                    if len(result["text"].strip()) > 100 and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "zenrows"
                        break
                    elif len(result["text"].strip()) <= 100 or result["text"].strip() == DDOS_PROTECTION_STR:
                        zenrows_exception = True
                except Exception as e:
                    zenrows_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} zenrows_service_result failed with exception = {str(e)}, \n {exc}")
                if len(result["text"].strip()) > 100 and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "zenrows"
                    break
            if (time.time() - st > 8 or zenrows_exception) and bright_data_result is None:
                bright_data_result = get_async_future(fetch_content_brightdata, link, apikeys['brightdataUrl'])
            elif (time.time() - st > 8 or brightdata_exception) and zenrows_service_result is None:
                zenrows_service_result = get_async_future(send_request_zenrows, link, apikeys['zenrows'])
            if bright_data_result is not None and bright_data_result.done() and not brightdata_exception:
                try:
                    result = bright_data_result.result()
                    if len(result["text"].strip()) > 100 and result["text"].strip() != DDOS_PROTECTION_STR:
                        result_from = "brightdata"
                        break
                    elif len(result["text"].strip()) <= 100 or result["text"].strip() == DDOS_PROTECTION_STR:
                        brightdata_exception = True
                except Exception as e:
                    brightdata_exception = True
                    exc = traceback.format_exc()
                    logger.info(
                        f"web_scrape_page:: {link} bright_data_result failed with exception = {str(e)}, \n {exc}")
                if len(result["text"].strip()) > 100 and result["text"].strip() != DDOS_PROTECTION_STR:
                    result_from = "brightdata"
                    break
            time.sleep(0.1)
        logger.info(
            f"web_scrape_page:: Got result from local browser for link {link}, result len = {len(result['text'])}, result sample = {result['text'][:100]}")
        if len(result["text"].strip()) < 100:
            result = {"text": "", "title": "", "link": link, "error": "Text too short"}
            logger.error(f"Text too short for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")
        if result["text"].strip() == DDOS_PROTECTION_STR:
            result = {"text": "", "title": "", "link": link, "error": DDOS_PROTECTION_STR}
            logger.error(f"{DDOS_PROTECTION_STR} DDOS Protection for {link} from {result_from}, result len = {len(result['text'])} and result sample = {result['text'][:10]}")

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
