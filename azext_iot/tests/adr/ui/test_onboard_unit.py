# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Guided onboarding: step graph, pickers and plan (steps 11-12)."""

import time

from azext_iot.adr.ui.screens.onboard.flow import Flow, PlanItem, Step, StepState
from azext_iot.adr.ui.screens.onboard.pickers import (
    ELIGIBLE,
    INELIGIBLE,
    WARNING,
    Candidate,
    evaluate,
    rank,
)
from azext_iot.adr.ui.screens.onboard.steps import build_flow
from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice,
    USER_ASSIGNED,
    attach_identity,
    set_choice,
    system_choice,
)


def namespace_payload(
    identity=None,
    provisioning=None,
    messaging=None,
    location="eastus2",
    outbound=True,
):
    properties = {}
    if identity and outbound:
        properties["outboundIdentity"] = {"type": identity}
    if provisioning is not None:
        properties["provisioning"] = {"endpoints": provisioning}
    if messaging is not None:
        properties["messaging"] = {"endpoints": messaging}
    return {
        "name": "ns1",
        "location": location,
        "properties": properties,
        "identity": {"type": identity} if identity else {},
    }


def context(namespace=None, **extra):
    # A live session always resolves a subscription, so the default context has one.
    base = {
        "subscription_id": "sub-1",
        "resource_group_name": "rg1",
        "namespace_name": "ns1",
        "namespace": namespace or {},
    }
    base.update(extra)
    return base


def all_states(flow):
    """State of every step, including the ones the rail hides.

    Visible steps come from ``states()`` so the current one is marked; hidden steps are
    resolved directly, since they never appear on the rail.
    """
    resolved = {step.id: state for step, state in flow.states()}
    for step in flow.steps:
        resolved.setdefault(step.id, flow.state_of(step))
    return resolved


def dps_candidate(name="dps-1"):
    return Candidate(name=name, resource_id=f"/subscriptions/s/rg/providers/dps/{name}")


def hub_candidate(name="hub-1"):
    return Candidate(name=name, resource_id=f"/subscriptions/s/rg/providers/hubs/{name}")


# -- the ordering rules the service enforces -----------------------------------------


def test_nothing_is_satisfied_for_a_bare_namespace():
    flow = build_flow(context())
    states = all_states(flow)
    assert states["namespace"] is StepState.CURRENT
    # Later steps are sequential, not blocked: the plan will create the namespace first.
    assert states["identity"] is StepState.PENDING
    # The DPS-first rule still holds, because no provisioning service is selected.
    assert states["hub"] is StepState.BLOCKED


def test_messaging_is_blocked_until_a_provisioning_endpoint_exists():
    """The service rejects a hub before a DPS; the interface must show that, not fail later."""
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    states = all_states(flow)
    assert states["dps"] is StepState.CURRENT
    assert states["hub"] is StepState.BLOCKED


def test_messaging_unblocks_once_provisioning_is_linked():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned", provisioning={"dps": {}}))
    )
    states = all_states(flow)
    assert states["dps"] is StepState.SATISFIED
    assert states["hub"] is StepState.CURRENT


def test_identity_is_planned_but_never_shown_as_a_decision():
    """It is automatic, so it belongs in the plan and not on the rail."""
    flow = build_flow(context(namespace_payload()))
    assert "identity" not in {step.id for step in flow.visible_steps()}
    assert all_states(flow)["identity"] is StepState.PENDING
    # Ordering that matters is among the operations that will actually run; blocked
    # placeholders are informational and sort with the context block.
    runnable = [item.key for item in flow.build_plan() if item.is_actionable]
    assert "identity" in runnable


def test_hub_is_blocked_until_a_provisioning_service_is_selected():
    """The one rule that must be enforced up front: a hub is meaningless without a DPS."""
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    blocked = all_states(flow)["hub"]
    assert blocked is StepState.BLOCKED

    chosen = build_flow(context(namespace_payload(identity="SystemAssigned"),
                                selected_dps=dps_candidate()))
    unblocked = all_states(chosen)["hub"]
    assert unblocked is not StepState.BLOCKED, "selecting a DPS unblocks planning the hub"


def test_blocked_step_explains_why():
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    hub = next(step for step in flow.steps if step.id == "hub")
    assert "Choose a DPS first" in hub.blocked_reason
    assert [blocked.id for blocked in flow.blocking(hub)] == ["dps"]


def test_a_fully_linked_namespace_has_only_optional_work_left():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned",
                                  provisioning={"dps": {}}, messaging={"hub": {}}))
    )
    states = all_states(flow)
    for required in ("namespace", "identity", "dps", "hub"):
        assert states[required] is StepState.SATISFIED
    # Only optional work is left: Software Updates, and the review step itself.
    assert flow.current().id in ("su", "review")


def test_progress_counts_required_steps_only():
    """Software Updates is optional and must not count against completion."""
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    done, total = flow.progress()
    required = [s for s in flow.visible_steps() if not s.optional]
    assert total == len(required)
    # subscription, resource group and namespace are satisfied here.
    assert done == 3


# -- resumability --------------------------------------------------------------------


def test_satisfied_steps_are_skipped_on_re_entry():
    """Re-entering a partly configured namespace resumes rather than restarting."""
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned", provisioning={"dps": {}}))
    )
    satisfied = {step.id for step in flow.satisfied()}
    assert {"scope", "namespace", "identity", "dps"} <= satisfied


def test_detection_reads_live_state_not_selections():
    """A selection must not make a step look done; only service state counts."""
    flow = build_flow(context(namespace_payload(identity="SystemAssigned"),
                              selected_dps=dps_candidate()))
    states = all_states(flow)
    assert states["dps"] is StepState.CURRENT, "selecting is not linking"


# -- plan ----------------------------------------------------------------------------


def test_plan_marks_existing_configuration_as_exists():
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    plan = {item.key: item for item in flow.build_plan()}
    assert plan["namespace"].action == "exists"
    assert plan["identity"].action == "exists"


def test_plan_includes_the_link_command_for_a_selected_service():
    flow = build_flow(context(namespace_payload(identity="SystemAssigned"),
                              selected_dps=dps_candidate()))
    plan = {item.key: item for item in flow.build_plan()}
    assert plan["dps"].action == "create"
    assert "az iot adr ns link dps add" in plan["dps"].command
    assert "--dps-id" in plan["dps"].command


def test_plan_shows_blocked_items_with_a_reason():
    flow = build_flow(context(namespace_payload(identity="SystemAssigned")))
    plan = {item.key: item for item in flow.build_plan()}
    assert plan["hub"].action == "blocked"
    assert plan["hub"].blocked_reason


def test_hub_link_depends_on_the_provisioning_link():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned"),
                selected_dps=dps_candidate(), selected_hubs=[hub_candidate()])
    )
    plan = {item.key: item for item in flow.build_plan()}
    assert "dps" in plan["hub-0"].depends_on, "ordering is encoded in the plan, not assumed"


def identified(candidate, principal="pid-target"):
    candidate.raw = {"identity": {"type": "SystemAssigned", "principalId": principal}}
    return candidate


def namespace_with_principal(principal="pid-ns", **kwargs):
    payload = namespace_payload(identity="SystemAssigned", **kwargs)
    payload["identity"]["principalId"] = principal
    return payload


def test_grant_commands_are_runnable_not_placeholders():
    """The customer must be able to paste these; a placeholder makes the plan useless."""
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()), subscription_id="sub-1")
    )
    grants = [item for item in flow.build_plan() if item.key.startswith("grant-ns-to")]
    assert grants
    for item in grants:
        assert "<" not in item.command, f"unresolved placeholder in: {item.command}"
        assert "--assignee-object-id pid-ns" in item.command
        assert "--assignee-principal-type ServicePrincipal" in item.command


def test_reverse_grant_uses_the_targets_own_principal():
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate(), principal="pid-dps"),
                subscription_id="sub-1")
    )
    reverse = next(item for item in flow.build_plan() if item.key.startswith("grant-dps-to-ns"))
    assert "--assignee-object-id pid-dps" in reverse.command
    assert "/providers/Microsoft.DeviceRegistry/namespaces/ns1" in reverse.command


def test_missing_namespace_principal_is_resolved_after_identity_setup():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned", provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()))
    )
    forward = next(item for item in flow.build_plan() if item.key.startswith("grant-ns-to"))
    assert forward.action == "manual"
    assert "az resource show" in forward.command


def test_target_without_identity_is_enabled_before_the_reverse_grant():
    candidate = dps_candidate()
    candidate.raw = {"identity": {}}
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}), selected_dps=candidate)
    )
    reverse = next(item for item in flow.build_plan() if item.key.startswith("grant-dps-to-ns"))
    assert reverse.action == "manual"
    assert "az resource show" in reverse.command


def test_plan_includes_a_propagation_wait():
    """Linking immediately after granting fails in a way that looks like a backend bug."""
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()))
    )
    wait = next(item for item in flow.build_plan() if item.key == "grant-propagation")
    assert "propagation" in wait.description


def test_permissions_plan_covers_both_directions():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned", provisioning={"dps": {}}),
                selected_dps=dps_candidate(), selected_hubs=[hub_candidate()],
                subscription_id="sub-1")
    )
    commands = [item.description for item in flow.build_plan() if item.key.startswith("grant-")]
    assert any("namespace identity" in text for text in commands)
    assert any("identity 'Contributor' on the namespace" in text for text in commands)


def test_hub_grants_include_the_data_role():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned", provisioning={"dps": {}}),
                selected_hubs=[hub_candidate()])
    )
    roles = " ".join(item.description for item in flow.build_plan())
    assert "IoT Hub Data Contributor" in roles


def test_grants_stay_manual_when_the_account_may_not_make_them():
    """Without the right, radr reports the grants rather than failing halfway through."""
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()), can_grant_roles=False)
    )
    grants = [item for item in flow.build_plan() if item.key.startswith("grant-")]
    assert grants
    assert all(item.action == "manual" for item in grants)
    assert all(item.invoke is None for item in grants)


def test_an_unanswered_permission_probe_is_treated_as_no():
    """Promising a grant radr cannot make would fail the run at the worst moment."""
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()), can_grant_roles=None)
    )
    grants = [item for item in flow.build_plan() if item.key.startswith("grant-")]
    assert grants and all(item.invoke is None for item in grants)


def test_grants_are_applied_when_the_account_is_allowed_to_make_them():
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()), can_grant_roles=True)
    )
    grants = [item for item in flow.build_plan() if item.key.startswith("grant-ns-to")]
    assert grants
    assert all(item.action == "create" for item in grants)
    assert all(item.invoke is not None for item in grants), "radr should do this itself"


def test_grants_run_before_the_links_that_need_them():
    flow = build_flow(
        context(namespace_with_principal(), selected_dps=identified(dps_candidate()),
                selected_hubs=[identified(hub_candidate())], can_grant_roles=True)
    )
    plan = [item for item in flow.build_plan() if item.invoke is not None]
    keys = [item.key for item in plan]
    last_grant = max(i for i, k in enumerate(keys) if k.startswith("grant-"))
    first_link = min(i for i, k in enumerate(keys) if k in ("dps", "hub-0"))
    assert last_grant < first_link


def test_script_is_runnable_and_annotates_what_is_skipped():
    flow = build_flow(
        context(namespace_payload(identity="SystemAssigned"), selected_dps=dps_candidate())
    )
    script = flow.script()
    assert script.startswith("#!/usr/bin/env bash")
    assert "az iot adr ns link dps add" in script
    assert "# Namespace - already configured" in script


def test_plan_never_mutates():
    """Building a plan must not touch the service; only apply may."""
    called = []
    step = Step(id="s", title="S", plan=lambda ctx: [
        PlanItem(key="s", description="do", invoke=lambda *a: called.append(1))
    ])
    Flow(steps=[step], context={}).build_plan()
    assert not called


# -- pickers -------------------------------------------------------------------------


def test_resource_without_identity_is_selectable_for_identity_setup():
    candidate = evaluate({"name": "dps-old", "id": "/x/dps-old", "location": "eastus2"})
    assert candidate.verdict == WARNING
    assert candidate.reason == "identity setup required"
    assert candidate.selectable


def test_region_mismatch_is_a_warning_not_a_block():
    candidate = evaluate(
        {"name": "dps-west", "id": "/x/dps-west", "location": "westus2",
         "identity": {"type": "SystemAssigned"}},
        namespace_location="eastus2",
    )
    assert candidate.verdict == WARNING
    assert candidate.selectable, "a warning must not prevent selection"


def test_failed_resource_is_blocked_from_linking():
    candidate = evaluate({
        "name": "broken-hub",
        "id": "/x/broken-hub",
        "identity": {"type": "SystemAssigned"},
        "properties": {"provisioningState": "Failed"},
    })
    assert candidate.verdict == INELIGIBLE
    assert candidate.reason == "provisioning failed"
    assert candidate.describe() == "blocked  provisioning failed"


def test_readiness_uses_customer_facing_labels():
    assert Candidate("a", "a", verdict=ELIGIBLE).describe() == "ready"
    assert Candidate("b", "b", verdict=WARNING).describe() == "check"
    assert Candidate("c", "c", verdict=INELIGIBLE).describe() == "blocked"


def test_readiness_messages_are_compact_and_unpunctuated():
    candidates = [
        evaluate({
            "name": "failed",
            "id": "failed",
            "identity": {"type": "SystemAssigned"},
            "properties": {"provisioningState": "Failed"},
        }),
        evaluate({"name": "missing", "id": "missing"}),
        evaluate(
            {"name": "hub", "id": "hub", "location": "westus2",
             "identity": {"type": "SystemAssigned"}},
            namespace_location="eastus2",
            registered_hub_names=[],
        ),
    ]
    assert [candidate.reason for candidate in candidates] == [
        "provisioning failed",
        "identity setup required",
        "other region + not in DPS",
    ]
    assert all(";" not in candidate.describe() for candidate in candidates)
    assert all(len(candidate.describe()) <= 32 for candidate in candidates)


def test_hub_registered_on_the_service_is_recommended():
    candidate = evaluate(
        {"name": "hub-a", "id": "/x/hub-a", "location": "eastus2",
         "identity": {"type": "SystemAssigned"}},
        namespace_location="eastus2",
        registered_hub_names=["hub-a.azure-devices.net"],
    )
    assert candidate.recommended and candidate.verdict == ELIGIBLE


def test_unregistered_hub_warns_about_silent_allocation_failure():
    candidate = evaluate(
        {"name": "hub-b", "id": "/x/hub-b", "location": "eastus2",
         "identity": {"type": "SystemAssigned"}},
        namespace_location="eastus2",
        registered_hub_names=["hub-a.azure-devices.net"],
    )
    assert candidate.verdict == WARNING
    assert candidate.reason == "not in DPS"


def test_link_readiness_reports_multiple_warnings_together():
    candidate = evaluate(
        {"name": "hub-b", "id": "/x/hub-b", "location": "westus2",
         "identity": {"type": "SystemAssigned"}},
        namespace_location="eastus2",
        registered_hub_names=["hub-a.azure-devices.net"],
    )
    assert candidate.verdict == WARNING
    assert candidate.reason == "other region + not in DPS"


def test_resource_group_is_parsed_from_the_id():
    candidate = evaluate(
        {"name": "dps", "id": "/subscriptions/s/resourceGroups/my-rg/providers/x/dps",
         "identity": {"type": "SystemAssigned"}}
    )
    assert candidate.resource_group == "my-rg"


def test_ranking_puts_recommended_first_and_ineligible_last():
    items = [
        Candidate(name="c", resource_id="c", verdict=INELIGIBLE),
        Candidate(name="b", resource_id="b", verdict=WARNING),
        Candidate(name="a", resource_id="a", verdict=ELIGIBLE),
        Candidate(name="r", resource_id="r", verdict=ELIGIBLE, recommended=True),
    ]
    assert [candidate.name for candidate in rank(items)] == ["r", "a", "b", "c"]


def test_ineligible_candidates_are_still_listed():
    """Hiding a resource makes a customer think the product is broken."""
    items = [Candidate(name="x", resource_id="x", verdict=INELIGIBLE)]
    assert len(rank(items)) == 1


def test_step_states_are_hidden_until_live_state_is_read():
    """Showing steps before reading the namespace would claim an existing one needs creating."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"namespace_name": "ns1",
                                                "resource_group_name": "rg1"})
    assert screen._state_loaded is False

    loaded = OnboardScreen(session=None, scope={"namespace_name": "ns1"},
                           namespace=namespace_payload(identity="SystemAssigned"))
    assert loaded._state_loaded is True


def test_registered_hub_names_are_read_from_the_service_record():
    """DPS records hub host names; the picker must compare on the same form."""
    from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog

    catalog = ResourceCatalog(cmd=None)
    dps = {"properties": {"iotHubs": [{"name": "hub-a.azure-devices.net"}, {"name": "hub-b"}]}}
    assert catalog.registered_hub_names(dps) == ["hub-a.azure-devices.net", "hub-b"]
    assert catalog.registered_hub_names({}) == []


def test_host_name_registration_matches_a_bare_hub_name():
    candidate = evaluate(
        {"name": "hub-a", "id": "/x/hub-a", "identity": {"type": "SystemAssigned"}},
        registered_hub_names=["hub-a.azure-devices.net"],
    )
    assert candidate.recommended, "a host-name record must match the hub resource name"


def test_catalog_records_why_an_enumeration_failed():
    """'None exist' and 'none visible to you' need different customer actions."""
    from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog

    catalog = ResourceCatalog(cmd=None)

    def broken():
        raise RuntimeError("AuthorizationFailed")

    assert catalog._listed("dps", broken) == []
    assert "AuthorizationFailed" in catalog.errors["dps"]


def test_namespace_catalog_errors_use_the_scoped_key():
    from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog

    catalog = ResourceCatalog(cmd=None)
    key = catalog.namespace_key("rg-one")
    catalog.errors[key] = "AuthorizationFailed"
    assert catalog.error_for("namespace", "rg-one") == "AuthorizationFailed"
    assert catalog.error_for("namespace", "rg-two") is None


def test_catalog_discards_results_started_before_clear():
    import threading

    from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog

    catalog = ResourceCatalog(cmd=None)
    started = threading.Event()
    release = threading.Event()
    result = []

    def slow_loader():
        started.set()
        release.wait(timeout=2)
        return [{"name": "old-subscription"}]

    worker = threading.Thread(
        target=lambda: result.extend(catalog._listed("hub", slow_loader))
    )
    worker.start()
    assert started.wait(timeout=2)
    catalog.clear()
    release.set()
    worker.join(timeout=2)

    assert result == []
    assert catalog._cache == {}
    assert catalog.errors == {}


def test_newer_same_key_catalog_load_wins():
    import threading

    from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog

    catalog = ResourceCatalog(cmd=None)
    old_started = threading.Event()
    release_old = threading.Event()
    old_result = []
    new_result = []

    def old_loader():
        old_started.set()
        release_old.wait(timeout=2)
        raise RuntimeError("old failure")

    old_worker = threading.Thread(
        target=lambda: old_result.extend(catalog._listed("hub", old_loader))
    )
    old_worker.start()
    assert old_started.wait(timeout=2)

    new_worker = threading.Thread(
        target=lambda: new_result.extend(
            catalog._listed("hub", lambda: [{"name": "current"}])
        )
    )
    new_worker.start()
    new_worker.join(timeout=2)
    release_old.set()
    old_worker.join(timeout=2)

    assert old_result == []
    assert new_result == [{"name": "current"}]
    assert catalog._cache["hub"] == [{"name": "current"}]
    assert "hub" not in catalog.errors


def test_candidate_keeps_the_payload_it_was_judged_from():
    resource = {"name": "dps", "id": "/x/dps", "identity": {"type": "SystemAssigned"}}
    assert evaluate(resource).raw is resource


def test_arm_none_identity_is_treated_as_missing():
    """ARM renders an absent identity as the string 'None', not an empty value."""
    for shape in ({"type": "None"}, {"type": "none"}, {"type": ""}, {}):
        candidate = evaluate({"name": "dps", "id": "/x/dps", "identity": shape})
        assert candidate.verdict == WARNING, f"identity {shape} must require setup"


def test_real_identity_shapes_remain_eligible():
    for shape in ("SystemAssigned", "UserAssigned", "SystemAssigned, UserAssigned"):
        candidate = evaluate({"name": "dps", "id": "/x/dps", "identity": {"type": shape}})
        assert candidate.verdict == ELIGIBLE


def test_grants_are_ordered_before_the_links_that_need_them():
    """Linking before the grant propagates fails with an authorization error."""
    flow = build_flow(
        context(namespace_with_principal(), selected_dps=identified(dps_candidate()),
                selected_hubs=[identified(hub_candidate())], subscription_id="sub-1")
    )
    keys = [item.key for item in flow.build_plan()]
    first_grant = min(i for i, key in enumerate(keys) if key.startswith("grant-ns-to"))
    link_dps = keys.index("dps")
    assert first_grant < link_dps, "grants must precede the link"
    assert keys.index("grant-propagation") < link_dps, "and the wait must precede it too"


def test_prerequisites_come_before_grants():
    flow = build_flow(
        context({}, namespace_name="new-ns", selected_dps=identified(dps_candidate()))
    )
    keys = [item.key for item in flow.build_plan()]
    assert keys.index("namespace") < keys.index("dps")


def test_script_states_existing_context_before_changes():
    flow = build_flow(
        context(namespace_with_principal(), selected_dps=identified(dps_candidate()),
                subscription_id="sub-1")
    )
    script = flow.script()
    assert script.index("already configured") < script.index("az role assignment create")


# -- apply --------------------------------------------------------------------------


def test_identity_and_link_steps_are_executable():
    """The wizard must be able to do the work, not only describe it."""
    flow = build_flow(
        context(namespace_payload(), namespace_name="ns1",
                selected_dps=identified(dps_candidate()),
                selected_hubs=[identified(hub_candidate())])
    )
    plan = {item.key: item for item in flow.build_plan()}
    assert plan["identity"].invoke is not None
    assert plan["dps"].invoke is not None
    assert plan["hub-0"].invoke is not None


def test_propagation_wait_is_skipped_when_nothing_was_newly_granted():
    """Re-running setup should not idle for a minute over long-settled assignments."""
    flow = build_flow(
        context(namespace_with_principal(provisioning={"dps": {}}),
                selected_dps=identified(dps_candidate()), can_grant_roles=True)
    )
    wait = next(item for item in flow.build_plan() if item.key == "grant-propagation")
    assert wait.invoke is not None
    started = time.monotonic()
    wait.invoke(None, {})
    assert time.monotonic() - started < 1, "no grant was created, so there is nothing to wait for"


def test_identity_step_calls_the_provider_with_no_wait():
    """PR1: the tray drives the poller, so the provider must not block on it."""
    calls = {}

    class FakeSession:
        def provider(self, name):
            calls["provider"] = name
            return self

        def update(self, **kwargs):
            calls.update(kwargs)
            return "poller"

        def call(self, func, **kwargs):
            return func(**kwargs)

    flow = build_flow(context(namespace_payload(), namespace_name="ns1",
                              resource_group_name="rg1"))
    identity = next(item for item in flow.build_plan() if item.key == "identity")
    assert identity.invoke(FakeSession(), flow.context) == "poller"
    assert calls["provider"] == "namespace"
    assert calls["outbound_mi_system_assigned"] is True
    assert calls["no_wait"] is True
    assert calls["namespace_name"] == "ns1"


def test_existing_namespace_without_outbound_identity_plans_update():
    flow = build_flow(
        context(
            namespace_payload(identity="SystemAssigned", outbound=False),
            namespace_name="ns1",
            resource_group_name="rg1",
        )
    )
    identity = next(item for item in flow.build_plan() if item.key == "identity")
    assert identity.action == "create"
    assert "ns update" in identity.command
    assert "--outbound-mi-system-assigned" in identity.command


def test_existing_namespace_uami_is_preserved_by_default():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    uami_id = (
        "/subscriptions/sub-1/resourceGroups/rg1/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/existing"
    )
    namespace = namespace_payload(identity="SystemAssigned")
    namespace["properties"]["outboundIdentity"] = {
        "type": "UserAssigned",
        "userAssignedIdentity": uami_id,
    }
    namespace["identity"]["userAssignedIdentities"] = {
        uami_id: {"principalId": "pid-uami"}
    }
    screen = OnboardScreen(
        session=None,
        scope={
            "subscription_id": "sub-1",
            "resource_group_name": "rg1",
            "namespace_name": "ns1",
        },
        namespace=namespace,
    )
    choice = screen.context["identity_choices"]["namespace"]
    assert choice.is_user_assigned
    assert choice.uami_id == uami_id
    assert next(
        item for item in screen.flow.build_plan() if item.key == "identity"
    ).action == "exists"


def test_permission_requirements_use_exact_role_scopes():
    from azext_iot.adr.ui.core.rbac import ROLE_WRITE_ACTION
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    dps = dps_candidate()
    dps.resource_group = "rg-dps"
    dps.resource_id = (
        "/subscriptions/sub-1/resourceGroups/rg-dps/providers/"
        "Microsoft.Devices/provisioningServices/dps-1"
    )
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg-identities/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/shared"
        ),
        uami_name="shared",
    )
    screen = OnboardScreen(
        session=None,
        scope={
            "subscription_id": "sub-1",
            "resource_group_name": "rg1",
            "namespace_name": "ns1",
        },
        namespace=namespace_payload(identity="SystemAssigned"),
    )
    screen.context["selected_dps"] = dps
    set_choice(screen.context, "dps", choice, dps.resource_id)
    requirements = screen._permission_requirements()
    assert ROLE_WRITE_ACTION in requirements[dps.resource_id]
    assert ROLE_WRITE_ACTION not in requirements[choice.uami_id]


def test_ready_target_only_requires_role_assignment_access():
    from azext_iot.adr.ui.core.rbac import ROLE_WRITE_ACTION
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    dps = dps_candidate()
    dps.resource_group = "rg-dps"
    dps.resource_id = (
        "/subscriptions/sub-1/resourceGroups/rg-dps/providers/"
        "Microsoft.Devices/provisioningServices/dps-1"
    )
    dps.raw = {
        "id": dps.resource_id,
        "name": dps.name,
        "identity": {"type": "SystemAssigned", "principalId": "pid-dps"},
    }
    screen = OnboardScreen(
        session=None,
        scope={
            "subscription_id": "sub-1",
            "resource_group_name": "rg1",
            "namespace_name": "ns1",
        },
        namespace=namespace_payload(identity="SystemAssigned"),
    )
    screen.context["selected_dps"] = dps
    requirements = screen._permission_requirements()
    assert requirements[dps.resource_id] == {ROLE_WRITE_ACTION}


def test_new_resource_group_checks_subscription_create_permission():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(
        session=None,
        scope={"subscription_id": "sub-1"},
    )
    request = create_request("resource_group", "new-rg", rg="new-rg")
    screen.context["create_resource_group"] = request
    screen.context["resource_group_name"] = request.name
    requirements = screen._permission_requirements()
    assert (
        "Microsoft.Resources/subscriptions/resourceGroups/write"
        in requirements["/subscriptions/sub-1"]
    )


def test_new_uami_permissions_are_checked_at_parent_scope():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(
        session=None,
        scope={
            "subscription_id": "sub-1",
            "resource_group_name": "rg1",
            "namespace_name": "ns1",
        },
        namespace=namespace_payload(identity="SystemAssigned"),
    )
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg-identities/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/new-uami"
        ),
        uami_name="new-uami",
        create_uami=True,
        uami_resource_group="rg-identities",
        uami_location="eastus2",
    )
    set_choice(screen.context, "namespace", choice)
    requirements = screen._permission_requirements()
    assert choice.uami_id not in requirements
    parent = "/subscriptions/sub-1/resourceGroups/rg-identities"
    assert "Microsoft.ManagedIdentity/userAssignedIdentities/write" in requirements[parent]
    assert (
        "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action"
        in requirements[parent]
    )


def test_final_verification_honors_new_namespace_uami():
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg1/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/outbound"
        ),
        uami_name="outbound",
    )
    namespace_request = create_request("namespace", "new-ns")
    namespace_request.identity = choice
    dps_request = create_request("dps", "new-dps")
    ctx = {
        "subscription_id": "sub-1",
        "resource_group_name": "rg1",
        "namespace_name": "new-ns",
        "create_namespace": namespace_request,
        "create_dps": dps_request,
    }
    verify = next(
        item
        for item in build_flow(ctx).build_plan()
        if item.key == "verify-readiness"
    )
    namespace = {
        "properties": {
            "outboundIdentity": {
                "type": "UserAssigned",
                "userAssignedIdentity": choice.uami_id,
            },
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "resourceId": dps_request.arm_id("sub-1"),
                        "linkingState": "Succeeded",
                    }
                }
            },
        }
    }

    class Session:
        def provider(self, name):
            assert name == "namespace"
            return self

        def show(self, **_):
            return namespace

        def call(self, func, **kwargs):
            return func(**kwargs)

    assert verify.verify(Session(), ctx) is namespace


def test_update_instance_identity_attachment_uses_registered_factory(monkeypatch):
    import azext_iot._factory as factories

    seen = {}

    class Operations:
        def begin_update(self, **kwargs):
            seen.update(kwargs)
            return "poller"

    class Catalog:
        cmd = type("Cmd", (), {"cli_ctx": object()})()

    monkeypatch.setattr(
        factories,
        "adr_update_instance_service_factory",
        lambda _cli_ctx: type("Client", (), {"update_instances": Operations()})(),
    )
    result = attach_identity(
        Catalog(),
        "su",
        {
            "name": "updates",
            "id": (
                "/subscriptions/sub-1/resourceGroups/rg1/providers/"
                "Microsoft.DeviceUpdate/updateInstances/updates"
            ),
            "identity": {},
        },
        system_choice(),
    )
    assert result == "poller"
    assert seen["properties"]["identity"]["type"] == "SystemAssigned"


def test_hub_identity_attachment_preserves_snake_case_uamis(monkeypatch):
    import azext_iot._factory as factories

    old_uami = (
        "/subscriptions/sub-1/resourceGroups/rg1/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/existing"
    )
    seen = {}

    class Operations:
        def begin_create_or_update(self, **kwargs):
            seen.update(kwargs)
            return "poller"

    class Catalog:
        cmd = type("Cmd", (), {"cli_ctx": object()})()

    monkeypatch.setattr(
        factories,
        "iot_hub_service_factory",
        lambda _cli_ctx: type("Client", (), {"iot_hub_resource": Operations()})(),
    )
    attach_identity(
        Catalog(),
        "hub",
        {
            "name": "hub",
            "resourceGroup": "rg1",
            "identity": {
                "type": "UserAssigned",
                "user_assigned_identities": {old_uami: {}},
            },
        },
        system_choice(),
    )
    identity = seen["iot_hub_description"]["identity"]
    assert old_uami in identity["userAssignedIdentities"]
    assert identity["type"] == "SystemAssigned, UserAssigned"


def test_selected_uami_flows_to_link_and_role_plans():
    dps = identified(dps_candidate())
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg-identities/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/connectivity"
        ),
        uami_name="connectivity",
        principal_id="pid-uami",
    )
    ctx = context(
        namespace_with_principal(),
        selected_dps=dps,
        can_grant_roles=True,
    )
    set_choice(ctx, "dps", choice, dps.resource_id)
    flow = build_flow(ctx)
    link = next(item for item in flow.build_plan() if item.key == "dps")
    reverse = next(
        item
        for item in flow.build_plan()
        if item.key.startswith("grant-dps-to-ns")
    )
    assert f"--mi-user-assigned {choice.uami_id}" in link.command
    assert "--assignee-object-id pid-uami" in reverse.command


def test_new_uami_is_created_before_identity_attachment():
    dps = dps_candidate()
    dps.raw = {
        "name": dps.name,
        "id": dps.resource_id,
        "resourceGroup": "rg1",
        "identity": {},
    }
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg1/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/new-uami"
        ),
        uami_name="new-uami",
        create_uami=True,
        uami_resource_group="rg1",
        uami_location="eastus2",
    )
    ctx = context(namespace_with_principal(), selected_dps=dps)
    set_choice(ctx, "dps", choice, dps.resource_id)
    plan = build_flow(ctx).build_plan()
    keys = [item.key for item in plan]
    assert keys.index("uami-create-new-uami") < keys.index(
        f"identity-dps:{dps.resource_id.casefold()}"
    )


def test_new_resource_group_precedes_uami_and_target_creation():
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/new-rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/new-uami"
        ),
        uami_name="new-uami",
        create_uami=True,
        uami_resource_group="new-rg",
        uami_location="eastus2",
    )
    dps_request = create_request("dps", "new-dps", rg="new-rg")
    dps_request.identity = choice
    ctx = {
        "subscription_id": "sub-1",
        "resource_group_name": "new-rg",
        "create_resource_group": create_request(
            "resource_group", "new-rg", rg="new-rg"
        ),
        "namespace_name": "new-ns",
        "create_namespace": create_request(
            "namespace", "new-ns", rg="new-rg"
        ),
        "create_dps": dps_request,
    }
    keys = [item.key for item in build_flow(ctx).build_plan()]
    assert keys.index("resource-group") < keys.index("uami-create-new-uami")
    assert keys.index("uami-create-new-uami") < keys.index("dps-create")


def test_link_verifier_waits_for_endpoint_linking_state():
    dps = identified(dps_candidate())
    ctx = context(
        namespace_payload(identity="SystemAssigned"),
        selected_dps=dps,
        _link_poll_interval=0,
        _link_poll_attempts=3,
    )
    item = next(
        entry for entry in build_flow(ctx).build_plan() if entry.key == "dps"
    )
    responses = iter(
        [
            {
                "properties": {
                    "provisioning": {
                        "endpoints": {"dps": {"linkingState": "Updating"}}
                    }
                }
            },
            {
                "properties": {
                    "provisioning": {
                        "endpoints": {"dps": {"linkingState": "Succeeded"}}
                    }
                }
            },
        ]
    )
    details = []

    class Session:
        def provider(self, name):
            assert name == "namespace"
            return self

        def show(self, **_):
            return next(responses)

        def call(self, func, **kwargs):
            return func(**kwargs)

    assert item.verify(Session(), ctx, details.append)["linkingState"] == "Succeeded"
    assert details == ["linkingState: Updating", "linkingState: Succeeded"]


def test_adu_grant_resolves_tenant_local_service_principal():
    update = identified(dps_candidate("su-1"), principal="pid-su")
    flow = build_flow(
        context(
            namespace_with_principal(provisioning={"dps": {}}),
            selected_sus=[update],
            subscription_id="sub-1",
            adu_fpa_confirmed=True,
        )
    )
    grant = next(
        item
        for item in flow.build_plan()
        if item.key.startswith("grant-adu-fpa-")
    )
    assert "az ad sp show --id 6ee392c4-d339-4083-b04d-6b7947c6cf78" in grant.command


def test_link_steps_pass_the_selected_resource_id():
    class FakeSession:
        def __init__(self):
            self.seen = {}

        def provider(self, name):
            return self

        def dps_add(self, **kwargs):
            self.seen.update(kwargs)
            return "poller"

        def call(self, func, **kwargs):
            return func(**kwargs)

    dps = identified(dps_candidate())
    flow = build_flow(context(namespace_payload(identity="SystemAssigned"), selected_dps=dps))
    item = next(entry for entry in flow.build_plan() if entry.key == "dps")
    session = FakeSession()
    item.invoke(session, flow.context)
    assert session.seen["dps_resource_id"] == dps.resource_id
    assert session.seen["mi_system_assigned"] is True
    assert session.seen["no_wait"] is True


def test_chosen_resources_are_reported_only_in_the_rail():
    """The right pane stays task-focused; selected names live under their step."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"namespace_name": "ns1"},
                           namespace=namespace_payload(identity="SystemAssigned"))
    screen.context["selected_dps"] = dps_candidate("dps-a")
    screen.context["selected_hubs"] = [hub_candidate("hub-a")]
    assert screen._chosen_lines("dps") == ["dps-a · choose identity"]
    assert screen._chosen_lines("hub") == ["hub-a · choose identity"]
    assert not hasattr(screen, "_selection_summary")


# -- create-new paths ---------------------------------------------------------------


def create_request(
    kind="dps",
    name="new-dps",
    rg="rg1",
    location="eastus2",
    tags=None,
    sku=None,
    capacity=1,
):
    from azext_iot.adr.ui.screens.onboard.create import CreateRequest

    return CreateRequest(
        kind=kind,
        name=name,
        resource_group_name=rg,
        location=location,
        sku=sku,
        capacity=capacity,
        tags=tags,
    )


def test_flow_can_start_with_no_namespace_at_all():
    """A fresh start: nothing exists yet, and the first step is to choose or create."""
    flow = build_flow({"subscription_id": "sub-1", "resource_group_name": "rg1"})
    states = all_states(flow)
    assert states["namespace"] is StepState.CURRENT


def test_creating_a_namespace_plans_it_with_an_identity():
    flow = build_flow({"subscription_id": "sub-1", "resource_group_name": "rg1",
                       "namespace_name": "new-ns",
                       "create_namespace": create_request("namespace", "new-ns")})
    plan = {item.key: item for item in flow.build_plan()}
    assert plan["namespace"].action == "create"
    assert plan["namespace"].invoke is not None
    assert "--outbound-mi-system-assigned" in plan["namespace"].command


def test_namespace_plan_includes_optional_tags():
    request = create_request(
        "namespace",
        "new-ns",
        tags={"environment": "dev", "owner": "iot team"},
    )
    flow = build_flow({
        "subscription_id": "sub-1",
        "resource_group_name": "rg1",
        "namespace_name": "new-ns",
        "create_namespace": request,
    })
    command = next(item.command for item in flow.build_plan() if item.key == "namespace")
    assert "--tags environment=dev" in command
    assert "'owner=iot team'" in command


def test_namespace_creation_passes_tags_to_the_provider():
    seen = {}

    class FakeSession:
        def provider(self, name):
            assert name == "namespace"
            return self

        def create(self, **kwargs):
            seen.update(kwargs)
            return "poller"

        def call(self, func, **kwargs):
            return func(**kwargs)

    request = create_request(
        "namespace",
        "new-ns",
        tags={"environment": "dev"},
    )
    flow = build_flow({
        "subscription_id": "sub-1",
        "resource_group_name": "rg1",
        "namespace_name": "new-ns",
        "create_namespace": request,
    })
    item = next(entry for entry in flow.build_plan() if entry.key == "namespace")
    assert item.invoke(FakeSession(), flow.context) == "poller"
    assert seen["tags"] == {"environment": "dev"}


def test_creating_a_provisioning_service_plans_create_then_link():
    flow = build_flow(context(namespace_with_principal(), create_dps=create_request(),
                              subscription_id="sub-1"))
    plan = [item.key for item in flow.build_plan() if item.is_actionable]
    assert plan.index("dps-create") < plan.index("dps"), "create before link"


def test_created_resources_get_a_deterministic_arm_id():
    """The link command can be written before the resource exists."""
    flow = build_flow(context(namespace_with_principal(), create_dps=create_request(),
                              subscription_id="sub-1"))
    link = next(item for item in flow.build_plan() if item.key == "dps")
    assert "/subscriptions/sub-1/resourceGroups/rg1/providers/" in link.command
    assert "provisioningServices/new-dps" in link.command


def test_new_resources_are_always_created_with_an_identity():
    from azext_iot.adr.ui.screens.onboard.create import dps_body, hub_body

    assert dps_body("eastus2")["identity"]["type"] == "SystemAssigned"
    assert hub_body("eastus2")["identity"]["type"] == "SystemAssigned"


def test_hub_and_dps_creation_honour_sku_and_capacity():
    from azext_iot.adr.ui.screens.onboard.create import dps_body, hub_body

    assert hub_body("eastus2", "S2", 3)["sku"] == {
        "name": "S2",
        "capacity": 3,
    }
    assert dps_body("eastus2", "S1", 2)["sku"] == {
        "name": "S1",
        "capacity": 2,
    }


def test_hub_and_dps_plan_commands_include_size():
    hub_flow = build_flow(
        context(
            namespace_with_principal(provisioning={"dps": {}}),
            create_hub=create_request("hub", "new-hub", sku="S2", capacity=3),
        )
    )
    hub = next(item for item in hub_flow.build_plan() if item.key == "hub-create")
    assert "--sku S2 --unit 3" in hub.command
    assert "--mi-system-assigned" in hub.command

    dps_flow = build_flow(
        context(
            namespace_with_principal(),
            create_dps=create_request("dps", "new-dps", sku="S1", capacity=2),
        )
    )
    dps = next(item for item in dps_flow.build_plan() if item.key == "dps-create")
    assert "--sku S1 --unit 2" in dps.command
    assert "--mi-system-assigned" in dps.command


def test_reverse_grant_for_a_pending_resource_says_when_to_run_it():
    """Without the right to grant, the principal id can only be read after creation."""
    flow = build_flow(context(namespace_with_principal(), create_dps=create_request(),
                              subscription_id="sub-1", can_grant_roles=False))
    reverse = next(item for item in flow.build_plan() if item.key.startswith("grant-dps-to-ns"))
    assert reverse.action == "manual"
    assert "after" in reverse.blocked_reason and "is created" in reverse.blocked_reason
    assert "az resource show" in reverse.command
    assert "<" not in reverse.command


def test_a_resource_without_an_identity_is_repaired_before_reverse_grant():
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_dps=dps_candidate(), can_grant_roles=True))
    reverse = next(item for item in flow.build_plan() if item.key.startswith("grant-dps-to-ns"))
    assert reverse.action == "create"


def test_creating_a_hub_plans_create_then_link():
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              create_hub=create_request("hub", "new-hub"),
                              subscription_id="sub-1"))
    plan = [item.key for item in flow.build_plan() if item.is_actionable]
    assert plan.index("hub-create") < plan.index("hub-0")


def test_software_updates_is_optional_and_absent_until_chosen():
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}},
                                                       messaging={"hub": {}})))
    keys = [item.key for item in flow.build_plan()]
    assert "su" not in keys, "an optional step contributes nothing until chosen"
    assert next(step for step in flow.steps if step.id == "su").optional


def test_choosing_software_updates_plans_the_link():
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_sus=[identified(dps_candidate("su-1"))],
                              subscription_id="sub-1"))
    link = next(item for item in flow.build_plan() if item.key == "su")
    assert "link su add" in link.command
    assert link.invoke is not None


def test_software_updates_gets_grants_in_both_directions():
    update = identified(dps_candidate("su-1"), principal="pid-su")
    flow = build_flow(
        context(
            namespace_with_principal(provisioning={"dps": {}}),
            selected_sus=[update],
            subscription_id="sub-1",
        )
    )
    grants = [
        item
        for item in flow.build_plan()
        if item.key.startswith("grant-") and "su-1" in item.key
    ]
    assert len(grants) == 3
    assert any("--assignee-object-id pid-ns" in item.command for item in grants)
    assert any("--assignee-object-id pid-su" in item.command for item in grants)
    link = next(item for item in flow.build_plan() if item.key == "su")
    assert max(item.phase for item in grants) < link.phase


def test_several_update_instances_are_each_linked_under_their_own_endpoint():
    """Updating endpoints are a map, so one namespace may serve several instances."""
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_sus=[identified(dps_candidate("su-1")),
                                            identified(dps_candidate("su-2"))],
                              subscription_id="sub-1"))
    links = [item for item in flow.build_plan() if item.key in ("su", "su-1")]
    assert len(links) == 2
    endpoints = {item.command.split("--endpoint-name ")[1].split()[0] for item in links}
    assert endpoints == {"su-1", "su-2"}, "a shared endpoint name would overwrite the first"


def test_name_validation_rejects_bad_resource_names():
    from azext_iot.adr.ui.screens.onboard.forms import parse_tags, validate_name

    assert validate_name("good-name-1") is None
    assert validate_name("") is not None
    assert validate_name("-leading") is not None
    assert validate_name("trailing-") is not None
    assert validate_name("has space") is not None
    assert validate_name("rg.prod_team", "resource_group") is None
    assert validate_name("rg.", "resource_group") is not None
    assert validate_name("d" * 64, "dps") is None
    assert validate_name("h" * 51, "hub") is not None
    assert validate_name("u" * 37, "su") is not None
    assert parse_tags('environment=dev owner="iot team"') == (
        {"environment": "dev", "owner": "iot team"},
        None,
    )
    assert "key=value" in parse_tags("broken")[1]


def test_created_resources_still_get_forward_grants():
    """A new resource needs the same grants; only its own principal id is unknown."""
    flow = build_flow(context(namespace_with_principal(), create_dps=create_request(),
                              subscription_id="sub-1"))
    forward = next(item for item in flow.build_plan() if item.key.startswith("grant-ns-to-dps"))
    assert "--assignee-object-id pid-ns" in forward.command


def test_a_resource_created_in_the_same_run_can_still_be_granted():
    """Its principal id is unknown when planning, so it is read when the grant runs."""
    flow = build_flow(context(namespace_with_principal(), create_dps=create_request(),
                              subscription_id="sub-1", can_grant_roles=True))
    reverse = next(item for item in flow.build_plan() if item.key.startswith("grant-dps-to-ns"))
    assert reverse.action == "create", "waiting for a second run defeats guided setup"
    assert reverse.invoke is not None


# -- scope: subscription and resource group ------------------------------------------


def test_subscription_is_the_first_step_and_gates_the_rest():
    flow = build_flow({})
    states = all_states(flow)
    assert states["subscription"] is StepState.CURRENT
    assert states["scope"] is StepState.BLOCKED


def test_resource_group_step_follows_the_subscription():
    flow = build_flow({"subscription_id": "sub-1"})
    states = all_states(flow)
    assert states["subscription"] is StepState.SATISFIED
    assert states["scope"] is StepState.CURRENT


def test_creating_a_resource_group_is_planned():
    flow = build_flow({"subscription_id": "sub-1",
                       "create_resource_group": create_request("resource_group", "new-rg")})
    item = next(entry for entry in flow.build_plan() if entry.key == "resource-group")
    assert item.invoke is not None
    assert "az group create -n new-rg" in item.command


def test_scope_without_a_resource_group_is_blocked_not_silent():
    flow = build_flow({"subscription_id": "sub-1"})
    item = next(entry for entry in flow.build_plan() if entry.key == "scope")
    assert item.action == "blocked"
    assert "no resource group chosen" in item.blocked_reason


def test_a_satisfied_step_can_be_revisited():
    """Satisfied steps are skipped by the flow; without a jump, subscription is unreachable."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None,
                           scope={"subscription_id": "sub-1", "resource_group_name": "rg1"},
                           namespace=namespace_payload(identity="SystemAssigned"))
    assert screen.active_step().id != "subscription", "satisfied, so normally skipped"
    screen._focus_step = "subscription"
    assert screen.active_step().id == "subscription", "a jump makes it reachable again"


def test_active_step_falls_back_to_the_flow():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen._focus_step = "does-not-exist"
    assert screen.active_step() is screen.flow.current()


# -- interaction model (follows Posting/Harlequin: focusable panes, inline forms) -----


def test_creation_is_inline_not_a_pushed_screen():
    """A pushed screen would hide the step rail and the context being worked against."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert "CreateResourceDialog" not in source, "creation must not push a screen"
    assert 'id="create-form"' in source, "the form lives inside the pane"


def test_screen_focuses_the_picker_on_arrival():
    """Without an explicit focus, arrow keys go nowhere."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert '.focus()' in source


def test_steps_are_listed_in_a_navigable_widget():
    """The rail is a list so arrows move through steps, as in the reference apps."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert "ListView" in source and "on_list_view_highlighted" in source


def test_create_request_is_recorded_and_scopes_downstream_steps():
    """Regression: _accept_create was lost in a refactor and crashed the form."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    request = create_request("namespace", "radar1", rg="cli-test-canary",
                             location="centraluseuap")
    screen._accept_create("namespace", "create_namespace", request)
    assert screen.context["create_namespace"] is request
    assert screen.context["namespace_name"] == "radar1"
    assert screen.context["resource_group_name"] == "cli-test-canary"
    assert screen.context["location"] == "centraluseuap"


def test_accept_create_ignores_a_cancelled_form():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen._accept_create("namespace", "create_namespace", None)
    assert "create_namespace" not in screen.context


def test_candidate_filter_matches_name_group_and_region():
    """Scrolling 308 subscriptions is unusable; filtering is not optional."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen._candidates = [
        Candidate(name="alpha-dps", resource_id="1", resource_group="rg-one",
                  location="eastus2"),
        Candidate(name="beta-dps", resource_id="2", resource_group="rg-two",
                  location="westus"),
    ]
    screen._candidate_filter = "alpha"
    assert [c.name for c in screen._visible_candidates()] == ["alpha-dps"]
    screen._candidate_filter = "rg-two"
    assert [c.name for c in screen._visible_candidates()] == ["beta-dps"]
    screen._candidate_filter = "westus"
    assert [c.name for c in screen._visible_candidates()] == ["beta-dps"]
    screen._candidate_filter = ""
    assert len(screen._visible_candidates()) == 2


def test_tab_is_not_swallowed_by_a_dead_binding():
    """A screen-level 'tab' binding to a non-existent action broke focus traversal."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    keys = [binding.key for binding in OnboardScreen.BINDINGS]
    assert "tab" not in keys, "Textual moves focus on Tab natively"


def test_queued_creation_is_visible_in_the_rail_and_body():
    """Clicking the button records intent; the customer must see that it landed."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    assert screen._pending_creation("namespace") is None
    assert screen._pending_summary() == ""

    request = create_request("namespace", "radar1")
    screen._accept_create("namespace", "create_namespace", request)
    assert screen._pending_creation("namespace") is request
    assert "create namespace 'radar1'" in screen._pending_summary()


def test_button_label_does_not_claim_to_create():
    """It adds to the plan; nothing runs until apply."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert "SetupFormButton(" in source and '"Add to setup"' in source
    assert 'Button("Create"' not in source


def test_creating_a_namespace_does_not_also_assign_an_identity():
    """`ns create` always assigns one; assigning again fails as 'already assigned'."""
    flow = build_flow({"subscription_id": "sub-1", "resource_group_name": "rg1",
                       "namespace_name": "radr",
                       "create_namespace": create_request("namespace", "radr")})
    identity = next(item for item in flow.build_plan() if item.key == "identity")
    assert identity.action == "exists"
    assert identity.invoke is None, "a redundant assign would fail the whole apply"


def test_adopting_a_namespace_without_identity_still_assigns_one():
    flow = build_flow(context(namespace_payload()))
    identity = next(item for item in flow.build_plan() if item.key == "identity")
    assert identity.invoke is not None


def test_steps_are_named_after_the_action_they_perform():
    """'Provisioning service' describes a noun; 'Link DPS' describes what happens."""
    flow = build_flow(context())
    titles = {step.id: step.title for step in flow.steps}
    assert titles["dps"] == "Link DPS"
    assert titles["hub"] == "Link Hub"
    assert titles["su"] == "Link Software Updates"
    assert titles["permissions"] == "Grant role assignments"


def test_step_titles_fit_a_narrow_rail():
    """The rail is ~28 columns at its narrowest; longer titles were being truncated."""
    flow = build_flow(context())
    for step in flow.steps:
        assert len(step.title) <= 24, f"'{step.title}' is too long for the rail"


# -- many hubs per namespace ---------------------------------------------------------


def test_multiple_hubs_each_get_their_own_link():
    """One DPS is the cap; hubs are many, which is why allocation weight exists."""
    hubs = [identified(hub_candidate("hub-a")), identified(hub_candidate("hub-b"))]
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_hubs=hubs, subscription_id="sub-1"))
    links = [item for item in flow.build_plan() if item.key.startswith("hub-")]
    assert len(links) == 2
    assert "hub-a" in links[0].command and "hub-b" in links[1].command


def test_each_hub_gets_its_own_endpoint_name():
    """Endpoint names must be unique within the namespace or the second link overwrites."""
    hubs = [identified(hub_candidate("hub-a")), identified(hub_candidate("hub-b"))]
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_hubs=hubs, subscription_id="sub-1"))
    names = [
        item.command.split("--endpoint-name ")[1].split(" ")[0]
        for item in flow.build_plan() if item.key.startswith("hub-")
    ]
    assert len(set(names)) == len(names), f"endpoint names collide: {names}"


def test_every_selected_hub_gets_grants_in_both_directions():
    hubs = [
        identified(hub_candidate("hub-a"), principal="pid-hub-a"),
        identified(hub_candidate("hub-b"), principal="pid-hub-b"),
    ]
    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_hubs=hubs, subscription_id="sub-1"))
    grants = [item.description for item in flow.build_plan() if item.key.startswith("grant-")]
    for hub in ("hub-a", "hub-b"):
        assert any(hub in text and "namespace identity" in text for text in grants)
        assert any(hub in text and "on the namespace" in text for text in grants)


def test_shared_uami_reverse_grant_is_deduplicated():
    hubs = [hub_candidate("hub-a"), hub_candidate("hub-b")]
    for hub in hubs:
        hub.raw = {"identity": {}}
    choice = IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=(
            "/subscriptions/sub-1/resourceGroups/rg1/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/shared"
        ),
        uami_name="shared",
        principal_id="pid-shared",
    )
    ctx = context(
        namespace_with_principal(provisioning={"dps": {}}),
        selected_hubs=hubs,
        subscription_id="sub-1",
    )
    for hub in hubs:
        set_choice(ctx, "hub", choice, hub.resource_id)
    reverse = [
        item
        for item in build_flow(ctx).build_plan()
        if item.key.startswith("grant-hub-to-ns")
    ]
    assert len(reverse) == 1


def test_rail_lists_decisions_only():
    """Automatic operations shown as steps read as chores the customer must act on."""
    flow = build_flow(context())
    visible = [step.id for step in flow.visible_steps()]
    assert "identity" not in visible, "assigning an identity is never a choice"
    assert "permissions" not in visible, "grants are an output, not a decision"
    assert visible[-1] == "review", "the rail ends where changes happen"


def test_hidden_steps_still_contribute_to_the_plan():
    flow = build_flow(context(namespace_payload()))
    keys = [item.key for item in flow.build_plan()]
    assert "identity" in keys, "hidden from the rail, but still executed"


# -- orientation: what am I choosing, and what have I chosen -------------------------


def test_rail_shows_what_was_chosen_for_each_step():
    """Without this the rail says 'Subscription' but never which one."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={
        "subscription_id": "sub-1", "subscription_name": "Contoso-Dev",
        "resource_group_name": "rg-one", "namespace_name": "factory",
    })
    assert screen._chosen_lines("subscription") == ["Contoso-Dev"]
    assert screen._chosen_lines("scope") == ["rg-one"]
    assert screen._chosen_lines("namespace") == ["factory · choose identity"]


def test_rail_uses_names_and_focus_instead_of_status_badges():
    """`[ok]` beside every selection is visual noise; the chosen name is the evidence."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    rail = source.split("def _render_rail", 1)[1].split("def _render_body", 1)[0]
    assert "[ok]" not in rail
    assert "_chosen_lines" in rail
    assert 'title_classes = "step-title"' in rail
    assert 'classes="step-resources"' in rail


def test_inline_create_form_has_a_clear_field_hierarchy():
    """The form should read as a compact form, not six unrelated stacked widgets."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert 'classes="form-field"' in source
    assert 'classes="form-label"' in source
    assert 'id="create-subtitle"' in source
    assert "SetupFormButton(" in source and '"Add to setup"' in source
    assert 'id="create-sku"' in source
    assert 'id="create-capacity"' in source
    assert 'id="create-form-hint"' in source
    assert "IDENTITY  SystemAssigned" not in source


def test_chosen_candidate_name_does_not_collide_with_cursor_colour():
    """The cursor owns foreground contrast; selection uses weight and a visible marker."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    paint = source.split("def _paint_candidates", 1)[1].split(
        "def _is_chosen", 1
    )[0]
    assert 'prefix = "[selected] "' in paint
    chosen_style = paint.split("name_style =", 1)[1].split("name = Text", 1)[0]
    assert '"bold"' in chosen_style
    assert "STYLE_ACTIVE" not in chosen_style


def test_candidate_loading_never_shows_rows_from_the_previous_step():
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert 'LoadingIndicator(id="candidate-loading")' in source
    assert "def _load_candidates(self, step_id: str, generation: int)" in source
    show = source.split("def _show_candidates", 1)[1].split(
        "def _paint_candidates", 1
    )[0]
    assert "step.id != step_id" in show
    reload_candidates = source.split("def _reload_candidates", 1)[1].split(
        "def _render_candidate_status", 1
    )[0]
    assert "self._candidates = []" in reload_candidates
    assert "table.display = False" in reload_candidates


def test_review_page_ends_with_one_clear_next_step():
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    review = source.split("def _render_review", 1)[1].split(
        "def _chosen_lines", 1
    )[0]
    assert '"\\nNEXT\\n"' in review
    assert "NEEDS ADMIN ACCESS" in review
    assert "manual[:4]" not in review, "individual grants belong in the full plan"


def test_right_pane_omits_progress_and_selected_resource_repetition():
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    body = source.split("def _render_body", 1)[1].split(
        "def _grant_rights_note", 1
    )[0]
    assert "_progress_text" not in body
    assert "_selection_summary" not in source
    assert "Selected   " not in body


def test_customer_facing_provisioning_resource_is_called_dps():
    import pathlib

    for path in pathlib.Path("azext_iot/adr/ui").rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert "provisioning service" not in source, path


def test_rail_lists_every_chosen_hub_rather_than_hiding_them():
    """'+3 more' hides exactly what the customer is checking before running the plan."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen.context["selected_hubs"] = [hub_candidate(f"hub-{i}") for i in range(4)]
    assert screen._chosen_lines("hub") == [
        "hub-0 · choose identity",
        "hub-1 · choose identity",
        "hub-2 · choose identity",
        "hub-3 · choose identity",
    ]


def test_rail_lists_chosen_update_instances_too():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen.context["selected_sus"] = [hub_candidate("su-a"), hub_candidate("su-b")]
    assert screen._chosen_lines("su") == [
        "su-a · choose identity",
        "su-b · choose identity",
    ]


def test_rail_stops_listing_choices_before_it_fills_the_pane():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen, _RAIL_CHOICE_LIMIT

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen.context["selected_hubs"] = [hub_candidate(f"hub-{i}") for i in range(14)]
    lines = screen._chosen_lines("hub")
    assert len(lines) == _RAIL_CHOICE_LIMIT + 1
    assert lines[-1] == f"and {14 - _RAIL_CHOICE_LIMIT} more"


def test_every_picker_step_has_empty_state_guidance():
    """An empty table with no explanation reads as a broken product."""
    from azext_iot.adr.ui.screens.onboard.screen import _EMPTY_GUIDANCE, _PICKER_STEPS

    for step_id in _PICKER_STEPS:
        message = _EMPTY_GUIDANCE.get(step_id, "")
        assert message, f"no guidance for an empty '{step_id}' picker"
        assert "press n" in message or "az login" in message, (
            f"guidance for '{step_id}' does not say what to do next"
        )


def test_existing_namespaces_can_be_selected():
    """Namespaces had no picker, so an existing one could not be adopted from the flow."""
    from azext_iot.adr.ui.screens.onboard.screen import _PICKER_STEPS

    assert "namespace" in _PICKER_STEPS


def test_rail_positions_map_to_visible_steps_only():
    """Indexing all steps selects the wrong one once a hidden step sits between two."""
    flow = build_flow(context())
    visible = flow.visible_steps()
    assert [s.id for s in visible][:4] == ["subscription", "scope", "namespace", "dps"]
    # Identity planning steps are hidden between scope/namespace and DPS.
    assert [s.id for s in flow.steps][2:5] == ["uami", "namespace", "identity"]
    assert visible[3].id == "dps", "rail position 4 must be Link DPS, not the hidden step"


def test_every_picker_step_has_a_loading_noun():
    """A missing entry crashed the status line the moment a new picker was added."""
    from azext_iot.adr.ui.screens.onboard.screen import _PICKER_NOUNS, _PICKER_STEPS

    for step_id in _PICKER_STEPS:
        assert step_id in _PICKER_NOUNS, f"no loading noun for '{step_id}'"


# -- advancing after a choice --------------------------------------------------------


def test_selecting_clears_the_pinned_step_so_the_flow_moves_on():
    """Without this the pane stays on the completed step and the customer must navigate."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen._focus_step = "scope"
    screen._candidate_filter = "canary"
    screen._advance()
    assert screen._focus_step == "scope", "the next open step is pinned explicitly"
    assert screen._candidate_filter == "", "a filter must not carry into the next step"


def test_advance_moves_to_the_next_unsatisfied_step():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    assert screen.active_step().id == "scope"
    screen.context["resource_group_name"] = "rg-one"
    screen._advance()
    assert screen.active_step().id == "namespace"


def test_hub_step_does_not_advance_because_it_is_multi_select():
    """Advancing after the first hub would make linking a second one awkward."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    hub_branch = source.split('if step.id == "hub":', 1)[1].split("def ", 1)[0]
    assert "_advance(" not in hub_branch, "the hub step must stay put for multi-select"


def test_rail_repaint_is_not_mistaken_for_a_choice():
    """Setting the rail index programmatically used to re-pin the step being left."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    assert "_syncing_rail" in source
    handler = source.split("def on_list_view_highlighted", 1)[1].split("def ", 1)[0]
    assert "if self._syncing_rail:" in handler


# -- finishing a multi-select step ---------------------------------------------------


def _screen_with(**context):
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    screen = OnboardScreen(session=None, scope={"subscription_id": "sub-1"})
    screen.context.update(context)
    screen.flashes = []
    screen.flash = lambda message, level="info": screen.flashes.append((level, message))
    return screen


def test_selecting_a_second_hub_keeps_both():
    screen = _screen_with()
    screen._toggle_choice("hub", hub_candidate("hub-a"))
    screen._toggle_choice("hub", hub_candidate("hub-b"))
    assert [h.name for h in screen.context["selected_hubs"]] == ["hub-a", "hub-b"]


def test_selecting_the_same_hub_twice_removes_it():
    """Appending twice used to queue a duplicate endpoint, which failed at link time."""
    screen = _screen_with()
    screen._toggle_choice("hub", hub_candidate("hub-a"))
    screen._toggle_choice("hub", hub_candidate("hub-a"))
    assert screen.context["selected_hubs"] == []


def test_update_instances_toggle_the_same_way_as_hubs():
    screen = _screen_with()
    screen._toggle_choice("su", hub_candidate("su-a"))
    screen._toggle_choice("su", hub_candidate("su-b"))
    assert [s.name for s in screen.context["selected_sus"]] == ["su-a", "su-b"]


def test_done_on_a_multi_select_step_moves_on():
    hub = hub_candidate("hub-a")
    screen = _screen_with(selected_hubs=[hub])
    set_choice(screen.context, "hub", system_choice(), hub.resource_id)
    screen._focus_step = "hub"
    screen.action_done_step()
    assert screen._focus_step != "hub"


def test_done_blocks_when_a_selected_resource_has_no_identity_choice():
    screen = _screen_with(selected_hubs=[hub_candidate("hub-a")])
    screen._focus_step = "hub"
    screen.action_done_step()
    assert screen._focus_step == "hub"
    assert any(
        "choose an identity" in message
        for _level, message in screen.flashes
    )


def test_rail_identifies_sami_and_uami_choices():
    sami_hub = hub_candidate("hub-sami")
    uami_hub = hub_candidate("hub-uami")
    screen = _screen_with(selected_hubs=[sami_hub, uami_hub])
    set_choice(screen.context, "hub", system_choice(), sami_hub.resource_id)
    set_choice(
        screen.context,
        "hub",
        IdentityChoice(
            mode=USER_ASSIGNED,
            uami_id=(
                "/subscriptions/sub-1/resourceGroups/rg1/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/shared"
            ),
            uami_name="shared",
        ),
        uami_hub.resource_id,
    )
    assert screen._chosen_lines("hub") == [
        "hub-sami · SAMI",
        "hub-uami · UAMI shared",
    ]


def test_done_with_nothing_chosen_on_a_required_step_says_so():
    """Silently advancing would produce a namespace with no messaging endpoint."""
    screen = _screen_with()
    screen._focus_step = "hub"
    screen.action_done_step()
    assert screen._focus_step == "hub"
    assert any(level == "warning" for level, _ in screen.flashes)


def test_done_with_nothing_chosen_skips_an_optional_step():
    screen = _screen_with()
    screen._focus_step = "su"
    screen.action_done_step()
    assert screen._focus_step != "su"


def test_done_counts_a_resource_that_is_still_to_be_created():
    screen = _screen_with(create_hub=create_request("hub", "new-hub"))
    screen._focus_step = "hub"
    screen.action_done_step()
    assert screen._focus_step != "hub"


def test_the_done_key_is_bound_and_advertised():
    """A multi-select step with no visible way out is a dead end."""
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    binding = next(b for b in OnboardScreen.BINDINGS if b.action == "done_step")
    assert binding.key == "d"
    assert binding.show, "the customer cannot guess an unlisted key"


def test_enter_is_primary_and_space_is_only_a_hidden_multi_select_shortcut():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    bindings = {binding.key: binding for binding in OnboardScreen.BINDINGS}
    assert bindings["enter"].action == "select"
    assert bindings["enter"].show
    assert bindings["space"].action == "toggle_multi"
    assert not bindings["space"].show


def test_a_step_whose_choices_are_made_is_not_shown_as_outstanding():
    """The rail must distinguish 'chosen, will run' from 'nothing done here yet'."""
    from azext_iot.adr.ui.screens.onboard.steps import build_flow

    flow = build_flow(context(namespace_with_principal(provisioning={"dps": {}}),
                              selected_hubs=[identified(hub_candidate())]))
    hub = next(step for step in flow.steps if step.id == "hub")
    assert not hub.is_satisfied(flow.context), "nothing is linked until the plan runs"
    assert hub.is_planned(flow.context), "but the rail should show it as ready"


def test_help_documents_the_guided_setup_keys():
    """Keys that only appear in the footer are invisible to anyone who opens help."""
    from azext_iot.adr.ui.screens.help import SETUP_KEYS

    keys = {key for key, _ in SETUP_KEYS}
    assert {"enter", "space", "d", "n", "j", "a", "p"} <= keys


def test_reload_re_asks_whether_grants_are_allowed():
    """The review panel tells the customer to activate PIM and press r, so r must re-ask."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    handler = source.split("def action_reload", 1)[1].split("    def ", 1)[0]
    assert "_grant_probe_for" in handler and "_probe_grant_rights()" in handler
    assert "self.catalog.clear()" in handler


def test_switching_subscription_discards_the_previous_grant_verdict():
    """Rights are per subscription; carrying the answer over would be wrong either way."""
    import pathlib

    source = pathlib.Path(
        "azext_iot/adr/ui/screens/onboard/screen.py"
    ).read_text(encoding="utf-8")
    handler = source.split("def _switch_subscription", 1)[1].split("    def ", 1)[0]
    assert 'pop("can_grant_roles"' in handler
