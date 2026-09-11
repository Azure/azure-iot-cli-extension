# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path

import pytest
from azure.cli.core import get_default_cli

from azext_iot.tests import helpers
from azext_iot.tests.conftest import integration_auth_defaults


@pytest.mark.parametrize("nodeid,expected", [
    ("tests/test_hub_int.py::test_devices", "login"),
    ("tests/test_hub_unit.py::test_internal_error", "key"),
], ids=["integration", "unit"])
def test_integration_auth_defaults_are_scoped(mocker, monkeypatch, nodeid, expected):
    request = mocker.Mock()
    request.node.path = Path(nodeid.partition("::")[0])
    for option in ("IOTHUB", "IOTDPS"):
        monkeypatch.setenv(f"AZURE_DEFAULTS_{option}-DATA-AUTH-TYPE", "key")
    integration_auth_defaults.__wrapped__(request, monkeypatch)
    config = get_default_cli().config
    for option in ("iothub", "iotdps"):
        assert config.get("defaults", f"{option}-data-auth-type") == expected


def test_service_scenarios_use_login_without_removing_auth_helper_coverage():
    assert helpers.DATAPLANE_AUTH_TYPES == ["login"]
    assert helpers.set_cmd_auth_type("command", "login", "cs") == "command --auth-type login"
    assert helpers.set_cmd_auth_type("command", "key", "cs") == "command --auth-type key"
    assert helpers.set_cmd_auth_type("command", "cstring", "cs") == "command --login cs"


def test_hub_cleanup_uses_login(mocker):
    invoke = mocker.patch.object(helpers.cli, "invoke")
    invoke.return_value.success.return_value = True
    invoke.return_value.as_json.side_effect = [
        [{"deviceId": "device"}], [{"id": "deployment"}], [{"id": "configuration"}],
    ]
    helpers.clean_up_iothub_device_config("hub", "rg")
    assert invoke.call_count == 6
    for call in invoke.call_args_list:
        assert call.args[0].endswith("--auth-type login")


@pytest.mark.parametrize("status", [404, 403, 409, 500])
@pytest.mark.parametrize("error_type", ["legacy", "modern"])
def test_hub_cleanup_does_not_retry_missing_targets_or_hide_other_errors(mocker, status, error_type):
    from azure.core.exceptions import HttpResponseError
    from msrestazure.azure_exceptions import CloudError

    response = mocker.Mock(status_code=status, reason="cleanup failure")
    response.text.return_value = '{"Message": "cleanup failure"}'
    response.json.return_value = {"Message": "cleanup failure"}
    error = CloudError(response, error="cleanup failure") if error_type == "legacy" else HttpResponseError(response=response)
    listed = mocker.Mock()
    listed.success.return_value = True
    listed.as_json.side_effect = [[{"deviceId": "stale-device"}], [], []]
    invoke = mocker.patch.object(helpers.cli, "invoke", side_effect=[listed, listed, listed, error, error, error])
    sleep = mocker.patch("time.sleep")
    if status == 404:
        helpers.clean_up_iothub_device_config("hub", "rg")
        assert invoke.call_count == 4
        sleep.assert_not_called()
    else:
        with pytest.raises(type(error)) as caught:
            helpers.clean_up_iothub_device_config("hub", "rg")
        assert caught.value is error
        assert invoke.call_count == 6
        assert sleep.call_count == 2
    assert all(call.kwargs["capture_stderr"] for call in invoke.call_args_list[3:])


@pytest.mark.parametrize("location", [None, "centraluseuap"])
def test_storage_creation_preserves_optional_location(mocker, location):
    cmd = mocker.Mock()
    cmd.return_value.get_output_in_json.side_effect = [[], {"connectionString": "test-storage-connection"}]
    result = helpers.create_storage_account(cmd, "account", "container", "rg", "hub", location=location)
    assert result == "test-storage-connection"
    create_command = cmd.call_args_list[1].args[0]
    assert create_command.startswith("storage account create -n account -g rg ")
    if location:
        assert create_command.endswith(f"--location {location}")
    else:
        assert "--location" not in create_command
