# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""One owned namespace: real radar reads and headless, read-only navigation."""

import asyncio
from dataclasses import replace
import json
import os
import shlex
from types import SimpleNamespace

import pytest
from textual.widgets import DataTable, Input

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.core.spec import Action, Registry
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.widgets.actions import ActionForm, ReviewDialog
from azext_iot.adr.ui.widgets.chrome import FlashLine
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper, CleanupLedger, resource_is_absent, wait_for_listed_resource, wait_for_resource_absent,
)
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
            names = [row.payload["name"] for row in root.model.rows]
            assert namespace["name"] in names
            root.query_one("#rows", DataTable).move_cursor(row=names.index(namespace["name"]))
            await pilot.press("enter")
            await _settle(app, pilot)
            overview = app.screen
            assert isinstance(overview, DetailScreen)
            assert overview.scope["namespace_name"] == namespace["name"]
            assert not overview.query(DataTable)
            for key, kind in (("l", "link"), ("d", "device"), ("g", "group"), ("j", "job"), ("c", "ca")):
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
            assert "writes are disabled" in overview.query_one(FlashLine).text
            assert not app.tracker.operations
        finally:
            # Join the HTTP-reading workers before run_test shuts down its timers and
            # before the caller can delete the owned namespace.
            await app.workers.wait_for_complete()
    assert not list(app.workers)


async def _reviewed_action(app, pilot, spec, name, payload, values=None):
    app.perform_action(spec, spec.action(name), payload, app.scope)
    await pilot.pause()
    if values is not None:
        assert isinstance(app.screen, ActionForm)
        for key, value in values.items():
            app.screen.query_one(f"#field-{key}", Input).value = value
        await pilot.click("#review")
        await pilot.pause()
    assert isinstance(app.screen, ReviewDialog)
    if app.screen.action.destructive:
        app.screen.query_one("#confirm-name", Input).value = app.screen.target_name
        await pilot.pause()
    await pilot.click("#confirm")
    await _settle(app, pilot)
    operation = app.tracker.operations[0]
    assert operation.state.value == "succeeded", operation.describe()


@pytest.mark.usefixtures("set_cwd")
class TestADRRadar(ADRFullInfraHelper, ADRLiveScenarioTest):
    def test_radar_device_crud_and_tag_preservation(self):
        namespace = generate_adr_namespace_name()
        args = f"-n {namespace} -g {TEST_RG}"
        device_args = f"-n radar-device --ns {namespace} -g {TEST_RG}"
        device_show = f"iot adr ns device show {device_args}"

        def remove_device():
            if ("namespace", namespace, TEST_RG) not in getattr(self, "_owned_resources", {}):
                return
            if not resource_is_absent(self, device_show):
                self.cmd(f"iot adr ns device delete {device_args} --yes")
                wait_for_resource_absent(self, device_show)

        with CleanupLedger() as cleanup:
            cleanup.register("namespace", self.cleanup_full_infra, depends_on=("device",))
            cleanup.register("device", remove_device)
            self.create_owned_resource(
                f"iot adr ns create {args} -l {TEST_LOCATION} --tags keep=original",
                kind="namespace", name=namespace, resource_group=TEST_RG,
            )
            assert resource_is_absent(self, device_show)
            session = Session(SimpleNamespace(cli_ctx=self.cli_ctx), TEST_RG, namespace)
            assert session.resolve_subscription().casefold() == TEST_SUBSCRIPTION.casefold()

            async def scenario():
                app = RadrApp(session=session, resource_group_name=TEST_RG, namespace_name=namespace,
                              refresh_interval=900)
                async with app.run_test(size=(110, 36)) as pilot:
                    try:
                        await _settle(app, pilot)
                        device_spec = app.registry.get("device")
                        await _reviewed_action(app, pilot, device_spec, "create", {}, {"name": "radar-device"})
                        created = self.cmd(device_show).get_output_in_json()
                        current = created["properties"].get("enablementState")
                        desired = "Disabled" if current == "Enabled" else "Enabled"
                        await _reviewed_action(
                            app, pilot, device_spec, "update", created, {"enablement_state": desired},
                        )
                        updated = self.cmd(device_show).get_output_in_json()
                        assert updated["properties"]["enablementState"] == desired
                        await _reviewed_action(app, pilot, device_spec, "delete", updated)
                        assert resource_is_absent(self, device_show)
                        existing = self.cmd(f"iot adr ns show {args}").get_output_in_json()
                        assert existing["tags"] == {"keep": "original"}
                        await _reviewed_action(
                            app, pilot, app.registry.get("namespace"), "update", existing,
                            {"tags": json.dumps({"keep": "original", "added": "radar"})},
                        )
                        assert self.cmd(f"iot adr ns show {args}").get_output_in_json()["tags"] == {
                            "keep": "original", "added": "radar",
                        }
                    finally:
                        await app.workers.wait_for_complete()
            asyncio.run(scenario())

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
