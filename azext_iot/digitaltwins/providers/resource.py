# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers import (
    DigitalTwinsResourceManager,
    CloudError,
    ErrorResponseException,
)
from azext_iot.digitaltwins.providers.rbac import RbacProvider
from azext_iot.sdk.digitaltwins.controlplane.models import (
    EventGrid as EventGridEndpointProperties,
    EventHub as EventHubEndpointProperties,
    ServiceBus as ServiceBusEndpointProperties,
)
from azext_iot.common.utility import unpack_msrest_error
from knack.util import CLIError


class ResourceProvider(DigitalTwinsResourceManager):
    def __init__(self, cmd):
        super(ResourceProvider, self).__init__(cmd=cmd)
        self.mgmt_sdk = self.get_mgmt_sdk()
        self.rbac = RbacProvider()

    def create(self, name, resource_group_name, location=None, tags=None, timeout=60):

        if not location:
            from azext_iot.common.embedded_cli import EmbeddedCLI

            resource_group_meta = (
                EmbeddedCLI()
                .invoke("group show --name {}".format(resource_group_name))
                .as_json()
            )
            location = resource_group_meta["location"]

        try:
            return self.mgmt_sdk.digital_twins.create_or_update(
                resource_name=name,
                resource_group_name=resource_group_name,
                location=location,
                tags=tags,
                long_running_operation_timeout=timeout,
            )
        except CloudError as e:
            raise e
        except ErrorResponseException as err:
            raise CLIError(unpack_msrest_error(err))

    def list(self):
        try:
            return self.mgmt_sdk.digital_twins.list()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def list_by_resouce_group(self, resource_group_name):
        try:
            return self.mgmt_sdk.digital_twins.list_by_resource_group(
                resource_group_name=resource_group_name
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def get(self, name, resource_group_name):
        try:
            return self.mgmt_sdk.digital_twins.get(
                resource_name=name, resource_group_name=resource_group_name
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def find_instance(self, name, resource_group_name=None):
        if resource_group_name:
            try:
                return self.get(name=name, resource_group_name=resource_group_name)
            except ErrorResponseException as e:
                raise CLIError(unpack_msrest_error(e))

        dt_collection_pager = self.list()
        dt_collection = []
        try:
            while True:
                dt_collection.extend(dt_collection_pager.advance_page())
        except StopIteration:
            pass

        compare_name = name.lower()
        filter_result = [
            instance
            for instance in dt_collection
            if instance.name.lower() == compare_name
        ]

        if filter_result:
            if len(filter_result) > 1:
                raise CLIError(
                    "Ambiguous DT instance name. Please include the DT instance resource group."
                )
            return filter_result[0]

        raise CLIError(
            "DT instance: '{}' not found by auto-discovery. "
            "Provide resource group via -g for direct lookup.".format(name)
        )

    def get_rg(self, dt_instance):
        dt_scope = dt_instance.id
        split_decomp = dt_scope.split("/")
        res_g = split_decomp[4]
        return res_g

    def delete(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.digital_twins.delete(
                resource_name=name,
                resource_group_name=resource_group_name,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    # RBAC

    def get_role_assignments(
        self, name, include_inherited=False, role_type=None, resource_group_name=None
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        return self.rbac.list_assignments(
            dt_scope=target_instance.id,
            include_inherited=include_inherited,
            role_type=role_type,
        )

    def assign_role(self, name, role_type, assignee, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        return self.rbac.assign_role(
            dt_scope=target_instance.id, assignee=assignee, role_type=role_type
        )

    def remove_role(self, name, assignee, role_type=None, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        return self.rbac.remove_role(
            dt_scope=target_instance.id, assignee=assignee, role_type=role_type
        )

    # Endpoints

    def get_endpoint(self, name, endpoint_name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.digital_twins_endpoint.get(
                resource_name=target_instance.name,
                endpoint_name=endpoint_name,
                resource_group_name=resource_group_name,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def list_endpoints(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.digital_twins_endpoint.list(
                resource_name=target_instance.name,
                resource_group_name=resource_group_name,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    # TODO: Polling issue related to mismatched status codes.
    def delete_endpoint(self, name, endpoint_name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.digital_twins_endpoint.delete(
                resource_name=target_instance.name,
                endpoint_name=endpoint_name,
                resource_group_name=resource_group_name,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    # TODO: Breakout and refactor
    def add_endpoint(
        self,
        name,
        endpoint_name,
        endpoint_resource_type,
        endpoint_resource_name,
        endpoint_resource_group,
        endpoint_resource_policy=None,
        endpoint_resource_namespace=None,
        endpoint_subscription=None,
        dead_letter_endpoint=None,
        tags=None,
        resource_group_name=None,
        timeout=20,
    ):
        from azext_iot.common.embedded_cli import EmbeddedCLI
        from azext_iot.digitaltwins.common import ADTEndpointType

        requires_policy = [ADTEndpointType.eventhub, ADTEndpointType.servicebus]
        if endpoint_resource_type in requires_policy:
            if not endpoint_resource_policy:
                raise CLIError(
                    "Endpoint resources of type {} require a policy name.".format(
                        " or ".join(map(str, requires_policy))
                    )
                )

            if not endpoint_resource_namespace:
                raise CLIError(
                    "Endpoint resources of type {} require a namespace.".format(
                        " or ".join(map(str, requires_policy))
                    )
                )

        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        cli = EmbeddedCLI()
        error_prefix = "Could not create ADT instance endpoint. Unable to retrieve"

        properties = {}

        if endpoint_resource_type == ADTEndpointType.eventgridtopic:
            eg_topic_keys_op = cli.invoke(
                "eventgrid topic key list -n {} -g {}".format(
                    endpoint_resource_name, endpoint_resource_group
                ),
                subscription=endpoint_subscription,
            )
            if not eg_topic_keys_op.success():
                raise CLIError("{} Event Grid topic keys.".format(error_prefix))
            eg_topic_keys = eg_topic_keys_op.as_json()

            eg_topic_endpoint_op = cli.invoke(
                "eventgrid topic show -n {} -g {}".format(
                    endpoint_resource_name, endpoint_resource_group
                ),
                subscription=endpoint_subscription,
            )
            if not eg_topic_endpoint_op.success():
                raise CLIError("{} Event Grid topic endpoint.".format(error_prefix))
            eg_topic_endpoint = eg_topic_endpoint_op.as_json()

            properties = EventGridEndpointProperties(
                access_key1=eg_topic_keys["key1"],
                access_key2=eg_topic_keys["key2"],
                dead_letter_secret=dead_letter_endpoint,
                topic_endpoint=eg_topic_endpoint["endpoint"],
            )

        elif endpoint_resource_type == ADTEndpointType.servicebus:
            sb_topic_keys_op = cli.invoke(
                "servicebus topic authorization-rule keys list -n {} "
                "--namespace-name {} -g {} --topic-name {}".format(
                    endpoint_resource_policy,
                    endpoint_resource_namespace,
                    endpoint_resource_group,
                    endpoint_resource_name,
                ),
                subscription=endpoint_subscription,
            )
            if not sb_topic_keys_op.success():
                raise CLIError("{} Service Bus topic keys.".format(error_prefix))
            sb_topic_keys = sb_topic_keys_op.as_json()

            properties = ServiceBusEndpointProperties(
                primary_connection_string=sb_topic_keys["primaryConnectionString"],
                secondary_connection_string=sb_topic_keys["secondaryConnectionString"],
                dead_letter_secret=dead_letter_endpoint,
            )

        elif endpoint_resource_type == ADTEndpointType.eventhub:
            eventhub_topic_keys_op = cli.invoke(
                "eventhubs eventhub authorization-rule keys list -n {} "
                "--namespace-name {} -g {} --eventhub-name {}".format(
                    endpoint_resource_policy,
                    endpoint_resource_namespace,
                    endpoint_resource_group,
                    endpoint_resource_name,
                ),
                subscription=endpoint_subscription,
            )
            if not eventhub_topic_keys_op.success():
                raise CLIError("{} Event Hub keys.".format(error_prefix))
            eventhub_topic_keys = eventhub_topic_keys_op.as_json()

            properties = EventHubEndpointProperties(
                connection_string_primary_key=eventhub_topic_keys[
                    "primaryConnectionString"
                ],
                connection_string_secondary_key=eventhub_topic_keys[
                    "secondaryConnectionString"
                ],
                dead_letter_secret=dead_letter_endpoint,
            )

        try:
            return self.mgmt_sdk.digital_twins_endpoint.create_or_update(
                resource_name=target_instance.name,
                resource_group_name=resource_group_name,
                endpoint_name=endpoint_name,
                properties=properties,
                long_running_operation_timeout=timeout,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))
