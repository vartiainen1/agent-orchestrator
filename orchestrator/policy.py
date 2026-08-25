"""Policy engine — layered policy evaluation with deterministic decisions.

Evaluates policy across three layers:
  BASE SAFETY  (inviolable, code-level)
  + MODE       (per-mode rules)
  + PROJECT    (optional overrides, can only tighten)
  = EFFECTIVE POLICY

Design: PHASE_5_POLICY_DESIGN.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .modes import (
    BASE_SAFETY_RULES,
    Mode,
    ModeRule,
    get_mode_rules,
    is_valid_mode,
)


# ── Policy outcomes ──────────────────────────────────────────────────────

class Outcome(str, Enum):
    """Possible policy decision outcomes."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_TOOL = "REQUIRE_TOOL"
    REQUIRE_GATE = "REQUIRE_GATE"
    REQUIRE_SANDBOX = "REQUIRE_SANDBOX"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    WARN = "WARN"


# ── Policy decision ──────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    """A single policy decision with full context.

    Every decision answers: WHAT was evaluated, WHICH rule applied,
    WHAT was the result, WHY, and WHAT should happen next.
    """
    rule: str
    outcome: Outcome
    reason: str
    mode: str
    mandatory: bool = False
    context: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Policy rule (effective) ─────────────────────────────────────────────

@dataclass(frozen=True)
class EffectiveRule:
    """A rule in the effective policy with its source layer."""
    name: str
    value: str
    mandatory: bool
    source: str  # "base", "mode", "project"
    reason: str


# ── Policy class ─────────────────────────────────────────────────────────

class Policy:
    """Immutable effective policy built from base + mode + project layers.

    Created by load_policy().  Evaluates pre-flight and post-flight checks.
    """

    def __init__(
        self,
        mode: Mode,
        rules: dict[str, EffectiveRule],
        project_source: str = "",
    ):
        self._mode = mode
        self._rules = dict(rules)
        self._project_source = project_source

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def rules(self) -> dict[str, EffectiveRule]:
        return dict(self._rules)

    def get(self, name: str) -> str | None:
        """Return the effective value of a rule, or None."""
        r = self._rules.get(name)
        return r.value if r else None

    def is_mandatory(self, name: str) -> bool:
        """Return True if *name* is a mandatory (inviolable) rule."""
        r = self._rules.get(name)
        return r.mandatory if r else False

    # ── Pre-flight checks ────────────────────────────────────────────

    def pre_flight(
        self,
        available_tools: set[str] | None = None,
    ) -> list[PolicyDecision]:
        """Evaluate policy before workflow execution.

        Returns a list of decisions.  If any DENY is present, the
        workflow should not start.
        """
        decisions: list[PolicyDecision] = []
        available = available_tools or set()

        # Error-log required?
        decisions.append(self._eval_rule(
            "error_log_required",
            context="pre-flight",
            tool_available="agent-error-log" in available,
        ))

        # Decision-log required?
        decisions.append(self._eval_rule(
            "decision_log_required",
            context="pre-flight",
            tool_available="agent-decision-log" in available,
        ))

        # Diff-gate required?
        if self.get("diff_gate_required") == "true":
            decisions.append(self._eval_rule(
                "diff_gate_required",
                context="pre-flight",
                tool_available="agent-diff-gate" in available,
            ))

        # Sandbox required?
        if self.get("sandbox_required") == "true":
            decisions.append(self._eval_rule(
                "sandbox_required",
                context="pre-flight",
                tool_available="agent-sandbox" in available,
            ))

        # LLM cloud check
        if self.get("llm_cloud_allowed") == "false":
            decisions.append(PolicyDecision(
                rule="llm_cloud_allowed",
                outcome=Outcome.DENY,
                reason="cloud LLM forbidden in this mode",
                mode=self._mode.value,
                context="pre-flight",
            ))

        # Host fallback check
        if self.get("host_fallback_allowed") == "false":
            decisions.append(PolicyDecision(
                rule="host_fallback_allowed",
                outcome=Outcome.WARN,
                reason="host fallback disabled; sandbox required for execution",
                mode=self._mode.value,
                context="pre-flight",
            ))

        # Approval check
        if self.get("approval_required") == "true":
            decisions.append(PolicyDecision(
                rule="approval_required",
                outcome=Outcome.REQUIRE_APPROVAL,
                reason="this mode requires human approval for consequential actions",
                mode=self._mode.value,
                context="pre-flight",
            ))

        return decisions

    # ── Post-flight checks ───────────────────────────────────────────

    def post_flight(
        self,
        tool_name: str,
        tool_status: str,
        tool_operation: str = "",
    ) -> list[PolicyDecision]:
        """Evaluate policy after a tool invocation.

        Checks whether the tool result satisfies policy requirements.
        """
        decisions: list[PolicyDecision] = []

        # Diff-gate must pass if required
        if (tool_name == "agent-diff-gate"
                and self.get("diff_gate_required") == "true"
                and tool_status != "PASS"):
            decisions.append(PolicyDecision(
                rule="diff_gate_required",
                outcome=Outcome.DENY,
                reason=f"diff-gate required but returned {tool_status}",
                mode=self._mode.value,
                mandatory=self.is_mandatory("diff_gate_required"),
                context=f"tool={tool_name} op={tool_operation} status={tool_status}",
            ))

        # Error-log must pass if mandatory
        if (tool_name == "agent-error-log"
                and self.get("error_log_required") == "true"
                and tool_status != "PASS"
                and tool_status != "UNSUPPORTED"):
            decisions.append(PolicyDecision(
                rule="error_log_required",
                outcome=Outcome.DENY,
                reason=f"error-log required but returned {tool_status}",
                mode=self._mode.value,
                mandatory=True,
                context=f"tool={tool_name} op={tool_operation} status={tool_status}",
            ))

        # Decision-log must pass if mandatory
        if (tool_name == "agent-decision-log"
                and self.get("decision_log_required") == "true"
                and tool_status != "PASS"
                and tool_status != "UNSUPPORTED"):
            decisions.append(PolicyDecision(
                rule="decision_log_required",
                outcome=Outcome.DENY,
                reason=f"decision-log required but returned {tool_status}",
                mode=self._mode.value,
                mandatory=True,
                context=f"tool={tool_name} op={tool_operation} status={tool_status}",
            ))

        # Sandbox strict: reject any non-PASS sandbox result
        if (tool_name == "agent-sandbox"
                and self.get("sandbox_strict") == "true"
                and tool_status not in ("PASS", "UNSUPPORTED")):
            decisions.append(PolicyDecision(
                rule="sandbox_strict",
                outcome=Outcome.DENY,
                reason=f"strict sandbox: sandbox returned {tool_status}",
                mode=self._mode.value,
                context=f"tool={tool_name} op={tool_operation} status={tool_status}",
            ))

        return decisions

    # ── Internal ─────────────────────────────────────────────────────

    def _eval_rule(
        self,
        rule_name: str,
        *,
        context: str = "",
        tool_available: bool = True,
    ) -> PolicyDecision:
        """Evaluate a single rule and produce a decision."""
        rule = self._rules.get(rule_name)
        if rule is None:
            return PolicyDecision(
                rule=rule_name,
                outcome=Outcome.ALLOW,
                reason="rule not defined; defaulting to allow",
                mode=self._mode.value,
                context=context,
            )

        if rule.value == "true" and not tool_available:
            return PolicyDecision(
                rule=rule_name,
                outcome=Outcome.DENY,
                reason=f"rule '{rule_name}' requires tool but it is not available",
                mode=self._mode.value,
                mandatory=rule.mandatory,
                context=context,
            )

        if rule.value == "true" and tool_available:
            return PolicyDecision(
                rule=rule_name,
                outcome=Outcome.ALLOW,
                reason=rule.reason,
                mode=self._mode.value,
                mandatory=rule.mandatory,
                context=context,
            )

        # Rule is "false" or other — allowed
        return PolicyDecision(
            rule=rule_name,
            outcome=Outcome.ALLOW,
            reason=f"rule '{rule_name}' is '{rule.value}'; not required",
            mode=self._mode.value,
            mandatory=rule.mandatory,
            context=context,
        )


# ── Configuration parsing ────────────────────────────────────────────────

_VALID_RULE_KEYS = frozenset({
    "mode",
    "diff_gate_required",
    "sandbox_required",
    "sandbox_strict",
    "approval_required",
    "evidence_level",
    "llm_cloud_allowed",
    "host_fallback_allowed",
    "max_tool_timeout",
})


def _parse_project_config(path: Path) -> dict[str, str]:
    """Parse .orchestrator/config as key=value lines.

    Rejects unknown keys.  Returns empty dict if file missing.
    """
    import re as _re  # noqa: F811
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if key not in _VALID_RULE_KEYS:
                raise InvalidPolicyError(f"unknown config key: {key!r}")
            result[key] = val
    return result


# ── Policy loading ───────────────────────────────────────────────────────

def load_policy(
    mode_name: str,
    project_dir: Path | None = None,
) -> Policy:
    """Build the effective policy from base + mode + project layers.

    Raises InvalidPolicyError on invalid mode or configuration.
    """
    # Validate mode
    if not is_valid_mode(mode_name):
        raise InvalidPolicyError(f"invalid mode: {mode_name!r}")
    mode = Mode(mode_name)

    # Load mode rules
    mode_rules = get_mode_rules(mode)

    # Build effective rules dict
    effective: dict[str, EffectiveRule] = {}
    for r in mode_rules:
        effective[r.name] = EffectiveRule(
            name=r.name,
            value=r.value,
            mandatory=r.mandatory,
            source="base" if r.mandatory else "mode",
            reason=r.reason,
        )

    # Load and apply project overrides
    project_source = ""
    if project_dir:
        config_path = project_dir / ".orchestrator" / "config"
        try:
            project_config = _parse_project_config(config_path)
        except InvalidPolicyError:
            raise
        if project_config:
            project_source = str(config_path)
            for key, val in project_config.items():
                if key == "mode":
                    continue  # mode is set at top level
                existing = effective.get(key)
                if existing and existing.mandatory:
                    raise InvalidPolicyError(
                        f"cannot override mandatory rule: {key}"
                    )
                effective[key] = EffectiveRule(
                    name=key,
                    value=val,
                    mandatory=False,
                    source="project",
                    reason=f"project override: {key}={val}",
                )

    return Policy(mode=mode, rules=effective, project_source=project_source)


# ── Errors ───────────────────────────────────────────────────────────────

class InvalidPolicyError(Exception):
    """Raised when policy configuration is invalid."""
    pass
