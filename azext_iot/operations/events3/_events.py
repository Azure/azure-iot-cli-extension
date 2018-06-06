# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
from time import time
from uuid import uuid4
import sys

import uamqp
from uamqp.async import ConnectionAsync, SASTokenAsync
import six
import yaml

from knack.log import get_logger
from azext_iot._constants import VERSION
from azext_iot.common.utility import url_encode_str
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import unicode_binary_map, parse_entity


logger = get_logger(__name__)


def executor(target, consumer_group, enqueued_time, device_id=None, properties=None, timeout=0):
    coroutines = []
    partitions = target['events']['partition_ids']

    if not partitions:
        logger.debug('No Event Hub partitions found to listen on.')
        return

    # TODO: Create and use shared connection
    # conn = _create_async_connection(target)
    for p in partitions:
        coroutines.append(monitor_events(target, p,
                                         connection=None,
                                         consumer_group=consumer_group,
                                         enqueuedtimeutc=enqueued_time,
                                         properties=properties,
                                         device_id=device_id,
                                         timeout=timeout))

    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

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
        # TODO: Close shared connection
        # close_task = loop.create_task(_close_connection_async(conn))
        # loop.run_until_complete(close_task)
        loop.close()
        if result:
            error = next(res for res in result if result)
            if error:
                logger.debug('Error: ', error)


async def monitor_events(target, partition, connection, consumer_group, enqueuedtimeutc,
                         properties, device_id=None, timeout=0, debug=False):
    source = uamqp.address.Source("amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
        target['events']['endpoint'], target['events']['path'], consumer_group, partition))

    source.set_filter(
        bytes('amqp.annotation.x-opt-enqueuedtimeutc > ' + str(enqueuedtimeutc), 'utf8'))

    def _output_msg_kpi(msg):
        # TODO: Determine if amqp filters can support boolean operators for multiple conditions
        if device_id and msg.annotations[b'iothub-connection-device-id'] != device_id:
            return

        event_source = {'event': {}}

        event_source['event']['origin'] = str(msg.annotations.get(b'iothub-connection-device-id'), 'utf8')
        event_source['event']['payload'] = str(next(msg.get_data()), 'utf8')
        if 'anno' in properties or 'all' in properties:
            event_source['event']['annotations'] = unicode_binary_map(msg.annotations)
        if 'sys' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            event_source['event']['properties']['system'] = unicode_binary_map(parse_entity(msg.properties))
        if 'app' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            app_prop = msg.application_properties if msg.application_properties else None

            if app_prop:
                event_source['event']['properties']['application'] = unicode_binary_map(app_prop)

        six.print_(yaml.dump(event_source, default_flow_style=False), flush=True)

    exp_cancelled = False
    async_client = uamqp.ReceiveClientAsync(source, auth=_create_sas_auth(target), timeout=timeout, prefetch=0, debug=debug)

    if connection:
        await async_client.open_async(connection=connection)

    try:
        # Alternative to async iterator: Callback method
        # await async_client.receive_messages_async(_output_msg_kpi)
        async for msg in async_client.receive_messages_iter_async():
            _output_msg_kpi(msg)
    except asyncio.CancelledError:
        exp_cancelled = True
        await async_client.close_async()
    finally:
        if not exp_cancelled:
            await async_client.close_async()


def _create_async_connection(target, debug=False):
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
    sas_uri = 'sb://{}/{}'.format(target['events']['endpoint'], target['events']['path'])
    sas_auth = SASTokenAsync.from_shared_access_key(sas_uri, target['policy'], target['primarykey'])
    return sas_auth


async def _close_connection_async(connection):
    if connection:
        await connection.destroy_async()


def send_c2d_message(target, device_id, data, properties=None,
                     correlation_id=None, ack=None):
    app_props = {}
    if properties:
        app_props.update(properties)

    app_props['iothub-ack'] = (ack if ack else 'none')

    msg_props = uamqp.message.MessageProperties()
    msg_props.to = '/devices/{}/messages/devicebound'.format(device_id)
    msg_props.message_id = str(uuid4())

    if correlation_id:
        msg_props.correlation_id = correlation_id

    msg_content = str.encode(data)

    message = uamqp.Message(msg_content, properties=msg_props, application_properties=app_props)

    operation = '/messages/devicebound'
    endpoint = _build_iothub_amqp_endpoint_from_target(target)
    endpoint = endpoint + operation
    client = uamqp.SendClient('amqps://' + endpoint)
    client.send_message(message)
    client.close()


def _build_iothub_amqp_endpoint_from_target(target):
    hub_name = target['entity'].split('.')[0]
    endpoint = "{}@sas.root.{}".format(target['policy'], hub_name)
    endpoint = url_encode_str(endpoint)
    sas_token = SasTokenAuthentication(target['entity'], target['policy'],
                                       target['primarykey'], time() + 360).generate_sas_token()
    endpoint = endpoint + ":{}@{}".format(url_encode_str(sas_token), target['entity'])

    return endpoint
