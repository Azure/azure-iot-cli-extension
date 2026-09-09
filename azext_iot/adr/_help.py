# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps


def load_adr_help():
    helps["iot adr"] = """
        type: group
        short-summary: Manage Azure Device Registry resources.
    """
    helps["iot adr ns"] = """
        type: group
        short-summary: Manage Device Registry namespaces.
        long-summary: Uses the 2026-04-01 management API.
    """
    helps["iot adr ns create"] = """
        type: command
        short-summary: Create or replace a namespace.
        long-summary: A system-assigned identity is enabled by default.
        examples:
        - name: Create a namespace with a system-assigned identity.
          text: az iot adr ns create -n mynamespace -g mygroup --location centraluseuap
        - name: Create with tags and a simple messaging endpoint.
          text: >
            az iot adr ns create -n mynamespace -g mygroup --tags environment=test
            --messaging-endpoints '{"events":{"address":"https://events.example"}}'
    """
    helps["iot adr ns show"] = """
        type: command
        short-summary: Show a namespace.
        examples:
        - name: Show namespace details.
          text: az iot adr ns show -n mynamespace -g mygroup
    """
    helps["iot adr ns list"] = """
        type: command
        short-summary: List namespaces in a subscription or resource group.
        examples:
        - name: List namespaces in a resource group.
          text: az iot adr ns list -g mygroup
    """
    helps["iot adr ns update"] = """
        type: command
        short-summary: Update namespace tags, system-assigned identity or messaging endpoints.
        long-summary: >
          Omitted properties remain unchanged. Tags and the messaging endpoint map are replaced
          when supplied. Use an empty endpoint object to clear messaging endpoints.
        examples:
        - name: Replace tags without changing other properties.
          text: az iot adr ns update -n mynamespace -g mygroup --tags environment=production
        - name: Load messaging endpoints from a JSON file.
          text: az iot adr ns update -n mynamespace -g mygroup --messaging-endpoints endpoints.json
        - name: Disable the system-assigned identity.
          text: az iot adr ns update -n mynamespace -g mygroup --system-assigned false
    """
    helps["iot adr ns delete"] = """
        type: command
        short-summary: Delete a namespace.
        long-summary: Remove child resources before deleting the namespace.
        examples:
        - name: Delete a namespace without confirmation.
          text: az iot adr ns delete -n mynamespace -g mygroup --yes
    """
    helps["iot adr ns wait"] = """
        type: command
        short-summary: Wait for a namespace to satisfy a condition.
        examples:
        - name: Wait for namespace creation.
          text: az iot adr ns wait -n mynamespace -g mygroup --created
    """
    helps["iot adr ns migrate"] = """
        type: command
        short-summary: Migrate legacy assets into a namespace.
        long-summary: >
          Migrates only the supplied Microsoft.DeviceRegistry/assets resource IDs using the Resources scope.
        examples:
        - name: Migrate a legacy asset.
          text: >
            az iot adr ns migrate -n mynamespace -g mygroup
            --resource-ids /subscriptions/{subscription}/resourceGroups/mygroup/providers/Microsoft.DeviceRegistry/assets/myasset
    """
    helps["iot adr ns identity"] = """
        type: group
        short-summary: Manage a namespace's system-assigned identity.
        long-summary: Only SystemAssigned and None identity types are supported.
    """
    helps["iot adr ns identity show"] = """
        type: command
        short-summary: Show a namespace's identity.
    """
    helps["iot adr ns identity assign"] = """
        type: command
        short-summary: Enable a namespace's system-assigned identity.
        examples:
        - name: Assign the system-assigned identity.
          text: az iot adr ns identity assign -n mynamespace -g mygroup
    """
    helps["iot adr ns identity remove"] = """
        type: command
        short-summary: Disable a namespace's system-assigned identity.
        examples:
        - name: Remove the system-assigned identity.
          text: az iot adr ns identity remove -n mynamespace -g mygroup
    """
    helps["iot adr ns identity wait"] = """
        type: command
        short-summary: Wait for a namespace identity update to complete.
        examples:
        - name: Wait until the namespace identity has been removed.
          text: az iot adr ns identity wait -n mynamespace -g mygroup --custom "identity.type=='None'"
    """
