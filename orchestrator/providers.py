"""AI provider adapters — local-first, zero-dependency.

Providers are the bridge between the orchestrator and AI models.
They are SEPARATE from the orchestration/policy layer.

The orchestrator must not be coupled to any specific provider.
Providers must work without API keys where possible (local-first).

Design: PHASE_6_MULTI_AGENT_DESIGN.md §25-29
         PHASE_11_FREEBUFF_CLI_DESIGN.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol


# ── Provider status ──────────────────────────────────────────────────────

class ProviderStatus(str, Enum):
    """Status of an AI provider."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


# ── Provider response ───────────────────────────────────────────────────

@dataclass
class ProviderResponse:
    """Normalized response from an AI provider."""
    text: str = ""
    model: str = ""
    status: ProviderStatus = ProviderStatus.AVAILABLE
    tokens_used: int = 0
    duration: float = 0.0
    error: str = ""
    raw: str = ""  # raw response (for evidence)

    @property
    def ok(self) -> bool:
        return self.status == ProviderStatus.AVAILABLE and bool(self.text)


# ── Provider protocol ────────────────────────────────────────────────────

class AIProvider(Protocol):
    """Interface that all AI providers must implement."""

    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool: ...

    def complete(
        self,
        prompt: str,
        *,
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> ProviderResponse: ...

    def health(self) -> ProviderStatus: ...


# ── NoneProvider ─────────────────────────────────────────────────────────

class NoneProvider:
    """Provider that returns no AI response.

    Used when no AI model is available.  Deterministic-only agents
    can still function; AI-dependent agents are marked BLOCKED.
    """

    @property
    def name(self) -> str:
        return "none"

    @property
    def available(self) -> bool:
        return True  # always "available" — just produces no output

    def complete(
        self,
        prompt: str,
        *,
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> ProviderResponse:
        return ProviderResponse(
            text="",
            model="none",
            status=ProviderStatus.UNAVAILABLE,
            error="no AI provider configured",
        )

    def health(self) -> ProviderStatus:
        return ProviderStatus.UNAVAILABLE


# ── OllamaProvider ──────────────────────────────────────────────────────

class OllamaProvider:
    """Adapter for Ollama local models.

    Uses urllib (stdlib) — no requests/httpx dependency.
    Default endpoint: http://localhost:11434
    No API key required.
    """

    def __init__(self, base_url: str = "http://localhost:11434"):
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def available(self) -> bool:
        return self.health() == ProviderStatus.AVAILABLE

    def health(self) -> ProviderStatus:
        """Ping Ollama to check availability."""
        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return ProviderStatus.AVAILABLE
            return ProviderStatus.UNAVAILABLE
        except (urllib.error.URLError, OSError, TimeoutError):
            return ProviderStatus.UNAVAILABLE

    def complete(
        self,
        prompt: str,
        *,
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> ProviderResponse:
        """Send a prompt to Ollama and return the completion."""
        import time
        start = time.monotonic()

        if not model:
            model = self._default_model()

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                duration = time.monotonic() - start

                return ProviderResponse(
                    text=data.get("response", ""),
                    model=model,
                    status=ProviderStatus.AVAILABLE,
                    tokens_used=data.get("eval_count", 0),
                    duration=duration,
                    raw=raw[:5000],  # cap for evidence
                )
        except urllib.error.URLError as exc:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.UNAVAILABLE,
                duration=duration,
                error=f"Ollama connection error: {exc}",
            )
        except TimeoutError:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.TIMEOUT,
                duration=duration,
                error=f"Ollama timeout after {timeout}s",
            )
        except (json.JSONDecodeError, KeyError) as exc:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                duration=duration,
                error=f"Ollama response parse error: {exc}",
            )
        except OSError as exc:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                duration=duration,
                error=f"Ollama OS error: {exc}",
            )

    def _default_model(self) -> str:
        """Try to detect the default Ollama model."""
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                if models:
                    return models[0].get("name", "llama2")
        except Exception:  # noqa: BLE001
            pass
        return "llama2"


# ── CLIProvider ──────────────────────────────────────────────────────────

class CLIProvider:
    """Base provider for CLI-based AI tools.

    Invokes an external CLI executable via subprocess.
    No API key required.  No network access required.
    Prompts are delivered via stdin (not command-line arguments).
    shell=False is always enforced.

    Design: PHASE_11_FREEBUFF_CLI_DESIGN.md
    """

    # Maximum output size in bytes
    DEFAULT_MAX_OUTPUT = 100_000

    def __init__(
        self,
        executable: str,
        args: list[str] | None = None,
        work_dir: str | None = None,
        timeout: float = 60.0,
        max_output: int = DEFAULT_MAX_OUTPUT,
        provider_name: str = "cli",
    ):
        self._executable = executable
        self._args = list(args) if args else []
        self._work_dir = work_dir
        self._timeout = timeout
        self._max_output = max_output
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def available(self) -> bool:
        return self.health() == ProviderStatus.AVAILABLE

    def health(self) -> ProviderStatus:
        """Check if the CLI executable is available."""
        if shutil.which(self._executable):
            return ProviderStatus.AVAILABLE
        return ProviderStatus.UNAVAILABLE

    def complete(
        self,
        prompt: str,
        *,
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> ProviderResponse:
        """Execute the CLI with the prompt via stdin.

        Security:
          - shell=False always enforced
          - Prompt delivered via stdin (not arguments)
          - Argument list constructed from config only
          - Output validated before return
          - Timeout enforced
        """
        start = time.monotonic()

        # Use instance timeout if caller timeout is default
        effective_timeout = timeout if timeout != 60.0 else self._timeout

        # Check executable exists and resolve to full path
        resolved = shutil.which(self._executable)
        if not resolved:
            return ProviderResponse(
                status=ProviderStatus.UNAVAILABLE,
                error=f"executable not found: {self._executable}",
            )

        # Construct argument list — NO shell concatenation
        # Use resolved full path to handle Windows .cmd/.bat wrappers
        cmd: list[str] = [resolved] + self._args

        try:
            result = subprocess.run(
                cmd,
                input=prompt,  # prompt via stdin, not arguments
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                shell=False,  # NEVER True
                cwd=self._work_dir,
            )
            duration = time.monotonic() - start

            stdout = result.stdout[:self._max_output]
            stderr = result.stderr[:self._max_output]
            exit_code = result.returncode

            # Validate output
            valid, reason = self._validate_output(stdout, stderr)
            if not valid:
                return ProviderResponse(
                    status=ProviderStatus.ERROR,
                    duration=duration,
                    error=f"output validation failed: {reason}",
                    raw=stdout[:5000],
                )

            # Check exit code
            if exit_code != 0:
                return ProviderResponse(
                    status=ProviderStatus.ERROR,
                    duration=duration,
                    error=f"CLI exited with code {exit_code}: {stderr[:500]}",
                    raw=stdout[:5000],
                )

            # Success
            return ProviderResponse(
                text=stdout.strip(),
                model=model or self._provider_name,
                status=ProviderStatus.AVAILABLE,
                duration=duration,
                raw=stdout[:5000],
            )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.TIMEOUT,
                duration=duration,
                error=f"CLI timeout after {effective_timeout}s",
            )
        except FileNotFoundError:
            return ProviderResponse(
                status=ProviderStatus.UNAVAILABLE,
                error=f"executable not found: {self._executable}",
            )
        except OSError as exc:
            duration = time.monotonic() - start
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                duration=duration,
                error=f"CLI OS error: {exc}",
            )

    def _validate_output(
        self, stdout: str, stderr: str
    ) -> tuple[bool, str]:
        """Validate CLI output.  Returns (valid, reason)."""
        # Null bytes
        if "\x00" in stdout:
            return False, "null bytes in stdout"
        if "\x00" in stderr:
            return False, "null bytes in stderr"

        # Binary content detection
        if stdout:
            encoded = stdout.encode("utf-8", errors="replace")
            non_text = sum(1 for b in encoded if b > 127)
            if len(encoded) > 0 and non_text / len(encoded) > 0.3:
                return False, "suspected binary content in stdout"

        return True, "ok"


# ── FreebuffProvider ──────────────────────────────────────────────────────

class FreebuffProvider(CLIProvider):
    """Provider for FreeBuff CLI AI.

    Invokes FreeBuff as a subprocess.  No API key required.
    FreeBuff must be installed and available on PATH.

    Design: PHASE_11_FREEBUFF_CLI_DESIGN.md
    """

    def __init__(
        self,
        executable: str = "freebuff",
        args: list[str] | None = None,
        work_dir: str | None = None,
        timeout: float = 60.0,
    ):
        # FreeBuff-specific defaults
        default_args = ["--no-banner", "--output", "text"]
        merged_args = default_args + (args or [])
        super().__init__(
            executable=executable,
            args=merged_args,
            work_dir=work_dir,
            timeout=timeout,
            provider_name="freebuff",
        )


# ── Provider registry ────────────────────────────────────────────────────

def get_provider(name: str, **kwargs) -> AIProvider:
    """Return a provider instance by name.

    Supported: "ollama", "none", "freebuff", "cli".
    """
    if name == "ollama":
        return OllamaProvider(**kwargs)
    if name == "freebuff":
        return FreebuffProvider(**kwargs)
    if name == "cli":
        # Generic CLI provider — requires executable in kwargs
        executable = kwargs.pop("executable", "")
        if not executable:
            return NoneProvider()
        return CLIProvider(executable=executable, **kwargs)
    return NoneProvider()


def list_providers() -> list[str]:
    """Return available provider names."""
    return ["ollama", "none", "freebuff", "cli"]
