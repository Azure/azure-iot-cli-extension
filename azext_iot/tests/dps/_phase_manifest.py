# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Credential-free, stdlib-only identities shared by collection, runner and final gate."""

from pathlib import Path

PHASE_NAMES = ("regular", "service-sas", "local-auth-toggle")
DPS_LIMIT = 10  # Conservative subscription default; no SDK quota-read operation is available.
REGULAR_REQUIRED_DPS_SLOTS = 4
CSR_RESOURCE_KINDS = ("csrns", "csrdps", "csrhub")
CSR_NODEIDS = frozenset(
    f"device_registration/test_iot_device_registration_int.py::test_register_and_issue_certificate_contract[{option}]"
    for option in ("default", "deadline")
)


def parse_capacity_limit(value):
    """Accept only an explicit positive integer, never booleans or numeric coercions."""
    if isinstance(value, str) and value.isascii() and value.isdecimal() and not value.startswith("0"):
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError("DPS capacity limit must be a positive base-10 integer (default: 10).")
    return value


def resource_type(kind):
    if kind in ("hub", "csrhub"):
        return "Microsoft.Devices/IotHubs"
    if kind == "csrns":
        return "Microsoft.DeviceRegistry/namespaces"
    return "Microsoft.Devices/provisioningServices"


LIFECYCLES = {
    "enrollment/test_iot_dps_enrollment_int.py": (
        "test_dps_enrollment_tpm_lifecycle", "test_dps_enrollment_x509_lifecycle",
        "test_dps_enrollment_symmetrickey_lifecycle",
    ),
    "enrollment_group/test_iot_dps_enrollment_group_int.py": (
        "test_dps_enrollment_group_x509_lifecycle", "test_dps_enrollment_group_symmetrickey_lifecycle",
        "test_dps_enrollment_twin_array",
    ),
    "device_registration/test_iot_device_registration_individual_int.py": (
        "test_dps_device_registration_symmetrickey_lifecycle", "test_dps_device_registration_x509_lifecycle",
        "test_dps_device_registration_unlinked_hub", "test_dps_device_registration_disabled_enrollment",
    ),
    "device_registration/test_iot_device_registration_group_int.py": (
        "test_dps_device_registration_symmetrickey_lifecycle", "test_dps_device_registration_x509_lifecycle",
        "test_dps_device_registration_unlinked_hub", "test_dps_device_registration_disabled_enrollment",
    ),
}

SERVICE_SAS_NODEIDS = frozenset(
    f"{module}::{name}[{auth}]"
    for module, names in LIFECYCLES.items() for name in names for auth in ("key", "cstring")
) | {"core/test_dps_linked_hub_int.py::test_linked_hub_create_keybased_then_switch_to_mi"}

REGULAR_BASE_NODEIDS = frozenset(
    f"{module}::{name}[login]" for module, names in LIFECYCLES.items() for name in names
) | {
    "core/test_dps_discovery_int.py::test_dps_discovery",
    "core/test_dps_unit_capacity_int.py::test_dps_unit_capacity_owned_lifecycle",
    "core/test_dps_discovery_int.py::test_dps_targets[key]",
    "core/test_dps_discovery_int.py::test_dps_targets[login]",
} | {
    "core/test_dps_linked_hub_int.py::" + name for name in (
        "test_linked_hub_create_auto_hostname", "test_linked_hub_create_classic_hostname",
        "test_linked_hub_create_device_hostname", "test_hub_show_returns_tls13_hostnames",
        "test_linked_hub_list_shows_hostname",
    )
} | {
    "device_registration/test_iot_device_registration_fresh_keys_int.py::"
    f"test_fresh_registration_credential[{key}-{endpoint}-{kind}]"
    for key in ("primaryKey", "secondaryKey") for endpoint in ("configured", "global")
    for kind in ("individual", "group")
}

LOCAL_AUTH_TOGGLE_NODEIDS = frozenset(
    "core/test_dps_disable_local_auth_int.py::" + name for name in (
        "test_dps_create_disable_local_auth",
        "test_dps_update_disable_local_auth",
        "test_dps_disable_local_auth_dataplane",
    )
)


def resource_kinds(phase):
    if phase == "local-auth-toggle":
        return ("dla",)
    if phase not in ("regular", "service-sas"):
        raise ValueError("Unknown DPS phase.")
    return (
        ("h", "nh", "hub", "unit1", "unitdefault", *CSR_RESOURCE_KINDS)
        if phase == "regular" else ("h", "nh", "hub")
    )


def expected_nodeids(phase):
    if phase == "local-auth-toggle":
        return LOCAL_AUTH_TOGGLE_NODEIDS
    if phase == "service-sas":
        return SERVICE_SAS_NODEIDS
    if phase != "regular":
        raise ValueError("Unknown DPS phase.")
    # Use the product's branch capability, not the existence/selection of test
    # files: deleting or filtering a modern contract test must not lower the gate.
    modern = Path(__file__).resolve().parents[2] / "dps/services/_registration_worker.py"
    extra = {
        f"device_registration/test_iot_device_registration_int.py::test_register_without_csr_deadline_contract[{option}]"
        for option in ("default", "deadline")
    } if modern.is_file() else set()
    return REGULAR_BASE_NODEIDS | extra | (CSR_NODEIDS if modern.is_file() else set())


def normalize_nodeid(nodeid):
    return nodeid.replace("\\", "/").partition("tests/dps/")[2]


def junit_nodeid(case):
    module = case.get("classname", "").partition("tests.dps.")[2].replace(".", "/")
    return module + ".py::" + case.get("name", "") if module else ""
