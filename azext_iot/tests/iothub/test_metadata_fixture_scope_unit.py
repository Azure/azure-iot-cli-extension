# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path

from azext_iot.tests.iothub import conftest as infrastructure
from azext_iot.tests.iothub.metadata import conftest as leased


pytest_plugins = ["pytester"]


def test_leased_metadata_does_not_inherit_dynamic_parent_cleanup(pytester, mocker, monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "False")
    mocker.patch("requests.sessions.Session.send", side_effect=AssertionError("Collection must remain offline."))
    mocker.patch("azure.cli.core._profile.Profile.get_raw_token", side_effect=AssertionError("No credentials."))
    root = Path(__file__).resolve().parents[3]
    _, recorder = pytester.inline_genitems(
        "-c", str(root / "setup.cfg"), "-o", "addopts=",
        str(Path(__file__).parent / "metadata" / "test_hub_metadata_int.py"),
        str(Path(__file__).parent / "devices" / "test_iothub_device_twin_int.py"),
    )
    assert recorder.getcalls("pytest_sessionfinish")[0].exitstatus == 0
    items = recorder.getcalls("pytest_collection_finish")[0].session.items
    metadata, regular = [], []
    for item in items:
        definitions = item._fixtureinfo.name2fixturedefs["_cleanup_dynamic_hub"]
        if Path(str(item.fspath)).parent.name == "metadata":
            metadata.append(item)
            assert definitions[-1].func is leased._cleanup_dynamic_hub.__wrapped__
        else:
            regular.append(item)
            assert definitions[-1].func is infrastructure._cleanup_dynamic_hub.__wrapped__
    assert len(metadata) == 1
    assert regular


def test_leased_cleanup_never_deletes_a_parent_even_in_live_mode(mocker, monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "True")
    delete = mocker.patch.object(
        infrastructure, "_delete_fixture_resource", side_effect=AssertionError("Lease parent deletion is forbidden."),
    )
    assert leased._cleanup_dynamic_hub.__wrapped__() is None
    delete.assert_not_called()
