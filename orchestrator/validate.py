"""Input validation and path security.

Provides deterministic validation for paths, configuration values,
and tool output before they can influence workflow decisions.

Design (from PHASE_8_HARDENING_DESIGN.md):
  - Path boundary enforcement
  - Config value validation
  - Tool output validation
  - Fail closed on invalid input

Security:
  - All validation is deterministic (no LLM required)
  - Invalid input produces explicit rejection, never silent acceptance
  - Path traversal is prevented by boundary checks
  - Config values are validated against expected types/ranges
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional


# ── Path validation ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class PathCheck:
    """Result of a path boundary validation."""
    valid: bool
    reason: str
    resolved: str = ""


def validate_path_boundary(base: Path, target: Path) -> PathCheck:
    """Verify that *target* is within the *base* directory.

    Prevents path traversal attacks where a crafted path escapes
    the intended boundary.

    Returns PathCheck with valid=True if safe, or valid=False with
    an explanation.
    """
    try:
        base_resolved = base.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
    except (OSError, ValueError) as exc:
        return PathCheck(valid=False, reason=f"cannot resolve path: {exc}")

    # Check if target is base or a descendant of base
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError:
        return PathCheck(
            valid=False,
            reason=f"path escapes boundary: {target} is outside {base}",
            resolved=str(target_resolved),
        )

    return PathCheck(valid=True, reason="ok", resolved=str(target_resolved))


def validate_run_id_path(base_dir: Path, run_id: str) -> PathCheck:
    """Validate that a run_id produces a safe path within base_dir."""
    from .persist import _validate_run_id

    if not _validate_run_id(run_id):
        return PathCheck(valid=False, reason=f"invalid run_id format: {run_id!r}")

    target = base_dir / "runs" / run_id
    return validate_path_boundary(base_dir, target)


def validate_config_path(project_dir: Path, config_path: Path) -> PathCheck:
    """Validate that a config path is within the project directory."""
    return validate_path_boundary(project_dir, config_path)


def is_safe_filename(name: str) -> bool:
    """Check if a filename is safe (no traversal, no special chars)."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name:
        return False
    if "\0" in name:
        return False
    # Allow alphanumeric, dash, underscore, dot
    return bool(re.match(r"^[a-zA-Z0-9._\-]+$", name))


# ── Config value validation ─────────────────────────────────────────────

# Valid config keys and their expected types
_CONFIG_SCHEMA: dict[str, dict] = {
    "mode": {
        "type": "enum",
        "values": {"solo", "development", "security", "enterprise"},
    },
    "diff_gate_required": {
        "type": "bool",
    },
    "sandbox_required": {
        "type": "bool",
    },
    "sandbox_strict": {
        "type": "bool",
    },
    "approval_required": {
        "type": "bool",
    },
    "llm_cloud_allowed": {
        "type": "bool",
    },
    "host_fallback_allowed": {
        "type": "bool",
    },
    "evidence_level": {
        "type": "enum",
        "values": {"basic", "standard", "enhanced", "complete"},
    },
    "max_tool_timeout": {
        "type": "int",
        "min": 1,
        "max": 3600,
    },
    "provider": {
        "type": "enum",
        "values": {"ollama", "none", "freebuff", "cli"},
    },
    "provider_executable": {
        "type": "string",
        "min_length": 1,
    },
    "provider_args": {
        "type": "string",
    },
    "provider_work_dir": {
        "type": "string",
    },
    "provider_timeout": {
        "type": "int",
        "min": 1,
        "max": 3600,
    },
}


@dataclass(frozen=True)
class ConfigValidation:
    """Result of a config value validation."""
    valid: bool
    key: str
    value: str
    reason: str = ""


def validate_config_value(key: str, value: str) -> ConfigValidation:
    """Validate a single config value against the expected schema.

    Returns ConfigValidation with valid=True if the value is acceptable.
    """
    schema = _CONFIG_SCHEMA.get(key)
    if schema is None:
        # Unknown key — allowed in project config (policy.py handles unknown key rejection)
        return ConfigValidation(valid=True, key=key, value=value)

    vtype = schema["type"]

    if vtype == "bool":
        if value.lower() not in ("true", "false"):
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"expected true/false, got {value!r}",
            )
        return ConfigValidation(valid=True, key=key, value=value)

    if vtype == "enum":
        allowed = schema.get("values", set())
        if value not in allowed:
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"expected one of {sorted(allowed)}, got {value!r}",
            )
        return ConfigValidation(valid=True, key=key, value=value)

    if vtype == "int":
        try:
            ivalue = int(value)
        except (ValueError, TypeError):
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"expected integer, got {value!r}",
            )
        vmin = schema.get("min")
        vmax = schema.get("max")
        if vmin is not None and ivalue < vmin:
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"minimum value is {vmin}, got {ivalue}",
            )
        if vmax is not None and ivalue > vmax:
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"maximum value is {vmax}, got {ivalue}",
            )
        return ConfigValidation(valid=True, key=key, value=value)

    if vtype == "string":
        min_length = schema.get("min_length", 0)
        if len(value) < min_length:
            return ConfigValidation(
                valid=False, key=key, value=value,
                reason=f"minimum length is {min_length}, got {len(value)}",
            )
        return ConfigValidation(valid=True, key=key, value=value)

    # Unknown type — accept
    return ConfigValidation(valid=True, key=key, value=value)


def validate_config_dict(config: dict[str, str]) -> list[ConfigValidation]:
    """Validate all values in a config dict.

    Returns a list of validation results.  Empty list means all valid.
    """
    results = []
    for key, value in config.items():
        result = validate_config_value(key, value)
        if not result.valid:
            results.append(result)
    return results


# ── Tool output validation ──────────────────────────────────────────────

@dataclass(frozen=True)
class OutputCheck:
    """Result of tool output validation."""
    valid: bool
    reason: str = ""
    severity: str = "LOW"  # LOW, MEDIUM, HIGH


def validate_tool_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    tool_name: str = "",
) -> OutputCheck:
    """Validate that tool output is within expected bounds.

    Checks for:
    - Empty output with success exit code (suspicious)
    - Extremely large output (potential DoS)
    - Binary content in text output
    - Null bytes
    """
    # Null bytes — never valid in text output
    if "\x00" in stdout or "\x00" in stderr:
        return OutputCheck(
            valid=False,
            reason="null bytes in tool output",
            severity="HIGH",
        )

    # Binary content detection (high byte ratio of non-text bytes)
    for label, text in [("stdout", stdout), ("stderr", stderr)]:
        if text:
            non_text = sum(1 for b in text.encode("utf-8", errors="replace")
                          if b > 127 and b not in (0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7,
                                                    0xc8, 0xc9, 0xca, 0xcb, 0xcc, 0xcd,
                                                    0xce, 0xcf, 0xd0, 0xd1, 0xd2, 0xd3,
                                                    0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9,
                                                    0xda, 0xdb, 0xdc, 0xdd, 0xde, 0xdf,
                                                    0xe0, 0xe1, 0xe2, 0xe3, 0xe4, 0xe5,
                                                    0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xeb,
                                                    0xec, 0xed, 0xee, 0xef,
                                                    0xf0, 0xf1, 0xf2, 0xf3, 0xf4,
                                                    0xf5, 0xf6, 0xf7, 0xf8, 0xf9,
                                                    0xfa, 0xfb, 0xfc, 0xfd, 0xfe, 0xff))
            total = len(text.encode("utf-8", errors="replace"))
            if total > 0 and non_text / total > 0.3:
                return OutputCheck(
                    valid=False,
                    reason=f"suspected binary content in {label}",
                    severity="MEDIUM",
                )

    # Reasonable size limit (1MB)
    max_size = 1_000_000
    if len(stdout) > max_size:
        return OutputCheck(
            valid=False,
            reason=f"stdout exceeds {max_size} bytes ({len(stdout)})",
            severity="MEDIUM",
        )
    if len(stderr) > max_size:
        return OutputCheck(
            valid=False,
            reason=f"stderr exceeds {max_size} bytes ({len(stderr)})",
            severity="MEDIUM",
        )

    return OutputCheck(valid=True, reason="ok")


def validate_exit_code(exit_code: int) -> OutputCheck:
    """Validate that an exit code is within expected range."""
    if not isinstance(exit_code, int):
        return OutputCheck(
            valid=False,
            reason=f"exit code is not an integer: {exit_code!r}",
            severity="HIGH",
        )
    if exit_code < -128 or exit_code > 255:
        return OutputCheck(
            valid=False,
            reason=f"exit code out of range: {exit_code}",
            severity="MEDIUM",
        )
    return OutputCheck(valid=True, reason="ok")


# ── Agent output validation ─────────────────────────────────────────────

@dataclass(frozen=True)
class AgentOutputCheck:
    """Result of agent output validation."""
    valid: bool
    findings: list[str]
    severity: str = "LOW"


# Patterns that suggest agent output contains dangerous instructions
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"git\s+commit\s+--no-verify", "git --no-verify attempt"),
    (r"rm\s+-rf\s+/", "recursive deletion of root"),
    (r"rm\s+-rf\s+~", "recursive deletion of home"),
    (r"chmod\s+777", "world-writable permissions"),
    (r"curl\s+.*\|\s*(ba)?sh", "remote code execution via pipe"),
    (r"wget\s+.*\|\s*(ba)?sh", "remote code execution via pipe"),
    (r"eval\s*\(", "dynamic code evaluation"),
    (r"exec\s*\(", "dynamic code execution"),
    (r"__import__\s*\(", "dynamic import"),
    (r"subprocess\.call.*shell\s*=\s*True", "shell=True subprocess"),
    (r"sudo\s+", "sudo privilege escalation"),
]


def validate_agent_output(text: str) -> AgentOutputCheck:
    """Scan agent output for dangerous patterns.

    This is a heuristic check.  It does not guarantee detection of all
    dangerous content, but catches the most common patterns.
    """
    findings = []
    for pattern, description in _DANGEROUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(description)

    severity = "LOW"
    if findings:
        severity = "HIGH" if len(findings) >= 2 else "MEDIUM"

    return AgentOutputCheck(
        valid=len(findings) == 0,
        findings=findings,
        severity=severity,
    )
