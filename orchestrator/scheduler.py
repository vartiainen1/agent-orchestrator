"""Task scheduler — assigns tasks to agents and manages execution.

The scheduler is the bridge between agent tasks and agent execution.
It handles:
  - Task assignment to appropriate agents
  - Sequential execution with full governance
  - Parallel execution with isolation (designed, sequential-first)
  - Result aggregation
  - Conflict resolution via authority hierarchy
  - Timeout enforcement
  - Cancellation
  - Failure handling

Design: PHASE_6_MULTI_AGENT_DESIGN.md
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from . import olog as log
from .agents import (
    Agent,
    AgentIdentity,
    AgentPermissions,
    AgentResult,
    AgentRole,
    AgentState,
    AgentTask,
    InvalidAgentTransition,
    authority_level,
)
from .evidence import EvidenceLog
from .providers import AIProvider, NoneProvider, ProviderResponse, ProviderStatus


# ── Scheduler mode ───────────────────────────────────────────────────────

class SchedulerMode(str, Enum):
    """Execution mode for the scheduler."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


# ── Task assignment ──────────────────────────────────────────────────────

def assign_task(
    task: AgentTask,
    agents: list[Agent],
) -> Agent | None:
    """Find the best available agent for *task*.

    Selection criteria:
      1. Agent must be in READY state
      2. Agent role must match task's required role
      3. Agent must have permission for the task's tools
      4. Highest authority wins ties

    Returns None if no suitable agent is found.
    """
    candidates: list[tuple[int, Agent]] = []

    for agent in agents:
        if agent.state != AgentState.READY:
            continue
        if agent.role != task.agent_role:
            continue
        # Check tool permissions
        for tool in task.allowed_tools:
            if not agent.can_use_tool(tool):
                break
        else:
            # All tools permitted
            candidates.append((authority_level(agent.role), agent))

    if not candidates:
        return None

    # Sort by authority descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ── Conflict resolution ─────────────────────────────────────────────────

def resolve_conflicts(
    results: list[AgentResult],
) -> AgentResult | None:
    """Given multiple agent results with conflicting proposals,
    return the result from the highest-authority agent.

    Returns None if no results.
    """
    if not results:
        return None
    # In Phase 6, we simply return the first result.
    # Future: compare proposed_actions and resolve by authority.
    return results[0]


# ── Task scheduler ───────────────────────────────────────────────────────

class TaskScheduler:
    """Manages task assignment and execution for multiple agents.

    Usage:
        scheduler = TaskScheduler(evidence)
        scheduler.register_agent(agent)
        result = scheduler.execute_task(task, provider)
    """

    def __init__(self, evidence: EvidenceLog | None = None):
        self._agents: list[Agent] = []
        self._evidence = evidence
        self._results: list[AgentResult] = []

    @property
    def agents(self) -> list[Agent]:
        return list(self._agents)

    @property
    def results(self) -> list[AgentResult]:
        return list(self._results)

    def register_agent(self, agent: Agent) -> None:
        """Register an agent with the scheduler."""
        self._agents.append(agent)

    def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent by ID.  Returns True if found."""
        for i, a in enumerate(self._agents):
            if a.agent_id == agent_id:
                self._agents.pop(i)
                return True
        return False

    def get_agent(self, agent_id: str) -> Agent | None:
        """Find an agent by ID."""
        for a in self._agents:
            if a.agent_id == agent_id:
                return a
        return None

    def ready_agents(self) -> list[Agent]:
        """Return agents in READY state."""
        return [a for a in self._agents if a.state == AgentState.READY]

    # ── Task execution ───────────────────────────────────────────────

    def execute_task(
        self,
        task: AgentTask,
        provider: AIProvider | None = None,
        context: dict[str, str] | None = None,
    ) -> AgentResult:
        """Assign and execute a single task.

        1. Find a suitable agent
        2. Initialize and assign the task
        3. Invoke the provider (if needed)
        4. Collect the result
        5. Record evidence
        """
        provider = provider or NoneProvider()
        ctx = context or {}

        # ── Assign ───────────────────────────────────────────────────
        agent = assign_task(task, self._agents)
        if agent is None:
            result = AgentResult(
                task_id=task.task_id,
                status=AgentState.BLOCKED,
                error="no suitable agent available",
            )
            self._record_evidence(task, result, "no_agent")
            return result

        # ── Initialize ───────────────────────────────────────────────
        try:
            agent.initialize()
            agent.ready()
        except InvalidAgentTransition:
            pass  # already initialized

        agent.assign(task)
        agent.start_running()

        evidence_detail = (
            f"agent={agent.agent_id} role={agent.role.value} "
            f"task={task.task_id}"
        )
        if self._evidence is not None:
            self._evidence.record(
                action="agent_task_started",
                tool=f"agent:{agent.agent_id}",
                detail=evidence_detail,
            )
        log.info(f"  agent {agent.agent_id} running task {task.task_id}", component="scheduler")

        # ── Execute ──────────────────────────────────────────────────
        start = time.monotonic()
        try:
            if task.timeout > 0:
                result = self._invoke_agent(
                    agent, task, provider, ctx, task.timeout,
                )
            else:
                result = self._invoke_agent(
                    agent, task, provider, ctx, 60.0,
                )
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            result = AgentResult(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                status=AgentState.FAILED,
                duration=duration,
                error=f"agent exception: {exc}",
            )

        # ── Finalize ─────────────────────────────────────────────────
        if result.status == AgentState.COMPLETED:
            agent.complete(result)
        elif result.status == AgentState.FAILED:
            agent.fail(result.error)
        else:
            agent.fail(result.error or "unknown failure")

        self._results.append(result)
        self._record_evidence(task, result, "completed")

        log.info(
            f"  agent {agent.agent_id} finished: {result.status.value} "
            f"({result.duration:.1f}s)",
            component="scheduler",
        )

        return result

    def _invoke_agent(
        self,
        agent: Agent,
        task: AgentTask,
        provider: AIProvider,
        context: dict[str, str],
        timeout: float,
    ) -> AgentResult:
        """Invoke the agent through its provider."""
        start = time.monotonic()

        # Build prompt from task + context
        prompt = self._build_prompt(task, context)

        # Check if agent needs AI or is deterministic
        needs_ai = agent.can_perform("execute") or agent.role in (
            AgentRole.DEVELOPER, AgentRole.PLANNER,
        )

        if needs_ai and isinstance(provider, NoneProvider):
            duration = time.monotonic() - start
            return AgentResult(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                status=AgentState.BLOCKED,
                duration=duration,
                error="AI provider unavailable",
            )

        if not needs_ai:
            # Deterministic agent — produce a simple result
            duration = time.monotonic() - start
            return AgentResult(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                status=AgentState.COMPLETED,
                output=f"[{agent.role.value}] analyzed: {task.description}",
                reasoning=f"deterministic analysis by {agent.role.value}",
                confidence=0.8,
                duration=duration,
            )

        # Call provider
        model = agent._identity.model if agent._identity.model else ""
        response = provider.complete(
            prompt,
            model=model,
            max_tokens=agent.permissions.max_tokens,
            timeout=timeout,
        )

        duration = time.monotonic() - start

        if not response.ok:
            return AgentResult(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                status=AgentState.FAILED,
                duration=duration,
                error=response.error or "provider returned no result",
            )

        return AgentResult(
            agent_id=agent.agent_id,
            task_id=task.task_id,
            status=AgentState.COMPLETED,
            output=response.text,
            reasoning=f"AI completion via {provider.name}",
            tokens_used=response.tokens_used,
            duration=duration,
        )

    def _build_prompt(
        self,
        task: AgentTask,
        context: dict[str, str],
    ) -> str:
        """Build a prompt from task description and context."""
        parts = [f"Task: {task.description}"]
        if context:
            parts.append("Context:")
            for k, v in context.items():
                parts.append(f"  {k}: {v}")
        return "\n".join(parts)

    def _record_evidence(
        self,
        task: AgentTask,
        result: AgentResult,
        phase: str,
    ) -> None:
        """Record task execution in evidence."""
        if self._evidence is not None:
            self._evidence.record(
                action=f"agent_task_{phase}",
                tool=f"agent:{result.agent_id}",
                operation=task.task_id,
                status=result.status.value,
                duration=result.duration,
                detail=result.error or f"tokens={result.tokens_used}",
            )

    # ── Sequential execution ─────────────────────────────────────────

    def execute_sequential(
        self,
        tasks: list[AgentTask],
        provider: AIProvider | None = None,
        context: dict[str, str] | None = None,
    ) -> list[AgentResult]:
        """Execute tasks one at a time, in order."""
        results: list[AgentResult] = []
        for task in tasks:
            result = self.execute_task(task, provider, context)
            results.append(result)
            # If critical task fails, stop
            if task.critical and result.status != AgentState.COMPLETED:
                log.warn(
                    f"critical task {task.task_id} failed; stopping sequence",
                    component="scheduler",
                )
                break
        return results

    # ── Parallel execution (sequential fallback) ─────────────────────

    def execute_parallel(
        self,
        tasks: list[AgentTask],
        provider: AIProvider | None = None,
        context: dict[str, str] | None = None,
    ) -> list[AgentResult]:
        """Execute tasks in parallel (currently sequential fallback).

        Phase 6 implements sequential-first.  The interface supports
        parallel; the implementation executes sequentially for safety.
        Future phases can add true threading.
        """
        # Sequential fallback — same governance, same evidence
        return self.execute_sequential(tasks, provider, context)
