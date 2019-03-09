# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=wrong-import-order,too-many-lines

from os.path import exists, basename
from time import time, sleep
import six
from knack.log import get_logger
from knack.util import CLIError
from azure.cli.core.util import read_file_content
from azext_iot.common.utility import calculate_millisec_since_unix_epoch_utc
from azext_iot._constants import EXTENSION_ROOT, BASE_API_VERSION, DEVICE_DEVICESCOPE_PREFIX
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import (DeviceAuthType,
                                     SdkType,
                                     MetricType)
from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot.common.utility import (shell_safe_json_parse,
                                      validate_key_value_pairs, url_encode_dict,
                                      evaluate_literal, unpack_msrest_error)
from azext_iot._factory import _bind_sdk
from azext_iot.operations.generic import _execute_query, _process_top


logger = get_logger(__name__)


# Query

def iot_query(cmd, query_command, hub_name=None, top=None, resource_group_name=None, login=None):
    top = _process_top(top)

    from azext_iot.service_sdk.models import QuerySpecification

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        query = QuerySpecification(query_command)
        query_method = service_sdk.query_iot_hub

        return _execute_query(query, query_method, top)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device

def iot_device_show(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_device_show(target, device_id)


def _iot_device_show(target, device_id):
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        device = service_sdk.get_device(device_id)
        device['hub'] = target.get('entity')
        return device
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_list(cmd, hub_name=None, top=1000, edge_enabled=False, resource_group_name=None, login=None):
    query = 'select * from devices where capabilities.iotEdge = true' if edge_enabled else 'select * from devices'
    result = iot_query(cmd, query, hub_name, top, resource_group_name, login=login)
    if not result:
        logger.info('No registered devices found on hub "%s".', hub_name)
    return result


# pylint: disable=too-many-locals
def iot_device_create(cmd, device_id, hub_name=None, edge_enabled=False,
                      auth_method='shared_private_key', primary_thumbprint=None,
                      secondary_thumbprint=None, status='enabled', status_reason=None,
                      valid_days=None, output_dir=None, set_parent_id=None, add_children=None,
                      force=False, resource_group_name=None, login=None):

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    deviceScope = None
    if edge_enabled:
        if auth_method != DeviceAuthType.shared_private_key.name:
            raise CLIError('currently edge devices are limited to symmetric key auth')
        if add_children:
            for non_edge_device_id in add_children.split(','):
                nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
                _validate_nonedge_device(nonedge_device)
                _validate_parent_child_relation(nonedge_device, '-', force)
    else:
        if set_parent_id:
            edge_device = _iot_device_show(target, set_parent_id)
            _validate_edge_device(edge_device)
            deviceScope = edge_device['deviceScope']

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise CLIError('certificate output directory of "{}" does not exist.')
        cert = _create_self_signed_cert(device_id, valid_days, output_dir)
        primary_thumbprint = cert['thumbprint']

    try:
        device = _assemble_device(device_id, auth_method, edge_enabled, primary_thumbprint,
                                  secondary_thumbprint, status, status_reason, deviceScope)
        output = service_sdk.create_or_update_device(device_id, device)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))

    if add_children:
        for non_edge_device_id in add_children.split(','):
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            _update_nonedge_devicescope(target, nonedge_device, output.device_scope)

    return output


def _assemble_device(device_id, auth_method, edge_enabled, pk=None, sk=None,
                     status='enabled', status_reason=None, device_scope=None):
    from azext_iot.service_sdk.models.device_capabilities import DeviceCapabilities
    from azext_iot.service_sdk.models.device import Device

    auth = _assemble_auth(auth_method, pk, sk)
    cap = DeviceCapabilities(edge_enabled)
    device = Device(device_id=device_id, authentication=auth,
                    capabilities=cap, status=status, status_reason=status_reason,
                    device_scope=device_scope)
    return device


def _assemble_auth(auth_method, pk, sk):
    from azext_iot.service_sdk.models.authentication_mechanism import AuthenticationMechanism
    from azext_iot.service_sdk.models.symmetric_key import SymmetricKey
    from azext_iot.service_sdk.models.x509_thumbprint import X509Thumbprint

    auth = None
    if auth_method in [DeviceAuthType.shared_private_key.name, 'sas']:
        auth = AuthenticationMechanism(
            symmetric_key=SymmetricKey(pk, sk), type='sas')
    elif auth_method in [DeviceAuthType.x509_thumbprint.name, 'selfSigned']:
        if not pk:
            raise ValueError('primary thumbprint required with selfSigned auth')
        auth = AuthenticationMechanism(x509_thumbprint=X509Thumbprint(
            pk, sk), type='selfSigned')
    elif auth_method in [DeviceAuthType.x509_ca.name, 'certificateAuthority']:
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
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        updated_device = _handle_device_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.create_or_update_device(device_id, updated_device, custom_headers=headers)
        raise LookupError("device etag not found.")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _handle_device_update_params(parameters):
    status = parameters['status'].lower()
    possible_status = ['enabled', 'disabled']
    if status not in possible_status:
        raise ValueError("status must be one of {}".format(possible_status))

    edge = parameters.get('capabilities').get('iotEdge')
    if not isinstance(edge, bool):
        raise ValueError("capabilities.iotEdge is of type bool")

    auth, pk, sk = _parse_auth(parameters)
    return _assemble_device(parameters['deviceId'], auth, edge, pk, sk, status, parameters.get('statusReason'))


def iot_device_delete(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        device = service_sdk.get_device(device_id)
        etag = device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.delete_device(device_id, custom_headers=headers)
            return
        raise LookupError("device etag not found")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_get_parent(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    child_device = _iot_device_show(target, device_id)
    _validate_nonedge_device(child_device)
    _validate_child_device(child_device)
    device_scope = child_device['deviceScope']
    parent_device_id = device_scope[len(DEVICE_DEVICESCOPE_PREFIX):device_scope.rindex('-')]
    return _iot_device_show(target, parent_device_id)


def iot_device_set_parent(cmd, device_id, parent_id, force=False, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    parent_device = _iot_device_show(target, parent_id)
    _validate_edge_device(parent_device)
    child_device = _iot_device_show(target, device_id)
    _validate_nonedge_device(child_device)
    _validate_parent_child_relation(child_device, parent_device['deviceScope'], force)
    _update_nonedge_devicescope(target, child_device, parent_device['deviceScope'])


def iot_device_children_add(cmd, device_id, child_list, force=False, hub_name=None,
                            resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    devices = []
    edge_device = _iot_device_show(target, device_id)
    _validate_edge_device(edge_device)
    for non_edge_device_id in child_list.split(','):
        nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
        _validate_nonedge_device(nonedge_device)
        _validate_parent_child_relation(nonedge_device, edge_device['deviceScope'], force)
        devices.append(nonedge_device)

    for device in devices:
        _update_nonedge_devicescope(target, device, edge_device['deviceScope'])


def iot_device_children_remove(cmd, device_id, child_list=None, remove_all=False, hub_name=None,
                               resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    devices = []
    if remove_all:
        result = _iot_device_children_list(cmd, device_id, hub_name, resource_group_name, login)
        if not result:
            raise CLIError('No registered child devices found for "{}" edge device.'.format(device_id))
        for non_edge_device_id in ([str(x['deviceId']) for x in result]):
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            devices.append(nonedge_device)
    elif child_list:
        edge_device = _iot_device_show(target, device_id)
        _validate_edge_device(edge_device)
        for non_edge_device_id in child_list.split(','):
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            _validate_nonedge_device(nonedge_device)
            _validate_child_device(nonedge_device)
            if nonedge_device['deviceScope'] == edge_device['deviceScope']:
                devices.append(nonedge_device)
            else:
                raise CLIError('The entered child device "{}" isn\'t assigned as a child of edge device "{}"'
                               .format(non_edge_device_id.strip(), device_id))
    else:
        raise CLIError('Please specify comma-separated child list or use --remove-all to remove all children.')

    for device in devices:
        _update_nonedge_devicescope(target, device)


def iot_device_children_list(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    result = _iot_device_children_list(cmd, device_id, hub_name, resource_group_name, login)
    if not result:
        raise CLIError('No registered child devices found for "{}" edge device.'.format(device_id))
    return ', '.join([str(x['deviceId']) for x in result])


def _iot_device_children_list(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    device = _iot_device_show(target, device_id)
    _validate_edge_device(device)
    query = ('select * from devices where capabilities.iotEdge=false and deviceScope=\'{}\''
             .format(device['deviceScope']))
    return iot_query(cmd, query, hub_name, None, resource_group_name, login=login)


def _update_nonedge_devicescope(target, nonedge_device, deviceScope=''):
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        nonedge_device['deviceScope'] = deviceScope
        etag = nonedge_device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.create_or_update_device(nonedge_device['deviceId'], nonedge_device, custom_headers=headers)
        else:
            raise LookupError("device etag not found.")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _validate_edge_device(device):
    if not device['capabilities']['iotEdge']:
        raise CLIError('The device "{}" should be edge device.'.format(device['deviceId']))


def _validate_nonedge_device(device):
    if device['capabilities']['iotEdge']:
        raise CLIError('The entered child device "{}" should be non-edge device.'.format(device['deviceId']))


def _validate_child_device(device):
    if 'deviceScope' not in device or device['deviceScope'] == '':
        raise CLIError('Device "{}" doesn\'t support parent device functionality.'.format(device['deviceId']))


def _validate_parent_child_relation(child_device, deviceScope, force):
    if 'deviceScope' not in child_device or child_device['deviceScope'] == '':
        return
    if child_device['deviceScope'] != deviceScope:
        if not force:
            raise CLIError('The entered device "{}" already has a parent device, please use \'--force\''
                           ' to overwrite'.format(child_device['deviceId']))
        return


# Module

def iot_device_module_create(cmd, device_id, module_id, hub_name=None, auth_method='shared_private_key',
                             primary_thumbprint=None, secondary_thumbprint=None, valid_days=None,
                             output_dir=None, resource_group_name=None, login=None):

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise CLIError('certificate output directory of "{}" does not exist.')
        cert = _create_self_signed_cert(module_id, valid_days, output_dir)
        primary_thumbprint = cert['thumbprint']

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        module = _assemble_module(device_id, module_id, auth_method, primary_thumbprint, secondary_thumbprint)
        return service_sdk.create_or_update_module(device_id, module_id, module)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _assemble_module(device_id, module_id, auth_method, pk=None, sk=None):
    from azext_iot.service_sdk.models.module import Module

    auth = _assemble_auth(auth_method, pk, sk)
    module = Module(module_id=module_id, device_id=device_id, authentication=auth)
    return module


def iot_device_module_update(cmd, device_id, module_id, parameters,
                             hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        updated_module = _handle_module_update_params(parameters)
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.create_or_update_module(device_id, module_id, updated_module, custom_headers=headers)
        raise LookupError("module etag not found.")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


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


def iot_device_module_list(cmd, device_id, hub_name=None, top=1000, resource_group_name=None, login=None):
    query = "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
    result = iot_query(cmd, query, hub_name, top, resource_group_name, login=login)
    if not result:
        logger.info('No modules found on registered device "%s".', device_id)
    return result


def iot_device_module_show(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_device_module_show(target, device_id, module_id)


def _iot_device_module_show(target, device_id, module_id):
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        module = service_sdk.get_module(device_id, module_id)
        module['hub'] = target.get('entity')
        return module
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_module_delete(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        module = service_sdk.get_module(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.delete_module(device_id, module_id, custom_headers=headers)
            return
        raise LookupError("module etag not found")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Module Twin

def iot_device_module_twin_show(cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        return service_sdk.get_module_twin(device_id, module_id)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_module_twin_update(cmd, device_id, module_id, parameters, hub_name=None, resource_group_name=None, login=None):
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            verify = {'properties.desired': dict}
            if parameters.get('tags', None):
                verify['tags'] = dict
            verify_transform(parameters, verify)
            return service_sdk.update_module_twin(device_id, module_id, parameters, custom_headers=headers)
        raise LookupError("module twin etag not found")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except AttributeError as att_err:
        raise CLIError(att_err)
    except TypeError as val_err:
        raise CLIError(val_err)


def iot_device_module_twin_replace(cmd, device_id, module_id, target_json, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = shell_safe_json_parse(target_json)
        module = service_sdk.get_module_twin(device_id, module_id)
        etag = module.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.replace_module_twin(device_id, module_id, target_json, custom_headers=headers)
        raise LookupError("module twin etag not found")
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Configuration

def iot_edge_set_modules(cmd, device_id, content, hub_name=None, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models.configuration_content import ConfigurationContent

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        if exists(content):
            content = str(read_file_content(content))
        content = shell_safe_json_parse(content)
        modules_content = _process_config_content(content)

        content = ConfigurationContent(modules_content=modules_content)
        service_sdk.apply_configuration_on_device(device_id, content)
        return iot_device_module_list(cmd, device_id, hub_name=hub_name, top=-1, login=login)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_edge_deployment_create(cmd, config_id, content, hub_name=None, target_condition="", priority=0,
                               labels=None, resource_group_name=None, login=None):
    return _iot_hub_configuration_create(cmd=cmd, config_id=config_id, content=content, hub_name=hub_name,
                                         target_condition=target_condition, priority=priority,
                                         labels=labels, resource_group_name=resource_group_name,
                                         login=login, edge=True)


def iot_hub_configuration_create(cmd, config_id, content, hub_name=None, target_condition="", priority=0,
                                 labels=None, metrics=None, resource_group_name=None, login=None):
    return _iot_hub_configuration_create(cmd=cmd, config_id=config_id, content=content, hub_name=hub_name,
                                         target_condition=target_condition, priority=priority,
                                         labels=labels, metrics=metrics, resource_group_name=resource_group_name,
                                         login=login)


def _iot_hub_configuration_create(cmd, config_id, content, hub_name=None, target_condition="", priority=0,
                                  labels=None, metrics=None, edge=False, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models.configuration import Configuration
    from azext_iot.service_sdk.models.configuration_content import ConfigurationContent
    from azext_iot.service_sdk.models.configuration_metrics import ConfigurationMetrics

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    metrics_key = 'queries'

    try:
        json_from_file = None

        if exists(content):
            json_from_file = content
            content = str(read_file_content(content))
        try:
            content = shell_safe_json_parse(content)
        except ValueError as j:
            raise CLIError("improperly formatted json argument 'content'{}: {}".format(
                '(in file {})'.format(json_from_file) if json_from_file else '', j))

        content = _process_config_content(content, 'module' if edge else 'device')

        if metrics:
            json_from_file = None
            if exists(metrics):
                json_from_file = metrics
                metrics = str(read_file_content(metrics))
            try:
                metrics = shell_safe_json_parse(metrics)
            except ValueError as j:
                raise CLIError("improperly formatted json argument 'metrics'{}: {}".format(
                    '(in file {})'.format(json_from_file) if json_from_file else '', j))

            if 'metrics' in metrics:
                metrics = metrics['metrics']
            if metrics_key not in metrics:
                raise CLIError("metrics json must include the '{}' property".format(metrics_key))
            metrics = metrics[metrics_key]

        if labels:
            try:
                labels = shell_safe_json_parse(labels)
            except ValueError as j:
                raise CLIError("improperly formatted json argument 'labels': {}".format(j))

        if edge:
            config_content = ConfigurationContent(modules_content=content)
        else:
            config_content = ConfigurationContent(device_content=content)

        config_metrics = ConfigurationMetrics(queries=metrics)
        config = Configuration(id=config_id,
                               schema_version='2.0',
                               labels=labels,
                               content=config_content,
                               metrics=config_metrics,
                               target_condition=target_condition,
                               etag=None,
                               priority=priority,
                               content_type='assignment')
        return service_sdk.create_or_update_configuration(config_id, config)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _process_config_content(content, content_type='module'):
    content_key = 'modulesContent' if 'module' in content_type else 'deviceContent'
    legacy_key = 'moduleContent'

    if 'content' in content:
        content = content['content']

    if content_key in content:
        content = content[content_key]
    elif 'module' in content_type and legacy_key in content:
        logger.warning("'%s' is deprecated use '%s' instead - request is still processing...", legacy_key, content_key)
        content = content[legacy_key]
    else:
        raise CLIError("content json must include the '{}' property".format(content_key))

    return content


def iot_hub_configuration_update(cmd, config_id, parameters, hub_name=None, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models.configuration import Configuration
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        etag = parameters.get('etag', None)
        if not etag:
            raise LookupError("invalid request, configuration etag not found")
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag)
        verify = {'metrics': dict, 'metrics.queries': dict, 'content': dict}
        if parameters.get('labels', None):
            verify['labels'] = dict
        verify_transform(parameters, verify)
        config = Configuration(id=parameters['id'],
                               schema_version=parameters['schemaVersion'],
                               labels=parameters['labels'],
                               content=parameters['content'],
                               metrics=parameters.get('metrics', None),
                               target_condition=parameters['targetCondition'],
                               priority=parameters['priority'],
                               content_type='assignment')
        return service_sdk.create_or_update_configuration(config_id, config, custom_headers=headers)
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except AttributeError as att_err:
        raise CLIError(att_err)
    except TypeError as val_err:
        raise CLIError(val_err)


def _handle_configuration_update_params(parameters):
    labels = parameters.get('labels', None)
    if labels:
        if not isinstance(labels, dict):
            labels = evaluate_literal(labels, dict)
            if not labels:
                raise ValueError('labels are malformed, expecting dictionary')
            parameters['labels'] = labels

    return parameters


def iot_hub_configuration_show(cmd, config_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        return service_sdk.get_configuration(config_id)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_hub_configuration_list(cmd, hub_name=None, top=10, resource_group_name=None, login=None):
    result = _iot_hub_configuration_list(cmd, hub_name=hub_name, top=top,
                                         resource_group_name=resource_group_name, login=login)
    filtered = [c for c in result if c['content'].get('deviceContent')]
    return filtered[:top]


def iot_edge_deployment_list(cmd, hub_name=None, top=10, resource_group_name=None, login=None):
    result = _iot_hub_configuration_list(cmd, hub_name=hub_name, top=top,
                                         resource_group_name=resource_group_name, login=login)

    filtered = [c for c in result if (c['content'].get('modulesContent') or c['content'].get('moduleContent'))]
    return filtered[:top]


def _iot_hub_configuration_list(cmd, hub_name=None, top=10, resource_group_name=None, login=None):
    top = _process_top(top, upper_limit=20)

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        result = service_sdk.get_configurations(top)
        if not result:
            logger.info('No configurations found on hub "%s".', hub_name)
        return result
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_hub_configuration_delete(cmd, config_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        config = service_sdk.get_configuration(config_id)
        etag = config.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.delete_configuration(config_id, custom_headers=headers)
            return
        raise LookupError("configuration etag not found")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_edge_deployment_metric_show(cmd, config_id, metric_id,
                                    hub_name=None, resource_group_name=None, login=None):
    return iot_hub_configuration_metric_show(cmd, config_id=config_id, metric_id=metric_id,
                                             metric_type='system', hub_name=hub_name,
                                             resource_group_name=resource_group_name, login=login)


def iot_hub_configuration_metric_show(cmd, config_id, metric_id, metric_type='user',
                                      hub_name=None, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models import QuerySpecification
    from azext_iot.common.utility import dict_transform_lower_case_key

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        config = service_sdk.get_configuration(config_id)

        metric_collection = None
        if metric_type == 'system':
            metric_collection = config.get('systemMetrics').get('queries')
        else:
            metric_collection = config.get('metrics').get('queries')

        if metric_id not in metric_collection:
            raise CLIError("the metric '{}' is not defined in the device configuration '{}'".format(metric_id, config_id))

        metric_query = metric_collection[metric_id]

        query = QuerySpecification(metric_query)
        query_method = service_sdk.query_iot_hub

        metric_result = _execute_query(query, query_method, None)

        # 'Flattens' system metrics by putting device Id's in a single list
        if metric_type == MetricType.system.name:
            flat_result = []
            for r in metric_result:
                r = dict_transform_lower_case_key(r)
                if 'deviceid' in r:
                    flat_result.append(r['deviceid'])
            if flat_result:
                metric_result = flat_result

        output = {}
        output['metric'] = metric_id
        output['query'] = metric_query
        output['result'] = metric_result

        return output
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device Twin

def iot_device_twin_show(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    query = "select * from devices where devices.deviceId='{}'".format(device_id)
    result = iot_query(cmd, query, hub_name, None, resource_group_name, login=login)
    if not result:
        raise CLIError('No registered device "{}" found.'.format(device_id))
    return result[0]


def iot_device_twin_update(cmd, device_id, parameters, hub_name=None, resource_group_name=None, login=None):
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        etag = parameters.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            verify = {'properties.desired': dict}
            if parameters.get('tags', None):
                verify['tags'] = dict
            verify_transform(parameters, verify)
            return service_sdk.update_twin(device_id, parameters, custom_headers=headers)
        raise LookupError("device twin etag not found")
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except AttributeError as att_err:
        raise CLIError(att_err)
    except TypeError as val_err:
        raise CLIError(val_err)


def iot_device_twin_replace(cmd, device_id, target_json, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        if exists(target_json):
            target_json = str(read_file_content(target_json))
        target_json = shell_safe_json_parse(target_json)
        device = service_sdk.get_twin(device_id)
        etag = device.get('etag', None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.replace_twin(device_id, target_json, custom_headers=headers)
        raise LookupError("device twin etag not found")
    except ValueError as j:
        raise CLIError('improperly formatted json: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device Method Invoke

def iot_device_method(cmd, device_id, method_name, hub_name=None, method_payload="{}",
                      timeout=60, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot._constants import METHOD_INVOKE_MAX_TIMEOUT_SEC, METHOD_INVOKE_MIN_TIMEOUT_SEC

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MAX_TIMEOUT_SEC))
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError('timeout must be at least {} seconds'.format(METHOD_INVOKE_MIN_TIMEOUT_SEC))

    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        if method_payload:
            if exists(method_payload):
                method_payload = str(read_file_content(method_payload))
            method_payload = shell_safe_json_parse(method_payload)

        method = CloudToDeviceMethod(method_name, timeout, timeout, method_payload)

        return service_sdk.invoke_device_method(device_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device Module Method Invoke

def iot_device_module_method(cmd, device_id, module_id, method_name, hub_name=None, method_payload="{}",
                             timeout=60, resource_group_name=None, login=None):
    from azext_iot.service_sdk.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot._constants import METHOD_INVOKE_MAX_TIMEOUT_SEC, METHOD_INVOKE_MIN_TIMEOUT_SEC

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MAX_TIMEOUT_SEC))
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError('timeout must not be over {} seconds'.format(METHOD_INVOKE_MIN_TIMEOUT_SEC))

    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        if method_payload:
            if exists(method_payload):
                method_payload = str(read_file_content(method_payload))
            method_payload = shell_safe_json_parse(method_payload)

        method = CloudToDeviceMethod(method_name, timeout, timeout)
        method.payload = method_payload
        return service_sdk.invoke_device_method1(device_id, module_id, method)
    except ValueError as j:
        raise CLIError('method_payload json malformed: {}'.format(j))
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Utility

def iot_get_sas_token(cmd, hub_name=None, device_id=None, policy_name='iothubowner', key_type='primary',
                      duration=3600, resource_group_name=None, login=None, module_id=None):
    key_type = key_type.lower()
    policy_name = policy_name.lower()

    if login and policy_name != 'iothubowner':
        raise CLIError('You are unable to change the sas policy with a hub connection string login.')
    if login and key_type != 'primary' and not device_id:
        raise CLIError('For non-device sas, you are unable to change the key type with a connection string login.')
    if module_id and not device_id:
        raise CLIError('You are unable to get sas token for module without device information.')

    return {'sas': _iot_build_sas_token(cmd, hub_name, device_id, module_id,
                                        policy_name, key_type, duration, resource_group_name, login).generate_sas_token()}


def _iot_build_sas_token(cmd, hub_name=None, device_id=None, module_id=None, policy_name='iothubowner',
                         key_type='primary', duration=3600, resource_group_name=None, login=None):
    from azext_iot.common._azure import (parse_iot_device_connection_string,
                                         parse_iot_device_module_connection_string)

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, policy_name, login=login)
    uri = None
    policy = None
    key = None
    if device_id:
        logger.info('Obtaining device "%s" details from registry, using IoT Hub policy "%s"', device_id, policy_name)
        device = _iot_device_show(target, device_id)
        if module_id:
            module = _iot_device_module_show(target, device_id, module_id)
            module_cs = _build_device_or_module_connection_string(device=device, key_type=key_type, module=module)
            uri = '{}/devices/{}/modules/{}'.format(target['entity'], device_id, module_id)
            try:
                parsed_module_cs = parse_iot_device_module_connection_string(module_cs)
            except ValueError as e:
                logger.debug(e)
                raise CLIError('This module does not support SAS auth.')

            key = parsed_module_cs['SharedAccessKey']
        else:
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
            elif auth_type in ['certificateauthority', 'selfsigned']:
                key = 'x509=true'
            if key:
                if module:
                    return template.format(module.get('hub'), module.get('deviceId'), module.get('moduleId'), key)
                return template.format(device.get('hub'), device.get('deviceId'), key)
    raise CLIError('Unable to form target connection string')


# Introducing breaking changes by removing this command as same command exist in core-cli.
# Only removing the command and keeping command definition for further references.
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
    result['connectionString'] = _build_device_or_module_connection_string(device, key_type)
    return result


def iot_get_module_connection_string(cmd, device_id, module_id, hub_name=None, key_type='primary',
                                     resource_group_name=None, login=None):
    result = {}
    module = iot_device_module_show(cmd, device_id, module_id,
                                    resource_group_name=resource_group_name, hub_name=hub_name, login=login)
    result['connectionString'] = _build_device_or_module_connection_string(None, key_type, module)
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
    auth = {'username': '{}/{}/api-version={}'.format(target['entity'], device_id, BASE_API_VERSION), 'password': sas}
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
    device_sdk, errors = _bind_sdk(target, SdkType.device_sdk, device_id)

    headers = {}

    if msg_id:
        headers['IotHub-MessageId'] = msg_id
    if corr_id:
        headers['IotHub-CorrelationId'] = corr_id
    if user_id:
        headers['IotHub-UserId'] = user_id

    try:
        return device_sdk.send_device_event(device_id, data, custom_headers=headers)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_complete(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_complete(target, device_id, etag)


def _iot_c2d_message_complete(target, device_id, etag):
    device_sdk, errors = _bind_sdk(target, SdkType.device_sdk, device_id)
    try:
        return device_sdk.complete_or_reject_device_bound_notification(device_id, etag)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_reject(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_reject(target, device_id, etag)


def _iot_c2d_message_reject(target, device_id, etag):
    device_sdk, errors = _bind_sdk(target, SdkType.device_sdk, device_id)
    try:
        return device_sdk.complete_or_reject_device_bound_notification(device_id, etag, '')
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_abandon(cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_abandon(target, device_id, etag)


def _iot_c2d_message_abandon(target, device_id, etag):
    device_sdk, errors = _bind_sdk(target, SdkType.device_sdk, device_id)
    try:
        return device_sdk.abandon_device_bound_notification(device_id, etag)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_receive(cmd, device_id, hub_name=None, lock_timeout=60, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_receive(target, device_id, lock_timeout)


def _iot_c2d_message_receive(target, device_id, lock_timeout=60):
    device_sdk, errors = _bind_sdk(target, SdkType.device_sdk, device_id)
    request_headers = {}
    if lock_timeout:
        request_headers['IotHub-MessageLockTimeout'] = str(lock_timeout)

    try:
        result = device_sdk.receive_device_bound_notification(device_id, custom_headers=request_headers)
        if result and result.status_code == 200:
            payload = {
                'ack': result.headers.get('iothub-ack'),
                'correlationId': result.headers.get('iothub-correlationid'),
                'data': result.text,
                'deliveryCount': result.headers.get('iothub-deliverycount'),
                'enqueuedTime': result.headers.get('iothub-enqueuedtime'),
                'expiry': result.headers.get('iothub-expiry'),
                'etag': result.headers.get('ETag'),
                'messageId': result.headers.get('iothub-messageid'),
                'sequenceNumber': result.headers.get('iothub-sequencenumber'),
                'to': result.headers.get('iothub-to'),
                'userId': result.headers.get('iothub-userid')
            }
            if payload.get('etag'):
                payload['etag'] = payload['etag'].strip('"')
            return payload
        return
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_send(cmd, device_id, hub_name=None, data='Ping from Az CLI IoT Extension',
                         properties=None, correlation_id=None, ack=None, wait_on_feedback=False,
                         yes=False, repair=False, resource_group_name=None, login=None):
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 4)

    if wait_on_feedback and not ack:
        raise CLIError('To wait on device feedback, ack must be "full", "negative" or "positive"')

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    return _iot_c2d_message_send(target=target, device_id=device_id, data=data, properties=properties,
                                 correlation_id=correlation_id, ack=ack, wait=wait_on_feedback)


def _iot_c2d_message_send(target, device_id, data, properties=None,
                          correlation_id=None, ack=None, wait=None):
    import importlib

    if properties:
        properties = validate_key_value_pairs(properties)

    events3 = importlib.import_module('azext_iot.operations.events3._events')
    msg_id, errors = events3.send_c2d_message(target=target, device_id=device_id, data=data,
                                              properties=properties, correlation_id=correlation_id, ack=ack)
    if errors:
        raise CLIError('Error: {}, use --debug for more details.'.format(errors))

    if wait:
        _iot_hub_monitor_feedback(target=target, device_id=device_id, wait_on_id=msg_id)


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
def iot_hub_monitor_events(cmd, hub_name=None, device_id=None, consumer_group='$Default', timeout=300,
                           enqueued_time=None, resource_group_name=None, yes=False, properties=None, repair=False,
                           login=None, content_type=None, device_query=None):
    import importlib
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 5)

    if timeout < 0:
        raise CLIError('Monitoring timeout must be 0 (inf) or greater.')
    timeout = (timeout * 1000)

    config = cmd.cli_ctx.config
    output = cmd.cli_ctx.invocation.data.get("output", None)
    if not output:
        output = 'json'
    ensure_uamqp(config, yes, repair)

    events3 = importlib.import_module('azext_iot.operations.events3._events')

    if not properties:
        properties = []
    properties = set((key.lower() for key in properties))

    if not enqueued_time:
        enqueued_time = calculate_millisec_since_unix_epoch_utc()

    device_ids = {}
    if device_query:
        devices_result = iot_query(cmd, device_query, hub_name, None, resource_group_name, login=login)
        if devices_result:
            for device_result in devices_result:
                device_ids[device_result['deviceId']] = True

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, include_events=True, login=login)
    events3.executor(target,
                     consumer_group=consumer_group,
                     enqueued_time=enqueued_time,
                     properties=properties,
                     timeout=timeout,
                     device_id=device_id,
                     output=output,
                     content_type=content_type,
                     devices=device_ids)


def iot_hub_monitor_feedback(cmd, hub_name=None, device_id=None, yes=False,
                             wait_on_id=None, repair=False, resource_group_name=None, login=None):
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 4)

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)

    return _iot_hub_monitor_feedback(target=target, device_id=device_id, wait_on_id=wait_on_id)


def _iot_hub_monitor_feedback(target, device_id, wait_on_id):
    import importlib

    events3 = importlib.import_module('azext_iot.operations.events3._events')
    events3.monitor_feedback(target=target, device_id=device_id, wait_on_id=wait_on_id, token_duration=3600)
