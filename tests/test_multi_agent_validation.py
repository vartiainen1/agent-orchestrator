"""STEP 3 — Real Multi-Agent Validation Tests.

Proves the multi-agent system works end-to-end with multiple agents,
roles, permissions, security boundaries, scheduling, and evidence.

Agents must be in READY state before the scheduler can assign tasks.
The pattern is: create -> initialize -> ready -> register -> execute.
"""

import unittest
import dataclasses
import tempfile
import shutil
from pathlib import Path

from orchestrator.agents import (
    Agent,
    AgentIdentity,
    AgentPermissions,
    AgentResult,
    AgentRole,
    AgentState,
    AgentTask,
    InvalidAgentTransition,
    authority_level,
    create_identity,
    get_default_permissions,
    is_valid_agent_transition,
)
from orchestrator.providers import NoneProvider, ProviderStatus
from orchestrator.scheduler import TaskScheduler, assign_task, resolve_conflicts
from orchestrator.evidence import EvidenceLog


def _make_ready(role, name="test"):
    """Create an agent and advance it to READY state."""
    agent = Agent.create(role, name)
    agent.initialize()
    agent.ready()
    return agent


# ── 1. Multiple agents can exist in one orchestration run ────────────────

class TestMultipleAgentsExist(unittest.TestCase):
    """VALIDATION: Multiple agents can coexist."""

    def test_five_agents_coexist(self):
        agents = [_make_ready(AgentRole.PLANNER, "P"),
                  _make_ready(AgentRole.DEVELOPER, "D"),
                  _make_ready(AgentRole.REVIEWER, "R"),
                  _make_ready(AgentRole.TESTER, "T"),
                  _make_ready(AgentRole.SECURITY, "S")]
        self.assertEqual(len(agents), 5)
        ids = [a.agent_id for a in agents]
        self.assertEqual(len(set(ids)), 5)

    def test_all_seven_roles_exist(self):
        for role in AgentRole:
            agent = _make_ready(role, f"r-{role.value}")
            self.assertEqual(agent.role, role)


# ── 2. Agents have distinct identities ──────────────────────────────────

class TestDistinctIdentities(unittest.TestCase):
    """VALIDATION: Agent identities are distinct and immutable."""

    def test_unique_agent_ids(self):
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        a2 = _make_ready(AgentRole.DEVELOPER, "D2")
        self.assertNotEqual(a1.agent_id, a2.agent_id)

    def test_identity_frozen(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ident.agent_id = "changed"

    def test_identity_role_immutable(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ident.role = AgentRole.SECURITY

    def test_identity_has_timestamp(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        self.assertTrue(len(ident.created_at) > 0)


# ── 3. Agents have explicit roles ───────────────────────────────────────

class TestExplicitRoles(unittest.TestCase):
    """VALIDATION: Each agent has a clear, explicit role."""

    def test_role_on_identity(self):
        agent = _make_ready(AgentRole.REVIEWER, "R")
        self.assertEqual(agent.identity.role, AgentRole.REVIEWER)
        self.assertEqual(agent.role, AgentRole.REVIEWER)

    def test_role_affects_permissions(self):
        planner = _make_ready(AgentRole.PLANNER, "P")
        developer = _make_ready(AgentRole.DEVELOPER, "D")
        self.assertFalse(planner.permissions.can_write)
        self.assertTrue(developer.permissions.can_write)


# ── 4. Agent permissions are enforced ───────────────────────────────────

class TestPermissionEnforcement(unittest.TestCase):
    """VALIDATION: Tool permissions are enforced per role."""

    def test_planner_limited_tools(self):
        p = _make_ready(AgentRole.PLANNER, "P")
        self.assertTrue(p.can_use_tool("agent-error-log"))
        self.assertTrue(p.can_use_tool("agent-decision-log"))
        self.assertTrue(p.can_use_tool("agent-memory"))
        self.assertFalse(p.can_use_tool("agent-sandbox"))
        self.assertFalse(p.can_use_tool("agent-diff-gate"))

    def test_developer_full_tools(self):
        d = _make_ready(AgentRole.DEVELOPER, "D")
        for tool in ("agent-error-log", "agent-decision-log", "agent-log-ai",
                      "agent-memory", "agent-blame", "agent-diff-gate", "agent-sandbox"):
            self.assertTrue(d.can_use_tool(tool), f"developer should use {tool}")

    def test_reviewer_read_only(self):
        r = _make_ready(AgentRole.REVIEWER, "R")
        self.assertTrue(r.can_perform("read"))
        self.assertFalse(r.can_perform("write"))
        self.assertFalse(r.can_perform("execute"))

    def test_tester_can_execute(self):
        t = _make_ready(AgentRole.TESTER, "T")
        self.assertTrue(t.can_perform("execute"))
        self.assertTrue(t.can_perform("sandbox"))
        self.assertTrue(t.can_use_tool("agent-sandbox"))

    def test_security_read_only_except_sandbox(self):
        s = _make_ready(AgentRole.SECURITY, "S")
        self.assertTrue(s.can_perform("read"))
        self.assertFalse(s.can_perform("write"))
        self.assertTrue(s.can_use_tool("agent-sandbox"))
        self.assertFalse(s.can_use_tool("agent-error-log"))

    def test_documenter_limited(self):
        d = _make_ready(AgentRole.DOCUMENTER, "D")
        self.assertTrue(d.can_perform("read"))
        self.assertTrue(d.can_perform("write"))
        self.assertFalse(d.can_perform("execute"))
        self.assertTrue(d.can_use_tool("agent-error-log"))
        self.assertFalse(d.can_use_tool("agent-sandbox"))

    def test_researcher_read_only(self):
        r = _make_ready(AgentRole.RESEARCHER, "R")
        self.assertTrue(r.can_perform("read"))
        self.assertFalse(r.can_perform("write"))
        self.assertFalse(r.can_perform("execute"))
        self.assertTrue(r.can_use_tool("agent-blame"))
        self.assertFalse(r.can_use_tool("agent-sandbox"))


# ── 5. Agents cannot modify their own permissions ──────────────────────

class TestImmutablePermissions(unittest.TestCase):
    """VALIDATION: Agents cannot self-escalate permissions."""

    def test_permissions_frozen(self):
        perms = AgentPermissions()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            perms.can_write = True

    def test_permissions_tuple_immutable(self):
        perms = AgentPermissions(can_use_tools=("a", "b"))
        with self.assertRaises(AttributeError):
            perms.can_use_tools = ("a", "b", "c")

    def test_agent_cannot_change_own_permissions(self):
        agent = _make_ready(AgentRole.PLANNER, "P")
        original = agent.permissions
        self.assertFalse(hasattr(agent, "set_permissions"))
        self.assertFalse(hasattr(agent, "grant_permission"))
        self.assertFalse(hasattr(agent, "escalate"))
        self.assertIs(agent.permissions, original)


# ── 6. Agents cannot self-assign unauthorized tasks ────────────────────

class TestNoSelfAssignment(unittest.TestCase):
    """VALIDATION: Scheduler controls task assignment, not agents."""

    def test_agent_cannot_assign_task_to_self(self):
        agent = _make_ready(AgentRole.PLANNER, "P")
        self.assertFalse(hasattr(agent, "assign_own_task"))
        self.assertFalse(hasattr(agent, "steal_task"))

    def test_scheduler_assigns_not_agent(self):
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-error-log",))
        scheduler = TaskScheduler()
        scheduler.register_agent(dev)
        assigned = assign_task(task, scheduler.agents)
        self.assertEqual(assigned, dev)

    def test_wrong_role_cannot_be_assigned(self):
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        task = AgentTask(description="security review", agent_role=AgentRole.SECURITY)
        scheduler = TaskScheduler()
        scheduler.register_agent(dev)
        assigned = assign_task(task, scheduler.agents)
        self.assertIsNone(assigned)


# ── 7. Agents cannot bypass policy ──────────────────────────────────────

class TestNoPolicyBypass(unittest.TestCase):
    """VALIDATION: Scheduler enforces tool permissions (proxy for policy)."""

    def test_agent_without_tool_permission_blocked(self):
        planner = _make_ready(AgentRole.PLANNER, "P")
        task = AgentTask(
            description="run in sandbox",
            agent_role=AgentRole.PLANNER,
            allowed_tools=("agent-sandbox",),
        )
        scheduler = TaskScheduler()
        scheduler.register_agent(planner)
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.BLOCKED)


# ── 8. Agents cannot directly modify another agent's state ─────────────

class TestNoCrossAgentModification(unittest.TestCase):
    """VALIDATION: Agents are isolated from each other."""

    def test_no_cross_agent_method(self):
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        self.assertFalse(hasattr(a1, "modify_agent"))
        self.assertFalse(hasattr(a1, "block_agent"))
        self.assertFalse(hasattr(a1, "cancel_agent"))

    def test_scheduler_is_only_bridge(self):
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        a2 = _make_ready(AgentRole.REVIEWER, "R2")
        scheduler = TaskScheduler()
        scheduler.register_agent(a1)
        scheduler.register_agent(a2)
        self.assertEqual(len(scheduler.agents), 2)
        self.assertIsNone(scheduler.get_agent("nonexistent"))


# ── 9. No direct agent-to-agent communication ──────────────────────────

class TestNoDirectCommunication(unittest.TestCase):
    """VALIDATION: Agents cannot bypass the orchestrator."""

    def test_agent_has_no_send_method(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        self.assertFalse(hasattr(agent, "send"))
        self.assertFalse(hasattr(agent, "broadcast"))
        self.assertFalse(hasattr(agent, "communicate"))
        self.assertFalse(hasattr(agent, "message"))

    def test_agent_has_no_receive_method(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        self.assertFalse(hasattr(agent, "receive"))
        self.assertFalse(hasattr(agent, "listen"))

    def test_agent_has_no_reference_to_other_agents(self):
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        self.assertFalse(hasattr(a1, "peers"))
        self.assertFalse(hasattr(a1, "team"))
        self.assertFalse(hasattr(a1, "neighbors"))


# ── 10. Agent outputs pass through validation ───────────────────────────

class TestAgentOutputValidation(unittest.TestCase):
    """VALIDATION: Agent results are structured and checkable."""

    def test_result_has_required_fields(self):
        result = AgentResult(
            agent_id="agent-dev-001",
            task_id="task-001",
            status=AgentState.COMPLETED,
            output="Fixed the bug",
            confidence=0.9,
        )
        self.assertEqual(result.agent_id, "agent-dev-001")
        self.assertEqual(result.status, AgentState.COMPLETED)
        self.assertTrue(result.timestamp)

    def test_scheduler_records_result_with_agent_id(self):
        reviewer = _make_ready(AgentRole.REVIEWER, "R")
        scheduler = TaskScheduler()
        scheduler.register_agent(reviewer)
        task = AgentTask(
            description="analyze code",
            agent_role=AgentRole.REVIEWER,
            allowed_tools=("agent-diff-gate",),
        )
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.agent_id, reviewer.agent_id)
        self.assertEqual(result.status, AgentState.COMPLETED)


# ── 11. Agent actions produce evidence ──────────────────────────────────

class TestEvidenceRecording(unittest.TestCase):
    """VALIDATION: Evidence is recorded for agent actions."""

    def test_evidence_recorded_for_task(self):
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id="RUN-TEST-EV", persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)
            reviewer = _make_ready(AgentRole.REVIEWER, "R")
            scheduler.register_agent(reviewer)
            task = AgentTask(
                description="test task",
                agent_role=AgentRole.REVIEWER,
                allowed_tools=("agent-diff-gate",),
            )
            scheduler.execute_task(task, NoneProvider())
            self.assertGreater(len(evidence.entries()), 0)
        finally:
            shutil.rmtree(td)

    def test_evidence_contains_agent_id(self):
        td = Path(tempfile.mkdtemp())
        try:
            evidence = EvidenceLog(run_id="RUN-TEST-EV2", persist_dir=td)
            scheduler = TaskScheduler(evidence=evidence)
            reviewer = _make_ready(AgentRole.REVIEWER, "R")
            scheduler.register_agent(reviewer)
            task = AgentTask(
                description="test",
                agent_role=AgentRole.REVIEWER,
                allowed_tools=("agent-diff-gate",),
            )
            scheduler.execute_task(task, NoneProvider())
            found = any(
                reviewer.agent_id in str(entry)
                for entry in evidence.entries()
            )
            self.assertTrue(found, "evidence should reference agent_id")
        finally:
            shutil.rmtree(td)


# ── 12. Orchestrator remains the authority ──────────────────────────────

class TestOrchestratorAuthority(unittest.TestCase):
    """VALIDATION: The scheduler (orchestrator) controls everything."""

    def test_scheduler_decides_which_agent_runs(self):
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        planner = _make_ready(AgentRole.PLANNER, "P")
        scheduler = TaskScheduler()
        scheduler.register_agent(dev)
        scheduler.register_agent(planner)
        task = AgentTask(
            description="code fix",
            agent_role=AgentRole.DEVELOPER,
            allowed_tools=("agent-error-log",),
        )
        assigned = assign_task(task, scheduler.agents)
        self.assertEqual(assigned.agent_id, dev.agent_id)

    def test_scheduler_can_block_agents(self):
        # Block via CREATED state (CREATED -> BLOCKED is valid)
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        agent.block()
        self.assertEqual(agent.state, AgentState.BLOCKED)
        # BLOCKED is not in TERMINAL_STATES but no transitions are allowed from it
        self.assertFalse(is_valid_agent_transition(AgentState.BLOCKED, AgentState.READY))
        self.assertFalse(is_valid_agent_transition(AgentState.BLOCKED, AgentState.RUNNING))

    def test_scheduler_manages_lifecycle(self):
        agent = _make_ready(AgentRole.SECURITY, "S")
        scheduler = TaskScheduler()
        scheduler.register_agent(agent)
        task = AgentTask(
            description="test",
            agent_role=AgentRole.SECURITY,
            allowed_tools=("agent-diff-gate",),
        )
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)
        self.assertEqual(agent.state, AgentState.COMPLETED)


# ── 13. Authority hierarchy ─────────────────────────────────────────────

class TestAuthorityHierarchy(unittest.TestCase):
    """VALIDATION: Authority levels are defined and respected."""

    def test_security_highest(self):
        self.assertGreater(authority_level(AgentRole.SECURITY),
                           authority_level(AgentRole.DEVELOPER))

    def test_reviewer_higher_than_developer(self):
        self.assertGreater(authority_level(AgentRole.REVIEWER),
                           authority_level(AgentRole.DEVELOPER))

    def test_documenter_lowest(self):
        for role in AgentRole:
            if role != AgentRole.DOCUMENTER:
                self.assertGreater(
                    authority_level(role),
                    authority_level(AgentRole.DOCUMENTER),
                )


# ── 14. Blocked agent remains blocked ───────────────────────────────────

class TestBlockedAgentBehavior(unittest.TestCase):
    """VALIDATION: Blocked agents cannot proceed."""

    def test_blocked_is_terminal(self):
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        agent.block()
        # BLOCKED has no outgoing transitions — effectively terminal
        for target in AgentState:
            if target == AgentState.BLOCKED:
                continue
            self.assertFalse(is_valid_agent_transition(AgentState.BLOCKED, target))

    def test_cannot_unblock(self):
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        agent.block()
        with self.assertRaises(InvalidAgentTransition):
            agent.ready()

    def test_cannot_assign_to_blocked(self):
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        agent.block()
        task = AgentTask(description="test", agent_role=AgentRole.DEVELOPER)
        scheduler = TaskScheduler()
        scheduler.register_agent(agent)
        assigned = assign_task(task, scheduler.agents)
        self.assertIsNone(assigned)


# ── 15. Failure handling ────────────────────────────────────────────────

class TestFailureHandling(unittest.TestCase):
    """VALIDATION: Agent failures are handled correctly."""

    def test_failed_is_terminal(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        task = AgentTask(description="test", agent_role=AgentRole.DEVELOPER)
        agent.assign(task)
        agent.start_running()
        agent.fail("something went wrong")
        self.assertTrue(agent.is_terminal())
        self.assertEqual(agent.state, AgentState.FAILED)

    def test_result_has_error(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        task = AgentTask(description="test", agent_role=AgentRole.DEVELOPER)
        agent.assign(task)
        agent.start_running()
        agent.fail("error message")
        self.assertIsNotNone(agent.result)
        self.assertEqual(agent.result.error, "error message")


# ── 16. Sequential multi-agent execution ────────────────────────────────

class TestSequentialExecution(unittest.TestCase):
    """VALIDATION: Multiple agents execute sequentially."""

    def test_three_agents_sequential(self):
        scheduler = TaskScheduler()
        rev = _make_ready(AgentRole.REVIEWER, "R")
        sec = _make_ready(AgentRole.SECURITY, "S")
        res = _make_ready(AgentRole.RESEARCHER, "Res")
        scheduler.register_agent(rev)
        scheduler.register_agent(sec)
        scheduler.register_agent(res)

        tasks = [
            AgentTask(description="review", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
            AgentTask(description="security check", agent_role=AgentRole.SECURITY,
                      allowed_tools=("agent-diff-gate",)),
            AgentTask(description="research history", agent_role=AgentRole.RESEARCHER,
                      allowed_tools=("agent-blame",)),
        ]

        results = scheduler.execute_sequential(tasks, NoneProvider())
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r.status, AgentState.COMPLETED)

    def test_critical_task_stops_sequence(self):
        scheduler = TaskScheduler()
        planner = _make_ready(AgentRole.PLANNER, "P")
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        scheduler.register_agent(planner)
        scheduler.register_agent(dev)

        tasks = [
            AgentTask(description="plan", agent_role=AgentRole.PLANNER,
                      allowed_tools=("agent-memory",)),
            AgentTask(description="sandbox work", agent_role=AgentRole.PLANNER,
                      allowed_tools=("agent-sandbox",), critical=True),
            AgentTask(description="develop", agent_role=AgentRole.DEVELOPER,
                      allowed_tools=("agent-error-log",)),
        ]

        results = scheduler.execute_sequential(tasks, NoneProvider())
        # Task 2 (critical, sandbox) fails because planner lacks sandbox permission
        # Task 3 should not execute
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1].status, AgentState.BLOCKED)


# ── 17. Parallel execution interface ────────────────────────────────────

class TestParallelInterface(unittest.TestCase):
    """VALIDATION: Parallel interface falls back to sequential safely."""

    def test_parallel_same_as_sequential(self):
        scheduler = TaskScheduler()
        # Need 2 reviewers since each agent can only handle one task
        r1 = _make_ready(AgentRole.REVIEWER, "R1")
        r2 = _make_ready(AgentRole.REVIEWER, "R2")
        scheduler.register_agent(r1)
        scheduler.register_agent(r2)

        tasks = [
            AgentTask(description="task1", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
            AgentTask(description="task2", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
        ]

        results = scheduler.execute_parallel(tasks, NoneProvider())
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r.status, AgentState.COMPLETED)


# ── 18. Provider abstraction ────────────────────────────────────────────

class TestProviderAbstraction(unittest.TestCase):
    """VALIDATION: Agents use providers without the engine knowing which."""

    def test_none_provider_blocks_ai_agents(self):
        scheduler = TaskScheduler()
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        scheduler.register_agent(dev)
        task = AgentTask(description="complex task", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-error-log",))
        result = scheduler.execute_task(task, NoneProvider())
        # DEVELOPER needs AI, NoneProvider blocks
        self.assertEqual(result.status, AgentState.BLOCKED)
        self.assertIn("AI provider unavailable", result.error)

    def test_deterministic_agents_work_without_provider(self):
        scheduler = TaskScheduler()
        reviewer = _make_ready(AgentRole.REVIEWER, "R")
        scheduler.register_agent(reviewer)
        task = AgentTask(description="review code", agent_role=AgentRole.REVIEWER,
                         allowed_tools=("agent-diff-gate",))
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)

    def test_researcher_works_without_provider(self):
        scheduler = TaskScheduler()
        researcher = _make_ready(AgentRole.RESEARCHER, "Res")
        scheduler.register_agent(researcher)
        task = AgentTask(description="investigate history", agent_role=AgentRole.RESEARCHER,
                         allowed_tools=("agent-blame",))
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)

    def test_security_works_without_provider(self):
        scheduler = TaskScheduler()
        security = _make_ready(AgentRole.SECURITY, "S")
        scheduler.register_agent(security)
        task = AgentTask(description="security review", agent_role=AgentRole.SECURITY,
                         allowed_tools=("agent-diff-gate",))
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)

    def test_documenter_works_without_provider(self):
        scheduler = TaskScheduler()
        doc = _make_ready(AgentRole.DOCUMENTER, "Doc")
        scheduler.register_agent(doc)
        task = AgentTask(description="write docs", agent_role=AgentRole.DOCUMENTER,
                         allowed_tools=("agent-decision-log",))
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)


# ── 19. Conflict resolution ────────────────────────────────────────────

class TestConflictResolution(unittest.TestCase):
    """VALIDATION: Conflicts are resolved through authority."""

    def test_empty_results(self):
        result = resolve_conflicts([])
        self.assertIsNone(result)

    def test_single_result(self):
        r = AgentResult(agent_id="a1", status=AgentState.COMPLETED)
        result = resolve_conflicts([r])
        self.assertEqual(result.agent_id, "a1")


# ── 20. Cancel behavior ─────────────────────────────────────────────────

class TestCancelBehavior(unittest.TestCase):
    """VALIDATION: Agents can be cancelled safely."""

    def test_cancelled_is_terminal(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        agent.cancel("not needed")
        self.assertTrue(agent.is_terminal())
        self.assertEqual(agent.state, AgentState.CANCELLED)

    def test_cancel_produces_result(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        agent.cancel("reason")
        self.assertIsNotNone(agent.result)
        self.assertIn("reason", agent.result.error)


# ── 21. Security attack tests ──────────────────────────────────────────

class TestSecurityAttacks(unittest.TestCase):
    """SECURITY: Attempt deliberate violations."""

    def test_cannot_grant_self_write(self):
        planner = _make_ready(AgentRole.PLANNER, "P")
        self.assertFalse(planner.permissions.can_write)

    def test_cannot_grant_self_sandbox(self):
        researcher = _make_ready(AgentRole.RESEARCHER, "R")
        self.assertFalse(researcher.permissions.can_use_sandbox)

    def test_cannot_approve_own_work(self):
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        self.assertFalse(dev.permissions.can_approve)

    def test_cannot_promote_memory(self):
        for role in AgentRole:
            agent = _make_ready(role, f"test-{role.value}")
            self.assertFalse(agent.permissions.can_promote_memory,
                             f"{role} should not promote memory")

    def test_blocked_agent_cannot_restart(self):
        # Block via CREATED state (CREATED -> BLOCKED is valid)
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        agent.block()
        self.assertEqual(agent.state, AgentState.BLOCKED)
        for target in AgentState:
            if target == AgentState.BLOCKED:
                continue
            with self.assertRaises(InvalidAgentTransition):
                agent._transition(target)

    def test_completed_agent_cannot_restart(self):
        agent = _make_ready(AgentRole.DEVELOPER, "D")
        task = AgentTask(description="test", agent_role=AgentRole.DEVELOPER)
        agent.assign(task)
        agent.start_running()
        agent.complete(AgentResult(agent_id=agent.agent_id, status=AgentState.COMPLETED))
        for target in AgentState:
            if target == AgentState.COMPLETED:
                continue
            with self.assertRaises(InvalidAgentTransition):
                agent._transition(target)

    def test_escalation_not_possible_via_task(self):
        planner = _make_ready(AgentRole.PLANNER, "P")
        task = AgentTask(
            description="use sandbox",
            agent_role=AgentRole.PLANNER,
            allowed_tools=("agent-sandbox",),
        )
        scheduler = TaskScheduler()
        scheduler.register_agent(planner)
        assigned = assign_task(task, scheduler.agents)
        self.assertIsNone(assigned, "planner should not be assignable to sandbox task")


# ── 22. Lifecycle state transitions ─────────────────────────────────────

class TestLifecycleTransitions(unittest.TestCase):
    """VALIDATION: Lifecycle state machine is correct."""

    def test_happy_path(self):
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        self.assertEqual(agent.state, AgentState.CREATED)
        agent.initialize()
        self.assertEqual(agent.state, AgentState.INITIALIZING)
        agent.ready()
        self.assertEqual(agent.state, AgentState.READY)
        task = AgentTask(description="test", agent_role=AgentRole.DEVELOPER)
        agent.assign(task)
        self.assertEqual(agent.state, AgentState.ASSIGNED)
        agent.start_running()
        self.assertEqual(agent.state, AgentState.RUNNING)
        agent.complete(AgentResult(agent_id=agent.agent_id, status=AgentState.COMPLETED))
        self.assertEqual(agent.state, AgentState.COMPLETED)
        self.assertTrue(agent.is_terminal())

    def test_invalid_transition_raises(self):
        agent = Agent.create(AgentRole.DEVELOPER, "D")
        with self.assertRaises(InvalidAgentTransition):
            agent._transition(AgentState.RUNNING)

    def test_valid_transition_map(self):
        self.assertTrue(is_valid_agent_transition(AgentState.CREATED, AgentState.INITIALIZING))
        self.assertTrue(is_valid_agent_transition(AgentState.CREATED, AgentState.BLOCKED))
        self.assertTrue(is_valid_agent_transition(AgentState.CREATED, AgentState.CANCELLED))
        self.assertFalse(is_valid_agent_transition(AgentState.CREATED, AgentState.RUNNING))
        self.assertFalse(is_valid_agent_transition(AgentState.CREATED, AgentState.COMPLETED))


# ── 23. Scheduler agent management ──────────────────────────────────────

class TestSchedulerAgentManagement(unittest.TestCase):
    """VALIDATION: Scheduler manages agent registration."""

    def test_register_and_list(self):
        scheduler = TaskScheduler()
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        a2 = _make_ready(AgentRole.REVIEWER, "R2")
        scheduler.register_agent(a1)
        scheduler.register_agent(a2)
        self.assertEqual(len(scheduler.agents), 2)

    def test_unregister(self):
        scheduler = TaskScheduler()
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        scheduler.register_agent(a1)
        self.assertTrue(scheduler.unregister_agent(a1.agent_id))
        self.assertEqual(len(scheduler.agents), 0)

    def test_unregister_nonexistent(self):
        scheduler = TaskScheduler()
        self.assertFalse(scheduler.unregister_agent("fake-id"))

    def test_get_agent(self):
        scheduler = TaskScheduler()
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        scheduler.register_agent(a1)
        found = scheduler.get_agent(a1.agent_id)
        self.assertEqual(found.agent_id, a1.agent_id)

    def test_ready_agents(self):
        scheduler = TaskScheduler()
        a1 = _make_ready(AgentRole.DEVELOPER, "D1")
        scheduler.register_agent(a1)
        self.assertEqual(len(scheduler.ready_agents()), 1)


# ── 24. No fabricated results ───────────────────────────────────────────

class TestNoFabricatedResults(unittest.TestCase):
    """SECURITY: Orchestrator never fabricates tool results."""

    def test_none_provider_does_not_fake_response(self):
        provider = NoneProvider()
        resp = provider.complete("test prompt")
        self.assertEqual(resp.status, ProviderStatus.UNAVAILABLE)
        self.assertFalse(resp.ok)
        self.assertEqual(resp.text, "")

    def test_scheduler_blocks_when_no_provider(self):
        scheduler = TaskScheduler()
        dev = _make_ready(AgentRole.DEVELOPER, "D")
        scheduler.register_agent(dev)
        task = AgentTask(description="complex", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-error-log",))
        result = scheduler.execute_task(task, NoneProvider())
        self.assertEqual(result.status, AgentState.BLOCKED)
        self.assertIn("unavailable", result.error)


if __name__ == "__main__":
    unittest.main()
