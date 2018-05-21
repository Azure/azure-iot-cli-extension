# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
from os import linesep
import six
from six.moves import input
from azext_iot._constants import EVENT_LIB, VERSION
from azext_iot.common.utility import test_import
from azext_iot.common.config import get_uamqp_ext_version, update_uamqp_ext_version
from azext_iot.common.pip import install


def ensure_uamqp(config, yes=False, repair=False):
    if get_uamqp_ext_version(config) != EVENT_LIB[1] or repair or not test_import(EVENT_LIB[0]):
        if not yes:
            input_txt = ('Dependency update required for IoT extension version: {}. {}'
                         'Updated dependency must be compatible with {} {}. '
                         'Continue? (y/n) -> ').format(VERSION, linesep, EVENT_LIB[0], EVENT_LIB[1])
            i = input(input_txt)
            if i.lower() != 'y':
                sys.exit('User has declined update...')

        six.print_('Updating required dependency...')
        if install(EVENT_LIB[0], compatible_version=EVENT_LIB[1]):
            update_uamqp_ext_version(config, EVENT_LIB[1])
            six.print_('Update appears to have worked. Executing command...')
        else:
            sys.exit('Failure updating {} {}. Aborting...'.format(EVENT_LIB[0], EVENT_LIB[1]))
