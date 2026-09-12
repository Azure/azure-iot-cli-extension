# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Optional, narrow receipts for the serial runner's two DPS fixtures and shared Hub."""

import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone

from filelock import FileLock
import pytest

from azext_iot.tests.dps import _phase
from azext_iot.tests.dps._phase_manifest import normalize_nodeid

DIRECTORY_ENV = "azext_iot_dps_phase_receipts"
RUN_UID_ENV = "azext_iot_dps_run_uid"
SUBSCRIPTION_ENV = "azext_iot_dps_test_subscription"
RESOURCE_GROUP_ENV = "azext_iot_dps_test_resource_group"


def settings():
    values = [os.environ.get(name) for name in (DIRECTORY_ENV, RUN_UID_ENV, SUBSCRIPTION_ENV, RESOURCE_GROUP_ENV)]
    if not any(values):
        return None
    directory, uid, subscription, group = values
    if not all(values) or not re.fullmatch(r"[0-9a-f]{32}", uid or ""):
        raise pytest.UsageError("DPS phase receipts require a directory, 32-hex run UID, subscription and resource group.")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription):
        raise pytest.UsageError("DPS phase receipts require a subscription UUID.")
    if not Path(directory).is_absolute() or not Path(directory).is_dir():
        raise pytest.UsageError("DPS phase receipt directory must be an existing absolute directory.")
    return Path(directory), uid, subscription, group


def write(name, payload, exclusive=False):
    config = settings()
    if not config:
        return
    directory, uid, subscription, _ = config
    payload = {
        "phase": _phase.get_phase(), "run_uid": uid, "subscription": subscription,
        "recorded_at": datetime.now(timezone.utc).isoformat(), **payload,
    }
    destination = directory / name
    with FileLock(str(destination) + ".lock"):
        if exclusive and destination.exists():
            raise RuntimeError(f"DPS phase refuses to repeat recorded mutation: {name}")
        temporary = destination.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)


def session_started(config):
    if settings() and not hasattr(config, "workerinput"):
        write("started.json", {"started": True}, exclusive=True)


def selected(config, items):
    if settings():
        worker = getattr(config, "workerinput", {}).get("workerid", "controller")
        write(f"selection-{worker}.json", {
            "selected": len(items), "nodeids": sorted(normalize_nodeid(item.nodeid) for item in items),
        })


def before_create(name, resource_group, run_uid, kind):
    config = settings()
    if not config:
        return
    _, uid, subscription, expected_group = config
    expected_uid = uid if _phase.get_phase() == _phase.REGULAR else f"{uid}-service-sas"
    if run_uid != expected_uid or kind not in ("h", "nh", "hub") or resource_group != expected_group:
        raise RuntimeError("Resource create does not match this phase's run UID/kind/resource group.")
    resource_type = "IotHubs" if kind == "hub" else "provisioningServices"
    write(f"owned-{kind}.json", {
        "name": name, "kind": kind, "resource_group": resource_group,
        "id": f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/Microsoft.Devices/{resource_type}/{name}",
        "tags": {"intTest": "true", "runUid": run_uid, "kind": kind},
        "create_attempted": True,
    }, exclusive=True)


def _owned(name):
    config = settings()
    if not config:
        return None
    directory, _, _, _ = config
    matches = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in directory.glob("owned-*.json")
    ]
    matches = [(path, record) for path, record in matches if record["name"] == name]
    if len(matches) != 1:
        raise RuntimeError("DPS phase refuses deletion without its exact pre-create ownership receipt.")
    return matches[0][1]


def after_create(name, resource):
    record = _owned(name)
    if record:
        resource = resource if isinstance(resource, dict) else {}
        state = (resource.get("properties") or {}).get("provisioningState")
        ready = (
            resource.get("id", "").lower() == record["id"].lower()
            and str(state).lower() == "succeeded"
            and all((resource.get("tags") or {}).get(key) == value for key, value in record["tags"].items())
        )
        write(f"created-{record['kind']}.json", {
            "id": record["id"], "create_completed": ready, "provisioning_state": state,
        }, exclusive=True)


def before_delete(name, resource=None):
    record = _owned(name)
    if not record:
        return True
    if resource is None:
        return False
    if (resource.get("id", "").lower() != record["id"].lower()
            or any((resource.get("tags") or {}).get(key) != value for key, value in record["tags"].items())):
        raise RuntimeError("DPS phase refuses deletion: current resource ownership does not match its receipt.")
    if str((resource.get("properties") or {}).get("provisioningState", "")).lower() == "deleting":
        write(f"deleting-{record['kind']}.json", {"id": record["id"], "already_deleting": True})
        return False
    write(f"delete-{record['kind']}.json", {"id": record["id"], "delete_attempted": True}, exclusive=True)
    return True


def after_delete(name):
    record = _owned(name)
    if record:
        write(f"deleted-{record['kind']}.json", {"id": record["id"], "delete_completed": True}, exclusive=True)
