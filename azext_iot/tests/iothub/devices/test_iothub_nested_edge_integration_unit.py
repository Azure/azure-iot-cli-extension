# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
from functools import partial

import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError

from azext_iot.tests.iothub._integration_helpers import wait_for_query_ids
from azext_iot.tests.iothub.devices import test_iothub_nested_edge_int as subject


@pytest.fixture
def nested_scenario(mocker):
    scenario = mocker.Mock()
    scenario.host_name = "owned-hub.test"
    scenario.entity_rg = "rg"
    scenario.generate_device_names.side_effect = [["child-a", "child-b", "child-c"], ["edge-a", "edge-b"]]
    scenario.set_cmd_auth_type.side_effect = lambda command, **kwargs: f"{command} --auth-type {kwargs['auth_type']}"
    scenario.check.side_effect = lambda path, value: (path, value)
    scenario.query_rows = iter([
        ["child-b"], ["child-b"],
        ["child-a"], ["edge-a", "child-a", "child-c"],
        ["child-a", "child-c"], [],
        [],
    ])
    scenario.events = []

    def command(command, **kwargs):
        args = shlex.split(command)
        result = mocker.Mock()
        if args[2:5] == ["device-identity", "children", "list"]:
            scenario.events.append(("query", args[args.index("-d") + 1]))
            result.get_output_in_json.side_effect = lambda: next(scenario.query_rows)
        elif args[2:5] == ["device-identity", "children", "remove"] and "--remove-all" in args:
            scenario.events.append((
                "remove-all", args[args.index("-d") + 1], kwargs.get("expect_failure", False),
            ))
        return result

    scenario.cmd.side_effect = command
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    scenario.wait = mocker.patch.object(
        subject, "wait_for_query_ids", side_effect=partial(wait_for_query_ids, attempts=3, wait=0),
    )
    return scenario


@pytest.mark.parametrize("auth_phase", ["login", "key"])
def test_remove_all_waits_for_complete_targets_then_an_empty_view(mocker, nested_scenario, auth_phase):
    scenario = nested_scenario
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", [auth_phase])
    subject.TestIoTHubNestedEdge.test_iothub_nested_edge(scenario)
    assert [call.args[1] for call in scenario.wait.call_args_list] == [
        ["child-b"], ["edge-a", "child-a", "child-c"], [],
    ]
    assert scenario.events == [
        ("query", "edge-a"), ("query", "edge-a"),
        ("remove-all", "child-a", True),
        ("query", "edge-b"), ("query", "edge-b"),
        ("remove-all", "edge-b", False),
        ("query", "edge-b"), ("query", "edge-b"),
        ("remove-all", "edge-b", True),
        ("query", "edge-b"),
    ]
    assert all(call.kwargs["auth_type"] == auth_phase for call in scenario.set_cmd_auth_type.call_args_list)
    negatives = [call for call in scenario.cmd.call_args_list if call.kwargs.get("expect_failure")]
    assert len(negatives) == 13


@pytest.mark.parametrize("stage", ["before_removal", "after_removal"])
@pytest.mark.parametrize("failure", ["omission", "service", "transport"])
def test_unready_or_failed_query_blocks_the_next_removal_without_replay(nested_scenario, stage, failure):
    scenario = nested_scenario
    prefix = [["child-b"], ["child-b"]]
    if stage == "after_removal":
        prefix.append(["edge-a", "child-a", "child-c"])
    error = {
        "service": HttpResponseError("Readiness query failed"),
        "transport": ServiceRequestError("Readiness transport failed"),
    }.get(failure)
    observations = [error] if error else [["child-a"]] * 3

    def query_rows():
        for value in prefix + observations:
            if isinstance(value, Exception):
                raise value
            yield value

    scenario.query_rows = query_rows()
    with pytest.raises(type(error) if error else AssertionError) as raised:
        subject.TestIoTHubNestedEdge.test_iothub_nested_edge(scenario)
    if error:
        assert raised.value is error
    removals = [event for event in scenario.events if event[:2] == ("remove-all", "edge-b")]
    assert removals == ([] if stage == "before_removal" else [("remove-all", "edge-b", False)])
