# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock, call

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
)
from azext_iot.adr.providers.wait import (
    WaitEvaluation,
    group_membership_ready,
    job_run_succeeded,
    link_succeeded,
    namespace_links_succeeded,
    provisioning_succeeded,
    resource_exists,
    wait_for_resource,
)
from azext_iot.adr import commands_wait


@pytest.fixture(autouse=True)
def mock_progress(mocker):
    return mocker.patch(
        "azext_iot.adr.providers.wait.IndeterminateProgressBar"
    ).return_value


@pytest.mark.parametrize(
    "state,complete,failure",
    [
        ("Succeeded", True, None),
        ("Accepted", False, None),
        ("Failed", False, "terminal provisioningState 'Failed'"),
        ("Canceled", False, "terminal provisioningState 'Canceled'"),
        (None, False, None),
    ],
)
def test_provisioning_default(state, complete, failure):
    result = provisioning_succeeded(
        {"properties": {"provisioningState": state}}
    )
    assert result.complete is complete
    if failure:
        assert failure in result.failure
    else:
        assert result.failure is None


def test_exists_default():
    assert resource_exists({}) == WaitEvaluation(
        True, observation="resource exists"
    )


@pytest.mark.parametrize(
    "state,complete,failure",
    [
        ("Ready", True, None),
        ("Resolving", False, None),
        ("RefreshingMembers", False, None),
        ("FailedToResolveMembers", False, "membership refresh failed"),
    ],
)
def test_group_default(state, complete, failure):
    result = group_membership_ready(
        {"properties": {"membershipState": state}}
    )
    assert result.complete is complete
    if failure:
        assert failure in result.failure


@pytest.mark.parametrize(
    "state,complete,failure",
    [
        ("Succeeded", True, None),
        ("Active", False, None),
        ("Failed", False, "terminal status 'Failed'"),
        ("Canceled", False, "terminal status 'Canceled'"),
        ("TimedOut", False, "terminal status 'TimedOut'"),
    ],
)
def test_job_run_default(state, complete, failure):
    result = job_run_succeeded({"properties": {"status": state}})
    assert result.complete is complete
    if failure:
        assert failure in result.failure


def test_endpoint_default_accepts_nested_status_and_surfaces_failure():
    assert link_succeeded(
        {"name": "hub", "provisioningStatus": {"status": "Succeeded"}}
    ).complete
    failed = link_succeeded(
        {
            "name": "hub",
            "linkingState": "Failed",
            "linkingError": {"message": "RBAC is incomplete"},
        }
    )
    assert "hub" in failed.failure
    assert "RBAC is incomplete" in failed.failure
    malformed = link_succeeded(
        {"name": "hub", "linkingState": "Failed", "linkingError": "opaque"}
    )
    assert malformed.failure == (
        "Link 'hub' reached terminal linkingState 'Failed'."
    )


def _namespace_links(hub="Succeeded", dps="Succeeded", su="Succeeded"):
    return {
        "properties": {
            "messaging": {
                "endpoints": {
                    "hub": {
                        "endpointType": IOT_HUB_ENDPOINT_TYPE,
                        "linkingState": hub,
                    }
                }
            },
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "endpointType": DPS_ENDPOINT_TYPE,
                        "linkingState": dps,
                    }
                }
            },
            "updating": {
                "endpoints": {
                    "su": {
                        "endpointType": SU_ENDPOINT_TYPE,
                        "linkingState": su,
                    }
                }
            },
        }
    }


def test_general_link_default_waits_for_all_links():
    assert namespace_links_succeeded(_namespace_links()).complete
    pending = namespace_links_succeeded(
        _namespace_links(hub="Linking", su="Pending")
    )
    assert not pending.complete
    assert "HUB link 'hub'=Linking" in pending.observation
    assert "SU link 'su'=Pending" in pending.observation


def test_general_link_default_supports_qualified_scope():
    result = namespace_links_succeeded(
        _namespace_links(hub="Linking"),
        dps_endpoint_name="dps",
    )
    assert result.complete

    missing = namespace_links_succeeded(
        _namespace_links(),
        hub_endpoint_name="later",
    )
    assert not missing.complete
    assert "not materialized" in missing.observation


def test_general_link_default_rejects_wrong_type_and_failed_link():
    resource = _namespace_links()
    resource["properties"]["messaging"]["endpoints"]["hub"][
        "endpointType"
    ] = DPS_ENDPOINT_TYPE
    wrong_type = namespace_links_succeeded(
        resource, hub_endpoint_name="hub"
    )
    assert "not 'Microsoft.Devices/IotHubs'" in wrong_type.failure

    resource["properties"]["messaging"]["endpoints"]["hub"] = "malformed"
    malformed = namespace_links_succeeded(
        resource, hub_endpoint_name="hub"
    )
    assert "endpointType 'None'" in malformed.failure

    failed = namespace_links_succeeded(_namespace_links(dps="Failed"))
    assert "DPS link 'dps'" in failed.failure


def test_general_link_default_does_not_complete_empty_scope():
    result = namespace_links_succeeded({"properties": {}})
    assert not result.complete
    assert result.observation == "no namespace links found"


def test_wait_uses_default_condition_when_no_standard_predicate(mock_progress):
    getter = MagicMock(
        side_effect=[
            {"properties": {"provisioningState": "Accepted"}},
            {"properties": {"provisioningState": "Succeeded"}},
        ]
    )
    sleeper = MagicMock()

    assert (
        wait_for_resource(
            MagicMock(),
            getter,
            provisioning_succeeded,
            timeout=2,
            interval=1,
            sleeper=sleeper,
        )
        is None
    )
    assert getter.call_count == 2
    sleeper.assert_called_once_with(1)
    mock_progress.end.assert_called_once()


def test_wait_surfaces_default_terminal_failure(mock_progress):
    with pytest.raises(AzureResponseError, match="terminal status 'Failed'"):
        wait_for_resource(
            MagicMock(),
            lambda: {"properties": {"status": "Failed"}},
            job_run_succeeded,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
    mock_progress.stop.assert_called_once()


@pytest.mark.parametrize("name,value", [("timeout", 0), ("interval", 0)])
def test_wait_rejects_non_positive_bounds(name, value):
    kwargs = {"timeout": 1, "interval": 1, name: value}
    with pytest.raises(InvalidArgumentValueError, match=f"--{name}"):
        wait_for_resource(
            MagicMock(),
            lambda: {},
            resource_exists,
            sleeper=lambda _: None,
            **kwargs,
        )


def test_wait_preserves_explicit_exists_custom_and_updated_modes():
    assert (
        wait_for_resource(
            MagicMock(),
            lambda: {},
            provisioning_succeeded,
            exists=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )
    assert (
        wait_for_resource(
            MagicMock(),
            lambda: {"provisioningState": "Succeeded"},
            resource_exists,
            created=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )


def test_wait_explicit_predicate_surfaces_failed_provisioning_state():
    with pytest.raises(AzureResponseError, match="operation failed"):
        wait_for_resource(
            MagicMock(),
            lambda: {"properties": {"provisioningState": "Failed"}},
            resource_exists,
            created=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
    assert (
        wait_for_resource(
            MagicMock(),
            lambda: {"ready": True},
            provisioning_succeeded,
            custom="ready",
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )
    assert (
        wait_for_resource(
            MagicMock(),
            lambda: {"properties": {"provisioningState": "Succeeded"}},
            resource_exists,
            updated=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )


def test_wait_preserves_deleted_and_not_found_retry_semantics():
    assert (
        wait_for_resource(
            MagicMock(),
            MagicMock(side_effect=ResourceNotFoundError("gone")),
            provisioning_succeeded,
            deleted=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )

    getter = MagicMock(
        side_effect=[
            ResourceNotFoundError("not materialized"),
            {"ok": True},
        ]
    )
    assert (
        wait_for_resource(
            MagicMock(),
            getter,
            resource_exists,
            timeout=2,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )


def test_wait_updated_propagates_not_found_like_azure_cli():
    with pytest.raises(ResourceNotFoundError):
        wait_for_resource(
            MagicMock(),
            MagicMock(side_effect=ResourceNotFoundError("missing")),
            provisioning_succeeded,
            updated=True,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )


def test_wait_retries_transient_sdk_not_found():
    response = MagicMock(status_code=404)
    error = HttpResponseError(response=response)
    getter = MagicMock(side_effect=[error, {"ready": True}])
    assert (
        wait_for_resource(
            MagicMock(),
            getter,
            resource_exists,
            timeout=2,
            interval=1,
            sleeper=lambda _: None,
        )
        is None
    )


def test_wait_propagates_non_not_found_sdk_error():
    response = MagicMock(status_code=403)
    error = HttpResponseError(response=response)
    with pytest.raises(HttpResponseError):
        wait_for_resource(
            MagicMock(),
            MagicMock(side_effect=error),
            resource_exists,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )


def test_wait_times_out_with_last_observation():
    with pytest.raises(CLIError, match="Accepted"):
        wait_for_resource(
            MagicMock(),
            lambda: {"properties": {"provisioningState": "Accepted"}},
            provisioning_succeeded,
            timeout=1,
            interval=1,
            sleeper=lambda _: None,
        )


def test_all_wait_command_wrappers_bind_their_resource_getters(mocker):
    resource = {
        "name": "endpoint",
        "linkingState": "Succeeded",
        "properties": {
            "provisioningState": "Succeeded",
            "membershipState": "Ready",
            "status": "Succeeded",
            "messaging": {
                "endpoints": {
                    "hub": {
                        "endpointType": IOT_HUB_ENDPOINT_TYPE,
                        "linkingState": "Succeeded",
                    }
                }
            },
            "provisioning": {
                "endpoints": {
                    "endpoint": {
                        "endpointType": DPS_ENDPOINT_TYPE,
                        "linkingState": "Succeeded",
                    }
                }
            },
            "updating": {
                "endpoints": {
                    "endpoint": {
                        "endpointType": SU_ENDPOINT_TYPE,
                        "linkingState": "Succeeded",
                    }
                }
            },
        },
    }
    provider = MagicMock()
    for method_name in (
        "show",
        "auth_show",
        "hub_show",
        "dps_show",
        "su_show",
        "show_update",
        "_get_namespace",
    ):
        getattr(provider, method_name).return_value = resource
    provider_types = {}
    for provider_name in (
        "NamespaceProvider",
        "CertificateAuthorityProvider",
        "CertificatePolicyProvider",
        "RegistryDeviceProvider",
        "GroupProvider",
        "JobProvider",
        "JobRunProvider",
        "LinkProvider",
        "UpdateInstanceProvider",
        "SoftwareUpdateProvider",
    ):
        provider_types[provider_name] = mocker.patch.object(
            commands_wait,
            provider_name,
            return_value=provider,
        )

    captured_conditions = []

    def run_getter(_cmd, getter, condition, *_args):
        value = getter()
        captured_conditions.append(condition(value))
        return value

    mocker.patch.object(commands_wait, "_wait", side_effect=run_getter)
    cmd = MagicMock()
    namespace_client = MagicMock()

    assert commands_wait.adr_namespace_wait(cmd, "ns", "rg") is resource
    assert commands_wait.adr_ca_wait(cmd, "ca", "ns", "rg") is resource
    assert (
        commands_wait.adr_ca_policy_wait(
            cmd, "policy", "ca", "ns", "rg"
        )
        is resource
    )
    assert (
        commands_wait.adr_registry_device_wait(
            cmd,
            "ns",
            "rg",
            external_device_id="external-42",
        )
        is resource
    )
    assert (
        commands_wait.adr_registry_device_auth_wait(
            cmd, "default", "device", "ns", "rg"
        )
        is resource
    )
    assert (
        commands_wait.adr_link_wait(
            cmd,
            namespace_client,
            "ns",
            "rg",
            hub_endpoint_name="hub",
        )
        is resource
    )
    assert (
        commands_wait.adr_link_hub_wait(
            cmd, namespace_client, "hub", "ns", "rg"
        )
        is resource
    )
    assert (
        commands_wait.adr_link_dps_wait(
            cmd, namespace_client, "endpoint", "ns", "rg"
        )
        is resource
    )
    assert (
        commands_wait.adr_link_su_wait(
            cmd, namespace_client, "endpoint", "ns", "rg"
        )
        is resource
    )
    assert commands_wait.adr_su_instance_wait(
        cmd, "instance", "rg"
    ) is resource
    assert (
        commands_wait.adr_su_software_update_wait(
            cmd, "ns", "rg", "provider", "update", "1.0"
        )
        is resource
    )
    assert commands_wait.adr_group_wait(
        cmd, "group", "ns", "rg"
    ) is resource
    assert commands_wait.adr_job_wait(
        cmd, "job", "ns", "rg"
    ) is resource
    assert commands_wait.adr_job_run_wait(
        cmd, "job", "run", "ns", "rg"
    ) is resource

    assert len(captured_conditions) == 14
    assert all(result.complete for result in captured_conditions)
    provider.show.assert_any_call("ns", "rg")
    provider.show.assert_any_call("ca", "ns", "rg")
    provider.show.assert_any_call("policy", "ca", "ns", "rg")
    provider.show.assert_any_call("instance", "rg")
    provider.auth_show.assert_called_once_with(
        "default", "device", "ns", "rg"
    )
    assert provider._get_namespace.call_count == 4
    assert provider_types["LinkProvider"].call_args_list == [
        call(cmd, client=namespace_client),
        call(cmd, client=namespace_client),
        call(cmd, client=namespace_client),
        call(cmd, client=namespace_client),
    ]
    provider.hub_show.assert_not_called()
    provider.dps_show.assert_not_called()
    provider.su_show.assert_not_called()
    provider.show_update.assert_called_once_with(
        "ns", "rg", "provider", "update", "1.0"
    )


def test_endpoint_wait_keeps_custom_predicates_on_namespace(mocker):
    provider = MagicMock()
    namespace = {"properties": {"ready": True}}
    provider._get_namespace.return_value = namespace
    provider.hub_show.return_value = {"linkingState": "Succeeded"}
    mocker.patch.object(commands_wait, "LinkProvider", return_value=provider)

    def run_getter(_cmd, getter, _condition, *_args):
        return getter()

    mocker.patch.object(commands_wait, "_wait", side_effect=run_getter)

    assert (
        commands_wait.adr_link_hub_wait(
            MagicMock(),
            MagicMock(),
            "hub",
            "ns",
            "rg",
            custom="properties.ready",
        )
        is namespace
    )
    provider._get_namespace.assert_called_once_with("ns", "rg")
    provider.hub_show.assert_not_called()


def test_endpoint_wait_uses_projected_endpoint_for_exists(mocker):
    provider = MagicMock()
    endpoint = {"name": "hub", "linkingState": "Succeeded"}
    provider.hub_show.return_value = endpoint
    mocker.patch.object(commands_wait, "LinkProvider", return_value=provider)

    def run_getter(_cmd, getter, _condition, *_args):
        return getter()

    mocker.patch.object(commands_wait, "_wait", side_effect=run_getter)

    assert (
        commands_wait.adr_link_hub_wait(
            MagicMock(), MagicMock(), "hub", "ns", "rg", exists=True
        )
        is endpoint
    )
    provider.hub_show.assert_called_once_with("hub", "ns", "rg")
    provider._get_namespace.assert_not_called()


def test_command_wait_common_wrapper_forwards_standard_options(mocker):
    delegated = mocker.patch.object(commands_wait, "wait_for_resource")
    cmd = MagicMock()
    getter = MagicMock()

    commands_wait._wait(  # pylint: disable=protected-access
        cmd,
        getter,
        resource_exists,
        10,
        2,
        True,
        False,
        False,
        False,
        "ready",
    )

    delegated.assert_called_once_with(
        cmd.cli_ctx,
        getter,
        resource_exists,
        timeout=10,
        interval=2,
        created=True,
        updated=False,
        deleted=False,
        exists=False,
        custom="ready",
    )
