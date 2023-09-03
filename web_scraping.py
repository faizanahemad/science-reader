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
""".strip() + "var script=document.createElement('script');async function myFunc(){await new Promise((e=>setTimeout(e,2e3))),function e(){if('interactive'===document.readyState||'complete'===document.readyState){var t=document.createElement('script');t.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(t)}else setTimeout(e,1e3)}(),function e(){if('undefined'!=typeof Readability){var t=new Readability(document).parse();const e=document.getElementsByTagName('body')[0];e.innerHTML='';const n=document.createElement('div');n.id='custom_content';const i=document.createElement('div');i.id='title',i.textContent=t.title;const a=document.createElement('div');return a.id='textContent',a.textContent=t.textContent,n.appendChild(i),n.appendChild(a),e.appendChild(n),t}setTimeout(e,2e3)}()}script.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(script),myFunc();"
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
def close_playwright():
    global playwright_obj
    if playwright_obj:
        playwright_obj.stop()

atexit.register(close_playwright)

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
            
driver_pool = Queue()
def create_driver_pool(pool_size=8):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.wait import WebDriverWait
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support import expected_conditions as EC
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--headless')
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-sandbox")
    options.add_argument("--no-zygote")
    options.add_argument("--single-process")
    
    for _ in range(pool_size):
        chosen_user_agent = random.choice(user_agents)
        actual_options = copy.deepcopy(options)
        actual_options.add_argument(f"user-agent={chosen_user_agent}")
        driver = webdriver.Chrome(options=actual_options)
        driver_pool.put(driver)
        
readability_script_content_response = requests.get("https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
assert readability_script_content_response.status_code == 200
readability_script_content = readability_script_content_response.text


def get_page_content(link, playwright_cdp_link=None, timeout=10):
    # TODO: try local browser based extraction first, if blocked by ddos protection then use cdplink
    text = ''
    title = ''
    browser_resources = page_pool.get()
    browser = browser_resources[0]
    for context in browser.contexts:
        context.clear_cookies()
    driver = driver_pool.get()
    driver.delete_all_cookies()
    try:
        
        
        _, page, example_page = browser_resources
        url = link
        response = page.goto(url)
        if response.status == 403 or response.status == 429 or response.status == 302 or response.status == 301:
            raise Exception("Blocked by ddos protection")
        initial_base_url = urlparse(link).netloc
        final_base_url = urlparse(response.url).netloc
        if initial_base_url != final_base_url:
            raise Exception("Blocked by ddos protection")
        # example_page = browser.new_page(ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
        # example_page.goto("https://www.example.com/")

        try:
            page.add_script_tag(content=readability_script_content)
            page.wait_for_selector('body', timeout=timeout * 1000)
            page.wait_for_function(
                "() => typeof(Readability) !== 'undefined' && document.readyState === 'complete'", timeout=10000)
            while page.evaluate('document.readyState') != 'complete':
                pass
            result = page.evaluate(
                """(function execute(){var article = new Readability(document).parse();return article})()""")
        except Exception as e:
            # TODO: use playwright response modify https://playwright.dev/python/docs/network#modify-responses instead of example.com
            logger.warning(
                f"Trying playwright for link {link} after playwright failed with exception = {str(e)}")
            # traceback.print_exc()
            # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
            page.wait_for_selector('body', timeout=timeout * 1000)
            while page.evaluate('document.readyState') != 'complete':
                pass
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
                "() => typeof(Readability) !== 'undefined' && document.readyState === 'complete'", timeout=10000)
            # page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability-readerable.js")
            page.wait_for_selector('body', timeout=timeout*1000)
            while page.evaluate('document.readyState') != 'complete':
                pass
            result = page.evaluate(
                """(function execute(){var article = new Readability(document).parse();return article})()""")
            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])

    except Exception as e:
        from selenium.webdriver.support.wait import WebDriverWait
        traceback.print_exc()
        try:
            logger.debug(
                f"Trying selenium for link {link} after playwright failed with exception = {str(e)})")
            
            driver.get(link)
            initial_base_url = urlparse(link).netloc
            final_base_url = urlparse(driver.current_url).netloc
            if initial_base_url != final_base_url:
                raise Exception("Blocked by ddos protection")
            driver.execute_script("var meta = document.createElement('meta'); meta.httpEquiv = 'Content-Security-Policy'; meta.content = 'script-src * \'unsafe-inline\';'; document.getElementsByTagName('head')[0].appendChild(meta);")
            add_readability_script = f'''
            var script = document.createElement("script");
            script.type = "text/javascript";
            script.innerHTML = `{readability_script_content}`;
            document.head.appendChild(script);
            '''
            try:
                driver.execute_script(add_readability_script)
                while driver.execute_script('return document.readyState;') != 'complete':
                    pass

                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined' && document.readyState === 'complete';""")
                WebDriverWait(driver, timeout=timeout).until(
                    document_initialised)
                result = driver.execute_script(
                    """var article = new Readability(document).parse();return article""")
            except Exception as e:
                traceback.print_exc()
                # Instead of this we can also load the readability script directly onto the page by using its content rather than adding script tag
                init_title = driver.execute_script(
                    """return document.title;""")
                init_html = driver.execute_script(
                    """return document.body.innerHTML;""")
                driver.get("https://www.example.com/")
                logger.debug(
                    f"Loaded html and title into page with example.com as url")
                driver.execute_script(
                    """document.body.innerHTML=arguments[0]""", init_html)
                driver.execute_script(
                    """document.title=arguments[0]""", init_title)
                driver.execute_script(add_readability_script)
                while driver.execute_script('return document.readyState;') != 'complete':
                    pass

                def document_initialised(driver):
                    return driver.execute_script("""return typeof(Readability) !== 'undefined' && document.readyState === 'complete';""")
                WebDriverWait(driver, timeout=timeout).until(
                    document_initialised)
                result = driver.execute_script(
                    """var article = new Readability(document).parse();return article""")

            title = normalize_whitespace(result['title'])
            text = normalize_whitespace(result['textContent'])
        except Exception as e:
            pass
        finally:
            pass
    finally:
        page_pool.put(browser_resources)
        driver_pool.put(driver)
    return {"text": text, "title": title}


def send_local_browser(link):
    st = time.time()
    result = get_page_content(link)
    et = time.time() - st
    logger.info(" ".join(['send_local_browser ', str(et), "\n", result['text'][-100:]]))

create_page_pool()
create_driver_pool()