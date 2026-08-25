"""Tests for orchestrator.config — configuration loading."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.config import (
    DEFAULTS,
    Config,
    _parse_key_value_config,
    load_config,
    load_workflow,
)


class TestDefaults(unittest.TestCase):
    """Verify default configuration values."""

    def test_has_mode(self):
        self.assertIn("mode", DEFAULTS)
        self.assertEqual(DEFAULTS["mode"], "solo")

    def test_has_sandbox_required(self):
        self.assertEqual(DEFAULTS["sandbox_required"], "true")

    def test_has_diff_gate_required(self):
        self.assertEqual(DEFAULTS["diff_gate_required"], "true")


class TestParseKeyValueConfig(unittest.TestCase):
    """_parse_key_value_config parses simple config files."""

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("")
            f.flush()
            result = _parse_key_value_config(Path(f.name))
            self.assertEqual(result, {})

    def test_missing_file(self):
        result = _parse_key_value_config(Path("/nonexistent/config"))
        self.assertEqual(result, {})

    def test_simple_pairs(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("mode = development\nsandbox_required = false\n")
            f.flush()
            result = _parse_key_value_config(Path(f.name))
            self.assertEqual(result["mode"], "development")
            self.assertEqual(result["sandbox_required"], "false")

    def test_comments_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("# this is a comment\nmode = solo\n")
            f.flush()
            result = _parse_key_value_config(Path(f.name))
            self.assertEqual(result, {"mode": "solo"})

    def test_blank_lines_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("\n\nmode = solo\n\n\n")
            f.flush()
            result = _parse_key_value_config(Path(f.name))
            self.assertEqual(result, {"mode": "solo"})

    def test_whitespace_stripped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("  mode  =  development  \n")
            f.flush()
            result = _parse_key_value_config(Path(f.name))
            self.assertEqual(result["mode"], "development")


class TestLoadConfig(unittest.TestCase):
    """load_config merges defaults with file overrides."""

    def test_defaults_when_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            self.assertEqual(config.mode, "solo")
            self.assertTrue(config.sandbox_required)
            self.assertTrue(config.diff_gate_required)
            self.assertFalse(config.has_config)

    def test_override_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("mode = security\nsandbox_required = false\n")
            config = load_config(Path(tmp))
            self.assertEqual(config.mode, "security")
            self.assertFalse(config.sandbox_required)
            self.assertTrue(config.has_config)

    def test_invalid_mode_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("mode = banana\n")
            with self.assertRaises(ValueError):
                load_config(Path(tmp))


class TestLoadWorkflow(unittest.TestCase):
    """load_workflow reads workflow.md when present."""

    def test_missing_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_workflow(Path(tmp))
            self.assertIsNone(result)

    def test_existing_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "workflow.md").write_text("# Workflow\nDo things.\n")
            result = load_workflow(Path(tmp))
            self.assertIsNotNone(result)
            self.assertIn("Workflow", result)


class TestConfigObject(unittest.TestCase):
    """Config accessor methods."""

    def test_getitem(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            self.assertEqual(config["mode"], "solo")

    def test_get_with_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            self.assertEqual(config.get("nonexistent", "fallback"), "fallback")

    def test_all_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            keys = config.all_keys()
            self.assertIn("mode", keys)
            self.assertEqual(keys, sorted(keys))

    def test_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            r = repr(config)
            self.assertIn("Config", r)
            self.assertIn("mode", r)


if __name__ == "__main__":
    unittest.main()
