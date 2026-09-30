# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.deviceupdate.conftest import ACCOUNT_RG
from typing import Dict


cli = EmbeddedCLI()

#  Instance creation and manipulation takes an extra long time overhead.
#  Therefore we are aiming to provision instance resources conservatively.


#  Currently only 1 iothub can be created per instance, even though the API definition shows a collection.

@pytest.mark.adu_infrastructure(location="eastus2euap", instance_count=2)
def test_instance_list_show_delete(provisioned_instances: Dict[str, dict]):
    for account_record in provisioned_instances.keys():
        instance_names = list(provisioned_instances[account_record].keys())
        instance_list_result: list = cli.invoke(f"iot du instance list -n {account_record}").as_json()
        assert len(instance_names) == len(instance_list_result)
        for instance in instance_list_result:
            assert instance["name"] in instance_names
            assert cli.invoke(f"iot du instance show -n {account_record} -i {instance['name']}").success()
        instance_list_by_group_result: list = cli.invoke(
            f"iot du instance list -n {account_record} -g {ACCOUNT_RG}"
        ).as_json()
        assert instance_list_result == instance_list_by_group_result
        for instance_name in instance_names:
            assert cli.invoke(
                f"iot du instance delete -n {account_record} -i {instance_name} "
                f" -g {ACCOUNT_RG} -y --no-wait"
            ).success()
        # @digimaun - Evaluate stability.
        # for instance_name in instance_names:
        #     cli.invoke(
        #         f"iot du instance wait -n {account_record} -i {instance_name} --deleted --timeout 900"
        #     )
        #     assert not cli.invoke(
        #         f"iot du instance show -n {account_record} -i {instance_name} -g {ACCOUNT_RG}"
        #     ).success()
