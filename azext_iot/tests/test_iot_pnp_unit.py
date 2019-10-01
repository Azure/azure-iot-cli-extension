# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import os

from uuid import uuid4
from azext_iot.operations import pnp as subject
from azext_iot.common.utility import url_encode_str
from knack.util import CLIError
from azure.cli.core.util import read_file_content
from .conftest import fixture_cmd, path_service_client, build_mock_response

_repo_endpoint = "https://{}.{}".format(str(uuid4()), "com")
_repo_id = str(uuid4()).replace("-", "")
_repo_keyname = str(uuid4()).replace("-", "")
_repo_secret = "lMT+wSy8TIzDASRMlhxwpYxG3mWba45YqCFUo6Qngju5uZS9V4tM2yh5pn3zdB0FC3yRx91UnSWjdr/jLutPbg=="
generic_cs_template = (
    "HostName={};RepositoryId={};SharedAccessKeyName={};SharedAccessKey={}"
)
path_ghcs = "azext_iot.operations.pnp.get_iot_pnp_connection_string"
_pnp_create_interface_payload_file = "test_pnp_create_payload_interface.json"
_pnp_create_model_payload_file = "test_pnp_create_payload_model.json"
_pnp_show_interface_file = "test_pnp_interface_show.json"
_pnp_generic_interface_id = "urn:example:interfaces:MXChip:1"
_pnp_generic_model_id = "urn:example:capabilityModels:Mxchip:1"


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker.patch(path_ghcs)
    ghcs.return_value = mock_target
    return ghcs


def generate_cs(
    endpoint=_repo_endpoint, repository=_repo_id, policy=_repo_keyname, key=_repo_secret
):
    return generic_cs_template.format(endpoint, repository, policy, key)


def change_dir():
    from inspect import getsourcefile

    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


mock_target = {}
mock_target["cs"] = generate_cs()
mock_target["policy"] = _repo_keyname
mock_target["primarykey"] = _repo_secret
mock_target["repository_id"] = _repo_id
mock_target["entity"] = _repo_endpoint
mock_target["entity"] = mock_target["entity"].replace("https://", "")
mock_target["entity"] = mock_target["entity"].replace("http://", "")


def generate_pnp_interface_create_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _pnp_create_interface_payload_file)

    return (
        str(read_file_content(_pnp_create_interface_payload_file)),
        _pnp_create_interface_payload_file,
    )


class TestModelRepoInterfaceCreate(object):
    @pytest.fixture(params=[201, 204, 412])
    def serviceclient(self, mocker, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_pnp_interface_create_payload()),
            (generate_pnp_interface_create_payload(content_from_file=True)),
        ],
    )
    def test_interface_create(self, fixture_cmd, serviceclient, payload_scenario):
        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_interface_payload_file))

        subject.iot_pnp_interface_create(
            fixture_cmd, interface_definition=payload, login=mock_target["cs"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_interface_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(data)
        assert headers.get("Authorization")

    @pytest.mark.parametrize(
        "payload_scenario", [(generate_pnp_interface_create_payload())]
    )
    def test_interface_create_error(
        self, fixture_cmd, serviceclient_generic_error, payload_scenario
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_create(
                fixture_cmd,
                login=mock_target["cs"],
                interface_definition=payload_scenario[0],
            )

    @pytest.mark.parametrize(
        "payload_scenario, exp", [(generate_pnp_interface_create_payload(), CLIError)]
    )
    def test_interface_create_invalid_args(self, serviceclient, payload_scenario, exp):
        with pytest.raises(exp):
            subject.iot_pnp_interface_create(
                fixture_cmd, interface_definition=payload_scenario
            )

    def test_interface_create_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_interface_payload_file))
        payload = json.loads(payload)
        del payload["@id"]
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_create(
                fixture_cmd, login=mock_target["cs"], interface_definition=payload
            )


class TestModelRepoInterfaceUpdate(object):
    @pytest.fixture(params=[(200, 201), (200, 204), (200, 412)])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        payload = {
            "continuationToken": "null",
            "results": [
                {
                    "comment": "",
                    "createdOn": "2019-07-09T07:46:06.044161+00:00",
                    "description": "",
                    "displayName": "MXChip 1",
                    "etag": '"41006e67-0000-0800-0000-5d2501b80000"',
                    "modelName": "example:interfaces:MXChip",
                    "publisherId": "aabbaabb-aabb-aabb-aabb-aabbaabbaabb",
                    "publisherName": "microsoft.com",
                    "type": "Interface",
                    "updatedOn": "2019-07-09T21:06:00.072063+00:00",
                    "urnId": "urn:example:interfaces:MXChip:1",
                    "version": 1,
                }
            ],
        }
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=payload),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            generate_pnp_interface_create_payload(),
            generate_pnp_interface_create_payload(content_from_file=True),
        ],
    )
    def test_interface_update(self, fixture_cmd, serviceclient, payload_scenario):
        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_interface_payload_file))

        subject.iot_pnp_interface_update(
            fixture_cmd,
            interface_definition=payload,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_interface_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(data)
        assert headers.get("Authorization")

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_pnp_interface_create_payload()),
            (generate_pnp_interface_create_payload(content_from_file=True)),
        ],
    )
    def test_model_update_error(
        self, fixture_cmd, serviceclient_generic_error, payload_scenario
    ):
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_interface_payload_file))
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_update(
                fixture_cmd,
                interface_definition=payload,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )

    @pytest.mark.parametrize(
        "payload_scenario, exp", [(generate_pnp_interface_create_payload(), CLIError)]
    )
    def test_interface_update_invalid_args(self, serviceclient, payload_scenario, exp):
        with pytest.raises(exp):
            subject.iot_pnp_interface_update(
                fixture_cmd, interface_definition=payload_scenario
            )

    def test_interface_update_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_interface_payload_file))
        payload = json.loads(payload)
        payload["@id"] = "fake_invalid_id"
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_update(
                fixture_cmd,
                interface_definition=payload,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoInterfacePublish(object):
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
                    "displayName": "MXChip 1",
                    "etag": '"41006e67-0000-0800-0000-5d2501b80000"',
                    "modelName": "example:interfaces:MXChip",
                    "publisherId": "aabbaabb-aabb-aabb-aabb-aabbaabbaabb",
                    "publisherName": "microsoft.com",
                    "type": "Interface",
                    "updatedOn": "2019-07-09T21:06:00.072063+00:00",
                    "urnId": "urn:example:interfaces:MXChip:1",
                    "version": 1,
                }
            ],
        }
        payload_show = {
            "@id": "urn:example:interfaces:MXChip:1",
            "@type": "Interface",
            "displayName": "MXChip 1",
            "contents": [
                {
                    "@type": "Property",
                    "displayName": "Die Number",
                    "name": "dieNumber",
                    "schema": "double",
                }
            ],
            "@context": "http://azureiot.com/v1/contexts/Interface.json",
        }
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=payload_list),
            build_mock_response(mocker, request.param[1], payload=payload_show),
            build_mock_response(mocker, request.param[2], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_interface", [(_pnp_generic_interface_id)])
    def test_interface_publish(self, fixture_cmd, serviceclient, target_interface):
        subject.iot_pnp_interface_publish(
            fixture_cmd, interface=target_interface, login=mock_target["cs"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_interface_id, plus=True)
            )
            in url
        )
        assert json.loads(data)["@id"] == _pnp_generic_interface_id
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_interface", [("acv.17")])
    def test_interface_publish_error(
        self, fixture_cmd, serviceclient_generic_error, target_interface
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_publish(
                fixture_cmd, interface=target_interface, login=mock_target["cs"]
            )


class TestModelRepoInterfaceShow(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        payload = {
            "@id": "urn:example:interfaces:MXChip:1",
            "@type": "Interface",
            "displayName": "MXChip 1",
            "contents": [
                {
                    "@type": "Property",
                    "displayName": "Die Number",
                    "name": "dieNumber",
                    "schema": "double",
                }
            ],
            "@context": "http://azureiot.com/v1/contexts/Interface.json",
        }
        service_client.return_value = build_mock_response(
            mocker, request.param, payload
        )
        return service_client

    @pytest.mark.parametrize("target_interface", [(_pnp_generic_interface_id)])
    def test_interface_show(self, fixture_cmd, serviceclient, target_interface):
        result = subject.iot_pnp_interface_show(
            fixture_cmd,
            interface=target_interface,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "GET"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_interface_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(result)
        assert headers.get("Authorization")

    @pytest.fixture(params=[200])
    def serviceclientemptyresult(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("target_interface", [(_pnp_generic_interface_id)])
    def test_interface_show_error(
        self, fixture_cmd, serviceclientemptyresult, target_interface
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_show(
                fixture_cmd,
                interface=target_interface,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoInterfaceList(object):
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
                    "displayName": "MXChip 1",
                    "etag": '"41006e67-0000-0800-0000-5d2501b80000"',
                    "modelName": "example:interfaces:MXChip",
                    "publisherId": "aabbaabb-aabb-aabb-aabb-aabbaabbaabb",
                    "publisherName": "microsoft.com",
                    "type": "Interface",
                    "updatedOn": "2019-07-09T21:06:00.072063+00:00",
                    "urnId": "urn:example:interfaces:MXChip:1",
                    "version": 1,
                }
            ],
        }
        serviceclient.return_value = build_mock_response(mocker, request.param, payload)
        return serviceclient

    def test_interface_list(self, fixture_cmd, service_client):
        result = subject.iot_pnp_interface_list(
            fixture_cmd,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = service_client.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "POST"
        assert "{}/models/search?".format(_repo_endpoint) in url
        assert "repositoryId={}".format(_repo_id) in url
        assert len(result) == 1
        assert headers.get("Authorization")

    def test_interface_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_list(
                fixture_cmd,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoInterfaceDelete(object):
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("target_interface", [(_pnp_generic_interface_id)])
    def test_interface_delete(self, fixture_cmd, serviceclient, target_interface):
        subject.iot_pnp_interface_delete(
            fixture_cmd,
            interface=target_interface,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "DELETE"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_interface_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_interface", [("acv.17")])
    def test_model_delete_error(
        self, fixture_cmd, serviceclient_generic_error, target_interface
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_interface_delete(
                fixture_cmd,
                interface=target_interface,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


def generate_pnp_model_create_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _pnp_create_model_payload_file)

    return (
        str(read_file_content(_pnp_create_model_payload_file)),
        _pnp_create_model_payload_file,
    )


class TestModelRepoModelCreate(object):
    @pytest.fixture(params=[201, 204, 412])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_pnp_model_create_payload()),
            (generate_pnp_model_create_payload(content_from_file=True)),
        ],
    )
    def test_model_create(self, fixture_cmd, serviceclient, payload_scenario):

        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))

        subject.iot_pnp_model_create(
            fixture_cmd,
            model_definition=payload,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(data)
        assert headers.get("Authorization")

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_pnp_model_create_payload()),
            (generate_pnp_model_create_payload(content_from_file=True)),
        ],
    )
    def test_model_create_error(
        self, fixture_cmd, serviceclient_generic_error, payload_scenario
    ):
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))
        with pytest.raises(CLIError):
            subject.iot_pnp_model_create(
                fixture_cmd,
                model_definition=payload,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )

    @pytest.mark.parametrize(
        "payload_scenario, exp", [(generate_pnp_model_create_payload(), CLIError)]
    )
    def test_model_create_invalid_args(self, serviceclient, payload_scenario, exp):
        with pytest.raises(exp):
            subject.iot_pnp_model_create(fixture_cmd, model_definition=payload_scenario)

    def test_model_create_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_model_payload_file))
        payload = json.loads(payload)
        del payload["@id"]
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            subject.iot_pnp_model_create(
                fixture_cmd, login=mock_target["cs"], model_definition=payload
            )


class TestModelRepoModelUpdate(object):
    @pytest.fixture(params=[(200, 201), (200, 204), (200, 412)])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
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
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=payload),
            build_mock_response(mocker, request.param[1], {}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            generate_pnp_model_create_payload(),
            generate_pnp_model_create_payload(content_from_file=True),
        ],
    )
    def test_model_update(self, fixture_cmd, serviceclient, payload_scenario):

        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))

        subject.iot_pnp_model_update(
            fixture_cmd,
            model_definition=payload,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(data)
        assert headers.get("Authorization")

    @pytest.mark.parametrize(
        "payload_scenario",
        [
            (generate_pnp_model_create_payload()),
            (generate_pnp_model_create_payload(content_from_file=True)),
        ],
    )
    def test_model_update_error(
        self, fixture_cmd, serviceclient_generic_error, payload_scenario
    ):
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_pnp_create_model_payload_file))
        with pytest.raises(CLIError):
            subject.iot_pnp_model_update(
                fixture_cmd,
                model_definition=payload,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )

    @pytest.mark.parametrize(
        "payload_scenario, exp", [(generate_pnp_model_create_payload(), CLIError)]
    )
    def test_model_update_invalid_args(self, serviceclient, payload_scenario, exp):
        with pytest.raises(exp):
            subject.iot_pnp_model_update(fixture_cmd, model_definition=payload_scenario)

    def test_model_update_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_model_payload_file))
        payload = json.loads(payload)
        payload["@id"] = "fake_invalid_id"
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            subject.iot_pnp_model_update(
                fixture_cmd,
                model_definition=payload,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoModelPublish(object):
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
            fixture_cmd, model=target_model, login=mock_target["cs"]
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data
        headers = args[0][0].headers

        assert method == "PUT"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_model_id, plus=True)
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
                fixture_cmd, model=target_model, login=mock_target["cs"]
            )


class TestModelRepoModelShow(object):
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
            model=target_model,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "GET"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert json.dumps(result)
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_model", [("acv:17")])
    def test_model_show_error(
        self, fixture_cmd, serviceclient_generic_error, target_model
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_show(
                fixture_cmd,
                model=target_model,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
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
                model=target_model,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoModelList(object):
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
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = service_client.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "POST"
        assert (
            "{}/models/search?repositoryId={}".format(_repo_endpoint, _repo_id) in url
        )
        assert len(result) == 1
        assert headers.get("Authorization")

    def test_model_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_list(
                fixture_cmd,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )


class TestModelRepoModelDelete(object):
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_delete(self, fixture_cmd, serviceclient, target_model):
        subject.iot_pnp_model_delete(
            fixture_cmd,
            model=target_model,
            repo_endpoint=mock_target["entity"],
            repo_id=mock_target["repository_id"],
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "DELETE"
        assert (
            "{}/models/{}?".format(
                _repo_endpoint, url_encode_str(_pnp_generic_model_id, plus=True)
            )
            in url
        )
        assert "repositoryId={}".format(_repo_id) in url
        assert headers.get("Authorization")

    @pytest.mark.parametrize("target_model", [("acv.17")])
    def test_model_delete_error(
        self, fixture_cmd, serviceclient_generic_error, target_model
    ):
        with pytest.raises(CLIError):
            subject.iot_pnp_model_delete(
                fixture_cmd,
                model=target_model,
                repo_endpoint=mock_target["entity"],
                repo_id=mock_target["repository_id"],
            )
