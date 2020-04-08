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
        pnp_context,
        interface_name,
        properties,
        content_type_hint,
        simulate_errors,
    ) -> dict:
        self._reset_issues()
        create_encoding_error = False
        create_custom_header_warning = False
        create_payload_error = False

        if not properties:
            properties = {}  # guard against None being passed in

        i = random.randint(1, 3)
        if simulate_errors and i == 1:
            create_encoding_error = True
        if simulate_errors and i == 2:
            create_custom_header_warning = True
        if simulate_errors and i == 3:
            create_payload_error = True

        system_properties = self._parse_system_properties(message)

        content_encoding = self._parse_content_encoding(
            message, system_properties, create_encoding_error
        )

        if not content_encoding:
            return {}

        event = {}

        origin_device_id = self.parse_device_id(message)
        event["origin"] = origin_device_id

        self._parse_content_type(
            content_type_hint,
            system_properties,
            origin_device_id,
            create_custom_header_warning,
        )

        if pnp_context:
            message_interface_name = self._parse_interface_name(
                message, pnp_context, interface_name, origin_device_id
            )

            if not message_interface_name:
                return {}

            event["interface"] = message_interface_name

        if properties:
            event["properties"] = {}

        if "anno" in properties or "all" in properties:
            annotations = self._parse_annotations(message)
            event["properties"]["annotations"] = annotations

        if system_properties and ("sys" in properties or "all" in properties):
            event["properties"]["system"] = system_properties

        if "app" in properties or "all" in properties:
            application_properties = self._parse_application_properties(message)
            event["properties"]["application"] = application_properties

        payload = self._parse_payload(message, origin_device_id, create_payload_error)
        if not payload:
            return {}

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def parse_device_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            self._errors.append(f"Device id not found in message: {message}")

    def log_errors(self) -> None:
        for error in self._errors:
            self._logger.error("[Error] " + error)

    def log_warnings(self) -> None:
        for warning in self._warnings:
            self._logger.warn("[Warning] " + warning)

    def log_info(self) -> None:
        for info in self._info:
            self._logger.info("[Info] " + info)

    def _reset_issues(self) -> None:
        self._info = []
        self._warnings = []
        self._errors = []

    def _parse_interface_name(
        self, message: Message, pnp_context, interface_name, origin_device_id
    ) -> str:
        message_interface_name = None

        try:
            message_interface_name = str(
                message.annotations.get(INTERFACE_NAME_IDENTIFIER), "utf8"
            )
        except Exception:
            pass

        if not message_interface_name:
            self._errors.append(
                f"Unable to parse interface_name given a pnp_device. {origin_device_id}. "
                f"message: {message}"
            )
            return None

        if interface_name != message_interface_name:
            self._errors.append(
                f"Inteface name mismatch. {origin_device_id}. "
                f"Expected: {interface_name}, Actual: {message_interface_name}"
            )
            return None

        return message_interface_name

    def _parse_system_properties(self, message: Message):
        try:
            return unicode_binary_map(parse_entity(message.properties, True))
        except Exception:
            self._errors.append(
                f"Failed to parse system_properties for message {message}."
            )

    def _parse_content_encoding(
        self, message: Message, system_properties, create_encoding_error
    ) -> str:
        if "content_encoding" not in system_properties:
            self._errors.append(f"No content encoding found for {message}.")
            return None

        content_encoding = system_properties["content_encoding"]

        if create_encoding_error:
            content_encoding = "Some Random Encoding"

        if not content_encoding:
            self._errors.append(f"No encoding found for message: {message}")
            return None
        if content_encoding and "utf-8" not in content_encoding.lower():
            self._errors.append(
                f"Unsupported encoding detected: '{content_encoding}'. "
                f"The currently supported encodings are: {SUPPORTED_ENCODINGS}. "
                f"System_properties: {system_properties}."
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

        if content_type and "application/json" in content_type.lower():
            return content_type

        self._warnings.append(
            "Content type not supported. "
            f"Content type found: {content_type}. "
            "Content type expected: application/json. "
            f"DeviceId: {origin_device_id}"
        )

        return content_type

    def _parse_payload(self, message: Message, origin_device_id, create_payload_error):
        payload = ""
        data = message.get_data()

        if data:
            payload = str(next(data), "utf8")

        if create_payload_error:
            payload = "Some Random Payload"

        try:
            payload = json.loads(re.compile(r"(\\r\\n)+|\\r+|\\n+").sub("", payload))
        except Exception:
            self._errors.append(
                "Invalid JSON format. "
                f"DeviceId: {origin_device_id}, Raw payload {payload}"
            )
            return ""

        return payload

    def _parse_annotations(self, message: Message):
        try:
            return unicode_binary_map(message.annotations)
        except Exception:
            self._warnings.append(
                f"Unable to decode message.annotations: {message.annotations}"
            )
            pass

    def _parse_application_properties(self, message: Message):
        try:
            return unicode_binary_map(message.application_properties)
        except Exception:
            self._warnings.append(
                f"Unable to decode message.application_properties: {message.application_properties}"
            )
            pass
