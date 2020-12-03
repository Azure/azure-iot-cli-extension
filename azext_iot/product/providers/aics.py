# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from functools import wraps
from azext_iot.product.providers import AICSServiceProvider
from azext_iot.product.shared import (
    TaskType,
    BadgeType,
)
from msrestazure.azure_exceptions import CloudError
from azext_iot.common.utility import unpack_msrest_error
from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)


def process_cloud_error(func):
    @wraps(func)
    def catch_unpack_clouderror(*args, **kwargs):
        """Process / unpack CloudError exceptions as CLIErrors"""
        try:
            return func(*args, **kwargs)
        except CloudError as e:
            return CLIError(unpack_msrest_error(e))

    return catch_unpack_clouderror


class AICSProvider(AICSServiceProvider):
    def __init__(self, cmd, base_url):
        super(AICSProvider, self).__init__(cmd=cmd, base_url=base_url)
        self.mgmt_sdk = self.get_mgmt_sdk()

    # Requirements
    @process_cloud_error
    def list_requirements(self, badge_type=BadgeType.IotDevice):
        return self.mgmt_sdk.get_device_certification_requirements(
            badge_type=badge_type
        )

    # Test Tasks
    @process_cloud_error
    def create_test_task(
        self, test_id, task_type=TaskType.QueueTestRun, wait=False, poll_interval=3
    ):
        return self.mgmt_sdk.create_device_test_task(
            device_test_id=test_id, task_type=task_type
        )

    @process_cloud_error
    def delete_test_task(self, test_id, task_id):
        return self.mgmt_sdk.cancel_device_test_task(
            task_id=task_id, device_test_id=test_id
        )

    @process_cloud_error
    def show_test_task(self, test_id, task_id=None):
        return self.mgmt_sdk.get_device_test_task(
            task_id=task_id, device_test_id=test_id
        )

    @process_cloud_error
    def show_running_test_task(self, test_id):
        return self.mgmt_sdk.get_running_device_test_tasks(device_test_id=test_id)

    # Tests
    @process_cloud_error
    def show_test(self, test_id):
        return self.mgmt_sdk.get_device_test(
            device_test_id=test_id, raw=True
        ).response.json()

    @process_cloud_error
    def search_test(self, searchOptions):
        return self.mgmt_sdk.search_device_test(body=searchOptions)

    @process_cloud_error
    def update_test(
        self, test_id, test_configuration, provisioning=False
    ):
        return self.mgmt_sdk.update_device_test(
            device_test_id=test_id,
            generate_provisioning_configuration=provisioning,
            body=test_configuration,
            raw=True,
        ).response.json()

    @process_cloud_error
    def create_test(
        self, test_configuration, provisioning=True,
    ):
        return self.mgmt_sdk.create_device_test(
            generate_provisioning_configuration=provisioning, body=test_configuration
        )

    # Test runs
    @process_cloud_error
    def show_test_run(self, test_id, run_id):
        return self.mgmt_sdk.get_test_run(test_run_id=run_id, device_test_id=test_id)

    @process_cloud_error
    def show_test_run_latest(self, test_id):
        return self.mgmt_sdk.get_latest_test_run(device_test_id=test_id)

    @process_cloud_error
    def submit_test_run(self, test_id, run_id):
        return self.mgmt_sdk.submit_test_run(test_run_id=run_id, device_test_id=test_id)

    # Test cases
    @process_cloud_error
    def show_test_cases(self, test_id):
        return self.mgmt_sdk.get_test_cases(device_test_id=test_id)

    @process_cloud_error
    def update_test_cases(self, test_id, patch):
        return self.mgmt_sdk.update_test_cases(
            device_test_id=test_id, certification_badge_test_cases=patch
        )
