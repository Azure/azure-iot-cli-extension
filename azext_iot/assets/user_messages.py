# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def ERROR_NO_HUB_OR_LOGIN_ON_INPUT(entity_type='IoT Hub'):
    return 'Please provide an {0} entity name or {0} connection string via --login...'.format(entity_type)
