# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums); hub and dps connection string functions.

"""

from enum import Enum
from knack.util import CLIError


# pylint: disable=too-few-public-methods
class SdkType(Enum):
    """
    Target SDK for interop.
    """
    device_query_sdk = 0
    modules_sdk = 1
    device_twin_sdk = 2
    device_msg_sdk = 3
    custom_sdk = 4
    dps_sdk = 5


# pylint: disable=too-few-public-methods
class EntityStatusType(Enum):
    """
    Resource status.
    """
    disabled = 'disabled'
    enabled = 'enabled'


# pylint: disable=too-few-public-methods
class SettleType(Enum):
    """
    Settlement state of C2D message.
    """
    complete = 'complete'
    abandon = 'abandon'
    reject = 'reject'


# pylint: disable=too-few-public-methods
class DeviceAuthType(Enum):
    """
    Device Authorization type.
    """
    shared_private_key = 'shared_private_key'
    x509_thumbprint = 'x509_thumbprint'
    x509_ca = 'x509_ca'


# pylint: disable=too-few-public-methods
class KeyType(Enum):
    """
    Shared private key.
    """
    primary = 'primary'
    secondary = 'secondary'


# pylint: disable=too-few-public-methods
class AttestationType(Enum):
    """
    Type of atestation (TMP or certificate based).
    """
    tpm = 'tpm'
    x509 = 'x509'

CONN_STR_TEMPLATE = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


# pylint: disable=broad-except
def get_iot_hub_connection_string(
        client,
        hub_name,
        resource_group_name,
        policy_name='iothubowner',
        key_type='primary'):
    """
    Function used to build up dictionary of IoT Hub connection string parts

    Args:
        client ():
        hub_name (str): IoT Hub name
        resource_group_name (str): name of Resource Group contianing IoT Hub
        policy_name (str): Security policy name for shared key; e.g. 'iothubowner'(default)
        key_type (str): Shared key; either 'primary'(default) or 'secondary'

    Returns:
        (dict): of connection string elements.

    Raises:
        CLIError: on input validation failure.

    """

    target_hub = None
    policy = None

    def _find_iot_hub_from_list(hubs, hub_name):
        if hubs:
            return next((hub for hub in hubs if hub_name.lower() == hub.name.lower()), None)
        return None

    if resource_group_name is None:
        hubs = client.list_by_subscription()
        if not hubs:
            raise CLIError('No IoT Hub found in current subscription.')
        target_hub = _find_iot_hub_from_list(hubs, hub_name)
    else:
        try:
            target_hub = client.get(resource_group_name, hub_name)
        except Exception:
            pass

    if target_hub is None:
        raise CLIError(
            'No IoT Hub found with name {} in current subscription.'.format(hub_name))

    try:
        policy = client.get_keys_for_key_name(
            target_hub.resourcegroup, target_hub.name, policy_name)
    except Exception:
        pass

    if policy is None:
        raise CLIError(
            'No keys found for policy {} of IoT Hub {}.'.format(policy_name, hub_name)
        )

    result = {}
    result['cs'] = CONN_STR_TEMPLATE.format(
        target_hub.properties.host_name,
        policy.key_name,
        policy.primary_key if key_type == 'primary' else policy.secondary_key)
    result['entity'] = target_hub.properties.host_name
    result['policy'] = policy_name
    result['primarykey'] = policy.primary_key
    result['secondarykey'] = policy.secondary_key
    result['subscription'] = client.config.subscription_id
    result['resourcegroup'] = target_hub.resourcegroup

    return result


# pylint: disable=broad-except
def get_iot_dps_connection_string(
        client,
        dps_name,
        resource_group_name,
        policy_name='provisioningserviceowner',
        key_type='primary'):
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
            return next((dps for dps in all_dps if dps_name.lower() == dps.name.lower()), None)
        return None

    try:
        target_dps = client.iot_dps_resource.get(dps_name, resource_group_name)
    except Exception:
        pass

    if target_dps is None:
        raise CLIError(
            'No IoT Provisioning Service found '
            'with name {} in current subscription.'.format(dps_name))

    try:
        policy = client.iot_dps_resource.list_keys_for_key_name(
            dps_name,
            policy_name,
            resource_group_name)
    except Exception:
        pass

    if policy is None:
        raise CLIError(
            'No keys found for policy {} of '
            'IoT Provisioning Service {}.'.format(policy_name, dps_name)
        )

    result = {}
    result['cs'] = CONN_STR_TEMPLATE.format(
        target_dps.properties.service_operations_host_name,
        policy.key_name,
        policy.primary_key if key_type == 'primary' else policy.secondary_key)
    result['entity'] = target_dps.properties.service_operations_host_name
    result['policy'] = policy_name
    result['primarykey'] = policy.primary_key
    result['secondarykey'] = policy.secondary_key
    result['subscription'] = client.config.subscription_id

    return result
