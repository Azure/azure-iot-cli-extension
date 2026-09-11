# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError as CLIResourceNotFoundError,
)
from azure.core.exceptions import ResourceNotFoundError
from knack.log import get_logger

from azext_iot.adr.common import (
    ADU_ATTRIBUTE_NAME,
    DeviceAttributeReportedType,
    RegistryDeviceAuthenticationType,
    RegistryDeviceEnablementState,
    is_adu_attribute_alias,
)
from azext_iot.adr.providers.base import ADRProvider, parse_json_object

logger = get_logger(__name__)


def _validate_enablement_state(enablement_state: Optional[str]) -> None:
    if enablement_state is not None and enablement_state not in {
        state.value for state in RegistryDeviceEnablementState
    }:
        raise InvalidArgumentValueError(
            "--enablement-state must be 'Enabled' or 'Disabled'."
        )


class RegistryDeviceProvider(ADRProvider):
    def __init__(self, cmd):
        super(RegistryDeviceProvider, self).__init__(cmd)

    def create(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        enablement_state: str = RegistryDeviceEnablementState.enabled.value,
        external_device_id: Optional[str] = None,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        hardware_revision: Optional[str] = None,
        software_revision: Optional[str] = None,
        no_wait: bool = False,
    ):
        _validate_enablement_state(enablement_state)
        properties = {"enablementState": enablement_state}
        optional_properties = (
            ("externalDeviceId", external_device_id),
            ("manufacturer", manufacturer),
            ("model", model),
            ("hardwareRevision", hardware_revision),
            ("softwareRevision", software_revision),
        )
        for property_name, value in optional_properties:
            if value is not None:
                properties[property_name] = value

        resource = {
            "location": self._resolve_location(
                namespace_name, resource_group_name, location
            ),
            "properties": properties,
        }
        if tags is not None:
            resource["tags"] = tags

        poller = self.client.registry_devices.begin_create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            resource=resource,
        )
        return self._wait(
            poller,
            f"Creating registry device '{registry_device_name}' in namespace {namespace_name}...",
            no_wait=no_wait,
        )

    def show(
        self,
        registry_device_name: Optional[str] = None,
        namespace_name: Optional[str] = None,
        resource_group_name: Optional[str] = None,
        external_device_id: Optional[str] = None,
    ):
        if registry_device_name and external_device_id:
            raise MutuallyExclusiveArgumentError(
                "Specify exactly one of --name or --external-device-id."
            )
        if not registry_device_name and not external_device_id:
            raise RequiredArgumentMissingError(
                "Specify exactly one of --name or --external-device-id."
            )
        if external_device_id:
            return self._show_by_external_device_id(
                external_device_id=external_device_id,
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
            )
        return self.client.registry_devices.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
        )

    def _show_by_external_device_id(
        self,
        external_device_id: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        """Resolve an external ID over the SDK's pageable namespace listing.

        The selected 2026-11-02-preview contract does not expose a server-side
        filter parameter for RegistryDevices_ListByNamespace. Iterating the
        ItemPaged result still follows every nextLink and prevents a match on a
        later page from being missed.
        """
        matches = []
        for device in self.client.registry_devices.list_by_namespace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
        ):
            properties = (device or {}).get("properties") or {}
            if properties.get("externalDeviceId") == external_device_id:
                matches.append(device)

        if not matches:
            raise CLIResourceNotFoundError(
                f"No Registry Device with external device ID "
                f"'{external_device_id}' was found in namespace "
                f"'{namespace_name}'. If registration just completed, use "
                "'az iot adr ns registry-device wait --external-device-id ...' "
                "to allow for materialization."
            )
        if len(matches) > 1:
            names = ", ".join(
                sorted(str(device.get("name") or "<unnamed>") for device in matches)
            )
            raise AzureResponseError(
                f"External device ID '{external_device_id}' matched multiple "
                f"Registry Devices in namespace '{namespace_name}': {names}. "
                "Use --name to select one resource."
            )
        return matches[0]

    def list(self, namespace_name: str, resource_group_name: str):
        return list(
            self.client.registry_devices.list_by_namespace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
        )

    def update(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        enablement_state: Optional[str] = None,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        hardware_revision: Optional[str] = None,
        software_revision: Optional[str] = None,
        no_wait: bool = False,
    ):
        _validate_enablement_state(enablement_state)
        inner_properties = {}
        optional_properties = (
            ("enablementState", enablement_state),
            ("manufacturer", manufacturer),
            ("model", model),
            ("hardwareRevision", hardware_revision),
            ("softwareRevision", software_revision),
        )
        for property_name, value in optional_properties:
            if value is not None:
                inner_properties[property_name] = value

        properties = {}
        if inner_properties:
            properties["properties"] = inner_properties
        if tags is not None:
            properties["tags"] = tags
        if not properties:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --enablement-state, --manufacturer, --model, "
                "--hardware-revision, --software-revision, or --tags."
            )

        poller = self.client.registry_devices.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            properties=properties,
        )
        return self._wait(
            poller,
            f"Updating registry device '{registry_device_name}' in namespace {namespace_name}...",
            no_wait=no_wait,
        )

    def delete(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
        no_wait: bool = False,
    ):
        poller = self.client.registry_devices.begin_delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
        )
        return self._wait(
            poller,
            f"Deleting registry device '{registry_device_name}' from namespace {namespace_name}...",
            no_wait=no_wait,
        )

    def auth_list(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return list(
            self.client.registry_device_authentication_profiles.list_by_device(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
            )
        )

    def auth_show(
        self,
        authentication_profile_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return self.client.registry_device_authentication_profiles.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            authentication_profile_name=authentication_profile_name,
        )

    def auth_show_keys(
        self,
        authentication_profile_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        profile = self.auth_show(
            authentication_profile_name=authentication_profile_name,
            registry_device_name=registry_device_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )
        authentication_type = ((profile or {}).get("properties") or {}).get(
            "authenticationType"
        )
        if authentication_type != RegistryDeviceAuthenticationType.symmetric_key.value:
            raise InvalidArgumentValueError(
                "Authentication keys can only be retrieved for a profile with "
                "authentication type 'SymmetricKey'."
            )

        keys = self.client.registry_device_authentication_profiles.list_keys(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            authentication_profile_name=authentication_profile_name,
            logging_enable=False,
        )
        logger.warning(
            "The returned symmetric keys are secrets. Store them securely and do not share them."
        )
        return keys

    def auth_revoke_certs(
        self,
        authentication_profile_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
        no_wait: bool = False,
    ):
        profile = self.auth_show(
            authentication_profile_name=authentication_profile_name,
            registry_device_name=registry_device_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )
        authentication_type = ((profile or {}).get("properties") or {}).get(
            "authenticationType"
        )
        if (
            authentication_type
            != RegistryDeviceAuthenticationType.certificate_authority_signed_x509_certificate.value
        ):
            raise InvalidArgumentValueError(
                "Certificates can only be revoked for a Microsoft-managed X.509 profile "
                "with authentication type "
                "'CertificateAuthoritySignedX509Certificate'."
            )

        poller = (
            self.client.registry_device_authentication_profiles.begin_revoke_certificates(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
                authentication_profile_name=authentication_profile_name,
            )
        )
        return self._wait(
            poller,
            f"Revoking certificates for authentication profile '{authentication_profile_name}'...",
            no_wait=no_wait,
        )

    def attribute_list(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return list(
            self.client.registry_device_attributes.list_by_device(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
            )
        )

    def attribute_show(
        self,
        attribute_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        try:
            return self.client.registry_device_attributes.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
                attribute_name=attribute_name,
            )
        except ResourceNotFoundError:
            # `software-update` is accepted as a friendlier spelling of the
            # ADU-reported attribute. The literal name is always tried first so
            # a customer-authored attribute of the same name still wins.
            if not is_adu_attribute_alias(attribute_name):
                raise
            logger.warning(
                "No attribute named '%s' exists on Registry Device '%s'. Showing the "
                "Azure Device Update attribute '%s' instead; '%s' is its canonical "
                "resource name and the only name accepted by other commands.",
                attribute_name,
                registry_device_name,
                ADU_ATTRIBUTE_NAME,
                ADU_ATTRIBUTE_NAME,
            )
            return self.client.registry_device_attributes.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
                attribute_name=ADU_ATTRIBUTE_NAME,
            )

    def attribute_create(
        self,
        attribute_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
        reported_by: str = DeviceAttributeReportedType.user.value,
        schema: Optional[str] = None,
        properties: Optional[str] = None,
    ):
        if reported_by != DeviceAttributeReportedType.user.value:
            if reported_by != DeviceAttributeReportedType.adu.value:
                raise InvalidArgumentValueError(
                    "The hidden --reported-by compatibility option accepts "
                    "only 'User'. Omit it for customer-authored attributes."
                )
            raise InvalidArgumentValueError(
                "'Microsoft.DeviceUpdate' is service-owned attribute provenance "
                "and cannot be authored with this command. Customer-authored "
                "attributes always use reportedBy='User'."
            )

        attribute_properties: Dict[str, object] = {}
        if properties is not None:
            attribute_properties.update(
                parse_json_object(properties, "--properties")
            )
        supplied_provenance = attribute_properties.get("reportedBy")
        if (
            supplied_provenance is not None
            and supplied_provenance != DeviceAttributeReportedType.user.value
        ):
            if supplied_provenance != DeviceAttributeReportedType.adu.value:
                raise InvalidArgumentValueError(
                    "The --properties reportedBy value must be 'User'. Remove "
                    "reportedBy to use the customer-authored default."
                )
            raise InvalidArgumentValueError(
                "The --properties value cannot set service-owned "
                "reportedBy='Microsoft.DeviceUpdate'. Remove reportedBy or set "
                "it to 'User'."
            )

        attribute_properties["reportedBy"] = DeviceAttributeReportedType.user.value
        if schema is not None:
            attribute_properties["schema"] = schema

        return self.client.registry_device_attributes.create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            attribute_name=attribute_name,
            resource={"properties": attribute_properties},
        )

    def attribute_delete(
        self,
        attribute_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return self.client.registry_device_attributes.delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            attribute_name=attribute_name,
        )

    def capability_list(
        self,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return list(
            self.client.registry_device_capabilities.list_by_device(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                registry_device_name=registry_device_name,
            )
        )

    def capability_show(
        self,
        capability_name: str,
        registry_device_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return self.client.registry_device_capabilities.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            registry_device_name=registry_device_name,
            capability_name=capability_name,
        )
