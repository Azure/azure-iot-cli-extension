# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import (
    AzureInternalError, AzureResponseError, BadRequestError, ForbiddenError,
    ResourceNotFoundError, UnauthorizedError,
)


def handle_service_error(error):
    """Preserve DPS's structured error code/message and original HTTP cause."""
    message = str(error)
    if error.response is not None:
        try:
            body = error.response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            details = body.get("error") or body
            if isinstance(details, dict):
                code = details.get("errorCode", details.get("code"))
                if code is not None:
                    message = f"({code}) {details.get('message') or message}"
    error_type = {
        400: BadRequestError, 401: UnauthorizedError, 403: ForbiddenError, 404: ResourceNotFoundError,
    }.get(error.status_code, AzureResponseError)
    if error.status_code is not None and 500 <= error.status_code < 600:
        error_type = AzureInternalError
    raise error_type(message) from error
