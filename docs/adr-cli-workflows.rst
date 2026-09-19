ADR link recovery and command compatibility
==========================================

Link DPS before adding a Hub. To retry a persisted Failed endpoint, use
``az iot adr ns link hub update``, ``link dps update`` or ``link su update``
with its existing endpoint name, namespace and resource group. Omit identity
options to reuse the saved identity and settings. Hub links may have no inbound
identity; DPS and Software Updates links still require one. Target, topology,
selected-identity and RBAC checks run again before mutation. A healthy endpoint
requires an explicit identity option.

Updates do not repoint endpoints or change Hub provisioning settings. Link
commands do not provide unlink operations or delete the linked resource.
If an endpoint name is occupied by another type, choose an unused name rather
than attempting an unavailable endpoint-delete command.

Use ``--system-assigned-mi`` (``--mi-sa``) or ``--user-assigned-mi``
(``--mi-ua``) for link inbound identity selection. The older
``--mi-system-assigned`` and ``--mi-user-assigned`` spellings remain deprecated
compatibility aliases. Composite link options use the ``--hub-`` or ``--dps-``
prefix. Its canonical labels are ``--hub-endpoint-name``/``--hen`` and
``--dps-endpoint-name``/``--den``; ``--hub-name``/``--hn`` and
``--dps-name``/``--dn`` still parse but now emit deprecation warnings.

Inspecting existing DPS Hubs
---------------------------

``az iot adr ns link dps show`` always distinguishes available DPS registration
data from unavailable enrichment. A successful DPS read returns
``brownfieldHubsAvailable: true`` and a ``brownfieldHubs`` list; ``[]`` means
the accessible DPS has no registered Hubs. Access, credential or service
failures return ``brownfieldHubsAvailable: false`` and ``brownfieldHubs: null``
with a warning, while preserving the namespace endpoint projection. Missing
target resources and unavailable cross-subscription access are not evidence
of an empty registration list. Invalid IDs and programming defects still fail.
Consumers that previously treated every empty list as authoritative must check
the availability field. Malformed successful DPS responses also fail rather than
being converted into an empty list.

Waiting and synchronous operations
----------------------------------

ADR ``wait`` commands count GET and predicate time against their monotonic
polling deadline and cap sleeps to the remaining budget. They do not start a
new GET at the deadline or accept success returned after it. A result received
exactly at the deadline can complete the wait. An in-flight request cannot be
interrupted by this polling deadline and remains subject to SDK transport
timeouts; the CLI can therefore return later than ``--timeout``.

Composite ``link add --no-wait`` still waits for DPS to reach Succeeded before
submitting the Hub stage. It skips only the final Hub wait; use ``link hub wait``
to observe that stage. A DPS failure prevents Hub submission, and partial
completion is not rolled back.

Group deletion is synchronous. Its compatibility ``--no-wait`` flag has no
effect and emits a warning; the command still waits for the delete response.
Software Update ``calculate-hash`` is a local command and needs no Azure call.

New IoT Hub defaults
--------------------

New Hubs default to S1, one unit, four device-to-cloud Event Hub partitions
and one day of event retention. Service-scoped local authentication is disabled
by default; use ``--auth-type login`` for service data-plane commands. Identity
assignment remains explicit.

These are new-resource defaults, not parser overrides for updates. Omitted
identity and local-auth settings retain their existing Hub upsert behavior;
omission must not be converted into an explicit false value or a new default.
DPS authentication defaults are unchanged.
