# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from configparser import ConfigParser
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace
import time

from azext_iot.tests import _locked_install


def _recorder(returncode=0, delay=0.0):
    calls, active, peak, guard = [], [0], [0], Lock()

    def run(command, check):
        assert check is False
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(delay)
        calls.append(command)
        with guard:
            active[0] -= 1
        return SimpleNamespace(returncode=returncode)

    return run, calls, peak


def test_concurrent_phases_share_one_serialized_install_per_runner_token(tmp_path):
    run, calls, peak = _recorder(delay=0.05)
    target = tmp_path / "extensions" / "azure-iot"
    barrier = Barrier(3)
    results = []

    def phase():
        barrier.wait()
        results.append(_locked_install.install(target, "runner-token", run_process=run))

    threads = [Thread(target=phase) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [0, 0, 0]
    assert len(calls) == 1 and peak[0] == 1
    assert calls[0][1:] == ["-m", "pip", "install", "-U", "--target", str(target), str(_locked_install.ROOT)]


def test_new_runner_token_reinstalls_and_failed_install_is_not_marked(tmp_path):
    target = tmp_path / "azure-iot"
    failed, failed_calls, _ = _recorder(returncode=1)
    assert _locked_install.install(target, "first", run_process=failed) == 1
    run, calls, _ = _recorder()
    assert _locked_install.install(target, "first", run_process=run) == 0
    assert _locked_install.install(target, "first", run_process=run) == 0
    assert _locked_install.install(target, "second", run_process=run) == 0
    assert len(failed_calls) == 1 and len(calls) == 2


def test_standalone_use_without_token_always_installs(tmp_path, monkeypatch):
    run, calls, _ = _recorder()
    for _ in range(2):
        assert _locked_install.install(tmp_path / "azure-iot", None, run_process=run) == 0
    assert len(calls) == 2
    assert not (tmp_path / "azure-iot.install-token").exists()


def test_only_dps_uses_the_locked_install():
    config = ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[2] / "tox.ini")
    commands = [line.strip() for line in
                config["testenv:{Central,ADT,DPS,HubControl,HubData,ADU,ADR}-int"]["commands"].splitlines()]
    assert "!DPS: pip install -U --target {envsitepackagesdir}/azure-cli-extensions/azure-iot ." in commands
    assert ("DPS: python {toxinidir}/azext_iot/tests/_locked_install.py "
            "{envsitepackagesdir}/azure-cli-extensions/azure-iot") in commands
