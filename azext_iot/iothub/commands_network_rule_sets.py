# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional
from azext_iot.iothub.providers.network_rule_sets import NetworkRuleSets
from knack.log import get_logger

logger = get_logger(__name__)


def network_rule_set_update(
    cmd,
    hub_name: str,
    public_network_access: Optional[bool] = None,
    add_ip_rules: Optional[Dict[str, str]] = None,
    apply_built_in: Optional[bool] = None,
    remove_all: bool = False,
    resource_group_name: Optional[str] = None,
):
    network_rule_set_provider = NetworkRuleSets(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return network_rule_set_provider.update(
        public_network_access=public_network_access,
        add_ip_rules=add_ip_rules,
        apply_built_in=apply_built_in,
        remove_all=remove_all
    )


def network_rule_set_show(
    cmd,
    hub_name: str,
    resource_group_name: Optional[str] = None,
):
    network_rule_set_provider = NetworkRuleSets(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return network_rule_set_provider.show()
