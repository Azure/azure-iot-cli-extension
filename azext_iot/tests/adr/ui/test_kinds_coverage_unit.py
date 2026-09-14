# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Provider-shaped namespace and link projections, including partial preview payloads."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from azext_iot.adr.ui.core.table import TableModel
from azext_iot.adr.ui.kinds import _common, job, link, namespace
from azext_iot.adr.ui.theme import DEFAULT_THEME, normalize_theme


def test_partial_payload_helpers_preserve_values_and_supply_defaults():
    assert _common.dig({"properties": []}, "properties", "name", default="missing") == "missing"
    extract = _common.field("identity", "type", default="None")
    assert extract({"identity": {"type": "SystemAssigned"}}) == "SystemAssigned"
    assert extract({"identity": None}) == "None"
    assert _common.name_column(label="RESOURCE", width=12).text({"id": "/resources/last/"}) == "last"
    assert _common.age_column().text({}) == ""
    assert normalize_theme(" DEFAULT ") == DEFAULT_THEME


@pytest.mark.parametrize("delta, expected", [
    (timedelta(seconds=-1), "0s"),
    (timedelta(seconds=12), "12s"),
    (timedelta(minutes=12), "12m"),
    (timedelta(hours=3), "3h"),
    (timedelta(days=4), "4d"),
])
@pytest.mark.parametrize("naive", [False, True])
def test_age_units_with_frozen_clock(monkeypatch, delta, expected, naive):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(_common, "datetime", Clock)
    moment = now - delta
    if naive:
        moment = moment.replace(tzinfo=None)
    assert _common.humanize_age(moment.isoformat()) == expected


@pytest.mark.parametrize("state, identity, dps, hubs, expected", [
    ("fAiLeD", "SystemAssigned", 1, 1, "blocked"),
    ("Canceled", "SystemAssigned", 1, 1, "blocked"),
    ("Succeeded", "None", 1, 1, "needs identity"),
    ("Succeeded", "SystemAssigned", 0, 1, "needs DPS"),
    ("Succeeded", "UserAssigned", 1, 0, "needs Hub"),
    ("Succeeded", "SystemAssigned", 1, 2, "ready"),
])
def test_namespace_readiness_reflects_endpoint_dependencies(state, identity, dps, hubs, expected):
    payload = {
        "identity": {"type": identity},
        "properties": {
            "provisioningState": state,
            "provisioning": {"endpoints": {str(i): {} for i in range(dps)}},
            "messaging": {"endpoints": {str(i): {} for i in range(hubs)}},
        },
    }
    spec = namespace.build(Mock())
    assert spec.column("readiness").text(payload) == expected
    assert spec.column("readiness").style(payload) == {
        "blocked": "error", "ready": "active",
    }.get(expected, "warn")
    assert spec.column("dps").extract(payload) == dps
    assert spec.column("hubs").extract(payload) == hubs


def test_link_rows_disambiguate_names_and_summarize_known_endpoint_types():
    session = Mock()
    payloads = [
        {"name": "same", "endpointType": "Microsoft.Devices/IotHubs",
         "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": "/identities/mi"}},
        {"name": "same", "endpointType": "Microsoft.Devices/provisioningServices",
         "inboundCallerIdentity": {"type": "SystemAssigned"}},
        {"name": "updates", "endpointType": "Microsoft.DeviceUpdate/updateInstances"},
        {"name": "future", "endpointType": "Future/type"},
    ]
    session.list_from.return_value = payloads
    spec = link.build(session)
    rows = spec.list({"namespace_name": "ns", "resource_group_name": "rg"})
    session.list_from.assert_called_once_with("link", "list_all", namespace_name="ns", resource_group_name="rg")
    model = TableModel(spec)
    model.apply(rows)
    assert [row.id for row in model.rows] == ["DPS/same", "IoT Hub/same", "Software Updates/updates", "other/future"]
    assert [spec.column("identity").text(row) for row in rows] == ["UserAssigned:mi", "SystemAssigned", "none", "none"]
    assert spec.summarize_rows(rows) == "DPS 1  ·  IoT Hubs 1  ·  Updates 1"
    assert spec.summarize_rows([]) == "DPS 0  ·  IoT Hubs 0  ·  Updates 0"
    assert spec.actions == ()


@pytest.mark.parametrize("job_type, target", [
    ("SoftwareUpdate", {
        "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
                      "Microsoft.DeviceRegistry/namespaces/ns/groups/production",
    }),
    ("OnboardingUpdate", None),
])
def test_job_columns_project_provider_target_and_update_resource_ids(job_type, target):
    properties = {
        "jobType": job_type,
        "definition": {"schedulingType": "Continuous",
                       "updateResourceId": "updates/providers/contoso/names/firmware/versions/1.2.3"},
        "provisioningState": "Succeeded",
    }
    if target is not None:
        properties["target"] = target
    payload = {"name": "rollout-not-the-update-name", "properties": properties}
    spec = job.build(Mock())
    table = TableModel(spec)
    table.apply([payload])
    cells = dict(zip((column.key for column in table.columns), table.row_at(0).cells))
    assert cells["name"] == "rollout-not-the-update-name"
    assert cells["target"] == ("production" if target else "")
    assert cells["update"] == "contoso/firmware/1.2.3"
    assert cells["type"] == job_type
    assert cells["state"] == "Succeeded"


@pytest.mark.parametrize("reference, expected", [
    (None, ""), ("", ""), ("updates/future-format", "updates/future-format"),
    ("/updates/providers/contoso/names/firmware/versions/1/", "contoso/firmware/1"),
])
def test_job_update_column_does_not_mislabel_missing_or_unknown_references(reference, expected):
    payload = {"name": "not-an-update", "properties": {"definition": {"updateResourceId": reference}}}
    assert job.build(Mock()).column("update").text(payload) == expected
