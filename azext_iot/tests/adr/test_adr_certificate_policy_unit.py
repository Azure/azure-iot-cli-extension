# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr import commands_certificate_policy


def _set_parent_ca(fixture_ca_policy_provider, ca_type="ICA"):
    fixture_ca_policy_provider.client.certificate_authorities.get.return_value = {
        "properties": {"certificateAuthorityType": ca_type}
    }


def _parent_not_found_error():
    e = HttpResponseError(message="ParentResourceNotFound: certificate authority not found")
    e.status_code = 404
    return e


# ==================== Create ====================


def test_create_ca_policy(fixture_ca_policy_provider, mock_poller):
    """Create builds the certificate config body and resolves location from the namespace."""
    sentinel = Mock()
    _set_parent_ca(fixture_ca_policy_provider)
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.return_value = mock_poller(
        sentinel
    )
    fixture_ca_policy_provider.client.namespaces.get.return_value = {"location": "eastus"}

    result = fixture_ca_policy_provider.create(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", validity_days=10,
    )

    assert result == sentinel
    call = fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.call_args[1]
    assert call["certificate_authority_name"] == "ca"
    assert call["certificate_policy_name"] == "cp"
    resource = call["resource"]
    assert resource["properties"]["certificate"]["validityPeriodInDays"] == 10
    assert resource["location"] == "eastus"
    fixture_ca_policy_provider.client.certificate_authorities.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="ns",
        certificate_authority_name="ca",
    )


@pytest.mark.parametrize("validity_days", [6, 91])
def test_create_ca_policy_rejects_invalid_validity_before_mutation(
    fixture_ca_policy_provider, validity_days
):
    with pytest.raises(InvalidArgumentValueError) as raised:
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp",
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            validity_days=validity_days,
        )

    assert str(raised.value) == (
        f"--validity-days must be between 7 and 90 days, inclusive. "
        f"Received {validity_days}."
    )
    fixture_ca_policy_provider.client.certificate_authorities.get.assert_not_called()
    fixture_ca_policy_provider.client.namespaces.get.assert_not_called()
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.assert_not_called()


def test_create_ca_policy_rejects_root_before_mutation(fixture_ca_policy_provider):
    _set_parent_ca(fixture_ca_policy_provider, "Root")

    with pytest.raises(
        InvalidArgumentValueError,
        match=r"requires an issuing certificate authority.*type 'ICA'.*--ca-name",
    ):
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp",
            certificate_authority_name="root",
            namespace_name="ns",
            resource_group_name="rg",
            validity_days=10,
        )

    fixture_ca_policy_provider.client.namespaces.get.assert_not_called()
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize(
    "parent",
    [
        None,
        {},
        {"properties": None},
        {"properties": {"certificateAuthorityType": "Unexpected"}},
    ],
)
def test_create_ca_policy_rejects_missing_or_odd_parent_response(
    fixture_ca_policy_provider, parent
):
    fixture_ca_policy_provider.client.certificate_authorities.get.return_value = parent

    with pytest.raises(InvalidArgumentValueError, match=r"type 'ICA'"):
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp",
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            validity_days=10,
        )

    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.assert_not_called()


def test_create_ca_policy_parent_get_not_found(fixture_ca_policy_provider):
    error = HttpResponseError(message="certificate authority not found")
    error.status_code = 404
    fixture_ca_policy_provider.client.certificate_authorities.get.side_effect = error

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp",
            certificate_authority_name="missing",
            namespace_name="ns",
            resource_group_name="rg",
            validity_days=10,
        )

    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.assert_not_called()


def test_create_ca_policy_parent_get_unrelated_error(fixture_ca_policy_provider):
    error = HttpResponseError(message="service unavailable")
    error.status_code = 503
    fixture_ca_policy_provider.client.certificate_authorities.get.side_effect = error

    with pytest.raises(HttpResponseError, match="service unavailable"):
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp",
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            validity_days=10,
        )


def test_create_ca_policy_parent_not_found(fixture_ca_policy_provider):
    """Create surfaces a friendly ResourceNotFoundError when the parent CA is missing."""
    _set_parent_ca(fixture_ca_policy_provider)
    fixture_ca_policy_provider.client.namespaces.get.return_value = {"location": "eastus"}
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.side_effect = (
        _parent_not_found_error()
    )

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.create(
            certificate_policy_name="cp", certificate_authority_name="ca",
            namespace_name="ns", resource_group_name="rg", validity_days=10,
        )


# ==================== Show / List ====================


def test_show_ca_policy(fixture_ca_policy_provider):
    """Show returns the certificate policy resource."""
    fixture_ca_policy_provider.client.certificate_policies.get.return_value = {"name": "cp"}

    result = fixture_ca_policy_provider.show(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg",
    )

    assert result["name"] == "cp"
    fixture_ca_policy_provider.client.certificate_policies.get.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns",
        certificate_authority_name="ca", certificate_policy_name="cp",
    )


def test_show_ca_policy_parent_not_found(fixture_ca_policy_provider):
    """Show maps a 404 ParentResourceNotFound to ResourceNotFoundError."""
    fixture_ca_policy_provider.client.certificate_policies.get.side_effect = _parent_not_found_error()

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.show(
            certificate_policy_name="cp", certificate_authority_name="ca",
            namespace_name="ns", resource_group_name="rg",
        )


def test_list_ca_policy(fixture_ca_policy_provider):
    """List returns the certificate policies as a list."""
    fixture_ca_policy_provider.client.certificate_policies.list_by_certificate_authority.return_value = iter(
        [{"name": "cp1"}, {"name": "cp2"}]
    )

    result = fixture_ca_policy_provider.list(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
    )

    assert [r["name"] for r in result] == ["cp1", "cp2"]


# ==================== Update ====================


def test_update_ca_policy(fixture_ca_policy_provider, mock_poller):
    """Update sends tags and fetches fresh state via show()."""
    fixture_ca_policy_provider.client.certificate_policies.begin_update.return_value = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.get.return_value = {"name": "cp"}

    result = fixture_ca_policy_provider.update(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", tags={"env": "test"},
    )

    assert result["name"] == "cp"
    properties = fixture_ca_policy_provider.client.certificate_policies.begin_update.call_args[1]["properties"]
    assert properties == {"tags": {"env": "test"}}


def test_update_ca_policy_validity_only(fixture_ca_policy_provider, mock_poller):
    fixture_ca_policy_provider.client.certificate_policies.begin_update.return_value = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.get.return_value = {"name": "cp"}

    fixture_ca_policy_provider.update(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg",
        validity_days=60,
    )

    properties = fixture_ca_policy_provider.client.certificate_policies.begin_update.call_args[1]["properties"]
    assert properties == {
        "properties": {
            "certificate": {
                "validityPeriodInDays": 60,
            }
        }
    }


@pytest.mark.parametrize("validity_days", [6, 91])
def test_update_ca_policy_rejects_invalid_validity_before_mutation(
    fixture_ca_policy_provider, validity_days
):
    with pytest.raises(InvalidArgumentValueError) as raised:
        fixture_ca_policy_provider.update(
            certificate_policy_name="cp",
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            tags={"env": "unchanged"},
            validity_days=validity_days,
        )

    assert str(raised.value) == (
        f"--validity-days must be between 7 and 90 days, inclusive. "
        f"Received {validity_days}."
    )
    fixture_ca_policy_provider.client.certificate_policies.begin_update.assert_not_called()
    fixture_ca_policy_provider.client.certificate_policies.get.assert_not_called()


def test_update_ca_policy_tags_and_validity(fixture_ca_policy_provider, mock_poller):
    fixture_ca_policy_provider.client.certificate_policies.begin_update.return_value = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.get.return_value = {"name": "cp"}

    fixture_ca_policy_provider.update(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg",
        tags={"env": "test"}, validity_days=90,
    )

    properties = fixture_ca_policy_provider.client.certificate_policies.begin_update.call_args[1]["properties"]
    assert properties == {
        "tags": {"env": "test"},
        "properties": {
            "certificate": {
                "validityPeriodInDays": 90,
            }
        },
    }


def test_update_ca_policy_wrapper_forwards_validity_days(mocker):
    provider = mocker.patch.object(
        commands_certificate_policy, "CertificatePolicyProvider"
    ).return_value

    commands_certificate_policy.adr_ca_policy_update(
        Mock(),
        certificate_policy_name="cp",
        certificate_authority_name="ca",
        namespace_name="ns",
        resource_group_name="rg",
        tags={"env": "test"},
        validity_days=60,
        no_wait=True,
    )

    provider.update.assert_called_once_with(
        certificate_policy_name="cp",
        certificate_authority_name="ca",
        namespace_name="ns",
        resource_group_name="rg",
        tags={"env": "test"},
        validity_days=60,
        no_wait=True,
    )


# ==================== Delete ====================


def test_delete_ca_policy(fixture_ca_policy_provider, mock_poller):
    """Delete triggers begin_delete LRO and returns the result."""
    sentinel = Mock()
    fixture_ca_policy_provider.client.certificate_policies.begin_delete.return_value = mock_poller(sentinel)

    result = fixture_ca_policy_provider.delete(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg",
    )

    assert result == sentinel
    fixture_ca_policy_provider.client.certificate_policies.begin_delete.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns",
        certificate_authority_name="ca", certificate_policy_name="cp",
    )


# ==================== --no-wait + guards + tags ====================


def test_create_ca_policy_no_wait_returns_poller(fixture_ca_policy_provider, mock_poller):
    """With --no-wait, create returns the poller without waiting."""
    poller = mock_poller({"name": "cp"})
    _set_parent_ca(fixture_ca_policy_provider)
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.return_value = poller
    fixture_ca_policy_provider.client.namespaces.get.return_value = {"location": "eastus"}

    result = fixture_ca_policy_provider.create(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", validity_days=10, no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()


def test_update_ca_policy_requires_a_field(fixture_ca_policy_provider):
    """Update with no updatable fields raises RequiredArgumentMissingError."""
    from azure.cli.core.azclierror import RequiredArgumentMissingError

    with pytest.raises(RequiredArgumentMissingError):
        fixture_ca_policy_provider.update(
            certificate_policy_name="cp", certificate_authority_name="ca",
            namespace_name="ns", resource_group_name="rg",
        )


def test_create_ca_policy_with_tags(fixture_ca_policy_provider, mock_poller):
    """Tags are included in the create body when provided."""
    _set_parent_ca(fixture_ca_policy_provider)
    fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.return_value = mock_poller(
        Mock()
    )
    fixture_ca_policy_provider.client.namespaces.get.return_value = {"location": "eastus"}

    fixture_ca_policy_provider.create(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", validity_days=10, tags={"env": "prod"},
    )

    resource = fixture_ca_policy_provider.client.certificate_policies.begin_create_or_replace.call_args[1][
        "resource"
    ]
    assert resource["tags"] == {"env": "prod"}


def test_update_ca_policy_parent_not_found(fixture_ca_policy_provider):
    """Update maps a 404 ParentResourceNotFound to ResourceNotFoundError."""
    fixture_ca_policy_provider.client.certificate_policies.begin_update.side_effect = (
        _parent_not_found_error()
    )

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.update(
            certificate_policy_name="cp", certificate_authority_name="ca",
            namespace_name="ns", resource_group_name="rg", tags={"env": "test"},
        )


def test_delete_ca_policy_parent_not_found(fixture_ca_policy_provider):
    """Delete maps a 404 ParentResourceNotFound to ResourceNotFoundError."""
    fixture_ca_policy_provider.client.certificate_policies.begin_delete.side_effect = (
        _parent_not_found_error()
    )

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.delete(
            certificate_policy_name="cp", certificate_authority_name="ca",
            namespace_name="ns", resource_group_name="rg",
        )


def test_list_ca_policy_parent_not_found(fixture_ca_policy_provider):
    """List maps a 404 ParentResourceNotFound to ResourceNotFoundError."""
    fixture_ca_policy_provider.client.certificate_policies.list_by_certificate_authority.side_effect = (
        _parent_not_found_error()
    )

    with pytest.raises(ResourceNotFoundError, match=r"certificate authority"):
        fixture_ca_policy_provider.list(
            certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        )


def test_update_ca_policy_with_tags(fixture_ca_policy_provider, mock_poller):
    """Tags-only update sends tags in the patch body and fetches fresh state via show()."""
    fixture_ca_policy_provider.client.certificate_policies.begin_update.return_value = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.get.return_value = {"name": "cp"}

    fixture_ca_policy_provider.update(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", tags={"env": "prod"},
    )

    properties = fixture_ca_policy_provider.client.certificate_policies.begin_update.call_args[1]["properties"]
    assert properties["tags"] == {"env": "prod"}


def test_update_ca_policy_no_wait_returns_poller(fixture_ca_policy_provider, mock_poller):
    """With --no-wait, update returns the poller without waiting or re-fetching."""
    poller = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.begin_update.return_value = poller

    result = fixture_ca_policy_provider.update(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", tags={"env": "test"}, no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()
    fixture_ca_policy_provider.client.certificate_policies.get.assert_not_called()


def test_delete_ca_policy_no_wait_returns_poller(fixture_ca_policy_provider, mock_poller):
    """With --no-wait, delete returns the poller without waiting."""
    poller = mock_poller(Mock())
    fixture_ca_policy_provider.client.certificate_policies.begin_delete.return_value = poller

    result = fixture_ca_policy_provider.delete(
        certificate_policy_name="cp", certificate_authority_name="ca",
        namespace_name="ns", resource_group_name="rg", no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()
