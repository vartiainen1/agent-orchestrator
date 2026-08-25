"""Configuration loading for the orchestrator.

Sources (in priority order):
  1. .orchestrator/config   — project-local overrides (key = value lines)
  2. workflow.md            — operating rules (always present if the user
                             follows the ecosystem convention)

Missing files are not an error — they simply mean defaults apply.

Security:
  - never execute anything found in config
  - never log secrets
  - treat config values as untrusted strings
"""

from __future__ import annotations

import re
from pathlib import Path

# ── Defaults ─────────────────────────────────────────────────────────────

DEFAULTS: dict[str, str] = {
    "mode": "solo",
    "sandbox_required": "true",
    "diff_gate_required": "true",
    "workflow_file": "workflow.md",
    "orchestrator_dir": ".orchestrator",
}

_VALID_MODES = frozenset({"solo", "development", "security", "enterprise"})


# ── Config object ────────────────────────────────────────────────────────

class Config:
    """Immutable configuration for one orchestrator run."""

    __slots__ = ("_data", "_project_dir", "_config_path", "_workflow_path")

    def __init__(self, project_dir: Path, data: dict[str, str] | None = None):
        self._project_dir = project_dir
        self._data: dict[str, str] = dict(DEFAULTS)
        if data:
            self._data.update(data)
        self._config_path = project_dir / ".orchestrator" / "config"
        self._workflow_path = project_dir / self._data["workflow_file"]

    # ── accessors ────────────────────────────────────────────────────

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    @property
    def mode(self) -> str:
        return self._data.get("mode", "solo")

    @property
    def sandbox_required(self) -> bool:
        return self._data.get("sandbox_required", "true").lower() == "true"

    @property
    def diff_gate_required(self) -> bool:
        return self._data.get("diff_gate_required", "true").lower() == "true"

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def workflow_path(self) -> Path:
        return self._workflow_path

    @property
    def has_workflow(self) -> bool:
        return self._workflow_path.is_file()

    @property
    def has_config(self) -> bool:
        return self._config_path.is_file()

    def all_keys(self) -> list[str]:
        return sorted(self._data)

    def __repr__(self) -> str:
        return f"Config(project={self._project_dir}, keys={self.all_keys()})"


# ── Loading ──────────────────────────────────────────────────────────────

def _parse_key_value_config(path: Path) -> dict[str, str]:
    """Parse a simple key = value config file.

    Lines that don't match ``key = value`` are silently ignored.
    Values are stripped of surrounding whitespace.
    """
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            key = match.group(1)
            val = match.group(2).strip()
            result[key] = val
    return result


def load_config(project_dir: Path) -> Config:
    """Load configuration for *project_dir*.

    Reads (in order):
      1. built-in DEFAULTS
      2. .orchestrator/config (if it exists)

    Validates all config values against expected types/ranges.
    """
    config_path = project_dir / ".orchestrator" / "config"
    overrides = _parse_key_value_config(config_path)

    # Validate mode if overridden.
    mode = overrides.get("mode", DEFAULTS["mode"])
    if mode not in _VALID_MODES:
        raise ValueError(
            f"invalid mode {mode!r} in config; choose from {sorted(_VALID_MODES)}"
        )

    # Validate config values using Phase 8B validation
    try:
        from .validate import validate_config_dict
        errors = validate_config_dict(overrides)
        if errors:
            msgs = [f"{e.key}={e.value!r}: {e.reason}" for e in errors]
            raise ValueError(
                f"invalid config values: {'; '.join(msgs)}"
            )
    except ImportError:
        pass  # validate module not yet available

    return Config(project_dir, overrides)


def load_workflow(project_dir: Path, filename: str = "workflow.md") -> str | None:
    """Return the contents of the workflow file, or None if absent."""
    path = project_dir / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")
