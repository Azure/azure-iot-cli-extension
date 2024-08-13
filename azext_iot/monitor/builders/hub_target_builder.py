# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import uamqp

from azure.cli.core.azclierror import CLIInternalError
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import parse_entity, unicode_binary_map, url_encode_str
from azext_iot.monitor.builders._common import query_meta_data
from azext_iot.monitor.models.target import Target

# To provide amqp frame trace
DEBUG = False


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

    def _build_auth_container(self, target):
        sas_uri = "sb://{}/{}".format(
            target["events"]["endpoint"], target["events"]["path"]
        )
        return uamqp.authentication.SASTokenAsync.from_shared_access_key(
            sas_uri, target["policy"], target["primarykey"]
        )

    async def _evaluate_redirect(self, endpoint):
        source = uamqp.address.Source(
            "amqps://{}/messages/events/$management".format(endpoint)
        )
        receive_client = uamqp.ReceiveClientAsync(
            source, timeout=30000, prefetch=1, debug=DEBUG
        )

        try:
            await receive_client.open_async()
            await receive_client.receive_message_batch_async(max_batch_size=1)
        except uamqp.errors.LinkRedirect as redirect:
            redirect = unicode_binary_map(parse_entity(redirect))
            result = {}
            result["events"] = {}
            result["events"]["endpoint"] = redirect["hostname"]
            result["events"]["path"] = (
                redirect["address"].replace("amqps://", "").split("/")[1]
            )
            result["events"]["address"] = redirect["address"]
            return redirect, result
        finally:
            await receive_client.close_async()

    async def _build_iot_hub_target_async(self, target):
        endpoint = AmqpBuilder.build_iothub_amqp_endpoint_from_target(target)
        _, update = await self._evaluate_redirect(endpoint)
        target["events"] = update["events"]
        endpoint = target["events"]["endpoint"]
        path = target["events"]["path"]
        auth = self._build_auth_container(target)
        meta_data = await query_meta_data(
            address=target["events"]["address"],
            path=target["events"]["path"],
            auth=auth,
        )
        partition_count = meta_data.get(b"partition_count")

        # if partition count is None or 0, throw
        if not partition_count or not int(partition_count):
            raise CLIInternalError(
                f"{target['entity'].split('.')[0]} has no partition count. Please contact a support "
                "representative to fix your IoT Hub."
            )

        partitions = [partition.decode("utf-8") for partition in meta_data.get(b"partition_ids", [])]
        if not partitions:
            for i in range(int(partition_count)):
                partitions.append(str(i))
            target["events"]["partition_ids"] = partitions
        auth = self._build_auth_container(target)

        return Target(hostname=endpoint, path=path, partitions=partitions, auth=auth)
