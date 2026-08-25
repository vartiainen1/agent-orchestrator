"""Workflow state model.

Defines the explicit states a workflow run can be in, and the run-state
dataclass that tracks everything about a single orchestration execution.

Design (from DESIGN.md §34):
  - State transitions must be explicit
  - Invalid transitions must fail safely
  - States: CREATED, BOOTSTRAPPING, PLANNING, EXECUTING, BLOCKED,
    VERIFYING, COMPLETED, FAILED, CANCELLED
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ── Workflow phase ───────────────────────────────────────────────────────

class Phase(str, Enum):
    """Distinct phases a workflow run progresses through."""
    CREATED = "CREATED"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    CHECKING = "CHECKING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    GATING = "GATING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Valid transitions: from -> set of allowed destinations.
_VALID_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.CREATED:     {Phase.BOOTSTRAPPING, Phase.CANCELLED},
    Phase.BOOTSTRAPPING: {Phase.CHECKING, Phase.FAILED, Phase.CANCELLED},
    Phase.CHECKING:    {Phase.PLANNING, Phase.EXECUTING, Phase.BLOCKED, Phase.FAILED, Phase.CANCELLED},
    Phase.PLANNING:    {Phase.EXECUTING, Phase.BLOCKED, Phase.FAILED, Phase.CANCELLED},
    Phase.EXECUTING:   {Phase.GATING, Phase.VERIFYING, Phase.COMPLETED, Phase.BLOCKED, Phase.FAILED, Phase.CANCELLED},
    Phase.GATING:      {Phase.EXECUTING, Phase.VERIFYING, Phase.COMPLETED, Phase.BLOCKED, Phase.FAILED, Phase.CANCELLED},
    Phase.VERIFYING:   {Phase.COMPLETED, Phase.BLOCKED, Phase.FAILED, Phase.CANCELLED},
    Phase.COMPLETED:   set(),  # terminal
    Phase.BLOCKED:     {Phase.EXECUTING, Phase.CANCELLED},  # can retry after fix
    Phase.FAILED:      {Phase.CANCELLED},  # terminal-ish
    Phase.CANCELLED:   set(),  # terminal
}

TERMINAL_PHASES = frozenset({Phase.COMPLETED, Phase.CANCELLED})


def is_valid_transition(current: Phase, target: Phase) -> bool:
    """Return True if *target* is reachable from *current*."""
    return target in _VALID_TRANSITIONS.get(current, set())


# ── Tool result summary ─────────────────────────────────────────────────

@dataclass
class ToolCall:
    """Record of a single tool invocation within a run."""
    tool_name: str
    operation: str
    args: list[str] = field(default_factory=list)
    exit_code: int = -1
    status: str = ""  # ResultStatus value
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timestamp: str = ""
    error: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Run state ────────────────────────────────────────────────────────────

@dataclass
class RunState:
    """Complete state of one workflow execution.

    Append-only: new records are added, never silently overwritten.
    """
    run_id: str = ""
    workflow_name: str = ""
    project_dir: str = ""
    workspace_dir: str = ""
    mode: str = "solo"
    phase: Phase = Phase.CREATED
    started_at: str = ""
    ended_at: str = ""
    final_status: str = ""  # PASS / FAIL / BLOCKED / UNSUPPORTED

    # Tool execution history
    tool_calls: list[ToolCall] = field(default_factory=list)

    # Decision/observation log
    observations: list[str] = field(default_factory=list)

    # Gate results
    gate_results: list[dict[str, str]] = field(default_factory=list)

    # Policy decisions
    policy_decisions: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        if not self.run_id:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            short = uuid.uuid4().hex[:6]
            self.run_id = f"RUN-{ts}-{short}"
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Phase transitions ────────────────────────────────────────────

    def transition(self, target: Phase) -> None:
        """Attempt a phase transition.  Raises on invalid transition."""
        if not is_valid_transition(self.phase, target):
            raise InvalidTransitionError(
                f"cannot transition from {self.phase.value} to {target.value}"
            )
        self.phase = target

    def is_terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    # ── Recording ────────────────────────────────────────────────────

    def record_tool_call(self, call: ToolCall) -> None:
        self.tool_calls.append(call)

    def observe(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.observations.append(f"[{ts}] {message}")

    def record_gate(self, gate_name: str, passed: bool, detail: str = "") -> None:
        self.gate_results.append({
            "gate": gate_name,
            "passed": str(passed),
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def finalize(self, status: str) -> None:
        self.final_status = status
        self.ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Errors ───────────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when a workflow state transition is not allowed."""
    pass
