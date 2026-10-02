# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""One owned namespace: real radar reads and headless, read-only navigation."""

import asyncio
from dataclasses import replace
import os
import shlex
from types import SimpleNamespace

import pytest
from textual.widgets import DataTable

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.core.spec import Action, Registry
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.adr.ui.widgets.chrome import ContextBar, FlashLine
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper, CleanupLedger, wait_for_listed_resource
from azext_iot.tests.adr.conftest import TEST_LOCATION, TEST_RG, TEST_SUBSCRIPTION, generate_adr_namespace_name


def _skip_namespace_list():
    return os.getenv("azext_iot_adr_radar_skip_namespace_list", "").lower() in {"1", "true", "yes"}


async def _settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def _browse_readonly_namespace(session, namespace):
    """Use the real registry and providers; no TTY, dependency creation, or grant discovery."""
    scope = {
        "namespace_name": namespace["name"],
        "resource_group_name": session.scope.resource_group_name,
    }
    app = RadrApp(
        cmd=session.cmd, session=session, read_only=True, refresh_interval=900, **scope,
    )
    if _skip_namespace_list():
        # Opt-in isolation for the known service continuation failure. Only the
        # namespace picker uses a scoped GET; all child collections remain real.
        def list_owned_namespace(target_scope):
            assert target_scope["namespace_name"] == namespace["name"]
            assert target_scope["resource_group_name"] == scope["resource_group_name"]
            return [session.call(session.provider("namespace").show, **scope)]

        registry = Registry()
        for spec in app.registry.all():
            registry.register(replace(spec, list=list_owned_namespace) if spec.kind == "namespace" else spec)
        app.registry = registry

    async with app.run_test(size=(140, 42)) as pilot:
        try:
            await _settle(app, pilot)
            root = app.screen
            assert isinstance(root, BrowseScreen) and root.spec.kind == "namespace"
            assert not root.model.error
            names = [row.id for row in root.model.rows]
            assert namespace["name"] in names
            root.query_one("#rows", DataTable).move_cursor(row=names.index(namespace["name"]))
            await pilot.press("enter")
            await _settle(app, pilot)
            overview = app.screen
            assert isinstance(overview, OverviewScreen)
            assert overview.scope["namespace_name"] == namespace["name"]
            bar = overview.query_one(ContextBar)
            assert namespace["name"] in bar.text and scope["resource_group_name"] in bar.text
            table = overview.query_one("#resource-map", DataTable)
            assert table.row_count == 4
            assert [table.get_row_at(index)[1].plain for index in range(4)] == ["0"] * 4
            for key, kind in (("l", "link"), ("g", "group"), ("j", "job"), ("c", "ca")):
                await pilot.press(key)
                await _settle(app, pilot)
                assert isinstance(app.screen, BrowseScreen) and app.screen.spec.kind == kind
                assert app.screen.scope["namespace_name"] == namespace["name"]
                assert app.screen.model.total_count == 0 and not app.screen.model.error
                await pilot.press("escape")
                await _settle(app, pilot)
                assert app.screen is overview

            # Exercise the generic mutation gate with a real provider operation. Even
            # a regression only opens an unapproved preview, never accepts a mutation.
            action = Action(
                "update", "Update namespace",
                invoke=lambda live, target_scope, _payload: live.call(
                    live.provider("namespace").update, **target_scope, tags={"radar-smoke": "unexpected"}, no_wait=True,
                ),
            )
            app.perform_action(root.spec, action, namespace, scope)
            assert app.screen is overview
            assert "state-changing actions are disabled" in overview.query_one(FlashLine).text

            # Render the live namespace snapshot without admitting a subscription or
            # catalog into setup. This exercises Apply without enumerating Hub/DPS/SU
            # candidates or opening an Azure RBAC permission/grant probe.
            onboard = OnboardScreen(session, scope, namespace=namespace)
            await app.push_screen(onboard)
            await _settle(app, pilot)
            await pilot.press("a")
            await pilot.pause()
            assert app.screen is onboard
            assert "read-only session: apply is disabled" in onboard.query_one(FlashLine).text
            assert not app.tracker.operations
            await pilot.press("escape")
            await _settle(app, pilot)
            assert app.screen is overview
        finally:
            # Join the HTTP-reading workers before run_test shuts down its timers and
            # before the caller can delete the owned namespace.
            await app.workers.wait_for_complete()
    assert not list(app.workers)


@pytest.mark.usefixtures("set_cwd")
class TestADRRadar(ADRFullInfraHelper, ADRLiveScenarioTest):
    def test_radar_readonly_namespace_smoke(self):
        namespace_name = generate_adr_namespace_name()
        assert self.cmd("account show").get_output_in_json()["id"].casefold() == TEST_SUBSCRIPTION.casefold()
        args = f"-n {shlex.quote(namespace_name)} -g {shlex.quote(TEST_RG)}"
        with CleanupLedger() as cleanup:
            # The helper refuses collisions and records ownership BEFORE the create
            # call, so a post-accept timeout still cleans up only our attempted name.
            cleanup.register("radar namespace", self.cleanup_full_infra)
            self.create_owned_resource(
                f"iot adr ns create {args} --location {shlex.quote(TEST_LOCATION)} --no-wait",
                kind="namespace", name=namespace_name, resource_group=TEST_RG,
            )
            self.cmd(f"iot adr ns wait {args} --timeout 120 --interval 5")
            if not _skip_namespace_list():
                wait_for_listed_resource(self, f"iot adr ns list -g {shlex.quote(TEST_RG)}", namespace_name)
            session = Session(
                SimpleNamespace(cli_ctx=self.cli_ctx), resource_group_name=TEST_RG,
                namespace_name=namespace_name, read_only=True,
            )
            assert session.resolve_subscription().casefold() == TEST_SUBSCRIPTION.casefold()
            namespace = session.call(
                session.provider("namespace").show, namespace_name=namespace_name, resource_group_name=TEST_RG,
            )
            assert namespace["name"] == namespace_name
            assert namespace["properties"]["provisioningState"] == "Succeeded"
            assert namespace["location"].casefold() == TEST_LOCATION.casefold()
            asyncio.run(_browse_readonly_namespace(session, namespace))
