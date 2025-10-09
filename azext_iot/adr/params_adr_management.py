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
        # Enable credential and policy creation
        context.argument(
            "enable_credential_policy",
            arg_group="Credential",
            options_list=["--enable-credential-policy", "--ecp"],
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

    # Policy create arguments can be used on ns policy create/update or ns create
    for cmd in ["iot adr ns policy create", "iot adr ns policy update", "iot adr ns create"]:
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
            context.argument(
                "certificate_validity_days",
                options_list=["--cert-validity-days"],
                type=int,
                arg_group="Policy Certificate",
                help="Policy certificate validity period in days.",
            )
