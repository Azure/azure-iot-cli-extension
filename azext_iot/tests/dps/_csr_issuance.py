# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""One receipt-owned ADR-bound DPS/Hub/issuer, shared by registration and CSR variants."""

from contextlib import contextmanager, ExitStack
import json
from shlex import quote
from time import monotonic, sleep, time
from uuid import UUID, uuid4

import pytest
from azure.cli.command_modules.role._client_factory import _auth_client_factory
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot._factory import adr_service_factory
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.adr._helpers import is_resource_not_found_error, wait_for_condition
from azext_iot.tests.dps import conftest as fixtures, _phase, _phase_receipts as receipts, _phase_runtime as runtime
from azext_iot.tests.helpers import invoke_checked, role_assignment_create_command, role_assignment_create_scope

ROOT_CA = "rootca"
ISSUING_CA = "issuingca"
POLICY = "leafpolicy"
LINK_OPTIONS = "--timeout 1200 --interval 10"
WAIT_OPTIONS = "--timeout 600 --interval 10"
NAMESPACE_ROLE_RECEIPT = "csr-namespace-self-role.json"
NAMESPACE_ROLE_PROPAGATION_SECONDS = 60
# Built-in Azure Device Registry Administrator: Microsoft.DeviceRegistry/*
# includes Microsoft.DeviceRegistry/namespaces/registryDevices/write (39640174).
NAMESPACE_ROLE_DEFINITION_ID = "12675fd7-7f59-493f-9201-f7944860a2f1"


def invoke(command):
    # Knack retains a failed command's --query handler; never share it with the next command.
    cli = EmbeddedCLI(cli_ctx=fixtures.cli.az_cli)
    return invoke_checked(cli, command, description="Owned CSR issuance command")


def _optional(command, *, dataplane=False):
    """DPS data-plane probes preserve their translated service errors."""
    try:
        return invoke(command).as_json()
    except (HttpResponseError, CloudError, CLIError) as error:
        if (dataplane and isinstance(error, ResourceNotFoundError)
                and isinstance(error.__cause__, HttpResponseError)
                and getattr(error.__cause__, "status_code") == 404):
            return None
        if is_resource_not_found_error(error):
            return None
        raise


def _arm_get(getter, **scope):
    """Avoid CLI ARM show, which converts an expected SDK 404 into SystemExit(3)."""
    try:
        resource = getter(**scope)
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise
    if not isinstance(resource, dict) or not isinstance(resource.get("id"), str) or not resource["id"]:
        raise AssertionError("Malformed ARM GET response cannot establish resource presence or absence.")
    return resource


def _arm_client():
    config = receipts.settings()
    if config is None:
        raise AssertionError("CSR ARM probes require the receipt-owned subscription and resource group.")
    return adr_service_factory(fixtures.cli.az_cli, subscription_id=config[2]), config[3]


def find_namespace(name):
    client, group = _arm_client()
    return _arm_get(client.namespaces.get, resource_group_name=group, namespace_name=name)


def find_child(namespace, label):
    client, group = _arm_client()
    scope = {"resource_group_name": group, "namespace_name": namespace}
    if label == "policy":
        return _arm_get(
            client.certificate_policies.get, **scope,
            certificate_authority_name=ISSUING_CA, certificate_policy_name=POLICY,
        )
    return _arm_get(
        client.certificate_authorities.get, **scope,
        certificate_authority_name={"root": ROOT_CA, "ica": ISSUING_CA}[label],
    )


def _wait_arm_absent(fetch, description):
    wait_for_condition(
        fetch, lambda resource: resource is None, description=description,
        timeout=600, interval=10, is_retryable_error=lambda _error: False,
    )


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


def _namespace_sami(namespace):
    identity = namespace["identity"]
    assert "systemassigned" in {kind.strip().casefold() for kind in identity["type"].split(",")}
    return str(UUID(identity["principalId"]))


def _namespace_role_binding(record, principal):
    return {
        "scope": record["id"], "principalId": principal, "principalType": "ServicePrincipal",
        "roleDefinitionId": (
            f"/subscriptions/{record['subscription']}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{NAMESPACE_ROLE_DEFINITION_ID}"
        ),
    }


def _assignment_matches(assignment, expected):
    return isinstance(assignment, dict) and all(
        isinstance(assignment.get(key), str) and assignment[key].casefold() == expected[key].casefold()
        for key in ("id", "name", "scope", "principalId", "principalType", "roleDefinitionId")
    )


def _get_namespace_role(client, expected):
    try:
        role = client.role_assignments.get_by_id(expected["id"])
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise
    assignment = {
        "id": role.id, "name": role.name, "scope": role.scope, "principalId": role.principal_id,
        "principalType": role.principal_type, "roleDefinitionId": role.role_definition_id,
    }
    assert _assignment_matches(assignment, expected), "Namespace role assignment binding changed."
    return assignment


def _grant_namespace_self_role(name):
    """Test-only Azure Device Registry Administrator prerequisite for the namespace's own SAMI (39640174)."""
    namespace = find_namespace(name)
    record = _require_owned(name, namespace)
    assert record["kind"] == "csrns" and namespace["properties"]["provisioningState"] == "Succeeded"
    principal = _namespace_sami(namespace)
    assignment_name = str(uuid4())
    claim = {
        **_namespace_role_binding(record, principal),
        "id": f"{record['id']}/providers/Microsoft.Authorization/roleAssignments/{assignment_name}",
        "name": assignment_name, "verified": False, "delete_attempted": False, "deleted": False, "conflicted": False,
    }
    with _auth_client_factory(fixtures.cli.az_cli, scope=record["id"]) as client:
        assert _get_namespace_role(client, claim) is None, "Refusing an existing namespace role assignment ID."
        receipts.write(NAMESPACE_ROLE_RECEIPT, claim, exclusive=True)
        command = role_assignment_create_command(
            claim["roleDefinitionId"], claim["scope"],
            assignee_object_id=principal, assignee_principal_type="ServicePrincipal",
        )
        with role_assignment_create_scope(principal):
            created = invoke(
                f"{command} --name {assignment_name} --subscription {record['subscription']}"
            ).as_json()
        if not _assignment_matches(created, claim):
            receipts.write(NAMESPACE_ROLE_RECEIPT, {**claim, "conflicted": True})
            raise AssertionError("Native role assignment did not preserve its exact journaled binding.")
        wait_for_condition(
            lambda: _get_namespace_role(client, claim), lambda value: value is not None,
            description="owned namespace SAMI Azure Device Registry Administrator visibility", timeout=300, interval=5,
            is_retryable_error=lambda _error: False,
        )
    receipts.write(NAMESPACE_ROLE_RECEIPT, {**claim, "verified": True})
    return monotonic() + NAMESPACE_ROLE_PROPAGATION_SECONDS


def _remove_namespace_self_role(name):
    path = receipts.settings()[0] / NAMESPACE_ROLE_RECEIPT
    if not path.exists():
        return
    namespace = find_namespace(name)
    record = _require_owned(name, namespace) if namespace is not None else receipts._owned(name)
    claim = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        **_namespace_role_binding(
            record, _namespace_sami(namespace) if namespace is not None else str(UUID(claim["principalId"])),
        ), "name": str(UUID(claim["name"])),
    }
    expected["id"] = f"{record['id']}/providers/Microsoft.Authorization/roleAssignments/{expected['name']}"
    assert _assignment_matches(claim, expected), "Namespace role receipt scope/principal/role changed."
    assert all(claim.get(key) == record[key] for key in ("run_uid", "subscription", "phase"))
    assert all(isinstance(claim.get(key), bool) for key in ("verified", "delete_attempted", "deleted", "conflicted"))
    assert not claim["conflicted"], "Conflicting namespace role ownership requires reconciliation."
    with _auth_client_factory(fixtures.cli.az_cli, scope=record["id"]) as client:
        if namespace is None:
            assert claim["deleted"] and _get_namespace_role(client, claim) is None, (
                "Namespace disappeared before exact role cleanup; orphan reconciliation is required."
            )
            return
        if not claim["verified"]:
            # An uncertain create followed by an early 404 cannot release the
            # namespace: a delayed assignment could otherwise become orphaned.
            wait_for_condition(
                lambda: _get_namespace_role(client, claim), lambda value: value is not None,
                description="uncertain namespace role creation reconciliation", timeout=300, interval=5,
                is_retryable_error=lambda _error: False,
            )
            claim["verified"] = True
            receipts.write(NAMESPACE_ROLE_RECEIPT, claim)
        if _get_namespace_role(client, claim) is not None:
            assert not claim["deleted"], "Completed namespace role assignment reappeared."
            if not claim["delete_attempted"]:
                claim["delete_attempted"] = True
                receipts.write(NAMESPACE_ROLE_RECEIPT, claim)
                invoke(f"role assignment delete --ids {quote(claim['id'])} --subscription {record['subscription']}")
            _wait_arm_absent(lambda: _get_namespace_role(client, claim), "owned namespace SAMI role absence")
    receipts.write(NAMESPACE_ROLE_RECEIPT, {**claim, "deleted": True})


def delete_namespace(name):
    from azext_iot.tests.dps._csr_registry import cleanup_registry_devices

    current = find_namespace(name)
    if current is None:
        _remove_namespace_self_role(name)
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
        child = find_child(name, label)
        if child is None:
            continue
        if child["id"].lower() != expected_id.lower() or any(
            child.get("tags", {}).get(key) != value for key, value in record["tags"].items()
        ):
            raise AssertionError("Refusing CSR child deletion after an ownership change.")
        if child["properties"].get("provisioningState") != "Deleting":
            invoke(f"{command} delete {arguments} -y")
        _wait_arm_absent(lambda: find_child(name, label), f"owned CSR {label} absence")
    _remove_namespace_self_role(name)
    if receipts.before_delete(name, find_namespace(name)):
        with runtime.owned_write(name, "DELETE"):
            invoke(f"iot adr ns delete -n {name} -g {fixtures.ENTITY_RG} -y")
        _wait_arm_absent(lambda: find_namespace(name), "owned CSR namespace absence")
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
        role_ready_at = _grant_namespace_self_role(name)

        record = receipts._owned(name)  # pylint: disable=protected-access
        for label, command, arguments, child_path, options in _children(name):
            if find_child(name, label) is not None:
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
        remaining = max(0, role_ready_at - monotonic())
        if remaining:
            sleep(remaining)
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
def enrollment(resource, enrollment_id, *, certificate=True):
    from azext_iot.tests.dps._csr_registry import RegistryDeviceOwnership

    dps = resource["dps"]
    arguments = f"--dps-name {dps['name']} -g {dps['resourceGroup']} --enrollment-id {enrollment_id} --auth-type login"
    # Unique IDs in a dedicated owned DPS; absence must be authoritative before claiming an uncertain create.
    if _optional(f"iot dps enrollment show {arguments} --query registrationId", dataplane=True) is not None:
        raise AssertionError("Refusing to overwrite an existing CSR enrollment.")
    ownership = None
    try:
        command = f"iot dps enrollment create {arguments} --attestation-type symmetricKey"
        expected = {"registrationId": enrollment_id}
        if certificate:
            command += (
                f" --adr-namespace {resource['namespace']} --adr-ca-name {resource['ca']}"
                f" --adr-cert-policy-name {resource['policy']}"
            )
            expected.update(namespaceName=resource["namespace"], certificateAuthorityName=resource["ca"],
                            certificatePolicyName=resource["policy"])
        projection = "{" + ",".join(f"{key}:{key}" for key in expected) + "}"
        created = invoke(f"{command} --query {quote(projection)}").as_json()
        observed = {key: created.get(key) for key in expected} if isinstance(created, dict) else type(created).__name__
        assert created == expected, f"Enrollment references differ: expected {expected}, observed {observed}"
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
