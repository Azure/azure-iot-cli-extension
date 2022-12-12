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
from typing import Dict, List, Optional
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from azext_iot.common.fileops import write_content_to_file
from azext_iot.common.shared import SHAHashVersions
from azure.cli.core.azclierror import FileOperationError


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

    result = {
        "certificate": cert_dump,
        "privateKey": key_dump,
        "thumbprint": thumbprint,
    }

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


def create_v3_self_signed_root_certificate(
    subject: str = "Azure_IoT_CLI_Extension_Cert",
    valid_days: int = 365,
    key_size: int = 4096,
) -> Dict[str, str]:
    """
    Function used to create a self-signed certificate with X.509 v3 extensions.

    Args:
        subject (str): Certificate common name field.
        valid_days (int): number of days certificate is valid for.
        key_size (int): size of the generated private key.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    serial = x509.random_serial_number()
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )

    # v3_ca extensions
    subject_key_id = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    authority_key_id = x509.AuthorityKeyIdentifier(
        authority_cert_issuer=[x509.DirectoryName(subject_name)],
        authority_cert_serial_number=serial,
        key_identifier=subject_key_id.digest
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
        .serial_number(serial)
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=valid_days)
        )
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

    return {
        "certificate": certificate,
        "privateKey": private_key,
        "thumbprint": thumbprint,
    }


def create_ca_signed_certificate(
    subject: str,
    ca_public: str,
    ca_private: str,
    cert_output_dir: Optional[str] = None,
    cert_file: Optional[str] = None,
    key_size: int = 4096,
    valid_days: Optional[int] = 365,
) -> Dict[str, str]:
    """
    Function used to create a new X.509 v3 certificate signed by an existing CA cert.

    Args:
        subject (str): Certificate common name field.
        ca_public (str): Signing CA public key
        ca_private (str): Signing CA private key
        cert_output_dir (str): string value of output directory.
        cert_file (bool): Certificate file name if it needs to be different from the subject.
        key_size (str): The size of the generated private key
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    ca_public_key = ca_public.encode("utf-8")
    ca_private_key = ca_private.encode("utf-8")
    ca_key = serialization.load_pem_private_key(ca_private_key, password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_public_key)

    # v3 certificate extensions
    subject_key_id = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    auth_subject_key = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier) or subject_key_id
    authority_key_id = x509.AuthorityKeyIdentifier(
        authority_cert_issuer=[x509.DirectoryName(ca_cert.subject)],
        authority_cert_serial_number=ca_cert.serial_number,
        key_identifier=auth_subject_key.value.digest
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
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(ca_cert.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=valid_days)
        )
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
            file_name=f"{cert_file or subject}.cert.pem",
        )
        write_content_to_file(
            content=privateKey,
            destination=cert_output_dir,
            file_name=f"{cert_file or subject}.key.pem",
        )
    return {
        "certificate": certificate,
        "thumbprint": thumbprint,
        "privateKey": privateKey,
    }


def load_ca_cert_info(
    cert_path: str, key_path: str, password: Optional[str] = None
) -> Dict[str, str]:
    """
    Function used to load CA certificate public and private key content
    into our certificate / thumprint / privateKey format.

    Args:
        cert_path (str): Path to certificate public key file.
        key_path (str): Path to the certificate private key file.
        password (str): Optional password used to unlock the private key.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """
    for path in [cert_path, key_path]:
        if not exists(path):
            raise FileOperationError(
                f"Error loading certificates. No file found at path '{path}'"
            )
    # open cert files and get string contents
    key_str = open_certificate(key_path).encode("utf-8")
    cert_str = open_certificate(cert_path).encode("utf-8")

    # load certificates
    try:
        cert_obj = x509.load_pem_x509_certificate(cert_str)
        key_obj = serialization.load_pem_private_key(
            key_str, password=(password.encode("utf-8") if password else None)
        )
    except Exception as ex:
        raise FileOperationError(f"Error loading certificate info:\n{ex}")

    # create correctly stringified versions
    key = key_obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    thumbprint = cert_obj.fingerprint(hashes.SHA256()).hex().upper()
    cert_dump = cert_obj.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    return {
        "certificate": cert_dump,
        "thumbprint": thumbprint,
        "privateKey": key,
    }


def make_cert_chain(
    certs: List[str],
    output_dir: Optional[str] = None,
    output_file: Optional[str] = None,
) -> str:
    """
    Function used to create a simple chain certificate file on disk.

    Args:
        certs List[str]: List of certificate contents (strings) to write to the file.
        output_dir str: The output directory to write the chained cert to.
        output_file str: The file name of the written certificate chain file.

    Returns:
        cert_content str: String content of chained certs
    """
    cert_content = "".join(certs)
    if output_dir and exists(output_dir) and len(certs):
        write_content_to_file(
            content=cert_content,
            destination=output_dir,
            file_name=output_file or "cert-chain.pem",
            overwrite=True,
        )
    return cert_content
