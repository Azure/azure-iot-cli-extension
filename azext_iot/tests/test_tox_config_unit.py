# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from configparser import ConfigParser
from pathlib import Path
import os
import subprocess
import sys

import pytest


INTEGRATION_ENVIRONMENT = "testenv:{Central,ADT,DPS,HubControl,HubData,ADU,ADR}-int"


@pytest.mark.parametrize("override", [None, "https://management.azure.com"])
def test_real_adr_tox_binds_product_factory_endpoint_to_fixture_endpoint(tmp_path, override):
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    for key in ("AZURE_IOT_ADR_ARM_ENDPOINT", "azext_iot_adr_arm_endpoint"):
        environment.pop(key, None)
    if override:
        environment["azext_iot_adr_arm_endpoint"] = override
    result = subprocess.run(
        [sys.executable, "-m", "tox", "c", "-c", str(root / "tox.ini"),
         "--workdir", str(tmp_path / "tox"), "-e", "ADR-int", "-k", "set_env"],
        cwd=root, env=environment, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0
    expected = override or "https://centraluseuap.management.azure.com"
    assert f"AZURE_IOT_ADR_ARM_ENDPOINT={expected}" in result.stdout
    assert f"azext_iot_adr_arm_endpoint={expected}" in result.stdout


def test_integration_environments_discover_the_candidate_extension():
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    section = config[INTEGRATION_ENVIRONMENT]
    settings = [line.strip() for line in section["setenv"].splitlines() if line.strip()]

    # This must be unconditional: PYTHONPATH alone does not make Azure CLI
    # discover the extension installed by the common integration commands.
    assert "AZURE_EXTENSION_DIR={envsitepackagesdir}/azure-cli-extensions" in settings
    assert "pip install -U --target {envsitepackagesdir}/azure-cli-extensions/azure-iot ." in section["commands"]
    adr_settings = [line for line in settings if "azext_iot_adr_" in line]
    assert adr_settings
    assert all(line.startswith("ADR: ") for line in adr_settings)


def test_dps_phase_junit_is_isolated_and_coverage_remains_cumulative():
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    section = config[INTEGRATION_ENVIRONMENT]
    dps = " ".join(line.strip() for line in section["commands"].splitlines() if line.strip().startswith("DPS:"))
    assert "--junitxml={env:azext_iot_dps_junit:junit/test-iotext-dps-int.xml}" in dps
    assert "--cov-append" in dps and "-n {env:azext_iot_dps_workers:7}" in dps
    # Grace is provided by worker cancellation, not tox's SIGINT/execnet teardown path.
    assert "interrupt_timeout" not in section
    assert "azext_*" in section["passenv"]


def test_dps_controller_dependencies_are_isolated_from_the_managed_environment():
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    section = config["testenv:DPS-phases"]
    dependencies = [line.strip() for line in section["deps"].splitlines() if line.strip()]
    assert "." in dependencies
    assert "azure-cli" in dependencies
    assert "{[base]deps}" in dependencies
    assert section.getboolean("skip_install")
    assert not section["commands"].strip()
    managed = config[INTEGRATION_ENVIRONMENT]
    assert "DPS: ." not in managed["deps"]


@pytest.mark.parametrize("service", ["ADR", "DPS"])
def test_preview_integration_environments_bound_each_test_and_select_only_integration_files(service):
    config = ConfigParser(interpolation=None)
    root = Path(__file__).resolve().parents[2]
    config.read(root / "tox.ini")
    section = config[INTEGRATION_ENVIRONMENT]
    startup = "python -m pytest" if service == "DPS" else "pytest"
    command = next(
        line.strip() for line in section["commands"].splitlines()
        if line.strip().startswith(f"{service}: {startup} ")
    )
    assert "--timeout=900" in command
    assert "--integration-progress-interval=60" in command
    assert "-o faulthandler_timeout=300" in command
    assert "-k _int.py " in command
    assert "PYTHONUNBUFFERED=1" in {line.strip() for line in section["setenv"].splitlines()}
    service_lines = [
        line.strip() for line in section["commands"].splitlines()
        if line.strip().startswith(f"{service}:")
    ]
    # Even --reruns 0 buffers phase reports until teardown finishes.
    assert "-p no:rerunfailures" in " ".join(service_lines)
    assert "--reruns" not in " ".join(service_lines)
    assert "pytest-timeout" in (root / "dev_requirements").read_text(encoding="utf-8")


@pytest.mark.parametrize("suite", ["HubControl", "HubData"])
def test_public_hub_tox_uses_managed_controller_with_explicit_scope_and_no_filters(suite):
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    section = config[INTEGRATION_ENVIRONMENT]
    commands = section["commands"]
    assert f"{suite}: python {{toxinidir}}/azext_iot/tests/_hub_phase_runner.py --suite {suite}" in commands
    assert "--subscription {env:azext_iot_hub_subscription}" in commands
    assert "--resource-group {env:azext_iot_testrg:cli-int-test-rg}" in commands
    assert "--region {env:azext_iot_testhub_location:centraluseuap}" in commands
    assert "--output test-result/hub-phases" in commands
    hub_lines = [
        line.strip() for line in commands.splitlines()
        if line.strip().startswith((f"{suite}: ", "HubControl,HubData: "))
    ]
    # Only controller-owned arguments may be forwarded, never a raw pytest command/filter.
    assert hub_lines == [
        f"{suite}: python {{toxinidir}}/azext_iot/tests/_hub_phase_runner.py --suite {suite} \\",
        "HubControl,HubData:    --subscription {env:azext_iot_hub_subscription} \\",
        "HubControl,HubData:    --resource-group {env:azext_iot_testrg:cli-int-test-rg} \\",
        "HubControl,HubData:    --region {env:azext_iot_testhub_location:centraluseuap} \\",
        "HubControl,HubData:    --arm-endpoint={env:azext_iot_test_arm_endpoint:} --output test-result/hub-phases {posargs}",
    ]
    assert "HubSAS" not in commands and "HubMgmt" not in commands
    assert "hubsas_subscription" not in section["setenv"]
    assert "azext_iot_testhub_location={env:azext_iot_testhub_location:centraluseuap}" in section["setenv"]


@pytest.mark.parametrize("suite", ["HubControl", "HubData"])
@pytest.mark.parametrize("arguments", [
    ["-k", "test_example"],
    ["-m", "integration"],
    ["--collect-only"],
    ["--", "-k", "test_example"],
    ["azext_iot/tests/iothub/core/test_example_int.py::test_example"],
])
def test_public_hub_controller_rejects_pytest_posargs_before_launch(mocker, monkeypatch, suite, arguments):
    from azext_iot.tests import _hub_phase_runner

    launch = mocker.patch.object(_hub_phase_runner, "run")
    monkeypatch.setattr(sys, "argv", [
        "_hub_phase_runner.py", "--suite", suite, "--subscription", "offline-subscription",
        "--resource-group", "offline-group", "--region", "centraluseuap", *arguments,
    ])
    with pytest.raises(SystemExit) as error:
        _hub_phase_runner.main()
    assert error.value.code == 2
    launch.assert_not_called()
