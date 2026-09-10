# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Help documentation for Azure Device Registry (ADR) namespace commands.
"""

from knack.help_files import helps
from azext_iot.adr.rbac import format_role_requirements


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
    A new namespace is created with a system-assigned managed identity by default.
    Observability is disabled by default for a new namespace. This command does not
    accept observability endpoint input. Re-running create for an existing namespace
    preserves its complete observability configuration.
  examples:
    - name: Create a basic Device Registry namespace
      text: az iot adr ns create -n myNamespace -g myResourceGroup
    - name: Create a Device Registry namespace with system-assigned outbound identity
      text: az iot adr ns create -n myNamespace -g myResourceGroup --outbound-system-assigned-mi
    - name: Create a namespace with a user-assigned outbound identity
      text: |
        az iot adr ns create -n myNamespace -g myResourceGroup \\
          --outbound-user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<id>
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
        "iot adr ns migrate"
    ] = """
  type: command
  short-summary: Migrate legacy assets into a Device Registry namespace.
  long-summary: |
    Migrates existing Microsoft.DeviceRegistry/assets resources into the
    namespace. The response reports success or failure for each resource ID.
  examples:
    - name: Migrate legacy assets into a namespace
      text: |
        az iot adr ns migrate -n myNamespace -g myResourceGroup \\
          --resource-ids /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DeviceRegistry/assets/asset1
  """

    helps[
        "iot adr ns update"
    ] = """
  type: command
  short-summary: Update a Device Registry namespace.
  long-summary: |
    Observability can only be enabled or disabled when the namespace already has a
    service-configured observability endpoint. The existing endpoint configuration
    is preserved. Raw observability endpoint input is not accepted by this command.
  examples:
    - name: Update namespace tags
      text: az iot adr ns update -n myNamespace -g myResourceGroup --tags key=value
    - name: Disable namespace observability
      text: az iot adr ns update -n myNamespace -g myResourceGroup --observability-enabled false
    - name: Switch outbound identity to system-assigned managed identity
      text: az iot adr ns update -n myNamespace -g myResourceGroup --outbound-system-assigned-mi
    - name: Switch outbound identity to a user-assigned managed identity
      text: |
        az iot adr ns update -n myNamespace -g myResourceGroup \\
          --outbound-user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<id>
    - name: Clear the explicit outbound identity and use the namespace default
      text: az iot adr ns update -n myNamespace -g myResourceGroup --outbound-system-assigned-mi false
  """

    helps[
        "iot adr ns ca"
    ] = """
  type: group
  short-summary: Manage certificate authorities for a Device Registry namespace.
  """

    helps[
        "iot adr ns ca create"
    ] = """
  type: command
  short-summary: Create a certificate authority for a Device Registry namespace.
  long-summary: |
    The certificate authority type determines the required associated properties:
    - Root: a service-managed self-signed root CA.
    - ICA with a Microsoft issuer: signed by a root CA in the same namespace. Pass the issuing
      CA's name with --issuer-ca-name.
    - ICA with an External issuer: signed by an external PKI. After creation the service returns
      a CSR; sign it and complete activation with 'az iot adr ns ca activate'.
  examples:
    - name: Create a service-managed root certificate authority
      text: az iot adr ns ca create -n myRootCA --ns myNamespace -g myResourceGroup --type Root
    - name: Create a Microsoft-issued intermediate certificate authority
      text: |
        az iot adr ns ca create -n myMicrosoftICA --ns myNamespace -g myResourceGroup \\
          --type ICA --issuer-type Microsoft --issuer-ca-name myRootCA
    - name: Create an externally issued intermediate certificate authority
      text: |
        az iot adr ns ca create -n myExternalICA --ns myNamespace -g myResourceGroup \\
          --type ICA --issuer-type External
  """

    helps[
        "iot adr ns ca show"
    ] = """
  type: command
  short-summary: Show a certificate authority for a Device Registry namespace.
  examples:
    - name: Show a certificate authority
      text: az iot adr ns ca show -n myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca list"
    ] = """
  type: command
  short-summary: List the certificate authorities for a Device Registry namespace.
  examples:
    - name: List certificate authorities
      text: az iot adr ns ca list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca update"
    ] = """
  type: command
  short-summary: Update a certificate authority for a Device Registry namespace.
  examples:
    - name: Update certificate authority tags
      text: az iot adr ns ca update -n myCA --ns myNamespace -g myResourceGroup --tags env=prod
  """

    helps[
        "iot adr ns ca delete"
    ] = """
  type: command
  short-summary: Delete a certificate authority from a Device Registry namespace.
  examples:
    - name: Delete a certificate authority
      text: az iot adr ns ca delete -n myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca activate"
    ] = """
  type: command
  short-summary: Activate an externally issued intermediate certificate authority.
  long-summary: |
    Use this after creating an ICA with --issuer-type External and signing the service-generated
    CSR with your external PKI. The certificate chain file must be in PEM
    format with certificates ordered from leaf to root.
  examples:
    - name: Activate an externally issued ICA
      text: az iot adr ns ca activate -n myExternalICA --ns myNamespace -g myResourceGroup --certificate-chain-file ./signed-chain.pem
  """

    helps[
        "iot adr ns ca revoke"
    ] = """
  type: command
  short-summary: Revoke and rotate an intermediate certificate authority issued by a Microsoft CA.
  long-summary: |
    Applies only to an ICA whose issuerType is 'Microsoft'. The service revokes the current
    certificate and issues a replacement signed by the same root CA.
  examples:
    - name: Revoke a certificate authority
      text: az iot adr ns ca revoke -n myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca wait"
    ] = """
  type: command
  short-summary: Wait for a certificate authority to reach a desired state.
  long-summary: Without an explicit wait predicate, waits for provisioningState Succeeded.
  examples:
    - name: Wait until certificate authority provisioning succeeds
      text: az iot adr ns ca wait -n myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca policy"
    ] = """
  type: group
  short-summary: Manage certificate policies for a certificate authority.
  long-summary: |
    A certificate policy carries the leaf certificate issuance settings for a certificate authority.
  """

    helps[
        "iot adr ns ca policy create"
    ] = """
  type: command
  short-summary: Create a certificate policy for a certificate authority.
  long-summary: |
    Certificate policies can only be created under an issuing certificate
    authority with type ICA. Create the ICA under a Root CA, then pass the ICA
    name to --ca-name. The leaf certificate validity period must be between 7
    and 90 days, inclusive. During the current preview rollout, Central US EUAP
    may reject values below 30 days even though the contract allows them.
  examples:
    - name: Create a certificate policy with a 30 day leaf certificate validity period
      text: az iot adr ns ca policy create -n myPolicy --ca-name myICA --ns myNamespace -g myResourceGroup --validity-days 30
  """

    helps[
        "iot adr ns ca policy show"
    ] = """
  type: command
  short-summary: Show a certificate policy for a certificate authority.
  examples:
    - name: Show a certificate policy
      text: az iot adr ns ca policy show -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca policy list"
    ] = """
  type: command
  short-summary: List the certificate policies for a certificate authority.
  examples:
    - name: List certificate policies
      text: az iot adr ns ca policy list --ca-name myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca policy update"
    ] = """
  type: command
  short-summary: Update a certificate policy for a certificate authority.
  long-summary: |
    When supplied, the leaf certificate validity period must be between 7 and
    90 days, inclusive.
  examples:
    - name: Update certificate policy tags
      text: az iot adr ns ca policy update -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup --tags env=prod
    - name: Update leaf certificate validity to the maximum supported period
      text: az iot adr ns ca policy update -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup --validity-days 90
  """

    helps[
        "iot adr ns ca policy delete"
    ] = """
  type: command
  short-summary: Delete a certificate policy from a certificate authority.
  examples:
    - name: Delete a certificate policy
      text: az iot adr ns ca policy delete -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns ca policy wait"
    ] = """
  type: command
  short-summary: Wait for a certificate policy to reach a desired state.
  long-summary: Without an explicit wait predicate, waits for provisioningState Succeeded.
  examples:
    - name: Wait until certificate policy provisioning succeeds
      text: az iot adr ns ca policy wait -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns wait"
    ] = """
  type: command
  short-summary: Wait for a Device Registry namespace to reach a desired state.
  long-summary: Without an explicit wait predicate, waits for provisioningState Succeeded.
  examples:
    - name: Wait until namespace provisioning succeeds
      text: az iot adr ns wait -n myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link"
    ] = """
  type: group
  short-summary: Manage links between a Device Registry namespace and downstream resources.
  long-summary: |
    Links live on the namespace, not on the linked IoT Hub, DPS, or Update Instance.
    Add and update use namespace PATCH. Destructive delete removes the linked Azure
    resource first and then uses the generated namespace replacement operation because
    this API exposes no narrow endpoint remove.
  """

    helps[
        "iot adr ns link hub"
    ] = """
  type: group
  short-summary: Manage IoT Hub links (messaging endpoints) on a Device Registry namespace.
  long-summary: |
    A namespace must have a linked DPS before a new Hub can be linked or a failed
    Hub link can be retried (DPS-first ordering). A successfully linked Hub remains
    operational and updateable after DPS deletion. Links live on the namespace,
    not on the IoT Hub resource.
  """

    helps[
        "iot adr ns link hub add"
    ] = f"""
  type: command
  short-summary: Link an IoT Hub to a Device Registry namespace.
  long-summary: |
    Adds a Hub messaging endpoint entry under the namespace's properties.messaging.endpoints.
    Requires the namespace to already have at least one linked DPS (DPS-first ordering).
    --system-assigned-mi and --user-assigned-mi are optional. When supplied, exactly one may be
    used to set the inbound caller identity that the Hub will use to call back into the namespace.
    Required service-to-service roles: {format_role_requirements("hub")}.
    The command reuses inherited assignments and automatically creates only missing assignments
    when the signed-in principal is inherited Owner or User Access Administrator. Otherwise it
    stops before namespace mutation and prints exact remediation commands. A newly created
    assignment must become visible within the 180-second preflight deadline before PATCH.
    IoT Hub Data
    Contributor is canonical for this implementation; final service-owner confirmation remains
    an external product decision.
  examples:
    - name: Link a Hub using the Hub's system-assigned identity for inbound calls
      text: |
        az iot adr ns link hub add -n primary --ns myNamespace -g myResourceGroup \\
          --hub-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/IotHubs/<hub> \\
          --system-assigned-mi
    - name: Link a Hub without configuring an inbound caller identity
      text: |
        az iot adr ns link hub add -n primary --ns myNamespace -g myResourceGroup \\
          --hub-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/IotHubs/<hub>
    - name: Link a Hub with a user-assigned identity and custom availability/weight
      text: |
        az iot adr ns link hub add -n secondary --ns myNamespace -g myResourceGroup \\
          --hub-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/IotHubs/<hub> \\
          --user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<id> \\
          --availability Available --allocation-weight 1
  """

    helps[
        "iot adr ns link hub update"
    ] = """
  type: command
  short-summary: Update an existing IoT Hub messaging endpoint on a Device Registry namespace.
  long-summary: |
    Only the inbound caller identity can be updated. The linked Hub resource and provisioning
    settings cannot be changed in place. Retrying an endpoint whose linkingState is Failed
    requires a linked DPS. An endpoint whose linkingState is Succeeded remains updateable
    after DPS deletion. Before PATCH, update repeats add's target existence, region,
    provisioning-state, Standard SKU, selected identity attachment, namespace outbound
    principal, and automatic RBAC preflight. Newly created assignments must become visible
    before namespace mutation.
  examples:
    - name: Switch a Hub link to a system-assigned identity
      text: az iot adr ns link hub update -n primary --ns myNamespace -g myResourceGroup --system-assigned-mi
  """

    helps[
        "iot adr ns link hub show"
    ] = """
  type: command
  short-summary: Show a single IoT Hub messaging endpoint on a Device Registry namespace.
  examples:
    - name: Show a Hub link by endpoint name
      text: az iot adr ns link hub show -n primary --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link hub list"
    ] = """
  type: command
  short-summary: List IoT Hub messaging endpoints on a Device Registry namespace.
  examples:
    - name: List all Hub links on a namespace
      text: az iot adr ns link hub list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link hub delete"
    ] = """
  type: command
  short-summary: Permanently delete a linked IoT Hub and update the namespace.
  long-summary: |
    Permanently deletes the actual IoT Hub resource referenced by the named link,
    then removes that messaging endpoint from the Device Registry namespace. Role
    assignments are not deleted. Immediately before namespace replacement, the command
    re-reads the namespace, preserves its latest unrelated state, and aborts if the named
    endpoint was repointed. The generated API exposes no ETag/If-Match for this replacement,
    so a narrower race after that final read cannot be eliminated. This operation cannot
    be undone.
  examples:
    - name: Delete the linked IoT Hub and update the namespace without prompting
      text: az iot adr ns link hub delete -n primary --ns myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns link hub wait"
    ] = """
  type: command
  short-summary: Wait for an IoT Hub endpoint to link successfully.
  long-summary: |
    The endpoint name is required. Without an explicit wait predicate, this command
    polls that endpoint's linkingState and fails immediately if it reaches Failed.
  examples:
    - name: Wait until a Hub endpoint reaches linkingState Succeeded
      text: az iot adr ns link hub wait -n primary --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link dps"
    ] = """
  type: group
  short-summary: Manage DPS links (provisioning endpoints) on a Device Registry namespace.
  long-summary: |
    Only one DPS may be linked per namespace today. Links live on the namespace, not on the
    DPS resource; there is no per-DPS unlink API.
  """

    helps[
        "iot adr ns link dps add"
    ] = f"""
  type: command
  short-summary: Link a Device Provisioning Service (DPS) to a Device Registry namespace.
  long-summary: |
    Adds a DPS provisioning endpoint entry under the namespace's properties.provisioning.endpoints.
    Rejected if the namespace already has a linked DPS (one DPS per namespace).
    Exactly one of --system-assigned-mi or --user-assigned-mi must be provided.
    Required service-to-service roles: {format_role_requirements("dps")}.
    The command reuses inherited assignments and automatically creates only missing assignments
    when the signed-in principal is inherited Owner or User Access Administrator. Otherwise it
    stops before namespace mutation and prints exact remediation commands. A newly created
    assignment must become visible within the 180-second preflight deadline before PATCH.
  examples:
    - name: Link a DPS using the DPS resource's system-assigned identity
      text: |
        az iot adr ns link dps add -n primary --ns myNamespace -g myResourceGroup \\
          --dps-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/provisioningServices/<dps> \\
          --system-assigned-mi
    - name: Link a DPS with a user-assigned identity
      text: |
        az iot adr ns link dps add -n primary --ns myNamespace -g myResourceGroup \\
          --dps-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/provisioningServices/<dps> \\
          --user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<id>
  """

    helps[
        "iot adr ns link dps update"
    ] = """
  type: command
  short-summary: Update an existing DPS provisioning endpoint on a Device Registry namespace.
  long-summary: |
    Only the inbound caller identity may be updated. The linked DPS resource cannot be changed
    in place. Before PATCH, update repeats add's target existence, region,
    provisioning-state, selected identity attachment, namespace outbound principal,
    automatic RBAC, and assignment-visibility preflight.
  examples:
    - name: Rotate to a system-assigned identity on an existing DPS link
      text: az iot adr ns link dps update -n primary --ns myNamespace -g myResourceGroup --system-assigned-mi
  """

    helps[
        "iot adr ns link dps show"
    ] = """
  type: command
  short-summary: Show a single DPS provisioning endpoint on a Device Registry namespace.
  long-summary: |
    Projects the named endpoint and, when the linked DPS is accessible, includes a
    read-only 'brownfieldHubs' list (the DPS resource's existing properties.iotHubs[]).
    The brownfield list is informational so you can decide which Hubs to subsequently link
    to the namespace.
  examples:
    - name: Show a DPS link by endpoint name (with brownfield Hubs when accessible)
      text: az iot adr ns link dps show -n primary --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link dps list"
    ] = """
  type: command
  short-summary: List DPS provisioning endpoints on a Device Registry namespace.
  examples:
    - name: List all DPS links on a namespace
      text: az iot adr ns link dps list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link dps delete"
    ] = """
  type: command
  short-summary: Permanently delete a linked DPS and update the namespace.
  long-summary: |
    Permanently deletes the actual Device Provisioning Service resource referenced
    by the named link, then removes that provisioning endpoint from the Device
    Registry namespace. Hub links do not block this command. Role assignments are
    not deleted. Successfully linked Hubs remain operational and updateable, but
    adding a new Hub or retrying a failed Hub requires linking another DPS first.
    The namespace is re-read immediately before replacement; latest unrelated state
    is preserved and a repointed endpoint causes an abort. The generated API has no
    ETag/If-Match, so a narrower post-read race remains. This operation cannot be undone.
  examples:
    - name: Delete the linked DPS and update the namespace without prompting
      text: az iot adr ns link dps delete -n primary --ns myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns link dps wait"
    ] = """
  type: command
  short-summary: Wait for a DPS endpoint to link successfully.
  long-summary: |
    The endpoint name is required. Without an explicit wait predicate, this command
    polls that endpoint's linkingState and fails immediately if it reaches Failed.
  examples:
    - name: Wait until a DPS endpoint reaches linkingState Succeeded
      text: az iot adr ns link dps wait -n primary --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link su"
    ] = """
  type: group
  short-summary: Manage Software Updates links (updating endpoints) on a Device Registry namespace.
  long-summary: |
    Links a 'Microsoft.DeviceUpdate/updateInstances' resource to the namespace as an
    updating endpoint under properties.updating.endpoints. Links live on the namespace, not on
    the Update Instance. Only one Software Updates instance may be linked per namespace.
    Linking is asynchronous; read-only address fields (serviceAddress, deviceAddress,
    legacyDeviceAddress) are resolved once linking succeeds.
  """

    helps[
        "iot adr ns link su add"
    ] = f"""
  type: command
  short-summary: Link an Update Instance to a Device Registry namespace.
  long-summary: |
    Adds a Software Updates updating endpoint entry under the namespace's properties.updating.endpoints.
    Only one Software Updates instance may be linked per namespace. If one is already
    linked, use 'link su update' to modify it or destructive 'link su delete' to replace it.
    Exactly one of --system-assigned-mi or --user-assigned-mi must be provided to set the
    inbound caller identity that the update instance will use to call back into the namespace.
    Required service-to-service roles: {format_role_requirements("su")}.
    Missing assignments are created only for an inherited Owner or User Access Administrator.
    A newly created assignment must become visible within the 180-second preflight deadline
    before PATCH. This link workflow never grants the signed-in user Software Updates content roles.
  examples:
    - name: Link an Update Instance using its system-assigned identity for inbound calls
      text: |
        az iot adr ns link su add -n my-su --ns myNamespace -g myResourceGroup \\
          --su-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DeviceUpdate/updateInstances/<instance> \\
          --system-assigned-mi
    - name: Link an Update Instance with a user-assigned identity
      text: |
        az iot adr ns link su add -n my-su --ns myNamespace -g myResourceGroup \\
          --su-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DeviceUpdate/updateInstances/<instance> \\
          --user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<id>
  """

    helps[
        "iot adr ns link su update"
    ] = """
  type: command
  short-summary: Update an existing Software Updates updating endpoint on a Device Registry namespace.
  long-summary: |
    Only the inbound caller identity may be updated. The linked update instance cannot be changed
    in place. Before PATCH, update repeats add's target existence, region,
    provisioning-state, selected identity attachment, namespace outbound principal,
    automatic RBAC, and assignment-visibility preflight.
  examples:
    - name: Rotate to a system-assigned identity on an existing Software Updates link
      text: az iot adr ns link su update -n my-su --ns myNamespace -g myResourceGroup --system-assigned-mi
  """

    helps[
        "iot adr ns link su show"
    ] = """
  type: command
  short-summary: Show a single Software Updates updating endpoint on a Device Registry namespace.
  examples:
    - name: Show a Software Updates link by endpoint name
      text: az iot adr ns link su show -n my-su --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link su list"
    ] = """
  type: command
  short-summary: List Software Updates updating endpoints on a Device Registry namespace.
  examples:
    - name: List all Software Updates links on a namespace
      text: az iot adr ns link su list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link su delete"
    ] = """
  type: command
  short-summary: Permanently delete a linked Update Instance and update the namespace.
  long-summary: |
    Permanently deletes the actual Microsoft.DeviceUpdate/updateInstances resource
    referenced by the named link, then removes that updating endpoint from the
    Device Registry namespace. Role assignments are not deleted. The namespace is
    re-read immediately before replacement; latest unrelated state is preserved and
    a repointed endpoint causes an abort. The generated API has no ETag/If-Match, so
    a narrower post-read race remains. This operation cannot be undone.
  examples:
    - name: Delete the linked Update Instance and update the namespace without prompting
      text: az iot adr ns link su delete -n my-su --ns myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns link su wait"
    ] = """
  type: command
  short-summary: Wait for a Software Updates endpoint to link successfully.
  long-summary: |
    The endpoint name is required. Without an explicit wait predicate, this command
    polls that endpoint's linkingState and fails immediately if it reaches Failed.
  examples:
    - name: Wait until a Software Updates endpoint reaches linkingState Succeeded
      text: az iot adr ns link su wait -n my-su --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns su"
    ] = """
  type: group
  short-summary: Manage Software Updates for Device Registry namespaces.
  long-summary: |
    Manages the Update Instance (Microsoft.DeviceUpdate/updateInstances) that powers
    Software Updates and the updates and device classes available through a linked
    Device Registry namespace. Namespace links remain under 'az iot adr ns link su'.
  """

    helps[
        "iot adr ns su instance"
    ] = """
  type: group
  short-summary: Manage the Update Instance that powers Software Updates.
  long-summary: |
    Update Instances are top-level Microsoft.DeviceUpdate resources. They are
    grouped here for Device Registry discoverability but are not namespace children.
  """

    helps[
        "iot adr ns su instance check-name"
    ] = """
  type: command
  short-summary: Check whether an Update Instance name is available.
  examples:
    - name: Check a name
      text: az iot adr ns su instance check-name -n myUpdateInstance
  """

    helps[
        "iot adr ns su instance create"
    ] = """
  type: command
  short-summary: Create an Update Instance.
  long-summary: |
    Creates a Microsoft.DeviceUpdate/updateInstances resource. Managed identity
    arguments can be combined and describe the complete desired identity state
    when supplied. Re-running create without either identity option preserves an
    existing instance's SAMI/UAMI configuration, tags, and service-managed state.
  examples:
    - name: Create an instance with a system-assigned identity
      text: az iot adr ns su instance create -n myUpdateInstance -g myResourceGroup --location eastus2 --system-assigned-mi
    - name: Create an instance with system- and user-assigned identities
      text: |
        az iot adr ns su instance create -n myUpdateInstance -g myResourceGroup \\
          --system-assigned-mi --user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity>
    - name: Replace an existing instance identity with a user-assigned-only configuration
      text: |
        az iot adr ns su instance create -n myUpdateInstance -g myResourceGroup \\
          --user-assigned-mi /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity>
  """

    helps[
        "iot adr ns su instance show"
    ] = """
  type: command
  short-summary: Show an Update Instance.
  examples:
    - name: Show an instance
      text: az iot adr ns su instance show -n myUpdateInstance -g myResourceGroup
  """

    helps[
        "iot adr ns su instance list"
    ] = """
  type: command
  short-summary: List Update Instances.
  examples:
    - name: List instances in a resource group
      text: az iot adr ns su instance list -g myResourceGroup
    - name: List instances in the subscription
      text: az iot adr ns su instance list
  """

    helps[
        "iot adr ns su instance update"
    ] = """
  type: command
  short-summary: Update an Update Instance's tags or managed identity.
  long-summary: |
    Identity options describe the complete desired identity state when supplied:
    --system-assigned-mi controls SAMI and --user-assigned-mi supplies the UAMI
    set. Omit both identity options to leave the existing identity unchanged.
  examples:
    - name: Update tags
      text: az iot adr ns su instance update -n myUpdateInstance -g myResourceGroup --tags environment=test
    - name: Set the identity to system-assigned
      text: az iot adr ns su instance update -n myUpdateInstance -g myResourceGroup --system-assigned-mi
  """

    helps[
        "iot adr ns su instance delete"
    ] = """
  type: command
  short-summary: Delete an Update Instance.
  examples:
    - name: Delete without prompting
      text: az iot adr ns su instance delete -n myUpdateInstance -g myResourceGroup --yes
  """

    helps[
        "iot adr ns su instance wait"
    ] = """
  type: command
  short-summary: Wait for an Update Instance condition.
  long-summary: Without an explicit wait predicate, waits for provisioningState Succeeded.
  examples:
    - name: Wait until provisioning succeeds
      text: az iot adr ns su instance wait -n myUpdateInstance -g myResourceGroup
  """

    helps["iot adr ns su software-update"] = """
  type: group
  short-summary: Import and manage Software Updates content.
  long-summary: |
    Uses the data-plane serviceAddress materialized on the namespace's Software
    Updates link. The link must finish provisioning before these commands can run.
  """

    helps["iot adr ns su software-update import"] = """
  type: command
  short-summary: Import an update into Software Updates.
  long-summary: |
    Imports a v5 manifest from a read-accessible URL. When --size or --hashes is
    omitted, the CLI streams the manifest to calculate its size and SHA-256 hash.
  examples:
    - name: Import a manifest and one payload file
      text: |
        az iot adr ns su software-update import --ns myNamespace -g myResourceGroup \\
          --url "https://storage.example/manifest.json?<sas>" \\
          --file filename=payload.bin url="https://storage.example/payload.bin?<sas>"
  """

    helps["iot adr ns su software-update stage"] = """
  type: command
  short-summary: Stage local update artifacts and optionally import them.
  long-summary: |
    Validates local manifest payload sizes and SHA-256 hashes, uploads each manifest
    and its files to Azure Storage, and reuses matching staged blobs. File references
    must name files in the same directory as their manifest. Without --then-import,
    no SAS URLs are generated or returned. With --then-import, fresh read-only SAS
    URLs are generated and all manifests are submitted in one import request.
  examples:
    - name: Stage a single update without importing it
      text: |
        az iot adr ns su software-update stage --ns myNamespace -g myResourceGroup \\
          --manifest-path ./manifest.json --storage-account mystorage \\
          --storage-container updates
    - name: Stage and import a multi-reference update
      text: |
        az iot adr ns su software-update stage --ns myNamespace -g myResourceGroup \\
          --manifest-path ./root.json --manifest-path ./leaf.json \\
          --storage-account /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/mystorage \\
          --storage-container updates --then-import --enable-scan
  """

    helps["iot adr ns su software-update list"] = """
  type: command
  short-summary: List updates imported into Software Updates.
  examples:
    - name: List all imported updates
      text: az iot adr ns su software-update list --ns myNamespace -g myResourceGroup
    - name: List deployable updates
      text: az iot adr ns su software-update list --ns myNamespace -g myResourceGroup --filter "isDeployable eq true"
  """

    helps["iot adr ns su software-update show"] = """
  type: command
  short-summary: Show an imported update.
  examples:
    - name: Show an update version
      text: |
        az iot adr ns su software-update show --ns myNamespace -g myResourceGroup \\
          --update-provider Contoso --update-name Thermostat --update-version 1.0
  """

    helps["iot adr ns su software-update wait"] = """
  type: command
  short-summary: Wait for an imported Software Update condition.
  long-summary: |
    The Software Update model has no lifecycle status. Without an explicit wait
    predicate, a successful GET means the imported update is materialized and ready.
  examples:
    - name: Wait until an imported update exists
      text: |
        az iot adr ns su software-update wait --ns myNamespace -g myResourceGroup \\
          --update-provider Contoso --update-name Thermostat --update-version 1.0
  """

    helps["iot adr ns su software-update delete"] = """
  type: command
  short-summary: Delete an imported update.
  examples:
    - name: Delete an update version without prompting
      text: |
        az iot adr ns su software-update delete --ns myNamespace -g myResourceGroup \\
          --update-provider Contoso --update-name Thermostat --update-version 1.0 --yes
  """

    helps["iot adr ns su software-update calculate-hash"] = """
  type: command
  short-summary: Calculate update-file hashes locally.
  examples:
    - name: Calculate a SHA-256 hash
      text: az iot adr ns su software-update calculate-hash --file-path ./payload.bin
  """

    helps["iot adr ns su software-update file"] = """
  type: group
  short-summary: Inspect files belonging to an imported update.
  """

    helps["iot adr ns su software-update file list"] = """
  type: command
  short-summary: List file identifiers for an imported update.
  examples:
    - name: List files
      text: |
        az iot adr ns su software-update file list --ns myNamespace -g myResourceGroup \\
          --update-provider Contoso --update-name Thermostat --update-version 1.0
  """

    helps["iot adr ns su software-update file show"] = """
  type: command
  short-summary: Show an imported update file.
  examples:
    - name: Show a file
      text: |
        az iot adr ns su software-update file show --ns myNamespace -g myResourceGroup \\
          --update-provider Contoso --update-name Thermostat --update-version 1.0 \\
          --update-file-id payload
  """

    helps["iot adr ns su software-update operation-status"] = """
  type: group
  short-summary: Inspect asynchronous Software Updates operations.
  """

    helps["iot adr ns su software-update operation-status list"] = """
  type: command
  short-summary: List retained Software Updates operation statuses.
  examples:
    - name: List import operation statuses
      text: az iot adr ns su software-update operation-status list --ns myNamespace -g myResourceGroup
  """

    helps["iot adr ns su software-update operation-status show"] = """
  type: command
  short-summary: Show a Software Updates operation status.
  examples:
    - name: Follow up a no-wait import
      text: |
        az iot adr ns su software-update operation-status show --ns myNamespace \\
          -g myResourceGroup --operation-id 00000000-0000-0000-0000-000000000000
  """

    helps["iot adr ns su software-update catalog"] = """
  type: group
  short-summary: Discover Software Updates catalog identifiers.
  """

    helps["iot adr ns su software-update catalog provider"] = """
  type: group
  short-summary: Discover update providers.
  """

    helps["iot adr ns su software-update catalog provider list"] = """
  type: command
  short-summary: List update providers in the catalog.
  examples:
    - name: List providers
      text: az iot adr ns su software-update catalog provider list --ns myNamespace -g myResourceGroup
  """

    helps["iot adr ns su software-update catalog name"] = """
  type: group
  short-summary: Discover update names for a provider.
  """

    helps["iot adr ns su software-update catalog name list"] = """
  type: command
  short-summary: List update names for a provider.
  examples:
    - name: List names
      text: |
        az iot adr ns su software-update catalog name list --ns myNamespace \\
          -g myResourceGroup --update-provider Contoso
  """

    helps["iot adr ns su software-update catalog version"] = """
  type: group
  short-summary: Discover update versions for a provider and name.
  """

    helps["iot adr ns su software-update catalog version list"] = """
  type: command
  short-summary: List update versions for a provider and name.
  examples:
    - name: List versions
      text: |
        az iot adr ns su software-update catalog version list --ns myNamespace \\
          -g myResourceGroup --update-provider Contoso --update-name Thermostat
  """

    helps["iot adr ns su software-update init"] = """
  type: group
  short-summary: Create Software Updates import manifests locally.
  """

    helps["iot adr ns su software-update init v5"] = """
  type: command
  short-summary: Create a version 5 import manifest.
  examples:
    - name: Create a simple manifest
      text: |
        az iot adr ns su software-update init v5 --update-provider Contoso \\
          --update-name Thermostat --update-version 1.0 \\
          --compat manufacturer=Contoso model=T1000 \\
          --step handler=microsoft/script:1 --file path=./install.sh
  """

    helps["iot adr ns su device-class"] = """
  type: group
  short-summary: View and delete Software Updates device classes.
  """

    helps["iot adr ns su device-class list"] = """
  type: command
  short-summary: List device classes in a linked Software Updates instance.
  examples:
    - name: List device classes
      text: az iot adr ns su device-class list --ns myNamespace -g myResourceGroup
  """

    helps["iot adr ns su device-class show"] = """
  type: command
  short-summary: Show a Software Updates device class.
  examples:
    - name: Show a device class
      text: |
        az iot adr ns su device-class show --ns myNamespace -g myResourceGroup \\
          --device-class-id 0123456789abcdef
  """

    helps["iot adr ns su device-class delete"] = """
  type: command
  short-summary: Delete a Software Updates device class.
  examples:
    - name: Delete a device class without prompting
      text: |
        az iot adr ns su device-class delete --ns myNamespace -g myResourceGroup \\
          --device-class-id 0123456789abcdef --yes
  """

    helps[
        "iot adr ns link add"
    ] = f"""
  type: command
  short-summary: Link a Hub and a DPS to a Device Registry namespace in a single operation.
  long-summary: |
    Composes a single namespace PATCH that adds both a DPS provisioning endpoint and an IoT Hub
    messaging endpoint. The DPS entry is serialized first to satisfy DPS-first ordering.
    Equivalent to running 'link dps add' followed by 'link hub add' but as one round-trip.
    Rejected if the namespace already has a linked DPS.
    Required roles are taken from the same authoritative matrices used by atomic adds:
    {format_role_requirements("dps")}; {format_role_requirements("hub")}.
  examples:
    - name: Link both a Hub and a DPS using system-assigned identity for both inbound callers
      text: |
        az iot adr ns link add --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --hub-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/IotHubs/<hub> --hub-system-assigned-mi \\
          --dps-endpoint-name primary-dps --dps-id /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Devices/provisioningServices/<dps> --dps-system-assigned-mi
    - name: Link both resources without configuring a Hub inbound caller identity
      text: |
        az iot adr ns link add --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --hub-id <hub-id> \\
          --dps-endpoint-name primary-dps --dps-id <dps-id> --dps-system-assigned-mi
    - name: Link both with custom Hub availability and weight
      text: |
        az iot adr ns link add --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --hub-id <hub-id> --hub-system-assigned-mi \\
          --hub-availability Available --hub-allocation-weight 1 \\
          --dps-endpoint-name primary-dps --dps-id <dps-id> --dps-system-assigned-mi
  """

    helps[
        "iot adr ns link wait"
    ] = """
  type: command
  short-summary: Wait for selected or all namespace links to succeed.
  long-summary: |
    Without an explicit wait predicate, waits until every selected endpoint has
    linkingState Succeeded and fails immediately if any reaches Failed. Scope the
    wait with --hub-endpoint-name, --dps-endpoint-name, and/or
    --su-endpoint-name. If none is supplied, all currently configured Hub, DPS,
    and Software Updates links are included. Explicit Azure CLI wait predicates
    inspect the namespace resource and retain their standard behavior.
  examples:
    - name: Wait until all configured namespace links succeed
      text: az iot adr ns link wait --ns myNamespace -g myResourceGroup
    - name: Wait for the Hub and DPS created by bundled link add
      text: |
        az iot adr ns link wait --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --dps-endpoint-name primary-dps
  """

    helps[
        "iot adr ns group"
    ] = """
    type: group
    short-summary: Manage Device Registry namespace groups.
  """

    helps[
        "iot adr ns group create"
    ] = """
  type: command
  short-summary: Create a group in a Device Registry namespace.
  long-summary: |
    The group's --group-type and --query-string are immutable after creation. Only
    'RegistryDevice' is supported as the group type in the current preview API.

    --query-string is passed to the service verbatim. Use '*' to include every device in
    the namespace.

    Creating a group starts its initial membership calculation. Use
    'az iot adr ns group wait' without a predicate to wait for that calculation.
    Manual membership refresh is rate-limited to once per hour.
  examples:
    - name: Create a group containing every device in the namespace
      text: |
        az iot adr ns group create -n myGroup --ns myNamespace -g myResourceGroup \\
          --query-string "*"
    - name: Create a group with a membership query, display name and description
      text: |
        az iot adr ns group create -n myGroup --ns myNamespace -g myResourceGroup \\
          --query-string "properties.manufacturer = 'Contoso'" \\
          --display-name "Contoso devices" --description "All Contoso-manufactured devices"
  """

    helps[
        "iot adr ns group update"
    ] = """
  type: command
  short-summary: Update a group in a Device Registry namespace.
  long-summary: |
    Only mutable fields are exposed: --display-name, --description and --tags. The group's
    type and membership query cannot be changed after creation; recreate the group instead.
  examples:
    - name: Update a group's display name
      text: az iot adr ns group update -n myGroup --ns myNamespace -g myResourceGroup --display-name "New name"
    - name: Update a group's description and tags
      text: az iot adr ns group update -n myGroup --ns myNamespace -g myResourceGroup --description "Updated" --tags env=prod
  """

    helps[
        "iot adr ns group show"
    ] = """
  type: command
  short-summary: Show a group in a Device Registry namespace.
  examples:
    - name: Show group details
      text: az iot adr ns group show -n myGroup --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns group list"
    ] = """
  type: command
  short-summary: List groups in a Device Registry namespace.
  examples:
    - name: List all groups in a namespace
      text: az iot adr ns group list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns group delete"
    ] = """
  type: command
  short-summary: Delete a group from a Device Registry namespace.
  long-summary: |
    Deletion completes synchronously and does not delete jobs or job runs.
    --no-wait is accepted for compatibility, but still waits for the delete response.
  examples:
    - name: Delete a group
      text: az iot adr ns group delete -n myGroup --ns myNamespace -g myResourceGroup
    - name: Delete a group without confirmation prompt
      text: az iot adr ns group delete -n myGroup --ns myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns group refresh"
    ] = """
  type: command
  short-summary: Trigger an asynchronous refresh of a group's membership.
  long-summary: |
    Refreshing membership is a long-running operation. Use 'az iot adr ns group wait'
    to wait for the refresh to complete, or 'az iot adr ns group show' to poll
    the 'membershipState' field. If a membership calculation is already in
    progress, this command reuses that calculation instead of starting another.
    The service allows membership refresh at most once per hour, including the
    initial membership calculation triggered by group creation.
  examples:
    - name: Refresh group membership
      text: az iot adr ns group refresh -n myGroup --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns group list-members"
    ] = """
  type: command
  short-summary: List the current members of a group.
  long-summary: |
    Follows the service's skip-token pagination and returns member resource ID
    objects.
  examples:
    - name: List group members
      text: az iot adr ns group list-members -n myGroup --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns group count"
    ] = """
  type: command
  short-summary: Show the current member count of a group.
  examples:
    - name: Show member count
      text: az iot adr ns group count -n myGroup --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns group wait"
    ] = """
  type: command
  short-summary: Wait for a Device Registry group to reach a desired state.
  long-summary: |
    Without an explicit wait predicate, waits through membershipState Resolving
    until Ready and fails immediately on FailedToResolveMembers. Explicit
    standard wait predicates remain available.
  examples:
    - name: Wait until a group's membership refresh completes
      text: az iot adr ns group wait -n myGroup --ns myNamespace -g myResourceGroup
    - name: Wait until a group is deleted
      text: az iot adr ns group wait -n myGroup --ns myNamespace -g myResourceGroup --deleted
  """

    helps[
        "iot adr ns job"
    ] = """
    type: group
    short-summary: Manage Device Registry namespace jobs.
  """

    helps[
        "iot adr ns job create"
    ] = """
  type: command
  short-summary: Create a job in a Device Registry namespace.
  long-summary: |
    PUT is a long-running operation. SoftwareUpdate jobs require a target group.
    OnboardingUpdate jobs target all compatible onboarding devices and do not
    accept a target group. Job definition fields are immutable after creation.

    The target group is specified by --target-group-name and must live in the
    same namespace and resource group as the job (cross-namespace targets are
    not supported in this preview release). The Software Update identity
    (--update-id-provider, --update-id-name, --update-id-version) is passed
    opaquely to the backend; no Software Updates preflight is performed.
  examples:
    - name: Create a SoftwareUpdate job targeting a group
      text: |
        az iot adr ns job create -n myJob --ns myNamespace -g myResourceGroup \\
          --type SoftwareUpdate \\
          --target-group-name myGroup \\
          --update-id-provider Contoso --update-id-name gateway-firmware --update-id-version 1.2.3
    - name: Create an OnboardingUpdate job
      text: |
        az iot adr ns job create -n onboarding --ns myNamespace -g myResourceGroup \\
          --type OnboardingUpdate \\
          --update-id-provider Contoso --update-id-name gateway-firmware --update-id-version 1.2.3
  """

    helps[
        "iot adr ns job update"
    ] = """
  type: command
  short-summary: Update tags on a job in a Device Registry namespace.
  long-summary: |
    PATCH is synchronous and tags-only by design. The job's --type, target
    group, update identity, and scheduling fields are immutable after creation
    because mutating them would have unintended effects on already-scheduled
    runs. To change these, delete and recreate the job.
  examples:
    - name: Update job tags
      text: az iot adr ns job update -n myJob --ns myNamespace -g myResourceGroup --tags env=prod owner=platform
    - name: Clear all job tags
      text: az iot adr ns job update -n myJob --ns myNamespace -g myResourceGroup --tags ""
  """

    helps[
        "iot adr ns job show"
    ] = """
  type: command
  short-summary: Show a job in a Device Registry namespace.
  examples:
    - name: Show job details
      text: az iot adr ns job show -n myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job list"
    ] = """
  type: command
  short-summary: List jobs in a Device Registry namespace.
  examples:
    - name: List all jobs in a namespace
      text: az iot adr ns job list --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job delete"
    ] = """
  type: command
  short-summary: Delete a job from a Device Registry namespace.
  long-summary: |
    DELETE is a long-running operation. If any in-flight runs (status
    'Scheduled' or 'Active') exist for this job, a warning is
    surfaced before deletion; the backend cancels affected runs with reason
    'CanceledByCustomer'.
  examples:
    - name: Delete a job
      text: az iot adr ns job delete -n myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job schedule"
    ] = """
  type: command
  short-summary: Schedule an execution of a Device Registry job.
  long-summary: |
    A job defines what to deploy and where; scheduling it creates a job run that
    tracks one execution. Schedule the same job as many times as you need.

    --scheduled-time is the only writable property on a run; every other property
    is populated by the service. Omit it to start immediately.

    --run-name is optional. When omitted, a UTC-timestamped name such as
    'run-20251201080000' is generated and returned in the response. Use
    'az iot adr ns job run' to show, cancel, or inspect the resulting run.
  examples:
    - name: Schedule a job to run immediately
      text: az iot adr ns job schedule -n myJob --ns myNamespace -g myResourceGroup
    - name: Schedule a job for a specific UTC time with an explicit run name
      text: |
        az iot adr ns job schedule -n myJob --ns myNamespace -g myResourceGroup \\
          --run-name myRun --scheduled-time 2025-12-01T08:00:00Z
  """

    helps[
        "iot adr ns job wait"
    ] = """
  type: command
  short-summary: Wait for a Device Registry job to reach a desired state.
  long-summary: Without an explicit wait predicate, waits for provisioningState Succeeded.
  examples:
    - name: Wait until job provisioning succeeds
      text: az iot adr ns job wait -n myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job run"
    ] = """
    type: group
    short-summary: Manage runs of Device Registry namespace jobs.
    long-summary: |
      A job describes what to deploy and where; a run is one execution of it.
      Schedule a run with 'az iot adr ns job schedule'.
  """

    helps[
        "iot adr ns job run show"
    ] = """
  type: command
  short-summary: Show a single run of a Device Registry job.
  examples:
    - name: Show a job run
      text: az iot adr ns job run show -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job run summary"
    ] = """
  type: command
  short-summary: Show aggregate progress counts for a Device Registry job run.
  long-summary: |
    Returns the target counts for the run: total, succeeded, failed, inProgress,
    pending, canceled and notApplied. Use 'az iot adr ns job run results' to see
    the individual devices behind these counts.
  examples:
    - name: Show the progress summary for a run
      text: az iot adr ns job run summary -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job run list"
    ] = """
  type: command
  short-summary: List job runs by parent job or across a namespace.
  examples:
    - name: List all runs for a job
      text: az iot adr ns job run list --job-name myJob --ns myNamespace -g myResourceGroup
    - name: List active runs across the namespace
      text: az iot adr ns job run list --ns myNamespace -g myResourceGroup --filter "status eq 'Active'"
    - name: List active or scheduled runs
      text: az iot adr ns job run list --ns myNamespace -g myResourceGroup --filter "status in ('Active', 'Scheduled')"
    - name: List runs ordered by status
      text: az iot adr ns job run list --ns myNamespace -g myResourceGroup --order-by "status asc"
  """

    helps[
        "iot adr ns job run results"
    ] = """
  type: command
  short-summary: Browse per-device results of a job run.
  long-summary: |
    Returns a flat list of per-device results aggregated across all pages of
    the service-side `POST .../listResults` response. Use --filter for
    server-side status filtering.
  examples:
    - name: List every per-device result for a run
      text: az iot adr ns job run results -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
    - name: Show only the failed devices in a run
      text: |
        az iot adr ns job run results -n myRun --job-name myJob --ns myNamespace -g myResourceGroup \\
          --filter "status eq 'Failed'"
    - name: Order device results by status
      text: |
        az iot adr ns job run results -n myRun --job-name myJob --ns myNamespace -g myResourceGroup \\
          --order-by "status asc"
  """

    helps[
        "iot adr ns job run delete"
    ] = """
  type: command
  short-summary: Delete a Device Registry job run.
  long-summary: |
    Deletes the run record. Cancel an in-flight run with
    'az iot adr ns job run cancel' before deleting it.
  examples:
    - name: Delete a job run
      text: az iot adr ns job run delete -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job run cancel"
    ] = """
  type: command
  short-summary: Cancel a Device Registry job run.
  examples:
    - name: Cancel a run
      text: az iot adr ns job run cancel -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns job run wait"
    ] = """
  type: command
  short-summary: Wait for a Device Registry job run to reach a desired state.
  long-summary: |
    Without an explicit wait predicate, waits for status Succeeded. Failed,
    Canceled, and TimedOut are surfaced immediately as unsuccessful terminal states.
  examples:
    - name: Wait until a job run succeeds
      text: az iot adr ns job run wait -n myRun --job-name myJob --ns myNamespace -g myResourceGroup
    - name: Explicitly wait for cancellation
      text: az iot adr ns job run wait -n myRun --job-name myJob --ns myNamespace -g myResourceGroup --custom "properties.status=='Canceled'"
  """

    helps[
        "iot adr ns report"
    ] = """
  type: group
  short-summary: Manage Device Registry update-compliance reports.
  """

    helps[
        "iot adr ns report generate"
    ] = """
  type: command
  short-summary: Generate an update-compliance report.
  long-summary: |
    Wait for generation to complete, then retrieve the latest report for the same type and group.
    With --no-wait, return the operation immediately without retrieving a report.
  examples:
    - name: Generate a namespace update-compliance report
      text: az iot adr ns report generate --ns myNamespace -g myResourceGroup --report-type NamespaceUpdateComplianceReport
    - name: Generate a group best-updates report
      text: az iot adr ns report generate --ns myNamespace -g myResourceGroup --report-type GroupBestUpdatesComplianceReport --group-name myGroup
  """

    helps[
        "iot adr ns report latest"
    ] = """
  type: command
  short-summary: Show the latest update-compliance report.
  examples:
    - name: Show the latest namespace update-compliance report
      text: az iot adr ns report latest --ns myNamespace -g myResourceGroup --report-type NamespaceUpdateComplianceReport
  """

    helps.update(
        {
            "iot adr ns registry-device": """
  type: group
  short-summary: Manage Registry Devices in a Device Registry namespace.
  long-summary: Registry Devices are distinct from Namespace Devices and expose service-materialized authentication profiles, attributes, and capabilities.
  examples:
    - name: List Registry Devices
      text: az iot adr ns registry-device list --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device create": """
  type: command
  short-summary: Create a Registry Device.
  examples:
    - name: Create an enabled Registry Device
      text: az iot adr ns registry-device create -n myDevice --ns myNamespace -g myResourceGroup --enablement-state Enabled --external-device-id edge-01
  """,
            "iot adr ns registry-device show": """
  type: command
  short-summary: Show a Registry Device by resource name or external device ID.
  long-summary: |
    Specify exactly one of --name or --external-device-id. External-ID lookup
    follows every page and fails if the value is missing or is not unique.
  examples:
    - name: Show a Registry Device
      text: az iot adr ns registry-device show -n myDevice --ns myNamespace -g myResourceGroup
    - name: Show a Registry Device by external device ID
      text: az iot adr ns registry-device show --external-device-id edge-01 --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device list": """
  type: command
  short-summary: List Registry Devices in a namespace.
  examples:
    - name: List Registry Devices
      text: az iot adr ns registry-device list --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device update": """
  type: command
  short-summary: Update writable Registry Device properties.
  examples:
    - name: Disable a Registry Device
      text: az iot adr ns registry-device update -n myDevice --ns myNamespace -g myResourceGroup --enablement-state Disabled
  """,
            "iot adr ns registry-device delete": """
  type: command
  short-summary: Delete a Registry Device.
  examples:
    - name: Delete a Registry Device without prompting
      text: az iot adr ns registry-device delete -n myDevice --ns myNamespace -g myResourceGroup --yes
  """,
            "iot adr ns registry-device wait": """
  type: command
  short-summary: Wait for a Registry Device to reach a desired state.
  long-summary: |
    Specify exactly one of --name or --external-device-id. Without an explicit
    predicate, waits for provisioningState Succeeded. Using
    --external-device-id provides a bounded materialization wait controlled by
    --timeout and --interval.
  examples:
    - name: Wait until a Registry Device succeeds
      text: az iot adr ns registry-device wait -n myDevice --ns myNamespace -g myResourceGroup
    - name: Wait for a registration-created device to materialize
      text: az iot adr ns registry-device wait --external-device-id edge-01 --ns myNamespace -g myResourceGroup --timeout 300 --interval 10
  """,
            "iot adr ns registry-device auth": """
  type: group
  short-summary: Inspect authentication profiles materialized beneath a Registry Device.
  examples:
    - name: List authentication profiles
      text: az iot adr ns registry-device auth list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device auth list": """
  type: command
  short-summary: List Registry Device authentication profiles.
  examples:
    - name: List authentication profiles
      text: az iot adr ns registry-device auth list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device auth show": """
  type: command
  short-summary: Show a Registry Device authentication profile.
  examples:
    - name: Show an authentication profile
      text: az iot adr ns registry-device auth show -n default --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device auth show-keys": """
  type: command
  short-summary: Retrieve plaintext keys for a symmetric-key authentication profile.
  long-summary: The response contains secrets. Store and display it securely. The command rejects non-SymmetricKey profiles before requesting keys.
  examples:
    - name: Retrieve symmetric keys
      text: az iot adr ns registry-device auth show-keys -n default --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device auth revoke-certs": """
  type: command
  short-summary: Revoke Microsoft-managed certificates for an authentication profile.
  long-summary: This destructive action applies only to CertificateAuthoritySignedX509Certificate profiles and requires confirmation unless --yes is supplied.
  examples:
    - name: Revoke certificates without prompting
      text: az iot adr ns registry-device auth revoke-certs -n default --registry-device-name myDevice --ns myNamespace -g myResourceGroup --yes
  """,
            "iot adr ns registry-device auth wait": """
  type: command
  short-summary: Wait for a Registry Device authentication profile condition.
  long-summary: Without an explicit wait predicate, waits until the profile exists.
  examples:
    - name: Wait until an authentication profile exists
      text: az iot adr ns registry-device auth wait -n default --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device attribute": """
  type: group
  short-summary: Manage Registry Device attributes.
  long-summary: >
    Attributes store cloud-side metadata for a device, separate from live telemetry.
    Customer-authored attributes are always serialized with reportedBy='User'.
    Microsoft.DeviceUpdate is reserved for backend-materialized attributes, which
    remain readable through list and show.
  examples:
    - name: List attributes
      text: az iot adr ns registry-device attribute list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device attribute create": """
  type: command
  short-summary: Create or replace a Registry Device attribute.
  long-summary: >
    The command performs a full replace (PUT). Any property omitted from --properties is
    removed. --properties accepts inline JSON, a plain JSON file path, or a file path
    with one leading '@'. reportedBy is always 'User'; attempts to author the
    service-owned Microsoft.DeviceUpdate value are rejected before mutation.
  examples:
    - name: Create a user-authored attribute from inline JSON
      text: >
        az iot adr ns registry-device attribute create -n siteInfo --registry-device-name myDevice
        --ns myNamespace -g myResourceGroup --properties '{"site": "plant-3", "rack": 12}'
    - name: Create a user-authored attribute from a JSON file and advertise its schema
      text: >
        az iot adr ns registry-device attribute create -n siteInfo --registry-device-name myDevice
        --ns myNamespace -g myResourceGroup --properties @./site.json
        --schema https://contoso.com/schemas/site.json
  """,
            "iot adr ns registry-device attribute list": """
  type: command
  short-summary: List Registry Device attributes.
  examples:
    - name: List attributes
      text: az iot adr ns registry-device attribute list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device attribute show": """
  type: command
  short-summary: Show a Registry Device attribute.
  long-summary: >
    The Azure Device Update attribute is materialized by the service under the
    canonical resource name 'update'. This command also accepts 'software-update'
    as an alias, applied only when no attribute matches the name you supplied.
    The alias is specific to this command; 'list' and 'delete' use canonical names
    only, and the returned resource still reports its canonical 'name' and 'id'.
  examples:
    - name: Show an attribute
      text: az iot adr ns registry-device attribute show -n agent --registry-device-name myDevice --ns myNamespace -g myResourceGroup
    - name: Show the Azure Device Update attribute by its canonical name
      text: az iot adr ns registry-device attribute show -n update --registry-device-name myDevice --ns myNamespace -g myResourceGroup
    - name: Show the Azure Device Update attribute using the software-update alias
      text: az iot adr ns registry-device attribute show -n software-update --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device attribute delete": """
  type: command
  short-summary: Delete a Registry Device attribute.
  examples:
    - name: Delete a user-authored attribute
      text: az iot adr ns registry-device attribute delete -n siteInfo --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device capability": """
  type: group
  short-summary: Inspect read-only Registry Device capabilities.
  examples:
    - name: List capabilities
      text: az iot adr ns registry-device capability list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device capability list": """
  type: command
  short-summary: List read-only Registry Device capabilities.
  examples:
    - name: List capabilities
      text: az iot adr ns registry-device capability list --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns registry-device capability show": """
  type: command
  short-summary: Show a read-only Registry Device capability.
  examples:
    - name: Show a capability
      text: az iot adr ns registry-device capability show -n iothub --registry-device-name myDevice --ns myNamespace -g myResourceGroup
  """,
            "iot adr ns identity": """
  type: group
  short-summary: Manage identities assigned to a Device Registry namespace.
  examples:
    - name: Show namespace identities
      text: az iot adr ns identity show -n myNamespace -g myResourceGroup
  """,
            "iot adr ns identity show": """
  type: command
  short-summary: Show identities assigned to a namespace.
  examples:
    - name: Show namespace identities
      text: az iot adr ns identity show -n myNamespace -g myResourceGroup
  """,
            "iot adr ns identity assign": """
  type: command
  short-summary: Assign system- or user-assigned identities to a namespace.
  examples:
    - name: Assign a system and user identity
      text: az iot adr ns identity assign -n myNamespace -g myResourceGroup --system --user /subscriptions/.../userAssignedIdentities/myIdentity
  """,
            "iot adr ns identity remove": """
  type: command
  short-summary: Remove system- or user-assigned identities from a namespace.
  long-summary: An identity configured as the namespace outbound identity must be changed before it can be removed.
  examples:
    - name: Remove all user-assigned identities
      text: az iot adr ns identity remove -n myNamespace -g myResourceGroup --user
  """,
            "iot adr ns identity wait": """
  type: command
  short-summary: Wait for a namespace identity update to succeed.
  long-summary: Without an explicit wait predicate, waits for namespace provisioningState Succeeded.
  examples:
    - name: Wait until the namespace update completes
      text: az iot adr ns identity wait -n myNamespace -g myResourceGroup
  """,
        }
    )
