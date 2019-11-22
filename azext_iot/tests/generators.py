# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


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
