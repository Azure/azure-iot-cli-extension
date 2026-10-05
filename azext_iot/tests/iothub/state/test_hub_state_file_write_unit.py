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
