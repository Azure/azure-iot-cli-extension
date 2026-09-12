# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import base64
from time import sleep
from typing import Dict


def compare_registrations(device_side: Dict[str, str], service_side: Dict[str, str]):
    """Compare the registration information from the device and the service clients."""
    assert device_side["assignedHub"] == service_side["assignedHub"]
    assert device_side["createdDateTimeUtc"].rstrip("+00:00") in service_side["createdDateTimeUtc"]
    assert device_side["deviceId"] == service_side["deviceId"]
    assert device_side["etag"] == service_side["etag"]
    assert device_side["lastUpdatedDateTimeUtc"].rstrip("+00:00") in service_side["lastUpdatedDateTimeUtc"]
    assert device_side["registrationId"] == service_side["registrationId"]
    # The device sdk always returns a substatus of initialAssignment, when that should not be the case if a
    # device is reregistered. The service side has the correct substatus.
    # assert device_side["substatus"] == service_side["substatus"]


def check_hub_device(
    cli,
    device: str,
    auth_type: str,
    hub: Dict,
    key: str = None,
    thumbprint: str = None
):
    """Read the Hub registry with Entra; auth_type describes the DEVICE, not the service caller."""

    last_error = None
    for attempt in range(3):
        try:
            result = cli.invoke(
                f"iot hub device-identity show -n {hub['name']} -g {hub['rg']} "
                f"-d {device} --auth-type login"
            )
            if not result.success():
                raise RuntimeError(f"Command failed with exit code {result.error_code}: {result.output}")
            device_auth = result.as_json()["authentication"]
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                sleep(30)
    else:
        raise last_error

    assert auth_type == device_auth["type"]
    if key:
        assert key == device_auth["symmetricKey"]["primaryKey"]
    if thumbprint:
        assert thumbprint == device_auth["x509Thumbprint"]["primaryThumbprint"]


def register_fresh_generated_credential(
    cli, resource, kind, key_name, request, endpoint=None, auth_type="login", connection_string=None,
):
    """Authenticate once with service-generated keys on an independent identity/group."""
    from azext_iot.constants import IOTDPS_PROVISIONING_HOST
    from azext_iot.tests.generators import generate_names
    from azext_iot.tests.helpers import invoke_checked, set_cmd_auth_type

    enrollment_id, device_id = generate_names(count=2)
    group = kind == "group"
    if not group:
        device_id = enrollment_id
    command_group = "enrollment-group" if group else "enrollment"
    context = f"--dps-name {resource['name']} -g {resource['resourceGroup']}"

    def invoke(command):
        return invoke_checked(
            cli,
            set_cmd_auth_type(command, auth_type=auth_type, cstring=connection_string),
            description="DPS credential integration command",
        )

    create = f"iot dps {command_group} create {context} --enrollment-id {enrollment_id}"
    create += " --show-keys" if group else " --attestation-type symmetricKey"
    response = invoke(create)
    request.addfinalizer(lambda: invoke(f"iot dps {command_group} delete {context} --enrollment-id {enrollment_id}"))
    enrollment = response.as_json()
    keys = enrollment["attestation"]["symmetricKey"]
    complete = all(isinstance(keys.get(name), str) and keys[name] for name in ("primaryKey", "secondaryKey"))
    assert complete, "DPS did not return both service-generated keys."
    distinct = keys["primaryKey"] != keys["secondaryKey"]
    assert distinct, "DPS returned identical primary and secondary keys."
    try:
        valid = all(bool(base64.b64decode(keys[name], validate=True)) for name in ("primaryKey", "secondaryKey"))
    except ValueError:
        valid = False
    assert valid, "DPS returned an invalid base64 credential."
    target = context
    if endpoint is not None:
        properties = resource["dps"]["properties"]
        host = properties["deviceProvisioningHostName"] if endpoint == "configured" else IOTDPS_PROVISIONING_HOST
        assert host
        target = f"--id-scope {properties['idScope']} --host {host}"
    registration = invoke(
        f"iot device registration create {target} --registration-id {device_id} --key {keys[key_name]}"
        + (" --compute-key" if group else "")
    ).as_json()
    assert registration["operationId"]
    assert registration["status"] == "assigned"
    state = registration["registrationState"]
    assert state["registrationId"] == device_id
    assert state["deviceId"] == device_id
    assert state["assignedHub"] == resource["hubHostName"]
    assert state["substatus"] == "initialAssignment"
    check_hub_device(cli, device_id, "sas", resource["iotHub"])
    identifier = "--registration-id" if group else "--enrollment-id"
    service_state = invoke(
        f"iot dps {command_group} registration show {context} {identifier} {device_id}"
    ).as_json()
    compare_registrations(state, service_state)
    return registration
