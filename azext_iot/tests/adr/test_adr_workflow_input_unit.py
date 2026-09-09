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
            "identity=/subscriptions/s/resourceGroups/r/providers/"
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


def test_resource_browse_and_exact_fallback():
    messages = []
    resource_id = HUB_ID
    assert subject._resource_input(
        "IoT Hub",
        "hub",
        lambda _: "1",
        messages.append,
        browse=lambda _: [{
            "id": resource_id,
            "name": "hub",
            "location": "eastus",
            "sku": "S1",
            "provisioningState": "Succeeded",
        }],
    ) == f"resource-id={resource_id}"
    assert any("hub · eastus · S1 · Succeeded" in item for item in messages)

    answers = iter(["exact-hub"])
    messages.clear()
    assert subject._resource_input(
        "IoT Hub",
        "hub",
        lambda _: next(answers),
        messages.append,
        browse=lambda _: (_ for _ in ()).throw(
            RuntimeError("list denied")
        ),
    ) == "resource-name=exact-hub"
    assert "Enter an exact name or ARM ID" in messages[0]
    assert "2 linked hub(s)" in subject._resource_choice_label({
        "name": "dps",
        "linkedHubs": ["one", "two"],
    })

    answers = iter(["manual"])
    assert subject._resource_input(
        "IoT Hub",
        "hub",
        lambda _: next(answers),
        lambda _: None,
        browse=lambda _: [{"id": HUB_ID, "name": "hub"}],
    ) == "resource-name=manual"


def test_resource_group_metadata_includes_compact_tags():
    label = subject._resource_choice_label({
        "name": "rg",
        "location": "eastus",
        "tags": {
            "environment": "production",
            "owner": "device-platform",
        },
    })
    assert "eastus" in label
    assert "environment=production" in label
    assert "owner=device-platform" in label


def test_scope_browse_and_denied_fallback():
    messages = []
    assert subject._browse_or_exact(
        "resource group",
        lambda: [{"name": RG, "location": "eastus"}],
        lambda _: "1",
        messages.append,
    ) == RG

    answers = iter(["manual-rg"])
    assert subject._browse_or_exact(
        "resource group",
        lambda: (_ for _ in ()).throw(RuntimeError("forbidden")),
        lambda _: next(answers),
        messages.append,
    ) == "manual-rg"
    assert any("Unable to browse resource groups" in item for item in messages)

    answers = iter(["new-ns"])
    assert subject._browse_or_exact(
        "namespace",
        lambda: [{"name": "existing"}],
        lambda _: next(answers),
        messages.append,
        allow_new=True,
    ) == "new-ns"


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


def test_build_setup_request_runs_real_guided_configuration():
    answers = iter(["1", "1", "1", "6"])
    request = subject.build_setup_request(
        "ns",
        RG,
        SUB,
        interactive=True,
        prompt=lambda _: next(answers),
        write=lambda _: None,
    )
    assert request.outbound_identity_type == "SystemAssigned"


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


def test_config_preserves_cli_scope_and_rejects_assign_roles(tmp_path):
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
    request = subject.build_setup_request(
        namespace_name="cli-ns",
        resource_group_name="cli-rg",
        subscription_id=SUB,
        location="eastus",
        config=str(config),
    )
    assert request.namespace_name == "cli-ns"
    assert request.resource_group_name == "cli-rg"
    assert request.location == "eastus"

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
            "namespace and links",
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
            None, None, SUB, config=str(config), no_input=True
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


def test_build_setup_request_uses_guided_values(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(subject.sys.stderr, "isatty", return_value=True)
    mocker.patch.object(
        subject,
        "_guided_configuration",
        return_value={
            "outbound_identity": "system-assigned",
            "skipped": (),
            "check_status": False,
        },
    )
    request = subject.build_setup_request("ns", RG, SUB)
    assert request.outbound_identity_type == "SystemAssigned"


def test_build_setup_request_wires_guided_validation(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(subject.sys.stderr, "isatty", return_value=True)
    endpoint = EndpointSpec(
        "hub", "hub", HUB_ID, "system-assigned"
    )
    resources = []
    identities = []

    calls = {"reuse": False}

    def guided(**kwargs):
        calls["reuse"] = kwargs["allow_identity_reuse"]
        resource = kwargs["validate_resource"](
            "hub", ["resource-id=" + HUB_ID]
        )
        kwargs["validate_endpoint_identity"](
            "hub",
            [
                "resource-id=" + HUB_ID,
                "identity=system-assigned",
            ],
            resource,
        )
        return {
            "outbound_identity": "system-assigned",
            "hubs": [[
                "resource-id=" + HUB_ID,
                "identity=system-assigned",
            ]],
        }

    mocker.patch.object(
        subject, "_guided_configuration", side_effect=guided
    )
    request = subject.build_setup_request(
        "ns",
        RG,
        SUB,
        write=lambda _: None,
        validate_endpoint_resource=lambda item, missing: (
            resources.append((item, missing)) or {"id": HUB_ID}
        ),
        validate_endpoint_identity=lambda item, resource: (
            identities.append((item, resource))
        ),
        can_reuse_identity=lambda *_: True,
    )
    assert request.hubs[0].resource_id == endpoint.resource_id
    assert calls["reuse"]
    assert len(resources) == 1
    assert len(identities) == 1


def test_build_setup_request_handles_back_at_first_choice(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(subject.sys.stderr, "isatty", return_value=True)
    mocker.patch.object(subject, "_is_interactive", return_value=True)
    guided = mocker.patch.object(
        subject,
        "_guided_configuration",
        side_effect=[
            subject.BackRequested(),
            {
                "outbound_identity": "system-assigned",
                "skipped": (),
                "check_status": False,
            },
        ],
    )
    prompt = mocker.Mock(side_effect=["ns", "new-ns"])
    messages = []
    request = subject.build_setup_request(
        None, RG, SUB, prompt=prompt, write=messages.append
    )
    assert request.outbound_identity_type == "SystemAssigned"
    assert guided.call_count == 2
    assert request.namespace_name == "new-ns"
    assert prompt.call_count == 2


def test_back_preserves_fixed_namespace(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(subject.sys.stderr, "isatty", return_value=True)
    guided = mocker.patch.object(
        subject,
        "_guided_configuration",
        side_effect=[
            subject.BackRequested(),
            {
                "outbound_identity": "system-assigned",
                "skipped": (),
                "check_status": False,
            },
        ],
    )
    messages = []
    request = subject.build_setup_request(
        "fixed-ns", RG, SUB, write=messages.append
    )
    assert request.namespace_name == "fixed-ns"
    assert guided.call_count == 2
    assert any("command input" in message for message in messages)


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
        validate_endpoint=lambda endpoint, allow_missing: endpoint_calls.append(
            (endpoint, allow_missing)
        ),
        validate_identity=identity_calls.append,
    )
    assert request.namespace_name == "ns"
    assert calls == [("group", RG), ("namespace", "ns", RG)]
    assert endpoint_calls == [(request.hubs[0], False)]
    assert identity_calls == [uami]


def test_build_setup_request_routes_scope_recovery_to_workspace():
    messages = []
    answers = iter(["edit", "good-rg", "new-ns"])
    validations = {"count": 0}

    def validate_group(_):
        validations["count"] += 1
        if validations["count"] == 1:
            raise RuntimeError("missing resource group")

    request = subject.build_setup_request(
        namespace_name="old-ns",
        resource_group_name="bad-rg",
        subscription_id=SUB,
        namespace_outbound_identity="system-assigned",
        interactive=True,
        prompt=lambda _: next(answers),
        write=messages.append,
        validate_resource_group=validate_group,
    )
    assert request.resource_group_name == "good-rg"
    assert request.namespace_name == "new-ns"
    assert "! missing resource group" in messages
    assert "What would you like to do?" in messages
    assert not any(
        message.startswith("Selected:") for message in messages
    )


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


def test_build_setup_request_rejects_noninteractive_empty_input(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=False)
    mocker.patch.object(subject.sys.stderr, "isatty", return_value=False)
    with pytest.raises(ArgumentUsageError, match="Specify"):
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


@pytest.mark.parametrize(
    "choice, expected_key",
    [
        ("1", "outbound_identity"),
        ("2", "dps"),
        ("3", "hubs"),
        ("4", "software_updates"),
        ("5", "dps"),
    ],
)
def test_guided_values(mocker, choice, expected_key):
    answers = {
        "1": [choice, "1"],
        "2": [choice, "dps", "1", "1"],
        "3": [choice, "hub", "1", "1", "1"],
        "4": [choice, "su", "1", "1"],
        "5": [choice, "dps", "1", "hub", "1", "1", "1"],
    }[choice]
    mocker.patch("builtins.input", side_effect=answers)
    assert expected_key in subject._guided_values()


def test_guided_values_reprompts_invalid_choice(mocker):
    mocker.patch("builtins.input", side_effect=["9", "identity", "system"])
    messages = []
    result = subject._guided_values(write=messages.append)
    assert result["outbound_identity"] == "system-assigned"
    assert any("Choose a listed" in message for message in messages)
    assert "Selected: Namespace identity" in messages


def test_guided_values_collects_multiple_hubs(mocker):
    mocker.patch(
        "builtins.input",
        side_effect=[
            "3",
            "hub-one",
            "1",
            "2",
            "/subscriptions/s/resourceGroups/r/providers/"
            "Microsoft.Devices/IotHubs/hub-two",
            "2",
            "/uami",
            "1",
            "1",
        ],
    )
    result = subject._guided_values()
    assert len(result["hubs"]) == 2
    assert "resource-name=hub-one" in result["hubs"][0]
    assert "endpoint=hub-two" in result["hubs"][1]
    assert "identity=/uami" in result["hubs"][1]


def test_guided_values_validates_each_endpoint_immediately(mocker):
    mocker.patch(
        "builtins.input",
        side_effect=["3", "hub", "1", "1", "1"],
    )
    resource_calls = []
    identity_calls = []
    subject._guided_values(
        validate_resource=lambda kind, values: (
            resource_calls.append((kind, values)) or {"id": "hub"}
        ),
        validate_endpoint_identity=lambda kind, values, resource: (
            identity_calls.append((kind, values, resource))
        ),
    )
    assert resource_calls == [("hub", ["resource-name=hub"])]
    assert identity_calls[0][0] == "hub"
    assert identity_calls[0][2] == {"id": "hub"}


def test_guided_values_supports_identity_reuse(mocker):
    mocker.patch("builtins.input", side_effect=["identity", "3"])
    messages = []
    assert subject._guided_values(
        write=messages.append,
        allow_identity_reuse=True,
    ) == {"reuse_identity": True}
    assert "Selected: Reuse current identity" in messages


def test_reuse_current_clears_staged_identity(mocker):
    answers = iter([
        "1",
        "1",
        "1",
        "1",
        "1",
        "3",
        "6",
    ])
    result = subject._guided_configuration(
        prompt=lambda _: next(answers),
        write=lambda _: None,
        validate_resource=None,
        validate_endpoint_identity=None,
        validate_namespace_identity=None,
        allow_identity_reuse=True,
        browse=None,
    )
    assert "outbound_identity" not in result


def test_request_guided_values_preserves_staged_configuration():
    request = SetupRequest(
        "ns",
        RG,
        outbound_identity_type="UserAssigned",
        outbound_user_assigned_identity="/ns-uami",
        dps=EndpointSpec(
            "dps", "dps", "/dps", "system-assigned"
        ),
        hubs=(
            EndpointSpec(
                "hub",
                "hub",
                "/hub",
                "user-assigned",
                "/hub-uami",
                availability="Available",
                allocation_weight=3,
            ),
        ),
        software_updates=EndpointSpec(
            "software-updates",
            "su",
            "/su",
            "system-assigned",
        ),
        create_update_instance=True,
        skipped=("status",),
        check_status=True,
    )
    values = subject._request_guided_values(request)
    assert values["outbound_identity"] == "/ns-uami"
    assert "identity=system-assigned" in values["dps"]
    assert "identity=/hub-uami" in values["hubs"][0]
    assert "availability=Available" in values["hubs"][0]
    assert "allocation-weight=3" in values["hubs"][0]
    assert values["software_updates"][0] == "endpoint=su"
    assert "create-if-missing=true" in values["software_updates"]
    assert values["skipped"] == ("status",)
    assert values["check_status"]

    system = subject._request_guided_values(
        SetupRequest(
            "ns", RG, outbound_identity_type="SystemAssigned"
        )
    )
    assert system["outbound_identity"] == "system-assigned"


def test_configuration_summary_is_meaningful():
    result = {
        "outbound_identity": "system-assigned",
        "hubs": [[
            "resource-name=hub-one",
            "identity=system-assigned",
        ]],
        "dps": [
            "resource-name=dps-one",
            "identity=system-assigned",
        ],
    }
    display = subject._configuration_display(
        result, {"updates"}, True
    )
    assert display["identity"] == "SystemAssigned · staged"
    assert "hub-one" in display["hub"]
    assert display["dps"] == "dps-one · staged"
    assert display["updates"] == "skipped"
    assert subject._configuration_totals(
        result, {"updates"}, True
    ) == "3 staged · 1 skipped · 1 checked"


def test_resource_group_back_can_return_to_subscription():
    with pytest.raises(subject.BackRequested):
        subject.resolve_scope_inputs(
            None,
            None,
            interactive=True,
            prompt=lambda _: (_ for _ in ()).throw(
                subject.BackRequested()
            ),
            back_from_resource_group=True,
        )


def test_guided_configuration_stage_skip_reset_and_status():
    answers = iter([
        "1",
        "1",
        "1",
        "3",
        "2",
        "3",
        "3",
        "3",
        "2",
        "5",
        "1",
        "6",
    ])
    status_calls = []
    result = subject._guided_configuration(
        prompt=lambda _: next(answers),
        write=lambda _: None,
        validate_resource=None,
        validate_endpoint_identity=None,
        validate_namespace_identity=None,
        allow_identity_reuse=False,
        browse=None,
        probe_status=lambda name, group: status_calls.append(
            (name, group)
        ),
        namespace_name="ns",
        resource_group_name=RG,
    )
    assert result["outbound_identity"] == "system-assigned"
    assert result["skipped"] == ("dps",)
    assert result["check_status"]
    assert status_calls == [("ns", RG)]


@pytest.mark.parametrize("index", ["1", "2", "3", "4", "5"])
def test_guided_configuration_skip_and_reset_branches(index):
    answers = iter([
        index,
        "2",
        index,
        "3",
        "6",
    ])
    result = subject._guided_configuration(
        prompt=lambda _: next(answers),
        write=lambda _: None,
        validate_resource=None,
        validate_endpoint_identity=None,
        validate_namespace_identity=None,
        allow_identity_reuse=False,
        browse=None,
    )
    assert result["skipped"] == ()


def test_guided_configuration_back_action():
    answers = iter(["1", subject.BackRequested(), "6"])

    def prompt(_):
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value

    result = subject._guided_configuration(
        prompt=prompt,
        write=lambda _: None,
        validate_resource=None,
        validate_endpoint_identity=None,
        validate_namespace_identity=None,
        allow_identity_reuse=False,
        browse=None,
    )
    assert result["skipped"] == ()


def test_guided_configuration_escape_preserves_staged_state(mocker):
    mocker.patch.object(
        subject, "_select", side_effect=["identity", "done"]
    )
    mocker.patch.object(
        subject, "_action", side_effect=subject.BackRequested()
    )
    result = subject._guided_configuration(
        prompt=lambda _: "",
        write=lambda _: None,
        validate_resource=None,
        validate_endpoint_identity=None,
        validate_namespace_identity=None,
        allow_identity_reuse=False,
        browse=None,
        initial={"outbound_identity": "system-assigned"},
    )
    assert result["outbound_identity"] == "system-assigned"


def test_guided_endpoint_identity_edit_paths(mocker):
    answers = iter([
        "hub",
        "uami",
        "/first",
        "uami",
        "/second",
    ])
    actions = iter(["edit"])
    mocker.patch.object(
        subject,
        "_validation_action",
        side_effect=lambda *_: next(actions),
    )
    calls = {"count": 0}

    def validate(*_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("bad identity")

    result = subject._guided_endpoint(
        "IoT Hub",
        "hub",
        lambda _: next(answers),
        lambda _: None,
        validate_identity=validate,
    )
    assert "identity=/second" in result


def test_namespace_identity_edit_path(mocker):
    answers = iter(["identity", "uami", "/first", "uami", "/second"])
    mocker.patch.object(
        subject, "_validation_action", return_value="edit"
    )
    calls = {"count": 0}

    def validate(_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("bad identity")

    result = subject._guided_values(
        prompt=lambda _: next(answers),
        write=lambda _: None,
        validate_namespace_identity=validate,
    )
    assert result["outbound_identity"] == "/second"


@pytest.mark.parametrize(
    "key, result_key",
    [
        ("identity", "outbound_identity"),
        ("hub", "hubs"),
        ("dps", "dps"),
        ("updates", "software_updates"),
    ],
)
def test_configuration_skip_and_reset_all_items(key, result_key):
    result = {
        "outbound_identity": "system-assigned",
        "hubs": [["resource-name=hub"]],
        "dps": ["resource-name=dps"],
        "software_updates": ["resource-name=su"],
    }
    skipped = {key}
    summary = subject._configuration_display(result, skipped, False)
    assert summary[key] == "skipped"
    assert result_key in result


def test_select_delegates_to_renderer():
    class Renderer:
        def select(
            self,
            title,
            options,
            guidance=None,
            allow_custom=False,
            show_options=False,
        ):
            assert title == "Title"
            assert options["one"][0] == "value"
            assert guidance is None
            assert not allow_custom
            assert not show_options
            return "value"

    renderer = Renderer()
    assert subject.select_value(
        "Title",
        {"one": ("value", "Label")},
        renderer.select,
        lambda _: None,
    ) == "value"


def test_action_delegates_to_renderer():
    class Renderer:
        def prompt(self, _):
            return ""

        def action(self, title, actions, default=None):
            assert title == "Recover?"
            assert actions == {"r": "retry"}
            assert default == "r"
            return "r"

    renderer = Renderer()
    assert subject._action(
        "Recover?",
        {"r": "retry"},
        renderer.prompt,
        lambda _: None,
        default="r",
    ) == "r"


def test_prompt_phase_follows_scope_and_configuration(mocker):
    class Renderer:
        def __init__(self):
            self.phases = []
            self.answers = iter(["rg", "ns"])

        def phase(self, name):
            self.phases.append(name)

        def prompt(self, _):
            return next(self.answers)

    renderer = Renderer()
    assert subject.resolve_scope_inputs(
        None,
        None,
        interactive=True,
        prompt=renderer.prompt,
    ) == ("ns", "rg")
    assert renderer.phases == ["Resource group", "Namespace"]

    mocker.patch.object(
        subject,
        "_guided_configuration",
        return_value={
            "outbound_identity": "system-assigned",
            "skipped": (),
            "check_status": False,
        },
    )
    subject.build_setup_request(
        "ns",
        RG,
        SUB,
        interactive=True,
        prompt=renderer.prompt,
    )
    assert renderer.phases[-1] == "Configuration"


def test_guided_endpoint_back_from_identity_edits_resource():
    answers = iter([
        "old-hub",
        "new-hub",
        "system",
    ])

    def prompt(_):
        value = next(answers)
        if value == "old-hub":
            return value
        if value == "new-hub":
            return value
        return value

    identity_prompts = {"count": 0}

    def navigation_prompt(label):
        if "name or ARM" in label:
            return prompt(label)
        identity_prompts["count"] += 1
        if identity_prompts["count"] == 1:
            raise subject.BackRequested()
        return prompt(label)

    result = subject._guided_endpoint(
        "IoT Hub",
        "hub",
        navigation_prompt,
        lambda _: None,
    )
    assert "resource-name=new-hub" in result


def test_validation_back_edits_input():
    def prompt(_):
        raise subject.BackRequested()

    assert subject._validation_action(
        RuntimeError("missing"), prompt, lambda _: None
    ) == "edit"


def test_validation_actions_retry_edit_and_quit():
    messages = []
    assert subject._validation_action(
        RuntimeError("missing"),
        lambda _: "r",
        messages.append,
    ) == "retry"
    assert subject._validation_action(
        RuntimeError("missing"),
        lambda _: "e",
        messages.append,
    ) == "edit"
    with pytest.raises(subject.WorkflowCancelled):
        subject._validation_action(
            RuntimeError("missing"),
            lambda _: "q",
            messages.append,
        )
    with pytest.raises(subject.BackRequested):
        subject._validation_action(
            subject.BackRequested(),
            lambda _: "r",
            messages.append,
        )


def test_guided_endpoint_retries_and_edits_resource(mocker):
    actions = iter(["retry", "edit"])
    mocker.patch.object(
        subject,
        "_validation_action",
        side_effect=lambda *_: next(actions),
    )
    resources = iter(["first", "second"])
    validation_calls = {"count": 0}

    def prompt(label):
        if "name or ARM" in label:
            return next(resources)
        return "system"

    def validate_resource(*_):
        validation_calls["count"] += 1
        if validation_calls["count"] < 3:
            raise RuntimeError("missing")
        return {"id": "second"}

    result = subject._guided_endpoint(
        "DPS",
        "dps",
        prompt,
        lambda _: None,
        validate_resource,
    )
    assert "resource-name=second" in result
    assert validation_calls["count"] == 3


def test_guided_endpoint_retries_identity_and_uami_back(mocker):
    mocker.patch.object(
        subject, "_validation_action", return_value="retry"
    )
    answers = iter(["hub", "user", "system", "system"])
    uami_back = {"done": False}

    def prompt(label):
        if label == "UAMI ARM ID: " and not uami_back["done"]:
            uami_back["done"] = True
            raise subject.BackRequested()
        return next(answers)

    identity_calls = {"count": 0}

    def validate_identity(*_):
        identity_calls["count"] += 1
        if identity_calls["count"] == 1:
            raise RuntimeError("not attached")

    result = subject._guided_endpoint(
        "IoT Hub",
        "hub",
        prompt,
        lambda _: None,
        validate_identity=validate_identity,
    )
    assert "identity=system-assigned" in result
    assert identity_calls["count"] == 2


def test_guided_namespace_uami_navigation(mocker):
    mocker.patch.object(
        subject, "_validation_action", return_value="retry"
    )
    answers = iter(["identity", "uami", "uami", "/uami"])
    back = {"done": False}
    validations = {"count": 0}

    def prompt(label):
        if label == "UAMI ARM ID: " and not back["done"]:
            back["done"] = True
            raise subject.BackRequested()
        return next(answers)

    def validate(_):
        validations["count"] += 1
        if validations["count"] == 1:
            raise RuntimeError("missing")

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
        validate_namespace_identity=validate,
    )
    assert result["outbound_identity"] == "/uami"
    assert validations["count"] == 2


def test_guided_hub_back_removes_last_entry(mocker):
    answers = iter([
        "hub",
        "first",
        "system",
        ":back",
        "second",
        "system",
        "no",
        "system",
    ])

    def prompt(label):
        value = next(answers)
        if value == ":back":
            raise subject.BackRequested()
        return value

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
    )
    assert len(result["hubs"]) == 1


def test_back_from_namespace_identity_preserves_capability():
    answers = iter([
        "dps",
        "first",
        "system",
        ":back",
        "second",
        "system",
        "system",
    ])

    def prompt(_):
        value = next(answers)
        if value == ":back":
            raise subject.BackRequested()
        return value

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
    )
    assert "resource-name=second" in result["dps"]
    assert result["outbound_identity"] == "system-assigned"


@pytest.mark.parametrize(
    "choice, answers, expected_key, expected_resource",
    [
        (
            "updates",
            [
                "first",
                "system",
                ":back",
                "second",
                "system",
                "system",
            ],
            "software_updates",
            "resource-name=second",
        ),
        (
            "hub",
            [
                "first",
                "system",
                "no",
                ":back",
                "second",
                "system",
                "system",
            ],
            "hubs",
            "resource-name=second",
        ),
    ],
)
def test_back_from_namespace_identity_edits_last_endpoint(
    choice, answers, expected_key, expected_resource
):
    values = iter([choice, *answers])

    def prompt(_):
        value = next(values)
        if value == ":back":
            raise subject.BackRequested()
        return value

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
    )
    endpoint = (
        result[expected_key][-1]
        if expected_key == "hubs"
        else result[expected_key]
    )
    assert expected_resource in endpoint


def test_back_from_additional_hub_preserves_first_hub():
    answers = iter([
        "hub",
        "first",
        "system",
        "yes",
        ":back",
        "system",
    ])

    def prompt(_):
        value = next(answers)
        if value == ":back":
            raise subject.BackRequested()
        return value

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
    )
    assert len(result["hubs"]) == 1
    assert "resource-name=first" in result["hubs"][0]


def test_back_from_complete_hub_returns_to_dps():
    answers = iter([
        "complete",
        "first-dps",
        "system",
        ":back",
        "second-dps",
        "system",
        "hub",
        "system",
        "no",
        "system",
    ])

    def prompt(_):
        value = next(answers)
        if value == ":back":
            raise subject.BackRequested()
        return value

    result = subject._guided_values(
        prompt=prompt,
        write=lambda _: None,
    )
    assert "resource-name=second-dps" in result["dps"]


def test_back_from_first_hub_returns_to_capability():
    answers = iter(["hub", ":back"])

    def prompt(_):
        value = next(answers)
        if value == ":back":
            raise subject.BackRequested()
        return value

    with pytest.raises(subject.BackRequested):
        subject._guided_values(
            prompt=prompt,
            write=lambda _: None,
        )


def test_resolve_scope_inputs_progressive(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=True)
    prompt = mocker.Mock(side_effect=["rg", "ns"])
    assert subject.resolve_scope_inputs(None, None, prompt=prompt) == (
        "ns",
        "rg",
    )
    prompt.reset_mock()
    assert subject.resolve_scope_inputs("ns", "rg", prompt=prompt) == (
        "ns",
        "rg",
    )
    prompt.assert_not_called()


def test_explicit_interactive_state_is_stable(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=False)
    prompt = mocker.Mock(side_effect=["rg", "ns"])
    assert subject.resolve_scope_inputs(
        None,
        None,
        interactive=True,
        prompt=prompt,
    ) == ("ns", "rg")


def test_scope_navigation_and_validation_recovery(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=True)
    messages = []
    answers = iter([
        subject.BackRequested(),
        "rg",
        subject.BackRequested(),
        "new-rg",
        "ns",
    ])

    def prompt(_):
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value

    assert subject.resolve_scope_inputs(
        None, None, prompt=prompt, write=messages.append
    ) == ("ns", "new-rg")
    assert "Enter a resource group or use :quit to cancel." in messages

    group_calls = {"count": 0}

    def group_validator(_):
        group_calls["count"] += 1
        if group_calls["count"] == 1:
            raise RuntimeError("temporary")

    mocker.patch.object(
        subject, "_validation_action", return_value="retry"
    )
    assert subject.resolve_scope_inputs(
        "ns",
        "rg",
        validate_resource_group=group_validator,
    ) == ("ns", "rg")

    mocker.patch.object(
        subject, "_validation_action", return_value="edit"
    )
    assert subject.resolve_scope_inputs(
        "old-ns",
        "old-rg",
        prompt=mocker.Mock(side_effect=["new-rg", "new-ns"]),
        validate_resource_group=mocker.Mock(
            side_effect=[RuntimeError("missing"), None]
        ),
    ) == ("new-ns", "new-rg")


def test_namespace_validation_retry_and_edit(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=True)
    validator = mocker.Mock(side_effect=[RuntimeError("temporary"), None])
    mocker.patch.object(
        subject, "_validation_action", return_value="retry"
    )
    assert subject.resolve_scope_inputs(
        "ns", "rg", validate_namespace=validator
    ) == ("ns", "rg")

    validator = mocker.Mock(side_effect=[RuntimeError("missing"), None])
    mocker.patch.object(
        subject, "_validation_action", return_value="edit"
    )
    assert subject.resolve_scope_inputs(
        "old",
        "rg",
        prompt=mocker.Mock(return_value="new"),
        validate_namespace=validator,
    ) == ("new", "rg")


def test_scope_validation_fails_immediately_noninteractive(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=False)
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


def test_resolve_scope_inputs_rejects_missing_noninteractive(mocker):
    mocker.patch.object(subject, "_is_interactive", return_value=False)
    with pytest.raises(ArgumentUsageError, match="resource-group"):
        subject.resolve_scope_inputs(None, None)
    with pytest.raises(ArgumentUsageError, match="--name"):
        subject.resolve_scope_inputs(None, "rg")
    mocker.patch.object(subject, "_is_interactive", return_value=True)
    with pytest.raises(ArgumentUsageError, match="cannot be empty"):
        subject.resolve_scope_inputs(None, None, prompt=lambda _: "")


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

    output = tmp_path / "result.json"
    subject.write_json_file(str(output), {"b": 2, "a": 1})
    assert json.loads(output.read_text(encoding="utf-8")) == {"a": 1, "b": 2}

    script = tmp_path / "plan.sh"
    subject.write_script_file(str(script), ["az one", "", "az two"])
    assert script.read_text(encoding="utf-8").endswith("az one\naz two\n")


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
