"""Workspace and project detection.

Knows how to find:
  - the current working directory
  - the ecosystem workspace (toolkit test/)
  - the seven tool repositories
  - the project directory (where the user is working)

Design rules (from SECURITY.md / DESIGN.md):
  - never hardcode absolute paths
  - never execute discovered files
  - fail closed when detection is ambiguous
  - defensive against unusual filesystem layouts
"""

from __future__ import annotations

import os
from pathlib import Path

# ── The canonical seven tools ────────────────────────────────────────────
TOOL_NAMES: tuple[str, ...] = (
    "agent-error-log",
    "agent-decision-log",
    "agent-log-ai",
    "agent-memory",
    "agent-blame",
    "agent-diff-gate",
    "agent-sandbox",
)

# Files that identify a tool repository (any one is sufficient).
_TOOL_MARKERS: tuple[str, ...] = ("pyproject.toml", "README.md")


# ── Path helpers ─────────────────────────────────────────────────────────

def cwd() -> Path:
    """Return the current working directory as a resolved Path."""
    return Path.cwd().resolve()


def _find_parent_with_name(start: Path, name: str, max_up: int = 10) -> Path | None:
    """Walk up from *start* looking for a directory named *name*.

    Returns the first match or ``None``.  Stops after *max_up* levels
    to avoid runaway traversal on unusual mount points.
    """
    current = start
    for _ in range(max_up):
        if current.name == name:
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


# ── Tool detection ───────────────────────────────────────────────────────

def detect_tool(tool_dir: Path) -> dict[str, object]:
    """Inspect a single tool directory and return its metadata dict.

    Keys:
        name      — directory name
        path      — resolved Path
        available — True if the directory looks like a valid tool repo
        has_pyproject — True if pyproject.toml exists
        has_readme    — True if README.md exists
    """
    info: dict[str, object] = {
        "name": tool_dir.name,
        "path": tool_dir,
        "available": False,
        "has_pyproject": False,
        "has_readme": False,
    }
    if not tool_dir.is_dir():
        return info
    info["has_pyproject"] = (tool_dir / "pyproject.toml").is_file()
    info["has_readme"] = (tool_dir / "README.md").is_file()
    # A tool is "available" if at least one marker exists.
    info["available"] = any((tool_dir / m).is_file() for m in _TOOL_MARKERS)
    return info


def detect_tools(workspace: Path) -> list[dict[str, object]]:
    """Return metadata for every canonical tool found under *workspace*."""
    results: list[dict[str, object]] = []
    for name in TOOL_NAMES:
        tool_dir = workspace / name
        results.append(detect_tool(tool_dir))
    return results


def all_tools_available(tools: list[dict[str, object]]) -> bool:
    """Return True only if every canonical tool is available."""
    return all(t["available"] for t in tools)


# ── Workspace detection ──────────────────────────────────────────────────

def find_workspace(start: Path | None = None) -> Path | None:
    """Locate the ecosystem workspace by walking upward from *start*.

    Strategy:
      1. If the current directory *is* the workspace (contains ≥ 3 tool
         dirs), return it.
      2. Walk upward looking for a directory that contains ≥ 3 tool dirs.
      3. Return None if nothing qualifies.

    The threshold of 3 avoids false positives on random parent dirs.
    """
    start = start or cwd()
    # Check current dir first.
    if _is_workspace(start):
        return start
    # Walk up.
    current = start.parent
    for _ in range(10):
        if _is_workspace(current):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _is_workspace(path: Path) -> bool:
    """Heuristic: a workspace contains at least 3 of the 7 tool dirs."""
    count = sum(1 for name in TOOL_NAMES if (path / name).is_dir())
    return count >= 3


# ── Project detection ────────────────────────────────────────────────────

def find_project(start: Path | None = None) -> Path | None:
    """Return the project directory.

    A project is the working directory itself (the user is expected to
    ``cd`` into their project before running the orchestrator).
    """
    return (start or cwd()).resolve()


# ── Orchestrator self-location ───────────────────────────────────────────

def find_orchestrator_root() -> Path:
    """Return the directory containing the ``orchestrator/`` Python package.

    This is the agent-orchestrator repository root.
    """
    return Path(__file__).resolve().parent.parent
