#!/bin/bash
# Run the chat server "for real" (no debugger), replicating the
# "Python: Debug Server" configuration from .vscode/launch.json:
# same env vars, same args (--login_not_needed --no-cache), but executed
# with the project venv's python directly.
#
# Usage: ./run_server.sh [extra args passed to server.py]
#
# Conversation Sync (documentation/features/conversation_sync) is configured via
# env vars — add these to the "Python: Debug Server" env block in launch.json
# (or export them before invoking) on the relevant instance; all are optional:
#   Receiver: SYNC_UPLOAD_TOKEN, SYNC_UPLOAD_USER_EMAIL
#   Sender:   SYNC_REMOTE_URL, SYNC_REMOTE_TOKEN, SYNC_HOST_LABEL (label optional)
# Receiver /sync/upload 404s entirely unless SYNC_UPLOAD_TOKEN is set.
#
# Host-local synthetic Main Models (local/gemini-rag, local/gemini-agent) —
# defaults below apply only when unset (launch.json / shell can override):
#   GEMINI_RAG_SCRIPT_PATH     default ~/.local/bin/gemini-rag-query
#   GEMINI_AGENT_SCRIPT_PATH   default ~/.local/bin/gemini-agent-query
#   GEMINI_RAG_MAX_URLS        default 20 (CLI clamps 1–20)
#   GEMINI_RAG_TIMEOUT         optional whole-pipeline timeout (seconds)
#   GEMINI_AGENT_TIMEOUT       optional whole-pipeline timeout (seconds)
#   GEMINI_RAG_DISABLED=1      kill-switch rag model
#   GEMINI_AGENT_DISABLED=1    kill-switch agent model
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "error: .venv not found — create it first (python -m venv .venv)"; exit 1; }

# Export the env block of the "Python: Debug Server" config from launch.json
# (strips // comments and trailing commas so json can parse it).
eval "$("$PY" - <<'PYEOF'
import json, re, shlex

raw = open(".vscode/launch.json").read()
raw = re.sub(r'^\s*//.*$', '', raw, flags=re.M)          # line comments
raw = re.sub(r',(\s*[}\]])', r'\1', raw)                  # trailing commas
cfg = next(c for c in json.loads(raw)["configurations"]
           if c["name"] == "Python: Debug Server")
for k, v in cfg.get("env", {}).items():
    print(f"export {k}={shlex.quote(v)}")
PYEOF
)"

# Host-local CLI Main Models: path defaults only if not already set by
# launch.json or the caller's environment. Do not force-enable if someone
# already set a kill-switch / custom script path.
export GEMINI_RAG_SCRIPT_PATH="${GEMINI_RAG_SCRIPT_PATH:-$HOME/.local/bin/gemini-rag-query}"
export GEMINI_AGENT_SCRIPT_PATH="${GEMINI_AGENT_SCRIPT_PATH:-$HOME/.local/bin/gemini-agent-query}"
export GEMINI_RAG_MAX_URLS="${GEMINI_RAG_MAX_URLS:-20}"

exec "$PY" server.py --login_not_needed --no-cache "$@"
