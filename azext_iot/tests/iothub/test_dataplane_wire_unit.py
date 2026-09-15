# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""All 51 generated Hub operations: independent verb/path and API-version oracle."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import RequestsTransport

from azext_iot.sdk.iothub.device import IotHubGatewayDeviceAPIs
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs

API = "2026-11-01-preview"
ENDPOINT = "https://hub.unit.invalid"
ID = {"id": "device"}
MODULE = {"id": "device", "mid": "module"}

# Service, group, method, verb, path, invocation kwargs, status, JSON response.
# SDK-only operations are intentionally included, not counted as exposed CLI commands.
CASES = [
    ("service", "configuration", "get", "GET", "/configurations/device", ID, 200, {}),
    ("service", "configuration", "create_or_update", "PUT", "/configurations/device",
     dict(ID, configuration={"id": "device", "labels": {"k": "v"}}), 200, {}),
    ("service", "configuration", "delete", "DELETE", "/configurations/device", ID, 204, None),
    ("service", "configuration", "get_configurations", "GET", "/configurations", {}, 200, []),
    ("service", "configuration", "test_queries", "POST", "/configurations/testQueries",
     {"input": {"queries": {"count": "select count() from devices"}}}, 200, {}),
    ("service", "configuration", "apply_on_edge_device", "POST", "/devices/device/applyConfigurationContent",
     dict(ID, content={"modulesContent": {}}), 204, None),
    ("service", "statistics", "get_device_statistics", "GET", "/statistics/devices", {}, 200, {}),
    ("service", "statistics", "get_service_statistics", "GET", "/statistics/service", {}, 200, {}),
    ("service", "devices", "get_devices", "GET", "/devices", {}, 200, []),
    ("service", "devices", "get_identity", "GET", "/devices/device", ID, 200,
     {"deviceId": "device", "adrDeviceProperties": {"uuid": "owned", "name": "adr-device"}}),
    ("service", "devices", "create_or_update_identity", "PUT", "/devices/device",
     dict(ID, device={"deviceId": "device", "attributes": {"k": True}}), 200, {}),
    ("service", "devices", "delete_identity", "DELETE", "/devices/device", ID, 204, None),
    ("service", "devices", "get_twin", "GET", "/twins/device", ID, 200, {}),
    ("service", "devices", "replace_twin", "PUT", "/twins/device",
     dict(ID, device_twin_info={"tags": {"remove": None}}), 200, {}),
    ("service", "devices", "update_twin", "PATCH", "/twins/device",
     dict(ID, device_twin_info={"properties": {"desired": {"remove": None}}}), 200, {}),
    ("service", "devices", "invoke_method", "POST", "/twins/device/methods",
     {"device_id": "device", "direct_method_request": {"methodName": "noop", "payload": None}}, 200,
     {"status": 200, "payload": None}),
    ("service", "bulk_registry", "update_registry", "POST", "/devices",
     {"devices": [{"id": "device", "importMode": "createOrUpdate"}]}, 200, {}),
    ("service", "query", "get_twins", "POST", "/devices/query",
     {"query_specification": {"query": "select count() from devices"}}, 200, [{"$1": 42}]),
    ("service", "jobs", "create_import_export_job", "POST", "/jobs/create",
     {"job_properties": {"type": "export", "outputBlobContainerUri": "https://storage.unit.invalid/out"}}, 200, {}),
    ("service", "jobs", "get_import_export_jobs", "GET", "/jobs", {}, 200, []),
    ("service", "jobs", "get_import_export_job", "GET", "/jobs/device", ID, 200, {}),
    ("service", "jobs", "cancel_import_export_job", "DELETE", "/jobs/device", ID, 204, None),
    ("service", "jobs", "get_scheduled_job", "GET", "/jobs/v2/device", ID, 200, {}),
    ("service", "jobs", "create_scheduled_job", "PUT", "/jobs/v2/device",
     dict(ID, job_request={"jobId": "device", "type": "scheduleUpdateTwin", "updateTwin": {"etag": "*"}}), 200, {}),
    ("service", "jobs", "cancel_scheduled_job", "POST", "/jobs/v2/device/cancel", ID, 200, {}),
    ("service", "jobs", "query_scheduled_jobs", "GET", "/jobs/v2/query", {}, 200, [{"jobId": "device"}]),
    ("service", "cloud_to_device_messages", "purge_cloud_to_device_message_queue", "DELETE",
     "/devices/device/commands", ID, 200, {}),
    ("service", "cloud_to_device_messages", "receive_feedback_notification", "GET",
     "/messages/serviceBound/feedback", {}, 200, None),
    ("service", "cloud_to_device_messages", "complete_feedback_notification", "DELETE",
     "/messages/serviceBound/feedback/lock", {"lock_token": "lock"}, 204, None),
    ("service", "cloud_to_device_messages", "abandon_feedback_notification", "POST",
     "/messages/serviceBound/feedback/lock/abandon", {"lock_token": "lock"}, 204, None),
    ("service", "service", "bulk_regenerate_device_key", "POST", "/devices/keys/regenerate",
     {"regenerate_device_keys_request": {"policyKey": "primaryKey", "devices": [{"id": "device"}]}}, 200, {}),
    ("service", "modules", "get_twin", "GET", "/twins/device/modules/module", MODULE, 200, {}),
    ("service", "modules", "replace_twin", "PUT", "/twins/device/modules/module",
     dict(MODULE, device_twin_info={"tags": None}), 200, {}),
    ("service", "modules", "update_twin", "PATCH", "/twins/device/modules/module",
     dict(MODULE, device_twin_info={"tags": {"remove": None}}), 200, {}),
    ("service", "modules", "get_modules_on_device", "GET", "/devices/device/modules", ID, 200, []),
    ("service", "modules", "get_identity", "GET", "/devices/device/modules/module", MODULE, 200, {}),
    ("service", "modules", "create_or_update_identity", "PUT", "/devices/device/modules/module",
     dict(MODULE, module={"moduleId": "module", "attributes": {"k": True}}), 200, {}),
    ("service", "modules", "delete_identity", "DELETE", "/devices/device/modules/module", MODULE, 204, None),
    ("service", "modules", "invoke_method", "POST", "/twins/device/modules/module/methods",
     {"device_id": "device", "module_id": "module",
      "direct_method_request": {"methodName": "noop", "payload": None}}, 200, {"status": 200, "payload": None}),
    ("service", "digital_twin", "get_digital_twin", "GET", "/digitaltwins/device", ID, 200, {}),
    ("service", "digital_twin", "update_digital_twin", "PATCH", "/digitaltwins/device",
     dict(ID, digital_twin_patch=[{"op": "remove", "path": "/obsolete"}]), 202, None),
    ("service", "digital_twin", "invoke_root_level_command", "POST", "/digitaltwins/device/commands/noop",
     dict(ID, command_name="noop", payload={"value": None}), 200, {}),
    ("service", "digital_twin", "invoke_component_command", "POST",
     "/digitaltwins/device/components/component/commands/noop",
     dict(ID, component_path="component", command_name="noop", payload={"value": None}), 200, {}),
    ("device", "device", "get_devices_and_modules_in_scope", "GET",
     "/devices/device/modules/module/devicesAndModulesInDeviceScope",
     {"device_id": "device", "module_id": "module"}, 200, {}),
    ("device", "device", "get_device_and_module_in_scope", "GET",
     "/devices/device/modules/module/deviceAndModuleInDeviceScope",
     {"device_id": "device", "module_id": "module"}, 200, {}),
    ("device", "device", "send_device_event", "POST", "/devices/device/messages/events", ID, 204, None),
    ("device", "device", "receive_device_bound_notification", "GET",
     "/devices/device/messages/deviceBound", ID, 200, None),
    ("device", "device", "abandon_device_bound_notification", "POST",
     "/devices/device/messages/deviceBound/lock/abandon", dict(ID, etag="lock"), 204, None),
    ("device", "device", "create_file_upload_sas_uri", "POST", "/devices/device/files",
     {"device_id": "device", "file_upload_request": {"blobName": "file.txt"}}, 200,
     {"correlationId": "correlation", "hostName": "storage.unit.invalid"}),
    ("device", "device", "update_file_upload_status", "POST", "/devices/device/files/notifications",
     {"device_id": "device", "file_upload_completion_status": {"correlationId": "correlation", "isSuccess": True}},
     204, None),
    ("device", "device", "complete_device_bound_notification", "DELETE",
     "/devices/device/messages/deviceBound/lock", dict(ID, etag="lock"), 204, None),
]

BODY_ARGUMENTS = {
    "configuration", "input", "content", "device", "device_twin_info", "direct_method_request",
    "devices", "query_specification", "job_properties", "job_request", "regenerate_device_keys_request",
    "module", "digital_twin_patch", "payload", "file_upload_request", "file_upload_completion_status",
}


class RecordingTransport(RequestsTransport):
    def __init__(self):
        super().__init__()
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        return super().send(request, **kwargs)


@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]}.{c[1]}.{c[2]}" for c in CASES])
@pytest.mark.parametrize("failure", [False, True], ids=["success", "http-error"])
def test_every_generated_operation_wire_contract(case, failure):
    side, group, name, verb, path, kwargs, status, payload = case
    assert len(CASES) == 51
    transport = RecordingTransport()
    constructor = IotHubGatewayServiceAPIs if side == "service" else IotHubGatewayDeviceAPIs
    with constructor(
        AzureKeyCredential("SharedAccessSignature offline"), endpoint=ENDPOINT,
        transport=transport, retry_total=0,
    ) as client, responses.RequestsMock() as network:
        network.add(
            verb, ENDPOINT + path, status=403 if failure else status,
            body=json.dumps({"Message": "Forbidden"}) if failure else (json.dumps(payload) if payload is not None else ""),
            content_type="application/json",
            headers={"x-ms-command-statuscode": "201", "x-ms-continuation": "next"},
            match=[responses.matchers.query_param_matcher({"api-version": API})],
        )
        operation = getattr(getattr(client, group), name)
        observed = []

        def capture(response, data, headers):
            observed.append(response.http_response)
            return data

        if failure:
            with pytest.raises(HttpResponseError) as error:
                operation(**kwargs, cls=capture)
            assert error.value.status_code == 403
            assert not observed
        else:
            assert operation(**kwargs, cls=capture) == payload
            assert observed[0].status_code == status
            assert observed[0].headers["x-ms-continuation"] == "next"
            assert observed[0].headers["x-ms-command-statuscode"] == "201"
        assert len(transport.requests) == len(network.calls) == 1
        request = network.calls[0].request
        assert request.method == verb
        assert urlsplit(request.url).path == path
        assert parse_qs(urlsplit(request.url).query) == {"api-version": [API]}
        assert request.headers["Authorization"] == "SharedAccessSignature offline"
        bodies = [value for key, value in kwargs.items() if key in BODY_ARGUMENTS]
        if bodies:
            assert json.loads(request.body) == bodies[0]
        else:
            assert request.body in (None, b"", "")
