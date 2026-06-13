# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.sas_token_auth import SasTokenAuthentication
import pytest
from knack.cli import CLIError
from azure.cli.core.azclierror import ArgumentUsageError, CLIInternalError
from azext_iot.operations import hub as subject
from azext_iot.tests.generators import generate_generic_id


def generate_valid_cs(validate_pairs=[]):
    host_name = generate_generic_id()
    shared_access_key = generate_generic_id()
    cs = f"HostName={host_name};"
    input_pairs = dict((k, generate_generic_id()) for k in validate_pairs)
    policy = input_pairs["SharedAccessKeyName"] if "SharedAccessKeyName" in input_pairs else None

    for key, value in input_pairs.items():
        cs += "{}={};".format(
            key, value
        )

    cs = f"{cs}SharedAccessKey={shared_access_key}"
    uri = host_name
    if "DeviceId" in input_pairs:
        uri = f"{uri}/devices/{input_pairs['DeviceId']}"
    if "ModuleId" in input_pairs:
        uri = f"{uri}/modules/{input_pairs['ModuleId']}"

    return {
        "connection_string": cs,
        "uri": uri,
        "policy": policy,
        "key": shared_access_key
    }


class TestGenerateSasToken:
    @pytest.mark.parametrize(
        "duration, req",
        [
            (3600, generate_valid_cs(["DeviceId"])),
            (30, generate_valid_cs(["DeviceId"])),
            (60000, generate_valid_cs(["DeviceId"])),
            (3600, generate_valid_cs(["SharedAccessKeyName"])),
            (3600, generate_valid_cs(["DeviceId"])),
            (3600, generate_valid_cs(["DeviceId", "ModuleId"])),
            (3600, generate_valid_cs(["Test", "DeviceId", "ModuleId"])),
            (3600, generate_valid_cs(["RepositoryId", "DeviceId", "ModuleId"])),
        ],
    )
    def test_generate_sas_token_from_cs(self, mocker, fixture_cmd, duration, req):
        patched_time = mocker.patch(
            "azext_iot.common.sas_token_auth.time"
        )
        patched_time.return_value = 0
        result = subject.iot_get_sas_token(
            cmd=fixture_cmd,
            connection_string=req["connection_string"],
            duration=duration
        )

        duration = duration if duration else 3600
        expected_sas = SasTokenAuthentication(
            req["uri"], req["policy"], req["key"], duration
        ).generate_sas_token()
        assert result["sas"] == expected_sas

    @pytest.mark.parametrize(
        "req",
        [
            (generate_valid_cs()),
            (generate_valid_cs(["ModuleId"])),
            (generate_valid_cs(["Test"]))
        ],
    )
    def test_generate_sas_token_from_cs_error(self, mocker, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_get_sas_token(
                cmd=fixture_cmd,
                connection_string=req["connection_string"],
            )


class TestHostnameTypeRouting:
    """SAS audience routing + CS-show service-hostname rejection."""

    HUB = "mygwv2hub"
    _PRIMARY = generate_generic_id()
    _SECONDARY = generate_generic_id()
    _DEVICE_PRIMARY = generate_generic_id()
    _DEVICE_SECONDARY = generate_generic_id()
    TARGET = {
        "entity": f"{HUB}.service.azure-devices.net",
        "policy": "iothubowner",
        "primarykey": _PRIMARY,
        "secondarykey": _SECONDARY,
        "name": HUB, "subscription": "sub", "resourcegroup": "rg",
        "deviceHostName": f"{HUB}.device.azure-devices.net",
        "serviceHostName": f"{HUB}.service.azure-devices.net",
        "cmd": None,
    }
    DEVICE = {
        "deviceId": "d1",
        "authentication": {"type": "sas", "symmetricKey": {
            "primaryKey": _DEVICE_PRIMARY, "secondaryKey": _DEVICE_SECONDARY}},
    }
    MODULE = {**DEVICE, "moduleId": "m1"}

    @pytest.fixture(autouse=True)
    def _patches(self, mocker):
        mocker.patch("azext_iot.operations.hub.IotHubDiscovery.get_target",
                     return_value=dict(self.TARGET))
        mocker.patch("azext_iot.operations.hub._iot_device_show", return_value=self.DEVICE)
        mocker.patch("azext_iot.operations.hub._iot_device_module_show", return_value=self.MODULE)

    @staticmethod
    def _sr(token):
        from urllib.parse import unquote
        for part in token["sas"].replace("SharedAccessSignature ", "").split("&"):
            if part.startswith("sr="):
                return unquote(part[3:])
        raise AssertionError(token["sas"])

    @pytest.mark.parametrize("scope, hostname_type, expected", [
        # defaults (auto) on GWv2: hub->service, device/module->device
        ({}, "auto", "mygwv2hub.service.azure-devices.net"),
        ({"device_id": "d1"}, "auto", "mygwv2hub.device.azure-devices.net/devices/d1"),
        ({"device_id": "d1", "module_id": "m1"}, "auto",
         "mygwv2hub.device.azure-devices.net/devices/d1/modules/m1"),

        ({"device_id": "d1"}, "service", "mygwv2hub.service.azure-devices.net/devices/d1"),
        ({"device_id": "d1", "module_id": "m1"}, "service",
         "mygwv2hub.service.azure-devices.net/devices/d1/modules/m1"),
    ])
    def test_sas_audience(self, fixture_cmd, scope, hostname_type, expected):
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname=self.HUB,
            hostname_type=hostname_type, **scope)
        assert self._sr(token) == expected

    @pytest.mark.parametrize("op, kwargs", [
        (subject.iot_get_device_connection_string,
         {"hub_name_or_hostname": "hub", "device_id": "d1"}),
        (subject.iot_get_module_connection_string,
         {"hub_name_or_hostname": "hub", "device_id": "d1", "module_id": "m1"}),
    ])
    def test_cs_show_rejects_service_hostname(self, fixture_cmd, op, kwargs):
        with pytest.raises(CLIError, match="not supported"):
            op(cmd=fixture_cmd, hostname_type="service", **kwargs)

    @pytest.mark.parametrize("hostname_type, expected_host", [
        ("auto", "mygwv2hub.device.azure-devices.net"),
        ("device", "mygwv2hub.device.azure-devices.net"),
        ("classic", "mygwv2hub.azure-devices.net"),
    ])
    def test_device_connection_string_show(
        self, fixture_cmd, hostname_type, expected_host
    ):
        result = subject.iot_get_device_connection_string(
            cmd=fixture_cmd, hub_name_or_hostname=self.HUB, device_id="d1",
            hostname_type=hostname_type)
        assert result["connectionString"] == (
            f"HostName={expected_host};DeviceId=d1;"
            f"SharedAccessKey={self._DEVICE_PRIMARY}")

    @pytest.mark.parametrize("hostname_type, expected_host", [
        ("auto", "mygwv2hub.device.azure-devices.net"),
        ("device", "mygwv2hub.device.azure-devices.net"),
        ("classic", "mygwv2hub.azure-devices.net"),
    ])
    def test_module_connection_string_show(
        self, fixture_cmd, hostname_type, expected_host
    ):
        result = subject.iot_get_module_connection_string(
            cmd=fixture_cmd, hub_name_or_hostname=self.HUB, device_id="d1",
            module_id="m1", hostname_type=hostname_type)
        assert result["connectionString"] == (
            f"HostName={expected_host};DeviceId=d1;ModuleId=m1;"
            f"SharedAccessKey={self._DEVICE_PRIMARY}")

    def test_device_connection_string_show_secondary_key(self, fixture_cmd):
        result = subject.iot_get_device_connection_string(
            cmd=fixture_cmd, hub_name_or_hostname=self.HUB, device_id="d1",
            key_type="secondary", hostname_type="classic")
        assert result["connectionString"] == (
            f"HostName=mygwv2hub.azure-devices.net;DeviceId=d1;"
            f"SharedAccessKey={self._DEVICE_SECONDARY}")

    def test_device_connection_string_show_login_mode(self, fixture_cmd):
        # login mode -> hostname is string-transformed from target entity.
        result = subject.iot_get_device_connection_string(
            cmd=fixture_cmd, login="cs", device_id="d1", hostname_type="device")
        assert result["connectionString"] == (
            f"HostName=mygwv2hub.device.azure-devices.net;DeviceId=d1;"
            f"SharedAccessKey={self._DEVICE_PRIMARY}")

    def test_module_connection_string_show_login_mode(self, fixture_cmd):
        result = subject.iot_get_module_connection_string(
            cmd=fixture_cmd, login="cs", device_id="d1", module_id="m1",
            hostname_type="device")
        assert result["connectionString"] == (
            f"HostName=mygwv2hub.device.azure-devices.net;DeviceId=d1;ModuleId=m1;"
            f"SharedAccessKey={self._DEVICE_PRIMARY}")

    @pytest.mark.parametrize("hostname_type", ["device", "service", "classic"])
    def test_sas_connection_string_rejects_explicit_hostname_type(
        self, fixture_cmd, hostname_type
    ):
        cs = generate_valid_cs(["DeviceId"])["connection_string"]
        with pytest.raises(CLIError, match="--connection-string"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd,
                connection_string=cs,
                hostname_type=hostname_type,
            )

    @pytest.mark.parametrize("scope, hostname_type, login_host, expected", [
        # login (offline) mode: audience comes from string-transformed CS HostName.
        # auto defaults to scope-appropriate hostname.
        ({}, "auto", "mygwv2hub.service.azure-devices.net",
         "mygwv2hub.service.azure-devices.net"),
        ({}, "auto", "mygwv2hub.azure-devices.net",
         "mygwv2hub.service.azure-devices.net"),
        ({"device_id": "d1"}, "auto", "mygwv2hub.service.azure-devices.net",
         "mygwv2hub.device.azure-devices.net/devices/d1"),
        ({"device_id": "d1"}, "auto", "mygwv2hub.azure-devices.net",
         "mygwv2hub.device.azure-devices.net/devices/d1"),
        ({"device_id": "d1", "module_id": "m1"}, "auto",
         "mygwv2hub.service.azure-devices.net",
         "mygwv2hub.device.azure-devices.net/devices/d1/modules/m1"),

        ({"device_id": "d1"}, "device", "mygwv2hub.azure-devices.net",
         "mygwv2hub.device.azure-devices.net/devices/d1"),
        ({"device_id": "d1"}, "classic", "mygwv2hub.service.azure-devices.net",
         "mygwv2hub.azure-devices.net/devices/d1"),
        ({"device_id": "d1", "module_id": "m1"}, "service",
         "mygwv2hub.device.azure-devices.net",
         "mygwv2hub.service.azure-devices.net/devices/d1/modules/m1"),
    ])
    def test_sas_audience_login_mode(
        self, mocker, fixture_cmd, scope, hostname_type, login_host, expected
    ):
        key = generate_generic_id()
        target = dict(self.TARGET, entity=login_host,
                      cs=(f"HostName={login_host};SharedAccessKeyName=iothubowner;"
                          f"SharedAccessKey={key}"))
        mocker.patch("azext_iot.operations.hub.IotHubDiscovery.get_target",
                     return_value=target)
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd,
            login=target["cs"],
            hostname_type=hostname_type,
            **scope,
        )
        assert self._sr(token) == expected


class TestValidateSasTokenArgs:
    """Direct unit coverage of _validate_iot_get_sas_token_args branches."""

    def test_login_with_non_default_policy_rejected(self):
        with pytest.raises(ArgumentUsageError, match="sas policy"):
            subject._validate_iot_get_sas_token_args(
                login="cs", policy_name="custom", key_type="primary",
                device_id=None, module_id=None, connection_string=None,
                hostname_type="auto")

    def test_login_with_non_primary_key_non_device_rejected(self):
        with pytest.raises(ArgumentUsageError, match="key type"):
            subject._validate_iot_get_sas_token_args(
                login="cs", policy_name="iothubowner", key_type="secondary",
                device_id=None, module_id=None, connection_string=None,
                hostname_type="auto")

    def test_module_without_device_rejected(self):
        with pytest.raises(ArgumentUsageError, match="without device"):
            subject._validate_iot_get_sas_token_args(
                login=None, policy_name="iothubowner", key_type="primary",
                device_id=None, module_id="m1", connection_string=None,
                hostname_type="auto")

    def test_connection_string_with_non_auto_hostname_rejected(self):
        with pytest.raises(ArgumentUsageError, match="--hostname-type"):
            subject._validate_iot_get_sas_token_args(
                login=None, policy_name="iothubowner", key_type="primary",
                device_id=None, module_id=None, connection_string="cs",
                hostname_type="device")

    def test_valid_args_pass(self):
        # No exception expected.
        subject._validate_iot_get_sas_token_args(
            login=None, policy_name="iothubowner", key_type="primary",
            device_id="d1", module_id="m1", connection_string=None,
            hostname_type="auto")


class TestSasTokenUnsupportedAuth:
    """x509 entities cannot form SAS tokens -> CLIInternalError."""

    HUB = "mygwv2hub"
    TARGET = {
        "entity": f"{HUB}.service.azure-devices.net",
        "policy": "iothubowner",
        "primarykey": generate_generic_id(),
        "secondarykey": generate_generic_id(),
        "name": HUB, "subscription": "sub", "resourcegroup": "rg",
        "deviceHostName": f"{HUB}.device.azure-devices.net",
        "serviceHostName": f"{HUB}.service.azure-devices.net",
        "cmd": None,
    }
    X509_DEVICE = {
        "deviceId": "d1",
        "authentication": {"type": "selfSigned"},
    }
    X509_MODULE = {**X509_DEVICE, "moduleId": "m1"}

    @pytest.fixture(autouse=True)
    def _patches(self, mocker):
        mocker.patch("azext_iot.operations.hub.IotHubDiscovery.get_target",
                     return_value=dict(self.TARGET))
        mocker.patch("azext_iot.operations.hub._iot_device_show",
                     return_value=self.X509_DEVICE)
        mocker.patch("azext_iot.operations.hub._iot_device_module_show",
                     return_value=self.X509_MODULE)

    def test_device_x509_sas_token_rejected(self, fixture_cmd):
        with pytest.raises(CLIInternalError, match="device does not support SAS"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname=self.HUB, device_id="d1")

    def test_module_x509_sas_token_rejected(self, fixture_cmd):
        with pytest.raises(CLIInternalError, match="module does not support SAS"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname=self.HUB,
                device_id="d1", module_id="m1")


class TestTwinUpdateCustom:
    """Pure patch-payload builder for iot twin update --desired/--tags."""

    def test_no_args_returns_instance_unchanged(self):
        instance = {"deviceId": "d1"}
        assert subject.iot_twin_update_custom(instance) is instance

    def test_desired_only_builds_patch(self):
        result = subject.iot_twin_update_custom(
            {"deviceId": "d1"}, desired='{"k": "v"}')
        assert result == {"properties": {"desired": {"k": "v"}}}

    def test_tags_only_builds_patch(self):
        result = subject.iot_twin_update_custom(
            {"deviceId": "d1"}, tags='{"t": "1"}')
        assert result == {"tags": {"t": "1"}}

    def test_desired_and_tags_builds_combined_patch(self):
        result = subject.iot_twin_update_custom(
            {"deviceId": "d1"}, desired='{"k": "v"}', tags='{"t": "1"}')
        assert result == {
            "properties": {"desired": {"k": "v"}},
            "tags": {"t": "1"},
        }
