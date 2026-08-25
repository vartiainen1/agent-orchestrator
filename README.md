# agent-orchestrator

Coordination layer for the 7-tool AI agent ecosystem.

## What is agent-orchestrator?

agent-orchestrator is the **control plane** that makes seven separate AI-agent
tools operate as one coherent engineering workflow. It is **not** an AI model,
**not** an AI provider, and **not** a replacement for any individual tool.

```
orchestrator ≠ AI model
orchestrator ≠ AI provider
orchestrator ≠ CLI transport
orchestrator ≠ individual tool
```

The orchestrator coordinates:

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

## Supported AI Providers

The orchestrator is **provider-agnostic**. It works with or without an AI
provider. Four providers are included:

| Provider | Type | API Key | Description |
|----------|------|:-------:|-------------|
| NoneProvider | Deterministic | No | No AI — agents produce deterministic output |
| OllamaProvider | Local HTTP | No | Local Ollama models via HTTP |
| CLIProvider | Generic CLI | No | Any CLI-based AI tool via subprocess |
| FreebuffProvider | CLI (FreeBuff) | No | FreeBuff CLI — one supported provider |

**No API key is required for local operation.**

### Adding a custom provider

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for how to implement your own
AI provider without modifying the core engine.

## Seven-Tool Ecosystem

The orchestrator discovers and integrates with seven existing tools:

| Tool | Capability | Platform |
|------|-----------|----------|
| agent-error-log | Error tracking, gate enforcement | All |
| agent-decision-log | Decision tracking | All |
| agent-log-ai | Log analysis, LLM extraction | All (needs Ollama) |
| agent-memory | Persistent knowledge | All |
| agent-blame | Git archaeology | All |
| agent-diff-gate | Diff validation, security checks | All |
| agent-sandbox | Isolated execution | Linux only |

The tools are **integrations** — the orchestrator locates them in the workspace
and invokes them through adapters. It does not bundle, modify, or replace them.

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

## Multi-Agent System

- 7 agent roles: planner, developer, reviewer, tester, security, researcher, documenter
- Immutable agent permissions (frozen dataclasses)
- Agents propose; the orchestrator decides
- No direct agent-to-agent communication
- Sequential execution with conflict resolution

See [docs/AGENTS.md](docs/AGENTS.md) for details on agent roles, permissions,
and the scheduler.

## Quick Start

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

# Launch the web dashboard
orchestrator dashboard
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
orchestrator dashboard             # launch web dashboard (read-only)
```

## Configuration

Configuration lives in `.orchestrator/config` inside your project:

```ini
# Operating mode: solo, development, security, enterprise
mode = solo

# Provider: none, ollama, freebuff, cli
provider = ollama

# Optional: custom CLI provider settings
# provider_executable = my-ai-tool
# provider_args = --flag1 --flag2
# provider_timeout = 60
```

Mode selection precedence: CLI `--mode` flag > config file > default (solo).

## Dashboard

The orchestrator includes a read-only web dashboard:

```bash
orchestrator dashboard                    # default: 127.0.0.1:8520
orchestrator dashboard --port 9000        # custom port
orchestrator dashboard --open             # open browser automatically
```

The dashboard displays:
- Run list with status summary
- Run detail with tool call timeline
- Evidence timeline
- Tool health status (all 7 tools)
- System status and configuration
- Policy comparison across all 4 modes

The dashboard is **read-only** — it cannot execute workflows, tools, or agents.
It consumes existing persisted data through a stdlib HTTP server.

## Security Model

- **Zero external dependencies** — Python standard library only
- **No shell=True** — all subprocess calls use argument lists
- **No eval/exec/os.system** — AST-verified
- **Fail closed** — invalid state, missing tools, unsupported sandbox → stop
- **Evidence-backed** — every important action produces an audit record
- **No fabricated results** — never claim a tool ran when it didn't
- **Mandatory safety rules** — 6 base rules inviolable across all modes
- **Path traversal protection** — validated run IDs and paths
- **Security scanner** — 26 deterministic patterns across 9 categories
- **Tool output validation** — null bytes, binary content, size limits

See [SECURITY.md](SECURITY.md) for the complete security model.

## Platform Support

| Platform | Status |
|----------|--------|
| Windows | Fully supported (agent-sandbox: UNSUPPORTED) |
| Linux | Fully supported (all 7 tools) |
| macOS | Expected to work (not actively tested) |

**agent-sandbox** is Linux-only. On Windows, SECURITY and ENTERPRISE modes
correctly fail closed when sandbox is mandatory.

**Ollama** requires a running Ollama instance with at least one model pulled.
See [Ollama docs](https://ollama.com) for installation.

**FreeBuff** is a CLI-based AI tool. It must be installed and available on
PATH. See [FreeBuff docs](https://freebuff.com) for installation.

## Development

```bash
# Run the complete test suite
python -m unittest discover -v

# Run a specific test module
python -m unitt
