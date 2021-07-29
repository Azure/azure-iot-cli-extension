# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os import environ


ENV_SET_TEST_IOTHUB_BASIC = [
    "azext_iot_testhub",
    "azext_iot_testrg",
]

ENV_SET_TEST_IOTHUB_CONNECTION_STRING = [
    "azext_iot_testhub_connection_string"
]


class Setting(object):
    pass


# Example of a dynamic class
# TODO: Evaluate moving this to the extension prime time
class DynamoSettings(object):
    def __init__(self, req_env_set: list = None, opt_env_set: list = None):
        if not req_env_set:
            req_env_set = []

        if not isinstance(req_env_set, list):
            raise TypeError("req_env_set must be a list")

        self.env = Setting()
        self._build_config(req_env_set)

        if opt_env_set:
            if not isinstance(opt_env_set, list):
                raise TypeError("opt_env_set must be a list")
            self._build_config(opt_env_set, optional=True)

    def _build_config(self, env_set: list, optional: bool = False):
        for key in env_set:
            value = environ.get(key)
            if not value:
                if not optional:
                    raise RuntimeError(
                        "{} environment variables required.".format(",".join(env_set))
                    )
            setattr(self.env, key, value)
