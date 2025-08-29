# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.credential import CredentialProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.policy import PolicyProvider


@pytest.fixture()
def fixture_adr_provider(fixture_cmd):
    """Base ADR provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client
        provider = ADRProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_credential_provider(fixture_cmd):
    """Credential provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client
        provider = CredentialProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_namespace_provider(fixture_cmd):
    """Namespace provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client
        provider = NamespaceProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_policy_provider(fixture_cmd):
    """Policy provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client
        provider = PolicyProvider(fixture_cmd)
        provider.client = mock_client
        return provider
