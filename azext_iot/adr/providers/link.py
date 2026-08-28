# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from knack.log import get_logger
from msrestazure.tools import is_valid_resource_id, parse_resource_id

from azext_iot._factory import iot_service_provisioning_factory
from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
    IdentityType,
    build_mi_body,
)
from azext_iot.adr.providers.base import ADRProvider

logger = get_logger(__name__)


DPS_FIRST_REQUIRED_MSG = (
    "Link a DPS to this namespace before adding a Hub. "
    "Run 'az iot adr ns link dps add ...' or 'az iot adr ns link add ...' to add both at once."
)

DPS_CAP_EXCEEDED_MSG = (
    "Namespace already has a linked DPS; use 'az iot adr ns link dps update' "
    "to rotate its identity. Only one DPS may be linked per namespace."
)

_MI_MUTEX_MSG = (
    "Specify only one linked-resource identity: use --mi-system-assigned for its "
    "system-assigned identity, or --mi-user-assigned <uami-resource-id> for a "
    "user-assigned identity attached to that resource."
)

_MI_REQUIRED_MSG = (
    "An inbound caller identity is required from the linked resource. Pass "
    "--mi-system-assigned for its system-assigned identity, or "
    "--mi-user-assigned <uami-resource-id> for an attached user-assigned identity."
)


def _parse_dps_resource_id(dps_resource_id: str) -> dict:
    """Parse a DPS ARM resource ID into its components.

    Expected shape:
        /subscriptions/<sub>/resourceGroups/<rg>/providers/
            Microsoft.Devices/provisioningServices/<name>
    """
    raw = (dps_resource_id or "").strip()
    if not raw:
        raise InvalidArgumentValueError(
            "--dps-id is required and must be a Microsoft.Devices/provisioningServices ARM resource ID."
        )
    # Friendly hint: a bare name (no slashes) is the most common mistake here.
    if "/" not in raw:
        raise InvalidArgumentValueError(
            f"'{raw}' looks like a bare DPS name. Pass the full ARM resource ID instead "
            "(use 'az iot dps show -n <dps> --query id -o tsv' to retrieve it)."
        )
    if not is_valid_resource_id(raw):
        raise InvalidArgumentValueError(
            f"'{dps_resource_id}' is not a valid ARM resource ID."
        )
    parsed = parse_resource_id(raw)
    # Reject child resources (e.g. .../provisioningServices/<n>/certificates/<c>) and
    # any non-DPS resource type.
    if (
        (parsed.get("namespace") or "").lower() != "microsoft.devices"
        or (parsed.get("type") or "").lower() != "provisioningservices"
        or "child_name_1" in parsed
    ):
        raise InvalidArgumentValueError(
            f"'{dps_resource_id}' is not a Microsoft.Devices/provisioningServices resource ID."
        )
    return {
        "subscription_id": parsed["subscription"],
        "resource_group_name": parsed["resource_group"],
        "name": parsed["name"],
    }


def _parse_su_resource_id(su_resource_id: str) -> dict:
    """Parse an Update Instance ARM resource ID into its components.

    Expected shape:
        /subscriptions/<sub>/resourceGroups/<rg>/providers/
            Microsoft.DeviceUpdate/updateInstances/<name>
    """
    raw = (su_resource_id or "").strip()
    if not raw:
        raise InvalidArgumentValueError(
            "--su-id is required and must be a Microsoft.DeviceUpdate/updateInstances ARM resource ID."
        )
    # Friendly hint: a bare name (no slashes) is the most common mistake here.
    if "/" not in raw:
        raise InvalidArgumentValueError(
            f"'{raw}' looks like a bare Update Instance name. Pass the full ARM resource ID instead."
        )
    if not is_valid_resource_id(raw):
        raise InvalidArgumentValueError(
            f"'{su_resource_id}' is not a valid ARM resource ID."
        )
    parsed = parse_resource_id(raw)
    # Reject child resources and any non-updateInstances resource type.
    if (
        (parsed.get("namespace") or "").lower() != "microsoft.deviceupdate"
        or (parsed.get("type") or "").lower() != "updateinstances"
        or "child_name_1" in parsed
    ):
        raise InvalidArgumentValueError(
            f"'{su_resource_id}' is not a Microsoft.DeviceUpdate/updateInstances resource ID. "
            "Pass the full ARM resource ID of the Software Update instance."
        )
    return {
        "subscription_id": parsed["subscription"],
        "resource_group_name": parsed["resource_group"],
        "name": parsed["name"],
    }


def _resolve_inbound_identity(
    mi_system_assigned: bool, mi_user_assigned: Optional[str]
) -> Optional[dict]:
    """Build the InboundCallerIdentity body from CLI flags, or None when neither is given.

    SAMI and UAMI are mutually exclusive. This does not require an identity (returns None when
    no flag is supplied) so it can be shared by both ``add`` (which requires one, via
    ``_build_inbound_identity``) and ``update`` (where the caller may change other fields only).
    """
    # Normalize empty/whitespace UAMI before the mutex check so a stray
    # '--mi-user-assigned ""' is treated as not provided.
    if mi_user_assigned is not None and not mi_user_assigned.strip():
        mi_user_assigned = None
    if mi_system_assigned and mi_user_assigned:
        raise ArgumentUsageError(_MI_MUTEX_MSG)
    return build_mi_body(
        mi_system_assigned,
        mi_user_assigned,
        sami_type=IdentityType.system_assigned.value,
        uami_type=IdentityType.user_assigned.value,
    )


def _build_inbound_identity(mi_system_assigned: bool, mi_user_assigned: Optional[str]) -> dict:
    """Build the InboundCallerIdentity body for ``add`` flows. Exactly one variant required."""
    body = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
    if body is None:
        raise RequiredArgumentMissingError(_MI_REQUIRED_MSG)
    return body


def _get_endpoints(namespace: dict, section: str) -> dict:
    """Return ``properties.<section>.endpoints`` from a namespace, defaulting to {} at each hop.

    ``section`` is one of "messaging" (Hub), "provisioning" (DPS) or "updating" (Software Updates).
    """
    return ((((namespace or {}).get("properties") or {}).get(section) or {}).get("endpoints")) or {}


def _get_messaging_endpoints(namespace: dict) -> dict:
    return _get_endpoints(namespace, "messaging")


def _get_provisioning_endpoints(namespace: dict) -> dict:
    return _get_endpoints(namespace, "provisioning")


def _get_updating_endpoints(namespace: dict) -> dict:
    return _get_endpoints(namespace, "updating")


def _project_endpoint_section(endpoints: dict, expected_type: str) -> list:
    """Project one endpoint section without hiding older records.

    The section itself is authoritative (messaging means Hub, provisioning means DPS,
    updating means Software Updates). Older records may omit ``endpointType``; strict
    filtering made namespace counts non-zero while the corresponding list looked empty.
    Preserve filtering for an explicitly different future type, but infer the type when
    it is absent.
    """
    projected = []
    for name, endpoint in endpoints.items():
        body = dict(endpoint or {})
        endpoint_type = body.get("endpointType")
        if endpoint_type and str(endpoint_type).casefold() != expected_type.casefold():
            continue
        body.setdefault("endpointType", expected_type)
        projected.append({"name": name, **body})
    return projected


def _build_hub_endpoint_body(
    hub_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
    availability: Optional[str] = None,
    allocation_weight: Optional[int] = None,
) -> dict:
    """Build a full Hub messaging-endpoint body for a namespace PATCH."""
    body = {
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": hub_resource_id,
    }
    inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
    if inbound_identity is not None:
        body["inboundCallerIdentity"] = inbound_identity
    provisioning = {}
    if availability is not None:
        provisioning["availability"] = availability
    if allocation_weight is not None:
        provisioning["allocationWeight"] = allocation_weight
    if provisioning:
        body["provisioning"] = provisioning
    return body


def _build_dps_endpoint_body(
    dps_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
) -> dict:
    """Build a full DPS provisioning-endpoint body for a namespace PATCH."""
    return {
        "endpointType": DPS_ENDPOINT_TYPE,
        "resourceId": dps_resource_id,
        "inboundCallerIdentity": _build_inbound_identity(mi_system_assigned, mi_user_assigned),
    }


def _build_su_endpoint_body(
    su_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
) -> dict:
    """Build a full Software Updates updating-endpoint body for a namespace PATCH."""
    return {
        "endpointType": SU_ENDPOINT_TYPE,
        "resourceId": su_resource_id,
        "inboundCallerIdentity": _build_inbound_identity(mi_system_assigned, mi_user_assigned),
    }


def _endpoint_update_body(
    existing: Optional[dict],
    inbound_identity: Optional[dict] = None,
) -> dict:
    """Build the endpoint body for an *update* PATCH.

    A namespace endpoint update must re-send the endpoint's identity (``endpointType`` and
    ``resourceId``), not a sparse delta, or the backend rejects it with InvalidRequestContent.
    Provisioning is intentionally omitted because established links only
    support inbound-identity rotation.
    """
    existing = existing or {}
    body: dict = {
        "endpointType": existing.get("endpointType"),
        "resourceId": existing.get("resourceId"),
    }
    current_inbound = existing.get("inboundCallerIdentity")
    if current_inbound is not None:
        body["inboundCallerIdentity"] = current_inbound
    if inbound_identity is not None:
        body["inboundCallerIdentity"] = inbound_identity
    return body


class LinkProvider(ADRProvider):
    def __init__(self, cmd):
        super(LinkProvider, self).__init__(cmd)

    # Helpers

    def _get_namespace(self, namespace_name: str, resource_group_name: str) -> dict:
        return dict(
            self.client.namespaces.get(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            or {}
        )

    def list_all(self, namespace_name: str, resource_group_name: str) -> list:
        """Project every endpoint section from one namespace read."""
        namespace = self._get_namespace(namespace_name, resource_group_name)
        return (
            _project_endpoint_section(
                _get_provisioning_endpoints(namespace),
                DPS_ENDPOINT_TYPE,
            )
            + _project_endpoint_section(
                _get_messaging_endpoints(namespace),
                IOT_HUB_ENDPOINT_TYPE,
            )
            + _project_endpoint_section(
                _get_updating_endpoints(namespace),
                SU_ENDPOINT_TYPE,
            )
        )

    def _patch_messaging_endpoints(
        self,
        namespace_name: str,
        resource_group_name: str,
        endpoints_patch: dict,
        no_wait: bool = False,
        **kwargs,
    ):
        properties = {"properties": {"messaging": {"endpoints": endpoints_patch}}}
        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties=properties,
        )
        return self._wait(
            poller,
            f"Updating messaging endpoints on namespace {namespace_name}...",
            no_wait=no_wait,
            **kwargs,
        )

    # Hub commands

    def hub_add(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        hub_resource_id: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        availability: Optional[str] = None,
        allocation_weight: Optional[int] = None,
        **kwargs,
    ):
        """Add an IoT Hub messaging endpoint to a namespace (DPS-first preflight)."""
        existing = self._get_namespace(namespace_name, resource_group_name)

        # DPS-first: namespace must already have at least one DPS endpoint
        if not _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(DPS_FIRST_REQUIRED_MSG)

        endpoint_body = _build_hub_endpoint_body(
            hub_resource_id,
            mi_system_assigned,
            mi_user_assigned,
            availability=availability,
            allocation_weight=allocation_weight,
        )

        return self._patch_messaging_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_body},
            **kwargs,
        )

    def hub_update(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        **kwargs,
    ):
        """Partial-update an existing IoT Hub messaging endpoint on a namespace."""
        if mi_system_assigned and mi_user_assigned:
            raise ArgumentUsageError(_MI_MUTEX_MSG)

        existing = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_messaging_endpoints(existing)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"Hub endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --mi-system-assigned or "
                "--mi-user-assigned <uami-resource-id>."
            )

        # The backend requires the full endpoint identity (endpointType + resourceId) on update,
        # so re-send the existing endpoint with the requested changes overlaid rather than a
        # sparse patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoints.get(endpoint_name),
            inbound_identity=inbound_identity,
        )

        return self._patch_messaging_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_patch},
            **kwargs,
        )

    def hub_show(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        """Project a single Hub messaging endpoint from the namespace."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_messaging_endpoints(ns)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"Hub endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )
        return {"name": endpoint_name, **(endpoints[endpoint_name] or {})}

    def hub_list(self, namespace_name: str, resource_group_name: str):
        """List all Hub messaging endpoints on the namespace."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        return _project_endpoint_section(
            _get_messaging_endpoints(ns), IOT_HUB_ENDPOINT_TYPE
        )

    # DPS commands

    def _patch_provisioning_endpoints(
        self,
        namespace_name: str,
        resource_group_name: str,
        endpoints_patch: dict,
        no_wait: bool = False,
        **kwargs,
    ):
        properties = {"properties": {"provisioning": {"endpoints": endpoints_patch}}}
        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties=properties,
        )
        return self._wait(
            poller,
            f"Updating provisioning endpoints on namespace {namespace_name}...",
            no_wait=no_wait,
            **kwargs,
        )

    def _side_get_dps_resource(self, dps_resource_id: str) -> dict:
        """Side-GET the DPS RP to surface existing ``properties.iotHubs[]`` registrations.

        Errors here are non-fatal: we surface a warning and return an empty dict so the
        primary projection still succeeds. RBAC on DPS is independent of the namespace.
        """
        try:
            parsed = _parse_dps_resource_id(dps_resource_id)
        except InvalidArgumentValueError:  # pragma: no cover - validated upstream
            return {}
        dps_name = parsed["name"]
        try:
            client = iot_service_provisioning_factory(self.cmd.cli_ctx).iot_dps_resource
            return dict(
                client.get(
                    resource_group_name=parsed["resource_group_name"],
                    provisioning_service_name=dps_name,
                )
                or {}
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning(
                "Could not list existing IoT Hubs registered on DPS '%s': %s", dps_name, exc
            )
            return {}

    def dps_add(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        dps_resource_id: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        **kwargs,
    ):
        """Add a DPS provisioning endpoint to a namespace.

        Only one DPS endpoint may be linked per namespace; the existence check
        below rejects a second one.
        """
        _parse_dps_resource_id(dps_resource_id)  # validate ARM ID shape up front

        existing = self._get_namespace(namespace_name, resource_group_name)
        if _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)

        endpoint_body = _build_dps_endpoint_body(
            dps_resource_id, mi_system_assigned, mi_user_assigned
        )
        return self._patch_provisioning_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_body},
            **kwargs,
        )

    def dps_update(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        **kwargs,
    ):
        """Partial-update an existing DPS provisioning endpoint on a namespace."""
        if mi_system_assigned and mi_user_assigned:
            raise ArgumentUsageError(_MI_MUTEX_MSG)

        existing = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_provisioning_endpoints(existing)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"DPS endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --mi-system-assigned or "
                "--mi-user-assigned <uami-resource-id> to change the inbound caller identity."
            )

        # The backend requires the full endpoint body (endpointType + resourceId) on update, so
        # re-send the existing endpoint with the new inbound identity overlaid rather than a sparse
        # patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoints.get(endpoint_name), inbound_identity=inbound_identity
        )

        return self._patch_provisioning_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_patch},
            **kwargs,
        )

    def dps_show(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        """Project a single DPS provisioning endpoint, enriched with the DPS RP's existing IoT Hub registrations."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_provisioning_endpoints(ns)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"DPS endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )
        endpoint = dict(endpoints[endpoint_name] or {})
        endpoint["name"] = endpoint_name
        dps_resource_id = endpoint.get("resourceId")
        if dps_resource_id:
            dps = self._side_get_dps_resource(dps_resource_id)
            brownfield_hubs = (dps.get("properties") or {}).get("iotHubs") or []
            # NOTE: 'brownfieldHubs' is a public response key documented in _help.py and
            # asserted by tests; do not rename without coordinating those.
            endpoint["brownfieldHubs"] = brownfield_hubs
        return endpoint

    def dps_list(self, namespace_name: str, resource_group_name: str):
        """List all DPS provisioning endpoints on the namespace."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        return _project_endpoint_section(
            _get_provisioning_endpoints(ns), DPS_ENDPOINT_TYPE
        )

    # Software Updates commands

    def _patch_updating_endpoints(
        self,
        namespace_name: str,
        resource_group_name: str,
        endpoints_patch: dict,
        no_wait: bool = False,
        **kwargs,
    ):
        properties = {"properties": {"updating": {"endpoints": endpoints_patch}}}
        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties=properties,
        )
        return self._wait(
            poller,
            f"Updating software update endpoints on namespace {namespace_name}...",
            no_wait=no_wait,
            **kwargs,
        )

    def su_add(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        su_resource_id: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        **kwargs,
    ):
        """Add a Software Updates updating endpoint to a namespace."""
        _parse_su_resource_id(su_resource_id)  # validate ARM ID shape up front

        existing = self._get_namespace(namespace_name, resource_group_name)
        if endpoint_name in _get_updating_endpoints(existing):
            raise ArgumentUsageError(
                f"Software update endpoint '{endpoint_name}' already exists on namespace "
                f"'{namespace_name}'. Use 'az iot adr ns link su update' to modify it."
            )

        endpoint_body = _build_su_endpoint_body(
            su_resource_id, mi_system_assigned, mi_user_assigned
        )
        return self._patch_updating_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_body},
            **kwargs,
        )

    def su_update(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        mi_system_assigned: bool = False,
        mi_user_assigned: Optional[str] = None,
        **kwargs,
    ):
        """Partial-update an existing Software Updates updating endpoint on a namespace."""
        if mi_system_assigned and mi_user_assigned:
            raise ArgumentUsageError(_MI_MUTEX_MSG)

        existing = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_updating_endpoints(existing)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"Software update endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --mi-system-assigned or "
                "--mi-user-assigned <uami-resource-id> to change the inbound caller identity."
            )

        # The backend requires the full endpoint body (endpointType + resourceId) on update, so
        # re-send the existing endpoint with the new inbound identity overlaid rather than a sparse
        # patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoints.get(endpoint_name), inbound_identity=inbound_identity
        )

        return self._patch_updating_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            endpoints_patch={endpoint_name: endpoint_patch},
            **kwargs,
        )

    def su_show(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        """Project a single Software Updates updating endpoint from the namespace."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        endpoints = _get_updating_endpoints(ns)
        if endpoint_name not in endpoints:
            raise ResourceNotFoundError(
                f"Software update endpoint '{endpoint_name}' was not found on namespace '{namespace_name}'."
            )
        return {"name": endpoint_name, **(endpoints[endpoint_name] or {})}

    def su_list(self, namespace_name: str, resource_group_name: str):
        """List all Software Updates updating endpoints on the namespace."""
        ns = self._get_namespace(namespace_name, resource_group_name)
        return _project_endpoint_section(
            _get_updating_endpoints(ns), SU_ENDPOINT_TYPE
        )

    # Bundled link add

    def link_add(
        self,
        namespace_name: str,
        resource_group_name: str,
        hub_endpoint_name: str,
        hub_resource_id: str,
        dps_endpoint_name: str,
        dps_resource_id: str,
        hub_mi_system_assigned: bool = False,
        hub_mi_user_assigned: Optional[str] = None,
        dps_mi_system_assigned: bool = False,
        dps_mi_user_assigned: Optional[str] = None,
        hub_availability: Optional[str] = None,
        hub_allocation_weight: Optional[int] = None,
        **kwargs,
    ):
        """Bundled link: add a Hub + DPS in a single namespace PATCH.

        The DPS entry is serialized into ``properties.provisioning.endpoints`` and the Hub
        entry into ``properties.messaging.endpoints`` in the same request. DPS is applied
        first because provisioning endpoints land before messaging endpoints in the
        materialized body order below.
        """
        # Validate DPS ARM ID up front; reject overflow before composing the body.
        _parse_dps_resource_id(dps_resource_id)
        existing = self._get_namespace(namespace_name, resource_group_name)
        if _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)

        # Build the two endpoint bodies (each call validates its own MI flag pair).
        dps_body = _build_dps_endpoint_body(
            dps_resource_id, dps_mi_system_assigned, dps_mi_user_assigned
        )
        hub_body = _build_hub_endpoint_body(
            hub_resource_id,
            hub_mi_system_assigned,
            hub_mi_user_assigned,
            availability=hub_availability,
            allocation_weight=hub_allocation_weight,
        )

        # DPS-first ordering in the bundled PATCH body.
        properties = {
            "properties": {
                "provisioning": {"endpoints": {dps_endpoint_name: dps_body}},
                "messaging": {"endpoints": {hub_endpoint_name: hub_body}},
            }
        }
        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties=properties,
        )
        return self._wait(poller, f"Linking Hub + DPS on namespace {namespace_name}...", **kwargs)
