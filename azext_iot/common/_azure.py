# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.common.utility import trim_from_start
from azext_iot._factory import iot_hub_service_factory
from azure.cli.core._profile import Profile


def _get_aad_token(cmd, resource=None):
    '''
    get AAD token to access to a specified resource
    :param resource: Azure resource endpoints. Default to Azure Resource Manager
    Use 'az cloud show' command for other Azure resources
    '''
    resource = (resource or cmd.cli_ctx.cloud.endpoints.active_directory_resource_id)
    profile = Profile(cli_ctx=cmd.cli_ctx)
    creds, subscription, tenant = profile.get_raw_token(subscription=None, resource=resource)
    return {
        'tokenType': creds[0],
        'accessToken': creds[1],
        'expiresOn': creds[2].get('expiresOn', 'N/A'),
        'subscription': subscription,
        'tenant': tenant
    }


def _parse_connection_string(cs, validate=None, cstring_type='entity'):
    decomposed = validate_key_value_pairs(cs)
    decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())
    if validate:
        for k in validate:
            if not any([decomposed.get(k), decomposed_lower.get(k.lower())]):
                raise ValueError('{} connection string has missing property: {}'.format(cstring_type, k))
    return decomposed


def parse_pnp_connection_string(cs):
    validate = ['HostName', 'RepositoryId', 'SharedAccessKeyName', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'PnP Model Repository')


def parse_iot_hub_connection_string(cs):
    validate = ['HostName', 'SharedAccessKeyName', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'IoT Hub')


def parse_iot_device_connection_string(cs):
    validate = ['HostName', 'DeviceId', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'Device')


def parse_iot_device_module_connection_string(cs):
    validate = ['HostName', 'DeviceId', 'ModuleId', 'SharedAccessKey']
    return _parse_connection_string(cs, validate, 'Module')


CONN_STR_TEMPLATE = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


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
            decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())
        except ValueError as e:
            raise CLIError(e)

        result = {}
        result['cs'] = login
        result['policy'] = decomposed_lower['sharedaccesskeyname']
        result['primarykey'] = decomposed_lower['sharedaccesskey']
        result['entity'] = decomposed_lower['hostname']
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
    result['location'] = target_hub.location
    result['sku_tier'] = target_hub.sku.tier.value

    if include_events:
        events = {}
        events['endpoint'] = trim_from_start(target_hub.properties.event_hub_endpoints['events'].endpoint, 'sb://').strip('/')
        events['partition_count'] = target_hub.properties.event_hub_endpoints['events'].partition_count
        events['path'] = target_hub.properties.event_hub_endpoints['events'].path
        events['partition_ids'] = target_hub.properties.event_hub_endpoints['events'].partition_ids
        result['events'] = events

    return result


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


def get_iot_central_tokens(cmd, app_id, central_api_uri):
    def get_event_hub_token(app_id, iotcAccessToken):
        import requests
        url = "https://{}/v1-beta/applications/{}/diagnostics/sasTokens".format(central_api_uri, app_id)
        response = requests.post(url, headers={'Authorization': 'Bearer {}'.format(iotcAccessToken)})
        return response.json()

    aad_token = _get_aad_token(cmd, resource="https://apps.azureiotcentral.com")['accessToken']

    tokens = get_event_hub_token(app_id, aad_token)

    if tokens.get('error'):
        raise CLIError(
            'Error {} getting tokens. {}'.format(tokens['error']['code'], tokens['error']['message'])
        )

    return tokens


def get_iot_hub_token_from_central_app_id(cmd, app_id, central_api_uri):
    return get_iot_central_tokens(cmd, app_id, central_api_uri)['iothubTenantSasToken']['sasToken']


def get_iot_pnp_connection_string(
        cmd,
        endpoint,
        repo_id,
        user_role='Admin',
        login=None):
    """
    Function used to build up dictionary of IoT PnP connection string parts

    Args:
        cmd (object): Knack cmd
        endpoint (str): PnP endpoint
        repository_id (str): PnP repository Id.
        user_role (str): User role of the access key for the given PnP repository.

    Returns:
        (dict): of connection string elements.

    Raises:
        CLIError: on input validation failure.

    """

    from azure.cli.command_modules.iot.digitaltwinrepositoryprovisioningservice import DigitalTwinRepositoryProvisioningService
    from azure.cli.command_modules.iot._utils import get_auth_header
    from azext_iot.constants import PNP_REPO_ENDPOINT

    result = {}
    client = None
    headers = None

    if login:

        try:
            decomposed = parse_pnp_connection_string(login)
        except ValueError as e:
            raise CLIError(e)

        result = {}
        result['cs'] = login
        result['policy'] = decomposed['SharedAccessKeyName']
        result['primarykey'] = decomposed['SharedAccessKey']
        result['repository_id'] = decomposed['RepositoryId']
        result['entity'] = decomposed['HostName']
        result['entity'] = result['entity'].replace('https://', '')
        result['entity'] = result['entity'].replace('http://', '')
        return result

    def _find_key_from_list(keys, user_role):
        if keys:
            return next((key for key in keys if key.user_role.lower() == user_role.lower()), None)
        return None

    if repo_id:
        client = DigitalTwinRepositoryProvisioningService(endpoint)
        headers = get_auth_header(cmd)
        keys = client.get_keys_async(repository_id=repo_id, api_version=client.api_version, custom_headers=headers)

        if keys is None:
            raise CLIError('Auth key required for repository "{}"'.format(repo_id))

        policy = _find_key_from_list(keys, user_role)

        if policy is None:
            raise CLIError(
                'No auth key found for repository "{}" with user_role "{}".'.format(repo_id, user_role)
            )

        result['cs'] = policy.connection_string
        result['entity'] = policy.service_endpoint
        result['policy'] = policy.id
        result['primarykey'] = policy.secret
        result['repository_id'] = policy.repository_id
    else:
        result['entity'] = PNP_REPO_ENDPOINT

    result['entity'] = result['entity'].replace('https://', '')
    result['entity'] = result['entity'].replace('http://', '')
    return result
