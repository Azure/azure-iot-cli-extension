# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Test cert utils: Functions for working with certificates for test devices in dps
"""

import datetime
from azure.cli.core.azclierror import CLIInternalError
from os.path import exists, join
from typing import Any, Dict
from cryptography import x509
from cryptography.x509.base import Certificate
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def _load_cert_data(
    cert_path: str = None,
    key_path: str = None,
    cert_object: Dict[str, str] = None,
    password: str = None
):
    """
    Function used to load certificate data. Will open from files or parse the certificate object
    created from create_self_signed_certificate.

    Args:
        cert_path (str): Path to certificate pem file.
        key_path (str): Path to key pem file.
        cert_object (dict): dict with certificate value, private key and thumbprint, returned from
            create_self_signed_certificate
        password (str): password for loading the private key.
    Returns:
        result (dict): dict with certificate object, certificate text, and private key object.
    """
    if not any([cert_path, key_path, cert_object]):
        return {}

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
            raise CLIInternalError("Need key file to sign new certificate.")

        if cert_path and cert_path.endswith(".pem"):
            with open(cert_path, "rb") as cert_file:
                pem_cert_text = cert_file.read()
        else:
            raise CLIInternalError("Need certificate file to get issuer for new certificate.")
    result = {
        "certificate": x509.load_pem_x509_certificate(pem_cert_text),
        "certificate_text": pem_cert_text.decode("utf-8"),
        "key": load_pem_private_key(pem_key_data, password=password)
    }
    return result


def _generate_root_certificate(subject: str, valid_days: int, key: rsa.RSAPrivateKey) -> Certificate:
    """
    Function to generate the root certificate that will be uploaded to the dps and used as
    enrollment group certificate.

    Args:
        subject (str): The subject for the certificate.
        valid_days (int): Number of days certificate should be valid.
        key (RSAPrivateKey): The private key to be associated with this certificate.
    Returns:
        cert (Certificate): Certificate object.
    """
    subject_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, subject)]
    )
    return (
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
            x509.BasicConstraints(ca=True, path_length=None), critical=True
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


def _generate_device_certificate(
    subject: str, valid_days: int, key: rsa.RSAPrivateKey, root_cert_obj: Dict[str, Any]
) -> Certificate:
    """
    Function to generate the device or verification certificate signed by a root certificate.

    If making a verification certificate, the subject must be the verification code.
    If making a device certificate, the subject must be the device id.

    Args:
        subject (str): The subject for the certificate.
        valid_days (int): Number of days certificate should be valid.
        key (RSAPrivateKey): The private key to be associated with this certificate.
        root_cert_obj (dict): The dictionary containing the root certificate and key to be used,
            returned from _load_cert_data
    Returns:
        cert (Certificate): Certificate object.
    """
    root_cert = root_cert_obj["certificate"]
    root_key = root_cert_obj["key"]
    # create a self-signed cert
    subject_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject),
        ]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(root_cert.issuer)
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
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_cert.public_key()), critical=False
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
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


def create_certificate(
    subject: str,
    valid_days: int,
    cert_output_dir: str,
    file_prefix: str = None,
    cert_path: str = None,
    key_path: str = None,
    cert_object: Dict[str, str] = None,
    loading_password: str = None,
    signing_password: str = None,
    chain_cert: bool = False
):
    """
    Function used to create a self-signed (root), verification, or device certificate.

    Args:
        subject (str): Certificate common name; host name or wildcard.
        valid_days (int): number of days certificate is valid for; used to calculate
            certificate expiry.
        cert_output_dir (str): string value of output directory.
        file_prefix (str): Certificate and key file name if it needs to be different from the subject.
        cert_path (str): Path to certificate pem file.
        key_path (str): Path to key pem file.
        cert_object (dict): dict with certificate value, private key and thumbprint, returned from
            create_self_signed_certificate
        loading_password (str): loading_password for loading the private key within the given certificate.
        signing_password (str): signing_password for encrypting the new private key.
        chain_cert (bool): whether the cert object should have the root certificate in it.
            Required for device certificates.

    Returns:
        result (dict): dict with certificate value, private key and thumbprint.
    """
    # Get root certificate and key if needed
    root_cert_object = {}
    if any([cert_path, key_path, cert_object]):
        root_cert_object = _load_cert_data(cert_path, key_path, cert_object, loading_password)

    # create a key pair
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # create a cert
    cert = (
        _generate_device_certificate(subject, valid_days, key, root_cert_object)
        if root_cert_object else
        _generate_root_certificate(subject, valid_days, key)
    )

    # dump the data
    encryption = (
        serialization.BestAvailableEncryption(str.encode(signing_password))
        if signing_password else
        serialization.NoEncryption()
    )
    key_dump = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=encryption,
    ).decode("utf-8")
    cert_dump = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumbprint = cert.fingerprint(hashes.SHA256()).hex().upper()

    if cert_output_dir and exists(cert_output_dir):
        cert_file = (file_prefix or subject) + "-cert.pem"
        key_file = (file_prefix or subject) + "-key.pem"

        with open(join(cert_output_dir, cert_file), "wt", encoding="utf-8") as f:
            f.write(cert_dump)
            if chain_cert:
                f.write(root_cert_object.get("certificate_text"))

        with open(join(cert_output_dir, key_file), "wt", encoding="utf-8") as f:
            f.write(key_dump)

    result = {
        "certificate": cert_dump,
        "privateKey": key_dump,
        "thumbprint": thumbprint,
    }

    return result
