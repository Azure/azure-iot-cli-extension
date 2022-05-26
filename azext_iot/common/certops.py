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
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def create_self_signed_certificate(
    subject, valid_days, cert_output_dir, cert_only=False, alt_name=None, allowed_signing=0,
):
    """
    Function used to create a self-signed certificate

    Args:
        subject (str): Certificate common name; host name or wildcard.
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.
        cert_putput_dir (str): string value of output directory.
        cert_only (bool): generate certificate only; no private key or thumbprint.
        alt_name (str): Certificate file name if it needs to be different from the subject.

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
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=allowed_signing), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True
        )
        .sign(key, hashes.SHA256())
    )

    key_dump = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    cert_dump = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA1()).hex().upper()

    if cert_output_dir and exists(cert_output_dir):
        cert_file = (alt_name or subject) + "-cert.pem"
        key_file = (alt_name or subject) + "-key.pem"

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


def create_key_signed_certificate(
    subject,
    valid_days,
    cert_output_dir,
    alt_name=None,
    cert_path=None,
    key_path=None,
    cert_object=None,
    password=None,
    allowed_signing=0,
):
    """
    Function used to create a self-signed certificate chained from the given certificate.

    Args:
        subject (str): Certificate common name; host name or wildcard.
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.
        cert_putput_dir (str): string value of output directory.
        alt_name (str): Certificate file name if it needs to be different from the subject.
        cert_path (str): Certificate path of the certificate to chain off.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """
    pem_cert_text = ""
    pem_key_data = ""
    if cert_object:
        pem_cert_text = cert_object["certificate"].encode("utf-8")
        pem_key_data = cert_object["privateKey"].encode("utf-8")
    else:
        if key_path and key_path.endswith(".pem"):
            with open(key_path, "rb") as cert_file:
                pem_key_data = cert_file.read()
        else:
            raise Exception("Need key file to sign new certificate.")

        if cert_path and cert_path.endswith(".pem"):
            with open(cert_path, "rb") as cert_file:
                pem_cert_text = cert_file.read()
        else:
            raise Exception("Need certificate file to get issuer for new certificate.")
    root_cert = x509.load_pem_x509_certificate(pem_cert_text)
    root_key = load_pem_private_key(pem_key_data, password=password)

    cert_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(root_cert.issuer)
        .public_key(cert_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=valid_days)
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(cert_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_cert.public_key()), critical=False
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=allowed_signing), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True
        )
        .sign(root_key, hashes.SHA256())
    )
    # import pdb; pdb.set_trace()

    key_dump = cert_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    cert_dump = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA1()).hex().upper()

    if cert_output_dir and exists(cert_output_dir):
        cert_file = (alt_name or subject) + "-cert.pem"
        key_file = (alt_name or subject) + "-key.pem"

        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(cert_dump)

        with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
            f.write(key_dump)

    result = {
        "certificate": cert_dump,
        "privateKey": key_dump,
        "thumbprint": thumbprint,
    }

    return result
