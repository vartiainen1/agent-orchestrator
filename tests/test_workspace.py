"""Tests for orchestrator.workspace — detection logic."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.workspace import (
    TOOL_NAMES,
    _is_workspace,
    all_tools_available,
    cwd,
    detect_tool,
    detect_tools,
    find_orchestrator_root,
    find_project,
    find_workspace,
)


class TestToolNames(unittest.TestCase):
    """The canonical tool list must contain exactly 7 entries."""

    def test_seven_tools(self):
        self.assertEqual(len(TOOL_NAMES), 7)

    def test_all_strings(self):
        for name in TOOL_NAMES:
            self.assertIsInstance(name, str)
            self.assertTrue(name.startswith("agent-"))


class TestDetectTool(unittest.TestCase):
    """detect_tool inspects a single directory."""

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = detect_tool(Path(tmp) / "nonexistent")
            self.assertFalse(info["available"])

    def test_dir_with_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "my-tool"
            p.mkdir()
            (p / "pyproject.toml").write_text("[project]\n")
            info = detect_tool(p)
            self.assertTrue(info["available"])
            self.assertTrue(info["has_pyproject"])

    def test_dir_with_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "my-tool"
            p.mkdir()
            (p / "README.md").write_text("# Hello\n")
            info = detect_tool(p)
            self.assertTrue(info["available"])
            self.assertTrue(info["has_readme"])

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "empty-tool"
            p.mkdir()
            info = detect_tool(p)
            self.assertFalse(info["available"])


class TestDetectTools(unittest.TestCase):
    """detect_tools scans a workspace for all 7 canonical tools."""

    def test_no_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = detect_tools(Path(tmp))
            self.assertEqual(len(tools), 7)
            self.assertFalse(any(t["available"] for t in tools))

    def test_partial_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # Create only 2 tools.
            for name in ["agent-error-log", "agent-blame"]:
                d = ws / name
                d.mkdir()
                (d / "pyproject.toml").write_text("[project]\n")
            tools = detect_tools(ws)
            avail = [t for t in tools if t["available"]]
            self.assertEqual(len(avail), 2)

    def test_all_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name in TOOL_NAMES:
                d = ws / name
                d.mkdir()
                (d / "pyproject.toml").write_text("[project]\n")
            tools = detect_tools(ws)
            self.assertTrue(all_tools_available(tools))


class TestIsWorkspace(unittest.TestCase):
    """_is_workspace uses the >= 3 tool heuristic."""

    def test_empty_dir_not_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_is_workspace(Path(tmp)))

    def test_two_tools_not_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name in TOOL_NAMES[:2]:
                (ws / name).mkdir()
            self.assertFalse(_is_workspace(ws))

    def test_three_tools_is_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name in TOOL_NAMES[:3]:
                (ws / name).mkdir()
            self.assertTrue(_is_workspace(ws))


class TestFindWorkspace(unittest.TestCase):
    """find_workspace locates the workspace by walking upward."""

    def test_from_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name in TOOL_NAMES[:3]:
                (ws / name).mkdir()
            self.assertEqual(find_workspace(ws), ws)

    def test_from_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name in TOOL_NAMES[:4]:
                (ws / name).mkdir()
            sub = ws / "project" / "src"
            sub.mkdir(parents=True)
            self.assertEqual(find_workspace(sub), ws)

    def test_no_workspace_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Only 2 tools — not enough.
            ws = Path(tmp)
            for name in TOOL_NAMES[:2]:
                (ws / name).mkdir()
            self.assertIsNone(find_workspace(ws))


class TestFindProject(unittest.TestCase):
    """find_project returns the resolved starting directory."""

    def test_finds_cwd(self):
        result = find_project()
        self.assertEqual(result, cwd())

    def test_finds_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = find_project(Path(tmp))
            self.assertEqual(result, Path(tmp).resolve())


class TestOrchestratorRoot(unittest.TestCase):
    """find_orchestrator_root locates the orchestrator package."""

    def test_returns_path(self):
        root = find_orchestrator_root()
        self.assertIsInstance(root, Path)
        # The root should contain orchestrator/ package.
        self.assertTrue((root / "orchestrator").is_dir())


if __name__ == "__main__":
    unittest.main()
