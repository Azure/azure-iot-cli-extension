# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
certops: Functions for working with certificates.
"""

import datetime
from os import makedirs
from os.path import exists, join
import base64
from pathlib import PurePath
from typing import List, Optional, TypedDict, Union
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
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

        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(cert_dump)

        if not cert_only:
            with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
                f.write(key_dump)

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


def create_edge_root_ca_certificate(cert_output_dir: str, cert_name: str) -> CertInfo:
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Azure_IoT_Config_Cli_Cert"),
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
        content_commitment=None,
        data_encipherment=None,
        decipher_only=None,
        encipher_only=None,
        key_agreement=None,
        key_encipherment=None)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(key.public_key())
        .add_extension(subject_key_id, False)
        .add_extension(authority_key_id, False)
        .add_extension(basic, True)
        .add_extension(key_usage, True)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA256()).hex().upper()
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    if cert_output_dir and exists(cert_output_dir):
        cert_file = cert_name + ".cert.pem"
        key_file = cert_name + ".key.pem"
        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(certificate)

        with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
            f.write(private_key)

    return CertInfo(
        certificate=certificate,
        privateKey=private_key,
        thumbprint=thumbprint,
    )


def create_signed_device_cert(device_id, ca_public, ca_private, cert_output_dir) -> CertInfo:
    ca_public_key = bytes(ca_public, "utf-8")
    ca_private_key =  serialization.load_pem_private_key(bytes(ca_private, "utf-8"), None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, f"{device_id}.deviceca"),
        ]
    )
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject_name)
        .sign(key, hashes.SHA256())
    )
    ca = x509.load_pem_x509_certificate(ca_public_key)

    cert = x509.CertificateBuilder().subject_name(
        csr.subject
    ).issuer_name(
        ca.subject
    ).public_key(
        csr.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).sign(ca_private_key, hashes.SHA256())
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA256()).hex().upper()
    privateKey = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    if cert_output_dir and exists(cert_output_dir):
        cert_file = device_id + ".cert.pem"
        key_file = device_id + ".key.pem"
        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(certificate)

        with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
            f.write(privateKey)
    return CertInfo(
        certificate=certificate,
        thumbprint=thumbprint,
        privateKey=privateKey
    )


def load_ca_cert_info(cert_path: str, key_path: str) -> CertInfo:
    for path in [cert_path, key_path]:
        if not exists(path):
            raise FileOperationError(
                "Error loading certificates. "
                f"No file found at path '{path}'"
            )
    certificate = x509.load_pem_x509_certificate(cert_path)
    thumbprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
    privateKey = x509.load_pem_x509_certificate(key_path)
    return CertInfo(
        certificate=certificate.public_bytes(serialization.Encoding.PEM),
        thumbprint=thumbprint,
        privateKey=privateKey
    )


def make_cert_chain(certs: List[str], output_dir: Optional[str]=None, output_file: Optional[str]="cert-chain.pem"):
    if output_dir and exists(output_dir) and len(certs):
        with open(join(output_dir, output_file), "wt", encoding="utf-8") as f:
            for cert in certs:
                f.write(cert)
    return "\n".join(certs)


def write_content_to_file(content: Union[str, bytes], destination: str, file_name: str, overwrite: Optional[bool]=False):
    dest_path = PurePath(destination)
    file_path = dest_path.joinpath(file_name)
    
    if exists(file_path) and not overwrite:
        raise FileOperationError(f"File already exists at path: {file_path}")
    if overwrite:
        makedirs(destination, exist_ok=True)
    with open(file_path, "wt" if isinstance(content, str) else "wb", encoding="utf-8") as f:
        f.write(content)
