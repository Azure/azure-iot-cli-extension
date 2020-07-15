# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re

from uamqp.message import Message

from azext_iot.common.utility import parse_entity, unicode_binary_map
from azext_iot.monitor.base_classes import AbstractBaseParser
from azext_iot.monitor.parsers import strings
from azext_iot.monitor.models.arguments import CommonParserArguments
from azext_iot.monitor.models.enum import Severity
from azext_iot.monitor.parsers.issue import IssueHandler

DEVICE_ID_IDENTIFIER = b"iothub-connection-device-id"
MODULE_ID_IDENTIFIER = b"iothub-connection-module-id"
INTERFACE_NAME_IDENTIFIER_V1 = b"iothub-interface-name"
INTERFACE_NAME_IDENTIFIER_V2 = b"dt-dataschema"
COMPONENT_NAME_IDENTIFIER = b"dt-subject"


class CommonParser(AbstractBaseParser):
    def __init__(self, message: Message, common_parser_args: CommonParserArguments):
        self.issues_handler = IssueHandler()
        self._common_parser_args = common_parser_args
        self._message = message
        self.device_id = ""  # need to default
        self.device_id = self._parse_device_id(message)
        self.module_id = self._parse_module_id(message)
        self.interface_name = self._parse_interface_name(message)
        self.component_name = self._parse_component_name(message)

    def parse_message(self) -> dict:
        """
        Parses an AMQP based IoT Hub telemetry event.

        """

        message = self._message
        properties = self._common_parser_args.properties
        content_type = self._common_parser_args.content_type

        event = {}
        event["origin"] = self.device_id
        event["module"] = self.module_id
        event["interface"] = self.interface_name
        event["component"] = self.component_name

        if not properties:
            properties = []  # guard against None being passed in

        system_properties = self._parse_system_properties(message)

        self._parse_content_encoding(message, system_properties)

        content_type = self._parse_content_type(content_type, system_properties)

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

        payload = self._parse_payload(message, content_type)

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def _add_issue(self, severity: Severity, details: str):
        self.issues_handler.add_issue(
            severity=severity,
            details=details,
            message=self._message,
            device_id=self.device_id,
        )

    def _parse_device_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            details = strings.unknown_device_id()
            self._add_issue(severity=Severity.error, details=details)
            return ""

    def _parse_module_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(MODULE_ID_IDENTIFIER), "utf8")
        except Exception:
            # a message not containing an module name is expected for non-edge devices
            # so there's no "issue" to log here
            return ""

    def _parse_interface_name(self, message: Message) -> str:
        try:
            # Grab either the DTDL v1 or v2 amqp interface identifier.
            # It's highly unlikely both will be present at the same time
            # as they reflect different versions of a Plug & Play device.
            target_interface = message.annotations.get(
                INTERFACE_NAME_IDENTIFIER_V1
            ) or message.annotations.get(INTERFACE_NAME_IDENTIFIER_V2)
            return str(target_interface, "utf8")
        except Exception:
            # a message not containing an interface name is expected for non-pnp devices
            # so there's no "issue" to log here
            return ""

    def _parse_component_name(self, message: Message) -> str:
        try:
            return str(message.annotations.get(COMPONENT_NAME_IDENTIFIER), "utf8")
        except Exception:
            return ""

    def _parse_system_properties(self, message: Message):
        try:
            return unicode_binary_map(parse_entity(message.properties, True))
        except Exception:
            details = strings.invalid_system_properties()
            self._add_issue(severity=Severity.warning, details=details)
            return {}

    def _parse_content_encoding(self, message: Message, system_properties) -> str:
        content_encoding = ""

        if "content_encoding" in system_properties:
            content_encoding = system_properties["content_encoding"]

        if not content_encoding:
            details = strings.invalid_encoding_none_found()
            self._add_issue(severity=Severity.warning, details=details)
            return None

        if "utf-8" not in content_encoding.lower():
            details = strings.invalid_encoding(content_encoding.lower())
            self._add_issue(severity=Severity.warning, details=details)
            return None

        return content_encoding

    def _parse_content_type(
        self, expected_content_type: str, system_properties: dict
    ) -> str:
        actual_content_type = system_properties.get("content_type", "")

        # Device data is not expected to be of a certain type
        # Continue parsing per rules that the device is sending
        if not expected_content_type:
            return actual_content_type.lower()

        # Device is expected to send data in a certain format.
        # Data from device implies the data is in an incorrect format.
        # Log the issue, and continue parsing as if device is in expected format.
        if actual_content_type.lower() != expected_content_type.lower():
            details = strings.content_type_mismatch(
                actual_content_type, expected_content_type
            )
            self._add_issue(severity=Severity.warning, details=details)
            return expected_content_type.lower()

        return actual_content_type

    def _parse_annotations(self, message: Message):
        try:
            return unicode_binary_map(message.annotations)
        except Exception:
            details = strings.invalid_annotations()
            self._add_issue(severity=Severity.warning, details=details)
            return {}

    def _parse_application_properties(self, message: Message):
        try:
            return unicode_binary_map(message.application_properties)
        except Exception:
            details = strings.invalid_application_properties()
            self._add_issue(severity=Severity.warning, details=details)
            return {}

    def _parse_payload(self, message: Message, content_type):
        payload = ""
        data = message.get_data()

        if data:
            payload = str(next(data), "utf8")

        if "application/json" in content_type.lower():
            return self._try_parse_json(payload)

        return payload

    def _try_parse_json(self, payload):
        result = payload
        try:
            regex = r"(\\r\\n)+|\\r+|\\n+"
            payload_no_white_space = re.compile(regex).sub("", payload)
            result = json.loads(payload_no_white_space)
        except Exception:
            details = strings.invalid_json()
            self._add_issue(severity=Severity.error, details=details)

        return result
