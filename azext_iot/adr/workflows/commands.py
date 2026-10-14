# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
from typing import List, Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    CLIError,
    ResourceNotFoundError,
)
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.adr.workflows.input import (
    build_setup_request,
    check_script_destination,
    resolve_scope_inputs,
    write_receipt_file,
    write_script_file,
)
from azext_iot.adr.workflows.namespace import NamespaceWorkflow
from azext_iot.adr.workflows.rendering import (
    RenderedWorkflowError,
    WorkflowRenderer,
)
from azext_iot.adr.workflows.services import WorkflowServices, is_not_found


def _structured_output_requested(cmd):
    del cmd
    arguments = sys.argv[1:]
    explicit_output = any(
        argument in {"-o", "--output"}
        or argument.startswith("--output=")
        for argument in arguments
    )
    stdout = getattr(sys, "__stdout__", None) or sys.stdout
    return explicit_output or not stdout.isatty()


def _plan_script_commands(items):
    """Commands for planned changes; refuse plans whose commands depend on unapplied prerequisites."""
    if any(
        item["action"] != "role" and item["state"] in {"Planned", "Manual"} and not item.get("command")
        for item in items
    ):
        raise ArgumentUsageError(
            "The plan contains operations whose final command cannot "
            "be resolved yet. Apply prerequisites or rerun setup "
            "before using --output-script."
        )
    return [item["command"] for item in items if item["state"] in {"Planned", "Manual"} and item.get("command")]


def _check_plan_script(path, items):
    """Everything --output-script needs, checked before approval; writes nothing."""
    _plan_script_commands(items)
    check_script_destination(path)


def _write_plan_script(path, items):
    write_script_file(path, _plan_script_commands(items))


def _persist_receipt(result):
    try:
        result["receipt"] = write_receipt_file(result)
    except OSError as error:
        result["receiptError"] = str(error)
    return result


def _validate_subscription(services, renderer, subscription_id):
    renderer.phase("Subscription")
    renderer.busy("validating subscription…")
    subscription = services.show_subscription(subscription_id)
    if subscription is None:
        raise ResourceNotFoundError(
            f"Subscription '{subscription_id}' was not found or is no "
            "longer accessible."
        )
    renderer.input_status(
        "Subscription",
        str(
            subscription.get("displayName")
            or subscription.get("display_name")
            or subscription_id
        ),
        "Satisfied",
        f"{subscription_id} · {subscription.get('state') or 'Found'}",
    )


def _validate_resource_group(services, renderer, resource_group_name):
    renderer.phase("Resource group")
    renderer.busy(f"validating resource group {resource_group_name}…")
    resource_group = services.show_resource_group(resource_group_name)
    if resource_group is None:
        raise ResourceNotFoundError(
            f"Resource group '{resource_group_name}' was not found in the "
            "active subscription."
        )
    renderer.input_status(
        "Resource group",
        resource_group_name,
        "Satisfied",
        " · ".join(
            value
            for value in (
                "Found",
                resource_group.get("location"),
            )
            if value
        ),
    )


def _validate_namespace(
    services,
    renderer,
    namespace_name,
    resource_group_name,
):
    renderer.phase("Namespace")
    renderer.busy(f"looking up namespace {namespace_name}…")
    namespace = services.show_namespace(
        namespace_name, resource_group_name
    )
    if namespace is None:
        renderer.input_status(
            "Namespace",
            namespace_name,
            "Planned",
            "Not found; setup will create it.",
        )
        return
    renderer.input_status(
        "Namespace",
        namespace_name,
        "Satisfied",
        " · ".join(
            value
            for value in (
                "Found",
                namespace.get("location"),
                (
                    namespace.get("properties", {}).get(
                        "provisioningState"
                    )
                    if isinstance(namespace.get("properties"), dict)
                    else None
                ),
                (
                    namespace.get("systemData", {}).get("createdBy")
                    if isinstance(namespace.get("systemData"), dict)
                    else None
                ),
            )
            if value
        ),
    )


def _validate_endpoint_resource(
    services,
    renderer,
    endpoint,
    allow_missing,
):
    renderer.phase("Configuration")
    renderer.busy(
        f"validating {endpoint.kind} {endpoint.endpoint_name}…"
    )
    try:
        resource = services.resolve_resource(endpoint)
    except Exception as error:
        if (
            allow_missing
            and endpoint.kind == "software-updates"
            and is_not_found(error)
        ):
            services.validate_update_instance_creation(endpoint)
            renderer.input_status(
                "Update Instance",
                endpoint.resource_id,
                "Planned",
                "Not found; setup will create it.",
            )
            return None
        raise
    labels = {
        "dps": "DPS",
        "hub": "IoT Hub",
        "software-updates": "Update Instance",
    }
    renderer.input_status(
        labels[endpoint.kind],
        endpoint.resource_id,
        "Satisfied",
        _resource_metadata(resource),
    )
    return resource


def _resource_metadata(resource):
    properties = resource.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    sku = resource.get("sku", {})
    if not isinstance(sku, dict):
        sku = {}
    linked_hubs = properties.get("iotHubs") or []
    return " · ".join(
        str(value)
        for value in (
            resource.get("location"),
            sku.get("name"),
            properties.get("provisioningState"),
            (
                f"{len(linked_hubs)} linked hub(s)"
                if linked_hubs
                else None
            ),
            "Found",
        )
        if value
    )


def _validate_endpoint_identity(
    services,
    renderer,
    endpoint,
    resource,
):
    labels = {
        "dps": "DPS",
        "hub": "IoT Hub",
        "software-updates": "Update Instance",
    }
    renderer.busy(
        f"validating {labels[endpoint.kind]} identity…"
    )
    services.principal_for_identity(
        endpoint.identity_type,
        endpoint.user_assigned_identity,
        resource,
    )
    renderer.input_status(
        f"{labels[endpoint.kind]} identity",
        endpoint.user_assigned_identity or "SystemAssigned",
        "Satisfied",
        "Ready",
    )


def _validate_identity(services, renderer, resource_id):
    renderer.phase("Configuration")
    renderer.busy("validating user-assigned identity…")
    services.resolve_uami(resource_id)
    renderer.input_status(
        "Outbound identity",
        resource_id,
        "Satisfied",
        "Found",
    )


def _prepare_namespace_setup(
    renderer,
    services,
    subscription_id,
    arguments,
):
    request = build_setup_request(
        namespace_name=arguments["namespace_name"],
        resource_group_name=arguments["resource_group_name"],
        subscription_id=subscription_id,
        location=arguments["location"],
        tags=arguments.get("tags"),
        namespace_outbound_identity=arguments[
            "namespace_outbound_identity"
        ],
        dps=arguments["dps"],
        hubs=arguments["hubs"],
        software_updates=arguments["software_updates"],
        complete_connectivity=arguments["complete_connectivity"],
        config=arguments["config"],
        validate_resource_group=lambda value: _validate_resource_group(
            services, renderer, value
        ),
        validate_namespace=lambda name, group: _validate_namespace(
            services,
            renderer,
            name,
            group,
        ),
        validate_endpoint_resource=lambda endpoint, allow_missing: (
            _validate_endpoint_resource(
                services,
                renderer,
                endpoint,
                allow_missing,
            )
        ),
        validate_endpoint_identity=lambda endpoint, resource: (
            _validate_endpoint_identity(
                services,
                renderer,
                endpoint,
                resource,
            )
        ),
        validate_identity=lambda resource_id: _validate_identity(
            services,
            renderer,
            resource_id,
        ),
    )
    renderer.phase("Configuration")
    workflow = NamespaceWorkflow(services)
    plan, items = workflow.plan_setup(request)
    renderer.plan(plan)
    return request, plan, items


def adr_namespace_check(
    cmd,
    namespace_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    no_input: bool = False,
    plain: bool = False,
):
    del no_input
    namespace_name = (namespace_name or "").strip()
    resource_group_name = (resource_group_name or "").strip()
    if not namespace_name or not resource_group_name:
        raise ArgumentUsageError(
            "--name and --resource-group are required. Check never prompts for input."
        )
    subscription_id = get_subscription_id(cmd.cli_ctx)
    namespace_name, resource_group_name = resolve_scope_inputs(
        namespace_name,
        resource_group_name,
        subscription_id=subscription_id,
    )
    renderer = WorkflowRenderer(
        "Namespace check",
        plain=plain or _structured_output_requested(cmd),
    )
    renderer.header(
        subscription_id, resource_group_name, namespace_name
    )
    try:
        result = NamespaceWorkflow(WorkflowServices(cmd)).check(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )
    except Exception as error:
        raise RenderedWorkflowError(error, renderer) from error
    if result["state"] in {"Blocked", "Failed"}:
        blockers = [
            item
            for item in result["items"]
            if item["state"] in {"Blocked", "Failed"}
        ]
        details = "\n".join(
            f"- {item['target']}: {item.get('message', item['state'])}"
            for item in blockers
        )
        error = CLIError(f"Namespace check found blockers:\n{details}")
        raise RenderedWorkflowError(
            CLIError("Namespace check found blockers."),
            renderer,
            result,
        ) from error
    renderer.receipt(result)
    return result


def adr_namespace_setup(
    cmd,
    namespace_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    location: Optional[str] = None,
    tags: Optional[dict] = None,
    namespace_outbound_identity: Optional[str] = None,
    dps: Optional[List[str]] = None,
    hubs: Optional[List[List[str]]] = None,
    software_updates: Optional[List[str]] = None,
    complete_connectivity: bool = False,
    config: Optional[str] = None,
    no_input: bool = False,
    plan_only: bool = False,
    output_script: Optional[str] = None,
    yes: bool = False,
    plain: bool = False,
):
    if config:
        from azext_iot.adr.workflows.configuration import load_config

        config = load_config(config)
    if sys.stdin.isatty() and sys.stderr.isatty() and not (no_input or yes):
        # Guided: prompts and progress on stderr, so structured stdout stays clean.
        from azext_iot.adr.workflows.guided import run_guided_setup

        result = run_guided_setup(
            WorkflowServices(cmd), get_subscription_id(cmd.cli_ctx), config=config, plain=plain,
            plan_only=plan_only, output_script=output_script, persist=_persist_receipt,
            write_script=_write_plan_script, check_script=_check_plan_script,
            arguments={
                "namespace_name": namespace_name, "resource_group_name": resource_group_name,
                "location": location, "tags": tags, "namespace_outbound_identity": namespace_outbound_identity,
                "dps": dps, "hubs": hubs, "software_updates": software_updates,
                "complete_connectivity": complete_connectivity,
            },
        )
        if result and not plan_only and result["state"] in {"Blocked", "Failed", "Stopped"}:
            raise CLIError("Setup did not complete. Rerun setup to re-read Azure and resume.")
        return result
    # Unattended: --yes, --no-input or no terminal. Never prompts; nothing is created unless requested.
    subscription_id = get_subscription_id(cmd.cli_ctx)
    renderer = WorkflowRenderer(
        "Namespace setup",
        plain=(
            plain
            or bool(config)
            or _structured_output_requested(cmd)
        ),
    )
    renderer.header(
        subscription_id, resource_group_name, namespace_name
    )
    renderer.phase("Subscription")
    services = WorkflowServices(cmd)
    try:
        renderer.account(services.account_context())
        _validate_subscription(services, renderer, subscription_id)
        request, plan, _ = _prepare_namespace_setup(
            renderer,
            services,
            subscription_id,
            {
                "namespace_name": namespace_name,
                "resource_group_name": resource_group_name,
                "location": location,
                "tags": tags,
                "namespace_outbound_identity": namespace_outbound_identity,
                "dps": dps,
                "hubs": hubs,
                "software_updates": software_updates,
                "complete_connectivity": complete_connectivity,
                "config": config,
            },
        )
    except Exception as error:
        raise RenderedWorkflowError(error, renderer) from error
    if output_script:
        try:
            _write_plan_script(output_script, plan["items"])
        except ArgumentUsageError:
            renderer.close()
            raise
    if plan_only:
        renderer.close()
        return plan
    if plan["state"] == "Blocked":
        error = ArgumentUsageError(
            "Namespace setup is blocked. Resolve the reported items and "
            "rerun."
        )
        raise RenderedWorkflowError(error, renderer, plan) from error
    renderer.phase("Apply")
    if not yes:
        renderer.close()
        raise ArgumentUsageError(
            "Namespace setup requires confirmation. Pass --yes in a "
            "non-interactive environment."
        )
    renderer.confirmed()
    try:
        with renderer.execution() as progress:
            result = NamespaceWorkflow(
                services, progress=progress
            ).setup(request)
    except Exception as error:
        failure_result = getattr(error, "result", plan)
        if hasattr(error, "result"):
            failure_result["keptActions"] = 0
            _persist_receipt(failure_result)
        raise RenderedWorkflowError(
            error,
            renderer,
            failure_result,
        ) from error
    if result["state"] in {"Blocked", "Failed"}:
        _persist_receipt(result)
        error = CLIError(
            "Namespace setup completed with readiness blockers."
        )
        raise RenderedWorkflowError(error, renderer, result) from error
    renderer.phase("Verify")
    _persist_receipt(result)
    renderer.receipt(result)
    return result
