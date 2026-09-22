# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Correlated external-ICA activation evidence, never a revocation verifier."""

from time import monotonic, sleep

from azure.cli.core.azclierror import AzureResponseError
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from azext_iot.adr.providers.base import _retry_after_seconds


def _issuer(resource):
    if isinstance(resource, dict):
        properties = resource.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("issuer"), dict):
            return properties, properties["issuer"]
    raise AzureResponseError("Invalid CA activation resource shape; response suppressed.")


def has_pending_activation(resource):
    properties, issuer = _issuer(resource)
    return (
        properties.get("certificateAuthorityType") == "ICA"
        and issuer.get("issuerType") == "External" and issuer.get("status") == "PendingActivation"
    )


class ExternalActivationEvidence:
    """Bind PendingActivation -> Active to the resource and submitted leaf certificate.

    Thumbprints are hex certificate digests (SHA-1 or SHA-256), not arbitrary
    resource versions. Neither an ETag change nor provisioningState alone proves
    activation. Keep the certificate/CSR out of stored evidence and diagnostics.
    """

    def __init__(self, before, chain, *, resource_id):
        if not has_pending_activation(before):
            raise AzureResponseError("CA activation resource evidence requires a PendingActivation external ICA.")
        self.resource_id = resource_id
        properties, issuer = self._identity(before)
        self._uuid = properties.get("uuid")
        certificate = x509.load_pem_x509_certificate(chain.encode("utf-8"))
        self._thumbprints = {
            certificate.fingerprint(algorithm).hex() for algorithm in (hashes.SHA1(), hashes.SHA256())
        }
        if self._matches_thumbprint(issuer.get("thumbprint")):
            raise AzureResponseError(
                "CA activation baseline already contains the submitted certificate; completion is uncertain."
            )

    def _identity(self, resource):
        properties, issuer = _issuer(resource)
        resource_id = resource.get("id")
        if (
            not isinstance(resource_id, str) or resource_id.casefold() != self.resource_id.casefold()
            or properties.get("certificateAuthorityType") != "ICA" or issuer.get("issuerType") != "External"
        ):
            raise AzureResponseError("CA activation resource identity changed; response suppressed.")
        return properties, issuer

    def _matches_thumbprint(self, value):
        return isinstance(value, str) and value.replace(":", "").casefold() in self._thumbprints

    def completed(self, resource):
        properties, issuer = self._identity(resource)
        if self._uuid is not None and properties.get("uuid") != self._uuid:
            raise AzureResponseError("CA activation resource UUID changed; response suppressed.")
        if any(value in ("Failed", "Canceled") for value in (
            properties.get("provisioningState"), issuer.get("status"),
        )):
            raise AzureResponseError("CA activation resource reached Failed/Canceled; response suppressed.")
        return (
            properties.get("provisioningState") == "Succeeded" and issuer.get("status") == "Active"
            and self._matches_thumbprint(issuer.get("thumbprint"))
        )


def wait_for_activation(fetch, evidence, *, initial_response, timeout_sec=600, wait_sec=1,
                        clock=None, sleeper=None):
    """Return the proving GET unchanged. A late read must not report success.

    ``fetch`` receives the remaining budget for transport timeouts. Read errors,
    including *all* 403s, propagate: this path is selected before submission, not
    as a response to a permission error. No Location or async-status read occurs.
    """
    clock, sleeper = clock or monotonic, sleeper or sleep
    deadline = clock() + max(0, timeout_sec)

    def remaining():
        value = deadline - clock()
        if value <= 0:
            raise AzureResponseError("Timed out proving CA activation from the resource; completion is uncertain.")
        return value

    delay = _retry_after_seconds(initial_response, wait_sec)
    while True:
        sleeper(min(delay, remaining()))
        resource = fetch(remaining())
        remaining()
        if evidence.completed(resource):
            return resource
        delay = wait_sec
