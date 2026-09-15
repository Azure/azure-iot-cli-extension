# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command-specific ADR wait wrappers."""

from typing import Callable, Optional

from azext_iot.adr.providers.certificate_authority import CertificateAuthorityProvider
from azext_iot.adr.providers.certificate_policy import CertificatePolicyProvider
from azext_iot.adr.providers.group import GroupProvider
from azext_iot.adr.providers.job import JobProvider
from azext_iot.adr.providers.job_run import JobRunProvider
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.software_update import SoftwareUpdateProvider
from azext_iot.adr.providers.update_instance import UpdateInstanceProvider
from azext_iot.adr.providers.wait import (
    DEFAULT_WAIT_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    group_membership_ready,
    job_run_succeeded,
    namespace_links_succeeded,
    provisioning_succeeded,
    resource_exists,
    wait_for_resource,
)


def _wait(
    cmd,
    getter: Callable[[], object],
    default_condition: Callable,
    timeout: int,
    interval: int,
    created: bool,
    updated: bool,
    deleted: bool,
    exists: bool,
    custom: Optional[str],
):
    return wait_for_resource(
        cmd.cli_ctx,
        getter,
        default_condition,
        timeout=timeout,
        interval=interval,
        created=created,
        updated=updated,
        deleted=deleted,
        exists=exists,
        custom=custom,
    )


def adr_namespace_wait(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = NamespaceProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(namespace_name, resource_group_name),
        provisioning_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_ca_wait(
    cmd,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = CertificateAuthorityProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(
            certificate_authority_name, namespace_name, resource_group_name
        ),
        provisioning_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_ca_policy_wait(
    cmd,
    certificate_policy_name: str,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = CertificatePolicyProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(
            certificate_policy_name,
            certificate_authority_name,
            namespace_name,
            resource_group_name,
        ),
        provisioning_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_link_wait(
    cmd,
    client,
    namespace_name: str,
    resource_group_name: str,
    hub_endpoint_name: Optional[str] = None,
    dps_endpoint_name: Optional[str] = None,
    su_endpoint_name: Optional[str] = None,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = LinkProvider(cmd, client=client)
    return _wait(
        cmd,
        lambda: provider._get_namespace(  # pylint: disable=protected-access
            namespace_name, resource_group_name
        ),
        lambda namespace: namespace_links_succeeded(
            namespace,
            hub_endpoint_name=hub_endpoint_name,
            dps_endpoint_name=dps_endpoint_name,
            su_endpoint_name=su_endpoint_name,
        ),
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def _endpoint_wait(
    cmd,
    endpoint_getter: Callable[[], object],
    namespace_getter: Callable[[], object],
    default_condition: Callable,
    timeout: int,
    interval: int,
    created: bool,
    updated: bool,
    deleted: bool,
    exists: bool,
    custom: Optional[str],
):
    # Before command-specific defaults were added, link waits evaluated
    # --created/--updated/--custom against the namespace GET. Keep that
    # compatibility. Default waits also inspect the namespace endpoint directly
    # (avoiding DPS show enrichment on every poll), while exists/deleted use
    # the projected endpoint so 404 has its normal resource meaning.
    getter = (
        endpoint_getter
        if exists or deleted
        else namespace_getter
    )
    return _wait(
        cmd,
        getter,
        default_condition,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_link_hub_wait(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = LinkProvider(cmd, client=client)
    return _endpoint_wait(
        cmd,
        lambda: provider.hub_show(
            endpoint_name, namespace_name, resource_group_name
        ),
        lambda: provider._get_namespace(  # pylint: disable=protected-access
            namespace_name, resource_group_name
        ),
        lambda namespace: namespace_links_succeeded(
            namespace, hub_endpoint_name=endpoint_name
        ),
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_link_dps_wait(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = LinkProvider(cmd, client=client)
    return _endpoint_wait(
        cmd,
        lambda: provider.dps_show(
            endpoint_name, namespace_name, resource_group_name
        ),
        lambda: provider._get_namespace(  # pylint: disable=protected-access
            namespace_name, resource_group_name
        ),
        lambda namespace: namespace_links_succeeded(
            namespace, dps_endpoint_name=endpoint_name
        ),
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_link_su_wait(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = LinkProvider(cmd, client=client)
    return _endpoint_wait(
        cmd,
        lambda: provider.su_show(
            endpoint_name, namespace_name, resource_group_name
        ),
        lambda: provider._get_namespace(  # pylint: disable=protected-access
            namespace_name, resource_group_name
        ),
        lambda namespace: namespace_links_succeeded(
            namespace, su_endpoint_name=endpoint_name
        ),
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_su_instance_wait(
    cmd,
    update_instance_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = UpdateInstanceProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(update_instance_name, resource_group_name),
        provisioning_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_su_software_update_wait(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    update_version: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = SoftwareUpdateProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show_update(
            namespace_name,
            resource_group_name,
            update_provider,
            update_name,
            update_version,
        ),
        resource_exists,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_group_wait(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = GroupProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(group_name, namespace_name, resource_group_name),
        group_membership_ready,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_job_wait(
    cmd,
    job_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = JobProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(job_name, namespace_name, resource_group_name),
        provisioning_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )


def adr_job_run_wait(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
):
    provider = JobRunProvider(cmd)
    return _wait(
        cmd,
        lambda: provider.show(
            job_name, run_name, namespace_name, resource_group_name
        ),
        job_run_succeeded,
        timeout,
        interval,
        created,
        updated,
        deleted,
        exists,
        custom,
    )
