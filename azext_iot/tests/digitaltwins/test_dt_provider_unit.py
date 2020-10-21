# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import pytest
import responses
import json
from azext_iot.digitaltwins.providers.base import DigitalTwinsProvider
from ..generators import generate_generic_id


resource_group = generate_generic_id()
instance_name = generate_generic_id()
qualified_hostname = "{}.subdomain.domain".format(instance_name)


@pytest.fixture
def get_mgmt_client(mocker, fixture_cmd):
    from azext_iot.sdk.digitaltwins.controlplane import AzureDigitalTwinsManagementClient
    from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication

    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    patch = mocker.patch(
        "azext_iot.digitaltwins.providers.digitaltwins_service_factory"
    )
    patch.return_value = AzureDigitalTwinsManagementClient(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        subscription_id="00000000-0000-0000-0000-000000000000",
    )

    return patch


class TestDigitalTwinsProvider:
    @pytest.fixture
    def service_client(self, mocked_response, get_mgmt_client):
        mocked_response.assert_all_requests_are_fired = False

        mocked_response.add(
            method=responses.GET,
            content_type="application/json",
            url=re.compile(
                "https://management.azure.com/subscriptions/(.*)/resourceGroups/{}/"
                "providers/Microsoft.DigitalTwins/digitalTwinsInstances/{}".format(
                    resource_group, instance_name
                )
            ),
            status=200,
            match_querystring=False,
            body=json.dumps({"hostName": qualified_hostname}),
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "name, expected",
        [
            (instance_name, "https://{}".format(qualified_hostname)),
            (qualified_hostname, "https://{}".format(qualified_hostname)),
            (
                "https://{}.domain".format(instance_name),
                "https://{}.domain".format(instance_name),
            ),
            (
                "http://{}.domain".format(instance_name),
                "https://{}.domain".format(instance_name),
            ),
        ],
    )
    def test_get_endpoint(self, fixture_cmd, name, expected, service_client):
        subject = DigitalTwinsProvider(cmd=fixture_cmd, name=name, rg=resource_group)
        endpoint = subject._get_endpoint()

        assert endpoint == expected
