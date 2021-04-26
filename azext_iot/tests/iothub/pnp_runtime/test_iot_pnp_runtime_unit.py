# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
import responses
import json
from random import randint
from knack.cli import CLIError
from azext_iot.iothub import commands_pnp_runtime as subject
from azext_iot.tests.conftest import mock_target
from azext_iot.tests.generators import generate_generic_id


device_id = generate_generic_id()
command_id = generate_generic_id()
component_id = generate_generic_id()
generic_result = json.dumps({"result": generate_generic_id()})


class TestPnPRuntimeInvokeCommand(object):
    @pytest.fixture(params=[201])
    def service_client_root(self, mocked_response, fixture_ghcs, request):
        # Root level device command mock
        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/commands/{}".format(
                mock_target["entity"], device_id, command_id
            ),
            body=generic_result,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.metadata = request.param
        yield mocked_response

    @pytest.fixture(params=[201])
    def service_client_component(self, mocked_response, fixture_ghcs, request):
        # Component level device command mock
        mocked_response.add(
            method=responses.POST,
            url="https://{}/digitaltwins/{}/components/{}/commands/{}".format(
                mock_target["entity"], device_id, component_id, command_id
            ),
            body=generic_result,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.metadata = request.param
        yield mocked_response

    @pytest.mark.parametrize(
        "request_payload, arbitrary_timeout",
        [
            ("{}", randint(10, 30)),
            (json.dumps({"key": str(generate_generic_id())}), None),
        ],
    )
    def test_pnp_runtime_invoke_root_command(
        self, fixture_cmd, service_client_root, request_payload, arbitrary_timeout
    ):
        result = subject.invoke_device_command(
            cmd=fixture_cmd,
            device_id=device_id,
            command_name=command_id,
            connect_timeout=arbitrary_timeout,
            response_timeout=arbitrary_timeout,
            payload=request_payload,
            hub_name=mock_target["entity"],
        )

        self._assert_common_attributes(
            request_payload=request_payload,
            executed_client=service_client_root,
            result=result,
            connect_timeout=arbitrary_timeout,
            response_timeout=arbitrary_timeout,
        )

    @pytest.mark.parametrize(
        "request_payload, arbitrary_timeout",
        [
            ("{}", randint(10, 30)),
            (json.dumps({"key": str(generate_generic_id())}), None),
        ],
    )
    def test_pnp_runtime_invoke_component_command(
        self, fixture_cmd, service_client_component, request_payload, arbitrary_timeout
    ):
        result = subject.invoke_device_command(
            cmd=fixture_cmd,
            device_id=device_id,
            command_name=command_id,
            connect_timeout=arbitrary_timeout,
            response_timeout=arbitrary_timeout,
            payload=request_payload,
            hub_name=mock_target["entity"],
            component_path=component_id,
        )

        self._assert_common_attributes(
            request_payload=request_payload,
            executed_client=service_client_component,
            result=result,
            connect_timeout=arbitrary_timeout,
            response_timeout=arbitrary_timeout,
        )

    def test_pnp_runtime_invoke_command_error(
        self,
        fixture_cmd,
        service_client_generic_errors,
    ):
        with pytest.raises(CLIError):
            subject.invoke_device_command(
                cmd=fixture_cmd,
                device_id=device_id,
                command_name=command_id,
                payload=json.dumps({}),
                hub_name=mock_target["entity"],
            )

        with pytest.raises(CLIError):
            subject.invoke_device_command(
                cmd=fixture_cmd,
                device_id=device_id,
                command_name=command_id,
                payload=json.dumps({}),
                hub_name=mock_target["entity"],
                component_path=component_id,
            )

    def _assert_common_attributes(
        self,
        request_payload,
        executed_client,
        result,
        connect_timeout=None,
        response_timeout=None,
    ):
        if connect_timeout:
            assert (
                "connectTimeoutInSeconds={}".format(connect_timeout)
                in executed_client.calls[0].request.url
            )

        if response_timeout:
            assert (
                "responseTimeoutInSeconds={}".format(response_timeout)
                in executed_client.calls[0].request.url
            )

        assert request_payload == executed_client.calls[0].request.body
        assert (
            executed_client.calls[0].request.headers["Content-Type"]
            == "application/json; charset=utf-8"
        )

        assert result["payload"] == json.loads(generic_result)
        assert result["status"] == str(executed_client.metadata)


class TestPnPRuntimeShowDigitalTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, fixture_ghcs, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                mock_target["entity"],
                device_id,
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_pnp_runtime_show_digital_twin(self, fixture_cmd, service_client):
        result = subject.get_digital_twin(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
        )

        # Validates simple endpoint behavior.
        # The request pattern is validated via responses mock.
        assert result == json.loads(generic_result)


class TestPnPRuntimeUpdateDigitalTwin(object):
    @pytest.fixture
    def service_client(self, mocked_response, fixture_ghcs, request):
        mocked_response.add(
            method=responses.PATCH,
            url="https://{}/digitaltwins/{}".format(
                mock_target["entity"],
                device_id,
            ),
            body=None,
            status=202,
            content_type="application/json",
            match_querystring=False,
        )

        # The command currently will GET a fresh view of the digital twin
        # because the update operation does not return anything.
        mocked_response.add(
            method=responses.GET,
            url="https://{}/digitaltwins/{}".format(
                mock_target["entity"],
                device_id,
            ),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "request_json_patch, etag",
        [
            (
                '[{"op":"remove", "path":"/thermostat1/targetTemperature"}, '
                '{"op":"add", "path":"/thermostat2/targetTemperature", "value": 22}]',
                generate_generic_id(),
            ),
            (
                '{"op":"add", "path":"/thermostat1/targetTemperature", "value": 54}',
                None,
            ),
        ],
    )
    def test_pnp_runtime_update_digital_twin(
        self, fixture_cmd, service_client, request_json_patch, etag
    ):
        json_patch = json.loads(request_json_patch)

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        expected_request_body = json.dumps(json_patch_collection)

        result = subject.patch_digital_twin(
            cmd=fixture_cmd,
            device_id=device_id,
            hub_name=mock_target["entity"],
            json_patch=request_json_patch,
            etag=etag,
        )

        # First call for patch
        patch_request = service_client.calls[0].request
        assert patch_request.body == expected_request_body
        assert patch_request.headers["If-Match"] == etag if etag else "*"

        # Result from get twin
        assert result == json.loads(generic_result)
