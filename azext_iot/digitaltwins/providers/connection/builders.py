# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from typing import Optional

from azure.cli.core.azclierror import BadRequestError, CLIInternalError, ManualInterrupt
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.sdk.digitaltwins.controlplane.models import (
    AzureDataExplorerConnectionProperties,
    ManagedIdentityReference,
    DigitalTwinsIdentityType,
)
from knack.log import get_logger
from knack.prompting import prompt_y_n
from azext_iot.digitaltwins.common import (
    DT_INSTANCE,
    USER_ASSIGNED_IDENTITY,
    DT_SYS_IDENTITY_ERROR,
    DT_UAI_IDENTITY_ERROR,
    ERROR_PREFIX,
    FINISHED_CHECK_RESOURCE_LOG_MSG,
    ADX_ROLE_MSG,
    RBAC_ROLE_MSG,
    SYSTEM_IDENTITY,
    TRY_ADD_ROLE_LOG_MSG,
    FINISHED_ADD_ROLE_LOG_MSG,
    SKIP_ADD_ROLE_MSG,
    FAIL_RBAC_MSG,
    FAIL_GENERIC_MSG,
    ABORT_MSG,
    ADD_ROLE_INPUT_MSG,
    CONT_INPUT_MSG,
    DEFAULT_CONSUMER_GROUP
)

logger = get_logger(__name__)


class AdxConnectionValidator(object):
    def __init__(
        self,
        adx_cluster_name: str,
        adx_database_name: str,
        adx_resource_group: str,
        adx_subscription: str,
        dt_instance,
        eh_namespace: str,
        eh_entity_path: str,
        eh_resource_group: str,
        eh_subscription: str,
        eh_consumer_group: str = DEFAULT_CONSUMER_GROUP,
        identity: str = SYSTEM_IDENTITY,
        yes: bool = False,
    ):
        self.cli = EmbeddedCLI()
        self.yes = yes
        self.dt = dt_instance
        # Check that the identity is associated with the dt
        if self.dt.identity is None and identity == SYSTEM_IDENTITY:
            raise BadRequestError(DT_SYS_IDENTITY_ERROR)
        elif (
            self.dt.identity is None
            or identity not in self.dt.identity.user_assigned_identities
            and identity != SYSTEM_IDENTITY
        ):
            raise BadRequestError(DT_UAI_IDENTITY_ERROR)
        # set the identity to be principal id for ease
        principal_id = (
            self.dt.identity.principal_id
            if identity == SYSTEM_IDENTITY
            else self.dt.identity.user_assigned_identities[identity].principal_id
        )

        # Populate adx_cluster_uri, adx_location, adx_resource_id and perform checks
        self.validate_adx(
            adx_cluster_name=adx_cluster_name,
            adx_database_name=adx_database_name,
            adx_resource_group=adx_resource_group,
            adx_subscription=adx_subscription,
            principal_id=principal_id,
        )

        self.eh_consumer_group = eh_consumer_group
        # Populate eh_endpoint_uri, eh_namespace_resource_id and perform checks
        self.validate_eventhub(
            eh_namespace=eh_namespace,
            eh_entity_path=eh_entity_path,
            eh_resource_group=eh_resource_group,
            eh_subscription=eh_subscription,
            eh_consumer_group=eh_consumer_group,
            identity=identity,
            principal_id=principal_id,
        )

    def validate_eventhub(
        self,
        eh_namespace: str,
        eh_entity_path: str,
        eh_resource_group: str,
        eh_subscription: str,
        eh_consumer_group: str,
        identity: str,
        principal_id: str
    ):
        from azext_iot.digitaltwins.providers.endpoint.builders import EventHubEndpointBuilder
        eh_endpoint = EventHubEndpointBuilder(
            endpoint_resource_name=eh_entity_path,
            endpoint_resource_group=eh_resource_group,
            endpoint_resource_namespace=eh_namespace,
            endpoint_resource_policy=None,
            endpoint_subscription=eh_subscription,
            identity=identity
        )
        eh_endpoint.error_prefix = ERROR_PREFIX + " find"
        self.eh_endpoint_uri = eh_endpoint.build_identity_based().endpoint_uri

        # Run check only if the consumer group is not the default. Default consumer group will always be present.
        if eh_consumer_group.lower() != DEFAULT_CONSUMER_GROUP.lower():
            eh_consumer_group_op = self.cli.invoke(
                "eventhubs eventhub consumer-group show -n {} --eventhub-name {} --namespace-name {} -g {}".format(
                    eh_consumer_group,
                    eh_entity_path,
                    eh_namespace,
                    eh_resource_group,
                ),
                subscription=eh_subscription,
            )
            if not eh_consumer_group_op.success():
                raise CLIInternalError("{} retrieve Event Hub Consumer Group.".format(ERROR_PREFIX))

        self.eh_namespace_resource_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.EventHub/namespaces/{}".format(
                eh_subscription,
                eh_resource_group,
                eh_namespace,
            )
        )
        logger.debug(FINISHED_CHECK_RESOURCE_LOG_MSG.format("Event Hub"))

        self.add_dt_role_assignment(
            role="Azure Event Hubs Data Owner",
            resource_id=f"{self.eh_namespace_resource_id}/eventhubs/{eh_entity_path}",
            principal_id=principal_id
        )

    def validate_adx(
        self,
        adx_cluster_name: str,
        adx_database_name: str,
        adx_resource_group: str,
        adx_subscription: str,
        principal_id: str,
    ):
        api_version = "api-version=2021-01-01"
        self.adx_resource_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.Kusto/clusters/{}".format(
                adx_subscription,
                adx_resource_group,
                adx_cluster_name
            )
        )

        adx_cluster_op = self.cli.invoke(
            "rest --method get --url {}?{}".format(
                self.adx_resource_id,
                api_version
            )
        )
        if not adx_cluster_op.success():
            raise CLIInternalError("{} retrieve Cluster.".format(ERROR_PREFIX))

        adx_cluster_meta = adx_cluster_op.as_json()
        self.adx_cluster_uri = adx_cluster_meta["properties"]["uri"]
        self.adx_location = adx_cluster_meta["location"].lower().replace(" ", "")

        adx_database_op = self.cli.invoke(
            "rest --method get --url {}/databases/{}?{}".format(
                self.adx_resource_id,
                adx_database_name,
                api_version
            )
        )
        if not adx_database_op.success():
            raise CLIInternalError("{} retrieve Database.".format(ERROR_PREFIX))

        logger.debug(FINISHED_CHECK_RESOURCE_LOG_MSG.format("Azure Data Explorer"))

        self.add_dt_role_assignment(
            role="Contributor",
            resource_id=f"{self.adx_resource_id}/databases/{adx_database_name}",
            principal_id=principal_id
        )
        self.add_adx_principal(adx_database_name, api_version, principal_id)

    def add_dt_role_assignment(self, role: str, resource_id: str, principal_id: str):
        assignee = DT_INSTANCE if self.dt.identity.principal_id == principal_id else USER_ASSIGNED_IDENTITY
        role_str = RBAC_ROLE_MSG.format(role, assignee, resource_id)
        logger.debug(TRY_ADD_ROLE_LOG_MSG.format(role_str))
        if not (self.yes or prompt_y_n(msg=ADD_ROLE_INPUT_MSG.format(role_str), default="y")):
            print(SKIP_ADD_ROLE_MSG.format(role_str))
            return

        role_command = (
            "role assignment create --role '{}' --assignee-object-id {} "
            "--assignee-principal-type ServicePrincipal --scope {}".format(
                role,
                principal_id,
                resource_id
            )
        )
        role_op = self.cli.invoke(role_command)
        if not role_op.success():
            print(FAIL_RBAC_MSG.format(role_str, role_command))
            if not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise ManualInterrupt(ABORT_MSG)

        logger.debug(FINISHED_ADD_ROLE_LOG_MSG.format(role_str))

    def add_adx_principal(self, adx_database_name: str, api_version: str, principal_id: str):
        assignee = DT_INSTANCE if self.dt.identity.principal_id == principal_id else USER_ASSIGNED_IDENTITY
        role_str = ADX_ROLE_MSG.format(assignee, adx_database_name)
        logger.debug(TRY_ADD_ROLE_LOG_MSG.format(role_str))
        if not (self.yes or prompt_y_n(msg=ADD_ROLE_INPUT_MSG.format(role_str), default="y")):
            print(SKIP_ADD_ROLE_MSG.format(role_str))
            return

        database_admin_op = self.cli.invoke(
            "rest --method POST --url {}/databases/{}/addPrincipals?{} -b '{}'".format(
                self.adx_resource_id,
                adx_database_name,
                api_version,
                json.dumps({
                    "value": [{
                        "role": "Admin",
                        "name": self.dt.name,
                        "type": "App",
                        "appId": principal_id,
                    }]
                })
            )
        )
        if not database_admin_op.success():
            print(FAIL_GENERIC_MSG.format(role_str))
            if not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise ManualInterrupt(ABORT_MSG)
            return

        logger.debug(FINISHED_ADD_ROLE_LOG_MSG.format(role_str))


def build_adx_connection_properties(
    adx_cluster_name: str,
    adx_database_name: str,
    dt_instance,
    eh_namespace: str,
    eh_entity_path: str,
    adx_table_name: Optional[str] = None,
    adx_resource_group: Optional[str] = None,
    adx_subscription: Optional[str] = None,
    eh_resource_group: Optional[str] = None,
    eh_subscription: Optional[str] = None,
    eh_consumer_group: str = DEFAULT_CONSUMER_GROUP,
    identity: str = SYSTEM_IDENTITY,
    yes: bool = False,
):
    validator = AdxConnectionValidator(
        adx_cluster_name=adx_cluster_name,
        adx_database_name=adx_database_name,
        adx_resource_group=adx_resource_group,
        adx_subscription=adx_subscription,
        dt_instance=dt_instance,
        eh_namespace=eh_namespace,
        eh_entity_path=eh_entity_path,
        eh_consumer_group=eh_consumer_group,
        eh_resource_group=eh_resource_group,
        eh_subscription=eh_subscription,
        identity=identity,
        yes=yes,
    )

    if identity == SYSTEM_IDENTITY:
        identity = ManagedIdentityReference(
            type=DigitalTwinsIdentityType.system_assigned.value
        )
    else:
        identity = ManagedIdentityReference(
            type=DigitalTwinsIdentityType.user_assigned.value,
            user_assigned_identity=identity
        )

    return AzureDataExplorerConnectionProperties(
        adx_resource_id=validator.adx_resource_id,
        adx_endpoint_uri=validator.adx_cluster_uri,
        adx_database_name=adx_database_name,
        adx_table_name=adx_table_name,
        event_hub_endpoint_uri=validator.eh_endpoint_uri,
        event_hub_entity_path=eh_entity_path,
        event_hub_consumer_group=eh_consumer_group,
        event_hub_namespace_resource_id=validator.eh_namespace_resource_id,
        identity=identity
    )
