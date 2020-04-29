
import asyncio
import sys
import uamqp

from uuid import uuid4
from knack.log import get_logger
from typing import List
from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.monitor.models.runner import Target, ExecutorData

logger = get_logger(__name__)
DEBUG = False


def executor(
    target: Target,
    consumer_group: str,
    enqueued_time_utc,
    on_start_string: str,
    on_message_received,
    timeout=0,
):
    """
    :param on_message_received: 
        A callback to process messages as they arrive from the service. 
        It takes a single argument, a ~uamqp.message.Message object.
    """
    executor = ExecutorData(target, consumer_group)

    return n_executor(
        executors=[executor],
        enqueued_time_utc=enqueued_time_utc,
        on_start_string=on_start_string,
        on_message_received=on_message_received,
        timeout=timeout,
    )


def n_executor(
    executors: List[ExecutorData],
    on_start_string: str,
    enqueued_time_utc,
    on_message_received,
    timeout=0,
):
    """
    :param on_message_received: 
        A callback to process messages as they arrive from the service. 
        It takes a single argument, a ~uamqp.message.Message object.
    """
    coroutines = [
        _initiate_event_monitor(
            executor=executor,
            enqueued_time_utc=enqueued_time_utc,
            on_message_received=on_message_received,
            timeout=timeout,
        )
        for executor in executors
    ]

    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    future = asyncio.gather(*coroutines, loop=loop, return_exceptions=True)
    result = None

    try:
        print(on_start_string, flush=True)
        future.add_done_callback(lambda future: _stop_and_suppress_eloop(loop))
        result = loop.run_until_complete(future)
    except KeyboardInterrupt:
        print("Stopping event monitor...", flush=True)
        for t in asyncio.Task.all_tasks():
            t.cancel()
        loop.run_forever()
    finally:
        if result:
            errors = result[0]
            if errors and errors[0]:
                logger.debug(errors)
                raise RuntimeError(errors[0])


async def _initiate_event_monitor(
    executor: ExecutorData, enqueued_time_utc, on_message_received, timeout=0
):
    target = executor.target
    consumer_group = executor.consumer_group

    if not target.partitions:
        logger.debug("No Event Hub partitions found to listen on.")
        return

    coroutines = []

    async with uamqp.ConnectionAsync(
        target.hostname,
        sasl=target.auth,
        debug=DEBUG,
        container_id=_get_container_id(),
        properties=_get_conn_props(),
    ) as conn:
        for p in target.partitions:
            coroutines.append(
                _monitor_events(
                    target=target,
                    connection=conn,
                    partition=p,
                    consumer_group=consumer_group,
                    enqueued_time_utc=enqueued_time_utc,
                    on_message_received=on_message_received,
                    timeout=timeout,
                )
            )
        return await asyncio.gather(*coroutines, return_exceptions=True)


async def _monitor_events(
    target: Target,
    connection,
    partition,
    consumer_group,
    enqueued_time_utc,
    on_message_received,
    timeout=0,
):
    source = uamqp.address.Source(
        "amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
            target.hostname, target.path, consumer_group, partition
        )
    )
    source.set_filter(
        bytes(
            "amqp.annotation.x-opt-enqueuedtimeutc > " + str(enqueued_time_utc), "utf8"
        )
    )

    exp_cancelled = False
    receive_client = uamqp.ReceiveClientAsync(
        source,
        auth=target.auth,
        timeout=timeout,
        prefetch=0,
        client_name=_get_container_id(),
        debug=DEBUG,
    )

    try:
        if connection:
            await receive_client.open_async(connection=connection)

        async for msg in receive_client.receive_messages_iter_async():
            on_message_received(msg)

    except asyncio.CancelledError:
        exp_cancelled = True
        await receive_client.close_async()
    except uamqp.errors.LinkDetach as ld:
        if isinstance(ld.description, bytes):
            ld.description = str(ld.description, "utf8")
        raise RuntimeError(ld.description)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, closing monitor on partition %s", partition)
        exp_cancelled = True
        await receive_client.close_async()
        raise
    finally:
        if not exp_cancelled:
            await receive_client.close_async()
        logger.info("Closed monitor on partition %s", partition)


def _stop_and_suppress_eloop(loop):
    try:
        loop.stop()
    except Exception:
        pass


def _get_conn_props():
    return {
        "product": USER_AGENT,
        "version": VERSION,
        "framework": "Python {}.{}.{}".format(*sys.version_info[0:3]),
        "platform": sys.platform,
    }


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))


def generate_on_start_string(device_id, pnp_context):
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    return "Starting {}event monitor,{} use ctrl-c to stop...".format(
        "Digital Twin " if pnp_context else "",
        device_filter_txt if device_filter_txt else "",
    )
