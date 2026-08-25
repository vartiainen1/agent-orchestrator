# Phase 7 — Operating Modes Design Proposal

## 1. Objective

Make the four operating modes (SOLO, DEVELOPMENT, SECURITY, ENTERPRISE)
fully operational through the CLI, with end-to-end verification that
each mode produces genuinely different enforcement behavior.

Phase 7 integrates existing components (PolicyEngine, WorkflowEngine,
TaskScheduler, ToolAdapters) into mode-driven execution paths accessible
via a single CLI command.

## 2. Current architecture (inspected)

| Module | Lines | Role |
|--------|:-----:|------|
| cli.py | 293 | CLI: --help, --version, status, doctor |
| modes.py | 196 | Mode enum, base safety rules, mode rules |
| policy.py | 410 | Policy class, pre/post-flight, config loading |
| engine.py | 337 | WorkflowEngine with policy integration |
| agents.py | 397 | Agent identity, roles, permissions, lifecycle |
| providers.py | 250 | AI providers (Ollama, None) |
| scheduler.py | 384 | Task assignment, sequential/parallel execution |
| adapter.py | 500 | 7 tool adapters |
| workflow.py | 238 | Workflow definitions, 3 predefined workflows |
| evidence.py | 116 | EvidenceLog, secret redaction |
| report.py | 167 | Markdown/JSON report generation |
| state.py | 160 | Phase enum, RunState, ToolCall |
| discovery.py | 387 | Tool discovery, health checks |
| config.py | 145 | Configuration loading |

Total: 4,644 lines source, 2,880 lines tests.

## 3. CLI design

### 3.1 New command: `run`

```
orchestrator run [OPTIONS]

Options:
  --mode MODE        operating mode: solo, development, security, enterprise
                     (default: from config, or "solo")
  --workflow NAME    workflow to execute (default: mode-appropriate)
  --verbose          enable debug logging
  --json             output report as JSON
  --report PATH      save report to file
```

### 3.2 Existing commands preserved

```
orchestrator --help       (unchanged)
orchestrator --version    (unchanged)
orchestrator status       (unchanged, add --mode display)
orchestrator doctor       (unchanged, add mode-aware checks)
orchestrator modes        (NEW: list available modes)
orchestrator policies     (NEW: show effective policy for a mode)
```

### 3.3 Mode selection precedence

1. CLI `--mode` flag (highest priority)
2. `.orchestrator/config` `mode = X` setting
3. Default: `solo`

Invalid mode -> error message + exit INVALID.

## 4. Per-mode behavior

### 4.1 SOLO

**Purpose**: Individual developer, experimentation, lowest ceremony.

| Aspect | SOLO behavior |
|--------|--------------|
| Default workflow | bootstrap |
| error-log check | Required (gate) |
| decision-log check | Required (gate) |
| diff-gate | Optional |
| sandbox | Optional |
| agents | DEVELOPER role only |
| AI providers | All (Ollama, None, cloud) |
| evidence | Basic |
| approval | Never |
| failure | Gate fail -> BLOCK; optional fail -> continue |

**CLI behavior**:
```
$ orchestrator run --mode solo
[bootstrap] error-log check: PASS
[bootstrap] decision-log check: PASS
[done] workflow completed: PASS
```

**What SOLO does NOT enforce**:
- Does not require diff-gate before completion
- Does not require sandbox for execution
- Does not restrict AI providers

### 4.2 DEVELOPMENT

**Purpose**: Normal software development with full workflow discipline.

| Aspect | DEVELOPMENT behavior |
|--------|---------------------|
| Default workflow | development |
| error-log check | Required (gate) |
| decision-log check | Required (gate) |
| diff-gate | Required |
| sandbox | Required |
| agents | DEVELOPER, REVIEWER, TESTER roles |
| AI providers | All except restricted cloud |
| evidence | Standard |
| approval | Never |
| failure | Any gate/required fail -> BLOCK |

**CLI behavior**:
```
$ orchestrator run --mode development
[bootstrap] error-log check: PASS
[bootstrap] decision-log check: PASS
[check] diff-gate rules loaded: 14 rules
[check] sandbox available: UNSUPPORTED (Windows)
[blocked] sandbox required but unavailable
```

**Key difference from SOLO**: diff-gate and sandbox are mandatory.

### 4.3 SECURITY

**Purpose**: Security-sensitive work with stronger validation.

| Aspect | SECURITY behavior |
|--------|------------------|
| Default workflow | development (with security enhancements) |
| error-log check | Required (gate) |
| decision-log check | Required (gate) |
| diff-gate | Required (strict) |
| sandbox | Mandatory (no host fallback) |
| agents | DEVELOPER, REVIEWER, SECURITY, TESTER roles |
| AI providers | Local only (Ollama, None) |
| evidence | Enhanced |
| approval | Required for security-sensitive operations |
| failure | Fail closed on any uncertainty |

**CLI behavior**:
```
$ orchestrator run --mode security
[bootstrap] error-log check: PASS
[bootstrap] decision-log check: PASS
[check] diff-gate rules loaded: 14 rules (strict)
[check] sandbox: BLOCKED (requires Linux)
[policy] llm_cloud_allowed: DENIED
[blocked] sandbox mandatory in SECURITY mode
```

**Key differences from DEVELOPMENT**:
- No cloud AI providers
- Strict sandbox (no host fallback)
- Enhanced evidence
- Security agent has highest authority

### 4.4 ENTERPRISE

**Purpose**: Maximum governance, auditability, accountability.

| Aspect | ENTERPRISE behavior |
|--------|-------------------|
| Default workflow | development (with enterprise enhancements) |
| error-log check | Required (gate) |
| decision-log check | Required (gate) |
| diff-gate | Required (strictest) |
| sandbox | Mandatory (isolated, audited) |
| agents | All roles available |
| AI providers | Local only |
| evidence | Complete audit trail |
| approval | Required for consequential actions |
| failure | Fail closed, full audit |

**CLI behavior**:
```
$ orchestrator run --mode enterprise
[bootstrap] error-log check: PASS
[bootstrap] decision-log check: PASS
[check] diff-gate rules loaded: 14 rules (strictest)
[check] sandbox: BLOCKED (requires Linux)
[policy] approval_required: REQUIRE_APPROVAL
[policy] evidence_level: complete
[blocked] sandbox mandatory in ENTERPRISE mode
```

**Key differences from SECURITY**:
- All agent roles available
- Complete evidence trail
- Approval requirements recorded
- Strongest policy enforcement

## 5. Integration architecture

```
orchestrator run --mode <MODE>
        |
        v
  1. Load mode (modes.py)
        |
        v
  2. Build effective policy (policy.py)
        |  base safety + mode rules + project config
        v
  3. Discover tools (discovery.py)
        |
        v
  4. Pre-flight policy check (policy.py)
        |  DENY -> BLOCK
        v
  5. Select workflow (workflow.py)
        |  mode-appropriate default workflow
        v
  6. Create agents (agents.py)
        |  mode-appropriate roles
        v
  7. Create scheduler (scheduler.py)
        |  register agents
        v
  8. Execute workflow (engine.py + policy)
        |  tools via adapters
        v
  9. Post-flight policy check (policy.py)
        |  DENY -> BLOCK
        v
 10. Generate report (report.py)
        |
        v
 11. Output (stdout or file)
```

## 6. Mode-specific workflow selection

| Mode | Default workflow | Available workflows |
|------|-----------------|-------------------|
| SOLO | bootstrap | bootstrap, doctor |
| DEVELOPMENT | development | bootstrap, development, doctor |
| SECURITY | development | bootstrap, development, doctor |
| ENTERPRISE | development | bootstrap, development, doctor |

The workflow engine already supports `policy` parameter. Phase 7
passes the mode-appropriate policy to the engine.

## 7. Mode-specific agent roles

| Mode | Available roles | Required roles |
|------|----------------|---------------|
| SOLO | DEVELOPER | None |
| DEVELOPMENT | DEVELOPER, REVIEWER, TESTER | None |
| SECURITY | DEVELOPER, REVIEWER, SECURITY, TESTER | None |
| ENTERPRISE | All 7 roles | None |

Agents are OPT-IN. The orchestrator works without agents (single-agent
workflow). When agents are available, the scheduler uses them.

## 8. Mode-specific provider restrictions

| Mode | Ollama | None | Cloud LLM |
|------|:------:|:----:|:---------:|
| SOLO | Yes | Yes | Yes |
| DEVELOPMENT | Yes | Yes | Yes |
| SECURITY | Yes | Yes | **No** |
| ENTERPRISE | Yes | Yes | **No** |

## 9. Evidence requirements per mode

| Mode | Tool calls | Gates | Policy decisions | Agent actions | Report format |
|------|:----------:|:-----:|:----------------:|:-------------:|:-------------:|
| SOLO | Basic | Yes | Yes | Optional | Markdown |
| DEVELOPMENT | Standard | Yes | Yes | Optional | Markdown + JSON |
| SECURITY | Enhanced | Yes | Yes | Enhanced | Markdown + JSON |
| ENTERPRISE | Complete | Yes | Yes | Complete | Markdown + JSON |

## 10. Security analysis

| Threat | Mitigation |
|--------|-----------|
| Mode bypass | Mode set at CLI/config, validated by policy |
| Privilege escalation | Policy can only tighten, never weaken |
| CLI/config conflict | CLI flag overrides config |
| Malicious config | Unknown keys rejected, mandatory rules protected |
| Unauthorized agent activation | Roles restricted per mode |
| Unauthorized tool activation | Tool permissions enforced per role |
| Provider bypass | Cloud providers blocked in SECURITY/ENTERPRISE |
| Sandbox bypass | Sandbox mandatory in DEV/SEC/ENT |
| Policy bypass | Mandatory rules inviolable |
| Enterprise approval bypass | Approval recorded, not auto-approved |
| Secret leakage | Redaction in all evidence/reports |
| Invalid mode manipulation | Mode validated at load time |

## 11. Acceptance criteria per mode

### SOLO
- [ ] `orchestrator run --mode solo` completes
- [ ] error-log gate enforced
- [ ] decision-log gate enforced
- [ ] diff-gate NOT required
- [ ] sandbox NOT required
- [ ] DEVELOPER agent role available
- [ ] All AI providers permitted
- [ ] Basic evidence produced
- [ ] Report shows SOLO mode

### DEVELOPMENT
- [ ] `orchestrator run --mode development` completes
- [ ] error-log gate enforced
- [ ] decision-log gate enforced
- [ ] diff-gate REQUIRED
- [ ] sandbox REQUIRED
- [ ] DEVELOPER, REVIEWER, TESTER roles available
- [ ] Sandbox unavailable -> BLOCKED
- [ ] Standard evidence produced
- [ ] Report shows DEVELOPMENT mode

### SECURITY
- [ ] `orchestrator run --mode security` completes
- [ ] error-log gate enforced
- [ ] decision-log gate enforced
- [ ] diff-gate REQUIRED (strict)
- [ ] sandbox MANDATORY (no host fallback)
- [ ] SECURITY role available
- [ ] Cloud AI BLOCKED
- [ ] Enhanced evidence produced
- [ ] Sandbox unavailable -> BLOCKED
- [ ] Report shows SECURITY mode

### ENTERPRISE
- [ ] `orchestrator run --mode enterprise` completes
- [ ] All SECURITY requirements met
- [ ] All agent roles available
- [ ] Approval requirements recorded
- [ ] Complete evidence trail
- [ ] Report shows ENTERPRISE mode

## 12. Proposed changes

### Modified files

| File | Change |
|------|--------|
| `orchestrator/cli.py` | Add `run`, `modes`, `policies` commands |
| `orchestrator/report.py` | Add mode-specific report sections |

### New files

| File | Purpose |
|------|---------|
| `tests/test_modes_integration.py` | End-to-end mode tests |

### NOT modified
- All existing modules (modes.py, policy.py, engine.py, etc.) — already support modes
- All 7 tool repositories
- pyproject.toml (no new dependencies)

## 13. Implementation steps

### Step 1: CLI `run` command
- Add `run` subcommand with `--mode` flag
- Wire mode -> policy -> engine execution
- Add mode validation
- Basic tests

### Step 2: CLI `modes` and `policies` commands
- `modes` lists available modes
- `policies` shows effective policy for a mode
- Tests

### Step 3: Mode-specific workflow selection
- Select default workflow based on mode
- Add workflow selection logic
- Tests

### Step 4: End-to-end SOLO test
- Run SOLO workflow
- Verify all acceptance criteria
- Integration test

### Step 5: End-to-end DEVELOPMENT test
- Run DEVELOPMENT workflow
- Verify diff-gate/sandbox required behavior
- Integration test

### Step 6: End-to-end SECURITY test
- Run SECURITY workflow
- Verify strict sandbox, no cloud AI
- Integration test

### Step 7: End-to-end ENTERPRISE test
- Run ENTERPRISE workflow
- Verify approval recording, complete evidence
- Integration test

### Step 8: Regression + final validation
- All 315+ tests pass
- Zero dependencies verified
- 7 repos untouched verified
- Report

## 14. Unresolved design questions

1. **Workflow selection**: Should the CLI auto-select the workflow based on mode, or should the user always specify? Recommendation: auto-select with override option.

2. **Agent activation**: Should agents be activated by default in all modes, or only when explicitly requested? Recommendation: agents are opt-in via a future `--agents` flag. Phase 7 focuses on mode enforcement without multi-agent.

3. **Report file naming**: Should reports be saved automatically or only with `--report`? Recommendation: only with `--report` flag.
