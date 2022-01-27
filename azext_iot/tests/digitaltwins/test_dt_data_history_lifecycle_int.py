# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from knack.log import get_logger
from . import DTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings
from . import generate_generic_id

logger = get_logger(__name__)

resource_test_env_vars = [
    "azext_dt_ep_eventhub_namespace",
    "azext_dt_ep_eventhub_topic_consumer_group",
    "azext_dt_ep_rg",
    "azext_dt_adx_cluster",
    "azext_dt_adx_database",
    "azext_dt_adx_rg",
    "azext_dt_testdt",
]
settings = DynamoSettings(opt_env_set=resource_test_env_vars)


class TestDTConnections(DTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDTConnections, self).__init__(test_case)
        self.adx_cluster_name = settings.env.azext_dt_adx_cluster
        self.adx_database_name = settings.env.azext_dt_adx_database
        self.adx_resource_group = settings.env.azext_dt_adx_rg
        self.eventhub_namespace = settings.env.azext_dt_ep_eventhub_namespace
        self.eventhub_resource_group = settings.env.azext_dt_ep_rg
        self.tracked_eventhubs = []

        self.adx_database_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.Kusto/clusters/{}"
            "/Databases/{}".format(
                self.current_subscription,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.adx_database_name
            )
        )

    def test_dt_data_history_adx(self):
        self.wait_for_capacity()
        instance_name = f"dt{generate_generic_id()}"
        connection_name = f"cn-{generate_generic_id()}"
        table_name = f"tb_{generate_generic_id()}"
        eventhub_name = f"e{generate_generic_id()}"
        consumer_group = "test"

        create_output = self.cmd(
            "dt create -n {} -g {} -l {} --assign-identity".format(
                instance_name,
                self.rg,
                "northeurope"
            )
        ).get_output_in_json()
        self.track_instance(create_output)

        # Fail test if hostName missing
        assert create_output.get(
            "hostName"
        ), "Service failed to provision DT instance: {}.".format(instance_name)
        assert create_output["publicNetworkAccess"] == "Enabled"

        # wait for identity assignment
        sleep(60)

        # Add required roles and create event hub
        eventhub_instance_id = self.create_new_eventhub(
            eventhub_namespace=self.eventhub_namespace,
            eventhub_name=eventhub_name,
            eventhub_rg=self.eventhub_resource_group,
            consumer_group=consumer_group
        )

        expected_attributes = {
            "dt_name": instance_name,
            "rg": self.rg,
            "connection_name": connection_name,
            "adx_database_name": self.adx_database_name,
            "adx_cluster_name": self.adx_cluster_name,
            "eventhub_namespace": self.eventhub_namespace,
            "eventhub_name": eventhub_name,
            "adx_resource_group": self.adx_resource_group,
            "eventhub_resource_group": self.eventhub_resource_group,
            "consumer_group": "$Default",
            "location": create_output["location"],
            "table_name": "adt_dh_{}_{}".format(
                instance_name,
                create_output["location"]
            )
        }

        connection_result = self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
            )
        ).get_output_in_json()
        assert_common_connection_attributes(
            connection_output=connection_result, expected_attributes=expected_attributes
        )

        # Check role assignments - needed once
        principal_id = create_output.get("identity").get("principalId")
        assert len(self.get_role_assignment(
            role="Azure Event Hubs Data Owner", scope=eventhub_instance_id, assignee=principal_id
        )) == 1
        assert len(self.get_role_assignment(
            role="Contributor", scope=self.adx_database_id, assignee=principal_id
        )) == 1
        assert len(self.get_adx_role(assignee_name=instance_name)) == 1

        # Add custom consumer group and table
        connection_result = self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxt {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} --ehc {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                table_name,
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
                consumer_group,
            )
        ).get_output_in_json()

        expected_attributes["consumer_group"] = consumer_group
        expected_attributes["table_name"] = table_name
        assert_common_connection_attributes(
            connection_output=connection_result, expected_attributes=expected_attributes
        )

        # One connection per dt instance
        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                generate_generic_id(),
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        list_result = self.cmd(
            "dt data-history list -n {} -g {}".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_result) == 1

        show_result = self.cmd(
            "dt data-history show -n {} -g {} --cn {}".format(
                instance_name, self.rg, connection_name
            )
        ).get_output_in_json()
        assert_common_connection_attributes(
            connection_output=show_result, expected_attributes=expected_attributes
        )

        self.cmd(
            "dt data-history delete -n {} -g {} --cn {} -y".format(
                instance_name, self.rg, connection_name
            )
        )

        list_result = self.cmd(
            "dt data-history list -n {} -g {}".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_result) == 0

    def test_dt_data_history_adx_create_incorrect_resource(self):
        self.wait_for_capacity()
        instance_name = f"dt{generate_generic_id()}"
        connection_name = f"cn-{generate_generic_id()}"
        eventhub_name = f"e{generate_generic_id()}"
        self.create_new_eventhub(
            eventhub_namespace=self.eventhub_namespace,
            eventhub_name=eventhub_name,
            eventhub_rg=self.eventhub_resource_group
        )

        create_output = self.cmd(
            "dt create -n {} -g {} -l {} --assign-identity".format(
                instance_name,
                self.rg,
                "northeurope"
            )
        ).get_output_in_json()
        self.track_instance(create_output)

        # Fail test if hostName missing
        assert create_output.get(
            "hostName"
        ), "Service failed to provision DT instance: {}.".format(instance_name)
        assert create_output["publicNetworkAccess"] == "Enabled"

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                "t",
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                "testresource",
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                self.adx_database_name,
                self.adx_resource_group,
                "testresource",
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                "testresource",
                eventhub_name,
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                "testresource",
                self.eventhub_resource_group,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} --ehc {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                self.adx_database_name,
                self.adx_resource_group,
                self.adx_cluster_name,
                self.eventhub_namespace,
                eventhub_name,
                self.eventhub_resource_group,
                "testresource",
            ),
            expect_failure=True
        )

    def get_adx_role(self, assignee_name):
        api_version = "api-version=2021-01-01"
        database_admin_list = self.cmd(
            "az rest --method POST --url {}/listPrincipals?{}".format(
                self.adx_database_id,
                api_version,
            )
        ).get_output_in_json()
        for principal in database_admin_list["value"]:
            if principal["name"] == assignee_name:
                return [principal]
        return []

    def get_role_assignment(self, scope, role, assignee):
        return self.cmd(
            'role assignment list --scope "{}" --role "{}" --assignee {}'.format(
                scope, role, assignee
            )
        ).get_output_in_json()

    def create_new_eventhub(self, eventhub_namespace, eventhub_name, eventhub_rg, consumer_group=None):
        resource_id = self.cmd(
            "eventhubs eventhub create --namespace-name {} -n {} -g {}".format(
                eventhub_namespace, eventhub_name, eventhub_rg
            )
        ).get_output_in_json()["id"]
        self.tracked_eventhubs.append(resource_id)
        if consumer_group:
            self.cmd(
                "eventhubs eventhub consumer-group create --namespace-name {} --eventhub-name {} "
                "-g {} -n {}".format(
                    eventhub_namespace, eventhub_name, eventhub_rg, consumer_group
                )
            )
        return resource_id

    def tearDown(self):
        for eventhub in self.tracked_eventhubs:
            self.cmd(
                "eventhubs eventhub delete --ids {}".format(
                    eventhub
                )
            )
        return super().tearDown()


def assert_common_connection_attributes(
    connection_output,
    expected_attributes,
):
    assert connection_output["systemData"]
    assert connection_output["systemData"]["createdAt"]

    assert connection_output["name"] == expected_attributes["connection_name"]
    assert connection_output["id"].endswith(expected_attributes["connection_name"])
    assert expected_attributes["dt_name"] in connection_output["id"]
    assert connection_output["type"] == "Microsoft.DigitalTwins/digitalTwinsInstances/timeSeriesDatabaseConnections"

    assert connection_output["properties"]
    properties = connection_output["properties"]
    assert properties["adxDatabaseName"] == expected_attributes["adx_database_name"]
    assert expected_attributes["adx_cluster_name"] in properties["adxEndpointUri"]
    assert expected_attributes["adx_cluster_name"] in properties["adxResourceId"]
    assert properties["adxTableName"] == expected_attributes["table_name"]
    assert properties["connectionType"] == "AzureDataExplorer"
    assert properties["eventHubConsumerGroup"] == expected_attributes["consumer_group"]
    assert properties["eventHubEndpointUri"] == (
        "sb://{}.servicebus.windows.net/".format(
            expected_attributes["eventhub_namespace"]
        )
    )
    assert expected_attributes["eventhub_namespace"] in properties["eventHubNamespaceResourceId"]
    assert properties["eventHubEntityPath"] == expected_attributes["eventhub_name"]
    assert properties["provisioningState"] == "Succeeded"
