# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=no-self-use,no-member,line-too-long,too-few-public-methods,no-name-in-module,C0103,R0913

import json
import uuid
from os.path import exists
from time import time, sleep
import six.moves
from azure.cli.core.util import CLIError, read_file_content
from azure.cli.command_modules.iot.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import DeviceAuthType, SdkType
from azext_iot._factory import _bind_sdk
from azext_iot.iot_sdk.utility import block_stdout, Default_Msg_Callbacks, evaluate_literal

from azext_iot.common.shared import get_iot_hub_connection_string
from azext_iot.modules_sdk.models.device_capabilities import DeviceCapabilities
from azext_iot.modules_sdk.models.authentication_mechanism import AuthenticationMechanism
from azext_iot.modules_sdk.models.symmetric_key import SymmetricKey
from azext_iot.modules_sdk.models.x509_thumbprint import X509Thumbprint
from azext_iot.modules_sdk.models.device import Device
from azext_iot.modules_sdk.models.configuration_content import ConfigurationContent
from azext_iot.modules_sdk.models.configuration import Configuration
from azext_iot.modules_sdk.models.error_details import ErrorDetailsException
from azext_iot.modules_sdk.models.device_module import DeviceModule
from azext_iot.device_query_sdk.models.query_specification import QuerySpecification
from azext_iot.device_twin_sdk.models.cloud_to_device_method import CloudToDeviceMethod
from msrestazure.azure_exceptions import CloudError


# Query

def iot_query(client, hub_name, query_command, top=None, resource_group_name=None):
    payload = []
    headers = {}
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    if top:
        if top <= 0:
            raise CLIError('top must be > 0')
    try:
        d_sdk = _bind_sdk(target, SdkType.device_query_sdk)
        query = QuerySpecification(query_command)
        if top:
            headers['x-ms-max-item-count'] = str(top)
        result, token = d_sdk.device_api.query_devices(query, headers)
        payload.extend(result)
        while token:
            # In case requested count is > service max page size
            if top:
                pl = len(payload)
                if pl < top:
                    page = top - pl
                    headers['x-ms-max-item-count'] = str(page)
                else:
                    break
            headers['x-ms-continuation'] = token
            result, token = d_sdk.device_api.query_devices(query, headers)
            payload.extend(result)
        return payload[:top] if top else payload
    except CloudError as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


# Device

def iot_device_show(client, device_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        device = m_sdk.device_api.get_device(device_id)
        device['hub'] = target.get('hub')
        return device
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_list(client, hub_name, top=10, edge_device=False, resource_group_name=None):
    if top <= 0:
        raise CLIError('top must be > 0')
    try:
        query = 'SELECT * FROM devices where capabilities.iotEdge = true' if edge_device else 'SELECT * from devices'
        result = iot_query(client, hub_name, query, top, resource_group_name)
        if not result:
            raise CLIError('No registered devices found.')
        return result
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_create(client, device_id, hub_name, edge_enabled=False,
                      auth_method='shared_private_key', primary_thumbprint=None,
                      secondary_thumbprint=None, status='enabled',
                      resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        device = _assemble_device(
            device_id, auth_method, edge_enabled, primary_thumbprint, secondary_thumbprint, status)
        return m_sdk.device_api.put_device(device_id, device)
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


def _assemble_device(device_id, auth_method, edge_enabled, pk=None, sk=None,
                     status='enabled', status_reason=None):
    auth = _assemble_auth(auth_method, pk, sk)
    cap = DeviceCapabilities(edge_enabled)
    device = Device(device_id=device_id, authentication=auth,
                    capabilities=cap, status=status, status_reason=status_reason)
    return device


def _assemble_auth(auth_method, pk, sk):
    auth = None
    if auth_method == DeviceAuthType.shared_private_key.name or auth_method == 'sas':
        auth = AuthenticationMechanism(
            symmetric_key=SymmetricKey(pk, sk), type='sas')
    elif auth_method == DeviceAuthType.x509_thumbprint.name or auth_method == 'selfSigned':
        if not any([pk, sk]):
            raise ValueError(
                'primary + secondary Thumbprint required with selfSigned auth')
        auth = AuthenticationMechanism(x509_thumbprint=X509Thumbprint(
            pk, sk), type='selfSigned')
    elif auth_method == DeviceAuthType.x509_ca.name or auth_method == 'certificateAuthority':
        auth = AuthenticationMechanism(type='certificateAuthority')
    else:
        raise ValueError(
            'Authorization method {} invalid.'.format(auth_method))
    return auth


def iot_device_update(client, device_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        updated_device = _handle_device_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk = _bind_sdk(target, SdkType.modules_sdk)
            return m_sdk.device_api.put_device(device_id, updated_device, headers)
        raise LookupError("device etag not found.")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as f:
        raise CLIError(f)


def _handle_device_update_params(parameters):
    status = parameters['status'].lower()
    if status not in ['enabled', 'disabled']:
        raise ValueError("status must be one of {}".format(status))

    edge = parameters.get('capabilities').get('iotEdge')
    if not isinstance(edge, bool):
        raise ValueError("capabilities.iotEdge is of type bool")

    auth, pk, sk = _parse_auth(parameters)

    return _assemble_device(parameters['deviceId'], auth, edge, pk, sk, status, parameters.get('statusReason'))


def iot_device_delete(client, device_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        device = m_sdk.device_api.get_device(device_id)
        etag = device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.device_api.delete_device(device_id, headers)
            return
        raise LookupError("device etag not found")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as f:
        raise CLIError(f)


# Module

def iot_device_module_create(client, device_id, hub_name, module_id, auth_method='shared_private_key',
                             primary_thumbprint=None, secondary_thumbprint=None, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        module = _assemble_module(device_id, module_id, auth_method, primary_thumbprint, secondary_thumbprint)
        return m_sdk.module_api.put_module(device_id, module_id, module)
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


def _assemble_module(device_id, module_id, auth_method, pk=None, sk=None):
    auth = _assemble_auth(auth_method, pk, sk)
    module = DeviceModule(module_id=module_id, device_id=device_id, authentication=auth)
    return module


def iot_device_module_update(client, device_id, hub_name, module_id, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        updated_module = _handle_module_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk = _bind_sdk(target, SdkType.modules_sdk)
            return m_sdk.module_api.put_module(device_id, module_id, updated_module, headers)
        raise LookupError("module etag not found.")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


def _handle_module_update_params(parameters):
    auth, pk, sk = _parse_auth(parameters)
    return _assemble_module(parameters['deviceId'], parameters['moduleId'], auth, pk, sk)


def _parse_auth(parameters):
    valid_auth = ['sas', 'selfSigned', 'certificateAuthority']
    auth = parameters.get('authentication').get('type')
    if auth not in valid_auth:
        raise ValueError("authentication.type must be one of {}".format(valid_auth))
    pk = sk = None
    if auth == 'sas':
        pk = parameters.get('authentication').get('symmetricKey').get('primaryKey')
        sk = parameters.get('authentication').get('symmetricKey').get('secondaryKey')
    elif auth == 'selfSigned':
        pk = parameters.get('authentication').get('x509Thumbprint').get('primaryThumbprint')
        sk = parameters.get('authentication').get('x509Thumbprint').get('secondaryThumbprint')
        if not any([pk, sk]):
            raise ValueError("primary + secondary Thumbprint required with selfSigned auth")
    return auth, pk, sk


def iot_device_module_list(client, device_id, hub_name, top=10, resource_group_name=None):
    if top <= 0:
        raise CLIError('top must be > 0')
    try:
        query = "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
        result = iot_query(client, hub_name, query, top, resource_group_name)
        if not result:
            raise CLIError('No modules found on registered devices {}.'.format(device_id))
        return result
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_show(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        return m_sdk.module_api.get_module(device_id, module_id)
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_delete(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        module = m_sdk.module_api.get_module(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.module_api.delete_device_module(device_id, module_id, headers)
            return
        raise LookupError("module etag not found")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as f:
        raise CLIError(f)


# Module Twin

def iot_device_module_twin_show(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        return m_sdk.device_twin_api.get_module_twin(device_id, module_id)
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_twin_update(client, device_id, hub_name, module_id, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.device_twin_api.update_module_twin(device_id, module_id, parameters, headers)
        raise LookupError("module twin etag not found")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as f:
        raise CLIError(f)


def iot_device_module_twin_replace(client, device_id, hub_name, module_id, target_json, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = json.loads(target_json)
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        module = m_sdk.device_twin_api.get_module_twin(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.device_twin_api.replace_module_twin(device_id, module_id, target_json, headers)
        raise LookupError("module twin etag not found")
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as f:
        raise CLIError(f)


# Configuration

def iot_device_configuration_apply(client, device_id, hub_name, content, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        if exists(content):
            content = str(read_file_content(content))
        content = json.loads(content)
        test_root = content.get('content', None)
        if test_root:
            content = test_root
        module_content = content.get('moduleContent', None)
        if not module_content:
            raise CLIError("content json must include 'moduleContent' property.")
        content = ConfigurationContent(module_content=module_content)
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        m_sdk.device_api.apply_configuration_content_on_device(device_id, content)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_create(client, config_id, hub_name, content, target_condition="", priority=0,
                                    labels=None, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        if exists(content):
            content = str(read_file_content(content))
        content = json.loads(content)
        content = content.get('content', None)
        if not content:
            raise CLIError("content json must include 'content' property.")
        if labels:
            labels = evaluate_literal(labels, dict)
            if not labels:
                raise CLIError('labels are malformed, expecting dictionary')
        config = Configuration(id=config_id,
                               schema_version="1.0",
                               labels=labels,
                               content=content,
                               content_type="assignments",
                               target_condition=target_condition,
                               etag=None,
                               priority=priority)
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        return m_sdk.configuration_api.put_configuration(config_id, config)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except ErrorDetailsException as f:
        raise CLIError(f)
    except Exception as x:
        raise CLIError(x)


def iot_device_configuration_update(client, config_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        parameters = _handle_device_configuration_update_params(parameters)
        etag = parameters.get('etag', None)
        headers = {}
        if not etag:
            raise CLIError('invalid request, etag is missing.')
        headers["If-Match"] = '"{}"'.format(etag)
        config = Configuration(id=config_id,
                               schema_version="1.0",
                               labels=parameters['labels'],
                               content=parameters['content'],
                               content_type="assignments",
                               target_condition=parameters['targetCondition'],
                               priority=parameters['priority'])
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        m_sdk.configuration_api.put_configuration(config_id, config, headers)
    except ValueError as e:
        raise CLIError(e)
    except ErrorDetailsException as f:
        raise CLIError(f)


def _handle_device_configuration_update_params(parameters):
    content = parameters['content']
    if isinstance(content, six.text_type):
        if exists(content):
            content = str(read_file_content(content))
        content = json.loads(content)
    parameters['content'] = content
    labels = parameters.get('labels', None)
    if labels:
        if not isinstance(labels, dict):
            labels = evaluate_literal(labels, dict)
            if not labels:
                raise ValueError('labels are malformed, expecting dictionary')
    parameters['labels'] = labels
    return parameters


def iot_device_configuration_show(client, config_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        return m_sdk.configuration_api.get_configuration(config_id)
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_list(client, hub_name, top=5, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        if top <= 0:
            raise CLIError('top must be > 0')
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        return m_sdk.configuration_api.get_configurations(top)
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_delete(client, config_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        m_sdk = _bind_sdk(target, SdkType.modules_sdk)
        config = m_sdk.configuration_api.get_configuration(config_id)
        etag = config.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.configuration_api.delete_configuration(config_id, headers)
            return
        raise LookupError("configuration etag not found")
    except ErrorDetailsException as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


# Device Twin

def iot_device_twin_show(client, device_id, hub_name, resource_group_name=None):
    try:
        query = "SELECT * FROM devices where devices.deviceId='{}'".format(device_id)
        result = iot_query(client, hub_name, query, None, resource_group_name)
        if not result:
            raise CLIError("No registered device '{}' found.".format(device_id))
        return result[0]
    except ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_twin_update(client, device_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    try:
        dt_sdk = _bind_sdk(target, SdkType.device_twin_sdk)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return dt_sdk.update_device_twin(device_id, parameters, headers)
        raise LookupError("device twin etag not found")
    except CloudError as e:
        raise CLIError(e)
    except Exception as x:
        raise CLIError(x)


# Device Method Invoke

def iot_device_method(client, device_id, hub_name, method_name, method_payload, timeout=60, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    if timeout > 300:
        raise CLIError('timeout must not be over 300 seconds')
    if timeout < 10:
        raise CLIError('timeout must be at least 10 seconds')

    try:
        if exists(method_payload):
            method_payload = str(read_file_content(method_payload))
        method_payload = json.loads(method_payload)
        dt_sdk = _bind_sdk(target, SdkType.device_twin_sdk)
        method = CloudToDeviceMethod(method_name, method_payload, timeout, timeout)
        return dt_sdk.invoke_device_method(device_id, method)
    except ValueError as e:
        raise CLIError('method_payload json malformed: {}'.format(e))
    except CloudError as f:
        if f.status_code == 404:
            raise CLIError('method not found')
        raise CLIError(f)
    except Exception as x:
        raise CLIError(x)


# Utility

def iot_get_sas_token(client, hub_name, device_id=None, policy_name='iothubowner', duration=3600, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name, policy_name)
    uri = '{0}/devices/{1}'.format(target['hub'], device_id) if device_id else target['hub']
    return SasTokenAuthentication(uri, target['policy'], target['primarykey'], time() + duration).generate_sas_token()


def _build_device_connection_string(client, device_id, hub_name, resource_group_name=None):
    device = iot_device_show(client, device_id, hub_name, resource_group_name)
    template = 'HostName={};DeviceId={};{}'
    auth = device.get('authentication')
    if auth:
        auth_type = auth.get('type')
        if auth_type:
            key = None
            auth_type = auth_type.lower()
            if auth_type == 'sas':
                key = 'SharedAccessKey={}'
                key = key.format(auth['symmetricKey']['primaryKey'])
            elif auth_type == 'certificateauthority' or auth_type == 'selfsigned':
                key = 'x509=true'

            if key:
                return template.format(device.get('hub'), device.get('deviceId'), key)
    raise CLIError("Unable to form target device '{}' connection string".format(device_id))


# Messaging

def iot_device_send_message_ext(client, device_id, hub_name, protocol='http', data='Ping from Azure CLI',
                                resource_group_name=None, message_id=None, correlation_id=None, user_id=None):
    # Isolate native C extension import to specific commands
    from iothub_client import IoTHubClientError
    from azext_iot.iot_sdk.device_manager import DeviceManager

    try:
        c = _build_device_connection_string(client, device_id, hub_name, resource_group_name)
        protocol = _iot_sdk_device_process_protocol(protocol)
        with block_stdout():
            device = DeviceManager(c, protocol)
            device.send_event(data, {'UserId': user_id} if user_id else None, message_id, correlation_id)
    except IoTHubClientError as e:
        raise CLIError(e)
    except RuntimeError as f:
        raise CLIError(f)


def iot_hub_message_send(client, device_id, hub_name, message_id=str(uuid.uuid4()), correlation_id=None,
                         data="Ping from Azure CLI", wait_feedback=False, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    from iothub_service_client import IoTHubError, IoTHubMessaging, IoTHubMessage
    try:
        iothub_messaging = IoTHubMessaging(target['cs'])
        message = IoTHubMessage(data)

        # optional: assign ids
        if correlation_id is not None:
            message.correlation_id = correlation_id
        if message_id is not None:
            message.message_id = message_id

        default = Default_Msg_Callbacks()

        iothub_messaging.open(default.open_complete_callback, 0)

        if wait_feedback:
            iothub_messaging.set_feedback_message_callback(default.feedback_received_callback, 0)

        iothub_messaging.send_async(device_id, message, default.send_complete_callback, 0)
        sleep(2)

        if wait_feedback:
            wait_feedback_msg = "Waiting for message feedback, press any key to continue...\n\n"
            six.print_('', flush=True)
            six.moves.input(wait_feedback_msg)

        iothub_messaging.close()
    except IoTHubError as e:
        raise CLIError("Unexpected client error %s" % e)
    except Exception as x:
        raise CLIError(x)


def iot_simulate_device(client, device_id, hub_name, settle='complete', protocol='amqp', data="Ping from Azure CLI",
                        message_count=5, message_interval=1, receive_count=None, file_path=None, resource_group_name=None):
    # Isolate native C extension import to specific commands
    from iothub_client import IoTHubClientError
    from azext_iot.iot_sdk.device_manager import DeviceManager

    if message_count < 0:
        raise CLIError("message-count must be at least 0!")
    if message_interval < 1:
        raise CLIError("message-interval must be > 0!")

    try:
        protocol = _iot_sdk_device_process_protocol(protocol)
        c = _build_device_connection_string(client, device_id, hub_name, resource_group_name)
        with block_stdout():
            sim_client = DeviceManager(c, protocol)

        if file_path:
            sim_client.upload_file_to_blob(file_path)

        if receive_count:
            sim_client.configure_receive_settle(settle)

        for message_counter in range(0, message_count):
            print_context = "Sending message %s, via %s with %s sec delay" % (message_counter + 1,
                                                                              protocol, message_interval)
            sim_client.send_event(data, None, str(uuid.uuid4()),
                                  str(uuid.uuid4()), 0, print_context)
            sleep(message_interval)

        if receive_count:
            if receive_count == -1:
                while True:
                    sleep(1)
            else:
                while sim_client.received() < receive_count:
                    sleep(1)

    except IoTHubClientError as e:
        raise CLIError("Unexpected client error %s" % e)
    except RuntimeError as f:
        raise CLIError("Unexpected runtime error %s" % f)


def _iot_sdk_device_process_protocol(protocol_string):
    from iothub_client import IoTHubTransportProvider
    protocol = None
    protocol_string = protocol_string.lower()
    if protocol_string == "http":
        if hasattr(IoTHubTransportProvider, "HTTP"):
            protocol = IoTHubTransportProvider.HTTP
    elif protocol_string == "amqp":
        if hasattr(IoTHubTransportProvider, "AMQP"):
            protocol = IoTHubTransportProvider.AMQP
    elif protocol_string == "mqtt":
        if hasattr(IoTHubTransportProvider, "MQTT"):
            protocol = IoTHubTransportProvider.MQTT
    else:
        raise ValueError("Error: {} protocol is not supported".format(protocol_string))

    return protocol
