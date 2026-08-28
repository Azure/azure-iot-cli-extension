# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Real resource kinds (step 8).

The providers themselves are already covered by the existing ADR suite, so these tests
assert the wiring: that each kind calls the right provider operation with the right
arguments, and that its columns tolerate the payloads the service actually returns.
"""

import pytest

from azext_iot.adr.ui.core.spec import STYLE_ERROR, STYLE_OK
from azext_iot.adr.ui.core.table import TableModel
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.kinds._common import dig, humanize_age, name_of, prop, resource_group_of, short_id


class RecordingSession:
    """Captures list_from calls instead of reaching the service."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def list_from(self, provider, method, **kwargs):
        self.calls.append((provider, method, kwargs))
        return self.results.get((provider, method), [])


@pytest.fixture
def session():
    return RecordingSession()


@pytest.fixture
def registry(session):
    return build_registry(session)


SCOPE = {
    "resource_group_name": "rg",
    "namespace_name": "ns",
    "registry_device_name": "dev1",
    "group_name": "grp1",
    "job_name": "job1",
    "certificate_authority_name": "ca1",
}


# -- registry ------------------------------------------------------------------------


def test_every_kind_registers_and_validates(registry):
    """Registration runs spec validation, so this covers all thirteen kinds at once."""
    assert len(registry) == 13


def test_namespace_is_the_root(registry):
    assert registry.roots()[0].kind == "namespace"


def test_update_instance_is_also_a_root(registry):
    """Update instances are subscription-scoped, not namespace children."""
    assert "su" in {spec.kind for spec in registry.roots()}


@pytest.mark.parametrize(
    "alias, kind",
    [
        ("ns", "namespace"), ("dev", "device"), ("rd", "device"), ("grp", "group"),
        ("jb", "job"), ("rn", "run"), ("ep", "link"), ("cert", "ca"), ("pol", "policy"),
        ("attr", "attribute"), ("cap", "capability"), ("auth", "auth"), ("mem", "member"),
    ],
)
def test_aliases_resolve(registry, alias, kind):
    assert registry.resolve(alias).kind == kind


def test_child_relationships_are_declared(registry):
    def children(kind):
        return {ref.kind for ref in registry.get(kind).children}

    assert {"device", "group", "job", "link", "ca"} <= children("namespace")
    assert {"auth", "attribute", "capability"} == children("device")
    assert children("group") == {"member"}
    assert children("job") == {"run"}
    assert children("ca") == {"policy"}


def test_auth_guide_uses_the_registered_device_name_flag(registry):
    command = registry.get("auth").guide.runs
    assert "--registry-device-name" in command
    assert " --device " not in command


def test_namespace_hierarchy_explains_every_related_collection(registry):
    children = registry.get("namespace").children
    assert [child.kind for child in children] == ["link", "device", "group", "job", "ca"]
    assert all(child.description for child in children)
    assert children[0].label == "Linked resources"


# -- provider wiring -----------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, provider, method, expected",
    [
        ("namespace", "namespace", "list", {"resource_group_name": "rg"}),
        ("device", "registry_device", "list",
         {"namespace_name": "ns", "resource_group_name": "rg"}),
        ("group", "group", "list", {"namespace_name": "ns", "resource_group_name": "rg"}),
        ("job", "job", "list", {"namespace_name": "ns", "resource_group_name": "rg"}),
        ("ca", "certificate_authority", "list",
         {"namespace_name": "ns", "resource_group_name": "rg"}),
        ("policy", "certificate_policy", "list",
         {"certificate_authority_name": "ca1", "namespace_name": "ns", "resource_group_name": "rg"}),
        ("su", "update_instance", "list", {"resource_group_name": "rg"}),
        ("auth", "registry_device", "auth_list",
         {"registry_device_name": "dev1", "namespace_name": "ns", "resource_group_name": "rg"}),
        ("attribute", "registry_device", "attribute_list",
         {"registry_device_name": "dev1", "namespace_name": "ns", "resource_group_name": "rg"}),
        ("capability", "registry_device", "capability_list",
         {"registry_device_name": "dev1", "namespace_name": "ns", "resource_group_name": "rg"}),
        ("member", "group", "list_members",
         {"group_name": "grp1", "namespace_name": "ns", "resource_group_name": "rg"}),
    ],
)
def test_kind_delegates_to_the_right_provider(registry, session, kind, provider, method, expected):
    registry.get(kind).list(SCOPE)
    assert session.calls == [(provider, method, expected)]


def test_run_list_is_scoped_to_its_parent_job(registry, session):
    registry.get("run").list(SCOPE)
    provider, method, kwargs = session.calls[0]
    assert (provider, method) == ("job_run", "list")
    assert kwargs["job_name"] == "job1"


def test_link_list_merges_the_three_endpoint_sections(registry, session):
    """Endpoints are three sections of one namespace and are read together."""
    registry.get("link").list(SCOPE)
    methods = [method for _, method, _ in session.calls]
    assert methods == ["list_all"]


# -- scoping -------------------------------------------------------------------------


def test_namespace_contributes_its_own_resource_group(registry):
    """A namespace's children live in its resource group, which may differ from the session's."""
    payload = {"name": "ns1", "resourceGroup": "other-rg"}
    assert registry.get("namespace").child_scope(payload) == {
        "namespace_name": "ns1",
        "resource_group_name": "other-rg",
    }


def test_namespace_resource_group_is_parsed_from_the_arm_id(registry):
    payload = {
        "name": "ns1",
        "id": "/subscriptions/s/resourceGroups/parsed-rg/providers/Microsoft.DeviceRegistry/namespaces/ns1",
    }
    assert registry.get("namespace").child_scope(payload)["resource_group_name"] == "parsed-rg"


@pytest.mark.parametrize(
    "kind, key",
    [("device", "registry_device_name"), ("group", "group_name"), ("job", "job_name"),
     ("ca", "certificate_authority_name")],
)
def test_child_scope_keys_match_provider_argument_names(registry, kind, key):
    """The scope key must be exactly the keyword the child's provider expects."""
    assert registry.get(kind).child_scope({"name": "x"}) == {key: "x"}


# -- rendering -----------------------------------------------------------------------


def test_namespace_row_renders_from_a_realistic_payload(registry):
    payload = {
        "name": "factory",
        "location": "eastus2",
        "resourceGroup": "adr-rg",
        "properties": {
            "provisioningState": "Succeeded",
            "provisioning": {"endpoints": {"dps": {}}},
            "messaging": {"endpoints": {"hub-a": {}, "hub-b": {}}},
            "updating": {"endpoints": {}},
        },
        "identity": {"type": "SystemAssigned"},
        "tags": {"environment": "prod", "owner": "iot"},
    }
    model = TableModel(registry.get("namespace"))
    model.apply([payload])
    row = model.rows[0]
    assert row.cells[0] == "factory"
    cells = dict(zip(model.headers, row.cells))
    assert cells["HUBS"] == "2"
    assert cells["DPS"] == "1"
    assert cells["UPDATES"] == "0"
    assert cells["LINK READINESS"] == "ready"
    assert cells["TAGS"] == "environment=prod owner=iot"
    assert STYLE_OK in row.styles


def test_device_row_colours_enablement_and_state(registry):
    payloads = [
        {"name": "d1", "properties": {"enablementState": "Enabled", "provisioningState": "Succeeded"}},
        {"name": "d2", "properties": {"enablementState": "Disabled", "provisioningState": "Failed"}},
    ]
    model = TableModel(registry.get("device"))
    model.apply(payloads)
    assert model.rows[0].styles[1] == STYLE_OK
    assert STYLE_ERROR in model.rows[1].styles


def test_link_rows_sort_provisioning_before_messaging(registry):
    """The ordering rule is visible in the table: a hub is meaningless without a DPS."""
    payloads = [
        {"name": "hub-a", "endpointType": "Microsoft.Devices/IotHubs", "resourceId": "/x/hubs/hub-a"},
        {"name": "dps-a", "endpointType": "Microsoft.Devices/provisioningServices",
         "resourceId": "/x/provisioningServices/dps-a"},
    ]
    model = TableModel(registry.get("link"))
    model.apply(payloads)
    assert [row.cells[1] for row in model.rows] == ["DPS", "IoT Hub"]


def test_link_row_ids_are_unique_across_sections(registry):
    """Endpoint names are unique only within a section, so identity includes the type."""
    same_name = [
        {"name": "edge", "endpointType": "Microsoft.Devices/IotHubs"},
        {"name": "edge", "endpointType": "Microsoft.Devices/provisioningServices"},
    ]
    model = TableModel(registry.get("link"))
    model.apply(same_name)
    assert model.total_count == 2, "identically named endpoints must not collide"


@pytest.mark.parametrize("kind", ["namespace", "device", "group", "job", "run", "link", "ca",
                                  "policy", "su", "auth", "attribute", "capability", "member"])
def test_every_kind_survives_an_empty_payload(registry, kind):
    """Preview payloads drop fields; a missing value must render blank, never raise."""
    model = TableModel(registry.get(kind))
    model.apply([{"name": "x"}])
    assert model.total_count == 1


@pytest.mark.parametrize("kind", ["namespace", "device", "group", "job", "run", "link", "ca",
                                  "policy", "su", "auth", "attribute", "capability", "member"])
def test_every_kind_survives_a_payload_with_null_properties(registry, kind):
    model = TableModel(registry.get(kind))
    model.apply([{"name": "x", "properties": None}])
    assert model.total_count == 1


# -- extraction helpers --------------------------------------------------------------


def test_prop_prefers_properties_but_falls_back_to_top_level():
    assert prop("state")({"properties": {"state": "nested"}}) == "nested"
    assert prop("state")({"state": "flat"}) == "flat", "endpoint entries are flat"
    assert prop("state")({}) == ""


def test_dig_returns_default_on_a_missing_hop():
    assert dig({"a": {"b": 1}}, "a", "b") == 1
    assert dig({"a": None}, "a", "b", default="x") == "x"
    assert dig({}, "a", "b", default="x") == "x"


def test_short_id_takes_the_last_segment():
    assert short_id("/subscriptions/s/resourceGroups/rg/providers/x/hubs/my-hub") == "my-hub"
    assert short_id("") == ""
    assert short_id(None) == ""


def test_name_of_prefers_name():
    assert name_of({"name": "a", "id": "/x/b"}) == "a"
    assert name_of({}) == ""


def test_resource_group_parses_from_id_when_absent():
    assert resource_group_of({"resourceGroup": "direct"}) == "direct"
    assert resource_group_of({"id": "/subscriptions/s/resourceGroups/parsed/providers/x"}) == "parsed"
    assert resource_group_of({}) == ""


def test_humanize_age_is_blank_for_unparseable_values():
    assert humanize_age("") == ""
    assert humanize_age("not-a-date") == ""
    assert humanize_age(None) == ""


def test_humanize_age_formats_recent_times():
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    assert humanize_age(recent).endswith("h")


def test_name_falls_back_to_the_id_segment_not_the_whole_id():
    """Live list projections sometimes omit `name`; the full ARM id is unreadable as a row."""
    payload = {
        "id": "/subscriptions/s/resourceGroups/rg/providers/"
              "Microsoft.DeviceRegistry/namespaces/scaletest-ns-auto-583b4f42"
    }
    assert name_of(payload) == "scaletest-ns-auto-583b4f42"


def test_namespace_without_a_name_still_renders_one_readable_row(registry):
    payload = {
        "id": "/subscriptions/s/resourceGroups/rg/providers/"
              "Microsoft.DeviceRegistry/namespaces/anonymous-ns",
        "location": "eastus2euap",
        "properties": {"provisioningState": "Succeeded"},
    }
    model = TableModel(registry.get("namespace"))
    model.apply([payload])
    assert model.rows[0].cells[0] == "anonymous-ns"
    assert model.rows[0].cells[1] == "rg", "resource group is parsed from the id too"


# -- required scope ------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, required",
    [
        ("device", "namespace_name"), ("group", "namespace_name"), ("job", "namespace_name"),
        ("link", "namespace_name"), ("ca", "namespace_name"),
        ("auth", "registry_device_name"), ("attribute", "registry_device_name"),
        ("capability", "registry_device_name"), ("member", "group_name"),
        ("policy", "certificate_authority_name"),
    ],
)
def test_kinds_declare_the_scope_they_need(registry, kind, required):
    assert required in registry.get(kind).requires


def test_missing_scope_is_detected_before_any_request(registry, session):
    spec = registry.get("link")
    assert spec.missing_scope({}) == ["namespace_name", "resource_group_name"]
    assert spec.missing_scope(SCOPE) == []
    assert session.calls == [], "the check must not touch the provider"


def test_roots_need_no_scope(registry):
    assert registry.get("namespace").requires == ()
    assert registry.get("su").requires == ()


def test_blank_scope_values_count_as_missing(registry):
    assert "namespace_name" in registry.get("device").missing_scope({"namespace_name": ""})


def test_device_column_labels_are_unambiguous(registry):
    """Enablement and provisioning are different things and must not share a header."""
    labels = [column.label for column in registry.get("device").columns]
    assert len(labels) == len(set(labels)), f"duplicate column headers: {labels}"


@pytest.mark.parametrize("kind", ["namespace", "device", "group", "job", "run", "link", "ca",
                                  "policy", "su", "auth", "attribute", "capability", "member"])
def test_no_kind_has_duplicate_column_labels(registry, kind):
    labels = [column.label for column in registry.get(kind).columns]
    assert len(labels) == len(set(labels))
