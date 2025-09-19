# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from argparse import Namespace
from azure.cli.core.azclierror import InvalidArgumentValueError


def validate_device_model_id(namespace: Namespace):
    if hasattr(namespace, 'model_id'):
        from azext_iot.common.utility import is_valid_dtmi
        model_id = namespace.model_id
        if model_id and not is_valid_dtmi(model_id):
            raise InvalidArgumentValueError(
                f"Invalid dtmi value '{model_id}' provided. A valid dtmi will look like "
                "'dtmi:com:example:TemperatureController;1'. "
                "See https://github.com/Azure/digital-twin-model-identifier for more details.")
