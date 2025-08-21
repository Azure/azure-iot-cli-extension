# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.base import ADRProvider


class TestADRProvider(object):
    """Test ADRProvider base class methods."""

    @pytest.fixture()
    def fixture_cmd(self):
        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()
        return mock_cmd

    @pytest.fixture()
    def fixture_adr_provider(self, fixture_cmd):
        with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
            mock_client = Mock()
            mock_factory.return_value = mock_client
            provider = ADRProvider(fixture_cmd)
            provider.client = mock_client
            return provider

    @pytest.mark.parametrize("resource_group,location", [("test-rg", "westus2")])
    def test_ensure_location_with_provided_location(self, fixture_adr_provider, fixture_cmd, resource_group, location):
        """Test _ensure_location when location is provided."""

        result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, location)
        assert result == location

    @pytest.mark.parametrize("resource_group,location,fallback_location", [("test-rg", None, "westus2")])
    def test_ensure_location_with_fallback(
        self, fixture_adr_provider, fixture_cmd, resource_group, location, fallback_location
    ):
        """Test _ensure_location when location is None and needs fallback."""

        with patch("azure.cli.core.commands.client_factory.get_mgmt_service_client") as mock_get_client:
            mock_resource_client = Mock()
            mock_rg = Mock()
            mock_rg.location = fallback_location
            mock_resource_client.resource_groups.get.return_value = mock_rg
            mock_get_client.return_value = mock_resource_client

            result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, location)

            assert result == fallback_location
            mock_get_client.assert_called_once()
            mock_resource_client.resource_groups.get.assert_called_once_with(resource_group)

    def test_provider_initialization(self, fixture_cmd):
        """Test that ADRProvider initializes correctly."""
        with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
            mock_client = Mock()
            mock_factory.return_value = mock_client

            provider = ADRProvider(fixture_cmd)

            assert provider.cmd == fixture_cmd
            assert provider.client == mock_client
            mock_factory.assert_called_once_with(fixture_cmd.cli_ctx)
