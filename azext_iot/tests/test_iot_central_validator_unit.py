# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import pytest

from azext_iot.monitor.parsers.central_parser import CentralParser
from azext_iot.monitor.central_validator.validators import enum
from azext_iot.monitor.central_validator import validate, extract_schema_type

from .helpers import load_json
from .test_constants import FileNames

# makes it easier to get the schemas out of the template
# also helps surface template parsing bugs
parser = CentralParser(None, None, None)
get_interfaces = parser._extract_interfaces
get_schema = parser._find_schema


class TestExtractSchemaType:
    def test_extract_schema_type(self):
        expected_mapping = {
            "Bool": "boolean",
            "Date": "date",
            "DateTime": "dateTime",
            "Double": "double",
            "Duration": "duration",
            "IntEnum": "Enum",
            "StringEnum": "Enum",
            "Float": "float",
            "Geopoint": "geopoint",
            "Long": "long",
            "Object": "Object",
            "String": "string",
            "Time": "time",
            "Vector": "vector",
        }
        template = load_json(FileNames.central_device_template_file)
        interfaces = get_interfaces(template)
        for key, val in expected_mapping.items():
            schema = get_schema(key, interfaces)
            schema_type = extract_schema_type(schema)
            assert schema_type == val


class TestPrimitiveValidations:
    @pytest.mark.parametrize(
        "value, expected_result",
        [
            (True, True),
            (False, True),
            ("False", False),
            ("True", False),
            (1, False),
            (0, False),
        ],
    )
    def test_boolean(self, value, expected_result):
        assert validate({"schema": "boolean"}, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [(1, True), (-1, True), (1.1, True), ("1", False), ("1.1", False)],
    )
    def test_double_float_long(self, value, expected_result):
        assert validate({"schema": "double"}, value) == expected_result
        assert validate({"schema": "float"}, value) == expected_result
        assert validate({"schema": "long"}, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [(1, True), (-1, True), (1.1, False), ("1", False), ("1.1", False)],
    )
    def test_int(self, value, expected_result):
        assert validate({"schema": "integer"}, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [("a", True), ("asd", True), (1, False), (True, False)],
    )
    def test_str(self, value, expected_result):
        assert validate({"schema": "string"}, value) == expected_result

    # by convention we have stated that an empty payload is valid
    def test_empty(self):
        assert validate(None, None)


# none of these are valid anything in ISO 8601
BAD_ARRAY = ["asd", "", 123.4, 123, True, False]


class TestDateTimeValidations:
    # Success suite
    @pytest.mark.parametrize(
        "to_validate", ["20200101", "20200101Z", "2020-01-01", "2020-01-01Z"]
    )
    def test_is_iso8601_date_pass(self, to_validate):
        assert validate({"schema": "date"}, to_validate)

    @pytest.mark.parametrize(
        "to_validate",
        [
            "20200101T00:00:00",
            "20200101T000000",
            "2020-01-01T00:00:00",
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:00:00.00",
            "2020-01-01T00:00:00.00Z",
            "2020-01-01T00:00:00.00+08:30",
        ],
    )
    def test_is_iso8601_datetime_pass(self, to_validate):
        assert validate({"schema": "dateTime"}, to_validate)

    @pytest.mark.parametrize("to_validate", ["P32DT7.592380349524318S", "P32DT7S"])
    def test_is_iso8601_duration_pass(self, to_validate):
        assert validate({"schema": "duration"}, to_validate)

    @pytest.mark.parametrize(
        "to_validate", ["00:00:00+08:30", "00:00:00Z", "00:00:00.123Z"]
    )
    def test_is_iso8601_time_pass(self, to_validate):
        assert validate({"schema": "time"}, to_validate)

    # Failure suite
    @pytest.mark.parametrize(
        "to_validate", ["2020-13-35", *BAD_ARRAY],
    )
    def test_is_iso8601_date_fail(self, to_validate):
        assert not validate({"schema": "date"}, to_validate)

    @pytest.mark.parametrize("to_validate", ["2020-13-35", "2020-00-00T", *BAD_ARRAY])
    def test_is_iso8601_datetime_fail(self, to_validate):
        assert not validate({"schema": "dateTime"}, to_validate)

    @pytest.mark.parametrize("to_validate", ["2020-01", *BAD_ARRAY])
    def test_is_iso8601_duration_fail(self, to_validate):
        assert not validate({"schema": "duration"}, to_validate)

    @pytest.mark.parametrize("to_validate", [*BAD_ARRAY])
    def test_is_iso8601_time_fail(self, to_validate):
        assert not validate({"schema": "time"}, to_validate)


class TestPredefinedComplexType:
    @pytest.mark.parametrize(
        "value, expected_result",
        [
            ({"lat": 123, "lon": 123, "alt": 123}, True),
            ({"lat": 123.123, "lon": 123.123, "alt": 123.123}, True),
            ({"lat": 123, "lon": 123}, True),
            ({"lat": 123}, False),
            ({"lon": 123}, False),
            ({"alt": 123}, False),
            ({"lat": "123.123", "lon": "123.123", "alt": "123.123"}, False),
            ({"x": 123, "y": 123, "z": 123}, False),
            ({"x": 123.123, "y": 123.123, "z": 123.123}, False),
        ],
    )
    def test_geopoint(self, value, expected_result):
        assert validate({"schema": "geopoint"}, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [
            ({"x": 123, "y": 123, "z": 123}, True),
            ({"x": 123.123, "y": 123.123, "z": 123.123}, True),
            ({"lat": 123, "lon": 123, "alt": 123}, False),
            ({"lat": 123.123, "lon": 123.123, "alt": 123.123}, False),
            ({"lat": 123, "lon": 123}, False),
            ({"x": "123", "y": "123", "z": "123"}, False),
            ({"x": 123.123, "y": 123.123}, False),
            ({"x": 123.123, "z": 123.123}, False),
            ({"y": 123.123, "z": 123.123}, False),
        ],
    )
    def test_vector(self, value, expected_result):
        assert validate({"schema": "vector"}, value) == expected_result


class TestComplexType:
    @pytest.mark.parametrize(
        "value, expected_result",
        [(1, True), (2, True), (3, False), ("1", False), ("2", False),],
    )
    def test_int_enum(self, value, expected_result):
        template = load_json(FileNames.central_device_template_file)
        interfaces = get_interfaces(template)
        schema = get_schema("IntEnum", interfaces)
        assert validate(schema, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [("A", True), ("B", True), ("C", False), (1, False), (2, False),],
    )
    def test_str_enum(self, value, expected_result):
        template = load_json(FileNames.central_device_template_file)
        interfaces = get_interfaces(template)
        schema = get_schema("StringEnum", interfaces)
        assert validate(schema, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [
            ({"Double": 123}, True),
            ({"Double": "123"}, False),
            ({"double": 123}, False),
            ({"asd": 123}, False),
        ],
    )
    def test_object_simple(self, value, expected_result):
        template = load_json(FileNames.central_device_template_file)
        interfaces = get_interfaces(template)
        schema = get_schema("Object", interfaces)
        assert validate(schema, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [
            ({"LayerC": {"Depth1C": {"SomeTelemetry": 100}}}, True,),
            ({"LayerC": {"Depth1C": {"SomeTelemetry": 100.001}}}, True,),
            ({"LayerC": {"Depth1C": {"SomeTelemetry": "100"}}}, False,),
            ({"LayerC": {"Depth1C": {"sometelemetry": 100.001}}}, False,),
            ({"LayerC": {"depth1c": {"SomeTelemetry": 100.001}}}, False,),
            ({"layerc": {"Depth1C": {"SomeTelemetry": 100.001}}}, False,),
        ],
    )
    def test_object_medium(self, value, expected_result):
        template = load_json(FileNames.central_deeply_nested_device_template_file)
        interfaces = get_interfaces(template)
        schema = get_schema("RidiculousObject", interfaces)
        assert validate(schema, value) == expected_result

    @pytest.mark.parametrize(
        "value, expected_result",
        [
            (
                {
                    "LayerA": {
                        "Depth1A": {
                            "Depth2": {
                                "Depth3": {
                                    "Depth4": {
                                        "DeepestComplexEnum": 1,
                                        "DeepestVector": {"x": 1, "y": 2, "z": 3},
                                        "DeepestGeopoint": {
                                            "lat": 1,
                                            "lon": 2,
                                            "alt": 3,
                                        },
                                        "Depth5": {"Depth6Double": 123},
                                    }
                                }
                            }
                        }
                    }
                },
                True,
            ),
            (
                {
                    "LayerA": {
                        "Depth1A": {
                            "Depth2": {
                                "Depth3": {
                                    "Depth4": {
                                        "DeepestComplexEnum": 1,
                                        "DeepestVector": {"x": 1, "y": 2, "z": 3},
                                        "DeepestGeopoint": {
                                            "lat": "1",
                                            "lon": 2,
                                            "alt": 3,
                                        },
                                    }
                                }
                            }
                        }
                    }
                },
                False,
            ),
            (
                {
                    "LayerA": {
                        "Depth1A": {
                            "Depth2": {
                                "Depth3": {
                                    "Depth3": {
                                        "DeepestComplexEnum": 1,
                                        "DeepestVector": {"x": 1, "y": 2, "z": 3},
                                        "DeepestGeopoint": {
                                            "lat": 1,
                                            "lon": 2,
                                            "alt": 3,
                                        },
                                    }
                                }
                            }
                        }
                    }
                },
                False,
            ),
        ],
    )
    def test_object_deep(self, value, expected_result):
        template = load_json(FileNames.central_deeply_nested_device_template_file)
        interfaces = get_interfaces(template)
        schema = get_schema("RidiculousObject", interfaces)
        assert validate(schema, value) == expected_result
