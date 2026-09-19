Registry Device focused validation
==================================

All 17 preview Registry Device commands remain available. Validation combines
runtime unit coverage, native CLI parsing/current SDK wire contracts and one
registry-only live lifecycle. Positive issued-profile, key retrieval and
certificate revocation behavior is covered offline, **not live-tested**.

Live node and prerequisites
---------------------------

``azext_iot/tests/adr/test_adr_registry_device_int.py::TestADRRegistryDeviceLifecycle::test_registry_device_lifecycle``

Run this node through the existing ADR pytest/tox runner, retaining mandatory
preflight, serial execution, incremental results and failure classification.
It inherits ``ADRLiveScenarioTest`` and delegates through its command wrapper.
The outer budget is 2100 seconds, including cleanup; no opt-in or skip hides
missing permissions or backend failures.

The caller needs namespace, Registry Device and attribute CRUD permissions in
the configured ADR resource group. Use the existing ADR settings:

* ``azext_iot_adr_subscription``: the target subscription.
* ``azext_iot_adr_resource_group``: the existing test resource group.
* ``azext_iot_adr_location``: ``centraluseuap``.
* ``azext_iot_adr_arm_endpoint``: ``https://centraluseuap.management.azure.com``.
* ``azext_iot_adr_arm_resource``: ``https://management.azure.com``.
* ``azext_iot_adr_api_version``: ``2026-11-02-preview``.

Live execution requires ``AZURE_TEST_RUN_LIVE=True`` and a private authenticated
Azure configuration. Do not globally change AzureCloud or the user's default
subscription. The scenario explicitly appends its configured subscription to
every CLI command, including helper-generated cleanup. Its SDK ownership reads
use the same subscription. A subprocess preflight ``account set`` cannot
synchronize an already-created in-process CLI context.

Live scope and ownership
------------------------

The lifecycle creates only a fresh namespace, Registry Device and User attribute.
It confirms exact absence before claiming ownership and records cleanup before
each create attempt. It deletes only exact owned children, verifies SDK GET404
for completion, and retains parents when dependent cleanup fails or a foreign
child collides. ARM-ID comparisons are case-insensitive; application identifiers
remain case-sensitive. Lookup/authentication/transport errors do not establish
absence, including errors encountered while unwinding a primary failure.

The scenario covers device CRUD, external-ID resolution, update preservation,
waited and no-wait operations, attribute CRUD/readback, missing targets and client
validation. A custom Disabled-property wait is followed by a terminal
``--updated`` wait before the next mutation. Attribute LIST indexing may lag GET:
the exact created ID must appear within 120 seconds, observed every 5 seconds.
The readiness loop does not retry mutations or conceal read errors.

Bare Registry Devices need not have authentication profiles or capabilities.
The live scenario exercises their lists and missing-target show/key/revocation
behavior, plus an absent-profile wait. It does not fabricate read-only metadata,
invent schema values or claim positive issued-profile coverage.

No Hub, DPS, identity, role assignment, certificate authority, certificate policy,
enrollment or registration is provisioned by this scenario. There is no issuance
producer, receipt, replay-claim file or manual issuance opt-in. Existing unrelated
ADR integration scenarios and their fixture requirements are unchanged.

Offline contracts
-----------------

``test_adr_registry_device_unit.py`` and
``test_adr_registry_device_contract_unit.py`` retain all command/provider coverage,
including auth/capability reads and pagination, key secrecy, authentication-type
guards, key/revocation action bodies, SDK errors, no-wait and native poller
completion. Native CLI parser tests retain all 17 preview commands, aliases,
confirmation, help/table output, validation and exact SDK delegation.

``test_adr_registry_device_scenarios_unit.py`` covers the focused lifecycle's
subscription wrapper, ownership/quarantine, exact HTTP absence, update sequencing
and attribute-index lag. Shared cleanup classifier regressions remain in their
existing modules. Run offline commands with a fresh empty private
``AZURE_CONFIG_DIR`` set before Python starts and the existing pytest override
``-o env=azext_iot_testrg=testrg``.

Measure the complete restored runtime modules and added executable lines in
shared runtime files with branch coverage. Do not present that scoped percentage
as coverage of the entire repository or generated SDK.

Combined preview registration assertions
---------------------------------------

The combined Hub/DPS branch additionally exercises registry commands inside the
four existing default/deadline registration cases in
``azext_iot/tests/dps/device_registration/test_iot_device_registration_int.py``:
``test_register_without_csr_deadline_contract[default]``,
``test_register_without_csr_deadline_contract[deadline]``,
``test_register_and_issue_certificate_contract[default]`` and
``test_register_and_issue_certificate_contract[deadline]``.

All four reuse ``provisioned_csr_issuance`` and its same owned namespace, DPS, Hub,
authorities and policy. No second provisioning stack is introduced. Ordinary
symmetric enrollments send no namespace/CA/policy references; certificate
enrollments retain the complete reference tuple and strict echo validation.
Both registration paths discover their bootstrap credential internally, rather
than outputting it or placing it in CLI arguments. The former argv-based
wrong-key probe is not repeated here; existing DPS authentication tests remain.

Assertions resolve the actual Registry Device through the existing pre-submit
baseline and registration external ID, then check show by name/external ID,
list, auth list/show/wait and capability list/show. They correlate Hub
``adrDeviceProperties.uuid`` with the registry UUID, require the issued profile's
exact owned policy, and wait only on read-only metadata visibility. Each metadata
wait is bounded by 600 seconds, with 5-second observations and no error retry.
The existing 2700-second CSR case ceiling also bounds the normal variants.

The symmetric case calls ``auth show-keys`` with a native CLI query that returns
only the two key lengths. The certificate case submits exactly one confirmed,
waited ``auth revoke-certs`` action, then reads the same profile. No-wait/LRO
variants remain covered by the restored runtime's offline SDK contracts; a
profile existence wait is not misrepresented as revocation completion.

Existing ownership receipts pin identity without freezing a cleanup ETag before
intentional profile mutation. Cleanup resolves the current version afterwards.
An uncertain revocation leaves a pending action receipt and quarantines the
device and dependent parents; neither the scenario nor controller replays it.
Read/auth errors, ambiguous external IDs and changed identity still fail closed.

Use the existing DPS phase controller's ``--debug-phase regular`` and repeated
``--debug-node`` options with these exact repository-relative node IDs. Debug
results remain non-qualifying subsets; the full phase manifest is unchanged.
The legacy Azure DevOps DPS invocation is explicitly a partial regular subset,
not full qualification, and rejects controller settings. It excludes both
``test_register_without_csr_deadline_contract`` and
``test_register_and_issue_certificate_contract``: all four default/deadline cases
require the owned controller fixture. This leaves 31 of the 35 full regular
manifest cases eligible for that legacy selector; pre-existing manual cases
outside that manifest are not reclassified as full coverage. Full regular/debug
selection still includes these four cases. The full phase counts remain
35 regular, 29 service-SAS and 3 local-auth-toggle.

The caller still needs the existing owned fixture's management, linking and
data-plane permissions, plus role-assignment read/write/delete at its newly
owned namespace. As explicitly approved for these tests, the fixture applies
the workaround verified in work item 39640174, comment 55823874: Contributor
(``b24988ac-6180-42a0-ab88-20f7382dd24c``) for the namespace's **own**
system-assigned principal at **that namespace's exact resource scope**.
The principal comes from a fresh, ownership-checked ARM read after linking.
This is separate from the DPS principal's namespace grant; it is not a
resource-group/subscription grant, custom role, or production CLI auto-grant.
Contributor is proven but broader than the still-unconfirmed minimum
``Microsoft.DeviceRegistry/namespaces/registryDevices/write`` contract.

The exact assignment GUID is journaled before its single native create, then
its ID/principal/role/scope are verified through ARM. Existing authority/policy
setup consumes the propagation floor; only the remainder of at least 60 seconds
after verified grant visibility is waited before exposing the fixture.
Cleanup removes only that exact verified assignment after owned registry/CA
cleanup and before namespace deletion. Unresolved creates, conflicting bindings,
unresolved registration/profile actions or missing namespaces with uncompleted
role cleanup retain the namespace/target quarantine; accepted or uncertain
assignment deletes are never replayed. Visibility/reconciliation has a
300-second bound and exact deletion absence a 600-second bound, with no service
error retry. Service ``403000`` and other failures must still surface rather
than triggering broader grants or registration retries. Retain actual local
results separately; offline contracts do not establish successful live issuance.
