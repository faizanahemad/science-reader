import argparse

from common import get_first_last_parts

try:
    import ujson as json
except ImportError:
    import json
from typing import Iterable, List
import logging
import sys
import os
import requests
logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.getcwd(), "log.txt"))
    ]
)

# https://vllm.readthedocs.io/en/latest/getting_started/quickstart.html
# https://github.com/vllm-project/vllm/blob/main/examples/api_client.py

# https://huggingface.co/lmsys/vicuna-13b-v1.5-16k
# https://huggingface.co/Open-Orca/LlongOrca-7B-16k
# https://huggingface.co/conceptofmind/Hermes-LLongMA-2-13b-8k
# https://huggingface.co/Panchovix/WizardLM-33B-V1.0-Uncensored-SuperHOT-8k
# https://huggingface.co/TheBloke/Platypus-30B-SuperHOT-8K-fp16
# https://huggingface.co/kingbri/airo-llongma-2-13b-16k
# https://huggingface.co/emozilla/LLongMA-2-13b-storysummarizer

# https://huggingface.co/garage-bAInd/Platypus2-70B-instruct
# https://huggingface.co/upstage/Llama-2-70b-instruct-v2
# https://huggingface.co/TheBloke/Llama-2-70B-Chat-fp16
# https://huggingface.co/WizardLM/WizardLM-70B-V1.0
# https://huggingface.co/WizardLM/WizardCoder-15B-V1.0

def _post_http_request(prompt: str, api_url: str, temperature=0.7, max_tokens=None) -> requests.Response:
    if max_tokens is None:
        max_tokens = 8000 - (1.25 * len(prompt.split()))
    headers = {"User-Agent": "Science Reader"}
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

def get_streaming_vllm_response(prompt: str, api_url: str, temperature=0.7, max_tokens=2048, max_allowed_tokens=3000) -> Iterable[str]:
    prompt = get_first_last_parts(prompt, 2000, 20000)
    if isinstance(max_tokens, int):
        response = _post_http_request(prompt, api_url, temperature, max_tokens)
    else:
        response = _post_http_request(prompt, api_url, temperature)
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

def vllm_tgi_streaming_response_wrapper(prompt: str, api_urls: List[str], use_small_models, temperature=0.7, max_tokens=16) -> Iterable[str]:
    pass

if __name__ == "__main__":
    for s in get_streaming_vllm_response('Who is the president of the United States?\n', 'http://localhost:8000/generate'):
        print(s, end='')
