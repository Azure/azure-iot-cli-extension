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
    ADUAccountSKUType,
    ADUManageDeviceImportType,
    ADUValidHashAlgorithmType,
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
            "You can configure the default group using `az config set defaults.adu_group=<name>`.",
            arg_group="Account Identifier",
            configured_default="adu_group",
        )
        context.argument(
            "name",
            options_list=["-n", "--account"],
            help="Device Update account name. "
            "You can configure the default account name using `az config set defaults.adu_account=<name>`.",
            arg_group="Account Identifier",
            configured_default="adu_account",
        )
        context.argument(
            "instance_name",
            options_list=["-i", "--instance"],
            help="Device Update instance name."
            "You can configure the default instance name using `az config set defaults.adu_instance=<name>`.",
            arg_group="Account Identifier",
            configured_default="adu_instance",
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

    with self.argument_context("iot device-update account private-endpoint-connection") as context:
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
        context.argument(
            "description",
            options_list=["--desc"],
            help="The reason for approval/rejection of the connection.",
        )

    with self.argument_context("iot device-update instance") as context:
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

    with self.argument_context("iot device-update update") as context:
        context.argument(
            "update_name",
            options_list=["--update-name", "--un"],
            help="The update name.",
        )
        context.argument(
            "update_provider",
            options_list=["--update-provider", "--up"],
            help="The update provider.",
        )
        context.argument(
            "update_version",
            options_list=["--update-version", "--uv"],
            help="The update version.",
        )
        context.argument(
            "update_file_id",
            options_list=["--update-file-id", "--ufid"],
            help="The update file Id.",
        )
        context.argument(
            "friendly_name",
            options_list=["--friendly-name"],
            help="Friendly name associated with the update definition.",
        )

    with self.argument_context("iot device-update update list") as context:
        context.argument(
            "by_provider",
            options_list=["--by-provider"],
            help="Flag indicating the result set should be constrained to update providers.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "search",
            options_list=["--search"],
            help="Request updates matching a free-text search expression. "
            "Supported when listing updates with no constraints.",
            arg_group="Filter",
        )
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Restricts the set of updates returned by property values. "
            "Supported when listing updates with no constraints or when listing by version.",
            arg_group="Filter",
        )

    with self.argument_context("iot device-update update import") as context:
        context.argument(
            "url",
            options_list=["--url"],
            help="Routable location from which the import manifest can be downloaded by Device Update for IoT Hub. "
            "This is typically a read-only SAS-protected blob URL with an expiration set to at least 4 hours.",
        )
        context.argument(
            "file",
            options_list=["--file"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to import manifest metadata file properties. "
            "Required keys include filename and url. --file can be used 1 or more times.",
        )
        context.argument(
            "hashes",
            options_list=["--hashes"],
            nargs="+",
            help="Space-separated key=value pairs where the key is the hash algorithm used and the value is the base64 encoded "
            "import manifest file hash. At least a sha256 entry is required. "
            "If not provided it will by calculated from the provided url.",
        )
        context.argument(
            "size",
            type=int,
            options_list=["--size"],
            help="File size in number of bytes. " "If not provided it will by calculated from the provided url.",
        )

    with self.argument_context("iot device-update device") as context:
        context.argument(
            "device_group_id",
            options_list=["--group-id", "--gid"],
            help="Device group Id. This is created from the value of the ADUGroup tag in the connected IoT Hub's "
            "device/module twin or $default for devices with no tag.",
        )
        context.argument(
            "device_class_id",
            options_list=["--class-id", "--cid"],
            help="Device class Id. This is generated from the model Id and the compat properties reported by the "
            "device update agent in the Device Update PnP interface in IoT Hub. It is a hex-encoded SHA1 hash.",
        )

    with self.argument_context("iot device-update device list") as context:
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Restricts the set of devices returned. You can filter on groupId, deviceClassId, "
            "or groupId and deploymentStatus.",
        )

    with self.argument_context("iot device-update device health") as context:
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Device health filter. Supports the properties of state or deviceId. "
            "If deviceId is provided moduleId can be optionally specified.",
        )

    with self.argument_context("iot device-update device class") as context:
        context.argument(
            "installable_updates",
            options_list=["--installable-updates"],
            help="Flag indicating the command should fetch installable updates for the device class.",
            arg_group="Update",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "best_update",
            options_list=["--best-update"],
            help="Flag indicating the command should fetch the best available update for the device class subgroup including "
            "a count of how many devices need the update. Group Id is required for this flag. "
            "A best update is the latest update that meets all compatibility specifications of a device class. ",
            arg_group="Update",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "update_compliance",
            options_list=["--update-compliance"],
            help="Flag indicating the command should fetch device class subgroup update compliance information, "
            "such as how many devices are on their latest update, how many need new updates, and how many are "
            "in progress on receiving a new update. Group Id is required for this flag.",
            arg_group="Update",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "friendly_name",
            options_list=["--friendly-name"],
            help="The device class friendly name. The friendly name must be 1 - 100 characters and supports "
            "alphanumeric, dot and dash values.",
        )

    with self.argument_context("iot device-update device class list") as context:
        context.argument(
            "filter",
            options_list=["--filter"],
            help="If provided with --group-id, supports filtering based on device class compat property names "
            "and values. For example \"compatProperties/manufacturer eq 'Contoso'\". "
            "Otherwise supports filtering by class friendly name.",
        )

    with self.argument_context("iot device-update device group") as context:
        context.argument(
            "best_updates",
            options_list=["--best-updates"],
            help="Flag indicating the command should fetch the best available updates for the device group including "
            "a count of how many devices need each update. "
            "A best update is the latest update that meets all compatibility specifications of a device class. ",
            arg_group="Update",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "update_compliance",
            options_list=["--update-compliance"],
            help="Flag indicating the command should fetch device group update compliance information such as how many devices "
            "are on their latest update, how many need new updates, and how many are in progress on receiving a new update.",
            arg_group="Update",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "order_by",
            options_list=["--order-by"],
            help="Orders the set of groups returned. You can order by groupId, deviceCount, "
            "createdDateTime, subgroupsWithNewUpdatesAvailableCount, subgroupsWithUpdatesInProgressCount "
            "or subgroupsWithOnLatestUpdateCount.",
        )

    with self.argument_context("iot device-update device import") as context:
        context.argument(
            "import_type",
            options_list=["--import-type", "--it"],
            help="The types of devices to import from IoT Hub.",
            arg_type=get_enum_type(ADUManageDeviceImportType),
        )

    with self.argument_context("iot device-update device deployment") as context:
        context.argument(
            "deployment_id",
            options_list=["--deployment-id", "--did"],
            help="The caller-provided deployment Id. This cannot be longer than 73 characters, "
            "must be all lower-case, and cannot contain '&', '^', '[', ']', '{', '}', '|', '<', '>', "
            "forward slash, backslash, or double quote.",
        )
        context.argument(
            "status",
            options_list=["--status"],
            help="Gets the status of a deployment including a breakdown of how many devices "
            "in the deployment are in progress, completed, or failed.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "update_name",
            options_list=["--update-name", "--un"],
            help="The update name.",
            arg_group="Update Id",
        )
        context.argument(
            "update_provider",
            options_list=["--update-provider", "--up"],
            help="The update provider.",
            arg_group="Update Id",
        )
        context.argument(
            "update_version",
            options_list=["--update-version", "--uv"],
            help="The update version.",
            arg_group="Update Id",
        )
        context.argument(
            "order_by",
            options_list=["--order-by"],
            help="Orders the set of deployments returned. You can order by startDateTime [desc/asc].",
        )

    with self.argument_context("iot device-update device deployment list-devices") as context:
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Restricts the set of deployment device states returned. You can filter on "
            "deviceId and moduleId and/or deviceState.",
        )

    with self.argument_context("iot device-update device deployment create") as context:
        context.argument(
            "start_date_time",
            options_list=["--start-time"],
            help="The iso-8601 compliant start time for deployment. If no value is provided the "
            "corresponding value for UTC 'now' will be used.",
        )
        context.argument(
            "rollback_update_name",
            options_list=["--rollback-update-name", "--rbun"],
            help="The rollback update name.",
            arg_group="Update Rollback Policy",
        )
        context.argument(
            "rollback_update_provider",
            options_list=["--rollback-update-provider", "--rbup"],
            help="The rollback update provider.",
            arg_group="Update Rollback Policy",
        )
        context.argument(
            "rollback_update_version",
            options_list=["--rollback-update-version", "--rbuv"],
            help="The rollback update version.",
            arg_group="Update Rollback Policy",
        )
        context.argument(
            "devices_failed_count",
            type=int,
            options_list=["--failed-count", "--fc"],
            help="Integer representing the number of failed devices in a deployment before a cloud initated rollback occurs. "
            "Required when defining rollback policy.",
            arg_group="Update Rollback Policy",
        )
        context.argument(
            "devices_failed_percentage",
            type=int,
            options_list=["--failed-percentage", "--fp"],
            help="Integer representing the percentage of failed devices in a deployment before a cloud initated rollback occurs. "
            "Required when defining rollback policy.",
            arg_group="Update Rollback Policy",
        )

    with self.argument_context("iot device-update device log") as context:
        context.argument(
            "log_collection_id",
            options_list=["--log-collection-id", "--lcid"],
            help="Log collection Id.",
        )
        context.argument(
            "detailed_status",
            options_list=["--detailed"],
            help="Flag indicating whether the command should fetch the detailed status of a log collection operation.",
            arg_type=get_three_state_flag(),
        )

    with self.argument_context("iot device-update device log collect") as context:
        context.argument(
            "agent_id",
            options_list=["--agent-id"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to device update agent identifier properties. "
            "The key of deviceId is required, while moduleId is optional. --agent-id can be used 1 or more times.",
        )
        context.argument(
            "description",
            options_list=["--description"],
            help="Description for the log collection operation.",
        )

    with self.argument_context("iot device-update update init") as context:
        context.argument(
            "update_provider",
            options_list=["--update-provider"],
            help="The update provider as a component of updateId.",
        )
        context.argument(
            "update_name",
            options_list=["--update-name"],
            help="The update name as a component of updateId.",
        )
        context.argument(
            "update_version",
            options_list=["--update-version"],
            help="The update version as a component of updateId.",
        )
        context.argument(
            "description",
            options_list=["--description"],
            help="Description for the import update manifest.",
        )
        context.argument(
            "deployable",
            options_list=["--is-deployable"],
            arg_type=get_three_state_flag(),
            help="Indicates whether the update is independently deployable.",
        )
        context.argument(
            "compatibility",
            options_list=["--compat"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to properties of a device this update is compatible with. "
            "Typically used for defining properties such as manufacturer and model. "
            "--compat can be used 1 or more times. ",
        )
        context.argument(
            "steps",
            options_list=["--step"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to 'instructions.steps' element properties. "
            "The client will determine if a step is an inline or reference step based on the provided "
            "key value pairs. If either inline or reference step can be satisfied, the reference step will be prioritized. "
            "Usage of --file will be associated with the nearest inline --step entry, deriving the value for 'files'. "
            "The following reference step keys are supported: "
            "`updateId.provider`, `updateId.name` `updateId.version` and `description`."
            "The following inline step keys are supported: "
            "`handler` (ex: 'microsoft/script:1' or 'microsoft/swupdate:1' or 'microsoft/apt:1'), "
            "`properties` (in-line json object the agent will pass to the handler), and `description`. "
            "--step can be used 1 or more times.",
        )
        context.argument(
            "files",
            options_list=["--file"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to 'files' element properties. "
            "A --file entry can include the closest --related-file entries if provided. "
            "The following keys are supported: "
            "`path` [required] local file path to update file, "
            "`downloadHandler` (ex: 'microsoft/delta:1') handler for utilizing related files to download payload file, "
            "`properties` (in-line json object the agent will pass to the handler). "
            "--file can be used 1 or more times."
        )
        context.argument(
            "related_files",
            options_list=["--related-file"],
            nargs="+",
            action="append",
            help="Space-separated key=value pairs corresponding to 'files[*].relatedFiles' element properties. "
            "A --related-file entry will be associated to the closest --file entry if it exists. "
            "The following keys are supported: "
            "`path` [required] local file path to related update file, "
            "`properties` (in-line json object passed to the download handler). "
            "--related-file can be used 1 or more times."
        )
        context.argument(
            "file_paths",
            options_list=["--file-path"],
            nargs="+",
            action="append",
            help="Local path to target file for hash calculation. "
            "--file-path can be used 1 or more times."
        )
        context.argument(
            "hash_algo",
            options_list=["--hash-algo"],
            help="Cryptographic algorithm to use for hashing.",
            arg_type=get_enum_type(ADUValidHashAlgorithmType),
            type=str,
        )
        context.argument(
            "validate",
            options_list=["--validate"],
            arg_type=get_three_state_flag(),
            help="Apply json schema validation to the import manifest content.",
        )
