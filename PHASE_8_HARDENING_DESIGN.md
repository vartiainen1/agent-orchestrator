# Phase 8 — Orchestrator Hardening / Production Readiness Design

## 1. Objective

Determine what the orchestrator needs before it should be considered a reliable
production-grade orchestration system.  Identify architectural gaps, security
weaknesses, reliability problems, state-management problems, and missing tests
in the current Phase 1-7 implementation, then design targeted fixes that
preserve the project's philosophy and architecture.

**This is a design document only.  No code is written until explicitly approved.**

---

## 2. Current Architecture Assessment

### 2.1 What exists (Phase 1-7)

| Component | Module | Lines | Status |
|-----------|--------|------:|--------|
| CLI | cli.py | 461 | Functional |
| Discovery | discovery.py | 387 | Functional |
| Adapters (7) | adapter.py | 500 | Functional |
| Workflow Engine | engine.py | 345 | Functional |
| Policy Engine | policy.py | 410 | Functional |
| Modes | modes.py | 196 | Functional |
| Agents | agents.py | 397 | Functional |
| Providers | providers.py | 250 | Functional |
| Scheduler | scheduler.py | 384 | Functional |
| State | state.py | 160 | Functional |
| Evidence | evidence.py | 116 | Functional |
| Report | report.py | 167 | Functional |
| Config | config.py | 145 | Functional |
| Workspace | workspace.py | 155 | Functional |
| Logging | olog.py | 73 | Functional |
| Exit codes | exit_codes.py | 17 | Functional |
| **Total** | | **4,663** | |

**Tests**: 396 passing across 13 test files (5,127 lines).

### 2.2 What works well

- Zero external dependencies maintained
- shell=False enforced via AST audit
- 7 tool repositories untouched
- Fail-closed behavior verified (SECURITY mode blocks on Windows)
- Policy engine correctly prevents mandatory safety rule weakening
- Evidence is append-only within a run
- Agent permissions are immutable (frozen dataclasses)
- Secret redaction is present in evidence and reports
- All four modes operational through CLI

### 2.3 Identified architectural gaps

The following gaps were found through systematic code inspection, NOT through
assumption.  Each gap is categorized by severity.

#### CRITICAL GAPS

**C1. No run persistence.**
RunState lives entirely in memory.  If the process is interrupted (Ctrl+C, crash,
timeout), ALL evidence and state for that run is lost.  There is no recovery
mechanism.  For production use, a run that produced evidence must survive process
termination.

**C2. No evidence auto-save.**
Evidence is only saved to disk if the user explicitly passes `--report PATH`.
Without this flag, ALL evidence is discarded after the run.  This means the
default behavior loses the audit trail.

**C3. No tool output validation.**
The adapter layer captures stdout/stderr/exit_code but does not validate the
content of tool output.  A tool could return:
- empty output and exit code 0
- malformed JSON where JSON is expected
- misleading text (e.g., "PASS" in stdout while exit code is 1)
- output containing injection attempts
The engine trusts tool output as-is without schema validation.

**C4. No resource limits.**
Tool execution has no CPU, memory, or disk limits.  A runaway tool can consume
all system resources.  The `max_tool_timeout` policy rule exists but is NOT
enforced in the adapter layer (subprocess.run has a timeout parameter but it
is hardcoded to 30s in the base adapter, ignoring the policy value).

**C5. No run cancellation.**
There is no mechanism to cancel a running workflow.  Once started, a run
continues until completion, failure, or the process is killed.  In production,
a user must be able to cancel a misbehaving run.

#### HIGH-SEVERITY GAPS

**H1. State transition fragility.**
The engine catches `InvalidTransitionError` with bare `pass` in multiple places
(e.g., the pre-flight block sequence tries three transitions in sequence,
silently catching failures).  This hides state management bugs.  A failed
transition should be logged, not silently swallowed.

**H2. Evidence log is not persisted between runs.**
There is no run history.  Each run creates a fresh EvidenceLog.  There is no
index of past runs, no way to query "what happened last time", and no way to
compare runs.

**H3. Agent task retry not implemented.**
The scheduler has `assign_task` but no retry logic.  If an agent fails, the
task is simply marked failed with no recovery option.

**H4. No provider health checking.**
The Ollama provider calls the API on every invocation without first checking
whether the server is available.  A more robust approach would check health
before the workflow starts (during pre-flight).

**H5. Secret redaction is heuristic-only.**
The regex patterns catch common formats (API keys, Bearer tokens, OpenAI-style
keys) but miss:
- AWS access keys (AKIA...)
- GitHub tokens (ghp_, gho_)
- Generic base64-encoded secrets
- Custom secret formats
This is documented as "best-effort" but should be acknowledged as a limitation.

**H6. No configuration schema validation.**
Project configuration (`.orchestrator/config`) is parsed with a simple
key=value regex.  While unknown keys are rejected, there is no validation of
values (e.g., `max_tool_timeout = not_a_number` would be accepted).

#### MEDIUM-SEVERITY GAPS

**M1. No cancellation token.**
The engine loop has no mechanism to check for cancellation between steps.
Adding a cancellation check between steps would allow graceful shutdown.

**M2. CLI does not expose run history.**
There is no `orchestrator history` or `orchestrator runs` command.  Users
cannot inspect past runs without manually finding report files.

**M3. No run resumability.**
BLOCKED runs cannot be resumed after the blocking issue is fixed.  The
`Phase.BLOCKED` state allows transition to `Phase.EXECUTING`, but there is
no CLI command or engine method to resume a blocked run.

**M4. Provider fallback not implemented.**
The scheduler has a single provider per agent.  There is no fallback chain
if the primary provider is unavailable.

**M5. No cross-run learning.**
Lessons learned from previous runs are not automatically fed back into
future runs.  The memory system stores knowledge but the orchestrator does
not actively recall it during pre-flight.

**M6. No workflow versioning.**
Workflows are defined as Python objects.  There is no version tracking, no
migration strategy, and no compatibility checking between workflow versions.

---

## 3. Threat Model

### 3.1 External threats

| Threat | Current mitigation | Gap |
|--------|-------------------|-----|
| Malicious project code | Sandbox execution | C4: No resource limits |
| Prompt injection in project files | Project content not treated as authority | H5: No output content validation |
| Malformed tool output | Exit code checked | C3: No output schema validation |
| Malicious tool output | Tool treated as untrusted | No output sanitization before use |
| Agent prompt injection | Agent output treated as untrusted | No structured output validation |
| Path traversal | Pathlib used | No explicit path boundary enforcement |
| Command injection | shell=False enforced | No argument validation |
| Supply-chain attack | Zero dependencies | N/A (mitigated by design) |

### 3.2 Internal threats

| Threat | Current mitigation | Gap |
|--------|-------------------|-----|
| Agent self-escalation | Frozen permissions | No runtime permission verification |
| Policy bypass | Mandatory rules in code | No audit of policy rule enforcement |
| Evidence tampering | Append-only in memory | C2: Evidence not persisted by default |
| Run state corruption | Phase transitions validated | H1: Some transitions silently caught |
| Resource exhaustion | Timeouts on subprocess | C4: No CPU/memory limits |
| Secret leakage | Regex redaction | H5: Heuristic-only |

### 3.3 Configuration threats

| Threat | Current mitigation | Gap |
|--------|-------------------|-----|
| Malicious config values | Unknown keys rejected | M6: No value validation |
| Config weakening mandatory rules | Mandatory rules enforced | Verified working |
| Invalid mode | Mode validation | Verified working |
| Missing config | Safe defaults | Verified working |

---

## 4. Reliability Model

### 4.1 Current failure modes

| Failure | Behavior | Correctness |
|---------|----------|:-----------:|
| Tool not found | ERROR result | PASS |
| Tool unavailable | UNSUPPORTED result | PASS |
| Tool timeout | TimeoutExpired caught | PASS |
| Tool exception | ERROR result with message | PASS |
| Invalid phase transition | Exception raised | PASS (but see H1) |
| Policy DENY | BLOCKED workflow | PASS |
| Sandbox unsupported | UNSUPPORTED + BLOCKED | PASS |
| Agent failure | AgentState.FAILED | PASS |
| Provider unavailable | AgentState.BLOCKED | PASS |

### 4.2 Unhandled failure modes

| Failure | Current behavior | Risk |
|---------|-----------------|------|
| Process crash mid-run | ALL evidence lost | **Critical** |
| Ctrl+C mid-run | ALL evidence lost | **Critical** |
| OOM kill | ALL evidence lost | **Critical** |
| Disk full during evidence write | Exception, partial evidence lost | High |
| Concurrent runs on same workspace | Race condition, undefined | High |
| Tool returns garbage output | Engine trusts it | High |
| Infinite step loop | max_steps prevents (default 50) | Low |
| Adapter memory leak | No mitigation | Medium |

---

## 5. State Model

### 5.1 Current state lifetime

```
RunState: created in memory -> modified during run -> returned to CLI -> discarded
EvidenceLog: created in memory -> modified during run -> saved IF --report -> discarded
```

Nothing survives process termination.

### 5.2 Proposed state model

```
RunState:
  - persisted to .orchestrator/runs/{run_id}/state.json on every phase transition
  - persisted on evidence record
  - persisted on workflow completion
  - recoverable from disk after process restart

EvidenceLog:
  - persisted to .orchestrator/runs/{run_id}/evidence.jsonl (append-only)
  - each entry written atomically
  - survives process termination

Run Index:
  - .orchestrator/runs/index.json updated on run start/complete
  - contains: run_id, workflow, mode, status, start/end times
  - enables run history queries
```

### 5.3 What must NEVER persist

- API keys or tokens
- Agent prompts containing secrets
- Raw environment variables
- Passwords or credentials
- Private keys

---

## 6. Recovery Model

### 6.1 Run recovery

When the orchestrator starts, it can:

1. Check `.orchestrator/runs/` for any run in non-terminal state
2. Report the interrupted run to the user
3. Offer to:
   - Resume from last known state
   - Mark as CANCELLED and archive
   - Discard

### 6.2 Evidence recovery

Even if state recovery is not implemented, evidence must survive:

- Each evidence entry is written as a JSON line to a persistent file
- On restart, evidence can be inspected even if state is lost
- Evidence is append-only (no overwrites)

### 6.3 Crash-safe writes

- Use atomic writes (write to temp file, then rename)
- On Windows, use `os.replace()` which is atomic
- Validate file integrity on read (optional checksum)

---

## 7. Multi-Agent Failure Model

### 7.1 Current gaps

| Gap | Description | Severity |
|-----|-------------|----------|
| No task retry | Failed agent tasks are not retried | High |
| No timeout enforcement | Agent timeout_seconds exists but scheduler doesn't enforce it | High |
| No deadlock detection | Sequential execution only (no deadlock possible currently) | Low |
| No duplicate work prevention | Same task could be assigned twice | Medium |
| No result validation | Agent output is used as-is | High |
| No cancellation propagation | Cannot cancel a running agent | Medium |

### 7.2 Proposed additions

**Task retry**: Configurable retry count per task (default 0 for safety).

**Timeout enforcement**: Scheduler wraps agent execution in a timeout check
using `time.monotonic()`.  Agent state set to FAILED on timeout.

**Result validation**: Agent output is checked for:
- Non-empty response
- Valid encoding
- Expected structure (if applicable)
- No obviously dangerous content (shell commands, file deletion, etc.)

**Cancellation**: Add a `cancelled` flag to TaskScheduler.  Checked between
tasks.  Running tasks cannot be interrupted (they use blocking subprocess)
but new tasks are not started.

---

## 8. Provider Failure Model

### 8.1 Current gaps

| Gap | Risk |
|-----|------|
| No health check before workflow | Provider fails mid-workflow |
| No retry on transient errors | Network blip = permanent failure |
| No response validation | Malformed JSON silently used |
| No timeout enforcement | Provider call blocks indefinitely |
| No fallback chain | Single point of failure |

### 8.2 Proposed additions

**Pre-flight health check**: Before workflow starts, check if configured
provider is reachable.  Record in policy pre-flight decisions.

**Response validation**: Validate that provider response is:
- Non-empty
- Valid JSON (for structured responses)
- Contains expected fields
- Within reasonable size bounds

**Timeout**: Use `urllib` timeout parameter (currently not set on
`urlopen`).  Default 30s.

**Fallback**: If primary provider fails, try fallback (if configured).
If no fallback, mark agent as BLOCKED.

---

## 9. Security Model

### 9.1 Path boundary enforcement

Currently, path operations use `pathlib.Path` which is safe against
traversal, but there is no explicit validation that:
- Tool paths are within the workspace
- Project paths don't escape the workspace
- Evidence paths are within the orchestrator directory

**Proposed**: Add `validate_path_boundary(base, target)` utility that
ensures `target` is a descendant of `base`.  Use in adapter, engine,
and evidence modules.

### 9.2 Tool output sanitization

Currently, tool output is used as-is.  For security-sensitive operations:

- Agent output containing shell commands should be flagged
- File deletion commands in output should be flagged
- Network commands in output should be flagged
- Output suggesting `--no-verify` should be flagged

**Proposed**: Add `SecurityScan` utility that flags suspicious patterns
in tool/agent output.  Not a hard block (that would be too restrictive)
but an evidence record + WARN decision.

### 9.3 Concurrent run protection

Currently, nothing prevents two orchestrator processes from running
simultaneously on the same workspace.  This could cause:
- Race conditions on evidence files
- Conflicting state updates
- Duplicate tool executions

**Proposed**: Use a simple lockfile (`.orchestrator/lock`) with PID
recording.  On startup, check for stale locks (PID not running) and
acquire lock before proceeding.

### 9.4 Configuration integrity

Currently, config is read but not integrity-checked.  A malicious
modification to `.orchestrator/config` could:
- Change mode to weaken policy
- Set invalid values
- Introduce unknown keys (rejected but could cause confusion)

**Proposed**: Optional config checksum stored alongside config.
If checksum exists and doesn't match, warn the user.

---

## 10. Evidence / Audit Model

### 10.1 Current evidence model

- EvidenceLog is append-only within a run
- Each entry has: timestamp, run_id, action, tool, operation, args,
  exit_code, status, duration, detail
- Secret redaction applied to args and detail
- Evidence is serialized to JSON
- Saved only if `--report PATH` is specified

### 10.2 Proposed evidence model

**Persistent evidence**: Each evidence entry is written to a JSONL file
immediately (not buffered).  This ensures evidence survives crashes.

**Run index**: A central index tracks all runs:
```json
{
  "runs": [
    {
      "run_id": "RUN-20260825-174630-cfc871",
      "workflow": "bootstrap",
      "mode": "solo",
      "status": "PASS",
      "started_at": "2026-08-25T17:46:30Z",
      "ended_at": "2026-08-25T17:46:31Z",
      "evidence_count": 8
    }
  ]
}
```

**Evidence integrity**: Optional SHA-256 hash chain.  Each entry includes
the hash of the previous entry.  Tampering with an entry breaks the chain.

**Evidence query**: CLI commands to inspect evidence:
- `orchestrator history` — list recent runs
- `orchestrator show RUN-ID` — show run details
- `orchestrator evidence RUN-ID` — show evidence entries

---

## 11. Configuration Model

### 11.1 Current configuration

- `.orchestrator/config`: key=value lines
- `workflow.md`: project workflow rules
- Mode selection: CLI > config > default

### 11.2 Proposed hardening

**Value validation**: Validate config values against expected types:
- `max_tool_timeout`: integer, 1-3600
- `diff_gate_required`: true/false
- `sandbox_required`: true/false
- `sandbox_strict`: true/false
- `approval_required`: true/false
- `llm_cloud_allowed`: true/false
- `host_fallback_allowed`: true/false
- `evidence_level`: basic/standard/enhanced/complete

**Config schema version**: Add `version = 1` to config.  Future versions
can add migration logic.

**Environment variable override**: Allow critical values to be overridden
by environment variables (e.g., `ORCHESTRATOR_MODE=security`).  This
enables CI/CD integration without config file changes.

---

## 12. Testing Strategy

### 12.1 Gap analysis

| Test category | Current coverage | Gap |
|---------------|:----------------:|-----|
| Unit tests | Good (396 tests) | No failure injection |
| Integration tests | Basic (real tool adapters) | No multi-agent integration |
| Security tests | Basic (shell=True AST, secret redaction) | No path traversal, no output injection |
| State tests | Good (phase transitions) | No crash recovery tests |
| Concurrency tests | None | No concurrent run tests |
| Provider tests | Basic (mock + real) | No timeout, no malformed response |
| Recovery tests | None | No crash recovery tests |
| Resource tests | None | No resource limit tests |
| CLI tests | Good | No run history, resume tests |

### 12.2 Proposed new tests

**Failure injection tests**:
- Tool returns empty output
- Tool returns malformed output
- Tool returns output containing injection patterns
- Provider returns invalid JSON
- Provider times out
- Disk full during evidence write
- Config file corrupted mid-read

**Security tests**:
- Path traversal attempt in tool arguments
- Agent output containing shell commands
- Agent output containing `--no-verify`
- Config attempting to weaken mandatory rules
- Concurrent run lock acquisition
- Evidence tampering detection

**Recovery tests**:
- Interrupted run state recovery
- Evidence integrity after crash
- Stale lock detection
- Config checksum validation

**Concurrency tests**:
- Two processes attempting same workspace
- Lock acquisition and release
- Stale lock cleanup

---

## 13. CLI Requirements

### 13.1 New commands

| Command | Purpose |
|---------|---------|
| `orchestrator history` | List recent runs from index |
| `orchestrator show RUN-ID` | Show run details and status |
| `orchestrator evidence RUN-ID` | Show evidence entries for a run |
| `orchestrator cancel RUN-ID` | Cancel a running/pending run |
| `orchestrator resume RUN-ID` | Resume a blocked run |

### 13.2 Modified commands

| Command | Change |
|---------|--------|
| `orchestrator run` | Auto-persist evidence and state |
| `orchestrator run --report` | Still works, now in addition to auto-save |
| `orchestrator doctor` | Add lock status, provider health |

### 13.3 Output format

History command output:
```
RUN-20260825-174630-cfc871  bootstrap    solo    PASS    2026-08-25T17:46:30Z  8 entries
RUN-20260825-174632-6a7395  development  sec     BLOCKED 2026-08-25T17:46:32Z  4 entries
```

---

## 14. Compatibility Requirements

### 14.1 What must not change

- Zero external dependencies
- Python standard library only
- All existing CLI commands work identically
- All 396 existing tests pass
- All 7 tool repositories untouched
- shell=False enforcement
- Fail-closed security behavior
- Mandatory safety rules remain inviolable
- Agent permissions remain immutable
- Policy engine authority remains above agents
- Evidence remains append-only
- All four modes remain functional

### 14.2 What may change

- Evidence is now auto-persisted (additive, no behavior change)
- Engine logs more detail (additive)
- Config validation is stricter (may reject previously-accepted garbage values)
- New CLI commands are added (additive)
- Report format may gain additional sections (additive)

### 14.3 Backwards compatibility test

After Phase 8, verify:
- `orchestrator --help` works
- `orchestrator --version` works
- `orchestrator status` works
- `orchestrator status --json` works
- `orchestrator doctor` works
- `orchestrator run --mode solo` works
- `orchestrator run --mode development` works
- `orchestrator run --mode security` works
- `orchestrator run --mode enterprise` works
- `orchestrator modes` works
- `orchestrator policies solo` works
- All 396+ tests pass

---

## 15. Proposed Modules / Files

### 15.1 New modules

| Module | Lines (est.) | Purpose |
|--------|:------------:|---------|
| `persist.py` | ~200 | Run state/evidence persistence, atomic writes, run index |
| `recovery.py` | ~100 | Crash recovery, interrupted run detection, lock management |
| `validate.py` | ~150 | Path boundary, output validation, config value validation |
| `security_scan.py` | ~80 | Suspicious pattern detection in tool/agent output |
| **Total** | **~530** | |

### 15.2 Modified modules

| Module | Change |
|--------|--------|
| `engine.py` | Auto-persist state on transitions, check cancellation, enforce timeouts |
| `evidence.py` | Auto-save entries to JSONL file |
| `adapter.py` | Enforce policy timeout, validate tool output |
| `scheduler.py` | Enforce agent timeout, add cancellation flag |
| `providers.py` | Add health check, timeout on urlopen, response validation |
| `cli.py` | Add history, show, evidence, cancel, resume commands |
| `config.py` | Add value validation, schema version, env var override |
| `report.py` | Add run history section, evidence integrity info |

### 15.3 New test files

| File | Purpose |
|------|---------|
| `tests/test_persist.py` | Persistence, atomic writes, run index |
| `tests/test_recovery.py` | Crash recovery, lock management |
| `tests/test_validate.py` | Path boundary, output validation, config validation |
| `tests/test_security_scan.py` | Suspicious pattern detection |
| `tests/test_hardening_integration.py` | End-to-end hardening integration tests |

---

## 16. Data Structures

### 16.1 Run persistence

```python
@dataclass
class PersistedRun:
    run_id: str
    workflow_name: str
    mode: str
    status: str  # PASS/FAIL/BLOCKED
    phase: str
    started_at: str
    ended_at: str
    project_dir: str
    workspace_dir: str
    tool_call_count: int
    evidence_count: int
    state_path: str  # path to state.json
    evidence_path: str  # path to evidence.jsonl
```

### 16.2 Run index

```python
@dataclass
class RunIndex:
    runs: list[PersistedRun]
    version: int = 1
```

### 16.3 Lock file

```python
@dataclass
class LockFile:
    pid: int
    acquired_at: str
    workspace: str
    run_id: str | None = None
```

### 16.4 Path validation result

```python
@dataclass(frozen=True)
class PathCheck:
    valid: bool
    reason: str
    resolved: str
```

### 16.5 Security scan result

```python
@dataclass(frozen=True)
class SecurityFinding:
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    category: str  # injection, command, path_traversal, etc.
    detail: str
    line: str | None = None
```

---

## 17. Interfaces

### 17.1 Persistence interface

```python
def save_run_state(state: RunState, base_dir: Path) -> Path:
    """Atomically save run state to disk.  Returns path."""

def load_run_state(run_id: str, base_dir: Path) -> RunState | None:
    """Load run state from disk.  Returns None if not found."""

def append_evidence(entry: dict, evidence_path: Path) -> None:
    """Append a single evidence entry atomically."""

def load_evidence(evidence_path: Path) -> list[dict]:
    """Load all evidence entries from a JSONL file."""

def update_run_index(index_path: Path, run: PersistedRun) -> None:
    """Add or update a run in the index."""

def list_runs(index_path: Path, limit: int = 20) -> list[PersistedRun]:
    """List recent runs from the index."""
```

### 17.2 Validation interface

```python
def validate_path_boundary(base: Path, target: Path) -> PathCheck:
    """Verify target is within base directory."""

def validate_config_value(key: str, value: str) -> bool:
    """Validate a config value against expected type/range."""

def scan_output(text: str) -> list[SecurityFinding]:
    """Scan tool/agent output for suspicious patterns."""
```

### 17.3 Recovery interface

```python
def acquire_lock(workspace: Path, run_id: str) -> bool:
    """Try to acquire workspace lock.  Returns True on success."""

def release_lock(workspace: Path) -> None:
    """Release workspace lock."""

def check_stale_lock(workspace: Path) -> bool:
    """Check if existing lock is stale (PID not running)."""

def find_interrupted_runs(base_dir: Path) -> list[PersistedRun]:
    """Find runs in non-terminal state."""
```

---

## 18. State Transitions

### 18.1 Persistence triggers

State is persisted to disk on:
- Run created (initial state)
- Phase transition (every transition)
- Tool call recorded
- Evidence entry recorded
- Policy decision recorded
- Workflow completed/failed/blocked
- Cancellation requested

### 18.2 Recovery state transitions

```
Interrupted run (non-terminal state on disk)
  |
  +--> User selects "resume"
  |      |
  |      v
  |    Load state from disk
  |      |
  |      v
  |    Validate state integrity
  |      |
  |      +--> Valid: continue from last phase
  |      |
  |      +--> Invalid: mark as CANCELLED, archive
  |
  +--> User selects "cancel"
  |      |
  |      v
  |    Mark as CANCELLED, archive
  |
  +--> User selects "discard"
         |
         v
       Delete run directory
```

---

## 19. Failure Behavior

### 19.1 Persistence failures

| Failure | Behavior |
|---------|----------|
| Cannot write state file | Log warning, continue run (evidence in memory) |
| Cannot write evidence file | Log warning, continue run (evidence in memory) |
| Corrupted state on disk | Report to user, offer recovery options |
| Full disk | Log error, attempt to save evidence to stderr |
| Permission denied on .orchestrator/ | Log error, run without persistence |

### 19.2 Lock failures

| Failure | Behavior |
|---------|----------|
| Lock held by running process | BLOCK: "Another run is active" |
| Lock held by dead process | Auto-clean stale lock, acquire |
| Cannot create lock file | Log warning, proceed without lock |
| Cannot remove lock file | Log warning, proceed (lock is advisory) |

### 19.3 Validation failures

| Failure | Behavior |
|---------|----------|
| Path boundary violation | DENY in policy decision |
| Invalid config value | INVALID exit code, report error |
| Suspicious output pattern | WARN in evidence, continue |
| Config checksum mismatch | WARN to user, continue |

---

## 20. Security Invariants

The following invariants MUST be preserved after Phase 8:

1. **Zero external dependencies** — Python standard library only.
2. **No shell=True** — AST-verified, no exceptions.
3. **Mandatory safety rules inviolable** — No mode, config, or agent can weaken them.
4. **Fail closed on uncertainty** — Unknown state = BLOCKED/FAIL.
5. **Evidence is append-only** — No silent overwrites of historical evidence.
6. **Agent permissions immutable** — Frozen dataclasses, no runtime modification.
7. **7 tool repositories untouched** — Orchestrator integrates, never modifies.
8. **No fabricated results** — Every claim backed by actual tool execution.
9. **Sandbox fail-closed** — UNSUPPORTED = BLOCKED, never silent host fallback.
10. **Secrets never in logs** — Regex redaction + no secret parameters.
11. **Policy above agents** — Agent cannot override policy decisions.
12. **No bypass gates** — No `--no-verify`, no silent gate skipping.
13. **Human authority preserved** — Memory promotion, policy changes require human.
14. **Deterministic-first** — LLM used only after deterministic analysis.
15. **Tool output is untrusted data** — Never blindly executed or trusted.

---

## 21. Migration / Backwards Compatibility

### 21.1 No breaking changes

Phase 8 is entirely additive.  No existing behavior changes.

- Evidence auto-save is new behavior (previously required `--report`)
- Persistence is new (previously no persistence)
- New CLI commands are new
- Config validation is stricter (may reject previously-accepted garbage)

### 21.2 Config migration

If config value validation rejects a previously-accepted value, the error
message must clearly explain:
- What value was found
- What values are accepted
- How to fix the config

### 21.3 State directory

New directory `.orchestrator/runs/` is created on first run.
If it cannot be created, persistence is gracefully disabled with a warning.

---

## 22. Implementation Phases

Phase 8 is split into 4 sub-phases to manage complexity.

### Phase 8A — Persistence & Evidence (CRITICAL)

**Scope**: Modules `persist.py`, modifications to `evidence.py`, `engine.py`

**Changes**:
- Create `persist.py` with atomic write, JSONL evidence, run index
- Modify `evidence.py` to auto-save entries to JSONL
- Modify `engine.py` to persist state on transitions
- Add `.orchestrator/runs/` directory management
- Tests for persistence, atomic writes, crash survival

**Exit criteria**:
- Evidence survives process interruption (Ctrl+C test)
- Run state persists on disk
- Run index tracks all runs
- All existing tests pass
- New persistence tests pass

### Phase 8B — Validation & Security (HIGH)

**Scope**: Modules `validate.py`, `security_scan.py`, modifications to `adapter.py`, `config.py`

**Changes**:
- Create `validate.py` with path boundary, config value validation
- Create `security_scan.py` with output pattern scanning
- Modify `adapter.py` to validate tool output paths
- Modify `config.py` to validate value types/ranges
- Tests for path traversal, injection detection, config validation

**Exit criteria**:
- Path boundary violations detected and denied
- Malformed config values rejected
- Suspicious output patterns flagged
- All existing tests pass
- New validation tests pass

### Phase 8C — Recovery & CLI (MEDIUM)

**Scope**: Module `recovery.py`, modifications to `cli.py`, `scheduler.py`, `providers.py`

**Changes**:
- Create `recovery.py` with lock management, interrupted run detection
- Add CLI commands: history, show, evidence, cancel
- Modify `scheduler.py` to enforce agent timeout, add cancellation
- Modify `providers.py` to add health check, timeout, response validation
- Add `orchestrator doctor` lock status and provider health
- Tests for recovery, CLI commands, timeout enforcement

**Exit criteria**:
- Lock prevents concurrent runs
- Interrupted runs detected on startup
- CLI history shows past runs
- Agent timeout enforced
- Provider health checked before workflow
- All existing tests pass
- New recovery/CLI tests pass

### Phase 8D — Integration & Final Audit (REQUIRED)

**Scope**: Full integration test, security audit, documentation

**Changes**:
- End-to-end integration test exercising all Phase 8 features
- Full AST audit for shell=True
- Full dependency audit
- 7-repository integrity check
- Documentation updates
- Final implementation report

**Exit criteria**:
- Complete integration test passes
- 0 shell=True
- 0 external dependencies
- 7 repos untouched
- All tests pass (existing + new)
- PHASE_8_IMPLEMENTATION_REPORT.md created

---

## 23. Exit Criteria

Phase 8 is complete when ALL of the following are true:

- [ ] Evidence auto-persists to disk during runs
- [ ] Run state persists on disk
- [ ] Process interruption does not lose evidence
- [ ] Run index tracks all runs
- [ ] `orchestrator history` lists past runs
- [ ] `orchestrator show RUN-ID` shows run details
- [ ] `orchestrator evidence RUN-ID` shows evidence
- [ ] Path boundary validation enforced
- [ ] Config value validation enforced
- [ ] Suspicious output patterns flagged
- [ ] Workspace lock prevents concurrent runs
- [ ] Interrupted runs detected on startup
- [ ] Agent timeout enforced by scheduler
- [ ] Provider health checked before workflow
- [ ] Provider response validated
- [ ] All existing 396+ tests pass
- [ ] All new Phase 8 tests pass
- [ ] Zero external dependencies
- [ ] Zero shell=True (AST-verified)
- [ ] 7 tool repositories untouched
- [ ] All four modes still operational
- [ ] PHASE_8_IMPLEMENTATION_REPORT.md created

---

## 24. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|:----------:|:------:|------------|
| Persistence adds complexity | High | Medium | Keep persist.py focused; simple JSON/JSONL |
| Atomic writes platform differences | Medium | Low | Use os.replace() (cross-platform atomic) |
| Lock file race conditions | Low | Medium | Advisory lock with PID check |
| Config validation rejects valid configs | Medium | Medium | Clear error messages, generous validation |
| Performance overhead from persistence | Low | Low | Append-only JSONL is fast; state save is infrequent |
| New tests take long to run | Low | Low | Persistence tests use temp directories |
| Recovery logic is complex | Medium | Medium | Keep recovery simple: report + options |

---

## 25. Open Architectural Decisions

### 25.1 Persistence granularity

**Question**: Should state be persisted on EVERY phase transition, or batched?

**Option A**: Every transition (safest, most I/O)
**Option B**: Every N transitions or on important events only (faster, slightly riskier)

**Recommendation**: Option A.  The performance cost is negligible for CLI usage,
and crash safety is paramount for production readiness.

### 25.2 Evidence format

**Question**: JSONL (one JSON object per line) vs single JSON array?

**Option A**: JSONL — append-friendly, crash-safe, streamable
**Option B**: JSON array — simpler to read, requires re写 entire file on append

**Recommendation**: JSONL.  Matches the append-only philosophy and crash safety
requirement.

### 25.3 Lock implementation

**Question**: File-based lock (PID in file) vs directory-based lock (mkdir atomic)?

**Option A**: PID file — simple, cross-platform, stale detection via kill(0)
**Option B**: mkdir — atomic on most filesystems, but not on all Windows NTFS

**Recommendation**: PID file with stale detection.  More portable, clearer error
messages.

### 25.4 Auto-save scope

**Question**: Auto-save evidence only, or also state?

**Option A**: Evidence only (state reconstructed from evidence if needed)
**Option B**: Both evidence and state (explicit, simpler recovery)

**Recommendation**: Option B.  State reconstruction from evidence is complex
and error-prone.  Explicit state files are simpler and more reliable.

### 25.5 Recovery interaction

**Question**: Should the orchestrator automatically offer recovery on startup,
or require explicit `orchestrator recover` command?

**Option A**: Automatic — check on every CLI invocation
**Option B**: Explicit — only check when user runs `orchestrator recover`

**Recommendation**: Hybrid.  Check on `orchestrator run` (warn if interrupted
runs exist, offer to resume or ignore).  Also provide explicit `orchestrator
history` for manual inspection.

---

## 26. Dashboard Readiness Recommendation

After Phase 8 is complete, the orchestrator will have:

- Persistent run history
- Evidence integrity
- Crash recovery
- Run inspection CLI
- Security validation
- Resource protection

**These are prerequisites for a dashboard.**  A dashboard that displays
ephemeral data is not useful.  A dashboard that displays persisted,
verified, crash-safe run history IS useful.

**Recommendation**: After Phase 8, the orchestrator IS ready for a dashboard.
The dashboard can read `.orchestrator/runs/` and present run history,
evidence, security findings, and status in a web interface.

However, the dashboard must remain:
- Optional (CLI is primary interface)
- Zero-dependency (use Python `http.server` stdlib)
- Not a core dependency (failure to load dashboard must not affect CLI)
- Read-only by default (dashboard observes, does not modify)

**Suggested dashboard phase**: Phase 9 — Dashboard / Web UI (after Phase 8).

---

## WHAT MUST NOT CHANGE

These architectural principles from Phases 1-7 are inviolable:

1. **ZERO external dependencies** — Python stdlib only
2. **No shell=True** — enforced everywhere
3. **Mandatory safety rules cannot be weakened** — by any mode, config, or agent
4. **Fail closed on uncertainty** — unknown = BLOCKED/FAIL
5. **Evidence is append-only** — no silent rewrites
6. **Agent permissions are immutable** — frozen dataclasses
7. **7 tool repositories are untouched** — orchestrator integrates, never modifies
8. **No fabricated results** — every claim backed by evidence
9. **Sandbox fail-closed** — UNSUPPORTED = BLOCKED, never host fallback
10. **Secrets never in logs** — redaction + no secret parameters
11. **Policy is above agents** — agents cannot override policy
12. **No gate bypass** — no `--no-verify`, no silent gate skipping
13. **Human authority is preserved** — memory promotion, policy changes
14. **Deterministic-first** — LLM only after deterministic analysis
15. **Tool output is untrusted data** — never blindly executed
16. **Agents propose, orchestrator decides** — agents cannot self-authorize
17. **No direct agent-to-agent communication** — orchestrator mediates
18. **Backwards compatibility with Phases 1-7** — all existing CLI, modes, tests
19. **CLI-first design** — dashboard is optional
20. **Small, focused modules** — no monolithic redesigns

---

*End of Phase 8 Hardening Design Document*
