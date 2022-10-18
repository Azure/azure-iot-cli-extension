# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import pytest
import responses
import json
from knack.cli import CLIError
from azext_iot.operations import hub as subject
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.utility import ensure_iothub_sdk_min_version
from azext_iot.constants import IOTHUB_TRACK_2_SDK_MIN_VERSION

hub_name = "HUBNAME"
blob_container_uri = "https://example.com"
resource_group_name = "RESOURCEGROUP"
managed_identity = "EXAMPLEMANAGEDIDENTITY"
generic_job_response = {"JobResponse": generate_generic_id()}
qualified_hostname = "{}.subdomain.domain".format(hub_name)


@pytest.fixture
def get_mgmt_client(mocker, fixture_cmd):
    from azure.mgmt.iothub import IotHubClient

    # discovery call to find iothub
    patch_discovery = mocker.patch(
        "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target"
    )
    patch_discovery.return_value = {
        "resourcegroup": resource_group_name
    }

    # raw token for login credentials
    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    patched_get_login_credentials = mocker.patch(
        "azure.cli.core._profile.Profile.get_login_credentials"
    )
    patched_get_login_credentials.return_value = (
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    patch = mocker.patch(
        "azext_iot._factory.iot_hub_service_factory"
    )
    # pylint: disable=no-value-for-parameter, unexpected-keyword-arg
    if ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION):
        patch.return_value = IotHubClient(
            credential='',
            subscription_id="00000000-0000-0000-0000-000000000000",
        )
    else:
        patch.return_value = IotHubClient(
            credentials='',
            subscription_id="00000000-0000-0000-0000-000000000000",
        )

    return patch


def generate_device_identity(include_keys=False, auth_type=None, identity=None, rg=None):
    return {
        "include_keys": include_keys,
        "storage_authentication_type": auth_type,
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
    assert actual.status_message is None
    assert actual.parent_job_id is None
    assert actual.additional_properties == expected


class TestIoTHubDeviceIdentityExport(object):
    @pytest.fixture
    def service_client(self, mocked_response, get_mgmt_client):
        mocked_response.assert_all_requests_are_fired = False

        mocked_response.add(
            method=responses.GET,
            content_type="application/json",
            url=re.compile(
                "https://(.*)management.azure.com/subscriptions/(.*)/"
                "providers/Microsoft.Devices/IotHubs"
            ),
            status=200,
            match_querystring=False,
            body=json.dumps({"hostName": qualified_hostname}),
        )

        mocked_response.add(
            method=responses.POST,
            url=re.compile(
                "https://management.azure.com/subscriptions/(.*)/"
                "providers/Microsoft.Devices/IotHubs/{}/exportDevices".format(
                    hub_name
                )
            ),
            body=json.dumps(generic_job_response),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(include_keys=True),
            generate_device_identity(auth_type="identity"),
            generate_device_identity(auth_type="key"),
            generate_device_identity(rg=resource_group_name),
        ]
    )
    def test_device_identity_export_track1(self, fixture_cmd, service_client, req):
        result = subject.iot_device_export(
            cmd=fixture_cmd,
            hub_name=hub_name,
            blob_container_uri=blob_container_uri,
            include_keys=req["include_keys"],
            storage_authentication_type=req["storage_authentication_type"],
            resource_group_name=req["resource_group_name"],
        )

        request = service_client.calls[0].request
        request_body = json.loads(request.body)

        assert request_body["exportBlobContainerUri"] == blob_container_uri
        assert request_body["excludeKeys"] == (not req["include_keys"])
        if req["storage_authentication_type"]:
            assert request_body["authenticationType"] == req["storage_authentication_type"] + "Based"
        if req["storage_authentication_type"] == "identityBased" and req["identity"] not in (None, "[system]"):
            assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(include_keys=True),
            generate_device_identity(auth_type="identity"),
            generate_device_identity(auth_type="key"),
            generate_device_identity(rg=resource_group_name),
            generate_device_identity(auth_type="identity", identity="[system]"),
            generate_device_identity(auth_type="identity", identity="system"),
            generate_device_identity(auth_type="identity", identity="managed_identity"),
        ]
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_device_identity_export_track2(self, fixture_cmd, service_client, req):
        result = subject.iot_device_export(
            cmd=fixture_cmd,
            hub_name=hub_name,
            blob_container_uri=blob_container_uri,
            include_keys=req["include_keys"],
            storage_authentication_type=req["storage_authentication_type"],
            identity=req["identity"],
            resource_group_name=req["resource_group_name"],
        )

        request = service_client.calls[0].request
        request_body = json.loads(request.body)

        assert request_body["exportBlobContainerUri"] == blob_container_uri
        assert request_body["excludeKeys"] == (not req["include_keys"])
        if req["storage_authentication_type"]:
            assert request_body["authenticationType"] == req["storage_authentication_type"] + "Based"
        if req["storage_authentication_type"] == "identityBased" and req["identity"] not in (None, "[system]"):
            assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(auth_type="key", identity="[system]"),
            generate_device_identity(auth_type="key", identity="system"),
        ]
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_device_identity_export_input(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_device_export(
                cmd=fixture_cmd,
                hub_name=hub_name,
                blob_container_uri=blob_container_uri,
                include_keys=req["include_keys"],
                storage_authentication_type=req["storage_authentication_type"],
                identity=req["identity"],
                resource_group_name=req["resource_group_name"],
            )


class TestIoTHubDeviceIdentityImport(object):
    @pytest.fixture
    def service_client(self, mocked_response, get_mgmt_client):
        mocked_response.assert_all_requests_are_fired = False

        mocked_response.add(
            method=responses.GET,
            content_type="application/json",
            url=re.compile(
                "https://(.*)management.azure.com/subscriptions/(.*)/"
                "providers/Microsoft.Devices/IotHubs"
            ),
            status=200,
            match_querystring=False,
            body=json.dumps({"hostName": qualified_hostname}),
        )

        mocked_response.add(
            method=responses.POST,
            content_type="application/json",
            url=re.compile(
                "https://management.azure.com/subscriptions/(.*)/"
                "providers/Microsoft.Devices/IotHubs/{}/importDevices".format(
                    hub_name
                )
            ),
            status=200,
            match_querystring=False,
            body=json.dumps(generic_job_response),
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(auth_type="identity"),
            generate_device_identity(auth_type="key"),
            generate_device_identity(rg=resource_group_name),
        ]
    )
    def test_device_identity_import_track1(self, fixture_cmd, service_client, req):
        result = subject.iot_device_import(
            cmd=fixture_cmd,
            hub_name=hub_name,
            input_blob_container_uri=blob_container_uri,
            output_blob_container_uri=blob_container_uri + "2",
            storage_authentication_type=req["storage_authentication_type"],
            resource_group_name=req["resource_group_name"],
        )
        request = service_client.calls[0].request
        request_body = json.loads(request.body)

        assert request_body["inputBlobContainerUri"] == blob_container_uri
        assert request_body["outputBlobContainerUri"] == blob_container_uri + "2"
        if req["storage_authentication_type"]:
            assert request_body["authenticationType"] == req["storage_authentication_type"] + "Based"
        if req["storage_authentication_type"] == "identityBased" and req["identity"] not in (None, "[system]"):
            assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(),
            generate_device_identity(auth_type="identity"),
            generate_device_identity(auth_type="key"),
            generate_device_identity(rg=resource_group_name),
            generate_device_identity(auth_type="identity", identity="[system]"),
            generate_device_identity(auth_type="identity", identity="managed_identity"),
        ]
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_device_identity_import_track2(self, fixture_cmd, service_client, req):
        result = subject.iot_device_import(
            cmd=fixture_cmd,
            hub_name=hub_name,
            input_blob_container_uri=blob_container_uri,
            output_blob_container_uri=blob_container_uri + "2",
            storage_authentication_type=req["storage_authentication_type"],
            identity=req["identity"],
            resource_group_name=req["resource_group_name"],
        )
        request = service_client.calls[0].request
        request_body = json.loads(request.body)

        assert request_body["inputBlobContainerUri"] == blob_container_uri
        assert request_body["outputBlobContainerUri"] == blob_container_uri + "2"
        if req["storage_authentication_type"]:
            assert request_body["authenticationType"] == req["storage_authentication_type"] + "Based"
        if req["storage_authentication_type"] == "identityBased" and req["identity"] not in (None, "[system]"):
            assert request_body["identity"]["userAssignedIdentity"] == req["identity"]

        assert_device_identity_result(result, generic_job_response)

    @pytest.mark.parametrize(
        "req",
        [
            generate_device_identity(auth_type="key", identity="[system]"),
            generate_device_identity(auth_type="key", identity="managed_identity"),
        ]
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_device_identity_import_input(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_device_import(
                cmd=fixture_cmd,
                hub_name=hub_name,
                input_blob_container_uri=blob_container_uri,
                output_blob_container_uri=blob_container_uri + "2",
                storage_authentication_type=req["storage_authentication_type"],
                identity=req["identity"],
                resource_group_name=req["resource_group_name"],
            )
