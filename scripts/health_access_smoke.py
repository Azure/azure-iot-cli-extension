# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Nonqualifying live access checks; never provision or delete IoT resources."""

import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from packaging.version import Version

from release_monitor import verify_bundle


WRITES = {
    "DPS": "Microsoft.Devices/provisioningServices/write",
    "HubControl": "Microsoft.Devices/IotHubs/write",
    "HubData": "Microsoft.Authorization/roleAssignments/write",
    "ADU": "Microsoft.DeviceUpdate/accounts/write",
    "ADR": "Microsoft.DeviceRegistry/namespaces/write",
}
COMMANDS = {
    "DPS": ["iot", "dps", "list"],
    "HubControl": ["iot", "hub", "list"],
    "HubData": ["iot", "hub", "list"],
    "ADU": ["iot", "du", "account", "list"],
    "ADR": ["iot", "adr", "ns", "list"],
}


def az(*arguments):
    result = subprocess.run(
        ["az", *arguments, "--only-show-errors", "--output", "json"],
        capture_output=True, text=True, timeout=180, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def permits(grants, action):
    action = action.casefold()
    return any(
        any(fnmatch.fnmatchcase(action, value.casefold()) for value in grant["actions"])
        and not any(fnmatch.fnmatchcase(action, value.casefold()) for value in grant.get("notActions", []))
        for grant in grants
    )


def main():
    service = os.environ["SMOKE_SERVICE"]
    output = Path(os.environ["SMOKE_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"mode": "access-smoke", "qualifiesFullSuite": False, "service": service, "checks": []}

    def check(name, operation):
        try:
            value = operation()
            evidence["checks"].append({"name": name, "status": "passed"})
            return value
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
            evidence["checks"].append({"name": name, "status": "failed", "error": (detail or str(error))[-3000:]})
            return None

    try:
        bundle = Path(os.environ["SMOKE_BUNDLE"])
        manifest = verify_bundle(
            bundle, extension="azure-iot", cloud=os.environ["MONITOR_CLOUD"],
            slot=os.environ["MONITOR_TRACK"], automation_commit=os.environ["BUILD_SOURCEVERSION"],
        )
        evidence.update(build=os.environ["BUILD_BUILDID"], manifest=manifest)
        az("extension", "add", "--source", str(bundle / manifest["wheel"]["name"]), "--yes")
        installed = az("extension", "show", "--name", "azure-iot", "--query", "version")
        if Version(installed) != Version(manifest["source"]["version"]):
            raise ValueError("Installed CLI differs from the frozen source-built wheel.")
        cloud = az("cloud", "show")
        subscription = az("account", "show", "--query", "id")
        if cloud["name"] != manifest["cloud"] or subscription != os.environ["MONITOR_SUBSCRIPTION"]:
            raise ValueError("The pipeline service connection selected an unexpected cloud or subscription.")
        evidence["checks"].append({"name": "connection_and_frozen_cli", "status": "passed"})
        group = os.environ["MONITOR_RESOURCE_GROUP"]
        endpoint = cloud["endpoints"]["resourceManager"].rstrip("/")
        if endpoint != os.environ["MONITOR_ENDPOINT"].rstrip("/"):
            raise ValueError("The service connection ARM endpoint differs from the reviewed monitor.")
        check("service_arm_list", lambda: az(*COMMANDS[service], "--resource-group", group, "--query", "length(@)"))
        url = (
            f"{endpoint}/subscriptions/{subscription}/resourceGroups/{quote(group, safe='')}"
            "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"
        )
        grants = check("read_effective_permissions", lambda: az("rest", "--method", "get", "--url", url))
        if grants is not None:
            allowed = permits(grants["value"], WRITES[service])
            evidence["checks"].append({
                "name": "listed_provisioning_permission", "action": WRITES[service],
                "status": "passed" if allowed else "failed",
                "note": "Listed RBAC action only; resource deployment and conditional grants are not exercised.",
            })
        if service == "HubData":
            hubs = check("find_existing_hub", lambda: az(
                "iot", "hub", "list", "--resource-group", group, "--query", "[].name",
            ))
            if hubs:
                check("existing_hub_query_select_star", lambda: az(
                    "iot", "hub", "device-identity", "list", "--hub-name", hubs[0], "--resource-group", group,
                    "--auth-type", "login", "--top", "1", "--query", "length(@)",
                ))
                check("existing_hub_data_read", lambda: az(
                    "iot", "hub", "query", "--hub-name", hubs[0], "--resource-group", group,
                    "--auth-type", "login", "--query-command", "SELECT COUNT() FROM devices",
                ))
                host = check("read_hub_hostname", lambda: az(
                    "iot", "hub", "show", "--name", hubs[0], "--resource-group", group,
                    "--query", "properties.hostName",
                ))
                if host:
                    suffix = {
                        "AzureCloud": ".azure-devices.net",
                        "AzureUSGovernment": ".azure-devices.us",
                        "AzureChinaCloud": ".azure-devices.cn",
                    }[cloud["name"]]
                    if not re.fullmatch(r"[a-z0-9-]+" + re.escape(suffix), host):
                        raise ValueError("The Hub hostname is outside the expected cloud service domain.")
                    for api_version in ("2024-03-31", "2026-11-01"):
                        check(f"same_query_api_{api_version}", lambda version=api_version: az(
                            "rest", "--method", "post",
                            "--resource", "https://iothubs.azure.net",
                            "--url", f"https://{host}/devices/query?api-version={version}",
                            "--body", json.dumps({"query": "SELECT COUNT() FROM devices"}),
                        ))
            else:
                evidence["checks"].append({
                    "name": "existing_hub_data_read", "status": "not_tested",
                    "reason": "No readable existing test Hub; this access-only smoke does not create one.",
                })
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        evidence["checks"].append({"name": "setup", "status": "failed", "error": (detail or str(error))[-3000:]})
    finally:
        text = json.dumps(evidence, indent=2)
        (output / "access-smoke.json").write_text(text, encoding="utf-8")
        print(text)
    return int(any(item["status"] == "failed" for item in evidence["checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
