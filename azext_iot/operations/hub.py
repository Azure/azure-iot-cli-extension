# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os.path import exists, basename
from time import time, sleep
from knack.log import get_logger
from enum import Enum, EnumMeta
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    CLIInternalError,
    ClientRequestError,
    FileOperationError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    ValidationError,
)
from azext_iot.constants import (
    DEVICE_DEVICESCOPE_PREFIX,
    TRACING_PROPERTY,
    TRACING_ALLOWED_FOR_LOCATION,
    TRACING_ALLOWED_FOR_SKU,
    IOTHUB_TRACK_2_SDK_MIN_VERSION,
)
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import (
    DeviceAuthType,
    SdkType,
    ProtocolType,
    ConfigType,
    KeyType,
    SettleType,
    RenewKeyType,
    IoTHubStateType,
    DeviceAuthApiType,
    ConnectionStringParser,
    EntityStatusType
)
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.common.utility import (
    handle_service_exception,
    read_file_content,
    validate_key_value_pairs,
    init_monitoring,
    process_json_arg,
    ensure_iothub_sdk_min_version,
    generate_key,
)
from azext_iot._factory import SdkResolver, CloudError
from azext_iot.operations.generic import _execute_query, _process_top
import pprint

logger = get_logger(__name__)
printer = pprint.PrettyPrinter(indent=2)


# Query

def iot_query(
    cmd,
    query_command,
    hub_name=None,
    top=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    top = _process_top(top)
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        query_args = [query_command]
        query_method = service_sdk.query.get_twins

        return _execute_query(query_args, query_method, top)
    except CloudError as e:
        handle_service_exception(e)


# Device


def iot_device_show(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_device_show(target, device_id)


def _iot_device_show(target, device_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        device = service_sdk.devices.get_identity(
            id=device_id, raw=True
        ).response.json()
        device["hub"] = target.get("entity")
        return device
    except CloudError as e:
        handle_service_exception(e)


def iot_device_list(
    cmd,
    hub_name=None,
    top=1000,
    edge_enabled=False,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    query = (
        "select * from devices where capabilities.iotEdge = true"
        if edge_enabled
        else "select * from devices"
    )
    result = iot_query(
        cmd=cmd,
        query_command=query,
        hub_name=hub_name,
        top=top,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )

    if not result:
        logger.info('No registered devices found on hub "%s".', hub_name)
    return result


def iot_device_create(
    cmd,
    device_id,
    hub_name=None,
    edge_enabled=False,
    auth_method=DeviceAuthType.shared_private_key.value,
    primary_key=None,
    secondary_key=None,
    primary_thumbprint=None,
    secondary_thumbprint=None,
    status=EntityStatusType.enabled.value,
    status_reason=None,
    valid_days=None,
    output_dir=None,
    device_scope=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise FileOperationError(
                "certificate output directory of '{}' does not exist.".format(
                    output_dir
                )
            )
        cert = _create_self_signed_cert(device_id, valid_days, output_dir)
        primary_thumbprint = cert["thumbprint"]

    try:
        device = _assemble_device(
            is_update=False,
            device_id=device_id,
            auth_method=auth_method,
            edge_enabled=edge_enabled,
            pk=primary_thumbprint if auth_method == DeviceAuthType.x509_thumbprint.value else primary_key,
            sk=secondary_thumbprint if auth_method == DeviceAuthType.x509_thumbprint.value else secondary_key,
            status=status,
            status_reason=status_reason,
            device_scope=device_scope,
        )
        output = service_sdk.devices.create_or_update_identity(
            id=device_id, device=device
        )
    except CloudError as e:
        handle_service_exception(e)
    except ValueError as ve:
        raise InvalidArgumentValueError(ve)

    return output


def _assemble_device(
    is_update,
    device_id,
    auth_method,
    edge_enabled,
    pk=None,
    sk=None,
    status=EntityStatusType.enabled.value,
    status_reason=None,
    device_scope=None,
):
    from azext_iot.sdk.iothub.service.models import DeviceCapabilities, Device

    auth = _assemble_auth(auth_method, pk, sk)
    cap = DeviceCapabilities(iot_edge=edge_enabled)
    if is_update:
        device = Device(
            device_id=device_id,
            authentication=auth,
            capabilities=cap,
            status=status,
            status_reason=status_reason,
            device_scope=device_scope,
        )
        return device
    if edge_enabled:
        parent_scopes = []
        if device_scope:
            parent_scopes = [device_scope]
        device = Device(
            device_id=device_id,
            authentication=auth,
            capabilities=cap,
            status=status,
            status_reason=status_reason,
            parent_scopes=parent_scopes,
        )
        return device
    else:
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
    if auth_method in [
        DeviceAuthType.shared_private_key.name,
        DeviceAuthApiType.sas.value,
    ]:
        if any([pk, sk]) and not all([pk, sk]):
            raise ValueError("When configuring symmetric key auth both primary and secondary keys are required.")

        auth = AuthenticationMechanism(
            symmetric_key=SymmetricKey(primary_key=pk, secondary_key=sk),
            type=DeviceAuthApiType.sas.value,
        )
    elif auth_method in [
        DeviceAuthType.x509_thumbprint.name,
        DeviceAuthApiType.selfSigned.value,
    ]:
        if not pk:
            raise ValueError("When configuring selfSigned auth the primary thumbprint is required.")
        auth = AuthenticationMechanism(
            x509_thumbprint=X509Thumbprint(
                primary_thumbprint=pk, secondary_thumbprint=sk
            ),
            type=DeviceAuthApiType.selfSigned.value,
        )
    elif auth_method in [
        DeviceAuthType.x509_ca.name,
        DeviceAuthApiType.certificateAuthority.value,
    ]:
        auth = AuthenticationMechanism(
            type=DeviceAuthApiType.certificateAuthority.value
        )
    else:
        raise ValueError("Authorization method {} invalid.".format(auth_method))
    return auth


def _create_self_signed_cert(subject, valid_days, output_path=None):
    from azext_iot.common.certops import create_self_signed_certificate

    return create_self_signed_certificate(subject, valid_days, output_path)


def update_iot_device_custom(
    instance,
    edge_enabled=None,
    status=None,
    status_reason=None,
    auth_method=None,
    primary_thumbprint=None,
    secondary_thumbprint=None,
    primary_key=None,
    secondary_key=None,
):
    if edge_enabled is not None:
        instance["capabilities"]["iotEdge"] = edge_enabled
    if status is not None:
        instance["status"] = status
    if status_reason is not None:
        instance["statusReason"] = status_reason

    auth_type = instance["authentication"]["type"]
    if auth_method is not None:
        if auth_method == DeviceAuthType.shared_private_key.name:
            auth = DeviceAuthApiType.sas.value
            if (primary_key and not secondary_key) or (
                not primary_key and secondary_key
            ):
                raise RequiredArgumentMissingError("primary + secondary Key required with sas auth")
            instance["authentication"]["symmetricKey"]["primaryKey"] = primary_key
            instance["authentication"]["symmetricKey"]["secondaryKey"] = secondary_key
        elif auth_method == DeviceAuthType.x509_thumbprint.name:
            auth = DeviceAuthApiType.selfSigned.value
            if not any([primary_thumbprint, secondary_thumbprint]):
                raise RequiredArgumentMissingError(
                    "primary or secondary Thumbprint required with selfSigned auth"
                )
            if primary_thumbprint:
                instance["authentication"]["x509Thumbprint"][
                    "primaryThumbprint"
                ] = primary_thumbprint
            if secondary_thumbprint:
                instance["authentication"]["x509Thumbprint"][
                    "secondaryThumbprint"
                ] = secondary_thumbprint
        elif auth_method == DeviceAuthType.x509_ca.name:
            auth = DeviceAuthApiType.certificateAuthority.value
        else:
            raise ValueError("Authorization method {} invalid.".format(auth_method))
        instance["authentication"]["type"] = auth

    # if no new auth_method is provided, validate secondary auth arguments and update accordingly
    elif auth_type == DeviceAuthApiType.sas.value:
        if any([primary_thumbprint, secondary_thumbprint]):
            raise ValueError(
                "Device authorization method {} does not support primary or secondary thumbprints.".format(
                    DeviceAuthType.shared_private_key.name
                )
            )
        if primary_key:
            instance["authentication"]["symmetricKey"]["primaryKey"] = primary_key
        if secondary_key:
            instance["authentication"]["symmetricKey"]["secondaryKey"] = secondary_key

    elif auth_type == DeviceAuthApiType.selfSigned.value:
        if any([primary_key, secondary_key]):
            raise ValueError(
                "Device authorization method {} does not support primary or secondary keys.".format(
                    DeviceAuthType.x509_thumbprint.name
                )
            )
        if primary_thumbprint:
            instance["authentication"]["x509Thumbprint"][
                "primaryThumbprint"
            ] = primary_thumbprint
        if secondary_thumbprint:
            instance["authentication"]["x509Thumbprint"][
                "secondaryThumbprint"
            ] = secondary_thumbprint
    return instance


def iot_device_update(
    cmd,
    device_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )

    auth, pk, sk = _parse_auth(parameters)
    updated_device = _assemble_device(
        True,
        parameters["deviceId"],
        auth,
        parameters["capabilities"]["iotEdge"],
        pk,
        sk,
        parameters["status"].lower(),
        parameters.get("statusReason"),
        parameters.get("deviceScope"),
    )
    updated_device.etag = etag if etag else "*"
    return _iot_device_update(target, device_id, updated_device)


def _iot_device_update(target, device_id, device):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(device.etag)
        return service_sdk.devices.create_or_update_identity(
            id=device_id, device=device, custom_headers=headers
        )
    except CloudError as e:
        handle_service_exception(e)


def iot_device_delete(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        service_sdk.devices.delete_identity(id=device_id, custom_headers=headers)
        return
    except CloudError as e:
        handle_service_exception(e)


def _update_device_key(target, device, auth_method, pk, sk, etag=None):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        auth = _assemble_auth(auth_method, pk, sk)
        device["authentication"] = auth
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        return service_sdk.devices.create_or_update_identity(
            id=device["deviceId"],
            device=device,
            custom_headers=headers,
        )
    except CloudError as e:
        handle_service_exception(e)


def iot_device_key_regenerate(
    cmd,
    hub_name,
    device_id,
    renew_key_type,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    device = _iot_device_show(target, device_id)
    if device["authentication"]["type"] != DeviceAuthApiType.sas.value:
        raise ClientRequestError("Device authentication should be of type sas")

    pk = device["authentication"]["symmetricKey"]["primaryKey"]
    sk = device["authentication"]["symmetricKey"]["secondaryKey"]

    if renew_key_type == RenewKeyType.primary.value:
        pk = generate_key()
    if renew_key_type == RenewKeyType.secondary.value:
        sk = generate_key()
    if renew_key_type == RenewKeyType.swap.value:
        temp = pk
        pk = sk
        sk = temp

    return _update_device_key(
        target, device, device["authentication"]["type"], pk, sk, etag
    )


def iot_device_get_parent(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    child_device = _iot_device_show(target, device_id)
    _validate_child_device(child_device)
    parent_scope = child_device["parentScopes"][0]
    parent_device_id = parent_scope[
        len(DEVICE_DEVICESCOPE_PREFIX) : parent_scope.rindex("-")
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
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    parent_device = _iot_device_show(target, parent_id)
    _validate_edge_device(parent_device)
    child_device = _iot_device_show(target, device_id)
    _validate_parent_child_relation(child_device, force)

    _update_device_parent(
        target,
        child_device,
        child_device["capabilities"]["iotEdge"],
        parent_device["deviceScope"],
    )


def iot_device_children_add(
    cmd,
    device_id,
    child_list,
    force=False,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    devices = []
    edge_device = _iot_device_show(target, device_id)
    _validate_edge_device(edge_device)
    converted_child_list = child_list
    for child_device_id in converted_child_list:
        child_device = _iot_device_show(target, child_device_id.strip())
        _validate_parent_child_relation(child_device, force)
        devices.append(child_device)

    for device in devices:
        _update_device_parent(
            target,
            device,
            device["capabilities"]["iotEdge"],
            edge_device["deviceScope"],
        )


def iot_device_children_remove(
    cmd,
    device_id,
    child_list=None,
    remove_all=False,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    devices = []
    if remove_all:
        result = _iot_device_children_list(
            cmd, device_id, hub_name, resource_group_name, login
        )
        if not result:
            raise ClientRequestError(
                'No registered child devices found for "{}" edge device.'.format(
                    device_id
                )
            )
        for child_device_id in [str(x["deviceId"]) for x in result]:
            child_device = _iot_device_show(target, child_device_id.strip())
            devices.append(child_device)
    elif child_list:
        edge_device = _iot_device_show(target, device_id)
        _validate_edge_device(edge_device)
        converted_child_list = child_list
        for child_device_id in converted_child_list:
            child_device = _iot_device_show(target, child_device_id.strip())
            _validate_child_device(child_device)
            if child_device["parentScopes"] == [edge_device["deviceScope"]]:
                devices.append(child_device)
            else:
                raise ClientRequestError(
                    'The entered child device "{}" isn\'t assigned as a child of edge device "{}"'.format(
                        child_device_id.strip(), device_id
                    )
                )
    else:
        raise RequiredArgumentMissingError(
            "Please specify child list or use --remove-all to remove all children."
        )

    for device in devices:
        _update_device_parent(target, device, device["capabilities"]["iotEdge"])


def iot_device_children_list(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    result = _iot_device_children_list(
        cmd=cmd,
        device_id=device_id,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )

    return [device["deviceId"] for device in result]


def _iot_device_children_list(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    device = _iot_device_show(target, device_id)
    _validate_edge_device(device)
    query = (
        "select deviceId from devices where array_contains(parentScopes, '{}')".format(
            device["deviceScope"]
        )
    )

    # TODO: Inefficient
    return iot_query(
        cmd=cmd,
        query_command=query,
        hub_name=hub_name,
        top=None,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )


def _update_device_parent(target, device, is_edge, device_scope=None):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        if is_edge:
            parent_scopes = []
            if device_scope:
                parent_scopes = [device_scope]
            device["parentScopes"] = parent_scopes
        else:
            if not device_scope:
                device_scope = ""
            device["deviceScope"] = device_scope
        etag = device.get("etag", None)
        if etag:
            headers = {}
            headers["If-Match"] = '"{}"'.format(etag)
            service_sdk.devices.create_or_update_identity(
                id=device["deviceId"],
                device=device,
                custom_headers=headers,
            )
            return
        raise LookupError("device etag not found.")
    except CloudError as e:
        handle_service_exception(e)
    except LookupError as err:
        raise CLIInternalError(err)


def _validate_edge_device(device):
    if not device["capabilities"]["iotEdge"]:
        raise ClientRequestError(
            'The device "{}" should be an edge device.'.format(device["deviceId"])
        )


def _validate_child_device(device):
    if "parentScopes" not in device:
        raise ClientRequestError(
            'Device "{}" doesn\'t support parent device functionality.'.format(
                device["deviceId"]
            )
        )
    if not device["parentScopes"]:
        raise ClientRequestError(
            'Device "{}" doesn\'t have any parent device.'.format(device["deviceId"])
        )


def _validate_parent_child_relation(child_device, force):
    if "parentScopes" not in child_device or child_device["parentScopes"] == []:
        return
    else:
        if not force:
            raise ClientRequestError(
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
    auth_method=DeviceAuthType.shared_private_key.value,
    primary_key=None,
    secondary_key=None,
    primary_thumbprint=None,
    secondary_thumbprint=None,
    valid_days=None,
    output_dir=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):

    if any([valid_days, output_dir]):
        valid_days = 365 if not valid_days else int(valid_days)
        if output_dir and not exists(output_dir):
            raise FileOperationError(
                "certificate output directory of '{}' does not exist.".format(
                    output_dir
                )
            )
        cert = _create_self_signed_cert(module_id, valid_days, output_dir)
        primary_thumbprint = cert["thumbprint"]

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        module = _assemble_module(
            device_id=device_id,
            module_id=module_id,
            auth_method=auth_method,
            pk=primary_thumbprint if auth_method == DeviceAuthType.x509_thumbprint.value else primary_key,
            sk=secondary_thumbprint if auth_method == DeviceAuthType.x509_thumbprint.value else secondary_key,
        )
        return service_sdk.modules.create_or_update_identity(
            id=device_id, mid=module_id, module=module
        )
    except CloudError as e:
        handle_service_exception(e)
    except ValueError as ve:
        raise InvalidArgumentValueError(ve)


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
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        updated_module = _handle_module_update_params(parameters)
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        return service_sdk.modules.create_or_update_identity(
            id=device_id,
            mid=module_id,
            module=updated_module,
            custom_headers=headers,
        )
    except CloudError as e:
        handle_service_exception(e)


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
    valid_auth = [
        DeviceAuthApiType.sas.value,
        DeviceAuthApiType.selfSigned.value,
        DeviceAuthApiType.certificateAuthority.value,
    ]
    auth = parameters["authentication"].get("type")
    if auth not in valid_auth:
        raise InvalidArgumentValueError("authentication.type must be one of {}".format(valid_auth))
    pk = sk = None
    if auth == DeviceAuthApiType.sas.value:
        pk = parameters["authentication"]["symmetricKey"]["primaryKey"]
        sk = parameters["authentication"]["symmetricKey"]["secondaryKey"]
    elif auth == DeviceAuthApiType.selfSigned.value:
        pk = parameters["authentication"]["x509Thumbprint"]["primaryThumbprint"]
        sk = parameters["authentication"]["x509Thumbprint"]["secondaryThumbprint"]
        if not any([pk, sk]):
            raise RequiredArgumentMissingError(
                "primary + secondary Thumbprint required with selfSigned auth"
            )
    return auth, pk, sk


def iot_device_module_key_regenerate(
    cmd,
    hub_name,
    device_id,
    module_id,
    renew_key_type,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)
    try:
        module = service_sdk.modules.get_identity(
            id=device_id, mid=module_id, raw=True
        ).response.json()
    except CloudError as e:
        handle_service_exception(e)

    if module["authentication"]["type"] != "sas":
        raise ClientRequestError("Module authentication should be of type sas")

    pk = module["authentication"]["symmetricKey"]["primaryKey"]
    sk = module["authentication"]["symmetricKey"]["secondaryKey"]

    if renew_key_type == RenewKeyType.primary.value:
        pk = generate_key()
    if renew_key_type == RenewKeyType.secondary.value:
        sk = generate_key()
    if renew_key_type == RenewKeyType.swap.value:
        temp = pk
        pk = sk
        sk = temp

    module["authentication"]["symmetricKey"]["primaryKey"] = pk
    module["authentication"]["symmetricKey"]["secondaryKey"] = sk

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        return service_sdk.modules.create_or_update_identity(
            id=device_id,
            mid=module_id,
            module=module,
            custom_headers=headers,
        )
    except CloudError as e:
        handle_service_exception(e)


def iot_device_module_list(
    cmd,
    device_id,
    hub_name=None,
    top=1000,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.modules.get_modules_on_device(device_id)[:top]
    except CloudError as e:
        handle_service_exception(e)


def iot_device_module_show(
    cmd,
    device_id,
    module_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_device_module_show(target, device_id, module_id)


def _iot_device_module_show(target, device_id, module_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        module = service_sdk.modules.get_identity(
            id=device_id, mid=module_id, raw=True
        ).response.json()
        module["hub"] = target.get("entity")
        return module
    except CloudError as e:
        handle_service_exception(e)


def iot_device_module_delete(
    cmd,
    device_id,
    module_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        service_sdk.modules.delete_identity(
            id=device_id, mid=module_id, custom_headers=headers
        )
        return
    except CloudError as e:
        handle_service_exception(e)


def iot_device_module_twin_show(
    cmd,
    device_id,
    module_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_device_module_twin_show(
        target=target, device_id=device_id, module_id=module_id
    )


def _iot_device_module_twin_show(target, device_id, module_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.modules.get_twin(
            id=device_id, mid=module_id, raw=True
        ).response.json()
    except CloudError as e:
        handle_service_exception(e)


def iot_device_module_twin_update(
    cmd,
    device_id,
    module_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    from azext_iot.common.utility import verify_transform

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        verify = {}
        if parameters.get("properties"):
            if parameters["properties"].get("desired"):
                verify = {"properties.desired": dict}
        if parameters.get("tags"):
            verify["tags"] = dict
        verify_transform(parameters, verify)
        return service_sdk.modules.update_twin(
            id=device_id,
            mid=module_id,
            device_twin_info=parameters,
            custom_headers=headers,
        )
    except CloudError as e:
        handle_service_exception(e)
    except (AttributeError, TypeError) as err:
        raise CLIInternalError(err)


def iot_device_module_twin_replace(
    cmd,
    device_id,
    module_id,
    target_json,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        target_json = process_json_arg(target_json, argument_name="json")
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        return service_sdk.modules.replace_twin(
            id=device_id,
            mid=module_id,
            device_twin_info=target_json,
            custom_headers=headers,
        )
    except CloudError as e:
        handle_service_exception(e)


def iot_edge_set_modules(
    cmd,
    device_id,
    content,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    from azext_iot.sdk.iothub.service.models import ConfigurationContent

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
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
        handle_service_exception(e)


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
    no_validation=False,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    # Short-term fix for --no-validation
    config_type = ConfigType.layered if layered or no_validation else ConfigType.edge
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
        auth_type_dataplane=auth_type_dataplane,
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
    auth_type_dataplane=None,
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
        auth_type_dataplane=auth_type_dataplane,
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
    auth_type_dataplane=None,
):
    from azext_iot.sdk.iothub.service.models import (
        Configuration,
        ConfigurationContent,
        ConfigurationMetrics,
    )

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
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
            raise InvalidArgumentValueError(
                "The target condition for a module configuration must start with '{}'".format(
                    required_target_prefix
                )
            )

    if metrics:
        metrics = process_json_arg(metrics, argument_name="metrics")

        if "metrics" in metrics:
            metrics = metrics["metrics"]
        if metrics_key not in metrics:
            raise InvalidArgumentValueError(
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
    )

    try:
        return service_sdk.configuration.create_or_update(
            id=config_id, configuration=config
        )
    except CloudError as e:
        handle_service_exception(e)


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

        raise InvalidArgumentValueError(
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

        raise InvalidArgumentValueError(
            "Edge deployment payloads require property: {}".format(valid_edge_key)
        )


def _validate_payload_schema(content):
    import json
    from os.path import join
    from azext_iot.models.validators import JsonSchemaType, JsonSchemaValidator
    from azext_iot.constants import EDGE_DEPLOYMENT_ROOT_SCHEMAS_PATH as root_schema_path
    from azext_iot.common.utility import shell_safe_json_parse

    EDGE_AGENT_SCHEMA_PATH = "azure-iot-edgeagent-deployment-{}.json"
    EDGE_HUB_SCHEMA_PATH = "azure-iot-edgehub-deployment-{}.json"
    EDGE_SCHEMA_PATH_DICT = {
        "$edgeAgent": EDGE_AGENT_SCHEMA_PATH,
        "$edgeHub": EDGE_HUB_SCHEMA_PATH,
    }

    modules_content = content["modulesContent"]
    system_modules_for_validation = ["$edgeAgent", "$edgeHub"]

    for sys_module in system_modules_for_validation:
        if sys_module in modules_content:
            if (
                "properties.desired" in modules_content[sys_module]
                and "schemaVersion"
                in modules_content[sys_module]["properties.desired"]
            ):
                target_schema_ver = modules_content[sys_module][
                    "properties.desired"
                ]["schemaVersion"]
                target_schema_def_path = join(root_schema_path, f"{EDGE_SCHEMA_PATH_DICT[sys_module].format(target_schema_ver)}")

                logger.info("Attempting to fetch schema content from %s...", target_schema_def_path)
                if not exists(target_schema_def_path):
                    logger.info("Invalid schema path %s, skipping validation...", target_schema_def_path)
                    continue

                try:
                    target_schema_def = str(read_file_content(target_schema_def_path))
                    target_schema_def = shell_safe_json_parse(target_schema_def)
                except Exception:
                    logger.info(
                        "Unable to fetch schema content from %s skipping validation...",
                        target_schema_def_path,
                    )
                    continue

                logger.info(f"Validating {sys_module} of deployment payload against schema...")
                to_validate_content = {
                    sys_module: modules_content[sys_module]
                }
                draft_version = JsonSchemaType.draft4
                if "$schema" in target_schema_def and "/draft-07/" in target_schema_def["$schema"]:
                    draft_version = JsonSchemaType.draft7

                v = JsonSchemaValidator(target_schema_def, draft_version)
                errors = v.validate(to_validate_content)
                if errors:
                    # Pretty printing schema validation errors
                    raise ValidationError(
                        json.dumps(
                            {"validationErrors": errors},
                            separators=(",", ":"),
                            indent=2,
                        )
                    )


def iot_hub_configuration_update(
    cmd,
    config_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    from azext_iot.sdk.iothub.service.models import Configuration
    from azext_iot.common.utility import verify_transform

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
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
        )
        return service_sdk.configuration.create_or_update(
            id=config_id, configuration=config, custom_headers=headers
        )
    except CloudError as e:
        handle_service_exception(e)
    except (AttributeError, TypeError) as err:
        raise CLIInternalError(err)


def iot_hub_configuration_show(
    cmd,
    config_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_hub_configuration_show(target=target, config_id=config_id)


def _iot_hub_configuration_show(target, config_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.configuration.get(id=config_id, raw=True).response.json()
    except CloudError as e:
        handle_service_exception(e)


def iot_hub_configuration_list(
    cmd,
    hub_name=None,
    top=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    result = _iot_hub_configuration_list(
        cmd=cmd,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    filtered = [
        c
        for c in result
        if (
            c["content"].get("deviceContent") is not None
            or c["content"].get("moduleContent") is not None
        )
    ]
    return filtered[:top]  # list[:None] == list[:len(list)]


def iot_edge_deployment_list(
    cmd,
    hub_name=None,
    top=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    result = _iot_hub_configuration_list(
        cmd,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )

    filtered = [c for c in result if c["content"].get("modulesContent") is not None]
    return filtered[:top]  # list[:None] == list[:len(list)]


def _iot_hub_configuration_list(
    cmd, hub_name=None, resource_group_name=None, login=None, auth_type_dataplane=None
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        result = service_sdk.configuration.get_configurations(raw=True).response.json()
        if not result:
            logger.info('No configurations found on hub "%s".', hub_name)
        return result
    except CloudError as e:
        handle_service_exception(e)


def iot_hub_configuration_delete(
    cmd,
    config_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        service_sdk.configuration.delete(id=config_id, custom_headers=headers)
    except CloudError as e:
        handle_service_exception(e)


def iot_edge_deployment_metric_show(
    cmd,
    config_id,
    metric_id,
    metric_type="user",
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    return iot_hub_configuration_metric_show(
        cmd,
        config_id=config_id,
        metric_id=metric_id,
        metric_type=metric_type,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )


def iot_hub_configuration_metric_show(
    cmd,
    config_id,
    metric_id,
    metric_type="user",
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
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
            raise InvalidArgumentValueError(
                "The {} metric '{}' is not defined in the configuration '{}'".format(
                    metric_type, metric_id, config_id
                )
            )

        metric_query = metric_collection[metric_id]

        query_args = [metric_query]
        query_method = service_sdk.query.get_twins

        metric_result = _execute_query(query_args, query_method, None)

        output = {}
        output["metric"] = metric_id
        output["query"] = metric_query
        output["result"] = metric_result

        return output
    except CloudError as e:
        handle_service_exception(e)


# Device Twin


def iot_device_twin_show(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_device_twin_show(target=target, device_id=device_id)


def _iot_device_twin_show(target, device_id):
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        return service_sdk.devices.get_twin(id=device_id, raw=True).response.json()
    except CloudError as e:
        handle_service_exception(e)


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
    cmd,
    device_id,
    parameters,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    return _iot_device_twin_update(target, device_id, parameters, etag)


def _iot_device_twin_update(
    target,
    device_id,
    parameters,
    etag=None,
):
    from azext_iot.common.utility import verify_transform

    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        verify = {}
        if parameters.get("properties"):
            if parameters["properties"].get("desired"):
                verify = {"properties.desired": dict}
        if parameters.get("tags"):
            verify["tags"] = dict
        verify_transform(parameters, verify)
        return service_sdk.devices.update_twin(
            id=device_id, device_twin_info=parameters, custom_headers=headers
        )
    except CloudError as e:
        handle_service_exception(e)
    except (AttributeError, TypeError) as err:
        raise CLIInternalError(err)


def iot_device_twin_replace(
    cmd,
    device_id,
    target_json,
    hub_name=None,
    resource_group_name=None,
    login=None,
    etag=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    try:
        target_json = process_json_arg(target_json, argument_name="json")
        headers = {}
        headers["If-Match"] = '"{}"'.format(etag if etag else "*")
        return service_sdk.devices.replace_twin(
            id=device_id, device_twin_info=target_json, custom_headers=headers
        )
    except CloudError as e:
        handle_service_exception(e)


def iot_device_method(
    cmd,
    device_id,
    method_name,
    hub_name=None,
    method_payload="{}",
    timeout=30,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    from azext_iot.constants import (
        METHOD_INVOKE_MAX_TIMEOUT_SEC,
        METHOD_INVOKE_MIN_TIMEOUT_SEC,
    )

    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise InvalidArgumentValueError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MAX_TIMEOUT_SEC)
        )
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise InvalidArgumentValueError(
            "timeout must be at least {} seconds".format(METHOD_INVOKE_MIN_TIMEOUT_SEC)
        )

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
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

        request_body = {
            "methodName": method_name,
            "payload": method_payload,
            "responseTimeoutInSeconds": timeout,
            "connectTimeoutInSeconds": timeout,
        }

        return service_sdk.devices.invoke_method(
            device_id=device_id,
            direct_method_request=request_body,
            timeout=timeout,
        )
    except CloudError as e:
        handle_service_exception(e)


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
    auth_type_dataplane=None,
):
    from azext_iot.constants import (
        METHOD_INVOKE_MAX_TIMEOUT_SEC,
        METHOD_INVOKE_MIN_TIMEOUT_SEC,
    )

    if timeout > METHOD_INVOKE_MAX_TIMEOUT_SEC:
        raise InvalidArgumentValueError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MAX_TIMEOUT_SEC)
        )
    if timeout < METHOD_INVOKE_MIN_TIMEOUT_SEC:
        raise InvalidArgumentValueError(
            "timeout must not be over {} seconds".format(METHOD_INVOKE_MIN_TIMEOUT_SEC)
        )

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
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

        request_body = {
            "methodName": method_name,
            "payload": method_payload,
            "responseTimeoutInSeconds": timeout,
            "connectTimeoutInSeconds": timeout,
        }

        return service_sdk.modules.invoke_method(
            device_id=device_id,
            module_id=module_id,
            direct_method_request=request_body,
            timeout=timeout,
        )
    except CloudError as e:
        handle_service_exception(e)


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
    auth_type_dataplane=None,
    connection_string=None,
):
    key_type = key_type.lower()
    policy_name = policy_name.lower()

    if login and policy_name != "iothubowner":
        raise ArgumentUsageError(
            "You are unable to change the sas policy with a hub connection string login."
        )
    if login and key_type != "primary" and not device_id:
        raise ArgumentUsageError(
            "For non-device sas, you are unable to change the key type with a connection string login."
        )
    if module_id and not device_id:
        raise ArgumentUsageError(
            "You are unable to get sas token for module without device information."
        )

    if connection_string:
        return {
            DeviceAuthApiType.sas.value: _iot_build_sas_token_from_cs(
                connection_string,
                duration,
            ).generate_sas_token()
        }

    return {
        DeviceAuthApiType.sas.value: _iot_build_sas_token(
            cmd,
            hub_name,
            device_id,
            module_id,
            policy_name,
            key_type,
            duration,
            resource_group_name,
            login,
            auth_type_dataplane,
        ).generate_sas_token()
    }


def _iot_build_sas_token_from_cs(connection_string, duration=3600):
    uri = None
    policy = None
    key = None

    parsed_cs = None
    all_parsers = [
        ConnectionStringParser.Module,
        ConnectionStringParser.Device,
        ConnectionStringParser.IotHub,
    ]

    for parser in all_parsers:
        try:
            parsed_cs = parser(connection_string)

            if "SharedAccessKeyName" in parsed_cs:
                policy = parsed_cs["SharedAccessKeyName"]
            key = parsed_cs["SharedAccessKey"]

            if parser == ConnectionStringParser.IotHub:
                uri = parsed_cs["HostName"]
            elif parser == ConnectionStringParser.Module:
                uri = "{}/devices/{}/modules/{}".format(
                    parsed_cs["HostName"], parsed_cs["DeviceId"], parsed_cs["ModuleId"]
                )
            elif parser == ConnectionStringParser.Device:
                uri = "{}/devices/{}".format(parsed_cs["HostName"], parsed_cs["DeviceId"])
            else:
                raise InvalidArgumentValueError("Given Connection String was not in a supported format.")

            return SasTokenAuthentication(uri, policy, key, duration)
        except ValueError:
            continue

    raise InvalidArgumentValueError("Given Connection String was not in a supported format.")


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
    auth_type_dataplane=None,
):
    from azext_iot.common._azure import (
        parse_iot_device_connection_string,
        parse_iot_device_module_connection_string,
    )

    # There is no dataplane operation for a pure IoT Hub sas token
    if all([device_id is None, module_id is None]):
        auth_type_dataplane = "key"

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        policy_name=policy_name,
        login=login,
        auth_type=auth_type_dataplane,
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
                raise CLIInternalError("This module does not support SAS auth.")

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
                raise CLIInternalError("This device does not support SAS auth.")

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
    if auth_type == DeviceAuthApiType.sas.value.lower():
        key = "SharedAccessKey={}".format(
            auth["symmetricKey"]["primaryKey"]
            if key_type == "primary"
            else auth["symmetricKey"]["secondaryKey"]
        )
    elif auth_type in [
        DeviceAuthApiType.certificateAuthority.value.lower(),
        DeviceAuthApiType.selfSigned.value.lower(),
    ]:
        key = "x509=true"
    else:
        raise CLIInternalError("Unable to form target connection string")

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
    auth_type_dataplane=None,
):
    result = {}
    device = iot_device_show(
        cmd,
        device_id,
        hub_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
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
    auth_type_dataplane=None,
):
    result = {}
    module = iot_device_module_show(
        cmd,
        device_id,
        module_id,
        resource_group_name=resource_group_name,
        hub_name=hub_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
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
    login=None
):
    from azext_iot.operations._mqtt import mqtt_client
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
    )
    if properties:
        properties = validate_key_value_pairs(properties)
    device = _iot_device_show(target, device_id)
    device_connection_string = _build_device_or_module_connection_string(device, KeyType.primary.value)
    device_auth_api_type = device.get("authentication", {}).get("type", "") if device else None
    client_mqtt = mqtt_client(
        target=target,
        device_conn_string=device_connection_string,
        device_id=device_id,
        device_auth_api_type=device_auth_api_type
    )
    for _ in range(msg_count):
        client_mqtt.send_d2c_message(message_text=data, properties=properties)
    client_mqtt.shutdown()


def iot_device_send_message_http(
    cmd,
    device_id,
    data,
    hub_name=None,
    headers=None,
    resource_group_name=None,
    login=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
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
        handle_service_exception(e)


def iot_c2d_message_complete(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
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
        handle_service_exception(e)


def iot_c2d_message_reject(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
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
        handle_service_exception(e)


def iot_c2d_message_abandon(
    cmd, device_id, etag, hub_name=None, resource_group_name=None, login=None
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
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
        handle_service_exception(e)


def iot_c2d_message_receive(
    cmd,
    device_id,
    hub_name=None,
    lock_timeout=60,
    resource_group_name=None,
    login=None,
    abandon=None,
    complete=None,
    reject=None,
):
    ack = None
    ack_vals = [abandon, complete, reject]
    if any(ack_vals):
        if len(list(filter(lambda val: val, ack_vals))) > 1:
            raise MutuallyExclusiveArgumentError(
                "Only one c2d-message ack argument can be used [--complete, --abandon, --reject]"
            )
        if abandon:
            ack = SettleType.abandon.value
        elif complete:
            ack = SettleType.complete.value
        elif reject:
            ack = SettleType.reject.value

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
    )
    return _iot_c2d_message_receive(target, device_id, lock_timeout, ack)


def _iot_c2d_message_receive(target, device_id, lock_timeout=60, ack=None):
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
                eTag = result.headers["etag"].strip('"')
                payload["etag"] = eTag

                if ack:
                    ack_response = {}
                    if ack == SettleType.abandon.value:
                        logger.debug("__Abandoning message__")
                        ack_response = (
                            device_sdk.device.abandon_device_bound_notification(
                                id=device_id, etag=eTag, raw=True
                            )
                        )
                    elif ack == SettleType.reject.value:
                        logger.debug("__Rejecting message__")
                        ack_response = (
                            device_sdk.device.complete_device_bound_notification(
                                id=device_id, etag=eTag, reject="", raw=True
                            )
                        )
                    else:
                        logger.debug("__Completing message__")
                        ack_response = (
                            device_sdk.device.complete_device_bound_notification(
                                id=device_id, etag=eTag, raw=True
                            )
                        )

                    payload["ack"] = (
                        ack
                        if (ack_response and ack_response.response.status_code == 204)
                        else None
                    )

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

            if result.content:
                target_encoding = result.headers.get("ContentEncoding", "utf-8")
                logger.info(f"Decoding message data encoded with: {target_encoding}")
                payload["data"] = result.content.decode(target_encoding)

            return payload
        return
    except CloudError as e:
        handle_service_exception(e)


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
    auth_type_dataplane=None,
):
    from azext_iot.common.deps import ensure_uamqp

    if wait_on_feedback and not ack:
        raise RequiredArgumentMissingError(
            'To wait on device feedback, ack must be "full", "negative" or "positive"'
        )

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )

    if properties:
        properties = validate_key_value_pairs(properties)

    if expiry_time_utc:
        now_in_milli = int(time() * 1000)
        user_msg_expiry = int(expiry_time_utc)
        if user_msg_expiry < now_in_milli:
            raise InvalidArgumentValueError("Message expiry time utc is in the past!")

    from azext_iot.monitor import event

    msg_id, errors = event.send_c2d_message(
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
        raise CLIInternalError(
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
    method_response_code=None,
    method_response_payload=None,
    init_reported_properties=None
):
    import sys
    import uuid
    import datetime
    import json
    from azext_iot.operations._mqtt import mqtt_client
    from threading import Event, Thread
    from tqdm import tqdm
    from azext_iot.constants import (
        MIN_SIM_MSG_INTERVAL,
        MIN_SIM_MSG_COUNT,
        SIM_RECEIVE_SLEEP_SEC,
    )

    protocol_type = protocol_type.lower()
    if protocol_type == ProtocolType.mqtt.name:
        if receive_settle != "complete":
            raise InvalidArgumentValueError('mqtt protocol only supports settle type of "complete"')

    if msg_interval < MIN_SIM_MSG_INTERVAL:
        raise InvalidArgumentValueError("msg interval must be at least {}".format(MIN_SIM_MSG_INTERVAL))

    if msg_count < MIN_SIM_MSG_COUNT:
        raise InvalidArgumentValueError("msg count must be at least {}".format(MIN_SIM_MSG_COUNT))

    if protocol_type != ProtocolType.mqtt.name:
        if method_response_code:
            raise ArgumentUsageError("'method-response-code' not supported, {} doesn't allow direct methods."
                                     .format(protocol_type))
        if method_response_payload:
            raise ArgumentUsageError("'method-response-payload' not supported, {} doesn't allow direct methods."
                                     .format(protocol_type))
        if init_reported_properties:
            raise ArgumentUsageError("'init-reported-properties' not supported, {} doesn't allow setting twin props"
                                     .format(protocol_type))

    properties_to_send = _iot_simulate_get_default_properties(protocol_type)
    user_properties = validate_key_value_pairs(properties) or {}
    properties_to_send.update(user_properties)

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
    )

    if method_response_payload:
        method_response_payload = process_json_arg(
            method_response_payload, argument_name="method-response-payload"
        )

    if init_reported_properties:
        init_reported_properties = process_json_arg(
            init_reported_properties, argument_name="init-reported-properties"
        )

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

    cancellation_token = Event()

    def http_wrap(target, device_id, generator, msg_interval, msg_count):
        for _ in tqdm(range(0, msg_count), desc='Sending and receiving events via https', ascii=' #'):
            d = generator.generate(False)
            _iot_device_send_message_http(target, device_id, d, headers=properties_to_send)
            if cancellation_token.wait(msg_interval):
                break
    try:
        device = _iot_device_show(target, device_id)
        if protocol_type == ProtocolType.mqtt.name:
            device_connection_string = _build_device_or_module_connection_string(device, KeyType.primary.value)
            device_auth_api_type = device.get("authentication", {}).get("type", "") if device else None

            client_mqtt = mqtt_client(
                target=target,
                device_conn_string=device_connection_string,
                device_id=device_id,
                device_auth_api_type=device_auth_api_type,
                method_response_code=method_response_code,
                method_response_payload=method_response_payload,
                init_reported_properties=init_reported_properties
            )
            client_mqtt.execute(data=generator(), properties=properties_to_send, publish_delay=msg_interval, msg_count=msg_count)
            client_mqtt.shutdown()
        else:
            op = Thread(target=http_wrap, args=(target, device_id, generator(), msg_interval, msg_count))
            op.start()

            while op.is_alive():
                _handle_c2d_msg(target, device_id, receive_settle)
                sleep(SIM_RECEIVE_SLEEP_SEC)

    except KeyboardInterrupt:
        sys.exit()
    except Exception as x:
        raise CLIInternalError(x)
    finally:
        if cancellation_token:
            cancellation_token.set()


def iot_c2d_message_purge(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
    )
    resolver = SdkResolver(target=target)
    service_sdk = resolver.get_sdk(SdkType.service_sdk)

    return service_sdk.cloud_to_device_messages.purge_cloud_to_device_message_queue(
        device_id
    )


def _iot_simulate_get_default_properties(protocol):
    default_properties = {}
    is_mqtt = protocol == ProtocolType.mqtt.name

    default_properties["$.ct" if is_mqtt else "content-type"] = "application/json"
    default_properties["$.ce" if is_mqtt else "content-encoding"] = "utf-8"

    return default_properties


def _handle_c2d_msg(target, device_id, receive_settle, lock_timeout=60):
    result = _iot_c2d_message_receive(target, device_id, lock_timeout)
    if result:
        print()
        print("C2D Message Handler [Received C2D message]:")
        printer.pprint(result)
        if receive_settle == "reject":
            print("C2D Message Handler [Rejecting message]")
            _iot_c2d_message_reject(target, device_id, result["etag"])
        elif receive_settle == "abandon":
            print("C2D Message Handler [Abandoning message]")
            _iot_c2d_message_abandon(target, device_id, result["etag"])
        else:
            print("C2D Message Handler [Completing message]")
            _iot_c2d_message_complete(target, device_id, result["etag"])
        return True
    return False


def iot_device_export(
    cmd,
    hub_name,
    blob_container_uri,
    include_keys=False,
    storage_authentication_type=None,
    identity=None,
    resource_group_name=None,
):
    from azext_iot._factory import iot_hub_service_factory

    client = iot_hub_service_factory(cmd.cli_ctx)
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name
    )

    if exists(blob_container_uri):
        blob_container_uri = read_file_content(blob_container_uri)

    if ensure_iothub_sdk_min_version("0.12.0"):
        from azure.mgmt.iothub.models import ExportDevicesRequest
        from azext_iot.common.shared import AuthenticationType

        storage_authentication_type = (
            AuthenticationType(storage_authentication_type).name
            if storage_authentication_type
            else None
        )

        export_request = ExportDevicesRequest(
            export_blob_container_uri=blob_container_uri,
            exclude_keys=not include_keys,
            authentication_type=storage_authentication_type,
        )

        user_identity = identity not in [None, "[system]"]
        if (
            user_identity
            and storage_authentication_type != AuthenticationType.identityBased.name
        ):
            raise ClientRequestError(
                "Device export with user-assigned identities requires identity-based authentication [--storage-auth-type]"
            )
        # Track 2 CLI SDKs provide support for user-assigned identity objects
        if (
            ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION)
            and user_identity
        ):
            from azure.mgmt.iothub.models import (
                ManagedIdentity,
            )  # pylint: disable=no-name-in-module

            export_request.identity = ManagedIdentity(user_assigned_identity=identity)

        # if the user supplied a user-assigned identity, let them know they need a new CLI/SDK
        elif user_identity:
            raise CLIInternalError(
                "Device export with user-assigned identities requires a dependency of azure-mgmt-iothub>={}".format(
                    IOTHUB_TRACK_2_SDK_MIN_VERSION
                )
            )

        return client.export_devices(
            target["resourcegroup"],
            hub_name,
            export_devices_parameters=export_request,
        )
    if storage_authentication_type:
        raise CLIInternalError(
            "Device export authentication-type properties require a dependency of azure-mgmt-iothub>=0.12.0"
        )
    return client.export_devices(
        target["resourcegroup"],
        hub_name,
        export_blob_container_uri=blob_container_uri,
        exclude_keys=not include_keys,
    )


def iot_device_import(
    cmd,
    hub_name,
    input_blob_container_uri,
    output_blob_container_uri,
    storage_authentication_type=None,
    resource_group_name=None,
    identity=None,
):
    from azext_iot._factory import iot_hub_service_factory

    client = iot_hub_service_factory(cmd.cli_ctx)
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name
    )

    if exists(input_blob_container_uri):
        input_blob_container_uri = read_file_content(input_blob_container_uri)

    if exists(output_blob_container_uri):
        output_blob_container_uri = read_file_content(output_blob_container_uri)

    if ensure_iothub_sdk_min_version("0.12.0"):
        from azure.mgmt.iothub.models import ImportDevicesRequest

        from azext_iot.common.shared import AuthenticationType

        storage_authentication_type = (
            AuthenticationType(storage_authentication_type).name
            if storage_authentication_type
            else None
        )

        import_request = ImportDevicesRequest(
            input_blob_container_uri=input_blob_container_uri,
            output_blob_container_uri=output_blob_container_uri,
            input_blob_name=None,
            output_blob_name=None,
            authentication_type=storage_authentication_type,
        )

        user_identity = identity not in [None, "[system]"]
        if (
            user_identity
            and storage_authentication_type != AuthenticationType.identityBased.name
        ):
            raise ClientRequestError(
                "Device import with user-assigned identities requires identity-based authentication [--storage-auth-type]"
            )
        # Track 2 CLI SDKs provide support for user-assigned identity objects
        if (
            ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION)
            and user_identity
        ):
            from azure.mgmt.iothub.models import (
                ManagedIdentity,
            )  # pylint: disable=no-name-in-module

            import_request.identity = ManagedIdentity(user_assigned_identity=identity)
        # if the user supplied a user-assigned identity, let them know they need a new CLI/SDK
        elif user_identity:
            raise CLIInternalError(
                "Device import with user-assigned identities requires a dependency of azure-mgmt-iothub>={}".format(
                    IOTHUB_TRACK_2_SDK_MIN_VERSION
                )
            )

        return client.import_devices(
            target["resourcegroup"],
            hub_name,
            import_devices_parameters=import_request,
        )
    if storage_authentication_type:
        raise CLIInternalError(
            "Device import authentication-type properties require a dependency of azure-mgmt-iothub>=0.12.0"
        )
    return client.import_devices(
        target["resourcegroup"],
        hub_name,
        input_blob_container_uri=input_blob_container_uri,
        output_blob_container_uri=output_blob_container_uri,
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

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name, resource_group_name=resource_group_name, login=login
    )

    resolver = SdkResolver(target=target, device_id=device_id)
    device_sdk = resolver.get_sdk(SdkType.device_sdk)

    if not exists(file_path):
        raise FileOperationError('File path "{}" does not exist!'.format(file_path))

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
        handle_service_exception(e)


def iot_hub_monitor_events(
    cmd,
    hub_name=None,
    device_id=None,
    interface=None,
    module_id=None,
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
            interface_name=interface,
            module_id=module_id,
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
        raise CLIInternalError(e)


def iot_hub_monitor_feedback(
    cmd,
    hub_name=None,
    device_id=None,
    yes=False,
    wait_on_id=None,
    repair=False,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    from azext_iot.common.deps import ensure_uamqp

    config = cmd.cli_ctx.config
    ensure_uamqp(config, yes, repair)

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )

    return _iot_hub_monitor_feedback(
        target=target, device_id=device_id, wait_on_id=wait_on_id
    )


def iot_hub_distributed_tracing_show(
    cmd,
    hub_name,
    device_id,
    resource_group_name=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        auth_type=auth_type_dataplane,
    )

    device_twin = _iot_hub_distributed_tracing_show(target=target, device_id=device_id)
    return _customize_device_tracing_output(
        device_twin["deviceId"],
        device_twin["properties"]["desired"],
        device_twin["properties"]["reported"],
    )


def _iot_hub_monitor_events(
    cmd,
    interface_name=None,
    module_id=None,
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

    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        include_events=True,
        login=login,
    )

    from azext_iot.monitor.builders import hub_target_builder
    from azext_iot.monitor.handlers import CommonHandler
    from azext_iot.monitor.telemetry import start_single_monitor
    from azext_iot.monitor.utility import generate_on_start_string
    from azext_iot.monitor.models.arguments import (
        CommonParserArguments,
        CommonHandlerArguments,
    )

    target = hub_target_builder.EventTargetBuilder().build_iot_hub_target(target)
    target.add_consumer_group(consumer_group)

    on_start_string = generate_on_start_string(device_id=device_id)

    parser_args = CommonParserArguments(
        properties=properties, content_type=content_type
    )
    handler_args = CommonHandlerArguments(
        output=output,
        common_parser_args=parser_args,
        devices=device_ids,
        device_id=device_id,
        interface_name=interface_name,
        module_id=module_id,
    )

    handler = CommonHandler(handler_args)

    start_single_monitor(
        target=target,
        enqueued_time_utc=enqueued_time,
        on_start_string=on_start_string,
        on_message_received=handler.parse_message,
        timeout=timeout,
    )


def iot_hub_distributed_tracing_update(
    cmd,
    hub_name,
    device_id,
    sampling_mode,
    sampling_rate,
    resource_group_name=None,
    auth_type_dataplane=None,
):
    discovery = IotHubDiscovery(cmd)
    target = discovery.get_target(
        resource_name=hub_name,
        resource_group_name=resource_group_name,
        include_events=True,
        auth_type=auth_type_dataplane,
    )

    if int(sampling_rate) not in range(0, 101):
        raise InvalidArgumentValueError(
            "Sampling rate is a percentage, So only values from 0 to 100(inclusive) are permitted."
        )
    device_twin = _iot_hub_distributed_tracing_show(target=target, device_id=device_id)
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


def iot_hub_connection_string_show(
    cmd,
    hub_name=None,
    resource_group_name=None,
    policy_name="iothubowner",
    key_type=KeyType.primary.value,
    show_all=False,
    default_eventhub=False,
):
    discovery = IotHubDiscovery(cmd)

    if hub_name is None:
        hubs = discovery.get_resources(resource_group_name)
        if hubs is None:
            raise ResourceNotFoundError("No IoT Hub found.")

        def conn_str_getter(hub):
            return _get_hub_connection_string(
                discovery, hub, policy_name, key_type, show_all, default_eventhub
            )

        connection_strings = []
        for hub in hubs:
            if hub.properties.state == IoTHubStateType.Active.value:
                try:
                    connection_strings.append(
                        {
                            "name": hub.name,
                            "connectionString": conn_str_getter(hub)
                            if show_all
                            else conn_str_getter(hub)[0],
                        }
                    )
                except Exception:
                    logger.warning(
                        f"Warning: The IoT Hub {hub.name} in resource group "
                        + f"{hub.additional_properties['resourcegroup']} does "
                        + f"not have the target policy {policy_name}."
                    )
            else:
                logger.warning(
                    f"Warning: The IoT Hub {hub.name} in resource group "
                    + f"{hub.additional_properties['resourcegroup']} is skipped "
                    + "because the hub is not active."
                )
        return connection_strings

    hub = discovery.find_resource(hub_name, resource_group_name)
    if hub:
        conn_str = _get_hub_connection_string(
            discovery, hub, policy_name, key_type, show_all, default_eventhub
        )
        return {"connectionString": conn_str if show_all else conn_str[0]}


def _get_hub_connection_string(
    discovery, hub, policy_name, key_type, show_all, default_eventhub
):

    policies = []
    if show_all:
        policies.extend(
            discovery.get_policies(hub.name, hub.additional_properties["resourcegroup"])
        )
    else:
        policies.append(
            discovery.find_policy(
                hub.name, hub.additional_properties["resourcegroup"], policy_name
            )
        )
    if default_eventhub:
        cs_template_eventhub = (
            "Endpoint={};SharedAccessKeyName={};SharedAccessKey={};EntityPath={}"
        )
        endpoint = hub.properties.event_hub_endpoints["events"].endpoint
        entityPath = hub.properties.event_hub_endpoints["events"].path
        return [
            cs_template_eventhub.format(
                endpoint,
                p.key_name,
                p.secondary_key
                if key_type == KeyType.secondary.value
                else p.primary_key,
                entityPath,
            )
            for p in policies
            if "serviceconnect"
            in (
                p.rights.value.lower()
                if isinstance(p.rights, (Enum, EnumMeta))
                else p.rights.lower()
            )
        ]

    hostname = hub.properties.host_name
    cs_template = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"
    return [
        cs_template.format(
            hostname,
            p.key_name,
            p.secondary_key if key_type == KeyType.secondary.value else p.primary_key,
        )
        for p in policies
    ]


def _iot_hub_monitor_feedback(target, device_id, wait_on_id):
    from azext_iot.monitor import event

    event.monitor_feedback(
        target=target, device_id=device_id, wait_on_id=wait_on_id, token_duration=3600
    )


def _iot_hub_distributed_tracing_show(target, device_id):
    device_twin = _iot_device_twin_show(target=target, device_id=device_id)
    _validate_device_tracing(target, device_twin)
    return device_twin


def _validate_device_tracing(target, device_twin):
    if target["location"].lower() not in TRACING_ALLOWED_FOR_LOCATION:
        raise ClientRequestError(
            'Distributed tracing isn\'t supported for the hub located at "{}" location.'.format(
                target["location"]
            )
        )
    if target["sku_tier"].lower() != TRACING_ALLOWED_FOR_SKU:
        raise ClientRequestError(
            'Distributed tracing isn\'t supported for the hub belongs to "{}" sku tier.'.format(
                target["sku_tier"]
            )
        )
    if device_twin["capabilities"]["iotEdge"]:
        raise ClientRequestError(
            'The device "{}" should be a non-edge device.'.format(device_twin["deviceId"])
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
