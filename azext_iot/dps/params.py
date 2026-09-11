# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azext_iot._validators import mode2_iot_login_handler
from azext_iot.dps.common import CERT_AUTH, DPS_IDENTIFIER, SYM_KEY_AUTH


def load_dps_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot device registration") as context:
        context.argument(
            "login",
            options_list=["--login", "-l"],
            validator=mode2_iot_login_handler,
            help="This command supports an entity connection string with rights to perform action. "
            'Use to avoid session login via "az login". '
            "If both an entity connection string and name are provided the connection string takes priority. "
            "Required if --dps-name is not provided or authenticaton arguments and --id-scope are not provided.",
            arg_group=DPS_IDENTIFIER
        )
        context.argument(
            "dps_name",
            options_list=["--dps-name", "-n"],
            help="Name of the Azure IoT Hub Device Provisioning Service. Required if --login is not provided "
            "or authenticaton arguments and --id-scope are not provided.",
            arg_group=DPS_IDENTIFIER
        )
        context.argument(
            "id_scope",
            options_list=["--id-scope", "--scope"],
            help="ID scope of the Azure IoT Hub Device Provisioning Service. ID scope "
            "does not identify a device endpoint: --dps-name or --login is still "
            "resolved when supplied. With only --id-scope and explicit device "
            "credentials, the documented global endpoint fallback is used.",
            arg_group=DPS_IDENTIFIER
        )
        context.argument(
            "registration_id",
            options_list=["--registration-id", "--rid"],
            help="Device registration ID or individual enrollment ID."
        )
        context.argument(
            "provisioning_host",
            options_list=["--provisioning-host", "--host"],
            help="DPS device endpoint. When omitted, the endpoint is derived from "
            "the selected DPS resource, then falls back to the global endpoint.",
        )
        context.argument(
            "enrollment_group_id",
            options_list=["--enrollment-group-id", "--group-id", "--gid"],
            help="Enrollment group ID. Only needed to retrieve authentication arguments.",
        )
        context.argument(
            "device_symmetric_key",
            options_list=["--symmetric-key", "--key"],
            help="The symmetric shared access key for the device registration.",
            arg_group=SYM_KEY_AUTH,
        )
        context.argument(
            "compute_key",
            options_list=["--compute-key", "--ck"],
            help="Compute the per-device key from --symmetric-key, or from the "
            "enrollment-group key resolved by --group-id with --dps-name/--login. "
            "Cannot be combined with X.509 inputs.",
            arg_group=SYM_KEY_AUTH,
        )
        context.argument(
            "certificate_file",
            options_list=["--certificate-file-path", "--cp"],
            help="Path to certificate PEM file. Required for x509 registrations.",
            arg_group=CERT_AUTH,
        )
        context.argument(
            "key_file",
            options_list=["--key-file-path", "--kp"],
            help="Path to key PEM file. Required for x509 registrations.",
            arg_group=CERT_AUTH,
        )
        context.argument(
            "passphrase",
            options_list=["--passphrase", "--pass"],
            help="Passphrase for the X.509 private key. Valid only with both "
            "--certificate-file-path and --key-file-path.",
            arg_group=CERT_AUTH,
        )
        context.argument(
            "payload",
            options_list=["--payload"],
            help="Registration payload as a JSON object or path to a JSON file.",
        )

    with self.argument_context("iot device registration create") as context:
        context.argument(
            "csr",
            options_list=["--csr", "--csr-file-path"],
            help="Inline PEM/base64 DER PKCS #10 CSR or path to a CSR file. "
            "Its signature must be valid and Common Name must match the registration ID. "
            "The request sends base64 DER without PEM headers.",
            arg_group="Certificate Issuance",
        )
        context.argument(
            "timeout", type=int,
            help="Positive integer hard REST registration timeout in seconds, including worker startup, HTTP and polling. "
            "Excludes preliminary ID scope and bootstrap credential discovery.",
        )
        context.argument(
            "endorsement_key",
            options_list=["--endorsement-key"],
            help="Advanced TPM request field retained by the service schema. Must "
            "be used with --storage-root-key. TPM-only client authentication is "
            "not supported by this command.",
            arg_group="TPM",
        )
        context.argument(
            "storage_root_key",
            options_list=["--storage-root-key"],
            help="Advanced TPM request field retained by the service schema. Must "
            "be used with --endorsement-key. TPM-only client authentication is "
            "not supported by this command.",
            arg_group="TPM",
        )

    with self.argument_context(
        "iot device registration operation-status"
    ) as context:
        context.argument(
            "operation_id",
            options_list=["--operation-id"],
            help="Registration operation identifier returned by create.",
        )
