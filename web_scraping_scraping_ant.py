import base64
import http.client
import time

import requests

url = "https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.min.js"
response = requests.get(url)

if response.status_code == 200:
    js_content = response.text
    # print(js_content)
else:
    print("Error downloading the file")
    
readability_append_custom_content = f"""
const body = document.getElementsByTagName('body')[0];
const helloDiv = document.createElement('div');
helloDiv.textContent = 'hello';
body.appendChild(helloDiv);
"""

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
print(remove_script_tags) 
exit()


next_readability_append_custom_content = f"""
function waitForCondition(condition, callback, interval = 100) {{
  const intervalId = setInterval(() => {{
    if (condition()) {{
        const body = document.getElementsByTagName('body')[0];
        const helloDiv = document.createElement('div');
        helloDiv.textContent = 'Satisfied condition';
        body.appendChild(helloDiv);
        clearInterval(intervalId);
        callback();
    }}
  }}, interval);
}}

waitForCondition(() => typeof(Readability) !== 'undefined', () => {{

}});
"""
# print(readability_append_custom_content)
# exit()


remove_script_tags = base64.b64encode(remove_script_tags.encode()).decode()


    

st = time.time()
conn = http.client.HTTPSConnection("api.scrapingant.com")
conn.request("GET", "/v2/general?url=https%3A%2F%2Fhuggingface.co%2Fblog%2Ftrl-peft&x-api-key=15ff4478f8914f819ae74fdbc9cacb7a&proxy_country=US&wait_for_selector=body&js_snippet="+remove_script_tags)

res = conn.getresponse()
data = res.read()

html_content = data.decode("utf-8")
print(html_content)
it_before_playwright = time.time()


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
        'textContent': text_content_div.text
    }

    return my_dict

soup_parser(html_content)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(ignore_https_errors=True, java_script_enabled=True, bypass_csp=True)
    page.set_content(html_content)
    page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js")
    page.wait_for_function("() => typeof(Readability) !== 'undefined' && document.readyState === 'complete'", timeout=10000)
    result = page.evaluate("""(function execute(){var article = new Readability(document).parse();return article})()""")
et = time.time()
# print(result)
print(it_before_playwright-st)
print(et-st)

