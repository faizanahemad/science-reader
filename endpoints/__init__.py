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
