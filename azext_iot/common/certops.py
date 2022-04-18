# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
certops: Functions for working with certificates.
"""

import datetime
from os.path import exists, join
import base64
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa


def create_self_signed_certificate(
    subject, valid_days, cert_output_dir, cert_only=False
):
    """
    Function used to create a self-signed certificate

    Args:
        subject (str): Certificate common name; host name or wildcard.
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.
        cert_putput_dir (str): string value of output directory.
        cert_only (bool): generate certificate only; no private key or thumbprint.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """
    # create a key pair
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # create a self-signed cert
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=valid_days)
        )
        .sign(key, hashes.SHA256())
    )

    cert_dump = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    key_dump = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint_bytes = cert.fingerprint(hashes.SHA1())
    thumbprint = "".join(f"{b:02X}" for b in thumbprint_bytes)

    if cert_output_dir and exists(cert_output_dir):
        cert_file = subject + "-cert.pem"
        key_file = subject + "-key.pem"

        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(cert_dump)

        if not cert_only:
            with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
                f.write(key_dump)

    result = {
        "certificate": cert_dump,
        "privateKey": key_dump,
        "thumbprint": thumbprint,
    }

    return result


def open_certificate(certificate_path):
    """
    Opens certificate file (as read binary) from the file system and
    retruns the value read.

    Args:
        certificate_path (str): the path the the certificate file.

    Returns:
        certificate (str): returns utf-8 encoded value from certificate file.
    """
    certificate = ""
    if certificate_path.endswith(".pem") or certificate_path.endswith(".cer"):
        with open(certificate_path, "rb") as cert_file:
            certificate = cert_file.read()
            try:
                certificate = certificate.decode("utf-8")
            except UnicodeError:
                certificate = base64.b64encode(certificate).decode("utf-8")
    return (
        certificate.rstrip()
    )  # Remove trailing white space from the certificate content
