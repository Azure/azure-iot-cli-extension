# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import mock

from uamqp.message import Message, MessageProperties
from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.monitor.parsers import common_parser
from .helpers import load_json
from .test_constants import FileNames


class TestCommonParser:
    device_id = "some-device-id"
    payload = {"String": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"

    bad_encoding = "ascii"
    bad_payload = "bad-payload"
    bad_field_name = {"violates-regex": "someValue"}
    bad_content_type = "bad-content-type"

    bad_dcm_payload = {"temperature": "someValue"}
    type_mismatch_payload = {"Bool": "someValue"}

    def test_parse_message_should_succeed(self):
        # setup
        app_prop_type = "some_property"
        app_prop_value = "some_value"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties={app_prop_type.encode(): app_prop_value.encode()},
        )
        parser = common_parser.CommonParser()

        device_template = load_json(FileNames.central_device_template_file)
        provider = CentralDeviceProvider(cmd=None, app_id=None)
        provider.get_device_template_by_device_id = mock.MagicMock(
            return_value=device_template
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties={"all"},
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=provider,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"][app_prop_type] == app_prop_value

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

    def test_parse_message_pnp_should_succeed(self):
        # setup
        interface_name = "interface_name"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                common_parser.INTERFACE_NAME_IDENTIFIER: interface_name.encode(),
            },
        )
        parser = common_parser.CommonParser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=True,
            interface_name=interface_name,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["interface"] == interface_name

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

    def test_parse_message_bad_content_type_should_warn(self):
        # setup
        encoded_payload = json.dumps(self.payload).encode()
        properties = MessageProperties(content_type=self.bad_content_type)
        message = Message(
            body=encoded_payload,
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = common_parser.CommonParser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        # verify
        # since the content_encoding header is not present, just dump the raw payload
        assert parsed_msg["event"]["payload"] == str(encoded_payload, "utf8")

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 1
        assert len(parser._info) == 0

        warning = parser._warnings[0]
        assert "Content type not supported." in warning
        assert self.bad_content_type in warning
        assert "application/json" in warning
        assert self.device_id in warning

        error = parser._errors[0]
        assert "No encoding found for message" in error

    def test_parse_message_bad_encoding_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.bad_encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(self.bad_encoding),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = common_parser.CommonParser()

        # act
        parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert "Unsupported encoding detected: '{}'".format(self.bad_encoding) in errors

    def test_parse_message_bad_json_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=self.bad_payload.encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = common_parser.CommonParser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_payload

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert "Invalid JSON format." in errors
        assert self.device_id in errors
        assert self.bad_payload in errors

    def test_parse_message_bad_field_name_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_field_name).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = common_parser.CommonParser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_field_name

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert "The following field names are not allowed" in errors
        assert "{}".format(next(iter(self.bad_field_name))) in errors
        assert str(self.bad_field_name) in errors
        assert self.device_id in errors

    def test_parse_message_pnp_should_fail(self):
        # setup
        actual_interface_name = "actual_interface_name"
        expected_interface_name = "expected_interface_name"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                common_parser.INTERFACE_NAME_IDENTIFIER: actual_interface_name.encode(),
            },
        )
        parser = common_parser.CommonParser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=True,
            interface_name=expected_interface_name,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=None,
        )

        # verify
        # all the items should still be parsed and available, but we should have an error
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["interface"] == actual_interface_name

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        actual_error = parser._errors[0]
        expected_error = "Inteface name mismatch. {}. Expected: {}, Actual: {}".format(
            self.device_id, expected_interface_name, actual_interface_name
        )
        assert actual_error == expected_error

    def test_validate_against_template_should_fail(self):
        # setup
        app_prop_type = "some_property"
        app_prop_value = "some_value"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties={app_prop_type.encode(): app_prop_value.encode()},
        )
        parser = common_parser.CommonParser()

        device_template = load_json(FileNames.central_device_template_file)
        provider = CentralDeviceProvider(cmd=None, app_id=None)
        provider.get_device_template_by_device_id = mock.MagicMock(
            return_value=device_template
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties={"all"},
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=provider,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"][app_prop_type] == app_prop_value

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        actual_error = parser._errors[0]
        expected_error = "Telemetry item '{}' is not present in capability model.".format(
            list(self.bad_dcm_payload)[0]
        )
        assert expected_error in actual_error

    def test_validate_against_bad_template_should_not_throw(self):
        # setup
        app_prop_type = "some_property"
        app_prop_value = "some_value"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties={app_prop_type.encode(): app_prop_value.encode()},
        )
        parser = common_parser.CommonParser()

        provider = CentralDeviceProvider(cmd=None, app_id=None)
        provider.get_device_template_by_device_id = mock.MagicMock(
            return_value="an_unparseable_template"
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties={"all"},
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=provider,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        actual_error = parser._errors[0]
        assert "Unable to extract device schema for device" in actual_error

    def test_type_mismatch_should_error(self):
        # setup
        app_prop_type = "some_property"
        app_prop_value = "some_value"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.type_mismatch_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties={app_prop_type.encode(): app_prop_value.encode()},
        )
        parser = common_parser.CommonParser()

        provider = CentralDeviceProvider(cmd=None, app_id=None)
        device_template = load_json(FileNames.central_device_template_file)
        provider.get_device_template_by_device_id = mock.MagicMock(
            return_value=device_template
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties={"all"},
            content_type_hint=None,
            simulate_errors=False,
            central_device_provider=provider,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.type_mismatch_payload
        assert parsed_msg["event"]["origin"] == self.device_id

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        actual_error = parser._errors[0]
        assert "Type mismatch" in actual_error
        assert "Type mismatch" in actual_error
        assert "Value received" in actual_error
        assert "Device ID" in actual_error
        assert (
            "All dates/times/datetimes/durations must be ISO 8601 compliant."
            in actual_error
        )
        assert list(self.type_mismatch_payload.values())[0] in actual_error
        assert list(self.type_mismatch_payload.keys())[0] in actual_error
