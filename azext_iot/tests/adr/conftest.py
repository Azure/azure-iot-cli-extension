# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from typing import Optional
from unittest.mock import Mock, patch

import pytest

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.credential import CredentialProvider
from azext_iot.adr.providers.device import DeviceProvider
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
CUSTOM_CERT_KEY_TYPE = "ECC"
CUSTOM_CERT_SUBJECT = "CN=test-device"

TEST_LOCATION = os.getenv("azext_iot_adr_location", "westus")


def pytest_runtest_logreport(report):
    """In pretty mode, emit PASSED/FAILED via _log so colors work."""
    if not os.environ.get("PRETTY_LOG"):
        return
    if report.when != "call":
        return
    from azext_iot.tests.adr._log import _log

    test_name = report.nodeid.split("::")[-1]
    if report.passed:
        _log("_pass", "%s", test_name)
    elif report.failed:
        # Include the first line of the failure for context
        short_reason = ""
        if report.longreprtext:
            for line in report.longreprtext.splitlines():
                line = line.strip()
                if line and not line.startswith("_"):
                    short_reason = f" -- {line[:200]}"
                    break
        _log("_fail", "%s%s", test_name, short_reason)


@pytest.fixture(autouse=True)
def mock_wait_for_terminal_state(request, monkeypatch):
    """Mock wait_for_terminal_state to avoid sleeping in unit tests.

    Skipped for integration tests (_int.py) which need real polling delays.
    """
    if "_int" in request.node.nodeid:
        return

    def fast_wait(poller, **kwargs):
        """Return poller result immediately without sleeping."""
        return poller.result()

    # Patch the function in all provider modules
    monkeypatch.setattr("azext_iot.adr.providers.namespace.wait_for_terminal_state", fast_wait)
    monkeypatch.setattr("azext_iot.adr.providers.credential.wait_for_terminal_state", fast_wait)
    monkeypatch.setattr("azext_iot.adr.providers.policy.wait_for_terminal_state", fast_wait)
    monkeypatch.setattr("azext_iot.adr.providers.device.wait_for_terminal_state", fast_wait)


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


@pytest.fixture()
def fixture_device_provider(fixture_cmd):
    """Device provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client
        provider = DeviceProvider(fixture_cmd)
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


# Shared test helpers for unit tests

def _serializable(data: dict) -> Mock:
    """Wrap *data* so ``.serialize(keep_readonly=True)`` returns it."""
    m = Mock()
    m.serialize.return_value = data
    return m


def _ns_mock(location: str = "eastus") -> Mock:
    """Return a namespace mock with a ``.location`` attribute."""
    ns = Mock()
    ns.location = location
    return ns


class RoleAssignmentHelper:
    """RBAC role-assignment helpers for ADR integration tests.

    Must be mixed into a class that provides ``self.cmd()``
    (e.g. ``CaptureOutputLiveScenarioTest``).
    """

    cmd: callable  # provided by CaptureOutputLiveScenarioTest via MRO

    def assign_role(
        self, assignee_id: str, role: str, scope: str, assignee_type: str = "auto",
    ) -> Optional[str]:
        """Assign an Azure RBAC role, skipping if already assigned."""
        from azext_iot.tests.adr._log import LogKind, _log

        try:
            check_cmd = f"role assignment list --assignee '{assignee_id}' --scope '{scope}' --role '{role}'"
            _log(LogKind.CMD, "az %s", check_cmd)
            existing = self.cmd(check_cmd).get_output_in_json()
            if existing:
                _log(LogKind.RESULT, "Role '%s' already assigned (skip)", role)
                return existing[0].get("id", "existing")

            if assignee_type == "auto":
                create_cmd = f"role assignment create --assignee '{assignee_id}' --role '{role}' --scope '{scope}'"
            else:
                create_cmd = (
                    f"role assignment create --assignee-object-id '{assignee_id}' --role '{role}' "
                    f"--scope '{scope}' --assignee-principal-type '{assignee_type}'"
                )
            _log(LogKind.CMD, "az %s", create_cmd)
            result = self.cmd(create_cmd).get_output_in_json()
            _log(LogKind.RESULT, "Role '%s' assigned", role)

            return result.get("id", "unknown")
        except Exception as e:
            _log(LogKind.WARN, "Failed to assign role '%s': %s", role, e)
            return None

    def assign_hub_rp_contributor_role(self, subscription_id: str, resource_group: str):
        """Assign Contributor to the IoT Hub first-party RP on the resource group."""
        hub_rp_object_id = "0aab4033-4ad9-4b0b-9934-542334eceffb"
        rg_scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        self.assign_role(hub_rp_object_id, "Contributor", rg_scope, assignee_type="ServicePrincipal")

    def assign_adr_roles_to_identity(self, principal_id: str, scope: str):
        """Assign ADR Contributor + Onboarding roles to a managed identity."""
        for role in ["Azure Device Registry Contributor", "Azure Device Registry Onboarding"]:
            self.assign_role(principal_id, role, scope)
