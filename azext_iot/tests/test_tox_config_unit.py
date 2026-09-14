# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from configparser import ConfigParser
from pathlib import Path

import pytest


INTEGRATION_ENVIRONMENT = "testenv:{Central,ADT,DPS,HubMgmt,HubData,HubSAS,ADU,ADR}-int"


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


@pytest.mark.parametrize("service", ["ADR", "DPS", "HubMgmt", "HubData", "HubSAS"])
def test_preview_integration_environments_bound_each_test_and_select_only_integration_files(service):
    config = ConfigParser(interpolation=None)
    root = Path(__file__).resolve().parents[2]
    config.read(root / "tox.ini")
    section = config[INTEGRATION_ENVIRONMENT]
    command = next(
        line.strip() for line in section["commands"].splitlines()
        if line.strip().startswith(f"{service}: pytest ")
    )
    assert "--timeout=900" in command
    assert "--integration-progress-interval=60" in command
    assert "-o faulthandler_timeout=300" in command
    if service != "HubSAS":
        assert "-k _int.py " in command
    assert "PYTHONUNBUFFERED=1" in {line.strip() for line in section["setenv"].splitlines()}
    service_lines = [
        line.strip() for line in section["commands"].splitlines()
        if line.strip().startswith(f"{service}:")
    ]
    if service == "HubSAS":
        from azext_iot.tests.iothub._sas_phase import NODES

        arguments = [line.split(":", 1)[1].strip() for line in service_lines]
        nodes = [argument for argument in arguments if argument.startswith("azext_iot/")]
        assert tuple(node.rstrip(" \\") for node in nodes) == NODES
        assert all(node.partition("::")[0].endswith("_int.py") for node in nodes)
        assert "-n 0" in " ".join(service_lines)
    # Even --reruns 0 buffers phase reports until teardown finishes.
    assert "-p no:rerunfailures" in " ".join(service_lines)
    assert "--reruns" not in " ".join(service_lines)
    assert "pytest-timeout" in (root / "dev_requirements").read_text(encoding="utf-8")
