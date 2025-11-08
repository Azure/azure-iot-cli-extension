# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help updates for CLI core commands.
"""

from knack.help_files import helps


# TODO - CMS Preview - help additions to core
def patch_core_help():

    # add Hub create examples for ADR properties
    if "iot hub create" in helps:
        helps[
            "iot hub create"
        ] += """
  - name: Create a Generation2 IoT Hub with Device Registry namespace properties.
    text: >
        az iot hub create --resource-group MyResourceGroup --name MyHub --sku GEN2 --ns-resource-id NamespaceResourceId
        --ns-identity-id UserIdentityResourceId
  - name: Create a Generation2 IoT Hub with Device Registry namespace properties and custom role assignment.
    text: >
        az iot hub create --resource-group MyResourceGroup --name MyHub --sku GEN2 --ns-resource-id NamespaceResourceId
        --ns-identity-id UserIdentityResourceId --custom-ns-role-id RoleResourceId
  - name: Create a Generation2 IoT Hub with Device Registry namespace properties and skip role assignment.
    text: >
        az iot hub create --resource-group MyResourceGroup --name MyHub --sku GEN2 --ns-resource-id NamespaceResourceId
        --ns-identity-id UserIdentityResourceId --skip-ns-ra
"""

    # add DPS create examples for ADR properties
    if "iot dps create" in helps:
        helps[
            "iot dps create"
        ] += """
  - name: Create an Azure IoT Hub Device Provisioning Service with system identity and Device Registry namespace properties
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --mi-system-assigned --ns-resource-id NamespaceResourceId
  - name: Create an Azure IoT Hub Device Provisioning Service with user-managed identity and Device Registry namespace properties
    text: >
        az iot dps create --name MyDps --resource-group MyResourceGroup --mi-user-assigned IdentityResourceId
        --ns-resource-id NamespaceResourceId --ns-identity-id IdentityResourceId
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
