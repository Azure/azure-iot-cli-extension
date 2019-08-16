# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.assets.user_messages import ERROR_NO_HUB_OR_LOGIN_ON_INPUT


def mode2_iot_login_handler(cmd, namespace):
    if cmd.name.startswith('iot'):
        args = vars(namespace)
        arg_keys = args.keys()
        if 'login' in arg_keys:
            login_value = args.get('login')
            iot_cmd_type = None
            entity_value = None
            if 'hub_name' in arg_keys:
                iot_cmd_type = 'IoT Hub'
                entity_value = args.get('hub_name')
            elif 'dps_name' in arg_keys:
                iot_cmd_type = 'DPS'
                entity_value = args.get('dps_name')
            elif 'repo_endpoint' in arg_keys:
                iot_cmd_type = 'PnP'
                entity_value = args.get('repo_endpoint')

            if not any([login_value, entity_value]):
                raise CLIError(ERROR_NO_HUB_OR_LOGIN_ON_INPUT(iot_cmd_type))
