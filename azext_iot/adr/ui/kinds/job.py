# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Jobs (what to roll out, and to whom) and their runs (when it executed)."""

from azext_iot.adr.ui.core.spec import ChildRef, Column, Guide, ResourceSpec
from azext_iot.adr.ui.kinds._common import (
    RUN_STATUS_STYLES,
    age_column,
    name_column,
    name_of,
    prop,
    short_id,
    state_column,
    value_style,
)


def _update_identity(payload) -> str:
    """Provider/name/version rendered as one readable token."""
    parts = [
        str(prop("updateId", key, default="")(payload) or prop(key, default="")(payload))
        for key in ("provider", "name", "version")
    ]
    parts = [part for part in parts if part]
    return "/".join(parts)


def build(session) -> ResourceSpec:
    def list_jobs(scope):
        return session.list_from(
            "job",
            "list",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="job",
        title="Job",
        title_plural="Jobs",
        aliases=("jb",),
        parent="namespace",
        guide=Guide(
            about="Jobs defined in this namespace. A job is the definition; each execution of it is a run.",
            runs="az iot adr ns job list --ns <namespace> -g <resource-group>  ·  read-only",
            note="Drill into a job to see its runs, which is where success and failure actually appear.",
        ),
        row_id=name_of,
        list=list_jobs,
        columns=(
            name_column(width=24),
            Column("type", "TYPE", prop("jobType"), width=18),
            Column(
                "target",
                "TARGET GROUP",
                lambda p: short_id(prop("targetGroupId", default="")(p))
                or prop("targetGroupName", default="")(p),
                width=22,
            ),
            Column("update", "UPDATE", _update_identity, width=28),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name"),
        scope_key="job_name",
        children=(ChildRef("run", "Runs", "u"),),
    )


def build_run(session) -> ResourceSpec:
    def list_runs(scope):
        return session.list_from(
            "job_run",
            "list",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
            job_name=scope.get("job_name"),
        )

    return ResourceSpec(
        kind="run",
        title="Job run",
        title_plural="Job runs",
        aliases=("rn",),
        parent="job",
        guide=Guide(
            about="Executions of this job, newest first, with per-device progress.",
            runs="az iot adr ns job run list --job <job> --ns <namespace>  ·  read-only",
            note=(
                "A run in progress updates on the next refresh; long jobs may take a while to reach a terminal state."
            ),
        ),
        row_id=name_of,
        list=list_runs,
        # Runs change while you watch them, so they poll faster than their parent job.
        refresh_interval=5,
        columns=(
            name_column("RUN", width=26),
            Column(
                "status",
                "STATUS",
                prop("status"),
                width=12,
                style=value_style(prop("status"), RUN_STATUS_STYLES),
            ),
            Column("scheduled", "SCHEDULED", prop("scheduledTime"), width=22),
            Column("succeeded", "OK", prop("succeededCount"), width=6),
            Column("failed", "FAILED", prop("failedCount"), width=7),
            Column("total", "TOTAL", prop("totalCount"), width=7, wide=True),
            state_column(),
        ),
        sort=("scheduled", True),
        requires=("namespace_name", "resource_group_name"),
        scope_key="run_name",
    )
