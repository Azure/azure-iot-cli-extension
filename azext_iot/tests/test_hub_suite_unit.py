# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Selection regression tests: no live collection, credentials or Azure resources."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from azext_iot.tests import _hub_suite_manifest as manifest
from azext_iot.tests import _hub_suite_plugin as plugin

ROOT = Path(manifest.__file__).resolve().parents[2]


def test_complete_behavior_ownership_and_phase_membership(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cases = manifest.contract()
    preview = any(case.capability == "preview" for case in cases)
    assert len(cases) == (81 if preview else 78)
    control = manifest.nodes("HubControl", "regular")
    entra = manifest.nodes("HubData", "entra")
    sas = manifest.nodes("HubData", "sas")
    assert (len(control), len(entra), len(sas)) == (28, 44 if preview else 42, 8 if preview else 6)
    assert len(set(entra) & set(sas)) == (2 if preview else 0)
    assert not set(control) & (set(entra) | set(sas))
    exceptions = {case.node for case in cases if case.exclusion}
    assert set(control) | set(entra) | set(sas) | exceptions == set(manifest.inventory())
    assert len(exceptions) == (3 if preview else 2)
    assert all(case.group and case.protocol and case.auth and case.dependencies for case in cases)
    assert manifest.phases("HubData") == ("entra", "sas")
    assert manifest.phases("HubControl") == ("regular",)
    assert json.loads(json.dumps(manifest.manifest("HubData", "entra")))["expected"] == list(entra)


def test_sas_exact_order_and_existing_normal_skip_contract():
    tree = ast.parse((ROOT / manifest.PREFIX / "_sas_phase.py").read_text(encoding="utf-8"))
    # Read the safe literal expressions, not the Azure-heavy module.
    values = {}

    def literal(node):
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal(node.left) + literal(node.right)
        if isinstance(node, ast.Tuple):
            return tuple(literal(item) for item in node.elts)
        return ast.literal_eval(node)

    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("ROOT", "MESSAGING", "NODES"):
                values[name] = literal(node.value)
    assert manifest.nodes("HubData", "sas") == values["NODES"]
    skipped = [case for case in manifest.contract() if case.normal_skip]
    assert len(skipped) == 6
    assert all(case.phases == ("sas",) for case in skipped)
    for case in skipped:
        filename, _, method = case.node.split("::")
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == method)
        assert any("not sas_phase_enabled()" in ast.unparse(mark) for mark in function.decorator_list)


def _checkout(tmp_path, capability="base"):
    constants = tmp_path / "azext_iot/constants.py"
    constants.parent.mkdir(parents=True)
    version = "2026-10-01-preview" if capability == "preview" else "2026-03-01-preview"
    constants.write_text(f'IOTHUB_PREVIEW_API_VERSION = "{version}"\n', encoding="utf-8")
    modules = {}
    for case in manifest.CASES:
        if case.capability not in ("base", capability):
            continue
        parts = case.node.split("::")
        modules.setdefault(parts[0], {}).setdefault(parts[1] if len(parts) == 3 else "", []).append(parts[-1])
    for name, classes in modules.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = ""
        for cls, methods in classes.items():
            if cls:
                text += f"class {cls}:\n"
            text += "".join(("    " if cls else "") + f"def {method}(): pass\n" for method in methods)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_child_capability_is_not_optional_file_existence(tmp_path):
    root = _checkout(tmp_path, "preview")
    assert len(manifest.contract(root)) == 81
    assert len(manifest.nodes("HubData", "entra", root)) == 44
    assert len(manifest.nodes("HubData", "sas", root)) == 8
    with pytest.raises(ValueError, match="not enabled"):
        manifest.nodes("HubData", "linked-metadata", root)
    assert len(manifest.nodes("HubData", "linked-metadata", root, linked_metadata=True)) == 1
    (root / manifest.PREFIX / "devices/test_hub_preview_int.py").unlink()
    with pytest.raises(ValueError, match="missing="):
        manifest.contract(root)


@pytest.mark.parametrize("damage", ["new", "missing", "duplicate", "unknown-api"])
def test_static_inventory_fails_closed(tmp_path, damage):
    root = _checkout(tmp_path)
    path = root / manifest.PREFIX / "tls13/test_tls13_int.py"
    text = path.read_text(encoding="utf-8")
    if damage == "new":
        text += "\ndef test_unknown_case(): pass\n"
    elif damage == "missing":
        text = ""
    elif damage == "duplicate":
        text += "\ndef test_gwv2_target_uses_service_hostname(): pass\n"
    else:
        (root / "azext_iot/constants.py").write_text('IOTHUB_PREVIEW_API_VERSION = "unknown"\n', encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        manifest.nodes("HubControl", "regular", root)


def _reports():
    return {"one": {stage: ["passed"] for stage in ("setup", "call", "teardown")}}


@pytest.mark.parametrize("damage", [
    "missing", "extra", "duplicate", "skip", "failure", "xfail", "rerun",
    "teardown", "no-call", "cancel", "incomplete", "exit",
])
def test_receipt_gate_fails_closed(damage):
    collected, reports, status, finished = ["one"], _reports(), 0, True
    if damage == "missing":
        collected = []
    elif damage == "extra":
        collected.append("other")
    elif damage == "duplicate":
        collected.append("one")
    elif damage in ("skip", "failure", "xfail"):
        reports["one"]["call"] = [damage]
    elif damage == "rerun":
        reports["one"]["call"].append("passed")
    elif damage == "teardown":
        reports["one"]["teardown"] = ["failed"]
    elif damage == "no-call":
        del reports["one"]["call"]
    elif damage == "cancel":
        status = 2
    elif damage == "incomplete":
        finished = False
    else:
        status = 1
    assert plugin.result_errors(["one"], collected, reports, status, finished)
    assert not plugin.result_errors(["one"], ["one"], _reports(), 0, True)


def test_receipt_is_exclusive_and_teardown_failure_changes_exit(tmp_path):
    path = tmp_path / "receipt.json"
    runtime = plugin.PhaseReceipt("HubData", "entra", ("one",), path, "nonce")
    with pytest.raises(FileExistsError):
        plugin.PhaseReceipt("HubData", "entra", ("one",), path, "new-nonce")
    assert not json.loads(path.read_text())["finished"]
    runtime.data["collected"] = ["one"]
    for stage in ("setup", "call", "teardown"):
        runtime.pytest_runtest_logreport(SimpleNamespace(
            nodeid="one", when=stage, outcome="failed" if stage == "teardown" else "passed",
        ))
    session = SimpleNamespace(exitstatus=0)
    hook = runtime.pytest_sessionfinish(session, 0)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(excinfo=None))
    receipt = json.loads(path.read_text())
    assert session.exitstatus == 1
    assert receipt["runId"] == "nonce"
    assert receipt["errors"]
    assert receipt["cleanup"] == {"pytestTeardown": "incomplete-or-failed", "resourceAbsence": "not-attested"}


@pytest.mark.parametrize("option", ["keyword", "markexpr", "deselect", "reruns", "numprocesses", "collectonly", "lf"])
def test_preimport_selection_rejects_filters(option):
    config = SimpleNamespace(args=["one"], getoption=lambda name, default=None: 1 if name == option else default)
    with pytest.raises(pytest.UsageError):
        plugin.validate_args(config, ("one",))


def test_preimport_selection_rejects_broad_arguments():
    config = SimpleNamespace(args=[manifest.PREFIX])
    with pytest.raises(pytest.UsageError, match="exact ordered"):
        plugin.validate_args(config, manifest.nodes("HubData", "entra"))


@pytest.mark.parametrize("mode", ["pass", "skip", "teardown", "expansion", "broad", "auth-leak"])
def test_real_plugin_early_selection_and_receipt(mode, tmp_path):
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    body = (
        "import pytest\nfrom pathlib import Path\nimport unittest\n"
        "Path('imported').touch()\n"
        "class TestUnselected(unittest.TestCase):\n"
        "    def __init__(self, *args): raise AssertionError('unselected constructor')\n"
        "    def test_never(self): raise AssertionError('unselected test')\n"
        "@pytest.fixture(autouse=True)\n"
        "def cleanup():\n    yield\n"
        + ("    raise AssertionError('cleanup failure')\n" if mode == "teardown" else "")
        + ("@pytest.mark.parametrize('value', [1, 2])\n" if mode == "expansion" else "")
        + ("def test_required(value):\n" if mode == "expansion" else "def test_required():\n")
        + ("    pytest.skip('blocked prerequisite')\n" if mode == "skip" else "    pass\n")
    )
    (tmp_path / "test_synthetic.py").write_text(body, encoding="utf-8")
    script = r'''
import socket
import sys
from types import SimpleNamespace
import urllib3
def forbidden(*args, **kwargs):
    raise AssertionError("Offline plugin proof attempted network")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.getaddrinfo = forbidden
from azext_iot.tests import _hub_suite_manifest as manifest
expected = ("test_synthetic.py::test_required",)
manifest.nodes = lambda *args, **kwargs: expected
manifest.contract = lambda: (SimpleNamespace(
    node=expected[0], suite="HubData", group="http-service", protocol=("https",),
    auth=("service:login",), dependencies=("hub",),
),)
import pytest
selected = ["test_synthetic.py"] if sys.argv[1] == "broad" else list(expected)
sys.exit(pytest.main([
    "-p", "azext_iot.tests._hub_suite_plugin", "-c", "pytest.ini",
    "--rootdir", ".", "--confcutdir", ".", "-q", *selected,
]))
'''
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *(os.path.abspath(path) for path in sys.path)])),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        AZEXT_IOT_HUB_SUITE="HubData", AZEXT_IOT_HUB_PHASE="entra",
        AZEXT_IOT_HUB_RUN_ID="nonce", AZEXT_IOT_HUB_RECEIPT=str(tmp_path / "receipt.json"),
        azext_iot_hub_auth_phase="local-auth" if mode == "auth-leak" else "regular",
    )
    result = subprocess.run(
        [sys.executable, "-c", script, mode], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    if mode in ("broad", "auth-leak"):
        assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
        assert not (tmp_path / "imported").exists()
        assert not (tmp_path / "receipt.json").exists()
    else:
        assert (tmp_path / "receipt.json").exists(), result.stdout + result.stderr
        receipt = json.loads((tmp_path / "receipt.json").read_text())
        assert (result.returncode == 0) == (mode == "pass"), result.stdout + result.stderr
        assert (not receipt["errors"]) == (mode == "pass")
        assert receipt["finished"]
        if mode != "expansion":
            assert receipt["collected"] == ["test_synthetic.py::test_required"]
        if mode == "skip":
            assert receipt["reports"]["test_synthetic.py::test_required"]["call"] == ["skipped"]


@pytest.mark.parametrize("suite,phase", [
    ("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas"), ("exceptions", "excluded"),
])
def test_guarded_offline_expanded_membership(suite, phase, tmp_path):
    """Real fresh pytest collection, denying constructors, CLI, tokens and sockets."""
    script = r'''
import json
import os
import socket
import sys
import webbrowser
import urllib3
blocked = []
def forbidden(*args, **kwargs):
    blocked.append(True)
    raise AssertionError("Guarded collection attempted constructor/CLI/token/network work")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.socket.bind = forbidden
socket.socket.sendto = forbidden
socket.getaddrinfo = forbidden
webbrowser.open = forbidden
from azure.cli.core._profile import Profile
Profile.get_raw_token = forbidden
Profile.get_login_credentials = forbidden
from azure.cli.core import util
util.check_connectivity = lambda *args, **kwargs: False
util.get_latest_version_from_ame_storage = lambda *args, **kwargs: None
from azext_iot.common.embedded_cli import EmbeddedCLI
EmbeddedCLI.invoke = forbidden
from azext_iot.tests.iothub import IoTLiveScenarioTest
IoTLiveScenarioTest.__init__ = forbidden
from azext_iot.tests import _hub_suite_manifest as manifest
import pytest
expected = (tuple(case.node for case in manifest.contract() if not case.phases)
            if sys.argv[1] == "exceptions" else manifest.nodes(sys.argv[1], sys.argv[2]))
class Proof:
    def pytest_collection_finish(self, session):
        assert not blocked
        assert tuple(item.nodeid for item in session.items) == expected
        print("EXACT_EXPANDED=" + json.dumps(list(expected)))
sys.exit(pytest.main([
    "-c", "setup.cfg", "--rootdir", str(manifest.ROOT), "--confcutdir", str(manifest.ROOT),
    "--collect-only", "-q", "-o", "addopts=", "-o", "log_cli=false", *expected,
], plugins=[Proof()]))
'''
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *(os.path.abspath(path) for path in sys.path)])),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        AZURE_CONFIG_DIR=str(tmp_path / "profile"), AZURE_TEST_RUN_LIVE="False",
        azext_iot_testrg="unit-rg", azext_iot_hub_auth_phase="local-auth" if phase == "sas" else "regular",
        azext_iot_hubsas_subscription="subscription", azext_iot_hubsas_receipt=str(tmp_path / "sas.json"),
        azext_iot_testhub="", azext_iot_teststorageaccount="", azext_iot_teststoragecontainer="",
    )
    result = subprocess.run(
        [sys.executable, "-c", script, suite, phase], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=60, check=False,
    )
    if phase == "sas" and sys.platform not in ("linux", "darwin"):
        assert result.returncode == pytest.ExitCode.USAGE_ERROR
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        line = next(line for line in result.stdout.splitlines() if line.startswith("EXACT_EXPANDED="))
        expected = ([case.node for case in manifest.contract() if not case.phases]
                    if suite == "exceptions" else list(manifest.nodes(suite, phase)))
        assert json.loads(line.partition("=")[2]) == expected
