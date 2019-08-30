import asyncio
import uamqp
from time import time

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import (parse_entity, unicode_binary_map, url_encode_str)

DEBUG = True

class EventTargetBuilder():

    def buildIotHubTargetSync(self, target):
        eventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(eventLoop)

        hubTarget = eventLoop.run_until_complete(self._buildIotHubTargetAsync(target))
        return hubTarget


    def buildCentralEventHubTarget(self, cmd, app_id, aad_token):
        eventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(eventLoop)

        centralTarget = eventLoop.run_until_complete(self._buildCentralEventHubTargetAsync(cmd, app_id, aad_token))
        return centralTarget


    def _build_auth_container(self, target):
        sas_uri = 'sb://{}/{}'.format(target['events']['endpoint'], target['events']['path'])
        return uamqp.authentication.SASTokenAsync.from_shared_access_key(sas_uri, target['policy'], target['primarykey'])


    def _build_auth_container_from_token(self, endpoint, path, token, tokenExpiry):
        sas_uri = 'sb://{}/{}'.format(endpoint, path)
        return uamqp.authentication.SASTokenAsync(audience=sas_uri, uri=sas_uri, expires_at=tokenExpiry, token=token)


    async def _query_meta_data(self, endpoint, path, auth):
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


    async def _evaluate_redirect(self, endpoint):
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


    async def _buildCentralEventHubTargetAsync(self, cmd, app_id, aad_token):
        from azext_iot.common._azure import get_iot_central_tokens

        tokens = get_iot_central_tokens(cmd, app_id, aad_token)
        eventHubToken = tokens['eventhubSasToken']
        hostnameWithoutPrefix = eventHubToken['hostname'].split("/")[2]
        endpoint = hostnameWithoutPrefix
        path = eventHubToken["entityPath"]
        tokenExpiry = tokens['expiry']
        auth = self._build_auth_container_from_token(endpoint, path, eventHubToken['sasToken'], tokenExpiry)
        address = "amqps://{}/{}/$management".format(hostnameWithoutPrefix, eventHubToken["entityPath"])
        meta_data = await self._query_meta_data(address, path, auth)
        partition_count = meta_data[b'partition_count']
        partition_ids = []
        for i in range(int(partition_count)):
            partition_ids.append(str(i))
        partitions = partition_ids
        auth = self._build_auth_container_from_token(endpoint, path, eventHubToken['sasToken'], tokenExpiry)

        eventHubTarget = {
            'endpoint': endpoint,
            'path': path,
            'auth': auth,
            'partitions': partitions
        }

        return eventHubTarget


    # TODO: This is both here and in _events
    def _build_iothub_amqp_endpoint_from_target(self, target, duration=360):
        hub_name = target['entity'].split('.')[0]
        user = "{}@sas.root.{}".format(target['policy'], hub_name)
        sas_token = SasTokenAuthentication(target['entity'], target['policy'],
                                        target['primarykey'], time() + duration).generate_sas_token()
        return url_encode_str(user) + ":{}@{}".format(url_encode_str(sas_token), target['entity'])


    async def _buildIotHubTargetAsync(self, target):
        if 'events' not in target:
            endpoint = self._build_iothub_amqp_endpoint_from_target(target)
            _, update = await self._evaluate_redirect(endpoint)
            target['events'] = update['events']
            endpoint = target['events']['endpoint']
            path = target['events']['path']
            auth = self._build_auth_container(target)
            meta_data = await self._query_meta_data(target['events']['address'], target['events']['path'], auth)
            partition_count = meta_data[b'partition_count']
            partition_ids = []
            for i in range(int(partition_count)):
                partition_ids.append(str(i))
            target['events']['partition_ids'] = partition_ids
        else:
            endpoint = target['events']['endpoint']
            path = target['events']['path']
        partitions = target['events']['partition_ids']
        auth = self._build_auth_container(target)

        eventHubTarget = {
            'endpoint': endpoint,
            'path': path,
            'auth': auth,
            'partitions': partitions
        }

        return eventHubTarget
