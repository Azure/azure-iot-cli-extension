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
from azext_iot.monitor.parsers.issue import Severity, IssueHandler, IssueMessageBuilder

DEVICE_ID_IDENTIFIER = b"iothub-connection-device-id"
INTERFACE_NAME_IDENTIFIER = b"iothub-interface-name"


class CommonParser(AbstractBaseParser):
    def __init__(self, logger=None):
        self.issues_handler = IssueHandler()
        self._device_id = None
        self._message = None

    def write_logs(self, severity=Severity.info) -> None:
        for issue in self.issues_handler.get_issues_with_minimum_severity(severity):
            issue.log()

    def parse_message(self, message: Message, **kwargs) -> dict:
        """
        Parse the message and collect errors if any occur

        Keyword Args:
            properties      (list)  list of properties to extract from message headers
            interface_name  (str)   expected interface name of pnp device
            pnp_context     (bool)  interpret the device as being a pnp device
            content_type    (str)   assumed content type (utf-8, ascii, etc)
        """
        self._message = message
        properties = kwargs.get("properties")
        pnp_context = kwargs.get("pnp_context")
        interface_name = kwargs.get("interface_name")
        content_type_hint = kwargs.get("content_type")

        event = {}

        self._device_id = self.parse_device_id(message)
        event["origin"] = self._device_id

        if not properties:
            properties = []  # guard against None being passed in

        system_properties = self._parse_system_properties(message)

        self._parse_content_encoding(message, system_properties)

        content_type = self._parse_content_type(content_type_hint, system_properties)

        if pnp_context:
            message_interface_name = self._parse_interface_name(
                message, pnp_context, interface_name
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

        payload = self._parse_payload(message, content_type)

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def _add_issue(self, severity: Severity, details: str):
        self.issues_handler.add_issue(
            severity=severity,
            details=details,
            message=self._message,
            device_id=self._device_id,
        )

    def parse_device_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            details = IssueMessageBuilder.unknown_device_id()
            self._add_issue(severity=Severity.error, details=details)
            return ""

    def _parse_interface_name(
        self, message: Message, pnp_context, expected_interface_name
    ) -> str:
        actual_interface_name = ""

        try:
            actual_interface_name = str(
                message.annotations.get(INTERFACE_NAME_IDENTIFIER), "utf8"
            )
        except Exception:
            details = IssueMessageBuilder.invalid_interface_name_not_found()
            self._add_issue(severity=Severity.error, details=details)

        if expected_interface_name != actual_interface_name:
            details = IssueMessageBuilder.invalid_interface_name_mismatch(
                expected_interface_name, actual_interface_name
            )
            self._add_issue(severity=Severity.warning, details=details)

        return actual_interface_name

    def _parse_system_properties(self, message: Message):
        try:
            return unicode_binary_map(parse_entity(message.properties, True))
        except Exception:
            details = IssueMessageBuilder.invalid_system_properties()
            self._add_issue(severity=Severity.error, details=details)
            return {}

    def _parse_content_encoding(self, message: Message, system_properties) -> str:
        content_encoding = ""

        if "content_encoding" in system_properties:
            content_encoding = system_properties["content_encoding"]

        if not content_encoding:
            details = IssueMessageBuilder.invalid_encoding_none_found()
            self._add_issue(severity=Severity.error, details=details)
            return None

        if "utf-8" not in content_encoding.lower():
            details = IssueMessageBuilder.invalid_encoding(content_encoding.lower())
            self._add_issue(severity=Severity.error, details=details)
            return None

        return content_encoding

    def _parse_content_type(self, content_type_hint, system_properties) -> str:
        content_type = ""
        if content_type_hint:
            content_type = content_type_hint
        elif "content_type" in system_properties:
            content_type = system_properties["content_type"]

        if not content_type:
            details = IssueMessageBuilder.invalid_encoding_missing(system_properties)
            self._add_issue(severity=Severity.error, details=details)

        return content_type

    def _parse_annotations(self, message: Message):
        try:
            return unicode_binary_map(message.annotations)
        except Exception:
            details = IssueMessageBuilder.invalid_annotations(message)
            self._add_issue(severity=Severity.error, details=details)
            return {}

    def _parse_application_properties(self, message: Message):
        try:
            return unicode_binary_map(message.application_properties)
        except Exception:
            details = IssueMessageBuilder.invalid_application_properties(message)
            self._add_issue(severity=Severity.error, details=details)
            return {}

    def _parse_payload(self, message: Message, content_type):
        payload = ""
        data = message.get_data()

        if data:
            payload = str(next(data), "utf8")

        if "application/json" not in content_type.lower():
            details = IssueMessageBuilder.invalid_content_type(content_type.lower())
            self._add_issue(severity=Severity.warning, details=details)
        else:
            try:
                regex = r"(\\r\\n)+|\\r+|\\n+"
                payload_no_white_space = re.compile(regex).sub("", payload)
                payload = json.loads(payload_no_white_space)
            except Exception:
                details = IssueMessageBuilder.invalid_json()
                self._add_issue(severity=Severity.error, details=details)

        return payload
