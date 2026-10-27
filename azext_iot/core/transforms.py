# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Output transforms that bridge legacy Azure CLI and modeless SDK shapes."""

import base64
import binascii

from knack.log import get_logger

from azure.cli.command_modules.iot._utils import (
    _dps_certificate_response_transform as _legacy_dps_certificate_transform,
    _safe_decode,
)


logger = get_logger(__name__)


def _decode_modelless_certificate(certificate: dict) -> dict:
    properties = certificate.get("properties")
    if not isinstance(properties, dict) or not properties.get("certificate"):
        return certificate

    value = properties["certificate"]
    if isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
    elif isinstance(value, str):
        if value.lstrip().startswith("-----BEGIN"):
            return certificate
        try:
            encoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            # A plain text value is already in the legacy output form.
            return certificate
    else:
        return certificate

    decoded = _safe_decode(encoded)
    if decoded is None:
        logger.warning(
            "Certificate `%s` contains invalid unicode characters; its body "
            "was omitted from output.",
            certificate.get("name"),
        )
        properties["certificate"] = None
    else:
        properties["certificate"] = decoded
    return certificate


def dps_certificate_response_transform(response):
    """Decode only management-certificate bodies for legacy output parity."""
    response = _legacy_dps_certificate_transform(response)
    if not isinstance(response, dict):
        return response

    values = response.get("value")
    if isinstance(values, list):
        for certificate in values:
            if isinstance(certificate, dict):
                _decode_modelless_certificate(certificate)
        return response

    return _decode_modelless_certificate(response)
