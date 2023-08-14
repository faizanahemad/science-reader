import argparse
import json
from typing import Iterable, List

import requests

# https://vllm.readthedocs.io/en/latest/getting_started/quickstart.html
# https://github.com/vllm-project/vllm/blob/main/examples/api_client.py

# https://huggingface.co/lmsys/vicuna-13b-v1.5-16k
# https://huggingface.co/Open-Orca/LlongOrca-7B-16k
# https://huggingface.co/conceptofmind/Hermes-LLongMA-2-13b-8k

def _post_http_request(prompt: str, api_url: str, temperature=0.7, max_tokens=16) -> requests.Response:
    headers = {"User-Agent": "Test Client"}
    pload = {
        "prompt": prompt,
        "n": 1,
        "use_beam_search": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    response = requests.post(api_url, headers=headers, json=pload, stream=True)
    return response

def get_streaming_vllm_response(prompt: str, api_url: str, temperature=0.7, max_tokens=16) -> Iterable[str]:
    response = _post_http_request(prompt, api_url, temperature, max_tokens)
    prior = "" + prompt
    for chunk in response.iter_lines(chunk_size=8192,
                                     decode_unicode=False,
                                     delimiter=b"\0"):
        if chunk:
            data = json.loads(chunk.decode("utf-8"))
            output = data["text"][0]

            output = output.replace(prior, "")
            prior += output
            yield output


if __name__ == "__main__":
    for s in get_streaming_vllm_response('Who is the president ', 'http://localhost:8000/generate'):
        print(s, end='')
