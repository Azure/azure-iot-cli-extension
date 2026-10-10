# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Secondary release inventories are deliberately read-only."""

from azext_iot.adr.ui.core.spec import Column, Guide, ResourceSpec
from azext_iot.adr.ui.kinds._common import name_column, name_of, prop, state_column


def build_schema_registry(session):
    def list_registries(scope):
        return session.list_from("schema_registry", "list", resource_group_name=scope.get("resource_group_name"))

    return ResourceSpec(
        kind="schema-registry", title="Schema registry", title_plural="Schema registries",
        aliases=("schema",), row_id=lambda p: p.get("id") or name_of(p), list=list_registries,
        columns=(name_column(), state_column(), Column("location", "LOCATION", prop("location"), width=18)),
        guide=Guide("Schema registry inventory.", runs="az iot adr schema registry list · read-only",
                    note="Storage access and schema content are managed through the release CLI."),
    )


def build_device_class(session):
    def list_classes(scope):
        return session.list_from("device_class", "list", namespace_name=scope["namespace_name"],
                                 resource_group_name=scope["resource_group_name"])

    return ResourceSpec(
        kind="device-class", title="Device class", title_plural="Device classes", parent="namespace",
        row_id=lambda p: p["deviceClassId"], list=list_classes, requires=("namespace_name", "resource_group_name"),
        columns=(Column("name", "DEVICE CLASS", lambda p: p["deviceClassId"], width=36),
                 Column("friendly", "FRIENDLY NAME", prop("friendlyName"), width=26)),
        guide=Guide("Device classes from the linked update service.", runs="az iot adr ns su device-class list · read-only"),
    )


def build_software_update(session):
    def name(payload):
        update = payload["updateId"]
        return "/".join(update[key] for key in ("provider", "name", "version"))

    def list_updates(scope):
        return session.list_from("software_update", "list_updates", namespace_name=scope["namespace_name"],
                                 resource_group_name=scope["resource_group_name"])

    return ResourceSpec(
        kind="software-update", title="Software update", title_plural="Software updates", parent="namespace",
        row_id=name, list=list_updates, requires=("namespace_name", "resource_group_name"),
        columns=(Column("name", "PROVIDER / NAME / VERSION", name, width=45),
                 Column("state", "STATE", prop("state"), width=16)),
        guide=Guide("Software update catalog metadata.", runs="az iot adr ns su software-update list · read-only",
                    note="Import and staging remain in the release CLI; radar never downloads update files."),
    )
