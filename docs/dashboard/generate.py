"""Generate a static Integration Tests Dashboard HTML page.

Fetches the last 10 workflow runs per branch from configured GitHub repos
and produces an index.html deployed to GitHub Pages.
Layout: CLI ext dev + preview side by side, Ops CLI ext dev below.
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
        "id": "iot-cli-dev",
        "title": "IoT CLI Extension — dev",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": True,
    },
    {
        "id": "iot-cli-preview",
        "title": "IoT CLI Extension — preview",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "preview",
        "same_repo": True,
    },
    {
        "id": "iot-ops-dev",
        "title": "IoT Ops CLI Extension — dev",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": False,
    },
]


def fetch_runs(repo: str, workflow_file: str, token: str,
               branch: str | None = None) -> list[dict] | None:
    """Fetch the last 10 completed workflow runs from GitHub API."""
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow_file}/runs?per_page=10&status=completed"
    )
    if branch:
        url += f"&branch={branch}"

    req = Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data.get("workflow_runs", [])
    except HTTPError as e:
        print(f"ERROR: Failed to fetch {repo}/{workflow_file} "
              f"(branch={branch}): {e.code} {e.reason}")
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


def generate_dashboard_data(token: str, gh_token: str) -> dict:
    """Fetch data for all workflows and return structured dashboard data."""
    workflows_data = []
    any_failure = False

    for wf in WORKFLOWS:
        tk = token or gh_token
        runs = fetch_runs(wf["repo"], wf["workflowFile"], tk, wf.get("branch"))

        if runs is None and token and gh_token and wf["same_repo"]:
            print(f"  Retrying {wf['repo']} ({wf.get('branch')}) with GITHUB_TOKEN...")
            runs = fetch_runs(wf["repo"], wf["workflowFile"], gh_token, wf.get("branch"))

        if runs is None:
            any_failure = True
            error_msg = f"Failed to fetch data from {wf['repo']}"
            if not wf["same_repo"]:
                error_msg += " — check GitHub App token configuration."
            workflows_data.append({
                "id": wf["id"],
                "title": escape(wf["title"]),
                "repo": escape(wf["repo"]),
                "workflowFile": escape(wf["workflowFile"]),
                "branch": escape(wf.get("branch", "")),
                "runs": [],
                "error": error_msg,
            })
        else:
            workflows_data.append({
                "id": wf["id"],
                "title": escape(wf["title"]),
                "repo": escape(wf["repo"]),
                "workflowFile": escape(wf["workflowFile"]),
                "branch": escape(wf.get("branch", "")),
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

    .header { text-align: center; margin-bottom: 32px; }
    .header h1 { font-size: 28px; font-weight: 600; margin-bottom: 8px; }
    .header p { color: var(--text-muted); font-size: 14px; }

    .dashboard {
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    /* Side-by-side row for the first two cards */
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }

    @media (max-width: 800px) {
      .row { grid-template-columns: 1fr; }
    }

    .workflow-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
    }

    .workflow-card h2 { font-size: 16px; font-weight: 600; margin-bottom: 4px; }

    .workflow-card .subtitle {
      color: var(--text-muted);
      font-size: 12px;
      margin-bottom: 16px;
    }

    .workflow-card .subtitle a {
      color: var(--link);
      text-decoration: none;
    }
    .workflow-card .subtitle a:hover { text-decoration: underline; }

    .chart-container {
      display: flex;
      align-items: flex-end;
      gap: 4px;
      height: 160px;
      padding: 0 4px;
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
      min-width: 28px;
    }

    .bar {
      width: 100%;
      max-width: 48px;
      min-height: 20px;
      height: 100%;
      border-radius: 4px 4px 0 0;
      transition: opacity 0.2s;
    }

    .bar-wrapper:hover .bar { opacity: 0.8; }

    .bar.success { background: var(--success); }
    .bar.failure { background: var(--failure); }
    .bar.cancelled { background: var(--cancelled); }

    .bar-label {
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 4px;
      white-space: nowrap;
      text-align: center;
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
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
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
    .tt-status.cancelled { background: rgba(139,148,158,0.2); color: var(--cancelled); }

    .legend {
      display: flex;
      gap: 16px;
      margin-top: 12px;
      justify-content: center;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .legend-dot { width: 10px; height: 10px; border-radius: 50%; }

    .error {
      color: var(--failure);
      font-size: 14px;
      text-align: center;
      padding: 20px;
    }

    .loading {
      text-align: center;
      color: var(--text-muted);
      padding: 40px;
      font-size: 14px;
    }

    .last-updated {
      text-align: center;
      color: var(--text-muted);
      font-size: 12px;
      margin-top: 16px;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>Integration Tests Dashboard</h1>
    <p>Azure IoT CLI Extensions — Last 10 runs per branch</p>
  </div>

  <div class="dashboard" id="dashboard"></div>
  <div class="last-updated" id="lastUpdated"></div>

  <script type="application/json" id="dashboardData">
__DASHBOARD_DATA__
  </script>

  <script>
    const DATA = JSON.parse(document.getElementById('dashboardData').textContent);

    function conclusionClass(c) {
      if (c === 'success') return 'success';
      if (c === 'failure') return 'failure';
      return 'cancelled';
    }

    function formatDate(s) {
      const d = new Date(s);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    function formatDateTime(s) {
      const d = new Date(s);
      return d.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    }

    function durationStr(a, b) {
      const ms = new Date(b) - new Date(a);
      const m = Math.floor(ms / 60000);
      const s = Math.floor((ms % 60000) / 1000);
      return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    function renderCard(wf) {
      const card = document.createElement('div');
      card.className = 'workflow-card';

      const repoUrl = `https://github.com/${wf.repo}/actions/workflows/${wf.workflowFile}`;
      card.innerHTML = `
        <h2>${wf.title}</h2>
        <div class="subtitle">
          <a href="${repoUrl}" target="_blank">${wf.repo}</a>
        </div>`;

      if (wf.error) {
        card.innerHTML += `<div class="error">${wf.error}</div>`;
        return card;
      }

      if (wf.runs.length === 0) {
        card.innerHTML += '<div class="loading">No completed runs found</div>';
        return card;
      }

      const chart = document.createElement('div');
      chart.className = 'chart-container';

      [...wf.runs].reverse().forEach(run => {
        const cls = conclusionClass(run.conclusion);
        const dur = durationStr(run.created_at, run.updated_at);

        const w = document.createElement('div');
        w.className = 'bar-wrapper';
        w.onclick = () => window.open(run.html_url, '_blank');

        w.innerHTML = `
          <div class="tooltip">
            <div class="tt-row"><span class="tt-label">Status</span><span class="tt-status ${cls}">${run.conclusion}</span></div>
            <div class="tt-row"><span class="tt-label">Run</span><span class="tt-value">#${run.run_number}</span></div>
            <div class="tt-row"><span class="tt-label">Branch</span><span class="tt-value">${run.head_branch}</span></div>
            <div class="tt-row"><span class="tt-label">Duration</span><span class="tt-value">${dur}</span></div>
            <div class="tt-row"><span class="tt-label">Date</span><span class="tt-value">${formatDateTime(run.created_at)}</span></div>
            <div class="tt-row"><span class="tt-label">Trigger</span><span class="tt-value">${run.event}</span></div>
          </div>
          <div class="bar ${cls}"></div>
          <div class="bar-label">${formatDate(run.created_at)}</div>`;

        chart.appendChild(w);
      });

      card.appendChild(chart);

      const legend = document.createElement('div');
      legend.className = 'legend';
      legend.innerHTML = `
        <div class="legend-item"><div class="legend-dot" style="background:var(--success)"></div> Success</div>
        <div class="legend-item"><div class="legend-dot" style="background:var(--failure)"></div> Failure</div>
        <div class="legend-item"><div class="legend-dot" style="background:var(--cancelled)"></div> Cancelled</div>`;
      card.appendChild(legend);

      return card;
    }

    const dashboard = document.getElementById('dashboard');
    const wfs = DATA.workflows;

    // First two cards side by side (CLI ext dev + preview)
    if (wfs.length >= 2) {
      const row = document.createElement('div');
      row.className = 'row';
      row.appendChild(renderCard(wfs[0]));
      row.appendChild(renderCard(wfs[1]));
      dashboard.appendChild(row);
    }

    // Remaining cards full width
    for (let i = 2; i < wfs.length; i++) {
      dashboard.appendChild(renderCard(wfs[i]));
    }

    const t = new Date(DATA.generated_at);
    document.getElementById('lastUpdated').textContent =
      `Dashboard generated: ${t.toLocaleString()} (updates after each integration test run)`;
  </script>
</body>
</html>"""


def main():
    token = os.environ.get("DASHBOARD_TOKEN", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not token and not gh_token:
        print("ERROR: At least one of DASHBOARD_TOKEN or GITHUB_TOKEN must be set")
        sys.exit(1)

    if not token:
        print("WARNING: DASHBOARD_TOKEN not set. Cross-repo data will not be available.")

    output_dir = os.environ.get("OUTPUT_DIR", ".")
    output_file = os.path.join(output_dir, "index.html")

    print("Fetching dashboard data...")
    data = generate_dashboard_data(token, gh_token)

    if data["fetch_errors"]:
        all_failed = all(wf["error"] for wf in data["workflows"])
        if all_failed:
            print("ERROR: All workflow data fetches failed.")
            sys.exit(1)
        print("WARNING: Some fetches failed. Generating partial dashboard.")

    data_json = json.dumps(data, indent=2)
    html = HTML_TEMPLATE.replace("__DASHBOARD_DATA__", data_json)

    os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(html)

    print(f"Dashboard generated: {output_file}")
    for wf in data["workflows"]:
        status = "ERROR" if wf["error"] else f"{len(wf['runs'])} runs"
        print(f"  {wf['title']}: {status}")


if __name__ == "__main__":
    main()
