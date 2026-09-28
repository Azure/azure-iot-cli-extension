# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Import-free Hub selection contract. Pass nodes() as pytest arguments, never folders.

Auth loops inside unittest methods are NOT parametrized pytest nodes. Every current
definition expands to exactly one node. Collection receipts guard future expansion.
The root argument is a repository root, defaulting to this module's checkout.
"""

import ast
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "azext_iot/tests/iothub/"
SUITES = ("HubControl", "HubData")


@dataclass(frozen=True)
class Case:
    node: str
    suite: str
    group: str
    protocol: tuple
    auth: tuple
    dependencies: tuple
    phases: tuple
    exclusion: str = ""
    capability: str = "base"
    normal_skip: str = ""


def _cases(module, cls, names, suite="HubData", group="http-service",
           protocol=("https",), auth=("service:login",), dependencies=("hub",),
           phase=("entra",), exclusion="", capability="base", normal_skip=""):
    prefix = PREFIX + module + ".py::" + (cls + "::" if cls else "")
    return tuple(Case(prefix + name, suite, group, protocol, auth, dependencies,
                      phase, exclusion, capability, normal_skip) for name in names.split())


def _with(base, **changes):
    result = base.copy()
    result.update(changes)
    return result


_CONTROL = {"suite": "HubControl", "group": "resource-management", "phase": ("regular",), "auth": ("arm:entra",)}
_POLICY = _with(_CONTROL, auth=("arm:entra", "hub-policy:metadata-only"))
_WORKFLOW = _with(_CONTROL, group="arm-workflow")
_SAS = {"group": "protocol", "phase": ("sas",),
        "auth": ("service:key/login/cstring", "hub-policy:sas"),
        "normal_skip": "Existing skipif(not sas_phase_enabled()); not required Entra coverage"}
_PROTOCOL = {"group": "protocol", "protocol": ("https", "mqtt"), "auth": ("service:login", "device:key")}
_PORTABILITY = {"group": "portability"}
_PREVIEW = {"capability": "preview", "phase": ("entra", "sas"),
            "auth": ("entra:service:login", "sas:service:key/login/cstring")}
_STATE_DEPS = ("hub", "storage", "user-identity", "rbac", "eventhub", "servicebus", "cosmosdb")

# Keep SAS upload first, including on the preview child.
CASES = (
    *_cases("core/test_iothub_storage_int", "TestIoTStorage", "test_device_upload_file",
            dependencies=("hub", "storage"), **_SAS),
    *_cases("core/test_iot_messaging_int", "TestIoTHubMessaging",
            "test_device_messaging test_pyamqp_device_messaging",
            protocol=("https", "mqtt", "amqp"), **_SAS),
    *_cases("core/test_iot_messaging_int", "TestIoTHubMessaging", "test_hub_monitor_events",
            protocol=("https", "mqtt", "amqp"), dependencies=("hub", "eventhub-builtin", "consumer-groups"), **_SAS),
    *_cases("core/test_iot_messaging_int", "TestIoTHubMessaging", "test_hub_monitor_feedback",
            protocol=("https", "amqp"), **_SAS),
    *_cases("messaging/test_iothub_c2d_messages_int", "TestIoTHubC2DMessages", "test_iothub_c2d_messages_http", **_SAS),
    *_cases("configurations/test_iot_config_int", "TestIoTConfigurations",
            "test_edge_set_modules test_edge_export_modules test_edge_deployments test_device_configurations"),
    *_cases("core/test_iot_messaging_int", "TestIoTHubMessaging",
            "test_mqtt_device_simulation_with_init_reported_properties test_mqtt_device_simulation_key "
            "test_mqtt_device_direct_method_with_custom_response_status_payload test_twin_properties_update", **_PROTOCOL),
    *_cases("core/test_iot_messaging_int", "TestIoTHubMessaging", "test_mqtt_device_simulation_x509",
            **_with(_PROTOCOL, auth=("service:login", "device:x509"), dependencies=("hub", "local-certificates"))),
    *_cases("core/test_iothub_certificate_int", "TestIoTHubCertificates",
            "test_hub_certificate_lifecycle_int", **_CONTROL),
    *_cases("core/test_iothub_discovery_int", "TestIoTHubDiscovery",
            "test_iothub_discovery test_iothub_discovery_lists test_iothub_target_lists", **_POLICY),
    *_cases("core/test_iothub_discovery_int", "TestIoTHubDiscovery", "test_iothub_targets",
            **_with(_POLICY, phase=()), exclusion="Existing explicit deselection; credential-target construction only"),
    *_cases("core/test_iothub_storage_int", "TestIoTStorage", "test_storage",
            dependencies=("hub", "storage"), auth=("service:login", "storage:sas"), **_PORTABILITY),
    *_cases("core/test_iothub_storage_int", "TestIoTStorage",
            "test_system_identity_storage test_user_identity_storage",
            dependencies=("hub", "storage", "managed-identity", "rbac"),
            auth=("service:login", "storage:managed-identity", "storage:sas-url"), **_PORTABILITY),
    *_cases("core/test_iothub_utilities_int", "TestIoTHubUtilities",
            "test_iothub_generate_sas_token test_iothub_generate_sas_token_hostname_type "
            "test_iothub_connection_string_show test_iothub_connection_string_lists", **_POLICY),
    *_cases("core/test_iothub_utilities_int", "TestIoTHubUtilities", "test_iothub_init"),
    *_cases("device_stream/test_iothub_device_stream_int", "", "test_device_stream",
            **_with(_CONTROL, phase=()), exclusion="Unselected legacy ARM property inspection; not streaming traffic"),
    *_cases("devices/test_iot_edge_devices_create_int", "TestNestedEdgeHierarchy",
            "test_nested_edge_devices_create_nArgs_full test_nested_edge_devices_create_nArgs_partial "
            "test_nested_edge_devices_create_config_full test_nested_edge_devices_create_config_partial "
            "test_edge_devices_nArgs_flat_no_output test_edge_devices_create_config_overrides",
            group="edge-workflow", dependencies=("hub", "local-certificates", "filesystem")),
    *_cases("devices/test_iothub_device_twin_int", "TestIoTHubDeviceTwin",
            "test_iothub_device_twin test_iothub_device_twin_replace"),
    *_cases("devices/test_iothub_devices_int", "TestIoTHubDevices",
            "test_iothub_device_identity test_iothub_device_renew_key test_iothub_device_connection_string_show "
            "test_iothub_device_generate_sas_token test_iothub_device_hostname_type_permutations"),
    *_cases("devices/test_iothub_nested_edge_int", "TestIoTHubNestedEdge",
            "test_iothub_nested_edge test_iothub_device_scope_on_create test_iothub_edge_device_parent_scope_on_create"),
    *_cases("jobs/test_iothub_jobs_int", "TestIoTHubJobs", "test_jobs"),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_eventhub_endpoint_lifecycle",
            dependencies=("hub", "eventhub", "managed-identity", "rbac"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_servicebus_endpoint_lifecycle",
            dependencies=("hub", "servicebus", "managed-identity", "rbac"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_storage_endpoint_lifecycle",
            dependencies=("hub", "storage", "managed-identity", "rbac"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_cosmos_endpoint_lifecycle",
            dependencies=("hub", "cosmosdb", "managed-identity", "rbac", "iothub-sdk>=2.3.0"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_fabric_eventstream_endpoint_lifecycle",
            dependencies=("hub", "eventhub", "managed-identity", "rbac"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_endpoint_int", "", "test_iot_endpoint_force_delete",
            dependencies=("hub", "servicebus", "managed-identity", "rbac"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_route_int", "", "test_route_lifecycle",
            dependencies=("hub", "eventhub"), **_CONTROL),
    *_cases("message_endpoint/test_iothub_message_route_int", "", "test_route_fallback_lifecycle", **_CONTROL),
    *_cases("messaging/test_iothub_c2d_messages_int", "TestIoTHubC2DMessages",
            "test_iothub_c2d_messages", **_PROTOCOL),
    *_cases("messaging/test_iothub_c2d_messages_int", "TestIoTHubC2DMessages",
            "test_iothub_c2d_feedback", **_with(_PROTOCOL, protocol=("https", "mqtt", "amqp"))),
    *_cases("modules/test_iothub_module_twin_int", "TestIoTHubModuleTwin",
            "test_iothub_module_twin test_iothub_module_twin_replace"),
    *_cases("modules/test_iothub_modules_int", "TestIoTHubModules",
            "test_iothub_module_identity test_iothub_module_renew_key test_iothub_module_connection_string_show "
            "test_iothub_module_generate_sas_token test_iothub_module_hostname_type_permutations"),
    *_cases("state/test_hub_state_dataplane_int", "", "test_migrate_dataplane test_export_import_dataplane", **_PORTABILITY),
    *_cases("state/test_hub_state_int", "", "test_mirgate_hub_dataplane_error", **_PORTABILITY),
    *_cases("state/test_hub_state_int", "",
            "test_migrate_controlplane test_migrate_controlplane_with_create "
            "test_export_import_controlplane test_export_import_controlplane_with_create",
            dependencies=_STATE_DEPS, **_WORKFLOW),
    *_cases("state/test_hub_state_int", "", "test_custom_scenarios_controlplane",
            dependencies=("hub", "eventhub"), **_WORKFLOW),
    *_cases("state/test_hub_state_int", "", "test_export_import_migrate_missing_hubs_error",
            dependencies=("arm-resource-discovery",), **_WORKFLOW),
    *_cases("state/test_hub_state_int", "", "test_export_endpoint_resource_name_starting_with_scheme_char",
            dependencies=("hub", "servicebus"), **_WORKFLOW),
    *_cases("state/test_hub_state_int", "", "test_export_cosmosdb_endpoint_resource_name_starting_with_scheme_char",
            dependencies=("hub", "cosmosdb"), **_WORKFLOW),
    *_cases("tls13/test_tls13_int", "",
            "test_find_resource_returns_hostname_properties test_build_target_includes_hostname_fields "
            "test_connection_string_uses_gwv2_hostname", **_POLICY),
    *_cases("tls13/test_tls13_int", "", "test_gwv2_target_uses_service_hostname",
            dependencies=("hub:gwv2",), **_POLICY),
    *_cases("devices/test_hub_preview_int", "TestHubPreview", "test_identity_roundtrip", **_PREVIEW),
    *_cases("devices/test_hub_preview_int", "TestHubPreview", "test_responding_digital_twin",
            group="protocol", protocol=("https", "mqtt"),
            **_with(_PREVIEW, auth=_PREVIEW["auth"] + ("device:key",))),
    *_cases("metadata/test_hub_metadata_int", "", "test_linked_metadata_state_and_service_bulk_portability",
            group="linked-metadata", capability="preview", phase=("linked-metadata",),
            dependencies=("leased-linked-hub", "leased-unlinked-hub", "adr-namespace", "storage", "rbac"),
            auth=("service:login", "arm:entra", "storage:sas"),
            exclusion="Opt-in only: externally admitted linked metadata lease required"),
)


def phases(suite, *, linked_metadata=False):
    """Required phases; linked metadata requires an explicit separate opt-in."""
    if suite == "HubControl":
        if linked_metadata:
            raise ValueError("Linked metadata belongs to HubData.")
        return ("regular",)
    if suite == "HubData":
        return ("entra", "sas") + (("linked-metadata",) if linked_metadata else ())
    raise ValueError(f"Unknown Hub suite: {suite}")


def _capability(root):
    # Do not infer capability from optional test existence: deleting those tests
    # must fail the inventory, not silently lower preview qualification.
    tree = ast.parse((root / "azext_iot/constants.py").read_text(encoding="utf-8"))
    versions = [ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "IOTHUB_PREVIEW_API_VERSION" for t in node.targets)]
    known = {"2026-03-01-preview": "base", "2026-10-01-preview": "preview"}
    if len(versions) != 1 or versions[0] not in known:
        raise ValueError("Unknown Hub capability: review the selection contract for this API version.")
    return known[versions[0]]


def inventory(root=ROOT):
    """AST-only inventory, with no Azure/test imports or constructor execution."""
    root = Path(root).resolve()
    found = []
    for path in sorted((root / PREFIX).rglob("test*.py")):
        if not path.name.endswith("_int.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            members = node.body if isinstance(node, ast.ClassDef) else (node,)
            for member in members:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test_"):
                    cls = node.name + "::" if isinstance(node, ast.ClassDef) else ""
                    found.append(path.relative_to(root).as_posix() + "::" + cls + member.name)
    return tuple(found)


def contract(root=ROOT):
    """All branch definitions, including explicit exceptions. Unknown/missing fail closed."""
    root = Path(root).resolve()
    capability = _capability(root)
    cases = tuple(case for case in CASES if case.capability in ("base", capability))
    expected, actual = Counter(case.node for case in cases), Counter(inventory(root))
    if any(count != 1 for count in expected.values()) or actual != expected:
        raise ValueError(f"Hub inventory mismatch; missing={list((expected - actual).elements())}; "
                         f"unknown/duplicate={list((actual - expected).elements())}")
    return cases


def nodes(suite, phase, root=ROOT, *, linked_metadata=False):
    """Exact repository-relative, expanded pytest node args, in required order."""
    if phase not in phases(suite, linked_metadata=linked_metadata):
        raise ValueError(f"Phase {phase} is not enabled for {suite}.")
    selected = tuple(case.node for case in contract(root) if case.suite == suite and phase in case.phases)
    if not selected:
        raise ValueError(f"No {suite}/{phase} capability in this checkout.")
    return selected


def manifest(suite, phase, root=ROOT, *, linked_metadata=False):
    """JSON-serializable expected membership and per-case metadata for controllers."""
    expected = nodes(suite, phase, root, linked_metadata=linked_metadata)
    return {
        "schemaVersion": 1, "suite": suite, "phase": phase, "expected": list(expected),
        "cases": [asdict(case) for case in contract(root) if case.node in expected],
        "intentionalAuthOverlap": [
            case.node for case in contract(root) if "entra" in case.phases and "sas" in case.phases
        ],
    }
