"""Workflow definitions — steps, conditions, and predefined workflows.

A workflow is a named sequence of steps.  Each step invokes a tool
operation and may conditionally branch based on the result.

Design (from DESIGN.md §9, §22):
  - TOOL OUTPUT → INTERPRETATION → DECISION → NEXT ACTION
  - Not every task requires every stage
  - The orchestrator decides which stages are required

This module defines the *structure* of workflows.
The *execution* is handled by engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# ── Step outcome ─────────────────────────────────────────────────────────

class StepOutcome(str, Enum):
    """Possible outcomes of a single workflow step."""
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"


# ── Workflow step ────────────────────────────────────────────────────────

@dataclass
class Step:
    """A single step in a workflow.

    Attributes:
        name:        human-readable step name
        tool:        adapter tool name (e.g. "agent-error-log")
        operation:   adapter method name (e.g. "check")
        args:        positional args for the operation
        kwargs:      keyword args for the operation
        required:    if True, failure blocks the workflow
        gate:        if True, this step is a gate (failure = BLOCKED)
        description: human-readable description
    """
    name: str
    tool: str
    operation: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    required: bool = True
    gate: bool = False
    description: str = ""


# ── Conditional branch ───────────────────────────────────────────────────

@dataclass
class Branch:
    """Conditional next-step based on step outcome.

    After a step completes, the engine checks branches in order.
    The first matching branch determines the next step.
    If no branch matches, the workflow continues to the next
    sequential step (or completes).
    """
    on_status: StepOutcome
    goto: str  # name of the next step, or "END" / "BLOCK" / "FAIL"


# ── Workflow definition ──────────────────────────────────────────────────

@dataclass
class Workflow:
    """A complete workflow definition.

    Attributes:
        name:        workflow name
        description: what this workflow does
        steps:       ordered list of steps
        branches:    conditional branches keyed by step name
    """
    name: str
    description: str = ""
    steps: list[Step] = field(default_factory=list)
    branches: dict[str, list[Branch]] = field(default_factory=dict)

    def step_by_name(self, name: str) -> Step | None:
        """Look up a step by name."""
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def step_index(self, name: str) -> int:
        """Return the index of a step by name, or -1."""
        for i, s in enumerate(self.steps):
            if s.name == name:
                return i
        return -1

    def next_branch(self, step_name: str, outcome: StepOutcome) -> str | None:
        """Given a step name and its outcome, return the goto target or None."""
        for b in self.branches.get(step_name, []):
            if b.on_status == outcome:
                return b.goto
        return None


# ══════════════════════════════════════════════════════════════════════════
#  PREDEFINED WORKFLOWS
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_workflow() -> Workflow:
    """Standard session-start bootstrap: check errors + decisions."""
    return Workflow(
        name="bootstrap",
        description="Session start: verify error-log and decision-log health",
        steps=[
            Step(
                name="check_error_log",
                tool="agent-error-log",
                operation="check",
                required=True,
                gate=True,
                description="Validate the error log is healthy",
            ),
            Step(
                name="check_decision_log",
                tool="agent-decision-log",
                operation="check",
                required=True,
                gate=True,
                description="Validate the decision log is healthy",
            ),
        ],
    )


def development_workflow() -> Workflow:
    """Standard development workflow: bootstrap → check → gate → verify."""
    return Workflow(
        name="development",
        description="Development workflow: bootstrap, validate, gate, verify",
        steps=[
            Step(
                name="check_error_log",
                tool="agent-error-log",
                operation="check",
                required=True,
                gate=True,
                description="Validate error log",
            ),
            Step(
                name="check_decision_log",
                tool="agent-decision-log",
                operation="check",
                required=True,
                gate=True,
                description="Validate decision log",
            ),
            Step(
                name="has_open_decisions",
                tool="agent-decision-log",
                operation="has_open",
                required=False,
                description="Check for unresolved decisions",
            ),
            Step(
                name="list_diff_rules",
                tool="agent-diff-gate",
                operation="list_rules",
                required=False,
                description="List available diff-gate rules",
            ),
        ],
        branches={
            "check_error_log": [
                Branch(on_status=StepOutcome.FAIL, goto="BLOCK"),
            ],
            "check_decision_log": [
                Branch(on_status=StepOutcome.FAIL, goto="BLOCK"),
            ],
        },
    )


def doctor_workflow() -> Workflow:
    """Health-check workflow: verify all tools are available."""
    return Workflow(
        name="doctor",
        description="Verify all 7 tools are discovered and healthy",
        steps=[
            Step(
                name="check_error_log",
                tool="agent-error-log",
                operation="check",
                required=True,
                description="Health-check agent-error-log",
            ),
            Step(
                name="check_decision_log",
                tool="agent-decision-log",
                operation="check",
                required=True,
                description="Health-check agent-decision-log",
            ),
            Step(
                name="list_diff_rules",
                tool="agent-diff-gate",
                operation="list_rules",
                required=True,
                description="Health-check agent-diff-gate",
            ),
        ],
    )


# Registry of available workflows
WORKFLOW_REGISTRY: dict[str, Callable[[], Workflow]] = {
    "bootstrap": bootstrap_workflow,
    "development": development_workflow,
    "doctor": doctor_workflow,
}


def get_workflow(name: str) -> Workflow | None:
    """Return a workflow by name, or None if unknown."""
    factory = WORKFLOW_REGISTRY.get(name)
    return factory() if factory else None


def list_workflows() -> list[str]:
    """Return names of all registered workflows."""
    return sorted(WORKFLOW_REGISTRY.keys())
