# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

from knack.util import CLIError
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.common.utility import trim_from_start
from azext_iot._factory import iot_hub_service_factory


def _parse_connection_string(cs, validate=None, cstring_type='entity'):
    decomposed = validate_key_value_pairs(cs)
    if validate:
        for k in validate:
            if not decomposed.get(k):
                raise ValueError('{} connection string has missing property: {}'.format(cstring_type, k))
    return decomposed


def parse_iot_hub_connection_string(cs):
    validate = ['HostName', 'SharedAccessKeyName', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'IoT Hub')


def parse_iot_device_connection_string(cs):
    validate = ['HostName', 'DeviceId', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'Device')


CONN_STR_TEMPLATE = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


# pylint: disable=broad-except
def get_iot_hub_connection_string(
        cmd,
        hub_name,
        resource_group_name,
        policy_name='iothubowner',
        key_type='primary',
        include_events=False,
        login=None):
    """
    Function used to build up dictionary of IoT Hub connection string parts

    Args:
        cmd (object): Knack cmd
        hub_name (str): IoT Hub name
        resource_group_name (str): name of Resource Group contianing IoT Hub
        policy_name (str): Security policy name for shared key; e.g. 'iothubowner'(default)
        key_type (str): Shared key; either 'primary'(default) or 'secondary'
        include_events (bool): Include key event hub properties

    Returns:
        (dict): of connection string elements.

    Raises:
        CLIError: on input validation failure.

    """

    result = {}
    target_hub = None
    policy = None

    if login:
        try:
            decomposed = parse_iot_hub_connection_string(login)
        except ValueError as e:
            raise CLIError(e)

        result = {}
        result['cs'] = login
        result['policy'] = decomposed['SharedAccessKeyName']
        result['primarykey'] = decomposed['SharedAccessKey']
        result['entity'] = decomposed['HostName']
        return result

    client = None
    if getattr(cmd, 'cli_ctx', None):
        client = iot_hub_service_factory(cmd.cli_ctx)
    else:
        client = cmd

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
        addprops = getattr(target_hub, 'additional_properties', None)
        resource_group_name = addprops.get('resourcegroup') if addprops else getattr(
            target_hub, 'resourcegroup', None)

        policy = client.get_keys_for_key_name(resource_group_name, target_hub.name, policy_name)
    except Exception:
        pass

    if policy is None:
        raise CLIError(
            'No keys found for policy {} of IoT Hub {}.'.format(policy_name, hub_name)
        )

    result['cs'] = CONN_STR_TEMPLATE.format(
        target_hub.properties.host_name,
        policy.key_name,
        policy.primary_key if key_type == 'primary' else policy.secondary_key)
    result['entity'] = target_hub.properties.host_name
    result['policy'] = policy_name
    result['primarykey'] = policy.primary_key
    result['secondarykey'] = policy.secondary_key
    result['subscription'] = client.config.subscription_id
    result['resourcegroup'] = resource_group_name

    if include_events:
        events = {}
        events['endpoint'] = trim_from_start(target_hub.properties.event_hub_endpoints['events'].endpoint, 'sb://').strip('/')
        events['partition_count'] = target_hub.properties.event_hub_endpoints['events'].partition_count
        events['path'] = target_hub.properties.event_hub_endpoints['events'].path
        events['partition_ids'] = target_hub.properties.event_hub_endpoints['events'].partition_ids
        result['events'] = events

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
