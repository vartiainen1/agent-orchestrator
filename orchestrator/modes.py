"""Operating modes and their default policy rules.

Four modes with distinct behavioral profiles:

  SOLO         — individual developer, lowest ceremony
  DEVELOPMENT  — normal software development, full workflow discipline
  SECURITY     — security-sensitive, stronger validation
  ENTERPRISE   — maximum governance and auditability

Each mode defines a set of policy rules.  The Policy Engine layers
these with base safety rules and optional project overrides.

Design: PHASE_5_POLICY_DESIGN.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ── Mode enum ────────────────────────────────────────────────────────────

class Mode(str, Enum):
    """Operating modes for the orchestrator."""
    SOLO = "solo"
    DEVELOPMENT = "development"
    SECURITY = "security"
    ENTERPRISE = "enterprise"


# ── Rule definition ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModeRule:
    """A single policy rule with its value and metadata.

    Frozen (immutable) — mode rules cannot be mutated after creation.
    """
    name: str
    value: str
    mandatory: bool = False
    reason: str = ""


# ── Base safety rules (inviolable) ──────────────────────────────────────

BASE_SAFETY_RULES: list[ModeRule] = [
    ModeRule(
        name="error_log_required",
        value="true",
        mandatory=True,
        reason="error-log gate is a core ecosystem invariant",
    ),
    ModeRule(
        name="decision_log_required",
        value="true",
        mandatory=True,
        reason="decision-log gate is a core ecosystem invariant",
    ),
    ModeRule(
        name="memory_auto_promote",
        value="false",
        mandatory=True,
        reason="memory trust model requires human promotion",
    ),
    ModeRule(
        name="no_git_no_verify",
        value="true",
        mandatory=True,
        reason="commit gates cannot be bypassed",
    ),
    ModeRule(
        name="no_secret_leakage",
        value="true",
        mandatory=True,
        reason="secrets must never appear in evidence or logs",
    ),
    ModeRule(
        name="fail_closed_on_uncertainty",
        value="true",
        mandatory=True,
        reason="unknown state must result in BLOCKED/FAIL",
    ),
]


# ── Mode-specific rules ─────────────────────────────────────────────────

_SOLO_RULES: list[ModeRule] = [
    ModeRule(name="diff_gate_required", value="false",
             reason="diff-gate optional in SOLO for speed"),
    ModeRule(name="sandbox_required", value="false",
             reason="sandbox optional in SOLO for convenience"),
    ModeRule(name="sandbox_strict", value="false",
             reason="non-strict sandbox in SOLO"),
    ModeRule(name="approval_required", value="false",
             reason="no approval needed in SOLO"),
    ModeRule(name="evidence_level", value="basic",
             reason="minimal evidence in SOLO"),
    ModeRule(name="llm_cloud_allowed", value="true",
             reason="cloud LLM allowed in SOLO"),
    ModeRule(name="host_fallback_allowed", value="true",
             reason="host fallback allowed in SOLO"),
    ModeRule(name="max_tool_timeout", value="30",
             reason="standard timeout in SOLO"),
]

_DEVELOPMENT_RULES: list[ModeRule] = [
    ModeRule(name="diff_gate_required", value="true",
             reason="diff-gate mandatory for code quality"),
    ModeRule(name="sandbox_required", value="true",
             reason="sandbox required for safe execution"),
    ModeRule(name="sandbox_strict", value="false",
             reason="standard sandbox in DEVELOPMENT"),
    ModeRule(name="approval_required", value="false",
             reason="no approval needed in DEVELOPMENT"),
    ModeRule(name="evidence_level", value="standard",
             reason="standard evidence for development"),
    ModeRule(name="llm_cloud_allowed", value="true",
             reason="cloud LLM allowed in DEVELOPMENT"),
    ModeRule(name="host_fallback_allowed", value="false",
             reason="no host fallback in DEVELOPMENT"),
    ModeRule(name="max_tool_timeout", value="30",
             reason="standard timeout in DEVELOPMENT"),
]

_SECURITY_RULES: list[ModeRule] = [
    ModeRule(name="diff_gate_required", value="true",
             reason="diff-gate mandatory with strict thresholds"),
    ModeRule(name="sandbox_required", value="true",
             reason="sandbox mandatory in SECURITY"),
    ModeRule(name="sandbox_strict", value="true",
             reason="strict sandbox enforcement in SECURITY"),
    ModeRule(name="approval_required", value="false",
             reason="approval for specific ops (future phase)"),
    ModeRule(name="evidence_level", value="enhanced",
             reason="enhanced evidence for security work"),
    ModeRule(name="llm_cloud_allowed", value="false",
             reason="cloud LLM forbidden in SECURITY"),
    ModeRule(name="host_fallback_allowed", value="false",
             reason="no host fallback in SECURITY"),
    ModeRule(name="max_tool_timeout", value="60",
             reason="longer timeout for security analysis"),
]

_ENTERPRISE_RULES: list[ModeRule] = [
    ModeRule(name="diff_gate_required", value="true",
             reason="diff-gate mandatory, strictest settings"),
    ModeRule(name="sandbox_required", value="true",
             reason="sandbox mandatory in ENTERPRISE"),
    ModeRule(name="sandbox_strict", value="true",
             reason="strictest sandbox in ENTERPRISE"),
    ModeRule(name="approval_required", value="true",
             reason="approval required for consequential actions"),
    ModeRule(name="evidence_level", value="complete",
             reason="complete audit trail in ENTERPRISE"),
    ModeRule(name="llm_cloud_allowed", value="false",
             reason="cloud LLM forbidden in ENTERPRISE"),
    ModeRule(name="host_fallback_allowed", value="false",
             reason="no host fallback in ENTERPRISE"),
    ModeRule(name="max_tool_timeout", value="120",
             reason="longer timeout for enterprise analysis"),
]


# ── Mode registry ────────────────────────────────────────────────────────

MODE_REGISTRY: dict[Mode, list[ModeRule]] = {
    Mode.SOLO: _SOLO_RULES,
    Mode.DEVELOPMENT: _DEVELOPMENT_RULES,
    Mode.SECURITY: _SECURITY_RULES,
    Mode.ENTERPRISE: _ENTERPRISE_RULES,
}


def get_mode_rules(mode: Mode) -> list[ModeRule]:
    """Return the default rules for *mode*, including base safety."""
    return list(BASE_SAFETY_RULES) + list(MODE_REGISTRY.get(mode, []))


def get_mode_rule_value(mode: Mode, rule_name: str) -> str | None:
    """Return the value of *rule_name* for *mode*, or None."""
    for r in get_mode_rules(mode):
        if r.name == rule_name:
            return r.value
    return None


def is_valid_mode(mode_str: str) -> bool:
    """Return True if *mode_str* is a recognized mode name."""
    try:
        Mode(mode_str)
        return True
    except ValueError:
        return False
