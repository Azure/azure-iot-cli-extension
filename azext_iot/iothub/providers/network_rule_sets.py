# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional
from knack.log import get_logger
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import assemble_nargs_to_dict, handle_service_exception
from azext_iot.iothub.common import PublicNetworkAccessType
from azext_iot.iothub.providers.base import IoTHubProvider
from azure.core.exceptions import HttpResponseError


logger = get_logger(__name__)


class NetworkRuleSets(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(NetworkRuleSets, self).__init__(cmd, hub_name, rg, dataplane=False)
        self.cli = EmbeddedCLI(cli_ctx=self.cmd.cli_ctx)

    def update(
        self,
        public_network_access: Optional[str] = None,
        add_ip_rules: Optional[List[List[str]]] = None,
        # remove_ip_rules: Optional[List[str]] = None,
        apply_built_in: Optional[bool] = None,
        remove_all: bool = False,
    ):
        network_rule_sets = self.hub_resource.properties.public_network_access
        if network_rule_sets is None and any([
            add_ip_rules, apply_built_in, public_network_access == PublicNetworkAccessType.IPRules
        ]):
            network_rule_sets = {
                "defaultAction": "Deny",
                "applyToBuiltInEventHubEndpoint": False,
                "ipRules": []
            }
        elif network_rule_sets:
            network_rule_sets = network_rule_sets.serialize()

        if apply_built_in:
            network_rule_sets["applyToBuiltInEventHubEndpoint"] = apply_built_in

        if remove_all:
            network_rule_sets["ipRules"] = []

        if add_ip_rules:
            current_filters = network_rule_sets["ipRules"]
            for rule in add_ip_rules:
                rule = assemble_nargs_to_dict(rule)
                if not all(["name" in rule, "address_range" in rule]):
                    raise Exception("Must have name and address range for an ip rule.")
                current_filters.append({
                    "filterName": rule["name"],
                    "action": "Allow",
                    "ipMask": rule["address_range"]
                })
            network_rule_sets["ipRules"] = current_filters

        if public_network_access == PublicNetworkAccessType.Enabled:
            self.hub_resource.properties.public_network_access = PublicNetworkAccessType.Enabled
            if network_rule_sets:
                network_rule_sets["defaultAction"] = "Allow"
        if public_network_access == PublicNetworkAccessType.Disabled:
            self.hub_resource.properties.public_network_access = PublicNetworkAccessType.Disabled
            if network_rule_sets:
                network_rule_sets["defaultAction"] = "Allow"
        if public_network_access == PublicNetworkAccessType.IPRules:
            # Q - can this be null with network rule sets not null?
            if self.hub_resource.properties.public_network_access:
                self.hub_resource.properties.public_network_access = PublicNetworkAccessType.Enabled
            network_rule_sets["defaultAction"] = "Deny"

        self.hub_resource.properties.network_rule_sets = network_rule_sets

        try:
            self.discovery.client.begin_create_or_update(
                self.hub_resource.additional_properties["resourcegroup"],
                self.hub_resource.name,
                self.hub_resource,
                if_match=self.hub_resource.etag
            )
            return self.show()
        except HttpResponseError as e:
            handle_service_exception(e)

    def show(self):
        network_rule_sets = self.hub_resource.properties.network_rule_sets
        if network_rule_sets is None:
            pass
        public_network_access = self.hub_resource.properties.public_network_access
        if public_network_access is None:
            public_network_access = PublicNetworkAccessType.Enabled
        return {
            "networkRuleSets" : network_rule_sets,
            "publicNetworkAccess" : public_network_access
        }
