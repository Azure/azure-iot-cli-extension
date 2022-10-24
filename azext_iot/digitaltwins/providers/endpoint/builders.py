# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import CLIInternalError
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.digitaltwins.common import ADTEndpointAuthType
from abc import ABC, abstractmethod
from knack.log import get_logger

from azext_iot.sdk.digitaltwins.controlplane.models import (
    ManagedIdentityReference,
    DigitalTwinsIdentityType,
    EventGrid as EventGridEndpointProperties,
    EventHub as EventHubEndpointProperties,
    ServiceBus as ServiceBusEndpointProperties,
)

logger = get_logger(__name__)


class BaseEndpointBuilder(ABC):
    def __init__(
        self,
        endpoint_resource_name: str,
        endpoint_resource_group: str,
        auth_type: str = ADTEndpointAuthType.keybased.value,
        dead_letter_secret: str = None,
        dead_letter_uri: str = None,
        endpoint_subscription: str = None,
        identity: str = None,
    ):
        self.cli = EmbeddedCLI()
        self.error_prefix = "Could not create ADT instance endpoint. Unable to retrieve"
        self.endpoint_resource_name = endpoint_resource_name
        self.endpoint_resource_group = endpoint_resource_group
        self.endpoint_subscription = endpoint_subscription
        self.auth_type = auth_type
        self.dead_letter_secret = dead_letter_secret
        self.dead_letter_uri = dead_letter_uri
        self.identity = identity

    def build_endpoint(self):
        endpoint_properties = (
            self.build_key_based()
            if self.auth_type == ADTEndpointAuthType.keybased.value
            else self.build_identity_based()
        )
        endpoint_properties.authentication_type = self.auth_type
        if self.identity == "[system]":
            endpoint_properties.identity = ManagedIdentityReference(
                type=DigitalTwinsIdentityType.system_assigned.value
            )
        elif self.identity:
            endpoint_properties.identity = ManagedIdentityReference(
                type=DigitalTwinsIdentityType.user_assigned.value, 
                user_assigned_identity= self.identity
            )

        return endpoint_properties

    @abstractmethod
    def build_key_based(self):
        pass

    @abstractmethod
    def build_identity_based(self):
        pass


class EventGridEndpointBuilder(BaseEndpointBuilder):
    def __init__(
        self,
        endpoint_resource_name,
        endpoint_resource_group,
        auth_type=ADTEndpointAuthType.keybased.value,
        dead_letter_secret=None,
        dead_letter_uri=None,
        endpoint_subscription=None,
        identity = None,
    ):
        super().__init__(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            identity=identity,
        )

    def build_key_based(self):
        eg_topic_keys_op = self.cli.invoke(
            "eventgrid topic key list -n {} -g {}".format(
                self.endpoint_resource_name, self.endpoint_resource_group
            ),
            subscription=self.endpoint_subscription,
        )
        if not eg_topic_keys_op.success():
            raise CLIInternalError("{} Event Grid topic keys.".format(self.error_prefix))
        eg_topic_keys = eg_topic_keys_op.as_json()

        eg_topic_endpoint_op = self.cli.invoke(
            "eventgrid topic show -n {} -g {}".format(
                self.endpoint_resource_name, self.endpoint_resource_group
            ),
            subscription=self.endpoint_subscription,
        )
        if not eg_topic_endpoint_op.success():
            raise CLIInternalError("{} Event Grid topic endpoint.".format(self.error_prefix))
        eg_topic_endpoint = eg_topic_endpoint_op.as_json()

        # TODO: Potentionally have shared attributes handled by build_endpoint()
        return EventGridEndpointProperties(
            access_key1=eg_topic_keys["key1"],
            access_key2=eg_topic_keys["key2"],
            dead_letter_secret=self.dead_letter_secret,
            dead_letter_uri=self.dead_letter_uri,
            topic_endpoint=eg_topic_endpoint["endpoint"],
        )

    def build_identity_based(self):
        raise CLIInternalError(
            "Identity based EventGrid endpoint creation is not yet supported. "
        )


class ServiceBusEndpointBuilder(BaseEndpointBuilder):
    def __init__(
        self,
        endpoint_resource_name,
        endpoint_resource_group,
        endpoint_resource_namespace,
        endpoint_resource_policy,
        auth_type=ADTEndpointAuthType.keybased.value,
        dead_letter_secret=None,
        dead_letter_uri=None,
        endpoint_subscription=None,
        identity = None,
    ):
        super().__init__(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            identity=identity,
        )
        self.endpoint_resource_namespace = endpoint_resource_namespace
        self.endpoint_resource_policy = endpoint_resource_policy

    def build_key_based(self):
        sb_topic_keys_op = self.cli.invoke(
            "servicebus topic authorization-rule keys list -n {} "
            "--namespace-name {} -g {} --topic-name {}".format(
                self.endpoint_resource_policy,
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
                self.endpoint_resource_name,
            ),
            subscription=self.endpoint_subscription,
        )
        if not sb_topic_keys_op.success():
            raise CLIInternalError("{} Service Bus topic keys.".format(self.error_prefix))
        sb_topic_keys = sb_topic_keys_op.as_json()

        return ServiceBusEndpointProperties(
            primary_connection_string=sb_topic_keys["primaryConnectionString"],
            secondary_connection_string=sb_topic_keys["secondaryConnectionString"],
            dead_letter_secret=self.dead_letter_secret,
            dead_letter_uri=self.dead_letter_uri,
        )

    def build_identity_based(self):
        sb_namespace_op = self.cli.invoke(
            "servicebus namespace show --name {} -g {}".format(
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
            ),
            subscription=self.endpoint_subscription,
        )
        if not sb_namespace_op.success():
            raise CLIInternalError("{} Service Bus Namespace.".format(self.error_prefix))
        sb_namespace_meta = sb_namespace_op.as_json()
        sb_endpoint = sb_namespace_meta["serviceBusEndpoint"]

        sb_topic_op = self.cli.invoke(
            "servicebus topic show --name {} --namespace {} -g {}".format(
                self.endpoint_resource_name,
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
            ),
            subscription=self.endpoint_subscription,
        )

        if not sb_topic_op.success():
            raise CLIInternalError("{} Service Bus Topic.".format(self.error_prefix))

        return ServiceBusEndpointProperties(
            endpoint_uri=transform_sb_hostname_to_schemauri(sb_endpoint),
            entity_path=self.endpoint_resource_name,
            dead_letter_secret=self.dead_letter_secret,
            dead_letter_uri=self.dead_letter_uri,
        )


class EventHubEndpointBuilder(BaseEndpointBuilder):
    def __init__(
        self,
        endpoint_resource_name,
        endpoint_resource_group,
        endpoint_resource_namespace,
        endpoint_resource_policy,
        auth_type=ADTEndpointAuthType.keybased.value,
        dead_letter_secret=None,
        dead_letter_uri=None,
        endpoint_subscription=None,
        identity = None,
    ):
        super().__init__(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            identity=identity,
        )
        self.endpoint_resource_namespace = endpoint_resource_namespace
        self.endpoint_resource_policy = endpoint_resource_policy

    def build_key_based(self):
        eventhub_topic_keys_op = self.cli.invoke(
            "eventhubs eventhub authorization-rule keys list -n {} "
            "--namespace-name {} -g {} --eventhub-name {}".format(
                self.endpoint_resource_policy,
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
                self.endpoint_resource_name,
            ),
            subscription=self.endpoint_subscription,
        )
        if not eventhub_topic_keys_op.success():
            raise CLIInternalError("{} Event Hub keys.".format(self.error_prefix))
        eventhub_topic_keys = eventhub_topic_keys_op.as_json()

        return EventHubEndpointProperties(
            connection_string_primary_key=eventhub_topic_keys[
                "primaryConnectionString"
            ],
            connection_string_secondary_key=eventhub_topic_keys[
                "secondaryConnectionString"
            ],
            dead_letter_secret=self.dead_letter_secret,
            dead_letter_uri=self.dead_letter_uri,
        )

    def build_identity_based(self):
        sb_namespace_op = self.cli.invoke(
            "eventhubs namespace show --name {} -g {}".format(
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
            ),
            subscription=self.endpoint_subscription,
        )
        if not sb_namespace_op.success():
            raise CLIInternalError("{} EventHub Namespace.".format(self.error_prefix))
        sb_namespace_meta = sb_namespace_op.as_json()
        sb_endpoint = sb_namespace_meta["serviceBusEndpoint"]

        sb_topic_op = self.cli.invoke(
            "eventhubs eventhub show --name {} --namespace {} -g {}".format(
                self.endpoint_resource_name,
                self.endpoint_resource_namespace,
                self.endpoint_resource_group,
            ),
            subscription=self.endpoint_subscription,
        )

        if not sb_topic_op.success():
            raise CLIInternalError("{} EventHub.".format(self.error_prefix))

        return EventHubEndpointProperties(
            endpoint_uri=transform_sb_hostname_to_schemauri(sb_endpoint),
            entity_path=self.endpoint_resource_name,
            dead_letter_secret=self.dead_letter_secret,
            dead_letter_uri=self.dead_letter_uri,
        )


def transform_sb_hostname_to_schemauri(endpoint):
    from urllib.parse import urlparse

    sb_endpoint_parts = urlparse(endpoint)
    sb_hostname = sb_endpoint_parts.hostname
    sb_schema_uri = "sb://{}/".format(sb_hostname)
    return sb_schema_uri


def build_endpoint(
    endpoint_resource_type: str,
    endpoint_resource_name: str,
    endpoint_resource_group: str,
    auth_type: str = ADTEndpointAuthType.keybased.value,
    endpoint_resource_namespace: str = None,
    endpoint_resource_policy: str = None,
    dead_letter_secret: str = None,
    dead_letter_uri: str = None,
    endpoint_subscription: str = None,
    identity: str = None,
):
    from azext_iot.digitaltwins.common import ADTEndpointType

    if endpoint_resource_type == ADTEndpointType.eventgridtopic.value:
        return EventGridEndpointBuilder(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            identity = identity,
        ).build_endpoint()

    if endpoint_resource_type == ADTEndpointType.servicebus.value:
        return ServiceBusEndpointBuilder(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            endpoint_resource_namespace=endpoint_resource_namespace,
            endpoint_resource_policy=endpoint_resource_policy,
            identity = identity,
        ).build_endpoint()

    if endpoint_resource_type == ADTEndpointType.eventhub.value:
        return EventHubEndpointBuilder(
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            endpoint_subscription=endpoint_subscription,
            endpoint_resource_namespace=endpoint_resource_namespace,
            endpoint_resource_policy=endpoint_resource_policy,
            identity = identity,
        ).build_endpoint()

    raise ValueError("{} not supported.".format(endpoint_resource_type))
