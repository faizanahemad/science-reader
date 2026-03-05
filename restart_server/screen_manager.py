"""
GNU Screen session manager for service restart operations.

Manages interaction with GNU screen sessions to restart the three
application services (OpenCode Web, OpenCode Serve, Main Python Server).

Responsibilities:
- Check whether screen sessions exist and their ports respond
- Discover startup commands from screen scrollback history or /tmp scripts
- Cache discovered commands for future restarts
- Send Ctrl+C and re-issue startup commands through screen
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------

SERVICES: Dict[str, dict] = {
    "opencode_web": {
        "screen_name": "opencode_server",
        "display_name": "OpenCode Web",
        "description": "opencode web UI (port 3000)",
        "url": "https://opencode.assist-chat.site",
        "port": 3000,
        "command_patterns": [r"opencode\s+web"],
    },
    "opencode_serve": {
        "screen_name": "opencode_local",
        "display_name": "OpenCode Serve",
        "description": "opencode serve backend (port 4096)",
        "port": 4096,
        "command_patterns": [r"opencode\s+serve"],
    },
    "main_server": {
        "screen_name": "science-reader",
        "display_name": "Main Python Server",
        "description": "Flask server.py (port 5000)",
        "url": "https://assist-chat.site",
        "port": 5000,
        "command_patterns": [r"python\s+server\.py"],
        "supports_git_pull": True,
    },
}

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "command_cache.json"
)

WORKDIR_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workdir_config.json"
)


class ScreenManager:
    """Manages GNU screen sessions for service lifecycle operations.

    Typical usage::

        mgr = ScreenManager()
        status = mgr.get_all_statuses()
        success, message, logs = mgr.restart_service("main_server")
    """

    def __init__(self) -> None:
        self._command_cache: dict = self._load_cache()
        self._workdir_config: dict = self._load_workdir_config()

    # ------------------------------------------------------------------
    # Command cache
    # ------------------------------------------------------------------

    def _load_cache(self) -> dict:
        """Load cached startup commands from disk."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as fh:
                    return json.load(fh)
            except Exception:
                logger.warning("Corrupt command cache, starting fresh")
        return {}

    def _save_cache(self) -> None:
        """Persist the command cache to disk."""
        try:
            with open(CACHE_FILE, "w") as fh:
                json.dump(self._command_cache, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save command cache: %s", exc)

    def get_cached_command(self, service_name: str) -> Optional[str]:
        """Return the cached startup command, or *None*."""
        return self._command_cache.get(service_name)

    def cache_command(self, service_name: str, command: str) -> None:
        """Store a startup command in the cache."""
        self._command_cache[service_name] = command
        self._save_cache()

    def clear_cached_command(self, service_name: str) -> None:
        """Remove a cached command."""
        self._command_cache.pop(service_name, None)
        self._save_cache()

    # ------------------------------------------------------------------
    # Working directory config
    # ------------------------------------------------------------------

    def _load_workdir_config(self) -> dict:
        """Load working directory configuration from disk."""
        if os.path.exists(WORKDIR_CONFIG_FILE):
            try:
                with open(WORKDIR_CONFIG_FILE, "r") as fh:
                    return json.load(fh)
            except Exception:
                logger.warning("Corrupt workdir config, starting fresh")
        return {}

    def _save_workdir_config(self) -> None:
        """Persist working directory configuration to disk."""
        try:
            with open(WORKDIR_CONFIG_FILE, "w") as fh:
                json.dump(self._workdir_config, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save workdir config: %s", exc)

    def get_workdir(self, service_name: str) -> Optional[str]:
        """Return the configured working directory, or *None*."""
        return self._workdir_config.get(service_name)

    def set_workdir(self, service_name: str, workdir: Optional[str]) -> None:
        """Set (or clear) the working directory for a service."""
        if workdir:
            self._workdir_config[service_name] = workdir
        else:
            self._workdir_config.pop(service_name, None)
        self._save_workdir_config()

    def get_all_workdirs(self) -> Dict[str, Optional[str]]:
        """Return workdir config for all services."""
        return {name: self._workdir_config.get(name) for name in SERVICES}

    def _ensure_workdir(
        self, screen_name: str, service_name: str, logs: List[str]
    ) -> None:
        """``cd`` into the configured working directory inside the screen.

        If no workdir is configured for the service, this is a no-op.
        """
        workdir = self.get_workdir(service_name)
        if not workdir:
            return
        logs.append(f"Setting workdir: cd '{workdir}'")
        self.send_command(screen_name, f"cd '{workdir}'")
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Screen primitives
    # ------------------------------------------------------------------

    def screen_exists(self, screen_name: str) -> bool:
        """Return *True* if a screen session with *screen_name* is listed."""
        result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
        # screen -ls output format: "	12345.screen_name	(Detached)" etc.
        return bool(re.search(rf"\d+\.{re.escape(screen_name)}\b", result.stdout))

    def create_screen(self, screen_name: str) -> bool:
        """Create a detached screen session. Returns *True* on success."""
        if self.screen_exists(screen_name):
            return True
        result = subprocess.run(
            ["screen", "-dmS", screen_name], capture_output=True, text=True
        )
        time.sleep(0.5)
        return result.returncode == 0

    def send_ctrl_c(self, screen_name: str) -> bool:
        """Send Ctrl+C (SIGINT) to the screen session."""
        result = subprocess.run(
            ["screen", "-S", screen_name, "-X", "stuff", "\x03"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def send_command(self, screen_name: str, command: str) -> bool:
        """Type *command* into the screen session.

        For long commands (>700 chars), writes the command to a temp
        script and sends ``bash /tmp/restart_cmd_<screen>.sh`` instead,
        avoiding screen's ``stuff`` character limit (~768 bytes).
        """
        _STUFF_LIMIT = 700  # conservative; screen limit is ~768

        if len(command) <= _STUFF_LIMIT:
            result = subprocess.run(
                ["screen", "-S", screen_name, "-X", "stuff", f"{command}\n"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0

        # Long command — write to a temp script and execute that instead.
        script_path = f"/tmp/restart_cmd_{screen_name}.sh"
        try:
            with open(script_path, "w") as fh:
                fh.write("#!/usr/bin/env bash\n")
                fh.write(command + "\n")
            os.chmod(script_path, 0o700)
            logger.info(
                "Command is %d chars (>%d), wrote to %s",
                len(command), _STUFF_LIMIT, script_path,
            )
            short_cmd = f"bash {script_path}"
            result = subprocess.run(
                ["screen", "-S", screen_name, "-X", "stuff", f"{short_cmd}\n"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.error("Failed to write command script %s: %s", script_path, exc)
            return False

    def get_scrollback(self, screen_name: str, lines: int = 5000) -> Optional[str]:
        """Dump the screen scrollback buffer and return its text.

        Uses ``screen -X hardcopy -h`` to dump the full scrollback to a
        temporary file, reads it, then cleans up.
        """
        tmp_path = tempfile.mktemp(suffix=".txt", prefix=f"screen_{screen_name}_")
        try:
            # Ensure a large enough scrollback buffer
            subprocess.run(
                ["screen", "-S", screen_name, "-X", "scrollback", str(lines)],
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                ["screen", "-S", screen_name, "-X", "hardcopy", "-h", tmp_path],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("hardcopy failed for %s: %s", screen_name, result.stderr)
                return None

            # screen writes the file asynchronously — give it a moment
            time.sleep(0.5)

            if os.path.exists(tmp_path):
                with open(tmp_path, "r", errors="replace") as fh:
                    return fh.read()
            return None
        except Exception as exc:
            logger.error("get_scrollback(%s) error: %s", screen_name, exc)
            return None
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Port / health checking
    # ------------------------------------------------------------------

    @staticmethod
    def check_port(port: int, timeout: float = 2.0) -> bool:
        """Return *True* if something is listening on ``localhost:port``."""
        try:
            with socket.create_connection(("localhost", port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def get_service_status(self, service_name: str) -> dict:
        """Return a status dict for a single service."""
        config = SERVICES.get(service_name)
        if not config:
            return {"error": f"Unknown service: {service_name}"}

        screen_active = self.screen_exists(config["screen_name"])
        port_open = self.check_port(config["port"])
        cached_cmd = self.get_cached_command(service_name)

        if port_open:
            status = "running"
        elif screen_active:
            status = "stopped"
        else:
            status = "no_screen"

        return {
            "service_name": service_name,
            "display_name": config["display_name"],
            "description": config["description"],
            "screen_name": config["screen_name"],
            "port": config["port"],
            "url": config.get("url"),
            "supports_git_pull": config.get("supports_git_pull", False),
            "screen_exists": screen_active,
            "running": port_open,
            "has_cached_command": cached_cmd is not None,
            "status": status,
            "workdir": self.get_workdir(service_name),
        }

    def get_all_statuses(self) -> Dict[str, dict]:
        """Return status dicts keyed by service name."""
        return {name: self.get_service_status(name) for name in SERVICES}

    # ------------------------------------------------------------------
    # Command discovery
    # ------------------------------------------------------------------

    def discover_command(self, service_name: str) -> Optional[str]:
        """Try to find the startup command for a service.

        Lookup order:
        1. In-memory / on-disk cache
        2. Screen scrollback history
        3. Known ``/tmp`` startup scripts

        Returns *None* when nothing can be found.
        """
        config = SERVICES.get(service_name)
        if not config:
            return None

        # 1. Cache
        cached = self.get_cached_command(service_name)
        if cached:
            logger.info("Using cached command for %s", service_name)
            return cached

        # 2. Scrollback
        if self.screen_exists(config["screen_name"]):
            scrollback = self.get_scrollback(config["screen_name"])
            if scrollback:
                cmd = self._parse_command_from_scrollback(
                    scrollback, config["command_patterns"]
                )
                if cmd:
                    self.cache_command(service_name, cmd)
                    logger.info(
                        "Discovered command for %s from scrollback", service_name
                    )
                    return cmd

        # 3. /tmp startup scripts
        script = self._find_startup_script(service_name)
        if script:
            cmd = self._parse_command_from_script(script, config["command_patterns"])
            if cmd:
                self.cache_command(service_name, cmd)
                logger.info("Discovered command for %s from %s", service_name, script)
                return cmd

        return None

    # -- Scrollback parsing --

    @staticmethod
    def _parse_command_from_scrollback(
        scrollback: str, patterns: List[str]
    ) -> Optional[str]:
        """Search scrollback (most-recent-first) for a line matching *patterns*.

        Terminal scrollback wraps long commands across multiple visual lines.
        When a match is found (e.g. ``python server.py``), we walk backwards
        to collect preceding lines that are part of the same command —
        typically ``KEY=VALUE`` env-var prefixes or line continuations.

        Heuristic for wrapped command lines (walk backwards while):
        - Line contains ``=`` (env var assignment like ``FOO=bar``)
        - Line ends with ``\\`` (explicit line continuation)
        - Line is non-empty and has no shell prompt (``$``, ``#``, ``%``)
        """
        lines = scrollback.strip().split("\n")
        # Use raw (non-stripped) lines for index tracking, strip for matching
        stripped = [l.strip() for l in lines]

        # Search from the end (most recent) backwards
        for i in range(len(stripped) - 1, -1, -1):
            line = stripped[i]
            if not line:
                continue
            for pattern in patterns:
                if not re.search(pattern, line):
                    continue

                # Found the command line. Strip shell prompt from it.
                cleaned = re.sub(r"^[\w@:\-~/.\\]+[#$%>]\s*", "", line)
                command_parts = [cleaned if cleaned else line]

                # Walk backwards to collect wrapped/continuation lines
                j = i - 1
                while j >= 0:
                    prev = stripped[j]
                    if not prev:
                        break  # empty line = different command

                    # Stop if line looks like a shell prompt output
                    # (e.g. "user@host:~$" or command output)
                    has_prompt = re.match(
                        r"^[\w@:\-~/.\\]+[#$%>]\s", prev
                    )
                    if has_prompt:
                        # The prompt line itself might start with env vars
                        after_prompt = re.sub(
                            r"^[\w@:\-~/.\\]+[#$%>]\s*", "", prev
                        )
                        if after_prompt and "=" in after_prompt.split()[0]:
                            command_parts.insert(0, after_prompt)
                        break

                    # Continuation heuristics:
                    # - contains KEY=VALUE (env var prefix)
                    # - ends with \\ (explicit continuation)
                    # - looks like a token continuation of the command
                    first_token = prev.split()[0] if prev.split() else ""
                    is_env_var = "=" in first_token
                    is_continuation = prev.endswith("\\")
                    # Also accept lines that are purely word chars / paths
                    # (part of a wrapped command, no output-like patterns)
                    is_word_fragment = bool(
                        re.match(r"^[\w=\-./\"\':;,{}\[\]@+]+", prev)
                    )

                    if is_env_var or is_continuation or is_word_fragment:
                        # Strip trailing backslash from continuation
                        part = prev.rstrip("\\" ).rstrip()
                        command_parts.insert(0, part)
                        j -= 1
                    else:
                        break

                # Join all parts into a single command string.
                # Parts are visual line fragments, so join with space.
                full_command = " ".join(command_parts)
                # Clean up any double spaces from joining
                full_command = re.sub(r"\s{2,}", " ", full_command).strip()
                return full_command

        return None

    # -- /tmp script discovery --

    @staticmethod
    def _find_startup_script(service_name: str) -> Optional[str]:
        """Return the path to a known startup script, if it exists."""
        candidates: Dict[str, List[str]] = {
            "main_server": ["/tmp/run_science_reader.sh"],
            "opencode_web": ["/tmp/run_opencode.sh", "/tmp/run_opencode_server.sh"],
            "opencode_serve": [
                "/tmp/run_opencode_local.sh",
                "/tmp/run_opencode_serve.sh",
            ],
        }
        for path in candidates.get(service_name, []):
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _parse_command_from_script(
        script_path: str, patterns: List[str]
    ) -> Optional[str]:
        """Extract the startup command from a shell script.

        Handles both ``export VAR=val`` (converted to inline) and
        ``VAR=val command`` formats.
        """
        try:
            with open(script_path, "r") as fh:
                content = fh.read()
        except Exception as exc:
            logger.error("Cannot read %s: %s", script_path, exc)
            return None

        env_lines: List[str] = []
        for raw_line in content.strip().split("\n"):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                env_lines.append(line)
            else:
                for pattern in patterns:
                    if re.search(pattern, line):
                        if env_lines:
                            inline = " ".join(
                                ln.replace("export ", "", 1) for ln in env_lines
                            )
                            return f"{inline} {line}"
                        return line
        return None

    # ------------------------------------------------------------------
    # Restart orchestration
    # ------------------------------------------------------------------

    def _git_pull_in_screen(
        self, screen_name: str, logs: List[str]
    ) -> Tuple[bool, str]:
        """Run ``git pull`` inside a screen session and wait for it to complete.

        The pull runs in whatever directory the screen shell is currently in,
        which is the same cwd the service was started from.

        We detect completion by writing a sentinel file after ``git pull``
        finishes, then polling for that file.

        Returns (success, message).
        """
        sentinel = f"/tmp/.git_pull_done_{screen_name}"

        # Clean up any stale sentinel
        try:
            os.unlink(sentinel)
        except FileNotFoundError:
            pass

        logs.append("Running git pull…")

        # Send: git pull && echo OK > sentinel || echo FAIL > sentinel
        pull_cmd = (
            f"git pull && echo OK > {sentinel} || echo FAIL > {sentinel}"
        )
        self.send_command(screen_name, pull_cmd)

        # Poll for the sentinel file (git pull can take a while on large repos)
        max_wait = 60
        waited = 0
        while waited < max_wait:
            time.sleep(2)
            waited += 2
            if os.path.exists(sentinel):
                break
            if waited % 10 == 0:
                logs.append(f"Waiting for git pull… ({waited}s)")

        if not os.path.exists(sentinel):
            logs.append("git pull timed out")
            return False, f"git pull did not complete within {max_wait}s"

        # Read result
        try:
            with open(sentinel, "r") as fh:
                result = fh.read().strip()
            os.unlink(sentinel)
        except Exception:
            result = "UNKNOWN"

        if result == "OK":
            # Capture the git pull output from scrollback
            time.sleep(0.5)
            scrollback = self.get_scrollback(screen_name, lines=30)
            if scrollback:
                # Show last few meaningful lines
                recent = [
                    ln.strip() for ln in scrollback.strip().split("\n")
                    if ln.strip()
                ][-10:]
                for ln in recent:
                    logs.append(f"  git: {ln}")
            logs.append("git pull succeeded")
            return True, "git pull OK"

        logs.append(f"git pull failed (result: {result})")
        # Show scrollback for error context
        scrollback = self.get_scrollback(screen_name, lines=30)
        if scrollback:
            recent = [
                ln.strip() for ln in scrollback.strip().split("\n")
                if ln.strip()
            ][-10:]
            for ln in recent:
                logs.append(f"  git: {ln}")
        return False, "git pull failed — check logs above"

    def restart_service(
        self,
        service_name: str,
        command_override: Optional[str] = None,
        git_pull: bool = False,
    ) -> Tuple[bool, str, List[str]]:
        """Restart a service inside its screen session.

        Parameters
        ----------
        service_name:
            Key in ``SERVICES``.
        command_override:
            If given, use this command instead of discovering one.
            The override is also cached for future restarts.
        git_pull:
            If *True*, run ``git pull`` inside the screen session before
            restarting.  Only allowed for services with
            ``supports_git_pull=True`` in their config.

        Returns
        -------
        (success, final_message, log_messages)
        """
        logs: List[str] = []
        config = SERVICES.get(service_name)
        if not config:
            return False, f"Unknown service: {service_name}", logs

        screen_name = config["screen_name"]
        port = config["port"]

        # 1. Determine startup command
        if command_override:
            command = command_override
            self.cache_command(service_name, command)
            logs.append("Using provided command override")
        else:
            command = self.discover_command(service_name)

        if not command:
            return (
                False,
                (
                    f"Could not determine startup command for {config['display_name']}. "
                    f"Please provide the command manually or ensure the screen "
                    f"session '{screen_name}' has scrollback history."
                ),
                logs,
            )

        # Only log a truncated preview (commands often contain secrets)
        preview = command[:100] + ("…" if len(command) > 100 else "")
        logs.append(f"Startup command resolved ({len(command)} chars): {preview}")

        # 2. Ensure screen exists
        if not self.screen_exists(screen_name):
            logs.append(f"Screen '{screen_name}' not found — creating")
            if not self.create_screen(screen_name):
                return False, f"Failed to create screen session '{screen_name}'", logs
            logs.append(f"Created screen '{screen_name}'")
            time.sleep(1)
        else:
            logs.append(f"Screen '{screen_name}' exists")

        # 3. Stop the current process
        if self.check_port(port):
            logs.append(f"Service running on port {port} — sending Ctrl+C")
            self.send_ctrl_c(screen_name)
            time.sleep(1)
            self.send_ctrl_c(screen_name)  # second for good measure

            # 4. Wait for process to die
            max_wait = 15
            waited = 0
            while self.check_port(port) and waited < max_wait:
                time.sleep(1)
                waited += 1
                if waited % 3 == 0:
                    logs.append(f"Waiting for process to stop… ({waited}s)")

            if self.check_port(port):
                logs.append("Process still alive — attempting kill")
                self.send_command(
                    screen_name, "kill %1 2>/dev/null; kill -9 %1 2>/dev/null"
                )
                time.sleep(3)
                if self.check_port(port):
                    return False, f"Failed to stop service on port {port}", logs

            logs.append("Process stopped")
        else:
            logs.append(f"No process running on port {port}")

        # 4a. Ensure correct working directory
        self._ensure_workdir(screen_name, service_name, logs)
        # 4b. Git pull (after process is stopped, before restart)
        if git_pull:
            if not config.get("supports_git_pull"):
                logs.append(f"Git pull not supported for {config['display_name']} — skipping")
            else:
                pull_ok, pull_msg = self._git_pull_in_screen(screen_name, logs)
                if not pull_ok:
                    return False, pull_msg, logs

        # Small settling pause
        time.sleep(2)

        # 5. Send startup command
        logs.append("Sending startup command…")
        self.send_command(screen_name, command)

        # 6. Wait for service to come up
        max_wait = 60
        waited = 0
        while not self.check_port(port) and waited < max_wait:
            time.sleep(2)
            waited += 2
            if waited % 10 == 0:
                logs.append(f"Waiting for service to start… ({waited}s)")

        if self.check_port(port):
            logs.append(f"Service '{config['display_name']}' is running on port {port}")
            return True, f"Successfully restarted {config['display_name']}", logs

        logs.append(f"Service did not respond within {max_wait}s")
        return (
            False,
            (
                f"{config['display_name']} did not come up on port {port} "
                f"within {max_wait}s"
            ),
            logs,
        )

    # ------------------------------------------------------------------
    # Diagnostics helpers
    # ------------------------------------------------------------------

    def get_recent_output(self, service_name: str, lines: int = 200) -> Optional[str]:
        """Get recent screen output for diagnostics."""
        config = SERVICES.get(service_name)
        if not config:
            return None
        if not self.screen_exists(config["screen_name"]):
            return None
        return self.get_scrollback(config["screen_name"], lines=lines)
