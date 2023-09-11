import json
import requests
import time

remove_script_tags = """
const scriptElements = document.querySelectorAll('body script');scriptElements.forEach(scriptElement => scriptElement.remove());const iframeElements = document.querySelectorAll('body iframe');iframeElements.forEach(iframeElement => iframeElement.remove());
""".strip() + "var script=document.createElement('script');async function myFunc(){await new Promise((e=>setTimeout(e,2e3))),function e(){if('interactive'===document.readyState||'complete'===document.readyState){var t=document.createElement('script');t.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(t)}else setTimeout(e,1e3)}(),function e(){if('undefined'!=typeof Readability){var t=new Readability(document).parse();const e=document.getElementsByTagName('body')[0];e.innerHTML='';const n=document.createElement('div');n.id='custom_content';const i=document.createElement('div');i.id='title',i.textContent=t.title;const a=document.createElement('div');return a.id='textContent',a.textContent=t.textContent,n.appendChild(i),n.appendChild(a),e.appendChild(n),t}setTimeout(e,2e3)}()}script.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(script),myFunc();"


url = "https://api.scrape-it.cloud/scrape"
payload = {
    "url": "https://huggingface.co/blog/trl-peft",
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
    "x-api-key": "12614849-6d81-4632-9e00-63bda2e1c996",
    "Content-Type": "application/json"
}

st = time.time()
response = requests.post(url, data=json.dumps(payload), headers=headers)
et = time.time() - st
data = response.json()['scrapingResult']['content']
print(data)
print(type(data))
print(et)
