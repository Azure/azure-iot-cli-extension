# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def error_no_hub_or_login_on_input(entity_type="IoT Hub"):
    return (
        "Please provide an {0} entity name (via the '--hub-name' or '-n' parameter)"
        " or {0} connection string via --login..."
    ).format(entity_type)


def error_param_top_out_of_bounds(upper_limit=None):
    ul_suffix = "and <= {}".format(upper_limit)
    return "top must be > 0 {}".format(ul_suffix if upper_limit else "")


def info_param_properties_device(include_mqtt=True, include_http=False):
    http_content = (
        "For http messaging - application properties are sent using iothub-app-<name>=value, for instance "
        "iothub-app-myprop=myvalue. System properties are generally prefixed with iothub-<name> like iothub-correlationid "
        "but there are exceptions such as content-type and content-encoding.  "
    )

    mqtt_content = (
        "For mqtt messaging - you are able to send system properties using "
        "$.<name>=value. For instance $.cid=12345 sets the system correlation Id property. "
        "Other system property identifier examples include $.ct for content type, "
        "$.mid for message Id and $.ce for content encoding.  "
    )

    return (
        "Message property bag in key-value pairs with the following format: a=b;c=d. "
        "{}{}".format(mqtt_content if include_mqtt else "", http_content if include_http else "")
    )
