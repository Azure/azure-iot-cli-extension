# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

SUPPORTED_ENCODING = ["utf-8"]
SUPPORTED_FIELD_NAME_CHARS = ["a-z", "A-Z", "0-9", "_"]
SUPPORTED_CONTENT_TYPE = ["application/json"]
SUPPORTED_MESSAGE_HEADERS = []


def unknown_device_id():
    return "Device ID not found in message".format()


def invalid_json():
    return "Invalid JSON format.".format()


def invalid_encoding(encoding: str):
    return "Encoding type '{}' is not supported. Expected encoding '{}'.".format(
        encoding, SUPPORTED_ENCODING
    )


def invalid_field_name(invalid_field_names: list):
    return (
        "Invalid characters detected. Invalid field names: '{}'. "
        "Allowed characters: {}."
    ).format(invalid_field_names, SUPPORTED_FIELD_NAME_CHARS)


def invalid_pnp_property_not_value_wrapped():
    raise NotImplementedError()


def invalid_non_pnp_field_name_duplicate():
    raise NotImplementedError()


def invalid_content_type(content_type: str):
    return "Content type '{}' is not supported. Expected Content type: {}.".format(
        content_type, SUPPORTED_CONTENT_TYPE
    )


def invalid_custom_headers():
    return (
        "Custom message headers are not supported in IoT Central. "
        "All the custom message headers will be dropped. "
        "Supported message headers: '{}'."
    ).format(SUPPORTED_MESSAGE_HEADERS)


def invalid_field_name_mismatch_template(
    unmodeled_capabilities: list, modeled_capabilities: list
):
    return (
        "Device is sending data that has not been defined in the device template. "
        "Following capabilities have NOT been defined in the device template '{}'. "
        "Following capabilities have been defined in the device template '{}'. "
    ).format(unmodeled_capabilities, modeled_capabilities)


def invalid_primitive_schema_mismatch_template(field_name: str, data_type: str, data):
    return (
        "Datatype of field '{}' does not match the datatype '{}'. Data '{}'. "
        "All dates/times/datetimes/durations must be ISO 8601 compliant.".format(
            field_name, data_type, data,
        )
    )


def invalid_interface_name_not_found():
    return "Interface name not found."


def invalid_interface_name_mismatch(
    expected_interface_name: str, actual_interface_name: str
):
    return "Inteface name mismatch. Expected: {}, Actual: {}.".format(
        expected_interface_name, actual_interface_name
    )


def invalid_system_properties():
    return "Failed to parse system properties.".format()


def invalid_encoding_none_found():
    return "No encoding found. Expected encoding 'utf-8' to be present in message header.".format()


def invalid_encoding_missing(system_properties: dict):
    return "Content type not found in system properties. System properties: {}.".format(
        system_properties
    )


def invalid_annotations(message):
    return "Unable to decode message.annotations: {}.".format(message.annotations)


def invalid_application_properties(message):
    return "Unable to decode message.application_properties: {}.".format(
        message.application_properties
    )


def device_template_not_found(error: Exception):
    return "Error retrieving template '{}'".format(error)


def invalid_template_extract_schema_failed(template: dict):
    return "Unable to extract device schema from template '{}'".format(template)
