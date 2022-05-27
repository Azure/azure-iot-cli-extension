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
