# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import datetime
import isodate
import time
from azext_iot.monitor.parsers import strings
from azext_iot.monitor.models.enum import Severity
from azext_iot.constants import (
    CENTRAL_ENDPOINT,
    DEVICETWIN_POLLING_INTERVAL_SEC,
    DEVICETWIN_MONITOR_TIME_SEC,
    PNP_INTERFACE_PREFIX,
)

from azext_iot.central.models.devicetwin import DeviceTwin, Property
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
    CentralDeviceTwinProvider,
)
from azext_iot.monitor.parsers.issue import IssueHandler


class PropertyMonitor:
    def __init__(
        self, cmd, app_id, device_id, central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        self._cmd = cmd
        self._app_id = app_id
        self._device_id = device_id
        self._central_dns_suffix = central_dns_suffix
        self._template = self._get_device_template()
        self._issues_handler = IssueHandler()

    def compare_properties(self, prev_prop: Property, prop: Property):
        if prev_prop.version == prop.version:
            return

        changes = {
            key: self._changed_props(prop.props[key], prop.metadata[key], key,)
            for key, val in prop.metadata.items()
            if self._is_relevant(key, val)
        }

        return changes

    def _is_relevant(self, key, val):
        if key in {"$lastUpdated", "$lastUpdatedVersion"}:
            return False

        updated_within = datetime.datetime.now() - datetime.timedelta(
            seconds=DEVICETWIN_MONITOR_TIME_SEC
        )

        last_updated = isodate.parse_datetime(val["$lastUpdated"])
        return last_updated.timestamp() >= updated_within.timestamp()

    def _changed_props(self, prop, metadata, property_name):
        # not an interface - whole thing is change log
        if not self._is_interface(property_name):
            return prop
        # iterate over property in the interface
        # if the property is not an exact match for what is present in the previous set of properties
        # track it as a change
        diff = {
            key: prop[key]
            for key, val in metadata.items()
            if self._is_relevant(key, val)
        }
        return diff

    def _validate_payload(self, changes, minimum_severity):
        for value in changes:
            self._validate_payload_against_interfaces(changes[value], value)

        issues = self._issues_handler.get_issues_with_minimum_severity(minimum_severity)

        for issue in issues:
            issue.log()

    def _validate_payload_against_interfaces(self, payload: dict, name):
        name_miss = []
        interface_name = name.replace(PNP_INTERFACE_PREFIX, "")
        if self._is_interface(interface_name):
            # if the payload is an interface then iterate thru the properties under the interface
            for property_name in payload.keys():
                schema = self._template.get_schema(
                    name=property_name, interface_name=interface_name
                )
                if not schema:
                    name_miss.append(property_name)
        else:
            # if the payload is a property then process the payload as a single unit.
            schema = self._template.get_schema(name=name, interface_name="")

            if not schema:
                name_miss.append(name)

            if self._validate_duplicate_properties(name):
                details = strings.duplicate_property_name(
                    name, list(self._template.interfaces.keys())
                )
                self._add_central_issue(severity=Severity.warning, details=details)

        if name_miss:
            details = strings.invalid_field_name_mismatch_template(
                name_miss, self._template.schema_names
            )
            self._add_central_issue(severity=Severity.warning, details=details)

    def _validate_duplicate_properties(self, property_name):
        value = (
            sum(
                property_name in idnumber
                for idnumber in self._template.interfaces.values()
            )
            > 1
        )
        return value

    def _add_central_issue(self, severity: Severity, details: str):
        self._issues_handler.add_central_issue(
            severity=severity,
            details=details,
            message=None,
            device_id=self._device_id,
            template_id=self._template.id,
        )

    def _is_interface(self, interface_name):
        # Remove PNP interface prefix to get the actual interface name
        interface_name = interface_name.replace(PNP_INTERFACE_PREFIX, "")
        return interface_name in self._template.interfaces

    def _get_device_template(self):

        central_device_provider = CentralDeviceProvider(self._cmd, self._app_id)
        device = central_device_provider.get_device(self._device_id)
        provider = CentralDeviceTemplateProvider(cmd=self._cmd, app_id=self._app_id)
        template = provider.get_device_template(
            device_template_id=device.instance_of,
            central_dns_suffix=self._central_dns_suffix,
        )
        return template

    def start_property_monitor(self,):
        prev_twin = None

        device_twin_provider = CentralDeviceTwinProvider(
            cmd=self._cmd, app_id=self._app_id, device_id=self._device_id
        )

        while True:

            raw_twin = device_twin_provider.get_device_twin(
                central_dns_suffix=self._central_dns_suffix
            )

            twin = DeviceTwin(raw_twin)
            if prev_twin:
                change_d = self.compare_properties(
                    prev_twin.desired_property, twin.desired_property,
                )
                change_r = self.compare_properties(
                    prev_twin.reported_property, twin.reported_property
                )

                if change_d:
                    print("Changes in desired properties:")
                    print("version :", twin.desired_property.version)
                    print(change_d)

                if change_r:
                    print("Changes in reported properties:")
                    print("version :", twin.reported_property.version)
                    print(change_r)
            time.sleep(DEVICETWIN_POLLING_INTERVAL_SEC)

            prev_twin = twin

    def start_validate_property_monitor(self, minimum_severity):
        prev_twin = None

        device_twin_provider = CentralDeviceTwinProvider(
            cmd=self._cmd, app_id=self._app_id, device_id=self._device_id
        )

        while True:

            raw_twin = device_twin_provider.get_device_twin(
                central_dns_suffix=self._central_dns_suffix
            )

            twin = DeviceTwin(raw_twin)
            if prev_twin:
                change_r = self.compare_properties(
                    prev_twin.reported_property, twin.reported_property
                )
                if change_r:
                    self._validate_payload(change_r, minimum_severity)

            time.sleep(DEVICETWIN_POLLING_INTERVAL_SEC)

            prev_twin = twin
