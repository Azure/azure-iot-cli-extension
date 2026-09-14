# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help updates for CLI core commands.
"""

from knack.help_files import helps


# Help additions for core commands
def patch_core_help():

    # Resource creation is separate from canonical namespace linking.
    if "iot hub create" in helps:
        helps[
            "iot hub create"
        ] += """
  - name: Create a Standard IoT Hub with a system-assigned identity for later namespace linking.
    text: az iot hub create --resource-group MyResourceGroup --name MyHub --sku S1 --system-assigned-mi
"""

    # add DPS create examples for ADR properties
    if "iot dps create" in helps:
        helps[
            "iot dps create"
        ] += """
  - name: Create DPS with a system-assigned identity for later namespace linking.
    text: az iot dps create --name MyDps --resource-group MyResourceGroup --system-assigned-mi
  - name: Create an Azure IoT Hub Device Provisioning Service with a user-assigned identity
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --user-assigned-mi IdentityResourceId
  - name: Create an Azure IoT Hub Device Provisioning Service with SAS key (local) authentication disabled, requiring Azure RBAC
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --disable-local-auth
"""

    # add DPS update example for local authentication
    if "iot dps update" in helps:
        helps[
            "iot dps update"
        ] += """
  - name: Disable SAS key (local) authentication on an existing Device Provisioning Service, requiring Azure RBAC
    text: >
        az iot dps update --name MyDps --resource-group MyResourceGroup --disable-local-auth
"""

    # add DPS identity help
    helps[
        "iot dps identity"
    ] = """
    type: group
    short-summary: Manage identities of an Azure IoT Hub Device Provisioning Service.
"""

    helps[
        "iot dps identity assign"
    ] = """
    type: command
    short-summary: Assign managed identities to an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Assign a system-assigned identity to an Azure IoT Hub Device Provisioning Service.
      text: az iot dps identity assign --name MyDps --resource-group MyResourceGroup --system
    - name: Assign both a system-assigned and a user-managed identity to an Azure IoT Hub Device Provisioning Service.
      text: az iot dps identity assign --name MyDps --resource-group MyResourceGroup --system --user IdentityResourceId
"""

    helps[
        "iot dps identity remove"
    ] = """
    type: command
    short-summary: Remove managed identities from an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Remove a system-assigned identity from an Azure IoT Hub Device Provisioning Service.
      text: az iot dps identity remove --name MyDps --resource-group MyResourceGroup --system
    - name: Remove a user-managed identity from an Azure IoT Hub Device Provisioning Service.
      text: az iot dps identity remove --name MyDps --resource-group MyResourceGroup --user IdentityResourceId
"""

    helps[
        "iot dps identity show"
    ] = """
    type: command
    short-summary: Show the identity properties of an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: View identity of an Azure IoT Hub Device Provisioning Service.
      text: az iot dps identity show --name MyDps --resource-group MyResourceGroup
"""
