# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

import base64
from typing import List, Optional

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralEnrollmentGroupProvider
from azext_iot.common.certops import open_certificate
from azext_iot.central.common import API_VERSION
from azext_iot.central.models.ga_2022_07_31 import EnrollmentGroupGa


def get_enrollment_group(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: Optional[str] = None,
    token: Optional[str] = None,
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

    if certificate_entry:
        response["x509"] = get_x509(
            cmd=cmd,
            app_id=app_id,
            group_id=group_id,
            certificate_entry=certificate_entry,
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
    enabled: Optional[str] = 'enabled',
    primary_key: Optional[str] = None,
    secondary_key: Optional[str] = None,
    primary_cert_path: Optional[str] = None,
    secondary_cert_path: Optional[str] = None,
    etag: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> EnrollmentGroupGa:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    response = provider.create_enrollment_group(
        group_id=group_id,
        attestation=attestation,
        primary_key=primary_key,
        secondary_key=secondary_key,
        display_name=display_name,
        type=type,
        enabled=(enabled == 'enabled'),
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )

    # For x509 we need to call a seperate API
    primary_cert = None
    secondary_cert = None

    if attestation == 'x509':
        if primary_cert_path:
            primary_cert = open_certificate(primary_cert_path)
            primary_cert = base64.encodebytes((primary_cert.replace('\r', '') + '\n').encode()).decode().replace('\n', '')

        if secondary_cert_path:
            secondary_cert = open_certificate(secondary_cert_path)
            secondary_cert = base64.encodebytes((secondary_cert.replace('\r', '') + '\n').encode()).decode().replace('\n', '')

        if primary_cert_path or secondary_cert_path:
            response["x509"] = create_x509(
                cmd=cmd,
                app_id=app_id,
                group_id=group_id,
                primary_cert=primary_cert,
                secondary_cert=secondary_cert,
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
    display_name: Optional[str] = None,
    type: Optional[str] = None,
    remove_x509: Optional[bool] = None,
    enabled: Optional[str] = 'enabled',
    primary_cert_path: Optional[str] = None,
    secondary_cert_path: Optional[str] = None,
    certificate_entry: Optional[str] = None,
    etag: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
):
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    response = provider.update_enrollment_group(
        group_id=group_id,
        display_name=display_name,
        type=type,
        enabled=(enabled == 'enabled'),
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )

    # Still can create/remove x509 during update
    primary_cert = None
    secondary_cert = None

    if primary_cert_path:
        primary_cert = open_certificate(primary_cert_path)

    if secondary_cert_path:
        secondary_cert = open_certificate(secondary_cert_path)

    if primary_cert_path or secondary_cert_path:
        response["x509"] = create_x509(
            cmd=cmd,
            app_id=app_id,
            group_id=group_id,
            primary_cert=primary_cert,
            secondary_cert=secondary_cert,
            etag=etag,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )
    elif remove_x509 is True and certificate_entry:
        # We need to remove x509 from the group
        response["x509"] = {
            "remove": delete_x509(
                cmd=cmd,
                app_id=app_id,
                group_id=group_id,
                certificate_entry=certificate_entry,
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
    primary_cert: Optional[str] = None,
    secondary_cert: Optional[str] = None,
    etag: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.create_x509(
        group_id=group_id,
        primary_cert=primary_cert,
        secondary_cert=secondary_cert,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )


def verify_x509(
    cmd,
    app_id: str,
    group_id: str,
    primary_cert_path: Optional[str] = None,
    secondary_cert_path: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    primary_cert = None
    secondary_cert = None

    if primary_cert_path:
        primary_cert = open_certificate(primary_cert_path)
        primary_cert = base64.encodebytes((primary_cert.replace('\r', '') + '\n').encode()).decode().replace('\n', '')

    if secondary_cert_path:
        secondary_cert = open_certificate(secondary_cert_path)
        secondary_cert = base64.encodebytes((secondary_cert.replace('\r', '') + '\n').encode()).decode().replace('\n', '')

    return provider.verify_x509(
        group_id=group_id,
        primary_cert=primary_cert,
        secondary_cert=secondary_cert,
        central_dns_suffix=central_dns_suffix,
    )


def get_x509(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_x509(
        group_id=group_id,
        certificate_entry=certificate_entry,
        central_dns_suffix=central_dns_suffix,
    )


def delete_x509(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_x509(
        group_id=group_id,
        certificate_entry=certificate_entry,
        central_dns_suffix=central_dns_suffix,
    )


def generate_verification_code(
    cmd,
    app_id: str,
    group_id: str,
    certificate_entry: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralEnrollmentGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.generate_verification_code(
        group_id=group_id,
        certificate_entry=certificate_entry,
        central_dns_suffix=central_dns_suffix,
    )
