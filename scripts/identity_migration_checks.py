# Copyright (c) Microsoft Corporation. All rights reserved.
"""Temporary, explicitly owned migration probes; never release qualification."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4


SUB = "a386d5ea-ea90-441a-8263-d816368c84a1"


def az(*args, expected_failure=False):
    result = subprocess.run(
        ["az", *args, "--only-show-errors", "--output", "json"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if expected_failure:
        if result.returncode == 0:
            raise RuntimeError("The conflicting create unexpectedly succeeded.")
        if "BlobAlreadyExists" not in result.stderr and "already exists" not in result.stderr:
            raise RuntimeError("The conflicting create failed for an unexpected reason: " + result.stderr[:1000])
        return None
    if result.returncode:
        raise RuntimeError("Probe command failed: " + result.stderr[:2000])
    return json.loads(result.stdout) if result.stdout.strip() else None


def resource_probe(group):
    if group not in ("cli-int-test-rg", "ops-cli-int-test-rg"):
        raise ValueError("Probe group is outside the approved test scopes.")
    nonce = uuid4().hex
    name = "mi-ado-probe-" + nonce[:16]
    role = str(uuid4())
    owner = "cli-identity-probe:" + nonce
    resource = None
    assignment = None
    role_attempted = False
    evidence = Path("migration-probe")
    evidence.mkdir(exist_ok=True)
    state = {"group": group, "name": name, "nonce": nonce, "role": role}
    (evidence / "state.json").write_text(json.dumps(state))
    if any(value["name"] == name for value in az("identity", "list", "--subscription", SUB, "-g", group)):
        raise ValueError("Refusing to reuse an existing probe resource.")
    try:
        resource = az(
            "identity", "create", "--subscription", SUB, "-g", group, "-n", name, "--location", "westus2",
            "--tags", "MigrationProbe=" + nonce, "Build=" + os.environ["BUILD_BUILDID"],
        )
        state["resource"] = resource["id"]
        (evidence / "state.json").write_text(json.dumps(state))
        print("Created exact probe resource: " + resource["id"], flush=True)
        current = az("identity", "show", "--subscription", SUB, "-g", group, "-n", name)
        if current["id"].lower() != resource["id"].lower() or current["tags"].get("MigrationProbe") != nonce:
            raise ValueError("Probe ownership changed.")
        role_attempted = True
        assignment = az(
            "role", "assignment", "create", "--subscription", SUB, "--name", role,
            "--assignee", os.environ["AZURE_CLIENT_ID"], "--role", "Reader", "--scope", resource["id"],
            "--description", owner,
        )
        if assignment["principalId"].lower() != os.environ["PROBE_PRINCIPAL_ID"].lower():
            raise ValueError("Client-ID resolution did not select the current UAMI service principal.")
        print("Verified owned resource creation and client-ID-to-principal role assignment.", flush=True)
    finally:
        if resource is not None:
            current = az("identity", "show", "--subscription", SUB, "-g", group, "-n", name)
            if current["tags"].get("MigrationProbe") != nonce:
                raise ValueError("Refusing cleanup after probe ownership changed.")
            if role_attempted and assignment is None:
                raise RuntimeError("Role creation did not return a receipt; retaining the owned probe for reconciliation.")
            if assignment:
                if assignment.get("description") != owner:
                    raise ValueError("Refusing cleanup of an unowned role assignment.")
                az("role", "assignment", "delete", "--subscription", SUB, "--ids", assignment["id"])
                url = "https://management.azure.com" + assignment["id"] + "?api-version=2022-04-01"
                for _ in range(6):
                    result = subprocess.run(
                        ["az", "rest", "--method", "get", "--url", url, "--output", "json"],
                        capture_output=True, text=True, timeout=60, check=False,
                    )
                    if result.returncode and "RoleAssignmentNotFound" in result.stderr:
                        break
                    if result.returncode:
                        raise RuntimeError("Cannot verify exact role absence; retaining the probe scope.")
                    time.sleep(5)
                else:
                    raise RuntimeError("Owned role remains; retaining the probe scope.")
            az("identity", "delete", "--subscription", SUB, "-g", group, "-n", name)
            if any(value["name"] == name for value in az("identity", "list", "--subscription", SUB, "-g", group)):
                raise RuntimeError("Owned probe resource is not confirmed absent.")
            print("Verified owned role/resource cleanup; no probe resources retained.", flush=True)
            state["cleanup"] = "passed"
            (evidence / "state.json").write_text(json.dumps(state))


def blob_probe():
    nonce = uuid4().hex
    name = f"ado-probes/{os.environ['BUILD_BUILDID']}/{nonce}/proof.txt"
    args = ("--account-name", "azedgecli", "--container-name", "drop", "--name", name, "--auth-mode", "login")
    content = ("CLI migration probe " + nonce).encode()
    with tempfile.TemporaryDirectory() as directory:
        source, downloaded = Path(directory) / "source", Path(directory) / "downloaded"
        source.write_bytes(content)
        created = False
        try:
            if az("storage", "blob", "exists", *args)["exists"]:
                raise ValueError("Refusing to reuse an existing probe blob.")
            az("storage", "blob", "upload", *args, "--file", str(source), "--overwrite", "false")
            created = True
            az("storage", "blob", "download", *args, "--file", str(downloaded), "--overwrite", "false")
            if downloaded.read_bytes() != content:
                raise RuntimeError("Uploaded probe bytes differ.")
            source.write_bytes(b"conflicting probe content")
            az("storage", "blob", "upload", *args, "--file", str(source), "--overwrite", "false",
               expected_failure=True)
            az("storage", "blob", "download", *args, "--file", str(downloaded), "--overwrite", "true")
            if downloaded.read_bytes() != content:
                raise RuntimeError("The original probe blob was overwritten.")
            print("Verified scoped Blob write/read and rejection of conflicting overwrite.", flush=True)
        finally:
            if created:
                az("storage", "blob", "download", *args, "--file", str(downloaded), "--overwrite", "true")
                if downloaded.read_bytes() != content:
                    raise ValueError("Refusing deletion after probe content changed.")
                az("storage", "blob", "delete", *args)
                if az("storage", "blob", "exists", *args)["exists"]:
                    raise RuntimeError("Probe blob is not confirmed absent.")
                print("Verified deletion of the exact owned probe blob.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", default="")
    args = parser.parse_args()
    if args.group:
        resource_probe(args.group)
    else:
        blob_probe()
