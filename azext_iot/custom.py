# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=no-self-use,no-member,line-too-long,too-few-public-methods,no-name-in-module,C0103,R0913

import json
from os.path import exists, basename
from time import time, sleep
import six
from knack.log import get_logger
from knack.util import CLIError
from azure.cli.core.util import read_file_content
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import (DeviceAuthType, 
                                     SdkType, 
                                     AttestationType,
                                     get_iot_hub_connection_string, 
                                     get_iot_dps_connection_string)
from azext_iot.common.utility import validate_key_value_pairs, evaluate_literal
from azext_iot.common.certops import open_certificate
from azext_iot._factory import _bind_sdk

from azext_iot.modules_sdk.models.device_capabilities import DeviceCapabilities
from azext_iot.modules_sdk.models.authentication_mechanism import AuthenticationMechanism
from azext_iot.modules_sdk.models.symmetric_key import SymmetricKey
from azext_iot.modules_sdk.models.x509_thumbprint import X509Thumbprint
from azext_iot.modules_sdk.models.device import Device
from azext_iot.modules_sdk.models.configuration_content import ConfigurationContent
from azext_iot.modules_sdk.models.configuration import Configuration
from azext_iot.modules_sdk.models.device_module import DeviceModule

from azext_iot.dps_sdk.models.individual_enrollment import IndividualEnrollment
from azext_iot.dps_sdk.models.attestation_mechanism import AttestationMechanism
from azext_iot.dps_sdk.models.tpm_attestation import TpmAttestation
from azext_iot.dps_sdk.models.x509_attestation import X509Attestation
from azext_iot.dps_sdk.models.x509_certificates import X509Certificates
from azext_iot.dps_sdk.models.x509_certificate_with_info import X509CertificateWithInfo
from azext_iot.dps_sdk.models.initial_twin import InitialTwin
from azext_iot.dps_sdk.models.twin_collection import TwinCollection
from azext_iot.dps_sdk.models.initial_twin_properties import InitialTwinProperties
from azext_iot.dps_sdk.models.enrollment_group import EnrollmentGroup

logger = get_logger(__name__)

# Query

def iot_query(client, hub_name, query_command, top=None, resource_group_name=None):
    from azext_iot.device_query_sdk.models.query_specification import QuerySpecification
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    q_sdk, errors = _bind_sdk(target, SdkType.device_query_sdk)
    try:
        query = QuerySpecification(query_command)
        return _execute_query(client, query, q_sdk.device_api.query_devices, errors, top)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device

def iot_device_show(client, device_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        device = m_sdk.device_api.get_device(device_id)
        device['hub'] = target.get('entity')
        return device
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_list(client, hub_name, top=10, edge_enabled=False, resource_group_name=None):
    if top <= 0:
        raise CLIError('top must be > 0')

    query = 'SELECT * FROM devices where capabilities.iotEdge = true' if edge_enabled else 'SELECT * from devices'
    result = iot_query(client, hub_name, query, top, resource_group_name)
    if not result:
        logger.info('No registered devices found on hub "%s".', hub_name)
    return result


def iot_device_create(client, device_id, hub_name, edge_enabled=False,
                      auth_method='shared_private_key', primary_thumbprint=None,
                      secondary_thumbprint=None, status='enabled', status_reason=None,
                      valid_days=None, output_dir=None, resource_group_name=None):

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else valid_days
        if output_dir and not exists(output_dir):
            raise CLIError('certificate output directory of "{}" does not exist.')
        cert = _create_self_signed_cert(device_id, valid_days, output_dir)
        primary_thumbprint = cert['thumbprint']

    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_update(client, device_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_delete(client, device_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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

def iot_device_module_create(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_module_update(client, device_id, hub_name, module_id, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_module_list(client, device_id, hub_name, top=10, resource_group_name=None):
    if top <= 0:
        raise CLIError('top must be > 0')

    query = "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
    result = iot_query(client, hub_name, query, top, resource_group_name)
    if not result:
        logger.info('No modules found on registered device "%s".', device_id)
    return result


def iot_device_module_show(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        module = m_sdk.module_api.get_module(device_id, module_id)
        module['hub'] = target.get('entity')
        return module
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_delete(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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

def iot_device_module_twin_show(client, device_id, hub_name, module_id, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        return m_sdk.device_twin_api.get_module_twin(device_id, module_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_module_twin_update(client, device_id, hub_name, module_id, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_module_twin_replace(client, device_id, hub_name, module_id, target_json, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = json.loads(target_json)
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

def iot_device_configuration_apply(client, device_id, hub_name, content, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
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
        return m_sdk.device_api.apply_configuration_content_on_device(device_id, content)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_create(client, config_id, hub_name, content, target_condition="", priority=0,
                                    labels=None, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
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
        return m_sdk.configuration_api.put_configuration(config_id, config)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_update(client, config_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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
    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        return m_sdk.configuration_api.get_configuration(config_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_device_configuration_list(client, hub_name, top=5, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_configuration_delete(client, config_id, hub_name, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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

def iot_device_twin_show(client, device_id, hub_name, resource_group_name=None):
    query = "SELECT * FROM devices where devices.deviceId='{}'".format(device_id)
    result = iot_query(client, hub_name, query, None, resource_group_name)
    if not result:
        raise CLIError('No registered device "{}" found.'.format(device_id))
    return result[0]


def iot_device_twin_update(client, device_id, hub_name, parameters, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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


def iot_device_twin_replace(client, device_id, hub_name, target_json, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    dt_sdk, errors = _bind_sdk(target, SdkType.device_twin_sdk)

    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = json.loads(target_json)
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

def iot_device_method(client, device_id, hub_name, method_name, method_payload, timeout=60, resource_group_name=None):
    from azext_iot.device_twin_sdk.models.cloud_to_device_method import CloudToDeviceMethod

    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    if timeout > 300:
        raise CLIError('timeout must not be over 300 seconds')
    if timeout < 10:
        raise CLIError('timeout must be at least 10 seconds')

    dt_sdk, errors = _bind_sdk(target, SdkType.device_twin_sdk)

    try:
        if exists(method_payload):
            method_payload = str(read_file_content(method_payload))
        method_payload = json.loads(method_payload)
        method = CloudToDeviceMethod(method_name, method_payload, timeout, timeout)
        return dt_sdk.invoke_device_method(device_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Device Module Method Invoke

def iot_device_module_method(client, device_id, hub_name, module_id, method_name, method_payload,
                             timeout=60, resource_group_name=None):
    from azext_iot.modules_sdk.models.cloud_to_device_method import CloudToDeviceMethod

    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    if timeout > 300:
        raise CLIError('timeout must not be over 300 seconds')
    if timeout < 10:
        raise CLIError('timeout must be at least 10 seconds')

    m_sdk, errors = _bind_sdk(target, SdkType.modules_sdk)
    try:
        if exists(method_payload):
            method_payload = str(read_file_content(method_payload))
        method_payload = json.loads(method_payload)
        method = CloudToDeviceMethod(method_name, method_payload, timeout, timeout)
        return m_sdk.module_api.invoke_device_module_method(device_id, module_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# Utility

def iot_get_sas_token(client, hub_name, device_id=None, policy_name='iothubowner',
                      key_type='primary', duration=3600, resource_group_name=None):
    return {'sas': _iot_build_sas_token(client, hub_name, device_id,
                                        policy_name, key_type, duration, resource_group_name).generate_sas_token()}


def _iot_build_sas_token(client, hub_name, device_id=None, policy_name='iothubowner',
                         key_type='primary', duration=3600, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name, policy_name)
    uri = '{0}/devices/{1}'.format(target['entity'], device_id) if device_id else target['entity']
    return SasTokenAuthentication(uri, target['policy'],
                                  target['primarykey'] if key_type == 'primary' else target['secondarykey'],
                                  time() + duration)


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
                else:
                    return template.format(device.get('hub'), device.get('deviceId'), key)
    raise CLIError('Unable to form target connection string')


def iot_get_hub_connection_string(client, hub_name, policy_name='iothubowner', key_type='primary',
                                  resource_group_name=None):
    result = {}
    result['cs'] = get_iot_hub_connection_string(client, hub_name, resource_group_name,
                                                 policy_name, key_type)['cs']
    return result


def iot_get_device_connection_string(client, hub_name, device_id, key_type='primary',
                                     resource_group_name=None):
    result = {}
    device = iot_device_show(client, device_id, hub_name, resource_group_name)
    result['cs'] = _build_device_or_module_connection_string(device, key_type)
    return result


def iot_get_module_connection_string(client, hub_name, device_id, module_id, key_type='primary',
                                     resource_group_name=None):
    result = {}
    module = iot_device_module_show(client, device_id, hub_name, module_id, resource_group_name)
    result['cs'] = _build_device_or_module_connection_string(None, key_type, module)
    return result


# Messaging

def iot_device_send_message(client, device_id, hub_name, data='Ping from Az CLI IoT Extension',
                            properties=None, msg_count=1, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return _iot_device_send_message(target, device_id, data, properties, msg_count)


def _iot_device_send_message(target, device_id, data, properties=None, msg_count=1):
    import paho.mqtt.publish as publish
    from paho.mqtt import client as mqtt
    import ssl
    import os

    try:
        from urllib import urlencode
    except ImportError:
        from urllib.parse import urlencode

    msgs = []
    if properties:
        properties = validate_key_value_pairs(properties)

    sas = SasTokenAuthentication(target['entity'], target['policy'], target['primarykey'], time() + 360).generate_sas_token()
    cwd = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(cwd, 'digicert.pem')
    auth = {'username': '{}/{}/api-version=2016-11-14'.format(target['entity'], device_id), 'password': sas}
    tls = {'ca_certs': cert_path, 'tls_version': ssl.PROTOCOL_SSLv23}
    topic = 'devices/{}/messages/events/{}'.format(device_id, urlencode(properties) if properties else '')
    for _ in range(msg_count):
        msgs.append({'topic': topic, 'payload': data})
    try:
        publish.multiple(msgs, client_id=device_id, hostname=target['entity'],
                         auth=auth, port=8883, protocol=mqtt.MQTTv311, tls=tls)
        return
    except Exception as x:
        raise CLIError(x)


def iot_c2d_message_complete(client, device_id, hub_name, etag, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return _iot_c2d_message_complete(target, device_id, etag)


def _iot_c2d_message_complete(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.complete_or_reject_message(device_id, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_reject(client, device_id, hub_name, etag, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return _iot_c2d_message_reject(target, device_id, etag)


def _iot_c2d_message_reject(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.complete_or_reject_message(device_id, etag, '')
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_abandon(client, device_id, hub_name, etag, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return _iot_c2d_message_abandon(target, device_id, etag)


def _iot_c2d_message_abandon(target, device_id, etag):
    msg_sdk, errors = _bind_sdk(target, SdkType.device_msg_sdk, device_id)
    try:
        return msg_sdk.iot_hub_devices.abandon_message(device_id, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_c2d_message_receive(client, device_id, hub_name, lock_timeout=60, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_simulate_device(client, device_id, hub_name, receive_settle='complete',
                        data='Ping from Az CLI IoT Extension', msg_count=2,
                        receive_count=None, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    sleep_interval = 3
    if msg_count < 0:
        raise CLIError("msg-count must be at least 0!")
    _iot_device_send_message(target, device_id, data, None, msg_count)

    if receive_count:
        if receive_count < -1:
            receive_count = 0

        if receive_count == -1:
            while True:
                _handle_c2d_msg(target, device_id, receive_settle)
                sleep(sleep_interval)
        else:
            received = 0
            while received < receive_count:
                if _handle_c2d_msg(target, device_id, receive_settle):
                    received += 1
                sleep(sleep_interval)


def _handle_c2d_msg(target, device_id, receive_settle):
    result = _iot_c2d_message_receive(target, device_id)
    if result:
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


def iot_device_export(client, hub_name, blob_container_uri, include_keys=False, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.export_devices(target['resourcegroup'], hub_name, blob_container_uri, not include_keys)


def iot_device_import(client, hub_name, input_blob_container_uri, output_blob_container_uri, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.import_devices(target['resourcegroup'], hub_name,
                                 input_blob_container_uri, output_blob_container_uri)


def iot_device_upload_file(client, device_id, hub_name, file_path, content_type, resource_group_name=None):
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
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

# DPS Enrollments
def iot_dps_device_enrollment_list(client, dps_name, resource_group_name, top=None):
    from azext_iot.dps_sdk.models.query_specification import QuerySpecification
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)    
    try: 
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk) 

        query_command = "SELECT *"
        query = QuerySpecification(query_command)     
        return _execute_query(client, query, m_sdk.device_enrollment.query, errors, top)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_get(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment.get(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_create(client, 
                                     enrollment_id, 
                                     attestation_type,
                                     dps_name, 
                                     resource_group_name,
                                     endorsement_key = None,
                                     certificate_path = None,
                                     device_id = None,
                                     iot_hub_host_name = None,
                                     initial_twin_tags = None,
                                     initial_twin_properties = None,
                                     provisioning_status = None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        
        if attestation_type == AttestationType.tpm.value: 
            if not endorsement_key:
                raise CLIError('Endorsement key is requried')
            tpm = TpmAttestation(endorsement_key)
            attestation = AttestationMechanism(AttestationType.tpm.value, tpm)
        if attestation_type == AttestationType.x509.value:
            attestation = _get_attestation_with_x509_client_cert(certificate_path)
         
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        enrollment = IndividualEnrollment(enrollment_id, 
                                          attestation, 
                                          device_id, 
                                          None, 
                                          iot_hub_host_name, 
                                          initial_twin,
                                          None,
                                          provisioning_status)
        
        return m_sdk.device_enrollment.create_or_update(enrollment_id, enrollment)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_update(client, 
                                     enrollment_id, 
                                     dps_name,                                    
                                     resource_group_name,
                                     etag,
                                     endorsement_key = None,
                                     certificate_path = None,
                                     device_id = None,
                                     iot_hub_host_name = None,
                                     initial_twin_tags = None,
                                     initial_twin_properties = None,
                                     provisioning_status = None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
           
        enrollment_record = m_sdk.device_enrollment.get(enrollment_id)
        if not 'etag' in enrollment_record:
            raise LookupError("enrollment etag not found.") 
        if etag != enrollment_record['etag'].replace('"', ''):
            raise LookupError("enrollment etag doesn't match.")

        attestation_type = enrollment_record['attestation']['type']
        
        if attestation_type == AttestationType.tpm.value:
            if certificate_path:
                raise CLIError('Cannot update certificate while enrollment is using tpm attestation mechanism')
            if endorsement_key:
                enrollment_record['attestation']['tpm']['endorsement_key'] = endorsement_key
        else:
            if endorsement_key:
                raise CLIError('Cannot update endorsement key while enrollment is using x509 attestation mechanism')
            enrollment_record['attestation'] = _get_attestation_with_x509_client_cert(certificate_path)

        enrollment_record['initialTwin'] = _get_updated_inital_twin(enrollment_record, 
                                                                  initial_twin_tags, 
                                                                  initial_twin_properties)

        if iot_hub_host_name:
            enrollment_record['iotHubHostName'] = iot_hub_host_name
        if device_id:
            enrollment_record['deviceId'] = device_id
        if provisioning_status:
            enrollment_record['provisioningStatus'] = provisioning_status
        enrollment_record['registrationState'] = None 
        
        return m_sdk.device_enrollment.create_or_update(enrollment_id, enrollment_record, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_delete(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment.delete(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

# DPS Enrollments Group

def iot_dps_device_enrollment_group_list(client, dps_name, resource_group_name, top=None):
    from azext_iot.dps_sdk.models.query_specification import QuerySpecification
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        
        query_command = "SELECT *"
        query = QuerySpecification(query_command) 
        return _execute_query(client, query, m_sdk.device_enrollment_group.query, errors, top)    
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_get(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment_group.get(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_group_create(client, 
                                     enrollment_id, 
                                     dps_name, 
                                     resource_group_name,
                                     certificate_path,
                                     iot_hub_host_name = None,
                                     initial_twin_tags = None,
                                     initial_twin_properties = None,
                                     provisioning_status = None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        
        attestation = _get_attestation_with_x509_signing_cert(certificate_path)          
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)       
        group_enrollment = EnrollmentGroup(enrollment_id, 
                                     attestation, 
                                     iot_hub_host_name, 
                                     initial_twin,
                                     None,
                                     provisioning_status)
        
        return m_sdk.device_enrollment_group.create_or_update(enrollment_id, group_enrollment)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_group_update(client, 
                                     enrollment_id, 
                                     dps_name, 
                                     resource_group_name,
                                     etag,
                                     certificate_path,
                                     iot_hub_host_name = None,
                                     initial_twin_tags = None,
                                     initial_twin_properties = None,
                                     provisioning_status = None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        
        enrollment_record = m_sdk.device_enrollment_group.get(enrollment_id)
        if not 'etag' in enrollment_record:
            raise LookupError("enrollment etag not found.") 
        if etag != enrollment_record['etag'].replace('"', ''):
            raise LookupError("enrollment etag doesn't match.")


        if iot_hub_host_name:
            enrollment_record['iotHubHostName'] = iot_hub_host_name
        if provisioning_status:
            enrollment_record['provisioningStatus'] = provisioning_status
 
        enrollment_record['initialTwin'] = _get_updated_inital_twin(enrollment_record, 
                                                                  initial_twin_tags, 
                                                                  initial_twin_properties)
        
        enrollment_record['attestation'] = _get_attestation_with_x509_signing_cert(certificate_path)
        
        return m_sdk.device_enrollment_group.create_or_update(enrollment_id, enrollment_record, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_device_enrollment_group_delete(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment_group.delete(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

# DPS Registration
def iot_dps_registration_list(client, dps_name, resource_group_name, enrollment_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.query_registration_state(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_registration_get(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.get_registration_state(registration_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def iot_dps_registration_delete(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.delete_registration_state(registration_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)

def _get_initial_twin(initial_twin_tags = None, initial_twin_properties = None):
    if not initial_twin_tags and not initial_twin_properties:
        return None
    if initial_twin_tags:
        initial_twin_tags = evaluate_literal(str(initial_twin_tags), dict)
    if initial_twin_properties:
        initial_twin_properties = evaluate_literal(str(initial_twin_properties), dict)
    return InitialTwin(TwinCollection(initial_twin_tags), 
                       InitialTwinProperties(TwinCollection(initial_twin_properties)))

def _get_updated_inital_twin(enrollment_record, initial_twin_tags = None, initial_twin_properties = None):
    if not initial_twin_tags:
        initial_twin_tags = enrollment_record['initialTwin']['tags']
    if not initial_twin_properties:
        initial_twin_properties = enrollment_record['initialTwin']['properties']['desired']    
    return _get_initial_twin(initial_twin_tags, initial_twin_properties) 

def _get_x509_certificate(certificate_path):
    if not certificate_path:
        raise CLIError('Certificate path is requried')

    certificate_content = open_certificate(certificate_path)
    certificate_with_info = X509CertificateWithInfo(certificate_content)
    x509certificate = X509Certificates(certificate_with_info)
    
    return x509certificate

def _get_attestation_with_x509_client_cert(certificate_path):
    if not certificate_path:
        raise CLIError('Certificate path is required')
    certificate = _get_x509_certificate(certificate_path)
    x509Attestation = X509Attestation(certificate)
    attestation = AttestationMechanism(AttestationType.x509.value, None, x509Attestation)

    return attestation

def _get_attestation_with_x509_signing_cert(certificate_path):
    if not certificate_path:
        raise CLIError('Certificate path is required')
    certificate = _get_x509_certificate(certificate_path)
    x509Attestation = X509Attestation(None, certificate)
    attestation = AttestationMechanism(AttestationType.x509.value, None, x509Attestation)

    return attestation

def _execute_query(client, query, query_method, errors, top=None):
    payload = []
    headers = {}

    # Consider top == 0
    if top is not None:
        if top <= 0:
            raise CLIError('top must be > 0')

    try:


        if top:
            headers['x-ms-max-item-count'] = str(top)
        result, token = query_method(query, headers)
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
            result, token = query_method(query, headers)
            payload.extend(result)
        return payload[:top] if top else payload
    except errors.ErrorDetailsException as e:
        raise CLIError(e) 