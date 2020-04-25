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


class MessageParser(object):
    _logger = get_logger(__name__)

    def __init__(self, logger=None):
        self._reset_issues()
        if logger:
            self._logger = logger

    def parse_message(self, message: Message, properties: dict) -> dict:
        self._reset_issues()

        if not properties:
            properties = {}  # guard against None being passed in

        system_properties = self._parse_system_properties(message)

        self._parse_content_encoding(message, system_properties)

        event = {}

        origin_device_id = self.parse_device_id(message)
        event["origin"] = origin_device_id

        content_type = self._parse_content_type(system_properties, origin_device_id)

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

        payload = self._parse_payload(message, origin_device_id, content_type)

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def parse_device_id(self, message: Message) -> str:
        try:
            return str(message.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            self._errors.append("Device id not found in message: {}".format(message))

    def write_logs(self):
        pass

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
                "Failed to parse system_properties for message {}.".format(message)
            )
            return {}

    def _parse_content_encoding(self, message: Message, system_properties) -> str:
        content_encoding = ""

        if "content_encoding" in system_properties:
            content_encoding = system_properties["content_encoding"]

        if not content_encoding:
            # encoding not found error
            return None

        if "utf-8" not in content_encoding.lower():
            # utf-8 error
            return None

        return content_encoding

    def _parse_content_type(self, system_properties, origin_device_id) -> str:
        content_type = ""
        if "content_type" in system_properties:
            content_type = system_properties["content_type"]

        if not content_type:
            # content_type warning
            pass

        return content_type

    def _parse_annotations(self, message: Message):
        try:
            return unicode_binary_map(message.annotations)
        except Exception:
            # decode warning
            pass

    def _parse_application_properties(self, message: Message):
        try:
            return unicode_binary_map(message.application_properties)
        except Exception:
            # decode warning
            pass

    def _parse_payload(self, message: Message, origin_device_id, content_type):
        payload = ""
        data = message.get_data()

        if data:
            payload = str(next(data), "utf8")

        if "application/json" not in content_type.lower():
            # warning
            pass
        else:
            try:
                payload = json.loads(
                    re.compile(r"(\\r\\n)+|\\r+|\\n+").sub("", payload)
                )
            except Exception:
                # invalid json error
                pass

        return payload
