# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.tests import _integration_target as subject


@pytest.mark.parametrize("region", ["centraluseuap", "australiaeast", "westeurope", "westus3", "futurepublicregion"])
@pytest.mark.parametrize("explicit", [False, True])
def test_only_authorized_region_endpoint_pairs(region, explicit):
    endpoint = subject.CANARY_ARM if region == "centraluseuap" else subject.PUBLIC_ARM
    expected = {"region": region, "endpoint": endpoint}
    assert subject.target(region, endpoint if explicit else None) == expected
    assert subject.matches({"target": expected}, expected)
    assert subject.matches({}, expected) == (region == "centraluseuap")
    assert not subject.matches({"target": None}, expected)
    subject.public_scope(subject.SUBSCRIPTION, subject.RESOURCE_GROUP, region)


@pytest.mark.parametrize("region,endpoint", [
    ("west us", None), ("AustraliaEast", None), ("", None), (None, None), ("a" * 65, None),
    ("australiaeast", "https://centraluseuap.management.azure.com"),
    ("westeurope", "https://centraluseuap.management.azure.com"),
    ("australiaeast", "http://management.azure.com"),
    ("australiaeast", "https://management.azure.com.invalid"),
    ("westus", "public"), ("westus", False),
])
def test_wrong_target_is_rejected(region, endpoint):
    with pytest.raises(ValueError, match="not authorized|requires region|region identifier"):
        subject.target(region, endpoint)


@pytest.mark.parametrize("subscription,group", [
    ("foreign", subject.RESOURCE_GROUP), (subject.SUBSCRIPTION, "foreign"),
])
@pytest.mark.parametrize("region", ["australiaeast", "westeurope", "centraluseuap"])
def test_public_target_preserves_explicit_authorized_resource_scope(subscription, group, region):
    with pytest.raises(ValueError, match="authorized subscription"):
        subject.public_scope(subscription, group, region, subject.PUBLIC_ARM)


def test_explicit_public_overrides_central_default_without_allowing_legacy_receipts():
    public = subject.target("centraluseuap", subject.PUBLIC_ARM)
    assert public == {"region": "centraluseuap", "endpoint": subject.PUBLIC_ARM}
    assert not subject.matches({}, public)
    assert subject.target("centraluseuap", "") == subject.target()
