# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from knack.log import get_logger
import pytest
from azext_iot.common.utility import unpack_msrest_error
from azext_iot.digitaltwins.common import IdentityType
from azext_iot.tests.digitaltwins.dt_helpers import assert_system_data_attributes
from . import DTLiveScenarioTest, generate_resource_id
from . import (
    ADX_RG,
    ADX_CLUSTER,
    ADX_DATABASE,
    EP_RG,
    EP_EVENTHUB_NAMESPACE,
    EP_EVENTHUB_TOPIC,
    generate_generic_id
)

logger = get_logger(__name__)


class TestDTConnections(DTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDTConnections, self).__init__(test_case)
        self.adx_database_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.Kusto/clusters/{}"
            "/Databases/{}".format(
                self.current_subscription,
                ADX_RG,
                ADX_CLUSTER,
                ADX_DATABASE
            )
        )

        self.eventhub_instance_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.EventHub/"
            "namespaces/{}/eventhubs/{}".format(
                self.current_subscription,
                EP_RG,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
            )
        )

    @pytest.fixture(scope='class', autouse=True)
    def setupSuite(self):
        self.ensure_eventhub_resource()
        self.ensure_adx_resource()

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        try:
            self.delete_user_identity()
        except Exception as e:
            logger.warning(
                "Failed to delete the User Identity resource. Additional details: " +
                unpack_msrest_error(e))
        try:
            self.delete_eventhub_resources()
        except Exception as e:
            logger.warning(
                "Failed to delete the EventHub resources. Additional details: " +
                unpack_msrest_error(e)
            )
        try:
            self.delete_adx_resources()
        except Exception as e:
            logger.warning(
                "Failed to delete the ADX resources. Additional details: " +
                unpack_msrest_error(e)
            )

    def test_dt_data_history_adx(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        connection_name = f"cn-{generate_generic_id()}"
        table_name = f"tb_{generate_generic_id()}"
        consumer_group = f"cg-{generate_generic_id()}"
        self.add_eventhub_consumer_group(consumer_group=consumer_group)
        user_identity = self.ensure_user_identity()["id"]
        # TODO: lower sleep time to necessary amount
        sleep(50)

        create_output = self.cmd(
            "dt create -n {} -g {} --mi-system-assigned --mi-user-assigned {}".format(
                instance_name,
                self.rg,
                user_identity
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

        expected_attributes = {
            "dt_name": instance_name,
            "rg": self.rg,
            "connection_name": connection_name,
            "adx_database_name": ADX_DATABASE,
            "adx_cluster_name": ADX_CLUSTER,
            "eventhub_namespace": EP_EVENTHUB_NAMESPACE,
            "eventhub_name": EP_EVENTHUB_TOPIC,
            "adx_resource_group": ADX_RG,
            "eventhub_resource_group": EP_RG,
            "consumer_group": "$Default",
            "location": create_output["location"],
            "table_name": "adt_dh_{}_{}".format(
                instance_name.replace("-", "_"),
                create_output["location"]
            ),
            "identity_type": IdentityType.system_assigned.value,
            "identity_uai": None
        }

        connection_result = self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
            )
        ).get_output_in_json()
        assert_common_connection_attributes(
            connection_output=connection_result, expected_attributes=expected_attributes
        )

        # Check role assignments - needed once
        principal_id = create_output.get("identity").get("principalId")
        assert len(self.get_role_assignment(
            role="Azure Event Hubs Data Owner", scope=self.eventhub_instance_id, assignee=principal_id
        )) == 1
        assert len(self.get_role_assignment(
            role="Contributor", scope=self.adx_database_id, assignee=principal_id
        )) == 1
        assert len(self.get_adx_role(assignee_name=instance_name)) == 1

        # Add custom consumer group and table and use user assigned identity
        connection_result = self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxt {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} --ehc {} --user {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                table_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
                consumer_group,
                user_identity,
            )
        ).get_output_in_json()

        expected_attributes["identity_type"] = IdentityType.user_assigned.value
        expected_attributes["identity_uai"] = user_identity
        expected_attributes["consumer_group"] = consumer_group
        expected_attributes["table_name"] = table_name
        assert_common_connection_attributes(
            connection_output=connection_result, expected_attributes=expected_attributes
        )

        # One connection per dt instance
        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                generate_generic_id(),
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
            ),
            expect_failure=True
        )

        list_result = self.cmd(
            "dt data-history connection list -n {} -g {}".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_result) == 1

        show_result = self.cmd(
            "dt data-history connection show -n {} -g {} --cn {}".format(
                instance_name, self.rg, connection_name
            )
        ).get_output_in_json()
        assert_common_connection_attributes(
            connection_output=show_result, expected_attributes=expected_attributes
        )

        self.cmd(
            "dt data-history connection delete -n {} -g {} --cn {} -y".format(
                instance_name, self.rg, connection_name
            )
        )

        list_result = self.cmd(
            "dt data-history connection list -n {} -g {}".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_result) == 0

    def test_dt_data_history_adx_create_incorrect_resource(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        connection_name = f"cn-{generate_generic_id()}"

        create_output = self.cmd(
            "dt create -n {} -g {} --mi-system-assigned".format(
                instance_name,
                self.rg,
            )
        ).get_output_in_json()
        self.track_instance(create_output)

        # Fail test if hostName missing
        assert create_output.get(
            "hostName"
        ), "Service failed to provision DT instance: {}.".format(instance_name)
        assert create_output["publicNetworkAccess"] == "Enabled"

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                "t",
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                "testresource",
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                "testresource",
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                "testresource",
                EP_EVENTHUB_TOPIC,
                EP_RG,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                "testresource",
                EP_RG,
            ),
            expect_failure=True
        )

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} --ehc {} -y".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
                "testresource",
            ),
            expect_failure=True
        )

    def test_dt_data_history_adx_wait(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        connection_name = f"cn-{generate_generic_id()}"
        consumer_group = f"cg-{generate_generic_id()}"
        self.add_eventhub_consumer_group(consumer_group=consumer_group)

        create_output = self.cmd(
            "dt create -n {} -g {} --mi-system-assigned".format(
                instance_name,
                self.rg,
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

        expected_attributes = {
            "dt_name": instance_name,
            "rg": self.rg,
            "connection_name": connection_name,
            "adx_database_name": ADX_DATABASE,
            "adx_cluster_name": ADX_CLUSTER,
            "eventhub_namespace": EP_EVENTHUB_NAMESPACE,
            "eventhub_name": EP_EVENTHUB_TOPIC,
            "adx_resource_group": ADX_RG,
            "eventhub_resource_group": EP_RG,
            "consumer_group": consumer_group,
            "location": create_output["location"],
            "table_name": "adt_dh_{}_{}".format(
                instance_name.replace("-", "_"),
                create_output["location"]
            ),
            "identity_type": IdentityType.system_assigned.value,
            "identity_uai": None
        }

        self.cmd(
            "dt data-history connection create adx -n {} -g {} --cn {} --adxd {} --adxg {} "
            "--adxc {} --ehn {} --eh {} --ehg {} --ehc {} -y --no-wait".format(
                instance_name,
                self.rg,
                connection_name,
                ADX_DATABASE,
                ADX_RG,
                ADX_CLUSTER,
                EP_EVENTHUB_NAMESPACE,
                EP_EVENTHUB_TOPIC,
                EP_RG,
                consumer_group,
            )
        )

        self.cmd(
            "dt data-history connection wait --created -n {} -g {} --cn {}".format(
                instance_name,
                self.rg,
                connection_name,
            )
        )

        connection_result = self.cmd(
            "dt data-history connection show -n {} -g {} --cn {}".format(
                instance_name,
                self.rg,
                connection_name,
            )
        ).get_output_in_json()

        assert_common_connection_attributes(
            connection_output=connection_result, expected_attributes=expected_attributes
        )

        # Check role assignments - needed once
        principal_id = create_output.get("identity").get("principalId")
        assert len(self.get_role_assignment(
            role="Azure Event Hubs Data Owner", scope=self.eventhub_instance_id, assignee=principal_id
        )) == 1
        assert len(self.get_role_assignment(
            role="Contributor", scope=self.adx_database_id, assignee=principal_id
        )) == 1
        assert len(self.get_adx_role(assignee_name=instance_name)) == 1

        self.cmd(
            "dt data-history connection delete -n {} -g {} --cn {} -y --no-wait".format(
                instance_name, self.rg, connection_name
            )
        )

        self.cmd(
            "dt data-history connection wait --deleted -n {} -g {} --cn {}".format(
                instance_name,
                self.rg,
                connection_name,
            )
        )

        list_result = self.cmd(
            "dt data-history connection list -n {} -g {}".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_result) == 0

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


def assert_common_connection_attributes(
    connection_output,
    expected_attributes,
):
    assert_system_data_attributes(connection_output.get("systemData"))

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
    assert properties["identity"]["type"] == expected_attributes["identity_type"]
    assert properties["identity"]["userAssignedIdentity"] == expected_attributes["identity_uai"]
