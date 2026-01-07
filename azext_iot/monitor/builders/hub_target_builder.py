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
        # If events metadata not provided, attempt to discover it
        if "events" not in target:
            event_info = await self._discover_eventhub_endpoint(target)
            if event_info:
                target["events"] = event_info
            else:
                raise CLIInternalError(
                    f"Unable to discover Event Hub endpoint for '{target['entity']}'. "
                    "Event Hub endpoint must be obtained via REST API. "
                    "Please ensure include_events=True is set when calling discovery.get_target()."
                )

        endpoint = target["events"]["endpoint"]
        path = target["events"]["path"]
        partition_ids = target["events"].get("partition_ids", [])
        partition_count = target["events"].get("partition_count", 0)
        if partition_ids:
            return Target(
                hostname=endpoint, path=path, partitions=partition_ids,
                policy=target["policy"], key=target["primarykey"]
            )
        if partition_count:
            for i in range(int(partition_count)):
                partition_ids.append(str(i))
            return Target(
                hostname=endpoint, path=path, partitions=partition_ids,
                policy=target["policy"], key=target["primarykey"]
            )

        # Query partition metadata using azure-eventhub
        connection_str = (
            f"Endpoint=sb://{endpoint}/;"
            f"SharedAccessKeyName={target['policy']};"
            f"SharedAccessKey={target['primarykey']};"
            f"EntityPath={path}"
        )
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

    async def _discover_eventhub_endpoint(self, target):
        """
        Discover Event Hub endpoint using Azure IoT Hub Management API.

        """
        try:
            from azext_iot._factory import iot_hub_service_factory
            from azext_iot.common.utility import trim_from_start

            # Get the IoT Hub Management client from the target's command context
            cmd = target.get("cmd")
            if not cmd:
                return None

            hub_name = target.get("name")
            resource_group = target.get("resourcegroup")
            subscription = target.get("subscription")

            if not all([hub_name, resource_group, subscription]):
                # Missing required information to query Azure Resource Manager
                return None

            # Query the IoT Hub resource to get Event Hub endpoint information
            client = iot_hub_service_factory(cmd.cli_ctx).iot_hub_resource
            resource = client.get(resource_group, hub_name)

            if resource and resource.properties and resource.properties.event_hub_endpoints:
                events_endpoint = resource.properties.event_hub_endpoints.get("events")
                if events_endpoint:
                    return {
                        "endpoint": trim_from_start(events_endpoint.endpoint, "sb://").strip("/"),
                        "path": events_endpoint.path,
                        "partition_count": events_endpoint.partition_count,
                        "partition_ids": events_endpoint.partition_ids
                    }
        except Exception as e:
            # If discovery fails, log the error and return None
            # This will trigger the helpful error message in the caller
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Event Hub endpoint discovery failed: {e}")

        return None
