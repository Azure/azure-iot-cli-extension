# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.adr.providers.software_update import SoftwareUpdateDataProvider


class DeviceClassProvider(SoftwareUpdateDataProvider):
    """Manage device classes through the linked ADU v2 data plane."""

    def list(self, namespace_name: str, resource_group_name: str):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).device_classes.list()

    def show(
        self,
        namespace_name: str,
        resource_group_name: str,
        device_class_id: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).device_classes.get_device_class(
            device_class_id=device_class_id,
        )

    def delete(
        self,
        namespace_name: str,
        resource_group_name: str,
        device_class_id: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).device_classes.delete(
            device_class_id=device_class_id,
        )
