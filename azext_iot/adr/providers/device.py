# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from knack.log import get_logger
from rich.console import Console

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.common.utility import shell_safe_json_parse, wait_for_terminal_state

console = Console()
logger = get_logger(__name__)


class DeviceProvider(ADRProvider):
    def __init__(self, cmd):
        super(DeviceProvider, self).__init__(cmd)

    def show(self, device_name: str, namespace_name: str, resource_group_name: str):
        return self.client.namespace_devices.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            device_name=device_name,
        )

    def list(self, namespace_name: str, resource_group_name: str):
        return list(
            self.client.namespace_devices.list_by_resource_group(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
        )

    def update(
        self,
        device_name: str,
        namespace_name: str,
        resource_group_name: str,
        enabled: Optional[bool] = None,
        tags: Optional[Dict[str, str]] = None,
        operating_system_version: Optional[str] = None,
        attributes: Optional[str] = None,
        policy_resource_id: Optional[str] = None,
        **kwargs,
    ):
        """Update a device in the namespace."""
        inner_props = {}

        if enabled is not None:
            inner_props["enabled"] = enabled
        if operating_system_version is not None:
            inner_props["operatingSystemVersion"] = operating_system_version
        if attributes is not None:
            if isinstance(attributes, str):
                if attributes == "":
                    attributes = None
                else:
                    attributes = shell_safe_json_parse(attributes)
            inner_props["attributes"] = attributes
        if policy_resource_id is not None:
            if policy_resource_id == "":
                inner_props["policy"] = None
            else:
                inner_props["policy"] = {"resourceId": policy_resource_id}

        properties = {}
        if inner_props:
            properties["properties"] = inner_props
        if tags is not None:
            properties["tags"] = tags

        with console.status(
            f"Updating device '{device_name}' in namespace {namespace_name}..."
        ):
            poller = self.client.namespace_devices.begin_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                device_name=device_name,
                properties=properties,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def revoke(
        self,
        device_name: str,
        namespace_name: str,
        resource_group_name: str,
        disable: bool = False,
        **kwargs,
    ):
        """Revoke credentials for a device in the namespace."""
        body = {}
        if disable:
            body["disable"] = True
        with console.status(
            f"Revoking credentials for device '{device_name}' in namespace {namespace_name}..."
        ):
            poller = self.client.namespace_devices.begin_revoke(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                device_name=device_name,
                body=body,
            )
            return wait_for_terminal_state(poller, **kwargs)
