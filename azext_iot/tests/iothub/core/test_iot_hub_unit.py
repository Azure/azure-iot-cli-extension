# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import responses
import json
from knack.cli import CLIError
from azext_iot.operations import hub as subject
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.shared import (
    JobType,
    AuthenticationType,
)
from azure.cli.core.azclierror import BadRequestError

hub_name = "hubname"
shared_access_key_name = "TEST_SAS_KEY_NAME"
shared_access_key = "AB+c/+5nm2XpDXcffhnGhnxz/TVF4m5ag7AuVIGwchj="
hub_connection_string = "HostName={};SharedAccessKeyName={};SharedAccessKey={}".format(
    hub_name, shared_access_key_name, shared_access_key
)
blob_container_uri = "https://example.com"
resource_group_name = "RESOURCEGROUP"
managed_identity = "EXAMPLEMANAGEDIDENTITY"
generic_job_response = {"JobResponse": generate_generic_id()}
qualified_hostname = "{}.subdomain.domain".format(hub_name)
hub_policy = "test_policy"


@pytest.fixture
def get_mgmt_client(mocker, fixture_cmd):

    # discovery call to find iothub
    patch_discovery = mocker.patch(
        "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target"
    )
    patch_discovery.return_value = {
        "resourcegroup": resource_group_name,
        "cs": hub_connection_string,
        "entity": hub_name,
        "policy": hub_policy,
        "primarykey": shared_access_key
    }

    return patch_discovery


def generate_device_identity(include_keys=False, identity=None, rg=None):
    return {
        "include_keys": include_keys,
        "identity": identity,
        "resource_group_name": rg
    }


def assert_device_identity_result(actual, expected):
    # the body from the call will be put into additional_properties
    assert actual.job_id is None
    assert actual.start_time_utc is None
    assert actual.end_time_utc is None
    assert actual.type is None
    assert actual.status is None
    assert actual.failure_reason is None
    assert actual.additional_properties == expected


class TestIoTHubDeviceIdentityExport(object):
    @pytest.fixture
    def service_client(self, mocked_response, get_mgmt_client):
        mocked_response.assert_all_requests_are_fired = True

        mocked_response.add(
            method=responses.POST,
            url="https://{}/jobs/create?api-version=2021-04-12".format(hub_name),
            body=json.dumps(generic_job_response),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.fixture(params=[(400, BadRequestError)])
    def service_client_error(self, mocked_response, get_mgmt_client, request):
        mocked_response.assert_all_requests_are_fired = True

        mocked_response.add(
            method=responses.POST,
            url="https://{}/jobs/create?api-version=2021-04-12".format(hub_name),
            body=json.dumps(
                {"Message": "ErrorCode:BlobContainerValidationError;Failed to read devices blob from the input container."}
            ),
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )
        setattr(mocked_response, "expected_exception", request.param[1])

        yield mocked_response

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(include_keys=True),
            generate_device_identity(rg=resource_group_name),
            generate_device_identity(identity="[system]"),
            generate_device_identity(identity="managed_identity"),
        ]
    )
    def test_device_identity_export(self, fixture_cmd, service_client, req):
        result = subject.iot_device_export(
            cmd=fixture_cmd,
            hub_name=hub_name,
            blob_container_uri=blob_container_uri,
            include_keys=req["include_keys"],
            identity=req["identity"],
            resource_group_name=req["resource_group_name"],
        )

        request = service_client.calls[0].request
        request_body = json.loads(request.body)
        assert request_body["type"] == JobType.exportDevices.value
        assert request_body["outputBlobContainerUri"] == blob_container_uri
        assert request_body["excludeKeysInExport"] == (not req["include_keys"])
        if req["identity"] is None:
            assert request_body["storageAuthenticationType"] == AuthenticationType.keyBased.name
        else:
            assert request_body["storageAuthenticationType"] == AuthenticationType.identityBased.name
            if req["identity"] != "[system]":
                assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(identity="[system]"),
            generate_device_identity(identity="system"),
        ]
    )
    def test_device_identity_export_input(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_device_export(
                cmd=fixture_cmd,
                hub_name=hub_name,
                blob_container_uri=blob_container_uri,
                include_keys=req["include_keys"],
                identity=req["identity"],
                resource_group_name=req["resource_group_name"],
            )

    def test_device_identity_export_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError) as e:
            subject.iot_device_export(
                cmd=fixture_cmd,
                hub_name=hub_name,
                blob_container_uri=blob_container_uri,
                resource_group_name="myresourcegroup",
            )
        assert isinstance(e.value, service_client_error.expected_exception)


class TestIoTHubDeviceIdentityImport(object):
    @pytest.fixture
    def service_client(self, mocked_response, get_mgmt_client):
        mocked_response.assert_all_requests_are_fired = True

        mocked_response.add(
            method=responses.POST,
            url="https://{}/jobs/create?api-version=2021-04-12".format(hub_name),
            body=json.dumps(generic_job_response),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.fixture(params=[(400, BadRequestError)])
    def service_client_error(self, mocked_response, get_mgmt_client, request):
        mocked_response.assert_all_requests_are_fired = True

        mocked_response.add(
            method=responses.POST,
            url="https://{}/jobs/create?api-version=2021-04-12".format(hub_name),
            body=json.dumps(
                {"Message": "ErrorCode:BlobContainerValidationError;Failed to read devices blob from the input container."}
            ),
            status=request.param[0],
            content_type="application/json",
            match_querystring=False,
        )
        setattr(mocked_response, "expected_exception", request.param[1])

        yield mocked_response

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(rg=resource_group_name),
            generate_device_identity(identity="[system]"),
            generate_device_identity(identity="managed_identity"),
        ]
    )
    def test_device_identity_import(self, fixture_cmd, service_client, req):
        result = subject.iot_device_import(
            cmd=fixture_cmd,
            hub_name=hub_name,
            input_blob_container_uri=blob_container_uri,
            output_blob_container_uri=blob_container_uri + "2",
            identity=req["identity"],
            resource_group_name=req["resource_group_name"],
        )
        request = service_client.calls[0].request
        request_body = json.loads(request.body)

        assert request_body["type"] == JobType.importDevices.value
        assert request_body["inputBlobContainerUri"] == blob_container_uri
        assert request_body["outputBlobContainerUri"] == blob_container_uri + "2"
        if req["identity"] is None:
            assert request_body["storageAuthenticationType"] == AuthenticationType.keyBased.name
        else:
            assert request_body["storageAuthenticationType"] == AuthenticationType.identityBased.name
            if req["identity"] != "[system]":
                assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(identity="[system]"),
            generate_device_identity(identity="managed_identity"),
        ]
    )
    def test_device_identity_import_input(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_device_import(
                cmd=fixture_cmd,
                hub_name=hub_name,
                input_blob_container_uri=blob_container_uri,
                output_blob_container_uri=blob_container_uri + "2",
                identity=req["identity"],
                resource_group_name=req["resource_group_name"],
            )

    def test_device_identity_import_error(self, fixture_cmd, service_client_error):
        with pytest.raises(CLIError) as e:
            subject.iot_device_import(
                cmd=fixture_cmd,
                hub_name=hub_name,
                input_blob_container_uri=blob_container_uri,
                output_blob_container_uri=blob_container_uri + "2",
                resource_group_name="myresourcegroup",
            )
        assert isinstance(e.value, service_client_error.expected_exception)
