# Phase 8A Implementation Report — Persistence & Evidence

## 1. Objective

Implement crash-safe persistence for run state and evidence so that
orchestration data survives process termination.  This addresses the
CRITICAL gaps identified in PHASE_8_HARDENING_DESIGN.md (C1, C2).

## 2. Files Created

| File | Lines | Purpose |
|------|------:|---------|
| `orchestrator/persist.py` | 380 | Persistence layer: atomic writes, JSONL evidence, run index |
| `tests/test_persist.py` | 370 | 50 comprehensive persistence tests |

## 3. Files Modified

| File | Change |
|------|--------|
| `orchestrator/evidence.py` | Added `persist_dir` parameter to `EvidenceLog`, auto-save on `record()` |
| `orchestrator/engine.py` | Added `persist_dir` parameter to `WorkflowEngine`, persist state on every transition and completion |

## 4. Persistence Architecture Implemented

### Storage layout
```
.orchestrator/
    runs/
        index.json              # run history index (all runs)
        {run_id}/
            state.json          # full run state (overwritten on each transition)
            evidence.jsonl      # append-only evidence entries (one JSON line per entry)
```

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Evidence format | JSONL (one JSON object per line) | Append-friendly, crash-safe, streamable |
| State format | JSON (complete overwrite) | Simpler than delta, state is small |
| Atomic writes | `tempfile.mkstemp()` + `os.replace()` | Cross-platform atomic rename |
| Evidence flush | Write + `fsync()` per entry | Ensures data hits disk before continuing |
| Run ID validation | Regex pattern matching | Prevents path traversal via crafted run IDs |
| Persistence errors | Logged as warnings, do not crash | Run must complete even if persistence fails |

### Evidence auto-save

When `persist_dir` is provided to `EvidenceLog`, each `record()` call
immediately appends the entry to the JSONL file.  This means:
- Evidence written before a crash survives
- At most one entry is lost if crash occurs mid-write
- In-memory evidence is always available regardless of persistence

### State persistence

The engine persists state at every significant point:
- Run created (initial state)
- Pre-flight policy BLOCKED
- Phase transitions (via evidence records that trigger persistence)
- Branch BLOCKED/FAIL
- Gate failure BLOCKED
- Required step failure
- Post-flight policy BLOCKED
- Workflow completion

### Run index

The index tracks all runs with summary information:
- run_id, workflow, mode, status
- started_at, ended_at
- tool_call_count, evidence_count
- phase

The index enables `orchestrator history` (future Phase 8C) and
`find_interrupted_runs()` for crash recovery.

## 5. Atomic-Write Mechanism

```python
def _atomic_write(path, content):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX and Windows
```

If the process crashes during write:
- The temp file remains (can be cleaned up)
- The original file is intact
- No corrupted state file can masquerade as valid

## 6. Failure Behavior

| Scenario | Behavior |
|----------|----------|
| Persistence directory cannot be created | Warning logged, run continues in-memory |
| State file write fails | Warning logged, run continues |
| Evidence write fails | Error recorded in `EvidenceLog.persist_error`, run continues |
| Corrupt state on disk | `load_state()` returns None |
| Corrupt evidence line | Marked as `CORRUPTED_LINE` in loaded entries |
| Invalid run_id | `ValueError` raised, no file operations |
| Disk full | `OSError` caught, warning logged |

## 7. Security Considerations

- **Path traversal**: Run IDs validated with regex `^RUN-\d{8}-\d{6}-[a-f0-9]{6}$`
- **No secrets persisted**: Uses existing `redact()` on tool errors; no API keys stored
- **No arbitrary code execution**: JSON parsing only, no `eval()`/`exec()`
- **No shell=True**: AST-verified (only `shell=False` in adapter.py)
- **Atomic writes**: Prevents corrupted files from being read as valid state
- **Run isolation**: Each run has its own directory, no cross-run access

## 8. Tests Added

| Category | Count | Tests |
|----------|:-----:|-------|
| Run ID validation | 5 | valid, empty, path traversal, too long, bad format |
| Atomic writes | 6 | create, overwrite, no temp left, parent dirs, append, empty |
| State persistence | 8 | save/load, roundtrip, nonexistent, corrupt, invalid ID, multiple runs, fields |
| Evidence persistence | 9 | append/load, multiple, nonexistent, invalid ID, count, corrupt line, isolation |
| Run index | 6 | update/list, update existing, multiple, limit, get, nonexistent |
| Full roundtrip | 6 | roundtrip, validate, corrupt, missing, invalid, interrupted |
| Evidence auto-save | 5 | auto-save, multiple, no persist default, error recorded, in-memory |
| Security | 3 | path traversal, special chars, redaction |
| Directory structure | 2 | expected files, separate dirs |
| **Total** | **50** | |

## 9. Complete Test-Suite Results

```
Ran 446 tests in 31.631s — OK

Phase 1-7 tests:  396 (all pass)
Phase 8A tests:    50 (all pass)
Total:            446
```

## 10. Dependency Audit

```
persist.py imports: __future__, json, hashlib, os, re, tempfile,
                    dataclasses, datetime, pathlib, typing (all stdlib)
                    + orchestrator.evidence.redact (internal)
                    + orchestrator.state (internal)
```

**Zero external dependencies.**

## 11. AST/Security Audit

| Check | Result |
|-------|:------:|
| shell=True | None found (only `shell=False` in adapter.py:94) |
| Non-stdlib imports | None (all stdlib or `orchestrator.*`) |
| `eval()`/`exec()` | None |
| `os.system()` | None |
| Path traversal prevention | Run ID regex validated |
| Secret redaction | `redact()` applied to persisted errors |
| Atomic writes | `os.replace()` used for all state writes |

## 12. Seven-Repository Integrity Check

| Repository | Modified by Phase 8A? |
|-----------|:---------------------:|
| agent-error-log | No |
| agent-decision-log | No (pre-existing change) |
| agent-log-ai | No (pre-existing change) |
| agent-memory | No |
| agent-blame | No |
| agent-diff-gate | No |
| agent-sandbox | No |

## 13. Backwards Compatibility Results

| Feature | Status |
|---------|:------:|
| `orchestrator --help` | PASS |
| `orchestrator --version` | PASS |
| `orchestrator status` | PASS |
| `orchestrator status --json` | PASS |
| `orchestrator doctor` | PASS |
| `orchestrator run --mode solo` | PASS |
| `orchestrator run --mode security` | PASS |
| `orchestrator modes` | PASS |
| `orchestrator policies solo` | PASS |
| All 396 Phase 1-7 tests | PASS |

**No breaking changes.**  Persistence is entirely additive — the engine
works identically with or without `persist_dir`.

## 14. Deviations from PHASE_8_HARDENING_DESIGN.md

None.  The implementation follows the design exactly:
- JSONL evidence format ✓
- Atomic writes via temp+replace ✓
- Run index with summary entries ✓
- State persisted on transitions ✓
- Run ID validation ✓
- Failure-warn-don't-crash behavior ✓

## 15. Problems Encountered

- **Windows `fsync()`**: On Windows, `os.fsync()` works but is slower.
  Accepted trade-off for crash safety.
- **Evidence hash chain**: Not implemented in Phase 8A (deferred to
  Phase 8B which adds the full security scanner).  The design mentions
  optional integrity hashing — this is a Phase 8B concern.

## 16. Known Limitations

- Evidence hash chain not yet implemented (Phase 8B)
- No run resume capability yet (Phase 8C)
- No `orchestrator history` CLI command yet (Phase 8C)
- No concurrency lock yet (Phase 8C)
- Persistence directory is not configurable (uses `.orchestrator/runs/` relative to base_dir)

## 17. Evidence of Actual Execution

- 446 tests executed and passed (31.6s)
- CLI `run --mode solo` executed, produced report
- CLI `doctor` executed, reported HEALTHY
- AST audit executed, verified 0 shell=True
- Dependency audit executed, verified 0 external deps
- 7-repository check executed, all untouched

## 18. Recommendation for Phase 8B

Phase 8B (Validation & Security) should implement:
- `validate.py` — path boundary validation, config value validation
- `security_scan.py` — suspicious pattern detection in tool/agent output
- Config value type/range validation
- Stricter output validation in adapters

Phase 8B does NOT depend on Phase 8A changes — they are independent.
However, Phase 8B's security scanner could benefit from the persisted
evidence for offline analysis.
