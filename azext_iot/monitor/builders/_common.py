# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import urllib
from azure.eventhub.aio import EventHubConsumerClient
from azure.core.credentials import AzureSasCredential
from azext_iot.monitor.models.target import Target


async def convert_token_to_target(tokens) -> Target:
    event_hub_token = tokens["eventhubSasToken"]

    sas_token = event_hub_token["sasToken"]
    path = event_hub_token["entityPath"]
    raw_url = event_hub_token["hostname"]

    url = urllib.parse.urlparse(raw_url)
    hostname = url.hostname

    credential = AzureSasCredential(sas_token)
    partition_count = await _query_partition_count(hostname, path, credential)
    partitions = [str(i) for i in range(partition_count)]

    return Target(hostname=hostname, path=path, partitions=partitions, sas_credential=credential)


async def _query_partition_count(hostname, path, credential):
    fully_qualified_namespace = hostname

    client = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=path,
        consumer_group="$Default",
        credential=credential,
    )

    try:
        async with client:
            partition_ids = await client.get_partition_ids()
            return len(partition_ids)
    except Exception as e:
        raise RuntimeError(f"Failed to query Event Hub metadata: {e}")
