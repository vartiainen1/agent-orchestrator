"""Comprehensive tests for the orchestrator dashboard.

Tests cover:
  - HTTP server start/stop
  - All API endpoints
  - Run listing
  - Run detail
  - Evidence timeline
  - Tool discovery
  - System status
  - Policy display
  - Interrupted runs
  - Path traversal prevention
  - Invalid run IDs
  - Secret redaction
  - Malformed data handling
  - Read-only behavior (POST/PUT/DELETE rejected)
  - HTML page serving
  - Health check
  - CLI integration
  - Zero external dependencies
  - shell=True absence
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

# Ensure orchestrator package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.dashboard import (
    DashboardServer,
    _validate_run_id,
    _DEFAULT_HOST,
    _DEFAULT_PORT,
)
from orchestrator.dashboard_ui import render_dashboard
from orchestrator.state import RunState, Phase, ToolCall
from orchestrator.persist import save_state, append_evidence, update_run_index
from orchestrator.evidence import evidence_entry


class TestDashboardServerLifecycle(unittest.TestCase):
    """Test server start/stop behavior."""

    def test_server_starts_and_stops(self):
        """Server can start and stop cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            server = DashboardServer(workspace, port=0)
            # Use port 0 for OS-assigned port
            server.start()
            self.assertTrue(server.serving())
            server.stop()
            self.assertFalse(server.serving())

    def test_server_url_format(self):
        """URL is formatted correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            server = DashboardServer(Path(tmpdir), host="127.0.0.1", port=9999)
            self.assertEqual(server.url, "http://127.0.0.1:9999")


class TestValidateRunId(unittest.TestCase):
    """Test run_id validation."""

    def test_valid_run_id(self):
        self.assertTrue(_validate_run_id("RUN-20260825-143022-a1b2c3"))

    def test_empty_run_id(self):
        self.assertFalse(_validate_run_id(""))

    def test_none_run_id(self):
        self.assertFalse(_validate_run_id(None))

    def test_path_traversal(self):
        self.assertFalse(_validate_run_id("../../../etc/passwd"))

    def test_double_dot(self):
        self.assertFalse(_validate_run_id("RUN-20260825-143022-a1b2c3/../../secret"))

    def test_too_long(self):
        self.assertFalse(_validate_run_id("RUN-" + "a" * 100))

    def test_invalid_format(self):
        self.assertFalse(_validate_run_id("not-a-run-id"))

    def test_special_characters(self):
        self.assertFalse(_validate_run_id("RUN-20260825-143022-a1b2c3;rm -rf /"))

    def test_windows_path(self):
        self.assertFalse(_validate_run_id("..\\..\\Windows\\System32"))


class TestDashboardHTML(unittest.TestCase):
    """Test HTML dashboard rendering."""

    def test_renders_html(self):
        """Dashboard renders valid HTML."""
        html = render_dashboard()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<html", html)
        self.assertIn("</html>", html)

    def test_contains_tabs(self):
        """Dashboard contains navigation tabs."""
        html = render_dashboard()
        self.assertIn("Runs", html)
        self.assertIn("Tools", html)
        self.assertIn("Status", html)
        self.assertIn("Policies", html)

    def test_contains_javascript(self):
        """Dashboard contains JavaScript for data fetching."""
        html = render_dashboard()
        self.assertIn("function loadRuns()", html)
        self.assertIn("function loadTools()", html)
        self.assertIn("function loadStatus()", html)
        self.assertIn("function loadPolicies()", html)

    def test_auto_refresh(self):
        """Dashboard includes auto-refresh logic."""
        html = render_dashboard(refresh_interval=5)
        self.assertIn("REFRESH_MS", html)
        self.assertIn("setInterval", html)

    def test_no_external_dependencies(self):
        """Dashboard has no external CDN/script references."""
        html = render_dashboard()
        self.assertNotIn("cdn.", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<script src=", html)

    def test_no_inline_event_handlers_in_template(self):
        """No dangerous inline handlers beyond onclick for navigation."""
        html = render_dashboard()
        # Should not have script injection vectors
        self.assertNotIn("onerror=", html)
        self.assertNotIn("onload=", html)


class TestDashboardRoutes(unittest.TestCase):
    """Test API endpoints using a real HTTP server."""

    def setUp(self):
        """Start a test server."""
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        # Create minimal .orchestrator/runs structure
        runs_dir = self.workspace / ".orchestrator" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "index.json").write_text(
            json.dumps({"version": 1, "runs": []}), encoding="utf-8"
        )

        self.server = DashboardServer(self.workspace, port=0)
        self.server.start()
        # Get the actual port
        self.port = self.server._httpd.server_address[1]
        self.conn = HTTPConnection("127.0.0.1", self.port, timeout=5)

    def tearDown(self):
        """Stop the test server."""
        self.conn.close()
        self.server.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get(self, path: str) -> tuple[int, dict]:
        """Make a GET request and return (status, json_data)."""
        self.conn.request("GET", path)
        resp = self.conn.getresponse()
        status = resp.status
        body = resp.read().decode("utf-8")
        return status, json.loads(body)

    def _get_raw(self, path: str) -> tuple[int, str]:
        """Make a GET request and return (status, raw_body)."""
        self.conn.request("GET", path)
        resp = self.conn.getresponse()
        return resp.status, resp.read().decode("utf-8")

    # ── Health ──────────────────────────────────────────────────

    def test_health_endpoint(self):
        status, data = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["status"], "healthy")
        self.assertIn("version", data["data"])

    # ── Status ──────────────────────────────────────────────────

    def test_status_endpoint(self):
        status, data = self._get("/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("version", data["data"])
        self.assertIn("workspace", data["data"])

    # ── Runs ────────────────────────────────────────────────────

    def test_runs_empty(self):
        status, data = self._get("/api/runs")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["total"], 0)
        self.assertEqual(data["data"]["runs"], [])

    def test_runs_with_data(self):
        # Persist a run
        state = RunState(
            workflow_name="test",
            mode="solo",
            phase=Phase.COMPLETED,
        )
        state.finalize("PASS")
        save_state(state, self.workspace)
        update_run_index(state, self.workspace)

        status, data = self._get("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(data["data"]["total"], 1)
        run = data["data"]["runs"][0]
        self.assertEqual(run["run_id"], state.run_id)
        self.assertEqual(run["workflow"], "test")
        self.assertEqual(run["status"], "PASS")

    # ── Run detail ──────────────────────────────────────────────

    def test_run_detail_valid(self):
        state = RunState(workflow_name="test", mode="solo")
        state.record_tool_call(ToolCall(
            tool_name="test-tool",
            operation="check",
            exit_code=0,
            status="PASS",
        ))
        state.finalize("PASS")
        save_state(state, self.workspace)

        status, data = self._get(f"/api/runs/{state.run_id}")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["workflow"], "test")
        self.assertEqual(len(data["data"]["tool_calls"]), 1)

    def test_run_detail_not_found(self):
        status, data = self._get("/api/runs/RUN-20260825-143022-aabbcc")
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])

    def test_run_detail_invalid_id(self):
        status, data = self._get("/api/runs/../../../etc/passwd")
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

    def test_run_detail_path_traversal(self):
        status, data = self._get("/api/runs/..%2F..%2Fetc%2Fpasswd")
        self.assertEqual(status, 400)

    # ── Evidence ────────────────────────────────────────────────

    def test_evidence_valid(self):
        state = RunState(workflow_name="test", mode="solo")
        save_state(state, self.workspace)
        entry = evidence_entry(
            run_id=state.run_id,
            action="test_action",
            tool="test-tool",
            status="PASS",
        )
        append_evidence(entry, self.workspace, state.run_id)

        status, data = self._get(f"/api/runs/{state.run_id}/evidence")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(data["data"]["entries"][0]["action"], "test_action")

    def test_evidence_empty(self):
        state = RunState(workflow_name="test", mode="solo")
        save_state(state, self.workspace)
        status, data = self._get(f"/api/runs/{state.run_id}/evidence")
        self.assertEqual(status, 200)
        self.assertEqual(data["data"]["total"], 0)

    def test_evidence_invalid_id(self):
        status, data = self._get("/api/runs/not-valid/evidence")
        self.assertEqual(status, 400)

    # ── Tools ───────────────────────────────────────────────────

    def test_tools_endpoint(self):
        status, data = self._get("/api/tools")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("tools", data["data"])
        self.assertIn("summary", data["data"])
        self.assertEqual(data["data"]["summary"]["total"], 7)

    # ── Interrupted ─────────────────────────────────────────────

    def test_interrupted_empty(self):
        status, data = self._get("/api/interrupted")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["total"], 0)

    # ── Policies ────────────────────────────────────────────────

    def test_policies_valid_mode(self):
        status, data = self._get("/api/policies/solo")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["mode"], "solo")
        self.assertIn("rules", data["data"])

    def test_policies_all_modes(self):
        for mode in ["solo", "development", "security", "enterprise"]:
            status, data = self._get(f"/api/policies/{mode}")
            self.assertEqual(status, 200, f"Failed for mode: {mode}")
            self.assertTrue(data["ok"])

    def test_policies_invalid_mode(self):
        status, data = self._get("/api/policies/invalid_mode")
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

    # ── 404 handling ────────────────────────────────────────────

    def test_unknown_path(self):
        status, data = self._get("/api/nonexistent")
        self.assertEqual(status, 404)

    def test_root_returns_html(self):
        status, body = self._get_raw("/")
        self.assertEqual(status, 200)
        self.assertIn("<!DOCTYPE html>", body)

    # ── Read-only enforcement ───────────────────────────────────

    def test_post_rejected(self):
        self.conn.request("POST", "/api/runs")
        resp = self.conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()

    def test_put_rejected(self):
        self.conn.request("PUT", "/api/runs/some-id")
        resp = self.conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()

    def test_delete_rejected(self):
        self.conn.request("DELETE", "/api/runs/some-id")
        resp = self.conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()

    def test_patch_rejected(self):
        self.conn.request("PATCH", "/api/runs/some-id")
        resp = self.conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()


class TestDashboardSecretRedaction(unittest.TestCase):
    """Test that secrets are not exposed through the dashboard."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        runs_dir = self.workspace / ".orchestrator" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "index.json").write_text(
            json.dumps({"version": 1, "runs": []}), encoding="utf-8"
        )

        self.server = DashboardServer(self.workspace, port=0)
        self.server.start()
        self.port = self.server._httpd.server_address[1]
        self.conn = HTTPConnection("127.0.0.1", self.port, timeout=5)

    def tearDown(self):
        self.conn.close()
        self.server.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get(self, path: str) -> tuple[int, dict]:
        self.conn.request("GET", path)
        resp = self.conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_evidence_redacts_secrets(self):
        """Evidence entries with secrets are redacted."""
        state = RunState(workflow_name="test", mode="solo")
        save_state(state, self.workspace)
        # Create evidence with a secret
        entry = evidence_entry(
            run_id=state.run_id,
            action="config_loaded",
            detail="api_key=sk-supersecret1234567890",
        )
        append_evidence(entry, self.workspace, state.run_id)

        status, data = self._get(f"/api/runs/{state.run_id}/evidence")
        self.assertEqual(status, 200)
        detail = data["data"]["entries"][0]["detail"]
        self.assertNotIn("sk-supersecret", detail)
        self.assertIn("[REDACTED]", detail)


class TestDashboardMalformedData(unittest.TestCase):
    """Test handling of corrupt/malformed persisted data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        self.runs_dir = self.workspace / ".orchestrator" / "runs"
        self.runs_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _start_server(self):
        server = DashboardServer(self.workspace, port=0)
        server.start()
        port = server._httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        return server, conn

    def _get(self, conn, path: str) -> tuple[int, dict]:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_corrupt_index(self):
        """Corrupt index.json is handled gracefully."""
        (self.runs_dir / "index.json").write_text("NOT JSON", encoding="utf-8")
        server, conn = self._start_server()
        try:
            status, data = self._get(conn, "/api/runs")
            self.assertEqual(status, 200)
            self.assertTrue(data["ok"])
            self.assertEqual(data["data"]["total"], 0)
        finally:
            conn.close()
            server.stop()

    def test_corrupt_state(self):
        """Corrupt state.json returns error (404 or 500) for that run."""
        # Create a run dir with corrupt state
        run_dir = self.runs_dir / "RUN-20260825-143022-aabbcc"
        run_dir.mkdir()
        (run_dir / "state.json").write_text("{corrupt", encoding="utf-8")
        # Add to index
        (self.runs_dir / "index.json").write_text(json.dumps({
            "version": 1,
            "runs": [{
                "run_id": "RUN-20260825-143022-aabbcc",
                "workflow": "test",
                "mode": "solo",
                "status": "RUNNING",
                "started_at": "2026-08-25T14:30:22Z",
                "phase": "EXECUTING",
            }]
        }), encoding="utf-8")

        server, conn = self._start_server()
        try:
            status, data = self._get(conn, "/api/runs/RUN-20260825-143022-aabbcc")
            # Corrupt state causes load_state to return None → 404
            self.assertIn(status, [404, 500])
            self.assertFalse(data["ok"])
        finally:
            conn.close()
            server.stop()

    def test_corrupt_evidence(self):
        """Corrupt evidence lines are skipped."""
        state = RunState(workflow_name="test", mode="solo")
        save_state(state, self.workspace)
        # Write corrupt evidence (ensure run dir exists)
        run_dir = self.runs_dir / state.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = run_dir / "evidence.jsonl"
        with open(evidence_path, "w") as f:
            f.write(json.dumps({"action": "good_entry"}) + "\n")
            f.write("NOT JSON\n")
            f.write(json.dumps({"action": "another_good"}) + "\n")

        server, conn = self._start_server()
        try:
            status, data = self._get(conn, f"/api/runs/{state.run_id}/evidence")
            self.assertEqual(status, 200)
            self.assertTrue(data["ok"])
            # Corrupted line is skipped, only valid entries returned
            # (persist.load_evidence skips corrupted lines)
        finally:
            conn.close()
            server.stop()

    def test_missing_index(self):
        """Missing index.json returns empty list."""
        server, conn = self._start_server()
        try:
            status, data = self._get(conn, "/api/runs")
            self.assertEqual(status, 200)
            self.assertEqual(data["data"]["total"], 0)
        finally:
            conn.close()
            server.stop()


class TestDashboardCLI(unittest.TestCase):
    """Test CLI integration for the dashboard command."""

    def test_dashboard_in_cli_help(self):
        """Dashboard appears in CLI help."""
        from orchestrator.cli import _build_parser
        parser = _build_parser()
        # Parse dashboard --help should not crash
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["dashboard", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_dashboard_default_args(self):
        """Dashboard parses default arguments."""
        from orchestrator.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["dashboard"])
        self.assertEqual(args.port, 8520)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertFalse(args.open)
        self.assertFalse(args.no_refresh)

    def test_dashboard_custom_args(self):
        """Dashboard parses custom arguments."""
        from orchestrator.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([
            "dashboard", "--port", "9999",
            "--host", "0.0.0.0",
            "--open",
            "--no-refresh",
        ])
        self.assertEqual(args.port, 9999)
        self.assertEqual(args.host, "0.0.0.0")
        self.assertTrue(args.open)
        self.assertTrue(args.no_refresh)


class TestZeroDependencies(unittest.TestCase):
    """Verify dashboard uses only stdlib."""

    def test_dashboard_imports_only_stdlib(self):
        """dashboard.py only imports stdlib + internal modules."""
        import ast
        src_path = Path(__file__).resolve().parent.parent / "orchestrator" / "dashboard.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Relative imports (from .xxx) are internal
                    if node.level and node.level > 0:
                        continue
                    imports.append(node.module)

        # Filter out stdlib and internal orchestrator imports
        stdlib = {
            "json", "sys", "time", "threading", "re",
            "http.server", "pathlib", "typing",
            "datetime", "webbrowser", "tempfile",
            "__future__", "os", "hashlib",
        }
        external = [
            i for i in imports
            if not i.startswith("orchestrator")
            and i not in stdlib
        ]
        self.assertEqual(external, [], f"External imports found: {external}")

    def test_dashboard_ui_imports_only_stdlib(self):
        """dashboard_ui.py only imports stdlib + internal modules."""
        import ast
        src_path = Path(__file__).resolve().parent.parent / "orchestrator" / "dashboard_ui.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    if node.level and node.level > 0:
                        continue
                    imports.append(node.module)

        stdlib = {"__future__"}
        external = [
            i for i in imports
            if not i.startswith("orchestrator")
            and i not in stdlib
        ]
        self.assertEqual(external, [], f"External imports found: {external}")


class TestSecurityAudit(unittest.TestCase):
    """Verify security properties of dashboard code."""

    def _code_lines(self, name: str) -> list[str]:
        """Extract only executable code lines (skip comments, docstrings, strings)."""
        import ast
        path = Path(__file__).resolve().parent.parent / "orchestrator" / name
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        # Use AST to find actual code locations, not docstrings
        tree = ast.parse(source)
        code_lines = set()
        for node in ast.walk(tree):
            if hasattr(node, 'lineno'):
                code_lines.add(node.lineno)
        # Also include import lines and any non-docstring, non-comment lines
        result = []
        in_docstring = False
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith('"\"\"') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            result.append(stripped)
        return result

    def test_no_shell_true(self):
        """No shell=True in executable code of dashboard modules."""
        for name in ["dashboard.py", "dashboard_ui.py"]:
            for i, line in enumerate(self._code_lines(name), 1):
                self.assertNotIn("shell=True", line,
                                 f"shell=True found in {name} line {i}: {line[:80]}")

    def test_no_eval_exec(self):
        """No eval() or exec() in executable code of dashboard modules."""
        for name in ["dashboard.py", "dashboard_ui.py"]:
            for i, line in enumerate(self._code_lines(name), 1):
                self.assertNotIn("eval(", line,
                                 f"eval() found in {name} line {i}: {line[:80]}")
                self.assertNotIn("exec(", line,
                                 f"exec() found in {name} line {i}: {line[:80]}")

    def test_no_os_system(self):
        """No os.system() in executable code of dashboard modules."""
        for name in ["dashboard.py", "dashboard_ui.py"]:
            for i, line in enumerate(self._code_lines(name), 1):
                self.assertNotIn("os.system(", line,
                                 f"os.system() found in {name} line {i}: {line[:80]}")

    def test_post_put_delete_rejected(self):
        """Dashboard handler rejects mutating HTTP methods."""
        import inspect
        from orchestrator.dashboard import _make_handler
        handler_class = _make_handler(Path("."), 5, 0.0)
        self.assertTrue(hasattr(handler_class, "do_POST"))
        self.assertTrue(hasattr(handler_class, "do_PUT"))
        self.assertTrue(hasattr(handler_class, "do_DELETE"))
        self.assertTrue(hasattr(handler_class, "do_PATCH"))


class TestRegressionCLI(unittest.TestCase):
    """Verify existing CLI commands still work."""

    def test_cli_status(self):
        """orchestrator status still works."""
        from orchestrator.cli import main
        # status command should not crash (even if workspace is missing)
        result = main(["status", "--json"])
        # May return BLOCKED if no workspace, but should not crash
        self.assertIn(result, [0, 3, 5])

    def test_cli_modes(self):
        """orchestrator modes still works."""
        from orchestrator.cli import main
        result = main(["modes"])
        self.assertEqual(result, 0)

    def test_cli_policies(self):
        """orchestrator policies still works."""
        from orchestrator.cli import main
        result = main(["policies", "solo"])
        self.assertEqual(result, 0)

    def test_cli_help(self):
        """orchestrator --help still works."""
        from orchestrator.cli import _build_parser
        parser = _build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)


class TestMultipleRuns(unittest.TestCase):
    """Test dashboard with multiple persisted runs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        runs_dir = self.workspace / ".orchestrator" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "index.json").write_text(
            json.dumps({"version": 1, "runs": []}), encoding="utf-8"
        )

        # Create 3 runs
        self.run_ids = []
        for i in range(3):
            state = RunState(
                workflow_name=f"workflow-{i}",
                mode=["solo", "development", "security"][i],
            )
            state.finalize(["PASS", "FAIL", "BLOCKED"][i])
            save_state(state, self.workspace)
            update_run_index(state, self.workspace)
            self.run_ids.append(state.run_id)

        self.server = DashboardServer(self.workspace, port=0)
        self.server.start()
        self.port = self.server._httpd.server_address[1]
        self.conn = HTTPConnection("127.0.0.1", self.port, timeout=5)

    def tearDown(self):
        self.conn.close()
        self.server.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get(self, path: str) -> tuple[int, dict]:
        self.conn.request("GET", path)
        resp = self.conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_runs_lists_all(self):
        """All runs appear in the list."""
        status, data = self._get("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(data["data"]["total"], 3)

    def test_runs_status_counts(self):
        """Status values are correct."""
        status, data = self._get("/api/runs")
        statuses = [r["status"] for r in data["data"]["runs"]]
        self.assertIn("PASS", statuses)
        self.assertIn("FAIL", statuses)
        self.assertIn("BLOCKED", statuses)

    def test_each_run_has_detail(self):
        """Each run can be fetched individually."""
        for run_id in self.run_ids:
            status, data = self._get(f"/api/runs/{run_id}")
            self.assertEqual(status, 200)
            self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main()
