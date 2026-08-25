"""Recovery and workspace lock management.

Provides crash recovery, interrupted-run detection, and workspace-level
locking to prevent concurrent runs from corrupting shared state.

Design (from PHASE_8_HARDENING_DESIGN.md):
  - Stale lock detection (PID not running)
  - Interrupted run detection on startup
  - Safe recovery options (resume, cancel, discard)
  - Advisory locking (not mandatory — fails safe)
  - All recovery decisions recorded in evidence

Security:
  - Lock files are advisory (not enforced by OS)
  - PID validation uses os.kill(pid, 0) — no signal sent
  - Persisted data treated as untrusted input
  - Recovery cannot bypass policy or safety gates
  - Path traversal prevented via validated run IDs
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .persist import (
    _validate_run_id,
    _runs_dir,
    _index_path,
    load_state,
    load_evidence,
    validate_persisted_state,
    PersistedRun,
)
from .state import Phase


# ── Lock file model ──────────────────────────────────────────────────────

_LOCK_FILE = "lock"


@dataclass
class LockInfo:
    """Contents of a workspace lock file."""
    pid: int
    acquired_at: str
    workspace: str
    run_id: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "pid": self.pid,
            "acquired_at": self.acquired_at,
            "workspace": self.workspace,
            "run_id": self.run_id,
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> LockInfo | None:
        try:
            data = json.loads(text)
            return cls(
                pid=data.get("pid", 0),
                acquired_at=data.get("acquired_at", ""),
                workspace=data.get("workspace", ""),
                run_id=data.get("run_id", ""),
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            return None


# ── PID check ────────────────────────────────────────────────────────────

def _pid_running(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses os.kill(pid, 0) which sends no signal but checks existence.
    On Windows, uses os.kill with signal=0 which works for existence checks.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:
        # Process exists but we can't signal it — still running
        return True


# ── Lock management ──────────────────────────────────────────────────────

def _lock_path(workspace: Path) -> Path:
    """Return the path to the workspace lock file."""
    return workspace / ".orchestrator" / _LOCK_FILE


def acquire_lock(
    workspace: Path,
    run_id: str = "",
) -> tuple[bool, str]:
    """Try to acquire the workspace lock.

    Returns (success, reason).
    If the lock is held by a running process, returns (False, reason).
    If the lock is stale (PID not running), auto-cleans and acquires.
    """
    lock = _lock_path(workspace)
    lock.parent.mkdir(parents=True, exist_ok=True)

    # Check existing lock
    if lock.is_file():
        try:
            text = lock.read_text(encoding="utf-8")
            info = LockInfo.from_json(text)
            if info and _pid_running(info.pid):
                return False, (
                    f"workspace locked by PID {info.pid} "
                    f"(acquired {info.acquired_at})"
                )
            # Stale lock — PID not running
        except (OSError, ValueError):
            pass  # Corrupt lock file — treat as stale

    # Acquire lock
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    info = LockInfo(
        pid=os.getpid(),
        acquired_at=now,
        workspace=str(workspace),
        run_id=run_id,
    )
    try:
        lock.write_text(info.to_json(), encoding="utf-8")
        return True, "acquired"
    except OSError as exc:
        return False, f"cannot write lock file: {exc}"


def release_lock(workspace: Path) -> None:
    """Release the workspace lock."""
    lock = _lock_path(workspace)
    if lock.is_file():
        try:
            # Verify we own the lock before releasing
            text = lock.read_text(encoding="utf-8")
            info = LockInfo.from_json(text)
            if info and info.pid == os.getpid():
                lock.unlink()
        except (OSError, ValueError):
            pass  # Best-effort cleanup


def check_lock(workspace: Path) -> LockInfo | None:
    """Check the current lock status.

    Returns LockInfo if locked, None if unlocked.
    """
    lock = _lock_path(workspace)
    if not lock.is_file():
        return None
    try:
        text = lock.read_text(encoding="utf-8")
        return LockInfo.from_json(text)
    except (OSError, ValueError):
        return None


def is_locked(workspace: Path) -> bool:
    """Check if the workspace is locked by a running process."""
    info = check_lock(workspace)
    if info is None:
        return False
    return _pid_running(info.pid)


def cleanup_stale_lock(workspace: Path) -> bool:
    """Remove a stale lock (PID not running).

    Returns True if a stale lock was cleaned up.
    """
    lock = _lock_path(workspace)
    if not lock.is_file():
        return False
    try:
        text = lock.read_text(encoding="utf-8")
        info = LockInfo.from_json(text)
        if info and not _pid_running(info.pid):
            lock.unlink()
            return True
    except (OSError, ValueError):
        # Corrupt lock — remove it
        try:
            lock.unlink()
            return True
        except OSError:
            pass
    return False


# ── Interrupted run detection ────────────────────────────────────────────

def find_interrupted_runs(workspace: Path) -> list[dict]:
    """Find runs that may have been interrupted (non-terminal state).

    Returns a list of dicts with run details for user inspection.
    """
    runs_dir = _runs_dir(workspace)
    if not runs_dir.is_dir():
        return []

    index_path = _index_path(workspace)
    if not index_path.is_file():
        return []

    try:
        text = index_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError):
        return []

    terminal_statuses = {"PASS", "FAIL", "BLOCKED", "CANCELLED", ""}
    interrupted = []

    for run_data in data.get("runs", []):
        status = run_data.get("status", "")
        phase = run_data.get("phase", "")
        run_id = run_data.get("run_id", "")

        if status not in terminal_statuses or phase not in ("COMPLETED", "CANCELLED"):
            # Validate the persisted state exists
            valid, reason = validate_persisted_state(run_id, workspace)
            interrupted.append({
                "run_id": run_id,
                "workflow": run_data.get("workflow", ""),
                "mode": run_data.get("mode", ""),
                "status": status or "UNKNOWN",
                "phase": phase,
                "started_at": run_data.get("started_at", ""),
                "valid": valid,
                "validation_reason": reason,
            })

    return interrupted


# ── Run recovery ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RecoveryResult:
    """Result of a recovery operation."""
    success: bool
    run_id: str
    action: str  # "resumed", "cancelled", "discarded", "failed"
    reason: str = ""
    state_phase: str = ""
    state_status: str = ""


def recover_run(
    workspace: Path,
    run_id: str,
    action: str = "cancel",
) -> RecoveryResult:
    """Recover an interrupted run.

    Supported actions:
      - "cancel": Mark the run as CANCELLED (safe default)
      - "discard": Remove the persisted run data

    The "resume" action is not supported in Phase 8C because resuming
    a workflow requires re-initializing adapters, tools, and policy
    state which is complex and risky.  The safe action is to cancel
    and let the user re-run.

    Returns RecoveryResult with the outcome.
    """
    if not _validate_run_id(run_id):
        return RecoveryResult(
            success=False, run_id=run_id, action=action,
            reason=f"invalid run_id: {run_id!r}",
        )

    # Validate persisted state
    valid, reason = validate_persisted_state(run_id, workspace)
    if not valid:
        return RecoveryResult(
            success=False, run_id=run_id, action=action,
            reason=f"state validation failed: {reason}",
        )

    # Load the state
    state = load_state(run_id, workspace)
    if state is None:
        return RecoveryResult(
            success=False, run_id=run_id, action=action,
            reason="failed to load state",
        )

    if action == "cancel":
        return _cancel_run(workspace, state)
    elif action == "discard":
        return _discard_run(workspace, state)
    else:
        return RecoveryResult(
            success=False, run_id=run_id, action=action,
            reason=f"unknown action: {action!r}",
        )


def _cancel_run(workspace: Path, state) -> RecoveryResult:
    """Cancel an interrupted run — mark as CANCELLED."""
    from .persist import save_state, update_run_index

    # Only cancel if not already terminal
    if state.is_terminal():
        return RecoveryResult(
            success=True, run_id=state.run_id, action="cancelled",
            reason="already in terminal state",
            state_phase=state.phase.value,
            state_status=state.final_status,
        )

    # Transition to CANCELLED
    try:
        from .state import InvalidTransitionError
        state.transition(Phase.CANCELLED)
    except Exception:  # noqa: BLE001
        # If transition fails, force the phase
        state.phase = Phase.CANCELLED

    state.finalize("CANCELLED")

    # Persist
    try:
        save_state(state, workspace)
        update_run_index(state, workspace)
    except Exception as exc:  # noqa: BLE001
        return RecoveryResult(
            success=False, run_id=state.run_id, action="cancel",
            reason=f"failed to persist cancellation: {exc}",
        )

    return RecoveryResult(
        success=True, run_id=state.run_id, action="cancelled",
        state_phase=state.phase.value,
        state_status=state.final_status,
    )


def _discard_run(workspace: Path, state) -> RecoveryResult:
    """Discard an interrupted run — remove persisted data."""
    run_dir = _runs_dir(workspace) / state.run_id
    if run_dir.is_dir():
        import shutil
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            return RecoveryResult(
                success=False, run_id=state.run_id, action="discard",
                reason=f"failed to remove run directory: {exc}",
            )

    # Update index to remove the run
    from .persist import _load_index, _save_index
    index = _load_index(workspace)
    index.runs = [r for r in index.runs if r.run_id != state.run_id]
    _save_index(index, workspace)

    return RecoveryResult(
        success=True, run_id=state.run_id, action="discarded",
    )


# ── Provider health check ───────────────────────────────────────────────

def check_provider_health(workspace: Path) -> dict[str, str]:
    """Check health of configured AI providers.

    Returns a dict of provider_name -> status.
    """
    from .providers import get_provider, ProviderStatus

    results = {}

    # Check Ollama (default local provider)
    ollama = get_provider("ollama")
    status = ollama.health()
    results["ollama"] = status.value

    return results


# ── Cleanup ──────────────────────────────────────────────────────────────

def cleanup_workspace(workspace: Path) -> dict[str, str]:
    """Perform workspace cleanup operations.

    Returns a summary of what was done.
    """
    results = {}

    # Clean stale lock
    if cleanup_stale_lock(workspace):
        results["lock"] = "cleaned stale lock"
    else:
        results["lock"] = "no stale lock"

    # Count interrupted runs
    interrupted = find_interrupted_runs(workspace)
    results["interrupted_runs"] = str(len(interrupted))

    return results
