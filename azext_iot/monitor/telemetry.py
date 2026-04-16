# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import sys
from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub import TransportType
from azext_iot.monitor.models.enum import Transport
from azure.cli.core.azclierror import CLIInternalError
from datetime import datetime, timezone

from uuid import uuid4
from knack.log import get_logger
from typing import List
from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.monitor.models.target import Target
from azext_iot.monitor.utility import get_http_proxy_settings, get_loop

logger = get_logger(__name__)
DEBUG = False


def start_single_monitor(
    target: Target,
    enqueued_time_utc,
    on_start_string: str,
    on_message_received,
    timeout=0,
    transport=None,
):
    """
    :param on_message_received:
        A callback to process messages as they arrive from the service.
        It takes a single argument, a message object.
    """
    return start_multiple_monitors(
        targets=[target],
        enqueued_time_utc=enqueued_time_utc,
        on_start_string=on_start_string,
        on_message_received=on_message_received,
        timeout=timeout,
        transport=transport,
    )


def start_multiple_monitors(
    targets: List[Target],
    on_start_string: str,
    enqueued_time_utc,
    on_message_received,
    timeout=0,
    transport=None,
):
    """
    :param on_message_received:
        A callback to process messages as they arrive from the service.
        It takes a single argument, a message object.
    """
    coroutines = [
        _initiate_event_monitor(
            target=target,
            enqueued_time_utc=enqueued_time_utc,
            on_message_received=on_message_received,
            timeout=timeout,
            transport=transport,
        )
        for target in targets
    ]

    loop = get_loop()

    future = asyncio.gather(*coroutines, return_exceptions=True)
    result = None

    try:
        print(on_start_string, flush=True)
        future.add_done_callback(lambda _: _stop_and_suppress_eloop(loop))
        result = loop.run_until_complete(future)
    except KeyboardInterrupt:
        print("Stopping event monitor...", flush=True)
        try:
            # TODO: remove when deprecating
            # pylint: disable=no-member
            tasks = asyncio.all_tasks(loop)
            for t in tasks:  # pylint: disable=no-member
                t.cancel()
            loop.run_forever()
        except RuntimeError:
            pass  # no running loop anymore
    finally:
        if result:
            if isinstance(result[0], Exception):
                raise result[0]

            errors = result[0]
            if errors and errors[0]:
                logger.debug(errors)
                raise RuntimeError(errors[0])


async def _initiate_event_monitor(
    target: Target, enqueued_time_utc, on_message_received, timeout=0, transport=None
):
    if not target.partitions:
        logger.warning("No Event Hub partitions found to listen on.")
        return

    # Create EventHub Consumer Client
    # Note: azure-eventhub SDK uses different patterns for async context:
    #   - IoT Hub: Connection string with policy+key (SDK handles auth internally)
    #   - IoT Central: AzureSasCredential with pre-generated token
    # EventHubSharedKeyCredential has sync/async compatibility issues with aio client

    proxy_settings = get_http_proxy_settings()

    if target.policy and target.key:
        # IoT Hub: Use connection string (works with async EventHubConsumerClient)
        connection_str = (
            f"Endpoint=sb://{target.hostname}/;"
            f"SharedAccessKeyName={target.policy};"
            f"SharedAccessKey={target.key};"
            f"EntityPath={target.path}"
        )
        create_kwargs = {
            "consumer_group": target.consumer_group,
            "eventhub_name": target.path,
        }
        if transport == Transport.AMQP_WS or proxy_settings:
            create_kwargs["transport_type"] = TransportType.AmqpOverWebsocket
        if proxy_settings:
            create_kwargs["http_proxy"] = proxy_settings

        consumer_client = EventHubConsumerClient.from_connection_string(
            connection_str,
            **create_kwargs,
        )
    elif target.sas_credential:
        # IoT Central: Use pre-generated SAS token credential
        create_kwargs = {
            "fully_qualified_namespace": target.hostname,
            "eventhub_name": target.path,
            "consumer_group": target.consumer_group,
            "credential": target.sas_credential,
        }
        if transport == Transport.AMQP_WS or proxy_settings:
            create_kwargs["transport_type"] = TransportType.AmqpOverWebsocket
        if proxy_settings:
            create_kwargs["http_proxy"] = proxy_settings

        consumer_client = EventHubConsumerClient(**create_kwargs)
    else:
        raise CLIInternalError(
            "Target object is missing authentication credentials. "
            "This indicates an internal error in target construction."
        )

    try:
        receive_tasks = []
        for partition_id in target.partitions:
            receive_tasks.append(
                _monitor_events(
                    consumer_client=consumer_client,
                    partition_id=partition_id,
                    enqueued_time_utc=enqueued_time_utc,
                    on_message_received=on_message_received,
                    timeout=timeout,
                )
            )
        return await asyncio.gather(*receive_tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error during event monitoring: {e}")
        raise RuntimeError(f"Event monitoring failed: {e}")


async def _monitor_events(
    consumer_client,
    partition_id,
    enqueued_time_utc,
    on_message_received,
    timeout=0,
):
    """Monitor events using EventHub SDK"""
    try:
        async def on_event(partition_context, event):
            on_message_received(event)

        # Convert milliseconds to datetime for EventHub SDK
        if isinstance(enqueued_time_utc, int):
            starting_position = datetime.fromtimestamp(enqueued_time_utc / 1000.0, tz=timezone.utc)
        else:
            starting_position = enqueued_time_utc

        receive_kwargs = {
            "on_event": on_event,
            "partition_id": str(partition_id),
            "starting_position": starting_position,
        }

        async with consumer_client:
            if timeout > 0:
                timeout_seconds = timeout / 1000.0
                await asyncio.wait_for(consumer_client.receive(**receive_kwargs), timeout=timeout_seconds)
            else:
                await consumer_client.receive(**receive_kwargs)

    except asyncio.TimeoutError:
        # This is expected - timeout means monitoring period is over
        pass
    except asyncio.CancelledError:
        logger.info("Monitoring cancelled on partition %s", partition_id)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, closing monitor on partition %s", partition_id)
        raise
    finally:
        logger.info("Closed monitor on partition %s", partition_id)


def _stop_and_suppress_eloop(loop):
    try:
        loop.stop()
    except Exception as e:
        logger.debug("Failed to stop event loop: %s", e)


def _get_conn_props():
    return {
        "product": USER_AGENT,
        "version": VERSION,
        "framework": "Python {}.{}.{}".format(*sys.version_info[0:3]),
        "platform": sys.platform,
    }


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))
