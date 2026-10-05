# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

import pytest
from azure.cli.core.azclierror import FileOperationError

import azext_iot.iothub.providers.helpers.state_strings as messages
import azext_iot.iothub.providers.state as subject


@pytest.fixture()
def provider(mocker):
    result = subject.StateProvider.__new__(subject.StateProvider)
    result.hub_name = "myhub"
    result.target = {"name": "myhub"}
    result.login = None
    mocker.patch.object(
        result, "process_hub_to_dict", return_value={"devices": {"device1": {"identity": {}}}}
    )
    return result


@pytest.fixture(autouse=True)
def isolated_fallback_directory(tmp_path, mocker):
    mocker.patch.object(subject.tempfile, "tempdir", str(tmp_path))


def test_state_written_and_readable(tmp_path):
    state_file = tmp_path / "state.json"
    hub_state = {"devices": {"device1": {"identity": {}}}}

    subject._write_state_file(hub_state, str(state_file))

    assert json.loads(state_file.read_text(encoding="utf-8")) == hub_state
    assert list(tmp_path.iterdir()) == [state_file]


@pytest.mark.parametrize("operation", ["json.dump", "os.fsync", "os.replace"])
def test_existing_file_not_truncated_on_failure(tmp_path, mocker, operation):
    state_file = tmp_path / "state.json"
    state_file.write_text("previous good state", encoding="utf-8")
    mocker.patch(f"azext_iot.iothub.providers.state.{operation}", side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        subject._write_state_file({"a": 1}, str(state_file))

    assert state_file.read_text(encoding="utf-8") == "previous good state"
    assert list(tmp_path.iterdir()) == [state_file]


def test_fallback_preserves_state(tmp_path):
    hub_state = {"devices": {"device1": {"identity": {}}}}

    fallback_path = subject._write_fallback_state_file(hub_state, "myhub")

    assert fallback_path
    with open(fallback_path, encoding="utf-8") as state_file:
        assert json.load(state_file) == hub_state
    assert len(list(tmp_path.iterdir())) == 1
    if os.name != "nt":
        assert os.stat(fallback_path).st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires additional Windows privileges")
@pytest.mark.parametrize("write_fails", [False, True])
def test_atomic_write_preserves_destination_symlink(tmp_path, mocker, write_fails):
    target = tmp_path / "target.json"
    target.write_text("previous state", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    if write_fails:
        mocker.patch.object(subject.os, "replace", side_effect=OSError("replace failed"))
        with pytest.raises(OSError, match="replace failed"):
            subject._write_state_file({"new": "state"}, str(link))
        assert target.read_text(encoding="utf-8") == "previous state"
    else:
        subject._write_state_file({"new": "state"}, str(link))
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": "state"}

    assert link.is_symlink()
    assert set(tmp_path.iterdir()) == {target, link}


def test_non_regular_destination_keeps_streaming_behavior(mocker):
    create_temporary_file = mocker.patch.object(subject.tempfile, "mkstemp")

    subject._write_state_file({"a": 1}, os.devnull)

    create_temporary_file.assert_not_called()


@pytest.mark.parametrize("fallback", [False, True])
def test_interrupted_write_removes_incomplete_file(tmp_path, mocker, fallback):
    mocker.patch.object(subject.json, "dump", side_effect=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        if fallback:
            subject._write_fallback_state_file({"a": 1}, "myhub")
        else:
            subject._write_state_file({"a": 1}, str(tmp_path / "state.json"))

    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("operation", ["tempfile.mkstemp", "json.dump", "os.fsync"])
def test_failed_fallback_leaves_no_partial_file(tmp_path, mocker, operation):
    mocker.patch(f"azext_iot.iothub.providers.state.{operation}", side_effect=OSError("no temp space"))

    assert subject._write_fallback_state_file({"a": 1}, "myhub") is None
    assert not list(tmp_path.iterdir())


def test_save_state_success(provider, tmp_path, mocker):
    state_file = tmp_path / "state.json"
    fallback = mocker.patch.object(subject, "_write_fallback_state_file")

    provider.save_state(str(state_file), hub_aspects=["devices"])

    assert json.loads(state_file.read_text(encoding="utf-8")) == provider.process_hub_to_dict.return_value
    provider.process_hub_to_dict.assert_called_once_with(provider.target, ["devices"])
    fallback.assert_not_called()


@pytest.mark.parametrize("path_form", ["trailing-separator", "dot", "missing-parent", "file-parent"])
def test_invalid_path_cannot_bypass_overwrite_confirmation(provider, tmp_path, path_form):
    state_file = tmp_path / "state.json"
    state_file.write_text("previous good state", encoding="utf-8")
    paths = {
        "trailing-separator": str(state_file) + os.sep,
        "dot": str(state_file) + os.sep + ".",
        "missing-parent": str(tmp_path / "missing" / ".." / "state.json"),
        "file-parent": str(state_file) + os.sep + ".." + os.sep + "state.json",
    }

    with pytest.raises(FileOperationError):
        provider.save_state(paths[path_form], hub_aspects=["devices"])

    assert state_file.read_text(encoding="utf-8") == "previous good state"


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires additional Windows privileges")
@pytest.mark.parametrize("target", ["missing/../state.json", "state.json/../state.json", "state.json/"])
def test_invalid_symlink_target_cannot_overwrite_another_file(provider, tmp_path, target):
    state_file = tmp_path / "state.json"
    state_file.write_text("previous good state", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(FileOperationError):
        provider.save_state(str(link), hub_aspects=["devices"])

    assert state_file.read_text(encoding="utf-8") == "previous good state"
    assert link.is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX filename-length regression")
def test_long_valid_basename_is_written(tmp_path):
    state_file = tmp_path / ("s" * 250)
    state_file.write_text("previous good state", encoding="utf-8")

    subject._write_state_file({"new": "state"}, str(state_file))

    assert json.loads(state_file.read_text(encoding="utf-8")) == {"new": "state"}
    assert list(tmp_path.iterdir()) == [state_file]


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires additional Windows privileges")
def test_dangling_symlink_with_valid_parent_creates_target(tmp_path):
    target = tmp_path / "new.json"
    link = tmp_path / "link.json"
    link.symlink_to(target)

    subject._write_state_file({"new": "state"}, str(link))

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": "state"}
    assert link.is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires additional Windows privileges")
def test_relative_dangling_symlink_chain_creates_target(tmp_path):
    directory = tmp_path / "subdirectory"
    directory.mkdir()
    target = directory / "new.json"
    indirect_link = tmp_path / "indirect.json"
    indirect_link.symlink_to("subdirectory/new.json")
    link = tmp_path / "link.json"
    link.symlink_to("indirect.json")

    subject._write_state_file({"new": "state"}, str(link))

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": "state"}
    assert link.is_symlink()
    assert indirect_link.is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires additional Windows privileges")
def test_symlink_cycle_fails_without_replacing_links(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.symlink_to("second.json")
    second.symlink_to("first.json")

    with pytest.raises(OSError):
        subject._write_state_file({"new": "state"}, str(first))

    assert first.is_symlink()
    assert second.is_symlink()
    assert set(tmp_path.iterdir()) == {first, second}


@pytest.mark.parametrize("missing_parent", [False, True])
def test_save_state_reports_recovered_data(provider, tmp_path, mocker, missing_parent):
    state_file = tmp_path / "missing" / "state.json" if missing_parent else tmp_path / "state.json"
    if not missing_parent:
        mocker.patch.object(subject, "_write_state_file", side_effect=PermissionError("destination is read-only"))

    with pytest.raises(FileOperationError) as error:
        provider.save_state(str(state_file), hub_aspects=["devices"])

    fallback_files = list(tmp_path.glob("iot-hub-state-myhub-*.json"))
    assert len(fallback_files) == 1
    fallback_file = fallback_files[0]
    assert str(state_file) in str(error.value)
    assert str(fallback_file) in str(error.value)
    assert json.loads(fallback_file.read_text(encoding="utf-8")) == provider.process_hub_to_dict.return_value
    assert not state_file.exists()


@pytest.mark.parametrize("missing_parent", [False, True])
def test_save_state_reports_failure_when_recovery_unavailable(provider, tmp_path, mocker, missing_parent):
    state_file = str(tmp_path / "state.json")
    write_error = FileNotFoundError("missing directory") if missing_parent else PermissionError("read-only")
    mocker.patch.object(subject, "_write_state_file", side_effect=write_error)
    fallback = mocker.patch.object(subject, "_write_fallback_state_file", return_value=None)

    with pytest.raises(FileOperationError) as error:
        provider.save_state(state_file, hub_aspects=["devices"])

    expected = (
        messages.FILE_NOT_FOUND_ERROR.format(state_file)
        if missing_parent else messages.SAVE_STATE_WRITE_ERROR.format(state_file, write_error)
    )
    assert str(error.value) == expected
    fallback.assert_called_once_with(provider.process_hub_to_dict.return_value, provider.hub_name)


def test_collection_failure_does_not_claim_recovery(provider, tmp_path, mocker):
    provider.process_hub_to_dict.side_effect = IndexError("missing ARM resource")
    write = mocker.patch.object(subject, "_write_state_file")
    fallback = mocker.patch.object(subject, "_write_fallback_state_file")

    with pytest.raises(IndexError, match="missing ARM resource"):
        provider.save_state(str(tmp_path / "state.json"), hub_aspects=["devices"])

    write.assert_not_called()
    fallback.assert_not_called()
