# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import urllib
import json
from azext_iot.tests.generators import generate_generic_id

instance_name = generate_generic_id()
hostname = "{}.subdomain.domain".format(instance_name)
etag = 'AAAA=='
resource_group = 'myrg'


def generate_model_id():
    normal_id = "dtmi:com:{}:{};1".format(generate_generic_id(), generate_generic_id())
    url_id = urllib.parse.quote_plus(normal_id)
    return normal_id, url_id


generic_result = json.dumps({"result": generate_generic_id()})
model_id, url_model_id = generate_model_id()
twin_id = generate_generic_id()


def generate_model_result(model_id=None):
    model_id = model_id if model_id else generate_model_id()[0]
    return {
        "model": {
            "@context" : ["dtmi:com:context;2"],
            "@id" : model_id,
            "@type" : "Interface"
        },
        "id": model_id
    }


def generate_relationship(relationship_name=None):
    return {
        "$relationshipId": generate_generic_id(),
        "$relationshipName": relationship_name,
        "$sourceId": generate_generic_id()
    }


def generate_twin_result(randomized=False):
    return {
        "$dtId": generate_generic_id() if randomized else twin_id,
        "$etag": generate_generic_id() if randomized else etag,
        "$metadata": {
            "$model": generate_generic_id() if randomized else model_id
        }
    }


@pytest.fixture
def control_and_data_plane_client(mocker, fixture_cmd):
    from azext_iot.sdk.digitaltwins.controlplane import AzureDigitalTwinsManagementClient
    from azext_iot.sdk.digitaltwins.dataplane import AzureDigitalTwinsAPI
    from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication

    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    control_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.digitaltwins_service_factory"
    )
    control_plane_patch.return_value = AzureDigitalTwinsManagementClient(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        subscription_id="00000000-0000-0000-0000-000000000000",
    )

    data_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.base.DigitalTwinsProvider.get_sdk"
    )

    data_plane_patch.return_value = AzureDigitalTwinsAPI(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        base_url="https://{}/".format(hostname)
    )

    return control_plane_patch, data_plane_patch
