# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Isolated partial-run guards; never a replacement for release security."""

import argparse
from datetime import datetime, timezone
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

import release_pipeline as release


ADMISSION_DEADLINE = datetime(2026, 10, 14, 23, tzinfo=timezone.utc)
PERMISSIONS_URL = (
    "https://dev.azure.com/azureiotdevxp/_apis/permissions/"
    "33344d9c-fc72-4d6f-aba5-fa317101a7e9"
)


def get(url, authenticated=False):
    headers = {"Accept": "application/json", "User-Agent": "azure-iot-partial-release-diagnostic"}
    if authenticated:
        headers["Authorization"] = f"Bearer {release.environment('SYSTEM_ACCESSTOKEN')}"
    request = Request(url, headers=headers)
    try:
        with build_opener(release.NoRedirect()).open(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Diagnostic read failed with HTTP {error.code}.") from None


def permissions():
    project = release.environment("SYSTEM_TEAMPROJECTID")
    required = {
        147: {"View builds": 1, "Queue builds": 128, "Stop builds": 512, "View pipeline": 1024},
        161: {"View producer builds": 1, "View producer pipeline": 1024},
    }
    denied = []
    for definition, actions in required.items():
        for name, bit in actions.items():
            query = urlencode({
                "tokens": f"{project}/{definition}",
                "alwaysAllowAdministrators": "false", "api-version": "7.1",
            })
            result = get(f"{PERMISSIONS_URL}/{bit}?{query}", authenticated=True)
            allowed = result.get("count") == 1 and result.get("value") == [True]
            print(f"Build Service permission: pipeline {definition}, {name}: {allowed}", flush=True)
            if not allowed:
                denied.append(f"{definition}: {name}")
    if denied:
        raise RuntimeError("Missing required Build Service permissions: " + ", ".join(denied))


def admission():
    if datetime.now(timezone.utc) >= ADMISSION_DEADLINE:
        raise RuntimeError("Diagnostic live admission expired; recheck capacity and daily 13:00 UTC cleanup.")
    builds = release.ado(
        "build/builds?statusFilter=notStarted,inProgress,postponed,cancelling&$top=100"
    )["value"]
    parent = release.identifier(release.environment("BUILD_BUILDID"))
    if len(builds) >= 100 or any(str(build["id"]) != parent for build in builds):
        raise RuntimeError("Other ADO workloads are active or queued; live admission must be reviewed again.")
    for status in ("in_progress", "queued", "waiting", "requested", "pending"):
        result = get(
            f"https://api.github.com/repos/{release.REPOSITORY}/actions/runs?status={status}&per_page=1"
        )
        if result["total_count"] != 0:
            raise RuntimeError(f"GitHub workflows are {status}; live admission must be reviewed again.")
    print("No competing queued/active ADO or GitHub workloads; time-bounded live admission remains valid.")


def report(output):
    producer = release.producer()
    records = release.ado(f"build/builds/{producer['build']}/timeline")["records"]
    release.write(output, {
        "scope": "partial diagnostics only",
        "producer": producer,
        "sourceCommit": release.DIAGNOSTIC_SOURCE_SHA,
        "components": [
            {"name": record["name"], "state": record["state"], "result": record.get("result")}
            for record in records if record["type"] == "Stage"
        ],
        "missingChecks": ["MicrosoftSecurityDevOps@1"],
        "releaseQualified": False,
        "publicationAllowed": False,
    })
    print("##vso[task.logissue type=error]INCOMPLETE: MSDO was not run; full release qualification is blocked.")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("permissions", "admission", "report"))
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.operation == "permissions":
        permissions()
    elif args.operation == "admission":
        admission()
    else:
        if not args.output:
            parser.error("--output is required for report")
        return report(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
