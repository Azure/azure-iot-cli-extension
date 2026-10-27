# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for the combined command's DPS-before-Hub mutation boundary."""

from copy import deepcopy
from types import MethodType
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError, AzureResponseError, InvalidArgumentValueError, RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.tests.adr.test_adr_link_propagation_unit import Clock
from azext_iot.tests.adr.test_adr_link_unit import DPS_ID, HUB_ID, UAMI_ID

NS_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"


@pytest.fixture
def combined(fixture_link_provider, mocker):
    provider = fixture_link_provider
    initial = {
        "id": NS_ID, "location": "centraluseuap",
        "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
        "properties": {
            "provisioningState": "Succeeded",
            "provisioning": {"endpoints": {"future": {"endpointType": "Microsoft.Future/provisioning"}}},
            "messaging": {"endpoints": {"future": {"endpointType": "Microsoft.Future/messaging"}}},
            "updating": {"endpoints": {"su": {"endpointType": "Microsoft.DeviceUpdate/updateInstances"}}},
        },
    }
    ready = deepcopy(initial)
    ready["properties"]["provisioning"]["endpoints"]["dps"] = {
        "endpointType": DPS_ENDPOINT_TYPE, "resourceId": DPS_ID, "linkingState": "Succeeded",
        "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
    }
    args = {
        "namespace_name": "ns", "resource_group_name": "rg",
        "hub_endpoint_name": "hub", "hub_resource_id": HUB_ID,
        "dps_endpoint_name": "dps", "dps_resource_id": DPS_ID,
        "dps_mi_user_assigned": UAMI_ID, "hub_mi_user_assigned": UAMI_ID,
        "hub_availability": "Available", "hub_allocation_weight": 25,
    }
    provider.client.namespaces.get.side_effect = [initial, ready]
    provider.client.namespaces.begin_update.return_value = Mock()
    provider._get_target = Mock(side_effect=AzureResponseError("synthetic recovery preflight failure"))
    mocker.patch.object(provider, "_await_terminal", side_effect=lambda poller, **_: poller.result())
    clock = Clock()
    mocker.patch("azext_iot.adr.providers.link.monotonic", side_effect=clock.time)
    mocker.patch("azext_iot.adr.providers.link.sleep", side_effect=clock.sleep)
    return provider, args, initial, ready


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("identity_kind", ["user", "system", "hub-omitted"])
def test_combined_preflights_both_then_waits_exact_dps_before_hub(combined, no_wait, identity_kind):
    provider, args, initial, ready = combined
    events = []
    if identity_kind == "system":
        args.update(dps_mi_user_assigned=None, hub_mi_user_assigned=None,
                    dps_mi_system_assigned=True, hub_mi_system_assigned=True)
        ready["properties"]["provisioning"]["endpoints"]["dps"]["inboundCallerIdentity"] = {"type": "SystemAssigned"}
    elif identity_kind == "hub-omitted":
        args["hub_mi_user_assigned"] = None
    expected_dps = deepcopy(ready["properties"]["provisioning"]["endpoints"]["dps"])
    expected_dps.pop("linkingState")
    expected_hub = {"endpointType": IOT_HUB_ENDPOINT_TYPE, "resourceId": HUB_ID,
                    "provisioning": {"availability": "Available", "allocationWeight": 25}}
    if identity_kind != "hub-omitted":
        expected_hub["inboundCallerIdentity"] = deepcopy(expected_dps["inboundCallerIdentity"])
    pending = deepcopy(ready)
    pending["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] = "InProgress"
    final = deepcopy(ready)
    final["properties"]["messaging"]["endpoints"]["hub"] = {**expected_hub, "linkingState": "Succeeded"}
    dps_poller, hub_poller = Mock(), Mock()
    # A completed namespace LRO is NOT sufficient: the first endpoint GET is still InProgress.
    dps_poller.result.return_value = deepcopy(ready)
    hub_poller.result.return_value = final
    observations = iter([initial, pending, ready, final])

    def get(**_):
        ns = next(observations)
        if ns is not initial and ns is not final:
            events.append("GET DPS " + ns["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"])
        return ns

    def preflight(**kwargs):
        events.append("preflight " + kwargs["link_type"])
        kwargs["rbac_requests"].append(kwargs["link_type"])
        return {}

    def rbac(requests):
        assert requests == ["dps", "hub"]
        events.append("RBAC both")

    def update(**kwargs):
        properties = kwargs["properties"]["properties"]
        assert kwargs["namespace_name"] == "ns" and kwargs["resource_group_name"] == "rg"
        if "provisioning" in properties:
            assert properties == {"provisioning": {"endpoints": {"dps": expected_dps}}}
            events.append("PATCH DPS")
            return dps_poller
        assert events[-1] == "GET DPS Succeeded"
        assert properties == {"messaging": {"endpoints": {"hub": expected_hub}}}
        events.append("PATCH Hub")
        return hub_poller

    provider.client.namespaces.get.side_effect = get
    provider._preflight_link.side_effect = preflight
    provider._rbac.ensure_many.side_effect = rbac
    provider.client.namespaces.begin_update.side_effect = update
    result = provider.link_add(**args, no_wait=no_wait)
    assert events == [
        "preflight dps", "preflight hub", "RBAC both", "PATCH DPS",
        "GET DPS InProgress", "GET DPS Succeeded", "PATCH Hub",
    ]
    dps_poller.result.assert_called_once()
    assert hub_poller.result.call_count == (0 if no_wait else 1)
    assert result is hub_poller if no_wait else result == final
    assert final["properties"]["updating"] == initial["properties"]["updating"]
    assert all(final["properties"][section]["endpoints"]["future"] == initial["properties"][section]["endpoints"]["future"]
               for section in ("provisioning", "messaging"))


@pytest.mark.parametrize("failure", [
    "Failed", "Canceled", "Cancelled", "InProgress", "missing", "nested-status-only",
    "wrong-target", "wrong-identity", "wrong-type", "namespace-Failed", "namespace-Updating", "GET-error",
])
@pytest.mark.parametrize("no_wait", [False, True])
def test_combined_dps_failure_or_timeout_never_submits_hub(combined, failure, no_wait, caplog):
    provider, args, initial, observed = combined
    endpoint = observed["properties"]["provisioning"]["endpoints"]["dps"]
    service_error = HttpResponseError("synthetic DPS GET error")
    if failure == "missing":
        del observed["properties"]["provisioning"]["endpoints"]["dps"]
    elif failure == "nested-status-only":
        endpoint.pop("linkingState")
        endpoint["provisioningStatus"] = {"status": "Succeeded"}
    elif failure == "wrong-target":
        endpoint["resourceId"] = DPS_ID + "-other"
    elif failure == "wrong-identity":
        endpoint["inboundCallerIdentity"]["userAssignedIdentity"] = UAMI_ID + "-other"
    elif failure == "wrong-type":
        endpoint["endpointType"] = IOT_HUB_ENDPOINT_TYPE
    elif failure.startswith("namespace-"):
        observed["properties"]["provisioningState"] = failure.split("-")[1]
    else:
        endpoint["linkingState"] = failure
    if failure == "Failed":
        endpoint["linkingError"] = {
            "code": "AdrMiNotAuthorized",
            "message": f"The namespace identity is not authorized to read '{DPS_ID}'.",
        }
    provider.client.namespaces.get.side_effect = [initial] + (
        [service_error] if failure == "GET-error" else [observed] * 3
    )
    with pytest.raises((CLIError, HttpResponseError)) as caught:
        provider.link_add(**args, no_wait=no_wait, timeout_sec=3, wait_sec=1)
    if failure == "GET-error":
        assert caught.value is service_error
    elif failure == "Failed":
        assert "AdrMiNotAuthorized" in caplog.text
    elif failure in {"InProgress", "missing", "namespace-Updating"}:
        assert "timed out" in str(caught.value)
    provider.client.namespaces.begin_update.assert_called_once()
    assert list(provider.client.namespaces.begin_update.call_args.kwargs["properties"]["properties"]) == ["provisioning"]
    assert "Hub link was NOT submitted" in caplog.text
    assert "No rollback" in caplog.text


@pytest.mark.parametrize("stage", ["DPS-submit", "DPS-LRO", "Hub-submit", "Hub-LRO"])
def test_combined_propagates_write_errors_and_reports_partial_completion(combined, stage, caplog):
    provider, args, _, _ = combined
    error = HttpResponseError(f"synthetic {stage} error; correlation=original-correlation")
    if stage.endswith("submit"):
        provider.client.namespaces.begin_update.side_effect = [error] if stage.startswith("DPS") else [Mock(), error]
    else:
        provider._await_terminal.side_effect = [error] if stage.startswith("DPS") else [{}, error]
    with pytest.raises(HttpResponseError) as caught:
        provider.link_add(**args)
    assert caught.value is error
    assert provider.client.namespaces.begin_update.call_count == (1 if stage.startswith("DPS") else 2)
    assert ("Hub link was NOT submitted" if stage.startswith("DPS") else "DPS link was not rolled back") in caplog.text
    provider.client.namespaces.begin_delete.assert_not_called()


@pytest.mark.parametrize("stage", ["dps-target", "hub-target", "rbac"])
def test_combined_preflight_failures_precede_all_namespace_mutations(combined, stage):
    provider, args, _, _ = combined
    error = AzureResponseError("synthetic preflight failure")
    if stage == "rbac":
        provider._rbac.ensure_many.side_effect = error
    else:
        provider._preflight_link.side_effect = [error] if stage == "dps-target" else [{}, error]
    with pytest.raises(AzureResponseError) as caught:
        provider.link_add(**args)
    assert caught.value is error
    provider.client.namespaces.begin_update.assert_not_called()
    assert provider._rbac.ensure_many.call_count == (1 if stage == "rbac" else 0)


@pytest.mark.parametrize("changes", [
    {"dps_resource_id": HUB_ID}, {"hub_resource_id": DPS_ID},
    {"dps_mi_system_assigned": True}, {"hub_mi_system_assigned": True},
    {"dps_mi_user_assigned": HUB_ID}, {"hub_mi_user_assigned": DPS_ID},
    {"dps_mi_user_assigned": None},
])
def test_combined_validates_both_ids_and_identity_selections_before_preflight(combined, changes):
    provider, args, _, _ = combined
    args.update(changes)
    with pytest.raises((ArgumentUsageError, InvalidArgumentValueError, RequiredArgumentMissingError)):
        provider.link_add(**args)
    provider._preflight_link.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


def test_combined_real_hub_validation_fails_before_queued_dps_rbac(combined):
    provider, args, _, _ = combined
    provider._preflight_link = MethodType(LinkProvider._preflight_link, provider)
    target = {
        "location": "centraluseuap", "properties": {"provisioningState": "Succeeded"},
        "identity": {"userAssignedIdentities": {UAMI_ID: {"principalId": "target-user"}}},
        "sku": {"name": "S1"},
    }
    provider._get_target = Mock(side_effect=[target, {**target, "sku": {"name": "B1"}}])
    with pytest.raises(InvalidArgumentValueError, match="Standard"):
        provider.link_add(**args)
    assert provider._get_target.call_count == 2
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("collision", ["same-target", "different-target", "future-type", "capacity"])
def test_combined_rechecks_hub_collisions_after_dps_wait(combined, collision, caplog):
    provider, args, _, ready = combined
    endpoints = ready["properties"]["messaging"]["endpoints"]
    if collision == "capacity":
        endpoints.update({
            f"other-{index}": {"endpointType": IOT_HUB_ENDPOINT_TYPE, "resourceId": HUB_ID + str(index)}
            for index in range(10)
        })
    else:
        endpoints["hub"] = {
            "endpointType": "Microsoft.Future/messaging" if collision == "future-type" else IOT_HUB_ENDPOINT_TYPE,
            "resourceId": HUB_ID if collision == "same-target" else HUB_ID + "-other",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }
    original = deepcopy(ready)
    with pytest.raises(ArgumentUsageError):
        provider.link_add(**args)
    provider.client.namespaces.begin_update.assert_called_once()
    assert ready == original
    assert "DPS link was not rolled back" in caplog.text


@pytest.mark.parametrize("option", ["timeout_sec", "wait_sec"])
@pytest.mark.parametrize("value", [0, -1])
def test_combined_rejects_invalid_wait_options_before_preflight(combined, option, value):
    provider, args, _, _ = combined
    with pytest.raises(InvalidArgumentValueError, match="greater than zero"):
        provider.link_add(**args, **{option: value})
    provider.client.namespaces.get.assert_not_called()
    provider._preflight_link.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("scenario", ["late-success", "pending", "late-lro"])
@pytest.mark.parametrize("no_wait", [False, True])
def test_combined_deadline_includes_dps_lro_and_get_time(combined, mocker, scenario, no_wait):
    provider, args, initial, ready = combined
    elapsed = [0.0]
    sleeps = []
    mocker.patch("azext_iot.adr.providers.link.monotonic", side_effect=lambda: elapsed[0])
    observed = deepcopy(ready)
    if scenario == "pending":
        observed["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] = "InProgress"

    def get(**_):
        if provider.client.namespaces.get.call_count == 1:
            return initial
        elapsed[0] += 4 if scenario == "late-success" else 2
        return observed

    def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    def wait_lro(poller, **_):
        if scenario == "late-lro":
            elapsed[0] += 4
        return poller.result()

    provider.client.namespaces.get.side_effect = get
    provider._await_terminal.side_effect = wait_lro
    mocker.patch("azext_iot.adr.providers.link.sleep", side_effect=sleep)
    with pytest.raises(CLIError, match="timed out"):
        provider.link_add(**args, no_wait=no_wait, timeout_sec=3, wait_sec=2)
    provider.client.namespaces.begin_update.assert_called_once()
    assert provider.client.namespaces.get.call_count == (1 if scenario == "late-lro" else 2)
    assert sleeps == ([1] if scenario == "pending" else [])


def test_combined_wrapper_forwards_wait_options(combined, mocker):
    from azext_iot.adr import commands_link

    provider, args, _, _ = combined
    provider.link_add = Mock()
    mocker.patch.object(commands_link, "LinkProvider", return_value=provider)
    result = commands_link.adr_link_add(Mock(), Mock(), **args, no_wait=True, timeout=60, interval=1)
    assert result is provider.link_add.return_value
    assert provider.link_add.call_args.kwargs["timeout_sec"] == 60
    assert provider.link_add.call_args.kwargs["wait_sec"] == 1
    assert provider.link_add.call_args.kwargs["no_wait"] is True


@pytest.mark.parametrize("submission_seconds", [2, 3, 4])
@pytest.mark.parametrize("no_wait", [False, True])
def test_combined_submission_time_is_deducted_before_dps_lro_wait(combined, mocker, submission_seconds, no_wait):
    provider, args, initial, ready = combined
    elapsed = [0.0]
    mocker.patch("azext_iot.adr.providers.link.monotonic", side_effect=lambda: elapsed[0])

    def submit(**_):
        if provider.client.namespaces.begin_update.call_count == 1:
            elapsed[0] += submission_seconds
        return Mock()

    provider.client.namespaces.begin_update.side_effect = submit
    if submission_seconds >= 3:
        with pytest.raises(CLIError, match="timed out"):
            provider.link_add(**args, no_wait=no_wait, timeout_sec=3)
        provider._await_terminal.assert_not_called()
        provider.client.namespaces.begin_update.assert_called_once()
        provider.client.namespaces.get.assert_called_once()
    else:
        # The waited terminal Hub now needs its own actual Succeeded readback.
        final = deepcopy(ready)
        final["properties"]["messaging"]["endpoints"]["hub"] = {
            "endpointType": IOT_HUB_ENDPOINT_TYPE, "resourceId": HUB_ID, "linkingState": "Succeeded",
            "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
            "provisioning": {"availability": "Available", "allocationWeight": 25},
        }
        provider.client.namespaces.get.side_effect = [initial, ready, final]
        provider.link_add(**args, no_wait=no_wait, timeout_sec=3)
        assert provider._await_terminal.call_args_list[0].kwargs["timeout_sec"] == 1
        if not no_wait:
            assert provider._await_terminal.call_args_list[1].kwargs["timeout_sec"] == 1
        assert provider.client.namespaces.begin_update.call_count == 2
