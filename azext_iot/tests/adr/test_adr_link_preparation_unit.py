# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.rbac import (
    ADU_FIRST_PARTY_APP_ID,
    GRAPH_SERVICE_PRINCIPALS_URL,
    LinkRbacManager,
)
from azext_iot.tests.adr import test_adr_link_int as subject


SU_ID = (
    "/subscriptions/fixture-sub/resourceGroups/fixture-rg/providers/"
    "Microsoft.DeviceUpdate/updateInstances/fixture"
)


@pytest.fixture()
def preparation(monkeypatch):
    test = Mock()
    test.cli_ctx = SimpleNamespace(cloud=SimpleNamespace(
        endpoints=SimpleNamespace(microsoft_graph_resource_id="https://graph.microsoft.com"),
    ))
    response = Mock()
    response.json.return_value = {"value": [{"id": "adu-principal"}]}
    manager = LinkRbacManager(test.cli_ctx, cli=Mock(), graph_get=Mock(return_value=response))
    manager._access_token = Mock(return_value="test-token")
    monkeypatch.setattr(subject, "LinkRbacManager", Mock(return_value=manager))
    monkeypatch.setattr(subject, "TEST_SUBSCRIPTION", "configured-sub")
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", "")
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_DISPOSABLE", False)
    return test, manager, response


@pytest.mark.parametrize("fixture_id,subscription", [("", "configured-sub"), (SU_ID, "fixture-sub")])
@pytest.mark.parametrize("error_type", [requests.HTTPError, requests.Timeout])
def test_su_graph_failure_precedes_all_resource_and_role_mutations(
    preparation, monkeypatch, fixture_id, subscription, error_type,
):
    test, manager, response = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", fixture_id)
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_DISPOSABLE", True)
    if error_type is requests.HTTPError:
        response.status_code = 403
        error = error_type("403 Client Error: Forbidden", response=response)
        response.raise_for_status.side_effect = error
    else:
        error = error_type("Graph request timed out")
        manager._graph_get.side_effect = error

    with pytest.raises(AzureResponseError, match="Could not query Microsoft Graph") as failure:
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert failure.value.__cause__ is error
    manager._access_token.assert_called_once_with(
        subscription, resource="https://graph.microsoft.com",
    )
    assert manager._graph_get.call_args.args == (GRAPH_SERVICE_PRINCIPALS_URL,)
    assert manager._graph_get.call_args.kwargs["params"] == {
        "$filter": f"appId eq '{ADU_FIRST_PARTY_APP_ID}'", "$select": "id",
    }
    assert manager._graph_get.call_args.kwargs["timeout"] == 30
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    manager.cli.invoke.assert_not_called()


def test_su_missing_adu_principal_fails_before_resources(preparation):
    test, manager, response = preparation
    response.json.return_value = {"value": []}

    with pytest.raises(AzureResponseError, match="Could not resolve the ADU first-party"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    manager.cli.invoke.assert_not_called()


def test_su_token_failure_fails_before_graph_or_resources(preparation):
    test, manager, _ = preparation
    manager._access_token.side_effect = AzureResponseError("Could not acquire an access token")

    with pytest.raises(AzureResponseError, match="Could not acquire an access token"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    manager._graph_get.assert_not_called()
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()


def test_su_successful_graph_preparation_precedes_provisioning(preparation):
    test, manager, response = preparation
    events = []

    def graph_get(*_args, **_kwargs):
        events.append("graph")
        return response

    def command(value):
        events.append(value)
        if value.startswith("identity create "):
            raise RuntimeError("Stop at the first provisioning command")
        return Mock(get_output_in_json=lambda: [])

    manager._graph_get.side_effect = graph_get
    test.cmd.side_effect = command

    with pytest.raises(RuntimeError, match="Stop at the first provisioning command"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert events[0] == "graph"
    assert events[1].startswith("identity create ")
    assert manager._adu_principal_ids == {"configured-sub": "adu-principal"}
    manager._graph_get.assert_called_once()


def test_su_non_disposable_fixture_still_skips_without_graph_or_mutation(preparation, monkeypatch):
    test, manager, _ = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID)

    with pytest.raises(pytest.skip.Exception, match="explicitly marked disposable"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    manager._graph_get.assert_not_called()
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
