#!/usr/bin/env python
# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import os.path
from io import open  # pylint: disable=W0622
from setuptools import setup, find_packages


package_folder_path = 'azext_iot'

# Version extraction inspired from 'requests'
with open(os.path.join(package_folder_path, '_constants.py'), 'r') as fd:
    VERSION = re.search(r'^VERSION\s*=\s*[\'"]([^\'"]*)[\'"]',
                        fd.read(), re.MULTILINE).group(1)


CLASSIFIERS = [
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'Intended Audience :: System Administrators',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'License :: OSI Approved :: MIT License',
]

DEPENDENCIES = [
    'msrestazure',
    'paho-mqtt==1.3.1',
    'pyyaml'
]


setup(
    name='azure-cli-iot-ext',
    version=VERSION,
    description='Provides the data plane command layer for Azure IoT Hub, IoT Edge and IoT Device Provisioning Service',
    long_description='Authoritative IoT data plane extension for Azure CLI. '
    'Focused on providing data plane commands for Azure IoT Hub, IoT Edge and IoT Device Provisioning Service',
    license='MIT',
    author='Microsoft',
    author_email='iotupx@microsoft.com',
    url='https://github.com/azure/azure-iot-cli-extension',
    classifiers=CLASSIFIERS,
    packages=find_packages(),
    package_data={'azext_iot': ['azext_metadata.json', 'digicert.pem']},
    install_requires=DEPENDENCIES
)
