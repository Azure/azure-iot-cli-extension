# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
import time
from typing import Any, Dict, Optional

from azure.cli.core.azclierror import (
    CLIInternalError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.cli.core.commands.client_factory import (
    get_mgmt_service_client,
    get_subscription_id,
    get_subscription_service_client,
)
from azure.core.exceptions import HttpResponseError
from azure.mgmt.resource import ResourceManagementClient
from msrestazure.tools import parse_resource_id

from azext_iot._factory import (
    iot_hub_service_factory,
    iot_service_provisioning_factory,
)
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.update_instance import UpdateInstanceProvider
from azext_iot.adr.rbac import LinkRbacManager
from azext_iot.adr.workflows.models import EndpointSpec
from azext_iot.common.embedded_cli import EmbeddedCLI


LINK_POLL_INTERVAL = 10
LINK_POLL_ATTEMPTS = 240


def as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    serializer = getattr(value, "as_dict", None)
    if callable(serializer):
        return serializer()
    serializer = getattr(value, "serialize", None)
    if callable(serializer):
        return serializer()
    try:
        return dict(value)
    except (TypeError, ValueError):
        return dict(vars(value))


def value_of(mapping: Dict[str, Any], *names: str):
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def is_not_found(error: Exception) -> bool:
    return isinstance(error, ResourceNotFoundError) or (
        isinstance(error, HttpResponseError) and error.status_code == 404
    )


class WorkflowServices:
    def __init__(self, cmd, sleep=time.sleep):
        self.cmd = cmd
        self.namespace = NamespaceProvider(cmd)
        self.links = LinkProvider(cmd)
        self.update_instances = UpdateInstanceProvider(cmd)
        self.subscriptions, _ = get_subscription_service_client(cmd.cli_ctx)
        self.resources = get_mgmt_service_client(
            cmd.cli_ctx, ResourceManagementClient
        )
        self.cli = EmbeddedCLI(cli_ctx=cmd.cli_ctx, capture_stderr=True)
        self.link_rbac = LinkRbacManager(cmd.cli_ctx)
        self.sleep = sleep

    @property
    def subscription_id(self) -> str:
        return get_subscription_id(self.cmd.cli_ctx)

    def show_subscription(self, subscription_id: str):
        try:
            return as_dict(
                self.subscriptions.subscriptions.get(subscription_id)
            )
        except Exception as error:  # noqa: BLE001 - normalize only not-found
            if is_not_found(error):
                return None
            raise

    def account_context(self):
        account = self.cli.invoke("account show").as_json()
        user = as_dict(account.get("user"))
        return {
            "subscriptionId": value_of(account, "id") or self.subscription_id,
            "subscriptionName": value_of(account, "name"),
            "tenantId": value_of(account, "tenantId", "tenant_id"),
            "userName": value_of(user, "name"),
            "userType": value_of(user, "type"),
        }

    def list_subscriptions(self):
        return [
            {
                "id": value_of(item, "subscriptionId", "subscription_id"),
                "name": value_of(item, "displayName", "display_name"),
                "state": value_of(item, "state"),
                "tenantId": value_of(item, "tenantId", "tenant_id"),
            }
            for item in map(
                as_dict, self.subscriptions.subscriptions.list()
            )
        ]

    def resolve_subscription(self, value: str):
        account = self.cli.invoke(
            "account show", subscription=value
        ).as_json()
        return {
            "id": value_of(account, "id"),
            "name": value_of(account, "name"),
            "state": value_of(account, "state"),
            "tenantId": value_of(account, "tenantId", "tenant_id"),
        }

    def list_resource_groups(self):
        return [
            {
                "id": value_of(item, "id"),
                "name": value_of(item, "name"),
                "location": value_of(item, "location"),
                "tags": value_of(item, "tags") or {},
            }
            for item in map(
                as_dict, self.resources.resource_groups.list()
            )
        ]

    def show_resource_group(self, resource_group_name: str):
        try:
            return as_dict(
                self.resources.resource_groups.get(resource_group_name)
            )
        except Exception as error:  # noqa: BLE001 - normalize only not-found
            if is_not_found(error):
                return None
            raise

    def show_namespace(self, namespace_name: str, resource_group_name: str):
        try:
            return as_dict(
                self.namespace.show(namespace_name, resource_group_name)
            )
        except Exception as error:  # noqa: BLE001 - normalize only not-found
            if is_not_found(error):
                return None
            raise

    def list_namespaces(self, resource_group_name: str):
        return [
            {
                "id": value_of(item, "id"),
                "name": value_of(item, "name"),
                "location": value_of(item, "location"),
                "provisioningState": value_of(
                    as_dict(item.get("properties")),
                    "provisioningState",
                    "provisioning_state",
                ),
                "createdBy": value_of(
                    as_dict(
                        value_of(item, "systemData", "system_data")
                    ),
                    "createdBy",
                    "created_by",
                ),
            }
            for item in map(
                as_dict, self.namespace.list(resource_group_name)
            )
        ]

    def create_namespace(
        self,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str],
        outbound_identity_type: Optional[str],
        outbound_user_assigned_identity: Optional[str],
        tags: Optional[Dict[str, str]] = None,
    ):
        return as_dict(
            self.namespace.create(
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
                location=location,
                tags=tags,
                outbound_mi_system_assigned=outbound_identity_type == "SystemAssigned",
                outbound_mi_user_assigned=outbound_user_assigned_identity,
            )
        )

    def configure_outbound_identity(
        self,
        namespace_name: str,
        resource_group_name: str,
        identity_type: str,
        user_assigned_identity: Optional[str],
    ):
        return as_dict(
            self.namespace.update(
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
                outbound_mi_system_assigned=identity_type == "SystemAssigned",
                outbound_mi_user_assigned=user_assigned_identity,
            )
        )

    def resolve_resource(self, endpoint: EndpointSpec) -> Dict[str, Any]:
        parsed = parse_resource_id(endpoint.resource_id)
        self._require_active_subscription(parsed, endpoint.kind)
        namespace = str(parsed.get("namespace") or "").casefold()
        resource_type = str(parsed.get("type") or "").casefold()
        resource_group = parsed.get("resource_group")
        name = parsed.get("name")
        if not resource_group or not name:
            raise InvalidArgumentValueError(
                f"Invalid {endpoint.kind} resource ID: {endpoint.resource_id}."
            )
        if endpoint.kind == "hub":
            if namespace != "microsoft.devices" or resource_type != "iothubs":
                raise InvalidArgumentValueError("--hub must reference an IoT Hub.")
            resource = iot_hub_service_factory(
                self.cmd.cli_ctx
            ).iot_hub_resource.get(
                resource_group_name=resource_group, resource_name=name
            )
        elif endpoint.kind == "dps":
            if (
                namespace != "microsoft.devices"
                or resource_type != "provisioningservices"
            ):
                raise InvalidArgumentValueError("--dps must reference a DPS resource.")
            resource = iot_service_provisioning_factory(
                self.cmd.cli_ctx
            ).iot_dps_resource.get(
                resource_group_name=resource_group,
                provisioning_service_name=name,
            )
        elif endpoint.kind == "software-updates":
            if (
                namespace != "microsoft.deviceupdate"
                or resource_type != "updateinstances"
            ):
                raise InvalidArgumentValueError(
                    "--software-updates must reference an Update Instance."
                )
            resource = self.update_instances.show(name, resource_group)
        else:
            raise InvalidArgumentValueError(
                f"Unsupported endpoint kind '{endpoint.kind}'."
            )
        result = as_dict(resource)
        result.setdefault("id", endpoint.resource_id)
        return result

    def list_link_targets(self, kind: str, resource_group_name: str):
        if kind == "hub":
            resources = iot_hub_service_factory(
                self.cmd.cli_ctx
            ).iot_hub_resource.list_by_resource_group(
                resource_group_name=resource_group_name
            )
        elif kind == "dps":
            resources = iot_service_provisioning_factory(
                self.cmd.cli_ctx
            ).iot_dps_resource.list_by_resource_group(
                resource_group_name=resource_group_name
            )
        elif kind == "software-updates":
            resources = self.update_instances.list(resource_group_name)
        else:
            raise InvalidArgumentValueError(
                f"Unsupported endpoint kind '{kind}'."
            )
        return [
            self._resource_choice(kind, as_dict(resource))
            for resource in resources
        ]

    @staticmethod
    def _resource_choice(kind: str, resource: Dict[str, Any]):
        properties = as_dict(resource.get("properties"))
        sku = as_dict(resource.get("sku"))
        identity = as_dict(resource.get("identity"))
        system_data = as_dict(
            value_of(resource, "systemData", "system_data")
        )
        choice = {
            "kind": kind,
            "id": value_of(resource, "id"),
            "name": value_of(resource, "name"),
            "location": value_of(resource, "location"),
            "provisioningState": value_of(
                properties, "provisioningState", "provisioning_state"
            ),
            "sku": value_of(sku, "name"),
            "identityType": value_of(identity, "type"),
            "principalId": value_of(
                identity, "principalId", "principal_id"
            ),
            "createdBy": value_of(
                system_data, "createdBy", "created_by"
            ),
            "createdAt": value_of(
                system_data, "createdAt", "created_at"
            ),
        }
        if kind == "dps":
            choice["linkedHubs"] = [
                value_of(as_dict(hub), "name", "hostName", "host_name")
                for hub in properties.get("iotHubs", [])
            ]
            choice["allocationPolicy"] = value_of(
                properties, "allocationPolicy", "allocation_policy"
            )
        if kind == "software-updates":
            choice["accountName"] = value_of(
                properties, "accountName", "account_name"
            )
        return choice

    def resolve_uami(self, resource_id: str) -> Dict[str, Any]:
        self._require_active_subscription(
            parse_resource_id(resource_id), "user-assigned identity"
        )
        result = self.cli.invoke(
            f"identity show --ids {shlex.quote(resource_id)}"
        ).as_json()
        if not isinstance(result, dict):
            raise CLIInternalError(
                f"Unable to resolve user-assigned identity '{resource_id}'."
            )
        return result

    def principal_for_identity(
        self,
        identity_type: str,
        user_assigned_identity: Optional[str],
        resource: Dict[str, Any],
        require_attached: bool = True,
    ) -> str:
        if identity_type.casefold() in {"userassigned", "user-assigned"}:
            if require_attached:
                assigned = as_dict(
                    as_dict(resource.get("identity")).get(
                        "userAssignedIdentities"
                    )
                )
                normalized = {
                    resource_id.rstrip("/").casefold()
                    for resource_id in assigned
                }
                if (
                    not user_assigned_identity
                    or user_assigned_identity.rstrip("/").casefold()
                    not in normalized
                ):
                    raise InvalidArgumentValueError(
                        "The selected user-assigned identity is not attached "
                        "to the target resource."
                    )
            identity = self.resolve_uami(user_assigned_identity)
        else:
            identity = as_dict(resource.get("identity"))
        principal_id = value_of(identity, "principalId", "principal_id")
        if not principal_id:
            raise InvalidArgumentValueError(
                "The selected managed identity does not have a principal ID."
            )
        return principal_id

    def namespace_outbound_principal(self, namespace: Dict[str, Any]) -> str:
        properties = as_dict(namespace.get("properties"))
        outbound = as_dict(properties.get("outboundIdentity"))
        identity_type = value_of(outbound, "type")
        if identity_type == "UserAssigned":
            uami = value_of(
                outbound, "userAssignedIdentity", "user_assigned_identity"
            )
            return self.principal_for_identity(
                "UserAssigned", uami, namespace
            )
        if identity_type == "SystemAssigned":
            return self.principal_for_identity(
                "SystemAssigned", None, namespace
            )
        raise InvalidArgumentValueError(
            "The namespace does not have a configured outbound identity."
        )

    def create_update_instance(
        self, endpoint: EndpointSpec, location: Optional[str]
    ):
        parsed = parse_resource_id(endpoint.resource_id)
        self._require_active_subscription(parsed, endpoint.kind)
        name = parsed.get("name")
        resource_group = parsed.get("resource_group")
        availability = as_dict(self.update_instances.check_name(name))
        if value_of(availability, "nameAvailable", "name_available") is False:
            raise InvalidArgumentValueError(
                f"Update Instance name '{name}' is not available."
            )
        return as_dict(
            self.update_instances.create(
                update_instance_name=name,
                resource_group_name=resource_group,
                location=location,
                mi_system_assigned=endpoint.identity_type == "system-assigned",
                mi_user_assigned=(
                    [endpoint.user_assigned_identity]
                    if endpoint.user_assigned_identity
                    else None
                ),
            )
        )

    def add_dps(self, request, endpoint: EndpointSpec):
        return self.links.dps_add(
            endpoint_name=endpoint.endpoint_name,
            namespace_name=request.namespace_name,
            resource_group_name=request.resource_group_name,
            dps_resource_id=endpoint.resource_id,
            mi_system_assigned=endpoint.identity_type == "system-assigned",
            mi_user_assigned=endpoint.user_assigned_identity,
        )

    def add_hub(self, request, endpoint: EndpointSpec):
        return self.links.hub_add(
            endpoint_name=endpoint.endpoint_name,
            namespace_name=request.namespace_name,
            resource_group_name=request.resource_group_name,
            hub_resource_id=endpoint.resource_id,
            mi_system_assigned=endpoint.identity_type == "system-assigned",
            mi_user_assigned=endpoint.user_assigned_identity,
            availability=endpoint.availability,
            allocation_weight=endpoint.allocation_weight,
        )

    def add_dps_and_hub(
        self, request, dps: EndpointSpec, hub: EndpointSpec
    ):
        return self.links.link_add(
            namespace_name=request.namespace_name,
            resource_group_name=request.resource_group_name,
            hub_endpoint_name=hub.endpoint_name,
            hub_resource_id=hub.resource_id,
            dps_endpoint_name=dps.endpoint_name,
            dps_resource_id=dps.resource_id,
            hub_mi_system_assigned=hub.identity_type == "system-assigned",
            hub_mi_user_assigned=hub.user_assigned_identity,
            dps_mi_system_assigned=dps.identity_type == "system-assigned",
            dps_mi_user_assigned=dps.user_assigned_identity,
            hub_availability=hub.availability,
            hub_allocation_weight=hub.allocation_weight,
        )

    def add_su(self, request, endpoint: EndpointSpec):
        return self.links.su_add(
            endpoint_name=endpoint.endpoint_name,
            namespace_name=request.namespace_name,
            resource_group_name=request.resource_group_name,
            su_resource_id=endpoint.resource_id,
            mi_system_assigned=endpoint.identity_type == "system-assigned",
            mi_user_assigned=endpoint.user_assigned_identity,
        )

    def ensure_link_access(self, request, endpoint: EndpointSpec):
        return self.links.ensure_link_access(
            link_type=(
                "su"
                if endpoint.kind == "software-updates"
                else endpoint.kind
            ),
            namespace_name=request.namespace_name,
            resource_group_name=request.resource_group_name,
            target_resource_id=endpoint.resource_id,
            mi_system_assigned=endpoint.identity_type == "system-assigned",
            mi_user_assigned=endpoint.user_assigned_identity,
        )

    def wait_for_link(
        self,
        namespace_name: str,
        resource_group_name: str,
        section: str,
        endpoint_name: str,
    ) -> Dict[str, Any]:
        last = {}
        for _ in range(LINK_POLL_ATTEMPTS):
            namespace = self.show_namespace(namespace_name, resource_group_name)
            properties = as_dict((namespace or {}).get("properties"))
            endpoints = as_dict(as_dict(properties.get(section)).get("endpoints"))
            last = as_dict(endpoints.get(endpoint_name))
            state = value_of(last, "linkingState", "linking_state")
            if state == "Succeeded":
                return last
            if state in {"Failed", "Canceled"}:
                error = as_dict(value_of(last, "linkingError", "linking_error"))
                message = value_of(error, "message") or "No service error was returned."
                raise CLIInternalError(
                    f"Endpoint '{endpoint_name}' failed to link: {message}"
                )
            self.sleep(LINK_POLL_INTERVAL)
        state = value_of(last, "linkingState", "linking_state")
        raise CLIInternalError(
            f"Timed out waiting for endpoint '{endpoint_name}' "
            f"(last linkingState={state or 'unknown'})."
        )

    def _require_active_subscription(
        self, parsed_resource_id: Dict[str, Any], resource_kind: str
    ):
        subscription_id = parsed_resource_id.get("subscription")
        if (
            subscription_id
            and subscription_id.casefold() != self.subscription_id.casefold()
        ):
            raise InvalidArgumentValueError(
                f"Cross-subscription {resource_kind} resources are not supported. "
                f"Select subscription '{subscription_id}' with 'az account set' "
                "before running this workflow."
            )
