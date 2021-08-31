# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from azure.cli.core.azclierror import (
    CLIInternalError,
    RequiredArgumentMissingError,
    ClientRequestError,
)
from azext_iot.product.shared import TaskType, DeviceTestTaskStatus as Status
from azext_iot.product.providers.aics import AICSProvider


def create(
    cmd, test_id, task_type=TaskType.QueueTestRun.value, wait=False, poll_interval=3, base_url=None
):
    ap = AICSProvider(cmd, base_url)
    final_statuses = [
        Status.failed.value,
        Status.completed.value,
        Status.cancelled.value,
    ]
    response = ap.create_test_task(
        test_id=test_id, task_type=task_type, wait=wait, poll_interval=poll_interval
    )
    if not response:
        raise ClientRequestError(
            "Failed to create device test task - please ensure a device test exists with Id {}".format(
                test_id
            )
        )
    if isinstance(response, dict):
        raise CLIInternalError(response)

    status = response.status
    task_id = response.id
    while all([wait, status, task_id]) and status not in final_statuses:
        sleep(poll_interval)
        response = ap.show_test_task(test_id=test_id, task_id=task_id)
        status = response.status

    # if a task of 'queueTestRun' is awaited, return the run result
    if all(
        [
            wait,
            status in final_statuses,
            task_type == TaskType.QueueTestRun.value,
            response.result_link,
        ]
    ):
        run_id = response.result_link.split("/")[-1]
        return ap.show_test_run(test_id=test_id, run_id=run_id) if run_id else response

    return response


def delete(cmd, test_id, task_id, base_url=None):
    ap = AICSProvider(cmd, base_url)
    return ap.delete_test_task(test_id=test_id, task_id=task_id)


def show(cmd, test_id, task_id=None, running=False, base_url=None):
    ap = AICSProvider(cmd, base_url)
    if task_id:
        return ap.show_test_task(test_id=test_id, task_id=task_id)
    elif running:
        return ap.show_running_test_task(test_id=test_id)
    raise RequiredArgumentMissingError(
        "Please provide a task-id for individual task details, or use the --running argument to list all running tasks"
    )
