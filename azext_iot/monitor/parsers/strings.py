# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

SUPPORTED_ENCODING = ["utf-8"]
SUPPORTED_FIELD_NAME_CHARS = ["a-z", "A-Z", "0-9", "_"]
SUPPORTED_CONTENT_TYPE = ["application/json"]
SUPPORTED_MESSAGE_HEADERS = []


def unknown_device_id():  # error
    return "Device ID not found in message"


def invalid_json():  # error
    return "Invalid JSON format."


def invalid_encoding(encoding: str):  # warning
    return "Encoding type '{}' is not supported. Expected encoding '{}'.".format(
        encoding, SUPPORTED_ENCODING
    )


def invalid_field_name(invalid_field_names: list):  # error
    return (
        "Invalid characters detected. Invalid field names: '{}'. "
        "Allowed characters: {}."
    ).format(invalid_field_names, SUPPORTED_FIELD_NAME_CHARS)


def invalid_pnp_property_not_value_wrapped():
    raise NotImplementedError()


def invalid_non_pnp_field_name_duplicate():
    raise NotImplementedError()


def content_type_mismatch(
    actual_content_type: str, expected_content_type: str
):  # warning
    return "Content type '{}' is not supported. Expected Content type is '{}'.".format(
        actual_content_type, expected_content_type
    )


def invalid_custom_headers():
    return (
        "Custom message headers are not supported in IoT Central. "
        "All the custom message headers will be dropped. "
        "Supported message headers: '{}'."
    ).format(SUPPORTED_MESSAGE_HEADERS)


# warning
def invalid_interface_name(interface_name: str, allowed_interfaces: list):
    return (
        "Device is specifying an interface that is unknown. Device specified interface: '{}'. Allowed interfaces: '{}'."
    ).format(interface_name, allowed_interfaces)


# warning
def invalid_field_name_mismatch_template(
    unmodeled_capabilities: list, modeled_capabilities: list
):
    return (
        "Device is sending data that has not been defined in the device template. "
        "Following capabilities have NOT been defined in the device template '{}'. "
        "Following capabilities have been defined in the device template (grouped by interface) '{}'. "
    ).format(unmodeled_capabilities, modeled_capabilities)


# warning
def duplicate_property_name(duplicate_prop_name, interfaces: list):
    return (
        "Duplicate property: '{}' found under following interfaces {} in the device model. "
        "Either provide the interface name as part of the device payload or make the propery name unique in the device model"
    ).format(duplicate_prop_name, interfaces)


# error
def invalid_primitive_schema_mismatch_template(field_name: str, data_type: str, data):
    return (
        "Datatype of telemetry field '{}' does not match the datatype {}. Data sent by the device - {}. "
        "For information about format of the payload refer: https://aka.ms/iotcentral-payloads"
    ).format(field_name, data_type, data,)


# to remove
def invalid_interface_name_not_found():
    return "Interface name not found."


# to remove
def invalid_interface_name_mismatch(
    expected_interface_name: str, actual_interface_name: str
):
    return "Inteface name mismatch. Expected: {}, Actual: {}.".format(
        expected_interface_name, actual_interface_name
    )


# warning; downgrade to info if needed
def invalid_system_properties():
    return "Failed to parse system properties."


# warning
def invalid_encoding_none_found():
    return (
        "No encoding found. Expected encoding 'utf-8' to be present in message header."
    )


# warning
def invalid_encoding_missing():
    return "Content type not found in system properties."


# warning
def invalid_annotations():
    return "Unable to decode message.annotations."


# warning
def invalid_application_properties():
    return "Unable to decode message.application_properties."


# error
def device_template_not_found(error: Exception):
    return "Error retrieving template '{}'. Please try again later.".format(error)


# error
def invalid_template_extract_schema_failed(template: dict):
    return "Unable to extract device schema from template '{}'.".format(template)
