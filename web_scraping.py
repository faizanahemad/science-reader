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




def send_request_zenrows(url, apikey):
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
    et = time.time() - st
    logger.info(" ".join(['send_request_zenrows ', str(et), "\n", response.text[-100:]]))
    return soup_parser(response.text)
    


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
        context = browser.new_context(user_agent=random.choice(
            user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
        page = context.new_page()
        example_page = context.new_page()
        example_page.goto("https://www.example.com/")
        example_page.add_script_tag(
            url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
        page_pool.put([browser, page, example_page])  # Store the page in the pool
        
        
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
        context = browser.new_context(user_agent=random.choice(user_agents), ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
        page = context.new_page()
        example_page = context.new_page()
        example_page.goto("https://www.example.com/")
        example_page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
        thread_local.page_pool.put([browser, page, example_page])  # Store the page in the thread-local pool
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
        _, page, example_page = browser_resources
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
        traceback.print_exc()
        exc = traceback.format_exc()
        logger.error(
            f"Error in parse_page_content with exception = {str(e)}\n{exc}")
    finally:
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
        _, page, example_page = browser_resources
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
            # page = example_page
            page = example_page
            page.evaluate(
                f"""text=>document.body.innerHTML=text""", init_html)
            page.evaluate(f"""text=>document.title=text""", init_title)
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
        page_pool.put(browser_resources)
    logger.info(" ".join(['get_page_content ', str(time.time() - st), "\n", text[-100:]]))
    return {"text": text, "title": title}

for i in range(pool_size):
    _ = playwright_thread_executor.submit(playwright_thread_worker, "https://www.example.com/").result()

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
from requests.packages.urllib3.util.retry import Retry


def fetch_content_brightdata(url, brightdata_proxy):
    """
    Fetch the content of the webpage at the specified URL using a proxy.

    Parameters:
    url (str): The URL of the webpage to fetch.

    Returns:
    str: The content of the webpage.
    """

    # Define the proxies
    proxies = {"http": brightdata_proxy, "https": brightdata_proxy}

    # Create a session
    session = requests.Session()

    # Set up retries
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))

    # Make the request
    response = session.get(url, proxies=proxies, verify=False)
    html = response.content.decode('utf-8')
    result = local_browser_reader(html)
    readabilipy_result = send_request_readabilipy(link=url, html=html)
    goose3_result = send_request_goose3(link=url, html=html)
    trafilatura_result = send_request_trafilatura(link=url, html=html)

    if len(result['text']) < len(readabilipy_result['text'])//2:
        result = readabilipy_result
    if len(result['text']) < len(goose3_result['text'])//2:
        result = goose3_result
    if len(result['text']) < len(trafilatura_result['text'])//2:
        result = trafilatura_result

    # Return the response content
    return result


def local_browser_reader(html):
    st = time.time()
    result = playwright_thread_executor.submit(playwright_thread_reader, html).result()
    et = time.time() - st
    logger.info(" ".join(['local_browser_reader ', str(et), "\n", result['text'][-100:]]))
    return result

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
    logger.info(" ".join(['send_request_readabilipy ', str(et), "\n", html[-100:]]))
    article = simple_json_from_html_string(html)
    return {"text": article['plain_text'], "title": article['title']}

def send_request_goose3(link, html=None):
    from goose3 import Goose
    st = time.time()
    g = Goose()
    article = g.extract(url=link, raw_html=html)
    et = time.time() - st
    logger.info(" ".join(['send_request_goose3 ', str(et), "\n", article.cleaned_text[:100]]))
    return {"text": article.cleaned_text, "title": article.title}


def send_request_trafilatura(link, html=None):
    import trafilatura
    st = time.time()
    if html is None:
        html = trafilatura.fetch_url(link)
    logger.info(" ".join(['send_request_trafilatura ', str(et), "\n", downloaded[:100]]))
    result = trafilatura.extract(html)
    et = time.time() - st
    title = result.split('\n')[0]
    return {"text": result, "title": title}
