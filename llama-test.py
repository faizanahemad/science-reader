from text_generation import Client
import time
import requests
import functools
import requests

def request_patch(slf, *args, **kwargs):
    timeout = kwargs.pop('timeout', 120)
    return slf.request_orig(*args, **kwargs, timeout=timeout)

setattr(requests.sessions.Session, 'request_orig', requests.sessions.Session.request)
requests.sessions.Session.request = request_patch

class SessionTimeoutFix(requests.Session):

    def request(self, *args, **kwargs):
        timeout = kwargs.pop('timeout', 120)
        return super().request(*args, **kwargs, timeout=timeout)

requests.sessions.Session = SessionTimeoutFix

s = requests.Session()
s.request = functools.partial(s.request, timeout=300)
# client = Client("http://127.0.0.1:8080")
# st = time.time()
# print(client.generate("""User: I am going to Paris, what should I see?
# Assistant: 
# """, max_new_tokens=500).generated_text)
# et = time.time()
# print(et-st)

import requests
input = """User: I am going to Paris, what should I see?
Assistant: 
"""
url = "http://127.0.0.1:8080/generate"
data = {
    "inputs": input,
    "parameters": {
        "max_new_tokens": 200
    }
}
headers = {
    "Content-Type": "application/json"
}
st = time.time()

response = requests.post(url, json=data, headers=headers, timeout=300)
print(response.json()["generated_text"])
et = time.time()
print(et-st)