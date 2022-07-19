# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

from msrest.serialization import Model


class NetworkRuleSetIpRule(Model):
    """IP Rule to be applied as part of Network Rule Set.

    All required parameters must be populated in order to send to Azure.

    :param filter_name: Required. Name of the IP filter rule.
    :type filter_name: str
    :param action: IP Filter Action. Possible values include: 'Allow'. Default
     value: "Allow" .
    :type action: str or ~service.models.NetworkRuleIPAction
    :param ip_mask: Required. A string that contains the IP address range in
     CIDR notation for the rule.
    :type ip_mask: str
    """

    _validation = {
        'filter_name': {'required': True},
        'ip_mask': {'required': True},
    }

    _attribute_map = {
        'filter_name': {'key': 'filterName', 'type': 'str'},
        'action': {'key': 'action', 'type': 'str'},
        'ip_mask': {'key': 'ipMask', 'type': 'str'},
    }

    def __init__(self, **kwargs):
        super(NetworkRuleSetIpRule, self).__init__(**kwargs)
        self.filter_name = kwargs.get('filter_name', None)
        self.action = kwargs.get('action', "Allow")
        self.ip_mask = kwargs.get('ip_mask', None)
