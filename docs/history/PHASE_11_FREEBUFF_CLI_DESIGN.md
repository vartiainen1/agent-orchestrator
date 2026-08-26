# Phase 11 — FreeBuff / CLI AI Integration Design

## 1. Objective

Design a CLI-based AI provider integration that allows the orchestrator to
invoke external AI CLIs (such as FreeBuff) as agent backends, without requiring
API keys, without creating dependencies on any specific CLI, and without
weakening the existing security model.

The provider must be a drop-in replacement for OllamaProvider that works
through subprocess invocation of an external CLI rather than HTTP API calls.

## 2. Scope

- New `CLIProvider` base class for CLI-based AI providers
- New `FreebuffProvider` extending CLIProvider
- Configuration for CLI executable, arguments, working directory
- Process execution with timeout, stdout/stderr capture, exit code validation
- Output validation and security scanning
- Integration with existing provider registry
- Integration with existing agent/scheduler architecture
- Evidence recording for all CLI interactions
- All four operating modes (SOLO, DEVELOPMENT, SECURITY, ENTERPRISE)

## 3. Non-goals

- Building a FreeBuff-specific protocol or API
- Requiring FreeBuff to be installed
- Modifying FreeBuff's source code
- Creating a plugin framework
- Adding external dependencies
- Implementing agent-to-agent communication through CLI
- Building a web UI or REST API
- Modifying the 7 existing tool repositories

## 4. Architecture

```
AIProvider (Protocol)
    |
    +-- NoneProvider          (no AI, deterministic agents only)
    +-- OllamaProvider        (HTTP API, local models)
    +-- CLIProvider           (subprocess, any CLI AI)
           |
           +-- FreebuffProvider   (FreeBuff-specific config)
           +-- future CLI providers (custom CLIs)
```

The CLIProvider is a generic base that handles:
- Process spawning (subprocess.run with argument list)
- Timeout enforcement
- stdout/stderr capture
- Exit code validation
- Output size limits
- Security scanning
- Evidence recording

FreebuffProvider adds:
- FreeBuff-specific default arguments
- FreeBuff-specific output parsing (if needed)
- FreeBuff-specific health check

## 5. Provider Abstraction

### 5.1 Existing AIProvider Protocol (unchanged)

```python
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def available(self) -> bool: ...
    def complete(self, prompt, *, model, max_tokens, temperature, timeout) -> ProviderResponse: ...
    def health(self) -> ProviderStatus: ...
```

### 5.2 CLIProvider implements AIProvider

```python
class CLIProvider:
    """Base provider for CLI-based AI tools.
    
    Invokes an external CLI executable via subprocess.
    No API key required.  No network access required.
    """
    
    def __init__(
        self,
        executable: str,          # e.g., "freebuff", "python -m freebuff"
        args: list[str] | None,   # extra arguments
        work_dir: str | None,     # working directory
        timeout: float = 60.0,    # default timeout
        max_output: int = 100_000, # max output bytes
    ): ...
```

## 6. CLI Provider Design

### 6.1 Process execution model

```
CLIProvider.complete(prompt)
    |
    +-- Validate executable exists (shutil.which)
    +-- Construct argument list: [executable, *args, prompt_via_stdin_or_arg]
    +-- subprocess.run(
            args,
            input=prompt,          # prompt via stdin (not shell interpolation)
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,           # NEVER True
            cwd=work_dir,
        )
    +-- Validate exit code
    +-- Validate output size
    +-- Security scan output
    +-- Return ProviderResponse
```

Key properties:
- **shell=False always**: Arguments passed as list, never concatenated into shell string
- **Prompt via stdin**: Prompt sent as process input, not command-line argument (avoids argument injection, length limits, and shell escaping issues)
- **Timeout enforced**: subprocess.run timeout parameter
- **Output capped**: Read limited bytes to prevent memory exhaustion
- **Exit code validated**: Non-zero = error (unless provider defines specific codes)

### 6.2 Prompt delivery

Two options considered:

**Option A: Prompt as stdin (RECOMMENDED)**
```python
subprocess.run(
    [executable, *args],
    input=prompt,
    capture_output=True,
    text=True,
    timeout=timeout,
    shell=False,
)
```
Advantages:
- No argument injection risk
- No shell escaping needed
- No command-line length limits
- Clean separation of command and data

**Option B: Prompt as argument**
```python
subprocess.run(
    [executable, *args, prompt],
    capture_output=True,
    text=True,
    timeout=timeout,
    shell=False,
)
```
Disadvantages:
- Command-line length limits (Windows: ~32K, Linux: ~2MB)
- Argument injection if prompt contains special characters
- Shell escaping concerns if caller constructs string

**Decision**: Option A (stdin).  The CLI reads from stdin by default.
FreeBuff already supports stdin input.

### 6.3 Output handling

The CLI's stdout is the AI response.  The CLI's stderr is diagnostic/error info.

```python
result = subprocess.run(...)
stdout = result.stdout[:max_output]  # cap
stderr = result.stderr[:max_output]  # cap
exit_code = result.returncode
```

Output validation:
- Null bytes → reject
- Binary content ratio > 30% → reject
- Size > max_output → reject (already capped by reading)
- Exit code 0 → success (unless provider defines otherwise)
- Exit code non-zero → ERROR status with stderr as error message

## 7. FreeBuff Provider Design

### 7.1 FreebuffProvider

```python
class FreebuffProvider(CLIProvider):
    """Provider for FreeBuff CLI AI.
    
    Invokes FreeBuff as a subprocess.  No API key required.
    FreeBuff must be installed and available on PATH.
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
        )
```

### 7.2 FreeBuff health check

```python
def health(self) -> ProviderStatus:
    """Check if FreeBuff CLI is available."""
    import shutil
    if shutil.which(self._executable):
        return ProviderStatus.AVAILABLE
    return ProviderStatus.UNAVAILABLE
```

### 7.3 FreeBuff does NOT require an API key

FreeBuff is a local CLI tool.  It reads from stdin and writes to stdout.
No API key, no cloud service, no network access required for local operation.

If FreeBuff needs configuration (e.g., model selection), it is passed
through the `args` parameter, not through environment variables containing
secrets.

## 8. Configuration Design

### 8.1 Provider configuration in `.orchestrator/config`

```ini
# Provider selection
provider = freebuff

# CLI provider settings (used when provider = freebuff or other CLI)
provider_executable = freebuff
provider_args = --no-banner --output text
provider_work_dir =
provider_timeout = 60
```

### 8.2 Configuration validation

| Key | Type | Default | Constraints |
|-----|------|---------|-------------|
| provider | enum | ollama | ollama, none, freebuff, cli |
| provider_executable | string | freebuff | non-empty, safe filename |
| provider_args | string | "" | space-separated args |
| provider_work_dir | string | "" | valid directory path |
| provider_timeout | int | 60 | 1-3600 |

### 8.3 CLI arguments construction

The `provider_args` string is split into a list using simple whitespace
splitting (not shell splitting).  This avoids shell injection.

```python
args_string = config.get("provider_args", "")
args = args_string.split() if args_string else []
```

Security: `shlex.split()` is NOT used because it interprets quotes and
escapes which could be exploited.  Simple `str.split()` treats each
whitespace-separated token as a literal argument.

## 9. Process Execution Model

### 9.1 Execution flow

```
CLIProvider.complete(prompt)
    |
    +-- 1. Validate executable exists
    |       shutil.which(executable) → FileNotFoundError → UNAVAILABLE
    |
    +-- 2. Construct argument list
    |       [executable, *args]
    |       NO shell concatenation
    |
    +-- 3. Execute subprocess
    |       subprocess.run(
    |           [executable, *args],
    |           input=prompt,        # stdin
    |           capture_output=True,
    |           text=True,
    |           timeout=timeout,
    |           shell=False,         # NEVER True
    |           cwd=work_dir,
    |       )
    |
    +-- 4. Handle exceptions
    |       TimeoutExpired → TIMEOUT
    |       FileNotFoundError → UNAVAILABLE
    |       OSError → ERROR
    |
    +-- 5. Validate output
    |       null bytes → reject
    |       binary content → reject
    |       size > max_output → reject
    |
    +-- 6. Validate exit code
    |       0 → success
    |       non-zero → ERROR (unless provider defines otherwise)
    |
    +-- 7. Return ProviderResponse
            text = stdout
            status = AVAILABLE/ERROR/TIMEOUT/UNAVAILABLE
            raw = stdout[:5000]  # for evidence
```

### 9.2 Security properties

| Threat | Mitigation |
|--------|------------|
| Command injection | shell=False, argument list, prompt via stdin |
| Malicious arguments | Args from config only, validated |
| PATH manipulation | shutil.which uses system PATH (acceptable) |
| Working directory traversal | work_dir validated if provided |
| Prompt injection in stdin | Prompt is data, not commands; output goes through security scan |
| Oversized output | max_output cap, output truncated |
| Hanging process | subprocess.run timeout |
| Secret leakage | Prompt not logged; output redacted in evidence |
| Provider impersonation | Executable validated via shutil.which |
| Unexpected exit codes | Non-zero treated as ERROR |
| Malformed output | Validated (null bytes, binary, size) |
| Provider executing tools | Provider output treated as untrusted; goes through security scan |
| Provider bypassing policy | Provider is BELOW policy engine in architecture |

## 10. Timeout Handling

```python
try:
    result = subprocess.run(..., timeout=timeout)
except subprocess.TimeoutExpired:
    # Kill the process
    result.kill()
    result.wait()
    return ProviderResponse(
        status=ProviderStatus.TIMEOUT,
        error=f"CLI timeout after {timeout}s",
    )
```

Default timeout: 60 seconds (configurable via `provider_timeout`).
Maximum timeout: 3600 seconds (enforced by config validation).

## 11. stdout/stderr Handling

- **stdout**: AI response text.  Stored in `ProviderResponse.text`.
- **stderr**: Diagnostic/error info.  Included in `ProviderResponse.error` if exit code != 0.
- Both capped at `max_output` bytes (default 100KB).
- Both scanned for security patterns before use.
- Raw stdout stored in `ProviderResponse.raw` (capped at 5000 chars for evidence).

## 12. Exit Code Handling

| Exit Code | ProviderResponse Status | Behavior |
|:---------:|:-----------------------:|----------|
| 0 | AVAILABLE | Normal — text is the AI response |
| 1 | ERROR | CLI reported an error |
| 2 | ERROR | CLI usage error |
| 126 | ERROR | Permission denied |
| 127 | UNAVAILABLE | Command not found |
| 137 | ERROR | Killed (SIGKILL) |
| 143 | ERROR | Terminated (SIGTERM) |
| other | ERROR | Unknown error |

## 13. Output Validation

```python
def _validate_output(self, stdout: str, stderr: str) -> tuple[bool, str]:
    """Validate CLI output.  Returns (valid, reason)."""
    # Null bytes
    if "\x00" in stdout:
        return False, "null bytes in stdout"
    
    # Binary content detection
    encoded = stdout.encode("utf-8", errors="replace")
    non_text = sum(1 for b in encoded if b > 127)
    if len(encoded) > 0 and non_text / len(encoded) > 0.3:
        return False, "suspected binary content"
    
    return True, "ok"
```

## 14. Security Threat Model

| Threat | Severity | Mitigation |
|--------|:--------:|------------|
| Command injection via executable | CRITICAL | shutil.which validation, shell=False |
| Argument injection via prompt | CRITICAL | Prompt via stdin, not arguments |
| Shell injection via args | HIGH | Args from config, split() not shlex |
| PATH manipulation | MEDIUM | shutil.which uses system PATH (acceptable for local CLI) |
| Malicious AI output | HIGH | Security scan (26 patterns) applied to response |
| Prompt injection in AI response | HIGH | Output treated as untrusted data |
| Oversized output DoS | MEDIUM | max_output cap |
| Hanging process | MEDIUM | subprocess timeout |
| Secret in prompt | MEDIUM | Prompt not logged; redaction in evidence |
| Provider impersonation | LOW | Executable validated via shutil.which |
| Provider executing tools directly | HIGH | Provider output goes through security scan + policy |
| Provider bypassing policy | CRITICAL | Provider is below PolicyEngine in architecture |
| Provider modifying files | HIGH | cwd validation; no file-write capabilities in provider |
| Provider spawning subprocesses | LOW | Provider is the only subprocess; its output is scanned |
| Cross-platform issues | LOW | subprocess.run is cross-platform; shell=False on all |

## 15. Secret Handling

- Prompt text is NOT logged (only "prompt_sent" action recorded)
- CLI output is scanned for secrets (existing security_scan patterns)
- Evidence records redacted output (existing redaction)
- No environment variables containing secrets are passed to CLI
- No API keys are required or stored
- CLI arguments are from config (not from user input at runtime)

## 16. Agent Permission Enforcement

The CLI provider operates WITHIN the existing agent permission model:

```
Agent (with permissions)
    |
    +-- Scheduler checks tool permissions
    |
    +-- CLIProvider.complete() invoked
    |
    +-- Output returned as AgentResult
    |
    +-- Orchestrator decides next action
```

The provider does NOT:
- Grant itself permissions
- Bypass tool permission checks
- Override agent role restrictions
- Self-assign tasks

## 17. Policy Integration

The CLI provider is subject to the same policy rules as OllamaProvider:

```python
# In policy pre-flight:
if policy.get("llm_cloud_allowed") == "false":
    # SECURITY/ENTERPRISE mode
    # CLI provider is LOCAL (no cloud), so it IS allowed
    # Only cloud providers are blocked
    pass
```

Important distinction: FreeBuff is a LOCAL CLI tool.  It does not access
the cloud.  Therefore SECURITY/ENTERPRISE modes that block cloud LLM
do NOT block FreeBuff.  FreeBuff is treated as a local provider like Ollama.

If a future CLI provider IS cloud-based, the policy should block it.
This is handled by configuration, not by hardcoded provider names.

## 18. Mode Integration

| Mode | CLI Provider Behavior |
|------|----------------------|
| SOLO | Allowed.  No restrictions. |
| DEVELOPMENT | Allowed.  No restrictions. |
| SECURITY | Allowed (local CLI, not cloud).  Output scanned. |
| ENTERPRISE | Allowed (local CLI, not cloud).  Output scanned.  Evidence recorded. |

If `provider = cloud_cli` (future), SECURITY/ENTERPRISE would block it
via the existing `llm_cloud_allowed` policy rule.

## 19. Evidence Integration

Every CLI provider interaction records evidence:

```python
evidence.record(
    action="provider_cli_invoked",
    tool=self.name,
    operation="complete",
    args=[self._executable],  # prompt NOT included (secret)
    exit_code=result.returncode,
    status=response.status.value,
    duration=response.duration,
    detail=response.error or "",
)
```

The prompt is NOT recorded in evidence (it may contain sensitive context).
The stdout is capped at 5000 chars in `ProviderResponse.raw` for evidence.

## 20. Error Handling

| Error | ProviderResponse | Recovery |
|-------|-----------------|----------|
| Executable not found | UNAVAILABLE | Agent marked BLOCKED |
| Process timeout | TIMEOUT | Process killed, agent marked FAILED |
| Non-zero exit | ERROR | stderr included in error |
| Null bytes in output | ERROR | Output rejected |
| Binary content | ERROR | Output rejected |
| Output too large | ERROR | Output truncated then validated |
| OSError | ERROR | OS-level failure |
| Config invalid | N/A | Config validation rejects at load time |

## 21. Failure-Closed Behavior

- If executable not found → UNAVAILABLE (not silent fallback)
- If output invalid → ERROR (not silent acceptance)
- If timeout → TIMEOUT (process killed)
- If config invalid → INVALID (startup fails)
- If policy blocks → DENY (workflow blocked)

The provider NEVER:
- Silently falls back to another provider
- Accepts invalid output as valid
- Continues after process failure
- Bypasses security scanning

## 22. Cancellation Behavior

If a CLI process needs to be cancelled:

```python
# subprocess.run with timeout handles this automatically
# On TimeoutExpired:
process.kill()
process.wait()
```

No explicit cancellation API is needed because:
- subprocess.run timeout handles hanging processes
- The scheduler can set shorter timeouts for cancellation
- The process is killed, not left running

## 23. Testing Strategy

### Unit tests (no actual CLI required)

- CLIProvider with mock subprocess
- Argument construction
- stdin prompt delivery
- Timeout handling
- Exit code mapping
- Output validation
- Security scanning integration
- Evidence recording
- Error handling for missing executable
- Error handling for invalid output
- Configuration parsing
- Provider registry integration

### Integration tests (with real CLI if available)

- FreeBuff health check
- FreeBuff complete with simple prompt
- FreeBuff timeout behavior
- FreeBuff unavailable behavior

### Security tests

- shell=False verified via AST
- No argument injection via prompt
- No shell concatenation
- Output scanning catches dangerous patterns
- Prompt not logged in evidence
- Secrets redacted in evidence

## 24. Negative/Security Tests

| Test | Expected Result |
|------|:---------------:|
| shell=True in CLIProvider | Must not exist (AST verified) |
| Executable with shell metacharacters | Treated as literal filename |
| Prompt containing `; rm -rf /` | Passed via stdin, not executed |
| Prompt containing `--flag` injection | Not interpreted as CLI flags |
| Output containing `git commit --no-verify` | Security scan flags it |
| Output exceeding max_output | Truncated, not crashed |
| Process hanging beyond timeout | Killed, TIMEOUT returned |
| Non-existent executable | UNAVAILABLE returned |
| Empty output | ERROR returned (no text) |
| Binary output | Rejected by validation |
| Null bytes in output | Rejected by validation |
| Config with malicious args | Args validated at config load |

## 25. Compatibility with OllamaProvider

- Both implement AIProvider protocol
- Both return ProviderResponse
- Both are registered in provider registry
- Both are subject to same policy rules
- Both record evidence
- Neither can bypass the orchestrator

Differences:
- OllamaProvider uses HTTP (urllib), CLIProvider uses subprocess
- OllamaProvider has model selection, CLIProvider uses CLI args
- OllamaProvider health = HTTP ping, CLIProvider health = shutil.which

## 26. Compatibility with NoneProvider

- NoneProvider always returns UNAVAILABLE
- CLIProvider returns AVAILABLE if executable exists
- Agents using NoneProvider are BLOCKED (no AI output)
- Agents using CLIProvider can function if CLI is installed
- Both are interchangeable through the provider registry

## 27. Future CLI Providers

Any CLI-based AI tool can be integrated by extending CLIProvider:

```python
class MyCustomProvider(CLIProvider):
    def __init__(self):
        super().__init__(
            executable="my-ai-cli",
            args=["--format", "text"],
        )
```

No changes to the scheduler, engine, or policy are needed.
The provider registry handles discovery.

## 28. Zero-Dependency Verification

CLIProvider uses only:
- `subprocess` (stdlib)
- `shutil` (stdlib)
- `os` (stdlib)
- `time` (stdlib)
- `json` (stdlib)

No external packages required.

## 29. Existing Architecture Conflict Check

| Component | Conflict? | Notes |
|-----------|:---------:|-------|
| AIProvider protocol | NO | CLIProvider implements it |
| ProviderResponse | NO | Reuses existing dataclass |
| ProviderStatus | NO | Reuses existing enum |
| Scheduler | NO | Provider passed as-is |
| Agent model | NO | Provider is agent's backend |
| Policy engine | NO | Provider below policy |
| Evidence | NO | Records via existing EvidenceLog |
| Config | NO | Extends existing config schema |
| Security scanner | NO | Applied to CLI output |
| Validation | NO | Applied to CLI output |
| Persistence | NO | Provider state not persisted |
| Modes | NO | Provider subject to mode rules |

**No conflicts found.**

## 30. Implementation Plan

### Step 1: CLIProvider base class
- Add `CLIProvider` to `providers.py`
- Process execution via subprocess.run
- Timeout, stdout/stderr, exit code handling
- Output validation
- Unit tests

### Step 2: FreebuffProvider
- Add `FreebuffProvider` extending CLIProvider
- FreeBuff-specific defaults
- Health check via shutil.which
- Unit tests

### Step 3: Configuration
- Add provider config keys to config schema
- Add validation in validate.py
- Update `get_provider()` registry
- Tests

### Step 4: Integration
- Wire into scheduler (no changes needed — provider is passed as-is)
- Wire into CLI (provider selection via config)
- Evidence recording
- Integration tests

### Step 5: Security audit
- AST scan for shell=True
- Dependency audit
- Security test suite
- Final verification

## 31. Exit Criteria

- [ ] CLIProvider implemented with subprocess execution
- [ ] shell=False enforced (AST verified)
- [ ] FreebuffProvider implemented with FreeBuff defaults
- [ ] Health check via shutil.which
- [ ] Timeout enforcement working
- [ ] Output validation working
- [ ] Security scanning applied to CLI output
- [ ] Evidence recorded for all CLI interactions
- [ ] Prompt NOT logged in evidence
- [ ] Configuration validated
- [ ] All 4 modes work with CLI provider
- [ ] SECURITY/ENTERPRISE allow local CLI providers
- [ ] Existing OllamaProvider unchanged
- [ ] Existing NoneProvider unchanged
- [ ] All existing tests pass
- [ ] New tests pass
- [ ] Zero external dependencies
- [ ] Zero shell=True
- [ ] 7 tool repositories untouched

---

## ANSWER: Can the orchestrator use FreeBuff CLI without an API key?

**YES.**

FreeBuff is a local CLI tool that reads from stdin and writes to stdout.
The CLIProvider invokes it via:

```python
subprocess.run(
    ["freebuff", "--no-banner", "--output", "text"],
    input=prompt,          # prompt via stdin
    capture_output=True,
    text=True,
    timeout=60,
    shell=False,
)
```

No API key is passed.  No environment variable with a secret is set.
No network call is made.  The interaction is purely local process I/O:

```
Orchestrator → stdin → FreeBuff CLI → stdout → Orchestrator
```

FreeBuff reads the prompt from stdin, processes it locally (using whatever
model it has configured), and writes the response to stdout.  The
orchestrator captures stdout as the AI response.

This is identical to how a human would use FreeBuff from a terminal:
`echo "prompt" | freebuff` — except the orchestrator automates it.
