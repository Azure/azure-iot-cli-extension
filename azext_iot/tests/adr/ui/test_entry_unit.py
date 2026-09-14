# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""CLI entry point behaviour (design doc step 0)."""

import pytest
from azure.cli.core.azclierror import CLIInternalError

from azext_iot.adr.ui import entry
from azext_iot.adr.ui.entry import MIN_REFRESH_INTERVAL_SEC, adr_ui_launch


class _RecordingApp:
    """Stands in for the real application so nothing tries to own the terminal."""

    last = None

    def __init__(self, **kwargs):
        type(self).last = kwargs
        self.ran = False

    def run(self):
        self.ran = True


@pytest.fixture
def recording_app(monkeypatch):
    import azext_iot.adr.ui.app as app_module

    monkeypatch.setattr(app_module, "RadrApp", _RecordingApp)
    _RecordingApp.last = None
    return _RecordingApp


def test_launch_passes_scope_through(recording_app):
    adr_ui_launch(
        cmd=object(),
        resource_group_name="my-rg",
        namespace_name="my-ns",
        read_only=True,
    )
    passed = recording_app.last
    assert passed["resource_group_name"] == "my-rg"
    assert passed["namespace_name"] == "my-ns"
    assert passed["read_only"] is True


def test_refresh_interval_is_clamped_to_the_floor(recording_app):
    adr_ui_launch(cmd=object(), refresh_interval=1)
    assert recording_app.last["refresh_interval"] == MIN_REFRESH_INTERVAL_SEC


def test_refresh_interval_above_the_floor_is_respected(recording_app):
    adr_ui_launch(cmd=object(), refresh_interval=30)
    assert recording_app.last["refresh_interval"] == 30


def test_missing_refresh_interval_uses_the_floor(recording_app):
    adr_ui_launch(cmd=object())
    assert recording_app.last["refresh_interval"] == MIN_REFRESH_INTERVAL_SEC


def test_launch_silences_the_provider_console(recording_app):
    """PR2: provider spinners write to stdout and would corrupt the screen."""
    from azext_iot.adr.providers.base import console

    console.quiet = False
    try:
        adr_ui_launch(cmd=object())
        assert console.quiet is True
    finally:
        console.quiet = False


def test_silence_helper_is_idempotent():
    from azext_iot.adr.providers.base import console

    try:
        entry._silence_provider_console()
        entry._silence_provider_console()
        assert console.quiet is True
    finally:
        console.quiet = False


def test_missing_framework_reports_an_actionable_error(monkeypatch):
    """A source install without the dependency must explain itself, not traceback."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "azext_iot.adr.ui.app":
            raise ModuleNotFoundError(
                "No module named 'textual'",
                name="textual",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(CLIInternalError, match="textual"):
        adr_ui_launch(cmd=object())


def test_unrelated_ui_import_failure_is_not_misreported(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "azext_iot.adr.ui.app":
            raise ModuleNotFoundError(
                "No module named 'broken_dependency'",
                name="broken_dependency",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ModuleNotFoundError, match="broken_dependency"):
        adr_ui_launch(cmd=object())


def test_refresh_floor_matches_the_store():
    """One definition of the floor: a mismatch would let the CLI accept what the store rejects."""
    from azext_iot.adr.ui.core.store import MIN_INTERVAL_SEC

    assert MIN_REFRESH_INTERVAL_SEC == MIN_INTERVAL_SEC
