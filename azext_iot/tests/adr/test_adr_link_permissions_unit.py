# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot.adr.providers.link_preflight import TargetLookup, preflight_target


NS_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.DeviceRegistry/namespaces/ns"
)
TARGET_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/provisioningServices/dps"
)
UAMI = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/outbound"
)


def test_dps_preflight_explains_namespace_system_identity_requirement():
    namespace = {
        "id": NS_ID,
        "location": "centraluseuap",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI: {"principalId": "namespace-uami"}},
        },
        "properties": {
            "outboundIdentity": {
                "type": "UserAssigned",
                "userAssignedIdentity": UAMI,
            }
        },
    }
    target = {
        "location": "centraluseuap",
        "identity": {"type": "SystemAssigned", "principalId": "dps-sami"},
        "properties": {"provisioningState": "Succeeded"},
    }
    rbac = MagicMock()

    with pytest.raises(InvalidArgumentValueError) as error:
        preflight_target(
            link_type="dps",
            namespace=namespace,
            target_resource_id=TARGET_ID,
            inbound_identity={"type": "SystemAssigned"},
            parsed={"subscription_id": "sub", "resource_group_name": "rg", "name": "dps"},
            strategy=TargetLookup(
                factory=MagicMock(),
                operation_group_name="iot_dps_resource",
                name_parameter="resource_name",
                display_name="DPS",
            ),
            lookup=MagicMock(return_value=target),
            rbac_manager=rbac,
        )

    assert "DPS links additionally require the namespace system-assigned identity" in str(error.value)
    assert "az iot adr ns identity assign --system-assigned -n ns -g rg" in str(error.value)
    rbac.ensure.assert_not_called()
