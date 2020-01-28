# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import subprocess
import sys
from azure.cli.core.extension import get_extension_path, extension_exists
from knack.log import get_logger
from azext_iot.constants import EXTENSION_NAME


logger = get_logger(__name__)


def install(package, exact_version=None, compatible_version=None, custom_version=None):
    if not extension_exists(EXTENSION_NAME):
        raise RuntimeError('iot extension is misconfigured')
    ext_path = get_extension_path(EXTENSION_NAME)
    cmd = [sys.executable, '-m', 'pip', '--disable-pip-version-check', '--no-cache-dir', 'install', '-U', '--target', ext_path]
    cmd_suffix = None

    if exact_version:
        cmd_suffix = '{}=={}'.format(package, exact_version)
    elif compatible_version:
        cmd_suffix = '{}~={}'.format(package, compatible_version)
    elif custom_version:
        cmd_suffix = '{}{}'.format(package, custom_version)
    else:
        cmd_suffix = package

    cmd.append(cmd_suffix)
    logger.info(cmd)
    try:
        log_output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        logger.debug(log_output)
        return True
    except subprocess.CalledProcessError as e:
        logger.debug(e.output)
        logger.debug(e)
        raise(RuntimeError(e.output))
