# Dockerize: Multi-Instance with Partitioned Storage

## Goal

Scale the chat app horizontally by running N independent instances behind nginx, each owning a partition of users. Zero shared state, zero code changes for the base path. Linear scaling: N instances = N× capacity.

## Architecture

```
Client → nginx (consistent hash on user email cookie)
              │
              ├── instance-1:5000 (disk: /data/instance-1/)
              ├── instance-2:5000 (disk: /data/instance-2/)
              └── instance-3:5000 (disk: /data/instance-3/)
```

Each instance is a fully independent server with its own:
- `storage/` directory (conversations, documents, PKB, cache)
- `flask_session/` directory
- `users.db`, `search_index.db`, `pkb.sqlite`
- Thread pool, conversation cache, terminal sessions

No shared filesystem. No Redis. No cross-instance communication.

## Routing Strategy

**Cookie-based consistent hashing** (preferred over ip_hash because users may share IPs behind NAT, and mobile users change IPs):

1. On first request (no cookie), nginx picks an instance via ip_hash fallback
2. After login, the app sets a `_route_key` cookie = hash of user email
3. nginx uses this cookie for all subsequent routing via `hash $cookie__route_key consistent`

Fallback: if cookie is absent, use `$remote_addr` (ip_hash behavior).

## Requirements

- Docker + Docker Compose (or any container runtime)
- Enough disk per instance for user data (~500MB-2GB per active user with documents)
- Backup strategy for instance-local data (S3 sync or volume snapshots)

## Capacity Estimates

| Instance Config | Concurrent Users/Instance | Total (3 instances) |
|----------------|--------------------------|---------------------|
| 1 worker, 64 threads | ~50 active streams | ~150 |
| 1 worker, 128 threads | ~80 active streams | ~240 |
| 1 worker, 256 threads | ~120 active streams | ~360 |

Memory per instance: ~4-8GB (conversation cache 200 objects + thread stacks + PKB vectors).

## Components

### 1. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libomp-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Application code
COPY . .

# Storage directory (mounted as persistent volume per instance)
RUN mkdir -p /app/storage

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Single worker, many threads — matches existing architecture
# gthread = threaded worker (compatible with dill, faiss, numpy)
# timeout = 3600s for long SSE streams
CMD ["gunicorn", "server:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--threads", "64", \
     "--timeout", "3600", \
     "--graceful-timeout", "30", \
     "--worker-class", "gthread", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100"]
```

Notes:
- `--workers 1`: Single process per container. Avoids breaking in-process state (conversation_cache, tool events, terminal sessions).
- `--threads 64`: Matches current ThreadPoolExecutor concurrency model.
- `--max-requests 1000`: Recycle worker after 1000 requests to prevent memory leaks from unbounded caches.
- `--worker-class gthread`: Threaded. NOT gevent (breaks dill, faiss C extensions).

### 2. docker-compose.yml

```yaml
version: "3.8"

services:
  instance-1:
    build: .
    container_name: chat-instance-1
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - INSTANCE_ID=1
    volumes:
      - instance1_data:/app/storage
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: "2"

  instance-2:
    build: .
    container_name: chat-instance-2
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - INSTANCE_ID=2
    volumes:
      - instance2_data:/app/storage
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: "2"

  instance-3:
    build: .
    container_name: chat-instance-3
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - INSTANCE_ID=3
    volumes:
      - instance3_data:/app/storage
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: "2"

  nginx:
    image: nginx:alpine
    container_name: chat-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - instance-1
      - instance-2
      - instance-3
    restart: unless-stopped

volumes:
  instance1_data:
  instance2_data:
  instance3_data:
```

### 3. nginx.conf (consistent hash routing)

```nginx
worker_processes auto;

events {
    worker_connections 2048;
}

http {
    # Upstream with consistent hashing on route cookie
    upstream chat_backend {
        hash $route_key consistent;
        server instance-1:5000;
        server instance-2:5000;
        server instance-3:5000;
    }

    # Extract routing key: prefer cookie, fall back to IP
    map $cookie__route_key $route_key {
        default   $cookie__route_key;
        ""        $remote_addr;
    }

    # HTTP → HTTPS redirect
    server {
        listen 80;
        server_name assist-chat.site;
        return 301 https://$host$request_uri;
    }

    # Main HTTPS server
    server {
        listen 443 ssl;
        server_name assist-chat.site;

        ssl_certificate /etc/letsencrypt/live/assist-chat.site/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/assist-chat.site/privkey.pem;

        client_max_body_size 100M;

        location / {
            proxy_pass http://chat_backend;
            proxy_read_timeout 3600;
            proxy_connect_timeout 300;
            proxy_send_timeout 3600;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Connection "";
            proxy_http_version 1.1;
            proxy_buffering off;
            proxy_cache off;
        }

        # Health check endpoint (not routed via hash)
        location /health {
            proxy_pass http://chat_backend;
        }
    }
}
```

### 4. Application code changes

#### 4a. Set routing cookie after login (endpoints/auth.py)

After successful Google OAuth callback, set the routing cookie:

```python
import hashlib

# After setting session["email"]:
route_key = hashlib.md5(email.encode()).hexdigest()[:8]
response.set_cookie("_route_key", route_key, max_age=30*86400, httponly=True, samesite="Lax")
```

This ensures all subsequent requests from this user hit the same instance.

#### 4b. Health check endpoint (server.py)

```python
@app.route("/health")
def health_check():
    return {"status": "ok", "instance": os.environ.get("INSTANCE_ID", "unknown")}, 200
```

#### 4c. Graceful shutdown handling (server.py)

```python
import signal

def graceful_shutdown(signum, frame):
    """Allow in-flight SSE streams to complete before exit."""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    # gunicorn handles this via --graceful-timeout, but log it
    
signal.signal(signal.SIGTERM, graceful_shutdown)
```

### 5. .dockerignore

```
.git
__pycache__
*.pyc
flask_session/
storage/
*.db
*.sqlite
*.log
.cursor/
.opencode/
desktop/node_modules/
output/
temp/
test_output/
tests/
users/
```

## Operations

### Initial deployment

```bash
# 1. Build
docker compose build

# 2. Start
docker compose up -d

# 3. Verify
curl -k https://assist-chat.site/health
```

### Adding a new instance

1. Add `instance-4` service to docker-compose.yml (copy instance-3 block)
2. Add `server instance-4:5000;` to nginx upstream
3. `docker compose up -d instance-4 && docker exec chat-nginx nginx -s reload`

nginx's `consistent` hashing minimizes user redistribution — only ~1/N users move to the new instance.

### User data migration (when rebalancing)

When adding/removing instances, some users get re-routed to an instance that doesn't have their data. Options:

**Option A: Lazy migration (simplest)**
- User lands on new instance → gets empty state → must re-login
- Old data sits on old instance, can be migrated manually later
- Acceptable for infrequent rebalancing

**Option B: Pre-migration script**
```bash
#!/bin/bash
# Compute which users move to new instance and rsync their data
for user_dir in /data/instance-1/storage/conversations/*/; do
    user_hash=$(echo -n "$user_email" | md5sum | cut -c1-8)
    target_instance=$(( 0x${user_hash:0:4} % $NUM_INSTANCES ))
    if [ $target_instance -ne 1 ]; then
        rsync -a "$user_dir" "/data/instance-${target_instance}/storage/conversations/"
    fi
done
```

**Option C: Shared object storage for cold data**
- Hot data (recent conversations) on local disk
- Cold data (>30 days) synced to S3
- On miss: pull from S3 to local disk on first access
- Decouples storage from routing

### Backup strategy

```bash
# Cron job per instance (daily)
0 3 * * * docker exec chat-instance-1 tar czf /tmp/backup.tar.gz /app/storage && \
          docker cp chat-instance-1:/tmp/backup.tar.gz /backups/instance-1-$(date +%Y%m%d).tar.gz
```

Or use Docker volume backup tools / EBS snapshots.

### Rolling updates (zero-downtime deploys)

```bash
# Update one instance at a time
for i in 1 2 3; do
    docker compose build instance-$i
    docker compose up -d --no-deps instance-$i
    sleep 60  # Wait for in-flight streams to complete
done
```

Active SSE streams on the restarting instance will drop (client auto-reconnects). Users may see a brief interruption.

### Monitoring

Key metrics per instance:
- Thread pool utilization: `active_threads / 64`
- Memory usage: container memory vs 8GB limit
- Response time p99: should be <500ms for non-streaming
- Active SSE streams: tracks concurrent users
- SQLite lock wait time: if >100ms, instance is overloaded

### Instance failure recovery

1. nginx detects failed health check → marks instance down
2. Affected users' requests fail (no automatic failover — data is instance-local)
3. Options:
   - **Wait**: restart instance, data intact on volume
   - **Failover**: route users to another instance (cold cache, no data until restore)
   - **Restore from backup**: mount backup volume to replacement instance

## What does NOT need to change

- All Flask routes and handlers
- Conversation.py (all persistence)
- PKB / truth_management_system
- DocIndex
- Tool calling pipeline
- Auto-doubts
- Web scraping / search
- LLM calling layer
- All frontend JavaScript

## Limitations of this approach

1. **No cross-instance features**: A user can't access another user's shared workspace/doc if they're on different instances. (Currently not a feature anyway.)
2. **No live failover**: Instance death = those users are down until recovery.
3. **Uneven load**: Some instances may have power users (heavy PKB, many docs) while others are idle. Manual rebalancing needed.
4. **Max single-user concurrency unchanged**: One user can still only push ~50 concurrent operations per instance. Doesn't help if one user is the bottleneck.
5. **Cold start after rebalance**: Users moved to new instance lose conversation cache and must re-auth.

## Future evolution (if needed beyond 500 users)

1. **Postgres + pgvector** for PKB → enables cross-instance PKB access, real connection pooling
2. **S3 for conversation storage** → decouples storage from compute, enables true stateless containers
3. **Redis for session + tool events** → enables random routing (no stickiness needed)
4. **Kubernetes** → auto-scaling, health-based routing, rolling deploys
5. **Message queue (Celery/SQS)** → decouple SSE streaming from LLM generation
