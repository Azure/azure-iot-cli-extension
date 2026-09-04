# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock, patch

import pytest

from azext_iot.adr.providers.device_class import DeviceClassProvider

NAMESPACE = "test-namespace"
RG = "test-rg"
ENDPOINT = "updates.example.test"
CLASS_ID = "class-id"


@pytest.fixture()
def provider():
    with patch(
        "azext_iot.adr.providers.software_update.adr_service_factory"
    ) as registry_factory, patch(
        "azext_iot.adr.providers.software_update."
        "adr_software_update_data_service_factory"
    ) as data_factory:
        registry_client = MagicMock()
        data_client = MagicMock()
        registry_factory.return_value = registry_client
        data_factory.return_value = data_client
        registry_client.namespaces.get.return_value = {
            "properties": {
                "updating": {
                    "endpoints": {
                        "software-updates": {
                            "endpointType": (
                                "Microsoft.DeviceUpdate/updateInstances"
                            ),
                            "linkingState": "Succeeded",
                            "serviceAddress": f"https://{ENDPOINT}",
                        }
                    }
                }
            }
        }
        value = DeviceClassProvider(MagicMock(cli_ctx=MagicMock()))
        value.client = data_client
        yield value


def test_list_device_classes(provider):
    expected = [{"deviceClassId": CLASS_ID}]
    provider.client.device_classes.list.return_value = expected

    assert provider.list(NAMESPACE, RG) == expected
    provider.client.device_classes.list.assert_called_once_with()


def test_show_device_class(provider):
    expected = {"deviceClassId": CLASS_ID}
    provider.client.device_classes.get_device_class.return_value = expected

    assert provider.show(NAMESPACE, RG, CLASS_ID) == expected
    provider.client.device_classes.get_device_class.assert_called_once_with(
        device_class_id=CLASS_ID,
    )


def test_delete_device_class(provider):
    expected = {"deleted": True}
    provider.client.device_classes.delete.return_value = expected

    assert provider.delete(NAMESPACE, RG, CLASS_ID) == expected
    provider.client.device_classes.delete.assert_called_once_with(
        device_class_id=CLASS_ID,
    )
