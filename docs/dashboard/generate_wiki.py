"""Generate Azure IoT CLI Dashboard as ADO Wiki markdown with Mermaid charts.

Fetches the last 10 workflow runs per branch from configured GitHub repos
and outputs Markdown with tables and Mermaid bar charts for ADO Wiki.
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
    """Generate a Markdown table for a single workflow."""
    lines = []
    lines.append(f"### {title}")
    lines.append("")

    if error:
        lines.append(f"> ⚠️ {error}")
        lines.append("")
        return "\n".join(lines), []

    if not runs:
        lines.append("_No completed runs found_")
        lines.append("")
        return "\n".join(lines), []

    lines.append("| Status | Date | Duration | Run |")
    lines.append("|--------|------|----------|-----|")

    durations = []
    for run in reversed(runs):
        conclusion = run.get("conclusion", "unknown")
        emoji = STATUS_EMOJI.get(conclusion, "⚪")
        num = run.get("run_number", "—")
        url = run.get("html_url", "#")
        date = format_date(run.get("created_at", ""))
        total_secs, dur_str = compute_duration(
            run.get("created_at", ""), run.get("updated_at", "")
        )
        durations.append({"date": date, "minutes": round(total_secs / 60, 1),
                          "conclusion": conclusion})
        lines.append(f"| {emoji} {conclusion} | {date} | {dur_str} | [#{num}]({url}) |")

    lines.append("")

    # Summary counts
    conclusions = [r.get("conclusion", "unknown") for r in runs]
    parts = []
    for status, emoji in STATUS_EMOJI.items():
        count = conclusions.count(status)
        if count:
            label = {"success": "passed", "failure": "failed",
                     "cancelled": "cancelled"}[status]
            parts.append(f"{emoji} {count} {label}")
    if parts:
        lines.append("  ·  ".join(parts))
        lines.append("")

    return "\n".join(lines), durations


def render_mermaid_chart(title, durations):
    """Generate a Mermaid xychart-beta bar chart for run durations."""
    if not durations:
        return ""

    dates = [d["date"] for d in durations]
    mins = [d["minutes"] for d in durations]
    max_val = max(mins) if mins else 100
    y_max = int(max_val * 1.2) + 10

    x_labels = ", ".join(f'"{d}"' for d in dates)
    y_values = ", ".join(str(m) for m in mins)

    return f"""
```mermaid
xychart-beta
    title "{title} — Duration (minutes)"
    x-axis [{x_labels}]
    y-axis "Minutes" 0 --> {y_max}
    bar [{y_values}]
```
"""


def generate_dashboard(token):
    """Fetch data and return dashboard Markdown for ADO Wiki."""
    sections = []
    sections.append("# Azure IoT CLI Dashboard")
    sections.append("")
    sections.append("## Integration Tests")
    sections.append("_Last 10 runs per branch_")
    sections.append("")

    all_failed = True

    for wf in WORKFLOWS:
        runs = fetch_runs(wf["repo"], wf["workflowFile"], token, wf.get("branch"))

        error = None
        if runs is None:
            error = f"Failed to fetch data from {wf['repo']}"
        else:
            all_failed = False

        table_md, durations = render_table(wf["title"], runs, error)
        chart_md = render_mermaid_chart(wf["title"], durations)

        sections.append(table_md)
        if chart_md:
            sections.append(chart_md)
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
    app_id = os.environ.get("GITHUB_APP_ID", "")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

    if not all([app_id, private_key, installation_id]):
        print("ERROR: GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, and "
              "GITHUB_APP_INSTALLATION_ID must all be set")
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
