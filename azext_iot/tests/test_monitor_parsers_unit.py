# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import mock
import pytest

from uamqp.message import Message, MessageProperties
from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.monitor.parsers import common_parser, central_parser
from azext_iot.monitor.parsers.issue import Severity, IssueMessageBuilder
from .helpers import load_json
from .test_constants import FileNames


def _encode_app_props(app_props: dict):
    return {key.encode(): value.encode() for key, value in app_props.items()}


def _validate_issues(
    parser: common_parser.CommonParser,
    severity: Severity,
    expected_total_issues: int,
    expected_specified_issues: int,
    expected_messages: list,
):
    issues = parser.issues_handler.get_all_issues()
    specified_issues = parser.issues_handler.get_issues_with_severity(severity)
    assert len(issues) == expected_total_issues
    assert len(specified_issues) == expected_specified_issues

    actual_messages = [issue.message for issue in specified_issues]
    for expected_message in expected_messages:
        assert expected_message in actual_messages


class TestCommonParser:
    device_id = "some-device-id"
    payload = {"String": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"

    bad_encoding = "ascii"
    bad_payload = "bad-payload"
    bad_content_type = "bad-content-type"

    @pytest.mark.parametrize(
        "device_id, encoding, content_type, interface_name, payload, properties, app_properties",
        [
            (
                "device-id",
                "utf-8",
                "application/json",
                "interface_name",
                {"payloadKey": "payloadValue"},
                {"propertiesKey": "propertiesValue"},
                {"appPropsKey": "appPropsValue"},
            ),
            (
                "device-id",
                "utf-8",
                "application/json",
                "",
                {"payloadKey": "payloadValue"},
                {"propertiesKey": "propertiesValue"},
                {"appPropsKey": "appPropsValue"},
            ),
            (
                "device-id",
                "utf-8",
                "application/json",
                "",
                {},
                {"propertiesKey": "propertiesValue"},
                {"appPropsKey": "appPropsValue"},
            ),
            (
                "device-id",
                "utf-8",
                "application/json",
                "",
                {},
                {},
                {"appPropsKey": "appPropsValue"},
            ),
            ("device-id", "utf-8", "application/json", "", {}, {}, {},),
        ],
    )
    def test_parse_message_should_succeed(
        self,
        device_id,
        encoding,
        content_type,
        interface_name,
        payload,
        properties,
        app_properties,
    ):
        # setup
        properties = MessageProperties(
            content_encoding=encoding, content_type=content_type
        )
        message = Message(
            body=json.dumps(payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: device_id.encode(),
                common_parser.INTERFACE_NAME_IDENTIFIER: interface_name.encode(),
            },
            application_properties=_encode_app_props(app_properties),
        )
        parser = common_parser.CommonParser()

        # act
        pnp_context = bool(interface_name)
        parsed_msg = parser.parse_message(
            message=message,
            properties=["all"],
            interface_name=interface_name,
            pnp_context=pnp_context,
            content_type=content_type,
        )

        # verify
        assert parsed_msg["event"]["payload"] == payload
        assert parsed_msg["event"]["origin"] == device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == encoding
        assert properties["system"]["content_type"] == content_type
        assert properties["application"] == app_properties

        assert len(parser.issues_handler.get_all_issues()) == 0

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
            content_type=None,
        )

        # verify
        # since the content_encoding header is not present, just dump the raw payload
        payload = str(encoded_payload, "utf8")
        assert parsed_msg["event"]["payload"] == payload

        expected_message = IssueMessageBuilder.invalid_encoding_none_found(payload)
        _validate_issues(parser, Severity.error, 2, 1, [expected_message])

        expected_message = IssueMessageBuilder.invalid_content_type(
            self.bad_content_type
        )
        _validate_issues(parser, Severity.warning, 2, 1, [expected_message])

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
            content_type=None,
        )

        expected_message = IssueMessageBuilder.invalid_encoding(self.bad_encoding)
        _validate_issues(parser, Severity.error, 1, 1, [expected_message])

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
            content_type=None,
        )

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_payload

        expected_message = IssueMessageBuilder.invalid_json(self.bad_payload)
        _validate_issues(parser, Severity.error, 1, 1, [expected_message])

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
            content_type=None,
        )

        # verify
        # all the items should still be parsed and available, but we should have an error
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["interface"] == actual_interface_name

        expected_message = IssueMessageBuilder.invalid_interface_name_mismatch(
            expected_interface_name, actual_interface_name
        )
        _validate_issues(parser, Severity.warning, 1, 1, [expected_message])


class TestCentralParser:
    device_id = "some-device-id"
    payload = {"String": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"
    app_properties = {"appPropsKey": "appPropsValue"}

    bad_encoding = "ascii"
    bad_payload = "bad-payload"
    bad_field_name = {"violates-regex": "someValue"}
    bad_content_type = "bad-content-type"

    bad_dcm_payload = {"temperature": "someValue"}
    type_mismatch_payload = {"Bool": "someValue"}

    def test_parse_message_bad_field_name_should_fail(self):
        # setup
        device_template = self._get_template()
        parser = self._create_parser(device_template)

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_field_name).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )

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

        schema = parser._extract_template_schemas_from_template(device_template)

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_field_name

        expected_message_1 = IssueMessageBuilder.invalid_field_name(
            list(self.bad_field_name.keys())
        )
        expected_message_2 = IssueMessageBuilder.invalid_field_name_mismatch_template(
            list(self.bad_field_name.keys()), list(schema.keys())
        )
        _validate_issues(
            parser, Severity.warning, 2, 2, [expected_message_1, expected_message_2]
        )

    def test_validate_against_template_should_fail(self):
        # setup
        device_template = self._get_template()
        parser = self._create_parser(device_template)

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=["all"],
            content_type=None,
        )

        schema = parser._extract_template_schemas_from_template(device_template)

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"] == self.app_properties

        expected_message = IssueMessageBuilder.invalid_field_name_mismatch_template(
            list(self.bad_dcm_payload.keys()), list(schema.keys())
        )

        _validate_issues(parser, Severity.warning, 1, 1, [expected_message])

    def test_validate_against_bad_template_should_not_throw(self):
        # setup
        device_template = "an_unparseable_template"
        parser = self._create_parser(device_template)

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=["all"],
            content_type=None,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id

        expected_message = IssueMessageBuilder.invalid_template_extract_schema_failed(
            device_template
        )

        _validate_issues(parser, Severity.error, 1, 1, [expected_message])

    def test_type_mismatch_should_error(self):
        # setup
        device_template = self._get_template()
        parser = self._create_parser(device_template)

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.type_mismatch_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties=["all"],
            content_type=None,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.type_mismatch_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["properties"]["application"] == self.app_properties

        field_name = list(self.type_mismatch_payload.keys())[0]
        data = list(self.type_mismatch_payload.values())[0]
        data_type = "boolean"
        expected_message = IssueMessageBuilder.invalid_primitive_schema_mismatch_template(
            field_name, data_type, data
        )
        _validate_issues(parser, Severity.warning, 1, 1, [expected_message])

    def _get_template(self):
        return load_json(FileNames.central_device_template_file)

    def _create_parser(self, device_template: dict):
        provider = CentralDeviceProvider(cmd=None, app_id=None)
        provider.get_device_template_by_device_id = mock.MagicMock(
            return_value=device_template
        )
        return central_parser.CentralParser(provider)
