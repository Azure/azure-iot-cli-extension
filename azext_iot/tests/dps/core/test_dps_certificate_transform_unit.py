# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64

from azext_iot.core import transforms


PEM = "-----BEGIN CERTIFICATE-----\nY2VydA==\n-----END CERTIFICATE-----\n"


def _encoded(value=PEM):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def test_modeless_certificate_list_preserves_shape_and_decodes_each_body():
    response = {
        "value": [
            {
                "id": "/certificates/one",
                "name": "one",
                "etag": "etag-one",
                "properties": {
                    "certificate": _encoded(),
                    "isVerified": True,
                },
            },
            {
                "id": "/certificates/two",
                "name": "two",
                "properties": {"certificate": PEM},
            },
        ],
        "nextLink": "next",
    }

    assert transforms.dps_certificate_response_transform(response) == {
        "value": [
            {
                "id": "/certificates/one",
                "name": "one",
                "etag": "etag-one",
                "properties": {
                    "certificate": PEM,
                    "isVerified": True,
                },
            },
            {
                "id": "/certificates/two",
                "name": "two",
                "properties": {"certificate": PEM},
            },
        ],
        "nextLink": "next",
    }


def test_modeless_single_certificate_shapes_decode_bytes_and_base64():
    for value in (PEM.encode("utf-8"), bytearray(PEM, "utf-8"), _encoded()):
        response = {
            "name": "certificate",
            "properties": {
                "certificate": value,
                "verificationCode": "code",
            },
        }
        transformed = transforms.dps_certificate_response_transform(response)
        assert transformed == {
            "name": "certificate",
            "properties": {
                "certificate": PEM,
                "verificationCode": "code",
            },
        }


def test_transform_does_not_decode_registration_certificate_chains():
    encoded = _encoded()
    response = {
        "registrationState": {
            "issuedCertificateChain": [encoded],
            "properties": {"certificate": encoded},
        }
    }

    assert transforms.dps_certificate_response_transform(response) == response
    assert response["registrationState"]["issuedCertificateChain"] == [encoded]
    assert response["registrationState"]["properties"]["certificate"] == encoded


def test_transform_leaves_plain_non_base64_certificate_text_unchanged():
    response = {
        "name": "certificate",
        "properties": {"certificate": "not-base64-or-pem"},
    }
    assert transforms.dps_certificate_response_transform(response) == response


def test_transform_leaves_unknown_certificate_value_type_unchanged():
    response = {
        "name": "certificate",
        "properties": {"certificate": {"unexpected": "value"}},
    }
    assert transforms.dps_certificate_response_transform(response) == response


def test_transform_omits_invalid_utf8_certificate(caplog):
    response = {
        "name": "bad",
        "properties": {
            "certificate": base64.b64encode(b"\xff").decode("ascii")
        },
    }

    transformed = transforms.dps_certificate_response_transform(response)

    assert transformed["properties"]["certificate"] is None
    assert "invalid unicode" in caplog.text


def test_transform_delegates_legacy_models(mocker):
    model = object()
    legacy = mocker.patch.object(
        transforms,
        "_legacy_dps_certificate_transform",
        return_value=model,
    )

    assert transforms.dps_certificate_response_transform("legacy") is model
    legacy.assert_called_once_with("legacy")
