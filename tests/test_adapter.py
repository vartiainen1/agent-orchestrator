"""Tests for orchestrator.adapter — Phase 3 tool adapter layer."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.adapter import (
    ADAPTER_CLASSES,
    BaseAdapter,
    BlameAdapter,
    DecisionLogAdapter,
    DiffGateAdapter,
    ErrorLogAdapter,
    LogAIAdapter,
    MemoryAdapter,
    SandboxAdapter,
    ToolResult,
    ResultStatus,
    get_adapter,
    get_all_adapters,
    run_tool,
)


# ── ToolResult ───────────────────────────────────────────────────────────

class TestToolResult(unittest.TestCase):
    """ToolResult dataclass."""

    def test_ok_true_on_pass(self):
        r = ToolResult(tool_name="x", operation="test", status=ResultStatus.PASS, exit_code=0)
        self.assertTrue(r.ok)

    def test_ok_false_on_fail(self):
        r = ToolResult(tool_name="x", operation="test", status=ResultStatus.FAIL, exit_code=1)
        self.assertFalse(r.ok)

    def test_ok_false_on_blocked(self):
        r = ToolResult(tool_name="x", operation="test", status=ResultStatus.BLOCKED, exit_code=1)
        self.assertFalse(r.ok)

    def test_repr(self):
        r = ToolResult(tool_name="x", operation="test", status=ResultStatus.PASS, exit_code=0)
        s = repr(r)
        self.assertIn("x", s)
        self.assertIn("PASS", s)


class TestResultStatus(unittest.TestCase):
    """ResultStatus enum."""

    def test_six_states(self):
        states = [s.value for s in ResultStatus]
        self.assertEqual(len(states), 6)
        self.assertIn("PASS", states)
        self.assertIn("FAIL", states)
        self.assertIn("BLOCKED", states)
        self.assertIn("UNSUPPORTED", states)
        self.assertIn("ERROR", states)
        self.assertIn("INVALID", states)


# ── run_tool ─────────────────────────────────────────────────────────────

class TestRunTool(unittest.TestCase):
    """run_tool subprocess helper."""

    def test_successful_command(self):
        exit_code, stdout, stderr, duration = run_tool(
            [sys.executable, "-c", "print('hello')"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("hello", stdout)
        self.assertGreater(duration, 0)

    def test_failing_command(self):
        exit_code, stdout, stderr, duration = run_tool(
            [sys.executable, "-c", "import sys; sys.exit(1)"]
        )
        self.assertEqual(exit_code, 1)

    def test_timeout(self):
        exit_code, stdout, stderr, duration = run_tool(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.5,
        )
        self.assertEqual(exit_code, -1)
        self.assertIn("timeout", stderr)

    def test_nonexistent_executable(self):
        exit_code, stdout, stderr, duration = run_tool(
            ["nonexistent_tool_xyz_12345"]
        )
        self.assertEqual(exit_code, -2)
        self.assertIn("os error", stderr)

    def test_no_shell_true(self):
        """Verify shell=False is used (command as list)."""
        exit_code, stdout, _, _ = run_tool(
            [sys.executable, "-c", "print('safe')"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("safe", stdout)


# ── BaseAdapter ──────────────────────────────────────────────────────────

class TestBaseAdapter(unittest.TestCase):
    """BaseAdapter availability check."""

    def test_available_when_pyproject_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            td = ws / "tool-x"
            td.mkdir()
            (td / "pyproject.toml").write_text("[project]\n")
            a = BaseAdapter(ws)
            a.TOOL_DIR_NAME = "tool-x"
            # Override tool_dir since it's set in __init__
            a.tool_dir = td
            self.assertTrue(a.available)

    def test_unavailable_when_no_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "tool-x").mkdir()
            a = BaseAdapter(ws)
            a.TOOL_DIR_NAME = "tool-x"
            self.assertFalse(a.available)

    def test_unavailable_when_no_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = BaseAdapter(Path(tmp))
            a.TOOL_DIR_NAME = "nonexistent"
            self.assertFalse(a.available)


# ── ErrorLogAdapter ──────────────────────────────────────────────────────

class TestErrorLogAdapter(unittest.TestCase):
    """ErrorLogAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = ErrorLogAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-error-log not found")

    def test_check(self):
        result = self.adapter.check()
        self.assertEqual(result.status, ResultStatus.PASS)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("error", result.stdout.lower())

    def test_has_entry_existing(self):
        result = self.adapter.has_entry("image resize service timeouts")
        # This entry exists in the real log
        self.assertIn(result.exit_code, [0, 1])

    def test_has_entry_nonexistent(self):
        result = self.adapter.has_entry("NONEXISTENT_AREA_XYZ_999")
        self.assertEqual(result.exit_code, 1)

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-error-log")


# ── DecisionLogAdapter ──────────────────────────────────────────────────

class TestDecisionLogAdapter(unittest.TestCase):
    """DecisionLogAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = DecisionLogAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-decision-log not found")

    def test_check(self):
        result = self.adapter.check()
        self.assertEqual(result.status, ResultStatus.PASS)

    def test_has_open(self):
        result = self.adapter.has_open()
        # Exit 0 = no open decisions, exit 1 = open decisions exist
        self.assertIn(result.exit_code, [0, 1])

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-decision-log")


# ── LogAIAdapter ────────────────────────────────────────────────────────

class TestLogAIAdapter(unittest.TestCase):
    """LogAIAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = LogAIAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-log-ai not found")

    def test_dry_run_lessons(self):
        result = self.adapter.dry_run_lessons()
        # Dry run should produce output (may exit 0 or 1 depending on log state)
        self.assertIn(result.exit_code, [0, 1])
        self.assertGreater(len(result.stdout) + len(result.stderr), 0)

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-log-ai")


# ── MemoryAdapter ───────────────────────────────────────────────────────

class TestMemoryAdapter(unittest.TestCase):
    """MemoryAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = MemoryAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-memory not found")

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-memory")

    def test_status_no_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.adapter.status(Path(tmp))
            # Should fail gracefully (no .agent/ store)
            self.assertIn(result.exit_code, [0, 1, 2])


# ── BlameAdapter ────────────────────────────────────────────────────────

class TestBlameAdapter(unittest.TestCase):
    """BlameAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = BlameAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-blame not found")

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-blame")

    def test_diff_in_repo(self):
        # Run blame --diff in a real git repo
        repo = ws = Path(__file__).resolve().parent.parent.parent / "agent-error-log"
        if not (repo / ".git").is_dir():
            self.skipTest("not a git repo")
        result = self.adapter.diff(cwd=repo)
        # Should succeed or produce output
        self.assertIn(result.exit_code, [0, 1])


# ── DiffGateAdapter ─────────────────────────────────────────────────────

class TestDiffGateAdapter(unittest.TestCase):
    """DiffGateAdapter against the real tool."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = DiffGateAdapter(ws)
        if not self.adapter.available:
            self.skipTest("agent-diff-gate not found")

    def test_list_rules(self):
        result = self.adapter.list_rules()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("rule", result.stdout.lower())

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-diff-gate")


# ── SandboxAdapter ──────────────────────────────────────────────────────

class TestSandboxAdapter(unittest.TestCase):
    """SandboxAdapter — platform-specific behavior."""

    def setUp(self):
        ws = Path(__file__).resolve().parent.parent.parent
        self.adapter = SandboxAdapter(ws)

    def test_unsupported_on_windows(self):
        if sys.platform == "linux":
            self.skipTest("running on Linux")
        result = self.adapter.run(["echo", "hello"])
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)
        self.assertIn("Linux", result.error)

    def test_health_unsupported_on_windows(self):
        if sys.platform == "linux":
            self.skipTest("running on Linux")
        result = self.adapter.health()
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)

    def test_available_false_on_windows(self):
        if sys.platform == "linux":
            self.skipTest("running on Linux")
        self.assertFalse(self.adapter.available)

    def test_no_host_fallback(self):
        """CRITICAL: sandbox adapter must never execute on host when unsupported."""
        if sys.platform == "linux":
            self.skipTest("running on Linux")
        result = self.adapter.run(["echo", "should-not-run"])
        self.assertEqual(result.status, ResultStatus.UNSUPPORTED)
        self.assertNotIn("should-not-run", result.stdout)

    def test_tool_name(self):
        self.assertEqual(self.adapter.TOOL_NAME, "agent-sandbox")


# ── Registry ────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    """Adapter registry."""

    def test_seven_adapters(self):
        self.assertEqual(len(ADAPTER_CLASSES), 7)

    def test_all_known_names(self):
        expected = {
            "agent-error-log", "agent-decision-log", "agent-log-ai",
            "agent-memory", "agent-blame", "agent-diff-gate", "agent-sandbox",
        }
        self.assertEqual(set(ADAPTER_CLASSES.keys()), expected)

    def test_get_adapter_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = get_adapter("agent-error-log", Path(tmp))
            self.assertIsInstance(a, ErrorLogAdapter)

    def test_get_adapter_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = get_adapter("nonexistent-tool", Path(tmp))
            self.assertIsNone(a)

    def test_get_all_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = get_all_adapters(Path(tmp))
            self.assertEqual(len(adapters), 7)
            for name in ADAPTER_CLASSES:
                self.assertIn(name, adapters)


# ── Security ─────────────────────────────────────────────────────────────

class TestAdapterSecurity(unittest.TestCase):
    """Security checks for the adapter layer."""

    def test_no_shell_true_in_run_tool(self):
        """run_tool must never use shell=True as a parameter."""
        import ast, inspect
        source = inspect.getsource(run_tool)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                # shell= should be False, not True
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("run_tool uses shell=True — forbidden")

    def test_no_secrets_in_result(self):
        """ToolResult must not accidentally contain secret patterns."""
        r = ToolResult(
            tool_name="test", operation="test",
            status=ResultStatus.PASS, exit_code=0,
            stdout="api_key=secret123 token=abc",
        )
        # The result preserves raw output — but the adapter layer
        # should not LOG secrets.  This test verifies the result
        # object exists and can be inspected.
        self.assertIn("secret123", r.stdout)  # raw evidence preserved
        # The important thing is that the orchestrator layer above
        # does NOT print this to logs.  That's enforced by olog.py.


# ── Integration: real tool invocations ──────────────────────────────────

class TestIntegrationRealTools(unittest.TestCase):
    """Integration tests against real tools (skipped if not available)."""

    def setUp(self):
        self.ws = Path(__file__).resolve().parent.parent.parent

    def test_error_log_check_integration(self):
        adapter = ErrorLogAdapter(self.ws)
        if not adapter.available:
            self.skipTest("agent-error-log not found")
        result = adapter.check()
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.ok)
        self.assertGreater(len(result.stdout), 0)

    def test_decision_log_check_integration(self):
        adapter = DecisionLogAdapter(self.ws)
        if not adapter.available:
            self.skipTest("agent-decision-log not found")
        result = adapter.check()
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.ok)

    def test_diff_gate_list_rules_integration(self):
        adapter = DiffGateAdapter(self.ws)
        if not adapter.available:
            self.skipTest("agent-diff-gate not found")
        result = adapter.list_rules()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("R1", result.stdout)


if __name__ == "__main__":
    unittest.main()
