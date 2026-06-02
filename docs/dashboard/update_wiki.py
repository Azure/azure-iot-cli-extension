"""Update ADO Wiki page with generated dashboard markdown.

Uses the ADO REST API with System.AccessToken to create/update
a wiki page.
"""

import os
import sys
import json
import base64
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def get_wiki_id(org_url, project, token):
    """Get the first project wiki ID."""
    url = f"{org_url}/{project}/_apis/wiki/wikis?api-version=7.1"
    auth = base64.b64encode(
        (':' + token).encode()
    ).decode()
    req = Request(url)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            wikis = data.get("value", [])
            for wiki in wikis:
                if wiki.get("type") == "projectWiki":
                    return wiki["id"]
            if wikis:
                return wikis[0]["id"]
    except (HTTPError, URLError) as e:
        print(f"ERROR: Failed to list wikis: {e}")
    return None


def update_wiki_page(org_url, project, wiki_id, page_path, content, token):
    """Create or update a wiki page."""
    from urllib.parse import quote
    encoded_path = quote(page_path, safe="")
    url = (f"{org_url}/{project}/_apis/wiki/wikis/{wiki_id}/"
           f"pages?path={encoded_path}&api-version=7.1")

    # Try to get existing page for ETag (needed for update)
    etag = None
    auth = base64.b64encode((':' + token).encode()).decode()
    req = Request(url)
    req.add_header("Authorization", f"Basic {auth}")
    try:
        with urlopen(req, timeout=30) as resp:
            etag = resp.headers.get("ETag", "")
    except HTTPError as e:
        if e.code != 404:
            print(f"ERROR: Failed to check wiki page: {e.code} {e.reason}")
            return False
        # 404 = page doesn't exist yet, will create
    except URLError as e:
        print(f"ERROR: Network error checking wiki page: {e}")
        return False

    body = json.dumps({"content": content}).encode("utf-8")
    req = Request(url, data=body, method="PUT")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    if etag:
        req.add_header("If-Match", etag)

    try:
        with urlopen(req, timeout=30) as resp:
            print(f"Wiki page updated: {resp.status}")
            return True
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"ERROR: Failed to update wiki page: {e.code} {e.reason}")
        print(f"Response: {body}")
        return False


def main():
    token = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    org_url = os.environ.get("WIKI_ORG_URL", "")
    project = os.environ.get("WIKI_PROJECT", "")
    dashboard_file = os.environ.get("DASHBOARD_FILE", "")

    if not all([token, org_url, project, dashboard_file]):
        print("ERROR: SYSTEM_ACCESSTOKEN, WIKI_ORG_URL, WIKI_PROJECT, "
              "and DASHBOARD_FILE must be set")
        sys.exit(1)

    if not os.path.isfile(dashboard_file):
        print(f"ERROR: Dashboard file not found: {dashboard_file}")
        sys.exit(1)

    with open(dashboard_file, "r") as f:
        content = f.read()

    print(f"Dashboard content length: {len(content)} chars")

    # Get wiki ID
    wiki_id = get_wiki_id(org_url, project, token)
    if not wiki_id:
        print("ERROR: Could not find a wiki. Please create a project wiki first.")
        sys.exit(1)
    print(f"Using wiki: {wiki_id}")

    # Update the page
    page_path = "/Azure IoT CLI Dashboard"
    success = update_wiki_page(org_url, project, wiki_id, page_path, content, token)
    if not success:
        sys.exit(1)
    print("Done!")


if __name__ == "__main__":
    main()
