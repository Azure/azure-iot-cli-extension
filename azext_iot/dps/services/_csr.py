# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
import binascii
import re

from azure.cli.core.azclierror import InvalidArgumentValueError
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID


def normalize_csr(value, registration_id):
    """Validate PKCS #10 and serialize base64 DER, without PEM armor."""
    try:
        encoded = value.encode("ascii")
        if value.lstrip().startswith("-----BEGIN") and not re.fullmatch(
            rb"-----BEGIN (CERTIFICATE REQUEST|NEW CERTIFICATE REQUEST)-----\s+"
            rb"[A-Za-z0-9+/=\s]+-----END \1-----", encoded.strip()
        ):
            raise ValueError("Expected one PEM certificate signing request.")
        csr = (
            x509.load_pem_x509_csr(encoded)
            if value.lstrip().startswith("-----BEGIN")
            else x509.load_der_x509_csr(base64.b64decode(encoded, validate=True))
        )
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise InvalidArgumentValueError("--csr must contain one PEM or base64 DER PKCS #10 request.") from error
    if not csr.is_signature_valid:
        raise InvalidArgumentValueError("CSR signature is invalid.")
    names = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(names) != 1 or names[0].value != registration_id:
        raise InvalidArgumentValueError("CSR Common Name must match --registration-id.")
    return base64.b64encode(csr.public_bytes(Encoding.DER)).decode("ascii")
