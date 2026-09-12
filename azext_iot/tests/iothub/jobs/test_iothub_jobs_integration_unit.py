# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import logging

import pytest

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


def test_job_scenario_checks_actual_desired_properties_and_logs_both_jobs(mocker):
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
    scenario.cmd.return_value.get_output_in_json.side_effect = [tag_result, property_result, []]
    statistics = mocker.patch.object(subject, "_log_job_device_statistics")
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    mocker.patch("time.sleep")

    subject.TestIoTHubJobs.test_jobs(scenario)

    assert statistics.call_args_list == [mocker.call(tag_result, 2), mocker.call(property_result, 2)]
    reads = [
        call for call in scenario.cmd.call_args_list
        if "device-twin show" in call.args[0] and "prop-" in call.args[0]
    ]
    assert len(reads) == 2
    assert all(call.kwargs["checks"] == [("properties.desired.arbitrary", "value")] for call in reads)
