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


@pytest.mark.parametrize("region,endpoint", [
    ("usgovvirginia", subject.GOVERNMENT_ARM), ("chinaeast2", subject.CHINA_ARM),
])
def test_sovereign_target_requires_exact_scope_and_receipt(monkeypatch, region, endpoint):
    expected = {"region": region, "endpoint": endpoint}
    assert subject.target(region) == expected
    assert not subject.matches({}, expected)
    monkeypatch.delenv("azext_iot_test_subscription", raising=False)
    with pytest.raises(ValueError, match="explicit subscription"):
        subject.scope(endpoint)
    subscription, group = "00000000-0000-0000-0000-000000000001", "sovereign-tests"
    monkeypatch.setenv("azext_iot_test_subscription", subscription)
    monkeypatch.setenv("azext_iot_testrg", group)
    subject.public_scope(subscription, group, **expected)
    with pytest.raises(ValueError, match="authorized subscription"):
        subject.public_scope(subscription, "foreign", **expected)
    assert subject.matches({"target": expected}, expected)
    assert not subject.matches({"target": subject.target()}, expected)


@pytest.mark.parametrize("region,endpoint", [
    ("usgovvirginia", subject.PUBLIC_ARM), ("chinaeast2", subject.GOVERNMENT_ARM),
    ("australiaeast", subject.CHINA_ARM),
])
def test_cross_cloud_region_is_rejected(region, endpoint):
    with pytest.raises(ValueError, match="same cloud"):
        subject.target(region, endpoint)


@pytest.mark.parametrize("group", ["sovereign-tests", "Fairfax-IoT-RG"])
def test_sovereign_ownership_keeps_scope_and_cloud_boundaries(monkeypatch, group):
    import runpy
    from pathlib import Path

    subscription = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setenv("azext_iot_test_subscription", subscription)
    monkeypatch.setenv("azext_iot_testrg", group)
    owned = runpy.run_path(str(Path(subject.__file__).with_name("_hub_ownership.py")))
    owned.update(owned["configure_target"]("usgovvirginia"))
    resource = f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.Devices/IotHubs/test"
    assert owned["scope_id"](resource)
    assert not owned["scope_id"](resource.replace(group, "foreign"))
    assert owned["arm_location"](subject.GOVERNMENT_ARM + resource).hostname == "management.usgovcloudapi.net"
    with pytest.raises(owned["OwnershipError"], match="Unplanned ARM"):
        owned["arm_location"](subject.PUBLIC_ARM + resource)
    assert owned["AUDIENCE"] == subject.CLOUDS[subject.GOVERNMENT_ARM]["audience"]
