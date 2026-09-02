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
from azext_iot.deviceupdate.common import ADUValidHashAlgorithmType
from azext_iot.adr.common import (
    CertificateAuthorityKeyType,
    CertificateAuthorityIssuerType,
    CertificateAuthorityType,
    DeviceAttributeReportedType,
    GroupType,
    JobType,
    MessagingEndpointAvailability,
    RegistryDeviceEnablementState,
    ReportType,
)


def load_adr_arguments(self, _):
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
    for cmd in ["iot adr ns create", "iot adr ns update"]:
        with self.argument_context(cmd) as context:
            context.argument(
                "observability_enabled",
                options_list=["--observability-enabled"],
                arg_type=get_three_state_flag(),
                help="Enable or disable namespace observability. When omitted, create "
                     "preserves the existing setting and update leaves it unchanged.",
            )
            context.argument(
                "messaging_endpoints",
                options_list=["--messaging-endpoints"],
                help="Messaging endpoint dictionary as inline JSON or a JSON file path.",
            )
            context.argument(
                "provisioning_endpoints",
                options_list=["--provisioning-endpoints"],
                help="Provisioning endpoint dictionary as inline JSON or a JSON file path.",
            )
            context.argument(
                "updating_endpoints",
                options_list=["--updating-endpoints"],
                help="Updating endpoint dictionary as inline JSON or a JSON file path. "
                     "At most one Software Updates endpoint may be linked per namespace.",
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
                 "ICA. Certificates must be ordered from leaf to root.",
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
        context.argument("tags", arg_type=tags_type)

    with self.argument_context("iot adr ns ca policy create") as context:
        context.argument(
            "validity_days",
            options_list=["--validity-days", "--vd"],
            type=int,
            help="Leaf certificate validity period in days.",
        )
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
        )

    with self.argument_context("iot adr ns ca policy update") as context:
        context.argument(
            "validity_days",
            options_list=["--validity-days", "--vd"],
            type=int,
            help="Updated leaf certificate validity period in days.",
        )

    # Registry Device arguments
    with self.argument_context("iot adr ns registry-device") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "registry_device_name",
            options_list=["--device-name", "--dn", "--name", "-n"],
            help="Name of the Registry Device.",
        )

    with self.argument_context("iot adr ns registry-device create") as context:
        context.argument("location", arg_type=get_location_type(self.cli_ctx))
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "enablement_state",
            options_list=["--enablement-state"],
            arg_type=get_enum_type(RegistryDeviceEnablementState),
            help="Whether the Registry Device is enabled or disabled.",
        )
        context.argument(
            "external_device_id",
            options_list=["--external-device-id", "--ext-id"],
            help="Customer-provided device ID. This property is create-only.",
        )
        context.argument(
            "manufacturer",
            options_list=["--manufacturer"],
            help="Manufacturer of the Registry Device.",
        )
        context.argument(
            "model",
            options_list=["--model"],
            help="Model of the Registry Device.",
        )
        context.argument(
            "hardware_revision",
            options_list=["--hardware-revision"],
            help="Hardware revision of the Registry Device.",
        )
        context.argument(
            "software_revision",
            options_list=["--software-revision"],
            help="Software revision of the Registry Device.",
        )

    with self.argument_context("iot adr ns registry-device update") as context:
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "enablement_state",
            options_list=["--enablement-state"],
            arg_type=get_enum_type(RegistryDeviceEnablementState),
            help="Whether the Registry Device is enabled or disabled.",
        )
        context.argument(
            "manufacturer",
            options_list=["--manufacturer"],
            help="Manufacturer of the Registry Device.",
        )
        context.argument(
            "model",
            options_list=["--model"],
            help="Model of the Registry Device.",
        )
        context.argument(
            "hardware_revision",
            options_list=["--hardware-revision"],
            help="Hardware revision of the Registry Device.",
        )
        context.argument(
            "software_revision",
            options_list=["--software-revision"],
            help="Software revision of the Registry Device.",
        )

    with self.argument_context(
        "iot adr ns registry-device auth"
    ) as context:
        context.argument(
            "registry_device_name",
            options_list=["--registry-device-name", "--rdn", "--device-name", "--dn"],
            help="Name of the parent Registry Device.",
        )
        context.argument(
            "authentication_profile_name",
            options_list=["--auth-profile-name", "--apn", "--name", "-n"],
            help="Name of the authentication profile.",
        )

    with self.argument_context(
        "iot adr ns registry-device attribute"
    ) as context:
        context.argument(
            "registry_device_name",
            options_list=["--registry-device-name", "--rdn", "--device-name", "--dn"],
            help="Name of the parent Registry Device.",
        )
        context.argument(
            "attribute_name",
            options_list=["--attribute-name", "--an", "--name", "-n"],
            help="Name of the Registry Device attribute.",
        )

    with self.argument_context(
        "iot adr ns registry-device attribute show"
    ) as context:
        context.argument(
            "attribute_name",
            options_list=["--attribute-name", "--an", "--name", "-n"],
            help="Name of the Registry Device attribute. 'software-update' is accepted "
            "as an alias for the Azure Device Update attribute, whose canonical "
            "resource name is 'update'; the alias only applies when no attribute "
            "matches the name you supplied.",
        )

    with self.argument_context(
        "iot adr ns registry-device attribute create"
    ) as context:
        context.argument(
            "reported_by",
            options_list=["--reported-by", "--rb"],
            arg_type=get_enum_type(DeviceAttributeReportedType),
            help="The cloud service that reports this attribute. 'Microsoft.DeviceUpdate' "
            "attributes are service-materialized; author your own metadata with 'User'.",
        )
        context.argument(
            "schema",
            options_list=["--schema"],
            help="URL of a JSON Schema document describing the shape of the attribute "
            "property bag. Advertisement only; the service does not validate against it.",
        )
        context.argument(
            "properties",
            options_list=["--properties", "--props"],
            help="Attribute property bag as inline JSON or a path to a JSON file "
            "prefixed with '@'. The service stores and returns the bag verbatim.",
        )

    with self.argument_context(
        "iot adr ns registry-device capability"
    ) as context:
        context.argument(
            "registry_device_name",
            options_list=["--registry-device-name", "--rdn", "--device-name", "--dn"],
            help="Name of the parent Registry Device.",
        )
        context.argument(
            "capability_name",
            options_list=["--capability-name", "--cn", "--name", "-n"],
            help="Name of the Registry Device capability.",
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
                options_list=["--outbound-mi-system-assigned", "--omi-sa"],
                arg_type=get_three_state_flag(),
                help="Enable the system-assigned managed identity as the outbound identity used by "
                     "this namespace when calling linked Hub/DPS resources.",
            )
            context.argument(
                "outbound_mi_user_assigned",
                arg_group="Outbound Identity",
                options_list=["--outbound-mi-user-assigned", "--omi-ua"],
                help="User-assigned managed identity resource ID to assign to the namespace and use "
                     "for outbound calls.",
            )

    with self.argument_context("iot adr ns link") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that owns the link.",
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
                options_list=["--mi-system-assigned", "--mi-sa"],
                arg_type=get_three_state_flag(),
                help="Use the linked IoT Hub's system-assigned identity as the inbound caller "
                     "identity. The Hub must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=["--mi-user-assigned", "--mi-ua"],
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
                options_list=["--mi-system-assigned", "--mi-sa"],
                arg_type=get_three_state_flag(),
                help="Use the linked DPS resource's system-assigned identity as the inbound caller "
                     "identity. DPS must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=["--mi-user-assigned", "--mi-ua"],
                help="Resource ID of a user-assigned identity attached to the linked DPS resource.",
            )

    with self.argument_context("iot adr ns link dps add") as context:
        context.argument(
            "dps_resource_id",
            options_list=["--dps-resource-id", "--dps-id"],
            help="Azure resource ID of the Device Provisioning Service to link to this namespace.",
        )

    # Software Updates link arguments
    with self.argument_context("iot adr ns link su") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that owns the link.",
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--en", "--name", "-n"],
            help="Logical name of the Software Updates endpoint entry.",
        )

    for action in ("add", "update"):
        with self.argument_context(f"iot adr ns link su {action}") as context:
            context.argument(
                "mi_system_assigned",
                arg_group="Inbound Caller Identity",
                options_list=["--mi-system-assigned", "--mi-sa"],
                arg_type=get_three_state_flag(),
                help="Use the linked Update Instance's system-assigned "
                     "identity. The instance must have that identity enabled.",
            )
            context.argument(
                "mi_user_assigned",
                arg_group="Inbound Caller Identity",
                options_list=["--mi-user-assigned", "--mi-ua"],
                help="Resource ID of a user-assigned identity attached to the "
                     "linked Update Instance.",
            )

    with self.argument_context("iot adr ns link su add") as context:
        context.argument(
            "su_resource_id",
            options_list=["--su-resource-id", "--su-id"],
            help="Azure resource ID of the Update Instance to link.",
        )

    # Software Updates commands
    with self.argument_context("iot adr ns su instance") as context:
        context.argument(
            "update_instance_name",
            options_list=["--name", "-n"],
            help="Name of the Update Instance.",
        )

    with self.argument_context("iot adr ns su instance create") as context:
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
            validator=get_default_location_from_resource_group,
        )
        context.argument("tags", arg_type=tags_type)

    with self.argument_context("iot adr ns su instance update") as context:
        context.argument("tags", arg_type=tags_type)

    for cmd in [
        "iot adr ns su instance create",
        "iot adr ns su instance update",
    ]:
        with self.argument_context(cmd) as context:
            context.argument(
                "mi_system_assigned",
                options_list=["--mi-system-assigned", "--mi-sa"],
                arg_type=get_three_state_flag(),
                help="Include or remove the system-assigned managed identity in the "
                     "complete desired identity state.",
            )
            context.argument(
                "mi_user_assigned",
                options_list=["--mi-user-assigned", "--mi-ua"],
                nargs="+",
                help="One or more user-assigned managed identity resource IDs in the "
                     "complete desired identity state.",
            )

    for command in (
        "iot adr ns su software-update",
        "iot adr ns su device-class",
    ):
        with self.argument_context(command) as context:
            context.argument(
                "namespace_name",
                options_list=["--namespace", "--ns", "--name", "-n"],
                help="Name of the Device Registry namespace.",
            )

    with self.argument_context("iot adr ns su software-update") as context:
        context.argument(
            "update_name",
            options_list=["--update-name", "--un"],
            help="Update name.",
        )
        context.argument(
            "update_provider",
            options_list=["--update-provider", "--up"],
            help="Update provider.",
        )
        context.argument(
            "update_version",
            options_list=["--update-version", "--uv"],
            help="Update version.",
        )

    with self.argument_context("iot adr ns su software-update list") as context:
        context.argument(
            "search",
            options_list=["--search"],
            help="Request updates matching a free-text search expression.",
            arg_group="Filter",
        )
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Filter updates by supported service properties.",
            arg_group="Filter",
        )

    with self.argument_context("iot adr ns su software-update import") as context:
        context.argument(
            "url",
            options_list=["--url"],
            help="Read-accessible URL of the update import manifest.",
        )
        context.argument(
            "size",
            type=int,
            options_list=["--size"],
            help="Import manifest size in bytes. Calculated from --url when omitted.",
        )
        context.argument(
            "hashes",
            options_list=["--hashes"],
            nargs="+",
            help="Manifest hashes as key=value pairs. A sha256 value is required. "
            "Calculated from --url when omitted.",
        )
        context.argument(
            "friendly_name",
            options_list=["--friendly-name"],
            help="Friendly name associated with the imported update.",
        )
        context.argument(
            "files",
            options_list=["--file"],
            nargs="+",
            action="append",
            help="Update file metadata as filename=FILE_NAME url=READ_ACCESSIBLE_URL. "
            "--file can be used more than once.",
        )
        context.argument(
            "enable_scan",
            options_list=["--enable-scan"],
            arg_type=get_three_state_flag(),
            help="Request malware scanning for the imported update.",
        )

    with self.argument_context("iot adr ns su software-update stage") as context:
        context.argument(
            "manifest_paths",
            options_list=["--manifest-path"],
            action="append",
            help="Local import manifest path. Use --manifest-path more than once "
            "for a multi-reference update, with the root manifest first.",
        )
        context.argument(
            "storage_account",
            options_list=["--storage-account"],
            help="Storage account name or ARM resource ID used to stage artifacts.",
            arg_group="Storage",
        )
        context.argument(
            "storage_container_name",
            options_list=["--storage-container"],
            help="Blob container used to stage artifacts.",
            arg_group="Storage",
        )
        context.argument(
            "storage_account_subscription",
            options_list=["--storage-subscription"],
            help="Storage account subscription. Use when the storage account is "
            "in a different subscription and is specified by name.",
            arg_group="Storage",
        )
        context.argument(
            "storage_prefix",
            options_list=["--storage-prefix"],
            help="Blob name prefix. Defaults to 'deviceupdate'.",
            arg_group="Storage",
        )
        context.argument(
            "friendly_name",
            options_list=["--friendly-name"],
            help="Friendly name applied to the first, root manifest.",
        )
        context.argument(
            "enable_scan",
            options_list=["--enable-scan"],
            arg_type=get_three_state_flag(),
            help="Request malware scanning when --then-import is used.",
        )
        context.argument(
            "overwrite",
            options_list=["--overwrite"],
            arg_type=get_three_state_flag(),
            help="Replace staged blobs whose content differs from local artifacts.",
            arg_group="Storage",
        )
        context.argument(
            "then_import",
            options_list=["--then-import"],
            arg_type=get_three_state_flag(),
            help="Import all staged manifests in one request after uploading.",
        )
        context.argument(
            "sas_expiry_hours",
            options_list=["--sas-expiry-hours"],
            type=int,
            help="Read-only SAS lifetime used by --then-import. Defaults to 4 hours.",
            arg_group="Storage",
        )

    with self.argument_context("iot adr ns su software-update file") as context:
        context.argument(
            "update_file_id",
            options_list=["--update-file-id", "--ufid"],
            help="Update file identifier.",
        )

    with self.argument_context("iot adr ns su software-update calculate-hash") as context:
        context.argument(
            "file_paths",
            options_list=["--file-path", "-f"],
            action="append",
            help="Local file to hash. Use --file-path more than once for multiple files.",
        )
        context.argument(
            "hash_algo",
            options_list=["--hash-algo"],
            arg_type=get_enum_type(ADUValidHashAlgorithmType),
            type=str,
            help="Cryptographic hash algorithm.",
        )

    with self.argument_context("iot adr ns su software-update init") as context:
        context.argument(
            "description",
            options_list=["--description"],
            help="Description for the import manifest.",
        )
        context.argument(
            "deployable",
            options_list=["--is-deployable"],
            arg_type=get_three_state_flag(),
            help="Whether the update is independently deployable.",
        )
        context.argument(
            "compatibility",
            options_list=["--compat"],
            nargs="+",
            action="append",
            help="Compatible device properties as key=value pairs. "
            "--compat can be used more than once.",
        )
        context.argument(
            "steps",
            options_list=["--step"],
            nargs="+",
            action="append",
            help="Manifest step properties as key=value pairs. "
            "--step can be used more than once.",
        )
        context.argument(
            "files",
            options_list=["--file"],
            nargs="+",
            action="append",
            help="Manifest file properties as key=value pairs. "
            "--file can be used more than once.",
        )
        context.argument(
            "related_files",
            options_list=["--related-file"],
            nargs="+",
            action="append",
            help="Related-file properties as key=value pairs. "
            "Each entry is associated with the nearest --file.",
        )
        context.argument(
            "no_validation",
            options_list=["--no-validation"],
            arg_type=get_three_state_flag(),
            help="Disable client-side import-manifest schema validation.",
        )

    with self.argument_context("iot adr ns su device-class") as context:
        context.argument(
            "device_class_id",
            options_list=["--device-class-id", "--class-id", "--cid"],
            help="Device class identifier.",
        )

    # Bundled link add
    with self.argument_context("iot adr ns link add") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace that will own both new links.",
        )
        context.argument(
            "hub_endpoint_name",
            arg_group="Hub",
            options_list=["--hub-name", "--hn"],
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
            options_list=["--hub-mi-system-assigned", "--hub-mi-sa"],
            arg_type=get_three_state_flag(),
            help="Use the linked IoT Hub's system-assigned identity as its inbound caller identity.",
        )
        context.argument(
            "hub_mi_user_assigned",
            arg_group="Hub",
            options_list=["--hub-mi-user-assigned", "--hub-mi-ua"],
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
            options_list=["--dps-name", "--dn"],
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
            options_list=["--dps-mi-system-assigned", "--dps-mi-sa"],
            arg_type=get_three_state_flag(),
            help="Use the linked DPS resource's system-assigned identity as its inbound caller identity.",
        )
        context.argument(
            "dps_mi_user_assigned",
            arg_group="DPS",
            options_list=["--dps-mi-user-assigned", "--dps-mi-ua"],
            help="User-assigned identity resource ID attached to the linked DPS resource.",
        )

    # Group arguments
    with self.argument_context("iot adr ns group") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "group_name",
            options_list=["--group-name", "--gn", "--name", "-n"],
            help="Name of the group.",
        )

    with self.argument_context("iot adr ns group create") as context:
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
        )
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "group_type",
            options_list=["--group-type", "--gt"],
            arg_type=get_enum_type(GroupType),
            help="Type of the group. Only 'RegistryDevice' is supported in the current preview "
                 "API; this is immutable after creation.",
        )
        context.argument(
            "query_string",
            options_list=["--query-string", "--qs"],
            # TODO(queryFilter): the 2026-11-02-preview examples disagree on the filter dialect
            # ("where a == 'b'" vs "a = 'b'"). Passed through verbatim until the service team
            # confirms the canonical grammar; do not add client-side validation before then.
            help="Membership query filter used to determine which devices belong to the group. "
                 "Use '*' to include every device in the namespace. Required and immutable "
                 "after creation.",
        )
        context.argument(
            "display_name",
            options_list=["--display-name"],
            help="Human-readable display name for the group.",
        )
        context.argument(
            "description",
            options_list=["--description"],
            help="Human-readable description of the group.",
        )

    with self.argument_context("iot adr ns group update") as context:
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "display_name",
            options_list=["--display-name"],
            help="Human-readable display name for the group.",
        )
        context.argument(
            "description",
            options_list=["--description"],
            help="Human-readable description of the group.",
        )

    with self.argument_context("iot adr ns group list-members") as context:
        context.argument(
            "page_size",
            options_list=["--page-size"],
            type=int,
            help="Maximum members per request. The service maximum is 1000.",
        )
        context.argument(
            "skip_token",
            options_list=["--skip-token"],
            help="Opaque token from which to start listing members.",
        )

    # Job arguments
    with self.argument_context("iot adr ns job") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "job_name",
            options_list=["--job-name", "--jn", "--name", "-n"],
            help="Name of the job.",
        )

    with self.argument_context("iot adr ns job create") as context:
        context.argument(
            "location",
            arg_type=get_location_type(self.cli_ctx),
        )
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "job_type",
            options_list=["--type"],
            arg_type=get_enum_type(JobType),
            help="Job type: SoftwareUpdate targets a group; OnboardingUpdate targets all "
                 "compatible onboarding devices.",
        )
        context.argument(
            "target_group_name",
            options_list=["--target-group-name", "--tg"],
            help="Name of the target group. The group must live in the same namespace and resource group "
                 "as the job; cross-namespace targets are not supported in this preview release.",
        )
        context.argument(
            "update_provider",
            arg_group="Update",
            options_list=["--update-id-provider", "--update-provider", "--up"],
            help="Software Update updateId.provider (e.g. 'Contoso'). The update identity is a {provider, name, version} triple.",
        )
        context.argument(
            "update_name",
            arg_group="Update",
            options_list=["--update-id-name", "--update-name", "--un"],
            help=(
                "Software Update updateId.name (e.g. 'gateway-firmware'). "
                "This is the update identity's name, distinct from the job's --name."
            ),
        )
        context.argument(
            "update_version",
            arg_group="Update",
            options_list=["--update-id-version", "--update-version", "--uv"],
            help="Software Update updateId.version (e.g. '1.2.3').",
        )
        context.argument(
            "description",
            options_list=["--description"],
            help="Human-readable job description.",
        )
        context.argument(
            "display_name",
            options_list=["--display-name"],
            help="Human-readable display name for the job.",
        )

    with self.argument_context("iot adr ns job update") as context:
        context.argument("tags", arg_type=tags_type)

    # Job run arguments
    with self.argument_context("iot adr ns job run") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "job_name",
            options_list=["--job-name", "--jn"],
            help="Name of the parent job that owns this run.",
        )
        context.argument(
            "run_name",
            options_list=["--run-name", "--rn", "--name", "-n"],
            help="Name of the job run.",
        )

    with self.argument_context("iot adr ns job schedule") as context:
        context.argument(
            "run_name",
            options_list=["--run-name", "--rn"],
            help="Name of the job run to create. Defaults to a generated "
                 "UTC-timestamped name such as 'run-20251201080000'.",
        )
        context.argument(
            "scheduled_time",
            options_list=["--scheduled-time", "--st"],
            help="Optional ISO 8601 UTC timestamp at which the run should start "
                 "(e.g. '2025-12-01T08:00:00Z'). Omit to start immediately.",
        )

    with self.argument_context("iot adr ns job run list") as context:
        context.argument(
            "job_name",
            options_list=["--job-name", "--jn", "--name", "-n"],
            help="Optional parent job name. Omit to list runs across the namespace.",
        )
        context.argument(
            "status_filter",
            options_list=["--filter"],
            help="Status filter using 'eq' or 'in', for example: "
                 "status in ('Active', 'Scheduled').",
        )
        context.argument(
            "order_by",
            options_list=["--order-by", "--ob"],
            help="Sort expression for job runs, for example: \"status asc\" or "
                 "\"status desc\".",
        )

    with self.argument_context("iot adr ns job run results") as context:
        context.argument(
            "status_filter",
            options_list=["--filter"],
            help="One result status equality clause, for example: status eq 'Failed'.",
        )
        context.argument(
            "order_by",
            options_list=["--order-by", "--ob"],
            help="Sort results by status: \"status\", \"status asc\", or \"status desc\".",
        )

    with self.argument_context("iot adr ns report") as context:
        context.argument(
            "namespace_name",
            options_list=["--namespace", "--ns"],
            help="Name of the Device Registry namespace.",
        )
        context.argument(
            "report_type",
            options_list=["--report-type", "--type"],
            arg_type=get_enum_type(ReportType),
            help="Type of update compliance report.",
        )
        context.argument(
            "group_name",
            options_list=["--group-name", "--gn"],
            help="Group target. Required for group report types.",
        )
