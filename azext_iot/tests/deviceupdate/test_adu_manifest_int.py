# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.conftest import get_context_path

cli = EmbeddedCLI()

logger = get_logger(__name__)


@pytest.mark.parametrize(
    "options, expected",
    [
        (
            "--update-provider digimaun0 --update-name simpleaptupdate --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--compat deviceManufacturer=Contoso deviceModel=Radio "
            "--step handler=microsoft/apt:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\"",
            {
                "updateId": {"provider": "digimaun0", "name": "simpleaptupdate", "version": "1.0.0"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Vacuum"},
                    {"deviceManufacturer": "Contoso", "deviceModel": "Radio"},
                ],
                "instructions": {
                    "steps": [{"handler": "microsoft/apt:1", "files": ["libcurl4-doc-apt-manifest.json"], "type": "inline"}]
                },
                "files": [
                    {
                        "filename": "libcurl4-doc-apt-manifest.json",
                        "sizeInBytes": 163,
                        "hashes": {"sha256": "iFWTIaxp33tf5BR1w0fMmnnHpjsUjLRQ9eZFjw74LbU="},
                    }
                ],
                "manifestVersion": "5.0",
            },
        ),
        (
            "--update-provider digimaun1 --update-name Microphone --update-version 2.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Microphone "
            "--step handler=microsoft/swupdate:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'install.sh')}\" "
            "--is-deployable false",
            {
                "updateId": {"provider": "digimaun1", "name": "Microphone", "version": "2.0.0"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Microphone"},
                ],
                "instructions": {
                    "steps": [{"handler": "microsoft/swupdate:1", "files": ["action.sh", "install.sh"], "type": "inline"}]
                },
                "files": [
                    {
                        "filename": "action.sh",
                        "sizeInBytes": 33,
                        "hashes": {"sha256": "n+KGjLjSGr7LVKsgWiExUDeU6Z2ZTJu0tpAWxkmYKxA="},
                    },
                    {
                        "filename": "install.sh",
                        "sizeInBytes": 23,
                        "hashes": {"sha256": "u6QdeTFImuTiReJ4WP9RlnYABdpd0cs8kuCz2zrHW28="},
                    },
                ],
                "manifestVersion": "5.0",
                "isDeployable": False,
            },
        ),
        (
            "--update-provider digimaun2 --update-name Toaster --update-version 1.0.1 "
            "--compat deviceManufacturer=Contoso deviceModel=Toaster "
            '--step handler=microsoft/script:1 properties=\'{"args": "--pre"}\' description="Pre-install script" files=image '
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'install.sh')}\" "
            "downloadHandler=microsoft/delta:1 "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'simple_apt_manifest_v5.json')}\" "
            'properties=\'{"microsoft.sourceFileHashAlgorithm":"sha256", '
            '"microsoft.sourceFileHash":"YmFYwnEUddq2nZsBAn5v7gCRKdHx+TUntMz5tLwU+24="}\' '
            '--step updateId.provider=digimaun updateId.name=Microphone updateId.version=1.3 description="Microphone Firmware" '
            '--step updateId.provider=digimaun updateId.name=Speaker updateId.version=0.9 description="Speaker Firmware" '
            '--step handler=microsoft/script:1 properties=\'{"args":"--post"}\' description="Post-install script" '
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" ",
            {
                "updateId": {"provider": "digimaun2", "name": "Toaster", "version": "1.0.1"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Toaster"},
                ],
                "instructions": {
                    "steps": [
                        {
                            "type": "inline",
                            "handler": "microsoft/script:1",
                            "handlerProperties": {"args": "--pre"},
                            "files": ["image"],
                            "description": "Pre-install script",
                        },
                        {
                            "type": "reference",
                            "updateId": {"provider": "digimaun", "name": "Microphone", "version": "1.3"},
                            "description": "Microphone Firmware",
                        },
                        {
                            "type": "reference",
                            "updateId": {"provider": "digimaun", "name": "Speaker", "version": "0.9"},
                            "description": "Speaker Firmware",
                        },
                        {
                            "type": "inline",
                            "handler": "microsoft/script:1",
                            "handlerProperties": {"args": "--post"},
                            "files": ["action.sh"],
                            "description": "Post-install script",
                        },
                    ]
                },
                "files": [
                    {
                        "filename": "install.sh",
                        "sizeInBytes": 23,
                        "hashes": {"sha256": "u6QdeTFImuTiReJ4WP9RlnYABdpd0cs8kuCz2zrHW28="},
                        "downloadHandler": {"id": "microsoft/delta:1"},
                        "relatedFiles": [
                            {
                                "filename": "simple_apt_manifest_v5.json",
                                "sizeInBytes": 1031,
                                "hashes": {"sha256": "L+ZKmOOT3xRfHsFK7pcTXBLjeI2OFCW0855qIcV5sts="},
                                "properties": {
                                    "microsoft.sourceFileHash": "YmFYwnEUddq2nZsBAn5v7gCRKdHx+TUntMz5tLwU+24=",
                                    "microsoft.sourceFileHashAlgorithm": "sha256",
                                },
                            }
                        ],
                    },
                    {
                        "filename": "action.sh",
                        "sizeInBytes": 33,
                        "hashes": {"sha256": "n+KGjLjSGr7LVKsgWiExUDeU6Z2ZTJu0tpAWxkmYKxA="},
                    },
                ],
                "manifestVersion": "5.0",
            },
        ),
    ],
)
def test_adu_manifest_init_v5(options, expected):
    result = cli.invoke(f"iot device-update update init v5 {options}").as_json()
    del result["createdDateTime"]
    assert result == expected


@pytest.mark.parametrize(
    "options",
    [
        (
            # path key is required for --file
            "--update-provider digimaun --update-name invalid --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 "
            "--file downhandler=abcd/123",
        ),
        (  # path key is required for --related-file
            "--update-provider digimaun --update-name invalid --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "--related-file properties='{\"a\": 1}'"
        ),
    ],
)
def test_adu_manifest_init_v5_invalid_path_required(options):
    assert not cli.invoke(f"iot device-update update init v5 {options}").success()
