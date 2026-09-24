# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for full license information.
# --------------------------------------------------------------------------------------------

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
import jmespath


BASH = shutil.which("bash")
REPOSITORY = "Azure/azure-iot-cli-extension"
RELEASE_SCHEDULE = "17 14 * * *"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/int_test_schedule.yml"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or BASH is None,
    reason="The Ubuntu scheduler's shell tests require Unix Bash.",
)

COMMAND_STUBS = r"""
date() {
    case "$*" in
        "-u +%s") printf '%s\n' "$TEST_EPOCH" ;;
        "-u +%u") printf '%s\n' "$TEST_WEEKDAY" ;;
        "-u +%j") printf '%s\n' "$TEST_YEAR_DAY" ;;
        "-u +%F") printf '%s\n' "$TEST_DATE" ;;
        *) return 99 ;;
    esac
}
gh() {
    printf 'gh %s\n' "$*" >&2
    if [ "$1" = "api" ]; then
        if [ "$TEST_GH_QUERY_EXIT" != "0" ]; then return "$TEST_GH_QUERY_EXIT"; fi
        if [[ "$*" == *"status=$TEST_GH_BUSY_STATUS&"* ]]; then
            printf '1\n'
        else
            printf '0\n'
        fi
    elif [ "$1 $2" = "workflow run" ]; then
        printf 'DISPATCH %s\n' "$*"
        return "$TEST_DISPATCH_EXIT"
    else
        return 99
    fi
}
az() {
    printf 'az %s\n' "$*" >&2
    if [ "$TEST_ADO_QUERY_EXIT" != "0" ]; then return "$TEST_ADO_QUERY_EXIT"; fi
    if [[ "$*" == *"--pipeline-ids 109 147"* ]]; then
        if [[ "$*" == *"--status $TEST_ADO_BUSY_STATUS "* ]]; then
            printf '1\n'
        else
            printf '0\n'
        fi
    elif [[ "$*" == *"--pipeline-ids 109 --top 1"* ]]; then
        printf '%s\n' "$TEST_CLEANUP_READY"
    else
        return 99
    fi
}
"""


@pytest.fixture
def schedule_workflow():
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _run_schedule(workflow, date="2026-09-24", trigger=RELEASE_SCHEDULE, **overrides):
    instant = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    environment = {
        **os.environ,
        "GH_REPO": REPOSITORY,
        "TRIGGER_SCHEDULE": trigger,
        "AZURE_DEVOPS_EXT_PAT": "unused-test-pat",
        "TEST_EPOCH": str(int(instant.timestamp())),
        "TEST_WEEKDAY": str(instant.isoweekday()),
        "TEST_YEAR_DAY": instant.strftime("%j"),
        "TEST_DATE": date,
        "TEST_GH_QUERY_EXIT": "0",
        "TEST_GH_BUSY_STATUS": "none",
        "TEST_ADO_QUERY_EXIT": "0",
        "TEST_ADO_BUSY_STATUS": "none",
        "TEST_CLEANUP_READY": "1",
        "TEST_DISPATCH_EXIT": "0",
        **overrides,
    }
    environment.pop("BASH_ENV", None)
    script = workflow["jobs"]["dispatch"]["steps"][0]["run"]
    script = script.replace("${{ github.repository }}", REPOSITORY)
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", COMMAND_STUBS + script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _dispatches(result):
    return [
        shlex.split(line[len("DISPATCH "):])
        for line in result.stdout.splitlines()
        if line.startswith("DISPATCH ")
    ]


def test_integration_schedule_configuration(schedule_workflow):
    assert [item["cron"] for item in schedule_workflow["on"]["schedule"]] == [
        "17 8 * * 1-5", "17 8 * * 6", RELEASE_SCHEDULE,
    ]
    job = schedule_workflow["jobs"]["dispatch"]
    assert job["if"] == f"github.repository == '{REPOSITORY}'"
    assert job["steps"][0]["env"]["TRIGGER_SCHEDULE"] == "${{ github.event.schedule }}"
    assert job["steps"][0]["env"]["AZURE_DEVOPS_EXT_PAT"] == "${{ secrets.ADO_PAT }}"
    assert schedule_workflow["permissions"]["actions"] == "write"


def test_release_integration_dispatch(schedule_workflow):
    result = _run_schedule(schedule_workflow)
    assert result.returncode == 0, result.stderr
    assert _dispatches(result) == [[
        "workflow", "run", "int_test.yml",
        "--repo", REPOSITORY,
        "--ref", "release/1.0.0-preview",
        "-f", "python-versions=3.13",
        "-f", "regions=australiaeast,centralus",
        "-f", "arm-endpoint=public",
        "-f", "resource-group=cli-int-test-rg",
        "-f", "subscription-id=a386d5ea-ea90-441a-8263-d816368c84a1",
    ]]
    assert "--pipeline-ids 109 147" in result.stderr
    assert "starts_with(finishTime || '', '2026-09-24')" in result.stderr


@pytest.mark.parametrize("date", [
    "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-09-30", "2026-10-01", "2026-10-02",
    "2026-12-31", "2027-01-01", "2027-01-02",
    "2028-02-28", "2028-02-29", "2028-03-01",
])
def test_release_schedule_preserves_alternate_days(schedule_workflow, date):
    result = _run_schedule(schedule_workflow, date=date)
    epoch_day = (datetime.fromisoformat(date) - datetime(1970, 1, 1)).days
    assert result.returncode == 0, result.stderr
    assert len(_dispatches(result)) == (1 if epoch_day % 2 == 0 else 0)
    if epoch_day % 2:
        assert result.stderr == ""


@pytest.mark.parametrize("status", ["requested", "queued", "pending", "in_progress", "waiting"])
def test_release_skips_active_github_integrations(schedule_workflow, status):
    result = _run_schedule(schedule_workflow, TEST_GH_BUSY_STATUS=status)
    assert result.returncode == 0, result.stderr
    assert not _dispatches(result)
    assert "GitHub integration runs are" in result.stdout
    assert "az " not in result.stderr


@pytest.mark.parametrize("status", ["inProgress", "notStarted", "cancelling", "postponed"])
def test_release_skips_active_ado_runs(schedule_workflow, status):
    result = _run_schedule(schedule_workflow, TEST_ADO_BUSY_STATUS=status)
    assert result.returncode == 0, result.stderr
    assert not _dispatches(result)
    assert "ADO cleanup or integration runs are" in result.stdout


def test_release_requires_completed_cleanup_today(schedule_workflow):
    result = _run_schedule(schedule_workflow, TEST_CLEANUP_READY="0")
    assert result.returncode == 0, result.stderr
    assert not _dispatches(result)
    assert "today's cleanup has not completed" in result.stdout


@pytest.mark.parametrize("builds,expected", [
    ([], 0),
    ([{"status": "completed", "finishTime": "2026-09-24T13:04:21Z"}], 1),
    ([{"status": "completed", "finishTime": "2026-09-24T13:04:21+00:00"}], 1),
    ([{"status": "completed", "finishTime": "2026-09-23T13:04:21Z"}], 0),
    ([{"status": "completed", "finishTime": None}], 0),
    ([{"status": "inProgress", "finishTime": None}], 0),
    ([{"status": "notStarted"}], 0),
])
def test_cleanup_query_requires_a_completed_run_today(schedule_workflow, builds, expected):
    script = schedule_workflow["jobs"]["dispatch"]["steps"][0]["run"]
    query = re.search(r'--query "(\[\?status==.*)"', script).group(1)
    assert jmespath.search(query.replace("$today", "2026-09-24"), builds) == expected


@pytest.mark.parametrize("environment,exit_code", [
    ({"AZURE_DEVOPS_EXT_PAT": ""}, 1),
    ({"TEST_GH_QUERY_EXIT": "17"}, 17),
    ({"TEST_ADO_QUERY_EXIT": "18"}, 18),
    ({"TEST_DISPATCH_EXIT": "19"}, 19),
])
def test_release_surfaces_dispatch_and_preflight_failures(schedule_workflow, environment, exit_code):
    result = _run_schedule(schedule_workflow, **environment)
    assert result.returncode == exit_code, result.stderr
    assert len(_dispatches(result)) == (1 if exit_code == 19 else 0)


@pytest.mark.parametrize("date,trigger,branch,python,region", [
    ("2026-09-24", "17 8 * * 1-5", "preview", "3.13", "northeurope"),
    ("2026-09-26", "17 8 * * 6", "dev", "3.11", "westeurope"),
    ("2026-09-27", "", "preview", "3.12", "westeurope"),
])
def test_existing_schedule_and_manual_dispatch_are_unchanged(
    schedule_workflow, date, trigger, branch, python, region
):
    result = _run_schedule(schedule_workflow, date=date, trigger=trigger, AZURE_DEVOPS_EXT_PAT="")
    assert result.returncode == 0, result.stderr
    assert _dispatches(result) == [[
        "workflow", "run", "int_test.yml", "--repo", REPOSITORY, "--ref", branch,
        "-f", f"python-versions={python}", "-f", f"regions={region}",
    ]]
    assert "gh api " not in result.stderr
    assert "az " not in result.stderr
