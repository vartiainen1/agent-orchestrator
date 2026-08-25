# Security Policy

## Reporting Security Issues

If you discover a security vulnerability in agent-orchestrator, please report
it responsibly. Do not open a public GitHub issue for security vulnerabilities.

## Security Model

agent-orchestrator implements a defense-in-depth security model:

- **Zero external dependencies** — Python standard library only
- **No shell=True** — all subprocess calls use argument lists
- **No eval/exec/os.system** — AST-verified
- **Fail closed** — invalid state, missing tools → stop
- **Evidence-backed** — every important action produces an audit record
- **Path traversal protection** — validated run IDs and paths
- **Security scanner** — 26 deterministic patterns across 9 categories

## Scope

In scope: orchestrator/ source code, CLI, dashboard, providers, persistence, evidence.

Out of scope: the seven external tool repositories, third-party AI providers, user project files.
