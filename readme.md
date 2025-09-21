# Install GCC
`sudo apt install build-essential`

# Ngingx config 
(`/etc/nginx/sites-available/default`) remove the default.
`sudo vi /etc/nginx/sites-available/science-reader`

```
server {                                                                                                                                                                                 
    listen 443 ssl;
    server_name sci-tldr.pro;

    ssl_certificate /etc/letsencrypt/live/sci-tldr.pro/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sci-tldr.pro/privkey.pem;
    
    client_max_body_size 100M;

    location / { 
        proxy_pass http://localhost:5000;
        proxy_read_timeout 300;  # Increase the read timeout (in seconds)
        proxy_connect_timeout 300;  # Increase the connection timeout (in seconds)
        proxy_send_timeout 300;  # Increase the send timeout (in seconds)
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }   
}
```
`sudo ls -l /etc/nginx/sites-enabled/`
`sudo rm /etc/nginx/sites-enabled/default`
`sudo systemctl reload nginx`

For HTTP only

```
server {                                                                                                                                                                                 
    listen 80;

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

Alternate nginx conf locations.

`sudo vi /etc/nginx/nginx.conf`

```
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;

# Load dynamic modules. See /usr/share/doc/nginx/README.dynamic.
include /usr/share/nginx/modules/*.conf;

events {
    worker_connections 1024;
}

http {
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;

    sendfile            on;
    tcp_nopush          on;
    tcp_nodelay         on;
    keepalive_timeout   65;
    types_hash_max_size 4096;

    include             /etc/nginx/mime.types;
    default_type        application/octet-stream;

    # Load modular configuration files from the /etc/nginx/conf.d directory.
    # See http://nginx.org/en/docs/ngx_core_module.html#include
    # for more information.
    
    # /etc/nginx/conf.d/default.conf
    # Comment the below line
    # include /etc/nginx/conf.d/*.conf;

    server {
    listen 80;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }
  }
}
```

Getting SSL CERT

Create `setup_ssl.sh` and put below content.
Then `chmod +x setup_ssl.sh` and `./setup_ssl.sh`
```shell
#!/bin/bash

# Define your domain
DOMAIN="assist-chat.site"
EMAIL="fahemad3+ssl@gmail.com"

# Certbot command to obtain the SSL certificate
echo "Obtaining SSL certificate for $DOMAIN..."
sudo certbot certonly --nginx -d "$DOMAIN" --non-interactive --agree-tos --email $EMAIL

# Check if Certbot was successful
if [ $? -ne 0 ]; then
  echo "Error: Certbot failed to obtain certificate."
  exit 1
fi

# Define the Nginx configuration file path
NGINX_CONF="/etc/nginx/sites-available/science-reader"

# Create Nginx configuration with SSL for the domain
echo "Updating Nginx configuration for $DOMAIN..."

sudo tee "$NGINX_CONF" > /dev/null <<EOL
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    
    client_max_body_size 100M;

    location / {
        proxy_pass http://localhost:5000;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
    }
}
EOL

# Test Nginx configuration for syntax errors
echo "Testing Nginx configuration..."
sudo nginx -t

if [ $? -ne 0 ]; then
  echo "Error: Nginx configuration test failed."
  exit 1
fi

# Reload Nginx to apply the changes
echo "Reloading Nginx..."
sudo systemctl reload nginx

# Setup automatic renewal (this is usually set by Certbot, but we'll ensure it)
echo "Setting up automatic SSL certificate renewal..."
sudo crontab -l | { cat; echo "0 0 * * * /usr/bin/certbot renew --quiet && systemctl reload nginx"; } | sudo crontab -

echo "SSL certificate setup and Nginx configuration complete for $DOMAIN."


```

# Start server
`screen -S science-reader`

`SECRET_KEY=XX GOOGLE_CLIENT_ID=XXX GOOGLE_CLIENT_SECRET=XXX python server.py`

`CTRL+A+D`

`CUDA_VISIBLE_DEVICES=2,3,4,5 python -m vllm.entrypoints.api_server --model conceptofmind/Hermes-LLongMA-2-13b-8k --tensor-parallel-size 4 --max-num-batched-tokens 8100`
`CUDA_VISIBLE_DEVICES=0,1,2,3 python -m vllm.entrypoints.api_server --model conceptofmind/Hermes-LLongMA-2-13b-8k --tensor-parallel-size 4 --max-num-batched-tokens 8100`

`curl http://localhost:8000/generate -d '{"prompt": "San Francisco is a ", "use_beam_search": true, "n": 2, "temperature": 0, "max_tokens": 100}'`


`
CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 python -m vllm.entrypoints.openai.api_server --model lmsys/vicuna-13b-v1.5-16k --tensor-parallel-size 8 --max-num-batched-tokens 16384 --dtype half --gpu-memory-utilization 0.8 --swap-space 32

CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 python -m vllm.entrypoints.openai.api_server --model Open-Orca/LlongOrca-13B-16k --tensor-parallel-size 8 --max-num-batched-tokens 16384 --dtype bfloat16 --gpu-memory-utilization 0.8 --swap-space 32 --max-model-len 16384
`

`python embedding_client_server.py --device cuda:7 --port 8001 --folder storage`

```
python download-model.py conceptofmind/Hermes-LLongMA-2-13b-8k
python server.py --multi-user --model-menu --bf16 --xformers --sdp-attention --trust-remote-code --share --extensions gallery FPreloader long_replies long_term_memory openai Playground webui-autonomics superbooga
```

[Chrome Driver](https://chromedriver.chromium.org/getting-started) , [Downloads](https://chromedriver.chromium.org/downloads)

`sudo apt-get install libomp-dev`



# Generate keys
```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d sci-tldr.pro
cd science-reader
cp /etc/letsencrypt/live/sci-tldr.pro/fullchain.pem cert-ext.pem
cp /etc/letsencrypt/live/sci-tldr.pro/privkey.pem key-ext.pem
sudo systemctl start nginx
```

# Install Gotenberg
https://linuxhint.com/install-package-to-a-specific-directory-using-yum/
Download from https://www.libreoffice.org/download/download-libreoffice/?type=deb-x86_64&version=7.6.2&lang=en-US
```bash
sudo apt install docker-ce
sudo systemctl start docker
sudo systemctl enable docker
docker stop gotenberg-production && docker rm gotenberg-production 
docker run -d --name gotenberg-production --restart unless-stopped -p 7777:80 --memory=1g --cpus=1.0 gotenberg/gotenberg:7 gotenberg --api-port=80 --api-timeout=30s --chromium-disable-web-security=true  

# for RHEL
cd ~
mkdir -p bin
wget https://ftp.gwdg.de/pub/tdf/libreoffice/stable/7.6.2/rpm/x86_64/LibreOffice_7.6.2_Linux_x86-64_rpm.tar.gz
tar -xvf LibreOffice_7.6.2_Linux_x86-64_rpm.tar.gz
cd LibreOffice_7.6.2.1_Linux_x86-64_rpm/RPMS
sudo yum --installroot=/home/ahemf/bin install *.rpm --skip-broken
# Add below line to your bash rc file
# export PATH="$PATH:$HOME/bin/opt/libreoffice7.6/program"
echo 'export PATH="$PATH:$HOME/bin/opt/libreoffice7.6/program"' >> ~/.bashrc
echo 'export PATH="$PATH:$HOME/bin/opt/libreoffice7.6/program"' >> ~/.zshrc


# for Debian
sudo snap install libreoffice


```

