from enum import Enum
from azure.cli.core.util import CLIError


class SdkType(Enum):
    device_query_sdk = 0
    modules_sdk = 1
    device_twin_sdk = 2


class DeviceStatusType(Enum):
    disabled = "disabled"
    enabled = "enabled"


class ProtocolType(Enum):
    http = 'http'
    amqp = 'amqp'
    mqtt = 'mqtt'


class SettleType(Enum):
    complete = 'complete'
    abandon = 'abandon'
    reject = 'reject'


class DeviceAuthType(Enum):
    shared_private_key = 'shared_private_key'
    x509_thumbprint = 'x509_thumbprint'
    x509_ca = 'x509_ca'


CONN_STR_TEMPLATE = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


def get_iot_hub_connection_string(client, hub_name, resource_group_name, policy_name='iothubowner'):
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
    result['cs'] = CONN_STR_TEMPLATE.format(target_hub.properties.host_name, policy.key_name, policy.primary_key)
    result['hub'] = target_hub.properties.host_name
    result['policy'] = policy_name
    result['primarykey'] = policy.primary_key
    result['secondarykey'] = policy.secondary_key
    return result
