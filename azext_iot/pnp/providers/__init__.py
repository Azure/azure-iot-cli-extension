# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.sdk.pnp.modelrepository import ModelRepositoryControlPlaneApi
from azext_iot.sdk.pnp.dataplane import DigitalTwinModelRepositoryApi
from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication
from azext_iot.constants import PNP_ENDPOINT, PNP_REPO_ENDPOINT, PNP_TENANT_RESOURCE_ID
from msrestazure.azure_exceptions import CloudError

__all__ = [
    "pnp_modelrepo_service_factory",
    "pnp_digitaltwin_modelrepo_api_service_factory",
    "PnPModelRepositoryApiManager",
    "PnPModelRepositoryManager",
    "CloudError",
]


def pnp_modelrepo_service_factory(cmd, *_):
    """
    Factory for importing deps and getting service client resources.
    Returns:
        pnp_modelrepo_resource (ModelRepositoryControlPlaneApi): operational resource for
            working with PnP Model Repository Tenants.
    """

    creds = DigitalTwinAuthentication(cmd=cmd, resource_id=PNP_TENANT_RESOURCE_ID)
    return ModelRepositoryControlPlaneApi(base_url=PNP_ENDPOINT, credentials=creds)


class PnPModelRepositoryManager(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_sdk(self):
        return pnp_modelrepo_service_factory(self.cmd)


def pnp_digitaltwin_modelrepo_api_service_factory(cmd, *_):
    """
    Factory for importing deps and getting service client resources.
    Returns:
        pnp_modelrepo_api_resource (DigitalTwinModelRepositoryApi): operational resource for
            working with PnP Model Repository data.
    """

    creds = DigitalTwinAuthentication(cmd=cmd, resource_id=PNP_TENANT_RESOURCE_ID)
    return DigitalTwinModelRepositoryApi(base_url=PNP_REPO_ENDPOINT, credentials=creds)


class PnPModelRepositoryApiManager(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_sdk(self):
        return pnp_digitaltwin_modelrepo_api_service_factory(self.cmd)
