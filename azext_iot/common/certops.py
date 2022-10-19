# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
certops: Functions for working with certificates.
"""

import datetime
from os.path import exists
import base64
from typing import List, Optional, TypedDict
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from azext_iot.common.fileops import write_content_to_file
from azext_iot.common.shared import SHAHashVersions
from azure.cli.core.azclierror import FileOperationError


class CertInfo(TypedDict):
    certificate: str
    privateKey: str
    thumbprint: str


def create_self_signed_certificate(
    subject: str,
    valid_days: int,
    cert_output_dir: str,
    cert_only: bool = False,
    file_prefix: str = None,
    sha_version: int = SHAHashVersions.SHA1.value,
) -> CertInfo:
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
        write_content_to_file(
            content=cert_dump,
            destination=cert_output_dir,
            file_name=cert_file,
            overwrite=True,
        )

        if not cert_only:
            write_content_to_file(
                content=key_dump,
                destination=cert_output_dir,
                file_name=key_file,
                overwrite=True,
            )

    result = CertInfo(
        certificate=cert_dump,
        privateKey=key_dump,
        thumbprint=thumbprint,
    )

    return result


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
    if certificate_path.endswith(".pem") or certificate_path.endswith(".cer"):
        with open(certificate_path, "rb") as cert_file:
            certificate = cert_file.read()
            try:
                certificate = certificate.decode("utf-8")
            except UnicodeError:
                certificate = base64.b64encode(certificate).decode("utf-8")
    else:
        raise ValueError("Certificate file type must be either '.pem' or '.cer'.")
    # Remove trailing white space from the certificate content
    return certificate.rstrip()


# TODO - Unit test, compare with test_utils::_generate_root_certificate
def create_edge_root_ca_certificate(
    subject: Optional[str] = "Azure_IoT_Config_Cli_Cert"
) -> CertInfo:
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )

    # v3_ca extensions
    subject_key_id = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    authority_key_id = x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
        subject_key_id
    )
    basic = x509.BasicConstraints(ca=True, path_length=None)
    key_usage = x509.KeyUsage(
        digital_signature=True,
        crl_sign=True,
        key_cert_sign=True,
        content_commitment=False,
        data_encipherment=False,
        decipher_only=False,
        encipher_only=False,
        key_agreement=False,
        key_encipherment=False,
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(subject_key_id, critical=False)
        .add_extension(authority_key_id, critical=False)
        .add_extension(basic, critical=True)
        .add_extension(key_usage, critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA256()).hex().upper()
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    return CertInfo(
        certificate=certificate,
        privateKey=private_key,
        thumbprint=thumbprint,
    )


# TODO - Unit test, compare with test_utils::_generate_device_certificate
def create_signed_device_cert(
    subject, ca_public, ca_private, cert_output_dir, cert_file
) -> CertInfo:

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ca_public_key = bytes(ca_public, "utf-8")
    ca_private_key = bytes(ca_private, "utf-8")
    ca_key = serialization.load_pem_private_key(ca_private_key, password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_public_key)

    # v3 certificate extensions
    subject_key_id = x509.SubjectKeyIdentifier.from_public_key(private_key.public_key())
    authority_key_id = x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
        subject_key_id,
    )
    basic_constraints = x509.BasicConstraints(ca=True, path_length=None)
    key_usage = x509.KeyUsage(
        digital_signature=True,
        crl_sign=True,
        key_cert_sign=True,
        content_commitment=False,
        data_encipherment=False,
        decipher_only=False,
        encipher_only=False,
        key_agreement=False,
        key_encipherment=False,
    )
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, subject),
                ]
            )
        )
        .sign(private_key, hashes.SHA256())
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(subject_key_id, False)
        .add_extension(authority_key_id, False)
        .add_extension(basic_constraints, True)
        .add_extension(key_usage, True)
        .sign(ca_key, hashes.SHA256())
    )
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA256()).hex().upper()
    privateKey = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    if cert_output_dir and exists(cert_output_dir):
        write_content_to_file(
            content=certificate,
            destination=cert_output_dir,
            file_name=f"{cert_file}.cert.pem",
        )
        write_content_to_file(
            content=privateKey,
            destination=cert_output_dir,
            file_name=f"{cert_file}.key.pem",
        )
    return CertInfo(
        certificate=certificate,
        thumbprint=thumbprint,
        privateKey=privateKey
    )


# TODO - Unit test
def load_ca_cert_info(cert_path: str, key_path: str) -> CertInfo:
    for path in [cert_path, key_path]:
        if not exists(path):
            raise FileOperationError(
                "Error loading certificates. " f"No file found at path '{path}'"
            )
    cert = open_certificate(cert_path)
    key = open_certificate(key_path)
    certificate = x509.load_pem_x509_certificate(cert)
    thumbprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
    return CertInfo(
        certificate=certificate.public_bytes(serialization.Encoding.PEM),
        thumbprint=thumbprint,
        privateKey=key,
    )


# TODO - Unit test
def make_cert_chain(
    certs: List[str],
    output_dir: Optional[str] = None,
    output_file: Optional[str] = "cert-chain.pem",
):
    cert_content = "".join(certs)
    if output_dir and exists(output_dir) and len(certs):
        write_content_to_file(
            content=cert_content,
            destination=output_dir,
            file_name=output_file,
            overwrite=True,
        )
    return cert_content
