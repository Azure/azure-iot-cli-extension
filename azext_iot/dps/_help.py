# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Help for DPS device registration."""

from knack.help_files import helps


def load_deviceprovisioningservice_help():
    helps["iot device registration"] = """
  type: group
  short-summary: Register a device through Azure IoT Hub Device Provisioning Service (DPS).
  long-summary: |
    Use create for an individual or group enrollment, then operation-status to
    follow an accepted registration. Authenticate the device with its symmetric
    key or an X.509 certificate. Service enrollment records and registration-state
    administration remain under `az iot dps`.
  """

    helps["iot device registration create"] = """
  type: command
  short-summary: Register a device and optionally issue its operational certificate.
  long-summary: |
    For an individual enrollment, supply its device --symmetric-key. For a group
    enrollment, supply the group key with --compute-key, or supply an already
    derived device key without --compute-key. Alternatively, use --dps-name with
    --auth-type login to discover the ID scope/endpoint and retrieve enrollment
    keys; add --group-id and --compute-key for a group enrollment. Entra login
    authorizes this bootstrap lookup, not the device registration request.

    Use --id-scope with explicit device credentials to skip DPS resource
    discovery. Set --host when using a non-default provisioning endpoint.
    For X.509 authentication, supply --certificate-file-path and --key-file-path;
    add --passphrase only if the private key is encrypted.

    Add --csr (alias --csr-file-path) to request an operational certificate.
    It accepts PEM or base64 DER PKCS #10, inline or from a file. The CSR signature
    must be valid and its Common Name must match --registration-id.
    A CSR does not replace the device's symmetric-key or X.509 authentication.

    The command polls accepted registrations, honoring Retry-After. If it times
    out after receiving an operation ID, use operation-status with that ID and
    the same registration ID, ID scope, endpoint and device authentication.
    A timeout does not cancel the backend operation; do not blindly rerun create.
    --timeout applies a hard deadline to the same REST flow for both CSR and non-CSR registration, including
    worker startup, HTTP retries and polling, after preliminary ID scope and bootstrap credential discovery.
    Without --timeout, the existing bounded five-minute polling behavior is retained.

    JSON output preserves issuedCertificateChain and connectionProfile when DPS
    returns them, plus registryDeviceExternalId for Registry Device correlation.
    The 2026-11-02-preview RegisterDeviceAndIssueCertificate contract describes issuedCertificateChain
    only as an array of bytes and does not define its wire encoding or certificate
    order. Consequently, this command preserves that field in JSON output but does
    not offer a certificate-file output option; writing a guessed chain could
    produce a non-TLS-ready or incorrectly ordered bundle.
    --endorsement-key and --storage-root-key are retained as advanced request-schema
    fields, but TPM-only authentication is explicitly unsupported because this
    contract provides no client TPM challenge protocol.
  examples:
    - name: Register an individual enrollment using Entra-authorized bootstrap key lookup
      text: |
        az iot device registration create --dps-name MyDps --resource-group MyResourceGroup \\
          --registration-id device-01 --auth-type login
    - name: Register a group member using Entra-authorized bootstrap key lookup
      text: |
        az iot device registration create --dps-name MyDps --registration-id device-01 \\
          --group-id MyEnrollmentGroup --compute-key --auth-type login
    - name: Register with a device key and known ID scope, without bootstrap lookup
      text: |
        az iot device registration create --id-scope 0ne00000000 \\
          --registration-id device-01 --symmetric-key DEVICE_KEY
    - name: Derive a device key from an enrollment group key and register
      text: |
        az iot device registration create --id-scope 0ne00000000 \\
          --registration-id device-01 --symmetric-key GROUP_KEY --compute-key
    - name: Register and request an operational certificate from a PEM CSR
      text: |
        az iot device registration create --id-scope 0ne00000000 --registration-id device-01 \\
          --symmetric-key DEVICE_KEY --csr ./device-01.csr --timeout 120
    - name: Register with an X.509 device certificate
      text: |
        az iot device registration create --id-scope 0ne00000000 \\
          --registration-id device-01 --certificate-file-path ./device.pem \\
          --key-file-path ./device-key.pem
  """

    helps["iot device registration operation-status"] = """
  type: command
  short-summary: Show the status of a DPS device registration operation.
  long-summary: |
    Supply the operation ID returned by DPS or reported by create after a timeout.
    Reuse the registration ID, ID scope (or DPS name), provisioning host and device
    authentication from create. This is a status read, not a new registration.
  examples:
    - name: Follow an individual enrollment with bootstrap key lookup
      text: |
        az iot device registration operation-status --dps-name MyDps \\
          --registration-id device-01 --operation-id OPERATION_ID --auth-type login
    - name: Follow a group member with the same group key and provisioning host
      text: |
        az iot device registration operation-status --id-scope 0ne00000000 \\
          --registration-id device-01 --operation-id OPERATION_ID \\
          --symmetric-key GROUP_KEY --compute-key --host MyProvisioningHost
    - name: Follow an accepted operation after a timeout without resubmitting registration
      text: |
        az iot device registration operation-status --id-scope 0ne00000000 \\
          --registration-id device-01 --operation-id OPERATION_ID --symmetric-key DEVICE_KEY
  """
