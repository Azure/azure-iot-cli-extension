# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Parameter definitions for Azure Device Registry (ADR) namespace commands.
"""

from azure.cli.core.commands.parameters import (
    get_location_type,
    resource_group_name_type,
    tags_type,
    get_enum_type,
    get_three_state_flag,
)
from azext_iot.adr.common import (
    CertificateAuthorityKeyType,
    CertificateAuthorityIssuerType,
    CertificateAuthorityType,
    MessagingEndpointAvailability,
    RegistryDeviceEnablementState,
)


def load_adr_arguments(self, _):
    """Load arguments for ADR namespace commands."""

    wait_commands = (
        "iot adr ns wait",
        "iot adr ns ca wait",
        "iot adr ns ca policy wait",
        "iot adr ns device wait",
        "iot adr ns identity wait",
        "iot adr ns link wait",
        "iot adr ns link hub wait",
        "iot adr ns link dps wait",
    )
    for command in wait_commands:
        created_help = (
            "Wait until the software update exists. Software updates have no provisioningState."
            if command == "iot adr ns su software-update wait"
            else "Wait until provisioningState is Succeeded."
        )
        with self.argument_context(command) as context:
            context.argument(
                "timeout",
                options_list=["--timeout"],
                type=int,
                default=3600,
                arg_group="Wait Condition",
                help="Polling budget in seconds, including GET time. An in-flight GET is bounded by "
                     "transport timeouts and cannot be interrupted by this polling deadline.",
            )
            context.argument(
                "interval",
                options_list=["--interval"],
                type=int,
                default=30,
                arg_group="Wait Condition",
                help="Polling interval in seconds.",
            )
            context.argument(
                "created",
                options_list=["--created"],
                action="store_true",
                arg_group="Wait Condition",
                help=created_help,
            )
            context.argument(
                "updated",
                options_list=["--updated"],
                action="store_true",
                arg_group="Wait Condition",
                help=created_help,
            )
            context.argument(
                "deleted",
                options_list=["--deleted"],
                action="store_true",
                arg_group="Wait Condition",
                help="Wait until the resource is deleted.",
            )
            context.argument(
                "exists",
                options_list=["--exists"],
                action="store_true",
                arg_group="Wait Condition",
                help="Wait until the resource exists.",
            )
            context.argument(
                "custom",
                options_list=["--custom"],
                arg_group="Wait Condition",
                help="Wait until a custom JMESPath expression evaluates to true.",
            )

    # Common arguments
    with self.argument_context("iot adr ns") as context:
        context.argument("resource_group_name", arg_type=resource_group_name_type)
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--name", "-n"],
            help="Name of the Device Registry namespace.",
        )
        context.argument("tags", arg_type=tags_type)

    # Namespace create arguments
    with self.argument_context("iot adr ns create") as context:
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
        )

    with self.argument_context("iot adr ns migrate") as context:
        context.argument(
            "resource_ids",
            options_list=["--resource-ids", "--ids"],
            nargs="+",
            required=True,
            help="Space-separated resource IDs of legacy "
                 "Microsoft.DeviceRegistry/assets resources to migrate.",
        )

    # Certificate Authority arguments
    with self.argument_context("iot adr ns ca") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "certificate_authority_name",
            options_list=["--name", "-n", "--ca-name"],
            help="Name of the certificate authority.",
        )
        context.argument("tags", arg_type=tags_type)

    with self.argument_context("iot adr ns ca create") as context:
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
        )
        context.argument(
            "certificate_authority_type",
            options_list=["--type", "--ca-type"],
            arg_type=get_enum_type(CertificateAuthorityType),
            help="The certificate authority type. Use 'Root' for a service-managed self-signed root CA "
                 "or 'ICA' for an intermediate CA.",
        )
        context.argument(
            "issuer_type",
            options_list=["--issuer-type"],
            arg_type=get_enum_type(CertificateAuthorityIssuerType),
            help="Issuer type for an ICA. Use 'Microsoft' for a same-namespace CA or 'External' "
                 "for an external PKI.",
        )
        context.argument(
            "issuer_certificate_authority_name",
            options_list=["--issuer-ca-name", "--issuer-certificate-authority-name"],
            help="Name of the same-namespace issuing root CA. Required with "
                 "--issuer-type Microsoft.",
        )
        context.argument(
            "key_type",
            options_list=["--key-type"],
            arg_type=get_enum_type(CertificateAuthorityKeyType),
            help="The cryptographic key type for the certificate authority.",
        )

    with self.argument_context("iot adr ns ca activate") as context:
        context.argument(
            "certificate_chain_file",
            options_list=["--certificate-chain-file", "--ccf"],
            help="Path to a PEM file containing the signed certificate chain for an externally issued "
                 "ICA. Certificates must be ordered from leaf to root, match the service CSR key, "
                 "and preserve requested extensions. Allow remaining-validity margin at activation; "
                 "see activate help for the OpenSSL recipe and observed service constraints.",
        )

    # Certificate Policy (nested under a certificate authority) arguments
    with self.argument_context("iot adr ns ca policy") as context:
        context.argument(
            "certificate_policy_name",
            options_list=["--name", "-n", "--policy-name", "--pn"],
            help="Name of the certificate policy.",
        )
        context.argument(
            "certificate_authority_name",
            options_list=["--ca-name", "--ca"],
            help="Name of the parent certificate authority.",
        )

    with self.argument_context("iot adr ns ca policy create") as context:
        context.argument(
            "validity_days",
            options_list=["--validity-days", "--vd"],
            type=int,
            help="Leaf certificate validity period in days. Must be between 7 and "
                 "90 days, inclusive.",
        )

    with self.argument_context("iot adr ns ca policy update") as context:
        context.argument(
            "validity_days",
            options_list=["--validity-days", "--vd"],
            type=int,
            help="Updated leaf certificate validity period in days. Must be between "
                 "7 and 90 days, inclusive.",
        )

    with self.argument_context("iot adr ns device") as context:
        context.argument(
            "namespace_name", options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "registry_device_name", options_list=["--device-name", "--dn", "--name", "-n"],
            help="Name of the Registry Device.",
        )

    for verb in ("create", "update"):
        with self.argument_context(f"iot adr ns device {verb}") as context:
            context.argument("tags", arg_type=tags_type)
            context.argument(
                "enablement_state", options_list=["--enablement-state"],
                arg_type=get_enum_type(RegistryDeviceEnablementState),
                help="Whether the Registry Device is enabled or disabled.",
            )
            for field, description in (
                ("manufacturer", "Manufacturer"), ("model", "Model"),
                ("hardware_revision", "Hardware revision"), ("software_revision", "Software revision"),
            ):
                context.argument(
                    field, options_list=[f"--{field.replace('_', '-')}"],
                    help=f"{description} of the Registry Device.",
                )

    with self.argument_context("iot adr ns device create") as context:
        context.argument("location", arg_type=get_location_type(self.cli_ctx))
        context.argument(
            "external_device_id", options_list=["--external-device-id", "--ext-id"],
            help="Customer-provided device ID. This property is create-only.",
        )

    for verb in ("show", "wait"):
        with self.argument_context(f"iot adr ns device {verb}") as context:
            context.argument(
                "external_device_id", options_list=["--external-device-id", "--ext-id"],
                help="Customer-provided external ID. Specify exactly one of this option or --name. "
                "Lookup follows all namespace result pages; duplicate matches are an error.",
            )

    # Namespace managed identity
    for cmd in ["iot adr ns identity assign", "iot adr ns identity remove"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "system_assigned",
                options_list=["--system-assigned", "--system"],
                arg_type=get_three_state_flag(),
                help="Assign or remove the namespace system-assigned managed identity.",
            )
            context.argument(
                "user_assigned_identities",
                options_list=["--user-assigned-identity", "--user"],
                nargs="*",
                help="Space-separated user-assigned managed identity resource IDs. On "
                     "remove, omit values to remove all user-assigned identities.",
            )

    # Outbound managed identity arguments (namespace create + update)
    for cmd in ["iot adr ns create", "iot adr ns update"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "outbound_mi_system_assigned",
                arg_group="Outbound Identity",
                options_list=[
                    "--outbound-system-assigned-mi",
                    "--omi-sa",
                ],
                arg_type=get_three_state_flag(),
                help="Enable the system-assigned managed identity as the outbound identity used by "
                     "this namespace when calling linked Hub/DPS resources.",
            )
            context.argument(
                "outbound_mi_user_assigned",
                arg_group="Outbound Identity",
                options_list=[
                    "--outbound-user-assigned-mi",
                    "--omi-ua",
                ],
                help="User-assigned managed identity resource ID to assign to the namespace and use "
                     "for outbound calls.",
            )

    # --subscription is registered by Azure CLI as the global _subscription
    # action. Link handlers receive the namespace client from their command
    # factory, so a command-local argument here would only create a collision.
    with self.argument_context("iot adr ns link") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that owns the link.",
        )

    with self.argument_context("iot adr ns link wait") as context:
        context.argument(
            "hub_endpoint_name",
            options_list=["--hub-endpoint-name", "--hen"],
            help="Hub endpoint to include in the wait scope.",
        )
        context.argument(
            "dps_endpoint_name",
            options_list=["--dps-endpoint-name", "--den"],
            help="DPS endpoint to include in the wait scope.",
        )

    # Link hub arguments
    with self.argument_context("iot adr ns link hub") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that owns the link.",
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--en", "--name", "-n"],
            help="Logical name of the messaging endpoint entry on the namespace.",
        )

    for cmd in ["iot adr ns link hub add", "iot adr ns link hub update"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "mi_system_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--system-assigned-mi",
                    "--mi-sa",
                ],
                arg_type=get_three_state_flag(),
                help="Use the linked IoT Hub's system-assigned identity as the inbound caller "
                     "identity. The Hub must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--user-assigned-mi",
                    "--mi-ua",
                ],
                help="Resource ID of a user-assigned identity attached to the linked IoT Hub.",
            )

    with self.argument_context("iot adr ns link hub add") as context:
        context.argument(
            "availability",
            arg_group="Provisioning",
            options_list=["--availability"],
            arg_type=get_enum_type(MessagingEndpointAvailability),
            help="Whether the endpoint is available for provisioning new devices.",
        )
        context.argument(
            "allocation_weight",
            arg_group="Provisioning",
            options_list=["--allocation-weight", "--weight"],
            type=int,
            help="Relative allocation weight used when distributing devices across endpoints.",
        )
        context.argument(
            "hub_resource_id",
            options_list=["--hub-resource-id", "--hub-id"],
            help="Azure resource ID of the IoT Hub to link to this namespace.",
        )

    # Link DPS arguments
    with self.argument_context("iot adr ns link dps") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that owns the link.",
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--en", "--name", "-n"],
            help="Logical name of the provisioning endpoint entry on the namespace.",
        )

    for cmd in ["iot adr ns link dps add", "iot adr ns link dps update"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "mi_system_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--system-assigned-mi",
                    "--mi-sa",
                ],
                arg_type=get_three_state_flag(),
                help="Use the linked DPS resource's system-assigned identity as the inbound caller "
                     "identity. DPS must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--user-assigned-mi",
                    "--mi-ua",
                ],
                help="Resource ID of a user-assigned identity attached to the linked DPS resource.",
            )

    with self.argument_context("iot adr ns link dps add") as context:
        context.argument(
            "dps_resource_id",
            options_list=["--dps-resource-id", "--dps-id"],
            help="Azure resource ID of the Device Provisioning Service to link to this namespace.",
        )

    for action in ("add", "update"):
        with self.argument_context(f"iot adr ns link su {action}") as context:
            context.argument(
                "mi_system_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--system-assigned-mi",
                    "--mi-sa",
                ],
                arg_type=get_three_state_flag(),
                help="Use the linked Update Instance's system-assigned "
                     "identity. The instance must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=[
                    "--user-assigned-mi",
                    "--mi-ua",
                ],
                help="Resource ID of a user-assigned identity attached to the "
                     "linked Update Instance.",
            )

    for kind in ("hub", "dps"):
        for action in ("add", "update"):
            with self.argument_context(f"iot adr ns link {kind} {action}") as context:
                context.argument(
                    "timeout", options_list=["--timeout"], type=int, arg_group="Wait Condition",
                    help="Positive mutation/recovery budget in seconds after initial RBAC preflight. Default: 600.",
                )
                context.argument(
                    "interval", options_list=["--interval"], type=int, arg_group="Wait Condition",
                    help="Positive polling interval in seconds. Default: 30.",
                )
                context.argument(
                    "no_wait", options_list=["--no-wait"], action="store_true",
                    help="Return after submission without observing endpoint readiness or recovering later failures.",
                )

    # Combined DPS-first link add
    with self.argument_context("iot adr ns link add") as context:
        context.argument(
            "timeout", options_list=["--timeout"], type=int, arg_group="Wait Condition",
            help="Positive shared mutation/recovery budget in seconds for DPS and Hub "
                 "after initial RBAC preflight. Default: 600.",
        )
        context.argument(
            "interval", options_list=["--interval"], type=int, arg_group="Wait Condition",
            help="Polling interval in seconds. Must be greater than zero.",
        )
        context.argument(
            "no_wait",
            help="Wait for DPS linking to succeed, then return without waiting for the final Hub operation.",
        )
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that will own both new links.",
        )
        context.argument(
            "hub_endpoint_name",
            arg_group="Hub",
            options_list=[
                "--hub-endpoint-name",
                "--hen",
            ],
            help="Logical name of the Hub messaging endpoint entry on the namespace.",
        )
        context.argument(
            "hub_resource_id",
            arg_group="Hub",
            options_list=["--hub-resource-id", "--hub-id"],
            help="Azure resource ID of the IoT Hub to link.",
        )
        context.argument(
            "hub_mi_system_assigned",
            arg_group="Hub",
            options_list=[
                "--hub-system-assigned-mi",
                "--hub-mi-sa",
            ],
            arg_type=get_three_state_flag(),
            help="Use the linked IoT Hub's system-assigned identity as its inbound caller identity.",
        )
        context.argument(
            "hub_mi_user_assigned",
            arg_group="Hub",
            options_list=[
                "--hub-user-assigned-mi",
                "--hub-mi-ua",
            ],
            help="User-assigned identity resource ID attached to the linked IoT Hub.",
        )
        context.argument(
            "hub_availability",
            arg_group="Hub",
            options_list=["--hub-availability"],
            arg_type=get_enum_type(MessagingEndpointAvailability),
            help="Hub messaging endpoint availability.",
        )
        context.argument(
            "hub_allocation_weight",
            arg_group="Hub",
            options_list=["--hub-allocation-weight", "--hub-weight"],
            type=int,
            help="Hub messaging endpoint allocation weight.",
        )
        context.argument(
            "dps_endpoint_name",
            arg_group="DPS",
            options_list=[
                "--dps-endpoint-name",
                "--den",
            ],
            help="Logical name of the DPS provisioning endpoint entry on the namespace.",
        )
        context.argument(
            "dps_resource_id",
            arg_group="DPS",
            options_list=["--dps-resource-id", "--dps-id"],
            help="Azure resource ID of the Device Provisioning Service to link.",
        )
        context.argument(
            "dps_mi_system_assigned",
            arg_group="DPS",
            options_list=[
                "--dps-system-assigned-mi",
                "--dps-mi-sa",
            ],
            arg_type=get_three_state_flag(),
            help="Use the linked DPS resource's system-assigned identity as its inbound caller identity.",
        )
        context.argument(
            "dps_mi_user_assigned",
            arg_group="DPS",
            options_list=[
                "--dps-user-assigned-mi",
                "--dps-mi-ua",
            ],
            help="User-assigned identity resource ID attached to the linked DPS resource.",
        )

    # Group arguments

    # Job arguments

    # Job run arguments
