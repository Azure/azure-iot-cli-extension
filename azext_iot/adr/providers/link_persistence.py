# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Namespace endpoint persistence and destructive link-delete coordination."""

from time import sleep
from typing import Callable

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.link_helpers import namespace_replace_body
from azext_iot.adr.topology import get_endpoints
from azext_iot.common.arm import adapt_modeless_lro_poller
from azext_iot.constants import LRO_POLL_RETRIES, LRO_POLL_WAIT_SEC


_MODELLESS_ARM_OPERATION_GROUPS = frozenset(
    {"iot_hub_resource", "iot_dps_resource", "update_instances"}
)


def get_typed_endpoint(
    namespace: dict,
    section: str,
    endpoint_name: str,
    endpoint_type: str,
    namespace_name: str,
    display_name: str,
) -> dict:
    endpoint = get_endpoints(namespace, section).get(endpoint_name)
    if (
        not endpoint
        or (endpoint.get("endpointType") or "").casefold()
        != endpoint_type.casefold()
    ):
        raise ResourceNotFoundError(
            f"{display_name} endpoint '{endpoint_name}' was not found on "
            f"namespace '{namespace_name}'."
        )
    return endpoint


def begin_linked_resource_delete(delete_operation: Callable):
    try:
        return delete_operation()
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise


def wait_for_linked_resource_deleted(
    get_operation: Callable,
    wait_sec: int = LRO_POLL_WAIT_SEC,
):
    for _ in range(LRO_POLL_RETRIES):
        try:
            get_operation()
        except HttpResponseError as error:
            if error.status_code == 404:
                return
            raise
        sleep(wait_sec)
    raise AzureResponseError(
        "Timed out waiting for the linked resource to be deleted."
    )


def patch_namespace_endpoints(
    *,
    client,
    wait_operation: Callable,
    namespace_name: str,
    resource_group_name: str,
    section: str,
    endpoints_patch: dict,
    status_message: str,
    no_wait: bool = False,
    **kwargs,
):
    """Submit one section-shaped namespace endpoint PATCH."""
    properties = {
        "properties": {section: {"endpoints": endpoints_patch}}
    }
    poller = client.namespaces.begin_update(
        resource_group_name=resource_group_name,
        namespace_name=namespace_name,
        properties=properties,
    )
    return wait_operation(
        poller,
        status_message,
        no_wait=no_wait,
        **kwargs,
    )


def delete_linked_resource_and_endpoint(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    cli_ctx,
    client,
    get_namespace: Callable,
    await_terminal: Callable,
    wait_for_deleted: Callable,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    section: str,
    endpoint_type: str,
    display_name: str,
    parse_linked_resource_id: Callable,
    operations_factory: Callable,
    operation_group_name: str,
    delete_name_parameter: str,
    no_wait: bool = False,
    **kwargs,
):
    """Delete the target first, then safely remove the matching endpoint."""
    namespace = get_namespace(namespace_name, resource_group_name)
    endpoint = get_typed_endpoint(
        namespace,
        section,
        endpoint_name,
        endpoint_type,
        namespace_name,
        display_name,
    )
    linked_resource_id = endpoint.get("resourceId")
    try:
        parsed = parse_linked_resource_id(linked_resource_id)
    except InvalidArgumentValueError as error:
        raise InvalidArgumentValueError(
            f"{display_name} endpoint '{endpoint_name}' on namespace "
            f"'{namespace_name}' has an invalid linked resource ID: "
            f"{linked_resource_id!r}."
        ) from error

    linked_client = operations_factory(
        cli_ctx, subscription_id=parsed["subscription_id"]
    )
    operations = getattr(linked_client, operation_group_name)
    resource_arguments = {
        "resource_group_name": parsed["resource_group_name"],
        delete_name_parameter: parsed["name"],
    }
    resource_poller = begin_linked_resource_delete(
        lambda: operations.begin_delete(**resource_arguments)
    )
    # Linked Hub, DPS, and Update Instance targets use the same defective
    # generated callback. The ADR namespace poller below retains its custom
    # polling path.
    if (
        resource_poller is not None
        and operation_group_name in _MODELLESS_ARM_OPERATION_GROUPS
    ):
        resource_poller = adapt_modeless_lro_poller(resource_poller)

    if resource_poller is not None:
        try:
            resource_poller.result()
        except HttpResponseError as error:
            if error.status_code != 404:
                raise AzureResponseError(
                    f"Failed to delete linked resource '{linked_resource_id}'. "
                    "The namespace endpoint was not changed. Backend detail: "
                    f"{error}"
                ) from error
    try:
        wait_for_deleted(
            lambda: operations.get(**resource_arguments),
            wait_sec=kwargs.get("wait_sec", LRO_POLL_WAIT_SEC),
        )
    except HttpResponseError as error:
        raise AzureResponseError(
            f"Linked resource '{linked_resource_id}' could not be confirmed "
            "deleted. The namespace endpoint was not changed. Backend detail: "
            f"{error}"
        ) from error
    except AzureResponseError as error:
        raise AzureResponseError(
            f"Timed out confirming deletion of linked resource "
            f"'{linked_resource_id}'. The namespace endpoint was not changed; "
            "rerun the command after checking the resource."
        ) from error

    try:
        latest_namespace = get_namespace(namespace_name, resource_group_name)
    except HttpResponseError as error:
        raise AzureResponseError(
            f"The linked resource '{linked_resource_id}' was deleted, but the "
            "Device Registry namespace could not be read before cleanup. Rerun "
            "this command to remove the stale link."
        ) from error
    latest_endpoint = get_endpoints(latest_namespace, section).get(endpoint_name)
    if latest_endpoint and (
        (latest_endpoint.get("endpointType") or "").casefold()
        != endpoint_type.casefold()
        or (latest_endpoint.get("resourceId") or "").rstrip("/").casefold()
        != linked_resource_id.rstrip("/").casefold()
    ):
        raise AzureResponseError(
            f"{display_name} endpoint '{endpoint_name}' changed while its "
            "linked resource was being deleted. The original linked resource "
            f"'{linked_resource_id}' has been deleted. The replacement "
            "endpoint was not removed and must be reconciled manually."
        )

    try:
        namespace_resource = namespace_replace_body(latest_namespace)
    except AzureResponseError as error:
        raise AzureResponseError(
            f"The linked resource '{linked_resource_id}' was deleted, but a "
            "complete Device Registry namespace replacement body could not be "
            "built. Rerun this command to remove the stale link."
        ) from error
    replacement_endpoints = (
        namespace_resource.setdefault("properties", {})
        .setdefault(section, {})
        .setdefault("endpoints", {})
    )
    replacement_endpoints.pop(endpoint_name, None)
    try:
        namespace_poller = client.namespaces.begin_create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            resource=namespace_resource,
        )
    except HttpResponseError as error:
        raise AzureResponseError(
            f"The linked resource '{linked_resource_id}' was deleted, but the "
            "Device Registry namespace update could not be submitted. Rerun "
            "this command to remove the stale link. Backend detail: "
            f"{error}"
        ) from error

    if no_wait:
        return namespace_poller

    try:
        await_terminal(namespace_poller, **kwargs)
    except (AzureResponseError, HttpResponseError) as error:
        raise AzureResponseError(
            f"The linked resource '{linked_resource_id}' was deleted, but the "
            "Device Registry namespace update did not complete. Rerun this "
            f"command to remove the stale link. Backend detail: {error}"
        ) from error
    return None
