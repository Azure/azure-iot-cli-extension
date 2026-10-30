# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.pipeline.transport import HttpRequest, RequestsTransport

from azext_iot.tests.dps.core import test_dps_unit_capacity_int as scenario


def test_capacity_live_case_requires_admission_before_resource_reads(mocker):
    mocker.patch.object(scenario._phase_receipts, "settings", return_value=None)
    read = mocker.patch.object(scenario.fixtures, "_find_dps_by_name")
    with pytest.raises(pytest.UsageError, match="admitted"):
        scenario.test_dps_unit_capacity_owned_lifecycle(mocker.Mock())
    read.assert_not_called()


def test_capacity_request_observer_is_read_only(mocker):
    request = HttpRequest("PUT", "https://centraluseuap.management.azure.com/resource")
    send = mocker.patch.object(RequestsTransport, "send", return_value="unchanged")
    transport = RequestsTransport()
    with scenario._observe_management_requests() as observed:
        assert transport.send(request, timeout=1) == "unchanged"
    assert observed == [("PUT", "/resource")]
    send.assert_called_once_with(transport, request, timeout=1)
    transport.close()


@pytest.mark.parametrize("regression", [False, True])
def test_capacity_live_lifecycle_is_sequential_and_cleans_unexpected_allocation(mocker, regression):
    resources, commands, deleted, events = {}, [], [], []
    uid = "a" * 32
    cli = SimpleNamespace(output="")
    mocker.patch.object(scenario, "EmbeddedCLI", return_value=cli)
    mocker.patch.object(scenario._phase_receipts, "settings", return_value=True)
    mocker.patch.object(scenario._phase, "get_phase", return_value=scenario._phase.REGULAR)
    mocker.patch.object(scenario.fixtures, "_get_run_uid", return_value=uid)
    mocker.patch.object(scenario.fixtures, "ENTITY_RG", "rg")
    mocker.patch.object(scenario.fixtures, "ENTITY_LOCATION", "centraluseuap")
    mocker.patch.object(scenario.fixtures, "_find_dps_by_name", side_effect=lambda name: deepcopy(resources.get(name)))
    receipt = mocker.patch.object(scenario._phase_receipts, "before_create")
    created = mocker.patch.object(scenario._phase_receipts, "after_create")
    mocker.patch.object(scenario._phase_runtime, "owned_write", side_effect=lambda *_: nullcontext())

    @contextmanager
    def observer():
        events.clear()
        yield events

    mocker.patch.object(scenario, "_observe_management_requests", observer)

    def cleanup(name, *_):
        deleted.append(name)
        resources.pop(name, None)

    mocker.patch.object(scenario.fixtures, "_cleanup_created_resource", side_effect=cleanup)

    def invoke(_cli, command, **_):
        commands.append(command)
        words = command.split()
        if words[2] == "list":
            result = list(resources.values())
        else:
            name = words[words.index("--name") + 1]
            if words[2] == "create":
                if command.endswith(("--unit 0", "--unit -1")) and not regression:
                    raise InvalidArgumentValueError("--unit must be an integer greater than or equal to 1.")
                assert not resources, "A second owned DPS must not overlap the first."
                resources[name] = {
                    "id": name, "sku": {"capacity": 1}, "tags": {},
                    "properties": {"provisioningState": "Succeeded", "disableLocalAuth": True},
                }
            elif "sku.capacity=" in command:
                events.append(("GET", name))
                raise InvalidArgumentValueError("sku.capacity must be an integer greater than or equal to 1.")
            else:
                resources[name]["tags"]["unitValidation"] = "passed"
            result = deepcopy(resources[name])
        return SimpleNamespace(as_json=lambda: result)

    mocker.patch.object(scenario, "invoke_checked", side_effect=invoke)
    if regression:
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            scenario.test_dps_unit_capacity_owned_lifecycle(mocker.Mock())
        assert len(deleted) == 1 and created.call_count == 0
    else:
        scenario.test_dps_unit_capacity_owned_lifecycle(mocker.Mock())
        assert len(deleted) == created.call_count == receipt.call_count == 2
        creates = [command for command in commands if "dps create" in command]
        assert creates[0].endswith("--unit 0") and creates[1].endswith("--unit 1")
        assert creates[2].endswith("--unit -1") and "--unit" not in creates[3]
    assert not resources
