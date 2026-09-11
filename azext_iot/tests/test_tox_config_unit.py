# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from configparser import ConfigParser
from pathlib import Path

import pytest


def test_integration_environments_discover_the_candidate_extension():
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    section = config["testenv:{Central,ADT,DPS,HubMgmt,HubData,ADU,ADR}-int"]
    settings = [line.strip() for line in section["setenv"].splitlines() if line.strip()]

    # This must be unconditional: PYTHONPATH alone does not make Azure CLI
    # discover the extension installed by the common integration commands.
    assert "AZURE_EXTENSION_DIR={envsitepackagesdir}/azure-cli-extensions" in settings
    assert "pip install -U --target {envsitepackagesdir}/azure-cli-extensions/azure-iot ." in section["commands"]
    adr_settings = [line for line in settings if "azext_iot_adr_" in line]
    assert adr_settings
    assert all(line.startswith("ADR: ") for line in adr_settings)


@pytest.mark.parametrize("service", ["ADR", "DPS", "HubMgmt", "HubData"])
def test_preview_integration_environments_bound_each_test_and_select_only_integration_files(service):
    config = ConfigParser(interpolation=None)
    root = Path(__file__).resolve().parents[2]
    config.read(root / "tox.ini")
    section = config["testenv:{Central,ADT,DPS,HubMgmt,HubData,ADU,ADR}-int"]
    command = next(
        line.strip() for line in section["commands"].splitlines()
        if line.strip().startswith(f"{service}: pytest ")
    )
    assert "--timeout=900" in command
    assert "-o faulthandler_timeout=300" in command
    assert "-k _int.py " in command
    assert "pytest-timeout" in (root / "dev_requirements").read_text(encoding="utf-8")
