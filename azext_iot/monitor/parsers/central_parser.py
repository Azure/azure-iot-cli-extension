# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re

from uamqp.message import Message

from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.monitor.parsers import strings
from azext_iot.monitor.central_validator import validate, extract_schema_type
from azext_iot.monitor.models.arguments import CommonParserArguments
from azext_iot.monitor.models.enum import Severity
from azext_iot.monitor.parsers.common_parser import CommonParser


class CentralParser(CommonParser):
    def __init__(
        self,
        message: Message,
        common_parser_args: CommonParserArguments,
        central_device_provider: CentralDeviceProvider,
    ):
        super(CentralParser, self).__init__(
            message=message, common_parser_args=common_parser_args
        )
        self._central_device_provider = central_device_provider
        self._template_id = None

    def _add_central_issue(self, severity: Severity, details: str):
        self.issues_handler.add_central_issue(
            severity=severity,
            details=details,
            message=self._message,
            device_id=self.device_id,
            template_id=self._template_id,
        )

    def parse_message(self) -> dict:
        parsed_message = super(CentralParser, self).parse_message()

        payload = parsed_message["event"]["payload"]

        self._perform_static_validations(payload=payload)

        # disable dynamic validations until Microservices work is figured out
        self._perform_dynamic_validations(payload=payload)

        return parsed_message

    # Static validations should only need information present in the payload
    # i.e. there should be no need for network calls
    def _perform_static_validations(self, payload: dict):
        # if its not a dictionary, something else went wrong with parsing
        if not isinstance(payload, dict):
            return

        self._validate_field_names(payload=payload)

    def _validate_field_names(self, payload: dict):
        # source:
        # https://github.com/Azure/IoTPlugandPlay/tree/master/DTDL
        regex = "^[a-zA-Z_][a-zA-Z0-9_]*$"

        # if a field name does not match the above regex, it is an invalid field name
        invalid_field_names = [
            field_name
            for field_name in payload.keys()
            if not re.search(regex, field_name)
        ]
        if invalid_field_names:
            details = strings.invalid_field_name(invalid_field_names)
            self._add_issue(severity=Severity.error, details=details)

    # Dynamic validations should need data external to the payload
    # e.g. device template
    def _perform_dynamic_validations(self, payload: dict):
        # if the payload is not a dictionary some other parsing error occurred
        if not isinstance(payload, dict):
            return

        template = self._get_device_template()

        # _get_device_template should log error if there was an issue
        if not template:
            return

        interfaces = self._extract_interfaces(template=template)

        # _extract_interfaces should log error if there was an issue
        if not isinstance(interfaces, dict):
            return

        self._validate_payload_against_interfaces(
            payload=payload, interfaces=interfaces,
        )

    def _get_device_template(self):
        try:
            return self._central_device_provider.get_device_template_by_device_id(
                self.device_id
            )
        except Exception as e:
            details = strings.device_template_not_found(e)
            self._add_central_issue(severity=Severity.error, details=details)

    def _extract_interfaces(self, template: dict):
        try:
            self._template_id = template.get("id")
            interfaces = {}
            dcm = template["capabilityModel"]
            interfaces = dcm["implements"]
            result = {
                interface["name"]: self._extract_schemas(interface)
                for interface in interfaces
            }
            return result
        except Exception:
            details = strings.invalid_template_extract_schema_failed(template)
            self._add_central_issue(severity=Severity.error, details=details)

    def _extract_schemas(self, interface: dict):
        return {schema["name"]: schema for schema in interface["schema"]["contents"]}

    # currently validates:
    # 1) primitive types match (e.g. boolean is indeed bool etc)
    # 2) names match (i.e. Humidity vs humidity etc)
    def _validate_payload_against_interfaces(
        self, payload: dict, interfaces: dict,
    ):
        template_schema_names = {
            interface_name: [schema_name for schema_name in interface_schemas]
            for interface_name, interface_schemas in interfaces.items()
        }
        name_miss = []
        for telemetry_name, telemetry in payload.items():
            schema = self._find_schema(telemetry_name, interfaces)
            if not schema:
                name_miss.append(telemetry_name)
            else:
                self._process_telemetry(telemetry_name, schema, telemetry)

        if name_miss:
            details = strings.invalid_field_name_mismatch_template(
                name_miss, template_schema_names
            )
            self._add_central_issue(severity=Severity.warning, details=details)

    def _find_schema(self, telemetry_name: str, interfaces: dict):
        interface = interfaces.get(self.interface_name)

        # pnp device
        if self.interface_name:
            # pnp device is sending data to an unrecognized interface
            if not isinstance(interface, dict):
                details = strings.invalid_interface_name(
                    self.interface_name, list(interfaces.keys())
                )
                self._add_central_issue(severity=Severity.warning, details=details)
                return None

            # return schema. If none is found, caller should handle adding a name_miss scenario
            return interface.get(telemetry_name)

        # non-pnp device, find first occurrence of telemetry_name
        # no detection for multiple definitions under other interfaces
        for interface in interfaces.values():
            schema = interface.get(telemetry_name)
            if schema:
                return schema

        # no interface was found if we reach this point
        # caller should add name_miss
        return None

    def _process_telemetry(self, telemetry_name, schema, telemetry):
        expected_type = extract_schema_type(schema)
        is_payload_valid = validate(schema, telemetry)
        if expected_type and not is_payload_valid:
            details = strings.invalid_primitive_schema_mismatch_template(
                telemetry_name, expected_type, telemetry
            )
            self._add_central_issue(severity=Severity.error, details=details)
