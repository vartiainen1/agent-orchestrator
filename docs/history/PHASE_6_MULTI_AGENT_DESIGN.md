# Phase 6 — Multi-Agent Engine Design Proposal

## 1. Objective

Extend the orchestrator into a governed multi-agent orchestration system
where multiple AI agents cooperate under the authority of the existing
PolicyEngine + WorkflowEngine + Tool Adapter architecture.

Core principle: **Agents propose. The orchestrator decides. Tools execute.
Policy governs.**

Agents must never bypass mandatory safety rules, gates, sandbox
requirements, evidence collection, or tool restrictions.

## 2. Architectural position

```
USER / AI AGENT (external CLI, e.g. Freebuff)
        |
        v
ORCHESTRATOR (CLI entry point)
        |
        v
POLICY ENGINE (Phase 5 — what is permitted)
        |
        v
MULTI-AGENT ENGINE (Phase 6 — who does what, when)
        |    |
        |    +--> Agent Registry (identity, roles, permissions)
        |    +--> Task Scheduler (sequential / parallel)
        |    +--> Agent Executor (invokes AI providers)
        |    +--> Result Aggregator (collects + reconciles outputs)
        |
        v
WORKFLOW ENGINE (Phase 4 — state machine execution)
        |
        v
TOOL ADAPTERS (Phase 3 — normalized tool invocation)
        |
        v
7 EXISTING TOOLS
```

The Multi-Agent Engine sits BETWEEN the Policy Engine and the
Workflow Engine.  It decides which agent handles which task,
manages their execution, and feeds their results back to the
workflow as tool invocations.

## 3. Agent identity

Every agent has a unique, immutable identity:

```python
@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str          # unique, e.g. "agent-dev-001"
    role: AgentRole        # planner, developer, reviewer, security, etc.
    display_name: str      # human-readable name
    provider: str          # "ollama", "openai-compatible", "cli", "none"
    model: str             # model name, e.g. "qwen2.5-coder:14b"
    created_at: str        # ISO timestamp
```

Identity is assigned at agent creation and NEVER changes during a run.
Agents cannot forge or modify their own identity.

## 4. Agent roles

```python
class AgentRole(str, Enum):
    PLANNER = "planner"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SECURITY = "security"
    RESEARCHER = "researcher"
    DOCUMENTER = "documenter"
```

Each role has fixed, predefined permissions (see section 5).
Roles cannot be changed at runtime.

## 5. Agent permissions

```python
@dataclass(frozen=True)
class AgentPermissions:
    can_read: bool = True
    can_write: bool = False
    can_execute: bool = False
    can_use_sandbox: bool = False
    can_use_tools: list[str] = field(default_factory=list)  # tool names
    can_approve: bool = False
    can_promote_memory: bool = False
    max_tokens: int = 4096
    timeout_seconds: float = 60.0
```

Default permissions by role:

| Role | read | write | execute | sandbox | tools | approve | memory_promote |
|------|:----:|:-----:|:-------:|:-------:|-------|:-------:|:--------------:|
| PLANNER | Yes | No | No | No | error-log, decision-log, memory | No | No |
| DEVELOPER | Yes | Yes | Yes | Yes | all | No | No |
| REVIEWER | Yes | No | No | No | diff-gate, blame, error-log | No | No |
| TESTER | Yes | Yes | Yes | Yes | sandbox, error-log | No | No |
| SECURITY | Yes | No | No | Yes | diff-gate, blame, sandbox, memory | No | No |
| RESEARCHER | Yes | No | No | No | blame, memory, log-ai | No | No |
| DOCUMENTER | Yes | Yes | No | No | error-log, decision-log | No | No |

**Security invariant**: Agent permissions can only be RESTRICTED
by policy, never EXPANDED.  A project or mode cannot grant an
agent more permissions than its role allows.

## 6. Agent lifecycle

```
CREATED --> INITIALIZING --> READY --> ASSIGNED --> RUNNING --> COMPLETED
                                    |                          |
                                    +--> CANCELLED             +--> FAILED
                                    +--> BLOCKED
```

States:
- **CREATED**: identity assigned, not yet initialized
- **INITIALIZING**: provider connection being established
- **READY**: agent is available for task assignment
- **ASSIGNED**: task received, not yet executing
- **RUNNING**: actively processing
- **COMPLETED**: task finished successfully
- **FAILED**: task finished with error
- **BLOCKED**: policy prevented execution
- **CANCELLED**: cancelled before/during execution

Terminal states: COMPLETED, FAILED, CANCELLED.

## 7. Sequential agent execution

The simplest execution model:

```
Task queue:
  [Task A] -> [Task B] -> [Task C]

Agent 1 runs Task A
  -> result
Agent 2 runs Task B
  -> result
Agent 3 runs Task C
  -> result
```

Each agent completes before the next begins.  The orchestrator
controls the sequence.  Agents cannot start early or skip ahead.

Use case: PLANNER -> DEVELOPER -> REVIEWER pipeline.

## 8. Parallel agent execution

When tasks are independent, multiple agents can run simultaneously:

```
            +--> Agent A (review code)
Fork -------+
            +--> Agent B (run tests)
            |
            +--> Agent C (security scan)
            |
            v
        Join (aggregate results)
```

**Security constraints on parallel execution**:
- Parallel agents MUST NOT share the same working tree unless
  explicitly designed for it
- Each parallel agent runs in isolation
- The orchestrator waits for all to complete before proceeding
- If any parallel agent fails, the orchestrator decides whether
  to continue or block

**Platform limitation**: True parallelism requires threading or
multiprocessing.  Phase 6 implements sequential-first with a
parallel interface that can be extended later.  The design
supports parallel; the initial implementation is sequential.

## 9. Agent task assignment

Tasks are assigned by the orchestrator, not requested by agents.

```python
@dataclass
class AgentTask:
    task_id: str
    description: str
    agent_role: AgentRole
    allowed_tools: list[str]
    context: dict[str, str]   # input data for the agent
    timeout: float = 60.0
    max_retries: int = 0
```

The orchestrator:
1. Determines which role is needed for a task
2. Selects an available agent with that role
3. Assigns the task with context
4. Monitors execution
5. Collects the result

Agents cannot self-assign tasks or request additional privileges.

## 10. Agent-to-agent communication

Agents do NOT communicate directly.  All inter-agent data flow
goes through the orchestrator:

```
Agent A --> [result] --> Orchestrator --> [context] --> Agent B
```

This prevents:
- Agent A from injecting malicious instructions into Agent B
- Agent B from escalating privileges through Agent A
- Direct prompt injection between agents

The orchestrator mediates all data flow and applies policy
validation at each transfer point.

## 11. Shared context

The orchestrator maintains a shared context dictionary that
agents can READ but not WRITE:

```python
@dataclass
class SharedContext:
    project_dir: str
    workspace_dir: str
    run_id: str
    mode: str
    tool_results: dict[str, str]    # previous tool outputs
    decisions: list[str]            # recorded decisions
    errors: list[str]               # recorded errors
    memory: list[str]               # recalled trusted memory
```

Agents receive a COPY of the relevant context.  They cannot
modify the shared context directly.  Only the orchestrator
updates context based on agent outputs.

## 12. Agent result handling

Every agent produces a structured result:

```python
@dataclass
class AgentResult:
    agent_id: str
    task_id: str
    status: str              # COMPLETED / FAILED / BLOCKED
    output: str              # agent's textual output
    proposed_actions: list[dict]  # actions the agent recommends
    reasoning: str           # agent's explanation
    confidence: float        # 0.0 - 1.0 (agent's self-assessed confidence)
    duration: float
    tokens_used: int
    error: str = ""
```

The orchestrator evaluates `proposed_actions` against policy
before executing any of them.  Agents propose; the orchestrator
disposes.

## 13. Conflicting agent decisions

When multiple agents produce conflicting recommendations:

1. The orchestrator logs all recommendations
2. Policy determines which role has authority for the decision
3. If no clear authority, the orchestrator defaults to SAFE FAILURE
4. Conflicts are recorded as evidence

Example:
- DEVELOPER says "fix with approach A"
- SECURITY says "approach A is unsafe, use approach B"
- Orchestrator: SECURITY role has higher authority for security
  decisions -> approach B is selected

Authority hierarchy (determined by role, not by agent identity):
1. SECURITY (highest for safety decisions)
2. REVIEWER (for code quality decisions)
3. DEVELOPER (for implementation decisions)
4. PLANNER (for task sequencing decisions)
5. Other roles

## 14. Agent failure handling

```
Agent fails
    |
    v
Orchestrator records failure
    |
    v
Check: is task critical?
    |
    +--> Yes: BLOCK workflow, report failure
    |
    +--> No: retry if max_retries > 0
              |
              +--> retries remaining: reassign to same/different agent
              |
              +--> no retries: mark task as FAILED, continue workflow
```

Failures are NEVER silently swallowed.  Every failure is:
1. Recorded in evidence
2. Recorded in error-log (if applicable)
3. Reported to the user
4. Available in the run report

## 15. Agent timeout handling

Every agent task has a timeout (from AgentPermissions or task config).

```
Agent running
    |
    v
Timeout exceeded
    |
    v
Orchestrator sends cancellation signal
    |
    v
Wait grace period (5s)
    |
    v
Agent still running?
    |
    +--> No: record timeout, mark FAILED
    |
    +--> Yes: force termination, mark FAILED
```

Timeouts are enforced by the orchestrator, not by the agent.

## 16. Agent cancellation

The orchestrator can cancel an agent at any time:

```python
agent.cancel(reason="policy violation")
```

Cancellation:
- Sets agent state to CANCELLED
- Records reason in evidence
- Prevents the agent from producing further output
- Does NOT affect other agents

Agents cannot cancel other agents or themselves without
orchestrator authorization.

## 17. Agent isolation

Each agent operates in isolation:

- Separate context copy
- Separate output buffer
- Separate timeout
- No shared mutable state
- No direct inter-agent communication

When parallel execution is implemented, isolation extends to:
- Separate working directories (where practical)
- Separate process/thread
- No file system sharing without orchestrator mediation

## 18. Tool permissions per agent

Each agent can only invoke tools explicitly listed in its
permissions.  The orchestrator enforces this:

```python
def _check_tool_permission(agent: Agent, tool_name: str) -> bool:
    return tool_name in agent.permissions.can_use_tools
```

If an agent attempts to use a tool not in its permissions:
- The attempt is BLOCKED
- Recorded as a policy violation
- The agent receives an error response
- The workflow may continue or block depending on criticality

## 19. Policy enforcement over agents

The PolicyEngine governs agents through:

1. **Pre-flight**: which agent roles are allowed in this mode
2. **Per-task**: whether the assigned tool is permitted for this role
3. **Post-flight**: whether the agent's output satisfies policy

Policy can:
- Require specific roles for specific tasks
- Restrict which tools each role can use
- Require approval for agent-proposed actions
- Block agents entirely in certain modes

Policy CANNOT:
- Grant agents permissions beyond their role
- Allow agents to bypass safety gates
- Override sandbox requirements
- Promote untrusted memory

## 20. Evidence collection for every agent action

Every agent action produces an evidence entry:

```python
evidence.record(
    action="agent_action",
    tool=f"agent:{agent_id}",
    operation=task_id,
    detail=f"role={role} status={status} tokens={tokens}",
)
```

The evidence trail answers:
- Which agent performed which task
- What was the agent's input/output
- What actions did the agent propose
- Were those actions approved/rejected by policy
- How long did the agent take
- How many tokens were used

## 21. ENTERPRISE approval requirements

In ENTERPRISE mode:
- Agent-proposed actions that modify code require approval
- Agent-proposed actions that execute code require approval
- Agent-proposed actions that change security policy require approval
- Approval is RECORD-ONLY in Phase 6 (same as Phase 5)

The orchestrator records: "Agent X proposed action Y. Approval required."

## 22. SECURITY mode restrictions

In SECURITY mode:
- All DEVELOPMENT restrictions apply
- Additional: security agent has highest authority
- Additional: all agent outputs are treated as untrusted
- Additional: agent-proposed code changes require diff-gate
- Additional: enhanced evidence for every agent action
- Additional: no cloud AI providers

## 23. DEVELOPMENT mode behavior

In DEVELOPMENT mode:
- Full agent roster available
- Standard evidence collection
- Agent-proposed changes go through diff-gate
- Sandbox required for execution
- Standard approval model (no approval required)

## 24. SOLO mode behavior

In SOLO mode:
- Minimal agent roster (typically just DEVELOPER role)
- Basic evidence collection
- Agent proposals are executed directly (no approval)
- Diff-gate optional
- Sandbox optional

## 25. Local AI support

The AI provider layer is SEPARATE from the orchestration layer:

```
Multi-Agent Engine
        |
        v
AI Provider Adapter
        |
        +--> Ollama (local)
        +--> OpenAI-compatible (local or remote)
        +--> CLI-based (e.g. Freebuff)
        +--> None (deterministic-only agents)
```

The orchestrator does NOT require any AI provider to function.
When no AI provider is available:
- Deterministic-only agents (planner, reviewer) still work
- AI-dependent agents (developer with LLM) are marked BLOCKED
- The workflow continues with available agents

## 26. Ollama/local-model support

```python
class OllamaProvider:
    """Adapter for Ollama local models."""
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url

    def complete(self, prompt: str, model: str, **kwargs) -> str:
        """Send prompt, return completion."""
        # Uses urllib (stdlib) — no requests dependency
        ...
```

Key principles:
- Uses `urllib.request` (stdlib) — no `requests` dependency
- Default endpoint: `http://localhost:11434`
- No API key required
- Timeout enforced
- Response validated before use

## 27. Operation without API keys

The orchestrator MUST work without any API key:

- Ollama runs locally, no key needed
- CLI-based agents (Freebuff) handle their own auth
- Deterministic agents (reviewer, tester) need no AI at all
- The policy engine can restrict cloud providers

If an agent requires a cloud API and no key is configured:
- The agent is marked BLOCKED
- The workflow continues with available agents
- A warning is recorded

## 28. Multiple AI providers/models

Different agents can use different providers:

```python
Agent(agent_id="dev-001", provider="ollama", model="qwen2.5-coder:14b")
Agent(agent_id="sec-001", provider="ollama", model="codellama:13b")
Agent(agent_id="plan-001", provider="none", model="")  # deterministic
```

The provider is an attribute of the agent, not a global setting.

## 29. Parallel model execution

When multiple AI agents run in parallel, each invokes its own
provider independently.  The orchestrator manages:

- Separate HTTP connections (for Ollama)
- Separate timeouts
- Separate result collection
- No shared state between providers

Phase 6 implements sequential-first.  Parallel is designed but
initially executed sequentially for safety.

## 30. Security boundaries between agents

```
Agent A (isolated)
    |
    |--> output buffer (owned by orchestrator)
    |
Orchestrator (mediates)
    |
    |--> validated context
    |
Agent B (isolated)
```

Boundaries:
- Agents cannot see each other's prompts
- Agents cannot see each other's raw outputs
- Agents cannot modify each other's context
- Agents cannot access each other's tools
- All cross-agent data passes through orchestrator validation

## 31. Secret handling

- Agents NEVER receive environment secrets
- Agents NEVER receive API keys
- Agent prompts are sanitized (no secret injection)
- Agent outputs are scanned for secret patterns before recording
- Agent context contains only project-relevant, non-sensitive data

## 32. Prompt/input validation

Before sending input to an AI provider:

1. Validate prompt length (within model limits)
2. Sanitize special characters
3. Remove any detected secret patterns
4. Verify prompt does not contain override instructions
5. Log the prompt (redacted) in evidence

Agent inputs are treated as UNTRUSTED.

## 33. Output validation

After receiving output from an AI provider:

1. Validate response is non-empty
2. Validate response length is reasonable
3. Scan for secret patterns
4. Scan for prompt injection patterns
5. Parse structured output (if expected format)
6. Log the output (redacted) in evidence

Agent outputs are treated as UNTRUSTED until validated.

## 34. Prevention of policy bypass

Agents cannot bypass policy through:

1. **Prompt injection**: inputs are sanitized, not executed as code
2. **Output manipulation**: outputs are validated before use
3. **Privilege escalation**: permissions are role-based, immutable
4. **Tool bypass**: tool access is checked per-invocation
5. **Gate bypass**: gates are enforced by WorkflowEngine, not agents
6. **Approval bypass**: approval requirements are policy-driven

## 35. Prevention of tool bypass

Agents invoke tools ONLY through the adapter layer:

```
Agent --> proposes action --> Orchestrator --> validates --> Adapter --> Tool
```

Agents NEVER:
- Execute shell commands directly
- Import tool modules directly
- Access tool files directly
- Bypass the adapter interface

## 36. Deterministic orchestration where possible

The orchestration logic itself is deterministic:

- Task assignment is rule-based (role -> task matching)
- Policy evaluation is deterministic
- Result aggregation follows fixed rules
- Evidence recording is append-only

Only the AI provider responses are non-deterministic.
The orchestrator handles non-determinism by:
- Validating all outputs
- Applying policy to all decisions
- Recording all evidence
- Defaulting to safe failure on uncertainty

## 37-38. Zero dependencies / standard-library-only

All Phase 6 code uses only Python stdlib:
- `dataclasses`, `enum` for data models
- `subprocess` for provider invocation (if needed)
- `urllib.request` for HTTP (Ollama API)
- `json` for serialization
- `threading` for parallel execution (stdlib)
- `uuid` for agent/task IDs
- `datetime` for timestamps

No external packages.

## 39. Testing strategy

### Unit tests
1. Agent identity creation and immutability
2. Role -> permission mapping for all 7 roles
3. Permission enforcement (allowed/blocked tool access)
4. Agent lifecycle state transitions
5. Task assignment and queue management
6. Sequential execution flow
7. Parallel execution flow (designed, executed sequentially initially)
8. Result aggregation
9. Conflict resolution (authority hierarchy)
10. Timeout enforcement
11. Cancellation
12. Failure handling (critical vs non-critical)
13. Provider adapter (Ollama, none)
14. Prompt sanitization
15. Output validation
16. Secret detection in agent I/O
17. Policy enforcement over agents
18. Mode-specific behavior (SOLO/DEV/SEC/ENT)
19. Evidence recording for all agent actions
20. No shell=True

### Integration tests
21. Planner -> Developer pipeline
22. Developer -> Reviewer pipeline
23. Parallel review + test
24. Agent failure -> retry -> success
25. Agent blocked by policy
26. Full workflow with multi-agent orchestration

### Security tests
27. Agent cannot access unauthorized tools
28. Agent cannot modify shared context
29. Agent cannot bypass diff-gate
30. Agent cannot bypass error-log gate
31. Agent cannot promote memory
32. Malformed agent output is rejected
33. Prompt injection in agent output is detected
34. Secret leakage prevention
35. Agent isolation verified

### Regression
36. All 238 Phase 1-5 tests continue passing

## 40. Failure-closed behavior

| Situation | Behavior |
|-----------|----------|
| Unknown agent role | BLOCKED |
| Invalid permissions | BLOCKED |
| Provider unavailable | Agent BLOCKED, workflow continues if possible |
| Agent timeout | Agent FAILED, retry or block |
| Malformed output | Agent FAILED, recorded |
| Policy violation | Agent BLOCKED, recorded |
| Parallel failure | Depends on criticality setting |
| Context corruption | BLOCKED, fail closed |
| Unknown state | BLOCKED |

## 41. Auditability

Every multi-agent run produces:

1. Agent registry snapshot (who was available)
2. Task assignment log (who got what)
3. Per-agent evidence (input, output, actions, duration)
4. Policy decisions (what was allowed/blocked)
5. Conflict resolutions (what was decided and why)
6. Final report (complete run summary)

The report answers: What happened? Who did it? What was decided?
What was blocked? Why?

## 42. Markdown/JSON reporting

Reports extend the existing report.py format:

```markdown
MULTI-AGENT REPORT

Agents:
  [dev-001] DEVELOPER  ollama/qwen2.5-coder:14b  COMPLETED  12.3s
  [sec-001] SECURITY   ollama/codellama:13b        COMPLETED  8.7s
  [rev-001] REVIEWER   none/deterministic          COMPLETED  0.1s

Tasks:
  [task-001] "Fix SQL injection"     -> dev-001  COMPLETED
  [task-002] "Review security"       -> sec-001  COMPLETED
  [task-003] "Code review"           -> rev-001  COMPLETED

Conflicts:
  (none)

Policy decisions:
  [ALLOW] error_log_required: tool available
  [DENY]  diff_gate_required: agent proposed change not gated

Summary:
  3 agents, 3 tasks, 3 completed, 0 failed, 0 blocked
```

## 43. Compatibility with all 7 tools

Multi-agent execution uses the SAME adapters as single-agent:

- error-log: agents can propose error logging
- decision-log: agents can propose decision recording
- log-ai: agents can invoke lesson extraction
- memory: agents can query memory (read-only unless promoted)
- blame: agents can invoke git archaeology
- diff-gate: agents' proposed changes go through diff-gate
- sandbox: agents' proposed code executes in sandbox

The tools do not change.  The orchestrator routes agent proposals
through the existing adapter layer.

## 44. Backwards compatibility with Phases 1-5

Phase 6 is ADDITIVE:
- New module: `orchestrator/agents.py`
- New module: `orchestrator/providers.py`
- New module: `orchestrator/scheduler.py`
- Modified: `orchestrator/engine.py` (optional agent integration)
- Modified: `orchestrator/policy.py` (agent role rules)
- Modified: `orchestrator/report.py` (agent section)

Existing single-agent workflows continue to work unchanged.
Multi-agent is OPT-IN — the engine works with or without agents.

## 45. Proposed file structure

```
orchestrator/
    agents.py        # AgentIdentity, AgentRole, AgentPermissions, Agent, AgentResult
    providers.py     # AI provider adapters (OllamaProvider, NoneProvider)
    scheduler.py     # Task assignment, sequential/parallel execution
    engine.py        # (modified) optional agent integration
    policy.py        # (modified) agent role rules
    report.py        # (modified) agent section in reports

tests/
    test_agents.py   # Agent model tests
    test_providers.py # Provider adapter tests
    test_scheduler.py # Scheduler tests
```

## 46. Proposed classes/interfaces

```python
# agents.py
class AgentRole(str, Enum): ...
class AgentState(str, Enum): ...
@dataclass(frozen=True) class AgentIdentity: ...
@dataclass(frozen=True) class AgentPermissions: ...
@dataclass class Agent: ...
@dataclass class AgentTask: ...
@dataclass class AgentResult: ...

# providers.py
class ProviderStatus(str, Enum): ...
class AIProvider(Protocol): ...
class OllamaProvider: ...
class NoneProvider: ...

# scheduler.py
class SchedulerMode(str, Enum): ...  # SEQUENTIAL, PARALLEL
class TaskScheduler: ...
    def assign(task, agent) -> None
    def execute_sequential(tasks, agents) -> list[AgentResult]
    def execute_parallel(tasks, agents) -> list[AgentResult]
```

## 47. Proposed tests (36 tests)

| # | Test | Category |
|---|------|----------|
| 1 | Agent identity creation | Unit |
| 2 | Agent identity immutability | Unit |
| 3 | All 7 roles defined | Unit |
| 4 | Role -> permissions mapping | Unit |
| 5 | Permission enforcement allowed | Unit |
| 6 | Permission enforcement blocked | Unit |
| 7 | Agent lifecycle transitions | Unit |
| 8 | Invalid lifecycle transition | Unit |
| 9 | Task assignment | Unit |
| 10 | Sequential execution | Unit |
| 11 | Parallel execution (sequential fallback) | Unit |
| 12 | Result aggregation | Unit |
| 13 | Conflict resolution | Unit |
| 14 | Timeout enforcement | Unit |
| 15 | Cancellation | Unit |
| 16 | Critical failure blocks workflow | Unit |
| 17 | Non-critical failure continues | Unit |
| 18 | NoneProvider works without AI | Unit |
| 19 | OllamaProvider uses urllib | Unit |
| 20 | Prompt sanitization | Unit |
| 21 | Output validation | Unit |
| 22 | Secret detection in I/O | Unit |
| 23 | Policy enforcement over agents | Unit |
| 24 | SOLO mode agent behavior | Unit |
| 25 | DEVELOPMENT mode agent behavior | Unit |
| 26 | SECURITY mode restrictions | Unit |
| 27 | ENTERPRISE approval requirements | Unit |
| 28 | Evidence recording | Unit |
| 29 | No shell=True | Unit |
| 30 | Planner -> Developer pipeline | Integration |
| 31 | Developer -> Reviewer pipeline | Integration |
| 32 | Agent failure -> retry | Integration |
| 33 | Agent blocked by policy | Integration |
| 34 | Agent cannot access unauthorized tools | Security |
| 35 | Agent cannot bypass diff-gate | Security |
| 36 | All Phase 1-5 tests pass | Regression |

## 48. Migration/compatibility

- No migration needed — Phase 6 is additive
- Existing workflows work without agents
- Agent integration is opt-in via CLI flag or programmatic API
- No changes to existing tool repositories
- No changes to existing adapter interfaces

## 49. Implementation phases for Phase 6

### Step 1: agents.py
- AgentIdentity, AgentRole, AgentPermissions, AgentState
- Agent class with lifecycle management
- AgentTask, AgentResult dataclasses

### Step 2: providers.py
- AIProvider protocol
- OllamaProvider (urllib-based)
- NoneProvider (deterministic fallback)

### Step 3: scheduler.py
- TaskScheduler with sequential execution
- Task assignment logic
- Result aggregation
- Conflict resolution

### Step 4: Integration
- Modify engine.py for optional agent support
- Modify policy.py for agent role rules
- Modify report.py for agent section

### Step 5: Tests
- 36 tests per test strategy
- All 238 existing tests must pass

## 50. Risks

| Risk | Mitigation |
|------|-----------|
| Over-engineering | Sequential-first, parallel designed but not fully implemented |
| Provider reliability | NoneProvider fallback, timeout enforcement |
| Agent non-determinism | All outputs validated, policy enforced |
| Security complexity | Agents are untrusted proposers, orchestrator mediates |
| Performance | Sequential execution is simple and predictable |
| Test complexity | Mock providers for unit tests, real providers for integration |

## 51. Unresolved design questions

1. **Agent memory**: Should agents have per-agent scratch memory,
   or only access the shared governed memory?  Recommendation:
   agents get a read-only view of shared memory plus a temporary
   scratch space that is discarded after the task.

2. **Streaming responses**: Should the orchestrator support streaming
   AI responses, or only complete responses?  Recommendation:
   complete responses only in Phase 6.  Streaming is a future
   optimization.

3. **Agent learning**: Should agents learn from previous task results
   within a run?  Recommendation: no — agents are stateless between
   tasks.  The orchestrator manages state.

4. **Dynamic role assignment**: Can the orchestrator change an agent's
   role mid-run?  Recommendation: no — roles are immutable per
   identity.  Create a new agent with a different role instead.
