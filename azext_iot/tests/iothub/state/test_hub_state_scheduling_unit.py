# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
from shlex import split
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import CLIInternalError

from azext_iot.tests.iothub import conftest as infrastructure
from azext_iot.tests.iothub.state import _state_helpers
from azext_iot.tests.iothub.state import test_hub_state_dataplane_int as dataplane
from azext_iot.tests.iothub.state import test_hub_state_int as controlplane


pytest_plugins = ["pytester"]

STATE_NODES = {
    "test_hub_state_int.py": {
        "test_migrate_controlplane", "test_migrate_controlplane_with_create",
        "test_mirgate_hub_dataplane_error", "test_export_import_controlplane",
        "test_export_import_controlplane_with_create", "test_custom_scenarios_controlplane",
        "test_export_import_migrate_missing_hubs_error",
        "test_export_endpoint_resource_name_starting_with_scheme_char",
        "test_export_cosmosdb_endpoint_resource_name_starting_with_scheme_char",
    },
    "test_hub_state_dataplane_int.py": {"test_migrate_dataplane", "test_export_import_dataplane"},
}


@pytest.mark.parametrize("failed_group", [None, "controlplane", "dataplane"])
@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero"])
@pytest.mark.parametrize("controlplane_pool", ["routing", "plain"])
def test_state_module_pools_own_distinct_resources_and_propagate_cleanup_failures(
    mocker, failed_group, failure_kind, controlplane_pool
):
    active = {}
    created = []
    deleted = []
    failed_name = None

    def invoke(command, **_kwargs):
        args = split(command)
        name = args[args.index("-n") + 1]
        assert args[args.index("-g") + 1] == infrastructure.RG
        resource = None
        failed = False
        if args[:3] == ["iot", "hub", "create"]:
            assert name not in active
            assert args[args.index("--location") + 1] == infrastructure.HUB_TEST_LOCATION
            assert args[args.index("--disable-local-auth") + 1] == "true"
            resource = {
                "id": f"/subscriptions/unit/resourceGroups/{infrastructure.RG}/providers/Microsoft.Devices/IotHubs/{name}",
                "location": infrastructure.HUB_TEST_LOCATION, "properties": {"disableLocalAuth": True},
            }
            active[name] = resource["id"]
            created.append(args)
        else:
            assert args[:3] == ["iot", "hub", "delete"]
            assert name in active, "Cleanup must address an owned resource exactly once."
            deleted.append(name)
            failed = name == failed_name
            if not failed:
                del active[name]
        return SimpleNamespace(
            success=lambda: not failed, as_json=lambda: resource, error_code=7 if failed else 0,
            get_error=lambda: CLIInternalError("Dependency cleanup failed") if failed and failure_kind == "cli_error" else None,
        )

    mocker.patch.object(infrastructure.cli, "invoke", side_effect=invoke)
    mocker.patch.object(infrastructure, "get_closest_marker", side_effect=lambda request: request.marker)
    cp_count = 2 if controlplane_pool == "routing" else 1
    cp_request = SimpleNamespace(marker=SimpleNamespace(kwargs=(
        {"count": 2, "sys_identity": True, "user_identity": True, "storage": True}
        if controlplane_pool == "routing" else {"count": 1}
    )))
    dp_request = SimpleNamespace(marker=SimpleNamespace(kwargs={"count": 2}))
    if controlplane_pool == "routing":
        cp_fixture = infrastructure.provisioned_iot_hubs_with_storage_user_module.__wrapped__(
            cp_request, {"id": "/unit/identity"}, {"connectionString": "unit-storage"},
        )
    else:
        cp_fixture = infrastructure.provisioned_only_iot_hubs_module.__wrapped__(cp_request)
    dp_fixture = infrastructure.provisioned_only_iot_hubs_module.__wrapped__(dp_request)
    cp_hubs, dp_hubs = next(cp_fixture), next(dp_fixture)
    cp_ids = {hub["hub"]["id"] for hub in cp_hubs}
    dp_ids = {hub["hub"]["id"] for hub in dp_hubs}
    assert len(cp_ids) == cp_count and len(dp_ids) == 2
    assert cp_ids.isdisjoint(dp_ids)
    assert cp_hubs is not dp_hubs
    for args in created[:cp_count]:
        if controlplane_pool == "routing":
            assert "--system-assigned-mi" in args and "--user-assigned-mi" in args and "--fcs" in args
        else:
            assert not {"--system-assigned-mi", "--user-assigned-mi", "--fcs"}.intersection(args)
    for args in created[cp_count:]:
        assert not {"--system-assigned-mi", "--user-assigned-mi", "--fcs"}.intersection(args)

    for group, fixture, hubs in (("controlplane", cp_fixture, cp_hubs), ("dataplane", dp_fixture, dp_hubs)):
        failed_name = hubs[0]["name"] if group == failed_group else None
        if failed_name:
            with pytest.raises(CLIInternalError, match="Failed to delete test IoT Hub resources"):
                next(fixture)
        else:
            with pytest.raises(StopIteration):
                next(fixture)
        assert all(hub["name"] in deleted for hub in hubs)
        if group == "controlplane":
            assert dp_ids.issubset(active.values())
    assert len(created) == len(deleted) == cp_count + 2
    assert len(active) == (1 if failed_group else 0)


@pytest.mark.parametrize("suite,phase,count", [
    ("HubControl", "regular", 28),
    ("HubData", "entra", 44),
])
def test_hub_manifest_collection_preserves_isolated_state_groups(
    pytester, mocker, monkeypatch, suite, phase, count
):
    from azext_iot.tests._hub_suite_manifest import nodes
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "False")
    mocker.patch("requests.sessions.Session.send", side_effect=AssertionError("Collection must not make network calls."))
    root = Path(__file__).resolve().parents[4]
    paths = [str(root / node) for node in nodes(suite, phase)]
    _, recorder = pytester.inline_genitems(
        "-c", str(root / "setup.cfg"), "--rootdir", str(root), "--confcutdir", str(root), *paths,
    )
    assert recorder.getcalls("pytest_sessionfinish")[0].exitstatus == 0
    items = recorder.getcalls("pytest_collection_finish")[0].session.items
    assert len(items) == len({item.nodeid for item in items}) == count
    state_items = [item for item in items if Path(str(item.fspath)).parent.name == "state"]
    # Classify asserted behavior, not the containing file: this negative is data-plane.
    data_negative = {"test_mirgate_hub_dataplane_error"}
    expected_files = (
        {"test_hub_state_int.py": STATE_NODES["test_hub_state_int.py"] - data_negative}
        if suite == "HubControl" else {
            "test_hub_state_int.py": data_negative,
            "test_hub_state_dataplane_int.py": STATE_NODES["test_hub_state_dataplane_int.py"],
        }
    )
    assert len(state_items) == sum(len(expected) for expected in expected_files.values())
    assert {Path(str(item.fspath)).name for item in state_items} == set(expected_files)
    heavy_dependencies = {
        "setup_hub_controlplane_states", "provisioned_iot_hubs_with_storage_user_module",
        "provisioned_storage_module", "provisioned_user_identity_module",
        "provisioned_event_hub_module", "provisioned_service_bus_module", "provisioned_cosmos_db_module",
    }
    for filename, expected in expected_files.items():
        selected = [item for item in state_items if Path(str(item.fspath)).name == filename]
        assert {item.name for item in selected} == expected
        for item in selected:
            assert item.obj.__module__ == item.module.__name__, "Do not collect imported test functions."
            fixtures = item._fixtureinfo.name2fixturedefs
            if filename == "test_hub_state_dataplane_int.py":
                assert item.module.__name__ == dataplane.__name__
                assert heavy_dependencies.isdisjoint(fixtures)
                assert fixtures["provisioned_only_iot_hubs_module"][-1].scope == "module"
                timeout = item.get_closest_marker("timeout")
                assert timeout.args == (_state_helpers.DATAPLANE_LIFECYCLE_TIMEOUT,)
                assert timeout.kwargs == {"func_only": False}
            elif "setup_hub_states_controlplane" in fixtures:
                assert item.module is controlplane
                assert fixtures["provisioned_iot_hubs_with_storage_user_module"][-1].scope == "module"
                assert fixtures["setup_hub_controlplane_states"][-1].scope == "module"
                timeout = item.get_closest_marker("timeout")
                assert timeout.args == (_state_helpers.CONTROLPLANE_LIFECYCLE_TIMEOUT,)
                assert timeout.kwargs == {"func_only": False}
    assert not any(name.startswith("test_") for name in vars(_state_helpers))
