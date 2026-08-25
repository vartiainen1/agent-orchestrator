# agent-orchestrator — Design Document

Version: 0.1.0
Status: DESIGN
Author: Vartiainen
Language: Python
Runtime dependencies: ZERO
Network requirement: NONE for core operation
AI provider requirement: NONE for core operation

---

# 1. Purpose

agent-orchestrator is the coordination layer for the existing Vartiainen AI-agent tool ecosystem.

The purpose is NOT to replace the existing tools.

The purpose is to make the existing tools operate as one coherent, repeatable, enforceable workflow around an AI coding agent.

The orchestrator should answer:

- What should the agent do next?
- Which tool should be used?
- In what order?
- What must happen before the next action?
- What evidence was produced?
- Did a gate pass or fail?
- Should another AI/agent be consulted?
- When should execution happen inside the sandbox?
- What should be remembered?
- What should be blocked?
- What should require human approval?

The orchestrator is therefore the CONTROL PLANE for the ecosystem.

The existing seven repositories remain the specialized tools.

---

# 2. Existing Ecosystem

The orchestrator MUST integrate with the existing seven repositories rather than duplicate their functionality.

1. agent-error-log
   - Error tracking
   - CHECK BEFORE CODING
   - LOG BEFORE FIXING
   - Commit enforcement
   - Error history

2. agent-decision-log
   - Decision tracking
   - Fork/decision discipline
   - Rationale
   - Persistent project decisions

3. agent-log-ai
   - Deterministic log analysis
   - LLM-assisted lesson extraction
   - Local-first AI
   - Dry-run before live model calls

4. agent-memory
   - Persistent project knowledge
   - Provenance
   - Trust levels
   - Secret protection
   - Human-controlled promotion

5. agent-blame
   - Deterministic Git archaeology
   - Code origin
   - Historical reasoning
   - Removal risk

6. agent-diff-gate
   - Diff analysis
   - Security checks
   - AI-generated-code quality checks
   - Pre-commit enforcement

7. agent-sandbox
   - Isolated code execution
   - Security boundary
   - Linux enforcement
   - Fail-closed behavior
   - Auditing

The orchestrator must preserve the responsibility boundaries of these tools.

---

# 3. Core Philosophy

agent-orchestrator follows these principles:

## 3.1 Zero dependencies

The orchestrator itself should use Python's standard library wherever practical.

No mandatory third-party Python packages.

No mandatory cloud service.

No mandatory database.

No mandatory API key.

No mandatory hosted AI provider.

The core orchestrator must remain usable offline.

Optional integrations may exist, but they must not become core dependencies.

---

# 4. Small Tool Philosophy

The orchestrator should NOT become a monolithic application.

The existing repositories are intentionally focused tools.

agent-orchestrator should follow the same philosophy.

Each component should have one clear responsibility.

Example:

orchestrator/
    orchestrator.py
    workflow.py
    registry.py
    executor.py
    evidence.py
    policy.py
    modes.py
    agents.py
    cli.py

The exact structure may change during implementation, but responsibilities must remain separated.

---

# 5. The Orchestrator Is Not Another AI

The orchestrator should not require an LLM to make basic workflow decisions.

The orchestrator is primarily deterministic.

It should be capable of:

- inspecting project state
- loading workflow rules
- checking tool availability
- selecting required workflow stages
- executing tools
- interpreting exit codes
- recording evidence
- enforcing gates
- stopping unsafe workflows
- invoking AI agents when appropriate

AI should be used for reasoning where deterministic rules are insufficient.

The architecture should therefore be:

    USER
      |
      v
    ORCHESTRATOR
      |
      +--> deterministic workflow
      |
      +--> existing tools
      |
      +--> AI agent(s)
      |
      +--> sandbox
      |
      v
    EVIDENCE / RESULT

---

# 6. No Replacement of Existing Tools

The orchestrator must NEVER silently reimplement:

- error logging
- decision logging
- memory governance
- Git blame analysis
- diff security analysis
- sandbox isolation
- LLM lesson extraction

Instead:

    Orchestrator
         |
         +--> agent-error-log
         +--> agent-decision-log
         +--> agent-log-ai
         +--> agent-memory
         +--> agent-blame
         +--> agent-diff-gate
         +--> agent-sandbox

Each tool remains independently usable.

This means a user can use any repository without the orchestrator.

The orchestrator simply provides the higher-level coordination layer.

---

# 7. Workspace Model

The normal working environment is:

    toolkit test/

The seven tools may be located beside the orchestrator.

Example:

    toolkit test/
    |
    +-- agent-error-log/
    +-- agent-decision-log/
    +-- agent-log-ai/
    +-- agent-memory/
    +-- agent-blame/
    +-- agent-diff-gate/
    +-- agent-sandbox/
    |
    +-- agent-orchestrator/
    |
    +-- projects/
        |
        +-- project-a/
        +-- project-b/

The orchestrator must never modify the seven tool repositories unless explicitly instructed.

Projects are separate workspaces.

---

# 8. Workflow File

The orchestrator must support a project-level:

    workflow.md

This file defines the operating rules for the AI agent.

The orchestrator reads it at startup.

The workflow file is not merely documentation.

It is an operational contract.

The orchestrator should expose its contents and verify that required workflow stages are available before allowing execution.

---

# 9. Standard Workflow

The default workflow should be approximately:

    SESSION START
         |
         v
    bootstrap
         |
         v
    inspect errors
         |
         v
    inspect decisions
         |
         v
    recall trusted memory
         |
         v
    understand task
         |
         v
    investigate history if needed
         |
         v
    PLAN
         |
         v
    CODE
         |
         v
    TEST
         |
         v
    LOG ERRORS
         |
         v
    RECORD DECISIONS
         |
         v
    ANALYZE LESSONS
         |
         v
    STORE KNOWLEDGE
         |
         v
    DIFF GATE
         |
         v
    SANDBOX
         |
         v
    VERIFY
         |
         v
    COMMIT
         |
         v
    FINAL AUDIT

Not every task requires every stage.

The orchestrator decides which stages are required based on task type and mode.

---

# 10. Default Sandbox Rule

agent-sandbox is the default execution environment.

The orchestrator must prefer:

    agent-sandbox

over native execution.

This applies especially to:

- tests
- generated programs
- build commands
- scripts
- untrusted code
- AI-generated code
- dependency installation
- security testing

If the sandbox cannot safely execute the workload, the orchestrator should fail closed where appropriate.

It must NOT silently fall back to unrestricted host execution.

A user may explicitly request native execution where the workflow permits it.

Such an exception should be visible and recorded.

---

# 11. Four Operating Modes

The orchestrator must support four primary modes.

## 11.1 SOLO MODE

Purpose:

Personal development and small projects.

Characteristics:

- One primary AI agent
- Standard seven-tool workflow
- Sandbox by default
- Normal error/decision/memory workflow
- Human remains final authority
- Minimal orchestration overhead

Flow:

    User
      |
      v
    Primary AI
      |
      v
    Orchestrator
      |
      +--> 7 tools
      |
      v
    Result

This is the simplest mode.

---

# 12. DEVELOPMENT MODE

Purpose:

Serious software development.

Characteristics:

- More aggressive testing
- More frequent diff-gate checks
- More use of agent-blame
- Stronger decision logging
- Sandbox-first execution
- Automatic regression testing
- Lesson extraction after meaningful failures
- Multiple AI agents may be used

Example:

    Planner Agent
         |
         v
    Developer Agent
         |
         v
    Test Agent
         |
         v
    Security Agent
         |
         v
    Diff Gate
         |
         v
    Sandbox
         |
         v
    Verification

Agents must not be allowed to bypass the gates.

---

# 13. SECURITY MODE

Purpose:

Security-sensitive development and auditing.

Security mode should be the strictest mode.

Characteristics:

- Sandbox mandatory
- Fail-closed behavior
- Diff-gate mandatory
- No automatic host execution
- Stronger evidence requirements
- More extensive testing
- Agent-blame encouraged
- Memory trust restrictions
- Human approval for consequential actions
- No automatic promotion of memory
- No secret storage
- No unverified security conclusions

Security mode must assume that AI-generated code can be incorrect or unsafe.

The AI is therefore treated as an untrusted proposer.

The tools provide verification and enforcement.

---

# 14. ENTERPRISE MODE

Purpose:

Organizations, teams and high-assurance environments.

Enterprise mode should build upon Security Mode rather than create an unrelated workflow.

Characteristics:

- Multiple agents
- Explicit roles
- Strong audit trail
- Per-agent identity
- Per-run identifiers
- Evidence records
- Human approval points
- Policy enforcement
- Reproducibility
- Immutable/append-only records where practical
- Workspace/project separation
- Configurable organizational policies
- Model/provider restrictions
- Security-focused sandbox policy
- Full workflow reports

Enterprise mode should make it possible to answer:

    What happened?

    Which agent did it?

    Which model was used?

    What tools were executed?

    What did each tool return?

    Which decisions were made?

    Which gates rejected changes?

    Which code was executed?

    Where was it executed?

    What was eventually committed?

    Which human approved the consequential action?

The orchestrator should produce an auditable run report.

---

# 15. Multi-Agent Architecture

The orchestrator should support multiple AI agents.

However, "multiple agents" must NOT simply mean running several models simultaneously and combining their text.

Agents should have explicit roles.

Example:

    ORCHESTRATOR
          |
    +-----+------+-------+-------+
    |            |       |       |
 Planner     Developer  Security  Reviewer
    |            |       |       |
    +------------+-------+-------+
                 |
            Verification
                 |
              Sandbox

Possible roles:

- planner
- developer
- reviewer
- tester
- security
- researcher
- architect
- debugger
- documentation

The orchestrator controls when each role may act.

---

# 16. Agent Independence

Agents must not be trusted simply because another agent produced an answer.

Example:

    Developer Agent
          |
          v
    proposed change
          |
          v
    Diff Gate
          |
          v
    Security Agent
          |
          v
    Sandbox
          |
          v
    Verification

The security agent cannot approve its own change merely because it wrote it.

The developer cannot bypass the diff gate.

The reviewer cannot bypass the sandbox.

The orchestrator must preserve separation of duties.

---

# 17. Multiple AI Providers

The architecture should support different AI backends.

Examples:

- Ollama
- OpenAI-compatible local servers
- vLLM
- other local providers
- future providers

But no provider should be mandatory.

agent-log-ai already establishes the local-first principle.

The orchestrator should follow the same philosophy.

A provider should be an adapter.

Example:

    AI Provider
        |
        +-- Ollama
        +-- OpenAI-compatible
        +-- Local model
        +-- Future provider

The core orchestrator must not depend on one provider.

---

# 18. Freebuff CLI Compatibility

The orchestrator should NOT require the orchestrator itself to become the AI model.

It should be possible to use an external AI CLI as the actual agent.

Conceptually:

    Freebuff CLI
          |
          v
    AI agent
          |
          v
    agent-orchestrator
          |
          +--> 7 tools

The orchestrator therefore needs a clean CLI/process interface.

The AI can execute the orchestrator using terminal commands.

No API key should be required merely to use the orchestrator.

If Freebuff can execute terminal commands, read files and interact with the project, it can participate in this architecture.

---

# 19. Tool Registry

The orchestrator should discover the seven tools rather than hardcode assumptions everywhere.

Example configuration:

    tools/
        agent-error-log
        agent-decision-log
        agent-log-ai
        agent-memory
        agent-blame
        agent-diff-gate
        agent-sandbox

The registry records:

- tool name
- path
- version
- executable/interface
- capabilities
- required platform
- security properties
- expected exit codes

Example conceptual record:

    agent-sandbox
        capability: execute
        security: isolated
        default: true
        fail_closed: true

---

# 20. Tool Discovery

At startup:

1. Locate the seven repositories.
2. Verify their presence.
3. Verify expected interfaces.
4. Read relevant documentation.
5. Record versions/commits where possible.
6. Refuse or warn if a required tool is missing.

The orchestrator must never pretend a tool ran when it did not.

---

# 21. Evidence Model

Every orchestration run should produce evidence.

A run should have an ID.

Example:

    RUN-2026-08-25-0001

Every action should record:

- timestamp
- action
- tool
- arguments
- exit code
- stdout/stderr summary
- result
- next action
- reason
- security state

The evidence should be human-readable.

Prefer plain files over a database in the first version.

---

# 22. Output -> Decision -> Next Action

This is one of the most important principles of the project.

The orchestrator must demonstrate:

    TOOL OUTPUT
        |
        v
    INTERPRETATION
        |
        v
    DECISION
        |
        v
    NEXT ACTION
        |
        v
    TOOL EXECUTION

Example:

    diff-gate
        |
        v
    R2 HIGH
        |
        v
    decision:
    unsafe change rejected
        |
        v
    developer must correct change
        |
        v
    diff-gate again

The orchestrator should not simply execute a fixed shell script.

It is a workflow engine.

---

# 23. Gates

Gates are hard boundaries.

A failed gate must prevent the workflow from continuing into an unsafe stage.

Examples:

    error not logged
        -> BLOCK FIX

    diff-gate fails
        -> BLOCK COMMIT

    sandbox unavailable
        -> BLOCK SANDBOX-REQUIRED EXECUTION

    memory untrusted
        -> BLOCK TRUSTED-CONTEXT USE

    required approval missing
        -> BLOCK CONSEQUENTIAL ACTION

The orchestrator must not reinterpret a failed gate as success.

---

# 24. No Gate Bypass

The orchestrator must explicitly prevent:

- git commit --no-verify
- disabling diff-gate
- disabling sandbox security
- silently switching to native execution
- self-promoting memory
- inventing tool results
- claiming tests passed when they did not
- skipping required workflow stages

If a tool blocks an action, the orchestrator records the block and determines the correct next step.

---

# 25. Human Authority

AI agents are proposers.

They are not the final authority.

Human-controlled actions should include:

- memory promotion
- policy changes
- security exceptions
- consequential deployment
- trust changes
- changing workflow requirements

The orchestrator should make these approval points explicit.

---

# 26. Memory Integration

agent-memory remains the authority for persistent agent knowledge.

The orchestrator should:

1. initialize memory
2. import relevant knowledge
3. recall trusted knowledge
4. provide trusted context to agents
5. import new lessons
6. never self-promote memory

The orchestrator must not create a second competing memory system.

---

# 27. Error Integration

agent-error-log remains the authority for errors.

The orchestrator should enforce:

    CHECK BEFORE CODING

and:

    LOG BEFORE FIXING

If an agent discovers an error:

    discover
       |
       v
    log error
       |
       v
    investigate
       |
       v
    fix
       |
       v
    verify
       |
       v
    mark fixed

---

# 28. Decision Integration

agent-decision-log remains the authority for important decisions.

The orchestrator should identify meaningful forks such as:

- architecture
- security design
- dependency selection
- data model
- major implementation strategy
- changing an established decision

The agent records the decision.

The orchestrator uses the resulting state to avoid unnecessary repeated exploration.

---

# 29. Log-AI Integration

agent-log-ai remains the LLM lesson extraction layer.

The orchestrator should prefer:

    deterministic analysis
          |
          v
    dry-run
          |
          v
    LLM
          |
          v
    lesson
          |
          v
    agent-memory

The orchestrator should not call an LLM unnecessarily.

---

# 30. Agent-Blame Integration

agent-blame should be used when historical context is relevant.

Examples:

- Why does this code exist?
- Who/what introduced it?
- Was this behavior intentional?
- What would removing it affect?
- Has this area previously caused problems?

Because agent-blame is deterministic, it should be preferred over asking an LLM to guess historical context.

---

# 31. Diff-Gate Integration

No normal AI-generated change should reach commit without diff-gate.

Standard flow:

    modify
      |
      v
    test
      |
      v
    diff-gate
      |
      +--> FAIL -> fix
      |
      +--> PASS
              |
              v
            commit gate

The orchestrator should surface the exact findings to the responsible agent.

---

# 32. Sandbox Integration

Sandbox is the default execution boundary.

The orchestrator should provide a standard execution abstraction:

    orchestrator run <command>

Internally:

    orchestrator
        |
        v
    agent-sandbox
        |
        v
    isolated workload

The agent should not need to manually construct Docker commands.

The orchestrator delegates sandbox execution to agent-sandbox.

---

# 33. Project State

The orchestrator should maintain minimal state.

Possible files:

    .orchestrator/
        run.json
        state.json
        evidence/
        reports/

Do NOT introduce a database in the initial version.

Plain files are:

- inspectable
- portable
- Git-friendly
- easy to debug
- zero dependency
- easy to back up

---

# 34. Run State

A run should have explicit states.

Example:

    CREATED
    BOOTSTRAPPING
    PLANNING
    EXECUTING
    BLOCKED
    VERIFYING
    COMPLETED
    FAILED
    CANCELLED

State transitions should be deterministic.

Invalid transitions should be rejected.

---

# 35. Failure Philosophy

Failures are information.

A failed tool should not automatically mean the whole system is broken.

The orchestrator should distinguish:

    PASS
    FAIL
    BLOCKED
    ERROR
    SKIPPED
    NOT_APPLICABLE

Example:

    diff-gate = BLOCKED

means:

    "The workflow intentionally stopped because the change violated a gate."

This is different from:

    diff-gate = ERROR

which means:

    "The tool itself failed to operate."

---

# 36. No False Success

The orchestrator must be extremely strict about evidence.

Never report:

    tests passed

unless actual test execution produced successful evidence.

Never report:

    sandboxed

unless agent-sandbox actually executed the workload.

Never report:

    memory recalled

unless agent-memory returned the result.

Never report:

    gate passed

unless the actual gate returned success.

This is a core security and trust principle.

---

# 37. Security Boundaries

The orchestrator itself must be treated as security-sensitive infrastructure.

Requirements:

- no arbitrary shell interpolation
- use subprocess argument arrays
- validate paths
- avoid shell=True
- avoid unnecessary privileges
- avoid writing outside intended workspace
- protect logs from accidental secret storage
- never expose environment secrets to AI unnecessarily
- never disable sandbox controls
- fail closed when security-critical state is unknown

---

# 38. Secret Handling

The orchestrator must not intentionally store:

- API keys
- passwords
- tokens
- private keys
- credentials

Logs and evidence should be treated as potentially sensitive.

The orchestrator should cooperate with agent-memory's secret protection rather than create its own competing implementation.

---

# 39. Configuration

Configuration should remain simple.

Prefer:

    workflow.md

plus optional:

    .orchestrator/config

or:

    orchestrator.toml

Only introduce configuration complexity when necessary.

The first implementation should prioritize readable configuration over framework-style configuration systems.

---

# 40. CLI

The CLI should be simple.

Potential interface:

    orchestrator init

    orchestrator doctor

    orchestrator status

    orchestrator run

    orchestrator run --mode solo

    orchestrator run --mode development

    orchestrator run --mode security

    orchestrator run --mode enterprise

    orchestrator tools

    orchestrator agents

    orchestrator report

    orchestrator audit

    orchestrator evidence

    orchestrator resume

The final command structure should be determined during implementation.

---

# 41. Doctor Command

The doctor command should verify:

- Python version
- Git availability
- Docker availability where required
- seven repositories
- tool versions
- required scripts
- sandbox capability
- workflow.md
- project state
- AI provider availability if configured

Example:

    orchestrator doctor

Output:

    [PASS] Python
    [PASS] Git
    [PASS] agent-error-log
    [PASS] agent-decision-log
    [PASS] agent-log-ai
    [PASS] agent-memory
    [PASS] agent-blame
    [PASS] agent-diff-gate
    [PASS] agent-sandbox
    [PASS] workflow.md
    [WARN] Ollama unavailable
    [PASS] Core orchestrator usable

The absence of an AI provider should not make the core system unusable.

---

# 42. AI Provider Failure

If an AI provider fails:

    provider unavailable

the orchestrator should distinguish this from a tool failure.

Possible behavior:

- continue deterministically where possible
- mark AI-assisted stage unavailable
- do not fabricate an AI result
- optionally request another configured agent/provider
- require human intervention if the stage is mandatory

---

# 43. Multi-Agent Scheduling

In multi-agent mode, the orchestrator should support:

    SEQUENTIAL

    PARALLEL

    REVIEW

    DEBATE

    CONSENSUS

However, parallel execution must only be allowed where tasks are independent and safe.

Example:

    Security review
          \
           \
            -> Orchestrator -> decision
           /
    Test review
          /

Agents should not concurrently modify the same working tree unless explicitly designed and isolated.

---

# 44. Agent Isolation

When multiple agents modify code:

Prefer:

    agent A -> isolated workspace/branch
    agent B -> isolated workspace/branch
    agent C -> read-only review

Then:

    orchestrator
         |
         v
    diff-gate
         |
         v
    sandbox
         |
         v
    merge decision

This prevents agents from corrupting one another's state.

---

# 45. Agent Roles

Agents should have capabilities, not unrestricted authority.

Example:

    planner:
        read = yes
        write = no
        execute = no

    developer:
        read = yes
        write = yes
        execute = sandbox-only

    security:
        read = yes
        write = proposal-only
        execute = sandbox-only

    reviewer:
        read = yes
        write = no
        execute = sandbox-only

The orchestrator enforces these capabilities.

---

# 46. Enterprise Governance

Enterprise mode should be policy-driven.

Example:

    policy:
        sandbox_required: true
        diff_gate_required: true
        human_approval_required: true
        memory_auto_promotion: false
        native_execution: false
        external_network: false

The exact configuration syntax should be designed later.

The important principle is that policy must be explicit and inspectable.

---

# 47. Audit Report

Every completed enterprise/security run should be able to generate:

    ORCHESTRATION_REPORT.md

The report should contain:

- run ID
- project
- mode
- start/end
- tools used
- agents used
- models used
- commands executed
- exit codes
- decisions
- errors
- gates
- sandbox executions
- tests
- final Git state
- blocked actions
- human approvals
- final verdict

This continues the evidence-first philosophy demonstrated by the existing ecosystem.

---

# 48. Testing Philosophy

The orchestrator must have extensive tests.

Minimum categories:

1. CLI tests
2. tool discovery tests
3. workflow parsing tests
4. state machine tests
5. gate tests
6. failure tests
7. security tests
8. sandbox integration tests
9. multi-agent tests
10. evidence/report tests
11. malicious input tests
12. path traversal tests
13. subprocess safety tests

The orchestrator should be tested against fake/mock tool outputs as well as real integration tests.

---

# 49. Integration Test

A complete integration test should reproduce the established seven-tool test philosophy.

Example:

    intentionally vulnerable project
          |
          v
    error-log
          |
          v
    decision-log
          |
          v
    log-ai
          |
          v
    memory
          |
          v
    blame
          |
          v
    unsafe change
          |
          v
    diff-gate rejects
          |
          v
    corrected change
          |
          v
    diff-gate passes
          |
          v
    commit
          |
          v
    sandbox
          |
          v
    tests
          |
          v
    report

The test must prove real execution, not simulated success.

---

# 50. Repository Structure

Initial repository proposal:

    agent-orchestrator/
    |
    +-- README.md
    +-- LICENSE
    +-- AGENTS.md
    +-- workflow.md
    +-- rules.txt
    +-- CHANGELOG.md
    |
    +-- orchestrator/
    |   +-- __init__.py
    |   +-- cli.py
    |   +-- workflow.py
    |   +-- registry.py
    |   +-- executor.py
    |   +-- evidence.py
    |   +-- policy.py
    |   +-- state.py
    |   +-- modes.py
    |   +-- agents.py
    |   +-- security.py
    |   +-- reports.py
    |
    +-- tests/
    |
    +-- examples/
    |
    +-- docs/
    |
    +-- .github/
        +-- workflows/

This structure should remain intentionally small.

---

# 51. Zero-Dependency Rule

The orchestrator must not introduce:

    pip install framework X

as a prerequisite for basic operation.

Prefer Python stdlib:

- subprocess
- pathlib
- json
- dataclasses
- enum
- argparse
- tempfile
- hashlib
- time
- os
- sys
- shlex where appropriate

External programs such as Git and Docker may be required for specific capabilities because the existing ecosystem already uses them.

The distinction is:

    Python runtime dependency = ZERO

while:

    optional/external execution capability = Git/Docker/etc.

---

# 52. No Hidden Framework

Do not build an internal "AI framework" unless there is a demonstrated need.

Avoid:

- unnecessary plugin frameworks
- dependency injection frameworks
- ORM
- web server
- database
- message broker
- cloud control plane
- complicated event bus

The orchestrator should initially be a deterministic Python CLI that coordinates processes.

---

# 53. Plugin Philosophy

Tool integrations should be extensible.

However, the seven existing tools should remain first-class.

A future tool could implement:

    name
    capabilities
    command
    inputs
    outputs
    security properties

But plugin architecture should not become a dependency-heavy system.

Simple Python interfaces or declarative metadata are preferred.

---

# 54. Observability

The orchestrator should be transparent.

A user should be able to understand:

    WHAT DID THE ORCHESTRATOR DO?

without reading source code.

Commands should be visible.

Tool output should be captured.

Decisions should be recorded.

Failures should be explained.

The user should never see:

    "AI magic happened."

They should see:

    tool -> output -> decision -> next action

---

# 55. Philosophy of AI

The orchestrator should assume:

AI is powerful but fallible.

Therefore:

    AI proposes.
    Deterministic tools verify.
    Security boundaries contain.
    Logs preserve history.
    Memory preserves trusted knowledge.
    Gates enforce quality.
    Humans retain authority.

This is the central philosophy of the entire ecosystem.

---

# 56. Relationship to Existing Seven Tools

The architecture should be:

                    AGENT
                      |
                      v
               ORCHESTRATOR
                      |
       +--------------+--------------+
       |              |              |
       v              v              v
    WORKFLOW       AI AGENTS       POLICY
       |              |              |
       +--------------+--------------+
                      |
          +-----------+-----------+
          |           |           |
          v           v           v
       ERROR       DECISION     MEMORY
          |
          +-----------+
          |
       LOG-AI
          |
       BLAME
          |
      DIFF-GATE
          |
      SANDBOX
          |
          v
       VERIFY
          |
          v
       COMMIT

The seven tools remain the foundation.

The orchestrator is the coordination layer.

---

# 57. What the Orchestrator Must NOT Become

It must NOT become:

- a replacement for the seven tools
- a mandatory cloud service
- an API-key-dependent framework
- a giant dependency tree
- an opaque autonomous system
- an unrestricted shell executor
- a database-first application
- a system that trusts AI output automatically
- a system that bypasses security for convenience
- a system that automatically promotes memory
- a system that hides failures

---

# 58. Initial MVP

The first release should NOT attempt to implement every Enterprise feature.

MVP:

1. Tool discovery
2. workflow.md loading
3. Solo mode
4. Development mode
5. Sandbox-first execution
6. Seven-tool integration
7. deterministic state machine
8. evidence recording
9. gate enforcement
10. run report
11. doctor command
12. resume capability

Then add:

13. Security mode
14. Multiple agents
15. Enterprise mode
16. agent isolation
17. approvals
18. policy engine
19. advanced audit/reporting

---

# 59. Development Order

Recommended implementation phases:

## Phase 1 — Foundation

Build:

- repository
- CLI
- tool registry
- workspace detection
- workflow.md loader
- basic state machine

Goal:

    orchestrator doctor

works reliably.

---

## Phase 2 — Seven Tool Integration

Integrate all seven repositories.

Goal:

    orchestrator tools

shows all seven tools and their status.

Then:

    orchestrator run

can execute the standard workflow.

---

## Phase 3 — Evidence

Add:

- run IDs
- action records
- exit codes
- tool outputs
- decisions
- evidence files
- reports

Goal:

Every run can be reconstructed.

---

## Phase 4 — Sandbox Default

Make agent-sandbox the standard execution mechanism.

Goal:

The agent does not normally execute project code directly on the host.

---

## Phase 5 — Security

Implement:

- fail-closed execution
- command validation
- path restrictions
- secret-safe logging
- policy enforcement
- explicit exceptions

---

## Phase 6 — Multi-Agent

Add:

- agent registry
- roles
- provider adapters
- sequential execution
- parallel independent tasks
- review agents
- isolated workspaces

---

## Phase 7 — Operating Modes

Finalize:

- SOLO
- DEVELOPMENT
- SECURITY
- ENTERPRISE

Each mode should be a policy profile over the same underlying engine.

Do NOT create four separate orchestrators.

---

# 60. Versioning

Follow the existing ecosystem's disciplined release approach.

Use semantic versions:

    v0.1.0
    v0.2.0
    v1.0.0

Record:

- changes
- security changes
- workflow changes
- compatibility changes
- tool integration changes

The orchestrator should report which tool versions were used during a run.

---

# 61. Compatibility

The orchestrator should avoid tightly coupling itself to internal implementation details of the seven repositories.

Prefer their:

- documented CLI
- documented files
- documented exit codes
- documented interfaces

If a tool changes internally but preserves its public interface, the orchestrator should continue working.

---

# 62. Security Priority

Security has priority over convenience.

If there is a choice between:

    "continue automatically"

and:

    "stop safely"

the default should be:

    STOP SAFELY

especially in SECURITY and ENTERPRISE modes.

---

# 63. Design Principle for Future Features

Every proposed feature should answer:

1. Does it improve orchestration?
2. Does it preserve zero dependencies?
3. Does it preserve local-first operation?
4. Does it preserve tool independence?
5. Does it improve evidence?
6. Does it improve security?
7. Does it reduce AI hallucination risk?
8. Does it preserve human authority?
9. Can it be tested deterministically?
10. Does it fit the philosophy of the existing ecosystem?

If the answer is no, the feature should be reconsidered.

---

# 64. Final Architectural Statement

agent-orchestrator is not intended to be "another AI agent."

It is the control layer that makes a collection of specialized agent tools behave like a coherent engineering system.

The architecture is:

    AI AGENT(S)
          |
          v
    AGENT-ORCHESTRATOR
          |
          +--> workflow
          +--> policy
          +--> evidence
          +--> state
          +--> scheduling
          |
          v
    EXISTING TOOL ECOSYSTEM
          |
          +--> error-log
          +--> decision-log
          +--> log-ai
          +--> memory
          +--> blame
          +--> diff-gate
          +--> sandbox
          |
          v
       VERIFIED RESULT

The fundamental rule is:

    AI may propose.
    The orchestrator coordinates.
    Tools verify.
    Gates enforce.
    Sandbox contains.
    Memory preserves trusted knowledge.
    Logs preserve history.
    Humans retain authority.

This principle must remain intact as the project grows.

---

# 65. Definition of Success

The orchestrator is successful when a user can place a project inside the ecosystem and simply tell an AI:

    "Build this feature."

The AI should then be able to operate through the orchestrator and automatically:

- understand the existing project
- inspect previous errors
- inspect previous decisions
- recall trusted knowledge
- plan the work
- use appropriate AI agents
- make changes
- test through the sandbox
- log failures before fixing them
- record important decisions
- use historical Git context when useful
- extract lessons
- preserve knowledge
- run diff-gate
- reject unsafe changes
- execute verified code in the sandbox
- commit only after required gates pass
- produce an evidence-backed report

The user should not need to manually coordinate the seven repositories.

That is the purpose of agent-orchestrator.

---

# 66. Final Rule

The orchestrator itself must live by the same philosophy as the tools it orchestrates.

It must be:

    small
    deterministic
    inspectable
    local-first
    zero-dependency
    security-first
    fail-closed where appropriate
    evidence-based
    AI-assisted, not AI-dependent
    human-governed
    composable
    independently testable

The orchestrator should become the eighth repository only because it coordinates the other seven — not because it replaces them.

END OF DESIGN DOCUMENT