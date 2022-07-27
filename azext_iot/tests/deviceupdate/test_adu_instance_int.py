# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.deviceupdate.conftest import ACCOUNT_RG
from azext_iot.tests.generators import generate_generic_id
from typing import Dict


cli = EmbeddedCLI()

#  Instance creation and manipulation takes an extra long time overhead.
#  Therefore we are aiming to provision instance resources conservatively.


#  Currently only 1 iothub can be created per instance, even though the API definition shows a collection.

@pytest.mark.adu_infrastructure(location="eastus2euap", instance_count=2)
def test_instance_list_show_delete(provisioned_instances: Dict[str, dict]):
    for account_record in provisioned_instances.keys():
        instance_names = list(provisioned_instances[account_record].keys())
        instance_list_result: list = cli.invoke(f"iot device-update instance list -n {account_record}").as_json()
        assert len(instance_names) == len(instance_list_result)
        for instance in instance_list_result:
            assert instance["name"] in instance_names
            assert cli.invoke(f"iot device-update instance show -n {account_record} -i {instance['name']}").success()
        instance_list_by_group_result: list = cli.invoke(
            f"iot device-update instance list -n {account_record} -g {ACCOUNT_RG}"
        ).as_json()
        assert instance_list_result == instance_list_by_group_result
        for instance_name in instance_names:
            assert cli.invoke(
                f"iot device-update instance delete -n {account_record} -i {instance_name} "
                f" -g {ACCOUNT_RG} -y --no-wait"
            ).success()
        # @digimaun - Evaluate stability.
        # for instance_name in instance_names:
        #     cli.invoke(
        #         f"iot device-update instance wait -n {account_record} -i {instance_name} --deleted --timeout 900"
        #     )
        #     assert not cli.invoke(
        #         f"iot device-update instance show -n {account_record} -i {instance_name} -g {ACCOUNT_RG}"
        #     ).success()


@pytest.mark.adu_infrastructure(
    location="eastus2euap", instance_count=1, instance_diagnostics=True, instance_diagnostics_user_storage=True
)
def test_instance_custom_storage_update_show_delete(provisioned_instances: Dict[str, dict]):
    account_name = list(provisioned_instances.keys())[0]
    instance_name = list(provisioned_instances[account_name].keys())[0]
    random_tag1 = generate_generic_id()
    random_tag2 = generate_generic_id()
    # Fetch backing storage account
    storage_resource_id = cli.invoke(f"iot device-update instance show -n {account_name} -i {instance_name}").as_json()[
        "diagnosticStorageProperties"
    ]["resourceId"]
    # Set tag, disable diagnostics and remove existing diagnostic storage account.
    updated_instance: dict = cli.invoke(
        f"iot device-update instance update -n {account_name} -i {instance_name} --set tags.env1={random_tag1} "
        "diagnosticStorageProperties=null enableDiagnostics=false"
    ).as_json()
    assert updated_instance["provisioningState"] == "Succeeded"
    assert updated_instance["tags"]["env1"] == random_tag1
    assert updated_instance["enableDiagnostics"] is False
    assert updated_instance["diagnosticStorageProperties"] is None
    # Set another tag, enable diagnostics and re-add existing storage account.
    cli.invoke(
        f"iot device-update instance update -n {account_name} -i {instance_name} "
        f"-g {ACCOUNT_RG} --set tags.env2={random_tag2} enableDiagnostics=true "
        f"diagnosticStorageProperties.resourceId={storage_resource_id} --no-wait"
    )
    cli.invoke(f"iot device-update instance wait -n {account_name} -i {instance_name} --updated")
    shown_instance: dict = cli.invoke(f"iot device-update instance show -n {account_name} -i {instance_name}").as_json()
    assert shown_instance["provisioningState"] == "Succeeded"
    assert shown_instance["tags"]["env1"] == random_tag1
    assert shown_instance["tags"]["env2"] == random_tag2
    assert shown_instance["enableDiagnostics"] is True
    assert shown_instance["diagnosticStorageProperties"]["resourceId"] == storage_resource_id
    assert shown_instance["id"] == provisioned_instances[account_name][instance_name]["id"]
    assert shown_instance["accountName"] == account_name
    # Delete synchronously
    assert cli.invoke(f"iot device-update instance delete -n {account_name} -i {instance_name} -y").success()
    assert not cli.invoke(
        f"iot device-update instance show -n {account_name} -i {instance_name} -g {ACCOUNT_RG}"
    ).success()
