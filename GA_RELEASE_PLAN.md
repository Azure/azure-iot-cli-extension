# GA SDK and command port plan

Research snapshot: 2026-09-30.

**Execution update:** implementation was subsequently authorized for extension
version **1.0.0** on `work/ga-2026-11-01`, in an isolated worktree based on the
pinned `preview` commit below. The original checkout remains untouched. Seven
SDK packages were generated independently and the supported preview-release
command/test port is implemented. Offline qualification passed: **9,726 unit tests**,
Flake8, Pylint, SDK checks, and the installed 1.0.0 wheel. See
[GA_RELEASE_REPORT.md](GA_RELEASE_REPORT.md) for provenance, compatibility
differences, validation evidence, and the initial collection incident.
**Do not run integration tests:** the selected GA APIs are not deployed;
live qualification, merging to `preview`/`dev`, and publication remain deferred.

The detailed checklists below retain the original release requirements. Current
execution status is:

| Steps | Status |
| --- | --- |
| 1-5: branch, scope, generation, replacement | Complete; seven generated packages verified |
| 6-7: supported command/test port | Complete; 439 retained commands, 67 preview-only commands excluded |
| 8: offline qualification | Complete; live and cross-platform release qualification remain deferred |
| 9: release metadata and documentation | Complete for unreleased 1.0.0 |
| 10: integration and publication | PR review, merge, later preview-to-dev synchronization, and release approval remain separate gates |

Live-service and publication steps below are future gates, not authorization to
run them during this implementation.

## 1. Confirmed scope

Create a new implementation branch from **`preview`**, not from
`release/1.0.0-preview`. Use `release/1.0.0-preview` as the source of the
applicable handwritten commands, providers, adapters, and tests. Generate the
target SDKs independently rather than copying its older generated packages.

The intended integration path is:

```text
preview -> new GA implementation branch -> reviewed integration into preview
        -> later, separately approved preview-to-dev synchronization -> GA release
```

### Included

| Area | Target API version | Command scope |
| --- | --- | --- |
| ADR / CMS control plane | `2026-11-01` | Namespace CRUD/migrate/wait, namespace identity, certificate authorities, certificate policies, registry-device CRUD/wait, Hub/DPS namespace links |
| IoT Hub control plane | `2026-11-01` | Applicable existing Hub management, identity, certificate, policy, routing, endpoint, and ADR-link behavior |
| DPS control plane | `2026-11-01` | Applicable existing DPS management, identity, certificate, policy, linked-Hub, and ADR-link behavior |
| DPS data plane | `2026-11-01` | Enrollment/enrollment-group operations, registration-state operations, device registration, certificate issuance, and operation-status recovery |
| IoT Hub data plane | `2026-11-01-preview` | Existing supported Hub device/service commands, including identities, twins, messaging, queries, configurations, jobs, and state workflows |

These are **five API areas but seven generated Python packages**: both DPS and
Hub data planes have separate service and device packages.

### Confirmed preview-only exclusions

These exclusions are supported by the specification contracts, not just a release
scope preference. A second check of the pinned specs confirmed that the following
operations are absent from the selected `2026-11-01` GA contracts and present in
the separate `2026-11-02-preview` contracts:

| Excluded family | Contract evidence |
| --- | --- |
| ADR groups, jobs, and job runs | `Groups`, `Jobs`, and `JobRuns` operation groups exist in ADR `2026-11-02-preview`, not ADR `2026-11-01`. |
| ADR reports | `Namespaces_GenerateReport` and `Namespaces_GetLatestReport` exist only in the compared ADR preview contract. |
| Registry-device child operations | `RegistryDeviceAuthenticationProfiles`, `RegistryDeviceAttributes`, and `RegistryDeviceCapabilities` exist only in the compared ADR preview contract. Parent `RegistryDevices` CRUD remains in GA. |
| ADR Software Updates links | The namespace `updating` property exists in the ADR preview schema, not the GA schema. GA retains `messaging` and `provisioning` for Hub/DPS links. |
| Namespace observability | The namespace `observability` property is absent from ADR `2026-11-01`; the preview-only update option is not exposed. |
| DPS Software Updates actions | `DeviceUpdate_ReportUpdateStatus`, `DeviceUpdate_RequestOnboardingUpdates`, and `DeviceUpdate_RequestSoftwareUpdates` exist in DPS device `2026-11-02-preview`, not `2026-11-01`. |
| Separate Software Updates control/data APIs | `deviceupdate/resource-manager/Microsoft.DeviceUpdate/DuDeviceRegistry` and `deviceupdate/data-plane/sudeviceregistry` are separate APIs outside the selected five areas. At the checked public snapshot, both have only `preview/2026-11-02-preview`, with no stable version directory. The source branch's two corresponding SDKs also use that preview version. |

Verification sources at public spec commit
`bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb`:
[ADR GA](https://github.com/Azure/azure-rest-api-specs/blob/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceregistry/resource-manager/Microsoft.DeviceRegistry/DeviceRegistry/stable/2026-11-01/deviceregistry.json),
[ADR preview](https://github.com/Azure/azure-rest-api-specs/blob/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceregistry/resource-manager/Microsoft.DeviceRegistry/DeviceRegistry/preview/2026-11-02-preview/deviceregistry.json),
[DPS device GA](https://github.com/Azure/azure-rest-api-specs/blob/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceprovisioningservices/data-plane/DeviceProvisioningServices/stable/2026-11-01/device.json),
[DPS device preview](https://github.com/Azure/azure-rest-api-specs/blob/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceprovisioningservices/data-plane/DeviceProvisioningServices/preview/2026-11-02-preview/device.json),
[Software Updates control](https://github.com/Azure/azure-rest-api-specs/tree/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceupdate/resource-manager/Microsoft.DeviceUpdate/DuDeviceRegistry),
[Software Updates data](https://github.com/Azure/azure-rest-api-specs/tree/bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb/specification/deviceupdate/data-plane/sudeviceregistry).

Do not port the following ADR preview families or their feature-specific help,
parameters, providers, fixtures, and tests:

- `iot adr ns group`.
- `iot adr ns job`, including `job run`.
- `iot adr ns report`.
- Registry-device child commands: `iot adr ns device auth`, `attribute`, and
  `capability`. Retain the parent `iot adr ns device` CRUD/wait surface.
- Software Updates: `iot adr ns su`, `iot adr ns link su`, and associated DPS
  software-update actions or preview-only payloads.
- The additional Software Updates packages
  `azext_iot/sdk/deviceupdate/duregistry` and
  `azext_iot/sdk/deviceupdate/duregistrydata`.

This exclusion does **not** remove existing IoT Hub jobs, DPS enrollment groups,
or the baseline `iot du` commands and their existing
`deviceupdate/controlplane` and `deviceupdate/dataplane` SDKs. Keep unrelated
baseline service features unchanged.

Likewise, excluding ADR child-resource commands does not remove similarly named
fields from other supported contracts: DPS GA enrollment capabilities still
include `iotEdge`. Make exclusions by service and operation, not by a broad
keyword search for "group", "job", "attribute", or "capability".

## 2. Verified sources and branch snapshots

### Extension branches

The local refs matched the upstream remote tips when checked:

| Role | Ref in `Azure/azure-iot-cli-extension` | Commit |
| --- | --- | --- |
| New-branch base | `preview` | `d1a400204397eb29e196a9fedd14916764f6ab4e` |
| Handwritten implementation/test source | `release/1.0.0-preview` | `eb6db3fe0dc0ea618393b435b42410264918f9d9` |
| Later GA integration destination | `dev` | `1456b28611725440f14bf4c252636d6e9f32cc1a` |

The source branch differs from `preview` in 550 files, including SDKs, excluded
preview features, and CI changes. Do not merge or copy that entire branch as a
shortcut. Re-resolve and record these refs before implementation; review any
new commits rather than silently changing this baseline.

### Specification provenance

| ID | Area | Verified source |
| --- | --- | --- |
| S1 | ADR / CMS | [Azure/azure-rest-api-specs#45288](https://github.com/Azure/azure-rest-api-specs/pull/45288), merged. Use public spec snapshot `bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb`, including later CMS corrections. |
| S2 | Hub control | [Azure/azure-rest-api-specs#46495](https://github.com/Azure/azure-rest-api-specs/pull/46495), open. Head repository `Azure/azure-rest-api-specs`, branch `davidemontanari/iothub-microsoft.devices-2026-11-01`, commit `9addd631abe66abf232c1ca49062e3a98a42c67a`. |
| S3 | DPS control | [Azure/azure-rest-api-specs#45368](https://github.com/Azure/azure-rest-api-specs/pull/45368), open. Head repository `Azure/azure-rest-api-specs`, branch `mollyiverson-microsoft-deviceprovisioningservices-Microsoft.Devices-2026-11-01`, commit `5775cdfc9384920d706b75356e9b75b2199a1dcf`. |
| S4 | DPS data | [Azure/azure-rest-api-specs#45041](https://github.com/Azure/azure-rest-api-specs/pull/45041), merged. Use public spec snapshot `bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb`. |
| S5 | Hub data | [Azure-IoT-Hub-Main Swagger directory](https://msazure.visualstudio.com/One/_git/Azure-IoT-Hub-Main?path=%2Fswagger%2F2026-11-01-preview), verified through authenticated Azure DevOps REST access at commit `77ed0fabb266a574f55051ac67ba3bcf7766b5e8`. |

S1 and S4 refer to a checked `main` snapshot, not to a moving `main` during
generation. For S2/S3, export the exact PR head, not the PR base branch.

Relevant Swagger files relative to the respective repository:

| Source | Files |
| --- | --- |
| S1 | `specification/deviceregistry/resource-manager/Microsoft.DeviceRegistry/DeviceRegistry/stable/2026-11-01/deviceregistry.json` |
| S2 | `specification/iothub/resource-manager/Microsoft.Devices/IoTHub/stable/2026-11-01/iothub.json` |
| S3 | `specification/deviceprovisioningservices/resource-manager/Microsoft.Devices/DeviceProvisioningServices/stable/2026-11-01/iotdps.json` |
| S4 | `specification/deviceprovisioningservices/data-plane/DeviceProvisioningServices/stable/2026-11-01/service.json` and `device.json` |
| S5 | `swagger/2026-11-01-preview/Service_2026-11-01-preview.json` and `Device_2026-11-01-preview.json` |

The S5 directory also contains files named for `2025-08-01-preview`; do not select
those just because they share the directory. Both selected 2026 files declare
Swagger 2.0 and `info.version: 2026-11-01-preview`.

The local spec checkouts are not authoritative for these snapshots:
`../azure-rest-api-specs` is on an older September 8 `main`, and
`../azure-rest-api-specs-pr` is on `release-adr-ignite`. Do not switch or modify
either source worktree.

## 3. Generation targets and existing guidance

Use [.github/skills/generate-typespec-sdk/SKILL.md](.github/skills/generate-typespec-sdk/SKILL.md)
and [.github/agents/azure-iot-cli-maintainer.agent.md](.github/agents/azure-iot-cli-maintainer.agent.md).
Keep generated replacements separate from handwritten compatibility changes.
Do not add a new generator helper to the repository.

### TypeSpec inputs

All five TypeSpec package builds below use **`client.tsp`**, not `main.tsp`.
The client entrypoints were checked remotely.

| Source | TypeSpec directory |
| --- | --- |
| S1 | `specification/deviceregistry/resource-manager/Microsoft.DeviceRegistry/DeviceRegistry` |
| S2 | `specification/iothub/resource-manager/Microsoft.Devices/IoTHub` |
| S3 | `specification/deviceprovisioningservices/resource-manager/Microsoft.Devices/DeviceProvisioningServices` |
| S4 service | `specification/deviceprovisioningservices/data-plane/DeviceProvisioningServices/service` |
| S4 device | `specification/deviceprovisioningservices/data-plane/DeviceProvisioningServices/device` |

**Guidance correction for this task:** the skill's DPS control-plane example
uses a `ProvisioningService` directory. The checked PR uses
`DeviceProvisioningServices`; use the actual source path above.

### Package destinations

The data-plane mappings below come from the source metadata and existing factory
imports; confirm them as generation inputs before executing the skill.

| Build | Python namespace | Expected exported client | Destination | Source branch API -> target |
| --- | --- | --- | --- | --- |
| ADR/CMS | `azext_iot.sdk.deviceregistry` | `DeviceRegistryMgmtClient` | `azext_iot/sdk/deviceregistry` | `2026-11-02-preview` -> `2026-11-01` |
| Hub control | `azext_iot.sdk.iothub.mgmt` | `IotHubClient` | `azext_iot/sdk/iothub/mgmt` | `2026-10-01-preview` -> `2026-11-01` |
| DPS control | `azext_iot.sdk.dps.mgmt` | `IotDpsClient` | `azext_iot/sdk/dps/mgmt` | `2026-06-01-preview` -> `2026-11-01` |
| DPS service | `azext_iot.sdk.dps.service` | `ProvisioningServiceClient` | `azext_iot/sdk/dps/service` | `2026-11-02-preview` -> `2026-11-01` |
| DPS device | `azext_iot.sdk.dps.device` | `ProvisioningDeviceClient` | `azext_iot/sdk/dps/device` | `2026-11-02-preview` -> `2026-11-01` |
| Hub service | `azext_iot.sdk.iothub.service` | `IotHubGatewayServiceAPIs` | `azext_iot/sdk/iothub/service` | `2026-11-01-preview` -> same version, pinned regeneration |
| Hub device | `azext_iot.sdk.iothub.device` | `IotHubGatewayDeviceAPIs` | `azext_iot/sdk/iothub/device` | `2026-11-01-preview` -> same version, pinned regeneration |

Hub data-plane inputs are **Swagger, not TypeSpec**. The loaded skill does not
provide a Swagger generation recipe. Preserve its source-protection,
temporary-output, compatibility-report, rollback, and validation rules, but
resolve and pin a compatible AutoRest CLI/core/Python-generator recipe before
generating these two packages. Do not feed JSON to the TypeSpec compiler or
invent a TypeSpec conversion as part of this port.

## 4. Findings that must shape implementation

| Finding | Required treatment |
| --- | --- |
| ADR GA includes namespace, certificate-authority/policy, and registry-device CRUD operations, but not the excluded child/group/job/report operations. Its namespace properties do not include `updating`. | Use a positive GA command/argument allowlist; do not copy all ADR command registrations, eager imports, or SU-link dispatch branches. |
| The checked ADR GA `CertificatePolicy` derives from `ProxyResource`. The source provider still writes `location` and `tags` and exposes tag updates. | Adapt policy create/update payloads, parameters, help, and tests together. Do not keep unsupported options that silently do nothing. |
| DPS GA retains `namespaceName`, `certificateAuthorityName`, and `certificatePolicyName` on enrollments. | Preserve certificate-reference enrollment flows and the associated CLI validation. |
| DPS GA device TypeSpec renames the registration body to `body` at `2026-11-01`; the source provider passes `device_registration=body`. | Compare actual generated signatures and adapt registration and polling call sites explicitly. A date-only SDK swap is insufficient. |
| DPS GA enrollment schemas do not contain `deviceTypeRefs`; the source artifact test asserts that this preview field is generated. | Replace preview-only field expectations with GA contract checks. Do not weaken supported enrollment, CSR, or registration tests. |
| Source factories pin Hub/DPS control APIs to older previews and route through an ARM endpoint helper that defaults to canary. | Update API selection and explicitly design/test production ARM routing. Regeneration alone does not change factories. |
| Hub data-plane source version already matches the requested target. | Regenerate from the checked source and compare wire behavior, rather than assuming matching version strings prove equivalent SDKs. |
| Shared registration fixtures call excluded ADR `auth` and `capability` commands. | Split GA registration/identity assertions from preview child-resource assertions; do not port those helpers unchanged. |
| Source command maps and shared parser fixtures eagerly enumerate excluded commands. | Update loaders, imports, help, params, parser tables, and collection dependencies together. Do not merely remove command map entries. |
| Extension GA intentionally retains a preview Hub data-plane API. | Document that distinction and obtain service-readiness confirmation; do not relabel the API as stable or blindly remove every command's preview annotation. |

Representative source files for these findings, at the pinned implementation
source commit:

- `azext_iot/_factory.py`, `azext_iot/constants.py`, `azext_iot/adr/endpoints.py`.
- `azext_iot/adr/command_map.py`, `azext_iot/adr/params.py`,
  `azext_iot/adr/providers/certificate_policy.py`.
- `azext_iot/dps/providers/device_registration.py`.
- `azext_iot/tests/test_hub_dps_sdk_artifacts_unit.py`,
  `azext_iot/tests/test_command_loader_unit.py`.
- `azext_iot/tests/adr/test_adr_surface_retirement_unit.py`,
  `azext_iot/tests/dps/_registry_assertions.py`.

## 5. Step-by-step execution plan

### Step 1 - Create an isolated branch from preview

- [ ] Recheck worktree status and upstream refs. Preserve the current unrelated
  work without stashing, resetting, or carrying it into the GA branch.
- [ ] Agree the implementation branch name; proposed name:
  `work/ga-2026-11-01`.
- [ ] Create a separate worktree and new branch from the approved `preview`
  commit. Example using this research snapshot, **not executed by this plan**:

  ```bash
  git worktree add -b work/ga-2026-11-01 \
    ../azure-iot-cli-extension-ga \
    d1a400204397eb29e196a9fedd14916764f6ab4e
  ```

- [ ] Record the base and source commits and copy this plan into that worktree.
  Do not base the new branch on the full preview-release implementation.

**Exit:** clean, isolated implementation worktree with an auditable preview
base; the original dirty checkout is untouched.

### Step 2 - Freeze the supported command/test manifest

- [ ] Inventory `preview` and the pinned `release/1.0.0-preview` command tables.
  Record command, arguments, handler, SDK operation, unit tests, and integration
  scenario for each in-scope change.
- [ ] Apply section 1's exclusions before selecting files or commits. Keep
  Hub jobs and DPS enrollment groups distinct from excluded ADR groups/jobs.
- [ ] Classify source changes as generated SDK, required handwritten
  implementation, required test infrastructure, excluded feature, or unrelated.
- [ ] Compare payload fields and operations against the pinned GA schemas.
  Resolve intentional behavior changes explicitly, especially CMS proxy-policy
  arguments; do not automatically revive retired ADR command spellings.
- [ ] Establish baseline command/help behavior and focused unit results in the
  isolated worktree before replacement.

**Exit:** a reviewed positive manifest for GA parity, plus explicit negative
checks for excluded command families.

### Step 3 - Export exact sources and resolve generation toolchains

- [ ] Revalidate PR head repositories/commits and the two merged-source snapshots.
  If a source changes, review its delta and update provenance first.
- [ ] Export each exact revision into temporary storage; never switch existing
  spec checkouts. Include required imported files and package/catalog/lock files.
- [ ] Export S5 through authenticated Azure DevOps access, pinned to the recorded
  commit. The existing CLI session can read it with `az rest` using resource
  `499b84ac-1321-427f-aa17-267ca6975798`. Do not print or persist tokens.
- [ ] Confirm all seven destinations are clean before generation.
- [ ] Resolve exact dependencies from root `package.json`,
  `pnpm-workspace.yaml`, and the lock file. Root dependencies use `catalog:`,
  so `package.json` alone is not a sufficient version manifest.
- [ ] Record the checked toolchain constraints:

  | Sources | Compiler / HTTP | Azure core / ARM | Client-generator-core |
  | --- | --- | --- | --- |
  | S1, S2, S4 | `1.16.0` | `0.72.1` | `0.72.2` |
  | S3 | `1.16.0` | `0.72.0` | `0.72.0` |

  The checked source roots require Node `>=24.14.1`; rest/versioning are
  `0.86.0`. Resolve all remaining imported libraries from the respective locks.
  Keep distinct toolchain hashes where versions differ.

- [ ] Select an exactly pinned, compatible `@azure-tools/typespec-python`.
  The checked root/catalog files do not supply its version. Reuse a workspace
  only if all relevant versions match; otherwise request an explicit emitter
  version before generation. Do not use `latest`, global TypeSpec, `npx`, an
  obsolete emitter patch, or forced peer-dependency bypasses.
- [ ] Pin and record the separate Hub AutoRest recipe, including generator
  versions and modeless/synchronous output options. This recipe is still an
  execution prerequisite, not a verified command in this plan.
- [ ] Follow the skill's approval rules if installing missing bootstrap tools
  such as nvm or uv is necessary.

**Exit:** reproducible source and toolchain manifests for all seven builds.

### Step 4 - Generate and qualify all seven packages outside the repository

- [ ] Compile the five TypeSpec targets from `client.tsp` using the workspace-local
  compiler. Mandatory emitter options are:

  ```text
  @azure-tools/typespec-python.models-mode=none
  @azure-tools/typespec-python.no-async=true
  @azure-tools/typespec-python.namespace=<declared namespace>
  @azure-tools/typespec-python.emitter-output-dir=<temporary output>
  @azure-tools/typespec-python.api-version=2026-11-01
  ```

- [ ] Explicitly select `2026-11-01` for each TypeSpec target even when the source
  has a newer preview. Do not merely override a runtime API-version string on a
  package generated from the wrong contract.
- [ ] Generate the Hub service/device packages from the selected S5 Swagger
  files with the separately verified AutoRest recipe.
- [ ] Stop on compilation or emitter errors. Confirm exported client names,
  synchronous methods, no `aio/` or `models/` package, valid Python, and no
  `Zone.Identifier` files. Do not delete substantive generated models to
  disguise an incompatible emitter.
- [ ] Compare each result with both the branch-base SDK and the implementation
  source SDK: files, constructors, operation groups/methods, parameter names,
  request fields, response types, pagination, LROs, endpoints, and API defaults.
- [ ] Record the generated package version separately from its service API
  version and from the extension release version.
- [ ] Run offline client/request probes against the exact generated code. Assert
  outgoing `api-version` values, not only `_config.api_version`.

**Exit:** seven qualified temporary packages and a compatibility report with
specific handwritten adaptation requirements.

### Step 5 - Replace SDK destinations as an isolated change

- [ ] Follow the skill's per-destination backup, staged replacement, and rollback
  procedure. Replace only the seven declared package directories.
- [ ] Do not bring in the two excluded Software Updates SDKs.
- [ ] Validate imports, Python compilation, modeless/synchronous shape, utility
  tests, and focused SDK contracts as required by the skill.
- [ ] If integrated validation fails, restore that destination exactly. Keep
  qualified temporary output/provenance for diagnosis; do not leave a failed
  replacement in place or silently waive a failed gate.
- [ ] Where existing call sites prevent a standalone replacement from passing,
  first prepare a separately reviewed compatibility change in the isolated
  worktree, then retry replacement and its validation.

**Exit:** generated-only changes with passing replacement gates and rollback
storage removed only after successful validation.

### Step 6 - Port shared integration and service code selectively

Use file/hunk selection against the pinned source. Whole-file copies are safe
only after checking for excluded imports and behavior.

| Work package | Primary surfaces to inspect/port |
| --- | --- |
| Root registration and shared glue | `azext_iot/__init__.py`, `commands.py`, `_params.py`, `_help.py`, `_validators.py`, `_factory.py`, `constants.py`, `common/arm.py`, `common/base_discovery.py`, necessary `common/embedded_cli.py` behavior |
| Hub/DPS control | `azext_iot/core/command_map.py`, `params.py`, `_params.py`, `_validators.py`, `custom.py`, `transforms.py`, `shared.py`; relevant `iothub/providers` and `dps/providers` |
| ADR/CMS | Namespace, CA, policy, registry-device parent CRUD, Hub/DPS link and wait command/provider code; `params.py`, `_help.py`, `common.py`, `topology.py`, `rbac.py`, `endpoints.py`, and required recovery helpers |
| DPS data | `azext_iot/operations/dps.py`, root enrollment params/help, `dps/commands_device_registration.py`, `dps/providers/device_registration.py`, `dps/services`, and discovery/authentication integration |
| Hub data | `azext_iot/operations/hub.py`, `iothub/_client.py`, `_payload.py`, `_authentication.py`, command/provider changes, and any required monitor integration |

- [ ] Wire the new constructors and operation signatures, using explicit keyword
  arguments and the declared generated client exports.
- [ ] Replace the older control-plane API pins in factories as well as generated
  code. Keep Hub data-plane selection at `2026-11-01-preview`; audit separately
  the meaning of `IOTHUB_PREVIEW_API_VERSION` and every consumer.
- [ ] Move production management defaults away from the preview canary endpoint
  to the approved public/cloud ARM endpoint. Keep canary an explicit test
  configuration if still needed; do not derive it from a resource's region or
  add silent API/endpoint fallbacks. Test any public-cloud-only limitation
  explicitly instead of claiming unverified sovereign-cloud support.
- [ ] Preserve subscription-scoped credentials, RBAC preflight before mutation,
  linking recovery, ETags, `--no-wait`, terminal failure handling, and command
  output contracts.
- [ ] Preserve shared Hub full-PUT sanitization through
  `IoTHubProvider._begin_hub_update`, `hub_description_for_write`, and
  `hub_etag_arguments`.
- [ ] Keep Hub compatibility behavior in the maintained adapter, not generated
  operations: query body wrapping, payload projection, raw responses/headers,
  C2D reject/receive semantics, Blob upload, and operation-specific retries.
- [ ] Preserve DPS SAS/Entra/X.509 authentication, discovered endpoints, bounded
  registration deadlines, accepted-operation recovery, and CSR behavior while
  adapting the generated GA request/poll signatures.
- [ ] Apply the CMS proxy-resource adjustment across command signatures,
  validation, payloads, help, and tests as one coherent change.
- [ ] Remove excluded preview references from selected files, including eager
  imports, dispatch tables, wait routing, RBAC/topology branches, and fixtures.
  Retain shared helpers only where required by included behavior.
- [ ] Preserve baseline features outside this port; do not copy unrelated CI,
  packaging, telemetry, or service changes merely because they are in the source
  branch.

**Exit:** all allowlisted commands load and execute against the target clients,
with no runtime dependency on excluded preview features.

### Step 7 - Port and adapt tests with the commands

- [ ] Update `test_command_loader_unit.py` parser maps and command-table
  expectations alongside service registration tests. Shared parsers index their
  enumerated commands, so stale excluded entries can break unrelated tests.
- [ ] Port/adapt `test_factory_unit.py`, `test_preview_sdk_compat_unit.py`, and
  `test_hub_dps_sdk_artifacts_unit.py`; add the ADR and both Hub data-plane
  packages to the target-version contract matrix as needed.
- [ ] Port the applicable control-plane handler/PUT/validator tests under
  `tests/core`, `tests/iothub/core`, and `tests/dps/core`.
- [ ] Port applicable ADR namespace, CA, policy, parent-device, link, RBAC,
  recovery, endpoint, SDK, and wait tests. Adapt mixed tests such as
  `test_adr_surface_retirement_unit.py` rather than copying excluded assertions.
- [ ] Preserve DPS enrollment and registration contract, authentication,
  certificate/CSR, timeout, and recovery coverage. Adapt
  `tests/dps/_registry_assertions.py` and dependent fixtures to use GA parent
  device/Hub identity evidence without excluded auth/capability commands.
- [ ] Preserve Hub adapter, wire, receive, payload, auth, state, and scenario
  tests. `tests/iothub/test_dataplane_wire_unit.py` currently covers all 51
  generated Hub operations; reconcile its operation inventory with the newly
  generated packages rather than testing only a few smoke calls.
- [ ] Add negative surface tests proving excluded ADR commands and help are
  absent, without excluding unrelated Hub jobs or DPS enrollment groups.
- [ ] Review test collection and fixtures before live execution: selecting an
  in-scope test must not import excluded SU/group/job/report modules.
- [ ] Port only the necessary shared integration runners/plugins/manifests and
  their dependencies. Rebuild expected GA cohort counts explicitly; do not
  treat preview-only missing tests as incidental skips.
- [ ] Preserve ADR integration scenario inheritance from `ADRLiveScenarioTest`
  and its logging wrapper.

**Exit:** offline collection succeeds and tests describe the selected GA
contract, including intentional omissions.

### Step 8 - Validate offline, then validate approved live cohorts

Run the smallest relevant checks after each work package. After integration,
use the existing development environment and repository tooling:

```bash
python -m pytest -q -k "_unit.py" \
  azext_iot/tests/core \
  azext_iot/tests/adr \
  azext_iot/tests/dps \
  azext_iot/tests/iothub \
  azext_iot/tests/utility \
  azext_iot/tests/test_factory_unit.py \
  azext_iot/tests/test_command_loader_unit.py \
  azext_iot/tests/test_preview_sdk_compat_unit.py \
  azext_iot/tests/test_hub_dps_sdk_artifacts_unit.py

git diff --check
python -m tox -e lint,python-azcur-unit
python -m build
```

These are future commands for the configured dev environment, not commands run
for this documentation task. The current shell has `python3`, not a bare
`python`; select/activate the intended environment before execution.

- [ ] Confirm all seven clients import and real request serialization uses the
  required versions, endpoints, body shapes, ETags, and polling behavior.
- [ ] Use transport-backed tests for CMS proxy-policy requests and DPS GA
  registration, not mocks that would accept obsolete keyword arguments.
- [ ] Run shared/root tests and the full unit suite after focused suites pass.
  Apply existing lint to handwritten code; generated SDK files are excluded by
  the repository's Flake8 configuration.
- [ ] Build/install the wheel into an isolated extension directory. Verify CLI
  help/command loading, dependencies, packaging contents, and supported Python
  versions through existing CI.
- [ ] Before any live run, confirm API deployment, subscription access, resource
  ownership, quotas, and absence of conflicting runs/cleanup. The ADO cleanup
  pipeline runs daily at 13:00 UTC and deletes nonexcluded resources in its
  target resource group; a GitHub-only admission check is insufficient.
- [ ] Run approved complete GA cohorts for Hub control, Hub data, DPS, and
  ADR/CMS using the existing service runners. Cover SAS and Entra paths, X.509
  registration, CMS issuance, Hub/DPS linking, and resource cleanup.
- [ ] Use public ARM and supported production regions for release qualification.
  Canary-only results are not evidence of production API availability.
- [ ] Reconcile GA cohort manifests and result evaluators before relying on
  their success. Focused/debug selections do not qualify a complete release.
- [ ] Preserve unaffected-service coverage required by the release workflow;
  changing shared factories/helpers can affect baseline consumers.

**Exit:** clean package/CLI validation and explicit pass/fail evidence for every
selected release cohort, with no unexplained skips or leaked resources.

### Step 9 - Prepare release metadata and documentation

- [x] Confirm the extension release version separately from API versions.
  The implementation uses `VERSION = "1.0.0"`, `azext.isPreview: false`, and a
  Production/Stable classifier. Private generated SDK package identifiers remain
  separate, as documented in the report.
- [ ] Update `constants.py`, `azext_metadata.json`, `setup.py`, `HISTORY.rst`,
  relevant README/install/help material, and release notes together.
- [ ] Review command-level preview flags individually against the agreed GA
  surface. Keep the intentional Hub data-plane preview API distinction clear.
- [ ] Document excluded ADR/SU preview features and the approved CMS argument
  changes. Do not advertise full `release/1.0.0-preview` feature parity.
- [ ] Review release CI and auth/branch wiring separately from the code port.
  Retain approval gates and required checks; do not trigger or bypass release
  workflows during implementation.

**Exit:** release metadata and documentation accurately describe the selected
surface and the mixed stable/preview API policy.

### Step 10 - Integrate and requalify before the later dev release

- [ ] Review generated SDK changes separately from shared glue, per-service
  ports, tests, and release metadata.
- [ ] Integrate the approved GA work into `preview` through the normal review
  process. Reconcile any preview changes that landed after the recorded base.
- [ ] Later, synchronize `preview` to `dev` in a separately reviewed change,
  checking for reintroduction of excluded commands, old SDKs, preview version
  pins, canary defaults, or prerelease packaging.
- [ ] Re-run the release gates on the actual final merged SHA and wheel; do not
  reuse results from a different branch tip.
- [ ] Publish only after explicit release approval and confirmed service
  deployment/readiness.

## 6. Remaining execution decisions and release gates

| Item | Status / required action |
| --- | --- |
| Excluded ADR/SU families | **Resolved:** exclude as specified in section 1. |
| Branch creation during this task | **Resolved:** authorized later and created as `work/ga-2026-11-01` in the isolated `azure-iot-cli-extension-ga` worktree. |
| Hub control version | **Resolved:** target stable `2026-11-01`; only `2026-10-01-preview`, not stable `2026-10-01`, was found in the October search. |
| Hub data-plane version/source | **Resolved:** `2026-11-01-preview`; both Swagger files and the pinned Azure DevOps commit were accessible and checked. |
| TypeSpec Python emitter | **Resolved:** Python emitter `0.63.7` and HTTP Python emitter `0.37.2`, with the source-pinned compiler/Azure libraries and Node `24.14.1`. |
| Hub Swagger generator recipe | **Resolved:** AutoRest CLI `3.8.0`, core `3.10.8`, Python `6.32.3`, ModelerFour `4.27.2`; synchronous/modeless clients with Authorization credentials. |
| Hub/DPS control PRs | Both are open at this snapshot. Generate from approved pinned heads; recheck final merged contracts and service deployment before publication. |
| CMS argument compatibility | **Resolved:** reject policy location/tags and namespace observability at the CLI surface; retain policy validity updates. Tagless policy fixtures verify their exact ID and owned parent CA. |
| Final GA version/date | **Version resolved:** `1.0.0`. Publication date and deployment remain unconfirmed; API labels do not prove rollout availability. |
| Production qualification | Require public-endpoint availability and approved live results, including the intentional preview Hub data-plane dependency. |

Completion means the seven target packages and the supported command/test
manifest agree, excluded families are absent from the GA port, baseline services
remain intact, and the final release artifact has been qualified on its actual
integration commit. None of those implementation steps is claimed complete by
this planning document.
