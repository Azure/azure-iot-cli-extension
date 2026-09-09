# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib
import inspect
import shlex
from pathlib import Path

import pytest
from azure.cli.testsdk.base import ExecutionResult

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._log import _redact_command


@pytest.fixture
def scenario(monkeypatch):
    monkeypatch.delenv("PRETTY_LOG", raising=False)
    test = object.__new__(ADRLiveScenarioTest)
    test._testMethodName = "runTest"
    test.kwargs = {"namespace": "test-ns"}
    test.cli_ctx = object()
    return test


@pytest.mark.parametrize(
    "arguments",
    [
        "--password redactme",
        "--password=redactme",
        "--client-secret 'redactme with spaces'",
        "--primary-key=redactme --secondary-key redactme",
        "--key 'redactme' --pk redactme --sk=redactme",
        "-p redactme -k redactme",
        "--access-token redactme",
        "--login 'HostName=host;SharedAccessKey=redactme'",
        "--connection-string 'AccountName=account;AccountKey=redactme'",
        "--body '{\"nested\":{\"password\":\"redactme\"}}'",
        "--properties '{\"unknownField\":\"redactme\"}'",
        "--parameters 'arbitrary=redactme' 'second=redactme'",
        "--set properties.nested.field=redactme other=redactme",
        "--headers 'Authorization=Bearer redactme' 'Custom=redactme'",
        "--url 'https://storage.example/blob?sv=1&sig=redactme&sp=r'",
        "--url=https://storage.example/blob?sig=redactme",
        "--url 'https://storage.example/blob?%73ig=redactme'",
        "--url 'https://user:redactme@host/path'",
        "--tags clientSecret=redactme",
        "--value 'SharedAccessKey=redactme'",
        "--value '{\"nested\":{\"private_key\":\"redactme\"}}'",
        "--value 'Bearer redactme'",
        "--value '-----BEGIN PRIVATE KEY----- redactme -----END PRIVATE KEY-----'",
        "--password '--redactme'",
        "--password 'redactme",
    ],
)
def test_command_display_redacts_secrets(arguments):
    display = _redact_command(f"iot adr ns show --name example {arguments}")

    assert "redactme" not in display
    assert "***" in display or "command omitted" in display


@pytest.mark.parametrize(
    "command",
    [
        "iot adr ns create -n ns -g rg -l centraluseuap",
        "az iot adr ns update -n ns --tags ''",
        'iot adr ns list --query "[].name"',
        'iot adr ns show --query "{name:name,state:properties.provisioningState}"',
        'iot adr ns identity show --query "type"',
        "",
    ],
)
def test_safe_command_display_preserves_arguments(command):
    expected = shlex.split(command)
    if not expected or expected[0] != "az":
        expected.insert(0, "az")
    assert shlex.split(_redact_command(command)) == expected


def test_command_display_escapes_control_characters():
    display = _redact_command("iot adr ns create --description 'first\nsecond\r\033[31m'")
    assert "\n" not in display
    assert "\r" not in display
    assert "\033" not in display
    assert r"\n" in display
    assert r"\r" in display
    assert r"\x1b" in display


@pytest.mark.parametrize("pretty", [False, True])
@pytest.mark.parametrize("expect_failure", [False, True])
def test_commands_are_logged_once_before_execution(
    scenario, mocker, monkeypatch, capsys, caplog, pretty, expect_failure
):
    if pretty:
        monkeypatch.setenv("PRETTY_LOG", "1")
    command = "iot adr ns show -n {namespace}"
    checks = [mocker.sentinel.check]
    result = mocker.create_autospec(ExecutionResult, instance=True)
    result.assert_with_checks.return_value = mocker.sentinel.result

    def execute(cli_ctx, resolved, expect_failure=False):
        assert cli_ctx is scenario.cli_ctx
        assert resolved == "iot adr ns show -n test-ns"
        message = "  \u203a az iot adr ns show -n test-ns"
        if expect_failure:
            message += "  (expect failure)"
        if pretty:
            assert capsys.readouterr().out == f"\033[38;2;116;175;198m{message}\033[0m\n"
            assert not caplog.records
        else:
            assert caplog.messages == [message]
        return result

    execution = mocker.patch("azure.cli.testsdk.base.execute", side_effect=execute)

    assert scenario.cmd(command, checks, expect_failure) is mocker.sentinel.result

    execution.assert_called_once_with(
        scenario.cli_ctx, "iot adr ns show -n test-ns", expect_failure=expect_failure
    )
    result.assert_with_checks.assert_called_once_with(checks)


def test_original_template_and_secrets_are_delegated_unchanged(scenario, mocker, caplog):
    command = "iot adr ns show -n {namespace} --password redactme"
    parent = mocker.patch.object(CaptureOutputLiveScenarioTest, "cmd", return_value=mocker.sentinel.result)

    assert scenario.cmd(command, expect_failure=True) is mocker.sentinel.result

    parent.assert_called_once_with(command, checks=None, expect_failure=True)
    assert "test-ns" in caplog.text
    assert "redactme" not in caplog.text
    assert "expect failure" in caplog.text


def test_formatted_json_is_not_formatted_a_second_time(scenario, mocker, caplog):
    scenario.kwargs["value"] = '{"site": "plant"}'
    command = "iot adr ns create -n {namespace} --properties '{value}'"
    execution = mocker.patch("azure.cli.testsdk.base.execute", autospec=True)

    scenario.cmd(command)

    execution.assert_called_once_with(
        scenario.cli_ctx,
        'iot adr ns create -n test-ns --properties \'{"site": "plant"}\'',
        expect_failure=False,
    )
    assert "plant" not in caplog.text


def test_execution_error_is_logged_then_propagated(scenario, mocker, caplog):
    error = RuntimeError("command failed")
    mocker.patch("azure.cli.testsdk.base.execute", side_effect=error)

    with pytest.raises(RuntimeError) as raised:
        scenario.cmd("iot adr ns wait -n {namespace} --created")

    assert raised.value is error
    assert caplog.messages == ["  \u203a az iot adr ns wait -n test-ns --created"]


def test_other_services_keep_their_existing_command_behavior(scenario, mocker, caplog):
    mocker.patch("azure.cli.testsdk.base.execute", autospec=True)

    CaptureOutputLiveScenarioTest.cmd(scenario, "account show")

    assert not caplog.records


def test_all_adr_scenarios_use_the_command_wrapper():
    for path in Path(__file__).parent.glob("test_*_int.py"):
        module = importlib.import_module(f"azext_iot.tests.adr.{path.stem}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, CaptureOutputLiveScenarioTest):
                assert issubclass(cls, ADRLiveScenarioTest), cls.__name__
                assert cls.cmd is ADRLiveScenarioTest.cmd, cls.__name__
