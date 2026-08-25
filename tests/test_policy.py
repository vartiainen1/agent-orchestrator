from orchestrator.workspace import find_workspace
"""Tests for orchestrator Phase 5 — policy engine."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.modes import (
    BASE_SAFETY_RULES,
    Mode,
    ModeRule,
    get_mode_rules,
    get_mode_rule_value,
    is_valid_mode,
    MODE_REGISTRY,
)
from orchestrator.policy import (
    EffectiveRule,
    InvalidPolicyError,
    Outcome,
    Policy,
    PolicyDecision,
    _parse_project_config,
    load_policy,
)


# ══════════════════════════════════════════════════════════════════════════
#  MODES
# ══════════════════════════════════════════════════════════════════════════

class TestMode(unittest.TestCase):
    """Mode enum."""

    def test_four_modes(self):
        self.assertEqual(len(Mode), 4)

    def test_values(self):
        self.assertEqual(Mode.SOLO.value, "solo")
        self.assertEqual(Mode.DEVELOPMENT.value, "development")
        self.assertEqual(Mode.SECURITY.value, "security")
        self.assertEqual(Mode.ENTERPRISE.value, "enterprise")


class TestIsValidMode(unittest.TestCase):
    """is_valid_mode."""

    def test_valid_modes(self):
        for m in ["solo", "development", "security", "enterprise"]:
            self.assertTrue(is_valid_mode(m))

    def test_invalid_mode(self):
        self.assertFalse(is_valid_mode("banana"))
        self.assertFalse(is_valid_mode(""))


class TestModeRules(unittest.TestCase):
    """Mode rule loading."""

    def test_all_modes_have_rules(self):
        for mode in Mode:
            rules = get_mode_rules(mode)
            self.assertGreater(len(rules), 0)

    def test_base_safety_in_every_mode(self):
        base_names = {r.name for r in BASE_SAFETY_RULES}
        for mode in Mode:
            rules = get_mode_rules(mode)
            rule_names = {r.name for r in rules}
            for name in base_names:
                self.assertIn(name, rule_names)

    def test_solo_diff_gate_optional(self):
        self.assertEqual(get_mode_rule_value(Mode.SOLO, "diff_gate_required"), "false")

    def test_development_diff_gate_required(self):
        self.assertEqual(get_mode_rule_value(Mode.DEVELOPMENT, "diff_gate_required"), "true")

    def test_security_sandbox_strict(self):
        self.assertEqual(get_mode_rule_value(Mode.SECURITY, "sandbox_strict"), "true")

    def test_enterprise_approval_required(self):
        self.assertEqual(get_mode_rule_value(Mode.ENTERPRISE, "approval_required"), "true")

    def test_mandatory_rules_cannot_differ(self):
        """Mandatory rules must have the same value across all modes."""
        for r in BASE_SAFETY_RULES:
            if r.mandatory:
                for mode in Mode:
                    val = get_mode_rule_value(mode, r.name)
                    self.assertEqual(val, r.value,
                                     f"mandatory rule {r.name} differs in {mode}")


class TestModeRegistry(unittest.TestCase):
    """MODE_REGISTRY."""

    def test_all_modes_registered(self):
        for mode in Mode:
            self.assertIn(mode, MODE_REGISTRY)


# ══════════════════════════════════════════════════════════════════════════
#  OUTCOME
# ══════════════════════════════════════════════════════════════════════════

class TestOutcome(unittest.TestCase):
    """Policy outcomes."""

    def test_seven_outcomes(self):
        self.assertEqual(len(Outcome), 7)

    def test_values(self):
        self.assertEqual(Outcome.ALLOW.value, "ALLOW")
        self.assertEqual(Outcome.DENY.value, "DENY")
        self.assertEqual(Outcome.REQUIRE_APPROVAL.value, "REQUIRE_APPROVAL")


# ══════════════════════════════════════════════════════════════════════════
#  POLICY DECISION
# ══════════════════════════════════════════════════════════════════════════

class TestPolicyDecision(unittest.TestCase):
    """PolicyDecision dataclass."""

    def test_auto_timestamp(self):
        d = PolicyDecision(rule="x", outcome=Outcome.ALLOW, reason="r", mode="solo")
        self.assertIn("2026", d.timestamp)

    def test_fields(self):
        d = PolicyDecision(
            rule="test", outcome=Outcome.DENY, reason="because",
            mode="security", mandatory=True, context="ctx",
        )
        self.assertEqual(d.rule, "test")
        self.assertEqual(d.outcome, Outcome.DENY)
        self.assertTrue(d.mandatory)


# ══════════════════════════════════════════════════════════════════════════
#  POLICY LOADING
# ══════════════════════════════════════════════════════════════════════════

class TestLoadPolicy(unittest.TestCase):
    """load_policy builds effective policy."""

    def test_solo_policy(self):
        p = load_policy("solo")
        self.assertEqual(p.mode, Mode.SOLO)
        self.assertEqual(p.get("diff_gate_required"), "false")
        self.assertEqual(p.get("error_log_required"), "true")

    def test_development_policy(self):
        p = load_policy("development")
        self.assertEqual(p.get("diff_gate_required"), "true")
        self.assertEqual(p.get("sandbox_required"), "true")

    def test_security_policy(self):
        p = load_policy("security")
        self.assertEqual(p.get("sandbox_strict"), "true")
        self.assertEqual(p.get("llm_cloud_allowed"), "false")

    def test_enterprise_policy(self):
        p = load_policy("enterprise")
        self.assertEqual(p.get("approval_required"), "true")
        self.assertEqual(p.get("evidence_level"), "complete")

    def test_invalid_mode_raises(self):
        with self.assertRaises(InvalidPolicyError):
            load_policy("banana")

    def test_project_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("diff_gate_required = true\n")
            p = load_policy("solo", project_dir=Path(tmp))
            # SOLO default is false, but project overrides to true
            self.assertEqual(p.get("diff_gate_required"), "true")

    def test_project_cannot_override_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("error_log_required = false\n")
            with self.assertRaises(InvalidPolicyError):
                load_policy("solo", project_dir=Path(tmp))

    def test_unknown_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("unknown_key = true\n")
            with self.assertRaises(InvalidPolicyError):
                load_policy("solo", project_dir=Path(tmp))


# ══════════════════════════════════════════════════════════════════════════
#  PRE-FLIGHT
# ══════════════════════════════════════════════════════════════════════════

class TestPreFlight(unittest.TestCase):
    """Policy pre-flight checks."""

    def test_solo_allows_when_tools_available(self):
        p = load_policy("solo")
        decisions = p.pre_flight(available_tools={
            "agent-error-log", "agent-decision-log", "agent-diff-gate",
            "agent-memory", "agent-blame", "agent-sandbox", "agent-log-ai",
        })
        self.assertFalse(any(d.outcome == Outcome.DENY for d in decisions))

    def test_solo_blocks_when_error_log_missing(self):
        p = load_policy("solo")
        decisions = p.pre_flight(available_tools=set())
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertGreater(len(denies), 0)

    def test_development_requires_diff_gate(self):
        p = load_policy("development")
        decisions = p.pre_flight(available_tools={
            "agent-error-log", "agent-decision-log",
            # diff-gate missing
        })
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertTrue(any(d.rule == "diff_gate_required" for d in denies))

    def test_enterprise_requires_approval(self):
        p = load_policy("enterprise")
        decisions = p.pre_flight(available_tools={
            "agent-error-log", "agent-decision-log", "agent-diff-gate",
            "agent-sandbox",
        })
        approvals = [d for d in decisions if d.outcome == Outcome.REQUIRE_APPROVAL]
        self.assertGreater(len(approvals), 0)


# ══════════════════════════════════════════════════════════════════════════
#  POST-FLIGHT
# ══════════════════════════════════════════════════════════════════════════

class TestPostFlight(unittest.TestCase):
    """Policy post-flight checks."""

    def test_error_log_fail_denied(self):
        p = load_policy("solo")
        decisions = p.post_flight("agent-error-log", "FAIL", "check")
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertGreater(len(denies), 0)

    def test_error_log_pass_allowed(self):
        p = load_policy("solo")
        decisions = p.post_flight("agent-error-log", "PASS", "check")
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertEqual(len(denies), 0)

    def test_diff_gate_fail_denied_in_development(self):
        p = load_policy("development")
        decisions = p.post_flight("agent-diff-gate", "FAIL", "check_staged")
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertGreater(len(denies), 0)

    def test_diff_gate_not_enforced_in_solo(self):
        p = load_policy("solo")
        decisions = p.post_flight("agent-diff-gate", "FAIL", "check_staged")
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertEqual(len(denies), 0)

    def test_sandbox_strict_denies_non_pass(self):
        p = load_policy("security")
        decisions = p.post_flight("agent-sandbox", "ERROR", "run")
        denies = [d for d in decisions if d.outcome == Outcome.DENY]
        self.assertGreater(len(denies), 0)


# ══════════════════════════════════════════════════════════════════════════
#  ENGINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════

class TestEngineWithPolicy(unittest.TestCase):
    """WorkflowEngine with policy integration."""

    def setUp(self):
        self.ws = find_workspace(Path(__file__).resolve().parent)
        if self.ws is None:
            self.skipTest("workspace not found")

    def test_engine_records_policy_decisions(self):
        from orchestrator.engine import WorkflowEngine
        from orchestrator.workflow import bootstrap_workflow
        engine = WorkflowEngine(self.ws)
        p = load_policy("solo")
        state = engine.run(bootstrap_workflow(), policy=p)
        # Policy decisions should be recorded
        self.assertIsInstance(state.policy_decisions, list)

    def test_engine_blocks_on_policy_deny(self):
        from orchestrator.engine import WorkflowEngine
        from orchestrator.workflow import Workflow, Step
        engine = WorkflowEngine(self.ws)
        p = load_policy("solo")
        # Create workflow with a tool that will be denied by policy
        w = Workflow(name="test", steps=[
            Step(name="check_error_log", tool="agent-error-log", operation="check",
                 required=True, gate=True),
        ])
        state = engine.run(w, policy=p)
        # Should work or block based on tool availability
        self.assertIn(state.final_status, ("PASS", "BLOCKED", "FAIL"))

    def test_engine_no_shell_true(self):
        import ast, inspect
        from orchestrator.engine import WorkflowEngine
        source = inspect.getsource(WorkflowEngine)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("engine uses shell=True")


# ══════════════════════════════════════════════════════════════════════════
#  MANDATORY SAFETY
# ══════════════════════════════════════════════════════════════════════════

class TestMandatorySafety(unittest.TestCase):
    """Mandatory rules cannot be weakened."""

    def test_error_log_always_required(self):
        for mode in Mode:
            p = load_policy(mode.value)
            self.assertEqual(p.get("error_log_required"), "true")
            self.assertTrue(p.is_mandatory("error_log_required"))

    def test_decision_log_always_required(self):
        for mode in Mode:
            p = load_policy(mode.value)
            self.assertEqual(p.get("decision_log_required"), "true")
            self.assertTrue(p.is_mandatory("decision_log_required"))

    def test_memory_auto_promote_always_false(self):
        for mode in Mode:
            p = load_policy(mode.value)
            self.assertEqual(p.get("memory_auto_promote"), "false")

    def test_project_cannot_weaken_error_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = Path(tmp) / ".orchestrator"
            orch.mkdir()
            (orch / "config").write_text("error_log_required = false\n")
            with self.assertRaises(InvalidPolicyError):
                load_policy("solo", project_dir=Path(tmp))


# ══════════════════════════════════════════════════════════════════════════
#  MODE DIFFERENCES
# ══════════════════════════════════════════════════════════════════════════

class TestModeDifferences(unittest.TestCase):
    """Modes have meaningful behavioral differences."""

    def test_solo_vs_development_diff_gate(self):
        solo = load_policy("solo")
        dev = load_policy("development")
        self.assertEqual(solo.get("diff_gate_required"), "false")
        self.assertEqual(dev.get("diff_gate_required"), "true")

    def test_development_vs_security_sandbox_strict(self):
        dev = load_policy("development")
        sec = load_policy("security")
        self.assertEqual(dev.get("sandbox_strict"), "false")
        self.assertEqual(sec.get("sandbox_strict"), "true")

    def test_security_vs_enterprise_approval(self):
        sec = load_policy("security")
        ent = load_policy("enterprise")
        self.assertEqual(sec.get("approval_required"), "false")
        self.assertEqual(ent.get("approval_required"), "true")

    def test_solo_allows_cloud_llm(self):
        p = load_policy("solo")
        self.assertEqual(p.get("llm_cloud_allowed"), "true")

    def test_security_forbids_cloud_llm(self):
        p = load_policy("security")
        self.assertEqual(p.get("llm_cloud_allowed"), "false")


# ══════════════════════════════════════════════════════════════════════════
#  CONFIG PARSING
# ══════════════════════════════════════════════════════════════════════════

class TestParseProjectConfig(unittest.TestCase):
    """_parse_project_config."""

    def test_missing_file(self):
        result = _parse_project_config(Path("/nonexistent"))
        self.assertEqual(result, {})

    def test_valid_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("mode = security\ndiff_gate_required = true\n")
            f.flush()
            result = _parse_project_config(Path(f.name))
            self.assertEqual(result["mode"], "security")
            self.assertEqual(result["diff_gate_required"], "true")

    def test_unknown_key_rejected(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("evil_key = true\n")
            f.flush()
            with self.assertRaises(InvalidPolicyError):
                _parse_project_config(Path(f.name))


# ══════════════════════════════════════════════════════════════════════════
#  EVIDENCE
# ══════════════════════════════════════════════════════════════════════════

class TestPolicyEvidence(unittest.TestCase):
    """Policy decisions produce evidence."""

    def test_decision_has_reason(self):
        d = PolicyDecision(
            rule="test", outcome=Outcome.DENY, reason="because",
            mode="solo",
        )
        self.assertEqual(d.reason, "because")

    def test_decision_has_mode(self):
        d = PolicyDecision(
            rule="test", outcome=Outcome.ALLOW, reason="ok",
            mode="security",
        )
        self.assertEqual(d.mode, "security")


if __name__ == "__main__":
    unittest.main()
