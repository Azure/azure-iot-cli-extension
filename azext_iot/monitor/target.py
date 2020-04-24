# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import asyncio
import uamqp
import urllib

from azext_iot.common._azure import get_iot_central_tokens

DEBUG = False


class Target:
    def __init__(
        self,
        hostname: str,
        path: str,
        partitions: list,
        auth: uamqp.authentication.SASTokenAsync,
    ):
        self.hostname = hostname
        self.path = path
        self.auth = auth
        self.partitions = partitions


def build_central_event_hub_target(cmd, app_id, central_api_uri) -> Target:
    event_loop = asyncio.get_event_loop()
    return event_loop.run_until_complete(
        _build_central_event_hub_target_async(cmd, app_id, central_api_uri)
    )


async def _build_central_event_hub_target_async(cmd, app_id, central_api_uri) -> Target:
    tokens = get_iot_central_tokens(cmd, app_id, central_api_uri)

    token_expiry = tokens["expiry"]
    token = tokens["eventhubSasToken"]

    sas_token = token["sasToken"]
    path = token["entityPath"]
    raw_url = token["hostname"]

    url = urllib.parse.urlparse(raw_url)
    hostname = url.hostname

    meta_data = await _query_meta_data(hostname, path, sas_token, token_expiry)

    partition_count = meta_data[b"partition_count"]
    partitions = [str(i) for i in range(int(partition_count))]

    auth = _build_auth_container_from_token(hostname, path, sas_token, token_expiry)

    return Target(hostname=hostname, path=path, partitions=partitions, auth=auth)


def _build_auth_container_from_token(hostname, path, token, tokenExpiry):
    sas_uri = "sb://{}/{}".format(hostname, path)
    return uamqp.authentication.SASTokenAsync(
        audience=sas_uri, uri=sas_uri, expires_at=tokenExpiry, token=token
    )


async def _query_meta_data(hostname, path, sas_token, token_expiry):
    address = "amqps://{}/{}/$management".format(hostname, path)
    auth = _build_auth_container_from_token(hostname, path, sas_token, token_expiry)
    source = uamqp.address.Source(address)
    receive_client = uamqp.ReceiveClientAsync(
        source, auth=auth, timeout=30000, debug=DEBUG
    )
    try:
        await receive_client.open_async()
        message = uamqp.Message(application_properties={"name": path})

        response = await receive_client.mgmt_request_async(
            message,
            b"READ",
            op_type=b"com.microsoft:eventhub",
            status_code_field=b"status-code",
            description_fields=b"status-description",
            timeout=30000,
        )
        test = response.get_data()
        return test
    finally:
        await receive_client.close_async()
