# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import subprocess
from typing import Optional
from unittest.mock import MagicMock, Mock, create_autospec, patch

import pytest

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.certificate_authority import CertificateAuthorityProvider
from azext_iot.adr.providers.certificate_policy import CertificatePolicyProvider
from azext_iot.adr.providers.group import GroupProvider
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.report import ReportProvider
from azext_iot.adr.providers.job import JobProvider
from azext_iot.adr.providers.job_run import JobRunProvider
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.adr._log import _log, _pretty_log_enabled

# ADR integration defaults mirror scripts/smoke_tests/adr_2026_11_02_full_e2e.sh.
TEST_SUBSCRIPTION = os.getenv(
    "azext_iot_adr_subscription",
    "a386d5ea-ea90-441a-8263-d816368c84a1",
)
TEST_RG = os.getenv(
    "azext_iot_adr_resource_group",
    "cli-int-test-rg",
)
TEST_LOCATION = os.getenv("azext_iot_adr_location", "centraluseuap")
TEST_API_VERSION = os.getenv(
    "azext_iot_adr_api_version",
    "2026-11-02-preview",
)
TEST_ARM_RESOURCE = os.getenv(
    "azext_iot_adr_arm_resource",
    "https://management.azure.com",
)
TEST_ARM_ENDPOINT = os.getenv(
    "azext_iot_adr_arm_endpoint",
    f"https://{TEST_LOCATION}.management.azure.com",
)
PREFLIGHT_TIMEOUT_SECONDS = 60
OPTIONAL_FIXTURE_ENV_VARS = (
    "azext_iot_adr_update_instance_id",
    "azext_iot_adr_update_instance_disposable",
    "azext_iot_adr_su_link_poll_attempts",
    "azext_iot_adr_adu_fpa_object_id",
    "azext_iot_adr_run_resource_parity_int",
    "azext_iot_adr_reports_enabled",
    "azext_iot_adr_revoke_certificates",
    "azext_iot_adr_ca_auth_profile_name",
    "azext_iot_adr_job_run_resource_group",
    "azext_iot_adr_job_run_namespace",
    "azext_iot_adr_job_run_job",
    "azext_iot_adr_job_run_name",
    "azext_iot_adr_uami_resource_id",
    "azext_iot_adr_su_namespace",
    "azext_iot_adr_su_storage_account",
    "azext_iot_adr_su_storage_subscription",
    "azext_iot_adr_failed_dps_namespace_id",
    "azext_iot_adr_failed_dps_endpoint",
)


def _run_preflight_command(command):
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise pytest.UsageError(
            f"ADR integration preflight could not run {' '.join(command)}: "
            f"{error}"
        ) from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise pytest.UsageError(
            f"ADR integration preflight failed: {' '.join(command)}"
            f"\n{detail}"
        )
    return result.stdout.strip()


def run_adr_integration_preflight(config):
    """Run mandatory checks and report optional ADR fixture availability."""
    if os.getenv("AZURE_TEST_RUN_LIVE", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise pytest.UsageError(
            "ADR integration tests require AZURE_TEST_RUN_LIVE=True."
        )

    _run_preflight_command(
        ["az", "account", "set", "--subscription", TEST_SUBSCRIPTION]
    )
    subscription_id = _run_preflight_command(
        ["az", "account", "show", "--query", "id", "-o", "tsv"]
    )
    if not subscription_id:
        raise pytest.UsageError(
            "ADR integration preflight returned an empty subscription ID."
        )
    if subscription_id.casefold() != TEST_SUBSCRIPTION.casefold():
        raise pytest.UsageError(
            "ADR integration preflight selected subscription "
            f"{subscription_id}, expected {TEST_SUBSCRIPTION}."
        )
    _run_preflight_command(
        ["az", "group", "show", "--name", TEST_RG, "--output", "none"]
    )
    _run_preflight_command(
        ["az", "iot", "adr", "ns", "--help"]
    )
    for provider_namespace in (
        "Microsoft.DeviceRegistry",
        "Microsoft.DeviceUpdate",
    ):
        provider_state = _run_preflight_command(
            [
                "az",
                "provider",
                "show",
                "--namespace",
                provider_namespace,
                "--query",
                "registrationState",
                "-o",
                "tsv",
            ]
        )
        if provider_state not in {"Registered", "Registering"}:
            raise pytest.UsageError(
                f"{provider_namespace} must be registered before running ADR "
                "integration tests; current state: "
                f"{provider_state or 'unknown'}."
            )
    _run_preflight_command(
        [
            "az",
            "rest",
            "--method",
            "get",
            "--resource",
            TEST_ARM_RESOURCE,
            "--url",
            (
                f"{TEST_ARM_ENDPOINT}/subscriptions/{TEST_SUBSCRIPTION}"
                f"/resourceGroups/{TEST_RG}/providers/"
                f"Microsoft.DeviceRegistry/namespaces"
                f"?api-version={TEST_API_VERSION}"
            ),
            "--output",
            "none",
        ]
    )

    configured = sorted(
        variable
        for variable in OPTIONAL_FIXTURE_ENV_VARS
        if os.getenv(variable)
    )
    missing = sorted(set(OPTIONAL_FIXTURE_ENV_VARS) - set(configured))
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_line(
            "ADR preflight: "
            f"subscription={subscription_id[:8]}..., "
            f"resource_group={TEST_RG}, location={TEST_LOCATION}, "
            f"endpoint={TEST_ARM_ENDPOINT}, api={TEST_API_VERSION}"
        )
        reporter.write_line(
            "ADR optional fixtures configured: "
            + (", ".join(configured) if configured else "none")
        )
        reporter.write_line(
            "ADR optional fixtures missing: "
            + (", ".join(missing) if missing else "none")
        )


@pytest.fixture(scope="session", autouse=True)
def adr_integration_preflight(request):
    """Validate mandatory live-test infrastructure once per ADR integration run."""
    integration_items = [
        item for item in request.session.items if "_int.py" in item.nodeid
    ]
    if not integration_items:
        return

    run_adr_integration_preflight(request.config)


def pytest_runtest_logreport(report):
    """In pretty mode, emit PASSED/FAILED via _log so colors work."""
    if not _pretty_log_enabled():
        return
    if report.when != "call":
        return

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

    # Patch the canonical wait helper. Every provider now defers to ADRProvider._wait /
    # _await_terminal (defined in base), so patching the base reference covers them all — the
    # individual providers no longer import wait_for_terminal_state directly.
    monkeypatch.setattr("azext_iot.adr.providers.base.wait_for_terminal_state", fast_wait)


@pytest.fixture()
def mock_poller():
    """Create a mock LRO poller for testing."""

    def _create_mock_poller(result_value=None):
        poller = Mock()
        poller.result.return_value = result_value or Mock()
        return poller

    return _create_mock_poller


# Operation groups reached by `az iot adr ns` commands. Specced strictly so an SDK
# regeneration that renames or removes one of these methods fails a unit test.
_SPECCED_OPERATION_GROUPS = (
    "namespaces",
    "certificate_authorities",
    "certificate_policies",
    "groups",
    "jobs",
    "job_runs",
    "job_runs_by_namespace",
    "registry_devices",
    "registry_device_attributes",
    "registry_device_authentication_profiles",
    "registry_device_capabilities",
)

_REAL_ADR_CLIENT = None


def _real_adr_client():
    """Instantiate the real management client once per session (no network I/O)."""
    global _REAL_ADR_CLIENT
    if _REAL_ADR_CLIENT is None:
        from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient

        _REAL_ADR_CLIENT = DeviceRegistryMgmtClient(
            credential=MagicMock(),
            subscription_id="00000000-0000-0000-0000-000000000000",
        )
    return _REAL_ADR_CLIENT


def _spec_adr_client() -> Mock:
    """Build a strictly-specced mock of the Device Registry management client.

    A bare ``Mock()`` auto-creates any attribute, so an SDK method rename (for
    example ``groups.begin_create_or_replace`` -> ``groups.create_or_replace``)
    silently keeps passing in unit tests while failing at runtime. Here every
    operation group is replaced with ``create_autospec`` of the *real*
    generated operations class, so calling a method that no longer exists
    raises ``AttributeError`` and calling one with the wrong keyword arguments
    raises ``TypeError``.

    Only the operation groups the ADR commands actually use are specced;
    everything else falls back to a permissive child mock. This keeps the
    fixture cheap while still catching drift in the surface we call.
    """
    client = Mock()
    real_client = _real_adr_client()
    for attribute in _SPECCED_OPERATION_GROUPS:
        operation_group = getattr(real_client, attribute)
        setattr(client, attribute, create_autospec(type(operation_group), instance=True))
    return client


@pytest.fixture()
def mock_adr_client():
    """Strictly-specced Device Registry client mock. See :func:`_spec_adr_client`."""
    return _spec_adr_client()


@pytest.fixture()
def fixture_adr_provider(fixture_cmd):
    """Base ADR provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = ADRProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_namespace_provider(fixture_cmd):
    """Namespace provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = NamespaceProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_ca_provider(fixture_cmd):
    """Certificate authority provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = CertificateAuthorityProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_ca_policy_provider(fixture_cmd):
    """Certificate policy provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = CertificatePolicyProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_link_provider(fixture_cmd):
    """Link provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = LinkProvider(fixture_cmd)
        provider.client = mock_client
        provider._rbac = MagicMock()  # pylint: disable=protected-access
        # Existing endpoint-shape tests isolate namespace mutation from the
        # cross-RP/RBAC preflight. Dedicated preflight/RBAC tests exercise the
        # real helpers with strictly controlled clients.
        provider._preflight_link = MagicMock(  # pylint: disable=protected-access
            return_value={
                "location": "centraluseuap",
                "sku": {"name": "S1"},
                "properties": {
                    "provisioningState": "Succeeded",
                    "hostName": "hub.azure-devices.net",
                },
            }
        )
        provider._warn_if_hub_classically_linked = MagicMock()  # pylint: disable=protected-access
        return provider


@pytest.fixture()
def fixture_group_provider(fixture_cmd):
    """Group provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = GroupProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_job_provider(fixture_cmd):
    """Job provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = JobProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_job_run_provider(fixture_cmd):
    """Job run (read-only) provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = JobRunProvider(fixture_cmd)
        provider.client = mock_client
        return provider


@pytest.fixture()
def fixture_report_provider(fixture_cmd):
    """Report provider fixture for testing."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = _spec_adr_client()
        mock_factory.return_value = mock_client
        provider = ReportProvider(fixture_cmd)
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
        self, assignee_id: str, role: str, scope: str, assignee_type: Optional[str] = "auto",
    ) -> Optional[str]:
        """Assign a role; None identifies an object ID whose type ARM should resolve."""
        from azext_iot.tests.adr._log import LogKind, _log

        try:
            if assignee_type == "auto":
                assignee_filter = f"--assignee '{assignee_id}'"
            else:
                assignee_filter = (
                    f"--assignee-object-id '{assignee_id}' "
                    "--fill-principal-name false"
                )
            check_cmd = (
                f"role assignment list {assignee_filter} --scope '{scope}' "
                f"--role '{role}'"
            )
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
                    f"--scope '{scope}'"
                )
                if assignee_type:
                    create_cmd += f" --assignee-principal-type {assignee_type}"
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
            assignment_id = self.assign_role(
                principal_id,
                role,
                scope,
                assignee_type="ServicePrincipal",
            )
            if assignment_id is None:
                raise AssertionError(
                    f"Failed to assign required ADR role '{role}'."
                )
