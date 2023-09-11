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
"""


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

payload = {
    "url": "https://geonode.com/",
    "configurations": {
        "js_render": True,
        "is_json_response": False,
        "keep_headers": False,
        "debug": False,
        "block_resources": False,
        "response_format": "json",
        "mode": "SPA",
        "waitForSelector": "#buttonId",
        "device_type": "desktop",
        "country_code": "tr",
        "cookies": [],
        "localStorage": {},
        "HTMLMinifier": {
            "useMinifier": False
        },
        "collect_data_from_requests": True,
        "optimizations": {},
        "retries": {},
        "proxy": {},
        "screenshot": {},
        "viewport": {},
        "js_scenario": {
            "actions": [],
        },
    }
}


import requests
url = "https://scraper.geonode.com/api/scraper/scrape/realtime"
username = "geonode_yRhoqy3DJt"
password = "<hidden>"
# Replace with the URL you want to scrape
target_url = "https://huggingface.co/blog/trl-peft"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"ApiKey {username}{password}"
}

data = {
    "url": target_url,
    "configurations": {
        "js_render": True,
        "is_json_response": False
    }
}

response = requests.post(url, json=data, headers=headers)

if response.status_code == 200:
    scraped_data = response.json()
    print(scraped_data)
else:
    print(response.text)
