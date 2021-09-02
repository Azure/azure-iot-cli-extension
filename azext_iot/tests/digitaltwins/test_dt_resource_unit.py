# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import pytest
import responses
import json
import azext_iot.digitaltwins.providers.resource
from time import sleep
from azext_iot.digitaltwins import commands_resource as subject
from azext_iot.tests.digitaltwins.dt_helpers import generate_generic_id
from msrestazure.azure_exceptions import CloudError
from azext_iot.digitaltwins.common import ADTPublicNetworkAccessType

# Default values
name = generate_generic_id()
resource_group_name = generate_generic_id()
location = 'westus'
role_type = "Contributor"
public_network_access = ADTPublicNetworkAccessType.enabled.value
provisioning = json.dumps({"provisioningState": "provisioning"})
finished = json.dumps({"provisioningState": "succeeded"})
failed = json.dumps({"provisioningState": "failed"})


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


class TestTwinCreateInstance(object):
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
                    "locations/xxx/operationResults/operationkey2"
            },
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_instance_with_retry(self, fixture_cmd, mocker, service_client_with_retry):
        mocker.patch.object(azext_iot.digitaltwins.providers.resource, "ADT_CREATE_RETRY_AFTER", 0.0001)
        subject.create_instance(
            cmd=fixture_cmd,
            name=name,
            resource_group_name=resource_group_name,
            location=location
        )
        while len(service_client_with_retry.calls) == 1:
            sleep(10)
        check_request = service_client_with_retry.calls[1].request
        assert "operationkey" in check_request.url
        assert len(service_client_with_retry.calls) == 2
        assert service_client_with_retry.calls[1].response.content.decode("utf-8") == finished

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
            method=responses.GET,
            url="https://management.azure.com/subscriptions/xxx/providers/Microsoft.DigitalTwins/"
                "locations/xxx/operationResults/operationkey",
            body=failed,
            status=500,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_create_instance_with_failed_retry(self, fixture_cmd, mocker, service_client_with_failed_retry):
        mocker.patch.object(azext_iot.digitaltwins.providers.resource, "ADT_CREATE_RETRY_AFTER", 0.0001)
        result = subject.create_instance(
            cmd=fixture_cmd,
            name=name,
            resource_group_name=resource_group_name,
            location=location
        )
        while len(service_client_with_failed_retry.calls) == 1:
            sleep(10)
        check_request = service_client_with_failed_retry.calls[1].request
        assert "operationkey" in check_request.url

        # The LRO poller calls once more for some reason
        assert len(service_client_with_failed_retry.calls) >= 2
        assert service_client_with_failed_retry.calls[1].response.content.decode("utf-8") == failed

        # The poller.result will have the error
        assert result.status() == "Failed"
        with pytest.raises(CloudError):
            result.result()
