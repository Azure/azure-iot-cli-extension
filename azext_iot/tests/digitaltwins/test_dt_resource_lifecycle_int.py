# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from time import sleep
from knack.log import get_logger
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.digitaltwins.common import ADTEndpointType
from ..settings import DynamoSettings
from . import DTLiveScenarioTest
from . import (
    MOCK_RESOURCE_TAGS,
    MOCK_ENDPOINT_TAGS,
    generate_resource_id,
    generate_group_id,
)

logger = get_logger(__name__)

resource_test_env_vars = [
    "azext_dt_rbac_assignee_owner",
    "azext_dt_rbac_assignee_reader",
    "azext_dt_ep_eventhub_namespace",
    "azext_dt_ep_eventhub_policy",
    "azext_dt_ep_eventhub_topic",
    "azext_dt_ep_servicebus_namespace",
    "azext_dt_ep_servicebus_policy",
    "azext_dt_ep_servicebus_topic",
    "azext_dt_ep_eventgrid_topic",
    "azext_dt_ep_rg"
]

settings = DynamoSettings([], resource_test_env_vars)
run_rbac_tests = False
run_resource_tests = False
run_endpoint_route_tests = False

if all(
    [
        settings.env.azext_dt_rbac_assignee_owner,
        settings.env.azext_dt_rbac_assignee_reader,
    ]
):
    run_rbac_tests = True

if all(
    [
        settings.env.azext_dt_rbac_assignee_owner,
        settings.env.azext_dt_ep_eventhub_namespace,
        settings.env.azext_dt_ep_eventhub_policy,
        settings.env.azext_dt_ep_eventhub_topic,
        settings.env.azext_dt_ep_servicebus_namespace,
        settings.env.azext_dt_ep_servicebus_policy,
        settings.env.azext_dt_ep_servicebus_topic,
        settings.env.azext_dt_ep_eventgrid_topic,
        settings.env.azext_dt_ep_rg,
    ]
):
    run_endpoint_route_tests = True


class TestDTResourceLifecycle(DTLiveScenarioTest):
    def __init__(self, test_case):
        self.group_names = [generate_group_id(), generate_group_id()]
        self.instance_names = [generate_resource_id(), generate_resource_id()]
        self.dt_location = "westus2"

        super(TestDTResourceLifecycle, self).__init__(test_case, self.group_names)

    def test_dt_resource(self):
        create_output = self.cmd(
            "dt create -n {} -g {} -l {} --tags {}".format(
                self.instance_names[0],
                self.group_names[0],
                self.dt_location,
                MOCK_RESOURCE_TAGS,
            )
        ).get_output_in_json()

        assert_common_resource_attributes(
            create_output,
            self.instance_names[0],
            self.group_names[0],
            self.dt_location,
            MOCK_RESOURCE_TAGS,
        )

        # Explictly assert create prevents provisioning on a name conflict (across regions)
        self.cmd(
            "dt create -n {} -g {} -l {} --tags {}".format(
                self.instance_names[0],
                self.group_names[0],
                "eastus2euap",
                MOCK_RESOURCE_TAGS,
            ),
            expect_failure=True,
        )

        create_output = self.cmd(
            "dt create -n {} -g {} -l {}".format(
                self.instance_names[1], self.group_names[1], self.dt_location
            )
        ).get_output_in_json()

        assert_common_resource_attributes(
            create_output,
            self.instance_names[1],
            self.group_names[1],
            self.dt_location,
            None,
        )

        show_output = self.cmd(
            "dt show -n {}".format(self.instance_names[0],)
        ).get_output_in_json()

        assert_common_resource_attributes(
            show_output,
            self.instance_names[0],
            self.group_names[0],
            self.dt_location,
            MOCK_RESOURCE_TAGS,
        )

        show_output = self.cmd(
            "dt show -n {} -g {}".format(self.instance_names[1], self.group_names[1])
        ).get_output_in_json()

        assert_common_resource_attributes(
            show_output,
            self.instance_names[1],
            self.group_names[1],
            self.dt_location,
            None,
        )

        list_output = self.cmd("dt list").get_output_in_json()
        filtered_list = filter_dt_list(list_output, self.instance_names)
        assert len(filtered_list) == len(self.instance_names)

        for group in self.group_names:
            list_output = self.cmd("dt list -g {}".format(group)).get_output_in_json()
            filtered_group_list = filter_dt_list(list_output, self.instance_names)
            assert len(filtered_group_list) == 1

        # Delete does not currently return output
        self.cmd("dt delete -n {}".format(self.instance_names[0]))
        self.cmd(
            "dt delete -n {} -g {}".format(self.instance_names[1], self.group_names[1])
        )

    @pytest.mark.skipif(
        not run_rbac_tests,
        reason="azext_dt_rbac_assignee_owner and azext_dt_rbac_assignee_reader values are required.",
    )
    def test_dt_rbac(self):
        self.rbac_assignee_owner = settings.env.azext_dt_rbac_assignee_owner
        self.rbac_assignee_reader = settings.env.azext_dt_rbac_assignee_reader

        rbac_instance_name = generate_resource_id()
        self.cmd(
            "dt create -n {} -g {} -l {}".format(
                rbac_instance_name, self.group_names[0], self.dt_location,
            )
        )

        assert (
            len(
                self.cmd(
                    "dt role-assignment list -n {}".format(rbac_instance_name)
                ).get_output_in_json()
            )
            == 0
        )

        assign_output = self.cmd(
            "dt role-assignment create -n {} --assignee {} --role '{}'".format(
                rbac_instance_name, self.rbac_assignee_owner, self.role_map["owner"]
            )
        ).get_output_in_json()

        assert_common_rbac_attributes(
            assign_output,
            rbac_instance_name,
            "owner",
            self.rbac_assignee_owner,
        )

        assign_output = self.cmd(
            "dt role-assignment create -n {} --assignee {} --role '{}' -g {}".format(
                rbac_instance_name,
                self.rbac_assignee_reader,
                self.role_map["reader"],
                self.group_names[0],
            )
        ).get_output_in_json()

        assert_common_rbac_attributes(
            assign_output,
            rbac_instance_name,
            "reader",
            self.rbac_assignee_reader,
        )

        # Also grant reader to owner principal for assignment removal test later
        assign_output = self.cmd(
            "dt role-assignment create -n {} --assignee {} --role '{}'".format(
                rbac_instance_name,
                self.rbac_assignee_owner,
                self.role_map["reader"],
            )
        ).get_output_in_json()

        list_assigned_output = self.cmd(
            "dt role-assignment list -n {}".format(rbac_instance_name)
        ).get_output_in_json()

        assert len(list_assigned_output) == 3

        # role-assignment delete does not currently return output

        # Remove all role assignments (1) for assignee
        self.cmd(
            "dt role-assignment delete -n {} --assignee {}".format(
                rbac_instance_name, self.rbac_assignee_reader
            )
        )

        # Remove specific role assignment (reader) for assignee
        self.cmd(
            "dt role-assignment delete -n {} --assignee {} --role '{}'".format(
                rbac_instance_name, self.rbac_assignee_owner, self.role_map["reader"],
            )
        )

        list_assigned_output = self.cmd(
            "dt role-assignment list -n {} -g {}".format(
                rbac_instance_name, self.group_names[0]
            )
        ).get_output_in_json()

        assert len(list_assigned_output) == 1

        self.cmd("dt delete -n {}".format(rbac_instance_name))

    @pytest.mark.skipif(
        not run_endpoint_route_tests,
        reason="azext_dt_rbac_assignee_owner and all azext_dt_ep_* env vars are required.",
    )
    def test_dt_endpoints_routes(self):
        endpoints_instance_name = generate_resource_id()
        self.cmd(
            "dt create -n {} -g {} -l {}".format(
                endpoints_instance_name, self.group_names[0], self.dt_location,
            )
        )

        self.rbac_assignee_owner = settings.env.azext_dt_rbac_assignee_owner

        # Setup RBAC so we can interact with routes
        self.cmd(
            "dt role-assignment create -n {} --assignee {} --role '{}' -g {}".format(
                endpoints_instance_name,
                self.rbac_assignee_owner,
                self.role_map["owner"],
                self.group_names[0],
            )
        )

        sleep(4)  # Wait for service to catch-up

        list_ep_output = self.cmd(
            "dt endpoint list -n {}".format(endpoints_instance_name)
        ).get_output_in_json()
        assert len(list_ep_output) == 0

        eventgrid_rg = settings.env.azext_dt_ep_rg
        eventgrid_topic = settings.env.azext_dt_ep_eventgrid_topic
        eventgrid_endpoint = "myeventgridendpoint"

        logger.debug("Adding eventgrid endpoint...")
        add_ep_output = self.cmd(
            "dt endpoint create eventgrid -n {} -g {} --egg {} --egt {} --en {} --tags {}".format(
                endpoints_instance_name,
                self.group_names[0],
                eventgrid_rg,
                eventgrid_topic,
                eventgrid_endpoint,
                MOCK_ENDPOINT_TAGS,
            )
        ).get_output_in_json()

        assert_common_endpoint_attributes(
            add_ep_output,
            eventgrid_endpoint,
            ADTEndpointType.eventgridtopic,
            MOCK_ENDPOINT_TAGS,
        )

        servicebus_rg = settings.env.azext_dt_ep_rg
        servicebus_namespace = settings.env.azext_dt_ep_servicebus_namespace
        servicebus_policy = settings.env.azext_dt_ep_servicebus_policy
        servicebus_topic = settings.env.azext_dt_ep_servicebus_topic
        servicebus_endpoint = "myservicebusendpoint"

        logger.debug("Adding servicebus topic endpoint...")
        add_ep_output = self.cmd(
            "dt endpoint create servicebus -n {} --sbg {} --sbn {} --sbp {} --sbt {} --en {} --tags {}".format(
                endpoints_instance_name,
                servicebus_rg,
                servicebus_namespace,
                servicebus_policy,
                servicebus_topic,
                servicebus_endpoint,
                MOCK_ENDPOINT_TAGS,
            )
        ).get_output_in_json()

        assert_common_endpoint_attributes(
            add_ep_output,
            servicebus_endpoint,
            ADTEndpointType.servicebus,
            MOCK_ENDPOINT_TAGS,
        )

        eventhub_rg = settings.env.azext_dt_ep_rg
        eventhub_namespace = settings.env.azext_dt_ep_eventhub_namespace
        eventhub_policy = settings.env.azext_dt_ep_eventhub_policy
        eventhub_topic = settings.env.azext_dt_ep_eventhub_topic
        eventhub_endpoint = "myeventhubendpoint"

        logger.debug("Adding eventhub endpoint...")
        add_ep_output = self.cmd(
            "dt endpoint create eventhub -n {} --ehg {} --ehn {} --ehp {} --eh {} --en {}".format(
                endpoints_instance_name,
                eventhub_rg,
                eventhub_namespace,
                eventhub_policy,
                eventhub_topic,
                eventhub_endpoint,
            )
        ).get_output_in_json()

        assert_common_endpoint_attributes(
            add_ep_output, eventhub_endpoint, ADTEndpointType.eventhub, None,
        )

        show_ep_output = self.cmd(
            "dt endpoint show -n {} --en {}".format(
                endpoints_instance_name, eventhub_endpoint,
            )
        ).get_output_in_json()

        assert_common_endpoint_attributes(
            show_ep_output, eventhub_endpoint, ADTEndpointType.eventhub, None,
        )

        show_ep_output = self.cmd(
            "dt endpoint show -n {} -g {} --en {}".format(
                endpoints_instance_name, self.group_names[0], servicebus_endpoint,
            )
        ).get_output_in_json()

        assert_common_endpoint_attributes(
            show_ep_output,
            servicebus_endpoint,
            ADTEndpointType.servicebus,
            MOCK_ENDPOINT_TAGS,
        )

        list_ep_output = self.cmd(
            "dt endpoint list -n {} -g {}".format(
                endpoints_instance_name, self.group_names[0]
            )
        ).get_output_in_json()
        assert len(list_ep_output) == 3

        endpoint_names = [eventgrid_endpoint, servicebus_endpoint, eventhub_endpoint]
        filter_values = ["", "false", "type = Microsoft.DigitalTwins.Twin.Create"]

        # Test Routes
        list_routes_output = self.cmd(
            "dt route list -n {}".format(endpoints_instance_name)
        ).get_output_in_json()
        assert len(list_routes_output) == 0

        for endpoint_name in endpoint_names:
            is_last = endpoint_name == endpoint_names[-1]
            route_name = "routefor{}".format(endpoint_name)
            filter_value = filter_values.pop()
            add_route_output = self.cmd(
                "dt route create -n {} --rn {} --en {} --filter '{}' {}".format(
                    endpoints_instance_name,
                    route_name,
                    endpoint_name,
                    filter_value,
                    "-g {}".format(self.group_names[0]) if is_last else "",
                )
            ).get_output_in_json()

            assert_common_route_attributes(
                add_route_output, route_name, endpoint_name, filter_value
            )

            show_route_output = self.cmd(
                "dt route show -n {} --rn {} {}".format(
                    endpoints_instance_name,
                    route_name,
                    "-g {}".format(self.group_names[0]) if is_last else "",
                )
            ).get_output_in_json()

            assert_common_route_attributes(
                show_route_output, route_name, endpoint_name, filter_value
            )

        list_routes_output = self.cmd(
            "dt route list -n {} -g {}".format(
                endpoints_instance_name, self.group_names[0]
            )
        ).get_output_in_json()
        assert len(list_routes_output) == 3

        for endpoint_name in endpoint_names:
            is_last = endpoint_name == endpoint_names[-1]
            route_name = "routefor{}".format(endpoint_name)
            self.cmd(
                "dt route delete -n {} --rn {} {}".format(
                    endpoints_instance_name,
                    route_name,
                    "-g {}".format(self.group_names[0]) if is_last else "",
                )
            )

        list_routes_output = self.cmd(
            "dt route list -n {} -g {}".format(
                endpoints_instance_name, self.group_names[0]
            )
        ).get_output_in_json()
        assert len(list_routes_output) == 0

        # Unfortuntely the service does not yet know how to delete child resouces
        # of a dt parent automatically. So we have to explictly delete every endpoint first.

        for endpoint_name in endpoint_names:
            logger.debug("Cleaning up {} endpoint...".format(endpoint_name))
            is_last = endpoint_name == endpoint_names[-1]
            delete_ep_output = self.cmd(
                "dt endpoint delete -n {} --en {} {}".format(
                    endpoints_instance_name,
                    endpoint_name,
                    "-g {}".format(self.group_names[0]) if is_last else "",
                )
            ).get_output_in_json()
            assert delete_ep_output["provisioningState"] == "Deleting"
            assert delete_ep_output["id"].endswith("/{}".format(endpoint_name))
            sleep(15)  # Wait for service to catch-up. Service will fix at some point.

        self.cmd(
            "dt delete -n {} -g {}".format(endpoints_instance_name, self.group_names[0])
        )


def assert_common_resource_attributes(
    instance_output, resource_id, group_id, location, tags
):
    assert instance_output["createdTime"]
    assert instance_output["hostName"].startswith(resource_id)
    assert instance_output["location"] == location
    assert instance_output["id"].endswith(resource_id)
    assert instance_output["lastUpdatedTime"]
    assert instance_output["name"] == resource_id
    assert instance_output["provisioningState"] == "Succeeded"
    assert instance_output["resourceGroup"] == group_id
    assert instance_output["type"] == "Microsoft.DigitalTwins/digitalTwinsInstances"
    assert instance_output["tags"] == validate_key_value_pairs(tags)


def assert_common_route_attributes(
    route_output, route_name, endpoint_name, filter_value
):
    assert route_output["endpointName"] == endpoint_name
    assert route_output["id"] == route_name
    assert route_output["filter"] == filter_value if filter_value else "true"


def assert_common_endpoint_attributes(
    endpoint_output, endpoint_name, endpoint_type, tags
):
    assert endpoint_output["id"].endswith("/{}".format(endpoint_name))
    assert (
        endpoint_output["type"]
        == "Microsoft.DigitalTwins/digitalTwinsInstances/endpoints"
    )
    assert endpoint_output["resourceGroup"]

    if tags:
        assert endpoint_output["properties"]["tags"] == validate_key_value_pairs(tags)

    assert endpoint_output["properties"]["provisioningState"]
    assert endpoint_output["properties"]["createdTime"]

    if endpoint_type == ADTEndpointType.eventgridtopic:
        assert endpoint_output["properties"]["TopicEndpoint"]
        assert endpoint_output["properties"]["accessKey1"]
        assert endpoint_output["properties"]["accessKey2"]
        assert endpoint_output["properties"]["endpointType"] == "EventGrid"
        return
    if endpoint_type == ADTEndpointType.servicebus:
        assert endpoint_output["properties"]["primaryConnectionString"]
        assert endpoint_output["properties"]["secondaryConnectionString"]
        assert endpoint_output["properties"]["endpointType"] == "ServiceBus"
        return
    if endpoint_type == ADTEndpointType.eventhub:
        assert endpoint_output["properties"]["connectionString-PrimaryKey"]
        assert endpoint_output["properties"]["connectionString-SecondaryKey"]
        assert endpoint_output["properties"]["endpointType"] == "EventHub"
        return


def assert_common_rbac_attributes(rbac_output, instance_name, role_name, assignee):
    role_def_id = None
    if role_name == "owner":
        role_def_id = "/bcd981a7-7f74-457b-83e1-cceb9e632ffe"
    elif role_name == "reader":
        role_def_id = "/d57506d4-4c8d-48b1-8587-93c323f6a5a3"

    assert rbac_output["roleDefinitionId"].endswith(role_def_id)
    assert rbac_output["type"] == "Microsoft.Authorization/roleAssignments"
    assert rbac_output["scope"].endswith("/{}".format(instance_name))


def filter_dt_list(list_output, valid_names):
    return [inst for inst in list_output if inst["name"] in valid_names]
