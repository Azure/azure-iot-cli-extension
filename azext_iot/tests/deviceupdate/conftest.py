# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings
from azext_iot.tests.generators import generate_generic_id
from typing import List, Tuple, Optional
from knack.log import get_logger

logger = get_logger(__name__)


cli = EmbeddedCLI()


required_test_env_vars = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=required_test_env_vars)

ACCOUNT_RG = settings.env.azext_iot_testrg
VALID_IDENTITY_MAP = {"system": 1, "user": 1}


def generate_account_id() -> str:
    return f"test-adu-{generate_generic_id()}"[:23]


def generate_instance_id() -> str:
    return f"test-instance-{generate_generic_id()}"[:36]


def generate_linked_hub_id() -> str:
    return f"test-adu-dep-{generate_generic_id()}"[:40]


def generate_linked_storage_id() -> str:
    return f"testadudep{generate_generic_id()}"[:24]


def generate_useridentity_id() -> str:
    return f"test-adu-dep-{generate_generic_id()}"


def tags_to_dict(tags: str) -> dict:
    result = {}
    split_tags = tags.split()
    for tag in split_tags:
        kvp = tag.split("=")
        result[kvp[0]] = kvp[1]
    return result


@pytest.fixture
def provisioned_accounts(request, provisioned_storage: dict) -> dict:
    result_accounts = {"accounts": {}}
    if provisioned_storage:
        result_accounts["storage"] = provisioned_storage

    acct_marker = request.node.get_closest_marker("adu_infrastructure")
    desired_location = None
    desired_tags = None
    desired_count = None
    desired_delete = True
    desired_public_network_access = None
    desired_identity = None
    desired_sku = None

    if acct_marker:
        desired_location = acct_marker.kwargs.get("location")
        desired_tags = acct_marker.kwargs.get("tags")
        desired_count = acct_marker.kwargs.get("count", 1)
        desired_delete = acct_marker.kwargs.get("delete", True)
        desired_public_network_access = acct_marker.kwargs.get(
            "public_network_access"
        )
        desired_identity = acct_marker.kwargs.get("identity")
        desired_role = acct_marker.kwargs.get("role")
        desired_sku = acct_marker.kwargs.get("sku")

    base_create_command = f"iot device-update account create -g {ACCOUNT_RG}"

    if desired_location:
        base_create_command = base_create_command + f" -l {desired_location}"
    if desired_tags:
        base_create_command = base_create_command + f" --tags {desired_tags}"
    if desired_public_network_access:
        base_create_command = base_create_command + f" --pna {desired_public_network_access}"
    if desired_sku:
        base_create_command = base_create_command + f" --sku {desired_sku}"

    base_create_command, user_identities, system_identity = _process_identity(
        base_create_command, desired_identity
    )

    desired_scope = None
    if system_identity and provisioned_storage:
        desired_scope = provisioned_storage['id']
        base_create_command = base_create_command + f" --scopes {desired_scope}"
        if desired_role:
            base_create_command = base_create_command + f" --role '{desired_role}'"
        else:
            desired_role = "Contributor"  # default role

    count = desired_count or 1
    for _ in range(count):
        target_name = generate_account_id()
        create_command = f"{base_create_command} -n {target_name}"
        create_result = cli.invoke(create_command)
        if not create_result.success():
            raise RuntimeError(f"Failed to provision device update account {target_name}.")
        account = create_result.as_json()
        result_accounts["accounts"][target_name] = account
        assert account["name"] == target_name
        assert account["provisioningState"] == "Succeeded"
        assert account["systemData"]
        assert account["type"] == "microsoft.deviceupdate/accounts"
        assert account["locations"]
        if desired_sku:
            assert account["sku"] == desired_sku
        else:
            assert account["sku"] == "Standard"
        if desired_location:
            assert account["location"] == desired_location
        else:
            group = cli.invoke(f"group show -n {ACCOUNT_RG}").as_json()
            assert account["location"] == group["location"]
        if desired_tags:
            assert account["tags"] == tags_to_dict(desired_tags)
        else:
            assert account["tags"] is None
        if desired_public_network_access:
            assert account["publicNetworkAccess"] == desired_public_network_access
        else:
            assert account["publicNetworkAccess"] == "Enabled"
        if user_identities:
            for user_id in user_identities:
                assert user_id["id"] in account["identity"]["userAssignedIdentities"]
            assert "UserAssigned" in account["identity"]["type"]
        if system_identity:
            assert account["identity"]["principalId"]
            assert account["identity"]["tenantId"]
            assert "SystemAssigned" in account["identity"]["type"]
            if desired_scope:
                assignments: list = cli.invoke(f"role assignment list --scope {desired_scope}").as_json()
                principal_map = {}
                for assignment in assignments:
                    principal_map[assignment["principalId"]] = assignment["roleDefinitionName"]
                assert account["identity"]["principalId"] in principal_map
                assert principal_map[account["identity"]["principalId"]] == desired_role
        if not any([user_identities, system_identity]):
            assert account["identity"] is None

    yield result_accounts

    if not desired_delete:
        return

    account_delete_failures = []
    for account_name in result_accounts["accounts"]:
        delete_command = f"iot device-update account delete -g {ACCOUNT_RG} -n {account_name} --no-wait -y"
        acct_delete_result = cli.invoke(delete_command)
        if not acct_delete_result.success():
            account_delete_failures.append(result_accounts["accounts"][account_name]["id"])

    user_delete_failures = []
    for user_identity in user_identities:
        delete_command = f"identity delete -g {ACCOUNT_RG} -n {user_identity['name']}"
        identity_delete_result = cli.invoke(delete_command)
        if not identity_delete_result.success():
            user_delete_failures.append(user_identity["id"])

    if any([account_delete_failures, user_delete_failures]):
        clean_up_error = (
            f"Failed to delete the following resources (by Id):\n "
            f"{' '.join(account_delete_failures)} {' '.join(user_delete_failures)}"
        )
        logger.error(clean_up_error)


def _process_identity(
    base_command: str, identity_request: str
) -> Tuple[str, List[dict], bool]:
    user_id_result: List[dict] = []
    system_processed = False
    if not identity_request:
        return base_command, user_id_result, system_processed

    split_identities = [i.strip() for i in identity_request.split(",")]
    for id in split_identities:
        if id in split_identities:
            if id == "user":
                user_id_result.append(
                    cli.invoke(
                        f"identity create -n {generate_useridentity_id()} -g {ACCOUNT_RG}"
                    ).as_json()
                )
            elif id == "system" and not system_processed:
                system_processed = True

    base_command = (
        f"{base_command} --assign-identity {'[system]' if system_processed else ''} "
        f"{' '.join([identity['id'] for identity in user_id_result])}"
    )

    return base_command, user_id_result, system_processed


@pytest.fixture
def provisioned_instances(request, provisioned_accounts: dict, provisioned_iothubs: dict) -> dict:
    acct_marker = request.node.get_closest_marker("adu_infrastructure")
    desired_instance_diagnostics = None
    desired_instance_diagnostics_user_storage = None
    result_map = {}

    base_create_command = "iot device-update instance create "

    if acct_marker:
        desired_instance_diagnostics = acct_marker.kwargs.get("instance_diagnostics", False)
        desired_instance_diagnostics_user_storage = acct_marker.kwargs.get("instance_diagnostics_user_storage")

    if desired_instance_diagnostics:
        base_create_command = base_create_command + " --enable-diagnostics"
        if desired_instance_diagnostics_user_storage:
            target_storage = provisioned_accounts.get("storage")
            if target_storage:
                base_create_command = base_create_command + f" --diagnostics-storage-id {target_storage['id']}"

    for acct_name in provisioned_accounts["accounts"]:
        for hub_id in provisioned_iothubs:
            target_instance_name = generate_instance_id()
            create_command = f"{base_create_command} -n {acct_name} -i {target_instance_name} --iothub-ids {hub_id}"
            instance_create_result = cli.invoke(create_command)
            if not instance_create_result.success():
                raise RuntimeError(f"Failed to provision instance resource {target_instance_name}.")
            target_instance = instance_create_result.as_json()
            assert target_instance["name"] == target_instance_name
            assert target_instance["provisioningState"] == "Succeeded"
            instance_hub_ids = [hub['resourceId'] for hub in target_instance["iotHubs"]]
            assert hub_id in instance_hub_ids
            if desired_instance_diagnostics:
                assert target_instance["enableDiagnostics"]
            else:
                assert target_instance["enableDiagnostics"] is None
            if desired_instance_diagnostics_user_storage:
                assert target_instance["diagnosticStorageProperties"]["authenticationType"] == "KeyBased"
                assert target_instance["diagnosticStorageProperties"]["resourceId"] == target_storage["id"]
            else:
                assert target_instance["diagnosticStorageProperties"] is None
            if acct_name in result_map:
                result_map[acct_name][target_instance_name] = target_instance
            else:
                result_map[acct_name] = {target_instance_name: target_instance}
    yield result_map
    # Non-explicit clean-up of instance done through account deletion.


@pytest.fixture
def provisioned_iothubs(request) -> Optional[dict]:
    acct_marker = request.node.get_closest_marker("adu_infrastructure")
    if acct_marker:
        desired_instance_count = acct_marker.kwargs.get("instance_count")
        if desired_instance_count:
            hub_id_map = {}
            hub_names = []
            for _ in range(desired_instance_count):
                target_name = generate_linked_hub_id()
                create_result = cli.invoke(f"iot hub create -g {ACCOUNT_RG} -n {target_name}")
                if not create_result.success():
                    raise RuntimeError(f"Failed to provision iot hub resource {target_name}.")
                create_result = create_result.as_json()
                hub_id_map[create_result["id"]] = create_result
                hub_names.append(target_name)
            yield hub_id_map
            for target_name in hub_names:
                delete_result = cli.invoke(f"iot hub delete -g {ACCOUNT_RG} -n {target_name}")
                if not delete_result.success():
                    logger.error(f"Failed to delete iot hub resource {target_name}.")
        else:
            yield


@pytest.fixture
def provisioned_storage(request) -> Optional[dict]:
    acct_marker = request.node.get_closest_marker("adu_infrastructure")
    if acct_marker:
        desired_scope = acct_marker.kwargs.get("scope")
        desired_instance_diagnostics_user_storage = acct_marker.kwargs.get("instance_diagnostics_user_storage", False)
        if desired_scope == "storage" or desired_instance_diagnostics_user_storage:
            target_name = generate_linked_storage_id()
            create_result = cli.invoke(f"storage account create -g {ACCOUNT_RG} -n {target_name}")
            if not create_result.success():
                raise RuntimeError(f"Failed to provision storage account resource {target_name}.")
            yield create_result.as_json()
            delete_result = cli.invoke(f"storage account delete -g {ACCOUNT_RG} -n {target_name} -y")
            if not delete_result.success():
                logger.error(f"Failed to delete storage account resource {target_name}.")
        else:
            yield
