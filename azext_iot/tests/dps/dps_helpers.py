# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

'''
NOTICE: These tests are to be phased out and introduced in more modern form.
        Try not to add any new content, only fixes if necessary.
        Look at IoT Hub jobs or configuration tests for a better example. Also use responses fixtures
        like mocked_response for http request mocking.
'''

import pytest
from azext_iot.common.sas_token_auth import SasTokenAuthentication

enrollment_id = 'myenrollment'
resource_group = 'myrg'
registration_id = 'myregistration'
etag = 'AAAA=='

mock_target = {}
mock_target['cs'] = 'HostName=mydps;SharedAccessKeyName=name;SharedAccessKey=value'
mock_target['entity'] = 'mydps'
mock_target['primarykey'] = 'rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['secondarykey'] = 'aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['policy'] = 'provisioningserviceowner'
mock_target['subscription'] = "5952cff8-bcd1-4235-9554-af2c0348bf23"

mock_symmetric_key_attestation = {
    "type": "symmetricKey",
    "symmetricKey": {
        "primaryKey": "primary_key",
        "secondaryKey": "secondary_key"
    },
}

# Patch Paths #
path_service_client = 'msrest.service_client.ServiceClient.send'
path_sas = 'azext_iot._factory.SasTokenAuthentication'
path_dps_sub_id = 'azure.cli.core._profile.Profile.get_subscription_id'
path_iot_service_provisioning_factory = "azext_iot._factory.iot_service_provisioning_factory"
path_gdcs = "azext_iot.dps.providers.discovery.DPSDiscovery.get_target"
path_discovery_dps_init = (
    "azext_iot.dps.providers.discovery.DPSDiscovery._initialize_client"
)


@pytest.fixture()
def fixture_gdcs(mocker):
    gdcs = mocker.patch(path_gdcs)
    gdcs.return_value = mock_target
    mocker.patch(path_iot_service_provisioning_factory)
    mocker.patch(path_discovery_dps_init)

    return gdcs


@pytest.fixture()
def fixture_get_sub_id(mocker):
    gsi = mocker.patch(path_dps_sub_id)
    gsi.return_value = mock_target['subscription']


@pytest.fixture()
def fixture_sas(mocker):
    r = SasTokenAuthentication(mock_target['entity'],
                               mock_target['policy'],
                               mock_target['primarykey'])
    sas = mocker.patch(path_sas)
    sas.return_value = r