# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.deviceupdate.conftest import (
    ACCOUNT_RG,
    generate_generic_id,
    generate_account_id
)
from typing import Dict


cli = EmbeddedCLI()


@pytest.mark.adu_infrastructure(location="eastus2euap", count=2, delete=False)
def test_account_show_delete(provisioned_accounts: Dict[str, dict]):
    acct_names = list(provisioned_accounts["accounts"].keys())
    for acct_name in acct_names:
        shown_account = cli.invoke(f"iot device-update account show -n {acct_name}").as_json()
        assert shown_account["id"] == provisioned_accounts["accounts"][acct_name]["id"]
        shown_account_rg = cli.invoke(f"iot device-update account show -n {acct_name} -g {ACCOUNT_RG}").as_json()
        assert shown_account_rg["id"] == provisioned_accounts["accounts"][acct_name]["id"]

    cli.invoke(f"iot device-update account delete -n {acct_names[0]} -y --no-wait")
    cli.invoke(f"iot device-update account delete -n {acct_names[1]} -g {ACCOUNT_RG} -y")
    cli.invoke(f"iot device-update account wait -n {acct_names[0]} --deleted")
    for acct_name in acct_names:
        assert not cli.invoke(f"iot device-update account show -n {acct_name} -g {ACCOUNT_RG}").success()


@pytest.mark.adu_infrastructure(location="eastus2euap", public_network_access=False, sku="Free")
def test_account_update(provisioned_accounts: Dict[str, dict]):
    acct_names = list(provisioned_accounts["accounts"].keys())
    target_acct_name = acct_names[0]

    updated_account = cli.invoke(
        f"iot device-update account update -n {target_acct_name} --set tags.env='test' publicNetworkAccess='Enabled'").as_json()
    assert updated_account["provisioningState"] == "Succeeded"
    assert updated_account["publicNetworkAccess"] == "Enabled"
    assert updated_account["tags"]["env"] == "test"

    cli.invoke(f"iot device-update account update -n {target_acct_name} --set tags.env2='staging' --no-wait")
    cli.invoke(f"iot device-update account wait -n {target_acct_name} -g {ACCOUNT_RG} --updated")
    updated_account = cli.invoke(f"iot device-update account show -n {target_acct_name}").as_json()
    assert updated_account["provisioningState"] == "Succeeded"
    assert updated_account["tags"]["env2"] == 'staging'

    # Properties outside of --set should not be changed.
    assert updated_account["publicNetworkAccess"] == "Enabled"
    assert updated_account["tags"]["env"] == "test"


@pytest.mark.adu_infrastructure(location="eastus2euap", tags="a=b c=d", identity="user,system,user")
def test_account_create_identity_mixed(provisioned_accounts: Dict[str, dict]):
    pass


@pytest.mark.adu_infrastructure(location="eastus2euap", identity="system", scope="storage", role="Storage Blob Data Contributor")
def test_account_create_identity_system_assign_scope(provisioned_accounts: Dict[str, dict], provisioned_storage: dict):
    pass


def test_account_create_custom():
    # Test create --no-wait/wait combo.
    target_account_name = generate_account_id()
    # @digimaun - We can uncomment once we have more capacity in none eastus2euap location.
    # group = cli.invoke(f"group show -n {ACCOUNT_RG}").as_json()
    cli.invoke(f"iot device-update account create -n {target_account_name} -g {ACCOUNT_RG} -l eastus2euap --no-wait")
    cli.invoke(f"iot device-update account wait -n {target_account_name} --created")
    account = cli.invoke(f"iot device-update account show -n {target_account_name}").as_json()
    assert account["provisioningState"] == "Succeeded"
    assert account["name"] == target_account_name
    # assert account["location"] == group["location"]
    cli.invoke(f"iot device-update account delete -n {target_account_name} -y --no-wait")


@pytest.mark.adu_infrastructure(location="eastus2euap", count=2)
def test_account_list(provisioned_accounts: Dict[str, dict]):
    provisioned_accounts_len = len(provisioned_accounts["accounts"])

    sub_accounts: list = cli.invoke("iot device-update account list").as_json()
    sub_accounts_len = len(sub_accounts)
    assert sub_accounts_len >= provisioned_accounts_len
    sub_acct_map = {}
    for acct in sub_accounts:
        sub_acct_map[acct["name"]] = True
    for acct_name in provisioned_accounts["accounts"]:
        assert acct_name in sub_acct_map

    group_accounts: list = cli.invoke(f"iot device-update account list -g {ACCOUNT_RG}").as_json()
    group_accounts_len = len(group_accounts)
    assert group_accounts_len >= provisioned_accounts_len and sub_accounts_len >= group_accounts_len
    group_acct_map = {}
    for acct in group_accounts:
        group_acct_map[acct["name"]] = True
    for acct_name in provisioned_accounts["accounts"]:
        assert acct_name in group_acct_map


@pytest.mark.adu_infrastructure(location="eastus2euap")
def test_account_private_links_endpoint_connections(provisioned_accounts: Dict[str, dict]):
    target_account_name = list(provisioned_accounts["accounts"].keys())[0]
    # There is a single command for private link resources
    expected_links = ["DeviceUpdate"]
    link_resources: list = cli.invoke(
        f"iot device-update account private-link-resource list -n {target_account_name}").as_json()
    assert len(link_resources) > 0
    link_map = {}
    for link in link_resources:
        link_map[link["groupId"]] = 1
    for expected_link in expected_links:
        assert expected_link in link_map

    nsg_name = generate_generic_id()
    vnet_name = generate_generic_id()
    subnet_name = generate_generic_id()
    endpoint_name = generate_generic_id()
    conn_name = generate_generic_id()

    try:
        cli.invoke(f"network nsg create -n {nsg_name} -g {ACCOUNT_RG}").as_json()  # Will fail if not succesful
        cli.invoke(f"network vnet create -n {vnet_name} -g {ACCOUNT_RG} --subnet-name {subnet_name} --nsg {nsg_name}").as_json()
        cli.invoke(
            f"network private-endpoint create --connection-name {conn_name} -n {endpoint_name} "
            f"--private-connection-resource-id {provisioned_accounts['accounts'][target_account_name]['id']} "
            f"--group-id {expected_links[0]} -g {ACCOUNT_RG} --vnet-name {vnet_name} --subnet {subnet_name} "
            f"--request-message 'Test {generate_generic_id()}' --manual-request")
        target_desc = generate_generic_id()
        target_status = "Approved"
        set_result = cli.invoke(
            f"iot device-update account private-endpoint-connection set -n {target_account_name} --cn {endpoint_name} "
            f"--status {target_status} --desc '{target_desc}'").as_json()
        assert set_result["name"] == endpoint_name
        assert set_result["privateEndpoint"]
        assert set_result["provisioningState"] == "Succeeded"
        assert set_result["privateLinkServiceConnectionState"]["description"] == target_desc
        assert set_result["privateLinkServiceConnectionState"]["status"] == target_status

        show_result = cli.invoke(
            f"iot device-update account private-endpoint-connection show -n {target_account_name} --cn {endpoint_name}").as_json()
        assert show_result["name"] == endpoint_name

        list_result: list = cli.invoke(
            f"iot device-update account private-endpoint-connection list -n {target_account_name}").as_json()
        assert endpoint_name in [record["name"] for record in list_result]
        assert cli.invoke(
            f"iot device-update account private-endpoint-connection delete -n {target_account_name} --cn {endpoint_name} -y"
        ).success()
        list_result: list = cli.invoke(
            f"iot device-update account private-endpoint-connection list -n {target_account_name}").as_json()
        assert len(list_result) == 0
    finally:
        cli.invoke(f"network private-endpoint delete -n {endpoint_name} -g {ACCOUNT_RG}")
        cli.invoke(f"network vnet delete -n {vnet_name} -g {ACCOUNT_RG}")
        cli.invoke(f"network nsg delete -n {nsg_name} -g {ACCOUNT_RG}")
