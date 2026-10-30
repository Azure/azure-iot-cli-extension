# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import re
from time import monotonic, sleep
from typing import Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    MutuallyExclusiveArgumentError,
    ResourceNotFoundError,
)
from azure.core.exceptions import DeserializationError, HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.mgmt.core.polling.arm_polling import ARMPolling
from knack.log import get_logger
from knack.util import CLIError
from msrestazure.tools import parse_resource_id

from azext_iot._factory import (
    _get_canary_credential_scopes,
    adr_iot_hub_service_factory,
    adr_iot_service_provisioning_factory,
)
from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    MessagingEndpointAvailability,
)
from azext_iot.adr.providers.base import ADRProvider, ADRResourceStateError, _ADR_LRO_TIMEOUT_SECONDS, parse_json_object
from azext_iot.adr.providers.link_helpers import (
    MI_MUTEX_MSG as _MI_MUTEX_MSG,
    build_dps_endpoint_body as _build_dps_endpoint_body,
    build_hub_endpoint_body as _build_hub_endpoint_body,
    endpoint_update_body as _endpoint_update_body,
    get_messaging_endpoints as _get_messaging_endpoints,
    get_provisioning_endpoints as _get_provisioning_endpoints,
    parse_dps_resource_id as _parse_dps_resource_id,
    parse_hub_resource_id as _parse_hub_resource_id,
    resolve_update_identity,
)
from azext_iot.adr.providers.link_persistence import (
    get_typed_endpoint,
    patch_namespace_endpoints,
)
from azext_iot.adr.providers.link_preflight import (
    TargetLookup,
    add_dps_hub_role_requirements,
    get_target,
    preflight_target,
    validate_dps_hubs,
)
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery, _normalized, validate_options
from azext_iot.adr.providers.wait import DEFAULT_WAIT_INTERVAL, link_succeeded, provisioning_succeeded
from azext_iot.adr.rbac import (
    HUB_UNLINK_WARNING, LinkRbacManager, UNLINK_WARNING, required_assignments, resolve_namespace_outbound_principal,
)
from azext_iot.adr.topology import (
    DPS_CAP_EXCEEDED_MSG,
    DPS_REQUIRED_MSG,
    HUB_CAP_EXCEEDED_MSG,
    endpoint_is_type,
    endpoint_settings_match,
    has_dps_endpoint,
    has_succeeded_dps_endpoint,
    hub_endpoint_count,
    is_failed_hub_endpoint,
    is_failed_link_endpoint,
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
        planned_hubs: Optional[dict] = None,
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
        if link_type == "dps":
            validate_dps_hubs(namespace, target, planned_hubs)
        add_dps_hub_role_requirements(
            requests[0], namespace,
            lambda resource_id: self._get_target(_parse_dps_resource_id(resource_id), _DPS_TARGET),
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

    def _remove_endpoint(
        self, endpoint_name, namespace_name, resource_group_name, section, endpoint_type, display_name,
        no_wait=False, no_rbac_check=False, grant_reader=False,
    ):
        if no_rbac_check and grant_reader:
            raise MutuallyExclusiveArgumentError(
                "--grant-reader cannot be combined with --no-rbac-check."
            )
        logger.warning("%s", HUB_UNLINK_WARNING if section == "messaging" else UNLINK_WARNING)
        namespace, etag = self.client.namespaces.get(
            resource_group_name=resource_group_name, namespace_name=namespace_name, retry_total=0,
            cls=lambda response, resource, _: (resource, response.http_response.headers.get("ETag")),
        )
        if isinstance(etag, str):
            etag = etag.strip(" \t")
        # If-Match requires a strong entity-tag, not a weak validator.
        if not isinstance(etag, str) or re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag) is None:
            raise AzureResponseError(
                "The namespace response did not include a usable ETag header (a strong, quoted entity-tag is required). "
                "Endpoint removal was not submitted because concurrent changes cannot be protected."
            )
        endpoint = self._get_typed_endpoint(namespace, section, endpoint_name, endpoint_type, namespace_name, display_name)
        if not no_rbac_check:
            self._check_unlink_permissions(namespace, endpoint, section, grant_reader=grant_reader)
        try:
            poller = self.client.namespaces.begin_update(
                resource_group_name=resource_group_name, namespace_name=namespace_name,
                properties={"properties": {section: {"endpoints": {endpoint_name: None}}}},
                headers={"If-Match": etag}, retry_total=0,
                # Suppress mutation retries without suppressing the poller's idempotent GET retries.
                polling=ARMPolling(
                    timeout=self.client._config.polling_interval,
                    path_format_arguments={"endpoint": self.client._config.base_url},
                ),
            )
            return self._wait(
                poller,
                f"Removing {display_name} endpoint '{endpoint_name}' from namespace {namespace_name}...",
                no_wait=no_wait,
                failure_target=(section, endpoint_name),
            )
        except HttpResponseError as error:
            if error.status_code == 412:
                logger.warning(
                    "Namespace '%s' changed before endpoint removal (HTTP 412). "
                    "Inspect the namespace with 'az iot adr ns show' and rerun the remove command.",
                    namespace_name,
                )
            raise

    def _check_unlink_permissions(self, namespace, endpoint, section, *, grant_reader=False):
        state = endpoint.get("linkingState")
        if state in ("LinkedResourceDeleted", "Failed"):
            logger.info("Skipping permission check for endpoint linkingState '%s'.", state)
            return
        if state != "Succeeded":
            logger.warning(
                "Endpoint linkingState is '%s'; permission preflight is unavailable for this state. "
                "Continuing without changing role assignments; ADR decides whether removal is allowed.",
                state,
            )
            return
        try:
            resource_id = endpoint.get("resourceId")
            if not isinstance(resource_id, str):
                raise AzureResponseError("The linked endpoint did not include a string resourceId.")
            parsed_id = parse_resource_id(resource_id.strip())
            if not all(parsed_id.get(field) for field in ("subscription", "resource_group", "name")):
                raise AzureResponseError("The linked endpoint resourceId must be a resource-group-scoped ARM resource ID.")
            outbound = namespace["properties"].get("outboundIdentity")
            if outbound is None:
                outbound = {}
            if not isinstance(outbound, dict):
                raise AzureResponseError("The namespace outboundIdentity must be an object.")
            if str(outbound.get("type") or "SystemAssigned").casefold() == "userassigned":
                if not isinstance(outbound.get("userAssignedIdentity"), str):
                    raise AzureResponseError("The outbound userAssignedIdentity must be a string resource ID.")
                identity = namespace.get("identity") or {}
                if not isinstance(identity, dict):
                    raise AzureResponseError("The namespace identity must be an object.")
                attached = identity.get("userAssignedIdentities") or {}
                if not isinstance(attached, dict) or any(
                    not isinstance(identity_id, str) or (details is not None and not isinstance(details, dict))
                    for identity_id, details in attached.items()
                ):
                    raise AzureResponseError("The attached user-assigned identity metadata is malformed.")
            parse_target = {
                "messaging": _parse_hub_resource_id,
                "provisioning": _parse_dps_resource_id,
            }[section]
            target = parse_target(resource_id)
            self._rbac_manager().check_unlink_read_access(
                resolve_namespace_outbound_principal(namespace),
                f"/subscriptions/{target['subscription_id']}/resourceGroups/{target['resource_group_name']}",
                grant_reader=grant_reader,
            )
        except (CLIError, HttpResponseError, ServiceRequestError, ServiceResponseError, DeserializationError) as error:
            if grant_reader:
                raise AzureResponseError(
                    "Reader setup could not be completed; endpoint removal was not submitted. "
                    "Any role assignments already created are retained. "
                    f"Detail: {error}"
                ) from error
            logger.warning(
                "Could not verify the namespace outbound identity's read access: %s "
                "Continuing without changing role assignments; ADR may reject removal. "
                "Use --no-rbac-check to skip this advisory check.",
                error,
            )

    def hub_remove(
        self, endpoint_name: str, namespace_name: str, resource_group_name: str,
        no_wait: bool = False, no_rbac_check: bool = False, grant_reader: bool = False,
    ):
        return self._remove_endpoint(
            endpoint_name, namespace_name, resource_group_name, "messaging", IOT_HUB_ENDPOINT_TYPE, "IoT Hub",
            no_wait=no_wait, no_rbac_check=no_rbac_check, grant_reader=grant_reader,
        )

    def dps_remove(
        self, endpoint_name: str, namespace_name: str, resource_group_name: str,
        no_wait: bool = False, no_rbac_check: bool = False, grant_reader: bool = False,
    ):
        return self._remove_endpoint(
            endpoint_name, namespace_name, resource_group_name, "provisioning", DPS_ENDPOINT_TYPE, "DPS",
            no_wait=no_wait, no_rbac_check=no_rbac_check, grant_reader=grant_reader,
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
            add_dps_hub_role_requirements(
                requests[0], current,
                lambda resource_id: deadline.call(
                    self._get_target, _parse_dps_resource_id(resource_id), _DPS_TARGET,
                ),
            )
            deadline.remaining()
            if requests != original_requests:
                raise AzureResponseError("Link preflight principal or scope changed; no recovery PATCH submitted.")
            self._rbac_manager().verify_many(requests, guard=deadline.remaining)

        required = [entry for request in original_requests or [] for entry in required_assignments(request)]
        created = set(self._rbac.created) if self._rbac else set()
        return LinkRecovery(
            self, namespace, section, name, expected, budget, verify,
            authorization_request=original_requests[0] if original_requests and len(original_requests) == 1 else None,
            recent_grants=any(rule.principal != "dps" and assignment in created for rule, assignment in required),
            recent_inbound_grant=any(
                rule.principal == "linked" and rule.scope == "namespace" and assignment in created
                for rule, assignment in required
            ),
        ).run(
            submit=lambda body: self._patch_endpoints(
                namespace_name, resource_group_name, section, {name: body}, status_message, no_wait=True,
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
        if not has_succeeded_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_REQUIRED_MSG)
        if hub_endpoint_count(existing) >= 10:
            raise ArgumentUsageError(HUB_CAP_EXCEEDED_MSG)
        if endpoint_name in _get_messaging_endpoints(existing):
            raise ArgumentUsageError(
                f"Messaging endpoint '{endpoint_name}' already exists on namespace "
                f"'{namespace_name}' and cannot be repointed by link hub add. "
                "Use 'az iot adr ns link hub update' for an existing Hub link, "
                "or choose an unused endpoint name. Use 'az iot adr ns link hub remove' to remove it; "
                "delete the target first only for a Succeeded link."
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
        availability: Optional[str] = None,
        allocation_weight: Optional[int] = None,
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
        if is_failed_hub_endpoint(endpoint) and not has_succeeded_dps_endpoint(existing):
            raise ArgumentUsageError(DPS_REQUIRED_MSG)

        settings = {}
        if availability is not None:
            settings["availability"] = availability
        if allocation_weight is not None:
            settings["allocationWeight"] = allocation_weight
        if settings and not mi_system_assigned and not mi_user_assigned and endpoint.get("linkingState") == "Succeeded":
            return self._patch_endpoints(
                namespace_name, resource_group_name, "messaging", {endpoint_name: {"provisioning": settings}},
                f"Updating provisioning settings for Hub '{endpoint_name}'...", **kwargs,
            )
        inbound_identity = resolve_update_identity(endpoint, mi_system_assigned, mi_user_assigned)

        # Identity changes and Failed retries retain the endpoint's saved writable settings.
        endpoint_patch = _endpoint_update_body(
            endpoint,
            inbound_identity=inbound_identity,
        )
        if settings:
            endpoint_patch["provisioning"] = {**(endpoint_patch.get("provisioning") or {}), **settings}
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
                        "authoritative ADR relationship. The classic list is read-only while linked; "
                        "use 'az iot adr ns link hub update --availability ... --weight ...' "
                        "to change namespace allocation settings.",
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
                "Use 'az iot adr ns link dps remove' to remove it; delete the target first only for a Succeeded link."
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

    # Combined DPS-first link add

    def _patch_link_batch(self, namespace_name, resource_group_name, sections, *, no_wait=False,
                          timeout_sec=_ADR_LRO_TIMEOUT_SECONDS, wait_sec=DEFAULT_WAIT_INTERVAL):
        budget = LinkDeadline(timeout_sec, wait_sec, clock=monotonic, sleeper=sleep)
        message = f"Updating selected links on namespace {namespace_name}..."
        try:
            poller = budget.call(
                self.client.namespaces.begin_update,
                resource_group_name=resource_group_name, namespace_name=namespace_name,
                properties={"properties": sections}, retry_total=0,
            )
            if no_wait:
                return self._wait(poller, message, no_wait=True)
            budget.call(
                self._wait, poller, message, timeout_sec=budget.remaining(), wait_sec=wait_sec,
                deadline_guard=budget.remaining,
            )
            while True:
                current = budget.call(self._get_namespace, namespace_name, resource_group_name)
                ready = provisioning_succeeded(current)
                if ready.failure:
                    raise ADRResourceStateError(self._format_failure("Failed", current, None), current)
                complete = ready.complete
                for section, group in sections.items():
                    endpoints = (current["properties"].get(section) or {}).get("endpoints") or {}
                    for name, expected in group["endpoints"].items():
                        endpoint = endpoints.get(name)
                        evaluation = link_succeeded(endpoint or {}, label=f"Link '{name}'")
                        if evaluation.failure:
                            raise ADRResourceStateError(evaluation.failure, current)
                        complete = complete and evaluation.complete
                        if evaluation.complete and not endpoint_settings_match(
                            _normalized(endpoint), _normalized(expected),
                        ):
                            raise AzureResponseError(f"Link '{name}' settings changed while waiting; stopped.")
                if complete:
                    return current
                budget.pause(wait_sec)
        except (CLIError, HttpResponseError, ServiceRequestError, ServiceResponseError):
            logger.warning(
                "The selected links did not complete; the submitted operation may still be running. "
                "Inspect 'az iot adr ns show'; use 'az iot adr ns link wait' for pending links. "
                "Only after observing Failed endpoints, use 'az iot adr ns link update' with the Failed DPS "
                "and required Failed Hub endpoint names to retry together. "
                "Do not rerun add for existing endpoints. No rollback was attempted."
            )
            raise

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
        hub_endpoints=None,
        **kwargs,
    ):
        """Batch brownfield/multi-Hub plans; retain DPS-first sequencing for a new single Hub."""
        timeout = kwargs.setdefault("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS)
        interval = kwargs.setdefault("wait_sec", DEFAULT_WAIT_INTERVAL)
        validate_options(timeout, interval)
        # Validate both ARM IDs up front; reject overflow/collisions before
        # composing the body or touching RBAC.
        parsed_dps = _parse_dps_resource_id(dps_resource_id)
        _parse_hub_resource_id(hub_resource_id)
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
        hubs = {hub_endpoint_name: hub_body}
        if hub_endpoints is not None:
            for name, value in parse_json_object(hub_endpoints, "--hub-endpoints").items():
                if not name or name in hubs or name in _get_messaging_endpoints(existing):
                    raise ArgumentUsageError(f"Hub endpoint name '{name}' is empty or already in use.")
                if not isinstance(value, dict):
                    raise ArgumentUsageError("Each --hub-endpoints value must be a JSON object.")
                value = parse_json_object(
                    value, "--hub-endpoints", allowed_keys={"resourceId", "inboundCallerIdentity", "provisioning"},
                    required_keys={"resourceId"},
                )
                for field in ("inboundCallerIdentity", "provisioning"):
                    if field in value and not isinstance(value[field], dict):
                        raise ArgumentUsageError(f"Hub {field} must be a JSON object.")
                if not isinstance(value["resourceId"], str):
                    raise ArgumentUsageError("Each --hub-endpoints resourceId must be a string ARM resource ID.")
                _parse_hub_resource_id(value["resourceId"])
                identity = parse_json_object(
                    value.get("inboundCallerIdentity", {}), "inboundCallerIdentity",
                    allowed_keys={"type", "userAssignedIdentity"},
                )
                if identity and identity.get("type") not in ("SystemAssigned", "UserAssigned"):
                    raise ArgumentUsageError("Hub inboundCallerIdentity.type must be SystemAssigned or UserAssigned.")
                if "userAssignedIdentity" in identity and not isinstance(identity["userAssignedIdentity"], str):
                    raise ArgumentUsageError("Hub userAssignedIdentity must be a string ARM resource ID.")
                if (identity.get("type") == "UserAssigned") != bool(identity.get("userAssignedIdentity")):
                    raise ArgumentUsageError("Only UserAssigned inbound identities require userAssignedIdentity.")
                provisioning = parse_json_object(
                    value.get("provisioning", {}), "provisioning", allowed_keys={"availability", "allocationWeight"},
                )
                if "availability" in provisioning and provisioning["availability"] not in [
                    choice.value for choice in MessagingEndpointAvailability
                ]:
                    raise ArgumentUsageError("Hub provisioning.availability must be Available or Disabled.")
                if "allocationWeight" in provisioning and type(provisioning["allocationWeight"]) is not int:
                    raise ArgumentUsageError("Hub provisioning.allocationWeight must be an integer.")
                hubs[name] = _build_hub_endpoint_body(
                    value["resourceId"], identity.get("type") == "SystemAssigned",
                    identity.get("userAssignedIdentity"), provisioning.get("availability"),
                    provisioning.get("allocationWeight"),
                )
        if hub_endpoint_count(existing) + len(hubs) > 10:
            raise ArgumentUsageError(HUB_CAP_EXCEEDED_MSG)
        if len({body["resourceId"].casefold() for body in hubs.values()}) != len(hubs):
            raise ArgumentUsageError("Each Hub resource may appear only once in the link plan.")
        rbac_requests = []
        dps = self._preflight_link(
            link_type="dps",
            namespace=existing,
            target_resource_id=dps_resource_id,
            inbound_identity=dps_body.get("inboundCallerIdentity"),
            parsed=parsed_dps,
            strategy=_DPS_TARGET,
            rbac_requests=rbac_requests,
            planned_hubs=hubs,
        )
        hub_plan = deepcopy(existing)
        properties = hub_plan.get("properties") or {}
        provisioning = properties.get("provisioning") or {}
        provisioning["endpoints"] = {**(provisioning.get("endpoints") or {}), dps_endpoint_name: dps_body}
        properties["provisioning"] = provisioning
        hub_plan["properties"] = properties
        batch = len(hubs) > 1 or bool((dps.get("properties") or {}).get("iotHubs"))
        if batch:
            properties["messaging"] = {"endpoints": {**_get_messaging_endpoints(existing), **hubs}}
            add_dps_hub_role_requirements(rbac_requests[0], hub_plan, None)
        for body in hubs.values():
            self._preflight_link(
                link_type="hub", namespace=hub_plan, target_resource_id=body["resourceId"],
                inbound_identity=body.get("inboundCallerIdentity"), parsed=_parse_hub_resource_id(body["resourceId"]),
                strategy=_HUB_TARGET, rbac_requests=rbac_requests,
            )
        self._rbac_manager().ensure_many(rbac_requests)
        if batch:
            return self._patch_link_batch(
                namespace_name, resource_group_name,
                {"provisioning": {"endpoints": {dps_endpoint_name: dps_body}}, "messaging": {"endpoints": hubs}},
                **kwargs,
            )

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

    def link_update(
        self, namespace_name, resource_group_name, dps_endpoint_name=None, hub_endpoint_names=None, **kwargs,
    ):
        validate_options(kwargs.get("timeout_sec", _ADR_LRO_TIMEOUT_SECONDS), kwargs.get("wait_sec", DEFAULT_WAIT_INTERVAL))
        if not dps_endpoint_name and not hub_endpoint_names:
            raise ArgumentUsageError("Select --dps-endpoint-name and/or --hub-endpoint-name to retry.")
        existing = self._get_namespace(namespace_name, resource_group_name)
        sections = {}
        for kind, section, names, endpoint_type in (
            ("dps", "provisioning", [dps_endpoint_name] if dps_endpoint_name else [], DPS_ENDPOINT_TYPE),
            ("hub", "messaging", hub_endpoint_names or [], IOT_HUB_ENDPOINT_TYPE),
        ):
            for name in names:
                endpoint = self._get_typed_endpoint(existing, section, name, endpoint_type, namespace_name, kind)
                if not is_failed_link_endpoint(endpoint):
                    raise ArgumentUsageError(f"Link '{name}' is not Failed; select only endpoints to retry.")
                sections.setdefault(section, {"endpoints": {}})["endpoints"][name] = _endpoint_update_body(endpoint)
        hubs = sections.get("messaging", {}).get("endpoints", {})
        dps = sections.get("provisioning", {}).get("endpoints", {})
        if hubs and not dps and not has_succeeded_dps_endpoint(existing):
            raise ArgumentUsageError("Select the Failed DPS with --dps-endpoint-name to retry it with its Hubs.")
        requests = []
        for kind, group, parser, strategy in (
            ("dps", dps, _parse_dps_resource_id, _DPS_TARGET),
            ("hub", hubs, _parse_hub_resource_id, _HUB_TARGET),
        ):
            for body in group.values():
                self._preflight_link(
                    kind, existing, body["resourceId"], body.get("inboundCallerIdentity"),
                    parser(body["resourceId"]), strategy, rbac_requests=requests, planned_hubs=hubs,
                )
        self._rbac_manager().ensure_many(requests)
        return self._patch_link_batch(namespace_name, resource_group_name, sections, **kwargs)
