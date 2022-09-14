# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.deviceupdate.providers.loaders import reload_modules

reload_modules()

from knack.log import get_logger
from azext_iot.constants import USER_AGENT
from azext_iot.sdk.deviceupdate.controlplane import DeviceUpdate
from azext_iot.sdk.deviceupdate.controlplane import (
    models as DeviceUpdateMgmtModels,
)
from azext_iot.sdk.deviceupdate.dataplane import DeviceUpdateClient
from azext_iot.sdk.deviceupdate.dataplane import models as DeviceUpdateDataModels

from azext_iot.deviceupdate.common import SYSTEM_IDENTITY_ARG, AUTH_RESOURCE_ID
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import handle_service_exception
from azure.cli.core.commands.client_factory import get_mgmt_service_client
from azure.cli.core.azclierror import ResourceNotFoundError, CLIInternalError, InvalidArgumentValueError
from azure.mgmt.core.polling.arm_polling import ARMPolling
from azure.core.exceptions import AzureError, HttpResponseError
from msrest.serialization import Model
from pathlib import Path
from typing import Any, NamedTuple, Union, List, Dict, Tuple, Optional
import json
import os


logger = get_logger(__name__)


class AccountContainer(NamedTuple):
    account: DeviceUpdateMgmtModels.Account
    resource_group: str


class UpdateManifestMeta(NamedTuple):
    bytes: int
    hash: str


__all__ = [
    "DeviceUpdateClientHandler",
    "DeviceUpdateAccountManager",
    "DeviceUpdateMgmtModels",
    "DeviceUpdateDataManager",
    "DeviceUpdateDataModels",
    "parse_account_rg",
    "AccountContainer",
    "UpdateManifestMeta",
    "ARMPolling",
    "AzureError",
    "HttpResponseError",
    "MicroObjectCache",
]


def parse_account_rg(id: str):
    return id.split("/")[4]


class DeviceUpdateClientHandler(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_client(self) -> DeviceUpdate:
        client: DeviceUpdate = get_mgmt_service_client(self.cmd.cli_ctx, DeviceUpdate)
        self._add_useragents(client)
        return client

    def get_data_client(self, endpoint: str, instance_id: str) -> DeviceUpdateClient:
        from azure.cli.core.commands.client_factory import prepare_client_kwargs_track2
        from azure.cli.core._profile import Profile

        profile = Profile()
        client: DeviceUpdateClient = DeviceUpdateClient(
            credential=profile.get_login_credentials(resource=AUTH_RESOURCE_ID)[0],
            endpoint=endpoint,
            instance_id=instance_id,
            **prepare_client_kwargs_track2(self.cmd.cli_ctx),
        )
        self._add_useragents(client)
        return client

    def _add_useragents(self, client: Union[DeviceUpdate, DeviceUpdateClient]):
        # Adding IoT Ext User-Agent is done with best attempt.
        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass
        return client


class DeviceUpdateAccountManager(DeviceUpdateClientHandler):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)
        self.mgmt_client = self.get_mgmt_client()
        self.cli = EmbeddedCLI(user_subscription=cmd.cli_ctx.data["subscription_id"])

    def find_account(self, target_name: str, target_rg: Optional[str] = None) -> AccountContainer:
        def find_account_rg(id: str):
            return id.split("/")[4]

        if target_rg:
            try:
                account = self.mgmt_client.accounts.get(resource_group_name=target_rg, account_name=target_name)
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
            target_identity_type = DeviceUpdateMgmtModels.ManagedServiceIdentityType.USER_ASSIGNED
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
    ) -> str:
        resource_group_meta = self.cli.invoke(f"group show --name {resource_group_name}").as_json()
        return resource_group_meta["location"]


class DeviceUpdateInstanceManager(DeviceUpdateAccountManager):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)

    def assemble_iothub_resources(self, resource_ids: List[str]) -> List[DeviceUpdateMgmtModels.IotHubSettings]:
        iothub_settings_list: List[DeviceUpdateMgmtModels.IotHubSettings] = []
        for id in resource_ids:
            iothub_settings_list.append(DeviceUpdateMgmtModels.IotHubSettings(resource_id=id))
        return iothub_settings_list

    def assemble_diagnostic_storage(self, storage_id: str) -> DeviceUpdateMgmtModels.DiagnosticStorageProperties:
        diagnostic_storage = DeviceUpdateMgmtModels.DiagnosticStorageProperties(
            authentication_type="KeyBased", resource_id=storage_id
        )
        cstring_op = self.cli.invoke(f"storage account show-connection-string --ids {storage_id}")
        if not cstring_op.success():
            raise CLIInternalError(
                f"Failed to fetch storage account connection string with resource id of '{storage_id}'."
            )
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


class DeviceUpdateDataManager(DeviceUpdateAccountManager):
    def __init__(self, cmd, account_name: str, instance_name: str, resource_group: Optional[str] = None):
        super().__init__(cmd=cmd)
        self.container = self.find_account(target_name=account_name, target_rg=resource_group)
        self.data_client = self.get_data_client(self.container.account.host_name, instance_name)

    def calculate_manifest_metadata(self, url: str) -> UpdateManifestMeta:
        """
        Calculates key attributes of an update manifest fetched from a given url.
        The hash value is a base64 representation of a sha256 digest.
        """
        from urllib.request import urlopen
        from base64 import b64encode
        from hashlib import sha256

        with urlopen(url) as f:
            file_content: bytes = f.read()
            hash = b64encode(sha256(file_content).digest()).decode("utf8")
            return UpdateManifestMeta(len(file_content), hash)

    def assemble_hashes(self, hash_list: List[str]) -> Dict[str, str]:
        result = {}
        if not hash_list:
            return result
        for hash in hash_list:
            split_hash = hash.split("=", 1)
            result[split_hash[0]] = split_hash[1]
        return result

    def assemble_files(self, file_list_col: List[List[str]]) -> Union[DeviceUpdateDataModels.FileImportMetadata, None]:
        if not file_list_col:
            return

        result: List[DeviceUpdateDataModels.FileImportMetadata] = []
        for file_list in file_list_col:
            file_name = None
            file_url = None
            for file_component in file_list:
                split_file_comp = file_component.split("=", 1)
                file_comp_key = split_file_comp[0]
                if file_comp_key == "filename":
                    file_name = split_file_comp[1]
                elif file_comp_key == "url":
                    file_url = split_file_comp[1]
                else:
                    logger.warning("Ignoring --file KEY '%s'", split_file_comp[0])

            if all([file_name, file_url]):
                result.append(DeviceUpdateDataModels.FileImportMetadata(filename=file_name, url=file_url))
            else:
                raise InvalidArgumentValueError("When using --file both filename and url are required.")
        return result

    def assemble_agent_ids(
        self, agent_list_col: List[List[str]]
    ) -> Union[DeviceUpdateDataModels.DeviceUpdateAgentId, None]:
        if not agent_list_col:
            return

        result: List[DeviceUpdateDataModels.DeviceUpdateAgentId] = []
        for agent_list in agent_list_col:
            device_id = None
            module_id = None
            for agent_component in agent_list:
                split_agent_comp = agent_component.split("=", 1)
                agent_comp_key = split_agent_comp[0]
                if agent_comp_key == "deviceId":
                    device_id = split_agent_comp[1]
                elif agent_comp_key == "moduleId":
                    module_id = split_agent_comp[1]
                else:
                    logger.warning("Ignoring --agent-id KEY '%s'", split_agent_comp[0])

            if device_id:
                result.append(DeviceUpdateDataModels.DeviceUpdateAgentId(device_id=device_id, module_id=module_id))
            else:
                raise InvalidArgumentValueError(
                    "When using --agent-id deviceId is required while moduleId is optional."
                )
        return result


# @digimaun - TODO: This is mostly ready to be used generically.
class MicroObjectCache(object):
    def __init__(self, cmd, models):
        from azure.cli.core.commands.client_factory import get_subscription_id
        from azext_iot.sdk.deviceupdate.dataplane._serialization import Deserializer, Serializer

        client_models = {k: v for k, v in models.__dict__.items() if isinstance(v, type)}
        self._serializer = Serializer(client_models)
        self._deserializer = Deserializer(client_models)

        self.cmd = cmd
        self.subscription_id: str = get_subscription_id(self.cmd.cli_ctx)
        if not self.subscription_id:
            raise RuntimeError("Unable to determine subscription Id.")
        self.cloud_name: str = self.cmd.cli_ctx.cloud.name

    def set(
        self, resource_name: str, resource_group: str, resource_type: str, payload: Model, serialization_model: str
    ):
        self._save(
            resource_name=resource_name,
            resource_group=resource_group,
            resource_type=resource_type,
            payload=self._serializer.body(payload, serialization_model),
        )

    def get(self, resource_name: str, resource_group: str, resource_type: str, serialization_model: str) -> Any:
        return self._load(
            resource_name=resource_name,
            resource_group=resource_group,
            resource_type=resource_type,
            serialization_model=serialization_model,
        )

    @classmethod
    def get_config_dir(cls) -> str:
        return os.getenv("AZURE_CONFIG_DIR") or os.path.expanduser(os.path.join("~", ".azure"))

    def _get_file_path(self, resource_name: str, resource_group: str, resource_type: str) -> Tuple[str, str]:
        directory = os.path.join(
            self.get_config_dir(),
            "object_cache",
            self.cloud_name,
            self.subscription_id,
            resource_group,
            resource_type,
        )
        filename = "{}.json".format(resource_name)
        return directory, filename

    def _save(self, resource_name: str, resource_group: str, resource_type: str, payload: Any):
        from knack.util import ensure_dir
        from datetime import datetime

        directory, filename = self._get_file_path(
            resource_name=resource_name, resource_group=resource_group, resource_type=resource_type
        )
        ensure_dir(directory)
        target_path = Path(os.path.join(directory, filename))
        with open(str(target_path), mode="w", encoding="utf8") as f:
            logger.info("Caching '%s' to: '%s'", resource_name, str(target_path))
            cache_obj_dump = json.dumps({"last_saved": str(datetime.now()), "_payload": payload})
            f.write(cache_obj_dump)

    def _load(self, resource_name: str, resource_group: str, resource_type: str, serialization_model: str) -> Any:
        directory, filename = self._get_file_path(
            resource_name=resource_name, resource_group=resource_group, resource_type=resource_type
        )
        target_path = Path(os.path.join(directory, filename))
        if target_path.exists():
            with open(str(target_path), mode="r", encoding="utf8") as f:
                logger.info(
                    "Loading '%s' from cache: %s",
                    resource_name,
                    str(target_path),
                )
                obj_data = json.loads(f.read())
                if "_payload" in obj_data:
                    return self._deserializer.deserialize_data(obj_data["_payload"], serialization_model)

    def remove(self, resource_name: str, resource_group: str, resource_type: str):
        directory, filename = self._get_file_path(
            resource_name=resource_name, resource_group=resource_group, resource_type=resource_type
        )
        try:
            target_path = Path(os.path.join(directory, filename))
            if target_path.exists():
                os.remove(str(target_path))
        except (OSError, IOError):
            pass
