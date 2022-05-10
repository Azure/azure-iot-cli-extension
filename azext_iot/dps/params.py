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
            "Required if --dps-name is not provided.",
            arg_group="Device Provisioning Service Identifier"
        )
        context.argument(
            "dps_name",
            options_list=["--dps-name", "-n"],
            help="Name of the Azure IoT Hub Device Provisioning Service. Required if --login is not provided.",
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
            "device_symmetric_key",
            options_list=["--symmetric-key", "--key"],
            help="The symmetric shared access key for the device. If provided, the SAS "
            "token will be generated directly from the supplied symmetric key without further validation.",
        )
        context.argument(
            "group_symmetric_key",
            options_list=["--group-symmetric-key", "--group-key"],
            help="The symmetric shared access key for the enrollment group. If provided, the device symmetric "
            "key will be generated directly from the supplied symmetric key without further validation. Only "
            "used for registrations part of an enrollment group.",
        )

    with self.argument_context("iot device registration operation") as context:
        context.argument(
            "operation_id",
            options_list=["--operation-id", "--oid"],
            help="Operation Id for the registration.",
        )
