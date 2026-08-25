"""Tool adapter layer — normalized interface to the 7 existing tools.

Each adapter wraps the real tool's CLI/script via subprocess, captures
stdout/stderr/exit-code, and returns a ToolResult.  Raw evidence is
never lost.

Design rules (from DESIGN.md / SECURITY.md):
  - NEVER reimplement tool functionality inside the adapter
  - NEVER use shell=True
  - NEVER fabricate results
  - NEVER bypass sandbox security
  - ALWAYS preserve raw stdout/stderr
  - ALWAYS capture exit code
  - ALWAYS apply timeouts
  - Treat tool output as untrusted data
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Result status ────────────────────────────────────────────────────────

class ResultStatus(str, Enum):
    """Normalized outcome of a tool invocation."""
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
    INVALID = "INVALID"


# ── ToolResult ───────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Normalized result from a tool invocation.

    Raw evidence (stdout, stderr, exit_code) is always preserved.
    The status field is derived from exit code + known tool conventions.
    """
    tool_name: str
    operation: str
    status: ResultStatus
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    error: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ResultStatus.PASS

    def __repr__(self) -> str:
        return (
            f"ToolResult(tool={self.tool_name!r}, op={self.operation!r}, "
            f"status={self.status.value}, exit={self.exit_code})"
        )


# ── Subprocess helper ────────────────────────────────────────────────────

def run_tool(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str, float]:
    """Run a tool command safely via subprocess.

    Returns (exit_code, stdout, stderr, duration_seconds).
    Never uses shell=True.  Always applies a timeout.
    """
    start = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            shell=False,
        )
        duration = time.monotonic() - start
        return r.returncode, r.stdout, r.stderr, duration
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return -1, "", f"timeout after {timeout}s", duration
    except OSError as exc:
        duration = time.monotonic() - start
        return -2, "", f"os error: {exc}", duration


# ── Base adapter ─────────────────────────────────────────────────────────

class BaseAdapter:
    """Abstract base for tool adapters.

    Subclasses implement ``_build_cmd`` and ``_interpret`` for each
    tool-specific operation.
    """

    TOOL_NAME: str = ""
    TOOL_DIR_NAME: str = ""  # directory name in the workspace

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.tool_dir = workspace / self.TOOL_DIR_NAME

    @property
    def available(self) -> bool:
        """True if the tool directory exists and has pyproject.toml."""
        return (self.tool_dir / "pyproject.toml").is_file()

    def _python(self) -> str:
        """Return the Python executable path."""
        return sys.executable

    def _run(
        self,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 30.0,
    ) -> ToolResult:
        """Run a command and wrap the result in a ToolResult.

        Subclasses call this from their operation methods.
        """
        exit_code, stdout, stderr, duration = run_tool(
            cmd, cwd=cwd or self.tool_dir, timeout=timeout,
        )
        return ToolResult(
            tool_name=self.TOOL_NAME,
            operation=cmd[1] if len(cmd) > 1 else cmd[0],
            status=self._interpret(exit_code, stdout, stderr),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration=duration,
        )

    def _interpret(self, exit_code: int, stdout: str, stderr: str) -> ResultStatus:
        """Map exit code to ResultStatus.  Override per-tool if needed."""
        if exit_code == -1:
            return ResultStatus.ERROR  # timeout
        if exit_code == -2:
            return ResultStatus.ERROR  # OS error
        if exit_code == 0:
            return ResultStatus.PASS
        return ResultStatus.FAIL


# ══════════════════════════════════════════════════════════════════════════
#  1. ERROR-LOG ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class ErrorLogAdapter(BaseAdapter):
    """Wraps agent-error-log (check_errors.py)."""

    TOOL_NAME = "agent-error-log"
    TOOL_DIR_NAME = "agent-error-log"

    def _script(self) -> Path:
        return self.tool_dir / "check_errors.py"

    def check(self, log_path: Path | None = None) -> ToolResult:
        """Validate the error log (health check).  Exit 0 = healthy."""
        cmd = [self._python(), str(self._script())]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def has_entry(self, area: str, log_path: Path | None = None) -> ToolResult:
        """Gate: exit 0 only if AREA is logged."""
        cmd = [self._python(), str(self._script()), "--has-entry", area]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def init_project(self, target: Path | None = None) -> ToolResult:
        """Run --init to scaffold error log in a project."""
        cmd = [self._python(), str(self._script()), "--init", "--no-tests"]
        if target:
            cmd += ["--target", str(target)]
        return self._run(cmd)

    def lessons(self, log_path: Path | None = None, apply: bool = False) -> ToolResult:
        """Distill lessons from the error log."""
        cmd = [self._python(), str(self._script()), "--lessons"]
        if apply:
            cmd.append("--apply")
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)


# ══════════════════════════════════════════════════════════════════════════
#  2. DECISION-LOG ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class DecisionLogAdapter(BaseAdapter):
    """Wraps agent-decision-log (check_decisions.py)."""

    TOOL_NAME = "agent-decision-log"
    TOOL_DIR_NAME = "agent-decision-log"

    def _script(self) -> Path:
        return self.tool_dir / "check_decisions.py"

    def check(self, log_path: Path | None = None) -> ToolResult:
        """Validate the decision log."""
        cmd = [self._python(), str(self._script())]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def has_open(self, log_path: Path | None = None) -> ToolResult:
        """Gate: exit 1 if any OPEN decision exists."""
        cmd = [self._python(), str(self._script()), "--has-open"]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def recent(self, n: int = 5, log_path: Path | None = None) -> ToolResult:
        """Show last N decisions."""
        cmd = [self._python(), str(self._script()), "--recent", str(n)]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def init_project(self, target: Path | None = None) -> ToolResult:
        """Run --init to scaffold decision log."""
        cmd = [self._python(), str(self._script()), "--init", "--no-tests"]
        if target:
            cmd += ["--target", str(target)]
        return self._run(cmd)


# ══════════════════════════════════════════════════════════════════════════
#  3. LOG-AI ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class LogAIAdapter(BaseAdapter):
    """Wraps agent-log-ai (check_logs_ai.py)."""

    TOOL_NAME = "agent-log-ai"
    TOOL_DIR_NAME = "agent-log-ai"

    def _script(self) -> Path:
        return self.tool_dir / "check_logs_ai.py"

    def check(self, model: str | None = None) -> ToolResult:
        """Ping the LLM endpoint (--check)."""
        cmd = [self._python(), str(self._script()), "--check"]
        if model:
            cmd += ["--model", model]
        return self._run(cmd, timeout=15)

    def dry_run_lessons(self, log_path: Path | None = None) -> ToolResult:
        """Preview the lessons prompt (--lessons --dry-run)."""
        cmd = [self._python(), str(self._script()), "--lessons", "--dry-run"]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd)

    def lessons(self, log_path: Path | None = None, model: str | None = None) -> ToolResult:
        """Run live LLM lesson extraction."""
        cmd = [self._python(), str(self._script()), "--lessons"]
        if model:
            cmd += ["--model", model]
        if log_path:
            cmd += ["--log", str(log_path)]
        return self._run(cmd, timeout=120)

    def review(self) -> ToolResult:
        """Analyze decision-log reversals."""
        cmd = [self._python(), str(self._script()), "--review"]
        return self._run(cmd, timeout=120)


# ══════════════════════════════════════════════════════════════════════════
#  4. MEMORY ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class MemoryAdapter(BaseAdapter):
    """Wraps agent-memory CLI."""

    TOOL_NAME = "agent-memory"
    TOOL_DIR_NAME = "agent-memory"

    def _memory_cmd(self, argv: list[str]) -> list[str]:
        """Build a Python -c command that can import agent_memory from tool_dir.

        Ensures the tool directory is on sys.path so the module is importable
        regardless of which directory the subprocess runs in.
        """
        tool_path = str(self.tool_dir).replace("\\", "/")
        return [self._python(), "-c",
                f"import sys; sys.path.insert(0, {tool_path!r}); "
                f"from agent_memory import main; "
                f"sys.argv = ['agent-memory'] + {argv!r}; main()"]

    def _run_memory(self, args: list[str], timeout: float = 30.0) -> ToolResult:
        """Run agent-memory as a module from its source directory."""
        cmd = self._memory_cmd(args)
        return self._run(cmd, cwd=self.tool_dir, timeout=timeout)

    def init(self, project_dir: Path) -> ToolResult:
        """Initialize memory store in a project."""
        cmd = self._memory_cmd(["init"])
        return self._run(cmd, cwd=project_dir)

    def status(self, project_dir: Path) -> ToolResult:
        """Check memory store health."""
        cmd = self._memory_cmd(["status"])
        return self._run(cmd, cwd=project_dir)

    def recall(self, query: str, project_dir: Path) -> ToolResult:
        """Recall trusted memories matching query."""
        cmd = self._memory_cmd(["recall", query])
        return self._run(cmd, cwd=project_dir)

    def list_memories(self, project_dir: Path) -> ToolResult:
        """List all memories."""
        cmd = self._memory_cmd(["list"])
        return self._run(cmd, cwd=project_dir)


# ══════════════════════════════════════════════════════════════════════════
#  5. BLAME ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class BlameAdapter(BaseAdapter):
    """Wraps agent-blame CLI."""

    TOOL_NAME = "agent-blame"
    TOOL_DIR_NAME = "agent-blame"

    def _blame_cmd(self, argv: list[str]) -> list[str]:
        """Build a Python -c command that can import agent_blame from tool_dir.

        Ensures the tool directory is on sys.path so the module is importable
        regardless of which directory the subprocess runs in.
        """
        tool_path = str(self.tool_dir).replace("\\", "/")
        return [self._python(), "-c",
                f"import sys; sys.path.insert(0, {tool_path!r}); "
                f"from agent_blame.cli import main; "
                f"sys.argv = ['agent-blame'] + {argv!r}; main()"]

    def _run_blame(self, args: list[str], cwd: Path | None = None,
                   timeout: float = 30.0) -> ToolResult:
        """Run agent-blame as a module from its source directory."""
        cmd = self._blame_cmd(args)
        return self._run(cmd, cwd=cwd or self.tool_dir, timeout=timeout)

    def blame(self, target: str, cwd: Path | None = None) -> ToolResult:
        """Why does this code exist? (file:line)"""
        return self._run_blame([target], cwd=cwd)

    def history(self, target: str, cwd: Path | None = None) -> ToolResult:
        """How did this code evolve?"""
        return self._run_blame(["--history", target], cwd=cwd)

    def risk(self, target: str, cwd: Path | None = None) -> ToolResult:
        """What is the removal/change risk?"""
        return self._run_blame(["--risk", target], cwd=cwd)

    def diff(self, cwd: Path | None = None) -> ToolResult:
        """Historical context for current working-tree changes."""
        return self._run_blame(["--diff"], cwd=cwd)

    def commit(self, rev: str, cwd: Path | None = None) -> ToolResult:
        """Historical context for a specific commit."""
        return self._run_blame(["--commit", rev], cwd=cwd)


# ══════════════════════════════════════════════════════════════════════════
#  6. DIFF-GATE ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class DiffGateAdapter(BaseAdapter):
    """Wraps agent-diff-gate (check_diff.py)."""

    TOOL_NAME = "agent-diff-gate"
    TOOL_DIR_NAME = "agent-diff-gate"

    def _script(self) -> Path:
        return self.tool_dir / "check_diff.py"

    def check_staged(self, cwd: Path | None = None) -> ToolResult:
        """Validate staged changes (git diff --cached)."""
        cmd = [self._python(), str(self._script()), "--staged"]
        return self._run(cmd, cwd=cwd)

    def check_range(self, a: str, b: str, cwd: Path | None = None) -> ToolResult:
        """Validate diff between two refs."""
        cmd = [self._python(), str(self._script()), "--range", a, b]
        return self._run(cmd, cwd=cwd)

    def check_file(self, path: Path, cwd: Path | None = None) -> ToolResult:
        """Validate a diff from a file."""
        cmd = [self._python(), str(self._script()), "--file", str(path)]
        return self._run(cmd, cwd=cwd)

    def list_rules(self) -> ToolResult:
        """List all built-in and plugin rules."""
        cmd = [self._python(), str(self._script()), "--list-rules"]
        return self._run(cmd)


# ══════════════════════════════════════════════════════════════════════════
#  7. SANDBOX ADAPTER
# ══════════════════════════════════════════════════════════════════════════

class SandboxAdapter(BaseAdapter):
    """Wraps agent-sandbox CLI.

    SECURITY: This adapter preserves the sandbox's fail-closed model.
    On unsupported platforms it returns UNSUPPORTED — never falls back
    to host execution.
    """

    TOOL_NAME = "agent-sandbox"
    TOOL_DIR_NAME = "agent-sandbox"

    @property
    def available(self) -> bool:
        """Sandbox is available only on Linux."""
        if sys.platform != "linux":
            return False
        return (self.tool_dir / "pyproject.toml").is_file()

    @property
    def supported(self) -> bool:
        """True if the current platform can run the sandbox."""
        return sys.platform == "linux"

    def run(self, command: list[str], *, project_dir: Path | None = None,
            timeout: float = 60.0) -> ToolResult:
        """Execute a command inside the sandbox.

        On unsupported platforms: returns UNSUPPORTED (never executes on host).
        """
        if not self.supported:
            return ToolResult(
                tool_name=self.TOOL_NAME,
                operation="run",
                status=ResultStatus.UNSUPPORTED,
                exit_code=-1,
                error=f"agent-sandbox requires Linux, current platform is {sys.platform}",
            )
        # Build the sandbox CLI invocation
        cmd = [self._python(), "-c",
               "from agent_sandbox.cli import main; import sys; "
               f"sys.argv = ['agent-sandbox', 'run'] + {command!r}; main()"]
        return self._run(cmd, cwd=project_dir or self.tool_dir, timeout=timeout)

    def health(self) -> ToolResult:
        """Check sandbox availability."""
        if not self.supported:
            return ToolResult(
                tool_name=self.TOOL_NAME,
                operation="health",
                status=ResultStatus.UNSUPPORTED,
                exit_code=-1,
                error=f"requires Linux, current platform is {sys.platform}",
            )
        cmd = [self._python(), "-c",
               "from agent_sandbox.cli import main; import sys; "
               "sys.argv = ['agent-sandbox', 'health']; main()"]
        return self._run(cmd, cwd=self.tool_dir, timeout=15)


# ══════════════════════════════════════════════════════════════════════════
#  ADAPTER REGISTRY
# ══════════════════════════════════════════════════════════════════════════

ADAPTER_CLASSES: dict[str, type[BaseAdapter]] = {
    "agent-error-log": ErrorLogAdapter,
    "agent-decision-log": DecisionLogAdapter,
    "agent-log-ai": LogAIAdapter,
    "agent-memory": MemoryAdapter,
    "agent-blame": BlameAdapter,
    "agent-diff-gate": DiffGateAdapter,
    "agent-sandbox": SandboxAdapter,
}


def get_adapter(tool_name: str, workspace: Path) -> BaseAdapter | None:
    """Return an adapter instance for *tool_name*, or None if unknown."""
    cls = ADAPTER_CLASSES.get(tool_name)
    if cls is None:
        return None
    return cls(workspace)


def get_all_adapters(workspace: Path) -> dict[str, BaseAdapter]:
    """Return adapter instances for all 7 canonical tools."""
    return {name: cls(workspace) for name, cls in ADAPTER_CLASSES.items()}
