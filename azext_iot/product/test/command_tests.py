# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.product.providers.aics import AICSProvider
from azext_iot.sdk.product.models import DeviceTestSearchOptions
from azext_iot.product.shared import BadgeType, AttestationType, ValidationType
from knack.log import get_logger
from knack.util import CLIError
import os

logger = get_logger(__name__)


def create(
    cmd,
    configuration_file=None,
    product_id=None,
    device_type=None,
    attestation_type=None,
    certificate_path=None,
    connection_string=None,
    endorsement_key=None,
    badge_type=BadgeType.IotDevice.value,
    validation_type=ValidationType.test.value,
    models=None,
    skip_provisioning=False,
    base_url=None,
):
    if attestation_type == AttestationType.x509.value and not certificate_path:
        raise CLIError("If attestation type is x509, certificate path is required")
    if attestation_type == AttestationType.tpm.value and not endorsement_key:
        raise CLIError("If attestation type is TPM, endorsement key is required")
    if badge_type == BadgeType.Pnp.value and not models:
        raise CLIError("If badge type is Pnp, models is required")
    if badge_type == BadgeType.IotEdgeCompatible.value and not all(
        [connection_string, attestation_type == AttestationType.connectionString.value]
    ):
        raise CLIError(
            "Connection string is required for Edge Compatible modules testing"
        )
    if badge_type != BadgeType.IotEdgeCompatible.value and (
        connection_string or attestation_type == AttestationType.connectionString.value
    ):
        raise CLIError(
            "Connection string is only available for Edge Compatible modules testing"
        )
    if validation_type != ValidationType.test.value and not product_id:
        raise CLIError(
            "Product Id is required for validation type {}".format(validation_type)
        )
    if not any(
        [
            configuration_file,
            all([device_type, attestation_type, badge_type]),
        ]
    ):
        raise CLIError(
            "If configuration file is not specified, attestation and device definition parameters must be specified"
        )
    test_configuration = (
        _create_from_file(configuration_file)
        if configuration_file
        else _build_test_configuration(
            product_id=product_id,
            device_type=device_type,
            attestation_type=attestation_type,
            certificate_path=certificate_path,
            endorsement_key=endorsement_key,
            badge_type=badge_type,
            connection_string=connection_string,
            models=models,
            validation_type=validation_type
        )
    )

    ap = AICSProvider(cmd, base_url)

    provisioning = not skip_provisioning
    test_data = ap.create_test(
        test_configuration=test_configuration, provisioning=provisioning
    )

    return test_data


def show(cmd, test_id, base_url=None):
    ap = AICSProvider(cmd, base_url)
    return ap.show_test(test_id)


def update(
    cmd,
    test_id,
    configuration_file=None,
    attestation_type=None,
    certificate_path=None,
    connection_string=None,
    endorsement_key=None,
    badge_type=None,
    models=None,
    base_url=None,
):
    provisioning = False
    # verify required parameters for various options
    if attestation_type == AttestationType.x509.value and not certificate_path:
        raise CLIError("If attestation type is x509, certificate path is required")
    if attestation_type == AttestationType.tpm.value and not endorsement_key:
        raise CLIError("If attestation type is tpm, endorsement key is required")
    if badge_type == BadgeType.Pnp.value and not models:
        raise CLIError("If badge type is Pnp, models is required")
    if badge_type == BadgeType.IotEdgeCompatible.value and not all(
        [connection_string, attestation_type == AttestationType.connectionString.value]
    ):
        raise CLIError(
            "Connection string is required for Edge Compatible modules testing"
        )
    if badge_type != BadgeType.IotEdgeCompatible.value and (
        connection_string or attestation_type == AttestationType.connectionString.value
    ):
        raise CLIError(
            "Connection string is only available for Edge Compatible modules testing"
        )
    ap = AICSProvider(cmd, base_url)
    if configuration_file:
        test_configuration = _create_from_file(configuration_file)
        return ap.update_test(
            test_id=test_id,
            test_configuration=test_configuration,
            provisioning=provisioning,
        )

    if not any([attestation_type, badge_type, models]):
        raise CLIError(
            "Configuration file, attestation information, or device configuration must be specified"
        )

    test_configuration = ap.show_test(test_id=test_id)

    provisioning_configuration = test_configuration["provisioningConfiguration"]
    registration_id = provisioning_configuration["dpsRegistrationId"]

    # change attestation
    if attestation_type:
        # reset the provisioningConfiguration
        test_configuration["provisioningConfiguration"] = {
            "type": attestation_type,
            "dpsRegistrationId": registration_id,
        }
        provisioning = True
        if attestation_type == AttestationType.symmetricKey.value:
            test_configuration["provisioningConfiguration"][
                "symmetricKeyEnrollmentInformation"
            ] = {}
        elif attestation_type == AttestationType.tpm.value:
            test_configuration["provisioningConfiguration"][
                "tpmEnrollmentInformation"
            ] = {"endorsementKey": endorsement_key}
        elif attestation_type == AttestationType.x509.value:
            test_configuration["provisioningConfiguration"][
                "x509EnrollmentInformation"
            ] = {
                "base64EncodedX509Certificate": _read_certificate_from_file(
                    certificate_path
                )
            }
        elif attestation_type == AttestationType.connectionString.value:
            test_configuration["provisioningConfiguration"][
                "deviceConnectionString"
            ] = connection_string

    # reset PnP models
    badge_config = test_configuration["certificationBadgeConfigurations"]

    if (
        badge_type == BadgeType.Pnp.value
        or badge_config[0]["type"].lower() == BadgeType.Pnp.value.lower()
    ) and models:
        models_array = _process_models_directory(models)
        test_configuration["certificationBadgeConfigurations"] = [
            {"type": BadgeType.Pnp.value, "digitalTwinModelDefinitions": models_array}
        ]
    elif badge_type:
        test_configuration["certificationBadgeConfigurations"] = [{"type": badge_type}]

    return ap.update_test(
        test_id=test_id,
        test_configuration=test_configuration,
        provisioning=provisioning,
    )


def search(
    cmd, product_id=None, registration_id=None, certificate_name=None, base_url=None
):
    if not any([product_id or registration_id or certificate_name]):
        raise CLIError("At least one search criteria must be specified")

    ap = AICSProvider(cmd, base_url)
    searchOptions = DeviceTestSearchOptions(
        product_id=product_id,
        dps_registration_id=registration_id,
        dps_x509_certificate_common_name=certificate_name,
    )
    return ap.search_test(searchOptions)


def _build_test_configuration(
    product_id,
    device_type,
    attestation_type,
    certificate_path,
    endorsement_key,
    connection_string,
    badge_type,
    models,
    validation_type
):
    config = {
        "validationType": validation_type,
        "productId": product_id,
        "deviceType": device_type,
        "provisioningConfiguration": {"type": attestation_type},
        "certificationBadgeConfigurations": [{"type": badge_type}],
    }
    if attestation_type == AttestationType.symmetricKey.value:
        config["provisioningConfiguration"]["symmetricKeyEnrollmentInformation"] = {}
    elif attestation_type == AttestationType.tpm.value:
        config["provisioningConfiguration"]["tpmEnrollmentInformation"] = {
            "endorsementKey": endorsement_key
        }
    elif attestation_type == AttestationType.x509.value:
        config["provisioningConfiguration"]["x509EnrollmentInformation"] = {
            "base64EncodedX509Certificate": _read_certificate_from_file(
                certificate_path
            )
        }
    elif attestation_type == AttestationType.connectionString.value:
        config["provisioningConfiguration"][
            "deviceConnectionString"
        ] = connection_string

    if badge_type == BadgeType.Pnp.value and models:
        models_array = _process_models_directory(models)
        config["certificationBadgeConfigurations"][0][
            "digitalTwinModelDefinitions"
        ] = models_array

    return config


def _process_models_directory(from_directory):
    from azext_iot.common.utility import scantree, process_json_arg, read_file_content
    # we need to double-encode the JSON string
    from json import dumps

    models = []
    if os.path.isfile(from_directory) and (from_directory.endswith(".json") or from_directory.endswith(".dtdl")):
        models.append(dumps(read_file_content(file_path=from_directory)))
        return models
    for entry in scantree(from_directory):
        if not any([entry.name.endswith(".json"), entry.name.endswith(".dtdl")]):
            logger.debug(
                "Skipping {} - model file must end with .json or .dtdl".format(
                    entry.path
                )
            )
            continue
        entry_json = process_json_arg(content=entry.path, argument_name=entry.name)

        models.append(dumps(entry_json))
    return models


def _read_certificate_from_file(certificate_path):
    with open(file=certificate_path, mode="rb") as f:
        data = f.read()

        from base64 import encodestring  # pylint: disable=no-name-in-module

        return encodestring(data)


def _create_from_file(configuration_file):
    if not (os.path.exists(configuration_file)):
        raise CLIError("Specified configuration file does not exist")

    # read the json file and POST /deviceTests
    with open(file=configuration_file, encoding="utf-8") as f:
        file_contents = f.read()

        from json import loads

        return loads(file_contents)
