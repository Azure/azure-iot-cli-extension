# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry devices and the collections the service materialises beneath them."""

from azext_iot.adr.ui.core.spec import (
    STYLE_MUTED,
    STYLE_OK,
    ChildRef,
    Column,
    Guide,
    ResourceSpec,
)
from azext_iot.adr.ui.kinds._common import (
    ENABLEMENT_STYLES,
    age_column,
    name_column,
    name_of,
    prop,
    state_column,
    value_style,
)

_AUTH_STYLES = {
    "SymmetricKey": STYLE_MUTED,
    "CertificateAuthority": STYLE_OK,
    "SelfSignedX509Certificate": STYLE_OK,
}


def build(session) -> ResourceSpec:
    def list_devices(scope):
        return session.list_from(
            "registry_device",
            "list",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="device",
        title="Registry device",
        title_plural="Registry devices",
        aliases=("dev", "rd", "registry-device"),
        parent="namespace",
        guide=Guide(
            about=(
                "Devices registered in this namespace, with the endpoints each one is allowed to use and its current "
                "enablement."
            ),
            runs="az iot adr ns registry-device list --ns <namespace> -g <resource-group>  ·  read-only",
            note=(
                "This is the registry record, not the device's live connection state; a device shown as enabled may "
                "still be offline."
            ),
        ),
        row_id=name_of,
        list=list_devices,
        columns=(
            name_column(width=26),
            Column(
                "enablement",
                "ENABLEMENT",
                prop("enablementState"),
                width=12,
                style=value_style(prop("enablementState"), ENABLEMENT_STYLES),
            ),
            Column("manufacturer", "MANUFACTURER", prop("manufacturer"), width=16),
            Column("model", "MODEL", prop("model"), width=14),
            Column("software", "SOFTWARE", prop("softwareRevision"), width=10),
            Column("external", "EXTERNAL ID", prop("externalDeviceId"), width=18, wide=True),
            Column("hardware", "HARDWARE", prop("hardwareRevision"), width=10, wide=True),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name"),
        scope_key="registry_device_name",
        children=(
            ChildRef("auth", "Authentication profiles", "a"),
            ChildRef("attribute", "Attributes", "t"),
            ChildRef("capability", "Capabilities", "b"),
        ),
    )


def build_auth(session) -> ResourceSpec:
    def list_auth(scope):
        return session.list_from(
            "registry_device",
            "auth_list",
            registry_device_name=scope.get("registry_device_name"),
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="auth",
        title="Authentication profile",
        title_plural="Authentication profiles",
        aliases=("auth",),
        parent="device",
        guide=Guide(
            about="How this device proves who it is - one profile per supported method.",
            runs=(
                "az iot adr ns registry-device auth list "
                "--registry-device-name <device> --ns <namespace> "
                "-g <resource-group>  ·  read-only"
            ),
            note="A device with no profile cannot connect until one is added.",
        ),
        row_id=name_of,
        list=list_auth,
        columns=(
            name_column(width=24),
            Column(
                "type",
                "TYPE",
                prop("authenticationType"),
                width=26,
                style=value_style(prop("authenticationType"), _AUTH_STYLES),
            ),
            Column("status", "STATUS", prop("status"), width=14),
            state_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name", "registry_device_name"),
        scope_key="authentication_profile_name",
    )


def build_attribute(session) -> ResourceSpec:
    def list_attributes(scope):
        return session.list_from(
            "registry_device",
            "attribute_list",
            registry_device_name=scope.get("registry_device_name"),
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="attribute",
        title="Attribute",
        title_plural="Attributes",
        aliases=("attr",),
        parent="device",
        guide=Guide(
            about=(
                "Free-form key/value metadata on this device. Groups can be defined by querying these, so they are "
                "worth keeping consistent."
            ),
            runs="Projected from the device payload already loaded  ·  no extra call",
        ),
        row_id=name_of,
        list=list_attributes,
        columns=(
            name_column(width=24),
            Column("reported", "REPORTED BY", prop("reportedBy"), width=24),
            Column("schema", "SCHEMA", prop("schema"), width=20, wide=True),
            state_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name", "registry_device_name"),
        scope_key="attribute_name",
    )


def build_capability(session) -> ResourceSpec:
    def list_capabilities(scope):
        return session.list_from(
            "registry_device",
            "capability_list",
            registry_device_name=scope.get("registry_device_name"),
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="capability",
        title="Capability",
        title_plural="Capabilities",
        aliases=("cap",),
        parent="device",
        guide=Guide(
            about="What this device reports it can do. Jobs use capabilities to decide which devices they apply to.",
            runs="Projected from the device payload already loaded  ·  no extra call",
        ),
        row_id=name_of,
        list=list_capabilities,
        columns=(
            name_column(width=28),
            Column("kind", "KIND", prop("capabilityType"), width=20),
            state_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name", "registry_device_name"),
        scope_key="capability_name",
    )
