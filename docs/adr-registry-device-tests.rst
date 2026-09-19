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
