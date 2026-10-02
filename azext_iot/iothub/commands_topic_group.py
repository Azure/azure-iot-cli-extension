# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional

from azure.cli.core.azclierror import (
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)

from azext_iot.iothub.providers.topic_group import TopicGroup


def topic_group_create(
    cmd,
    hub_name: str,
    topic_group_id: str,
    topic_templates: List[str],
    resource_group_name: Optional[str] = None,
):
    topic_group_provider = TopicGroup(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return topic_group_provider.create(
        topic_group_id=topic_group_id,
        topic_templates=topic_templates,
    )


def topic_group_show(
    cmd,
    hub_name: str,
    topic_group_id: str,
    resource_group_name: Optional[str] = None,
):
    topic_group_provider = TopicGroup(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return topic_group_provider.show(topic_group_id=topic_group_id)


def topic_group_list(
    cmd,
    hub_name: str,
    resource_group_name: Optional[str] = None,
):
    topic_group_provider = TopicGroup(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return topic_group_provider.list()


def topic_group_update(
    cmd,
    hub_name: str,
    topic_group_id: str,
    topic_templates: List[str],
    resource_group_name: Optional[str] = None,
):
    topic_group_provider = TopicGroup(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return topic_group_provider.update(
        topic_group_id=topic_group_id,
        topic_templates=topic_templates,
    )


def topic_group_delete(
    cmd,
    hub_name: str,
    *,
    topic_group_id: Optional[str] = None,
    delete_all: bool = False,
    yes: bool = False,
    resource_group_name: Optional[str] = None,
):
    if topic_group_id is not None and delete_all:
        raise MutuallyExclusiveArgumentError(
            "Use either --topic-group-id or --all, not both."
        )
    if topic_group_id is None and not delete_all:
        raise RequiredArgumentMissingError(
            "Specify either --topic-group-id or --all."
        )

    topic_group_provider = TopicGroup(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return topic_group_provider.delete(
        topic_group_id=topic_group_id,
        delete_all=delete_all,
        yes=yes,
    )
