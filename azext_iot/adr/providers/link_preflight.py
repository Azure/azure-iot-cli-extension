# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Target lookup and RBAC preflight strategies for namespace links."""

from dataclasses import dataclass
from typing import Callable, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link_helpers import parse_hub_resource_id
from azext_iot.adr.rbac import (
    resolve_linked_resource_principal,
    resolve_namespace_outbound_principal,
)
from azext_iot.adr.topology import DPS_CAP_EXCEEDED_MSG, endpoint_is_type, get_endpoints, is_failed_link_endpoint


@dataclass(frozen=True)
class TargetLookup:
    """Configuration needed to resolve one kind of linked ARM resource."""

    factory: Callable
    operation_group_name: str
    name_parameter: str
    display_name: str
    require_standard_hub: bool = False


def validate_dps_hubs(namespace: dict, target: dict, planned_hubs=None) -> None:
    hubs = (target.get("properties") or {}).get("iotHubs") or []
    if not isinstance(hubs, list):
        raise AzureResponseError("DPS properties.iotHubs must be a list.")
    existing_hubs = {
        parse_hub_resource_id(endpoint["resourceId"])["name"].casefold(): endpoint
        for endpoint in get_endpoints(namespace, "messaging").values()
        if endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE)
    }
    available = {name for name, endpoint in existing_hubs.items() if endpoint.get("linkingState") == "Succeeded"}
    available.update(
        parse_hub_resource_id(endpoint["resourceId"])["name"].casefold()
        for endpoint in (planned_hubs or {}).values()
    )
    missing = []
    for hub in hubs:
        name = (hub.get("name") or hub.get("hostName")) if isinstance(hub, dict) else None
        if not isinstance(name, str) or not name:
            raise AzureResponseError("A DPS properties.iotHubs entry has no valid name or hostName.")
        if name.split(".", 1)[0].casefold() not in available:
            missing.append(name)
    if missing:
        guidance = (
            "Use 'az iot adr ns link add' for a new DPS with all required Hubs not already Succeeded "
            "(--hub-endpoints accepts additional Hubs). For an existing Succeeded DPS, finish its required "
            "Hub links with 'link hub add', 'link hub update' or 'link wait' before retrying the DPS update. "
            "Use 'az iot adr ns link update' to retry an existing Failed DPS and its required Failed Hubs together. "
        )
        if any(name.split(".", 1)[0].casefold() not in existing_hubs for name in missing) and any(
            endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE) and is_failed_link_endpoint(endpoint)
            for endpoint in get_endpoints(namespace, "provisioning").values()
        ):
            guidance = (
                "The existing DPS is Failed and required Hub entries are missing. Wait for any pending Hubs first. "
                "Save the Failed Hubs' allocation settings, remove the Failed DPS with 'az iot adr ns link dps remove', "
                "then remove only its required Failed Hub entries with 'az iot adr ns link hub remove'. "
                "Do not remove Succeeded Hubs or delete the target resources. Use 'az iot adr ns link add' "
                "with the missing/removed Hubs and reapply saved allocation settings through --hub-endpoints provisioning. "
            )
        raise InvalidArgumentValueError(
            "DPS has classic Hubs that must be linked in the same request: "
            f"{', '.join(missing)}. {guidance}"
            "No role assignments or namespace changes were submitted."
        )


def validate_target_state(
    namespace: dict,
    target: dict,
    display_name: str,
    *,
    require_standard_hub: bool = False,
) -> None:
    namespace_location = str((namespace or {}).get("location") or "")
    target_location = str((target or {}).get("location") or "")
    if not target_location:
        raise AzureResponseError(
            f"The {display_name} response did not include a location. "
            "Wait for provisioning to complete and retry."
        )
    if namespace_location.casefold() != target_location.casefold():
        raise InvalidArgumentValueError(
            "Cross-region linking is not supported. Namespace region is "
            f"'{namespace_location}' and {display_name} region is "
            f"'{target_location}'. Create or select a target in the namespace region."
        )

    provisioning_state = str(
        ((target or {}).get("properties") or {}).get("provisioningState") or ""
    )
    if provisioning_state.casefold() != "succeeded":
        raise InvalidArgumentValueError(
            f"{display_name} provisioningState is "
            f"'{provisioning_state or 'unknown'}'; linking requires "
            "provisioningState 'Succeeded'. Wait for the resource and retry."
        )

    if require_standard_hub:
        sku_name = str(((target or {}).get("sku") or {}).get("name") or "")
        if not sku_name.upper().startswith("S"):
            raise InvalidArgumentValueError(
                f"IoT Hub SKU '{sku_name or 'unknown'}' is not supported for "
                "ADR linking. Use a Standard S-tier Hub such as S1."
            )


def get_target(cli_ctx, parsed: dict, strategy: TargetLookup) -> dict:
    """Resolve a target in the subscription encoded by its resource ID."""
    client = strategy.factory(
        cli_ctx, subscription_id=parsed["subscription_id"]
    )
    operations = getattr(client, strategy.operation_group_name)
    try:
        return dict(
            operations.get(
                resource_group_name=parsed["resource_group_name"],
                **{strategy.name_parameter: parsed["name"]},
            )
            or {}
        )
    except HttpResponseError as error:
        if error.status_code == 404:
            raise ResourceNotFoundError(
                f"{strategy.display_name} '{parsed['name']}' was not found in "
                f"resource group '{parsed['resource_group_name']}' and "
                f"subscription '{parsed['subscription_id']}'. Verify the resource ID."
            ) from error
        raise


def preflight_target(
    *,
    link_type: str,
    namespace: dict,
    target_resource_id: str,
    inbound_identity: Optional[dict],
    parsed: dict,
    strategy: TargetLookup,
    lookup: Callable[[dict, TargetLookup], dict],
    rbac_manager,
    rbac_requests: Optional[list] = None,
) -> dict:
    """Validate a target and either execute or queue its RBAC request."""
    target = lookup(parsed, strategy)
    validate_target_state(
        namespace,
        target,
        strategy.display_name,
        require_standard_hub=strategy.require_standard_hub,
    )
    namespace_scope = (namespace or {}).get("id")
    if not namespace_scope:
        raise AzureResponseError(
            "The namespace response did not include the resource ID required "
            "for link RBAC preflight."
        )
    request = {
        "link_type": link_type,
        "namespace_scope": namespace_scope,
        "target_scope": target_resource_id,
        "namespace_principal_id": resolve_namespace_outbound_principal(
            namespace
        ),
        "linked_principal_id": resolve_linked_resource_principal(
            target, inbound_identity, strategy.display_name
        ),
    }
    if link_type == "dps":
        # Retain DPS's SAMI presence prerequisite independently of outbound RBAC.
        request["namespace_system_principal_id"] = resolve_linked_resource_principal(
            namespace, {"type": "SystemAssigned"}, "namespace"
        )
    if rbac_requests is not None:
        rbac_requests.append(request)
    else:
        manager = rbac_manager() if callable(rbac_manager) else rbac_manager
        manager.ensure(**request)
    return target


def add_dps_hub_role_requirements(request: dict, namespace: dict, lookup_dps: Callable) -> None:
    """Bind the selected DPS principal to the Hub scopes in this link plan."""
    kind = request["link_type"]
    if kind not in ("hub", "dps"):
        return
    hub_scopes = (
        [request["target_scope"]] if kind == "hub" else [
            endpoint.get("resourceId")
            for endpoint in get_endpoints(namespace, "messaging").values()
            if endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE)
        ]
    )
    if not hub_scopes:
        return
    for scope in hub_scopes:
        parse_hub_resource_id(scope)

    principal = request["linked_principal_id"]
    if kind == "hub":
        endpoints = [
            endpoint for endpoint in get_endpoints(namespace, "provisioning").values()
            if endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE)
        ]
        if not endpoints:
            return
        if len(endpoints) != 1:
            raise InvalidArgumentValueError(DPS_CAP_EXCEEDED_MSG)
        endpoint = endpoints[0]
        principal = resolve_linked_resource_principal(
            lookup_dps(endpoint.get("resourceId")), endpoint.get("inboundCallerIdentity"), "DPS",
        )
    if not principal:
        raise AzureResponseError(
            "The linked DPS must select an attached managed identity before granting access to IoT Hubs."
        )
    request["dps_principal_id"] = principal
    request["hub_scopes"] = tuple(sorted({scope.rstrip("/").lower() for scope in hub_scopes}))
