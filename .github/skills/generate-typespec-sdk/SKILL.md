---
name: generate-typespec-sdk
description: Generate and safely replace a modeless synchronous Azure IoT Python SDK from a local or GitHub TypeSpec source.
---

# Generate a TypeSpec SDK

Use this workflow for control-plane or data-plane SDKs under `azext_iot/sdk`, including IoT Hub, DPS, Digital Twins,
Device Update, Device Registry, and future services.

The workflow is instruction-driven. Do not add a generator helper to the repository.

## Required inputs

Collect these values before generation:

- service and plane;
- source as one of:
  - local Git repository plus explicit branch, tag, or commit;
  - GitHub repository plus explicit branch, tag, or commit;
  - GitHub pull request URL;
- TypeSpec source directory;
- compile entrypoint, normally `client.tsp`;
- Python namespace;
- expected generated client class;
- destination directory under `azext_iot/sdk`;
- existing TypeSpec workspace path, if available;
- explicit `@azure-tools/typespec-python` version only when neither the spec nor a compatible workspace supplies it.

Normalize `\\wsl.localhost\Ubuntu\...` paths to Linux paths.

Known control-plane mappings:

| Service | Source directory | Entrypoint | Namespace | Client | Destination |
| --- | --- | --- | --- | --- | --- |
| IoT Hub | `specification/iothub/resource-manager/Microsoft.Devices/IoTHub` | `client.tsp` | `azext_iot.sdk.iothub.mgmt` | `IotHubClient` | `azext_iot/sdk/iothub/mgmt` |
| DPS | `specification/deviceprovisioningservices/resource-manager/Microsoft.Devices/ProvisioningService` | `client.tsp` | `azext_iot.sdk.dps.mgmt` | `IotDpsClient` | `azext_iot/sdk/dps/mgmt` |

Do not guess data-plane mappings. Ask for explicit source directory, entrypoint, namespace, client, and destination.

## 1. Protect the extension repository

1. Confirm the current Git repository is `azure-iot-cli-extension`.
2. Resolve the destination and ensure it is inside `azext_iot/sdk`.
3. Inspect Git status for the destination.
4. Refuse to proceed if tracked or untracked changes already exist inside the destination.
5. Do not modify factories, providers, commands, tests, other SDKs, or packaging as part of generation.

## 2. Resolve the exact source

Never switch or modify an existing source worktree.

For a local Git repository:

1. Confirm the explicit ref resolves.
2. Record the resolved commit.
3. Export that commit into temporary storage with `git archive`.

For a GitHub repository/ref:

1. Resolve the ref to a commit.
2. Use a temporary shallow, blob-filtered, sparse checkout containing the TypeSpec directory and root package files.

For a GitHub pull request:

1. Run `gh auth status` and confirm the authenticated account can access the source repository. Private repositories,
   including `azure-rest-api-specs-pr`, require prior authentication.
2. Parse the owner, repository, and pull-request number from the URL, then use the REST API to resolve the head
   repository, head ref, and exact head commit:

   ```shell
   gh api repos/<owner>/<repo>/pulls/<number> \
     --jq '{repository: .head.repo.full_name, ref: .head.ref, commit: .head.sha}'
   ```

3. Clone/export that exact commit into temporary storage. Do not rely on the PR base branch.

Verify the TypeSpec directory and entrypoint exist in the exported source. Prefer `client.tsp`, because it commonly
contains client naming and operation overrides. If only `main.tsp` is selected while `client.tsp` exists, stop and ask
for confirmation.

## 3. Resolve or create the toolchain workspace

The selected spec revision is authoritative for TypeSpec compiler and Azure library versions.

1. Read exact versions from its root `package.json` and lock file when available.
2. Required packages normally include:
   - `@typespec/compiler`;
   - `@typespec/http`;
   - `@typespec/rest`;
   - `@typespec/versioning`;
   - `@typespec/openapi`;
   - `@azure-tools/typespec-azure-core`;
   - `@azure-tools/typespec-azure-resource-manager` for ARM specs;
   - `@azure-tools/typespec-azure-rulesets`;
   - `@azure-tools/typespec-python`;
   - any additional packages imported by the selected spec.
3. If the spec does not pin `@azure-tools/typespec-python`, reuse the exact version from a compatible supplied
   workspace. If none exists, ask for an explicit emitter version; never choose `latest`.

### Reuse a workspace

An existing workspace is compatible only when:

- its installed compiler and imported TypeSpec package versions exactly match the selected spec revision;
- it has the required Python emitter version;
- `node_modules` is complete;
- `uv` is available;
- its Node version satisfies the selected compiler's `engines.node` requirement. TypeSpec compiler 1.12.0 and later
  requires Node 22 or newer.

If a workspace has `.nvmrc`, load `nvm` and run `nvm use`. Never trust the caller's active Node version.

### Create a workspace

If no compatible workspace exists, create:

```text
~/.cache/azure-iot-cli/typespec-sdk/<toolchain-hash>
```

The hash must be derived from the exact package names and versions.

Bootstrap it as follows. Installing either tool changes the user's machine and requires explicit approval:

1. If `nvm` is missing, stop and ask for approval before installing it. Use an official installer URL pinned to an
   explicit `nvm-sh/nvm` release tag, record the version, and never fetch a moving `install.sh`.
2. Inspect the selected compiler's `engines.node` requirement, install/use a satisfying Node version, and write
   `.nvmrc`. TypeSpec compiler 1.12.0 and later requires Node 22 or newer.
3. If `uv` is missing, stop and ask for approval before installing it. Use Astral's official installer pinned to an
   explicit `uv` release version and record the version.
4. Create a minimal private `package.json` containing exact package versions.
5. Run:

   ```shell
   npm install --registry=https://registry.npmjs.org/
   ```

6. Verify the local compiler and emitter versions.

Do not use global TypeSpec packages. Do not use `npx`. Do not run or recreate the obsolete modeless emitter patch.

## 4. Generate in temporary storage

Copy the exported TypeSpec directory into temporary working storage if needed so generation cannot modify the source.
Set `$HOME/.local/bin` on `PATH` for `uv`.

Run the workspace-local compiler:

```shell
node <workspace>/node_modules/@typespec/compiler/cmd/tsp.js compile <source>/<entrypoint> \
  --emit @azure-tools/typespec-python \
  --option "@azure-tools/typespec-python.models-mode=none" \
  --option "@azure-tools/typespec-python.no-async=true" \
  --option "@azure-tools/typespec-python.namespace=<namespace>" \
  --option "@azure-tools/typespec-python.emitter-output-dir=<temp-output>"
```

Use emitter options from the selected spec's `tspconfig.yaml` when they are required for correctness, but the four
options above are mandatory and take precedence for extension integration.

Warnings may be reported, but any compiler or emitter error stops the workflow.

## 5. Verify generated output

Before touching the extension repository, assert:

- the expected namespace directory exists;
- the expected client class is exported by the package;
- no `models/` directory exists;
- no `aio/` directory exists;
- operation methods use synchronous definitions;
- generated Python files compile;
- no `Zone.Identifier` files remain;
- no output was written outside temporary storage.

Record:

- source repository, ref/PR, and exact commit;
- TypeSpec directory and entrypoint;
- Node, compiler, emitter, and imported library versions;
- namespace, client class, destination, and generated SDK version.

## 6. Compare and report compatibility

Compare the generated directory with the existing destination before replacement. Report:

- files added, removed, and changed;
- client and configuration constructor parameter changes;
- operation groups added or removed;
- operation method additions, removals, and signature changes;
- default API-version and endpoint/base-URL changes;
- generated package version changes;
- imports and extension call sites that may become incompatible.

Pay particular attention to:

- expected client-class renames caused by compiling `main.tsp` instead of `client.tsp`;
- `endpoint` versus `base_url`;
- required constructor parameters;
- renamed operation groups or methods;
- changes between pageable and non-pageable operations.

This report does not block replacement when generation checks pass, but compatibility warnings must be prominent.
Do not edit call sites automatically.

## 7. Replace automatically with rollback

After all generation checks pass:

1. Copy the current destination to temporary rollback storage.
2. Stage the generated namespace directory beside the destination.
3. Remove any `Zone.Identifier` files from the staged copy.
4. Replace only the declared destination.
5. If replacement or any validation step fails, restore the original destination exactly.
6. Remove temporary source, output, and staging storage when no longer needed, but retain rollback storage until all
   integrated validation in section 8 succeeds.

Do not modify another SDK directory.

## 8. Validate the integrated SDK

1. Compile every generated Python file.
2. Import the expected client from the destination namespace.
3. Reconfirm modeless and synchronous output.
4. Run:

   ```shell
   python -m pytest -q azext_iot/tests/utility/test_iot_utility_unit.py
   git diff --check
   ```

5. Run focused service unit tests when they are discoverable and do not require live Azure resources.
6. Show the final diff summary, toolchain/source provenance, API comparison, and compatibility warnings.
7. After every validation step succeeds, remove rollback storage. If any validation step fails, restore the original
   destination exactly before removing temporary storage and report the failure.

Generated SDK files are excluded by the repository's Flake8 configuration. Run existing lint only for non-generated
files if they were explicitly changed in a separate compatibility task.

Never commit, push, publish, switch the extension branch, or trigger a workflow.

## IoT Hub PR example

```text
Generate the IoT Hub control-plane SDK from:
https://github.com/Azure/azure-rest-api-specs-pr/pull/28915

TypeSpec directory:
specification/iothub/resource-manager/Microsoft.Devices/IoTHub

Entrypoint: client.tsp
Workspace: <path-to-typespec-workspace>
Namespace: azext_iot.sdk.iothub.mgmt
Client: IotHubClient
Destination: azext_iot/sdk/iothub/mgmt
```
