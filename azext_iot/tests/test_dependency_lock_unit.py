# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

import json
from pathlib import Path
import runpy

import pytest


@pytest.fixture
def lock(monkeypatch, tmp_path):
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/dependency_lock.py"))
    for name, value in {
        "BUILD_BUILDID": "12", "SYSTEM_DEFINITIONID": "147", "BUILD_SOURCEVERSION": "a" * 40,
    }.items():
        monkeypatch.setenv(name, value)
    wheel = tmp_path / "candidate.whl"
    wheel.write_bytes(b"immutable candidate")
    return module, wheel


def snapshot(module, wheel, version="4.2.10"):
    return {
        "schema": 1, "identity": module["identity"]("DPS-3.13", wheel),
        "environments": {
            "main": {"filelock": {"version": version, "metadata": "b" * 64}},
            "extension": {
                "azure-iot": {"version": "1.0.0", "metadata": "c" * 64},
                "azure-storage-blob": {"version": "12.29.0", "metadata": "d" * 64},
            },
        },
    }


def test_retry_restores_separate_constraints_without_resolving_candidate_from_index(lock, tmp_path):
    module, wheel = lock
    saved = tmp_path / "history/dependencies-DPS-3.13-1"
    saved.mkdir(parents=True)
    module["write"](saved / "lock.json", snapshot(module, wheel))
    output = tmp_path / "restored"
    module["restore"](saved.parent, output, "DPS-3.13", wheel, ["main", "extension"], 2)
    assert (output / "main.txt").read_text() == "filelock==4.2.10\n"
    assert (output / "extension.txt").read_text() == "azure-storage-blob==12.29.0\n"


@pytest.mark.parametrize("failure", ["missing", "wheel", "identity", "conflict"])
def test_retry_rejects_missing_or_changed_snapshot(lock, tmp_path, failure):
    module, wheel = lock
    history = tmp_path / "history"
    history.mkdir()
    value = snapshot(module, wheel)
    if failure != "missing":
        saved = history / "dependencies-DPS-3.13-1"
        saved.mkdir()
        if failure == "identity":
            value["identity"]["BUILD_BUILDID"] = "13"
        module["write"](saved / "lock.json", value)
    if failure == "wheel":
        wheel.write_bytes(b"different candidate")
    if failure == "conflict":
        second = history / "dependencies-DPS-3.13-2"
        second.mkdir()
        module["write"](second / "lock.json", snapshot(module, wheel, "4.2.11"))
    with pytest.raises(ValueError):
        module["restore"](history, tmp_path / "restored", "DPS-3.13", wheel, ["main", "extension"], 2)


def test_capture_rejects_drift_without_overwriting_original(lock, tmp_path, monkeypatch):
    module, wheel = lock
    output = tmp_path / "snapshot"
    output.mkdir()
    original = snapshot(module, wheel)
    module["write"](output / "lock.json", original)
    extension = tmp_path / "extension"
    extension.mkdir()
    calls = iter([
        json.dumps({"filelock": {"version": "4.2.11", "metadata": "b" * 64}}),
        json.dumps(original["environments"]["extension"]),
    ])
    monkeypatch.setattr(module["subprocess"], "check_output", lambda *args, **kwargs: next(calls))
    with pytest.raises(ValueError, match="Restored dependencies differ"):
        module["capture"](output, "DPS-3.13", wheel, {"main": "python"}, {"extension": str(extension)})
    assert module["read"](output / "lock.json") == original


def test_target_inventory_records_metadata_and_rejects_unrestorable_origins(lock, tmp_path):
    module, _ = lock
    metadata_dir = tmp_path / "extension/filelock-4.2.10.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text("Name: filelock\nVersion: 4.2.10\n", encoding="utf-8")
    inventory = module["package_inventory"](metadata_dir.parent)
    assert inventory["filelock"]["version"] == "4.2.10"
    assert len(inventory["filelock"]["metadata"]) == 64
    (metadata_dir / "direct_url.json").write_text('{"url":"https://example.invalid/package.whl"}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-index dependency filelock"):
        module["package_inventory"](metadata_dir.parent)
