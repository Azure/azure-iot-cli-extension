# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azure.cli.core.commands.parameters import get_three_state_flag, get_enum_type
from azext_iot.product.shared import AttestationType, DeviceType, TaskType, ValidationType


def load_product_test_params(self, _):
    with self.argument_context("iot product test") as c:
        c.argument(
            "skip_provisioning",
            options_list=["--skip-provisioning", "--sp"],
            help="Determines whether the service skips generating provisioning configuration. "
            + "Only applies to SymmetricKey and ConnectionString provisioning types",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "configuration_file",
            options_list=["--configuration-file", "--cf"],
            help="Path to device test JSON file. "
            "If not specified, attestation and device definition parameters must be specified",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "attestation_type",
            options_list=["--attestation-type", "--at"],
            help="How the device will authenticate to testing service Device Provisioning Service",
            arg_group="IoT Device Certification Attestation",
            arg_type=get_enum_type(AttestationType),
        )
        c.argument(
            "certificate_path",
            options_list=["--certificate-path", "--cp"],
            help="The path to the file containing the primary certificate. "
            "When choosing x509 as attestation type, one of the certificate path is required",
            arg_group="IoT Device Certification Attestation",
        )
        c.argument(
            "endorsement_key",
            options_list=["--endorsement-key", "--ek"],
            help="TPM endorsement key for a TPM device. "
            "When choosing TPM as attestation type, endorsement key is required",
            arg_group="IoT Device Certification Attestation",
        )
        c.argument(
            "connection_string",
            options_list=["--connection-string", "--cs"],
            help="Edge module connection string"
            "When choosing IotEdgeCompatible badge type, connection string and attestaion-type of connection string are required",
            arg_group="IoT Device Certification Attestation",
        )
        c.argument(
            "models",
            options_list=["--models", "-m"],
            help="Path containing Azure IoT Plug and Play interfaces implemented by the device being tested. "
            "When badge type is Pnp, models is required",
            arg_group="IoT Device Certification Device Definition",
        )
        c.argument(
            "device_type",
            options_list=["--device-type", "--dt"],
            help="Defines the type of device to be tested",
            arg_group="IoT Device Certification Device Definition",
            arg_type=get_enum_type(DeviceType),
        )
        c.argument(
            "product_id",
            options_list=["--product-id", "-p"],
            help="The submitted product id. Required when validation-type is 'Certification'.",
            arg_group="IoT Device Certification Device Definition",
        )
        c.argument(
            "validation_type",
            options_list=["--validation-type", "--vt"],
            help="The type of validations testing to be performed",
            arg_group="IoT Device Certification Device Definition",
            arg_type=get_enum_type(ValidationType)
        )
    with self.argument_context("iot product test search") as c:
        c.argument(
            "product_id",
            options_list=["--product-id", "-p"],
            help="The submitted product id",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "registration_id",
            options_list=["--registration-id", "-r"],
            help="The regstration Id for Device Provisioning Service",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "certificate_name",
            options_list=["--certificate-name", "--cn"],
            help="The x509 Certificate Common Name (cn) used for Device Provisioning Service attestation",
            arg_group="IoT Device Certification",
        )
    with self.argument_context("iot product test case") as c:
        c.argument(
            "configuration_file",
            options_list=["--configuration-file", "--cf"],
            help="The file path for test case configuration JSON",
            arg_group="IoT Device Certification",
        )
    with self.argument_context("iot product test task") as c:
        c.argument(
            "task_id",
            options_list=["--task-id"],
            help="The generated Id of the testing task",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "running",
            options_list=["--running"],
            help="Get the running tasks of a device test",
            arg_group="IoT Device Certification",
            arg_type=get_three_state_flag(),
        )
        c.argument(
            "task_type",
            options_list=["--type"],
            help="The type of task for the device test",
            arg_group="IoT Device Certification",
            arg_type=get_enum_type(TaskType),
        )
        c.argument(
            "wait",
            options_list=["--wait", "-w"],
            help="Wait for task completion and return test case data when available",
            arg_group="IoT Device Certification",
            arg_type=get_three_state_flag(),
        )
        c.argument(
            "poll_interval",
            options_list=["--poll-interval", "--interval"],
            help="Used in conjunction with --wait. Sepcifies how frequently (in seconds) polling occurs",
            arg_group="IoT Device Certification",
        )
    with self.argument_context("iot product test run") as c:
        c.argument(
            "run_id",
            options_list=["--run-id", "-r"],
            help="The generated Id of a test run",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "wait",
            options_list=["--wait", "-w"],
            help='Wait until test run status is "started" or "running"',
            arg_group="IoT Device Certification",
            arg_type=get_three_state_flag(),
        )
        c.argument(
            "poll_interval",
            options_list=["--poll-interval", "--interval"],
            help="Used in conjunction with --wait. Specifies how frequently (in seconds) polling occurs",
            arg_group="IoT Device Certification",
        )
