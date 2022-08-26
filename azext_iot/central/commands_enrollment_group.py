# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralEnrollmentGroupProvider
from azext_iot.common import utility
from azext_iot.central.common import API_VERSION
from azext_iot.central.models.ga_2022_07_31 import EnrollmentGroupGa


def get_enrollment_group(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> EnrollmentGroupGa:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_enrollment_group(
        enrollment_group_id=enrollment_group_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_enrollment_groups(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> List[EnrollmentGroupGa]:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_enrollment_groups(central_dns_suffix=central_dns_suffix)


def create_enrollment_group(
    cmd,
    app_id: str,
    attestation: str,
    display_name: str,
    type: str,
    enrollment_group_id: str,
    enabled: bool = False,
    etag : str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> EnrollmentGroupGa:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    attestation = utility.process_json_arg(attestation, argument_name="attestation")

    return provider.create_enrollment_group(
        enrollment_group_id=enrollment_group_id,
        attestation=attestation,
        display_name=display_name,
        type=type,
        enabled=enabled,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )


def update_enrollment_group(
    cmd,
    app_id: str,
    attestation: str,
    display_name: str,
    type: str,
    enrollment_group_id: str,
    enabled: bool = False,
    etag : str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
):
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    attestation = utility.process_json_arg(attestation, argument_name="attestation")

    return provider.update_enrollment_group(
        enrollment_group_id=enrollment_group_id,
        attestation=attestation,
        display_name=display_name,
        type=type,
        enabled=enabled,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )


def delete_enrollment_group(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_enrollment_group(
        enrollment_group_id=enrollment_group_id,
        central_dns_suffix=central_dns_suffix,
    )


def create_x509(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    entry: str,
    certificate: str,
    verified: bool,
    etag: str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.create_x509(
        enrollment_group_id=enrollment_group_id,
        entry=entry,
        certificate=certificate,
        verified=verified,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )


def get_x509(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_x509(
        enrollment_group_id=enrollment_group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )


def delete_x509(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_x509(
        enrollment_group_id=enrollment_group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )


def verify_x509(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    entry: str,
    certificate: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.verify_x509(
        enrollment_group_id=enrollment_group_id,
        entry=entry,
        certificate=certificate,
        central_dns_suffix=central_dns_suffix,
    )


def generate_verification_code(
    cmd,
    app_id: str,
    enrollment_group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.generate_verification_code(
        enrollment_group_id=enrollment_group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )
