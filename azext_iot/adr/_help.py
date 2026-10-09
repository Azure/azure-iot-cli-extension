# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Help documentation for Azure Device Registry (ADR) commands.
"""

from knack.help_files import helps
from azext_iot.adr.rbac import format_role_requirements


def _load_schema_help():
    helps["iot adr schema"] = """
  type: group
  short-summary: Manage schemas and their versions in a Schema Registry.
  long-summary: |
    A Schema stores information such as the document type and format. Each Schema
    Version stores one Message Schema, Thing Model, or Thing Description document.
    When another resource asks for a schema or model reference, use the full resource
    ID of a specific Schema Version.
  """
    helps["iot adr schema create"] = """
  type: command
  short-summary: Create a Schema.
  long-summary: |
    Creates Schema metadata. Use 'schema version create' to create a version and
    provide its schemaContent value.
  examples:
    - name: Create a Thing Model Schema
      text: |
        az iot adr schema create -n smart-lamp -g MyRG --registry site-a \\
          --schema-type ThingModel --format JsonLD/1.1
  """
    helps["iot adr schema show"] = """
  type: command
  short-summary: Show a Schema.
  long-summary: |
    Shows the Schema type, format, and other properties. Use 'schema version show'
    to retrieve the document stored in a version.
  examples:
    - name: Show a Schema
      text: az iot adr schema show -n smart-lamp --registry site-a -g MyRG
  """
    helps["iot adr schema list"] = """
  type: command
  short-summary: List Schemas in a Schema Registry.
  examples:
    - name: List Schemas
      text: az iot adr schema list --registry site-a -g MyRG
  """
    helps["iot adr schema delete"] = """
  type: command
  short-summary: Delete a Schema.
  examples:
    - name: Delete a Schema
      text: az iot adr schema delete -n smart-lamp --registry site-a -g MyRG --yes
  """
    helps["iot adr schema wait"] = """
  type: command
  short-summary: Wait for a Schema operation to finish.
  long-summary: |
    Use after starting an operation with --no-wait. Specify a condition such as
    --deleted, --exists, or --custom.
  examples:
    - name: Wait for a Schema to be deleted
      text: az iot adr schema wait -n smart-lamp --registry site-a -g MyRG --deleted
  """
    helps["iot adr schema registry"] = """
  type: group
  short-summary: Manage Schema Registries.
  long-summary: |
    A Schema Registry stores Schema Version content in an Azure Data Lake Storage
    Gen2 container. It is a separate Azure resource and does not belong to a
    Device Registry namespace.
  """
    helps["iot adr schema registry create"] = """
  type: command
  short-summary: Create a Schema Registry backed by Azure Data Lake Storage Gen2.
  long-summary: |
    Provide the URL of an existing container in a storage account with hierarchical
    namespace. When only an outbound identity is selected, the command also attaches
    that identity to the Schema Registry. The command does not create the container
    or grant storage access.
  examples:
    - name: Create a Schema Registry with a system-assigned identity
      text: |
        az iot adr schema registry create -n site-a -g MyRG \\
          --registry-namespace site-a \\
          --storage-account-container-url https://mystorage.blob.core.windows.net/schemas \\
          --system-assigned-mi
  """
    helps["iot adr schema registry update"] = """
  type: command
  short-summary: Update writable Schema Registry properties.
  examples:
    - name: Update the display name and tags
      text: |
        az iot adr schema registry update -n site-a -g MyRG \\
          --display-name "Site A" --tags environment=test
  """
    helps["iot adr schema registry show"] = """
  type: command
  short-summary: Show a Schema Registry.
  examples:
    - name: Show a Schema Registry
      text: az iot adr schema registry show -n site-a -g MyRG
  """
    helps["iot adr schema registry list"] = """
  type: command
  short-summary: List Schema Registries.
  examples:
    - name: List Schema Registries in a resource group
      text: az iot adr schema registry list -g MyRG
    - name: List Schema Registries in the subscription
      text: az iot adr schema registry list
  """
    helps["iot adr schema registry delete"] = """
  type: command
  short-summary: Delete a Schema Registry.
  examples:
    - name: Delete a Schema Registry
      text: az iot adr schema registry delete -n site-a -g MyRG --yes
  """
    helps["iot adr schema registry wait"] = """
  type: command
  short-summary: Wait for a Schema Registry operation to finish.
  long-summary: |
    Use after starting an operation with --no-wait. Specify a condition such as
    --created, --updated, --deleted, or --exists.
  examples:
    - name: Wait for a Schema Registry to be created
      text: az iot adr schema registry wait -n site-a -g MyRG --created
  """
    helps["iot adr schema version"] = """
  type: group
  short-summary: Manage Schema Versions.
  long-summary: |
    A version name must contain 1 to 10 digits.
  """
    helps["iot adr schema version create"] = """
  type: command
  short-summary: Create a Schema Version.
  long-summary: |
    The --schema-content value is sent directly to properties.schemaContent.
    After a version is created, its schemaContent cannot be changed.
  examples:
    - name: Create a Message Schema version
      text: |
        az iot adr schema version create --registry site-a --schema telemetry \\
          --version 1 --schema-content '{"type":"object"}' -g MyRG
  """
    helps["iot adr schema version show"] = """
  type: command
  short-summary: Show a Schema Version and its content.
  examples:
    - name: Get the resource ID for a Thing Model version
      text: |
        THING_MODEL_ID=$(az iot adr schema version show --registry site-a \\
          --schema smart-lamp --version 1 -g MyRG --query id -o tsv)
  """
    helps["iot adr schema version list"] = """
  type: command
  short-summary: List Schema Versions.
  examples:
    - name: List all versions of a Schema
      text: az iot adr schema version list --registry site-a --schema smart-lamp -g MyRG
  """
    helps["iot adr schema version delete"] = """
  type: command
  short-summary: Delete a Schema Version.
  examples:
    - name: Delete version 2
      text: |
        az iot adr schema version delete --registry site-a --schema smart-lamp \\
          --version 2 -g MyRG --yes
  """
    helps["iot adr schema version wait"] = """
  type: command
  short-summary: Wait for a Schema Version operation to finish.
  long-summary: |
    Use after starting an operation with --no-wait. Specify a condition such as
    --deleted, --exists, or --custom.
  examples:
    - name: Wait for a Schema Version to be deleted
      text: |
        az iot adr schema version wait --registry site-a --schema smart-lamp \\
          --version 2 -g MyRG --deleted
  """


def _load_registry_device_help():
    helps["iot adr ns device"] = """
  type: group
  short-summary: Manage Registry Devices in a Device Registry namespace.
  long-summary: |
    Registry Devices use the 2026-11-01 management API. Device creation does
    not itself issue credentials or create service capabilities. Authentication
    profiles and capabilities are materialized by the provisioning services.
  """
    helps["iot adr ns device create"] = """
  type: command
  short-summary: Create or replace a Registry Device.
  long-summary: Location defaults to the namespace location. External device ID is create-only.
  examples:
    - name: Create an enabled device.
      text: az iot adr ns device create -n my-device --ns my-ns -g MyRG --external-device-id factory-device-1 --manufacturer Contoso
  """
    helps["iot adr ns device show"] = """
  type: command
  short-summary: Get a Registry Device by name or external device ID.
  long-summary: External ID lookup scans every namespace page and fails on ambiguous matches.
  examples:
    - name: Resolve a provisioned device without guessing its Registry Device name.
      text: az iot adr ns device show --external-device-id factory-device-1 --ns my-ns -g MyRG
  """
    helps["iot adr ns device list"] = """
  type: command
  short-summary: List all Registry Devices in a namespace.
  examples:
    - name: List devices.
      text: az iot adr ns device list --ns my-ns -g MyRG
  """
    helps["iot adr ns device update"] = """
  type: command
  short-summary: Update writable Registry Device properties.
  long-summary: Only supplied fields are patched. Unspecified properties are preserved.
  examples:
    - name: Disable a device without replacing its metadata.
      text: az iot adr ns device update -n my-device --ns my-ns -g MyRG --enablement-state Disabled
  """
    helps["iot adr ns device delete"] = """
  type: command
  short-summary: Delete a Registry Device.
  examples:
    - name: Delete a device and wait for its absence.
      text: |
        az iot adr ns device delete -n my-device --ns my-ns -g MyRG --yes --no-wait
        az iot adr ns device wait -n my-device --ns my-ns -g MyRG --deleted
  """
    helps["iot adr ns device wait"] = """
  type: command
  short-summary: Wait for Registry Device provisioning or a specified condition.
  long-summary: |
    By default waits for provisioningState Succeeded and fails on Failed or Canceled.
    Use --exists for materialization alone or --deleted for absence. Specify exactly
    one of --name and --external-device-id.
  examples:
    - name: Wait for a device materialized by registration.
      text: az iot adr ns device wait --external-device-id factory-device-1 --ns my-ns -g MyRG --exists --timeout 600 --interval 10
  """


def load_adr_help():
    _load_schema_help()
    _load_registry_device_help()
    helps[
        "iot adr"
    ] = """
  type: group
  short-summary: Manage Azure Device Registry (ADR) resources.
  long-summary: |
    ADR management APIs support the Azure public cloud only. Management clients default
    to https://management.azure.com. AZURE_IOT_ADR_ARM_ENDPOINT can explicitly select
    the supported public canary endpoint for testing.
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
  examples:
    - name: Update namespace tags
      text: az iot adr ns update -n myNamespace -g myResourceGroup --tags key=value
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
      a CSR; sign that CSR (do not generate a replacement ICA key) and complete activation with
      'az iot adr ns ca activate'. See activate help for a complete external ECC signing recipe.
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
    format with certificates ordered from leaf to root. Sign the actual service CSR and preserve
    its requested extensions. OpenSSL x509 -req does not copy them by default: the recipe below
    requires an OpenSSL version supporting -copy_extensions copy and req -addext.
    Protect the external root private key; use this disposable test root only for testing.
    Remaining validity is measured at activation. Activation may be rejected when less than
    365 days of validity remain, so allow margin and make sure the root covers the ICA's entire
    validity. Keep the extensions requested in the CSR.
    The CLI checks common certificate defects; the service does final validation.
    Without --no-wait, returns the CA once it is Active.
  examples:
    - name: Activate an externally issued ICA
      text: az iot adr ns ca activate -n myExternalICA --ns myNamespace -g myResourceGroup --certificate-chain-file ./signed-chain.pem
    - name: Create a disposable ECC root, sign the service CSR, and activate (Bash; supported OpenSSL required)
      text: |
        (
          set -eu
          umask 077
          pki=$(mktemp -d)
          trap 'rm -f "$pki/root.key" "$pki/root.pem" "$pki/ica.csr" "$pki/ica.pem" "$pki/chain.pem"; rmdir "$pki"' EXIT
          openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:secp384r1 -nodes \\
            -keyout "$pki/root.key" -out "$pki/root.pem" -days 3650 -subj "/CN=Disposable ADR Root" \\
            -addext "basicConstraints=critical,CA:TRUE,pathlen:2" \\
            -addext "keyUsage=critical,keyCertSign,cRLSign"
          az iot adr ns ca create -n myExternalICA --ns myNamespace -g myResourceGroup \\
            --type ICA --issuer-type External --key-type ECC
          az iot adr ns ca show -n myExternalICA --ns myNamespace -g myResourceGroup \\
            --query properties.issuer.certificateSigningRequest -o tsv > "$pki/ica.csr"
          openssl req -in "$pki/ica.csr" -noout -text
          openssl x509 -req -in "$pki/ica.csr" -CA "$pki/root.pem" -CAkey "$pki/root.key" \\
            -set_serial 2 -days 730 -sha384 -copy_extensions copy -out "$pki/ica.pem"
          cat "$pki/ica.pem" "$pki/root.pem" > "$pki/chain.pem"
          az iot adr ns ca activate -n myExternalICA --ns myNamespace -g myResourceGroup \\
            --certificate-chain-file "$pki/chain.pem"
        )
  """

    helps[
        "iot adr ns ca revoke"
    ] = """
  type: command
  short-summary: Revoke and rotate an intermediate certificate authority issued by a Microsoft CA.
  long-summary: |
    Applies only to an ICA whose issuerType is 'Microsoft'. The service revokes the current
    certificate and issues a replacement signed by the same root CA.
    Successful waited revocation returns a fresh CA resource; --no-wait returns submission only
    without an added completion wait or output read. Microsoft issuers may not expose status or
    thumbprint. Fields are returned as supplied by the service. provisioningState describes the
    resource operation; it does not prove that an old certificate is rejected.
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
    name to --ca-name. The leaf certificate validity period must be between 1
    and 90 days, inclusive. Use 'ca policy update --validity-days' to change
    the validity period of an existing policy.
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
    When supplied, the leaf certificate validity period must be between 1 and
    90 days, inclusive.
  examples:
    - name: Update certificate policy tags
      text: az iot adr ns ca policy update -n myPolicy --ca-name myCA --ns myNamespace -g myResourceGroup --validity-days 90
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
    Link a DPS first, then link your IoT Hubs. Use update to change a link's inbound
    identity or retry a Failed endpoint with its saved identity and settings.
    Use show, list and wait to inspect linkingState. Links belong to the namespace.
    To unlink, delete the linked resource first, then run link hub/dps/su remove to remove
    its endpoint from the namespace. Remove does not delete or check the linked resource
    and does not wait for unlink completion.
    Add/update wait for the link to succeed (--timeout default 600 seconds, --interval 30).
    After --no-wait, use link hub/dps/su wait to track completion.
  """

    helps[
        "iot adr ns link hub"
    ] = """
  type: group
  short-summary: Manage IoT Hub links (messaging endpoints) on a Device Registry namespace.
  long-summary: |
    A namespace must have a linked DPS before a new Hub can be linked or a failed
    Hub link can be retried (DPS-first ordering). Hub updates preserve existing
    provisioning settings. Links live on the namespace, not on the IoT Hub resource.
  """

    for kind, resource in (("hub", "IoT Hub"), ("dps", "DPS")):
        helps[f"iot adr ns link {kind} remove"] = f"""
  type: command
  short-summary: Remove a {resource} endpoint from a Device Registry namespace.
  long-summary: |
    Delete the linked {resource} first; this command removes only the namespace endpoint.
    The namespace outbound identity needs Reader on the linked resource's resource group.
    A missing grant is created when you can create role assignments; it is kept after unlinking.
    Keep that resource group until the unlink completes.
    The command does not wait. Confirm removal with 'az iot adr ns show'.
    Avoid concurrent namespace updates while this command runs.
  examples:
    - name: Remove an endpoint after its linked {resource} has been deleted
      text: az iot adr ns link {kind} remove -n primary --ns myNamespace -g myResourceGroup --yes
  """

    helps[
        "iot adr ns link hub add"
    ] = f"""
  type: command
  short-summary: Link an IoT Hub to a Device Registry namespace.
  long-summary: |
    Link a Standard S-tier Hub, such as S1, as a namespace messaging endpoint.
    Requires the namespace to already have at least one linked DPS (DPS-first ordering).
    --system-assigned-mi and --user-assigned-mi are optional. When supplied, exactly one may be
    used to set the inbound caller identity that the Hub will use to call back into the namespace.
    Required service-to-service roles: {format_role_requirements("hub")}.
    The command reuses inherited assignments and creates only missing assignments when run by
    a caller who can create role assignments (for example Owner, User Access Administrator,
    or Role Based Access Control Administrator). Otherwise it stops before changing the namespace and prints the exact commands
    to run. A newly created assignment must become visible within 180 seconds.
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
    Retry a Failed Hub endpoint without identity options to preserve its saved identity
    (including no inbound identity) and provisioning settings. A linked DPS is required.
    To change the inbound identity, pass --system-assigned-mi or --user-assigned-mi.
    Healthy endpoints require an explicit identity change; target and provisioning settings
    cannot be changed in place. A Succeeded endpoint remains updateable after DPS deletion.
    Update checks target existence, region,
    provisioning-state, Standard SKU, selected identity attachment, namespace outbound
    principal, and automatic RBAC preflight. Newly created assignments must become visible
    before namespace mutation.
    ARM assignment visibility does not guarantee that the linked service already honors access.
    Waited add/update commands recover only confirmed AdrMiNotAuthorized on the unchanged endpoint,
    rechecking required assignments and preserving identity and settings. --timeout (600 seconds) bounds
    mutation, polling and 30/60/120-second propagation backoff after initial RBAC preflight;
    --interval (30 seconds) controls polling. Success requires endpoint linkingState Succeeded.
    With --no-wait, use the matching link wait command to track completion.
    Use update, not add, for a persisted failure. Do not delete the linked Hub to retry it.
  examples:
    - name: Retry a failed Hub link with its saved identity and settings
      text: az iot adr ns link hub update -n primary --ns myNamespace -g myResourceGroup
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
    - name: Show the endpoint linking state
      text: az iot adr ns link hub show -n primary --ns myNamespace -g myResourceGroup --query linkingState -o tsv
  """

    helps[
        "iot adr ns link hub list"
    ] = """
  type: command
  short-summary: List IoT Hub messaging endpoints on a Device Registry namespace.
  examples:
    - name: List all Hub links on a namespace
      text: az iot adr ns link hub list --ns myNamespace -g myResourceGroup
    - name: List endpoint names and linking states
      text: az iot adr ns link hub list --ns myNamespace -g myResourceGroup --query "[].{name:name,linkingState:linkingState}"
    - name: List failed Hub endpoints
      text: az iot adr ns link hub list --ns myNamespace -g myResourceGroup --query "[?linkingState=='Failed']"
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
    DPS resource. After deleting the DPS resource, run link dps remove to remove its
    namespace endpoint.
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
    The namespace must also have a system-assigned identity. It receives Azure Device Registry
    Administrator on its own namespace for registry-device provisioning, even when the
    namespace outbound identity is user-assigned. No role is granted to the signed-in caller;
    DPS enrollment management with --auth-type login requires separate DPS data-plane access.
    The command reuses inherited assignments and creates only missing assignments when run by
    a caller who can create role assignments (for example Owner, User Access Administrator,
    or Role Based Access Control Administrator). Otherwise it stops before changing the namespace and prints the exact commands
    to run. A newly created assignment must become visible within 180 seconds.
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
    Retry a Failed DPS endpoint without identity options to reuse its saved inbound identity.
    Pass --system-assigned-mi or --user-assigned-mi to change that identity. A healthy endpoint
    requires an explicit change; the target DPS cannot be changed in place.
    Update checks target existence, region,
    provisioning-state, selected identity attachment, namespace outbound principal,
    automatic RBAC, and assignment-visibility preflight.
    DPS preflight also ensures the namespace system-assigned identity has Azure Device Registry
    Administrator on its own namespace, independently of the namespace outbound identity.
    ARM assignment visibility does not guarantee that the linked service already honors access.
    Waited add/update commands recover only confirmed AdrMiNotAuthorized on the unchanged endpoint,
    rechecking required assignments and preserving identity and settings. --timeout (600 seconds) bounds
    mutation, polling and 30/60/120-second propagation backoff after initial RBAC preflight;
    --interval (30 seconds) controls polling. Success requires endpoint linkingState Succeeded.
    With --no-wait, use the matching link wait command to track completion.
    Use update, not add, for a persisted failure. Do not delete the linked DPS to retry it.
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
    Inspect the named endpoint and decide which existing DPS Hubs to link to the namespace.
    When the DPS read succeeds, brownfieldHubs contains its properties.iotHubs[] list and
    brownfieldHubsAvailable is true. An empty list then means no Hubs are registered.
    If access or a service failure prevents that read, brownfieldHubs is null,
    brownfieldHubsAvailable is false, and a warning explains why. Namespace inspection
    still succeeds; unavailable data must not be treated as an empty DPS registration list.
  examples:
    - name: Show a DPS link by endpoint name (with brownfield Hubs when accessible)
      text: az iot adr ns link dps show -n primary --ns myNamespace -g myResourceGroup
    - name: Show the endpoint linking state
      text: az iot adr ns link dps show -n primary --ns myNamespace -g myResourceGroup --query linkingState -o tsv
  """

    helps[
        "iot adr ns link dps list"
    ] = """
  type: command
  short-summary: List DPS provisioning endpoints on a Device Registry namespace.
  examples:
    - name: List all DPS links on a namespace
      text: az iot adr ns link dps list --ns myNamespace -g myResourceGroup
    - name: List endpoint names and linking states
      text: az iot adr ns link dps list --ns myNamespace -g myResourceGroup --query "[].{name:name,linkingState:linkingState}"
    - name: List failed DPS endpoints
      text: az iot adr ns link dps list --ns myNamespace -g myResourceGroup --query "[?linkingState=='Failed']"
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
        "iot adr ns link add"
    ] = f"""
  type: command
  short-summary: Link DPS first, then a Hub, to a Device Registry namespace.
  long-summary: |
    Validates both targets, endpoint names, identity selections, and required RBAC before
    changing namespace endpoints. Submits a DPS-only namespace update and waits for the exact
    DPS endpoint to reach linkingState Succeeded before submitting a separate Hub update.
    --no-wait still waits for this DPS dependency; it skips waiting only for the final Hub operation.
    Both waited stages recover only confirmed AdrMiNotAuthorized on the unchanged endpoint after
    verifying required service-role assignments. Recovery uses endpoint update, never another add.
    --timeout (600 seconds) is one shared mutation/recovery budget for both stages after initial RBAC
    preflight, including RPCs, polling and bounded 30/60/120-second backoff. --interval defaults to 30
    seconds. Both must be positive. No delay is added when authorization already works.
    With --no-wait, use link hub wait to track the Hub stage.
    Rejected if the namespace already has a linked DPS. A DPS failure or timeout prevents Hub submission.
    Partial completion is not rolled back. Inspect failed endpoints with link dps show or link hub show
    and repair persisted failures with the corresponding link update, preserving the existing identity.
    After DPS succeeds, use link hub add only if the Hub endpoint is absent; use link hub wait if pending.
    Do not rerun combined link add when the DPS endpoint already exists.
    Required service-to-service roles:
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
    - name: Wait for DPS, submit the Hub without waiting, then observe the Hub link
      text: |
        az iot adr ns link add --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --hub-id <hub-id> \\
          --dps-endpoint-name primary-dps --dps-id <dps-id> --dps-system-assigned-mi --no-wait
        az iot adr ns link hub wait -n primary-hub --ns myNamespace -g myResourceGroup
  """

    helps[
        "iot adr ns link wait"
    ] = """
  type: command
  short-summary: Wait for selected or all namespace links to succeed.
  long-summary: |
    Without an explicit wait predicate, waits until every selected endpoint has
    linkingState Succeeded and fails immediately if any reaches Failed. Scope the
    wait with --hub-endpoint-name and/or --dps-endpoint-name. If neither is
    supplied, all configured Hub and DPS links are included. Explicit Azure CLI wait predicates
    inspect the namespace resource and retain their standard behavior.
  examples:
    - name: Wait until all configured namespace links succeed
      text: az iot adr ns link wait --ns myNamespace -g myResourceGroup
    - name: Wait for the Hub and DPS created by combined DPS-first link add
      text: |
        az iot adr ns link wait --ns myNamespace -g myResourceGroup \\
          --hub-endpoint-name primary-hub --dps-endpoint-name primary-dps
  """

    helps.update(
        {
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
