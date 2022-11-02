# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    MutuallyExclusiveArgumentError
)
from azext_iot.digitaltwins.common import (
    DEFAULT_CONSUMER_GROUP,
    MAX_ADT_DH_CREATE_RETRIES,
    ADTEndpointAuthType,
    ADTPublicNetworkAccessType,
    MAX_ADT_CREATE_RETRIES,
    IdentityType,
)
from azext_iot.digitaltwins.providers import (
    DigitalTwinsResourceManager,
    CloudError,
    ErrorResponseException,
)
from azext_iot.digitaltwins.providers.generic import generic_check_state
from azext_iot.digitaltwins.providers.rbac import RbacProvider
from azext_iot.sdk.digitaltwins.controlplane.models import (
    DigitalTwinsDescription,
)
from azext_iot.common.utility import (
    handle_service_exception
)
from knack.log import get_logger

from azext_iot.sdk.digitaltwins.controlplane.models import DigitalTwinsIdentity

logger = get_logger(__name__)


class ResourceProvider(DigitalTwinsResourceManager):
    def __init__(self, cmd):
        super(ResourceProvider, self).__init__(cmd=cmd)
        self.mgmt_sdk = self.get_mgmt_sdk()
        self.rbac = RbacProvider(cmd.cli_ctx)

    def create(
        self,
        name,
        resource_group_name,
        location=None,
        tags=None,
        timeout=60,
        assign_identity=None,
        scopes=None,
        role_type="Contributor",
        public_network_access=ADTPublicNetworkAccessType.enabled.value,
        system_identity=None,
        user_identities=None
    ):
        if not location:
            from azext_iot.common.embedded_cli import EmbeddedCLI
            resource_group_meta = (
                EmbeddedCLI(cli_ctx=self.cmd.cli_ctx)
                .invoke("group show --name {}".format(resource_group_name))
                .as_json()
            )
            location = resource_group_meta["location"]

        try:
            # Temporary make the deprecated assign_identity param work for now
            if assign_identity and not system_identity:
                system_identity = assign_identity

            if system_identity:
                if scopes and not role_type:
                    raise RequiredArgumentMissingError(
                        "Both --scopes and --role values are required when assigning the instance identity."
                    )

            identity = {"type": IdentityType.none.value}
            if system_identity and user_identities:
                identity["type"] = IdentityType.system_assigned_user_assigned.value
            elif user_identities:
                identity["type"] = IdentityType.user_assigned.value
            elif system_identity:
                identity["type"] = IdentityType.system_assigned.value

            if user_identities:
                identity["userAssignedIdentities"] = {}
                for user_identity in user_identities:
                    identity["userAssignedIdentities"][user_identity] = {}

            digital_twins_create = DigitalTwinsDescription(
                location=location,
                tags=tags,
                identity=identity,
                public_network_access=public_network_access,
            )
            create_or_update = self.mgmt_sdk.digital_twins.create_or_update(
                resource_name=name,
                resource_group_name=resource_group_name,
                digital_twins_create=digital_twins_create,
                long_running_operation_timeout=timeout,
            )

            def check_state(lro):
                generic_check_state(
                    lro=lro,
                    show_cmd=f"az dt show -n {name} -g {resource_group_name}",
                    max_retries=MAX_ADT_CREATE_RETRIES
                )

            def rbac_handler(lro):
                instance = lro.resource().as_dict()
                identity = instance.get("identity")
                if identity:
                    identity_type = identity.get("type")
                    principal_id = identity.get("principal_id")

                    if (
                        principal_id
                        and scopes
                        and identity_type
                        and identity_type.lower() == "systemassigned"
                    ):
                        for scope in scopes:
                            logger.info(
                                "Applying rbac assignment: Principal Id: {}, Scope: {}, Role: {}".format(
                                    principal_id, scope, role_type
                                )
                            )
                            self.rbac.assign_role_flex(
                                principal_id=principal_id,
                                scope=scope,
                                role_type=role_type,
                            )

            create_or_update.add_done_callback(check_state)
            create_or_update.add_done_callback(rbac_handler)
            return create_or_update
        except CloudError as e:
            raise e
        except ErrorResponseException as err:
            handle_service_exception(err)

    def list(self):
        try:
            return self.mgmt_sdk.digital_twins.list()
        except ErrorResponseException as e:
            handle_service_exception(e)

    def list_by_resouce_group(self, resource_group_name):
        try:
            return self.mgmt_sdk.digital_twins.list_by_resource_group(
                resource_group_name=resource_group_name
            )
        except ErrorResponseException as e:
            handle_service_exception(e)

    def get(self, name, resource_group_name, wait=False):
        try:
            return self.mgmt_sdk.digital_twins.get(
                resource_name=name, resource_group_name=resource_group_name
            )
        except ErrorResponseException as e:
            handle_service_exception(e)

    def find_instance(self, name, resource_group_name=None, wait=False):
        if resource_group_name:
            return self.get(
                name=name, resource_group_name=resource_group_name, wait=wait
            )

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
                raise ArgumentUsageError(
                    "Ambiguous DT instance name. Please include the DT instance resource group."
                )
            return filter_result[0]

        raise ResourceNotFoundError(
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
            handle_service_exception(e)

    # RBAC

    def get_role_assignments(
        self, name, include_inherited=False, role_type=None, resource_group_name=None
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        return self.rbac.list_assignments(
            dt_scope=target_instance.id,
            include_inherited=include_inherited,
            role_type=role_type,
        )

    def assign_role(self, name, role_type, assignee, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        return self.rbac.assign_role(
            dt_scope=target_instance.id, assignee=assignee, role_type=role_type
        )

    def remove_role(self, name, assignee, role_type=None, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        return self.rbac.remove_role(
            dt_scope=target_instance.id, assignee=assignee, role_type=role_type
        )

    # Identity

    def assign_identity(
        self,
        name,
        system_identity=None,
        user_identities=None,
        identity_role=None,
        identity_scopes=None,
        resource_group_name=None
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        if bool(identity_role) ^ bool(identity_scopes):
            raise RequiredArgumentMissingError(
                'At least one scope (--scopes) and one role (--role) required for system-managed identity role assignment.'
            )
        if not system_identity and not user_identities:
            raise RequiredArgumentMissingError(
                'No identities provided to assign. Please provide system (--system) or user-assigned identities (--user).'
            )

        if not target_instance.identity:
            target_instance.identity = DigitalTwinsIdentity()

        if user_identities:
            if not target_instance.identity.user_assigned_identities:
                target_instance.identity.user_assigned_identities = {}
            for user_identity in user_identities:
                identity = target_instance.identity.user_assigned_identities.get(user_identity, {})
                target_instance.identity.user_assigned_identities[user_identity] = identity

        has_system_identity = target_instance.identity.type in [
            IdentityType.system_assigned_user_assigned.value, IdentityType.system_assigned.value
        ]

        if system_identity or has_system_identity:
            if target_instance.identity.user_assigned_identities:
                target_instance.identity.type = IdentityType.system_assigned_user_assigned.value
            else:
                target_instance.identity.type = IdentityType.system_assigned.value
        else:
            if target_instance.identity.user_assigned_identities:
                target_instance.identity.type = IdentityType.user_assigned.value
            else:
                target_instance.identity.type = IdentityType.none.value

        try:
            update_poller = self.mgmt_sdk.digital_twins.create_or_update(
                resource_name=name,
                resource_group_name=resource_group_name,
                digital_twins_create=target_instance,
                long_running_operation_timeout=60,
            )

            def rbac_handler(lro):
                instance = lro.resource().as_dict()
                identity = instance.get("identity")
                if identity:
                    identity_type = identity.get("type")
                    principal_id = identity.get("principal_id")

                    if (
                        principal_id
                        and identity_scopes
                        and identity_type
                        and identity_type.lower() == "systemassigned"
                    ):
                        for scope in identity_scopes:
                            logger.info(
                                "Applying rbac assignment: Principal Id: {}, Scope: {}, Role: {}".format(
                                    principal_id, scope, identity_role
                                )
                            )
                            self.rbac.assign_role_flex(
                                principal_id=principal_id,
                                scope=scope,
                                role_type=identity_role,
                            )

            update_poller.add_done_callback(rbac_handler)
            return update_poller
        except CloudError as e:
            raise e
        except ErrorResponseException as err:
            handle_service_exception(err)

    def remove_identity(
        self,
        name,
        system_identity=None,
        user_identities=None,
        resource_group_name=None
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        if not system_identity and user_identities is None:
            raise RequiredArgumentMissingError(
                'No identities provided to remove. Please provide system (--system) or user-assigned identities (--user).'
            )

        # Turn off system managed identity
        if system_identity:
            if target_instance.identity.type not in [
                    IdentityType.system_assigned.value,
                    IdentityType.system_assigned_user_assigned.value
            ]:
                raise ArgumentUsageError('Digital Twin {} is not currently using a system-assigned identity'.format(name))
            elif target_instance.identity.type == IdentityType.system_assigned_user_assigned.value:
                target_instance.identity.type = IdentityType.user_assigned
            else:
                target_instance.identity.type = IdentityType.none.value

        if user_identities and target_instance.identity.user_assigned_identities:
            # loop through user_identities to remove
            for identity in user_identities:
                if not target_instance.identity.user_assigned_identities.get(identity):
                    raise ArgumentUsageError(
                        'Digital Twin {0} is not currently using a user-assigned identity with id: {1}'.format(name, identity)
                    )
                del target_instance.identity.user_assigned_identities[identity]
            if not target_instance.identity.user_assigned_identities:
                target_instance.identity.user_assigned_identities = None
        elif isinstance(user_identities, list):
            target_instance.identity.user_assigned_identities = None

        if target_instance.identity.type in [
                IdentityType.system_assigned.value,
                IdentityType.system_assigned_user_assigned.value
        ]:
            if getattr(target_instance.identity, 'user_assigned_identities', None):
                target_instance.identity.type = IdentityType.system_assigned_user_assigned.value
            else:
                target_instance.identity.type = IdentityType.system_assigned.value
        else:
            if getattr(target_instance.identity, 'user_assigned_identities', None):
                target_instance.identity.type = IdentityType.user_assigned.value
            else:
                target_instance.identity.type = IdentityType.none.value

        try:
            update_poller = self.mgmt_sdk.digital_twins.create_or_update(
                resource_name=name,
                resource_group_name=resource_group_name,
                digital_twins_create=target_instance,
                long_running_operation_timeout=60,
            )
            return update_poller
        except ErrorResponseException as err:
            handle_service_exception(err)

    def show_identity(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )

        return target_instance.identity

    # Endpoints

    def get_endpoint(self, name, endpoint_name, resource_group_name=None, wait=False):
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
            if wait:
                e.status_code = e.response.status_code
                raise e
            handle_service_exception(e)

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
            handle_service_exception(e)

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
            handle_service_exception(e)

    def add_endpoint(
        self,
        name,
        endpoint_name,
        endpoint_resource_type,
        endpoint_resource_name,
        endpoint_resource_group=None,
        endpoint_resource_policy=None,
        endpoint_resource_namespace=None,
        endpoint_subscription=None,
        dead_letter_uri=None,
        dead_letter_secret=None,
        resource_group_name=None,
        timeout=20,
        auth_type=None,
        system_identity=None,
        user_identity=None,
    ):
        from azext_iot.digitaltwins.common import ADTEndpointType

        if system_identity and user_identity:
            raise MutuallyExclusiveArgumentError(
                "Only one type of identity is permitted for endpoint creation."
            )

        identity = "[system]" if system_identity else user_identity

        # do not break users who are still using auth_type to make identity based endpoints
        if not identity and auth_type == ADTEndpointAuthType.identitybased.value:
            identity = "[system]"

        # Determine auth type from identity
        auth_type = ADTEndpointAuthType.identitybased.value if identity else ADTEndpointAuthType.keybased.value

        requires_namespace = [
            ADTEndpointType.eventhub.value,
            ADTEndpointType.servicebus.value,
        ]
        if endpoint_resource_type in requires_namespace:
            if not endpoint_resource_namespace:
                raise RequiredArgumentMissingError(
                    "Endpoint resources of type {} require a namespace.".format(
                        " or ".join(map(str, requires_namespace))
                    )
                )

            if (
                auth_type == ADTEndpointAuthType.keybased.value
                and not endpoint_resource_policy
            ):
                raise RequiredArgumentMissingError(
                    "Endpoint resources of type {} require a policy name when using Key based integration.".format(
                        " or ".join(map(str, requires_namespace))
                    )
                )

        if dead_letter_uri and auth_type == ADTEndpointAuthType.keybased.value:
            raise RequiredArgumentMissingError(
                "Use --deadletter-sas-uri to support deadletter for a Key based endpoint."
            )

        if dead_letter_secret and auth_type == ADTEndpointAuthType.identitybased.value:
            raise RequiredArgumentMissingError(
                "Use --deadletter-uri to support deadletter for an Identity based endpoint."
            )

        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        endpoint_resource_group = endpoint_resource_group or resource_group_name

        from azext_iot.digitaltwins.providers.endpoint.builders import build_endpoint

        properties = build_endpoint(
            endpoint_resource_type=endpoint_resource_type,
            endpoint_resource_name=endpoint_resource_name,
            endpoint_resource_group=endpoint_resource_group,
            endpoint_subscription=endpoint_subscription,
            endpoint_resource_namespace=endpoint_resource_namespace,
            endpoint_resource_policy=endpoint_resource_policy,
            auth_type=auth_type,
            dead_letter_secret=dead_letter_secret,
            dead_letter_uri=dead_letter_uri,
            identity=identity,
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
            handle_service_exception(e)

    def get_private_link(self, name, link_name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.private_link_resources.get(
                resource_group_name=resource_group_name,
                resource_name=name,
                resource_id=link_name,
                raw=True,
            ).response.json()
        except ErrorResponseException as e:
            handle_service_exception(e)

    def list_private_links(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            # This resource is not paged though it may have been the intent.
            link_collection = self.mgmt_sdk.private_link_resources.list(
                resource_group_name=resource_group_name, resource_name=name, raw=True
            ).response.json()
            return link_collection.get("value", [])
        except ErrorResponseException as e:
            handle_service_exception(e)

    def set_private_endpoint_conn(
        self,
        name,
        conn_name,
        status,
        description,
        actions_required=None,
        group_ids=None,
        resource_group_name=None,
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.private_endpoint_connections.create_or_update(
                resource_group_name=resource_group_name,
                resource_name=name,
                private_endpoint_connection_name=conn_name,
                properties={
                    "privateLinkServiceConnectionState": {
                        "status": status,
                        "description": description,
                        "actions_required": actions_required,
                    },
                    "groupIds": group_ids,
                },
            )

        except ErrorResponseException as e:
            handle_service_exception(e)

    def get_private_endpoint_conn(
        self,
        name,
        conn_name,
        resource_group_name=None,
        wait=False
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.private_endpoint_connections.get(
                resource_group_name=resource_group_name,
                resource_name=name,
                private_endpoint_connection_name=conn_name
            )
        except ErrorResponseException as e:
            if wait:
                e.status_code = e.response.status_code
                raise e
            handle_service_exception(e)

    def list_private_endpoint_conns(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            # This resource is not paged though it may have been the intent.
            endpoint_collection = self.mgmt_sdk.private_endpoint_connections.list(
                resource_group_name=resource_group_name, resource_name=name, raw=True
            ).response.json()
            return endpoint_collection.get("value", [])
        except ErrorResponseException as e:
            handle_service_exception(e)

    def delete_private_endpoint_conn(self, name, conn_name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.private_endpoint_connections.delete(
                resource_group_name=resource_group_name,
                resource_name=name,
                private_endpoint_connection_name=conn_name
            )
        except ErrorResponseException as e:
            handle_service_exception(e)

    def create_adx_data_connection(
        self,
        name,
        conn_name,
        adx_cluster_name,
        adx_database_name,
        eh_namespace,
        eh_entity_path,
        adx_table_name=None,
        adx_resource_group=None,
        adx_subscription=None,
        eh_consumer_group=DEFAULT_CONSUMER_GROUP,
        eh_resource_group=None,
        eh_subscription=None,
        resource_group_name=None,
        yes=False,
    ):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)
        subscription = target_instance.id.split("/")[2]

        if len(conn_name) <= 2:
            raise InvalidArgumentValueError(
                "The connection name must have a length greater than 2"
            )

        adx_resource_group = adx_resource_group if adx_resource_group else resource_group_name
        eh_resource_group = eh_resource_group if eh_resource_group else resource_group_name
        adx_subscription = adx_subscription if adx_subscription else subscription
        eh_subscription = eh_subscription if eh_subscription else subscription

        from azext_iot.digitaltwins.providers.connection.builders import build_adx_connection_properties
        properties = build_adx_connection_properties(
            adx_cluster_name=adx_cluster_name,
            adx_database_name=adx_database_name,
            adx_table_name=adx_table_name,
            adx_resource_group=adx_resource_group,
            adx_subscription=adx_subscription,
            dt_instance=target_instance,
            eh_namespace=eh_namespace,
            eh_entity_path=eh_entity_path,
            eh_consumer_group=eh_consumer_group,
            eh_resource_group=eh_resource_group,
            eh_subscription=eh_subscription,
            yes=yes,
        )

        try:
            def check_state(lro):
                generic_check_state(
                    lro=lro,
                    show_cmd="az dt data-history show -n {} -g {} --cn {}".format(
                        name, resource_group_name, conn_name
                    ),
                    max_retries=MAX_ADT_DH_CREATE_RETRIES
                )

            create_or_update = self.mgmt_sdk.time_series_database_connections.create_or_update(
                resource_group_name=resource_group_name,
                resource_name=name,
                time_series_database_connection_name=conn_name,
                properties=properties
            )
            create_or_update.add_done_callback(check_state)
            return create_or_update
        except ErrorResponseException as e:
            handle_service_exception(e)

    def get_data_connection(self, name, conn_name, resource_group_name=None, wait=False):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.time_series_database_connections.get(
                resource_group_name=resource_group_name,
                resource_name=name,
                time_series_database_connection_name=conn_name,
            )
        except ErrorResponseException as e:
            if wait:
                e.status_code = e.response.status_code
                raise e
            handle_service_exception(e)

    def list_data_connection(self, name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.time_series_database_connections.list(
                resource_group_name=resource_group_name,
                resource_name=name,
            )
        except ErrorResponseException as e:
            handle_service_exception(e)

    def delete_data_connection(self, name, conn_name, resource_group_name=None):
        target_instance = self.find_instance(
            name=name, resource_group_name=resource_group_name
        )
        if not resource_group_name:
            resource_group_name = self.get_rg(target_instance)

        try:
            return self.mgmt_sdk.time_series_database_connections.delete(
                resource_group_name=resource_group_name,
                resource_name=name,
                time_series_database_connection_name=conn_name,
            )
        except ErrorResponseException as e:
            handle_service_exception(e)
