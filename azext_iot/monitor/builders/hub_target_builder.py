# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio

from azure.cli.core.azclierror import CLIInternalError
from azure.eventhub.aio import EventHubConsumerClient
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import url_encode_str
from azext_iot.monitor.models.target import Target


class AmqpBuilder:
    """Helper class for building AMQP endpoints (used by C2D operations)"""
    @classmethod
    def build_iothub_amqp_endpoint_from_target(cls, target, duration=360):
        hub_name = target["entity"].split(".")[0]
        user = "{}@sas.root.{}".format(target["policy"], hub_name)
        sas_token = SasTokenAuthentication(
            target["entity"], target["policy"], target["primarykey"], duration
        ).generate_sas_token()
        return url_encode_str(user) + ":{}@{}".format(
            url_encode_str(sas_token), target["entity"]
        )


class EventTargetBuilder:
    def __init__(self):
        self.eventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.eventLoop)

    def build_iot_hub_target(self, target):
        return self.eventLoop.run_until_complete(
            self._build_iot_hub_target_async(target)
        )

    async def _build_iot_hub_target_async(self, target):
        # Event Hub endpoint should be provided via include_events=True in discovery
        if "events" not in target:
            raise CLIInternalError(
                "Event Hub endpoint information is missing. "
                "Ensure the target includes Event Hub configuration."
            )
        endpoint = target["events"]["endpoint"]
        path = target["events"]["path"]
        partition_ids = target["events"].get("partition_ids", [])
        partition_count = target["events"].get("partition_count", 0)
        if partition_ids:
            return Target(hostname=endpoint, path=path, partitions=partition_ids, policy=target["policy"], key=target["primarykey"])
        if partition_count:
            for i in range(int(partition_count)):
                partition_ids.append(str(i))
            return Target(hostname=endpoint, path=path, partitions=partition_ids, policy=target["policy"], key=target["primarykey"])
        
        # Query partition metadata using azure-eventhub
        connection_str = f"Endpoint=sb://{endpoint}/;SharedAccessKeyName={target['policy']};SharedAccessKey={target['primarykey']};EntityPath={path}"
        client = EventHubConsumerClient.from_connection_string(
            connection_str,
            consumer_group="$Default",
            eventhub_name=path,
        )
        
        try:
            async with client:
                amqp_partition_ids = await client.get_partition_ids()
                if amqp_partition_ids:
                    return Target(
                        hostname=endpoint,
                        path=path,
                        partitions=list(amqp_partition_ids),
                        policy=target["policy"],
                        key=target["primarykey"]
                    )
        except Exception as e:
            raise CLIInternalError(
                f"Unable to query partitions for '{target['entity'].split('.')[0]}': {e}"
            )

        raise CLIInternalError(
            f"Unable to determine partitions for '{target['entity'].split('.')[0]}'."
        )
