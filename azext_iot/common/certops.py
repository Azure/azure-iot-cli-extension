# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
certops: Functions for working with certificates.
"""

from os.path import exists, join
import base64
from OpenSSL import crypto


def create_self_signed_certificate(subject, valid_days, cert_output_dir, cert_only=False):
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
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)

    # create a self-signed cert
    cert = crypto.X509()
    cert.get_subject().CN = subject
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(valid_days * 24 * 60 * 60)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')

    cert_dump = crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('utf-8')
    key_dump = crypto.dump_privatekey(crypto.FILETYPE_PEM, key).decode('utf-8')
    thumbprint = cert.digest('sha1').replace(b':', b'').decode('utf-8')

    if cert_output_dir and exists(cert_output_dir):
        cert_file = subject + '-cert.pem'
        key_file = subject + '-key.pem'

        open(join(cert_output_dir, cert_file), "wt").write(cert_dump)

        if not cert_only:
            open(join(cert_output_dir, key_file), "wt").write(key_dump)

    result = {
        'certificate': cert_dump,
        'privateKey': key_dump,
        'thumbprint': thumbprint
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
    if certificate_path.endswith('.pem') or certificate_path.endswith('.cer'):
        with open(certificate_path, "rb") as cert_file:
            certificate = cert_file.read()
            try:
                certificate = certificate.decode("utf-8")
            except UnicodeError:
                certificate = base64.b64encode(certificate).decode("utf-8")
    return certificate.rstrip()  # Remove trailing white space from the certificate content
