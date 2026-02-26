"""
Flask endpoint modules (Blueprints).

This package will contain one module per logical API group (auth, conversations,
pkb, etc.). Each module defines a Flask Blueprint and the route handlers for
that domain.

`server.py` is responsible for creating the Flask app and then calling
`register_blueprints(app)` to attach all endpoint groups.
"""

from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """
    Register all endpoint Blueprints on the provided Flask app.

    Notes
    -----
    - We intentionally keep this function import-only: endpoint modules should
      not import `server.py`.
    - During the refactor rollout, this function may initially be a no-op and
      will be filled in as blueprints are created.
    """

    # Order can matter for request hooks (e.g., auth remember-token logic uses
    # `before_app_request`), so we register auth first.
    from .auth import auth_bp
    from .static_routes import static_bp
    from .workspaces import workspaces_bp
    from .conversations import conversations_bp
    from .doubts import doubts_bp
    from .sections import sections_bp
    from .documents import documents_bp
    from .audio import audio_bp
    from .users import users_bp
    from .pkb import pkb_bp
    from .prompts import prompts_bp
    from .code_runner import code_runner_bp
    from .artefacts import artefacts_bp
    from .global_docs import global_docs_bp
    from .ext_auth import ext_auth_bp
    from .ext_page_context import ext_page_bp
    from .ext_scripts import ext_scripts_bp
    from .ext_workflows import ext_workflows_bp
    from .ext_settings import ext_settings_bp
    from .file_browser import file_browser_bp
    from .doc_folders import doc_folders_bp
    # OpenCode terminal (WebSocket-based PTY)
    try:
        from .terminal import terminal_bp, sock as terminal_sock
        app.register_blueprint(terminal_bp)
        terminal_sock.init_app(app)
    except ImportError:
        pass  # endpoints/terminal.py not created yet

    app.register_blueprint(auth_bp)
    app.register_blueprint(static_bp)
    app.register_blueprint(workspaces_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(doubts_bp)
    app.register_blueprint(sections_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(pkb_bp)
    app.register_blueprint(prompts_bp)
    app.register_blueprint(code_runner_bp)
    app.register_blueprint(artefacts_bp)
    app.register_blueprint(global_docs_bp)
    app.register_blueprint(ext_auth_bp)
    app.register_blueprint(ext_page_bp)
    app.register_blueprint(ext_scripts_bp)
    app.register_blueprint(ext_workflows_bp)
    app.register_blueprint(ext_settings_bp)
    app.register_blueprint(file_browser_bp)
    app.register_blueprint(doc_folders_bp)
