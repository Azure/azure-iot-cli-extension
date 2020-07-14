# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.sdk.pnp.modelrepository import ModelRepositoryControlPlaneApi
from azext_iot.sdk.pnp.dataplane import DigitalTwinModelRepositoryApi
from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication
from azext_iot.constants import PNP_ENDPOINT, PNP_TENANT_RESOURCE_ID
from msrestazure.azure_exceptions import CloudError

__all__ = [
    "pnp_modelrepo_service_factory",
    "pnp_digitaltwin_modelrepo_api_service_factory",
    "PnPModelRepositoryApiManager",
    "PnPModelRepositoryManager",
    "CloudError",
]


def pnp_modelrepo_service_factory(cmd, pnp_dns_suffix=None, *_):
    """
    Factory for importing deps and getting service client resources.
    Returns:
        pnp_modelrepo_resource (ModelRepositoryControlPlaneApi): operational resource for
            working with PnP Model Repository Tenants.
    """
    creds = DigitalTwinAuthentication(cmd=cmd, resource_id=PNP_TENANT_RESOURCE_ID)
    endpoint = "https://provider.{}".format(
        pnp_dns_suffix if pnp_dns_suffix else PNP_ENDPOINT
    )
    return ModelRepositoryControlPlaneApi(base_url=endpoint, credentials=creds)


class PnPModelRepositoryManager(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_sdk(self, pnp_dns_suffix=None):
        return pnp_modelrepo_service_factory(self.cmd, pnp_dns_suffix)


def pnp_digitaltwin_modelrepo_api_service_factory(cmd, pnp_dns_suffix=None, *_):
    """
    Factory for importing deps and getting service client resources.
    Returns:
        pnp_modelrepo_api_resource (DigitalTwinModelRepositoryApi): operational resource for
            working with PnP Model Repository data.
    """
    creds = DigitalTwinAuthentication(cmd=cmd, resource_id=PNP_TENANT_RESOURCE_ID)
    endpoint = "https://repo.{}".format(
        pnp_dns_suffix if pnp_dns_suffix else PNP_ENDPOINT
    )
    return DigitalTwinModelRepositoryApi(base_url=endpoint, credentials=creds)


class PnPModelRepositoryApiManager(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_sdk(self, pnp_dns_suffix=None):
        return pnp_digitaltwin_modelrepo_api_service_factory(self.cmd, pnp_dns_suffix)
