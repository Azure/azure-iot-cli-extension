# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Help documentation for Azure Device Registry (ADR) namespace commands.
"""

from knack.help_files import helps


def load_adr_help():
    helps[
        "iot adr"
    ] = """
  type: group
  short-summary: Manage Azure Device Registry (ADR) resources.
  """

    helps[
        "iot adr ns"
    ] = """
  type: group
  short-summary: Manage Device Registry namespaces.
  """

    helps[
        "iot adr ns create"
    ] = """
  type: command
  short-summary: Create a Device Registry namespace.
  long-summary: |
    By default, a namespace is created with a system-assigned managed identity.
    To create a credential and credential policy, use `--enable-certificate-management` or provide any policy parameters.
    The policy resource name can be customized with the --policy-name argument, but the 'default' credential name cannot be changed.
  examples:
    - name: Create a basic Device Registry namespace
      text: az iot adr ns create -n myNamespace -g myResourceGroup
    - name: Create a Device Registry namespace with credential and default policy
      text: az iot adr ns create -n myNamespace -g myResourceGroup --enable-certificate-management
    - name: Create a Device Registry namespace with custom credential policy
      text: az iot adr ns create -n myNamespace -g myResourceGroup --policy-name myPolicy --cert-validity-days 30
  """

    helps[
        "iot adr ns show"
    ] = """
  type: command
  short-summary: Show details of a Device Registry namespace.
  examples:
    - name: Show namespace details
      text: az iot adr ns show -n myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns list"
    ] = """
  type: command
  short-summary: List Device Registry namespaces.
  examples:
    - name: List all namespaces in a resource group
      text: az iot adr ns list -g myResourceGroup
    - name: List all namespaces in the subscription
      text: az iot adr ns list
  """

    helps[
        "iot adr ns delete"
    ] = """
  type: command
  short-summary: Delete a Device Registry namespace.
  examples:
    - name: Delete a namespace
      text: az iot adr ns delete -n myNamespace -g myResourceGroup
    - name: Delete a namespace with no confirmation prompt
      text: az iot adr ns delete -n myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns update"
    ] = """
  type: command
  short-summary: Update a Device Registry namespace.
  examples:
    - name: Update namespace tags
      text: az iot adr ns update -n myNamespace -g myResourceGroup --tags key=value
  """

    helps[
        "iot adr ns credential"
    ] = """
  type: group
  short-summary: Manage Device Registry namespace credentials.
  """

    helps[
        "iot adr ns credential create"
    ] = """
  type: command
  short-summary: Create credentials for a Device Registry namespace.
  examples:
    - name: Create default credentials for a namespace
      text: az iot adr ns credential create --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns credential show"
    ] = """
  type: command
  short-summary: Show credentials for a Device Registry namespace.
  examples:
    - name: Show namespace credentials
      text: az iot adr ns credential show --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns credential delete"
    ] = """
  type: command
  short-summary: Delete a credential for a Device Registry namespace.
  examples:
    - name: Delete a namespace credential
      text: az iot adr ns credential delete --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns credential sync"
    ] = """
  type: command
  short-summary: Synchronize Device Registry credentials to linked Iot Hubs
  long-summary: This will create or update an ADR managed certificate in IoT Hubs linked to this Device Registry Namespace.
  examples:
    - name: Synchronize a namespace credential certificate to linked IoT Hubs
      text: az iot adr ns credential sync --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy"
    ] = """
    type: group
    short-summary: Manage Device Registry namespace policies.
  """

    helps[
        "iot adr ns policy create"
    ] = """
  type: command
  short-summary: Create a policy for a Device Registry namespace.
  long-summary: |
    By default, policies use a service-managed CA.
    To use your own CA (Bring Your Own Root), use --enable-byor and then activate the policy with the signed CSR using activate-byor.
  examples:
    - name: Create a basic policy with a default subject, certificate type (ECC), and validity period.
      text: az iot adr ns policy create -n myPolicy --ns myNamespace -g myResourceGroup
    - name: Create a policy with custom validity period
      text: az iot adr ns policy create -n myPolicy --ns myNamespace -g myResourceGroup --cert-validity-days 30
    - name: Create a BYOR (Bring Your Own Root) policy
      text: |
        az iot adr ns policy create -n myPolicy --ns myNamespace -g myResourceGroup --enable-byor
        # After creation, retrieve the CSR from 'policy show' and sign it with your CA,
        # then activate with 'az iot adr ns policy activate-byor'
  """

    helps[
        "iot adr ns policy show"
    ] = """
  type: command
  short-summary: Show a policy for a Device Registry namespace.
  long-summary: |
    For BYOR (Bring Your Own Root) policies, the output includes the certificate signing request (CSR) that needs to be signed by your Certificate Authority.
  examples:
    - name: Show policy details
      text: az iot adr ns policy show -n myPolicy --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy list"
    ] = """
  type: command
  short-summary: List policies for Device Registry namespaces.
  examples:
    - name: List policies for a namespace
      text: az iot adr ns policy list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy delete"
    ] = """
  type: command
  short-summary: Delete a policy for a Device Registry namespace.
  examples:
    - name: Delete a policy
      text: az iot adr ns policy delete -n myPolicy --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy update"
    ] = """
  type: command
  short-summary: Update a policy for a Device Registry namespace.
  examples:
    - name: Update certificate validity period
      text: az iot adr ns policy update -n myPolicy --cert-validity-days 10 --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy revoke-issuer"
    ] = """
  type: command
  short-summary: Revoke the CA certificate for a Device Registry namespace policy.
  long-summary: |
    This command revokes the current CA (issuer) certificate for the policy, triggering the service to generate a new CA certificate. All device credentials issued by the old CA will need to be re-issued. Use this when the CA certificate is compromised or needs rotation.
  examples:
    - name: Revoke the issuer certificate for a policy
      text: az iot adr ns policy revoke-issuer -n myPolicy --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns policy activate-byor"
    ] = """
  type: command
  short-summary: Activate or renew a Bring Your Own Root (BYOR) policy with a signed certificate chain.
  long-summary: |
    This command activates a BYOR policy by uploading the signed certificate chain. Use this after creating a policy with --enable-byor and signing the CSR (from 'policy show') with your CA.

    The certificate chain file must be in PEM format and contain:
    1. The signed certificate (matching the CSR generated by the service)
    2. Any intermediate CA certificates
    3. Optionally, the root CA certificate

    Certificates must be ordered from leaf to root.

    This command is also used for certificate renewal when the BYOR status shows 'ActiveButPendingRenewal'.
  examples:
    - name: Activate a BYOR policy with a signed certificate chain
      text: az iot adr ns policy activate-byor -n myPolicy --ns myNamespace -g myResourceGroup --certificate-chain-file ./signed-chain.pem
  """

    helps[
        "iot adr ns device"
    ] = """
    type: group
    short-summary: Manage Device Registry namespace devices.
  """

    helps[
        "iot adr ns device show"
    ] = """
  type: command
  short-summary: Show a device in a Device Registry namespace.
  examples:
    - name: Show device details
      text: az iot adr ns device show -n myDevice --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns device list"
    ] = """
  type: command
  short-summary: List devices in a Device Registry namespace.
  examples:
    - name: List all devices in a namespace
      text: az iot adr ns device list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns device update"
    ] = """
  type: command
  short-summary: Update a device in a Device Registry namespace.
  examples:
    - name: Disable a device
      text: az iot adr ns device update -n myDevice --ns myNamespace -g myResourceGroup --enabled false
    - name: Update device OS version
      text: az iot adr ns device update -n myDevice --ns myNamespace -g myResourceGroup --os-version "2.0.1"
  """

    helps[
        "iot adr ns device revoke"
    ] = """
  type: command
  short-summary: Revoke credentials for a device in a Device Registry namespace.
  long-summary: |
    This command revokes all active credentials for the specified device. The device will need to re-authenticate and obtain new credentials.

    Use --disable to also prevent the device from obtaining new credentials.
  examples:
    - name: Revoke device credentials
      text: az iot adr ns device revoke -n myDevice --ns myNamespace -g myResourceGroup
    - name: Revoke credentials and disable the device
      text: az iot adr ns device revoke -n myDevice --ns myNamespace -g myResourceGroup --disable
  """
