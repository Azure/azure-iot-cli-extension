# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re

from uamqp.message import Message

from azext_iot.common.utility import ISO8601Validator
from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.monitor.parsers import strings
from azext_iot.monitor.models.arguments import CommonParserArguments
from azext_iot.monitor.models.enum import Severity
from azext_iot.monitor.parsers.common_parser import CommonParser

ios_validator = ISO8601Validator()


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
        # self._perform_dynamic_validations(payload=payload)

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

        template_schemas = self._extract_template_schemas_from_template(
            template=template
        )

        # _extract_template_schemas_from_template should log error if there was an issue
        if not isinstance(template_schemas, dict):
            return

        self._validate_payload_against_schema(
            payload=payload, template_schemas=template_schemas,
        )

    def _get_device_template(self):
        try:
            return self._central_device_provider.get_device_template_by_device_id(
                self.device_id
            )
        except Exception as e:
            details = strings.device_template_not_found(e)
            self._add_central_issue(severity=Severity.error, details=details)

    def _extract_template_schemas_from_template(self, template: dict):
        try:
            self._template_id = template.get("id")
            schemas = []
            dcm = template["capabilityModel"]
            implements = dcm["implements"]
            for implementation in implements:
                contents = implementation["schema"]["contents"]
                schemas.extend(contents)
            return {schema["name"]: schema for schema in schemas}
        except Exception:
            details = strings.invalid_template_extract_schema_failed(template)
            self._add_central_issue(severity=Severity.error, details=details)

    # currently validates:
    # 1) primitive types match (e.g. boolean is indeed bool etc)
    # 2) names match (i.e. Humidity vs humidity etc)
    def _validate_payload_against_schema(
        self, payload: dict, template_schemas: dict,
    ):
        template_schema_names = template_schemas.keys()
        name_miss = []
        for name, value in payload.items():
            schema = template_schemas.get(name)
            if not schema:
                name_miss.append(name)

            is_dict = isinstance(schema, dict)
            if is_dict and not self._validate_types_match(value, schema):
                expected_type = str(schema.get("schema"))
                details = strings.invalid_primitive_schema_mismatch_template(
                    name, expected_type, value
                )
                self._add_central_issue(severity=Severity.error, details=details)

        if name_miss:
            details = strings.invalid_field_name_mismatch_template(
                name_miss, list(template_schema_names)
            )
            self._add_central_issue(severity=Severity.warning, details=details)

    def _validate_types_match(self, value, schema: dict) -> bool:
        # suppress error if there is no "schema" in schema
        # means something else went wrong
        schema_type = schema.get("schema")
        if not schema_type:
            return True

        if schema_type == "boolean":
            return isinstance(value, bool)
        elif schema_type == "double":
            return isinstance(value, (float, int))
        elif schema_type == "float":
            return isinstance(value, (float, int))
        elif schema_type == "integer":
            return isinstance(value, int)
        elif schema_type == "long":
            return isinstance(value, (float, int))
        elif schema_type == "string":
            return isinstance(value, str)
        elif schema_type == "time":
            return ios_validator.is_iso8601_time(value)
        elif schema_type == "date":
            return ios_validator.is_iso8601_date(value)
        elif schema_type == "dateTime":
            return ios_validator.is_iso8601_datetime(value)
        elif schema_type == "duration":
            return ios_validator.is_iso8601_duration(value)

        # if the schema_type is not found above, suppress error
        return True
