"""Security scanner for tool and agent output.

Provides deterministic pattern-based scanning of tool output and agent
proposals for suspicious or dangerous content.

Design (from PHASE_8_HARDENING_DESIGN.md):
  - Detect suspicious patterns in tool/agent output
  - Flag shell commands, file deletion, network commands
  - Flag --no-verify attempts
  - Record findings as evidence (WARN, not hard block)
  - Deterministic-first (no LLM required)
  - Standard-library only

Security:
  - Findings are recorded, not silently discarded
  - Scanner does not execute or modify any content
  - Scanner is purely observational
  - Findings influence policy decisions, not bypass them
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Severity levels ──────────────────────────────────────────────────────

class Severity(str, Enum):
    """Security finding severity."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Finding categories ───────────────────────────────────────────────────

class Category(str, Enum):
    """Security finding category."""
    SHELL_COMMAND = "shell_command"
    FILE_DELETION = "file_deletion"
    NETWORK = "network"
    BYPASS_ATTEMPT = "bypass_attempt"
    PERMISSION_ESCALATION = "permission_escalation"
    CODE_INJECTION = "code_injection"
    PATH_TRAVERSAL = "path_traversal"
    SECRET_EXPOSURE = "secret_exposure"
    UNTRUSTED_EXECUTION = "untrusted_execution"


# ── Finding ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SecurityFinding:
    """A single security finding from a scan."""
    severity: Severity
    category: Category
    description: str
    line: str = ""
    line_number: int = 0
    pattern: str = ""


# ── Scan result ──────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    """Result of a security scan."""
    findings: list[SecurityFinding] = field(default_factory=list)
    scanned_bytes: int = 0
    scan_time_ms: float = 0.0

    @property
    def has_findings(self) -> bool:
        return len(self.findings) > 0

    @property
    def max_severity(self) -> Severity:
        if not self.findings:
            return Severity.LOW
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return max(self.findings, key=lambda f: order.index(f.severity)).severity

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def by_severity(self, severity: Severity) -> list[SecurityFinding]:
        return [f for f in self.findings if f.severity == severity]

    def by_category(self, category: Category) -> list[SecurityFinding]:
        return [f for f in self.findings if f.category == category]


# ── Pattern definitions ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ScanPattern:
    """A single scanning pattern."""
    regex: re.Pattern[str]
    severity: Severity
    category: Category
    description: str


# Compile all patterns once at module load time
_SCAN_PATTERNS: list[ScanPattern] = [
    # ── Git bypass attempts ──────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"git\s+commit\s+--no-verify", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.BYPASS_ATTEMPT,
        description="git commit --no-verify bypass attempt",
    ),
    ScanPattern(
        regex=re.compile(r"git\s+push\s+--force", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.BYPASS_ATTEMPT,
        description="git push --force (history rewrite risk)",
    ),
    ScanPattern(
        regex=re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.FILE_DELETION,
        description="git reset --hard (uncommitted work loss)",
    ),
    ScanPattern(
        regex=re.compile(r"git\s+clean\s+-[^\s]*f", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.FILE_DELETION,
        description="git clean -f (untracked file removal)",
    ),

    # ── Destructive file operations ──────────────────────────────────
    ScanPattern(
        regex=re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.FILE_DELETION,
        description="recursive deletion of root filesystem",
    ),
    ScanPattern(
        regex=re.compile(r"rm\s+-rf\s+~", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.FILE_DELETION,
        description="recursive deletion of home directory",
    ),
    ScanPattern(
        regex=re.compile(r"rm\s+-rf\s+\*", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.FILE_DELETION,
        description="recursive wildcard deletion",
    ),
    ScanPattern(
        regex=re.compile(r"rmdir\s+/[^ ]+", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.FILE_DELETION,
        description="directory removal",
    ),
    ScanPattern(
        regex=re.compile(r"format\s+[a-z]:", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.FILE_DELETION,
        description="disk format attempt",
    ),

    # ── Permission escalation ────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"chmod\s+777", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.PERMISSION_ESCALATION,
        description="world-writable permissions (chmod 777)",
    ),
    ScanPattern(
        regex=re.compile(r"chmod\s+[0-7]*7[0-7]*7", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.PERMISSION_ESCALATION,
        description="broad permission grant",
    ),
    ScanPattern(
        regex=re.compile(r"sudo\s+", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.PERMISSION_ESCALATION,
        description="sudo privilege escalation",
    ),
    ScanPattern(
        regex=re.compile(r"chown\s+root", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.PERMISSION_ESCALATION,
        description="ownership change to root",
    ),

    # ── Remote code execution ────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"curl\s+[^|]*\|\s*(ba)?sh", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.UNTRUSTED_EXECUTION,
        description="remote code execution via curl pipe to shell",
    ),
    ScanPattern(
        regex=re.compile(r"wget\s+[^|]*\|\s*(ba)?sh", re.IGNORECASE),
        severity=Severity.CRITICAL,
        category=Category.UNTRUSTED_EXECUTION,
        description="remote code execution via wget pipe to shell",
    ),
    ScanPattern(
        regex=re.compile(r"eval\s*\(", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.CODE_INJECTION,
        description="dynamic code evaluation (eval)",
    ),
    ScanPattern(
        regex=re.compile(r"exec\s*\(", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.CODE_INJECTION,
        description="dynamic code execution (exec)",
    ),
    ScanPattern(
        regex=re.compile(r"__import__\s*\(", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.CODE_INJECTION,
        description="dynamic import (__import__)",
    ),
    ScanPattern(
        regex=re.compile(r"subprocess\.\w+\(.*shell\s*=\s*True", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.SHELL_COMMAND,
        description="shell=True subprocess call",
    ),
    ScanPattern(
        regex=re.compile(r"os\.system\s*\(", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.SHELL_COMMAND,
        description="os.system() shell execution",
    ),
    ScanPattern(
        regex=re.compile(r"os\.popen\s*\(", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.SHELL_COMMAND,
        description="os.popen() shell execution",
    ),

    # ── Network ──────────────────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"nc\s+-[^\s]*l", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.NETWORK,
        description="netcat listener (reverse shell risk)",
    ),
    ScanPattern(
        regex=re.compile(r"python[23]?\s+-m\s+http\.server", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.NETWORK,
        description="HTTP server started",
    ),
    ScanPattern(
        regex=re.compile(r"ssh\s+-R\s+", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.NETWORK,
        description="SSH reverse tunnel",
    ),

    # ── Path traversal ───────────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"\.\./\.\./\.\.", re.IGNORECASE),
        severity=Severity.MEDIUM,
        category=Category.PATH_TRAVERSAL,
        description="triple parent directory traversal",
    ),

    # ── Secret exposure ──────────────────────────────────────────────
    ScanPattern(
        regex=re.compile(r"(api[_-]?key|token|password|secret)\s*[=:]\s*\S{8,}", re.IGNORECASE),
        severity=Severity.HIGH,
        category=Category.SECRET_EXPOSURE,
        description="potential secret in output",
    ),
]


# ── Scanner ──────────────────────────────────────────────────────────────

def scan_text(text: str) -> ScanResult:
    """Scan text content for suspicious patterns.

    Returns a ScanResult with all findings.  This is deterministic
    and does not execute or modify any content.
    """
    import time
    start = time.monotonic()

    findings: list[SecurityFinding] = []
    scanned_bytes = len(text.encode("utf-8", errors="replace"))

    for line_num, line in enumerate(text.splitlines(), 1):
        for pattern in _SCAN_PATTERNS:
            if pattern.regex.search(line):
                findings.append(SecurityFinding(
                    severity=pattern.severity,
                    category=pattern.category,
                    description=pattern.description,
                    line=line.strip()[:200],  # cap line length
                    line_number=line_num,
                    pattern=pattern.regex.pattern,
                ))

    elapsed = (time.monotonic() - start) * 1000
    return ScanResult(
        findings=findings,
        scanned_bytes=scanned_bytes,
        scan_time_ms=round(elapsed, 2),
    )


def scan_tool_output(
    stdout: str,
    stderr: str,
    tool_name: str = "",
) -> ScanResult:
    """Scan tool output (stdout + stderr) for suspicious patterns.

    Combines findings from both streams.
    """
    combined = f"=== STDOUT ({tool_name}) ===\n{stdout}\n=== STDERR ({tool_name}) ===\n{stderr}"
    return scan_text(combined)


def scan_agent_proposal(text: str, agent_role: str = "") -> ScanResult:
    """Scan an agent's proposed output for dangerous patterns.

    Agent output is treated as untrusted and may contain injection
    attempts or dangerous instructions.
    """
    prefix = f"=== AGENT ({agent_role}) ===\n" if agent_role else ""
    return scan_text(prefix + text)


# ── Convenience ──────────────────────────────────────────────────────────

def has_critical_findings(result: ScanResult) -> bool:
    """Check if a scan result contains any CRITICAL findings."""
    return any(f.severity == Severity.CRITICAL for f in result.findings)


def finding_summary(result: ScanResult) -> str:
    """Generate a human-readable summary of scan findings."""
    if not result.findings:
        return "No security findings."

    lines = [f"Security scan: {result.finding_count} finding(s)"]
    for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
        items = result.by_severity(sev)
        if items:
            lines.append(f"  [{sev.value}] {len(items)} finding(s)")
            for f in items:
                lines.append(f"    - {f.description} (line {f.line_number})")
    return "\n".join(lines)
