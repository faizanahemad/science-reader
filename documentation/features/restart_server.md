# Restart Manager Server

Standalone Flask server that provides a web UI to monitor and restart the three application services via GNU screen sessions.

Accessible at `restart.mysite.com` (or whatever subdomain you configure in nginx).

## Motivation

Restarting services requires SSH access, attaching to screen sessions, running Ctrl+C, and re-issuing long startup commands with many env vars. This server automates that into a single button press with a web UI.

## Services Managed

| Service Key | Display Name | Screen Session | Port |
|---|---|---|---|
| `opencode_web` | OpenCode Web | `opencode_server` | 3000 |
| `opencode_serve` | OpenCode Serve | `opencode_local` | 4096 |
| `main_server` | Main Python Server | `science-reader` | 5000 |

## Features

- **Status monitoring** — checks if each service port is responding, whether the screen session exists
- **One-click restart** — sends Ctrl+C to stop, waits for process death, re-issues the startup command
- **Command discovery** — automatically finds startup commands from screen scrollback history or `/tmp` startup scripts
- **Command caching** — discovered commands are cached in `restart_server/command_cache.json` for instant future restarts
- **Manual command override** — set or edit the startup command for any service via the UI
- **LLM diagnosis** — when a restart fails, sends screen output to an LLM for root cause analysis
- **Auth** — same PASSWORD-based login as the main server
- **Auto-refresh** — status updates every 10 seconds
- **Configurable working directories** — set per-service workdir via UI; system `cd`s into it before running any commands

## How to Run

```bash
# Minimal (uses same SECRET_KEY and PASSWORD as main server)
SECRET_KEY=secret PASSWORD=Hotpot123. python run_restart_server.py

# With custom port
SECRET_KEY=secret PASSWORD=Hotpot123. python run_restart_server.py --port 5005

# With LLM diagnosis enabled (needs OpenRouter key)
SECRET_KEY=secret PASSWORD=Hotpot123. OPENROUTER_API_KEY=sk-or-... python run_restart_server.py
```

Default port: **5005**

## Nginx Configuration

Add this server block to expose it at `restart.assist-chat.site`:

```nginx
server {
    listen 80;
    server_name restart.assist-chat.site;
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name restart.assist-chat.site;

    ssl_certificate /etc/letsencrypt/live/assist-chat.site/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/assist-chat.site/privkey.pem;

    location / {
        proxy_pass http://localhost:5005;
        proxy_read_timeout 120;
        proxy_connect_timeout 30;
        proxy_send_timeout 120;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }
}
```

Then reload: `sudo systemctl reload nginx`

For SSL on the subdomain: `sudo certbot certonly --nginx -d restart.assist-chat.site`

## Running in a Screen Session

```bash
screen -dmS restart-manager
screen -S restart-manager -X stuff 'SECRET_KEY=secret PASSWORD=Hotpot123. OPENROUTER_API_KEY=sk-or-... python run_restart_server.py\n'
```

## File Structure

```
restart_server/
    __init__.py            # Package marker
    app.py                 # Flask app factory + all routes
    auth.py                # login_required, check_credentials, login/logout routes
    screen_manager.py      # ScreenManager class — screen interaction, port checking, command discovery
    llm_helper.py          # LLM-based failure diagnosis via code_common.call_llm
    command_cache.json     # Auto-generated: cached startup commands
    workdir_config.json   # Auto-generated: per-service working directories
    flask_sessions/        # Auto-generated: filesystem-backed Flask sessions
    templates/
        login.html         # Login page (Bootstrap 5, same pattern as main server)
        dashboard.html     # Main dashboard with service cards, restart buttons, logs viewer
run_restart_server.py      # Entry point script (at project root)
```

## API Endpoints

All endpoints require authentication (session cookie from `/login`).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Dashboard page |
| GET | `/login` | Login page |
| POST | `/login` | Authenticate (form: email, password) |
| GET | `/logout` | Clear session, redirect to login |
| GET | `/api/status` | JSON status of all 3 services |
| GET | `/api/status/<svc>` | JSON status of one service |
| POST | `/api/restart/<svc>` | Restart a service. Optional body: `{"command": "..."}` |
| GET | `/api/logs/<svc>` | Recent screen scrollback output |
| GET | `/api/discover_command/<svc>` | Show discovered/cached startup command |
| POST | `/api/set_command/<svc>` | Set startup command. Body: `{"command": "..."}` |
| POST | `/api/diagnose/<svc>` | LLM diagnosis of current state |
| GET | `/api/config/workdir` | Get working directories for all services |
| POST | `/api/config/workdir/<svc>` | Set working directory. Body: `{"workdir": "/path"}` |

Service keys: `opencode_web`, `opencode_serve`, `main_server`

## Restart Flow

When a user clicks "Restart" for a service:

1. **Resolve startup command** — check cache, then parse screen scrollback, then check `/tmp` scripts
2. **Ensure screen exists** — create it if missing (`screen -dmS <name>`)
3. **Ensure correct working directory** — if a workdir is configured for the service, send `cd '<workdir>'` to the screen session
3. **Stop current process** — send Ctrl+C (twice), wait up to 15s for port to close
4. **Kill if stubborn** — if still running, send `kill %1` and `kill -9 %1`
5. **Issue startup command** — type the command into the screen session
6. **Wait for startup** — poll the port for up to 60s
7. **Report result** — success with green toast, or failure with restart logs and LLM diagnosis

## Command Discovery

The system discovers startup commands in this order:

1. **Cache** — `command_cache.json` (fastest, used after first successful discovery)
2. **Screen scrollback** — dumps scrollback via `screen -X hardcopy -h`, searches for command patterns like `opencode web`, `opencode serve`, `python server.py`
3. **Startup scripts** — checks `/tmp/run_science_reader.sh`, `/tmp/run_opencode.sh`, etc.
4. **Manual override** — user can paste the command via "Set Cmd" button in the UI

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session encryption key |
| `PASSWORD` | Yes | Login password (same as main server) |
| `OPENROUTER_API_KEY` | No | Enables LLM diagnosis on restart failures |

## Dependencies

Uses the same Python environment (`science-reader` conda env) as the main server. Key packages:
- `flask` + `flask-session` — web framework and session management
- `code_common.call_llm` — LLM calls for diagnosis (imported from project)

## Implementation Notes

- **Auth is independent** — the restart server has its own session store (`restart_server/flask_sessions/`) and cookie name (`restart_session_id`) to avoid conflicts with the main server
- **No database** — all state is in `command_cache.json` and filesystem sessions
- **Fail-safe LLM** — if `OPENROUTER_API_KEY` is not set or the LLM call fails, a descriptive error message is returned instead of crashing
- **Concurrent restart protection** — only one restart per service at a time (in-memory lock)
- **Port checking** — uses TCP socket connection to `localhost:<port>` with a 2s timeout to determine if a service is running
- **Working directory config** — stored in `workdir_config.json`, enforced before every restart and git pull. The `_ensure_workdir()` method sends `cd '<path>'` into the screen session so all subsequent commands run in the correct directory. Configurable via the collapsible "Configuration — Working Directories" panel on the dashboard, separate from service cards
