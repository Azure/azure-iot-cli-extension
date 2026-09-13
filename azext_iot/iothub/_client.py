# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Small maintained bridge from Hub CLI conventions to modeless Azure Core SDKs."""

from functools import partial
import inspect
from types import SimpleNamespace
from urllib.parse import urlsplit

import requests
from azure.cli.core.azclierror import FileOperationError
from azure.core.exceptions import HttpResponseError, map_error
from azure.core.utils import case_insensitive_dict
from msrestazure.azure_exceptions import CloudError

from azext_iot.iothub._payload import project


_BODIES = {
    ("devices", "create_or_update_identity"): ("device", "Device"),
    ("modules", "create_or_update_identity"): ("module", "Module"),
    ("devices", "update_twin"): ("device_twin_info", "Twin"),
    ("modules", "update_twin"): ("device_twin_info", "Twin"),
    ("configuration", "create_or_update"): ("configuration", "Configuration"),
    ("configuration", "apply_on_edge_device"): ("content", "ConfigurationContent"),
    ("jobs", "create_scheduled_job"): ("job_request", "JobRequest"),
    ("jobs", "create_import_export_job"): ("job_properties", "JobProperties"),
    ("device", "create_file_upload_sas_uri"): ("file_upload_request", "FileUploadRequest"),
    ("device", "update_file_upload_status"): ("file_upload_completion_status", "FileUploadCompletionStatus"),
}


def _response(response):
    """Expose the requests-style raw contract used by messaging and query consumers."""
    result = requests.Response()
    result.status_code = response.status_code
    result.headers.update(response.headers)
    result._content = response.content  # pylint: disable=protected-access
    result._content_consumed = True  # pylint: disable=protected-access
    result.reason = response.reason
    result.encoding = "utf-8"
    return result


def _capture(pipeline_response, _deserialized, _headers):
    return SimpleNamespace(response=_response(pipeline_response.http_response))


class HubOperationGroup:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.operations = getattr(client.sdk, name)
        self.config = client.config

    def __getattr__(self, name):
        if name == "upload_file_to_container":
            return upload_file_to_container
        return partial(self._call, name)

    def _call(self, name, *args, **kwargs):
        raw = kwargs.pop("raw", False)
        headers = case_insensitive_dict(kwargs.pop("custom_headers", {}))
        if_match = kwargs.pop("if_match", None)
        if if_match is not None:
            headers["If-Match"] = if_match
        timeout = kwargs.pop("timeout", None)
        if timeout is not None:
            kwargs.update(connection_timeout=timeout, read_timeout=timeout)
        # CLI controls retries explicitly; do not replay uncertain mutations.
        kwargs.setdefault("retry_total", 0)
        kwargs["headers"] = headers
        if self.name == "jobs" and name == "query_scheduled_jobs":
            kwargs.update(zip(("job_type", "job_status"), args))
            args = ()
        if self.name == "query" and name == "get_twins" and args and isinstance(args[0], str):
            args = ({"query": args[0]},) + args[1:]
        if name == "bulk_regenerate_device_key_method":
            name = "bulk_regenerate_device_key"
            kwargs["regenerate_device_keys_request"] = {
                "policyKey": kwargs.pop("policy_key"), "devices": kwargs.pop("devices")
            }
        if self.name == "device" and name == "create_file_upload_sas_uri" and "blob_name" in kwargs:
            kwargs["file_upload_request"] = {"blobName": kwargs.pop("blob_name")}
        if self.name == "device" and name == "complete_device_bound_notification":
            reject = kwargs.pop("reject", None)
            if reject is not None:
                kwargs["params"] = dict(kwargs.pop("params", None) or {}, reject=reject)
        body = _BODIES.get((self.name, name))
        if body or name in ("replace_twin", "invoke_method", "invoke_root_level_command", "invoke_component_command"):
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        if body:
            key, model = body
            # Some existing callers pass the body positionally.
            bound = inspect.signature(getattr(self.operations, name)).bind_partial(*args, **kwargs)
            if key in bound.arguments:
                value = project(model, bound.arguments[key])
                if key in kwargs:
                    kwargs[key] = value
                else:
                    position = list(inspect.signature(getattr(self.operations, name)).parameters).index(key)
                    args = args[:position] + (value,) + args[position + 1:]
        resource_response = None
        response_hook = kwargs.pop("raw_response_hook", None)

        def observe_response(pipeline_response):
            nonlocal resource_response
            if response_hook is not None:
                response_hook(pipeline_response)
            resource_response = pipeline_response.http_response

        kwargs["raw_response_hook"] = observe_response
        try:
            if self.name == "device" and name == "receive_device_bound_notification":
                return self._receive_device_bound_notification(*args, raw=raw, **kwargs)
            if self.name == "device" and name == "send_device_event":
                from azext_iot.sdk.iothub.device.operations._operations import build_device_send_device_event_request
                request = build_device_send_device_event_request(
                    id=kwargs.pop("id"), content=kwargs.pop("message"),
                    headers=headers, api_version=self.client.sdk._config.api_version,
                )
                kwargs.pop("headers")
                response = self.client.sdk.send_request(request, **kwargs)
                if response.status_code != 204:
                    raise HttpResponseError(response=response)
                return SimpleNamespace(response=_response(response)) if raw else None
            if raw:
                kwargs["cls"] = _capture
            return getattr(self.operations, name)(*args, **kwargs)
        except HttpResponseError as error:
            if error.response is None or error.response is not resource_response:
                raise
            # Earlier Hub SDKs explicitly accepted 200 as well as 204 here.
            # Preserve that successful response without replaying the POST.
            if self.name == "configuration" and name == "apply_on_edge_device" and error.status_code == 200:
                return SimpleNamespace(response=_response(error.response)) if raw else None
            raise CloudError(_response(error.response), error=error.message) from error

    def _receive_device_bound_notification(self, id, raw=False, **kwargs):
        """C2D content is opaque, not a JSON/XML document described by its HTTP media type."""
        from azext_iot.sdk.iothub.device.operations._operations import build_device_receive_device_bound_notification_request

        request = build_device_receive_device_bound_notification_request(
            id=id, api_version=self.client.sdk._config.api_version,
            headers=kwargs.pop("headers"), params=kwargs.pop("params", None),
        )
        hook = kwargs.pop("raw_response_hook")
        callback = kwargs.pop("cls", None)
        error_map = kwargs.pop("error_map", None) or {}
        captured = None

        def receive_response(pipeline_response):
            nonlocal captured
            # Buffer bytes and close even if reading or a user hook fails. The
            # supported stream=True request option skips ContentDecodePolicy;
            # generated receive's stream=False would parse before its cls hook.
            with pipeline_response.http_response as response:
                response.read()
                hook(pipeline_response)
            captured = pipeline_response

        response = self.client.sdk.send_request(request, stream=True, raw_response_hook=receive_response, **kwargs)
        if response.status_code not in (200, 204):
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            raise HttpResponseError(response=response)
        if raw:
            return _capture(captured, None, {})
        if callback:
            return callback(captured, None, {})
        return None


class HubClient:
    """Expose the CLI's raw/header conventions without modifying generated SDKs."""

    device: HubOperationGroup
    devices: HubOperationGroup
    modules: HubOperationGroup
    configuration: HubOperationGroup
    statistics: HubOperationGroup
    bulk_registry: HubOperationGroup
    query: HubOperationGroup
    jobs: HubOperationGroup
    cloud_to_device_messages: HubOperationGroup
    service: HubOperationGroup
    digital_twin: HubOperationGroup

    def __init__(self, sdk, groups):
        self.sdk = sdk
        self.config = sdk._config  # pylint: disable=protected-access
        for name in groups:
            setattr(self, name, HubOperationGroup(self, name))

    def close(self):
        self.sdk.close()


def upload_file_to_container(storage_endpoint, content, content_type):
    """Upload to the separately signed Blob URL, without Hub credentials or redirects."""
    url = "https://" + storage_endpoint
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise FileOperationError("Invalid storage upload endpoint.")
    if isinstance(content, str):
        content = content.encode("utf-8")
    headers = {"x-ms-blob-type": "BlockBlob", "Content-Type": content_type, "Content-Length": str(len(content))}
    try:
        response = requests.put(url, data=content, headers=headers, timeout=60, allow_redirects=False)
    except requests.RequestException:
        raise FileOperationError("Storage upload transport failed.") from None
    if response.status_code not in (200, 201):
        raise FileOperationError(f"Storage upload failed with HTTP {response.status_code}.")
    return response
