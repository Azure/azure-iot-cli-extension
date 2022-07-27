# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for Device Update commands.
"""

from knack.help_files import helps


def load_deviceupdate_help():

    helps["iot device-update"] = """
        type: group
        short-summary: Device Update for IoT Hub is a service that enables you to deploy over-the-air updates (OTA) for your IoT devices.
        long-summary: As organizations look to further enable productivity and operational efficiency, Internet of Things (IoT) solutions
          continue to be adopted at increasing rates. This makes it essential that the devices forming these solutions are built on a foundation
          of reliability and security and are easy to connect and manage at scale. Device Update for IoT Hub is an end-to-end platform that customers
          can use to publish, distribute, and manage over-the-air updates for everything from tiny sensors to gateway-level devices.

          To learn more about the Device Update for IoT Hub service visit https://docs.microsoft.com/en-us/azure/iot-hub-device-update/
    """

    helps["iot device-update account"] = """
        type: group
        short-summary: Device Update account management.
    """

    helps["iot device-update account create"] = """
        type: command
        short-summary: Create a Device Update account.

        examples:
        - name: Create a Device Update account in target resource group using the resource group location.
          text: >
            az iot device-update account create -n {account_name} -g {resouce_group}

        - name: Create a free sku Device Update account in target resource group with specified location and tags without blocking.
          text: >
            az iot device-update account create -n {account_name} -g {resouce_group} -l westus --tags a=b c=d --sku Free --no-wait

        - name: Create a Device Update account in target resource group with a system managed identity.
          text: >
            az iot device-update account create -n {account_name} -g {resouce_group} --assign-identity [system]

        - name: Create a Device Update account in target resource group with a system managed identity then
                assign the system identity to a single scope with the role of Contributor.
          text: >
            az iot device-update account create -n {account_name} -g {resouce_group} --assign-identity [system]
            --scopes /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount

        - name: Create a Device Update account in target resource group with system and user-assigned managed identities then
                assign the system identity to one or more scopes (space-seperated) with a custom specified role.
          text: >
            az iot device-update account create -n {account_name} -g {resouce_group}
            --assign-identity [system] /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourcegroups/ProResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myIdentity
            --scopes /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount1
              /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount2
            --role "Storage Blob Data Contributor"
    """

    helps["iot device-update account update"] = """
        type: command
        short-summary: Update a Device Update account.
        long-summary: Currently the following account properties can be updated - tags, identity, publicNetworkAccess.

        examples:
        - name: Set a specific account tag attribute.
          text: >
            az iot device-update account update -n {account_name} --set tags.env='test'

        - name: Disable public network access.
          text: >
            az iot device-update account update -n {account_name} --set publicNetworkAccess='Disabled'
    """

    helps["iot device-update account show"] = """
        type: command
        short-summary: Show the details of a Device Update account.

        examples:
        - name: Show a target account.
          text: >
            az iot device-update account show -n {account_name}

        - name: Show a target account filtering on a specific property.
          text: >
            az iot device-update account show -n {account_name} --query identity
    """

    helps["iot device-update account list"] = """
        type: command
        short-summary: List all Device Update accounts in a subscription or resource group.

        examples:
        - name: List all accounts in a subscription.
          text: >
            az iot device-update account list

        - name: List accounts in a subscription that meet filter criteria.
          text: >
            az iot device-update account list --query "[?tags.env == 'test']"

        - name: List all accounts in a resource group.
          text: >
            az iot device-update account list -g {resource_group}
    """

    helps["iot device-update account delete"] = """
        type: command
        short-summary: Delete a Device Update account.

        examples:
        - name: Delete a target account.
          text: >
            az iot device-update account delete -n {account_name}

        - name: Delete a target account without confirmation or blocking.
          text: >
            az iot device-update account delete -n {account_name} -y --no-wait
    """

    helps["iot device-update account wait"] = """
        type: command
        short-summary: Block until a desired account resource state has been met.

        examples:
        - name: Block until an account resource has finished updating.
          text: >
            az iot device-update account wait -n {account_name} -g {resource_group} --updated
    """

    helps["iot device-update account private-link-resource"] = """
        type: group
        short-summary: Device Update account private link resource management.
    """

    helps["iot device-update account private-link-resource list"] = """
        type: command
        short-summary: List private link resources supported by the account.

        examples:
        - name: List account private link resources.
          text: >
            az iot device-update account private-link-resource list -n {account_name}
    """

    helps["iot device-update account private-endpoint-connection"] = """
        type: group
        short-summary: Device Update account private endpoint connection management.
    """

    helps["iot device-update account private-endpoint-connection list"] = """
        type: command
        short-summary: List private endpoint connections associated with a Device Update account.

        examples:
        - name: List all private endpoint connections for a target account.
          text: >
            az iot device-update account private-endpoint-connection list -n {account_name}
    """

    helps["iot device-update account private-endpoint-connection show"] = """
        type: command
        short-summary: Show a private endpoint connection associated with a Device Update account.

        examples:
        - name: Show a private endpoint connection associated with a target account.
          text: >
            az iot device-update account private-endpoint-connection show -n {account_name} --cn {connection_name}
    """

    helps["iot device-update account private-endpoint-connection delete"] = """
        type: command
        short-summary: Delete a private endpoint connection associated with a Device Update account.

        examples:
        - name: Delete a private endpoint connection associated with a target account.
          text: >
            az iot device-update account private-endpoint-connection delete -n {account_name} --cn {connection_name}
    """

    helps["iot device-update account private-endpoint-connection set"] = """
        type: command
        short-summary: Set the state of a private endpoint connection associated with a Device Update account.

        examples:
        - name: Approve a private endpoint connection request on the target account.
          text: >
            az iot device-update account private-endpoint-connection set -n {account_name} --cn {connection_name} --status Approved --desc "For reasons."
    """

    helps["iot device-update instance"] = """
        type: group
        short-summary: Device Update instance management.
    """

    helps["iot device-update instance create"] = """
        type: command
        short-summary: Create a Device Update instance.
    """

    helps["iot device-update instance update"] = """
        type: command
        short-summary: Update a Device Update instance.
        long-summary: Currently the following instance properties can be updated - iotHubs, enableDiagnostics, diagnosticStorageProperties.

        examples:
        - name: Set a specific instance tag attribute.
          text: >
            az iot device-update instance update -n {account_name} -i {instance_name} --set tags.env='test'
    """

    helps["iot device-update instance show"] = """
        type: command
        short-summary: Show a Device Update instance.

        examples:
        - name: Show the details of an instance associated with the target account.
          text: >
            az iot device-update instance show -n {account_name} -i {instance_name}
    """

    helps["iot device-update instance list"] = """
        type: command
        short-summary: List Device Update instances.

        examples:
        - name: List instances associated with the target account.
          text: >
            az iot device-update instance list -n {account_name}
    """

    helps["iot device-update instance delete"] = """
        type: command
        short-summary: Delete a Device Update instance.

        examples:
        - name: Delete an instance associated with the target account.
          text: >
            az iot device-update instance delete -n {account_name} -i {instance_name}
        - name: Delete an instance associated with the target account and skip the confirmation prompt.
          text: >
            az iot device-update instance delete -n {account_name} -i {instance_name} -y
    """

    helps["iot device-update instance wait"] = """
        type: command
        short-summary: Block until a desired instance resource state has been met.

        examples:
        - name: Block until the target instance has been deleted.
          text: >
            az iot device-update instance wait -n {account_name} -i {instance_name} --deleted
    """
