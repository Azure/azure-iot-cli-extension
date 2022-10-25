# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.shared import DeviceAuthType
from azext_iot.constants import EDGE_ROOT_CERTIFICATE_FILENAME
from azext_iot.sdk.iothub.service.models.configuration_content_py3 import ConfigurationContent
import pytest
import json
import responses
import re
from azext_iot.iothub import commands_device_identity as subject
from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider, EdgeContainerAuth, NestedEdgeDeviceConfig
from azext_iot.tests.conftest import fixture_cmd, mock_target

from azure.cli.core.azclierror import (
    FileOperationError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError
)

from shutil import rmtree

hub_name = "myhub"
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
            url=re.compile(r"{}/dev\d+".format(devices_url)),
            body="{}",
            status=204,
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

        # GET specific devices
        mocked_response.add(
            method=responses.GET,
            url=re.compile(r"{}/dev\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Create / Update device-identity
        mocked_response.add(
            method=responses.PUT,
            url=re.compile(r"{}/dev\d+".format(devices_url)),
            body=json.dumps(
                {"authentication": {"symmetricKey": {"primaryKey": "devicePrimaryKey"}}}
            ),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "devices, config, visualize, clean",
        [([["id=dev1", "parent=dev2"], ["id=dev2"]], None, False, True)],
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
        rmtree("device_bundles")


class TestHierarchyCreateFailures:
    @pytest.mark.parametrize(
        "devices, config, root_cert, root_key, exception",
        [
            # No devices
            (None, None, None, None, InvalidArgumentValueError),
            # Missing Device Id
            ([["parent=dev2"], ["id=dev2"]], None, None, None, InvalidArgumentValueError),
            # Loop
            (
                [["id=dev1", "parent=dev2"], ["id=dev2", "parent=dev1"]],
                None,
                None,
                None,
                InvalidArgumentValueError,
            ),
            # duplicate device
            (
                [
                    ["id=dev1", "parent=dev2"],
                    ["id=dev2"],
                    ["id=dev1"],
                ],
                None,
                None,
                None,
                InvalidArgumentValueError,
            ),
            # missing parent
            (
                [
                    ["id=dev1", "parent=dev3"],
                    ["id=dev2"],
                    ["id=dev4"],
                ],
                None,
                None,
                None,
                InvalidArgumentValueError,
            ),
            # devices AND config
            (
                [
                    ["id=dev1", "parent=dev2"],
                    ["id=dev2"],
                ],
                "path-to-config.yml",
                None,
                None,
                MutuallyExclusiveArgumentError,
            ),
            # invalid deployment path
            (
                [
                    ["id=dev1", "parent=dev2", "deployment=path_does_not_exist.json"],
                    ["id=dev2"],
                ],
                None,
                None,
                None,
                FileOperationError,
            ),
            # invalid deployment JSON
            (
                [
                    [
                        "id=dev1",
                        "parent=dev2",
                        "deployment=./hierarchy_configs/invalid/invalid_deployment.json",
                    ],
                    ["id=dev2"],
                ],
                None,
                None,
                None,
                InvalidArgumentValueError,
            ),
            # root cert but not key
            (
                [
                    ["id=dev1"],
                ],
                None,
                "root_cert.pem",
                None,
                RequiredArgumentMissingError
            ),
            # missing cert paths
            (
                [
                    ["id=dev1"],
                ],
                None,
                "root_cert.pem",
                "root_key.pem",
                FileOperationError
            ),
        ],
    )
    def test_edge_hierarchy_create_arg_failures(
        self, fixture_cmd, fixture_ghcs, set_cwd, devices, config, root_cert, root_key, exception
    ):
        with pytest.raises(exception):
            subject.iot_edge_hierarchy_create(
                cmd=fixture_cmd,
                devices=devices,
                config_file=config,
                root_cert_path=root_cert,
                root_key_path=root_key
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
                    ["id=dev1", "parent=dev2"],
                    ["id=dev2"],
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
    def test_edge_hierarchy_create_config_failures(
        self, fixture_ghcs, set_cwd, devices, config, exception
    ):
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
            url=re.compile(r"{}/device_\d+".format(devices_url)),
            body="{}",
            status=204,
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
            url=re.compile(r"{}/device_\d+".format(devices_url)),
            body=json.dumps(
                {"authentication": {"symmetricKey": {"primaryKey": "devicePrimaryKey"}}}
            ),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # GET specific device
        mocked_response.add(
            method=responses.GET,
            url=re.compile(r"{}/device_\d+".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Update config content / set modules
        mocked_response.add(
            method=responses.POST,
            url=re.compile(
                r"{}/device_\d+/applyConfigurationContent".format(devices_url)
            ),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "devices, config, visualize, clean",
        [
            (None, "hierarchy_configs/nested_edge_config.yml", False, True),
            (None, "hierarchy_configs/nested_edge_config.json", True, True),
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
        rmtree("device_bundles")


class TestEdgeHierarchyConfigFunctions:

    test_device_id = "test_device_id"
    device_config_with_parent_no_agent = NestedEdgeDeviceConfig(
        device_id=test_device_id,
        parent_id="parent_device_id",
        parent_hostname="parentHostname",
        hostname="hostname"
    )
    device_config_container_auth_with_agent_no_parent = NestedEdgeDeviceConfig(
        device_id=test_device_id,
        container_auth = EdgeContainerAuth(
            serveraddress="test-container-registry-address",
            username="container registry username",
            password="container registry password"
        ),
        edge_agent="special-edge-agent"
    )

    @pytest.mark.parametrize(
        "device_id, auth_method, device_config, default_edge_agent, device_config_path, device_pk, output_path",
        [
            # load external TOML, key auth
            (test_device_id, DeviceAuthType.shared_private_key.value, device_config_with_parent_no_agent, "default-edge-agent", "./hierarchy_configs/device_config.toml", "test-device-pk", None),
            # load default TOML, cert auth
            (test_device_id, DeviceAuthType.x509_ca.value, device_config_container_auth_with_agent_no_parent, "default-edge-agent", None, None, "output_device_configs"),
        ],
    )
    def test_create_edge_device_config(
        self,
        set_cwd,
        fixture_ghcs,
        device_id,
        auth_method,
        device_config,
        default_edge_agent,
        device_config_path,
        device_pk,
        output_path,
    ):
        provider = DeviceIdentityProvider(fixture_cmd, hub_name, resource_group_name)
        device_toml = provider.create_edge_device_config(
            device_id=device_id,
            auth_method=auth_method,
            device_config=device_config,
            default_edge_agent=default_edge_agent,
            device_config_path=device_config_path,
            device_pk=device_pk,
            output_path=output_path,
        )

        # always assert
        assert (
            device_toml["trust_bundle_cert"]
            == f"file:///etc/aziot/certificates/{EDGE_ROOT_CERTIFICATE_FILENAME}"
        )
        assert device_toml["auto_reprovisioning_mode"] == "Dynamic"
        assert device_toml["edge_ca"] == {
            "cert": f"file:///etc/aziot/certificates/{device_id}.full-chain.cert.pem",
            "pk": f"file:///etc/aziot/certificates/{device_id}.key.pem",
        }

        assert device_toml["hostname"] == (
            device_config.hostname if device_config.hostname else "{{HOSTNAME}}"
        )

        # parent hostname config
        if device_config.parent_id:
            assert device_toml["parent_hostname"] == (
                device_config.parent_hostname
                if device_config.parent_hostname
                else "{{PARENT_HOSTNAME}}"
            )

        # hub provisioning
        assert device_toml["provisioning"]["device_id"] == device_id
        assert device_toml["provisioning"]["iothub_hostname"] == hub_entity
        assert device_toml["provisioning"]["source"] == "manual"

        auth = device_toml["provisioning"]["authentication"]
        if auth_method == DeviceAuthType.shared_private_key.value:
            assert auth == {"device_id_pk": {"value": device_pk}, "method": "sas"}
        else:
            assert auth == {
                "method": "x509",
                "identity_cert": f"file:///etc/aziot/certificates/{device_id}.hub-auth-cert.pem",
                "identity_pk": f"file:///etc/aziot/certificates/{device_id}.hub-auth-key.pem",
            }

        assert device_toml["agent"]["config"]["image"] == (
            device_config.edge_agent if device_config.edge_agent else default_edge_agent
        )

        if not device_config.container_auth:
            assert device_toml["agent"]["config"]["auth"] == {}
        else:
            assert device_toml["agent"]["config"]["auth"]["serveraddress"] == device_config.container_auth.serveraddress
            assert device_toml["agent"]["config"]["auth"]["username"] == device_config.container_auth.username
            assert device_toml["agent"]["config"]["auth"]["password"] == device_config.container_auth.password

        if output_path:
            import toml
            from os.path import join
            path = join(output_path, 'config.toml')
            with open(path, 'rt', encoding="utf-8") as f:
                assert toml.dumps(device_toml) == f.read()
            rmtree(output_path)


    @pytest.mark.parametrize("deployment, error", 
    [
        ("hierarchy_configs/invalid/invalid_deployment.json", InvalidArgumentValueError),
        ("path_does_not_exist.json", FileOperationError),
        ("hierarchy_configs/deploymentLowerLayer.json", None)
    ])
    def test_process_edge_config_content(self, fixture_ghcs, set_cwd, deployment, error):
        provider = DeviceIdentityProvider(fixture_cmd, hub_name, resource_group_name)
        try:
            config_content = provider._try_parse_valid_deployment_config(deployment)
            assert isinstance(config_content, ConfigurationContent)
        except error as ex:
            assert isinstance(ex, error)
