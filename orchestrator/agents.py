"""Multi-agent model — identity, roles, permissions, lifecycle, results.

Agents are PROPOSERS.  They suggest actions within their permitted
scope.  The orchestrator decides.  Tools execute.

Agents never bypass:
  - PolicyEngine
  - WorkflowEngine
  - Tool permission checks
  - Safety gates
  - Sandbox requirements

Design: PHASE_6_MULTI_AGENT_DESIGN.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ── Agent roles ──────────────────────────────────────────────────────────

class AgentRole(str, Enum):
    """Predefined agent roles with fixed permission profiles."""
    PLANNER = "planner"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SECURITY = "security"
    RESEARCHER = "researcher"
    DOCUMENTER = "documenter"


# ── Agent lifecycle states ───────────────────────────────────────────────

class AgentState(str, Enum):
    """Lifecycle states for an agent within a run."""
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


TERMINAL_AGENT_STATES = frozenset({
    AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED,
})

_AGENT_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.CREATED:     {AgentState.INITIALIZING, AgentState.BLOCKED, AgentState.CANCELLED},
    AgentState.INITIALIZING: {AgentState.READY, AgentState.FAILED, AgentState.BLOCKED, AgentState.CANCELLED},
    AgentState.READY:       {AgentState.ASSIGNED, AgentState.CANCELLED},
    AgentState.ASSIGNED:    {AgentState.RUNNING, AgentState.CANCELLED},
    AgentState.RUNNING:     {AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED},
    AgentState.COMPLETED:   set(),
    AgentState.FAILED:      set(),
    AgentState.BLOCKED:     set(),
    AgentState.CANCELLED:   set(),
}


def is_valid_agent_transition(current: AgentState, target: AgentState) -> bool:
    """Return True if the transition is allowed."""
    return target in _AGENT_TRANSITIONS.get(current, set())


class InvalidAgentTransition(Exception):
    """Raised on invalid agent lifecycle transition."""
    pass


# ── Agent identity ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentIdentity:
    """Immutable identity for an agent.

    Created once, never modified.
    """
    agent_id: str
    role: AgentRole
    display_name: str
    provider: str = "none"
    model: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            # frozen dataclass — use object.__setattr__
            object.__setattr__(
                self, "created_at",
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )


def create_identity(
    role: AgentRole,
    display_name: str,
    provider: str = "none",
    model: str = "",
) -> AgentIdentity:
    """Factory: create a new agent identity with auto-generated ID."""
    agent_id = f"agent-{role.value}-{uuid.uuid4().hex[:6]}"
    return AgentIdentity(
        agent_id=agent_id,
        role=role,
        display_name=display_name,
        provider=provider,
        model=model,
    )


# ── Agent permissions ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentPermissions:
    """Fixed permissions for an agent role.

    Immutable — agents cannot modify their own permissions.
    """
    can_read: bool = True
    can_write: bool = False
    can_execute: bool = False
    can_use_sandbox: bool = False
    can_use_tools: tuple[str, ...] = ()
    can_approve: bool = False
    can_promote_memory: bool = False
    max_tokens: int = 4096
    timeout_seconds: float = 60.0


# ── Default permissions by role ──────────────────────────────────────────

_DEFAULT_PERMISSIONS: dict[AgentRole, AgentPermissions] = {
    AgentRole.PLANNER: AgentPermissions(
        can_read=True, can_write=False, can_execute=False,
        can_use_sandbox=False,
        can_use_tools=("agent-error-log", "agent-decision-log", "agent-memory"),
        max_tokens=4096, timeout_seconds=30.0,
    ),
    AgentRole.DEVELOPER: AgentPermissions(
        can_read=True, can_write=True, can_execute=True,
        can_use_sandbox=True,
        can_use_tools=(
            "agent-error-log", "agent-decision-log", "agent-log-ai",
            "agent-memory", "agent-blame", "agent-diff-gate", "agent-sandbox",
        ),
        max_tokens=8192, timeout_seconds=120.0,
    ),
    AgentRole.REVIEWER: AgentPermissions(
        can_read=True, can_write=False, can_execute=False,
        can_use_sandbox=False,
        can_use_tools=("agent-diff-gate", "agent-blame", "agent-error-log"),
        max_tokens=4096, timeout_seconds=60.0,
    ),
    AgentRole.TESTER: AgentPermissions(
        can_read=True, can_write=True, can_execute=True,
        can_use_sandbox=True,
        can_use_tools=("agent-sandbox", "agent-error-log"),
        max_tokens=4096, timeout_seconds=120.0,
    ),
    AgentRole.SECURITY: AgentPermissions(
        can_read=True, can_write=False, can_execute=False,
        can_use_sandbox=True,
        can_use_tools=(
            "agent-diff-gate", "agent-blame", "agent-sandbox", "agent-memory",
        ),
        max_tokens=4096, timeout_seconds=60.0,
    ),
    AgentRole.RESEARCHER: AgentPermissions(
        can_read=True, can_write=False, can_execute=False,
        can_use_sandbox=False,
        can_use_tools=("agent-blame", "agent-memory", "agent-log-ai"),
        max_tokens=4096, timeout_seconds=60.0,
    ),
    AgentRole.DOCUMENTER: AgentPermissions(
        can_read=True, can_write=True, can_execute=False,
        can_use_sandbox=False,
        can_use_tools=("agent-error-log", "agent-decision-log"),
        max_tokens=4096, timeout_seconds=30.0,
    ),
}


def get_default_permissions(role: AgentRole) -> AgentPermissions:
    """Return the default permissions for *role*."""
    return _DEFAULT_PERMISSIONS.get(role, AgentPermissions(can_read=False))


# ── Authority hierarchy ──────────────────────────────────────────────────

_AUTHORITY_ORDER: dict[AgentRole, int] = {
    AgentRole.SECURITY: 100,     # highest for safety decisions
    AgentRole.REVIEWER: 80,
    AgentRole.DEVELOPER: 60,
    AgentRole.TESTER: 60,
    AgentRole.PLANNER: 40,
    AgentRole.RESEARCHER: 20,
    AgentRole.DOCUMENTER: 10,
}


def authority_level(role: AgentRole) -> int:
    """Return the authority level for *role* (higher = more authority)."""
    return _AUTHORITY_ORDER.get(role, 0)


# ── Agent task ───────────────────────────────────────────────────────────

@dataclass
class AgentTask:
    """A task assigned to an agent."""
    task_id: str = ""
    description: str = ""
    agent_role: AgentRole = AgentRole.DEVELOPER
    allowed_tools: tuple[str, ...] = ()
    context: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    max_retries: int = 0
    critical: bool = False  # if True, failure blocks the workflow

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"task-{uuid.uuid4().hex[:8]}"


# ── Agent result ─────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Structured result from an agent task execution."""
    agent_id: str = ""
    task_id: str = ""
    status: AgentState = AgentState.COMPLETED
    output: str = ""
    proposed_actions: list[dict[str, str]] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0
    duration: float = 0.0
    tokens_used: int = 0
    error: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Agent class ──────────────────────────────────────────────────────────

class Agent:
    """An agent with identity, permissions, and lifecycle.

    Usage:
        agent = Agent.create(AgentRole.DEVELOPER, "Dev Agent")
        agent.initialize()
        agent.assign(task)
        result = agent.execute(context)
    """

    def __init__(
        self,
        identity: AgentIdentity,
        permissions: AgentPermissions | None = None,
    ):
        self._identity = identity
        self._permissions = permissions or get_default_permissions(identity.role)
        self._state = AgentState.CREATED
        self._task: AgentTask | None = None
        self._result: AgentResult | None = None

    @classmethod
    def create(
        cls,
        role: AgentRole,
        display_name: str,
        provider: str = "none",
        model: str = "",
        permissions: AgentPermissions | None = None,
    ) -> Agent:
        """Factory: create an agent with a new identity."""
        identity = create_identity(role, display_name, provider, model)
        return cls(identity, permissions)

    @property
    def identity(self) -> AgentIdentity:
        return self._identity

    @property
    def permissions(self) -> AgentPermissions:
        return self._permissions

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def task(self) -> AgentTask | None:
        return self._task

    @property
    def result(self) -> AgentResult | None:
        return self._result

    @property
    def agent_id(self) -> str:
        return self._identity.agent_id

    @property
    def role(self) -> AgentRole:
        return self._identity.role

    # ── Lifecycle ────────────────────────────────────────────────────

    def _transition(self, target: AgentState) -> None:
        if not is_valid_agent_transition(self._state, target):
            raise InvalidAgentTransition(
                f"agent {self.agent_id}: cannot transition "
                f"from {self._state.value} to {target.value}"
            )
        self._state = target

    def initialize(self) -> None:
        """Move to INITIALIZING state."""
        self._transition(AgentState.INITIALIZING)

    def ready(self) -> None:
        """Move to READY state."""
        self._transition(AgentState.READY)

    def assign(self, task: AgentTask) -> None:
        """Assign a task to this agent."""
        self._transition(AgentState.ASSIGNED)
        self._task = task

    def start_running(self) -> None:
        """Begin execution."""
        self._transition(AgentState.RUNNING)

    def complete(self, result: AgentResult) -> None:
        """Mark as completed with a result."""
        self._transition(AgentState.COMPLETED)
        self._result = result

    def fail(self, error: str = "") -> None:
        """Mark as failed."""
        self._transition(AgentState.FAILED)
        self._result = AgentResult(
            agent_id=self.agent_id,
            task_id=self._task.task_id if self._task else "",
            status=AgentState.FAILED,
            error=error,
        )

    def block(self) -> None:
        """Mark as blocked (policy prevented execution)."""
        self._transition(AgentState.BLOCKED)

    def cancel(self, reason: str = "") -> None:
        """Cancel the agent."""
        self._transition(AgentState.CANCELLED)
        if self._result is None:
            self._result = AgentResult(
                agent_id=self.agent_id,
                task_id=self._task.task_id if self._task else "",
                status=AgentState.CANCELLED,
                error=f"cancelled: {reason}" if reason else "cancelled",
            )

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_AGENT_STATES

    # ── Permission checks ────────────────────────────────────────────

    def can_use_tool(self, tool_name: str) -> bool:
        """Return True if this agent is permitted to use *tool_name*."""
        return tool_name in self._permissions.can_use_tools

    def can_perform(self, action: str) -> bool:
        """Check a general capability: read, write, execute, approve."""
        mapping = {
            "read": self._permissions.can_read,
            "write": self._permissions.can_write,
            "execute": self._permissions.can_execute,
            "sandbox": self._permissions.can_use_sandbox,
            "approve": self._permissions.can_approve,
            "promote_memory": self._permissions.can_promote_memory,
        }
        return mapping.get(action, False)
