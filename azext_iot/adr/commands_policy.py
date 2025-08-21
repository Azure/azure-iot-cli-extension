# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Azure Device Registry (ADR) policy command implementations.
"""

from typing import Dict, Optional

from knack.log import get_logger

from azext_iot.adr.providers.policy import PolicyProvider

logger = get_logger(__name__)


def adr_policy_create(
    cmd,
    policy_name: str,
    namespace_name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    certificate_key_type: Optional[str] = None,
    certificate_subject: Optional[str] = None,
    certificate_validity_days: Optional[int] = None,
):
    """Create a policy for an ADR namespace."""

    provider = PolicyProvider(cmd)
    return provider.create(
        policy_name=policy_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
        certificate_key_type=certificate_key_type,
        certificate_subject=certificate_subject,
        certificate_validity_days=certificate_validity_days,
    )


def adr_policy_show(cmd, policy_name: str, namespace_name: str, resource_group_name: str):
    """Show a policy for an ADR namespace."""

    provider = PolicyProvider(cmd)
    return provider.show(
        policy_name=policy_name, namespace_name=namespace_name, resource_group_name=resource_group_name
    )


def adr_policy_list(cmd, namespace_name: str, resource_group_name: Optional[str] = None):
    """List policies for ADR namespaces."""

    provider = PolicyProvider(cmd)
    return provider.list(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_policy_delete(cmd, policy_name: str, namespace_name: str, resource_group_name: str):
    """Delete a policy for an ADR namespace."""

    provider = PolicyProvider(cmd)
    return provider.delete(
        policy_name=policy_name, namespace_name=namespace_name, resource_group_name=resource_group_name
    )


def adr_policy_update(
    cmd,
    policy_name: str,
    namespace_name: str,
    resource_group_name: str,
    certificate_key_type: Optional[str] = None,
    certificate_subject: Optional[str] = None,
    certificate_validity_days: Optional[int] = None,
):
    """Update a policy for an ADR namespace."""

    provider = PolicyProvider(cmd)
    return provider.update(
        policy_name=policy_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        certificate_key_type=certificate_key_type,
        certificate_subject=certificate_subject,
        certificate_validity_days=certificate_validity_days,
    )
