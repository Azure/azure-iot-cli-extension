# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, patch

from azext_iot.adr import commands_su

RG = "test-rg"
INSTANCE = "test-update-instance"
UAMI_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
)


def test_update_instance_commands_delegate_all_arguments():
    cmd = Mock()
    with patch(
        "azext_iot.adr.commands_su.UpdateInstanceProvider"
    ) as provider_type:
        provider = provider_type.return_value

        commands_su.adr_su_instance_check_name(cmd, INSTANCE)
        commands_su.adr_su_instance_list(cmd, RG)
        commands_su.adr_su_instance_show(cmd, INSTANCE, RG)
        commands_su.adr_su_instance_create(
            cmd,
            INSTANCE,
            RG,
            location="eastus2",
            tags={"env": "test"},
            mi_system_assigned=True,
            mi_user_assigned=[UAMI_ID],
            no_wait=True,
        )
        commands_su.adr_su_instance_update(
            cmd,
            INSTANCE,
            RG,
            tags={},
            mi_system_assigned=False,
            mi_user_assigned=[UAMI_ID],
            no_wait=True,
        )
        commands_su.adr_su_instance_delete(cmd, INSTANCE, RG, no_wait=True)

        assert provider_type.call_count == 6
        provider.check_name.assert_called_once_with(INSTANCE)
        provider.list.assert_called_once_with(resource_group_name=RG)
        provider.show.assert_called_once_with(
            update_instance_name=INSTANCE,
            resource_group_name=RG,
        )
        provider.create.assert_called_once_with(
            update_instance_name=INSTANCE,
            resource_group_name=RG,
            location="eastus2",
            tags={"env": "test"},
            mi_system_assigned=True,
            mi_user_assigned=[UAMI_ID],
            no_wait=True,
        )
        provider.update.assert_called_once_with(
            update_instance_name=INSTANCE,
            resource_group_name=RG,
            tags={},
            mi_system_assigned=False,
            mi_user_assigned=[UAMI_ID],
            no_wait=True,
        )
        provider.delete.assert_called_once_with(
            update_instance_name=INSTANCE,
            resource_group_name=RG,
            no_wait=True,
        )


def test_software_update_commands_delegate_all_arguments():
    cmd = Mock()
    with patch(
        "azext_iot.adr.commands_su.SoftwareUpdateProvider"
    ) as provider_type:
        provider = provider_type.return_value

        commands_su.adr_su_software_update_list(
            cmd, "ns", RG, search="s", filter="f"
        )
        commands_su.adr_su_software_update_show(
            cmd, "ns", RG, "p", "n", "v"
        )
        commands_su.adr_su_software_update_delete(
            cmd, "ns", RG, "p", "n", "v", no_wait=True
        )
        commands_su.adr_su_software_update_import(
            cmd,
            "ns",
            RG,
            "https://example.test/manifest",
            size=1,
            hashes=["sha256=digest"],
            friendly_name="friendly",
            files=[["filename=f", "url=https://example.test/f"]],
            enable_scan=True,
            no_wait=True,
        )
        commands_su.adr_su_software_update_stage(
            cmd,
            "ns",
            RG,
            ["manifest.json"],
            "storage",
            "updates",
            storage_account_subscription="storage-sub",
            storage_prefix="prefix",
            friendly_name="friendly",
            enable_scan=True,
            overwrite=True,
            then_import=True,
            sas_expiry_hours=6,
            no_wait=True,
        )
        commands_su.adr_su_software_update_file_list(
            cmd, "ns", RG, "p", "n", "v"
        )
        commands_su.adr_su_software_update_file_show(
            cmd, "ns", RG, "p", "n", "v", "file-id"
        )
        commands_su.adr_su_software_update_operation_status_list(
            cmd, "ns", RG
        )
        commands_su.adr_su_software_update_operation_status_show(
            cmd, "ns", RG, "operation"
        )
        commands_su.adr_su_software_update_provider_list(cmd, "ns", RG)
        commands_su.adr_su_software_update_name_list(
            cmd, "ns", RG, "p"
        )
        commands_su.adr_su_software_update_version_list(
            cmd, "ns", RG, "p", "n", filter="f"
        )

        assert provider_type.call_count == 12
        provider.list_updates.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            search="s",
            filter="f",
        )
        provider.show_update.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
            update_name="n",
            update_version="v",
        )
        provider.delete_update.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
            update_name="n",
            update_version="v",
            no_wait=True,
        )
        provider.import_update.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            url="https://example.test/manifest",
            size=1,
            hashes=["sha256=digest"],
            friendly_name="friendly",
            files=[["filename=f", "url=https://example.test/f"]],
            enable_scan=True,
            no_wait=True,
        )
        provider.stage_update.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            manifest_paths=["manifest.json"],
            storage_account="storage",
            storage_container_name="updates",
            storage_account_subscription="storage-sub",
            storage_prefix="prefix",
            friendly_name="friendly",
            enable_scan=True,
            overwrite=True,
            then_import=True,
            sas_expiry_hours=6,
            no_wait=True,
        )
        provider.list_update_files.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
            update_name="n",
            update_version="v",
        )
        provider.show_update_file.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
            update_name="n",
            update_version="v",
            update_file_id="file-id",
        )
        provider.list_operation_statuses.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
        )
        provider.show_operation_status.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            operation_id="operation",
        )
        provider.list_providers.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
        )
        provider.list_names.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
        )
        provider.list_versions.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            update_provider="p",
            update_name="n",
            filter="f",
        )


def test_device_class_commands_delegate_all_arguments():
    cmd = Mock()
    with patch(
        "azext_iot.adr.commands_su.DeviceClassProvider"
    ) as provider_type:
        provider = provider_type.return_value

        commands_su.adr_su_device_class_list(cmd, "ns", RG)
        commands_su.adr_su_device_class_show(cmd, "ns", RG, "class")
        commands_su.adr_su_device_class_delete(cmd, "ns", RG, "class")

        assert provider_type.call_count == 3
        provider.list.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
        )
        provider.show.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            device_class_id="class",
        )
        provider.delete.assert_called_once_with(
            namespace_name="ns",
            resource_group_name=RG,
            device_class_id="class",
        )


def test_local_software_update_commands_delegate():
    cmd = Mock()
    with patch(
        "azext_iot.adr.commands_su.calculate_update_hash",
        return_value=[{"hash": "digest"}],
    ) as calculate, patch(
        "azext_iot.adr.commands_su.manifest_init_v5",
        return_value={"manifestVersion": "5.0"},
    ) as manifest:
        assert commands_su.adr_su_software_update_calculate_hash(
            ["payload.bin"], "sha256"
        ) == [{"hash": "digest"}]
        assert commands_su.adr_su_software_update_manifest_init_v5(
            cmd,
            "name",
            "provider",
            "version",
            [["manufacturer=Contoso"]],
            [["handler=microsoft/script:1"]],
            files=[["path=payload.bin"]],
            related_files=[["path=signature"]],
            description="description",
            deployable=False,
            no_validation=True,
        ) == {"manifestVersion": "5.0"}

    calculate.assert_called_once_with(
        file_paths=["payload.bin"],
        hash_algo="sha256",
    )
    manifest.assert_called_once_with(
        cmd=cmd,
        update_name="name",
        update_provider="provider",
        update_version="version",
        compatibility=[["manufacturer=Contoso"]],
        steps=[["handler=microsoft/script:1"]],
        files=[["path=payload.bin"]],
        related_files=[["path=signature"]],
        description="description",
        deployable=False,
        no_validation=True,
    )
