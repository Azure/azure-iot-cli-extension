# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azure.cli.core.azclierror import BadRequestError

from azext_iot.core.custom import iot_dps_create, iot_dps_get, iot_dps_update
from azext_iot.tests.generators import generate_generic_id

# Test constants
dps_name = generate_generic_id()
resource_group = generate_generic_id()
location = "westus2"


def _get_sent_description(mock_client):
    return mock_client.iot_dps_resource.begin_create_or_update.call_args.kwargs["iot_dps_description"]


class TestDPSCreate(object):
    @pytest.mark.parametrize("disable_local_auth", [None, True, False])
    @patch("azext_iot.core.custom._ensure_location")
    def test_dps_create(self, mock_ensure_location, disable_local_auth):
        """--disable-local-auth is sent only when the user provides it."""
        mock_ensure_location.return_value = location
        mock_client = Mock()
        mock_client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {
            "nameAvailable": True
        }

        iot_dps_create(
            Mock(), mock_client, dps_name, resource_group, disable_local_auth=disable_local_auth
        )

        description = _get_sent_description(mock_client)
        if disable_local_auth is None:
            assert "disableLocalAuth" not in description["properties"]
        else:
            assert description["properties"]["disableLocalAuth"] is disable_local_auth

        # Takeover must keep core's defaults.
        assert description["location"] == location
        assert description["sku"] == {"name": "S1", "capacity": 1}
        mock_client.iot_dps_resource.begin_create_or_update.assert_called_once_with(
            resource_group_name=resource_group,
            provisioning_service_name=dps_name,
            iot_dps_description=description,
        )

    @patch("azext_iot.core.custom._ensure_location")
    def test_dps_create_omits_unset_optionals(self, mock_ensure_location):
        """The body is raw JSON with no serializer, so unset optionals must be omitted, not sent as null."""
        mock_ensure_location.return_value = location
        mock_client = Mock()
        mock_client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {
            "nameAvailable": True
        }

        iot_dps_create(Mock(), mock_client, dps_name, resource_group)

        description = _get_sent_description(mock_client)
        assert description["properties"] == {}
        assert "tags" not in description

    @patch("azext_iot.core.custom._ensure_location")
    def test_dps_create_sends_supplied_optionals(self, mock_ensure_location):
        """Optionals the user does supply must reach the body."""
        mock_ensure_location.return_value = location
        mock_client = Mock()
        mock_client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {
            "nameAvailable": True
        }

        iot_dps_create(
            Mock(),
            mock_client,
            dps_name,
            resource_group,
            tags={"a": "b"},
            enable_data_residency=True,
            disable_local_auth=True,
        )

        description = _get_sent_description(mock_client)
        assert description["properties"] == {"enableDataResidency": True, "disableLocalAuth": True}
        assert description["tags"] == {"a": "b"}

    @patch("azext_iot.core.custom._ensure_location")
    def test_dps_create_name_unavailable(self, mock_ensure_location):
        mock_ensure_location.return_value = location
        mock_client = Mock()
        mock_client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {
            "nameAvailable": False,
            "message": "name taken",
        }

        with pytest.raises(BadRequestError):
            iot_dps_create(Mock(), mock_client, dps_name, resource_group)

        mock_client.iot_dps_resource.begin_create_or_update.assert_not_called()


class TestDPSUpdate(object):
    @pytest.mark.parametrize("disable_local_auth", [None, True, False])
    def test_dps_update(self, disable_local_auth):
        """Omitting --disable-local-auth must leave the existing value untouched."""
        mock_client = Mock()
        parameters = {"properties": {"disableLocalAuth": True}}

        iot_dps_update(
            mock_client, dps_name, parameters, resource_group, disable_local_auth=disable_local_auth
        )

        description = _get_sent_description(mock_client)
        expected = True if disable_local_auth is None else disable_local_auth
        assert description["properties"]["disableLocalAuth"] is expected

        # begin_update only accepts tags, so updates go through create_or_update.
        mock_client.iot_dps_resource.begin_update.assert_not_called()
        mock_client.iot_dps_resource.begin_create_or_update.assert_called_once()

    def test_dps_update_resolves_resource_group(self):
        mock_client = Mock()
        mock_client.iot_dps_resource.list_by_subscription.return_value = [
            {"name": dps_name, "resourcegroup": resource_group}
        ]

        iot_dps_update(mock_client, dps_name, {"properties": {}})

        call_kwargs = mock_client.iot_dps_resource.begin_create_or_update.call_args.kwargs
        assert call_kwargs["resource_group_name"] == resource_group


class TestDPSGet(object):
    def test_dps_get(self):
        """Getter backs both show and generic update, so arguments must not swap."""
        mock_client = Mock()

        iot_dps_get(mock_client, dps_name, resource_group)

        mock_client.iot_dps_resource.get.assert_called_once_with(
            provisioning_service_name=dps_name, resource_group_name=resource_group
        )

    def test_dps_get_without_resource_group(self):
        mock_client = Mock()
        mock_client.iot_dps_resource.list_by_subscription.return_value = [
            {"name": dps_name, "resourcegroup": resource_group}
        ]

        assert iot_dps_get(mock_client, dps_name)["resourcegroup"] == resource_group
        mock_client.iot_dps_resource.get.assert_not_called()
