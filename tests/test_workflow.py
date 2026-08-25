from orchestrator.workspace import find_workspace
"""Tests for orchestrator Phase 4 — workflow engine."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.state import (
    Phase,
    RunState,
    ToolCall,
    InvalidTransitionError,
    is_valid_transition,
)
from orchestrator.evidence import EvidenceLog, evidence_entry, redact
from orchestrator.workflow import (
    Branch,
    Step,
    StepOutcome,
    Workflow,
    bootstrap_workflow,
    development_workflow,
    doctor_workflow,
    get_workflow,
    list_workflows,
)
from orchestrator.engine import WorkflowEngine, _to_step_outcome
from orchestrator.report import format_report, report_dict, report_json, save_report
from orchestrator.adapter import ToolResult, ResultStatus


# ══════════════════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════════════════

class TestPhase(unittest.TestCase):
    """Phase enum."""

    def test_eleven_phases(self):
        self.assertEqual(len(Phase), 11)

    def test_terminal_phases(self):
        from orchestrator.state import TERMINAL_PHASES
        self.assertIn(Phase.COMPLETED, TERMINAL_PHASES)
        self.assertIn(Phase.CANCELLED, TERMINAL_PHASES)
        self.assertNotIn(Phase.EXECUTING, TERMINAL_PHASES)


class TestValidTransition(unittest.TestCase):
    """is_valid_transition."""

    def test_created_to_bootstrapping(self):
        self.assertTrue(is_valid_transition(Phase.CREATED, Phase.BOOTSTRAPPING))

    def test_created_to_executing_invalid(self):
        self.assertFalse(is_valid_transition(Phase.CREATED, Phase.EXECUTING))

    def test_completed_is_terminal(self):
        self.assertFalse(is_valid_transition(Phase.COMPLETED, Phase.EXECUTING))

    def test_blocked_can_retry(self):
        self.assertTrue(is_valid_transition(Phase.BLOCKED, Phase.EXECUTING))


class TestRunState(unittest.TestCase):
    """RunState dataclass."""

    def test_auto_run_id(self):
        s = RunState()
        self.assertTrue(s.run_id.startswith("RUN-"))

    def test_auto_timestamp(self):
        s = RunState()
        self.assertIn("2026", s.started_at)

    def test_valid_transition(self):
        s = RunState()
        self.assertEqual(s.phase, Phase.CREATED)
        s.transition(Phase.BOOTSTRAPPING)
        self.assertEqual(s.phase, Phase.BOOTSTRAPPING)

    def test_invalid_transition_raises(self):
        s = RunState()
        with self.assertRaises(InvalidTransitionError):
            s.transition(Phase.COMPLETED)  # can't jump to terminal

    def test_record_tool_call(self):
        s = RunState()
        call = ToolCall(tool_name="x", operation="test", status="PASS", exit_code=0)
        s.record_tool_call(call)
        self.assertEqual(len(s.tool_calls), 1)

    def test_observe(self):
        s = RunState()
        s.observe("something happened")
        self.assertEqual(len(s.observations), 1)
        self.assertIn("something happened", s.observations[0])

    def test_record_gate(self):
        s = RunState()
        s.record_gate("test_gate", passed=True, detail="ok")
        self.assertEqual(len(s.gate_results), 1)
        self.assertEqual(s.gate_results[0]["passed"], "True")

    def test_finalize(self):
        s = RunState()
        s.finalize("PASS")
        self.assertEqual(s.final_status, "PASS")
        self.assertTrue(len(s.ended_at) > 0)

    def test_is_terminal(self):
        s = RunState()
        self.assertFalse(s.is_terminal())
        # Must go through valid transition chain
        s.transition(Phase.BOOTSTRAPPING)
        s.transition(Phase.CHECKING)
        s.transition(Phase.EXECUTING)
        s.transition(Phase.COMPLETED)
        self.assertTrue(s.is_terminal())


# ══════════════════════════════════════════════════════════════════════════
#  EVIDENCE
# ══════════════════════════════════════════════════════════════════════════

class TestRedact(unittest.TestCase):
    """redact() removes secret patterns."""

    def test_api_key(self):
        self.assertIn("[REDACTED]", redact("api_key=secret123abc"))

    def test_token(self):
        self.assertIn("[REDACTED]", redact("token=xyz789"))

    def test_bearer(self):
        self.assertIn("[REDACTED]", redact("Bearer sk-abc123def456"))

    def test_clean_text(self):
        self.assertEqual(redact("hello world"), "hello world")

    def test_password(self):
        self.assertIn("[REDACTED]", redact("password=hunter2"))


class TestEvidenceEntry(unittest.TestCase):
    """evidence_entry creates properly structured entries."""

    def test_basic_entry(self):
        e = evidence_entry(run_id="R1", action="test")
        self.assertEqual(e["run_id"], "R1")
        self.assertEqual(e["action"], "test")
        self.assertIn("timestamp", e)

    def test_redacts_args(self):
        e = evidence_entry(run_id="R1", action="test", args=["api_key=secret"])
        self.assertIn("[REDACTED]", e["args"][0])

    def test_redacts_detail(self):
        e = evidence_entry(run_id="R1", action="test", detail="token=abc")
        self.assertIn("[REDACTED]", e["detail"])


class TestEvidenceLog(unittest.TestCase):
    """EvidenceLog append-only log."""

    def test_record_and_retrieve(self):
        log = EvidenceLog("R1")
        log.record(action="a1")
        log.record(action="a2")
        self.assertEqual(len(log), 2)

    def test_to_json(self):
        log = EvidenceLog("R1")
        log.record(action="test")
        j = log.to_json()
        data = json.loads(j)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "test")

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = EvidenceLog("R1")
            log.record(action="test")
            log.save(Path(tmp) / "evidence.json")
            content = (Path(tmp) / "evidence.json").read_text()
            data = json.loads(content)
            self.assertEqual(len(data), 1)


# ══════════════════════════════════════════════════════════════════════════
#  WORKFLOW
# ══════════════════════════════════════════════════════════════════════════

class TestStep(unittest.TestCase):
    """Step dataclass."""

    def test_defaults(self):
        s = Step(name="x", tool="t", operation="o")
        self.assertTrue(s.required)
        self.assertFalse(s.gate)
        self.assertEqual(s.args, [])

    def test_gate_step(self):
        s = Step(name="x", tool="t", operation="o", gate=True)
        self.assertTrue(s.gate)


class TestWorkflow(unittest.TestCase):
    """Workflow definition."""

    def test_step_by_name(self):
        w = Workflow(name="test", steps=[
            Step(name="a", tool="t", operation="o"),
            Step(name="b", tool="t", operation="o"),
        ])
        self.assertIsNotNone(w.step_by_name("a"))
        self.assertIsNone(w.step_by_name("z"))

    def test_step_index(self):
        w = Workflow(name="test", steps=[
            Step(name="a", tool="t", operation="o"),
            Step(name="b", tool="t", operation="o"),
        ])
        self.assertEqual(w.step_index("a"), 0)
        self.assertEqual(w.step_index("b"), 1)
        self.assertEqual(w.step_index("z"), -1)

    def test_next_branch(self):
        w = Workflow(name="test", steps=[
            Step(name="a", tool="t", operation="o"),
        ], branches={
            "a": [Branch(on_status=StepOutcome.FAIL, goto="BLOCK")],
        })
        self.assertEqual(w.next_branch("a", StepOutcome.FAIL), "BLOCK")
        self.assertIsNone(w.next_branch("a", StepOutcome.PASS))


class TestPredefinedWorkflows(unittest.TestCase):
    """Predefined workflow factories."""

    def test_bootstrap(self):
        w = bootstrap_workflow()
        self.assertEqual(w.name, "bootstrap")
        self.assertEqual(len(w.steps), 2)

    def test_development(self):
        w = development_workflow()
        self.assertEqual(w.name, "development")
        self.assertGreaterEqual(len(w.steps), 3)

    def test_doctor(self):
        w = doctor_workflow()
        self.assertEqual(w.name, "doctor")

    def test_get_workflow(self):
        self.assertIsNotNone(get_workflow("bootstrap"))
        self.assertIsNone(get_workflow("nonexistent"))

    def test_list_workflows(self):
        names = list_workflows()
        self.assertIn("bootstrap", names)
        self.assertIn("development", names)


# ══════════════════════════════════════════════════════════════════════════
#  ENGINE
# ══════════════════════════════════════════════════════════════════════════

class TestToStepOutcome(unittest.TestCase):
    """_to_step_outcome mapping."""

    def test_pass(self):
        r = ToolResult(tool_name="x", operation="o", status=ResultStatus.PASS, exit_code=0)
        self.assertEqual(_to_step_outcome(r), StepOutcome.PASS)

    def test_fail(self):
        r = ToolResult(tool_name="x", operation="o", status=ResultStatus.FAIL, exit_code=1)
        self.assertEqual(_to_step_outcome(r), StepOutcome.FAIL)

    def test_blocked(self):
        r = ToolResult(tool_name="x", operation="o", status=ResultStatus.BLOCKED, exit_code=1)
        self.assertEqual(_to_step_outcome(r), StepOutcome.BLOCKED)

    def test_unsupported(self):
        r = ToolResult(tool_name="x", operation="o", status=ResultStatus.UNSUPPORTED, exit_code=-1)
        self.assertEqual(_to_step_outcome(r), StepOutcome.UNSUPPORTED)


class TestWorkflowEngine(unittest.TestCase):
    """WorkflowEngine execution."""

    def setUp(self):
        self.ws = find_workspace(Path(__file__).resolve().parent)
        if self.ws is None:
            self.skipTest("workspace not found")

    def test_engine_runs_bootstrap(self):
        """Integration: bootstrap workflow against real tools."""
        engine = WorkflowEngine(self.ws)
        w = bootstrap_workflow()
        state = engine.run(w)
        # Should complete or block (depending on tool availability)
        self.assertIn(state.final_status, ("PASS", "BLOCKED", "FAIL"))
        self.assertTrue(state.is_terminal() or state.phase == Phase.BLOCKED)
        self.assertGreater(len(state.tool_calls), 0)

    def test_engine_records_evidence(self):
        """Engine records tool calls in state."""
        engine = WorkflowEngine(self.ws)
        w = bootstrap_workflow()
        state = engine.run(w)
        self.assertGreater(len(state.tool_calls), 0)
        for call in state.tool_calls:
            self.assertIn(call.status, ("PASS", "FAIL", "BLOCKED", "UNSUPPORTED", "ERROR"))

    def test_engine_blocks_on_gate_failure(self):
        """Gate step failure blocks the workflow."""
        engine = WorkflowEngine(self.ws)
        # Create a workflow with a gate that will fail
        w = Workflow(name="test_gate", steps=[
            Step(name="fail_gate", tool="nonexistent-tool", operation="check",
                 gate=True, required=True),
        ])
        state = engine.run(w)
        self.assertEqual(state.final_status, "BLOCKED")

    def test_engine_stops_on_required_failure(self):
        """Required step failure stops the workflow."""
        engine = WorkflowEngine(self.ws)
        w = Workflow(name="test_required", steps=[
            Step(name="fail_required", tool="nonexistent-tool", operation="check",
                 required=True, gate=False),
        ])
        state = engine.run(w)
        self.assertEqual(state.final_status, "FAIL")

    def test_engine_skips_optional_failure(self):
        """Optional step failure does not stop the workflow."""
        engine = WorkflowEngine(self.ws)
        w = Workflow(name="test_optional", steps=[
            Step(name="fail_optional", tool="nonexistent-tool", operation="check",
                 required=False, gate=False),
            Step(name="second", tool="agent-error-log", operation="check",
                 required=False, gate=False),
        ])
        state = engine.run(w)
        # Should not FAIL just because optional step failed
        self.assertNotEqual(state.final_status, "FAIL")

    def test_engine_branch_to_block(self):
        """Branch on FAIL → BLOCK stops the workflow."""
        engine = WorkflowEngine(self.ws)
        w = Workflow(name="test_branch", steps=[
            Step(name="step_a", tool="nonexistent-tool", operation="check"),
        ], branches={
            "step_a": [Branch(on_status=StepOutcome.FAIL, goto="BLOCK")],
        })
        state = engine.run(w)
        self.assertEqual(state.final_status, "BLOCKED")

    def test_engine_no_shell_true(self):
        """Engine never uses shell=True."""
        import ast, inspect
        source = inspect.getsource(WorkflowEngine)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("engine uses shell=True")


class TestEngineIntegration(unittest.TestCase):
    """Integration tests against real tools."""

    def setUp(self):
        self.ws = find_workspace(Path(__file__).resolve().parent)
        if self.ws is None:
            self.skipTest("workspace not found")

    def test_doctor_workflow(self):
        """Doctor workflow runs all health checks."""
        engine = WorkflowEngine(self.ws)
        w = doctor_workflow()
        state = engine.run(w)
        # At least some tools should be checked
        self.assertGreater(len(state.tool_calls), 0)
        self.assertIn(state.final_status, ("PASS", "BLOCKED", "FAIL"))

    def test_development_workflow(self):
        """Development workflow runs bootstrap + checks."""
        engine = WorkflowEngine(self.ws)
        w = development_workflow()
        state = engine.run(w)
        self.assertGreater(len(state.tool_calls), 0)


# ══════════════════════════════════════════════════════════════════════════
#  REPORT
# ══════════════════════════════════════════════════════════════════════════

class TestReport(unittest.TestCase):
    """Report generation."""

    def test_format_report(self):
        state = RunState(workflow_name="test", project_dir="/p", workspace_dir="/w")
        state.finalize("PASS")
        report = format_report(state)
        self.assertIn("test", report)
        self.assertIn("PASS", report)
        self.assertIn("ORCHESTRATION REPORT", report)

    def test_report_dict(self):
        state = RunState(workflow_name="test")
        d = report_dict(state)
        self.assertEqual(d["workflow"], "test")
        self.assertIn("tool_calls", d)
        self.assertIn("gate_results", d)

    def test_report_json(self):
        state = RunState(workflow_name="test")
        j = report_json(state)
        data = json.loads(j)
        self.assertEqual(data["workflow"], "test")

    def test_save_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = RunState(workflow_name="test")
            state.finalize("PASS")
            save_report(state, Path(tmp) / "report")
            self.assertTrue((Path(tmp) / "report.md").is_file())
            self.assertTrue((Path(tmp) / "report.json").is_file())

    def test_report_redacts_secrets(self):
        state = RunState(workflow_name="test")
        state.record_tool_call(ToolCall(
            tool_name="x", operation="o", status="PASS", exit_code=0,
            error="api_key=secret123",
        ))
        report = format_report(state)
        self.assertNotIn("secret123", report)
        self.assertIn("[REDACTED]", report)


class TestEndToEndWorkflow(unittest.TestCase):
    """End-to-end: run a workflow and produce a report."""

    def setUp(self):
        self.ws = find_workspace(Path(__file__).resolve().parent)
        if self.ws is None:
            self.skipTest("workspace not found")

    def test_full_cycle(self):
        """Run doctor workflow, generate report, verify completeness."""
        engine = WorkflowEngine(self.ws)
        w = doctor_workflow()
        state = engine.run(w)

        # Generate reports
        report_text = format_report(state)
        report_data = report_dict(state)

        # Verify report content
        self.assertIn(state.run_id, report_text)
        self.assertIn("doctor", report_text)
        self.assertGreater(len(state.tool_calls), 0)

        # Verify JSON report
        self.assertEqual(report_data["workflow"], "doctor")
        self.assertEqual(report_data["run_id"], state.run_id)
        self.assertGreater(len(report_data["tool_calls"]), 0)

        # Verify evidence is preserved
        for call in state.tool_calls:
            self.assertTrue(call.stdout or call.stderr or call.error or call.status == "PASS")


if __name__ == "__main__":
    unittest.main()
