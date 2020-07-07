# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for PnP commands
"""

from knack.help_files import helps


def load_pnp_help():

    helps["iot pnp"] = """
        type: group
        short-summary: Manage Azure IoT Plug-and-Play repositories and models.
    """

    helps["iot pnp repo"] = """
        type: group
        short-summary: Create and view Azure IoT Plug-and-Play tenant repositories.
    """

    helps["iot pnp repo create"] = """
        type: command
        short-summary: Create a new PnP tenant repository.
        long-summary: |
          Note that this command takes no parameters. The repository will be created in your tenant,
          and the user who creates the repository will be granted the TenantAdministrator role.
    """

    helps["iot pnp repo list"] = """
        type: command
        short-summary: List PnP repositories in your tenant
    """

    helps["iot pnp role-assignment"] = """
        type: group
        short-summary: Manage and configure PnP repository and model role assignments.
    """

    helps["iot pnp role-assignment list"] = """
        type: command
        short-summary: Lists role assignments for a specific tenant or model. Can be filtered by subject-id.

        examples:
        - name: List role assignments for a specific tenant repository
          text: >
            az iot pnp role-assignment list --resource-id {tenant_id} --resource-type Tenant

        - name: List role assignments for a specific model and subject.
          text: >
            az iot pnp role-assignment list --resource-id {model_id}
            --resource-type Model
            --subject-id {user_or_spn_id}
    """

    helps["iot pnp role-assignment create"] = """
        type: command
        short-summary: Creates role assignments for a specific resource and user or service principal.

        examples:
        - name: Assign a user the role of Tenant Administrator
          text: >
            az iot pnp role-assignment create --resource-id {tenant_id}
            --resource-type Tenant
            --role TenantAdministrator
            --subject-id {user_id}
            --subject-type User

        - name: Assign a service principal the role of Model Administrator
          text: >
            az iot pnp role-assignment create --resource-id {tenant_id}
            --resource-type Tenant
            --role ModelAdministrator
            --subject-id {spn_id}
            --subject-type ServicePrincipal
    """

    helps["iot pnp role-assigment delete"] = """
        type: command
        short-summary: Deletes a role assignment for a specific resource and user or service principal

        examples:
        - name: Remove an assigned role for a specific user
          text: >
            az iot pnp role-assignment delete --resource-id {tenant_id}
            --resource-type Tenant
            --role {role}
            --subject-id {user_id}
    """

    helps["iot pnp model"] = """
    type: group
    short-summary: Create, view, and publish device models in your PnP model repository.
    """

    helps["iot pnp model create"] = """
    type: command
    short-summary: Create a new device model in your PnP model repository

    examples:
    - name: Create a new model by uploading a JSON file
      text: >
        az iot pnp model create -m {model_id} --model {path\\to\\definition\\file.json}
    """

    helps["iot pnp model show"] = """
    type: command
    short-summary: View a device model in your PnP model repository

    examples:
    - name: View a model named {dtmi:my:model}
      text: >
        az iot pnp model show --dtmi {dtmi:my:model}
    """

    helps["iot pnp model list"] = """
    type: command
    short-summary: List or search for models in your PnP model repository

    examples:
    - name: List all models in the repository
      text: >
        az iot pnp model list

    - name: Search for all 'Listed' models created by a specific user or spn
      text: >
        az iot pnp model list --state Listed --created-by {user_or_spn_id}

    - name: Search for shared interfaces with name or description matching `{keyword}`
      text: >
        az iot pnp model list -q {keyword} --shared --type Interface
    """

    helps["iot pnp model publish"] = """
    type: command
    short-summary: Publish a device model located in your PnP model repository.

    examples:
    - name: Publish a model named {dtmi:my:model}
      text: >
        az iot pnp model publish --model-id {dtmi:my:model}
    """
