# pip install -U --force-reinstall --no-deps git+https://github.com/huggingface/transformers accelerate bitsandbytes tokenizers datasets
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig
from transformers import pipeline
import time
import torch
# 70B meta model doesn't work in 4bit and 8bit currently
# https://github.com/TimDettmers/bitsandbytes/issues/610
# repo_id = "meta-llama/Llama-2-70b-chat-hf"

# select one of the following three lines, depending on which model you want to use
repo_id = "TheBloke/Llama-2-70B-Chat-fp16"
repo_id = "meta-llama/Llama-2-13b-chat-hf"
repo_id = "meta-llama/Llama-2-7b-chat-hf"

# For quantization, use the following config, if not quantizing, make it an empty dict.
# bnb_config = dict(load_in_4bit=True)
# bnb_config = dict(load_in_8bit=True)
bnb_config = dict()

# config = AutoConfig.from_pretrained(repo_id, pretraining_tp=1)

# rope_scaling={"type": "dynamic", "factor": 2.0} -> to increase context length support to 8K
if repo_id == "meta-llama/Llama-2-70b-chat-hf" or repo_id == "meta-llama/Llama-2-13b-chat-hf" and len(bnb_config) > 0:
    assert ("load_in_4bit" in bnb_config and bnb_config["load_in_4bit"] == True) or ("load_in_8bit" in bnb_config and bnb_config["load_in_8bit"] == True)
    config = AutoConfig.from_pretrained(repo_id, pretraining_tp=1)
else:
    config = AutoConfig.from_pretrained(repo_id)
if len(bnb_config) > 0:
    model = AutoModelForCausalLM.from_pretrained(repo_id, device_map="auto", use_auth_token=True, config=config, **bnb_config)
else:
    model = AutoModelForCausalLM.from_pretrained(repo_id, device_map="auto", use_auth_token=True, torch_dtype=torch.float16, config=config,)

for p in model.parameters():
    p.requires_grad = False
tokenizer = AutoTokenizer.from_pretrained(repo_id, use_fast=True)
generate_kwargs = {"max_new_tokens":100, "do_sample":False}

## using model generate
question = "User:\nHow to kill a python process using terminal when the process refuses to shut down itself? Provide a brief and short answer.\nAssistant:\n"
model_inputs = tokenizer(question, return_tensors="pt").to("cuda:0")
st = time.time()
gen_out = model.generate(**model_inputs, **generate_kwargs)
print(len(gen_out[0]), "\n", tokenizer.decode(gen_out[0], skip_special_tokens=True))
et = time.time()
print(et-st)

# 7B at fp16 = 3.7s (no quantization) 1xA100 135 Tokens
# 7B at 8bit = 15.1s (quantization) 1xA100 135 tokens
# 7B at 4bit = 4.91s (quantization) 1xA100 135 tokens
# 13B at fp16 = 6.7s (no quantization) 1xA100
# 13B at 4bit = 6.1s (quantization) 1xA100
# 13B at 8bit = 19.2s (quantization) 1xA100

## using pipeline
st = time.time()
pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, device_map="auto", use_auth_token=True, max_length=4096)
print(pipe(question)[0]["generated_text"])
et = time.time()
print(et-st)