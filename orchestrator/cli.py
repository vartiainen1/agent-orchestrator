"""orchestrator — CLI entry point.

Usage:
    orchestrator --help
    orchestrator --version
    orchestrator status
    orchestrator doctor

Phase 2: doctor now runs real tool discovery.  status provides concise
workspace/tool information.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import exit_codes
from . import olog as log
from .config import load_config, load_workflow
from .discovery import ToolStatus, discover_all, format_summary, format_tool_info
from .modes import Mode, get_mode_rules, is_valid_mode
from .policy import load_policy
from .engine import WorkflowEngine
from .workflow import get_workflow, list_workflows
from .report import format_report, save_report
from .workspace import (
    cwd,
    find_orchestrator_root,
    find_project,
    find_workspace,
)

# ── Argument parser ──────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description=(
            "Coordination layer for the 7-tool AI agent ecosystem.\n\n"
            "orchestrator coordinates agent-error-log, agent-decision-log,\n"
            "agent-log-ai, agent-memory, agent-blame, agent-diff-gate, and\n"
            "agent-sandbox into one coherent workflow."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="enable debug-level logging",
    )

    sub = parser.add_subparsers(dest="command")

    # ── status ───────────────────────────────────────────────────────
    status_p = sub.add_parser(
        "status",
        help="show workspace, project, and tool status",
    )
    status_p.add_argument(
        "--json",
        action="store_true",
        help="output as JSON (machine-readable)",
    )

    # ── doctor ───────────────────────────────────────────────────────
    doctor_p = sub.add_parser(
        "doctor",
        help="verify environment and tool readiness",
    )
    doctor_p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="show detailed tool information",
    )

    # ── run ─────────────────────────────────────────────────────────
    run_p = sub.add_parser(
        "run",
        help="execute a workflow in a specific mode",
    )
    run_p.add_argument(
        "--mode",
        choices=["solo", "development", "security", "enterprise"],
        default=None,
        help="operating mode (default: from config or solo)",
    )
    run_p.add_argument(
        "--workflow",
        default=None,
        help="workflow name (default: mode-appropriate)",
    )
    run_p.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="save report to file",
    )
    run_p.add_argument(
        "--json",
        action="store_true",
        help="output report as JSON",
    )

    # ── modes ────────────────────────────────────────────────────────
    sub.add_parser(
        "modes",
        help="list available operating modes",
    )

    # ── policies ─────────────────────────────────────────────────────
    pol_p = sub.add_parser(
        "policies",
        help="show effective policy for a mode",
    )
    pol_p.add_argument(
        "mode",
        nargs="?",
        default="solo",
        help="mode to inspect (default: solo)",
    )

    # ── history ──────────────────────────────────────────────────────
    hist_p = sub.add_parser(
        "history",
        help="list recent orchestration runs",
    )
    hist_p.add_argument(
        "-n", "--limit",
        type=int,
        default=20,
        help="max runs to show (default: 20)",
    )
    hist_p.add_argument(
        "--json",
        action="store_true",
        help="output as JSON",
    )

    # ── show ─────────────────────────────────────────────────────────
    show_p = sub.add_parser(
        "show",
        help="show details of a specific run",
    )
    show_p.add_argument(
        "run_id",
        help="run ID to inspect",
    )
    show_p.add_argument(
        "--json",
        action="store_true",
        help="output as JSON",
    )

    # ── evidence ─────────────────────────────────────────────────────
    ev_p = sub.add_parser(
        "evidence",
        help="show evidence entries for a run",
    )
    ev_p.add_argument(
        "run_id",
        help="run ID to inspect",
    )
    ev_p.add_argument(
        "--json",
        action="store_true",
        help="output as JSON",
    )
    ev_p.add_argument(
        "-n", "--limit",
        type=int,
        default=50,
        help="max entries to show (default: 50)",
    )

    # ── cancel ───────────────────────────────────────────────────────
    cancel_p = sub.add_parser(
        "cancel",
        help="cancel an interrupted run",
    )
    cancel_p.add_argument(
        "run_id",
        help="run ID to cancel",
    )

    # ── recover ──────────────────────────────────────────────────────
    recover_p = sub.add_parser(
        "recover",
        help="recover interrupted runs",
    )
    recover_p.add_argument(
        "--list",
        action="store_true",
        help="list interrupted runs",
    )
    recover_p.add_argument(
        "--cancel",
        metavar="RUN_ID",
        help="cancel a specific interrupted run",
    )
    recover_p.add_argument(
        "--discard",
        metavar="RUN_ID",
        help="discard a specific interrupted run",
    )

    # ── dashboard ──────────────────────────────────────────────────
    dash_p = sub.add_parser(
        "dashboard",
        help="launch the web dashboard (read-only)",
    )
    dash_p.add_argument(
        "--port",
        type=int,
        default=8520,
        help="port to listen on (default: 8520)",
    )
    dash_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default: 127.0.0.1)",
    )
    dash_p.add_argument(
        "--open",
        action="store_true",
        help="open browser automatically",
    )
    dash_p.add_argument(
        "--no-refresh",
        action="store_true",
        help="disable auto-refresh polling",
    )

    return parser


# ── Commands ─────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> int:
    """Print workspace, project, configuration, and tool availability."""
    project = find_project()
    workspace = find_workspace(project)
    orch_root = find_orchestrator_root()

    if getattr(args, "json", False):
        return _status_json(project, workspace, orch_root)

    log.info(f"orchestrator {__version__}", component="status")
    log.info(f"project     : {project}", component="status")

    if workspace:
        log.info(f"workspace   : {workspace}", component="status")
    else:
        log.warn("workspace   : NOT FOUND (no toolkit test/ detected)", component="status")

    log.info(f"orchestrator: {orch_root}", component="status")

    # Config
    try:
        config = load_config(project)
        log.info(f"mode        : {config.mode}", component="status")
        log.info(f"sandbox_req : {config.sandbox_required}", component="status")
        log.info(f"diff_gate   : {config.diff_gate_required}", component="status")
        log.info(f"config_file : {config.config_path} ({'exists' if config.has_config else 'missing'})", component="status")
        log.info(f"workflow    : {config.workflow_path} ({'exists' if config.has_workflow else 'missing'})", component="status")
    except ValueError as exc:
        log.error(f"config error: {exc}", component="status")
        return exit_codes.INVALID

    # Tools (concise)
    if workspace:
        tools = discover_all(workspace)
        counts = {}
        for t in tools:
            key = t.status.value
            counts[key] = counts.get(key, 0) + 1
        log.info("", component="status")
        log.info("tools:", component="status")
        for t in tools:
            marker = "+" if t.status == ToolStatus.AVAILABLE else "-"
            ver = f" {t.version}" if t.version else ""
            log.info(f"  [{marker}] {t.name}{ver}", component="status")
        total = len(tools)
        avail = counts.get("AVAILABLE", 0)
        log.info(f"  {avail}/{total} available", component="status")
    else:
        log.warn("cannot detect tools (no workspace found)", component="status")

    return exit_codes.OK


def _status_json(project: Path, workspace: Path | None, orch_root: Path) -> int:
    """Print status as JSON for machine consumption."""
    import json  # noqa: F811 — stdlib, only imported in this path

    data: dict[str, object] = {
        "orchestrator_version": __version__,
        "project": str(project),
        "workspace": str(workspace) if workspace else None,
        "orchestrator_root": str(orch_root),
    }

    try:
        config = load_config(project)
        data["config"] = {
            "mode": config.mode,
            "sandbox_required": config.sandbox_required,
            "diff_gate_required": config.diff_gate_required,
            "has_config": config.has_config,
            "has_workflow": config.has_workflow,
        }
    except ValueError as exc:
        data["config"] = {"error": str(exc)}

    if workspace:
        tools = discover_all(workspace)
        data["tools"] = [
            {
                "name": t.name,
                "status": t.status.value,
                "version": t.version,
            }
            for t in tools
        ]

    print(json.dumps(data, indent=2))
    return exit_codes.OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Full discovery and health-check report."""
    verbose = getattr(args, "verbose", False)
    project = find_project()
    workspace = find_workspace(project)

    log.info(f"orchestrator {__version__} — doctor", component="doctor")
    log.info("", component="doctor")

    # Python
    log.info(f"[PASS] Python {sys.version.split()[0]}", component="doctor")

    # Workspace
    if workspace:
        log.info(f"[PASS] Workspace: {workspace}", component="doctor")
    else:
        log.warn("[WARN] Workspace not found (no toolkit test/ detected)", component="doctor")
        log.info("", component="doctor")
        log.info("Summary: workspace missing — cannot discover tools", component="doctor")
        return exit_codes.BLOCKED

    # Config
    try:
        config = load_config(project)
        log.info(f"[PASS] Config loaded (mode={config.mode})", component="doctor")
    except ValueError as exc:
        log.error(f"[FAIL] Config invalid: {exc}", component="doctor")
        return exit_codes.INVALID

    # Workflow
    if config.has_workflow:
        log.info(f"[PASS] workflow.md found", component="doctor")
    else:
        log.warn("[WARN] workflow.md not found", component="doctor")

    # Tool discovery
    log.info("", component="doctor")
    log.info("Tools:", component="doctor")
    tools = discover_all(workspace)

    for tool in tools:
        if tool.status == ToolStatus.AVAILABLE:
            log.info(f"[PASS] {tool.name}", component="doctor")
        elif tool.status == ToolStatus.UNSUPPORTED:
            log.warn(f"[SKIP] {tool.name} — {tool.platform_support}", component="doctor")
        elif tool.status == ToolStatus.MISSING:
            log.error(f"[MISS] {tool.name}", component="doctor")
        elif tool.status == ToolStatus.INVALID:
            log.error(f"[FAIL] {tool.name} — {'; '.join(tool.discovery_errors)}", component="doctor")
        elif tool.status == ToolStatus.ERROR:
            log.error(f"[FAIL] {tool.name} — health check failed", component="doctor")
        else:
            log.warn(f"[???]  {tool.name} — {tool.status.value}", component="doctor")

        if verbose:
            detail = format_tool_info(tool, verbose=True)
            for line in detail.splitlines():
                log.info(line, component="doctor")

    # Summary
    log.info("", component="doctor")
    log.info("Summary:", component="doctor")
    log.info(format_summary(tools), component="doctor")

    # Determine overall status
    counts = {}
    for t in tools:
        key = t.status.value
        counts[key] = counts.get(key, 0) + 1

    if counts.get("ERROR", 0) > 0 or counts.get("INVALID", 0) > 0:
        log.warn("", component="doctor")
        log.warn("Status: DEGRADED (some tools have issues)", component="doctor")
        return exit_codes.ERROR
    elif counts.get("MISSING", 0) > 0:
        log.warn("", component="doctor")
        log.warn("Status: DEGRADED (some tools missing)", component="doctor")
        return exit_codes.BLOCKED
    else:
        log.info("", component="doctor")
        log.info("Status: HEALTHY", component="doctor")
        return exit_codes.OK


# ── Mode commands ────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    """Execute a workflow in the specified mode."""
    project = find_project()
    workspace = find_workspace(project)

    # ── Mode selection: CLI > config > default(solo) ───────────────
    mode_name = getattr(args, "mode", None)
    if not mode_name:
        try:
            config = load_config(project)
            mode_name = config.mode
        except Exception:  # noqa: BLE001
            mode_name = "solo"

    if not is_valid_mode(mode_name):
        log.error(f"invalid mode: {mode_name!r}", component="run")
        return exit_codes.INVALID

    log.info(f"orchestrator run --mode {mode_name}", component="run")
    log.info(f"project     : {project}", component="run")

    if not workspace:
        log.error("workspace not found", component="run")
        return exit_codes.BLOCKED

    log.info(f"workspace   : {workspace}", component="run")

    # ── Load policy ─────────────────────────────────────────────────
    try:
        policy = load_policy(mode_name, project_dir=project)
    except Exception as exc:  # noqa: BLE001
        log.error(f"policy error: {exc}", component="run")
        return exit_codes.INVALID

    log.info(f"policy mode : {policy.mode.value}", component="run")

    # ── Select workflow ─────────────────────────────────────────────
    workflow_name = getattr(args, "workflow", None)
    if not workflow_name:
        # Mode-appropriate default
        workflow_name = "development" if mode_name != "solo" else "bootstrap"

    workflow = get_workflow(workflow_name)
    if workflow is None:
        log.error(f"unknown workflow: {workflow_name!r}", component="run")
        return exit_codes.INVALID

    log.info(f"workflow    : {workflow.name}", component="run")
    log.info("", component="run")

    # ── Execute ─────────────────────────────────────────────────────
    engine = WorkflowEngine(workspace, project)
    state = engine.run(workflow, policy=policy)

    # ── Output ──────────────────────────────────────────────────────
    if getattr(args, "json", False):
        from .report import report_json
        print(report_json(state))
    else:
        print(format_report(state))

    # ── Save report if requested ────────────────────────────────────
    report_path = getattr(args, "report", None)
    if report_path:
        save_report(state, Path(report_path))
        log.info(f"report saved: {report_path}", component="run")

    # ── Exit code ───────────────────────────────────────────────────
    if state.final_status == "PASS":
        return exit_codes.OK
    elif state.final_status == "BLOCKED":
        return exit_codes.BLOCKED
    else:
        return exit_codes.ERROR


def cmd_modes(args: argparse.Namespace) -> int:
    """List available operating modes."""
    print("Available modes:\n")
    for mode in Mode:
        rules = get_mode_rules(mode)
        mandatory = sum(1 for r in rules if r.mandatory)
        optional = len(rules) - mandatory
        print(f"  {mode.value:15s}  {len(rules)} rules ({mandatory} mandatory, {optional} optional)")
    print(f"\nDefault: solo")
    print(f"Selection: CLI --mode > .orchestrator/config > default")
    return exit_codes.OK


def cmd_policies(args: argparse.Namespace) -> int:
    """Show effective policy for a mode."""
    mode_name = getattr(args, "mode", "solo")
    if not is_valid_mode(mode_name):
        log.error(f"invalid mode: {mode_name!r}", component="policies")
        return exit_codes.INVALID

    project = find_project()
    try:
        policy = load_policy(mode_name, project_dir=project)
    except Exception as exc:  # noqa: BLE001
        log.error(f"policy error: {exc}", component="policies")
        return exit_codes.INVALID

    print(f"Effective policy for mode: {policy.mode.value}\n")
    for name, rule in sorted(policy.rules.items()):
        mandatory = " [MANDATORY]" if rule.mandatory else ""
        print(f"  {name:30s} = {rule.value:10s}  ({rule.source}){mandatory}")
        if rule.reason:
            print(f"  {'':30s}   reason: {rule.reason}")
    return exit_codes.OK


# ── History command ──────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> int:
    """List recent orchestration runs."""
    from .persist import list_runs

    workspace = find_workspace(find_project())
    if not workspace:
        log.error("workspace not found", component="history")
        return exit_codes.BLOCKED

    limit = getattr(args, "limit", 20)
    runs = list_runs(workspace, limit=limit)

    if getattr(args, "json", False):
        import json as _json
        data = [{
            "run_id": r.run_id,
            "workflow": r.workflow,
            "mode": r.mode,
            "status": r.status,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "phase": r.phase,
            "tool_call_count": r.tool_call_count,
            "evidence_count": r.evidence_count,
        } for r in runs]
        print(_json.dumps(data, indent=2))
        return exit_codes.OK

    if not runs:
        log.info("no runs found", component="history")
        return exit_codes.OK

    # Table header
    print(f"{'RUN ID':40s}  {'WORKFLOW':15s}  {'MODE':12s}  {'STATUS':10s}  {'STARTED'}")
    print("-" * 110)
    for r in runs:
        status_display = r.status or "RUNNING"
        print(f"{r.run_id:40s}  {r.workflow:15s}  {r.mode:12s}  {status_display:10s}  {r.started_at}")
    print(f"\n{len(runs)} run(s)")
    return exit_codes.OK


# ── Show command ─────────────────────────────────────────────────────────

def cmd_show(args: argparse.Namespace) -> int:
    """Show details of a specific run."""
    from .persist import load_state, get_persisted_run
    from .report import report_dict

    workspace = find_workspace(find_project())
    if not workspace:
        log.error("workspace not found", component="show")
        return exit_codes.BLOCKED

    run_id = args.run_id
    state = load_state(run_id, workspace)
    if state is None:
        log.error(f"run not found: {run_id}", component="show")
        return exit_codes.INVALID

    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(report_dict(state), indent=2, default=str))
        return exit_codes.OK

    # Human-readable output
    print(f"Run ID       : {state.run_id}")
    print(f"Workflow     : {state.workflow_name}")
    print(f"Mode         : {state.mode}")
    print(f"Phase        : {state.phase.value}")
    print(f"Status       : {state.final_status or '(pending)'}")
    print(f"Project      : {state.project_dir}")
    print(f"Workspace    : {state.workspace_dir}")
    print(f"Started      : {state.started_at}")
    print(f"Ended        : {state.ended_at or '(in progress)'}")
    print(f"Tool calls   : {len(state.tool_calls)}")
    print(f"Policy decisions : {len(state.policy_decisions)}")
    print(f"Gate results     : {len(state.gate_results)}")
    print(f"Observations     : {len(state.observations)}")
    return exit_codes.OK


# ── Evidence command ─────────────────────────────────────────────────────

def cmd_evidence(args: argparse.Namespace) -> int:
    """Show evidence entries for a run."""
    from .persist import load_evidence

    workspace = find_workspace(find_project())
    if not workspace:
        log.error("workspace not found", component="evidence")
        return exit_codes.BLOCKED

    run_id = args.run_id
    entries = load_evidence(run_id, workspace)

    if not entries:
        log.info(f"no evidence found for {run_id}", component="evidence")
        return exit_codes.OK

    limit = getattr(args, "limit", 50)
    entries = entries[:limit]

    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(entries, indent=2, default=str))
        return exit_codes.OK

    print(f"Evidence for {run_id} ({len(entries)} entries):\n")
    for i, entry in enumerate(entries, 1):
        action = entry.get("action", "?")
        ts = entry.get("timestamp", "")
        tool = entry.get("tool", "")
        status = entry.get("status", "")
        detail = entry.get("detail", "")

        line = f"  [{i:3d}] {ts}  {action}"
        if tool:
            line += f"  tool={tool}"
        if status:
            line += f"  status={status}"
        print(line)
        if detail:
            print(f"        detail: {detail[:120]}")
    return exit_codes.OK


# ── Cancel command ───────────────────────────────────────────────────────

def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel an interrupted run."""
    from .recovery import recover_run

    workspace = find_workspace(find_project())
    if not workspace:
        log.error("workspace not found", component="cancel")
        return exit_codes.BLOCKED

    run_id = args.run_id
    result = recover_run(workspace, run_id, action="cancel")

    if result.success:
        log.info(f"run {run_id} cancelled", component="cancel")
        return exit_codes.OK
    else:
        log.error(f"cancel failed: {result.reason}", component="cancel")
        return exit_codes.ERROR


# ── Recover command ──────────────────────────────────────────────────────

def cmd_recover(args: argparse.Namespace) -> int:
    """Recover interrupted runs."""
    from .recovery import find_interrupted_runs, recover_run

    workspace = find_workspace(find_project())
    if not workspace:
        log.error("workspace not found", component="recover")
        return exit_codes.BLOCKED

    # List interrupted runs
    if getattr(args, "list", False):
        interrupted = find_interrupted_runs(workspace)
        if not interrupted:
            log.info("no interrupted runs found", component="recover")
            return exit_codes.OK
        print(f"Interrupted runs ({len(interrupted)}):\n")
        for r in interrupted:
            valid_marker = "[VALID]" if r["valid"] else "[CORRUPT]"
            print(f"  {r['run_id']:40s}  {r['workflow']:15s}  {r['phase']:15s}  {valid_marker}")
        return exit_codes.OK

    # Cancel a specific run
    cancel_id = getattr(args, "cancel", None)
    if cancel_id:
        result = recover_run(workspace, cancel_id, action="cancel")
        if result.success:
            log.info(f"run {cancel_id} cancelled", component="recover")
            return exit_codes.OK
        else:
            log.error(f"cancel failed: {result.reason}", component="recover")
            return exit_codes.ERROR

    # Discard a specific run
    discard_id = getattr(args, "discard", None)
    if discard_id:
        result = recover_run(workspace, discard_id, action="discard")
        if result.success:
            log.info(f"run {discard_id} discarded", component="recover")
            return exit_codes.OK
        else:
            log.error(f"discard failed: {result.reason}", component="recover")
            return exit_codes.ERROR

    log.info("use --list, --cancel RUN_ID, or --discard RUN_ID", component="recover")
    return exit_codes.OK


# ── Dashboard command ────────────────────────────────────────────────

def cmd_dashboard(args: argparse.Namespace) -> int:
    """Launch the web dashboard."""
    from .dashboard import launch_dashboard

    project = find_project()
    workspace = find_workspace(project)

    if not workspace:
        log.error("workspace not found", component="dashboard")
        return exit_codes.BLOCKED

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8520)
    open_browser = getattr(args, "open", False)
    refresh = 0 if getattr(args, "no_refresh", False) else 5

    return launch_dashboard(
        workspace=workspace,
        host=host,
        port=port,
        refresh=refresh,
        open_browser=open_browser,
    )


# ── Main entry point ─────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        log.set_level("DEBUG")

    if args.command is None:
        parser.print_help()
        return exit_codes.OK

    commands = {
        "status": cmd_status,
        "doctor": cmd_doctor,
        "run": cmd_run,
        "modes": cmd_modes,
        "policies": cmd_policies,
        "history": cmd_history,
        "show": cmd_show,
        "evidence": cmd_evidence,
        "cancel": cmd_cancel,
        "recover": cmd_recover,
        "dashboard": cmd_dashboard,
    }

    handler = commands.get(args.command)
    if handler is None:
        log.error(f"unknown command: {args.command}", component="cli")
        return exit_codes.INVALID

    try:
        return handler(args)
    except KeyboardInterrupt:
        return exit_codes.ERROR
    except Exception as exc:  # noqa: BLE001 — last-resort safety net
        log.error(f"unhandled error: {exc}", component="cli")
        return exit_codes.ERROR


if __name__ == "__main__":
    sys.exit(main())
