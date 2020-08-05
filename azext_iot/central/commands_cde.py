# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralContDataExportProvider


def add_cde(
    cmd,
    app_id: str,
    export_id: str,
    role: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralContDataExportProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.add_cde(export_id=export_id, central_dns_suffix=central_dns_suffix,)


def list_cdes(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralContDataExportProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.get_cde_list(central_dns_suffix=central_dns_suffix,)


def get_cde(
    cmd, app_id: str, export_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralContDataExportProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.get_cde(export_id=export_id, central_dns_suffix=central_dns_suffix)


def delete_cde(
    cmd, app_id: str, export_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralContDataExportProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.delete_cde(
        export_id=export_id, central_dns_suffix=central_dns_suffix
    )


def update_cde(
    cmd, app_id: str, export_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralContDataExportProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.update_cde(
        export_id=export_id, central_dns_suffix=central_dns_suffix
    )
