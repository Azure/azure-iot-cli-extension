# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.product.test.command_test_tasks import create
from azext_iot.digitaltwins.common import ADTPublicNetworkAccessType
import re
import pytest
import responses
import json
from knack.cli import CLIError
from azext_iot.digitaltwins import commands_resource as subject
from azext_iot.tests.digitaltwins.dt_helpers import (
    generate_generic_id,
    generic_result,
)
from azext_iot.tests.conftest import fixture_dt_client

# Default values
name = generate_generic_id()
resource_group_name = generate_generic_id()
location = 'westus'
role_type = "Contributor"
public_network_access = ADTPublicNetworkAccessType.enabled.value
provisioning = json.dumps({"properties":{"provisioningState": "provisioning"}})
finished = json.dumps({"properties":{"provisioningState": "finished"}})
failed = json.dumps({"properties":{"provisioningState": "failed"}})


@pytest.fixture
def start_twin_response(mocked_response, fixture_dt_client):
    mocked_response.assert_all_requests_are_fired = False

    mocked_response.add(
        method=responses.GET,
        content_type="application/json",
        url=re.compile(
            "https://management.azure.com/subscriptions/(.*)/resourcegroups/(.*)?"
        ),
        status=200,
        match_querystring=False,
        body=json.dumps({"name": name}),
    )

    mocked_response.add(
        method=responses.GET,
        content_type="application/json",
        url=re.compile(
            "https://management.azure.com/subscriptions/(.*)/"
            "providers/Microsoft.DigitalTwins/digitalTwinsInstances"
        ),
        status=200,
        match_querystring=False,
        body=json.dumps({"name": name}),
    )

    yield mocked_response


def generate_digital_twin_instance(
    location=None,
    tags=None,
    timeout=None,
    assign_identity=None,
    scopes=None,
    role_type=None,
    public_network_access=None,
):
    return {
        'location': location,
        'tags': tags,
        'timeout': timeout,
        'assign_identity': assign_identity,
        'scopes': scopes,
        'role_type': role_type,
        'public_network_access': public_network_access,
    }


class TestTwinCreateInstance(object):
    @pytest.fixture
    def service_client(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/digitaltwins/{}".format(
                resource_group_name, name
            ),
            body=finished,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PUT,
            url=re.compile("https://graph.windows.net/(.*)/getObjectsByObjectIds"),
            body=generic_result,
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "props",
        [
            generate_digital_twin_instance(),
            generate_digital_twin_instance(location="eastus"),
            generate_digital_twin_instance(tags=[generate_generic_id(), generate_generic_id()]),
            generate_digital_twin_instance(timeout=10),
            generate_digital_twin_instance(assign_identity=True),
            generate_digital_twin_instance(scopes=['Generic Scope1','Generic Scope2']),
            generate_digital_twin_instance(role_type="Generic Role"),
            generate_digital_twin_instance(public_network_access=ADTPublicNetworkAccessType.disabled.value),
        ]
    )
    def test_create_instance(self, fixture_cmd, service_client, props):
        result = subject.create_instance(
            cmd=fixture_cmd,
            name=name,
            resource_group_name=resource_group_name,
            location=props['location'],
            tags=props['tags'],
            assign_identity=props['assign_identity'],
            scopes=props['scopes'],
            role_type=props['role_type'],
            public_network_access=props['public_network_access'],
        )

        request = service_client.calls[0].request
        assert request.method == "PUT"
        assert (
            "resourceGroups/{}/providers/Microsoft.DigitalTwins/digitalTwinsInstances/{}".format(
                resource_group_name, name
            ) in request.url
        )

        request_body = json.loads(request.body)
        assert request_body["location"] == props['location'] if props['location'] else location
        assert request_body["properties"]["publicNetworkAccess"] == props['public_network_access']

        if props['assign_identity']:
            assert request_body["identity"]["type"] == "SystemAssigned"
        else:
            assert request_body["identity"]["type"] == None

        assert result == json.loads(finished)

        # Test RBAC role assignment callback function
        if props["scopes"]:
            graph_body = json.loads(service_client.calls[1].request.body)
            assert graph_body["objectIds"] == props["scopes"]

    @pytest.fixture
    def service_client_with_retry(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PUT,
            url=re.compile(
                "https://(.*)management.azure.com/subscriptions/(.*)/"
                "resourceGroups/{}/providers/Microsoft.DigitalTwins/digitalTwinsInstances/{}".format(
                    resource_group_name, name
                )
            ),
            body=provisioning,
            status=201,
            headers={
                "Location":
                    "https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                    "locations/xxx/operationResults/operationkey"
            },
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.GET,
            url="https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                "locations/xxx/operationResults/operationkey",
            body=finished,
            status=200,
            headers={
                "Location":
                    "https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                    "locations/xxx/operationResults/operationkey"
            },
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_instance_with_retry(self, fixture_cmd, service_client_with_retry):
        result = subject.create_instance(
            cmd=fixture_cmd,
            name=name,
            resource_group_name=resource_group_name,
            location=location
        )
        import pdb; pdb.set_trace()
        create_request = service_client_with_retry.calls[0].request
        print(create_request.url)
        print(json.loads(create_request.body))
        print(create_request.headers)
        check_request = service_client_with_retry.calls[1].request
        assert create_request.headers == check_request.url

        assert result == json.loads(finished)


    @pytest.fixture
    def service_client_with_failed_retry(self, mocked_response, start_twin_response):
        mocked_response.add(
            method=responses.PUT,
            url=re.compile(
                "https://(.*)management.azure.com/subscriptions/(.*)/"
                "resourceGroups/{}/providers/Microsoft.DigitalTwins/digitalTwinsInstances/{}".format(
                    resource_group_name, name
                )
            ),
            body=provisioning,
            status=201,
            headers={
                "Location":
                    "https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                    "locations/xxx/operationResults/operationkey"
            },
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.PUT,
            url="https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                "locations/xxx/operationResults/operationkey",
            body=failed,
            status=500,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_instance_with_failed_retry(self, fixture_cmd, service_client_with_failed_retry):
        result = subject.create_instance(
            cmd=fixture_cmd,
            name=name,
            resource_group_name=resource_group_name,
        )

        assert result == json.loads(finished)

    # @pytest.fixture(params=[400, 401, 500])
    # def service_client_error(self, mocked_response, start_twin_response, request):
    #     mocked_response.add(
    #         method=responses.PUT,
    #         url="https://{}/digitaltwins/{}".format(
    #             resource_group_name, name
    #         ),
    #         body=generic_result,
    #         status=request.param,
    #         content_type="application/json",
    #         match_querystring=False,
    #     )

    #     yield mocked_response

    # def test_create_instance_error(self, fixture_cmd, service_client_error):
    #     with pytest.raises(CLIError):
    #         subject.create_instance(
    #             cmd=fixture_cmd,
    #             name=name,
    #             resource_group_name=resource_group_name
    #         )
