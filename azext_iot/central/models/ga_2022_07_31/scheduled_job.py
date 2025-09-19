# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class ScheduledJob:
    def __init__(self, job: dict):
        self.display_name = job.get("displayName")
        self.id = job.get("id")
        self.group = job.get("group")
        self.status = job.get("status")
        self.data = job.get("data")
        self.description = job.get("description")
        self.batch = job.get("batch")
        self.cancellation_threshold = job.get("cancellationThreshold")
        self.schedule = job.get("schedule")
