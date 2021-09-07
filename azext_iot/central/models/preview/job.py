# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class Job:
    def __init__(self, job: dict):
        self.display_name = job.get("displayName")
        self.id = job.get("id")
        self.group = job.get("group")
        self.status = job.get("status")
        self.data = job.get("data")
        self.description = job.get("description")
        self.batch = job.get("batch")
        self.cancellation_threshold = job.get("cancellationThreshold")
