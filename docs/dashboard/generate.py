"""Generate an Integration Tests Dashboard as GitHub Actions workflow summary.

Fetches the last 10 workflow runs from configured GitHub repos
and writes a markdown summary to GITHUB_STEP_SUMMARY.
Users view the dashboard by clicking on the workflow run in the Actions tab.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError


WORKFLOWS = [
    {
        "id": "iot-cli-int-test",
        "title": "Azure IoT CLI Extension — Integration Tests",
        "repo": "Azure/azure-iot-cli-extension",
        "workflowFile": "int_test.yml",
        "same_repo": True,
    },
    {
        "id": "iot-ops-int-test",
        "title": "Azure IoT Ops CLI Extension — Integration Tests",
        "repo": "Azure/azure-iot-ops-cli-extension",
        "workflowFile": "int_test.yml",
        "same_repo": False,
    },
]

STATUS_EMOJI = {
    "success": "✅",
    "failure": "❌",
    "cancelled": "⏹️",
}


def fetch_runs(repo: str, workflow_file: str, token: str) -> list[dict] | None:
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


def format_date(date_str: str) -> str:
    """Format ISO date string to readable format."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, AttributeError):
        return date_str


def compute_duration(created_at: str, updated_at: str) -> str:
    """Compute duration between two ISO timestamps."""
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        delta = end - start
        total_secs = int(delta.total_seconds())
        mins, secs = divmod(total_secs, 60)
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"
    except (ValueError, AttributeError):
        return "—"


def truncate_branch(branch: str, max_len: int = 30) -> str:
    """Truncate branch name if too long."""
    if len(branch) <= max_len:
        return branch
    return branch[:max_len - 1] + "…"


def generate_workflow_markdown(title: str, repo: str, workflow_file: str,
                                runs: list[dict] | None, error: str | None) -> str:
    """Generate markdown section for a single workflow."""
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

    # Table header
    lines.append("| # | Status | Branch | Date | Duration | Trigger |")
    lines.append("|---|--------|--------|------|----------|---------|")

    # Show oldest first (API returns newest first)
    for run in reversed(runs):
        conclusion = run.get("conclusion", "unknown")
        emoji = STATUS_EMOJI.get(conclusion, "⚪")
        run_number = run.get("run_number", "—")
        branch = run.get("head_branch", "—")
        html_url = run.get("html_url", "#")
        created_at = run.get("created_at", "")
        updated_at = run.get("updated_at", "")
        event = run.get("event", "—")

        date_str = format_date(created_at)
        duration = compute_duration(created_at, updated_at)
        branch_display = truncate_branch(branch)

        lines.append(
            f"| [#{run_number}]({html_url}) "
            f"| {emoji} {conclusion} "
            f"| `{branch_display}` "
            f"| {date_str} "
            f"| {duration} "
            f"| {event} |"
        )

    lines.append("")

    # Summary counts
    conclusions = [r.get("conclusion", "unknown") for r in runs]
    success_count = conclusions.count("success")
    failure_count = conclusions.count("failure")
    cancelled_count = conclusions.count("cancelled")
    summary_parts = []
    if success_count:
        summary_parts.append(f"✅ {success_count} passed")
    if failure_count:
        summary_parts.append(f"❌ {failure_count} failed")
    if cancelled_count:
        summary_parts.append(f"⏹️ {cancelled_count} cancelled")
    lines.append(" · ".join(summary_parts))
    lines.append("")

    return "\n".join(lines)


def generate_dashboard(token: str, gh_token: str) -> str:
    """Fetch data for all workflows and return markdown dashboard."""
    sections = []
    sections.append("# Integration Tests Dashboard")
    sections.append("*Azure IoT CLI Extensions — Last 10 workflow runs*")
    sections.append("")

    any_failure = False
    all_failed = True

    for wf in WORKFLOWS:
        tk = token or gh_token
        runs = fetch_runs(wf["repo"], wf["workflowFile"], tk)

        if runs is None and token and gh_token and wf["same_repo"]:
            print(f"  Retrying {wf['repo']} with GITHUB_TOKEN...")
            runs = fetch_runs(wf["repo"], wf["workflowFile"], gh_token)

        error = None
        if runs is None:
            any_failure = True
            error = f"Failed to fetch data from {wf['repo']}"
            if not wf["same_repo"]:
                error += " — check GitHub App token configuration."
        else:
            all_failed = False

        sections.append(generate_workflow_markdown(
            wf["title"], wf["repo"], wf["workflowFile"], runs, error
        ))

    sections.append("---")
    gen_time = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    sections.append(f"*Dashboard generated: {gen_time} · Refreshes every 2 hours*")

    if all_failed and any_failure:
        return None

    return "\n".join(sections)


def main():
    # DASHBOARD_TOKEN: GitHub App token with Actions:read for all repos (auto-generated per run)
    # GITHUB_TOKEN: automatic workflow token for same-repo fallback (never expires)
    token = os.environ.get("DASHBOARD_TOKEN", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not token and not gh_token:
        print("ERROR: At least one of DASHBOARD_TOKEN or GITHUB_TOKEN must be set")
        sys.exit(1)

    if not token:
        print("WARNING: DASHBOARD_TOKEN not set. Cross-repo data will not be available.")
        print("  Only same-repo (azure-iot-cli-extension) data will be shown.")

    print("Fetching dashboard data...")
    markdown = generate_dashboard(token, gh_token)

    if markdown is None:
        print("ERROR: All workflow data fetches failed.")
        sys.exit(1)

    # Write to GITHUB_STEP_SUMMARY if running in Actions, otherwise to stdout/file
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write(markdown)
        print(f"Dashboard written to GITHUB_STEP_SUMMARY")
    else:
        # Local development: write to file or stdout
        output_dir = os.environ.get("OUTPUT_DIR", ".")
        output_file = os.path.join(output_dir, "dashboard.md")
        os.makedirs(output_dir, exist_ok=True)
        with open(output_file, "w") as f:
            f.write(markdown)
        print(f"Dashboard written to: {output_file}")

    print("Done.")


if __name__ == "__main__":
    main()
