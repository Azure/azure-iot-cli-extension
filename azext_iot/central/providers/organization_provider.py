# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Optional

from azure.cli.core.azclierror import AzureResponseError, ClientRequestError, ResourceNotFoundError
from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import Organization


class CentralOrganizationProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().organizations
        # Cache
        self._orgs = {}

    def list(self) -> List[Organization]:
        try:
            orgs = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._orgs.update({org.id: org for org in orgs})

        return orgs

    def get(
        self,
        org_id: str,
    ) -> Organization:
        # Try cache
        org = self._orgs.get(org_id)

        if not org:
            try:
                org = self.sdk.get(organization_id=org_id)
            except CloudError as e:
                handle_service_exception(e)

        if not org:
            raise ResourceNotFoundError("No organization found with id: '{}'.".format(org_id))

        # Update cache
        self._orgs[org_id] = org

        return org

    def delete(
        self,
        org_id: str,
    ):
        try:
            result = self.sdk.remove(organization_id=org_id)
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache
        del self._orgs[org_id]

        return result

    def create(
        self,
        org_id: str,
        org_name: Optional[str] = None,
        parent_org: Optional[str] = None,
    ):
        if org_id in self._orgs:
            raise ClientRequestError("Organization already exists")

        if not org_name:
            org_name = org_id

        payload = {
            "displayName": org_name,
        }
        if parent_org:
            payload["parent"] = parent_org

        try:
            org = self.sdk.create(organization_id=org_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

        if not org:
            raise AzureResponseError(
                "Failed to create organization with id: '{}'.".format(org_id)
            )

        # Update cache
        self._orgs[org.id] = org

        return org

    def update(
        self,
        org_id: str,
        org_name: Optional[str] = None,
        parent_org: Optional[str] = None,
    ):
        if not org_name:
            org_name = org_id

        payload = {
            "displayName": org_name,
        }
        if parent_org:
            payload["parent"] = parent_org

        try:
            org = self.sdk.update(organization_id=org_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

        if not org:
            raise AzureResponseError(
                "Failed to update organization with id: '{}'.".format(org_id)
            )

        # Update cache
        self._orgs[org.id] = org

        return org
