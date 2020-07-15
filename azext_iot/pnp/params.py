# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azext_iot.pnp.common import (
    RoleResourceType,
    RoleIdentifier,
    SubjectType,
    ModelState,
    ModelType,
)
from azure.cli.core.commands.parameters import get_enum_type, get_three_state_flag


def load_pnp_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot pnp") as context:
        context.argument(
            "pnp_dns_suffix",
            options_list=["--pnp-dns-suffix"],
            help="An optional PnP DNS suffix used to interact with different PnP environments"
        )

    with self.argument_context("iot pnp role-assignment") as context:
        context.argument(
            "resource_id",
            options_list=["--resource-id"],
            help="The ID of the resource to manage role assignments for",
        )
        context.argument(
            "subject_id",
            options_list=["--subject-id"],
            help="The ID of a specific subject (User or Service Principal) to manage role assignments for.",
        )
        context.argument(
            "resource_type",
            arg_type=get_enum_type(RoleResourceType),
            options_list=["--resource-type"],
            help="Resource Type for role",
        )
        context.argument(
            "role",
            arg_type=get_enum_type(RoleIdentifier),
            options_list=["--role"],
            help="Role for assignment",
        )
    with self.argument_context("iot pnp role-assignment create") as context:
        context.argument(
            "subject_type",
            arg_type=get_enum_type(SubjectType),
            options_list=["--subject-type"],
            help="Subject Type for role assignment",
        )
    with self.argument_context("iot pnp model") as context:
        context.argument(
            "model_id",
            options_list=["--model-id", "--dtmi"],
            help="Digital Twins model Id. Example: dtmi:example:Room;2",
        )
    with self.argument_context("iot pnp model create") as context:
        context.argument(
            "model",
            options_list=["--model"],
            help="IoT Plug and Play capability-model definition written in DTDL (JSON-LD). "
            "Can either be directly input or a file path where the content is extracted from.",
        )
    with self.argument_context("iot pnp model show") as context:
        context.argument(
            "expand",
            options_list=["--expand", "--def", "--definition"],
            arg_type=get_three_state_flag(),
            help="Expand the model’s referenced definitions inline",
        )
    with self.argument_context("iot pnp model list") as context:
        context.argument(
            "keyword",
            options_list=["--keyword", "-q"],
            help="Restrict model list to those matching a provided keyword",
        )
        context.argument(
            "created_by",
            options_list=["--created-by"],
            help="Restrict model list to models created by a specific user or service principal",
        )
        context.argument(
            "model_state",
            arg_type=get_enum_type(ModelState),
            options_list=["--state", "--model-state"],
            help="Restrict model list to models with a specific state",
        )
        context.argument(
            "model_type",
            arg_type=get_enum_type(ModelType),
            options_list=["--type", "--model-type"],
            help="Restrict model list to models with a specific type",
        )
        context.argument(
            "publisher_id",
            options_list=["--publisher-id", "--pub"],
            help="Restrict model list to models published by a specific user or service principal",
        )
        context.argument(
            "shared",
            arg_type=get_three_state_flag(),
            options_list=["--shared"],
            help="Restrict model list to shared models only",
        )
