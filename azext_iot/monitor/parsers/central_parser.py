# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re

from uamqp.message import Message

from azext_iot.central.models.template import Template
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
        central_device_provider,
        central_template_provider,
    ):
        super(CentralParser, self).__init__(
            message=message, common_parser_args=common_parser_args
        )
        self._central_device_provider = central_device_provider
        self._central_template_provider = central_template_provider
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

        template = self._get_template()

        if not isinstance(template, Template):
            return

        # if component name is not defined then data should be mapped to root/inherited interfaces
        if not self.component_name:
            self._validate_payload(
                payload=payload, template=template, is_component=False
            )
            return

        if not template.components:
            # template does not have any valid components
            details = strings.invalid_component_name(self.component_name, list())
            self._add_central_issue(severity=Severity.warning, details=details)
            return

        # if component name is defined check to see if its a valid name
        if self.component_name not in template.components:
            details = strings.invalid_component_name(
                self.component_name, list(template.components.keys())
            )
            self._add_central_issue(severity=Severity.warning, details=details)
            return

        # if component name is valid check to see if payload is valid
        self._validate_payload(payload=payload, template=template, is_component=True)

    def _get_template(self):
        try:
            device = self._central_device_provider.get_device(self.device_id)
            if hasattr(device, "instance_of"):
                template = self._central_template_provider.get_device_template(
                    device.instance_of
                )
            else:
                template = self._central_template_provider.get_device_template(
                    device.template
                )
            self._template_id = template.id
            return template
        except Exception as e:
            details = strings.device_template_not_found(e)
            self._add_central_issue(severity=Severity.error, details=details)

    # currently validates:
    # 1) primitive types match (e.g. boolean is indeed bool etc)
    # 2) names match (i.e. Humidity vs humidity etc)
    def _validate_payload(self, payload: dict, template: Template, is_component: bool):
        name_miss = []
        for telemetry_name, telemetry in payload.items():
            schema = template.get_schema(
                name=telemetry_name,
                identifier=self.component_name,
                is_component=is_component,
            )
            if not schema:
                name_miss.append(telemetry_name)
            else:
                self._process_telemetry(telemetry_name, schema, telemetry)

        if name_miss:
            if is_component:
                details = strings.invalid_field_name_component_mismatch_template(
                    name_miss, template.component_schema_names
                )
            else:
                details = strings.invalid_field_name_mismatch_template(
                    name_miss, template.schema_names,
                )
            self._add_central_issue(severity=Severity.warning, details=details)

    def _process_telemetry(self, telemetry_name: str, schema, telemetry):
        expected_type = extract_schema_type(schema)
        is_payload_valid = validate(schema, telemetry)
        if expected_type and not is_payload_valid:
            details = strings.invalid_primitive_schema_mismatch_template(
                telemetry_name, expected_type, telemetry
            )
            self._add_central_issue(severity=Severity.error, details=details)
