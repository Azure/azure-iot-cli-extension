# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry command assertions on the existing registration fixture's owned devices."""

from shlex import join, quote

from azext_iot.tests.adr._helpers import wait_for_condition
from azext_iot.tests.dps._csr_issuance import invoke

PREFIX = "iot adr ns device"
METADATA_TIMEOUT = 600


def _wait(fetch, condition, description):
    return wait_for_condition(
        fetch, condition, description=description, timeout=METADATA_TIMEOUT, interval=5,
        is_retryable_error=lambda _error: False,
    )


def assert_registry_registration(resource, ownership, *, certificate):
    device = ownership.read_device()
    namespace = ownership.namespace
    properties = device["properties"]
    scope = join(["--ns", namespace["name"], "-g", namespace["resource_group"],
                  "--subscription", namespace["subscription"]])
    args = f"{scope} -n {quote(device['name'])}"
    invoke(f"{PREFIX} wait {args} --exists --timeout 600 --interval 5")
    for selector in (f"-n {quote(device['name'])}", f"--external-device-id {quote(properties['externalDeviceId'])}"):
        shown = invoke(f"{PREFIX} show {scope} {selector}").as_json()
        assert shown["id"].casefold() == device["id"].casefold()
        assert shown["properties"]["externalDeviceId"] == properties["externalDeviceId"]
        assert shown["properties"]["uuid"] == properties["uuid"]
    listed = invoke(f"{PREFIX} list {scope}").as_json()
    assert sum(item["id"].casefold() == device["id"].casefold() for item in listed) == 1

    hub = resource["hub"]
    identity = _wait(
        lambda: invoke(
            f"iot hub device-identity show -n {quote(hub['name'])} -g {quote(hub['rg'])} "
            f"-d {quote(ownership.intent['device_id'])} --auth-type login --subscription {namespace['subscription']} "
            "--query '{deviceId:deviceId,uuid:adrDeviceProperties.uuid,authType:authentication.type}'"
        ).as_json(),
        lambda value: bool(value["uuid"]), "owned Hub RegistryDevice metadata",
    )
    assert identity["deviceId"] == ownership.intent["device_id"]
    assert isinstance(properties["uuid"], str) and properties["uuid"]
    assert identity["uuid"].casefold() == properties["uuid"].casefold()
    if not certificate:
        assert identity["authType"] == "sas"
    ownership.read_device()
