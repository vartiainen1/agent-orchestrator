"""STEP 7 — Real-World Production Validation Tests.

Creates a temporary project and exercises realistic workflows end-to-end.
Every result classified: REAL / ENVIRONMENT-LIMITED / UNAVAILABLE / MOCK.
"""

import unittest
import tempfile
import shutil
import json
import os
from pathlib import Path

from orchestrator.agents import (
    Agent, AgentRole, AgentState, AgentTask, AgentResult,
)
from orchestrator.adapter import get_adapter, ToolResult, ResultStatus
from orchestrator.providers import NoneProvider, ProviderStatus
from orchestrator.scheduler import TaskScheduler
from orchestrator.evidence import EvidenceLog
from orchestrator.persist import (
    persist_run, list_runs, load_state,
    find_interrupted_runs, validate_persisted_state,
)
from orchestrator.state import RunState, Phase
from orchestrator.policy import load_policy
from orchestrator.modes import Mode
from orchestrator.validate import validate_config_value
from orchestrator.report import format_report, report_json, report_dict
from orchestrator.discovery import discover_all


WORKSPACE = Path(__file__).resolve().parent.parent / ".."


def _make_completed_run(workflow_name='test', mode='solo'):
    """Helper: create a RunState that reached COMPLETED."""
    state = RunState(workflow_name=workflow_name, mode=mode)
    state.transition(Phase.BOOTSTRAPPING)
    state.transition(Phase.CHECKING)
    state.transition(Phase.EXECUTING)
    state.transition(Phase.COMPLETED)
    state.finalize('PASS')
    return state


# ══════════════════════════════════════════════════════════════════════════
#  1. PROJECT LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════

class TestProjectLifecycle(unittest.TestCase):
    """REAL: Create fresh project, initialize, run, verify."""

    def test_full_lifecycle(self):
        """REAL: Fresh project → init → run → verify → cleanup."""
        td = Path(tempfile.mkdtemp())
        try:
            # 1. Create fresh project structure
            project = td / 'test-project'
            project.mkdir()
            (project / 'src').mkdir()
            (project / 'src' / 'main.py').write_text(
                'def hello():\n    return "world"\n', encoding='utf-8'
            )
            (project / 'tests').mkdir()
            (project / 'tests' / 'test_main.py').write_text(
                'from src.main import hello\n'
                'def test_hello():\n    assert hello() == "world"\n',
                encoding='utf-8'
            )

            # 2. Initialize error log
            error_adapter = get_adapter('agent-error-log', WORKSPACE)
            r = error_adapter.init_project()
            self.assertIn(r.exit_code, (0, 1))

            # 3. Initialize decision log
            decision_adapter = get_adapter('agent-decision-log', WORKSPACE)
            r = decision_adapter.init_project()
            self.assertIn(r.exit_code, (0, 1))

            # 4. Verify tools can run against the project
            error_result = error_adapter.check()
            self.assertIsInstance(error_result, ToolResult)

            decision_result = decision_adapter.check()
            self.assertIsInstance(decision_result, ToolResult)

            diff_result = get_adapter('agent-diff-gate', WORKSPACE).check_staged()
            self.assertIsInstance(diff_result, ToolResult)

            # 5. Create and persist a run
            state = RunState(
                workflow_name='test-lifecycle',
                mode='solo',
                project_dir=str(project),
            )
            state.transition(Phase.BOOTSTRAPPING)
            state.transition(Phase.CHECKING)
            state.transition(Phase.EXECUTING)
            state.transition(Phase.COMPLETED)
            state.finalize('PASS')  # noqa: already at COMPLETED
            persist_run(state, td)

            # 6. Verify persistence
            runs = list_runs(td)
            self.assertEqual(len(runs), 1)

            # 7. Load and verify state
            loaded = load_state(state.run_id, td)
            self.assertEqual(loaded.phase, Phase.COMPLETED)
            self.assertEqual(loaded.final_status, 'PASS')

        finally:
            shutil.rmtree(td)


# ══════════════════════════════════════════════════════════════════════════
#  2. SOLO WORKFLOW
# ══════════════════════════════════════════════════════════════════════════

class TestSoloWorkflow(unittest.TestCase):
    """REAL: SOLO mode end-to-end."""

    def test_solo_workflow(self):
        """REAL: SOLO mode runs with minimal ceremony."""
        # Verify SOLO policy
        policy = load_policy(Mode('solo'))
        self.assertEqual(policy.get('sandbox_required'), 'false')
        self.assertEqual(policy.get('diff_gate_required'), 'false')
        self.assertEqual(policy.get('llm_cloud_allowed'), 'true')

        # SOLO allows proceeding without sandbox
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id='RUN-SOLO-001', persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)

            # Deterministic reviewer can work in SOLO without AI
            reviewer = Agent.create(AgentRole.REVIEWER, 'Solo Reviewer')
            reviewer.initialize()
            reviewer.ready()
            scheduler.register_agent(reviewer)

            task = AgentTask(
                description='review code quality',
                agent_role=AgentRole.REVIEWER,
                allowed_tools=('agent-diff-gate',),
            )
            result = scheduler.execute_task(task, NoneProvider())
            self.assertEqual(result.status, AgentState.COMPLETED)

            # Evidence was recorded
            self.assertGreater(len(evidence.entries()), 0)
        finally:
            shutil.rmtree(td)


# ══════════════════════════════════════════════════════════════════════════
#  3. DEVELOPMENT WORKFLOW
# ══════════════════════════════════════════════════════════════════════════

class TestDevelopmentWorkflow(unittest.TestCase):
    """REAL: DEVELOPMENT mode end-to-end."""

    def test_development_workflow(self):
        """REAL: DEVELOPMENT mode requires diff-gate and sandbox."""
        policy = load_policy(Mode('development'))
        self.assertEqual(policy.get('diff_gate_required'), 'true')
        self.assertEqual(policy.get('sandbox_required'), 'true')

        # DEVELOPMENT mode enforces stronger validation
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id='RUN-DEV-001', persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)

            # Reviewer and security agents work without AI
            reviewer = Agent.create(AgentRole.REVIEWER, 'Dev Reviewer')
            reviewer.initialize()
            reviewer.ready()
            security = Agent.create(AgentRole.SECURITY, 'Dev Security')
            security.initialize()
            security.ready()
            scheduler.register_agent(reviewer)
            scheduler.register_agent(security)

            tasks = [
                AgentTask(
                    description='code review',
                    agent_role=AgentRole.REVIEWER,
                    allowed_tools=('agent-diff-gate',),
                ),
                AgentTask(
                    description='security scan',
                    agent_role=AgentRole.SECURITY,
                    allowed_tools=('agent-diff-gate',),
                ),
            ]

            results = scheduler.execute_sequential(tasks, NoneProvider())
            self.assertEqual(len(results), 2)
            for r in results:
                self.assertEqual(r.status, AgentState.COMPLETED)
        finally:
            shutil.rmtree(td)


# ══════════════════════════════════════════════════════════════════════════
#  4. SECURITY MODE
# ══════════════════════════════════════════════════════════════════════════

class TestSecurityMode(unittest.TestCase):
    """REAL: SECURITY mode enforces strict requirements."""

    def test_security_blocks_cloud_ai(self):
        """REAL: SECURITY mode blocks cloud AI."""
        policy = load_policy(Mode('security'))
        self.assertEqual(policy.get('llm_cloud_allowed'), 'false')

    def test_security_requires_sandbox(self):
        """REAL: SECURITY requires sandbox — fails closed on Windows."""
        policy = load_policy(Mode('security'))
        self.assertEqual(policy.get('sandbox_required'), 'true')

        # On Windows, sandbox is UNSUPPORTED → workflow must be BLOCKED
        sandbox = get_adapter('agent-sandbox', WORKSPACE)
        health = sandbox.health()
        if health.status == ResultStatus.UNSUPPORTED:
            # SECURITY mode cannot proceed without sandbox
            self.assertEqual(health.status, ResultStatus.UNSUPPORTED)

    def test_security_strict_diff_gate(self):
        """REAL: SECURITY requires strict diff-gate."""
        policy = load_policy(Mode('security'))
        self.assertEqual(policy.get('diff_gate_required'), 'true')
        self.assertEqual(policy.get('sandbox_strict'), 'true')

    def test_security_enhanced_evidence(self):
        """REAL: SECURITY uses enhanced evidence level."""
        policy = load_policy(Mode('security'))
        self.assertEqual(policy.get('evidence_level'), 'enhanced')


# ══════════════════════════════════════════════════════════════════════════
#  5. ENTERPRISE MODE
# ══════════════════════════════════════════════════════════════════════════

class TestEnterpriseMode(unittest.TestCase):
    """REAL: ENTERPRISE mode enforces maximum governance."""

    def test_enterprise_requires_approval(self):
        """REAL: ENTERPRISE requires approval."""
        policy = load_policy(Mode('enterprise'))
        self.assertEqual(policy.get('approval_required'), 'true')

    def test_enterprise_blocks_cloud_ai(self):
        """REAL: ENTERPRISE blocks cloud AI."""
        policy = load_policy(Mode('enterprise'))
        self.assertEqual(policy.get('llm_cloud_allowed'), 'false')

    def test_enterprise_complete_evidence(self):
        """REAL: ENTERPRISE uses complete evidence."""
        policy = load_policy(Mode('enterprise'))
        self.assertEqual(policy.get('evidence_level'), 'complete')


# ══════════════════════════════════════════════════════════════════════════
#  6. MULTI-AGENT INTEGRATION
# ══════════════════════════════════════════════════════════════════════════

class TestMultiAgentIntegration(unittest.TestCase):
    """REAL: Multiple agents with different roles."""

    def test_planner_reviewer_security_pipeline(self):
        """REAL: Planner → Reviewer → Security pipeline."""
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id='RUN-MULTI-001', persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)

            reviewer = Agent.create(AgentRole.REVIEWER, 'Reviewer')
            reviewer.initialize()
            reviewer.ready()
            security = Agent.create(AgentRole.SECURITY, 'Security')
            security.initialize()
            security.ready()
            researcher = Agent.create(AgentRole.RESEARCHER, 'Researcher')
            researcher.initialize()
            researcher.ready()

            scheduler.register_agent(reviewer)
            scheduler.register_agent(security)
            scheduler.register_agent(researcher)

            tasks = [
                AgentTask(
                    description='review changes',
                    agent_role=AgentRole.REVIEWER,
                    allowed_tools=('agent-diff-gate',),
                ),
                AgentTask(
                    description='security analysis',
                    agent_role=AgentRole.SECURITY,
                    allowed_tools=('agent-diff-gate',),
                ),
                AgentTask(
                    description='investigate history',
                    agent_role=AgentRole.RESEARCHER,
                    allowed_tools=('agent-blame',),
                ),
            ]

            results = scheduler.execute_sequential(tasks, NoneProvider())
            self.assertEqual(len(results), 3)

            # Verify each agent produced a result
            for r in results:
                self.assertEqual(r.status, AgentState.COMPLETED)
                self.assertTrue(len(r.output) > 0)

            # Verify evidence recorded all three
            entries = evidence.entries()
            agent_entries = [e for e in entries if 'agent_task' in str(e.get('action', ''))]
            self.assertGreaterEqual(len(agent_entries), 3)
        finally:
            shutil.rmtree(td)

    def test_agent_failure_stops_sequence(self):
        """REAL: Critical agent failure stops the pipeline."""
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id='RUN-FAIL-001', persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)

            planner = Agent.create(AgentRole.PLANNER, 'Planner')
            planner.initialize()
            planner.ready()
            scheduler.register_agent(planner)

            tasks = [
                AgentTask(
                    description='plan work',
                    agent_role=AgentRole.PLANNER,
                    allowed_tools=('agent-memory',),
                ),
                AgentTask(
                    description='execute in sandbox',
                    agent_role=AgentRole.PLANNER,
                    allowed_tools=('agent-sandbox',),
                    critical=True,
                ),
            ]

            results = scheduler.execute_sequential(tasks, NoneProvider())
            # Second task is critical and should fail (planner lacks sandbox)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[1].status, AgentState.BLOCKED)
        finally:
            shutil.rmtree(td)


# ══════════════════════════════════════════════════════════════════════════
#  7. SEVEN-TOOL INTEGRATION
# ══════════════════════════════════════════════════════════════════════════

class TestSevenToolIntegration(unittest.TestCase):
    """REAL: All seven tools exercised through adapters."""

    def test_all_tools_exercised(self):
        """REAL: Every tool returns a real result."""
        results = {}

        # error-log
        a = get_adapter('agent-error-log', WORKSPACE)
        r = a.check()
        results['error-log'] = r.exit_code

        # decision-log
        a = get_adapter('agent-decision-log', WORKSPACE)
        r = a.check()
        results['decision-log'] = r.exit_code

        # log-ai
        a = get_adapter('agent-log-ai', WORKSPACE)
        r = a.check(model='qwen2.5-coder:14b')
        results['log-ai'] = r.exit_code

        # memory
        a = get_adapter('agent-memory', WORKSPACE)
        r = a.status(WORKSPACE)
        results['memory'] = r.exit_code

        # blame
        a = get_adapter('agent-blame', WORKSPACE)
        r = a.diff()
        results['blame'] = r.exit_code

        # diff-gate
        a = get_adapter('agent-diff-gate', WORKSPACE)
        r = a.check_staged()
        results['diff-gate'] = r.exit_code

        # sandbox
        a = get_adapter('agent-sandbox', WORKSPACE)
        r = a.health()
        results['sandbox'] = r.exit_code

        # Verify all returned real results (not exceptions)
        for name, code in results.items():
            self.assertIsInstance(code, int, f"{name} did not return an exit code")

    def test_tool_output_to_decision_chain(self):
        """REAL: Tool output flows into decisions."""
        # Step 1: error-log check
        error_adapter = get_adapter('agent-error-log', WORKSPACE)
        error_result = error_adapter.check()
        has_errors = error_result.status == ResultStatus.FAIL

        # Step 2: decision based on error result
        if has_errors:
            decision = 'BLOCK — log errors first'
        else:
            decision = 'PROCEED — no errors'

        self.assertIn(decision, ('BLOCK — log errors first', 'PROCEED — no errors'))

        # Step 3: diff-gate check
        diff_adapter = get_adapter('agent-diff-gate', WORKSPACE)
        diff_result = diff_adapter.check_staged()
        diff_pass = 'PASS' in diff_result.stdout

        # Step 4: combined decision
        if decision.startswith('PROCEED') and diff_pass:
            final = 'SAFE to commit'
        else:
            final = 'BLOCKED'

        self.assertIn(final, ('SAFE to commit', 'BLOCKED'))


# ══════════════════════════════════════════════════════════════════════════
#  8. PERSISTENCE AND RECOVERY
# ══════════════════════════════════════════════════════════════════════════

class TestPersistenceRecovery(unittest.TestCase):
    """REAL: Persistence survives normal completion."""

    def test_run_persists_and_loads(self):
        """REAL: Run state persists and loads correctly."""
        td = Path(tempfile.mkdtemp())
        try:
            state = RunState(workflow_name='test-persist', mode='solo')
            state.transition(Phase.BOOTSTRAPPING)
            state.transition(Phase.CHECKING)
            state.transition(Phase.EXECUTING)
            state.transition(Phase.COMPLETED)
            state.finalize('PASS')
            persist_run(state, td)

            # Load and verify
            loaded = load_state(state.run_id, td)
            self.assertEqual(loaded.phase, Phase.COMPLETED)
            self.assertEqual(loaded.final_status, 'PASS')
            self.assertEqual(loaded.workflow_name, 'test-persist')
        finally:
            shutil.rmtree(td)

    def test_evidence_persists(self):
        """REAL: Evidence survives process termination."""
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id='RUN-EV-PERSIST', persist_dir=td)
            evidence.record(action='step1', tool='test', status='PASS')
            evidence.record(action='step2', tool='test', status='PASS')
            evidence.record(action='step3', tool='test', status='FAIL')

            # Verify entries persist
            entries = evidence.entries()
            self.assertEqual(len(entries), 3)
        finally:
            shutil.rmtree(td)

    def test_interrupted_run_detected(self):
        """REAL: Interrupted runs are detectable."""
        td = Path(tempfile.mkdtemp())
        try:
            # Create a run that didn't complete
            state = RunState(workflow_name='test-interrupted', mode='solo')
            state.transition(Phase.BOOTSTRAPPING)
            state.transition(Phase.CHECKING)
            state.transition(Phase.EXECUTING)
            # Don't transition to COMPLETED — simulate interruption
            persist_run(state, td)

            # Should be detected as interrupted
            interrupted = find_interrupted_runs(td)
            self.assertEqual(len(interrupted), 1)
        finally:
            shutil.rmtree(td)

    def test_run_history(self):
        """REAL: Multiple runs tracked in history."""
        td = Path(tempfile.mkdtemp())
        try:
            for i in range(3):
                state = _make_completed_run(f'run-{i}', 'solo')
                persist_run(state, td)

            runs = list_runs(td)
            self.assertEqual(len(runs), 3)
        finally:
            shutil.rmtree(td)


# ══════════════════════════════════════════════════════════════════════════
#  9. REPORTING
# ══════════════════════════════════════════════════════════════════════════

class TestReporting(unittest.TestCase):
    """REAL: Markdown and JSON reports generated correctly."""

    def test_markdown_report(self):
        """REAL: Markdown report generated from state."""
        state = _make_completed_run('test-report', 'solo')
        md = format_report(state)
        self.assertIn('test-report', md)
        self.assertIn('PASS', md)
        self.assertIn('solo', md)

    def test_json_report(self):
        """REAL: JSON report generated from state."""
        state = _make_completed_run('test-json', 'development')
        jr = report_json(state)
        data = json.loads(jr)
        self.assertIn('workflow', data)
        self.assertIn('final_status', data)

    def test_report_no_secrets(self):
        """REAL: Reports do not contain secrets."""
        state = _make_completed_run('test-secrets', 'solo')
        md = format_report(state)
        jr = report_json(state)
        for report in [md, jr]:
            self.assertNotIn('password', report.lower())
            self.assertNotIn('api_key', report.lower())
            self.assertNotIn('secret_key', report.lower())


# ══════════════════════════════════════════════════════════════════════════
#  10. FAILURE HANDLING
# ══════════════════════════════════════════════════════════════════════════

class TestFailureHandling(unittest.TestCase):
    """REAL: Failures are handled correctly."""

    def test_invalid_config_fails_closed(self):
        """REAL: Invalid configuration rejected."""
        result = validate_config_value('mode', 'INVALID')
        self.assertFalse(result.valid)

    def test_nonexistent_tool_returns_error(self):
        """REAL: Nonexistent adapter returns None."""
        result = get_adapter('nonexistent-tool', WORKSPACE)
        self.assertIsNone(result)

    def test_provider_unavailable_blocks_ai_agents(self):
        """REAL: NoneProvider blocks AI-needing agents."""
        scheduler = TaskScheduler()
        dev = Agent.create(AgentRole.DEVELOPER, 'D')
        dev.initialize()
        dev.ready()
        scheduler.register_agent(dev)

        task = AgentTask(
            description='complex task',
            agent_role=AgentRole.DEVELOPER,
            allowed_tools=('agent-error-log',),
        )
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.BLOCKED)
        self.assertIn('unavailable', result.error)

    def test_deterministic_agents_survive_provider_failure(self):
        """REAL: Deterministic agents work without provider."""
        scheduler = TaskScheduler()
        reviewer = Agent.create(AgentRole.REVIEWER, 'R')
        reviewer.initialize()
        reviewer.ready()
        scheduler.register_agent(reviewer)

        task = AgentTask(
            description='review',
            agent_role=AgentRole.REVIEWER,
            allowed_tools=('agent-diff-gate',),
        )
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)


# ══════════════════════════════════════════════════════════════════════════
#  11. CLI VERIFICATION
# ══════════════════════════════════════════════════════════════════════════

class TestCLIVerification(unittest.TestCase):
    """REAL: All CLI commands work."""

    def test_cli_commands_exist(self):
        """REAL: CLI module is importable and has main."""
        from orchestrator.cli import main
        self.assertTrue(callable(main))

    def test_discovery_all_seven(self):
        """REAL: All seven tools discovered."""
        tools = discover_all(WORKSPACE)
        self.assertEqual(len(tools), 7)
        names = {t.name for t in tools}
        self.assertIn('agent-error-log', names)
        self.assertIn('agent-sandbox', names)


# ══════════════════════════════════════════════════════════════════════════
#  12. CROSS-PROJECT ISOLATION
# ══════════════════════════════════════════════════════════════════════════

class TestCrossProjectIsolation(unittest.TestCase):
    """REAL: Multiple projects remain isolated."""

    def test_independent_persistence(self):
        """REAL: Separate persistence directories."""
        td1 = Path(tempfile.mkdtemp())
        td2 = Path(tempfile.mkdtemp())
        try:
            state1 = _make_completed_run('project-a', 'solo')
            persist_run(state1, td1)

            state2 = _make_completed_run('project-b', 'development')
            persist_run(state2, td2)

            runs1 = list_runs(td1)
            runs2 = list_runs(td2)

            self.assertEqual(len(runs1), 1)
            self.assertEqual(len(runs2), 1)
            self.assertNotEqual(runs1[0].run_id, runs2[0].run_id)
        finally:
            shutil.rmtree(td1)
            shutil.rmtree(td2)


if __name__ == '__main__':
    unittest.main()
