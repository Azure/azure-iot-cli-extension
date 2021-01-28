# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from . import DTLiveScenarioTest
from . import generate_resource_id, generate_generic_id

logger = get_logger(__name__)


class TestDTPrivateLinksLifecycle(DTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDTPrivateLinksLifecycle, self).__init__(test_case)

    def test_dt_privatelinks(self):
        self.wait_for_capacity()

        instance_name = generate_resource_id()
        group_id = "API"
        create_output = self.cmd(
            "dt create -n {} -g {} -l {}".format(
                instance_name,
                self.rg,
                self.region,
            )
        ).get_output_in_json()
        self.track_instance(create_output)
        create_output = self.wait_for_hostname(create_output)

        # Fail test if hostName missing
        assert create_output.get(
            "hostName"
        ), "Service failed to provision DT instance: {}.".format(instance_name)
        assert create_output["publicNetworkAccess"] == "Enabled"

        update_output = self.cmd(
            "dt create -n {} -g {} -l {} --public-network-access Disabled".format(
                instance_name,
                self.rg,
                self.region,
            )
        ).get_output_in_json()
        assert update_output["publicNetworkAccess"] == "Disabled"

        list_priv_links = self.cmd(
            "dt network private-link list -n {} -g {}".format(
                instance_name,
                self.rg,
            )
        ).get_output_in_json()
        assert len(list_priv_links) > 0

        show_api_priv_link = self.cmd(
            "dt network private-link show -n {} -g {} --ln {}".format(
                instance_name, self.rg, group_id
            )
        ).get_output_in_json()
        assert show_api_priv_link["name"] == group_id
        assert (
            show_api_priv_link["type"]
            == "Microsoft.DigitalTwins/digitalTwinsInstances/privateLinkResources"
        )

        connection_name = generate_generic_id()
        endpoint_name = generate_generic_id()
        dt_instance_id = create_output["id"]
        vnet_name = generate_generic_id()
        subnet_name = generate_generic_id()

        # Create VNET
        self.cmd(
            "network vnet create -n {} -g {} --subnet-name {}".format(
                vnet_name, self.rg, subnet_name
            ),
            checks=self.check("length(newVNet.subnets)", 1),
        )
        self.cmd(
            "network vnet subnet update -n {} --vnet-name {} -g {} "
            "--disable-private-endpoint-network-policies true".format(
                subnet_name, vnet_name, self.rg
            ),
            checks=self.check("privateEndpointNetworkPolicies", "Disabled"),
        )

        create_priv_endpoint_result = self.embedded_cli.invoke(
            "network private-endpoint create --connection-name {} -n {} --private-connection-resource-id '{}'"
            " --group-id {} -g {} --vnet-name {} --subnet {} --manual-request".format(
                connection_name,
                endpoint_name,
                dt_instance_id,
                group_id,
                self.rg,
                vnet_name,
                subnet_name,
            )
        )

        if not create_priv_endpoint_result.success():
            raise RuntimeError(
                "Failed to configure private-endpoint for DT instance: {}".format(
                    instance_name
                )
            )

        list_priv_endpoints = self.cmd(
            "dt network private-endpoint connection list -n {} -g {}".format(
                instance_name,
                self.rg,
            )
        ).get_output_in_json()
        assert len(list_priv_endpoints) > 0

        instance_connection_id = list_priv_endpoints[-1]["name"]

        show_priv_endpoint = self.cmd(
            "dt network private-endpoint connection show -n {} -g {} --cn {}".format(
                instance_name, self.rg, instance_connection_id
            )
        ).get_output_in_json()
        assert show_priv_endpoint["name"] == instance_connection_id
        assert (
            show_priv_endpoint["type"]
            == "Microsoft.DigitalTwins/digitalTwinsInstances/privateEndpointConnections"
        )
        assert show_priv_endpoint["properties"]["provisioningState"] == "Succeeded"

        # Force manual approval
        assert (
            show_priv_endpoint["properties"]["privateLinkServiceConnectionState"]["status"]
            == "Pending"
        )

        random_desc_approval = "{} {}".format(
            generate_generic_id(), generate_generic_id()
        )
        set_connection_output = self.cmd(
            "dt network private-endpoint connection set -n {} -g {} --cn {} --status Approved --desc '{}'".format(
                instance_name, self.rg, instance_connection_id, random_desc_approval
            )
        ).get_output_in_json()
        assert (
            set_connection_output["properties"]["privateLinkServiceConnectionState"]["status"]
            == "Approved"
        )
        assert (
            set_connection_output["properties"]["privateLinkServiceConnectionState"]["description"]
            == random_desc_approval
        )

        random_desc_rejected = "{} {}".format(
            generate_generic_id(), generate_generic_id()
        )
        set_connection_output = self.cmd(
            "dt network private-endpoint connection set -n {} -g {} --cn {} --status Rejected --desc '{}'".format(
                instance_name, self.rg, instance_connection_id, random_desc_rejected
            )
        ).get_output_in_json()
        assert (
            set_connection_output["properties"]["privateLinkServiceConnectionState"]["status"]
            == "Rejected"
        )
        assert (
            set_connection_output["properties"]["privateLinkServiceConnectionState"]["description"]
            == random_desc_rejected
        )

        self.cmd(
            "dt network private-endpoint connection delete -n {} -g {} --cn {} -y".format(
                instance_name, self.rg, instance_connection_id
            )
        )

        list_priv_endpoints = self.cmd(
            "dt network private-endpoint connection list -n {} -g {}".format(
                instance_name,
                self.rg,
            )
        ).get_output_in_json()
        assert len(list_priv_endpoints) == 0

        # TODO clean-up optimization

        self.cmd("network private-endpoint delete -n {} -g {} ".format(endpoint_name, self.rg))
        self.cmd("network vnet delete -n {} -g {} ".format(vnet_name, self.rg))
