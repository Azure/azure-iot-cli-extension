# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Role assignments: the permission probe and the grant itself."""

import pytest

from azext_iot.adr.ui.core import rbac
from azext_iot.adr.ui.core.rbac import GrantDenied, ROLE_WRITE_ACTION, permits


class FakeCLI:
    """Stands in for EmbeddedCLI: records the command, returns or raises what it is told."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.commands = []

    def invoke(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self

    def as_json(self):
        return self.payload


@pytest.fixture
def fake_cli(monkeypatch):
    holder = {}

    def install(payload=None, error=None):
        cli = FakeCLI(payload=payload, error=error)
        holder["cli"] = cli
        monkeypatch.setattr(rbac, "_embedded_cli", lambda _session: cli)
        return cli

    return install


# -- what the caller is allowed to do -------------------------------------------------


def test_an_owner_style_wildcard_permits_granting():
    assert permits([{"actions": ["*"], "notActions": []}])


def test_a_contributor_cannot_grant():
    """Contributor holds '*' but is denied role assignment writes, which is the point."""
    contributor = [{
        "actions": ["*"],
        "notActions": [
            "Microsoft.Authorization/*/Delete",
            "Microsoft.Authorization/*/Write",
            "Microsoft.Authorization/elevateAccess/Action",
        ],
    }]
    assert not permits(contributor)


def test_user_access_administrator_permits_granting():
    uaa = [{"actions": ["*/read", "Microsoft.Authorization/*"], "notActions": []}]
    assert permits(uaa)


def test_a_reader_cannot_grant():
    assert not permits([{"actions": ["*/read"], "notActions": []}])


def test_each_assignment_is_judged_on_its_own():
    """A separate Owner assignment is not cancelled by Contributor's notActions."""
    combined = [
        {"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write"]},
        {"actions": ["*"], "notActions": []},
    ]
    assert permits(combined)


def test_no_permissions_at_all_is_not_a_yes():
    assert not permits([])
    assert not permits(None)


def test_the_action_checked_is_the_one_arm_requires():
    assert ROLE_WRITE_ACTION == "Microsoft.Authorization/roleAssignments/write"


# -- the probe ------------------------------------------------------------------------


def test_probe_reports_yes_for_an_owner(fake_cli):
    fake_cli(payload={"value": [{"actions": ["*"], "notActions": []}]})
    assert rbac.can_grant_roles(object(), "/subscriptions/sub-1") is True


def test_probe_reports_no_for_a_contributor(fake_cli):
    fake_cli(payload={"value": [
        {"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write"]}
    ]})
    assert rbac.can_grant_roles(object(), "/subscriptions/sub-1") is False


def test_an_unanswerable_probe_returns_none_rather_than_guessing(fake_cli):
    """None is not False: the difference is what the review panel tells the customer."""
    fake_cli(error=RuntimeError("network is down"))
    assert rbac.can_grant_roles(object(), "/subscriptions/sub-1") is None


def test_probe_without_a_scope_asks_nothing():
    assert rbac.can_grant_roles(object(), "") is None


def test_probe_asks_arm_at_the_given_scope(fake_cli):
    cli = fake_cli(payload={"value": []})
    rbac.can_grant_roles(object(), "/subscriptions/sub-1")
    command = cli.commands[0]
    assert "/subscriptions/sub-1/providers/Microsoft.Authorization/permissions" in command
    assert "rest --method get" in command


def test_scope_probe_resolves_every_required_action(fake_cli):
    fake_cli(
        payload={
            "value": [
                {
                    "actions": [
                        "Microsoft.Authorization/roleAssignments/write",
                        "Microsoft.Devices/IotHubs/write",
                    ],
                    "notActions": [],
                }
            ]
        }
    )
    result = rbac.permissions_at_scope(
        object(),
        "/subscriptions/sub-1/resourceGroups/rg1",
        [
            "Microsoft.Authorization/roleAssignments/write",
            "Microsoft.Devices/IotHubs/write",
            "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
        ],
    )
    assert result == {
        "Microsoft.Authorization/roleAssignments/write": True,
        "Microsoft.Devices/IotHubs/write": True,
        "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action": False,
    }


# -- making the grant -----------------------------------------------------------------


def test_a_grant_is_addressed_by_object_id_and_principal_type(fake_cli):
    """A directory lookup by name fails for a managed identity, so neither is used."""
    cli = fake_cli(payload={})
    rbac.grant_role(object(), "pid-1", "Contributor", "/subscriptions/s/rg/hub")
    command = cli.commands[0]
    assert "--assignee-object-id pid-1" in command
    assert "--assignee-principal-type ServicePrincipal" in command
    assert "--role Contributor" in command
    assert "--scope /subscriptions/s/rg/hub" in command


def test_a_new_grant_reports_that_it_was_created(fake_cli):
    fake_cli(payload={})
    assert rbac.grant_role(object(), "pid-1", "Contributor", "/scope") is True


def test_an_existing_grant_is_not_a_failure(fake_cli):
    """Re-running guided setup must be safe; the assignment is already what we want."""
    fake_cli(error=RuntimeError("(RoleAssignmentExists) The role assignment already exists."))
    assert rbac.grant_role(object(), "pid-1", "Contributor", "/scope") is False


def test_a_refused_grant_is_reported_as_such(fake_cli):
    fake_cli(error=RuntimeError(
        "(AuthorizationFailed) The client does not have authorization to perform action "
        "'Microsoft.Authorization/roleAssignments/write'"
    ))
    with pytest.raises(GrantDenied) as caught:
        rbac.grant_role(object(), "pid-1", "Contributor", "/subscriptions/s/rg/hub-a")
    assert "Owner or User Access Administrator" in str(caught.value)


def test_an_unrelated_failure_is_not_swallowed(fake_cli):
    fake_cli(error=RuntimeError("(GatewayTimeout) try again"))
    with pytest.raises(RuntimeError, match="GatewayTimeout"):
        rbac.grant_role(object(), "pid-1", "Contributor", "/scope")


def test_a_grant_needs_both_a_principal_and_a_scope():
    with pytest.raises(ValueError):
        rbac.grant_role(object(), "", "Contributor", "/scope")
    with pytest.raises(ValueError):
        rbac.grant_role(object(), "pid-1", "Contributor", "")


def test_grant_arguments_are_shell_safe(fake_cli):
    cli = fake_cli(payload={})
    rbac.grant_role(
        object(),
        "$(touch /tmp/owned)",
        "Role `unsafe`",
        "/subscriptions/s/resourceGroups/rg with spaces",
    )
    command = cli.commands[0]
    assert "'$(touch /tmp/owned)'" in command
    assert "'Role `unsafe`'" in command
    assert "'/subscriptions/s/resourceGroups/rg with spaces'" in command


# -- reading an identity created moments ago ------------------------------------------


def test_a_principal_can_be_read_after_the_resource_exists(fake_cli):
    cli = fake_cli(payload="pid-new")
    assert rbac.resolve_principal(object(), "/subscriptions/s/rg/dps-a") == "pid-new"
    assert "--ids /subscriptions/s/rg/dps-a" in cli.commands[0]
    assert "properties.principalId" in cli.commands[0]


def test_a_resource_without_an_identity_resolves_to_nothing(fake_cli):
    fake_cli(payload=None)
    assert rbac.resolve_principal(object(), "/subscriptions/s/rg/dps-a") is None


def test_an_unreadable_resource_resolves_to_nothing(fake_cli):
    fake_cli(error=RuntimeError("not found"))
    assert rbac.resolve_principal(object(), "/subscriptions/s/rg/dps-a") is None


def test_rbac_is_free_of_ui_framework_imports():
    """Principle: core stays testable without a terminal."""
    import pathlib

    source = pathlib.Path("azext_iot/adr/ui/core/rbac.py").read_text(encoding="utf-8")
    assert "textual" not in source
