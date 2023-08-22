# Ngingx config
`sudo vi /etc/nginx/sites-available/science-reader`

```
server {                                                                                                                                                                                 
    listen 443 ssl;
    server_name sci-tldr.pro;

    ssl_certificate /root/science-reader/cert-ext.pem;
    ssl_certificate_key /root/science-reader/key-ext.pem;

    location / { 
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }   
}
```

`sudo ln -s /etc/nginx/sites-available/science-reader /etc/nginx/sites-enabled/`

`sudo systemctl restart nginx`

`sudo systemctl reload nginx`

# Start server
`screen -S science-reader`

`SECRET_KEY=XX GOOGLE_CLIENT_ID=XXX GOOGLE_CLIENT_SECRET=XXX python server.py`

`CTRL+A+D`

`CUDA_VISIBLE_DEVICES=2,3,4,5 python -m vllm.entrypoints.api_server --model conceptofmind/Hermes-LLongMA-2-13b-8k --tensor-parallel-size 4 --max-num-batched-tokens 8100`
`CUDA_VISIBLE_DEVICES=0,1,2,3 python -m vllm.entrypoints.api_server --model conceptofmind/Hermes-LLongMA-2-13b-8k --tensor-parallel-size 4 --max-num-batched-tokens 8100`

`curl http://localhost:8000/generate -d '{"prompt": "San Francisco is a ", "use_beam_search": true, "n": 2, "temperature": 0, "max_tokens": 100}'`

`python embedding_client_server.py --device cuda:7 --port 8001 --folder storage`

```
python download-model.py conceptofmind/Hermes-LLongMA-2-13b-8k
python server.py --multi-user --model-menu --bf16 --xformers --sdp-attention --trust-remote-code --share --extensions gallery FPreloader long_replies long_term_memory openai Playground webui-autonomics superbooga
```

[Chrome Driver](https://chromedriver.chromium.org/getting-started) , [Downloads](https://chromedriver.chromium.org/downloads)






