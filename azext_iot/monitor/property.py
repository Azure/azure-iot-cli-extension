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
    PNP_DTDLV2_COMPONENT_MARKER,
)

from azext_iot.central.models.devicetwin import DeviceTwin, Property

from azext_iot.central.providers import CentralDeviceTwinProvider
from azext_iot.central.providers.v1 import (
    CentralDeviceProviderV1,
    CentralDeviceTemplateProviderV1,
)
from azext_iot.monitor.parsers.issue import IssueHandler


class PropertyMonitor:
    def __init__(
        self,
        cmd,
        app_id: str,
        device_id: str,
        token: str,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        self._cmd = cmd
        self._app_id = app_id
        self._device_id = device_id
        self._token = token
        self._central_dns_suffix = central_dns_suffix
        self._device_twin_provider = CentralDeviceTwinProvider(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            device_id=self._device_id,
        )
        self._central_device_provider = CentralDeviceProviderV1(
            cmd=self._cmd, app_id=self._app_id, token=self._token
        )
        self._central_template_provider = CentralDeviceTemplateProviderV1(
            cmd=self._cmd, app_id=self._app_id, token=self._token
        )
        self._template = self._get_device_template()

    def _compare_properties(self, prev_prop: Property, prop: Property):
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
        if not self._is_component(prop):
            return prop

        # iterate over properties in the component
        # if the property is not an exact match for what is present in the previous set of properties
        # track it as a change
        diff = {
            key: prop[key]
            for key, val in metadata.items()
            if self._is_relevant(key, val)
        }
        return diff

    def _is_component(self, prop):
        return type(prop) == dict and prop.get(PNP_DTDLV2_COMPONENT_MARKER) == "c"

    def _validate_payload(self, changes, minimum_severity):
        for value in changes:
            issues = self._validate_payload_against_entities(
                changes[value], value, minimum_severity
            )
            for issue in issues:
                issue.log()

    def _validate_payload_against_entities(self, payload: dict, name, minimum_severity):
        name_miss = []
        issues_handler = IssueHandler()

        if not self._is_component(payload):
            # update is not part of a component check under interfaces
            schema = self._template.get_schema(name=name)
            if not schema:
                name_miss.append(name)
                details = strings.invalid_field_name_mismatch_template(
                    name_miss, self._template.schema_names
                )

            interfaces_with_specified_property = self._template._get_interface_list_property(
                name
            )

            if len(interfaces_with_specified_property) > 1:
                details = strings.duplicate_property_name(
                    name, interfaces_with_specified_property
                )
                issues_handler.add_central_issue(
                    severity=Severity.warning,
                    details=details,
                    message=None,
                    device_id=self._device_id,
                    template_id=self._template.id,
                )
        else:
            # Property update is part of a component perform additional validations under component list.
            component_property_updates = [
                property_name
                for property_name in payload
                if property_name != PNP_DTDLV2_COMPONENT_MARKER
            ]
            for property_name in component_property_updates:
                schema = self._template.get_schema(
                    name=property_name, identifier=name, is_component=True
                )
                if not schema:
                    name_miss.append(property_name)
                    details = strings.invalid_field_name_component_mismatch_template(
                        name_miss, self._template.component_schema_names
                    )

        if name_miss:
            issues_handler.add_central_issue(
                severity=Severity.warning,
                details=details,
                message=None,
                device_id=self._device_id,
                template_id=self._template.id,
            )

        return issues_handler.get_issues_with_minimum_severity(minimum_severity)

    def _get_device_template(self):
        device = self._central_device_provider.get_device(self._device_id)
        template = self._central_template_provider.get_device_template(
            device_template_id=device.template,
            central_dns_suffix=self._central_dns_suffix,
        )
        return template

    def start_property_monitor(self,):
        prev_twin = None

        while True:
            raw_twin = self._device_twin_provider.get_device_twin(
                central_dns_suffix=self._central_dns_suffix
            )

            twin = DeviceTwin(raw_twin)
            if prev_twin:
                change_d = self._compare_properties(
                    prev_twin.desired_property, twin.desired_property,
                )
                change_r = self._compare_properties(
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

        while True:

            raw_twin = self._device_twin_provider.get_device_twin(
                central_dns_suffix=self._central_dns_suffix
            )

            twin = DeviceTwin(raw_twin)
            if prev_twin:
                change_r = self._compare_properties(
                    prev_twin.reported_property, twin.reported_property
                )
                if change_r:
                    self._validate_payload(change_r, minimum_severity)

            time.sleep(DEVICETWIN_POLLING_INTERVAL_SEC)

            prev_twin = twin
