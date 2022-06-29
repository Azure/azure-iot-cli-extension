# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for Digital Twins commands.
"""

from knack.help_files import helps


def load_digitaltwins_help():

    helps["dt"] = """
        type: group
        short-summary: Manage Azure Digital Twins solutions & infrastructure.
    """

    helps["dt create"] = """
        type: command
        short-summary: Create or update a Digital Twins instance.

        examples:
        - name: Create instance in target resource group using the resource group location.
          text: >
            az dt create -n {instance_name} -g {resouce_group}

        - name: Create instance in target resource group with specified location and tags.
          text: >
            az dt create -n {instance_name} -g {resouce_group} -l westus --tags a=b c=d

        - name: Create instance in the target resource group with a system managed identity.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --assign-identity

        - name: Create instance in the target resource group with a system managed identity then
                assign the identity to one or more scopes (space-separated) with the role of Contributor.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --assign-identity
            --scopes
            "/subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.EventHub/namespaces/myEventHubNamespace/eventhubs/myEventHub"
            "/subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.ServiceBus/namespaces/myServiceBusNamespace/topics/myTopic"

        - name: Create instance in the target resource group with a system managed identity then
                assign the identity to one or more scopes with a custom specified role.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --assign-identity
            --scopes
            "/subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.EventHub/namespaces/myEventHubNamespace/eventhubs/myEventHub"
            "/subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.ServiceBus/namespaces/myServiceBusNamespace/topics/myTopic"
            --role MyCustomRole

        - name: Update an instance in the target resource group to enable system managed identity.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --assign-identity

        - name: Update an instance in the target resource group to disable system managed identity.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --assign-identity false

        - name: Update an instance in the target resource group with new tag values and disable public network access.
          text: >
            az dt create -n {instance_name} -g {resouce_group} --tags env=prod --public-network-access Disabled
    """

    helps["dt show"] = """
        type: command
        short-summary: Show an existing Digital Twins instance.

        examples:
        - name: Show an instance.
          text: >
            az dt show -n {instance_name}

        - name: Show an instance and project certain properties.
          text: >
            az dt show -n {instance_name} --query "{Endpoint:hostName, Location:location}"
    """

    helps["dt list"] = """
        type: command
        short-summary: List the collection of Digital Twins instances by subscription or resource group.

        examples:
        - name: List all instances in the current subscription.
          text: >
            az dt list

        - name: List all instances in target resource group and output in table format.
          text: >
            az dt list -g {resource_group} --output table

        - name: List all instances in subscription that meet a condition.
          text: >
            az dt list --query "[?contains(name, 'Production')]"

        - name: Count instances that meet condition.
          text: >
            az dt list --query "length([?contains(name, 'Production')])"
    """

    helps["dt delete"] = """
        type: command
        short-summary: Delete an existing Digital Twins instance.

        examples:
        - name: Delete an arbitrary instance in blocking fashion with a confirmation prompt.
          text: >
            az dt delete -n {instance_name}
        - name: Delete an arbitrary instance with no blocking or prompt.
          text: >
            az dt delete -n {instance_name} -y --no-wait
    """

    helps["dt wait"] = """
        type: command
        short-summary: Wait until an operation on an Digital Twins instance is complete.

        examples:
        - name: Wait until an arbitrary instance is created.
          text: >
            az dt wait -n {instance_name} --created
        - name: Wait until an existing instance is deleted.
          text: >
            az dt wait -n {instance_name} --deleted
        - name: Wait until an existing instance's publicNetworkAccess property is set to Enabled
          text: >
            az dt wait -n {instance_name} --custom "publicNetworkAccess=='Enabled'"
    """

    helps["dt reset"] = """
        type: command
        short-summary: Reset an existing Digital Twins instance by deleting associated
            assets. Currently only supports deleting models and twins.

        examples:
        - name: Reset all assets for a Digital Twins instance.
          text: >
            az dt reset -n {instance_name}
    """

    helps["dt data-history"] = """
        type: group
        short-summary: Manage and configure data history.
    """

    helps["dt data-history connection"] = """
        type: group
        short-summary: Manage and configure data history connections.
    """

    helps["dt data-history connection create"] = """
        type: group
        short-summary: Creates a data history connection between a Digital Twins instance and supported resources.
    """

    helps["dt data-history connection create adx"] = """
        type: command
        short-summary: Creates a data history connection between a Digital Twins instance and an Azure
            Data Explorer database. Requires pre-created Azure Data Explorer and Event Hub resources.
        long-summary: |
            Will prompt the user to add the following roles and permissions on the Digital Twins instance needed to successfully create the connection:
            - 'Contributor' role for the Azure Data Explorer Database scope
            - 'Database Admin' permission for the Azure Data Explorer Database scope
            - 'Azure Event Hubs Data Owner' role for the Event Hub scope

        examples:
        - name: Adds a data history connection to a target Digital Twins instance with the $Default Event Hub
            consumer group.
          text: >
            az dt data-history connection create adx -n {instance_name}
            --cn {time_series_database_connection_name}
            --adx-cluster-name {adx_cluster_name}
            --adx-database-name {adx_database_name}
            --eventhub {event_hub}
            --eventhub-namespace {event_hub_namespace}
        - name: Adds a data history connection to a target Digital Twins instance with a custom Azure Data Explorer
            table name and Event Hub consumer group.
          text: >
            az dt data-history connection create adx -n {instance_name}
            --cn {time_series_database_connection_name}
            --adx-cluster-name {adx_cluster_name}
            --adx-database-name {adx_database_name}
            --adx-table-name {adx_table_name}
            --eventhub {event_hub}
            --eventhub-namespace {event_hub_namespace}
            --eventhub-consumer-group {event_hub_consumer_group}
        - name: Adds a data history connection to a target Digital Twins instance integrating with an Event Hub and Azure
            Data Explorer instances in different resource groups and subscriptions from the target instance.
          text: >
            az dt data-history connection create adx -n {instance_name}
            --cn {time_series_database_connection_name}
            --adx-cluster-name {adx_cluster_name}
            --adx-database-name {adx_database_name}
            --adx-resource-group {adx_resource_group}
            --adx-subscription {adx_subscription}
            --eventhub {event_hub}
            --eventhub-namespace {event_hub_namespace}
            --eventhub-resource-group {event_hub_resource_group}
            --eventhub-subscription {event_subscription}
        - name: Adds a data history connection to a target Digital Twins instance with the $Default Event Hub consumer group
            and skip the role assignment prompts.
          text: >
            az dt data-history connection create adx -n {instance_name} -y
            --cn {time_series_database_connection_name}
            --adx-cluster-name {adx_cluster_name}
            --adx-database-name {adx_database_name}
            --eventhub {event_hub}
            --eventhub-namespace {event_hub_namespace}
    """

    helps["dt data-history connection list"] = """
        type: command
        short-summary: List all data history connections configured on a Digital Twins instance.
        examples:
        - name: List all data history connections configured on an instance.
          text: >
            az dt data-history connection list -n {instance_name}
    """

    helps["dt data-history connection show"] = """
        type: command
        short-summary: Show details of a data history connection configured on a Digital Twins instance.
        examples:
        - name: Show a data history connection configured on an instance.
          text: >
            az dt data-history connection show -n {instance_name} --cn {time_series_database_connection_name}
    """

    helps["dt data-history connection wait"] = """
        type: command
        short-summary: Wait until an operation on a data history connection is complete.
        examples:
        - name: Wait until a data history connection is created.
          text: >
            az dt data-history connection wait -n {instance_name} --cn {time_series_database_connection_name} --created
        - name: Wait until an existing data history connection is deleted.
          text: >
            az dt data-history connection wait -n {instance_name} --cn {time_series_database_connection_name} --deleted
    """

    helps["dt data-history connection delete"] = """
        type: command
        short-summary: Delete a data history connection configured on a Digital Twins instance.
        examples:
        - name: Delete a data history connection configured on an instance
            and block until the operation is complete.
          text: >
            az dt data-history connection delete -n {instance_name}
            --cn {time_series_database_connection_name}
        - name: Delete a data history connection configured on an instance
            without confirmation or blocking.
          text: >
            az dt data-history connection delete -n {instance_name}
            --cn {time_series_database_connection_name}
            -y --no-wait
    """

    helps["dt endpoint"] = """
        type: group
        short-summary: Manage and configure Digital Twins instance endpoints.
    """

    helps["dt endpoint create"] = """
        type: group
        short-summary: Add egress endpoints to a Digital Twins instance.
    """

    helps["dt endpoint create eventgrid"] = """
        type: command
        short-summary: Adds an EventGrid Topic endpoint to a Digital Twins instance.
            Requires pre-created resource.

        examples:
        - name: Adds an EventGrid Topic endpoint to a target instance.
          text: >
            az dt endpoint create eventgrid --endpoint-name {endpoint_name}
            --eventgrid-resource-group {eventgrid_resource_group}
            --eventgrid-topic {eventgrid_topic_name}
            -n {instance_name}
    """

    helps["dt endpoint create eventhub"] = """
        type: command
        short-summary: Adds an EventHub endpoint to a Digital Twins instance.
            Requires pre-created resource. The instance must be created
            with a managed identity to support identity based endpoint integration

        examples:
        - name: Adds an EventHub endpoint to a target instance using Key based auth.
          text: >
            az dt endpoint create eventhub --endpoint-name {endpoint_name}
            --eventhub-resource-group {eventhub_resource_group}
            --eventhub-namespace {eventhub_namespace}
            --eventhub {eventhub_name}
            --eventhub-policy {eventhub_policy}
            -n {instance_name}

        - name: Adds an EventHub endpoint to a target instance using Identity based auth.
          text: >
            az dt endpoint create eventhub --endpoint-name {endpoint_name}
            --eventhub-resource-group {eventhub_resource_group}
            --eventhub-namespace {eventhub_namespace}
            --eventhub {eventhub_name}
            --auth-type IdentityBased
            -n {instance_name}
    """

    helps["dt endpoint create servicebus"] = """
        type: command
        short-summary: Adds a ServiceBus Topic endpoint to a Digital Twins instance.
            Requires pre-created resource. The instance must be created
            with a managed identity to support identity based endpoint integration

        examples:
        - name: Adds a ServiceBus Topic endpoint to a target instance using Key based auth.
          text: >
            az dt endpoint create servicebus --endpoint-name {endpoint_name}
            --servicebus-resource-group {servicebus_resource_group}
            --servicebus-namespace {servicebus_namespace}
            --servicebus-topic {servicebus_topic_name}
            --servicebus-policy {servicebus_policy}
            -n {instance_name}

        - name: Adds a ServiceBus Topic endpoint to a target instance using Identity based auth.
          text: >
            az dt endpoint create servicebus --endpoint-name {endpoint_name}
            --servicebus-resource-group {servicebus_resource_group}
            --servicebus-namespace {servicebus_namespace}
            --servicebus-topic {servicebus_topic_name}
            -n {instance_name}
    """

    helps["dt endpoint list"] = """
        type: command
        short-summary: List all egress endpoints configured on a Digital Twins instance.

        examples:
        - name: List all egress endpoints configured on an instance.
          text: >
            az dt endpoint list -n {instance_name}
    """

    helps["dt endpoint show"] = """
        type: command
        short-summary: Show details of an endpoint configured on a Digital Twins instance.

        examples:
        - name: Show a desired endpoint by name on an instance.
          text: >
            az dt endpoint show -n {instance_name} --endpoint-name {endpoint_name}
    """

    helps["dt endpoint delete"] = """
        type: command
        short-summary: Remove an endpoint from a Digital Twins instance.

        examples:
        - name: Remove an endpoint from an instance and block until the operation is complete.
          text: >
            az dt endpoint delete -n {instance_name} --endpoint-name {endpoint_name}
        - name: Remove an endpoint from an instance without confirmation or blocking.
          text: >
            az dt endpoint delete -n {instance_name} --endpoint-name {endpoint_name} -y --no-wait
    """

    helps["dt endpoint wait"] = """
        type: command
        short-summary: Wait until an endpoint operation is done.

        examples:
        - name: Wait until an endpoint for an instance is created.
          text: >
            az dt endpoint wait -n {instance_name} --endpoint-name {endpoint_name} --created
        - name: Wait until an existing endpoint is deleted from an instance.
          text: >
            az dt endpoint wait -n {instance_name} --endpoint-name {endpoint_name} --deleted
        - name: Wait until an existing endpoint's primaryConnectionString is null.
          text: >
            az dt endpoint wait -n {instance_name} --endpoint-name {endpoint_name} --custom "properties.primaryConnectionString==null"
    """

    helps["dt network"] = """
        type: group
        short-summary: Manage Digital Twins network configuration including private links and endpoint connections.
    """

    helps["dt network private-link"] = """
        type: group
        short-summary: Manage Digital Twins instance private-link operations.
    """

    helps["dt network private-link show"] = """
        type: command
        short-summary: Show a private-link associated with the instance.

        examples:
        - name: Show the private-link named "API" associated with the instance.
          text: >
            az dt network private-link show -n {instance_name} --link-name API
    """

    helps["dt network private-link list"] = """
        type: command
        short-summary: List private-links associated with the Digital Twins instance.

        examples:
        - name: List all private-links associated with the instance.
          text: >
            az dt network private-link list -n {instance_name}
    """

    helps["dt network private-endpoint"] = """
        type: group
        short-summary: Manage Digital Twins instance private-endpoints.
        long-summary: Use 'az network private-endpoint create' to create a private-endpoint and link to a Digital Twins resource.
    """

    helps["dt network private-endpoint connection"] = """
        type: group
        short-summary: Manage Digital Twins instance private-endpoint connections.
    """

    helps["dt network private-endpoint connection list"] = """
        type: command
        short-summary: List private-endpoint connections associated with the Digital Twins instance.

        examples:
        - name: List all private-endpoint connections associated with the instance.
          text: >
            az dt network private-endpoint connection list -n {instance_name}
    """

    helps["dt network private-endpoint connection show"] = """
        type: command
        short-summary: Show a private-endpoint connection associated with the Digital Twins instance.

        examples:
        - name: Show details of the private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f.
          text: >
            az dt network private-endpoint connection show -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f
    """

    helps["dt network private-endpoint connection set"] = """
        type: command
        short-summary: Set the state of a private-endpoint connection associated with the Digital Twins instance.

        examples:
        - name: Approve a pending private-endpoint connection associated with the instance and add a description.
          text: >
            az dt network private-endpoint connection set -n {instance_name} --cn {connection_name} --status Approved --desc "A description."
        - name: Reject a private-endpoint connection associated with the instance and add a description.
          text: >
            az dt network private-endpoint connection set -n {instance_name} --cn {connection_name} --status Rejected --desc "Does not comply."
    """

    helps["dt network private-endpoint connection delete"] = """
        type: command
        short-summary: Delete a private-endpoint connection associated with the Digital Twins instance.

        examples:
        - name: Delete the private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f with confirmation. Block until finished.
          text: >
            az dt network private-endpoint connection delete -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f

        - name: Delete the private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f no confirmation. Return immediately.
          text: >
            az dt network private-endpoint connection delete -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f -y --no-wait
    """

    helps["dt network private-endpoint connection wait"] = """
        type: command
        short-summary: Wait until an operation on a private-endpoint connection is complete.

        examples:
        - name: Wait until the existing private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f state is updated.
          text: >
            az dt network private-endpoint connection wait -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f --updated

        - name: Wait until the existing private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f is deleted.
          text: >
            az dt network private-endpoint connection wait -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f --deleted
        - name: Wait until the existing private-endpoint connection named ba8408b6-1372-41b2-aef8-af43afc4729f has no actions required in the privateLinkServiceConnectionState property.
          text: >
            az dt network private-endpoint connection wait -n {instance_name} --cn ba8408b6-1372-41b2-aef8-af43afc4729f --custom "properties.privateLinkServiceConnectionState.actionsRequired=='None'"
    """

    helps["dt role-assignment"] = """
        type: group
        short-summary: Manage RBAC role assignments for a Digital Twins instance.
        long-summary: |
            Note that in order to perform role assignments, the logged in principal needs permissions
            such as Owner or User Access Administrator at the assigned scope.

            This command group is provided for convenience. For more complex role assignment scenarios
            use the 'az role assignment' command group.
    """

    helps["dt role-assignment create"] = """
        type: command
        short-summary: Assign a user, group or service principal to a role against a Digital Twins instance.
        long-summary:
            Note that in order to perform role assignments, the logged in principal needs permissions
            such as Owner or User Access Administrator at the assigned scope.

        examples:
        - name: Assign a user (by email) the built-in Digital Twins Owner role against a target instance.
          text: >
            az dt role-assignment create -n {instance_name} --assignee "owneruser@microsoft.com" --role "Azure Digital Twins Data Owner"

        - name: Assign a user (by object Id) the built-in Digital Twins Reader role against a target instance.
          text: >
            az dt role-assignment create -n {instance_name} --assignee "97a89267-0966-4054-a156-b7d86ef8e216" --role "Azure Digital Twins Data Reader"

        - name: Assign a service principal a custom role against a target instance.
          text: >
            az dt role-assignment create -n {instance_name} --assignee {service_principal_name_or_id} --role {role_name_or_id}
    """

    helps["dt role-assignment delete"] = """
        type: command
        short-summary: Remove a user, group or service principal role assignment from a Digital Twins instance.
        long-summary:
            Note that in order to perform role assignments, the logged in principal needs permissions
            such as Owner or User Access Administrator at the assigned scope.

        examples:
        - name: Remove a user from a specific role assignment of a Digital Twins instance.
          text: >
            az dt role-assignment delete -n {instance_name} --assignee "removeuser@microsoft.com" --role "Azure Digital Twins Data Reader"

        - name: Remove a user from all assigned roles of a Digital Twins instance.
          text: >
            az dt role-assignment delete -n {instance_name} --assignee "removeuser@microsoft.com"
    """

    helps["dt role-assignment list"] = """
        type: command
        short-summary: List the existing role assignments of a Digital Twins instance.

        examples:
        - name: List the role assignments on a target instance.
          text: >
            az dt role-assignment list -n {instance_name}

        - name: List the role assignments on a target instance and filter by role.
          text: >
            az dt role-assignment list -n {instance_name} --role {role_name_or_id}
    """

    helps["dt route"] = """
        type: group
        short-summary: Manage and configure event routes.
        long-summary:
            Note that an endpoint must first be configred before adding an event route.
    """

    helps["dt route create"] = """
        type: command
        short-summary: Add an event route to a Digital Twins instance.

        examples:
        - name: Adds an event route for an existing endpoint on target instance with default filter of "true".
          text: >
            az dt route create -n {instance_or_hostname} --endpoint-name {endpoint_name} --route-name {route_name}
        - name: Adds an event route for an existing endpoint on target instance with custom filter.
          text: >
            az dt route create -n {instance_or_hostname} --endpoint-name {endpoint_name} --route-name {route_name}
            --filter "type = 'Microsoft.DigitalTwins.Twin.Create'"
    """

    helps["dt route list"] = """
        type: command
        short-summary: List the configured event routes of a Digital Twins instance.

        examples:
        - name: List configured event routes of a target instance.
          text: >
            az dt route list -n {instance_or_hostname}
    """

    helps["dt route delete"] = """
        type: command
        short-summary: Remove an event route from a Digital Twins instance.

        examples:
        - name: Remove an event route from a target instance.
          text: >
            az dt route delete -n {instance_or_hostname} --route-name {route_name}
    """

    helps["dt route show"] = """
        type: command
        short-summary: Show details of an event route configured on a Digital Twins instance.

        examples:
        - name: Show an event route on a target instance.
          text: >
            az dt route show -n {instance_or_hostname} --route-name {route_name}
    """

    helps["dt twin"] = """
        type: group
        short-summary: Manage and configure the digital twins of a Digital Twins instance.
    """

    helps["dt twin create"] = """
        type: command
        short-summary: Create a digital twin on an instance.
        long-summary: |
                      --properties can be inline JSON or file path.
                      Note: --properties are required for twins that contain components.

        examples:
        - name: Create a digital twin from an existing (prior-created) model.
          text: >
            az dt twin create -n {instance_or_hostname} --dtmi "dtmi:com:example:Room;1"
            --twin-id {twin_id}

        - name: Create a digital twin from an existing (prior-created) model with if-none-match tag.
          text: >
            az dt twin create -n {instance_or_hostname} --dtmi "dtmi:com:example:Room;1"
            --twin-id {twin_id} --if-none-match

        - name: Create a digital twin from an existing (prior-created) model. Instantiate with property values.
          text: >
            az dt twin create -n {instance_or_hostname} --dtmi "dtmi:com:example:DeviceInformation;1"
            --twin-id {twin_id} --properties '{"manufacturer": "Microsoft"}'

        - name: Create a digital twin with component from existing (prior-created) models. Instantiate component with minimum properties.
          text: >
            az dt twin create -n {instance_or_hostname} --dtmi "dtmi:com:example:TemperatureController;1" --twin-id {twin_id} --properties '{
                "Thermostat": {
                    "$metadata": {},
                }
            }'

        - name: Create a digital twin with component from existing (prior-created) models. Instantiate with property values.
          text: >
            az dt twin create -n {instance_or_hostname} --dtmi "dtmi:com:example:TemperatureController;1" --twin-id {twin_id} --properties '{
                "Temperature": 10.2,
                "Thermostat": {
                    "$metadata": {},
                    "setPointTemp": 23.12
                }
            }'
    """

    helps["dt twin update"] = """
        type: command
        short-summary: Update an instance digital twin via JSON patch specification.
        long-summary: Updates to property values and $model elements may happen
                      in the same request. Operations are limited to add, replace and remove.

        examples:
        - name: Update a digital twin via JSON patch specification.
          text: >
            az dt twin update -n {instance_or_hostname} --twin-id {twin_id}
            --json-patch '{"op":"replace", "path":"/Temperature", "value": 20.5}'

        - name: Update a digital twin via JSON patch specification and using etag.
          text: >
            az dt twin update -n {instance_or_hostname} --twin-id {twin_id} --etag {etag}
            --json-patch '{"op":"replace", "path":"/Temperature", "value": 20.5}'

        - name: Update a digital twin via JSON patch specification.
          text: >
            az dt twin update -n {instance_or_hostname} --twin-id {twin_id}
            --json-patch '[
              {"op":"replace", "path":"/Temperature", "value": 20.5},
              {"op":"add", "path":"/Areas", "value": ["ControlSystem"]}
            ]'

        - name: Update a digital twin via JSON patch specification defined in a file.
          text: >
            az dt twin update -n {instance_or_hostname} --twin-id {twin_id}
            --json-patch ./my/patch/document.json
    """

    helps["dt twin show"] = """
        type: command
        short-summary: Show the details of a digital twin.

        examples:
        - name: Show the details of a digital twin.
          text: >
            az dt twin show -n {instance_or_hostname} --twin-id {twin_id}
    """

    helps["dt twin query"] = """
        type: command
        short-summary: Query the digital twins of an instance. Allows traversing relationships and filtering by property values.
        long-summary: In many twin queries, the `$` character is used to reference the `$dtId` property of a twin. In bash-like
          shells or powershell the `$` character has functional meaning and must be escaped as part of the query input. Please review the
          Digital Twins CLI concepts document https://docs.microsoft.com/en-us/azure/digital-twins/concepts-cli for more information.

        examples:
        - name: Query all digital twins in target instance and project all attributes. Also show cost in query units.
          text: >
            az dt twin query -n {instance_or_hostname} -q "select * from digitaltwins" --show-cost

        - name: Query by model and project all attributes.
          text: >
            az dt twin query -n {instance_or_hostname} -q "select * from digitaltwins T where IS_OF_MODEL(T, 'dtmi:com:example:Room;2')"

        - name: Query leveraging `$dtId` with bash compatible syntax
          text: >
            az dt twin query -n {instance_or_hostname} --query-command "SELECT * FROM DigitalTwins T Where T.\\$dtId = 'room0'"

        - name: Query leveraging `$dtId` with powershell compatible syntax
          text: >
            az dt twin query -n {instance_or_hostname} --query-command "SELECT * FROM DigitalTwins T Where T.`$dtId = 'room0'"
    """

    helps["dt twin delete"] = """
        type: command
        short-summary: Remove a digital twin. All relationships referencing this twin must already be deleted.

        examples:
        - name: Remove a digital twin by Id.
          text: >
            az dt twin delete -n {instance_or_hostname} --twin-id {twin_id}

        - name: Remove a digital twin by Id using the etag.
          text: >
            az dt twin delete -n {instance_or_hostname} --twin-id {twin_id} --etag {etag}
    """

    helps["dt twin delete-all"] = """
        type: command
        short-summary: Deletes all digital twins within a Digital Twins instance, including all relationships for those twins.

        examples:
        - name: Delete all digital twins. Any relationships referencing the twins will also be deleted.
          text: >
            az dt twin delete-all -n {instance_or_hostname}
    """

    helps["dt twin relationship"] = """
        type: group
        short-summary: Manage and configure the digital twin relationships of a Digital Twins instance.
    """

    helps["dt twin relationship create"] = """
        type: command
        short-summary: Create a relationship between source and target digital twins.
        long-summary: --properties can be inline JSON or file path.

        examples:
        - name: Create a relationship between two digital twins.
          text: >
            az dt twin relationship create -n {instance_or_hostname} --relationship-id {relationship_id} --relationship contains
            --twin-id {source_twin_id} --target {target_twin_id}

        - name: Create a relationship between two digital twins with if-none-match tag
          text: >
            az dt twin relationship create -n {instance_or_hostname} --relationship-id {relationship_id} --relationship contains
            --twin-id {source_twin_id} --target {target_twin_id} --if-none-match

        - name: Create a relationship with initialized properties between two digital twins.
          text: >
            az dt twin relationship create -n {instance_or_hostname} --relationship-id {relationship_id} --relationship contains
            --twin-id {source_twin_id} --target {target_twin_id}
            --properties '{"ownershipUser": "me", "ownershipDepartment": "Computer Science"}'
    """

    helps["dt twin relationship show"] = """
        type: command
        short-summary: Show details of a digital twin relationship.

        examples:
        - name: Show details of a digital twin relationship.
          text: >
            az dt twin relationship show -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}
    """

    helps["dt twin relationship list"] = """
        type: command
        short-summary: List the relationships of a digital twin.

        examples:
        - name: List outgoing relationships of a digital twin.
          text: >
            az dt twin relationship list -n {instance_or_hostname} --twin-id {twin_id}

        - name: List outgoing relationships of a digital twin and filter on relationship 'contains'
          text: >
            az dt twin relationship list -n {instance_or_hostname} --twin-id {twin_id} --relationship contains

        - name: List incoming relationships of a digital twin.
          text: >
            az dt twin relationship list -n {instance_or_hostname} --twin-id {twin_id} --incoming

        - name: List incoming relationships of a digital twin and filter on relationship 'contains'.
          text: >
            az dt twin relationship list -n {instance_or_hostname} --twin-id {twin_id} --relationship contains --incoming
    """

    helps["dt twin relationship update"] = """
        type: command
        short-summary: Updates the properties of a relationship between two
                          digital twins via JSON patch specification.
        long-summary: Operations are limited to add, replace and remove.

        examples:
        - name: Update a digital twin relationship via JSON patch specification.
          text: >
            az dt twin relationship update -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}
            --relationship contains --json-patch '{"op":"replace", "path":"/Temperature", "value": 20.5}'

        - name: Update a digital twin relationship via JSON patch specification and using etag.
          text: >
            az dt twin relationship update -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}
            --relationship contains --json-patch '{"op":"replace", "path":"/Temperature", "value": 20.5}' --etag {etag}

        - name: Update a digital twin relationship via JSON patch specification.
          text: >
            az dt twin relationship update -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}
            --relationship contains --json-patch '[
              {"op":"replace", "path":"/Temperature", "value": 20.5},
              {"op":"add", "path":"/Areas", "value": ["ControlSystem"]}
            ]'

        - name: Update a digital twin relationship via JSON patch specification defined in a file.
          text: >
            az dt twin relationship update -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}
            --relationship contains --json-patch ./my/patch/document.json
    """

    helps["dt twin relationship delete"] = """
        type: command
        short-summary: Delete a digital twin relationship on a Digital Twins instance.

        examples:
        - name: Delete a digital twin relationship.
          text: >
            az dt twin relationship delete -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id}

        - name: Delete a digital twin relationship using the etag.
          text: >
            az dt twin relationship delete -n {instance_or_hostname} --twin-id {twin_id} --relationship-id {relationship_id} --etag {etag}
    """

    helps["dt twin relationship delete-all"] = """
        type: command
        short-summary: Deletes all digital twin relationships within a Digital Twins instance, including incoming relationships.

        examples:
        - name: Delete all digital twin relationships associated with the twin.
          text: >
            az dt twin relationship delete-all -n {instance_or_hostname} --twin-id {twin_id}

        - name: Delete all digital twin relationships within the Digital Twins instace.
          text: >
            az dt twin relationship delete-all -n {instance_or_hostname}
    """

    helps["dt twin telemetry"] = """
        type: group
        short-summary: Test and validate the event routes and endpoints of a Digital Twins instance.
    """

    helps["dt twin telemetry send"] = """
        type: command
        short-summary: Sends telemetry on behalf of a digital twin. If component path is provided the
                       emitted telemetry is on behalf of the component.

        examples:
        - name: Send twin telemetry
          text: >
            az dt twin telemetry send -n {instance_or_hostname} --twin-id {twin_id}
        - name: Send twin telemetry with a custom telemetry source timestamp and message identifier
          text: >
            az dt twin telemetry send -n {instance_or_hostname} --twin-id {twin_id} --tst {telemetry_source_timestamp} --dt-id {dt_id}
    """

    helps["dt twin component"] = """
        type: group
        short-summary: Show and update the digital twin components of a Digital Twins instance.
    """

    helps["dt twin component show"] = """
        type: command
        short-summary: Show details of a digital twin component.

        examples:
        - name: Show details of a digital twin component
          text: >
            az dt twin component show -n {instance_or_hostname} --twin-id {twin_id} --component Thermostat
    """

    helps["dt twin component update"] = """
        type: command
        short-summary: Update a digital twin component via JSON patch specification.
        long-summary: Updates to property values and $model elements may happen
                      in the same request. Operations are limited to add, replace and remove.

        examples:
        - name: Update a digital twin component via JSON patch specification.
          text: >
            az dt twin component update -n {instance_or_hostname} --twin-id {twin_id} --component {component_path}
            --json-patch '{"op":"replace", "path":"/Temperature", "value": 20.5}'

        - name: Update a digital twin component via JSON patch specification.
          text: >
            az dt twin component update -n {instance_or_hostname} --twin-id {twin_id} --component {component_path}
            --json-patch '[
              {"op":"replace", "path":"/Temperature", "value": 20.5},
              {"op":"add", "path":"/Areas", "value": ["ControlSystem"]}
            ]'

        - name: Update a digital twin component via JSON patch specification defined in a file.
          text: >
            az dt twin component update -n {instance_or_hostname} --twin-id {twin_id} --component {component_path}
            --json-patch ./my/patch/document.json
    """

    helps["dt model"] = """
        type: group
        short-summary: Manage DTDL models and definitions on a Digital Twins instance.
    """

    helps["dt model create"] = """
        type: command
        short-summary: Uploads one or more models. When any error occurs, no models are uploaded.
        long-summary: --models can be inline json or file path. Size of input model set (ontology) is
                      constrained by max number of models which the DT instance can store (default is 10000 models).
                      Please Note: Input model set is chunked and created in batches when it contains more than
                      250 models (API limit). In case of an error processing a batch, the operation gets rolled back.
                      During the rollback all models created in previous batches are deleted one at a time, thereby
                      enforcing atomicity of this operation.

        examples:
        - name: Bulk upload all .json or .dtdl model files from a target directory. Model processing is recursive.
          text: >
            az dt model create -n {instance_or_hostname} --from-directory {directory_path}

        - name: Upload model json inline or from file path.
          text: >
            az dt model create -n {instance_or_hostname} --models {file_path_or_inline_json}
    """

    helps["dt model show"] = """
        type: command
        short-summary: Retrieve a target model or model definition.

        examples:
        - name: Show model meta data
          text: >
            az dt model show -n {instance_or_hostname} --dtmi "dtmi:com:example:Floor;1"

        - name: Show model meta data and definition
          text: >
            az dt model show -n {instance_or_hostname} --dtmi "dtmi:com:example:Floor;1" --definition
    """

    helps["dt model list"] = """
        type: command
        short-summary: List model metadata, definitions and dependencies.

        examples:
        - name: List model metadata
          text: >
            az dt model list -n {instance_or_hostname}

        - name: List model definitions
          text: >
            az dt model list -n {instance_or_hostname} --definition

        - name: List dependencies of particular pre-existing model(s). Space seperate dtmi values.
          text: >
            az dt model list -n {instance_or_hostname} --dependencies-for {model_id0} {model_id1}
    """

    helps["dt model update"] = """
        type: command
        short-summary: Updates the metadata for a model. Currently a model can only be decommisioned.

        examples:
        - name: Decommision a target model
          text: >
            az dt model update -n {instance_or_hostname} --dtmi "dtmi:com:example:Floor;1" --decommission
    """

    helps["dt model delete"] = """
        type: command
        short-summary: Delete a model. A model can only be deleted if no other models reference it.

        examples:
        - name: Delete a target model.
          text: >
            az dt model delete -n {instance_or_hostname} --dtmi "dtmi:com:example:Floor;1"
    """

    helps["dt model delete-all"] = """
        type: command
        short-summary: Delete all models within a Digital Twins instance. Twins configurations are not affected but may be broken without model definitions.

        examples:
        - name: Delete all models.
          text: >
            az dt model delete-all -n {instance_or_hostname}
    """

    helps["dt job"] = """
        type: group
        short-summary: Manage and configure jobs for a digital twin instance.
    """

    helps["dt job import"] = """
        type: group
        short-summary: Manage and configure jobs for importing model, twin and relationships data to a digital twin instance.
    """

    helps["dt job import create"] = """
        type: command
        short-summary: Create and execute a data import job on a digital twin instance.
        long-summary: The command requires an input import data file (in .ndjson format) to be present in the input blob container.
                      Additionally, the DT instance being used must have 'Storage Blob Data Contributor' role set on input storage account.
                      Once the job completes, an output file containing job's logs and errors will be created.

        examples:
        - name: Creates a job for importing data file stored in an Azure Storage Container. Import job's output file is created in the input file's blob container.
          text: >
            az dt job import create -n {instance_or_hostname} --data-file {data_file_name} --input-blob-container {input_blob_container_name}
            --input-storage-account {input_storage_account_name} --output-file {output_file_name}
        - name: Creates a job for importing data file stored in an azure storage container. Import job's output file is created in user-defined storage account and blob container.
          text: >
            az dt job import create -n {instance_or_hostname} --data-file {data_file_name} --input-blob-container {input_blob_container_name}
            --input-storage-account {input_storage_account_name} --output-file {output_file_name} --output-blob-container {output_blob_container_name}
            --output-storage-account {output_storage_account_name}
    """

    helps["dt job import show"] = """
        type: command
        short-summary: Show details of a data import job executed on a digital twins instance

        examples:
        - name: Show details of a data import job by job id.
          text: >
            az dt job import show -n {instance_or_hostname} -j {job_id}
    """

    helps["dt job import list"] = """
        type: command
        short-summary: List all data import jobs executed on a digital twins instance.

        examples:
        - name: List all data import jobs on a target digital twins instance.
          text: >
            az dt job import list -n {instance_or_hostname}
    """

    helps["dt job import delete"] = """
        type: command
        short-summary: Delete a data import job executed on a digital twins instance.

        examples:
        - name: Delete a data import job by job id.
          text: >
            az dt job import delete -n {instance_or_hostname} -j {job_id}
    """
