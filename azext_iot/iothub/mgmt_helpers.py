# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot._factory import iot_hub_service_factory
from knack.util import CLIError


def get_mgmt_iothub_exception():
    """ Py 2/3 compatible management plane exception import"""

    try:
        from azure.mgmt.iothub.models.error_details_py3 import ErrorDetailsException
    except ImportError:
        from azure.mgmt.iothub.models.error_details import ErrorDetailsException

    return ErrorDetailsException


def get_mgmt_iothub_client(cmd, raise_if_error=False):
    try:
        return iot_hub_service_factory(cmd.cli_ctx)
    except CLIError as e:
        if raise_if_error:
            raise e
        return None
