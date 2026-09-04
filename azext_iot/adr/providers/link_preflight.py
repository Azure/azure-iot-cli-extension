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

from azext_iot.adr.rbac import (
    resolve_linked_resource_principal,
    resolve_namespace_outbound_principal,
)


@dataclass(frozen=True)
class TargetLookup:
    """Configuration needed to resolve one kind of linked ARM resource."""

    factory: Callable
    operation_group_name: str
    name_parameter: str
    display_name: str
    require_standard_hub: bool = False


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
    if rbac_requests is not None:
        rbac_requests.append(request)
    else:
        manager = rbac_manager() if callable(rbac_manager) else rbac_manager
        manager.ensure(**request)
    return target
