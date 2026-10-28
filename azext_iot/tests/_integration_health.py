# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Resolve editable ADO health profiles into immutable branch/day execution plans."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
SERVICES = {"DPS", "HubControl", "HubData", "ADU", "ADR"}
PYTHONS = {"3.10", "3.11", "3.12", "3.13"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def required(name):
    value = os.environ.get(name, "")
    if not value or "$(" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Configure {name} explicitly.")
    return value


def ado_get(path):
    request = Request(
        "https://dev.azure.com/azureiotdevxp/aziotcli/_apis/build/" + path,
        headers={"Authorization": "Bearer " + required("SYSTEM_ACCESSTOKEN")},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"ADO health lookup failed with HTTP {error.code}.") from None


def identity():
    value = {key: required(env) for key, env in (
        ("build", "BUILD_BUILDID"), ("pipeline", "SYSTEM_DEFINITIONID"),
        ("commit", "BUILD_SOURCEVERSION"), ("branch", "BUILD_SOURCEBRANCH"),
    )}
    if not all(re.fullmatch(r"[1-9][0-9]*", value[key]) for key in ("build", "pipeline")):
        raise ValueError("Build and pipeline IDs must be positive integers.")
    if not re.fullmatch(r"[a-f0-9]{40}", value["commit"]) or not value["branch"].startswith("refs/heads/"):
        raise ValueError("An immutable commit on an explicit branch is required.")
    return value


def choose(configuration, build, producer):
    if (str(build["id"]) != producer["build"] or str(build["definition"]["id"]) != producer["pipeline"]
            or build["sourceVersion"] != producer["commit"] or build["sourceBranch"] != producer["branch"]):
        raise ValueError("ADO source identity differs from this run.")
    queued = datetime.fromisoformat(build["queueTime"].replace("Z", "+00:00"))
    if queued.tzinfo is None:
        raise ValueError("Queue time must include a timezone.")
    day = DAYS[queued.astimezone(timezone.utc).weekday()]
    if not isinstance(configuration, dict) or set(configuration) != {"schema", "branches"}:
        raise ValueError("ValidationProfiles requires schema and branches.")
    if (type(configuration["schema"]) is not int or configuration["schema"] != 1
            or not isinstance(configuration["branches"], dict)):
        raise ValueError("Unsupported ValidationProfiles schema.")
    branch = configuration["branches"].get(producer["branch"])
    if not isinstance(branch, dict) or not set(branch) <= set(DAYS) or day not in branch:
        raise ValueError(f"No valid profile for {producer['branch']} on {day}.")
    return {
        "schema": 1, "producer": producer, "queuedAt": queued.isoformat(), "day": day, "profile": branch[day],
        "configurationSha256": hashlib.sha256(
            json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def selected(values, allowed, name):
    if (not isinstance(values, list) or not values or not all(isinstance(item, str) for item in values)
            or len(values) != len(set(values)) or not set(values) <= allowed):
        raise ValueError(f"Select distinct supported {name}.")


def validate(profile):
    required_keys = {"region", "pythonVersions", "services"}
    if (not isinstance(profile, dict) or not required_keys <= set(profile)
            or not set(profile) <= required_keys | {"armEndpoint"}):
        raise ValueError("IoT profile requires region, pythonVersions and services, with optional armEndpoint.")
    region = profile["region"]
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9]{1,40}", region):
        raise ValueError("Health profiles require an explicit Azure region.")
    routing = profile.get("armEndpoint", "public")
    endpoints = {"public": "https://management.azure.com", "canary": "https://centraluseuap.management.azure.com"}
    if (not isinstance(routing, str) or routing not in endpoints
            or region == "centraluseuap" and routing != "canary"):
        raise ValueError("Select public or canary ARM explicitly; centraluseuap requires canary.")
    selected(profile["pythonVersions"], PYTHONS, "Python versions")
    selected(profile["services"], SERVICES, "services")
    targets = runpy.run_path(str(ROOT / "azext_iot/tests/_integration_target.py"))
    return targets["target"](region, endpoints[routing])


def resolve(history):
    producer = identity()
    previous = sorted(Path(history).glob("integration-plan-*/health-profile.json"))
    if previous:
        values = [json.loads(path.read_text(encoding="utf-8")) for path in previous]
        if any(value != values[0] for value in values) or values[0]["producer"] != producer:
            raise ValueError("Health profile history changed or belongs to another run.")
        return values[0]
    if int(required("SYSTEM_JOBATTEMPT")) > 1 and list(Path(history).glob("integration-plan-*")):
        raise ValueError("Existing plan is missing its health profile.")
    try:
        configuration = json.loads(os.environ.get("VALIDATION_PROFILES", ""))
    except json.JSONDecodeError:
        raise ValueError("ValidationProfiles must contain valid JSON.") from None
    build = ado_get(f"builds/{producer['build']}?api-version=7.1")
    return choose(configuration, build, producer)


def admission(now=None, check_cleanup=True):
    current = identity()
    runs = ado_get("builds?statusFilter=inProgress,notStarted&$top=100&api-version=7.1")["value"]
    if len(runs) >= 100:
        raise ValueError("Too many active builds to establish IoT admission.")
    for run in runs:
        family = run["definition"]["id"] == 147 or run["definition"]["name"] == "Azure IoT CLI - Integration Health"
        if family and str(run["id"]) != current["build"]:
            raise ValueError("Another IoT integration or health run is active or queued.")
    if not check_cleanup:
        return
    now = now or datetime.now(timezone.utc)
    cleanup = now.replace(hour=13, minute=0, second=0, microsecond=0)
    if cleanup <= now:
        cleanup += timedelta(days=1)
    if cleanup - now < timedelta(hours=7):
        raise ValueError("Insufficient time before the 13:00 UTC resource-group cleanup.")


def plan(output, history):
    value = resolve(history)
    profile = value["profile"]
    target = validate(profile)
    planner = runpy.run_path(str(ROOT / "azext_iot/tests/_ado_pipeline.py"))
    jobs = planner["plan"](profile["services"], profile["pythonVersions"], [profile["region"]],
                           target["endpoint"])
    output.mkdir(parents=True, exist_ok=True)
    for name, document in (("health-profile.json", value), ("plan.json", jobs)):
        (output / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    matrix = {f"py{version.replace('.', '')}_{profile['region']}": {"python": version, **target}
              for version in profile["pythonVersions"]}
    print(f"##vso[task.setvariable variable=matrix;isOutput=true]{json.dumps(matrix)}")
    for service in sorted(SERVICES):
        print(f"##vso[task.setvariable variable={service};isOutput=true]"
              f"{str(service in profile['services']).lower()}")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    arguments = parser.parse_args()
    plan(arguments.output, arguments.history)
