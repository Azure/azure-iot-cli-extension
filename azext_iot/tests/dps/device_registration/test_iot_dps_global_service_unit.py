# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
from unittest.mock import MagicMock

from azext_iot.dps.services import auth
from azext_iot.dps.services import global_service


def test_get_dps_sas_auth_header():
    key = base64.b64encode(b"super-secret").decode("utf-8")
    token = auth.get_dps_sas_auth_header("myscope", "device1", key)
    assert token.startswith("SharedAccessSignature sr=myscope%2Fregistrations%2Fdevice1")
    assert "sig=" in token
    assert "skn=registration" in token
    assert "&se=" in token


def test_get_registration_state_success(mocker):
    key = base64.b64encode(b"k").decode("utf-8")
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"status": "assigned"}
    post = mocker.patch("requests.post", return_value=response)

    result = global_service.get_registration_state(id_scope="scope", key=key, device_id="device1")

    assert result == {"status": "assigned"}
    post.assert_called_once()


def test_get_registration_state_error(mocker):
    key = base64.b64encode(b"k").decode("utf-8")
    response = MagicMock()
    response.raise_for_status.side_effect = Exception("boom")
    mocker.patch("requests.post", return_value=response)

    result = global_service.get_registration_state(id_scope="scope", key=key, device_id="device1")

    assert result["device_id"] == "device1"
    assert "error" in result
