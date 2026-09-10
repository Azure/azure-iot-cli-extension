# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

import azext_iot.iothub.commands_message_route as subject

logging.disable(logging.CRITICAL)

hub_name = "hubname"
hub_rg = "hubrg"
generic_response = {"result": "ok"}

iot_hub_providers_path = "azext_iot.iothub.providers"
path_find_resource = f"{iot_hub_providers_path}.discovery.IotHubDiscovery.find_resource"
handle_service_exception_path = f"{iot_hub_providers_path}.message_route.handle_service_exception"


def _routes():
    return [
        {
            "source": "DeviceMessages",
            "name": "route1",
            "endpointNames": ["ep1"],
            "condition": "true",
            "isEnabled": True,
        },
        {
            "source": "TwinChangeEvents",
            "name": "route2",
            "endpointNames": ["ep2"],
            "condition": "true",
            "isEnabled": False,
        },
    ]


@pytest.fixture()
def fixture_route_ops(mocker):
    find_resource = mocker.patch(path_find_resource, autospec=True)

    hub_mock = {
        "name": "test-hub",
        "etag": "test-etag",
        "resourcegroup": "test-rg",
        "subscriptionid": "test-sub",
        "properties": {
            "routing": {
                "routes": _routes(),
                "fallbackRoute": {"name": "$fallback", "isEnabled": True},
            }
        },
    }

    def initialize_mock_client(self, *args):
        self.client = mocker.MagicMock()
        self.client.begin_create_or_update.return_value = generic_response
        return hub_mock

    find_resource.side_effect = initialize_mock_client
    yield hub_mock


class TestMessageRouteCreate:
    def test_create(self, fixture_route_ops):
        result = subject.message_route_create(
            cmd=None,
            hub_name=hub_name,
            route_name="newroute",
            source_type="DeviceMessages",
            endpoint_name="ep1 ep2",
            enabled=True,
            condition="true",
            resource_group_name=hub_rg,
        )
        assert result == generic_response
        routes = fixture_route_ops["properties"]["routing"]["routes"]
        assert any(r["name"] == "newroute" and r["endpointNames"] == ["ep1", "ep2"] for r in routes)

    def test_create_error(self, fixture_route_ops, mocker):
        handler = mocker.patch(handle_service_exception_path)
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.begin_create_or_update.side_effect = HttpResponseError("boom")
        provider.create(
            route_name="r", source_type="DeviceMessages", endpoint_name="ep", enabled=True, condition="true"
        )
        handler.assert_called_once()


class TestMessageRouteUpdate:
    def test_update(self, fixture_route_ops):
        result = subject.message_route_update(
            cmd=None,
            hub_name=hub_name,
            route_name="route1",
            source_type="TwinChangeEvents",
            endpoint_name="epX",
            enabled=False,
            condition="false",
            resource_group_name=hub_rg,
        )
        assert result == generic_response

    def test_update_defaults_kept(self, fixture_route_ops):
        result = subject.message_route_update(
            cmd=None,
            hub_name=hub_name,
            route_name="route1",
            resource_group_name=hub_rg,
        )
        assert result == generic_response

    def test_update_error(self, fixture_route_ops, mocker):
        handler = mocker.patch(handle_service_exception_path)
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.begin_create_or_update.side_effect = HttpResponseError("boom")
        provider.update(route_name="route1", source_type="DeviceMessages")
        handler.assert_called_once()


class TestMessageRouteShow:
    def test_show(self, fixture_route_ops):
        result = subject.message_route_show(
            cmd=None, hub_name=hub_name, route_name="ROUTE1", resource_group_name=hub_rg
        )
        assert result["name"] == "route1"

    def test_show_not_found(self, fixture_route_ops):
        with pytest.raises(ResourceNotFoundError):
            subject.message_route_show(
                cmd=None, hub_name=hub_name, route_name="missing", resource_group_name=hub_rg
            )


class TestMessageRouteList:
    def test_list_all(self, fixture_route_ops):
        result = subject.message_route_list(cmd=None, hub_name=hub_name, resource_group_name=hub_rg)
        assert len(result) == 2

    def test_list_filtered(self, fixture_route_ops):
        result = subject.message_route_list(
            cmd=None, hub_name=hub_name, source_type="DeviceMessages", resource_group_name=hub_rg
        )
        assert len(result) == 1
        assert result[0]["name"] == "route1"


class TestMessageRouteDelete:
    def test_delete_by_name(self, fixture_route_ops):
        result = subject.message_route_delete(
            cmd=None, hub_name=hub_name, route_name="route1", resource_group_name=hub_rg
        )
        assert result == generic_response
        routes = fixture_route_ops["properties"]["routing"]["routes"]
        assert all(r["name"] != "route1" for r in routes)

    def test_delete_by_source(self, fixture_route_ops):
        result = subject.message_route_delete(
            cmd=None, hub_name=hub_name, source_type="DeviceMessages", resource_group_name=hub_rg
        )
        assert result == generic_response
        routes = fixture_route_ops["properties"]["routing"]["routes"]
        assert all(r["source"] != "DeviceMessages" for r in routes)

    def test_delete_all(self, fixture_route_ops):
        result = subject.message_route_delete(cmd=None, hub_name=hub_name, resource_group_name=hub_rg)
        assert result == generic_response
        assert fixture_route_ops["properties"]["routing"]["routes"] == []

    def test_delete_error(self, fixture_route_ops, mocker):
        handler = mocker.patch(handle_service_exception_path)
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.begin_create_or_update.side_effect = HttpResponseError("boom")
        provider.delete(route_name="route1")
        handler.assert_called_once()


class TestMessageRouteTest:
    def test_test_by_route_name(self, fixture_route_ops, mocker):
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.test_route.return_value = {"result": []}
        result = provider.test(route_name="route1", app_properties='{"a":"b"}', system_properties='{"c":"d"}')
        provider.discovery.client.test_route.assert_called_once()
        assert result == {"result": []}

    def test_test_command_wrapper(self, fixture_route_ops, mocker):
        from azext_iot.iothub.providers.message_route import MessageRoute

        mocker.patch.object(
            MessageRoute, "test", return_value={"routes": []}
        )
        result = subject.message_route_test(
            cmd=None,
            hub_name=hub_name,
            route_name="route1",
            resource_group_name=hub_rg,
        )
        assert result == {"routes": []}

    def test_test_by_source(self, fixture_route_ops, mocker):
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.test_all_routes.return_value = {"routes": []}
        provider.test(source_type="DeviceMessages")
        provider.discovery.client.test_all_routes.assert_called_once()

    def test_test_all_types_with_routes(self, fixture_route_ops):
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.test_all_routes.return_value = {
            "routes": [{"properties": {"name": "route1"}}]
        }
        result = provider.test()
        assert len(result["routes"]) >= 1

    def test_test_all_types_fallback(self, fixture_route_ops):
        from azext_iot.iothub.providers.message_route import MessageRoute

        provider = MessageRoute(cmd=None, hub_name=hub_name, rg=hub_rg)
        provider.discovery.client.test_all_routes.return_value = {
            "routes": [{"properties": {"name": "$fallback"}}]
        }
        result = provider.test()
        assert result["routes"][0]["properties"]["name"] == "$fallback"


class TestMessageFallbackRoute:
    def test_show_fallback(self, fixture_route_ops):
        result = subject.message_fallback_route_show(
            cmd=None, hub_name=hub_name, resource_group_name=hub_rg
        )
        assert result["name"] == "$fallback"

    def test_set_fallback(self, fixture_route_ops):
        result = subject.message_fallback_route_set(
            cmd=None, hub_name=hub_name, enabled=False, resource_group_name=hub_rg
        )
        assert result["isEnabled"] is False


class TestCommonEnumLists:
    def test_endpoint_type_list(self):
        from azext_iot.iothub.common import EndpointType

        values = EndpointType.list()
        assert "eventhub" in values
        assert len(values) == len(list(EndpointType))

    def test_route_source_type_list(self):
        from azext_iot.iothub.common import RouteSourceType

        values = RouteSourceType.list()
        assert "devicemessages" in values
        assert len(values) == len(list(RouteSourceType))


class TestCommandMapTransforms:
    def test_endpoint_update_result_transform(self, mocker):
        from azext_iot.iothub.command_map import EndpointUpdateResultTransform

        transform = EndpointUpdateResultTransform(mocker.MagicMock())
        result = {"properties": {"routing": {"endpoints": ["ep"]}}}
        mocker.patch(
            "azext_iot.iothub.command_map.LongRunningOperation.__call__",
            return_value=result,
        )
        assert transform("poller") == ["ep"]

    def test_route_update_result_transform(self, mocker):
        from azext_iot.iothub.command_map import RouteUpdateResultTransform

        transform = RouteUpdateResultTransform(mocker.MagicMock())
        result = {"properties": {"routing": {"routes": ["r"]}}}
        mocker.patch(
            "azext_iot.iothub.command_map.LongRunningOperation.__call__",
            return_value=result,
        )
        assert transform("poller") == ["r"]
