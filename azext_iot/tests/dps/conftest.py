# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from datetime import datetime, timezone
from time import sleep, time
from typing import Dict, Iterator, Optional
import json
import os
import tempfile
import uuid

import pytest
from azure.cli.core.azclierror import CLIInternalError
from filelock import FileLock
from knack.log import get_logger

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import assign_role_assignment
from azext_iot.tests.settings import (
    DynamoSettings,
    ENV_SET_TEST_IOTHUB_REQUIRED,
    ENV_SET_TEST_IOTHUB_OPTIONAL,
    ENV_SET_TEST_IOTDPS_OPTIONAL,
)

logger = get_logger(__name__)
HUB_USER_ROLE = "IoT Hub Data Contributor"
DPS_USER_ROLE = "Device Provisioning Service Data Contributor"
cli = EmbeddedCLI()

# Test Environment Variables
settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED,
    opt_env_set=list(set(
        ENV_SET_TEST_IOTHUB_OPTIONAL + ENV_SET_TEST_IOTDPS_OPTIONAL + ["azext_iot_dps_test_location"]
    ))
)
ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_LOCATION = settings.env.azext_iot_dps_test_location or "westus"
MAX_RBAC_ASSIGNMENT_TRIES = settings.env.azext_iot_rbac_max_tries if settings.env.azext_iot_rbac_max_tries else 10

# DPS instance strategy (timestamp + run-tag + age-based GC)
# ----------------------------------------------------------
# A subscription is limited to 10 DPS instances, the subscription is shared with the team, and
# several integration runs may execute concurrently. To stay within quota and never accumulate
# orphans we:
#   * Name each instance with a UTC timestamp + a per-run token + a kind suffix so concurrent runs
#     never collide (DPS names also map to globally-unique DNS).
#   * Tag each instance (intTest/runUid/kind/createdEpoch) so it can be discovered and garbage
#     collected reliably without fragile name parsing.
#   * Share a single instance per kind across all xdist workers of the same run (ref-counted), so a
#     run only ever holds 2 instances (hub + no-hub) regardless of "-n".
#   * Delete our own instances at teardown once the last worker is done, and additionally GC any
#     stale int-test instance older than ``DPS_GC_THRESHOLD_SECONDS`` (left behind by crashed runs).
INT_TEST_DPS_PREFIX = "aziotcli-int-dps"
INT_TEST_HUB_PREFIX = "aziotcli-int-hub"
DPS_GC_THRESHOLD_SECONDS = 24 * 60 * 60

# Unique per process; identifies a run when not executing under pytest-xdist. Under xdist all workers
# of the same run share ``workerinput["testrunuid"]`` instead.
_LOCAL_RUN_UID = uuid.uuid4().hex


def generate_hub_id() -> str:
    return f"aziotclitest-hub-{generate_generic_id()}"[:35]


def generate_dps_id() -> str:
    return f"aziotclitest-dps-{generate_generic_id()}"[:35]


def assign_iot_dps_dataplane_rbac_role(target_dps):
    account = cli.invoke("account show").as_json()
    user = account["user"]
    if user["name"] is None:
        raise CLIInternalError("User not found")
    assign_role_assignment(
        role=DPS_USER_ROLE,
        scope=target_dps["id"],
        assignee=user["name"],
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )


# IoT DPS fixtures
@pytest.fixture(scope="session")
def provisioned_iot_dps_module(request, provisioned_only_iot_hubs_session) -> Iterator[dict]:
    result = _iot_dps_provisioner(request, provisioned_only_iot_hubs_session)
    yield result
    if result:
        _iot_dps_removal(result)


@pytest.fixture(scope="session")
def provisioned_iot_dps_no_hub_module(request) -> Iterator[dict]:
    result = _iot_dps_provisioner(request)
    yield result
    if result:
        _iot_dps_removal(result)


def _get_run_uid(request) -> str:
    """Return an id that is identical for every worker of the same test run.

    Under pytest-xdist all workers receive the same ``testrunuid``; outside of xdist we fall back
    to a per-process uuid so each fresh invocation is treated as its own run.
    """
    workerinput = getattr(request.config, "workerinput", None)
    if workerinput and workerinput.get("testrunuid"):
        return workerinput["testrunuid"]
    return _LOCAL_RUN_UID


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


# --- Cross-worker shared-resource coordination -------------------------------------------------
# A single instance per kind is shared by every xdist worker of the same run. State is a small JSON
# file (``{"name", "refcount"}``) guarded by a file lock so only the first worker creates the
# resource and the last worker out deletes it. ``kind`` is one of "h" (hub-linked DPS), "nh"
# (no-hub DPS) or "hub" (the shared IoT Hub).
def _state_paths(run_uid: str, kind: str):
    base = os.path.join(tempfile.gettempdir(), f"{INT_TEST_DPS_PREFIX}-{run_uid}-{kind}")
    return base + ".lock", base + ".json"


def _read_state(state_path: str) -> Optional[Dict]:
    try:
        with open(state_path, encoding="utf-8") as state_file:
            return json.load(state_file)
    except (OSError, ValueError):
        return None


def _write_state(state_path: str, state: Dict) -> None:
    with open(state_path, "w", encoding="utf-8") as state_file:
        json.dump(state, state_file)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _shared_acquire(run_uid: str, kind: str, create_fn, find_fn) -> dict:
    """Create or reuse the shared resource for ``kind``, bumping its reference count."""
    lock_path, state_path = _state_paths(run_uid, kind)
    with FileLock(lock_path):
        state = _read_state(state_path)
        if state:
            resource = find_fn(state["name"])
            if resource:
                state["refcount"] += 1
                _write_state(state_path, state)
                return resource
        name, resource = create_fn(run_uid, kind)
        _write_state(state_path, {"name": name, "refcount": 1})
        return resource


def _shared_release(run_uid: str, kind: str, delete_fn) -> None:
    """Drop one reference to the shared resource for ``kind``; the last worker deletes it."""
    lock_path, state_path = _state_paths(run_uid, kind)
    with FileLock(lock_path):
        state = _read_state(state_path)
        if not state:
            return
        state["refcount"] -= 1
        if state["refcount"] <= 0:
            delete_fn(state["name"])
            _safe_remove(state_path)
        else:
            _write_state(state_path, state)


# --- Age-based garbage collection of orphans (from crashed runs) -------------------------------
def _gc_stale_resources_once(run_uid: str) -> None:
    """Reap int-test resources older than the threshold, exactly once per run."""
    gc_lock = os.path.join(tempfile.gettempdir(), f"{INT_TEST_DPS_PREFIX}-gc.lock")
    gc_marker = os.path.join(tempfile.gettempdir(), f"{INT_TEST_DPS_PREFIX}-gc-{run_uid}.done")
    with FileLock(gc_lock):
        if os.path.exists(gc_marker):
            return
        try:
            _gc_stale(run_uid, INT_TEST_DPS_PREFIX, _list_dps, _delete_dps)
            _gc_stale(run_uid, INT_TEST_HUB_PREFIX, _list_hubs, _delete_hub)
        finally:
            with open(gc_marker, "w", encoding="utf-8"):
                pass


def _gc_stale(current_run_uid: str, prefix: str, list_fn, delete_fn) -> None:
    now = time()
    for resource in list_fn():
        name = resource.get("name", "")
        if not name.startswith(prefix):
            continue
        tags = resource.get("tags") or {}
        # Only reap resources we positively recognise as expired int-test artifacts. Anything
        # missing the marker tags or an unparseable timestamp is left untouched (defensive against
        # deleting manually-created or in-use resources).
        if tags.get("intTest") != "true" or tags.get("runUid") == current_run_uid:
            continue
        try:
            age = now - int(tags.get("createdEpoch"))
        except (TypeError, ValueError):
            continue
        if age > DPS_GC_THRESHOLD_SECONDS:
            logger.info(f"Garbage-collecting stale int-test resource '{name}' (age {int(age)}s).")
            delete_fn(name)


# --- DPS helpers -------------------------------------------------------------------------------
def _list_dps() -> list:
    return cli.invoke('iot dps list -g "{}"'.format(ENTITY_RG)).as_json() or []


def _find_dps_by_name(dps_name: str) -> Optional[dict]:
    for dps in _list_dps():
        if dps["name"] == dps_name:
            return dps
    return None


def _delete_dps(dps_name: str) -> None:
    cli.invoke(f"iot dps delete --name {dps_name} --resource-group {ENTITY_RG}")


def _hub_link_host_name(iot_hub: Dict) -> str:
    """Return the hub hostname the way DPS actually links it.

    DPS links the hub from its connection string and records the linked hub by the
    connection string's ``HostName``. On GWv2/TLS 1.3 hubs that is the device-facing
    hostname (``<name>.device.azure-devices.net``) rather than the classic
    ``<name>.azure-devices.net``. Enrollment ``--iot-hubs`` and the registration
    ``assignedHub`` must use this same value, so derive it from the connection string.
    """
    for segment in iot_hub["connectionString"].split(";"):
        if segment.lower().startswith("hostname="):
            return segment.split("=", 1)[1]
    return "{}.azure-devices.net".format(iot_hub["name"])


def _link_hub(dps_name: str, iot_hub: Dict) -> str:
    linked_hubs = cli.invoke(
        "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
    ).as_json()
    hub_host_name = _hub_link_host_name(iot_hub)
    if hub_host_name not in [hub["name"] for hub in linked_hubs]:
        cli.invoke(
            f"iot dps linked-hub create --dps-name {dps_name} -g {ENTITY_RG} "
            f"--connection-string {iot_hub['connectionString']}"
        )
    return hub_host_name


def _unlink_all_hubs(dps_name: str) -> None:
    linked_hubs = cli.invoke(
        "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
    ).as_json()
    for hub in linked_hubs:
        cli.invoke(
            f"iot dps linked-hub delete --dps-name {dps_name} -g {ENTITY_RG} --linked-hub {hub['name']}"
        )


def _create_managed_dps(run_uid: str, kind: str, iot_hub: Optional[Dict]) -> tuple:
    """Create a tagged, run-scoped DPS and perform one-time RBAC + hub linking (creator only)."""
    name = f"{INT_TEST_DPS_PREFIX}-{_timestamp()}-{run_uid[:8]}-{kind}"
    tags = f"intTest=true runUid={run_uid} kind={kind} createdEpoch={int(time())}"
    if iot_hub:
        tags += f" hubname={iot_hub['name']}"
    target_dps = cli.invoke(
        f"iot dps create --name {name} --resource-group {ENTITY_RG} "
        f"--location {ENTITY_LOCATION} --tags {tags}"
    ).as_json()
    assign_iot_dps_dataplane_rbac_role(target_dps)
    if iot_hub:
        _link_hub(name, iot_hub)
    else:
        _unlink_all_hubs(name)
        # Allow data-plane RBAC propagation to settle on the fresh instance.
        sleep(60)
    return name, target_dps


def _create_unmanaged_dps(dps_name: str, iot_hub: Optional[Dict]) -> dict:
    base_command = f"iot dps create --name {dps_name} --resource-group {ENTITY_RG} --location {ENTITY_LOCATION}"
    if iot_hub:
        base_command += f" --tags hubname={iot_hub['name']}"
    return cli.invoke(base_command).as_json()


def _iot_dps_provisioner(request, iot_hub: Optional[Dict] = None) -> dict:
    """Create or reuse a device provisioning service for testing purposes."""
    use_managed = not settings.env.azext_iot_testdps
    kind = "h" if iot_hub else "nh"
    run_uid = _get_run_uid(request)

    if use_managed:
        _gc_stale_resources_once(run_uid)
        target_dps = _shared_acquire(
            run_uid,
            kind,
            create_fn=lambda ru, k: _create_managed_dps(ru, k, iot_hub),
            find_fn=_find_dps_by_name,
        )
        dps_name = target_dps["name"]
        hub_host_name = _hub_link_host_name(iot_hub) if iot_hub else None
    else:
        dps_name = settings.env.azext_iot_testdps
        target_dps = _find_dps_by_name(dps_name)
        if not target_dps:
            logger.error(f"DPS {dps_name} specified in pytest settings not found. DPS will be created")
            target_dps = _create_unmanaged_dps(dps_name, iot_hub)
        assign_iot_dps_dataplane_rbac_role(target_dps)
        hub_host_name = _link_hub(dps_name, iot_hub) if iot_hub else None
        if not iot_hub:
            _unlink_all_hubs(dps_name)

    return {
        "name": dps_name,
        "resourceGroup": ENTITY_RG,
        "dps": target_dps,
        "connectionString": get_dps_cstring(dps_name, ENTITY_RG),
        "hubHostName": hub_host_name,
        "hubConnectionString": iot_hub["connectionString"] if iot_hub else None,
        "certificates": [],
        "_runUid": run_uid if use_managed else None,
        "_kind": kind if use_managed else None,
    }


def get_dps_cstring(dps_name: str, dps_rg: str, policy: str = "provisioningserviceowner") -> str:
    return cli.invoke(
        "iot dps connection-string show -n {} -g {} --policy-name {}".format(
            dps_name, dps_rg, policy
        )
    ).as_json()["connectionString"]


def _iot_dps_removal(dps):
    for cert in dps["certificates"]:
        if os.path.exists(cert):
            try:
                os.remove(cert)
            except OSError as e:
                logger.error(f"Failed to remove {cert}. {e}")
    # Release this run's shared DPS; the last worker out deletes it. An env-pinned DPS
    # (azext_iot_testdps) carries no run id and is intentionally left in place. Any instance that
    # escapes deletion (e.g. crashed worker) is reaped by the age-based GC on a subsequent run.
    run_uid = dps.get("_runUid")
    kind = dps.get("_kind")
    if run_uid and kind:
        _shared_release(run_uid, kind, delete_fn=_delete_dps)


# IoT Hub fixtures for DPS
@pytest.fixture(scope="session")
def provisioned_only_iot_hubs_session(request) -> Iterator[dict]:
    result = _iot_hubs_provisioner(request)
    yield result
    if result:
        _iot_hubs_removal(result)


def _list_hubs() -> list:
    return cli.invoke('iot hub list -g "{}"'.format(ENTITY_RG)).as_json() or []


def _find_hub_by_name(name: str) -> Optional[dict]:
    for hub in _list_hubs():
        if hub["name"] == name:
            return hub
    return None


def _create_managed_hub(run_uid: str, kind: str) -> tuple:
    name = f"{INT_TEST_HUB_PREFIX}-{_timestamp()}-{run_uid[:8]}"
    target_hub = cli.invoke(
        f"iot hub create -n {name} -g {ENTITY_RG} --sku S1 "
        f"--tags intTest=true runUid={run_uid} kind=hub createdEpoch={int(time())}"
    ).as_json()
    return name, target_hub


def _delete_hub(name: str) -> None:
    if not cli.invoke(f"iot hub delete -n {name} -g {ENTITY_RG}").success():
        logger.error(f"Failed to delete iot hub resource {name}.")


def _iot_hubs_provisioner(request):
    """Provision (or reuse) a single IoT Hub shared by all workers of the run for DPS tests."""
    if settings.env.azext_iot_testdps_hub:
        name = settings.env.azext_iot_testdps_hub
        target_hub = _find_hub_by_name(name)
        if not target_hub:
            logger.error(f"Hub {name} specified in pytest settings not found. Hub will be created")
            target_hub = cli.invoke(f"iot hub create -n {name} -g {ENTITY_RG} --sku S1").as_json()
        run_uid = None
    else:
        run_uid = _get_run_uid(request)
        target_hub = _shared_acquire(
            run_uid, "hub", create_fn=_create_managed_hub, find_fn=_find_hub_by_name
        )
        name = target_hub["name"]

    return {
        "hub": target_hub,
        "name": name,
        "rg": ENTITY_RG,
        "connectionString": _get_hub_connection_string(name, ENTITY_RG),
        "_runUid": run_uid,
    }


def _get_hub_connection_string(name, rg, policy="iothubowner"):
    return cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            name, rg, policy
        )
    ).as_json()["connectionString"]


def _iot_hubs_removal(hub_result):
    # Release this run's shared hub; the last worker out deletes it. An env-pinned hub
    # (azext_iot_testdps_hub) carries no run id and is intentionally left in place.
    run_uid = hub_result.get("_runUid")
    if run_uid:
        _shared_release(run_uid, "hub", delete_fn=_delete_hub)
