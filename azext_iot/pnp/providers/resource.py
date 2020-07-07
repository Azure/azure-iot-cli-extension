# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.pnp.providers import (
    PnPModelRepositoryManager,
    CloudError,
)
from azext_iot.common.utility import unpack_msrest_error
from knack.util import CLIError


class RepoResourceProvider(PnPModelRepositoryManager):
    def __init__(self, cmd):
        super(RepoResourceProvider, self).__init__(cmd=cmd)
        self.mgmt_sdk = self.get_mgmt_sdk()

    def create(self):
        try:
            return self.mgmt_sdk.create_tenant_async(self)
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def list(self):
        try:
            return self.mgmt_sdk.get_tenant_async(self)
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    # RBAC

    def get_role_assignments_for_resource(self, resource_id, resource_type):
        try:
            return self.mgmt_sdk.get_subjects_for_resources_async(
                resource_id=resource_id, resource_type=resource_type,
            )
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def get_role_assignments_for_subject(self, resource_id, resource_type, subject_id):
        try:
            return self.mgmt_sdk.get_subjects_for_resources_async1(
                resource_id=resource_id,
                resource_type=resource_type,
                subject_id=subject_id,
            )
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def add_role_assignment(self, resource_id, resource_type, subject_id, subject=None):
        try:
            return self.mgmt_sdk.assign_roles_async(
                resource_id=resource_id,
                resource_type=resource_type,
                subject=subject,
                subject_id=subject_id,
            )
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def remove_role_assignment(self, resource_id, resource_type, role_id, subject_id):
        try:
            return self.mgmt_sdk.remove_roles_async(
                resource_id=resource_id,
                resource_type=resource_type,
                subject_id=subject_id,
                role_id=role_id,
            )
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))
