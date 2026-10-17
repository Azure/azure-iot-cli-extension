# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry-device metadata and basic CRUD; authentication secrets are never requested."""

from azext_iot.adr.ui.core.actions import Field, crud
from azext_iot.adr.ui.core.spec import Column, Guide, ResourceSpec
from azext_iot.adr.ui.kinds._common import name_column, name_of, prop, state_column


def build(session):
    def list_devices(scope):
        return session.list_from("device", "list", namespace_name=scope["namespace_name"],
                                 resource_group_name=scope["resource_group_name"])

    return ResourceSpec(
        kind="device", title="Device", title_plural="Devices", parent="namespace",
        aliases=("dev", "registry-device"), row_id=name_of, list=list_devices,
        requires=("namespace_name", "resource_group_name"),
        columns=(name_column(), Column("enabled", "ENABLEMENT", prop("enablementState"), width=14),
                 state_column(), Column("model", "MODEL", prop("model"), width=20, wide=True)),
        guide=Guide("Registry device metadata.",
                    runs="az iot adr ns device list --ns <namespace> -g <resource-group>  ·  read-only",
                    note="Credentials, certificates and authentication keys are not retrieved."),
        actions=crud(
            "device", "iot adr ns device", "registry_device_name", create_fields=(),
            update_fields=(Field("enablement_state", "--enablement-state", "Enablement: Enabled or Disabled",
                                 "Enabled", ("Enabled", "Disabled")),),
        ),
    )
