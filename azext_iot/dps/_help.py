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
  short-summary: Run DPS 2026-11-02 device registration.
  long-summary: |
    Calls the service-derived DPS device endpoint using symmetric-key or X.509
    device authentication. Service enrollment records and registration-state
    administration remain under `az iot dps`.
  """

    helps["iot device registration create"] = """
  type: command
  short-summary: Register a device and optionally issue its operational certificate.
  long-summary: |
    Uses RegisterDeviceAndIssueCertificate. The response includes issuedCertificateChain
    and connectionProfile when returned by DPS, plus registryDeviceExternalId to correlate
    the result with `az iot adr ns registry-device show`. Supply --symmetric-key
    (optionally --compute-key and --group-id), or an X.509 --certificate-file-path
    and --key-file-path pair. When DPS credentials are available, symmetric
    attestation material can be retrieved as before. A 202 response is polled,
    honoring Retry-After, until DPS returns 200 or the bounded client wait expires;
    operation-status remains available for explicit follow-up.
    The generated 2026-11-02-preview contract describes issuedCertificateChain
    only as an array of bytes and does not define its wire encoding or certificate
    order. Consequently, this command preserves that field in JSON output but does
    not offer a certificate-file output option; writing a guessed chain could
    produce a non-TLS-ready or incorrectly ordered bundle.
    --endorsement-key and --storage-root-key are retained as advanced request-schema
    fields, but TPM-only authentication is explicitly unsupported because this
    contract provides no client TPM challenge protocol.
  examples:
    - name: Register and issue a certificate from a PEM CSR
      text: |
        az iot device registration create --dps-name MyDps --registration-id device-01 \\
          --symmetric-key DEVICE_KEY --csr ./device-01.csr
    - name: Register with an X.509 device certificate
      text: |
        az iot device registration create --id-scope 0ne00000000 \\
          --registration-id device-01 --certificate-file-path ./device.pem \\
          --key-file-path ./device-key.pem --passphrase SECRET
  """

    helps["iot device registration operation-status"] = """
  type: command
  short-summary: Show the status of a DPS device registration operation.
  examples:
    - name: Show registration status
      text: |
        az iot device registration operation-status --dps-name MyDps \\
          --registration-id device-01 --operation-id 00000000-0000-0000-0000-000000000000
  """
