# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import subprocess
from unittest.mock import Mock, patch

import pytest

from azext_iot.tests.adr import conftest as subject


def _config():
    reporter = Mock()
    config = Mock()
    config.pluginmanager.get_plugin.return_value = reporter
    return config, reporter


def test_preflight_requires_live_mode(monkeypatch):
    monkeypatch.delenv("AZURE_TEST_RUN_LIVE", raising=False)

    with pytest.raises(pytest.UsageError, match="AZURE_TEST_RUN_LIVE"):
        subject.run_adr_integration_preflight(Mock())


def test_preflight_validates_mandatory_resources_and_reports_optional_fixtures(
    monkeypatch,
):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    monkeypatch.setenv("azext_iot_adr_reports_enabled", "1")
    config, reporter = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=[
            "",
            "00000000-0000-0000-0000-000000000000",
            "",
            "",
            "Registered",
            "Registered",
            "",
        ],
    ) as run:
        with patch.object(
            subject,
            "TEST_SUBSCRIPTION",
            "00000000-0000-0000-0000-000000000000",
        ):
            subject.run_adr_integration_preflight(config)

    assert run.call_count == 7
    assert run.call_args_list[0].args[0] == [
        "az",
        "account",
        "set",
        "--subscription",
        "00000000-0000-0000-0000-000000000000",
    ]
    messages = [call.args[0] for call in reporter.write_line.call_args_list]
    assert any("subscription=00000000" in message for message in messages)
    assert any("endpoint=" in message and "api=" in message for message in messages)
    assert any("azext_iot_adr_reports_enabled" in message for message in messages)
    assert any("azext_iot_adr_update_instance_id" in message for message in messages)


def test_preflight_rejects_unregistered_provider(monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    config, _ = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=["", subject.TEST_SUBSCRIPTION, "", "", "NotRegistered"],
    ), pytest.raises(pytest.UsageError, match="must be registered"):
        subject.run_adr_integration_preflight(config)


def test_preflight_rejects_unexpected_subscription(monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    config, _ = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=["", "different-subscription"],
    ), pytest.raises(pytest.UsageError, match="expected"):
        subject.run_adr_integration_preflight(config)


@pytest.mark.parametrize(
    "side_effect",
    [
        OSError("az not found"),
        subprocess.TimeoutExpired(["az", "account", "show"], 60),
    ],
)
def test_run_preflight_command_translates_execution_failures(side_effect):
    with patch("subprocess.run", side_effect=side_effect), pytest.raises(
        pytest.UsageError, match="could not run"
    ):
        subject._run_preflight_command(["az", "account", "show"])


def test_run_preflight_command_surfaces_cli_error():
    result = Mock(returncode=1, stderr="not logged in", stdout="")
    with patch("subprocess.run", return_value=result), pytest.raises(
        pytest.UsageError, match="not logged in"
    ):
        subject._run_preflight_command(["az", "account", "show"])
