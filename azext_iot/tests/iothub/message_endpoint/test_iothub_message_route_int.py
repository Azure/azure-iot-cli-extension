# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import Optional
import pytest
from azext_iot.iothub.common import RouteSourceType
from azext_iot.tests.iothub import (
    EP_COSMOS_PARTITION_PATH,
    STORAGE_ACCOUNT,
    IoTLiveScenarioTest,
    EP_RG,
    EP_EVENTHUB_NAMESPACE,
    EP_EVENTHUB_INSTANCE,
    EP_SERVICEBUS_NAMESPACE,
    EP_SERVICEBUS_QUEUE,
    EP_SERVICEBUS_TOPIC,
    EP_COSMOS_DATABASE,
    EP_COSMOS_COLLECTION,
    STORAGE_CONTAINER
)
from azext_iot.common._azure import _parse_connection_string, parse_cosmos_db_connection_string


class TestIoTMessageRoutes(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTMessageRoutes, self).__init__(
            test_case
        )
        # self._create_eventhub()
        # self.enable_hub_system_identity()
        self.ran_eventhub = False

    @pytest.fixture(scope='class', autouse=True)
    def tearDownEndpoints(self):
        yield None

        # Event hub deletes fail if not there (delete is not a no-op)
        if self.ran_eventhub:
            self._delete_eventhub()


    def test_route_lifecycle(self):
        # make a route of every kind
        route_names = self.generate_device_names(6)
        built_in_endpoint = "events"
        endpoint_name = "events" # "endpoint_to_be_created"

        # # Basic use, type = Invalid
        # self.cmd(
        #     "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
        #         self.entity_name, self.entity_rg, route_names[0], built_in_endpoint, RouteSourceType.Invalid.value
        #     )
        # )

        # Custom endpoint must exist
        self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
                self.entity_name, self.entity_rg, route_names[0], "test", RouteSourceType.DeviceMessages.value
            ),
            expect_failure=True
        )

        # Basic use, type = DeviceMessages
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
                self.entity_name, self.entity_rg, route_names[0], built_in_endpoint, RouteSourceType.DeviceMessages.value
            )
        ).get_output_in_json()
        assert len(routes) == 1

        expected_route = build_expected_route(name=route_names[0], source_type=RouteSourceType.DeviceMessages.value)
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[0]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[0]
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # disabled, type = TwinChangeEvents
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e false".format(
                self.entity_name, self.entity_rg, route_names[1], built_in_endpoint, RouteSourceType.TwinChangeEvents.value
            )
        ).get_output_in_json()
        assert len(routes) == 2

        expected_route = build_expected_route(name=route_names[1], source_type=RouteSourceType.TwinChangeEvents.value, enabled=False)
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[1]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[1]
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # custom endpoint, type = DeviceLifecycleEvents
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
                self.entity_name, self.entity_rg, route_names[2], endpoint_name, RouteSourceType.DeviceLifecycleEvents.value
            )
        ).get_output_in_json()
        assert len(routes) == 3

        expected_route = build_expected_route(
            name=route_names[2], source_type=RouteSourceType.DeviceLifecycleEvents.value, endpoint_name=endpoint_name
        )
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[2]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[2]
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # custom condition = false, type = DeviceJobLifecycleEvents
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -c false".format(
                self.entity_name, self.entity_rg, route_names[3], built_in_endpoint, RouteSourceType.DeviceJobLifecycleEvents.value
            )
        ).get_output_in_json()
        assert len(routes) == 4

        expected_route = build_expected_route(
            name=route_names[3], source_type=RouteSourceType.DeviceJobLifecycleEvents.value, condition="false"
        )
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[3]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[3]
            )
        ).get_output_in_json()["result"]
        assert test_result == "false"

        # enabled, DigitalTwinChangeEvents
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e true".format(
                self.entity_name, self.entity_rg, route_names[4], built_in_endpoint, RouteSourceType.DigitalTwinChangeEvents.value
            )
        ).get_output_in_json()
        assert len(routes) == 5

        expected_route = build_expected_route(name=route_names[4], source_type=RouteSourceType.DigitalTwinChangeEvents.value)
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[4]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[0]
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # enabled, custom condition, DeviceConnectionStateEvents
        routes = self.cmd(
            "iot hub message-route create -n {} -g {} --rn {} --en {} -t {} -e true -c true".format(
                self.entity_name, self.entity_rg, route_names[5], built_in_endpoint, RouteSourceType.DeviceConnectionStateEvents.value
            )
        ).get_output_in_json()
        assert len(routes) == 6

        expected_route = build_expected_route(
            name=route_names[5], source_type=RouteSourceType.DeviceConnectionStateEvents.value, condition="true"
        )
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[5]
            )
        ).get_output_in_json()

        assert_route_properties(route, expected_route)

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[0]
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # list all routes, check list by source types
        routes = self.cmd(
            "iot hub message-route list -n {} -g {}".format(
                self.entity_name, self.entity_rg,
            )
        ).get_output_in_json()
        assert len(routes) == 6

        source_types = [
            RouteSourceType.DeviceMessages.value,
            RouteSourceType.TwinChangeEvents.value,
            RouteSourceType.DeviceLifecycleEvents.value,
            RouteSourceType.DeviceJobLifecycleEvents.value,
            RouteSourceType.DigitalTwinChangeEvents.value,
            RouteSourceType.DeviceConnectionStateEvents.value
        ]
        for source_type in source_types:
            routes = self.cmd(
                "iot hub message-route list -n {} -g {} -t {}".format(
                    self.entity_name, self.entity_rg, source_type
                )
            ).get_output_in_json()
            assert len(routes) == 1

        # test all routes
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {}".format(
                self.entity_name, self.entity_rg, route_names[0]
            )
        ).get_output_in_json()["routes"]
        assert len(test_result) == 1
        assert test_result[0]["properties"]["source"].lower() == RouteSourceType.DeviceMessages.value

        # test by source type
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, RouteSourceType.DeviceMessages.value
            )
        ).get_output_in_json()["routes"]
        assert len(test_result) == 1
        assert test_result[0]["properties"]["source"].lower() == RouteSourceType.DeviceMessages.value

        # for some reason, if you try to test a source that has no successful routes, it returns all routes
        # that are successful - if you put in DeviceJobLifecycleEvents - it will return devicemessages...
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, RouteSourceType.DeviceLifecycleEvents.value
            )
        ).get_output_in_json()["routes"]
        assert len(test_result) == 1
        assert test_result[0]["properties"]["source"].lower() == RouteSourceType.DeviceLifecycleEvents.value

        # update route
        condition = "$connectionDeviceId = 'Device_temp_1' AND processingPath = 'hot' AND $body.hello = 4"
        self.cmd(
            "iot hub message-route update -n {} -g {} --rn {} -t {} --en {} -c \"{}\" -e false".format(
                self.entity_name, self.entity_rg, route_names[4], RouteSourceType.DeviceMessages.value, endpoint_name, condition
            )
        )

        expected_route = build_expected_route(
            name=route_names[4],
            source_type=RouteSourceType.DeviceMessages.value,
            endpoint_name=endpoint_name,
            condition=condition,
            enabled=False
        )
        route = self.cmd(
            "iot hub message-route show -n {} -g {} --rn {}".format(
                self.entity_name, self.entity_rg, route_names[4]
            )
        ).get_output_in_json()
        assert_route_properties(route, expected_route)

        self.kwargs["msg_body"] = {"hello": 4}
        self.kwargs["app_properties"] = {"processingPath": "hot"}
        self.kwargs["system_properties"] = {
            "contentEncoding": "utf-8",
            "contentType": "application/json",
            "connectionDeviceId": "Device_temp_1"
        }

        # Test updated route with custom props
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} --rn {} -b \"{}\" --ap \"{}\" --sp \"{}\"".format(
                self.entity_name, self.entity_rg, route_names[4], '{msg_body}', '{app_properties}', '{system_properties}'
            )
        ).get_output_in_json()["result"]
        assert test_result == "true"

        # Test all routes with custom props
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} -b \"{}\" --ap \"{}\" --sp \"{}\"".format(
                self.entity_name, self.entity_rg, '{msg_body}', '{app_properties}', '{system_properties}'
            )
        ).get_output_in_json()["routes"]
        assert len(test_result) == 1

        # delete routes by name
        self.cmd(
            "iot hub message-route delete -n {} -g {} --rn {} -y".format(
                self.entity_name, self.entity_rg, route_names[1]

            )
        )
        routes = self.cmd(
            "iot hub message-route list -n {} -g {}".format(
                self.entity_name, self.entity_rg,
            )
        ).get_output_in_json()
        assert len(routes) == 5

        # Delete by type
        self.cmd(
            "iot hub message-route delete -n {} -g {} -t {} -y".format(
                self.entity_name, self.entity_rg, RouteSourceType.DeviceMessages.value
            )
        )
        routes = self.cmd(
            "iot hub message-route list -n {} -g {}".format(
                self.entity_name, self.entity_rg,
            )
        ).get_output_in_json()
        assert len(routes) == 3

        # Return no routes that are successful, ignore fallback
        test_result = self.cmd(
            "iot hub message-route test -n {} -g {}".format(
                self.entity_name, self.entity_rg,
            )
        ).get_output_in_json()["routes"]
        test_result = remove_fallback_route(test_result)
        assert len(test_result) == 0

        test_result = self.cmd(
            "iot hub message-route test -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, RouteSourceType.DeviceMessages.value
            )
        ).get_output_in_json()["routes"]
        test_result = remove_fallback_route(test_result)
        assert len(test_result) == 0

        # Delete all
        self.cmd(
            "iot hub message-route delete -n {} -g {} -y".format(
                self.entity_name, self.entity_rg
            )
        )
        routes = self.cmd(
            "iot hub message-route list -n {} -g {}".format(
                self.entity_name, self.entity_rg,
            )
        ).get_output_in_json()
        assert len(routes) == 0

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
    return [route for route in result if route.name.lower() != "$fallback"]
