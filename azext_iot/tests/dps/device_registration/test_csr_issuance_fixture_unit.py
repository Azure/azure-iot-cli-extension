# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Owned CSR setup, secret boundaries, cleanup and required-phase contracts, without Azure."""

from copy import deepcopy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shlex
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from azure.cli.core.azclierror import ForbiddenError, ResourceNotFoundError
from azure.cli.core.commands.arm import show_exception_handler
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key
from cryptography.x509.oid import NameOID
from knack.cli import CLI
from knack.events import EVENT_INVOKER_FILTER_RESULT
from knack.query import CLIQuery
from knack.util import CommandResultItem
from requests.exceptions import ConnectionError as RequestsConnectionError

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.dps import _csr_issuance as csr, _phase, _phase_manifest as manifest
from azext_iot.tests.dps._csr import temporary_csr
from azext_iot.tests.dps.device_registration import test_iot_device_registration_int as scenario

UID = "a" * 32
SUB = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def scope(tmp_path, monkeypatch, mocker):
    for key, value in (
        (csr.receipts.DIRECTORY_ENV, str(tmp_path)), (csr.receipts.RUN_UID_ENV, UID),
        (csr.receipts.SUBSCRIPTION_ENV, SUB), (csr.receipts.RESOURCE_GROUP_ENV, "rg"), (_phase.PHASE_ENV, "regular"),
    ):
        monkeypatch.setenv(key, value)
    mocker.patch.object(csr.fixtures, "ENTITY_RG", "rg")
    mocker.patch.object(csr.fixtures, "ENTITY_LOCATION", "centraluseuap")
    mocker.patch.object(csr.fixtures.cli, "invoke", side_effect=AssertionError("Unexpected live CLI invocation"))
    return tmp_path


@pytest.fixture
def resource():
    base = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Devices/"
    return {
        "namespace": "csr-" + UID[:16], "ca": csr.ISSUING_CA, "policy": csr.POLICY,
        "dps": {"name": "dps", "resourceGroup": "rg", "_kind": "csrdps", "_runUid": UID,
                "dps": {"id": base + "provisioningServices/dps", "properties": {"idScope": "scope"}}},
        "hub": {"name": "hub", "rg": "rg", "_kind": "csrhub", "_runUid": UID,
                "hub": {"id": base + "IotHubs/hub", "properties": {"hostName": "classic", "deviceHostName": "modern"}}},
    }


class NamespaceCommands:
    def __init__(self, resource):
        self.resource = resource
        self.commands = []
        self.resources = {}
        self.fail = None
        self.namespace_id = (
            f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/"
            + resource["namespace"]
        )

    def __call__(self, command):
        self.commands.append(command)
        args = shlex.split(command)
        if self.fail and self.fail in command:
            raise ForbiddenError("Injected service rejection")
        if "identity assign" in command:
            identity = {"principalId": args[1] + "-principal", "type": "SystemAssigned"}
            body = {"identity": identity} if args[1] == "dps" else identity
        elif "link add" in command:
            body = deepcopy(self.resources["namespace"])
            for section, name, key in (("provisioning", "dps", "dps"), ("messaging", "hub", "hub")):
                body["properties"][section] = {"endpoints": {name: {
                    "linkingState": "Succeeded", "resourceId": self.resource[key][key]["id"],
                    "inboundCallerIdentity": {"type": "SystemAssigned"},
                }}}
            self.resources["namespace"] = body
        else:
            label = next((label for label, group, arguments, _, _ in csr._children(self.resource["namespace"])
                          if command.startswith(group + " ") and arguments in command), "namespace")
            if " show " in command:
                if label not in self.resources:
                    raise ResourceNotFoundError("ResourceNotFound") from None
                body = self.resources[label]
            elif " create " in command:
                record = csr.receipts._owned(self.resource["namespace"])
                suffix = next((path for key, _, _, path, _ in csr._children(self.resource["namespace"]) if key == label), "")
                properties = {"provisioningState": "Succeeded"}
                if label in ("root", "ica"):
                    properties["certificateAuthorityType"] = "Root" if label == "root" else "ICA"
                body = {
                    "id": self.namespace_id + ("/" + suffix if suffix else ""),
                    "name": self.resource["namespace"] if label == "namespace" else args[args.index("-n") + 1],
                    "properties": properties, "tags": record["tags"],
                }
                self.resources[label] = body
            elif " delete " in command:
                del self.resources[label]
                body = None
            elif " wait " in command:
                body = None
            else:
                raise AssertionError(command)
        return SimpleNamespace(as_json=lambda: deepcopy(body))


@pytest.fixture
def namespace_commands(scope, resource, mocker):
    backend = NamespaceCommands(resource)
    mocker.patch.object(csr, "invoke", side_effect=backend)
    mocker.patch.object(csr, "find_namespace", side_effect=lambda _name: backend.resources.get("namespace"))
    mocker.patch.object(csr, "find_child", side_effect=lambda _name, label: backend.resources.get(label))
    return backend


@pytest.fixture
def arm_commands(scope, resource, mocker):
    backend = NamespaceCommands(resource)
    backend.get_responses, backend.get_calls, backend.transport_error = {}, [], None
    endpoint = "https://centraluseuap.management.azure.com"
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 9999999999))
    backend.client = DeviceRegistryMgmtClient(credential, SUB, base_url=endpoint, retry_total=0)
    backend.factory = mocker.patch.object(csr, "adr_service_factory", return_value=backend.client)
    mocker.patch.object(csr, "invoke", side_effect=backend)
    paths = {backend.namespace_id: "namespace"}
    paths.update({backend.namespace_id + "/" + path: label
                  for label, _, _, path, _ in csr._children(resource["namespace"])})

    def respond(request):
        assert request.method == "GET"
        assert parse_qs(urlsplit(request.url).query) == {"api-version": ["2026-11-02-preview"]}
        label = paths[urlsplit(request.url).path]
        if backend.transport_error is not None:
            raise backend.transport_error
        status, body = backend.get_responses.get(label, (
            (200, backend.resources[label]) if label in backend.resources
            else (404, {"error": {"code": "ResourceNotFound", "message": "Expected absent resource"}})
        ))
        backend.get_calls.append((label, status))
        return status, {"Content-Type": "application/json"}, json.dumps(body)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        for path in paths:
            network.add_callback(responses.GET, endpoint + path, callback=respond)
        yield backend
    backend.client.close()


def test_real_sdk_absence_probes_complete_setup_and_dependency_ordered_cleanup(arm_commands, resource, scope):
    name, _ = csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    csr.delete_namespace(name)
    for label in ("namespace", "root", "ica", "policy"):
        assert arm_commands.get_calls.count((label, 404)) == 2
    assert all(call.kwargs == {"subscription_id": SUB} for call in arm_commands.factory.call_args_list)
    assert json.loads((scope / "deleted-csrns.json").read_text())["delete_completed"] is True
    assert not arm_commands.resources
    assert sum(" show " in command for command in arm_commands.commands) == 3  # Present-child readback only.
    assert not any("iot adr ns show " in command for command in arm_commands.commands)
    deletes = [command for command in arm_commands.commands if " delete " in command]
    assert [command.split(" -n ")[1].split()[0] for command in deletes] == [
        csr.POLICY, csr.ISSUING_CA, csr.ROOT_CA, name,
    ]


def test_real_arm_show_handler_exits_on_sdk_404_but_scoped_probe_returns_absent(arm_commands, resource, mocker):
    mocker.patch("azure.cli.core.azclierror.ResourceNotFoundError.send_telemetry")
    with pytest.raises(HttpResponseError) as missing:
        arm_commands.client.certificate_authorities.get(
            resource_group_name="rg", namespace_name=resource["namespace"], certificate_authority_name=csr.ROOT_CA,
        )
    assert missing.value.status_code == 404
    with pytest.raises(SystemExit) as exited:
        show_exception_handler(missing.value)
    assert exited.value.code == 3
    assert csr.find_child(resource["namespace"], "root") is None
    assert arm_commands.get_calls == [("root", 404), ("root", 404)]
    assert not arm_commands.commands


@pytest.mark.parametrize("label", ["namespace", "root", "ica", "policy"])
@pytest.mark.parametrize("status", [400, 401, 403, 409, 500])
def test_scoped_sdk_absence_wait_never_swallows_other_http_errors(arm_commands, resource, label, status):
    arm_commands.get_responses[label] = (status, {"error": {"code": "ResourceNotFound", "message": "Not a 404"}})
    with pytest.raises(HttpResponseError) as raised:
        csr._wait_arm_absent(
            lambda: csr.find_namespace(resource["namespace"]) if label == "namespace"
            else csr.find_child(resource["namespace"], label),
            "owned absence",
        )
    assert raised.value.status_code == status
    assert arm_commands.get_calls == [(label, status)]
    assert not arm_commands.commands


@pytest.mark.parametrize("label", ["namespace", "root", "ica", "policy"])
@pytest.mark.parametrize("body", [None, {}, [], {"id": None}, {"id": ""}])
def test_scoped_sdk_null_or_malformed_success_cannot_prove_absence(arm_commands, resource, label, body):
    arm_commands.get_responses[label] = (200, body)
    with pytest.raises(AssertionError, match="Malformed ARM GET"):
        if label == "namespace":
            csr.find_namespace(resource["namespace"])
        else:
            csr.find_child(resource["namespace"], label)
    assert not arm_commands.commands


def test_scoped_sdk_transport_failure_is_not_absence(arm_commands, resource):
    arm_commands.transport_error = RequestsConnectionError("Offline transport failure")
    with pytest.raises(ServiceRequestError, match="Offline transport failure"):
        csr.find_child(resource["namespace"], "root")
    assert not arm_commands.commands


def test_precreate_sdk_rejection_preserves_error_and_never_claims_or_creates_ca(arm_commands, resource, scope):
    arm_commands.get_responses["root"] = (403, {"error": {"code": "AuthorizationFailed"}})
    with pytest.raises(HttpResponseError) as raised:
        csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    assert raised.value.status_code == 403
    assert not (scope / "csr-child-root.json").exists()
    assert not any("ns ca create" in command for command in arm_commands.commands)
    assert not arm_commands.resources
    assert json.loads((scope / "deleted-csrns.json").read_text())["delete_completed"] is True


@pytest.mark.parametrize("label", ["namespace", "root", "ica", "policy"])
def test_postdelete_sdk_error_cannot_record_namespace_cleanup_completion(arm_commands, resource, scope, mocker, label):
    name, _ = csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    target = {"namespace": name, "root": csr.ROOT_CA, "ica": csr.ISSUING_CA, "policy": csr.POLICY}[label]

    def invoke(command):
        result = arm_commands(command)
        if f" delete -n {target} " in command:
            arm_commands.get_responses[label] = (403, {"error": {"code": "AuthorizationFailed"}})
        return result

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    with pytest.raises(HttpResponseError) as raised:
        csr.delete_namespace(name)
    assert raised.value.status_code == 403
    completed = scope / "deleted-csrns.json"
    assert not completed.exists() or not json.loads(completed.read_text()).get("delete_completed")
    assert sum(f" delete -n {target} " in command for command in arm_commands.commands) == 1
    if label != "namespace":
        assert "namespace" in arm_commands.resources
        assert not any("iot adr ns delete " in command for command in arm_commands.commands)


def test_setup_uses_dedicated_pair_native_dps_first_and_ready_service_issuer(namespace_commands, resource, scope):
    name, namespace = csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    assert name == resource["namespace"]
    assert namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] == "Succeeded"
    mutations = [command for command in namespace_commands.commands if any(
        action in command for action in (" create ", " assign ", " add ")
    )]
    assert len(mutations) == 7
    assert "iot dps identity assign" in mutations[1]
    assert "iot hub identity assign" in mutations[2]
    assert mutations[3].startswith("iot adr ns link add ")
    assert "--timeout 1200 --interval 10" in mutations[3]
    assert "--dps-system-assigned-mi" in mutations[3] and "--hub-system-assigned-mi" in mutations[3]
    assert "--type Root" in mutations[4]
    assert "--issuer-type Microsoft --issuer-ca-name rootca" in mutations[5]
    assert "--validity-days 30" in mutations[6]
    assert sum(" wait " in command for command in namespace_commands.commands) == 3
    assert not any("role assignment" in command or "linked-hub" in command for command in mutations)
    assert json.loads((scope / "created-csrns.json").read_text())["create_completed"]
    csr.delete_namespace(name)
    deletes = [command for command in namespace_commands.commands if " delete " in command]
    assert ["policy" if " policy " in command else "ica" if "issuingca" in command
            else "root" if "rootca" in command else "namespace" for command in deletes] == [
        "policy", "ica", "root", "namespace",
    ]
    assert json.loads((scope / "deleted-csrns.json").read_text())["delete_completed"]
    assert not namespace_commands.resources


def test_fixture_commands_parse_through_real_root_loader(namespace_commands, resource):
    from azure.cli.core import AzCommandsLoader
    from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
    from azure.cli.core.mock import DummyCli
    from azure.cli.core.parser import AzCliCommandParser
    from azext_iot import IoTExtCommandsLoader

    name, _ = csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    csr.delete_namespace(name)
    commands = [shlex.split(command) for command in namespace_commands.commands]
    names = {
        " ".join(command[:next(i for i, arg in enumerate(command) if arg in {
            "create", "show", "wait", "delete", "assign", "add",
        }) + 1])
        for command in commands
    }
    cli = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    loader.command_table = {name: loader.command_table[name] for name in names}
    cli.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    for name in names:
        loader.load_arguments(name)
        AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli)
    parser.load_command_table(loader)
    for command in commands:
        parser.parse_args(command)


def test_uncertain_ica_submission_preserves_failure_and_cleans_persisted_child(namespace_commands, resource, mocker):
    def invoke(command):
        result = namespace_commands(command)
        if "create -n issuingca" in command:
            raise ForbiddenError("Response failed after materialization")
        return result

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    with pytest.raises(ForbiddenError, match="after materialization"):
        csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    assert not namespace_commands.resources
    assert sum("delete -n issuingca" in command for command in namespace_commands.commands) == 1


@pytest.mark.parametrize("failed", ["iot dps identity assign", "iot adr ns link add", "create -n issuingca"])
def test_setup_failure_is_not_repaired_and_cleans_only_attempted_children(namespace_commands, resource, failed):
    namespace_commands.fail = failed
    with pytest.raises(ForbiddenError, match="Injected service rejection"):
        csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    assert sum(failed in command for command in namespace_commands.commands) == 1
    assert not namespace_commands.resources
    assert not any("link update" in command for command in namespace_commands.commands)


@pytest.mark.parametrize("target", ["namespace", "root", "ica", "policy"])
def test_cleanup_refuses_current_ownership_change(namespace_commands, resource, target):
    name, _ = csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    namespace_commands.resources[target]["tags"] = {"runUid": "another-run"}
    with pytest.raises(AssertionError, match="ownership|ownership change"):
        csr.delete_namespace(name)
    assert target in namespace_commands.resources
    assert "namespace" in namespace_commands.resources


def test_unclaimed_existing_namespace_is_not_mutated(namespace_commands, resource):
    namespace_commands.resources["namespace"] = {"id": "preexisting"}
    with pytest.raises(AssertionError, match="overwrite"):
        csr._create_namespace(UID, "csrns", resource["dps"], resource["hub"])
    assert not namespace_commands.commands


@pytest.mark.parametrize("failing_body", [False, True])
def test_shared_fixture_acquires_and_releases_only_dedicated_kinds(scope, resource, mocker, failing_body):
    events = []
    namespace = {"name": resource["namespace"], "properties": {"provisioningState": "Succeeded"}}
    for section, name in (("provisioning", "dps"), ("messaging", "hub")):
        namespace["properties"][section] = {"endpoints": {name: {
            "resourceId": resource[name][name]["id"], "linkingState": "Succeeded",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}}
    for name, kind, current in (
        ("hub", "csrhub", resource["hub"]["hub"]), ("dps", "csrdps", resource["dps"]["dps"]),
        (namespace["name"], "csrns", namespace),
    ):
        csr.receipts.before_create(name, "rg", UID, kind)
        record = csr.receipts._owned(name)
        current.update(id=record["id"], tags=record["tags"])
    mocker.patch.object(csr.fixtures, "_get_run_uid", return_value=UID)
    hub = mocker.patch.object(csr.fixtures, "_iot_hubs_provisioner", return_value=resource["hub"])
    dps = mocker.patch.object(csr.fixtures, "_iot_dps_provisioner", return_value=resource["dps"])
    acquire = mocker.patch.object(csr.fixtures, "_shared_acquire", return_value=namespace)
    for name, value in (("_find_dps_by_name", resource["dps"]["dps"]), ("_find_hub_by_name", resource["hub"]["hub"])):
        mocker.patch.object(csr.fixtures, name, return_value=value)
    mocker.patch.object(csr.fixtures, "_shared_release", side_effect=lambda *args: events.append(args[1]))
    mocker.patch.object(csr.fixtures, "_iot_dps_removal", side_effect=lambda _resource: events.append("csrdps"))
    mocker.patch.object(csr.fixtures, "_iot_hubs_removal", side_effect=lambda _resource: events.append("csrhub"))
    request = object()
    with pytest.raises(ValueError, match="body") if failing_body else nullcontext():
        with csr.provisioned_issuance(request) as result:
            assert result == resource
            if failing_body:
                raise ValueError("body")
    hub.assert_called_once_with(request, managed_kind="csrhub")
    dps.assert_called_once_with(request, managed_kind="csrdps")
    assert acquire.call_args.args[:2] == (UID, "csrns")
    assert events == ["csrns", "csrdps", "csrhub"]


@pytest.mark.parametrize("defect", ["missing-receipt", "missing-resource", "changed-id", "changed-tags"])
def test_reused_target_requires_current_exact_ownership(scope, defect):
    if defect != "missing-receipt":
        csr.receipts.before_create("dps", "rg", UID, "csrdps")
    current = {"id": f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps",
               "tags": {"intTest": "true", "runUid": UID, "kind": "csrdps"}}
    if defect == "missing-resource":
        current = None
    elif defect == "changed-id":
        current["id"] += "-other"
    elif defect == "changed-tags":
        current["tags"]["runUid"] = "another-run"
    with pytest.raises(RuntimeError if defect == "missing-receipt" else AssertionError, match="ownership"):
        csr._require_owned("dps", current)


def test_unorchestrated_csr_fails_before_provisioning(monkeypatch, mocker):
    mocker.patch.object(csr.receipts, "settings", return_value=None)
    provision = mocker.patch.object(csr.fixtures, "_iot_hubs_provisioner")
    with pytest.raises(pytest.UsageError, match="controller"):
        with csr.provisioned_issuance(object()):
            pytest.fail("Unowned CSR fixture yielded")
    provision.assert_not_called()


def test_temporary_csr_is_fresh_matching_protected_and_removed_after_error(tmp_path, mocker):
    open_file = mocker.spy(os, "open")
    make_directory = mocker.spy(os, "mkdir")
    public_keys = []
    directories = []
    for registration_id in ("first", "second"):
        with pytest.raises(ValueError, match="body"):
            with temporary_csr(tmp_path, registration_id) as path:
                request = x509.load_pem_x509_csr(path.read_bytes())
                key_path = path.parent / "key.pem"
                private = load_pem_private_key(key_path.read_bytes(), None)
                assert request.is_signature_valid
                assert request.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == registration_id
                assert request.public_key().public_numbers() == private.public_key().public_numbers()
                for material in (path, key_path):
                    open_file.assert_any_call(material, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                make_directory.assert_any_call(str(path.parent), 0o700)
                # Windows stat reports DOS attributes, not POSIX permission bits.
                # Still verify exclusive creation and requested modes on every OS.
                if os.name == "posix":
                    assert path.stat().st_mode & 0o777 == key_path.stat().st_mode & 0o777 == 0o600
                    assert path.parent.stat().st_mode & 0o777 == 0o700
                directories.append(path.parent)
                public_keys.append(private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo))
                raise ValueError("body")
    assert public_keys[0] != public_keys[1]
    assert not any(directory.exists() for directory in directories)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
def test_enrollment_absence_accepts_only_authoritative_not_found(mocker, status):
    response = SimpleNamespace(status_code=status, reason="error", headers={})
    cause = HttpResponseError(response=response)
    error = ResourceNotFoundError("ResourceNotFound") if status == 404 else ForbiddenError("ResourceNotFound")
    error.__cause__ = cause
    mocker.patch.object(csr, "invoke", side_effect=error)
    if status == 404:
        assert csr._optional("show", dataplane=True) is None
    else:
        with pytest.raises(ForbiddenError):
            csr._optional("show", dataplane=True)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
def test_data_plane_translation_survives_real_arm_show_exception_boundary(mocker, status):
    from knack.util import CLIError
    from azext_iot.dps.services._enrollment import handle_service_error

    cause = HttpResponseError(response=SimpleNamespace(
        status_code=status, reason="error", headers={}, json=lambda: {"errorCode": status, "message": "DPS error"},
    ))

    def translated_show(_command):
        try:
            handle_service_error(cause)
        except CLIError as error:
            show_exception_handler(error)

    mocker.patch.object(csr, "invoke", side_effect=translated_show)
    if status == 404:
        assert csr._optional("iot dps enrollment show", dataplane=True) is None
    else:
        with pytest.raises(CLIError) as raised:
            csr._optional("iot dps enrollment show", dataplane=True)
        assert raised.value.__cause__ is cause


def test_expected_404_query_cannot_filter_the_next_enrollment_result(resource, tmp_path, mocker, caplog):
    record = {}
    contexts = []
    returned = []

    class OfflineInvocation:
        def __init__(self, cli_ctx, **_kwargs):
            self.cli_ctx = cli_ctx
            self.data = {"output": "json"}

        def execute(self, args):
            if "--query" in args:
                CLIQuery.handle_query_parameter(self.cli_ctx, args=SimpleNamespace(
                    _jmespath_query=CLIQuery.jmespath_type(args[args.index("--query") + 1]),
                ))
            if "show" in args and (not record or "registration" in args):
                cause = HttpResponseError(response=SimpleNamespace(status_code=404, reason="Not Found", headers={}))
                raise ResourceNotFoundError("EnrollmentNotFound") from cause
            if "create" in args:
                record.update({
                    "registrationId": args[args.index("--enrollment-id") + 1],
                    "namespaceName": resource["namespace"],
                    "certificateAuthorityName": resource["ca"],
                    "certificatePolicyName": resource["policy"],
                    "attestation": {"symmetricKey": {"primaryKey": "DO-NOT-LOG-BOOTSTRAP-KEY"}},
                })
            if "delete" in args:
                record.clear()
            event = {"result": deepcopy(record)}
            self.cli_ctx.raise_event(EVENT_INVOKER_FILTER_RESULT, event_data=event)
            returned.append(event["result"])
            return CommandResultItem(event["result"])

    def fresh_context():
        context = CLI(cli_name="csr-offline", config_dir=str(tmp_path), invocation_cls=OfflineInvocation)
        context.data = {"subscription_id": SUB}
        contexts.append(context)
        return context

    mocker.patch("azext_iot.common.embedded_cli.get_default_cli", side_effect=fresh_context)
    mocker.patch.object(csr.fixtures, "cli", EmbeddedCLI())
    owner = mocker.patch("azext_iot.tests.dps._csr_registry.RegistryDeviceOwnership").return_value
    with caplog.at_level("DEBUG", logger="azext_iot.common.embedded_cli"):
        for registration_id in ("first", "second"):
            with csr.enrollment(resource, registration_id) as ownership:
                assert ownership is owner
    assert owner.cleanup.call_count == 2
    assert not record
    assert len(contexts) == 11  # Shared fixture context plus one isolated context per command.
    assert [value["registrationId"] for value in returned if isinstance(value, dict) and value] == ["first", "second"]
    assert "DO-NOT-LOG-BOOTSTRAP-KEY" not in caplog.text


@pytest.mark.parametrize("timeout", [None, 180])
@pytest.mark.parametrize("failure", [None, "create", "registration", "operation-status"])
def test_real_scenario_uses_fresh_enrollment_secret_free_commands_and_cleanup(
    resource, tmp_path, mocker, timeout, failure,
):
    commands = []
    ids = []
    existing = False
    owner = mocker.patch("azext_iot.tests.dps._csr_registry.RegistryDeviceOwnership").return_value

    def invoke(command):
        nonlocal existing
        commands.append(command)
        args = shlex.split(command)
        if "enrollment show" in command:
            assert "--query registrationId" in command
            body = ids[-1] if existing else None
        elif "enrollment create" in command:
            enrollment_id = args[args.index("--enrollment-id") + 1]
            ids.append(enrollment_id)
            existing = True  # Also materializes when submission's response fails.
            if failure == "create":
                raise ForbiddenError("create rejected")
            assert "--query" in args and "primaryKey" not in args[args.index("--query") + 1]
            body = {
                "registrationId": enrollment_id, "namespaceName": resource["namespace"],
                "certificateAuthorityName": resource["ca"], "certificatePolicyName": resource["policy"],
            }
        elif "enrollment delete" in command:
            existing = False
            body = None
        elif "enrollment registration show" in command:
            body = None
        elif "device registration" in command:
            assert "--key" not in args and "--symmetric-key" not in args
            assert "--auth-type login" in command and "--id-scope scope" in command
            if args[3] == "create":
                assert ("--timeout" in args) == (timeout is not None)
                path = Path(args[args.index("--csr") + 1])
                request = x509.load_pem_x509_csr(path.read_bytes())
                assert request.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == ids[-1]
                if failure == "registration":
                    raise ForbiddenError("registration rejected")
            elif failure == "operation-status":
                raise ForbiddenError("operation-status rejected")
            body = {
                "operationId": "operation", "status": "assigned",
                "registrationState": {
                    "registrationId": ids[-1], "deviceId": ids[-1], "assignedHub": "modern",
                    "connectionProfile": "MqttV5", "issuedCertificateChain": ["opaque-contract-value"],
                    "registryDeviceExternalId": "external-id",
                },
            }
        else:
            raise AssertionError(command)
        return SimpleNamespace(as_json=lambda: body)

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    mocker.patch.object(scenario, "invoke", side_effect=invoke)
    for _ in range(2):
        with pytest.raises(ForbiddenError, match="rejected") if failure else nullcontext():
            scenario.test_register_and_issue_certificate_contract(resource, tmp_path, timeout)
        assert not existing
        assert not list(tmp_path.iterdir())
    assert len(set(ids)) == 2
    assert sum("enrollment delete" in command for command in commands) == 2
    assert not any("link update" in command or "--key " in command for command in commands)
    assert owner.before_submit.call_count == (0 if failure == "create" else 2)
    assert owner.cleanup.call_count == (0 if failure == "create" else 2)


def test_csr_cases_are_required_not_pending_and_resources_are_typed():
    assert manifest.CSR_NODEIDS <= manifest.expected_nodeids("regular")
    assert "test_register_and_issue_certificate_contract" not in _phase.PENDING_CERTIFICATE_TESTS
    assert not manifest.CSR_NODEIDS & manifest.expected_nodeids("service-sas")
    assert manifest.resource_kinds("regular")[-3:] == ("csrns", "csrdps", "csrhub")
    assert manifest.resource_type("csrns") == "Microsoft.DeviceRegistry/namespaces"
    assert manifest.resource_type("csrhub") == "Microsoft.Devices/IotHubs"


@pytest.mark.parametrize("nodeid", sorted(manifest.CSR_NODEIDS))
@pytest.mark.parametrize("stage", ["setup", "call", "teardown"])
def test_requested_csr_skip_is_a_failure(monkeypatch, nodeid, stage):
    monkeypatch.setenv(_phase.PHASE_ENV, "regular")
    item = SimpleNamespace(nodeid="azext_iot/tests/dps/" + nodeid, get_closest_marker=lambda _name: None)
    report = pytest.TestReport(
        nodeid=item.nodeid, location=("test.py", 1, "csr"), keywords={}, outcome="skipped",
        longrepr=("test.py", 1, "Skipped: missing CSR prerequisite"), when=stage,
    )
    hook = csr.fixtures.pytest_runtest_makereport(item)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: report))
    assert report.failed and not report.skipped
