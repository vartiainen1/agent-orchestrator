"""Workflow engine — executes workflows using the adapter layer.

The engine is the core coordinator.  It:
  1. Takes a Workflow definition
  2. Creates a RunState
  3. Executes steps through adapters
  4. Interprets results
  5. Makes decisions (branch or continue)
  6. Enforces gates
  7. Records evidence
  8. Produces a final report

Design (from DESIGN.md §22):
  TOOL OUTPUT → INTERPRETATION → DECISION → NEXT ACTION

Security:
  - Never bypasses adapter layer
  - Never executes tool code directly
  - Never uses shell=True
  - Preserves all raw evidence
  - Fails closed on invalid state
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import olog as log
from .adapter import BaseAdapter, ToolResult, ResultStatus, get_adapter
from .discovery import ToolStatus, discover_all
from .evidence import EvidenceLog, redact
from .state import (
    Phase,
    RunState,
    ToolCall,
    InvalidTransitionError,
)
from .workflow import Step, StepOutcome, Workflow
from .policy import Policy, Outcome


# ── Mapping: ResultStatus → StepOutcome ──────────────────────────────────

def _to_step_outcome(result: ToolResult) -> StepOutcome:
    """Map a ToolResult status to a StepOutcome for branching."""
    mapping = {
        ResultStatus.PASS: StepOutcome.PASS,
        ResultStatus.FAIL: StepOutcome.FAIL,
        ResultStatus.BLOCKED: StepOutcome.BLOCKED,
        ResultStatus.UNSUPPORTED: StepOutcome.UNSUPPORTED,
        ResultStatus.ERROR: StepOutcome.FAIL,
        ResultStatus.INVALID: StepOutcome.FAIL,
    }
    return mapping.get(result.status, StepOutcome.FAIL)


# ── Workflow Engine ──────────────────────────────────────────────────────

class WorkflowEngine:
    """Executes a Workflow definition using adapters.

    Usage:
        engine = WorkflowEngine(workspace, project_dir)
        result = engine.run(workflow)

    Persistence (Phase 8A):
        When persist_dir is provided, run state and evidence are
        automatically saved to disk on transitions and completion.
    """

    def __init__(
        self,
        workspace: Path,
        project_dir: Path | None = None,
        persist_dir: Path | None = None,
    ):
        self.workspace = workspace
        self.project_dir = project_dir or workspace
        self.persist_dir = persist_dir

    def run(self, workflow: Workflow, *, policy: Policy | None = None,
            max_steps: int = 50) -> RunState:
        """Execute a workflow and return the final RunState.

        The engine processes steps sequentially, checking branches
        after each step.  Gates stop the workflow on failure.
        """
        state = RunState(
            workflow_name=workflow.name,
            project_dir=str(self.project_dir),
            workspace_dir=str(self.workspace),
            mode=policy.mode.value if policy else "solo",
        )
        evidence = EvidenceLog(state.run_id, persist_dir=self.persist_dir)

        # Persist initial state
        self._persist_state(state)

        evidence.record(action="workflow_started", detail=workflow.name)
        log.info(f"workflow '{workflow.name}' started  run_id={state.run_id}", component="engine")

        # ── Pre-flight policy check ─────────────────────────────────
        if policy:
            # Discover available tools for pre-flight check
            available = set()
            try:
                tools = discover_all(self.workspace)
                available = {t.name for t in tools if t.status == ToolStatus.AVAILABLE}
            except Exception:  # noqa: BLE001
                pass
            pre_decisions = policy.pre_flight(available_tools=available)
            for d in pre_decisions:
                state.policy_decisions.append({
                    "rule": d.rule, "outcome": d.outcome.value,
                    "reason": d.reason, "mandatory": str(d.mandatory),
                })
                evidence.record(
                    action="policy_decision",
                    detail=f"rule={d.rule} outcome={d.outcome.value} reason={d.reason}",
                )
                log.info(f"  policy: {d.rule} -> {d.outcome.value}", component="engine")

            # If any DENY in pre-flight, block immediately
            if any(d.outcome == Outcome.DENY for d in pre_decisions):
                # Transition through valid phases to reach BLOCKED
                try:
                    state.transition(Phase.BOOTSTRAPPING)
                except InvalidTransitionError:
                    pass
                try:
                    state.transition(Phase.CHECKING)
                except InvalidTransitionError:
                    pass
                try:
                    state.transition(Phase.BLOCKED)
                except InvalidTransitionError:
                    pass
                state.finalize("BLOCKED")
                evidence.record(action="policy_blocked",
                                detail="pre-flight policy denied workflow")
                log.warn("workflow BLOCKED by pre-flight policy", component="engine")
                self._persist_state(state)
                self._persist_index(state)
                return state

        # ── Execute steps ────────────────────────────────────────────
        step_index = 0
        steps_taken = 0

        while step_index < len(workflow.steps) and steps_taken < max_steps:
            step = workflow.steps[step_index]
            steps_taken += 1

            # Transition to EXECUTING
            try:
                if state.phase in (Phase.CREATED, Phase.BOOTSTRAPPING, Phase.CHECKING,
                                   Phase.PLANNING, Phase.GATING, Phase.EXECUTING):
                    if state.phase == Phase.CREATED:
                        state.transition(Phase.BOOTSTRAPPING)
                    evidence.record(action="phase_transition", detail="CREATED -> BOOTSTRAPPING")
                if state.phase == Phase.BOOTSTRAPPING:
                    state.transition(Phase.CHECKING)
                    evidence.record(action="phase_transition", detail="BOOTSTRAPPING -> CHECKING")
                if state.phase == Phase.CHECKING:
                    state.transition(Phase.EXECUTING)
                    evidence.record(action="phase_transition", detail="CHECKING -> EXECUTING")
            except InvalidTransitionError:
                pass  # already in a valid phase for execution

            # ── Invoke tool ──────────────────────────────────────────
            result = self._invoke_step(step, state, evidence)

            # ── Check branches ───────────────────────────────────────
            outcome = _to_step_outcome(result)
            branch_target = workflow.next_branch(step.name, outcome)

            if branch_target:
                evidence.record(
                    action="branch",
                    detail=f"step={step.name} outcome={outcome.value} -> {branch_target}",
                )
                log.info(f"  branch: {step.name}={outcome.value} -> {branch_target}", component="engine")

                if branch_target == "BLOCK":
                    state.transition(Phase.BLOCKED)
                    state.finalize("BLOCKED")
                    evidence.record(action="workflow_blocked", detail=f"blocked at step {step.name}")
                    log.warn(f"workflow BLOCKED at step {step.name}", component="engine")
                    self._persist_state(state)
                    self._persist_index(state)
                    return state
                elif branch_target == "FAIL":
                    state.transition(Phase.FAILED)
                    state.finalize("FAIL")
                    evidence.record(action="workflow_failed", detail=f"failed at step {step.name}")
                    log.error(f"workflow FAILED at step {step.name}", component="engine")
                    self._persist_state(state)
                    self._persist_index(state)
                    return state
                elif branch_target == "END":
                    break
                else:
                    # Jump to named step
                    idx = workflow.step_index(branch_target)
                    if idx >= 0:
                        step_index = idx
                        continue
                    else:
                        state.transition(Phase.FAILED)
                        state.finalize("FAIL")
                        evidence.record(action="workflow_failed",
                                         detail=f"branch target '{branch_target}' not found")
                        self._persist_state(state)
                        self._persist_index(state)
                        return state

            # ── Gate check ───────────────────────────────────────────
            if step.gate and result.status != ResultStatus.PASS:
                state.transition(Phase.BLOCKED)
                state.finalize("BLOCKED")
                state.record_gate(step.name, passed=False, detail=result.stderr or result.stdout)
                evidence.record(
                    action="gate_failed",
                    tool=step.tool,
                    detail=f"gate '{step.name}' failed: {result.status.value}",
                )
                log.warn(f"gate '{step.name}' BLOCKED workflow", component="engine")
                self._persist_state(state)
                self._persist_index(state)
                return state

            # ── Required step failure ────────────────────────────────
            if step.required and result.status not in (ResultStatus.PASS, ResultStatus.UNSUPPORTED):
                state.transition(Phase.FAILED)
                state.finalize("FAIL")
                evidence.record(
                    action="required_step_failed",
                    tool=step.tool,
                    detail=f"required step '{step.name}' failed: {result.status.value}",
                )
                log.error(f"required step '{step.name}' FAILED", component="engine")
                self._persist_state(state)
                self._persist_index(state)
                return state

            # ── Post-flight policy check ──────────────────────────
            if policy:
                post_decisions = policy.post_flight(
                    tool_name=result.tool_name,
                    tool_status=result.status.value,
                    tool_operation=result.operation,
                )
                for d in post_decisions:
                    state.policy_decisions.append({
                        "rule": d.rule, "outcome": d.outcome.value,
                        "reason": d.reason, "mandatory": str(d.mandatory),
                    })
                    evidence.record(
                        action="policy_decision",
                        detail=f"rule={d.rule} outcome={d.outcome.value} reason={d.reason}",
                    )
                    log.info(f"  policy: {d.rule} -> {d.outcome.value}", component="engine")

                if any(d.outcome == Outcome.DENY for d in post_decisions):
                    state.transition(Phase.BLOCKED)
                    state.finalize("BLOCKED")
                    deny_reasons = [d.reason for d in post_decisions if d.outcome == Outcome.DENY]
                    evidence.record(action="policy_blocked",
                                    detail=f"post-flight denied: {'; '.join(deny_reasons)}")
                    log.warn("workflow BLOCKED by post-flight policy", component="engine")
                    self._persist_state(state)
                    self._persist_index(state)
                    return state

            # ── Continue to next step ────────────────────────────────
            step_index += 1

        # ── Workflow complete ────────────────────────────────────────
        if not state.is_terminal():
            try:
                state.transition(Phase.COMPLETED)
            except InvalidTransitionError:
                pass
            state.finalize("PASS")

        evidence.record(action="workflow_completed", detail=f"steps_taken={steps_taken}")
        log.info(f"workflow '{workflow.name}' completed  status={state.final_status}", component="engine")

        # Persist final state and update index
        self._persist_state(state)
        self._persist_index(state)

        return state

    def _invoke_step(
        self,
        step: Step,
        state: RunState,
        evidence: EvidenceLog,
    ) -> ToolResult:
        """Invoke a single step through the adapter layer."""
        adapter = get_adapter(step.tool, self.workspace)

        if adapter is None:
            result = ToolResult(
                tool_name=step.tool,
                operation=step.operation,
                status=ResultStatus.ERROR,
                exit_code=-1,
                error=f"no adapter for tool '{step.tool}'",
            )
        elif not adapter.available:
            result = ToolResult(
                tool_name=step.tool,
                operation=step.operation,
                status=ResultStatus.UNSUPPORTED,
                exit_code=-1,
                error=f"tool '{step.tool}' not available",
            )
        else:
            # Call the adapter method
            method = getattr(adapter, step.operation, None)
            if method is None:
                result = ToolResult(
                    tool_name=step.tool,
                    operation=step.operation,
                    status=ResultStatus.ERROR,
                    exit_code=-1,
                    error=f"adapter has no operation '{step.operation}'",
                )
            else:
                try:
                    result = method(*step.args, **step.kwargs)
                except Exception as exc:  # noqa: BLE001
                    result = ToolResult(
                        tool_name=step.tool,
                        operation=step.operation,
                        status=ResultStatus.ERROR,
                        exit_code=-1,
                        error=f"adapter exception: {exc}",
                    )

        # ── Record evidence ──────────────────────────────────────────
        call = ToolCall(
            tool_name=result.tool_name,
            operation=result.operation,
            args=step.args,
            exit_code=result.exit_code,
            status=result.status.value,
            stdout=result.stdout[:2000],  # cap for evidence
            stderr=result.stderr[:2000],
            duration=result.duration,
            error=result.error,
        )
        state.record_tool_call(call)

        evidence.record(
            action="tool_invoked",
            tool=result.tool_name,
            operation=result.operation,
            args=step.args,
            exit_code=result.exit_code,
            status=result.status.value,
            duration=result.duration,
            detail=result.error or "",
        )

        log.info(
            f"  {step.name}: {result.tool_name}.{result.operation} -> "
            f"{result.status.value} (exit={result.exit_code}, {result.duration:.1f}s)",
            component="engine",
        )

        return result

    # ── Persistence helpers ──────────────────────────────────────────

    def _persist_state(self, state: RunState) -> None:
        """Persist run state if persistence is enabled."""
        if not self.persist_dir:
            return
        try:
            from .persist import save_state
            save_state(state, self.persist_dir)
        except Exception as exc:  # noqa: BLE001
            log.warn(f"state persistence failed: {exc}", component="engine")

    def _persist_index(self, state: RunState) -> None:
        """Update the run index if persistence is enabled."""
        if not self.persist_dir:
            return
        try:
            from .persist import update_run_index
            update_run_index(state, self.persist_dir)
        except Exception as exc:  # noqa: BLE001
            log.warn(f"index persistence failed: {exc}", component="engine")
