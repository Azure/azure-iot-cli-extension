# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from knack.log import get_logger
from azure.cli.core.azclierror import ResourceNotFoundError
from azext_iot.common.utility import process_json_arg
from azext_iot.constants import USER_AGENT
from azext_iot.iothub.common import RouteSourceType
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azure.cli.core.commands.client_factory import get_subscription_id


logger = get_logger(__name__)


class MessageRoute(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
    ):
        self.cmd = cmd
        self.api_version = "2022-04-30-preview"
        self.client = self.get_client()
        self.discovery = IotHubDiscovery(cmd)
        self.discovery.track2 = True
        self.discovery.client = self.client.iot_hub_resource
        self.discovery.sub_id = get_subscription_id(self.cmd.cli_ctx)
        # Need to get the direct resource
        self.hub_resource = self.get_iot_hub_resource(hub_name, rg)

    def get_client(self):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.cli.core.profiles import ResourceType
        client = get_mgmt_service_client(
            self.cmd.cli_ctx,
            ResourceType.MGMT_IOTHUB,
            api_version=self.api_version
        )

        # Adding IoT Ext User-Agent is done with best attempt.
        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client

    def get_iot_hub_resource(self, hub_name, rg):
        return self.discovery.find_resource(hub_name, rg)

    def create(
        self,
        route_name: str,
        source_type: str,
        endpoint_name: str,
        enabled: bool = True,
        condition: Optional[str] = None,
    ):
        self.hub_resource.properties.routing.routes.append(
            {
                "source":source_type,
                "name":route_name,
                "endpointNames":endpoint_name.split(),
                "condition":('true' if condition is None else condition),
                "isEnabled":enabled
            }
        )

        return self.client.iot_hub_resource.begin_create_or_update(
            resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
            resource_name=self.hub_resource.name,
            iot_hub_description=self.hub_resource,
            if_match=self.hub_resource.etag
        )

    def update(
        self,
        route_name: str,
        source_type: Optional[str] = None,
        endpoint_name: Optional[str] = None,
        enabled: Optional[bool] = None,
        condition: Optional[str] = None,
    ):
        route = self.show(route_name=route_name)
        route.source = route.source if source_type is None else source_type
        route.endpoint_names = route.endpoint_names if endpoint_name is None else endpoint_name.split()
        route.condition = route.condition if condition is None else condition
        route.is_enabled = route.is_enabled if enabled is None else enabled

        return self.client.iot_hub_resource.begin_create_or_update(
            resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
            resource_name=self.hub_resource.name,
            iot_hub_description=self.hub_resource,
            if_match=self.hub_resource.etag
        )

    def show(self, route_name: str):
        routes = self.hub_resource.properties.routing.routes
        for route in routes:
            if route.name.lower() == route_name.lower():
                return route
        raise ResourceNotFoundError("No route found.")

    def list(self, source_type: Optional[str] = None):
        routes = self.hub_resource.properties.routing.routes
        if source_type:
            return [route for route in routes if route.source.lower() == source_type.lower()]
        return routes

    def delete(self, route_name: Optional[str] = None, source_type: Optional[str] = None):
        routing = self.hub_resource.properties.routing
        if not route_name and not source_type:
            routing.routes = []
        elif route_name:
            routing.routes = [route for route in routing.routes if route.name.lower() != route_name.lower()]
        else:
            routing.routes = [route for route in routing.routes if route.source.lower() != source_type.lower()]

        return self.client.iot_hub_resource.begin_create_or_update(
            resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
            resource_name=self.hub_resource.name,
            iot_hub_description=self.hub_resource,
            if_match=self.hub_resource.etag
        )

    def test(
        self,
        route_name: Optional[str] = None,
        source_type: Optional[str] = None,
        body: Optional[str] = None,
        app_properties: Optional[str] = None,
        system_properties: Optional[str] = None
    ):
        if app_properties:
            app_properties = process_json_arg(content=app_properties, argument_name="app_properties")
        if system_properties:
            system_properties = process_json_arg(content=system_properties, argument_name="system_properties")


        route_message = {
            "body": body,
            "appProperties": app_properties,
            "systemProperties": system_properties
        }

        if route_name:
            route = self.show(route_name)
            test_route_input = {
                "message": route_message,
                "twin": None,
                "route": route
            }
            return self.client.iot_hub_resource.test_route(
                iot_hub_name=self.hub_resource.name,
                resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
                input=test_route_input
            )

        if source_type:
            test_all_routes_input = {
                "routingSource": source_type,
                "message": route_message,
                "twin": None
            }
            return self.client.iot_hub_resource.test_all_routes(
                iot_hub_name=self.hub_resource.name,
                resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
                input=test_all_routes_input
            )

        # for all types, need to test all types one by one
        routes = []
        all_route_types = [
            RouteSourceType.DeviceConnectionStateEvents.value,
            RouteSourceType.DeviceJobLifecycleEvents.value,
            RouteSourceType.DeviceLifecycleEvents.value,
            RouteSourceType.DeviceMessages.value,
            RouteSourceType.DigitalTwinChangeEvents.value,
            RouteSourceType.TwinChangeEvents.value
        ]
        fallback = None
        for type in all_route_types:
            test_all_routes_input = {
                "routingSource": type,
                "message": route_message,
                "twin": None
            }
            result = self.client.iot_hub_resource.test_all_routes(
                iot_hub_name=self.hub_resource.name,
                resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
                input=test_all_routes_input
            ).routes

            # Fallback for if no routes pass
            if len(result) == 1 and result[0].properties.name == "$fallback":
                fallback = result
            else:
                routes.extend(result)

        if len(routes) == 0 and fallback:
            routes = fallback
        return {"routes": routes}

    def show_fallback(self):
        return self.hub_resource.properties.routing.fallback_route

    def set_fallback(self, enabled: bool):
        fallback_route = self.hub_resource.properties.routing.fallback_route
        fallback_route.is_enabled = enabled

        self.client.iot_hub_resource.begin_create_or_update(
            resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
            resource_name=self.hub_resource.name,
            iot_hub_description=self.hub_resource,
            if_match=self.hub_resource.etag
        )
        return self.show_fallback()
