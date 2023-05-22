# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


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
    hub_cstring: str,
    key: str = None,
    thumbprint: str = None
):
    """Helper method to check whether a device exists in a hub."""

    device_auth = cli.invoke(
        "iot hub device-identity show -l {} -d {}".format(
            hub_cstring,
            device,
        ), capture_stderr=True
    ).as_json()["authentication"]
    assert auth_type == device_auth["type"]
    if key:
        assert key == device_auth["symmetricKey"]["primaryKey"]
    if thumbprint:
        assert thumbprint == device_auth["x509Thumbprint"]["primaryThumbprint"]
