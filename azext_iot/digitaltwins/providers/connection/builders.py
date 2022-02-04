# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.sdk.digitaltwins.controlplane.models import AzureDataExplorerConnectionProperties
from knack.util import CLIError
from knack.log import get_logger
from knack.prompting import prompt_y_n
from azext_iot.digitaltwins.common import (
    DT_IDENTITY_ERROR,
    ERROR_PREFIX,
    FINISHED_CHECK_RESOURCE_LOG_MSG,
    ADX_ROLE_MSG,
    RBAC_ROLE_MSG,
    TRY_ADD_ROLE_LOG_MSG,
    FINISHED_ADD_ROLE_LOG_MSG,
    SKIP_ADD_ROLE_MSG,
    FAIL_RBAC_MSG,
    FAIL_GENERIC_MSG,
    ABORT_MSG,
    ADD_ROLE_INPUT_MSG,
    CONT_INPUT_MSG
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
        eh_consumer_group: str = '$Default',
        yes: bool = False,
    ):
        self.cli = EmbeddedCLI()
        self.yes = yes
        self.dt = dt_instance
        if self.dt.identity is None:
            raise CLIError(DT_IDENTITY_ERROR)

        # Populate adx_cluster_uri, adx_location, adx_resource_id and perform checks
        self.validate_adx(
            adx_cluster_name=adx_cluster_name,
            adx_database_name=adx_database_name,
            adx_resource_group=adx_resource_group,
            adx_subscription=adx_subscription,
        )

        self.eh_consumer_group = eh_consumer_group
        # Populate eh_endpoint_uri, eh_namespace_resource_id and perform checks
        self.validate_eventhub(
            eh_namespace=eh_namespace,
            eh_entity_path=eh_entity_path,
            eh_resource_group=eh_resource_group,
            eh_subscription=eh_subscription,
            eh_consumer_group=eh_consumer_group,
        )

    def validate_eventhub(
        self,
        eh_namespace: str,
        eh_entity_path: str,
        eh_resource_group: str,
        eh_subscription: str,
        eh_consumer_group: str
    ):
        from azext_iot.digitaltwins.providers.endpoint.builders import EventHubEndpointBuilder
        eh_endpoint = EventHubEndpointBuilder(
            endpoint_resource_name=eh_entity_path,
            endpoint_resource_group=eh_resource_group,
            endpoint_resource_namespace=eh_namespace,
            endpoint_resource_policy=None,
            endpoint_subscription=eh_subscription,
        )
        eh_endpoint.error_prefix = ERROR_PREFIX + " find"
        self.eh_endpoint_uri = eh_endpoint.build_identity_based().endpoint_uri

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
            raise CLIError("{} retrieve Event Hub Consumer Group.".format(ERROR_PREFIX))

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
            resource_id=f"{self.eh_namespace_resource_id}/eventhubs/{eh_entity_path}"
        )

    def validate_adx(
        self,
        adx_cluster_name: str,
        adx_database_name: str,
        adx_resource_group: str,
        adx_subscription: str,
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
            raise CLIError("{} retrieve Cluster.".format(ERROR_PREFIX))

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
            raise CLIError("{} retrieve Database.".format(ERROR_PREFIX))

        logger.debug(FINISHED_CHECK_RESOURCE_LOG_MSG.format("Azure Data Explorer"))

        self.add_dt_role_assignment(
            role="Contributor",
            resource_id=f"{self.adx_resource_id}/databases/{adx_database_name}"
        )
        self.add_adx_principal(adx_database_name, api_version)

    def add_dt_role_assignment(self, role, resource_id):
        role_str = RBAC_ROLE_MSG.format(role, resource_id)
        logger.debug(TRY_ADD_ROLE_LOG_MSG.format(role_str))
        if not (self.yes or prompt_y_n(msg=ADD_ROLE_INPUT_MSG.format(role_str), default="y")):
            print(SKIP_ADD_ROLE_MSG.format(role_str))
            return

        role_command = (
            "role assignment create --role '{}' --assignee-object-id {} "
            "--assignee-principal-type ServicePrincipal --scope {}".format(
                role,
                self.dt.identity.principal_id,
                resource_id
            )
        )
        role_op = self.cli.invoke(role_command)
        if not role_op.success():
            print(FAIL_RBAC_MSG.format(role_str, role_command))
            if not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise CLIError(ABORT_MSG)

        logger.debug(FINISHED_ADD_ROLE_LOG_MSG.format(role_str))

    def add_adx_principal(self, adx_database_name: str, api_version: str):
        role_str = ADX_ROLE_MSG.format(adx_database_name)
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
                        "appId": self.dt.identity.principal_id,
                    }]
                })
            )
        )
        if not database_admin_op.success():
            print(FAIL_GENERIC_MSG.format(role_str))
            if not prompt_y_n(msg=CONT_INPUT_MSG, default="n"):
                raise CLIError(ABORT_MSG)
            return

        logger.debug(FINISHED_ADD_ROLE_LOG_MSG.format(role_str))


def build_adx_connection_properties(
    adx_cluster_name: str,
    adx_database_name: str,
    dt_instance,
    eh_namespace: str,
    eh_entity_path: str,
    adx_table_name: str = None,
    adx_resource_group: str = None,
    adx_subscription: str = None,
    eh_resource_group: str = None,
    eh_subscription: str = None,
    eh_consumer_group: str = "$Default",
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
        yes=yes,
    )

    return AzureDataExplorerConnectionProperties(
        adx_resource_id=validator.adx_resource_id,
        adx_endpoint_uri=validator.adx_cluster_uri,
        adx_database_name=adx_database_name,
        adx_table_name=adx_table_name,
        event_hub_endpoint_uri=validator.eh_endpoint_uri,
        event_hub_entity_path=eh_entity_path,
        event_hub_consumer_group=eh_consumer_group,
        event_hub_namespace_resource_id=validator.eh_namespace_resource_id
    )
