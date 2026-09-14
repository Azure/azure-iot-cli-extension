# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Certificate authorities, their policies, and Software Update instances."""

from azext_iot.adr.ui.core.spec import (
    STYLE_MUTED,
    STYLE_OK,
    ChildRef,
    Column,
    Guide,
    ResourceSpec,
)
from azext_iot.adr.ui.kinds._common import (
    age_column,
    dig,
    humanize_age,
    name_column,
    name_of,
    prop,
    resource_group_of,
    state_column,
    value_style,
)

_CA_TYPE_STYLES = {"Root": STYLE_OK, "ICA": STYLE_MUTED}


def build_ca(session) -> ResourceSpec:
    def list_authorities(scope):
        return session.list_from(
            "certificate_authority",
            "list",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="ca",
        title="Certificate authority",
        title_plural="Certificate authorities",
        aliases=("cert",),
        parent="namespace",
        guide=Guide(
            about="Certificate authorities this namespace trusts when devices present X.509 credentials.",
            runs="az iot adr ns ca list --ns <namespace> -g <resource-group>  ·  read-only",
            note="An expired or unverified authority silently prevents devices from onboarding.",
        ),
        row_id=name_of,
        list=list_authorities,
        columns=(
            name_column(width=26),
            Column(
                "type",
                "TYPE",
                prop("certificateAuthorityType"),
                width=8,
                style=value_style(prop("certificateAuthorityType"), _CA_TYPE_STYLES),
            ),
            Column("issuer", "ISSUER", prop("issuerType"), width=12),
            Column("issued_by", "ISSUED BY", prop("issuerCertificateAuthorityName"), width=22),
            Column(
                "expires",
                "EXPIRES IN",
                lambda p: humanize_age(prop("notAfter", default="")(p)),
                width=11,
                sort_key=lambda p: str(prop("notAfter", default="")(p)),
            ),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name"),
        scope_key="certificate_authority_name",
        children=(ChildRef("policy", "Certificate policies", "p"),),
    )


def build_policy(session) -> ResourceSpec:
    def list_policies(scope):
        return session.list_from(
            "certificate_policy",
            "list",
            certificate_authority_name=scope.get("certificate_authority_name"),
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="policy",
        title="Certificate policy",
        title_plural="Certificate policies",
        aliases=("pol",),
        parent="ca",
        guide=Guide(
            about="Rules applied when issuing or renewing certificates under this authority.",
            runs="az iot adr ns ca policy list --ns <namespace> -g <resource-group>  ·  read-only",
        ),
        row_id=name_of,
        list=list_policies,
        columns=(
            name_column(width=26),
            Column("validity", "VALIDITY (DAYS)", prop("validityDays"), width=16),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name", "certificate_authority_name"),
        scope_key="certificate_policy_name",
    )


def build_update_instance(session) -> ResourceSpec:
    def list_instances(scope):
        return session.list_from(
            "update_instance",
            "list",
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="su",
        title="Update instance",
        title_plural="Update instances",
        aliases=("update-instance",),
        guide=Guide(
            about="Software Updates instances - the service that runs update jobs against devices in this namespace.",
            runs="az iot adr ns su instance list -g <resource-group>  ·  read-only",
            note="Listed at resource-group level; linking one to a namespace is done in guided setup.",
        ),
        row_id=name_of,
        list=list_instances,
        columns=(
            name_column(width=28),
            Column("rg", "RESOURCE GROUP", resource_group_of, width=22),
            Column("location", "LOCATION", lambda p: p.get("location", ""), width=14),
            Column(
                "identity",
                "IDENTITY",
                lambda p: dig(p, "identity", "type", default="None"),
                width=20,
                wide=True,
            ),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        scope_key="update_instance_name",
    )
