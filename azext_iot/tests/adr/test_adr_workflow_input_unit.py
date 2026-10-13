# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError

from azext_iot.adr.workflows import input as subject
from azext_iot.adr.workflows.models import (
    EndpointSpec,
    PlanItem,
    SetupRequest,
    workflow_result,
)


SUB = "00000000-0000-0000-0000-000000000000"
RG = "test-rg"
HUB_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}"
    "/providers/Microsoft.Devices/IotHubs/hub"
)


def test_plan_item_and_workflow_result_omit_empty_fields():
    item = PlanItem("namespace", "check", "ns", "Satisfied")
    assert item.as_dict() == {
        "id": "namespace",
        "action": "check",
        "target": "ns",
        "state": "Satisfied",
    }

    detailed = PlanItem(
        "hub",
        "link",
        "hub",
        "Planned",
        message="pending",
        command="az test",
        dependencies=("namespace",),
        details={"resourceId": HUB_ID},
    )
    result = workflow_result("cmd", "Planned", "ns", RG, [item, detailed])
    assert result["summary"] == {"Satisfied": 1, "Planned": 1}
    assert result["items"][1]["dependencies"] == ["namespace"]


def test_setup_request_reports_link_intent():
    assert not SetupRequest("ns", RG).requests_links
    endpoint = EndpointSpec("hub", "hub", HUB_ID, "system-assigned")
    assert SetupRequest("ns", RG, hubs=(endpoint,)).requests_links


def test_parse_endpoint_from_id_and_name():
    by_id = subject.parse_endpoint(
        ["name=primary", f"resource-id={HUB_ID}", "identity=system-assigned"],
        "hub",
        RG,
        SUB,
    )
    assert by_id.endpoint_name == "primary"
    assert by_id.identity_type == "system-assigned"

    by_name = subject.parse_endpoint(
        [
            "resource-name=other",
            "resource-group=other-rg",
            f"identity=/subscriptions/{SUB}/resourceGroups/r/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/u",
            "allocation-weight=4",
        ],
        "hub",
        RG,
        SUB,
    )
    assert "/resourceGroups/other-rg/" in by_name.resource_id
    assert by_name.endpoint_name == "other"
    assert by_name.identity_type == "user-assigned"
    assert by_name.allocation_weight == 4
    assert subject.parse_endpoint(None, "hub", RG, SUB) is None


@pytest.mark.parametrize(
    "values, expected",
    [
        (["bad"], "key=value"),
        (["name="], "cannot be empty"),
        (["unknown=value"], "Unsupported"),
        (["name=a", "name=b"], "more than once"),
        (["name=a", "resource-id=/x"], "requires identity"),
        (["name=a", "resource-id=/x", "identity=bad"], "UAMI ARM"),
        (["name=a", "identity=system-assigned"], "requires resource-id"),
        (
            [
                "name=a",
                f"resource-id={HUB_ID}",
                "identity=system-assigned",
                "allocation-weight=bad",
            ],
            "integer",
        ),
    ],
)
def test_parse_endpoint_rejects_invalid_values(values, expected):
    with pytest.raises(InvalidArgumentValueError, match=expected):
        subject.parse_endpoint(values, "hub", RG, SUB)


def test_build_setup_request_from_arguments():
    request = subject.build_setup_request(
        namespace_name="ns",
        resource_group_name=RG,
        subscription_id=SUB,
        namespace_outbound_identity="system-assigned",
        hubs=[[
            "name=primary",
            f"resource-id={HUB_ID}",
            "identity=system-assigned",
        ]],
    )
    assert request.outbound_identity_type == "SystemAssigned"
    assert request.hubs[0].resource_id == HUB_ID


def test_setup_request_leaves_role_ownership_to_link_provider():
    request = subject.build_setup_request(
        namespace_name="ns",
        resource_group_name=RG,
        subscription_id=SUB,
        namespace_outbound_identity="system-assigned",
    )
    assert not hasattr(request, "assign_roles")


def test_config_builds_without_workflow_role_policy(tmp_path):
    config = tmp_path / "setup.yaml"
    config.write_text(
        """
namespace:
  name: ns
  resourceGroup: rg
  outboundIdentity:
    type: SystemAssigned
links: {}
""",
        encoding="utf-8",
    )
    request = subject.build_setup_request(
        None, None, SUB, config=str(config)
    )
    assert request.namespace_name == "ns"
    assert not hasattr(request, "assign_roles")


def test_build_setup_request_supports_uami_and_complete_connectivity():
    uami = (
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/u"
    )
    request = subject.build_setup_request(
        namespace_name="ns",
        resource_group_name=RG,
        subscription_id=SUB,
        namespace_outbound_identity=uami,
        dps=[
            "name=dps",
            "resource-name=dps",
            "identity=system-assigned",
        ],
        hubs=[[
            "name=hub",
            "resource-name=hub",
            "identity=system-assigned",
        ]],
        complete_connectivity=True,
    )
    assert request.outbound_identity_type == "UserAssigned"
    assert request.outbound_user_assigned_identity == uami
    assert "/provisioningServices/dps" in request.dps.resource_id


def test_build_setup_request_loads_yaml_config(tmp_path):
    config = tmp_path / "setup.yaml"
    config.write_text(
        f"""
namespace:
  name: config-ns
  resourceGroup: config-rg
  location: eastus
  outboundIdentity:
    type: SystemAssigned
links:
  hubs:
    - endpointName: primary
      resourceId: {HUB_ID}
      identity:
        type: SystemAssigned
""",
        encoding="utf-8",
    )
    request = subject.build_setup_request(
        namespace_name=None,
        resource_group_name=None,
        subscription_id=SUB,
        config=str(config),
    )
    assert request.namespace_name == "config-ns"
    assert request.resource_group_name == "config-rg"
    assert request.location == "eastus"
    assert request.hubs[0].endpoint_name == "primary"


def test_config_rejects_cli_scope_conflict_and_assign_roles(tmp_path):
    config = tmp_path / "setup.yaml"
    config.write_text(
        """
namespace:
  name: config-ns
  resourceGroup: config-rg
  location: westus
  outboundIdentity:
    type: SystemAssigned
links: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidArgumentValueError, match="namespace.name conflicts"):
        subject.build_setup_request(
            namespace_name="cli-ns",
            resource_group_name="cli-rg",
            subscription_id=SUB,
            location="eastus",
            config=str(config),
        )

    config.write_text("assignRoles: false\n", encoding="utf-8")
    with pytest.raises(InvalidArgumentValueError, match="no longer supported"):
        subject.build_setup_request("ns", RG, SUB, config=str(config))


@pytest.mark.parametrize(
    "content, expected",
    [
        (
            """
namespace: []
links: {}
""",
            "namespace",
        ),
        (
            """
namespace:
  name: ns
  resourceGroup: rg
  outboundIdentity:
    type: SystemAssigned
links:
  hubs: {}
""",
            "links.hubs",
        ),
        (
            """
namespace:
  name: ns
  resourceGroup: rg
  outboundIdentity:
    type: SystemAssigned
links:
  hubs:
    - {}
""",
            "non-empty object",
        ),
    ],
)
def test_build_setup_request_rejects_malformed_config(
    tmp_path, content, expected
):
    config = tmp_path / "setup.yaml"
    config.write_text(content, encoding="utf-8")
    with pytest.raises(InvalidArgumentValueError, match=expected):
        subject.build_setup_request(None, None, SUB, config=str(config))


def test_config_pairs_supports_boolean_and_rejects_invalid_identity():
    assert subject._config_pairs({"createIfMissing": True}) == [
        "create-if-missing=true"
    ]
    with pytest.raises(InvalidArgumentValueError, match="Config endpoint identity"):
        subject._config_pairs({"identity": {"type": "Invalid"}})


def test_config_rejects_non_object_namespace_tags(tmp_path):
    config = tmp_path / "setup.yaml"
    config.write_text(
        "namespace:\n"
        "  name: ns\n"
        f"  resourceGroup: {RG}\n"
        "  tags: invalid\n"
        "  outboundIdentity:\n"
        "    type: SystemAssigned\n"
        "links: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidArgumentValueError, match="namespace.tags"):
        subject.build_setup_request(
            None, None, SUB, config=str(config)
        )


def test_explicit_empty_tags_are_preserved():
    request = subject.build_setup_request(
        "ns",
        RG,
        SUB,
        tags={},
        namespace_outbound_identity="system-assigned",
    )
    assert request.tags == {}


def test_build_setup_request_uses_split_endpoint_validators():
    resources = []
    identities = []
    request = subject.build_setup_request(
        "ns",
        RG,
        SUB,
        hubs=[[
            "resource-id=" + HUB_ID,
            "identity=system-assigned",
        ]],
        validate_endpoint_resource=lambda endpoint, allow_missing: (
            resources.append((endpoint, allow_missing)) or {"id": HUB_ID}
        ),
        validate_endpoint_identity=lambda endpoint, resource: (
            identities.append((endpoint, resource))
        ),
    )
    assert resources == [(request.hubs[0], False)]
    assert identities == [(request.hubs[0], {"id": HUB_ID})]


def test_build_setup_request_validates_supplied_resources():
    calls = []
    endpoint_calls = []
    identity_calls = []
    uami = (
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/u"
    )
    request = subject.build_setup_request(
        namespace_name="ns",
        resource_group_name=RG,
        subscription_id=SUB,
        namespace_outbound_identity=uami,
        hubs=[[
            "endpoint=hub",
            f"resource-id={HUB_ID}",
            "identity=system-assigned",
        ]],
        validate_resource_group=lambda value: calls.append(("group", value)),
        validate_namespace=lambda name, group: calls.append(
            ("namespace", name, group)
        ),
        validate_endpoint_resource=lambda endpoint, allow_missing: endpoint_calls.append(
            (endpoint, allow_missing)
        ),
        validate_identity=identity_calls.append,
    )
    assert request.namespace_name == "ns"
    assert calls == [("group", RG), ("namespace", "ns", RG)]
    assert endpoint_calls == [(request.hubs[0], False)]
    assert identity_calls == [uami]


def test_build_setup_request_software_updates_creation():
    request = subject.build_setup_request(
        namespace_name="ns",
        resource_group_name=RG,
        subscription_id=SUB,
        namespace_outbound_identity="system-assigned",
        software_updates=[
            "name=su",
            "resource-name=updates",
            "identity=system-assigned",
            "create-if-missing=true",
        ],
    )
    assert request.create_update_instance
    assert request.update_instance_name == "updates"


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (
            {
                "namespace_name": "ns",
                "resource_group_name": RG,
                "subscription_id": SUB,
                "config": "file",
                "namespace_outbound_identity": "system-assigned",
            },
            "cannot be combined",
        ),
        (
            {
                "namespace_name": None,
                "resource_group_name": RG,
                "subscription_id": SUB,
                "namespace_outbound_identity": "system-assigned",
            },
            "--name",
        ),
        (
            {
                "namespace_name": "ns",
                "resource_group_name": RG,
                "subscription_id": SUB,
                "namespace_outbound_identity": "bad",
            },
            "outbound-identity",
        ),
        (
            {
                "namespace_name": "ns",
                "resource_group_name": RG,
                "subscription_id": SUB,
                "namespace_outbound_identity": "system-assigned",
                "complete_connectivity": True,
            },
            "requires both",
        ),
    ],
)
def test_build_setup_request_rejects_invalid_combinations(mocker, kwargs, expected):
    if kwargs.get("config"):
        mocker.patch.object(subject, "_read_config", return_value={})
    with pytest.raises((ArgumentUsageError, InvalidArgumentValueError), match=expected):
        subject.build_setup_request(**kwargs)


def test_build_setup_request_requires_explicit_capabilities():
    # Strict requests never create default resources; only guided setup proposes them.
    with pytest.raises(ArgumentUsageError, match="Specify .*to be guided"):
        subject.build_setup_request("ns", RG, SUB)


def test_build_setup_request_allows_reusing_existing_outbound_identity():
    request = subject.build_setup_request(
        "ns",
        RG,
        SUB,
        hubs=[[
            "name=hub",
            f"resource-id={HUB_ID}",
            "identity=system-assigned",
        ]],
    )
    assert request.outbound_identity_type is None


def test_scope_validation_fails_immediately():
    with pytest.raises(RuntimeError, match="missing"):
        subject.resolve_scope_inputs(
            "ns",
            "rg",
            validate_resource_group=lambda _: (
                _ for _ in ()
            ).throw(RuntimeError("missing")),
        )
    with pytest.raises(RuntimeError, match="missing"):
        subject.resolve_scope_inputs(
            "ns",
            "rg",
            validate_namespace=lambda *_: (
                _ for _ in ()
            ).throw(RuntimeError("missing")),
        )


def test_resolve_scope_inputs_normalizes_and_validates_scope():
    resource_group_id = f"/subscriptions/{SUB}/resourceGroups/{RG}"
    calls = []
    result = subject.resolve_scope_inputs(
        "ns",
        resource_group_id,
        subscription_id=SUB,
        validate_resource_group=lambda value: calls.append(("group", value)),
        validate_namespace=lambda name, group: calls.append(
            ("namespace", name, group)
        ),
    )
    assert result == ("ns", RG)
    assert calls == [("group", RG), ("namespace", "ns", RG)]

    with pytest.raises(InvalidArgumentValueError, match="active subscription"):
        subject.resolve_scope_inputs(
            "ns",
            "/subscriptions/other/resourceGroups/rg",
            subscription_id=SUB,
        )


def test_resolve_scope_inputs_rejects_missing_scope():
    with pytest.raises(ArgumentUsageError, match="resource-group"):
        subject.resolve_scope_inputs(None, None)
    with pytest.raises(ArgumentUsageError, match="--name"):
        subject.resolve_scope_inputs(None, "rg")


def test_read_config_and_write_helpers(tmp_path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(InvalidArgumentValueError, match="Unable to read"):
        subject._read_config(str(missing))

    malformed = tmp_path / "bad.yaml"
    malformed.write_text("[", encoding="utf-8")
    with pytest.raises(InvalidArgumentValueError, match="not valid"):
        subject._read_config(str(malformed))

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("value", encoding="utf-8")
    with pytest.raises(InvalidArgumentValueError, match="object"):
        subject._read_config(str(scalar))
    assert subject._config_pairs(None) is None

    script = tmp_path / "plan.sh"
    subject.write_script_file(str(script), ["az one", "", "az two"])
    assert script.read_text(encoding="utf-8").endswith("az one\naz two\n")


def test_check_script_destination_writes_nothing(tmp_path, mocker, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subject.check_script_destination("plan.sh")
    subject.check_script_destination(str(tmp_path / "new.sh"))
    existing = tmp_path / "old.sh"
    existing.write_text("keep", encoding="utf-8")
    subject.check_script_destination(str(existing))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["old.sh"]
    assert existing.read_text(encoding="utf-8") == "keep"
    with pytest.raises(ArgumentUsageError, match="is a folder"):
        subject.check_script_destination(str(tmp_path))
    with pytest.raises(ArgumentUsageError, match="doesn't exist"):
        subject.check_script_destination(str(tmp_path / "missing" / "plan.sh"))
    access = mocker.patch.object(subject.os, "access", return_value=False)
    with pytest.raises(ArgumentUsageError, match="isn't writable"):
        subject.check_script_destination(str(existing))
    access.assert_called_once_with(existing, subject.os.W_OK)


def test_write_receipt_file(tmp_path, mocker):
    mocker.patch.dict(
        subject.os.environ, {"AZURE_CONFIG_DIR": str(tmp_path)}
    )
    path = subject.write_receipt_file({"state": "Succeeded"})
    assert subject.Path(path).name.startswith("setup-")
    assert path.endswith(".json")
    assert json.loads(
        subject.Path(path).read_text(encoding="utf-8")
    )["state"] == "Succeeded"
    second = subject.write_receipt_file({"state": "Failed"})
    assert second != path
