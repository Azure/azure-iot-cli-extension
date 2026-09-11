# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import runpy

import pytest

from azext_iot.tests.dps import conftest as dps_fixtures


@pytest.mark.parametrize("location", [None, "", "sentinel", "centraluseuap"])
def test_dps_fixture_location_setting(monkeypatch, mocker, location):
    monkeypatch.setenv("azext_iot_testrg", "unit-test-rg")
    if location is None:
        monkeypatch.delenv("azext_iot_dps_test_location", raising=False)
    else:
        monkeypatch.setenv("azext_iot_dps_test_location", location)
    cli = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")

    fixture_globals = runpy.run_path(str(Path(dps_fixtures.__file__)))

    assert fixture_globals["ENTITY_LOCATION"] == ("centraluseuap" if location == "centraluseuap" else "westus")
    assert fixture_globals["ENTITY_RG"] == "unit-test-rg"
    cli.return_value.invoke.assert_not_called()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("iot_hub", [None, {"name": "existing-hub"}])
def test_dps_fixture_creates_in_configured_region(monkeypatch, mocker, managed, iot_hub):
    cli = mocker.patch.object(dps_fixtures, "cli")
    mocker.patch.object(dps_fixtures, "assign_iot_dps_dataplane_rbac_role")
    mocker.patch.object(dps_fixtures, "_link_hub")
    mocker.patch.object(dps_fixtures, "_unlink_all_hubs")
    mocker.patch.object(dps_fixtures, "sleep")
    monkeypatch.setattr(dps_fixtures, "ENTITY_LOCATION", "centraluseuap")
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")

    if managed:
        dps_fixtures._create_managed_dps("test-run", "h" if iot_hub else "nh", iot_hub)
    else:
        dps_fixtures._create_unmanaged_dps("test-dps", iot_hub)

    cli.invoke.assert_called_once()
    command = cli.invoke.call_args.args[0]
    assert command.startswith("iot dps create ")
    assert "--location centraluseuap" in command
    assert "--resource-group unit-test-rg" in command
    if iot_hub:
        assert "hubname=existing-hub" in command


def test_managed_dps_fixture_sets_disable_local_auth(monkeypatch, mocker):
    cli = mocker.patch.object(dps_fixtures, "cli")
    mocker.patch.object(dps_fixtures, "assign_iot_dps_dataplane_rbac_role")
    mocker.patch.object(dps_fixtures, "_unlink_all_hubs")
    mocker.patch.object(dps_fixtures, "sleep")
    monkeypatch.setattr(dps_fixtures, "ENTITY_LOCATION", "westus")
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")

    dps_fixtures._create_managed_dps("test-run", "dla", None, disable_local_auth=True)

    assert "--disable-local-auth true" in cli.invoke.call_args.args[0]
