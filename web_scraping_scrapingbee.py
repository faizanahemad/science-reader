#  Install the Python Requests library:
# `pip install requests`
import requests
url = "https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.min.js"
response = requests.get(url)

if response.status_code == 200:
    js_content = response.text
    # print(js_content)
else:
    print("Error downloading the file")

remove_script_tags = """
const scriptElements = document.querySelectorAll('body script');
scriptElements.forEach(scriptElement => scriptElement.remove());
const iframeElements = document.querySelectorAll('body iframe');
iframeElements.forEach(iframeElement => iframeElement.remove());
"""

add_readability_to_selenium = '''
var script = document.createElement('script');
script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
document.head.appendChild(script);
async function myFunc() {
    await new Promise(r => setTimeout(r, 2000));
}
myFunc();

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





js = '{"instructions":[{"wait_for":"body"},{"evaluate":"' + remove_script_tags + '"}]}'
def send_request():
    response = requests.get(
        url='https://app.scrapingbee.com/api/v1/',
        params={
            'api_key': 'PFZ8KTWZ2GBQQIHUEY9Q1EHLVHATZ98C3NNXFPEBMU0S90NK5QHRWN12IAYTURYRUZ645OVUUEUCEPBO',
            'url': 'https://huggingface.co/blog/trl-peft',
            'wait_for': 'body',
            'block_ads': 'true',
            'js_scenario': js,
        },

    )
    print('Response HTTP Status Code: ', response.status_code, type(response.content))
    print('Response HTTP Response Body: ', response.content.decode('utf-8'))


send_request()
