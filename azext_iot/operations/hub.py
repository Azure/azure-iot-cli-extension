# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os.path import exists, basename
from time import time, sleep
import six
from knack.log import get_logger
from knack.util import CLIError
from azext_iot.constants import (
    EXTENSION_ROOT,
    DEVICE_DEVICESCOPE_PREFIX,
    TRACING_PROPERTY,
    TRACING_ALLOWED_FOR_LOCATION,
    TRACING_ALLOWED_FOR_SKU,
)
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import DeviceAuthType, SdkType, ProtocolType, ConfigType
from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot.common.utility import (
    shell_safe_json_parse,
    read_file_content,
    validate_key_value_pairs,
    url_encode_dict,
    unpack_msrest_error,
    init_monitoring,
    process_json_arg,
)
from azext_iot._factory import SdkResolver, CloudError
from azext_iot.operations.generic import _execute_query, _process_top


logger = get_logger(__name__)


# Query


def iot_query(
    cmd, query_command, hub_name=None, top=None, resource_group_name=None, login=None
):
    top = _process_top(top)
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )

    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        query_args = [query_command]
        query_method = service_sdk.registry_manager.query_iot_hub

        return _execute_query(query_args, query_method, top)
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device


def iot_device_show(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_show(target, device_id)


def _iot_device_show(target, device_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        device = service_sdk.registry_manager.get_device(
            id=device_id, raw=True
        ).response.json()
        device["hub"] = target.get("entity")
        return device
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_list(
    cmd,
    hub_name=None,
    top=1000,
    edge_enabled=False,
    resource_group_name=None,
    login=None,
):
    query = (
        "select * from devices where capabilities.iotEdge = true"
        if edge_enabled
        else "select * from devices"
    )
    result = iot_query(cmd, query, hub_name, top, resource_group_name, login=login)
    if not result:
        logger.info('No registered devices found on hub "%s".', hub_name)
    return result


def iot_device_create(
    cmd,
    device_id,
    hub_name=None,
    edge_enabled=False,
    auth_method="shared_private_key",
    primary_thumbprint=None,
    secondary_thumbprint=None,
    status="enabled",
    status_reason=None,
    valid_days=None,
    output_dir=None,
    set_parent_id=None,
    add_children=None,
    force=False,
    resource_group_name=None,
    login=None,
):

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    deviceScope = None
    if edge_enabled:
        if auth_method != DeviceAuthType.shared_private_key.name:
            raise CLIError("currently edge devices are limited to symmetric key auth")
        if add_children:
            for non_edge_device_id in add_children.split(","):
                nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
                _validate_nonedge_device(nonedge_device)
                _validate_parent_child_relation(nonedge_device, "-", force)
    else:
        if set_parent_id:
            edge_device = _iot_device_show(target, set_parent_id)
            _validate_edge_device(edge_device)
            deviceScope = edge_device["deviceScope"]

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise CLIError(
                "certificate output directory of '{}' does not exist.".format(
                    output_dir
                )
            )
        cert = _create_self_signed_cert(device_id, valid_days, output_dir)
        primary_thumbprint = cert["thumbprint"]

    try:
        device = _assemble_device(
            device_id,
            auth_method,
            edge_enabled,
            primary_thumbprint,
            secondary_thumbprint,
            status,
            status_reason,
            deviceScope,
        )
        output = service_sdk.registry_manager.create_or_update_device(
            id=device_id, device=device
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))

    if add_children:
        for non_edge_device_id in add_children.split(","):
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            _update_nonedge_devicescope(target, nonedge_device, output.device_scope)

    return output


def _assemble_device(
    device_id,
    auth_method,
    edge_enabled,
    pk=None,
    sk=None,
    status="enabled",
    status_reason=None,
    device_scope=None,
):
    from azext_iot.sdk.iothub.service.models import DeviceCapabilities, Device

    auth = _assemble_auth(auth_method, pk, sk)
    cap = DeviceCapabilities(iot_edge=edge_enabled)
    device = Device(
        device_id=device_id,
        authentication=auth,
        capabilities=cap,
        status=status,
        status_reason=status_reason,
        device_scope=device_scope,
    )
    return device


def _assemble_auth(auth_method, pk, sk):
    from azext_iot.sdk.iothub.service.models import (
        AuthenticationMechanism,
        SymmetricKey,
        X509Thumbprint,
    )

    auth = None
    if auth_method in [DeviceAuthType.shared_private_key.name, "sas"]:
        auth = AuthenticationMechanism(
            symmetric_key=SymmetricKey(primary_key=pk, secondary_key=sk), type="sas"
        )
    elif auth_method in [DeviceAuthType.x509_thumbprint.name, "selfSigned"]:
        if not pk:
            raise ValueError("primary thumbprint required with selfSigned auth")
        auth = AuthenticationMechanism(
            x509_thumbprint=X509Thumbprint(
                primary_thumbprint=pk, secondary_thumbprint=sk
            ),
            type="selfSigned",
        )
    elif auth_method in [DeviceAuthType.x509_ca.name, "certificateAuthority"]:
        auth = AuthenticationMechanism(type="certificateAuthority")
    else:
        raise ValueError("Authorization method {} invalid.".format(auth_method))
    return auth


def _create_self_signed_cert(subject, valid_days, output_path=None):
    from azext_iot.common.certops import create_self_signed_certificate

    return create_self_signed_certificate(subject, valid_days, output_path)


def iot_device_update(
    cmd, device_id, parameters, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        updated_device = _handle_device_update_params(parameters)
        etag = parameters.get("etag", None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.registry_manager.create_or_update_device(
                id=device_id, device=updated_device, custom_headers=headers
            )
        raise LookupError("device etag not found.")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def _handle_device_update_params(parameters):
    status = parameters["status"].lower()
    possible_status = ["enabled", "disabled"]
    if status not in possible_status:
        raise CLIError("status must be one of {}".format(possible_status))

    edge = parameters["capabilities"].get("iotEdge")
    if not isinstance(edge, bool):
        raise CLIError("capabilities.iotEdge is of type bool")

    auth, pk, sk = _parse_auth(parameters)
    return _assemble_device(
        parameters["deviceId"],
        auth,
        edge,
        pk,
        sk,
        status,
        parameters.get("statusReason"),
    )


def iot_device_delete(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        device = _iot_device_show(target=target, device_id=device_id)
        etag = device.get("etag")

        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.registry_manager.delete_device(
                id=device_id, custom_headers=headers
            )
            return
        raise LookupError("device etag not found")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def iot_device_get_parent(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    child_device = _iot_device_show(target, device_id)
    _validate_nonedge_device(child_device)
    _validate_child_device(child_device)
    device_scope = child_device["deviceScope"]
    parent_device_id = device_scope[
        len(DEVICE_DEVICESCOPE_PREFIX) : device_scope.rindex("-")
    ]
    return _iot_device_show(target, parent_device_id)


def iot_device_set_parent(
    cmd,
    device_id,
    parent_id,
    force=False,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    parent_device = _iot_device_show(target, parent_id)
    _validate_edge_device(parent_device)
    child_device = _iot_device_show(target, device_id)
    _validate_nonedge_device(child_device)
    _validate_parent_child_relation(child_device, parent_device["deviceScope"], force)
    _update_nonedge_devicescope(target, child_device, parent_device["deviceScope"])


def iot_device_children_add(
    cmd,
    device_id,
    child_list,
    force=False,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    devices = []
    edge_device = _iot_device_show(target, device_id)
    _validate_edge_device(edge_device)
    for non_edge_device_id in child_list.split(","):
        nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
        _validate_nonedge_device(nonedge_device)
        _validate_parent_child_relation(
            nonedge_device, edge_device["deviceScope"], force
        )
        devices.append(nonedge_device)

    for device in devices:
        _update_nonedge_devicescope(target, device, edge_device["deviceScope"])


def iot_device_children_remove(
    cmd,
    device_id,
    child_list=None,
    remove_all=False,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    devices = []
    if remove_all:
        result = _iot_device_children_list(
            cmd, device_id, hub_name, resource_group_name, login
        )
        if not result:
            raise CLIError(
                'No registered child devices found for "{}" edge device.'.format(
                    device_id
                )
            )
        for non_edge_device_id in [str(x["deviceId"]) for x in result]:
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            devices.append(nonedge_device)
    elif child_list:
        edge_device = _iot_device_show(target, device_id)
        _validate_edge_device(edge_device)
        for non_edge_device_id in child_list.split(","):
            nonedge_device = _iot_device_show(target, non_edge_device_id.strip())
            _validate_nonedge_device(nonedge_device)
            _validate_child_device(nonedge_device)
            if nonedge_device["deviceScope"] == edge_device["deviceScope"]:
                devices.append(nonedge_device)
            else:
                raise CLIError(
                    'The entered child device "{}" isn\'t assigned as a child of edge device "{}"'.format(
                        non_edge_device_id.strip(), device_id
                    )
                )
    else:
        raise CLIError(
            "Please specify comma-separated child list or use --remove-all to remove all children."
        )

    for device in devices:
        _update_nonedge_devicescope(target, device)


def iot_device_children_list(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    result = _iot_device_children_list(
        cmd, device_id, hub_name, resource_group_name, login
    )
    if not result:
        raise CLIError(
            'No registered child devices found for "{}" edge device.'.format(device_id)
        )
    return ", ".join([str(x["deviceId"]) for x in result])


def _iot_device_children_list(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    device = _iot_device_show(target, device_id)
    _validate_edge_device(device)
    query = "select * from devices where capabilities.iotEdge=false and deviceScope='{}'".format(
        device["deviceScope"]
    )
    return iot_query(cmd, query, hub_name, None, resource_group_name, login=login)


def _update_nonedge_devicescope(target, nonedge_device, deviceScope=""):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        nonedge_device["deviceScope"] = deviceScope
        etag = nonedge_device.get("etag", None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.registry_manager.create_or_update_device(
                id=nonedge_device["deviceId"],
                device=nonedge_device,
                custom_headers=headers,
            )
            return
        raise LookupError("device etag not found.")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def _validate_edge_device(device):
    if not device["capabilities"]["iotEdge"]:
        raise CLIError(
            'The device "{}" should be edge device.'.format(device["deviceId"])
        )


def _validate_nonedge_device(device):
    if device["capabilities"]["iotEdge"]:
        raise CLIError(
            'The entered child device "{}" should be non-edge device.'.format(
                device["deviceId"]
            )
        )


def _validate_child_device(device):
    if "deviceScope" not in device or device["deviceScope"] == "":
        raise CLIError(
            'Device "{}" doesn\'t support parent device functionality.'.format(
                device["deviceId"]
            )
        )


def _validate_parent_child_relation(child_device, deviceScope, force):
    if "deviceScope" not in child_device or child_device["deviceScope"] == "":
        return
    if child_device["deviceScope"] != deviceScope:
        if not force:
            raise CLIError(
                "The entered device \"{}\" already has a parent device, please use '--force'"
                " to overwrite".format(child_device["deviceId"])
            )
        return


# Module


def iot_device_module_create(
    cmd,
    device_id,
    module_id,
    hub_name=None,
    auth_method="shared_private_key",
    primary_thumbprint=None,
    secondary_thumbprint=None,
    valid_days=None,
    output_dir=None,
    resource_group_name=None,
    login=None,
):

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise CLIError(
                "certificate output directory of '{}' does not exist.".format(
                    output_dir
                )
            )
        cert = _create_self_signed_cert(module_id, valid_days, output_dir)
        primary_thumbprint = cert["thumbprint"]

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        module = _assemble_module(
            device_id=device_id,
            module_id=module_id,
            auth_method=auth_method,
            pk=primary_thumbprint,
            sk=secondary_thumbprint,
        )
        return service_sdk.registry_manager.create_or_update_module(
            id=device_id, mid=module_id, module=module
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _assemble_module(device_id, module_id, auth_method, pk=None, sk=None):
    from azext_iot.sdk.iothub.service.models import Module

    auth = _assemble_auth(auth_method, pk, sk)
    module = Module(module_id=module_id, device_id=device_id, authentication=auth)
    return module


def iot_device_module_update(
    cmd,
    device_id,
    module_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        updated_module = _handle_module_update_params(parameters)
        etag = parameters.get("etag")
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.registry_manager.create_or_update_module(
                id=device_id,
                mid=module_id,
                module=updated_module,
                custom_headers=headers,
            )
        raise LookupError("module etag not found.")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def _handle_module_update_params(parameters):
    auth, pk, sk = _parse_auth(parameters)
    return _assemble_module(
        device_id=parameters["deviceId"],
        module_id=parameters["moduleId"],
        auth_method=auth,
        pk=pk,
        sk=sk,
    )


def _parse_auth(parameters):
    valid_auth = ["sas", "selfSigned", "certificateAuthority"]
    auth = parameters["authentication"].get("type")
    if auth not in valid_auth:
        raise CLIError("authentication.type must be one of {}".format(valid_auth))
    pk = sk = None
    if auth == "sas":
        pk = parameters["authentication"]["symmetricKey"]["primaryKey"]
        sk = parameters["authentication"]["symmetricKey"]["secondaryKey"]
    elif auth == "selfSigned":
        pk = parameters["authentication"]["x509Thumbprint"]["primaryThumbprint"]
        sk = parameters["authentication"]["x509Thumbprint"]["secondaryThumbprint"]
        if not any([pk, sk]):
            raise CLIError(
                "primary + secondary Thumbprint required with selfSigned auth"
            )
    return auth, pk, sk


def iot_device_module_list(
    cmd, device_id, hub_name=None, top=1000, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.registry_manager.get_modules_on_device(device_id)[:top]
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_module_show(
    cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_module_show(target, device_id, module_id)


def _iot_device_module_show(target, device_id, module_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        module = service_sdk.registry_manager.get_module(
            id=device_id, mid=module_id, raw=True
        ).response.json()
        module["hub"] = target.get("entity")
        return module
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_module_delete(
    cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        module = _iot_device_module_show(
            target=target, device_id=device_id, module_id=module_id
        )
        etag = module.get("etag")
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.registry_manager.delete_module(
                id=device_id, mid=module_id, custom_headers=headers
            )
            return
        raise LookupError("module etag not found")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def iot_device_module_twin_show(
    cmd, device_id, module_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_module_twin_show(
        target=target, device_id=device_id, module_id=module_id
    )


def _iot_device_module_twin_show(target, device_id, module_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.twin.get_module_twin(
            id=device_id, mid=module_id, raw=True
        ).response.json()
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_device_module_twin_update(
    cmd,
    device_id,
    module_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"*"'
        verify = {}
        if parameters.get("properties"):
            if parameters["properties"].get("desired"):
                verify = {"properties.desired": dict}
        if parameters.get("tags"):
            verify["tags"] = dict
        verify_transform(parameters, verify)
        return service_sdk.twin.update_module_twin(
            id=device_id,
            mid=module_id,
            device_twin_info=parameters,
            custom_headers=headers,
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except (AttributeError, TypeError) as err:
        raise CLIError(err)


def iot_device_module_twin_replace(
    cmd,
    device_id,
    module_id,
    target_json,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        target_json = process_json_arg(target_json, argument_name="json")
        module = _iot_device_module_twin_show(
            target=target, device_id=device_id, module_id=module_id
        )
        etag = module.get("etag")
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.twin.replace_module_twin(
                id=device_id,
                mid=module_id,
                device_twin_info=target_json,
                custom_headers=headers,
            )
        raise LookupError("module twin etag not found")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def iot_edge_set_modules(
    cmd, device_id, content, hub_name=None, resource_group_name=None, login=None
):
    from azext_iot.sdk.iothub.service.models import ConfigurationContent

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        content = process_json_arg(content, argument_name="content")
        processed_content = _process_config_content(
            content, config_type=ConfigType.edge
        )

        content = ConfigurationContent(**processed_content)
        service_sdk.configuration.apply_on_edge_device(id=device_id, content=content)
        return iot_device_module_list(cmd, device_id, hub_name=hub_name, login=login)
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_edge_deployment_create(
    cmd,
    config_id,
    content,
    hub_name=None,
    target_condition="",
    priority=0,
    labels=None,
    metrics=None,
    layered=False,
    resource_group_name=None,
    login=None,
):
    config_type = ConfigType.layered if layered else ConfigType.edge
    return _iot_hub_configuration_create(
        cmd=cmd,
        config_id=config_id,
        content=content,
        hub_name=hub_name,
        target_condition=target_condition,
        priority=priority,
        labels=labels,
        metrics=metrics,
        resource_group_name=resource_group_name,
        login=login,
        config_type=config_type,
    )


def iot_hub_configuration_create(
    cmd,
    config_id,
    content,
    hub_name=None,
    target_condition="",
    priority=0,
    labels=None,
    metrics=None,
    resource_group_name=None,
    login=None,
):
    return _iot_hub_configuration_create(
        cmd=cmd,
        config_id=config_id,
        content=content,
        hub_name=hub_name,
        target_condition=target_condition,
        priority=priority,
        labels=labels,
        metrics=metrics,
        resource_group_name=resource_group_name,
        login=login,
        config_type=ConfigType.adm,
    )


def _iot_hub_configuration_create(
    cmd,
    config_id,
    content,
    config_type,
    hub_name=None,
    target_condition="",
    priority=0,
    labels=None,
    metrics=None,
    resource_group_name=None,
    login=None,
):
    from azext_iot.sdk.service.models import (
        Configuration,
        ConfigurationContent,
        ConfigurationMetrics,
    )

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    logger.debug("ensuring lowercase configuration Id...")
    config_id = config_id.lower()
    metrics_key = "queries"

    content = process_json_arg(content, argument_name="content")
    processed_content = _process_config_content(content, config_type)
    if "module_content" in processed_content:
        required_target_prefix = "from devices.modules where"
        lower_target_condition = target_condition.lower()
        if not lower_target_condition.startswith(required_target_prefix):
            raise CLIError(
                "The target condition for a module configuration must start with '{}'".format(
                    required_target_prefix
                )
            )

    if metrics:
        metrics = process_json_arg(metrics, argument_name="metrics")

        if "metrics" in metrics:
            metrics = metrics["metrics"]
        if metrics_key not in metrics:
            raise CLIError(
                "metrics json must include the '{}' property".format(metrics_key)
            )
        metrics = metrics[metrics_key]

    if labels:
        labels = process_json_arg(labels, argument_name="labels")

    config_content = ConfigurationContent(**processed_content)

    config_metrics = ConfigurationMetrics(queries=metrics)
    config = Configuration(
        id=config_id,
        schema_version="2.0",
        labels=labels,
        content=config_content,
        metrics=config_metrics,
        target_condition=target_condition,
        etag="*",
        priority=priority,
        content_type="assignment",
    )
    try:
        return service_sdk.configuration.create_or_update(
            id=config_id, configuration=config
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def _process_config_content(content, config_type):
    from knack.util import to_snake_case

    # Supports scenario where configuration payload is contained in 'content' key
    if "content" in content:
        content = content["content"]

    # Create new config dict to remove superflous properties
    processed_content = {}
    if config_type == ConfigType.adm:
        valid_adm_keys = ["deviceContent", "moduleContent"]
        if not all(key in content for key in valid_adm_keys):
            for key in valid_adm_keys:
                if key in content:
                    processed_content[to_snake_case(key)] = content[key]
                    return processed_content

        raise CLIError(
            "Automatic device configuration payloads require property: {}".format(
                " or ".join(map(str, valid_adm_keys))
            )
        )

    if config_type == ConfigType.edge or config_type == ConfigType.layered:
        valid_edge_key = "modulesContent"
        legacy_edge_key = "moduleContent"

        if valid_edge_key in content:
            processed_content[valid_edge_key] = content[valid_edge_key]
        elif legacy_edge_key in content:
            logger.warning(
                "'%s' is deprecated for edge deployments. Use '%s' instead - request is still processing...",
                legacy_edge_key,
                valid_edge_key,
            )
            processed_content[valid_edge_key] = content[legacy_edge_key]

        if processed_content:
            # Schema based validation currently for IoT edge deployment only
            if config_type == ConfigType.edge:
                _validate_payload_schema(processed_content)

            processed_content[to_snake_case(valid_edge_key)] = processed_content[
                valid_edge_key
            ]
            del processed_content[valid_edge_key]

            return processed_content

        raise CLIError(
            "Edge deployment payloads require property: {}".format(valid_edge_key)
        )


def _validate_payload_schema(content):
    import json
    from azext_iot.constants import EDGE_DEPLOYMENT_SCHEMA_2_PATH as schema_path
    from azext_iot.models.validators import JsonSchemaType, JsonSchemaValidator

    if not exists(schema_path):
        logger.info("Invalid schema path %s, skipping validation...", schema_path)
        return

    logger.info("Validating deployment payload...")
    schema_content = str(read_file_content(schema_path))

    try:
        schema_content = shell_safe_json_parse(schema_content)
    except CLIError:
        logger.info("Issue parsing Edge deployment schema, skipping validation...")
        return

    v = JsonSchemaValidator(schema_content, JsonSchemaType.draft4)
    errors = v.validate(content)
    if errors:
        # Pretty printing schema validation errors
        raise CLIError(
            json.dumps({"validationErrors": errors}, separators=(",", ":"), indent=2)
        )

    return


def iot_hub_configuration_update(
    cmd, config_id, parameters, hub_name=None, resource_group_name=None, login=None
):
    from azext_iot.sdk.service.models.configuration import Configuration
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        etag = parameters.get("etag")
        if not etag:
            raise LookupError("invalid request, configuration etag not found")
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag)
        verify = {"metrics": dict, "metrics.queries": dict, "content": dict}
        if parameters.get("labels"):
            verify["labels"] = dict
        verify_transform(parameters, verify)
        config = Configuration(
            id=parameters["id"],
            schema_version=parameters["schemaVersion"],
            labels=parameters["labels"],
            content=parameters["content"],
            metrics=parameters.get("metrics", None),
            target_condition=parameters["targetCondition"],
            priority=parameters["priority"],
            content_type="assignment",
        )
        return service_sdk.configuration.create_or_update(
            id=config_id, configuration=config, custom_headers=headers
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except (AttributeError, LookupError, TypeError) as err:
        raise CLIError(err)


def iot_hub_configuration_show(
    cmd, config_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_hub_configuration_show(target=target, config_id=config_id)


def _iot_hub_configuration_show(target, config_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.configuration.get(id=config_id, raw=True).response.json()
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_hub_configuration_list(
    cmd, hub_name=None, top=10, resource_group_name=None, login=None
):
    result = _iot_hub_configuration_list(
        cmd,
        hub_name=hub_name,
        top=top,
        resource_group_name=resource_group_name,
        login=login,
    )
    filtered = [
        c
        for c in result
        if (c["content"].get("deviceContent") or c["content"].get("moduleContent"))
    ]
    return filtered[:top]


def iot_edge_deployment_list(
    cmd, hub_name=None, top=10, resource_group_name=None, login=None
):
    result = _iot_hub_configuration_list(
        cmd,
        hub_name=hub_name,
        top=top,
        resource_group_name=resource_group_name,
        login=login,
    )

    filtered = [c for c in result if c["content"].get("modulesContent")]
    return filtered[:top]


def _iot_hub_configuration_list(
    cmd, hub_name=None, top=10, resource_group_name=None, login=None
):
    top = _process_top(top, upper_limit=100)

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        result = service_sdk.configuration.get_configurations(
            top=top, raw=True
        ).response.json()
        if not result:
            logger.info('No configurations found on hub "%s".', hub_name)
        return result
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_hub_configuration_delete(
    cmd, config_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        config = _iot_hub_configuration_show(target=target, config_id=config_id)
        etag = config.get("etag")
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.configuration.delete(id=config_id, custom_headers=headers)
            return
        raise LookupError("configuration etag not found")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def iot_edge_deployment_metric_show(
    cmd,
    config_id,
    metric_id,
    metric_type="user",
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    return iot_hub_configuration_metric_show(
        cmd,
        config_id=config_id,
        metric_id=metric_id,
        metric_type=metric_type,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
    )


def iot_hub_configuration_metric_show(
    cmd,
    config_id,
    metric_id,
    metric_type="user",
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        config = _iot_hub_configuration_show(target=target, config_id=config_id)

        metric_collection = None
        if metric_type == "system":
            metric_collection = config["systemMetrics"].get("queries")
        else:
            metric_collection = config["metrics"].get("queries")

        if metric_id not in metric_collection:
            raise CLIError(
                "the metric '{}' is not defined in the device configuration '{}'".format(
                    metric_id, config_id
                )
            )

        metric_query = metric_collection[metric_id]

        query_args = [metric_query]
        query_method = service_sdk.registry_manager.query_iot_hub

        metric_result = _execute_query(query_args, query_method, None)

        output = {}
        output["metric"] = metric_id
        output["query"] = metric_query
        output["result"] = metric_result

        return output
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device Twin


def iot_device_twin_show(
    cmd, device_id, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_twin_show(target=target, device_id=device_id)


def _iot_device_twin_show(target, device_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.twin.get_device_twin(id=device_id, raw=True).response.json()
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_twin_update_custom(instance, desired=None, tags=None):
    payload = {}
    is_patch = False
    if desired:
        is_patch = True
        payload["properties"] = {"desired": process_json_arg(desired, "desired")}

    if tags:
        is_patch = True
        payload["tags"] = process_json_arg(tags, "tags")

    return payload if is_patch else instance


def iot_device_twin_update(
    cmd, device_id, parameters, hub_name=None, resource_group_name=None, login=None
):
    from azext_iot.common.utility import verify_transform

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"*"'
        verify = {}
        if parameters.get("properties"):
            if parameters["properties"].get("desired"):
                verify = {"properties.desired": dict}
        if parameters.get("tags"):
            verify["tags"] = dict
        verify_transform(parameters, verify)
        return service_sdk.twin.update_device_twin(
            id=device_id, device_twin_info=parameters, custom_headers=headers
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except (AttributeError, TypeError) as err:
        raise CLIError(err)


def iot_device_twin_replace(
    cmd, device_id, target_json, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        target_json = process_json_arg(target_json, argument_name="json")
        device = _iot_device_twin_show(target=target, device_id=device_id)
        etag = device.get("etag")
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            return service_sdk.twin.replace_device_twin(
                id=device_id, device_twin_info=target_json, custom_headers=headers
            )
        raise LookupError("device twin etag not found")
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except LookupError as err:
        raise CLIError(err)


def iot_device_method(
    cmd,
    device_id,
    method_name,
    hub_name=None,
    method_payload="{}",
    timeout=30,
    resource_group_name=None,
    login=None,
):
    from azext_iot.sdk.service.models import CloudToDeviceMethod
    from azext_iot.constants import (
        METHOD_INVOKE_MAX_TIMEOUT_SEC,
        METHOD_INVOKE_MIN_TIMEOUT_SEC,
    )

    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MAX_TIMEOUT_SEC)
        )
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError(
            "timeout must be at least {} seconds".format(METHOD_INVOKE_MIN_TIMEOUT_SEC)
        )

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    # Prevent msrest locking up shell
    service_sdk.config.retry_policy.retries = 1
    try:
        if method_payload:
            method_payload = process_json_arg(
                method_payload, argument_name="method-payload"
            )

        method = CloudToDeviceMethod(method_name, timeout, timeout, method_payload)
        return service_sdk.device_method.invoke_device_method(
            device_id=device_id, direct_method_request=method, timeout=timeout
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Device Module Method Invoke


def iot_device_module_method(
    cmd,
    device_id,
    module_id,
    method_name,
    hub_name=None,
    method_payload="{}",
    timeout=30,
    resource_group_name=None,
    login=None,
):
    from azext_iot.sdk.service.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot.constants import (
        METHOD_INVOKE_MAX_TIMEOUT_SEC,
        METHOD_INVOKE_MIN_TIMEOUT_SEC,
    )

    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise CLIError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MAX_TIMEOUT_SEC)
        )
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise CLIError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MIN_TIMEOUT_SEC)
        )

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    # Prevent msrest locking up shell
    service_sdk.config.retry_policy.retries = 1
    try:
        if method_payload:
            method_payload = process_json_arg(
                method_payload, argument_name="method-payload"
            )

        method = CloudToDeviceMethod(method_name, timeout, timeout, method_payload)
        return service_sdk.device_method.invoke_module_method(
            device_id=device_id,
            module_id=module_id,
            direct_method_request=method,
            timeout=timeout,
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


# Utility


def iot_get_sas_token(
    cmd,
    hub_name=None,
    device_id=None,
    policy_name="iothubowner",
    key_type="primary",
    duration=3600,
    resource_group_name=None,
    login=None,
    module_id=None,
):
    key_type = key_type.lower()
    policy_name = policy_name.lower()

    if login and policy_name != "iothubowner":
        raise CLIError(
            "You are unable to change the sas policy with a hub connection string login."
        )
    if login and key_type != "primary" and not device_id:
        raise CLIError(
            "For non-device sas, you are unable to change the key type with a connection string login."
        )
    if module_id and not device_id:
        raise CLIError(
            "You are unable to get sas token for module without device information."
        )

    return {
        "sas": _iot_build_sas_token(
            cmd,
            hub_name,
            device_id,
            module_id,
            policy_name,
            key_type,
            duration,
            resource_group_name,
            login,
        ).generate_sas_token()
    }


def _iot_build_sas_token(
    cmd,
    hub_name=None,
    device_id=None,
    module_id=None,
    policy_name="iothubowner",
    key_type="primary",
    duration=3600,
    resource_group_name=None,
    login=None,
):
    from azext_iot.common._azure import (
        parse_iot_device_connection_string,
        parse_iot_device_module_connection_string,
    )

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, policy_name, login=login
    )
    uri = None
    policy = None
    key = None
    if device_id:
        logger.info(
            'Obtaining device "%s" details from registry, using IoT Hub policy "%s"',
            device_id,
            policy_name,
        )
        device = _iot_device_show(target, device_id)
        if module_id:
            module = _iot_device_module_show(target, device_id, module_id)
            module_cs = _build_device_or_module_connection_string(
                entity=module, key_type=key_type
            )
            uri = "{}/devices/{}/modules/{}".format(
                target["entity"], device_id, module_id
            )
            try:
                parsed_module_cs = parse_iot_device_module_connection_string(module_cs)
            except ValueError as e:
                logger.debug(e)
                raise CLIError("This module does not support SAS auth.")

            key = parsed_module_cs["SharedAccessKey"]
        else:
            device_cs = _build_device_or_module_connection_string(
                entity=device, key_type=key_type
            )
            uri = "{}/devices/{}".format(target["entity"], device_id)
            try:
                parsed_device_cs = parse_iot_device_connection_string(device_cs)
            except ValueError as e:
                logger.debug(e)
                raise CLIError("This device does not support SAS auth.")

            key = parsed_device_cs["SharedAccessKey"]
    else:
        uri = target["entity"]
        policy = target["policy"]
        key = target["primarykey"] if key_type == "primary" else target["secondarykey"]

    return SasTokenAuthentication(uri, policy, key, duration)


def _build_device_or_module_connection_string(entity, key_type="primary"):
    is_device = entity.get("moduleId") is None
    template = (
        "HostName={};DeviceId={};{}"
        if is_device
        else "HostName={};DeviceId={};ModuleId={};{}"
    )
    auth = entity["authentication"]
    auth_type = auth["type"].lower()
    if auth_type == "sas":
        key = "SharedAccessKey={}".format(
            auth["symmetricKey"]["primaryKey"]
            if key_type == "primary"
            else auth["symmetricKey"]["secondaryKey"]
        )
    elif auth_type in ["certificateauthority", "selfsigned"]:
        key = "x509=true"
    else:
        raise CLIError("Unable to form target connection string")

    if is_device:
        return template.format(entity.get("hub"), entity.get("deviceId"), key)
    else:
        return template.format(
            entity.get("hub"), entity.get("deviceId"), entity.get("moduleId"), key
        )


def iot_get_device_connection_string(
    cmd,
    device_id,
    hub_name=None,
    key_type="primary",
    resource_group_name=None,
    login=None,
):
    result = {}
    device = iot_device_show(
        cmd,
        device_id,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
    )
    result["connectionString"] = _build_device_or_module_connection_string(
        device, key_type
    )
    return result


def iot_get_module_connection_string(
    cmd,
    device_id,
    module_id,
    hub_name=None,
    key_type="primary",
    resource_group_name=None,
    login=None,
):
    result = {}
    module = iot_device_module_show(
        cmd,
        device_id,
        module_id,
        resource_group_name=resource_group_name,
        hub_name=hub_name,
        login=login,
    )
    result["connectionString"] = _build_device_or_module_connection_string(
        module, key_type
    )
    return result


# Messaging


def iot_device_send_message(
    cmd,
    device_id,
    hub_name=None,
    data="Ping from Az CLI IoT Extension",
    properties=None,
    msg_count=1,
    resource_group_name=None,
    login=None,
    qos=1,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_send_message(
        target=target,
        device_id=device_id,
        data=data,
        properties=properties,
        msg_count=msg_count,
        qos=qos,
    )


def _iot_device_send_message(
    target, device_id, data, properties=None, msg_count=1, qos=1
):
    from azext_iot.operations._mqtt import build_mqtt_device_username
    import paho.mqtt.publish as publish
    from paho.mqtt import client as mqtt
    import ssl
    import os

    msgs = []
    if properties:
        properties = validate_key_value_pairs(properties)

    sas = SasTokenAuthentication(
        target["entity"], target["policy"], target["primarykey"], 360
    ).generate_sas_token()
    cwd = EXTENSION_ROOT
    cert_path = os.path.join(cwd, "digicert.pem")
    auth = {
        "username": build_mqtt_device_username(target["entity"], device_id),
        "password": sas,
    }

    tls = {"ca_certs": cert_path, "tls_version": ssl.PROTOCOL_SSLv23}
    topic = "devices/{}/messages/events/{}".format(
        device_id, url_encode_dict(properties) if properties else ""
    )
    for _ in range(msg_count):
        msgs.append({"topic": topic, "payload": data, "qos": int(qos)})
    try:
        publish.multiple(
            msgs,
            client_id=device_id,
            hostname=target["entity"],
            auth=auth,
            port=8883,
            protocol=mqtt.MQTTv311,
            tls=tls,
        )
        return
    except Exception as x:
        raise CLIError(x)


def iot_device_send_message_http(
    cmd,
    device_id,
    data,
    hub_name=None,
    headers=None,
    resource_group_name=None,
    login=None,
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_device_send_message_http(target, device_id, data, headers)


def _iot_device_send_message_http(target, device_id, data, headers=None):
    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    try:
        return device_sdk.device.send_device_event(
            id=device_id, message=data, custom_headers=headers
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_complete(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_c2d_message_complete(target, device_id, etag)


def _iot_c2d_message_complete(target, device_id, etag):
    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    try:
        return device_sdk.device.complete_device_bound_notification(
            id=device_id, etag=etag
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_reject(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_c2d_message_reject(target, device_id, etag)


def _iot_c2d_message_reject(target, device_id, etag):
    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    try:
        return device_sdk.device.complete_device_bound_notification(
            id=device_id, etag=etag, reject=""
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_abandon(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_c2d_message_abandon(target, device_id, etag)


def _iot_c2d_message_abandon(target, device_id, etag):
    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    try:
        return device_sdk.device.abandon_device_bound_notification(
            id=device_id, etag=etag
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_receive(
    cmd, device_id, hub_name=None, lock_timeout=60, resource_group_name=None, login=None
):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _iot_c2d_message_receive(target, device_id, lock_timeout)


def _iot_c2d_message_receive(target, device_id, lock_timeout=60):
    from azext_iot.constants import MESSAGING_HTTP_C2D_SYSTEM_PROPERTIES

    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    request_headers = {}
    if lock_timeout:
        request_headers["IotHub-MessageLockTimeout"] = str(lock_timeout)

    try:
        result = device_sdk.device.receive_device_bound_notification(
            id=device_id, custom_headers=request_headers, raw=True
        ).response

        if result and result.status_code == 200:
            payload = {"properties": {}}

            if "etag" in result.headers:
                payload["etag"] = result.headers["etag"].strip('"')

            app_prop_prefix = "iothub-app-"
            app_prop_keys = [
                header
                for header in result.headers
                if header.lower().startswith(app_prop_prefix)
            ]

            app_props = {}
            for key in app_prop_keys:
                app_props[key[len(app_prop_prefix) :]] = result.headers[key]

            if app_props:
                payload["properties"]["app"] = app_props

            sys_props = {}
            for key in MESSAGING_HTTP_C2D_SYSTEM_PROPERTIES:
                if key in result.headers:
                    sys_props[key] = result.headers[key]

            if sys_props:
                payload["properties"]["system"] = sys_props

            if result.text:
                payload["data"] = (
                    result.text
                    if not isinstance(result.text, six.binary_type)
                    else result.text.decode("utf-8")
                )

            return payload
        return
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_c2d_message_send(
    cmd,
    device_id,
    hub_name=None,
    data="Ping from Az CLI IoT Extension",
    message_id=None,
    correlation_id=None,
    user_id=None,
    content_encoding="utf-8",
    content_type=None,
    expiry_time_utc=None,
    properties=None,
    ack=None,
    wait_on_feedback=False,
    yes=False,
    repair=False,
    resource_group_name=None,
    login=None,
):
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 4)

    if wait_on_feedback and not ack:
        raise CLIError(
            'To wait on device feedback, ack must be "full", "negative" or "positive"'
        )

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )

    if properties:
        properties = validate_key_value_pairs(properties)

    if expiry_time_utc:
        now_in_milli = int(time() * 1000)
        user_msg_expiry = int(expiry_time_utc)
        if user_msg_expiry < now_in_milli:
            raise CLIError("Message expiry time utc is in the past!")

    from azext_iot.operations.events3 import _events

    msg_id, errors = _events.send_c2d_message(
        target=target,
        device_id=device_id,
        data=data,
        message_id=message_id,
        correlation_id=correlation_id,
        user_id=user_id,
        content_encoding=content_encoding,
        content_type=content_type,
        expiry_time_utc=expiry_time_utc,
        properties=properties,
        ack=ack,
    )
    if errors:
        raise CLIError(
            "C2D message error: {}, use --debug for more details.".format(errors)
        )

    if wait_on_feedback:
        _iot_hub_monitor_feedback(target=target, device_id=device_id, wait_on_id=msg_id)


def iot_simulate_device(
    cmd,
    device_id,
    hub_name=None,
    receive_settle="complete",
    data="Ping from Az CLI IoT Extension",
    msg_count=100,
    msg_interval=3,
    protocol_type="mqtt",
    properties=None,
    resource_group_name=None,
    login=None,
):
    import sys
    import uuid
    import datetime
    import json
    from azext_iot.operations._mqtt import mqtt_client_wrap
    from azext_iot.common.utility import execute_onthread
    from azext_iot.constants import (
        MIN_SIM_MSG_INTERVAL,
        MIN_SIM_MSG_COUNT,
        SIM_RECEIVE_SLEEP_SEC,
    )

    protocol_type = protocol_type.lower()
    if protocol_type == ProtocolType.mqtt.name:
        if receive_settle != "complete":
            raise CLIError('mqtt protocol only supports settle type of "complete"')

    if msg_interval < MIN_SIM_MSG_INTERVAL:
        raise CLIError("msg interval must be at least {}".format(MIN_SIM_MSG_INTERVAL))

    if msg_count < MIN_SIM_MSG_COUNT:
        raise CLIError("msg count must be at least {}".format(MIN_SIM_MSG_COUNT))

    properties_to_send = _iot_simulate_get_default_properties(protocol_type)
    user_properties = validate_key_value_pairs(properties) or {}
    properties_to_send.update(user_properties)

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    token = None

    class generator(object):
        def __init__(self):
            self.calls = 0

        def generate(self, jsonify=True):
            self.calls += 1
            payload = {
                "id": str(uuid.uuid4()),
                "timestamp": str(datetime.datetime.utcnow()),
                "data": str(data + " #{}".format(self.calls)),
            }
            return json.dumps(payload) if jsonify else payload

    def http_wrap(target, device_id, generator):
        d = generator.generate(False)
        _iot_device_send_message_http(target, device_id, d, headers=properties_to_send)
        six.print_(".", end="", flush=True)

    try:
        if protocol_type == ProtocolType.mqtt.name:
            wrap = mqtt_client_wrap(
                target=target,
                device_id=device_id,
                properties=properties_to_send,
                sas_duration=(msg_count * msg_interval)
                + 60,  # int type is enforced for msg_count and msg_interval
            )
            wrap.execute(generator(), publish_delay=msg_interval, msg_count=msg_count)
        else:
            six.print_("Sending and receiving events via https")
            token, op = execute_onthread(
                method=http_wrap,
                args=[target, device_id, generator()],
                interval=msg_interval,
                max_runs=msg_count,
                return_handle=True,
            )
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


def _iot_simulate_get_default_properties(protocol):
    default_properties = {}
    is_mqtt = protocol == ProtocolType.mqtt.name

    default_properties["$.ct" if is_mqtt else "content-type"] = "application/json"
    default_properties["$.ce" if is_mqtt else "content-encoding"] = "utf-8"

    return default_properties


def _handle_c2d_msg(target, device_id, receive_settle):
    result = _iot_c2d_message_receive(target, device_id)
    if result:
        six.print_()
        six.print_("__Received C2D Message__")
        six.print_(result)
        if receive_settle == "reject":
            six.print_("__Rejecting message__")
            _iot_c2d_message_reject(target, device_id, result["etag"])
        elif receive_settle == "abandon":
            six.print_("__Abandoning message__")
            _iot_c2d_message_abandon(target, device_id, result["etag"])
        else:
            six.print_("__Completing message__")
            _iot_c2d_message_complete(target, device_id, result["etag"])
        return True
    return False


def iot_device_export(
    cmd, hub_name, blob_container_uri, include_keys=False, resource_group_name=None
):
    from azext_iot._factory import iot_hub_service_factory

    client = iot_hub_service_factory(cmd.cli_ctx)
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.export_devices(
        target["resourcegroup"], hub_name, blob_container_uri, not include_keys
    )


def iot_device_import(
    cmd,
    hub_name,
    input_blob_container_uri,
    output_blob_container_uri,
    resource_group_name=None,
):
    from azext_iot._factory import iot_hub_service_factory

    client = iot_hub_service_factory(cmd.cli_ctx)
    target = get_iot_hub_connection_string(client, hub_name, resource_group_name)
    return client.import_devices(
        target["resourcegroup"],
        hub_name,
        input_blob_container_uri,
        output_blob_container_uri,
    )


def iot_device_upload_file(
    cmd,
    device_id,
    file_path,
    content_type,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    from azext_iot.sdk.iothub.device.models import FileUploadCompletionStatus

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )

    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    if not exists(file_path):
        raise CLIError('File path "{}" does not exist!'.format(file_path))

    content = read_file_content(file_path)
    file_name = basename(file_path)

    try:
        upload_meta = device_sdk.device.create_file_upload_sas_uri(
            device_id=device_id, blob_name=file_name, raw=True
        ).response.json()
        storage_endpoint = "{}/{}/{}{}".format(
            upload_meta["hostName"],
            upload_meta["containerName"],
            upload_meta["blobName"],
            upload_meta["sasToken"],
        )
        completion_status = FileUploadCompletionStatus(
            correlation_id=upload_meta["correlationId"], is_success=True
        )
        upload_response = device_sdk.device.upload_file_to_container(
            storage_endpoint=storage_endpoint,
            content=content,
            content_type=content_type,
        )
        completion_status.status_code = upload_response.status_code
        completion_status.status_reason = upload_response.reason

        return device_sdk.device.update_file_upload_status(
            device_id=device_id, file_upload_completion_status=completion_status
        )
    except CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def iot_hub_monitor_events(
    cmd,
    hub_name=None,
    device_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    resource_group_name=None,
    yes=False,
    properties=None,
    repair=False,
    login=None,
    content_type=None,
    device_query=None,
):
    try:
        _iot_hub_monitor_events(
            cmd,
            hub_name=hub_name,
            device_id=device_id,
            consumer_group=consumer_group,
            timeout=timeout,
            enqueued_time=enqueued_time,
            resource_group_name=resource_group_name,
            yes=yes,
            properties=properties,
            repair=repair,
            login=login,
            content_type=content_type,
            device_query=device_query,
        )
    except RuntimeError as e:
        raise CLIError(e)


def iot_hub_monitor_feedback(
    cmd,
    hub_name=None,
    device_id=None,
    yes=False,
    wait_on_id=None,
    repair=False,
    resource_group_name=None,
    login=None,
):
    from azext_iot.common.deps import ensure_uamqp
    from azext_iot.common.utility import validate_min_python_version

    validate_min_python_version(3, 4)

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )

    return _iot_hub_monitor_feedback(
        target=target, device_id=device_id, wait_on_id=wait_on_id
    )


def iot_hub_distributed_tracing_show(
    cmd, hub_name, device_id, resource_group_name=None
):
    device_twin = _iot_hub_distributed_tracing_show(
        cmd, hub_name, device_id, resource_group_name
    )
    return _customize_device_tracing_output(
        device_twin["deviceId"],
        device_twin["properties"]["desired"],
        device_twin["properties"]["reported"],
    )


def _iot_hub_monitor_events(
    cmd,
    interface_name=None,
    pnp_context=None,
    hub_name=None,
    device_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    resource_group_name=None,
    yes=False,
    properties=None,
    repair=False,
    login=None,
    content_type=None,
    device_query=None,
):
    (enqueued_time, properties, timeout, output) = init_monitoring(
        cmd, timeout, properties, enqueued_time, repair, yes
    )

    device_ids = {}
    if device_query:
        devices_result = iot_query(
            cmd, device_query, hub_name, None, resource_group_name, login=login
        )
        if devices_result:
            for device_result in devices_result:
                device_ids[device_result["deviceId"]] = True

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, include_events=True, login=login
    )

    from azext_iot.operations.events3 import _builders, _events

    eventHubTarget = _builders.EventTargetBuilder().build_iot_hub_target(target)

    _events.executor(
        eventHubTarget,
        consumer_group=consumer_group,
        enqueued_time=enqueued_time,
        properties=properties,
        timeout=timeout,
        device_id=device_id,
        output=output,
        content_type=content_type,
        devices=device_ids,
        interface_name=interface_name,
        pnp_context=pnp_context,
    )


def iot_hub_distributed_tracing_update(
    cmd, hub_name, device_id, sampling_mode, sampling_rate, resource_group_name=None
):
    if int(sampling_rate) not in range(0, 101):
        raise CLIError(
            "Sampling rate is a percentage, So only values from 0 to 100(inclusive) are permitted."
        )
    device_twin = _iot_hub_distributed_tracing_show(
        cmd, hub_name, device_id, resource_group_name
    )
    if TRACING_PROPERTY not in device_twin["properties"]["desired"]:
        device_twin["properties"]["desired"][TRACING_PROPERTY] = {}
    device_twin["properties"]["desired"][TRACING_PROPERTY]["sampling_rate"] = int(
        sampling_rate
    )
    device_twin["properties"]["desired"][TRACING_PROPERTY]["sampling_mode"] = (
        1 if sampling_mode.lower() == "on" else 2
    )
    result = iot_device_twin_update(
        cmd, device_id, device_twin, hub_name, resource_group_name
    )
    return _customize_device_tracing_output(
        result.device_id, result.properties.desired, result.properties.reported
    )


def _iot_hub_monitor_feedback(target, device_id, wait_on_id):
    from azext_iot.operations.events3 import _events

    _events.monitor_feedback(
        target=target, device_id=device_id, wait_on_id=wait_on_id, token_duration=3600
    )


def _iot_hub_distributed_tracing_show(
    cmd, hub_name, device_id, resource_group_name=None
):
    target = get_iot_hub_connection_string(cmd, hub_name, resource_group_name)
    device_twin = iot_device_twin_show(cmd, device_id, hub_name, resource_group_name)
    _validate_device_tracing(target, device_twin)
    return device_twin


def _validate_device_tracing(target, device_twin):
    if target["location"].lower() not in TRACING_ALLOWED_FOR_LOCATION:
        raise CLIError(
            'Distributed tracing isn\'t supported for the hub located at "{}" location.'.format(
                target["location"]
            )
        )
    if target["sku_tier"].lower() != TRACING_ALLOWED_FOR_SKU:
        raise CLIError(
            'Distributed tracing isn\'t supported for the hub belongs to "{}" sku tier.'.format(
                target["sku_tier"]
            )
        )
    if device_twin["capabilities"]["iotEdge"]:
        raise CLIError(
            'The device "{}" should be non-edge device.'.format(device_twin["deviceId"])
        )


def _customize_device_tracing_output(device_id, desired, reported):
    output = {}
    desired_tracing = desired.get(TRACING_PROPERTY, None)
    if desired_tracing:
        output["deviceId"] = device_id
        output["samplingMode"] = (
            "enabled" if desired_tracing.get("sampling_mode") == 1 else "disabled"
        )
        output["samplingRate"] = "{}%".format(desired_tracing.get("sampling_rate"))
        output["isSynced"] = False
        reported_tracing = reported.get(TRACING_PROPERTY, None)
        if (
            reported_tracing
            and desired_tracing.get("sampling_mode")
            == reported_tracing.get("sampling_mode").get("value", None)
            and desired_tracing.get("sampling_rate")
            == reported_tracing.get("sampling_rate").get("value", None)
        ):
            output["isSynced"] = True
    return output
