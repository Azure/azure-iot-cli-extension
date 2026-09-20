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

from azext_iot.common.utility import generate_key


_IDENTITY_UPDATE_COMMAND = "iot hub device-identity update"
_IDENTITY_LOGIN = "HostName=hub.unit.invalid;SharedAccessKeyName=owner;SharedAccessKey=b2ZmbGluZQ=="
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
_REGISTRY_DEVICE_PARSER_CASES = {
    f"iot adr ns registry-device{group} {verb}": [*arguments, *extra]
    for group, arguments, verbs in (
        ("", [], {
            "create": ["-n", "device", "--ext-id", "external"], "show": ["-n", "device"], "list": [],
            "update": ["-n", "device", "--manufacturer", "Contoso"], "delete": ["-n", "device", "--yes"],
            "wait": ["-n", "device"],
        }),
        (" auth", ["--rdn", "device"], {
            "list": [], "show": ["-n", "profile"], "show-keys": ["-n", "profile"],
            "revoke-certs": ["-n", "profile", "--yes"], "wait": ["-n", "profile"],
        }),
        (" attribute", ["--rdn", "device"], {
            "create": ["-n", "attribute"], "list": [], "show": ["-n", "attribute"],
            "delete": ["-n", "attribute", "--yes"],
        }),
        (" capability", ["--rdn", "device"], {"list": [], "show": ["-n", "capability"]}),
    )
    for verb, extra in verbs.items()
}
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
    names = [
        *_LINK_PARSER_CASES, *_PNP_PARSER_CASES, *_REGISTRY_DEVICE_PARSER_CASES,
        "iot hub create", "iot dps create", _IDENTITY_UPDATE_COMMAND,
    ]
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


class _HubIdentityCommandsLoader(MainCommandsLoader):
    def load_command_table(self, args):
        from azext_iot import IoTExtCommandsLoader

        loader = IoTExtCommandsLoader(self.cli_ctx)
        table = loader.load_command_table(args)
        self.command_table = {_IDENTITY_UPDATE_COMMAND: table[_IDENTITY_UPDATE_COMMAND]}
        self.cmd_to_loader_map = {_IDENTITY_UPDATE_COMMAND: [loader]}
        return self.command_table


@pytest.fixture
def identity_update_cli(mocker):
    """Run the native invoker, discovery, generic update and SDK against offline HTTP only."""
    from azure.core.credentials import AzureKeyCredential
    from azext_iot import _factory
    from azext_iot.iothub.providers.discovery import IotHubDiscovery
    from azext_iot.operations import hub

    subscription = "00000000-0000-0000-0000-000000000001"
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 9999999999))
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    oauth = mocker.patch.object(_factory, "IoTOAuth", return_value=AzureKeyCredential("Bearer offline-token"))
    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=subscription)
    mocker.patch("azext_iot.iothub.providers.discovery.get_subscription_id", return_value=subscription)
    profile_guard = mocker.patch("azure.cli.core._profile.Profile.__init__", side_effect=AssertionError("Live Profile"))
    discovery = mocker.spy(IotHubDiscovery, "get_target")
    custom_update = mocker.spy(hub, "update_iot_device_custom")
    cli = DummyCli(commands_loader_cls=_HubIdentityCommandsLoader)
    cli.data["subscription_id"] = subscription
    resource_id = f"/subscriptions/{subscription}/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub"
    symmetric_keys = {"primaryKey": generate_key(), "secondaryKey": generate_key()}
    policy_key = generate_key()
    state = SimpleNamespace(
        cli=cli, discovery=discovery, custom_update=custom_update, oauth=oauth, requests=[],
        symmetric_keys=symmetric_keys,
        resource={
            "deviceId": "device", "etag": "original", "status": "enabled", "statusReason": "original",
            "capabilities": {"iotEdge": False},
            "authentication": {
                "type": "sas", "symmetricKey": dict(symmetric_keys),
                "x509Thumbprint": {"primaryThumbprint": "primary", "secondaryThumbprint": "secondary"},
                "policyResourceId": "policy", "x509CaValidation": True, "unknownAuthField": "drop",
            },
            "attributes": {"keep": "value", "items": []},
            "adrDeviceProperties": {"uuid": "owned"}, "deviceResourceId": "owned",
            "armSyncStatus": {"status": "owned"}, "unknownField": "drop",
        },
    )

    def respond(request):
        state.requests.append(request)
        path = urlsplit(request.url).path
        if path == resource_id:
            assert request.method == "GET"
            return 200, {}, json.dumps({
                "id": resource_id, "name": "hub", "location": "centraluseuap", "sku": {"tier": "Standard"},
                "properties": {"hostName": "hub.unit.invalid"},
            })
        if path == resource_id + "/listkeys":
            assert request.method == "POST"
            return 200, {}, json.dumps({"value": [{
                "keyName": "owner", "primaryKey": policy_key, "secondaryKey": policy_key,
                "rights": "RegistryWrite, ServiceConnect, DeviceConnect",
            }]})
        assert urlsplit(request.url).netloc == "hub.unit.invalid"
        assert path == "/devices/device"
        assert "api-version=2026-11-01-preview" in request.url
        if request.method == "PUT":
            state.resource = json.loads(request.body)
        else:
            assert request.method == "GET"
        return 200, {}, json.dumps(state.resource)

    def invoke(arguments):
        output = StringIO()
        try:
            code = cli.invoke([*_IDENTITY_UPDATE_COMMAND.split(), *arguments], out_file=output)
        except SystemExit as error:
            code = error.code
        return code, cli.result, output.getvalue()

    state.invoke = invoke
    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        for method in ("GET", "POST", "PUT"):
            network.add_callback(
                method, re.compile(r"https://(?:hub\.unit\.invalid|centraluseuap\.management\.azure\.com)/.*"),
                callback=respond, content_type="application/json",
            )
        yield state
    profile_guard.assert_not_called()


@pytest.mark.parametrize("arguments", [[], ["--auth-type", "login"], ["-g", "rg"], ["--login", ""], ["-n", ""]])
def test_identity_update_invocation_requires_target_before_getter(identity_update_cli, arguments):
    from azure.cli.core.azclierror import RequiredArgumentMissingError

    runtime = identity_update_cli
    code, result, _ = runtime.invoke(["-d", "device", "--set", "status=disabled", *arguments])
    assert code != 0
    assert isinstance(result.error, RequiredArgumentMissingError)
    assert "hub" in str(result.error).lower() and "login" in str(result.error).lower()
    runtime.discovery.assert_not_called()
    runtime.custom_update.assert_not_called()
    assert runtime.requests == []


@pytest.mark.parametrize("target,authorization,management_methods", [
    (["-n", "hub", "-g", "rg"], "SharedAccessSignature ", ["GET", "POST", "GET", "POST"]),
    (["-n", "hub", "-g", "rg", "--auth-type", "login"], "Bearer ", ["GET", "GET"]),
    (["-n", "hub.unit.invalid", "--auth-type", "login"], "Bearer ", []),
    (["--login", _IDENTITY_LOGIN], "SharedAccessSignature ", []),
    (["-n", "ignored", "--auth-type", "login", "--login", _IDENTITY_LOGIN], "SharedAccessSignature ", []),
])
def test_identity_update_invocation_preserves_target_auth_and_write_projection(
    identity_update_cli, target, authorization, management_methods,
):
    runtime = identity_update_cli
    code, result, _ = runtime.invoke([
        "-d", "device", *target, "--set", "status=DISABLED", "--status-reason", "maintenance", "--etag", "explicit",
    ])
    assert code == 0, result.error
    requests = [request for request in runtime.requests if urlsplit(request.url).netloc == "hub.unit.invalid"]
    assert [request.method for request in requests] == ["GET", "PUT"]
    assert [request.method for request in runtime.requests if request not in requests] == management_methods
    assert all(request.headers["Authorization"].startswith(authorization) for request in requests)
    assert requests[-1].headers["If-Match"] == '"explicit"'
    assert runtime.resource["status"] == "disabled"
    assert runtime.resource["statusReason"] == "maintenance"
    assert runtime.resource["authentication"] == {
        "type": "sas", "symmetricKey": runtime.symmetric_keys,
        "x509Thumbprint": {"primaryThumbprint": "primary", "secondaryThumbprint": "secondary"},
        "policyResourceId": "policy", "x509CaValidation": True,
    }
    assert not {"adrDeviceProperties", "deviceResourceId", "armSyncStatus", "unknownField", "hub"} & runtime.resource.keys()
    assert runtime.discovery.call_count == 2
    runtime.custom_update.assert_called_once()
    assert runtime.oauth.call_count == (2 if authorization == "Bearer " else 0)


@pytest.mark.parametrize("arguments,path,expected", [
    (["--status-reason", "maintenance"], ("statusReason",), "maintenance"),
    (["--edge-enabled", "true"], ("capabilities", "iotEdge"), True),
    (["--primary-key", "bmV3"], ("authentication", "symmetricKey", "primaryKey"), "bmV3"),
    (["--set", ".status=DISABLED"], ("status",), "disabled"),
    (["--set", "attributes.adrDeviceProperties=user"], ("attributes", "adrDeviceProperties"), "user"),
    (["--set", "attributes.deviceResourceId=null"], ("attributes", "deviceResourceId"), None),
    (["--add", "attributes.items", "adrDeviceProperties=user"], ("attributes", "items"), [{"adrDeviceProperties": "user"}]),
    (["--remove", "attributes.keep"], ("attributes",), {"items": []}),
    (["--status", "enabled", "--set", "status=disabled"], ("status",), "disabled"),
    (["--set", "status=disabled", "--set", "status=enabled"], ("status",), "enabled"),
])
def test_identity_update_invocation_keeps_allowed_partial_updates(identity_update_cli, arguments, path, expected):
    runtime = identity_update_cli
    code, result, _ = runtime.invoke(["-d", "device", "--login", _IDENTITY_LOGIN, *arguments])
    assert code == 0, result.error
    assert [request.method for request in runtime.requests] == ["GET", "PUT"]
    assert runtime.requests[-1].headers["If-Match"] == '"*"'
    value = runtime.resource
    for key in path:
        value = value[key]
    assert value == expected


@pytest.mark.parametrize("auth_type", ["sas", "selfSigned", "certificateAuthority"])
def test_identity_update_invocation_preserves_partial_policy_auth(identity_update_cli, auth_type):
    runtime = identity_update_cli
    authentication = {"type": auth_type, "policyResourceId": "policy", "x509CaValidation": True}
    if auth_type == "selfSigned":
        authentication["x509Thumbprint"] = {"primaryThumbprint": "primary", "secondaryThumbprint": "secondary"}
    runtime.resource["authentication"] = deepcopy(authentication)
    code, result, _ = runtime.invoke([
        "-d", "device", "--login", _IDENTITY_LOGIN, "--status-reason", "maintenance",
    ])
    assert code == 0, result.error
    assert [request.method for request in runtime.requests] == ["GET", "PUT"]
    assert runtime.resource["authentication"] == authentication


@pytest.mark.parametrize("path", [
    "adrDeviceProperties", "deviceResourceId", "armSyncStatus",
    "adr_device_properties.uuid", "ADRDEVICEPROPERTIES.uuid", "armSyncStatus[0]",
    ".adrDeviceProperties.uuid", "..device_resource_id", ".armSyncStatus.[0]",
])
@pytest.mark.parametrize("operation", ["--set", "--add", "--remove"])
def test_identity_update_invocation_rejects_owned_intent_before_getter(identity_update_cli, path, operation):
    runtime = identity_update_cli
    values = [f"{path}=forged"] if operation == "--set" else [path, "uuid=forged"] if operation == "--add" else [path]
    code, result, _ = runtime.invoke([
        "-d", "device", "--login", _IDENTITY_LOGIN, "--set", "status=disabled", operation, *values,
    ])
    assert code != 0
    assert "owned by ADR/ARM" in str(result.error)
    runtime.discovery.assert_not_called()
    runtime.custom_update.assert_not_called()
    assert runtime.requests == []


@pytest.mark.parametrize("arguments", [
    ["--set", "deviceResourceId=owned"],
    ["--set", "adrDeviceProperties.uuid=forged", "--set", "adrDeviceProperties.uuid=owned"],
    ["--remove", "adrDeviceProperties", "--set", 'adrDeviceProperties={"uuid":"owned"}'],
])
def test_identity_update_invocation_rejects_owned_intent_even_without_net_change(identity_update_cli, arguments):
    runtime = identity_update_cli
    code, result, _ = runtime.invoke(["-d", "device", "--login", _IDENTITY_LOGIN, *arguments])
    assert code != 0
    assert "owned by ADR/ARM" in str(result.error)
    runtime.discovery.assert_not_called()
    runtime.custom_update.assert_not_called()
    assert runtime.requests == []


def test_identity_update_invocation_requires_device(identity_update_cli):
    code, _, _ = identity_update_cli.invoke(["--login", _IDENTITY_LOGIN, "--set", "status=disabled"])
    assert code != 0
    identity_update_cli.discovery.assert_not_called()
    assert identity_update_cli.requests == []


def test_identity_update_invocation_rejects_malformed_login_before_http(identity_update_cli):
    code, result, _ = identity_update_cli.invoke([
        "-d", "device", "--login", "malformed", "--set", "status=disabled",
    ])
    assert code != 0
    assert "connection string" in str(result.error).lower()
    identity_update_cli.custom_update.assert_not_called()
    assert identity_update_cli.requests == []


@pytest.mark.parametrize("arguments", [
    ["--auth-type", "invalid"], ["--auth-method", "invalid"], ["--status", "invalid"],
    ["--edge-enabled", "invalid"], ["--set"], ["--unknown-option"],
])
def test_identity_update_invocation_rejects_invalid_arguments_before_getter(identity_update_cli, arguments):
    runtime = identity_update_cli
    code, _, _ = runtime.invoke(["-d", "device", "--login", _IDENTITY_LOGIN, *arguments])
    assert code != 0
    runtime.discovery.assert_not_called()
    runtime.custom_update.assert_not_called()
    assert runtime.requests == []


@pytest.mark.parametrize("arguments,message", [
    (["--primary-thumbprint", "new"], "does not support primary or secondary thumbprints"),
    (["--auth-method", "shared_private_key", "--primary-key", "bmV3"], "primary + secondary Key required"),
    (["--auth-method", "x509_thumbprint"], "primary or secondary Thumbprint required"),
    (["--set", "authentication.type=invalid"], "authentication.type must be one of"),
    (["--remove", "notPresent"], "notPresent"),
    (["--set", "=empty"], "Empty key"),
])
def test_identity_update_invocation_rejects_invalid_update_before_setter(identity_update_cli, arguments, message):
    runtime = identity_update_cli
    code, result, _ = runtime.invoke(["-d", "device", "--login", _IDENTITY_LOGIN, *arguments])
    assert code != 0
    assert message in str(result.error)
    assert [request.method for request in runtime.requests] == ["GET"]


def test_identity_update_hook_is_hidden_and_cannot_be_supplied(identity_update_cli, capsys):
    runtime = identity_update_cli
    code, _, output = runtime.invoke(["--help"])
    assert code == 0
    help_output = (output + capsys.readouterr().out).lower()
    assert "--login" in help_output and "--set" in help_output
    assert "identity_update" not in help_output and "identity-update" not in help_output
    for option in ("--identity-update", "--identity_update", "--__IDENTITY_UPDATE", "--__IDENTITY_UPDATE=false"):
        code, _, _ = runtime.invoke([
            "-d", "device", "--login", _IDENTITY_LOGIN, "--set", "adrDeviceProperties.uuid=forged", option,
        ])
        assert code != 0
    runtime.discovery.assert_not_called()
    assert runtime.requests == []


def test_identity_update_composes_native_argument_validators(management_command_parser):
    from azext_iot._validators import mode2_iot_login_handler
    from azext_iot.iothub._payload import validate_identity_update

    parsed = management_command_parser.parse_args([
        *_IDENTITY_UPDATE_COMMAND.split(), "-d", "device", "--set", "status=disabled",
    ])
    assert not getattr(parsed, "_command_validator", None)
    assert {mode2_iot_login_handler, validate_identity_update} <= set(parsed._argument_validators)


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


@pytest.mark.parametrize("command_name", _REGISTRY_DEVICE_PARSER_CASES)
def test_restored_registry_device_commands_parse(command_table, management_command_parser, command_name):
    assert command_table[command_name].command_kwargs["is_preview"]
    parsed = management_command_parser.parse_args([
        *command_name.split(), *_NAMESPACE_ARGUMENTS, *_REGISTRY_DEVICE_PARSER_CASES[command_name],
    ])
    assert parsed.namespace_name == "namespace"
    assert parsed.resource_group_name == "resource-group"


def test_adr_command_count_includes_all_restored_registry_devices(command_table):
    commands = [name for name in command_table if name.startswith("iot adr ")]
    assert len(commands) == 109
    assert {name for name in commands if name.startswith("iot adr ns registry-device")} == set(_REGISTRY_DEVICE_PARSER_CASES)


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
    assert any(
        getattr(option, "target", None) == "--hub-name" and option.hide
        for option in bundled["hub_endpoint_name"].settings["options_list"]
    )
    assert "--dps-endpoint-name" in bundled["dps_endpoint_name"].settings[
        "options_list"
    ]
    assert any(
        getattr(option, "target", None) == "--dps-name" and option.hide
        for option in bundled["dps_endpoint_name"].settings["options_list"]
    )

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


@pytest.mark.parametrize("no_wait", [False, True])
def test_combined_link_parser_exposes_dependency_wait_options(management_command_parser, no_wait):
    command_name = "iot adr ns link add"
    arguments = [
        *command_name.split(), *_LINK_PARSER_CASES[command_name],
        "--timeout", "60", "--interval", "1",
    ]
    if no_wait:
        arguments.append("--no-wait")
    parsed = management_command_parser.parse_args(arguments)
    assert parsed.timeout == 60 and parsed.interval == 1
    assert bool(parsed.no_wait) is no_wait


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
@pytest.mark.parametrize("action", ["add", "update"])
@pytest.mark.parametrize("custom", [False, True])
def test_atomic_link_root_parser_exposes_recovery_options(management_command_parser, kind, action, custom):
    command = f"iot adr ns link {kind} {action}"
    arguments = [*command.split(), *_LINK_PARSER_CASES[command]]
    if custom:
        arguments.extend(["--timeout", "91", "--interval", "2", "--no-wait"])
    parsed = management_command_parser.parse_args(arguments)
    # Update commands must not publish non-None defaults in the command table.
    # Their omitted recovery settings are resolved by the command handler.
    assert parsed.timeout == (91 if custom else (600 if action == "add" else None))
    assert parsed.interval == (2 if custom else (30 if action == "add" else None))
    assert bool(parsed.no_wait) is custom


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
            if name in ("iot dps create", "iot dps update", "iot dps show", "iot dps list", "iot dps delete")
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
        requests=[], status=201, available=True, lro=False, resource_counts=[],
        resource={"id": resource_id, "name": "dps", "location": "centraluseuap",
                  "sku": {"name": "S1", "capacity": 1}, "properties": {"provisioningState": "Succeeded"}},
    )
    state.resources = {resource_id: state.resource}
    prefix = resource_id.rsplit("/", 1)[0]

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
        if path == prefix and request.method == "GET":
            return 200, {}, json.dumps({"value": list(state.resources.values())})
        assert path.startswith(prefix + "/") and "/" not in path[len(prefix) + 1:]
        if request.method == "PUT":
            if state.status >= 400:
                return state.status, {}, json.dumps({"error": {"code": "UnitServiceError", "message": "Service rejected"}})
            body = json.loads(request.body)
            assert "tags" not in body or isinstance(body["tags"], dict), "ARM tags must be a JSON object."
            resource = state.resources.setdefault(path, {"id": path, "name": path.rsplit("/", 1)[1]})
            resource.update(body)
            resource.setdefault("properties", {})["provisioningState"] = "Succeeded"
            state.resource_counts.append(len(state.resources))
            if state.lro:
                return 201, {"Azure-AsyncOperation": "https://centraluseuap.management.azure.com/unit-operation",
                             "Retry-After": "0"}, json.dumps(resource)
            return state.status, {}, json.dumps(resource)
        if request.method == "DELETE":
            del state.resources[path]
            state.resource_counts.append(len(state.resources))
            return 200, {}, ""
        assert request.method == "GET"
        if path not in state.resources:
            return 404, {}, json.dumps({"error": {"code": "ResourceNotFound", "message": "Resource is absent"}})
        return 200, {}, json.dumps(state.resources[path])

    def invoke(action, arguments, *, use_ids=False):
        output = StringIO()
        target = ["--ids", resource_id] if use_ids else ["-n", "dps", "-g", "rg"]
        try:
            code = cli.invoke(["iot", "dps", action, *target, *arguments], out_file=output)
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
@pytest.mark.parametrize("use_ids", [False, True], ids=["name-and-group", "ids"])
def test_dps_generic_final_explicit_capacity_invalid_never_writes(dps_management_cli, arguments, baseline, use_ids):
    runtime = dps_management_cli
    runtime.resource["sku"]["capacity"] = baseline
    before = deepcopy(runtime.resource)
    code, result, _ = runtime.invoke("update", arguments, use_ids=use_ids)
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
@pytest.mark.parametrize("use_ids", [False, True], ids=["name-and-group", "ids"])
def test_dps_generic_capacity_validates_final_ordered_edits(dps_management_cli, arguments, capacity, use_ids):
    code, result, _ = dps_management_cli.invoke("update", arguments, use_ids=use_ids)
    assert code == 0, result.error
    writes = [request for request in dps_management_cli.requests if request.method == "PUT"]
    assert len(writes) == 1
    assert json.loads(writes[0].body)["sku"]["capacity"] == capacity


@pytest.mark.parametrize("sku", [{}, {"name": "S1"}, {"capacity": None}, {"capacity": 0}, None])
@pytest.mark.parametrize("arguments", [
    ["--set", "tags.purpose=unit"], ["--tags", "purpose=unit"],
    ["--system-assigned-mi"], ["--remove", "tags.old"],
])
@pytest.mark.parametrize("use_ids", [False, True], ids=["name-and-group", "ids"])
def test_dps_unrelated_update_does_not_validate_baseline_capacity(dps_management_cli, sku, arguments, use_ids):
    runtime = dps_management_cli
    runtime.resource["tags"] = {"old": "value"}
    runtime.resource["properties"]["disableLocalAuth"] = True
    if sku is None:
        runtime.resource.pop("sku")
    else:
        runtime.resource["sku"] = sku
    code, result, _ = runtime.invoke("update", arguments, use_ids=use_ids)
    assert code == 0, result.error
    writes = [request for request in runtime.requests if request.method == "PUT"]
    assert len(writes) == 1
    body = json.loads(writes[0].body)
    assert isinstance(body["tags"], dict)
    assert body["properties"]["disableLocalAuth"] is True
    assert body.get("sku") == sku


@pytest.mark.parametrize("capacity_arguments,expected_capacity", [
    ([], 1),
    (["--set", "sku.capacity=2"], 2),
    (["--set", "sku.capacity=0", "--set", "sku.capacity=2"], 2),
    (["--set", 'sku={"name":"S1","capacity":2}'], 2),
    (["--set", "sku.capacity=0"], None),
    (["--set", ".sku.capacity=-1"], None),
    (["--set", "sku.capacity=1", "--force-string"], None),
])
@pytest.mark.parametrize("use_ids", [False, True], ids=["name-and-group", "ids"])
def test_dps_tags_and_capacity_run_both_argument_validators(
    dps_management_cli, capacity_arguments, expected_capacity, use_ids,
):
    runtime = dps_management_cli
    runtime.resource["tags"] = {"old": "value"}
    runtime.resource["properties"]["disableLocalAuth"] = True
    before = deepcopy(runtime.resource)
    code, result, _ = runtime.invoke(
        "update", ["--tags", "purpose=unit", "empty", "message=two words", "equals=a=b", *capacity_arguments],
        use_ids=use_ids,
    )
    if expected_capacity is None:
        assert code != 0
        assert "sku.capacity must be an integer greater than or equal to 1" in str(result.error)
        assert [request.method for request in runtime.requests] == ["GET"]
        assert runtime.resource == before
    else:
        assert code == 0, result.error
        writes = [request for request in runtime.requests if request.method == "PUT"]
        assert len(writes) == 1
        body = json.loads(writes[0].body)
        assert body["tags"] == {"purpose": "unit", "empty": "", "message": "two words", "equals": "a=b"}
        assert body["sku"]["capacity"] == expected_capacity
        assert body["properties"]["disableLocalAuth"] is True


def test_dps_capacity_actual_lifecycle_preserves_auth_and_all_controls(dps_management_cli, mocker, monkeypatch, tmp_path):
    from azext_iot.common.embedded_cli import EmbeddedCLI
    from azext_iot.tests.dps.core import test_dps_unit_capacity_int as scenario

    runtime = dps_management_cli
    runtime.resources.clear()
    uid = "a" * 32
    subscription = "00000000-0000-0000-0000-000000000001"
    receipts = scenario._phase_receipts
    for name, value in {
        receipts.DIRECTORY_ENV: str(tmp_path),
        receipts.RUN_UID_ENV: uid,
        receipts.SUBSCRIPTION_ENV: subscription,
        receipts.RESOURCE_GROUP_ENV: "rg",
        scenario._phase.PHASE_ENV: scenario._phase.REGULAR,
    }.items():
        monkeypatch.setenv(name, value)
    cli = EmbeddedCLI()
    cli.az_cli = runtime.cli
    mocker.patch.object(scenario, "EmbeddedCLI", return_value=cli)
    mocker.patch.object(scenario.fixtures, "cli", cli)
    mocker.patch.object(scenario.fixtures, "ENTITY_RG", "rg")
    mocker.patch.object(scenario.fixtures, "ENTITY_LOCATION", "centraluseuap")
    mocker.patch.object(scenario.fixtures, "_get_run_uid", return_value=uid)
    with scenario._phase_runtime.activate(subscription, existing=[cli]):
        mocker.patch("azure.cli.core._profile.Profile", return_value=SimpleNamespace(
            load_cached_subscriptions=lambda: [{"id": subscription, "name": "offline"}],
        ))
        commands = mocker.spy(cli, "invoke")
        scenario.test_dps_unit_capacity_owned_lifecycle(mocker.Mock())

    assert not runtime.resources
    assert runtime.resource_counts == [1, 1, 0, 1, 0]
    writes = [(request.method, urlsplit(request.url).path, json.loads(request.body) if request.body else None)
              for request in runtime.requests if request.method in ("PUT", "DELETE")]
    names = [f"clitest-dps-{kind}-{uid[:12]}" for kind in ("unit1", "unitdefault")]
    assert [(method, path.rsplit("/", 1)[1]) for method, path, _ in writes] == [
        ("PUT", names[0]), ("PUT", names[0]), ("DELETE", names[0]),
        ("PUT", names[1]), ("DELETE", names[1]),
    ]
    for method, _, body in writes:
        if method == "PUT":
            assert body["sku"]["capacity"] == 1
            assert body["properties"]["disableLocalAuth"] is True
            assert body["tags"]["runUid"] == uid
    assert writes[1][2]["tags"]["unitValidation"] == "passed"
    for kind in ("unit1", "unitdefault"):
        assert json.loads((tmp_path / f"created-{kind}.json").read_text())["create_completed"] is True
        assert json.loads((tmp_path / f"deleted-{kind}.json").read_text())["delete_completed"] is True
    creates = [call.args[0] for call in commands.call_args_list if call.args[0].startswith("iot dps create")]
    assert len(creates) == 4
    assert creates[0].endswith("--unit 0") and creates[1].endswith("--unit 1")
    assert creates[2].endswith("--unit -1") and "--unit" not in creates[3]
    updates = [call.args[0] for call in commands.call_args_list if call.args[0].startswith("iot dps update")]
    assert len(updates) == 3
    assert updates[0].endswith("sku.capacity=0") and updates[1].endswith("sku.capacity=-1")
    assert updates[2].endswith("tags.unitValidation=passed")
    assert sum(call.args[0].startswith("iot dps list") for call in commands.call_args_list) == 2


def test_dps_actual_local_auth_update_lifecycle_keeps_tags_object(dps_management_cli, mocker):
    from azext_iot.common.embedded_cli import EmbeddedCLI
    from azext_iot.tests.dps.core import test_dps_disable_local_auth_int as scenario

    runtime = dps_management_cli
    runtime.resource["tags"] = {"intTest": "true", "runUid": "a" * 32, "kind": "dla"}
    runtime.resource["properties"]["disableLocalAuth"] = False
    cli = EmbeddedCLI()
    cli.az_cli = runtime.cli
    mocker.patch.object(scenario, "cli", cli)
    scenario.test_dps_update_disable_local_auth({
        "name": "dps", "resourceGroup": "rg", "dps": deepcopy(runtime.resource),
    })
    writes = [json.loads(request.body) for request in runtime.requests if request.method == "PUT"]
    assert len(writes) == 3
    assert [body["properties"]["disableLocalAuth"] for body in writes] == [True, True, False]
    assert all(isinstance(body["tags"], dict) for body in writes)
    assert writes[1]["tags"]["testtag"] == "value"


def test_dps_unit_help_and_internal_update_argument_are_not_public(dps_management_cli, capsys):
    code, _, output = dps_management_cli.invoke("create", ["--help"])
    assert code == 0
    assert "Integer minimum: 1" in " ".join((output + capsys.readouterr().out).split())
    code, _, output = dps_management_cli.invoke("update", ["--help"])
    assert code == 0
    help_output = (output + capsys.readouterr().out).lower()
    assert "--ids" in help_output
    assert "--unit" not in help_output and "dps_capacity_edited" not in help_output
    assert "dps-capacity-edited" not in help_output
    for option in ("--unit", "--dps-capacity-edited", "--__DPS_CAPACITY_EDITED"):
        code, _, _ = dps_management_cli.invoke("update", [option, "1"])
        assert code != 0
    assert dps_management_cli.requests == []
