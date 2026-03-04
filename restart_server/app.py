"""
Flask application for the service restart manager.

Provides a web dashboard to monitor and restart three services
(OpenCode Web, OpenCode Serve, Main Python Server) that run inside
GNU screen sessions.

Routes
------
GET  /                          Dashboard (requires login)
GET  /api/status                JSON status of all services
GET  /api/status/<svc>          JSON status of one service
POST /api/restart/<svc>         Trigger a restart (with auto-recovery on failure)
POST /api/recover/<svc>         Standalone LLM recovery agent
GET  /api/logs/<svc>            Recent screen output
GET  /api/discover_command/<svc>  Show discovered startup command
POST /api/set_command/<svc>     Manually set startup command
POST /api/diagnose/<svc>        LLM diagnosis of current state
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, render_template, request

from restart_server.auth import auth_bp, login_required
from restart_server.llm_helper import diagnose_restart_failure, recover_service
from restart_server.screen_manager import SERVICES, ScreenManager

logger = logging.getLogger(__name__)

# Singleton screen manager — lives for the process lifetime.
screen_mgr = ScreenManager()

# Simple per-service lock to prevent concurrent restarts.
_restart_in_progress: dict[str, bool] = {}


def create_app() -> Flask:
    """Application factory for the restart manager."""

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    )

    # -- Session / cookie config (mirrors main server pattern) --
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="restart_session_id",
        SESSION_COOKIE_PATH="/",
    )
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = os.path.join(
        os.path.dirname(__file__), "flask_sessions"
    )
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "restart-server-fallback-key"
    )
    app.secret_key = app.config["SECRET_KEY"]

    # Flask-Session (filesystem-backed)
    from flask_session import Session

    Session(app)

    # Register auth blueprint (login/logout)
    app.register_blueprint(auth_bp)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.route("/")
    @login_required
    def dashboard():
        """Render the single-page management dashboard."""
        return render_template("dashboard.html")

    # ------------------------------------------------------------------
    # JSON API
    # ------------------------------------------------------------------

    @app.route("/api/status")
    @login_required
    def api_status():
        """Return JSON status for all three services."""
        return jsonify(screen_mgr.get_all_statuses())

    @app.route("/api/status/<service_name>")
    @login_required
    def api_service_status(service_name: str):
        """Return JSON status for a single service."""
        status = screen_mgr.get_service_status(service_name)
        if "error" in status:
            return jsonify(status), 404
        return jsonify(status)

    @app.route("/api/restart/<service_name>", methods=["POST"])
    @login_required
    def api_restart(service_name: str):
        """Restart a service.  Optionally accepts ``{"command": "..."}`` body.

        If the basic restart fails and ``OPENROUTER_API_KEY`` is set, the
        LLM recovery agent automatically takes over — executing commands,
        reading logs, and retrying until the service is up or it gives up.
        """
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        if _restart_in_progress.get(service_name):
            return jsonify(
                {"error": "Restart already in progress for this service"}
            ), 409

        data = request.get_json(silent=True) or {}
        command_override = data.get("command")

        _restart_in_progress[service_name] = True
        try:
            success, message, logs = screen_mgr.restart_service(
                service_name, command_override=command_override
            )

            result: dict = {
                "success": success,
                "message": message,
                "logs": logs,
            }

            # On failure, run the LLM recovery agent (not just diagnosis)
            if not success and os.getenv("OPENROUTER_API_KEY"):
                cfg = SERVICES[service_name]
                screen_output = screen_mgr.get_recent_output(service_name)
                cached_cmd = screen_mgr.get_cached_command(service_name)

                logs.append("Basic restart failed — handing off to LLM recovery agent…")
                rec_ok, rec_summary, rec_actions = recover_service(
                    service_name=service_name,
                    display_name=cfg["display_name"],
                    screen_name=cfg["screen_name"],
                    port=cfg["port"],
                    restart_logs=logs,
                    screen_output=screen_output,
                    cached_command=cached_cmd,
                )

                result["recovery_ran"] = True
                result["recovery_success"] = rec_ok
                result["recovery_summary"] = rec_summary
                result["recovery_actions"] = rec_actions

                if rec_ok:
                    result["success"] = True
                    result["message"] = f"Recovered by LLM agent: {rec_summary}"
                    success = True

            elif not success:
                # No API key — fall back to read-only diagnosis
                screen_output = screen_mgr.get_recent_output(service_name)
                diagnosis = diagnose_restart_failure(
                    service_name=service_name,
                    display_name=SERVICES[service_name]["display_name"],
                    restart_logs=logs,
                    screen_output=screen_output,
                )
                result["diagnosis"] = diagnosis

            status_code = 200 if success else 500
            return jsonify(result), status_code

        finally:
            _restart_in_progress[service_name] = False

    @app.route("/api/recover/<service_name>", methods=["POST"])
    @login_required
    def api_recover(service_name: str):
        """Standalone LLM recovery agent endpoint.

        Runs the recovery agent independently of the restart flow.
        Useful when the service is in a broken state and you want the
        LLM to diagnose and fix it from scratch.
        """
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        if _restart_in_progress.get(service_name):
            return jsonify(
                {"error": "A restart/recovery is already in progress"}
            ), 409

        cfg = SERVICES[service_name]
        _restart_in_progress[service_name] = True
        try:
            screen_output = screen_mgr.get_recent_output(service_name)
            cached_cmd = screen_mgr.get_cached_command(service_name)

            data = request.get_json(silent=True) or {}
            extra_context = data.get("context", "")
            context_logs = [extra_context] if extra_context else []

            rec_ok, rec_summary, rec_actions = recover_service(
                service_name=service_name,
                display_name=cfg["display_name"],
                screen_name=cfg["screen_name"],
                port=cfg["port"],
                restart_logs=context_logs,
                screen_output=screen_output,
                cached_command=cached_cmd,
            )

            return jsonify({
                "success": rec_ok,
                "summary": rec_summary,
                "actions": rec_actions,
            }), 200 if rec_ok else 500

        finally:
            _restart_in_progress[service_name] = False
    @app.route("/api/logs/<service_name>")
    @login_required
    def api_logs(service_name: str):
        """Return recent screen scrollback output for a service."""
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        output = screen_mgr.get_recent_output(service_name)
        return jsonify(
            {
                "service_name": service_name,
                "output": output or "(no output available)",
            }
        )

    @app.route("/api/discover_command/<service_name>")
    @login_required
    def api_discover_command(service_name: str):
        """Attempt to discover the startup command for a service."""
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        command = screen_mgr.discover_command(service_name)
        cached = screen_mgr.get_cached_command(service_name)
        return jsonify(
            {
                "service_name": service_name,
                "command": command,
                "source": "cache"
                if cached == command and cached is not None
                else "discovered",
            }
        )

    @app.route("/api/set_command/<service_name>", methods=["POST"])
    @login_required
    def api_set_command(service_name: str):
        """Manually set / override the cached startup command."""
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        data = request.get_json(silent=True) or {}
        command = data.get("command")
        if not command:
            return jsonify({"error": "No 'command' field in request body"}), 400

        screen_mgr.cache_command(service_name, command)
        return jsonify(
            {"success": True, "message": f"Command cached for {service_name}"}
        )

    @app.route("/api/diagnose/<service_name>", methods=["POST"])
    @login_required
    def api_diagnose(service_name: str):
        """Run LLM diagnosis on a service's current screen output."""
        if service_name not in SERVICES:
            return jsonify({"error": f"Unknown service: {service_name}"}), 404

        screen_output = screen_mgr.get_recent_output(service_name)
        data = request.get_json(silent=True) or {}
        extra_context = data.get("context", "")

        diagnosis = diagnose_restart_failure(
            service_name=service_name,
            display_name=SERVICES[service_name]["display_name"],
            restart_logs=[extra_context] if extra_context else [],
            screen_output=screen_output,
        )
        return jsonify({"service_name": service_name, "diagnosis": diagnosis})

    return app
