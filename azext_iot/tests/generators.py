# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from uuid import uuid4


def create_req_monitor_events(
    device_id=None,
    device_query=None,
    interface_name=None,
    consumer_group="$Default",
    timeout=300,
    hub_name=None,
    resource_group_name=None,
    yes=False,
    properties=None,
    repair=False,
    login=None,
    content_type=None,
    enqueued_time=None,
):
    return {
        "device_id": device_id,
        "device_query": device_query,
        "interface_name": interface_name,
        "consumer_group": consumer_group,
        "timeout": timeout,
        "hub_name": hub_name,
        "resource_group_name": resource_group_name,
        "content_type": content_type,
        "enqueued_time": enqueued_time,
        "yes": yes,
        "properties": properties,
        "repair": repair,
        "login": login,
    }


def create_c2d_receive_response(minimum=False):
    baseline = {
        "headers": {
            "iothub-ack": "none",
            "iothub-correlationid": "",
            "iothub-deliverycount": "0",
            "iothub-enqueuedtime": "12/09/2019 12:00:00 PM",
            "etag": '"{}"'.format(str(uuid4())),
            "iothub-expiry": "",
            "iothub-messageid": "{}".format(str(uuid4())),
            "iothub-sequencenumber": "1",
            "iothub-to": "/devices/sensor1/messages/deviceBound",
            "iothub-userid": "",
        },
        "body": None,
    }

    if not minimum:
        baseline["headers"]["iothub-ack"] = "full"
        baseline["headers"]["iothub-app-propKey0"] = str(uuid4())
        baseline["headers"]["iothub-app-propKey1"] = str(uuid4())
        baseline["headers"]["iothub-correlationid"] = str(uuid4())
        baseline["headers"]["iothub-expiry"] = "12/09/2019 12:10:00 PM"
        baseline["headers"]["iothub-userid"] = str(uuid4())
        baseline["body"] = str(uuid4())

    return baseline


def generate_generic_id():
    return str(uuid4()).replace("-", "")
