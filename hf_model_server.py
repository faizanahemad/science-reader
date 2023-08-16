from flask import Flask, request, Response, jsonify, stream_with_context
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig, pipeline, TextStreamer, TextIteratorStreamer
import torch
import argparse
import logging
from threading import Thread
import sys
import os
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

app = Flask(__name__)


def load_model(dtype, repo_id):
    # Set up bnb_config based on dtype
    if dtype == 'int8':
        bnb_config = dict(load_in_4bit=False, load_in_8bit=True)
    elif dtype == 'int4':
        bnb_config = dict(load_in_4bit=True, load_in_8bit=False)
    else:
        bnb_config = dict()

    if repo_id in ["meta-llama/Llama-2-70b-chat-hf", "meta-llama/Llama-2-13b-chat-hf"] and len(bnb_config) > 0:
        config = AutoConfig.from_pretrained(repo_id, pretraining_tp=1)
    else:
        config = AutoConfig.from_pretrained(repo_id)

    torch_dtype = torch.float16 if dtype == 'float16' else torch.bfloat16 if dtype == 'bfloat16' else torch.float32

    if len(bnb_config) > 0:
        model = AutoModelForCausalLM.from_pretrained(repo_id, device_map="auto", use_auth_token=True, config=config,
                                                     **bnb_config)
    else:
        model = AutoModelForCausalLM.from_pretrained(repo_id, device_map="auto", use_auth_token=True,
                                                     torch_dtype=torch_dtype, config=config)

    for p in model.parameters():
        p.requires_grad = False
    tokenizer = AutoTokenizer.from_pretrained(repo_id, use_fast=True)
    return {"model": model, "tokenizer": tokenizer, "pipeline": pipeline("text-generation", model=model, tokenizer=tokenizer, device_map="auto", use_auth_token=True,
                    max_length=4096)}


@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    prompt = data['text']
    generate_kwargs = data.get('generate_kwargs', {"max_new_tokens": 200, "do_sample": False})
    model = pipe["model"]
    tokenizer = pipe["tokenizer"]
    pipeline = pipe["pipeline"]
    inputs = tokenizer([prompt], return_tensors="pt")
    streamer = TextIteratorStreamer(tokenizer)
    thread = Thread(target=model.generate, kwargs=dict(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], **generate_kwargs))
    thread.start()
    def streaming_builder():
        for chunk in streamer:
            yield chunk
        thread.join()
    return Response(stream_with_context(streaming_builder()), content_type='text/plain')


import requests


class LLMAClient:
    def __init__(self, server_url):
        self.server_url = server_url

    def __call__(self, text, temperature=0.7, max_tokens=None):
        # Form the JSON payload
        payload = {
            'text': text,
            'generate_kwargs': {
                'temperature': temperature
            }
        }
        if max_tokens is not None:
            payload['generate_kwargs']['max_new_tokens'] = max_tokens

        # Make the request to the server
        response = requests.post(f'{self.server_url}/generate', json=payload, stream=True)

        # Buffer the response until we reach the end of the input prompt
        buffer = ''
        for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
            buffer += chunk
            if buffer.endswith(text):  # End of prompt reached
                break

        # Stream the remaining response
        for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
            yield chunk


# Example usage
server_url = 'http://localhost:8003'
client = LLMAClient(server_url)
for generated_text in client('How are you?', temperature=0.9):
    print(generated_text)

if __name__ == "__main__":
    app = Flask(__name__)

    # Load model on app startup
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument("--dtype", choices=['bfloat16', 'float16', 'int8', 'int4'])
    parser.add_argument("--model")
    args = parser.parse_args()
    pipe = load_model(args.dtype, args.model)
    app.run(port=args.port, threaded=True, processes=1)
