# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import time
from uuid import uuid4

from azure.cli.core.commands.arm import resolve_role_id
from azure.cli.core.commands.client_factory import get_mgmt_service_client
from azure.cli.core.profiles import ResourceType
from azure.core.exceptions import HttpResponseError
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
from knack.log import get_logger

logger = get_logger(__name__)


def create_role_assignment(
    cli_ctx,
    principal_id,
    identity_role=None,
    identity_scope=None,
):
    """Create an identity role assignment without Azure CLI's private helper."""
    principal_id = str(principal_id) if principal_id else principal_id
    identity_role = str(identity_role) if identity_role else identity_role
    identity_scope = str(identity_scope) if identity_scope else identity_scope

    role_definition_id = resolve_role_id(
        cli_ctx,
        identity_role,
        identity_scope,
    )
    assignments = get_mgmt_service_client(
        cli_ctx,
        ResourceType.MGMT_AUTHORIZATION,
    ).role_assignments
    parameters = RoleAssignmentCreateParameters(
        role_definition_id=role_definition_id,
        principal_id=principal_id,
        principal_type=None,
    )

    logger.info(
        "Creating an assignment with role '%s' on scope '%s'",
        role_definition_id,
        identity_scope,
    )
    retry_times = 36
    assignment_name = str(uuid4())
    for retry_time in range(retry_times):
        try:
            return assignments.create(
                scope=identity_scope,
                role_assignment_name=assignment_name,
                parameters=parameters,
            )
        except HttpResponseError as ex:
            error_code = getattr(getattr(ex, "error", None), "code", None)
            if error_code == "RoleAssignmentExists":
                logger.info("Role assignment already exists")
                return None
            if (
                retry_time < retry_times - 1
                and " does not exist in the directory " in str(ex)
            ):
                time.sleep(5)
                logger.warning(
                    "Retrying role assignment creation: %s/%s",
                    retry_time + 1,
                    retry_times,
                )
                continue
            raise
