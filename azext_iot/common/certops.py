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
from typing import Dict
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from azext_iot.common.shared import SHAHashVersions


def create_self_signed_certificate(
    subject: str,
    valid_days: int,
    cert_output_dir: str,
    cert_only: bool = False,
    file_prefix: str = None,
    sha_version: int = SHAHashVersions.SHA1.value,
) -> Dict[str, str]:
    """
    Function used to create a basic self-signed certificate with no extensions.

    Args:
        subject (str): Certificate common name; host name or wildcard.
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.
        cert_putput_dir (str): string value of output directory.
        cert_only (bool): generate certificate only; no private key or thumbprint.
        file_prefix (str): Certificate file name if it needs to be different from the subject.
        sha_version (int): The SHA version to use for generating the thumbprint. For
            IoT Hub, SHA1 is currently used. For DPS, SHA256 has to be used.

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

    key_dump = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    cert_dump = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    hash = None
    if sha_version == SHAHashVersions.SHA1.value:
        hash = hashes.SHA1()
    elif sha_version == SHAHashVersions.SHA256.value:
        hash = hashes.SHA256()
    else:
        raise ValueError("Only SHA1 and SHA256 supported for now.")

    thumbprint = cert.fingerprint(hash).hex().upper()

    if cert_output_dir and exists(cert_output_dir):
        cert_file = (file_prefix or subject) + "-cert.pem"
        key_file = (file_prefix or subject) + "-key.pem"

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


def isBase64(content: str) -> bool:
    """
    Checks if certificant content should be valid base64 string without prefix and suffix

    Args:
        content (str): certificant content without prefix and suffix.

    Returns:
        isBase64 (bool): returns where the certificant content is valid base64 value.
    """
    try:
        sb_bytes = bytes(content, "ascii")
        base64.b64decode(sb_bytes)
    except Exception:
        return False
    return True


def getCertificateFormatValidation(certificate: str) -> str:
    """
    Checks if the certificate format is valid
    1. start with -----BEGIN CERTIFICATE----- (prefix)
    2. end with -----END CERTIFICATE----- (suffix)
    3. content should be valid base64 string without prefix and suffix

    Args:
        certificate (str): certificate string.

    Returns:
        validation string (str): returns validation string when content format is incorrect.
    """
    if (
        certificate.find("-----BEGIN CERTIFICATE-----") != -1
        and certificate.find("-----END CERTIFICATE-----") != -1
    ):
        certificate = certificate.replace("-----BEGIN CERTIFICATE-----", "")
        certificate = certificate.replace("-----END CERTIFICATE-----", "")
        if isBase64(certificate):
            return ""
        else:
            return "The certificate content is not a valid base64 string value"
    else:
        return "The certificate should start with '-----BEGIN CERTIFICATE-----' and end with '-----END CERTIFICATE-----'"


def open_certificate(certificate_path: str) -> str:
    """
    Opens certificate file (as read binary) from the file system and
    returns the value read.

    Args:
        certificate_path (str): the path the the certificate file.

    Returns:
        certificate (str): returns utf-8 encoded value from certificate file.
    """
    certificate = ""
    with open(certificate_path, "rb") as cert_file:
        certificate = cert_file.read()
        try:
            certificate = certificate.decode("utf-8")
        except UnicodeError:
            certificate = base64.b64encode(certificate).decode("utf-8")
        validationString = getCertificateFormatValidation(certificate)
        if validationString != "":
            raise ValueError(validationString)
    # Remove trailing white space from the certificate content
    return certificate.rstrip()
