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




