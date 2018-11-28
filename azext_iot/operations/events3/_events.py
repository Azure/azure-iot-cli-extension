# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import json
import re
import sys
from time import time
from uuid import uuid4

import six

import uamqp
import yaml
from azext_iot._constants import VERSION
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import (parse_entity, unicode_binary_map,
                                      url_encode_str)
from knack.log import get_logger

logger = get_logger(__name__)

DEBUG = True


def executor(target, consumer_group, enqueued_time, device_id=None, properties=None, timeout=0, output=None, content_type=None,
             device_regex=None):
    coroutines = []
    coroutines.append(initiate_event_monitor(target, consumer_group, enqueued_time, device_id, properties,
                                             timeout, output, content_type, device_regex))
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

        def stop_and_suppress_eloop():
            try:
                loop.stop()
            except Exception:  # pylint: disable=broad-except
                pass

        six.print_('Starting event monitor,{} use ctrl-c to stop...'.format(device_filter_txt if device_filter_txt else ''))
        future.add_done_callback(lambda future: stop_and_suppress_eloop())
        result = loop.run_until_complete(future)
    except KeyboardInterrupt:
        six.print_('Stopping event monitor...')
        for t in asyncio.Task.all_tasks():
            t.cancel()
        loop.run_forever()
    finally:
        if result:
            error = next(res for res in result if result)
            if error:
                logger.error(error)
                raise RuntimeError(error)


async def initiate_event_monitor(target, consumer_group, enqueued_time, device_id=None, properties=None,
                                 timeout=0, output=None, content_type=None, device_regex=None):
    def _get_conn_props():
        properties = {}
        properties["product"] = "az.cli.iot.extension"
        properties["version"] = VERSION
        properties["framework"] = "Python {}.{}.{}".format(*sys.version_info[0:3])
        properties["platform"] = sys.platform
        return properties

    if not target.get('events'):
        endpoint = _build_iothub_amqp_endpoint_from_target(target)
        _, update = await evaluate_redirect(endpoint)
        target['events'] = update['events']
        auth = _build_auth_container(target)
        meta_data = await query_meta_data(target['events']['address'], target['events']['path'], auth)
        partition_count = meta_data[b'partition_count']
        partition_ids = []
        for i in range(int(partition_count)):
            partition_ids.append(str(i))
        target['events']['partition_ids'] = partition_ids

    partitions = target['events']['partition_ids']

    if not partitions:
        logger.debug('No Event Hub partitions found to listen on.')
        return

    coroutines = []

    auth = _build_auth_container(target)
    async with uamqp.ConnectionAsync(target['events']['endpoint'], sasl=auth,
                                     debug=DEBUG, container_id=str(uuid4()), properties=_get_conn_props()) as conn:
        for p in partitions:
            coroutines.append(monitor_events(endpoint=target['events']['endpoint'],
                                             connection=conn,
                                             path=target['events']['path'],
                                             auth=auth,
                                             partition=p,
                                             consumer_group=consumer_group,
                                             enqueuedtimeutc=enqueued_time,
                                             properties=properties,
                                             device_id=device_id,
                                             timeout=timeout,
                                             output=output,
                                             content_type=content_type,
                                             device_regex=device_regex))
        await asyncio.gather(*coroutines, return_exceptions=True)


# pylint: disable=too-many-statements
async def monitor_events(endpoint, connection, path, auth, partition, consumer_group, enqueuedtimeutc,
                         properties, device_id=None, timeout=0, output=None, content_type=None, device_regex=None):
    source = uamqp.address.Source('amqps://{}/{}/ConsumerGroups/{}/Partitions/{}'.format(endpoint, path,
                                                                                         consumer_group, partition))
    source.set_filter(
        bytes('amqp.annotation.x-opt-enqueuedtimeutc > ' + str(enqueuedtimeutc), 'utf8'))

    def _output_msg_kpi(msg):
        # TODO: Determine if amqp filters can support boolean operators for multiple conditions
        origin = str(msg.annotations.get(b'iothub-connection-device-id'), 'utf8')
        if (device_id and origin != device_id) or (device_regex and not re.match(device_regex, origin)):
            return

        event_source = {'event': {}}

        event_source['event']['origin'] = origin

        payload = ''

        data = msg.get_data()
        if data:
            payload = str(next(data), 'utf8')

        system_props = unicode_binary_map(parse_entity(msg.properties, True))

        ct = content_type
        if not ct:
            ct = system_props['content_type'] if 'content_type' in system_props else ''

        if ct and ct.lower() == 'application/json':
            try:
                payload = json.loads(re.compile(r'(\\r\\n)+|\\r+|\\n+').sub('', payload))
            except Exception:  # pylint: disable=broad-except
                # We don't want to crash the monitor if JSON parsing fails
                pass

        event_source['event']['payload'] = payload

        if 'anno' in properties or 'all' in properties:
            event_source['event']['annotations'] = unicode_binary_map(msg.annotations)
        if 'sys' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            event_source['event']['properties']['system'] = system_props
        if 'app' in properties or 'all' in properties:
            if not event_source['event'].get('properties'):
                event_source['event']['properties'] = {}
            app_prop = msg.application_properties if msg.application_properties else None

            if app_prop:
                event_source['event']['properties']['application'] = unicode_binary_map(app_prop)

        if output.lower() == 'json':
            dump = json.dumps(event_source, indent=4)
        else:
            dump = yaml.safe_dump(event_source, default_flow_style=False)

        six.print_(dump, flush=True)

    exp_cancelled = False
    receive_client = uamqp.ReceiveClientAsync(source, auth=auth, timeout=timeout, prefetch=0, debug=DEBUG)

    try:
        if connection:
            await receive_client.open_async(connection=connection)

        async for msg in receive_client.receive_messages_iter_async():
            _output_msg_kpi(msg)

    except asyncio.CancelledError:
        exp_cancelled = True
        await receive_client.close_async()
    except uamqp.errors.LinkDetach as ld:
        if isinstance(ld.description, bytes):
            ld.description = str(ld.description, 'utf8')
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


def _build_auth_container(target):
    sas_uri = 'sb://{}/{}'.format(target['events']['endpoint'], target['events']['path'])
    return uamqp.authentication.SASTokenAsync.from_shared_access_key(sas_uri, target['policy'], target['primarykey'])


async def evaluate_redirect(endpoint):
    source = uamqp.address.Source('amqps://{}/messages/events/$management'.format(endpoint))
    receive_client = uamqp.ReceiveClientAsync(source, timeout=30000, prefetch=1, debug=DEBUG)

    try:
        await receive_client.open_async()
        await receive_client.receive_message_batch_async(max_batch_size=1)
    except uamqp.errors.LinkRedirect as redirect:
        redirect = unicode_binary_map(parse_entity(redirect))
        result = {}
        result['events'] = {}
        result['events']['endpoint'] = redirect['hostname']
        result['events']['path'] = redirect['address'].replace('amqps://', '').split('/')[1]
        result['events']['address'] = redirect['address']
        return redirect, result
    finally:
        await receive_client.close_async()


async def query_meta_data(endpoint, path, auth):
    source = uamqp.address.Source(endpoint)
    receive_client = uamqp.ReceiveClientAsync(source, auth=auth, timeout=30000, debug=DEBUG)
    try:
        await receive_client.open_async()
        message = uamqp.Message(application_properties={'name': path})

        response = await receive_client.mgmt_request_async(
            message,
            b'READ',
            op_type=b'com.microsoft:eventhub',
            status_code_field=b'status-code',
            description_fields=b'status-description',
            timeout=30000
        )
        test = response.get_data()
        return test
    finally:
        await receive_client.close_async()


def send_c2d_message(target, device_id, data, properties=None,
                     correlation_id=None, ack=None):
    app_props = {}
    if properties:
        app_props.update(properties)

    app_props['iothub-ack'] = (ack if ack else 'none')

    msg_props = uamqp.message.MessageProperties()
    msg_props.to = '/devices/{}/messages/devicebound'.format(device_id)
    msg_id = str(uuid4())
    msg_props.message_id = msg_id

    if correlation_id:
        msg_props.correlation_id = correlation_id

    msg_content = str.encode(data)

    message = uamqp.Message(msg_content, properties=msg_props, application_properties=app_props)

    operation = '/messages/devicebound'
    endpoint = _build_iothub_amqp_endpoint_from_target(target)
    endpoint = endpoint + operation
    client = uamqp.SendClient('amqps://' + endpoint, debug=DEBUG)
    client.queue_message(message)
    result = client.send_all_messages()
    errors = [m for m in result if m == uamqp.constants.MessageState.SendFailed]
    return msg_id, errors


def _build_iothub_amqp_endpoint_from_target(target, duration=360):
    hub_name = target['entity'].split('.')[0]
    user = "{}@sas.root.{}".format(target['policy'], hub_name)
    sas_token = SasTokenAuthentication(target['entity'], target['policy'],
                                       target['primarykey'], time() + duration).generate_sas_token()
    return url_encode_str(user) + ":{}@{}".format(url_encode_str(sas_token), target['entity'])


def monitor_feedback(target, device_id, wait_on_id=None, token_duration=3600):

    def handle_msg(msg):
        payload = next(msg.get_data())
        if isinstance(payload, bytes):
            payload = str(payload, 'utf8')
        # assume json [] based on spec
        payload = json.loads(payload)
        for p in payload:
            if device_id and p.get('deviceId') and p['deviceId'].lower() != device_id.lower():
                return None
            six.print_(yaml.dump({'feedback': p}, default_flow_style=False), flush=True)
            if wait_on_id:
                msg_id = p['originalMessageId']
                if msg_id == wait_on_id:
                    return msg_id
        return None

    operation = '/messages/servicebound/feedback'
    endpoint = _build_iothub_amqp_endpoint_from_target(target, duration=token_duration)
    endpoint = endpoint + operation

    device_filter_txt = None
    if device_id:
        device_filter_txt = ' filtering on device: {},'.format(device_id)

    six.print_('Starting C2D feedback monitor,{} use ctrl-c to stop...'.format(device_filter_txt if device_filter_txt else ''))

    try:
        client = uamqp.ReceiveClient('amqps://' + endpoint, debug=DEBUG)
        message_generator = client.receive_messages_iter()
        for msg in message_generator:
            match = handle_msg(msg)
            if match:
                logger.info('requested msg id has been matched...')
                msg.accept()
                return match
    except uamqp.errors.AMQPConnectionError:
        logger.debug('amqp connection has expired...')
    finally:
        client.close()
