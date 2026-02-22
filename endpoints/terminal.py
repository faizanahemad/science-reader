"""
WebSocket-based terminal for OpenCode TUI.

Spawns ``opencode`` in a PTY, bridges I/O to browser via WebSocket + xterm.js.
Auth-protected by Flask session (same as all other endpoints).

Architecture
------------
- ``TerminalSession`` class wraps a single PTY process with process-group
  isolation (``os.setsid()`` in child) so that ``os.killpg`` can reap the
  entire subtree (LSP servers, tools, etc.) on cleanup.
- One ``TerminalSession`` per user email; second tabs reattach to the same PTY.
- A reader thread pumps PTY output → WebSocket; the main thread pumps
  WebSocket input → PTY.
- Idle timeout, max-sessions cap, and graceful SIGTERM→wait→SIGKILL cleanup
  prevent resource leaks.

Configuration (env vars)
------------------------
- TERMINAL_IDLE_TIMEOUT  — seconds before idle kill (default 1800 = 30 min)
- TERMINAL_MAX_SESSIONS  — global cap on concurrent sessions (default 5)
- TERMINAL_SCROLLBACK    — advertised scrollback (default 5000, used by client)
- OPENCODE_BINARY        — binary name / path (default "opencode")
- PROJECT_DIR            — cwd for the spawned process (default os.getcwd())
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import select
import signal
import struct
import termios
import threading
import time
from typing import Dict, Optional

from flask import Blueprint, send_from_directory, session
from flask_sock import Sock

from endpoints.auth import login_required
from endpoints.session_utils import get_session_identity
from extensions import limiter

logger = logging.getLogger(__name__)

terminal_bp = Blueprint("terminal", __name__)

# ─── Global session registry (per-user terminal sessions) ─────────────
# Key: user_email, Value: TerminalSession object
_terminal_sessions: Dict[str, "TerminalSession"] = {}
_sessions_lock = threading.Lock()

# ─── Configuration ────────────────────────────────────────────────────
TERMINAL_IDLE_TIMEOUT = int(os.getenv("TERMINAL_IDLE_TIMEOUT", "1800"))  # 30 min
TERMINAL_MAX_SESSIONS = int(os.getenv("TERMINAL_MAX_SESSIONS", "5"))
TERMINAL_SCROLLBACK = int(os.getenv("TERMINAL_SCROLLBACK", "5000"))
OPENCODE_BINARY = os.getenv("OPENCODE_BINARY", "opencode")
PROJECT_DIR = os.getenv("PROJECT_DIR", os.getcwd())


# ─── TerminalSession ─────────────────────────────────────────────────


class TerminalSession:
    """
    Manages a single PTY process for a user.

    Handles:
    - PTY spawning with process group isolation
    - Terminal resize (SIGWINCH propagation)
    - Idle timeout detection
    - Graceful and forced cleanup
    - Zombie process prevention

    Parameters
    ----------
    user_email : str
        Owner's email (used as registry key).
    cols : int
        Initial terminal width in columns.
    rows : int
        Initial terminal height in rows.
    """

    def __init__(self, user_email: str, cols: int = 80, rows: int = 24):
        self.user_email = user_email
        self.cols = cols
        self.rows = rows
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None
        self.alive = False
        self.last_activity = time.time()
        self.created_at = time.time()
        self._lock = threading.Lock()

    def spawn(self) -> None:
        """
        Spawn opencode in a new PTY with process group isolation.

        Child calls ``os.setsid()`` to create a new session/process group,
        then ``os.execvpe`` replaces it with the opencode binary.
        Parent stores pid/fd and sets initial terminal size.
        """
        import pty as pty_module

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["COLUMNS"] = str(self.cols)
        env["LINES"] = str(self.rows)

        pid, fd = pty_module.fork()

        if pid == 0:
            # ─── Child process ───
            # Create new process group (so we can kill all children)
            os.setsid()
            os.chdir(PROJECT_DIR)
            os.execvpe(
                OPENCODE_BINARY,
                [OPENCODE_BINARY, PROJECT_DIR],
                env,
            )
            # execvpe does not return; if it fails:
            os._exit(1)
        else:
            # ─── Parent process ───
            self.pid = pid
            self.fd = fd
            self.alive = True
            # Set initial terminal size
            self._set_winsize(self.cols, self.rows)
            logger.info(f"Terminal spawned for {self.user_email}: pid={pid}, fd={fd}")

    def resize(self, cols: int, rows: int) -> None:
        """
        Propagate terminal resize to PTY (sends SIGWINCH to child).

        Parameters
        ----------
        cols : int
            New width in columns.
        rows : int
            New height in rows.
        """
        self.cols = cols
        self.rows = rows
        if self.fd is not None:
            self._set_winsize(cols, rows)

    def _set_winsize(self, cols: int, rows: int) -> None:
        """Set PTY window size via ``ioctl(TIOCSWINSZ)`` (triggers SIGWINCH in child)."""
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except (OSError, ValueError) as e:
            logger.warning(f"Failed to set winsize: {e}")

    def read(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Non-blocking read from PTY fd.

        Uses ``select.select`` to avoid blocking indefinitely.

        Parameters
        ----------
        timeout : float
            Max seconds to wait for data.

        Returns
        -------
        bytes or None
            Raw bytes from PTY, or None if nothing available / EOF / error.
        """
        if self.fd is None or not self.alive:
            return None
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if ready:
                data = os.read(self.fd, 65536)  # 64KB buffer
                if data:
                    self.last_activity = time.time()
                    return data
                else:
                    # EOF — process exited
                    self.alive = False
                    return None
        except (OSError, ValueError):
            self.alive = False
            return None

    def write(self, data: bytes) -> None:
        """
        Write input to PTY fd.

        Parameters
        ----------
        data : bytes
            Raw bytes to send to the PTY (keyboard input, control chars, etc.).
        """
        if self.fd is not None and self.alive:
            try:
                os.write(self.fd, data)
                self.last_activity = time.time()
            except OSError as e:
                logger.warning(f"PTY write error: {e}")
                self.alive = False

    def is_idle(self) -> bool:
        """Check if session has been idle beyond ``TERMINAL_IDLE_TIMEOUT``."""
        return (time.time() - self.last_activity) > TERMINAL_IDLE_TIMEOUT

    def cleanup(self) -> None:
        """
        Kill process and all children, close fd, prevent zombies.

        Cleanup sequence:
        1. Close PTY fd (signals EOF to child).
        2. ``SIGTERM`` to process group via ``os.killpg``.
        3. Poll ``waitpid`` for ~1 s for graceful exit.
        4. ``SIGKILL`` + blocking ``waitpid`` if still alive.

        Uses process group kill (``os.killpg``) to ensure child processes
        spawned by opencode (LSP servers, tools, etc.) are also terminated.
        Thread-safe — guarded by ``self._lock``.
        """
        with self._lock:
            if not self.alive and self.pid is None:
                return

            self.alive = False
            pid = self.pid
            fd = self.fd
            self.pid = None
            self.fd = None

        # 1. Close PTY fd first (signals EOF to child)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        if pid is not None:
            # 2. Try graceful SIGTERM to process group
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

            # 3. Wait briefly for graceful exit
            for _ in range(10):  # 1 second total
                try:
                    result = os.waitpid(pid, os.WNOHANG)
                    if result[0] != 0:
                        logger.info(f"Terminal pid={pid} exited gracefully")
                        return
                except ChildProcessError:
                    return  # Already reaped
                time.sleep(0.1)

            # 4. Force kill if still alive
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                os.waitpid(pid, 0)  # Reap zombie
                logger.info(f"Terminal pid={pid} force-killed")
            except (OSError, ChildProcessError):
                pass

    def __del__(self):
        self.cleanup()


# ─── Routes ──────────────────────────────────────────────────────────


@terminal_bp.route("/terminal")
@limiter.limit("30 per minute")
@login_required
def terminal_page():
    """Serve the standalone terminal page."""
    return send_from_directory("interface", "terminal.html", max_age=0)


# ─── WebSocket helpers ───────────────────────────────────────────────


def _ws_auth_check() -> Optional[str]:
    """
    Verify WebSocket connection is authenticated.

    Returns
    -------
    str or None
        User email if session is valid, None otherwise.
        Flask session is available in flask-sock handlers.
    """
    email = session.get("email")
    name = session.get("name")
    if not email or not name:
        return None
    return email


# ─── WebSocket endpoint ──────────────────────────────────────────────

sock = Sock()  # Initialized in server.py via sock.init_app(app)


@sock.route("/ws/terminal")
def terminal_websocket(ws):
    """
    WebSocket endpoint for terminal I/O.

    Bridges browser ↔ PTY using JSON messages.

    Protocol
    --------
    Client → Server:
    - ``{"type": "input", "data": "..."}``  — keyboard input
    - ``{"type": "resize", "cols": N, "rows": N}``  — terminal resize
    - ``{"type": "ping"}``  — keepalive

    Server → Client:
    - ``{"type": "output", "data": "..."}``  — terminal output
    - ``{"type": "exit", "code": N}``  — process exited
    - ``{"type": "error", "message": "..."}``  — error / idle timeout
    - ``{"type": "pong"}``  — keepalive response
    """
    # ─── Auth check ───
    email = _ws_auth_check()
    if not email:
        ws.send(json.dumps({"type": "error", "message": "Not authenticated"}))
        ws.close(1008, "Unauthorized")
        return

    logger.info(f"Terminal WebSocket connected for {email}")

    # ─── Get or create terminal session ───
    terminal = None
    try:
        with _sessions_lock:
            if email in _terminal_sessions and _terminal_sessions[email].alive:
                terminal = _terminal_sessions[email]
                logger.info(f"Reattaching to existing terminal for {email}")
            else:
                # Check max sessions cap
                active_count = sum(1 for s in _terminal_sessions.values() if s.alive)
                if active_count >= TERMINAL_MAX_SESSIONS:
                    ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "message": f"Maximum terminal sessions ({TERMINAL_MAX_SESSIONS}) reached",
                            }
                        )
                    )
                    ws.close(1013, "Too many sessions")
                    return
                terminal = TerminalSession(user_email=email)
                terminal.spawn()
                _terminal_sessions[email] = terminal

        # ─── Reader thread: PTY → WebSocket ───
        reader_alive = threading.Event()
        reader_alive.set()

        def pty_reader():
            """Read PTY output and send to WebSocket."""
            while reader_alive.is_set() and terminal.alive:
                data = terminal.read(timeout=0.05)
                if data:
                    try:
                        text = data.decode("utf-8", errors="replace")
                        ws.send(json.dumps({"type": "output", "data": text}))
                    except Exception:
                        break  # WebSocket closed
                # Check idle timeout
                if terminal.is_idle():
                    try:
                        ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "message": f"Terminal idle for {TERMINAL_IDLE_TIMEOUT}s, disconnecting",
                                }
                            )
                        )
                    except Exception:
                        pass
                    terminal.cleanup()
                    break

            # Process exited or disconnected
            if not terminal.alive:
                try:
                    ws.send(json.dumps({"type": "exit", "code": 0}))
                except Exception:
                    pass

        reader_thread = threading.Thread(target=pty_reader, daemon=True)
        reader_thread.start()

        # ─── Main loop: WebSocket → PTY ───
        while terminal.alive:
            try:
                raw = ws.receive(timeout=5)
                if raw is None:
                    break  # WebSocket closed

                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "input":
                    terminal.write(msg["data"].encode("utf-8"))

                elif msg_type == "resize":
                    cols = int(msg.get("cols", 80))
                    rows = int(msg.get("rows", 24))
                    terminal.resize(cols, rows)

                elif msg_type == "ping":
                    ws.send(json.dumps({"type": "pong"}))
                    terminal.last_activity = time.time()

            except json.JSONDecodeError:
                # Raw binary input (fallback)
                if isinstance(raw, (str, bytes)):
                    terminal.write(raw.encode("utf-8") if isinstance(raw, str) else raw)
            except Exception as e:
                logger.warning(f"Terminal WebSocket error for {email}: {e}")
                break

    except Exception as e:
        logger.exception(f"Terminal fatal error for {email}: {e}")
    finally:
        # ─── Cleanup ───
        reader_alive.clear()
        if terminal:
            terminal.cleanup()
        with _sessions_lock:
            if email in _terminal_sessions:
                del _terminal_sessions[email]
        logger.info(f"Terminal WebSocket disconnected for {email}")
