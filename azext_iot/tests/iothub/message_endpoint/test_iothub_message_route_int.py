# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
from time import sleep
import pytest
from azext_iot.iothub.common import RouteSourceType
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id

cli = EmbeddedCLI()
MAX_HUB_RETRIES = 30


def generate_names(prefix: str = "", count: int = 1):
    return [
        prefix + generate_generic_id()[:32 - len(prefix)]
        for _ in range(count)
    ]


@pytest.mark.hub_infrastructure(desired_tags="test=message_route")
def test_route_lifecycle(provisioned_only_iot_hubs_module, provisioned_event_hub_module):
    iot_hub = provisioned_only_iot_hubs_module[0]["name"]
    iot_rg = provisioned_only_iot_hubs_module[0]["rg"]

    # make a route of every kind
    route_names = generate_names(prefix="route", count=6)
    built_in_endpoint = "events"
    endpoint_name = generate_names(prefix="ep")[0]
    eventhub_cs = provisioned_event_hub_module["connectionString"]

    # Custom endpoint must exist - TODO: hide the error message from the pytest logs
    result = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[0], endpoint_name, RouteSourceType.DeviceMessages.value
        ),
        capture_stderr=True
    )
    assert not result.success()

    # Create said endpoint
    cli.invoke(
        "iot hub message-endpoint create eventhub -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_name, iot_rg, eventhub_cs
        )
    )

    # Basic use, type = DeviceMessages
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[0], built_in_endpoint, RouteSourceType.DeviceMessages.value
        )
    ).as_json()
    assert len(routes) == 1

    expected_route = build_expected_route(name=route_names[0], source_type=RouteSourceType.DeviceMessages.value)
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[0]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[0]
        )
    ).as_json()["result"]
    assert test_result == "true"

    # disabled, type = TwinChangeEvents
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e false".format(
            iot_hub, iot_rg, route_names[1], built_in_endpoint, RouteSourceType.TwinChangeEvents.value
        )
    ).as_json()
    assert len(routes) == 2

    expected_route = build_expected_route(
        name=route_names[1], source_type=RouteSourceType.TwinChangeEvents.value, enabled=False
    )
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[1]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[1]
        )
    ).as_json()["result"]
    assert test_result == "true"

    # custom endpoint, type = DeviceLifecycleEvents
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[2], endpoint_name, RouteSourceType.DeviceLifecycleEvents.value
        )
    ).as_json()
    assert len(routes) == 3

    expected_route = build_expected_route(
        name=route_names[2], source_type=RouteSourceType.DeviceLifecycleEvents.value, endpoint_name=endpoint_name
    )
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[2]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[2]
        )
    ).as_json()["result"]
    assert test_result == "true"

    # custom condition = false, type = DeviceJobLifecycleEvents
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -c false".format(
            iot_hub, iot_rg, route_names[3], built_in_endpoint, RouteSourceType.DeviceJobLifecycleEvents.value
        )
    ).as_json()
    assert len(routes) == 4

    expected_route = build_expected_route(
        name=route_names[3], source_type=RouteSourceType.DeviceJobLifecycleEvents.value, condition="false"
    )
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[3]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[3]
        )
    ).as_json()["result"]
    assert test_result == "false"

    # enabled, DigitalTwinChangeEvents
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e true".format(
            iot_hub, iot_rg, route_names[4], built_in_endpoint, RouteSourceType.DigitalTwinChangeEvents.value
        )
    ).as_json()
    assert len(routes) == 5

    expected_route = build_expected_route(name=route_names[4], source_type=RouteSourceType.DigitalTwinChangeEvents.value)
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[4]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[0]
        )
    ).as_json()["result"]
    assert test_result == "true"

    # enabled, custom condition, DeviceConnectionStateEvents
    routes = cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e true -c true".format(
            iot_hub, iot_rg, route_names[5], built_in_endpoint, RouteSourceType.DeviceConnectionStateEvents.value
        )
    ).as_json()
    assert len(routes) == 6

    expected_route = build_expected_route(
        name=route_names[5], source_type=RouteSourceType.DeviceConnectionStateEvents.value, condition="true"
    )
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[5]
        )
    ).as_json()

    assert_route_properties(route, expected_route)

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[0]
        )
    ).as_json()["result"]
    assert test_result == "true"

    # list all routes, check list by source types
    routes = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()
    assert len(routes) == 6

    for source_type in RouteSourceType.list_valid_types():
        routes = cli.invoke(
            "iot hub message-route list -n {} -g {} -t {}".format(
                iot_hub, iot_rg, source_type
            )
        ).as_json()
        assert len(routes) == 1

    # test all routes
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {}".format(
            iot_hub, iot_rg
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 4
    source_types = set(route["properties"]["source"].lower() for route in test_result)
    expected_types = set([
        RouteSourceType.DeviceConnectionStateEvents.value,
        RouteSourceType.DeviceLifecycleEvents.value,
        RouteSourceType.DeviceMessages.value,
        RouteSourceType.DigitalTwinChangeEvents.value
    ])
    assert source_types == expected_types

    # test by source type
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -t {}".format(
            iot_hub, iot_rg, RouteSourceType.DeviceMessages.value
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 1
    assert test_result[0]["properties"]["source"].lower() == RouteSourceType.DeviceMessages.value

    # for some reason, if you try to test a source that has no successful routes, it returns all routes
    # that are successful - if you put in DeviceJobLifecycleEvents - it will return devicemessages...
    # update 9/16 - service changed how this works?
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -t {}".format(
            iot_hub, iot_rg, RouteSourceType.DeviceJobLifecycleEvents.value
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 0

    # update route
    condition = "$connectionDeviceId = 'Device_temp_1' AND processingPath = 'hot' AND $body.hello = 4"
    cli.invoke(
        "iot hub message-route update -n {} -g {} --rn {} -t {} --en {} -c \"{}\" -e false".format(
            iot_hub, iot_rg, route_names[4], RouteSourceType.DeviceMessages.value, endpoint_name, condition
        )
    )

    expected_route = build_expected_route(
        name=route_names[4],
        source_type=RouteSourceType.DeviceMessages.value,
        endpoint_name=endpoint_name,
        condition=condition,
        enabled=False
    )
    route = cli.invoke(
        "iot hub message-route show -n {} -g {} --rn {}".format(
            iot_hub, iot_rg, route_names[4]
        )
    ).as_json()
    assert_route_properties(route, expected_route)

    msg_body = json.dumps({"hello": 4})
    app_properties = json.dumps({"processingPath": "hot"})
    system_properties = json.dumps({
        "contentEncoding": "utf-8",
        "contentType": "application/json",
        "connectionDeviceId": "Device_temp_1"
    })

    # Test updated route with custom props
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} --rn {} -b '{}' --ap '{}' --sp '{}'".format(
            iot_hub, iot_rg, route_names[4], msg_body, app_properties, system_properties
        )
    ).as_json()["result"]
    assert test_result == "true"

    # Test all routes with custom props
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -b '{}' --ap '{}' --sp '{}'".format(
            iot_hub, iot_rg, msg_body, app_properties, system_properties
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 3

    # delete routes by name
    cli.invoke(
        "iot hub message-route delete -n {} -g {} --rn {} -y".format(
            iot_hub, iot_rg, route_names[1]

        )
    )
    routes = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()
    assert len(routes) == 5

    # Delete by type
    cli.invoke(
        "iot hub message-route delete -n {} -g {} -t {} -y".format(
            iot_hub, iot_rg, RouteSourceType.DeviceMessages.value
        )
    )
    routes = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()
    assert len(routes) == 3

    # Wait for deletes to ensure test doesnt pick up deleted routes
    sleep(1)
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 2

    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -t {}".format(
            iot_hub, iot_rg, RouteSourceType.DeviceMessages.value
        )
    ).as_json()["routes"]
    test_result = remove_fallback_route(test_result)
    assert len(test_result) == 0

    # Delete all
    cli.invoke(
        "iot hub message-route delete -n {} -g {} -y".format(
            iot_hub, iot_rg
        )
    )
    routes = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()
    assert len(routes) == 0


@pytest.mark.hub_infrastructure(desired_tags="test=message_route")
def test_route_fallback_lifecycle(provisioned_only_iot_hubs_module):
    iot_hub = provisioned_only_iot_hubs_module[0]["name"]
    iot_rg = provisioned_only_iot_hubs_module[0]["rg"]
    fallback_name = "$fallback"

    expected_fallback_route = build_expected_route(
        name=fallback_name,
        source_type=RouteSourceType.DeviceMessages.value,
    )
    fallback_route = cli.invoke(
        f"iot hub message-route fallback show -n {iot_hub} -g {iot_rg}"
    ).as_json()

    assert_route_properties(fallback_route, expected_fallback_route)

    # Test by type and test all should return fallback route
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -t {}".format(
            iot_hub, iot_rg, RouteSourceType.TwinChangeEvents.value
        )
    ).as_json()["routes"]
    assert len(test_result) == 1
    assert test_result[0]["properties"]["name"] == fallback_name

    test_result = cli.invoke(
        f"iot hub message-route test -n {iot_hub} -g {iot_rg}"
    ).as_json()["routes"]
    assert len(test_result) == 1
    assert test_result[0]["properties"]["name"] == fallback_name

    # Disable fallback route
    expected_fallback_route = build_expected_route(
        name=fallback_name,
        source_type=RouteSourceType.DeviceMessages.value,
        enabled=False
    )

    fallback_route = cli.invoke(
        f"iot hub message-route fallback set -n {iot_hub} -g {iot_rg} -e false"
    ).as_json()
    assert_route_properties(fallback_route, expected_fallback_route)
    wait_till_hub_state_is_active(iot_hub, iot_rg)

    # Test by type and test all should return nothing
    test_result = cli.invoke(
        "iot hub message-route test -n {} -g {} -t {}".format(
            iot_hub, iot_rg, RouteSourceType.TwinChangeEvents.value
        )
    ).as_json()["routes"]
    assert len(test_result) == 0

    test_result = cli.invoke(
        f"iot hub message-route test -n {iot_hub} -g {iot_rg}"
    ).as_json()["routes"]
    assert len(test_result) == 0

    # Re-enable fallback
    expected_fallback_route = build_expected_route(
        name=fallback_name,
        source_type=RouteSourceType.DeviceMessages.value
    )
    fallback_route = cli.invoke(
        f"iot hub message-route fallback set -n {iot_hub} -g {iot_rg} -e true"
    ).as_json()

    assert_route_properties(fallback_route, expected_fallback_route)
    wait_till_hub_state_is_active(iot_hub, iot_rg)


def wait_till_hub_state_is_active(iot_hub: str, iot_rg: str):
    state = None
    retries = 0
    while state != "active" and retries < MAX_HUB_RETRIES:
        sleep(1)
        retries += 1
        state = cli.invoke(
            f"iot hub show -n {iot_hub} -g {iot_rg}"
        ).as_json()["properties"]["state"].lower()


def build_expected_route(
    name: str,
    source_type: str,
    endpoint_name: str = "events",
    condition: str = "true",
    enabled: bool = True
):
    return {
        "condition": condition,
        "endpointNames": [
            endpoint_name
        ],
        "isEnabled": enabled,
        "name": name,
        "source": source_type
    }


def assert_route_properties(result: dict, expected: dict):
    assert result["condition"] == expected["condition"]
    assert result["endpointNames"] == expected["endpointNames"]
    assert result["isEnabled"] == expected["isEnabled"]
    assert result["name"] == expected["name"]
    assert result["source"].lower() == expected["source"].lower()


def remove_fallback_route(result: list) -> list:
    return [route for route in result if route["properties"]["name"].lower() != "$fallback"]
