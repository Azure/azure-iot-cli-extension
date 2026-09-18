# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import BadRequestError, CLIInternalError

from azext_iot.tests.iothub.message_endpoint import test_iothub_message_endpoint_int as subject


@pytest.fixture
def storage_scenario(mocker):
    client = SimpleNamespace(exception_handler=mocker.Mock(return_value=1), result=SimpleNamespace(error=None))
    mocker.patch.object(subject.cli, "az_cli", client)
    mocker.patch.object(subject.cli, "user_subscription", None)
    mocker.patch.object(subject.cli, "capture_stderr", False)
    scenario = SimpleNamespace(
        calls=[], endpoints={}, fail_at=None, corrupt_at=None, reads=0,
        error=BadRequestError("IH400117: storage endpoint authorization rejected"),
    )
    build_expected = subject.build_expected_endpoint

    def remember_expected(*args, **kwargs):
        expected = build_expected(*args, **kwargs)
        scenario.endpoints[expected["name"]] = expected
        return expected

    mocker.patch.object(subject, "build_expected_endpoint", side_effect=remember_expected)
    scenario.assertions = mocker.spy(subject, "assert_endpoint_properties")

    def invoke(args, out_file):
        assert args[:3] == ["iot", "hub", "message-endpoint"]
        assert args[args.index("-n") + 1] == "owned-hub"
        assert args[args.index("-g") + 1] == "owned-rg"
        scenario.calls.append(args)
        client.result.error = None
        if len(scenario.calls) - 1 == scenario.fail_at:
            client.result.error = scenario.error
            return 7
        operation = args[3]
        name = args[args.index("--en") + 1] if "--en" in args else None
        output = None
        if operation == "show":
            output = deepcopy(scenario.endpoints[name])
            if scenario.reads == scenario.corrupt_at:
                output["encoding"] = "incorrect"
            scenario.reads += 1
        elif operation == "list":
            endpoints = list(scenario.endpoints.values())
            output = endpoints if "-t" in args else {"storageContainers": endpoints}
        elif operation == "delete":
            if name:
                del scenario.endpoints[name]
            else:
                scenario.endpoints.clear()
        else:
            assert operation in ("create", "update")
        out_file.write(json.dumps(output))
        return 0

    client.invoke = mocker.Mock(side_effect=invoke)
    scenario.infrastructure = (
        [{"hub": {
            "name": "owned-hub", "resourcegroup": "owned-rg", "subscriptionid": "sub",
            "identity": {"userAssignedIdentities": {"owned-identity": {}}},
        }}],
        {
            "connectionString": "DefaultEndpointsProtocol=https;AccountName=offline",
            "storage": {"primaryEndpoints": {"blob": "https://offline.blob.core.windows.net/"}},
            "container": {"name": "container"},
        },
    )
    return scenario


def test_storage_lifecycle_preserves_all_success_assertions(storage_scenario):
    subject.test_iot_storage_endpoint_lifecycle(storage_scenario.infrastructure)
    assert len(storage_scenario.calls) == 19
    assert storage_scenario.assertions.call_count == 6
    assert storage_scenario.endpoints == {}


@pytest.mark.parametrize("failure_kind", ["service", "exit"])
@pytest.mark.parametrize("fail_at", range(19))
def test_storage_lifecycle_preserves_original_failure_without_followup(storage_scenario, failure_kind, fail_at):
    storage_scenario.fail_at = fail_at
    if failure_kind == "exit":
        storage_scenario.error = None
    with pytest.raises(BadRequestError if failure_kind == "service" else CLIInternalError) as raised:
        subject.test_iot_storage_endpoint_lifecycle(storage_scenario.infrastructure)
    if failure_kind == "service":
        assert raised.value is storage_scenario.error
    else:
        assert "failed with exit code 7" in str(raised.value)
    assert len(storage_scenario.calls) == fail_at + 1
    assert "Issue parsing received payload" not in str(raised.value)
    if fail_at == 3:
        assert storage_scenario.calls[-1][3:5] == ["create", "storage-container"]
        assert storage_scenario.calls[-1][storage_scenario.calls[-1].index("--identity") + 1] == "[system]"


@pytest.mark.parametrize("corrupt_at", range(6))
def test_storage_lifecycle_still_rejects_wrong_endpoint_properties(storage_scenario, corrupt_at):
    storage_scenario.corrupt_at = corrupt_at
    with pytest.raises(AssertionError):
        subject.test_iot_storage_endpoint_lifecycle(storage_scenario.infrastructure)
    assert storage_scenario.assertions.call_count == corrupt_at + 1
    assert storage_scenario.calls[-1][3] == "show"
