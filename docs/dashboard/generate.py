"""Generate Azure IoT CLI Dashboard as workflow summary.

Fetches the last 10 workflow runs per branch from configured GitHub repos
and writes HTML tables to GITHUB_STEP_SUMMARY.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError


WORKFLOWS = [
    {
        "title": "azure-iot-cli-extension — dev",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": True,
        "group": "cli-ext",
    },
    {
        "title": "azure-iot-cli-extension — preview",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "preview",
        "same_repo": True,
        "group": "cli-ext",
    },
    {
        "title": "azure-iot-ops-cli-extension — dev",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": False,
        "group": "ops-ext",
    },
]

STATUS_EMOJI = {"success": "✅", "failure": "❌", "cancelled": "⏹️"}


def fetch_runs(repo, workflow_file, token, branch=None):
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


def format_date(date_str):
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d")
    except (ValueError, AttributeError):
        return date_str


def compute_duration(created_at, updated_at):
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        total_secs = int((end - start).total_seconds())
        mins, secs = divmod(total_secs, 60)
        return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
    except (ValueError, AttributeError):
        return "—"


def render_table_html(title, runs, error):
    """Generate an HTML table for a single workflow."""
    lines = []
    lines.append(f"<h4>{title}</h4>")

    if error:
        lines.append(f"<p>⚠️ {error}</p>")
        return "\n".join(lines)

    if not runs:
        lines.append("<p><em>No completed runs found</em></p>")
        return "\n".join(lines)

    lines.append('<table border="1" cellpadding="6" cellspacing="0">')
    lines.append('<tr><th>Status</th><th>Date</th><th>Duration</th><th>Run</th></tr>')

    for run in runs:
        conclusion = run.get("conclusion", "unknown")
        emoji = STATUS_EMOJI.get(conclusion, "⚪")
        num = run.get("run_number", "—")
        url = run.get("html_url", "#")
        date = format_date(run.get("created_at", ""))
        dur = compute_duration(run.get("created_at", ""), run.get("updated_at", ""))

        lines.append(
            f"<tr>"
            f"<td>{emoji} {conclusion}</td>"
            f"<td>{date}</td>"
            f"<td>{dur}</td>"
            f"<td><a href=\"{url}\">#{num}</a></td>"
            f"</tr>"
        )

    lines.append("</table>")

    # Summary
    conclusions = [r.get("conclusion", "unknown") for r in runs]
    parts = []
    for status, emoji in STATUS_EMOJI.items():
        count = conclusions.count(status)
        if count:
            label = {"success": "passed", "failure": "failed", "cancelled": "cancelled"}[status]
            parts.append(f"{emoji} {count} {label}")
    if parts:
        lines.append(f"<p>{'  ·  '.join(parts)}</p>")

    return "\n".join(lines)


def generate_dashboard(token, gh_token):
    """Fetch data and return dashboard HTML."""
    sections = []
    sections.append("<h1>Azure IoT CLI Dashboard</h1>")
    sections.append("<h2>Integration Tests</h2>")
    sections.append("<p><em>Last 10 runs per branch</em></p>")

    all_failed = True
    cli_ext_tables = []
    ops_ext_tables = []

    for wf in WORKFLOWS:
        tk = token or gh_token
        runs = fetch_runs(wf["repo"], wf["workflowFile"], tk, wf.get("branch"))

        if runs is None and token and gh_token and wf["same_repo"]:
            print(f"  Retrying {wf['repo']} ({wf.get('branch')}) with GITHUB_TOKEN...")
            runs = fetch_runs(wf["repo"], wf["workflowFile"], gh_token, wf.get("branch"))

        error = None
        if runs is None:
            error = f"Failed to fetch data from {wf['repo']}"
            if not wf["same_repo"]:
                error += " — check GitHub App token configuration."
        else:
            all_failed = False

        table_html = render_table_html(wf["title"], runs, error)

        if wf["group"] == "cli-ext":
            cli_ext_tables.append(table_html)
        else:
            ops_ext_tables.append(table_html)

    # Side-by-side layout for CLI ext dev + preview (borderless layout)
    if len(cli_ext_tables) == 2:
        sections.append('<table style="border: none; border-collapse: collapse;"><tr>')
        sections.append(f'<td valign="top" style="border: none; padding-right: 40px;">\n{cli_ext_tables[0]}\n</td>')
        sections.append(f'<td valign="top" style="border: none;">\n{cli_ext_tables[1]}\n</td>')
        sections.append('</tr></table>')
    else:
        for t in cli_ext_tables:
            sections.append(t)

    sections.append("")
    sections.append("<br>")
    sections.append("")

    # Ops ext full width
    for t in ops_ext_tables:
        sections.append(t)
        sections.append("")

    sections.append("<hr>")
    gen_time = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    sections.append(f"<p><em>Dashboard generated: {gen_time} · Updates after each integration test run</em></p>")

    if all_failed:
        return None

    return "\n".join(sections)


def main():
    token = os.environ.get("DASHBOARD_TOKEN", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not token and not gh_token:
        print("ERROR: At least one of DASHBOARD_TOKEN or GITHUB_TOKEN must be set")
        sys.exit(1)

    if not token:
        print("WARNING: DASHBOARD_TOKEN not set. Cross-repo data will not be available.")

    print("Fetching dashboard data...")
    markdown = generate_dashboard(token, gh_token)

    if markdown is None:
        print("ERROR: All workflow data fetches failed.")
        sys.exit(1)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write(markdown)
        print("Dashboard written to GITHUB_STEP_SUMMARY")
    else:
        output_dir = os.environ.get("OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "dashboard.md")
        os.makedirs(output_dir, exist_ok=True)
        with open(output_file, "w") as f:
            f.write(markdown)
        print(f"Dashboard written to: {output_file}")


if __name__ == "__main__":
    main()
