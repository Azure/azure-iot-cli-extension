# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, patch

import pytest

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.credential import CredentialProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.policy import PolicyProvider
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.settings import DynamoSettings

# Integration test constants
REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)
TEST_RG = settings.env.azext_iot_testrg

# Test constants for integration tests
CUSTOM_POLICY_NAME = "custompolicy"
CUSTOM_CERT_VALIDITY_DAYS = 25
CUSTOM_CERT_UPDATE_VALIDITY_DAYS = 20
CUSTOM_CERT_UPDATE_KEYTYPE = "RSA"
CUSTOM_CERT_KEY_TYPE = "ECC"
CUSTOM_CERT_SUBJECT = "CN=test-device"


@pytest.fixture(autouse=True)
def mock_wait_for_terminal_state(monkeypatch):
    """Mock wait_for_terminal_state to avoid sleeping in tests."""

    def fast_wait(poller, **kwargs):
        """Return poller result immediately without sleeping."""
        return poller.result()

    # Patch the function in all provider modules
    monkeypatch.setattr("azext_iot.adr.providers.namespace.wait_for_terminal_state", fast_wait)
    monkeypatch.setattr("azext_iot.adr.providers.credential.wait_for_terminal_state", fast_wait)
    monkeypatch.setattr("azext_iot.adr.providers.policy.wait_for_terminal_state", fast_wait)


@pytest.fixture()
def mock_poller():
    """Create a mock LRO poller for testing."""

    def _create_mock_poller(result_value=None):
        poller = Mock()
        poller.result.return_value = result_value or Mock()
        return poller

    return _create_mock_poller


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


def generate_adr_namespace_name() -> str:
    return f"testadr{generate_generic_id()[:8]}"


def generate_hub_name() -> str:
    return f"testhub{generate_generic_id()[:8]}"


def generate_dps_name() -> str:
    return f"testdps{generate_generic_id()[:8]}"


def generate_identity_name() -> str:
    return f"testuami{generate_generic_id()[:8]}"


def generate_device_id() -> str:
    return f"testdev{generate_generic_id()[:8]}"


def generate_enrollment_group_id() -> str:
    return f"testgroup{generate_generic_id()[:8]}"
