"""Update ADO Dashboard Markdown widget with generated dashboard content.

Uses the ADO REST API with System.AccessToken to update
a Markdown widget on an Azure DevOps dashboard.
"""

import os
import sys
import json
import base64
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Dashboard configuration
DASHBOARD_ID = "f4abb839-fbbc-45c8-aae7-017d6ccb3bd5"
WIDGET_ID = "e073ffb9-cad3-4731-b831-15360539e636"
TEAM = "iot-central"


def get_widget(org_url, project, token):
    """Get the current widget configuration."""
    url = (
        f"{org_url}/{project}/{TEAM}/_apis/dashboard/"
        f"dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}"
        f"?api-version=7.1-preview.2"
    )
    auth = base64.b64encode((':' + token).encode()).decode()
    req = Request(url)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (HTTPError, URLError) as e:
        print(f"ERROR: Failed to get widget: {e}")
        return None


def update_widget(org_url, project, token, content):
    """Update the Markdown widget with new content."""
    # Get current widget to preserve settings
    widget = get_widget(org_url, project, token)
    if not widget:
        print("ERROR: Could not fetch current widget configuration.")
        return False

    # Update the markdown content in widget settings
    settings = json.dumps({"markdown": content})
    widget["settings"] = settings
    widget["name"] = "Integration Tests Dashboard"

    url = (
        f"{org_url}/{project}/{TEAM}/_apis/dashboard/"
        f"dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}"
        f"?api-version=7.1-preview.2"
    )
    auth = base64.b64encode((':' + token).encode()).decode()
    body = json.dumps(widget).encode("utf-8")
    req = Request(url, data=body, method="PUT")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            print(f"Widget updated successfully: {resp.status}")
            return True
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"ERROR: Failed to update widget: {e.code} {e.reason}")
        print(f"Response: {error_body}")
        return False
    except URLError as e:
        print(f"ERROR: Network error updating widget: {e}")
        return False


def main():
    token = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    org_url = os.environ.get(
        "DASHBOARD_ORG_URL", "https://dev.azure.com/msazure"
    )
    project = os.environ.get("DASHBOARD_PROJECT", "One")
    dashboard_file = os.environ.get("DASHBOARD_FILE", "")

    if not token:
        print("ERROR: SYSTEM_ACCESSTOKEN must be set")
        sys.exit(1)

    if not dashboard_file:
        print("ERROR: DASHBOARD_FILE must be set")
        sys.exit(1)

    if not os.path.isfile(dashboard_file):
        print(f"ERROR: Dashboard file not found: {dashboard_file}")
        sys.exit(1)

    with open(dashboard_file, "r") as f:
        content = f.read()

    print(f"Dashboard content length: {len(content)} chars")

    success = update_widget(org_url, project, token, content)
    if not success:
        sys.exit(1)
    print("Done!")


if __name__ == "__main__":
    main()
