# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import sys
import six
from knack.log import get_logger
from azext_iot._constants import VERSION


logger = get_logger(__name__)


def executor(target, consumer_group, enqueued_time, device_id=None, properties=None, timeout=0):

    coroutines = []
    partitions = target['events']['partition_ids']

    if not partitions:
        logger.debug('No Event Hub partitions found to listen on.')
        return

    # TODO: Shared connection having issues.
    # conn = create_connection_async(target)
    for p in partitions:
        coroutines.append(monitor_events(target, p,
                                         consumer_group=consumer_group,
                                         enqueuedtimeutc=enqueued_time,
                                         properties=properties,
                                         device_id=device_id,
                                         timeout=timeout))

    loop = asyncio.get_event_loop()
    future = asyncio.gather(*coroutines, loop=loop, return_exceptions=True)
    result = None
    try:
        device_filter_txt = None
        if device_id:
            device_filter_txt = ' filtering on device: {},'.format(device_id)

        six.print_('Starting event monitor,{} use ctrl-c to stop...'.format(device_filter_txt if device_filter_txt else ''))
        future.add_done_callback(lambda future: loop.stop())
        result = loop.run_until_complete(future)
    except KeyboardInterrupt:
        six.print_('Stopping event monitor...')
        future.cancel()
        loop.run_forever()
    finally:
        # TODO: Shared connection having issues.
        # close_task = loop.create_task(close_connection_async(conn))
        # loop.run_until_complete(close_task)
        loop.close()
        if result:
            error = next(res for res in result if result)
            if error:
                six.print_('Error: ', error)


async def monitor_events(target, partition, consumer_group, enqueuedtimeutc,
                         properties, device_id=None, timeout=0, debug=False):
    import uamqp
    import yaml
    from azext_iot.common.utility import unicode_binary_map, parse_entity

    source = uamqp.address.Source("amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
        target['events']['endpoint'], target['events']['path'], consumer_group, partition))

    source.set_filter(
        bytes('amqp.annotation.x-opt-enqueuedtimeutc > ' + str(enqueuedtimeutc), 'utf8'))

    def _output_msg_kpi(msg):
        # TODO: Determine if amqp filters can support boolean operators for multiple conditions
        if device_id and msg.message_annotations[b'iothub-connection-device-id'] != device_id:
            return

        event_source = {'event': {}}
        event_source['event']['origin'] = msg.message_annotations.get(b'iothub-connection-device-id')
        event_source['event']['payload'] = str(next(msg.get_data()), 'utf8')
        if 'anno' in properties or 'all' in properties:
            event_source['event']['annotations'] = unicode_binary_map(msg.message_annotations)
        if 'sys' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            event_source['event']['properties']['system'] = parse_entity(msg.properties)
        if 'app' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            app_prop = None
            msg_handle = msg.get_message()
            app_prop = msg_handle.application_properties.value.value
            del msg_handle
            if app_prop:
                event_source['event']['properties']['application'] = app_prop

        six.print_(yaml.dump(event_source, default_flow_style=False), flush=True)

    exp_cancelled = False
    async_client = uamqp.ReceiveClientAsync(source, auth=_create_sas_auth(target), timeout=timeout, prefetch=0, debug=debug)

    try:
        # await async_client.open_async(connection=connection)
        # Callback method
        # await async_client.receive_messages_async(_output_msg_kpi)
        async for msg in async_client.receive_messages_iter_async():
            _output_msg_kpi(msg)
    except asyncio.CancelledError:
        exp_cancelled = True
        await async_client.close_async()
    finally:
        if not exp_cancelled:
            await async_client.close_async()


def create_connection_async(target, debug=False):
    from uuid import uuid4
    from uamqp.async import ConnectionAsync

    def _create_properties():
        properties = {}
        properties["product"] = "az.cli.iot.extension"
        properties["version"] = VERSION
        properties["framework"] = "Python {}.{}.{}".format(*sys.version_info[0:3])
        properties["platform"] = sys.platform
        return properties

    sas_auth = _create_sas_auth(target)

    return ConnectionAsync(target['events']['endpoint'], sas_auth,
                           container_id=str(uuid4()), properties=_create_properties(),
                           debug=debug)


def _create_sas_auth(target):
    from uamqp.async import SASTokenAsync

    sas_uri = 'sb://{}/{}'.format(target['events']['endpoint'], target['events']['path'])
    sas_auth = SASTokenAsync.from_shared_access_key(sas_uri, target['policy'], target['primarykey'])
    return sas_auth


async def close_connection_async(connection):
    if connection:
        await connection.destroy_async()
