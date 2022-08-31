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
    group_id: str,
    entry: str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> EnrollmentGroupGa:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    response = provider.get_enrollment_group(
        group_id=group_id,
        central_dns_suffix=central_dns_suffix,
    )

    if entry is not None:
        response["x509"] = get_x509(
            cmd=cmd,
            app_id=app_id,
            group_id=group_id,
            entry=entry,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )

    return response


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
    group_id: str,
    enabled: bool = False,
    entry: str = None,
    certificate: str = None,
    verified: bool = None,
    etag : str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> EnrollmentGroupGa:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    attestation = utility.process_json_arg(attestation, argument_name="attestation")

    response = provider.create_enrollment_group(
        group_id=group_id,
        attestation=attestation,
        display_name=display_name,
        type=type,
        enabled=enabled,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )

    if None not in (certificate, verified, entry):
        # We need to set up the primary or secondary x509 certificate
        response["x509"] = create_x509(
            cmd=cmd,
            app_id=app_id,
            group_id=group_id,
            entry=entry,
            certificate=certificate,
            verified=verified,
            etag=etag,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )

    return response


def update_enrollment_group(
    cmd,
    app_id: str,
    group_id: str,
    attestation: str = None,
    display_name: str = None,
    type: str = None,
    enabled: bool = False,
    entry: str = None,
    certificate: str = None,
    verified: bool = None,
    remove_x509: bool = None,
    etag : str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
):
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    if attestation is not None:
        attestation = utility.process_json_arg(attestation, argument_name="attestation")

    response = provider.update_enrollment_group(
        group_id=group_id,
        attestation=attestation,
        display_name=display_name,
        type=type,
        enabled=enabled,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )

    if None not in (certificate, verified, entry):
        # We need to set up the primary or secondary x509 certificate
        response["x509"] = create_x509(
            cmd=cmd,
            app_id=app_id,
            group_id=group_id,
            entry=entry,
            certificate=certificate,
            verified=verified,
            etag=etag,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )
    elif remove_x509 is True:
        # We need to remove x509 from the group
        response["x509"] = {
            "remove": delete_x509(
                cmd=cmd,
                app_id=app_id,
                group_id=group_id,
                entry=entry,
                token=token,
                central_dns_suffix=central_dns_suffix,
                api_version=api_version,
            )
        }

    return response


def delete_enrollment_group(
    cmd,
    app_id: str,
    group_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_enrollment_group(
        group_id=group_id,
        central_dns_suffix=central_dns_suffix,
    )


def create_x509(
    cmd,
    app_id: str,
    group_id: str,
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
        group_id=group_id,
        entry=entry,
        certificate=certificate,
        verified=verified,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )


def get_x509(
    cmd,
    app_id: str,
    group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_x509(
        group_id=group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )


def delete_x509(
    cmd,
    app_id: str,
    group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_x509(
        group_id=group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )


def verify_x509(
    cmd,
    app_id: str,
    group_id: str,
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
        group_id=group_id,
        entry=entry,
        certificate=certificate,
        central_dns_suffix=central_dns_suffix,
    )


def generate_verification_code(
    cmd,
    app_id: str,
    group_id: str,
    entry: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.generate_verification_code(
        group_id=group_id,
        entry=entry,
        central_dns_suffix=central_dns_suffix,
    )
