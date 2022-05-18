# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azext_iot._validators import mode2_iot_login_handler


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
            arg_group="Device Provisioning Service Identifier"
        )
        context.argument(
            "dps_name",
            options_list=["--dps-name", "-n"],
            help="Name of the Azure IoT Hub Device Provisioning Service. Required if --login is not provided "
            "or authenticaton arguments and --id-scope are not provided.",
            arg_group="Device Provisioning Service Identifier"
        )
        context.argument(
            "id_scope",
            options_list=["--id-scope", "--scope"],
            help="Id Scope of the Azure IoT Hub Device Provisioning Service. If provided with authentication "
            "arguments, will avoid session login.",
            arg_group="Device Provisioning Service Identifier"
        )
        context.argument(
            "registration_id",
            options_list=["--registration-id", "--rid"],
            help="Device registration ID or individual enrollment ID."
        )
        context.argument(
            "enrollment_group_id",
            options_list=["--enrollment-group-id", "--group-id", "--gid"],
            help="Enrollment group ID."
        )
        context.argument(
            "symmetric_key",
            options_list=["--symmetric-key", "--key"],
            help="The symmetric shared access key for the device registration.",
            arg_group="Authentication"
        )
        context.argument(
            "compute_key",
            options_list=["--compute-key", "--ck"],
            help="Flag to indicate that the symmetric key for the device registration should be computed from the "
            "given key with --symmetric-key.",
            arg_group="Authentication"
        )
        context.argument(
            "payload",
            options_list=["--payload"],
            help="Custom allocation payload as JSON. Specifically for use with custom allocation policies "
            "using Azure Functions."
        )

    with self.argument_context("iot device registration create") as context:
        context.argument(
            "wait",
            options_list=["--wait", "-w"],
            help="Block until the device registration assignment is completed or failed. Will regularly "
            "poll on interval specified by --poll-interval."
        )
        context.argument(
            "poll_interval",
            options_list=["--poll-interval", "--interval"],
            help="Interval in seconds that job status will be checked if --wait flag is passed in."
        )

    with self.argument_context("iot device registration operation") as context:
        context.argument(
            "operation_id",
            options_list=["--operation-id", "--oid"],
            help="Operation Id for the registration.",
        )
