# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from argparse import Namespace
from azure.cli.core.azclierror import InvalidArgumentValueError


def validate_device_model_id(namespace: Namespace):
    if hasattr(namespace, 'model_id'):
        from azext_iot.common.utility import is_valid_dtmi
        model_id = namespace.model_id
        if not(is_valid_dtmi(model_id)):
            raise InvalidArgumentValueError(
                "Invalid dtmi value provided. A valid dtmi will look like "
                "'dtmi:com:example:TemperatureController;1'. "
                "See https://github.com/Azure/digital-twin-model-identifier for more details.")
