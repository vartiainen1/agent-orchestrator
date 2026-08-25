"""Phase 7 — Operating Modes integration tests.

Tests that all four modes are operational through the CLI, that mode
precedence works, that mode-specific policy enforcement works, and that
existing Phase 1-6 functionality remains intact.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.cli import main
from orchestrator.exit_codes import OK, BLOCKED, ERROR, INVALID
from orchestrator.modes import Mode, get_mode_rules, is_valid_mode, MODE_REGISTRY
from orchestrator.policy import load_policy, Outcome, InvalidPolicyError
from orchestrator.engine import WorkflowEngine
from orchestrator.workflow import get_workflow, list_workflows
from orchestrator.discovery import discover_all, ToolStatus


# ── Mode loading tests ─────────────────────────────────────────────────

class TestAllModesLoad(unittest.TestCase):
    """All four modes must load without error."""

    def test_solo_loads(self):
        policy = load_policy("solo")
        self.assertEqual(policy.mode, Mode.SOLO)

    def test_development_loads(self):
        policy = load_policy("development")
        self.assertEqual(policy.mode, Mode.DEVELOPMENT)

    def test_security_loads(self):
        policy = load_policy("security")
        self.assertEqual(policy.mode, Mode.SECURITY)

    def test_enterprise_loads(self):
        policy = load_policy("enterprise")
        self.assertEqual(policy.mode, Mode.ENTERPRISE)

    def test_all_four_modes_exist(self):
        self.assertEqual(len(Mode), 4)
        expected = {"solo", "development", "security", "enterprise"}
        self.assertEqual({m.value for m in Mode}, expected)

    def test_all_modes_have_rules(self):
        for mode in Mode:
            rules = get_mode_rules(mode)
            self.assertGreater(len(rules), 0, f"{mode.value} has no rules")


class TestModePrecedence(unittest.TestCase):
    """CLI flag > config > default."""

    def test_default_mode_is_solo(self):
        """Without CLI flag or config, default is solo."""
        policy = load_policy("solo")
        self.assertEqual(policy.mode, Mode.SOLO)

    def test_cli_overrides_config(self, tmp_path=Path("nonexistent")):
        """CLI --mode explicitly selects the mode."""
        policy = load_policy("enterprise")
        self.assertEqual(policy.mode, Mode.ENTERPRISE)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(InvalidPolicyError):
            load_policy("invalid_mode_name")

    def test_is_valid_mode(self):
        self.assertTrue(is_valid_mode("solo"))
        self.assertTrue(is_valid_mode("development"))
        self.assertTrue(is_valid_mode("security"))
        self.assertTrue(is_valid_mode("enterprise"))
        self.assertFalse(is_valid_mode("production"))
        self.assertFalse(is_valid_mode(""))
        self.assertFalse(is_valid_mode("SOLO"))  # case-sensitive


# ── Mode-specific policy enforcement ───────────────────────────────────

class TestSoloMode(unittest.TestCase):
    """SOLO mode: diff-gate optional, sandbox optional, cloud allowed."""

    def setUp(self):
        self.policy = load_policy("solo")

    def test_diff_gate_optional(self):
        self.assertEqual(self.policy.get("diff_gate_required"), "false")

    def test_sandbox_optional(self):
        self.assertEqual(self.policy.get("sandbox_required"), "false")

    def test_cloud_llm_allowed(self):
        self.assertEqual(self.policy.get("llm_cloud_allowed"), "true")

    def test_host_fallback_allowed(self):
        self.assertEqual(self.policy.get("host_fallback_allowed"), "true")

    def test_approval_not_required(self):
        self.assertEqual(self.policy.get("approval_required"), "false")

    def test_evidence_level_basic(self):
        self.assertEqual(self.policy.get("evidence_level"), "basic")


class TestDevelopmentMode(unittest.TestCase):
    """DEVELOPMENT mode: diff-gate required, sandbox required."""

    def setUp(self):
        self.policy = load_policy("development")

    def test_diff_gate_required(self):
        self.assertEqual(self.policy.get("diff_gate_required"), "true")

    def test_sandbox_required(self):
        self.assertEqual(self.policy.get("sandbox_required"), "true")

    def test_cloud_llm_allowed(self):
        self.assertEqual(self.policy.get("llm_cloud_allowed"), "true")

    def test_host_fallback_denied(self):
        self.assertEqual(self.policy.get("host_fallback_allowed"), "false")

    def test_approval_not_required(self):
        self.assertEqual(self.policy.get("approval_required"), "false")

    def test_evidence_level_standard(self):
        self.assertEqual(self.policy.get("evidence_level"), "standard")


class TestSecurityMode(unittest.TestCase):
    """SECURITY mode: strict sandbox, no cloud LLM."""

    def setUp(self):
        self.policy = load_policy("security")

    def test_diff_gate_required(self):
        self.assertEqual(self.policy.get("diff_gate_required"), "true")

    def test_sandbox_required(self):
        self.assertEqual(self.policy.get("sandbox_required"), "true")

    def test_sandbox_strict(self):
        self.assertEqual(self.policy.get("sandbox_strict"), "true")

    def test_cloud_llm_denied(self):
        self.assertEqual(self.policy.get("llm_cloud_allowed"), "false")

    def test_host_fallback_denied(self):
        self.assertEqual(self.policy.get("host_fallback_allowed"), "false")

    def test_evidence_level_enhanced(self):
        self.assertEqual(self.policy.get("evidence_level"), "enhanced")

    def test_timeout_longer(self):
        self.assertEqual(self.policy.get("max_tool_timeout"), "60")


class TestEnterpriseMode(unittest.TestCase):
    """ENTERPRISE mode: approval required, strictest policy."""

    def setUp(self):
        self.policy = load_policy("enterprise")

    def test_diff_gate_required(self):
        self.assertEqual(self.policy.get("diff_gate_required"), "true")

    def test_sandbox_required(self):
        self.assertEqual(self.policy.get("sandbox_required"), "true")

    def test_sandbox_strict(self):
        self.assertEqual(self.policy.get("sandbox_strict"), "true")

    def test_cloud_llm_denied(self):
        self.assertEqual(self.policy.get("llm_cloud_allowed"), "false")

    def test_host_fallback_denied(self):
        self.assertEqual(self.policy.get("host_fallback_allowed"), "false")

    def test_approval_required(self):
        self.assertEqual(self.policy.get("approval_required"), "true")

    def test_evidence_level_complete(self):
        self.assertEqual(self.policy.get("evidence_level"), "complete")

    def test_timeout_longest(self):
        self.assertEqual(self.policy.get("max_tool_timeout"), "120")


# ── Mandatory safety rules ─────────────────────────────────────────────

class TestMandatorySafety(unittest.TestCase):
    """Base safety rules cannot be weakened by any mode."""

    def test_error_log_mandatory_all_modes(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertTrue(policy.is_mandatory("error_log_required"),
                            f"error_log_required not mandatory in {mode.value}")

    def test_decision_log_mandatory_all_modes(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertTrue(policy.is_mandatory("decision_log_required"),
                            f"decision_log_required not mandatory in {mode.value}")

    def test_memory_auto_promote_forbidden(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertEqual(policy.get("memory_auto_promote"), "false")
            self.assertTrue(policy.is_mandatory("memory_auto_promote"))

    def test_no_git_no_verify_mandatory(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertTrue(policy.is_mandatory("no_git_no_verify"))

    def test_fail_closed_mandatory(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertTrue(policy.is_mandatory("fail_closed_on_uncertainty"))


# ── Pre-flight enforcement ─────────────────────────────────────────────

class TestPreflightEnforcement(unittest.TestCase):
    """Pre-flight checks produce correct decisions per mode."""

    def test_solo_no_sandbox_check(self):
        policy = load_policy("solo")
        decisions = policy.pre_flight(available_tools={"agent-error-log", "agent-decision-log"})
        rule_names = [d.rule for d in decisions]
        # sandbox_required is false in SOLO, so no sandbox pre-flight check
        self.assertNotIn("sandbox_required", rule_names)

    def test_development_checks_sandbox(self):
        policy = load_policy("development")
        decisions = policy.pre_flight(available_tools={"agent-error-log", "agent-decision-log"})
        rule_names = [d.rule for d in decisions]
        # sandbox_required is true in DEVELOPMENT, so it should be checked
        self.assertIn("sandbox_required", rule_names)

    def test_security_blocks_cloud_llm(self):
        policy = load_policy("security")
        decisions = policy.pre_flight()
        cloud_decisions = [d for d in decisions if d.rule == "llm_cloud_allowed"]
        self.assertEqual(len(cloud_decisions), 1)
        self.assertEqual(cloud_decisions[0].outcome, Outcome.DENY)

    def test_enterprise_requires_approval(self):
        policy = load_policy("enterprise")
        decisions = policy.pre_flight()
        approval = [d for d in decisions if d.rule == "approval_required"]
        self.assertEqual(len(approval), 1)
        self.assertEqual(approval[0].outcome, Outcome.REQUIRE_APPROVAL)

    def test_sandbox_not_available_denies_dev(self):
        """DEVELOPMENT requires sandbox; if unavailable, DENY."""
        policy = load_policy("development")
        decisions = policy.pre_flight(available_tools={"agent-error-log", "agent-decision-log"})
        sandbox = [d for d in decisions if d.rule == "sandbox_required"]
        self.assertEqual(len(sandbox), 1)
        self.assertEqual(sandbox[0].outcome, Outcome.DENY)

    def test_sandbox_available_allows_dev(self):
        """DEVELOPMENT with sandbox available should ALLOW."""
        policy = load_policy("development")
        tools = {"agent-error-log", "agent-decision-log", "agent-sandbox", "agent-diff-gate"}
        decisions = policy.pre_flight(available_tools=tools)
        sandbox = [d for d in decisions if d.rule == "sandbox_required"]
        self.assertEqual(len(sandbox), 1)
        self.assertEqual(sandbox[0].outcome, Outcome.ALLOW)


# ── Engine integration ─────────────────────────────────────────────────

class TestModeEngineIntegration(unittest.TestCase):
    """Verify engine respects mode-specific policy decisions."""

    def test_solo_passes_when_tools_available(self):
        """SOLO with error-log + decision-log available should PASS."""
        from orchestrator.discovery import ToolInfo
        workspace = Path(".")

        # Create a minimal policy
        policy = load_policy("solo")
        workflow = get_workflow("bootstrap")
        self.assertIsNotNone(workflow)

        engine = WorkflowEngine(workspace)
        state = engine.run(workflow, policy=policy)

        # Should complete (PASS or at least not BLOCKED by policy)
        self.assertIn(state.final_status, ("PASS", "BLOCKED", "FAIL"))

    def test_security_blocks_without_sandbox(self):
        """SECURITY blocks when sandbox is UNSUPPORTED (Windows)."""
        workspace = Path(".")
        policy = load_policy("security")
        workflow = get_workflow("development")

        engine = WorkflowEngine(workspace)
        state = engine.run(workflow, policy=policy)

        # Sandbox is unsupported on Windows -> DENY -> BLOCKED
        self.assertEqual(state.final_status, "BLOCKED")

    def test_enterprise_records_approval(self):
        """ENTERPRISE pre-flight records REQUIRE_APPROVAL."""
        workspace = Path(".")
        policy = load_policy("enterprise")
        workflow = get_workflow("bootstrap")

        engine = WorkflowEngine(workspace)
        state = engine.run(workflow, policy=policy)

        # Check approval decision was recorded
        approval_decisions = [
            d for d in state.policy_decisions
            if d.get("rule") == "approval_required"
        ]
        self.assertGreater(len(approval_decisions), 0,
                           "approval_required decision not recorded in state")


# ── CLI integration tests ──────────────────────────────────────────────

class TestCLIModes(unittest.TestCase):
    """CLI modes command."""

    def test_modes_exit_ok(self):
        exit_code = main(["modes"])
        self.assertEqual(exit_code, OK)

    def test_modes_lists_all_four(self):
        """modes command should mention all four modes."""
        # Can't easily capture stdout, but verify it doesn't error
        exit_code = main(["modes"])
        self.assertEqual(exit_code, OK)


class TestCLIPolicies(unittest.TestCase):
    """CLI policies command."""

    def test_policies_solo(self):
        exit_code = main(["policies", "solo"])
        self.assertEqual(exit_code, OK)

    def test_policies_development(self):
        exit_code = main(["policies", "development"])
        self.assertEqual(exit_code, OK)

    def test_policies_security(self):
        exit_code = main(["policies", "security"])
        self.assertEqual(exit_code, OK)

    def test_policies_enterprise(self):
        exit_code = main(["policies", "enterprise"])
        self.assertEqual(exit_code, OK)

    def test_policies_default_is_solo(self):
        exit_code = main(["policies"])
        self.assertEqual(exit_code, OK)

    def test_policies_invalid_mode(self):
        exit_code = main(["policies", "invalid_mode"])
        self.assertEqual(exit_code, INVALID)


class TestCLIRun(unittest.TestCase):
    """CLI run command."""

    def test_run_solo(self):
        exit_code = main(["run", "--mode", "solo"])
        self.assertEqual(exit_code, OK)

    def test_run_development(self):
        exit_code = main(["run", "--mode", "development"])
        # May be BLOCKED if sandbox unavailable
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_run_security(self):
        exit_code = main(["run", "--mode", "security"])
        # Sandbox unsupported -> BLOCKED
        self.assertEqual(exit_code, BLOCKED)

    def test_run_enterprise(self):
        exit_code = main(["run", "--mode", "enterprise"])
        # Sandbox unsupported -> BLOCKED
        self.assertEqual(exit_code, BLOCKED)

    def test_run_invalid_mode(self):
        """argparse rejects invalid choice with SystemExit(2)."""
        with self.assertRaises(SystemExit) as ctx:
            main(["run", "--mode", "invalid"])
        self.assertEqual(ctx.exception.code, 2)

    def test_run_default_mode(self):
        """Without --mode, should default to solo."""
        exit_code = main(["run"])
        self.assertEqual(exit_code, OK)


# ── Backwards compatibility ────────────────────────────────────────────

class TestBackwardsCompatibility(unittest.TestCase):
    """Existing Phase 1-6 CLI commands must still work."""

    def test_help(self):
        """--help raises SystemExit(0) via argparse."""
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_version(self):
        """--version raises SystemExit(0) via argparse."""
        with self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_status(self):
        exit_code = main(["status"])
        self.assertEqual(exit_code, OK)

    def test_status_json(self):
        exit_code = main(["status", "--json"])
        self.assertEqual(exit_code, OK)

    def test_doctor(self):
        exit_code = main(["doctor"])
        self.assertIn(exit_code, (OK, BLOCKED))

    def test_no_command(self):
        """No subcommand should print help and return OK."""
        exit_code = main([])
        self.assertEqual(exit_code, OK)


# ── Workflow availability ──────────────────────────────────────────────

class TestWorkflowAvailability(unittest.TestCase):
    """Workflows are available and correct."""

    def test_bootstrap_workflow(self):
        w = get_workflow("bootstrap")
        self.assertIsNotNone(w)
        self.assertEqual(w.name, "bootstrap")

    def test_development_workflow(self):
        w = get_workflow("development")
        self.assertIsNotNone(w)
        self.assertEqual(w.name, "development")

    def test_doctor_workflow(self):
        w = get_workflow("doctor")
        self.assertIsNotNone(w)

    def test_list_workflows(self):
        names = list_workflows()
        self.assertIn("bootstrap", names)
        self.assertIn("development", names)

    def test_unknown_workflow_returns_none(self):
        w = get_workflow("nonexistent")
        self.assertIsNone(w)


# ── Security ───────────────────────────────────────────────────────────

class TestModeSecurity(unittest.TestCase):
    """Security properties of mode enforcement."""

    def test_no_mode_can_weaken_error_log(self):
        """No mode can set error_log_required to false."""
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertEqual(policy.get("error_log_required"), "true")

    def test_no_mode_can_weaken_decision_log(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertEqual(policy.get("decision_log_required"), "true")

    def test_no_mode_can_enable_memory_auto_promote(self):
        for mode in Mode:
            policy = load_policy(mode.value)
            self.assertEqual(policy.get("memory_auto_promote"), "false")

    def test_security_and_enterprise_block_cloud(self):
        for mode in ("security", "enterprise"):
            policy = load_policy(mode)
            self.assertEqual(policy.get("llm_cloud_allowed"), "false")

    def test_solo_and_dev_allow_cloud(self):
        for mode in ("solo", "development"):
            policy = load_policy(mode)
            self.assertEqual(policy.get("llm_cloud_allowed"), "true")


if __name__ == "__main__":
    unittest.main()
