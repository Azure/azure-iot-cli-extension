# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.sdk.digitaltwins.controlplane.models import AzureDataExplorerConnectionProperties
from abc import ABC
from knack.util import CLIError
from knack.log import get_logger
from knack.prompting import prompt_y_n

logger = get_logger(__name__)


class AdxConnectionValidator(ABC):
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
        self.error_prefix = "Could not create ADT instance connection. Unable to"
        self.dt = dt_instance
        if self.dt.identity is None:
            raise CLIError(
                "DT instance does not have System-Assigned Identity enabled. Please enable and try again."
            )

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
        eh_endpoint.error_prefix = self.error_prefix + " find"
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
            raise CLIError("{} retrieve Event Hub Consumer Group.".format(self.error_prefix))

        self.eh_namespace_resource_id = (
            "/subscriptions/{}/resourceGroups/{}/providers/Microsoft.EventHub/namespaces/{}".format(
                eh_subscription,
                eh_resource_group,
                eh_namespace,
            )
        )
        logger.debug("Finished checking the EventHub resource.")

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
            raise CLIError("{} retrieve Cluster.".format(self.error_prefix))

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
            raise CLIError("{} retrieve Database.".format(self.error_prefix))

        logger.debug("Finished checking the ADX resource.")

        self.add_dt_role_assignment(
            role="Contributor",
            resource_id=f"{self.adx_resource_id}/databases/{adx_database_name}"
        )
        self.add_adx_principal(adx_database_name, api_version)

    def add_dt_role_assignment(self, role, resource_id):
        role_str = f"'{role}' role on the Digital Twins instance for the scope '{resource_id}'"
        logger.debug(f"Trying to add the {role_str}.")
        if not (self.yes or prompt_y_n(msg=f"Add the {role_str}?", default="y")):
            print(
                f"Skipping addition of the '{role}' role. "
                "This may prevent creation of the data history connection."
            )
            return

        current_roles_op = self.cli.invoke(
            "role assignment list --role '{}' --assignee {} --scope {}".format(
                role,
                self.dt.identity.principal_id,
                resource_id
            )
        )

        if current_roles_op.success() and len(current_roles_op.as_json()) > 1:
            logger.debug(f"The {role_str} is already present.")
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
            print(
                "{} assign {}. Please assign role manually with the command `az {}`.".format(
                    self.error_prefix, role_str, role_command
                )
            )
            if not prompt_y_n(msg="Continue with Data History Connection create anyway?", default="n"):
                raise CLIError("Command was aborted.")

        logger.debug(f"Finished adding the {role_str}.")

    def add_adx_principal(self, adx_database_name: str, api_version: str):
        role_str = (
            "'Database Admin' permission on the Digital Twins instance for the Azure Data Explorer"
            f" database '{adx_database_name}'"
        )
        try:
            logger.debug(f"Trying to add the {role_str}.")
            if not (self.yes or prompt_y_n(msg=f"Add the {role_str}?", default="y")):
                print(
                    "Skipping addition of the 'Database Admin' permission. "
                    "This may prevent creation of the data history connection."
                )
                return

            database_admin_list_op = self.cli.invoke(
                "rest --method POST --url {}/databases/{}/listPrincipals?{}".format(
                    self.adx_resource_id,
                    adx_database_name,
                    api_version,
                )
            )
            if not database_admin_list_op.success():
                raise database_admin_list_op.az_cli.result.error

            for principal in database_admin_list_op.as_json()["value"]:
                if principal["name"] == self.dt.name:
                    logger.debug(f"The {role_str} is already present.")
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
                raise database_admin_op.az_cli.result.error
            logger.debug(f"Finished adding the {role_str}.")

        except CLIError:
            print(
                "{} assign 'Database Admin' role to the Digital Twins instance. Please assign this role manually.".format(
                    self.error_prefix
                )
            )
            if not prompt_y_n(msg="Continue with Data History Connection create anyway?", default="n"):
                raise CLIError("Command was aborted.")
            return


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
