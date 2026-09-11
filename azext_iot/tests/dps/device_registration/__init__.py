# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


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
    assert device_side["substatus"] == service_side["substatus"]


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
