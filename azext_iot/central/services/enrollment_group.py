# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/deviceGroups

from typing import List
import requests

from knack.log import get_logger

from azure.cli.core.azclierror import AzureResponseError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.ga_2022_07_31 import EnrollmentGroupGa
from azext_iot.central.common import API_VERSION

logger = get_logger(__name__)

BASE_PATH = "api/enrollmentGroups"
MODEL = "EnrollmentGroup"


def list_enrollment_groups(
    cmd,
    app_id: str,
    token: str,
    api_version=API_VERSION,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[EnrollmentGroupGa]:
    """
    Get a list of all enrollment groups.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of enrollment groups
    """
    api_version = API_VERSION

    enrollment_groups = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        for enrollment_group in result["value"]:
            enrollment_groups.append(EnrollmentGroupGa(enrollment_group))

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return enrollment_groups


def get_enrollment_group(
    cmd,
    app_id: str,
    group_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> EnrollmentGroupGa:
    """
    Get a specific enrollment group.

    Args:
        cmd: command passed into az
        group_id: case sensitive enrollment group id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        enrollment_group: dict
    """
    api_version = API_VERSION

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, group_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def create_enrollment_group(
    cmd,
    app_id: str,
    attestation: str,
    primary_key: str,
    secondary_key: str,
    display_name: str,
    type: str,
    token: str,
    group_id: str,
    enabled: bool = True,
    etag: str = None,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> EnrollmentGroupGa:
    """
    Creates a enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        display_name: Display name of the enrollment group
        attestation: The attestation mechanism for the enrollment group
        type: Type of devices that connect through the group
        enabled	: Whether the devices using the group are allowed to connect to IoT Central
        etag: ETag used to prevent conflict in enrollment group updates
        token: (OPTIONAL) authorization token to fetch enrollment details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        enrollment_group: dict
    """
    api_version = API_VERSION

    if attestation is None:
        attestation = 'symmetricKey'

    attestation_payload = {
        "type": attestation
    }
    if attestation == 'symmetricKey' and (primary_key or secondary_key):
        attestation_payload['symmetricKey'] = {}
        attestation_payload['symmetricKey']['primaryKey'] = primary_key
        attestation_payload['symmetricKey']['secondaryKey'] = secondary_key

    payload = {
        "displayName": display_name,
        "attestation": attestation_payload,
        "type": type,
    }

    if enabled is not None:
        payload['enabled'] = enabled

    if etag is not None:
        payload['etag'] = etag

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, group_id),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def update_enrollment_group(
    cmd,
    app_id: str,
    display_name: str,
    type: str,
    token: str,
    group_id: str,
    enabled: bool = True,
    etag : str = None,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> EnrollmentGroupGa:
    """
    Updates a enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        display_name: Display name of the enrollment group
        attestation: The attestation mechanism for the enrollment group
        type: Type of devices that connect through the group
        enabled	: Whether the devices using the group are allowed to connect to IoT Central
        etag: ETag used to prevent conflict in enrollment group updates
        token: (OPTIONAL) authorization token to fetch enrollment details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        enrollment_group: dict
    """
    api_version = API_VERSION

    payload = {}

    if display_name is not None:
        payload["displayName"] = display_name

    if enabled is not None:
        payload['enabled'] = enabled

    if etag is not None:
        payload['etag'] = etag

    if type is not None:
        payload["type"] = type

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PATCH",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, group_id),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, MODEL, api_version)


def delete_enrollment_group(
    cmd,
    app_id: str,
    group_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete a enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        enrollment_group: dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, group_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def create_x509(
    cmd,
    app_id: str,
    group_id: str,
    primary_cert: str,
    secondary_cert: str,
    etag: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Sets the primary or secondary x509 certificate of an enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        entry: entry of certificate only support primary and secondary
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        dict
    """
    api_version = API_VERSION

    entry = 'primary' if primary_cert is not None else 'secondary'

    payload = {
        "certificate": primary_cert if primary_cert is not None else secondary_cert,
    }

    if etag is not None:
        payload['etag'] = etag

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url="https://{}.{}/{}/{}/certificates/{}".format(
            app_id, central_dns_suffix, BASE_PATH, group_id, entry),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_x509(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Get the primary or secondary x509 certificate of an enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        entry: entry of certificate only support primary and secondary
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}/certificates/{}".format(
            app_id, central_dns_suffix, BASE_PATH, group_id, certificate_entry),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def delete_x509(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Removes the primary or secondary x509 certificate of an enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        entry: entry of certificate only support primary and secondary
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url="https://{}.{}/{}/{}/certificates/{}".format(
            app_id, central_dns_suffix, BASE_PATH, group_id, certificate_entry),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def verify_x509(
    cmd,
    app_id: str,
    group_id: str,
    primary_cert: str,
    secondary_cert: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Verify the primary or secondary x509 certificate of an enrollment group
    by providing a certificate with the signed verification code.

    Please note that if an enrollment group was created with an unverified x509
    certificate, a verification certificate will need to be created using the 
    unverified x509 certificate and a verification code before using this command.
    A verification code can be generated via cli using
    the 'enrollment-group generate-verification-code' command. Learn more on how to
    create verification certificates using verification code at 
    https://learn.microsoft.com/en-us/azure/iot-central/core/how-to-connect-devices-x509

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        entry: entry of certificate only support primary and secondary
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        dict
    """
    api_version = API_VERSION

    entry = 'primary' if primary_cert is not None else 'secondary'

    payload = {
        "certificate": primary_cert if primary_cert is not None else secondary_cert,
    }

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="POST",
        url="https://{}.{}/{}/{}/certificates/{}/verify".format(
            app_id, central_dns_suffix, BASE_PATH, group_id, entry),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def generate_verification_code(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Generate a verification code for the primary or secondary x509 certificate of
    an enrollment group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        group_id: case sensitive enrollment group id
        entry: entry of certificate only support primary and secondary
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="POST",
        url="https://{}.{}/{}/{}/certificates/{}/generateVerificationCode".format(
            app_id, central_dns_suffix, BASE_PATH, group_id, certificate_entry),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
