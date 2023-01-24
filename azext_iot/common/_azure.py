# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import AzureResponseError, CLIInternalError
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.common.auth import get_aad_token


IOT_SERVICE_CS_TEMPLATE = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"


def _parse_connection_string(cs, validate=None, cstring_type="entity"):
    decomposed = validate_key_value_pairs(cs)
    decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())
    if validate:
        for k in validate:
            if not any([decomposed.get(k), decomposed_lower.get(k.lower())]):
                raise ValueError(
                    "{} connection string has missing property: {}".format(
                        cstring_type, k
                    )
                )
    return decomposed


def parse_iot_hub_connection_string(cs):
    validate = ["HostName", "SharedAccessKeyName", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "IoT Hub")


def parse_iot_dps_connection_string(cs):
    validate = ["HostName", "SharedAccessKeyName", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "IoT DPS")


def parse_iot_device_connection_string(cs):
    validate = ["HostName", "DeviceId", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "Device")


def parse_iot_device_module_connection_string(cs):
    validate = ["HostName", "DeviceId", "ModuleId", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "Module")


def parse_iot_hub_message_endpoint_connection_string(cs):
    validate = ["Endpoint", "SharedAccessKeyName", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "Endpoint")


def parse_storage_container_connection_string(cs):
    validate = ["AccountName", "AccountKey"]
    return _parse_connection_string(cs, validate, "Storage Container")


def parse_cosmos_db_connection_string(cs):
    validate = ["AccountEndpoint", "AccountKey"]
    return _parse_connection_string(cs, validate, "Cosmos DB Collection")


def parse_event_hub_connection_string(cs):
    # note that this is for an event hub instance, not namespace
    validate = ["Endpoint", "SharedAccessKeyName", "SharedAccessKey", "EntityPath"]
    return _parse_connection_string(cs, validate, "Event Hub")


def get_iot_central_tokens(cmd, app_id, token, central_dns_suffix):
    import requests

    if not token:
        aad_token = get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
            "accessToken"
        ]
        token = "Bearer {}".format(aad_token)

    url = "https://{}.{}/system/iothubs/generateEventSasTokens".format(
        app_id, central_dns_suffix
    )

    response = requests.post(url, headers={"Authorization": token})
    tokens = response.json()

    additional_help = (
        "Please ensure that the user is logged through the `az login` command, "
        "has the correct tenant set (the users home tenant) and "
        "has access to the application through http://apps.azureiotcentral.com"
    )

    if tokens.get("error"):
        error_message = tokens["error"]["message"]
        if tokens["error"]["code"].startswith("403.043.004."):
            error_message = "{} {}".format(error_message, additional_help)

        raise AzureResponseError(
            "Error {} getting tokens. {}".format(tokens["error"]["code"], error_message)
        )

    if tokens.get("message"):
        error_message = "{} {}".format(tokens["message"], additional_help)
        raise CLIInternalError(error_message)

    return tokens
