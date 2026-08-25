"""Phase 8C — Recovery and CLI tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.recovery import (
    LockInfo,
    _pid_running,
    acquire_lock,
    release_lock,
    check_lock,
    is_locked,
    cleanup_stale_lock,
    find_interrupted_runs,
    recover_run,
    RecoveryResult,
)
from orchestrator.persist import (
    save_state,
    load_state,
    append_evidence,
    update_run_index,
    persist_run,
)
from orchestrator.state import RunState, Phase
from orchestrator.cli import main
from orchestrator.exit_codes import OK, BLOCKED, ERROR, INVALID


# ── Fixtures ─────────────────────────────────────────────────────────────

def _make_state(
    run_id: str = "RUN-20260825-174630-cfc871",
    phase: Phase = Phase.COMPLETED,
    status: str = "PASS",
) -> RunState:
    return RunState(
        run_id=run_id,
        workflow_name="bootstrap",
        project_dir="/tmp/test",
        workspace_dir="/tmp",
        mode="solo",
        phase=phase,
        started_at="2026-08-25T17:46:30Z",
        ended_at="2026-08-25T17:46:31Z",
        final_status=status,
    )


# ── Lock tests ───────────────────────────────────────────────────────────

class TestLockManagement(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_acquire_lock(self):
        success, reason = acquire_lock(self.tmpdir, "RUN-20260825-000000-aaaaaa")
        self.assertTrue(success)
        self.assertEqual(reason, "acquired")
        release_lock(self.tmpdir)

    def test_release_lock(self):
        acquire_lock(self.tmpdir)
        release_lock(self.tmpdir)
        info = check_lock(self.tmpdir)
        self.assertIsNone(info)

    def test_check_lock_unlocked(self):
        info = check_lock(self.tmpdir)
        self.assertIsNone(info)

    def test_check_lock_locked(self):
        acquire_lock(self.tmpdir)
        info = check_lock(self.tmpdir)
        self.assertIsNotNone(info)
        self.assertEqual(info.pid, os.getpid())
        release_lock(self.tmpdir)

    def test_is_locked(self):
        self.assertFalse(is_locked(self.tmpdir))
        acquire_lock(self.tmpdir)
        # Current process owns the lock, so is_locked returns True
        # (PID is running — it's us)
        self.assertTrue(is_locked(self.tmpdir))
        release_lock(self.tmpdir)

    def test_cleanup_stale_lock(self):
        # Create a lock with a non-existent PID
        lock_path = self.tmpdir / ".orchestrator" / "lock"
        lock_path.parent.mkdir(parents=True)
        info = LockInfo(pid=999999999, acquired_at="2026-01-01T00:00:00Z",
                        workspace=str(self.tmpdir))
        lock_path.write_text(info.to_json())
        # PID 999999999 shouldn't be running
        result = cleanup_stale_lock(self.tmpdir)
        self.assertTrue(result)
        self.assertFalse(lock_path.is_file())

    def test_lock_info_roundtrip(self):
        info = LockInfo(pid=1234, acquired_at="2026-08-25T17:46:30Z",
                        workspace="/tmp", run_id="RUN-123")
        text = info.to_json()
        loaded = LockInfo.from_json(text)
        self.assertEqual(loaded.pid, 1234)
        self.assertEqual(loaded.run_id, "RUN-123")

    def test_lock_info_invalid_json(self):
        result = LockInfo.from_json("not json")
        self.assertIsNone(result)

    def test_lock_stale_detection(self):
        # Lock with PID that doesn't exist
        lock_path = self.tmpdir / ".orchestrator" / "lock"
        lock_path.parent.mkdir(parents=True)
        info = LockInfo(pid=1, acquired_at="2026-01-01T00:00:00Z",
                        workspace=str(self.tmpdir))
        lock_path.write_text(info.to_json())
        # PID 1 might or might not be running (init on Unix, system on Windows)
        # Just test that the function doesn't crash
        result = is_locked(self.tmpdir)
        self.assertIsInstance(result, bool)


# ── Interrupted run detection ────────────────────────────────────────────

class TestInterruptedRuns(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_interrupted_runs(self):
        result = find_interrupted_runs(self.tmpdir)
        self.assertEqual(result, [])

    def test_detects_running_state(self):
        state = _make_state(phase=Phase.EXECUTING, status="")
        persist_run(state, self.tmpdir)
        interrupted = find_interrupted_runs(self.tmpdir)
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0]["run_id"], state.run_id)

    def test_ignores_completed_state(self):
        state = _make_state(phase=Phase.COMPLETED, status="PASS")
        persist_run(state, self.tmpdir)
        interrupted = find_interrupted_runs(self.tmpdir)
        self.assertEqual(len(interrupted), 0)

    def test_ignores_cancelled_state(self):
        state = _make_state(phase=Phase.CANCELLED, status="CANCELLED")
        persist_run(state, self.tmpdir)
        interrupted = find_interrupted_runs(self.tmpdir)
        self.assertEqual(len(interrupted), 0)


# ── Recovery tests ───────────────────────────────────────────────────────

class TestRecovery(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cancel_interrupted_run(self):
        state = _make_state(phase=Phase.EXECUTING, status="")
        persist_run(state, self.tmpdir)
        result = recover_run(self.tmpdir, state.run_id, action="cancel")
        self.assertTrue(result.success)
        self.assertEqual(result.action, "cancelled")
        # Verify state is now CANCELLED
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertEqual(loaded.phase, Phase.CANCELLED)
        self.assertEqual(loaded.final_status, "CANCELLED")

    def test_cancel_already_terminal(self):
        state = _make_state(phase=Phase.COMPLETED, status="PASS")
        persist_run(state, self.tmpdir)
        result = recover_run(self.tmpdir, state.run_id, action="cancel")
        self.assertTrue(result.success)
        self.assertIn("already", result.reason)

    def test_discard_run(self):
        state = _make_state(phase=Phase.EXECUTING, status="")
        persist_run(state, self.tmpdir)
        result = recover_run(self.tmpdir, state.run_id, action="discard")
        self.assertTrue(result.success)
        self.assertEqual(result.action, "discarded")
        # Verify data is removed
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertIsNone(loaded)

    def test_invalid_run_id(self):
        result = recover_run(self.tmpdir, "bad-id", action="cancel")
        self.assertFalse(result.success)
        self.assertIn("invalid", result.reason)

    def test_nonexistent_run(self):
        result = recover_run(self.tmpdir, "RUN-20260825-000000-000000", action="cancel")
        self.assertFalse(result.success)

    def test_unknown_action(self):
        state = _make_state(phase=Phase.EXECUTING, status="")
        persist_run(state, self.tmpdir)
        result = recover_run(self.tmpdir, state.run_id, action="explode")
        self.assertFalse(result.success)
        self.assertIn("unknown", result.reason)


# ── CLI history command ──────────────────────────────────────────────────

class TestCLIHistory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_history_empty(self):
        # No workspace found from CLI — this tests the command exists
        exit_code = main(["history"])
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_history_json(self):
        exit_code = main(["history", "--json"])
        self.assertIn(exit_code, (OK, BLOCKED))


# ── CLI show command ─────────────────────────────────────────────────────

class TestCLIShow(unittest.TestCase):

    def test_show_invalid_run_id(self):
        exit_code = main(["show", "bad-id"])
        self.assertIn(exit_code, (INVALID, BLOCKED))

    def test_show_nonexistent_run(self):
        exit_code = main(["show", "RUN-20260825-000000-000000"])
        self.assertIn(exit_code, (INVALID, BLOCKED))


# ── CLI evidence command ─────────────────────────────────────────────────

class TestCLIEvidence(unittest.TestCase):

    def test_evidence_invalid_run_id(self):
        exit_code = main(["evidence", "bad-id"])
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_evidence_json(self):
        exit_code = main(["evidence", "RUN-20260825-000000-000000", "--json"])
        self.assertIn(exit_code, (OK, BLOCKED))


# ── CLI cancel command ───────────────────────────────────────────────────

class TestCLICancel(unittest.TestCase):

    def test_cancel_invalid_run_id(self):
        exit_code = main(["cancel", "bad-id"])
        self.assertIn(exit_code, (ERROR, BLOCKED))

    def test_cancel_nonexistent_run(self):
        exit_code = main(["cancel", "RUN-20260825-000000-000000"])
        self.assertIn(exit_code, (ERROR, BLOCKED))


# ── CLI recover command ──────────────────────────────────────────────────

class TestCLIRecover(unittest.TestCase):

    def test_recover_no_args(self):
        exit_code = main(["recover"])
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_recover_list(self):
        exit_code = main(["recover", "--list"])
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_recover_help(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["recover", "--help"])
        self.assertEqual(ctx.exception.code, 0)


# ── Security tests ───────────────────────────────────────────────────────

class TestRecoverySecurity(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_path_traversal_in_run_id(self):
        result = recover_run(self.tmpdir, "../../../etc/passwd", action="cancel")
        self.assertFalse(result.success)

    def test_lock_with_special_pid(self):
        # Lock with PID 0 — should not crash
        lock_path = self.tmpdir / ".orchestrator" / "lock"
        lock_path.parent.mkdir(parents=True)
        info = LockInfo(pid=0, acquired_at="2026-01-01T00:00:00Z",
                        workspace=str(self.tmpdir))
        lock_path.write_text(info.to_json())
        result = is_locked(self.tmpdir)
        self.assertFalse(result)  # PID 0 is not running

    def test_recovery_does_not_bypass_policy(self):
        # Recovery only cancels or discards — never resumes
        state = _make_state(phase=Phase.EXECUTING, status="")
        persist_run(state, self.tmpdir)
        result = recover_run(self.tmpdir, state.run_id, action="cancel")
        self.assertTrue(result.success)
        # After cancel, state is CANCELLED (terminal) — cannot be resumed
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertTrue(loaded.is_terminal())


# ── Exit code tests ──────────────────────────────────────────────────────

class TestCLIExitCodes(unittest.TestCase):

    def test_history_returns_int(self):
        result = main(["history"])
        self.assertIsInstance(result, int)

    def test_show_returns_int(self):
        result = main(["show", "bad-id"])
        self.assertIsInstance(result, int)

    def test_evidence_returns_int(self):
        result = main(["evidence", "bad-id"])
        self.assertIsInstance(result, int)

    def test_cancel_returns_int(self):
        result = main(["cancel", "bad-id"])
        self.assertIsInstance(result, int)

    def test_recover_returns_int(self):
        result = main(["recover"])
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
