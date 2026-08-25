"""Tests for orchestrator.scheduler — Phase 6 Step 3: task scheduler."""

import unittest

from orchestrator.agents import (
    Agent,
    AgentPermissions,
    AgentResult,
    AgentRole,
    AgentState,
    AgentTask,
)
from orchestrator.evidence import EvidenceLog
from orchestrator.providers import NoneProvider, ProviderStatus
from orchestrator.scheduler import (
    SchedulerMode,
    TaskScheduler,
    assign_task,
    resolve_conflicts,
)


# ══════════════════════════════════════════════════════════════════════════
#  TASK ASSIGNMENT
# ══════════════════════════════════════════════════════════════════════════

class TestAssignTask(unittest.TestCase):
    """assign_task function."""

    def setUp(self):
        self.dev = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.dev.initialize()
        self.dev.ready()
        self.rev = Agent.create(AgentRole.REVIEWER, "Rev")
        self.rev.initialize()
        self.rev.ready()
        self.sec = Agent.create(AgentRole.SECURITY, "Sec")
        self.sec.initialize()
        self.sec.ready()

    def test_assign_to_matching_role(self):
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-diff-gate",))
        agent = assign_task(task, [self.dev, self.rev])
        self.assertEqual(agent.role, AgentRole.DEVELOPER)

    def test_assign_rejects_wrong_role(self):
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-diff-gate",))
        agent = assign_task(task, [self.rev])
        self.assertIsNone(agent)

    def test_assign_rejects_unauthorized_tool(self):
        task = AgentTask(description="run sandbox", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-sandbox",))
        # Reviewer cannot use sandbox
        agent = assign_task(task, [self.rev])
        self.assertIsNone(agent)

    def test_assign_skips_non_ready_agents(self):
        self.dev.cancel("test")
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-diff-gate",))
        agent = assign_task(task, [self.dev])
        self.assertIsNone(agent)

    def test_assign_no_agents(self):
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER)
        agent = assign_task(task, [])
        self.assertIsNone(agent)


# ══════════════════════════════════════════════════════════════════════════
#  CONFLICT RESOLUTION
# ══════════════════════════════════════════════════════════════════════════

class TestResolveConflicts(unittest.TestCase):
    """resolve_conflicts function."""

    def test_empty(self):
        self.assertIsNone(resolve_conflicts([]))

    def test_single_result(self):
        r = AgentResult(agent_id="a", output="x")
        result = resolve_conflicts([r])
        self.assertEqual(result.agent_id, "a")


# ══════════════════════════════════════════════════════════════════════════
#  SCHEDULER
# ══════════════════════════════════════════════════════════════════════════

class TestTaskScheduler(unittest.TestCase):
    """TaskScheduler."""

    def setUp(self):
        self.evidence = EvidenceLog("test-run")
        self.scheduler = TaskScheduler(self.evidence)

    def test_register_agent(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.scheduler.register_agent(agent)
        self.assertEqual(len(self.scheduler.agents), 1)

    def test_unregister_agent(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.scheduler.register_agent(agent)
        self.assertTrue(self.scheduler.unregister_agent(agent.agent_id))
        self.assertEqual(len(self.scheduler.agents), 0)

    def test_unregister_nonexistent(self):
        self.assertFalse(self.scheduler.unregister_agent("nope"))

    def test_get_agent(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.scheduler.register_agent(agent)
        found = self.scheduler.get_agent(agent.agent_id)
        self.assertEqual(found.agent_id, agent.agent_id)

    def test_ready_agents(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        self.assertEqual(len(self.scheduler.ready_agents()), 1)
        agent.cancel("test")
        self.assertEqual(len(self.scheduler.ready_agents()), 0)

    def test_execute_task_no_agent(self):
        task = AgentTask(description="fix bug", agent_role=AgentRole.DEVELOPER)
        result = self.scheduler.execute_task(task)
        self.assertEqual(result.status, AgentState.BLOCKED)
        self.assertIn("no suitable agent", result.error)

    def test_execute_task_deterministic(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        task = AgentTask(description="review code", agent_role=AgentRole.REVIEWER,
                         allowed_tools=("agent-diff-gate",))
        result = self.scheduler.execute_task(task, provider=NoneProvider())
        self.assertEqual(result.status, AgentState.COMPLETED)
        self.assertIn("analyzed", result.output.lower())

    def test_execute_task_blocked_no_provider(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        task = AgentTask(description="write code", agent_role=AgentRole.DEVELOPER,
                         allowed_tools=("agent-diff-gate",))
        result = self.scheduler.execute_task(task, provider=NoneProvider())
        # Developer needs AI but NoneProvider is unavailable
        self.assertEqual(result.status, AgentState.BLOCKED)

    def test_execute_sequential(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        tasks = [
            AgentTask(description="review 1", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
            AgentTask(description="review 2", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
        ]
        results = self.scheduler.execute_sequential(tasks, provider=NoneProvider())
        self.assertEqual(len(results), 2)

    def test_execute_sequential_stops_on_critical_failure(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        tasks = [
            AgentTask(description="fail", agent_role=AgentRole.DEVELOPER,
                      allowed_tools=("agent-diff-gate",), critical=True),
            AgentTask(description="never run", agent_role=AgentRole.DEVELOPER,
                      allowed_tools=("agent-diff-gate",)),
        ]
        results = self.scheduler.execute_sequential(tasks, provider=NoneProvider())
        # Second task should not have run
        self.assertEqual(len(results), 1)

    def test_execute_parallel_falls_back_to_sequential(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        tasks = [
            AgentTask(description="task 1", agent_role=AgentRole.REVIEWER,
                      allowed_tools=("agent-diff-gate",)),
        ]
        results = self.scheduler.execute_parallel(tasks, provider=NoneProvider())
        self.assertEqual(len(results), 1)

    def test_evidence_recorded(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        agent.initialize()
        agent.ready()
        self.scheduler.register_agent(agent)
        task = AgentTask(description="review", agent_role=AgentRole.REVIEWER,
                         allowed_tools=("agent-diff-gate",))
        self.scheduler.execute_task(task, provider=NoneProvider())
        self.assertGreater(len(self.evidence), 0)


# ══════════════════════════════════════════════════════════════════════════
#  SECURITY
# ══════════════════════════════════════════════════════════════════════════

class TestSchedulerSecurity(unittest.TestCase):
    """Security properties of the scheduler."""

    def test_no_shell_true(self):
        import ast, inspect
        source = inspect.getsource(TaskScheduler)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("scheduler uses shell=True")

    def test_agent_cannot_self_assign(self):
        """Agents cannot assign tasks to themselves."""
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        # Agent has no method to self-assign
        self.assertFalse(hasattr(agent, "self_assign"))
        self.assertFalse(hasattr(agent, "assign_self"))

    def test_scheduler_enforces_tool_permissions(self):
        """Scheduler rejects tasks requiring unauthorized tools."""
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        agent.initialize()
        agent.ready()
        scheduler = TaskScheduler()
        scheduler.register_agent(agent)
        # Reviewer cannot use agent-sandbox
        task = AgentTask(description="run in sandbox", agent_role=AgentRole.REVIEWER,
                         allowed_tools=("agent-sandbox",))
        result = scheduler.execute_task(task)
        self.assertEqual(result.status, AgentState.BLOCKED)


if __name__ == "__main__":
    unittest.main()
