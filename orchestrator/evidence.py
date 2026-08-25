"""Evidence recording and secret redaction.

Every orchestration action produces evidence.  This module provides
utilities for recording, redacting, and serializing that evidence.

Design (from DESIGN.md §21):
  - Every run has an ID
  - Every action records: timestamp, action, tool, arguments, exit code,
    stdout/stderr summary, result, next action, reason, security state
  - Evidence must be human-readable
  - Prefer plain files over a database

Security (from SECURITY.md §14):
  - Never log secrets
  - Redact sensitive values from reports/logs
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Secret patterns ──────────────────────────────────────────────────────

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(api[_-]?key|token|password|secret|credential|private[_-]?key)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style keys
]


def redact(text: str) -> str:
    """Replace potential secrets in *text* with [REDACTED].

    This is a best-effort heuristic.  It does not guarantee all secrets
    are caught, but it prevents the most common patterns from leaking
    into logs and reports.
    """
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


# ── Evidence entry ───────────────────────────────────────────────────────

def evidence_entry(
    *,
    run_id: str,
    action: str,
    tool: str = "",
    operation: str = "",
    args: list[str] | None = None,
    exit_code: int | None = None,
    status: str = "",
    duration: float | None = None,
    detail: str = "",
) -> dict[str, object]:
    """Create a single evidence entry dict.

    Secrets in args and detail are redacted.
    """
    entry: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "action": action,
    }
    if tool:
        entry["tool"] = tool
    if operation:
        entry["operation"] = operation
    if args is not None:
        entry["args"] = [redact(a) for a in args]
    if exit_code is not None:
        entry["exit_code"] = exit_code
    if status:
        entry["status"] = status
    if duration is not None:
        entry["duration"] = round(duration, 3)
    if detail:
        entry["detail"] = redact(detail)
    return entry


# ── Evidence log ─────────────────────────────────────────────────────────

class EvidenceLog:
    """Append-only evidence log for a single workflow run.

    Supports auto-save: when a persist_dir and run_id are provided,
    each entry is immediately appended to a JSONL file on disk.
    This ensures evidence survives process termination.
    """

    def __init__(
        self,
        run_id: str,
        persist_dir: Path | None = None,
    ):
        self.run_id = run_id
        self._entries: list[dict[str, object]] = []
        self._persist_dir = persist_dir
        self._persist_enabled = persist_dir is not None
        self._persist_error: str | None = None

    @property
    def persist_enabled(self) -> bool:
        """Whether auto-save is active."""
        return self._persist_enabled

    @property
    def persist_error(self) -> str | None:
        """Last persistence error, if any."""
        return self._persist_error

    def record(self, **kwargs) -> None:
        """Append an evidence entry.

        If auto-save is enabled, the entry is immediately persisted
        to the JSONL file.
        """
        entry = evidence_entry(run_id=self.run_id, **kwargs)
        self._entries.append(entry)

        if self._persist_enabled and self._persist_dir:
            try:
                from .persist import append_evidence
                append_evidence(entry, self._persist_dir, self.run_id)
                self._persist_error = None
            except Exception as exc:  # noqa: BLE001
                # Persistence failure must not crash the run
                self._persist_error = str(exc)

    def entries(self) -> list[dict[str, object]]:
        """Return a copy of all entries."""
        return list(self._entries)

    def to_json(self, indent: int = 2) -> str:
        """Serialize all entries to JSON."""
        return json.dumps(self._entries, indent=indent, default=str)

    def save(self, path: Path) -> None:
        """Write the evidence log to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._entries)
