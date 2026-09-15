# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Explicitly leased linked/unlinked fixtures; never provision or delete their parent resources."""

import json
import os
from contextlib import ExitStack
from shlex import quote
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.exceptions import HttpResponseError
from azure.mgmt.core.tools import parse_resource_id
from msrestazure.azure_exceptions import CloudError

from azext_iot._factory import SdkResolver, adr_service_factory
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import generate_storage_account_sas_token
from azext_iot.tests.iothub._integration_helpers import wait_for_query_ids
from azext_iot.tests.iothub.devices.test_hub_preview_int import _fingerprint


def _checked(cli, command):
    result = cli.invoke(command, capture_stderr=True)
    error = result.get_error()
    if error:
        raise error
    assert result.success(), "CLI invocation failed without a structured service error."
    return result


def _absent(read):
    resource_response = None

    def observed(response):
        nonlocal resource_response
        resource_response = response.http_response

    try:
        read(raw_response_hook=observed)
    except (CloudError, HttpResponseError) as error:
        if (
            resource_response is not None and resource_response.status_code == 404
            and error.response is not None and error.response.status_code == 404
        ):
            return True
        raise
    return False


def _wait(read, ready, label, timeout=300):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        value = read()  # Service/credential errors are never retried.
        remaining = deadline - monotonic()
        if remaining < 0:
            break
        if ready(value):
            return value
        sleep(min(2, remaining))
    raise AssertionError(f"{label} did not complete within its {timeout}s elapsed-time deadline.")


def _cleanup_device(client, identifier, sent_deletes):
    def read(**kwargs):
        return client.devices.get_identity(id=identifier, timeout=30, **kwargs)

    if not _absent(read) and identifier not in sent_deletes:
        sent_deletes.add(identifier)  # Never replay an accepted or uncertain DELETE.
        client.devices.delete_identity(id=identifier, if_match="*", timeout=30)
    _wait(lambda: _absent(read), bool, "Owned Hub identity deletion")
    print(json.dumps({"hubPreviewCleanup": "GET404", "deviceId": identifier}), flush=True)


def _cleanup_devices(client, identifiers, sent_deletes, pending_jobs=None):
    assert not pending_jobs, "Refusing identity deletion while an owned service job remains undrained."
    with ExitStack() as cleanup:
        for identifier in identifiers:
            cleanup.callback(_cleanup_device, client, identifier, sent_deletes)


def _job_finished(client, job_id):
    job = {}

    def read(**kwargs):
        nonlocal job
        job = client.jobs.get_import_export_job(id=job_id, timeout=30, **kwargs)

    if _absent(read):
        return True
    return job["status"] in ("completed", "failed", "cancelled")


def _drain_job(lease, entry):
    index, job_id = entry
    assert job_id, "An import/export submission has no confirmed job ID; refusing destructive cleanup."
    client = lease.clients[index]
    if not _job_finished(client, job_id):
        client.jobs.cancel_import_export_job(id=job_id, timeout=30)
    _wait(lambda: _job_finished(client, job_id), bool, f"Owned job {job_id} cancellation")
    lease.pending_jobs.remove(entry)


def _drain_jobs(lease):
    with ExitStack() as cleanup:
        for entry in list(lease.pending_jobs):
            cleanup.callback(_drain_job, lease, entry)


@pytest.fixture
def preview_lease():
    assert os.getenv("AZURE_TEST_RUN_LIVE", "").casefold() == "true", "This explicit lease requires AZURE_TEST_RUN_LIVE=True."
    required = (
        "azext_iot_hub_preview_source", "azext_iot_hub_preview_destination",
        "azext_iot_hub_preview_namespace", "azext_iot_hub_preview_owner",
        "azext_iot_hub_preview_storage_connection_string",
    )
    missing = [name for name in required if not os.getenv(name)]
    assert not missing, f"Explicit preview resource lease is required; missing: {', '.join(missing)}"
    owner = os.environ[required[3]]
    identifiers = [os.environ[name].rstrip("/") for name in required[:3]]
    resources = [parse_resource_id(identifier) for identifier in identifiers]
    for resource, kind in zip(resources, ("iothubs", "iothubs", "namespaces")):
        assert resource.get("type", "").casefold() == kind
        assert all(resource.get(name) for name in ("subscription", "resource_group", "name"))
    assert identifiers[0].casefold() != identifiers[1].casefold(), "Source and destination must be distinct."
    cli = EmbeddedCLI()
    scopes = [
        f"-n {quote(resource['name'])} -g {quote(resource['resource_group'])} "
        f"--subscription {quote(resource['subscription'])}"
        for resource in resources[:2]
    ]
    hubs = [_checked(cli, f"iot hub show {scope}").as_json() for scope in scopes]
    namespace = resources[2]
    with ExitStack() as cleanup:
        registry_client = adr_service_factory(cli.az_cli, subscription_id=namespace["subscription"])
        cleanup.callback(registry_client.close)
        namespace_args = {"resource_group_name": namespace["resource_group"], "namespace_name": namespace["name"]}
        namespace_view = registry_client.namespaces.get(**namespace_args, retry_total=0)
        for resource in [*hubs, namespace_view]:
            assert (resource.get("tags") or {}).get("hubPreviewOwner") == owner, "Parent resource is not leased to this run."
        endpoints = namespace_view["properties"]["messaging"]["endpoints"].values()
        assert any(endpoint.get("resourceId", "").casefold() == identifiers[0].casefold() for endpoint in endpoints)
        assert hubs[0]["properties"].get("deviceRegistry"), "Source Hub has no active ADR projection."
        assert not hubs[1]["properties"].get("deviceRegistry"), "Destination must be unlinked."
        assert not list(registry_client.namespace_devices.list_by_namespace(**namespace_args, retry_total=0)), (
            "Refusing a namespace containing existing registry devices."
        )
        clients = []
        for hub in hubs:
            properties = hub["properties"]
            client = SdkResolver({
                "entity": properties.get("serviceHostName") or properties["hostName"],
                "policy": "login", "cmd": SimpleNamespace(cli_ctx=cli.az_cli),
            }).get_sdk(SdkType.service_sdk)
            cleanup.callback(client.close)
            assert client.devices.get_devices(top=1, timeout=30) == [], "Refusing a Hub containing pre-existing devices."
            clients.append(client)
        owned_registry = {}
        pending_jobs = []
        planned = [[], []]
        sent_deletes = [set(), set()]

        def clean_registry():
            assert not pending_jobs, "Refusing registry deletion while an owned service job remains undrained."
            for identifier in planned[0]:
                assert _absent(lambda **kwargs: clients[0].devices.get_identity(id=identifier, timeout=30, **kwargs)), (
                    "Refusing registry deletion before the corresponding Hub identities are absent."
                )
            for name, expected_uuid in owned_registry.items():
                arguments = dict(
                    namespace_args, device_name=name, retry_total=0, connection_timeout=30, read_timeout=30,
                )

                def read(**kwargs):
                    return registry_client.namespace_devices.get(**arguments, **kwargs)

                if not _absent(read):
                    record = read()
                    assert record["properties"]["uuid"] == expected_uuid, "Registry ownership changed; refusing DELETE."
                    # Disable the SDK polling thread; verify absence ourselves
                    # with bounded GETs after the one accepted DELETE.
                    registry_client.namespace_devices.begin_delete(**arguments, polling=False).result()
                _wait(lambda: _absent(read), bool, "Owned registry identity deletion")
                print(json.dumps({"hubPreviewRegistryCleanup": "GET404", "name": name, "uuid": expected_uuid}), flush=True)

        cleanup.callback(clean_registry)
        for client, devices, deleted in zip(clients, planned, sent_deletes):
            cleanup.callback(_cleanup_devices, client, devices, deleted, pending_jobs)
        yield SimpleNamespace(
            cli=cli, scopes=[scope + " --auth-type login" for scope in scopes],
            clients=clients, planned=planned, registry=registry_client.namespace_devices,
            namespace_args=namespace_args, owned_registry=owned_registry,
            pending_jobs=pending_jobs,
            sent_deletes=sent_deletes,
            storage_connection_string=os.environ[required[4]],
        )


@pytest.fixture
def preview_container(preview_lease):
    from azure.storage.blob import ContainerClient

    name = "hub-preview-" + uuid4().hex
    with ContainerClient.from_connection_string(
        preview_lease.storage_connection_string, name, retry_total=0, connection_timeout=30, read_timeout=30,
    ) as container:
        assert _absent(container.get_container_properties), "Refusing a pre-existing Blob container."
        print(json.dumps({"hubPreviewOwnedContainer": name, "account": container.account_name}), flush=True)
        try:
            container.create_container()
            token = generate_storage_account_sas_token(
                preview_lease.storage_connection_string, read=True, write=True, create=True, add=True, delete=True,
            )
            yield container, container.url + "?" + token
        finally:
            _drain_jobs(preview_lease)
            if not _absent(container.get_container_properties):
                container.delete_container()
            _wait(lambda: _absent(container.get_container_properties), bool, "Owned Blob container deletion")
            print(json.dumps({"hubPreviewContainerCleanup": "GET404", "container": name}), flush=True)


def _query_ready(lease, index, devices):
    wait_for_query_ids(
        lambda: _checked(
            lease.cli, f'iot hub query {lease.scopes[index]} -q "select deviceId from devices"',
        ).as_json(),
        devices, id_key="deviceId", timeout=300,
    )


def _job_completed(lease, index, job_id):
    entry = (index, job_id)
    assert entry in lease.pending_jobs, "Cannot poll an untracked import/export job."
    print(json.dumps({"hubPreviewOwnedJob": job_id, "hubIndex": index}), flush=True)

    def read():
        job = _checked(lease.cli, f"iot hub job show {lease.scopes[index]} --job-id {quote(job_id)}").as_json()
        status = job["status"]
        assert status not in ("failed", "cancelled"), f"Owned import/export job {job_id} ended as {status}."
        return status

    _wait(read, lambda status: status == "completed", f"Import/export job {job_id}", timeout=600)
    lease.pending_jobs.remove(entry)


def _submit_job(lease, index, command):
    uncertain = (index, None)
    lease.pending_jobs.append(uncertain)
    result = _checked(lease.cli, command).as_json()
    job_id = result.get("jobId") if isinstance(result, dict) else None
    assert isinstance(job_id, str) and job_id, "Import/export response omitted its confirmed job ID."
    lease.pending_jobs[lease.pending_jobs.index(uncertain)] = (index, job_id)
    _job_completed(lease, index, job_id)
    return result


@pytest.mark.timeout(2700, func_only=False)
def test_linked_metadata_state_and_service_bulk_portability(preview_lease, preview_container, tmp_path):
    lease = preview_lease
    source, destination = lease.clients
    parent, child = ["preview-" + uuid4().hex for _ in range(2)]
    module = "preview-module"
    metadata = {}
    for device in (parent, child):
        assert _absent(lambda **kwargs: source.devices.get_identity(id=device, timeout=30, **kwargs))
        lease.planned[0].append(device)
        _checked(lease.cli, f"iot hub device-identity create {lease.scopes[0]} -d {device} --ee")
        identity = _wait(
            lambda: source.devices.get_identity(id=device, timeout=30),
            lambda value: bool((value.get("adrDeviceProperties") or {}).get("uuid")),
            "Authoritative linked identity metadata",
        )
        metadata[device] = identity["adrDeviceProperties"]
        owned = metadata[device]
        assert owned.get("name") and owned.get("etag") and isinstance(owned.get("systemData"), dict)
        lease.owned_registry[owned["name"]] = owned["uuid"]
        registry = lease.registry.get(**lease.namespace_args, device_name=owned["name"], retry_total=0)
        assert registry["properties"]["uuid"] == owned["uuid"]
        assert registry["name"] == owned["name"]
        print(json.dumps({"hubPreviewOwned": device, "registryName": owned["name"], "registryUuid": owned["uuid"]}), flush=True)
    attributes = json.dumps({"owner": child})
    _checked(
        lease.cli, f"iot hub device-identity update {lease.scopes[0]} -d {child} "
        f"--status-reason portability --set {quote('attributes=' + attributes)}",
    )
    _checked(lease.cli, f"iot hub device-identity parent set {lease.scopes[0]} -d {child} --pd {parent}")
    _checked(lease.cli, f"iot hub device-identity renew-key {lease.scopes[0]} -d {child} --kt swap")
    _checked(lease.cli, f"iot hub module-identity create {lease.scopes[0]} -d {child} -m {module}")
    _checked(
        lease.cli, f"iot hub module-identity update {lease.scopes[0]} -d {child} -m {module} "
        f"--set {quote('attributes=' + attributes)}",
    )
    with pytest.raises(InvalidArgumentValueError, match="owned"):
        _checked(lease.cli, f"iot hub device-identity update {lease.scopes[0]} -d {child} --set adrDeviceProperties.uuid=forged")
    for device in (parent, child):
        current = source.devices.get_identity(id=device, timeout=30)
        assert current["adrDeviceProperties"]["uuid"] == metadata[device]["uuid"]
    _query_ready(lease, 0, (parent, child))
    snapshot_path = tmp_path / "snapshot.json"
    _checked(lease.cli, f"iot hub state export {lease.scopes[0]} --aspects devices -f {quote(str(snapshot_path))}")
    snapshot = json.loads(snapshot_path.read_text())
    assert set(snapshot["devices"]) == {parent, child}, "Source ownership changed before snapshot export."
    for device in (parent, child):
        assert snapshot["devices"][device]["identity"]["adrDeviceProperties"]["uuid"] == metadata[device]["uuid"]
        assert _absent(lambda **kwargs: destination.devices.get_identity(id=device, timeout=30, **kwargs))
        lease.planned[1].append(device)
    _checked(lease.cli, f"iot hub state import {lease.scopes[1]} --aspects devices -f {quote(str(snapshot_path))}")
    _query_ready(lease, 1, (parent, child))
    restored = destination.devices.get_identity(id=child, timeout=30)
    assert not restored.get("adrDeviceProperties"), "State import replayed source-owned ADR identity data."
    assert restored["attributes"] == {"owner": child}
    assert restored["statusReason"] == "portability"
    assert restored["parentScopes"] == [destination.devices.get_identity(id=parent, timeout=30)["deviceScope"]]
    expected_auth = _fingerprint(snapshot["devices"][child]["identity"]["authentication"])
    actual_auth = _fingerprint(restored["authentication"])
    assert actual_auth == expected_auth
    restored_module = destination.modules.get_identity(id=child, mid=module, timeout=30)
    assert restored_module["attributes"] == {"owner": child}
    _cleanup_devices(destination, lease.planned[1], lease.sent_deletes[1])

    container, uri = preview_container
    _submit_job(lease, 0, f"iot hub device-identity export {lease.scopes[0]} --bcu {quote(uri)} --ik true")
    records = [json.loads(line) for line in container.download_blob("devices.txt").readall().splitlines() if line]
    exported_devices = {record["id"]: record for record in records if not record.get("moduleId")}
    assert set(exported_devices) == {parent, child}
    for device in (parent, child):
        assert exported_devices[device]["adrDeviceProperties"]["uuid"] == metadata[device]["uuid"]
    # Choose import intent explicitly, but do NOT sanitize ADR metadata in the
    # blob: the CLI submits its URI, and the service's portability contract is
    # what this test must establish (a rejection is a genuine backend blocker).
    for record in records:
        record["importMode"] = "createOrUpdate"
    container.upload_blob(
        "devices.txt", b"\n".join(json.dumps(record).encode() for record in records), overwrite=True,
    )
    # A new explicit import starts a new lifecycle only after prior GET404s.
    lease.sent_deletes[1].difference_update(lease.planned[1])
    _submit_job(
        lease, 1, f"iot hub device-identity import {lease.scopes[1]} --ibcu {quote(uri)} --obcu {quote(uri)}",
    )
    for device in (parent, child):
        restored = destination.devices.get_identity(id=device, timeout=30)
        assert not restored.get("adrDeviceProperties"), "Bulk import rebound a source-owned ADR identity."
        expected_auth = _fingerprint(source.devices.get_identity(id=device, timeout=30)["authentication"])
        actual_auth = _fingerprint(restored["authentication"])
        assert actual_auth == expected_auth
