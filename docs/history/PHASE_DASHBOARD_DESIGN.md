# PHASE DASHBOARD DESIGN

## Orchestrate — Web Dashboard Design Document

---

## 1. Objective

Design an optional, read-first web dashboard that consumes the existing persisted run/state/evidence data and provides a browser-based interface for monitoring and inspecting orchestration runs.

The dashboard must be:
- **Optional** — the CLI remains the primary interface
- **Read-only by default** — no mutation without explicit action
- **Zero-dependency** — Python stdlib only (http.server)
- **Provider-agnostic** — no FreeBuff branding in the core
- **Security-first** — localhost-only, no secrets, no unauthenticated remote access
- **Additive** — no changes to existing orchestrator architecture

---

## 2. Scope

### In Scope
- Read-only web dashboard over existing persisted data
- Run listing and inspection
- Evidence timeline viewing
- Tool health/status display
- Agent activity display (from evidence)
- Policy decision visibility
- Gate result visibility
- Multi-project support (workspace directory)
- Live refresh via polling (no websockets)
- CLI command to launch the dashboard

### Non-Goals (Phase 1)
- Run creation/cancellation/recovery through the dashboard
- Real-time streaming of in-progress runs
- Authentication system
- User management
- Database backend
- WebSocket architecture
- Mobile-responsive design (desktop-first)
- Internationalization
- Dark/light mode toggle (single clean theme)
- Charts/graphs (text-based visualization is sufficient for v1)

---

## 3. Architecture

### 3.1 Current Architecture (Unchanged)

```
CLI → Workspace → Discovery → Adapters → WorkflowEngine → PolicyEngine → Evidence → Persistence → Reports
```

### 3.2 Dashboard Architecture (Additive)

```
Browser → HTTP Server (stdlib) → Dashboard Handler → Read existing data → JSON/HTML response
                                    ↓
                              .orchestrator/runs/  (read-only)
                              workspace/           (read-only for discovery)
```

The dashboard is a **read layer** over the existing persistence format. It does NOT:
- Create a second evidence system
- Duplicate the workflow engine
- Duplicate the policy engine
- Write to the persistence layer (except optional view-state tracking)
- Execute tools
- Execute workflows
- Modify agent state

### 3.3 Data Flow

```
                    ┌─────────────────────┐
                    │   Browser (HTML)    │
                    └─────────┬───────────┘
                              │ HTTP GET /api/...
                              ▼
                    ┌─────────────────────┐
                    │  DashboardHandler   │  (Python stdlib HTTP)
                    │  http.server        │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  Data Access Layer   │  (reads existing files)
                    │  persist.py (read)   │
                    │  evidence.py (read)  │
                    │  discovery.py        │
                    │  recovery.py (read)  │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  .orchestrator/      │
                    │    runs/             │
                    │      index.json      │
                    │      {run_id}/       │
                    │        state.json    │
                    │        evidence.jsonl│
                    └─────────────────────┘
```

---

## 4. Module Structure

### New Files

```
orchestrator/
    dashboard.py          # HTTP server + request handler (single file, <500 lines)
    dashboard_ui.py       # HTML template rendering (single file, <400 lines)
```

### Modified Files

```
orchestrator/cli.py      # Add "dashboard" subcommand
orchestrator/__init__.py # Add __version__ reference if needed
```

**Total new code: ~900 lines across 2 files.**

### Why Only 2 New Files

1. **`dashboard.py`** — The HTTP server, route handling, and data access. Uses `http.server.HTTPServer` and `http.server.BaseHTTPRequestHandler`. Routes are simple path-based dispatch.

2. **`dashboard_ui.py`** — HTML rendering. Generates clean HTML with inline CSS. No templates, no Jinja, no external assets. Self-contained single-page app.

No additional files needed because:
- The existing `persist.py` already provides all read functions (`list_runs`, `load_state`, `load_evidence`, `get_persisted_run`)
- The existing `discovery.py` already provides `discover_all`
- The existing `recovery.py` already provides `find_interrupted_runs`
- The existing `evidence.py` already provides `redact`
- The existing `report.py` already provides `report_dict`

---

## 5. CLI Integration

### New Command

```
orchestrator dashboard [OPTIONS]
```

Options:
```
  --port PORT       Port to listen on (default: 8520)
  --host HOST       Bind address (default: 127.0.0.1)
  --open            Open browser automatically (default: False)
  --no-refresh      Disable auto-refresh polling
```

### Behavior

1. Validates workspace exists
2. Starts HTTP server on localhost
3. Prints URL to terminal
4. Optionally opens browser
5. Serves until Ctrl+C
6. Cleans up on exit

### Exit Codes

- `0` — normal shutdown (Ctrl+C)
- `1` — startup error (port in use, workspace missing)

### Example Output

```
$ orchestrator dashboard
Orchestrate Dashboard v1.0
Serving on http://127.0.0.1:8520
Press Ctrl+C to stop.
```

---

## 6. API Design

All endpoints return JSON. The dashboard is read-only.

### 6.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard HTML page |
| GET | `/api/runs` | List all runs (from index) |
| GET | `/api/runs/{run_id}` | Run detail (full state) |
| GET | `/api/runs/{run_id}/evidence` | Evidence entries for a run |
| GET | `/api/tools` | Tool discovery status |
| GET | `/api/status` | System status (version, workspace, mode) |
| GET | `/api/interrupted` | Interrupted runs |
| GET | `/api/policies/{mode}` | Policy rules for a mode |
| GET | `/api/health` | Server health check |
| GET | `/static/{path}` | Serve inline static assets (CSS/JS embedded in HTML) |

### 6.2 Response Format

All API responses follow a consistent structure:

```json
{
  "ok": true,
  "data": { ... },
  "error": null
}
```

Error responses:

```json
{
  "ok": false,
  "data": null,
  "error": "run not found: RUN-xxx"
}
```

### 6.3 Endpoint Details

#### GET /api/runs

Returns the run index, most recent first.

```json
{
  "ok": true,
  "data": {
    "runs": [
      {
        "run_id": "RUN-20260825-143022-a1b2c3",
        "workflow": "development",
        "mode": "solo",
        "status": "PASS",
        "started_at": "2026-08-25T14:30:22Z",
        "ended_at": "2026-08-25T14:30:45Z",
        "project_dir": "/path/to/project",
        "tool_call_count": 7,
        "evidence_count": 12,
        "phase": "COMPLETED"
      }
    ],
    "total": 15
  }
}
```

#### GET /api/runs/{run_id}

Returns full run state including tool calls, policy decisions, gate results, observations.

```json
{
  "ok": true,
  "data": {
    "run_id": "RUN-...",
    "workflow_name": "development",
    "mode": "solo",
    "phase": "COMPLETED",
    "final_status": "PASS",
    "started_at": "...",
    "ended_at": "...",
    "tool_calls": [
      {
        "tool_name": "agent-error-log",
        "operation": "check",
        "status": "PASS",
        "exit_code": 0,
        "duration": 1.2,
        "timestamp": "...",
        "args": [],
        "stdout_preview": "No errors found...",
        "error": ""
      }
    ],
    "policy_decisions": [...],
    "gate_results": [...],
    "observations": [...]
  }
}
```

#### GET /api/runs/{run_id}/evidence

Returns evidence entries for a run.

```json
{
  "ok": true,
  "data": {
    "run_id": "RUN-...",
    "entries": [
      {
        "timestamp": "2026-08-25T14:30:22Z",
        "action": "workflow_started",
        "tool": "",
        "status": "",
        "detail": "development"
      }
    ],
    "total": 12
  }
}
```

#### GET /api/tools

Returns tool discovery results.

```json
{
  "ok": true,
  "data": {
    "tools": [
      {
        "name": "agent-error-log",
        "status": "AVAILABLE",
        "version": "0.1.0",
        "platform_support": "all",
        "capabilities": ["log-errors", "bootstrap", "health-check"]
      }
    ],
    "summary": {
      "total": 7,
      "available": 6,
      "unsupported": 1,
      "missing": 0
    }
  }
}
```

#### GET /api/status

Returns system status.

```json
{
  "ok": true,
  "data": {
    "version": "1.0.0",
    "project": "/path/to/project",
    "workspace": "/path/to/workspace",
    "mode": "solo",
    "sandbox_required": true,
    "diff_gate_required": true,
    "has_config": true,
    "has_workflow": true
  }
}
```

#### GET /api/interrupted

Returns interrupted runs.

```json
{
  "ok": true,
  "data": {
    "interrupted": [
      {
        "run_id": "RUN-...",
        "workflow": "development",
        "mode": "solo",
        "status": "RUNNING",
        "phase": "EXECUTING",
        "started_at": "...",
        "valid": true,
        "validation_reason": "valid"
      }
    ],
    "total": 0
  }
}
```

#### GET /api/policies/{mode}

Returns policy rules for a mode.

```json
{
  "ok": true,
  "data": {
    "mode": "security",
    "rules": {
      "diff_gate": {"value": "required", "mandatory": true, "source": "base"},
      "sandbox": {"value": "mandatory", "mandatory": true, "source": "base"},
      "cloud_ai": {"value": "blocked", "mandatory": true, "source": "base"}
    }
  }
}
```

#### GET /api/health

Simple health check.

```json
{
  "ok": true,
  "data": {
    "status": "healthy",
    "version": "1.0.0",
    "uptime": 123.45
  }
}
```

---

## 7. HTML Dashboard

### 7.1 Single-Page Architecture

The dashboard serves a single HTML page at `/` that uses JavaScript to fetch data from the API endpoints and render it dynamically.

No build step. No npm. No webpack. No React. Just vanilla HTML + CSS + JS.

### 7.2 Layout

```
┌──────────────────────────────────────────────────────────┐
│  ORCHESTRATE DASHBOARD                    v1.0.0   [⟳]  │
├──────────────────────────────────────────────────────────┤
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │
│  │ Runs │ │Tools │ │Status│ │Agent │ │Policy│          │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [Main content area — changes based on selected view]   │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Run List / Run Detail / Evidence / Tools / etc.  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 7.3 Views

#### View 1: Runs (default)

- Table of all runs from the index
- Columns: Run ID, Workflow, Mode, Status, Started, Tool Calls, Evidence Count
- Click a run to see detail
- Color-coded status: green (PASS), red (FAIL), yellow (BLOCKED), gray (RUNNING/CANCELLED)

#### View 2: Run Detail

- Full run information
- Tool call timeline (chronological)
- Each tool call shows: name, operation, status, duration, exit code
- Policy decisions section
- Gate results section
- Observations section
- Link to evidence timeline
- Back button to runs list

#### View 3: Evidence Timeline

- Chronological list of evidence entries for a selected run
- Each entry shows: timestamp, action, tool, status, detail
- Scrollable timeline
- Filter by action type

#### View 4: Tools

- Tool discovery results
- Each tool shows: name, status, version, platform, capabilities
- Color-coded: green (AVAILABLE), yellow (UNSUPPORTED), red (MISSING/ERROR)
- Summary counts

#### View 5: Status

- System information
- Version, project, workspace
- Configuration (mode, sandbox, diff_gate)
- Config file status
- Workflow file status
- Interrupted runs count

#### View 6: Policies

- Policy rules for each mode
- Side-by-side comparison of modes
- Highlight mandatory vs optional rules

### 7.4 Auto-Refresh

The dashboard polls `/api/runs` every 5 seconds (configurable) to detect new/in-progress runs. A refresh indicator shows in the header. Auto-refresh can be paused by the user.

No websockets. Simple HTTP polling.

### 7.5 Styling

Inline CSS in the HTML. Clean, minimal, professional:
- Monospace fonts for run IDs, tool names, code
- Sans-serif for headings and body
- Dark header, light content area
- Subtle borders and spacing
- Color-coded statuses
- No external fonts, no CDN, no icons library

---

## 8. Security Model

### 8.1 Binding

- **Default bind: 127.0.0.1** (localhost only)
- Not accessible from the network by default
- `--host 0.0.0.0` explicitly required for remote access (not recommended)

### 8.2 Authentication

- **None for v1** — localhost-only provides sufficient isolation
- Future versions may add optional token-based auth for remote access
- No session management needed for local-only use

### 8.3 Read-Only by Default

The dashboard does NOT provide:
- Run creation endpoints
- Run cancellation endpoints
- Run recovery endpoints
- Tool execution endpoints
- Workflow execution endpoints
- Configuration modification endpoints
- Agent management endpoints

All mutation operations remain CLI-only.

### 8.4 Secret Protection

- The dashboard inherits the existing `redact()` function from `evidence.py`
- Evidence entries are already redacted before persistence
- Dashboard reads the already-redacted data
- No raw secrets are served
- No environment variables are exposed
- No configuration file contents are dumped verbatim (only keys, not values for sensitive fields)

### 8.5 Path Traversal

- Run IDs are validated by `_validate_run_id()` before any file access
- The dashboard uses the same validation
- No user-supplied file paths are accepted
- Only the `.orchestrator/runs/` directory is accessed

### 8.6 No Arbitrary Execution

- The dashboard never executes tool code
- The dashboard never executes workflow code
- The dashboard never executes agent code
- The dashboard never executes subprocesses
- The dashboard only reads JSON/JSONL files

### 8.7 Content Security

- HTML is generated server-side (no user input in templates)
- API responses are JSON-serialized (no XSS through response data)
- JavaScript uses `textContent` not `innerHTML` for user data
- No inline event handlers
- No `eval()` in JavaScript

---

## 9. Data Access Layer

The dashboard reads data through the existing orchestrator functions. It does NOT implement its own file reading.

### 9.1 Functions Used

```python
# From persist.py
from .persist import (
    list_runs,              # GET /api/runs
    load_state,             # GET /api/runs/{run_id}
    load_evidence,          # GET /api/runs/{run_id}/evidence
    get_persisted_run,      # Single run lookup
    find_interrupted_runs,  # GET /api/interrupted
    _validate_run_id,       # Path traversal prevention
)

# From discovery.py
from .discovery import (
    discover_all,           # GET /api/tools
)

# From config.py
from .config import (
    load_config,            # GET /api/status
)

# From policy.py
from .policy import (
    load_policy,            # GET /api/policies/{mode}
)

# From evidence.py
from .evidence import (
    redact,                 # Secret redaction (inherited from persistence)
)

# From report.py
from .report import (
    report_dict,            # Run detail formatting
)
```

### 9.2 No New Read Functions Needed

The existing persistence layer already provides all required read operations. The dashboard adds zero new data access logic.

---

## 10. Run Lifecycle Visualization

### 10.1 Phase Timeline

For a run detail view, the dashboard shows the phase progression:

```
CREATED → BOOTSTRAPPING → CHECKING → EXECUTING → GATING → VERIFYING → COMPLETED
```

With color coding:
- Completed phases: green
- Current phase: blue
- Failed phases: red
- Future phases: gray

### 10.2 Tool Call Timeline

Each tool call is shown chronologically:

```
14:30:22  agent-error-log.check()     PASS    1.2s
14:30:24  agent-decision-log.check()  PASS    0.8s
14:30:25  agent-diff-gate.check()     PASS    2.1s
14:30:28  agent-sandbox.run()         BLOCKED (UNSUPPORTED on Windows)
```

### 10.3 Policy Decision Timeline

Policy decisions are shown inline with tool calls:

```
14:30:22  [POLICY] diff_gate = required (mandatory, base)
14:30:22  [POLICY] sandbox = mandatory (mandatory, base)
14:30:28  [POLICY BLOCKED] sandbox unavailable → workflow blocked
```

---

## 11. Multi-Agent Visualization

### 11.1 Agent Activity (from Evidence)

The dashboard shows agent activity by filtering evidence entries with `agent:` tools:

```
14:30:22  [AGENT] reviewer-abc123 started task "review code"
14:30:25  [AGENT] reviewer-abc123 completed (0.8s, tokens=0)
14:30:26  [AGENT] security-def456 started task "security scan"
14:30:30  [AGENT] security-def456 completed (1.2s, tokens=0)
```

### 11.2 Agent Identity Display

For each agent seen in evidence:
- Agent ID
- Role (planner, developer, reviewer, security, researcher, documenter, tester)
- Tasks assigned
- Tasks completed
- Total duration

### 11.3 Provider Display

The dashboard shows which provider was used (from evidence/config):
- Provider name (ollama, freebuff, cli, none)
- Provider status (AVAILABLE, UNAVAILABLE, ERROR, TIMEOUT)
- No API keys or credentials displayed

---

## 12. Tool Health Visualization

### 12.1 Tool Status Display

Each tool is shown with:
- Name
- Status (AVAILABLE, MISSING, UNSUPPORTED, ERROR)
- Version
- Platform support
- Capabilities
- Health check result

### 12.2 Platform Awareness

- agent-sandbox shows "UNSUPPORTED on Windows" when on Windows
- This is documented, not a bug
- On Linux, sandbox shows AVAILABLE if healthy

---

## 13. Configuration

### 13.1 Dashboard Configuration

The dashboard reads configuration from the existing `.orchestrator/config` system.

Optional dashboard-specific config keys (in `.orchestrator/config`):

```
dashboard_port = 8520
dashboard_host = 127.0.0.1
dashboard_refresh = 5
```

These are optional. Defaults are used if not specified.

### 13.2 Validation

All dashboard config values are validated:
- `dashboard_port`: integer, 1024-65535
- `dashboard_host`: string, must be valid IP or hostname
- `dashboard_refresh`: integer, 1-60 (seconds)

Invalid values fall back to defaults.

---

## 14. Failure Behavior

### 14.1 Server Failures

| Failure | Behavior |
|---------|----------|
| Port in use | Print error, exit with code 1 |
| Workspace not found | Print error, exit with code 1 |
| Invalid config | Print error, exit with code 1 |
| KeyboardInterrupt | Graceful shutdown, exit code 0 |
| Unhandled exception | Log error, return 500 JSON response |

### 14.2 Data Failures

| Failure | Behavior |
|---------|----------|
| Missing run index | Return empty runs list |
| Corrupt run state | Return error for that run |
| Missing evidence | Return empty evidence list |
| Corrupt evidence line | Skip line, mark as CORRUPTED |
| Missing tool directory | Report as MISSING in tool list |

### 14.3 Never

- Never crash the server on bad data
- Never serve unredacted secrets
- Never execute code from persisted data
- Never modify persisted data
- Never expose the filesystem beyond `.orchestrator/runs/`

---

## 15. Testing Strategy

### 15.1 Unit Tests

Test file: `tests/test_dashboard.py`

Tests:
1. Server starts and stops cleanly
2. GET / returns HTML (200)
3. GET /api/health returns healthy
4. GET /api/runs returns run list
5. GET /api/runs with no runs returns empty list
6. GET /api/runs/{run_id} returns run detail
7. GET /api/runs/{invalid_id} returns 404
8. GET /api/runs/{path_traversal_id} returns 404
9. GET /api/runs/{run_id}/evidence returns evidence
10. GET /api/tools returns tool status
11. GET /api/status returns system status
12. GET /api/interrupted returns interrupted runs
13. GET /api/policies/solo returns solo policies
14. GET /api/policies/invalid returns error
15. POST requests are rejected (405)
16. Unknown paths return 404
17. Empty workspace handled gracefully
18. Corrupt state handled gracefully
19. Corrupt evidence handled gracefully
20. Secret redaction applied to served data
21. Run ID validation prevents path traversal
22. Port configuration works
23. Host configuration works
24. Auto-refresh JavaScript present in HTML
25. HTML contains all view tabs

### 15.2 Integration Tests

1. Start server → fetch runs → stop server
2. Persist a run → fetch via API → verify data matches
3. Persist evidence → fetch via API → verify entries match
4. Multiple runs → verify ordering (most recent first)
5. Tool discovery → fetch via API → verify statuses match

### 15.3 Security Tests

1. Path traversal in run_id is rejected
2. Path traversal in URL path is rejected
3. POST/PUT/DELETE requests are rejected
4. Port 0 is rejected
5. Invalid host is rejected
6. Secrets not in HTML output
7. Secrets not in API responses
8. No eval/exec in JavaScript
9. No shell=True in server code
10. Localhost-only binding verified

### 15.4 Regression Tests

1. Existing CLI commands still work
2. Existing tests still pass
3. Zero external dependencies maintained
4. Seven tool repositories untouched

---

## 16. Compatibility

### 16.1 Backwards Compatibility

- All existing CLI commands unchanged
- All existing tests unchanged
- All existing data formats unchanged
- All existing adapters unchanged
- All existing engines unchanged
- Dashboard is purely additive

### 16.2 Persistence Compatibility

The dashboard reads the exact same files that the CLI reads:
- `.orchestrator/runs/index.json`
- `.orchestrator/runs/{run_id}/state.json`
- `.orchestrator/runs/{run_id}/evidence.jsonl`

No new persistence format is introduced.

### 16.3 Platform Compatibility

- Works on Windows (where the dashboard is being developed)
- Works on Linux (where agent-sandbox is available)
- Works on macOS (expected, stdlib-only)
- Uses `pathlib.Path` throughout (cross-platform)

---

## 17. Implementation Plan

### Step 1: Create `dashboard.py`

Create the HTTP server module:
- `DashboardHandler` class extending `BaseHTTPRequestHandler`
- Route dispatch
- JSON response helpers
- Error handling
- CORS headers (localhost only)

### Step 2: Create `dashboard_ui.py`

Create the HTML rendering module:
- Single-page HTML with inline CSS and JS
- Tab navigation (Runs, Tools, Status, Policies)
- Run list table
- Run detail view
- Evidence timeline
- Auto-refresh logic
- Fetch-based API calls

### Step 3: Add CLI command

Add `orchestrator dashboard` command to `cli.py`:
- Argument parsing
- Server startup
- Browser opening (optional)
- Graceful shutdown

### Step 4: Write tests

Create `tests/test_dashboard.py`:
- Server start/stop tests
- API endpoint tests
- Security tests
- Regression tests

### Step 5: Run full test suite

Verify no regressions:
- All existing tests pass
- New dashboard tests pass
- Zero external dependencies
- shell=True = 0

### Step 6: Create implementation report

Document the implementation.

---

## 18. Estimated Scope

| Metric | Value |
|--------|-------|
| New files | 2 |
| Modified files | 1 (cli.py) |
| New lines | ~900 |
| New tests | ~40 |
| Total test count | ~885 |
| Implementation time | ~2 hours |
| Dependencies added | 0 |

---

## 19. Architectural Decision

### Question: Is the existing architecture sufficient?

### Answer: **A) Yes — the dashboard can be implemented additively.**

The existing persistence format provides all the data the dashboard needs. The existing read functions in `persist.py`, `discovery.py`, `config.py`, and `recovery.py` are sufficient. No new data access is required.

The dashboard is a pure **read layer** over existing data, served through Python's `http.server`. It requires:
- No new persistence format
- No new data model
- No changes to the workflow engine
- No changes to the policy engine
- No changes to the evidence system
- No changes to the adapter layer
- No changes to the agent system
- No changes to the provider system
- No changes to the seven tool repositories

The only modification is adding a `dashboard` subcommand to the CLI, which is a one-line addition to the command dispatch table.

### Recommendation

Proceed with implementation. The dashboard is the smallest possible increment over the existing architecture that provides significant new value (visual monitoring) without any architectural risk.

---

## 20. Future Considerations (NOT for v1)

These are explicitly deferred:
- WebSocket for real-time streaming
- Authentication for remote access
- Run creation through the dashboard
- Run cancellation through the dashboard
- Run recovery through the dashboard
- Dark mode
- Mobile responsiveness
- Charts and graphs
- Export functionality
- Multi-user support
- Database backend

Each of these would require separate design and authorization.

---

*Design document created: 2026-08-25*
*Status: PENDING REVIEW*
*Author: Buffy (Codebuff)*
