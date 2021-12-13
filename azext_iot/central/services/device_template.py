# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates

from typing import Union
import requests
from typing import List

from knack.util import CLIError
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.preview import TemplatePreview
from azext_iot.central.models.v1 import TemplateV1
from azext_iot.central.models.v1_1_preview import TemplateV1_1_preview

logger = get_logger(__name__)

BASE_PATH = "api/deviceTemplates"
MODEL = "Template"


def get_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[TemplatePreview, TemplateV1, TemplateV1_1_preview]:
    """
    Get a specific device template from IoTC

    Args:
        cmd: command passed into az
        device_template_id: case sensitive device template id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """
    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(url, headers=headers, params=query_parameters)
    result = _utility.try_extract_result(response)
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def list_device_templates(
    cmd,
    app_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[TemplatePreview, TemplateV1, TemplateV1_1_preview]]:
    """
    Get a list of all device templates in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_templates: dict
    """

    device_templates = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    logger.warning(
        "This command may take a long time to complete if your app contains a lot of device templates"
    )

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(
            url,
            headers=headers,
            params=query_parameters if pages_processed == 0 else None,
        )
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        device_templates.extend(
            [
                _utility.get_object(template, MODEL, api_version)
                for template in result["value"]
            ]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return device_templates


def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    payload: dict,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[TemplatePreview, TemplateV1, TemplateV1_1_preview]:
    """
    Create a device template in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_template_id: case sensitive device template id,
        payload: see example payload available in
            <repo-root>/azext_iot/tests/central/json/device_template_int_test.json
            or check here for more information
            https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.put(url, headers=headers, json=payload, params=query_parameters)
    result = _utility.try_extract_result(response)
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def update_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    payload: dict,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[TemplatePreview, TemplateV1, TemplateV1_1_preview]:
    """
    Updates a device template in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_template_id: case sensitive device template id,
        payload: see example payload available in
            <repo-root>/azext_iot/tests/central/json/device_template_int_test.json
            or check here for more information
            https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.patch(
        url, headers=headers, json=payload, params=query_parameters
    )
    result = _utility.try_extract_result(response)
    return _utility.get_object(result, MODEL, api_version)


def delete_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete a device template from IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_template_id: case sensitive device template id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """
    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.delete(url, headers=headers, params=query_parameters)
    return _utility.try_extract_result(response)
