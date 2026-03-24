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
from azure.cli.core.commands.validators import get_default_location_from_resource_group
from azext_iot.adr.common import (
    PolicyCertificateKeyType,
)


def load_adr_management_arguments(self, _):
    """Load arguments for ADR namespace commands."""

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
            validator=get_default_location_from_resource_group,
        )
        # Enable certificate management and policy creation
        context.argument(
            "enable_certificate_management",
            arg_group="Credential",
            options_list=["--enable-certificate-management", "--ecm"],
            arg_type=get_three_state_flag(),
            help="Create a credential and credential policy for this Device Registry namespace. "
                 "This is also enabled when any custom policy parameters are provided.",
        )
        context.argument(
            "policy_name",
            arg_group="Policy",
            options_list=["--policy-name", "--pn"],
            help="Customize the name of the namespace credential policy",
        )

    # Credentials naming arguments
    with self.argument_context("iot adr ns credential") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )

    # Policy naming arguments
    with self.argument_context("iot adr ns policy") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        # TODO - CMS Preview - (-n for standard naming convention, --pn to match adr ns create)
        context.argument(
            "policy_name", options_list=["--policy-name", "--pn", "--name", "-n"], help="Name of the policy."
        )

    # Policy certificate arguments for create commands only (key type and subject cannot be changed after creation)
    for cmd in ["iot adr ns policy create", "iot adr ns create"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "certificate_key_type",
                options_list=["--cert-key-type"],
                arg_type=get_enum_type(PolicyCertificateKeyType),
                arg_group="Policy Certificate",
                help="Policy certificate authority key type.",
            )
            context.argument(
                "certificate_subject",
                options_list=["--cert-subject"],
                help="Policy certificate subject.",
                arg_group="Policy Certificate",
            )

    # Certificate validity can be set on create or update
    for cmd in ["iot adr ns policy create", "iot adr ns policy update", "iot adr ns create"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "certificate_validity_days",
                options_list=["--cert-validity-days"],
                type=int,
                arg_group="Policy Certificate",
                help="Policy certificate validity period in days.",
            )

    # BYOR (Bring Your Own Root) arguments for policy create
    with self.argument_context("iot adr ns policy create") as context:
        context.argument(
            "enable_byor",
            options_list=["--enable-byor"],
            arg_type=get_three_state_flag(),
            arg_group="Bring Your Own Root",
            help="Enable Bring Your Own Root (BYOR) mode for the policy. "
                 "When enabled, you must sign the service-generated CSR with your own CA "
                 "and activate using 'az iot adr ns policy activate-byor'. "
                 "This cannot be changed after policy creation.",
        )

    # BYOR activation arguments
    with self.argument_context("iot adr ns policy activate-byor") as context:
        context.argument(
            "certificate_chain_file",
            options_list=["--certificate-chain-file", "--ccf"],
            help="Path to a PEM file containing the signed certificate chain. "
                 "The file must contain the signed certificate (matching the CSR from policy show), "
                 "followed by any intermediate CAs, and optionally the root CA. "
                 "Certificates must be ordered from leaf to root.",
        )

    # Device arguments
    with self.argument_context("iot adr ns device") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "device_name",
            options_list=["--device-name", "--dn", "--name", "-n"],
            help="Name of the device.",
        )

    # Device update arguments
    with self.argument_context("iot adr ns device update") as context:
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "enabled",
            options_list=["--enabled"],
            arg_type=get_three_state_flag(),
            help="Enable or disable the device. A disabled device cannot authenticate with Microsoft Entra ID.",
        )
        context.argument(
            "operating_system_version",
            options_list=["--os-version"],
            help="Operating system version of the device.",
        )
        context.argument(
            "attributes",
            options_list=["--attributes"],
            help="Device attributes in JSON format.",
        )
        context.argument(
            "policy_resource_id",
            options_list=["--policy-resource-id"],
            help="Resource ID of the credential policy to associate with the device.",
        )

    # Device revoke arguments
    with self.argument_context("iot adr ns device revoke") as context:
        context.argument(
            "disable",
            options_list=["--disable"],
            action="store_true",
            help="Disable the device after revoking credentials. "
                 "Prevents new credentials from being issued.",
        )
