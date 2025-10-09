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
    To create a credential and credential policy, use `--enable-credential-policy` or provide any policy parameters.
    The policy resource name can be customized with the --policy-name argument, but the 'default' credential name cannot be changed.
  examples:
    - name: Create a basic Device Registry namespace
      text: az iot adr ns create -n myNamespace -g myResourceGroup
    - name: Create a Device Registry namespace with credential and default policy
      text: az iot adr ns create -n myNamespace -g myResourceGroup --enable-credential-policy
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
  examples:
    - name: Create a basic policy with a default subject, certificate type (ECC), and validity period.
      text: az iot adr ns policy create -n myPolicy --ns myNamespace -g myResourceGroup
    - name: Create a policy with custom validity period
      text: az iot adr ns policy create -n myPolicy --ns myNamespace -g myResourceGroup --cert-validity-days 30
  """

    helps[
        "iot adr ns policy show"
    ] = """
  type: command
  short-summary: Show a policy for a Device Registry namespace.
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
