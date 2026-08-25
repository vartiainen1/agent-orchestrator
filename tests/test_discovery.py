from orchestrator.workspace import find_workspace
"""Tests for orchestrator.discovery — Phase 2 tool discovery."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.discovery import (
    TOOL_REGISTRY,
    Capability,
    ToolInfo,
    ToolStatus,
    _health_check,
    _read_entry_point,
    _read_git_tag,
    _read_pyproject_version,
    _read_requires_python,
    discover_all,
    discover_tool,
    format_summary,
    format_tool_info,
    summary,
)


class TestToolStatus(unittest.TestCase):
    """ToolStatus enum has exactly the required states."""

    def test_six_states(self):
        states = [s.value for s in ToolStatus]
        self.assertEqual(len(states), 6)
        self.assertIn("AVAILABLE", states)
        self.assertIn("MISSING", states)
        self.assertIn("INVALID", states)
        self.assertIn("UNSUPPORTED", states)
        self.assertIn("BLOCKED", states)
        self.assertIn("ERROR", states)


class TestCapability(unittest.TestCase):
    """Capability enum covers the known tool capabilities."""

    def test_nine_capabilities(self):
        caps = [c.value for c in Capability]
        self.assertEqual(len(caps), 9)
        self.assertIn("log-errors", caps)
        self.assertIn("execute-sandboxed", caps)


class TestToolInfo(unittest.TestCase):
    """ToolInfo dataclass construction."""

    def test_defaults(self):
        info = ToolInfo(name="test", path=Path("/tmp"))
        self.assertEqual(info.status, ToolStatus.MISSING)
        self.assertEqual(info.version, "")
        self.assertFalse(info.health_ok)
        self.assertEqual(info.capabilities, [])

    def test_repr(self):
        info = ToolInfo(name="x", path=Path("/x"), status=ToolStatus.AVAILABLE, version="1.0")
        r = repr(info)
        self.assertIn("x", r)
        self.assertIn("AVAILABLE", r)
        self.assertIn("1.0", r)


class TestToolRegistry(unittest.TestCase):
    """The canonical registry contains exactly 7 entries."""

    def test_seven_entries(self):
        self.assertEqual(len(TOOL_REGISTRY), 7)

    def test_all_have_names(self):
        for reg in TOOL_REGISTRY:
            self.assertIn("name", reg)
            self.assertTrue(reg["name"].startswith("agent-"))

    def test_all_have_entry_modules(self):
        for reg in TOOL_REGISTRY:
            self.assertIn("entry_module", reg)
            self.assertIsInstance(reg["entry_module"], str)


class TestReadPyprojectVersion(unittest.TestCase):
    """_read_pyproject_version extracts version from pyproject.toml."""

    def test_static_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pyproject.toml"
            p.write_text('[project]\nversion = "1.2.3"\n')
            self.assertEqual(_read_pyproject_version(Path(tmp)), "1.2.3")

    def test_dynamic_version_falls_back_to_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pyproject.toml"
            p.write_text('[project]\ndynamic = ["version"]\n')
            # No git repo — should return ""
            self.assertEqual(_read_pyproject_version(Path(tmp)), "")

    def test_missing_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_read_pyproject_version(Path(tmp)), "")


class TestReadEntryPoint(unittest.TestCase):
    """_read_entry_point parses pyproject.toml scripts."""

    def test_parses_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pyproject.toml"
            p.write_text('[project.scripts]\nmy-tool = "my_mod:main"\n')
            cmd, ep = _read_entry_point(Path(tmp))
            self.assertEqual(cmd, "my-tool")
            self.assertEqual(ep, "my_mod:main")

    def test_missing_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd, ep = _read_entry_point(Path(tmp))
            self.assertEqual(cmd, "")
            self.assertEqual(ep, "")


class TestReadRequiresPython(unittest.TestCase):
    """_read_requires_python extracts requires-python."""

    def test_extracts_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pyproject.toml"
            p.write_text('[project]\nrequires-python = ">=3.11"\n')
            self.assertEqual(_read_requires_python(Path(tmp)), ">=3.11")

    def test_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_read_requires_python(Path(tmp)), "")


class TestDiscoverTool(unittest.TestCase):
    """discover_tool inspects a single tool directory."""

    def test_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = TOOL_REGISTRY[0]
            info = discover_tool(Path(tmp) / "nonexistent", reg)
            self.assertEqual(info.status, ToolStatus.MISSING)
            self.assertFalse(info.health_ok)
            self.assertTrue(len(info.discovery_errors) > 0)

    def test_invalid_no_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "agent-test"
            d.mkdir()
            (d / "README.md").write_text("# Test\n")
            reg = TOOL_REGISTRY[0]
            info = discover_tool(d, reg)
            self.assertEqual(info.status, ToolStatus.INVALID)
            self.assertIn("pyproject.toml", info.discovery_errors[0])

    def test_valid_tool(self):
        """Test with the real agent-error-log if available."""
        workspace = find_workspace(Path(__file__).resolve().parent)
        if workspace is None:
            self.skipTest("workspace not found")
        tool_dir = workspace / "agent-error-log"
        if not tool_dir.is_dir():
            self.skipTest("agent-error-log not found")
        reg = TOOL_REGISTRY[0]  # agent-error-log
        info = discover_tool(tool_dir, reg)
        self.assertEqual(info.status, ToolStatus.AVAILABLE)
        self.assertTrue(info.health_ok)
        self.assertTrue(info.has_pyproject)
        self.assertTrue(info.has_readme)
        self.assertTrue(info.has_start_py)
        self.assertTrue(info.has_agents_md)
        self.assertIn(Capability.LOG_ERRORS.value, info.capabilities)

    def test_linux_only_tool_on_windows(self):
        """agent-sandbox should be UNSUPPORTED on Windows."""
        import sys
        if sys.platform == "linux":
            self.skipTest("running on Linux")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "agent-sandbox"
            d.mkdir()
            # Minimal pyproject.toml
            (d / "pyproject.toml").write_text(
                '[project]\nversion = "0.1.0"\n'
                '[project.scripts]\nagent-sandbox = "agent_sandbox.cli:main"\n'
            )
            # Minimal module
            mod = d / "agent_sandbox"
            mod.mkdir()
            (mod / "__init__.py").write_text("")
            (mod / "cli.py").write_text(
                'import sys\ndef main(): print("help"); sys.exit(0)\n'
            )
            reg = {
                "name": "agent-sandbox",
                "entry_module": "agent_sandbox.cli",
                "capabilities": ["execute-sandboxed"],
                "platform_support": "linux-only",
            }
            info = discover_tool(d, reg)
            self.assertEqual(info.status, ToolStatus.UNSUPPORTED)


class TestDiscoverAll(unittest.TestCase):
    """discover_all scans all 7 tools."""

    def test_with_real_workspace(self):
        workspace = find_workspace(Path(__file__).resolve().parent)
        if not (workspace / "agent-error-log").is_dir():
            self.skipTest("workspace not found")
        tools = discover_all(workspace)
        self.assertEqual(len(tools), 7)
        # agent-error-log should be available
        err_log = [t for t in tools if t.name == "agent-error-log"][0]
        self.assertEqual(err_log.status, ToolStatus.AVAILABLE)

    def test_with_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = discover_all(Path(tmp))
            self.assertEqual(len(tools), 7)
            # All should be MISSING
            for t in tools:
                self.assertEqual(t.status, ToolStatus.MISSING)


class TestSummary(unittest.TestCase):
    """summary counts tool statuses."""

    def test_all_available(self):
        tools = [
            ToolInfo(name="a", path=Path("/a"), status=ToolStatus.AVAILABLE),
            ToolInfo(name="b", path=Path("/b"), status=ToolStatus.AVAILABLE),
        ]
        s = summary(tools)
        self.assertEqual(s["AVAILABLE"], 2)
        self.assertEqual(s["total"], 2)

    def test_mixed(self):
        tools = [
            ToolInfo(name="a", path=Path("/a"), status=ToolStatus.AVAILABLE),
            ToolInfo(name="b", path=Path("/b"), status=ToolStatus.MISSING),
            ToolInfo(name="c", path=Path("/c"), status=ToolStatus.ERROR),
        ]
        s = summary(tools)
        self.assertEqual(s["AVAILABLE"], 1)
        self.assertEqual(s["MISSING"], 1)
        self.assertEqual(s["ERROR"], 1)
        self.assertEqual(s["total"], 3)


class TestFormatToolInfo(unittest.TestCase):
    """format_tool_info produces readable output."""

    def test_basic_format(self):
        info = ToolInfo(
            name="agent-test",
            path=Path("/tmp/test"),
            status=ToolStatus.AVAILABLE,
            version="1.0.0",
        )
        text = format_tool_info(info)
        self.assertIn("agent-test", text)
        self.assertIn("AVAILABLE", text)
        self.assertIn("1.0.0", text)

    def test_verbose_format(self):
        info = ToolInfo(
            name="agent-test",
            path=Path("/tmp/test"),
            status=ToolStatus.AVAILABLE,
            has_pyproject=True,
            has_readme=True,
        )
        text = format_tool_info(info, verbose=True)
        self.assertIn("pyproject", text)
        self.assertIn("readme", text)

    def test_errors_shown(self):
        info = ToolInfo(
            name="agent-test",
            path=Path("/tmp/test"),
            status=ToolStatus.MISSING,
            discovery_errors=["not found"],
        )
        text = format_tool_info(info)
        self.assertIn("ERROR", text)
        self.assertIn("not found", text)


class TestFormatSummary(unittest.TestCase):
    """format_summary produces the summary line."""

    def test_format(self):
        tools = [
            ToolInfo(name="a", path=Path("/a"), status=ToolStatus.AVAILABLE),
            ToolInfo(name="b", path=Path("/b"), status=ToolStatus.MISSING),
        ]
        text = format_summary(tools)
        self.assertIn("2 discovered", text)
        self.assertIn("1 available", text)
        self.assertIn("1 missing", text)


class TestHealthCheck(unittest.TestCase):
    """_health_check runs safely."""

    def test_with_real_tool(self):
        workspace = find_workspace(Path(__file__).resolve().parent)
        if workspace is None:
            self.skipTest("workspace not found")
        tool_dir = workspace / "agent-error-log"
        if not tool_dir.is_dir():
            self.skipTest("agent-error-log not found")
        ok, out, err = _health_check(tool_dir, "check_errors")
        self.assertTrue(ok)
        self.assertIn("usage", out.lower())

    def test_with_nonexistent_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, out, err = _health_check(Path(tmp), "nonexistent_module_xyz")
            self.assertFalse(ok)


class TestNoSecrets(unittest.TestCase):
    """Discovery output must not accidentally contain secrets."""

    def test_no_api_keys_in_output(self):
        workspace = find_workspace(Path(__file__).resolve().parent)
        if not (workspace / "agent-error-log").is_dir():
            self.skipTest("workspace not found")
        tools = discover_all(workspace)
        full_output = "\n".join(format_tool_info(t) for t in tools)
        # Check for common secret patterns
        self.assertNotIn("api_key", full_output.lower())
        self.assertNotIn("password", full_output.lower())
        self.assertNotIn("token", full_output.lower())
        self.assertNotIn("secret", full_output.lower())


if __name__ == "__main__":
    unittest.main()
