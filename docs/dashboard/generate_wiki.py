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
STATUS_COLORS = {"success": "#2da44e", "failure": "#cf222e", "cancelled": "#6e7781"}


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


def collect_run_data(runs):
    """Extract duration and status data from workflow runs."""
    data = []
    for run in reversed(runs):
        conclusion = run.get("conclusion", "unknown")
        date = format_date(run.get("created_at", ""))
        total_secs, dur_str = compute_duration(
            run.get("created_at", ""), run.get("updated_at", "")
        )
        data.append({
            "date": date,
            "minutes": round(total_secs / 60, 1),
            "dur_str": dur_str,
            "conclusion": conclusion,
            "run_number": run.get("run_number", "—"),
            "url": run.get("html_url", "#"),
        })
    return data


def render_svg_bar_chart(title, data):
    """Generate an inline SVG bar chart with colored bars per status."""
    if not data:
        return ""

    n = len(data)
    bar_width = 40
    bar_gap = 12
    chart_left = 50
    chart_top = 10
    chart_height = 160
    chart_width = n * (bar_width + bar_gap) + bar_gap
    total_width = chart_left + chart_width + 10
    label_area = 50
    legend_area = 30
    total_height = chart_top + chart_height + label_area + legend_area

    mins = [d["minutes"] for d in data]
    max_val = max(mins) if mins else 100
    if max_val == 0:
        max_val = 10

    svg_lines = []
    svg_lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_width}" height="{total_height}" '
        f'style="font-family: -apple-system, BlinkMacSystemFont, Segoe UI, '
        f'Helvetica, Arial, sans-serif; font-size: 11px;">'
    )

    # Y-axis labels and grid lines
    for i in range(5):
        y_val = max_val * i / 4
        y_pos = chart_top + chart_height - (chart_height * i / 4)
        svg_lines.append(
            f'<text x="{chart_left - 5}" y="{y_pos + 4}" '
            f'text-anchor="end" fill="#656d76">{int(y_val)}</text>'
        )
        svg_lines.append(
            f'<line x1="{chart_left}" y1="{y_pos}" '
            f'x2="{chart_left + chart_width}" y2="{y_pos}" '
            f'stroke="#e1e4e8" stroke-width="1"/>'
        )

    # Y-axis label
    svg_lines.append(
        f'<text x="12" y="{chart_top + chart_height / 2}" '
        f'text-anchor="middle" fill="#656d76" font-size="10" '
        f'transform="rotate(-90, 12, {chart_top + chart_height / 2})">Minutes</text>'
    )

    # Bars
    for i, d in enumerate(data):
        x = chart_left + bar_gap + i * (bar_width + bar_gap)
        bar_h = (d["minutes"] / max_val) * chart_height if max_val > 0 else 0
        bar_h = max(bar_h, 2)  # minimum visible height
        y = chart_top + chart_height - bar_h
        color = STATUS_COLORS.get(d["conclusion"], "#6e7781")

        # Bar
        svg_lines.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_h}" '
            f'fill="{color}" rx="2"/>'
        )

        # Duration label on top of bar
        svg_lines.append(
            f'<text x="{x + bar_width / 2}" y="{y - 4}" '
            f'text-anchor="middle" fill="#1f2328" font-size="9">'
            f'{int(d["minutes"])}m</text>'
        )

        # Date label below
        svg_lines.append(
            f'<text x="{x + bar_width / 2}" '
            f'y="{chart_top + chart_height + 14}" '
            f'text-anchor="middle" fill="#656d76" font-size="10">'
            f'{d["date"]}</text>'
        )

        # Run number below date
        svg_lines.append(
            f'<text x="{x + bar_width / 2}" '
            f'y="{chart_top + chart_height + 28}" '
            f'text-anchor="middle" fill="#656d76" font-size="9">'
            f'#{d["run_number"]}</text>'
        )

    # Legend
    legend_y = chart_top + chart_height + label_area + 5
    legend_items = [
        ("Success", STATUS_COLORS["success"]),
        ("Failure", STATUS_COLORS["failure"]),
        ("Cancelled", STATUS_COLORS["cancelled"]),
    ]
    lx = chart_left
    for label, color in legend_items:
        svg_lines.append(
            f'<rect x="{lx}" y="{legend_y}" width="12" height="12" '
            f'fill="{color}" rx="2"/>'
        )
        svg_lines.append(
            f'<text x="{lx + 16}" y="{legend_y + 10}" '
            f'fill="#1f2328" font-size="11">{label}</text>'
        )
        lx += len(label) * 7 + 30

    svg_lines.append("</svg>")
    return "\n".join(svg_lines)


def render_bar_chart(title, runs, error):
    """Generate an SVG bar chart with summary for a workflow."""
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

    data = collect_run_data(runs)

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
    lines.append(render_svg_bar_chart(title, data))
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

        chart = render_bar_chart(wf["title"], runs, error)

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
