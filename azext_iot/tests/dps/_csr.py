# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Fresh CSR material shared by parser contracts and owned issuance integration."""

from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509.oid import NameOID


def generate_csr(names=("reg",)):
    key = ec.generate_private_key(ec.SECP256R1())
    request = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name) for name in names])
    ).sign(key, hashes.SHA256())
    return key, request


@contextmanager
def temporary_csr(directory, registration_id):
    key, request = generate_csr((registration_id,))
    with TemporaryDirectory(prefix="csr-", dir=directory) as temporary:
        for name, content in (
            ("key.pem", key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())),
            ("request.pem", request.public_bytes(Encoding.PEM)),
        ):
            with os.fdopen(os.open(Path(temporary) / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                output.write(content)
        yield Path(temporary) / "request.pem"
