# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Optional
from azure.cli.core.azclierror import (
    AzureResponseError,
    ClientRequestError,
    CLIInternalError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from knack.log import get_logger
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azext_iot.central import services as central_services
from azext_iot.central.models.enum import DeviceStatus

from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import Device, DeviceCommand
from azext_iot.sdk.central.preview_2022_06_30.models import DeviceRelationship
from azext_iot.dps.services import global_service as dps_global_service


logger = get_logger(__name__)
MODEL = "Device"


class CentralDeviceProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().devices
        self.sdk_preview = self.get_sdk_preview().devices

        # Cache
        self._devices = {}
        self._device_templates = {}
        self._device_credentials = {}
        self._device_registration_info = {}

    """
    Device
    """
    def create(
        self,
        device_id: str,
        display_name: Optional[str] = None,
        template: Optional[str] = None,
        organizations: Optional[str] = None,
        simulated: Optional[bool] = False,
    ) -> Device:
        if not device_id:
            raise RequiredArgumentMissingError("Device id must be specified.")

        if device_id in self._devices:
            raise ClientRequestError("Device already exists.")

        payload = {
            "displayName": display_name,
            "simulated": simulated,
            "enabled": True,
        }

        if template:
            payload["template"] = template

        if organizations:
            payload["organizations"] = organizations.split(",")

        try:
            device = self.sdk.create(
                device_id=device_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not device:
            raise AzureResponseError(
                "Failed to create device with id: '{}'.".format(device_id)
            )

        # Update cache
        self._devices[device.id] = device

        return self._devices[device.id]

    def get(
        self,
        device_id: str,
    ) -> Device:
        # Try cache
        device = self._devices.get(device_id)

        if not device:
            try:
                device = self.sdk.get(device_id=device_id)
            except CloudError as e:
                handle_service_exception(e)

            # Update cache
            self._devices[device_id] = device

        if not device:
            raise ResourceNotFoundError(
                "No device found with id: '{}'.".format(device_id)
            )

        return self._devices[device_id]

    def list(
        self,
        filter: Optional[str] = None
    ) -> List[Device]:
        try:
            # We have to use Preview version sdk here
            # since GA version doesn't support this parameter
            devices = self.sdk_preview.list(filter=filter)
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._devices.update({device.id: device for device in devices})
        return devices

    def update(
        self,
        device_id: str,
        display_name: Optional[str] = None,
        template: Optional[str] = None,
        simulated: Optional[bool] = False,
        organizations: Optional[str] = None,
        enabled: Optional[bool] = False,
    ) -> Device:
        if not device_id:
            raise RequiredArgumentMissingError("Device id must be specified.")

        if device_id in self._devices:
            raise ClientRequestError("Device already exists.")

        current_device = self.sdk.get(device_id=device_id)

        if display_name is not None:
            current_device["displayName"] = display_name

        if template is not None:
            current_device["template"] = template

        if enabled is not None:
            current_device["enabled"] = enabled

        if simulated is not None:
            current_device["simulated"] = simulated

        if organizations is not None:
            current_device["organizations"] = organizations.split(",")

        try:
            device = self.sdk.update(
                device_id=device_id,
                body=current_device,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not device:
            raise ResourceNotFoundError(
                "No device found with id: '{}'.".format(device_id)
            )

        # Update cache
        self._devices[device.id] = device

        return self._devices[device.id]

    def delete(
        self,
        device_id: str,
    ):
        if not device_id:
            raise RequiredArgumentMissingError("Device id must be specified.")

        try:
            result = self.sdk.remove(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache, pop "miss" raises a KeyError if None is not provided
        self._devices.pop(device_id, None)
        self._device_credentials.pop(device_id, None)

        return result

    """
    Device relationship
    """
    def create_relationship(
        self,
        device_id: str,
        target_id: str,
        rel_id: str,
    ) -> DeviceRelationship:
        payload = {
            "id": rel_id,
            "source": device_id,
            "target": target_id
        }

        try:
            relationship = self.sdk_preview.create_relationship(
                device_id=device_id,
                relationship_id=rel_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not relationship:
            raise ResourceNotFoundError(
                "No relationship found with id: '{}'.".format(rel_id)
            )

        return relationship

    def list_relationships(
        self,
        device_id: str,
        rel_name: Optional[str] = None,
    ) -> List[DeviceRelationship]:
        try:
            relationships = self.sdk_preview.list_relationships(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

        if relationships is None:
            return []

        if rel_name:
            relationships = [rel for rel in relationships if rel.name == rel_name]

        return relationships

    def get_relationship(
        self,
        device_id: str,
        rel_id: str,
    ) -> DeviceRelationship:
        try:
            relationship = self.sdk_preview.get_relationship(
                device_id=device_id,
                relationship_id=rel_id,
            )
        except CloudError as e:
            handle_service_exception(e)

        return relationship

    def update_relationship(
        self,
        device_id: str,
        target_id: str,
        rel_id: str,
    ) -> DeviceRelationship:
        payload = {"target": target_id}

        try:
            relationship = self.sdk_preview.update_relationship(
                device_id=device_id,
                relationship_id=rel_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not relationship:
            raise ResourceNotFoundError(
                "No relationship found with id: '{}'.".format(rel_id)
            )

        return relationship

    def delete_relationship(
        self,
        device_id,
        rel_id,
    ):
        try:
            result = self.sdk_preview.remove_relationship(
                device_id=device_id,
                relationship_id=rel_id,
            )
        except CloudError as e:
            handle_service_exception(e)

        return result

    """
    Device credential
    """
    def get_device_credentials(
        self,
        device_id,
    ) -> dict:
        # Try cache
        credentials = self._device_credentials.get(device_id)

        if not credentials:
            try:
                credentials = self.sdk.get_credentials(device_id=device_id)
            except CloudError as e:
                handle_service_exception(e)

        if not credentials:
            raise CLIInternalError(
                "Could not find device credentials for device '{}'.".format(device_id)
            )

        # Update cache
        self._device_credentials[device_id] = credentials

        return credentials

    """
    Device registration
    """
    def get_device_registration_info(
        self,
        device_id,
        device_status: DeviceStatus,
    ) -> dict:
        # Try cache
        info = self._device_registration_info.get(device_id)

        if info:
            return info

        dps_state = {}

        try:
            device = self.get(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

        if device._device_status == DeviceStatus.provisioned:
            credentials = self.get_device_credentials(device_id=device_id)
            id_scope = credentials["idScope"]
            key = credentials["symmetricKey"]["primaryKey"]
            dps_state = dps_global_service.get_registration_state(
                id_scope=id_scope, key=key, device_id=device_id
            )

        dps_state = self._dps_populate_essential_info(dps_state, device._device_status)

        registration_info = {
            "device_status": self._parse_device_status(device=device),
            "display_name": device.display_name,
            "id": device.id,
            "simulated": device.simulated,
            "template": device.template,
        }

        info = {
            "@device_id": device_id,
            "dps_state": dps_state,
            "device_registration_info": registration_info,
        }
        self._device_registration_info[device_id] = info

        return info

    def get_device_registration_summary(self):
        try:
            devices = self.list()
        except CloudError as e:
            handle_service_exception(e)

        registration_summary = {status.value: 0 for status in DeviceStatus}

        for device in devices:
            registration_summary[
                self._parse_device_status(device=device),
            ] += 1

        return registration_summary

    """
    Command
    """
    def run_command(
        self,
        device_id: str,
        interface_id: str,
        component_name: str,
        module_name: str,
        command_name: str,
        payload: dict,
    ) -> DeviceCommand:
        if interface_id and self._is_interface_id_component(
            device_id=device_id,
            interface_id=interface_id,
        ):
            component_name = interface_id

        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.run_module_component_command(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                        command_name=command_name,
                        body=payload,
                    )
                else:
                    return self.sdk.run_module_command(
                        device_id=device_id,
                        module_name=module_name,
                        command_name=command_name,
                        body=payload,
                    )
            else:
                if component_name is not None:
                    return self.sdk.run_component_command(
                        device_id=device_id,
                        component_name=component_name,
                        command_name=command_name,
                        body=payload,
                    )
                else:
                    return self.sdk.run_command(
                        device_id=device_id,
                        command_name=command_name,
                        body=payload,
                    )       
        except CloudError as e:
            handle_service_exception(e)

    def get_command_history(
        self,
        device_id: str,
        interface_id: str,
        component_name: str,
        module_name: str,
        command_name: str,
    ) -> List[DeviceCommand]:
        if interface_id and self._is_interface_id_component(
            device_id=device_id,
            interface_id=interface_id,
        ):
            component_name = interface_id

        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.get_module_component_command_history(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                        command_name=command_name,
                    )
                else:
                    return self.sdk.get_module_command_history(
                        device_id=device_id,
                        module_name=module_name,
                        command_name=command_name,
                    )
            else:
                if component_name is not None:
                    return self.sdk.get_component_command_history(
                        device_id=device_id,
                        component_name=component_name,
                        command_name=command_name,
                    )
                else:
                    return self.sdk.get_command_history(
                        device_id=device_id,
                        command_name=command_name,
                    )   
        except CloudError as e:
            handle_service_exception(e)

    """
    Device modules
    """
    def list_device_modules(
        self,
        device_id: str,
    ) -> List[EdgeModule]:
        modules = central_services.device.list_device_modules(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id
        )

        if not modules:
            return []

        return modules

    def restart_device_module(
        self,
        device_id,
        module_id,
    ) -> List[EdgeModule]:

        status = central_services.device.restart_device_module(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id,
            module_id=module_id,
        )

        if not status or status != 200:
            raise ResourceNotFoundError(
                "No module found for device {} with id: '{}'.".format(
                    device_id, module_id
                )
            )

        return status

    """
    Device twin
    """
    def get_device_twin(
        self,
        device_id,
    ) -> DeviceTwin:
        twin = central_services.device.get_device_twin(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id,
        )

        if not twin:
            raise ResourceNotFoundError(
                "No twin found for device with id: '{}'.".format(device_id)
            )

        return twin

    """
    Failover
    """
    def run_manual_failover(
        self,
        device_id: str,
        ttl_minutes: Optional[int] = None,
    ):
        return central_services.device.run_manual_failover(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id,
            ttl_minutes=ttl_minutes,
        )

    """
    Failback
    """
    def run_manual_failback(
        self,
        device_id: str,
    ):
        return central_services.device.run_manual_failback(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id,
        )

    """
    Purge c2d message
    """
    def purge_c2d_messages(
        self,
        device_id: str,
    ):
        return central_services.device.purge_c2d_messages(
            cmd=self.cmd,
            app_id=self.app_id,
            device_id=device_id,
        )

    """
    Device attestation
    """
    def get_device_attestation(
        self,
        device_id: str,
    ):
        try:
            return self.sdk.get_attestation(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

    def delete_device_attestation(
        self,
        device_id: str,
    ):
        try:
            return self.sdk.remove(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

    def update_device_attestation(
        self,
        device_id: str,
        payload,
    ):
        try:
            return self.sdk.update(device_id=device_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def create_device_attestation(
        self,
        device_id: str,
        payload,
    ):
        try:
            return self.sdk.create(device_id=device_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    """
    Device properties
    """
    def list_modules(
        self,
        device_id: str,
    ):
        try:
            return self.sdk.list_modules(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

    def list_device_components(
        self,
        device_id: str,
        module_name: Optional[str] = None,
    ):
        try:
            if module_name is not None:
                return self.sdk.list_module_components(device_id=device_id, module_name=module_name)
            else:
                return self.sdk.list_components(device_id=device_id)
        except CloudError as e:
            handle_service_exception(e)

    def get_device_properties(
        self,
        device_id: str,
        component_name: Optional[str] = None,
        module_name: Optional[str] = None,
    ):
        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.get_module_component_properties(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                    )
                else:
                    return self.sdk.get_module_properties(
                        device_id=device_id,
                        module_name=module_name,
                    )
            else:
                if component_name is not None:
                    return self.sdk.get_component_properties(
                        device_id=device_id,
                        component_name=component_name,
                    )
                else:
                    return self.sdk.get_properties(
                        device_id=device_id,
                    )
        except CloudError as e:
            handle_service_exception(e)

    def replace_device_properties(
        self,
        device_id: str,
        payload: str,
        component_name: Optional[str] = None,
        module_name: Optional[str] = None,
    ):
        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.replace_module_component_properties(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                        body=payload,
                    )
                else:
                    return self.sdk.replace_module_properties(
                        device_id=device_id,
                        module_name=module_name,
                        body=payload,
                    )
            else:
                if component_name is not None:
                    return self.sdk.replace_component_properties(
                        device_id=device_id,
                        component_name=component_name,
                        body=payload,
                    )
                else:
                    return self.sdk.replace_properties(
                        device_id=device_id,
                        body=payload,
                    )
        except CloudError as e:
            handle_service_exception(e)

    def update_device_properties(
        self,
        device_id: str,
        payload: str,
        component_name: Optional[str] = None,
        module_name: Optional[str] = None,
    ):
        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.update_module_component_properties(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                        body=payload,
                    )
                else:
                    return self.sdk.update_module_properties(
                        device_id=device_id,
                        module_name=module_name,
                        body=payload,
                    )
            else:
                if component_name is not None:
                    return self.sdk.update_component_properties(
                        device_id=device_id,
                        component_name=component_name,
                        body=payload,
                    )
                else:
                    return self.sdk.update_properties(
                        device_id=device_id,
                        body=payload,
                    )
        except CloudError as e:
            handle_service_exception(e)

    def get_telemetry_value(
        self,
        device_id: str,
        component_name: str,
        module_name: str,
        telemetry_name: str,
    ):
        try:
            if module_name is not None:
                if component_name is not None:
                    return self.sdk.get_module_component_telemetry_value(
                        device_id=device_id,
                        module_name=module_name,
                        component_name=component_name,
                        telemetry_name=telemetry_name,
                    )
                else:
                    return self.sdk.get_module_telemetry_value(
                        device_id=device_id,
                        module_name=module_name,
                        telemetry_name=telemetry_name,
                    )
            else:
                if component_name is not None:
                    return self.sdk.get_component_telemetry_value(
                        device_id=device_id,
                        component_name=component_name,
                        telemetry_name=telemetry_name,
                    )
                else:
                    return self.sdk.get_telemetry_value(
                        device_id=device_id,
                        telemetry_name=telemetry_name,
                    )
        except CloudError as e:
            handle_service_exception(e)

    def _dps_populate_essential_info(self, dps_info, device_status: DeviceStatus):
        error = {
            DeviceStatus.provisioned: "None.",
            DeviceStatus.registered: "Device is not yet provisioned.",
            DeviceStatus.blocked: "Device is blocked from connecting to IoT Central application."
            " Unblock the device in IoT Central and retry. Learn more: https://aka.ms/iotcentral-docs-dps-SAS",
            DeviceStatus.unassociated: "Device does not have a valid template associated with it.",
        }

        filtered_dps_info = {
            "status": dps_info.get("status"),
            "error": error.get(device_status),
        }
        return filtered_dps_info

    def _is_interface_id_component(
        self,
        device_id: str,
        interface_id: str,
    ) -> bool:

        current_device = self.get(device_id)

        template = self.get_sdk().device_templates.get(
            device_template_id=current_device.template,
        )

        if interface_id in template.components:
            return True

        for module in template.modules:
            if interface_id in module.components:
                return True

        return False

    def _parse_device_status(self, device: Device) -> DeviceStatus:
        if not device.approved:
            return DeviceStatus.blocked

        if not device.instance_of:
            return DeviceStatus.unassociated

        if not device.provisioned:
            return DeviceStatus.registered
