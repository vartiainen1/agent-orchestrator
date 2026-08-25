"""Persistence layer for run state and evidence.

Provides crash-safe persistence for orchestration runs so that evidence
and state survive process termination.

Design (from PHASE_8_HARDENING_DESIGN.md):
  - Evidence auto-saves to JSONL (one entry per line, append-only)
  - Run state saves on phase transitions
  - Run index tracks all runs
  - Atomic writes prevent corruption from interrupted writes
  - Secrets are never intentionally persisted

Storage layout:
    .orchestrator/
        runs/
            index.json              # run history index
            {run_id}/
                state.json          # full run state (overwritten on transition)
                evidence.jsonl      # append-only evidence entries
                evidence.sha256     # optional integrity hash chain

Security:
  - Uses os.replace() for atomic writes (cross-platform)
  - Validates run_id to prevent path traversal
  - Does not persist raw secrets (uses existing redaction)
  - Fails safely when persistence cannot be completed
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .evidence import redact
from .state import RunState, Phase, ToolCall


# ── Constants ────────────────────────────────────────────────────────────

_RUNS_DIR = "runs"
_INDEX_FILE = "index.json"
_STATE_FILE = "state.json"
_EVIDENCE_FILE = "evidence.jsonl"
_EVIDENCE_HASH_FILE = "evidence.sha256"

# Valid run_id pattern: RUN-YYYYMMDD-HHMMSS-xxxxxx
_RUN_ID_PATTERN = re.compile(r"^RUN-\d{8}-\d{6}-[a-f0-9]{6}$")

# Maximum run_id length to prevent abuse
_MAX_RUN_ID_LENGTH = 64

_INDEX_VERSION = 1


# ── Run index entry ──────────────────────────────────────────────────────

@dataclass
class PersistedRun:
    """Summary of a persisted run for the index."""
    run_id: str
    workflow: str
    mode: str
    status: str  # PASS / FAIL / BLOCKED / CANCELLED / RUNNING
    started_at: str
    ended_at: str = ""
    project_dir: str = ""
    tool_call_count: int = 0
    evidence_count: int = 0
    phase: str = "CREATED"


@dataclass
class RunIndex:
    """Central index tracking all runs."""
    version: int = _INDEX_VERSION
    runs: list[PersistedRun] = field(default_factory=list)


# ── Path helpers ─────────────────────────────────────────────────────────

def _validate_run_id(run_id: str) -> bool:
    """Validate run_id format to prevent path traversal."""
    if not run_id or len(run_id) > _MAX_RUN_ID_LENGTH:
        return False
    return bool(_RUN_ID_PATTERN.match(run_id))


def _runs_dir(base_dir: Path) -> Path:
    """Return the runs directory path."""
    return base_dir / _RUNS_DIR


def _run_dir(base_dir: Path, run_id: str) -> Path:
    """Return the directory for a specific run."""
    return _runs_dir(base_dir) / run_id


def _index_path(base_dir: Path) -> Path:
    """Return the path to the run index file."""
    return _runs_dir(base_dir) / _INDEX_FILE


def _state_path(base_dir: Path, run_id: str) -> Path:
    """Return the path to the state file for a run."""
    return _run_dir(base_dir, run_id) / _STATE_FILE


def _evidence_path(base_dir: Path, run_id: str) -> Path:
    """Return the path to the evidence JSONL file for a run."""
    return _run_dir(base_dir, run_id) / _EVIDENCE_FILE


def _evidence_hash_path(base_dir: Path, run_id: str) -> Path:
    """Return the path to the evidence hash chain file."""
    return _run_dir(base_dir, run_id) / _EVIDENCE_HASH_FILE


# ── Atomic writes ────────────────────────────────────────────────────────

def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically using temp file + os.replace().

    If the write fails partway, the original file (if any) remains intact.
    This prevents corrupted files from interrupted writes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (same filesystem for atomic rename)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            suffix=".tmp",
            prefix=path.stem + ".",
        )
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        fd = None  # closed by os.fdopen

        # Atomic rename
        os.replace(tmp_path, path)
        tmp_path = None
    except BaseException:
        # Clean up on any failure
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _atomic_append_line(path: Path, line: str, encoding: str = "utf-8") -> None:
    """Append a single line to a file atomically.

    Uses file open in append mode.  Each line is written and flushed
    individually so that a crash loses at most one line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding=encoding) as f:
        f.write(line)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


# ── Run state persistence ───────────────────────────────────────────────

def _state_to_dict(state: RunState) -> dict:
    """Convert RunState to a JSON-serializable dict."""
    return {
        "run_id": state.run_id,
        "workflow_name": state.workflow_name,
        "project_dir": state.project_dir,
        "workspace_dir": state.workspace_dir,
        "mode": state.mode,
        "phase": state.phase.value,
        "started_at": state.started_at,
        "ended_at": state.ended_at,
        "final_status": state.final_status,
        "tool_calls": [
            {
                "tool_name": c.tool_name,
                "operation": c.operation,
                "args": c.args,
                "exit_code": c.exit_code,
                "status": c.status,
                "stdout": c.stdout[:2000],  # cap for storage
                "stderr": c.stderr[:2000],
                "duration": round(c.duration, 3),
                "timestamp": c.timestamp,
                "error": redact(c.error) if c.error else "",
            }
            for c in state.tool_calls
        ],
        "observations": list(state.observations),
        "gate_results": list(state.gate_results),
        "policy_decisions": list(state.policy_decisions),
    }


def _state_from_dict(data: dict) -> RunState:
    """Reconstruct a RunState from a persisted dict."""
    tool_calls = [
        ToolCall(
            tool_name=c.get("tool_name", ""),
            operation=c.get("operation", ""),
            args=c.get("args", []),
            exit_code=c.get("exit_code", -1),
            status=c.get("status", ""),
            stdout=c.get("stdout", ""),
            stderr=c.get("stderr", ""),
            duration=c.get("duration", 0.0),
            timestamp=c.get("timestamp", ""),
            error=c.get("error", ""),
        )
        for c in data.get("tool_calls", [])
    ]

    phase_str = data.get("phase", "CREATED")
    try:
        phase = Phase(phase_str)
    except ValueError:
        phase = Phase.CREATED

    state = RunState(
        run_id=data.get("run_id", ""),
        workflow_name=data.get("workflow_name", ""),
        project_dir=data.get("project_dir", ""),
        workspace_dir=data.get("workspace_dir", ""),
        mode=data.get("mode", "solo"),
        phase=phase,
        started_at=data.get("started_at", ""),
        ended_at=data.get("ended_at", ""),
        final_status=data.get("final_status", ""),
        tool_calls=tool_calls,
        observations=data.get("observations", []),
        gate_results=data.get("gate_results", []),
        policy_decisions=data.get("policy_decisions", []),
    )
    return state


def save_state(state: RunState, base_dir: Path) -> Path:
    """Atomically save run state to disk.

    Returns the path where state was saved.
    """
    if not _validate_run_id(state.run_id):
        raise ValueError(f"invalid run_id: {state.run_id!r}")

    path = _state_path(base_dir, state.run_id)
    content = json.dumps(_state_to_dict(state), indent=2, default=str)
    _atomic_write(path, content)
    return path


def load_state(run_id: str, base_dir: Path) -> RunState | None:
    """Load run state from disk.

    Returns None if the state file does not exist or is invalid.
    """
    if not _validate_run_id(run_id):
        return None

    path = _state_path(base_dir, run_id)
    if not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return _state_from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


# ── Evidence persistence ────────────────────────────────────────────────

def append_evidence(entry: dict, base_dir: Path, run_id: str) -> None:
    """Append a single evidence entry to the JSONL file.

    Each entry is written and flushed individually so that a crash
    loses at most one line.
    """
    if not _validate_run_id(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")

    path = _evidence_path(base_dir, run_id)
    line = json.dumps(entry, default=str)
    _atomic_append_line(path, line)


def load_evidence(run_id: str, base_dir: Path) -> list[dict]:
    """Load all evidence entries from a JSONL file.

    Returns empty list if the file does not exist.
    Corrupted lines are skipped with a marker entry.
    """
    if not _validate_run_id(run_id):
        return []

    path = _evidence_path(base_dir, run_id)
    if not path.is_file():
        return []

    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    entries.append({
                        "action": "CORRUPTED_LINE",
                        "line_number": line_num,
                        "detail": f"line {line_num} failed to parse",
                    })
    except OSError:
        return []
    return entries


def evidence_count(run_id: str, base_dir: Path) -> int:
    """Count evidence entries without loading them all."""
    if not _validate_run_id(run_id):
        return 0
    path = _evidence_path(base_dir, run_id)
    if not path.is_file():
        return 0
    count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


# ── Run index ────────────────────────────────────────────────────────────

def _load_index(base_dir: Path) -> RunIndex:
    """Load the run index from disk."""
    path = _index_path(base_dir)
    if not path.is_file():
        return RunIndex()
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        runs = [
            PersistedRun(**r) for r in data.get("runs", [])
        ]
        return RunIndex(
            version=data.get("version", _INDEX_VERSION),
            runs=runs,
        )
    except (json.JSONDecodeError, OSError, TypeError):
        return RunIndex()


def _save_index(index: RunIndex, base_dir: Path) -> None:
    """Atomically save the run index."""
    path = _index_path(base_dir)
    data = {
        "version": index.version,
        "runs": [asdict(r) for r in index.runs],
    }
    content = json.dumps(data, indent=2, default=str)
    _atomic_write(path, content)


def update_run_index(state: RunState, base_dir: Path) -> None:
    """Add or update a run in the index."""
    index = _load_index(base_dir)

    entry = PersistedRun(
        run_id=state.run_id,
        workflow=state.workflow_name,
        mode=state.mode,
        status=state.final_status or "RUNNING",
        started_at=state.started_at,
        ended_at=state.ended_at,
        project_dir=state.project_dir,
        tool_call_count=len(state.tool_calls),
        evidence_count=evidence_count(state.run_id, base_dir),
        phase=state.phase.value,
    )

    # Update existing or append
    found = False
    for i, existing in enumerate(index.runs):
        if existing.run_id == state.run_id:
            index.runs[i] = entry
            found = True
            break
    if not found:
        index.runs.append(entry)

    _save_index(index, base_dir)


def list_runs(base_dir: Path, limit: int = 20) -> list[PersistedRun]:
    """List recent runs from the index."""
    index = _load_index(base_dir)
    # Most recent first
    runs = list(reversed(index.runs))
    return runs[:limit]


def get_persisted_run(run_id: str, base_dir: Path) -> PersistedRun | None:
    """Get a specific run from the index."""
    if not _validate_run_id(run_id):
        return None
    index = _load_index(base_dir)
    for run in index.runs:
        if run.run_id == run_id:
            return run
    return None


# ── Convenience: persist a full run ─────────────────────────────────────

def persist_run(state: RunState, base_dir: Path) -> None:
    """Persist complete run state and update index.

    This is the main entry point for saving a run.
    """
    if not _validate_run_id(state.run_id):
        raise ValueError(f"invalid run_id: {state.run_id!r}")
    save_state(state, base_dir)
    update_run_index(state, base_dir)


# ── Corrupt state detection ─────────────────────────────────────────────

def validate_persisted_state(run_id: str, base_dir: Path) -> tuple[bool, str]:
    """Validate that persisted state is intact.

    Returns (is_valid, reason).
    """
    if not _validate_run_id(run_id):
        return False, f"invalid run_id format: {run_id!r}"

    path = _state_path(base_dir, run_id)
    if not path.is_file():
        return False, "state file not found"

    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"state file unreadable/corrupt: {exc}"

    required = {"run_id", "workflow_name", "phase", "started_at"}
    missing = required - set(data.keys())
    if missing:
        return False, f"state missing required fields: {missing}"

    if data.get("run_id") != run_id:
        return False, "run_id mismatch"

    return True, "valid"


# ── Find interrupted runs ───────────────────────────────────────────────

def find_interrupted_runs(base_dir: Path) -> list[PersistedRun]:
    """Find runs in non-terminal state (potentially interrupted)."""
    index = _load_index(base_dir)
    terminal = {"PASS", "FAIL", "BLOCKED", "CANCELLED", ""}
    return [
        run for run in index.runs
        if run.status not in terminal or run.phase not in ("COMPLETED", "CANCELLED")
    ]
