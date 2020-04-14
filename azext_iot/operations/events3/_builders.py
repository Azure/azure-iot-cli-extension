import asyncio
import uamqp

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import (parse_entity, unicode_binary_map, url_encode_str)

# To provide amqp frame trace
DEBUG = False


class AmqpBuilder():
    @classmethod
    def build_iothub_amqp_endpoint_from_target(cls, target, duration=360):
        hub_name = target['entity'].split('.')[0]
        user = "{}@sas.root.{}".format(target['policy'], hub_name)
        sas_token = SasTokenAuthentication(target['entity'], target['policy'],
                                           target['primarykey'], duration).generate_sas_token()
        return url_encode_str(user) + ":{}@{}".format(url_encode_str(sas_token), target['entity'])


class EventTargetBuilder():

    def __init__(self):
        self.eventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.eventLoop)

    def build_iot_hub_target(self, target):
        return self.eventLoop.run_until_complete(self._build_iot_hub_target_async(target))

    def build_central_event_hub_target(self, cmd, app_id, central_api_uri):
        return self.eventLoop.run_until_complete(self._build_central_event_hub_target_async(cmd, app_id, central_api_uri))

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

    async def _build_central_event_hub_target_async(self, cmd, app_id, central_api_uri):
        from azext_iot.common._azure import get_iot_central_tokens

        allTokens = get_iot_central_tokens(cmd, app_id, central_api_uri)
        targets = []
        # create target for each event hub
        for key in allTokens:
            tokens = allTokens[key]
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

            targets.append(eventHubTarget)

        return targets

    async def _build_iot_hub_target_async(self, target):
        if 'events' not in target:
            endpoint = AmqpBuilder.build_iothub_amqp_endpoint_from_target(target)
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
