"""Run report generation.

Produces human-readable and machine-readable reports from a completed
RunState.  The report is the evidence-backed summary of everything
that happened during a workflow execution.

Design (from DESIGN.md §47):
  Every completed run should produce an ORCHESTRATION_REPORT containing:
  - run ID, project, mode, start/end
  - tools used, commands executed, exit codes
  - decisions, errors, gates, sandbox executions
  - final Git state, blocked actions, final verdict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .evidence import redact
from .state import RunState, Phase


# ── Human-readable report ────────────────────────────────────────────────

def format_report(state: RunState) -> str:
    """Generate a human-readable Markdown report from a RunState."""
    lines: list[str] = []
    bar = "=" * 72

    lines.append(bar)
    lines.append(f"ORCHESTRATION REPORT — {state.workflow_name}")
    lines.append(bar)
    lines.append("")

    # ── Run info ─────────────────────────────────────────────────────
    lines.append(f"Run ID      : {state.run_id}")
    lines.append(f"Workflow    : {state.workflow_name}")
    lines.append(f"Project     : {state.project_dir}")
    lines.append(f"Workspace   : {state.workspace_dir}")
    lines.append(f"Mode        : {state.mode}")
    lines.append(f"Started     : {state.started_at}")
    lines.append(f"Ended       : {state.ended_at or '(in progress)'}")
    lines.append(f"Final phase : {state.phase.value}")
    lines.append(f"Final status: {state.final_status or '(pending)'}")
    lines.append("")

    # ── Tool calls ───────────────────────────────────────────────────
    if state.tool_calls:
        lines.append("-" * 72)
        lines.append("TOOL CALLS")
        lines.append("-" * 72)
        for i, call in enumerate(state.tool_calls, 1):
            lines.append(f"\n  [{i}] {call.tool_name}.{call.operation}")
            lines.append(f"      status  : {call.status}")
            lines.append(f"      exit    : {call.exit_code}")
            lines.append(f"      duration: {call.duration:.1f}s")
            if call.args:
                lines.append(f"      args    : {call.args}")
            if call.error:
                lines.append(f"      error   : {redact(call.error)}")
            if call.stdout:
                preview = call.stdout[:200].replace("\n", " ")
                lines.append(f"      stdout  : {preview}{'...' if len(call.stdout) > 200 else ''}")
            if call.stderr:
                preview = call.stderr[:200].replace("\n", " ")
                lines.append(f"      stderr  : {preview}{'...' if len(call.stderr) > 200 else ''}")

    # ── Policy decisions ────────────────────────────────────────────
    if state.policy_decisions:
        lines.append("")
        lines.append("-" * 72)
        lines.append("POLICY DECISIONS")
        lines.append("-" * 72)
        for pd in state.policy_decisions:
            lines.append(f"  [{pd['outcome']}] {pd['rule']}: {pd.get('reason', '')}")

    # ── Gate results ─────────────────────────────────────────────────
    if state.gate_results:
        lines.append("")
        lines.append("-" * 72)
        lines.append("GATE RESULTS")
        lines.append("-" * 72)
        for g in state.gate_results:
            status = "PASS" if g["passed"] == "True" else "FAIL"
            lines.append(f"  [{status}] {g['gate']}: {g.get('detail', '')}")

    # ── Observations ─────────────────────────────────────────────────
    if state.observations:
        lines.append("")
        lines.append("-" * 72)
        lines.append("OBSERVATIONS")
        lines.append("-" * 72)
        for obs in state.observations:
            lines.append(f"  {obs}")

    # ── Summary ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("-" * 72)
    lines.append("SUMMARY")
    lines.append("-" * 72)
    total = len(state.tool_calls)
    passed = sum(1 for c in state.tool_calls if c.status == "PASS")
    failed = sum(1 for c in state.tool_calls if c.status in ("FAIL", "ERROR"))
    blocked = sum(1 for c in state.tool_calls if c.status == "BLOCKED")
    unsupported = sum(1 for c in state.tool_calls if c.status == "UNSUPPORTED")

    lines.append(f"  Total tool calls   : {total}")
    lines.append(f"  Passed             : {passed}")
    lines.append(f"  Failed             : {failed}")
    lines.append(f"  Blocked            : {blocked}")
    lines.append(f"  Unsupported        : {unsupported}")
    lines.append(f"  Gates passed       : {sum(1 for g in state.gate_results if g['passed'] == 'True')}")
    lines.append(f"  Gates failed       : {sum(1 for g in state.gate_results if g['passed'] != 'True')}")
    lines.append(f"  Final status       : {state.final_status}")
    lines.append("")
    lines.append(bar)

    return "\n".join(lines)


# ── Machine-readable report ──────────────────────────────────────────────

def report_dict(state: RunState) -> dict[str, object]:
    """Generate a machine-readable dict from a RunState."""
    return {
        "run_id": state.run_id,
        "workflow": state.workflow_name,
        "project": state.project_dir,
        "workspace": state.workspace_dir,
        "mode": state.mode,
        "started_at": state.started_at,
        "ended_at": state.ended_at,
        "phase": state.phase.value,
        "final_status": state.final_status,
        "tool_calls": [
            {
                "tool": c.tool_name,
                "operation": c.operation,
                "args": c.args,
                "exit_code": c.exit_code,
                "status": c.status,
                "duration": round(c.duration, 3),
                "error": redact(c.error) if c.error else "",
            }
            for c in state.tool_calls
        ],
        "gate_results": state.gate_results,
        "policy_decisions": state.policy_decisions,
        "observations": state.observations,
    }


def report_json(state: RunState, indent: int = 2) -> str:
    """Generate a machine-readable JSON report."""
    return json.dumps(report_dict(state), indent=indent, default=str)


def save_report(state: RunState, path: Path) -> None:
    """Save both Markdown and JSON reports."""
    path.parent.mkdir(parents=True, exist_ok=True)
    md_path = path.with_suffix(".md")
    json_path = path.with_suffix(".json")
    md_path.write_text(format_report(state), encoding="utf-8")
    json_path.write_text(report_json(state), encoding="utf-8")
