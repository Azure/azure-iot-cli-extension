#!/usr/bin/env python
# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import os.path
from io import open
from setuptools import setup, find_packages


EXTENSION_REF_NAME = "azext_iot"

# Version extraction inspired from 'requests'
with open(
    os.path.join(EXTENSION_REF_NAME, "constants.py"), "r", encoding="utf-8"
) as fd:
    constants_raw = fd.read()
    VERSION = re.search(
        r'^VERSION\s*=\s*[\'"]([^\'"]*)[\'"]', constants_raw, re.MULTILINE
    ).group(1)

    PACKAGE_NAME = re.search(
        r'^EXTENSION_NAME\s*=\s*[\'"]([^\'"]*)[\'"]', constants_raw, re.MULTILINE
    ).group(1)


if not VERSION:
    raise RuntimeError("Cannot find version information")

if not PACKAGE_NAME:
    raise RuntimeError("Cannot find package information")


# The following dependencies are needed by the IoT extension but used from Az CLI Core.
# 'jmespath',
# 'pyyaml'
# 'knack'

# There is also a dependency for uamqp for amqp based commands
# though that is installed out of band (managed by the extension)
# for compatibility reasons.

DEPENDENCIES = [
    "azure-core>=1.24.0,<2.0.0",
    "azure-mgmt-core>=1.3.0,<2.0.0",
    "azure-identity>=1.6.1,<2.0.0",
    "azure-storage-blob>=12.14.0,<13.0.0",
    "msrest>=0.6.21",
    "msrestazure>=0.6.3,<2.0.0",
    "jsonschema~=3.2.0",
    "azure-iot-device~=2.11",
    "tomli~=2.0",
    "tomli-w~=1.0",
    "tqdm~=4.62",
    "treelib~=1.6",
    "packaging"
]
EXTRAS = {"uamqp": ["uamqp~=1.2"]}

CLASSIFIERS = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Intended Audience :: System Administrators",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "License :: OSI Approved :: MIT License",
]

short_description = "The Azure IoT extension for Azure CLI."

setup(
    name=PACKAGE_NAME,
    version=VERSION,
    python_requires=">=3.8",
    description=short_description,
    long_description="{} Intended for power users and/or automation of IoT solutions at scale.".format(
        short_description
    ),
    license="MIT",
    author="Microsoft",
    author_email="iotupx@microsoft.com",  # +@digimaun
    url="https://github.com/azure/azure-iot-cli-extension",
    classifiers=CLASSIFIERS,
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "scripts"]),
    package_data={
        EXTENSION_REF_NAME: [
            "azext_metadata.json",
            "assets/*",
        ]
    },
    install_requires=DEPENDENCIES,
    extras_require=EXTRAS,
    zip_safe=False,
)
