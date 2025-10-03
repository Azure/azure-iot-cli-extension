# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
from os import linesep

from azure.cli.core.azclierror import CLIInternalError
from azext_iot.constants import UAMQP_DEP_NAME, UAMQP_COMPAT_VERSION, VERSION
from azext_iot.common.utility import test_import_and_version
from azext_iot.common.pip import install
from azext_iot.common._homebrew_patch import HomebrewPipPatch


def ensure_uamqp(config, yes=False, repair=False):
    if repair or not test_import_and_version(UAMQP_DEP_NAME, UAMQP_COMPAT_VERSION):
        if not yes:
            input_txt = ('Dependency update ({} {}) required for IoT extension version: {}. {}'
                         'Continue? (y/n) -> ').format(UAMQP_DEP_NAME, UAMQP_COMPAT_VERSION, VERSION, linesep)
            i = input(input_txt)
            if i.lower() != 'y':
                sys.exit('User has declined update...')

        print('Updating required dependency...')
        with HomebrewPipPatch():
            # The version range defined in this custom_version parameter should be stable
            try:
                install(UAMQP_DEP_NAME, compatible_version=UAMQP_COMPAT_VERSION)
                print('Update complete. Executing command...')
            except RuntimeError as e:
                print('Failure updating {}. Aborting...'.format(UAMQP_DEP_NAME))
                raise CLIInternalError(e)
