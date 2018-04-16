# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=wrong-import-order

from os.path import exists, basename
from time import time, sleep
import six
from knack.log import get_logger
from knack.util import CLIError
from azure.cli.core.util import read_file_content
from azext_iot._constants import EXTENSION_ROOT
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import (DeviceAuthType,
                                     SdkType)
from azext_iot.common.azure import get_iot_hub_connection_string
from azext_iot.common.utility import (shell_safe_json_parse,
                                      validate_key_value_pairs, url_encode_dict,
                                      evaluate_literal)
from azext_iot._factory import _bind_sdk
from azext_iot.operations.generic import execute_query

from azext_iot.modules_sdk.models.device_capabilities import DeviceCapabilities
from azext_iot.modules_sdk.models.authentication_mechanism import AuthenticationMechanism
from azext_iot.modules_sdk.models.symmetric_key import SymmetricKey
from azext_iot.modules_sdk.models.x509_thumbprint import X509Thumbprint
from azext_iot.modules_sdk.models.device import Device
from azext_iot.modules_sdk.models.configuration_content import ConfigurationContent
from azext_iot.modules_sdk.models.configuration import Configuration
from azext_iot.modules_sdk.models.device_module import DeviceModule

logger = get_logger(__name__)


# Query

def iot_query(cmd, query_command, hub_name=None, top=None, resource_group_name=None, login=None):
    from azext_iot.device_query_sdk.models.query_specification import QuerySpecification
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    q_sdk, errors = _bind_sdk(target, SdkType.device_query_sdk)
    try:
        query = QuerySpecification(query_command)
        return execute_query(query, q_sdk.device_api.query_devices, errors, top)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device

def iot_device_show(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_device_show(target, device_id)


def _iot_device_show(target, device_id):
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        device = m_sdk.device_api.get_device(device_id)
        device['hub'] = target.get('entity')
        return device
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_list(cmd, hub_name=None, top=10, edge_enabled=False, resource_group_name=None, login=None):
    if top <= 0:
        raise CLIError('top must be > 0')

    query = 'select * from devices where capabilities.iotEdge = true' if edge_enabled else 'select * from devices'
    result = iot_query(cmd, query, hub_name, top, resource_group_name, login=login)
    if not result:
        logger.info('No registered devices found on hub "%s".', hub_name)
    return result


def iot_device_create(cmd, device_id, hub_name=None, edge_enabled=False,
                      auth_method='shared_private_key', primary_thumbprint=None,
                      secondary_thumbprint=None, status='enabled', status_reason=None,
                      valid_days=None, output_dir=None, resource_group_name=None, login=None):

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else valid_days
        if output_dir and not exists(output_dir):
            raise CLIError('certificate output directory of "{}" does not exist.')
        cert = _create_self_signed_cert(device_id, valid_days, output_dir)
        primary_thumbprint = cert['thumbprint']

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        device = _assemble_device(
            device_id, auth_method, edge_enabled, primary_thumbprint, secondary_thumbprint, status, status_reason)
        return m_sdk.device_api.put_device(device_id, device)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


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
        if not pk:
            raise ValueError('primary thumbprint required with selfSigned auth')
        auth = AuthenticationMechanism(x509_thumbprint=X509Thumbprint(
            pk, sk), type='selfSigned')
    elif auth_method == DeviceAuthType.x509_ca.name or auth_method == 'certificateAuthority':
        auth = AuthenticationMechanism(type='certificateAuthority')
    else:
        raise ValueError(
            'Authorization method {} invalid.'.format(auth_method))
    return auth


def _create_self_signed_cert(subject, valid_days, output_path=None):
    from azext_iot.common.certops import create_self_signed_certificate
    return create_self_signed_certificate(subject, valid_days, output_path)


def iot_device_update(cmd, device_id, parameters, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        updated_device = _handle_device_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.device_api.put_device(device_id, updated_device, headers)
        raise LookupError("device etag not found.")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def _handle_device_update_params(parameters):
    status = parameters['status'].lower()
    if status not in ['enabled', 'disabled']:
        raise ValueError("status must be one of {}".format(status))

    edge = parameters.get('capabilities').get('iotEdge')
    if not isinstance(edge, bool):
        raise ValueError("capabilities.iotEdge is of type bool")

    auth, pk, sk = _parse_auth(parameters)

    return _assemble_device(parameters['deviceId'], auth, edge, pk, sk, status, parameters.get('statusReason'))


def iot_device_delete(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        device = m_sdk.device_api.get_device(device_id)
        etag = device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.device_api.delete_device(device_id, headers)
            return
        raise LookupError("device etag not found")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Module

def iot_device_module_create(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        # Current SPK auth only
        auth_method = 'shared_private_key'
        module = _assemble_module(device_id, module_id, auth_method, None, None)
        return m_sdk.module_api.put_module(device_id, module_id, module)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def _assemble_module(device_id, module_id, auth_method, pk=None, sk=None):
    auth = _assemble_auth(auth_method, pk, sk)
    module = DeviceModule(module_id=module_id, device_id=device_id, authentication=auth)
    return module


def iot_device_module_update(cmd, device_id, module_id, parameters,
                             hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        updated_module = _handle_module_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.module_api.put_module(device_id, module_id, updated_module, headers)
        raise LookupError("module etag not found.")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


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


def iot_device_module_list(cmd, device_id, hub_name=None, top=10, resource_group_name=None, login=None):
    if top <= 0:
        raise CLIError('top must be > 0')

    query = "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
    result = iot_query(cmd, query, hub_name, top, resource_group_name, login=login)
    if not result:
        logger.info('No modules found on registered device "%s".', device_id)
    return result


def iot_device_module_show(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        module = m_sdk.module_api.get_module(device_id, module_id)
        module['hub'] = target.get('entity')
        return module
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_delete(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        module = m_sdk.module_api.get_module(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.module_api.delete_device_module(device_id, module_id, headers)
            return
        raise LookupError("module etag not found")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Module Twin

def iot_device_module_twin_show(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        return m_sdk.device_twin_api.get_module_twin(device_id, module_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_twin_update(cmd, device_id, module_id, parameters, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.device_twin_api.update_module_twin(device_id, module_id, parameters, headers)
        raise LookupError("module twin etag not found")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_twin_replace(cmd, device_id, module_id, target_json, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = shell_safe_json_parse(target_json)
        module = m_sdk.device_twin_api.get_module_twin(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return m_sdk.device_twin_api.replace_module_twin(device_id, module_id, target_json, headers)
        raise LookupError("module twin etag not found")
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Configuration

def iot_device_configuration_apply(cmd, device_id, content, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if exists(content):
            content = str(read_file_content(content))
        content = shell_safe_json_parse(content)
        test_root = content.get('content', None)
        if test_root:
            content = test_root
        module_content = content.get('moduleContent', None)
        if not module_content:
            raise CLIError("content json must include 'moduleContent' property.")
        content = ConfigurationContent(module_content=module_content)
        m_sdk.device_api.apply_configuration_content_on_device(device_id, content)
        return iot_device_module_list(cmd, device_id, hub_name=hub_name, top=1000, login=login)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_create(cmd, config_id, content, hub_name=None, target_condition="", priority=0,
                                    labels=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if exists(content):
            content = str(read_file_content(content))
        content = shell_safe_json_parse(content)
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
        return m_sdk.configuration_api.put_configuration(config_id, config)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_update(cmd, config_id, parameters, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
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
        return m_sdk.configuration_api.put_configuration(config_id, config, headers)
    except ValueError as e:
        raise CLIError(e)
    except errors.ErrorDetailsException as f:
        raise CLIError(f)


def _handle_device_configuration_update_params(parameters):
    content = parameters['content']
    if isinstance(content, six.string_types):
        if exists(content):
            content = str(read_file_content(content))
        content = shell_safe_json_parse(content)
    parameters['content'] = content
    labels = parameters.get('labels', None)
    if labels:
        if not isinstance(labels, dict):
            labels = evaluate_literal(labels, dict)
            if not labels:
                raise ValueError('labels are malformed, expecting dictionary')
    parameters['labels'] = labels
    return parameters


def iot_device_configuration_show(cmd, config_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        return m_sdk.configuration_api.get_configuration(config_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_list(cmd, hub_name=None, top=5, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if top <= 0:
        raise CLIError('top must be > 0')
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        result = m_sdk.configuration_api.get_configurations(top)
        if not result:
            logger.info('No Edge deployment configurations found on hub "%s".', hub_name)
        return result
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_delete(cmd, config_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        config = m_sdk.configuration_api.get_configuration(config_id)
        etag = config.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            m_sdk.configuration_api.delete_configuration(config_id, headers)
            return
        raise LookupError("configuration etag not found")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device Twin

def iot_device_twin_show(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    query = "SELECT * FROM devices where devices.deviceId='{}'".format(device_id)
    result = iot_query(cmd, query, hub_name, None, resource_group_name, login=login)
    if not result:
        raise CLIError('No registered device "{}" found.'.format(device_id))
    return result[0]


def iot_device_twin_update(cmd, device_id, parameters, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    dt_sdk, errors = _bind_sdk(target, SdkType.device_twin_sdk)

    try:
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return dt_sdk.update_device_twin(device_id, parameters, headers)
        raise LookupError("device twin etag not found")
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_twin_replace(cmd, device_id, target_json, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    dt_sdk, errors = _bind_sdk(target, SdkType.device_twin_sdk)

    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = shell_safe_json_parse(target_json)
        device = dt_sdk.get_device_twin(device_id)
        etag = device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return dt_sdk.replace_device_twin(device_id, target_json, headers)
        raise LookupError("device twin etag not found")
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device Method Invoke

def iot_device_method(cmd, device_id, method_name, hub_name=None, method_payload="{}",
                      timeout=60, resource_group_name=None, login=None):
    from azext_iot.device_twin_sdk.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot._constants import METHOD_INVOKE_MAX_TIMEOUT_SEC, METHOD_INVOKE_MIN_TIMEOUT_SEC

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MAX_TIMEOUT_SEC))
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError('timeout must be at least {} seconds'.format(METHOD_INVOKE_MIN_TIMEOUT_SEC))

    dt_sdk, errors = _bind_sdk(target, SdkType.device_twin_sdk)

    try:
        if method_payload:
            if exists(method_payload):
                method_payload = str(read_file_content(method_payload))
            method_payload = shell_safe_json_parse(method_payload)

        method = CloudToDeviceMethod(method_name, method_payload, timeout, timeout)
        return dt_sdk.invoke_device_method(device_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device Module Method Invoke

def iot_device_module_method(cmd, device_id, module_id, method_name, hub_name=None, method_payload="{}",
                             timeout=60, resource_group_name=None, login=None):
    from azext_iot.modules_sdk.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot._constants import METHOD_INVOKE_MAX_TIMEOUT_SEC, METHOD_INVOKE_MIN_TIMEOUT_SEC

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MAX_TIMEOUT_SEC))
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MIN_TIMEOUT_SEC))

    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if method_payload:
            if exists(method_payload):
                method_payload = str(read_file_content(method_payload))
            method_payload = shell_safe_json_parse(method_payload)

        method = CloudToDeviceMethod(method_name, method_payload, timeout, timeout)
        return m_sdk.module_api.invoke_device_module_method(device_id, module_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Utility

def iot_get_sas_token(cmd, hub_name=None, device_id=None, policy_name='iothubowner',
                      key_type='primary', duration=3600, resource_group_name=None, login=None):
    key_type = key_type.lower()
    policy_name = policy_name.lower()

    if login and policy_name != 'iothubowner':
        raise CLIError('You are unable to change the sas policy with a hub connection string login.')
    if login and key_type != 'primary' and not device_id:
        raise CLIError('For non-device sas, you are unable to change the key type with a connection string login.')

    return {'sas': _iot_build_sas_token(cmd, hub_name, device_id,
                                        policy_name, key_type, duration, resource_group_name, login).generate_sas_token()}


def _iot_build_sas_token(cmd, hub_name=None, device_id=None, policy_name='iothubowner',
                         key_type='primary', duration=3600, resource_group_name=None, login=None):
    from azext_iot.common.azure import parse_iot_device_connection_string

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, policy_name, login=login)
    uri = None
    policy = None
    key = None
    if device_id:
        logger.info('Obtaining device "%s" details from registry, using IoT Hub policy "%s"', device_id, policy_name)
        device = _iot_device_show(target, device_id)
        device_cs = _build_device_or_module_connection_string(device=device, key_type=key_type)
        uri = '{}/devices/{}'.format(target['entity'], device_id)
        try:
            parsed_device_cs = parse_iot_device_connection_string(device_cs)
        except ValueError as e:
            logger.debug(e)
            raise CLIError('This device does not support SAS auth.')

        key = parsed_device_cs['SharedAccessKey']
    else:
        uri = target['entity']
        policy = target['policy']
        key = target['primarykey'] if key_type == 'primary' else target['secondarykey']

    return SasTokenAuthentication(uri, policy, key, time() + int(duration))


# pylint: disable=inconsistent-return-statements
def _build_device_or_module_connection_string(device, key_type='primary', module=None):
    template = 'HostName={};DeviceId={};ModuleId={};{}' if module else 'HostName={};DeviceId={};{}'
    auth = module.get('authentication') if module else device.get('authentication')
    if auth:
        auth_type = auth.get('type')
        if auth_type:
            key = None
            auth_type = auth_type.lower()
            if auth_type == 'sas':
                key = 'SharedAccessKey={}'
                key = key.format(auth['symmetricKey']['primaryKey'] if key_type == 'primary'
                                 else auth['symmetricKey']['secondaryKey'])
            elif auth_type == 'certificateauthority' or auth_type == 'selfsigned':
                key = 'x509=true'
            if key:
                if module:
                    return template.format(module.get('hub'), module.get('deviceId'), module.get('moduleId'), key)
                return template.format(device.get('hub'), device.get('deviceId'), key)
    raise CLIError('Unable to form target connection string')


def iot_get_hub_connection_string(cmd, hub_name, policy_name='iothubowner', key_type='primary',
                                  resource_group_name=None):
    result = {}
    result['cs'] = get_iot_hub_connection_string(cmd, hub_name, resource_group_name,
                                                 policy_name, key_type)['cs']
    return result


def iot_get_device_connection_string(cmd, device_id, hub_name=None, key_type='primary',
                                     resource_group_name=None, login=None):
    result = {}
    device = iot_device_show(cmd, device_id,
                             hub_name=hub_name, resource_group_name=resource_group_name, login=login)
    result['cs'] = _build_device_or_module_connection_string(device, key_type)
    return result


def iot_get_module_connection_string(cmd, device_id, module_id, hub_name=None, key_type='primary',
                                     resource_group_name=None, login=None):
    result = {}
    module = iot_device_module_show(cmd, device_id, module_id,
                                    resource_group_name=resource_group_name, hub_name=hub_name, login=login)
    result['cs'] = _build_device_or_module_connection_string(None, key_type, module)
    return result


# Messaging

def iot_device_send_message(cmd, device_id, hub_name=None, data='Ping from Az CLI IoT Extension',
                            properties=None, msg_count=1, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_device_send_message(target, device_id, data, properties, msg_count)


def _iot_device_send_message(target, device_id, data, properties=None, msg_count=1):
    import paho.mqtt.publish as publish
    from paho.mqtt import client as mqtt
    import ssl
    import os

    msgs = []
    if properties:
        properties = validate_key_value_pairs(properties)

    sas = SasTokenAuthentication(target['entity'], target['policy'], target['primarykey'], time() + 360).generate_sas_token()
    cwd = EXTENSION_ROOT
    cert_path = os.path.join(cwd, 'digicert.pem')
    auth = {'username': '{}/{}/api-version=2016-11-14'.format(target['entity'], device_id), 'password': sas}
    tls = {'ca_certs': cert_path, 'tls_version': ssl.PROTOCOL_SSLv23}
    topic = 'devices/{}/messages/events/{}'.format(device_id, url_encode_dict(properties) if properties else '')
    for _ in range(msg_count):
        msgs.append({'topic': topic, 'payload': data})
    try:
        publish.multiple(msgs, client_id=device_id, hostname=target['entity'],
                         auth=auth, port=8883, protocol=mqtt.MQTTv311, tls=tls)
        return
    except Exception as x:
        raise CLIError(x)


def iot_device_send_message_http(cmd, device_id, data, hub_name=None, msg_id=None,
                                 corr_id=None, user_id=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_device_send_message_http(target, device_id, data, msg_id, corr_id, user_id)


def _iot_device_send_message_http(target, device_id, data, msg_id=None,
                                  corr_id=None, user_id=None):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.send_message(device_id, data, msg_id, corr_id, user_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_complete(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_complete(target, device_id, etag)


def _iot_c2d_message_complete(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.complete_or_reject_message(device_id, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_reject(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_reject(target, device_id, etag)


def _iot_c2d_message_reject(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.complete_or_reject_message(device_id, etag, '')
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_abandon(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_abandon(target, device_id, etag)


def _iot_c2d_message_abandon(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.abandon_message(device_id, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_receive(cmd, device_id, hub_name=None, lock_timeout=60, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_receive(target, device_id, lock_timeout)


def _iot_c2d_message_receive(target, device_id, lock_timeout=60):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        result = msg_sdk.iot_hub_devices.receive_message(device_id, lock_timeout, raw=True)
        if result and result.response.status_code == 200:
            return {
                'ack': result.headers['iothub-ack'],
                'correlationId': result.headers['iothub-correlationid'],
                'data': result.response.content,
                'deliveryCount': result.headers['iothub-deliverycount'],
                'enqueuedTime': result.headers['iothub-enqueuedtime'],
                'expiry': result.headers['iothub-expiry'],
                'etag': result.headers['ETag'].strip('"'),
                'messageId': result.headers['iothub-messageid'],
                'sequenceNumber': result.headers['iothub-sequencenumber'],
                'to': result.headers['iothub-to'],
                'userId': result.headers['iothub-userid']
            }
        return {}
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# pylint: disable=too-many-locals
def iot_simulate_device(cmd, device_id, hub_name=None, receive_settle='complete',
                        data='Ping from Az CLI IoT Extension', msg_count=100,
                        msg_interval=3, protocol_type='mqtt', resource_group_name=None, login=None):
    import sys
    import uuid
    import datetime
    import json
    from azext_iot.operations._mqtt import mqtt_client_wrap
    from azext_iot.common.utility import execute_onthread
    from azext_iot._constants import MIN_SIM_MSG_INTERVAL, MIN_SIM_MSG_COUNT, SIM_RECEIVE_SLEEP_SEC

    if protocol_type == 'mqtt':
        if receive_settle != 'complete':
            raise CLIError('mqtt protocol only supports settle type of "complete"')

    if msg_interval < MIN_SIM_MSG_INTERVAL:
        raise CLIError('msg interval must be at least {}'.format(MIN_SIM_MSG_INTERVAL))

    if msg_count < MIN_SIM_MSG_COUNT:
        raise CLIError('msg count must be at least {}'.format(MIN_SIM_MSG_COUNT))

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    token = None

    # pylint: disable=too-few-public-methods
    class generator(object):
        def __init__(self):
            self.calls = 0

        def generate(self, jsonify=True):
            self.calls += 1
            payload = {'id': str(uuid.uuid4()), 'timestamp': str(datetime.datetime.utcnow()),
                       'data': str(data + ' #{}'.format(self.calls))}
            return json.dumps(payload) if jsonify else payload

    def http_wrap(target, device_id, generator):
        d = generator.generate(False)
        _iot_device_send_message_http(target, device_id, d)
        six.print_('.', end='', flush=True)
        return

    try:
        if protocol_type == 'mqtt':
            wrap = mqtt_client_wrap(target, device_id)
            wrap.execute(generator(), publish_delay=msg_interval, msg_count=msg_count)
        else:
            six.print_('Sending and receiving events via https')
            token, op = execute_onthread(method=http_wrap,
                                         args=[target, device_id, generator()],
                                         interval=msg_interval, max_runs=msg_count,
                                         return_handle=True)
            while True and op.is_alive():
                _handle_c2d_msg(target, device_id, receive_settle)
                sleep(SIM_RECEIVE_SLEEP_SEC)

    except KeyboardInterrupt:
        sys.exit()
    except Exception as x:
        raise CLIError(x)
    finally:
        if token:
            token.set()


def _handle_c2d_msg(target, device_id, receive_settle):
    result = _iot_c2d_message_receive(target, device_id)
    if result:
        six.print_()
        six.print_('__Received C2D Message__')
        six.print_(result)
        if receive_settle == 'reject':
            six.print_('__Rejecting message__')
            _iot_c2d_message_reject(target, device_id, result['etag'])
        elif receive_settle == 'abandon':
            six.print_('__Abandoning message__')
            _iot_c2d_message_abandon(target, device_id, result['etag'])
        else:
            six.print_('__Completing message__')
            _iot_c2d_message_complete(target, device_id, result['etag'])
        return True
    return False


def iot_device_export(cmd, hub_name, blob_container_uri, include_keys=False, resource_group_name=None):
    from azext_iot._factory import iot_hub_service_factory
    client = iot_hub_service_factory(cmd.cli_ctx)
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.export_devices(target['resourcegroup'], hub_name, blob_container_uri, not include_keys)


def iot_device_import(cmd, hub_name, input_blob_container_uri, output_blob_container_uri, resource_group_name=None):
    from azext_iot._factory import iot_hub_service_factory
    client = iot_hub_service_factory(cmd.cli_ctx)
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.import_devices(target['resourcegroup'], hub_name,
                                 input_blob_container_uri, output_blob_container_uri)


def iot_device_upload_file(cmd, device_id, file_path, content_type, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if not exists(file_path):
        raise CLIError('File path "{}" does not exist!'.format(file_path))

    content = None
    with open(file_path, 'rb') as input_file:
        content = input_file.read()
    filename = basename(file_path)

    custom_sdk, errors = _bind_sdk(target, SdkType.custom_sdk)
    try:
        container = custom_sdk.build_device_file_container(device_id, filename)
        storage_endpoint = '{}/{}/{}{}'.format(container['hostName'], container['containerName'],
                                               container['blobName'], container['sasToken'])
        custom_sdk.upload_file_to_container(storage_endpoint, content, content_type)
        custom_sdk.post_file_notification(device_id, container['correlationId'])
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# pylint: disable=too-many-locals
def iot_hub_monitor_events(cmd, hub_name, device_id=None, consumer_group='$Default', timeout=300,
                           enqueued_time=None, resource_group_name=None, yes=False, properties=None, repair=False):
    from azext_iot.common.utility import validate_min_python_version
    validate_min_python_version(3, 5)

    import importlib
    import sys
    from os import linesep
    from datetime import datetime
    from six.moves import input
    from azext_iot.common.config import get_uamqp_ext_version, update_uamqp_ext_version
    from azext_iot._constants import EVENT_LIB, VERSION
    from azext_iot.common.utility import test_import
    from azext_iot.common.pip import install

    events3 = importlib.import_module('azext_iot.operations.events3._events')

    config = cmd.cli_ctx.config

    if not properties:
        properties = []
    properties = set((key.lower() for key in properties))

    if timeout < 0:
        raise CLIError('Monitoring timeout must be 0 (inf) or greater.')
    timeout = (timeout * 1000)

    if get_uamqp_ext_version(config) != EVENT_LIB[1] or repair or not test_import(EVENT_LIB[0]):
        if not yes:
            input_txt = ('Dependency update required for IoT extension version: {}. {}'
                         'Updated dependency must be compatible with {} {}. '
                         'Continue? (y/n) -> ').format(VERSION, linesep, EVENT_LIB[0], EVENT_LIB[1])
            i = input(input_txt)
            if i.lower() != 'y':
                sys.exit('User has declined update...')

        six.print_('Updating required dependency...')
        if install(EVENT_LIB[0], compatible_version=EVENT_LIB[1]):
            update_uamqp_ext_version(config, EVENT_LIB[1])
            six.print_('Update appears to have worked. Executing command...')
        else:
            sys.exit('Failure updating {} {}. Aborting...'.format(EVENT_LIB[0], EVENT_LIB[1]))

    def _calculate_millisec_since_unix_epoch_utc():
        now = datetime.utcnow()
        epoch = datetime.utcfromtimestamp(0)
        return int(1000 * (now - epoch).total_seconds())

    if not enqueued_time:
        enqueued_time = _calculate_millisec_since_unix_epoch_utc()

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, include_events=True)

    events3.executor(target,
                     consumer_group=consumer_group,
                     enqueued_time=enqueued_time,
                     properties=properties,
                     timeout=timeout,
                     device_id=device_id)
