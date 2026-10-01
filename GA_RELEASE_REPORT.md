# azure-iot 1.0.0 GA preparation report

Prepared 2026-10-01. This is an implementation and offline-qualification report,
not a deployment, live-qualification, merge, or release-publication announcement.

## Branch and command parity

- Branch: `work/ga-2026-11-01`, created in a separate worktree from
  `preview@d1a400204397eb29e196a9fedd14916764f6ab4e`.
- Handwritten implementation and test source:
  `release/1.0.0-preview@eb6db3fe0dc0ea618393b435b42410264918f9d9`.
- Review target: `Azure/azure-iot-cli-extension:preview`. The upstream base still
  matches the pinned commit; the fork's preview branch is 25 commits behind it.
- Exact command-name comparison: **506 source commands - 67 excluded ADR preview
  commands = 439 retained commands**. No unexpected additions or missing retained
  commands were found. The retained ADR surface contains 45 commands.
- Existing Hub jobs, DPS enrollment groups, and baseline `iot du` are retained.
  The original working checkout and its unrelated changes were not modified.

## Seven generated packages

| Area | Package below `azext_iot/sdk` | API | Pinned source |
| --- | --- | --- | --- |
| ADR/CMS control | `deviceregistry` | `2026-11-01` | Public specs `bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb`, including merged Azure/azure-rest-api-specs#45288 and later CMS corrections |
| Hub control | `iothub/mgmt` | `2026-11-01` | Azure/azure-rest-api-specs#46495, head `9addd631abe66abf232c1ca49062e3a98a42c67a` |
| DPS control | `dps/mgmt` | `2026-11-01` | Azure/azure-rest-api-specs#45368, head `5775cdfc9384920d706b75356e9b75b2199a1dcf` |
| DPS service data | `dps/service` | `2026-11-01` | Public specs `bb83f364d8d79a7c64cc5d6ed9677cbe27c8e1cb`, including merged Azure/azure-rest-api-specs#45041 |
| DPS device data | `dps/device` | `2026-11-01` | Same public snapshot |
| Hub service data | `iothub/service` | `2026-11-01-preview` | Azure-IoT-Hub-Main `77ed0fabb266a574f55051ac67ba3bcf7766b5e8`, `Service_2026-11-01-preview.json` |
| Hub device data | `iothub/device` | `2026-11-01-preview` | Same commit, `Device_2026-11-01-preview.json` |

Both control-plane PR heads were rechecked and remain unchanged and unmerged.
The private raw Hub Swagger inputs are not included in the change.

All **79 generated Python files** compile and match the qualified generated
output byte-for-byte. All seven packages are synchronous and modeless, with no
`aio` or serialized-model packages. Generated `types.py` files contain valid
`TypedDict`/`Literal` annotations and are retained. Empty model scaffolding was
verified to contain no model implementations before removal.

The private TypeSpec packages retain the emitter's `1.0.0b1` package-version
default; the two AutoRest packages use `1.0.0`. These internal SDK identifiers
are separate from the extension's **1.0.0** distribution and API-version pins.
The extension has `azext.isPreview: false` and the Production/Stable classifier.

## Generation recipe

Five targets used `client.tsp`, the source-pinned TypeSpec compiler `1.16.0`,
Node `24.14.1`, Python emitter `0.63.7`, and HTTP Python emitter `0.37.2`.
Azure core/ARM libraries were `0.72.1` and client-generator-core `0.72.2` for
ADR, Hub management, and DPS data; the DPS management source pins these Azure
libraries to `0.72.0`. Rest/versioning libraries were `0.86.0`.
No forced peer-dependency bypass or obsolete modeless-emitter patch was used.

Every TypeSpec invocation explicitly supplied:

```text
--emit @azure-tools/typespec-python
--option @azure-tools/typespec-python.models-mode=none
--option @azure-tools/typespec-python.no-async=true
--option @azure-tools/typespec-python.namespace=<target namespace>
--option @azure-tools/typespec-python.emitter-output-dir=<temporary output>
--option @azure-tools/typespec-python.api-version=2026-11-01
```

Hub data used AutoRest CLI `3.8.0`, core `3.10.8`, Python `6.32.3`, and
ModelerFour `4.27.2`, with:

```text
--python --azure-arm=false --models-mode=none --no-async=true
--add-credential=true
--credential-default-policy-type=AzureKeyCredentialPolicy
--credential-key-header-name=Authorization
--license-header=MICROSOFT_MIT_NO_VERSION --package-version=1.0.0
```

Compiler warnings concerned example-value mappings; no generation errors remain.
The repository skill now records the correct DPS source directory, permits
modeless `TypedDict` annotations, and requires checking generated dependency
floors against the extension manifest.

## Required differences from the preview release

1. **GA exclusions:** ADR groups/jobs/job runs, reports, registry-device
   auth/attribute/capability children, and ADR Software Updates commands and SDKs
   are excluded. Namespace `updating`/`observability` and DPS Software Updates
   actions are absent from the selected GA contracts.
2. **CMS policy arguments:** policy create/update reject tags; create also
   rejects location. Policy update uses `--validity-days`. Namespace update does
   not expose `--observability-enabled`, and general link wait has no SU selector.
   Tagless policy fixture cleanup verifies the policy ID and owned parent ICA
   rather than inventing unsupported tags.
3. **SDK integration:** DPS registration's generated keyword changed from
   `device_registration` to `body`; payload behavior is preserved. ARM defaults
   now use public Azure, while trusted explicit overrides remain available.
4. **Generated LRO defect:** some modeless callbacks reference an undefined
   `response`. The existing shared adapter was extended and wired into ADR
   callers without editing generated files. It repairs only that callback's
   unbound-name failure, preserves healthy callbacks and void DELETE results,
   and retains the original poller interface. Unrelated failures propagate.
   Direct consumers of these private SDK pollers must use the adapter where
   applicable until the generator defect is fixed.
5. **Retained behavior:** the source Hub adapter retains its 51-operation wire
   contract, payload/query/header handling, C2D rejection, and upload behavior.
   Subscription-scoped authentication, Hub PUT sanitization/ETags, RBAC preflight,
   DPS-first linking, bounded recovery, and registration ownership checks remain.
6. **Tests and packaging:** feature-only excluded tests were removed; generic
   recovery proofs formerly using SU were migrated to supported Hub/DPS cases.
   ADR mocks now reject operation groups absent from the real SDK. Runtime
   minimums match emitted requirements: `azure-core>=1.37.0`,
   `azure-mgmt-core>=1.6.0`, `isodate>=0.6.1`, and `typing-extensions>=4.6.0`.
   Source-branch macOS OpenSSL capability checks and interpreter-consistent ADO
   CLI installation were carried over for the retained unit tests.

The selected ADR/CMS and DPS registration surfaces and GA linked-Hub arguments
are marked stable. Existing unrelated preview features are not blanket-promoted,
and the intentional Hub data-plane preview API remains explicit.

## Offline validation

| Gate | Result |
| --- | --- |
| Full unit suite | **9,726 passed**, zero failures/errors/skips; 669 warnings, 796.74 seconds |
| Flake8 | Passed with repository configuration against `azext_iot/` |
| Pylint | Passed, **10.00/10** |
| Generated SDK checks | Seven packages, 79 Python files; compilation, imports, synchronous/modeless shape, and byte identity verified |
| Wheel and native CLI | `azure_iot-1.0.0-py3-none-any.whl` built and installed; ten help/absence checks passed |
| Installed dependencies | `pip check`: **No broken requirements found** |
| Git whitespace | `git diff --check` passed |

The last test-double signature adjustment was additionally checked with all 20
registry-scenario unit cases and Pylint. No production code changed after the
validated wheel was built.

The wheel used the repository's isolated build-system requirements. Its SDK
files match the source packages, excluded commands are not registered, and
extension metadata reports a stable 1.0.0 package.

```text
Wheel: azure_iot-1.0.0-py3-none-any.whl
SHA-256: 60a430006fca098a5c76ca9b3a1e715bcabb0deed1e7a830c54d622c630675ce
```

Validation used Linux/Python 3.10, published Azure CLI `2.90.0`, testsdk `0.3.0`,
and repository-pinned pytest `8.1.1`. Shared CLI dependency versions were kept
compatible: cryptography `47.0.0`, msal `1.36.0`, and azure-storage-blob
`12.29.0b1`. The pre-existing development environment used editable CLI packages
and a different pytest version, so it was not used for final qualification.

**Collection incident:** an initial collection attempt entered live fixture
constructor code and failed with CLI exit 3; no live integration scenario
completed. Setting `AZURE_TEST_RUN_LIVE=False` is not safe because that nonempty
string is truthy to testsdk. Subsequent runs unset it and use unit-only file
selection. An early collection guard and regression tests now prevent live
scenario construction in unit-only runs while preserving safe manifest
collection. All qualification results above are offline.

## Deferred release gates

- No live integration suite, release workflow, deployment, merge, or release
  publication was run. The selected GA APIs are not deployed, as specified by
  the user.
- Reconcile the two open control-plane spec PRs before final release.
- Run approved live cohorts only after deployment and admission/ownership checks,
  including the shared subscription's scheduled cleanup windows.
- Review and merge into `preview`, then separately synchronize to `dev` and
  requalify the final merged SHA and wheel. Local Linux results do not substitute
  for the configured cross-platform CI matrix or production qualification.
