# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Namespace endpoint lookup and PATCH persistence."""

from typing import Callable

from azure.cli.core.azclierror import ResourceNotFoundError

from azext_iot.adr.topology import get_endpoints


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
