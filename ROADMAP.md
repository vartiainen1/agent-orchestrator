# ROADMAP.md — Orchestrator

## Project Goal

Build the Orchestrator as the 8th component of the existing AI development
ecosystem.

The Orchestrator coordinates:

1. agent-error-log
2. agent-decision-log
3. agent-log-ai
4. agent-memory
5. agent-blame
6. agent-diff-gate
7. agent-sandbox

The Orchestrator must preserve their philosophy:

- zero/minimal dependencies
- CLI-first
- modular
- composable
- auditable
- security-focused
- fail-closed
- agent-friendly
- locally usable
- transparent

---

# PHASE 0 — FOUNDATION

Status:

    DESIGN COMPLETE

Artifacts:

- design.md
- AGENTS.md
- ROADMAP.md
- SECURITY.md

Goals:

- define architecture
- define security model
- define agent rules
- define implementation phases
- define compatibility requirements

Exit criteria:

- architecture documented
- security principles documented
- workflow documented
- no major unresolved architectural ambiguity

---

# PHASE 1 — PROJECT SKELETON

Goals:

Create the minimal working repository.

Implement:

- package/module structure
- CLI entry point
- version information
- configuration loading
- basic logging
- exit codes
- project detection
- workspace detection

Constraints:

- standard library preferred
- no unnecessary framework
- no external service required

Example:

    orchestrator --help

    orchestrator --version

    orchestrator status

Exit criteria:

- CLI starts
- help works
- version works
- status works
- tests pass

---

# PHASE 2 — TOOL DISCOVERY

Goals:

Allow the Orchestrator to discover the seven tools.

The Orchestrator should detect:

- repository
- version
- available CLI
- capabilities
- health
- expected interface

Tools must not be assumed to exist.

Example:

    orchestrator tools

Output:

    agent-error-log     AVAILABLE
    agent-decision-log  AVAILABLE
    agent-log-ai        AVAILABLE
    agent-memory        AVAILABLE
    agent-blame         AVAILABLE
    agent-diff-gate     AVAILABLE
    agent-sandbox       AVAILABLE

Exit criteria:

- all seven tools can be detected
- unavailable tools are clearly reported
- no tool is falsely reported as available

---

# PHASE 3 — TOOL ADAPTER LAYER

Goals:

Create a clean internal adapter for each tool.

Example:

    ErrorLogAdapter
    DecisionLogAdapter
    LogAIAdapter
    MemoryAdapter
    BlameAdapter
    DiffGateAdapter
    SandboxAdapter

Adapters should:

- invoke the actual tool
- capture stdout
- capture stderr
- capture exit code
- record execution time
- normalize results
- preserve raw evidence

The adapter must not silently replace a missing tool.

Exit criteria:

- each tool can be invoked through its adapter
- raw output is preserved
- failures are represented accurately
- tests cover success and failure

---

# PHASE 4 — WORKFLOW ENGINE

Goals:

Create the core orchestration engine.

The engine must understand:

    task
      ↓
    context
      ↓
    policy
      ↓
    tool
      ↓
    result
      ↓
    decision
      ↓
    next action

The workflow engine must be deterministic where possible.

It should support explicit workflow states.

Example:

    INITIALIZE
    CHECK
    PLAN
    EXECUTE
    VALIDATE
    REVIEW
    COMMIT
    VERIFY
    COMPLETE

Failure states:

    BLOCKED
    FAILED
    DENIED
    REQUIRES_APPROVAL

Exit criteria:

- workflow can execute a simple project task
- state transitions are explicit
- failures stop unsafe execution
- workflow state is auditable

---

# PHASE 5 — POLICY ENGINE

Goals:

Separate orchestration logic from policy.

Implement policy controls for:

- allowed tools
- allowed agents
- execution environment
- filesystem access
- network access
- commit permissions
- approval requirements
- sandbox requirements

Policies must be explicit.

Modes should use the same policy engine.

Exit criteria:

- policies can deny actions
- denied actions fail closed
- policies are testable
- policies are auditable

---

# PHASE 6 — SANDBOX-FIRST EXECUTION

Goals:

Integrate agent-sandbox as the default execution boundary.

Execution flow:

    Orchestrator
        ↓
    Sandbox
        ↓
    Project
        ↓
    Tests / commands
        ↓
    Evidence
        ↓
    Orchestrator

Requirements:

- no silent host fallback
- sandbox failure must be visible
- execution evidence must be recorded
- exit code must be captured

Exit criteria:

- project code executes through sandbox
- sandbox failure blocks execution
- evidence confirms execution environment
- host fallback is disabled by default

---

# PHASE 7 — GOVERNED CONTEXT

Integrate:

- agent-error-log
- agent-decision-log
- agent-log-ai
- agent-memory
- agent-blame

Goals:

Build the context pipeline:

    errors
       ↓
    decisions
       ↓
    analysis
       ↓
    lessons
       ↓
    governed memory
       ↓
    future context

Memory trust boundaries must remain intact.

Exit criteria:

- relevant context can be gathered
- untrusted memory is not treated as trusted
- lessons can be stored
- historical context can be retrieved
- provenance is preserved

---

# PHASE 8 — DEVELOPMENT GATES

Integrate:

- agent-diff-gate
- agent-error-log commit gate

Goals:

Prevent unsafe changes from reaching commits.

Flow:

    code
      ↓
    tests
      ↓
    diff-gate
      ↓
    error-log gate
      ↓
    commit

Failures must block the workflow.

Exit criteria:

- unsafe changes are rejected
- valid changes pass
- commit gates remain active
- no --no-verify path is used

---

# PHASE 9 — MODES

Implement:

## Solo Mode

One primary agent.

Focus:

- simplicity
- normal development workflow
- full seven-tool integration

## Development Mode

Development-focused orchestration.

Focus:

- coding
- testing
- debugging
- review
- memory

## Security Mode

Security-focused orchestration.

Focus:

- stricter policies
- security analysis
- sandbox
- diff-gate
- independent review
- stronger evidence requirements

## Enterprise Mode

Maximum governance.

Focus:

- auditability
- policy
- approvals
- agent isolation
- evidence
- reproducibility
- multi-agent workflows

All modes must share the same core engine.

---

# PHASE 10 — MULTI-AGENT ENGINE

Goals:

Allow multiple AI agents to cooperate.

Agent model:

    Agent
      ├── identity
      ├── role
      ├── permissions
      ├── context
      ├── task
      ├── output
      └── evidence

Example:

    Developer Agent
          ↓
    Security Agent
          ↓
    Review Agent
          ↓
    Orchestrator
          ↓
    Gates
          ↓
    Sandbox

Agents must not automatically trust one another.

The Orchestrator remains the coordinator.

Exit criteria:

- multiple agents can operate independently
- roles are explicit
- permissions are enforced
- outputs are auditable
- one agent cannot silently override another agent's restrictions

---

# PHASE 11 — FREEBUFF / CLI INTEGRATION

Goal:

Allow the Orchestrator to work with CLI-based AI systems without requiring
a direct model API key.

The Orchestrator should support AI processes through controlled CLI interfaces.

Possible architecture:

    Orchestrator
        ↓
    subprocess / CLI
        ↓
    AI CLI
        ↓
    output
        ↓
    validation
        ↓
    workflow

Requirements:

- explicit command configuration
- timeout handling
- stdout/stderr capture
- exit code handling
- no blind command execution
- no secret leakage
- configurable agent roles

The Orchestrator must not require FreeBuff specifically to function.

FreeBuff should be one compatible agent interface.

---

# PHASE 12 — AUDIT / EVIDENCE SYSTEM

Every important orchestration action should produce evidence.

Record:

- timestamp
- action
- actor/agent
- tool
- command
- exit code
- result
- policy decision
- relevant files
- workflow state

Evidence must be append-oriented.

Do not silently rewrite historical evidence.

Exit criteria:

- complete workflow can be reconstructed
- tool execution can be verified
- agent actions can be traced
- failures can be investigated

---

# PHASE 13 — HARDENING

Security review of:

- command execution
- subprocess handling
- filesystem paths
- path traversal
- environment variables
- secrets
- agent permissions
- policy bypass
- sandbox failures
- malformed tool output
- malicious tool output
- malicious project code
- prompt injection
- agent-to-agent injection

Add negative tests.

Attempt to break the system deliberately.

Exit criteria:

- security tests pass
- fail-closed behavior verified
- no known critical bypasses remain

---

# PHASE 14 — FULL ECOSYSTEM INTEGRATION TEST

Create a dedicated integration project.

The test must demonstrate:

    error
      ↓
    error-log
      ↓
    decision-log
      ↓
    log-ai
      ↓
    memory
      ↓
    blame
      ↓
    code change
      ↓
    diff-gate
      ↓
    commit gate
      ↓
    sandbox
      ↓
    verification
      ↓
    evidence

All seven tools must participate.

The Orchestrator must demonstrate actual output-to-decision-to-next-tool
interaction.

Exit criteria:

- all seven tools execute
- gates reject unsafe work
- safe work passes
- sandbox executes the project
- evidence report is generated
- no tool repositories are modified

---

# PHASE 15 — RELEASE HARDENING

Before first stable release:

- documentation review
- dependency review
- security review
- CLI review
- compatibility review
- test suite review
- integration test
- clean installation test
- clean-machine test
- failure-mode testing

Release only when the project can reproduce its own documented behavior.

---

# LONG-TERM

Potential future features:

- dashboard
- distributed agents
- remote agents
- additional AI providers
- agent scheduling
- enterprise policy management
- visualization
- metrics
- plugin ecosystem

These must remain optional.

The core CLI and zero/minimal-dependency philosophy must remain intact.