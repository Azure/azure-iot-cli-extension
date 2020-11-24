# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.common.auth import get_aad_token


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


def parse_pnp_connection_string(cs):
    validate = ["HostName", "RepositoryId", "SharedAccessKeyName", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "PnP Model Repository")


def parse_iot_hub_connection_string(cs):
    validate = ["HostName", "SharedAccessKeyName", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "IoT Hub")


def parse_iot_device_connection_string(cs):
    validate = ["HostName", "DeviceId", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "Device")


def parse_iot_device_module_connection_string(cs):
    validate = ["HostName", "DeviceId", "ModuleId", "SharedAccessKey"]
    return _parse_connection_string(cs, validate, "Module")


CONN_STR_TEMPLATE = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"


def get_iot_dps_connection_string(
    client,
    dps_name,
    resource_group_name,
    policy_name="provisioningserviceowner",
    key_type="primary",
):
    """
    Function used to build up dictionary of IoT Hub Device
    Provisioning Service connection string parts

    Args:
        client ():
        dps_name (str): Device Provisioning Service name
        resource_group_name (str): name of Resource Group contianing IoT Hub
        policy_name (str): Security policy name for shared key; e.g. 'iothubowner'(default)
        key_type (str): Shared key; either 'primary'(default) or 'secondary'

    Returns:
        (dict): of connection string elements.

    Raises:
        CLIError: on input validation failure.
    """
    target_dps = None
    policy = None

    def _find_iot_dps_from_list(all_dps, dps_name):
        if all_dps:
            return next(
                (dps for dps in all_dps if dps_name.lower() == dps.name.lower()), None
            )
        return None

    try:
        target_dps = client.iot_dps_resource.get(dps_name, resource_group_name)
    except Exception:
        pass

    if target_dps is None:
        raise CLIError(
            "No IoT Provisioning Service found "
            "with name {} in current subscription.".format(dps_name)
        )

    try:
        policy = client.iot_dps_resource.list_keys_for_key_name(
            dps_name, policy_name, resource_group_name
        )
    except Exception:
        pass

    if policy is None:
        raise CLIError(
            "No keys found for policy {} of "
            "IoT Provisioning Service {}.".format(policy_name, dps_name)
        )

    result = {}
    result["cs"] = CONN_STR_TEMPLATE.format(
        target_dps.properties.service_operations_host_name,
        policy.key_name,
        policy.primary_key if key_type == "primary" else policy.secondary_key,
    )
    result["entity"] = target_dps.properties.service_operations_host_name
    result["policy"] = policy_name
    result["primarykey"] = policy.primary_key
    result["secondarykey"] = policy.secondary_key
    result["subscription"] = client.config.subscription_id

    return result


def get_iot_central_tokens(cmd, app_id, token, central_dns_suffix):
    from requests import post
    from azure.cli.core.util import should_disable_connection_verify


    if not token:
        aad_token = get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
            "accessToken"
        ]
        token = "Bearer {}".format(aad_token)

    url = "https://{}.{}/system/iothubs/generateSasTokens".format(
        app_id, central_dns_suffix
    )
    response = post(url, headers={"Authorization": token}, verify = not should_disable_connection_verify())
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

        raise CLIError(
            "Error {} getting tokens. {}".format(tokens["error"]["code"], error_message)
        )

    if tokens.get("message"):
        error_message = "{} {}".format(tokens["message"], additional_help)
        raise CLIError(error_message)

    return tokens
