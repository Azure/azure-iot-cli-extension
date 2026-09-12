# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import ExitStack
from datetime import datetime, timezone
from time import sleep, time
from typing import Dict, Iterator, Optional
import json
import os
import tempfile
import uuid

import pytest
from azure.cli.core.azclierror import CLIInternalError
from azure.core.exceptions import HttpResponseError
from azure.mgmt.core.tools import parse_resource_id
from filelock import FileLock
from knack.log import get_logger

from azext_iot._factory import iot_hub_service_factory, iot_service_provisioning_factory
from azext_iot.common._azure import IOT_SERVICE_CS_TEMPLATE
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import assign_role_assignment, invoke_checked
from azext_iot.tests.dps import _phase, _phase_receipts, _phase_runtime
from azext_iot.tests.settings import (
    DynamoSettings,
    ENV_SET_TEST_IOTHUB_REQUIRED,
    ENV_SET_TEST_IOTHUB_OPTIONAL,
    ENV_SET_TEST_IOTDPS_OPTIONAL,
    HUB_TEST_LOCATION,
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
DPS_NO_HUB_LOCK_TIMEOUT_SECONDS = 300

# Unique per process; identifies a run when not executing under pytest-xdist. Under xdist all workers
# of the same run share ``workerinput["testrunuid"]`` instead.
_LOCAL_RUN_UID = uuid.uuid4().hex


def pytest_configure(config):
    _phase.configure(config)
    receipts = _phase_receipts.settings()
    if receipts:
        if settings.env.azext_iot_testdps or settings.env.azext_iot_testdps_hub or settings.env.azext_iot_testhub:
            raise pytest.UsageError("Isolated DPS phases reject supplied resource pins, including pytest configuration pins.")
        if ENTITY_RG != receipts[3] or ENTITY_LOCATION != "centraluseuap" or HUB_TEST_LOCATION != "centraluseuap":
            raise pytest.UsageError("Isolated DPS phases require the explicit test resource group and centraluseuap fixtures.")
        _phase_runtime.require_linux()
        from azext_iot.tests import helpers
        runtime = _phase_runtime.activate(receipts[2], existing=(cli, helpers.cli))
        runtime.__enter__()
        config.add_cleanup(lambda: runtime.__exit__(None, None, None))


def pytest_sessionstart(session):
    _phase_receipts.session_started(session.config)
    _phase_runtime.start_worker(session)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    _phase.select_items(config, items)
    _phase_receipts.selected(config, items)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item):
    outcome = yield
    _phase.require_requested_coverage(item, outcome.get_result())


def generate_hub_id() -> str:
    return f"aziotclitest-hub-{generate_generic_id()}"[:35]


def generate_dps_id() -> str:
    return f"aziotclitest-dps-{generate_generic_id()}"[:35]


def assign_iot_dps_dataplane_rbac_role(target_dps):
    _assign_current_user_role(DPS_USER_ROLE, target_dps["id"])


def _assign_fixture_role(**kwargs):
    if _phase_receipts.settings():
        return _phase_runtime.assign_role_assignment_once(**kwargs)
    return assign_role_assignment(**kwargs)


def _assign_current_user_role(role: str, scope: str):
    account = cli.invoke("account show").as_json()
    user = account["user"]
    if user["name"] is None:
        raise CLIInternalError("User not found")
    _assign_fixture_role(
        role=role,
        scope=scope,
        assignee=user["name"],
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    # ARM role-assignment visibility is not data-plane readiness. Login is the
    # first service-auth phase, including for env-pinned resources, so retain
    # the bounded propagation wait AFTER ensuring the caller's data role.
    sleep(60)


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


@pytest.fixture
def exclusive_iot_dps_no_hub(request, provisioned_iot_dps_no_hub_module):
    """Keep temporary Hub links out of concurrent no-Hub registration tests."""
    resource = provisioned_iot_dps_no_hub_module
    with _no_hub_usage_lock(request):
        _assert_no_linked_hubs(resource, "before")
        try:
            yield resource
        finally:
            _assert_no_linked_hubs(resource, "after")


def _no_hub_usage_lock(request):
    # Resource reference-count locking protects setup/teardown, not test-body mutations.
    lock_path, _ = _state_paths(_get_run_uid(request), "nh-usage")
    return FileLock(lock_path, timeout=DPS_NO_HUB_LOCK_TIMEOUT_SECONDS)


def _assert_no_linked_hubs(resource, phase):
    linked_hubs = invoke_checked(
        cli,
        f"iot dps linked-hub list --dps-name {resource['name']} -g {resource['resourceGroup']}",
        description="Read shared no-Hub DPS links",
    ).as_json()
    empty = linked_hubs == []
    assert empty, f"Shared no-Hub DPS '{resource['name']}' must have no linked hubs {phase} the isolated test."


def _get_run_uid(request) -> str:
    """Return an id that is identical for every worker of the same test run.

    Under pytest-xdist all workers receive the same ``testrunuid``; outside of xdist we fall back
    to a per-process uuid so each fresh invocation is treated as its own run.
    """
    workerinput = getattr(request.config, "workerinput", None)
    run_uid = os.environ.get(_phase_receipts.RUN_UID_ENV) or (
        workerinput["testrunuid"] if workerinput and workerinput.get("testrunuid") else _LOCAL_RUN_UID
    )
    # Even if an external runner reuses an xdist run UID, never acquire a regular
    # phase's DLA-true fixture for SAS (or silently change its resource policy).
    return run_uid if _phase.get_phase() == _phase.REGULAR else f"{run_uid}-service-sas"


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
        with ExitStack() as cleanup:
            cleanup.callback(
                _cleanup_created_resource, name, run_uid, kind, find_fn,
                _delete_hub if kind == "hub" else _delete_dps,
            )
            _write_state(state_path, {"name": name, "refcount": 1})
            cleanup.pop_all()
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
        _gc_stale(run_uid, INT_TEST_DPS_PREFIX, _list_dps, _delete_dps)
        # Only orphan discovery needs a Hub list. A known canary pagination failure
        # must not block creation of this run's uniquely named, directly addressed Hub.
        try:
            hubs = _list_hubs()
        except HttpResponseError as error:
            if error.status_code != 502 or getattr(error.error, "code", None) != "ProviderError":
                raise
            logger.warning(
                "Deferring stale DPS-test Hub cleanup: Hub list returned the backend-confirmed "
                "HTTP 502 ProviderError. No partial list is used; retry cleanup on the next run."
            )
        else:
            _gc_stale(run_uid, INT_TEST_HUB_PREFIX, lambda: hubs, _delete_hub)
        # Unexpected failures must not mark GC complete for the other workers.
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
    return cli.invoke('iot dps list -g "{}"'.format(ENTITY_RG), capture_stderr=True).as_json() or []


def _assert_local_auth_policy(resource: Dict) -> None:
    expected = _phase.local_auth_disabled()
    assert (resource.get("properties") or {}).get("disableLocalAuth") is expected, (
        f"Integration resource {resource.get('name')} must have disableLocalAuth={str(expected).lower()} "
        f"for the {_phase.get_phase()} phase. "
        "Fixtures will not change a supplied resource's auth policy."
    )


def _dps_service_connection_string(resource: Dict) -> str:
    """Retrieve only the selected fixture's service credential, without EmbeddedCLI output logging."""
    properties = resource.get("properties") or {}
    hostname = properties.get("serviceOperationsHostName")
    subscription = parse_resource_id(resource.get("id", "")).get("subscription")
    if not hostname or not subscription:
        raise CLIInternalError(
            "The service-sas phase requires a DPS ARM ID and serviceOperationsHostName before retrieving credentials."
        )
    client = iot_service_provisioning_factory(cli.az_cli, subscription_id=subscription)
    policy = client.iot_dps_resource.list_keys_for_key_name(
        provisioning_service_name=resource["name"], resource_group_name=ENTITY_RG,
        key_name="provisioningserviceowner",
    )
    if not isinstance(policy, dict) or not policy.get("keyName") or not policy.get("primaryKey"):
        raise CLIInternalError("The service-sas phase requires a usable DPS service-policy credential.")
    return IOT_SERVICE_CS_TEMPLATE.format(hostname, policy["keyName"], policy["primaryKey"])


def _find_dps_by_name(dps_name: str) -> Optional[dict]:
    # The CLI show handler turns an expected ARM 404 into SystemExit(3).
    receipt_config = _phase_receipts.settings()
    client = iot_service_provisioning_factory(cli.az_cli, subscription_id=receipt_config[2]) if receipt_config else (
        iot_service_provisioning_factory(cli.az_cli)
    )
    try:
        return client.iot_dps_resource.get(provisioning_service_name=dps_name, resource_group_name=ENTITY_RG)
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise


def _delete_dps(dps_name: str) -> None:
    if _phase_receipts.settings() and not _phase_receipts.before_delete(dps_name, _find_dps_by_name(dps_name)):
        return
    with _phase_runtime.owned_write(dps_name, "DELETE"):
        result = cli.invoke(f"iot dps delete --name {dps_name} --resource-group {ENTITY_RG}", capture_stderr=True)
    if not result.success():
        raise CLIInternalError(f"Failed to delete DPS '{dps_name}' in resource group '{ENTITY_RG}'.")
    _phase_receipts.after_delete(dps_name)


def _cleanup_created_resource(name, run_uid, kind, find_fn, delete_fn):
    resource = find_fn(name)
    if resource is None:
        return
    tags = resource.get("tags") or {}
    if resource.get("name") != name or any(
        tags.get(key) != value for key, value in {"intTest": "true", "runUid": run_uid, "kind": kind}.items()
    ):
        logger.error("Not deleting '%s': resource ownership does not match this test run.", name)
        return
    delete_fn(name)


def _hub_link_host_name(iot_hub: Dict) -> str:
    """Match linked-hub's auto hostname selection without retrieving Hub SAS keys."""
    properties = iot_hub["hub"]["properties"]
    return properties.get("deviceHostName") or properties["hostName"]


def _enable_dps_hub_identity(dps_name: str, iot_hub: Dict) -> None:
    dps = cli.invoke(
        f"iot dps identity assign --name {dps_name} -g {ENTITY_RG} --system-assigned",
        capture_stderr=True,
    ).as_json()
    principal_id = (dps.get("identity") or {}).get("principalId")
    if not principal_id:
        raise CLIInternalError(
            "DPS linked-Hub tests require a system-assigned identity principalId before Hub role assignment."
        )
    _assign_fixture_role(
        role=HUB_USER_ROLE,
        scope=iot_hub["hub"]["id"],
        assignee=principal_id,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES,
    )
    # The DPS managed identity has a separate Hub data-role grant and must
    # settle before device provisioning. Caller-role propagation is handled
    # by _assign_current_user_role; device attestation is still key/X.509.
    sleep(60)


def _link_hub(dps_name: str, iot_hub: Dict) -> str:
    _enable_dps_hub_identity(dps_name, iot_hub)
    linked_hubs = cli.invoke(
        "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
    ).as_json()
    hub_host_name = _hub_link_host_name(iot_hub)
    linked_hub = next((hub for hub in linked_hubs if hub["name"] == hub_host_name), None)
    if not linked_hub:
        cli.invoke(
            f"iot dps linked-hub create --dps-name {dps_name} -g {ENTITY_RG} "
            f"--hub-name {iot_hub['name']} --hub-resource-group {iot_hub['rg']} "
            "--authentication-type SystemAssigned",
            capture_stderr=True,
        )
    elif linked_hub.get("authenticationType") != "SystemAssigned":
        cli.invoke(
            f"iot dps linked-hub update --dps-name {dps_name} -g {ENTITY_RG} "
            f"--linked-hub {hub_host_name} --authentication-type SystemAssigned",
            capture_stderr=True,
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
    tags = f"intTest=true runUid={run_uid} kind={kind} createdEpoch={int(time())} authPhase={_phase.get_phase()}"
    if iot_hub:
        tags += f" hubname={iot_hub['name']}"
    with ExitStack() as cleanup:
        if _phase_receipts.settings() and _find_dps_by_name(name) is not None:
            raise CLIInternalError("Isolated DPS name already exists; refusing to overwrite it.")
        _phase_receipts.before_create(name, ENTITY_RG, run_uid, kind)
        cleanup.callback(_cleanup_created_resource, name, run_uid, kind, _find_dps_by_name, _delete_dps)
        with _phase_runtime.owned_write(name, "PUT"):
            target_dps = cli.invoke(
                f"iot dps create --name {name} --resource-group {ENTITY_RG} "
                f"--location {ENTITY_LOCATION} --disable-local-auth {str(_phase.local_auth_disabled()).lower()} --tags {tags}",
                capture_stderr=True,
            ).as_json()
        _phase_receipts.after_create(name, target_dps)
        _assert_local_auth_policy(target_dps)
        if _phase.local_auth_disabled():
            assign_iot_dps_dataplane_rbac_role(target_dps)
        if iot_hub:
            _link_hub(name, iot_hub)
        else:
            _unlink_all_hubs(name)
        cleanup.pop_all()
        return name, target_dps


def _iot_dps_provisioner(request, iot_hub: Optional[Dict] = None) -> dict:
    """Create or reuse a device provisioning service for testing purposes."""
    use_managed = not settings.env.azext_iot_testdps
    kind = "h" if iot_hub else "nh"
    run_uid = _get_run_uid(request)

    with ExitStack() as cleanup:
        if use_managed:
            if _phase.local_auth_disabled() and not _phase_receipts.settings():
                _gc_stale_resources_once(run_uid)
            target_dps = _shared_acquire(
                run_uid,
                kind,
                create_fn=lambda ru, k: _create_managed_dps(ru, k, iot_hub),
                find_fn=_find_dps_by_name,
            )
            cleanup.callback(
                _shared_release, run_uid, kind,
                lambda name: _cleanup_created_resource(name, run_uid, kind, _find_dps_by_name, _delete_dps),
            )
            dps_name = target_dps["name"]
            hub_host_name = _hub_link_host_name(iot_hub) if iot_hub else None
        else:
            dps_name = settings.env.azext_iot_testdps
            target_dps = _find_dps_by_name(dps_name)
            if not target_dps:
                raise CLIInternalError(
                    f"Supplied DPS '{dps_name}' was not found in '{ENTITY_RG}'; fixtures will not create a supplied resource."
                )
            _assert_local_auth_policy(target_dps)
            if _phase.local_auth_disabled():
                assign_iot_dps_dataplane_rbac_role(target_dps)
            hub_host_name = _link_hub(dps_name, iot_hub) if iot_hub else None
            if not iot_hub:
                _unlink_all_hubs(dps_name)

        _assert_local_auth_policy(target_dps)
        result = {
            "name": dps_name,
            "resourceGroup": ENTITY_RG,
            "dps": target_dps,
            # Default Entra/device-attestation fixtures do not retrieve service-policy keys.
            "connectionString": _dps_service_connection_string(target_dps) if not _phase.local_auth_disabled() else None,
            "hubHostName": hub_host_name,
            "iotHub": iot_hub,
            "certificates": [],
            "_runUid": run_uid if use_managed else None,
            "_kind": kind if use_managed else None,
        }
        cleanup.pop_all()
        return result


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


@pytest.fixture(scope="session")
def dps_linked_hub_identity(request, provisioned_iot_dps_no_hub_module, provisioned_only_iot_hubs_session):
    """Enable MI without linking, so linked-hub lifecycle tests own their entries."""
    with _no_hub_usage_lock(request):
        _enable_dps_hub_identity(
            provisioned_iot_dps_no_hub_module["name"], provisioned_only_iot_hubs_session
        )


def _list_hubs() -> list:
    return cli.invoke('iot hub list -g "{}"'.format(ENTITY_RG), capture_stderr=True).as_json() or []


def _find_hub_by_name(name: str) -> Optional[dict]:
    # `iot hub show` can translate name availability into an untyped CLIError.
    # A scoped ARM GET preserves the distinction between absence and failures.
    receipt_config = _phase_receipts.settings()
    client = iot_hub_service_factory(cli.az_cli, subscription_id=receipt_config[2]) if receipt_config else (
        iot_hub_service_factory(cli.az_cli)
    )
    try:
        return client.iot_hub_resource.get(resource_group_name=ENTITY_RG, resource_name=name)
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise


def _create_managed_hub(run_uid: str, kind: str) -> tuple:
    name = f"{INT_TEST_HUB_PREFIX}-{_timestamp()}-{run_uid[:8]}"
    with ExitStack() as cleanup:
        if _phase_receipts.settings() and _find_hub_by_name(name) is not None:
            raise CLIInternalError("Isolated Hub name already exists; refusing to overwrite it.")
        _phase_receipts.before_create(name, ENTITY_RG, run_uid, kind)
        cleanup.callback(_cleanup_created_resource, name, run_uid, kind, _find_hub_by_name, _delete_hub)
        with _phase_runtime.owned_write(name, "PUT"):
            target_hub = cli.invoke(
                f"iot hub create -n {name} -g {ENTITY_RG} --sku S1 "
                f"--location {HUB_TEST_LOCATION} --disable-local-auth {str(_phase.local_auth_disabled()).lower()} "
                f"--tags intTest=true runUid={run_uid} kind=hub createdEpoch={int(time())} authPhase={_phase.get_phase()}",
                capture_stderr=True,
            ).as_json()
        _phase_receipts.after_create(name, target_hub)
        cleanup.pop_all()
        return name, target_hub


def _delete_hub(name: str) -> None:
    if _phase_receipts.settings() and not _phase_receipts.before_delete(name, _find_hub_by_name(name)):
        return
    with _phase_runtime.owned_write(name, "DELETE"):
        if not cli.invoke(f"iot hub delete -n {name} -g {ENTITY_RG}", capture_stderr=True).success():
            raise CLIInternalError(f"Failed to delete iot hub resource '{name}' in resource group '{ENTITY_RG}'.")
    _phase_receipts.after_delete(name)


def _iot_hubs_provisioner(request):
    """Provision (or reuse) a single IoT Hub shared by all workers of the run for DPS tests."""
    if settings.env.azext_iot_testdps_hub:
        name = settings.env.azext_iot_testdps_hub
        target_hub = _find_hub_by_name(name)
        if not target_hub:
            raise CLIInternalError(
                f"Supplied Hub '{name}' was not found in '{ENTITY_RG}'; fixtures will not create a supplied resource."
            )
        run_uid = None
    else:
        run_uid = _get_run_uid(request)
        target_hub = _shared_acquire(
            run_uid, "hub", create_fn=_create_managed_hub, find_fn=_find_hub_by_name
        )
        name = target_hub["name"]

    with ExitStack() as cleanup:
        if run_uid:
            cleanup.callback(
                _shared_release, run_uid, "hub",
                lambda target: _cleanup_created_resource(target, run_uid, "hub", _find_hub_by_name, _delete_hub),
            )
        _assert_local_auth_policy(target_hub)
        assert target_hub["location"].replace(" ", "").casefold() == HUB_TEST_LOCATION.replace(" ", "").casefold(), (
            f"DPS integration Hubs must be in {HUB_TEST_LOCATION}; use a compliant azext_iot_testdps_hub."
        )
        _assign_current_user_role(HUB_USER_ROLE, target_hub["id"])
        result = {
            "hub": target_hub,
            "name": name,
            "rg": ENTITY_RG,
            "_runUid": run_uid,
        }
        cleanup.pop_all()
        return result


def _iot_hubs_removal(hub_result):
    # Release this run's shared hub; the last worker out deletes it. An env-pinned hub
    # (azext_iot_testdps_hub) carries no run id and is intentionally left in place.
    run_uid = hub_result.get("_runUid")
    if run_uid:
        _shared_release(run_uid, "hub", delete_fn=_delete_hub)
