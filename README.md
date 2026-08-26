# agent-orchestrator

[![CI](https://github.com/vartiainen1/agent-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/vartiainen1/agent-orchestrator/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](https://github.com/vartiainen1/agent-orchestrator/releases/tag/v0.1.0)

Coordination layer for the 7-tool AI agent ecosystem.

agent-orchestrator is the **control plane** that makes seven separate AI-agent tools operate as one coherent engineering workflow. It is **not** an AI model, **not** an AI provider, and **not** a replacement for any individual tool.

    orchestrator != AI model
    orchestrator != AI provider
    orchestrator != CLI transport
    orchestrator != individual tool

## Why It Exists

Modern AI-assisted development involves many independent tools: error tracking, decision logging, code review, memory, blame analysis, diff validation, and sandboxed execution. Each tool is useful alone, but coordinating them manually is tedious and error-prone.

agent-orchestrator solves this by providing a single coordination layer that:

- Discovers and invokes tools through a uniform adapter interface
- Enforces security policies across all tool interactions
- Manages multi-agent workflows with role-based permissions
- Records evidence for every significant action
- Supports four operating modes from lightweight to enterprise-grade

## Architecture

    AI AGENT / CLI
          |
    ORCHESTRATOR
          |
    +-----------------+
    |  Policy Engine   |  <- 4 modes: SOLO, DEVELOPMENT, SECURITY, ENTERPRISE
    +-----------------+
    | Workflow Engine  |  <- state machine, branching, gate enforcement
    +-----------------+
    |  Multi-Agent     |  <- 7 roles, scheduler, provider abstraction
    +-----------------+
    |  Evidence/Report |  <- append-only, persistence, Markdown + JSON
    +-----------------+
    |  Validation      |  <- path boundaries, tool output, security scanning
    +-----------------+
          |
    +-----------------+
    | Tool Adapters    |  <- 7 adapters, shell=False
    +-----------------+
          |
    7 EXISTING TOOLS   <- unchanged, authoritative

## Seven-Tool Ecosystem

The orchestrator discovers and integrates with seven existing tools:

| Tool | Purpose | Platform | Required? |
|------|---------|----------|:---------:|
| [agent-error-log](https://github.com/vartiainen1/agent-error-log) | Error tracking and gate enforcement | All | For full workflow |
| [agent-decision-log](https://github.com/vartiainen1/agent-decision-log) | Decision tracking with rationale | All | For full workflow |
| [agent-log-ai](https://github.com/vartiainen1/agent-log-ai) | Log analysis, LLM lesson extraction | All | Needs Ollama |
| [agent-memory](https://github.com/vartiainen1/agent-memory) | Governed persistent knowledge | All | For full workflow |
| [agent-blame](https://github.com/vartiainen1/agent-blame) | Git archaeology and historical context | All | For full workflow |
| [agent-diff-gate](https://github.com/vartiainen1/agent-diff-gate) | Pre-commit diff validation | All | For full workflow |
| [agent-sandbox](https://github.com/vartiainen1/agent-sandbox) | Isolated code execution | Linux only | SECURITY/ENTERPRISE |

The tools are **integrations** -- the orchestrator locates them in the workspace and invokes them through adapters. It does not bundle, modify, or replace them.

When a tool is unavailable, the orchestrator continues with the remaining tools and reports which tools are missing via `orchestrator doctor`.

## Supported AI Providers

The orchestrator is **provider-agnostic**. It works with or without an AI provider. Four providers are included:

| Provider | Type | API Key | Description |
|----------|------|:-------:|-------------|
| NoneProvider | Deterministic | No | No AI -- agents produce deterministic output |
| OllamaProvider | Local HTTP | No | Local Ollama models via HTTP |
| CLIProvider | Generic CLI | No | Any CLI-based AI tool via subprocess |
| FreebuffProvider | CLI (FreeBuff) | No | FreeBuff CLI -- one supported provider |

**No API key is required for local operation.**

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for how to implement your own AI provider without modifying the core engine.

## Operating Modes

| Behavior | SOLO | DEVELOPMENT | SECURITY | ENTERPRISE |
|----------|:----:|:-----------:|:--------:|:----------:|
| diff-gate | optional | **required** | **required** | **required** |
| sandbox | optional | **required** | **mandatory** | **mandatory** |
| sandbox strict | no | no | **yes** | **yes** |
| cloud AI | allowed | allowed | **blocked** | **blocked** |
| approval | no | no | no | **recorded** |
| evidence level | basic | standard | enhanced | **complete** |

All four modes share 6 inviolable base safety rules that cannot be weakened through configuration.

## Multi-Agent System

- 7 agent roles: planner, developer, reviewer, tester, security, researcher, documenter
- Immutable agent permissions (frozen dataclasses)
- Agents propose; the orchestrator decides
- No direct agent-to-agent communication
- Sequential execution with conflict resolution

See [docs/AGENTS.md](docs/AGENTS.md) for details on agent roles, permissions, and the scheduler.

## Security Model

- **Zero external dependencies** -- Python standard library only
- **No shell=True** -- all subprocess calls use argument lists
- **No eval/exec/os.system** -- AST-verified
- **Fail closed** -- invalid state, missing tools, unsupported sandbox -> stop
- **Evidence-backed** -- every important action produces an audit record
- **No fabricated results** -- never claim a tool ran when it did not
- **Mandatory safety rules** -- 6 base rules inviolable across all modes
- **Path traversal protection** -- validated run IDs and paths
- **Security scanner** -- 26 deterministic patterns across 9 categories
- **Tool output validation** -- null bytes, binary content, size limits

See [SECURITY.md](SECURITY.md) for the complete security model.

## Evidence / Persistence / Recovery

- **Evidence logging** -- append-only JSONL records of every significant action
- **Persistence** -- atomic state writes with fsync, survives crashes
- **Run history** -- browseable via `orchestrator history`
- **Recovery** -- interrupted runs detected and recoverable via `orchestrator recover`
- **Cancellation** -- `orchestrator cancel` preserves evidence and cleans up

Evidence includes: provider invocations, tool results, policy decisions, gate outcomes, agent actions, workflow state transitions, and error records.

## Installation

```bash
# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install from the repository
pip install git+https://github.com/vartiainen1/agent-orchestrator.git

# Or clone and install in development mode
git clone https://github.com/vartiainen1/agent-orchestrator.git
cd agent-orchestrator
pip install -e .

# Verify installation
orchestrator --version
orchestrator doctor
```

### Companion Tools

The seven companion tools are **optional** for basic operation but required for full ecosystem functionality. Clone them as siblings of your project:

```
my-project/
+-- agent-error-log/      # optional
+-- agent-decision-log/   # optional
+-- agent-log-ai/         # optional (needs Ollama)
+-- agent-memory/         # optional
+-- agent-blame/          # optional
+-- agent-diff-gate/      # optional
+-- agent-sandbox/        # optional (Linux only)
+-- .orchestrator/        # created by orchestrator
```

The orchestrator discovers tools automatically via workspace detection. Missing tools are reported via `orchestrator doctor` and handled gracefully.

## Quick Start

```bash
# Install
pip install -e .

# Check system health
orchestrator doctor

# Run a workflow
orchestrator run --mode solo

# Start the dashboard
orchestrator dashboard
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `orchestrator status` | Show orchestrator and tool status |
| `orchestrator doctor` | System health check with tool availability |
| `orchestrator run` | Execute a workflow |
| `orchestrator modes` | List operating modes and policies |
| `orchestrator policies` | Show mode policy details |
| `orchestrator history` | Browse run history |
| `orchestrator show <RUN_ID>` | Show run details |
| `orchestrator evidence <RUN_ID>` | Show run evidence timeline |
| `orchestrator cancel <RUN_ID>` | Cancel a running workflow |
| `orchestrator recover` | Recover interrupted runs |
| `orchestrator dashboard` | Start the local web dashboard |

## Dashboard

A read-only web dashboard is included for monitoring orchestrator activity.

```bash
orchestrator dashboard              # starts on 127.0.0.1:8520
orchestrator dashboard --port 9000  # custom port
orchestrator dashboard --open       # open in browser
orchestrator dashboard --no-refresh # disable auto-refresh
```

The dashboard displays:
- Active and recent runs with status
- Run detail with full lifecycle
- Evidence timeline for each run
- Tool health and availability
- System status and configuration
- Policy information by mode

The dashboard is **read-only** -- it cannot execute workflows, modify runs, or interact with providers.

## Configuration

The orchestrator uses `.orchestrator/config` in your project directory:

- **provider**: which AI provider to use (`none`, `ollama`, `cli`, `freebuff`)
- **mode**: default operating mode (`solo`, `development`, `security`, `enterprise`)
- **project_path**: project root for tool discovery

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for provider configuration details.

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux | **Fully supported** | All 7 tools available |
| Windows | **Fully supported** | agent-sandbox: UNSUPPORTED |
| macOS | Expected | Not actively tested |

**agent-sandbox** requires Linux. On Windows, SECURITY and ENTERPRISE modes correctly block execution when sandbox is unavailable.

## Testing

```bash
python -m unittest discover -v
```

The test suite contains **905 tests** covering:
- Workflow engine and state machine
- Policy enforcement across all 4 modes
- Multi-agent execution and permissions
- Tool adapters and discovery
- Provider abstraction
- Persistence, recovery, and evidence
- Dashboard HTTP endpoints
- Security scanning and adversarial attacks
- CLI commands

## Project Structure

```
agent-orchestrator/
+-- orchestrator/        # core engine
|   +-- engine.py        # workflow state machine
|   +-- scheduler.py     # step execution
|   +-- policy.py        # mode policies
|   +-- agents.py        # multi-agent system
|   +-- providers.py     # AI provider abstraction
|   +-- adapters.py      # tool adapters
|   +-- discovery.py     # tool workspace discovery
|   +-- persist.py       # atomic state persistence
|   +-- evidence.py      # JSONL evidence logging
|   +-- recovery.py      # interrupted-run detection
|   +-- report.py        # report generation
|   +-- scanner.py       # security pattern scanner
|   +-- state.py         # state types and dataclasses
|   +-- config.py        # configuration loading
|   +-- cli.py           # CLI entry point
|   +-- dashboard.py     # HTTP server
|   +-- dashboard_ui.py  # HTML rendering
+-- tests/               # 905 tests
+-- docs/                # documentation
+-- .github/             # CI and community standards
+-- README.md
+-- LICENSE
+-- SECURITY.md
+-- DESIGN.md
+-- AGENTS.md
+-- ROADMAP.md
+-- pyproject.toml
```

## Documentation

- [DESIGN.md](DESIGN.md) -- architecture and design principles
- [AGENTS.md](AGENTS.md) -- multi-agent system
- [SECURITY.md](SECURITY.md) -- security model
- [ROADMAP.md](ROADMAP.md) -- development history
- [docs/PROVIDERS.md](docs/PROVIDERS.md) -- AI provider integration
- [docs/AGENTS.md](docs/AGENTS.md) -- agent roles and permissions

## Companion Tools

The seven companion tools are separate repositories maintained alongside the orchestrator:

| Repository | Description |
|------------|-------------|
| [agent-error-log](https://github.com/vartiainen1/agent-error-log) | Error tracking and gate enforcement |
| [agent-decision-log](https://github.com/vartiainen1/agent-decision-log) | Decision tracking with rationale |
| [agent-log-ai](https://github.com/vartiainen1/agent-log-ai) | Log analysis with LLM extraction |
| [agent-memory](https://github.com/vartiainen1/agent-memory) | Governed persistent knowledge |
| [agent-blame](https://github.com/vartiainen1/agent-blame) | Git archaeology and historical context |
| [agent-diff-gate](https://github.com/vartiainen1/agent-diff-gate) | Pre-commit diff validation |
| [agent-sandbox](https://github.com/vartiainen1/agent-sandbox) | Isolated code execution (Linux) |

## License

MIT License. See [LICENSE](LICENSE) for the full license text.

## Status

Current version: **v0.1.0**

- 905 tests passing
- CI green on Python 3.11, 3.12, 3.13
- Zero external Python dependencies
- 674+ real-world CLI executions validated
