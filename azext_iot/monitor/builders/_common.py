# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import uamqp
import urllib

from azext_iot.monitor.models.target import Target

DEBUG = False


async def convert_token_to_target(tokens) -> Target:
    token_expiry = tokens["expiry"]
    event_hub_token = tokens["eventhubSasToken"]

    sas_token = event_hub_token["sasToken"]
    path = event_hub_token["entityPath"]
    raw_url = event_hub_token["hostname"]

    url = urllib.parse.urlparse(raw_url)
    hostname = url.hostname

    meta_data = await _query_meta_data_internal(hostname, path, sas_token, token_expiry)

    partition_count = meta_data[b"partition_count"]
    partitions = [str(i) for i in range(int(partition_count))]

    auth = _build_auth_container_from_token(hostname, path, sas_token, token_expiry)

    return Target(hostname=hostname, path=path, partitions=partitions, auth=auth)


async def query_meta_data(address, path, auth):
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


async def _query_meta_data_internal(hostname, path, sas_token, token_expiry):
    address = "amqps://{}/{}/$management".format(hostname, path)
    auth = _build_auth_container_from_token(hostname, path, sas_token, token_expiry)
    return await query_meta_data(address=address, path=path, auth=auth)


def _build_auth_container_from_token(hostname, path, token, expiry):
    sas_uri = "sb://{}/{}".format(hostname, path)
    return uamqp.authentication.SASTokenAsync(
        audience=sas_uri, uri=sas_uri, expires_at=expiry, token=token
    )
