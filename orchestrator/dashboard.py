"""Web dashboard — read-only browser interface over persisted orchestration data.

Provides an HTTP server that serves a single-page dashboard consuming the
existing persistence format.  No new data models, no duplicate engines.

Design: PHASE_DASHBOARD_DESIGN.md
Security:
  - Read-only (no mutation endpoints)
  - Localhost-only binding by default
  - All run IDs validated (path traversal prevention)
  - Secrets never exposed (inherits redaction from persistence)
  - No shell=True, eval(), exec(), os.system()
  - No arbitrary filesystem access
"""

from __future__ import annotations

import json
import sys
import time
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from . import __version__ as _version
from . import olog as log
from .evidence import redact

# ── Constants ────────────────────────────────────────────────────────────

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8520
_DEFAULT_REFRESH = 5  # seconds

# Routes that serve JSON data
_API_PREFIX = "/api/"

# Valid run ID pattern (must match persist.py)
import re
_RUN_ID_RE = re.compile(r"^RUN-\d{8}-\d{6}-[a-f0-9]{6}$")


# ── Helpers ──────────────────────────────────────────────────────────────

def _validate_run_id(run_id: str) -> bool:
    """Validate a run_id to prevent path traversal."""
    if not run_id or len(run_id) > 64:
        return False
    return bool(_RUN_ID_RE.match(run_id))


def _json_response(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    """Send a JSON response."""
    body = json.dumps(data, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def _error_response(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    """Send an error JSON response."""
    _json_response(handler, {"ok": False, "data": None, "error": message}, status)


def _ok_response(handler: BaseHTTPRequestHandler, data: dict) -> None:
    """Send a success JSON response."""
    _json_response(handler, {"ok": True, "data": data, "error": None})


# ── Dashboard Server ─────────────────────────────────────────────────────

class DashboardServer:
    """Manages the HTTP server lifecycle.

    Usage:
        server = DashboardServer(workspace, port=8520)
        server.start()   # non-blocking
        server.stop()    # blocking
    """

    def __init__(
        self,
        workspace: Path,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        refresh: int = _DEFAULT_REFRESH,
    ):
        self.workspace = workspace
        self.host = host
        self.port = port
        self.refresh = refresh
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._start_time = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Start the server in a background thread."""
        handler = _make_handler(self.workspace, self.refresh, self._start_time)
        self._httpd = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def serving(self) -> bool:
        return self._httpd is not None


def _make_handler(
    workspace: Path,
    refresh: int,
    start_time: float,
):
    """Create a request handler class with workspace closure."""

    class DashboardHandler(BaseHTTPRequestHandler):
        """HTTP request handler for the dashboard."""

        # Suppress default stderr logging
        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):
            """Handle GET requests."""
            path = self.path.split("?")[0]  # strip query string

            # ── Static routes ───────────────────────────────────
            if path == "/":
                self._serve_dashboard()
            elif path == "/api/health":
                self._serve_health()
            elif path == "/api/status":
                self._serve_status()
            elif path == "/api/runs":
                self._serve_runs()
            elif path == "/api/tools":
                self._serve_tools()
            elif path == "/api/interrupted":
                self._serve_interrupted()
            elif path.startswith("/api/runs/") and path.endswith("/evidence"):
                run_id = path.split("/")[3]
                self._serve_evidence(run_id)
            elif path.startswith("/api/runs/"):
                run_id = path.split("/")[3]
                self._serve_run_detail(run_id)
            elif path.startswith("/api/policies/"):
                mode = path.split("/")[3]
                self._serve_policies(mode)
            else:
                _error_response(self, "not found", 404)

        def do_POST(self):
            _error_response(self, "method not allowed", 405)

        def do_PUT(self):
            _error_response(self, "method not allowed", 405)

        def do_DELETE(self):
            _error_response(self, "method not allowed", 405)

        def do_PATCH(self):
            _error_response(self, "method not allowed", 405)

        # ── Route implementations ────────────────────────────────

        def _serve_dashboard(self):
            """Serve the HTML dashboard page."""
            from .dashboard_ui import render_dashboard
            body = render_dashboard(refresh_interval=refresh).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_health(self):
            """Health check endpoint."""
            uptime = time.monotonic() - start_time
            _ok_response(self, {
                "status": "healthy",
                "version": _version,
                "uptime": round(uptime, 2),
            })

        def _serve_status(self):
            """System status endpoint."""
            try:
                from .config import load_config
                config = load_config(workspace)
                _ok_response(self, {
                    "version": _version,
                    "project": str(workspace),
                    "workspace": str(workspace),
                    "mode": config.mode,
                    "sandbox_required": config.sandbox_required,
                    "diff_gate_required": config.diff_gate_required,
                    "has_config": config.has_config,
                    "has_workflow": config.has_workflow,
                })
            except Exception as exc:
                _ok_response(self, {
                    "version": _version,
                    "project": str(workspace),
                    "workspace": str(workspace),
                    "mode": "solo",
                    "error": str(exc),
                })

        def _serve_runs(self):
            """List all runs from the index."""
            try:
                from .persist import list_runs
                runs = list_runs(workspace, limit=100)
                run_list = []
                for r in runs:
                    run_list.append({
                        "run_id": r.run_id,
                        "workflow": r.workflow,
                        "mode": r.mode,
                        "status": r.status or "RUNNING",
                        "started_at": r.started_at,
                        "ended_at": r.ended_at,
                        "project_dir": r.project_dir,
                        "tool_call_count": r.tool_call_count,
                        "evidence_count": r.evidence_count,
                        "phase": r.phase,
                    })
                _ok_response(self, {"runs": run_list, "total": len(run_list)})
            except Exception as exc:
                _error_response(self, f"failed to load runs: {exc}", 500)

        def _serve_run_detail(self, run_id: str):
            """Show details of a specific run."""
            if not _validate_run_id(run_id):
                _error_response(self, f"invalid run_id: {run_id!r}", 400)
                return
            try:
                from .persist import load_state
                from .report import report_dict
                state = load_state(run_id, workspace)
                if state is None:
                    _error_response(self, f"run not found: {run_id}", 404)
                    return
                data = report_dict(state)
                # Add evidence count
                try:
                    from .persist import evidence_count
                    data["evidence_count"] = evidence_count(run_id, workspace)
                except Exception:
                    data["evidence_count"] = 0
                # Cap stdout/stderr in tool calls for API response
                for tc in data.get("tool_calls", []):
                    tc.pop("stdout", None)
                    tc.pop("stderr", None)
                _ok_response(self, data)
            except Exception as exc:
                _error_response(self, f"failed to load run: {exc}", 500)

        def _serve_evidence(self, run_id: str):
            """Show evidence entries for a run."""
            if not _validate_run_id(run_id):
                _error_response(self, f"invalid run_id: {run_id!r}", 400)
                return
            try:
                from .persist import load_evidence
                entries = load_evidence(run_id, workspace)
                _ok_response(self, {
                    "run_id": run_id,
                    "entries": entries,
                    "total": len(entries),
                })
            except Exception as exc:
                _error_response(self, f"failed to load evidence: {exc}", 500)

        def _serve_tools(self):
            """Tool discovery status."""
            try:
                from .discovery import discover_all
                tools = discover_all(workspace)
                tool_list = []
                for t in tools:
                    tool_list.append({
                        "name": t.name,
                        "status": t.status.value,
                        "version": t.version,
                        "platform_support": t.platform_support,
                        "capabilities": t.capabilities,
                    })
                # Summary
                counts = {}
                for t in tools:
                    key = t.status.value
                    counts[key] = counts.get(key, 0) + 1
                _ok_response(self, {
                    "tools": tool_list,
                    "summary": {
                        "total": len(tools),
                        "available": counts.get("AVAILABLE", 0),
                        "unsupported": counts.get("UNSUPPORTED", 0),
                        "missing": counts.get("MISSING", 0),
                        "error": counts.get("ERROR", 0),
                    },
                })
            except Exception as exc:
                _error_response(self, f"failed to discover tools: {exc}", 500)

        def _serve_interrupted(self):
            """List interrupted runs."""
            try:
                from .recovery import find_interrupted_runs
                interrupted = find_interrupted_runs(workspace)
                _ok_response(self, {
                    "interrupted": interrupted,
                    "total": len(interrupted),
                })
            except Exception as exc:
                _error_response(self, f"failed to find interrupted runs: {exc}", 500)

        def _serve_policies(self, mode: str):
            """Show policy rules for a mode."""
            from .modes import is_valid_mode
            if not is_valid_mode(mode):
                _error_response(self, f"invalid mode: {mode!r}", 400)
                return
            try:
                from .policy import load_policy
                policy = load_policy(mode, project_dir=workspace)
                rules = {}
                for name, rule in policy.rules.items():
                    rules[name] = {
                        "value": rule.value,
                        "mandatory": rule.mandatory,
                        "source": rule.source,
                        "reason": rule.reason,
                    }
                _ok_response(self, {"mode": mode, "rules": rules})
            except Exception as exc:
                _error_response(self, f"failed to load policy: {exc}", 500)

    return DashboardHandler


# ── Launch function ──────────────────────────────────────────────────────

def launch_dashboard(
    workspace: Path,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    refresh: int = _DEFAULT_REFRESH,
    open_browser: bool = False,
) -> int:
    """Launch the dashboard server.

    Returns exit code: 0 = normal, 1 = error.
    """
    server = DashboardServer(workspace, host, port, refresh)

    try:
        server.start()
    except OSError as exc:
        log.error(f"dashboard startup failed: {exc}", component="dashboard")
        return 1

    log.info(f"Orchestrate Dashboard v{_version}", component="dashboard")
    log.info(f"Serving on {server.url}", component="dashboard")
    log.info("Press Ctrl+C to stop.", component="dashboard")

    if open_browser:
        import webbrowser
        try:
            webbrowser.open(server.url)
        except Exception:
            pass

    try:
        # Block until interrupted
        while server.serving():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()

    log.info("Dashboard stopped.", component="dashboard")
    return 0
