# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.central.models.enum import ApiVersion
import json
import pytest

from unittest import mock
from uamqp.message import Message, MessageProperties
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)
from azext_iot.central.models.v1 import TemplateV1, DeviceV1
from azext_iot.monitor.parsers import common_parser, central_parser
from azext_iot.monitor.parsers import strings
from azext_iot.monitor.models.arguments import CommonParserArguments
from azext_iot.monitor.models.enum import Severity
from azext_iot.tests.helpers import load_json
from azext_iot.tests.test_constants import FileNames


def _encode_app_props(app_props: dict):
    return {key.encode(): value.encode() for key, value in app_props.items()}


def _validate_issues(
    parser: common_parser.CommonParser,
    severity: Severity,
    expected_total_issues: int,
    expected_specified_issues: int,
    expected_detailss: list,
):
    issues = parser.issues_handler.get_all_issues()
    specified_issues = parser.issues_handler.get_issues_with_severity(severity)
    assert len(issues) == expected_total_issues
    assert len(specified_issues) == expected_specified_issues

    actual_messages = [issue.details for issue in specified_issues]
    for expected_details in expected_detailss:
        assert expected_details in actual_messages


@pytest.fixture(
    params=[
        common_parser.INTERFACE_NAME_IDENTIFIER_V1,
        common_parser.INTERFACE_NAME_IDENTIFIER_V2,
    ]
)
def interface_identifier_bytes(request):
    return request.param


class TestCommonParser:
    device_id = "some-device-id"
    payload = {"String": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"

    bad_encoding = "ascii"
    bad_payload = "{bad-payload"
    bad_content_type = "bad-content-type"

    @pytest.mark.parametrize(
        "device_id, encoding, content_type, interface_name, component_name, "
        "module_id, payload, properties, app_properties",
        [
            (
                "device-id",
                "utf-8",
                "application/json",
                "interface_name",
                "component_name",
                "module-id",
                {"payloadKey": "payloadValue"},
                {"propertiesKey": "propertiesValue"},
                {"appPropsKey": "appPropsValue"},
            ),
            (
                "device-id",
                "utf-8",
                "application/json",
                "interface_name",
                "component_name",
                "",
                {"payloadKey": "payloadValue"},
                {"propertiesKey": "propertiesValue"},
                {"appPropsKey": "appPropsValue"},
            ),
            (
                "device-id",
                "utf-8",
                "application/json",
                "interface_name",
                "",
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
                "",
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
                "",
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
                "",
                "",
                {},
                {},
                {"appPropsKey": "appPropsValue"},
            ),
            ("device-id", "utf-8", "application/json", "", "", "", {}, {}, {}),
        ],
    )
    def test_parse_message_should_succeed(
        self,
        device_id,
        encoding,
        content_type,
        interface_name,
        component_name,
        payload,
        properties,
        app_properties,
        module_id,
        interface_identifier_bytes,
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
                interface_identifier_bytes: interface_name.encode(),
                common_parser.MODULE_ID_IDENTIFIER: module_id.encode(),
                common_parser.COMPONENT_NAME_IDENTIFIER: component_name.encode(),
            },
            application_properties=_encode_app_props(app_properties),
        )
        args = CommonParserArguments(properties=["all"], content_type=content_type)
        parser = common_parser.CommonParser(message=message, common_parser_args=args)

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == payload
        assert parsed_msg["event"]["origin"] == device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == device_id
        module_identifier = str(common_parser.MODULE_ID_IDENTIFIER, "utf8")
        if module_id:
            assert parsed_msg["event"]["annotations"][module_identifier] == module_id
        else:
            assert not parsed_msg["event"]["annotations"].get(module_identifier)
        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == encoding
        assert properties["system"]["content_type"] == content_type
        assert properties["application"] == app_properties

        assert parsed_msg["event"]["interface"] == interface_name
        assert parsed_msg["event"]["component"] == component_name

        if interface_name:
            interface_identifier = str(interface_identifier_bytes, "utf8")
            assert (
                parsed_msg["event"]["annotations"][interface_identifier]
                == interface_name
            )

        if component_name:
            component_identifier = str(common_parser.COMPONENT_NAME_IDENTIFIER, "utf8")
            assert (
                parsed_msg["event"]["annotations"][component_identifier]
                == component_name
            )

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
        args = CommonParserArguments(content_type="application/json")
        parser = common_parser.CommonParser(message=message, common_parser_args=args)

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.payload

        expected_details_1 = strings.invalid_encoding_none_found()
        expected_details_2 = strings.content_type_mismatch(
            self.bad_content_type, "application/json"
        )
        _validate_issues(
            parser,
            Severity.warning,
            2,
            2,
            [expected_details_1, expected_details_2],
        )

    def test_parse_bad_type_and_bad_payload_should_error(self):
        # setup
        encoded_payload = self.bad_payload.encode()
        properties = MessageProperties(
            content_type=self.bad_content_type, content_encoding=self.encoding
        )
        message = Message(
            body=encoded_payload,
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        args = CommonParserArguments(content_type="application/json")
        parser = common_parser.CommonParser(message=message, common_parser_args=args)

        # act
        parsed_msg = parser.parse_message()

        # verify
        # since the content_encoding header is not present, just dump the raw payload
        payload = str(encoded_payload, "utf8")
        assert parsed_msg["event"]["payload"] == payload

        expected_details_1 = strings.content_type_mismatch(
            self.bad_content_type, "application/json"
        )
        _validate_issues(parser, Severity.warning, 2, 1, [expected_details_1])

        expected_details_2 = strings.invalid_json()
        _validate_issues(parser, Severity.error, 2, 1, [expected_details_2])

    def test_parse_message_bad_encoding_should_warn(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.bad_encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(self.bad_encoding),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        args = CommonParserArguments()
        parser = common_parser.CommonParser(message=message, common_parser_args=args)

        # act
        parser.parse_message()

        expected_details = strings.invalid_encoding(self.bad_encoding)
        _validate_issues(parser, Severity.warning, 1, 1, [expected_details])

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
        args = CommonParserArguments()
        parser = common_parser.CommonParser(message=message, common_parser_args=args)

        # act
        parsed_msg = parser.parse_message()

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_payload

        expected_details = strings.invalid_json()
        _validate_issues(parser, Severity.error, 1, 1, [expected_details])


class TestCentralParser:
    device_id = "some-device-id"
    payload = {"String": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"
    app_properties = {"appPropsKey": "appPropsValue"}
    component_name = "some-component-name"

    bad_encoding = "ascii"
    bad_payload = "bad-payload"
    bad_field_name = {"violates-regex": "someValue"}
    bad_content_type = "bad-content-type"

    bad_dcm_payload = {"temperature": "someValue"}
    type_mismatch_payload = {"Bool": "someValue"}

    def test_parse_message_bad_field_name_should_fail(self):
        # setup
        device_template = self._get_template()

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_field_name).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        args = CommonParserArguments()
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_field_name

        # field name contains '-' character error
        expected_details_1 = strings.invalid_field_name(
            list(self.bad_field_name.keys())
        )
        _validate_issues(parser, Severity.error, 2, 1, [expected_details_1])

        # field name not present in template warning
        expected_details_2 = strings.invalid_field_name_mismatch_template(
            list(self.bad_field_name.keys()), device_template.schema_names
        )

        _validate_issues(parser, Severity.warning, 2, 1, [expected_details_2])

    def test_validate_against_template_should_fail(self):
        # setup
        device_template = self._get_template()

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"] == self.app_properties

        expected_details = strings.invalid_field_name_mismatch_template(
            list(self.bad_dcm_payload.keys()), device_template.schema_names
        )

        _validate_issues(parser, Severity.warning, 1, 1, [expected_details])

    def test_validate_against_no_component_template_should_fail(self):
        # setup
        device_template = self._get_template()

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                common_parser.COMPONENT_NAME_IDENTIFIER: self.component_name.encode(),
            },
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id
        component_identifier = str(common_parser.COMPONENT_NAME_IDENTIFIER, "utf8")
        assert (
            parsed_msg["event"]["annotations"][component_identifier]
            == self.component_name
        )
        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"] == self.app_properties

        expected_details = strings.invalid_component_name(self.component_name, [])

        _validate_issues(parser, Severity.warning, 1, 1, [expected_details])

    def test_validate_against_invalid_component_template_should_fail(self):
        # setup
        device_template = TemplateV1(
            load_json(FileNames.central_property_validation_template_file)
        )

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                common_parser.COMPONENT_NAME_IDENTIFIER: self.component_name.encode(),
            },
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id
        component_identifier = str(common_parser.COMPONENT_NAME_IDENTIFIER, "utf8")
        assert (
            parsed_msg["event"]["annotations"][component_identifier]
            == self.component_name
        )
        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"] == self.app_properties

        expected_details = strings.invalid_component_name(
            self.component_name, list(device_template.components.keys())
        )

        _validate_issues(parser, Severity.warning, 1, 1, [expected_details])

    def test_validate_invalid_telmetry_component_template_should_fail(self):
        # setup
        device_template = TemplateV1(
            load_json(FileNames.central_property_validation_template_file)
        )

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={
                common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                common_parser.COMPONENT_NAME_IDENTIFIER: list(
                    device_template.components.keys()
                )[1].encode(),
            },
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(common_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id
        component_identifier = str(common_parser.COMPONENT_NAME_IDENTIFIER, "utf8")
        assert (
            parsed_msg["event"]["annotations"][component_identifier]
            == list(device_template.components.keys())[1]
        )
        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"] == self.app_properties

        expected_details = strings.invalid_field_name_component_mismatch_template(
            list(self.bad_dcm_payload.keys()),
            device_template.component_schema_names,
        )

        _validate_issues(parser, Severity.warning, 1, 1, [expected_details])

    def test_validate_against_bad_template_should_not_throw(self):
        # setup
        device_template = "an_unparseable_template"

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.bad_dcm_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # haven't found a better way to force the error to occur within parser
        parser._central_template_provider.get_device_template = (
            lambda x, central_dns_suffix: TemplateV1(device_template)
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.bad_dcm_payload
        assert parsed_msg["event"]["origin"] == self.device_id

        expected_details = strings.device_template_not_found(
            "Could not parse iot central device template."
        )

        _validate_issues(parser, Severity.error, 1, 1, [expected_details])

    def test_type_mismatch_should_error(self):
        # setup
        device_template = self._get_template()

        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.type_mismatch_payload).encode(),
            properties=properties,
            annotations={common_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties=_encode_app_props(self.app_properties),
        )
        args = CommonParserArguments(properties=["all"])
        parser = self._create_parser(
            device_template=device_template, message=message, args=args
        )

        # act
        parsed_msg = parser.parse_message()

        # verify
        assert parsed_msg["event"]["payload"] == self.type_mismatch_payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["properties"]["application"] == self.app_properties

        field_name = list(self.type_mismatch_payload.keys())[0]
        data = list(self.type_mismatch_payload.values())[0]
        data_type = "boolean"
        expected_details = strings.invalid_primitive_schema_mismatch_template(
            field_name, data_type, data
        )
        _validate_issues(parser, Severity.error, 1, 1, [expected_details])

    def _get_template(self):
        return TemplateV1(load_json(FileNames.central_device_template_file))

    def _create_parser(
        self,
        device_template: TemplateV1,
        message: Message,
        args: CommonParserArguments,
    ):
        device_provider = CentralDeviceProvider(
            cmd=None, app_id=None, api_version=ApiVersion.v1.value
        )
        template_provider = CentralDeviceTemplateProvider(
            cmd=None, app_id=None, api_version=ApiVersion.v1.value
        )
        device_provider.get_device = mock.MagicMock(return_value=DeviceV1({}))
        template_provider.get_device_template = mock.MagicMock(
            return_value=device_template
        )
        return central_parser.CentralParser(
            message=message,
            central_device_provider=device_provider,
            central_template_provider=template_provider,
            common_parser_args=args,
        )
