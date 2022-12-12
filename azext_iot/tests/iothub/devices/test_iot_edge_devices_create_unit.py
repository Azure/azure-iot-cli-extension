# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import responses
import re
from os.path import exists, join
from azext_iot.common.certops import create_v3_self_signed_root_certificate
from azext_iot.common.fileops import write_content_to_file
from azext_iot.common.shared import DeviceAuthType
from azext_iot.common.utility import process_json_arg, process_yaml_arg
from azext_iot.sdk.iothub.service.models import ConfigurationContent
from azext_iot.iothub import commands_device_identity as subject
from azext_iot.iothub.providers.helpers.edge_device_config import (
    EDGE_CONFIG_SCRIPT_APPLY,
    EDGE_CONFIG_SCRIPT_CA_CERTS,
    EDGE_CONFIG_SCRIPT_HEADERS,
    EDGE_CONFIG_SCRIPT_HOSTNAME,
    EDGE_CONFIG_SCRIPT_HUB_AUTH_CERTS,
    EDGE_CONFIG_SCRIPT_PARENT_HOSTNAME,
    EDGE_ROOT_CERTIFICATE_FILENAME,
    create_edge_device_config_script,
    process_edge_devices_config_args,
    process_edge_devices_config_file_content,
    create_edge_device_config,
    try_parse_valid_deployment_config,
)
from azext_iot.iothub.common import (
    EdgeContainerAuth,
    EdgeDevicesConfig,
    EdgeDeviceConfig,
)
from azext_iot.tests.conftest import fixture_cmd, mock_target

from azure.cli.core.azclierror import (
    FileOperationError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)

from shutil import rmtree

hub_name = "myhub"
hub_entity = mock_target["entity"]
resource_group_name = "RESOURCEGROUP"
mock_container_auth = {
    "serverAddress": "serverAddress",
    "username": "username",
    "password": "$credential$",
}


test_certs_folder = "./test_certs"
test_root_cert = "root-cert.pem"
test_root_key = "root-key.pem"


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

        # Update config content / set modules
        mocked_response.add(
            method=responses.POST,
            url=re.compile(r"{}/dev\d+/applyConfigurationContent".format(devices_url)),
            body="{}",
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.mark.parametrize(
        "devices, config, visualize, clean, auth, output",
        [
            # basic example, default auth, should output no files
            ([["id=dev1", "parent=dev2"], ["id=dev2"]], None, False, True, None, None),
            # Visualize, no clean, certificate auth, specified output
            (
                [["id=dev3"]],
                None,
                True,
                False,
                DeviceAuthType.x509_thumbprint.value,
                "device_bundles",
            ),
            # Flex argument processing
            (
                [
                    [
                        "id=dev4",
                        "hostname=device-hostname",
                        "deployment=device_configs/deploymentTopLayer.json",
                        "edge_agent=my-edge-agent",
                        f"container_auth={json.dumps(mock_container_auth)}",
                    ],
                    [
                        "id=dev5",
                        "hostname=device-hostname",
                        "deployment=device_configs/deploymentTopLayer.json",
                        "edge_agent=my-edge-agent",
                        "container_auth=device_configs/fake_edge_container_auth.json",
                    ],
                ],
                None,
                True,
                False,
                DeviceAuthType.x509_thumbprint.value,
                "new_device_bundle_folder",
            ),
        ],
    )
    def test_edge_devices_create_args(
        self,
        fixture_cmd,
        set_cwd,
        service_client,
        devices,
        config,
        visualize,
        clean,
        auth,
        output,
    ):
        subject.iot_edge_devices_create(
            cmd=fixture_cmd,
            devices=devices,
            config_file=config,
            visualize=visualize,
            clean=clean,
            # can't prompt in unit test
            yes=clean,
            device_auth_type=auth,
            bundle_output_path=output,
        )

        if output:
            assert exists(output)
            for device in devices:
                device_id = device[0].split("=")[1]
                assert exists(join(output, f"{device_id}.tgz"))

            rmtree(output)
        pass


class TestHierarchyCreateFailures:
    @pytest.mark.parametrize(
        "devices, config, root_cert, root_key, exception",
        [
            # No devices
            (None, None, None, None, InvalidArgumentValueError),
            # Missing Device Id
            (
                [["parent=dev2"], ["id=dev2"]],
                None,
                None,
                None,
                InvalidArgumentValueError,
            ),
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
                        "deployment=./device_configs/invalid/invalid_deployment.json",
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
                RequiredArgumentMissingError,
            ),
            # missing cert paths
            (
                [
                    ["id=dev1"],
                ],
                None,
                "root_cert.pem",
                "root_key.pem",
                FileOperationError,
            ),
        ],
    )
    def test_edge_devices_create_arg_failures(
        self,
        fixture_cmd,
        fixture_ghcs,
        set_cwd,
        devices,
        config,
        root_cert,
        root_key,
        exception,
    ):
        with pytest.raises(exception):
            subject.iot_edge_devices_create(
                cmd=fixture_cmd,
                devices=devices,
                config_file=config,
                root_cert_path=root_cert,
                root_key_path=root_key,
            )

    @pytest.mark.parametrize(
        "devices, config, exception",
        [
            # No devices
            (None, None, InvalidArgumentValueError),
            # duplicate device
            (
                None,
                "device_configs/invalid/duplicate_device_config.yml",
                InvalidArgumentValueError,
            ),
            # missing device ID
            (
                None,
                "device_configs/invalid/missing_device_id.yml",
                InvalidArgumentValueError,
            ),
            # devices AND config
            (
                [
                    ["id=dev1", "parent=dev2"],
                    ["id=dev2"],
                ],
                "device_configs/nested_edge_config.yml",
                MutuallyExclusiveArgumentError,
            ),
            # invalid file format
            (
                None,
                "device_configs/nested_edge_config.txt",
                InvalidArgumentValueError,
            ),
        ],
    )
    def test_edge_devices_create_config_failures(
        self, fixture_ghcs, set_cwd, devices, config, exception
    ):
        with pytest.raises(exception):
            subject.iot_edge_devices_create(
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

    @pytest.fixture()
    def mock_config_parse(self, mocker):
        from azext_iot.iothub.providers import device_identity

        return mocker.spy(device_identity, "process_edge_devices_config_file_content")

    @pytest.mark.parametrize(
        "devices, config, visualize, clean, out, auth_override, agent_override, "
        "template_override, ca_cert_override, ca_key_override",
        [  # yaml config
            (
                None,
                "device_configs/nested_edge_config.yml",
                False,
                True,
                "device_bundles",
                None,
                None,
                None,
                None,
                None,
            ),
            # yaml with auth type, device_config, and agent override
            (
                None,
                "device_configs/nested_edge_config.yml",
                False,
                True,
                "device_bundles",
                DeviceAuthType.x509_thumbprint.value,
                "custom_edge_agent",
                "./device_configs/device_config.toml",
                None,
                None
            ),
            # json config
            (
                None,
                "device_configs/nested_edge_config.json",
                True,
                True,
                "device_bundles_2",
                None,
                None,
                None,
                None,
                None,
            ),
            # json config with cert overrides
            (
                None,
                "device_configs/nested_edge_config.json",
                True,
                True,
                "device_bundles_2",
                None,
                None,
                None,
                f"{test_certs_folder}/{test_root_cert}",
                f"{test_certs_folder}/{test_root_key}"
            ),
            # no output
            (
                None,
                "device_configs/nested_edge_config.json",
                True,
                True,
                None,
                None,
                None,
                None,
                None,
                None
            ),
        ],
    )
    def test_edge_devices_create_config(
        self,
        fixture_cmd,
        mock_config_parse,
        service_client,
        set_cwd,
        devices,
        config,
        visualize,
        clean,
        out,
        auth_override,
        agent_override,
        template_override,
        ca_cert_override,
        ca_key_override
    ):

        # create cert if we need
        if ca_cert_override and ca_key_override:
            root_cert = create_v3_self_signed_root_certificate()
            write_content_to_file(
                content=root_cert["certificate"],
                destination=test_certs_folder,
                file_name=test_root_cert,
                overwrite=True,
            )
            write_content_to_file(
                content=root_cert["privateKey"],
                destination=test_certs_folder,
                file_name=test_root_key,
                overwrite=True,
            )

        subject.iot_edge_devices_create(
            cmd=fixture_cmd,
            devices=devices,
            config_file=config,
            visualize=visualize,
            clean=clean,
            # can't prompt in unit test
            yes=clean,
            bundle_output_path=out,
            device_auth_type=auth_override,
            device_config_template=template_override,
            default_edge_agent=agent_override,
            root_cert_path=ca_cert_override,
            root_key_path=ca_key_override
        )

        # remove test cert'
        if ca_cert_override and ca_key_override:
            rmtree(test_certs_folder)

        cfg_obj = (
            process_yaml_arg(config)
            if config.endswith(".yml")
            else process_json_arg(config)
        )

        # parse called with correct config
        assert mock_config_parse.call_args[1]["content"] == cfg_obj

        # assert inline overrides
        assert mock_config_parse.call_args[1]["content"] == cfg_obj
        assert mock_config_parse.call_args[1]["override_auth_type"] == auth_override
        assert (
            mock_config_parse.call_args[1]["override_default_edge_agent"]
            == agent_override
        )
        assert (
            mock_config_parse.call_args[1]["override_device_config_template"]
            == template_override
        )
        assert (
            mock_config_parse.call_args[1]["override_root_cert_path"]
            == ca_cert_override
        )
        assert (
            mock_config_parse.call_args[1]["override_root_key_path"]
            == ca_key_override
        )

        expected_devices = []

        def add_device(device):
            expected_devices.append(device["deviceId"])
            for child in device.get("children", []):
                add_device(child)

        for device in cfg_obj["edgeDevices"]:
            add_device(device)
        if out:
            assert exists(out)
            for device_id in expected_devices:
                assert exists(join(out, f"{device_id}.tgz"))

            rmtree(out)


class TestEdgeHierarchyConfigFunctions:
    def create_test_root_cert(self, path):
        root_cert = create_v3_self_signed_root_certificate()
        write_content_to_file(
            content=root_cert["certificate"],
            destination=path,
            file_name=test_root_cert,
            overwrite=True,
        )
        write_content_to_file(
            content=root_cert["privateKey"],
            destination=path,
            file_name=test_root_key,
            overwrite=True,
        )
        return root_cert

    test_device_id = "test_device_id"
    device_config_with_parent_no_agent = EdgeDeviceConfig(
        device_id=test_device_id,
        parent_id="parent_device_id",
        parent_hostname="parentHostname",
        hostname="hostname",
    )
    device_config_container_auth_with_agent_no_parent = EdgeDeviceConfig(
        device_id=test_device_id,
        container_auth=EdgeContainerAuth(
            serveraddress="test-container-registry-address",
            username="container registry username",
            password="container registry password",
        ),
        edge_agent="special-edge-agent",
    )

    @pytest.mark.parametrize(
        "device_id, auth_method, device_config, default_edge_agent, device_config_path, device_pk, output_path",
        [
            # load external TOML, key auth
            (
                test_device_id,
                DeviceAuthType.shared_private_key.value,
                device_config_with_parent_no_agent,
                "default-edge-agent",
                "./device_configs/device_config.toml",
                "test-device-pk",
                None,
            ),
            # load default TOML, cert auth
            (
                test_device_id,
                DeviceAuthType.x509_thumbprint.value,
                device_config_container_auth_with_agent_no_parent,
                "default-edge-agent",
                None,
                None,
                "output_device_configs",
            ),
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
        device_toml = create_edge_device_config(
            device_id=device_id,
            hub_hostname=hub_entity,
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
        if auth_method == DeviceAuthType.x509_thumbprint.value:
            assert auth == {
                "method": "x509",
                "identity_cert": f"file:///etc/aziot/certificates/{device_id}.hub-auth-cert.pem",
                "identity_pk": f"file:///etc/aziot/certificates/{device_id}.hub-auth-key.pem",
            }
        else:
            assert auth == {"device_id_pk": {"value": device_pk}, "method": "sas"}

        assert device_toml["agent"]["config"]["image"] == (
            device_config.edge_agent if device_config.edge_agent else default_edge_agent
        )

        if not device_config.container_auth:
            assert device_toml["agent"]["config"]["auth"] == {}
        else:
            assert (
                device_toml["agent"]["config"]["auth"]["serveraddress"]
                == device_config.container_auth.serveraddress
            )
            assert (
                device_toml["agent"]["config"]["auth"]["username"]
                == device_config.container_auth.username
            )
            assert (
                device_toml["agent"]["config"]["auth"]["password"]
                == device_config.container_auth.password
            )

        if output_path:
            import tomli_w
            from os.path import join

            path = join(output_path, "config.toml")
            with open(path, "rt", encoding="utf-8") as f:
                assert tomli_w.dumps(device_toml) == f.read()
            rmtree(output_path)

    @pytest.mark.parametrize(
        "deployment, error",
        [
            (
                "device_configs/invalid/invalid_deployment.json",
                InvalidArgumentValueError,
            ),
            ("path_does_not_exist.json", FileOperationError),
            ("device_configs/deploymentLowerLayer.json", None),
        ],
    )
    def test_process_edge_config_content(self, set_cwd, deployment, error):
        try:
            config_content = try_parse_valid_deployment_config(deployment)
            assert isinstance(config_content, ConfigurationContent)
        except error as ex:
            assert isinstance(ex, error)

    @pytest.mark.parametrize(
        "content, expected",
        [
            (
                {
                    "configVersion": "1.0",
                    "iotHub": {"authenticationMethod": "symmetricKey"},
                    "edgeConfiguration": {
                        "templateConfigPath": "template-config-path.toml",
                        "defaultEdgeAgent": "edge-agent-1",
                    },
                    "edgeDevices": [
                        {
                            "deviceId": "parent-device-id",
                            "edgeAgent": "test-agent",
                            "hostname": "parent-hostname",
                        },
                    ],
                },
                EdgeDevicesConfig(
                    version="1.0",
                    auth_method=DeviceAuthType.shared_private_key.value,
                    root_cert={
                        "certificate": "root_certificate",
                        "thumbprint": "root_thumbprint",
                        "privateKey": "root_private_key",
                    },
                    devices=[
                        EdgeDeviceConfig(
                            device_id="parent-device-id",
                            edge_agent="test-agent",
                            hostname="parent-hostname",
                        ),
                    ],
                    template_config_path="template-config-path.toml",
                    default_edge_agent="edge-agent-1",
                ),
            ),
            (
                {
                    "configVersion": "1.0",
                    "iotHub": {"authenticationMethod": "x509Certificate"},
                    "edgeConfiguration": {"defaultEdgeAgent": "edge-agent-1"},
                    "edgeDevices": [
                        {
                            "deviceId": "parent-device-id",
                            "edgeAgent": "test-agent",
                            "hostname": "parent-hostname",
                            "children": [
                                {
                                    "deviceId": "child-device-id",
                                    "edgeAgent": "test-agent2",
                                    "hostname": "child-hostname",
                                }
                            ],
                        }
                    ],
                },
                EdgeDevicesConfig(
                    version="1.0",
                    auth_method=DeviceAuthType.x509_thumbprint.value,
                    root_cert={
                        "certificate": "root_certificate",
                        "thumbprint": "root_thumbprint",
                        "privateKey": "root_private_key",
                    },
                    devices=[
                        EdgeDeviceConfig(
                            device_id="parent-device-id",
                            edge_agent="test-agent",
                            hostname="parent-hostname",
                        ),
                        EdgeDeviceConfig(
                            device_id="child-device-id",
                            edge_agent="test-agent2",
                            hostname="child-hostname",
                            parent_id="parent-device-id",
                            parent_hostname="parent-hostname",
                        ),
                    ],
                    default_edge_agent="edge-agent-1",
                ),
            ),
        ],
    )
    def test_process_edge_devices_config_content(
        self, set_cwd, patch_create_edge_root_cert, content, expected
    ):
        result = process_edge_devices_config_file_content(content)
        assert result == expected

    def test_process_edge_devices_config_load_cert(
        self,
        set_cwd,
    ):
        content = {
            "configVersion": "1.0",
            "iotHub": {"authenticationMethod": "x509Certificate"},
            "edgeConfiguration": {"defaultEdgeAgent": "edge-agent-2"},
            "certificates": {
                "rootCACertPath": f"{test_certs_folder}/{test_root_cert}",
                "rootCACertKeyPath": f"{test_certs_folder}/{test_root_key}",
            },
            "edgeDevices": [{"deviceId": "test"}],
        }
        cert = self.create_test_root_cert(test_certs_folder)
        result = process_edge_devices_config_file_content(content)
        rmtree(test_certs_folder)
        assert result == EdgeDevicesConfig(
            version="1.0",
            auth_method=DeviceAuthType.x509_thumbprint.value,
            default_edge_agent="edge-agent-2",
            root_cert=cert,
            devices=[EdgeDeviceConfig(device_id="test")],
        )

    @pytest.mark.parametrize(
        "content, error",
        [
            # no version
            (
                {
                    "iotHub": {"authentication_method": "symmetricKey"},
                    "edgeConfiguration": {
                        "templateConfigPath": "template-config-path.toml",
                        "defaultEdgeAgent": "edge-agent-1",
                    },
                },
                InvalidArgumentValueError,
            ),
            # No iothub config
            (
                {
                    "configVersion": "1.0",
                    "edgeConfiguration": {
                        "templateConfigPath": "template-config-path.toml",
                        "defaultEdgeAgent": "edge-agent-1",
                    },
                },
                InvalidArgumentValueError,
            ),
            # missing root CA key
            (
                {
                    "configVersion": "1.0",
                    "iotHub": {"authentication_method": "symmetricKey"},
                    "edgeConfiguration": {
                        "templateConfigPath": "template-config-path.toml",
                        "defaultEdgeAgent": "edge-agent-1",
                    },
                    "certificates": {
                        "rootCACertPath": "certs/root-cert.pem",
                    },
                    "edgeDevices": [],
                },
                InvalidArgumentValueError,
            ),
            # invalid auth value
            (
                {
                    "configVersion": "1.0",
                    "iotHub": {"authenticationMethod": "super-duper-auth"},
                    "edgeConfiguration": {
                        "templateConfigPath": "template-config-path.toml",
                        "defaultEdgeAgent": "edge-agent-1",
                    },
                    "edgeDevices": [],
                },
                InvalidArgumentValueError,
            ),
        ],
    )
    def test_process_edge_devices_config_errors(self, content, error):
        with pytest.raises(error):
            process_edge_devices_config_file_content(content)

    @pytest.mark.parametrize(
        "devices, auth, edge_agent, config_template, expected",
        [
            # No extra params
            (
                [["id=dev1", "parent=dev2"], ["id=dev2"]],
                DeviceAuthType.x509_thumbprint.value,
                None,
                None,
                EdgeDevicesConfig(
                    version="1.0",
                    auth_method=DeviceAuthType.x509_thumbprint.value,
                    root_cert={
                        "certificate": "root_certificate",
                        "thumbprint": "root_thumbprint",
                        "privateKey": "root_private_key",
                    },
                    devices=[
                        EdgeDeviceConfig(device_id="dev1", parent_id="dev2"),
                        EdgeDeviceConfig(device_id="dev2"),
                    ],
                ),
            ),
            # various edge-agent configs
            (
                [
                    ["id=dev1", "edge_agent=new-edge-agent"],
                    ["id=dev2"],
                ],
                DeviceAuthType.x509_thumbprint.value,
                "default-edge-agent",
                None,
                EdgeDevicesConfig(
                    version="1.0",
                    auth_method=DeviceAuthType.x509_thumbprint.value,
                    default_edge_agent="default-edge-agent",
                    root_cert={
                        "certificate": "root_certificate",
                        "thumbprint": "root_thumbprint",
                        "privateKey": "root_private_key",
                    },
                    devices=[
                        EdgeDeviceConfig(device_id="dev1", edge_agent="new-edge-agent"),
                        EdgeDeviceConfig(
                            device_id="dev2",
                        ),
                    ],
                ),
            ),
            # load device config toml
            (
                [
                    ["id=dev1", "edge_agent=new-edge-agent", "hostname=dev1"],
                    ["id=dev2", "hostname=dev2"],
                ],
                DeviceAuthType.x509_thumbprint.value,
                None,
                "device_configs/device_config.toml",
                EdgeDevicesConfig(
                    version="1.0",
                    auth_method=DeviceAuthType.x509_thumbprint.value,
                    root_cert={
                        "certificate": "root_certificate",
                        "thumbprint": "root_thumbprint",
                        "privateKey": "root_private_key",
                    },
                    template_config_path="device_configs/device_config.toml",
                    devices=[
                        EdgeDeviceConfig(
                            device_id="dev1",
                            edge_agent="new-edge-agent",
                            hostname="dev1",
                        ),
                        EdgeDeviceConfig(device_id="dev2", hostname="dev2"),
                    ],
                ),
            ),
        ],
    )
    def test_process_edge_devices_config_args(
        self,
        set_cwd,
        patch_create_edge_root_cert,
        devices,
        auth,
        edge_agent,
        config_template,
        expected,
    ):
        result = process_edge_devices_config_args(
            device_args=devices,
            auth_type=auth,
            default_edge_agent=edge_agent,
            device_config_template=config_template,
        )
        assert result == expected

    @pytest.mark.parametrize(
        "device_id, hub_auth, hostname, has_parent, parent_hostname, segments",
        [
            # device, hub_auth, hostname, parent, parent_hostname
            (
                "test_device_id",
                True,
                "hostname",
                True,
                "parent_hostname",
                [
                    EDGE_CONFIG_SCRIPT_HEADERS.format("test_device_id"),
                    EDGE_CONFIG_SCRIPT_CA_CERTS,
                    EDGE_CONFIG_SCRIPT_HUB_AUTH_CERTS,
                    EDGE_CONFIG_SCRIPT_APPLY,
                ],
            ),
            # device, no hub auth, hostname, parent, parent_hostname
            (
                "test_device_id",
                False,
                "hostname",
                True,
                "parent_hostname",
                [
                    EDGE_CONFIG_SCRIPT_HEADERS.format("test_device_id"),
                    EDGE_CONFIG_SCRIPT_CA_CERTS,
                    EDGE_CONFIG_SCRIPT_APPLY,
                ],
            ),
            # no optional parameters
            (
                "test_device_id",
                None,
                None,
                None,
                None,
                [
                    EDGE_CONFIG_SCRIPT_HEADERS.format("test_device_id"),
                    EDGE_CONFIG_SCRIPT_HOSTNAME,
                    EDGE_CONFIG_SCRIPT_CA_CERTS,
                    EDGE_CONFIG_SCRIPT_APPLY,
                ],
            ),
            # parent but no hostnames, no hub auth
            (
                "test_device_id",
                False,
                None,
                True,
                None,
                [
                    EDGE_CONFIG_SCRIPT_HEADERS.format("test_device_id"),
                    EDGE_CONFIG_SCRIPT_HOSTNAME,
                    EDGE_CONFIG_SCRIPT_PARENT_HOSTNAME,
                    EDGE_CONFIG_SCRIPT_CA_CERTS,
                    EDGE_CONFIG_SCRIPT_APPLY,
                ],
            ),
        ],
    )
    def test_create_edge_device_config_script(
        self, device_id, hub_auth, hostname, has_parent, parent_hostname, segments
    ):
        script_content = create_edge_device_config_script(
            device_id=device_id,
            hub_auth=hub_auth,
            hostname=hostname,
            has_parent=has_parent,
            parent_hostname=parent_hostname,
        )

        assert script_content == "\n".join(segments)
