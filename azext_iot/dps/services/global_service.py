# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is for calls that route to the global DPS
# Useful for when you don't know what the dps name is ahead of time
# E.g. most IoT Central scenarios

import requests

from azext_iot import constants
from azext_iot.dps.services import auth


def get_registration_state(id_scope: str, key: str, device_id: str):
    """
    Gets device registration state from global dps endpoint
    Usefule for when dps name is unknown

    https://docs.microsoft.com/en-us/rest/api/iot-dps/getdeviceregistrationstate/getdeviceregistrationstate

    Params:
        id_scope: dps id_scope
        key: either primary or secondary symmetric key
        device_id: device id that uniquely identifies the device

    Returns:
        DeviceRegistrationState: dict
        ProvisioningServiceErrorDetails: dict
    """
    authToken = auth.get_dps_sas_auth_header(id_scope, device_id, key)

    url = "https://global.azure-devices-provisioning.net/{}/registrations/{}?api-version=2019-03-31".format(
        id_scope, device_id
    )
    header_parameters = {
        "Content-Type": "application/json",
        "User-Agent": constants.USER_AGENT,
        "Authorization": authToken,
    }
    body = {"registrationId": "{}".format(device_id)}
    response = requests.post(url, headers=header_parameters, json=body)

    try:
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e), "device_id": device_id}
