# Phase 8C Implementation Report — Recovery & CLI

## 1. Objective

Implement the Recovery & CLI portion of Phase 8 hardening, providing
interrupted-run detection, workspace locking, run inspection, cancellation,
and provider health checking.

## 2. Files Created

| File | Lines | Purpose |
|------|------:|---------|
| `orchestrator/recovery.py` | 290 | Lock management, interrupted-run detection, recovery |
| `tests/test_recovery.py` | 310 | 38 comprehensive recovery and CLI tests |

## 3. Files Modified

| File | Change |
|------|--------|
| `orchestrator/cli.py` | Added 6 new commands: history, show, evidence, cancel, recover, help |

## 4. What Was Implemented

### 4.1 Module: `recovery.py`

| Component | Purpose |
|-----------|---------|
| `LockInfo` | Dataclass for workspace lock file contents |
| `_pid_running(pid)` | Check if a process is running via `os.kill(pid, 0)` |
| `acquire_lock(workspace, run_id)` | Acquire workspace lock with stale detection |
| `release_lock(workspace)` | Release lock (only if owned by current PID) |
| `check_lock(workspace)` | Check current lock status |
| `is_locked(workspace)` | Check if workspace is locked by running process |
| `cleanup_stale_lock(workspace)` | Remove lock if PID not running |
| `find_interrupted_runs(workspace)` | Find runs in non-terminal state |
| `recover_run(workspace, run_id, action)` | Recover interrupted run (cancel/discard) |
| `check_provider_health(workspace)` | Check Ollama provider availability |
| `cleanup_workspace(workspace)` | Combined cleanup operations |

### 4.2 CLI Commands Added

| Command | Purpose | Exit Codes |
|---------|---------|:----------:|
| `orchestrator history [-n N] [--json]` | List recent runs | OK, BLOCKED |
| `orchestrator show RUN_ID [--json]` | Show run details | OK, INVALID, BLOCKED |
| `orchestrator evidence RUN_ID [--json] [-n N]` | Show evidence entries | OK, BLOCKED |
| `orchestrator cancel RUN_ID` | Cancel interrupted run | OK, ERROR, BLOCKED |
| `orchestrator recover [--list] [--cancel ID] [--discard ID]` | Recovery operations | OK, ERROR, BLOCKED |

### 4.3 Recovery Behavior

| Scenario | Behavior |
|----------|----------|
| Cancel running run | Phase -> CANCELLED, status -> CANCELLED, persisted |
| Cancel already terminal | Returns "already in terminal state" |
| Discard run | Removes run directory, updates index |
| Invalid run_id | Returns error, no file operations |
| Nonexistent run | Returns error |
| Corrupt persisted state | Returns validation failure |
| Unknown action | Returns error |

### 4.4 Lock Behavior

| Scenario | Behavior |
|----------|----------|
| No lock exists | Acquire successfully |
| Lock by running PID | Refuse with "locked by PID" |
| Lock by dead PID (stale) | Auto-cleanup, acquire |
| Corrupt lock file | Treat as stale, cleanup |
| Release own lock | Remove lock file |
| Release other's lock | Skip (only release own) |

### 4.5 Provider Health

- Checks Ollama availability via `GET /api/tags`
- Returns `AVAILABLE` or `UNAVAILABLE`
- No API key required (local-first)
- Uses urllib (stdlib only)
- Integrated into `cleanup_workspace()` summary

## 5. Tests Added

| Category | Count | Tests |
|----------|:-----:|-------|
| Lock management | 9 | acquire, release, check, is_locked, stale cleanup, roundtrip, invalid JSON, PID 0, special PID |
| Interrupted run detection | 4 | no runs, running state, completed state, cancelled state |
| Recovery | 6 | cancel, already terminal, discard, invalid ID, nonexistent, unknown action |
| CLI history | 2 | empty, JSON output |
| CLI show | 2 | invalid ID, nonexistent |
| CLI evidence | 2 | invalid ID, JSON output |
| CLI cancel | 2 | invalid ID, nonexistent |
| CLI recover | 3 | no args, --list, --help |
| Security | 3 | path traversal, PID 0, no policy bypass |
| Exit codes | 5 | all return int |
| **Total** | **38** | |

## 6. Total Tests

```
Ran 548 tests in 31.663s — OK

Phase 1-7 tests:   396 (all pass)
Phase 8A tests:     50 (all pass)
Phase 8B tests:     64 (all pass)
Phase 8C tests:     38 (all pass)
Total:             548
```

## 7. CLI Commands Tested

| Command | Exit | Output |
|---------|:----:|--------|
| `orchestrator --help` | 0 | Lists all 10 commands |
| `orchestrator history` | 0 | "no runs found" |
| `orchestrator history --json` | 0 | JSON output |
| `orchestrator show bad-id` | 3 | Error: invalid run_id |
| `orchestrator evidence bad-id` | 0 | "no evidence found" |
| `orchestrator cancel bad-id` | 1 | Error: invalid run_id |
| `orchestrator recover` | 0 | Help text |
| `orchestrator recover --list` | 0 | "no interrupted runs" |
| `orchestrator recover --help` | 0 | Usage info |

## 8. Recovery Behavior

- **Cancel**: Transitions run to CANCELLED phase, persists state, updates index
- **Discard**: Removes run directory, removes from index
- **Resume**: NOT implemented (by design — resuming requires re-initializing adapters/tools/policy which is complex and risky)
- **Invalid ID**: Returns error without file operations
- **Corrupt state**: Returns validation failure

## 9. Cancellation Behavior

- Explicit: requires run_id argument
- Recorded: state persisted as CANCELLED
- Preserves evidence: evidence file untouched
- Safe for terminal runs: returns "already terminal"
- Never silently deletes: only `--discard` removes data

## 10. History/Show Behavior

- **history**: Reads from run index, shows table with run_id, workflow, mode, status, started_at
- **show**: Loads full state from disk, shows all fields
- **evidence**: Loads JSONL entries, shows with line numbers

## 11. Provider Health/Fallback

- Provider health check: `OllamaProvider.health()` via `GET /api/tags`
- Returns `AVAILABLE` or `UNAVAILABLE`
- No API key required
- No fallback chain (single provider)
- SECURITY/ENTERPRISE restrictions remain enforced by policy engine

## 12. Security Checks

| Check | Result |
|-------|:------:|
| shell=True | None found |
| Non-stdlib imports | None (all stdlib or `orchestrator.*`) |
| Path traversal prevention | Run ID regex + boundary checks |
| Lock PID validation | `os.kill(pid, 0)` — no signal sent |
| Recovery cannot resume | Only cancel/discard supported |
| Persisted data treated as untrusted | Validation before recovery |
| No policy bypass | Recovery only cancels/discards |
| No secret exposure | Redaction applied in persistence |
| No eval/exec | None used |

## 13. Persistence/Recovery Integrity

- Run ID validated before any file operation
- State validated before recovery
- Lock prevents concurrent modifications
- Stale locks auto-detected and cleaned
- Evidence preserved during cancellation
- Discard removes all data cleanly

## 14. Dependency Audit

All imports are Python standard library:
- `os`, `signal`, `json`, `time`, `pathlib`, `dataclasses`, `datetime`, `typing`
- `shutil` (for discard cleanup)
- Internal `orchestrator.*` imports only

**Zero external dependencies.**

## 15. shell=True Audit

```
orchestrator/adapter.py:94: shell=FALSE
```

**Zero shell=True.**

## 16. Seven-Repository Integrity Check

| Repository | Modified by Phase 8C? |
|-----------|:---------------------:|
| agent-error-log | No |
| agent-decision-log | No |
| agent-log-ai | No |
| agent-memory | No |
| agent-blame | No |
| agent-diff-gate | No |
| agent-sandbox | No |

## 17. Deviations from PHASE_8_HARDENING_DESIGN.md

- **Resume not implemented**: The design mentions `orchestrator resume` as a
  future capability.  Phase 8C implements cancel/discard instead because
  resuming requires re-initializing adapters, tools, and policy state which
  is complex and risky.  This is documented as a known limitation.
- **Config checksum**: The design mentions optional config checksum.  This
  is deferred to a future phase as it provides marginal security benefit
  compared to the validation already implemented in Phase 8B.

## 18. Known Limitations

- Resume not supported (cancel/discard only)
- No config checksum verification
- Lock is advisory (not OS-enforced)
- Provider health check only (no fallback chain)
- No run filtering in history (only limit)

## 19. Recommended Next Step

**Phase 8D — Integration & Final Audit**: Full end-to-end integration test,
complete security audit, documentation updates, and final implementation report.
