"""Generate Integration Tests Dashboard as workflow summary.

Fetches the last 10 workflow runs per branch from configured GitHub repos
and writes markdown tables to GITHUB_STEP_SUMMARY.
Layout: CLI ext dev + preview, then Ops CLI ext dev.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError


WORKFLOWS = [
    {
        "id": "iot-cli-dev",
        "title": "Azure IoT CLI Extension — dev",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": True,
    },
    {
        "id": "iot-cli-preview",
        "title": "Azure IoT CLI Extension — preview",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "preview",
        "same_repo": True,
    },
    {
        "id": "iot-ops-dev",
        "title": "Azure IoT Ops CLI Extension — dev",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "branch": "dev",
        "same_repo": False,
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
    """Format ISO date string to readable format."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, AttributeError):
        return date_str


def compute_duration(created_at, updated_at):
    """Compute duration between two ISO timestamps."""
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        total_secs = int((end - start).total_seconds())
        mins, secs = divmod(total_secs, 60)
        return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
    except (ValueError, AttributeError):
        return "—"


def render_workflow_table(title, repo, workflow_file, runs, error):
    """Generate markdown table for a single workflow."""
    lines = []
    repo_url = f"https://github.com/{repo}/actions/workflows/{workflow_file}"
    lines.append(f"### {title}")
    lines.append(f"[{repo}]({repo_url}) · `{workflow_file}`")
    lines.append("")

    if error:
        lines.append(f"> ⚠️ {error}")
        lines.append("")
        return "\n".join(lines)

    if not runs:
        lines.append("> No completed runs found")
        lines.append("")
        return "\n".join(lines)

    lines.append("| # | Status | Date | Duration | Trigger |")
    lines.append("|---|--------|------|----------|---------|")

    for run in reversed(runs):
        conclusion = run.get("conclusion", "unknown")
        emoji = STATUS_EMOJI.get(conclusion, "⚪")
        num = run.get("run_number", "—")
        url = run.get("html_url", "#")
        date = format_date(run.get("created_at", ""))
        dur = compute_duration(run.get("created_at", ""), run.get("updated_at", ""))
        event = run.get("event", "—")

        lines.append(f"| [#{num}]({url}) | {emoji} {conclusion} | {date} | {dur} | {event} |")

    lines.append("")

    # Summary counts
    conclusions = [r.get("conclusion", "unknown") for r in runs]
    parts = []
    label_map = {"success": "passed", "failure": "failed", "cancelled": "cancelled"}
    for status, emoji in STATUS_EMOJI.items():
        count = conclusions.count(status)
        if count:
            parts.append(f"{emoji} {count} {label_map[status]}")
    if parts:
        lines.append(" · ".join(parts))
        lines.append("")

    return "\n".join(lines)


def generate_dashboard(token, gh_token):
    """Fetch data and return markdown dashboard."""
    sections = []
    sections.append("# Integration Tests Dashboard")
    sections.append("*Azure IoT CLI Extensions — Last 10 runs per branch*")
    sections.append("")

    any_failure = False
    all_failed = True

    for wf in WORKFLOWS:
        tk = token or gh_token
        runs = fetch_runs(wf["repo"], wf["workflowFile"], tk, wf.get("branch"))

        if runs is None and token and gh_token and wf["same_repo"]:
            print(f"  Retrying {wf['repo']} ({wf.get('branch')}) with GITHUB_TOKEN...")
            runs = fetch_runs(wf["repo"], wf["workflowFile"], gh_token, wf.get("branch"))

        error = None
        if runs is None:
            any_failure = True
            error = f"Failed to fetch data from {wf['repo']}"
            if not wf["same_repo"]:
                error += " — check GitHub App token configuration."
        else:
            all_failed = False

        sections.append(render_workflow_table(
            wf["title"], wf["repo"], wf["workflowFile"], runs, error
        ))

    sections.append("---")
    gen_time = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    sections.append(f"*Dashboard generated: {gen_time} · Updates after each integration test run*")

    if all_failed and any_failure:
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
