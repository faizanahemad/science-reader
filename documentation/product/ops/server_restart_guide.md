# Server Restart Guide

How to restart the three server processes (science-reader, OpenCode, extension_server) that run in GNU screen sessions. Covers both individual restarts and the full stack.

**Important**: Never write secrets, API keys, or tokens directly in documentation or script files checked into git. Always extract them from the running environment.

---

## Architecture Overview

```
Screen Sessions:
  science-reader     → Flask app (port 5000) + 7 MCP servers (ports 8100-8106)
  opencode_server    → OpenCode web UI (port 3000)
  extension_server   → MCP extension server (source of JWT tokens for OpenCode)
```

All three run in detached `screen` sessions. The science-reader process is the core — it hosts the Flask web app **and** spawns 7 MCP Uvicorn servers as daemon threads. OpenCode connects to those MCP servers for its tools.

**Dependency order**: `extension_server` → `science-reader` → `opencode_server`

- `extension_server` must be running first (OpenCode needs `MCP_JWT_TOKEN` extracted from its environment)
- `science-reader` must be running before OpenCode (MCP servers must be up for tool registration)
- `opencode_server` connects to MCP servers on startup; if they're down, tools won't register

---

## Extracting Secrets from Running Processes

All secrets live in the environment of running screen sessions. Never hardcode them.

### Extract all env vars from the science-reader process

```bash
# Find the PID of the python process inside the science-reader screen
SR_PID=$(ps aux | grep '[p]ython server.py' | awk '{print $2}' | head -1)

# Dump all env vars
cat /proc/$SR_PID/environ | tr '\0' '\n'

# Extract a specific var
cat /proc/$SR_PID/environ | tr '\0' '\n' | grep MCP_JWT_SECRET
cat /proc/$SR_PID/environ | tr '\0' '\n' | grep MCP_JWT_TOKEN
cat /proc/$SR_PID/environ | tr '\0' '\n' | grep OPENROUTER_API_KEY
```

### Extract MCP_JWT_TOKEN from the extension_server process

```bash
# Find the extension_server PID
EXT_PID=$(ps aux | grep '[e]xtension_server' | awk '{print $2}' | head -1)

# Extract the token
cat /proc/$EXT_PID/environ | tr '\0' '\n' | grep MCP_JWT_TOKEN
```

### Extract from the startup script (if process is dead)

The startup script at `/tmp/run_science_reader.sh` contains all env vars. Note: this file is in `/tmp` and may not survive reboots.

```bash
grep MCP_JWT_TOKEN /tmp/run_science_reader.sh
grep MCP_JWT_SECRET /tmp/run_science_reader.sh
```

### Rebuild the startup script from a running process

If `/tmp/run_science_reader.sh` is lost but science-reader is still running:

```bash
SR_PID=$(ps aux | grep '[p]ython server.py' | awk '{print $2}' | head -1)

# Write all env vars as exports to a new script
echo '#!/bin/bash' > /tmp/run_science_reader.sh
cat /proc/$SR_PID/environ | tr '\0' '\n' | grep -v '^$' | \
  grep -E '^(BRIGHT|CONVERT|GOOGLE_|google|open|OPEN|PYTHON|scraping|serp|zenrow|jina|ASSEMBLYAI|eleven|SECRET_KEY|PASSWORD|MCP_)' | \
  sed 's/^/export /' >> /tmp/run_science_reader.sh
echo 'cd /root/science-reader' >> /tmp/run_science_reader.sh
echo 'python server.py' >> /tmp/run_science_reader.sh
chmod +x /tmp/run_science_reader.sh
```

---

## 1. Restart science-reader (Flask + 7 MCP Servers)

The science-reader process requires ~20 environment variables (API keys, secrets, scraping proxies, etc.). These are captured in `/tmp/run_science_reader.sh`.

### Using the restart script

```bash
# Attach to the screen session
screen -r science-reader

# Kill the running process
Ctrl+C

# Run the startup script
bash /tmp/run_science_reader.sh

# Detach
Ctrl+A, D
```

### If the startup script is missing

Rebuild it from the running process first (see "Rebuild the startup script" above), then use it.

### Verify MCP servers are up

After startup, all 7 MCP servers should be listening:

```bash
for port in 8100 8101 8102 8103 8104 8105 8106; do
  echo -n "Port $port: "
  curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health
  echo
done
```

Expected: all return `200` (health endpoint is unauthenticated).

| Port | MCP Server | Tools |
|------|-----------|-------|
| 8100 | Web Search | `perplexity_search`, `jina_search`, `deep_search`, `jina_read_page`, `read_link` |
| 8101 | PKB (Personal Knowledge Base) | `pkb_search`, `pkb_get_claim`, `pkb_resolve_reference`, `pkb_get_pinned_claims`, `pkb_add_claim`, `pkb_edit_claim` |
| 8102 | Documents | `docs_list_conversation_docs`, `docs_list_global_docs`, `docs_query`, `docs_get_full_text` |
| 8103 | Artefacts | `artefacts_list`, `artefacts_create`, `artefacts_get`, `artefacts_get_file_path`, `artefacts_update`, `artefacts_delete`, `artefacts_propose_edits`, `artefacts_apply_edits` |
| 8104 | Conversation | `conv_get_memory_pad`, `conv_set_memory_pad`, `conv_get_history`, `conv_get_user_detail`, `conv_get_user_preference`, `conv_get_messages`, `conv_set_user_detail` |
| 8105 | Prompts & Actions | `prompts_list`, `prompts_get`, `temp_llm_action`, `prompts_create`, `prompts_update` |
| 8106 | Code Runner | `run_python_code` |

---

## 2. Restart OpenCode Server

OpenCode requires `MCP_JWT_TOKEN` in its environment to authenticate with MCP servers. This must be extracted before restarting.

### Step 1: Extract the JWT token

```bash
# From science-reader process
SR_PID=$(ps aux | grep '[p]ython server.py' | awk '{print $2}' | head -1)
MCP_TOKEN=$(cat /proc/$SR_PID/environ | tr '\0' '\n' | grep '^MCP_JWT_TOKEN=' | cut -d= -f2-)
echo "$MCP_TOKEN"

# Or from the startup script
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)
echo "$MCP_TOKEN"
```

### Step 2: Restart OpenCode

**Method A — Direct attach (when you can access the screen):**

```bash
screen -r opencode_server

# Kill current process
Ctrl+C

# Start with extracted token
export MCP_JWT_TOKEN=<paste-token-from-step-1>
opencode web --port 3000 --hostname 127.0.0.1

# Detach
Ctrl+A, D
```

**Method B — nohup + sleep deferred restart (when restarting from inside OpenCode):**

When you're inside an OpenCode session (e.g., this conversation) and need to restart the OpenCode process itself, you can't just kill it — that would terminate your session. Use the deferred restart pattern:

```bash
# 1. Extract token first
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)

# 2. Write a restart script (avoids screen -X stuff truncating long commands)
cat > /tmp/run_opencode.sh << EOF
export MCP_JWT_TOKEN=$MCP_TOKEN
opencode web --port 3000 --hostname 127.0.0.1
EOF

# 3. Schedule the restart: sleep gives time for Ctrl+C to kill the current process,
#    then the script runs in the now-free screen shell.
#    nohup ensures the sleep+restart survives the current process dying.
nohup bash -c 'sleep 5 && screen -S opencode_server -X stuff "bash /tmp/run_opencode.sh\n"' &>/dev/null &

# 4. Kill the current OpenCode process (the nohup'd restart will fire after 5s)
screen -S opencode_server -X stuff $'\003'
```

**Why this pattern?**
- `screen -X stuff` sends keystrokes to a screen session, but truncates commands longer than ~256 chars — so we write to a script file instead.
- `nohup ... &` runs in the background and survives the parent process being killed.
- `sleep 5` gives the Ctrl+C (`$'\003'`) time to kill the running process before the new command is injected into the screen.
- The sequence is: (1) schedule the deferred restart, (2) kill the current process, (3) after delay the restart command runs in the now-idle screen shell.

**Method C — From a separate SSH session:**

If you have another terminal open:

```bash
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)

# Kill current process
screen -S opencode_server -X stuff $'\003'
sleep 2

# Start new one
screen -S opencode_server -X stuff "export MCP_JWT_TOKEN=$MCP_TOKEN && opencode web --port 3000 --hostname 127.0.0.1\n"
```

### Verify OpenCode is up

```bash
curl -s http://localhost:3000/ | head -5
# Should return HTML content
```

Check that MCP tools registered: in the OpenCode UI, tools from all 7 MCP servers should appear (37 tools total + pdf-reader tools from the local npx server).

---

## 3. Restart extension_server

The extension server rarely needs restarting. It provides the MCP JWT token that OpenCode uses.

```bash
screen -r extension_server
# Check what command is running, note it
Ctrl+C
# Re-run the command
# Ctrl+A, D to detach
```

---

## 4. Full Stack Restart

When you need to restart everything (e.g., after a deploy or major config change):

```bash
# 0. Extract token before killing anything
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)

# 1. Restart science-reader first (all MCP servers)
screen -S science-reader -X stuff $'\003'
sleep 2
screen -S science-reader -X stuff 'bash /tmp/run_science_reader.sh\n'

# 2. Wait for MCP servers to come up
sleep 10

# 3. Verify MCP servers
for port in 8100 8101 8102 8103 8104 8105 8106; do
  echo -n "Port $port: "
  curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health
  echo
done

# 4. Restart OpenCode (needs MCP servers running to register tools)
cat > /tmp/run_opencode.sh << EOF
export MCP_JWT_TOKEN=$MCP_TOKEN
opencode web --port 3000 --hostname 127.0.0.1
EOF

screen -S opencode_server -X stuff $'\003'
sleep 2
screen -S opencode_server -X stuff 'bash /tmp/run_opencode.sh\n'
```

---

## 5. Creating Screen Sessions from Scratch

If a screen session doesn't exist (e.g., after server reboot):

```bash
# Create all three sessions
screen -dmS science-reader
screen -dmS opencode_server
screen -dmS extension_server

# Start science-reader (must have /tmp/run_science_reader.sh)
screen -S science-reader -X stuff 'bash /tmp/run_science_reader.sh\n'

# Wait for MCP servers
sleep 15

# Extract token and start OpenCode
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)
cat > /tmp/run_opencode.sh << EOF
export MCP_JWT_TOKEN=$MCP_TOKEN
opencode web --port 3000 --hostname 127.0.0.1
EOF

screen -S opencode_server -X stuff 'bash /tmp/run_opencode.sh\n'
```

---

## 6. Generating a Fresh JWT Token

If the token has expired or you need a new one:

```bash
# Extract the JWT secret from the running science-reader
SR_PID=$(ps aux | grep '[p]ython server.py' | awk '{print $2}' | head -1)
MCP_SECRET=$(cat /proc/$SR_PID/environ | tr '\0' '\n' | grep '^MCP_JWT_SECRET=' | cut -d= -f2-)

# Or from the startup script
MCP_SECRET=$(grep '^export MCP_JWT_SECRET=' /tmp/run_science_reader.sh | cut -d= -f2-)

# Generate new token
cd /root/science-reader
export MCP_JWT_SECRET="$MCP_SECRET"
python -m mcp_server.auth --email fahemad3@gmail.com --days 365

# Update the token in /tmp/run_science_reader.sh with the new value
# Then restart OpenCode with the new token
```

---

## 7. Troubleshooting

### MCP tools not showing in OpenCode

1. Check MCP servers are running: `curl http://localhost:8100/health`
2. Check `MCP_JWT_TOKEN` is set in the OpenCode process
3. OpenCode registers MCP tools **only at startup** — if MCP servers were down when OpenCode started, restart OpenCode
4. Check `opencode.json` has all 7 MCP server entries with `{env:MCP_JWT_TOKEN}` in headers

### science-reader won't start

1. Check Python environment: `which python` should be the conda env
2. Check port conflicts: `lsof -i :5000` and `lsof -i :8100`
3. Check env vars are set: `echo $MCP_JWT_SECRET`
4. Look at the screen output: `screen -r science-reader`

### OpenCode starts but no MCP tools

Root cause is almost always `MCP_JWT_TOKEN` not set or wrong. The token must match the `MCP_JWT_SECRET` used by science-reader.

```bash
# Verify the token works against a running MCP server
MCP_TOKEN=$(grep '^export MCP_JWT_TOKEN=' /tmp/run_science_reader.sh | cut -d= -f2-)
curl -H "Authorization: Bearer $MCP_TOKEN" http://localhost:8100/
# Should NOT return 401
```

### screen session lost / doesn't exist

```bash
screen -ls  # check what exists
# If missing, create it:
screen -dmS science-reader
screen -r science-reader
# Then start the process manually
```

---

## Key Files

| File | Purpose |
|------|---------|
| `/tmp/run_science_reader.sh` | Startup script with all env vars for science-reader (**not in git, lives in /tmp**) |
| `/root/science-reader/opencode.json` | OpenCode config — 7 remote MCP servers + model settings |
| `/root/science-reader/opencode.jsonc` | OpenCode config — local pdf-reader MCP server (npx) |
| `/root/science-reader/server.py` | Flask entry point, spawns all 7 MCP servers |
| `/root/science-reader/mcp_server/__init__.py` | MCP server launcher functions |
| `/root/science-reader/mcp_server/mcp_app.py` | Web Search MCP (port 8100) |
| `/root/science-reader/mcp_server/pkb.py` | PKB MCP (port 8101) |
| `/root/science-reader/mcp_server/docs.py` | Documents MCP (port 8102) |
| `/root/science-reader/mcp_server/artefacts.py` | Artefacts MCP (port 8103) |
| `/root/science-reader/mcp_server/conversation.py` | Conversation MCP (port 8104) |
| `/root/science-reader/mcp_server/prompts_actions.py` | Prompts & Actions MCP (port 8105) |
| `/root/science-reader/mcp_server/code_runner_mcp.py` | Code Runner MCP (port 8106) |
