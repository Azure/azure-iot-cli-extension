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
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.sdk.iothub.controlplane.models import RouteProperties, RoutingMessage, TestRouteInput, TestAllRoutesInput


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
        from azext_iot.sdk.iothub.controlplane import IotHubClient
        client = get_mgmt_service_client(self.cmd.cli_ctx, IotHubClient, api_version=self.api_version)

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
            RouteProperties(
                source=source_type,
                name=route_name,
                endpoint_names=endpoint_name.split(),
                condition=('true' if condition is None else condition),
                is_enabled=enabled
            )
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


        route_message = RoutingMessage(
            body=body,
            app_properties=app_properties,
            system_properties=system_properties
        )

        if route_name:
            route = self.show(route_name)
            test_route_input = TestRouteInput(
                message=route_message,
                twin=None,
                route=route
            )
            return self.client.iot_hub_resource.test_route(
                iot_hub_name=self.hub_resource.name,
                resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
                input=test_route_input
            )

        test_all_routes_input = TestAllRoutesInput(
            routing_source=source_type,
            message=route_message,
            twin=None
        )
        return self.client.iot_hub_resource.test_all_routes(
            iot_hub_name=self.hub_resource.name,
            resource_group_name=self.hub_resource.additional_properties['resourcegroup'],
            input=test_all_routes_input
        )

