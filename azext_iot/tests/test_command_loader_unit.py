# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests that exercise the extension command loader. Loading the full command
table and the arguments for every command executes the module-level command
registration, parameter registration and help registration code across all
service command groups (command_map.py, params.py, _help.py).
"""

from pathlib import Path
from copy import deepcopy
from io import StringIO
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import responses
import yaml
from azure.cli.core import AzCommandsLoader, MainCommandsLoader
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser
from azure.core.credentials import AccessToken


_NAMESPACE_ARGUMENTS = [
    "--namespace",
    "namespace",
    "--resource-group",
    "resource-group",
]
_ENDPOINT_ARGUMENTS = [
    "--endpoint-name",
    "endpoint",
    *_NAMESPACE_ARGUMENTS,
]
_HUB_ID = (
    "/subscriptions/hub-sub/resourceGroups/hub-rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)
_DPS_ID = (
    "/subscriptions/dps-sub/resourceGroups/dps-rg/providers/"
    "Microsoft.Devices/provisioningServices/dps"
)
_SU_ID = (
    "/subscriptions/su-sub/resourceGroups/su-rg/providers/"
    "Microsoft.DeviceUpdate/updateInstances/su"
)
_LINK_PARSER_CASES = {
    "iot adr ns link add": [
        *_NAMESPACE_ARGUMENTS,
        "--hub-endpoint-name",
        "hub",
        "--hub-resource-id",
        _HUB_ID,
        "--dps-endpoint-name",
        "dps",
        "--dps-resource-id",
        _DPS_ID,
    ],
    "iot adr ns link wait": _NAMESPACE_ARGUMENTS,
}
_PNP_PARSER_CASES = {
    "iot hub digital-twin show": [],
    "iot hub digital-twin update": ["--patch", "[]"],
    "iot hub digital-twin invoke-command": ["--cn", "noop"],
}
_RETIRED_REGISTRY_DEVICE_COMMANDS = [
    f"iot adr ns registry-device{group} {verb}"
    for group, verbs in (
        ("", ("create", "show", "list", "update", "delete", "wait")),
        (" auth", ("list", "show", "show-keys", "revoke-certs", "wait")),
        (" attribute", ("create", "list", "show", "delete")),
        (" capability", ("list", "show")),
    )
    for verb in verbs
]
for _kind, _resource_option, _resource_id in (
    ("hub", "--hub-resource-id", _HUB_ID),
    ("dps", "--dps-resource-id", _DPS_ID),
    ("su", "--su-resource-id", _SU_ID),
):
    _LINK_PARSER_CASES[f"iot adr ns link {_kind} add"] = [
        *_ENDPOINT_ARGUMENTS,
        _resource_option,
        _resource_id,
    ]
    for _action in ("update", "show", "wait"):
        _LINK_PARSER_CASES[
            f"iot adr ns link {_kind} {_action}"
        ] = _ENDPOINT_ARGUMENTS
    _LINK_PARSER_CASES[
        f"iot adr ns link {_kind} list"
    ] = _NAMESPACE_ARGUMENTS


@pytest.fixture(scope="module")
def loader():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli()
    loader = IoTExtCommandsLoader(cli_ctx=cli_ctx)
    return loader


@pytest.fixture(scope="module")
def command_table(loader):
    table = loader.load_command_table(None)
    return table


@pytest.fixture(scope="module")
def management_command_parser():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli_ctx.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    names = [*_LINK_PARSER_CASES, *_PNP_PARSER_CASES, "iot hub create", "iot dps create"]
    loader.command_table = {
        name: loader.command_table[name]
        for name in names
    }

    # Azure CLI contributes --subscription as a private global argument before
    # extension signatures and argument overrides are loaded.
    cli_ctx.raise_event(
        EVENT_INVOKER_PRE_LOAD_ARGUMENTS,
        commands_loader=loader,
    )
    for command_name in names:
        loader.load_arguments(command_name)
        AzCommandsLoader.load_arguments(loader, command_name)

    parser = AzCliCommandParser(cli_ctx=cli_ctx)
    parser.load_command_table(loader)
    return parser


@pytest.mark.parametrize("command_name", _PNP_PARSER_CASES)
@pytest.mark.parametrize("auth_type", ["key", "login"])
def test_pnp_standard_authentication_options(management_command_parser, command_name, auth_type):
    parsed = management_command_parser.parse_args([
        *command_name.split(), "-n", "hub", "-d", "device",
        "--auth-type", auth_type, *_PNP_PARSER_CASES[command_name],
    ])
    assert parsed.auth_type_dataplane == auth_type


def test_pnp_update_authentication_default_has_only_the_standard_linter_exception(management_command_parser):
    parsed = management_command_parser.parse_args([
        "iot", "hub", "digital-twin", "update", "-n", "hub", "-d", "device", "--patch", "[]",
    ])
    assert parsed.auth_type_dataplane == "key"
    exclusions = yaml.safe_load(
        (Path(__file__).parents[2] / "linter_exclusions.yml").read_text(encoding="utf-8")
    )
    assert exclusions["iot hub digital-twin update"] == exclusions["iot hub device-twin update"] == {
        "parameters": {
            "auth_type_dataplane": {"rule_exclusions": ["no_parameter_defaults_for_update_commands"]},
        },
    }


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_retired_link_delete_is_not_registered(command_table, kind):
    assert f"iot adr ns link {kind} delete" not in command_table


@pytest.mark.parametrize("command_name", _RETIRED_REGISTRY_DEVICE_COMMANDS)
def test_retired_registry_device_commands_are_rejected(command_table, management_command_parser, command_name):
    assert command_name not in command_table
    with pytest.raises(SystemExit) as error:
        management_command_parser.parse_args(command_name.split())
    assert error.value.code == 2


def test_adr_command_count_excludes_retired_registry_devices(command_table):
    commands = [name for name in command_table if name.startswith("iot adr ")]
    assert len(commands) == 92
    assert not any(name.startswith("iot adr ns registry-device") for name in commands)


def test_command_table_loads(command_table):
    # The extension should register a non-trivial number of commands.
    assert command_table
    assert len(command_table) > 100
    # Spot check a few representative commands across services.
    for expected in [
        "iot du account create",
        "iot du instance create",
        "iot du update list",
        "iot dps enrollment create",
        "iot hub device-identity create",
        "iot device registration create",
        "iot device registration operation-status",
        "iot adr ns su software-update operation-status list",
        "iot adr ns su software-update catalog provider list",
        "iot adr ns su software-update catalog name list",
        "iot adr ns su software-update catalog version list",
    ]:
        assert expected in command_table, f"Missing command: {expected}"


def test_load_arguments_for_all_commands(loader, command_table):
    # Loading arguments for every command exercises all params.py modules.
    # skip_applicability avoids the need for a live invocation context.
    loader.skip_applicability = True
    for command_name in command_table:
        loader.load_arguments(command_name)
    # Argument registry should be populated.
    assert loader.command_table

    def scoped_arguments(command_name):
        parts = command_name.split()
        result = {}
        for index in range(1, len(parts) + 1):
            result.update(
                loader.argument_registry.arguments.get(
                    " ".join(parts[:index]), {}
                )
            )
        return result

    for command_name in ("iot hub create", "iot dps create", "iot dps update"):
        arguments = scoped_arguments(command_name)
        assert "adr_ns_id" not in arguments
        assert "adr_ns_identity_id" not in arguments
        options = {
            option
            for argument in arguments.values()
            for option in argument.settings.get("options_list", [])
        }
        assert "--ns-resource-id" not in options
        assert "--ns-identity-id" not in options

    for command_name in ("iot adr ns create", "iot adr ns update"):
        arguments = scoped_arguments(command_name)
        options = {
            option
            for argument in arguments.values()
            for option in argument.settings.get("options_list", [])
        }
        assert {
            "--messaging-endpoints",
            "--provisioning-endpoints",
            "--updating-endpoints",
        }.isdisjoint(options)
        if command_name.endswith(" create"):
            assert "--observability-enabled" not in options
        else:
            assert "--observability-enabled" in options

    for command_name in ("iot hub create", "iot dps create", "iot dps update"):
        arguments = scoped_arguments(command_name)
        system_options = arguments[
            "system_identity"
            if command_name == "iot hub create"
            else "mi_system_assigned"
        ].settings["options_list"]
        user_options = arguments[
            "user_identities"
            if command_name == "iot hub create"
            else "mi_user_assigned"
        ].settings["options_list"]
        assert system_options[0] == "--system-assigned-mi"
        assert user_options[0] == "--user-assigned-mi"
        assert any(
            getattr(option, "target", None) == "--mi-system-assigned"
            and option.hide
            for option in system_options
        )
        assert any(
            getattr(option, "target", None) == "--mi-user-assigned"
            and option.hide
            for option in user_options
        )

    for command_name in (
        "iot dps enrollment create",
        "iot dps enrollment-group create",
    ):
        arguments = scoped_arguments(command_name)
        assert "mi_system_assigned" not in arguments
        assert "mi_user_assigned" not in arguments

    hub_identity = scoped_arguments("iot hub identity assign")
    assert hub_identity["system_identity"].settings["options_list"] == [
        "--system-assigned",
        "--system",
    ]
    assert hub_identity["user_identities"].settings["options_list"] == [
        "--user-assigned",
        "--user",
    ]
    dps_identity = scoped_arguments("iot dps identity assign")
    assert dps_identity["system_assigned"].settings["options_list"] == [
        "--system",
        "--system-assigned",
    ]
    assert dps_identity["user_assigned"].settings["options_list"] == [
        "--user",
        "--user-assigned",
    ]

    bundled = scoped_arguments("iot adr ns link add")
    assert "--hub-endpoint-name" in bundled["hub_endpoint_name"].settings[
        "options_list"
    ]
    assert "--hub-name" in bundled["hub_endpoint_name"].settings[
        "options_list"
    ]
    assert "--dps-endpoint-name" in bundled["dps_endpoint_name"].settings[
        "options_list"
    ]
    assert "--dps-name" in bundled["dps_endpoint_name"].settings[
        "options_list"
    ]

    for command_name in (
        "iot device registration request-software-updates",
        "iot device registration request-onboarding-updates",
        "iot device registration report-update-status",
    ):
        assert command_name not in command_table


@pytest.mark.parametrize("command_name", sorted(_LINK_PARSER_CASES))
def test_all_link_commands_parse_one_global_subscription_without_collision(
    mocker,
    management_command_parser,
    command_name,
):
    subscription = "namespace-sub"
    mocker.patch(
        "azure.cli.core._profile.Profile.load_cached_subscriptions",
        return_value=[{"id": subscription, "name": "namespace-subscription"}],
    )
    parsed = management_command_parser.parse_args(
        [
            *command_name.split(),
            *_LINK_PARSER_CASES[command_name],
            "--subscription",
            subscription,
        ]
    )

    assert parsed._subscription == subscription  # pylint: disable=protected-access
    subscription_actions = [
        action
        for action in management_command_parser.subparser_map[
            command_name
        ]._actions  # pylint: disable=protected-access
        if "--subscription" in action.option_strings
    ]
    assert len(subscription_actions) == 1
    assert subscription_actions[0].dest == "_subscription"


def test_link_command_parser_leaves_subscription_for_current_account_default(
    management_command_parser,
):
    command_name = "iot adr ns link su add"
    parsed = management_command_parser.parse_args(
        [
            *command_name.split(),
            *_LINK_PARSER_CASES[command_name],
        ]
    )

    assert parsed._subscription is None  # pylint: disable=protected-access


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("value,expected", [(None, None), ("true", True), ("false", False)])
def test_resource_create_local_auth_option(management_command_parser, kind, value, expected):
    arguments = ["iot", kind, "create", "--name", "resource", "--resource-group", "rg"]
    if value is not None:
        arguments += ["--disable-local-auth", value]
    parsed = management_command_parser.parse_args(arguments)
    assert parsed.disable_local_auth is expected


@pytest.fixture(scope="module")
def hub_dps_parser():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli_ctx.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    names = [
        f"iot dps {kind} {action}"
        for kind in ("enrollment", "enrollment-group") for action in ("create", "update")
    ] + ["iot device registration create", "iot device registration operation-status"]
    loader.command_table = {name: loader.command_table[name] for name in names}
    cli_ctx.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    for name in names:
        loader.load_arguments(name)
        AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli_ctx)
    parser.load_command_table(loader)
    return parser


@pytest.mark.parametrize("kind", ["enrollment", "enrollment-group"])
@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("aliases", [False, True])
def test_enrollment_canonical_and_child_aliases_parse_once(hub_dps_parser, kind, action, aliases):
    name = f"iot dps {kind} {action}"
    flags = (
        ["--namespace-name", "namespace", "--certificate-authority-name", "authority", "--certificate-policy-name", "policy"]
        if aliases else
        ["--adr-namespace", "namespace", "--adr-ca-name", "authority", "--adr-cert-policy-name", "policy"]
    )
    arguments = [*name.split(), "--enrollment-id", "test", "--dps-name", "mydps", *flags]
    if kind == "enrollment" and action == "create":
        arguments += ["--attestation-type", "symmetricKey"]
    parsed = hub_dps_parser.parse_args(arguments)
    assert (parsed.adr_namespace, parsed.adr_ca_name, parsed.adr_certificate_policy_name) == (
        "namespace", "authority", "policy",
    )
    options = [
        option for entry in hub_dps_parser.subparser_map[name]._actions  # pylint: disable=protected-access
        for option in entry.option_strings
    ]
    assert len(options) == len(set(options))


@pytest.mark.parametrize("command", ["create", "operation-status"])
def test_rest_registration_keeps_csr_timeout_and_operation_status(hub_dps_parser, command):
    args = ["iot", "device", "registration", command, "--registration-id", "reg", "--id-scope", "scope"]
    if command == "create":
        args += ["--csr-file-path", "request.pem", "--timeout", "7"]
    else:
        args += ["--operation-id", "op"]
    parsed = hub_dps_parser.parse_args(args)
    if command == "create":
        assert parsed.csr == "request.pem" and parsed.timeout == 7
    else:
        assert parsed.operation_id == "op"


class _DpsManagementCommandsLoader(MainCommandsLoader):
    def load_command_table(self, args):
        from azext_iot import IoTExtCommandsLoader

        loader = IoTExtCommandsLoader(self.cli_ctx)
        self.command_table = {
            name: command for name, command in loader.load_command_table(args).items()
            if name in ("iot dps create", "iot dps update")
        }
        self.cmd_to_loader_map = {name: [loader] for name in self.command_table}
        return self.command_table


@pytest.fixture
def dps_management_cli(mocker):
    from azext_iot import _factory
    from azure.mgmt.resource import ResourceManagementClient

    subscription = "00000000-0000-0000-0000-000000000001"
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 9999999999))
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    management_factory = mocker.spy(_factory, "_iot_dps_management_client")
    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=subscription)
    profile_guard = mocker.patch("azure.cli.core._profile.Profile.__init__", side_effect=AssertionError("Live Profile"))
    resource_client = ResourceManagementClient(credential, subscription)
    location_factory = mocker.patch(
        "azext_iot.core.custom.resource_service_factory", return_value=resource_client,
    )
    cli = DummyCli(commands_loader_cls=_DpsManagementCommandsLoader)
    cli.data["subscription_id"] = subscription
    resource_id = (
        f"/subscriptions/{subscription}/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps"
    )
    state = SimpleNamespace(
        cli=cli, location_factory=location_factory, management_factory=management_factory,
        requests=[], status=201, available=True, lro=False,
        resource={"id": resource_id, "name": "dps", "location": "centraluseuap",
                  "sku": {"name": "S1", "capacity": 1}, "properties": {"provisioningState": "Succeeded"}},
    )

    def respond(request):
        state.requests.append(request)
        path = urlsplit(request.url).path
        if request.method == "POST":
            assert path.lower().endswith("/checkprovisioningservicenameavailability")
            return 200, {}, json.dumps({"nameAvailable": state.available, "message": "Name is taken"})
        if path.lower().endswith("/resourcegroups/rg"):
            return 200, {}, json.dumps({"id": path, "name": "rg", "location": "centraluseuap"})
        if path.endswith("/unit-operation"):
            return 200, {}, json.dumps({"status": "Succeeded"})
        assert path == resource_id
        if request.method == "PUT":
            if state.status >= 400:
                return state.status, {}, json.dumps({"error": {"code": "UnitServiceError", "message": "Service rejected"}})
            state.resource.update(json.loads(request.body))
            state.resource.setdefault("properties", {})["provisioningState"] = "Succeeded"
            if state.lro:
                return 201, {"Azure-AsyncOperation": "https://centraluseuap.management.azure.com/unit-operation",
                             "Retry-After": "0"}, json.dumps(state.resource)
            return state.status, {}, json.dumps(state.resource)
        assert request.method == "GET"
        return 200, {}, json.dumps(state.resource)

    def invoke(action, arguments):
        output = StringIO()
        try:
            code = cli.invoke(["iot", "dps", action, "-n", "dps", "-g", "rg", *arguments], out_file=output)
        except SystemExit as error:
            code = error.code
        return code, cli.result, output.getvalue()

    state.invoke = invoke
    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            network.add_callback(method, re.compile(r"https://.*"), callback=respond, content_type="application/json")
        yield state
    resource_client.close()
    profile_guard.assert_not_called()


@pytest.mark.parametrize("unit", [
    ["--unit", "0"], ["--unit", "-1"], ["--unit", "-999"], ["--unit=0"], ["--unit=-1"],
    ["--unit", "1.5"], ["--unit", "text"], ["--unit"],
])
@pytest.mark.parametrize("location", [[], ["--location", "centraluseuap"]])
def test_dps_invalid_unit_actual_invocation_never_reaches_management(dps_management_cli, unit, location, caplog):
    runtime = dps_management_cli
    runtime.available = False
    code, result, output = runtime.invoke(
        "create", [*location, "--tags", "purpose=unit", "--system-assigned-mi", *unit],
    )
    assert code != 0
    assert not output.strip()
    if unit not in (["--unit", "1.5"], ["--unit", "text"], ["--unit"]):
        assert "--unit must be an integer greater than or equal to 1" in str(result.error)
    else:
        assert code == 2
        diagnostic = caplog.text
        assert "invalid int value" in diagnostic or "expected one argument" in diagnostic
    assert runtime.requests == []
    runtime.location_factory.assert_not_called()
    runtime.management_factory.assert_not_called()


@pytest.mark.parametrize("unit,capacity", [
    ([], 1), (["--unit", "1"], 1), (["--unit", "2"], 2), (["--unit", "999999999"], 999999999),
])
@pytest.mark.parametrize("location", [[], ["--location", "centraluseuap"]])
def test_dps_valid_unit_actual_cli_to_sdk_json(dps_management_cli, unit, capacity, location):
    runtime = dps_management_cli
    code, result, output = runtime.invoke("create", [*location, *unit])
    assert code == 0, result.error
    assert json.loads(output)["sku"]["capacity"] == capacity
    writes = [request for request in runtime.requests if request.method == "PUT"]
    assert len(writes) == 1
    body = json.loads(writes[0].body)
    assert body["sku"] == {"name": "S1", "capacity": capacity}
    assert body["location"] == "centraluseuap"
    assert body["properties"] == {}
    assert all("api-version=2026-06-01-preview" in request.url for request in runtime.requests
               if "Microsoft.Devices" in request.url)
    assert runtime.location_factory.call_count == (0 if location else 1)


def test_dps_create_options_and_real_lro_are_preserved(dps_management_cli):
    runtime = dps_management_cli
    runtime.lro = True
    identity = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/"
        "providers/Microsoft.ManagedIdentity/userAssignedIdentities/user"
    )
    code, result, _ = runtime.invoke("create", [
        "--unit", "2", "--location", "centraluseuap", "--tags", "purpose=unit",
        "--system-assigned-mi", "--user-assigned-mi", identity, "--disable-local-auth", "false",
        "--enforce-data-residency", "true",
    ])
    assert code == 0, result.error
    body = json.loads(next(request.body for request in runtime.requests if request.method == "PUT"))
    assert body["sku"]["capacity"] == 2
    assert body["tags"] == {"purpose": "unit"}
    assert body["properties"] == {"disableLocalAuth": False, "enableDataResidency": True}
    assert body["identity"]["userAssignedIdentities"] == {identity: {}}
    assert "SystemAssigned" in body["identity"]["type"]
    assert any("/unit-operation" in request.url for request in runtime.requests)
    assert result.result["properties"]["provisioningState"] == "Succeeded"


def test_dps_valid_create_service_error_remains_visible(dps_management_cli):
    dps_management_cli.status = 409
    code, result, _ = dps_management_cli.invoke("create", ["--unit", "1", "--location", "centraluseuap"])
    assert code != 0
    assert "Service rejected" in str(result.error)
    assert len([request for request in dps_management_cli.requests if request.method == "PUT"]) == 1


@pytest.mark.parametrize("arguments", [
    ["--set", "sku.capacity=0"], ["--set", "sku.capacity=-1"], ["--set", "sku.capacity=1.5"],
    ["--set", "sku.capacity=true"], ["--set", "sku.capacity=null"], ["--set", "sku.capacity=text"],
    ["--set", "sku.capacity=1", "--force-string"], ["--remove", "sku.capacity"], ["--remove", "sku"],
    ["--set", 'sku={"name":"S1","capacity":0}'], ["--set", 'sku={"name":"S1"}'],
    ["--set", "sku=null"], ["--set", "sku=[]"], ["--set", "sku=1"],
    ["--set", "sku.CAPACITY=0"], ["--set", 'SKU={"capacity":0}'],
    ["--set", "sku.capacity=2", "--set", "sku.capacity=0"],
    ["--remove", "sku", "--set", 'sku={"capacity":0}'],
    ["--set", "sku..capacity=0"], ["--set", ".sku.capacity=-1"],
    ["--set", "..sku...capacity=1.5"], ["--set", "sku.capacity.=true"],
    ["--set", ".sku..capacity=null"], ["--remove", ".sku.capacity"],
    ["--set", '.sku={"name":"S1","capacity":0}'],
])
@pytest.mark.parametrize("baseline", [0, 1])
def test_dps_generic_final_explicit_capacity_invalid_never_writes(dps_management_cli, arguments, baseline):
    runtime = dps_management_cli
    runtime.resource["sku"]["capacity"] = baseline
    before = deepcopy(runtime.resource)
    code, result, _ = runtime.invoke("update", arguments)
    assert code != 0
    assert "sku.capacity must be an integer greater than or equal to 1" in str(result.error)
    assert [request.method for request in runtime.requests] == ["GET"]
    assert runtime.resource == before


@pytest.mark.parametrize("arguments,capacity", [
    (["--set", "sku.capacity=1"], 1), (["--set", "sku.capacity=2"], 2),
    (["--set", "sku.capacity=0", "--set", "sku.capacity=2"], 2),
    (["--remove", "sku.capacity", "--set", "sku.capacity=1"], 1),
    (["--set", 'sku={"name":"S1","capacity":2}'], 2),
    (["--set", "sku..capacity=2"], 2),
    (["--set", ".sku.capacity=0", "--set", "sku.capacity.=2"], 2),
])
def test_dps_generic_capacity_validates_final_ordered_edits(dps_management_cli, arguments, capacity):
    code, result, _ = dps_management_cli.invoke("update", arguments)
    assert code == 0, result.error
    writes = [request for request in dps_management_cli.requests if request.method == "PUT"]
    assert len(writes) == 1
    assert json.loads(writes[0].body)["sku"]["capacity"] == capacity


@pytest.mark.parametrize("sku", [{}, {"name": "S1"}, {"capacity": None}, {"capacity": 0}, None])
@pytest.mark.parametrize("arguments", [
    ["--set", "tags.purpose=unit"], ["--tags", "purpose=unit"],
    ["--system-assigned-mi"], ["--remove", "tags.old"],
])
def test_dps_unrelated_update_does_not_validate_baseline_capacity(dps_management_cli, sku, arguments):
    runtime = dps_management_cli
    runtime.resource["tags"] = {"old": "value"}
    if sku is None:
        runtime.resource.pop("sku")
    else:
        runtime.resource["sku"] = sku
    code, result, _ = runtime.invoke("update", arguments)
    assert code == 0, result.error
    assert len([request for request in runtime.requests if request.method == "PUT"]) == 1


def test_dps_unit_help_and_internal_update_argument_are_not_public(dps_management_cli, capsys):
    code, _, output = dps_management_cli.invoke("create", ["--help"])
    assert code == 0
    assert "Integer minimum: 1" in " ".join((output + capsys.readouterr().out).split())
    for option in ("--unit", "--dps-capacity-edited"):
        code, _, _ = dps_management_cli.invoke("update", [option, "1"])
        assert code != 0
    assert dps_management_cli.requests == []
