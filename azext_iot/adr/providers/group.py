# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import GroupType
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.wait import (
    group_membership_ready,
    wait_for_resource,
)


_GROUP_REFRESH_ALREADY_IN_PROGRESS = "GroupRefreshAlreadyInProgress"


class GroupProvider(ADRProvider):
    def create(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
        query_string: str,
        group_type: str = GroupType.registry_device.value,
        location: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,  # pylint: disable=unused-argument
    ):
        location = self._resolve_location(namespace_name, resource_group_name, location)
        properties = {"groupType": group_type, "queryFilter": query_string}
        if display_name is not None:
            properties["displayName"] = display_name
        if description is not None:
            properties["description"] = description

        resource = {"location": location, "properties": properties}
        if tags is not None:
            resource["tags"] = tags

        return self.client.groups.create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            group_name=group_name,
            resource=resource,
        )

    def update(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,  # pylint: disable=unused-argument
    ):
        inner_properties = {}
        if display_name is not None:
            inner_properties["displayName"] = display_name
        if description is not None:
            inner_properties["description"] = description
        if not inner_properties and tags is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --display-name, --description or --tags."
            )

        body = {}
        if inner_properties:
            body["properties"] = inner_properties
        if tags is not None:
            body["tags"] = tags

        return self.client.groups.update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            group_name=group_name,
            properties=body,
        )

    def show(self, group_name: str, namespace_name: str, resource_group_name: str):
        return self.client.groups.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            group_name=group_name,
        )

    def list(self, namespace_name: str, resource_group_name: str):
        return list(
            self.client.groups.list_by_namespace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
        )

    def delete(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        poller = self.client.groups.begin_delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            group_name=group_name,
        )
        return self._wait(
            poller,
            f"Deleting group '{group_name}' from namespace {namespace_name}...",
            **kwargs,
        )

    def refresh(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        no_wait = kwargs.pop("no_wait", False)
        try:
            poller = self.client.groups.begin_refresh_members(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                group_name=group_name,
            )
        except HttpResponseError as error:
            error_code = getattr(getattr(error, "error", None), "code", None)
            if (
                error.status_code != 409
                or error_code != _GROUP_REFRESH_ALREADY_IN_PROGRESS
            ):
                raise
            if no_wait:
                return self.show(group_name, namespace_name, resource_group_name)
            wait_for_resource(
                self.cmd.cli_ctx,
                lambda: self.show(
                    group_name, namespace_name, resource_group_name
                ),
                group_membership_ready,
            )
            return self.show(
                group_name, namespace_name, resource_group_name
            )
        return self._wait(
            poller,
            f"Refreshing members of group '{group_name}' in namespace {namespace_name}...",
            no_wait=no_wait,
            **kwargs,
        )

    def list_members(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
        page_size: Optional[int] = None,
        skip_token: Optional[str] = None,
    ) -> list:
        if page_size is not None and not 1 <= page_size <= 1000:
            raise InvalidArgumentValueError("--page-size must be between 1 and 1000.")

        body = {}
        if page_size is not None:
            body["pageSize"] = page_size
        if skip_token:
            body["skipToken"] = skip_token

        members = []
        seen_tokens = set()
        while True:
            response = self.client.groups.list_members(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                group_name=group_name,
                body=body,
            )
            members.extend((response or {}).get("members") or [])
            next_token = (response or {}).get("skipToken")
            if not next_token:
                return members
            if next_token in seen_tokens:
                raise AzureResponseError(
                    "The group member list returned a repeated skip token."
                )
            seen_tokens.add(next_token)
            body["skipToken"] = next_token

    def count(
        self,
        group_name: str,
        namespace_name: str,
        resource_group_name: str,
    ) -> int:
        response = self.client.groups.count_members(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            group_name=group_name,
        )
        return (response or {}).get("count") or 0
