# ADR certificate action completion

External ICA activation has a resource-based completion path. When the
pre-submission GET reports an external ICA as `PendingActivation`, the CLI submits once
without SDK background status polling. A waited command then GETs that exact
resource until it reports all of:

* The same resource identity (and UUID, when present in the baseline).
* `issuer.status == Active`.
* A certificate thumbprint matching the submitted leaf certificate (hex SHA-1
  or SHA-256, case-insensitive, with optional colon separators).
* `provisioningState == Succeeded`.

The proving GET is returned unchanged, preserving the waited CA output contract.
`--no-wait` still returns submission only, with no post-submission GET. The CA
integration tests independently reconcile the same resource evidence before
reporting success or allowing cleanup, including for `--no-wait`.

This is selected **before** submitting, not after an authorization error. If a
PendingActivation baseline is unavailable, the CLI explicitly reports that the existing
action-status polling contract is required. It never switches completion paths
in response to a 403. All resource read errors propagate; stale/unrelated Active
certificates, identity changes, failures, and deadlines cannot prove success.

The local live ADR run on 2026-09-22 returned `issuer.status = PendingActivation`
with `provisioningState = Succeeded` before activation. The generated SDK types
issuer status as a string, not an enum. `Pending` was an incorrect client/fixture
assumption, not the observed service value; it is not accepted as an alias.
`PendingActivation` only selects the read-based completion path. It is never
itself completion evidence; the matching-certificate `Active` proof above is
still required.

## Revocation remains blocked without operation-status access

The checked-in Device Registry API (`2026-11-02-preview`) declares:

* External CA issuers: CSR, status and thumbprint.
* Microsoft CA issuers: issuing CA resource ID, but no certificate fingerprint,
  rotation generation, or correlated operation-completion marker.
* CA-signed authentication profiles: certificate policy resource ID.
  `revokeCertificates` invalidates outstanding certificates through the PKI
  revocation list **and preserves the authentication profile**.

These contracts are in `CertificateAuthoritiesOperations.get` and
`RegistryDeviceAuthenticationProfilesOperations.get/begin_revoke_certificates`
in `azext_iot/sdk/deviceregistry/operations/_operations.py`.

Neither a successful resource GET, provisioningState, timestamps nor an ETag
change proves Microsoft CA rotation or device certificate revocation. The
current DPS CSR scenario establishes registration and certificate issuance, not
a documented fresh-connection authentication probe proving that an old
certificate is rejected while a newly issued certificate works.

Consequently Microsoft CA revocation and DPS `auth revoke-certs` still require
authoritative LRO completion. A denied
`Microsoft.DeviceRegistry/locations/asyncOperationStatuses/read` remains a
failure, not success or a skip. Uncertain actions retain the existing cleanup
quarantine, ownership receipts and dedicated targets. No test selection or
revocation assertion has been removed. A resource-only revocation alternative
requires an additional documented service marker or a supported, correlated
fresh-connection behavioral proof; resource mutation alone is insufficient.
