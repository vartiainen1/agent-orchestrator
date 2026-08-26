# Phase 11 Implementation Report — FreeBuff / CLI AI Integration

## 1. Objective

Implement generic CLI-based AI provider support with FreeBuff as the first
concrete implementation, following PHASE_11_FREEBUFF_CLI_DESIGN.md exactly.

## 2. Files Created

| File | Lines | Purpose |
|------|------:|---------|
| `tests/test_cli_provider.py` | 310 | 45 comprehensive CLI provider tests |

## 3. Files Modified

| File | Change |
|------|--------|
| `orchestrator/providers.py` | Added CLIProvider (150 lines) + FreebuffProvider (25 lines) + updated registry |
| `orchestrator/validate.py` | Added 5 config schema entries + string type validation |

## 4. Architecture Changes

```
AIProvider (Protocol)
    |
    +-- NoneProvider          (no AI)
    +-- OllamaProvider        (HTTP API)
    +-- CLIProvider           (subprocess, stdin/stdout)
           |
           +-- FreebuffProvider   (FreeBuff-specific defaults)
           +-- future CLI providers
```

### Provider hierarchy

| Provider | Type | API Key | Network | stdin/stdout |
|----------|------|:-------:|:-------:|:------------:|
| NoneProvider | local | No | No | N/A |
| OllamaProvider | local | No | HTTP | No |
| CLIProvider | local | No | No | Yes |
| FreebuffProvider | local | No | No | Yes |

## 5. CLIProvider Implementation

### Key properties
- `shell=False` always enforced (subprocess.run with argument list)
- Prompt delivered via **stdin** (not command-line arguments)
- Output validated (null bytes, binary content, size limits)
- Timeout enforced via subprocess.run
- Exit code mapped to ProviderStatus
- Raw output capped at 5000 chars for evidence
- No API key required

### Process execution model
```python
subprocess.run(
    [executable, *args],     # argument list, NOT shell string
    input=prompt,             # prompt via stdin
    capture_output=True,
    text=True,
    timeout=timeout,
    shell=False,              # NEVER True
    cwd=work_dir,
)
```

## 6. FreebuffProvider Implementation

- Extends CLIProvider
- Default args: `["--no-banner", "--output", "text"]`
- Custom args merged with defaults
- Health check via `shutil.which("freebuff")`
- No API key required

## 7. Configuration Changes

New config keys in `.orchestrator/config`:

| Key | Type | Default | Constraints |
|-----|------|---------|-------------|
| provider | enum | ollama | ollama, none, freebuff, cli |
| provider_executable | string | freebuff | min_length=1 |
| provider_args | string | "" | (space-separated) |
| provider_work_dir | string | "" | (directory path) |
| provider_timeout | int | 60 | 1-3600 |

## 8. Policy Integration

- CLI providers are LOCAL (no cloud access)
- SECURITY/ENTERPRISE modes allow local CLI providers
- SECURITY/ENTERPRISE modes block cloud providers via `llm_cloud_allowed`
- FreeBuff is treated as local, same as Ollama

## 9. Validation/Security Integration

- Output validated (null bytes, binary detection)
- Security scanner can be applied to CLI output
- Existing `validate.py` config schema extended
- Evidence recording integrated via ProviderResponse

## 10. Evidence Integration

Provider execution records:
- provider name
- executable (not args with secrets)
- exit code
- duration
- status
- error (if any)
- raw output (capped at 5000 chars)

Prompt is NOT recorded in evidence (may contain sensitive context).

## 11. Timeout/Error Handling

| Scenario | Status | Error Message |
|----------|:------:|---------------|
| Executable not found | UNAVAILABLE | "executable not found: ..." |
| Timeout | TIMEOUT | "CLI timeout after Xs" |
| Non-zero exit | ERROR | "CLI exited with code N: ..." |
| Null bytes in output | ERROR | "output validation failed: null bytes" |
| Binary content | ERROR | "output validation failed: suspected binary" |
| OSError | ERROR | "CLI OS error: ..." |

## 12. Tests

| Category | Count | Tests |
|----------|:-----:|-------|
| CLIProvider init | 4 | basic, args, custom name, timeout |
| CLIProvider health | 3 | available, unavailable, property |
| CLIProvider complete | 9 | success, stdin, stderr, exit code, not found, timeout, size limit, args, work_dir |
| Output validation | 1 | null bytes |
| Security | 2 | no shell=True, stdin delivery |
| FreebuffProvider | 4 | init, executable, args, is_cli |
| FreebuffProvider health | 1 | unavailable |
| Provider registry | 6 | ollama, none, freebuff, cli, cli-no-exe, unknown |
| Config validation | 8 | provider enum, invalid, executable, empty, args, timeout, invalid, range |
| Backward compatibility | 4 | ollama unchanged, none unchanged, all have complete, response compatible |
| Integration | 2 | full workflow, freebuff-like workflow |
| **Total** | **45** | |

## 13. Full Test Results

```
Ran 593 tests in 34.931s — OK (skipped=2)

Phase 1-8D tests:  548 (all pass)
Phase 11 tests:     45 (all pass, 2 skipped)
Total:             593

Skipped: 2 (Windows timeout tests — platform limitation)
```

## 14. Security Audit Results

| Check | Result |
|-------|:------:|
| shell=True | **0 found** (AST verified) |
| eval/exec | **0 found** |
| os.system | **0 found** |
| shell=False enforced | YES (subprocess.run with argument list) |
| Prompt via stdin | YES (input=prompt, not arguments) |
| Output validation | YES (null bytes, binary, size) |
| Timeout enforced | YES (subprocess.run timeout) |
| No secret leakage | YES (prompt not logged) |

## 15. Dependency Audit

```
providers.py new imports: os, shutil, subprocess, time (all stdlib)
validate.py: no new imports
Zero external dependencies confirmed.
```

## 16. Seven-Repository Integrity

| Repository | Modified by Phase 11? |
|-----------|:---------------------:|
| agent-error-log | No |
| agent-decision-log | No |
| agent-log-ai | No |
| agent-memory | No |
| agent-blame | No |
| agent-diff-gate | No |
| agent-sandbox | No |

## 17. CLI Verification

All existing CLI commands still work:
- `orchestrator --help` → lists all commands including new providers
- `orchestrator run --mode solo` → works with any provider
- `orchestrator doctor` → reports provider status
- `orchestrator modes` → all 4 modes work
- `orchestrator policies` → policy enforcement unchanged

## 18. Known Limitations

1. **FreeBuff not tested with real installation**: Tests use fake CLI scripts.
   Real FreeBuff integration requires FreeBuff to be installed.
2. **No structured output protocol**: CLI output treated as untrusted text.
   Future versions may support JSON output from FreeBuff.
3. **No cancellation of running CLI**: Timeout handles hanging processes,
   but no mid-execution cancellation API.
4. **Args split is simple**: `str.split()` not `shlex.split()`.  Quotes and
   escapes in config args are not interpreted.  This is intentional for security.

## 19. Exact Final State

- 593 tests passing (2 skipped)
- 23 source files in orchestrator/
- 18 test files in tests/
- Zero external dependencies
- Zero shell=True
- 7 tool repositories untouched
- All existing functionality preserved
- New CLIProvider + FreebuffProvider working

## 20. Recommended Next Phase

**Phase 14 — Full Ecosystem Integration Test**: Create a dedicated integration
project demonstrating all 7 tools working together through the orchestrator.
