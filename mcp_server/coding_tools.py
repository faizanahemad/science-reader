"""
MCP coding & file tools server application.

Creates a ``FastMCP`` instance that exposes file system navigation tools
and a simple todo list manager over the streamable-HTTP transport on port 8108.

All file system tools operate relative to the server's working directory
(``os.getcwd()``) and enforce path-traversal safety — no operation can
escape the project root.

Tools
-----
File system:
  ``fs_read_file``   — Read file contents, optionally a line range.
  ``fs_write_file``  — Write (create or overwrite) a file.
  ``fs_list_dir``    — List directory entries.
  ``fs_find_files``  — Find files by glob pattern.
  ``fs_grep``        — Search file contents by regular expression.
  ``fs_file_info``   — Get path metadata (exists, type, size, mtime).

Todo list:
  ``todo_write``     — Write/replace the todo list (global or per-conversation).
  ``todo_read``      — Read the current todo list.

Authentication and rate limiting are handled by the same Starlette
middleware used by the web-search MCP server (``mcp_server.mcp_app``).

Entry point: ``create_coding_tools_mcp_app(jwt_secret, rate_limit)``
returns a Starlette ``ASGIApp`` ready to be run with uvicorn.

Launcher: ``start_coding_tools_mcp_server()`` boots the server in a
daemon thread alongside the main Flask application.
"""

from __future__ import annotations

import contextlib
import fnmatch
import glob as _glob
import json
import logging
import os
import re
import threading
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from mcp_server.mcp_app import (
    JWTAuthMiddleware,
    RateLimitMiddleware,
    _health_check,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")

# Maximum characters returned by fs_read_file / fs_grep to keep results LLM-friendly
_MAX_READ_CHARS = 100_000
_MAX_GREP_MATCHES = 200


# ---------------------------------------------------------------------------
# Path safety helpers
# ---------------------------------------------------------------------------


def _project_root() -> str:
    """Return the server's working directory (project root)."""
    return os.getcwd()


def _resolve_safe_path(rel_or_abs: str) -> str:
    """Resolve a path and verify it stays within the project root.

    Parameters
    ----------
    rel_or_abs:
        A path that may be relative (resolved from cwd) or absolute.

    Returns
    -------
    str
        Absolute, normalised path guaranteed to be inside the project root.

    Raises
    ------
    ValueError
        If the resolved path escapes the project root.
    """
    root = _project_root()
    resolved = os.path.normpath(os.path.join(root, rel_or_abs))
    if not resolved.startswith(root):
        raise ValueError(
            f"Path '{rel_or_abs}' escapes the project root '{root}'. "
            "Only paths within the project directory are allowed."
        )
    return resolved


# ---------------------------------------------------------------------------
# Todo helpers
# ---------------------------------------------------------------------------

_TODO_FILENAME = "todo.json"


def _todo_path(scope: str, conversation_id: str) -> str:
    """Return the absolute path to the todo JSON file.

    Parameters
    ----------
    scope:
        ``"global"`` — stored at ``<STORAGE_DIR>/todo.json``.
        ``"conversation"`` — stored at
        ``<STORAGE_DIR>/conversations/<conversation_id>/todo.json``.
    conversation_id:
        Required when ``scope == "conversation"``.
    """
    root = _project_root()
    if scope == "conversation":
        if not conversation_id:
            raise ValueError("conversation_id is required when scope='conversation'.")
        return os.path.join(
            root, STORAGE_DIR, "conversations", conversation_id, _TODO_FILENAME
        )
    return os.path.join(root, STORAGE_DIR, _TODO_FILENAME)


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_coding_tools_mcp_app(
    jwt_secret: str, rate_limit: int = 10
) -> tuple[ASGIApp, Any]:
    """Create the MCP coding & file tools server as an ASGI application.

    Returns a tuple of ``(asgi_app, fastmcp_instance)`` so the caller
    can manage the FastMCP session lifecycle if needed.

    Parameters
    ----------
    jwt_secret:
        HS256 secret for JWT verification.
    rate_limit:
        Maximum tool calls per token per minute.

    Returns
    -------
    tuple[ASGIApp, FastMCP]
        The wrapped Starlette ASGI app and the underlying FastMCP instance.
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "Coding & File Tools Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: fs_read_file
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_read_file(
        user_email: str,
        path: str,
        start_line: int = 1,
        end_line: int = 0,
    ) -> str:
        """Read the contents of a file, optionally restricted to a line range.

        Paths are relative to the project root (server working directory).
        Supports plain text files and PDF files (.pdf extension is auto-detected).
        For text files: use start_line / end_line to read a specific section.
        For PDF files: returns extracted text grouped by page (start_line/end_line ignored).

        Args:
            user_email: Email of the requesting user.
            path: File path (relative to project root or absolute). .pdf files are read as PDFs.
            start_line: First line to return (1-indexed, default 1). Text files only.
            end_line: Last line to return inclusive (0 = read to end). Text files only.

        Returns:
            File contents as a string. PDFs return page-separated text.
            Returns a JSON error object if the file does not exist.
        """
        try:
            abs_path = _resolve_safe_path(path)
            if not os.path.isfile(abs_path):
                return json.dumps({"error": f"File not found: {path}"})

            # PDF branch — use pdfplumber (primary) or freePDFReader fallback
            if abs_path.lower().endswith(".pdf"):
                try:
                    import pdfplumber
                    with pdfplumber.open(abs_path) as pdf:
                        pages_text = []
                        for i, page in enumerate(pdf.pages, 1):
                            text = page.extract_text()
                            if text and text.strip():
                                pages_text.append(f"--- Page {i} ---\n{text.strip()}")
                    if not pages_text:
                        raise ValueError("pdfplumber found no extractable text in PDF")
                    full_text = "\n\n".join(pages_text)
                except ImportError:
                    from base import freePDFReader
                    full_text = freePDFReader(abs_path)
                    if not full_text or not full_text.strip():
                        raise ValueError("freePDFReader found no extractable text in PDF")
                if len(full_text) > _MAX_READ_CHARS:
                    full_text = full_text[:_MAX_READ_CHARS] + "\n\n... [truncated — PDF too large]"
                return full_text

            # Image branch — vision LLM analysis
            _IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
            if os.path.splitext(abs_path)[1].lower() in _IMAGE_EXTS:
                try:
                    from code_common.call_llm import call_llm
                    from common import VERY_CHEAP_LLM
                    from endpoints.utils import keyParser
                    _keys = keyParser({})
                    system = "You are an expert image analyst. Produce a comprehensive analysis."
                    prompt = (
                        "Analyse this image and return exactly the following four sections:\n\n"
                        "**OCR**\nTranscribe all readable text, preserving structure.\n\n"
                        "**Scene Description**\nDescribe setting, layout, visual composition.\n\n"
                        "**Objects & Elements**\nBullet list of all key objects and visual elements.\n\n"
                        "**Summary**\n2-3 sentence summary of what this image communicates."
                    )
                    result = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                                     text=prompt, images=[abs_path],
                                     temperature=0.0, stream=False, system=system)
                    return result if isinstance(result, str) else "(empty)"
                except Exception as img_exc:
                    logger.exception("fs_read_file image error: %s", img_exc)
                    return json.dumps({"error": f"Image analysis failed: {img_exc}"})

            # Text branch
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()

            total = len(lines)
            s = max(1, start_line) - 1  # 0-indexed
            e = total if end_line <= 0 else min(end_line, total)

            selected = lines[s:e]
            numbered = "".join(
                f"{s + i + 1}: {line}" for i, line in enumerate(selected)
            )

            if len(numbered) > _MAX_READ_CHARS:
                numbered = numbered[:_MAX_READ_CHARS] + "\n... [truncated]"

            return numbered
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_read_file error: %s", exc)
            return json.dumps({"error": str(exc)})


    # -----------------------------------------------------------------
    # Tool 1b: fs_read_pdf  (dedicated PDF reader with page selection)
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_read_pdf(
        user_email: str,
        path: str,
        pages: str = "",
    ) -> str:
        """Read a PDF with optional page selection.

        Page selection via `pages` argument:
          - Empty string or omit: all pages.
          - Single page:  '3'
          - Range:        '1-5'
          - List:         '1,3,5'

        Returns up to 100,000 characters of extracted text prefixed by a metadata
        header that always reports which pages were read, total page count, and
        whether truncation was applied.

        Args:
            user_email: Email of the requesting user.
            path: PDF file path (relative to project root).
            pages: Page selection string (empty = all pages).

        Returns:
            Metadata header + page-separated text, or JSON error.
        """
        def _parse(spec):
            if not spec or not spec.strip():
                return None
            spec = spec.strip()
            if "-" in spec and "," not in spec:
                parts = spec.split("-", 1)
                try:
                    return list(range(int(parts[0]) - 1, int(parts[1])))
                except ValueError:
                    pass
            if "," in spec:
                try:
                    return sorted({int(p.strip()) - 1 for p in spec.split(",") if p.strip()})
                except ValueError:
                    pass
            try:
                return [int(spec) - 1]
            except ValueError:
                return None

        try:
            abs_path = _resolve_safe_path(path)
            if not os.path.isfile(abs_path):
                return json.dumps({"error": f"File not found: {path}"})
            if not abs_path.lower().endswith(".pdf"):
                return json.dumps({"error": f"Not a PDF file: {path}"})

            page_indices = _parse(pages)
            import pdfplumber
            with pdfplumber.open(abs_path) as _pdf:
                total = len(_pdf.pages)
                selected = list(range(total)) if page_indices is None else [i for i in page_indices if 0 <= i < total]
                pages_text = []
                for idx in selected:
                    t = _pdf.pages[idx].extract_text()
                    if t and t.strip():
                        pages_text.append(f"--- Page {idx + 1} ---\n{t.strip()}")
            full_text = "\n\n".join(pages_text)
            if not full_text.strip():
                return json.dumps({"error": "No extractable text in PDF"})
            truncated = len(full_text) > _MAX_READ_CHARS
            if truncated:
                full_text = full_text[:_MAX_READ_CHARS]
            read_label = (
                ", ".join(str(i + 1) for i in sorted(page_indices))
                if page_indices is not None else "all pages"
            )
            header = (
                f"[PDF: {os.path.basename(path)} | Reading: {read_label} | "
                f"{total} total pages | Truncated: {'Yes' if truncated else 'No'}]\n\n"
            )
            return header + full_text
        except ImportError:
            try:
                from base import freePDFReader
                text = freePDFReader(abs_path)
                truncated = len(text) > _MAX_READ_CHARS
                if truncated:
                    text = text[:_MAX_READ_CHARS]
                return f"[PDF: {os.path.basename(path)} | Truncated: {'Yes' if truncated else 'No'}]\n\n" + text
            except Exception as fe:
                return json.dumps({"error": f"PDF read failed: {fe}"})
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_read_pdf error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 1c: fs_get_file_structure_and_summary
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_get_file_structure_and_summary(
        user_email: str,
        path: str,
    ) -> str:
        """Get LLM-generated structure and summary of a file.

        Supports text, Markdown, PDF, and image files. An LLM orchestrates up to
        5 reading iterations to build full understanding, then returns a structured
        outline and a 2-3 paragraph summary.

        Args:
            user_email: Email of the requesting user.
            path: File path (relative to project root).

        Returns:
            Formatted text with STRUCTURE and SUMMARY sections, or JSON error.
        """
        import json as _json
        try:
            abs_path = _resolve_safe_path(path)
            if not os.path.isfile(abs_path):
                return _json.dumps({"error": f"File not found: {path}"})

            from endpoints.utils import keyParser
            from code_common.call_llm import call_llm
            from common import VERY_CHEAP_LLM
            _keys = keyParser({})
            ext = os.path.splitext(abs_path)[1].lower()
            basename = os.path.basename(abs_path)
            file_size = os.path.getsize(abs_path)
            MAX_ITER = 5
            BUDGET = 12_000
            _IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})

            # Image: single-shot
            if ext in _IMAGE_EXTS:
                system = "You are an expert image analyst."
                prompt = (
                    "Analyse this image and return exactly the following four sections:\n\n"
                    "**OCR**\nTranscribe all visible text.\n\n"
                    "**Scene Description**\nDescribe setting and composition.\n\n"
                    "**Objects & Elements**\nBullet list of key objects.\n\n"
                    "**Summary**\n2-3 sentence summary."
                )
                desc = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                                text=prompt, images=[abs_path],
                                temperature=0.0, stream=False, system=system)
                return f"[File: {basename} | Type: image]\n\n{desc}"

            SYSTEM = (
                "You are a file analysis assistant. You read files in parts and build structural understanding.\n"
                "Respond ONLY with valid JSON in one of two schemas:\n"
                'If you need more: {"action": "read_more", "reason": "...", '
                '"request": {"start_line": N, "end_line": N}} (for PDFs use "pages": "N-M")\n'
                'When ready: {"action": "done", "structure": [...], "summary": "..."}'
            )

            is_pdf = ext == ".pdf"
            is_md = ext in (".md", ".markdown")

            if is_pdf:
                try:
                    import pdfplumber
                    with pdfplumber.open(abs_path) as _p:
                        total_pages = len(_p.pages)
                        pages_text = []
                        for idx in range(min(5, total_pages)):
                            t = _p.pages[idx].extract_text()
                            if t and t.strip():
                                pages_text.append(f"--- Page {idx+1} ---\n{t.strip()}")
                    accumulated = "\n\n".join(pages_text)[:BUDGET]
                except Exception:
                    from base import freePDFReader
                    accumulated = freePDFReader(abs_path)[:BUDGET]
                    total_pages = -1
                file_meta = {"name": basename, "type": "pdf", "total_pages": total_pages}
            else:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read()
                headers = [l.strip() for l in raw.splitlines() if l.strip().startswith("#")] if is_md else []
                file_meta = {"name": basename, "type": "markdown" if is_md else "text",
                             "total_lines": raw.count("\n") + 1,
                             "headers": headers[:50]}
                accumulated = raw[:BUDGET]

            structure, summary = [], ""
            for iteration in range(1, MAX_ITER + 1):
                user_msg = (
                    f"FILE METADATA: {_json.dumps(file_meta)}\n\n"
                    f"CONTENT (iteration {iteration}/{MAX_ITER}):\n{accumulated}\n\n"
                    f"{'FINAL iteration — respond with action=done.' if iteration == MAX_ITER else ''}"
                )
                raw_resp = call_llm(keys=_keys, model_name=VERY_CHEAP_LLM[0],
                                   text=user_msg, temperature=0.0, stream=False, system=SYSTEM)
                try:
                    clean = raw_resp.strip()
                    if clean.startswith("```"):
                        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
                    llm_json = _json.loads(clean)
                except Exception:
                    import re as _re
                    m = _re.search(r"\{.*\}", raw_resp, _re.DOTALL)
                    llm_json = _json.loads(m.group()) if m else None

                if llm_json is None or llm_json.get("action") == "done" or iteration == MAX_ITER:
                    structure = (llm_json or {}).get("structure", [])
                    summary = (llm_json or {}).get("summary", "")
                    break

                req = llm_json.get("request", {})
                if is_pdf and "pages" in req:
                    try:
                        import pdfplumber
                        spec = req["pages"]
                        parts = spec.split("-", 1)
                        pidx = list(range(int(parts[0]) - 1, int(parts[1])))
                        with pdfplumber.open(abs_path) as _p:
                            more = []
                            for idx in pidx:
                                if 0 <= idx < len(_p.pages):
                                    t = _p.pages[idx].extract_text()
                                    if t:
                                        more.append(f"--- Page {idx+1} ---\n{t.strip()}")
                        accumulated += "\n\n" + "\n\n".join(more)[:BUDGET // 2]
                    except Exception:
                        break
                else:
                    s = max(0, req.get("start_line", 1) - 1)
                    e_line = req.get("end_line", s + 100)
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                        all_lines = fh.readlines()
                    accumulated += "\n\n" + "".join(all_lines[s:min(len(all_lines), e_line)])[:BUDGET // 2]

            structure_txt = "\n".join(structure) if structure else "(no structure extracted)"
            out = (
                f"[File: {basename} | Type: {file_meta.get('type', ext)} | Size: {file_size:,} bytes]\n\n"
                f"STRUCTURE:\n{structure_txt}\n\nSUMMARY:\n{summary}"
            )
            return out[:_MAX_READ_CHARS]
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_get_file_structure_and_summary error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 2: fs_write_file
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_write_file(
        user_email: str,
        path: str,
        content: str,
    ) -> str:
        """Write content to a file, creating it (and any parent directories) if needed.

        Overwrites the file if it already exists. Paths are relative to the
        project root. Use this for creating new files or replacing entire files.
        For targeted line-level edits, prefer reading the file first, modifying
        the relevant lines, and writing back.

        Args:
            user_email: Email of the requesting user.
            path: Destination file path (relative to project root or absolute).
            content: Full file content to write.

        Returns:
            JSON object with {"status": "ok", "path": "<absolute>", "bytes": N}
            or {"error": "..."} on failure.
        """
        try:
            abs_path = _resolve_safe_path(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            encoded = content.encode("utf-8")
            with open(abs_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return json.dumps({"status": "ok", "path": abs_path, "bytes": len(encoded)})
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_write_file error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 3: fs_list_dir
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_list_dir(
        user_email: str,
        path: str = ".",
    ) -> str:
        """List the entries in a directory.

        Returns file names, types (file/dir), and sizes. Hidden files and
        __pycache__ entries are included by default but clearly labelled.

        Args:
            user_email: Email of the requesting user.
            path: Directory path (relative to project root, default ".").

        Returns:
            JSON array of objects with fields: name, type, size_bytes, modified.
            Returns a JSON error object if path does not exist or is not a directory.
        """
        try:
            abs_path = _resolve_safe_path(path)
            if not os.path.isdir(abs_path):
                return json.dumps({"error": f"Not a directory: {path}"})

            entries = []
            for name in sorted(os.listdir(abs_path)):
                full = os.path.join(abs_path, name)
                try:
                    stat = os.stat(full)
                    entries.append(
                        {
                            "name": name,
                            "type": "dir" if os.path.isdir(full) else "file",
                            "size_bytes": stat.st_size,
                            "modified": stat.st_mtime,
                        }
                    )
                except OSError:
                    entries.append({"name": name, "type": "unknown"})

            return json.dumps(entries)
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_list_dir error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 4: fs_find_files
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_find_files(
        user_email: str,
        pattern: str,
        base_path: str = ".",
        max_results: int = 100,
    ) -> str:
        """Find files matching a glob pattern under a base directory.

        Common patterns: "*.py", "**/*.json", "src/**/*.ts".
        The search is always recursive (** is supported).

        Args:
            user_email: Email of the requesting user.
            pattern: Glob pattern relative to base_path.
            base_path: Directory to search in (relative to project root, default ".").
            max_results: Maximum number of paths to return (default 100).

        Returns:
            JSON array of matching paths relative to the project root.
            Returns a JSON error object if base_path does not exist.
        """
        try:
            abs_base = _resolve_safe_path(base_path)
            if not os.path.isdir(abs_base):
                return json.dumps({"error": f"Not a directory: {base_path}"})

            root = _project_root()
            full_pattern = os.path.join(abs_base, pattern)
            matches = _glob.glob(full_pattern, recursive=True)

            # Return paths relative to project root for readability
            rel_matches = []
            for m in sorted(matches)[:max_results]:
                try:
                    rel_matches.append(os.path.relpath(m, root))
                except ValueError:
                    rel_matches.append(m)

            return json.dumps(rel_matches)
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_find_files error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 5: fs_grep
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_grep(
        user_email: str,
        pattern: str,
        path: str = ".",
        include_glob: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100,
    ) -> str:
        """Search file contents for lines matching a regular expression.

        Recursively searches all files under path that match include_glob.
        Returns matching lines with file path and line number.

        Args:
            user_email: Email of the requesting user.
            pattern: Python regular expression to search for.
            path: File or directory to search (relative to project root, default ".").
            include_glob: Only search files whose names match this glob (e.g. "*.py").
            case_sensitive: Whether to match case-sensitively (default True).
            max_results: Maximum number of matching lines to return (default 100).

        Returns:
            JSON array of match objects with fields: file, line_number, line.
            Returns a JSON error object on invalid regex or path issues.
        """
        try:
            abs_path = _resolve_safe_path(path)
            flags = 0 if case_sensitive else re.IGNORECASE
            compiled = re.compile(pattern, flags)
        except re.error as re_err:
            return json.dumps({"error": f"Invalid regex: {re_err}"})
        except ValueError as ve:
            return json.dumps({"error": str(ve)})

        try:
            root = _project_root()
            results = []

            def _search_file(file_path: str) -> None:
                if len(results) >= max_results:
                    return
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if compiled.search(line):
                                results.append(
                                    {
                                        "file": os.path.relpath(file_path, root),
                                        "line_number": lineno,
                                        "line": line.rstrip("\n"),
                                    }
                                )
                                if len(results) >= max_results:
                                    return
                except (OSError, UnicodeDecodeError):
                    pass

            if os.path.isfile(abs_path):
                _search_file(abs_path)
            elif os.path.isdir(abs_path):
                for dirpath, _dirs, filenames in os.walk(abs_path):
                    for fname in sorted(filenames):
                        if fnmatch.fnmatch(fname, include_glob):
                            _search_file(os.path.join(dirpath, fname))
                        if len(results) >= max_results:
                            break
            else:
                return json.dumps({"error": f"Path not found: {path}"})

            return json.dumps(results)
        except Exception as exc:
            logger.exception("fs_grep error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 6: fs_file_info
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_file_info(
        user_email: str,
        path: str,
    ) -> str:
        """Get metadata about a file or directory path.

        Useful for checking existence, type, and size before reading or writing.

        Args:
            user_email: Email of the requesting user.
            path: Path to inspect (relative to project root or absolute).

        Returns:
            JSON object with fields: exists, type ("file"/"dir"/"other"),
            size_bytes, modified (Unix timestamp), abs_path, rel_path.
        """
        try:
            abs_path = _resolve_safe_path(path)
            root = _project_root()

            if not os.path.exists(abs_path):
                return json.dumps(
                    {
                        "exists": False,
                        "abs_path": abs_path,
                        "rel_path": os.path.relpath(abs_path, root),
                    }
                )

            stat = os.stat(abs_path)
            if os.path.isfile(abs_path):
                ftype = "file"
            elif os.path.isdir(abs_path):
                ftype = "dir"
            else:
                ftype = "other"

            return json.dumps(
                {
                    "exists": True,
                    "type": ftype,
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                    "abs_path": abs_path,
                    "rel_path": os.path.relpath(abs_path, root),
                }
            )
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_file_info error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 7: todo_write
    # -----------------------------------------------------------------

    @mcp.tool()
    def todo_write(
        user_email: str,
        todos: str,
        scope: str = "global",
        conversation_id: str = "",
    ) -> str:
        """Write (replace) the todo list.

        Stores a structured task list as JSON. Each task should be an object
        with at least a "content" field. Recommended fields:
          - content: string — task description
          - status: "pending" | "in_progress" | "completed" | "cancelled"
          - priority: "high" | "medium" | "low"
          - id: string — unique identifier (optional, auto-assigned if missing)

        Args:
            user_email: Email of the requesting user.
            todos: JSON string — an array of task objects.
            scope: "global" (default) or "conversation". Global todos are
                   shared across all conversations; conversation todos are
                   scoped to a single conversation.
            conversation_id: Required when scope="conversation".

        Returns:
            JSON object with {"status": "ok", "count": N, "path": "..."} or
            {"error": "..."} on failure.
        """
        try:
            # Validate todos is valid JSON array
            parsed = json.loads(todos)
            if not isinstance(parsed, list):
                return json.dumps({"error": "'todos' must be a JSON array."})

            # Auto-assign IDs if missing
            for i, task in enumerate(parsed):
                if isinstance(task, dict) and "id" not in task:
                    task["id"] = str(i + 1)

            todo_file = _todo_path(scope, conversation_id)
            os.makedirs(os.path.dirname(todo_file), exist_ok=True)

            with open(todo_file, "w", encoding="utf-8") as fh:
                json.dump(parsed, fh, indent=2)

            return json.dumps({"status": "ok", "count": len(parsed), "path": todo_file})
        except json.JSONDecodeError as je:
            return json.dumps({"error": f"Invalid JSON in todos: {je}"})
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("todo_write error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 8: todo_read
    # -----------------------------------------------------------------

    @mcp.tool()
    def todo_read(
        user_email: str,
        scope: str = "global",
        conversation_id: str = "",
    ) -> str:
        """Read the current todo list.

        Args:
            user_email: Email of the requesting user.
            scope: "global" (default) or "conversation".
            conversation_id: Required when scope="conversation".

        Returns:
            JSON array of task objects, or {"todos": [], "message": "No todos found"}
            if no todo list has been created yet.
        """
        try:
            todo_file = _todo_path(scope, conversation_id)

            if not os.path.isfile(todo_file):
                return json.dumps({"todos": [], "message": "No todo list found."})

            with open(todo_file, "r", encoding="utf-8") as fh:
                todos = json.load(fh)

            return json.dumps(todos)
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("todo_read error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 9: fs_patch_file
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_patch_file(
        user_email: str,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
    ) -> str:
        """Replace a range of lines in a file with new content.

        Lines are 1-indexed and inclusive. For example, start_line=3, end_line=5
        replaces lines 3, 4, and 5 with new_content. To insert without removing
        any lines use start_line=N+1, end_line=N (empty range). To delete lines
        without replacement pass new_content=''.

        Args:
            user_email: Email of the requesting user.
            path: File path (relative to project root or absolute).
            start_line: First line to replace (1-indexed, inclusive).
            end_line: Last line to replace (1-indexed, inclusive).
            new_content: Replacement text. May be empty to delete lines.
                         Should NOT include trailing newline unless intended.
        """
        try:
            abs_path = _resolve_safe_path(path)
            if not os.path.isfile(abs_path):
                return json.dumps({"error": f"File not found: {path}"})
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            total = len(lines)
            s = max(1, start_line) - 1   # 0-indexed
            e = min(end_line, total)      # 0-indexed exclusive end
            if s > total:
                return json.dumps({
                    "error": f"start_line {start_line} exceeds file length {total}."
                })
            replacement: list[str] = []
            if new_content:
                for chunk in new_content.split("\n"):
                    replacement.append(chunk + "\n")
                # If new_content didn't end with \n, strip the spurious trailing newline
                if not new_content.endswith("\n") and replacement:
                    replacement[-1] = replacement[-1].rstrip("\n")
            new_lines = lines[:s] + replacement + lines[e:]
            with open(abs_path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
            removed = e - s
            added = len(replacement)
            return json.dumps({
                "status": "ok",
                "lines_removed": removed,
                "lines_added": added,
                "total_lines": len(new_lines),
            })
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_patch_file error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 10: fs_bash
    # -----------------------------------------------------------------

    @mcp.tool()
    def fs_bash(
        user_email: str,
        command: str,
        workdir: str = ".",
        timeout: int = 60,
    ) -> str:
        """Execute a bash shell command in the project directory.

        Runs the command in a subprocess with a configurable timeout.
        The working directory defaults to the project root and must stay
        within the project root (path-traversal protection applies).

        Use for: running tests, build commands, git operations, installing
        packages, running scripts, or any shell task.

        Args:
            user_email: Email of the requesting user.
            command: Shell command string to execute (passed to bash -c).
            workdir: Working directory (relative to project root, default '.').
            timeout: Maximum seconds to wait (default 60, max 300).
        """
        import subprocess
        try:
            abs_workdir = _resolve_safe_path(workdir)
            if not os.path.isdir(abs_workdir):
                return json.dumps({"error": f"workdir not a directory: {workdir}"})
            effective_timeout = min(max(1, timeout), 300)
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd=abs_workdir,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            # Trim very long output
            if len(stdout) > 50_000:
                stdout = stdout[:50_000] + "\n... [stdout truncated]"
            if len(stderr) > 10_000:
                stderr = stderr[:10_000] + "\n... [stderr truncated]"
            return json.dumps({
                "exit_code": proc.returncode,
                "success": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({
                "exit_code": -1,
                "success": False,
                "error": f"Command timed out after {timeout}s.",
                "stdout": "",
                "stderr": "",
            })
        except ValueError as ve:
            return json.dumps({"error": str(ve)})
        except Exception as exc:
            logger.exception("fs_bash error: %s", exc)
            return json.dumps({"error": str(exc)})
    # -----------------------------------------------------------------
    # Build the Starlette ASGI app with middleware layers
    # -----------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    mcp_starlette = mcp.streamable_http_app()

    outer_app = Starlette(
        routes=[
            Route("/health", _health_check, methods=["GET"]),
            Mount("/", app=mcp_starlette),
        ],
        lifespan=lifespan,
    )

    app_with_rate_limit = RateLimitMiddleware(outer_app, rate=rate_limit, window=60)

    app_with_auth: ASGIApp = JWTAuthMiddleware(
        app_with_rate_limit, jwt_secret=jwt_secret
    )

    return app_with_auth, mcp


# ---------------------------------------------------------------------------
# Daemon-thread launcher (mirrors mcp_server/__init__.py pattern)
# ---------------------------------------------------------------------------


def start_coding_tools_mcp_server() -> None:
    """Start the MCP coding & file tools server in a daemon thread.

    Reads configuration from environment variables:
    - ``CODING_TOOLS_MCP_ENABLED``: set to ``"false"`` to skip (default ``"true"``)
    - ``CODING_TOOLS_MCP_PORT``: port number (default ``8108``)
    - ``MCP_JWT_SECRET``: HS256 secret for bearer-token verification (required)
    - ``MCP_RATE_LIMIT``: max tool calls per token per minute (default ``10``)

    Does nothing if disabled or if ``MCP_JWT_SECRET`` is not set.
    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("CODING_TOOLS_MCP_ENABLED", "true").lower() == "false":
        logger.info("Coding Tools MCP server disabled (CODING_TOOLS_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Coding Tools MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the Coding Tools MCP server."
        )
        return

    port = int(os.getenv("CODING_TOOLS_MCP_PORT", "8108"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_coding_tools_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Coding Tools MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Coding Tools MCP server failed to start")

    thread = threading.Thread(target=_run, name="coding-tools-mcp-server", daemon=True)
    thread.start()
    logger.info(
        "Coding Tools MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
