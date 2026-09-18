# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""One receipt-owned ADR-bound DPS/Hub/issuer, shared by the two CSR variants."""

from contextlib import contextmanager, ExitStack
import json
from shlex import quote
from time import time
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot._factory import adr_service_factory
from azext_iot.tests.adr._helpers import is_resource_not_found_error, wait_for_resource_absent
from azext_iot.tests.dps import conftest as fixtures, _phase, _phase_receipts as receipts, _phase_runtime as runtime
from azext_iot.tests.helpers import invoke_checked

ROOT_CA = "rootca"
ISSUING_CA = "issuingca"
POLICY = "leafpolicy"
LINK_OPTIONS = "--timeout 1200 --interval 10"
WAIT_OPTIONS = "--timeout 600 --interval 10"


def invoke(command):
    return invoke_checked(fixtures.cli, command, description="Owned CSR issuance command")


def _optional(command, *, dataplane=False):
    try:
        return invoke(command).as_json()
    except (HttpResponseError, CloudError, CLIError) as error:
        if (dataplane and isinstance(error, ResourceNotFoundError)
                and isinstance(error.__cause__, HttpResponseError) and error.__cause__.status_code == 404):
            return None
        if is_resource_not_found_error(error):
            return None
        raise


def find_namespace(name):
    try:
        return adr_service_factory(fixtures.cli.az_cli).namespaces.get(
            resource_group_name=fixtures.ENTITY_RG, namespace_name=name,
        )
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise


def _children(namespace):
    scope = f"--ns {namespace} -g {fixtures.ENTITY_RG}"
    return (
        ("root", "iot adr ns ca", f"-n {ROOT_CA} {scope}", f"certificateAuthorities/{ROOT_CA}",
         "--type Root"),
        ("ica", "iot adr ns ca", f"-n {ISSUING_CA} {scope}", f"certificateAuthorities/{ISSUING_CA}",
         f"--type ICA --issuer-type Microsoft --issuer-ca-name {ROOT_CA}"),
        ("policy", "iot adr ns ca policy", f"-n {POLICY} --ca-name {ISSUING_CA} {scope}",
         f"certificateAuthorities/{ISSUING_CA}/certificatePolicies/{POLICY}", "--validity-days 30"),
    )


def _require_owned(name, current):
    record = receipts._owned(name)  # pylint: disable=protected-access
    if (not record or not isinstance(current, dict) or current["id"].lower() != record["id"].lower()
            or any(current.get("tags", {}).get(key) != value for key, value in record["tags"].items())):
        raise AssertionError("CSR resource requires exact current receipt ownership.")
    return record


def _assert_linked(namespace, dps, hub):
    assert namespace["properties"]["provisioningState"] == "Succeeded"
    for section, endpoint_name, target_id in (
        ("provisioning", "dps", dps["dps"]["id"]), ("messaging", "hub", hub["hub"]["id"]),
    ):
        endpoint = namespace["properties"][section]["endpoints"][endpoint_name]
        assert endpoint["resourceId"].lower() == target_id.lower()
        assert endpoint["linkingState"] == "Succeeded"
        assert endpoint["inboundCallerIdentity"]["type"] == "SystemAssigned"


def delete_namespace(name):
    from azext_iot.tests.dps._csr_registry import cleanup_registry_devices

    current = find_namespace(name)
    if current is None:
        return
    record = _require_owned(name, current)
    cleanup_registry_devices(record)
    directory = receipts.settings()[0]
    for label, command, arguments, child_path, _ in reversed(_children(name)):
        path = directory / f"csr-child-{label}.json"
        if not path.is_file():
            continue  # No pre-create ownership claim: never delete an unowned child.
        child_record = json.loads(path.read_text(encoding="utf-8"))
        expected_id = record["id"] + "/" + child_path
        if any(child_record.get(key) != value for key, value in {
            "id": expected_id, "tags": record["tags"], "run_uid": record["run_uid"],
            "subscription": record["subscription"], "phase": record["phase"],
        }.items()):
            raise AssertionError("CSR child receipt does not match its owned namespace.")
        child = _optional(f"{command} show {arguments}")
        if child is None:
            continue
        if child["id"].lower() != expected_id.lower() or any(
            child.get("tags", {}).get(key) != value for key, value in record["tags"].items()
        ):
            raise AssertionError("Refusing CSR child deletion after an ownership change.")
        if child["properties"].get("provisioningState") != "Deleting":
            invoke(f"{command} delete {arguments} -y")
        wait_for_resource_absent(
            SimpleNamespace(cmd=invoke), f"{command} show {arguments}", timeout=600, interval=10,
        )
    if receipts.before_delete(name, find_namespace(name)):
        with runtime.owned_write(name, "DELETE"):
            invoke(f"iot adr ns delete -n {name} -g {fixtures.ENTITY_RG} -y")
        wait_for_resource_absent(
            SimpleNamespace(cmd=invoke), f"iot adr ns show -n {name} -g {fixtures.ENTITY_RG}", timeout=600, interval=10,
        )
        receipts.after_delete(name)


def _create_namespace(run_uid, kind, dps, hub):
    name = f"csr-{run_uid[:16]}"
    if find_namespace(name) is not None:
        raise AssertionError("Refusing to overwrite an existing CSR namespace.")
    receipts.before_create(name, fixtures.ENTITY_RG, run_uid, kind)
    tags = f"intTest=true runUid={run_uid} kind={kind} createdEpoch={int(time())} authPhase={_phase.REGULAR}"
    with ExitStack() as cleanup:
        cleanup.callback(delete_namespace, name)
        with runtime.owned_write(name, "PUT"):
            namespace = invoke(
                f"iot adr ns create -n {name} -g {fixtures.ENTITY_RG} --location {fixtures.ENTITY_LOCATION} "
                f"--tags {tags}"
            ).as_json()
        receipts.after_create(name, namespace)
        _require_owned(name, namespace)
        assert namespace["properties"]["provisioningState"] == "Succeeded"
        for kind_name, target in (("dps", dps), ("hub", hub)):
            identity = invoke(
                f"iot {kind_name} identity assign -n {target['name']} -g {fixtures.ENTITY_RG} --system-assigned"
            ).as_json()
            assert (identity["identity"] if kind_name == "dps" else identity)["principalId"]

        linked = invoke(
            f"iot adr ns link add --ns {name} -g {fixtures.ENTITY_RG} "
            f"--dps-endpoint-name dps --dps-id {dps['dps']['id']} --dps-system-assigned-mi "
            f"--hub-endpoint-name hub --hub-id {hub['hub']['id']} --hub-system-assigned-mi "
            f"--hub-availability Available --hub-weight 1 {LINK_OPTIONS}"
        ).as_json()
        _assert_linked(linked, dps, hub)

        record = receipts._owned(name)  # pylint: disable=protected-access
        for label, command, arguments, child_path, options in _children(name):
            if _optional(f"{command} show {arguments}") is not None:
                raise AssertionError(f"Refusing to overwrite existing CSR {label}.")
            receipts.write(f"csr-child-{label}.json", {
                "id": record["id"] + "/" + child_path, "tags": record["tags"],
            }, exclusive=True)
            invoke(f"{command} create {arguments} {options} --tags {tags}")
            invoke(f"{command} wait {arguments} {WAIT_OPTIONS}" + (" --created" if label == "policy" else ""))
            child = invoke(f"{command} show {arguments}").as_json()
            assert child["id"].lower() == (record["id"] + "/" + child_path).lower()
            assert all(child.get("tags", {}).get(key) == value for key, value in record["tags"].items())
            assert child["properties"]["provisioningState"] == "Succeeded"
            if label != "policy":
                assert child["properties"]["certificateAuthorityType"] == ("Root" if label == "root" else "ICA")
        cleanup.pop_all()
        return name, linked


@contextmanager
def provisioned_issuance(request):
    if _phase.get_phase() != _phase.REGULAR or not receipts.settings():
        raise pytest.UsageError("Self-contained CSR issuance requires the regular DPS phase controller and owned receipts.")
    run_uid = fixtures._get_run_uid(request)  # pylint: disable=protected-access
    with ExitStack() as cleanup:
        hub = fixtures._iot_hubs_provisioner(request, managed_kind="csrhub")  # pylint: disable=protected-access
        cleanup.callback(fixtures._iot_hubs_removal, hub)  # pylint: disable=protected-access
        dps = fixtures._iot_dps_provisioner(request, managed_kind="csrdps")  # pylint: disable=protected-access
        cleanup.callback(fixtures._iot_dps_removal, dps)  # pylint: disable=protected-access
        _require_owned(dps["name"], dps["dps"])
        _require_owned(hub["name"], hub["hub"])
        namespace = fixtures._shared_acquire(  # pylint: disable=protected-access
            run_uid, "csrns", lambda uid, kind: _create_namespace(uid, kind, dps, hub), find_namespace,
        )
        cleanup.callback(fixtures._shared_release, run_uid, "csrns", delete_namespace)  # pylint: disable=protected-access
        # Native ADR binding, not classic DPS linked-hub fixture setup, owns this pair.
        dps["dps"] = fixtures._find_dps_by_name(dps["name"])  # pylint: disable=protected-access
        hub["hub"] = fixtures._find_hub_by_name(hub["name"])  # pylint: disable=protected-access
        for name, current in ((dps["name"], dps["dps"]), (hub["name"], hub["hub"]), (namespace["name"], namespace)):
            _require_owned(name, current)
        _assert_linked(namespace, dps, hub)
        yield {"dps": dps, "hub": hub, "namespace": namespace["name"], "ca": ISSUING_CA, "policy": POLICY}


@contextmanager
def enrollment(resource, enrollment_id):
    from azext_iot.tests.dps._csr_registry import RegistryDeviceOwnership

    dps = resource["dps"]
    arguments = f"--dps-name {dps['name']} -g {dps['resourceGroup']} --enrollment-id {enrollment_id} --auth-type login"
    # Unique IDs in a dedicated owned DPS; absence must be authoritative before claiming an uncertain create.
    if _optional(f"iot dps enrollment show {arguments} --query registrationId", dataplane=True) is not None:
        raise AssertionError("Refusing to overwrite an existing CSR enrollment.")
    ownership = None
    try:
        projection = "{registrationId:registrationId,namespaceName:namespaceName," \
                     "certificateAuthorityName:certificateAuthorityName,certificatePolicyName:certificatePolicyName}"
        created = invoke(
            f"iot dps enrollment create {arguments} --attestation-type symmetricKey "
            f"--adr-namespace {resource['namespace']} --adr-ca-name {resource['ca']} "
            f"--adr-cert-policy-name {resource['policy']} --query {quote(projection)}"
        ).as_json()
        assert created == {
            "registrationId": enrollment_id, "namespaceName": resource["namespace"],
            "certificateAuthorityName": resource["ca"], "certificatePolicyName": resource["policy"],
        }
        ownership = RegistryDeviceOwnership(resource, enrollment_id)
        yield ownership
    finally:
        if ownership:
            ownership.cleanup()
        # Never read/log generated keys: native registration discovers the enrollment's bootstrap key internally.
        if _optional(f"iot dps enrollment registration show {arguments}", dataplane=True) is not None:
            invoke(f"iot dps enrollment registration delete {arguments}")
        if _optional(f"iot dps enrollment show {arguments} --query registrationId", dataplane=True) is not None:
            invoke(f"iot dps enrollment delete {arguments}")
