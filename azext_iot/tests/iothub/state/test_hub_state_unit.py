# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
import azext_iot.iothub.commands_state as subject
from azure.cli.core.azclierror import (
    FileOperationError,
    BadRequestError,
    MutuallyExclusiveArgumentError
)
import azext_iot.iothub.providers.helpers.state_strings as constants

from azext_iot.tests.conftest import generate_cs
from azext_iot.iothub.providers.state import StateProvider, _endpoint_resource_name

hub_name = "hubname"
hub_rg = "hubrg"
resource_not_found_error = "Resource not found."


def _build_device_twin(device_id="device1", auth_type="sas", include_thumbprint=True):
    """Minimal device twin shaped like the output of `_iot_device_twin_list`."""
    twin = {
        "deviceId": device_id,
        "authenticationType": auth_type,
        "properties": {
            "desired": {"$metadata": {}, "$version": 1},
            "reported": {},
        },
    }
    if include_thumbprint:
        twin["x509Thumbprint"] = {
            "primaryThumbprint": "AAAA",
            "secondaryThumbprint": "BBBB",
        }
    return twin


class TestHubStateExport:
    def test_present_file_no_replace(self, fixture_cmd, fixture_ghcs, mocker):
        patched_prompt_y_n = mocker.patch("azext_iot.iothub.providers.state.prompt_y_n")
        patched_prompt_y_n.return_value = False

        # make a temporary file
        fake_file = "fake_file.json"
        with open(fake_file, "w", encoding='utf-8') as f:
            f.write("Hello World")

        with pytest.raises(FileOperationError) as error:
            subject.state_export(
                cmd=fixture_cmd,
                state_file=fake_file,
                hub_name_or_hostname="someHub",
                resource_group_name="somerg"
            )
        assert constants.FILE_NOT_EMPTY_ERROR == str(error.value)

        if os.path.isfile(fake_file):
            os.remove(fake_file)

    def test_hub_login_with_arm_aspects(self, fixture_cmd, fixture_ghcs):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_export(
                cmd=fixture_cmd,
                state_file="./file.json",
                login=generate_cs(),
                replace=True
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)


class TestHubStateImport:
    def test_missing_file(self, fixture_cmd, fixture_ghcs):
        file_name = "./file.json"
        with pytest.raises(FileOperationError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file="./file.json",
                hub_name_or_hostname="someHub",
                resource_group_name="somerg"
            )
        assert constants.FILE_NOT_FOUND_ERROR.format(file_name) == str(error.value)

    def test_hub_login_with_arm_aspects(self, fixture_cmd, fixture_ghcs):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file="./file.json",
                login=generate_cs()
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)

    def test_missing_arm_file(self, fixture_cmd, fixture_ghcs_resource_not_found_error):
        hub_name = "someHub"
        # make a temporary file
        fake_file = "fake_file.json"
        with open(fake_file, "w", encoding='utf-8') as f:
            f.write("{}")

        with pytest.raises(BadRequestError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file=fake_file,
                hub_name_or_hostname=hub_name,
                resource_group_name="somerg"
            )
        assert constants.HUB_NOT_CREATED_MSG.format(hub_name) == str(error.value)

        if os.path.isfile(fake_file):
            os.remove(fake_file)


class TestHubStateMigrate:
    def test_hub_login_with_arm_aspects(self, fixture_cmd, fixture_ghcs):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_migrate(
                cmd=fixture_cmd,
                login=generate_cs(),
                orig_hub_login=generate_cs()
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)


class TestDownloadDevicesThumbprint:
    """`state export` must not crash on twins that lack an x509Thumbprint (issue #746)."""

    def _patch_device_calls(self, mocker, twins):
        mocker.patch(
            "azext_iot.iothub.providers.state._iot_device_twin_list", return_value=twins
        )
        mocker.patch(
            "azext_iot.iothub.providers.state._iot_device_show",
            return_value={"authentication": {"symmetricKey": {"primaryKey": "pk", "secondaryKey": "sk"}}},
        )
        mocker.patch(
            "azext_iot.iothub.providers.state._iot_device_module_list", return_value=[]
        )

    def test_missing_thumbprint_does_not_raise(self, mocker):
        # a twin without the x509Thumbprint key previously raised KeyError: 'x509Thumbprint'
        self._patch_device_calls(mocker, [_build_device_twin(include_thumbprint=False)])

        provider = StateProvider.__new__(StateProvider)
        devices = provider.download_devices(target={})

        assert "device1" in devices
        thumbprint = devices["device1"]["identity"]["authentication"]["x509Thumbprint"]
        assert thumbprint == {"primaryThumbprint": None, "secondaryThumbprint": None}

    def test_present_thumbprint_is_preserved(self, mocker):
        self._patch_device_calls(mocker, [_build_device_twin(include_thumbprint=True)])

        provider = StateProvider.__new__(StateProvider)
        devices = provider.download_devices(target={})

        thumbprint = devices["device1"]["identity"]["authentication"]["x509Thumbprint"]
        assert thumbprint == {"primaryThumbprint": "AAAA", "secondaryThumbprint": "BBBB"}

    def test_mixed_devices_all_exported(self, mocker):
        # one bad device must not abort the export of the rest
        self._patch_device_calls(
            mocker,
            [
                _build_device_twin(device_id="withThumbprint", include_thumbprint=True),
                _build_device_twin(device_id="noThumbprint", include_thumbprint=False),
            ],
        )

        provider = StateProvider.__new__(StateProvider)
        devices = provider.download_devices(target={})

        assert set(devices.keys()) == {"withThumbprint", "noThumbprint"}


class TestEndpointHostNameParsing:
    """routing-endpoint host-name extraction used by state export."""

    @pytest.mark.parametrize(
        "endpoint_uri, expected",
        [
            # Service Bus / Event Hub (sb://)
            ("sb://scyhbus.servicebus.windows.net/", "scyhbus"),
            ("sb://bhub.servicebus.windows.net/", "bhub"),
            ("sb://sbnamespace.servicebus.windows.net/", "sbnamespace"),
            ("sb://normal.servicebus.windows.net/", "normal"),
            # Cosmos DB / Storage (https://)
            ("https://sstorage.blob.core.windows.net/", "sstorage"),
            ("https://tcosmos.documents.azure.com:443/", "tcosmos"),
            ("https://httpsaccount.blob.core.windows.net/", "httpsaccount"),
            ("https://plainaccount.documents.azure.com:443/", "plainaccount"),
            # Port must be stripped
            ("sb://sbwithport.servicebus.windows.net:5671/", "sbwithport"),
            ("sb://MixedCase.servicebus.windows.net/", "mixedcase"),
        ],
    )
    def test_host_name_not_corrupted(self, endpoint_uri, expected):
        assert _endpoint_resource_name(endpoint_uri) == expected
