# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azure.cli.core.commands.parameters import (
    resource_group_name_type,
    get_three_state_flag,
    get_enum_type,
    tags_type,
)
from azext_iot.deviceupdate.common import (
    ADUPublicNetworkAccessType,
    ADUPrivateLinkServiceConnectionStatus,
    ADUAccountSKUType
)


def load_deviceupdate_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot device-update") as context:
        context.argument(
            "resource_group_name",
            arg_type=resource_group_name_type,
            help="Device Update account resource group name. "
            "You can configure the default group using `az configure --defaults group=<name>`.",
        )
        context.argument(
            "name",
            options_list=["-n", "--account"],
            help="Device Update account name.",
        )
        context.argument(
            "instance_name",
            options_list=["-i", "--instance"],
            help="Device Update instance name.",
        )
        context.argument(
            "public_network_access",
            options_list=["--public-network-access", "--pna"],
            help="Indicates if the Device Update account can be accessed from a public network.",
            arg_group="Network",
            arg_type=get_enum_type(ADUPublicNetworkAccessType),
        )
        context.argument(
            "tags",
            options_list=["--tags"],
            arg_type=tags_type,
            help="Resource tags. Property bag in key-value pairs with the following format: a=b c=d",
        )
        context.argument(
            "public_network_access",
            options_list=["--public-network-access", "--pna"],
            help="Indicates if the Device Update account can be accessed from a public network.",
            arg_group="Network",
            arg_type=get_enum_type(ADUPublicNetworkAccessType),
        )

    with self.argument_context("iot device-update account") as context:
        context.argument(
            "location",
            options_list=["-l", "--location"],
            help="Device Update account location. If no location is provided the resource group location is used. "
            "You can configure the default location using `az configure --defaults location=<name>`.",
        )
        context.argument(
            "assign_identity",
            arg_group="Managed Service Identity",
            nargs="+",
            help="Accepts system or user assigned identities separated by spaces. Use '[system]' "
            "to refer to the system assigned identity, or a resource Id to refer to a user assigned identity. "
            "Check out help for examples.",
        )
        context.argument(
            "scopes",
            arg_group="Managed Service Identity",
            nargs="+",
            options_list=["--scopes"],
            help="Space-separated scopes the system assigned identity can access. Cannot be used with --no-wait.",
        )
        context.argument(
            "role",
            arg_group="Managed Service Identity",
            options_list=["--role"],
            help="Role name or Id the system assigned identity will have.",
        )
        context.argument(
            "sku",
            options_list=["--sku"],
            help="Device Update account SKU.",
            arg_type=get_enum_type(ADUAccountSKUType),
        )

    with self.argument_context(
        "iot device-update account private-endpoint-connection"
    ) as context:
        context.argument(
            "conn_name",
            options_list=["--cn", "--conn-name"],
            help="Private endpoint connection name.",
        )
        context.argument(
            "status",
            options_list=["--status"],
            help="The status of the private endpoint connection.",
            arg_type=get_enum_type(ADUPrivateLinkServiceConnectionStatus),
        )
        # @digimaun - actionsRequired is in exposed in the API spec however it is not yet implemented.
        # context.argument(
        #     "actions",
        #     options_list=["--actions"],
        #     help="Message indicating if changes on the service provider require any updates on the consumer.",
        # )
        context.argument(
            "description",
            options_list=["--desc"],
            help="The reason for approval/rejection of the connection.",
        )

    with self.argument_context("iot device-update instance") as context:
        context.argument(
            "location",
            options_list=["-l", "--location"],
            help="Device Update instance location. If no location is provided the encompassing account location is used. "
            "You can configure the default location using `az configure --defaults location=<name>`.",
        )
        context.argument(
            "iothub_resource_ids",
            arg_group="IoT Hub",
            nargs="+",
            options_list=["--iothub-ids"],
            help="Space-separated IoT Hub resource Ids.",
        )
        context.argument(
            "diagnostics",
            options_list=["--enable-diagnostics"],
            help="Enables diagnostic logs collection.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "storage_resource_id",
            arg_group="Storage",
            options_list=["--diagnostics-storage-id"],
            help="User provided storage account resource Id for use in diagnostic logs collection.",
        )
