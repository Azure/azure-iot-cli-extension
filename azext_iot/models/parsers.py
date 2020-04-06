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
        pass

    def parse_msg(
        self,
        msg,
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

        system_properties = self._parse_system_properties(msg)

        content_encoding = self._parse_content_encoding(
            system_properties, msg, create_encoding_error
        )

        if not content_encoding:
            return {}

        event = {"properties": {}}

        origin_device_id = self.parse_device_id(msg)
        event["origin"] = origin_device_id

        self._parse_content_type(
            content_type_hint,
            system_properties,
            origin_device_id,
            create_custom_header_warning,
        )

        if pnp_context:
            msg_interface_name = self._parse_interface_name(
                msg, pnp_context, interface_name, origin_device_id
            )

            if not msg_interface_name:
                return {}

            event["interface"] = msg_interface_name

        if "anno" in properties or "all" in properties:
            annotations = self._parse_annotations(msg)
            event["annotations"] = annotations

        if system_properties and ("sys" in properties or "all" in properties):
            event["properties"]["system"] = system_properties

        if "app" in properties or "all" in properties:
            application_properties = self._parse_application_properties(msg)
            event["properties"]["application"] = application_properties

        payload = self._parse_payload(msg, origin_device_id, create_payload_error)
        if not payload:
            return {}

        event["payload"] = payload

        event_source = {"event": event}

        return event_source

    def parse_device_id(self, msg) -> str:
        try:
            return str(msg.annotations.get(DEVICE_ID_IDENTIFIER), "utf8")
        except Exception:
            self._errors.append(f"Device id not found in message: {msg}")

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
        self, msg, pnp_context, interface_name, origin_device_id
    ) -> str:
        msg_interface_name = None

        try:
            msg_interface_name = str(
                msg.annotations.get(INTERFACE_NAME_IDENTIFIER), "utf8"
            )
        except Exception:
            pass

        if not msg_interface_name:
            self._errors.append(
                f"Unable to parse interface_name given a pnp_device. {origin_device_id}. "
                f"msg: {msg}"
            )
            return None

        if interface_name != msg_interface_name:
            self._errors.append(
                f"Inteface name mismatch. {origin_device_id}. "
                f"Expected: {interface_name}, Actual: {msg_interface_name}"
            )
            return None

        return msg_interface_name

    def _parse_system_properties(self, msg):
        try:
            return unicode_binary_map(parse_entity(msg.properties, True))
        except Exception:
            self._errors.append(f"Failed to parse system_properties for msg {msg}.")

    def _parse_content_encoding(
        self, system_properties, msg, create_encoding_error
    ) -> str:
        if "content_encoding" not in system_properties:
            self._errors.append(f"No content encoding found for {msg}.")
            return None

        content_encoding = system_properties["content_encoding"]

        if create_encoding_error:
            content_encoding = "Some Random Encoding"

        if not content_encoding:
            self._errors.append(f"No encoding found for msg: {msg}")
            return None
        if content_encoding and "utf-8" not in content_encoding.lower():
            self._errors.append(
                f"Detected encoding {content_encoding}. "
                f"The currently supported encodings are: {SUPPORTED_ENCODINGS}. "
                f"system_properties: {system_properties}."
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
            "Message contains custom headers. "
            "Custom headers are not supported and will be dropped from the message. "
            f"DeviceId: {origin_device_id}"
        )

        return content_type

    def _parse_payload(self, msg: Message, origin_device_id, create_payload_error):
        payload = ""
        data = msg.get_data()

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

    def _parse_annotations(self, msg):
        try:
            return unicode_binary_map(msg.annotations)
        except Exception:
            self._warnings.append(
                f"Unable to decode msg.annotations: {msg.annotations}"
            )
            pass

    def _parse_application_properties(self, msg):
        try:
            return unicode_binary_map(msg.application_properties)
        except Exception:
            self._warnings.append(
                f"Unable to decode msg.application_properties: {msg.application_properties}"
            )
            pass
