# Contributing to agent-orchestrator

Thank you for your interest in contributing to agent-orchestrator.

## What is agent-orchestrator?

agent-orchestrator is the coordination layer for a 7-tool AI agent ecosystem.
It is **not** an AI model, **not** an AI provider, and **not** a replacement for
any individual tool. It discovers and coordinates seven existing tools through a
uniform adapter interface, enforces security policies, manages multi-agent
workflows, and records evidence for every significant action.

## Development Setup

### Requirements

- Python 3.11 or later
- No external dependencies required (Python standard library only)

### Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### Install for Development

```bash
git clone https://github.com/vartiainen1/agent-orchestrator.git
cd agent-orchestrator
pip install -e .
```

### Run the Test Suite

```bash
python -m unittest discover -v
```

Expected result: **905 tests passing**, 0 failures.

If your test count differs significantly, check that you are on the `main`
branch and that your working tree is clean.

## Seven Companion Tools

The orchestrator integrates with seven existing tools:

- agent-error-log
- agent-decision-log
- agent-log-ai
- agent-memory
- agent-blame
- agent-diff-gate
- agent-sandbox

These tools live in **separate repositories**. They are discovered automatically
when present as sibling directories in the workspace. You do **not** need to
clone them for basic development, but some integration tests expect them to be
present.

The seven tool repositories should **not** be modified as part of contributions
to agent-orchestrator unless there is a specific, justified reason. If a change
in agent-orchestrator requires a corresponding change in a companion tool, that
must be explicitly documented in the pull request.

## Platform Considerations

- **Windows**: Fully supported. agent-sandbox is **not available** on Windows.
  This is a known platform limitation, not a bug.
- **Linux**: Fully supported. All seven tools are available.
- **macOS**: Expected to work but not actively tested.

When contributing, be aware that some tests behave differently on Windows vs
Linux, particularly around sandbox availability and path handling.

## Security Expectations

agent-orchestrator enforces strict security invariants. All contributions must
preserve these:

- **Zero external dependencies** -- Python standard library only. Do not add
  third-party packages without explicit approval.
- **No shell=True** -- all subprocess calls must use argument lists.
- **No eval/exec/os.system** -- these are forbidden in production code.
- **Fail closed** -- when in doubt, the orchestrator stops rather than proceeds
  with uncertain state.
- **No secret leakage** -- never commit secrets, API keys, credentials, or
  personal tokens.
- **Path traversal protection** -- all file paths and run IDs must be validated.

If your change touches subprocess invocation, provider interaction, tool
adapter logic, policy enforcement, or evidence recording, it will receive
additional security review.

## Documentation Expectations

- Keep documentation consistent with implementation.
- If you add or change a CLI command, update the relevant documentation.
- If you change provider behavior, update `docs/PROVIDERS.md`.
- If you change agent behavior, update `docs/AGENTS.md`.
- Do not invent features or capabilities that do not exist.

## Submitting an Issue

Before opening an issue, check whether a similar issue already exists.

When reporting a bug, include:

- Description of the problem
- Expected vs actual behavior
- Steps to reproduce
- Python version and operating system
- agent-orchestrator version
- Relevant logs or evidence output
- Whether the issue involves a security concern (see SECURITY.md)

For feature requests, describe the problem you are trying to solve, your
proposed solution, and any alternatives you considered.

## Submitting a Pull Request

1. Fork the repository and create a branch from `main`.
2. Make your changes.
3. Run the full test suite: `python -m unittest discover -v`
4. Verify all 905 tests pass.
5. Open a pull request against `main`.

In your pull request:

- Describe what changed and why.
- Note any breaking changes.
- Note any impact on the seven-tool ecosystem.
- Confirm that no secrets, credentials, or API keys were added.
- Confirm that no external dependencies were added.
- Confirm that security invariants are preserved.

Keep changes focused. Avoid unrelated refactors in the same pull request.

## CI

Pull requests run GitHub Actions CI on Python 3.11, 3.12, and 13. The CI
workflow:

- Installs the project
- Runs the complete test suite
- Checks for zero external dependencies
- Runs security/AST scanning

All CI checks must pass before a pull request can be merged.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.
