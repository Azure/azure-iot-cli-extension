# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# TODO: This module will look very different for the PnP refresh.

import pytest
import json
import os

from azext_iot.operations import digitaltwin as subject
from azext_iot.operations.digitaltwin import INTERFACE_KEY_NAME
from azext_iot.constants import PNP_ENDPOINT
from azext_iot.tests.conftest import build_mock_response
from azext_iot.tests.generators import create_req_monitor_events
from knack.util import CLIError
from azext_iot.common.utility import read_file_content

_device_digitaltwin_invoke_command_payload = (
    "test_device_digitaltwin_invoke_command.json"
)
_device_digitaltwin_payload_file = "test_device_digitaltwin_interfaces.json"
_device_digitaltwin_property_update_payload_file = (
    "test_device_digitaltwin_property_update.json"
)
_pnp_show_interface_file = "test_pnp_interface_show.json"
_pnp_list_interface_file = "test_pnp_interface_list.json"
path_iot_hub_monitor_events_entrypoint = (
    "azext_iot.operations.digitaltwin._iot_hub_monitor_events"
)
device_id = "mydevice"
hub_entity = "myhub.azure-devices.net"

# Patch Paths #
path_mqtt_client = "azext_iot.operations._mqtt.mqtt.Client"
path_service_client = "msrest.service_client.ServiceClient.send"
path_ghcs = "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target"
path_pnpcs = "azext_iot.operations.pnp.get_iot_pnp_connection_string"
path_sas = "azext_iot._factory.SasTokenAuthentication"

mock_target = {}
mock_target["entity"] = hub_entity
mock_target["primarykey"] = "rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["secondarykey"] = "aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["policy"] = "iothubowner"
mock_target["subscription"] = "5952cff8-bcd1-4235-9554-af2c0348bf23"
mock_target["location"] = "westus2"
mock_target["sku_tier"] = "Standard"
generic_cs_template = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"

mock_pnptarget = {}
mock_pnptarget["entity"] = PNP_ENDPOINT
mock_pnptarget["primarykey"] = "rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_pnptarget["repository_id"] = "1b10ab39a62946ffada85db3b785b3dd"
mock_pnptarget["policy"] = "43325732479e453093a3d1ae5b95c62e"
generic_pnpcs_template = (
    "HostName={};RepositoryId={};SharedAccessKeyName={};SharedAccessKey={}"
)


def generate_pnpcs(
    pnp=PNP_ENDPOINT,
    repository=mock_pnptarget["repository_id"],
    policy=mock_target["policy"],
    key=mock_target["primarykey"],
):
    return generic_pnpcs_template.format(pnp, repository, policy, key)


def generate_cs(
    hub=hub_entity, policy=mock_target["policy"], key=mock_target["primarykey"]
):
    return generic_cs_template.format(hub, policy, key)


mock_pnptarget["cs"] = generate_pnpcs()
mock_target["cs"] = generate_cs()


def change_dir():
    from inspect import getsourcefile

    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


def generate_device_interfaces_payload():
    change_dir()
    return json.loads(read_file_content(_device_digitaltwin_payload_file))


def generate_pnp_interface_show_payload():
    change_dir()
    return json.loads(read_file_content(_pnp_show_interface_file))


def generate_pnp_interface_list_payload():
    change_dir()
    return json.loads(read_file_content(_pnp_list_interface_file))


def generate_device_digitaltwin_property_update_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _device_digitaltwin_property_update_payload_file)

    return (
        str(read_file_content(_device_digitaltwin_property_update_payload_file)),
        _device_digitaltwin_property_update_payload_file,
    )


def generate_device_digitaltwin_invoke_command_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _device_digitaltwin_invoke_command_payload)

    return (
        str(read_file_content(_device_digitaltwin_invoke_command_payload)),
        _device_digitaltwin_invoke_command_payload,
    )


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker.patch(path_ghcs)
    ghcs.return_value = mock_target
    return ghcs


@pytest.fixture()
def fixture_pnpcs(mocker):
    pnpcs = mocker.patch(path_pnpcs)
    pnpcs.return_value = mock_pnptarget
    return pnpcs


@pytest.fixture()
def fixture_monitor_events_entrypoint(mocker):
    return mocker.patch(path_iot_hub_monitor_events_entrypoint)


class TestDTInterfaceList(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        service_client.return_value = build_mock_response(mocker, request.param, output)
        return service_client

    def test_iot_digitaltwin_interface_list(self, fixture_cmd, serviceclient):
        result = subject.iot_digitaltwin_interface_list(
            fixture_cmd, device_id=device_id, login=mock_target["cs"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert (
            "{}/digitalTwins/{}/interfaces/{}?".format(
                mock_target["entity"], device_id, INTERFACE_KEY_NAME
            )
            in url
        )
        assert json.dumps(result)
        assert len(result["interfaces"]) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_interface_list_error(
        self, fixture_cmd, serviceclient_generic_error, exp
    ):
        with pytest.raises(exp):
            subject.iot_digitaltwin_interface_list(
                fixture_cmd, device_id=device_id, login=mock_target["cs"]
            )


class TestDTCommandList(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_iot_digitaltwin_command_list(self, fixture_cmd, serviceclient):
        result = subject.iot_digitaltwin_command_list(
            fixture_cmd,
            device_id=device_id,
            source_model="public",
            interface="environmentalSensor",
            login=mock_target["cs"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert "/models/" in url
        assert json.dumps(result)
        assert len(result["interfaces"]) == 1
        assert result["interfaces"][0]["name"] == "environmentalSensor"
        assert len(result["interfaces"][0]["commands"]) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_command_list_error(
        self, fixture_cmd, serviceclient_generic_error, exp
    ):
        with pytest.raises(exp):
            subject.iot_digitaltwin_command_list(
                fixture_cmd,
                device_id=device_id,
                source_model="public",
                login=mock_target["cs"],
            )

    @pytest.mark.parametrize("interface, exp", [("inter1", CLIError)])
    def test_iot_digitaltwin_command_list_args_error(
        self, fixture_cmd, serviceclient, interface, exp
    ):
        with pytest.raises(exp):
            subject.iot_digitaltwin_command_list(
                fixture_cmd,
                device_id=device_id,
                interface=interface,
                login=mock_target["cs"],
                source_model="public",
            )


class TestDTPropertiesList(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_interface", [("environmentalSensor")])
    def test_iot_digitaltwin_properties_list(
        self, fixture_cmd, serviceclient, target_interface
    ):
        result = subject.iot_digitaltwin_properties_list(
            fixture_cmd,
            device_id=device_id,
            source_model="public",
            interface=target_interface,
            login=mock_target["cs"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert "/models/" in url
        assert json.dumps(result)
        if target_interface:
            assert len(result["interfaces"]) == 1
            assert result["interfaces"][0]["name"] == "environmentalSensor"
            assert len(result["interfaces"][0]["properties"]) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_properties_list_error(
        self, fixture_cmd, serviceclient_generic_error, exp
    ):
        with pytest.raises(exp):
            subject.iot_digitaltwin_properties_list(
                fixture_cmd,
                device_id=device_id,
                source_model="public",
                login=mock_target["cs"],
            )

    @pytest.mark.parametrize("interface, exp", [("inter1", CLIError)])
    def test_iot_digitaltwin_properties_list_args_error(
        self, fixture_cmd, serviceclient, interface, exp
    ):
        with pytest.raises(exp):
            subject.iot_digitaltwin_properties_list(
                fixture_cmd,
                device_id=device_id,
                interface=interface,
                login=mock_target["cs"],
                source_model="public",
            )


class TestDTPropertyUpdate(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_device_digitaltwin_property_update_payload()),
            (
                generate_device_digitaltwin_property_update_payload(
                    content_from_file=True
                )
            ),
        ],
    )
    def test_iot_digitaltwin_property_update(
        self, fixture_cmd, serviceclient, payload_scenario
    ):

        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(
                read_file_content(_device_digitaltwin_property_update_payload_file)
            )

        subject.iot_digitaltwin_property_update(
            fixture_cmd,
            device_id=device_id,
            interface_payload=payload,
            login=mock_target["cs"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "PATCH"
        assert (
            "{}/digitalTwins/{}/interfaces?".format(mock_target["entity"], device_id)
            in url
        )

    @pytest.mark.parametrize(
        "payload_scenario", [(generate_device_digitaltwin_property_update_payload())]
    )
    def test_iot_digitaltwin_property_update_error(
        self, fixture_cmd, serviceclient_generic_error, payload_scenario
    ):
        with pytest.raises(CLIError):
            subject.iot_digitaltwin_property_update(
                fixture_cmd,
                device_id=device_id,
                interface_payload=payload_scenario[0],
                login=mock_target["cs"],
            )


class TestDTInvokeCommand(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show),
            build_mock_response(mocker, request.param, {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "command_payload",
        [
            (generate_device_digitaltwin_invoke_command_payload()),
            (
                generate_device_digitaltwin_invoke_command_payload(
                    content_from_file=True
                )
            ),
        ],
    )
    def test_iot_digitaltwin_invoke_command(
        self, fixture_cmd, serviceclient, command_payload
    ):

        payload = None
        interface = "environmentalSensor"
        command = "blink"

        # If file path provided
        if not command_payload[0]:
            payload = command_payload[1]
        else:
            payload = str(read_file_content(_device_digitaltwin_invoke_command_payload))

        subject.iot_digitaltwin_invoke_command(
            fixture_cmd,
            device_id=device_id,
            interface=interface,
            command_name=command,
            command_payload=payload,
            login=mock_target["cs"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "POST"
        assert (
            "{}/digitalTwins/{}/interfaces/{}/commands/{}?".format(
                mock_target["entity"], device_id, interface, command
            )
            in url
        )

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def serviceclient_error(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=output),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "command_payload, interface, command",
        [
            (
                generate_device_digitaltwin_invoke_command_payload(),
                "environmentalSensor",
                "blink",
            ),
            (
                generate_device_digitaltwin_invoke_command_payload(
                    content_from_file=True
                ),
                "environmentalSensor",
                "blink",
            ),
            (generate_device_digitaltwin_invoke_command_payload(), "test", "blink"),
            (
                generate_device_digitaltwin_invoke_command_payload(),
                "environmentalSensor",
                "test",
            ),
        ],
    )
    def test_iot_digitaltwin_property_update_error(
        self, fixture_cmd, serviceclient_error, command_payload, interface, command
    ):
        payload = None
        if not command_payload[0]:
            payload = command_payload[1]
        else:
            payload = str(read_file_content(_device_digitaltwin_invoke_command_payload))
        with pytest.raises(CLIError):
            subject.iot_digitaltwin_invoke_command(
                fixture_cmd,
                device_id=device_id,
                interface=interface,
                command_name=command,
                command_payload=payload,
                login=mock_target["cs"],
            )


class TestDTMonitorEvents(object):
    @pytest.mark.parametrize(
        "req",
        [
            (
                create_req_monitor_events(
                    device_id=device_id,
                    interface_name="environmentalSensor",
                    yes=True,
                    properties="all",
                    consumer_group="group1",
                    login=mock_target["cs"],
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id,
                    interface_name="environmentalSensor",
                    yes=False,
                    properties="sys anno",
                    login=mock_target["cs"],
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id,
                    interface_name="environmentalSensor",
                    enqueued_time="5432154321",
                    yes=True,
                    properties="sys",
                    login=mock_target["cs"],
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id,
                    enqueued_time="321321321",
                    content_type="application/json",
                    timeout=100,
                    yes=True,
                    properties="all",
                    login=mock_target["cs"],
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id,
                    timeout=100,
                    yes=True,
                    properties="all",
                    hub_name="myhub",
                    resource_group_name="myrg",
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id,
                    yes=True,
                    properties="all",
                    login=mock_target["cs"],
                )
            ),
            (
                create_req_monitor_events(
                    device_id=device_id, repair=True, login=mock_target["cs"]
                )
            ),
            (create_req_monitor_events(login=mock_target["cs"])),
            (create_req_monitor_events(hub_name="myhub")),
            (
                create_req_monitor_events(
                    device_query="select * from devices", login=mock_target["cs"]
                )
            ),
            (
                create_req_monitor_events(
                    interface_name="environmentalSensor", hub_name="myiothub"
                )
            ),
            (
                create_req_monitor_events(
                    device_id="auxFridgeUnit-*",
                    device_query="select * from devices",
                    interface_name="environmentalSensor",
                    login=mock_target["cs"],
                )
            ),
        ],
    )
    def test_iot_digitaltwin_monitor_events_entrypoint(
        self, fixture_cmd, fixture_monitor_events_entrypoint, req
    ):
        subject.iot_digitaltwin_monitor_events(
            fixture_cmd,
            device_id=req["device_id"],
            device_query=req["device_query"],
            interface=req["interface_name"],
            consumer_group=req["consumer_group"],
            content_type=req["content_type"],
            enqueued_time=req["enqueued_time"],
            timeout=req["timeout"],
            hub_name=req["hub_name"],
            resource_group_name=req["resource_group_name"],
            yes=req["yes"],
            properties=req["properties"],
            repair=req["repair"],
            login=req["login"],
        )

        monitor_events_args = fixture_monitor_events_entrypoint.call_args[1]

        dt_attribute_set = [
            "device_id",
            "device_query",
            "interface_name",
            "consumer_group",
            "enqueued_time",
            "content_type",
            "timeout",
            "login",
            "hub_name",
            "resource_group_name",
            "yes",
            "properties",
            "repair",
        ]
        for attribute in dt_attribute_set:
            if req[attribute]:
                assert monitor_events_args[attribute] == req[attribute]
            else:
                assert not monitor_events_args[attribute]
