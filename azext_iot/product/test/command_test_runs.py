# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep

from azure.cli.core.azclierror import ResourceNotFoundError
from azext_iot.product.providers.aics import AICSProvider
from azext_iot.product.shared import DeviceTestTaskStatus as Status


def show(cmd, test_id, run_id=None, wait=False, poll_interval=3, base_url=None):
    final_statuses = [
        Status.failed.value,
        Status.completed.value,
        Status.cancelled.value,
    ]
    ap = AICSProvider(cmd, base_url)
    if run_id:
        response = ap.show_test_run(test_id=test_id, run_id=run_id)
    else:
        response = ap.show_test_run_latest(test_id=test_id)

    if not response:
        error = "No test run found for test ID '{}'".format(test_id)
        if run_id:
            error = error + " with run ID '{}'".format(run_id)
        raise ResourceNotFoundError(error)
    status = response.status
    run_id = response.id
    while all([wait, status, run_id]) and status not in final_statuses:
        sleep(poll_interval)
        response = ap.show_test_run(test_id=test_id, run_id=run_id)
        status = response.status
    return response


def submit(cmd, test_id, run_id, base_url=None):
    ap = AICSProvider(cmd, base_url)
    return ap.submit_test_run(test_id=test_id, run_id=run_id)
