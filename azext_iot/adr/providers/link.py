# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Callable, Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from knack.log import get_logger

from azext_iot._factory import (
    adr_iot_hub_service_factory,
    adr_iot_service_provisioning_factory,
    adr_update_instance_service_factory,
)
from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
)
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.link_helpers import (
    MI_MUTEX_MSG as _MI_MUTEX_MSG,
    build_dps_endpoint_body as _build_dps_endpoint_body,
    build_hub_endpoint_body as _build_hub_endpoint_body,
    build_su_endpoint_body as _build_su_endpoint_body,
    endpoint_update_body as _endpoint_update_body,
    get_messaging_endpoints as _get_messaging_endpoints,
    get_provisioning_endpoints as _get_provisioning_endpoints,
    get_updating_endpoints as _get_updating_endpoints,
    parse_dps_resource_id as _parse_dps_resource_id,
    parse_hub_resource_id as _parse_hub_resource_id,
    parse_su_resource_id as _parse_su_resource_id,
    resolve_inbound_identity as _resolve_inbound_identity,
)
from azext_iot.adr.providers.link_persistence import (
    delete_linked_resource_and_endpoint,
    get_typed_endpoint,
    patch_namespace_endpoints,
    wait_for_linked_resource_deleted,
)
from azext_iot.adr.providers.link_preflight import (
    TargetLookup,
    get_target,
    preflight_target,
)
from azext_iot.adr.rbac import LinkRbacManager
from azext_iot.adr.topology import (
    DPS_CAP_EXCEEDED_MSG,
    DPS_REQUIRED_MSG,
    HUB_CAP_EXCEEDED_MSG,
    SU_CAP_EXCEEDED_MSG,
    endpoint_is_type,
    has_dps_endpoint,
    has_su_endpoint,
    hub_endpoint_count,
    is_failed_hub_endpoint,
)
from azext_iot.constants import LRO_POLL_WAIT_SEC

logger = get_logger(__name__)

_HUB_TARGET = TargetLookup(
    factory=adr_iot_hub_service_factory,
    operation_group_name="iot_hub_resource",
    name_parameter="resource_name",
    display_name="IoT Hub",
    require_standard_hub=True,
)
_DPS_TARGET = TargetLookup(
    factory=adr_iot_service_provisioning_factory,
    operation_group_name="iot_dps_resource",
    name_parameter="provisioning_service_name",
    display_name="DPS",
)
_SU_TARGET = TargetLookup(
    factory=adr_update_instance_service_factory,
    operation_group_name="update_instances",
    name_parameter="update_instance_name",
    display_name="Software Updates instance",
)


class LinkProvider(ADRProvider):
    def __init__(self, cmd):
        super(LinkProvider, self).__init__(cmd)
        self._rbac = None

    # Helpers

    def _get_namespace(self, namespace_name: str, resource_group_name: str) -> dict:
        return dict(
            self.client.namespaces.get(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            or {}
        )

    def _rbac_manager(self):
        if self._rbac is None:
            self._rbac = LinkRbacManager(self.cmd.cli_ctx)
        return self._rbac

    def _get_target(
        self,
        parsed: dict,
        strategy: TargetLookup,
    ) -> dict:
        return get_target(
            self.cmd.cli_ctx,
            parsed,
            strategy,
        )

    def _preflight_link(
        self,
        link_type: str,
        namespace: dict,
        target_resource_id: str,
        inbound_identity: Optional[dict],
        parsed: dict,
        strategy: TargetLookup,
        *,
        rbac_requests: Optional[list] = None,
    ) -> dict:
        return preflight_target(
            link_type=link_type,
            namespace=namespace,
            target_resource_id=target_resource_id,
            inbound_identity=inbound_identity,
            parsed=parsed,
            strategy=strategy,
            lookup=lambda parsed_id, _: self._get_target(parsed_id, strategy),
            rbac_manager=self._rbac_manager,
            rbac_requests=rbac_requests,
        )

    @staticmethod
    def _get_typed_endpoint(
        namespace: dict,
        section: str,
        endpoint_name: str,
        endpoint_type: str,
        namespace_name: str,
        display_name: str,
    ) -> dict:
        return get_typed_endpoint(
            namespace,
            section,
            endpoint_name,
            endpoint_type,
            namespace_name,
            display_name,
        )

    @staticmethod
    def _wait_for_linked_resource_deleted(
        get_operation: Callable,
        wait_sec: int = LRO_POLL_WAIT_SEC,
    ):
        return wait_for_linked_resource_deleted(
            get_operation,
            wait_sec=wait_sec,
        )

    def _delete_link(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        section: str,
        endpoint_type: str,
        display_name: str,
        parse_linked_resource_id: Callable,
        operations_factory: Callable,
        operation_group_name: str,
        delete_name_parameter: str,
        no_wait: bool = False,
        **kwargs,
    ):
        return delete_linked_resource_and_endpoint(
            cli_ctx=self.cmd.cli_ctx,
            client=self.client,
            get_namespace=self._get_namespace,
            await_terminal=self._await_terminal,
            wait_for_deleted=self._wait_for_linked_resource_deleted,
            endpoint_name=endpoint_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section=section,
            endpoint_type=endpoint_type,
            display_name=display_name,
            parse_linked_resource_id=parse_linked_resource_id,
            operations_factory=operations_factory,
            operation_group_name=operation_group_name,
            delete_name_parameter=delete_name_parameter,
            no_wait=no_wait,
            **kwargs,
        )

    def _patch_endpoints(
        self,
        namespace_name: str,
        resource_group_name: str,
        section: str,
        endpoints_patch: dict,
        status_message: str,
        no_wait: bool = False,
        **kwargs,
    ):
        return patch_namespace_endpoints(
            client=self.client,
            wait_operation=self._wait,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section=section,
            endpoints_patch=endpoints_patch,
            status_message=status_message,
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
        parsed_hub = _parse_hub_resource_id(hub_resource_id)
        existing = self._get_namespace(namespace_name, resource_group_name)

        # DPS-first: namespace must already have at least one DPS endpoint
        if not has_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_REQUIRED_MSG)
        if hub_endpoint_count(existing) >= 10:
            raise ArgumentUsageError(HUB_CAP_EXCEEDED_MSG)
        if endpoint_name in _get_messaging_endpoints(existing):
            raise ArgumentUsageError(
                f"Messaging endpoint '{endpoint_name}' already exists on namespace "
                f"'{namespace_name}' and cannot be repointed by link hub add. "
                "Use link hub update or delete the existing endpoint first."
            )

        endpoint_body = _build_hub_endpoint_body(
            hub_resource_id,
            mi_system_assigned,
            mi_user_assigned,
            availability=availability,
            allocation_weight=allocation_weight,
        )
        hub = self._preflight_link(
            link_type="hub",
            namespace=existing,
            target_resource_id=hub_resource_id,
            inbound_identity=endpoint_body.get("inboundCallerIdentity"),
            parsed=parsed_hub,
            strategy=_HUB_TARGET,
        )
        self._warn_if_hub_classically_linked(existing, parsed_hub, hub)

        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="messaging",
            endpoints_patch={endpoint_name: endpoint_body},
            status_message=(
                f"Updating messaging endpoints on namespace {namespace_name}..."
            ),
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
        endpoint = self._get_typed_endpoint(
            existing,
            "messaging",
            endpoint_name,
            IOT_HUB_ENDPOINT_TYPE,
            namespace_name,
            "Hub",
        )
        if is_failed_hub_endpoint(endpoint) and not has_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_REQUIRED_MSG)

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --system-assigned-mi or "
                "--user-assigned-mi <uami-resource-id>."
            )

        # The backend requires the full endpoint identity (endpointType + resourceId) on update,
        # so re-send the existing endpoint with the requested changes overlaid rather than a
        # sparse patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoint,
            inbound_identity=inbound_identity,
        )
        hub_resource_id = endpoint.get("resourceId")
        parsed_hub = _parse_hub_resource_id(hub_resource_id)
        hub = self._preflight_link(
            link_type="hub",
            namespace=existing,
            target_resource_id=hub_resource_id,
            inbound_identity=inbound_identity,
            parsed=parsed_hub,
            strategy=_HUB_TARGET,
        )
        self._warn_if_hub_classically_linked(existing, parsed_hub, hub)

        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="messaging",
            endpoints_patch={endpoint_name: endpoint_patch},
            status_message=(
                f"Updating messaging endpoints on namespace {namespace_name}..."
            ),
            **kwargs,
        )

    def hub_delete(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        """Delete a linked IoT Hub and remove its namespace endpoint."""
        return self._delete_link(
            endpoint_name=endpoint_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="messaging",
            endpoint_type=IOT_HUB_ENDPOINT_TYPE,
            display_name="Hub",
            parse_linked_resource_id=_parse_hub_resource_id,
            operations_factory=adr_iot_hub_service_factory,
            operation_group_name="iot_hub_resource",
            delete_name_parameter="resource_name",
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
        endpoints = _get_messaging_endpoints(ns)
        # Filter to only Hub-typed entries (defensively; other endpointTypes may exist later)
        return [
            {"name": name, **(ep or {})}
            for name, ep in endpoints.items()
            if endpoint_is_type(ep, IOT_HUB_ENDPOINT_TYPE)
        ]

    # DPS commands

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
            client = adr_iot_service_provisioning_factory(
                self.cmd.cli_ctx,
                subscription_id=parsed["subscription_id"],
            ).iot_dps_resource
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

    def _warn_if_hub_classically_linked(
        self, namespace: dict, parsed_hub: dict, hub: dict
    ):
        hub_names = {
            parsed_hub["name"].casefold(),
            str(((hub.get("properties") or {}).get("hostName") or "")).casefold(),
            str(((hub.get("properties") or {}).get("deviceHostName") or "")).casefold(),
        }
        for endpoint in _get_provisioning_endpoints(namespace).values():
            if not endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE):
                continue
            dps = self._side_get_dps_resource(endpoint.get("resourceId"))
            for classic_hub in ((dps.get("properties") or {}).get("iotHubs") or []):
                classic_name = str(
                    classic_hub.get("hostName")
                    or classic_hub.get("name")
                    or ""
                ).casefold()
                if (
                    classic_name in hub_names
                    or classic_name.split(".", 1)[0]
                    == parsed_hub["name"].casefold()
                ):
                    logger.warning(
                        "IoT Hub '%s' is also configured in the linked DPS "
                        "properties.iotHubs list. The namespace Hub link is the "
                        "authoritative ADR relationship; keep classic DPS allocation "
                        "settings reconciled.",
                        parsed_hub["name"],
                    )
                    return

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
        parsed_dps = _parse_dps_resource_id(dps_resource_id)

        existing = self._get_namespace(namespace_name, resource_group_name)
        if has_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)
        if endpoint_name in _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(
                f"Provisioning endpoint '{endpoint_name}' already exists on "
                f"namespace '{namespace_name}'. Update or remove it first."
            )

        endpoint_body = _build_dps_endpoint_body(
            dps_resource_id, mi_system_assigned, mi_user_assigned
        )
        self._preflight_link(
            link_type="dps",
            namespace=existing,
            target_resource_id=dps_resource_id,
            inbound_identity=endpoint_body.get("inboundCallerIdentity"),
            parsed=parsed_dps,
            strategy=_DPS_TARGET,
        )
        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="provisioning",
            endpoints_patch={endpoint_name: endpoint_body},
            status_message=(
                f"Updating provisioning endpoints on namespace {namespace_name}..."
            ),
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
        endpoint = self._get_typed_endpoint(
            existing,
            "provisioning",
            endpoint_name,
            DPS_ENDPOINT_TYPE,
            namespace_name,
            "DPS",
        )

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --system-assigned-mi or "
                "--user-assigned-mi <uami-resource-id> to change the inbound caller identity."
            )

        # The backend requires the full endpoint body (endpointType + resourceId) on update, so
        # re-send the existing endpoint with the new inbound identity overlaid rather than a sparse
        # patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoint, inbound_identity=inbound_identity
        )
        dps_resource_id = endpoint.get("resourceId")
        self._preflight_link(
            link_type="dps",
            namespace=existing,
            target_resource_id=dps_resource_id,
            inbound_identity=inbound_identity,
            parsed=_parse_dps_resource_id(dps_resource_id),
            strategy=_DPS_TARGET,
        )

        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="provisioning",
            endpoints_patch={endpoint_name: endpoint_patch},
            status_message=(
                f"Updating provisioning endpoints on namespace {namespace_name}..."
            ),
            **kwargs,
        )

    def dps_delete(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        """Delete a linked DPS and remove its namespace endpoint."""
        return self._delete_link(
            endpoint_name=endpoint_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="provisioning",
            endpoint_type=DPS_ENDPOINT_TYPE,
            display_name="DPS",
            parse_linked_resource_id=_parse_dps_resource_id,
            operations_factory=adr_iot_service_provisioning_factory,
            operation_group_name="iot_dps_resource",
            delete_name_parameter="provisioning_service_name",
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
        endpoints = _get_provisioning_endpoints(ns)
        return [
            {"name": name, **(ep or {})}
            for name, ep in endpoints.items()
            if endpoint_is_type(ep, DPS_ENDPOINT_TYPE)
        ]

    # Software Updates commands

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
        parsed_su = _parse_su_resource_id(su_resource_id)

        existing = self._get_namespace(namespace_name, resource_group_name)
        updating_endpoints = _get_updating_endpoints(existing)
        if has_su_endpoint(existing):
            raise ArgumentUsageError(SU_CAP_EXCEEDED_MSG)
        if endpoint_name in updating_endpoints:
            raise ArgumentUsageError(
                f"Updating endpoint '{endpoint_name}' already exists on namespace "
                f"'{namespace_name}' and cannot be overwritten by link su add. "
                "Update or remove the existing endpoint first."
            )

        endpoint_body = _build_su_endpoint_body(
            su_resource_id, mi_system_assigned, mi_user_assigned
        )
        self._preflight_link(
            link_type="su",
            namespace=existing,
            target_resource_id=su_resource_id,
            inbound_identity=endpoint_body.get("inboundCallerIdentity"),
            parsed=parsed_su,
            strategy=_SU_TARGET,
        )
        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="updating",
            endpoints_patch={endpoint_name: endpoint_body},
            status_message=(
                "Updating software update endpoints on namespace "
                f"{namespace_name}..."
            ),
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
        endpoint = self._get_typed_endpoint(
            existing,
            "updating",
            endpoint_name,
            SU_ENDPOINT_TYPE,
            namespace_name,
            "Software update",
        )

        inbound_identity = _resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
        if inbound_identity is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Pass --system-assigned-mi or "
                "--user-assigned-mi <uami-resource-id> to change the inbound caller identity."
            )

        # The backend requires the full endpoint body (endpointType + resourceId) on update, so
        # re-send the existing endpoint with the new inbound identity overlaid rather than a sparse
        # patch (which fails InvalidRequestContent).
        endpoint_patch = _endpoint_update_body(
            endpoint, inbound_identity=inbound_identity
        )
        su_resource_id = endpoint.get("resourceId")
        self._preflight_link(
            link_type="su",
            namespace=existing,
            target_resource_id=su_resource_id,
            inbound_identity=inbound_identity,
            parsed=_parse_su_resource_id(su_resource_id),
            strategy=_SU_TARGET,
        )

        return self._patch_endpoints(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="updating",
            endpoints_patch={endpoint_name: endpoint_patch},
            status_message=(
                "Updating software update endpoints on namespace "
                f"{namespace_name}..."
            ),
            **kwargs,
        )

    def su_delete(
        self,
        endpoint_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        """Delete a linked Update Instance and remove its namespace endpoint."""
        return self._delete_link(
            endpoint_name=endpoint_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="updating",
            endpoint_type=SU_ENDPOINT_TYPE,
            display_name="Software update",
            parse_linked_resource_id=_parse_su_resource_id,
            operations_factory=adr_update_instance_service_factory,
            operation_group_name="update_instances",
            delete_name_parameter="update_instance_name",
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
        endpoints = _get_updating_endpoints(ns)
        return [
            {"name": name, **(ep or {})}
            for name, ep in endpoints.items()
            if endpoint_is_type(ep, SU_ENDPOINT_TYPE)
        ]

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
        # Validate both ARM IDs up front; reject overflow/collisions before
        # composing the body or touching RBAC.
        parsed_dps = _parse_dps_resource_id(dps_resource_id)
        parsed_hub = _parse_hub_resource_id(hub_resource_id)
        existing = self._get_namespace(namespace_name, resource_group_name)
        if has_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)
        if hub_endpoint_count(existing) >= 10:
            raise ArgumentUsageError(HUB_CAP_EXCEEDED_MSG)
        if dps_endpoint_name in _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(
                f"Provisioning endpoint '{dps_endpoint_name}' already exists on "
                f"namespace '{namespace_name}'."
            )
        if hub_endpoint_name in _get_messaging_endpoints(existing):
            raise ArgumentUsageError(
                f"Messaging endpoint '{hub_endpoint_name}' already exists on "
                f"namespace '{namespace_name}' and cannot be repointed."
            )

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
        rbac_requests = []
        self._preflight_link(
            link_type="dps",
            namespace=existing,
            target_resource_id=dps_resource_id,
            inbound_identity=dps_body.get("inboundCallerIdentity"),
            parsed=parsed_dps,
            strategy=_DPS_TARGET,
            rbac_requests=rbac_requests,
        )
        hub = self._preflight_link(
            link_type="hub",
            namespace=existing,
            target_resource_id=hub_resource_id,
            inbound_identity=hub_body.get("inboundCallerIdentity"),
            parsed=parsed_hub,
            strategy=_HUB_TARGET,
            rbac_requests=rbac_requests,
        )
        self._rbac_manager().ensure_many(rbac_requests)
        self._warn_if_hub_classically_linked(existing, parsed_hub, hub)

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
