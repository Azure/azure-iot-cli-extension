# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.assets.user_messages import error_no_hub_or_login_on_input


def mode2_iot_login_handler(cmd, namespace):
    if cmd.name.startswith('iot'):
        args = vars(namespace)

        if 'login' in args:
            login_value = args['login']
            iot_cmd_type = None
            entity_value = None

            if 'hub_name' in args:
                iot_cmd_type = 'IoT Hub'
                entity_value = args['hub_name']
            elif 'dps_name' in args:
                iot_cmd_type = 'DPS'
                entity_value = args['dps_name']
            elif 'repo_endpoint' in args:
                iot_cmd_type = 'PnP'
                entity_value = args['repo_endpoint']

            if not any([login_value, entity_value]):
                raise CLIError(error_no_hub_or_login_on_input(iot_cmd_type))
