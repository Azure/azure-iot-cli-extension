# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json

from azext_iot.pnp import commands_api as subject
from azext_iot.constants import PNP_REPO_ENDPOINT
from azext_iot.common.utility import url_encode_str, read_file_content
from knack.util import CLIError
from ..conftest import fixture_cmd, path_service_client, build_mock_response

_repo_endpoint = PNP_REPO_ENDPOINT

generic_cs_template = (
    "HostName={};RepositoryId={};SharedAccessKeyName={};SharedAccessKey={}"
)
_pnp_create_interface_payload_file = "test_pnp_create_payload_interface.json"
_pnp_create_model_payload_file = "test_pnp_create_payload_model.json"
_pnp_show_interface_file = "test_pnp_interface_show.json"
_pnp_generic_interface_id = "urn:example:interfaces:MXChip:1"
_pnp_generic_model_id = "urn:example:capabilityModels:Mxchip:1"

mock_target = {}


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker
    ghcs.return_value = mock_target
    return ghcs


def generate_pnp_model_create_payload(content_from_file=False):
    if content_from_file:
        return (None, _pnp_create_model_payload_file)

    return (
        str(read_file_content(_pnp_create_model_payload_file)),
        _pnp_create_model_payload_file,
    )


@pytest.mark.usefixtures("set_cwd")
class xTestModelRepoModelCreate(object):
    @pytest.fixture(params=[201, 204, 412])
    def serviceclient(self, mocker, fixture_ghcs, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "content_from_file",
        [
            True,
            False,
        ],
    )
    def test_model_create(self, fixture_cmd, serviceclient, content_from_file, set_cwd):

        payload = None
        payload_scenario = generate_pnp_model_create_payload(content_from_file)
        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))

        model_id = json.loads(payload)['@id']
        subject.iot_pnp_model_create(
            cmd=fixture_cmd,
            model_id=model_id,
            model=payload,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "/models/{}?".format(
                url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert json.dumps(data)
        assert headers.get("Authorization")

    @pytest.mark.parametrize(
        "content_from_file",
        [
            True,
            False
        ],
    )
    def test_model_create_error(
        self, fixture_cmd, serviceclient_generic_error, content_from_file
    ):
        payload = None
        payload_scenario = generate_pnp_model_create_payload(content_from_file)
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))

        model_id = json.loads(payload)['@id']
        with pytest.raises(CLIError):
            subject.iot_pnp_model_create(
                fixture_cmd,
                model_id=model_id,
                model=payload,
            )

    @pytest.mark.parametrize(
        "model_id, exp", [('test-id', CLIError)]
    )
    def test_model_create_invalid_args(self, serviceclient, payload_scenario, model_id, exp):
        payload_scenario = generate_pnp_model_create_payload()
        with pytest.raises(exp):
            subject.iot_pnp_model_create(fixture_cmd, model_id=model_id, model=payload_scenario)

    def test_model_create_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_model_payload_file))
        payload = json.loads(payload)
        del payload["@id"]
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            subject.iot_pnp_model_create(
                fixture_cmd, model_id=None, model=payload
            )


class xTestModelRepoModelPublish(object):
    @pytest.fixture(params=[(200, 200, 201), (200, 200, 204), (200, 200, 412)])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        payload_list = {
            "continuationToken": "null",
            "results": [
                {
                    "comment": "",
                    "createdOn": "2019-07-09T07:46:06.044161+00:00",
                    "description": "",
                    "displayName": "Mxchip 1",
                    "etag": '"41006e67-0000-0800-0000-5d2501b80000"',
                    "modelName": "example:capabilityModels:Mxchip",
                    "publisherId": "aabbaabb-aabb-aabb-aabb-aabbaabbaabb",
                    "publisherName": "microsoft.com",
                    "type": "CapabilityModel",
                    "updatedOn": "2019-07-09T21:06:00.072063+00:00",
                    "urnId": "urn:example:capabilityModels:Mxchip:1",
                    "version": 1,
                }
            ],
        }
        payload_show = {
            "@id": "urn:example:capabilityModels:Mxchip:1",
            "@type": "CapabilityModel",
            "displayName": "Mxchip 1",
            "implements": [
                {"schema": "urn:example:interfaces:MXChip:1", "name": "MXChip1"}
            ],
            "@context": "http://azureiot.com/v1/contexts/CapabilityModel.json",
        }
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=payload_list),
            build_mock_response(mocker, request.param[1], payload=payload_show),
            build_mock_response(mocker, request.param[2], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_publish(self, fixture_cmd, serviceclient, target_model):
        subject.iot_pnp_model_publish(
            fixture_cmd, model_id=target_model,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "/models/{}?".format(
                url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert json.loads(data)["@id"] == _pnp_generic_model_id
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_model", [("acv.17")])
    def test_model_publish_error(
        self, fixture_cmd, serviceclient_generic_error, target_model
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_publish(
                fixture_cmd, model_id=target_model,
            )


class xTestModelRepoModelShow(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        payload = {
            "@id": "urn:example:capabilityModels:Mxchip:1",
            "@type": "CapabilityModel",
            "displayName": "Mxchip 1",
            "implements": [
                {"schema": "urn:example:interfaces:MXChip:1", "name": "MXChip1"}
            ],
            "@context": "http://azureiot.com/v1/contexts/CapabilityModel.json",
        }
        service_client.return_value = build_mock_response(
            mocker, request.param, payload=payload
        )
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_show(self, fixture_cmd, serviceclient, target_model):
        result = subject.iot_pnp_model_show(
            fixture_cmd,
            model_id=target_model
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "GET"
        assert (
            "/models/{}?".format(
                url_encode_str(target_model, plus=True)
            )
            in url
        )
        assert json.dumps(result)
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_model", [("acv:17")])
    def test_model_show_error(
        self, fixture_cmd, serviceclient_generic_error, target_model
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_show(
                fixture_cmd,
                model_id=target_model
            )

    @pytest.fixture(params=[200])
    def serviceclientemptyresult(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_show_no_result(
        self, fixture_cmd, serviceclientemptyresult, target_model
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_show(
                fixture_cmd,
                model_id=target_model,
            )


class xTestModelRepoModelList(object):
    @pytest.fixture(params=[200])
    def service_client(self, mocker, fixture_ghcs, request):
        serviceclient = mocker.patch(path_service_client)
        payload = {
            "continuationToken": "null",
            "results": [
                {
                    "comment": "",
                    "createdOn": "2019-07-09T07:46:06.044161+00:00",
                    "description": "",
                    "displayName": "Mxchip 1",
                    "etag": '"41006e67-0000-0800-0000-5d2501b80000"',
                    "modelName": "example:capabilityModels:Mxchip",
                    "publisherId": "aabbaabb-aabb-aabb-aabb-aabbaabbaabb",
                    "publisherName": "microsoft.com",
                    "type": "CapabilityModel",
                    "updatedOn": "2019-07-09T21:06:00.072063+00:00",
                    "urnId": "urn:example:capabilityModels:Mxchip:1",
                    "version": 1,
                }
            ],
        }
        serviceclient.return_value = build_mock_response(mocker, request.param, payload)
        return serviceclient

    def test_model_list(self, fixture_cmd, service_client):
        result = subject.iot_pnp_model_list(
            fixture_cmd,
        )
        args = service_client.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "POST"
        assert "/models/search?" in url
        assert len(result) == 1
        assert headers.get("Authorization")

    def test_model_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_list(
                fixture_cmd,
            )
