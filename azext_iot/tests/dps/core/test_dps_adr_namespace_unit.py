# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from azure.cli.core.azclierror import ArgumentUsageError

from azext_iot.core.custom import (
    _dps_description_for_write,
    _dps_identity_removals,
    _merge_dps_identity,
    _protect_dps_link_identity,
    iot_dps_linked_hub_get,
    iot_dps_linked_hub_create,
    iot_dps_linked_hub_list,
    iot_dps_create,
    iot_dps_update,
    iot_hub_create,
)

UAMI_1 = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/one"
)
UAMI_2 = UAMI_1.replace("/one", "/two")
DPS_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/provisioningServices/dps"
)
NS_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.DeviceRegistry/namespaces/ns"
)


def _dps():
    return {
        "id": DPS_ID,
        "name": "dps",
        "location": "centraluseuap",
        "sku": {"name": "S1", "capacity": 1},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "dps-principal",
            "userAssignedIdentities": {
                UAMI_1: {"principalId": "uami-principal"}
            },
        },
        "properties": {
            "provisioningState": "Succeeded",
            "state": "Active",
            "idScope": "scope",
            "serviceOperationsHostName": "dps.azure-devices-provisioning.net",
            "deviceProvisioningHostName": "global.azure-devices-provisioning.net",
            "iotHubs": [],
            "deviceRegistryNamespaces": [{"resourceId": NS_ID}],
        },
    }


def test_resource_side_namespace_parameters_are_removed():
    for operation in (iot_hub_create, iot_dps_create, iot_dps_update):
        parameters = inspect.signature(operation).parameters
        assert "adr_ns_id" not in parameters
        assert "adr_ns_identity_id" not in parameters


def test_dps_create_does_not_emit_namespace_relationship(mocker):
    mocker.patch("azext_iot.core.custom._check_dps_name_availability")
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )
    client = MagicMock()

    iot_dps_create(
        cmd=MagicMock(),
        client=client,
        dps_name="dps",
        resource_group_name="rg",
        mi_system_assigned=True,
    )

    body = client.iot_dps_resource.begin_create_or_update.call_args.kwargs[
        "iot_dps_description"
    ]
    assert "deviceRegistryNamespace" not in body["properties"]
    assert body["identity"]["type"] == "SystemAssigned"


def test_dps_partial_identity_update_preserves_existing_identities():
    merged = _merge_dps_identity(
        _dps()["identity"], system_assigned=None, user_identities=[UAMI_2]
    )

    assert merged["type"] == "SystemAssigned,UserAssigned"
    assert set(merged["userAssignedIdentities"]) == {UAMI_1, UAMI_2}


def test_dps_update_requires_explicit_false_to_remove_system_identity():
    client = MagicMock()
    parameters = _dps()
    parameters["properties"]["deviceRegistryNamespaces"] = []
    client.iot_dps_resource.get.return_value = deepcopy(parameters)

    iot_dps_update(
        client,
        "dps",
        parameters,
        resource_group_name="rg",
        mi_user_assigned=[UAMI_2],
    )
    body = client.iot_dps_resource.begin_create_or_update.call_args.kwargs[
        "iot_dps_description"
    ]
    assert body["identity"]["type"] == "SystemAssigned,UserAssigned"

    iot_dps_update(
        client,
        "dps",
        parameters,
        resource_group_name="rg",
        mi_system_assigned=False,
    )
    body = client.iot_dps_resource.begin_create_or_update.call_args.kwargs[
        "iot_dps_description"
    ]
    assert body["identity"]["type"] == "UserAssigned"


def test_dps_generic_update_applies_tags_without_identity_removal():
    client = MagicMock()
    parameters = _dps()
    parameters["properties"]["deviceRegistryNamespaces"] = []
    client.iot_dps_resource.get.return_value = deepcopy(parameters)

    iot_dps_update(
        client,
        "dps",
        parameters,
        resource_group_name="rg",
        tags={"environment": "test"},
    )

    body = client.iot_dps_resource.begin_create_or_update.call_args.kwargs[
        "iot_dps_description"
    ]
    assert body["tags"] == {"environment": "test"}


def test_dps_identity_removal_diff_is_case_insensitive():
    remove_system, removed_uamis = _dps_identity_removals(
        _dps()["identity"],
        {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_2: {}},
        },
    )

    assert remove_system is True
    assert removed_uamis == [UAMI_1]
    assert _dps_identity_removals(
        {"type": "UserAssigned", "userAssignedIdentities": {UAMI_1: {}}},
        {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_1.upper(): {}},
        },
    ) == (False, None)


def test_dps_generic_update_blocks_explicit_system_identity_removal():
    client = MagicMock()
    current = _dps()
    client.iot_dps_resource.get.return_value = deepcopy(current)
    registry = MagicMock()
    registry.namespaces.get.return_value = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": DPS_ID,
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                    }
                }
            }
        }
    }

    with patch(
        "azext_iot._factory.adr_service_factory", return_value=registry
    ), pytest.raises(ArgumentUsageError, match="link dps update"):
        iot_dps_update(
            client,
            "dps",
            deepcopy(current),
            resource_group_name="rg",
            mi_system_assigned=False,
            cmd=MagicMock(),
        )

    client.iot_dps_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("remove_whole_identity", [True, False])
def test_dps_generic_remove_path_blocks_selected_uami(
    remove_whole_identity,
):
    client = MagicMock()
    current = _dps()
    client.iot_dps_resource.get.return_value = deepcopy(current)
    desired = deepcopy(current)
    if remove_whole_identity:
        desired.pop("identity")
    else:
        desired["identity"]["type"] = "SystemAssigned"
        desired["identity"]["userAssignedIdentities"].pop(UAMI_1)
    registry = MagicMock()
    registry.namespaces.get.return_value = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": DPS_ID,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned",
                            "userAssignedIdentity": UAMI_1.upper(),
                        },
                    }
                }
            }
        }
    }

    with patch(
        "azext_iot._factory.adr_service_factory", return_value=registry
    ), pytest.raises(ArgumentUsageError, match="selected DPS"):
        iot_dps_update(
            client,
            "dps",
            desired,
            resource_group_name="rg",
            cmd=MagicMock(),
        )

    client.iot_dps_resource.begin_create_or_update.assert_not_called()


def test_dps_generic_update_allows_removing_unselected_uami():
    current = _dps()
    current["identity"]["userAssignedIdentities"][UAMI_2] = {}
    desired = deepcopy(current)
    desired["identity"]["userAssignedIdentities"].pop(UAMI_2)
    client = MagicMock()
    client.iot_dps_resource.get.return_value = deepcopy(current)
    registry = MagicMock()
    registry.namespaces.get.return_value = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": DPS_ID,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned",
                            "userAssignedIdentity": UAMI_1,
                        },
                    }
                }
            }
        }
    }

    with patch(
        "azext_iot._factory.adr_service_factory", return_value=registry
    ):
        iot_dps_update(
            client,
            "dps",
            desired,
            resource_group_name="rg",
            cmd=MagicMock(),
        )

    client.iot_dps_resource.begin_create_or_update.assert_called_once()


def test_dps_write_body_omits_read_only_namespace_projection():
    body = _dps_description_for_write(_dps())

    assert "id" not in body
    assert "deviceRegistryNamespaces" not in body["properties"]
    assert "provisioningState" not in body["properties"]
    assert body["properties"]["iotHubs"] == []
    assert body["identity"]["userAssignedIdentities"] == {UAMI_1: {}}


def test_active_dps_link_blocks_selected_identity_removal():
    namespace = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": DPS_ID,
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                    }
                }
            }
        }
    }
    cmd = MagicMock()
    registry = MagicMock()
    registry.namespaces.get.return_value = namespace

    with patch(
        "azext_iot._factory.adr_service_factory", return_value=registry
    ), pytest.raises(ArgumentUsageError, match="link dps update"):
        _protect_dps_link_identity(
            cmd,
            _dps(),
            remove_system=True,
            remove_user_identities=None,
        )


def test_active_dps_link_blocks_uami_and_unreadable_projection():
    dps = _dps()
    namespace = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": DPS_ID,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned",
                            "userAssignedIdentity": UAMI_1,
                        },
                    }
                }
            }
        }
    }
    cmd = MagicMock()
    registry = MagicMock()
    registry.namespaces.get.return_value = namespace
    with patch("azext_iot._factory.adr_service_factory", return_value=registry):
        with pytest.raises(ArgumentUsageError, match="selected DPS"):
            _protect_dps_link_identity(
                cmd,
                dps,
                remove_system=False,
                remove_user_identities=[UAMI_1.upper()],
            )

    with patch(
        "azext_iot._factory.adr_service_factory",
        side_effect=RuntimeError("forbidden"),
    ), pytest.raises(ArgumentUsageError, match="could not be read"):
        _protect_dps_link_identity(
            cmd,
            dps,
            remove_system=False,
            remove_user_identities=[UAMI_2],
        )


def test_dps_identity_guard_blocks_unverifiable_link_shapes():
    dps = _dps()
    dps.pop("id")
    with pytest.raises(ArgumentUsageError, match="resource ID is missing"):
        _protect_dps_link_identity(
            MagicMock(), dps, remove_system=True, remove_user_identities=None
        )

    dps = _dps()
    with pytest.raises(ArgumentUsageError, match="through Azure CLI"):
        _protect_dps_link_identity(
            None, dps, remove_system=True, remove_user_identities=None
        )

    dps["properties"]["deviceRegistryNamespaces"] = [
        {"resourceId": "not-an-arm-id"}
    ]
    with pytest.raises(ArgumentUsageError, match="could not be validated"):
        _protect_dps_link_identity(
            MagicMock(), dps, remove_system=True, remove_user_identities=None
        )


def test_dps_identity_guard_ignores_unrelated_namespace_endpoint():
    registry = MagicMock()
    registry.namespaces.get.return_value = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "other": {
                        "resourceId": DPS_ID.replace("/dps", "/other"),
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                    }
                }
            }
        }
    }
    with patch("azext_iot._factory.adr_service_factory", return_value=registry):
        _protect_dps_link_identity(
            MagicMock(),
            _dps(),
            remove_system=True,
            remove_user_identities=None,
        )


def test_classic_linked_hub_list_and_show_run_namespace_warning(mocker):
    dps = {
        "properties": {
            "deviceRegistryNamespaces": [{"resourceId": NS_ID}],
            "iotHubs": [{"name": "hub.azure-devices.net"}],
        }
    }
    mocker.patch("azext_iot.core.custom.iot_dps_get", return_value=dps)
    warning = mocker.patch("azext_iot.core.custom._warn_namespace_linked_dps")
    client = MagicMock()

    assert iot_dps_linked_hub_list(client, "dps") == dps["properties"]["iotHubs"]
    assert iot_dps_linked_hub_get(
        MagicMock(), client, "dps", "hub.azure-devices.net"
    )["name"] == "hub.azure-devices.net"
    assert warning.call_count == 2


def test_classic_linked_hub_create_runs_namespace_warning(mocker):
    dps = {
        "properties": {
            "deviceRegistryNamespaces": [{"resourceId": NS_ID}],
            "iotHubs": [],
        }
    }
    mocker.patch(
        "azext_iot.core.custom._ensure_dps_resource_group_name",
        return_value="rg",
    )
    mocker.patch("azext_iot.core.custom.iot_dps_get", return_value=dps)
    warning = mocker.patch("azext_iot.core.custom._warn_namespace_linked_dps")
    client = MagicMock()

    iot_dps_linked_hub_create(
        MagicMock(),
        client,
        "dps",
        connection_string=(
            "HostName=hub.azure-devices.net;"
            "SharedAccessKeyName=owner;SharedAccessKey=key"
        ),
        location="centraluseuap",
        resource_group_name="rg",
        no_wait=True,
    )

    warning.assert_called_once_with(dps)
