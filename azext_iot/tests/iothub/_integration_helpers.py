# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
from contextlib import contextmanager
from math import isfinite
from queue import Queue
from time import monotonic, sleep
from urllib.parse import parse_qs, urlparse

import pytest
from azure.cli.core.azclierror import CLIInternalError
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from msrestazure.azure_exceptions import CloudError

from azext_iot.tests.helpers import assign_role_assignment, get_role_assignments
from azext_iot.tests.helpers import invoke_checked  # noqa: F401 - compatibility re-export
from azext_iot.tests.settings import HUB_TEST_LOCATION


LOCAL_AUTH_MONITOR_REASON = (
    "IoT Hub integration policy requires disableLocalAuth=true. monitor-events uses "
    "Hub-policy SAS for the built-in Event Hubs endpoint and has no Entra authentication path."
)
LOCAL_AUTH_DEVICE_HTTP_REASON = (
    "IoT Hub integration policy requires disableLocalAuth=true. This CLI device HTTP "
    "operation uses a Hub shared-access policy, not a device key, and has no Entra/device-key option."
)
_CANARY_HUB_LIST_API_VERSIONS = frozenset({"2026-05-01-preview", "2026-10-01-preview"})
# Documented query tolerance, not a maximum-latency guarantee:
# https://learn.microsoft.com/azure/iot-hub/iot-hub-devguide-query-language#twin-query-limitations
QUERY_VISIBILITY_TIMEOUT = 30 * 60
logger = get_logger(__name__)


def wait_for_query_ids(read, expected_ids, id_key=None, attempts=None, wait=10, timeout=QUERY_VISIBILITY_TIMEOUT):
    """Wait for exact query IDs, charging reads and sleeps to one elapsed-time budget.

    An optional attempt limit can shorten the budget. In-flight reads retain their
    own transport timeouts; late results do not extend this visibility deadline.
    Command/service errors propagate without retry.
    """
    if attempts is not None and (isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1):
        raise ValueError("Query wait requires at least one attempt when an attempt limit is supplied.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
           for value in (wait, timeout)) or wait < 0 or timeout <= 0 or (attempts is None and wait == 0):
        raise ValueError("Query wait requires a finite positive timeout and polling interval (zero only with attempts).")
    expected = set(expected_ids)
    start = monotonic()
    elapsed = 0
    attempt = 0
    ids = []
    while elapsed < timeout:
        attempt += 1
        rows = read()
        ids = [row[id_key] for row in rows] if id_key else list(rows)
        observed = set(ids)
        elapsed = monotonic() - start
        if observed == expected and len(ids) == len(expected) and elapsed <= timeout:
            return rows
        logger.warning(
            "Query visibility after %s reads, %.1fs/%.1fs: expected IDs %s, observed IDs %s (%s rows)",
            attempt, elapsed, timeout, sorted(expected), sorted(observed), len(ids),
        )
        if elapsed >= timeout or (attempts is not None and attempt >= attempts):
            break
        sleep(min(wait, timeout - elapsed))
        elapsed = monotonic() - start
    raise AssertionError(
        f"Query visibility deadline/attempt limit exhausted after {attempt} reads, {elapsed:.1f}s "
        f"(budget {timeout:.1f}s): expected IDs {sorted(expected)}, "
        f"observed IDs {sorted(ids)}"
    )


def delete_known_devices(devices, device_ids):
    """Delete only test-owned IDs, without relying on the query index to enumerate them."""
    for device_id in dict.fromkeys(device_ids):
        try:
            devices.delete_identity(id=device_id, if_match="*")
        except (CloudError, HttpResponseError) as error:
            if getattr(error.response, "status_code", None) != 404:
                raise


def assign_role_with_propagation(*, role, scope, assignee, max_tries, wait):
    """Wait after a new data-role grant, not before it or before every test.

    Reuse the shared bounded assignment loop, but do not treat its None return
    value (including unsuccessful grants) as proof that a role was assigned.
    Service authorization failures are never caught/retried here.
    """
    if not assignee:
        raise CLIInternalError("A principal is required for the Hub data-role assignment.")

    def is_assigned():
        assignments = get_role_assignments(scope=scope, role=role, fill_role_definition_name=False)
        return any(
            assignment.get(key) == assignee
            for assignment in assignments
            for key in ("name", "principalId", "principalName")
        )

    if is_assigned():
        return

    assign_role_assignment(role=role, scope=scope, assignee=assignee, max_tries=max_tries)
    if not is_assigned():
        raise CLIInternalError(f"Required data role '{role}' was not assigned on '{scope}'.")
    sleep(wait)


def get_or_create_hub(client, name, resource_group, create):
    """Never enumerate Hubs to find a resource whose name and RG are already known."""
    try:
        return client.get(resource_group_name=resource_group, resource_name=name), False
    except HttpResponseError as error:
        # In particular, a canary 502 ProviderError is not evidence of absence.
        if error.status_code != 404:
            raise
    create()
    return client.get(resource_group_name=resource_group, resource_name=name), True


def assert_hub_policy(hub):
    """Fail rather than silently moving or weakening a caller-supplied Hub."""
    assert hub["location"].replace(" ", "").casefold() == HUB_TEST_LOCATION.replace(" ", "").casefold()
    assert hub["properties"].get("disableLocalAuth") is True, (
        "Hub integration tests require disableLocalAuth=true; use a policy-compliant test Hub."
    )


def scope_known_hub(command, resource_group, hub_names):
    """Keep known-Hub scenarios independent of subscription-list pagination.

    Commands intentionally enumerating Hubs (no name supplied) remain unchanged.
    """
    args = shlex.split(command)
    if args[:1] == ["az"]:
        args = args[1:]
    if args[:2] not in (["iot", "hub"], ["iot", "device"], ["iot", "edge"]):
        return command
    if any(arg in args for arg in ("-g", "--resource-group", "--resource-group-name")):
        return command
    names = {name for name in hub_names if name}
    if any(
        arg in ("-n", "--hub-name", "--name") and args[index + 1] in names
        for index, arg in enumerate(args[:-1])
    ):
        return f"{command} --resource-group {shlex.quote(resource_group)}"
    return command


@contextmanager
def device_receiver(connection_string):
    """Receive/ack as a device, not with the disabled Hub service shared-access policy."""
    from azure.iot.device import IoTHubDeviceClient

    messages = Queue()
    client = IoTHubDeviceClient.create_from_connection_string(connection_string)
    client.on_message_received = messages.put
    try:
        client.connect()
        yield messages
    finally:
        client.shutdown()


@contextmanager
def skip_hub_list_provider_error():
    """Scope the canary list defect to enumeration tests and the two branch APIs.

    Never return a partial list or treat any other service error as a pass/skip.
    """
    try:
        yield
    except HttpResponseError as error:
        request = getattr(getattr(error, "response", None), "request", None)
        url = urlparse(getattr(request, "url", ""))
        api_versions = parse_qs(url.query).get("api-version", [])
        is_canary_hub_list = (
            getattr(request, "method", "").upper() == "GET"
            and url.scheme == "https"
            and url.hostname == "centraluseuap.management.azure.com"
            and url.path.rstrip("/").casefold().endswith("/providers/microsoft.devices/iothubs")
            and len(api_versions) == 1
            and api_versions[0] in _CANARY_HUB_LIST_API_VERSIONS
        )
        if (
            error.status_code == 502
            and getattr(error.error, "code", None) == "ProviderError"
            and is_canary_hub_list
        ):
            pytest.skip(
                f"Canary Hub list ({api_versions[0]}) returned HTTP 502 ProviderError (known pagination defect)."
            )
        raise
