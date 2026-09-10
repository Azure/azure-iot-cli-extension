# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging

import pytest
from azure.cli.core.azclierror import (
    AzCLIError,
    BadRequestError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)

from azext_iot.iothub.providers import state as state_module
from azext_iot.iothub.providers.state import StateProvider
from azext_iot.iothub.common import HubAspects
from azext_iot.common.shared import DeviceAuthApiType

logging.disable(logging.CRITICAL)

sp = "azext_iot.iothub.providers.state"

_UNSET = object()


def _provider(mocker, target=_UNSET):
    p = StateProvider.__new__(StateProvider)
    p.cmd = mocker.MagicMock()
    p.target = {
        "name": "hub",
        "entity": "hub.azure-devices.net",
        "resourcegroup": "rg",
    } if target is _UNSET else target
    p.hub_name = "hub"
    p.rg = "rg"
    p.login = None
    p.auth_type = None
    p.discovery = mocker.MagicMock()
    return p


def _device_identity(auth_type=DeviceAuthApiType.sas.value, status_reason=False):
    identity = {
        "authentication": {
            "type": auth_type,
            "x509Thumbprint": {"primaryThumbprint": "p", "secondaryThumbprint": "s"},
            "symmetricKey": {"primaryKey": "pk", "secondaryKey": "sk"},
        },
        "capabilities": {"iotEdge": False},
        "status": "enabled",
    }
    if status_reason:
        identity["status_reason"] = "reason"
        identity["statusReason"] = "reason"
    return identity


class TestUploadDeviceIdentity:
    def test_sas(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_create")
        mocker.patch(f"{sp}._iot_device_show")
        p.upload_device_identity("dev1", _device_identity(status_reason=True))
        create.assert_called_once()

    def test_self_signed(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_create")
        mocker.patch(f"{sp}._iot_device_show")
        p.upload_device_identity("dev1", _device_identity(DeviceAuthApiType.selfSigned.value))
        create.assert_called_once()

    def test_certificate_authority(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_create")
        mocker.patch(f"{sp}._iot_device_show")
        p.upload_device_identity(
            "dev1", _device_identity(DeviceAuthApiType.certificateAuthority.value)
        )
        create.assert_called_once()

    def test_bad_auth(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_create")
        mocker.patch(f"{sp}._iot_device_show")
        p.upload_device_identity("dev1", _device_identity("badauth"))
        create.assert_not_called()


class TestUploadModuleIdentity:
    def test_sas(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_module_create")
        p.upload_module_identity("dev1", "mod1", _device_identity())
        create.assert_called_once()

    def test_self_signed(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_module_create")
        p.upload_module_identity("dev1", "mod1", _device_identity(DeviceAuthApiType.selfSigned.value))
        create.assert_called_once()

    def test_certificate_authority(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_module_create")
        p.upload_module_identity(
            "dev1", "mod1", _device_identity(DeviceAuthApiType.certificateAuthority.value)
        )
        create.assert_called_once()

    def test_bad_auth(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_device_module_create")
        p.upload_module_identity("dev1", "mod1", _device_identity("badauth"))
        create.assert_not_called()


class TestDeleteCommands:
    def test_delete_all_certificates(self, mocker):
        p = _provider(mocker)
        client = mocker.MagicMock()
        client.certificates.list_by_iot_hub.return_value = {
            "value": [{"name": "c1", "etag": "e1"}]
        }
        mocker.patch.object(p, "_get_client", return_value=client)
        p.delete_all_certificates()
        client.certificates.delete.assert_called_once()

    def test_delete_all_configs(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_hub_configuration_list", return_value=[{"id": "c1"}])
        delete = mocker.patch(f"{sp}._iot_hub_configuration_delete")
        p.delete_all_configs()
        delete.assert_called_once()

    def test_delete_all_configs_list_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_hub_configuration_list", side_effect=AzCLIError("boom"))
        delete = mocker.patch(f"{sp}._iot_hub_configuration_delete")
        p.delete_all_configs()
        delete.assert_not_called()

    def test_delete_all_configs_delete_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_hub_configuration_list", return_value=[{"id": "c1"}])
        mocker.patch(f"{sp}._iot_hub_configuration_delete", side_effect=ResourceNotFoundError("x"))
        p.delete_all_configs()

    def test_delete_all_devices(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[{"deviceId": "d1"}])
        delete = mocker.patch(f"{sp}._iot_device_delete")
        p.delete_all_devices()
        delete.assert_called_once()

    def test_delete_all_devices_delete_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[{"deviceId": "d1"}])
        mocker.patch(f"{sp}._iot_device_delete", side_effect=ResourceNotFoundError("x"))
        p.delete_all_devices()


class TestDeleteAspects:
    def test_delete_all_aspects(self, mocker):
        p = _provider(mocker)
        configs = mocker.patch.object(p, "delete_all_configs")
        devices = mocker.patch.object(p, "delete_all_devices")
        certs = mocker.patch.object(p, "delete_all_certificates")
        p.delete_aspects(replace=True, hub_aspects=HubAspects.list())
        configs.assert_called_once()
        devices.assert_called_once()
        certs.assert_called_once()

    def test_delete_no_replace(self, mocker):
        p = _provider(mocker)
        configs = mocker.patch.object(p, "delete_all_configs")
        p.delete_aspects(replace=False, hub_aspects=HubAspects.list())
        configs.assert_not_called()

    def test_delete_no_target(self, mocker):
        p = _provider(mocker, target=None)
        configs = mocker.patch.object(p, "delete_all_configs")
        p.delete_aspects(replace=True, hub_aspects=HubAspects.list())
        configs.assert_not_called()


class TestSaveState:
    def test_save_state_success(self, mocker, tmp_path):
        p = _provider(mocker)
        mocker.patch.object(p, "process_hub_to_dict", return_value={"devices": {}})
        state_file = str(tmp_path / "out.json")
        p.save_state(state_file=state_file)
        import os

        assert os.path.exists(state_file)

    def test_save_state_existing_no_replace(self, mocker, tmp_path):
        p = _provider(mocker)
        from azure.cli.core.azclierror import FileOperationError

        mocker.patch(f"{sp}.prompt_y_n", return_value=False)
        state_file = tmp_path / "out.json"
        state_file.write_text("data")
        with pytest.raises(FileOperationError):
            p.save_state(state_file=str(state_file))

    def test_save_state_arm_with_login(self, mocker, tmp_path):
        p = _provider(mocker)
        p.login = "HostName=x;SharedAccessKeyName=y;SharedAccessKey=z"
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.save_state(state_file=str(tmp_path / "out.json"), replace=True)

    def test_save_state_file_not_found(self, mocker, tmp_path):
        p = _provider(mocker)
        from azure.cli.core.azclierror import FileOperationError

        mocker.patch.object(p, "process_hub_to_dict", return_value={"devices": {}})
        bad_path = str(tmp_path / "missing_dir" / "out.json")
        with pytest.raises(FileOperationError):
            p.save_state(state_file=bad_path)


class TestUploadState:
    def test_upload_arm_with_login(self, mocker, tmp_path):
        p = _provider(mocker)
        p.login = "HostName=x;SharedAccessKeyName=y;SharedAccessKey=z"
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.upload_state(state_file=str(tmp_path / "f.json"))

    def test_upload_missing_rg_and_target(self, mocker, tmp_path):
        p = _provider(mocker, target=None)
        p.rg = None
        with pytest.raises(RequiredArgumentMissingError):
            p.upload_state(
                state_file=str(tmp_path / "f.json"),
                hub_aspects=[HubAspects.Devices.value],
            )

    def test_upload_no_target_no_arm(self, mocker, tmp_path):
        p = _provider(mocker, target=None)
        p.rg = "rg"
        with pytest.raises(ResourceNotFoundError):
            p.upload_state(
                state_file=str(tmp_path / "f.json"),
                hub_aspects=[HubAspects.Devices.value],
            )

    def test_upload_success(self, mocker, tmp_path):
        p = _provider(mocker)
        mocker.patch.object(p, "delete_aspects")
        upload = mocker.patch.object(p, "upload_hub_from_dict")
        state_file = tmp_path / "f.json"
        state_file.write_text('{"devices": {}}')
        p.upload_state(state_file=str(state_file), hub_aspects=[HubAspects.Devices.value])
        upload.assert_called_once()

    def test_upload_file_not_found(self, mocker):
        p = _provider(mocker)
        from azure.cli.core.azclierror import FileOperationError

        mocker.patch.object(p, "delete_aspects")
        with pytest.raises(FileOperationError):
            p.upload_state(
                state_file="/no/such/file.json", hub_aspects=[HubAspects.Devices.value]
            )


class TestMigrateState:
    def test_migrate_arm_with_login(self, mocker):
        p = _provider(mocker)
        p.login = "HostName=x;SharedAccessKeyName=y;SharedAccessKey=z"
        p.discovery.get_target.return_value = {"resourcegroup": "rg2"}
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.migrate_state(orig_hub="orig")

    def test_migrate_no_target_no_arm(self, mocker):
        p = _provider(mocker, target=None)
        p.rg = "rg"
        p.discovery.get_target.return_value = {"resourcegroup": "rg2"}
        with pytest.raises(ResourceNotFoundError):
            p.migrate_state(orig_hub="orig", hub_aspects=[HubAspects.Devices.value])

    def test_migrate_success(self, mocker):
        p = _provider(mocker)
        p.discovery.get_target.return_value = {"resourcegroup": "rg2"}
        mocker.patch.object(p, "process_hub_to_dict", return_value={"devices": {}})
        delete = mocker.patch.object(p, "delete_aspects")
        upload = mocker.patch.object(p, "upload_hub_from_dict")
        p.migrate_state(orig_hub="orig", hub_aspects=[HubAspects.Devices.value])
        delete.assert_called_once()
        upload.assert_called_once()

    def test_migrate_rg_from_orig_target(self, mocker):
        p = _provider(mocker, target=None)
        p.rg = None
        p.discovery.get_target.return_value = {"resourcegroup": "rg2"}
        mocker.patch.object(p, "process_hub_to_dict", return_value={})
        mocker.patch.object(p, "delete_aspects")
        mocker.patch.object(p, "upload_hub_from_dict")
        p.migrate_state(orig_hub="orig", hub_aspects=[HubAspects.Arm.value])
        assert p.rg == "rg2"


class TestProcessHubToDict:
    def test_configurations_and_devices(self, mocker):
        p = _provider(mocker)
        adm = {
            "id": "c1",
            "content": {"deviceContent": {"x": 1}},
            "targetCondition": "",
            "priority": 1,
            "labels": {},
            "metrics": {},
            "createdTimeUtc": "t",
            "etag": "e",
            "lastUpdatedTimeUtc": "t",
            "schemaVersion": "1",
        }
        edge = {"id": "e1", "content": {"modulesContent": {"x": 1}}}
        mocker.patch(f"{sp}._iot_hub_configuration_list", return_value=[adm, edge])
        mocker.patch.object(p, "download_devices", return_value={"d1": {}})
        result = p.process_hub_to_dict(p.target, [HubAspects.Configurations.value, HubAspects.Devices.value])
        assert "c1" in result["configurations"]["admConfigurations"]
        assert "e1" in result["configurations"]["edgeDeployments"]
        assert result["devices"] == {"d1": {}}

    def test_configurations_list_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_hub_configuration_list", side_effect=AzCLIError("boom"))
        result = p.process_hub_to_dict(p.target, [HubAspects.Configurations.value])
        assert "configurations" not in result

    def test_arm_aspect(self, mocker):
        p = _provider(mocker)
        p.discovery.find_resource.return_value = {
            "resourcegroup": "rg",
            "id": "/subscriptions/x/hub",
        }
        arm_json = {"resources": [{"name": "hub", "type": "Microsoft.Devices/IotHubs"}]}
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.return_value = arm_json
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(p, "check_controlplane")
        result = p.process_hub_to_dict(p.target, [HubAspects.Arm.value])
        assert result["arm"] == arm_json

    def test_arm_aspect_target_no_rg(self, mocker):
        p = _provider(mocker)
        p.target = {"entity": "hub.azure-devices.net"}
        p.discovery.find_resource.return_value = {
            "resourcegroup": "rg-from-resource",
            "id": "/subscriptions/x/hub",
        }
        arm_json = {"resources": [{"name": "hub", "type": "Microsoft.Devices/IotHubs"}]}
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.return_value = arm_json
        invoke = mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(p, "check_controlplane")
        result = p.process_hub_to_dict(p.target, [HubAspects.Arm.value])
        assert result["arm"] == arm_json
        assert "rg-from-resource" in invoke.call_args[0][0]

    def test_arm_aspect_empty(self, mocker):
        p = _provider(mocker)
        p.discovery.find_resource.return_value = {"resourcegroup": "rg", "id": "id"}
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.return_value = {"resources": []}
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        result = p.process_hub_to_dict(p.target, [HubAspects.Arm.value])
        assert "arm" not in result

    def test_arm_aspect_error(self, mocker):
        p = _provider(mocker)
        p.discovery.find_resource.side_effect = AzCLIError("boom")
        result = p.process_hub_to_dict(p.target, [HubAspects.Arm.value])
        assert "arm" not in result


class TestDownloadDevices:
    def test_list_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", side_effect=AzCLIError("boom"))
        assert p.download_devices(p.target) is None

    def test_basic_tier_no_properties(self, mocker):
        p = _provider(mocker)
        twin = {"deviceId": "d1"}
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[twin])
        result = p.download_devices(p.target)
        assert result == {}

    def test_full_device_with_module(self, mocker):
        p = _provider(mocker)
        twin = {
            "deviceId": "d1",
            "parentScopes": ["ms-azure-iot-edge://parentdev-abc123"],
            "properties": {
                "desired": {"$metadata": {}, "$version": 1, "foo": "bar"},
                "reported": {},
            },
            "tags": {"t": 1},
            "authenticationType": DeviceAuthApiType.sas.value,
            "x509Thumbprint": None,
        }
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[twin])
        mocker.patch(
            f"{sp}._iot_device_show",
            return_value={"authentication": {"symmetricKey": {"primaryKey": "pk"}}},
        )
        module = mocker.MagicMock()
        module.serialize.return_value = {
            "moduleId": "m1",
            "generationId": "g",
            "connectionStateUpdatedTime": "t",
            "lastActivityTime": "t",
            "cloudToDeviceMessageCount": 0,
            "etag": "e",
            "deviceId": "d1",
        }
        mocker.patch(f"{sp}._iot_device_module_list", return_value=[module])
        mocker.patch(
            f"{sp}._iot_device_module_show",
            return_value={"authentication": {"type": "sas"}},
        )
        mocker.patch(
            f"{sp}._iot_device_module_twin_show",
            return_value={
                "deviceEtag": "e",
                "lastActivityTime": "t",
                "etag": "e",
                "version": 1,
                "cloudToDeviceMessageCount": 0,
                "statusUpdateTime": "t",
                "authenticationType": "sas",
                "connectionState": "x",
                "deviceId": "d1",
                "moduleId": "m1",
                "x509Thumbprint": None,
                "properties": {"desired": {"$metadata": {}, "$version": 1}, "reported": {}},
            },
        )
        result = p.download_devices(p.target)
        assert "d1" in result
        assert "m1" in result["d1"]["modules"]
        assert result["d1"]["parent"] == "parentdev"

    def test_sas_show_fails(self, mocker):
        p = _provider(mocker)
        twin = {
            "deviceId": "d1",
            "properties": {"desired": {"$metadata": {}, "$version": 1}, "reported": {}},
            "authenticationType": DeviceAuthApiType.sas.value,
            "x509Thumbprint": None,
        }
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[twin])
        mocker.patch(f"{sp}._iot_device_show", side_effect=AzCLIError("boom"))
        result = p.download_devices(p.target)
        assert result == {}

    def _sas_device_twin(self):
        return {
            "deviceId": "d1",
            "properties": {"desired": {"$metadata": {}, "$version": 1}, "reported": {}},
            "authenticationType": DeviceAuthApiType.sas.value,
            "x509Thumbprint": None,
        }

    def _serialized_module(self, mocker):
        module = mocker.MagicMock()
        module.serialize.return_value = {
            "moduleId": "m1",
            "generationId": "g",
            "connectionStateUpdatedTime": "t",
            "lastActivityTime": "t",
            "cloudToDeviceMessageCount": 0,
            "etag": "e",
            "deviceId": "d1",
        }
        return module

    def test_module_list_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[self._sas_device_twin()])
        mocker.patch(
            f"{sp}._iot_device_show",
            return_value={"authentication": {"symmetricKey": {"primaryKey": "pk"}}},
        )
        mocker.patch(f"{sp}._iot_device_module_list", side_effect=AzCLIError("boom"))
        result = p.download_devices(p.target)
        assert "modules" not in result["d1"]

    def test_module_identity_show_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[self._sas_device_twin()])
        mocker.patch(
            f"{sp}._iot_device_show",
            return_value={"authentication": {"symmetricKey": {"primaryKey": "pk"}}},
        )
        mocker.patch(f"{sp}._iot_device_module_list", return_value=[self._serialized_module(mocker)])
        mocker.patch(f"{sp}._iot_device_module_show", side_effect=AzCLIError("boom"))
        result = p.download_devices(p.target)
        assert result["d1"]["modules"] == {}

    def test_module_twin_show_fails(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_device_twin_list", return_value=[self._sas_device_twin()])
        mocker.patch(
            f"{sp}._iot_device_show",
            return_value={"authentication": {"symmetricKey": {"primaryKey": "pk"}}},
        )
        mocker.patch(f"{sp}._iot_device_module_list", return_value=[self._serialized_module(mocker)])
        mocker.patch(
            f"{sp}._iot_device_module_show",
            return_value={"authentication": {"type": "sas"}},
        )
        mocker.patch(f"{sp}._iot_device_module_twin_show", side_effect=AzCLIError("boom"))
        result = p.download_devices(p.target)
        assert result["d1"]["modules"] == {}


class TestUploadHubFromDict:
    def _configs_state(self):
        adm = {
            "content": {"deviceContent": {}},
            "targetCondition": "",
            "priority": 1,
            "labels": {},
            "metrics": {},
        }
        edge = {
            "content": {"modulesContent": {"$edgeAgent": {"properties.desired": {}}}},
            "targetCondition": "",
            "priority": 1,
            "labels": {},
            "metrics": {},
        }
        layered = {
            "content": {"modulesContent": {"$edgeAgent": {}}},
            "targetCondition": "",
            "priority": 1,
            "labels": {},
            "metrics": {},
        }
        return {
            "configurations": {
                "admConfigurations": {"adm1": adm},
                "edgeDeployments": {"edge1": edge, "layered1": layered},
            }
        }

    def test_upload_configs(self, mocker):
        p = _provider(mocker)
        create = mocker.patch(f"{sp}._iot_hub_configuration_create")
        p.upload_hub_from_dict(self._configs_state(), [HubAspects.Configurations.value])
        assert create.call_count == 3

    def test_upload_configs_errors(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{sp}._iot_hub_configuration_create", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(self._configs_state(), [HubAspects.Configurations.value])

    def test_upload_devices(self, mocker):
        p = _provider(mocker)
        state = {
            "devices": {
                "d1": {
                    "identity": {"authentication": {"type": "sas"}},
                    "twin": {"properties": {}},
                    "parent": "parent1",
                    "modules": {
                        "m1": {
                            "identity": {"authentication": {"type": "sas"}},
                            "twin": {"properties": {}},
                        },
                        "$edgeAgent": {
                            "identity": {"authentication": {"type": "none"}},
                            "twin": {"properties": {"desired": {}}},
                        },
                    },
                }
            }
        }
        upload_dev = mocker.patch.object(p, "upload_device_identity")
        upload_mod = mocker.patch.object(p, "upload_module_identity")
        mocker.patch(f"{sp}._iot_device_twin_update")
        mocker.patch(f"{sp}._iot_device_module_twin_update")
        edge = mocker.patch(f"{sp}._iot_edge_set_modules")
        parent = mocker.patch(f"{sp}._iot_device_set_parent")
        p.upload_hub_from_dict(state, [HubAspects.Devices.value])
        upload_dev.assert_called_once()
        upload_mod.assert_called_once()
        edge.assert_called_once()
        parent.assert_called_once()

    def test_upload_devices_identity_error(self, mocker):
        p = _provider(mocker)
        state = {
            "devices": {
                "d1": {
                    "identity": {"authentication": {"type": "sas"}},
                    "twin": {"properties": {}},
                }
            }
        }
        mocker.patch.object(p, "upload_device_identity", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(state, [HubAspects.Devices.value])

    def _device_with_module_state(self):
        return {
            "devices": {
                "d1": {
                    "identity": {"authentication": {"type": "sas"}},
                    "twin": {"properties": {}},
                    "parent": "parent1",
                    "modules": {
                        "m1": {
                            "identity": {"authentication": {"type": "sas"}},
                            "twin": {"properties": {}},
                        },
                    },
                }
            }
        }

    def test_upload_devices_twin_error(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "upload_device_identity")
        mocker.patch(f"{sp}._iot_device_twin_update", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(self._device_with_module_state(), [HubAspects.Devices.value])

    def test_upload_devices_module_identity_error(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "upload_device_identity")
        mocker.patch(f"{sp}._iot_device_twin_update")
        mocker.patch(f"{sp}._iot_device_set_parent")
        mocker.patch.object(p, "upload_module_identity", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(self._device_with_module_state(), [HubAspects.Devices.value])

    def test_upload_devices_module_twin_error(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "upload_device_identity")
        mocker.patch(f"{sp}._iot_device_twin_update")
        mocker.patch(f"{sp}._iot_device_set_parent")
        mocker.patch.object(p, "upload_module_identity")
        mocker.patch(f"{sp}._iot_device_module_twin_update", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(self._device_with_module_state(), [HubAspects.Devices.value])

    def test_upload_devices_edge_module_error(self, mocker):
        p = _provider(mocker)
        state = {
            "devices": {
                "d1": {
                    "identity": {"authentication": {"type": "sas"}},
                    "twin": {"properties": {}},
                    "modules": {
                        "$edgeAgent": {
                            "identity": {"authentication": {"type": "none"}},
                            "twin": {"properties": {"desired": {}}},
                        },
                    },
                }
            }
        }
        mocker.patch.object(p, "upload_device_identity")
        mocker.patch(f"{sp}._iot_device_twin_update")
        mocker.patch(f"{sp}._iot_edge_set_modules", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(state, [HubAspects.Devices.value])

    def test_upload_devices_parent_error(self, mocker):
        p = _provider(mocker)
        state = {
            "devices": {
                "d1": {
                    "identity": {"authentication": {"type": "sas"}},
                    "twin": {"properties": {}},
                    "parent": "parent1",
                }
            }
        }
        mocker.patch.object(p, "upload_device_identity")
        mocker.patch(f"{sp}._iot_device_twin_update")
        mocker.patch(f"{sp}._iot_device_set_parent", side_effect=AzCLIError("boom"))
        p.upload_hub_from_dict(state, [HubAspects.Devices.value])

    def test_upload_no_target_raises(self, mocker):
        p = _provider(mocker, target=None)
        with pytest.raises(BadRequestError):
            p.upload_hub_from_dict({}, [HubAspects.Devices.value])

    def test_upload_leftover_aspects_warns(self, mocker):
        p = _provider(mocker)
        p.upload_hub_from_dict({}, [HubAspects.Devices.value])

    def _arm_state(self):
        return {
            "arm": {
                "resources": [
                    {
                        "name": "oldhub",
                        "type": "Microsoft.Devices/IotHubs",
                        "location": "westus",
                        "sku": {},
                        "identity": {},
                        "properties": {
                            "eventHubEndpoints": {"events": {"partitionCount": 4}},
                            "features": "None",
                            "routing": {"endpoints": {}, "routes": []},
                            "storageEndpoints": {},
                        },
                    }
                ]
            }
        }

    def test_upload_arm_existing_target(self, mocker):
        p = _provider(mocker)
        p.discovery.find_resource.return_value = {
            "resourcegroup": "rg",
            "location": "eastus",
            "sku": {"name": "S1"},
            "properties": {
                "eventHubEndpoints": {"events": {"partitionCount": 2}},
                "features": "DeviceManagement",
            },
        }
        invoke_result = mocker.MagicMock()
        invoke_result.success.return_value = True
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(state_module.os, "remove")
        p.upload_hub_from_dict(self._arm_state(), [HubAspects.Arm.value])

    def test_upload_arm_existing_target_no_rg_with_certs(self, mocker):
        p = _provider(mocker)
        p.rg = None
        p.discovery.find_resource.return_value = {
            "resourcegroup": "rg-resolved",
            "location": "eastus",
            "sku": {"name": "S1"},
            "properties": {
                "eventHubEndpoints": {"events": {"partitionCount": 2}},
                "features": "DeviceManagement",
                "enableDataResidency": True,
            },
        }
        state = self._arm_state()
        state["arm"]["resources"][0]["properties"]["enableDataResidency"] = False
        # add a certificate resource and an extra non-cert resource (private endpoint)
        state["arm"]["resources"].append(
            {
                "name": "oldhub/cert1",
                "type": "Microsoft.Devices/IotHubs/certificates",
                "dependsOn": ["[resourceId('Microsoft.Devices/IotHubs', 'oldhub')]"],
            }
        )
        state["arm"]["resources"].append(
            {
                "name": "oldhub/pe1",
                "type": "Microsoft.Devices/IotHubs/privateEndpointConnections",
            }
        )
        invoke_result = mocker.MagicMock()
        invoke_result.success.return_value = True
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(state_module.os, "remove")
        p.upload_hub_from_dict(state, [HubAspects.Arm.value])
        assert p.rg == "rg-resolved"
        cert = state["arm"]["resources"][-1]
        assert cert["name"] == "hub/cert1"
        assert cert["dependsOn"][0].split("'")[3] == "hub"

    def test_upload_arm_deployment_fails(self, mocker):
        p = _provider(mocker)
        p.discovery.find_resource.return_value = {
            "resourcegroup": "rg",
            "location": "eastus",
            "sku": {"name": "S1"},
            "properties": {
                "eventHubEndpoints": {"events": {"partitionCount": 2}},
                "features": "DeviceManagement",
            },
        }
        invoke_result = mocker.MagicMock()
        invoke_result.success.return_value = False
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(state_module.os, "remove")
        with pytest.raises(BadRequestError):
            p.upload_hub_from_dict(self._arm_state(), [HubAspects.Arm.value])

    def test_upload_arm_new_hub_identity_endpoint_error(self, mocker):
        p = _provider(mocker, target=None)
        p.rg = "rg"
        state = self._arm_state()
        state["arm"]["resources"][0]["properties"]["routing"]["endpoints"] = {
            "eventHubs": [{"name": "ep1", "authenticationType": "identityBased"}]
        }
        with pytest.raises(BadRequestError):
            p.upload_hub_from_dict(state, [HubAspects.Arm.value])

    def test_upload_arm_new_hub_success(self, mocker):
        p = _provider(mocker, target=None)
        p.rg = "rg"
        invoke_result = mocker.MagicMock()
        invoke_result.success.return_value = True
        invoke_result.as_json.return_value = {"resourceGroup": "rg"}
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        mocker.patch.object(state_module.os, "remove")
        p.discovery.get_target.return_value = {"name": "hub", "entity": "hub.azure-devices.net"}
        p.upload_hub_from_dict(self._arm_state(), [HubAspects.Arm.value])
        assert p.target is not None


class TestStateProviderInit:
    def test_init_success(self, mocker):
        def fake_init(self, **kwargs):
            self.target = {"name": "hub", "resourcegroup": "rg"}
            self.rg = None

        mocker.patch.object(state_module.IoTHubProvider, "__init__", fake_init)
        p = StateProvider(cmd=mocker.MagicMock())
        assert p.hub_name == "hub"
        assert p.rg == "rg"

    def test_init_not_found_export(self, mocker):
        def fake_init(self, **kwargs):
            self.rg = None
            raise ResourceNotFoundError("nf")

        mocker.patch.object(state_module.IoTHubProvider, "__init__", fake_init)
        with pytest.raises(ResourceNotFoundError):
            StateProvider(cmd=mocker.MagicMock(), export=True)

    def test_init_not_found_no_export(self, mocker):
        def fake_init(self, **kwargs):
            self.rg = None
            raise ResourceNotFoundError("nf")

        mocker.patch.object(state_module.IoTHubProvider, "__init__", fake_init)
        p = StateProvider(cmd=mocker.MagicMock(), export=False)
        assert p.target is None

    def test_get_client(self, mocker):
        p = _provider(mocker)
        factory = mocker.patch(f"{sp}.iot_hub_service_factory", return_value="client")
        assert p._get_client() == "client"
        factory.assert_called_once()


class TestCheckControlplane:
    def _invoke(self, mocker, success=True, as_json=None):
        result = mocker.MagicMock()
        result.success.return_value = success
        result.as_json.return_value = as_json if as_json is not None else {}
        return result

    def _hub_resource(self):
        return {
            "identity": {"userAssignedIdentities": {}},
            "properties": {
                "routing": {
                    "endpoints": {
                        "cosmosDBSqlContainers": [],
                        "eventHubs": [],
                        "serviceBusQueues": [],
                        "serviceBusTopics": [],
                        "storageContainers": [],
                    },
                    "routes": [],
                },
                "storageEndpoints": {},
            },
        }

    def test_uai_existing_and_missing(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["identity"]["userAssignedIdentities"] = {"id1": {}, "id2": {}}
        invoke = mocker.patch.object(state_module.cli, "invoke")
        invoke.side_effect = [
            self._invoke(mocker, success=True),
            self._invoke(mocker, success=False),
        ]
        p.check_controlplane(hub)
        assert "id1" in hub["identity"]["userAssignedIdentities"]
        assert "id2" not in hub["identity"]["userAssignedIdentities"]

    def test_cosmos_connection_string(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = [
            {
                "name": "c1",
                "endpointUri": "https://acct.documents.azure.com",
                "primaryKey": "pk",
                "secondaryKey": "sk",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        cosmos_keys = {
            "connectionStrings": [
                {"description": "Primary SQL Connection String", "connectionString": "cs1"},
                {"description": "Secondary SQL Connection String", "connectionString": "cs2"},
            ]
        }
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, as_json=cosmos_keys)
        )
        mocker.patch(
            f"{sp}.parse_cosmos_db_connection_string", return_value={"AccountKey": "parsed"}
        )
        p.check_controlplane(hub)
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]["primaryKey"] == "parsed"

    def test_cosmos_show_success(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = [
            {
                "name": "c1",
                "endpointUri": "https://acct.documents.azure.com",
                "databaseName": "db",
                "collectionName": "col",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=True)
        )
        p.check_controlplane(hub)
        assert len(hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]) == 1

    def test_cosmos_show_fails(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = [
            {
                "name": "c1",
                "endpointUri": "https://acct.documents.azure.com",
                "databaseName": "db",
                "collectionName": "col",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        hub["properties"]["routing"]["routes"] = [{"name": "r1", "endpointNames": ["c1"]}]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=False)
        )
        p.check_controlplane(hub)
        assert not hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]
        assert not hub["properties"]["routing"]["routes"]

        p = _provider(mocker)
        hub = self._hub_resource()
        hub["identity"]["userAssignedIdentities"] = {"id1": {}}
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = [
            {
                "name": "c1",
                "endpointUri": "https://acct.documents.azure.com",
                "identity": {"userAssignedIdentity": "id1"},
            }
        ]
        hub["properties"]["routing"]["routes"] = [
            {"name": "r1", "endpointNames": ["c1"]}
        ]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=False)
        )
        p.check_controlplane(hub)
        # endpoint stays in list but its route is removed
        assert not hub["properties"]["routing"]["routes"]

    def test_eventhub_and_servicebus_cstring(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        ep = {
            "name": "e1",
            "connectionString": "cs",
            "resourceGroup": "rg",
            "subscriptionId": "sub",
        }
        hub["properties"]["routing"]["endpoints"]["eventHubs"] = [dict(ep)]
        hub["properties"]["routing"]["endpoints"]["serviceBusQueues"] = [dict(ep)]
        hub["properties"]["routing"]["endpoints"]["serviceBusTopics"] = [dict(ep)]
        mocker.patch(
            f"{sp}.parse_iot_hub_message_endpoint_connection_string",
            return_value={
                "Endpoint": "sb://ns.servicebus.windows.net",
                "EntityPath": "path",
                "SharedAccessKeyName": "key",
            },
        )
        mocker.patch.object(
            state_module.cli,
            "invoke",
            return_value=self._invoke(mocker, as_json={"primaryConnectionString": "newcs"}),
        )
        p.check_controlplane(hub)
        assert hub["properties"]["routing"]["endpoints"]["eventHubs"][0]["connectionString"] == "newcs"

    def test_eventhub_servicebus_show_success(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        ep = {
            "name": "e1",
            "endpointUri": "sb://ns.servicebus.windows.net",
            "entityPath": "path",
            "resourceGroup": "rg",
            "subscriptionId": "sub",
        }
        hub["properties"]["routing"]["endpoints"]["eventHubs"] = [dict(ep)]
        hub["properties"]["routing"]["endpoints"]["serviceBusQueues"] = [dict(ep)]
        hub["properties"]["routing"]["endpoints"]["serviceBusTopics"] = [dict(ep)]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=True)
        )
        p.check_controlplane(hub)
        assert len(hub["properties"]["routing"]["endpoints"]["eventHubs"]) == 1

    def test_storage_cstring_and_route_removal(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["storageContainers"] = [
            {
                "name": "s1",
                "connectionString": "cs",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        # a route that uses a removed endpoint
        hub["properties"]["routing"]["endpoints"]["eventHubs"] = [
            {
                "name": "removedEp",
                "endpointUri": "sb://ns.servicebus.windows.net",
                "entityPath": "path",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        hub["properties"]["routing"]["routes"] = [
            {"name": "r1", "endpointNames": ["removedEp"]},
            {"name": "r2", "endpointNames": ["s1"]},
        ]
        mocker.patch(
            f"{sp}.parse_storage_container_connection_string",
            return_value={"AccountName": "acct"},
        )

        def invoke_side_effect(command):
            if "eventhubs eventhub show" in command:
                return self._invoke(mocker, success=False)
            return self._invoke(mocker, as_json={"connectionString": "newcs"})

        mocker.patch.object(state_module.cli, "invoke", side_effect=invoke_side_effect)
        p.check_controlplane(hub)
        route_names = [r["name"] for r in hub["properties"]["routing"]["routes"]]
        assert "r1" not in route_names
        assert "r2" in route_names

    def test_file_upload_cstring(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["storageEndpoints"] = {
            "$default": {"connectionString": "cs"}
        }
        mocker.patch(
            f"{sp}.parse_storage_container_connection_string",
            return_value={"AccountName": "acct"},
        )
        mocker.patch.object(
            state_module.cli,
            "invoke",
            return_value=self._invoke(mocker, as_json={"connectionString": "newcs"}),
        )
        p.check_controlplane(hub)
        assert hub["properties"]["storageEndpoints"]["$default"]["connectionString"] == "newcs"

    def test_file_upload_cstring_fails(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["storageEndpoints"] = {
            "$default": {"connectionString": "cs", "containerName": "c"}
        }
        mocker.patch(
            f"{sp}.parse_storage_container_connection_string",
            return_value={"AccountName": "acct"},
        )
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.side_effect = AzCLIError("boom")
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        p.check_controlplane(hub)
        assert hub["properties"]["storageEndpoints"]["$default"]["connectionString"] is None

    def test_file_upload_uai_removed(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["identity"]["userAssignedIdentities"] = {"id1": {}}
        hub["properties"]["storageEndpoints"] = {
            "$default": {"identity": {"userAssignedIdentity": "id1"}}
        }
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=False)
        )
        p.check_controlplane(hub)
        assert hub["properties"]["storageEndpoints"]["$default"]["authenticationType"] is None

    def test_cosmos_cstring_retrieve_fail(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = [
            {
                "name": "c1",
                "endpointUri": "https://acct.documents.azure.com",
                "primaryKey": "pk",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.side_effect = AzCLIError("boom")
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        p.check_controlplane(hub)
        assert not hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]

    @pytest.mark.parametrize(
        "ep_type", ["eventHubs", "serviceBusQueues", "serviceBusTopics"]
    )
    def test_sb_eventhub_cstring_retrieve_fail(self, mocker, ep_type):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"][ep_type] = [
            {
                "name": "e1",
                "connectionString": "cs",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        mocker.patch(
            f"{sp}.parse_iot_hub_message_endpoint_connection_string",
            return_value={
                "Endpoint": "sb://ns.servicebus.windows.net",
                "EntityPath": "path",
                "SharedAccessKeyName": "key",
            },
        )
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.side_effect = AzCLIError("boom")
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        p.check_controlplane(hub)
        assert hub["properties"]["routing"]["endpoints"][ep_type] == []

    @pytest.mark.parametrize(
        "ep_type,show_cmd",
        [
            ("eventHubs", "eventhubs eventhub show"),
            ("serviceBusQueues", "servicebus queue show"),
            ("serviceBusTopics", "servicebus topic show"),
            ("storageContainers", "storage account show"),
        ],
    )
    def test_endpoint_show_fail(self, mocker, ep_type, show_cmd):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"][ep_type] = [
            {
                "name": "e1",
                "endpointUri": "sb://ns.servicebus.windows.net"
                if ep_type != "storageContainers"
                else "https://acct.blob.core.windows.net",
                "entityPath": "path",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=False)
        )
        p.check_controlplane(hub)
        assert hub["properties"]["routing"]["endpoints"][ep_type] == []

    def test_storage_cstring_retrieve_fail(self, mocker):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["properties"]["routing"]["endpoints"]["storageContainers"] = [
            {
                "name": "s1",
                "connectionString": "cs",
                "resourceGroup": "rg",
                "subscriptionId": "sub",
            }
        ]
        mocker.patch(
            f"{sp}.parse_storage_container_connection_string",
            return_value={"AccountName": "acct"},
        )
        invoke_result = mocker.MagicMock()
        invoke_result.as_json.side_effect = AzCLIError("boom")
        mocker.patch.object(state_module.cli, "invoke", return_value=invoke_result)
        p.check_controlplane(hub)
        assert not hub["properties"]["routing"]["endpoints"]["storageContainers"]

    @pytest.mark.parametrize(
        "ep_type", ["eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"]
    )
    def test_endpoint_uai_removed(self, mocker, ep_type):
        p = _provider(mocker)
        hub = self._hub_resource()
        hub["identity"]["userAssignedIdentities"] = {"id1": {}}
        hub["properties"]["routing"]["endpoints"][ep_type] = [
            {"name": "e1", "identity": {"userAssignedIdentity": "id1"}}
        ]
        hub["properties"]["routing"]["routes"] = [
            {"name": "r1", "endpointNames": ["e1"]}
        ]
        mocker.patch.object(
            state_module.cli, "invoke", return_value=self._invoke(mocker, success=False)
        )
        p.check_controlplane(hub)
        # route referencing the UAI-removed endpoint is dropped
        assert not hub["properties"]["routing"]["routes"]
