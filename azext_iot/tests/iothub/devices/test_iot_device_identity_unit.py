# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import responses
import re
from azext_iot.iothub import commands_device_identity as subject
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.iothub.providers import device_identity as provider
from azext_iot.tests.conftest import fixture_cmd, fixture_ghcs, fixture_sas, mock_target

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
)


hub_name = 'myhub'
#myhub.azuredevices.net
hub_entity = mock_target["entity"]
resource_group_name = "RESOURCEGROUP"


class TestEdgeHierarchyCreateArgs:
    @pytest.fixture()
    def service_client(self, mocked_response, fixture_ghcs, fixture_sas):
        mocked_response.assert_all_requests_are_fired = False
        devices_url = f"https://{hub_entity}/devices"
        # Query devices
        mocked_response.add(
            method=responses.POST,
            url=f"{devices_url}/query",
            body=json.dumps(
                [
                    {"deviceId": "dev1", "deviceScope": "dev1-scope-value"},
                    {"deviceId": "dev2", "deviceScope": "dev2-scope-value"},
                ]
            ),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # delete any existing devices
        mocked_response.add(
            method=responses.DELETE,
            url=re.compile("{}/dev\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # GET existing devices
        mocked_response.add(
            method=responses.GET,
            url=devices_url,
            body="[]",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Create / Update device-identity
        mocked_response.add(
            method=responses.PUT,
            url=re.compile("{}/dev\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "devices, config, visualize, clean",
        [([["device_id=dev1", "parent=dev2"], ["device_id=dev2"]], None, False, True)],
    )
    def test_edge_hierarchy_create_args(
        self, fixture_cmd, service_client, devices, config, visualize, clean
    ):
        subject.iot_edge_hierarchy_create(
            cmd=fixture_cmd,
            devices=devices,
            config_file=config,
            visualize=visualize,
            clean=clean,
        )

class TestHierarchyCreateFailures:
    @pytest.mark.parametrize(
        "devices, config, exception",
        [
            # No devices
            (None, None, InvalidArgumentValueError),
            # Missing Device Id
            (
                [["parent=dev2"], ["device_id=dev2"]],
                None,
                InvalidArgumentValueError
            ),
            # Loop
            (
                [["device_id=dev1", "parent=dev2"], ["device_id=dev2", "parent=dev1"]],
                None,
                InvalidArgumentValueError,
            ),
            # duplicate device
            (
                [
                    ["device_id=dev1", "parent=dev2"],
                    ["device_id=dev2"],
                    ["device_id=dev1"],
                ],
                None,
                InvalidArgumentValueError,
            ),
            # missing parent
            (
                [
                    ["device_id=dev1", "parent=dev3"],
                    ["device_id=dev2"],
                    ["device_id=dev4"],
                ],
                None,
                InvalidArgumentValueError,
            ),
            # devices AND config
            (
                [
                    ["device_id=dev1", "parent=dev2"],
                    ["device_id=dev2"],
                ],
                "path-to-config.yml",
                MutuallyExclusiveArgumentError,
            ),
        ],
    )
    def test_edge_hierarchy_create_arg_failures(
        self, fixture_cmd, fixture_ghcs, devices, config, exception
    ):
        with pytest.raises(exception):
            subject.iot_edge_hierarchy_create(
                cmd=fixture_cmd,
                devices=devices,
                config_file=config,
            )

    @pytest.mark.parametrize(
        "devices, config, exception",
        [
            # No devices
            (None, None, InvalidArgumentValueError),
            # duplicate device
            (
                None,
                "hierarchy_configs/invalid/duplicate_device_config.yml",
                InvalidArgumentValueError,
            ),
            # missing device ID
            (
                None,
                "hierarchy_configs/invalid/missing_device_id.yml",
                InvalidArgumentValueError,
            ),
            # devices AND config
            (
                [
                    ["device_id=dev1", "parent=dev2"],
                    ["device_id=dev2"],
                ],
                "hierarchy_configs/nested_edge_config.yml",
                MutuallyExclusiveArgumentError,
            ),
            # invalid file format
            (
                None,
                "hierarchy_configs/nested_edge_config.txt",
                InvalidArgumentValueError,
            ),
        ],
    )
    def test_edge_hierarchy_create_config_failures(self, fixture_ghcs, set_cwd, devices, config, exception):
        with pytest.raises(exception):
            subject.iot_edge_hierarchy_create(
                cmd=fixture_cmd,
                devices=devices,
                config_file=config,
            )

class TestHierarchyCreateConfig:
    @pytest.fixture()
    def service_client(self, mocked_response, fixture_ghcs, fixture_sas):
        mocked_response.assert_all_requests_are_fired = False
        devices_url = f"https://{hub_entity}/devices"
        # Query devices
        mocked_response.add(
            method=responses.POST,
            url=f"{devices_url}/query",
            body=json.dumps(
                [
                    {"deviceId": "device_1", "deviceScope": "dev1-scope-value"},
                    {"deviceId": "device_2", "deviceScope": "dev2-scope-value"},
                    {"deviceId": "device_3", "deviceScope": "dev3-scope-value"},
                    {"deviceId": "device_4", "deviceScope": "dev4-scope-value"},
                    {"deviceId": "device_5", "deviceScope": "dev5-scope-value"},
                    {"deviceId": "device_6", "deviceScope": "dev6-scope-value"},
                    {"deviceId": "device_7", "deviceScope": "dev7-scope-value"},
                ]
            ),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # delete any existing devices
        mocked_response.add(
            method=responses.DELETE,
            url=re.compile("{}/device_\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # GET existing devices
        mocked_response.add(
            method=responses.GET,
            url=devices_url,
            body="[]",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Create / Update device-identity
        mocked_response.add(
            method=responses.PUT,
            url=re.compile("{}/device_\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Update config content / set modules
        mocked_response.add(
            method=responses.POST,
            url=re.compile("{}/device_\d+/applyConfigurationContent".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "devices, config, visualize, clean",
        [
            (None, "hierarchy_configs/nested_edge_config.yml", False, True),
            (None, "hierarchy_configs/nested_edge_config.json", False, True)
        ],
    )
    def test_edge_hierarchy_create_config(
        self, fixture_cmd, service_client, set_cwd, devices, config, visualize, clean
    ):
        subject.iot_edge_hierarchy_create(
            cmd=fixture_cmd,
            devices=devices,
            config_file=config,
            visualize=visualize,
            clean=clean,
        )

@pytest.mark.skip('Not yet used')
class TestBulkDeviceCRUD:
    @pytest.fixture()
    def service_client(self, mocked_response, fixture_ghcs, fixture_sas):
        devices_url = f"https://{hub_entity}/devices"

        yield mocked_response

    @pytest.mark.parametrize(
        "device_ids, confirm", 
        [
            (['device_1', 'device_2'], True),
            (['device_1', 'device_2'], False)
        ]
    )
    def test_bulk_delete_devices(self, fixture_cmd, service_client, device_ids, confirm):
        subject.iot_bulk_delete_devices(
            cmd=fixture_cmd,
            device_ids=device_ids,
            confirm=confirm
        )

    @pytest.mark.parametrize(
        "device_ids, confirm", 
        [
            (['device_1', 'device_2'], True),
            (['device_1', 'device_2'], False)
        ]
    )
    def test_bulk_delete_devices(self, fixture_cmd, service_client, device_ids, confirm):
        subject.iot_bulk_delete_devices(
            cmd=fixture_cmd,
            device_ids=device_ids,
            confirm=confirm
        )