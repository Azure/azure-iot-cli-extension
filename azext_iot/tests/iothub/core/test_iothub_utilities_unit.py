# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.sas_token_auth import SasTokenAuthentication
import pytest
from knack.cli import CLIError
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


class TestGenerateSasTokenHostnameType:
    """Bug-bash #9 — generate-sas-token --hostname-type plumbing.

    Default behavior shifts on GWv2 hubs:
    - Hub-level SAS (no -d): `sr=` uses the service hostname (GWv2) or classic hostname (classic hub).
    - Device-level SAS (-d): `sr=` uses the device hostname (GWv2) or classic hostname (classic hub).
    - Module-level SAS (-d -m): same as device-level.
    Explicit `--hostname-type service` is rejected for device/module scopes.
    Explicit `--hostname-type device`/`service` raises on classic hubs.
    """

    GWV2_TARGET = {
        "entity": "mygwv2hub.service.azure-devices.net",
        "policy": "iothubowner",
        "primarykey": "cHJpbWFyeUtleQ==",
        "secondarykey": "c2Vjb25kYXJ5S2V5",
        "name": "mygwv2hub",
        "subscription": "sub",
        "resourcegroup": "rg",
        "deviceHostName": "mygwv2hub.device.azure-devices.net",
        "serviceHostName": "mygwv2hub.service.azure-devices.net",
        "location": "eastus2euap",
        "cmd": None,
    }
    CLASSIC_TARGET = {
        "entity": "myclassichub.azure-devices.net",
        "policy": "iothubowner",
        "primarykey": "cHJpbWFyeUtleQ==",
        "secondarykey": "c2Vjb25kYXJ5S2V5",
        "name": "myclassichub",
        "subscription": "sub",
        "resourcegroup": "rg",
        "location": "eastus",
        "cmd": None,
    }
    DEVICE_ID = "device1"
    MODULE_ID = "module1"
    DEVICE_KEY = "ZGV2aWNlS2V5MQ=="
    MODULE_KEY = "bW9kdWxlS2V5MQ=="

    @pytest.fixture
    def patch_discovery(self, mocker):
        """Returns a helper that patches IotHubDiscovery.get_target to return the given target."""
        def _patch(target):
            mocker.patch(
                "azext_iot.operations.hub.IotHubDiscovery.get_target",
                return_value=dict(target),
            )
        return _patch

    @pytest.fixture
    def patch_device_show(self, mocker):
        def _patch():
            mocker.patch(
                "azext_iot.operations.hub._iot_device_show",
                return_value={
                    "deviceId": TestGenerateSasTokenHostnameType.DEVICE_ID,
                    "authentication": {
                        "type": "sas",
                        "symmetricKey": {
                            "primaryKey": TestGenerateSasTokenHostnameType.DEVICE_KEY,
                            "secondaryKey": "device-secondary",
                        },
                    },
                },
            )
        return _patch

    @pytest.fixture
    def patch_module_show(self, mocker):
        def _patch():
            mocker.patch(
                "azext_iot.operations.hub._iot_device_show",
                return_value={
                    "deviceId": TestGenerateSasTokenHostnameType.DEVICE_ID,
                    "authentication": {
                        "type": "sas",
                        "symmetricKey": {
                            "primaryKey": TestGenerateSasTokenHostnameType.DEVICE_KEY,
                            "secondaryKey": "device-secondary",
                        },
                    },
                },
            )
            mocker.patch(
                "azext_iot.operations.hub._iot_device_module_show",
                return_value={
                    "deviceId": TestGenerateSasTokenHostnameType.DEVICE_ID,
                    "moduleId": TestGenerateSasTokenHostnameType.MODULE_ID,
                    "authentication": {
                        "type": "sas",
                        "symmetricKey": {
                            "primaryKey": TestGenerateSasTokenHostnameType.MODULE_KEY,
                            "secondaryKey": "module-secondary",
                        },
                    },
                },
            )
        return _patch

    @staticmethod
    def _extract_sr(sas_token):
        """Extract the URL-decoded `sr=` audience from a SAS token string."""
        from urllib.parse import unquote
        sas = sas_token["sas"]
        # sas tokens look like: "SharedAccessSignature sr=<encoded>&sig=...&se=...&skn=..."
        parts = sas.replace("SharedAccessSignature ", "").split("&")
        for part in parts:
            if part.startswith("sr="):
                return unquote(part[3:])
        raise AssertionError(f"sas token had no sr= component: {sas}")

    # ===== Hub-level SAS (no device) =====

    def test_hub_sas_auto_on_gwv2_uses_service_endpoint(self, fixture_cmd, patch_discovery):
        """Default (auto) on a GWv2 hub for hub-level SAS resolves to the service endpoint."""
        patch_discovery(self.GWV2_TARGET)
        token = subject.iot_get_sas_token(cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub")
        assert self._extract_sr(token) == "mygwv2hub.service.azure-devices.net"

    def test_hub_sas_explicit_service(self, fixture_cmd, patch_discovery):
        patch_discovery(self.GWV2_TARGET)
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub", hostname_type="service"
        )
        assert self._extract_sr(token) == "mygwv2hub.service.azure-devices.net"

    def test_hub_sas_explicit_device(self, fixture_cmd, patch_discovery):
        patch_discovery(self.GWV2_TARGET)
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub", hostname_type="device"
        )
        assert self._extract_sr(token) == "mygwv2hub.device.azure-devices.net"

    def test_hub_sas_explicit_classic(self, fixture_cmd, patch_discovery):
        patch_discovery(self.GWV2_TARGET)
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub", hostname_type="classic"
        )
        assert self._extract_sr(token) == "mygwv2hub.azure-devices.net"

    def test_hub_sas_auto_on_classic_hub(self, fixture_cmd, patch_discovery):
        patch_discovery(self.CLASSIC_TARGET)
        token = subject.iot_get_sas_token(cmd=fixture_cmd, hub_name_or_hostname="myclassichub")
        assert self._extract_sr(token) == "myclassichub.azure-devices.net"

    def test_hub_sas_explicit_service_on_classic_hub_errors(self, fixture_cmd, patch_discovery):
        patch_discovery(self.CLASSIC_TARGET)
        with pytest.raises(CLIError, match="not available"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname="myclassichub", hostname_type="service"
            )

    def test_hub_sas_explicit_device_on_classic_hub_errors(self, fixture_cmd, patch_discovery):
        patch_discovery(self.CLASSIC_TARGET)
        with pytest.raises(CLIError, match="not available"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname="myclassichub", hostname_type="device"
            )

    # ===== Device-level SAS =====

    def test_device_sas_auto_on_gwv2_uses_device_endpoint(
        self, fixture_cmd, patch_discovery, patch_device_show
    ):
        """Default (auto) on a GWv2 hub for device-level SAS resolves to the device endpoint."""
        patch_discovery(self.GWV2_TARGET)
        patch_device_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub", device_id=self.DEVICE_ID
        )
        assert self._extract_sr(token) == f"mygwv2hub.device.azure-devices.net/devices/{self.DEVICE_ID}"

    def test_device_sas_explicit_device(self, fixture_cmd, patch_discovery, patch_device_show):
        patch_discovery(self.GWV2_TARGET)
        patch_device_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
            device_id=self.DEVICE_ID, hostname_type="device",
        )
        assert self._extract_sr(token) == f"mygwv2hub.device.azure-devices.net/devices/{self.DEVICE_ID}"

    def test_device_sas_explicit_classic(self, fixture_cmd, patch_discovery, patch_device_show):
        patch_discovery(self.GWV2_TARGET)
        patch_device_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
            device_id=self.DEVICE_ID, hostname_type="classic",
        )
        assert self._extract_sr(token) == f"mygwv2hub.azure-devices.net/devices/{self.DEVICE_ID}"

    def test_device_sas_explicit_service_rejected(self, fixture_cmd, patch_discovery):
        """Device-scope SAS with --hostname-type service must be rejected up-front."""
        with pytest.raises(CLIError, match="not supported for device or module"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
                device_id=self.DEVICE_ID, hostname_type="service",
            )

    def test_device_sas_auto_on_classic_hub(
        self, fixture_cmd, patch_discovery, patch_device_show
    ):
        patch_discovery(self.CLASSIC_TARGET)
        patch_device_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="myclassichub", device_id=self.DEVICE_ID
        )
        assert self._extract_sr(token) == f"myclassichub.azure-devices.net/devices/{self.DEVICE_ID}"

    # ===== Module-level SAS =====

    def test_module_sas_auto_on_gwv2_uses_device_endpoint(
        self, fixture_cmd, patch_discovery, patch_module_show
    ):
        patch_discovery(self.GWV2_TARGET)
        patch_module_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
            device_id=self.DEVICE_ID, module_id=self.MODULE_ID,
        )
        expected = f"mygwv2hub.device.azure-devices.net/devices/{self.DEVICE_ID}/modules/{self.MODULE_ID}"
        assert self._extract_sr(token) == expected

    def test_module_sas_explicit_service_rejected(self, fixture_cmd):
        with pytest.raises(CLIError, match="not supported for device or module"):
            subject.iot_get_sas_token(
                cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
                device_id=self.DEVICE_ID, module_id=self.MODULE_ID,
                hostname_type="service",
            )

    def test_module_sas_explicit_classic(
        self, fixture_cmd, patch_discovery, patch_module_show
    ):
        patch_discovery(self.GWV2_TARGET)
        patch_module_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, hub_name_or_hostname="mygwv2hub",
            device_id=self.DEVICE_ID, module_id=self.MODULE_ID,
            hostname_type="classic",
        )
        expected = f"mygwv2hub.azure-devices.net/devices/{self.DEVICE_ID}/modules/{self.MODULE_ID}"
        assert self._extract_sr(token) == expected

    # ===== --login mode (CS-based; _transform_hostname path) =====

    def test_hub_sas_login_mode_classic_string_transformed_to_service(
        self, fixture_cmd, patch_discovery
    ):
        """In --login mode, the target's entity comes from the CS; --hostname-type rewrites it."""
        login_target = {
            "entity": "loginhub.azure-devices.net",
            "policy": "iothubowner",
            "primarykey": "cHJpbWFyeUtleQ==",
            "secondarykey": "c2Vjb25kYXJ5S2V5",
            "name": "loginhub",
            "cmd": None,
        }
        patch_discovery(login_target)
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, login="HostName=loginhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k",
            hostname_type="service",
        )
        assert self._extract_sr(token) == "loginhub.service.azure-devices.net"

    def test_device_sas_login_mode_device_hostname_transform(
        self, fixture_cmd, patch_discovery, patch_device_show
    ):
        login_target = {
            "entity": "loginhub.azure-devices.net",
            "policy": "iothubowner",
            "primarykey": "cHJpbWFyeUtleQ==",
            "secondarykey": "c2Vjb25kYXJ5S2V5",
            "name": "loginhub",
            "cmd": None,
        }
        patch_discovery(login_target)
        patch_device_show()
        token = subject.iot_get_sas_token(
            cmd=fixture_cmd, login="HostName=loginhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k",
            device_id=self.DEVICE_ID, hostname_type="device",
        )
        assert self._extract_sr(token) == f"loginhub.device.azure-devices.net/devices/{self.DEVICE_ID}"


class TestConnectionStringServiceRejection:
    """Bug-bash #8 — device/module connection-string commands reject --hostname-type service."""

    def test_device_cs_service_rejected(self, fixture_cmd):
        with pytest.raises(CLIError, match="not supported for device"):
            subject.iot_get_device_connection_string(
                cmd=fixture_cmd, device_id="d1", hub_name_or_hostname="hub",
                hostname_type="service",
            )

    def test_module_cs_service_rejected(self, fixture_cmd):
        with pytest.raises(CLIError, match="not supported for module"):
            subject.iot_get_module_connection_string(
                cmd=fixture_cmd, device_id="d1", module_id="m1",
                hub_name_or_hostname="hub", hostname_type="service",
            )

    def test_device_cs_with_login_service_rejected(self, fixture_cmd):
        """The guard fires before discovery, regardless of login vs ARM auth."""
        with pytest.raises(CLIError, match="not supported for device"):
            subject.iot_get_device_connection_string(
                cmd=fixture_cmd, device_id="d1",
                login="HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k",
                hostname_type="service",
            )
