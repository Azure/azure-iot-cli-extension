# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.base import ADRProvider


@pytest.mark.parametrize("input_location", ["location", None])
def test_ensure_location(fixture_adr_provider, fixture_cmd, input_location):
    """Test _ensure_location behavior with various input combinations."""
    resource_group = "test-resource-group"
    fallback_location = "resource-group-location"

    if input_location is None:
        # Mock the resource client when location lookup is needed
        with patch("azure.cli.core.commands.client_factory.get_mgmt_service_client") as mock_get_client:
            mock_resource_client = Mock()
            mock_rg = Mock()
            mock_rg.location = fallback_location
            mock_resource_client.resource_groups.get.return_value = mock_rg
            mock_get_client.return_value = mock_resource_client

            result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, input_location)

            assert result == fallback_location
            mock_get_client.assert_called_once()
            mock_resource_client.resource_groups.get.assert_called_once_with(resource_group)
    else:
        # When location is provided, it should return immediately without any mocking needed
        result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, input_location)
        assert result == input_location


def test_provider_initialization(fixture_cmd):
    """Test that ADRProvider initializes correctly."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client

        provider = ADRProvider(fixture_cmd)

        assert provider.cmd == fixture_cmd
        assert provider.client == mock_client
        mock_factory.assert_called_once_with(fixture_cmd.cli_ctx)
