# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from enum import IntEnum, Enum


class Severity(IntEnum):
    info = 1
    warning = 2
    error = 3


class Transport(str, Enum):
    AMQP = "amqp"
    AMQP_WS = "amqp_ws"
