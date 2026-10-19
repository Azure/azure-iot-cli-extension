# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Conservative external-ICA preflight, not a certificate trust validator."""

import re
from datetime import datetime, timedelta, timezone

from azure.cli.core.azclierror import InvalidArgumentValueError
from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from knack.log import get_logger

logger = get_logger(__name__)
_CERTIFICATE = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL)


def _public_key_bytes(certificate):
    return certificate.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)


def _chain_order_errors(certificates):
    errors = []
    for child_index, child in certificates:
        if child.issuer == child.subject:
            try:
                child.verify_directly_issued_by(child)
            except (ValueError, InvalidSignature, UnsupportedAlgorithm):
                pass
            else:
                continue
        issuers = []
        for issuer_index, issuer in certificates:
            if child_index == issuer_index or child.issuer != issuer.subject:
                continue
            try:
                child.verify_directly_issued_by(issuer)
            except (ValueError, InvalidSignature, UnsupportedAlgorithm):
                continue
            issuers.append(issuer_index)
        if len(issuers) == 1 and issuers[0] < child_index:
            errors.append(
                f"Certificate {child_index} follows its verified issuer {issuers[0]}; "
                "order the chain from leaf to root."
            )
    return errors


def _csr_findings(leaf, csr_text, errors, warnings):
    if not isinstance(csr_text, str) or not csr_text.strip():
        warnings.append("The service CSR is unavailable; public-key match and requested extensions were not verified.")
        return
    try:
        csr = x509.load_pem_x509_csr(csr_text.encode("utf-8"))
        requested = csr.extensions
        csr_key = _public_key_bytes(csr)
    except (ValueError, UnsupportedAlgorithm, x509.DuplicateExtension):
        warnings.append("The service CSR could not be decoded; public-key match and requested extensions were not verified.")
        return
    try:
        leaf_key = _public_key_bytes(leaf)
    except ValueError:
        errors.append("The first certificate public key is malformed; obtain a valid signed certificate.")
    except UnsupportedAlgorithm:
        warnings.append("The first certificate public-key algorithm is unsupported locally; public-key match was not verified.")
    else:
        if leaf_key != csr_key:
            errors.append("The first certificate public key does not match the service CSR; sign the actual service CSR.")
    extensions = {extension.oid for extension in leaf.extensions}
    missing = [extension.oid.dotted_string for extension in requested if extension.oid not in extensions]
    if missing:
        warnings.append(
            "The signed ICA is missing requested CSR extensions: " + ", ".join(missing)
            + ". Re-sign with the requested extensions (OpenSSL -copy_extensions copy); do not edit a signed certificate."
        )


def validate_external_certificate_chain(chain, certificate_authority, *, now=None):
    """Reject proven defects, warn on uncertain policy, and never rewrite input."""
    now = now or datetime.now(timezone.utc)
    errors = []
    warnings = []
    blocks = _CERTIFICATE.findall(chain)
    if not blocks or _CERTIFICATE.sub("", chain).strip():
        errors.append("The certificate chain must contain only PEM CERTIFICATE blocks and whitespace.")
    certificates = []
    for index, block in enumerate(blocks, 1):
        try:
            certificate = x509.load_pem_x509_certificate(block.encode("utf-8"))
            # Extension decoding is lazy; malformed/duplicate extensions are also certificate defects.
            list(certificate.extensions)
        except (ValueError, UnsupportedAlgorithm, x509.DuplicateExtension):
            errors.append(f"Certificate {index} is malformed or uses an unsupported certificate encoding.")
            continue
        certificates.append((index, certificate))
        if certificate.not_valid_after_utc <= now:
            errors.append(f"Certificate {index} has expired; obtain a newly signed certificate.")
        elif certificate.not_valid_after_utc - now <= timedelta(days=365):
            warnings.append(
                f"Certificate {index} has no margin beyond 365 days remaining. A service rejection below "
                "365 days remaining has been observed; the exact service policy is unconfirmed. Allow operational margin."
            )
        if certificate.not_valid_before_utc > now:
            warnings.append(f"Certificate {index} is not yet valid; activation may be rejected by the service.")
    errors.extend(_chain_order_errors(certificates))
    if certificates and certificates[0][0] == 1:
        issuer = ((certificate_authority.get("properties") or {}).get("issuer") or {})
        _csr_findings(certificates[0][1], issuer.get("certificateSigningRequest"), errors, warnings)
    for warning in warnings:
        logger.warning(warning)
    if errors:
        raise InvalidArgumentValueError("Certificate chain preflight failed:\n" + "\n".join(errors))


def log_activation_error_hint(error):
    """Add context only to recognized service diagnostics, without replacing them."""
    text = str(error)
    if re.search(r"\bCertificateExpiringSoon\b", text):
        logger.warning(
            "The service rejected remaining certificate validity. Re-sign the service CSR with operational "
            "margin and an issuer valid for the ICA's lifetime; exactly 730 days is not required."
        )
    elif (
        "InvalidPropertyValue" in text
        and "properties.certificateProperties.extendedKeyUsage" in text
        and re.search(r"at least one|must not be empty|missing|required", text, re.IGNORECASE)
    ):
        logger.warning(
            "The service identified missing extended key usage. Re-sign the service CSR preserving requested "
            "extensions (OpenSSL -copy_extensions copy); clientAuth is not assumed to be the only accepted EKU."
        )
