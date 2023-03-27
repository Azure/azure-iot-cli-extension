# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
import json
from pathlib import PurePath
from typing import List
from knack.log import get_logger
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.conftest import get_context_path, generate_generic_id

cli = EmbeddedCLI()

logger = get_logger(__name__)

# TODO: Research https://github.com/pytest-dev/pytest-xdist/issues/432
# unique_description = f"{generate_generic_id()} {generate_generic_id()}"[:-2]
# unique_properties = {generate_generic_id(): generate_generic_id(), generate_generic_id(): unique_description}
sample_properties = {"property1": "value1", "property2": 2, "property3": {"a": "b"}}


@pytest.mark.parametrize(
    "options, expected",
    [
        (
            "--update-provider digimaun0 --update-name simpleaptupdate --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            '--step handler=custom/handler:1 properties=\'{"installedCriteria":"2.0"}\' '
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\"",
            {
                "updateId": {"provider": "digimaun0", "name": "simpleaptupdate", "version": "1.0.0"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Vacuum"},
                ],
                "instructions": {
                    "steps": [
                        {
                            # Ensures custom handler can be used.
                            "handler": "custom/handler:1",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "2.0"},
                            "type": "inline",
                        }
                    ]
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
            "--update-provider digimaun0 --update-name simpleaptupdate --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            '--step handler=microsoft/apt:1 properties=\'{"installedCriteria":"2.0"}\' '
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\"",
            {
                "updateId": {"provider": "digimaun0", "name": "simpleaptupdate", "version": "1.0.0"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Vacuum"},
                ],
                "instructions": {
                    "steps": [
                        {
                            # Tests that user input installedCriteria does not get clobbered.
                            "handler": "microsoft/apt:1",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "2.0"},
                            "type": "inline",
                        }
                    ]
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
                    # handlerProperties.installedCriteria has been added automatically for specific content handlers.
                    "steps": [
                        {
                            "handler": "microsoft/apt:1",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        }
                    ]
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
            "--update-provider digimaun0 --update-name simplescriptupdate --update-version 1.0 "
            f"--description 'my update description' "
            "--compat manufacturer=Contoso model=Vacuum "
            f"--step handler=microsoft/script:1 description='my step description' "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            f"properties='{json.dumps(sample_properties)}' "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'simple_apt_manifest_v5.json')}\" "
            f"properties='{json.dumps(sample_properties)}' "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'parent.importmanifest.json')}\" "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" ",
            {
                "updateId": {"provider": "digimaun0", "name": "simplescriptupdate", "version": "1.0"},
                "description": "my update description",
                "compatibility": [
                    {"manufacturer": "Contoso", "model": "Vacuum"},
                ],
                "instructions": {
                    "steps": [
                        {
                            # handlerProperties.installedCriteria not required/auto-added for microsoft/script:1
                            "handler": "microsoft/script:1",
                            "files": ["libcurl4-doc-apt-manifest.json", "action.sh"],
                            "type": "inline",
                            "description": "my step description",
                        }
                    ]
                },
                "files": [
                    {
                        "filename": "libcurl4-doc-apt-manifest.json",
                        "sizeInBytes": 163,
                        "hashes": {"sha256": "iFWTIaxp33tf5BR1w0fMmnnHpjsUjLRQ9eZFjw74LbU="},
                        "properties": sample_properties,
                        "relatedFiles": [
                            {
                                "filename": "simple_apt_manifest_v5.json",
                                "sizeInBytes": 1031,
                                "hashes": {"sha256": "L+ZKmOOT3xRfHsFK7pcTXBLjeI2OFCW0855qIcV5sts="},
                                "properties": sample_properties,
                            },
                            {
                                "filename": "parent.importmanifest.json",
                                "sizeInBytes": 1390,
                                "hashes": {"sha256": "hos1UvCk66WmtL/SPNUmub+k302BM4gtWYtAF7tOCb4="},
                            },
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
        (
            "--update-provider digimaun1 --update-name Microphone --update-version 2.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Microphone "
            '--step handler=microsoft/swupdate:1 properties=\'{"arguments": "--pre"}\' '
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'install.sh')}\" "
            "--is-deployable false",
            {
                "updateId": {"provider": "digimaun1", "name": "Microphone", "version": "2.0.0"},
                "compatibility": [
                    {"deviceManufacturer": "Contoso", "deviceModel": "Microphone"},
                ],
                "instructions": {
                    "steps": [
                        {
                            # Ensures handlerProperties addition is merged with existing input.
                            "handler": "microsoft/swupdate:1",
                            "handlerProperties": {"installedCriteria": "1.0", "arguments": "--pre"},
                            "files": ["action.sh", "install.sh"],
                            "type": "inline",
                        }
                    ]
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
        (
            "--update-provider digimaun0 --update-name swupdatev2 --update-version 0.1 "
            "--compat manufacturer=Contoso model=Vacuum "
            "--step handler=microsoft/swupdate:2 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'action.sh')}\" ",
            {
                "updateId": {"provider": "digimaun0", "name": "swupdatev2", "version": "0.1"},
                "compatibility": [
                    {"manufacturer": "Contoso", "model": "Vacuum"},
                ],
                "instructions": {
                    # handlerProperties.installedCriteria has been added automatically for specific content handlers.
                    "steps": [
                        {
                            "handler": "microsoft/swupdate:2",
                            # Duplicate file names should not exist in same step{}.
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        }
                    ]
                },
                "files": [
                    # Duplicate file names should not exist in files[].
                    {
                        "filename": "libcurl4-doc-apt-manifest.json",
                        "sizeInBytes": 163,
                        "hashes": {"sha256": "iFWTIaxp33tf5BR1w0fMmnnHpjsUjLRQ9eZFjw74LbU="},
                        "relatedFiles": [
                            # Duplicated related file names should not exist in relatedFiles[]
                            {
                                "filename": "action.sh",
                                "sizeInBytes": 33,
                                "hashes": {"sha256": "n+KGjLjSGr7LVKsgWiExUDeU6Z2ZTJu0tpAWxkmYKxA="},
                            },
                        ],
                    }
                ],
                "manifestVersion": "5.0",
            },
        ),
        (
            "--update-provider digimaun0 --update-name swupdatev2 --update-version 0.1 "
            "--compat manufacturer=Contoso model=Vacuum "
            "--step handler=microsoft/swupdate:2 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "--step handler=microsoft/swupdate:2 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" ",
            {
                "updateId": {"provider": "digimaun0", "name": "swupdatev2", "version": "0.1"},
                "compatibility": [
                    {"manufacturer": "Contoso", "model": "Vacuum"},
                ],
                "instructions": {
                    # handlerProperties.installedCriteria has been added automatically for specific content handlers.
                    "steps": [
                        {
                            "handler": "microsoft/swupdate:2",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        },
                        {
                            "handler": "microsoft/swupdate:2",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        },
                    ]
                },
                "files": [
                    # Duplicate file names should not exist in files[].
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
            "--update-provider digimaun0 --update-name swupdatev2 --update-version 0.1 "
            "--compat manufacturer=Contoso model=Vacuum "
            "--compat ring=0 tier=test "
            "--step handler=microsoft/swupdate:2 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "--step handler=microsoft/swupdate:2 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            f"--related-file path=\"{get_context_path(__file__, 'manifests', 'surface15', 'parent.importmanifest.json')}\" ",
            {
                "updateId": {"provider": "digimaun0", "name": "swupdatev2", "version": "0.1"},
                "compatibility": [
                    {"manufacturer": "Contoso", "model": "Vacuum"},
                    {"ring": "0", "tier": "test"},
                ],
                "instructions": {
                    # handlerProperties.installedCriteria has been added automatically for specific content handlers.
                    "steps": [
                        {
                            "handler": "microsoft/swupdate:2",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        },
                        {
                            "handler": "microsoft/swupdate:2",
                            "files": ["libcurl4-doc-apt-manifest.json"],
                            "handlerProperties": {"installedCriteria": "1.0"},
                            "type": "inline",
                        },
                    ]
                },
                "files": [
                    # Duplicate file names should not exist in files[], but last --file with same name wins.
                    {
                        "filename": "libcurl4-doc-apt-manifest.json",
                        "sizeInBytes": 163,
                        "hashes": {"sha256": "iFWTIaxp33tf5BR1w0fMmnnHpjsUjLRQ9eZFjw74LbU="},
                        "relatedFiles": [
                            {
                                "filename": "parent.importmanifest.json",
                                "sizeInBytes": 1390,
                                "hashes": {"sha256": "hos1UvCk66WmtL/SPNUmub+k302BM4gtWYtAF7tOCb4="},
                            }
                        ],
                    }
                ],
                "manifestVersion": "5.0",
            },
        ),
    ],
)
def test_adu_manifest_init_v5(options, expected):
    result = cli.invoke(f"iot du update init v5 {options}").as_json()
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
            "--file downhandler=abcd/123"
        ),
        (
            # path key is required for --related-file
            "--update-provider digimaun --update-name invalid --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "--related-file properties='{\"a\": 1}'"
        ),
        (
            # Usage of --step requires at least an entry of handler=<value> for an inline step or
            # all of updateId.provider=<value>, updateId.name=<value>, updateId.version=<value> for a reference step.
            "--update-provider digimaun --update-name invalid --update-version 1.0.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step stuff=things "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
        ),
    ],
)
def test_adu_manifest_init_v5_invalid_path_required(options):
    assert not cli.invoke(f"iot du update init v5 {options}", capture_stderr=True).success()


@pytest.mark.parametrize(
    "options, no_validation",
    [
        (
            # No files array provided for in-line step.
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 ",
            False,
        ),
        (
            # Too long of a provider value.
            "--update-provider digimaundigimaundigimaundigimaundigimaundigimaundigimaundigimaunn "
            "--update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 files=hello.json",
            False,
        ),
        (
            # Too long of a compat property value.
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=ContosoContosoContosoContosoContosoContosoContosoContosoContosooo "
            "--step handler=microsoft/apt:1 files=hello.json",
            False,
        ),
        (
            # Bad version value.
            "--update-provider digimaun --update-name invalid --update-version 1 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 ",
            False,
        ),
        (
            # Too short file downloadHandler value.
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=ContosoContosoContosoContosoContosoContoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "downloadHandler=abc",
            False,
        ),
        (
            # Same as prior test case but disable client-side validation.
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=ContosoContosoContosoContosoContosoContoso deviceModel=Vacuum "
            "--step handler=microsoft/apt:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" "
            "downloadHandler=abc",
            True,
        ),
        (
            # If content handler starts with microsoft (case-insensitive) enforce valid value.
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/fake:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" ",
            False,
        ),
        (
            # Same as prior test case but ensure escape hatch with --no-validation
            "--update-provider digimaun --update-name invalid --update-version 1.0 "
            "--compat deviceManufacturer=Contoso deviceModel=Vacuum "
            "--step handler=microsoft/fake:1 "
            f"--file path=\"{get_context_path(__file__, 'manifests', 'libcurl4-doc-apt-manifest.json')}\" ",
            False,
        ),
    ],
)
def test_adu_manifest_init_v5_validate_errors(options, no_validation):
    if no_validation:
        assert cli.invoke(f"iot du update init v5 {options} --no-validation").success()
    else:
        assert not cli.invoke(f"iot du update init v5 {options}", capture_stderr=True).success()


@pytest.mark.parametrize(
    "files_count, expected_bytes",
    [
        (1, 1024),
        (2, 512),
        (3, 256),
        (1, 4097),  # 1 additional byte over chunk size.
    ],
)
def test_adu_manifest_calculate_hash(files_count, expected_bytes):
    from azext_iot.deviceupdate.providers.base import DeviceUpdateDataManager, FileMetadata

    normalized_paths: List[PurePath] = []
    metadata: List[FileMetadata] = []
    for i in range(files_count):
        content_file_path = PurePath(get_context_path(__file__, "manifests", generate_generic_id()))
        target_bytes = os.urandom(expected_bytes)
        with open(content_file_path, "w+b") as f:
            f.write(target_bytes)
            f.seek(0)
            file_bytes: bytes = f.read()

        normalized_paths.append(content_file_path)
        metadata.append(
            FileMetadata(
                len(file_bytes),
                DeviceUpdateDataManager.calculate_hash_from_bytes(file_bytes),
                content_file_path.name,
                content_file_path,
            )
        )

    cli_path_input = ""
    for p in normalized_paths:
        cli_path_input = cli_path_input + f" --file-path '{str(p)}'"

    result = cli.invoke(f"iot du update calculate-hash {cli_path_input}").as_json()

    for i in range(files_count):
        assert result[i]["hashAlgorithm"] == "sha256"
        assert result[i]["uri"] == normalized_paths[i].as_uri()
        assert result[i]["hash"] == metadata[i].hash
        assert result[i]["bytes"] == metadata[i].bytes

        if os.path.exists(normalized_paths[i]):
            os.remove(normalized_paths[i])
