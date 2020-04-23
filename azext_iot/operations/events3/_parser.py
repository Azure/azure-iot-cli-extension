# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import random
import re

from knack.log import get_logger
from uamqp.message import Message

from azext_iot.common.utility import parse_entity, unicode_binary_map, ISO8601Validator
from azext_iot.central.providers import CentralDeviceProvider

SUPPORTED_ENCODINGS = ["utf-8"]
DEVICE_ID_IDENTIFIER = b"iothub-connection-device-id"
INTERFACE_NAME_IDENTIFIER = b"iothub-interface-name"
random.seed(0)

ios_validator = ISO8601Validator()


class Event3Parser(object):
    _logger = get_logger(__name__)

    def __init__(self, logger=None):
        self._reset_issues()
        if logger:
            self._logger = logger

    def parse_message(
        self,
        message: Message,
        pnp_context: bool,
        interface_name: str,
        properties: dict,
        content_type_hint: str,
        simulate_errors: bool,
        central_device_provider: CentralDeviceProvider,
    ) -> dict:
        self._reset_issues()
        create_encoding_error = False
        create_custom_header_warning = False
        create_payload_error = False
        create_payload_name_error = False

        if not properties:
            properties = {}  # guard against None being passed in

        i = random.randint(1, 4)
        if simulate_errors and i == 1:
            create_encoding_error = True
        if simulate_errors and i == 2:
            create_custom_header_warning = True
        if simulate_errors and i == 3:
            create_payload_error = True
        if simulate_errors and i == 4:
            create_payload_name_error = True

        system_properties = self._parse_system_properties(message)

        self._parse_content_encoding(message, system_properties, create_encoding_error)

        event = {}

        origin_device_id = self.parse_device_id(message)
        event["origin"] = origin_device_id

        content_type = self._parse_content_type(
            content_type_hint,
            system_properties,
            origin_device_id,
            create_custom_header_warning,
        )

        if pnp_context:
            message_interface_name = self._parse_interface_name(
                message, pnp_context, interface_name, origin_device_id
            )

            event["interface"] = message_interface_name

        if properties:
            event["properties"] = {}

        if "anno" in properties or "all" in properties:
            annotations = self._parse_annotations(message)
            event["annotations"] = annotations

        if system_properties and ("sys" in properties or "all" in properties):
            event["properties"]["system"] = system_properties

        if "app" in properties or "all" in properties:
            application_properties = self._parse_application_properties(message)
            event["properties"]["application"] = application_properties

        payload = self._parse_payload(
            message, origin_device_id, content_type, create_payload_error
        )

        self._perform_static_validations(
            origin_device_id=origin_device_id, payload=payload
        )

        self._perform_dynamic_validations(
            origin_device_id=origin_device_id,
            payload=payload,
            central_device_provider=central_device_provider,
            create_payload_name_error=create_payload_name_error,
        )

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def parse_device_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            self._errors.append("Device id not found in message: {}".format(message))

    def write_logs(self) -> None:
        for error in self._errors:
            self._logger.error("[Error] " + error)

        for warning in self._warnings:
            self._logger.warn("[Warning] " + warning)

        for info in self._info:
            self._logger.info("[Info] " + info)

    def _reset_issues(self) -> None:
        self._info = []
        self._warnings = []
        self._errors = []

    def _parse_interface_name(
        self, message: Message, pnp_context, interface_name, origin_device_id
    ) -> str:
        message_interface_name = ""

        try:
            message_interface_name = str(
                message.annotations.get(INTERFACE_NAME_IDENTIFIER), "utf8"
            )
        except Exception:
            self._errors.append(
                "Unable to parse interface_name given a pnp_device. {}. "
                "message: {}".format(origin_device_id, message)
            )

        if interface_name != message_interface_name:
            self._errors.append(
                "Inteface name mismatch. {}. "
                "Expected: {}, Actual: {}".format(
                    origin_device_id, interface_name, message_interface_name
                )
            )

        return message_interface_name

    def _parse_system_properties(self, message: Message):
        try:
            return unicode_binary_map(parse_entity(message.properties, True))
        except Exception:
            self._errors.append(
                "Failed to parse system_properties for message {message}.".format(
                    message
                )
            )
            return {}

    def _parse_content_encoding(
        self, message: Message, system_properties, create_encoding_error
    ) -> str:
        content_encoding = ""

        if "content_encoding" in system_properties:
            content_encoding = system_properties["content_encoding"]

        if not content_encoding:
            self._errors.append("No encoding found for message: {}".format(message))
            return None

        if create_encoding_error:
            content_encoding = "Some Random Encoding"

        if "utf-8" not in content_encoding.lower():
            self._errors.append(
                "Unsupported encoding detected: '{}'. "
                "The currently supported encodings are: {}. "
                "System_properties: {}.".format(
                    content_encoding, SUPPORTED_ENCODINGS, system_properties
                )
            )
            return None

        return content_encoding

    def _parse_content_type(
        self,
        content_type_hint,
        system_properties,
        origin_device_id,
        create_custom_header_warning,
    ) -> str:
        content_type = ""
        if content_type_hint:
            content_type = content_type_hint
        elif "content_type" in system_properties:
            content_type = system_properties["content_type"]

        if create_custom_header_warning:
            content_type = "Some Random Custom Header"

        if not content_type:
            self._warnings.append(
                "Content type not found in system_properties. "
                "System_properties: {}".format(system_properties)
            )

        return content_type

    def _parse_annotations(self, message: Message):
        try:
            return unicode_binary_map(message.annotations)
        except Exception:
            self._warnings.append(
                "Unable to decode message.annotations: {}".format(message.annotations)
            )

    def _parse_application_properties(self, message: Message):
        try:
            return unicode_binary_map(message.application_properties)
        except Exception:
            self._warnings.append(
                "Unable to decode message.application_properties: {}".format(
                    message.application_properties
                )
            )

    def _parse_payload(
        self, message: Message, origin_device_id, content_type, create_payload_error
    ):
        payload = ""
        data = message.get_data()

        if data:
            payload = str(next(data), "utf8")

        if create_payload_error:
            payload = "Some Random Payload"

        if "application/json" not in content_type.lower():
            self._warnings.append(
                "Content type not supported. "
                "Content type found: {}. "
                "Content type expected: application/json. "
                "DeviceId: {}".format(content_type, origin_device_id)
            )
        else:
            try:
                payload = json.loads(
                    re.compile(r"(\\r\\n)+|\\r+|\\n+").sub("", payload)
                )
            except Exception:
                self._errors.append(
                    "Invalid JSON format. "
                    "DeviceId: {}, Raw payload {}".format(origin_device_id, payload)
                )

        return payload

    # Static validations should only need information present in the payload
    # i.e. there should be no need for network calls
    def _perform_static_validations(self, origin_device_id: str, payload: dict):
        # if its not a dictionary, something else went wrong with parsing
        if not isinstance(payload, dict):
            return

        self._validate_field_names(origin_device_id=origin_device_id, payload=payload)

    def _validate_field_names(self, origin_device_id: str, payload: dict):
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
            self._errors.append(
                "The following field names are not allowed: '{}'. "
                "Payload: '{}'. "
                "Message origin: '{}'.".format(
                    invalid_field_names, payload, origin_device_id
                )
            )

    # Dynamic validations should need data external to the payload
    # e.g. device template
    def _perform_dynamic_validations(
        self,
        origin_device_id: str,
        payload: dict,
        central_device_provider: CentralDeviceProvider,
        create_payload_name_error=False,
    ):
        # if the payload is not a dictionary some other parsing error occurred
        if not isinstance(payload, dict):
            return

        # device provider was not passed in, no way to get the device template
        if not isinstance(central_device_provider, CentralDeviceProvider):
            return

        template = self._get_device_template(
            origin_device_id=origin_device_id,
            central_device_provider=central_device_provider,
        )

        # _get_device_template should log error if there was an issue
        if not template:
            return

        template_schemas = self._extract_template_schemas_from_template(
            origin_device_id=origin_device_id, template=template
        )

        # _extract_template_schemas_from_template should log error if there was an issue
        if not isinstance(template_schemas, dict):
            return

        self._validate_payload_against_schema(
            origin_device_id=origin_device_id,
            payload=payload,
            template_schemas=template_schemas,
        )

    def _get_device_template(
        self, origin_device_id: str, central_device_provider: CentralDeviceProvider,
    ):
        try:
            return central_device_provider.get_device_template_by_device_id(
                origin_device_id
            )
        except Exception as e:
            self._errors.append(
                "Unable to get DCM for device: {}."
                "Inner exception: {}".format(origin_device_id, e)
            )

    def _extract_template_schemas_from_template(
        self, origin_device_id: str, template: dict
    ):
        try:
            schemas = []
            dcm = template["capabilityModel"]
            implements = dcm["implements"]
            for implementation in implements:
                contents = implementation["schema"]["contents"]
                schemas.extend(contents)
            return {schema["name"]: schema for schema in schemas}
        except Exception:
            self._errors.append(
                "Unable to extract device schema for device: {}."
                "Template: {}".format(origin_device_id, template)
            )

    # currently validates:
    # 1) primitive types match (e.g. boolean is indeed bool etc)
    # 2) names match (i.e. Humidity vs humidity etc)
    def _validate_payload_against_schema(
        self, origin_device_id: str, payload: dict, template_schemas: dict,
    ):
        template_schema_names = template_schemas.keys()
        for name, value in payload.items():
            schema = template_schemas.get(name)
            if not schema:
                self._errors.append(
                    "Telemetry item '{}' is not present in DCM. "
                    "Device ID: {}. "
                    "List of allowed telemetry values for this type of device: {}. "
                    "NOTE: telemetry names are CASE-SENSITIVE".format(
                        name, origin_device_id, template_schema_names
                    )
                )

            is_dict = isinstance(schema, dict)
            if is_dict and not self._validate_types_match(value, schema):
                expected_type = str(schema.get("schema"))
                self._errors.append(
                    "Type mismatch. "
                    "Expected type: '{}'. "
                    "Value received: '{}'. "
                    "Telemetry identifier: {}. "
                    "Device ID: {}. "
                    "All dates/times/durations must be ISO 8601 compliant.".format(
                        expected_type, value, name, origin_device_id
                    )
                )

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
