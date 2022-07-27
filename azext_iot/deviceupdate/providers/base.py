# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# flake8: noqa: E402

from azext_iot.deviceupdate.providers.loaders import reload_modules
reload_modules()

from azext_iot.constants import USER_AGENT
from azext_iot.sdk.deviceupdate.controlplane import DeviceUpdate
from azext_iot.sdk.deviceupdate.controlplane import (
    models as DeviceUpdateMgmtModels,
)

from azext_iot.deviceupdate.common import SYSTEM_IDENTITY_ARG
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import handle_service_exception
from azure.cli.core.commands.client_factory import get_mgmt_service_client
from azure.cli.core.azclierror import ResourceNotFoundError, CLIInternalError
from azure.mgmt.core.polling.arm_polling import ARMPolling
from azure.core.exceptions import AzureError
from typing import NamedTuple, Union, List


class AccountContainer(NamedTuple):
    account: DeviceUpdateMgmtModels.Account
    resource_group: str


__all__ = [
    "DeviceUpdateClientHandler",
    "DeviceUpdateAccountManager",
    "DeviceUpdateMgmtModels",
    "parse_account_rg",
    "AccountContainer",
    "ARMPolling",
    "AzureError",
]


def parse_account_rg(id: str):
    return id.split("/")[4]


class DeviceUpdateClientHandler(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_client(self) -> DeviceUpdate:
        client: DeviceUpdate = get_mgmt_service_client(self.cmd.cli_ctx, DeviceUpdate)

        # Adding IoT Ext User-Agent is done with best attempt.
        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client

    def get_data_client(self):
        pass


class DeviceUpdateAccountManager(DeviceUpdateClientHandler):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)
        self.mgmt_client = self.get_mgmt_client()
        self.cli = EmbeddedCLI()

    def find_account(self, target_name: str, target_rg: str = None) -> AccountContainer:
        def find_account_rg(id: str):
            return id.split("/")[4]

        if target_rg:
            try:
                account = self.mgmt_client.accounts.get(
                    resource_group_name=target_rg, account_name=target_name
                )
                return AccountContainer(account, find_account_rg(account.id))
            except AzureError as e:
                handle_service_exception(e)

        try:
            for account in self.mgmt_client.accounts.list_by_subscription():
                if account.name == target_name:
                    return AccountContainer(account, find_account_rg(account.id))
        except AzureError as e:
            handle_service_exception(e)

        raise ResourceNotFoundError(
            f"DeviceUpdate account: '{target_name}' not found by auto-discovery. "
            "Provide resource group via -g for direct lookup."
        )

    @classmethod
    def assemble_account_auth(
        cls,
        assign_identity: list,
    ) -> Union[None, DeviceUpdateMgmtModels.ManagedServiceIdentity]:
        if not assign_identity:
            return None

        if len(assign_identity) == 1:
            if SYSTEM_IDENTITY_ARG in assign_identity:
                return DeviceUpdateMgmtModels.ManagedServiceIdentity(
                    type=DeviceUpdateMgmtModels.ManagedServiceIdentityType.SYSTEM_ASSIGNED
                )
            else:
                return DeviceUpdateMgmtModels.ManagedServiceIdentity(
                    type=DeviceUpdateMgmtModels.ManagedServiceIdentityType.USER_ASSIGNED,
                    user_assigned_identities={assign_identity[0], {}},
                )
        else:
            target_identity_type = (
                DeviceUpdateMgmtModels.ManagedServiceIdentityType.USER_ASSIGNED
            )
            user_assigned_identities = {}
            has_system = False
            for identity in assign_identity:
                if identity == SYSTEM_IDENTITY_ARG and not has_system:
                    target_identity_type = (
                        DeviceUpdateMgmtModels.ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED
                    )
                    has_system = True
                else:
                    user_assigned_identities[identity] = {}

            return DeviceUpdateMgmtModels.ManagedServiceIdentity(
                type=target_identity_type,
                user_assigned_identities=user_assigned_identities,
            )

    def assign_msi_scope(
        self,
        principal_id: str,
        scope: str,
        principal_type: str = "ServicePrincipal",
        role: str = "Contributor",
    ) -> dict:
        assign_op = self.cli.invoke(
            f"role assignment create --scope '{scope}' --role '{role}' --assignee-object-id '{principal_id}' "
            f"--assignee-principal-type '{principal_type}'"
        )
        if not assign_op.success():
            raise CLIInternalError(f"Failed to assign '{principal_id}' the role of '{role}' against scope '{scope}'.")

        return assign_op.as_json()

    def get_rg_location(
        self,
        resource_group_name: str,
    ):
        resource_group_meta = self.cli.invoke(
            f"group show --name {resource_group_name}"
        ).as_json()
        return resource_group_meta["location"]


class DeviceUpdateInstanceManager(DeviceUpdateAccountManager):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)

    def assemble_iothub_resources(
        self, resource_ids: List[str]
    ) -> List[DeviceUpdateMgmtModels.IotHubSettings]:
        iothub_settings_list: List[DeviceUpdateMgmtModels.IotHubSettings] = []
        for id in resource_ids:
            iothub_settings_list.append(
                DeviceUpdateMgmtModels.IotHubSettings(resource_id=id)
            )
        return iothub_settings_list

    def assemble_diagnostic_storage(
        self, storage_id: str
    ) -> DeviceUpdateMgmtModels.DiagnosticStorageProperties:
        diagnostic_storage = DeviceUpdateMgmtModels.DiagnosticStorageProperties(
            authentication_type="KeyBased", resource_id=storage_id
        )
        cstring_op = self.cli.invoke(
            f"storage account show-connection-string --ids {storage_id}"
        )
        if not cstring_op.success():
            raise CLIInternalError(f"Failed to fetch storage account connection string with resource id of '{storage_id}'.")
        diagnostic_storage.connection_string = cstring_op.as_json()["connectionString"]

        # @digimaun - the service appears to have a limitation handling the EndpointSuffix segment, it must be at the end.
        split_cstring: list = diagnostic_storage.connection_string.split(";")
        endpoint_suffix = "EndpointSuffix=core.windows.net"
        for i in range(0, len(split_cstring)):
            if "EndpointSuffix=" in split_cstring[i]:
                endpoint_suffix = split_cstring.pop(i)
                break
        split_cstring.append(endpoint_suffix)
        diagnostic_storage.connection_string = ";".join(split_cstring)
        return diagnostic_storage
