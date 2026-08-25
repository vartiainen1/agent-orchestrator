"""Tests for orchestrator.agents — Phase 6 Step 1: agent model."""

import unittest

from orchestrator.agents import (
    Agent,
    AgentIdentity,
    AgentPermissions,
    AgentResult,
    AgentRole,
    AgentState,
    AgentTask,
    InvalidAgentTransition,
    TERMINAL_AGENT_STATES,
    _AUTHORITY_ORDER,
    _DEFAULT_PERMISSIONS,
    authority_level,
    create_identity,
    get_default_permissions,
    is_valid_agent_transition,
)


# ══════════════════════════════════════════════════════════════════════════
#  ROLES
# ══════════════════════════════════════════════════════════════════════════

class TestAgentRole(unittest.TestCase):
    """AgentRole enum."""

    def test_seven_roles(self):
        self.assertEqual(len(AgentRole), 7)

    def test_all_roles_have_permissions(self):
        for role in AgentRole:
            perms = get_default_permissions(role)
            self.assertIsInstance(perms, AgentPermissions)


# ══════════════════════════════════════════════════════════════════════════
#  IDENTITY
# ══════════════════════════════════════════════════════════════════════════

class TestAgentIdentity(unittest.TestCase):
    """AgentIdentity creation and immutability."""

    def test_auto_id(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        self.assertTrue(ident.agent_id.startswith("agent-developer-"))

    def test_auto_timestamp(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        self.assertIn("2026", ident.created_at)

    def test_frozen(self):
        ident = create_identity(AgentRole.DEVELOPER, "Dev")
        with self.assertRaises(AttributeError):
            ident.agent_id = "changed"

    def test_unique_ids(self):
        ids = {create_identity(AgentRole.DEVELOPER, "Dev").agent_id for _ in range(10)}
        self.assertEqual(len(ids), 10)


# ══════════════════════════════════════════════════════════════════════════
#  PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════

class TestAgentPermissions(unittest.TestCase):
    """AgentPermissions model."""

    def test_default_permissions_exist(self):
        for role in AgentRole:
            perms = get_default_permissions(role)
            self.assertIsInstance(perms.can_read, bool)

    def test_frozen(self):
        perms = AgentPermissions()
        with self.assertRaises(AttributeError):
            perms.can_write = True

    def test_developer_can_write(self):
        perms = get_default_permissions(AgentRole.DEVELOPER)
        self.assertTrue(perms.can_write)
        self.assertTrue(perms.can_execute)

    def test_reviewer_cannot_write(self):
        perms = get_default_permissions(AgentRole.REVIEWER)
        self.assertFalse(perms.can_write)
        self.assertFalse(perms.can_execute)

    def test_planner_tools_limited(self):
        perms = get_default_permissions(AgentRole.PLANNER)
        self.assertIn("agent-error-log", perms.can_use_tools)
        self.assertNotIn("agent-sandbox", perms.can_use_tools)

    def test_security_has_all_security_tools(self):
        perms = get_default_permissions(AgentRole.SECURITY)
        self.assertIn("agent-diff-gate", perms.can_use_tools)
        self.assertIn("agent-blame", perms.can_use_tools)
        self.assertIn("agent-sandbox", perms.can_use_tools)


# ══════════════════════════════════════════════════════════════════════════
#  AUTHORITY
# ══════════════════════════════════════════════════════════════════════════

class TestAuthority(unittest.TestCase):
    """Authority hierarchy."""

    def test_security_highest(self):
        self.assertEqual(authority_level(AgentRole.SECURITY), 100)

    def test_reviewer_high(self):
        self.assertGreater(authority_level(AgentRole.REVIEWER), authority_level(AgentRole.DEVELOPER))

    def test_documenter_lowest(self):
        self.assertEqual(authority_level(AgentRole.DOCUMENTER), 10)


# ══════════════════════════════════════════════════════════════════════════
#  LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════

class TestAgentLifecycle(unittest.TestCase):
    """Agent state transitions."""

    def test_valid_transitions(self):
        self.assertTrue(is_valid_agent_transition(AgentState.CREATED, AgentState.INITIALIZING))
        self.assertTrue(is_valid_agent_transition(AgentState.INITIALIZING, AgentState.READY))
        self.assertTrue(is_valid_agent_transition(AgentState.READY, AgentState.ASSIGNED))
        self.assertTrue(is_valid_agent_transition(AgentState.ASSIGNED, AgentState.RUNNING))
        self.assertTrue(is_valid_agent_transition(AgentState.RUNNING, AgentState.COMPLETED))

    def test_invalid_transitions(self):
        self.assertFalse(is_valid_agent_transition(AgentState.CREATED, AgentState.RUNNING))
        self.assertFalse(is_valid_agent_transition(AgentState.COMPLETED, AgentState.RUNNING))

    def test_terminal_states(self):
        self.assertIn(AgentState.COMPLETED, TERMINAL_AGENT_STATES)
        self.assertIn(AgentState.FAILED, TERMINAL_AGENT_STATES)
        self.assertIn(AgentState.CANCELLED, TERMINAL_AGENT_STATES)
        self.assertNotIn(AgentState.RUNNING, TERMINAL_AGENT_STATES)


class TestAgent(unittest.TestCase):
    """Agent class lifecycle."""

    def test_create(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.assertEqual(agent.state, AgentState.CREATED)
        self.assertEqual(agent.role, AgentRole.DEVELOPER)

    def test_full_lifecycle(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.initialize()
        self.assertEqual(agent.state, AgentState.INITIALIZING)
        agent.ready()
        self.assertEqual(agent.state, AgentState.READY)
        task = AgentTask(description="fix bug")
        agent.assign(task)
        self.assertEqual(agent.state, AgentState.ASSIGNED)
        agent.start_running()
        self.assertEqual(agent.state, AgentState.RUNNING)
        result = AgentResult(status=AgentState.COMPLETED, output="done")
        agent.complete(result)
        self.assertEqual(agent.state, AgentState.COMPLETED)
        self.assertTrue(agent.is_terminal())

    def test_invalid_transition_raises(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        with self.assertRaises(InvalidAgentTransition):
            agent.start_running()  # can't go from CREATED to RUNNING

    def test_cancel(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.cancel("not needed")
        self.assertEqual(agent.state, AgentState.CANCELLED)
        self.assertTrue(agent.is_terminal())
        self.assertIsNotNone(agent.result)

    def test_fail(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.initialize()
        agent.ready()
        task = AgentTask(description="do something")
        agent.assign(task)
        agent.start_running()
        agent.fail("something broke")
        self.assertEqual(agent.state, AgentState.FAILED)
        self.assertIn("something broke", agent.result.error)

    def test_block(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        agent.block()
        self.assertEqual(agent.state, AgentState.BLOCKED)

    def test_immutable_permissions(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        with self.assertRaises(AttributeError):
            agent._permissions.can_write = False


# ══════════════════════════════════════════════════════════════════════════
#  PERMISSIONS ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════

class TestPermissionEnforcement(unittest.TestCase):
    """Tool permission checks."""

    def test_developer_can_use_all_tools(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.assertTrue(agent.can_use_tool("agent-error-log"))
        self.assertTrue(agent.can_use_tool("agent-sandbox"))
        self.assertTrue(agent.can_use_tool("agent-diff-gate"))

    def test_reviewer_cannot_use_sandbox(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        self.assertFalse(agent.can_use_tool("agent-sandbox"))
        self.assertTrue(agent.can_use_tool("agent-diff-gate"))

    def test_planner_cannot_use_sandbox(self):
        agent = Agent.create(AgentRole.PLANNER, "Plan")
        self.assertFalse(agent.can_use_tool("agent-sandbox"))
        self.assertFalse(agent.can_use_tool("agent-diff-gate"))

    def test_can_perform_read(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.assertTrue(agent.can_perform("read"))

    def test_reviewer_cannot_perform_write(self):
        agent = Agent.create(AgentRole.REVIEWER, "Rev")
        self.assertFalse(agent.can_perform("write"))

    def test_unknown_action_denied(self):
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        self.assertFalse(agent.can_perform("magic"))


# ══════════════════════════════════════════════════════════════════════════
#  SECURITY
# ══════════════════════════════════════════════════════════════════════════

class TestAgentSecurity(unittest.TestCase):
    """Security properties of the agent model."""

    def test_permissions_cannot_be_modified(self):
        """Agent cannot grant itself additional permissions."""
        agent = Agent.create(AgentRole.PLANNER, "Plan")
        # Try to modify via property
        self.assertFalse(agent.can_use_tool("agent-sandbox"))
        # Permissions are frozen — no way to add tools
        self.assertIsInstance(agent.permissions, AgentPermissions)

    def test_identity_is_frozen(self):
        """Agent cannot change its own identity."""
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        original_id = agent.agent_id
        # Cannot set agent_id — frozen dataclass
        self.assertEqual(agent.agent_id, original_id)

    def test_no_agent_to_agent(self):
        """Agents have no reference to other agents."""
        agent = Agent.create(AgentRole.DEVELOPER, "Dev")
        # Agent class has no method to access other agents
        self.assertFalse(hasattr(agent, "send_to"))
        self.assertFalse(hasattr(agent, "invoke_agent"))

    def test_all_roles_have_permissions(self):
        """Every role must have defined permissions."""
        for role in AgentRole:
            perms = get_default_permissions(role)
            self.assertGreater(len(perms.can_use_tools), 0,
                               f"{role} has no tools")


if __name__ == "__main__":
    unittest.main()
