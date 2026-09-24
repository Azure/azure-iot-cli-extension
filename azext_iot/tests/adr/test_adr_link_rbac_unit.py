# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
from io import StringIO
import json
import logging
import re
import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
)
from azure.cli.core.cloud import AZURE_CHINA_CLOUD, AZURE_PUBLIC_CLOUD, AZURE_US_GOV_CLOUD
from azure.core.credentials import AccessToken
from azure.mgmt.authorization import AuthorizationManagementClient

from azext_iot.adr.rbac import (
    ADR_ADMINISTRATOR_ROLE,
    ADR_CONTRIBUTOR_ROLE,
    HUB_DATA_ROLE,
    LINK_ROLE_IDS,
    LINK_ROLE_MATRIX,
    LinkRbacManager,
    OWNER_ROLE,
    _assignment_scope_applies,
    _scope_subscription,
    format_role_requirements,
    resolve_linked_resource_principal,
    resolve_namespace_outbound_principal,
)

NS_SCOPE = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.DeviceRegistry/namespaces/ns"
)
TARGET_SCOPE = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub"
)
UAMI = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/link"
)


def _result(payload, success=True):
    result = MagicMock()
    result.success.return_value = success
    result.as_json.return_value = payload
    return result


def _access_token(object_id="caller-object-id"):
    claims = base64.urlsafe_b64encode(
        json.dumps({"oid": object_id}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{claims}.signature"


@pytest.fixture(autouse=True)
def token_profile(mocker):
    """Keep RBAC token acquisition isolated from the local Azure login."""
    profile = mocker.patch("azext_iot.adr.rbac.Profile")
    profile.return_value.get_raw_token.return_value = (
        ("Bearer", _access_token(), {}),
        "sub",
        "tenant",
    )
    return profile


def _namespace(outbound=None):
    properties = {}
    if outbound is not None:
        properties["outboundIdentity"] = outbound
    return {
        "id": NS_SCOPE,
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "ns-system",
            "userAssignedIdentities": {
                UAMI: {"principalId": "ns-user"}
            },
        },
        "properties": properties,
    }


def _resource():
    return {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "target-system",
            "userAssignedIdentities": {
                UAMI: {"principalId": "target-user"}
            },
        }
    }


def test_role_matrix_is_authoritative_and_never_grants_user_content_roles():
    # Independent contracts: do not derive expected grants from the matrix under test.
    assert {
        kind: [(rule.principal, rule.role, rule.scope) for rule in rules]
        for kind, rules in LINK_ROLE_MATRIX.items()
    } == {
        "hub": [
            ("namespace", "Contributor", "target"),
            ("namespace", "IoT Hub Data Contributor", "target"),
            ("linked", "Contributor", "namespace"),
        ],
        "dps": [
            ("namespace", "Contributor", "target"),
            ("linked", "Contributor", "namespace"),
            ("namespace_system", "Azure Device Registry Administrator", "namespace"),
        ],
        "su": [
            ("namespace", "Contributor", "target"),
            ("linked", "Azure Device Registry Contributor", "namespace"),
        ],
    }
    assert ADR_CONTRIBUTOR_ROLE == "Azure Device Registry Contributor"
    assert LINK_ROLE_IDS[ADR_ADMINISTRATOR_ROLE] == "12675fd7-7f59-493f-9201-f7944860a2f1"
    assert "namespace system-assigned MI -> Azure Device Registry Administrator on namespace" in (
        format_role_requirements("dps")
    )
    assert format_role_requirements("su") == (
        "namespace outbound MI -> Contributor on SU; "
        "SU selected inbound MI -> Azure Device Registry Contributor on namespace"
    )
    assert all(
        rule.principal != "signed_in_user"
        for rules in LINK_ROLE_MATRIX.values()
        for rule in rules
    )
    hub_requirements = format_role_requirements("hub")
    assert HUB_DATA_ROLE in hub_requirements
    assert (
        "when an inbound identity is selected, HUB selected inbound MI"
        in hub_requirements
    )
    assert "when an inbound identity is selected" not in (
        format_role_requirements("dps")
    )
    assert _scope_subscription(TARGET_SCOPE) == "sub"
    assert _scope_subscription("/") is None


@pytest.mark.parametrize("assignment_scope,trusted,expected", [
    ("/providers/Microsoft.Management/managementGroups/parent", True, True),
    ("/providers/Microsoft.Management/managementGroups/parent", False, False),
    ("/providers/Microsoft.Management/managementGroups/unrelated", False, False),
    ("/providers/Microsoft.Management/managementGroups/parent/children/other", True, False),
    ("/providers/Microsoft.Management/managementGroups", True, False),
    ("/providers/Other/managementGroups/parent", True, False),
    ("/subscriptions/other", True, False),
    ("/subscriptions/sub/resourceGroups/other", True, False),
    (NS_SCOPE + "/children/child", True, False),
    ("/subscriptions/sub", False, True),
    (NS_SCOPE.upper(), False, True),
])
def test_recovery_scope_requires_authoritative_inheritance_for_management_groups(assignment_scope, trusted, expected):
    assert _assignment_scope_applies(assignment_scope, NS_SCOPE, inherited_at_scope=trusted) is expected


@pytest.mark.parametrize("scope", [None, "", "subscriptions/sub"])
def test_strict_recovery_cannot_fall_back_to_unscoped_role_list(scope):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    with pytest.raises(InvalidArgumentValueError, match="explicit ARM scope"):
        manager._assignment_exists("principal", "Contributor", scope, strict=True)
    manager.cli.invoke.assert_not_called()


@pytest.mark.parametrize("scenario,expected", [
    ("applicable", True), ("unrelated", False), ("wrong-principal", False), ("wrong-role", False),
    ("conditional", False), ("condition-version", False), ("foreign-subscription", False),
])
def test_strict_management_group_roles_use_actual_cli_arm_at_scope_query(mocker, mocked_response, scenario, expected):
    """The real CLI and Authorization SDK must retain only ARM-applicable ancestors."""
    from azure.cli.command_modules.role import custom as role_commands

    principal = "11111111-1111-1111-1111-111111111111"
    role_id = "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/" + LINK_ROLE_IDS["Contributor"]
    assignment = {
        "id": "/providers/Microsoft.Management/managementGroups/parent/providers/Microsoft.Authorization/roleAssignments/one",
        "name": "one", "type": "Microsoft.Authorization/roleAssignments",
        "properties": {"principalId": principal, "roleDefinitionId": role_id,
                       "scope": "/providers/Microsoft.Management/managementGroups/parent"},
    }
    changes = {
        "wrong-principal": {"principalId": "22222222-2222-2222-2222-222222222222"},
        "wrong-role": {"roleDefinitionId": role_id + "-different"},
        "conditional": {"condition": "restricted", "conditionVersion": "2.0"},
        "condition-version": {"conditionVersion": "2.0"},
        "foreign-subscription": {"scope": "/subscriptions/unrelated"},
    }
    assignment["properties"].update(changes.get(scenario, {}))
    queries = []

    def role_assignments(request):
        parsed = urlsplit(request.url)
        query = parse_qs(parsed.query)
        queries.append((parsed.path, query))
        if (
            parsed.path == NS_SCOPE + "/providers/Microsoft.Authorization/roleAssignments"
            and query.get("$filter") == ["atScope()"]
        ):
            # ARM excludes an unrelated management group from scoped results.
            applicable = [] if scenario == "unrelated" else [assignment]
        else:
            # An unscoped response may contain a matching but unrelated MG grant.
            applicable = [assignment]
        return 200, {"Content-Type": "application/json"}, json.dumps({"value": applicable})

    mocked_response.add_callback(
        "GET", re.compile(r"https://management\.azure\.com/.*/roleAssignments(?:\?.*)?$"), callback=role_assignments,
    )
    if scenario not in {"unrelated", "wrong-principal", "wrong-role"}:
        mocked_response.add(
            "GET", "https://management.azure.com" + NS_SCOPE + "/providers/Microsoft.Authorization/roleDefinitions",
            json={"value": [{"id": role_id, "name": LINK_ROLE_IDS["Contributor"],
                             "properties": {"roleName": "Contributor", "type": "BuiltInRole"}}]},
        )
    credential = MagicMock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-unit-token", 4102444800)
    graph = mocker.patch.object(role_commands, "_get_object_stubs", side_effect=AssertionError("Graph is forbidden"))
    mocker.patch.object(role_commands, "_graph_client_factory", return_value=MagicMock())
    mocker.patch.object(role_commands, "_resolve_role_id", return_value=role_id)
    cli = MagicMock()
    manager = LinkRbacManager(MagicMock(), cli=cli)

    def invoke(command, **kwargs):
        parts = shlex.split(command)
        assert parts[:3] == ["role", "assignment", "list"]
        assert "--include-inherited" in parts
        assert parts[parts.index("--fill-principal-name") + 1] == "false"
        assert kwargs == {"subscription": "sub"}
        return _result(role_commands.list_role_assignments(
            MagicMock(), scope=parts[parts.index("--scope") + 1],
            assignee_object_id=parts[parts.index("--assignee-object-id") + 1],
            role=parts[parts.index("--role") + 1], include_inherited=True, fill_principal_name=False,
        ))

    cli.invoke.side_effect = invoke
    with AuthorizationManagementClient(credential, "sub", retry_total=0) as client:
        mocker.patch.object(role_commands, "_auth_client_factory", return_value=client)
        assert manager._assignment_exists(principal, "Contributor", NS_SCOPE, strict=True) is expected
    assert len(queries) == 1
    path, query = queries[0]
    assert path == NS_SCOPE + "/providers/Microsoft.Authorization/roleAssignments"
    assert query["$filter"] == ["atScope()"]
    cli.invoke.assert_called_once()
    graph.assert_not_called()


def test_namespace_outbound_principal_defaults_to_system_identity():
    assert resolve_namespace_outbound_principal(_namespace()) == "ns-system"


def test_namespace_outbound_principal_uses_selected_uami_case_insensitively():
    namespace = _namespace(
        {"type": "UserAssigned", "userAssignedIdentity": UAMI.upper()}
    )
    assert resolve_namespace_outbound_principal(namespace) == "ns-user"


@pytest.mark.parametrize(
    "namespace, error_type, message",
    [
        (
            {
                "identity": {"type": "UserAssigned"},
                "properties": {},
            },
            InvalidArgumentValueError,
            "system-assigned",
        ),
        (
            _namespace(
                {
                    "type": "UserAssigned",
                    "userAssignedIdentity": UAMI.replace("/link", "/missing"),
                }
            ),
            InvalidArgumentValueError,
            "not attached",
        ),
        (
            {
                **_namespace(
                    {"type": "UserAssigned", "userAssignedIdentity": UAMI}
                ),
                "identity": {
                    "type": "UserAssigned",
                    "userAssignedIdentities": {UAMI: {}},
                },
            },
            AzureResponseError,
            "principalId",
        ),
        (
            {
                **_namespace(),
                "identity": {
                    "type": "SystemAssigned",
                    "principalId": None,
                },
            },
            AzureResponseError,
            "principalId",
        ),
        (
            _namespace({"type": "FutureIdentity"}),
            InvalidArgumentValueError,
            "Unsupported",
        ),
    ],
)
def test_namespace_outbound_principal_errors(namespace, error_type, message):
    with pytest.raises(error_type, match=message):
        resolve_namespace_outbound_principal(namespace)


def test_linked_principal_supports_system_user_and_omitted_identity():
    resource = _resource()
    assert (
        resolve_linked_resource_principal(
            resource, {"type": "SystemAssigned"}, "Hub"
        )
        == "target-system"
    )
    assert (
        resolve_linked_resource_principal(
            resource,
            {"type": "UserAssigned", "userAssignedIdentity": UAMI.upper()},
            "Hub",
        )
        == "target-user"
    )
    assert resolve_linked_resource_principal(resource, None, "Hub") is None


@pytest.mark.parametrize(
    "resource, selected, error_type, message",
    [
        (
            {"identity": {"type": "UserAssigned"}},
            {"type": "SystemAssigned"},
            InvalidArgumentValueError,
            "not enabled",
        ),
        (
            _resource(),
            {
                "type": "UserAssigned",
                "userAssignedIdentity": UAMI.replace("/link", "/missing"),
            },
            InvalidArgumentValueError,
            "not attached",
        ),
        (
            {
                "identity": {
                    "type": "UserAssigned",
                    "userAssignedIdentities": {UAMI: {}},
                }
            },
            {"type": "UserAssigned", "userAssignedIdentity": UAMI},
            AzureResponseError,
            "principalId",
        ),
        (
            {"identity": {"type": "SystemAssigned"}},
            {"type": "SystemAssigned"},
            AzureResponseError,
            "principalId",
        ),
        (
            _resource(),
            {"type": "Future"},
            InvalidArgumentValueError,
            "Unsupported",
        ),
    ],
)
def test_linked_principal_errors(resource, selected, error_type, message):
    with pytest.raises(error_type, match=message):
        resolve_linked_resource_principal(resource, selected, "target")


def test_rbac_reuses_inherited_assignments_without_privilege_check_or_create():
    cli = MagicMock()
    cli.invoke.side_effect = [_result([{"id": "existing"}]) for _ in range(3)]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure(
        "hub", NS_SCOPE, TARGET_SCOPE, "ns-principal", "hub-principal"
    )

    commands = [call.args[0] for call in cli.invoke.call_args_list]
    assert len(commands) == 3
    assert all("--include-inherited" in command for command in commands)
    assert all("--all" not in command for command in commands)
    assert all(
        call.kwargs["subscription"] == "sub"
        for call in cli.invoke.call_args_list
    )
    assert not any("account get-access-token" in command for command in commands)
    assert not any("role assignment create" in command for command in commands)


def test_rbac_scope_query_passes_real_azure_cli_validation(mocker):
    from azure.cli.core import get_default_cli

    recording_cli = MagicMock()
    recording_cli.invoke.return_value = _result([])
    manager = LinkRbacManager(MagicMock(), cli=recording_cli)
    assert not manager._assignment_exists(
        "principal-id", OWNER_ROLE, TARGET_SCOPE
    )
    command = recording_cli.invoke.call_args.args[0]
    assert "--scope" in command
    assert "--include-inherited" in command
    assert "--assignee-object-id 'principal-id'" in command
    assert "--fill-principal-name false" in command
    assert "--all" not in command
    assert not manager._caller_can_assign("caller", TARGET_SCOPE)
    privilege_command = recording_cli.invoke.call_args.args[0]
    assert "--assignee-object-id 'caller'" in privilege_command
    assert "--fill-principal-name false" in privilege_command
    assert "--include-inherited" in privilege_command
    assert "--include-groups" in privilege_command
    assert "--all" not in privilege_command

    auth_client = MagicMock()
    auth_client.role_definitions._config.subscription_id = "sub"
    mocker.patch(
        "azure.cli.command_modules.role.custom._graph_client_factory",
        return_value=MagicMock(),
    )
    mocker.patch(
        "azure.cli.command_modules.role.custom._auth_client_factory",
        return_value=auth_client,
    )
    mocker.patch(
        "azure.cli.command_modules.role.custom._resolve_object_id",
        return_value="principal-id",
    )
    search = mocker.patch(
        "azure.cli.command_modules.role.custom._search_role_assignments",
        return_value=[],
    )
    network = mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("unit test attempted a network request"),
    )

    for parsed_command in (command, privilege_command):
        cli = get_default_cli()
        output = StringIO()
        assert (
            cli.invoke(
                shlex.split(parsed_command) + ["-o", "json"],
                out_file=output,
            )
            == 0
        )
        assert cli.result.error is None
    assert search.call_count == 2
    network.assert_not_called()


def test_hub_without_inbound_identity_skips_reverse_assignment():
    cli = MagicMock()
    cli.invoke.side_effect = [_result([{"id": "existing"}]) for _ in range(2)]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure("hub", NS_SCOPE, TARGET_SCOPE, "ns-principal", None)

    assert cli.invoke.call_count == 2


def test_rbac_authorized_caller_creates_only_missing_assignments():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),  # namespace -> Contributor target
        _result([{"id": "existing-data-role"}]),
        _result([]),  # linked -> Contributor namespace
        _result([{"roleDefinitionName": "Owner"}]),  # target privilege
        _result([]),  # namespace Owner
        _result([{"roleDefinitionName": "User Access Administrator"}]),
        _result({"id": "created-target"}),
        _result({"id": "created-namespace"}),
        _result([{"id": "visible-target"}]),
        _result([{"id": "visible-namespace"}]),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure(
        "hub", NS_SCOPE, TARGET_SCOPE, "ns-principal", "hub-principal"
    )

    creates = [
        call.args[0]
        for call in cli.invoke.call_args_list
        if "role assignment create" in call.args[0]
    ]
    assert len(creates) == 2
    assert all("--assignee-principal-type ServicePrincipal" in item for item in creates)
    assert not any(HUB_DATA_ROLE in item for item in creates)
    privilege_queries = [
        call.args[0]
        for call in cli.invoke.call_args_list
        if "role assignment list" in call.args[0]
        and "caller-object-id" in call.args[0]
    ]
    assert privilege_queries
    assert all("--include-groups" in item for item in privilege_queries)
    assert all("--include-inherited" in item for item in privilege_queries)
    assert all("--all" not in item for item in privilege_queries)


def test_rbac_unauthorized_fails_with_exact_remediation_before_create():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([]),
        _result([]),
        _result([]),
        _result([]),
        _result([]),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError) as raised:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal",
            namespace_system_principal_id="ns-system",
        )

    message = str(raised.value)
    assert "No link mutation was submitted" in message
    assert "--assignee-object-id 'ns-principal'" in message
    assert "--assignee-object-id 'dps-principal'" in message
    assert (
        "--assignee-object-id 'ns-system' --assignee-principal-type ServicePrincipal "
        f"--role 'Azure Device Registry Administrator' --scope '{NS_SCOPE}'"
    ) in message
    assert not any(
        "role assignment create" in call.args[0]
        for call in cli.invoke.call_args_list
    )


def test_atomic_rbac_plan_checks_every_service_before_any_assignment(token_profile):
    cli = MagicMock()
    cli.invoke.return_value = _result([])
    raw_token = token_profile.return_value.get_raw_token

    def acquire_token(**_):
        # Both service plans must be read before checking caller privileges.
        assert cli.invoke.call_count == 6
        return ("Bearer", _access_token("reader-object-id"), {}), "sub", "tenant"

    raw_token.side_effect = acquire_token
    manager = LinkRbacManager(MagicMock(), cli=cli)
    dps_scope = TARGET_SCOPE.replace(
        "Microsoft.Devices/IotHubs/hub",
        "Microsoft.Devices/provisioningServices/dps",
    )
    requests = [
        {
            "link_type": "dps",
            "namespace_scope": NS_SCOPE,
            "target_scope": dps_scope,
            "namespace_principal_id": "ns-principal",
            "linked_principal_id": "dps-principal",
            "namespace_system_principal_id": "ns-system",
        },
        {
            "link_type": "hub",
            "namespace_scope": NS_SCOPE,
            "target_scope": TARGET_SCOPE,
            "namespace_principal_id": "ns-principal",
            "linked_principal_id": "hub-principal",
        },
    ]

    with pytest.raises(AzureResponseError, match="No link mutation"):
        manager.ensure_many(requests)

    commands = [call.args[0] for call in cli.invoke.call_args_list]
    raw_token.assert_called_once_with(subscription="sub", resource=None)
    assert not any("role assignment create" in command for command in commands)


def test_su_creates_exact_two_service_grants_without_graph(token_profile, mocker):
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        _result({"id": "created-1"}),
        _result({"id": "created-2"}),
        _result([{"id": "visible-1"}]),
        _result([{"id": "visible-2"}]),
    ]
    network = mocker.patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network/Graph"))
    cli_ctx = SimpleNamespace(cloud=AZURE_PUBLIC_CLOUD)
    raw_token = token_profile.return_value.get_raw_token
    raw_token.side_effect = [
        (("Bearer", _access_token("owner-object-id"), {}), "sub", "tenant"),
    ]
    manager = LinkRbacManager(cli_ctx, cli=cli)
    target = TARGET_SCOPE.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.DeviceUpdate/updateInstances/su")

    manager.ensure(
        "su", NS_SCOPE, target, "ns-principal", "su-principal"
    )

    commands = [call.args[0] for call in cli.invoke.call_args_list]
    assert [call.kwargs for call in raw_token.call_args_list] == [
        {"subscription": "sub", "resource": None},
    ]
    assert not any("get-access-token" in command for command in commands)
    assert [command for command in commands if command.startswith("role assignment create ")] == [
        "role assignment create --assignee-object-id 'ns-principal' "
        f"--assignee-principal-type ServicePrincipal --role 'Contributor' --scope '{target}'",
        "role assignment create --assignee-object-id 'su-principal' "
        f"--assignee-principal-type ServicePrincipal --role 'Azure Device Registry Contributor' --scope '{NS_SCOPE}'",
    ]
    assert all("--fill-principal-name false" in command for command in commands if " list " in command)
    network.assert_not_called()


@pytest.mark.parametrize("authorized", [True, False])
def test_su_missing_registry_role_is_scoped_and_privilege_gated(mocker, authorized):
    scope = TARGET_SCOPE.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.DeviceUpdate/updateInstances/su")
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    mocker.patch.object(
        manager, "_assignment_exists",
        side_effect=lambda _principal, role, _scope: role != ADR_CONTRIBUTOR_ROLE,
    )
    privilege = mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    invoke = mocker.patch.object(manager, "_invoke_json")
    wait = mocker.patch.object(manager, "_wait_for_assignments")

    if authorized:
        manager.ensure("su", NS_SCOPE, scope, "ns-principal", "su-principal")
        invoke.assert_called_once_with(
            "role assignment create --assignee-object-id 'su-principal' "
            "--assignee-principal-type ServicePrincipal --role 'Azure Device Registry Contributor' "
            f"--scope '{NS_SCOPE}'",
            subscription="sub",
        )
        wait.assert_called_once_with([("su-principal", "Azure Device Registry Contributor", NS_SCOPE)])
    else:
        with pytest.raises(AzureResponseError, match="Azure Device Registry Contributor"):
            manager.ensure("su", NS_SCOPE, scope, "ns-principal", "su-principal")
        invoke.assert_not_called()
        wait.assert_not_called()
    privilege.assert_called_once_with("caller", NS_SCOPE)


def test_su_existing_roles_need_neither_token_nor_graph(token_profile, mocker):
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([{"id": "existing"}]),
        _result([{"id": "existing"}]),
    ]
    network = mocker.patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network/Graph"))
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure("su", NS_SCOPE, TARGET_SCOPE, "ns-principal", "su-principal")
    assert cli.invoke.call_count == 2
    token_profile.assert_not_called()
    network.assert_not_called()


@pytest.mark.parametrize("token", [None, "", 123])
def test_access_token_requires_nonempty_string(token_profile, token):
    cli = MagicMock()
    token_profile.return_value.get_raw_token.return_value = (
        ("Bearer", token, {}), "sub", "tenant"
    )
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError, match="acquire an access token"):
        manager._access_token("sub")  # pylint: disable=protected-access
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("resource", [None, "https://management.azure.com/"])
def test_access_token_does_not_log_secret(token_profile, mocker, caplog, resource):
    token = "synthetic-bearer-token-do-not-log"
    token_profile.return_value.get_raw_token.return_value = (
        ("Bearer", token, {}), "target-sub", "target-tenant"
    )
    # Use the real EmbeddedCLI wrapper so routing token acquisition back
    # through it would expose the synthetic token to the debug-log assertion.
    cli = MagicMock()
    cli.result.error = None

    def invoke(args, out_file):
        assert args[:2] == ["account", "get-access-token"]
        out_file.write(json.dumps(token))
        return 0

    cli.invoke.side_effect = invoke
    mocker.patch("azext_iot.common.embedded_cli.get_default_cli", return_value=cli)
    cli_ctx = SimpleNamespace(data={"subscription_id": "hosting-sub"})
    manager = LinkRbacManager(cli_ctx)
    caplog.set_level(logging.DEBUG)

    assert manager._access_token("target-sub", resource=resource) == token

    token_profile.assert_called_once_with(cli_ctx=cli_ctx)
    token_profile.return_value.get_raw_token.assert_called_once_with(
        subscription="target-sub", resource=resource
    )
    cli.invoke.assert_not_called()
    assert token not in caplog.text


@pytest.mark.parametrize("cloud", [AZURE_PUBLIC_CLOUD, AZURE_US_GOV_CLOUD, AZURE_CHINA_CLOUD])
def test_tokens_use_host_cloud_and_target_subscription(token_profile, cloud):
    cli_ctx = SimpleNamespace(cloud=cloud, data={"subscription_id": "hosting-sub"})
    cli = MagicMock()
    manager = LinkRbacManager(cli_ctx, cli=cli)
    raw_token = token_profile.return_value.get_raw_token
    raw_token.side_effect = [
        (("Bearer", _access_token("target-caller"), {}), "target-sub", "target-tenant"),
        (("Bearer", _access_token("other-caller"), {}), "other-sub", "other-tenant"),
    ]

    assert manager._current_assignee_object_id("target-sub") == "target-caller"
    assert manager._current_assignee_object_id("other-sub") == "other-caller"
    # Caches remain subscription-scoped, not scoped to the hosting CLI login.
    assert manager._current_assignee_object_id("target-sub") == "target-caller"

    assert [call.kwargs for call in token_profile.call_args_list] == [
        {"cli_ctx": cli_ctx}
    ] * 2
    assert [call.kwargs for call in raw_token.call_args_list] == [
        {"subscription": "target-sub", "resource": None},
        {"subscription": "other-sub", "resource": None},
    ]
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("error", [
    AzureResponseError("login required"), RuntimeError("profile unavailable"),
])
def test_access_token_profile_failure_propagates(token_profile, error):
    token_profile.return_value.get_raw_token.side_effect = error
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())

    with pytest.raises(type(error)) as raised:
        manager._access_token("sub")

    assert raised.value is error
    manager.cli.invoke.assert_not_called()


def test_su_assignment_lookup_failure_stops_before_grants(mocker):
    cli = MagicMock()
    cli.invoke.side_effect = AzureResponseError("assignment lookup denied")
    manager = LinkRbacManager(MagicMock(), cli=cli)
    privilege = mocker.patch.object(manager, "_caller_can_assign")
    with pytest.raises(AzureResponseError, match="assignment lookup denied"):
        manager.ensure("su", NS_SCOPE, TARGET_SCOPE, "ns-principal", "su-principal")
    cli.invoke.assert_called_once()
    assert cli.invoke.call_args.args[0].startswith("role assignment list ")
    privilege.assert_not_called()


def test_missing_current_assignee_stops_before_privilege_checks(token_profile):
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([]),
    ]
    token_profile.return_value.get_raw_token.return_value = (
        ("Bearer", "not-a-jwt", {}), "sub", "tenant"
    )
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError, match="signed-in principal"):
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal",
            namespace_system_principal_id="ns-system",
        )


def test_rbac_creation_failure_lists_remaining_commands():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([{"id": "existing-self-role"}]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        RuntimeError("authorization changed"),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError, match="before namespace mutation") as raised:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal",
            namespace_system_principal_id="ns-system",
        )
    assert "--assignee-object-id 'ns-principal'" in str(raised.value)


def test_rbac_creation_race_reuses_assignment_created_by_another_actor(caplog):
    caplog.set_level(logging.WARNING, logger="azext_iot.adr.rbac")
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([{"id": "existing-self-role"}]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        RuntimeError("assignment already exists"),
        _result([{"id": "raced-assignment"}]),
        _result({"id": "created-second"}),
        _result([{"id": "visible-second"}]),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure(
        "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal",
        namespace_system_principal_id="ns-system",
    )

    creates = [
        call.args[0]
        for call in cli.invoke.call_args_list
        if "role assignment create" in call.args[0]
    ]
    assert len(creates) == 2
    completed = caplog.text.split("Completed these role-assignment creation requests")[1]
    assert "principalId=dps-principal" in completed
    assert "principalId=ns-principal" not in completed


def test_created_assignments_wait_for_visibility_with_capped_backoff():
    now = [0]
    sleeps = []

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    manager = LinkRbacManager(
        MagicMock(),
        cli=MagicMock(),
        clock=lambda: now[0],
        sleeper=sleeper,
    )
    manager._assignment_exists = MagicMock(  # pylint: disable=protected-access
        side_effect=[
            False,
            False,
            False,
            False,
            False,
            True,
        ]
    )

    manager._wait_for_assignments(  # pylint: disable=protected-access
        [("principal", "Contributor", TARGET_SCOPE)]
    )

    assert sleeps == [2, 4, 8, 10, 10]


def test_assignment_visibility_tolerates_transient_read():
    now = [0]

    def sleeper(delay):
        now[0] += delay

    manager = LinkRbacManager(
        MagicMock(),
        cli=MagicMock(),
        clock=lambda: now[0],
        sleeper=sleeper,
    )
    manager._assignment_exists = MagicMock(  # pylint: disable=protected-access
        side_effect=[
            AzureResponseError("throttled"),
            True,
        ]
    )

    manager._wait_for_assignments(  # pylint: disable=protected-access
        [("principal", "Contributor", TARGET_SCOPE)]
    )

    assert now[0] == 2


def test_assignment_visibility_timeout_fails_safely_and_is_retryable():
    now = [0]
    sleeps = []

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    manager = LinkRbacManager(
        MagicMock(),
        cli=MagicMock(),
        clock=lambda: now[0],
        sleeper=sleeper,
        propagation_timeout=3,
    )
    manager._assignment_exists = MagicMock(  # pylint: disable=protected-access
        return_value=False
    )

    with pytest.raises(AzureResponseError) as raised:
        manager._wait_for_assignments(  # pylint: disable=protected-access
            [("principal", "Contributor", TARGET_SCOPE)]
        )

    assert sleeps == [2, 1]
    assert "No namespace mutation was submitted" in str(raised.value)
    assert "may already exist" in str(raised.value)
    assert "retrying the link command is safe" in str(raised.value)


def test_assignment_visibility_empty_set_returns_immediately():
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())

    manager._wait_for_assignments([])  # pylint: disable=protected-access

    manager.cli.invoke.assert_not_called()


@pytest.mark.parametrize("link_type", ["hub", "dps", "su"])
def test_assignment_plan_is_visible_before_every_write(mocker, caplog, capsys, link_type):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    mocker.patch.object(manager, "_assignment_exists", return_value=False)
    mocker.patch.object(manager, "_caller_can_assign", return_value=True)
    mocker.patch.object(manager, "_wait_for_assignments")
    caplog.set_level(logging.WARNING, logger="azext_iot.adr.rbac")
    target = TARGET_SCOPE.replace("/sub/", "/target-sub/")
    namespace = NS_SCOPE.replace("/sub/", "/namespace-sub/")

    def create(command, subscription):
        assert command.startswith("role assignment create ")
        assert "before updating the namespace" in caplog.text
        assert f"scope={target}; subscription=target-sub" in caplog.text
        assert f"scope={namespace}; subscription=namespace-sub" in caplog.text
        assert subscription in ("target-sub", "namespace-sub")
        return {"id": "created"}

    invoke = mocker.patch.object(manager, "_invoke_json", side_effect=create)
    manager.ensure(
        link_type, namespace, target, "ns-principal", "linked-principal",
        namespace_system_principal_id="ns-system",
    )

    assert invoke.call_count == len(LINK_ROLE_MATRIX[link_type])
    assert caplog.text.count("before updating the namespace") == 1
    assert "Completed these role-assignment creation requests" in caplog.text
    assert "service authorization may still need time to propagate" in caplog.text
    assert f"namespace outbound MI -> Contributor on {link_type.upper()}" in caplog.text
    role = "Azure Device Registry Contributor" if link_type == "su" else "Contributor"
    assert f"{link_type.upper()} selected inbound MI -> {role} on namespace" in caplog.text
    assert "principalId=ns-principal" in caplog.text
    assert "principalId=linked-principal" in caplog.text
    if link_type == "dps":
        assert "namespace system-assigned MI -> Azure Device Registry Administrator on namespace" in caplog.text
        assert "principalId=ns-system" in caplog.text
    if link_type == "su":
        assert invoke.call_count == 2
        assert "ADU first-party" not in caplog.text
    assert "caller-object-id" not in caplog.text
    assert _access_token() not in caplog.text
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("already_assigned", [False, True])
def test_no_automatic_grant_notice_when_no_creation_can_occur(mocker, caplog, already_assigned):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    mocker.patch.object(manager, "_assignment_exists", return_value=already_assigned)
    mocker.patch.object(manager, "_caller_can_assign", return_value=False)
    invoke = mocker.patch.object(manager, "_invoke_json")
    caplog.set_level(logging.WARNING, logger="azext_iot.adr.rbac")

    if already_assigned:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal", namespace_system_principal_id="ns-system",
        )
    else:
        with pytest.raises(AzureResponseError, match="No link mutation was submitted"):
            manager.ensure(
                "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal", namespace_system_principal_id="ns-system",
            )

    invoke.assert_not_called()
    assert "before updating the namespace" not in caplog.text


def test_partial_assignment_failure_reports_completed_and_remaining_requests(mocker):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    mocker.patch.object(manager, "_assignment_exists", return_value=False)
    mocker.patch.object(manager, "_caller_can_assign", return_value=True)
    error = AzureResponseError("Original assignment rejection")
    mocker.patch.object(manager, "_invoke_json", side_effect=[{"id": "created"}, error])
    wait = mocker.patch.object(manager, "_wait_for_assignments")

    with pytest.raises(AzureResponseError) as raised:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal", namespace_system_principal_id="ns-system",
        )

    completed, remaining = str(raised.value).split("Complete these exact remediation commands")
    assert "Assignment requests completed before the failure" in completed
    assert "principalId=ns-principal" in completed
    assert "principalId=dps-principal" not in completed
    assert "--assignee-object-id 'dps-principal'" in remaining
    assert "--assignee-object-id 'ns-principal'" not in remaining
    assert raised.value.__cause__ is error
    wait.assert_not_called()


def test_rbac_rejects_unknown_link_type_and_failed_cli_command():
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    with pytest.raises(InvalidArgumentValueError, match="Unsupported"):
        manager.ensure("unknown", NS_SCOPE, TARGET_SCOPE, "ns", "target")

    manager.cli.invoke.return_value = _result({}, success=False)
    with pytest.raises(AzureResponseError, match="preflight"):
        manager._invoke_json("account show")


@pytest.mark.parametrize("operation", ["ensure_many", "verify_many"])
@pytest.mark.parametrize("principal", [None, ""])
def test_dps_rbac_cannot_skip_missing_namespace_system_principal(operation, principal):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    request = {
        "link_type": "dps", "namespace_scope": NS_SCOPE, "target_scope": TARGET_SCOPE,
        "namespace_principal_id": "outbound-uami", "linked_principal_id": "dps-principal",
        "namespace_system_principal_id": principal,
    }
    kwargs = {"guard": MagicMock()} if operation == "verify_many" else {}
    with pytest.raises(AzureResponseError, match="namespace system-assigned principalId"):
        getattr(manager, operation)([request], **kwargs)
    manager.cli.invoke.assert_not_called()


@pytest.mark.parametrize("existing,authorized", [(True, False), (False, True), (False, False)])
def test_dps_self_role_is_exact_reused_and_privilege_gated(mocker, existing, authorized):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    assignment = ("namespace-system", ADR_ADMINISTRATOR_ROLE, NS_SCOPE)
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    lookup = mocker.patch.object(
        manager, "_assignment_exists", side_effect=lambda *args: existing or args != assignment,
    )
    privilege = mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    invoke = mocker.patch.object(manager, "_invoke_json")
    wait = mocker.patch.object(manager, "_wait_for_assignments")
    args = ("dps", NS_SCOPE, TARGET_SCOPE, "namespace-outbound", "dps-principal")
    kwargs = {"namespace_system_principal_id": "namespace-system"}
    if existing or authorized:
        manager.ensure(*args, **kwargs)
    else:
        with pytest.raises(AzureResponseError, match="Azure Device Registry Administrator") as error:
            manager.ensure(*args, **kwargs)
        assert "--assignee-object-id 'namespace-system'" in str(error.value)
        assert "--assignee-object-id 'namespace-outbound'" not in str(error.value)
    assert assignment in [call.args for call in lookup.call_args_list]
    if existing:
        privilege.assert_not_called()
    else:
        privilege.assert_called_once_with("caller", NS_SCOPE)
    if authorized and not existing:
        invoke.assert_called_once_with(
            "role assignment create --assignee-object-id 'namespace-system' "
            "--assignee-principal-type ServicePrincipal --role 'Azure Device Registry Administrator' "
            f"--scope '{NS_SCOPE}'", subscription="sub",
        )
        wait.assert_called_once_with([assignment])
    else:
        invoke.assert_not_called()
        wait.assert_not_called()


@pytest.mark.parametrize("present", [False, True])
def test_recovery_verifies_namespace_self_role_without_granting(mocker, present):
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    lookup = mocker.patch.object(
        manager, "_assignment_exists",
        side_effect=lambda _principal, role, _scope, **_kwargs: present or role != ADR_ADMINISTRATOR_ROLE,
    )
    guard = MagicMock()
    request = {
        "link_type": "dps", "namespace_scope": NS_SCOPE, "target_scope": TARGET_SCOPE,
        "namespace_principal_id": "outbound-uami", "linked_principal_id": "dps-principal",
        "namespace_system_principal_id": "namespace-system",
    }
    if present:
        manager.verify_many([request], guard=guard)
    else:
        with pytest.raises(AzureResponseError, match="Azure Device Registry Administrator"):
            manager.verify_many([request], guard=guard)
    lookup.assert_any_call("namespace-system", ADR_ADMINISTRATOR_ROLE, NS_SCOPE, strict=True)
    assert guard.call_count == 6
    manager.cli.invoke.assert_not_called()
