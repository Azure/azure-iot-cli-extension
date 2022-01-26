# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.settings import DynamoSettings
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.embedded_cli import EmbeddedCLI
from knack.log import get_logger

logger = get_logger(__name__)

MOCK_RESOURCE_TAGS = "a=b c=d"
MOCK_RESOURCE_TAGS_DICT = {"a": "b", "c": "d"}
MOCK_DEAD_LETTER_ENDPOINT = "https://accountname.blob.core.windows.net/containerName"
MOCK_DEAD_LETTER_SECRET = "{}?sasToken".format(MOCK_DEAD_LETTER_ENDPOINT)
REGION_RESOURCE_LIMIT = 10
REGION_LIST = ["westus2", "westcentralus", "eastus2", "eastus", "eastus2euap"]

required_test_env_vars = ["azext_iot_testrg"]
resource_test_env_vars = [
    "azext_dt_ep_eventhub_namespace",
    "azext_dt_ep_eventhub_policy",
    "azext_dt_ep_eventhub_topic",
    "azext_dt_ep_servicebus_namespace",
    "azext_dt_ep_servicebus_policy",
    "azext_dt_ep_servicebus_topic",
    "azext_dt_ep_eventgrid_topic",
    "azext_dt_ep_rg",
    "azext_dt_region",
]

settings = DynamoSettings(req_env_set=required_test_env_vars, opt_env_set=resource_test_env_vars)
# Endpoint resource group
EP_RG = settings.env.azext_dt_ep_rg or settings.env.azext_iot_testrg
# EventHub
EP_EVENTHUB_NAMESPACE = settings.env.azext_dt_ep_eventhub_namespace or ("test-ehn-" + generate_generic_id())
EP_EVENTHUB_POLICY = settings.env.azext_dt_ep_eventhub_policy or ("test-ehp-" + generate_generic_id())
EP_EVENTHUB_TOPIC = settings.env.azext_dt_ep_eventhub_topic or ("test-eh-" + generate_generic_id())
# Service Bus
EP_SERVICEBUS_NAMESPACE = settings.env.azext_dt_ep_servicebus_namespace or ("test-sbn-" + generate_generic_id())
EP_SERVICEBUS_POLICY = settings.env.azext_dt_ep_servicebus_policy or ("test-sbp-" + generate_generic_id())
EP_SERVICEBUS_TOPIC = settings.env.azext_dt_ep_servicebus_topic or ("test-sbt-" + generate_generic_id())
# EventGrid
EP_EVENTGRID_TOPIC = settings.env.azext_dt_ep_eventgrid_topic or ("test-egt-" + generate_generic_id())


def generate_resource_id():
    return "dtcli-{}".format(generate_generic_id())


class DTLiveScenarioTest(LiveScenarioTest):
    role_map = {
        "owner": "Azure Digital Twins Data Owner",
        "reader": "Azure Digital Twins Data Reader",
    }

    def __init__(self, test_scenario):
        assert test_scenario

        super(DTLiveScenarioTest, self).__init__(test_scenario)
        self.embedded_cli = EmbeddedCLI()
        self._bootup_scenario()

    def _bootup_scenario(self):
        self._is_provider_registered()
        self._init_basic_env_vars()
        self.tracked_instances = []

    def _is_provider_registered(self):
        result = self.cmd(
            "provider show --namespace 'Microsoft.DigitalTwins' --query 'registrationState'"
        )
        if '"registered"' in result.output.lower():
            return

        pytest.skip(
            "Microsoft.DigitalTwins provider not registered. "
            "Run 'az provider register --namespace Microsoft.DigitalTwins'"
        )

    def _init_basic_env_vars(self):
        self._force_region = settings.env.azext_dt_region
        if self._force_region and not self.is_region_available(self._force_region):
            raise RuntimeError(
                "Forced region: {} does not have capacity.".format(self._force_region)
            )

        self.region = (
            self._force_region if self._force_region else self.get_available_region()
        )
        self.rg = settings.env.azext_iot_testrg
        if not self.rg:
            pytest.skip(
                "Digital Twins CLI tests requires at least 'azext_iot_testrg' for resource deployment."
            )
        self.rg_region = self.embedded_cli.invoke(
            "group show --name {}".format(self.rg)
        ).as_json()["location"]

    @property
    def current_user(self):
        return self.embedded_cli.invoke("account show").as_json()["user"]["name"]

    @property
    def current_subscription(self):
        return self.embedded_cli.invoke("account show").as_json()["id"]

    def wait_for_capacity(
        self, region=None, capacity: int = 1, wait_in_sec: int = 10, interval: int = 3
    ):
        from time import sleep

        target_region = region
        if not target_region:
            target_region = self.region

        if self.is_region_available(region=target_region, capacity=capacity):
            return

        while interval >= 1:
            logger.info("Waiting :{} (sec) for capacity.")
            sleep(wait_in_sec)
            if self.is_region_available(region=target_region, capacity=capacity):
                return
            interval = interval - 1

        raise RuntimeError(
            "Unavailable region DT capacity. wait(sec): {}, interval: {}, region: {}, capacity: {}".format(
                wait_in_sec, interval, target_region, capacity
            )
        )

    def is_region_available(self, region, capacity: int = 1):
        region_capacity = self.calculate_region_capacity
        return (region_capacity.get(region, 0) + capacity) <= REGION_RESOURCE_LIMIT

    @property
    def calculate_region_capacity(self) -> dict:
        instances = self.instances = self.embedded_cli.invoke("dt list").as_json()
        capacity_map = {}
        for instance in instances:
            cap_val = capacity_map.get(instance["location"], 0)
            cap_val = cap_val + 1
            capacity_map[instance["location"]] = cap_val

        for region in REGION_LIST:
            if region not in capacity_map:
                capacity_map[region] = 0

        return capacity_map

    def get_available_region(self, capacity: int = 1, skip_regions: list = None) -> str:
        if not skip_regions:
            skip_regions = []

        region_capacity = self.calculate_region_capacity

        while region_capacity:
            region = min(region_capacity, key=region_capacity.get)
            if region not in skip_regions:
                if region_capacity[region] + capacity <= REGION_RESOURCE_LIMIT:
                    return region
            region_capacity.pop(region, None)

        raise RuntimeError(
            "There are no available regions with capacity: {} for provision DT instances in subscription: {}".format(
                capacity, self.current_subscription
            )
        )

    def ensure_eventhub_resource(self):
        """Ensure that the test has all Event hub resources."""
        if not settings.env.azext_dt_ep_eventhub_namespace:
            self.embedded_cli.invoke(
                "eventhubs namespace create --name {} --resource-group {}".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                )
            )

        if not settings.env.azext_dt_ep_eventhub_topic:
            self.embedded_cli.invoke(
                "eventhubs eventhub create --namespace-name {} --resource-group {} --name {}".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                    EP_EVENTHUB_TOPIC
                )
            )

        if not settings.env.azext_dt_ep_eventhub_policy:
            self.embedded_cli.invoke(
                "eventhubs eventhub authorization-rule create --namespace-name {} --resource-group {} "
                "--eventhub-name {} --name {} --rights Send".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                    EP_EVENTHUB_TOPIC,
                    EP_EVENTHUB_POLICY
                )
            )

    def ensure_eventgrid_resource(self):
        """Ensure that the test has the Event Grid."""
        if not settings.env.azext_dt_ep_eventgrid_topic:
            self.embedded_cli.invoke(
                "eventgrid topic create --name {} --resource-group {} -l {}".format(
                    EP_EVENTGRID_TOPIC,
                    EP_RG,
                    self.region,
                )
            )

    def ensure_servicebus_resource(self):
        """Ensure that the test has all Service Bus resources."""
        if not settings.env.azext_dt_ep_servicebus_namespace:
            self.embedded_cli.invoke(
                "servicebus namespace create --name {} --resource-group {}".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                )
            )

        if not settings.env.azext_dt_ep_servicebus_topic:
            self.embedded_cli.invoke(
                "servicebus topic create --namespace-name {} --resource-group {} --name {}".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                    EP_SERVICEBUS_TOPIC
                )
            )

        if not settings.env.azext_dt_ep_servicebus_policy:
            self.embedded_cli.invoke(
                "servicebus topic authorization-rule create --namespace-name {} --resource-group {} "
                "--topic-name {} --name {} --rights Send".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                    EP_SERVICEBUS_TOPIC,
                    EP_SERVICEBUS_POLICY
                )
            )

    def delete_eventhub_resources(self):
        """Delete all created resources for endpoint tests."""
        # Eventhub
        if not settings.env.azext_dt_ep_eventhub_namespace:
            self.embedded_cli.invoke(
                "eventhubs namespace delete --name {} --resource-group {}".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                )
            )
        elif not settings.env.azext_dt_ep_eventhub_topic:
            self.embedded_cli.invoke(
                "eventhubs eventhub delete --namespace-name {} --resource-group {} --name {}".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                    EP_EVENTHUB_TOPIC
                )
            )
        elif not settings.env.azext_dt_ep_eventhub_policy:
            self.embedded_cli.invoke(
                "eventhubs eventhub authorization-rule delete --namespace-name {} --resource-group {} "
                "--topic-name {} --name {} --rights Send".format(
                    EP_EVENTHUB_NAMESPACE,
                    EP_RG,
                    EP_EVENTHUB_TOPIC,
                    EP_EVENTHUB_POLICY
                )
            )

    def delete_eventgrid_resources(self):
        """Delete all created resources for endpoint tests."""
        # Event Grid
        if not settings.env.azext_dt_ep_eventgrid_topic:
            self.embedded_cli.invoke(
                "eventgrid topic delete --name {} --resource-group {}".format(
                    EP_EVENTGRID_TOPIC,
                    EP_RG,
                )
            )

    def delete_servicebus_resources(self):
        """Delete all created resources for endpoint tests."""
        # Service Bus
        if not settings.env.azext_dt_ep_servicebus_namespace:
            self.embedded_cli.invoke(
                "servicebus namespace delete --name {} --resource-group {}".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                )
            )
        elif not settings.env.azext_dt_ep_servicebus_topic:
            self.embedded_cli.invoke(
                "servicebus topic delete --namespace-name {} --resource-group {} --name {}".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                    EP_SERVICEBUS_TOPIC
                )
            )
        elif not settings.env.azext_dt_ep_servicebus_policy:
            self.embedded_cli.invoke(
                "servicebus topic authorization-rule delete --namespace-name {} --resource-group {} "
                "--topic-name {} --name {} ".format(
                    EP_SERVICEBUS_NAMESPACE,
                    EP_RG,
                    EP_SERVICEBUS_TOPIC,
                    EP_SERVICEBUS_POLICY
                )
            )

    def track_instance(self, instance: dict):
        self.tracked_instances.append((instance["name"], instance["resourceGroup"]))

    def tearDown(self):
        for instance in self.tracked_instances:
            try:
                self.embedded_cli.invoke(
                    "dt delete -n {} -g {} -y --no-wait".format(instance[0], instance[1])
                )
            except Exception:
                logger.info("The DT instance {} has already been deleted.".format(instance))
