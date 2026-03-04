#!/usr/bin/env python3
"""
Entry point for the restart manager server.

Usage::

    SECRET_KEY=secret PASSWORD=Hotpot123. python run_restart_server.py
    # or with a custom port:
    SECRET_KEY=secret PASSWORD=Hotpot123. python run_restart_server.py --port 5005

The server should be placed behind nginx for the ``restart.mysite.com``
subdomain.  Example nginx block::

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
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Ensure project root is importable (for code_common, etc.)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = _THIS_DIR  # run_restart_server.py sits at project root
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from restart_server.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart Manager Server")
    parser.add_argument(
        "--port", type=int, default=5005, help="Port to listen on (default: 5005)"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = create_app()
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
