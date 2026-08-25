# agent-orchestrator

Coordination layer for the 7-tool AI agent ecosystem.

## What is this?

agent-orchestrator is the **control plane** that makes seven separate AI-agent
tools operate as one coherent engineering workflow:

1. **agent-error-log** — error tracking and gate enforcement
2. **agent-decision-log** — decision tracking with rationale
3. **agent-log-ai** — deterministic analysis + LLM lesson extraction
4. **agent-memory** — governed persistent knowledge with trust model
5. **agent-blame** — Git archaeology and historical context
6. **agent-diff-gate** — pre-commit diff validation and security checks
7. **agent-sandbox** — isolated code execution boundary

The orchestrator does **not** replace these tools. It coordinates them.

## Architecture

```
AI AGENT / CLI
      ↓
ORCHESTRATOR
      ↓
┌─────────────────┐
│  Policy Engine   │  ← 4 modes: SOLO, DEVELOPMENT, SECURITY, ENTERPRISE
├─────────────────┤
│ Workflow Engine  │  ← 11 states, branching, gate enforcement
├─────────────────┤
│  Multi-Agent     │  ← 7 roles, scheduler, provider abstraction
├─────────────────┤
│  Evidence/Report │  ← append-only, persistence, Markdown + JSON
├─────────────────┤
│  Validation      │  ← path boundaries, tool output, security scanning
└─────────────────┘
      ↓
┌─────────────────┐
│ Tool Adapters    │  ← 7 adapters, 26+ operations, shell=False
└─────────────────┘
      ↓
7 EXISTING TOOLS   ← unchanged, authoritative
```

## CLI Commands

```
orchestrator --help                # show available commands
orchestrator --version             # show version
orchestrator status                # workspace, project, and tool status
orchestrator status --json         # machine-readable status
orchestrator doctor                # verify environment readiness
orchestrator run --mode solo       # execute workflow in SOLO mode
orchestrator run --mode development
orchestrator run --mode security
orchestrator run --mode enterprise
orchestrator modes                 # list available modes with rules
orchestrator policies [mode]       # show effective policy
orchestrator history               # list recent runs
orchestrator show <run-id>         # show run details
orchestrator evidence <run-id>     # show evidence entries
orchestrator cancel <run-id>       # cancel interrupted run
orchestrator recover --list        # list interrupted runs
orchestrator recover --cancel ID   # cancel specific run
orchestrator recover --discard ID  # discard specific run
```

## Operating Modes

| Behavior | SOLO | DEVELOPMENT | SECURITY | ENTERPRISE |
|----------|:----:|:-----------:|:--------:|:----------:|
| diff-gate | optional | **required** | **required** | **required** |
| sandbox | optional | **required** | **mandatory** | **mandatory** |
| sandbox strict | no | no | **yes** | **yes** |
| cloud AI | allowed | allowed | **blocked** | **blocked** |
| approval | no | no | no | **recorded** |
| evidence level | basic | standard | enhanced | **complete** |

All four modes share 6 inviolable base safety rules that cannot be weakened
through configuration.

## Multi-Agent Engine

- 7 agent roles: planner, developer, reviewer, tester, security, researcher, documenter
- Immutable agent permissions (frozen dataclasses)
- Agents propose; the orchestrator decides
- No direct agent-to-agent communication
- Sequential execution with conflict resolution
- AI providers: NoneProvider (deterministic), OllamaProvider (local), FreebuffProvider (CLI)

## AI Provider Architecture

```
AIProvider (Protocol)
    ├── NoneProvider          # deterministic fallback, no AI
    ├── OllamaProvider        # local Ollama via HTTP, no API key
    └── CLIProvider           # generic CLI subprocess
          └── FreebuffProvider  # FreeBuff CLI, no API key
```

No API key is required for local operation.

## Security Model

- **Zero external dependencies** — Python standard library only
- **No shell=True** — all subprocess calls use argument lists
- **No eval/exec/os.system** — AST-verified
- **Fail closed** — invalid state, missing tools, unsupported sandbox → stop
- **Evidence-backed** — every important action produces an audit record
- **No fabricated results** — never claim a tool ran when it didn't
- **Mandatory safety rules** — 6 base rules inviolable across all modes
- **Sandbox is default execution boundary** — no silent host fallback
- **Path traversal protection** — validated run IDs and paths
- **Security scanner** — 26 deterministic patterns across 9 categories
- **Tool output validation** — null bytes, binary content, size limits

## Persistence

- Atomic writes (tempfile + os.replace)
- JSONL evidence append
- Run state persistence at every transition
- Run index for history
- Interrupted-run detection and recovery
- Corrupt state detection

## Requirements

- Python >= 3.11
- Zero external dependencies (stdlib only)
- The seven tool repositories in the same workspace (optional — system works without them, reporting their absence)

## Quick start

```bash
# Show help
orchestrator --help

# Show version
orchestrator --version

# Show workspace and tool status
orchestrator status

# Verify environment
orchestrator doctor

# Run in SOLO mode (default)
orchestrator run --mode solo

# Run in DEVELOPMENT mode
orchestrator run --mode development

# List available modes
orchestrator modes

# Show effective policy for a mode
orchestrator policies security

# View run history
orchestrator history
```

## Running tests

```bash
python -m unittest discover -v
```

## Project structure

```
agent-orchestrator/
├── orchestrator/
│   ├── __init__.py          # version
│   ├── cli.py               # CLI entry point (14 commands)
│   ├── config.py            # configuration loading + validation
│   ├── discovery.py         # tool discovery (7 tools)
│   ├── adapter.py           # tool adapter layer (7 adapters)
│   ├── engine.py            # workflow engine (11 states)
│   ├── workflow.py          # workflow definitions (3 built-in)
│   ├── state.py             # run state model
│   ├── modes.py             # 4 operating modes + base safety rules
│   ├── policy.py            # layered policy engine
│   ├── agents.py            # agent identity, roles, permissions
│   ├── providers.py         # AI providers (None, Ollama, CLI, FreeBuff)
│   ├── scheduler.py         # task scheduling (sequential + parallel)
│   ├── evidence.py          # evidence logging + auto-save
│   ├── persist.py           # atomic persistence (JSONL + state)
│   ├── recovery.py          # interrupted-run detection + recovery
│   ├── report.py            # Markdown + JSON reporting
│   ├── validate.py          # input validation + path boundaries
│   ├── security_scan.py     # deterministic security scanner (26 patterns)
│   ├── exit_codes.py        # named exit codes
│   ├── olog.py              # structured logging
│   └── workspace.py         # workspace/project detection
├── tests/                   # unittest-based test suite (19 files, 633 tests)
├── pyproject.toml
├── README.md
├── DESIGN.md
├── AGENTS.md
├── ROADMAP.md
├── SECURITY.md
└── PHASE_*_*.md             # phase design + implementation reports
```

## Philosophy

- **Zero dependencies** — Python standard library only
- **CLI-first** — human-readable, machine-parseable output
- **Deterministic** — the orchestrator is primarily a workflow engine, not an AI
- **Fail closed** — security over convenience
- **Evidence-based** — every action produces verifiable output
- **No fabricated results** — never claim a tool ran when it didn't
- **AI proposes, tools verify, gates enforce, humans retain authority**

## Platform Notes

- agent-sandbox is **Linux-only** — correctly detected as UNSUPPORTED on Windows
- SECURITY and ENTERPRISE modes **fail closed** when sandbox is unavailable on Windows
- All other tools work cross-platform

## License

MIT
