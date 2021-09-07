# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/deviceGroups

from typing import List, Union
import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.preview import DeviceGroupPreview
from azext_iot.central.models.v2 import DeviceGroupV2
from azext_iot.central.models.enum import ApiVersion

logger = get_logger(__name__)

BASE_PATH = "api/deviceGroups"


def list_device_groups(
    cmd,
    app_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[DeviceGroupPreview, DeviceGroupV2]]:
    """
    Get a list of all device groups in IoTC app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of device groups
    """

    device_groups = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        device_groups.extend(
            [
                DeviceGroupPreview(device_group)
                if api_version == ApiVersion.preview.value
                else DeviceGroupV2(device_group)
                for device_group in result["value"]
            ]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return device_groups
