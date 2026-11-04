# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.dps.models.dps_target import DPSTarget


def test_from_connection_string_and_as_dict():
    cstring = (
        "HostName=mydps.azure-devices-provisioning.net;"
        "SharedAccessKeyName=provisioningserviceowner;SharedAccessKey=fakekey=="
    )
    target = DPSTarget.from_connection_string(cstring)
    result = target.as_dict()
    assert result["entity"] == "mydps.azure-devices-provisioning.net"
    assert result["policy"] == "provisioningserviceowner"
    assert result["primarykey"] == "fakekey=="
    assert result["cs"] == cstring
