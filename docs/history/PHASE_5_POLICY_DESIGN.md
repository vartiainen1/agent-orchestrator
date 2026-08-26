# Phase 5 — Policy Engine Design Proposal

## 1. Objective

Design a policy engine that determines what is ALLOWED, REQUIRED, BLOCKED,
or REQUIRES APPROVAL — sitting above the Workflow Engine and below the
AI agent / user.

The Policy Engine makes deterministic, auditable decisions about whether
operations are permitted.  It does NOT execute workflows, invoke tools,
or replace any existing safety mechanism.

## 2. Architectural position

```
USER / AI AGENT
        |
        v
ORCHESTRATOR (CLI / entry point)
        |
        v
POLICY ENGINE          <-- Phase 5: determines what is permitted
        |
        v
WORKFLOW ENGINE        <-- Phase 4: executes state transitions
        |
        v
7 TOOL ADAPTERS        <-- Phase 3: normalized tool invocation
        |
        v
7 EXISTING TOOLS       <-- authorities for their own domains
```

The Policy Engine has two insertion points:

**Pre-flight** (before workflow starts):
- Is this mode allowed?
- Are the required tools available?
- Does the project configuration satisfy policy?
- Are there unresolved approval requirements?

**Post-flight** (after each tool result):
- Did the result satisfy mandatory gates?
- Does the result require additional action?
- Should the workflow be blocked or escalated?

## 3. Policy Engine responsibilities

- Load and validate policy configuration
- Determine the active mode (SOLO / DEVELOPMENT / SECURITY / ENTERPRISE)
- Evaluate pre-flight checks before workflow execution
- Evaluate post-flight checks after each tool invocation
- Produce policy decisions with reasons
- Record all policy decisions in the evidence log
- Enforce mandatory safety invariants that no mode can override
- Reject invalid or insecure configurations

## 4. Non-responsibilities

- Does NOT execute workflows (WorkflowEngine's job)
- Does NOT invoke tools (adapters' job)
- Does NOT make AI reasoning decisions
- Does NOT replace tool-level gates (error-log, diff-gate remain authoritative)
- Does NOT implement approval workflows (records that approval is needed)
- Does NOT modify the 7 existing tools
- Does NOT create a new evidence system (uses existing EvidenceLog)

## 5. Four mode definitions

### 5.1 SOLO

**Purpose**: Individual developer, experimentation, lowest ceremony.

| Aspect | SOLO behavior |
|--------|--------------|
| Error-log check | Required (gate) |
| Decision-log check | Required (gate) |
| Diff-gate | Optional |
| Sandbox | Preferred but not mandatory |
| Memory trust | Standard (untrusted excluded from recall) |
| Evidence | Basic (tool calls + final status) |
| Approval | Never required |
| LLM usage | Allowed (local-first) |
| Failure behavior | Fail on gate failure, continue on optional failures |

**What SOLO does NOT allow**:
- Cannot bypass error-log gate
- Cannot bypass decision-log gate
- Cannot bypass sandbox platform restrictions
- Cannot fabricate results

### 5.2 DEVELOPMENT

**Purpose**: Normal software development with full workflow discipline.

| Aspect | DEVELOPMENT behavior |
|--------|---------------------|
| Error-log check | Required (gate) |
| Decision-log check | Required (gate) |
| Diff-gate | Required before commits |
| Sandbox | Required for execution |
| Memory trust | Standard |
| Evidence | Standard (tool calls + gates + decisions) |
| Approval | Never required |
| LLM usage | Allowed (local-first, dry-run before live) |
| Failure behavior | Fail on any gate or required step failure |

**What DEVELOPMENT adds over SOLO**:
- Diff-gate is mandatory (not optional)
- Sandbox is required for code execution
- More structured evidence collection

### 5.3 SECURITY

**Purpose**: Security-sensitive work with stronger validation.

| Aspect | SECURITY behavior |
|--------|------------------|
| Error-log check | Required (gate) |
| Decision-log check | Required (gate) |
| Diff-gate | Required (strict: all severities) |
| Sandbox | Mandatory (no host fallback) |
| Memory trust | Stricter (no auto-promotion) |
| Evidence | Enhanced (more detail recorded) |
| Approval | Required for security-sensitive operations |
| LLM usage | Restricted (no cloud, local-only) |
| Failure behavior | Fail closed on any uncertainty |

**What SECURITY adds over DEVELOPMENT**:
- Diff-gate runs with stricter thresholds
- Sandbox is absolute (never host fallback)
- Additional evidence requirements
- Approval required for certain operations
- No silent fallback from any security control

### 5.4 ENTERPRISE

**Purpose**: Maximum governance, auditability, and accountability.

| Aspect | ENTERPRISE behavior |
|--------|-------------------|
| Error-log check | Required (gate) |
| Decision-log check | Required (gate) |
| Diff-gate | Required (strictest) |
| Sandbox | Mandatory (isolated, audited) |
| Memory trust | Strictest (explicit promotion required) |
| Evidence | Complete audit trail |
| Approval | Required for consequential actions |
| LLM usage | Restricted and logged |
| Failure behavior | Fail closed, full audit |
| Additional | Per-agent identity, run isolation, policy enforcement |

**What ENTERPRISE adds over SECURITY**:
- Complete audit trail for every action
- Approval boundaries for consequential actions
- Stronger separation of duties
- Policy enforcement on all operations
- Reproducible execution records

## 6. Policy model

### 6.1 Layered policy composition

```
BASE SAFETY POLICY  (inviolable — no mode can weaken these)
        +
MODE POLICY         (per-mode rules)
        +
PROJECT POLICY      (optional per-project overrides, can only tighten)
        =
ACTIVE POLICY
```

**Rule**: Project policy can only ADD restrictions, never remove them.
Mode policy can only ADD restrictions over base policy, never remove them.

### 6.2 Policy data model

```python
@dataclass
class PolicyRule:
    name: str                    # e.g. "sandbox_required"
    value: str                   # e.g. "true", "strict", "false"
    source: str                  # "base", "mode", "project"
    reason: str                  # why this rule exists
    mandatory: bool              # True = cannot be overridden

@dataclass
class Policy:
    mode: str                    # "solo", "development", "security", "enterprise"
    rules: dict[str, PolicyRule] # rule name -> rule
    source_files: list[str]      # which files contributed rules
```

### 6.3 Core policy rules

| Rule name | SOLO | DEVELOPMENT | SECURITY | ENTERPRISE | Mandatory? |
|-----------|------|-------------|----------|------------|:----------:|
| `error_log_required` | true | true | true | true | Yes |
| `decision_log_required` | true | true | true | true | Yes |
| `diff_gate_required` | false | true | true | true | No |
| `sandbox_required` | false | true | true | true | No |
| `sandbox_strict` | false | false | true | true | No |
| `approval_required` | false | false | false | true | No |
| `memory_auto_promote` | false | false | false | false | Yes (always false) |
| `evidence_level` | basic | standard | enhanced | complete | No |
| `llm_cloud_allowed` | true | true | false | false | No |
| `host_fallback_allowed` | true | false | false | false | No |
| `max_tool_timeout` | 30 | 30 | 60 | 120 | No |

**Mandatory rules** (marked Yes) are inviolable — no mode or project
configuration can override them.  They represent the ecosystem's
hard safety invariants.

## 7. Policy decision model

### 7.1 Decision outcomes

| Decision | Meaning |
|----------|---------|
| `ALLOW` | Operation is permitted |
| `DENY` | Operation is forbidden (with reason) |
| `REQUIRE_TOOL` | A specific tool must run before this is allowed |
| `REQUIRE_GATE` | A specific gate must pass before this is allowed |
| `REQUIRE_SANDBOX` | Execution must go through the sandbox |
| `REQUIRE_APPROVAL` | Human approval is needed (records the requirement) |
| `WARN` | Operation is permitted but a warning is recorded |

### 7.2 Decision record

```python
@dataclass
class PolicyDecision:
    rule: str              # which rule was evaluated
    outcome: str           # ALLOW / DENY / REQUIRE_* / WARN
    reason: str            # human-readable explanation
    mode: str              # active mode
    mandatory: bool        # was this a mandatory rule?
    timestamp: str         # when the decision was made
    context: str           # additional context (tool name, step, etc.)
```

## 8. Policy/workflow interaction

### 8.1 Pre-flight check

Before `WorkflowEngine.run()` starts:

```python
policy = load_policy(mode, project_dir)
decisions = policy.pre_flight(workflow, available_tools)
for d in decisions:
    if d.outcome == "DENY":
        return RunState(final_status="BLOCKED", reason=d.reason)
    if d.outcome == "REQUIRE_TOOL":
        # Add the required tool to the workflow
        workflow.steps.insert(0, required_step)
```

### 8.2 Post-flight check

After each tool invocation in `WorkflowEngine._invoke_step()`:

```python
decisions = policy.post_flight(step, result, state)
for d in decisions:
    if d.outcome == "DENY":
        state.transition(Phase.BLOCKED)
        return
    if d.outcome == "REQUIRE_APPROVAL":
        state.observe(f"APPROVAL REQUIRED: {d.reason}")
        # Record but do not block (approval is a future mechanism)
```

### 8.3 What policy CAN do

- Prevent a workflow from starting (DENY)
- Require additional tools be added to the workflow
- Require specific gates pass
- Require sandbox execution
- Record that human approval is needed
- Tighten timeout values
- Restrict evidence level
- Block operations after results

### 8.4 What policy CANNOT do

- Override a tool's own gate (error-log says fail -> policy cannot make it pass)
- Bypass sandbox platform restrictions (Linux-only remains Linux-only)
- Promote untrusted memory
- Fabricate approval
- Weaken mandatory base safety rules
- Execute tools directly
- Modify the 7 existing tools

## 9. Policy/tool interaction

The Policy Engine does NOT interact with tools directly.

It interacts with the Workflow Engine, which interacts with adapters,
which interact with tools.

```
Policy Engine
    |
    v  (policy decisions)
Workflow Engine
    |
    v  (tool calls via adapters)
Tool Adapters
    |
    v  (subprocess invocation)
Existing Tools
    |
    v  (exit codes, stdout, stderr)
Tool Results
    |
    v  (fed back to Policy Engine for post-flight)
```

The policy engine's authority is LIMITED to:
1. Whether a workflow/step is permitted
2. Whether additional requirements must be satisfied
3. Whether the workflow should be blocked

It NEVER:
- Interprets tool output as policy decisions
- Overrides tool exit codes
- Modifies tool behavior

## 10. Security invariants

These are inviolable — no mode, no project config, no policy override
can change them:

1. **Error-log gate is mandatory**: If error-log check fails, workflow is BLOCKED.
2. **Decision-log gate is mandatory**: If decision-log check fails, workflow is BLOCKED.
3. **Sandbox platform restrictions are absolute**: agent-sandbox on non-Linux = UNSUPPORTED, no host fallback.
4. **Memory trust model is preserved**: No auto-promotion of untrusted memory.
5. **No fabricated results**: Policy cannot claim a tool passed when it didn't.
6. **No `git commit --no-verify`**: The commit gate cannot be bypassed.
7. **No secret leakage**: Secrets are redacted from all evidence/logs.
8. **Fail closed on uncertainty**: If policy cannot be determined, BLOCK.
9. **No silent security downgrade**: SECURITY/ENTERPRISE cannot silently become SOLO.
10. **Evidence is append-only**: Policy decisions cannot rewrite history.

## 11. Approval model

**Phase 5 limitation**: The approval model is RECORD-ONLY.

The Policy Engine can determine that approval is required and record
this in the evidence log.  It does NOT implement an approval workflow
(such as waiting for a human click, sending notifications, etc.).

That is left for a future phase.

What Phase 5 does:
- Policy decision: `REQUIRE_APPROVAL` with reason
- Evidence record: "approval required for X because Y"
- Workflow state: `state.observe("APPROVAL REQUIRED: ...")`

What Phase 5 does NOT do:
- Block waiting for approval
- Implement approval UI
- Send notifications
- Track approval status

## 12. Evidence/audit model

Every policy decision is recorded in the existing `EvidenceLog`:

```python
evidence.record(
    action="policy_decision",
    detail=f"rule={d.rule} outcome={d.outcome} reason={d.reason}",
)
```

This integrates with the existing evidence system rather than
creating a competing one.

The policy engine also adds a `policy_decisions` list to `RunState`:

```python
@dataclass
class RunState:
    ...
    policy_decisions: list[dict[str, str]] = field(default_factory=list)
```

## 13. Configuration model

Policy configuration comes from three sources (in priority order):

1. **Built-in base policy** (code-level, cannot be overridden)
2. **Mode selection** (CLI flag or config file)
3. **Project overrides** (`.orchestrator/config`)

Example `.orchestrator/config`:
```
mode = security
sandbox_required = true
diff_gate_required = true
evidence_level = enhanced
```

**Validation rules**:
- Unknown keys are rejected (fail closed)
- Mandatory rules cannot be overridden
- Invalid mode is rejected
- Project config that weakens mode policy is rejected

## 14. Failure behavior

| Situation | Behavior |
|-----------|----------|
| Unknown mode | FAIL (InvalidPolicyError) |
| Invalid config | FAIL (InvalidPolicyError) |
| Policy denies workflow start | BLOCKED |
| Policy denies a step | BLOCKED |
| Policy requires unavailable tool | BLOCKED |
| Policy requires sandbox but unavailable | BLOCKED |
| Mandatory rule conflict | FAIL (should never happen — invariant violation) |
| Policy engine error | FAIL (fail closed) |

**No silent fallbacks.**  If policy cannot be reliably determined,
the system BLOCKS or FAILS.

## 15. Extensibility

New modes can be added by:
1. Adding a new `Mode` enum value
2. Defining the mode's policy rules
3. Adding the mode to `MODE_REGISTRY`

New policy rules can be added by:
1. Adding a new rule name to the rule set
2. Defining its value for each mode
3. Marking it mandatory or optional

The Workflow Engine does NOT need to change when new modes/rules are added.
The Policy Engine evaluates rules and produces decisions; the engine
enforces those decisions.

## 16. Threat model

| Threat | Mitigation |
|--------|-----------|
| Policy tampering | Base policy is code-level, not configurable |
| Unauthorized mode change | Mode is set at workflow start, cannot change mid-run |
| Privilege escalation | Policy can only make things stricter |
| Policy weakening | Mandatory rules cannot be overridden by project config |
| Configuration injection | Config is parsed with strict validation, unknown keys rejected |
| Malicious project config | Project config cannot override mandatory rules |
| Secret leakage | All policy decisions pass through redact() |
| Untrusted tool output | Policy decisions are deterministic, not based on tool output |
| Approval spoofing | Approval is record-only in Phase 5, no bypass possible |
| Audit-log manipulation | Evidence is append-only |
| Fail-open behavior | All failure paths lead to BLOCKED or FAIL |

## 17. Test strategy

### Unit tests
1. Each mode produces correct default policy
2. Base safety rules are inviolable
3. Project config can only tighten, never weaken
4. Unknown mode is rejected
5. Invalid config is rejected
6. Policy decisions are deterministic
7. Pre-flight checks work for each mode
8. Post-flight checks work for each mode
9. DENY decisions have reasons
10. Mandatory rules cannot be overridden

### Integration tests
11. SOLO workflow with policy
12. DEVELOPMENT workflow with policy
13. SECURITY workflow with policy
14. ENTERPRISE workflow with policy
15. Policy blocks workflow when tool missing
16. Policy requires sandbox but unavailable
17. Policy records all decisions in evidence log
18. Existing Phase 1-4 tests still pass

### Security tests
19. Cannot weaken mandatory rules via config
20. Cannot bypass error-log gate via policy
21. Cannot bypass sandbox restrictions via policy
22. Cannot silently downgrade from SECURITY to SOLO
23. Malformed config is rejected
24. Unknown config keys are rejected

## 18. Proposed module structure

```
orchestrator/
    policy.py         # Policy, PolicyRule, PolicyDecision, load_policy
    modes.py          # Mode enum, MODE_REGISTRY, mode definitions
```

Two new modules.  Small, focused, consistent with the project philosophy.

`policy.py` (~200 lines):
- `PolicyRule` dataclass
- `PolicyDecision` dataclass
- `Policy` class with `pre_flight()` and `post_flight()` methods
- `load_policy()` factory function
- Rule validation logic

`modes.py` (~150 lines):
- `Mode` enum (SOLO, DEVELOPMENT, SECURITY, ENTERPRISE)
- `MODE_REGISTRY` mapping mode -> default rules
- `get_mode_policy()` factory function
- Mode validation

## 19. Example policy decisions

### SOLO pre-flight
```
rule=error_log_required  outcome=ALLOW    reason="error-log check is mandatory"
rule=decision_log_required outcome=ALLOW reason="decision-log check is mandatory"
rule=diff_gate_required  outcome=ALLOW    reason="diff-gate not required in SOLO"
rule=sandbox_required    outcome=ALLOW    reason="sandbox not required in SOLO"
```

### SECURITY post-flight (diff-gate fails)
```
rule=diff_gate_required  outcome=DENY     reason="diff-gate failed in SECURITY mode"
```

### ENTERPRISE pre-flight (missing approval)
```
rule=approval_required   outcome=REQUIRE_APPROVAL reason="consequential action requires approval"
```

## 20. Example SOLO workflow

```
User: "Run bootstrap workflow in SOLO mode"

Policy Engine (pre-flight):
  - mode=SOLO: loaded
  - error_log_required: ALLOW
  - decision_log_required: ALLOW
  - diff_gate_required: not required (SOLO)
  - sandbox_required: not required (SOLO)

Workflow Engine:
  - Step 1: error-log.check -> PASS
  - Step 2: decision-log.check -> PASS

Policy Engine (post-flight):
  - All gates passed, no additional requirements

Result: COMPLETED, status=PASS
```

## 21. Example DEVELOPMENT workflow

```
User: "Run development workflow"

Policy Engine (pre-flight):
  - mode=DEVELOPMENT: loaded
  - error_log_required: ALLOW
  - decision_log_required: ALLOW
  - diff_gate_required: REQUIRED
  - sandbox_required: REQUIRED

Workflow Engine:
  - Step 1: error-log.check -> PASS
  - Step 2: decision-log.check -> PASS
  - Step 3: diff-gate.check_staged -> FAIL

Policy Engine (post-flight):
  - diff_gate_required: DENY (diff-gate failed)

Result: BLOCKED, "diff-gate rejected changes"
```

## 22. Example SECURITY workflow

```
User: "Run security audit"

Policy Engine (pre-flight):
  - mode=SECURITY: loaded
  - error_log_required: ALLOW
  - decision_log_required: ALLOW
  - diff_gate_required: REQUIRED (strict)
  - sandbox_required: MANDATORY
  - sandbox_strict: true
  - host_fallback_allowed: false
  - evidence_level: enhanced

Workflow Engine:
  - Step 1: error-log.check -> PASS
  - Step 2: decision-log.check -> PASS
  - Step 3: sandbox.health -> UNSUPPORTED (Windows)

Policy Engine (post-flight):
  - sandbox_required: DENY (sandbox unavailable, no host fallback allowed)

Result: BLOCKED, "sandbox required but unavailable on this platform"
```

## 23. Example ENTERPRISE workflow

```
User: "Run enterprise deployment check"

Policy Engine (pre-flight):
  - mode=ENTERPRISE: loaded
  - All DEVELOPMENT rules apply
  - approval_required: true
  - evidence_level: complete

Workflow Engine:
  - Step 1: error-log.check -> PASS
  - Step 2: decision-log.check -> PASS

Policy Engine (post-flight):
  - approval_required: REQUIRE_APPROVAL
  - "deployment requires human approval"

Result: BLOCKED (or observes approval requirement)
Note: In Phase 5, approval is recorded but does not block.
       Future phases will implement approval workflows.
```

## 24. Risks/tradeoffs

| Risk | Mitigation |
|------|-----------|
| Over-engineering | Keep to 2 modules, ~350 lines total |
| Performance | Policy evaluation is O(rules), negligible |
| Complexity | Deterministic rules only, no AI-based policy |
| Approval gap | Phase 5 records only, future phases implement |
| Mode creep | Four modes is sufficient for now |
| Config drift | Strict validation rejects unknown keys |

**Key tradeoff**: The approval model is record-only in Phase 5.
This means ENTERPRISE mode cannot fully enforce approval requirements
until a future phase implements the approval workflow.  This is
acceptable because the policy engine correctly IDENTIFIES the need
and RECORDS it — the enforcement mechanism is a separate concern.

## 25. Phase 5 implementation plan

### Step 1: modes.py
- Mode enum
- MODE_REGISTRY with default rules per mode
- get_mode_policy() factory

### Step 2: policy.py
- PolicyRule, PolicyDecision dataclasses
- Policy class with pre_flight() and post_flight()
- load_policy() factory
- Rule validation

### Step 3: Integration
- Add policy_decisions to RunState
- Add pre-flight check to WorkflowEngine.run()
- Add post-flight check to WorkflowEngine._invoke_step()
- Update CLI to accept --mode flag
- Update report.py to include policy decisions

### Step 4: Tests
- 24 tests per the test strategy
- All existing 188 tests must continue passing

### Step 5: Documentation
- Update README.md
- Create PHASE_5_IMPLEMENTATION_REPORT.md

**Estimated scope**: ~350 lines of new code, ~24 new tests.
