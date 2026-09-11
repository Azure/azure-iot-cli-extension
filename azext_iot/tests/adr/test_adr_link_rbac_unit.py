# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
from io import StringIO
import json
import logging
import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
)
from azure.cli.core.cloud import AZURE_CHINA_CLOUD, AZURE_PUBLIC_CLOUD, AZURE_US_GOV_CLOUD

from azext_iot.adr.rbac import (
    ADU_FIRST_PARTY_APP_ID,
    GRAPH_SERVICE_PRINCIPALS_URL,
    HUB_DATA_ROLE,
    LINK_ROLE_MATRIX,
    LinkRbacManager,
    OWNER_ROLE,
    SU_DATA_ROLE,
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


def _graph_response(principals):
    response = MagicMock()
    response.json.return_value = {"value": principals}
    return response


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
    assert LINK_ROLE_MATRIX["hub"][1].role == HUB_DATA_ROLE
    assert (
        LINK_ROLE_MATRIX["su"][1].principal,
        LINK_ROLE_MATRIX["su"][1].role,
        LINK_ROLE_MATRIX["su"][1].scope,
    ) == ("namespace", SU_DATA_ROLE, "target")
    assert "namespace outbound MI -> Device Update Administrator on SU" in (
        format_role_requirements("su")
    )
    assert {rule.principal for rule in LINK_ROLE_MATRIX["su"]} == {
        "namespace",
        "linked",
        "adu_first_party",
    }
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
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError) as raised:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal"
        )

    message = str(raised.value)
    assert "No link mutation was submitted" in message
    assert "--assignee-object-id 'ns-principal'" in message
    assert "--assignee-object-id 'dps-principal'" in message
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
        assert cli.invoke.call_count == 5
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


def test_su_resolves_first_party_principal_and_includes_its_assignment(token_profile):
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([]),
        _result([]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        _result({"id": "created-1"}),
        _result({"id": "created-2"}),
        _result({"id": "created-3"}),
        _result({"id": "created-4"}),
        _result([{"id": "visible-1"}]),
        _result([{"id": "visible-2"}]),
        _result([{"id": "visible-3"}]),
        _result([{"id": "visible-4"}]),
    ]
    graph_get = MagicMock(
        return_value=_graph_response([{"id": "adu-object-id"}])
    )
    cli_ctx = SimpleNamespace(cloud=AZURE_PUBLIC_CLOUD)
    raw_token = token_profile.return_value.get_raw_token
    raw_token.side_effect = [
        (("Bearer", "graph-access-token", {}), "sub", "tenant"),
        (("Bearer", _access_token("owner-object-id"), {}), "sub", "tenant"),
    ]
    manager = LinkRbacManager(cli_ctx, cli=cli, graph_get=graph_get)

    manager.ensure(
        "su", NS_SCOPE, TARGET_SCOPE, "ns-principal", "su-principal"
    )

    commands = [call.args[0] for call in cli.invoke.call_args_list]
    assert [call.kwargs for call in raw_token.call_args_list] == [
        {
            "subscription": "sub",
            "resource": AZURE_PUBLIC_CLOUD.endpoints.microsoft_graph_resource_id,
        },
        {"subscription": "sub", "resource": None},
    ]
    assert not any("get-access-token" in command for command in commands)
    graph_get.assert_called_once_with(
        GRAPH_SERVICE_PRINCIPALS_URL,
        headers={"Authorization": "Bearer graph-access-token"},
        params={
            "$filter": f"appId eq '{ADU_FIRST_PARTY_APP_ID}'",
            "$select": "id",
        },
        timeout=30,
    )
    assert any(
        "role assignment create" in command
        and "--assignee-object-id 'adu-object-id'" in command
        for command in commands
    )
    assert any(
        "role assignment create" in command
        and "--assignee-object-id 'ns-principal'" in command
        and f"--role '{SU_DATA_ROLE}'" in command
        and f"--scope '{TARGET_SCOPE}'" in command
        for command in commands
    )


@pytest.mark.parametrize("authorized", [True, False])
def test_su_missing_data_role_is_scoped_and_privilege_gated(mocker, authorized):
    scope = TARGET_SCOPE.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.DeviceUpdate/updateInstances/su")
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    mocker.patch.object(manager, "_resolve_adu_principal", return_value="adu-principal")
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    mocker.patch.object(
        manager, "_assignment_exists",
        side_effect=lambda _principal, role, _scope: role != SU_DATA_ROLE,
    )
    privilege = mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    invoke = mocker.patch.object(manager, "_invoke_json")
    wait = mocker.patch.object(manager, "_wait_for_assignments")

    if authorized:
        manager.ensure("su", NS_SCOPE, scope, "ns-principal", "su-principal")
        invoke.assert_called_once_with(
            "role assignment create --assignee-object-id 'ns-principal' "
            f"--assignee-principal-type ServicePrincipal --role '{SU_DATA_ROLE}' "
            f"--scope '{scope}'",
            subscription="sub",
        )
        wait.assert_called_once_with([("ns-principal", SU_DATA_ROLE, scope)])
    else:
        with pytest.raises(AzureResponseError, match=SU_DATA_ROLE):
            manager.ensure("su", NS_SCOPE, scope, "ns-principal", "su-principal")
        invoke.assert_not_called()
        wait.assert_not_called()
    privilege.assert_called_once_with("caller", scope)


def test_su_reports_unresolvable_first_party_principal():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([{"id": "existing"}]),
        _result([{"id": "existing"}]),
        _result([{"id": "existing"}]),
    ]
    manager = LinkRbacManager(
        MagicMock(),
        cli=cli,
        graph_get=MagicMock(return_value=_graph_response([])),
    )

    with pytest.raises(AzureResponseError, match="first-party"):
        manager.ensure(
            "su", NS_SCOPE, TARGET_SCOPE, "ns-principal", "su-principal"
        )


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


@pytest.mark.parametrize("resource", [None, "https://graph.microsoft.com/"])
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
    graph_get = MagicMock(return_value=_graph_response([{"id": "adu-object-id"}]))
    manager = LinkRbacManager(cli_ctx, cli=cli, graph_get=graph_get)
    raw_token = token_profile.return_value.get_raw_token
    raw_token.side_effect = [
        (("Bearer", _access_token("target-caller"), {}), "target-sub", "target-tenant"),
        (("Bearer", "synthetic-graph-token", {}), "target-sub", "target-tenant"),
        (("Bearer", _access_token("other-caller"), {}), "other-sub", "other-tenant"),
    ]

    assert manager._current_assignee_object_id("target-sub") == "target-caller"
    assert manager._resolve_adu_principal("target-sub") == "adu-object-id"
    assert manager._current_assignee_object_id("other-sub") == "other-caller"
    # Caches remain subscription-scoped, not scoped to the hosting CLI login.
    assert manager._current_assignee_object_id("target-sub") == "target-caller"
    assert manager._resolve_adu_principal("target-sub") == "adu-object-id"

    assert [call.kwargs for call in token_profile.call_args_list] == [
        {"cli_ctx": cli_ctx}
    ] * 3
    assert [call.kwargs for call in raw_token.call_args_list] == [
        {"subscription": "target-sub", "resource": None},
        {"subscription": "target-sub", "resource": cloud.endpoints.microsoft_graph_resource_id},
        {"subscription": "other-sub", "resource": None},
    ]
    cli.invoke.assert_not_called()
    graph_get.assert_called_once()


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


def test_su_reports_graph_query_failure():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([{"id": "existing"}]),
        _result([{"id": "existing"}]),
        _result([{"id": "existing"}]),
    ]
    response = _graph_response([])
    response.raise_for_status.side_effect = requests.RequestException(
        "graph unavailable"
    )
    manager = LinkRbacManager(
        MagicMock(),
        cli=cli,
        graph_get=MagicMock(return_value=response),
    )

    with pytest.raises(AzureResponseError, match="query Microsoft Graph"):
        manager.ensure(
            "su", NS_SCOPE, TARGET_SCOPE, "ns-principal", "su-principal"
        )


def test_missing_current_assignee_stops_before_privilege_checks(token_profile):
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
    ]
    token_profile.return_value.get_raw_token.return_value = (
        ("Bearer", "not-a-jwt", {}), "sub", "tenant"
    )
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError, match="signed-in principal"):
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal"
        )


def test_rbac_creation_failure_lists_remaining_commands():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        RuntimeError("authorization changed"),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    with pytest.raises(AzureResponseError, match="before namespace mutation") as raised:
        manager.ensure(
            "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal"
        )
    assert "--assignee-object-id 'ns-principal'" in str(raised.value)


def test_rbac_creation_race_reuses_assignment_created_by_another_actor():
    cli = MagicMock()
    cli.invoke.side_effect = [
        _result([]),
        _result([]),
        _result([{"id": "owner"}]),
        _result([{"id": "owner"}]),
        RuntimeError("assignment already exists"),
        _result([{"id": "raced-assignment"}]),
        _result({"id": "created-second"}),
        _result([{"id": "visible-second"}]),
    ]
    manager = LinkRbacManager(MagicMock(), cli=cli)

    manager.ensure(
        "dps", NS_SCOPE, TARGET_SCOPE, "ns-principal", "dps-principal"
    )

    creates = [
        call.args[0]
        for call in cli.invoke.call_args_list
        if "role assignment create" in call.args[0]
    ]
    assert len(creates) == 2


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


def test_rbac_rejects_unknown_link_type_and_failed_cli_command():
    manager = LinkRbacManager(MagicMock(), cli=MagicMock())
    with pytest.raises(InvalidArgumentValueError, match="Unsupported"):
        manager.ensure("unknown", NS_SCOPE, TARGET_SCOPE, "ns", "target")

    manager.cli.invoke.return_value = _result({}, success=False)
    with pytest.raises(AzureResponseError, match="preflight"):
        manager._invoke_json("account show")
