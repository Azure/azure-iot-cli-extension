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

import pytest

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


@pytest.mark.parametrize("posix_lock", [True, False])
def test_concurrent_phases_share_one_serialized_install_per_runner_token(tmp_path, monkeypatch, posix_lock):
    if not posix_lock:
        monkeypatch.setattr(_locked_install, "fcntl", None)
    elif _locked_install.fcntl is None:
        pytest.skip("POSIX file locks are unavailable on this platform")
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


def test_explicit_candidate_is_installed_once_independent_of_phase_tokens(tmp_path, monkeypatch, mocker):
    wheel = tmp_path / "candidate.whl"
    wheel.write_bytes(b"offline-wheel")
    monkeypatch.setenv("azext_iot_candidate_wheel", str(wheel))
    monkeypatch.setattr("sys.argv", ["install", str(tmp_path / "extension")])
    install = mocker.patch.object(_locked_install, "install", return_value=0)
    tokens = []
    for token in ("phase-one", "phase-two"):
        monkeypatch.setenv(_locked_install.TOKEN_ENV, token)
        assert _locked_install.main() == 0
        tokens.append(install.call_args.args[1])
        assert install.call_args.kwargs["source"] == str(wheel)
    assert tokens[0] == tokens[1] and tokens[0].startswith("candidate:")
    wheel.unlink()
    with pytest.raises(SystemExit):
        _locked_install.main()
