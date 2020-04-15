# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError
from azext_iot.common._azure import _get_aad_token


def _get_dps_sas_auth_header(
    scope_id, device_id, key,
):
    import time
    import base64
    import hmac
    import hashlib
    import urllib

    sr = "{}%2Fregistrations%2F{}".format(scope_id, device_id)
    expires = int(time.time() + 21600)
    registration_id = f"{sr}\n{str(expires)}"
    secret = base64.b64decode(key)
    signature = base64.b64encode(
        hmac.new(
            secret, msg=registration_id.encode("utf8"), digestmod=hashlib.sha256
        ).digest()
    )
    quote_signature = urllib.parse.quote(signature, "~()*!.'")
    token = f"SharedAccessSignature sr={sr}&sig={quote_signature}&se={str(expires)}&skn=registration"
    return token


def validate_response_payload(response):
    if response.status_code in [200, 201]:
        return response.json()
    exp = CloudError(response)
    exp.request_id = response.headers.get("x-ms-request-id")
    raise exp


def get_iot_central_device_list(app_id, token):
    import requests

    host = get_app_host(app_id, token)["host"]
    url = "https://{}/api/preview/devices".format(host)
    response = requests.get(url, headers={"Authorization": "Bearer {}".format(token)})
    return validate_response_payload(response)


def get_app_host(app_id, token):
    import requests

    url = "https://apps.azureiotcentral.com/api/preview/applications/{}".format(app_id)
    response = requests.get(url, headers={"Authorization": "Bearer {}".format(token)})
    return validate_response_payload(response)


def show_iot_central_provisioning_information(cmd, app_id, device_id):
    aad_token = _get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
        "accessToken"
    ]
    if device_id is None:
        device_list = get_iot_central_device_list(app_id, aad_token)
        print("Device Provisioning Summary:")
        for item in device_list.get("value"):
            print("\n")
            data = {
                i: item.get(i) for i in ["id", "displayName", "provisioned", "approved"]
            }
            print("{}".format(data))
    else:
        deviceCredentialData = get_iot_central_device_api_tokens(
            cmd, app_id, device_id, aad_token
        )
        show_iot_central_device_provisioning_information(
            deviceCredentialData["idScope"],
            deviceCredentialData["symmetricKey"]["primaryKey"],
            device_id,
        )


def get_iot_central_device_api_tokens(cmd, app_id, device_id, token):
    import requests

    host = get_app_host(app_id, token)["host"]
    url = "https://{}/api/preview/devices/{}/credentials".format(host, device_id)
    response = requests.get(url, headers={"Authorization": "Bearer {}".format(token)})
    return validate_response_payload(response)


def show_iot_central_device_provisioning_information(id_scope, primary_key, device_id):
    provisioning_status = get_iot_central_device_provisioning_information(
        id_scope, primary_key, device_id
    )
    print("provisioning information :\n")
    for k, v in provisioning_status.items():
        print("{} : {}\n".format(k, v))


def get_iot_central_device_provisioning_information(id_scope, primary_key, device_id):
    import requests

    authToken = _get_dps_sas_auth_header(id_scope, device_id, primary_key)

    url = "https://global.azure-devices-provisioning.net/{}/registrations/{}?api-version=2019-03-31".format(
        id_scope, device_id
    )
    header_parameters = {}
    header_parameters["Content-Type"] = "application/json"
    header_parameters["Authorization"] = "{}".format(authToken)
    body = {"registrationId": "{}".format(device_id)}
    response = requests.post(url, headers=header_parameters, json=body)
    return validate_response_payload(response)


def get_iot_central_tokens(cmd, app_id, central_api_uri):
    def get_event_hub_token(app_id, iotcAccessToken):
        import requests

        url = "https://{}/v1-beta/applications/{}/diagnostics/sasTokens".format(
            central_api_uri, app_id
        )
        response = requests.post(
            url, headers={"Authorization": "Bearer {}".format(iotcAccessToken)}
        )
        return response.json()

    aad_token = _get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
        "accessToken"
    ]

    tokens = get_event_hub_token(app_id, aad_token)

    if tokens.get("error"):
        raise CLIError(
            "Error {} getting tokens. {}".format(
                tokens["error"]["code"], tokens["error"]["message"]
            )
        )

    return tokens


def get_iot_hub_token_from_central_app_id(cmd, app_id, central_api_uri):
    return get_iot_central_tokens(cmd, app_id, central_api_uri)["iothubTenantSasToken"][
        "sasToken"
    ]
