"""Dashboard UI — HTML rendering for the single-page web dashboard.

Generates a self-contained HTML page with inline CSS and vanilla JavaScript.
No external dependencies, no build step, no CDN, no frameworks.

Design: PHASE_DASHBOARD_DESIGN.md
"""

from __future__ import annotations


def render_dashboard(refresh_interval: int = 5) -> str:
    """Render the complete dashboard HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orchestrate Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f6f8; color: #1a1a2e; font-size: 14px; }}

/* Header */
.header {{ background: #1a1a2e; color: #fff; padding: 12px 24px;
           display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 16px; font-weight: 600; letter-spacing: 0.5px; }}
.header .meta {{ font-size: 12px; color: #8892b0; }}
.header .refresh-btn {{ background: #16213e; border: 1px solid #0f3460;
                         color: #e2e8f0; padding: 4px 12px; border-radius: 4px;
                         cursor: pointer; font-size: 12px; }}
.header .refresh-btn:hover {{ background: #0f3460; }}

/* Tabs */
.tabs {{ background: #fff; border-bottom: 1px solid #dde; padding: 0 24px;
         display: flex; gap: 0; }}
.tab {{ padding: 10px 20px; cursor: pointer; border-bottom: 2px solid transparent;
         color: #666; font-size: 13px; font-weight: 500; transition: all 0.15s; }}
.tab:hover {{ color: #1a1a2e; background: #f8f9fa; }}
.tab.active {{ color: #0f3460; border-bottom-color: #0f3460; }}

/* Content */
.content {{ max-width: 1200px; margin: 0 auto; padding: 20px 24px; }}
.panel {{ display: none; }}
.panel.active {{ display: block; }}

/* Tables */
table {{ width: 100%; border-collapse: collapse; background: #fff;
         border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
th {{ background: #f0f2f5; text-align: left; padding: 10px 14px;
      font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
      color: #555; border-bottom: 1px solid #dde; }}
td {{ padding: 10px 14px; border-bottom: 1px solid #eef; font-size: 13px; }}
tr:last-child td {{ border-bottom: none; }}
tr:hover {{ background: #f8f9fb; }}

/* Status badges */
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 600; text-transform: uppercase; }}
.badge-pass {{ background: #d4edda; color: #155724; }}
.badge-fail {{ background: #f8d7da; color: #721c24; }}
.badge-blocked {{ background: #fff3cd; color: #856404; }}
.badge-running {{ background: #cce5ff; color: #004085; }}
.badge-cancelled {{ background: #e2e3e5; color: #383d41; }}
.badge-unsupported {{ background: #e2e3e5; color: #383d41; }}
.badge-available {{ background: #d4edda; color: #155724; }}
.badge-missing {{ background: #f8d7da; color: #721c24; }}
.badge-error {{ background: #f8d7da; color: #721c24; }}

/* Detail cards */
.card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
         padding: 16px 20px; margin-bottom: 16px; }}
.card h3 {{ font-size: 14px; font-weight: 600; color: #1a1a2e;
            margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #eef; }}
.card .row {{ display: flex; gap: 24px; margin-bottom: 6px; }}
.card .label {{ color: #888; min-width: 140px; font-size: 12px; }}
.card .value {{ color: #1a1a2e; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }}

/* Timeline */
.timeline {{ position: relative; padding-left: 24px; }}
.timeline::before {{ content: ''; position: absolute; left: 8px; top: 0; bottom: 0;
                      width: 2px; background: #dde; }}
.timeline-entry {{ position: relative; margin-bottom: 12px; padding: 8px 12px;
                    background: #fff; border-radius: 6px;
                    box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
.timeline-entry::before {{ content: ''; position: absolute; left: -20px; top: 12px;
                            width: 10px; height: 10px; border-radius: 50%;
                            background: #0f3460; border: 2px solid #fff; }}
.timeline-entry.pass::before {{ background: #28a745; }}
.timeline-entry.fail::before {{ background: #dc3545; }}
.timeline-entry.blocked::before {{ background: #ffc107; }}
.timeline-entry .ts {{ font-size: 11px; color: #888; font-family: monospace; }}
.timeline-entry .action {{ font-weight: 600; font-size: 13px; }}
.timeline-entry .detail {{ font-size: 12px; color: #666; margin-top: 4px; }}

/* Policy table */
.policy-mandatory {{ font-weight: 600; }}
.policy-optional {{ color: #888; }}

/* Summary cards */
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px; margin-bottom: 20px; }}
.summary-card {{ background: #fff; border-radius: 8px; padding: 16px;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.08); text-align: center; }}
.summary-card .number {{ font-size: 28px; font-weight: 700; color: #0f3460; }}
.summary-card .label {{ font-size: 12px; color: #888; margin-top: 4px; }}

/* Empty state */
.empty {{ text-align: center; padding: 40px; color: #888; }}
.empty h3 {{ margin-bottom: 8px; }}

/* Clickable rows */
tr.clickable {{ cursor: pointer; }}
tr.clickable:hover {{ background: #e8ecf1; }}

/* Back link */
.back {{ display: inline-block; margin-bottom: 16px; color: #0f3460;
         cursor: pointer; font-size: 13px; text-decoration: none; }}
.back:hover {{ text-decoration: underline; }}

/* Loading */
.loading {{ text-align: center; padding: 40px; color: #888; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>ORCHESTRATE</h1>
    <span class="meta">Dashboard v{_version_str()}</span>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <span class="meta" id="last-update"></span>
    <button class="refresh-btn" onclick="refreshAll()">&#x21bb; Refresh</button>
  </div>
</div>

<div class="tabs">
  <div class="tab active" data-panel="runs">Runs</div>
  <div class="tab" data-panel="tools">Tools</div>
  <div class="tab" data-panel="status">Status</div>
  <div class="tab" data-panel="policies">Policies</div>
</div>

<div class="content">
  <!-- Runs Panel -->
  <div class="panel active" id="panel-runs">
    <div id="runs-content"><div class="loading">Loading...</div></div>
  </div>

  <!-- Run Detail Panel -->
  <div class="panel" id="panel-run-detail">
    <div id="run-detail-content"><div class="loading">Loading...</div></div>
  </div>

  <!-- Evidence Panel -->
  <div class="panel" id="panel-evidence">
    <div id="evidence-content"><div class="loading">Loading...</div></div>
  </div>

  <!-- Tools Panel -->
  <div class="panel" id="panel-tools">
    <div id="tools-content"><div class="loading">Loading...</div></div>
  </div>

  <!-- Status Panel -->
  <div class="panel" id="panel-status">
    <div id="status-content"><div class="loading">Loading...</div></div>
  </div>

  <!-- Policies Panel -->
  <div class="panel" id="panel-policies">
    <div id="policies-content"><div class="loading">Loading...</div></div>
  </div>
</div>

<script>
// ── Config ──────────────────────────────────────────────────────────
var REFRESH_MS = {refresh_interval * 1000};
var refreshTimer = null;

// ── Tab navigation ──────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(function(tab) {{
  tab.addEventListener('click', function() {{
    document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.querySelectorAll('.panel').forEach(function(p) {{ p.classList.remove('active'); }});
    tab.classList.add('active');
    var panelId = 'panel-' + tab.getAttribute('data-panel');
    var panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
    loadPanelData(tab.getAttribute('data-panel'));
  }});
}});

function showPanel(name) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.panel').forEach(function(p) {{ p.classList.remove('active'); }});
  var tab = document.querySelector('.tab[data-panel="' + name + '"]');
  if (tab) tab.classList.add('active');
  var panel = document.getElementById('panel-' + name);
  if (panel) panel.classList.add('active');
}}

// ── Fetch helper ────────────────────────────────────────────────────
function api(path) {{
  return fetch('/api/' + path)
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      if (!data.ok) throw new Error(data.error || 'API error');
      return data.data;
    }});
}}

// ── Status badge ────────────────────────────────────────────────────
function badge(status) {{
  var cls = 'badge';
  var s = (status || '').toUpperCase();
  if (s === 'PASS' || s === 'AVAILABLE' || s === 'COMPLETED') cls += ' badge-pass';
  else if (s === 'FAIL' || s === 'ERROR' || s === 'MISSING') cls += ' badge-fail';
  else if (s === 'BLOCKED') cls += ' badge-blocked';
  else if (s === 'RUNNING' || s === 'EXECUTING') cls += ' badge-running';
  else if (s === 'CANCELLED') cls += ' badge-cancelled';
  else if (s === 'UNSUPPORTED') cls += ' badge-unsupported';
  else cls += ' badge-running';
  return '<span class="' + cls + '">' + escapeHtml(status || '?') + '</span>';
}}

function escapeHtml(text) {{
  var d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}}

// ── Load panel data ─────────────────────────────────────────────────
function loadPanelData(name) {{
  if (name === 'runs') loadRuns();
  else if (name === 'tools') loadTools();
  else if (name === 'status') loadStatus();
  else if (name === 'policies') loadPolicies();
}}

// ── Runs ────────────────────────────────────────────────────────────
function loadRuns() {{
  var el = document.getElementById('runs-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  api('runs').then(function(data) {{
    if (!data.runs || data.runs.length === 0) {{
      el.innerHTML = '<div class="empty"><h3>No runs yet</h3><p>Run <code>orchestrator run</code> to start.</p></div>';
      return;
    }}
    var html = '<div class="summary">';
    html += '<div class="summary-card"><div class="number">' + data.total + '</div><div class="label">Total Runs</div></div>';
    var pass = 0, fail = 0, blocked = 0;
    data.runs.forEach(function(r) {{
      if (r.status === 'PASS') pass++;
      else if (r.status === 'FAIL') fail++;
      else if (r.status === 'BLOCKED') blocked++;
    }});
    html += '<div class="summary-card"><div class="number" style="color:#28a745">' + pass + '</div><div class="label">Passed</div></div>';
    html += '<div class="summary-card"><div class="number" style="color:#dc3545">' + fail + '</div><div class="label">Failed</div></div>';
    html += '<div class="summary-card"><div class="number" style="color:#856404">' + blocked + '</div><div class="label">Blocked</div></div>';
    html += '</div>';

    html += '<table><thead><tr>';
    html += '<th>Run ID</th><th>Workflow</th><th>Mode</th><th>Status</th><th>Started</th><th>Tools</th><th>Evidence</th>';
    html += '</tr></thead><tbody>';
    data.runs.forEach(function(r) {{
      html += '<tr class="clickable" onclick="showRunDetail(\\'' + r.run_id + '\\')">';
      html += '<td style="font-family:monospace;font-size:12px">' + escapeHtml(r.run_id) + '</td>';
      html += '<td>' + escapeHtml(r.workflow) + '</td>';
      html += '<td>' + escapeHtml(r.mode) + '</td>';
      html += '<td>' + badge(r.status) + '</td>';
      html += '<td style="font-size:12px">' + escapeHtml(r.started_at || '-') + '</td>';
      html += '<td>' + r.tool_call_count + '</td>';
      html += '<td>' + r.evidence_count + '</td>';
      html += '</tr>';
    }});
    html += '</tbody></table>';
    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading runs</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

// ── Run Detail ──────────────────────────────────────────────────────
function showRunDetail(runId) {{
  showPanel('run-detail');
  var el = document.getElementById('run-detail-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  api('runs/' + runId).then(function(data) {{
    var html = '<a class="back" onclick="showRuns()">&larr; Back to runs</a>';

    // Summary card
    html += '<div class="card"><h3>Run Summary</h3>';
    html += '<div class="row"><span class="label">Run ID</span><span class="value">' + escapeHtml(data.run_id) + '</span></div>';
    html += '<div class="row"><span class="label">Workflow</span><span class="value">' + escapeHtml(data.workflow) + '</span></div>';
    html += '<div class="row"><span class="label">Mode</span><span class="value">' + escapeHtml(data.mode) + '</span></div>';
    html += '<div class="row"><span class="label">Phase</span><span class="value">' + escapeHtml(data.phase) + '</span></div>';
    html += '<div class="row"><span class="label">Status</span><span class="value">' + badge(data.final_status || 'RUNNING') + '</span></div>';
    html += '<div class="row"><span class="label">Started</span><span class="value">' + escapeHtml(data.started_at) + '</span></div>';
    html += '<div class="row"><span class="label">Ended</span><span class="value">' + escapeHtml(data.ended_at || '-') + '</span></div>';
    html += '</div>';

    // Tool calls
    if (data.tool_calls && data.tool_calls.length > 0) {{
      html += '<div class="card"><h3>Tool Calls (' + data.tool_calls.length + ')</h3>';
      html += '<div class="timeline">';
      data.tool_calls.forEach(function(tc) {{
        var cls = (tc.status || '').toLowerCase();
        html += '<div class="timeline-entry ' + cls + '">';
        html += '<div class="ts">' + escapeHtml(tc.timestamp || '') + '</div>';
        html += '<div class="action">' + escapeHtml(tc.tool) + '.' + escapeHtml(tc.operation) + ' ' + badge(tc.status) + '</div>';
        html += '<div class="detail">exit=' + tc.exit_code + '  duration=' + tc.duration + 's';
        if (tc.error) html += '  error=' + escapeHtml(tc.error);
        html += '</div>';
        html += '</div>';
      }});
      html += '</div></div>';
    }}

    // Policy decisions
    if (data.policy_decisions && data.policy_decisions.length > 0) {{
      html += '<div class="card"><h3>Policy Decisions</h3>';
      html += '<table><thead><tr><th>Rule</th><th>Outcome</th><th>Mandatory</th><th>Reason</th></tr></thead><tbody>';
      data.policy_decisions.forEach(function(pd) {{
        html += '<tr>';
        html += '<td>' + escapeHtml(pd.rule) + '</td>';
        html += '<td>' + badge(pd.outcome) + '</td>';
        html += '<td>' + (pd.mandatory === 'True' ? 'Yes' : 'No') + '</td>';
        html += '<td style="font-size:12px">' + escapeHtml(pd.reason || '') + '</td>';
        html += '</tr>';
      }});
      html += '</tbody></table></div>';
    }}

    // Gate results
    if (data.gate_results && data.gate_results.length > 0) {{
      html += '<div class="card"><h3>Gate Results</h3>';
      html += '<table><thead><tr><th>Gate</th><th>Passed</th><th>Detail</th><th>Timestamp</th></tr></thead><tbody>';
      data.gate_results.forEach(function(g) {{
        html += '<tr>';
        html += '<td>' + escapeHtml(g.gate) + '</td>';
        html += '<td>' + (g.passed === 'True' ? badge('PASS') : badge('FAIL')) + '</td>';
        html += '<td style="font-size:12px">' + escapeHtml(g.detail || '') + '</td>';
        html += '<td style="font-size:12px">' + escapeHtml(g.timestamp || '') + '</td>';
        html += '</tr>';
      }});
      html += '</tbody></table></div>';
    }}

    // Observations
    if (data.observations && data.observations.length > 0) {{
      html += '<div class="card"><h3>Observations</h3>';
      data.observations.forEach(function(obs) {{
        html += '<div style="font-size:12px;color:#555;margin-bottom:4px;font-family:monospace">' + escapeHtml(obs) + '</div>';
      }});
      html += '</div>';
    }}

    // Evidence link
    html += '<div style="margin-top:12px"><a class="back" onclick="showEvidence(\\'' + data.run_id + '\\')">View Evidence Timeline &rarr;</a></div>';

    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading run</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

function showRuns() {{
  showPanel('runs');
  loadRuns();
}}

// ── Evidence ────────────────────────────────────────────────────────
function showEvidence(runId) {{
  showPanel('evidence');
  var el = document.getElementById('evidence-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  api('runs/' + runId + '/evidence').then(function(data) {{
    var html = '<a class="back" onclick="showRunDetail(\\'' + runId + '\\')">&larr; Back to run detail</a>';
    html += '<div class="card"><h3>Evidence Timeline (' + data.total + ' entries)</h3>';
    if (data.entries.length === 0) {{
      html += '<div class="empty"><h3>No evidence</h3></div>';
    }} else {{
      html += '<div class="timeline">';
      data.entries.forEach(function(e) {{
        var action = (e.action || '').toLowerCase();
        var cls = '';
        if (action.indexOf('fail') >= 0 || action.indexOf('error') >= 0) cls = 'fail';
        else if (action.indexOf('block') >= 0) cls = 'blocked';
        else if (action.indexOf('pass') >= 0 || action.indexOf('complet') >= 0) cls = 'pass';
        html += '<div class="timeline-entry ' + cls + '">';
        html += '<div class="ts">' + escapeHtml(e.timestamp || '') + '</div>';
        html += '<div class="action">' + escapeHtml(e.action || '?');
        if (e.tool) html += ' <span style="color:#0f3460">(' + escapeHtml(e.tool) + ')</span>';
        if (e.status) html += ' ' + badge(e.status);
        html += '</div>';
        if (e.detail) html += '<div class="detail">' + escapeHtml(e.detail) + '</div>';
        html += '</div>';
      }});
      html += '</div>';
    }}
    html += '</div>';
    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading evidence</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

// ── Tools ───────────────────────────────────────────────────────────
function loadTools() {{
  var el = document.getElementById('tools-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  api('tools').then(function(data) {{
    var s = data.summary;
    var html = '<div class="summary">';
    html += '<div class="summary-card"><div class="number">' + s.total + '</div><div class="label">Total Tools</div></div>';
    html += '<div class="summary-card"><div class="number" style="color:#28a745">' + s.available + '</div><div class="label">Available</div></div>';
    html += '<div class="summary-card"><div class="number" style="color:#856404">' + s.unsupported + '</div><div class="label">Unsupported</div></div>';
    html += '<div class="summary-card"><div class="number" style="color:#dc3545">' + (s.missing + s.error) + '</div><div class="label">Missing/Error</div></div>';
    html += '</div>';

    html += '<table><thead><tr>';
    html += '<th>Tool</th><th>Status</th><th>Version</th><th>Platform</th><th>Capabilities</th>';
    html += '</tr></thead><tbody>';
    data.tools.forEach(function(t) {{
      html += '<tr>';
      html += '<td style="font-weight:600">' + escapeHtml(t.name) + '</td>';
      html += '<td>' + badge(t.status) + '</td>';
      html += '<td style="font-size:12px">' + escapeHtml(t.version || '-') + '</td>';
      html += '<td style="font-size:12px">' + escapeHtml(t.platform_support) + '</td>';
      html += '<td style="font-size:11px">' + escapeHtml((t.capabilities || []).join(', ')) + '</td>';
      html += '</tr>';
    }});
    html += '</tbody></table>';
    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading tools</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

// ── Status ──────────────────────────────────────────────────────────
function loadStatus() {{
  var el = document.getElementById('status-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  Promise.all([api('status'), api('interrupted')]).then(function(results) {{
    var status = results[0];
    var interrupted = results[1];
    var html = '<div class="card"><h3>System</h3>';
    html += '<div class="row"><span class="label">Version</span><span class="value">' + escapeHtml(status.version) + '</span></div>';
    html += '<div class="row"><span class="label">Project</span><span class="value">' + escapeHtml(status.project) + '</span></div>';
    html += '<div class="row"><span class="label">Workspace</span><span class="value">' + escapeHtml(status.workspace || 'Not found') + '</span></div>';
    html += '<div class="row"><span class="label">Mode</span><span class="value">' + badge(status.mode) + '</span></div>';
    html += '<div class="row"><span class="label">Sandbox Required</span><span class="value">' + (status.sandbox_required ? 'Yes' : 'No') + '</span></div>';
    html += '<div class="row"><span class="label">Diff Gate Required</span><span class="value">' + (status.diff_gate_required ? 'Yes' : 'No') + '</span></div>';
    html += '<div class="row"><span class="label">Config File</span><span class="value">' + (status.has_config ? 'Found' : 'Missing') + '</span></div>';
    html += '<div class="row"><span class="label">Workflow File</span><span class="value">' + (status.has_workflow ? 'Found' : 'Missing') + '</span></div>';
    html += '</div>';

    // Interrupted runs
    html += '<div class="card"><h3>Interrupted Runs (' + interrupted.total + ')</h3>';
    if (interrupted.interrupted.length === 0) {{
      html += '<div style="padding:8px;color:#888">No interrupted runs.</div>';
    }} else {{
      html += '<table><thead><tr><th>Run ID</th><th>Workflow</th><th>Phase</th><th>Valid</th></tr></thead><tbody>';
      interrupted.interrupted.forEach(function(r) {{
        html += '<tr>';
        html += '<td style="font-family:monospace;font-size:12px">' + escapeHtml(r.run_id) + '</td>';
        html += '<td>' + escapeHtml(r.workflow) + '</td>';
        html += '<td>' + escapeHtml(r.phase) + '</td>';
        html += '<td>' + (r.valid ? badge('PASS') : badge('FAIL')) + '</td>';
        html += '</tr>';
      }});
      html += '</tbody></table>';
    }}
    html += '</div>';
    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading status</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

// ── Policies ────────────────────────────────────────────────────────
function loadPolicies() {{
  var el = document.getElementById('policies-content');
  el.innerHTML = '<div class="loading">Loading...</div>';
  var modes = ['solo', 'development', 'security', 'enterprise'];
  Promise.all(modes.map(function(m) {{ return api('policies/' + m); }})).then(function(results) {{
    // Collect all rule names
    var allRules = {{}};
    results.forEach(function(r) {{
      Object.keys(r.rules).forEach(function(name) {{ allRules[name] = true; }});
    }});
    var ruleNames = Object.keys(allRules).sort();

    var html = '<table><thead><tr><th>Rule</th>';
    modes.forEach(function(m) {{ html += '<th>' + m.charAt(0).toUpperCase() + m.slice(1) + '</th>'; }});
    html += '</tr></thead><tbody>';
    ruleNames.forEach(function(name) {{
      html += '<tr><td style="font-weight:600">' + escapeHtml(name) + '</td>';
      results.forEach(function(r) {{
        var rule = r.rules[name];
        if (rule) {{
          var cls = rule.mandatory ? 'policy-mandatory' : 'policy-optional';
          html += '<td class="' + cls + '">' + escapeHtml(rule.value) + '</td>';
        }} else {{
          html += '<td style="color:#ccc">-</td>';
        }}
      }});
      html += '</tr>';
    }});
    html += '</tbody></table>';
    html += '<div style="margin-top:12px;font-size:12px;color:#888">';
    html += 'Bold = mandatory rule. Non-bold = optional.';
    html += '</div>';
    el.innerHTML = html;
  }}).catch(function(err) {{
    el.innerHTML = '<div class="empty"><h3>Error loading policies</h3><p>' + escapeHtml(err.message) + '</p></div>';
  }});
}}

// ── Refresh ─────────────────────────────────────────────────────────
function refreshAll() {{
  var active = document.querySelector('.tab.active');
  if (active) loadPanelData(active.getAttribute('data-panel'));
  document.getElementById('last-update').textContent = 'Updated: ' + new Date().toLocaleTimeString();
}}

function startAutoRefresh() {{
  refreshTimer = setInterval(refreshAll, REFRESH_MS);
}}

// ── Init ────────────────────────────────────────────────────────────
loadRuns();
loadTools();
loadStatus();
loadPolicies();
startAutoRefresh();
refreshAll();
</script>

</body>
</html>"""


def _version_str() -> str:
    """Return the orchestrator version string."""
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "dev"
