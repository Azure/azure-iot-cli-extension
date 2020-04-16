# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import random
import re
import json

from knack.log import get_logger
from uamqp.message import Message
from azext_iot.common.utility import parse_entity, unicode_binary_map
from azext_iot.central.providers import CentralDeviceProvider

SUPPORTED_ENCODINGS = ["utf-8"]
DEVICE_ID_IDENTIFIER = b"iothub-connection-device-id"
INTERFACE_NAME_IDENTIFIER = b"iothub-interface-name"
random.seed(0)


class Event3Parser(object):
    _info = []
    _warnings = []
    _errors = []
    _logger = get_logger(__name__)

    def __init__(self, logger=None):
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

        self._validate_payload_against_dcm(
            origin_device_id,
            payload,
            central_device_provider,
            create_payload_name_error,
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

    def _validate_payload_against_dcm(
        self,
        origin_device_id: str,
        payload: str,
        central_device_provider: CentralDeviceProvider,
        create_payload_name_error=False,
    ):
        if not central_device_provider:
            return

        if not hasattr(payload, "keys"):
            # some error happend while parsing
            # should be captured by _parse_payload method above
            return

        try:
            template = central_device_provider.get_device_template(origin_device_id)
        except Exception as e:
            self._errors.append(
                "Unable to get DCM for device: {}."
                "Inner exception: {}".format(origin_device_id, e)
            )
            return

        try:
            all_schema = self._extract_schema_from_template(template)
            all_names = [schema["name"] for schema in all_schema]
        except Exception:
            self._errors.append(
                "Unable to extract device schema for device: {}."
                "Template: {}".format(origin_device_id, template)
            )
            return

        for telemetry_name in payload.keys():
            if create_payload_name_error or telemetry_name not in all_names:
                self._errors.append(
                    "Telemetry item '{}' is not present in DCM. "
                    "Device ID: {}. "
                    "List of allowed telemetry values for this type of device: {}. "
                    "NOTE: telemetry names are CASE-SENSITIVE".format(
                        telemetry_name, origin_device_id, all_names
                    )
                )

    def _extract_schema_from_template(self, template):
        all_schema = []
        dcm = template["capabilityModel"]
        implements = dcm["implements"]
        for implementation in implements:
            contents = implementation["schema"]["contents"]
            all_schema.extend(contents)

        return all_schema
