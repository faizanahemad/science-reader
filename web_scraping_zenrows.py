# pip install requests
from jsmin import jsmin
import requests

# https://minify-js.com/
add_readability_to_selenium = '''
var script = document.createElement('script');
script.src = 'https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js';
document.head.appendChild(script);
async function myFunc() {
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
}
myFunc();



'''

remove_script_tags = """
const scriptElements = document.querySelectorAll('body script');scriptElements.forEach(scriptElement => scriptElement.remove());const iframeElements = document.querySelectorAll('body iframe');iframeElements.forEach(iframeElement => iframeElement.remove());
""".strip() + "var script=document.createElement('script');async function myFunc(){await new Promise((e=>setTimeout(e,2e3))),function e(){if('interactive'===document.readyState||'complete'===document.readyState){var t=document.createElement('script');t.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(t)}else setTimeout(e,1e3)}(),function e(){if('undefined'!=typeof Readability){var t=new Readability(document).parse();const e=document.getElementsByTagName('body')[0];e.innerHTML='';const n=document.createElement('div');n.id='custom_content';const i=document.createElement('div');i.id='title',i.textContent=t.title;const a=document.createElement('div');return a.id='textContent',a.textContent=t.textContent,n.appendChild(i),n.appendChild(a),e.appendChild(n),t}setTimeout(e,2e3)}()}script.src='https://cdnjs.cloudflare.com/ajax/libs/readability/0.4.4/Readability.js',document.head.appendChild(script),myFunc();"


js = '''[{"wait":500},{"wait_for":"body"},{"evaluate":"''' + remove_script_tags + '''"}]'''


url = 'https://huggingface.co/blog/trl-peft'
apikey = '0e1c6def95eadc85bf9eff4798f311231caca6b3'
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
et = time.time() - st
print(response.text)
print(et)
