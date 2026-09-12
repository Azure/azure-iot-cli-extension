# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import logging
from functools import partial

import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError

from azext_iot.tests.iothub._integration_helpers import wait_for_query_ids
from azext_iot.tests.iothub.jobs import test_iothub_jobs_int as subject


@pytest.mark.parametrize("statistics", [
    None,
    {"deviceCount": 0, "succeededCount": 0, "failedCount": 0},
    {"deviceCount": 2, "succeededCount": 2, "failedCount": 0, "extra": "not logged"},
])
def test_job_statistics_report_missing_or_actual_counters(capsys, statistics):
    subject._log_job_device_statistics({"jobId": "job", "deviceJobStatistics": statistics}, 2)
    output = capsys.readouterr().out
    prefix = "Hub job job: expected devices=2; service statistics="
    assert output.startswith(prefix)
    counters = json.loads(output[len(prefix):])
    assert set(counters) == {"deviceCount", "succeededCount", "failedCount", "pendingCount", "runningCount"}
    for name, value in counters.items():
        assert value == (statistics or {}).get(name)


def test_job_statistics_remain_visible_when_logging_is_disabled(capsys, monkeypatch):
    monkeypatch.setattr(logging.root.manager, "disable", logging.CRITICAL)
    subject._log_job_device_statistics(
        {"jobId": "job", "deviceJobStatistics": {"deviceCount": 0}}, 2,
    )
    assert '"deviceCount": 0' in capsys.readouterr().out


@pytest.fixture
def job_scenario(mocker):
    scenario = mocker.Mock()
    scenario.kwargs = {}
    scenario.host_name = "hub.test"
    scenario.entity_name = "hub"
    scenario.entity_rg = "rg"
    scenario.generate_device_names.side_effect = [["tag-one", "tag-two"], ["prop-one", "prop-two"]]
    scenario.generate_job_names.return_value = ["tag-job", "property-job", "cancel-job"]
    scenario.set_cmd_auth_type.side_effect = lambda command, **_kwargs: command
    scenario.check.side_effect = lambda path, value: (path, value)
    tag_result = {"jobId": "tag-job", "deviceJobStatistics": {"deviceCount": 2}}
    property_result = {"jobId": "property-job", "deviceJobStatistics": {"deviceCount": 2}}
    scenario.tag_result = tag_result
    scenario.property_result = property_result
    scenario.tag_ids = [{"deviceId": name} for name in ("tag-one", "tag-two")]
    scenario.property_ids = [{"deviceId": name} for name in ("prop-one", "prop-two")]
    scenario.cmd.return_value.get_output_in_json.side_effect = [
        scenario.tag_ids, tag_result, scenario.property_ids, property_result, [],
    ]
    scenario.statistics = mocker.patch.object(subject, "_log_job_device_statistics")
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    mocker.patch("time.sleep")
    mocker.patch.object(subject, "wait_for_query_ids", side_effect=partial(wait_for_query_ids, attempts=3, wait=0))
    return scenario


@pytest.mark.parametrize("auth_phase", ["login", "key"])
def test_job_scenario_checks_actual_twins_and_waits_for_both_target_cohorts(mocker, job_scenario, auth_phase):
    scenario = job_scenario
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", [auth_phase])
    scenario.cmd.return_value.get_output_in_json.side_effect = [
        scenario.tag_ids[:1], scenario.tag_ids, scenario.tag_result,
        scenario.property_ids[:1], scenario.property_ids, scenario.property_result, [],
    ]
    subject.TestIoTHubJobs.test_jobs(scenario)

    assert scenario.statistics.call_args_list == [
        mocker.call(scenario.tag_result, 2), mocker.call(scenario.property_result, 2),
    ]
    reads = [
        call for call in scenario.cmd.call_args_list
        if "device-twin show" in call.args[0] and "prop-" in call.args[0]
    ]
    assert len(reads) == 2
    assert all(call.kwargs["checks"] == [("properties.desired.arbitrary", "value")] for call in reads)
    tag_reads = [
        call for call in scenario.cmd.call_args_list
        if "device-twin show" in call.args[0] and "tag-" in call.args[0]
    ]
    assert len(tag_reads) == 2
    assert all(call.kwargs["checks"] == [("tags", {"deviceClass": "Class1, Class2, Class3"})] for call in tag_reads)
    conditions = ("deviceId in ['tag-one','tag-two']", "deviceId in ['prop-one','prop-two']")
    for condition, job_id in zip(conditions, ("tag-job", "property-job")):
        commands = [call.args[0] for call in scenario.set_cmd_auth_type.call_args_list]
        query = f'iot hub query -n hub.test -g rg -q "select deviceId from devices where {condition}"'
        assert commands.count(query) == 2
        create = next(call for call in scenario.cmd.call_args_list if f"--job-id {job_id} " in call.args[0])
        assert commands.index(create.args[0]) > max(index for index, command in enumerate(commands) if command == query)
        assert ("status", "completed") in create.kwargs["checks"]
        assert ("queryCondition", condition) in create.kwargs["checks"]
        assert ("updateTwin.etag", "*") in create.kwargs["checks"]
    assert all(call.kwargs["auth_type"] == auth_phase for call in scenario.set_cmd_auth_type.call_args_list)


@pytest.mark.parametrize("cohort", ["tags", "desired"])
@pytest.mark.parametrize("failure", ["omission", "service", "transport"])
def test_unready_or_failed_query_prevents_that_job_submission(job_scenario, cohort, failure):
    scenario = job_scenario
    before = [] if cohort == "tags" else [scenario.tag_ids, scenario.tag_result]
    error = {
        "service": HttpResponseError("Query authorization failed"),
        "transport": ServiceRequestError("Query transport failed"),
    }.get(failure)
    observations = [error] if error else [[]] * 3
    scenario.cmd.return_value.get_output_in_json.side_effect = before + observations
    with pytest.raises(type(error) if error else AssertionError) as raised:
        subject.TestIoTHubJobs.test_jobs(scenario)
    if error:
        assert raised.value is error
    blocked = "tag-job" if cohort == "tags" else "property-job"
    creates = [call for call in scenario.cmd.call_args_list if "iot hub job create" in call.args[0]]
    assert not any(f"--job-id {blocked} " in call.args[0] for call in creates)
    assert len(creates) == (0 if cohort == "tags" else 1)
    assert scenario.statistics.call_count == (0 if cohort == "tags" else 1)
