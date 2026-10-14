# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import errno
import json
import os
import re
import sys
import threading
from copy import deepcopy
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError, ResourceNotFoundError
from rich.cells import cell_len
from rich.color import Color
from rich.console import Console

from azext_iot.adr.workflows import guided
from azext_iot.adr.workflows.configuration import load_config
from azext_iot.adr.workflows.input import BackRequested, WorkflowCancelled
from azext_iot.adr.workflows.models import PlanItem, SetupRequest, WorkflowExecutionError

SUB = "00000000-0000-0000-0000-000000000001"
ARM = f"/subscriptions/{SUB}/resourceGroups/rg-demo/providers/"
DPS_ID = ARM + "Microsoft.Devices/provisioningServices/shared-dps"
HUB_ID = ARM + "Microsoft.Devices/IotHubs/typed-hub"
UAMI_ID = ARM + "Microsoft.ManagedIdentity/userAssignedIdentities/id"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
Back = BackRequested


def plain(text):
    return ANSI.sub("", text)


def flat(text):
    """Whitespace-normalised text: assertions on messages independent of terminal wrapping."""
    return " ".join(text.split())


def joined(text):
    """Transcript text with wrapped value lines rejoined, for asserting on whole sentences."""
    return text.replace("\n" + " " * 23, " ")


MANAGER_ESC = "esc-in-hubs-manager"  # script answer: Esc in the IoT Hubs manager (a bare Back there would continue)


class Scripted:
    """A prompter that replays answers and records every question that was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.continued = []  # IoT Hubs manager prompts the script left to their default, Continue

    def _next(self, kind, label, rows=(), **kwargs):
        self.calls.append({"kind": kind, "label": label, "rows": list(rows), **kwargs})
        if not self.answers:
            raise AssertionError(f"Unexpected question {label}")
        value = self.answers.pop(0)
        if isinstance(value, BaseException) or (isinstance(value, type) and issubclass(value, BaseException)):
            raise value
        return value

    def ask(self, label, rows=(), **kwargs):
        return self._next("ask", label, rows, **kwargs)

    def select(self, label, rows, **kwargs):
        # The IoT Hubs manager follows the first IoT Hub. Scripts that don't operate it (their next answer isn't
        # one of its rows) continue with what was chosen, as Enter on its default "Continue" row does.
        if label == "IoT Hubs:" and not (self.answers and isinstance(self.answers[0], str) and (
                self.answers[0] in ("done", MANAGER_ESC) or self.answers[0].startswith(("hub:", "add-")))):
            self.continued.append({"kind": "select", "label": label, "rows": list(rows), **kwargs})
            return "done"
        value = self._next("select", label, rows, **kwargs)
        if value == MANAGER_ESC:
            raise BackRequested()
        return value

    def ask_many(self, label, rows=(), **kwargs):
        value = self._next("ask_many", label, rows, **kwargs)
        return value if isinstance(value, list) else [value]

    def confirm(self, label, **kwargs):
        return self._next("confirm", label, **kwargs)

    @property
    def labels(self):
        return [call["label"] for call in self.calls]


class Engine:
    """NamespaceWorkflow stand-in: plans are queued (the last repeats); setup is scripted per test."""

    def __init__(self, *plans, setup=None):
        self.plans = list(plans)
        self.requests = []
        self.applied = []
        self.setup_fn = setup or succeed

    def __call__(self, services, progress=None):
        engine = self

        class Bound:
            def plan_setup(self, request):
                engine.requests.append(request)
                plan = engine.plans.pop(0) if len(engine.plans) > 1 else engine.plans[0]
                if isinstance(plan, BaseException):
                    raise plan
                return deepcopy(plan), []

            def setup(self, request):
                engine.applied.append(request)
                return engine.setup_fn(progress, request)

        return Bound()


def succeed(progress, request):
    progress.observe_items([PlanItem("namespace", "create", request.namespace_name, "Succeeded")])
    progress.run("Create namespace", lambda: None, workflow_scope="namespace", mutation=True)
    progress.run("Read hub", lambda: None)
    progress.run("Link hub main", lambda: None)
    with pytest.raises(ValueError):
        progress.run("Check role", _raise, handled_error=lambda error: True)
    return {"state": "Succeeded", "items": [
        {"id": "namespace", "state": "Succeeded", "action": "create", "target": request.namespace_name},
        {"id": "link-hub-main", "state": "Succeeded", "action": "link", "message": "Link request submitted."},
    ]}


def _raise():
    raise ValueError("expected")


def services(namespace=None, groups=None, targets=None):
    fake = MagicMock()
    fake.subscription_id = SUB
    fake.show_subscription.return_value = {"displayName": "Contoso Dev"}
    fake.list_resource_groups.return_value = groups if groups is not None else [
        {"name": "rg-demo", "location": "eastus"}, {"name": "rg-other", "location": "westus"},
    ]
    fake.show_resource_group.side_effect = lambda name: {"name": name, "location": "eastus"}
    fake.list_namespaces.return_value = [{"name": "existing-ns", "location": "eastus", "provisioningState": "Succeeded"}]
    fake.show_namespace.return_value = namespace
    fake.list_link_targets.side_effect = lambda kind, rg=None, subscription=None: (targets or {}).get(kind, [])
    fake.namespace_outbound_principal.return_value = "principal"
    fake.resolve_resource.side_effect = lambda endpoint: {
        "id": endpoint.resource_id, "name": endpoint.endpoint_name, "location": "eastus", "sku": {"name": "S1"},
        "properties": {"provisioningState": "Succeeded"},
    }
    fake.validate_setup_target.return_value = None
    return fake


def screen(width=80, *, plain_mode=False, color="standard"):
    stream = StringIO()
    console = Console(file=stream, force_terminal=not plain_mode, width=width, color_system=None if plain_mode else color,
                      highlight=False, markup=False, emoji=False)
    return guided.Screen(stream, plain=plain_mode, console=console, motion=False)


def plan(*items, state="Planned"):
    return {"state": state, "items": list(items), "summary": {}}


def item(item_id, action="create", target="adr-demo", state="Planned", **details):
    return {"id": item_id, "action": action, "target": target, "state": state, "details": details}


NEW_PLAN = plan(
    item("namespace", location="eastus"),
    item("namespace-outbound-identity", "configure"),
    item("resource-dps-adr-demo-dps", target="adr-demo-dps", sku="S1", unit=1, location="eastus"),
    item("resource-hub-adr-demo-hub", target="adr-demo-hub", sku="S1", unit=1, location="eastus"),
    item("link-dps-adr-demo-dps", "link", "adr-demo-dps", resourceId="/s/dps/adr-demo-dps", identityType="SystemAssigned"),
    item("roles-dps-adr-demo-dps", "role", "/s/dps/adr-demo-dps", targetScope="/s/dps/adr-demo-dps"),
    item("link-hub-adr-demo-hub", "link", "adr-demo-hub", resourceId="/s/hub/adr-demo-hub", identityType="SystemAssigned"),
    item("roles-hub-adr-demo-hub", "role", "/s/hub/adr-demo-hub", targetScope="/s/hub/adr-demo-hub"),
    item("skip-software-updates", "skip", "software-updates", "Satisfied"),
    item("namespace-status", "check"),
)


def run(fake, prompter, engine, mocker, *, width=80, **kwargs):
    mocker.patch.object(guided, "NamespaceWorkflow", engine)
    mocker.patch.object(guided, "no_echo", MagicMock())
    out = screen(width)
    persist = kwargs.pop("persist", MagicMock(side_effect=lambda result: result.update(receipt="/tmp/r.json")))
    result = guided.run_guided_setup(
        fake, SUB, screen=out, prompter=prompter, persist=persist, arguments=kwargs.pop("arguments", {}), **kwargs,
    )
    return result, plain(out.stream.getvalue()), out.stream.getvalue(), persist


# --------------------------------------------------------------------------------------------
# Default resource rules and pure helpers
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("namespace", ["a", "adr-demo", "Plant_7.Line", "a" * 63, "x" + "-" * 61 + "y", "9" * 63])
def test_derived_names_are_always_valid_targets(namespace):
    for kind in ("dps", "hub", "software-updates"):
        name = guided.derive_name(namespace, kind)
        assert guided.TARGET_NAME.fullmatch(name) and len(name) >= 3, name
        if kind in guided.NAME_LIMITS:
            assert not guided.target_name_error(name, kind), name
        assert len(name) <= guided.DERIVED_NAME_CAPS[kind]
        assert name.endswith("-" + guided.NAME_SUFFIX[kind])
    assert len(guided.derive_name("a" * 63, "hub")) == 50
    assert guided.derive_name("Plant_7.Line", "dps") == "plant-7-line-dps"
    assert guided.derive_name("___", "software-updates") == "adr-su"


def test_target_name_errors():
    assert "3–50" in guided.target_name_error("ab", "hub")
    assert guided.target_name_error("-bad", "dps")
    assert guided.target_name_error("a" * 51, "hub")
    assert not guided.target_name_error("a" * 64, "dps")


def test_equivalent_command_reproduces_config_or_declines():
    config = load_config({
        "schemaVersion": 1, "subscriptionId": SUB,
        "namespace": {"name": "ns", "resourceGroup": "my rg", "location": "eastus", "tags": {"b": "2", "a": "x y"},
                      "outboundIdentity": {"type": "SystemAssigned"}},
        "links": {
            "dps": {"resourceName": "d", "identity": {"type": "SystemAssigned"}, "createIfMissing": True},
            "hubs": [{"resourceName": "h", "identity": {"type": "SystemAssigned"}}],
            "softwareUpdates": {"resourceName": "su", "identity": {"type": "SystemAssigned"}, "createIfMissing": True},
        },
    })
    lines = guided.equivalent_command(config)
    assert lines[0] == "az iot adr ns setup -n ns -g 'my rg'"
    assert lines[1] == f"--subscription {SUB}"
    assert "--location eastus" in lines
    assert "--tags 'a=x y' b=2" in lines
    assert "--outbound-identity system-assigned" in lines
    assert any(line.startswith("--dps ") and "create-if-missing=true" in line for line in lines)
    assert any(line.startswith("--hub ") for line in lines)
    assert any(line.startswith("--su ") for line in lines)
    assert lines[-1] == "--yes"
    assert guided.equivalent_command(dict(config, cms={"enabled": True})) is None
    assert guided.equivalent_command(dict(config, checkStatus=True)) is None


def test_parse_tags():
    assert guided.parse_tags("env=dev 'team=a b'") == {"env": "dev", "team": "a b"}
    assert guided.parse_tags("  ") is None
    with pytest.raises(InvalidArgumentValueError, match="key=value"):
        guided.parse_tags("broken")
    with pytest.raises(InvalidArgumentValueError):
        guided.parse_tags("=value")


def test_termination_kind_follows_causes():
    stopped = RuntimeError("wrapped")
    stopped.__cause__ = guided.SetupStopped()
    assert guided.termination_kind(stopped) == "stopped"
    interrupted = RuntimeError("wrapped")
    interrupted.__context__ = KeyboardInterrupt()
    assert guided.termination_kind(interrupted) == "interrupted"
    suppressed = RuntimeError("wrapped")
    suppressed.__context__ = KeyboardInterrupt()
    suppressed.__suppress_context__ = True
    assert guided.termination_kind(suppressed) == "failed"
    loop = RuntimeError("loop")
    loop.__cause__ = loop
    assert guided.termination_kind(loop) == "failed"
    assert guided.termination_kind(None) == "failed"


@pytest.mark.parametrize("env, plain_mode, tty, expected", [
    ({}, False, True, True),
    ({}, True, True, False),
    ({}, False, False, False),
    ({"NO_COLOR": "1"}, False, True, False),
    ({"TERM": "dumb"}, False, True, False),
    ({"TEXTUAL_ANIMATIONS": "none"}, False, True, False),
])
def test_motion_respects_terminal_and_preferences(monkeypatch, env, plain_mode, tty, expected):
    for name in ("NO_COLOR", "TERM", "TEXTUAL_ANIMATIONS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    stream = MagicMock()
    stream.isatty.return_value = tty
    assert guided.motion_allowed(stream, plain_mode) is expected


def test_labels_and_links():
    # Only the engine's kind word is spelled out; resource names containing hub/dps stay verbatim.
    assert guided.pretty_label("Create hub ns-guided-demo-hub") == "Create IoT Hub ns-guided-demo-hub"
    assert guided.pretty_label("Create dps ns-guided-demo-dps") == "Create DPS ns-guided-demo-dps"
    assert guided.pretty_label("Validate software-updates hub-dps-su") == "Validate Software Updates hub-dps-su"
    assert guided.pretty_label("Resolve dps identity") == "Resolve DPS identity"
    assert guided.pretty_label("Wait for DPS ns-guided-demo-dps") == "Wait for DPS ns-guided-demo-dps"
    assert guided.pretty_label("Wait for ns-hub") == "Wait for ns-hub"
    assert guided.pretty_label("Validate access for dps") == "Validate access for dps"
    assert guided.pretty_label("hub") == "hub"
    namespace = {"properties": {"messaging": {"endpoints": {
        "b": {"resourceId": "/x/hubs/hub-b", "linkingState": "Linked"}, "a": "unexpected",
    }}}}
    assert guided.linked_endpoints(namespace, "hub") == [
        {"endpoint": "a", "resource": "a", "state": ""},
        {"endpoint": "b", "resource": "hub-b", "state": "Linked"},
    ]
    assert not guided.linked_endpoints(None, "dps")


def test_plan_rows_order_tags_and_roles():
    items = [
        item("cms-root"), item("namespace-status", "check"), item("roles-hub-h", "role", "/s/hub/h", targetScope="/s/hub/h"),
        item("link-hub-h", "link", "h", resourceId="/s/hub/h", userAssignedIdentity="/s/uami/id"),
        item("roles-dps-orphan", "role"), item("resource-hub-h", target="h", sku="S1"),
        item("namespace"), item("unknown", "configure"),
    ]
    ordered = [entry["id"] for entry in guided.ordered_items({"items": items})]
    assert ordered == ["namespace", "resource-hub-h", "link-hub-h", "roles-hub-h", "cms-root", "namespace-status",
                       "unknown", "roles-dps-orphan"]
    assert guided.item_detail(items[3], "ns") == "IoT Hub user-assigned managed identity id"
    assert guided.item_detail(items[3], "ns", identity=False) == ""
    assert guided.item_detail(item("link-hub-e", "link", "endpoint-x", resourceId="/s/hub/h"), "ns") == "endpoint endpoint-x"
    assert guided.item_detail(items[5], "ns") == "S1 · 1 unit"
    assert guided.item_detail(item("namespace-tags", "configure", tags={"b": 1, "a": 2}), "ns") == "a=2 b=1"
    assert guided.item_label(item("skip-hub", "skip")) == "IoT Hub:"
    assert guided.item_label(item("unknown")) == "Check:"
    roles = [line.plain for line in guided.role_lines(items[2], "ns")]
    assert roles == ["Namespace outbound managed identity → Contributor, IoT Hub Data Contributor on h",
                     "IoT Hub managed identity → Contributor on ns"]
    inbound = guided.inbound_identity("hub", items[3]["details"])
    assert inbound == "IoT Hub user-assigned managed identity id"
    assert [line.plain for line in guided.role_lines(items[2], "ns", inbound)][1] == inbound + " → Contributor on ns"
    assert guided.inbound_identity("dps", {"identityType": "SystemAssigned"}) == "DPS system-assigned managed identity"
    states = [
        ({"state": "Failed"}, "blocked"), ({"state": "Warning"}, "warning"), ({"state": "Manual"}, "manual"),
        ({"state": "Satisfied", "action": "skip"}, "skip"), ({"state": "Planned", "action": "role"}, "role"),
        ({"state": "Planned", "action": "link"}, "link"), ({"state": "Planned", "action": "other"}, "update"),
        ({"state": "Satisfied", "action": "check"}, "check"), ({"state": "Satisfied", "action": "link"}, "reuse"),
    ]
    for entry, tag in states:
        assert guided.item_tag(entry) == tag
    identity = {"id": "namespace-outbound-identity", "state": "Planned", "action": "configure"}
    assert guided.item_tag(identity) == "update"
    assert guided.item_tag(identity, new_namespace=True) == "new"
    counts = guided.plan_counts([{"state": "Planned", "action": "link"}] * 2 + [{"state": "Planned", "action": "create"}])
    assert counts == [("new", 1, "new"), ("link", 2, "links")]
    assert guided.item_kind("roles-software-updates-x") == "software-updates" and guided.item_kind("cms-root") == ""


def test_progress_reports_observed_operations_and_stops():
    progress = guided.Progress()
    assert progress.run("Create", lambda value: value + 1, 1, workflow_scope="ns", mutation=True) == 2
    with pytest.raises(ValueError):
        progress.run("Probe", _raise, handled_error=lambda error: True)
    with pytest.raises(ValueError):
        progress.run("Fail", _raise)
    events = [progress.events.get_nowait() for _ in range(6)]
    assert [event[0] for event in events] == ["start", "done", "start", "done", "start", "fail"]
    progress.stop.set()
    called = MagicMock()
    with pytest.raises(guided.SetupStopped):
        progress.run("Next", called)
    called.assert_not_called()


def test_quiet_providers_restores_console():
    from azext_iot.adr.providers.base import console

    before = console.quiet
    with guided.quiet_providers():
        assert console.quiet is True
    assert console.quiet is before


def test_no_echo_only_touches_real_terminals():
    with guided.no_echo(StringIO()):
        pass

    with patch.dict(sys.modules, {"termios": None}):  # non-POSIX console: echo is left alone
        with guided.no_echo(StringIO()):
            pass
    termios = pytest.importorskip("termios")
    pty = pytest.importorskip("pty")
    leader, follower = pty.openpty()
    try:
        stream = os.fdopen(follower, "r", closefd=False)
        with guided.no_echo(stream):
            assert not termios.tcgetattr(follower)[3] & termios.ECHO
        assert termios.tcgetattr(follower)[3] & termios.ECHO
        reader, writer = os.pipe()
        with guided.no_echo(os.fdopen(reader, "r", closefd=False)):
            pass
        os.close(reader)
        os.close(writer)
    finally:
        os.close(leader)
        os.close(follower)


# --------------------------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [80, 120, 40])
def test_screen_aligns_labels_and_wraps_long_values(width):
    out = screen(width)
    resource = "/subscriptions/" + SUB + "/resourceGroups/a-very-long-resource-group-name/providers/x/" + "y" * 60
    out.fact("Resource group:", resource, "eastus", tag="NEW", tag_style=guided.GOOD_BOLD)
    out.fact("DPS:", "dps", extra=["second line"])
    raw = out.stream.getvalue()
    lines = plain(raw).splitlines()
    assert all(cell_len(line) <= min(width, guided.MAX_WIDTH) for line in lines)
    assert lines[0].startswith("  ✓ Resource group:    /subscriptions/")
    assert resource.replace("/", "") in "".join(line.strip() for line in lines[:-2]).replace("/", "")
    assert all(line.startswith(" " * 23) for line in lines[1:-2])
    assert lines[-2].startswith("  ✓ DPS:               dps")
    assert lines[-1] == " " * 23 + "second line"
    assert "\x1b[1m/subscriptions" in raw
    assert "38;2" not in raw and "48;" not in raw and "\x1b[4m" not in raw and "\x1b[2;1m" not in raw


def test_screen_blank_lines_and_plain_mode():
    out = screen(plain_mode=True)
    out.blank()
    out.print(guided.Text("x"))
    out.blank()
    out.blank()
    out.note("note", timing="1s")
    out.warn("warn")
    out.error("bad")
    out.command(["az one", "--yes"], "Run:")
    text = out.stream.getvalue()
    assert "\x1b" not in text
    assert text.startswith("x\n\n")
    assert "  ↺ note  1s" in text and "  ! warn" in text and "  ✗ bad" in text
    assert "    az one \\\n      --yes" in text
    with out.activity("Reading"):
        pass
    assert out.stream.getvalue().endswith("Reading…\n")
    out.status("ignored")
    assert not out._status


class Tty(StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("colors", [True, False])
def test_screen_transient_status_line_is_cleared(monkeypatch, colors):
    monkeypatch.delenv("NO_COLOR", raising=False)
    if not colors:
        monkeypatch.setenv("NO_COLOR", "1")
    stream = Tty()
    out = guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=60, color_system="standard"),
                        motion=False)
    out.status("x" * 100, started=guided.time.monotonic() - 3)
    written = stream.getvalue()
    assert written.startswith("\r\x1b[2K  ")
    assert "…" in written and "s" not in written.replace("x", "").split("…")[-1]  # no timer without motion
    assert ("\x1b[1;34m" in written) is colors  # the still mark in the terminal's own blue
    assert "38;2" not in written
    out.print("after")
    assert "\r\x1b[2K" in stream.getvalue()[len(written):]
    assert not out._status


def test_screen_activity_animates_only_real_work(monkeypatch):
    stream = Tty()
    out = guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=80), motion=True)
    seen = threading.Event()
    original = out.status

    def status(*args):
        original(*args)
        if stream.getvalue().count("Reading") > 1:
            seen.set()

    monkeypatch.setattr(out, "status", status)
    with out.activity("Reading"):
        assert seen.wait(2)
    assert stream.getvalue().endswith("\r\x1b[2K")
    with pytest.raises(RuntimeError):
        with out.activity("Failing"):
            raise RuntimeError("read failed")
    assert stream.getvalue().endswith("\r\x1b[2K")


def test_default_screen_uses_stderr_and_respects_plain(monkeypatch):
    stream = StringIO()
    monkeypatch.setattr(guided.sys, "stderr", stream)
    out = guided.Screen(plain=True)
    assert out.stream is stream and not out.live and not out.motion
    assert out.width >= 40


# --------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------


ROWS = [guided.Row(f"id-{index}", f"name-{index}", f"detail {index}") for index in range(8)]


def test_picker_filters_highlights_and_scrolls():
    picker = guided.Picker(ROWS, default="id-2")
    assert picker.current().value == "id-2"
    picker.move(-1)
    picker.move(1)
    picker.move(1)
    assert picker.current().value == "id-3"
    for _ in range(5):
        picker.move(1)
    assert picker.current().value == "id-0" and picker.top == 0
    picker.move(-1)
    assert picker.current().value == "id-7" and picker.top == 2
    picker.set_text("me-1")
    assert [row.title for row in picker.visible()] == ["name-1"]
    picker.set_text("name-1")
    assert picker.accept() == "id-1"
    creating = guided.Picker(ROWS, create="created in rg", text="name")
    assert creating.visible()[0].tag == "NEW"
    assert creating.accept() == "name"
    assert creating.completion() == "name-0"
    creating.move(1)
    assert creating.completion() == "name-0"
    empty = guided.Picker([], default="fallback")
    empty.move(1)
    assert empty.current() is None and empty.accept() == "fallback"
    empty.set_text("typed")
    assert empty.accept() == "typed" and empty.completion() is None
    none = guided.Picker(ROWS)
    none.move(-1)
    assert none.current().value == "id-7"
    assert guided.Picker([]).accept() is None


def test_list_fragments_are_bounded_and_marked():
    picker = guided.Picker(ROWS, text="name")
    text = "".join(fragment for _, fragment in guided.list_fragments(picker, 40))
    assert text.count("\n") == guided.LIST_ROWS
    assert "❯ name-0" in text
    assert "1–6 of 8 · type to filter" in text
    styles = {style for style, _ in guided.list_fragments(guided.Picker(ROWS, text="ame-3"), 120)}
    assert {"class:pointer", "class:selected-match", "class:selected-detail"} <= styles
    assert "class:detail" in {style for style, _ in guided.list_fragments(guided.Picker(ROWS), 120)}
    wide = "".join(fragment for _, fragment in guided.list_fragments(guided.Picker(
        [guided.Row("a", "a", "d" * 200, "NEW")]), 60))
    assert wide.endswith("…") and "NEW" in wide and "\n" not in wide
    assert not guided.list_fragments(guided.Picker([], text="x"), 80)
    choices = [guided.Row(f"c{index}", f"choice {index}") for index in range(16)]
    shown = "".join(fragment for _, fragment in guided.list_fragments(guided.Picker(choices, filterable=False), 80))
    assert shown.count("choice") == guided.CHOICE_ROWS and shown.endswith("1–14 of 16 · ↑↓ for more")
    narrow = "".join(fragment for _, fragment in guided.list_fragments(guided.Picker(ROWS[:1]), 20))
    assert narrow == "      name-0"  # nothing preselected without a default; no room for details


def test_hint_fragments():
    text = "".join(fragment for _, fragment in guided._hint_fragments([("enter", "accept"), ("", "type"), ("esc", "")]))
    assert text == "    enter accept · type · esc"


def test_command_rows_pack_words_and_keep_quoting():
    rows = guided.command_rows(["az iot adr ns setup -n ns", "--tags 'team=a b' owner=me", "--yes"], 24)
    assert rows == [(0, "az iot adr ns setup -n"), (4, "ns"), (2, "--tags 'team=a b'"), (4, "owner=me"), (2, "--yes")]
    assert guided.command_rows(["--config @" + "x" * 40], 20) == [(0, "--config"), (4, "@" + "x" * 40)]


def _terminal(keys, method, *args, **kwargs):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput())
        return getattr(prompter, method)(*args, **kwargs)


def _rendered(monkeypatch, keys, method, *args, rows=24, **kwargs):
    """Render the prompt's real layout into a terminal-sized region, as prompt_toolkit does once CPR reports
    the rows below the cursor, and return the visible lines."""
    _, canvas = _canvas(monkeypatch, keys, method, *args, rows=rows, **kwargs)
    return ["".join(canvas.data_buffer[y][x].char for x in range(80)).rstrip() for y in range(rows)]


def _canvas(monkeypatch, keys, method, *args, rows=24, **kwargs):
    import prompt_toolkit.application
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen as PromptScreen, WritePosition

    apps = []
    base = prompt_toolkit.application.Application

    class Capture(base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            apps.append(self)

    monkeypatch.setattr(prompt_toolkit.application, "Application", Capture)
    try:
        _terminal(keys, method, *args, **kwargs)
    except BackRequested:  # keys ending in Esc: the state an unfinished prompt shows
        pass
    canvas = PromptScreen()
    apps[0].layout.container.write_to_screen(canvas, MouseHandlers(), WritePosition(0, 0, 80, rows), "", True, None)
    canvas.draw_all_floats()  # as prompt_toolkit's renderer does: the focus rail is a float
    return apps[0], canvas


def test_terminal_prompt_is_content_sized_not_viewport_filling(monkeypatch):
    lines = _rendered(monkeypatch, "\r", "ask", "Resource group:", ROWS[:2], default="id-1")
    assert lines[0].startswith("┃ ? Resource group:")
    assert "name-0" in lines[1] and "name-1" in lines[2]  # the list sits right under the question
    assert "enter accept" in lines[3]
    assert not any(lines[4:])  # nothing pinned to the bottom of the terminal
    # The focus rail marks exactly the active prompt's rows, in the column every prompt row leaves blank.
    assert [line[:1] for line in lines[:4]] == ["┃"] * 4

    lines = _rendered(monkeypatch, "\r", "select", "Connectivity:", ROWS[:3], default="id-0")
    assert lines[0].startswith("┃ ? Connectivity:") and "name-0" in lines[1] and "choose" in lines[4]
    assert not any(lines[5:]) and all(line.startswith("┃ ") for line in lines[:5])


def test_terminal_confirm_help_hangs_under_the_answer_and_wraps_on_words(monkeypatch):
    hint = "y adds Azure-managed certificates: root CA, intermediate CA, default policy · 30 days and more words"
    lines = _rendered(monkeypatch, "\r", "confirm", "CMS:", hint=hint)
    assert lines[0].rstrip().endswith("? CMS:               y/N") and lines[0].startswith("┃")
    help_lines = [line for line in lines[1:] if line.startswith("┃" + " " * 22) and line[1:].strip()]
    assert len(help_lines) >= 2
    assert " ".join(line[1:].strip() for line in help_lines) == hint  # every break falls between words
    assert "enter default" in lines[1 + len(help_lines)]
    assert not any(lines[2 + len(help_lines):])


def test_terminal_error_wraps_on_words(monkeypatch):
    error = "That name is taken by another IoT Hub somewhere in Azure; choose a different name and try again"
    lines = _rendered(monkeypatch, "\r", "ask", "IoT Hub name:", default="hub", error=error)
    assert lines[1].startswith("┃ ✗ That name")
    assert " ".join(line[1:].strip() for line in lines[1:3]) == "✗ " + error
    assert lines[2].startswith("┃   ") and "enter accept" in lines[3]


def test_wrapped_fragments():
    assert guided.wrapped_fragments("", "s", 80, 4) == [("", "    "), ("s", "")]
    narrow = guided.wrapped_fragments("one two three", "s", 20, 4)
    assert [text for style, text in narrow if style == "s"] == ["one two three"]
    assert [text for style, text in guided.wrapped_fragments("aaaa bbbb", "s", 13, 4)
            if style == "s"] == ["aaaa", "bbbb"]


@pytest.mark.parametrize("keys, expected", [
    ("\r", "id-1"),
    ("\x1b[B\r", "id-2"),
    ("\x0e\x0e\x10\r", "id-2"),
    ("\x1b[A\r", "id-0"),
    ("name-5\r", "id-5"),
    ("brand-new\r", "brand-new"),
    ("ame-6\t\r", "id-6"),
])
def test_terminal_prompter_ask(keys, expected):
    assert _terminal(keys, "ask", "Resource group:", ROWS, default="id-1", create="created") == expected


def test_terminal_prompter_errors_back_and_cancel():
    assert _terminal("\rvalue\r", "ask", "Approve:") == "value"
    assert _terminal("x\x7f\r\rok\r", "ask", "Name:", ROWS, error="previous") == "ok"
    with pytest.raises(BackRequested):
        _terminal("\x1b", "ask", "Name:")
    with pytest.raises(KeyboardInterrupt):
        _terminal("\x03", "ask", "Name:")
    with pytest.raises(KeyboardInterrupt):
        _terminal("\x04", "ask", "Name:")
    assert _terminal("ab\x04\r", "ask", "Name:") == "ab"
    assert _terminal("ab\t\r", "ask", "Name:") == "ab"  # nothing to complete


def test_terminal_prompter_select_and_confirm():
    rows = ROWS[:3]
    assert _terminal("\r", "select", "Connectivity:", rows, default="id-1") == "id-1"
    assert _terminal("\r", "select", "Connectivity:", rows) == "id-0"  # without a default the first row is focused
    assert _terminal("\t\r", "select", "Connectivity:", rows, default="gone") == "id-0"
    assert _terminal("3", "select", "Connectivity:", rows) == "id-2"
    assert _terminal("\x1b[B\r", "select", "Connectivity:", rows) == "id-1"
    assert _terminal("y", "confirm", "CMS:", hint="detail") is True
    assert _terminal("N", "confirm", "CMS:", default=True) is False
    assert _terminal("\r", "confirm", "CMS:", default=True) is True
    assert _terminal("\r", "confirm", "CMS:") is False
    with pytest.raises(BackRequested):
        _terminal("\x1b", "confirm", "CMS:")


def test_terminal_prompter_creates_output_for_its_stream(mocker):
    created = mocker.patch("prompt_toolkit.output.defaults.create_output", return_value="output")
    prompter = guided.TerminalPrompter(StringIO())
    assert prompter._output() == "output"
    assert prompter._output() == "output"
    created.assert_called_once_with(stdout=prompter.stream)


def _plain_prompter(*lines):
    stream = StringIO()
    feed = iter(list(lines) + [""])
    return guided.PlainPrompter(stream, reader=lambda: next(feed)), stream


def test_plain_prompter_numbers_defaults_and_commands():
    prompter, stream = _plain_prompter("\n", "2\n", "NAME-3\n", "typed\n", "\n", "9\n", "1\n")
    assert prompter.ask("Group:", ROWS[:4], default="d", error="bad", hint=[("esc", "back")]) == "d"
    assert prompter.ask("Group:", ROWS[:4]) == "id-1"
    assert prompter.ask("Group:", ROWS[:4]) == "id-3"
    assert prompter.ask("Group:", ROWS[:4]) == "typed"
    assert prompter.select("Mode:", ROWS[:2], default="id-1") == "id-1"
    assert prompter.select("Mode:", ROWS[:2]) == "id-0"
    text = stream.getvalue()
    assert "  ! bad" in text and "    1) name-0  detail 0" in text and "    esc back" in text
    assert "  Group: [d] " in text and "  Mode: [name-1] " in text
    assert "Enter a listed number. :back goes back." in text
    assert "\x1b" not in text
    for command, error in ((":back\n", BackRequested), (":edit\n", BackRequested), (":q\n", KeyboardInterrupt),
                           ("", KeyboardInterrupt)):
        prompter, _ = _plain_prompter(command)
        with pytest.raises(error):
            prompter.ask("Name:")


def test_plain_prompter_confirm():
    prompter, stream = _plain_prompter("\n", "maybe\n", "YES\n", "n\n")
    assert prompter.confirm("CMS:", default=True, hint="adds certificates") is True
    assert prompter.confirm("CMS:") is True
    assert prompter.confirm("CMS:") is False
    text = stream.getvalue()
    assert "    adds certificates" in text and "[Y/n]" in text and "[y/N]" in text and "Enter y or n" in text


def test_run_guided_setup_picks_prompter(mocker):
    setup = mocker.patch.object(guided, "GuidedSetup")
    guided.run_guided_setup("services", SUB, plain=True)
    assert isinstance(setup.call_args.kwargs["prompter"], guided.PlainPrompter)
    assert setup.call_args.kwargs["screen"].plain
    guided.run_guided_setup("services", SUB)
    assert isinstance(setup.call_args.kwargs["prompter"], guided.TerminalPrompter)


# --------------------------------------------------------------------------------------------
# Guided flows
# --------------------------------------------------------------------------------------------


def test_fresh_setup_proposes_new_dps_and_hub_and_applies(mocker):
    fake = services()
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    result, text, raw, persist = run(fake, prompter, engine, mocker)

    assert prompter.labels == ["Resource group:", "Namespace:", "Connectivity:", "IoT Hub tier:", "Software updates:",
                               "CMS:", "Approve:"]
    connectivity = prompter.calls[2]
    assert connectivity["default"] == "new"
    titles = [row.title for row in connectivity["rows"]]
    assert titles == ["New DPS and IoT Hub", "Existing DPS and IoT Hubs", "Namespace only"]
    assert connectivity["rows"][0].detail == "adr-demo-dps · adr-demo-hub · Standard tier next"
    tier = prompter.calls[3]
    assert tier["kind"] == "select" and tier["default"] == "S1"
    assert [row.value for row in tier["rows"]] == ["S1", "S2", "S3"]  # only tiers that can link to ADR
    assert prompter.calls[1]["create"] == "created in rg-demo"
    assert "y creates Device Update instance adr-demo-su" in prompter.calls[4]["hint"]

    request = engine.requests[0]
    assert request.namespace_name == "adr-demo" and request.subscription_id == SUB
    assert request.dps.create_if_missing and request.dps.endpoint_name == "adr-demo-dps"
    assert [hub.endpoint_name for hub in request.hubs] == ["adr-demo-hub"]
    assert request.hubs[0].create_if_missing and request.hubs[0].identity_type == "system-assigned"
    assert request.outbound_identity_type == "SystemAssigned"
    assert request.software_updates is None and request.cms is None
    assert len(engine.requests) == 2  # plan, then the fingerprint re-read before applying
    assert engine.applied == [engine.requests[1]]
    assert result["state"] == "Succeeded" and result["receipt"] == "/tmp/r.json"
    persist.assert_called_once_with(result)

    for expected in (
        "  ✓ Subscription:      Contoso Dev  " + SUB,
        "  ✓ Resource group:    rg-demo  eastus",
        "  ✓ Namespace:         adr-demo  NEW · eastus",
        "  ✓ DPS:               adr-demo-dps  NEW · S1 · 1 unit",
        "  ✓ IoT Hub:           adr-demo-hub  NEW · S1 · 1 unit",
        "  ✓ Software updates:  No  add later with --su",
        "  ✓ CMS:               No  certificate management off",
        "  Plan  ✦ 4 new · ⇄ 2 links",
        "  ✦ Outbound identity: system-assigned  NEW · namespace managed identity",
        "  ⇄ DPS:               adr-demo-dps  LINK · DPS system-assigned managed identity\n",
        "  ✓ Approved:          adr-demo  applying the plan above",
        "  ✓ Create namespace",
        "  ✓ Link IoT Hub main",
        "  ✓ Done:              adr-demo is set up  2 changes",
        "1 link request submitted; linking can take a few minutes.",
        "  · Receipt:           /tmp/r.json",
        "    az iot adr ns check -n adr-demo -g rg-demo \\\n      --subscription " + SUB + "\n",
        "      --dps resource-name=adr-demo-dps identity=system-assigned \\\n        create-if-missing=true \\\n",
        "  Repeat without prompts:",
    ):
        assert expected in text, expected
    assert "Read hub" not in text and "Check role" not in text  # only changes stay in scrollback
    # Healthy role checks are the engine's business: the approval view never lists them (the plan keeps them).
    assert "◇" not in text and "Contributor" not in text and "role" not in text.split("  Plan  ", 1)[1]
    assert "software-updates" not in text.split("  Plan  ", 1)[1].split("Approved:")[0]
    assert "+ Namespace:" not in text  # the scope row above the plan already says NEW
    assert "\x1b[1madr-demo-dps" in raw and "\x1b[1;32mNEW" in raw
    assert "38;2" not in raw and "48;" not in raw and "\x1b[4m" not in raw


def test_fresh_setup_with_real_engine_plan(mocker):
    fake = services()
    fake.show_namespace.return_value = None
    fake.setup_location.return_value = "eastus"
    fake.resolve_resource.side_effect = ResourceNotFoundError("missing")
    fake.target_create_command.return_value = "az create"
    fake.show_cms.return_value = None
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", True, True, KeyboardInterrupt())
    mocker.patch.object(guided, "no_echo", MagicMock())
    out = screen(120)
    assert guided.run_guided_setup(fake, SUB, screen=out, prompter=prompter, arguments={}) is None
    text = plain(out.stream.getvalue())
    assert "  ✓ Namespace:         adr-demo  NEW · eastus" in text and "+ Namespace:" not in text
    assert "  ✦ Software updates:  adr-demo-su  NEW" in text
    assert "  ✦ CMS:               Azure-managed  NEW · root · intermediate · default" in text
    assert "  ✦ IoT Hub:           adr-demo-hub  NEW · S1 · 1 unit · eastus" in text
    assert ("  ⇄ Software updates:  adr-demo-su  LINK · Device Update system-assigned managed\n"
            "                       identity\n" in text)  # long details wrap under the value column
    assert "◇" not in text and "Administrator" not in text  # role checks run, but stay out of the approval view
    assert "✦ 8 new · ⇄ 3 links\n" in text and "nothing is deleted" not in text
    assert not re.search(r"\bMI\b", text)  # identities are named in full
    assert text.rstrip().endswith("✗ Cancelled · nothing was written to Azure.")


def test_existing_resources_are_selected_deliberately(mocker):
    targets = {
        "dps": [{"id": DPS_ID, "name": "shared-dps", "location": "eastus", "sku": "S1"}, {"location": "unnamed"}],
    }
    fake = services(targets=targets)
    engine = Engine(plan(item("namespace")))
    prompter = Scripted("rg-demo", "adr-demo", "existing", DPS_ID, "/sub/x/hubs/typed-hub", HUB_ID, False, False,
                        "adr-demo")
    _, text, _, _ = run(fake, prompter, engine, mocker)
    assert prompter.labels[3:6] == ["DPS:", "IoT Hubs:", "IoT Hubs:"]  # existing IoT Hubs: the multi-select
    # Only targets in the namespace's region are offered ("unnamed" is elsewhere), from every resource group.
    assert [(row.value, row.title, row.detail) for row in prompter.calls[3]["rows"]] == [
        (DPS_ID, "shared-dps", "rg-demo · S1")]
    picker = prompter.calls[3]
    assert picker["focus_first"] and picker["hint"][0] == ("↑↓", "choose")  # the first suggestion is focused
    assert picker["action"] == guided.Row(guided.SCOPE, "Another subscription…", "now: Contoso Dev")
    assert picker["caption"](1, 1, "") == ("1 DPS in eastus · Contoso Dev · all resource groups · type to filter, "
                                           "or a resource ID")
    assert picker["caption"](0, 1, "zz") == "No DPS in eastus matches · enter checks what you typed"
    fake.list_link_targets.assert_any_call("dps", None, None)  # the namespace subscription, every resource group
    assert not prompter.calls[4]["rows"] and prompter.calls[4]["kind"] == "ask_many"
    assert prompter.calls[4]["limit"] == 10 and prompter.calls[4]["marked"] == []
    assert prompter.calls[4]["action"].value == guided.SCOPE
    caption = prompter.calls[4]["caption"]
    assert caption(0, 0, "") == ("No IoT Hub to choose in eastus · Contoso Dev · all resource groups · type a name, "
                                 "or any resource ID")
    assert "isn't an IoT Hub resource ID" in prompter.calls[5]["error"]
    assert prompter.calls[5]["initial"] == "/sub/x/hubs/typed-hub"  # the field keeps the input to correct
    request = engine.requests[0]
    assert request.dps.resource_id == DPS_ID and not request.dps.create_if_missing
    assert request.hubs[0].resource_id == HUB_ID
    assert "  ✓ DPS:               shared-dps  REUSE · eastus · S1" in text
    assert "  ✓ IoT Hub:           typed-hub  REUSE" in text


def test_existing_namespace_keeps_outbound_identity_and_accepts_typed_names(mocker):
    fake = services(namespace={"name": "adr-demo", "location": "eastus", "properties": {"provisioningState": "Succeeded"}})
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "existing", "plant-dps", "plant-hub", False, False, "adr-demo")
    _, text, _, _ = run(fake, prompter, engine, mocker)
    request = engine.requests[0]
    assert request.outbound_identity_type is None  # the namespace's working identity is reused, never replaced
    assert request.dps.resource_id.endswith("/resourceGroups/rg-demo/providers/Microsoft.Devices/provisioningServices/"
                                            "plant-dps") and not request.dps.create_if_missing
    assert request.hubs[0].resource_id.endswith("/IotHubs/plant-hub")
    assert "  ✓ Namespace:         adr-demo  REUSE" in text


def test_summary_without_receipt_links_or_repeatable_command(mocker):
    def cms_only(progress, request):
        return {"state": "Succeeded", "items": [{"id": "cms-root", "state": "Succeeded", "action": "create"}]}

    prompter = Scripted("rg-demo", "adr-demo", "none", False, True, "adr-demo")
    _, text, _, _ = run(services(), prompter, Engine(NEW_PLAN, setup=cms_only), mocker, persist=MagicMock())
    assert "  ✓ Done:              adr-demo is set up  1 changes" in text
    assert "Receipt" not in text and "link request" not in text and "Repeat without prompts" not in text
    assert "Check readiness (read-only):" in text


def test_existing_target_back_returns_to_connectivity(mocker):
    fake = services()
    engine = Engine(plan(item("namespace", state="Satisfied"), state="Succeeded"))
    prompter = Scripted("rg-demo", "adr-demo", "existing", Back, "none", False, False)
    _, text, _, _ = run(fake, prompter, engine, mocker)
    assert prompter.labels.count("Connectivity:") == 2
    assert prompter.calls[4]["default"] == "existing"
    assert engine.requests[0].dps is None and not engine.requests[0].hubs
    assert "  ✓ Connectivity:      Namespace only  link later" in text
    assert "  ✓ Up to date:        adr-demo" in text


LINKED_DPS = ARM + "Microsoft.Devices/provisioningServices/adr-demo-dps"
LINKED_HUB = ARM + "Microsoft.Devices/IotHubs/adr-demo-hub"
LINKED = {
    "name": "adr-demo", "location": "eastus", "properties": {
        "provisioningState": "Succeeded",
        "provisioning": {"endpoints": {"adr-demo-dps": {
            "resourceId": LINKED_DPS, "linkingState": "Succeeded", "inboundCallerIdentity": {"type": "SystemAssigned"}}}},
        "messaging": {"endpoints": {"main": {
            "resourceId": LINKED_HUB, "linkingState": "Succeeded",
            "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}}}},
        # Azure returned no identity for this link: setup can't express it exactly, so it is left alone.
        "updating": {"endpoints": {"adr-demo-su": {"resourceId": "/s/du/adr-demo-su"}}},
    },
}
REUSE_PLAN = plan(
    item("namespace", "reuse", state="Satisfied"),
    item("link-dps-adr-demo-dps", "reuse", "adr-demo-dps", "Satisfied", resourceId=LINKED_DPS,
         identityType="SystemAssigned"),
    item("roles-dps-adr-demo-dps", "role", LINKED_DPS, targetScope=LINKED_DPS),
    item("link-hub-main", "reuse", "main", "Satisfied", resourceId=LINKED_HUB, userAssignedIdentity=UAMI_ID),
    item("roles-hub-main", "role", LINKED_HUB, targetScope=LINKED_HUB),
)


def test_rerun_rechecks_existing_links_with_their_exact_identities(mocker):
    fake = services(namespace=LINKED)
    engine = Engine(REUSE_PLAN)
    prompter = Scripted(False, "adr-demo")
    result, text, _, persist = run(fake, prompter, engine, mocker, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"})
    assert prompter.labels == ["CMS:", "Approve:"]  # links are re-checked and role access is part of the plan
    request = engine.requests[0]
    assert request.dps.endpoint_name == "adr-demo-dps" and request.dps.resource_id == LINKED_DPS
    assert request.dps.identity_type == "system-assigned" and not request.dps.create_if_missing
    hub = request.hubs[0]  # mixed identities stay exactly as linked; no system identity is minted
    assert hub.endpoint_name == "main" and hub.resource_id == LINKED_HUB and hub.user_assigned_identity == UAMI_ID
    assert request.software_updates is None and not request.create_update_instance
    assert request.outbound_identity_type is None
    fake.namespace_outbound_principal.assert_called_once_with(LINKED)
    assert len(engine.applied) == 1 and result["state"] == "Succeeded"
    persist.assert_called_once()
    fake.list_resource_groups.assert_not_called()
    fake.list_namespaces.assert_not_called()
    for expected in (
        "  ✓ Namespace:         adr-demo  REUSE · eastus",
        "  ✓ DPS:               adr-demo-dps  LINKED · endpoint adr-demo-dps · Succeeded",
        "  ✓ IoT Hub:           adr-demo-hub  LINKED · endpoint main · Succeeded",
        "  ✓ Software updates:  adr-demo-su  LINKED · endpoint adr-demo-su",
        "  ○ DPS:               adr-demo-dps  REUSE · DPS system-assigned managed identity",
        "  ○ IoT Hub:           main  REUSE · endpoint main · IoT Hub user-assigned managed identity id",
        "  ! Software updates:  adr-demo-su  WARNING · existing link",
        "unchecked · Azure didn't report its target or identity, so setup leaves it as is · run check",
        "○ 3 reuse · ! 1 unchecked",
        "--hub endpoint=main \\ resource-id=" + LINKED_HUB + " \\ identity=" + UAMI_ID,
    ):
        assert flat(expected) in flat(joined(text)), expected


def test_existing_link_config_is_exact_or_none():
    system = {"resourceId": LINKED_DPS, "inboundCallerIdentity": {"type": "SystemAssigned"}}
    assert guided.existing_link_config("dps", "e", system) == {
        "endpointName": "e", "resourceId": LINKED_DPS, "identity": {"type": "SystemAssigned"}}
    user = {"resource_id": LINKED_HUB, "inbound_caller_identity": {"type": "UserAssigned", "user_assigned_identity": UAMI_ID}}
    assert guided.existing_link_config("hub", "h", user)["identity"] == {
        "type": "UserAssigned", "userAssignedResourceId": UAMI_ID}
    assert guided.existing_link_config("hub", "h", {"resourceId": LINKED_HUB}) is None
    assert guided.existing_link_config("hub", "h", {"resourceId": LINKED_HUB, "inboundCallerIdentity": {
        "type": "UserAssigned"}}) is None
    assert guided.existing_link_config("dps", "e", dict(system, resourceId=LINKED_HUB)) is None
    assert guided.existing_link_config("dps", "e", "unexpected") is None


def test_failed_existing_link_blocks_with_the_real_engine(mocker):
    namespace = deepcopy(LINKED)
    del namespace["properties"]["updating"]
    namespace["properties"]["provisioning"]["endpoints"]["adr-demo-dps"]["linkingState"] = "Failed"
    namespace["identity"] = {"type": "SystemAssigned", "principalId": "p"}
    fake = services(namespace=namespace)
    fake.resolve_resource.side_effect = lambda endpoint: {"id": endpoint.resource_id, "name": endpoint.endpoint_name}
    fake.show_cms.return_value = None
    prompter = Scripted(False, False, "quit")
    mocker.patch.object(guided, "no_echo", MagicMock())
    out = screen(120)
    assert guided.run_guided_setup(fake, SUB, screen=out, prompter=prompter, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"}) is None
    text = flat(plain(out.stream.getvalue()))
    assert "✗ DPS: adr-demo-dps BLOCKED" in text and "linkingError" in text
    assert "The plan is blocked." in text and prompter.labels == ["Software updates:", "CMS:", "Change:"]
    assert "Cancelled · nothing was written to Azure." in text


@pytest.mark.parametrize("software_updates", [True, False])
def test_hub_only_namespace_skipping_dps_still_sets_up_cms_and_software_updates(mocker, software_updates):
    """Real engine: a healthy Hub link without any DPS link must not block CMS/SU-only intent."""
    namespace = deepcopy(LINKED)
    del namespace["properties"]["provisioning"], namespace["properties"]["updating"]
    namespace["identity"] = {"type": "SystemAssigned", "principalId": "p"}
    fake = services(namespace=namespace)
    fake.resolve_resource.side_effect = ResourceNotFoundError("missing")
    fake.target_create_command.return_value = "az create"
    fake.show_cms.return_value = None
    planned = mocker.spy(guided.NamespaceWorkflow, "plan_setup")
    prompter = Scripted("none", software_updates, True, KeyboardInterrupt())
    mocker.patch.object(guided, "no_echo", MagicMock())
    out = screen(120)
    assert guided.run_guided_setup(fake, SUB, screen=out, prompter=prompter, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"}) is None
    text = flat(plain(out.stream.getvalue()))
    assert prompter.labels == ["Connectivity:", "Software updates:", "CMS:", "Approve:"]
    assert [row.title for row in prompter.calls[0]["rows"]] == ["New DPS", "Existing DPS", "Skip DPS"]
    request = planned.call_args.args[1]
    assert request.hubs == () and request.dps is None  # existing Hub left unchanged, no DPS proposed or created
    assert bool(request.software_updates) is software_updates and request.create_update_instance is software_updates
    assert request.cms is not None and request.outbound_identity_type is None
    assert "BLOCKED" not in text and "healthy existing or requested DPS link" not in text
    assert "! IoT Hub: main WARNING · existing link" in text
    assert "unchecked · needs a DPS link, so setup leaves it as is · link a DPS or run check" in text
    assert "✦ CMS: Azure-managed NEW · root · intermediate · default" in text
    assert ("✦ Software updates: adr-demo-su NEW" in text) is software_updates
    assert "resource-dps" not in text and "DPS: adr-demo-dps" not in text
    fake.create_target.assert_not_called()


@pytest.mark.parametrize("dps_state, hubs_rechecked", [("Failed", False), ("Succeeded", True)])
def test_existing_hubs_are_rechecked_only_with_a_dps(dps_state, hubs_rechecked):
    namespace = deepcopy(LINKED)
    namespace["properties"]["provisioning"]["endpoints"]["adr-demo-dps"] = {  # no identity: not expressible
        "resourceId": LINKED_DPS, "linkingState": dps_state}
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.rg, setup.namespace, setup.ns_info = "rg-demo", "adr-demo", namespace
    setup.choices = {"hub": [{"mode": "new", "name": "extra-hub"}]}
    hubs = setup.compose()["links"]["hubs"]
    new_hub = {"resourceName": "extra-hub", "identity": {"type": "SystemAssigned"}, "createIfMissing": True}
    assert hubs[-1] == new_hub  # a new Hub is still requested; the engine blocks it until a DPS is linked
    assert (len(hubs) == 2) is hubs_rechecked
    assert (("hub", "main", guided.NEEDS_DPS_LINK) in setup.unassessed) is not hubs_rechecked
    assert ("dps", "adr-demo-dps", guided.UNREADABLE_LINK) in setup.unassessed


def test_half_linked_namespace_with_unusable_outbound_identity_asks_instead_of_replacing(mocker):
    namespace = deepcopy(LINKED)
    del namespace["properties"]["messaging"]
    namespace["properties"]["provisioningState"] = "Updating"
    fake = services(namespace=namespace)
    fake.namespace_outbound_principal.side_effect = InvalidArgumentValueError("Outbound identity id is not attached.")
    engine = Engine(plan(item("namespace", "reuse", state="Satisfied")))
    prompter = Scripted("new", "S1", False, Back, "identity", "system-assigned", "back", KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, engine, mocker, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"})
    rows = prompter.calls[0]["rows"]
    assert [row.title for row in rows] == ["New IoT Hub", "Existing IoT Hubs", "Skip IoT Hub"]
    assert rows[0].detail == "adr-demo-hub · Standard tier next"
    assert prompter.labels == ["Connectivity:", "IoT Hub tier:", "CMS:", "Outbound identity:", "Change:",
                               "Outbound identity:", "Change:", "Approve:"]  # Change stays open after an edit
    assert "can't be used for links: Outbound identity id is not attached." in prompter.calls[3]["error"]
    assert "Setup never replaces an existing outbound identity on its own." in flat(text)
    assert len(engine.requests) == 1  # nothing was planned until the user decided
    request = engine.requests[0]
    assert request.outbound_identity_type == "SystemAssigned"
    assert request.dps.endpoint_name == "adr-demo-dps" and request.hubs[0].endpoint_name == "adr-demo-hub"


def test_outbound_principal_not_yet_provisioned_can_be_reread(mocker):
    from azure.cli.core.azclierror import AzureResponseError

    fake = services(namespace=LINKED)
    fake.namespace_outbound_principal.side_effect = [AzureResponseError("principalId isn't available yet."), "p"]
    engine = Engine(REUSE_PLAN)
    prompter = Scripted(False, Back, "reread", KeyboardInterrupt())
    result, text, _, _ = run(fake, prompter, engine, mocker, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"})
    assert result is None and prompter.labels == ["CMS:", "Outbound identity:", "Change:", "Approve:"]
    assert prompter.calls[2]["rows"][0].value == "reread"
    assert engine.requests[0].outbound_identity_type is None  # still the namespace's own identity
    assert "principalId isn't available yet." in flat(text)


def test_explicit_namespace_only_config_asks_nothing(mocker):
    config = load_config({"schemaVersion": 1, "namespace": {"name": "ns", "resourceGroup": "rg"}, "links": {}})
    fake = services(namespace={"name": "ns", "location": "eastus", "properties": {}})
    engine = Engine(plan(item("namespace", "reuse", "ns", "Satisfied"), item("namespace-tags", "configure", "ns")))
    prompter = Scripted("ns")
    result, text, _, _ = run(fake, prompter, engine, mocker, config=config, plan_only=False)
    assert prompter.labels == ["Approve:"]
    assert result["state"] == "Succeeded"
    request = engine.requests[0]
    assert request.dps is None and not request.hubs and request.cms is None
    assert "Connectivity" not in text and "Repeat without prompts:" in text
    fake.namespace_outbound_principal.assert_not_called()


def test_explicit_arguments_are_not_reasked(mocker):
    fake = services()
    engine = Engine(plan(item("namespace")))
    arguments = {"dps": ["resource-name=my-dps", "create-if-missing=true", "identity=system-assigned"],
                 "location": "westus2",
                 "tags": {"env": "dev"}, "namespace_outbound_identity": "system-assigned"}
    prompter = Scripted("rg-demo", "adr-demo", Back)
    prompter.answers.append("quit")
    result, text, _, _ = run(fake, prompter, engine, mocker, arguments=arguments)
    assert result is None
    assert prompter.labels == ["Resource group:", "Namespace:", "Approve:", "Change:"]
    change_rows = [row.value for row in prompter.calls[3]["rows"]]
    assert change_rows == ["back", "resource_group", "namespace", "save", "quit"]
    request = engine.requests[0]
    assert request.dps.endpoint_name == "my-dps" and request.location == "westus2" and request.tags == {"env": "dev"}
    assert "Cancelled · nothing was written to Azure." in text
    with pytest.raises(InvalidArgumentValueError, match="--hub requires identity"):
        run(fake, Scripted(), Engine(NEW_PLAN), mocker, arguments={
            "resource_group_name": "rg-demo", "namespace_name": "adr-demo", "hubs": [["resource-name=h"]]})


def test_back_navigation_and_first_question(mocker):
    fake = services()
    engine = Engine(plan(item("namespace", state="Satisfied"), state="Succeeded"))
    prompter = Scripted(Back, "rg-demo", "adr-demo", Back, "adr-two", "none", True, Back, Back, "new", "S1", False, False)
    _, text, _, _ = run(fake, prompter, engine, mocker)
    assert prompter.labels == ["Resource group:", "Resource group:", "Namespace:", "Connectivity:", "Namespace:",
                               "Connectivity:", "Software updates:", "CMS:", "Software updates:", "Connectivity:",
                               "IoT Hub tier:", "Software updates:", "CMS:"]
    assert "This is the first question · Ctrl+C cancels." in text
    assert prompter.calls[4]["default"] == "adr-demo"
    assert prompter.calls[8]["default"] is True
    assert "Namespace changed · connectivity and capabilities are asked again." in text
    assert engine.requests[0].namespace_name == "adr-two" and engine.requests[0].dps.create_if_missing


def test_change_resource_group_invalidates_dependent_answers(mocker):
    fake = services()
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", True, True, Back, "resource_group", "rg-other", "adr-demo",
                        "none", False, False, "back", "adr-demo")
    run(fake, prompter, engine, mocker)
    assert "Change:" in prompter.labels
    labels = prompter.labels[prompter.labels.index("Change:") + 1:]
    assert labels == ["Resource group:", "Namespace:", "Connectivity:", "Software updates:", "CMS:", "Change:",
                      "Approve:"]
    assert prompter.calls[prompter.labels.index("Change:") + 3]["default"] == "new"  # answers were cleared
    first, last = engine.requests[0], engine.requests[-1]
    assert first.resource_group_name == "rg-demo" and first.cms and first.software_updates
    assert last.resource_group_name == "rg-other" and last.dps is None and last.cms is None
    fake.list_namespaces.assert_any_call("rg-other")


def test_change_menu_edits_names_region_tags_identity(mocker):
    fake = services()
    engine = Engine(NEW_PLAN)
    prompter = Scripted(
        "rg-demo", "adr-demo", "new", "S1", False, False,
        Back,  # Esc on Approve opens Change; every edit below returns to it, never to approval
        "hubs", "hub:0", "change", "x", "custom-hub", "S2", "done",
        "region", "East US", "westeurope",
        "tags", "broken", "env=dev",
        "identity", "not-an-id", UAMI_ID,
        "dps", Back,  # Esc in an editor: still in Change
        "cms", Back,
        "back",  # Back to approval: Azure is read again
        Back, Back,  # Change again, then Esc from Change itself: read again even though nothing changed
        "adr-demo",
    )
    _, text, _, _ = run(fake, prompter, engine, mocker)
    labels = prompter.labels
    assert labels.count("Change:") == 8 and labels.count("Approve:") == 3
    assert [labels[index + 1] for index, label in enumerate(labels) if label == "Change:"] == [
        "IoT Hubs:", "Region:", "Tags:", "Outbound identity:", "DPS:", "CMS:", "Approve:", "Approve:"]
    assert len(engine.requests) == 4  # the first plan, both returns to approval, the re-read before applying
    request = engine.requests[-1]
    assert request.hubs[0].endpoint_name == "custom-hub" and (request.hubs[0].sku, request.hubs[0].unit) == ("S2", 1)
    assert request.dps.endpoint_name == "adr-demo-dps" and request.dps.sku is None  # Esc in the DPS editor: no change
    change = next(call for call in prompter.calls if call["label"] == "Change:")
    menu = [(row.value, row.title, row.detail) for row in change["rows"]]
    assert ("dps", "DPS", "new · adr-demo-dps · S1 · 1 unit") in menu
    assert ("hubs", "IoT Hubs", "1 new") in menu
    assert ("identity", "Outbound identity", "system-assigned when linking") in menu
    assert not [value for value, _, _ in menu if value.startswith("name-") or value == "connectivity"]
    assert request.location == "westeurope" and request.tags == {"env": "dev"}
    assert request.outbound_user_assigned_identity.endswith("/id")
    errors = [call.get("error") for call in prompter.calls if call["label"] in ("IoT Hub name:", "Region:", "Tags:",
                                                                                "Outbound identity:")]
    assert "IoT Hub names are 3–50" in errors[1]
    assert "Use a region name" in errors[3]
    assert "must use key=value" in errors[5]
    assert errors[7]
    for expected in ("  ✓ IoT Hub:           custom-hub  NEW · S2 · 1 unit",
                     "  ✓ Namespace:         adr-demo  NEW · westeurope",
                     "  ✓ Namespace:         adr-demo  NEW · westeurope · env=dev",
                     "  ✓ Outbound identity: id  namespace user-assigned managed identity",
                     "create-if-missing=true sku=S2 unit=1"):
        assert expected in text


def test_create_name_conflict_routes_to_name_edit(mocker):
    fake = services()
    conflict = InvalidArgumentValueError("IoT Hub name 'adr-demo-hub' is not available: AlreadyExists")
    engine = Engine(conflict, NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S3", False, False, "adr-demo-hub-2", "S3", "adr-demo")
    run(fake, prompter, engine, mocker)
    name_call = prompter.calls[6]  # the IoT Hub editor opens at the step that can fix it, with the problem shown
    assert name_call["label"] == "IoT Hub name:" and "not available" in name_call["error"]
    assert prompter.calls[7]["label"] == "IoT Hub tier:" and prompter.calls[7]["default"] == "S3"
    assert engine.requests[-1].hubs[0].endpoint_name == "adr-demo-hub-2" and engine.requests[-1].hubs[0].sku == "S3"


@pytest.mark.parametrize("message, field", [
    ("--dps.resource-id is not valid", "dps"),
    ("links.hubs[1].sku conflicts with the existing resource", "hub:0"),
    ("Update Instance 'adr-demo-su' is not available", "name-software-updates"),
    ("namespace.location 'mars' is not supported", "region"),
    ("unrelated", None),
])
def test_plan_error_routing(message, field):
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.namespace = "adr-demo"
    setup.choices = {"dps": {"mode": "existing", "name": "x"}, "software-updates": {"mode": "new", "name": "adr-demo-su"},
                     "hub": [{"mode": "existing", "value": "h", "name": "h"}]}
    setup.hub_slots = {1: 0}  # links.hubs[0] is a kept link; [1] is the chosen IoT Hub
    setup.software_updates = True
    assert setup.plan_error(InvalidArgumentValueError(message)) == field
    setup.choices = {}
    assert setup.plan_error(InvalidArgumentValueError("Update Instance missing")) == "name-software-updates"
    setup.explicit = True
    assert setup.plan_error(InvalidArgumentValueError("--dps.resource-id")) is None


def test_unroutable_plan_error_offers_reread_and_back(mocker):
    fake = services()
    engine = Engine(RuntimeError("throttled"), RuntimeError("still throttled"), NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "reread", Back, "adr-demo")
    _, text, _, _ = run(fake, prompter, engine, mocker)
    assert text.count("✗ throttled") == 1 and "✗ still throttled" in text
    assert [row.value for row in prompter.calls[6]["rows"]][0] == "reread"
    assert len(engine.applied) == 1


def test_plan_error_edit_back_opens_change_menu(mocker):
    fake = services()
    engine = Engine(InvalidArgumentValueError("DPS name 'adr-demo-dps' is taken"), NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, Back, Back, "back", "adr-demo")
    run(fake, prompter, engine, mocker)
    assert prompter.labels[6:9] == ["DPS name:", "DPS:", "Change:"]  # Esc steps out of the editor, then to Change
    assert prompter.calls[7]["default"] == "new"


def test_blocked_plan_offers_change_and_reread(mocker):
    blocked = plan(item("link-hub-h", "link", "h", "Blocked", resourceId="/s/hub/h") | {"message": "Hub is disabled"},
                   state="Blocked")
    engine = Engine(blocked, NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "reread", "adr-demo")
    _, text, _, _ = run(services(), prompter, engine, mocker)
    assert "  ✗ IoT Hub:           h  BLOCKED\n                       Hub is disabled" in text
    assert "  Plan  ✗ 1 blocked\n" in text
    assert "The plan is blocked." in text and "  ✗ IoT Hub: h · Hub is disabled" in text  # kept beside Change
    assert len(engine.applied) == 1


def test_wrong_approval_and_cancel_write_nothing(mocker):
    fake = services()
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr", Back, Back, KeyboardInterrupt())
    result, text, _, persist = run(fake, prompter, engine, mocker)
    assert result is None
    assert "Type adr-demo exactly to apply" in prompter.calls[7]["error"]
    assert not engine.applied
    persist.assert_not_called()
    assert "Cancelled · nothing was written to Azure." in text


def test_change_menu_quit_is_cancel():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted("quit"))
    setup.namespace, setup.rg = "ns", "rg"
    with pytest.raises(WorkflowCancelled):
        setup.change_menu()


def test_save_configuration_never_overwrites(mocker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "taken.json"
    existing.write_text("{}", encoding="utf-8")
    target = tmp_path / "setup.json"
    fake = services()
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, True, Back, "save", str(existing),
                        str(tmp_path / "missing" / "x.json"), "setup.json", Back, "save", Back, Back, KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, engine, mocker)
    errors = [call.get("error") for call in prompter.calls if call["label"] == "Save to:"]
    assert "already exists" in errors[1] and "Couldn't write" in errors[2]
    assert existing.read_text(encoding="utf-8") == "{}"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert load_config(saved)["links"]["dps"]["createIfMissing"] is True
    assert saved["cms"]["enabled"] is True
    assert "  ✓ Saved setup.json · strict setup configuration" in text
    assert "  · Rerun or automate: az iot adr ns setup --config @setup.json" in text


def test_plan_only_writes_script_and_shows_command(mocker, tmp_path):
    fake = services()
    engine = Engine(NEW_PLAN)
    write = MagicMock()
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False)
    result, text, _, _ = run(fake, prompter, engine, mocker, plan_only=True, output_script="plan.sh",
                             write_script=write)
    assert result["state"] == "Planned" and not engine.applied
    write.assert_called_once_with("plan.sh", result["items"])
    assert "  ✓ Script:            plan.sh  commands for the planned changes" in text
    assert "Plan only · nothing was written. Apply it with:" in text
    assert "      --dps resource-name=adr-demo-dps identity=system-assigned \\\n        create-if-missing=true" in text

    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, True)
    _, text, _, _ = run(fake, prompter, Engine(NEW_PLAN), mocker, plan_only=True)
    assert "Plan only · nothing was written. Save the configuration from Change to automate CMS" in flat(text)


def test_missing_scope_and_read_errors(mocker):
    fake = services(groups=[])
    fake.list_resource_groups.side_effect = RuntimeError("forbidden")
    fake.show_resource_group.side_effect = lambda name: None if name == "nope" else {"name": name}
    fake.list_namespaces.return_value = [{"location": "no name"}]
    prompter = Scripted("nope", "rg-demo", "bad name!", KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, Engine(NEW_PLAN), mocker)
    assert "Couldn't list resource groups: forbidden. Type an exact name instead." in text
    assert "Resource group 'nope' was not found in Contoso Dev" in prompter.calls[1]["error"]
    assert "Namespace names start with" in prompter.calls[3]["error"]
    assert not prompter.calls[2]["rows"]
    assert "  ✓ Resource group:    rg-demo\n" in text

    fake = services()
    fake.show_resource_group.side_effect = lambda name: None
    with pytest.raises(InvalidArgumentValueError, match="'missing' was not found"):
        run(fake, Scripted(), Engine(NEW_PLAN), mocker, arguments={"resource_group_name": "missing"})
    with pytest.raises(InvalidArgumentValueError, match="Namespace names"):
        run(services(), Scripted(), Engine(NEW_PLAN), mocker,
            arguments={"resource_group_name": "rg", "namespace_name": "-bad"})
    fake = services()
    fake.show_subscription.return_value = None
    with pytest.raises(InvalidArgumentValueError, match="--subscription"):
        run(fake, Scripted(), Engine(NEW_PLAN), mocker)


def test_reread_failure_and_changed_plan_are_reviewed_again(mocker):
    changed = deepcopy(NEW_PLAN)
    changed["items"][2]["state"] = "Satisfied"
    changed["items"][2]["action"] = "reuse"
    engine = Engine(NEW_PLAN, RuntimeError("timeout"), changed, changed)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo", "adr-demo", "adr-demo")
    result, text, _, _ = run(services(), prompter, engine, mocker)
    assert "Couldn't re-read Azure before applying: timeout" in text
    assert "Azure changed since you reviewed the plan. Review the updated plan." in text
    assert text.count("  Plan  ✦ 4 new") == 1 and "  Plan  ✦ 3 new · ⇄ 2 links · ○ 1 reuse" in text
    assert prompter.labels.count("Approve:") == 3
    assert result["state"] == "Succeeded"


def test_apply_failure_reports_partial_result(mocker):
    partial = {"state": "Failed", "namespace": "adr-demo", "items": [
        {"id": "namespace", "state": "Succeeded"}, {"id": "link", "state": "Failed", "message": "hub denied"}]}

    def fail(progress, request):
        progress.run("Create namespace", lambda: None, workflow_scope="namespace", mutation=True)
        progress.run("Link hub", lambda: (_ for _ in ()).throw(RuntimeError("hub denied")))

    def wrapped(progress, request):
        try:
            fail(progress, request)
        except RuntimeError as error:
            raise WorkflowExecutionError(error, partial) from error

    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    result, text, _, persist = run(services(), prompter, Engine(NEW_PLAN, setup=wrapped), mocker)
    assert result is not partial and result["state"] == "Failed"
    persist.assert_called_once_with(result)
    for expected in ("  ✓ Create namespace", "  ✗ Link IoT Hub", "  ✗ Failed:            adr-demo  1 changes completed",
                     "  · hub denied", "nothing was rolled back. Rerun the same setup"):
        assert flat(expected) in flat(text), expected


def test_apply_error_without_result_is_reported(mocker):
    def boom(progress, request):
        progress.observe_items([PlanItem("namespace", "create", "adr-demo", "Planned")])
        raise RuntimeError("token expired")

    persist = MagicMock(side_effect=lambda result: result.update(receiptError="disk full"))
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    result, text, _, _ = run(services(), prompter, Engine(NEW_PLAN, setup=boom), mocker, persist=persist)
    assert result["state"] == "Failed" and result["items"][-1]["message"] == "token expired"
    assert "Couldn't save the receipt: disk full" in text
    assert "Rerun the same setup" in flat(text)


def test_blocked_result_is_not_called_done(mocker):
    def blockers(progress, request):
        return {"state": "Blocked", "items": [{"id": "namespace-status", "state": "Blocked", "message": "not ready"}]}

    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    result, text, _, _ = run(services(), prompter, Engine(NEW_PLAN, setup=blockers), mocker)
    assert result["state"] == "Blocked"
    assert "  ! Blocked:           adr-demo  finished with blockers · 0 changes completed" in text
    assert "No changes were made by this attempt." in flat(text) and "Done:" not in text


def test_ctrl_c_during_apply_stops_before_next_request(mocker):
    gate = threading.Event()

    def slow(progress, request):
        progress.observe_items([PlanItem("namespace", "create", "adr-demo", "Succeeded")])
        progress.run("Create namespace", gate.wait, 5, workflow_scope="namespace", mutation=True)
        try:
            progress.run("Link hub", lambda: None)
        except guided.SetupStopped as error:
            raise WorkflowExecutionError(error, {"state": "Failed", "items": [
                {"id": "namespace", "state": "Succeeded"},
                {"id": "execution", "state": "Failed", "message": "Stopped before the next Azure request."}]}) from error

    pump = guided.GuidedSetup._pump
    calls = {"count": 0}

    def interrupting(self, progress, current):
        calls["count"] += 1
        if calls["count"] == 2:
            raise KeyboardInterrupt()
        if calls["count"] == 3:
            gate.set()
        return pump(self, progress, current)

    mocker.patch.object(guided.GuidedSetup, "_pump", interrupting)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    result, text, _, _ = run(services(), prompter, Engine(NEW_PLAN, setup=slow), mocker)
    assert result["state"] == "Stopped"
    assert result["items"][-1]["state"] == "Stopped"
    assert "Stopping after the current Azure request · Ctrl+C again stops watching." in text
    assert "  ✗ Stopped:           adr-demo  1 changes completed" in text
    assert "Submitted requests may continue in Azure; nothing was rolled back." in flat(text)


def test_second_ctrl_c_stops_watching_truthfully(mocker):
    gate = threading.Event()

    def hanging(progress, request):
        progress.observe_items([PlanItem("namespace", "create", "adr-demo", "Succeeded")])
        progress.run("Link hub main", gate.wait, 5, workflow_scope="hub", mutation=True)
        return {"state": "Succeeded", "items": []}

    pump = guided.GuidedSetup._pump
    calls = {"count": 0}

    def interrupting(self, progress, current):
        calls["count"] += 1
        if calls["count"] > 1 and current["label"]:
            raise KeyboardInterrupt()
        return pump(self, progress, current)

    mocker.patch.object(guided.GuidedSetup, "_pump", interrupting)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")
    try:
        result, text, _, persist = run(services(), prompter, Engine(NEW_PLAN, setup=hanging), mocker)
    finally:
        gate.set()
    assert result["state"] == "Stopped" and result["summary"] == {"Succeeded": 1, "Stopped": 1}
    assert "Stopped watching while 'Link hub main' was in progress" in result["items"][-1]["message"]
    persist.assert_called_once_with(result)
    assert "that request may still complete in Azure." in flat(text)
    assert guided.GuidedSetup._detached_result(
        SetupRequest("ns", "rg"), guided.Progress(), "")["items"][0]["message"].startswith("Stopped watching;")


def test_pump_shows_live_status_for_running_operation(mocker):
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    status = mocker.patch.object(setup.screen, "status")
    progress = guided.Progress()
    assert setup._pump(progress, {"label": "", "since": 0}) is False
    status.assert_not_called()  # idle: no fake activity
    current = {"label": "Create namespace", "since": 0}
    assert setup._pump(progress, current) is False
    status.assert_called_once_with("Create namespace", 0)
    progress.events.put(("done", "Wait for link", False))
    setup._pump(progress, current)
    assert "Wait for link" in plain(setup.screen.stream.getvalue())


@pytest.mark.parametrize("width", [80, 120])
def test_transcript_fits_common_terminal_sizes(mocker, width):
    long_rg = "rg-" + "manufacturing-north-europe-" * 3
    fake = services(groups=[{"name": long_rg, "location": "northeurope"}])
    namespace = "n" * 63
    engine = Engine(NEW_PLAN)
    prompter = Scripted(long_rg, namespace, "new", "S1", True, True, KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, engine, mocker, width=width)
    assert all(cell_len(line) <= min(width, guided.MAX_WIDTH) for line in text.splitlines())
    joined = text.replace("\n" + " " * 23, "")
    assert ("n" * 46 + "-hub") in joined and ("n" * 59 + "-dps") in joined and long_rg in joined
    assert engine.requests[0].hubs[0].endpoint_name == "n" * 46 + "-hub"


def test_plain_mode_transcript_has_no_ansi(mocker):
    out = screen(plain_mode=True)
    mocker.patch.object(guided, "NamespaceWorkflow", Engine(NEW_PLAN))
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, KeyboardInterrupt())
    guided.run_guided_setup(services(), SUB, screen=out, prompter=prompter, arguments={})
    text = out.stream.getvalue()
    assert "\x1b" not in text
    assert "Getting your plan ready…" in text
    assert "  ✓ DPS:               adr-demo-dps  NEW · S1 · 1 unit" in text


def test_compose_preserves_user_assigned_outbound_identity():
    identity = UAMI_ID
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted(),
                               arguments={"namespace_outbound_identity": identity})
    setup.rg, setup.namespace = "rg", "ns"
    config = setup.compose()
    assert config["namespace"]["outboundIdentity"] == {"type": "UserAssigned", "userAssignedResourceId": identity}
    assert config["links"] == {}


# --------------------------------------------------------------------------------------------
# Review regressions: truthful outcomes after approval, edits that must be honoured
# --------------------------------------------------------------------------------------------


FRESH = ("rg-demo", "adr-demo", "new", "S1", False, False, "adr-demo")


def test_interrupt_while_saving_the_receipt_keeps_the_true_result(mocker):
    persist = MagicMock(side_effect=KeyboardInterrupt())
    result, text, _, _ = run(services(), Scripted(*FRESH), Engine(NEW_PLAN), mocker, persist=persist)
    assert result["state"] == "Succeeded"
    assert result["receiptError"] == "interrupted before the receipt was saved"
    persist.assert_called_once_with(result)  # never retried: a receipt is written at most once
    assert "nothing was written" not in text
    assert "  ✓ Done:              adr-demo is set up" in text
    assert "Couldn't save the receipt: interrupted before the receipt was saved" in flat(text)

    persist = MagicMock(side_effect=lambda value: (value.update(receipt="/tmp/r.json"), (_ for _ in ()).throw(
        KeyboardInterrupt())))
    result, _, _, _ = run(services(), Scripted(*FRESH), Engine(NEW_PLAN), mocker, persist=persist)
    assert result["receipt"] == "/tmp/r.json" and "receiptError" not in result


def test_interrupt_during_the_summary_still_returns_the_result(mocker):
    mocker.patch.object(guided.GuidedSetup, "summary", side_effect=KeyboardInterrupt())
    result, text, _, persist = run(services(), Scripted(*FRESH), Engine(NEW_PLAN), mocker)
    assert result["state"] == "Succeeded" and result["receipt"] == "/tmp/r.json"
    persist.assert_called_once_with(result)
    assert "Cancelled" not in text


def test_interrupt_while_finishing_does_not_change_the_outcome(mocker):
    armed = threading.Event()

    def failing(progress, request):
        armed.set()
        raise RuntimeError("hub denied")

    clear, convert = guided.Screen.clear_status, guided.GuidedSetup._failed_result
    calls = {"clear": 0, "convert": 0}

    def flaky_clear(self):
        if armed.is_set() and not calls["clear"]:
            calls["clear"] += 1
            raise KeyboardInterrupt()
        return clear(self)

    def flaky_convert(self, *args):
        calls["convert"] += 1
        if calls["convert"] == 1:
            raise KeyboardInterrupt()
        return convert(self, *args)

    mocker.patch.object(guided.Screen, "clear_status", flaky_clear)
    mocker.patch.object(guided.GuidedSetup, "_failed_result", flaky_convert)
    result, text, _, persist = run(services(), Scripted(*FRESH), Engine(NEW_PLAN, setup=failing), mocker)
    assert calls == {"clear": 1, "convert": 2}
    assert result["state"] == "Failed" and result["items"][-1]["message"] == "hub denied"
    persist.assert_called_once_with(result)
    assert "  ✗ Failed:            adr-demo" in text and "Cancelled" not in text


def test_interrupt_on_the_stopping_notice_stops_watching(mocker):
    gate = threading.Event()

    def hanging(progress, request):
        progress.run("Create namespace adr-demo", gate.wait, 5, workflow_scope="namespace", mutation=True)
        return {"state": "Succeeded", "items": []}

    pump = guided.GuidedSetup._pump

    def interrupting(self, progress, current):
        if current["label"]:
            raise KeyboardInterrupt()
        return pump(self, progress, current)

    mocker.patch.object(guided.GuidedSetup, "_pump", interrupting)
    mocker.patch.object(guided.Screen, "warn", side_effect=KeyboardInterrupt())
    try:
        result, text, _, persist = run(services(), Scripted(*FRESH), Engine(NEW_PLAN, setup=hanging), mocker)
    finally:
        gate.set()
    assert result["state"] == "Stopped"
    assert "Stopped watching while 'Create namespace adr-demo' was in progress" in result["items"][-1]["message"]
    persist.assert_called_once_with(result)
    assert "nothing was written" not in text


def test_interrupt_while_cancelling_still_cancels(mocker):
    mocker.patch.object(guided.Screen, "clear_status", side_effect=KeyboardInterrupt())
    result, _, _, persist = run(services(), Scripted(KeyboardInterrupt()), Engine(NEW_PLAN), mocker)
    assert result is None
    persist.assert_not_called()


def test_stop_during_readiness_check_is_stopped_not_blocked(mocker):
    from azext_iot.adr.workflows.namespace import NamespaceWorkflow

    progress = guided.Progress()
    fake = services(namespace=LINKED)

    def read_then_stop(name, group):
        progress.stop.set()  # Ctrl+C lands while the namespace read is in flight
        return LINKED

    fake.show_namespace.side_effect = read_then_stop
    with pytest.raises(guided.SetupStopped):  # broad readiness handlers no longer record it as Blocked
        NamespaceWorkflow(fake, progress=progress).check("adr-demo", "rg-demo")
    fake.namespace_outbound_principal.assert_not_called()

    progress = guided.Progress()
    fake.show_namespace.side_effect = read_then_stop
    workflow = NamespaceWorkflow(fake, progress=progress)
    request = SetupRequest("adr-demo", "rg-demo", check_status=True)
    done = PlanItem("namespace", "create", "adr-demo", "Succeeded")
    mocker.patch.object(workflow, "plan_setup", return_value=({}, []))
    mocker.patch.object(workflow, "_apply_setup", side_effect=lambda request, items: (
        items.append(done), workflow._append_status_check(request, items)))
    with pytest.raises(WorkflowExecutionError) as caught:
        workflow.setup(request)
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    result = setup._failed_result(request, progress, caught.value)
    assert result["state"] == "Stopped"
    assert [(entry["id"], entry["state"]) for entry in result["items"]] == [
        ("namespace", "Succeeded"), ("execution", "Stopped")]
    assert result["items"][-1]["message"] == "Stopped before the next Azure request."

    interrupted = WorkflowExecutionError(KeyboardInterrupt(), {"state": "Failed", "items": [
        {"id": "execution", "state": "Failed", "message": "Interrupted by user."}]})
    interrupted.__cause__ = KeyboardInterrupt()  # as the engine raises it: `raise ... from error`
    result = setup._failed_result(request, progress, interrupted)
    assert result["state"] == "Stopped" and result["items"][0] == {
        "id": "execution", "state": "Stopped", "message": "Interrupted by user."}


def test_warning_result_is_reported_as_warning_with_its_messages(mocker):
    def warned(progress, request):
        return {"state": "Warning", "items": [
            {"id": "namespace", "state": "Succeeded", "action": "create"},
            {"id": "link-hub-main", "state": "Succeeded", "action": "link", "message": "Link request submitted."},
            {"id": "namespace-status", "state": "Warning", "action": "check",
             "message": "Read-only readiness result: Warning."},
            {"id": "roles-hub-main", "state": "Warning", "action": "check"},
        ]}

    result, text, _, _ = run(services(), Scripted(*FRESH), Engine(NEW_PLAN, setup=warned), mocker)
    assert result["state"] == "Warning"
    for expected in ("  ! Done:              adr-demo  applied with 2 warnings · 2 changes",
                     "  ! Readiness: Read-only readiness result: Warning.", "  ! Roles: needs attention",
                     "1 link request submitted", "Check readiness (read-only):"):
        assert expected in text, expected
    assert "Failed" not in text and "is set up" not in text


def test_plan_with_only_warnings_never_claims_up_to_date(mocker):
    fake = services(namespace={"name": "adr-demo", "location": "eastus", "properties": {}})
    warning = plan(item("namespace", "reuse", state="Satisfied"),
                   item("dps-allocation-warning", "check", state="Warning") | {"message": "Allocation is uneven."},
                   state="Succeeded")
    prompter = Scripted("none", False, False)
    result, text, _, persist = run(fake, prompter, Engine(warning), mocker, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"})
    assert result["state"] == "Succeeded" and "Approve:" not in prompter.labels
    persist.assert_not_called()
    assert "  ! No changes:        adr-demo  nothing to apply · 1 item above needs attention" in text
    assert "Up to date" not in text and "already matches" not in text
    assert "Allocation is uneven." in text and "Check readiness (read-only):" in text

    two = deepcopy(warning)
    two["items"].append(item("hub-prerequisite", "check", state="Manual"))
    _, text, _, _ = run(fake, Scripted("none", False, False), Engine(two), mocker, arguments={
        "namespace_name": "adr-demo", "resource_group_name": "rg-demo"})
    assert "2 items above need attention" in text


def test_explicit_mode_identity_change_is_planned_and_saved(mocker, tmp_path):
    fake = services()
    engine = Engine(plan(item("namespace")))
    target = tmp_path / "explicit.json"
    arguments = {"dps": ["resource-name=my-dps", "create-if-missing=true", "identity=system-assigned"],
                 "location": "westus2", "tags": {"env": "dev"}}
    prompter = Scripted("rg-demo", "adr-demo", Back, "identity", UAMI_ID, "save", str(target), "back", Back, "quit")
    result, _, _, _ = run(fake, prompter, engine, mocker, arguments=arguments)
    assert result is None
    assert prompter.labels[2:] == ["Approve:", "Change:", "Outbound identity:", "Change:", "Save to:",
                                   "Change:", "Approve:", "Change:"]  # the edit and Save both stay in Change
    first, second = engine.requests
    assert first.outbound_identity_type is None
    assert second.outbound_user_assigned_identity == UAMI_ID and second.dps.endpoint_name == "my-dps"
    assert second.location == "westus2" and second.tags == {"env": "dev"}
    saved = load_config(json.loads(target.read_text(encoding="utf-8")))
    assert saved["namespace"]["outboundIdentity"] == {"type": "UserAssigned", "userAssignedResourceId": UAMI_ID}
    assert saved["links"]["dps"]["resourceId"].endswith("/provisioningServices/my-dps")
    assert saved["namespace"]["location"] == "westus2" and saved["namespace"]["tags"] == {"env": "dev"}


def test_changing_namespace_resets_interactive_region_and_tags(mocker):
    fake = services()
    existing = {"name": "existing-ns", "location": "eastus", "properties": {"provisioningState": "Succeeded"}}
    fake.show_namespace.side_effect = lambda name, group: existing if name == "existing-ns" else None
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False,
                        Back, "region", "westeurope", "tags", "env=dev", "back",
                        Back, "namespace", "existing-ns", "none", False, False, "back", KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, engine, mocker)
    assert engine.requests[-2].location == "westeurope" and engine.requests[-2].tags == {"env": "dev"}
    last = engine.requests[-1]
    assert last.namespace_name == "existing-ns" and last.location is None and last.tags is None
    assert "Namespace changed · connectivity and capabilities are asked again · region and tags reset." in flat(text)


def test_scope_change_keeps_supplied_region_and_tags():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted(),
                               arguments={"location": "westus2", "tags": {"team": "a"}})
    setup.tags = {"env": "dev"}
    setup._invalidate("Resource group changed")
    assert (setup.location, setup.tags) == ("westus2", {"team": "a"})
    assert "region and tags reset" in setup.notes[-1][0]
    setup._invalidate("Resource group changed")
    assert "reset" not in setup.notes[-1][0]


def test_software_updates_name_conflict_routes_to_instance_name(mocker):
    conflict = InvalidArgumentValueError("Device Update instance name 'adr-demo-su' is not available: AlreadyExists")
    engine = Engine(conflict, NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", True, False, " ", "adr-demo-updates",
                        Back, "software_updates", True, Back, Back, Back, KeyboardInterrupt())
    _, text, _, _ = run(services(), prompter, engine, mocker)
    names = [call for call in prompter.calls if call["label"] == "Instance name:"]
    assert names[0]["default"] == "adr-demo-su" and "not available" in names[0]["error"]
    assert names[1]["error"] == "Enter a Device Update instance name."
    assert names[2]["default"] == "adr-demo-updates"
    change = next(call for call in prompter.calls if call["label"] == "Change:")
    assert ("software_updates", "Software updates", "yes · new adr-demo-updates") in [
        (row.value, row.title, row.detail) for row in change["rows"]]  # one editor: yes/no, then the name
    assert prompter.labels[-6:] == ["Change:", "Software updates:", "Instance name:", "Software updates:", "Change:",
                                    "Approve:"]  # Esc out of the editor stays in Change; Esc there re-plans
    request = engine.requests[-1]
    assert request.software_updates.endpoint_name == "adr-demo-updates" and request.create_update_instance
    assert "  ✓ Software updates:  adr-demo-updates  NEW · Device Update instance" in text
    for typed in ("a" * 80, "ab", "Mixed_Case.name"):  # no invented service rule; Azure's check_name decides
        assert guided.target_name_error(typed, "software-updates") == ""


def test_save_reports_configuration_errors_and_stays_usable():
    from azure.cli.core.azclierror import AzureResponseError

    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.compose = MagicMock(side_effect=AzureResponseError("principalId isn't available yet."))
    assert setup.save() is None
    assert "Couldn't build the configuration: principalId isn't available yet." in flat(plain(
        setup.screen.stream.getvalue()))


def test_output_script_is_checked_before_approval_and_written_after(mocker):
    from azure.cli.core.azclierror import ArgumentUsageError

    events = []
    prompter = Scripted(*FRESH)
    engine = Engine(NEW_PLAN, setup=lambda progress, request: (events.append("apply"), succeed(progress, request))[1])
    check = MagicMock(side_effect=lambda path, items: events.append(("check", "Approve:" in prompter.labels)))
    write = MagicMock(side_effect=lambda path, items: events.append(("write", "Approve:" in prompter.labels)))
    _, text, _, _ = run(services(), prompter, engine, mocker, output_script="plan.sh", check_script=check,
                        write_script=write)
    assert events == [("check", False), ("write", True), "apply"]
    assert "  ✓ Script:            plan.sh  commands for the planned changes" in text

    check = MagicMock(side_effect=ArgumentUsageError("The plan contains operations whose final command cannot be "
                                                     "resolved yet."))
    write = MagicMock()
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", True, False, "quit")
    engine = Engine(NEW_PLAN)
    result, text, _, _ = run(services(), prompter, engine, mocker, output_script="plan.sh", check_script=check,
                             write_script=write)
    assert result is None and "Approve:" not in prompter.labels and not engine.applied
    write.assert_not_called()
    assert "--output-script: The plan contains operations whose final command cannot be resolved yet." in flat(text)
    assert prompter.calls[-1]["rows"][0].value == "reread"

    # Turning Software Updates off makes the plan scriptable; approval is asked only then.
    check = MagicMock(side_effect=[ArgumentUsageError("cannot be resolved yet"), None])
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", True, False, "software_updates", False, "reread",
                        KeyboardInterrupt())
    run(services(), prompter, Engine(NEW_PLAN), mocker, output_script="plan.sh", check_script=check,
        write_script=write)
    assert prompter.labels[-4:] == ["Change:", "Software updates:", "Change:", "Approve:"] and check.call_count == 2
    write.assert_not_called()


# --------------------------------------------------------------------------------------------
# Compact plan rows
# --------------------------------------------------------------------------------------------


def test_plan_entries_are_compact_and_never_merge_problems():
    items = guided.ordered_items(plan(
        item("namespace", location="eastus"),
        item("namespace-tags", "configure", tags={"env": "dev"}),
        item("namespace-outbound-identity", "configure", userAssignedIdentity=UAMI_ID),
        item("link-hub-h", "link", "h", resourceId="/s/hub/h", identityType="SystemAssigned"),
        item("roles-hub-h", "role", "/s/hub/h", targetScope="/s/hub/h"),
        item("link-dps-d", "link", "d", "Blocked", resourceId="/s/dps/d") | {"message": "DPS is disabled"},
        item("roles-dps-d", "role", "/s/dps/d", targetScope="/s/dps/d"),
        item("cms-root", target="root"), item("cms-intermediate", target="intermediate"),
        item("cms-policy", target="default", state="Warning") | {"message": "policy differs"},
        item("roles-software-updates-orphan", "role", "/s/du/su", targetScope="/s/du/su"),
        item("roles-hub-x", "role", "/s/hub/x", "Blocked", targetScope="/s/hub/x") | {"message": "no permission"},
        item("roles-hub-w", "role", "/s/hub/w", "Warning", targetScope="/s/hub/w") | {"message": "check roles"},
    ))
    entries = guided.plan_entries(items, "ns", new_namespace=True)
    rows = [(entry.label, entry.value, entry.detail, entry.tag) for entry in entries]
    assert ("Namespace:", "adr-demo", "eastus", "new") not in rows  # the scope row above already says NEW
    assert rows[0] == ("Tags:", "adr-demo", "env=dev", "update")
    assert rows[1] == ("Outbound identity:", "id", "namespace managed identity", "new")
    # The link says which identity it uses; its healthy role checks are not listed (the plan keeps them).
    assert rows[2] == ("IoT Hub:", "h", "IoT Hub system-assigned managed identity", "link")
    assert not entries[2].extra and not entries[2].roles
    assert rows[3] == ("DPS:", "d", "", "blocked")  # never claims a grant
    assert [line.plain for line in entries[3].extra] == ["DPS is disabled"] and not entries[3].roles
    assert rows[4] == ("CMS:", "Azure-managed", "root · intermediate", "new")
    assert rows[5] == ("CMS:", "default", "certificate policy", "warning")  # a CMS warning is never merged away
    assert entries[5].extra[0].plain == "policy differs"
    assert "su" not in [row[1] for row in rows]  # a healthy role item with no link row is hidden too
    # Role items that need attention stay, with their message and every identity, role and scope involved.
    assert rows[6] == ("Roles:", "x", "role access for the link", "blocked")
    assert [line.plain for line in entries[6].extra] == ["no permission"]
    assert [line.plain for line in entries[6].roles] == [
        "Namespace outbound managed identity → Contributor, IoT Hub Data Contributor on x",
        "IoT Hub managed identity → Contributor on ns"]  # each principal named in full
    assert rows[7][1:] == ("w", "role access for the link", "warning") and entries[7].roles
    assert len(rows) == 8
    assert guided.plan_entries(guided.ordered_items(plan(item("namespace", "configure"))), "ns")[0].label == "Namespace:"
    single = guided.plan_entries([item("cms-root", target="root")], "ns")
    assert (single[0].value, single[0].detail) == ("root", "root CA")


# --------------------------------------------------------------------------------------------
# The workspace: one block repainted in place
# --------------------------------------------------------------------------------------------


class Term:
    """A tiny terminal: enough of VT100 (cursor up, erase, CR/LF) to see what a repaint leaves behind.
    It never scrolls content away, so every line ever kept is in ``lines`` (screen plus scrollback)."""

    TOKEN = re.compile(r"(\x1b\[[0-9;?]*[A-Za-z]|\r|\n)")

    def __init__(self):
        self.lines, self.row, self.col = [""], 0, 0

    def feed(self, data):
        for token in self.TOKEN.split(data):
            if not token:
                continue
            if token == "\n":
                self.row, self.col = self.row + 1, 0
                if self.row == len(self.lines):
                    self.lines.append("")
            elif token == "\r":
                self.col = 0
            elif token.startswith("\x1b["):
                command, argument = token[-1], token[2:-1]
                if command == "A":
                    self.row = max(0, self.row - int(argument or 1))
                elif command == "J":
                    del self.lines[self.row + 1:]
                    self.lines[self.row] = self.lines[self.row][:self.col]
                elif command == "K":
                    self.lines[self.row] = "" if argument == "2" else self.lines[self.row][:self.col]
            else:
                line = self.lines[self.row].ljust(self.col)
                self.lines[self.row] = line[:self.col] + token + line[self.col + len(token):]
                self.col += len(token)

    @property
    def text(self):
        return "\n".join(self.lines)


class TermStream(Tty):
    def __init__(self, term):
        super().__init__()
        self.term = term

    def write(self, data):
        self.term.feed(data)
        return super().write(data)


def tty_screen(monkeypatch, columns=80, rows=1000, color="standard"):
    monkeypatch.setenv("TERM", "xterm-256color")
    term = Term()
    stream = TermStream(term)
    console = Console(file=stream, force_terminal=True, width=columns, color_system=color, highlight=False,
                      markup=False, emoji=False)
    out = guided.Screen(stream, console=console, motion=False)
    out.size = lambda: (columns, rows)
    return out, term


def lines(*texts):
    from rich.text import Text

    return [Text(text) for text in texts]


def test_workspace_repaints_in_place_without_growing(monkeypatch):
    out, term = tty_screen(monkeypatch)
    out.print("header")
    out.show(lines("a", "b"))
    assert term.lines == ["header", "a", "b", ""]
    before = out.stream.getvalue()
    out.show(lines("a", "b"))
    assert out.stream.getvalue() == before  # identical: nothing is written at all
    out.reserve(5)
    out.show(lines("a", "c", "d"))
    assert out.stream.getvalue()[len(before):].startswith("\x1b[2A\r\x1b[J")
    assert term.lines == ["header", "a", "c", "d", ""]
    out.show(lines("a"))
    assert term.lines == ["header", "a", ""]  # a shorter workspace leaves no stale rows below it
    out.commit()
    out.show(lines("next"))
    assert term.lines == ["header", "a", "next", ""]  # committed rows stay as ordinary scrollback
    out.print("done")
    assert term.lines == ["header", "a", "next", "done", ""]


def test_workspace_overflow_redraws_only_rows_still_on_screen(monkeypatch):
    out, _ = tty_screen(monkeypatch, rows=24)
    old = [f"row {index}" for index in range(30)]
    out.show(lines(*old))
    start = len(out.stream.getvalue())
    out.reserve(3)  # 30 + 3 rows on a 24-row terminal: the first 10 rows may be in scrollback by now
    out.show(lines(*old[:10], "changed"))
    written = out.stream.getvalue()[start:]
    assert written.startswith("\x1b[20A\r\x1b[J") and "changed" in written and "row 9" not in written
    out.show(lines(*old))
    start = len(out.stream.getvalue())
    out.reserve(3)
    out.show(lines("new top", *old[1:5]))  # unreachable rows changed: the new workspace is drawn whole, below them
    written = out.stream.getvalue()[start:]
    assert written.startswith("\x1b[20A\r\x1b[J") and "new top" in written and "row 1" in written


def test_workspace_after_a_width_change_draws_below(monkeypatch):
    out, term = tty_screen(monkeypatch)
    out.show(lines("a", "b"))
    out.size = lambda: (100, 1000)
    start = len(out.stream.getvalue())
    out.show(lines("a", "c"))
    assert out.stream.getvalue()[start:].startswith("\r\x1b[J")  # never moves into rows the terminal re-flowed
    assert term.lines == ["a", "b", "a", "c", ""]


@pytest.mark.parametrize("dumb", [True, False])
def test_workspace_is_append_only_without_a_terminal(monkeypatch, dumb):
    if dumb:
        monkeypatch.setenv("TERM", "dumb")
        stream = Tty()
        out = guided.Screen(stream, console=Console(file=stream, width=80, force_terminal=True), motion=False)
    else:
        out = screen()
    assert not out.repaint
    out.show(lines("a", "b"))
    out.show(lines("a", "c", "d"))
    out.show(lines("a", "c"))
    assert plain(out.stream.getvalue()) == "a\nb\nc\nd\n"  # only rows that changed are added, never erased
    assert "\x1b[J" not in out.stream.getvalue()


def test_screen_size_reads_the_terminal_behind_the_stream(monkeypatch):
    out = screen()
    assert out.size() == (out.console.size.width, out.console.size.height)  # StringIO has no terminal
    stream = Tty()
    stream.fileno = lambda: 7
    monkeypatch.setattr(guided.os, "get_terminal_size", lambda descriptor: os.terminal_size((132, 43)))
    assert guided.Screen(stream, console=Console(file=stream, width=80), motion=False).size() == (132, 43)


class Watching(Scripted):
    """Scripted answers that also record how many terminal lines exist when each question is asked."""

    def __init__(self, term, *answers):
        super().__init__(*answers)
        self.term = term
        self.heights = []

    def _next(self, kind, label, rows=(), **kwargs):
        self.heights.append((label, len(self.term.lines)))
        return super()._next(kind, label, rows, **kwargs)


def test_repeated_review_and_change_cycles_update_one_workspace(mocker, monkeypatch):
    mocker.patch.object(guided, "NamespaceWorkflow", Engine(NEW_PLAN))
    out, term = tty_screen(monkeypatch)
    cycles = []
    for answer in (True, False, True):
        cycles += [Back, "cms", answer, "back"]
    prompter = Watching(term, "rg-demo", "adr-demo", "new", "S1", False, False, *cycles,
                        Back, "namespace", "adr-two", "new", "S1", False, False, "back",
                        Back, "resource_group", "rg-other", "adr-two", "existing", "shared-dps", "typed-hub", False, True,
                        "back", Back, "back", KeyboardInterrupt())
    assert guided.run_guided_setup(services(), SUB, screen=out, prompter=prompter) is None
    approvals = [height for label, height in prompter.heights if label == "Approve:"]
    changes = [height for label, height in prompter.heights if label == "Change:"]
    assert len(set(approvals[:4])) == 1, approvals  # Review → Esc → Change CMS → Review never grows
    # The Change view is the answers, updated in place after each edit while Change stays open;
    # "CMS: Azure-managed …" wraps to two rows at 80 columns, "No" to one.
    first = changes[0]
    assert changes[:6] == [first, first + 1, first + 1, first, first, first + 1], changes
    text = term.text
    for label in ("Subscription:", "Resource group:", "Namespace:", "Plan  "):
        assert text.count(label) == 1, (label, text)
    assert len(set(approvals)) == 1, approvals  # nor do namespace and resource group changes
    assert "  ✓ Resource group:    rg-other  eastus" in text and "  ✓ Namespace:         adr-two  NEW" in text
    assert text.rstrip().endswith("✗ Cancelled · nothing was written to Azure.")
    assert "Namespace changed" not in text and "Resource group changed" not in text  # notes go once answered


# --------------------------------------------------------------------------------------------
# Existing DPS / IoT Hub: checked as soon as they are entered
# --------------------------------------------------------------------------------------------


def _http_error(status, message="denied"):
    from azure.core.exceptions import HttpResponseError

    error = HttpResponseError(message)
    error.status_code = status
    return error


def _choose(fake, *answers, kind="hub", namespace=None, location="eastus"):
    setup = guided.GuidedSetup(fake, SUB, screen=screen(), prompter=Scripted(*answers))
    setup.rg, setup.namespace, setup.ns_info = "rg-demo", "adr-demo", namespace
    setup.rg_info = {"name": "rg-demo", "location": location}
    return setup, setup._target_choice(kind, "existing", ask_name=False)


def test_existing_target_found_by_name_or_resource_id():
    fake = services()
    setup, choice = _choose(fake, "typed-hub")
    endpoint, resource, location = fake.validate_setup_target.call_args.args
    assert endpoint.resource_id == HUB_ID and endpoint.identity_type == "system-assigned"
    assert resource["id"] == HUB_ID and location == "eastus"
    assert choice == {"mode": "existing", "value": "typed-hub", "name": "typed-hub", "detail": "eastus · S1"}
    assert setup.prompter.calls[0]["hint"][:2] == [("↑↓", "choose"), ("enter", "check")]

    fake = services()
    fake.resolve_resource.side_effect = lambda endpoint: {"id": endpoint.resource_id, "location": "westus",
                                                          "properties": {"provisioningState": "Updating"}}
    _, choice = _choose(fake, DPS_ID, kind="dps", namespace={"location": "westus"})
    assert fake.validate_setup_target.call_args.args[2] == "westus"  # an existing namespace's own region
    assert choice["name"] == "shared-dps" and choice["detail"] == "westus · Updating"


def test_existing_target_without_a_known_region_is_only_resolved():
    fake = services()
    _, choice = _choose(fake, "typed-hub", location=None)
    fake.resolve_resource.assert_called_once()
    fake.validate_setup_target.assert_not_called()
    assert choice["detail"] == "eastus · S1"


@pytest.mark.parametrize("failure, message", [
    (ResourceNotFoundError("gone"), "IoT Hub 'typed-hub' was not found in rg-demo. Check the name, or go back"),
    ("azure-not-found", "IoT Hub 'typed-hub' was not found in rg-demo."),
    (_http_error(404, "missing"), "IoT Hub 'typed-hub' was not found in rg-demo."),
    (_http_error(403), "Access denied reading IoT Hub 'typed-hub' (403). Choose another, or ask for read access"),
    ("unauthorized", "Access denied reading IoT Hub 'typed-hub' (unauthorized)."),
    (_http_error(500, "(InternalError) boom\nCode: InternalError"), "IoT Hub 'typed-hub' can't be linked: (InternalError) boom"),
    (_http_error(500, ""), "IoT Hub 'typed-hub' can't be linked: Operation returned an invalid status"),
])
def test_existing_target_lookup_problems_stay_on_the_field(failure, message):
    from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError as AzureNotFound

    failure = {"azure-not-found": AzureNotFound("gone"), "unauthorized": ClientAuthenticationError("no token")}.get(
        failure, failure) if isinstance(failure, str) else failure
    fake = services()
    seen = []

    def resolve(endpoint):
        seen.append(endpoint.resource_id)
        if len(seen) == 1:
            raise failure
        return {"id": endpoint.resource_id, "location": "eastus"}

    fake.resolve_resource.side_effect = resolve
    setup, choice = _choose(fake, "typed-hub", "typed-hub")
    first, second = setup.prompter.calls
    assert message in second["error"] and second["initial"] == "typed-hub"  # the input is kept to correct
    assert first["error"] == "" and choice["value"] == "typed-hub" and len(seen) == 2


def test_existing_target_rejections_name_the_problem():
    fake = services()
    fake.validate_setup_target.side_effect = [InvalidArgumentValueError(
        "Cross-region linking is not supported. Namespace region is 'eastus' and hub region is 'westus'."), None]
    setup, _ = _choose(fake, "typed-hub", "other-hub")
    assert "IoT Hub 'typed-hub' can't be linked: Cross-region linking is not supported." in setup.prompter.calls[1]["error"]

    fake = services()
    setup, choice = _choose(fake, DPS_ID, "bad name", "typed-hub")
    errors = [call["error"] for call in setup.prompter.calls]
    assert errors[1] == "That isn't an IoT Hub resource ID. Type a name in rg-demo, or its full resource ID."
    assert errors[2] == "'bad name' isn't an IoT Hub name: names have no spaces or slashes."
    assert fake.resolve_resource.call_count == 1 and choice["name"] == "typed-hub"  # wrong kinds never reach Azure

    targets = {"dps": [{"id": DPS_ID, "name": "shared-dps", "location": "eastus"}]}
    fake = services(targets=targets)
    fake.resolve_resource.side_effect = [_http_error(403), {"id": DPS_ID, "location": "eastus"}]
    setup, choice = _choose(fake, DPS_ID, DPS_ID, kind="dps")
    assert setup.prompter.calls[1]["initial"] == "shared-dps"  # a picked row comes back as its name
    assert "isn't a DPS" not in setup.prompter.calls[1]["error"] and choice["detail"] == "eastus"


def test_existing_target_unexpected_errors_and_escape_propagate():
    fake = services()
    fake.resolve_resource.side_effect = RuntimeError("bug")
    with pytest.raises(RuntimeError, match="bug"):
        _choose(fake, "typed-hub")
    with pytest.raises(BackRequested):
        _choose(services(), Back)


def test_missing_existing_target_is_reported_before_review(mocker):
    fake = services()
    fake.resolve_resource.side_effect = lambda endpoint: (_ for _ in ()).throw(ResourceNotFoundError("missing")) if (
        "missing" in endpoint.resource_id) else {"id": endpoint.resource_id, "location": "eastus"}
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "existing", "missing-dps", "shared-dps", "typed-hub", False, False,
                        "adr-demo")
    run(fake, prompter, engine, mocker)
    assert prompter.labels[3:6] == ["DPS:", "DPS:", "IoT Hubs:"]
    assert "DPS 'missing-dps' was not found in rg-demo" in prompter.calls[4]["error"]
    assert engine.requests[0].dps.resource_id == DPS_ID  # only the corrected, verified target is planned


# --------------------------------------------------------------------------------------------
# Prompt sizing, notes and styles
# --------------------------------------------------------------------------------------------


def test_prompt_height_counts_every_row_a_prompt_can_use():
    hint = [("↑↓", "choose"), ("enter", "accept")]
    assert guided.prompt_height(guided.Picker([]), 80, label="Approve:", hint=hint) == 3
    assert guided.prompt_height(guided.Picker(ROWS), 80, label="Namespace:", hint=hint) == 3 + guided.LIST_ROWS + 1
    assert guided.prompt_height(guided.Picker(ROWS[:2], create="new"), 80, label="Namespace:", hint=hint) == 6
    long = guided.prompt_height(guided.Picker([]), 40, label="A much longer label:", value="v" * 60,
                                help_text="word " * 20, error="error " * 20, hint=hint * 6)
    assert long > 12


def test_terminal_prompter_reserves_its_rows():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    reserved = []
    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), reserve=reserved.append)
        assert prompter.ask("Resource group:", ROWS[:2], default="id-1") == "id-1"
    assert reserved == [guided.prompt_height(guided.Picker(ROWS[:2]), 80, label="Resource group:", value="id-1",
                                             hint=[("↑↓", "choose"), ("enter", "accept"), ("tab", "complete"),
                                                   ("esc", "back")])]


def test_filtered_out_list_leaves_no_blank_row(monkeypatch):
    lines = _rendered(monkeypatch, "zzz\r", "ask", "Resource group:", ROWS[:2])
    assert lines[0].startswith("┃ ? Resource group:") and "enter accept" in lines[1]


def test_first_question_note_and_plan_error_note_are_shown_once(mocker):
    fake = services()
    prompter = Scripted(Back, Back, KeyboardInterrupt())
    _, text, _, _ = run(fake, prompter, Engine(NEW_PLAN), mocker)
    assert text.count("This is the first question") == 1

    error = InvalidArgumentValueError("--dps.resourceId: the DPS can't be linked")
    prompter = Scripted("rg-demo", "adr-demo", "existing", "shared-dps", "typed-hub", False, False, Back, Back,
                        "reread", KeyboardInterrupt())
    _, text, _, _ = run(services(), prompter, Engine(error), mocker)
    # Routed to the DPS editor's picker (the step that can fix it), Esc to its New/Existing/None, Esc to Change;
    # re-read fails the same way, so it is routed there again.
    assert prompter.labels[-4:] == ["DPS:", "DPS:", "Change:", "DPS:"]
    assert [call["kind"] for call in prompter.calls[-4:-2]] == ["ask", "select"]
    assert "can't be linked" in prompter.calls[-4]["error"] and prompter.calls[-4]["default"] == "shared-dps"
    assert text.count("✗ --dps.resourceId: the DPS can't be linked") == 1  # once, as a note, behind the menu


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_styles_are_terminal_native():
    for palette in guided.PALETTES:
        for value in guided.prompt_style(palette).values():
            words = value.split()
            assert "bg:" not in value and "underline" not in words and "reverse" not in words and "dim" != value or (
                value == "dim")
            assert ("#" in value) is False or palette != "ansi"
        styles = guided.prompt_style(palette)
        assert styles["selected-detail"] == "noreverse"  # the focused row's detail is never dimmed
        assert "noreverse" in styles["selected"].split() and "noreverse" in styles["selected-match"].split()
        assert styles["hint"] == styles["detail"] == "dim"  # only secondary text is dim, never a name or value
        for name, style in guided.theme(palette).styles.items():
            if name.startswith("setup."):
                assert style.bgcolor is None and not style.underline and not style.reverse and not style.dim
                assert style.color.is_system_defined is (palette == "ansi"), (palette, name)


def _fresh_rich_styles():
    """Rich caches combined styles with their escape codes; a real session renders at one depth, tests at several."""
    from rich.style import Style

    for name in ("_add", "parse", "normalize"):
        getattr(Style, name).cache_clear()


def _xterm(color):
    from rich.color import Color, ColorSystem

    return "#%02x%02x%02x" % tuple(Color.parse(color).downgrade(ColorSystem.EIGHT_BIT).get_truecolor())


@pytest.mark.parametrize("background, floor", [
    ("#ffffff", 4.0), ("#000000", 4.0), ("#1e1e1e", 4.0),  # plain light/dark and the common dark editor default
    ("#282c34", 3.3), ("#002b36", 3.3), ("#fdf6e3", 3.3), ("#f5f5f5", 3.3),  # One Dark, Solarized dark/light, grey
    ("#0c0c0c", 4.0), ("#300a24", 3.3),  # Windows Terminal Campbell, Ubuntu aubergine
])
def test_rgb_palette_reads_on_light_and_dark_backgrounds_alike(background, floor):
    """One mid-luminance palette, so no background detection and no assumption of a dark terminal. Its 256-colour
    entries (xterm-256color without COLORTERM), and the bold wordmark ramp, keep at least 3:1."""
    assert guided.PALETTES["256"] is guided.PALETTES["truecolor"] and guided.GRADIENTS["256"] == guided.GRADIENTS[
        "truecolor"]
    for color in set(guided.RGB.values()):
        assert _contrast(color, background) >= floor, (color, background)
        assert _contrast(_xterm(color), background) >= 3.0, (color, _xterm(color), background)
    for color in guided.GRADIENTS["truecolor"]:
        assert _contrast(color, background) >= 3.0 and _contrast(_xterm(color), background) >= 3.0, (color, background)
    luminance = sorted(round(_luminance(color), 2) for color in guided.RGB.values())
    assert luminance[-1] - luminance[0] <= 0.02  # one cohesive set: equal lightness, hue carries the meaning


def test_wordmark_ramp_is_distinct_at_every_depth():
    ramp = guided.GRADIENTS["truecolor"]
    assert len({_xterm(color) for color in ramp}) == len(ramp)  # four visible steps even at 256 colours
    assert guided.GRADIENTS["ansi"] == ("cyan", "blue", "magenta")


@pytest.mark.parametrize("system, no_color, palette", [
    ("truecolor", False, "truecolor"), ("truecolor", True, "ansi"), ("256", False, "256"), ("standard", False, "ansi"),
])
def test_screen_picks_the_palette_the_terminal_reports(system, no_color, palette, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    _fresh_rich_styles()
    stream = Tty()
    console = Console(file=stream, force_terminal=True, width=80, color_system=system, no_color=no_color)
    out = guided.Screen(stream, console=console, motion=False)
    assert out.palette == palette
    out.fact("DPS:", "adr-demo-dps", "S1 · 1 unit", tag="NEW", tag_style=guided.GOOD_BOLD)
    raw = stream.getvalue()
    assert "48;" not in raw and "\x1b[7m" not in raw and "\x1b[4m" not in raw
    assert ("38;2;31;142;110" in raw) is (palette == "truecolor")  # jade NEW in 24-bit only when reported
    assert ("38;5;29m" in raw) is (palette == "256")  # its nearest 256-colour entry, never 24-bit codes there
    assert ("38;2;" in raw) is (palette == "truecolor")
    if no_color:
        assert "\x1b[" not in raw.replace("\x1b[1m", "").replace("\x1b[2m", "").replace("\x1b[0m", "")


def test_title_wordmark_gradient_only_with_colour():
    out = guided.Screen(Tty(), console=Console(file=Tty(), force_terminal=True, width=80, color_system="truecolor"),
                        motion=False)
    title = out.brand("Azure Device Registry")
    assert title.plain == "Azure Device Registry"
    colors = [span.style.color.triplet.hex for span in title.spans]
    assert colors[0] == "#119994" and colors[-1] == "#ca478d" and len(set(colors)) > 15  # teal → azure → rose
    assert all(span.style.bold for span in title.spans)
    ansi = guided.Screen(Tty(), console=Console(file=Tty(), force_terminal=True, width=80, color_system="standard"),
                         motion=False).brand("ADR")
    assert [span.style.color.name for span in ansi.spans] == ["cyan", "blue", "magenta"]
    bare = screen(plain_mode=True).brand("ADR")
    assert bare.plain == "ADR" and [span.style for span in bare.spans] == [guided.BOLD]
    assert guided.gradient(("#000000",), 2) == ["#000000"] * 2 and guided.gradient(("cyan", "blue"), 0) == []


def test_activity_spinner_leads_the_line_and_moves_only_with_motion(monkeypatch):
    """One animation, at the start of the line: the Braille spinner in the mark column from the very first frame,
    its colour gliding along the aurora, so the text never moves. Azure reports no progress, so there is no
    percentage, ETA or bar after the text; reduced motion and NO_COLOR keep one still glyph and no ticking timer."""
    monkeypatch.delenv("NO_COLOR", raising=False)

    def line(motion, elapsed, system="truecolor"):
        stream = Tty()
        out = guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=80, color_system=system),
                            motion=motion)
        out.status("Creating IoT Hub adr-demo-hub", started=guided.time.monotonic() - elapsed)
        return stream.getvalue()

    first = plain(line(True, 0)).strip("\r")
    assert first == "  ⠋ Creating IoT Hub adr-demo-hub"  # the spinner itself from frame one: no other glyph first
    spun = line(True, 3)
    text = plain(spun).strip("\r")
    assert re.fullmatch(r"  [⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Creating IoT Hub adr-demo-hub  3s", text) and "%" not in spun
    assert text.index("Creating") == guided.INDENT + guided.MARK  # the operation text stays where it started
    assert not any(glyph in spun for glyph in "━─•⋯…")  # no trailing bar, no dots
    still = plain(line(False, 3)).strip("\r")
    assert still == f"  {guided.STILL} Creating IoT Hub adr-demo-hub"  # reduced motion: one still glyph, no timer
    assert re.search("[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]", line(None, 3))  # a real terminal session decides motion itself
    assert "38;5;" in line(True, 3, "256") and "38;2;" not in line(True, 3, "256")
    assert "38;2;" not in line(True, 3, "standard") and "38;5;" not in line(True, 3, "standard")

    for system in ("truecolor", "256", "standard"):
        out = guided.Screen(Tty(), console=Console(file=Tty(), force_terminal=True, color_system=system), motion=True)
        cycle = [out._spinner(tick * guided.FRAME) for tick in range(round(guided.SPIN_COLOR / guided.FRAME))]
        assert [plain(frame) for frame in cycle[:10]] == list(guided.SPINNER)  # the next glyph on every frame
        assert all(re.fullmatch(r"\x1b\[1;[0-9;]+m.\x1b\[0m", frame) for frame in cycle)  # one bold, reset glyph
        colors = [re.match(r"\x1b\[1;([0-9;]+)m", frame).group(1) for frame in cycle]
        if system != "standard":
            assert len(set(colors)) > 6  # the colour glides along the aurora and back
        else:
            assert 2 <= len(set(colors)) <= 3  # the three ANSI stops
    monkeypatch.setenv("NO_COLOR", "1")
    assert plain(line(None, 3)).strip("\r") == still and "\x1b[" not in line(None, 3).replace("\x1b[2K", "")


def test_truecolor_prompt_renders_in_24_bit_and_ansi_keeps_the_terminal_depth(monkeypatch):
    import prompt_toolkit.application
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.output.color_depth import ColorDepth

    apps = []
    base = prompt_toolkit.application.Application

    class Capture(base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            apps.append(self)

    monkeypatch.setattr(prompt_toolkit.application, "Application", Capture)
    for palette in ("truecolor", "ansi", "256"):
        with create_pipe_input() as pipe:
            pipe.send_text("\r")
            prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), palette=palette)
            assert prompter.confirm("CMS:", default=False) is False
    assert apps[0].color_depth == ColorDepth.TRUE_COLOR
    assert apps[1]._color_depth is None
    assert apps[2].color_depth == ColorDepth.DEPTH_8_BIT  # xterm-256color: nearest entries, not 24-bit codes
    style = apps[0]._merged_style
    assert style.get_attrs_for_style_str("class:label").color == "2f81c9"
    assert not style.get_attrs_for_style_str("class:selected").reverse


def test_checked_dps_is_shown_while_the_hub_is_asked_and_dropped_on_back(mocker, monkeypatch):
    mocker.patch.object(guided, "NamespaceWorkflow", Engine(NEW_PLAN))
    out, term = tty_screen(monkeypatch)
    seen = {}

    class Recording(Scripted):
        def _next(self, kind, label, rows=(), **kwargs):
            seen.setdefault(label, []).append(term.text)
            return super()._next(kind, label, rows, **kwargs)

    prompter = Recording("rg-demo", "adr-demo", "existing", "shared-dps", Back, "new", "S1", False, False,
                         KeyboardInterrupt())
    guided.run_guided_setup(services(), SUB, screen=out, prompter=prompter)
    assert "  ✓ DPS:               shared-dps  REUSE · eastus · S1" in seen["IoT Hubs:"][0]
    assert "shared-dps" not in seen["Connectivity:"][1]  # Back from the IoT Hub forgets the unconfirmed DPS
    assert "  ✓ DPS:               adr-demo-dps  NEW · S1 · 1 unit" in seen["Software updates:"][0]


def test_selected_filtered_row_has_no_reverse_video_in_the_real_application_style(monkeypatch):
    """prompt_toolkit's default UI style reverses "class:selected"; the merged style the prompt really renders
    with must not, or unmatched parts of the focused row become reverse-video blocks around the matched text."""
    rows = [guided.Row(f"/s/dps/{name}", name, "eastus · S1") for name in ("shared-dps", "other-dps", "plant-dps")]
    app, canvas = _canvas(monkeypatch, "dps\r", "ask", "DPS:", rows)
    style = app._merged_style
    cells = [canvas.data_buffer[y][x] for y in range(24) for x in range(80)]
    selected = [cell for cell in cells if "class:selected" in cell.style]
    assert {cell.char for cell in selected} >= set("shared-dps")  # the focused row, matched and unmatched parts
    assert any("selected-match" in cell.style for cell in selected) and any(
        "selected-match" not in cell.style for cell in selected)
    for cell in cells:
        attrs = style.get_attrs_for_style_str(cell.style)
        assert not attrs.reverse and not attrs.bgcolor and not attrs.underline, (cell.char, cell.style)
    focused = style.get_attrs_for_style_str("class:selected")
    assert focused.bold and not focused.reverse and not focused.dim


def test_profile_lookup_cli_error_stays_on_the_field_and_the_session_continues(mocker):
    """knack's plain CLIError (not an AzCLIError) is what credential/profile lookup raises for an ARM ID in a
    subscription that isn't in the profile: it is a field error to correct, never an aborted setup."""
    from knack.util import CLIError

    other = "/subscriptions/99999999-9999-9999-9999-999999999999/resourceGroups/rg-demo/providers/" \
            "Microsoft.Devices/provisioningServices/far-dps"
    fake = services()

    def resolve(endpoint):
        if endpoint.resource_id == other:
            raise CLIError("Subscription '99999999-9999-9999-9999-999999999999' not found.\n"
                           "Check the spelling and casing and try again.")
        return {"id": endpoint.resource_id, "location": "eastus"}

    fake.resolve_resource.side_effect = resolve
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "existing", other, DPS_ID, "typed-hub", False, False, "adr-demo")
    result, _, _, _ = run(fake, prompter, engine, mocker)
    assert prompter.labels[3:6] == ["DPS:", "DPS:", "IoT Hubs:"]
    retry = prompter.calls[4]
    assert retry["error"] == ("DPS 'far-dps' can't be linked: "
                              "Subscription '99999999-9999-9999-9999-999999999999' not found.")
    assert retry["initial"] == other  # the typed ID is kept to correct
    assert engine.requests[0].dps.resource_id == DPS_ID and result["state"] == "Succeeded"


# --------------------------------------------------------------------------------------------
# Tiers, resource editors and identity wording
# --------------------------------------------------------------------------------------------


def test_hub_tier_round_trips_through_editor_save_repeat_command_and_request(mocker, tmp_path, monkeypatch):
    """The chosen tier is what is planned, saved, repeated and created — and the editor reopens on it."""
    monkeypatch.chdir(tmp_path)
    engine = Engine(NEW_PLAN)
    prompter = Scripted(
        "rg-demo", "adr-demo", "new", Back, "new", "S2", False, False,  # Back from the tier: to Connectivity
        Back, "hubs", "hub:0", "change", Back, "change", "adr-demo-hub", Back, "adr-demo-hub", "S2",  # back inside
        "done", "save", "setup.json", "back", "adr-demo",  # Save stays in Change; Back to approval re-plans
    )
    result, text, _, _ = run(services(), prompter, engine, mocker)
    tiers = [call for call in prompter.calls if call["label"] == "IoT Hub tier:"]
    assert [call["default"] for call in tiers] == ["S1", "S1", "S2", "S2"]
    assert prompter.labels[2:5] == ["Connectivity:", "IoT Hub tier:", "Connectivity:"]
    assert prompter.calls[4]["default"] == "new"
    for request in (engine.requests[0], engine.requests[-1], engine.applied[0]):
        hub = request.hubs[0]
        assert (hub.sku, hub.unit, hub.create_if_missing) == ("S2", 1, True)
        assert request.dps.sku is None and request.dps.unit is None  # DPS has one tier; nothing is chosen
    saved = load_config(json.loads((tmp_path / "setup.json").read_text(encoding="utf-8")))
    assert {key: saved["links"]["hubs"][0][key] for key in ("sku", "unit", "createIfMissing")} == {
        "sku": "S2", "unit": 1, "createIfMissing": True}
    assert "sku" not in saved["links"]["dps"]
    assert "create-if-missing=true sku=S2 unit=1" in text
    assert "  ✓ IoT Hub:           adr-demo-hub  NEW · S2 · 1 unit" in text
    assert result["state"] == "Succeeded"
    assert "S2" not in [row.value for call in prompter.calls if call["label"] in ("DPS:", "DPS name:")
                        for row in call["rows"]]


def test_dps_editor_never_offers_a_tier_and_escape_changes_nothing(mocker):
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S3", False, False,
                        Back, "dps", "new", "plant-dps",  # name only: DPS is created as S1
                        "hubs", MANAGER_ESC,  # Esc in the IoT Hubs manager: nothing changes, still in Change
                        "back", "adr-demo")
    run(services(), prompter, engine, mocker)
    assert "IoT Hub tier:" not in prompter.labels[6:]
    assert prompter.labels[7:] == ["Change:", "DPS:", "DPS name:", "Change:", "IoT Hubs:", "Change:", "Approve:"]
    request = engine.requests[-1]
    assert request.dps.endpoint_name == "plant-dps" and request.dps.sku is None
    assert (request.hubs[0].endpoint_name, request.hubs[0].sku) == ("adr-demo-hub", "S3")
    dps_rows = prompter.calls[8]["rows"]
    assert [row.value for row in dps_rows] == ["new", "existing", "none"]
    assert dps_rows[0].detail == "adr-demo-dps · S1 · 1 unit"  # the only DPS tier is shown, never asked


def test_mixed_new_dps_and_existing_hub_and_link_later_rows(mocker):
    targets = {"hub": [{"id": HUB_ID, "name": "typed-hub", "location": "eastus", "sku": "S3"}]}
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False,
                        Back, "hubs", "hub:0", "remove", "add-existing", HUB_ID, "done", "back",
                        Back, "dps", "none", "back", KeyboardInterrupt())
    run(services(targets=targets), prompter, engine, mocker)
    hub_request = engine.requests[1].hubs[0]
    assert hub_request.resource_id == HUB_ID and not hub_request.create_if_missing
    assert hub_request.sku is None and hub_request.unit is None  # the displayed S3 is information, not a resize
    assert engine.requests[1].dps.create_if_missing and engine.requests[2].dps is None
    menu = {row.value: row.detail for row in prompter.calls[-2]["rows"]}
    assert menu["hubs"] == "1 existing" and menu["dps"] == "none · link later"
    picker = next(call for call in prompter.calls if call["kind"] == "ask_many")
    assert picker["rows"][0].detail == "rg-demo · S3" and picker["limit"] == 10  # the removed draft freed its place


def test_answer_rows_name_link_later_only_beside_a_chosen_resource():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.rg, setup.namespace = "rg-demo", "adr-demo"
    setup.choices = {"dps": {"mode": "none"}, "hub": [{"mode": "existing", "value": "h", "name": "h",
                                                       "detail": "eastus · S3"}]}
    rows = [line.plain for line in setup._answer_lines()]
    assert "  ✓ DPS:               No  link later" in rows and "  ✓ IoT Hub:           h  REUSE · eastus · S3" in rows
    setup.choices = {"dps": {"mode": "none"}, "hub": []}
    assert [line.plain for line in setup._answer_lines()] == ["  ✓ Connectivity:      Namespace only  link later"]


def test_existing_resources_never_carry_a_tier_into_the_request():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.rg, setup.namespace = "rg-demo", "adr-demo"
    setup.choices = {"dps": {"mode": "existing", "value": DPS_ID, "name": "shared-dps", "detail": "eastus · S1"},
                     "hub": [{"mode": "existing", "value": "typed-hub", "name": "typed-hub", "detail": "eastus · S3"}]}
    links = setup.compose()["links"]
    assert links["dps"] == {"resourceId": DPS_ID, "identity": {"type": "SystemAssigned"}}
    assert links["hubs"] == [{"resourceName": "typed-hub", "identity": {"type": "SystemAssigned"}}]
    setup.choices["hub"] = [{"mode": "new", "name": "n-hub"}]  # a new hub without a recorded tier: engine default
    assert "sku" not in setup.compose()["links"]["hubs"][0]


def test_existing_hub_picker_marks_tiers_that_cannot_link():
    targets = {"hub": [
        {"id": HUB_ID, "name": "typed-hub", "location": "eastus", "sku": "S1", "provisioningState": "Succeeded"},
        {"id": HUB_ID + "-b", "name": "basic-hub", "location": "eastus", "sku": "B1"},
        {"id": HUB_ID + "-f", "name": "free-hub", "location": "East US", "sku": "F1", "provisioningState": "Updating"},
    ]}
    setup, _ = _choose(services(targets=targets), "typed-hub")
    rows = setup.prompter.calls[0]["rows"]
    assert [row.detail for row in rows] == ["rg-demo · S1", "rg-demo · B1: not a Standard tier",
                                            "rg-demo · F1: not a Standard tier · Updating"]  # "East US" is eastus


def test_change_menu_offers_one_editor_per_resource():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted("quit"))
    setup.rg, setup.namespace = "rg-demo", "adr-demo"
    setup.choices = {"dps": {"mode": "new", "name": "d"}, "hub": [{"mode": "new", "name": "h", "sku": "S3", "unit": 1}]}
    setup.software_updates = True
    with pytest.raises(WorkflowCancelled):
        setup.change_menu()
    rows = [(row.value, row.title, row.detail) for row in setup.prompter.calls[0]["rows"]]
    assert rows[3:6] == [("dps", "DPS", "new · d · S1 · 1 unit"), ("hubs", "IoT Hubs", "1 new"),
                         ("software_updates", "Software updates", "yes · new adr-demo-su")]
    assert [value for value, _, _ in rows].count("hubs") == 1 and "hub" not in [value for value, _, _ in rows]


def test_software_updates_editor_asks_yes_then_name_and_escape_restores():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted(True, Back, True, "my-su"))
    setup.rg, setup.namespace = "rg-demo", "adr-demo"
    setup.edit("software_updates")
    assert setup.software_updates and setup.names["software-updates"] == "my-su"
    assert setup.prompter.labels == ["Software updates:", "Instance name:", "Software updates:", "Instance name:"]
    setup.prompter = Scripted(False, Back)
    setup.edit("software_updates")
    assert not setup.software_updates
    setup.prompter = Scripted(Back)
    setup.software_updates = True
    with pytest.raises(BackRequested):
        setup.edit("software_updates")
    assert setup.software_updates and setup.names["software-updates"] == "my-su"


def test_identity_wording_never_rewrites_names_ids_or_role_names():
    """Only generated labels are spelled out: names containing 'MI' (like the earlier hub/dps progress-label bug)
    stay verbatim, and so do official role-definition names."""
    uami = ARM + "Microsoft.ManagedIdentity/userAssignedIdentities/MI"
    items = guided.ordered_items(plan(
        item("namespace-outbound-identity", "configure", userAssignedIdentity=ARM + "x/userAssignedIdentities/MI-out"),
        item("link-hub-MI-hub", "link", "MI-hub", resourceId="/s/hub/MI-hub", userAssignedIdentity=uami),
        item("roles-hub-MI-hub", "role", "/s/hub/MI-hub", targetScope="/s/hub/MI-hub"),
        item("link-dps-adr-MI-dps", "link", "adr-MI-dps", "Blocked", resourceId="/s/dps/adr-MI-dps") | {
            "message": "Missing roles: namespace outbound MI -> Contributor on DPS; DPS selected inbound MI -> "
                       "Contributor on namespace; HUB selected inbound MI -> x; SU selected inbound MI -> y; "
                       "namespace system-assigned MI -> Azure Device Registry Administrator on namespace (MI-hub)"},
    ))
    entries = guided.plan_entries(items, "MI-ns", new_namespace=True)
    assert (entries[0].value, entries[0].detail) == ("MI-out", "namespace managed identity")
    assert entries[1].value == "MI-hub" and entries[1].detail == "IoT Hub user-assigned managed identity MI"
    blocked = guided.plan_entries([item("roles-hub-MI-hub", "role", "/s/hub/MI-hub", "Blocked",
                                        targetScope="/s/hub/MI-hub")], "MI-ns")
    assert [line.plain for line in blocked[0].roles] == [
        "Namespace outbound managed identity → Contributor, IoT Hub Data Contributor on MI-hub",
        "IoT Hub managed identity → Contributor on MI-ns"]
    assert entries[2].extra[0].plain == (
        "Missing roles: namespace outbound managed identity -> Contributor on DPS; DPS managed identity -> "
        "Contributor on namespace; IoT Hub managed identity -> x; Device Update managed identity -> y; "
        "namespace system-assigned managed identity -> Azure Device Registry Administrator on namespace (MI-hub)")
    assert guided.identity_words("MI-hub MI /s/MI/x outbound MI") == "MI-hub MI /s/MI/x outbound MI"
    assert guided.pretty_label("Create hub MI-hub") == "Create IoT Hub MI-hub"
    assert guided.identity_value(uami) == ("MI", "namespace user-assigned managed identity")
    assert guided.identity_value("system-assigned") == ("system-assigned", "namespace managed identity")


def test_identity_words_reach_every_place_engine_text_is_shown(mocker):
    message = "namespace outbound MI -> Contributor on HUB is missing"
    blocked = plan(item("link-hub-h", "link", "h", "Blocked", resourceId="/s/hub/h") | {"message": message},
                   state="Blocked")
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1", False, False, "quit")
    _, text, _, _ = run(services(), prompter, Engine(blocked), mocker)
    assert "namespace outbound managed identity -> Contributor on HUB is missing" in flat(text)
    assert not re.search(r"\bMI\b", text)

    def failing(progress, request):
        raise WorkflowExecutionError("x", result={"state": "Warning", "items": [
            {"id": "link-hub-h", "state": "Warning", "action": "link", "message": message}]})

    _, text, _, _ = run(services(), Scripted(*FRESH), Engine(NEW_PLAN, setup=failing), mocker)
    assert "namespace outbound managed identity" in flat(text) and not re.search(r"\bMI\b", text)


def test_picker_caption_sits_between_question_and_list_in_the_real_layout(monkeypatch):
    def caption(shown, total, query):
        if not total:
            return ""
        return f"{total} IoT Hubs in rg-demo · type to filter, or a resource ID" if shown == total else \
            f"{shown} of {total} match"

    lines = _rendered(monkeypatch, "\r", "ask", "IoT Hub:", ROWS[:3], caption=caption, focus_first=True)
    assert lines[0].startswith("┃ ? IoT Hub:")
    assert lines[1][1:].strip() == "3 IoT Hubs in rg-demo · type to filter, or a resource ID"
    assert "name-0" in lines[2] and "name-2" in lines[4]
    assert "↑↓ for more" not in "\n".join(lines)  # every row fits: no scrolling footer
    lines = _rendered(monkeypatch, "name-1\r", "ask", "IoT Hub:", ROWS[:3], caption=caption, focus_first=True)
    assert lines[1][1:].strip() == "1 of 3 match" and "name-1" in lines[2]
    lines = _rendered(monkeypatch, "typed\r", "ask", "IoT Hub:", (), caption=caption)
    assert lines[0].startswith("┃ ? IoT Hub:") and "typed" in lines[0]
    assert "IoT Hubs" not in "\n".join(lines)  # an empty caption takes no row


def test_plain_prompter_prints_the_picker_caption():
    prompter, stream = _plain_prompter("\n")
    assert prompter.ask("IoT Hub:", ROWS[:2], default="id-0", caption=lambda shown, total, query: f"{total} hubs",
                        help="Standard tier only") == "id-0"
    assert "    2 hubs\n" in stream.getvalue() and "Standard tier only" in stream.getvalue()


def test_plan_failure_routed_to_a_question_keeps_one_problem_note_after_back():
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    setup.rg, setup.namespace = "rg-demo", "adr-demo"
    setup.edit = MagicMock(side_effect=BackRequested())
    setup.change_menu = MagicMock()
    for field in ("region", "namespace"):  # an editor field carries the error itself; a question also keeps a note
        setup.edit.reset_mock()
        setup.plan_error = MagicMock(return_value=field)
        setup._plan_failed("namespace.location is not available: HUB selected inbound MI")
        problem = ("namespace.location is not available: IoT Hub managed identity", "✗", guided.BAD_BOLD)
        assert setup.notes.count(problem) == 1
        setup.edit.assert_called_once_with(field, error=problem[0])
    assert setup.change_menu.call_args_list == [call(blocked=True)] * 2


OTHER_DPS_ID = "/subscriptions/other/resourceGroups/rg-other/providers/Microsoft.Devices/provisioningServices/far-dps"
DPS_ROWS = [guided.Row(DPS_ID, "shared-dps", "eastus"), guided.Row(DPS_ID + "-2", "second-dps", "eastus")]


def test_picker_focuses_the_first_row_only_for_an_empty_field():
    assert guided.Picker(DPS_ROWS, focus_first=True).current() == DPS_ROWS[0]
    outside = guided.Picker(DPS_ROWS, default=OTHER_DPS_ID, focus_first=True)
    assert outside.current() is None and outside.accept() == OTHER_DPS_ID  # a previous choice elsewhere is kept
    assert guided.Picker(DPS_ROWS, default="typed-dps", focus_first=True).accept() == "typed-dps"
    assert guided.Picker(DPS_ROWS, default="SECOND-dps", focus_first=True).current() == DPS_ROWS[1]
    assert guided.Picker(DPS_ROWS, default=DPS_ID.upper() + "-2", focus_first=True).current() == DPS_ROWS[1]


@pytest.mark.parametrize("default, expected", [
    (OTHER_DPS_ID, OTHER_DPS_ID),  # a resource ID in another resource group or subscription
    ("typed-dps", "typed-dps"),  # a typed name that isn't listed
    ("Second-DPS", DPS_ID + "-2"),  # the same resource, typed in another case
    ("", DPS_ID),  # nothing chosen yet: Enter takes the focused first row
])
def test_terminal_picker_enter_keeps_a_default_outside_the_list(default, expected):
    def caption(_shown, total, _query):
        return f"{total} DPS in rg-demo · type to filter, or a resource ID"

    assert _terminal("\r", "ask", "DPS:", DPS_ROWS, default=default, caption=caption, focus_first=True) == expected


def test_caption_height_uses_the_real_wrapping_for_long_scopes(monkeypatch):
    rg = "rg-" + "very-long-resource-group-name-" * 3

    def caption(shown, total, query):
        if query and not shown:
            return f"No DPS in {rg} matches · enter checks what you typed"
        return f"{total} DPS in {rg} · type to filter, or a resource ID"

    picker = guided.Picker(DPS_ROWS)
    rows = guided.caption_height(picker, caption, 80)
    assert rows == max(len(guided.wrapped_lines(caption(n, 2, q), 80, guided.CAPTION_INDENT))
                       for n, q in ((2, ""), (0, "?"))) >= 2
    assert guided.caption_height(picker, None, 80) == 0
    hint = [("↑↓", "choose"), ("enter", "check"), ("tab", "complete"), ("esc", "back")]
    reserved = guided.prompt_height(picker, 80, label="DPS:", hint=hint, caption=caption)
    assert reserved == guided.prompt_height(picker, 80, label="DPS:", hint=hint) + rows
    for keys in ("\r", "zzz\r"):  # unfiltered, and the no-match caption
        lines = _rendered(monkeypatch, keys, "ask", "DPS:", DPS_ROWS, caption=caption, focus_first=True, hint=hint,
                          default="x" if keys == "\r" else "")
        used = max(index for index, line in enumerate(lines) if line) + 1
        assert used <= reserved  # the prompt never draws below the rows it reserved
        assert any(rg[-20:] in line for line in lines) or any("very-long" in line for line in lines)


# --------------------------------------------------------------------------------------------
# Focus and the one activity animation
# --------------------------------------------------------------------------------------------


def test_one_focus_language_for_questions_rows_and_confirms(monkeypatch):
    """The active question and the focused row share one cue set (accent rail, ?, label, pointer, bold accent
    name); answered rows stay quiet but readable; nothing is dim, reversed, underlined or painted."""
    for palette in ("ansi", "truecolor"):
        style = dict(guided.prompt_style(palette))
        accent = style["rail"]
        for name in ("mark", "label", "pointer", "selected", "choice-default"):
            assert style[name].startswith(accent) and "bold" in style[name], (palette, name)
        assert "noreverse" in style["selected"] and "dim" not in style["selected"]
        assert style["name"] == "" and "dim" not in style["input"]  # unfocused names and typed text: normal ink
    rows = [guided.Row(f"r{index}", f"row-{index}", "detail") for index in range(3)]
    for method, args, kwargs in (("select", ("Change:", rows), {"default": "r1"}),
                                 ("ask", ("Resource group:", rows), {"default": "r1"}),
                                 ("ask_many", ("IoT Hubs:", rows), {"limit": 10, "marked": ["r1"]}),
                                 ("confirm", ("CMS:",), {})):
        app, canvas = _canvas(monkeypatch, "\r", method, *args, **kwargs)
        merged = app._merged_style
        text = ["".join(canvas.data_buffer[y][x].char for x in range(80)).rstrip() for y in range(24)]
        height = sum(1 for line in text if line)
        assert all(line.startswith("┃") for line in text[:height]), (method, text)  # the rail spans the prompt
        cells = {(y, x): canvas.data_buffer[y][x] for y in range(height) for x in range(80)}
        rail = merged.get_attrs_for_style_str(cells[0, 0].style)
        label = merged.get_attrs_for_style_str(cells[0, text[0].index(args[0][0])].style)
        assert rail.color == label.color and label.bold and not label.dim
        if method == "confirm":
            continue
        focused = next(y for y in range(1, height) if guided.POINTER in text[y])
        assert "row-1" in text[focused] or method == "ask_many"  # the default row is the focused one
        name = merged.get_attrs_for_style_str(cells[focused, text[focused].index("row-")].style)
        other = next(y for y in range(1, height) if "row-" in text[y] and y != focused)
        quiet = merged.get_attrs_for_style_str(cells[other, text[other].index("row-")].style)
        assert name.bold and name.color == rail.color and not name.reverse and not name.dim
        assert not quiet.bold and not quiet.dim and quiet.color != rail.color  # readable, not competing
        for cell in cells.values():
            attrs = merged.get_attrs_for_style_str(cell.style)
            assert not attrs.reverse and not attrs.underline and not attrs.bgcolor


def test_answered_rows_are_quiet_labels_with_bold_values():
    out = screen(color="truecolor")
    out.fact("Resource group:", "rg-demo", "eastus")
    raw = out.stream.getvalue()
    assert "\x1b[1m" + "rg-demo" in raw or "\x1b[1mrg-demo" in raw.replace("\x1b[0m", "")
    label = re.search(r"\x1b\[([0-9;]+)mResource group:", raw).group(1)
    assert "38;2;98;127;161" in label and not label.startswith("1;") and ";1;" not in label  # quiet, not bold
    assert "\x1b[2m" not in raw.split("rg-demo")[0] + "rg-demo"  # neither label nor value is dim


def test_one_activity_animation_for_reads_and_writes(monkeypatch):
    """Every wait (reads, checks, plan reads, writes) uses Screen.status: the same spinner from its first frame, no
    small mark that later grows and no trailing bar, and with reduced motion or without colour one still glyph that
    never changes (not even a timer), so nothing is repainted while the work lasts."""
    import inspect

    monkeypatch.delenv("NO_COLOR", raising=False)
    source = inspect.getsource(guided)
    assert not any(name in source for name in ("PULSE", "_pulse", "BUSY", "def frame("))  # old animated effects
    assert set(re.findall("[\u2800-\u28ff]", source)) == set(guided.SPINNER + guided.STILL)

    def screen_for(motion, system="truecolor"):
        stream = Tty()
        return guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=80,
                                                     color_system=system), motion=motion), stream

    out, stream = screen_for(True)
    started = guided.time.monotonic()
    glyphs = []
    for elapsed in (0, 0.09, 0.17, 1.25):
        monkeypatch.setattr(guided.time, "monotonic", lambda elapsed=elapsed: started + elapsed)
        out.status("Getting your plan ready", started=started)
        glyphs.append(plain(stream.getvalue()).split("\r")[-1])
    monkeypatch.undo()
    assert glyphs == ["  ⠋ Getting your plan ready", "  ⠙ Getting your plan ready", "  ⠹ Getting your plan ready",
                      "  ⠴ Getting your plan ready  1s"]  # one glyph, one style: the same line keeps spinning

    for motion, environment in ((False, {}), (None, {"NO_COLOR": "1"})):  # reduced motion; NO_COLOR decides itself
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        still, stream = screen_for(motion)
        started = guided.time.monotonic()
        for elapsed in (0, 1.2, 3.5, 61):  # seconds pass: the line stays exactly as first drawn
            monkeypatch.setattr(guided.time, "monotonic", lambda elapsed=elapsed: started + elapsed)
            still.status("Checking IoT Hub hub-a", started=started)
        monkeypatch.undo()
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert stream.getvalue().count("\r\x1b[2K") == 1 and plain(stream.getvalue()) == (
            f"\r  {guided.STILL} Checking IoT Hub hub-a")
    monkeypatch.setenv("NO_COLOR", "1")
    bare, stream = screen_for(None)
    bare.status("Checking IoT Hub hub-a", started=guided.time.monotonic() - 2)
    assert stream.getvalue() == f"\r\x1b[2K  {guided.STILL} Checking IoT Hub hub-a"

    # Reduced motion starts no ticker thread at all; the operation line still appears and is cleared.
    monkeypatch.setattr(guided.threading, "Thread", MagicMock(side_effect=AssertionError("no idle threads")))
    quiet, stream = screen_for(False)
    with quiet.activity("Loading IoT Hubs in rg-demo"):
        assert guided.STILL in stream.getvalue()
    assert stream.getvalue().endswith("\r\x1b[2K")


def test_apply_progress_uses_the_same_operation_line(mocker):
    setup = guided.GuidedSetup(services(), SUB, screen=screen(), prompter=Scripted())
    status = mocker.patch.object(setup.screen, "status")
    activity = mocker.patch.object(setup.screen, "activity")
    progress = guided.Progress()
    progress.events.put(("start", "Create hub adr-demo-hub", True))
    current = {"label": "", "since": 0}
    setup._pump(progress, current)
    assert status.call_args.args[0] == "Create IoT Hub adr-demo-hub"  # Screen.status: the reads' renderer
    activity.assert_not_called()


# --------------------------------------------------------------------------------------------
# The IoT Hubs collection
# --------------------------------------------------------------------------------------------


def new_hub(name, sku="S1"):
    return {"mode": "new", "name": name, "sku": sku, "unit": 1}


def old_hub(name, value=None):
    return {"mode": "existing", "value": value or name, "name": name, "detail": "eastus · S1"}


def hub_setup(*answers, namespace=None, targets=None, hubs=()):
    setup = guided.GuidedSetup(services(namespace=namespace, targets=targets), SUB, screen=screen(),
                               prompter=Scripted(*answers))
    setup.rg, setup.namespace, setup.ns_info, setup.ns_read = "rg-demo", "adr-demo", namespace, True
    setup.rg_info = {"name": "rg-demo", "location": "eastus"}
    setup.choices = {"dps": {"mode": "new", "name": "adr-demo-dps"}, "hub": [dict(hub) for hub in hubs]}
    return setup


def linked_hubs(count):
    namespace = deepcopy(LINKED)
    namespace["properties"]["messaging"]["endpoints"] = {
        f"link-{index}": {"resourceId": ARM + f"Microsoft.Devices/IotHubs/linked-{index}", "linkingState": "Succeeded",
                          "inboundCallerIdentity": {"type": "SystemAssigned"}} for index in range(count)}
    return namespace


HUB_CATALOG = {"hub": [{"id": ARM + f"Microsoft.Devices/IotHubs/plant-{index}", "name": f"plant-{index}",
                        "location": "eastus", "sku": "S1"} for index in range(12)]}


def test_derived_hub_names_are_numbered_and_still_valid():
    assert guided.derive_name("adr-demo", "hub", 1) == "adr-demo-hub"
    assert guided.derive_name("adr-demo", "hub", 10) == "adr-demo-hub-10"
    long = guided.derive_name("a" * 63, "hub", 10)
    assert len(long) <= 50 and long.endswith("-hub-10") and not guided.target_name_error(long, "hub")
    setup = hub_setup(hubs=[new_hub("adr-demo-hub"), new_hub("ADR-DEMO-HUB-2")])
    assert setup._next_hub_name(setup.choices["hub"]) == "adr-demo-hub-3"  # past every name in any letter case


def test_ten_new_hubs_each_with_a_name_and_tier_then_the_eleventh_is_explained():
    answers = ["S2"]  # the first: the derived name, its tier
    for number in range(2, 11):
        answers += ["add-new", f"adr-demo-hub-{number}", ("S1", "S2", "S3")[number % 3]]
    answers += ["add-new", "add-existing", "done"]
    setup = hub_setup(*answers)
    hubs = setup._connect_hubs("new")
    assert [hub["name"] for hub in hubs] == ["adr-demo-hub"] + [f"adr-demo-hub-{n}" for n in range(2, 11)]
    assert [hub["sku"] for hub in hubs] == ["S2"] + [("S1", "S2", "S3")[n % 3] for n in range(2, 11)]
    managers = [call for call in setup.prompter.calls if call["label"] == "IoT Hubs:"]
    assert [call["summary"] for call in managers[:2]] == ["1 of 10", "2 of 10"] and managers[-1]["summary"] == "10 of 10"
    full = {row.value: row for row in managers[-1]["rows"]}
    assert full["add-new"].detail == full["add-existing"].detail == "none left of 10"
    limit = "Guided setup links 10 IoT Hubs at most. Remove one from this setup to add another."
    assert managers[-2]["error"] == managers[-1]["error"] == limit  # Add new, then Add existing: nothing opens
    assert full["done"].detail == "10 new"
    assert [row.tag for row in managers[-1]["rows"][:10]] == ["NEW"] * 10
    names = [call for call in setup.prompter.calls if call["label"] == "IoT Hub name:"]
    assert names[0]["default"] == "adr-demo-hub-2"  # each Add new proposes the next free name

    setup.choices["hub"] = hubs
    links = setup.compose()["links"]["hubs"]
    assert [(hub["resourceName"], hub["sku"], hub["createIfMissing"]) for hub in links] == [
        (hub["name"], hub["sku"], True) for hub in hubs]
    assert setup.hub_slots == {index: index for index in range(10)}


def test_zero_one_and_two_hubs_compose_as_chosen():
    setup = hub_setup()
    assert setup._connect_hubs("none") == [] and "hubs" not in setup.compose()["links"]
    setup.choices["hub"] = [new_hub("one-hub")]
    assert [hub["resourceName"] for hub in setup.compose()["links"]["hubs"]] == ["one-hub"]
    setup.choices["hub"] = [new_hub("one-hub", "S3"), old_hub("typed-hub", HUB_ID)]
    hubs = setup.compose()["links"]["hubs"]
    assert hubs[0] == {"resourceName": "one-hub", "identity": {"type": "SystemAssigned"}, "createIfMissing": True,
                       "sku": "S3", "unit": 1}
    assert hubs[1] == {"resourceId": HUB_ID, "identity": {"type": "SystemAssigned"}}  # no tier, no unit, no create


def test_existing_hubs_are_marked_together_and_each_checked():
    setup = hub_setup([ARM + "Microsoft.Devices/IotHubs/plant-1", "plant-2", "/subscriptions/x/far-hub"],
                      targets=HUB_CATALOG)
    fake = setup.services
    far = f"/subscriptions/{SUB}/resourceGroups/rg-far/providers/Microsoft.Devices/IotHubs/far-hub"
    setup.prompter.answers = [[ARM + "Microsoft.Devices/IotHubs/plant-1", "plant-2", far]]
    hubs = setup._choose_existing_hubs([])
    assert [(hub["name"], hub["value"]) for hub in hubs] == [
        ("plant-1", ARM + "Microsoft.Devices/IotHubs/plant-1"), ("plant-2", ARM + "Microsoft.Devices/IotHubs/plant-2"),
        ("far-hub", far)]
    assert fake.validate_setup_target.call_count == 3  # every Hub is checked before it joins
    call = setup.prompter.calls[0]
    assert call["kind"] == "ask_many" and call["limit"] == 10 and len(call["rows"]) == 12
    assert call["caption"](12, 12, "").startswith("12 IoT Hubs in eastus · ")


def test_an_existing_hub_that_fails_its_check_stays_in_the_field_and_the_others_stay_marked():
    plant = [ARM + f"Microsoft.Devices/IotHubs/plant-{index}" for index in range(3)]
    setup = hub_setup(targets=HUB_CATALOG)
    setup.prompter.answers = [[plant[0], "missing-hub", plant[2]], [plant[0], plant[2], "plant-3"]]
    fake = setup.services
    fake.resolve_resource.side_effect = lambda endpoint: (_ for _ in ()).throw(ResourceNotFoundError("gone")) if (
        "missing" in endpoint.resource_id) else {"id": endpoint.resource_id, "location": "eastus", "sku": {"name": "S1"}}
    hubs = setup._choose_existing_hubs([])
    retry = setup.prompter.calls[1]
    assert "IoT Hub 'missing-hub' was not found in rg-demo" in retry["error"]
    assert retry["initial"] == "missing-hub" and retry["marked"] == [plant[0], plant[2]]
    assert [hub["name"] for hub in hubs] == ["plant-0", "plant-2", "plant-3"]
    checked = [args.args[0].endpoint_name for args in fake.validate_setup_target.call_args_list]
    assert checked.count("plant-0") == 1  # a successful check isn't repeated after a retry


@pytest.mark.parametrize("entered, expected", [
    ("plant-0", "IoT Hub 'plant-0' is already in this setup."),
    ("PLANT-0", "IoT Hub 'PLANT-0' is already in this setup."),
    (ARM.upper() + "MICROSOFT.DEVICES/IOTHUBS/PLANT-0", "is already in this setup."),  # a name and its ID are one
    ("adr-demo-dps", "Endpoint name 'adr-demo-dps' is already used in this setup; endpoint names are unique"),
    ("main", "Endpoint name 'main' is already used by a link on adr-demo; endpoint names are unique"),
    (LINKED_HUB.upper(), "is already linked to adr-demo; it stays linked."),
])
def test_duplicates_are_refused_as_soon_as_entered(entered, expected):
    setup = hub_setup(namespace=LINKED, hubs=[new_hub("plant-0")])
    setup.ns_info = deepcopy(LINKED)
    del setup.ns_info["properties"]["provisioning"]  # the DPS is chosen, not linked
    assert expected in setup._hub_conflict(entered, setup.choices["hub"])
    assert setup._hub_conflict("fresh-hub", setup.choices["hub"]) == ""
    assert setup._hub_conflict("x" * 300 + "/bad/", []) == ""  # malformed input: its own check explains it


def test_duplicate_new_hub_name_is_a_field_error_and_existing_picker_hides_chosen_hubs():
    plant = ARM + "Microsoft.Devices/IotHubs/plant-0"
    setup = hub_setup("add-new", "plant-0", "Plant-1", "S1", "add-existing", ["plant-2"], "done",
                      targets=HUB_CATALOG, hubs=[old_hub("plant-0", plant)])
    hubs = setup._manage_hubs(setup.choices["hub"])
    names = [call for call in setup.prompter.calls if call["label"] == "IoT Hub name:"]
    assert names[1]["error"] == "IoT Hub 'plant-0' is already in this setup."
    assert [hub["name"] for hub in hubs] == ["plant-0", "Plant-1", "plant-2"]  # typed names kept verbatim
    picker = next(call for call in setup.prompter.calls if call["kind"] == "ask_many")
    assert "plant-0" not in [row.title for row in picker["rows"]] and len(picker["rows"]) == 10  # plant-1 too
    assert picker["caption"](10, 10, "").startswith("10 IoT Hubs in eastus · ")
    assert "2 already in this setup" in picker["caption"](10, 10, "")


def test_editing_one_hub_changes_only_it_and_escape_rolls_the_manager_back():
    hubs = [new_hub(f"adr-demo-hub-{n}" if n > 1 else "adr-demo-hub") for n in range(1, 6)]
    setup = hub_setup("hub:4", "change", "line-5-hub", "S3", "done", hubs=hubs)
    edited = setup._manage_hubs(setup.choices["hub"])
    assert edited[4] == new_hub("line-5-hub", "S3") and edited[:4] == hubs[:4]
    editor = next(call for call in setup.prompter.calls if call["label"] == "IoT Hub:")
    assert editor["summary"] == "adr-demo-hub-5"
    assert [row.title for row in editor["rows"]] == ["Change name and tier", "Remove from setup"]
    assert setup.prompter.calls[-1]["default"] == "hub:4"  # focus stays on the row just used

    setup = hub_setup("hub:4", "change", "line-5-hub", "S3", "hub:0", "remove", MANAGER_ESC, hubs=hubs)
    with pytest.raises(BackRequested):
        setup._manage_hubs(setup.choices["hub"])
    assert setup.choices["hub"] == hubs and not setup.managing  # nothing changed until Continue

    # Esc inside one Hub's editor leaves it as it was, and the manager continues.
    setup = hub_setup("hub:1", "change", Back, Back, "done", hubs=hubs)
    assert setup._manage_hubs(hubs) == hubs


def test_removing_a_draft_is_setup_only_and_the_note_says_so():
    hubs = [new_hub("hub-a"), old_hub("hub-b", HUB_ID), new_hub("hub-c")]
    setup = hub_setup("hub:1", "remove", "hub:1", "remove", "done", hubs=hubs)
    result = setup._manage_hubs(hubs)
    assert [hub["name"] for hub in result] == ["hub-a"]
    managers = [call for call in setup.prompter.calls if call["label"] == "IoT Hubs:"]
    assert managers[1]["help"] == "Removed hub-b from this setup · nothing in Azure is deleted."
    assert managers[1]["default"] == "hub:1" and managers[2]["default"] == "add-new"  # the next row, or Add
    assert managers[2]["summary"] == "1 of 10"
    fake = setup.services
    assert not [name for name, _, _ in fake.method_calls if "delete" in name or "unlink" in name]
    editor = next(call for call in setup.prompter.calls if call["label"] == "IoT Hub:")
    assert [row.title for row in editor["rows"]] == ["Choose another", "Remove from setup"]
    assert editor["rows"][1].detail == "nothing in Azure is deleted"


def test_linked_hubs_count_toward_ten_are_never_offered_for_removal_and_more_than_ten_stay():
    setup = hub_setup("done", namespace=linked_hubs(8), hubs=[new_hub("hub-a")])
    setup._manage_hubs(setup.choices["hub"])
    manager = setup.prompter.calls[0]
    assert manager["summary"] == "9 of 10" and manager["help"] == "8 linked IoT Hubs stay linked and count toward 10."
    assert [row.value for row in manager["rows"]] == ["hub:0", "add-new", "add-existing", "done"]
    assert manager["rows"][-1].detail == "1 new · 8 linked"

    setup = hub_setup("add-existing", "done", namespace=linked_hubs(12))
    assert setup._manage_hubs([]) == []
    manager = setup.prompter.calls[-1]
    assert manager["summary"] == "12 · all linked ones are kept"
    assert manager["error"] == ("12 IoT Hubs are already linked; guided setup links 10 at most. They all stay linked.")
    config = setup.compose()
    assert len(config["links"]["hubs"]) == 12  # every link is kept and re-checked; none dropped or truncated


def test_connectivity_keeps_chosen_hubs_and_focuses_the_answers_way_to_add():
    setup = hub_setup("done", hubs=[new_hub("hub-a")])
    assert setup._connect_hubs("existing") == [new_hub("hub-a")]
    assert setup.prompter.calls[0]["default"] == "add-existing"
    setup = hub_setup("done", hubs=[new_hub("hub-a")])
    setup._connect_hubs("new")
    assert setup.prompter.calls[0]["default"] == "done"
    setup = hub_setup(targets=HUB_CATALOG)
    setup.prompter.answers = [["plant-1", "plant-2"], "done"]
    setup.choices["hub"] = setup._connect_hubs("existing")
    assert [hub["name"] for hub in setup.choices["hub"]] == ["plant-1", "plant-2"]
    assert setup._mode("hub") == "existing"
    setup.choices["hub"] = [new_hub("hub-a"), old_hub("hub-b")]
    assert setup._mode("hub") == "new"  # a mixed collection reads as New
    rows = setup._mode_rows(["hub"])
    assert rows[0].detail == "2 IoT Hubs chosen · review IoT Hubs next"


def test_multiple_hubs_survive_review_save_repeat_and_apply(mocker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plant = ARM + "Microsoft.Devices/IotHubs/plant-1"
    engine = Engine(NEW_PLAN)
    prompter = Scripted("rg-demo", "adr-demo", "new", "S1",
                        "add-new", "line-2-hub", "S3", "add-existing", [plant], "done", False, False,
                        Back, "save", "setup.json", "back", "adr-demo")
    result, text, _, _ = run(services(targets=HUB_CATALOG), prompter, engine, mocker)
    expected = [("adr-demo-hub", "S1", True), ("line-2-hub", "S3", True), ("plant-1", None, False)]
    for request in (engine.requests[0], engine.requests[-1], engine.applied[0]):
        assert [(hub.endpoint_name, hub.sku, bool(hub.create_if_missing)) for hub in request.hubs] == expected
    saved = load_config(json.loads((tmp_path / "setup.json").read_text(encoding="utf-8")))
    assert [hub.get("resourceName") or hub.get("resourceId") for hub in saved["links"]["hubs"]] == [
        "adr-demo-hub", "line-2-hub", plant]
    assert "sku" not in saved["links"]["hubs"][2] and "unit" not in saved["links"]["hubs"][2]
    for line in ("  ✓ IoT Hub:           adr-demo-hub  NEW · S1 · 1 unit",
                 "  ✓ IoT Hub:           line-2-hub  NEW · S3 · 1 unit",
                 "  ✓ IoT Hub:           plant-1  REUSE"):
        assert line in text
    assert text.count("--hub ") == 3  # the repeat command lists every Hub
    assert result["state"] == "Succeeded"
    menu = next(call for call in prompter.calls if call["label"] == "Change:")
    assert ("hubs", "IoT Hubs", "2 new · 1 existing") in [(row.value, row.title, row.detail) for row in menu["rows"]]


def test_scope_change_drops_every_chosen_hub():
    setup = hub_setup(hubs=[new_hub("hub-a"), old_hub("hub-b")])
    setup._invalidate("Resource group changed")
    assert "hub" not in setup.choices


@pytest.mark.parametrize("message, field", [
    ("links.hubs[2].sku conflicts with the existing resource", "hub:1"),
    ("links.hubs[0] can't be re-checked", None),  # a kept link: Change, with the problem
    ("IoT Hub 'hub-c' is in another region", "hub:2"),
    ("--hub.resourceName is unavailable: the name is taken", "hub:1"),  # the endpoint the plan was checking
    ("links.hubs is not valid", "hubs"),
])
def test_plan_problems_reach_the_right_hub_among_many(message, field):
    setup = hub_setup(namespace=deepcopy(LINKED), hubs=[new_hub("hub-a"), new_hub("hub-b"), new_hub("hub-c")])
    setup.compose()
    assert setup.hub_slots == {1: 0, 2: 1, 3: 2}
    setup.plan_target = ("hub", "hub-b") if message.startswith("--hub.") else None
    assert setup.plan_error(InvalidArgumentValueError(message)) == field
    setup.choices["hub"] = []
    assert setup.plan_error(InvalidArgumentValueError("--hub.resourceName is unavailable")) is None


def test_plan_problem_opens_that_hubs_name_field_inside_the_manager():
    hubs = [new_hub("hub-a"), new_hub("hub-b")]
    setup = hub_setup("hub-b2", "S1", "done", hubs=hubs)
    setup.edit("hub:1", error="IoT Hub name 'hub-b' is not available.")
    assert setup.prompter.calls[0]["label"] == "IoT Hub name:"
    assert setup.prompter.calls[0]["error"] == "IoT Hub name 'hub-b' is not available."
    assert [hub["name"] for hub in setup.choices["hub"]] == ["hub-a", "hub-b2"]


def test_plan_target_follows_the_engines_validation_labels():
    tracker = guided.PlanTarget()
    assert tracker.run("Validate hub Line-2-Hub", lambda value: value * 2, 4) == 8
    assert tracker.current == ("hub", "line-2-hub")
    tracker.run("Validate hub creation", lambda: None)
    assert tracker.current == ("hub", "line-2-hub")  # creation continues the Hub checked before it
    tracker.run("Read namespace", lambda: None)
    assert tracker.current is None
    with pytest.raises(ValueError):
        tracker.run("Validate dps adr-demo-dps", _raise)
    assert tracker.current == ("dps", "adr-demo-dps")


def test_failed_plan_read_records_the_hub_it_was_checking(mocker):
    setup = hub_setup(hubs=[new_hub("hub-a"), new_hub("hub-b")])

    class Failing:
        def __init__(self, services, progress=None):
            self.progress = progress

        def plan_setup(self, request):
            self.progress.run("Validate hub hub-b", lambda: None)
            raise InvalidArgumentValueError("--hub.resourceName is unavailable")

    mocker.patch.object(guided, "NamespaceWorkflow", Failing)
    with pytest.raises(InvalidArgumentValueError):
        setup.read_plan(setup.compose())
    assert setup.plan_target == ("hub", "hub-b")


def test_answer_rows_list_every_hub_and_the_manager_shows_them_itself():
    setup = hub_setup(hubs=[new_hub("hub-a", "S2"), old_hub("hub-b")])
    rows = [line.plain for line in setup._answer_lines()]
    assert "  ✓ IoT Hub:           hub-a  NEW · S2 · 1 unit" in rows
    assert "  ✓ IoT Hub:           hub-b  REUSE · eastus · S1" in rows
    setup.managing = True
    assert not [row for row in (line.plain for line in setup._answer_lines()) if "IoT Hub:" in row]


# --------------------------------------------------------------------------------------------
# Several at once: the real prompt and the plain one
# --------------------------------------------------------------------------------------------


PLANTS = [guided.Row(f"/id/plant-{index}", f"plant-{index}", "eastus · S1") for index in range(4)]


def test_space_marks_rows_and_typed_names_and_enter_takes_them():
    assert _terminal("plant-2 plant-0 \r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == [
        "/id/plant-2", "/id/plant-0"]  # search, Space marks the match and clears the search
    assert _terminal(" \x1b[B \r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == ["/id/plant-0", "/id/plant-1"]
    assert _terminal("far-hub plant-1 \r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == ["far-hub", "/id/plant-1"]
    assert _terminal("  \x1b[B\r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == ["/id/plant-1"]  # unmarked
    assert _terminal("\r", "ask_many", "IoT Hubs:", PLANTS, limit=10, marked=["/id/plant-3"]) == ["/id/plant-3"]
    assert _terminal("typed\r", "ask_many", "IoT Hubs:", [], limit=10) == ["typed"]


def test_enter_commits_the_marks_and_never_drops_or_adds_a_pending_hub(monkeypatch):
    """Empty field, or a search that only filters: Enter commits exactly the marks, wherever the pointer is. A Hub
    itself in the field (typed in full, or a name or ID matching no row, e.g. corrected after a failed check) is
    neither dropped nor added unasked: Enter explains and Space adds it."""
    many = {"limit": 10, "marked": ["/id/plant-0"]}
    # The ordinary filtered multi-select: the search stays a search, not an unmarked Hub.
    assert _terminal("plant-2 plant-\r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == ["/id/plant-2"]
    assert _terminal("plant-0\r", "ask_many", "IoT Hubs:", PLANTS, **many) == ["/id/plant-0"]  # marked already
    # Pointer moved to an unmarked row, field empty: only the marks; a deliberately unmarked row stays out.
    assert _terminal("\x1b[B\x1b[B\r", "ask_many", "IoT Hubs:", PLANTS, **many) == ["/id/plant-0"]
    assert _terminal(" \x1b[B \x1b[B \x1b[A \r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == [
        "/id/plant-0", "/id/plant-2"]
    # A corrected value with another Hub marked: Enter explains, Space adds it, Enter checks both.
    for field in ("fixed-hub", "PLANT-2", "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/far"):
        lines = _rendered(monkeypatch, "\x15" + field + "\r\x1b", "ask_many", "IoT Hubs:", PLANTS, initial="missing-hub",
                          **many)
        shown = "plant-2" if field == "PLANT-2" else field.rsplit("/", 1)[-1]
        assert any(f"Space adds {shown} · or clear the field to check the 1 selected." in line for line in lines)
    assert _terminal("\x15fixed-hub \r", "ask_many", "IoT Hubs:", PLANTS, initial="missing-hub", **many) == [
        "/id/plant-0", "fixed-hub"]
    assert _terminal("\x15plant-2 \r", "ask_many", "IoT Hubs:", PLANTS, initial="missing-hub", **many) == [
        "/id/plant-0", "/id/plant-2"]
    # Ctrl+U clears the field: Enter then checks only the marks (the failed Hub is deliberately left out).
    assert _terminal("\r\x15\r", "ask_many", "IoT Hubs:", PLANTS, initial="missing-hub", **many) == ["/id/plant-0"]
    # With nothing marked, Enter takes the field as a single pick always did.
    assert _terminal("fixed-hub\r", "ask_many", "IoT Hubs:", PLANTS, limit=10) == ["fixed-hub"]


def test_ten_marked_the_eleventh_is_blocked_and_enter_still_checks_ten(monkeypatch):
    rows = [guided.Row(f"/id/hub-{index:02}", f"hub-{index:02}", "eastus · S1") for index in range(11)]
    keys = " \x1b[B" * 11 + "\r"  # Space on each row, the eleventh too, then Enter
    assert _terminal(keys, "ask_many", "IoT Hubs:", rows, limit=10) == [row.value for row in rows[:10]]
    lines = _rendered(monkeypatch, " \x1b[B" * 10 + " \x1b", "ask_many", "IoT Hubs:", rows, limit=10)
    assert any("10 at most here · space on a ✓ row unmarks it · enter checks them." in line for line in lines)
    lines = _rendered(monkeypatch, " \x1b[B" * 10 + "hub-10\r\x1b", "ask_many", "IoT Hubs:", rows, limit=10)
    assert "10 at most here · unmark one to add hub-10, or clear the field to check the 10 selected." in flat(
        " ".join(line.lstrip("┃ ") for line in lines))


def test_corrected_hub_after_a_failed_check_joins_the_other_marks():
    """The real recovery: the failing Hub is put back in the field and the others stay marked; the corrected
    name, added with Space, is checked and taken with them."""
    plant = [ARM + f"Microsoft.Devices/IotHubs/plant-{index}" for index in range(2)]
    setup = hub_setup(targets=HUB_CATALOG)
    fake = setup.services
    fake.resolve_resource.side_effect = lambda endpoint: (_ for _ in ()).throw(ResourceNotFoundError("gone")) if (
        "missing" in endpoint.resource_id) else {"id": endpoint.resource_id, "location": "eastus", "sku": {"name": "S1"}}

    class Real(Scripted):
        def ask_many(self, label, rows=(), **kwargs):  # the second answer comes from the real prompt
            if not self.calls:
                return super().ask_many(label, rows, **kwargs)
            self.calls.append({"kind": "ask_many", "label": label, "rows": list(rows), **kwargs})
            return _terminal("\x15plant-1 \r", "ask_many", label, rows, **kwargs)

    setup.prompter = Real([plant[0], "missing-hub"])
    hubs = setup._choose_existing_hubs([])
    assert setup.prompter.calls[1]["initial"] == "missing-hub" and setup.prompter.calls[1]["marked"] == [plant[0]]
    assert [hub["name"] for hub in hubs] == ["plant-0", "plant-1"]


def test_space_at_the_limit_explains_and_marks_nothing_more(monkeypatch):
    lines = _rendered(monkeypatch, " \x1b[B \x1b", "ask_many", "IoT Hubs:", PLANTS, limit=1)
    assert any("1 at most here · space on a ✓ row unmarks it · enter checks them." in line for line in lines)
    assert _terminal(" \x1b[B \r", "ask_many", "IoT Hubs:", PLANTS, limit=1) == ["/id/plant-0"]


def test_marked_rows_show_a_check_and_the_caption_counts_them_at_80_columns(monkeypatch):
    def caption(shown, total, query):
        return f"{total} IoT Hubs in rg-demo · type to filter, or a resource ID"

    lines = _rendered(monkeypatch, "\x1b[B \x1b", "ask_many", "IoT Hubs:", PLANTS, limit=10, marked=["/id/plant-0"],
                      caption=caption)
    assert all(cell_len(line) <= 80 for line in lines)
    marked = [line for line in lines if "✓" in line]
    assert len(marked) == 2 and "plant-0" in marked[0] and "plant-1" in marked[1]
    assert any("2 selected" in line for line in lines)
    assert any("space select" in line for line in lines)


def test_ten_hub_manager_fits_80x24_without_scrolling(monkeypatch):
    setup = hub_setup(hubs=[new_hub(f"adr-demo-hub-{n}") for n in range(1, 11)])
    rows = setup._hub_rows(setup.choices["hub"])
    lines = _rendered(monkeypatch, "\r", "select", "IoT Hubs:", rows, default="done", summary="10 of 10",
                      help="Removed x from this setup · nothing in Azure is deleted.")
    height = sum(1 for line in lines if line)
    assert height <= 24 and all(cell_len(line) <= 80 for line in lines)
    assert "Continue" in "".join(lines) and "10 of 10" in lines[0]
    assert sum("NEW" in line for line in lines) == 10


def test_plain_prompter_takes_several_numbers_or_names():
    prompter, stream = _plain_prompter("1, name-2 far\n", "\n", "1 2 3\n", "\n", "2\n")
    assert prompter.ask_many("IoT Hubs:", ROWS[:3], limit=10, error="bad",
                             caption=lambda shown, total, query: f"{total} listed") == ["id-0", "id-2", "far"]
    assert prompter.ask_many("IoT Hubs:", ROWS[:3], limit=10, marked=["id-1"]) == ["id-1"]
    assert prompter.ask_many("IoT Hubs:", ROWS[:3], limit=2) == ["id-1"]  # 3 is too many; then empty; then 2
    text = stream.getvalue()
    assert "  ! bad" in text and "    3 listed" in text and "[name-1]" in text and "(numbers or names, up to 10)" in text
    assert "Enter 1 to 2 numbers or names." in text and "Enter one or more numbers or names." in text


def test_choosing_another_existing_hub_is_checked_against_the_rest_and_esc_in_add_changes_nothing():
    plant = [ARM + f"Microsoft.Devices/IotHubs/plant-{index}" for index in range(4)]
    hubs = [old_hub("plant-0", plant[0]), old_hub("plant-1", plant[1])]
    setup = hub_setup("add-new", Back, "hub:1", "change", "plant-0", "plant-3", "done",
                      targets=HUB_CATALOG, hubs=hubs)
    result = setup._manage_hubs(hubs)
    assert [hub["name"] for hub in result] == ["plant-0", "plant-3"]
    picks = [call for call in setup.prompter.calls if call["label"] == "IoT Hub:" and call["kind"] == "ask"]
    assert picks[0]["default"] == plant[1]  # reopens on the Hub it replaces
    assert "plant-0" not in [row.title for row in picks[0]["rows"]]  # the other chosen Hub isn't offered
    assert picks[1]["error"] == "IoT Hub 'plant-0' is already in this setup."
    assert setup.prompter.calls[2]["default"] == "add-new"  # Esc in Add new: back on its row, nothing added


def test_space_with_an_empty_field_and_no_rows_does_nothing_and_malformed_drafts_never_match():
    assert _terminal(" typed\r", "ask_many", "IoT Hubs:", [], limit=10) == ["typed"]
    setup = hub_setup()
    assert setup._hub_conflict("fresh-hub", [old_hub("odd", "/not/an/arm/id")]) == ""


# --------------------------------------------------------------------------------------------
# Targets in other resource groups and subscriptions: "Another subscription…"
# --------------------------------------------------------------------------------------------


TENANT = "tenant-a"
SHARED_SUB = "11111111-1111-4111-8111-111111111111"
SHARED_HUB = f"/subscriptions/{SHARED_SUB}/resourceGroups/rg-shared/providers/Microsoft.Devices/IotHubs/hub-shared"
EDGE_HUB = ARM.replace("rg-demo", "rg-contoso-edge") + "Microsoft.Devices/IotHubs/hub-edge"
ACTION = guided.Row(guided.SCOPE, "Another subscription…", "now: Contoso Dev")


def scoped_setup(*answers, subscriptions=None):
    """A setup whose subscription lists Hubs in two resource groups (one in another region), and a second
    subscription in the same directory with one Hub; another directory's and a disabled subscription are listed."""
    home = [{"id": ARM + "Microsoft.Devices/IotHubs/plant-0", "name": "plant-0", "location": "eastus", "sku": "S1",
             "resourceGroup": "rg-demo"},
            {"id": EDGE_HUB, "name": "hub-edge", "location": "eastus", "sku": "S1", "resourceGroup": "rg-contoso-edge"},
            {"id": ARM + "Microsoft.Devices/IotHubs/hub-wrong-region", "name": "hub-wrong-region", "location": "westus",
             "sku": "S1"}]
    shared = [{"id": SHARED_HUB, "name": "hub-shared", "location": "East US", "sku": "S2", "resourceGroup": "rg-shared"}]
    setup = hub_setup(*answers)
    setup.subscription_name = "Contoso Dev"
    fake = setup.services
    fake.list_link_targets.side_effect = lambda kind, group=None, subscription=None: (
        shared if subscription == SHARED_SUB else home) if kind == "hub" else []
    fake.list_subscriptions.return_value = subscriptions if subscriptions is not None else [
        {"id": SUB, "name": "Contoso Dev", "state": "Enabled", "tenantId": TENANT},
        {"id": SHARED_SUB, "name": "Contoso Shared Services", "state": "Enabled", "tenantId": TENANT},
        {"id": "22222222-2222-4222-8222-222222222222", "name": "Fabrikam", "state": "Enabled", "tenantId": "other"},
        {"id": "33333333-3333-4333-8333-333333333333", "name": "Retired", "state": "Disabled", "tenantId": TENANT},
    ]
    return setup


def test_scope_row_is_pinned_last_and_never_focused_without_the_arrows():
    picker = guided.Picker(ROWS[:3], focus_first=True, action=ACTION)
    assert picker.visible()[-1] == ACTION and picker.current().value == "id-0"
    picker.set_text("name-1")
    assert [row.value for row in picker.visible()] == ["id-1", guided.SCOPE] and picker.current().value == "id-1"
    picker.set_text("zz")  # no match: nothing is focused, least of all the command
    assert picker.index == -1 and not picker.acting()
    picker.set_text("")
    picker.move(-1)  # ↑ from the first row wraps to the command
    assert picker.acting() and picker.current() == ACTION


def test_scope_row_in_the_real_prompt_carries_the_search_and_marks():
    rows = PLANTS
    assert _terminal("\x1b[A\r", "ask", "DPS:", rows, action=ACTION, focus_first=True) == guided.SCOPE
    assert _terminal("plant\x1b[A\r", "ask", "DPS:", rows, action=ACTION, focus_first=True) == guided.SCOPE + "plant"
    assert _terminal("\r", "ask", "DPS:", rows, action=ACTION, focus_first=True) == "/id/plant-0"  # never the command
    # Marks and the search travel with the command; Space on it marks nothing.
    assert _terminal(" \x1b[A \r", "ask_many", "IoT Hubs:", rows, limit=10, action=ACTION) == [
        guided.SCOPE, "/id/plant-0"]
    assert _terminal(" west\x1b[A\x1b[A\r", "ask_many", "IoT Hubs:", rows, limit=10, action=ACTION) == [
        guided.SCOPE + "west", "/id/plant-0"]


def test_plain_prompter_takes_the_scope_number_alone_and_never_drops_a_selection():
    prompter, stream = _plain_prompter("5\n", "1,5\n", "5\n", "5\n")
    assert prompter.ask("DPS:", PLANTS, action=ACTION) == guided.SCOPE
    # "1,5": a resource and the command together would lose the resource; it is refused, the list kept.
    assert prompter.ask_many("IoT Hubs:", PLANTS, limit=10, marked=["/id/plant-3"], action=ACTION) == [
        guided.SCOPE, "/id/plant-3"]
    assert "Enter 5 alone to choose Another subscription; the marks are kept." in stream.getvalue()
    assert "    5) Another subscription…  now: Contoso Dev" in stream.getvalue()
    assert prompter.ask_many("IoT Hubs:", PLANTS, limit=10, action=ACTION) == [guided.SCOPE]


def test_hub_picker_lists_every_resource_group_in_the_namespace_region_by_default():
    setup = scoped_setup([EDGE_HUB])
    hubs = setup._choose_existing_hubs([])
    setup.services.list_link_targets.assert_called_once_with("hub", None, None)  # one subscription-wide list
    call = setup.prompter.calls[0]
    assert [(row.title, row.detail) for row in call["rows"]] == [
        ("plant-0", "rg-demo · S1"), ("hub-edge", "rg-contoso-edge · S1")]
    assert call["caption"](2, 2, "") == ("2 IoT Hubs in eastus · Contoso Dev · all resource groups · 1 in other "
                                         "regions not shown · type to filter, or a resource ID")
    assert call["action"] == ACTION
    # A Hub in another resource group says where it is wherever it is shown; the namespace scope is unchanged.
    assert hubs == [{"mode": "existing", "value": EDGE_HUB, "name": "hub-edge", "detail": "in rg-contoso-edge · eastus · S1"}]
    setup.choices["hub"] = hubs
    assert setup.compose()["links"]["hubs"][0]["resourceId"] == EDGE_HUB
    assert (setup.subscription, setup.rg) == (SUB, "rg-demo")


def test_another_subscription_keeps_marks_and_search_and_names_carried_hubs():
    plant = ARM + "Microsoft.Devices/IotHubs/plant-0"
    setup = scoped_setup([guided.SCOPE + "hub", plant], SHARED_SUB, [plant, SHARED_HUB])
    hubs = setup._choose_existing_hubs([])
    fake, calls = setup.services, setup.prompter.calls
    fake.list_link_targets.assert_any_call("hub", None, SHARED_SUB)  # that subscription, without changing the profile
    pick = calls[1]
    assert pick["label"] == "Subscription:" and [row.title for row in pick["rows"]] == [
        "Contoso Dev", "Contoso Shared Services"]  # another directory and a disabled one are never offered
    assert pick["caption"](2, 2, "") == ("2 subscriptions in this directory · 2 not shown: other directory or disabled "
                                         "· type to filter")
    again = calls[2]
    assert again["marked"] == [plant] and again["initial"] == "hub"  # the mark and the search survive
    assert [(row.title, row.detail) for row in again["rows"]] == [
        ("plant-0", "rg-demo · S1 · Contoso Dev"),  # carried: always names its subscription
        ("hub-shared", "rg-shared · S2")]  # this subscription's rows stay compact
    assert again["action"].detail == "now: Contoso Shared Services"
    assert again["caption"](2, 2, "hub") == "2 of 2 match"  # carried rows are searched and counted alike
    assert again["caption"](1, 1, "").startswith("1 IoT Hub in eastus · Contoso Shared Services")
    assert [hub["name"] for hub in hubs] == ["plant-0", "hub-shared"]
    assert hubs[1]["detail"].startswith("in rg-shared, Contoso Shared Services · ")
    assert (setup.subscription, setup.rg) == (SUB, "rg-demo")
    setup.choices["hub"] = hubs
    assert [hub["resourceId"] for hub in setup.compose()["links"]["hubs"]] == [plant, SHARED_HUB]
    rows = setup._hub_rows(hubs)
    assert any("in rg-shared, Contoso Shared Services" in row.detail for row in rows)


def test_cancelled_subscription_choice_changes_nothing():
    setup = scoped_setup([guided.SCOPE + "edge", EDGE_HUB], Back, [EDGE_HUB])
    setup._choose_existing_hubs([])
    first, again = setup.prompter.calls[0], setup.prompter.calls[2]
    assert again["initial"] == "edge" and again["marked"] == [EDGE_HUB]
    assert [row.value for row in again["rows"]] == [row.value for row in first["rows"]]
    assert setup.services.list_link_targets.call_count == 1  # same scope: the listing isn't read again

    setup = scoped_setup(guided.SCOPE + "shared-d", Back, DPS_ID)
    setup.services.list_link_targets.side_effect = lambda kind, group=None, subscription=None: []
    setup._choose_existing("dps")
    assert setup.prompter.calls[2]["initial"] == "shared-d" and setup.prompter.calls[2]["label"] == "DPS:"


def test_a_mark_typed_in_another_case_becomes_the_listed_row_after_a_switch():
    typed = SHARED_HUB.upper()  # marked while its subscription wasn't listed
    setup = scoped_setup([guided.SCOPE, typed], SHARED_SUB, [SHARED_HUB])
    hubs = setup._choose_existing_hubs([])
    again = setup.prompter.calls[2]
    assert again["marked"] == [SHARED_HUB]  # one ✓ on the listed row, not a second unmarked-looking copy
    assert [row.value for row in again["rows"]] == [SHARED_HUB]
    assert [hub["value"] for hub in hubs] == [SHARED_HUB]
    assert _terminal(SHARED_HUB.upper() + " \r", "ask_many", "IoT Hubs:",
                     [guided.Row(SHARED_HUB, "hub-shared", "")], limit=10) == [SHARED_HUB]


def test_subscription_listing_problems_are_shown_and_a_full_id_still_works():
    setup = scoped_setup([guided.SCOPE], SUB, SHARED_HUB)
    setup.services.list_subscriptions.side_effect = RuntimeError("AuthorizationFailed")
    setup.prompter.answers = [[guided.SCOPE], SUB, [SHARED_HUB]]
    hubs = setup._choose_existing_hubs([])
    assert [row.value for row in setup.prompter.calls[1]["rows"]] == [SUB]  # the namespace's own is always there
    assert "Couldn't list subscriptions: AuthorizationFailed. Type a full resource ID instead." in flat(
        plain(setup.screen.stream.getvalue()))
    assert [hub["value"] for hub in hubs] == [SHARED_HUB]
    assert ("subscriptions",) not in setup.cache  # retried on the next visit

    setup = scoped_setup(guided.SCOPE, "Fabrikam", Back, DPS_ID)
    setup.services.list_link_targets.side_effect = lambda kind, group=None, subscription=None: []
    setup._choose_existing("dps")
    assert setup.prompter.calls[2]["error"].startswith("Choose a listed subscription")


def test_elsewhere_names_only_what_differs_from_the_namespace():
    setup = scoped_setup()
    setup.subscription_names[SHARED_SUB] = "Contoso Shared Services"
    assert setup._elsewhere(ARM + "Microsoft.Devices/IotHubs/x") == ""
    assert setup._elsewhere(EDGE_HUB) == "in rg-contoso-edge"
    assert setup._elsewhere(SHARED_HUB) == "in rg-shared, Contoso Shared Services"
    assert setup._elsewhere("plain-name") == ""
    items = [item("link-hub-hub-shared", "link", "hub-shared", resourceId=SHARED_HUB, identityType="SystemAssigned"),
             item("link-hub-local", "link", "local", resourceId=ARM + "Microsoft.Devices/IotHubs/local")]
    entries = guided.plan_entries(items, "adr-demo", where=setup._elsewhere)
    assert entries[0].detail == "in rg-shared, Contoso Shared Services · IoT Hub system-assigned managed identity"
    assert entries[1].detail == ""  # a target in the namespace's own resource group needs no annotation


# --------------------------------------------------------------------------------------------
# The approval surface
# --------------------------------------------------------------------------------------------


def test_plan_surface_is_a_faint_wash_without_a_border_and_fits_the_width(monkeypatch):
    from rich.text import Text

    monkeypatch.delenv("NO_COLOR", raising=False)
    summary = Text("✦ 4 new · ⇄ 2 links", guided.GOOD)
    body = [Text("  ✦ DPS:               adr-demo-dps  NEW")]
    for system, background, code in (("truecolor", "#1e1e1e", "48;2;44;47;50"), ("truecolor", "#ffffff", "48;2;"),
                                     ("256", "#1e1e1e", "48;5;236")):
        for columns in (80, 120):
            out, _ = tty_screen(monkeypatch, columns=columns, color=system)
            out.tints = guided.surface_tints(background, system)
            washed = out.surface("Plan", summary, body)
            cap, heading, row, bottom = washed
            assert cap.plain == "▄" * (out.width - 1) and bottom.plain == "▀" * (out.width - 1)  # half-row air
            assert heading.plain.rstrip() == "  Plan  ✦ 4 new · ⇄ 2 links" and row.plain.rstrip() == body[0].plain
            assert all(cell_len(line.plain) == out.width - 1 for line in washed)  # never the terminal's last column
            raw = out._render(washed)
            assert code in raw and not any(stroke in raw for stroke in "╭╮╰╯│─┌└")  # a wash, no drawn border
            assert heading.spans[0].style.bgcolor and heading.spans[0].end == len(heading.plain)  # under the colours
            assert any(span.style == guided.GOOD + guided.WASHED for span in heading.spans)  # its own, legible
            ink = Color.parse(out.tints.rich_inks["create"]).get_ansi_codes()
            assert ";".join(ink) in raw.split("✦")[0].rsplit("\x1b[", 1)[-1]  # drawn in the washed jade
            assert body[0].spans == []  # the caller's rows are not changed
    with out.inset():
        assert out._inset == 1
        long = out.surface("Plan", Text(" · ".join(["✦ 9 new"] * 30)), [])
    assert out._inset == 0
    assert len(long) > 4 and long[2].plain.startswith("        ") and all(  # wrapped under the summary
        cell_len(line.plain) == out.width - 1 for line in long)

    interactive, _ = tty_screen(monkeypatch)
    assert interactive.surface("Plan", summary, body) is None  # the caller builds the narrower frame instead
    plain_out = screen()
    bare = plain_out.surface("Plan", summary, body)
    assert [line.plain for line in bare] == ["", "  Plan  ✦ 4 new · ⇄ 2 links", body[0].plain, ""]
    assert "48;" not in plain_out._render(bare)
    with plain_out.inset():
        assert plain_out._inset == 0  # nothing to inset without a wash


def test_surface_is_only_behind_the_plan_and_gone_in_change(mocker, monkeypatch):
    mocker.patch.object(guided, "NamespaceWorkflow", Engine(NEW_PLAN))
    monkeypatch.delenv("NO_COLOR", raising=False)
    out, term = tty_screen(monkeypatch, color="truecolor")
    out.tints = guided.surface_tints("#1e1e1e", "truecolor")
    out.foreground = "#d4d4d4"
    seen = {}

    class Recording(Scripted):
        def _next(self, kind, label, rows=(), **kwargs):
            seen.setdefault(label, []).append((term.text, out._render(out._region)))
            return super()._next(kind, label, rows, **kwargs)

    prompter = Recording("rg-demo", "adr-demo", "new", "S1", False, False, Back, Back, KeyboardInterrupt())
    guided.run_guided_setup(services(), SUB, screen=out, prompter=prompter)
    approve, raw = seen["Approve:"][0]
    assert "▄▄▄▄" in approve and "▀▀▀▀" in approve and "  Plan  ✦ 4 new · ⇄ 2 links" in approve
    assert "nothing is deleted" not in approve and "48;2;" in raw
    change, raw = seen["Change:"][0]
    assert "▄" not in change and "▀" not in change and "48;" not in raw  # repainted away: the answers, unwashed
    assert "▄▄▄▄" in seen["Approve:"][1][0]  # back to approval (read again): on the surface again
    assert prompter.labels[-3:] == ["Approve:", "Change:", "Approve:"]


@pytest.mark.parametrize("palette", ["256", "truecolor", "standard"])
@pytest.mark.parametrize("columns", [40, 80, 120])
def test_frame_reuses_the_wordmark_gradient_and_only_fills_readable_tags(monkeypatch, columns, palette):
    from rich.text import Text

    monkeypatch.delenv("NO_COLOR", raising=False)
    out, _ = tty_screen(monkeypatch, columns=columns, color=palette)
    with out.inset(3):
        body = out.fact_lines("DPS:", "温度-cafe\u0301-with-a-long-resource-name", "S1 · australiaeast",
                              tag="NEW", tag_style=guided.GOOD_BOLD, mark="✦", mark_style=guided.GOOD_BOLD,
                              badge=True)
        body += out.fact_lines("IoT Hub:", "a" * 50, "IoT Hub system-assigned managed identity",
                               tag="LINK", tag_style=guided.LINK_BOLD, mark="⇄", mark_style=guided.LINK_BOLD,
                               badge=True)
    original = [row.copy() for row in body]
    rows = out.frame_surface("Plan", Text("✦ 2 new · ⇄ 1 link"), body)
    assert rows[0].plain == "" and rows[1].plain.startswith("╭─ Plan  ") and rows[1].plain.endswith("╮")
    assert rows[-1].plain == "╰" + "─" * (out.width - 3) + "╯"
    assert all(cell_len(row.plain) == out.width - 1 for row in rows[1:])
    assert body == original and out._inset == 0
    assert out.frame_surface("Plan", Text("✦ 2 new · ⇄ 1 link"), body) == rows
    bottom = rows[-1]
    for index, color in enumerate(guided.gradient(guided.GRADIENTS[out.palette], out.width - 1)):
        assert bottom.get_style_at_offset(out.console, index).color == Color.parse(color)
    for row in rows[2:-1]:
        assert row.plain.startswith("│") and row.plain.endswith("│")
        assert row.get_style_at_offset(out.console, 0).color == Color.parse(guided.GRADIENTS[out.palette][0])
        assert row.get_style_at_offset(out.console, len(row.plain) - 1).color == Color.parse(
            guided.GRADIENTS[out.palette][-1])
    painted = []
    for row in rows[1:]:
        for index, char in enumerate(row.plain):
            style = row.get_style_at_offset(out.console, index)
            assert not style.dim
            if style.bgcolor:
                painted.append(char)
                assert guided.contrast(style.color.get_truecolor().hex, style.bgcolor.get_truecolor().hex) >= 4.5
            elif char.isalnum():
                assert style.color is None or style.color.is_default
    assert "".join(painted).replace("\u00a0", "").replace(" ", "") == ("NEWLINK" if palette != "standard" else "")
    raw = out._render(rows)
    assert not any(code in raw for code in ("\x1b[?1049h", "\x1b[2J", "\x1b[3J"))
    if palette != "truecolor":
        assert "38;2;" not in raw and "48;2;" not in raw
    if palette == "standard":
        assert "38;5;" not in raw and "48;5;" not in raw


def test_da1_only_terminal_gets_a_frame_that_leaves_change_and_preserves_engine_work(mocker, monkeypatch):
    # Rich caches a combined style's first ANSI encoding across consoles of different color depths.
    guided.Style._add.cache_clear()
    monkeypatch.delenv("NO_COLOR", raising=False)
    out, term = tty_screen(monkeypatch, color="256")
    replies = guided.TerminalReplies(("foreground", "osc", "da1"))
    replies.feed(UNSUPPORTED_REPLY)
    probe = mocker.patch.object(guided, "probe_background", return_value=(replies, ""))
    mocker.patch.object(guided, "same_terminal", return_value=True)
    assert out.probe(_Stdin()) == ""
    assert out.tints is None and out.foreground is None and not replies.outstanding
    engine = Engine(NEW_PLAN)
    mocker.patch.object(guided, "NamespaceWorkflow", engine)
    seen = {}

    class Recording(Scripted):
        def _next(self, kind, label, rows=(), **kwargs):
            seen.setdefault(label, []).append((term.text, out._render(out._region)))
            return super()._next(kind, label, rows, **kwargs)

    prompter = Recording("rg-demo", "adr-demo", "new", "S1", False, False, Back, Back, KeyboardInterrupt())
    guided.run_guided_setup(services(), SUB, screen=out, prompter=prompter)
    for text, raw in seen["Approve:"]:
        assert "╭─ Plan  ✦ 4 new · ⇄ 2 links" in text and "╯" in text
        assert "adr-demo-dps" in text and "adr-demo-hub" in text
        assert "48;5;29" in raw and "48;5;61" in raw
        assert "38;2;" not in raw and "48;2;" not in raw
    text, raw = seen["Change:"][0]
    assert not any(char in text for char in "╭╰╮╯") and "48;" not in raw
    assert prompter.labels[-3:] == ["Approve:", "Change:", "Approve:"]
    probe.assert_called_once()
    assert not engine.applied


def test_frame_keeps_a_wrapped_heading_and_monochrome_structure_without_affecting_plain_output(monkeypatch):
    from rich.text import Text

    monkeypatch.setenv("NO_COLOR", "1")
    out, _ = tty_screen(monkeypatch, columns=80, color="truecolor")
    with out.inset(3):
        body = out.fact_lines("DPS:", "my-dps", "S1", tag="NEW", tag_style=guided.GOOD_BOLD, badge=True)
    summary = Text(" · ".join(["✦ 9 new"] * 30))
    rows = out.frame_surface("Plan", summary, body)
    assert all(cell_len(row.plain) == 79 for row in rows[1:])
    assert flat(" ".join(row.plain.replace("│", " ") for row in rows)).count("9 new") == 30
    assert rows[-2].plain.startswith("│") and rows[-1].plain.endswith("╯")
    raw = out._render(rows)
    for match in re.finditer(r"\x1b\[([0-9;]*)m", raw):
        assert set(match[1].split(";")) <= {"", "0", "1", "2", "22"}
    bare = screen(plain_mode=True).surface("Plan", Text("✦ 1 new"), body)
    assert bare[0].plain == bare[-1].plain == ""
    assert not any(char in "\n".join(row.plain for row in bare) for char in "╭╰╮╯")


def test_failed_mist_contrast_rebuilds_the_plan_for_the_frame_width(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    setup = hub_setup()
    out, _ = tty_screen(monkeypatch, columns=80, color="truecolor")
    out.tints = guided.surface_tints("#1e1e1e", "truecolor")
    out.foreground = "#444444"
    setup.screen, setup.plan, setup.mode = out, NEW_PLAN, "plan"
    before = deepcopy(setup.plan)
    rows = setup._plan_lines()
    assert rows[1].plain.startswith("╭─ Plan")
    assert all(cell_len(row.plain) == 79 for row in rows[1:])
    assert setup.plan == before and out._inset == 0
    text = " ".join(row.plain.replace("│", " ") for row in rows)
    assert "IoT Hub system-assigned managed identity" in flat(text)


def test_role_items_needing_attention_stay_visible_under_their_row(mocker):
    blocked = plan(item("namespace", state="Satisfied"),
                   item("link-hub-h", "link", "h", resourceId="/s/hub/h", identityType="SystemAssigned"),
                   item("roles-hub-h", "role", "/s/hub/h", "Blocked", targetScope="/s/hub/h") | {
                       "message": "Missing roles: namespace outbound MI -> Contributor on HUB"})
    setup = hub_setup()
    setup.plan, setup.mode = blocked, "plan"
    text = "\n".join(line.plain for line in setup.view())
    assert "  ⇄ IoT Hub:           h  LINK · IoT Hub system-assigned managed identity" in text
    assert "  ✗ Roles:             h  BLOCKED · role access for the link" in text
    assert "Missing roles: namespace outbound managed identity -> Contributor on HUB" in flat(text)
    assert "◇ Namespace outbound managed identity → Contributor, IoT Hub Data Contributor on h" in flat(text)
    assert blocked["items"][2]["id"] == "roles-hub-h"  # the plan itself (JSON, saved) keeps every role item


def test_subscription_picker_search_cache_and_repeated_marks():
    setup = scoped_setup([guided.SCOPE, EDGE_HUB, EDGE_HUB.upper()], SHARED_SUB, [guided.SCOPE], Back, [SHARED_HUB])
    setup._choose_existing_hubs([])
    pick = setup.prompter.calls[1]
    assert pick["caption"](1, 2, "shared") == "1 of 2 match"
    assert pick["caption"](0, 2, "zz") == "No subscription in this directory matches"
    assert setup.services.list_subscriptions.call_count == 1  # listed once, then reused
    assert setup.prompter.calls[2]["marked"] == [EDGE_HUB]  # the same Hub in two cases is one mark


def test_escape_from_save_stays_in_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup = hub_setup("save", Back, "back")
    setup.change_menu()
    assert setup.prompter.labels == ["Change:", "Save to:", "Change:"]
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------------------------
# The terminal's background: the probe, late answers and the washes
# --------------------------------------------------------------------------------------------

DARK_REPLY = "\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\\x1b[?62;22c"  # ST-terminated colour, then DA1
LIGHT_REPLY = "\x1b]11;rgb:ffff/ffff/ffff\x07\x1b[?62;22c"  # BEL-terminated colour
UNSUPPORTED_REPLY = "\x1b[?6c"  # DA1 only: no colour is coming
BACKGROUNDS = ["#ffffff", "#000000", "#1e1e1e", "#282c34", "#002b36", "#fdf6e3", "#f5f5f5", "#0c0c0c", "#300a24",
               "#2e3440", "#1d1f21", "#fafafa"]


def test_parse_background_reads_every_osc11_form_and_guesses_nothing():
    assert guided.parse_background("rgb:1e1e/1e1e/1e1e") == "#1e1e1e"
    assert guided.parse_background("rgb:f/8/0") == "#ff8800"
    assert guided.parse_background("rgb:FF/80/00") == "#ff8000"
    assert guided.parse_background("rgb:fff/000/800") == "#ff0080"
    assert guided.parse_background("rgba:ffff/ffff/ffff/0000") == "#ffffff"  # alpha ignored
    assert guided.parse_background("#1e1e1e") == "#1e1e1e" and guided.parse_background("#fff") == "#ffffff"
    assert guided.parse_background("#1e1e1e1e1e1e") == "#1e1e1e"
    for bad in ("", "#", "rgb:", "rgb:1e/1e", "rgb:12345/0/0", "rgb:gg/00/00", "rgb:/1/2", "rgba:ff/ff/ff",
                "#12345", "cmy:1/2/3"):
        assert guided.parse_background(bad) is None


def test_surface_tints_are_faint_theme_washes_that_keep_every_colour_readable(monkeypatch):
    for palette in ("truecolor", "256"):
        for background in BACKGROUNDS:
            tints = guided.surface_tints(background, palette)
            dark = guided.luminance(background) < guided.TINT_DARK
            ink = "#ffffff" if dark else "#000000"  # bold values use the terminal's own foreground
            assert tints.background == background
            for wash in (tints.focus, tints.surface):
                assert guided.TINT_SEEN <= guided.contrast(wash, background) <= guided.TINT_MOST  # seen, not loud
                assert (guided.luminance(wash) > guided.luminance(background)) is dark  # lifted dark, lowered light
                assert guided.contrast(ink, wash) >= 7
                assert all(guided.contrast(color, wash) >= 0.75 * guided.contrast(color, background)
                           for color in guided.RGB.values())  # labels, tags and matches keep their contrast
            if palette == "truecolor":
                assert (tints.rich_focus, tints.rich_surface) == (tints.focus, tints.surface)
                assert tints.focus != tints.surface  # the focused row leans bluer than the surface
            else:  # the same xterm entry for Rich (by index) and prompt_toolkit (by its exact colour)
                for rich, wash in ((tints.rich_focus, tints.focus), (tints.rich_surface, tints.surface)):
                    index = int(re.fullmatch(r"color\((\d+)\)", rich).group(1))
                    assert dict(guided.XTERM)[index] == wash and index != guided.xterm(background)[0]
            entries = dict(guided.XTERM)
            for role, color in guided.RGB.items():  # coloured text on a wash: 4.5:1 or better, measured
                ink, rich = tints.inks[role], tints.rich_inks[role]
                drawn = entries[int(rich[6:-1])] if rich.startswith("color(") else rich
                assert min(guided.contrast(ink, tints.focus), guided.contrast(ink, background)) >= 4.5
                assert guided.contrast(drawn, tints.surface) >= 4.5
                if palette == "truecolor" and guided.contrast(color, tints.surface) >= 4.5:
                    assert rich == color  # a colour that is already legible is left as it is
    black = guided.surface_tints("#000000", "truecolor")
    assert black.inks["accent"] == guided.RGB["accent"]  # 5:1 on black already
    for background in ("#1e1e1e", "#ffffff"):  # the plain accent falls short on both washes: it is moved, in hue
        tints = guided.surface_tints(background, "truecolor")
        assert guided.contrast(guided.RGB["accent"], tints.focus) < 4.5 and tints.inks["accent"] != guided.RGB["accent"]
        red, green, blue = (int(tints.inks["accent"][i:i + 2], 16) for i in (1, 3, 5))
        assert blue > green > red  # still the azure accent
    assert guided.surface_tints("#1e1e1e", "ansi") is None  # 16 themeable colours: nothing to compute against
    assert guided.surface_tints("#808080", "truecolor") is None  # mid-grey: no faint wash would show
    assert guided.xterm("#1e1e1e") == (234, "#1c1c1c") and guided.xterm("#ff0000") == (196, "#ff0000")
    monkeypatch.setattr(guided, "XTERM", [(16, "#000000"), (231, "#ffffff")])
    assert guided.surface_tints("#000000", "256") is None  # no entry between the background and loud


def _filtered(*chunks, outstanding=("osc", "da1")):
    replies = guided.TerminalReplies(outstanding)
    return replies, "".join(replies.feed(chunk) for chunk in chunks)


def test_terminal_replies_are_removed_whole_split_or_late_and_keys_survive_in_order():
    replies, keys = _filtered("ab" + DARK_REPLY + "cd")
    assert keys == "abcd" and replies.background == "#1e1e1e" and not replies.outstanding and not replies.held
    full = "x\x1b[A" + DARK_REPLY + "y"
    for cut in range(len(full) + 1):  # cut anywhere, even inside either answer or the arrow key
        replies, keys = _filtered(full[:cut], full[cut:])
        assert keys == "x\x1b[Ay" and replies.background == "#1e1e1e" and not replies.outstanding
    replies, keys = _filtered(*("é" + LIGHT_REPLY + "z"))  # one character per read, BEL terminator
    assert keys == "éz" and replies.background == "#ffffff"
    replies, keys = _filtered("\x1b[B" + UNSUPPORTED_REPLY + "n")  # no colour: DA1 alone ends the wait
    assert keys == "\x1b[Bn" and replies.background is None and not replies.outstanding
    replies, keys = _filtered("\x1b]11;rgb:1e1e/1e1e/1e1e\x07", "q", outstanding=("osc",))
    assert keys == "q" and replies.background == "#1e1e1e" and not replies.outstanding
    replies, keys = _filtered("k" + DARK_REPLY[:-4], outstanding=("osc", "da1"))
    assert keys == "k" and replies.outstanding == {"da1"} and replies.held == "\x1b[?62"  # a late DA1, part here
    assert replies.flush() == "" and replies.held  # a partial answer is not an Esc: it waits for the rest
    assert replies.feed(";22cm") == "m" and not replies.outstanding
    assert replies.feed(DARK_REPLY + "\x1b") == DARK_REPLY + "\x1b"  # nothing outstanding: a plain pass-through


def test_terminal_replies_release_the_users_escape_and_lookalike_keys():
    replies, keys = _filtered("\x1b")
    assert keys == "" and replies.flush() == "\x1b" and replies.flush() == ""  # a lone Esc, at the Esc timeout
    assert _filtered("\x1bx")[1] == "\x1bx"  # Alt+x
    replies, keys = _filtered("\x1b\x1b")
    assert keys == "\x1b" and replies.held == "\x1b"
    assert _filtered("\x1b]x")[1] == "\x1b]x"  # Alt+] then x
    assert _filtered("\x1b]11;rgb:1e!")[1] == "\x1b]11;rgb:1e!"  # not an answer after all: given back in order
    assert _filtered("\x1b[?1;2x")[1] == "\x1b[?1;2x"
    assert _filtered("\x1b[?6c", outstanding=("osc",))[1] == "\x1b[?6c"  # DA1 is only removed while it is due
    assert _filtered("\x1b]11;rgb:1e\x1bq")[1] == "\x1b]11;rgb:1e\x1bq"


def _prompt_app(monkeypatch):
    import prompt_toolkit.application

    apps = []
    base = prompt_toolkit.application.Application

    class Capture(base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            apps.append(self)

    monkeypatch.setattr(prompt_toolkit.application, "Application", Capture)
    return apps


def test_prompts_never_take_a_late_answer_as_keys_and_esc_still_goes_back(monkeypatch):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    apps = _prompt_app(monkeypatch)
    replies = guided.TerminalReplies()
    with create_pipe_input() as pipe:
        prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), replies=replies)
        assert prompter._input() is pipe  # Windows pipe inputs parse on send, not on read.
        pipe.send_text("adr-\x1b]11;rgb:1e1e/")  # the colour answer arrives late, split across reads
        timer = threading.Timer(0.4, pipe.send_text, ["1e1e/1e1e\x1b\\demo\r"])
        timer.start()
        try:
            assert prompter.ask("Namespace:", ()) == "adr-demo"  # never part of the name, never Back
        finally:
            timer.join()
        assert apps[0].ttimeoutlen == guided.LATE_ESCAPE and replies.outstanding == {"da1"}
        pipe.send_text("\x1b")
        with pytest.raises(BackRequested):  # the user's own Esc still means Back while an answer is due
            prompter.ask("Namespace:", ())
        pipe.send_text("\x1b[?62;22c\x1b[Bn\r")  # DA1 late, then the user's arrow key and text
        escape_timeout = guided.LATE_ESCAPE if replies.outstanding else 0.05
        assert prompter.confirm("CMS:", default=True) is False
        assert not replies.outstanding and apps[-1].ttimeoutlen == escape_timeout
        pipe.send_text("ok\r")
        assert prompter.ask("Name:", ()) == "ok" and apps[-1].ttimeoutlen == 0.05  # nothing due: the usual wait
        parser = pipe.vt100_parser
        replies.attach(pipe)
        assert getattr(parser, "adr_replies") is replies  # attached once per input, never wrapped twice
    guided.TerminalReplies().attach(object())  # an input without a vt100 parser is left as it is


def test_keys_typed_while_the_terminal_was_asked_reach_the_first_prompt_once():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), typed="adr-")
        pipe.send_text("demo\r")
        assert prompter.ask("Namespace:", ()) == "adr-demo"
        pipe.send_text("x\r")
        assert prompter.ask("Namespace:", ()) == "x" and prompter.typed == ""


def test_prompts_use_the_session_input_when_none_is_given(mocker):
    session = mocker.patch("prompt_toolkit.application.current.get_app_session")
    prompter = guided.TerminalPrompter(StringIO(), replies=guided.TerminalReplies())
    assert prompter._input() is session.return_value.input


@pytest.fixture
def pty_pair():
    pytest.importorskip("termios")
    import pty

    master, slave = pty.openpty()
    stdin = os.fdopen(slave, "rb", buffering=0)
    yield master, stdin
    stdin.close()
    os.close(master)


def _assert_terminal_settings(actual, expected, termios):
    # BSD sets PENDIN when restoring canonical input; it is pending-input state, not a saved setting.
    actual, expected = list(actual), list(expected)
    pending = getattr(termios, "PENDIN", 0)
    actual[3] &= ~pending
    expected[3] &= ~pending
    assert actual == expected


@pytest.mark.parametrize("pending", [0x4000, 0x20000000])
def test_terminal_restoration_ignores_only_pending_input_state(pending):
    termios = MagicMock(PENDIN=pending)
    before = [1, 2, 3, 8, 9600, 9600, [b"\x03"]]
    after = deepcopy(before)
    after[3] |= pending
    _assert_terminal_settings(after, before, termios)
    assert before[3] == 8 and after[3] == 8 | pending
    after[3] &= ~8
    with pytest.raises(AssertionError):
        _assert_terminal_settings(after, before, termios)


def test_probe_reads_the_answer_without_echo_and_keeps_what_was_typed(pty_pair):
    termios = pytest.importorskip("termios")

    master, stdin = pty_pair
    before = termios.tcgetattr(stdin.fileno())
    written = []

    def terminal(text):  # the terminal answers at once; the user had typed "ad" just before
        written.append(text)
        os.write(master, ("ad" + DARK_REPLY + "r").encode())

    replies, typed = guided.probe_background(stdin, terminal, timeout=2)
    assert written == [guided.BACKGROUND_QUERY] and typed == "adr" and replies.background == "#1e1e1e"
    assert not replies.outstanding and replies.terminal is None
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)
    replies, typed = guided.probe_background(stdin, lambda text: os.write(master, UNSUPPORTED_REPLY.encode()))
    assert replies.background is None and typed == ""
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)


def test_a_silent_terminal_costs_the_bounded_wait_and_echo_waits_for_the_late_answer(pty_pair):
    import select

    termios = pytest.importorskip("termios")

    master, stdin = pty_pair
    before = termios.tcgetattr(stdin.fileno())
    started = guided.time.monotonic()
    replies, typed = guided.probe_background(stdin, lambda text: None, timeout=0.1)
    assert 0.1 <= guided.time.monotonic() - started < 1 and typed == ""
    assert replies.outstanding == {"foreground", "osc", "da1"}
    during = termios.tcgetattr(stdin.fileno())
    assert not during[3] & termios.ECHO and during[3] & termios.ICANON  # no echo of a late answer; lines as usual
    assert replies.terminal == (stdin.fileno(), before)
    os.write(master, b"zz\n")  # typed after the last prompt, still unread when setup ends
    replies.close()
    assert replies.terminal is None
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)
    assert select.select([stdin], [], [], 1)[0] and os.read(stdin.fileno(), 64) == b"zz\n"  # left for the shell
    replies.close()  # once only

    replies, _ = guided.probe_background(stdin, lambda text: os.write(master, b"\x1b]11;#1e1e1e\x07"),
                                         timeout=0.1)
    assert replies.background == "#1e1e1e" and replies.outstanding == {"foreground", "da1"}
    replies.outstanding.clear()  # it came during the prompts
    replies.close()
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)
    with open(guided.__file__, encoding="utf-8") as source:
        assert "TIOCSTI" not in source.read()


def test_restoring_a_terminal_that_went_away_is_quiet_and_other_failures_surface(monkeypatch):
    termios = pytest.importorskip("termios")

    calls = []

    def gone(descriptor, when, settings):
        calls.append(settings)
        raise termios.error(errno.EIO, "Input/output error")

    monkeypatch.setattr(termios, "tcsetattr", gone)
    replies = guided.TerminalReplies()
    replies.terminal = (7, ["saved"])
    replies.close()
    assert calls == [["saved"]] and replies.terminal is None
    monkeypatch.setattr(termios, "tcsetattr", MagicMock(side_effect=termios.error(errno.EBADF, "Bad descriptor")))
    replies.terminal = (7, ["saved"])
    with pytest.raises(termios.error):
        replies.close()


def test_probe_needs_a_posix_terminal(monkeypatch):
    assert guided.probe_background(StringIO(), print) == (None, "")
    monkeypatch.setitem(sys.modules, "termios", None)
    assert guided.probe_background(StringIO(), print) == (None, "")
    assert guided.TerminalReplies().close() is None  # nothing was changed: nothing to restore


def test_same_terminal_compares_the_devices(pty_pair):
    import pty

    other_master, other = pty.openpty()
    try:
        assert guided.same_terminal(pty_pair[1], pty_pair[1])
        assert not guided.same_terminal(pty_pair[1], os.fdopen(other, "rb", buffering=0, closefd=False))
        assert guided.same_terminal(StringIO(), pty_pair[1])  # can't tell: assumed
    finally:
        os.close(other)
        os.close(other_master)


class _Stdin:
    def __init__(self, tty=True):
        self.tty = tty

    def isatty(self):
        return self.tty


def test_screen_probes_only_where_a_wash_can_be_shown(mocker, monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    mocker.patch.object(guided, "same_terminal", return_value=True)

    def answered(stdin, write):
        write(guided.BACKGROUND_QUERY)
        replies = guided.TerminalReplies()
        replies.feed(DARK_REPLY)
        return replies, "typed"

    probe = mocker.patch.object(guided, "probe_background", side_effect=answered)

    def make(system="truecolor", **options):
        stream = Tty()
        return guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=80, color_system=system),
                             motion=False, **options), stream

    out, stream = make()
    assert out.probe(_Stdin()) == "typed" and stream.getvalue() == guided.BACKGROUND_QUERY
    assert out.tints == guided.surface_tints("#1e1e1e", "truecolor") and out.replies.background == "#1e1e1e"
    assert make("256")[0].probe(_Stdin()) == "typed"
    assert probe.call_count == 2
    for screen_, stdin in ((make("standard")[0], _Stdin()), (make(plain=True)[0], _Stdin()), (make()[0], _Stdin(False))):
        assert screen_.probe(stdin) == "" and screen_.tints is None and screen_.replies is None
    guided.same_terminal.return_value = False
    assert make()[0].probe(_Stdin()) == ""
    guided.same_terminal.return_value = True
    monkeypatch.setenv("NO_COLOR", "1")
    assert make()[0].probe(_Stdin()) == ""
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert make()[0].probe(_Stdin()) == ""
    assert probe.call_count == 2  # every gate above asked nothing

    monkeypatch.setenv("TERM", "xterm-256color")
    probe.side_effect = lambda stdin, write: (guided.TerminalReplies(()), "")  # DA1 only: no colour
    silent, _ = make()
    assert silent.probe(_Stdin()) == "" and silent.tints is None and silent.replies is not None
    probe.side_effect = lambda stdin, write: (None, "")
    monkeypatch.setattr(guided.sys, "stdin", _Stdin())
    default, _ = make()
    assert default.probe() == "" and default.replies is None and probe.call_count == 4
    default.release()  # nothing asked: nothing to release
    silent.replies = MagicMock()
    silent.release()
    silent.replies.close.assert_called_once_with()


def test_a_real_run_asks_once_shares_the_answer_and_always_releases(mocker):
    screen_class = mocker.patch.object(guided, "Screen")
    made = screen_class.return_value
    made.probe.return_value = "typed"
    prompter = mocker.patch.object(guided, "TerminalPrompter")
    setup = mocker.patch.object(guided, "GuidedSetup")
    setup.return_value.run.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        guided.run_guided_setup("services", SUB)
    made.probe.assert_called_once_with()
    made.release.assert_called_once_with()
    kwargs = prompter.call_args.kwargs
    assert kwargs["typed"] == "typed" and kwargs["replies"] is made.replies and kwargs["tints"] is made.tints
    setup.return_value.run.side_effect = None
    given = MagicMock()
    assert guided.run_guided_setup("services", SUB, screen=given, prompter=MagicMock()) is setup.return_value.run()
    given.probe.assert_not_called()  # a caller's screen was set up by the caller
    given.release.assert_called_once_with()


def test_focused_row_alone_carries_one_faint_wash_of_a_steady_width():
    rows = [guided.Row("a", "hub-a", "rg-demo"), guided.Row("b", "hub-longer-name", "rg-demo")]
    for index in (0, 1):
        picker = guided.Picker(rows, focus_first=True)
        picker.index = index
        fragments = guided.list_fragments(picker, 80, focus="bg:#202c36")
        lines = "".join(text for _, text in fragments).split("\n")
        washed = [(style, text) for style, text in fragments if "bg:#202c36" in style]
        assert "".join(text for _, text in washed).strip().startswith(guided.POINTER + " " + rows[index].title)
        assert all(style.endswith("bg:#202c36") for style, _ in washed)  # after the row's own colours
        assert lines[index].index(guided.POINTER) == guided.INDENT + guided.MARK  # the pointer never moves
        assert len(lines[index].rstrip("\n")) == len(lines[index])
        start = guided.INDENT + guided.MARK - 1  # one cell of wash before the pointer, one after the longest row
        assert start + cell_len("".join(text for _, text in washed)) == len(lines[1 - index].rstrip()) + 1
        assert len(lines[index]) < 80 - 1  # never the terminal's last column
    plain_fragments = guided.list_fragments(picker, 80)
    assert not any("bg:" in style for style, _ in plain_fragments)
    assert "".join(text for _, text in plain_fragments) == "".join(
        text for _, text in guided.list_fragments(picker, 80, focus="")).rstrip() + ""
    for size in (32, 33):  # a row as wide as the terminal allows: the wash stops one column short of the edge
        narrow = guided.list_fragments(guided.Picker([guided.Row("x", "x" * size)], focus_first=True), 40,
                                       focus="bg:#202c36")
        assert cell_len("".join(text for style, text in narrow if "bg:" in style)) == 40 - guided.INDENT - guided.MARK


def test_focus_wash_settles_once_after_a_move_and_only_with_motion(monkeypatch):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    tints = guided.surface_tints("#1e1e1e", "truecolor")
    half = "bg:" + guided.mix(tints.background, tints.focus, guided.FOCUS_FROM)
    monkeypatch.setattr(guided, "FOCUS_SETTLE", 0.3)
    original = guided.list_fragments
    rows = [guided.Row("a", "hub-a"), guided.Row("b", "hub-b")]

    def run(motion, tinted):
        seen = []

        def recording(*args, **kwargs):
            seen.append(kwargs["focus"])
            return original(*args, **kwargs)

        monkeypatch.setattr(guided, "list_fragments", recording)
        with create_pipe_input() as pipe:
            prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), palette="truecolor",
                                               tints=tints if tinted else None, motion=motion)
            pipe.send_text("\x1b[B")
            timer = threading.Timer(0.6, pipe.send_text, ["\r"])
            timer.start()
            assert prompter.select("IoT Hub:", rows) == "b"
            timer.join()
        return seen

    moving = run(True, True)
    assert moving[0] == "bg:" + tints.focus and half in moving  # half strength just after the move …
    assert moving[-1] == "bg:" + tints.focus and moving.index(half) < len(moving) - 1  # … then full, and it stays
    assert set(run(False, True)) == {"bg:" + tints.focus}  # reduced motion: the full wash at once, no fade
    assert set(run(True, False)) == {""}  # no known background: the pointer and bold only


def test_focused_text_on_the_wash_is_native_or_legibly_coloured():
    from prompt_toolkit.styles import Style as PromptStyle

    assert not guided.focus_inks(None)
    for background in ("#1e1e1e", "#ffffff", "#282c34", "#fdf6e3"):
        tints = guided.surface_tints(background, "truecolor")
        inks = guided.focus_inks(tints)
        rows = [guided.Row("a", "hub-a", "rg-demo", "NEW"), guided.Row("b", "hub-b", "rg-demo", "REUSE")]
        picker = guided.Picker(rows, text="hub", focus_first=True)
        focus = "bg:" + tints.focus
        fragments = guided.list_fragments(picker, 80, marked={"a"}, focus=focus, inks=inks)
        style = PromptStyle.from_dict(guided.prompt_style("truecolor"))
        first = "".join(text for _, text in fragments).split("\n", maxsplit=1)[0]
        focused = [(fragment, text) for fragment, text in fragments if focus in fragment and text.strip()]
        assert "".join(text for _, text in focused).split() == first.split()  # the whole focused row is washed
        for fragment, text in focused:
            attrs = style.get_attrs_for_style_str(fragment)
            assert attrs.bgcolor == tints.focus[1:] and not attrs.reverse and not attrs.dim
            if text.strip() in ("-a", "rg-demo"):  # the name and the detail: the terminal's own foreground
                assert attrs.color == ""
            else:  # pointer, match, check, tag: their colours, at 4.5:1 or better on the wash
                assert guided.contrast("#" + attrs.color, tints.focus) >= 4.5, text
        other = [fragment for fragment, text in fragments if "hub-b" in text or text == "  REUSE"]
        assert other and not any("bg:" in fragment for fragment in other)  # other rows are untouched
        assert style.get_attrs_for_style_str("class:reuse").color == guided.RGB["reuse"][1:]


def test_the_prompt_passes_the_focus_inks_with_its_wash(monkeypatch):
    seen = []
    original = guided.list_fragments

    def recording(*args, **kwargs):
        seen.append(kwargs["inks"])
        return original(*args, **kwargs)

    monkeypatch.setattr(guided, "list_fragments", recording)
    tints = guided.surface_tints("#ffffff", "truecolor")
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        prompter = guided.TerminalPrompter(StringIO(), input=pipe, output=DummyOutput(), palette="truecolor",
                                           tints=tints)
        assert prompter.select("IoT Hub:", [guided.Row("a", "hub-a")]) == "a"
    assert seen and all(inks == guided.focus_inks(tints) for inks in seen)


def test_a_terminal_that_hangs_up_ends_the_probe_and_other_read_errors_surface(pty_pair, monkeypatch):
    termios = pytest.importorskip("termios")

    master, stdin = pty_pair
    before = termios.tcgetattr(stdin.fileno())
    os.write(master, b"x")
    monkeypatch.setattr(guided.os, "read", MagicMock(side_effect=OSError(errno.EIO, "EIO")))
    replies, typed = guided.probe_background(stdin, lambda text: None, timeout=1)
    assert typed == "" and replies.outstanding  # stopped at once, nothing guessed
    replies.close()
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)
    monkeypatch.setattr(guided.os, "read", MagicMock(side_effect=OSError(errno.EBADF, "EBADF")))
    with pytest.raises(OSError, match="EBADF"):
        guided.probe_background(stdin, lambda text: None, timeout=1)
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)  # restored on the way out


def test_every_way_out_of_the_probe_but_an_answer_restores_the_terminal_at_once(pty_pair, monkeypatch):
    import select

    termios = pytest.importorskip("termios")

    master, stdin = pty_pair
    before = termios.tcgetattr(stdin.fileno())

    def broken(text):
        raise OSError(errno.EIO, "query not written")

    with pytest.raises(OSError, match="query not written"):  # the query never reached the terminal
        guided.probe_background(stdin, broken, timeout=1)
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)

    waiting = MagicMock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(select, "select", waiting)
    with pytest.raises(KeyboardInterrupt):  # Ctrl+C while waiting for the answer
        guided.probe_background(stdin, lambda text: None, timeout=1)
    waiting.side_effect = None
    monkeypatch.undo()
    assert waiting.call_count == 1
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)

    monkeypatch.setattr(guided.os, "read", MagicMock(side_effect=KeyboardInterrupt))
    os.write(master, b"x")
    with pytest.raises(KeyboardInterrupt):  # Ctrl+C in the middle of reading it
        guided.probe_background(stdin, lambda text: None, timeout=1)
    guided.os.read.side_effect = None
    monkeypatch.undo()
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)

    applied, real = [], termios.tcsetattr

    def refused(descriptor, when, settings):  # the terminal refuses "echo off until the late answer"
        applied.append(settings)
        if len(applied) == 2:
            raise termios.error(errno.EINVAL, "refused")
        real(descriptor, when, settings)

    monkeypatch.setattr(termios, "tcsetattr", refused)
    with pytest.raises(termios.error, match="refused"):
        guided.probe_background(stdin, lambda text: None, timeout=0.05)
    monkeypatch.undo()
    assert len(applied) == 3
    _assert_terminal_settings(applied[-1], before, termios)
    _assert_terminal_settings(termios.tcgetattr(stdin.fileno()), before, termios)


def test_a_failing_probe_or_prompter_still_releases_the_terminal(mocker):
    screen_class = mocker.patch.object(guided, "Screen")
    made = screen_class.return_value
    setup = mocker.patch.object(guided, "GuidedSetup")
    made.probe.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):  # Ctrl+C during the background question
        guided.run_guided_setup("services", SUB)
    made.probe.side_effect = None
    made.release.assert_called_once_with()
    made.probe.return_value = ""
    mocker.patch.object(guided, "TerminalPrompter", side_effect=RuntimeError("no prompt"))
    with pytest.raises(RuntimeError, match="no prompt"):
        guided.run_guided_setup("services", SUB)
    assert made.release.call_count == 2 and not setup.called


def test_a_screen_without_washes_keeps_its_theme():
    out = screen(color="truecolor")
    themes = len(out.console._theme_stack._entries)
    out.tints = None
    assert len(out.console._theme_stack._entries) == themes and out.tints is None
    out.tints = guided.surface_tints("#1e1e1e", "truecolor")
    assert out.console.get_style(guided.LABEL_STYLE + guided.WASHED).color.triplet.hex == out.tints.rich_inks["label"]
    grounds = ("#707070", "#909090")  # mid-greys on both sides of the line: nothing reaches 4.5:1 on both
    assert guided.legible("#2f81c9", grounds, "truecolor") == ("#ffffff", "#ffffff")
    best = max(guided.XTERM, key=lambda entry: min(guided.contrast(entry[1], ground) for ground in grounds))
    assert guided.legible("#2f81c9", grounds, "256") == (best[1], f"color({best[0]})")


@pytest.mark.parametrize("background,foreground", [
    ("#1e1e1e", "#d4d4d4"), ("#ffffff", "#202020"),
    ("#282c34", "#abb2bf"), ("#fdf6e3", "#657b83"),
])
@pytest.mark.parametrize("palette", ["truecolor", "256"])
@pytest.mark.parametrize("width", [79, 87])
def test_mist_is_static_bounded_and_keeps_native_and_semantic_text_readable(background, foreground, palette, width):
    mist = guided.mist_surface(background, foreground, palette, width, 12)
    assert mist is not None
    assert len(mist.rows) == 14 and all(len(row) == width for row in mist.rows)
    native = guided.contrast(foreground, background)
    target = native if native < 4.5 else min(7, native * .88)
    grounds = {Color.parse(color).get_truecolor().hex for row in mist.rows[1:-1] for color in row}
    assert all(guided.contrast(foreground, ground) >= target for ground in grounds)
    for ink in list(mist.inks.values()) + [mist.quiet]:
        drawn = Color.parse(ink).get_truecolor().hex
        assert all(guided.contrast(drawn, ground) >= 4.5 for ground in grounds)
    if palette == "truecolor":
        assert len(grounds) > 8
    else:
        assert len(grounds) == 1 and all(color.startswith("color(") for row in mist.rows for color in row)
    assert guided.mist_surface(background, foreground, palette, width, 12) is mist


def test_mist_falls_back_without_guessing_or_lowering_already_low_dark_contrast():
    assert guided.mist_surface("#1e1e1e", "#444444", "truecolor", 87, 12) is None
    assert guided.mist_surface("#1e1e1e", "#d4d4d4", "ansi", 87, 12) is None
    assert guided.mist_surface("#1e1e1e", "#d4d4d4", "truecolor", 87, 0) is None


@pytest.mark.parametrize("columns", [80, 120])
def test_mist_paints_only_approval_cells_and_preserves_unicode_and_styles(monkeypatch, columns):
    from rich.text import Text

    monkeypatch.delenv("NO_COLOR", raising=False)
    out, _ = tty_screen(monkeypatch, columns=columns, color="truecolor")
    out.tints = guided.surface_tints("#1e1e1e", "truecolor")
    out.foreground = "#d4d4d4"
    body = out.fact_lines("DPS:", "温度-cafe\u0301", "S1 · australiaeast", tag="NEW", tag_style=guided.GOOD_BOLD)
    original = [row.copy() for row in body]
    rows = out.surface("Plan", Text("✦ 1 new", guided.GOOD_BOLD), body)
    assert rows[0].plain == "▄" * (out.width - 1)
    assert rows[-1].plain == "▀" * (out.width - 1)
    assert all(cell_len(row.plain) == out.width - 1 for row in rows)
    assert body == original
    text = rows[2]
    start = text.plain.index("温")
    for index in range(start, start + len("温度-cafe\u0301")):
        style = text.get_style_at_offset(out.console, index)
        assert style.bold and style.color is None and style.bgcolor is not None
    for index, character in enumerate(text.plain):
        style = text.get_style_at_offset(out.console, index)
        assert not style.dim
        if character.strip() and style.color:
            assert guided.contrast(style.color.get_truecolor().hex, style.bgcolor.get_truecolor().hex) >= 4.5
    raw = out._render(rows)
    assert "48;2;" in raw and not any(code in raw for code in ("\x1b[?1049h", "\x1b[2J", "\x1b[3J"))
    assert out.surface("Plan", Text("✦ 1 new", guided.GOOD_BOLD), body) == rows
    out.foreground = "#444444"
    assert out.surface("Plan", Text("✦ 1 new"), body) is None  # unsafe Mist also requests the frame fallback


def test_foreground_and_background_replies_are_filtered_at_every_split():
    foreground = "\x1b]10;rgb:d4d4/d4d4/d4d4\x1b\\"
    text = "ad" + foreground + DARK_REPLY + "r"
    for cut in range(len(text) + 1):
        replies, keys = _filtered(text[:cut], text[cut:], outstanding=("foreground", "osc", "da1"))
        assert keys == "adr" and replies.foreground == "#d4d4d4" and replies.background == "#1e1e1e"
        assert not replies.outstanding
    replies, keys = _filtered("\x1b]10;#202020\x07" + LIGHT_REPLY, outstanding=("foreground", "osc", "da1"))
    assert keys == "" and replies.foreground == "#202020" and replies.background == "#ffffff"
    assert _filtered(foreground)[1] == foreground  # not requested: ordinary input is not discarded


def test_probe_passes_both_terminal_colors_to_the_screen(mocker, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    mocker.patch.object(guided, "same_terminal", return_value=True)

    def answered(_stdin, write):
        write(guided.BACKGROUND_QUERY)
        replies = guided.TerminalReplies(("foreground", "osc", "da1"))
        replies.feed("\x1b]10;#d4d4d4\x07" + DARK_REPLY)
        return replies, "typed"

    mocker.patch.object(guided, "probe_background", side_effect=answered)
    stream = Tty()
    out = guided.Screen(stream, console=Console(file=stream, force_terminal=True, width=80, color_system="truecolor"))
    assert out.probe(_Stdin()) == "typed"
    assert stream.getvalue() == "\x1b]10;?\x1b\\\x1b]11;?\x1b\\\x1b[c"
    assert out.foreground == "#d4d4d4"
    assert out.tints == guided.surface_tints("#1e1e1e", "truecolor")


def test_attached_parser_sees_only_the_users_keys_and_a_lone_escape_at_flush():
    seen = []
    parser = MagicMock()
    parser.feed.side_effect = seen.append
    parser.flush.side_effect = lambda: seen.append("<flush>")
    source = MagicMock(vt100_parser=parser)
    replies = guided.TerminalReplies()
    replies.attach(source)
    parser.feed("a\x1b]11;rgb:0/0/0\x07")
    parser.flush()  # nothing held: only the parser's own flush
    parser.feed("\x1b")
    parser.flush()  # the user's Esc, released at its timeout
    parser.feed("\x1b[?6")
    parser.flush()  # part of an answer: kept back
    parser.feed("2c")
    assert seen == ["a", "<flush>", "", "\x1b", "<flush>", "", "<flush>", ""]
