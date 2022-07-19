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


class RoutingProperties(Model):
    """The routing related properties of the IoT hub. See:
    https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-messaging.

    :param endpoints:
    :type endpoints: ~service.models.RoutingEndpoints
    :param routes: The list of user-provided routing rules that the IoT hub
     uses to route messages to built-in and custom endpoints. A maximum of 100
     routing rules are allowed for paid hubs and a maximum of 5 routing rules
     are allowed for free hubs.
    :type routes: list[~service.models.RouteProperties]
    :param fallback_route: The properties of the route that is used as a
     fall-back route when none of the conditions specified in the 'routes'
     section are met. This is an optional parameter. When this property is not
     set, the messages which do not meet any of the conditions specified in the
     'routes' section get routed to the built-in eventhub endpoint.
    :type fallback_route: ~service.models.FallbackRouteProperties
    :param enrichments: The list of user-provided enrichments that the IoT hub
     applies to messages to be delivered to built-in and custom endpoints. See:
     https://aka.ms/telemetryoneventgrid
    :type enrichments: list[~service.models.EnrichmentProperties]
    """

    _attribute_map = {
        'endpoints': {'key': 'endpoints', 'type': 'RoutingEndpoints'},
        'routes': {'key': 'routes', 'type': '[RouteProperties]'},
        'fallback_route': {'key': 'fallbackRoute', 'type': 'FallbackRouteProperties'},
        'enrichments': {'key': 'enrichments', 'type': '[EnrichmentProperties]'},
    }

    def __init__(self, **kwargs):
        super(RoutingProperties, self).__init__(**kwargs)
        self.endpoints = kwargs.get('endpoints', None)
        self.routes = kwargs.get('routes', None)
        self.fallback_route = kwargs.get('fallback_route', None)
        self.enrichments = kwargs.get('enrichments', None)
