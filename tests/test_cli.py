"""Tests for orchestrator.cli — Phase 1 commands."""

import unittest
from io import StringIO
from unittest.mock import patch

from orchestrator import __version__, exit_codes
from orchestrator.cli import main


class TestCliVersion(unittest.TestCase):
    """--version prints the version and exits 0."""

    def test_version_exits_zero(self):
        with patch("sys.stdout", new_callable=StringIO):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
            self.assertEqual(ctx.exception.code, 0)

    def test_version_contains_number(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            with self.assertRaises(SystemExit):
                main(["--version"])
            self.assertIn(__version__, buf.getvalue())


class TestCliHelp(unittest.TestCase):
    """--help prints usage and exits 0."""

    def test_help_exits_zero(self):
        with patch("sys.stdout", new_callable=StringIO):
            with self.assertRaises(SystemExit) as ctx:
                main(["--help"])
            self.assertEqual(ctx.exception.code, 0)

    def test_help_mentions_orchestrator(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            with self.assertRaises(SystemExit):
                main(["--help"])
            self.assertIn("orchestrator", buf.getvalue().lower())


class TestCliNoCommand(unittest.TestCase):
    """No arguments prints help and exits 0."""

    def test_no_args_exits_zero(self):
        with patch("sys.stdout", new_callable=StringIO):
            rc = main([])
            self.assertEqual(rc, exit_codes.OK)


class TestCliStatus(unittest.TestCase):
    """status command returns OK."""

    def test_status_exits_zero(self):
        with patch("sys.stdout", new_callable=StringIO):
            rc = main(["status"])
            self.assertEqual(rc, exit_codes.OK)

    def test_status_mentions_project(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            rc = main(["status"])
            output = buf.getvalue()
            self.assertIn("project", output.lower())
            self.assertEqual(rc, exit_codes.OK)


class TestCliDoctor(unittest.TestCase):
    """doctor command returns OK (Phase 1 stub)."""

    def test_doctor_exits_zero(self):
        with patch("sys.stdout", new_callable=StringIO):
            rc = main(["doctor"])
            self.assertEqual(rc, exit_codes.OK)

    def test_doctor_mentions_python(self):
        with patch("sys.stdout", new_callable=StringIO) as buf:
            rc = main(["doctor"])
            output = buf.getvalue()
            self.assertIn("Python", output)
            self.assertEqual(rc, exit_codes.OK)


class TestCliVerbose(unittest.TestCase):
    """--verbose enables debug logging."""

    def test_verbose_flag_accepted(self):
        with patch("sys.stdout", new_callable=StringIO):
            rc = main(["--verbose", "status"])
            self.assertEqual(rc, exit_codes.OK)


if __name__ == "__main__":
    unittest.main()
