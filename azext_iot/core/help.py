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
  - name: Create a Standard IoT Hub, then link it from a Device Registry namespace.
    text: >
        az iot hub create --resource-group MyResourceGroup --name MyHub --sku S1 --system-assigned-mi;
        az iot adr ns link hub add --namespace MyNamespace --resource-group MyResourceGroup
        --endpoint-name primary --hub-id $(az iot hub show --name MyHub --resource-group
        MyResourceGroup --query id -o tsv) --system-assigned-mi
"""

    # add DPS create examples for ADR properties
    if "iot dps create" in helps:
        helps[
            "iot dps create"
        ] += """
  - name: Create DPS with a system identity, then link it from the namespace.
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --system-assigned-mi;
        az iot adr ns link dps add --namespace MyNamespace --resource-group MyResourceGroup
        --endpoint-name primary --dps-id $(az iot dps show --name MyDps --resource-group
        MyResourceGroup --query id -o tsv) --system-assigned-mi
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
