# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Reap expired, explicitly owned integration resources without touching active runs."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
from urllib.parse import quote


MIN_AGE_SECONDS = 48 * 60 * 60
HUB = runpy.run_path(str(Path(__file__).resolve().parents[1] / "azext_iot/tests/_hub_ownership.py"))


def owner_stamp(resource):
    tags = resource.get("tags") or {}
    created = tags.get("createdEpoch", "")
    if (tags.get("intTest") == "true" and isinstance(tags.get("runUid"), str) and tags["runUid"]
            and isinstance(created, str) and created.isascii() and created.isdigit()):
        return "createdEpoch", "runUid", tags["runUid"], created, int(created)
    if not HUB["planned_root"](resource.get("id", "")):
        return None
    owner_key = HUB["OWNER_TAG"]
    if owner_key not in tags and tags.get("authPhase") == "local-auth":
        owner_key = "runUid"
    if not isinstance(tags.get(owner_key), str) or not re.fullmatch(r"[0-9a-f]{32}", tags[owner_key]):
        return None
    created = resource.get("createdTime", "")
    try:
        timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if timestamp.utcoffset() is not None:
            return "createdTime", owner_key, tags[owner_key], created, timestamp.timestamp()
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def expired(resource, exclusions, now):
    stamp = owner_stamp(resource)
    return resource["name"] not in exclusions and stamp is not None and 0 < stamp[-1] <= now - MIN_AGE_SECONDS


def inventory_url(group):
    subscription = subprocess.check_output(
        ["az", "account", "show", "--query", "id", "--output", "tsv"], text=True,
    ).strip()
    endpoint = subprocess.check_output(
        ["az", "cloud", "show", "--query", "endpoints.resourceManager", "--output", "tsv"], text=True,
    ).strip()
    return (
        f"{endpoint.rstrip('/')}/subscriptions/{subscription}/resourceGroups/{quote(group, safe='')}"
        "/resources?api-version=2021-04-01&$expand=createdTime"
    )


def inventory(url):
    prefix = url.split("?", 1)[0].casefold()
    resources = []
    while url:
        if not url.casefold().startswith(prefix + "?"):
            raise ValueError("Unexpected cleanup inventory continuation scope.")
        page = json.loads(subprocess.check_output(
            ["az", "rest", "--method", "get", "--url", url, "--output", "json"],
            text=True, stderr=subprocess.PIPE,
        ))
        resources.extend(page["value"])
        url = page.get("nextLink")
    return resources


def cleanup(group, exclusions, now=None):
    if not group or group.startswith("$("):
        raise ValueError("An explicit cleanup resource group is required.")
    now = time.time() if now is None else now
    url = inventory_url(group)
    resources = inventory(url)
    selected = [resource for resource in resources if expired(resource, exclusions, now)]
    print(f"Found {len(selected)} expired owned resources; preserving {len(resources) - len(selected)} others.")
    failures = []
    for resource in selected:
        try:
            current = json.loads(subprocess.check_output(
                ["az", "resource", "show", "--ids", resource["id"], "--output", "json"],
                text=True, stderr=subprocess.PIPE,
            ))
            if owner_stamp(resource)[0] == "createdTime":
                matches = [item for item in inventory(url) if item["id"].casefold() == resource["id"].casefold()]
                if len(matches) != 1 or owner_stamp(matches[0]) != owner_stamp(resource):
                    raise ValueError(f"Cleanup creation/ownership changed for {resource['name']}; refusing deletion.")
                current["createdTime"] = matches[0].get("createdTime")
            if (current.get("id", "").casefold() != resource["id"].casefold()
                    or not expired(current, exclusions, now) or owner_stamp(current) != owner_stamp(resource)):
                raise ValueError(f"Cleanup ownership changed for {resource['name']}; refusing deletion.")
            subprocess.run(
                ["az", "resource", "delete", "--ids", resource["id"]],
                check=True, text=True, stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as error:
            if re.search(r"\((?:ResourceNotFound|ResourceGroupNotFound)\)", error.stderr or ""):
                print(f"Already deleted: {resource['id']}")
                continue
            message = f"Cleanup failed for {resource['id']}: {error.stderr or error}"
            print(message, file=sys.stderr)
            failures.append(message)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            failures.append(str(error))
    if failures:
        raise RuntimeError(f"{len(failures)} resource cleanup failures; all other eligible resources were attempted.")


if __name__ == "__main__":
    cleanup(os.environ["RESOURCEGROUP"], set(os.environ.get("EXCLUSIONS", "").split()))
