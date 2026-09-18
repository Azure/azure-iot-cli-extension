# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import contextmanager

from azure.cli.core.azclierror import ForbiddenError, ResourceNotFoundError, UnauthorizedError
from azure.core.exceptions import HttpResponseError


@contextmanager
def arm_authorization_context():
    try:
        yield
    except (HttpResponseError, ResourceNotFoundError) as error:
        original = error
        if isinstance(error, ResourceNotFoundError):
            original = error.__cause__ or error.__context__
        status = getattr(original, "status_code", None)
        if isinstance(original, HttpResponseError) and status in (401, 403):
            kind = UnauthorizedError if status == 401 else ForbiddenError
            raise kind(
                f"{original}\nDPS ARM discovery or shared-access-policy lookup failed. "
                "Check the selected subscription/resource group and the caller's ARM read/list-keys permissions. "
                "DPS data-plane roles do not grant ARM permissions. This is not a DPS managed-identity request to ADR."
            ) from original
        raise


def handle_enrollment_error(error, target, operation, translate):
    """Add service-operation context only; never used for device authentication."""
    try:
        translate(error)
    except (UnauthorizedError, ForbiddenError) as translated:
        if target.get("policy") == "login":
            guidance = (
                "The resolved DPS service authentication is Microsoft Entra. "
                "Check the caller's DPS data-plane permission for this enrollment operation"
            )
            if operation.startswith(("create", "update", "delete")):
                guidance += " (for example, Device Provisioning Service Data Contributor for enrollment writes)"
            guidance += ". ARM management permissions alone do not grant this data-plane access."
        else:
            guidance = (
                "The resolved DPS service authentication is SAS/shared-access policy, including when a "
                "connection string overrides --auth-type. Check that policy's enrollment permissions and "
                "the DPS local-auth configuration. Caller Entra role assignments do not authorize a SAS request; "
                "use --auth-type login without a connection string when service local authentication is disabled."
            )
        raise type(translated)(
            f"{translated}\nDPS service operation: {operation}. {guidance} "
            "If this enrollment uses an ADR policy, DPS managed-identity access to the referenced ADR namespace "
            "is a separate authorization boundary. This response alone does not identify that identity or "
            "namespace, or prove that either boundary lacks a particular role."
        ) from error
