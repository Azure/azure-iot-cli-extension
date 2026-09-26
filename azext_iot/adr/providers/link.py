# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from time import monotonic, sleep
from typing import Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError
from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.arm import sanitize_arm_identity

from azext_iot._factory import (
    _get_canary_credential_scopes,
    adr_iot_hub_service_factory,
    adr_iot_service_provisioning_factory,
    adr_update_instance_service_factory,
)
from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
)
from azext_iot.adr.providers import base
from azext_iot.adr.providers.base import ADRProvider, _ADR_LRO_TIMEOUT_SECONDS
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
    resolve_update_identity,
)
from azext_iot.adr.providers.link_persistence import (
    get_typed_endpoint,
    patch_namespace_endpoints,
)
from azext_iot.adr.providers.link_preflight import (
    TargetLookup,
    get_target,
    preflight_target,
)
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery, validate_options
from azext_iot.adr.providers.wait import DEFAULT_WAIT_INTERVAL
from azext_iot.adr.rbac import LinkRbacManager, resolve_namespace_outbound_principal
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
    writable_namespace_properties,
)

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
    def __init__(self, cmd, client=None):
        super(LinkProvider, self).__init__(cmd, client=client)
        self._rbac = None
        self._link_requests = {}

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
        requests = []
        target = preflight_target(
            link_type=link_type,
            namespace=namespace,
            target_resource_id=target_resource_id,
            inbound_identity=inbound_identity,
            parsed=parsed,
            strategy=strategy,
            lookup=lambda parsed_id, _: self._get_target(parsed_id, strategy),
            rbac_manager=self._rbac_manager,
            rbac_requests=requests,
        )
        self._link_requests[(link_type, target_resource_id.casefold())] = deepcopy(requests)
        if rbac_requests is not None:
            rbac_requests.extend(requests)
        else:
            self._rbac_manager().ensure(**requests[0])
        return target

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

    def _delete_endpoint(
        self, endpoint_name, namespace_name, resource_group_name, section, endpoint_type, display_name,
    ):
        namespace = self.client.namespaces.get(
            resource_group_name=resource_group_name, namespace_name=namespace_name, retry_total=0,
        )
        endpoint = self._get_typed_endpoint(namespace, section, endpoint_name, endpoint_type, namespace_name, display_name)
        parse_target = {
            "messaging": _parse_hub_resource_id,
            "provisioning": _parse_dps_resource_id,
            "updating": _parse_su_resource_id,
        }[section]
        target = parse_target(endpoint.get("resourceId"))
        self._rbac_manager().ensure_unlink_reader(
            resolve_namespace_outbound_principal(namespace),
            f"/subscriptions/{target['subscription_id']}/resourceGroups/{target['resource_group_name']}",
        )
        properties = writable_namespace_properties(namespace["properties"])
        del properties[section]["endpoints"][endpoint_name]
        resource = {key: deepcopy(namespace[key]) for key in ("location", "tags") if key in namespace}
        resource["properties"] = properties
        resource["identity"] = sanitize_arm_identity(namespace["identity"])
        # NoPolling returns the initial PUT response, not asynchronous completion.
        return self.client.namespaces.begin_create_or_replace(
            resource_group_name=resource_group_name, namespace_name=namespace_name,
            resource=resource, polling=False, retry_total=0,
        ).result()

    def hub_delete(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        return self._delete_endpoint(
            endpoint_name, namespace_name, resource_group_name, "messaging", IOT_HUB_ENDPOINT_TYPE, "IoT Hub",
        )

    def dps_delete(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        return self._delete_endpoint(
            endpoint_name, namespace_name, resource_group_name, "provisioning", DPS_ENDPOINT_TYPE, "DPS",
        )

    def su_delete(self, endpoint_name: str, namespace_name: str, resource_group_name: str):
        return self._delete_endpoint(
            endpoint_name, namespace_name, resource_group_name, "updating", SU_ENDPOINT_TYPE, "Software Updates",
        )

    def _patch_link(
        self, namespace, namespace_name, resource_group_name, section,
        endpoints_patch, status_message, no_wait=False, budget=None, **kwargs,
    ):
        """Shared waited mutation policy; raw endpoint persistence remains separate."""
        budget = budget or LinkDeadline(
            kwargs.pop("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS),
            kwargs.pop("wait_sec", DEFAULT_WAIT_INTERVAL), clock=monotonic, sleeper=sleep,
        )
        name, expected = next(iter(endpoints_patch.items()))
        kind, parser, strategy = {
            "messaging": ("hub", _parse_hub_resource_id, _HUB_TARGET),
            "provisioning": ("dps", _parse_dps_resource_id, _DPS_TARGET),
            "updating": ("su", _parse_su_resource_id, _SU_TARGET),
        }[section]
        original_requests = deepcopy(self._link_requests.get((kind, expected["resourceId"].casefold())))
        original_dps = {
            name: _endpoint_update_body(endpoint)
            for name, endpoint in _get_provisioning_endpoints(namespace).items()
            if endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE)
        }

        def verify(current, deadline):
            requests = []
            deadline.remaining()
            if kind == "hub":
                current_dps = {
                    name: _endpoint_update_body(endpoint)
                    for name, endpoint in _get_provisioning_endpoints(current).items()
                    if endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE) and endpoint.get("linkingState") == "Succeeded"
                }
                if not original_dps or current_dps != original_dps:
                    raise AzureResponseError(
                        "The exact DPS dependency is no longer Succeeded; no Hub recovery PATCH submitted."
                    )
            preflight_target(
                link_type=kind, namespace=current, target_resource_id=expected["resourceId"],
                inbound_identity=expected.get("inboundCallerIdentity"), parsed=parser(expected["resourceId"]),
                strategy=strategy, lookup=lambda parsed, _: deadline.call(self._get_target, parsed, strategy),
                rbac_manager=self._rbac_manager, rbac_requests=requests,
            )
            deadline.remaining()
            if requests != original_requests:
                raise AzureResponseError("Link preflight principal or scope changed; no recovery PATCH submitted.")
            self._rbac_manager().verify_many(requests, guard=deadline.remaining)

        return LinkRecovery(
            self, namespace, section, name, expected, budget, verify,
            authorization_request=original_requests[0] if original_requests and len(original_requests) == 1 else None,
        ).run(
            submit=lambda body: self._patch_endpoints(
                namespace_name, resource_group_name, section, {name: body}, status_message, no_wait=True,
                # The waited canary path owns resource polling. Do not also
                # start an SDK thread against the broken async-status host.
                # Terminal no-wait retains the ordinary, real Azure Core poller.
                **({"polling": False} if not no_wait and base.POLL_PROVISIONING_STATE_WORKAROUND else {}),
            ),
            get=lambda: self._get_namespace(namespace_name, resource_group_name),
            status_message=status_message, no_wait=no_wait, endpoint_body=expected, **kwargs,
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
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
                "Use 'az iot adr ns link hub update' for an existing Hub link, "
                "or choose an unused endpoint name. To unlink, delete the Hub resource first, then use link hub delete."
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

        return self._patch_link(
            namespace=existing,
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
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

        inbound_identity = resolve_update_identity(endpoint, mi_system_assigned, mi_user_assigned)

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

        return self._patch_link(
            namespace=existing,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="messaging",
            endpoints_patch={endpoint_name: endpoint_patch},
            status_message=(
                f"Updating messaging endpoints on namespace {namespace_name}..."
            ),
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

    def _side_get_dps_resource(self, dps_resource_id: str) -> Optional[dict]:
        """Return None, with a warning, when optional DPS inspection is unavailable."""
        parsed = _parse_dps_resource_id(dps_resource_id)
        dps_name = parsed["name"]
        # Routing validation is mandatory even when profile lookup is optional.
        _get_canary_credential_scopes(self.cmd.cli_ctx)
        try:
            try:
                client = adr_iot_service_provisioning_factory(
                    self.cmd.cli_ctx,
                    subscription_id=parsed["subscription_id"],
                ).iot_dps_resource
            except CLIError as error:
                # Profile/credential lookup can fail for a different subscription
                # even when the caller can inspect the namespace.
                logger.warning("Could not initialize DPS inspection for '%s': %s", dps_resource_id, error)
                return None
            dps = client.get(
                resource_group_name=parsed["resource_group_name"],
                provisioning_service_name=dps_name,
            )
        except (HttpResponseError, ServiceRequestError, ServiceResponseError) as exc:
            logger.warning(
                "Could not list existing IoT Hubs registered on DPS '%s': %s", dps_name, exc
            )
            return None
        properties = dps.get("properties") if isinstance(dps, dict) else None
        if not isinstance(properties, dict):
            raise AzureResponseError("DPS inspection did not return a resource with valid properties.")
        hubs = properties.get("iotHubs")
        if hubs is not None and not isinstance(hubs, list):
            raise AzureResponseError("DPS inspection returned an invalid properties.iotHubs list.")
        return dps

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
            if dps is None:
                continue
            for classic_hub in ((dps.get("properties") or {}).get("iotHubs") or []):
                classic_name = str(
                    classic_hub.get("hostName")
                    or classic_hub.get("name")
                    or ""
                ).casefold()
                if classic_name and (
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
        parsed_dps = _parse_dps_resource_id(dps_resource_id)

        existing = self._get_namespace(namespace_name, resource_group_name)
        if has_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)
        if endpoint_name in _get_provisioning_endpoints(existing):
            raise ArgumentUsageError(
                f"Provisioning endpoint '{endpoint_name}' already exists on "
                f"namespace '{namespace_name}'. Choose an unused endpoint name. "
                "To unlink, delete the DPS resource first, then use link dps delete."
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
        return self._patch_link(
            namespace=existing,
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
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

        inbound_identity = resolve_update_identity(endpoint, mi_system_assigned, mi_user_assigned, required=True)

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

        return self._patch_link(
            namespace=existing,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            section="provisioning",
            endpoints_patch={endpoint_name: endpoint_patch},
            status_message=(
                f"Updating provisioning endpoints on namespace {namespace_name}..."
            ),
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
        endpoint["brownfieldHubs"] = None
        endpoint["brownfieldHubsAvailable"] = False
        if dps_resource_id:
            dps = self._side_get_dps_resource(dps_resource_id)
            if dps is not None:
                endpoint["brownfieldHubs"] = (dps.get("properties") or {}).get("iotHubs") or []
                endpoint["brownfieldHubsAvailable"] = True
        else:
            logger.warning("DPS endpoint '%s' has no resource ID; registered Hub information is unavailable.", endpoint_name)
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
        parsed_su = _parse_su_resource_id(su_resource_id)

        existing = self._get_namespace(namespace_name, resource_group_name)
        updating_endpoints = _get_updating_endpoints(existing)
        if has_su_endpoint(existing):
            raise ArgumentUsageError(SU_CAP_EXCEEDED_MSG)
        if endpoint_name in updating_endpoints:
            raise ArgumentUsageError(
                f"Updating endpoint '{endpoint_name}' already exists on namespace "
                f"'{namespace_name}' and cannot be overwritten by link su add. "
                "Choose an unused endpoint name. To unlink, delete the Update Instance first, then use link su delete."
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
        return self._patch_link(
            namespace=existing,
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
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
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

        inbound_identity = resolve_update_identity(endpoint, mi_system_assigned, mi_user_assigned, required=True)

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

        return self._patch_link(
            namespace=existing,
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

    # Combined DPS-first link add

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
        """Preflight both targets, link DPS successfully, then submit the Hub link.

        Even with no_wait, the DPS dependency must reach linkingState Succeeded.
        Only the final Hub operation may be returned without waiting. Partial
        completion is preserved on failure; never replay adds or roll back DPS.
        """
        timeout = kwargs.setdefault("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS)
        interval = kwargs.setdefault("wait_sec", DEFAULT_WAIT_INTERVAL)
        validate_options(timeout, interval)
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

        no_wait = kwargs.pop("no_wait", False)
        budget = LinkDeadline(timeout, interval, clock=monotonic, sleeper=sleep)
        try:
            linked_namespace = self._patch_link(
                existing, namespace_name, resource_group_name, "provisioning", {dps_endpoint_name: dps_body},
                f"Linking DPS on namespace {namespace_name} before submitting Hub...",
                budget=budget, **kwargs,
            )
        except (CLIError, HttpResponseError):
            logger.warning(
                "DPS linking did not complete; the Hub link was NOT submitted. Inspect 'iot adr ns link dps show'. "
                "If the DPS endpoint is Failed, use 'iot adr ns link dps update' with its existing identity, "
                "then wait for Succeeded before using 'iot adr ns link hub add'. "
                "Do not rerun combined link add while the DPS endpoint exists. No rollback was attempted."
            )
            raise

        try:
            if hub_endpoint_name in _get_messaging_endpoints(linked_namespace):
                raise ArgumentUsageError(
                    f"Messaging endpoint '{hub_endpoint_name}' appeared while DPS was linking. "
                    "The existing Hub endpoint will not be changed."
                )
            if hub_endpoint_count(linked_namespace) >= 10:
                raise ArgumentUsageError(HUB_CAP_EXCEEDED_MSG)
            logger.warning(
                "DPS link '%s' target and identity verified with linkingState Succeeded; submitting Hub link '%s'.",
                dps_endpoint_name, hub_endpoint_name,
            )
            return self._patch_link(
                linked_namespace, namespace_name, resource_group_name, "messaging", {hub_endpoint_name: hub_body},
                f"Linking Hub on namespace {namespace_name} after DPS Succeeded...",
                no_wait=no_wait, budget=budget, **kwargs,
            )
        except (CLIError, HttpResponseError):
            logger.warning(
                "DPS linking succeeded, but the Hub operation did not complete. The DPS link was not rolled back. "
                "Inspect 'iot adr ns link hub show': if the endpoint is Failed, use 'iot adr ns link hub update' "
                "with its existing identity; if absent, use 'iot adr ns link hub add'. "
                "For a pending endpoint, use 'iot adr ns link hub wait'. Do not rerun combined link add."
            )
            raise
