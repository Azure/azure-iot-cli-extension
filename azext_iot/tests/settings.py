# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from os import environ


ENV_SET_TEST_IOTHUB_BASIC = ["azext_iot_testhub", "azext_iot_testrg", "azext_iot_testhub_cs"]


class Setting(object):
    pass


# Example of a dynamic class
# TODO: Evaluate moving this to the extension prime time
class DynamoSettings(object):
    def __init__(self, env_set):
        if not isinstance(env_set, list):
            raise TypeError("env_set must be a list")
        self.env = Setting()
        self._build_config(env_set)

    def _build_config(self, env_set):
        for key in env_set:
            value = environ.get(key)
            if not value:
                raise RuntimeError("'{}' environment variable required.")
            setattr(self.env, key, value)
