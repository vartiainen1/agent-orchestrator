# Multi-Agent System

The orchestrator supports multiple agents working through a centralized scheduler.
Agents **propose**; the orchestrator **decides**.

## Agent Roles

| Role | Description | Needs AI |
|------|-------------|:--------:|
| planner | Plans tasks and strategy | Yes |
| developer | Writes and modifies code | Yes |
| reviewer | Reviews code and decisions | No (deterministic) |
| tester | Tests and validates | Yes |
| security | Security analysis | No (deterministic) |
| researcher | Researches and analyzes | No (deterministic) |
| documenter | Documents findings | No (deterministic) |

**4 of 7 roles are deterministic** -- they work without any AI provider.

## Agent Permissions

Permissions are **immutable** (frozen dataclasses). Agents cannot modify
their own permissions.

## Scheduler

Tasks are assigned based on role match, tool permissions, and authority level.

## Provider Relationship

Multiple agents can share a single provider. Ten logical agents can use
the same provider/model sequentially through controlled scheduling.

## Security Properties

- Agents cannot self-assign tasks
- Agents cannot modify their own permissions
- Agents cannot bypass policy
- Agents cannot directly communicate with each other
- Tool permissions are enforced
