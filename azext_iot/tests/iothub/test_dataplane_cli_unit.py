# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Hub factory, parser, and provider contracts around the regenerated HTTP clients."""

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
import responses
from azure.cli.core import AzCommandsLoader
from azure.cli.core.azclierror import AuthenticationError, AzureInternalError, FileOperationError, InvalidArgumentValueError
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError, ServiceResponseError

from azext_iot import IoTExtCommandsLoader
from azext_iot._factory import SdkResolver
from azext_iot.common.shared import SdkType
from azext_iot.iothub._payload import validate_identity_update
from azext_iot.iothub import commands_pnp_runtime
from azext_iot.iothub.providers.device_messaging import DeviceMessagingProvider
from azext_iot.iothub.providers.job import JobProvider
from azext_iot.iothub.providers.pnp_runtime import PnPRuntimeProvider
from azext_iot.iothub.providers.state import StateProvider
from azext_iot.operations import hub
from azext_iot.tests.conftest import mock_target
from azext_iot.tests.iothub.test_dataplane_adapter_unit import adapter
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, ENDPOINT


@pytest.fixture(scope="module")
def identity_parser():
    cli_ctx = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli_ctx.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    names = ["iot hub device-identity update"] + [
        f"iot hub digital-twin {action}" for action in ("show", "update", "invoke-command")
    ]
    loader.command_table = {name: loader.command_table[name] for name in names}
    cli_ctx.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    for name in names:
        loader.load_arguments(name)
        AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli_ctx)
    parser.load_command_table(loader)
    return parser


@pytest.mark.parametrize("arguments", [
    ["--set", "status=disabled", "adrDeviceProperties.uuid=forged"],
    ["--remove", "adrDeviceProperties"],
    ["--add", "adrDeviceProperties", "name=forged"],
])
def test_real_identity_parser_rejects_explicit_owned_changes(identity_parser, arguments):
    namespace = identity_parser.parse_args([
        "iot", "hub", "device-identity", "update", "-n", "hub", "-d", "device", *arguments,
    ])
    with pytest.raises(InvalidArgumentValueError, match="owned"):
        validate_identity_update(namespace)


@pytest.mark.parametrize("side", ["service", "device"])
@pytest.mark.parametrize("split_host", [False, True])
def test_factory_real_wire_preserves_sas_audience_and_endpoint(side, split_host):
    target = dict(mock_target, entity="classic.unit.invalid")
    if split_host:
        target.update(serviceHostName="service.unit.invalid", deviceHostName="device.unit.invalid")
    hostname = target.get(side + "HostName") or target["entity"]
    kind = SdkType.service_sdk if side == "service" else SdkType.device_sdk
    client = SdkResolver(target, device_id="device").get_sdk(kind)
    route = "/devices/device" if side == "service" else "/devices/device/messages/deviceBound"
    with responses.RequestsMock() as network:
        network.add("GET", "https://" + hostname + route, json={}, status=200)
        if side == "service":
            client.devices.get_identity(id="device")
        else:
            client.device.receive_device_bound_notification(id="device", raw=True)
        request = network.calls[0].request
        audience = hostname if side == "service" else hostname + "/devices/device"
        authorization = unquote(request.headers["Authorization"])
        assert authorization.startswith("SharedAccessSignature ")
        assert "sr=" + audience in authorization
        assert target["primarykey"] not in authorization
        assert "api-version=" + API in request.url
        assert request.headers["User-Agent"].startswith("IoTPlatformCliExtension/")
    client.close()


def test_device_factory_without_device_id_keeps_the_hub_policy_audience():
    client = SdkResolver(dict(mock_target, entity="https://hub.unit.invalid/")).get_sdk(SdkType.device_sdk)
    with responses.RequestsMock() as network:
        network.add("GET", ENDPOINT + "/devices/device/messages/deviceBound", body=b"raw", status=200)
        result = client.device.receive_device_bound_notification(id="device", raw=True)
        assert list(result.response.iter_content()) == [b"r", b"a", b"w"]
        result.response.close()
        authorization = unquote(network.calls[0].request.headers["Authorization"])
        assert "sr=hub.unit.invalid&" in authorization and "sr=https://" not in authorization
    client.close()


@pytest.mark.parametrize("side", ["service", "device"])
@pytest.mark.parametrize("endpoint", [
    "http://hub.unit.invalid", "https://user@hub.unit.invalid", "https://hub.unit.invalid/path",
])
def test_invalid_hub_origins_fail_before_credential_construction(mocker, side, endpoint):
    sas = mocker.patch("azext_iot._factory.SasTokenAuthentication", side_effect=AssertionError("Credentials not allowed"))
    oauth = mocker.patch("azext_iot._factory.IoTOAuth", side_effect=AssertionError("Credentials not allowed"))
    kind = SdkType.service_sdk if side == "service" else SdkType.device_sdk
    with pytest.raises(InvalidArgumentValueError, match="Hub endpoints"):
        SdkResolver(dict(mock_target, entity=endpoint)).get_sdk(kind)
    sas.assert_not_called()
    oauth.assert_not_called()


@pytest.mark.parametrize("action,operation,extra", [
    ("show", "get_digital_twin", {}),
    ("update", "patch_digital_twin", {"json_patch": "[]"}),
    ("invoke-command", "invoke_device_command", {"command_name": "noop"}),
])
@pytest.mark.parametrize("auth_type", ["login", "key"])
def test_pnp_standard_auth_reaches_the_provider(mocker, identity_parser, action, operation, extra, auth_type):
    flags = ["--patch", "[]"] if action == "update" else ["--cn", "noop"] if action == "invoke-command" else []
    namespace = identity_parser.parse_args([
        "iot", "hub", "digital-twin", action, "-n", "hub", "-d", "device", "--auth-type", auth_type, *flags,
    ])
    assert namespace.auth_type_dataplane == auth_type
    provider = mocker.patch.object(commands_pnp_runtime, "PnPRuntimeProvider")
    cmd = mocker.Mock()
    getattr(commands_pnp_runtime, operation)(
        cmd=cmd, device_id="device", hub_name_or_hostname="hub", resource_group_name="rg",
        auth_type_dataplane=auth_type, **extra,
    )
    provider.assert_called_once_with(
        cmd=cmd, hub_name="hub", rg="rg", login=None, auth_type_dataplane=auth_type,
    )


def test_pnp_login_is_propagated_to_discovery_and_actual_http_authorization(mocker):
    cmd = mocker.Mock()
    discovery = mocker.patch("azext_iot.iothub.providers.base.IotHubDiscovery").return_value
    discovery.get_target.return_value = {"entity": "hub.unit.invalid", "policy": "login", "cmd": cmd}
    oauth = mocker.patch("azext_iot._factory.IoTOAuth", return_value=AzureKeyCredential("Bearer offline"))
    provider = PnPRuntimeProvider(cmd, hub_name="hub", rg="rg", auth_type_dataplane="login")
    discovery.get_target.assert_called_once_with(resource_name="hub", resource_group_name="rg", login=None, auth_type="login")
    oauth.assert_called_once_with(cli_ctx=cmd.cli_ctx, resource_id="https://iothubs.azure.net")
    with responses.RequestsMock() as network:
        network.add("GET", ENDPOINT + "/digitaltwins/device", json={"value": 1})
        assert provider.get_digital_twin("device") == {"value": 1}
        assert network.calls[0].request.headers["Authorization"] == "Bearer offline"
    provider.runtime_sdk.client.close()


def test_pnp_falsey_scalar_payload_is_a_real_json_body():
    client = adapter()
    provider = PnPRuntimeProvider.__new__(PnPRuntimeProvider)
    provider.runtime_sdk = client.digital_twin
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/digitaltwins/device/commands/noop", json={"echo": 0},
                    headers={"x-ms-command-statuscode": "200"})
        assert provider.invoke_device_command("device", "noop", payload=0) == {"payload": {"echo": 0}, "status": "200"}
        assert network.calls[0].request.body in (b"0", "0")
    client.close()


def _upload_provider(client):
    provider = DeviceMessagingProvider.__new__(DeviceMessagingProvider)
    provider.device_id = "device"
    provider.device_sdk = client
    return provider


@pytest.mark.parametrize("blob_status", [201, 403])
@pytest.mark.parametrize("notification_status", [204, 503])
def test_upload_provider_real_binary_body_and_truthful_completion(tmp_path, blob_status, notification_status):
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\x00\xff\xfe\x80")
    client = adapter("device")
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/device/files", json={
            "hostName": "storage.unit.invalid", "containerName": "container", "blobName": "blob",
            "sasToken": "?sig=offline", "correlationId": "correlation",
        })
        network.add("PUT", "https://storage.unit.invalid/container/blob?sig=offline", status=blob_status)
        network.add("POST", ENDPOINT + "/devices/device/files/notifications", status=notification_status)
        provider = _upload_provider(client)
        if blob_status == 403:
            with pytest.raises(FileOperationError, match="HTTP 403"):
                provider.device_upload_file(str(path), "application/octet-stream")
        elif notification_status == 503:
            with pytest.raises(AzureInternalError):
                provider.device_upload_file(str(path), "application/octet-stream")
        else:
            assert provider.device_upload_file(str(path), "application/octet-stream") is None
        assert len(network.calls) == 3
        assert network.calls[1].request.body == path.read_bytes()
        completion = json.loads(network.calls[2].request.body)
        assert completion["isSuccess"] is (blob_status == 201)
        assert completion["statusCode"] == (201 if blob_status == 201 else 500)
        assert completion["correlationId"] == "correlation"
        assert "statusDescription" in completion
        assert "reason" not in completion
    client.close()


@pytest.mark.parametrize("failure", [
    ServiceRequestError("offline"), ServiceResponseError("offline"),
    ClientAuthenticationError("credential failed"), AuthenticationError("login failed"),
])
def test_failed_upload_notification_transport_does_not_mask_original_failure(tmp_path, mocker, failure):
    path = tmp_path / "file"
    path.write_bytes(b"bytes")
    client = adapter("device")
    original = FileOperationError("original upload failure")
    mocker.patch.object(client.device, "create_file_upload_sas_uri", return_value=SimpleNamespace(
        response=SimpleNamespace(json=lambda: {
            "hostName": "storage", "containerName": "container", "blobName": "blob",
            "sasToken": "?sig=offline", "correlationId": "correlation",
        }),
    ))
    mocker.patch.object(client.device, "upload_file_to_container", side_effect=original)
    notify = mocker.patch.object(client.device, "update_file_upload_status", side_effect=failure)
    with pytest.raises(FileOperationError) as observed:
        _upload_provider(client).device_upload_file(str(path), "text/plain")
    assert observed.value is original
    notify.assert_called_once()
    client.close()


def test_unreadable_upload_fails_before_request(tmp_path, mocker):
    path = tmp_path / "file"
    path.touch()
    mocker.patch("azext_iot.iothub.providers.device_messaging.Path.read_bytes", side_effect=PermissionError())
    client = adapter("device")
    with pytest.raises(FileOperationError, match="Unable to read"):
        _upload_provider(client).device_upload_file(str(path), "text/plain")
    client.close()


def test_bulk_regeneration_accumulates_rotated_keys_across_real_requests():
    client = adapter()
    with responses.RequestsMock() as network:
        payload = {"policyKey": "primaryKey", "errors": [], "rotatedKeys": [{"id": "device", "primaryKey": "new"}]}
        network.add("POST", ENDPOINT + "/devices/keys/regenerate", json=payload)
        result = hub._iot_key_regenerate_batch(client, "primaryKey", [{"id": "device"}], no_progress=True)
        assert result == payload
        assert json.loads(network.calls[0].request.body) == {
            "policyKey": "primaryKey", "devices": [{"id": "device"}],
        }
    client.close()


def test_bulk_empty_cohort_does_not_send_a_request():
    client = adapter()
    result = hub._iot_key_regenerate_batch(client, "primaryKey", [], no_progress=True)
    assert isinstance(result, dict)
    assert not result
    client.close()


def test_module_wildcard_key_rotation_excludes_non_sas_identities(mocker):
    mocker.patch.object(hub, "_iot_device_module_list", return_value=[
        {"moduleId": "sas-module", "authentication": {"type": "sas"}},
        {"moduleId": "ca-module", "authentication": {"type": "certificateAuthority"}},
    ])
    assert hub._iot_key_regenerate_process_modules({}, "device", ["*"]) == [{"id": "device", "moduleId": "sas-module"}]


def test_partial_bulk_failure_does_not_log_regenerated_secrets(mocker):
    from azure.cli.core.azclierror import ForbiddenError

    client = adapter()
    warning = mocker.patch.object(hub.logger, "warning")
    mocker.patch.object(hub, "IOTHUB_RENEW_KEY_BATCH_SIZE", 1)
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/keys/regenerate", json={
            "rotatedKeys": [{"id": "first", "primaryKey": "sensitive-generated-key"}],
        })
        network.add("POST", ENDPOINT + "/devices/keys/regenerate", status=403, json={"Message": "Denied."})
        with pytest.raises(ForbiddenError):
            hub._iot_key_regenerate_batch(client, "primaryKey", [{"id": "first"}, {"id": "second"}], no_progress=True)
        assert len(network.calls) == 2
    warning.assert_called_once_with("Managed to renew keys for %d identities before the failed batch.", 1)
    assert "sensitive-generated-key" not in str(warning.call_args)
    client.close()


def test_unknown_service_job_type_error_is_preserved_without_fabricating_a_job_body(mocker):
    from azure.cli.core.azclierror import BadRequestError

    client = adapter()
    provider = JobProvider.__new__(JobProvider)
    mocker.patch.object(provider, "get_sdk", return_value=client)
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/jobs/v2/job", status=400, json={"Message": "Unsupported job type."})
        with pytest.raises(BadRequestError, match="Unsupported"):
            provider.create(job_id="job", job_type="unsupported")
        body = json.loads(network.calls[0].request.body)
        assert body["type"] == "unsupported"
        assert "updateTwin" not in body and "cloudToDeviceMethod" not in body
        assert len(network.calls) == 1
    client.close()


def test_scheduled_job_missing_status_keeps_polling_without_losing_the_response(mocker):
    client = adapter()
    provider = JobProvider.__new__(JobProvider)
    mocker.patch.object(provider, "get_sdk", return_value=client)
    mocker.patch.object(provider, "_get", side_effect=[{"jobId": "job"}, {"jobId": "job", "status": "completed"}])
    pause = mocker.patch("azext_iot.iothub.providers.job.sleep")
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/jobs/v2/job", json={"jobId": "job", "status": "queued"})
        result = provider.create(
            job_id="job", job_type="scheduleUpdateTwin", query_condition="*", twin_patch='{"tags":{"x":1}}',
            wait=True, poll_interval=1,
        )
        assert result["status"] == "completed"
    pause.assert_called_once_with(1)
    client.close()


@pytest.mark.parametrize("resource", ["Device", "Module"])
def test_unrelated_update_preserves_policy_auth_without_fabricating_keys(resource):
    identity = {
        "deviceId": "device", "moduleId": "module", "status": "enabled",
        "authentication": {"type": "sas", "policyResourceId": "policy", "x509CaValidation": {"value": {}}},
        "attributes": {"keep": True}, "adrDeviceProperties": {"uuid": "owned"},
    }
    assert hub._parse_auth(identity) == ("sas", None, None)
    if resource == "Module":
        projected = hub._handle_module_update_params(identity)
        assert projected["authentication"] == identity["authentication"]
        assert "adrDeviceProperties" not in projected


@pytest.mark.parametrize("auth_type", ["sas", "selfSigned", "certificateAuthority"])
def test_state_snapshot_reads_identity_metadata_for_every_auth_type(mocker, auth_type):
    from copy import deepcopy

    provider = StateProvider.__new__(StateProvider)
    authentication = {"type": auth_type, "policyResourceId": "policy", "x509CaValidation": {"value": {"keep": True}}}
    metadata = {"uuid": "source-uuid", "name": "registry-device", "etag": "owned-etag", "systemData": {"createdBy": "service"}}
    identity = {
        "authentication": authentication, "adrDeviceProperties": metadata,
        "deviceResourceId": "/source", "armSyncStatus": {"status": "InSync"},
        "attributes": {"keep": "value"},
    }
    twin = {
        "deviceId": "device", "status": "enabled", "capabilities": {"iotEdge": False},
        "authenticationType": auth_type, "x509Thumbprint": {},
        "tags": {"fresh": "value"},
        "properties": {"desired": {"$metadata": {}, "$version": 1, "value": 7}, "reported": {"notReplayed": True}},
    }
    mocker.patch("azext_iot.iothub.providers.state._iot_device_twin_list", return_value=[{"deviceId": "device"}])
    read_twin = mocker.patch("azext_iot.iothub.providers.state._iot_device_twin_show", return_value=deepcopy(twin))
    read = mocker.patch("azext_iot.iothub.providers.state._iot_device_show", return_value=identity)
    mocker.patch("azext_iot.iothub.providers.state._iot_device_module_list", return_value=[])
    snapshot = provider.download_devices({"entity": "hub"})["device"]
    read.assert_called_once()
    read_twin.assert_called_once_with(target={"entity": "hub"}, device_id="device")
    assert snapshot["identity"]["authentication"] == authentication
    assert snapshot["identity"]["adrDeviceProperties"] == metadata
    assert snapshot["identity"]["attributes"] == identity["attributes"]
    assert snapshot["twin"] == {"tags": {"fresh": "value"}, "properties": {"desired": {"value": 7}}}


def test_state_status_reason_and_extensions_are_forwarded_to_write_projection(mocker):
    provider = StateProvider.__new__(StateProvider)
    provider.target = {}
    identity = {
        "authentication": {
            "type": "sas", "symmetricKey": {"primaryKey": "primary", "secondaryKey": "secondary"},
            "x509Thumbprint": {"primaryThumbprint": None, "secondaryThumbprint": None},
        },
        "capabilities": {"iotEdge": False}, "status": "enabled", "statusReason": "wire-name",
        "attributes": {"keep": True}, "adrDeviceProperties": {"uuid": "source"},
    }
    create = mocker.patch("azext_iot.iothub.providers.state._iot_device_create")
    mocker.patch("azext_iot.iothub.providers.state._iot_device_show")
    provider.upload_device_identity("device", identity)
    assert create.call_args.kwargs["status_reason"] == "wire-name"
    assert create.call_args.kwargs["identity_properties"] is identity


@pytest.mark.parametrize("module", [False, True])
def test_state_policy_auth_without_optional_key_or_thumbprint_objects(mocker, module):
    provider = StateProvider.__new__(StateProvider)
    provider.target = {}
    identity = {
        "authentication": {"type": "sas", "policyResourceId": "policy"},
        "capabilities": {"iotEdge": False}, "status": "enabled",
    }
    name = "_iot_device_module_create" if module else "_iot_device_create"
    create = mocker.patch("azext_iot.iothub.providers.state." + name)
    mocker.patch("azext_iot.iothub.providers.state._iot_device_show")
    if module:
        provider.upload_module_identity("device", "module", identity)
    else:
        provider.upload_device_identity("device", identity)
    assert create.call_args.kwargs["primary_key"] is None
    assert create.call_args.kwargs["secondary_key"] is None
    assert create.call_args.kwargs["identity_properties"] is identity


def test_import_export_container_uri_files_preserve_the_explicit_values(tmp_path):
    incoming = tmp_path / "input.txt"
    outgoing = tmp_path / "output.txt"
    incoming.write_text("https://storage.unit.invalid/in")
    outgoing.write_text("https://storage.unit.invalid/out")
    result = hub._create_export_import_job_properties(
        "import", input_blob_container_uri=str(incoming), output_blob_container_uri=str(outgoing),
    )
    assert result["inputBlobContainerUri"] == incoming.read_text()
    assert result["outputBlobContainerUri"] == outgoing.read_text()


@pytest.mark.parametrize("operation", ["key", "edge", "configuration"])
def test_migrated_write_consumers_preserve_real_service_errors(mocker, operation):
    from azure.cli.core.azclierror import ForbiddenError

    client = adapter()
    mocker.patch.object(hub.SdkResolver, "get_sdk", return_value=client)
    mocker.patch.object(hub, "IotHubDiscovery").return_value.get_target.return_value = {"entity": "hub.unit.invalid"}
    with responses.RequestsMock() as network:
        if operation == "key":
            network.add("PUT", ENDPOINT + "/devices/device", status=403, json={"Message": "Denied."})
            with pytest.raises(ForbiddenError):
                hub._update_device_key(
                    {"entity": "hub.unit.invalid"},
                    {"deviceId": "device", "authentication": {"type": "sas", "policyResourceId": "policy"}},
                    "sas", "primary", "secondary",
                )
            assert json.loads(network.calls[0].request.body)["authentication"]["policyResourceId"] == "policy"
        elif operation == "edge":
            network.add("POST", ENDPOINT + "/devices/device/applyConfigurationContent", status=403, json={"Message": "Denied."})
            content = Path(__file__).parent / "configurations" / "test_edge_deployment.json"
            with pytest.raises(ForbiddenError):
                hub._iot_edge_set_modules({"entity": "hub.unit.invalid"}, "device", str(content))
        else:
            network.add("PUT", ENDPOINT + "/configurations/config", status=403, json={"Message": "Denied."})
            with pytest.raises(ForbiddenError):
                hub.iot_hub_configuration_update(
                    cmd=mocker.Mock(), config_id="config", parameters={
                        "id": "config", "schemaVersion": "2.0", "labels": {}, "content": {"deviceContent": {}},
                        "metrics": {"queries": {}}, "targetCondition": "*", "priority": 0,
                    },
                )
        assert len(network.calls) == 1
    client.close()


def test_identity_bad_certificate_output_directory_does_not_send_a_request(mocker, tmp_path):
    client = adapter()
    mocker.patch.object(hub.SdkResolver, "get_sdk", return_value=client)
    certificate = mocker.patch.object(hub, "_create_self_signed_cert")
    with pytest.raises(FileOperationError, match="does not exist"):
        hub._iot_device_create({"entity": "hub.unit.invalid"}, "device", output_dir=str(tmp_path / "missing"))
    certificate.assert_not_called()
    client.close()


@pytest.mark.parametrize("metrics", [{"queries": {"count": "select count() from devices"}}, {"notQueries": {}}])
def test_configuration_metrics_and_legacy_custom_labels_are_projected(mocker, metrics):
    client = adapter()
    mocker.patch.object(hub.SdkResolver, "get_sdk", return_value=client)
    with responses.RequestsMock() as network:
        if "queries" not in metrics:
            with pytest.raises(InvalidArgumentValueError, match="queries"):
                hub._iot_hub_configuration_create(
                    {"entity": "hub.unit.invalid"}, "CONFIG", '{"deviceContent":{}}', metrics=json.dumps(metrics),
                )
            assert not network.calls
        else:
            network.add("PUT", ENDPOINT + "/configurations/config", json={})
            hub._iot_hub_configuration_create(
                {"entity": "hub.unit.invalid"}, "CONFIG", '{"deviceContent":{}}',
                metrics=json.dumps(metrics), custom_labels=["owner=unit"],
            )
            body = json.loads(network.calls[0].request.body)
            assert body["labels"] == {"owner": "unit"}
            assert body["metrics"] == metrics
    client.close()


def test_configuration_without_custom_metrics_preserves_modeled_omission(mocker):
    client = adapter()
    mocker.patch.object(hub.SdkResolver, "get_sdk", return_value=client)
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/configurations/config", json={})
        hub._iot_hub_configuration_create({"entity": "hub.unit.invalid"}, "config", '{"deviceContent":{}}')
        body = json.loads(network.calls[0].request.body)
        assert isinstance(body["metrics"], dict)
        assert not body["metrics"]
        assert "labels" not in body
    client.close()
