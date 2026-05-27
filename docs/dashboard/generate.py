"""Generate a static Integration Tests Dashboard HTML page.

Fetches the last 10 workflow runs from configured GitHub repos
and produces an index.html with data embedded as JSON.
No client-side API calls or PAT tokens required for viewers.
"""

import json
import os
import sys
from datetime import datetime, timezone
from html import escape
from urllib.request import Request, urlopen
from urllib.error import HTTPError


WORKFLOWS = [
    {
        "id": "iot-cli-int-test",
        "title": "Azure IoT CLI Extension \u2014 Integration Tests",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "same_repo": True,
    },
    {
        "id": "iot-ops-int-test",
        "title": "Azure IoT Ops CLI Extension \u2014 Integration Tests",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "same_repo": False,
    },
]


def fetch_runs(repo: str, workflow_file: str, token: str) -> list[dict]:
    """Fetch the last 10 completed workflow runs from GitHub API."""
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow_file}/runs?per_page=10&status=completed"
    )
    req = Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data.get("workflow_runs", [])
    except HTTPError as e:
        print(f"ERROR: Failed to fetch {repo}/{workflow_file}: {e.code} {e.reason}")
        return None


def sanitize_run(run: dict) -> dict:
    """Extract and HTML-escape relevant fields from a workflow run."""
    return {
        "conclusion": escape(run.get("conclusion") or "unknown"),
        "run_number": run.get("run_number", 0),
        "name": escape(run.get("name") or ""),
        "head_branch": escape(run.get("head_branch") or ""),
        "html_url": escape(run.get("html_url") or "#"),
        "created_at": escape(run.get("created_at") or ""),
        "updated_at": escape(run.get("updated_at") or ""),
        "event": escape(run.get("event") or ""),
    }


def generate_dashboard_data(pat: str, gh_token: str) -> dict:
    """Fetch data for all workflows and return structured dashboard data.

    Uses pat (DASHBOARD_PAT) for all repos. If pat fails for cross-repo
    requests, those repos show an error.
    For same-repo workflows, falls back to gh_token (GITHUB_TOKEN).
    """
    workflows_data = []
    any_failure = False

    for wf in WORKFLOWS:
        token = pat or gh_token
        runs = fetch_runs(wf["repo"], wf["workflowFile"], token)

        if runs is None and pat and gh_token and wf["same_repo"]:
            print(f"  Retrying {wf['repo']} with GITHUB_TOKEN (PAT may be expired)...")
            runs = fetch_runs(wf["repo"], wf["workflowFile"], gh_token)

        if runs is None:
            any_failure = True
            error_msg = f"Failed to fetch data from {wf['repo']}"
            if not wf["same_repo"]:
                error_msg += " — DASHBOARD_PAT may have expired. Please renew the secret."
            workflows_data.append({
                "id": wf["id"],
                "title": escape(wf["title"]),
                "repo": escape(wf["repo"]),
                "workflowFile": escape(wf["workflowFile"]),
                "runs": [],
                "error": error_msg,
            })
        else:
            workflows_data.append({
                "id": wf["id"],
                "title": escape(wf["title"]),
                "repo": escape(wf["repo"]),
                "workflowFile": escape(wf["workflowFile"]),
                "runs": [sanitize_run(r) for r in runs],
                "error": None,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflows": workflows_data,
        "fetch_errors": any_failure,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Integration Tests Dashboard</title>
  <style>
    :root {
      --bg: #ffffff;
      --surface: #f6f8fa;
      --border: #d0d7de;
      --text: #1f2328;
      --text-muted: #656d76;
      --success: #1a7f37;
      --failure: #cf222e;
      --in-progress: #9a6700;
      --cancelled: #656d76;
      --link: #0969da;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
    }

    .header {
      text-align: center;
      margin-bottom: 32px;
    }

    .header h1 {
      font-size: 28px;
      font-weight: 600;
      margin-bottom: 8px;
    }

    .header p {
      color: var(--text-muted);
      font-size: 14px;
    }

    .dashboard {
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 32px;
    }

    .workflow-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
    }

    .workflow-card h2 {
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 4px;
    }

    .workflow-card .subtitle {
      color: var(--text-muted);
      font-size: 13px;
      margin-bottom: 20px;
    }

    .workflow-card .subtitle a {
      color: var(--link);
      text-decoration: none;
    }

    .workflow-card .subtitle a:hover { text-decoration: underline; }

    .chart-container {
      display: flex;
      align-items: flex-end;
      gap: 6px;
      height: 180px;
      padding: 0 8px;
      position: relative;
    }

    .bar-wrapper {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      height: 100%;
      justify-content: flex-end;
      position: relative;
      cursor: pointer;
      min-width: 40px;
      max-width: 100px;
    }

    .bar {
      width: 100%;
      max-width: 60px;
      min-height: 20px;
      height: 100%;
      border-radius: 4px 4px 0 0;
      transition: opacity 0.2s;
      position: relative;
    }

    .bar-wrapper:hover .bar { opacity: 0.8; }

    .bar.success { background: var(--success); }
    .bar.failure { background: var(--failure); }
    .bar.in_progress { background: var(--in-progress); }
    .bar.cancelled { background: var(--cancelled); }

    .bar-label {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 6px;
      white-space: nowrap;
      text-align: center;
      width: 100%;
    }

    .bar-branch {
      font-size: 10px;
      color: var(--link);
      font-weight: 500;
      display: block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tooltip {
      display: none;
      position: absolute;
      bottom: calc(100% + 10px);
      left: 50%;
      transform: translateX(-50%);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 13px;
      white-space: nowrap;
      z-index: 100;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      min-width: 220px;
    }

    .bar-wrapper:hover .tooltip { display: block; }

    .tooltip .tt-row {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 4px;
    }

    .tooltip .tt-row:last-child { margin-bottom: 0; }

    .tooltip .tt-label { color: var(--text-muted); }

    .tooltip .tt-value { font-weight: 500; }

    .tooltip .tt-status {
      display: inline-block;
      padding: 1px 8px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
    }

    .tt-status.success { background: rgba(63,185,80,0.2); color: var(--success); }
    .tt-status.failure { background: rgba(248,81,73,0.2); color: var(--failure); }
    .tt-status.in_progress { background: rgba(210,153,34,0.2); color: var(--in-progress); }
    .tt-status.cancelled { background: rgba(139,148,158,0.2); color: var(--cancelled); }

    .legend {
      display: flex;
      gap: 16px;
      margin-top: 16px;
      justify-content: center;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }

    .loading {
      text-align: center;
      color: var(--text-muted);
      padding: 40px;
      font-size: 14px;
    }

    .error {
      color: var(--failure);
      font-size: 14px;
      text-align: center;
      padding: 20px;
    }

    .last-updated {
      text-align: center;
      color: var(--text-muted);
      font-size: 12px;
      margin-top: 16px;
    }

    @media (max-width: 600px) {
      .chart-container { gap: 3px; height: 140px; }
      .bar-wrapper { min-width: 28px; }
      .bar-label { font-size: 9px; }
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>Integration Tests Dashboard</h1>
    <p>Azure IoT CLI Extensions — Last 10 workflow runs</p>
  </div>

  <div class="dashboard" id="dashboard"></div>
  <div class="last-updated" id="lastUpdated"></div>

  <script type="application/json" id="dashboardData">
__DASHBOARD_DATA__
  </script>

  <script>
    const DATA = JSON.parse(document.getElementById('dashboardData').textContent);

    function conclusionClass(conclusion) {
      if (conclusion === 'success') return 'success';
      if (conclusion === 'failure') return 'failure';
      if (conclusion === 'cancelled') return 'cancelled';
      return 'in_progress';
    }

    function formatDate(dateStr) {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    function formatDateTime(dateStr) {
      const d = new Date(dateStr);
      return d.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    }

    function durationStr(createdAt, updatedAt) {
      const ms = new Date(updatedAt) - new Date(createdAt);
      const mins = Math.floor(ms / 60000);
      const secs = Math.floor((ms % 60000) / 1000);
      if (mins > 0) return `${mins}m ${secs}s`;
      return `${secs}s`;
    }

    function extractDetail(name, repo) {
      if (repo.includes('azure-iot-cli-extension')) {
        const match = name.match(/\(([^)]+)\)/);
        return match ? match[1] : '';
      }
      if (repo.includes('azure-iot-ops-cli-extension')) {
        const match = name.match(/\[([^\]]+)\]/);
        return match ? match[1] : '';
      }
      return '';
    }

    function renderChart(workflow) {
      const card = document.createElement('div');
      card.className = 'workflow-card';

      const repoUrl = `https://github.com/${workflow.repo}/actions/workflows/${workflow.workflowFile}`;

      card.innerHTML = `
        <h2>${workflow.title}</h2>
        <div class="subtitle">
          <a href="${repoUrl}" target="_blank">${workflow.repo}</a> · ${workflow.workflowFile}
        </div>
      `;

      if (workflow.error) {
        card.innerHTML += `<div class="error">${workflow.error}</div>`;
        return card;
      }

      if (workflow.runs.length === 0) {
        card.innerHTML += '<div class="loading">No completed runs found</div>';
        return card;
      }

      const chart = document.createElement('div');
      chart.className = 'chart-container';

      // Show oldest first (left to right = old to new)
      const sortedRuns = [...workflow.runs].reverse();

      sortedRuns.forEach(run => {
        const cls = conclusionClass(run.conclusion);
        const detail = extractDetail(run.name, workflow.repo);
        const duration = durationStr(run.created_at, run.updated_at);

        const wrapper = document.createElement('div');
        wrapper.className = 'bar-wrapper';
        wrapper.onclick = () => window.open(run.html_url, '_blank');

        // Build tooltip with textContent for safety
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.innerHTML = `
          <div class="tt-row">
            <span class="tt-label">Status</span>
            <span class="tt-status ${cls}">${run.conclusion}</span>
          </div>
          <div class="tt-row">
            <span class="tt-label">Run</span>
            <span class="tt-value">#${run.run_number}</span>
          </div>
          ${detail ? `<div class="tt-row">
            <span class="tt-label">Details</span>
            <span class="tt-value">${detail}</span>
          </div>` : ''}
          <div class="tt-row">
            <span class="tt-label">Branch</span>
            <span class="tt-value">${run.head_branch}</span>
          </div>
          <div class="tt-row">
            <span class="tt-label">Duration</span>
            <span class="tt-value">${duration}</span>
          </div>
          <div class="tt-row">
            <span class="tt-label">Date</span>
            <span class="tt-value">${formatDateTime(run.created_at)}</span>
          </div>
          <div class="tt-row">
            <span class="tt-label">Trigger</span>
            <span class="tt-value">${run.event}</span>
          </div>
        `;

        const bar = document.createElement('div');
        bar.className = `bar ${cls}`;

        const label = document.createElement('div');
        label.className = 'bar-label';
        label.innerHTML = `${formatDate(run.created_at)}<br/><span class="bar-branch">${run.head_branch}</span>`;

        wrapper.appendChild(tooltip);
        wrapper.appendChild(bar);
        wrapper.appendChild(label);
        chart.appendChild(wrapper);
      });

      card.appendChild(chart);

      // Legend
      const legend = document.createElement('div');
      legend.className = 'legend';
      legend.innerHTML = `
        <div class="legend-item"><div class="legend-dot" style="background:var(--success)"></div> Success</div>
        <div class="legend-item"><div class="legend-dot" style="background:var(--failure)"></div> Failure</div>
        <div class="legend-item"><div class="legend-dot" style="background:var(--cancelled)"></div> Cancelled</div>
      `;
      card.appendChild(legend);

      return card;
    }

    // Render dashboard
    const dashboard = document.getElementById('dashboard');
    DATA.workflows.forEach(wf => {
      dashboard.appendChild(renderChart(wf));
    });

    // Show generation timestamp
    const genTime = new Date(DATA.generated_at);
    document.getElementById('lastUpdated').textContent =
      `Dashboard generated: ${genTime.toLocaleString()} (auto-refreshes every 2 hours)`;
  </script>
</body>
</html>"""


def main():
    # DASHBOARD_PAT: PAT with Actions:read for cross-repo access (renew every 90 days)
    # GITHUB_TOKEN: automatic workflow token for same-repo fallback (never expires)
    pat = os.environ.get("DASHBOARD_PAT", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not pat and not gh_token:
        print("ERROR: At least one of DASHBOARD_PAT or GITHUB_TOKEN must be set")
        sys.exit(1)

    if not pat:
        print("WARNING: DASHBOARD_PAT not set. Cross-repo data will not be available.")
        print("  Only same-repo (azure-iot-cli-extension) data will be shown.")

    output_dir = os.environ.get("OUTPUT_DIR", ".")
    output_file = os.path.join(output_dir, "index.html")

    print("Fetching dashboard data...")
    data = generate_dashboard_data(pat, gh_token)

    if data["fetch_errors"]:
        # Check if ALL workflows failed
        all_failed = all(wf["error"] for wf in data["workflows"])
        if all_failed:
            print("ERROR: All workflow data fetches failed. Not generating dashboard.")
            sys.exit(1)
        else:
            print("WARNING: Some workflow data fetches failed. Generating partial dashboard.")

    # Serialize data as JSON and embed in HTML
    data_json = json.dumps(data, indent=2)
    html = HTML_TEMPLATE.replace("__DASHBOARD_DATA__", data_json)

    os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(html)

    print(f"Dashboard generated: {output_file}")
    for wf in data["workflows"]:
        status = "ERROR" if wf["error"] else f"{len(wf['runs'])} runs"
        print(f"  {wf['repo']}: {status}")


if __name__ == "__main__":
    main()
