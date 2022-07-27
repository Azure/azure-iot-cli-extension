# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azext_iot._validators import mode2_iot_login_handler
from azext_iot.dps.common import CERT_AUTH, DPS_IDENTIFIER, SYM_KEY_AUTH, TRUST_BUNDLE


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
            help="Id Scope of the Azure IoT Hub Device Provisioning Service. If provided with authentication "
            "arguments, will avoid session login.",
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
            help="Endpoint pointing to the provisioning host to use."
        )
        context.argument(
            "enrollment_group_id",
            options_list=["--enrollment-group-id", "--group-id", "--gid"],
            help="Enrollment group ID. Only needed to retrieve authentication arguments."
        )
        context.argument(
            "device_symmetric_key",
            options_list=["--symmetric-key", "--key"],
            help="The symmetric shared access key for the device registration.",
            arg_group=SYM_KEY_AUTH
        )
        context.argument(
            "compute_key",
            options_list=["--compute-key", "--ck"],
            help="Flag to indicate that the symmetric key for the device registration should be computed from the "
            "given key with --symmetric-key.",
            arg_group=SYM_KEY_AUTH
        )
        context.argument(
            "payload",
            options_list=["--payload"],
            help="Custom allocation payload as JSON. Specifically for use with custom allocation policies "
            "using Azure Functions."
        )
        context.argument(
            "certificate_file",
            options_list=["--certificate-file-path", "--cp"],
            help="Path to certificate PEM file. Required for x509 registrations.",
            arg_group=CERT_AUTH
        )
        context.argument(
            "key_file",
            options_list=["--key-file-path", "--kp"],
            help="Path to key PEM file. Required for x509 registrations.",
            arg_group=CERT_AUTH
        )
        context.argument(
            "passphrase",
            options_list=["--passphrase", "--pass"],
            help="Passphrase for the certificate.",
            arg_group=CERT_AUTH
        )

    with self.argument_context("iot dps trust-bundle") as context:
        context.argument(
            "trust_bundle_id",
            options_list=["--trust-bundle-id", "--tb"],
            help="The trust bundle id. A case-insensitive string of alphanumeric & certain special characters : . _ - "
            "It can be upto 128 characters long. Special characters are not allowed at start or end.",
            arg_group=TRUST_BUNDLE,
        )
        context.argument(
            "trusted_certificates",
            options_list=["--trusted-certificates", "--tc"],
            help="Inline trusted certificates JSON or file path to trusted certificates JSON.",
            arg_group=TRUST_BUNDLE,
        )
        context.argument(
            "with_certificate_data",
            options_list=["--with-certificate-data", "--wcd"],
            help="Flag to specify if certificate data is to be fetched when listing certificates.",
            arg_group=TRUST_BUNDLE,
        )
