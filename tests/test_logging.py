"""Tests for orchestrator.logging — structured logging."""

import unittest
from io import StringIO
from unittest.mock import patch

from orchestrator import olog as orch_log


class TestLogLevel(unittest.TestCase):
    """Level get/set."""

    def test_default_level(self):
        orch_log.set_level("INFO")
        self.assertEqual(orch_log.get_level(), "INFO")

    def test_set_debug(self):
        orch_log.set_level("DEBUG")
        self.assertEqual(orch_log.get_level(), "DEBUG")

    def test_invalid_level_raises(self):
        with self.assertRaises(ValueError):
            orch_log.set_level("BANANA")


class TestLogging(unittest.TestCase):
    """Log emission and filtering."""

    def setUp(self):
        orch_log.set_level("INFO")

    def test_info_emitted(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.info("hello")
            self.assertIn("hello", buf.getvalue())

    def test_debug_suppressed_at_info(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.debug("secret")
            self.assertNotIn("secret", buf.getvalue())

    def test_debug_emitted_at_debug(self):
        orch_log.set_level("DEBUG")
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.debug("visible")
            self.assertIn("visible", buf.getvalue())

    def test_component_tagged(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.info("msg", component="test")
            output = buf.getvalue()
            self.assertIn("[test]", output)
            self.assertIn("msg", output)

    def test_timestamp_present(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.info("ts-check")
            output = buf.getvalue()
            # ISO timestamp format: 2026-...
            self.assertIn("2026-", output)

    def test_error_level(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.error("bad thing")
            output = buf.getvalue()
            self.assertIn("ERROR", output)
            self.assertIn("bad thing", output)

    def test_warn_level(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            orch_log.warn("caution")
            output = buf.getvalue()
            self.assertIn("WARN", output)
            self.assertIn("caution", output)


if __name__ == "__main__":
    unittest.main()
