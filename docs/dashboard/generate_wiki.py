"""Generate Azure IoT CLI Dashboard as ADO Wiki markdown with SVG bar charts.

Fetches the last 10 workflow runs per branch from configured GitHub repos
and outputs Markdown with colored SVG bar charts for ADO Wiki.
Uses GitHub App authentication (JWT → installation token).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    import jwt  # PyJWT
except ImportError:
    print("ERROR: PyJWT not installed. Run: pip install PyJWT cryptography")
    sys.exit(1)


WORKFLOWS = [
    {
        "id": "iot-cli-dev",
        "title": "azure-iot-cli-extension — dev",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "group": "cli-ext",
    },
    {
        "id": "iot-cli-preview",
        "title": "azure-iot-cli-extension — preview",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "preview",
        "group": "cli-ext",
    },
    {
        "id": "iot-ops-dev",
        "title": "azure-iot-ops-cli-extension — dev",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "group": "ops-ext",
    },
]

STATUS_EMOJI = {"success": "✅", "failure": "❌", "cancelled": "⏹️"}


def generate_github_app_token(app_id, private_key, installation_id):
    """Generate a GitHub App installation token from app credentials."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id,
    }
    encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    # Exchange JWT for installation token
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = Request(url, method="POST")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Authorization", f"Bearer {encoded_jwt}")

    with urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        return data["token"]


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
        return total_secs, f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
    except (ValueError, AttributeError):
        return 0, "—"


def render_table(title, runs, error):
    """Generate an HTML table for a workflow."""
    lines = []

    if error:
        lines.append(f"**{title}**")
        lines.append(f"> ⚠️ {error}")
        lines.append("")
        return "\n".join(lines)

    if not runs:
        lines.append(f"**{title}**")
        lines.append("_No completed runs found_")
        lines.append("")
        return "\n".join(lines)

    # Summary counts
    conclusions = [r.get("conclusion", "unknown") for r in runs]
    parts = []
    for status, emoji in STATUS_EMOJI.items():
        count = conclusions.count(status)
        if count:
            label = {"success": "passed", "failure": "failed",
                     "cancelled": "cancelled"}[status]
            parts.append(f"{emoji} {count} {label}")

    summary = "  ·  ".join(parts) if parts else ""

    lines.append(f"**{title}** — {summary}")
    lines.append("")
    lines.append('<table>')
    lines.append('<tr><th>Status</th><th>Date</th><th>Duration</th><th>Run</th></tr>')

    # Newest first (API returns newest first)
    for run in runs:
        conclusion = run.get("conclusion", "unknown")
        emoji = STATUS_EMOJI.get(conclusion, "⚪")
        num = run.get("run_number", "—")
        url = run.get("html_url", "#")
        date = format_date(run.get("created_at", ""))
        _, dur_str = compute_duration(
            run.get("created_at", ""), run.get("updated_at", "")
        )
        lines.append(
            f'<tr><td>{emoji} {conclusion}</td><td>{date}</td>'
            f'<td>{dur_str}</td><td><a href="{url}">#{num}</a></td></tr>'
        )

    lines.append('</table>')
    lines.append("")
    return "\n".join(lines)


def generate_dashboard(token):
    """Fetch data and return dashboard Markdown for ADO Wiki."""
    sections = []
    sections.append("# Azure IoT CLI Dashboard")
    sections.append("")
    sections.append("## Integration Tests")
    sections.append("_Last 10 runs per branch_")
    sections.append("")

    all_failed = True
    cli_ext_charts = []
    ops_ext_charts = []

    for wf in WORKFLOWS:
        runs = fetch_runs(wf["repo"], wf["workflowFile"], token, wf.get("branch"))

        error = None
        if runs is None:
            error = f"Failed to fetch data from {wf['repo']}"
        else:
            all_failed = False

        chart = render_table(wf["title"], runs, error)

        if wf["group"] == "cli-ext":
            cli_ext_charts.append(chart)
        else:
            ops_ext_charts.append(chart)

    # Side-by-side for CLI ext dev + preview
    if len(cli_ext_charts) == 2:
        sections.append('<table><tr>')
        sections.append(f'<td valign="top">\n\n{cli_ext_charts[0]}\n\n</td>')
        sections.append(f'<td valign="top">\n\n{cli_ext_charts[1]}\n\n</td>')
        sections.append('</tr></table>')
    else:
        for c in cli_ext_charts:
            sections.append(c)
    sections.append("")

    # Ops ext full width
    for c in ops_ext_charts:
        sections.append(c)
        sections.append("")

    sections.append("---")
    gen_time = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    sections.append(
        f"_Dashboard generated: {gen_time} · Auto-updates every 6 hours_"
    )

    if all_failed:
        return None

    return "\n".join(sections)


def main():
    app_id = os.environ.get("DASHBOARD_APP_ID", "")
    private_key = os.environ.get("DASHBOARD_APP_PRIVATE_KEY", "")
    installation_id = os.environ.get("DASHBOARD_APP_INSTALLATION_ID", "")

    if not all([app_id, private_key, installation_id]):
        print("ERROR: DASHBOARD_APP_ID, DASHBOARD_APP_PRIVATE_KEY, and "
              "DASHBOARD_APP_INSTALLATION_ID must all be set")
        sys.exit(1)

    print("Generating GitHub App installation token...")
    try:
        token = generate_github_app_token(app_id, private_key, installation_id)
        print("Token generated successfully")
    except Exception as e:
        print(f"ERROR: Failed to generate token: {e}")
        sys.exit(1)

    print("Fetching dashboard data...")
    markdown = generate_dashboard(token)

    if markdown is None:
        print("ERROR: All workflow data fetches failed.")
        sys.exit(1)

    output_dir = os.environ.get("OUTPUT_DIR", ".")
    output_file = os.path.join(output_dir, "dashboard.md")
    os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(markdown)
    print(f"Dashboard written to: {output_file}")


if __name__ == "__main__":
    main()
