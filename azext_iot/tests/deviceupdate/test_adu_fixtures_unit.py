# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from azext_iot.tests.deviceupdate import conftest as fixtures


@pytest.mark.parametrize("marker", [None, SimpleNamespace(kwargs={}), SimpleNamespace(kwargs={"instance_count": 0})])
def test_no_adu_hubs_without_instance_request(monkeypatch, marker):
    cli = Mock()
    monkeypatch.setattr(fixtures, "cli", cli)
    request = Mock()
    request.node.get_closest_marker.return_value = marker
    assert fixtures._iothub_provisioner(request) is None
    cli.invoke.assert_not_called()


def test_adu_dependency_hubs_enable_required_shared_access(monkeypatch):
    cli = Mock()
    monkeypatch.setattr(fixtures, "cli", cli)
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.side_effect = [{"id": "hub-1"}, {"id": "hub-2"}]
    request = Mock()
    request.node.get_closest_marker.return_value = SimpleNamespace(kwargs={"instance_count": 2})

    assert fixtures._iothub_provisioner(request) == {"hub-1": {"id": "hub-1"}, "hub-2": {"id": "hub-2"}}
    assert cli.invoke.call_count == 2
    for call in cli.invoke.call_args_list:
        assert "--disable-local-auth false" in call.args[0]
        assert f"--location {fixtures.HUB_TEST_LOCATION}" in call.args[0]
        assert f"-g {fixtures.ACCOUNT_RG}" in call.args[0]


def test_adu_hub_provisioning_failure_is_not_accepted(monkeypatch):
    cli = Mock()
    monkeypatch.setattr(fixtures, "cli", cli)
    cli.invoke.return_value.success.return_value = False
    request = Mock()
    request.node.get_closest_marker.return_value = SimpleNamespace(kwargs={"instance_count": 1})
    with pytest.raises(RuntimeError, match="Failed to provision iot hub"):
        fixtures._iothub_provisioner(request)
    cli.invoke.return_value.as_json.assert_not_called()
