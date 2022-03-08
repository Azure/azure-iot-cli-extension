# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import FileOperationError
from azext_iot.product.providers.aics import AICSProvider
from azext_iot.common.utility import process_json_arg


def list(cmd, test_id, base_url=None):
    ap = AICSProvider(cmd, base_url)
    return ap.show_test_cases(test_id=test_id)


def update(cmd, test_id, configuration_file, base_url=None):
    import os

    if not os.path.exists(configuration_file):
        raise FileOperationError("Specified configuration file does not exist")
    ap = AICSProvider(cmd, base_url)
    return ap.update_test_cases(
        test_id=test_id,
        patch=process_json_arg(configuration_file, "configuration_file"),
    )
