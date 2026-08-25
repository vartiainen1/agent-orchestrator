"""Phase 8A — Persistence tests.

Tests for crash-safe persistence of run state and evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from orchestrator.persist import (
    _validate_run_id,
    _atomic_write,
    _atomic_append_line,
    save_state,
    load_state,
    append_evidence,
    load_evidence,
    evidence_count,
    update_run_index,
    list_runs,
    get_persisted_run,
    persist_run,
    validate_persisted_state,
    find_interrupted_runs,
    PersistedRun,
    RunIndex,
)
from orchestrator.state import RunState, Phase, ToolCall
from orchestrator.evidence import EvidenceLog


# ── Fixtures ─────────────────────────────────────────────────────────────

def _make_state(
    run_id: str = "RUN-20260825-174630-cfc871",
    workflow: str = "bootstrap",
    mode: str = "solo",
    phase: Phase = Phase.COMPLETED,
    status: str = "PASS",
) -> RunState:
    """Create a test RunState."""
    return RunState(
        run_id=run_id,
        workflow_name=workflow,
        project_dir="/tmp/test",
        workspace_dir="/tmp",
        mode=mode,
        phase=phase,
        started_at="2026-08-25T17:46:30Z",
        ended_at="2026-08-25T17:46:31Z",
        final_status=status,
    )


def _make_state_with_tools(run_id: str = "RUN-20260825-174630-cfc871") -> RunState:
    """Create a test RunState with tool calls."""
    state = _make_state(run_id=run_id, phase=Phase.COMPLETED, status="PASS")
    state.tool_calls.append(ToolCall(
        tool_name="agent-error-log",
        operation="check",
        exit_code=0,
        status="PASS",
        duration=0.1,
    ))
    state.tool_calls.append(ToolCall(
        tool_name="agent-decision-log",
        operation="check",
        exit_code=0,
        status="PASS",
        duration=0.1,
    ))
    state.gate_results.append({
        "gate": "check_error_log",
        "passed": "True",
        "detail": "",
        "timestamp": "2026-08-25T17:46:30Z",
    })
    state.policy_decisions.append({
        "rule": "error_log_required",
        "outcome": "ALLOW",
        "reason": "rule is true and tool available",
        "mandatory": "True",
    })
    return state


# ── Run ID validation ───────────────────────────────────────────────────

class TestRunIdValidation(unittest.TestCase):

    def test_valid_run_id(self):
        self.assertTrue(_validate_run_id("RUN-20260825-174630-cfc871"))

    def test_empty_run_id(self):
        self.assertFalse(_validate_run_id(""))

    def test_path_traversal(self):
        self.assertFalse(_validate_run_id("../../../etc/passwd"))

    def test_too_long(self):
        self.assertFalse(_validate_run_id("R" * 100))

    def test_bad_format(self):
        self.assertFalse(_validate_run_id("run-2026-08-25"))


# ── Atomic writes ────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_atomic_write_creates_file(self):
        path = self.tmpdir / "test.txt"
        _atomic_write(path, "hello world")
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(), "hello world")

    def test_atomic_write_overwrites(self):
        path = self.tmpdir / "test.txt"
        _atomic_write(path, "first")
        _atomic_write(path, "second")
        self.assertEqual(path.read_text(), "second")

    def test_atomic_write_no_temp_left_on_success(self):
        path = self.tmpdir / "test.txt"
        _atomic_write(path, "content")
        tmp_files = list(self.tmpdir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_atomic_write_creates_parent_dirs(self):
        path = self.tmpdir / "sub" / "dir" / "file.txt"
        _atomic_write(path, "nested")
        self.assertEqual(path.read_text(), "nested")

    def test_atomic_append_line(self):
        path = self.tmpdir / "log.jsonl"
        _atomic_append_line(path, '{"a": 1}')
        _atomic_append_line(path, '{"b": 2}')
        lines = path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"a": 1})
        self.assertEqual(json.loads(lines[1]), {"b": 2})

    def test_atomic_append_empty_file(self):
        path = self.tmpdir / "empty.jsonl"
        _atomic_append_line(path, '{"x": 1}')
        self.assertTrue(path.is_file())
        content = path.read_text()
        self.assertIn('{"x": 1}', content)


# ── State persistence ────────────────────────────────────────────────────

class TestStatePersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load_state(self):
        state = _make_state()
        save_state(state, self.tmpdir)
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.run_id, state.run_id)
        self.assertEqual(loaded.workflow_name, "bootstrap")
        self.assertEqual(loaded.phase, Phase.COMPLETED)
        self.assertEqual(loaded.final_status, "PASS")

    def test_state_with_tools_roundtrip(self):
        state = _make_state_with_tools()
        save_state(state, self.tmpdir)
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertEqual(len(loaded.tool_calls), 2)
        self.assertEqual(loaded.tool_calls[0].tool_name, "agent-error-log")
        self.assertEqual(len(loaded.gate_results), 1)
        self.assertEqual(len(loaded.policy_decisions), 1)

    def test_load_nonexistent_returns_none(self):
        result = load_state("RUN-20260825-000000-000000", self.tmpdir)
        self.assertIsNone(result)

    def test_load_invalid_run_id_returns_none(self):
        result = load_state("../../../etc/passwd", self.tmpdir)
        self.assertIsNone(result)

    def test_load_corrupt_file_returns_none(self):
        run_dir = self.tmpdir / "runs" / "RUN-20260825-000000-000000"
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text("NOT JSON {{{")
        result = load_state("RUN-20260825-000000-000000", self.tmpdir)
        self.assertIsNone(result)

    def test_save_invalid_run_id_raises(self):
        state = _make_state(run_id="bad-id")
        with self.assertRaises(ValueError):
            save_state(state, self.tmpdir)

    def test_multiple_runs_isolated(self):
        s1 = _make_state(run_id="RUN-20260825-000000-aaaaaa", status="PASS")
        s2 = _make_state(run_id="RUN-20260825-000000-bbbbbb", status="FAIL")
        save_state(s1, self.tmpdir)
        save_state(s2, self.tmpdir)
        loaded1 = load_state(s1.run_id, self.tmpdir)
        loaded2 = load_state(s2.run_id, self.tmpdir)
        self.assertEqual(loaded1.final_status, "PASS")
        self.assertEqual(loaded2.final_status, "FAIL")

    def test_state_preserves_all_fields(self):
        state = _make_state()
        state.observations.append("[2026-08-25T17:46:30Z] test observation")
        save_state(state, self.tmpdir)
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertEqual(len(loaded.observations), 1)
        self.assertIn("test observation", loaded.observations[0])


# ── Evidence persistence ────────────────────────────────────────────────

class TestEvidencePersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.run_id = "RUN-20260825-174630-cfc871"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_append_and_load_evidence(self):
        entry = {"action": "test", "run_id": self.run_id}
        append_evidence(entry, self.tmpdir, self.run_id)
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "test")

    def test_multiple_entries(self):
        for i in range(5):
            append_evidence({"action": f"step_{i}", "run_id": self.run_id},
                            self.tmpdir, self.run_id)
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["action"], "step_0")
        self.assertEqual(entries[4]["action"], "step_4")

    def test_load_nonexistent_returns_empty(self):
        entries = load_evidence("RUN-20260825-000000-000000", self.tmpdir)
        self.assertEqual(entries, [])

    def test_load_invalid_run_id_returns_empty(self):
        entries = load_evidence("bad-id", self.tmpdir)
        self.assertEqual(entries, [])

    def test_evidence_count(self):
        for i in range(3):
            append_evidence({"action": f"e{i}", "run_id": self.run_id},
                            self.tmpdir, self.run_id)
        self.assertEqual(evidence_count(self.run_id, self.tmpdir), 3)

    def test_evidence_count_nonexistent(self):
        self.assertEqual(evidence_count("RUN-20260825-000000-000000", self.tmpdir), 0)

    def test_append_invalid_run_id_raises(self):
        with self.assertRaises(ValueError):
            append_evidence({"action": "x"}, self.tmpdir, "bad-id")

    def test_corrupt_line_in_evidence(self):
        path = self.tmpdir / "runs" / self.run_id / "evidence.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"ok": true}\nNOT JSON\n{"also": true}\n')
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 3)
        # The corrupt line gets a marker
        corrupt = [e for e in entries if e.get("action") == "CORRUPTED_LINE"]
        self.assertEqual(len(corrupt), 1)

    def test_multiple_runs_evidence_isolated(self):
        run1 = "RUN-20260825-000000-aaaaaa"
        run2 = "RUN-20260825-000000-bbbbbb"
        append_evidence({"action": "a"}, self.tmpdir, run1)
        append_evidence({"action": "b"}, self.tmpdir, run2)
        self.assertEqual(len(load_evidence(run1, self.tmpdir)), 1)
        self.assertEqual(len(load_evidence(run2, self.tmpdir)), 1)
        self.assertEqual(load_evidence(run1, self.tmpdir)[0]["action"], "a")
        self.assertEqual(load_evidence(run2, self.tmpdir)[0]["action"], "b")


# ── Run index ────────────────────────────────────────────────────────────

class TestRunIndex(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_and_list(self):
        state = _make_state()
        update_run_index(state, self.tmpdir)
        runs = list_runs(self.tmpdir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, state.run_id)
        self.assertEqual(runs[0].workflow, "bootstrap")

    def test_update_existing_run(self):
        state = _make_state()
        update_run_index(state, self.tmpdir)
        # Update with new status
        state2 = _make_state(phase=Phase.BLOCKED, status="BLOCKED")
        update_run_index(state2, self.tmpdir)
        runs = list_runs(self.tmpdir)
        self.assertEqual(len(runs), 1)  # still one run
        self.assertEqual(runs[0].status, "BLOCKED")

    def test_multiple_runs(self):
        s1 = _make_state(run_id="RUN-20260825-000000-aaaaaa")
        s2 = _make_state(run_id="RUN-20260825-000000-bbbbbb")
        update_run_index(s1, self.tmpdir)
        update_run_index(s2, self.tmpdir)
        runs = list_runs(self.tmpdir)
        self.assertEqual(len(runs), 2)

    def test_list_runs_limit(self):
        for i in range(5):
            s = _make_state(run_id=f"RUN-20260825-00000{i}-abcdef")
            update_run_index(s, self.tmpdir)
        runs = list_runs(self.tmpdir, limit=3)
        self.assertEqual(len(runs), 3)

    def test_get_persisted_run(self):
        state = _make_state()
        update_run_index(state, self.tmpdir)
        found = get_persisted_run(state.run_id, self.tmpdir)
        self.assertIsNotNone(found)
        self.assertEqual(found.run_id, state.run_id)

    def test_get_nonexistent_run(self):
        found = get_persisted_run("RUN-20260825-000000-000000", self.tmpdir)
        self.assertIsNone(found)


# ── Full persistence roundtrip ───────────────────────────────────────────

class TestPersistRun(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_roundtrip(self):
        state = _make_state_with_tools()
        persist_run(state, self.tmpdir)

        # Verify state
        loaded = load_state(state.run_id, self.tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.run_id, state.run_id)
        self.assertEqual(len(loaded.tool_calls), 2)

        # Verify index
        runs = list_runs(self.tmpdir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, state.run_id)

    def test_validate_persisted_state(self):
        state = _make_state()
        persist_run(state, self.tmpdir)
        valid, reason = validate_persisted_state(state.run_id, self.tmpdir)
        self.assertTrue(valid)
        self.assertEqual(reason, "valid")

    def test_validate_corrupt_state(self):
        run_id = "RUN-20260825-000000-000000"
        run_dir = self.tmpdir / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text("corrupt")
        valid, reason = validate_persisted_state(run_id, self.tmpdir)
        self.assertFalse(valid)
        self.assertIn("corrupt", reason.lower())

    def test_validate_missing_state(self):
        valid, reason = validate_persisted_state("RUN-20260825-000000-000000", self.tmpdir)
        self.assertFalse(valid)
        self.assertIn("not found", reason)

    def test_validate_invalid_run_id(self):
        valid, reason = validate_persisted_state("bad-id", self.tmpdir)
        self.assertFalse(valid)

    def test_find_interrupted_runs(self):
        # Running state (not terminal)
        running = _make_state(
            run_id="RUN-20260825-000000-aaaaaa",
            phase=Phase.EXECUTING,
            status="",
        )
        persist_run(running, self.tmpdir)

        # Completed state
        done = _make_state(
            run_id="RUN-20260825-000000-bbbbbb",
            phase=Phase.COMPLETED,
            status="PASS",
        )
        persist_run(done, self.tmpdir)

        interrupted = find_interrupted_runs(self.tmpdir)
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0].run_id, running.run_id)


# ── Evidence auto-save via EvidenceLog ──────────────────────────────────

class TestEvidenceAutoSave(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.run_id = "RUN-20260825-174630-cfc871"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_auto_save_on_record(self):
        log = EvidenceLog(self.run_id, persist_dir=self.tmpdir)
        self.assertTrue(log.persist_enabled)
        log.record(action="test_event", detail="hello")
        # Evidence should be on disk
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "test_event")

    def test_multiple_entries_auto_saved(self):
        log = EvidenceLog(self.run_id, persist_dir=self.tmpdir)
        for i in range(5):
            log.record(action=f"event_{i}")
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 5)

    def test_no_persist_by_default(self):
        log = EvidenceLog(self.run_id)
        self.assertFalse(log.persist_enabled)
        log.record(action="test")
        entries = load_evidence(self.run_id, self.tmpdir)
        self.assertEqual(len(entries), 0)

    def test_persist_error_recorded(self):
        # Use invalid run_id to trigger persistence error
        log = EvidenceLog("bad-id", persist_dir=self.tmpdir)
        log.record(action="test")
        # Error should be recorded (not crash)
        self.assertIsNotNone(log.persist_error)

    def test_in_memory_still_works(self):
        log = EvidenceLog(self.run_id, persist_dir=self.tmpdir)
        log.record(action="a")
        log.record(action="b")
        # In-memory entries still available
        self.assertEqual(len(log.entries()), 2)


# ── Security ────────────────────────────────────────────────────────────

class TestPersistenceSecurity(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_path_traversal_in_run_id(self):
        result = load_state("../../../etc/passwd", self.tmpdir)
        self.assertIsNone(result)
        result = load_state("../../../../etc/shadow", self.tmpdir)
        self.assertIsNone(result)

    def test_run_id_with_special_chars(self):
        result = load_state("RUN-2026-08-25; rm -rf /", self.tmpdir)
        self.assertIsNone(result)

    def test_evidence_redaction_in_persistence(self):
        state = _make_state()
        state.tool_calls.append(ToolCall(
            tool_name="test",
            operation="run",
            error="api_key=secret123 is bad",
        ))
        save_state(state, self.tmpdir)
        loaded = load_state(state.run_id, self.tmpdir)
        # Error should be redacted in persisted state
        self.assertNotIn("secret123", loaded.tool_calls[0].error)


# ── Run directory structure ──────────────────────────────────────────────

class TestRunDirectoryStructure(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_expected_files(self):
        state = _make_state()
        persist_run(state, self.tmpdir)

        run_dir = self.tmpdir / "runs" / state.run_id
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertTrue((self.tmpdir / "runs" / "index.json").is_file())

    def test_multiple_runs_separate_dirs(self):
        s1 = _make_state(run_id="RUN-20260825-000000-aaaaaa")
        s2 = _make_state(run_id="RUN-20260825-000000-bbbbbb")
        persist_run(s1, self.tmpdir)
        persist_run(s2, self.tmpdir)

        dir1 = self.tmpdir / "runs" / s1.run_id
        dir2 = self.tmpdir / "runs" / s2.run_id
        self.assertTrue(dir1.is_dir())
        self.assertTrue(dir2.is_dir())
        self.assertNotEqual(dir1, dir2)


if __name__ == "__main__":
    unittest.main()
