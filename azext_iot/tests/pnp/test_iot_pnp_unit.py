# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json

from azext_iot.pnp import commands_api as dataplane, commands_repository as repo
from azext_iot.pnp.common import RoleIdentifier
from azext_iot.common.utility import url_encode_str, read_file_content
from knack.util import CLIError
from ..conftest import fixture_cmd, path_service_client, build_mock_response


_pnp_create_model_payload_file = "test_pnp_create_payload_model.json"
_pnp_generic_model_id = "urn:example:capabilityModels:Mxchip:1"

mock_target = {}


def generate_pnp_model_create_payload(content_from_file=False):
    if content_from_file:
        return (None, _pnp_create_model_payload_file)

    return (
        str(read_file_content(_pnp_create_model_payload_file)),
        _pnp_create_model_payload_file,
    )


@pytest.mark.usefixtures("set_cwd")
class TestModelRepoModelCreate(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize(
        "content_from_file", [True, False],
    )
    def test_model_create(self, fixture_cmd, serviceclient, content_from_file, set_cwd):

        payload = None
        payload_scenario = generate_pnp_model_create_payload(content_from_file)
        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        payload = str(read_file_content(_pnp_create_model_payload_file))

        model_id = json.loads(payload)["@id"]
        dataplane.iot_pnp_model_create(
            cmd=fixture_cmd, model=payload,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = args[0][0].data

        assert method == "PUT"
        assert "/models/{}?".format(url_encode_str(model_id, plus=True)) in url
        assert json.dumps(data)

    @pytest.mark.parametrize(
        "content_from_file", [True, False],
    )
    def test_model_create_error(
        self, fixture_cmd, serviceclient_generic_error, content_from_file
    ):
        payload = None
        payload_scenario = generate_pnp_model_create_payload(content_from_file)
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        payload = str(read_file_content(_pnp_create_model_payload_file))

        payload = json.loads(payload)
        del payload["@id"]
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            dataplane.iot_pnp_model_create(
                fixture_cmd, model=payload,
            )

    @pytest.mark.parametrize("model_id, exp", [("", CLIError)])
    def test_model_create_invalid_args(self, serviceclient, model_id, exp):
        with pytest.raises(exp):
            dataplane.iot_pnp_model_create(fixture_cmd, model="{{}")

    def test_model_create_invalid_payload(self, serviceclient):

        payload = str(read_file_content(_pnp_create_model_payload_file))
        payload = json.loads(payload)
        del payload["@id"]
        payload = json.dumps(payload)
        with pytest.raises(CLIError):
            dataplane.iot_pnp_model_create(fixture_cmd, model=payload)


class TestModelRepoModelPublish(object):
    @pytest.fixture(params=[400, 418, 503])
    def serviceclient_publish_errors(self, mocker, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, {"error": "something failed"}
        )
        return service_client

    @pytest.fixture(params=[(200, 200, 201), (200, 200, 204), (200, 200, 412)])
    def serviceclient(self, mocker, request):
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
            build_mock_response(
                mocker, request.param[0], payload=payload_list, headers={"eTag": "eTag"}
            ),
            build_mock_response(
                mocker, request.param[1], payload=payload_show, headers={"eTag": "eTag"}
            ),
            build_mock_response(mocker, request.param[2], {}, headers={"eTag": "eTag"}),
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_publish(self, fixture_cmd, serviceclient, target_model):
        dataplane.iot_pnp_model_publish(
            fixture_cmd, model_id=target_model,
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers

        assert method == "PUT"
        assert "/models/{}?".format(url_encode_str(target_model, plus=True)) in url
        assert "update-metadata=true" in url
        assert headers.get("x-ms-model-state") == "Listed"

    @pytest.mark.parametrize("target_model", [("acv.17")])
    def test_model_publish_error(
        self, fixture_cmd, serviceclient_publish_errors, target_model
    ):
        with pytest.raises(CLIError):
            dataplane.iot_pnp_model_publish(
                fixture_cmd, model_id=target_model,
            )


class TestModelRepoModelShow(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request):
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

    @pytest.fixture(params=[404, 500])
    def serviceclient_generic_error(self, mocker, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, {"error": "something failed"}
        )
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_show(self, fixture_cmd, serviceclient, target_model):
        result = dataplane.iot_pnp_model_show(fixture_cmd, model_id=target_model)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert "/models/{}?".format(url_encode_str(target_model, plus=True)) in url
        assert json.dumps(result)

    @pytest.mark.parametrize("target_model", [("acv:17")])
    def test_model_show_error(
        self, fixture_cmd, serviceclient_generic_error, target_model
    ):
        response = dataplane.iot_pnp_model_show(fixture_cmd, model_id=target_model)
        assert "error" in response

    @pytest.fixture(params=[400])
    def serviceclientemptyresult(self, mocker, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("target_model", [(_pnp_generic_model_id)])
    def test_model_show_no_result(
        self, fixture_cmd, serviceclientemptyresult, target_model
    ):
        with pytest.raises(CLIError):
            dataplane.iot_pnp_model_show(
                fixture_cmd, model_id=target_model,
            )


class TestModelRepoModelList(object):
    @pytest.fixture(params=[200])
    def service_client(self, mocker, request):
        serviceclient = mocker.patch(path_service_client)
        payload = json.dumps(
            [
                {
                    "_etag": '"00000000-0000-0800-0000-000000000000"',
                    "comment": "",
                    "countOfCommands": 0,
                    "countOfComponents": 0,
                    "countOfExtends": 0,
                    "countOfProperties": 0,
                    "countOfRelationships": 0,
                    "countOfSchemas": 0,
                    "countOfTelemetries": 0,
                    "createdBy": "user@contoso.com",
                    "createdDate": "2020-04-29T17:17:44.3055434+00:00",
                    "displayName": "Device Information",
                    "modelId": "test:model:name;1",
                    "modelName": "test:model:name",
                    "modelState": "Listed",
                    "modelType": "Interface",
                    "publisherId": "00000000-0000-0000-0000-000000000000",
                    "publisherName": "user@contoso.com",
                    "updatedDate": "2020-04-29T17:24:48.8645696+00:00",
                    "version": "1",
                }
            ]
        )
        serviceclient.return_value = build_mock_response(mocker, request.param, payload)
        return serviceclient

    @pytest.fixture(params=[400, 503])
    def serviceclient_generic_error(self, mocker, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, {"error": "something failed"}
        )
        return service_client

    @pytest.mark.parametrize(
        ["search_content", "shared"],
        [
            (
                {
                    "searchKeyword": "keyword",
                    "modelType": "type",
                    "modelState": "state",
                    "publisherId": "publisher",
                },
                False,
            ),
            ({"searchKeyword": "test"}, True),
            ({}, False),
        ],
    )
    def test_model_list(self, fixture_cmd, service_client, search_content, shared):
        result = dataplane.iot_pnp_model_list(
            fixture_cmd,
            keyword=search_content.get("searchKeyword"),
            model_type=search_content.get("modelType"),
            model_state=search_content.get("modelState"),
            publisher_id=search_content.get("publisherId"),
            shared=shared,
        )
        args = service_client.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][0].headers
        body = json.loads(args[0][0].body)

        for k in search_content.keys():
            assert body[k] == search_content[k]

        assert (
            headers.get("x-ms-show-shared-models-only") == "true" if shared else "false"
        )
        assert method == "POST"

        assert "/models/search?" in url
        assert len(result) == 1

    def test_model_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            dataplane.iot_pnp_model_list(fixture_cmd,)


class TestModelRepoRepoCreate(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    def test_repo_create(self, fixture_cmd, serviceclient):
        repo.iot_pnp_tenant_create(fixture_cmd)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "/tenants" in url
        assert method == "PUT"


class TestModelRepoRepoList(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, [{}])
        return service_client

    def test_repo_list(self, fixture_cmd, serviceclient):
        repo.iot_pnp_tenant_show(fixture_cmd)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "/tenants" in url
        assert method == "GET"


class TestModelRepoRBAC(object):
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.fixture(params=[200])
    def serviceclient_arr(self, mocker, request, set_cwd):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, [{}])
        return service_client

    @pytest.mark.parametrize(
        ["role", "resource_id", "resource_type", "subject_id", "subject_type"],
        [
            (
                RoleIdentifier.modelAdmin,
                "12345-12345-12345-12345",
                "Tenant",
                "user@tenant.com",
                "user",
            ),
            (
                RoleIdentifier.modelReader,
                "abc:123:model;2",
                "Model",
                "user@tenant.com",
                "user",
            ),
            (
                RoleIdentifier.modelsCreator,
                "12345-12345-12345-12345",
                "Tenant",
                "12345-12345-12345",
                "ServicePrincipal",
            ),
            (
                RoleIdentifier.modelsPublisher,
                "abc:123:model;2",
                "Model",
                "12345-12345-12345",
                "ServicePrincipal",
            ),
        ],
    )
    def test_repo_role_create(
        self,
        fixture_cmd,
        serviceclient,
        role,
        resource_id,
        resource_type,
        subject_id,
        subject_type,
    ):

        resource_id = "resource_id"
        resource_type = "resource_type"
        subject_id = "subject"
        subject_type = "subject_type"

        repo.iot_pnp_role_create(
            fixture_cmd, resource_id, resource_type, subject_id, subject_type, role
        )
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        data = json.loads(args[0][0].data)

        assert method == "PUT"
        assert (
            "/resources/{0}/types/{1}/subjects/{2}".format(
                resource_id, resource_type, subject_id
            )
            in url
        )
        assert data["subjectType"] == subject_type
        assert data["role"] == role.value
        assert data["resourceType"] == resource_type

    @pytest.mark.parametrize(
        ["resource_id", "resource_type", "subject_id"],
        [
            ("12345-12345-12345", "Tenant", "user@tenant.com"),
            ("test:model:perms;1", "Model", "12345-12345-12345"),
            ("12345-12345-12345", "Tenant", None),
            ("test:model:perms;1", "Model", None),
        ],
    )
    def test_repo_role_show(
        self, fixture_cmd, serviceclient_arr, resource_id, resource_type, subject_id
    ):

        repo.iot_pnp_role_list(fixture_cmd, resource_id, resource_type, subject_id)
        args = serviceclient_arr.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == "GET"
        assert (
            (
                "/resources/{0}/types/{1}/subjects/{2}".format(
                    url_encode_str(resource_id),
                    resource_type,
                    url_encode_str(subject_id),
                )
                in url
            )
            if subject_id
            else (
                "/resources/{0}/types/{1}".format(
                    url_encode_str(resource_id), resource_type
                )
                in url
            )
        )

    @pytest.mark.parametrize(
        ["role", "resource_id", "resource_type", "subject_id"],
        [
            (
                RoleIdentifier.modelAdmin,
                "12345-12345-12345-12345",
                "Tenant",
                "user@tenant.com",
            ),
            (
                RoleIdentifier.modelReader,
                "abc:123:model;2",
                "Model",
                "12345-12345-12345",
            ),
        ],
    )
    def test_repo_role_delete(
        self, fixture_cmd, serviceclient, role, resource_id, resource_type, subject_id,
    ):

        repo.iot_pnp_role_delete(
            fixture_cmd, resource_id, resource_type, role, subject_id
        )
        args = serviceclient.call_args
        url = args[0][0].url

        assert (
            "/resources/{0}/types/{1}/subjects/{2}/roles/{3}".format(
                url_encode_str(resource_id),
                resource_type,
                url_encode_str(subject_id),
                role.value,
            )
            in url
        )
