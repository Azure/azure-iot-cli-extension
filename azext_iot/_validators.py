# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.assets.user_messages import error_no_hub_or_login_on_input
from azext_iot.operations.generic import _process_top
from azure.cli.core.azclierror import RequiredArgumentMissingError


def mode2_iot_login_handler(cmd, namespace):
    if cmd.name.startswith('iot'):
        args = vars(namespace)

        if 'login' in args:
            login_value = args['login']
            iot_cmd_type = None
            entity_value = None
            offline = None

            if 'hub_name' in args:
                iot_cmd_type = 'IoT Hub'
                entity_value = args['hub_name']
            elif 'dps_name' in args:
                iot_cmd_type = 'DPS'
                entity_value = args['dps_name']

            if 'connection_string' in args:
                # support offline az iot hub generate-sas-token
                offline = args['connection_string']
            elif 'symmetric_key' in args:
                # support offline az iot dps compute-device-keys
                offline = args['symmetric_key']
            elif 'id_scope' in args:
                offline = args['id_scope']

            if not any([login_value, entity_value, offline]):
                raise RequiredArgumentMissingError(error_no_hub_or_login_on_input(iot_cmd_type))


def process_top(namespace):
    if hasattr(namespace, "top"):
        namespace.top = _process_top(top=namespace.top)
