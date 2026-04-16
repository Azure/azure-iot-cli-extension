# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio

from azure.cli.core.azclierror import CLIInternalError
from azure.eventhub import TransportType
from azure.eventhub.aio import EventHubConsumerClient
from knack.log import get_logger
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import url_encode_str, is_eventhub_connection_string
from azext_iot.monitor.models.enum import Transport
from azext_iot.monitor.models.target import Target
from azext_iot.monitor.utility import get_http_proxy_settings

logger = get_logger(__name__)


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

    def build_iot_hub_target(self, target, transport=None):
        return self.eventLoop.run_until_complete(
            self._build_iot_hub_target_async(target, transport=transport)
        )

    async def _build_iot_hub_target_async(self, target, transport=None):
        cs = target.get("cs", "")
        # If the connection string is an Event Hub connection string (e.g. from IoT Hub's
        # built-in endpoint in the Azure portal), skip the AMQP redirect and connect
        # directly.  This also ensures proxy settings are applied correctly.
        if is_eventhub_connection_string(cs):
            return await self._build_from_eh_connection_string(cs, transport=transport)

        # If events metadata not provided, attempt to discover it via AMQP redirect
        if "events" not in target:
            event_info = await self._evaluate_redirect(target)
            if event_info:
                target["events"] = event_info
            else:
                raise CLIInternalError(
                    f"Unable to discover Event Hub endpoint for '{target['entity']}'. "
                    "Ensure the IoT Hub connection string is valid or provide hub name with "
                    "--hub-name to use Azure Resource Manager discovery."
                )

        endpoint = target["events"]["endpoint"]
        path = target["events"]["path"]
        partition_ids = target["events"].get("partition_ids", [])
        partition_count = target["events"].get("partition_count", 0)

        # Store policy and key for credential generation at usage time
        policy = target["policy"]
        key = target["primarykey"]

        if partition_ids:
            return Target(
                hostname=endpoint, path=path, partitions=partition_ids,
                policy=policy, key=key
            )
        if partition_count:
            for i in range(int(partition_count)):
                partition_ids.append(str(i))
            return Target(
                hostname=endpoint, path=path, partitions=partition_ids,
                policy=policy, key=key
            )

        # Query partition metadata using azure-eventhub
        connection_str = (
            f"Endpoint=sb://{endpoint}/;"
            f"SharedAccessKeyName={policy};"
            f"SharedAccessKey={key};"
            f"EntityPath={path}"
        )
        create_kwargs = {
            "consumer_group": "$Default",
            "eventhub_name": path,
        }
        proxy_settings = get_http_proxy_settings()
        if transport == Transport.AMQP_WS or proxy_settings:
            create_kwargs["transport_type"] = TransportType.AmqpOverWebsocket
        if proxy_settings:
            create_kwargs["http_proxy"] = proxy_settings

        client = EventHubConsumerClient.from_connection_string(
            connection_str,
            **create_kwargs,
        )

        try:
            async with client:
                amqp_partition_ids = await client.get_partition_ids()
                return Target(
                    hostname=endpoint,
                    path=path,
                    partitions=list(amqp_partition_ids),
                    policy=policy,
                    key=key
                )
        except Exception as e:
            raise CLIInternalError(
                f"Unable to query partitions for '{target['entity'].split('.')[0]}': {e}"
            )

    async def _build_from_eh_connection_string(self, cs: str, transport=None) -> Target:
        """Build a Target directly from an Event Hub connection string.

        Parses and connects to the Event Hub endpoint described by *cs*, applying
        any configured HTTP proxy.  Used when the caller supplies an EH connection
        string (e.g. from IoT Hub's built-in endpoint in the Azure portal) so that
        the AMQP link-redirect step can be skipped entirely.
        """
        from azext_iot.common._azure import parse_event_hub_connection_string
        parsed = parse_event_hub_connection_string(cs)
        endpoint_raw = parsed.get("Endpoint", "")
        for prefix in ("sb://", "amqps://"):
            if endpoint_raw.lower().startswith(prefix):
                endpoint_raw = endpoint_raw[len(prefix):]
                break
        hostname = endpoint_raw.rstrip("/")
        entity_path = parsed["EntityPath"]
        sas_key_name = parsed["SharedAccessKeyName"]
        sas_key = parsed["SharedAccessKey"]

        create_kwargs = {
            "consumer_group": "$Default",
        }
        proxy_settings = get_http_proxy_settings()
        if transport == Transport.AMQP_WS or proxy_settings:
            create_kwargs["transport_type"] = TransportType.AmqpOverWebsocket
        if proxy_settings:
            create_kwargs["http_proxy"] = proxy_settings

        client = EventHubConsumerClient.from_connection_string(cs, **create_kwargs)
        try:
            async with client:
                partition_ids = await client.get_partition_ids()
                return Target(
                    hostname=hostname,
                    path=entity_path,
                    partitions=list(partition_ids),
                    policy=sas_key_name,
                    key=sas_key,
                )
        except Exception as e:
            raise CLIInternalError(
                f"Unable to query partitions from Event Hub endpoint '{hostname}': {e}"
            )

    async def _evaluate_redirect(self, target):
        """
        Discover Event Hub endpoint using AMQP link redirect.
        This allows discovery with just a connection string, without Azure login.

        When connecting to IoT Hub's management endpoint, it redirects to the
        Event Hub-compatible endpoint, revealing the actual endpoint and path.
        """
        def _sync_redirect():
            try:
                from azure.eventhub._pyamqp import ReceiveClient as PyAMQPReceiveClient
                from azure.eventhub._pyamqp.error import AMQPLinkRedirect
                from azure.eventhub._pyamqp.authentication import _CBSAuth as PyAMQPCBSAuth
                from azext_iot.common.sas_token_auth import SasTokenAuthentication
                from time import time
                from collections import namedtuple

                AccessToken = namedtuple("AccessToken", ["token", "expires_on"])

                hostname = target["entity"]
                policy = target["policy"]
                key = target["primarykey"]
                token_duration = 360

                # Generate IoT Hub-compatible SAS token
                sas_generator = SasTokenAuthentication(
                    uri=hostname,
                    shared_access_policy_name=policy,
                    shared_access_key=key,
                    expiry=token_duration
                )

                def sas_token_provider():
                    token = sas_generator.generate_sas_token()
                    return AccessToken(token, time() + token_duration)

                # Management endpoint to trigger redirect
                source = f"amqps://{hostname}/messages/events/$management"

                # Use CBS authentication
                auth = PyAMQPCBSAuth(
                    uri=source,
                    audience=hostname,
                    token_type=b"servicebus.windows.net:sastoken",
                    get_token=sas_token_provider,
                    expires_in=token_duration
                )

                client = PyAMQPReceiveClient(
                    hostname=hostname,
                    source=source,
                    auth=auth,
                    network_trace=False,
                    timeout=30000,
                    prefetch=1
                )

                result = None
                try:
                    client.open()
                    # Try to receive - this will trigger link redirect from IoT Hub
                    client.receive_message_batch(max_batch_size=1, timeout=5000)
                except AMQPLinkRedirect as redirect:
                    # Extract redirect information
                    if redirect.info:
                        hostname_redirect = redirect.info.get(b"hostname") or redirect.info.get("hostname")
                        address_redirect = redirect.info.get(b"address") or redirect.info.get("address")

                        if isinstance(hostname_redirect, bytes):
                            hostname_redirect = hostname_redirect.decode("utf-8")
                        if isinstance(address_redirect, bytes):
                            address_redirect = address_redirect.decode("utf-8")

                        if hostname_redirect and address_redirect:
                            # Parse address to extract path
                            # Address format: "amqps://hostname:port/path/$management"
                            path = (
                                address_redirect.replace("amqps://", "").split("/", 1)[1]
                                if "/" in address_redirect
                                else address_redirect
                            )
                            # Remove port and $management suffix
                            if ":" in path:
                                path = path.split("/", 1)[1] if "/" in path else path
                            if path.endswith("/$management"):
                                path = path.replace("/$management", "")

                            result = {
                                "endpoint": hostname_redirect,
                                "path": path
                            }
                except Exception as e:
                    logger.debug(f"AMQP redirect receive failed: {e}")
                finally:
                    try:
                        client.close()
                    except Exception as e:
                        logger.debug("Failed to close AMQP client during cleanup: %s", e)

                return result

            except Exception as e:
                # If AMQP redirect discovery fails, return None to try ARM API fallback
                logger.debug(f"AMQP link redirect discovery failed: {e}")

            return None

        # Run the synchronous redirect logic in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_redirect)
