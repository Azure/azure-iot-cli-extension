# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import DEFAULT_NS_POLICY_CERT_KEY_TYPE, DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS


# ==================== Helpers ====================


def _setup_create(provider, mock_poller, serialized: dict, ns_location: str = "eastus"):
    """Wire up mocks needed for a ``create()`` call."""
    provider.client.policies.begin_create_or_update.return_value = mock_poller(serialized)
    provider.client.namespaces.get.return_value = {"location": ns_location}


def _setup_show(provider, serialized: dict):
    """Wire up mocks needed for a ``show()`` call (namespaces.get + policies.get)."""
    provider.client.namespaces.get.return_value = {}
    provider.client.policies.get.return_value = serialized


def _get_create_cert(provider) -> dict:
    """Extract the certificate dict from the last ``begin_create_or_update`` resource body."""
    resource = provider.client.policies.begin_create_or_update.call_args[1]["resource"]
    return resource.get("properties", {}).get("certificate")


# ==================== Create ====================


@pytest.mark.parametrize(
    "key_type, subject, days, location",
    [
        ("ECC", "test", 30, None),
        (None, None, None, None),
        ("ECC", "test", 30, "westus"),
    ],
    ids=["all-cert-params", "no-cert-params", "explicit-location"],
)
def test_create_policy(fixture_policy_provider, mock_poller, key_type, subject, days, location):
    """Policy creation with various parameter combinations."""
    expected = {"name": "policy", "properties": {"provisioningState": "Succeeded"}}
    _setup_create(fixture_policy_provider, mock_poller, expected)

    result = fixture_policy_provider.create(
        policy_name="policy", namespace_name="ns", resource_group_name="rg",
        location=location, certificate_key_type=key_type,
        certificate_subject=subject, certificate_validity_days=days,
    )

    assert result == expected

    if location:
        fixture_policy_provider.client.namespaces.get.assert_not_called()
    else:
        fixture_policy_provider.client.namespaces.get.assert_called_once()

    cert = _get_create_cert(fixture_policy_provider)
    if any([key_type, subject, days]):
        assert isinstance(cert, dict)
        assert cert["certificateAuthorityConfiguration"]["keyType"] == (key_type or DEFAULT_NS_POLICY_CERT_KEY_TYPE)
        assert cert["leafCertificateConfiguration"]["validityPeriodInDays"] == (days or DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS)
    else:
        assert cert is None


@pytest.mark.parametrize("key_type", [None, "ECC"])
@pytest.mark.parametrize("days", [None, 30])
@pytest.mark.parametrize("subject", [None, "test"])
def test_create_policy_defaults(fixture_policy_provider, mock_poller, key_type, days, subject):
    """Defaults are applied when at least one cert param is specified."""
    _setup_create(fixture_policy_provider, mock_poller, {"name": "p"})

    fixture_policy_provider.create(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
        certificate_key_type=key_type, certificate_subject=subject, certificate_validity_days=days,
    )

    cert = _get_create_cert(fixture_policy_provider)
    if any([key_type, subject, days]):
        assert cert["certificateAuthorityConfiguration"]["keyType"] == (key_type or DEFAULT_NS_POLICY_CERT_KEY_TYPE)
        assert cert["leafCertificateConfiguration"]["validityPeriodInDays"] == (days or DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS)
    else:
        assert cert is None


def test_create_byor(fixture_policy_provider, mock_poller):
    """BYOR creation sets BringYourOwnRoot(enabled=True) with default cert params."""
    _setup_create(fixture_policy_provider, mock_poller, {"name": "byor"})

    fixture_policy_provider.create(
        policy_name="byor", namespace_name="ns", resource_group_name="rg", enable_byor=True,
    )

    cert = _get_create_cert(fixture_policy_provider)
    assert isinstance(cert, dict)
    ca = cert["certificateAuthorityConfiguration"]
    assert ca["bringYourOwnRoot"]["enabled"] is True
    assert ca["keyType"] == DEFAULT_NS_POLICY_CERT_KEY_TYPE
    assert cert["leafCertificateConfiguration"]["validityPeriodInDays"] == DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS


def test_create_byor_with_custom_options(fixture_policy_provider, mock_poller):
    """BYOR with explicit cert options respects the overrides."""
    _setup_create(fixture_policy_provider, mock_poller, {"name": "byor"})

    fixture_policy_provider.create(
        policy_name="byor", namespace_name="ns", resource_group_name="rg",
        enable_byor=True, certificate_key_type="ECC", certificate_validity_days=60,
    )

    cert = _get_create_cert(fixture_policy_provider)
    assert cert["certificateAuthorityConfiguration"]["bringYourOwnRoot"]["enabled"] is True
    assert cert["certificateAuthorityConfiguration"]["keyType"] == "ECC"
    assert cert["leafCertificateConfiguration"]["validityPeriodInDays"] == 60


# ==================== Show ====================


def test_create_policy_namespace_missing_location(fixture_policy_provider):
    """Create raises when parent namespace has no location to inherit."""
    fixture_policy_provider.client.namespaces.get.return_value = {}

    with pytest.raises(AzureResponseError):
        fixture_policy_provider.create(
            policy_name="p", namespace_name="ns", resource_group_name="rg", location=None,
        )


def test_show_policy(fixture_policy_provider):
    """Show returns the serialized policy and calls the correct SDK methods."""
    expected = {"name": "p", "properties": {"provisioningState": "Succeeded"}}
    _setup_show(fixture_policy_provider, expected)

    result = fixture_policy_provider.show(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
    )

    assert result == expected
    fixture_policy_provider.client.policies.get.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", policy_name="p",
    )


def test_show_policy_reraises_non_parent_error(fixture_policy_provider):
    """Show re-raises HttpResponseError when not a ParentResourceNotFound 404."""
    fixture_policy_provider.client.namespaces.get.return_value = {}
    fixture_policy_provider.client.policies.get.side_effect = HttpResponseError(
        response=Mock(status_code=500)
    )

    with pytest.raises(HttpResponseError):
        fixture_policy_provider.show(policy_name="p", namespace_name="ns", resource_group_name="rg")


# ==================== List ====================


def test_list_policies(fixture_policy_provider):
    """List returns serialized results for each policy."""
    fixture_policy_provider.client.namespaces.get.return_value = Mock()
    fixture_policy_provider.client.policies.list_by_resource_group.return_value = [
        {"name": "a"},
        {"name": "b"},
    ]

    result = fixture_policy_provider.list(namespace_name="ns", resource_group_name="rg")

    assert result == [{"name": "a"}, {"name": "b"}]


def test_list_policies_reraises_non_parent_error(fixture_policy_provider):
    """List re-raises HttpResponseError when not a ParentResourceNotFound 404."""
    fixture_policy_provider.client.namespaces.get.return_value = {}
    fixture_policy_provider.client.policies.list_by_resource_group.side_effect = HttpResponseError(
        response=Mock(status_code=500)
    )

    with pytest.raises(HttpResponseError):
        fixture_policy_provider.list(namespace_name="ns", resource_group_name="rg")

# ==================== Delete ====================


def test_delete_policy(fixture_policy_provider, mock_poller):
    """Delete triggers begin_delete LRO and returns the result."""
    sentinel = Mock()
    fixture_policy_provider.client.policies.begin_delete.return_value = mock_poller(sentinel)

    result = fixture_policy_provider.delete(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
    )

    assert result == sentinel
    fixture_policy_provider.client.policies.begin_delete.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", policy_name="p",
    )

# ==================== Update ====================


@pytest.mark.parametrize("days", [None, 20], ids=["no-update", "update-validity"])
def test_update_policy(fixture_policy_provider, mock_poller, days):
    """Update triggers begin_update LRO then fetches fresh state via show()."""
    fixture_policy_provider.client.policies.begin_update.return_value = mock_poller(Mock())
    _setup_show(fixture_policy_provider, {"name": "p", "properties": {"provisioningState": "Succeeded"}})

    result = fixture_policy_provider.update(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
        certificate_validity_days=days,
    )

    assert result["name"] == "p"

    resource = fixture_policy_provider.client.policies.begin_update.call_args[1]["properties"]
    if days is not None:
        cert_config = resource["properties"]["certificate"]
        assert cert_config["leafCertificateConfiguration"]["validityPeriodInDays"] == days
    else:
        assert "certificate" not in resource.get("properties", {})


def test_update_policy_with_tags(fixture_policy_provider, mock_poller):
    """Update passes tags through in the resource body."""
    fixture_policy_provider.client.policies.begin_update.return_value = mock_poller(Mock())
    _setup_show(fixture_policy_provider, {"name": "p"})

    fixture_policy_provider.update(
        policy_name="p", namespace_name="ns", resource_group_name="rg", tags={"env": "test"},
    )

    resource = fixture_policy_provider.client.policies.begin_update.call_args[1]["properties"]
    assert resource["tags"] == {"env": "test"}


# ==================== Revoke Issuer ====================


def test_revoke_issuer(fixture_policy_provider, mock_poller):
    """Revoke triggers begin_revoke_issuer LRO then fetches fresh state via show()."""
    fixture_policy_provider.client.policies.begin_revoke_issuer.return_value = mock_poller(None)
    _setup_show(fixture_policy_provider, {"name": "p", "properties": {"thumbprint": "new"}})

    result = fixture_policy_provider.revoke_issuer(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
    )

    assert result["properties"]["thumbprint"] == "new"
    fixture_policy_provider.client.policies.begin_revoke_issuer.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", policy_name="p",
    )


# ==================== Activate BYOR ====================


def test_activate_byor(fixture_policy_provider, mock_poller):
    """Activate BYOR triggers LRO with cert chain then fetches fresh state via show()."""
    fixture_policy_provider.client.policies.begin_activate_bring_your_own_root.return_value = mock_poller(None)
    show_data = {
        "name": "p",
        "properties": {
            "certificate": {
                "certificateAuthorityConfiguration": {
                    "bringYourOwnRoot": {"status": "Active", "issuingCertificateThumbprint": "abc"},
                }
            }
        },
    }
    _setup_show(fixture_policy_provider, show_data)

    chain = "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----"
    result = fixture_policy_provider.activate_byor(
        policy_name="p", namespace_name="ns", resource_group_name="rg",
        certificate_chain=chain,
    )

    assert result == show_data
    fixture_policy_provider.client.policies.begin_activate_bring_your_own_root.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", policy_name="p",
        body={"certificateChain": chain},
    )


# ==================== Error Scenarios ====================


def _make_parent_not_found_error():
    """Create an HttpResponseError mimicking a ParentResourceNotFound 404."""
    resp = Mock(status_code=404)

    class _Error(HttpResponseError):
        def __str__(self):
            return "ParentResourceNotFound"

    return _Error(response=resp)


@pytest.mark.parametrize("ns_exists", [True, False], ids=["credential-missing", "namespace-missing"])
def test_show_policy_not_found(fixture_policy_provider, ns_exists):
    """Show raises appropriate error when namespace or credential is missing."""
    _assert_not_found(fixture_policy_provider, "show",
                      {"policy_name": "p", "namespace_name": "ns", "resource_group_name": "rg"},
                      ns_exists)


@pytest.mark.parametrize("ns_exists", [True, False], ids=["credential-missing", "namespace-missing"])
def test_list_policies_not_found(fixture_policy_provider, ns_exists):
    """List raises appropriate error when namespace or credential is missing."""
    _assert_not_found(fixture_policy_provider, "list",
                      {"namespace_name": "ns", "resource_group_name": "rg"},
                      ns_exists)


def _assert_not_found(provider, method_name, kwargs, namespace_exists):
    """
    If the namespace exists but credential doesn't → friendly ResourceNotFoundError.
    If the namespace itself is missing → raw HttpResponseError propagates.
    """
    resp_404 = Mock(status_code=404)

    if namespace_exists:
        provider.client.namespaces.get.return_value = Mock()
        error = _make_parent_not_found_error()
        target = (
            provider.client.policies.list_by_resource_group
            if method_name == "list"
            else provider.client.policies.get
        )
        target.side_effect = error

        with pytest.raises(ResourceNotFoundError, match="No credential exists"):
            getattr(provider, method_name)(**kwargs)
    else:
        provider.client.namespaces.get.side_effect = HttpResponseError(response=resp_404)

        with pytest.raises(HttpResponseError):
            getattr(provider, method_name)(**kwargs)
