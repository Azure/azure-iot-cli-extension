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
INTERFACE_NAME_IDENTIFIER = b"iothub-interface-name"


class CommonParser(AbstractBaseParser):
    def __init__(self, message: Message, common_parser_args: CommonParserArguments):
        self.issues_handler = IssueHandler()
        self._common_parser_args = common_parser_args
        self._message = message
        self.device_id = self._parse_device_id(message)
        self.interface_name = self._parse_interface_name(message)

    def parse_message(self) -> dict:
        message = self._message
        properties = self._common_parser_args.properties
        content_type = self._common_parser_args.content_type

        event = {}
        event["origin"] = self.device_id
        event["interface"] = self.interface_name

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

    def _parse_interface_name(self, message: Message) -> str:
        try:
            return str(message.annotations.get(INTERFACE_NAME_IDENTIFIER), "utf8")
        except Exception:
            # a message not containing an interface name is expected for non-pnp devices
            # so there's no "issue" to log here
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

    def _parse_content_type(self, content_type: str, system_properties: dict) -> str:
        # if content type has been set, return it
        if content_type:
            return content_type

        # otherwise attempt to parse it from system_properties
        content_type = system_properties.get("content_type", "")

        if not content_type:
            details = strings.invalid_encoding_missing()
            self._add_issue(severity=Severity.warning, details=details)

        return content_type

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

        # Assume the payload is JSON, and try to parse it.
        json_payload = self._try_parse_json(payload)

        # Only return the parsed JSON if the header specifies the payload is application/json.
        # Otherwise, just return the raw payload.
        if "application/json" in content_type.lower():
            return json_payload

        details = strings.invalid_content_type(content_type.lower())
        self._add_issue(severity=Severity.warning, details=details)

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
