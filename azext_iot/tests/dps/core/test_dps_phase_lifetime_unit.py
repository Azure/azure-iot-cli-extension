# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline controller-reference regressions, including actual xdist session teardown."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import runpy
import sys
import textwrap
from types import SimpleNamespace

from filelock import FileLock
import pytest

from azext_iot.tests.dps import _phase, _phase_receipts as receipts
from azext_iot.tests.dps import conftest as fixtures

ROOT = Path(__file__).resolve().parents[4]
UID = "d" * 32
SUB = "11111111-2222-3333-4444-555555555555"
GROUP = "offline-lifetime"


class LocalResources:
    """Tiny filesystem fake; real fixture state locks and ownership receipts remain in use."""

    def __init__(self, root):
        self.root = Path(root)

    def paths(self, uid, kind):
        base = self.root / f"state-{uid}-{kind}"
        return str(base) + ".lock", str(base) + ".json"

    def find(self, name):
        path = self.root / f"resource-{name}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def event(self, action, name):
        with FileLock(str(self.root / "events.lock")):
            with (self.root / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"action": action, "name": name, "pid": os.getpid()}) + "\n")

    def events(self):
        path = self.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def create(self, uid, kind):
        name = f"unit-lifetime-{kind}"
        receipts.before_create(name, GROUP, uid, kind)
        resource_type = "IotHubs" if kind == "hub" else "provisioningServices"
        resource = {
            "id": f"/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/Microsoft.Devices/{resource_type}/{name}",
            "name": name, "tags": {"intTest": "true", "runUid": uid, "kind": kind},
            "properties": {"provisioningState": "Succeeded"},
        }
        with (self.root / f"resource-{name}.json").open("x", encoding="utf-8") as stream:
            json.dump(resource, stream)
        self.event("create", name)
        receipts.after_create(name, resource)
        return name, resource

    def delete(self, name):
        if receipts.settings() and not receipts.before_delete(name, self.find(name)):
            return
        self.event("delete", name)
        (self.root / f"resource-{name}.json").unlink()
        receipts.after_delete(name)


def _session(worker=False):
    config = SimpleNamespace(workerinput={"testrunuid": "not-the-explicit-uid"}) if worker else SimpleNamespace()
    return SimpleNamespace(config=config)


@pytest.fixture
def local(tmp_path, monkeypatch, mocker):
    directory = tmp_path / "receipts"
    directory.mkdir()
    for key, value in (
        (receipts.DIRECTORY_ENV, str(directory)), (receipts.RUN_UID_ENV, UID),
        (receipts.SUBSCRIPTION_ENV, SUB), (receipts.RESOURCE_GROUP_ENV, GROUP), (_phase.PHASE_ENV, _phase.REGULAR),
    ):
        monkeypatch.setenv(key, value)
    store = LocalResources(tmp_path)
    mocker.patch.object(fixtures, "_state_paths", side_effect=store.paths)
    for name in ("_find_dps_by_name", "_find_hub_by_name"):
        mocker.patch.object(fixtures, name, side_effect=store.find)
    for name in ("_delete_dps", "_delete_hub"):
        mocker.patch.object(fixtures, name, side_effect=store.delete)
    mocker.patch.object(fixtures.cli, "invoke", side_effect=AssertionError("No CLI calls in lifetime tests"))
    return store


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_late_consumer_reuses_single_creation_until_controller_releases(local, monkeypatch, phase, kind):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    uid = fixtures._get_run_uid(_session())
    assert uid == UID + ("-service-sas" if phase == _phase.SERVICE_SAS else "")
    assert fixtures._get_run_uid(_session(worker=True)) == uid
    original = fixtures._shared_acquire(uid, kind, local.create, local.find)
    assert fixtures._shared_acquire(uid, kind, local.create, local.find) == original
    fixtures._shared_release(uid, kind, local.delete)
    fixtures._shared_release(uid, kind, local.delete)
    assert fixtures._read_state(local.paths(uid, kind)[1])["refcount"] == 1
    assert fixtures._shared_acquire(uid, kind, local.create, local.find) == original
    fixtures._shared_release(uid, kind, local.delete)
    assert [event["action"] for event in local.events()] == ["create"]
    # The fix must reserve lifetime, never weaken the exclusive mutation guard.
    with pytest.raises(RuntimeError, match="repeat"):
        receipts.before_create(original["name"], GROUP, uid, kind)
    fixtures.pytest_sessionfinish(_session())
    assert [event["action"] for event in local.events()] == ["create", "delete"]
    assert local.find(original["name"]) is None
    assert fixtures._read_state(local.paths(uid, kind)[1]) is None
    assert (local.root / "receipts" / f"deleted-{kind}.json").is_file()


@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_remaining_worker_reference_prevents_controller_premature_deletion(local, kind):
    resource = fixtures._shared_acquire(UID, kind, local.create, local.find)
    fixtures._shared_acquire(UID, kind, local.create, local.find)
    fixtures._shared_release(UID, kind, local.delete)
    fixtures.pytest_sessionfinish(_session())
    assert fixtures._read_state(local.paths(UID, kind)[1])["refcount"] == 1
    assert local.find(resource["name"]) == resource
    assert len(local.events()) == 1
    fixtures._shared_release(UID, kind, local.delete)
    assert [event["action"] for event in local.events()] == ["create", "delete"]


@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_nonphase_lifetime_keeps_last_worker_cleanup_without_controller_reference(local, monkeypatch, kind):
    for name in (receipts.DIRECTORY_ENV, receipts.RUN_UID_ENV, receipts.SUBSCRIPTION_ENV, receipts.RESOURCE_GROUP_ENV):
        monkeypatch.delenv(name)
    uid = fixtures._get_run_uid(_session())
    resource = fixtures._shared_acquire(uid, kind, local.create, local.find)
    assert fixtures._read_state(local.paths(uid, kind)[1])["refcount"] == 1
    fixtures.pytest_sessionfinish(_session())
    assert fixtures._read_state(local.paths(uid, kind)[1])["refcount"] == 1
    fixtures._shared_release(uid, kind, local.delete)
    assert local.find(resource["name"]) is None
    assert fixtures._read_state(local.paths(uid, kind)[1]) is None


def test_worker_sessionfinish_does_not_release_controller_reference(local, mocker):
    fixtures._shared_acquire(UID, "nh", local.create, local.find)
    release = mocker.spy(fixtures, "_release_phase_fixture")
    fixtures.pytest_sessionfinish(_session(worker=True))
    release.assert_not_called()
    assert fixtures._read_state(local.paths(UID, "nh")[1])["refcount"] == 2
    assert len(local.events()) == 1


@pytest.mark.parametrize("failure", [None, "h", "nh", "hub"])
def test_controller_attempts_all_owned_cleanup_dps_before_hub_and_propagates_error(local, mocker, failure):
    for kind in ("h", "nh", "hub"):
        fixtures._shared_acquire(UID, kind, local.create, local.find)
        fixtures._shared_release(UID, kind, local.delete)
    attempted = []

    def delete(name):
        kind = local.find(name)["tags"]["kind"]
        attempted.append(kind)
        if kind == failure:
            raise RuntimeError(f"synthetic cleanup failure: {kind}")
        local.delete(name)

    mocker.patch.object(fixtures, "_delete_dps", side_effect=delete)
    mocker.patch.object(fixtures, "_delete_hub", side_effect=delete)
    with pytest.raises(RuntimeError, match="synthetic cleanup failure") if failure else nullcontext():
        fixtures.pytest_sessionfinish(_session())
    assert attempted == ["h", "nh", "hub"]
    for kind in ("h", "nh", "hub"):
        assert (local.find(f"unit-lifetime-{kind}") is not None) == (kind == failure)
        if kind == failure:
            assert fixtures._read_state(local.paths(UID, kind)[1])["refcount"] == 1


@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_controller_cleanup_rechecks_ownership_and_never_deletes_foreign_resource(local, kind):
    resource = fixtures._shared_acquire(UID, kind, local.create, local.find)
    fixtures._shared_release(UID, kind, local.delete)
    resource["tags"]["runUid"] = "foreign-owner"
    (local.root / f"resource-{resource['name']}.json").write_text(json.dumps(resource), encoding="utf-8")
    fixtures.pytest_sessionfinish(_session())
    assert local.find(resource["name"]) == resource
    assert [event["action"] for event in local.events()] == ["create"]


CHILD_CONFTEST = """
import builtins,json,os,socket,webbrowser
from pathlib import Path
def deny(*args, **kwargs): raise AssertionError('lifetime proof forbids network/auth/CLI/interactive calls')
socket.socket.connect = socket.socket.connect_ex = deny
socket.create_connection = socket.getaddrinfo = deny
builtins.input = webbrowser.open = deny
import requests
requests.sessions.Session.request = deny
from azure.cli.core._profile import Profile
Profile.get_raw_token = Profile.get_login_credentials = Profile.login = deny
from azure.cli.core import util
util.check_connectivity = lambda *args, **kwargs: False
util.get_latest_version_from_ame_storage = lambda *args, **kwargs: None
from azext_iot.common.embedded_cli import EmbeddedCLI
EmbeddedCLI.invoke = deny
import pytest
from lifetime_parent_dependency import AVAILABLE
assert AVAILABLE
from azext_iot.tests.dps import conftest as fixtures, _phase_runtime
from azext_iot.tests.dps.core.test_dps_phase_lifetime_unit import LocalResources
root = Path(__file__).parent
store = LocalResources(root)
fixtures._state_paths = store.paths
fixtures._find_dps_by_name = fixtures._find_hub_by_name = store.find
fixtures._delete_dps = fixtures._delete_hub = store.delete
class ActualTeardown:
    pytest_sessionfinish = staticmethod(fixtures.pytest_sessionfinish)
def pytest_configure(config):
    config.pluginmanager.register(ActualTeardown(), 'actual-dps-controller-teardown')
def pytest_sessionstart(session):
    _phase_runtime.start_worker(session)
    if not hasattr(session.config, 'workerinput'):
        (root/'controller.json').write_text(json.dumps({'pid':os.getpid()}))
@pytest.hookimpl(hookwrapper=True)
def pytest_sessionfinish(session):
    yield
    if hasattr(session.config, 'workerinput'):
        (root/('finished-'+str(os.getpid()))).write_text('actual hook completed')
@pytest.fixture(scope='session')
def owned(request):
    uid = fixtures._get_run_uid(request)
    result = fixtures._shared_acquire(uid, 'nh', store.create, store.find)
    yield result
    fixtures._shared_release(uid, 'nh', store.delete)
"""


@pytest.mark.timeout(60)
@pytest.mark.skipif(sys.platform != "linux", reason="Bounded actual xdist process proof uses Linux process groups and /proc.")
def test_real_xdist_late_file_reuses_no_hub_until_actual_controller_sessionfinish(tmp_path, mocker, monkeypatch):
    directory = tmp_path / "receipts"
    directory.mkdir()
    dependency_path = tmp_path / "parent-only-imports"
    dependency_path.mkdir()
    (dependency_path / "lifetime_parent_dependency.py").write_text("AVAILABLE = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(dependency_path))
    profile = tmp_path / "private-cli"
    profile.mkdir(mode=0o700)
    (profile / "config").write_text(
        "[core]\ncheck_version=no\ncollect_telemetry=no\n[extension]\nuse_dynamic_install=no\n", encoding="utf-8",
    )
    (profile / "config").chmod(0o600)
    (tmp_path / "conftest.py").write_text(textwrap.dedent(CHILD_CONFTEST), encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts=\n", encoding="utf-8")
    (tmp_path / "test_early.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_early(owned):\n"
        "    assert owned['name']=='unit-lifetime-nh'\n"
        "    Path('early-pid').write_text(str(os.getpid()))\n", encoding="utf-8",
    )
    (tmp_path / "test_late.py").write_text(
        "import os,time\nfrom pathlib import Path\n"
        "def test_late(request):\n"
        "    deadline=time.monotonic()+15\n"
        "    while not Path('early-pid').exists() or not Path('finished-'+Path('early-pid').read_text()).exists():\n"
        "        assert time.monotonic()<deadline, 'early worker did not finish before late acquisition'\n"
        "        time.sleep(.02)\n"
        "    assert int(Path('early-pid').read_text())!=os.getpid()\n"
        "    assert request.getfixturevalue('owned')['name']=='unit-lifetime-nh'\n"
        "    Path('late-pid').write_text(str(os.getpid()))\n", encoding="utf-8",
    )
    # Azure CLI adds extension dependency directories at runtime, outside the interpreter's site-packages.
    import_paths = dict.fromkeys([str(ROOT), *(os.path.abspath(path) for path in sys.path)])
    environment = dict(
        os.environ, PYTHONPATH=os.pathsep.join(import_paths), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        AZURE_CONFIG_DIR=str(profile),
        AZURE_TEST_RUN_LIVE="False", AZURE_CORE_COLLECT_TELEMETRY="0", AZURE_CORE_CHECK_VERSION="no",
        AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no", azext_iot_testrg=GROUP,
        azext_iot_dps_phase_receipts=str(directory), azext_iot_dps_run_uid=UID,
        azext_iot_dps_test_subscription=SUB, azext_iot_dps_test_resource_group=GROUP,
        azext_iot_dps_test_phase=_phase.SERVICE_SAS,
    )
    command = [
        sys.executable, "-m", "pytest", "-p", "xdist.plugin", "-n", "2", "--dist=loadfile", "--max-worker-restart=0",
        "--rootdir", str(tmp_path), "--confcutdir", str(tmp_path), "-c", str(tmp_path / "pytest.ini"),
        "-q", str(tmp_path / "test_early.py"), str(tmp_path / "test_late.py"),
    ]
    runner = runpy.run_path(str(ROOT / "scripts/run_dps_phases.py"))
    mocker.patch.dict(runner["child"].__globals__, READ_SECONDS=1)
    # The runner retains its owned process-group kill/wait bound. No venv or installs.
    processes = runner["child"].__globals__["subprocess"]
    original = processes.Popen

    def launch(*args, **kwargs):
        return original(*args, cwd=tmp_path, **kwargs)

    mocker.patch.object(processes, "Popen", side_effect=launch)
    try:
        result = runner["child"](command, environment, tmp_path / "output.log", runtime=25, cleanup=8)
    finally:
        import shutil
        shutil.rmtree(profile)
    diagnostic = (tmp_path / "output.log").read_text(encoding="utf-8")[-4096:]
    assert result["exit_code"] == 0 and not result["timed_out"] and not result["interrupted"], diagnostic
    controller = json.loads((tmp_path / "controller.json").read_text())["pid"]
    early = int((tmp_path / "early-pid").read_text())
    late = int((tmp_path / "late-pid").read_text())
    assert early != late and controller not in (early, late)
    assert LocalResources(tmp_path).events() == [
        {"action": "create", "name": "unit-lifetime-nh", "pid": early},
        {"action": "delete", "name": "unit-lifetime-nh", "pid": controller},
    ]
    assert len(list(directory.glob("owned-*.json"))) == 1
    assert (directory / "deleted-nh.json").exists()
    assert not list(tmp_path.glob("resource-*.json")) and not list(tmp_path.glob("state-*.json"))
    for pid in (controller, early, late):
        assert not Path(f"/proc/{pid}").exists()
