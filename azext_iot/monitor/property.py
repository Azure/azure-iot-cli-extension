# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import datetime
import isodate
import time

from azext_iot.constants import (
    CENTRAL_ENDPOINT,
    DEVICETWIN_POLLING_INTERVAL_SEC,
    DEVICETWIN_MONITOR_TIME_SEC,
)
from azext_iot.central.providers.devicetwin_provider import CentralDeviceTwinProvider
from azext_iot.central.models.devicetwin import DeviceTwin, Property


def start_property_monitor(
    cmd,
    device_id,
    app_id,
    token,
    central_dns_suffix=CENTRAL_ENDPOINT,
    polling_interval_seconds=DEVICETWIN_POLLING_INTERVAL_SEC,
):
    prev_twin = None

    device_twin_provider = CentralDeviceTwinProvider(
        cmd=cmd, app_id=app_id, token=token, device_id=device_id
    )

    while True:

        raw_twin = device_twin_provider.get_device_twin(
            central_dns_suffix=central_dns_suffix
        )

        twin = DeviceTwin(raw_twin)
        if prev_twin:
            change_d = compare_properties(
                prev_twin.desired_property, twin.desired_property
            )
            change_r = compare_properties(
                prev_twin.reported_property, twin.reported_property
            )

            if change_d:
                print("Changes in desired properties:")
                print("version :", twin.desired_property.version)
                print(change_d)

            if change_r:
                print("Changes in reported properties:")
                print("version :", twin.reported_property.version)
                print(change_r)

        time.sleep(polling_interval_seconds)

        prev_twin = twin


def compare_properties(prev_prop: Property, prop: Property):
    if prev_prop.version == prop.version:
        return

    changes = {
        key: changed_props(prop.props[key], prop.metadata[key], key)
        for key, val in prop.metadata.items()
        if is_relevant(key, val)
    }

    return changes


def is_relevant(key, val):
    if key in {"$lastUpdated", "$lastUpdatedVersion"}:
        return False

    updated_within = datetime.datetime.now() - datetime.timedelta(
        seconds=DEVICETWIN_MONITOR_TIME_SEC
    )

    last_updated = isodate.parse_datetime(val["$lastUpdated"])
    return last_updated.timestamp() >= updated_within.timestamp()


def changed_props(prop, metadata, property_name):
    # not an interface - whole thing is change log
    if "$iotin" not in property_name:
        return prop

    # iterate over property in the interface
    # if the property has been updated within DEVICETWIN_MONITOR_TIME_SEC
    # track it as a change
    diff = {key: prop[key] for key, val in metadata.items() if is_relevant(key, val)}
    return diff
