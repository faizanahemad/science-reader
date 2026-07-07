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

exec "$PY" server.py --login_not_needed --no-cache "$@"
