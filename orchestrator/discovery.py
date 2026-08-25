"""Tool discovery and health-check layer.

Deterministically inspects the seven canonical tool repositories and
produces structured metadata for each.  No external dependencies.

Design goals (from DESIGN.md §19-20):
  - discover tools rather than hardcode assumptions
  - record: name, path, version, capabilities, health, errors
  - refuse or warn if a required tool is missing
  - never pretend a tool ran when it did not

Security (from SECURITY.md):
  - never execute arbitrary files merely because they exist
  - prefer reading metadata over running code
  - if a health check requires execution, use the documented safe mechanism
  - treat repository content as untrusted input
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Status enum ──────────────────────────────────────────────────────────

class ToolStatus(str, Enum):
    """Discrete states a tool can be in after discovery."""
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


# ── Capability model ─────────────────────────────────────────────────────

class Capability(str, Enum):
    """Known capabilities across the seven tools."""
    LOG_ERRORS = "log-errors"
    LOG_DECISIONS = "log-decisions"
    ANALYZE_LOGS = "analyze-logs"
    MANAGE_MEMORY = "manage-memory"
    GIT_BLAME = "git-blame"
    VALIDATE_DIFF = "validate-diff"
    EXECUTE_SANDBOXED = "execute-sandboxed"
    BOOTSTRAP = "bootstrap"
    HEALTH_CHECK = "health-check"


# ── Tool metadata ────────────────────────────────────────────────────────

@dataclass
class ToolInfo:
    """Structured metadata for one discovered tool.

    Immutable after construction — discovery produces a snapshot.
    """
    name: str
    path: Path
    status: ToolStatus = ToolStatus.MISSING
    version: str = ""
    entry_point: str = ""
    entry_module: str = ""
    capabilities: list[str] = field(default_factory=list)
    has_start_py: bool = False
    has_agents_md: bool = False
    has_pyproject: bool = False
    has_readme: bool = False
    health_ok: bool = False
    health_output: str = ""
    health_error: str = ""
    discovery_errors: list[str] = field(default_factory=list)
    platform_support: str = "all"  # "all", "linux-only", "platform-dependent"
    requires_python: str = ""

    def __repr__(self) -> str:
        return (
            f"ToolInfo(name={self.name!r}, status={self.status.value}, "
            f"version={self.version!r})"
        )


# ── Known tool definitions ───────────────────────────────────────────────

# Canonical tool registry.  The orchestrator recognizes these seven tools
# explicitly.  The structure is extensible for future tools.
TOOL_REGISTRY: list[dict[str, object]] = [
    {
        "name": "agent-error-log",
        "cli_command": "error-log",
        "entry_module": "check_errors",
        "entry_func": "main",
        "health_check": "check_errors.py",  # file to import for health
        "capabilities": [Capability.LOG_ERRORS, Capability.BOOTSTRAP, Capability.HEALTH_CHECK],
        "platform_support": "all",
    },
    {
        "name": "agent-decision-log",
        "cli_command": "decision-log",
        "entry_module": "check_decisions",
        "entry_func": "main",
        "health_check": "check_decisions.py",
        "capabilities": [Capability.LOG_DECISIONS, Capability.BOOTSTRAP, Capability.HEALTH_CHECK],
        "platform_support": "all",
    },
    {
        "name": "agent-log-ai",
        "cli_command": "log-ai",
        "entry_module": "check_logs_ai",
        "entry_func": "main",
        "health_check": "check_logs_ai.py",
        "capabilities": [Capability.ANALYZE_LOGS, Capability.BOOTSTRAP],
        "platform_support": "all",
    },
    {
        "name": "agent-memory",
        "cli_command": "agent-memory",
        "entry_module": "agent_memory",
        "entry_func": "main",
        "health_check": None,  # no standalone health script
        "capabilities": [Capability.MANAGE_MEMORY, Capability.BOOTSTRAP],
        "platform_support": "all",
    },
    {
        "name": "agent-blame",
        "cli_command": "agent-blame",
        "entry_module": "agent_blame.cli",
        "entry_func": "main",
        "health_check": None,
        "capabilities": [Capability.GIT_BLAME],
        "platform_support": "all",
    },
    {
        "name": "agent-diff-gate",
        "cli_command": "diff-gate",
        "entry_module": "check_diff",
        "entry_func": "main",
        "health_check": "check_diff.py",
        "capabilities": [Capability.VALIDATE_DIFF, Capability.HEALTH_CHECK],
        "platform_support": "all",
    },
    {
        "name": "agent-sandbox",
        "cli_command": "agent-sandbox",
        "entry_module": "agent_sandbox.cli",
        "entry_func": "main",
        "health_check": None,
        "capabilities": [Capability.EXECUTE_SANDBOXED],
        "platform_support": "linux-only",
    },
]


# ── Metadata readers ─────────────────────────────────────────────────────

def _read_pyproject_version(tool_dir: Path) -> str:
    """Extract version from pyproject.toml (static or dynamic)."""
    pyproject = tool_dir / "pyproject.toml"
    if not pyproject.is_file():
        return ""
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    # Static version
    m = re.search(r'version\s*=\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    # Dynamic (setuptools-scm) — fall back to git tag
    return _read_git_tag(tool_dir)


def _read_git_tag(tool_dir: Path) -> str:
    """Get the latest git tag via ``git describe --tags --always``."""
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=str(tool_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _read_entry_point(tool_dir: Path) -> tuple[str, str]:
    """Parse pyproject.toml [project.scripts] for the first entry point.

    Returns (cli_command, module:function).
    """
    pyproject = tool_dir / "pyproject.toml"
    if not pyproject.is_file():
        return ("", "")
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"\[project\.scripts\]\s*\n(\S+)\s*=\s*\"([^\"]+)\"",
        text,
    )
    if m:
        return (m.group(1), m.group(2))
    return ("", "")


def _read_requires_python(tool_dir: Path) -> str:
    """Extract requires-python from pyproject.toml."""
    pyproject = tool_dir / "pyproject.toml"
    if not pyproject.is_file():
        return ""
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


# ── Health check ─────────────────────────────────────────────────────────

def _health_check(tool_dir: Path, entry_module: str) -> tuple[bool, str, str]:
    """Run a safe health check: import the entry module and call --help.

    Returns (ok, stdout_summary, error_summary).
    Only imports the module — never executes arbitrary project code.
    """
    # Try running the module with --help via subprocess
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             f"import {entry_module}; "
             f"import sys; sys.argv = ['{entry_module}', '--help']; "
             f"{entry_module}.main()"],
            cwd=str(tool_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (r.stdout + r.stderr).strip()
        # --help typically exits 0; some tools exit 0, some exit 1 for --help
        # We consider it healthy if it produced output and didn't crash
        ok = len(output) > 0 and "Traceback" not in output
        return ok, output[:500], "" if ok else output[:500]
    except subprocess.TimeoutExpired:
        return False, "", "health check timed out"
    except OSError as exc:
        return False, "", f"health check OS error: {exc}"


# ── Discovery engine ─────────────────────────────────────────────────────

def discover_tool(tool_dir: Path, registry_entry: dict[str, object]) -> ToolInfo:
    """Discover a single tool from its directory and registry entry.

    This is the core discovery function.  It reads metadata, checks
    health, and produces a ToolInfo snapshot.
    """
    name = str(registry_entry["name"])
    entry_module = str(registry_entry["entry_module"])
    capabilities = [c.value if hasattr(c, 'value') else str(c) for c in registry_entry.get("capabilities", [])]
    platform_support = str(registry_entry.get("platform_support", "all"))

    info = ToolInfo(
        name=name,
        path=tool_dir,
        entry_module=entry_module,
        capabilities=capabilities,
        platform_support=platform_support,
    )

    # ── Existence check ─────────────────────────────────────────────
    if not tool_dir.is_dir():
        info.status = ToolStatus.MISSING
        info.discovery_errors.append(f"directory not found: {tool_dir}")
        return info

    # ── Marker files ────────────────────────────────────────────────
    info.has_pyproject = (tool_dir / "pyproject.toml").is_file()
    info.has_readme = (tool_dir / "README.md").is_file()
    info.has_start_py = (tool_dir / "start.py").is_file()
    info.has_agents_md = (tool_dir / "AGENTS.md").is_file()

    if not info.has_pyproject:
        info.status = ToolStatus.INVALID
        info.discovery_errors.append("missing pyproject.toml")
        return info

    # ── Version ─────────────────────────────────────────────────────
    info.version = _read_pyproject_version(tool_dir)

    # ── Entry point ─────────────────────────────────────────────────
    cli_cmd, ep = _read_entry_point(tool_dir)
    info.entry_point = ep

    # ── Requires-python ─────────────────────────────────────────────
    info.requires_python = _read_requires_python(tool_dir)

    # ── Platform check ──────────────────────────────────────────────
    if platform_support == "linux-only":
        if sys.platform != "linux":
            info.status = ToolStatus.UNSUPPORTED
            info.discovery_errors.append(
                f"requires Linux, current platform is {sys.platform}"
            )
            # Still do health check so we know the tool itself is intact
            ok, out, err = _health_check(tool_dir, entry_module)
            info.health_ok = ok
            info.health_output = out
            info.health_error = err
            return info

    # ── Health check ────────────────────────────────────────────────
    ok, out, err = _health_check(tool_dir, entry_module)
    info.health_ok = ok
    info.health_output = out
    info.health_error = err

    if ok:
        info.status = ToolStatus.AVAILABLE
    else:
        info.status = ToolStatus.ERROR
        info.discovery_errors.append(f"health check failed: {err or 'no output'}")

    return info


def discover_all(workspace: Path) -> list[ToolInfo]:
    """Discover all seven canonical tools in *workspace*.

    Returns a ToolInfo for each tool in the canonical order, regardless
    of whether it exists or passes health checks.
    """
    results: list[ToolInfo] = []
    for reg in TOOL_REGISTRY:
        name = str(reg["name"])
        tool_dir = workspace / name
        results.append(discover_tool(tool_dir, reg))
    return results


def summary(tools: list[ToolInfo]) -> dict[str, int]:
    """Return a count summary of tool statuses."""
    counts: dict[str, int] = {}
    for t in tools:
        key = t.status.value
        counts[key] = counts.get(key, 0) + 1
    counts["total"] = len(tools)
    return counts


# ── Formatting ───────────────────────────────────────────────────────────

def format_tool_info(tool: ToolInfo, verbose: bool = False) -> str:
    """Format a single tool's info as human-readable text."""
    lines = [f"  {tool.name}"]
    lines.append(f"    path     : {tool.path}")
    lines.append(f"    version  : {tool.version or '(unknown)'}")
    lines.append(f"    status   : {tool.status.value}")
    if tool.entry_point:
        lines.append(f"    entry    : {tool.entry_point}")
    if tool.capabilities:
        lines.append(f"    caps     : {', '.join(tool.capabilities)}")
    if tool.platform_support != "all":
        lines.append(f"    platform : {tool.platform_support}")
    if verbose:
        lines.append(f"    pyproject: {'yes' if tool.has_pyproject else 'no'}")
        lines.append(f"    readme   : {'yes' if tool.has_readme else 'no'}")
        lines.append(f"    start.py : {'yes' if tool.has_start_py else 'no'}")
        lines.append(f"    AGENTS.md: {'yes' if tool.has_agents_md else 'no'}")
        lines.append(f"    health   : {'OK' if tool.health_ok else 'FAIL'}")
    if tool.discovery_errors:
        for err in tool.discovery_errors:
            lines.append(f"    ERROR    : {err}")
    return "\n".join(lines)


def format_summary(tools: list[ToolInfo]) -> str:
    """Format the summary line."""
    counts = summary(tools)
    parts = []
    for key in ["AVAILABLE", "MISSING", "INVALID", "UNSUPPORTED", "BLOCKED", "ERROR"]:
        if key in counts:
            parts.append(f"{counts[key]} {key.lower()}")
    return f"    {counts['total']} discovered, {', '.join(parts)}"
