"""Tests for orchestrator.exit_codes."""

import unittest

from orchestrator import exit_codes


class TestExitCodes(unittest.TestCase):
    """Verify exit code constants have expected values and are distinct."""

    def test_ok_is_zero(self):
        self.assertEqual(exit_codes.OK, 0)

    def test_error_is_one(self):
        self.assertEqual(exit_codes.ERROR, 1)

    def test_blocked_is_two(self):
        self.assertEqual(exit_codes.BLOCKED, 2)

    def test_invalid_is_three(self):
        self.assertEqual(exit_codes.INVALID, 3)

    def test_all_distinct(self):
        codes = [exit_codes.OK, exit_codes.ERROR, exit_codes.BLOCKED, exit_codes.INVALID]
        self.assertEqual(len(codes), len(set(codes)), "exit codes must be unique")


if __name__ == "__main__":
    unittest.main()
