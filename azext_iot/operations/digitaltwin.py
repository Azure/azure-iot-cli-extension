# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os.path import exists
from knack.util import CLIError
from azure.cli.core.util import read_file_content
from azext_iot.constants import PNP_ENDPOINT
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType, ModelSourceType
from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot.common.utility import (shell_safe_json_parse,
                                      unpack_msrest_error)
from azext_iot.operations.pnp import (iot_pnp_interface_show,
                                      iot_pnp_interface_list,
                                      _validate_repository)
from azext_iot.operations.hub import _iot_hub_monitor_events


INTERFACE_KEY_NAME = 'urn_azureiot_ModelDiscovery_DigitalTwin'
INTERFACE_COMMAND = 'Command'
INTERFACE_PROPERTY = 'Property'
INTERFACE_TELEMETRY = 'Telemetry'
INTERFACE_MODELDEFINITION = 'urn_azureiot_ModelDiscovery_ModelDefinition'
INTERFACE_COMMANDNAME = 'getModelDefinition'


def iot_digitaltwin_interface_list(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    device_default_interface = _iot_digitaltwin_interface_show(cmd, device_id, INTERFACE_KEY_NAME,
                                                               hub_name, resource_group_name, login)
    result = _get_device_default_interface_dict(device_default_interface)
    return {'interfaces': result}


def iot_digitaltwin_command_list(cmd, device_id, source_model, interface=None, schema=False,
                                 repo_endpoint=PNP_ENDPOINT, repo_id=None, repo_login=None,
                                 hub_name=None, resource_group_name=None, login=None):
    result = []
    target_interfaces = []
    source_model = source_model.lower()
    device_interfaces = _iot_digitaltwin_interface_list(cmd, device_id, hub_name, resource_group_name, login)
    interface_list = _get_device_default_interface_dict(device_interfaces)
    target_interface = next((item for item in interface_list if item['name'] == interface), None)
    if interface and not target_interface:
        raise CLIError('Target interface is not implemented by the device!')

    if interface:
        target_interfaces.append(target_interface)
    else:
        target_interfaces = interface_list

    for entity in target_interfaces:
        interface_result = {'name': entity['name'], 'urn_id': entity['urn_id'], 'commands': {}}
        interface_commands = []
        found_commands = []
        if source_model == ModelSourceType.device.value.lower():
            found_commands = _device_interface_elements(cmd, device_id, entity['urn_id'], INTERFACE_COMMAND,
                                                        hub_name, resource_group_name, login)
        else:
            if source_model == ModelSourceType.private.value.lower():
                _validate_repository(repo_id, repo_login)
            found_commands = _pnp_interface_elements(cmd, entity['urn_id'], INTERFACE_COMMAND,
                                                     repo_endpoint, repo_id, repo_login)
        for command in found_commands:
            command.pop('@type', None)
            if schema:
                interface_commands.append(command)
            else:
                interface_commands.append(command.get('name'))
        interface_result['commands'] = interface_commands
        result.append(interface_result)
    return {'interfaces': result}


def iot_digitaltwin_properties_list(cmd, device_id, source_model, interface=None, schema=False,
                                    repo_endpoint=PNP_ENDPOINT, repo_id=None, repo_login=None,
                                    hub_name=None, resource_group_name=None, login=None):
    result = []
    target_interfaces = []
    source_model = source_model.lower()
    device_interfaces = _iot_digitaltwin_interface_list(cmd, device_id, hub_name, resource_group_name, login)
    interface_list = _get_device_default_interface_dict(device_interfaces)
    target_interface = next((item for item in interface_list if item['name'] == interface), None)
    if interface and not target_interface:
        raise CLIError('Target interface is not implemented by the device!')

    if interface:
        target_interfaces.append(target_interface)
    else:
        target_interfaces = interface_list

    for entity in target_interfaces:
        interface_result = {'name': entity['name'], 'urn_id': entity['urn_id'], 'properties': {}}
        interface_properties = []
        found_properties = []
        if source_model == ModelSourceType.device.value.lower():
            found_properties = _device_interface_elements(cmd, device_id, entity['urn_id'], INTERFACE_PROPERTY,
                                                          hub_name, resource_group_name, login)
        else:
            if source_model == ModelSourceType.private.value.lower():
                _validate_repository(repo_id, repo_login)
            found_properties = _pnp_interface_elements(cmd, entity['urn_id'], INTERFACE_PROPERTY,
                                                       repo_endpoint, repo_id, repo_login)
        for prop in found_properties:
            prop.pop('@type', None)
            if schema:
                interface_properties.append(prop)
            else:
                interface_properties.append(prop.get('name'))
        interface_result['properties'] = interface_properties
        result.append(interface_result)
    return {'interfaces': result}


def iot_digitaltwin_invoke_command(cmd, interface, device_id, command_name, command_payload=None,
                                   timeout=10, hub_name=None, resource_group_name=None, login=None):
    device_interfaces = _iot_digitaltwin_interface_list(cmd, device_id, hub_name, resource_group_name, login)
    interface_list = _get_device_default_interface_dict(device_interfaces)

    target_interface = next((item for item in interface_list if item['name'] == interface), None)

    if not target_interface:
        raise CLIError('Target interface is not implemented by the device!')

    if command_payload:
        if exists(command_payload):
            command_payload = str(read_file_content(command_payload))

        target_json = None
        try:
            target_json = shell_safe_json_parse(command_payload)
        except ValueError:
            pass

        if target_json or isinstance(target_json, bool):
            command_payload = target_json

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        result = service_sdk.invoke_interface_command(device_id,
                                                      interface,
                                                      command_name,
                                                      command_payload,
                                                      connect_timeout_in_seconds=timeout,
                                                      response_timeout_in_seconds=timeout)
        return result
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_digitaltwin_property_update(cmd, interface_payload, device_id,
                                    hub_name=None, resource_group_name=None, login=None):
    if exists(interface_payload):
        interface_payload = str(read_file_content(interface_payload))

    target_json = None
    try:
        target_json = shell_safe_json_parse(interface_payload)
    except ValueError:
        pass

    if target_json:
        interface_payload = target_json

    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        result = service_sdk.update_interfaces(device_id, interfaces=interface_payload)
        return result
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_digitaltwin_monitor_events(cmd, device_id=None, device_query=None, interface=None,
                                   source_model=ModelSourceType.public.value, repo_endpoint=PNP_ENDPOINT,
                                   repo_id=None, consumer_group='$Default', timeout=300, hub_name=None,
                                   resource_group_name=None, yes=False, properties=None, repair=False,
                                   login=None, repo_login=None):
    source_model = source_model.lower()
    pnp_context = {'enabled': True, 'interface': {}}
    target_interfaces = []
    interface_name = None
    if all([device_id, device_query]):
        raise CLIError('You cannot use --device-id/-d and --device-query/-q at the same time!')

    if all([interface, device_query]):
        raise CLIError('You cannot use --interface/-i and --device-query/-q at the same time!')

    if device_id:
        device_interfaces = _iot_digitaltwin_interface_list(cmd, device_id, hub_name, resource_group_name, login)
        interface_list = _get_device_default_interface_dict(device_interfaces)

        target_interface = next((k for k in interface_list if k['name'] == interface), None)
        if interface and not target_interface:
            raise CLIError('Target interface is not implemented by the device!')

        if interface:
            target_interfaces.append(target_interface)
            interface_name = interface
        else:
            target_interfaces = interface_list

        for entity in target_interfaces:
            pnp_context['interface'][entity['name']] = {}
            found_telemetry = []
            if source_model == ModelSourceType.device.value.lower():
                found_telemetry = _device_interface_elements(cmd, device_id, entity['urn_id'], INTERFACE_TELEMETRY,
                                                             hub_name, resource_group_name, login)
            else:
                if source_model == ModelSourceType.private.value.lower():
                    _validate_repository(repo_id, repo_login)
                found_telemetry = _pnp_interface_elements(cmd, entity['urn_id'], INTERFACE_TELEMETRY,
                                                          repo_endpoint, repo_id, repo_login)

            for telemetry in found_telemetry:
                telemetry_data = {'display': telemetry.get('displayName'), 'unit': telemetry.get('unit')}
                pnp_context['interface'][entity['name']][telemetry['name']] = telemetry_data

    _iot_hub_monitor_events(cmd=cmd, interface=interface_name, pnp_context=pnp_context,
                            hub_name=hub_name, device_id=device_id, consumer_group=consumer_group, timeout=timeout,
                            enqueued_time=None, resource_group_name=resource_group_name,
                            yes=yes, properties=properties, repair=repair,
                            login=login, device_query=device_query)


def _iot_digitaltwin_interface_show(cmd, device_id, interface, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        device_interface = service_sdk.get_interface(device_id, interface)
        return device_interface
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _iot_digitaltwin_interface_list(cmd, device_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    try:
        device_interfaces = service_sdk.get_interfaces(device_id)
        return device_interfaces
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _get_device_default_interface_dict(device_default_interface):
    interface = device_default_interface['interfaces'][INTERFACE_KEY_NAME]
    result = []
    for k, v in interface['properties']['modelInformation']['reported']['value']['interfaces'].items():
        result.append({'name': k, "urn_id": v})
    return result


def _pnp_interface_elements(cmd, interface, target_type, repo_endpoint, repo_id, login):
    interface_elements = []
    results = iot_pnp_interface_list(cmd, repo_endpoint, repo_id, interface, login=login)
    if results:
        interface_def = iot_pnp_interface_show(cmd, interface, repo_endpoint, repo_id, login)
        interface_contents = interface_def.get('contents')
        for content in interface_contents:
            if isinstance(content.get('@type'), list) and target_type in content.get('@type'):
                interface_elements.append(content)
            elif content.get('@type') == target_type:
                interface_elements.append(content)
    return interface_elements


def _device_interface_elements(cmd, device_id, interface, target_type, hub_name, resource_group_name, login):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name, login=login)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)
    interface_elements = []
    try:
        payload = {'id': {}}
        payload['id'] = interface
        target_payload = shell_safe_json_parse(str(payload))
        interface_def = service_sdk.invoke_interface_command(device_id,
                                                             INTERFACE_MODELDEFINITION,
                                                             INTERFACE_COMMANDNAME,
                                                             target_payload)
        if interface_def and interface_def.get('contents'):
            interface_contents = interface_def.get('contents')
            for content in interface_contents:
                if isinstance(content.get('@type'), list) and target_type in content.get('@type'):
                    interface_elements.append(content)
                elif content.get('@type') == target_type:
                    interface_elements.append(content)
        return interface_elements
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except Exception:
        # returning an empty collection to continue
        return []
