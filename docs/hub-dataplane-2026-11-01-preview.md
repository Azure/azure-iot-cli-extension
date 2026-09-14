# Hub HTTP dataplane: 2026-11-01-preview

This update changes the **Hub service and device HTTP clients**, not the Hub
management API, DPS, ADR, or the MQTT/AMQP protocol libraries. CLI command names
remain unchanged. Digital-twin show/update/invoke-command additionally accept the
standard Hub `--auth-type {key,login}` option and configured authentication default.
Previously those handlers did not propagate authentication selection, leaving
PnP calls on the shared-key path even in an Entra-configured environment.

## Generation provenance and interfaces

Both Swagger 2.0 inputs were pinned to source commit
`0feb01f04079a1d4ae40196da9311926912cee1c` and verified as Git blobs:

| Input | Git blob |
| --- | --- |
| `Service_2026-11-01-preview.json` | `4223a1a1cc8ceace064a0f67d76ce9590db468f0` |
| `Device_2026-11-01-preview.json` | `358292a1cd093e84ae41d0306c32617dda73f26d` |

The private source documents are **not included** in this repository. Generation
used cached AutoRest Core **3.10.8**, Python **6.32.3**, ModelerFour **4.27.2**,
and Node **20.19.2**, with isolated output and a complete pre-replacement backup.
These are OpenAPI inputs, not TypeSpec inputs.

Common verified generator settings:

```text
--azure-arm=false --version-tolerant=true
--models-mode=none --no-async=true
--add-credential=true
--credential-default-policy-type=AzureKeyCredentialPolicy
--credential-key-header-name=Authorization
--no-namespace-folders=true --basic-setup-py=false
--package-version=2026-11-01-preview --black=true
--license-header=MICROSOFT_MIT_NO_VERSION
```

The namespaces and historical exported names remain:

| Namespace | Client |
| --- | --- |
| `azext_iot.sdk.iothub.service` | `IotHubGatewayServiceAPIs` |
| `azext_iot.sdk.iothub.device` | `IotHubGatewayDeviceAPIs` |

Use the matching `--namespace` and `--override-client-name` for each input.
Do not generate over a dirty destination or hand-edit the emitted packages.
Neither package contains `models` or `aio`. The generated route surface remains
**43 service operations on 29 paths and eight device operations on eight paths**.

The previous embedded API versions were service **2024-03-31** and device
**2019-10-01**. Both now send **2026-11-01-preview** on actual HTTP requests.

Important generated-interface changes:

- Constructors use `credential=` and keyword-only `endpoint=`, not
  `credentials=` and `base_url=`.
- Results/bodies are JSON dictionaries rather than MSRest model instances.
- Operations use Azure Core exceptions, `headers`, `params`, and `cls`;
  legacy `raw`, `custom_headers`, and exact `If-Match` behavior are maintained
  outside generated code.
- `bulk_regenerate_device_key_method` became `bulk_regenerate_device_key`;
  the request is now `regenerate_device_keys_request`.
- SQL queries require a `query_specification` body; upload allocation requires
  a `file_upload_request` body. Maintained adapters translate the existing callers.
- The new apply-configuration operation declares 204 only. The adapter also
  retains the older successful 200 contract, without repeating the POST.

## Maintained contracts

`iothub/_authentication.py`, `_client.py`, and `_payload.py` hold the handwritten
behavior. Factories always replace the generated key-header policy with the
Hub policy: refreshed service Entra/SAS, device SAS, the existing
`https://iothubs.azure.net` audience, and the discovered service/device hostname
split. An origin change, insecure endpoint, raw key, or SAS-as-Bearer value is
not accepted. Automatic redirects/replays are disabled. Existing explicit,
bounded service-throttling handling remains in its callers.

The adapters retain:

- HTTP D2C bodies, absent from the device Swagger.
- C2D rejection by query-parameter **presence**, including `reject=`.
- Arbitrary query projections/aggregates, continuation headers and scheduled-job
  query/header translation.
- Explicit `payload: null` in direct-method envelopes.
- Dictionary-preserving twin replacement and nested JSON deletion markers.
- Raw C2D bytes, ETags, void responses and PnP command-status headers.
- A separately signed Blob PUT, with raw file bytes, byte-accurate length,
  no Hub credentials/API version, no redirects, and truthful completion
  notification. Failed notification must not hide an earlier upload failure.

The old models had **no read-only validation declarations**. The update does not
recursively remove `status`, `etag`, `reported`, or null dictionary entries.
Resource-specific projections retain modeled-property None omission, aliases,
datetime serialization, authentication extensions, attributes and relationships.

### ADR ownership and portability

`adrDeviceProperties` is declared on **Device** and **ExportImportDevice**, not
Twin. Its shape is `uuid`, `name`, `etag`, and `systemData`. The description of
ExportImportDevice mentions additional fields not present in that shape; no
commands or flags are inferred from those descriptions.

Identity reads retain the new metadata, as well as the older 2025
`deviceResourceId`, `armSyncStatus`, authentication `policyResourceId` and
`x509CaValidation` fields. Implicit identity writes exclude ADR/ARM-owned
`adrDeviceProperties`, `deviceResourceId` and `armSyncStatus`. Explicit generic
device-identity mutations of those top-level properties fail clearly. User
attributes with the same nested names remain user data.

State export uses queries to discover device IDs, then direct identity and twin
GETs for authoritative authentication, metadata, tags and desired properties.
Stale or incomplete query projections are not used as device-twin snapshots.
A failed direct device-twin read stops export/migration before replacing an
existing snapshot file or changing the destination. Enumeration still depends
on query visibility, and snapshots are not atomic against concurrent writes.
Snapshots retain source metadata;
restore preserves writable authentication/attribute extensions and restores
parents against destination identities, without replaying source ownership.

**Service-managed import/export is different:** the CLI submits Blob URIs, not
individual records. It does not silently read/rewrite customer import blobs.
The leased integration case preserves exported ADR metadata in the submitted
records to establish the backend's portability contract. A backend rejection is
a real failure/blocker, not something to hide by sanitizing the test input.

## Operation-to-CLI coverage inventory

Every named operation below has an individual real-generated-SDK success/error
transport case in `tests/iothub/test_dataplane_wire_unit.py`. Those 51 cases assert
exact verb/path, exact API query, JSON/no-body behavior and callback results.
`test_dataplane_adapter_unit.py`, `test_dataplane_cli_unit.py` and existing
consumer units cover the maintained seams and actual parser/factory behavior.
`test_preview_auth_switch_unit.py` exercises repeated key/login/connection-string
CLI invocations in one context, including invoke-only authorization failures and
token-acquisition failures without credential reuse or automatic fallback.

The following table names **all 42 CLI-used generated operations**. Paths use
the SDK's operation group names. Existing suites supply broad behavioral
coverage; the new cases add metadata/auth/portability and responding-PnP proof.

| Operations | CLI consumers | Live selectors beneath `azext_iot/tests/iothub/` |
| --- | --- | --- |
| `configuration.get`, `create_or_update`, `delete`, `get_configurations` | `iot hub configuration`, `iot edge deployment`; state/config composites | `configurations/*_int.py`, `state/test_hub_state_dataplane_int.py` |
| `configuration.apply_on_edge_device` | `iot edge set-modules`, `iot edge devices create`, deployment composites | `configurations/*_int.py`, `devices/test_iot_edge_devices_create_int.py` |
| `devices.get_devices` | identity listing, owned state preflight | `devices/test_iothub_devices_int.py`, `state/*_int.py`, leased metadata case |
| `devices.get_identity` | identity show/update/keys/connection strings, simulation, monitoring, state | device/core suites; both new preview cases; leased metadata case |
| `devices.create_or_update_identity` | identity create/update/keys/parents/children, nested Edge, state | device/nested-Edge suites; `devices/test_hub_preview_int.py::TestHubPreview::test_identity_roundtrip`; leased metadata case |
| `devices.delete_identity` | identity delete, owned cleanup/state | device/state suites and all new owned cohorts |
| `devices.get_twin`, `update_twin`, `replace_twin` | device twin show/update/replace, tracing, state | `devices/test_iothub_device_twin_int.py`, core/state suites |
| `devices.invoke_method` | `iot hub invoke-device-method`, simulation | `devices/test_iothub_devices_int.py`, core messaging cases |
| `modules.get_identity`, `get_modules_on_device` | module show/list, keys/connection strings, Edge export, state | `modules/test_iothub_modules_int.py`, configurations/state and new identity/metadata cases |
| `modules.create_or_update_identity`, `delete_identity` | module CRUD/keys, nested Edge, state | module/Edge/state suites and new identity/metadata cases |
| `modules.get_twin`, `update_twin`, `replace_twin` | module twin show/update/replace and state | `modules/test_iothub_module_twin_int.py`, state suites |
| `modules.invoke_method` | `iot hub invoke-module-method` | module integration suite |
| `query.get_twins` | `iot hub query`, twin lists, metrics, state, monitor filtering, Edge discovery | core/configuration/device/state suites; exact-cohort monitor and metadata cases |
| `jobs.create_import_export_job` | identity import/export | `core/test_iothub_storage_int.py`, leased metadata case |
| `jobs.get_import_export_jobs`, `get_import_export_job` | job list/show, import/export polling | storage and leased metadata cases |
| `jobs.cancel_import_export_job` | cancellation of v1 import/export jobs | leased metadata cleanup if an owned job is still active; see qualification below |
| `jobs.create_scheduled_job`, `get_scheduled_job`, `query_scheduled_jobs`, `cancel_scheduled_job` | job create/show/list/cancel | `jobs/test_iothub_jobs_int.py` |
| `cloud_to_device_messages.purge_cloud_to_device_message_queue` | `iot device c2d-message purge` | HubSAS HTTP C2D/core messaging cases |
| `service.bulk_regenerate_device_key` | device/module `renew-key` | device/module integration suites; identity roundtrip additionally covers swap's identity PUT |
| `digital_twin.get_digital_twin`, `update_digital_twin`, `invoke_root_level_command`, `invoke_component_command` | digital-twin show/update/invoke-command | `devices/test_hub_preview_int.py::TestHubPreview::test_responding_digital_twin` |
| `device.send_device_event` | HTTP send/simulate | HubSAS/core messaging cases; binary body adapter contracts |
| `device.receive_device_bound_notification`, `complete_device_bound_notification`, `abandon_device_bound_notification` | HTTP C2D receive/complete/reject/abandon | HubSAS HTTP C2D/core messaging cases |
| `device.create_file_upload_sas_uri`, `update_file_upload_status` | `iot device upload-file` | HubSAS upload case, including separate binary Blob verification |

Nine operations have **no current CLI callsite** and are not presented as live
CLI coverage: `bulk_registry.update_registry`, `configuration.test_queries`,
both `statistics` GETs, service HTTP feedback receive/complete/abandon, and both
device-scope GETs. They are included in the 51-operation wire suite. AMQP
feedback monitoring does **not** exercise the three unused HTTP feedback routes.
Blob PUT and the C2D reject variant have additional adapter contracts.

Qualification: v1 job cancellation needs an in-flight owned import/export job.
The leased scenario drains/cancels such jobs on failure; a normal fast successful
run need not exercise that DELETE. Report whether it actually ran, rather than
claiming a guaranteed live cancellation success. Its generated HTTP success and
error contracts are covered deterministically offline.

## Required live execution

These commands are for the resource owner to execute after review/publication.
Do not mix live coverage into the unit-only coverage gate.

1. Run the existing **HubMgmt-int** suite: configurations, core, jobs, state and
   TLS. Despite its name, this includes substantial dataplane coverage.
2. Run **HubData-int**: devices, messaging, modules and message endpoints. It now
   includes the owned identity and responding-PnP cases.
3. Run the complete **HubSAS-int** entry point, serially, upload first. All eight
   required cases must pass with no skips and complete owned cleanup. Do not
   use `-k`, deselect nodes, enable reruns, or weaken its receipt gate.
4. Run the leased linked/unlinked case explicitly:

```text
pytest -c setup.cfg -vv -n 0 -p no:rerunfailures \
  azext_iot/tests/iothub/metadata/test_hub_metadata_int.py \
  --capture=fd -o log_cli=false --tb=short
```

That case requires `AZURE_TEST_RUN_LIVE=True` and:

| Environment variable | Required value |
| --- | --- |
| `azext_iot_hub_preview_source` | Full ARM ID of an otherwise empty, actively ADR-linked Hub |
| `azext_iot_hub_preview_destination` | Full ARM ID of a distinct, empty, unlinked Hub |
| `azext_iot_hub_preview_namespace` | Full ARM ID of the linked namespace, with no registry devices |
| `azext_iot_hub_preview_owner` | Exclusive run lease value matching the `hubPreviewOwner` tag on all three parent resources |
| `azext_iot_hub_preview_storage_connection_string` | Secret connection string for an owner-approved Storage account |

The caller needs Hub data permissions on both Hubs, read access to the parent
resources, and permission to read/delete the newly auto-created registry devices.
The existing namespace messaging endpoint must reference the source Hub.
Do not share these fixtures with another writer.

The test creates two uniquely named Edge identities, a child module and one
unique Blob container; records their non-secret IDs; and checks linked UUIDs
against authoritative registry GETs. It exercises readonly rejection, parent/key
writes, state export/import and service-managed export/import to the unlinked
destination. No parent Hub, namespace, account, identity, link or role is created,
reconfigured or deleted by this test.

Cleanup tracks planned IDs, does not resend accepted/uncertain DELETEs, drains
known service jobs first, and verifies native resource-response GET404.
Credential/factory HTTP404 is not absence. Registry deletion additionally checks
the recorded UUID and requires the source Hub identities to be absent. No
unbounded ARM polling thread is started. Failure to drain a job blocks destructive
resource cleanup and must be reported to the resource owner.
An unconfirmed job ID after submission also blocks destructive cleanup; an
uncertain submission is never retried automatically.

Missing permissions, unhealthy ADR projection, absent metadata, export/import
rejection, or unsupported PnP behavior remain **failures**, not skip-to-green
conditions. Forced process termination can bypass finalizers: use the printed
owned IDs for independent read-only verification and separately authorized cleanup.
