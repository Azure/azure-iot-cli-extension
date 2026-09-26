# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError, ServiceResponseError

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from azext_iot.common.certops import make_cert_chain

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def is_expected_policy_rejection(error):
    """Require positive policy evidence; contradictory HTTP/auth evidence wins."""
    seen, texts, statuses, codes = set(), [], [], []
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ClientAuthenticationError, ServiceRequestError, ServiceResponseError)):
            return False
        for status in (getattr(current, "status_code", None),
                       getattr(getattr(current, "response", None), "status_code", None)):
            if status is not None and status not in (200, 201, 202, 400, 409):
                return False
            if status is not None:
                statuses.append(status)
        text = str(current)
        for detail in (current, getattr(current, "error", None)):
            code = detail.get("code") if isinstance(detail, dict) else getattr(detail, "code", None)
            if isinstance(code, str):
                codes.append(code.casefold())
                text += " " + code
        texts.append(text)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    text = " ".join(texts)
    if re.search(
        r"\b(?:401|403|408|429|5\d\d)\b|Unauthorized|Forbidden|Authentication|Authorization|"
        r"InvalidAuthenticationToken|ExpiredAuthenticationToken|RequestTimeout|TooManyRequests|"
        r"InternalServerError|BadGateway|ServiceUnavailable|GatewayTimeout|"
        r"ServiceRequestError|ServiceResponseError|ConnectionError|ConnectionReset|NameResolution|"
        r"InvalidSubscription|SubscriptionNotFound|TenantNotFound|AccessDenied|InvalidToken|"
        r"not authorized|timed out",
        text, re.IGNORECASE,
    ):
        return False
    if any(code not in ("policyrejected", "certificatepolicylimitexceeded") for code in codes):
        return False
    if re.search(r"\bPolicyRejected\b|\bCertificatePolicyLimitExceeded\b", text, re.IGNORECASE):
        return True
    return (
        not any(status in (400, 409) for status in statuses)
        and "provisioningState='Failed'" in text
        and "did not include a detailed error" in text
        and ("resource-status response" in text or "initial operation response" in text)
        and "Check Azure Activity Log for this resource around the operation time" in text
    )


def certificate_fixture(*, remaining=timedelta(days=730), starts=timedelta(days=-1),
                        mismatch=False, copy_extensions=True, extra_eku=False, csr_text=None, now=NOW):
    root_key = ec.generate_private_key(ec.SECP384R1())
    ica_key = ec.generate_private_key(ec.SECP384R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable ADR root")])
    ica_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Service ICA")])
    root = (
        x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
        .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=10)).not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=2), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(root_key, hashes.SHA384())
    )
    csr = (
        x509.CertificateSigningRequestBuilder().subject_name(ica_name)
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ica_key, hashes.SHA384())
    )
    if csr_text:
        csr = x509.load_pem_x509_csr(csr_text.encode("utf-8"))
    leaf = (
        x509.CertificateBuilder().subject_name(csr.subject).issuer_name(root.subject)
        .public_key(root_key.public_key() if mismatch else csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + starts).not_valid_after(now + remaining)
    )
    if copy_extensions:
        for extension in csr.extensions:
            value = extension.value
            if extra_eku and extension.oid == x509.ExtensionOID.EXTENDED_KEY_USAGE:
                value = x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH])
            leaf = leaf.add_extension(value, extension.critical)
    leaf = leaf.sign(root_key, hashes.SHA384())
    root_pem = root.public_bytes(serialization.Encoding.PEM).decode()
    leaf_pem = leaf.public_bytes(serialization.Encoding.PEM).decode()
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    return {
        "chain": make_cert_chain([leaf_pem, root_pem]), "root": root_pem, "leaf": leaf_pem,
        "resource": {"properties": {
            "certificateAuthorityType": "ICA",
            "issuer": {"issuerType": "External", "certificateSigningRequest": csr_pem},
        }},
    }


def negative_certificate_chains(resource, *, now=NOW):
    csr_text = resource["properties"]["issuer"]["certificateSigningRequest"]
    valid = certificate_fixture(csr_text=csr_text, now=now)
    expired = certificate_fixture(csr_text=csr_text, remaining=timedelta(seconds=-1), now=now)
    wrong = certificate_fixture(csr_text=csr_text, mismatch=True, now=now)
    multiple = certificate_fixture(csr_text=csr_text, mismatch=True, remaining=timedelta(seconds=-1), now=now)
    return [
        ("malformed", "-----BEGIN CERTIFICATE-----\nbroken\n-----END CERTIFICATE-----", ("malformed",)),
        ("expired", expired["chain"], ("expired",)),
        ("wrong-key", wrong["chain"], ("does not match",)),
        ("root-first", valid["root"] + valid["leaf"], ("verified issuer", "does not match")),
        ("multiple", multiple["chain"], ("expired", "does not match")),
    ]
