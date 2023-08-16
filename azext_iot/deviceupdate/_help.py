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

    helps["iot du"] = """
        type: group
        short-summary: Device Update for IoT Hub is a service that enables you to deploy over-the-air updates (OTA) for your IoT devices.
        long-summary: As organizations look to further enable productivity and operational efficiency, Internet of Things (IoT) solutions
          continue to be adopted at increasing rates. This makes it essential that the devices forming these solutions are built on a foundation
          of reliability and security and are easy to connect and manage at scale. Device Update for IoT Hub is an end-to-end platform that customers
          can use to publish, distribute, and manage over-the-air updates for everything from tiny sensors to gateway-level devices.

          To learn more about the Device Update for IoT Hub service visit https://docs.microsoft.com/en-us/azure/iot-hub-device-update/
    """

    helps["iot du account"] = """
        type: group
        short-summary: Device Update account management.
    """

    helps["iot du account create"] = """
        type: command
        short-summary: Create a Device Update account.
        long-summary: This command may also be used to update the state of an existing account.

        examples:
        - name: Create a Device Update account in target resource group using the resource group location.
          text: >
            az iot du account create -n {account_name} -g {resouce_group}

        - name: Create a free sku Device Update account in target resource group with specified location and tags without blocking.
          text: >
            az iot du account create -n {account_name} -g {resouce_group} -l westus --tags a=b c=d --sku Free --no-wait

        - name: Create a Device Update account in target resource group with a system managed identity.
          text: >
            az iot du account create -n {account_name} -g {resouce_group} --assign-identity [system]

        - name: Create a Device Update account in target resource group with a system managed identity then
                assign the system identity to a single scope with the role of Contributor.
          text: >
            az iot du account create -n {account_name} -g {resouce_group} --assign-identity [system]
            --scopes /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount

        - name: Create a Device Update account in target resource group with system and user-assigned managed identities then
                assign the system identity to one or more scopes (space-separated) with a custom specified role.
          text: >
            az iot du account create -n {account_name} -g {resouce_group}
            --assign-identity [system] /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourcegroups/ProResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myIdentity
            --scopes /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount1
              /subscriptions/a12345ea-bb21-994d-2263-c716348e32a1/resourceGroups/ProResourceGroup/providers/Microsoft.Storage/storageAccounts/myStorageAccount2
            --role "Storage Blob Data Contributor"
    """

    helps["iot du account update"] = """
        type: command
        short-summary: Update a Device Update account.
        long-summary: Currently the following account properties can be updated - identity, publicNetworkAccess and tags.

        examples:
        - name: Set a specific account tag attribute.
          text: >
            az iot du account update -n {account_name} --set tags.env='test'

        - name: Disable public network access.
          text: >
            az iot du account update -n {account_name} --set publicNetworkAccess='Disabled'
    """

    helps["iot du account show"] = """
        type: command
        short-summary: Show the details of a Device Update account.

        examples:
        - name: Show a target account.
          text: >
            az iot du account show -n {account_name}

        - name: Show a target account filtering on a specific property.
          text: >
            az iot du account show -n {account_name} --query identity
    """

    helps["iot du account list"] = """
        type: command
        short-summary: List all Device Update accounts in a subscription or resource group.

        examples:
        - name: List all accounts in a subscription.
          text: >
            az iot du account list

        - name: List accounts in a subscription that meet filter criteria.
          text: >
            az iot du account list --query "[?tags.env == 'test']"

        - name: List all accounts in a resource group.
          text: >
            az iot du account list -g {resource_group}
    """

    helps["iot du account delete"] = """
        type: command
        short-summary: Delete a Device Update account.

        examples:
        - name: Delete a target account.
          text: >
            az iot du account delete -n {account_name}

        - name: Delete a target account without confirmation or blocking.
          text: >
            az iot du account delete -n {account_name} -y --no-wait
    """

    helps["iot du account wait"] = """
        type: command
        short-summary: Block until a desired account resource state has been met.

        examples:
        - name: Block until an account resource has finished updating.
          text: >
            az iot du account wait -n {account_name} -g {resource_group} --updated
    """

    helps["iot du account private-link-resource"] = """
        type: group
        short-summary: Device Update account private link resource management.
    """

    helps["iot du account private-link-resource list"] = """
        type: command
        short-summary: List private link resources supported by the account.

        examples:
        - name: List account private link resources.
          text: >
            az iot du account private-link-resource list -n {account_name}
    """

    helps["iot du account private-endpoint-connection"] = """
        type: group
        short-summary: Device Update account private endpoint connection management.
    """

    helps["iot du account private-endpoint-connection list"] = """
        type: command
        short-summary: List private endpoint connections associated with a Device Update account.

        examples:
        - name: List all private endpoint connections for a target account.
          text: >
            az iot du account private-endpoint-connection list -n {account_name}
    """

    helps["iot du account private-endpoint-connection show"] = """
        type: command
        short-summary: Show a private endpoint connection associated with a Device Update account.

        examples:
        - name: Show a private endpoint connection associated with a target account.
          text: >
            az iot du account private-endpoint-connection show -n {account_name} --cn {connection_name}
    """

    helps["iot du account private-endpoint-connection delete"] = """
        type: command
        short-summary: Delete a private endpoint connection associated with a Device Update account.

        examples:
        - name: Delete a private endpoint connection associated with a target account.
          text: >
            az iot du account private-endpoint-connection delete -n {account_name} --cn {connection_name}
    """

    helps["iot du account private-endpoint-connection set"] = """
        type: command
        short-summary: Set the state of a private endpoint connection associated with a Device Update account.

        examples:
        - name: Approve a private endpoint connection request on the target account.
          text: >
            az iot du account private-endpoint-connection set -n {account_name} --cn {connection_name} --status Approved --desc "For reasons."
    """

    helps["iot du instance"] = """
        type: group
        short-summary: Device Update instance management.
    """

    helps["iot du instance create"] = """
        type: command
        short-summary: Create a Device Update instance.
        long-summary: This command may also be used to update the state of an existing instance.

        examples:
        - name: Create an instance with minimum configuration.
          text: >
            az iot du instance create -n {account_name} -i {instance_name} --iothub-ids {iothub_resource_id}

        - name: Create an instance with diagnostics enabled, paired with a user provided storage account. Include tags.
          text: >
            az iot du instance create -n {account_name} -i {instance_name} --iothub-ids {iothub_resource_id} --enable-diagnostics
            --diagnostics-storage-id {storage_account_resource_id} --tags a=b
    """

    helps["iot du instance update"] = """
        type: command
        short-summary: Update a Device Update instance.
        long-summary: Currently the following instance properties can be updated - iotHubs, enableDiagnostics, diagnosticStorageProperties and tags.

        examples:
        - name: Set a specific instance tag attribute.
          text: >
            az iot du instance update -n {account_name} -i {instance_name} --set tags.env='test'

        - name: Enable diagnostics and configure a storage account for log collection.
          text: >
            az iot du instance update -n {account_name} -i {instance_name} --set enableDiagnostics=true
            diagnosticStorageProperties.resourceId={storage_account_resource_id}
    """

    helps["iot du instance show"] = """
        type: command
        short-summary: Show a Device Update instance.

        examples:
        - name: Show the details of an instance associated with the target account.
          text: >
            az iot du instance show -n {account_name} -i {instance_name}
    """

    helps["iot du instance list"] = """
        type: command
        short-summary: List Device Update instances.

        examples:
        - name: List instances associated with the target account.
          text: >
            az iot du instance list -n {account_name}
    """

    helps["iot du instance delete"] = """
        type: command
        short-summary: Delete a Device Update instance.

        examples:
        - name: Delete an instance associated with the target account.
          text: >
            az iot du instance delete -n {account_name} -i {instance_name}
        - name: Delete an instance associated with the target account and skip the confirmation prompt.
          text: >
            az iot du instance delete -n {account_name} -i {instance_name} -y
    """

    helps["iot du instance wait"] = """
        type: command
        short-summary: Block until a desired instance resource state has been met.

        examples:
        - name: Block until the target instance has been deleted.
          text: >
            az iot du instance wait -n {account_name} -i {instance_name} --deleted
    """

    helps["iot du update"] = """
        type: group
        short-summary: Device Update update management.
    """

    helps["iot du update list"] = """
        type: command
        short-summary: List updates that have been imported to the Device Update instance.
        long-summary: When listing update providers only the --by-provider flag needs to be supplied
          in addition to the common instance look up arguments.
          When listing update names the update provider must be supplied.
          When listing update versions the update provider and update name must be supplied.

        examples:
        - name: List all updates.
          text: >
            az iot du update list -n {account_name} -i {instance_name}

        - name: List all updates satisfying a free-text search criteria, in this case the update provider of Contoso.
          text: >
            az iot du update list -n {account_name} -i {instance_name} --search 'Contoso'

        - name: List all updates satisfying an odata filter, in this case filtering for non-deployable updates.
          text: >
            az iot du update list -n {account_name} -i {instance_name} --filter 'isDeployable eq false'

        - name: List all update providers.
          text: >
            az iot du update list -n {account_name} -i {instance_name} --by-provider

        - name: List all update names by update provider.
          text: >
            az iot du update list -n {account_name} -i {instance_name} --update-provider {provider_name}

        - name: List all update versions by update provider and update name.
          text: >
            az iot du update list -n {account_name} -i {instance_name} --update-provider {provider_name} --update-name {update_name}
    """

    helps["iot du update show"] = """
        type: command
        short-summary: Show a specific update version.

        examples:
        - name: Show a specific update with respect to update provider, name and version.
          text: >
            az iot du update show -n {account_name} -i {instance_name} --update-provider {provider_name}
            --update-name {update_name} --update-version {update_version}
    """

    helps["iot du update delete"] = """
        type: command
        short-summary: Delete a specific update version.

        examples:
        - name: Delete a target update with respect to update provider, name and version.
          text: >
            az iot du update delete -n {account_name} -i {instance_name} --update-provider {provider_name}
            --update-name {update_name} --update-version {update_version}
    """

    helps["iot du update file"] = """
        type: group
        short-summary: Update file operations.
    """

    helps["iot du update file list"] = """
        type: command
        short-summary: List update file Ids with respect to update provider, name and version.

        examples:
        - name: List update files with respect to update provider, name and version.
          text: >
            az iot du update file list -n {account_name} -i {instance_name} --update-provider {provider_name}
            --update-name {update_name} --update-version {update_version}
    """

    helps["iot du update file show"] = """
        type: command
        short-summary: Show the details of a specific update file with respect to update provider, name and version.

        examples:
        - name: Show a specific update file with respect to update provider, name and version.
          text: >
            az iot du update file show -n {account_name} -i {instance_name} --update-provider {provider_name}
            --update-name {update_name} --update-version {update_version} --update-file-id {update_file_id}
    """

    helps["iot du update import"] = """
        type: command
        short-summary: Import a new update version into the Device Update instance.
        long-summary: |
          This command supports the `--defer` capability. When used the command will store the
          object payload intended to be sent to Azure in a local cache. The next usage of this command
          without `--defer` will combine the new request payload with the cached objects sending them together.

          Upon success the corresponding local cache entry will be purged. If failure occurs cached
          contents will not be removed. Use `az cache` commands to manage local cache entries independently.

          Defer support is intended primarily for updates with multiple reference steps, such that
          parent and child updates can be submitted together.

        examples:
        - name: Import an update with two related files and no reference steps, explicitly providing
            manifest hash value and manifest size in bytes.
          text: >
            az iot du update import -n {account_name} -i {instance_name} --hashes sha256={hash_value} --size {size_in_bytes}
            --url {manifest_location} --file filename={file1_name} url={file1_url} --file filename={file2_name} url={file2_url}

        - name: Import an update with two related files and no reference steps, letting the CLI calculate the import manifest
            hash value and size in bytes.
          text: >
            az iot du update import -n {account_name} -i {instance_name} --url {manifest_location}
            --file filename={file1_name} url={file1_url} --file filename={file2_name} url={file2_url}

        - name: Import a parent update with two child update reference steps, where all three import manifests have one related file.
            Let the CLI calculate hash value and size in bytes for all. This operation will rely on the `--defer` capability.
          text: >
            az iot du update import -n {account_name} -i {instance_name} --url {parent_manifest_location}
            --file filename={parent_file_name} url={parent_file_url} --defer


            az iot du update import -n {account_name} -i {instance_name} --url {child1_manifest_location}
            --file filename={child1_file_name} url={child1_file_url} --defer


            az iot du update import -n {account_name} -i {instance_name} --url {child2_manifest_location}
            --file filename={child2_file_name} url={child2_file_url}
    """

    helps["iot du device"] = """
        type: group
        short-summary: Device Update device management.
    """

    helps["iot du device class"] = """
        type: group
        short-summary: Device class and device class subgroup management.
        long-summary: A device class describes a set of devices which share a common set of attributes across groups
          while a device class subgroup is a subset of devices in a group that share the same device class id.
          Device classes are created automatically when Device Update-enabled devices are connected to
          the hub.
    """

    helps["iot du device class list"] = """
        type: command
        short-summary: List device classes or device class subgroups.

        examples:
        - name: List device classes within an instance.
          text: >
            az iot du device class list -n {account_name} -i {instance_name}

        - name: List instance device classes filtered by friendly name.
          text: >
            az iot du device class list -n {account_name} -i {instance_name} --filter "friendlyName eq 'my-favorite-class'"

        - name: List device class subgroups for the group.
          text: >
            az iot du device class list -n {account_name} -i {instance_name} --group-id {device_group_id}

        - name: List device class subgroups for the group, filtered by compatProperties/manufacturer.
          text: >
            az iot du device class list -n {account_name} -i {instance_name} --group-id {device_group_id} --filter "compatProperties/manufacturer eq 'Contoso'"
    """

    helps["iot du device class show"] = """
        type: command
        short-summary: Show details about a device class or device class subgroup including installable updates,
          the best update and update compliance.

        examples:
        - name: Show a device class.
          text: >
            az iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id}

        - name: Show installable updates for the device class. This flag modifies the command to returns a list.
          text: >
            az iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id} --installable-updates

        - name: Show a device class subgroup.
          text: >
            az iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id} --group-id {device_group_id}

        - name: Show the best update available for a device class subgroup.
          text: >
            az iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id} --group-id {device_group_id} --best-update

        - name: Show update compliance for a device class subgroup.
          text: >
            az iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id} --group-id {device_group_id} --update-compliance
    """

    helps["iot du device class update"] = """
        type: command
        short-summary: Update a device class.

        examples:
        - name: Update the device class friendly name.
          text: >
            az iot du device class update -n {account_name} -i {instance_name} --class-id {device_class_id} --friendly-name "EU-region"
    """

    helps["iot du device class delete"] = """
        type: command
        short-summary: Delete a device class or device class subgroup.
        long-summary: >
          Device classes are automatically created when Device Update-enabled devices are connected to
          the hub but are not automatically cleaned up since they are referenced by device class subgroups.
          If all device class subgroups for a target device class are deleted then the device class itself can also be deleted
          to remove the records from the system and to stop checking the compatibility of the device class with new
          updates. If a device is ever reconnected its device class will be re-created if it does not exist.

        examples:
        - name: Delete a device class.
          text: >
            az iot du device class delete -n {account_name} -i {instance_name} --class-id {device_class_id}

        - name: Delete a device class and skip the confirmation prompt.
          text: >
            az iot du device class delete -n {account_name} -i {instance_name} --class-id {device_class_id} -y

        - name: Delete a device class subgroup.
          text: >
            az iot du device class delete -n {account_name} -i {instance_name} --class-id {device_class_id} --group-id {device_group_id}
    """

    helps["iot du device group"] = """
        type: group
        short-summary: Device group management.
        long-summary: >
          A device group is a collection of devices. Device groups provide a way to scale deployments to many devices.
          Each device belongs to exactly one device group at a time. A device group is automatically created when a Device Update-enabled
          device is connected to the hub and reports its properties.
    """

    helps["iot du device group list"] = """
        type: command
        short-summary: List device groups within an instance.

        examples:
        - name: List device groups.
          text: >
            az iot du device group list -n {account_name} -i {instance_name}

        - name: List device groups in a desired order, in this case by deviceCount.
          text: >
            az iot du device group list -n {account_name} -i {instance_name} --order-by deviceCount
    """

    helps["iot du device group show"] = """
        type: command
        short-summary: Show details about a device group including the best update and update compliance.

        examples:
        - name: Show a device group.
          text: >
            az iot du device group show -n {account_name} -i {instance_name} --group-id {device_group_id}

        - name: Show the best updates available for a device group. This flag modifies the command to returns a list.
          text: >
            az iot du device group show -n {account_name} -i {instance_name} --group-id {device_group_id} --best-updates

        - name: Show update compliance for a device group.
          text: >
            az iot du device group show -n {account_name} -i {instance_name} --group-id {device_group_id} --update-compliance
    """

    helps["iot du device group delete"] = """
        type: command
        short-summary: Delete a device group.
        long-summary: >
          Device groups are not automatically cleaned up but are retained for history purposes. This operation
          can be used if there is no need for the group or need to retain history for it. If a device is ever connected
          again for a group after the group was deleted it will be automatically re-created with no history.

        examples:
        - name: Delete a device group.
          text: >
            az iot du device group delete -n {account_name} -i {instance_name} --group-id {device_group_id}

        - name: Delete a device group skipping the confirmation prompt.
          text: >
            az iot du device group delete -n {account_name} -i {instance_name} --group-id {device_group_id} -y
    """

    helps["iot du device deployment"] = """
        type: group
        short-summary: Device deployment management.
        long-summary: Deployments will apply a desired compatible update against a target device group distributing the update
          across device classes within the group. Cloud-initiated rollback policy can be optionally configured.
    """

    helps["iot du device deployment create"] = """
        type: command
        short-summary: Create a deployment for a device group. The deployment will be multi-cast against
          every device class subgroup within the target group.

        examples:
        - name: Create a device group deployment scheduled to start immediately (with respect to UTC time).
          text: >
            az iot du device deployment create -n {account_name} -i {instance_name} --group-id {device_group_id} --deployment-id {deployment_id}
            --update-name {update_name} --update-provider {update_provider} --update-version {update_version}

        - name: Create a device group deployment scheduled to start on a desired iso-8601 compliant datetime.
          text: >
            az iot du device deployment create -n {account_name} -i {instance_name} --group-id {device_group_id} --deployment-id {deployment_id}
            --update-name {update_name} --update-provider {update_provider} --update-version {update_version} --start-time "2022-12-20T01:00:00"

        - name: Create a device group deployment scheduled to start immediately with a defined cloud-initiated rollback policy.
            The cloud rollback is initiated when failed count or failed percentage targets are met.
          text: >
            az iot du device deployment create -n {account_name} -i {instance_name} --group-id {device_group_id} --deployment-id {deployment_id}
            --update-name {update_name} --update-provider {update_provider} --update-version {update_version}
            --failed-count 10 --failed-percentage 5 --rollback-update-name {rollback_update_name} --rollback-update-provider {rollback_update_provider}
            --rollback-update-version {rollback_update_version}
    """

    helps["iot du device deployment list"] = """
        type: command
        short-summary: List deployments for a device group or device class subgroup.

        examples:
        - name: List deployments for a device group.
          text: >
            az iot du device deployment list -n {account_name} -i {instance_name} --group-id {device_group_id}

        - name: List deployments for a device group ordering results by startDateTime descending.
          text: >
            az iot du device deployment list -n {account_name} -i {instance_name} --group-id {device_group_id} --order-by "startDateTime desc"

        - name: List deployments for a device class subgroup.
          text: >
            az iot du device deployment list -n {account_name} -i {instance_name} --group-id {device_group_id} --class-id {device_class_id}
    """

    helps["iot du device deployment list-devices"] = """
        type: command
        short-summary: List devices in a device class subgroup deployment along with their state. Useful for getting a list of
          failed devices.

        examples:
        - name: List devices in a device class subgroup deployment.
          text: >
            az iot du device deployment list-devices -n {account_name} -i {instance_name} --group-id {device_group_id}
            --class-id {device_class_id} --deployment-id {deployment_id}

        - name: List devices in a device class subgroup deployment filtering by deviceId and deviceState.
          text: >
            az iot du device deployment list-devices -n {account_name} -i {instance_name} --group-id {device_group_id}
            --class-id {device_class_id} --deployment-id {deployment_id} --filter "deviceId eq 'd0' and deviceState eq 'InProgress'"
    """

    helps["iot du device deployment show"] = """
        type: command
        short-summary: Show a deployment for a device group or device class subgroup including
          status which details a breakdown of how many devices in the deployment are in progress, completed, or failed.

        examples:
        - name: Show a deployment for a device group.
          text: >
            az iot du device deployment show -n {account_name} -i {instance_name} --group-id {device_group_id}
            --deployment-id {deployment_id}

        - name: Show the status of a device group deployment.
          text: >
            az iot du device deployment show -n {account_name} -i {instance_name} --group-id {device_group_id}
            --deployment-id {deployment_id} --status

        - name: Show a deployment for a device class subgroup.
          text: >
            az iot du device deployment show -n {account_name} -i {instance_name} --group-id {device_group_id}
            --class-id {device_class_id} --deployment-id {deployment_id}

        - name: Show the status of a device class subgroup deployment.
          text: >
            az iot du device deployment show -n {account_name} -i {instance_name} --group-id {device_group_id}
            --class-id {device_class_id} --deployment-id {deployment_id} --status
    """

    helps["iot du device deployment cancel"] = """
        type: command
        short-summary: Cancel a device class subgroup deployment.

        examples:
        - name: Cancel the target device class subgroup deployment.
          text: >
            az iot du device deployment cancel -n {account_name} -i {instance_name} --deployment-id {deployment_id}
            --group-id {device_group_id} --class-id {device_class_id}
    """

    helps["iot du device deployment retry"] = """
        type: command
        short-summary: Retry a device class subgroup deployment.

        examples:
        - name: Retry the target device class subgroup deployment.
          text: >
            az iot du device deployment retry -n {account_name} -i {instance_name} --deployment-id {deployment_id}
            --group-id {device_group_id} --class-id {device_class_id}
    """

    helps["iot du device deployment delete"] = """
        type: command
        short-summary: Delete a deployment by device group or device class subgroup.

        examples:
        - name: Delete the target device group deployment.
          text: >
            az iot du device deployment delete -n {account_name} -i {instance_name} --deployment-id {deployment_id}
            --group-id {device_group_id}

        - name: Delete the target device class subgroup deployment.
          text: >
            az iot du device deployment delete -n {account_name} -i {instance_name} --deployment-id {deployment_id}
            --group-id {device_group_id} --class-id {device_class_id}
    """

    helps["iot du device compliance"] = """
        type: group
        short-summary: Instance-view device compliance utilities.
    """

    helps["iot du device compliance show"] = """
        type: command
        short-summary: Gets the breakdown of how many devices are on their latest update, have new updates available,
          or are in progress receiving new updates.

        examples:
        - name: Show device update compliance for an instance.
          text: >
            az iot du device compliance show -n {account_name} -i {instance_name}
    """

    helps["iot du device health"] = """
        type: group
        short-summary: Device health-check utilities.
    """

    helps["iot du device health list"] = """
        type: command
        short-summary: List device health with respect to a target filter.

        examples:
        - name: List healthy devices in an instance.
          text: >
            az iot du device health list -n {account_name} -i {instance_name} --filter "state eq 'Healthy'"

        - name: List unhealthy devices in an instance.
          text: >
            az iot du device health list -n {account_name} -i {instance_name} --filter "state eq 'Unhealthy'"

        - name: Show the health state for a target device.
          text: >
            az iot du device health list -n {account_name} -i {instance_name} --filter "deviceId eq 'd0'"
    """

    helps["iot du device log"] = """
        type: group
        short-summary: Instance log collection management.
    """

    helps["iot du device log collect"] = """
        type: command
        short-summary: Configure a device diagnostics log collection operation on specified devices.

        examples:
        - name: Configure diagnostics log collection for two devices d0 and d1.
          text: >
            az iot du device log collect -n {account_name} -i {instance_name} --log-collection-id {log_collection_id} --description "North-wing device diagnostics"
            --agent-id deviceId=d0 --agent-id deviceId=d1

        - name: Configure diagnostics log collection for a module m0 deployed on device d0.
          text: >
            az iot du device log collect -n {account_name} -i {instance_name} --log-collection-id {log_collection_id} --description "ML module diagnostics"
            --agent-id deviceId=d0 moduleId=m0
    """

    helps["iot du device log list"] = """
        type: command
        short-summary: List instance diagnostic log collection operations.

        examples:
        - name: List diagnostic log collection operations.
          text: >
            az iot du device log list -n {account_name} -i {instance_name}
    """

    helps["iot du device log show"] = """
        type: command
        short-summary: Show a specific instance diagnostic log collection operation.

        examples:
        - name: Show a diagnostic log collection operation.
          text: >
            az iot du device log show -n {account_name} -i {instance_name} --log-collection-id {log_collection_id}
    """

    helps["iot du device module"] = """
        type: group
        short-summary: Device module management.
    """

    helps["iot du device module show"] = """
        type: command
        short-summary: Show a device module identity imported to the instance.

        examples:
        - name: Show a device module identity.
          text: >
            az iot du device module show -n {account_name} -i {instance_name} -d {device_id} -m {module_id}
    """

    helps["iot du device import"] = """
        type: command
        short-summary: Import devices and modules to the Device Update instance from a linked IoT Hub.

        examples:
        - name: Import devices and modules into a target instance.
          text: >
            az iot du device import -n {account_name} -i {instance_name}

        - name: Import only devices.
          text: >
            az iot du device import -n {account_name} -i {instance_name} --import-type Devices

        - name: Import only modules.
          text: >
            az iot du device import -n {account_name} -i {instance_name} --import-type Modules
    """

    helps["iot du device list"] = """
        type: command
        short-summary: List device identities contained within an instance.

        examples:
        - name: List device identities within a target instance.
          text: >
            az iot du device list -n {account_name} -i {instance_name}

        - name: List device identities within a target instance filtering by a desired group Id.
          text: >
            az iot du device list -n {account_name} -i {instance_name} --filter "groupId eq 'myDeviceGroup'"
    """

    helps["iot du device show"] = """
        type: command
        short-summary: Show a device identity contained within an instance.

        examples:
        - name: Show a device identity within a target instance.
          text: >
            az iot du device show -n {account_name} -i {instance_name} -d {device_id}
    """

    helps["iot du update init"] = """
        type: group
        short-summary: Utility for import manifest initialization.
    """

    helps["iot du update init v5"] = """
        type: command
        short-summary: Initialize a v5 import manifest with the desired state.
        long-summary: |
          This command supports all attributes of the v5 import manifest. Note that there is
          positional sensitivity between `--step` and `--file`, as well as `--file` and
          `--related-file`. Review examples and parameter descriptions for details on how
          to fully utilize the operation.

          Read more about using quotation marks and escape characters in different shells here:
            https://aka.ms/aziotcli-json

        examples:
        - name: Initialize a minimum content import manifest. Inline json optimized for `bash`.
          text: >
            az iot du update init v5
            --update-provider Microsoft --update-name myAptUpdate --update-version 1.0.0
            --description "My minimum update"
            --compat manufacturer=Contoso model=Vacuum
            --step handler=microsoft/apt:1 properties='{"installedCriteria": "1.0"}'
            --file path=/my/apt/manifest/file

        - name: Initialize a minimum content import manifest. Inline json optimized for `powershell`.
          text: >
            az iot du update init v5
            --update-provider Microsoft --update-name myAptUpdate --update-version 1.0.0
            --description "My minimum update"
            --compat manufacturer=Contoso model=Vacuum
            --step handler=microsoft/apt:1 properties='{\\"installedCriteria\\": \\"1.0\\"}'
            --file path=/my/apt/manifest/file

        - name: Initialize a minimum content import manifest. Inline json optimized for `cmd`.
          text: >
            az iot du update init v5
            --update-provider Microsoft --update-name myAptUpdate --update-version 1.0.0
            --description "My minimum update"
            --compat manufacturer=Contoso model=Vacuum
            --step handler=microsoft/apt:1 properties=\"{\\"installedCriteria\\": \\"1.0\\"}\"
            --file path=/my/apt/manifest/file

        - name: Initialize a minimum content import manifest. Use file input for json.
          text: >
            az iot du update init v5
            --update-provider Microsoft --update-name myAptUpdate --update-version 1.0.0
            --description "My minimum update"
            --compat manufacturer=Contoso model=Vacuum
            --step handler=microsoft/apt:1 properties="@/path/to/file"
            --file path=/my/apt/manifest/file

        - name: Initialize a non-deployable leaf update to be referenced in a bundled update.
            Inline json optimized for `bash`.
          text: >
            az iot du update init v5
            --update-provider Microsoft --update-name mySwUpdate --update-version 1.1.0
            --compat manufacturer=Contoso model=Microphone
            --step handler=microsoft/swupdate:1 description="Deploy Update" properties='{"installedCriteria": "1.0"}'
            --file path=/my/update/image/file1
            --file path=/my/update/image/file2
            --is-deployable false

        - name: Initialize a bundled update referencing a leaf update as well as defining independent steps. Example
            optimized for `bash` using command continuation to delineate import manifest segments.
          text: |
            az iot du update init v5 \\
            --update-provider Microsoft --update-name myBundled --update-version 2.0 \\
            --compat manufacturer=Contoso model=SpaceStation \\
            --step handler=microsoft/script:1 properties='{"arguments": "--pre"}' description="Pre-install script" \\
            --file path=/my/update/scripts/preinstall.sh downloadHandler=microsoft/delta:1 \\
            --related-file path=/my/update/scripts/related_preinstall.json properties='{"microsoft.sourceFileHashAlgorithm": "sha256"}' \\
            --step updateId.provider=Microsoft updateId.name=SwUpdate updateId.version=1.1 \\
            --step handler=microsoft/script:1 properties='{"arguments": "--post"}' description="Post-install script" \\
            --file path=/my/update/scripts/postinstall.sh
    """

    helps["iot du update calculate-hash"] = """
        type: command
        short-summary: Calculate the base64 hashed representation of a file.

        examples:
        - name: Calculate the base64 representation of a sha256 digest for a target update file.
          text: >
            az iot du update calculate-hash --file-path /path/to/file

        - name: Calculate the base64 representation of a sha256 digest for multiple target update files.
          text: >
            az iot du update calculate-hash
            --file-path /path/to/file1
            --file-path /path/to/file2
            --file-path /path/to/file3
    """

    helps["iot du update stage"] = """
        type: command
        short-summary: Stage an update for import to a target instance.
        long-summary: |
          Staging an update refers to accelerating the pre-requisite steps
          of importing an update to a target instance. For a given import manifest, the process
          will determine relevant files, push them to a desired storage container,
          generate SAS URIs and cover other preparation steps for a succesful import.

          This command depends on a convention based organization of update files. All update files
          for a target manifest are expected to be in the same directory the import manifest resides in.

          Key based access is used to upload blob artifacts and to generate 3 hour duration SAS URIs with read access.

          If `--then-import` flag is provided, the command will import the staged update. Otherwise
          the result of this operation is an import command to run to achieve the same result at a later time.

          This command will purge and refresh any local cache entry for the target instance.

        examples:
        - name: Stage a stand-alone update. Update files are expected to reside in the same directory
            as the manifest. The resultant import command can be executed at a later time to initiate the
            import of the staged update prior to SAS token expiration.
          text: >
            az iot du update stage -n {account_name} -i {instance_name} --storage-account {storage_account_name}
            --storage-container {storage_container_name} --manifest-path /path/to/manifest.json

        - name: Stage a stand-alone update. After staging, import the update to the instance using a desired friendly
            name.
          text: >
            az iot du update stage -n {account_name} -i {instance_name} --storage-account {storage_account_name}
            --storage-container {storage_container_name} --manifest-path /path/to/manifest.json --then-import
            --friendly-name myAptUpdate

        - name: Stage a multi-reference update. Update files will be uploaded to a storage blob container
            residing in a different subscription to the update account.
          text: >
            az iot du update stage -n {account_name} -i {instance_name} --storage-account {storage_account_name}
            --storage-container {storage_container_name} --storage-subscription {storage_account_subscription}
            --manifest-path /path/to/parent/parent.manifest.json --manifest-path /path/to/leaf1/leaf1.manifest.json
            --manifest-path /path/to/leaf2/leaf2.manifest.json

        - name: Stage a multi-reference update, overwriting existing blobs if they exist. After staging,
            import the update to the instance.
          text: >
            az iot du update stage -n {account_name} -i {instance_name} --storage-account {storage_account_name}
            --storage-container {storage_container_name} --manifest-path /path/to/parent/parent.manifest.json
            --manifest-path /path/to/leaf1/leaf1.manifest.json --manifest-path /path/to/leaf2/leaf2.manifest.json
            --then-import --overwrite
    """
