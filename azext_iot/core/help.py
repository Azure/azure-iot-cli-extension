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

    helps["iot dps certificate generate-verification-code"] = """
type: command
short-summary: Generate a verification code for a certificate in an Azure IoT Hub Device Provisioning Service instance.
long-summary: |
    Use the verification code as the CN of a new certificate signed with the root certificate's private key.
    If --etag is omitted, the current certificate ETag is fetched automatically. This requires certificate read permission.
    Supply --etag to skip the read and operate only on that version. A concurrent change still causes the operation to fail.
    To read an ETag explicitly, use 'az iot dps certificate show --dps-name MyDps -g MyResourceGroup
    --name MyCertificate --query etag -o tsv'.
examples:
  - name: Generate a verification code using the automatically fetched ETag.
    text: >
        az iot dps certificate generate-verification-code --dps-name MyDps -g MyResourceGroup --name MyCertificate
  - name: Generate a verification code using an explicitly supplied ETag.
    text: >
        az iot dps certificate generate-verification-code --dps-name MyDps -g MyResourceGroup
        --name MyCertificate --etag AAAAAAAAAAA=
"""

    helps["iot dps certificate verify"] = """
type: command
short-summary: Verify a certificate in an Azure IoT Hub Device Provisioning Service instance.
long-summary: |
    Upload a verification certificate containing the code returned by generate-verification-code to prove possession.
    If --etag is omitted, the current certificate ETag is fetched automatically. This requires certificate read permission.
    Supply --etag to skip the read and operate only on that version. Use the ETag returned after generating the verification
    code, or read the current ETag with certificate show; an earlier ETag may be stale.
examples:
  - name: Verify a certificate using the automatically fetched ETag.
    text: >
        az iot dps certificate verify --dps-name MyDps -g MyResourceGroup --name MyCertificate
        --path /certificates/Verification.pem
  - name: Verify a certificate using the ETag returned after generating its verification code.
    text: >
        az iot dps certificate verify --dps-name MyDps -g MyResourceGroup --name MyCertificate
        --path /certificates/Verification.pem --etag AAAAAAAAAAA=
"""

    # Resource creation is separate from canonical namespace linking.
    if "iot hub create" in helps:
        helps[
            "iot hub create"
        ] += """
  - name: Create a Standard IoT Hub with a system-assigned identity for later namespace linking.
    text: az iot hub create --resource-group MyResourceGroup --name MyHub --sku S1 --system-assigned-mi
  - name: Create an IoT Hub with the MQTT 5 connection profile.
    text: >
        az iot hub create --resource-group MyResourceGroup --name MyHub --sku S1 --unit 1
        --connection-profile MqttV5 --yes
"""

    # add DPS create examples for ADR properties
    if "iot dps create" in helps:
        helps[
            "iot dps create"
        ] += """
  - name: Create DPS with a system-assigned identity for later namespace linking.
    text: az iot dps create --name MyDps --resource-group MyResourceGroup --system-assigned-mi
  - name: Create DPS with one unit (the default). Units must be an integer of at least 1.
    text: az iot dps create --name MyDps --resource-group MyResourceGroup --unit 1
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
  - name: Explicit capacity edits must retain an integer of at least 1.
    text: az iot dps update --name MyDps --resource-group MyResourceGroup --set sku.capacity=1
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
